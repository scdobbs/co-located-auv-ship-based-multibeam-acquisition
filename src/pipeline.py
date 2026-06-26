"""End-to-end orchestrator.

A single Tier-1 pair definition can produce either:
  * one harmonized output (DISCOL: one HR raster, one LR raster), or
  * N harmonized outputs (Cal DIG: 19 small AUV dive-patch tiles paired
    against the single Cal DIG 10 m mosaic — each tile is its own sub-pair).

Resumable + idempotent: rasterio rewrites are atomic enough at our sizes,
and downstream steps re-check checksums before redoing work.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import rioxarray  # noqa: F401

from . import cmgds, pangaea, qa as qa_mod
from .config import Config
from .coregister import CoregResult, apply_xyz, estimate_rigid_xyz
from .download import fetch, sha256_file
from .harmonize import harmonize_pair
from .manifest import ManifestRow, upsert
from .pairs import Pair
from .raster_io import describe


log = logging.getLogger(__name__)


def _slug(doi: str) -> str:
    return doi.replace("/", "_").replace(":", "_")


def _pangaea_single(role: str, doi: str, out_dir: Path) -> tuple[Path, dict]:
    record = pangaea.resolve(doi)
    if not record.rasters:
        raise RuntimeError(f"[{role}] no rasters discovered for DOI {doi}.")
    # Prefer the largest raster (typically the main grid; smaller siblings
    # are sub-area zooms). Fall back to first if sizes are unknown.
    sized = [r for r in record.rasters if getattr(r, "size_bytes", None)]
    primary = max(sized, key=lambda r: r.size_bytes) if sized else record.rasters[0]
    log.info("[%s] PANGAEA primary raster %s (%s siblings)",
             role, primary.filename, len(record.rasters) - 1)
    dest = out_dir / f"{role}_{_slug(doi)}_{primary.filename}"
    result = fetch(primary.url, dest)
    # Some PANGAEA releases (e.g. AtlantOS M127 868686) ship GMT NetCDF
    # Classic ``.grd`` files that GDAL can't read directly. Transparently
    # convert to a sibling GeoTIFF and use that as the canonical raster.
    from . import gmt_grd as _gmt
    canonical = result.path
    if _gmt.is_gmt_grd(canonical):
        tif_path = canonical.with_suffix(".tif")
        if not tif_path.exists():
            _gmt.convert(canonical, tif_path)
        canonical = tif_path
    meta = {
        "role": role, "doi": doi, "provider": "pangaea",
        "citation": record.citation, "license": record.license,
        "primary_filename": primary.filename, "primary_url": primary.url,
        "all_rasters": [{"filename": r.filename, "url": r.url} for r in record.rasters],
        "downloaded_path": str(result.path),
        "canonical_raster_path": str(canonical),
        "sha256": result.sha256, "size_bytes": result.size_bytes,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_metadata": record.raw_metadata,
    }
    return canonical, meta


def _cmgds_tiles(role: str, doi: str, out_dir: Path) -> tuple[list[Path], dict]:
    res = cmgds.prepare(doi=doi, role=role, out_dir=out_dir, kind="bathy")
    meta = {
        "role": role, "doi": doi, "provider": "cmgds",
        "citation": res.citation, "license": res.license,
        "landing_url": res.landing_url,
        "source_urls": [s.url for s in res.sources],
        "source_filenames": [s.filename for s in res.sources],
        "tile_paths": [str(p) for p in res.tiles],
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Acquired via CMGDS landing-page hrefs; user-approved directive "
            "deviation 2026-06-02 (ScienceBase API not applicable for this DOI)."
        ),
    }
    return res.tiles, meta


def _harmonize_one(
    *,
    cfg: Config,
    pair: Pair,
    sub_pair_id: str,
    hr_raw: Path,
    lr_raw: Path,
    sub_out_dir: Path,
    sub_raw_meta: dict,
    sub_notes_prefix: str = "",
) -> dict | None:
    """Harmonize one (HR, LR) pair, coregister if required, write manifest row.

    Returns the result dict, or None if the pair was rejected (e.g. zero
    overlap with LR — common for AUV tiles outside the LR footprint).
    """
    sub_out_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency: if both harmonized outputs already exist AND a manifest row
    # already exists for this sub_pair_id, skip end-to-end. The manifest
    # check guards against the case where harmonization wrote files but the
    # process was killed before the row was inserted.
    from . import manifest as _mf
    manifest_df = _mf.load()
    hr_done = (sub_out_dir / "hr.tif").exists()
    lr_done = (sub_out_dir / "lr.tif").exists()
    in_manifest = sub_pair_id in set(manifest_df.get("pair_id", []))
    if hr_done and lr_done and in_manifest:
        log.info("[%s] already harmonized + in manifest; skipping", sub_pair_id)
        return {"sub_pair_id": sub_pair_id, "skipped": True}

    log.info("[%s] describe rasters", sub_pair_id)
    hr_info = describe(hr_raw)
    lr_info = describe(lr_raw)

    # Use the pair's declared `native_res_m` (always in metres) for this
    # sanity check — raster `gsd_m` is in CRS units, which can be degrees
    # for geographic-CRS inputs (e.g. TAG AUV in EPSG:4326).
    declared_hr = float(pair.hr.native_res_m)
    declared_lr = float(pair.lr.native_res_m)
    if declared_lr <= declared_hr * 2:
        raise RuntimeError(
            f"[{sub_pair_id}] LR declared {declared_lr:.2f} m is not coarser than "
            f"2x HR declared {declared_hr:.2f} m. Refusing — LR must be the real ship grid."
        )

    log.info("[%s] harmonize -> %s", sub_pair_id, pair.target_crs)
    try:
        harmonized = harmonize_pair(
            pair_id=sub_pair_id,
            hr_raw=hr_raw,
            lr_raw=lr_raw,
            target_crs=pair.target_crs,
            resample_kernel=cfg.resample_kernel,
            nodata=float(cfg.nodata["fill_value"]),
            out_dir=sub_out_dir,
            vertical_sign=cfg.vertical["sign_convention"],
            min_overlap_area_km2=float(cfg.pair_qa["min_overlap_area_km2"]),
        )
    except Exception as e:
        # Common rejection: AUV tile sits outside LR footprint or overlap is tiny.
        log.warning("[%s] harmonization rejected: %s", sub_pair_id, e)
        return None

    coreg: CoregResult | None = None
    if pair.coregistration_required:
        log.info("[%s] coregister AUV->ship", sub_pair_id)
        hr_da = rioxarray.open_rasterio(harmonized.hr_path, masked=True).squeeze("band", drop=True)
        lr_da = rioxarray.open_rasterio(harmonized.lr_path, masked=True).squeeze("band", drop=True)
        try:
            coreg = estimate_rigid_xyz(hr_da, lr_da)
        except RuntimeError as e:
            log.warning("[%s] coregistration could not run (%s); skipping correction", sub_pair_id, e)
            coreg = None
        if coreg is not None:
            if coreg.post_residual_mad_m > float(cfg.coregistration["acceptance_threshold_m"]):
                log.warning(
                    "[%s] post-coreg MAD %.2f m exceeds threshold %.2f m — flagging in notes",
                    sub_pair_id, coreg.post_residual_mad_m,
                    float(cfg.coregistration["acceptance_threshold_m"]),
                )
            corrected = apply_xyz(hr_da, coreg.dx_m, coreg.dy_m, coreg.dz_m)
            corrected.attrs.pop("_FillValue", None)
            corrected.encoding.pop("_FillValue", None)
            corrected.rio.write_nodata(float(cfg.nodata["fill_value"]), encoded=True, inplace=True)
            corrected.rio.to_raster(harmonized.hr_path, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")

    qa = qa_mod.compute(
        pair_id=sub_pair_id,
        hr_path=harmonized.hr_path,
        lr_path=harmonized.lr_path,
        overlap_area_km2=harmonized.overlap_area_km2,
        hr_gsd_m=harmonized.hr_info.gsd_m,
        lr_gsd_m=harmonized.lr_info.gsd_m,
        coreg=coreg,
    )

    hr_sha = sha256_file(harmonized.hr_path)
    lr_sha = sha256_file(harmonized.lr_path)

    notes = (sub_notes_prefix + " " + pair.notes).strip()
    if coreg is not None:
        notes += (
            f" Coreg: dx={coreg.dx_m:+.2f} m, dy={coreg.dy_m:+.2f} m, dz={coreg.dz_m:+.2f} m; "
            f"post-residual MAD={coreg.post_residual_mad_m:.2f} m."
        )

    row = ManifestRow(
        pair_id=sub_pair_id,
        site_name=pair.site_name,
        region=pair.region,
        cruise_id=pair.cruise_id,
        vessel=pair.vessel,
        hr_platform=pair.hr.platform,
        hr_sonar=pair.hr.sonar,
        hr_doi=pair.hr.doi,
        hr_native_res_m=pair.hr.native_res_m,
        lr_platform=pair.lr.platform,
        lr_sonar=pair.lr.sonar,
        lr_doi=pair.lr.doi,
        lr_native_res_m=pair.lr.native_res_m,
        res_ratio=pair.lr.native_res_m / pair.hr.native_res_m,
        depth_min_m=pair.depth_range_m[0],
        depth_max_m=pair.depth_range_m[1],
        terrain_class=pair.terrain_class,
        native_crs_hr=hr_info.crs,
        native_crs_lr=lr_info.crs,
        target_crs=pair.target_crs,
        vertical_datum=pair.vertical_datum,
        footprint_wkt=str(harmonized.footprint_path),
        license=f"HR: {pair.hr.license}; LR: {pair.lr.license}",
        acquisition_date=pair.acquisition_date,
        verification_status=pair.verification_status,
        raw_path_hr=str(hr_raw),
        raw_path_lr=str(lr_raw),
        harmonized_path_hr=str(harmonized.hr_path),
        harmonized_path_lr=str(harmonized.lr_path),
        checksum_hr=hr_sha,
        checksum_lr=lr_sha,
        notes=notes,
        # v1.3 §5: propagate the source-type from the pair definition.
        # Defaults to "doi" for legacy Tier 1; Tier 2 pairs declare "pangaea_doi".
        hr_source_type=getattr(pair, "hr_source_type", "doi"),
    )
    upsert(row)
    return {
        "sub_pair_id": sub_pair_id,
        "harmonized": asdict(harmonized.hr_info),
        "qa": qa_mod.render_markdown(qa),
        "row": row.to_record(),
        "overlap_area_km2": harmonized.overlap_area_km2,
    }


def ingest(cfg: Config, pair: Pair) -> dict:
    pair_raw = cfg.raw_dir / pair.pair_id
    pair_out = cfg.harmonized_dir / pair.pair_id
    pair_raw.mkdir(parents=True, exist_ok=True)
    pair_out.mkdir(parents=True, exist_ok=True)

    log.info("[%s] === download HR + LR -> %s ===", pair.pair_id, pair_raw)

    # ---- HR side ----
    hr_meta: dict
    hr_tiles: list[Path]
    if pair.hr.provider == "pangaea":
        path, hr_meta = _pangaea_single("hr", pair.hr.doi, pair_raw)
        hr_tiles = [path]
    elif pair.hr.provider == "cmgds":
        hr_tiles, hr_meta = _cmgds_tiles("hr", pair.hr.doi, pair_raw)
    else:
        raise ValueError(f"unknown HR provider {pair.hr.provider}")

    # ---- LR side (always single canonical raster) ----
    lr_meta: dict
    if pair.lr.provider == "pangaea":
        lr_path, lr_meta = _pangaea_single("lr", pair.lr.doi, pair_raw)
    elif pair.lr.provider == "cmgds":
        lr_tiles, lr_meta = _cmgds_tiles("lr", pair.lr.doi, pair_raw)
        if len(lr_tiles) != 1:
            log.info("[%s] LR yielded %d tiles; using first (%s)", pair.pair_id, len(lr_tiles), lr_tiles[0].name)
        lr_path = lr_tiles[0]
        lr_meta["used_lr_tile"] = str(lr_path)
    else:
        raise ValueError(f"unknown LR provider {pair.lr.provider}")

    (pair_raw / "metadata.json").write_text(json.dumps(
        {"pair_id": pair.pair_id, "hr": hr_meta, "lr": lr_meta,
         "scratch_purge_warning": "Sherlock scratch is not permanent archival."},
        indent=2, default=str,
    ))

    # ---- Harmonize: one call for single-tile HR, N calls for multi-tile HR ----
    if len(hr_tiles) == 1:
        sub_pair_id = pair.pair_id
        sub_out_dir = pair_out
        result = _harmonize_one(
            cfg=cfg, pair=pair, sub_pair_id=sub_pair_id,
            hr_raw=hr_tiles[0], lr_raw=lr_path,
            sub_out_dir=sub_out_dir, sub_raw_meta=hr_meta,
        )
        return {"pair_id": pair.pair_id, "sub_pairs": [result] if result else []}

    results: list[dict] = []
    rejected: list[tuple[str, str]] = []
    for tile in hr_tiles:
        sub_pair_id = f"{pair.pair_id}__{tile.stem}"
        sub_out_dir = pair_out / tile.stem
        try:
            r = _harmonize_one(
                cfg=cfg, pair=pair, sub_pair_id=sub_pair_id,
                hr_raw=tile, lr_raw=lr_path,
                sub_out_dir=sub_out_dir, sub_raw_meta=hr_meta,
                sub_notes_prefix=f"AUV dive patch {tile.stem}.",
            )
        except Exception as e:
            log.error("[%s] failed: %s", sub_pair_id, e, exc_info=True)
            rejected.append((sub_pair_id, repr(e)))
            continue
        if r is None:
            rejected.append((sub_pair_id, "no overlap or harmonization rejected"))
        else:
            results.append(r)
    log.info("[%s] harmonized %d/%d tile pairs (%d rejected)",
             pair.pair_id, len(results), len(hr_tiles), len(rejected))
    return {"pair_id": pair.pair_id, "sub_pairs": results, "rejected": rejected}
