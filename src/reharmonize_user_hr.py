"""Re-harmonize Cal DIG sub-pairs from user-provided HR
(v1.2 + v1.2.1 addenda).

Driven by ``reports/user_hr_approved_mapping.yaml``:

  settings:
    hr_target_gsd_m: 2.0
    downsample_kernel: average     # used when native pixel < 2 m
    reproject_kernel: cubic         # used when native pixel == 2 m
    target_crs: EPSG:26910
    base_dir: <absolute path under data_root/user-provided-cal-dig>

  pairs:                            # existing CMGDS-replacement pairs
    <pair_id>:
      hr: [<file1>, ...]            # >1 entry => mosaic before warp

  new_pairs:                        # pairs with no CMGDS ancestor
    <pair_id>:
      hr: [<file>]
      terrain_class: <vocab>

  dropped: [<pair_id>, ...]         # remove from manifest; no CMGDS fallback
  rejected: [<pair_id>, ...]        # stay rejected (LR coverage hole)
  unused: [<filename>, ...]         # informational

For every active pair (existing or new):

  1. Resolve list of HR source paths. If >1, mosaic in EPSG:32610 before warp.
  2. **Single warp** EPSG:32610 → EPSG:26910 AT 2 m resolution. Kernel:
       - input finer than 2 m → ``average`` (area-weighted downsample)
       - input already 2 m   → ``cubic``  (datum reprojection only)
       - never ``nearest``.
     (v1.2.1 §2: do NOT compound interpolation by reprojecting first then
     downsampling separately.)
  3. Compute HR∩LR overlap polygon. If overlap < ``pair_qa.min_overlap_area_km2``,
     reject the pair (writes the row with `coreg_status='reject'` for new
     pairs; raises an error for existing pairs since CMGDS already had overlap).
  4. Clip both rasters to the overlap, write footprint.geojson.
  5. **Re-solve** coregistration from scratch — never reuse CMGDS dx/dy/dz.
  6. Run v1.1 §A QA (PSR / eig_ratio / peak_agrees / overlay PNG).
  7. Upsert manifest row with provenance fields:
     hr_source_type='user_provided', hr_local_path=<first source>,
     hr_superseded_doi='10.5066/P97QM7NF' (existing) or '' (new),
     hr_superseded_reason, native_gsd, resample_kernel, etc.

Drop list: remove from manifest entirely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import rioxarray  # noqa: F401
import xarray as xr
import yaml
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.merge import merge as rio_merge
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import shape
from shapely.ops import unary_union

from . import coregister as cor
from . import qc
from .config import Config
from .download import sha256_file
from .manifest import ManifestRow, drop as drop_pair, load as load_manifest, upsert


log = logging.getLogger(__name__)


SUPERSEDED_DOI = "10.5066/P97QM7NF"
SUPERSEDED_REASON = "baked-in NN reprojection criss-cross artifact (v1.2 addendum)"
NEW_PAIR_REASON = "no CMGDS ancestor; user-provided HR added per v1.2.1 §4"


_RESAMPLING_MAP = {
    "average": Resampling.average,
    "cubic": Resampling.cubic,
    "bilinear": Resampling.bilinear,
    "nearest": Resampling.nearest,   # only declared so we can refuse it
}


@dataclass
class ReharmResult:
    pair_id: str
    user_files: list[str]
    native_gsd_m: float
    resample_kernel: str
    horiz_offset_m: float
    vert_offset_m: float
    psr: float
    eig_ratio: float
    peak_agrees: bool
    coreg_status: str
    overlap_area_km2: float
    harmonized_hr: str
    harmonized_lr: str
    overlay_path: str
    rejected_reason: str = ""


@dataclass
class ReharmReport:
    results: list[ReharmResult]
    dropped: list[str]
    rejected: list[str]
    rejection_reasons: dict[str, str]
    luciachica_iou: dict[str, dict[str, float]]


# ---------- helpers ----------

def _open(path: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(path, masked=True)
    if da.ndim == 3 and da.sizes.get("band") == 1:
        da = da.squeeze("band", drop=True)
    return da


def _load_lr_canonical(cfg: Config) -> Path:
    cand = list((cfg.raw_dir / "cal_dig_morro_bay").glob(
        "lr_Cal_DIG_I_Bathymetry_10m_extracted/Cal_DIG_I_Bathymetry_10m.tif"
    ))
    if not cand:
        raise FileNotFoundError("canonical Cal DIG LR mosaic not found")
    return cand[0]


def _valid_polygon_from_path(path: Path, target_crs: str | None = None):
    with rasterio.open(path) as ds:
        arr = ds.read(1, masked=True)
        v = (~arr.mask).astype("uint8") if hasattr(arr, "mask") else (arr != ds.nodata).astype("uint8")
        polys = [shape(g) for g, val in shapes(v, mask=v.astype(bool), transform=ds.transform) if val == 1]
        poly = unary_union(polys)
        src_crs = ds.crs.to_string()
    if target_crs is None or str(src_crs) == str(target_crs):
        return poly, src_crs
    gs = gpd.GeoSeries([poly], crs=src_crs).to_crs(target_crs)
    return gs.iloc[0], target_crs


def _valid_polygon_xr(da: xr.DataArray):
    arr = np.asarray(da.values)
    mask = np.isfinite(arr).astype("uint8")
    if mask.sum() == 0:
        return None
    polys = [shape(g) for g, v in shapes(mask, mask=mask.astype(bool), transform=da.rio.transform()) if v == 1]
    return unary_union(polys)


# ---------- core: mosaic + single warp ----------

def _mosaic_in_native_crs(hr_paths: list[Path], scratch_dir: Path) -> tuple[Path, str, float, bool]:
    """Mosaic 2+ HR tiles in their native CRS to a temp GeoTIFF on scratch.

    Returns (mosaic_path, native_crs_str, native_pixel_m, is_disjoint).
    The is_disjoint flag is True when the merged footprint has an interior
    gap larger than ~10% of the bounding box — surfaced for human review.
    """
    sources = [rasterio.open(p) for p in hr_paths]
    try:
        # Verify shared CRS + comparable pixel sizes
        crs_set = {s.crs.to_string() for s in sources}
        if len(crs_set) > 1:
            raise RuntimeError(f"mosaic sources must share a CRS; got {crs_set}")
        native_crs = crs_set.pop()
        px_set = {round(abs(s.transform.a), 4) for s in sources}
        if len(px_set) > 1:
            log.warning("mosaic sources have mixed pixel sizes %s; using nearest-pixel merge", px_set)
        native_px = min(px_set)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        out_path = scratch_dir / ("mosaic_" + "_".join(p.stem for p in hr_paths)[:100] + ".tif")
        # Use untiled writing for the intermediate mosaic — tiled blocks must
        # be multiples of 16 and the merged output may not satisfy that at
        # edge tiles. The harmonized hr.tif is rewritten via rioxarray later.
        rio_merge(
            sources, dst_path=str(out_path),
            dst_kwds={"compress": "DEFLATE", "tiled": False, "BIGTIFF": "IF_SAFER"},
            nodata=sources[0].nodata,
            mem_limit=512,
        )
    finally:
        for s in sources:
            s.close()
    # Disjointness check
    indiv_polys = []
    for p in hr_paths:
        poly, _ = _valid_polygon_from_path(p)
        indiv_polys.append(poly)
    union = unary_union(indiv_polys)
    bbox = union.envelope
    gap_frac = max(0.0, (bbox.area - union.area) / bbox.area)
    is_disjoint = gap_frac > 0.10
    return out_path, native_crs, float(native_px), is_disjoint


def _single_warp_to_2m(
    src_path: Path,
    target_crs: str,
    target_gsd_m: float,
    kernel_for_downsample: str,
    kernel_for_reproject: str,
    fill: float,
    out_path: Path,
) -> tuple[str, str, float]:
    """One reproject+resample step: chooses kernel based on native GSD.

    Returns (kernel_used, native_crs_str, native_gsd_m).
    """
    with rasterio.open(src_path) as src:
        native_crs = src.crs.to_string()
        native_gsd = float(abs(src.transform.a))
        # Pick kernel per v1.2.1 §2. Use a 1% relative tolerance: rasters whose
        # native pixel rounds to the target GSD (e.g. 2.000135 m vs 2.0 m) are
        # treated as already-at-target and get the reproject-only kernel.
        ratio = native_gsd / float(target_gsd_m)
        if ratio < 0.99:
            kernel = kernel_for_downsample
        elif ratio <= 1.01:
            kernel = kernel_for_reproject
        else:
            raise RuntimeError(
                f"{src_path.name}: native GSD {native_gsd:.3f} m is coarser than "
                f"target {target_gsd_m} m by >1%; refusing to upsample"
            )
        if kernel == "nearest":
            raise RuntimeError("nearest-neighbour reprojection is forbidden (v1.2.1 §2)")
        resampling = _RESAMPLING_MAP[kernel]

        # Build target transform / dims
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src.crs, target_crs,
            src.width, src.height, *src.bounds,
            resolution=target_gsd_m,
        )
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": target_crs,
            "transform": dst_transform,
            "width": dst_w,
            "height": dst_h,
            "nodata": fill,
            "dtype": "float32",
            "compress": "DEFLATE",
            "tiled": True,
            "BIGTIFF": "IF_SAFER",
        })
        with rasterio.open(out_path, "w", **kwargs) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=dst_transform, dst_crs=target_crs,
                src_nodata=src.nodata, dst_nodata=fill,
                resampling=resampling,
                num_threads=2,
            )
    return kernel, native_crs, native_gsd


# ---------- top-level per-pair flow ----------

def _harmonize_pair(
    *,
    cfg: Config,
    pair_id: str,
    user_hr_paths: list[Path],
    lr_path: Path,
    settings: dict[str, Any],
    is_new_pair: bool,
    terrain_class: str | None,
) -> ReharmResult:
    short = pair_id.split("__", 1)[1]
    out_dir = cfg.harmonized_dir / "cal_dig_morro_bay" / short
    out_dir.mkdir(parents=True, exist_ok=True)
    fill = float(cfg.nodata["fill_value"])
    target_crs = settings["target_crs"]
    target_gsd = float(settings["hr_target_gsd_m"])
    k_down = settings["downsample_kernel"]
    k_rep = settings["reproject_kernel"]

    # 1+2. Mosaic if needed, then single-warp to 2 m EPSG:26910.
    if len(user_hr_paths) == 0:
        raise RuntimeError(f"[{pair_id}] no HR source files")
    is_disjoint = False
    if len(user_hr_paths) == 1:
        mosaic_input = user_hr_paths[0]
        scratch_temp = None
    else:
        log.info("[%s] mosaicking %d HR tiles in native CRS", pair_id, len(user_hr_paths))
        scratch_temp = cfg.data_root / "scratch_mosaic" / short
        mosaic_input, _native_crs, _native_px, is_disjoint = _mosaic_in_native_crs(
            user_hr_paths, scratch_temp,
        )
        if is_disjoint:
            log.warning("[%s] mosaic footprint has interior gap >10%% of bbox", pair_id)

    warped_path = out_dir / "hr_warped.tif"
    log.info("[%s] single-warp -> %s @ %s m", pair_id, target_crs, target_gsd)
    kernel_used, native_crs, native_gsd = _single_warp_to_2m(
        mosaic_input, target_crs=target_crs, target_gsd_m=target_gsd,
        kernel_for_downsample=k_down, kernel_for_reproject=k_rep,
        fill=fill, out_path=warped_path,
    )

    # 3. HR∩LR overlap
    hr_t = _open(warped_path)
    lr = _open(lr_path)
    hr_poly = _valid_polygon_xr(hr_t)
    lr_poly = _valid_polygon_xr(lr)
    if hr_poly is None or lr_poly is None:
        raise RuntimeError(f"[{pair_id}] empty HR or LR valid region")
    overlap = hr_poly.intersection(lr_poly)
    if overlap.is_empty:
        if is_new_pair:
            return ReharmResult(
                pair_id=pair_id, user_files=[str(p) for p in user_hr_paths],
                native_gsd_m=native_gsd, resample_kernel=kernel_used,
                horiz_offset_m=0.0, vert_offset_m=0.0, psr=float("nan"),
                eig_ratio=float("nan"), peak_agrees=False,
                coreg_status="reject",
                overlap_area_km2=0.0,
                harmonized_hr="", harmonized_lr="",
                overlay_path="",
                rejected_reason="HR∩LR is empty",
            )
        raise RuntimeError(f"[{pair_id}] HR∩LR is empty")
    overlap_gs = gpd.GeoSeries([overlap], crs=target_crs)
    overlap_area_km2 = float(overlap_gs.area.iloc[0]) / 1e6
    min_overlap = float(cfg.pair_qa["min_overlap_area_km2"])
    if overlap_area_km2 < min_overlap:
        if is_new_pair:
            log.info("[%s] overlap %.3f km^2 < %.2f km^2 -> reject (no LR)",
                     pair_id, overlap_area_km2, min_overlap)
            return ReharmResult(
                pair_id=pair_id, user_files=[str(p) for p in user_hr_paths],
                native_gsd_m=native_gsd, resample_kernel=kernel_used,
                horiz_offset_m=0.0, vert_offset_m=0.0, psr=float("nan"),
                eig_ratio=float("nan"), peak_agrees=False,
                coreg_status="reject",
                overlap_area_km2=overlap_area_km2,
                harmonized_hr="", harmonized_lr="",
                overlay_path="",
                rejected_reason=f"HR∩LR area {overlap_area_km2:.2f} km^2 < threshold {min_overlap} km^2 (no LR coverage)",
            )
        raise RuntimeError(
            f"[{pair_id}] overlap {overlap_area_km2:.3f} km^2 below threshold {min_overlap}"
        )

    if len(user_hr_paths) > 1:
        # v1.2.1 §3 reachability check: combined IoU vs CMGDS patch
        # (only enforce when CMGDS has a footprint, i.e. existing pair).
        if not is_new_pair:
            try:
                cmgds_path = _cmgds_path(pair_id, cfg)
                if cmgds_path:
                    cmgds_poly, _ = _valid_polygon_from_path(cmgds_path, target_crs)
                    iou = overlap.intersection(cmgds_poly).area / overlap.union(cmgds_poly).area
                    log.info("[%s] mosaic combined IoU vs CMGDS = %.2f (disjoint=%s)",
                             pair_id, iou, is_disjoint)
                    if iou < 0.80:
                        log.warning("[%s] mosaic IoU %.2f < 0.80 — flag for human review", pair_id, iou)
            except Exception as e:
                log.warning("[%s] could not compute mosaic IoU: %s", pair_id, e)

    footprint_path = out_dir / "footprint.geojson"
    overlap_gs.to_file(footprint_path, driver="GeoJSON")

    # 4. Clip HR + LR to overlap, write final harmonized
    log.info("[%s] clipping to overlap (%.3f km^2)", pair_id, overlap_area_km2)
    hr_clip = hr_t.rio.clip(overlap_gs.geometry, overlap_gs.crs, drop=True, all_touched=False)
    lr_clip = lr.rio.clip(overlap_gs.geometry, overlap_gs.crs, drop=True, all_touched=False)
    hr_out = out_dir / "hr.tif"
    lr_out = out_dir / "lr.tif"
    for da in (hr_clip, lr_clip):
        da.attrs.pop("_FillValue", None)
        da.encoding.pop("_FillValue", None)
        da.rio.write_nodata(fill, encoded=True, inplace=True)
    hr_clip.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    lr_clip.rio.to_raster(lr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    # The warped intermediate isn't needed anymore.
    try:
        warped_path.unlink()
    except FileNotFoundError:
        pass

    # 5. Re-solve coregistration from scratch (no CMGDS reuse)
    log.info("[%s] re-solving coregistration", pair_id)
    hr_da = _open(hr_out); lr_da = _open(lr_out)
    coreg = None
    try:
        coreg = cor.estimate_rigid_xyz(hr_da, lr_da)
    except RuntimeError as e:
        log.warning("[%s] coreg could not run (%s)", pair_id, e)
    if coreg is not None:
        log.info("[%s] coreg dx=%+.2f dy=%+.2f dz=%+.2f MAD=%.2f m",
                 pair_id, coreg.dx_m, coreg.dy_m, coreg.dz_m, coreg.post_residual_mad_m)
        corrected = cor.apply_xyz(hr_da, coreg.dx_m, coreg.dy_m, coreg.dz_m)
        corrected.attrs.pop("_FillValue", None)
        corrected.encoding.pop("_FillValue", None)
        corrected.rio.write_nodata(fill, encoded=True, inplace=True)
        corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")

    # 6. v1.1 §A QA
    overlay_dir = out_dir / "qc"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = overlay_dir / f"{pair_id}_overlay.png"
    qc_result, status = qc.evaluate(
        sub_pair_id=pair_id,
        hr_path=hr_out, lr_path=lr_out,
        out_overlay_path=overlay_path,
        applied_dx_m=coreg.dx_m if coreg else 0.0,
        applied_dy_m=coreg.dy_m if coreg else 0.0,
        applied_dz_m=coreg.dz_m if coreg else 0.0,
        usbl_bound_m=float(cfg.coregistration["usbl_bound_m"]),
        mad_m=coreg.post_residual_mad_m if coreg else None,
        mad_threshold_m=float(cfg.coregistration["acceptance_threshold_m"]),
        min_peak_sharpness=cfg.coregistration.get("min_peak_sharpness"),
        peak_anisotropy_max=cfg.coregistration.get("peak_anisotropy_max"),
    )

    # 7. Manifest upsert
    df = load_manifest()
    existing = df[df["pair_id"] == pair_id]
    base = existing.iloc[0].to_dict() if len(existing) else {}

    notes_prefix = (
        f"User-provided HR (single warp to {target_gsd:.0f} m EPSG:26910 with "
        f"`{kernel_used}` resample; native GSD {native_gsd:.2f} m, native CRS "
        f"{native_crs}). "
    )
    if len(user_hr_paths) > 1:
        notes_prefix += f"Mosaicked {len(user_hr_paths)} source tiles before warp. "
    if is_new_pair:
        notes_prefix += "New pair (no CMGDS ancestor; v1.2.1 §4). "
    else:
        notes_prefix += f"Supersedes CMGDS {SUPERSEDED_DOI}. "
    if coreg is not None:
        notes_prefix += (
            f"Coreg: dx={coreg.dx_m:+.2f} m, dy={coreg.dy_m:+.2f} m, "
            f"dz={coreg.dz_m:+.2f} m; post-residual MAD={coreg.post_residual_mad_m:.2f} m."
        )

    row_kwargs = _build_row_kwargs(
        pair_id=pair_id, base=base, is_new_pair=is_new_pair,
        terrain_class=terrain_class,
        user_hr_paths=user_hr_paths, native_crs=native_crs, native_gsd=native_gsd,
        kernel_used=kernel_used, target_gsd=target_gsd, target_crs=target_crs,
        footprint_path=footprint_path,
        hr_out=hr_out, lr_out=lr_out,
        qc_result=qc_result, status=status,
        notes=notes_prefix.strip(),
    )
    upsert(ManifestRow(**row_kwargs))

    return ReharmResult(
        pair_id=pair_id,
        user_files=[str(p) for p in user_hr_paths],
        native_gsd_m=native_gsd, resample_kernel=kernel_used,
        horiz_offset_m=qc_result.horiz_offset_m,
        vert_offset_m=qc_result.vert_offset_m,
        psr=qc_result.peak.psr,
        eig_ratio=qc_result.peak.eig_ratio,
        peak_agrees=qc_result.peak.peak_agrees,
        coreg_status=status,
        overlap_area_km2=overlap_area_km2,
        harmonized_hr=str(hr_out), harmonized_lr=str(lr_out),
        overlay_path=str(overlay_path),
    )


def _cmgds_path(pair_id: str, cfg: Config) -> Path | None:
    short = pair_id.split("__", 1)[1]
    matches = list((cfg.raw_dir / "cal_dig_morro_bay").glob(f"hr_2021-*_extracted/{short}.tif"))
    seen = set(); uniq: list[Path] = []
    for m in matches:
        if m.name not in seen:
            seen.add(m.name); uniq.append(m)
    return uniq[0] if uniq else None


def _build_row_kwargs(
    *, pair_id: str, base: dict, is_new_pair: bool,
    terrain_class: str | None,
    user_hr_paths: list[Path], native_crs: str, native_gsd: float,
    kernel_used: str, target_gsd: float, target_crs: str,
    footprint_path: Path, hr_out: Path, lr_out: Path,
    qc_result: Any, status: str, notes: str,
) -> dict:
    # Defaults for new pairs
    new_defaults = {
        "site_name": "Cal DIG I / Morro Bay",
        "region": "Offshore South-Central California",
        "cruise_id": "Cal DIG I",
        "vessel": "NOAA Rainier/Fairweather (+ R/V Sally Ride gap-fill)",
        "hr_platform": "MBARI-donated AUV",
        "hr_sonar": "Reson 7125 400 kHz",
        "hr_doi": "",
        "hr_native_res_m": float(native_gsd),
        "lr_platform": "NOAA hull",
        "lr_sonar": "Simrad EM 700 series",
        "lr_doi": "10.5066/P9QQZ27U",
        "lr_native_res_m": 10.0,
        "res_ratio": 10.0 / float(target_gsd),
        "depth_min_m": 0.0,
        "depth_max_m": 0.0,
        "terrain_class": terrain_class or "continental_margin",
        "vertical_datum": "MSL_negative_down",
        "license": "HR: MBARI/USGS public AUV; LR: public_domain_usgs",
        "acquisition_date": "",
        "verification_status": "verified_pair",
    }
    out: dict = dict(new_defaults)
    out.update({k: v for k, v in base.items() if v is not None and not (isinstance(v, float) and np.isnan(v))})
    out.update({
        "pair_id": pair_id,
        "hr_doi": "",
        "hr_native_res_m": float(native_gsd),
        "lr_native_res_m": 10.0,
        "res_ratio": 10.0 / float(target_gsd),
        "native_crs_hr": native_crs,
        "native_crs_lr": "EPSG:26910",
        "target_crs": target_crs,
        "footprint_wkt": str(footprint_path),
        "raw_path_hr": str(user_hr_paths[0]),
        "raw_path_lr": str(_load_lr_canonical_for_row()),
        "harmonized_path_hr": str(hr_out),
        "harmonized_path_lr": str(lr_out),
        "checksum_hr": sha256_file(hr_out),
        "checksum_lr": sha256_file(lr_out),
        "hr_source_type": "user_provided",
        "hr_local_path": str(user_hr_paths[0]),
        "hr_superseded_doi": "" if is_new_pair else SUPERSEDED_DOI,
        "hr_superseded_reason": NEW_PAIR_REASON if is_new_pair else SUPERSEDED_REASON,
        "horiz_offset_m": float(qc_result.horiz_offset_m),
        "vert_offset_m": float(qc_result.vert_offset_m),
        "coreg_peak_psr": float(qc_result.peak.psr),
        "coreg_peak_eig_ratio": float(qc_result.peak.eig_ratio),
        "coreg_peak_agrees": bool(qc_result.peak.peak_agrees),
        "coreg_status": status,
        "qc_artifact_path": str(qc_result.overlay_path),
        "notes": notes,
    })
    # Trim to declared fields only
    return {k: out[k] for k in ManifestRow.__dataclass_fields__ if k in out}


def _load_lr_canonical_for_row() -> Path:
    # Called in build_row_kwargs; cheap glob.
    base = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/raw/cal_dig_morro_bay")
    cand = list(base.glob("lr_Cal_DIG_I_Bathymetry_10m_extracted/Cal_DIG_I_Bathymetry_10m.tif"))
    return cand[0] if cand else Path("")


# ---------- LuciaChica IoU matrix (informational, v1.2.1 §5) ----------

def luciachica_iou_matrix(approved: dict, settings: dict, base_dir: Path) -> dict[str, dict[str, float]]:
    """Pairwise footprint IoU across the four LuciaChica HR files (informational)."""
    targets = {
        "2007": "LuciaChica_2007_Topo1m_UTM_utm.tif",
        "2008": "LuciaChica_2008_Topo1m_UTM_utm.tif",
        "2009": "LuciaChica_2009_Topo1m_UTM_utm.tif",
        "2019_970m": "LuciaChica970_2m.tif",
    }
    polys: dict[str, Any] = {}
    for k, name in targets.items():
        p = base_dir / name
        if not p.exists():
            continue
        poly, _ = _valid_polygon_from_path(p, settings["target_crs"])
        polys[k] = poly
    out: dict[str, dict[str, float]] = {}
    for a, pa in polys.items():
        out[a] = {}
        for b, pb in polys.items():
            inter = pa.intersection(pb).area
            union = pa.union(pb).area
            out[a][b] = float(inter / union) if union > 0 else 0.0
    return out


# ---------- top-level driver ----------

def reharmonize(cfg: Config, approved_path: Path) -> ReharmReport:
    approved = yaml.safe_load(approved_path.read_text())
    settings = approved["settings"]
    base_dir = Path(settings["base_dir"])
    if not base_dir.is_absolute():
        base_dir = cfg.data_root / "user-provided-cal-dig"
    target_crs = settings["target_crs"]
    if target_crs != "EPSG:26910":
        raise RuntimeError(f"unexpected target_crs {target_crs}")
    for k_field in ("downsample_kernel", "reproject_kernel"):
        if settings[k_field] == "nearest":
            raise RuntimeError(f"settings.{k_field} == 'nearest' is forbidden (v1.2.1 §2)")

    lr_path = _load_lr_canonical(cfg)
    results: list[ReharmResult] = []
    rejection_reasons: dict[str, str] = {}

    # --- Existing CMGDS-replacement pairs ---
    for pair_id, spec in (approved.get("pairs") or {}).items():
        hr_files = [base_dir / f for f in spec["hr"]]
        for f in hr_files:
            if not f.exists():
                raise RuntimeError(f"[{pair_id}] HR file missing: {f}")
        try:
            r = _harmonize_pair(
                cfg=cfg, pair_id=pair_id, user_hr_paths=hr_files,
                lr_path=lr_path, settings=settings,
                is_new_pair=False, terrain_class=None,
            )
            results.append(r)
            if r.coreg_status == "reject":
                rejection_reasons[pair_id] = r.rejected_reason
        except Exception as e:
            log.exception("[%s] re-harmonization failed: %s", pair_id, e)

    # --- New pairs (no CMGDS ancestor) ---
    for pair_id, spec in (approved.get("new_pairs") or {}).items():
        hr_files = [base_dir / f for f in spec["hr"]]
        for f in hr_files:
            if not f.exists():
                raise RuntimeError(f"[{pair_id}] HR file missing: {f}")
        try:
            r = _harmonize_pair(
                cfg=cfg, pair_id=pair_id, user_hr_paths=hr_files,
                lr_path=lr_path, settings=settings,
                is_new_pair=True, terrain_class=spec.get("terrain_class"),
            )
            results.append(r)
            if r.coreg_status == "reject":
                rejection_reasons[pair_id] = r.rejected_reason
        except Exception as e:
            log.exception("[%s] new-pair harmonization failed: %s", pair_id, e)

    # --- Dropped: remove from manifest, do NOT fall back to CMGDS ---
    dropped: list[str] = []
    for pair_id in (approved.get("dropped") or []):
        if drop_pair(pair_id):
            dropped.append(pair_id)
            log.info("[%s] dropped from manifest", pair_id)

    # --- LuciaChica IoU matrix (informational) ---
    iou = luciachica_iou_matrix(approved, settings, base_dir)

    return ReharmReport(
        results=results,
        dropped=dropped,
        rejected=list(approved.get("rejected") or []),
        rejection_reasons=rejection_reasons,
        luciachica_iou=iou,
    )
