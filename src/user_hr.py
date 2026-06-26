"""User-provided Cal DIG HR inventory + artifact verification (v1.2 §B + §C).

Two responsibilities:
  inventory(...)  — §B: enumerate user files, record raster metadata, SHA256,
                    render hillshade + 2-D FFT spectrum PNGs, write
                    provenance.json sidecars. Human attests artifact-free.
  match(...)      — §C: name-fuzzy + spatial-IoU mapping from each user file
                    to one of the existing Cal DIG sub-pairs (or unmatched).
                    Mandatory spatial IoU threshold (default 0.8) over the
                    CMGDS HR footprint the file would replace.

Both steps are read-only — no harmonization, no manifest writes. The caller
pauses for human confirmation after each.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LightSource


log = logging.getLogger(__name__)


# -------- §B: inventory --------

@dataclass
class FileInfo:
    path: str
    name: str
    sha256: str
    size_bytes: int
    crs: str
    crs_units: str
    pixel_size_x_m: float
    pixel_size_y_m: float
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    nodata: float | None
    valid_fraction: float
    depth_min_m: float | None
    depth_max_m: float | None
    depth_median_m: float | None
    hillshade_png: str
    spectrum_png: str
    sidecar_json: str
    # Per v1.2.1 §8: do NOT expose numeric spectral metrics — they were
    # non-discriminating. Hillshade + FFT images still feed the §7(a) contact
    # sheet; artifact-free status is human-attested.


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _hillshade_png(arr: np.ndarray, dx: float, dy: float, out_path: Path, title: str) -> None:
    a = np.where(np.isfinite(arr), arr, np.nanmedian(arr))
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(a, vert_exag=1.0, dx=dx, dy=abs(dy))
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(hs, cmap="gray", origin="upper")
    ax.set_title(title, fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _fft_spectrum(arr: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    """Return log10(|FFT|^2) for the largest finite window in arr, plus
    a few summary metrics: radial log-log slope (steeper = smoother),
    'axis_excess' = ratio of high-freq energy on the cardinal axes to a
    radial baseline at the same frequencies. A sustained axis_excess > 1.5
    on a flat sub-region is a strong signal of grid-axis spectral spikes
    typical of NN-reprojection criss-cross.
    """
    a = arr.astype(float)
    mask = np.isfinite(a)
    if not mask.any():
        return np.zeros((1, 1)), {"radial_log_slope": float("nan"), "axis_excess": float("nan")}
    a = np.where(mask, a, np.nanmean(a))
    a = a - a.mean()
    # Window
    wy = np.hanning(a.shape[0]); wx = np.hanning(a.shape[1])
    aw = a * np.outer(wy, wx)
    F = np.fft.fftshift(np.fft.fft2(aw))
    P = (F * np.conj(F)).real
    cy, cx = P.shape[0] // 2, P.shape[1] // 2
    P[cy, cx] = 0.0

    # Radial profile
    yy, xx = np.indices(P.shape)
    r = np.round(np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)).astype(int)
    rmax = min(cy, cx)
    radial = np.zeros(rmax + 1)
    for rr in range(1, rmax + 1):
        m = (r == rr)
        if m.any():
            radial[rr] = P[m].mean()
    # log-log slope over the mid frequencies
    lo, hi = max(2, rmax // 16), rmax // 2
    xs = np.log(np.arange(lo, hi))
    ys = np.log(np.maximum(radial[lo:hi], 1e-30))
    slope = float(np.polyfit(xs, ys, 1)[0]) if ys.size > 4 else float("nan")

    # Axis excess at high-frequency bin: compare axis energy to radial baseline
    hi_band = slice(int(rmax * 0.5), rmax)
    axis_band_y = P[hi_band, cx]
    axis_band_x = P[cy, hi_band]
    radial_at_band = radial[hi_band]
    if radial_at_band.size and radial_at_band.mean() > 0:
        axis_excess = float(
            (axis_band_y.mean() + axis_band_x.mean()) / (2 * radial_at_band.mean())
        )
    else:
        axis_excess = float("nan")
    return np.log10(np.maximum(P, 1e-30)), {
        "radial_log_slope": slope,
        "axis_excess": axis_excess,
    }


def _select_flat_window(ds: rasterio.DatasetReader, target: int = 256) -> tuple[int, int, int]:
    """Pick a window of size 'target' with the lowest local variance —
    suppresses real bathymetry so artifacts dominate the FFT.
    """
    h, w = ds.height, ds.width
    # Sample a 1024x1024 thumb to scout
    thumb = ds.read(
        1, out_shape=(min(h, 1024), min(w, 1024)), masked=True
    )
    a = thumb.filled(np.nan) if hasattr(thumb, "mask") else thumb.astype(float)
    mask = np.isfinite(a)
    if mask.sum() == 0:
        return 0, 0, target
    a_fill = np.where(mask, a, np.nanmean(a))
    # Local variance via integral image trick (uniform_filter)
    from scipy.ndimage import uniform_filter
    side = max(64, target // 4)
    m = uniform_filter(a_fill, size=side)
    m2 = uniform_filter(a_fill * a_fill, size=side)
    var = m2 - m * m
    valid_frac = uniform_filter(mask.astype(float), size=side)
    var = np.where(valid_frac > 0.99, var, np.inf)
    yi, xi = np.unravel_index(np.argmin(var), var.shape)
    sy = max(1, h / thumb.shape[0]); sx = max(1, w / thumb.shape[1])
    rr = max(0, int(yi * sy - target // 2))
    cc = max(0, int(xi * sx - target // 2))
    rr = min(rr, h - target)
    cc = min(cc, w - target)
    return rr, cc, target


def _spectrum_png(P_log: np.ndarray, out_path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 5.5))
    im = ax.imshow(P_log, cmap="magma", origin="upper")
    cy, cx = P_log.shape[0] // 2, P_log.shape[1] // 2
    ax.axhline(cy, color="cyan", lw=0.4, alpha=0.5)
    ax.axvline(cx, color="cyan", lw=0.4, alpha=0.5)
    ax.set_title(title + "\nlog10 |FFT|^2 of flat window", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    fig.colorbar(im, ax=ax, label="log10 power")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def inspect_one(path: Path, out_dir: Path) -> FileInfo:
    out_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path) as ds:
        crs = ds.crs.to_string() if ds.crs else "unknown"
        crs_units = ds.crs.linear_units if ds.crs else "unknown"
        tr = ds.transform
        dx, dy = float(tr.a), float(tr.e)
        bounds = tuple(ds.bounds)
        w, h = ds.width, ds.height
        nodata = ds.nodata
        # Downsample for stats
        ovr = ds.read(1, out_shape=(min(h, 2048), min(w, 2048)), masked=True)
        a = ovr.filled(np.nan) if hasattr(ovr, "mask") else ovr.astype(float)
        valid = np.isfinite(a)
        depths = a[valid]
        d_min = float(depths.min()) if depths.size else None
        d_max = float(depths.max()) if depths.size else None
        d_med = float(np.median(depths)) if depths.size else None
        # Hillshade thumb
        hs_path = out_dir / (path.stem + "_hillshade.png")
        _hillshade_png(a, dx, dy, hs_path, path.name)
        # Flat window for FFT
        rr, cc, win = _select_flat_window(ds, target=min(256, h - 1, w - 1))
        flat = ds.read(1, window=((rr, rr + win), (cc, cc + win)), masked=True)
        flat_arr = flat.filled(np.nan) if hasattr(flat, "mask") else flat.astype(float)
    P_log, _ = _fft_spectrum(flat_arr)
    sp_path = out_dir / (path.stem + "_fft.png")
    _spectrum_png(P_log, sp_path,
                  f"{path.name}\nflat-window {win}px at ({rr}, {cc})")

    sha = _sha256(path)
    info = FileInfo(
        path=str(path),
        name=path.name,
        sha256=sha,
        size_bytes=path.stat().st_size,
        crs=crs,
        crs_units=crs_units,
        pixel_size_x_m=dx,
        pixel_size_y_m=dy,
        width=w, height=h,
        bounds=bounds,
        nodata=float(nodata) if nodata is not None else None,
        valid_fraction=float(valid.mean()),
        depth_min_m=d_min, depth_max_m=d_max, depth_median_m=d_med,
        hillshade_png=str(hs_path),
        spectrum_png=str(sp_path),
        sidecar_json="",
    )
    sidecar = path.with_suffix(path.suffix + ".provenance.json")
    # Drop axis_excess + numeric FFT stats from sidecar (v1.2.1 §8).
    sidecar.write_text(json.dumps({
        "source": "user_provided",
        "path": str(path),
        "sha256": sha,
        "size_bytes": info.size_bytes,
        "crs": crs,
        "pixel_size_m": [dx, dy],
        "bounds": list(bounds),
        "hillshade_png": str(hs_path),
        "spectrum_png": str(sp_path),
        "attested_artifact_free": None,
    }, indent=2))
    info.sidecar_json = str(sidecar)
    return info


def inventory(root: Path, out_dir: Path) -> list[FileInfo]:
    paths = sorted(p for p in root.glob("*.tif") if p.is_file())
    items: list[FileInfo] = []
    for p in paths:
        log.info("inspecting %s", p.name)
        try:
            items.append(inspect_one(p, out_dir))
        except Exception as e:
            log.exception("failed on %s: %s", p, e)
    return items


# -------- §C: name + spatial match --------


def _normalise_name(s: str) -> str:
    s = s.lower()
    # Strip date/dive prefixes like "20180426m1_" or "201804_"
    s = re.sub(r"^\d{6,8}m?\d*_?", "", s)
    s = re.sub(r"\d{4}_", "", s, count=1)
    # Strip noisy suffixes
    for suf in (
        "_topo1m_utminterp_utm", "_topo1m_utm_utm", "_topo1m_utm",
        "_topo1m_converted", "_topo1m_interp_converted", "_topo1m_interp",
        "_2m", "_mauv", "_utm", "_interp", "_converted",
    ):
        s = s.replace(suf, "")
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _token_overlap(a: str, b: str) -> float:
    """Symmetric character-trigram similarity in [0, 1]."""
    if not a or not b:
        return 0.0
    def trigrams(x: str) -> set[str]:
        return {x[i:i+3] for i in range(len(x) - 2)} or {x}
    A, B = trigrams(a), trigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _footprint_in_crs(path: Path, target_crs: str) -> Optional[object]:
    """Return the valid-data polygon of a raster, reprojected to target_crs."""
    import geopandas as gpd
    from rasterio.features import shapes
    from shapely.geometry import shape
    from shapely.ops import unary_union
    with rasterio.open(path) as ds:
        arr = ds.read(1, masked=True)
        v = (~arr.mask).astype("uint8") if hasattr(arr, "mask") else (arr != ds.nodata).astype("uint8")
        polys = [shape(g) for g, val in shapes(v, mask=v.astype(bool), transform=ds.transform) if val == 1]
        poly = unary_union(polys)
        src_crs = ds.crs.to_string()
    if str(src_crs) == str(target_crs):
        return poly
    gs = gpd.GeoSeries([poly], crs=src_crs).to_crs(target_crs)
    return gs.iloc[0]


@dataclass
class MatchCandidate:
    user_file: str
    sub_pair_id: str
    name_score: float
    iou: float
    user_area_km2: float
    cmgds_area_km2: float
    intersection_area_km2: float


@dataclass
class MatchReport:
    proposed: list[MatchCandidate] = field(default_factory=list)
    user_unmatched: list[str] = field(default_factory=list)
    sub_pair_unmatched: list[str] = field(default_factory=list)
    collisions: list[dict] = field(default_factory=list)
    threshold_iou: float = 0.8


def _cmgds_tile_path(sub_pair_id: str, raw_root: Path) -> Path | None:
    short = sub_pair_id.split("__", 1)[1]
    matches = list(raw_root.glob(f"hr_2021-*_extracted/{short}.tif"))
    # Dedupe by absolute path (we earlier had duplicate hr_hr_ prefixes)
    seen = set()
    uniq = []
    for m in matches:
        key = m.name
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    return uniq[0] if uniq else None


def match(
    user_files: list[FileInfo],
    sub_pair_ids: list[str],
    raw_root: Path,
    target_crs: str = "EPSG:26910",
    iou_threshold: float = 0.8,
    name_score_min: float = 0.30,
) -> MatchReport:
    """For each sub_pair, find the user file with highest name score that
    ALSO meets the IoU threshold against the CMGDS HR footprint. Report
    everything that doesn't cleanly resolve.
    """
    report = MatchReport(threshold_iou=iou_threshold)

    # Precompute footprints
    cmgds_polys: dict[str, object] = {}
    cmgds_paths: dict[str, Path] = {}
    for sp in sub_pair_ids:
        p = _cmgds_tile_path(sp, raw_root)
        if p is None:
            log.warning("no CMGDS tile found for %s", sp)
            continue
        cmgds_paths[sp] = p
        try:
            cmgds_polys[sp] = _footprint_in_crs(p, target_crs)
        except Exception as e:
            log.exception("CMGDS footprint failed for %s: %s", sp, e)

    user_polys: dict[str, object] = {}
    for u in user_files:
        try:
            user_polys[u.path] = _footprint_in_crs(Path(u.path), target_crs)
        except Exception as e:
            log.exception("user footprint failed for %s: %s", u.name, e)

    # Name candidates: for each sub-pair, score all user files
    sub_norms = {sp: _normalise_name(sp.split("__", 1)[1]) for sp in sub_pair_ids}
    user_norms = {u.path: _normalise_name(u.name.rsplit(".", 1)[0]) for u in user_files}

    # Track best (sub, user) and second-best per sub for collision detection
    proposed: dict[str, MatchCandidate] = {}
    user_to_best_sub: dict[str, tuple[str, float]] = {}

    for sp in sub_pair_ids:
        if sp not in cmgds_polys:
            continue
        cmgds_p = cmgds_polys[sp]
        scored: list[tuple[float, str]] = []
        for u in user_files:
            score = _token_overlap(sub_norms[sp], user_norms[u.path])
            if score >= name_score_min:
                scored.append((score, u.path))
        scored.sort(reverse=True)
        # Pick first candidate that meets IoU threshold
        accepted = None
        for score, upath in scored:
            up = user_polys.get(upath)
            if up is None or cmgds_p is None:
                continue
            inter = up.intersection(cmgds_p)
            union = up.union(cmgds_p)
            iou = (inter.area / union.area) if union.area > 0 else 0.0
            cand = MatchCandidate(
                user_file=upath, sub_pair_id=sp,
                name_score=score, iou=iou,
                user_area_km2=up.area / 1e6, cmgds_area_km2=cmgds_p.area / 1e6,
                intersection_area_km2=inter.area / 1e6,
            )
            if iou >= iou_threshold:
                accepted = cand
                break
            # also record near-miss for the report
            if accepted is None:
                accepted = cand
        if accepted is not None:
            proposed[sp] = accepted
            prev = user_to_best_sub.get(accepted.user_file)
            if prev is None or accepted.name_score > prev[1]:
                user_to_best_sub[accepted.user_file] = (sp, accepted.name_score)

    # Identify collisions (one user file is the best candidate for multiple sub-pairs)
    user_counts: dict[str, list[str]] = {}
    for sp, c in proposed.items():
        user_counts.setdefault(c.user_file, []).append(sp)
    for upath, sps in user_counts.items():
        if len(sps) > 1:
            report.collisions.append({"user_file": upath, "sub_pairs": sps})

    # Build outputs
    report.proposed = [proposed[sp] for sp in sub_pair_ids if sp in proposed]
    proposed_user_files = {c.user_file for c in report.proposed if c.iou >= iou_threshold}
    report.user_unmatched = sorted(
        u.path for u in user_files if u.path not in proposed_user_files
    )
    report.sub_pair_unmatched = sorted(
        sp for sp in sub_pair_ids
        if sp not in proposed or proposed[sp].iou < iou_threshold
    )
    return report


def render_inventory_report(items: list[FileInfo], out_path: Path) -> None:
    lines = [
        f"# v1.2 §B — User-provided Cal DIG HR inventory ({len(items)} files)",
        "",
        "Each file got: SHA256, raster metadata, hillshade PNG, FFT spectrum PNG of "
        "a flat window, and a `<file>.provenance.json` sidecar with "
        "`attested_artifact_free: null` awaiting human attestation.",
        "",
        "v1.2.1 §8: numeric spectral metrics dropped — they were non-discriminating. "
        "Artifact-free status is attested visually from the hillshade + FFT images "
        "(see the §7(a) contact sheet).",
        "",
        "| file | CRS | pixel (m) | width × height | depth (min/med/max) | hillshade | FFT |",
        "|---|---|---|---|---|---|---|",
    ]
    for it in items:
        dm = f"{it.depth_min_m:.0f}/{it.depth_median_m:.0f}/{it.depth_max_m:.0f}" if it.depth_min_m is not None else "—"
        lines.append(
            f"| `{it.name}` | {it.crs} | {abs(it.pixel_size_x_m):.2f} × {abs(it.pixel_size_y_m):.2f} | "
            f"{it.width} × {it.height} | {dm} | "
            f"`{Path(it.hillshade_png).name}` | `{Path(it.spectrum_png).name}` |"
        )
    lines += [
        "",
        "## Sidecars",
        "",
        "Provenance sidecars written next to each file:",
        "",
    ]
    for it in items:
        lines.append(f"- `{Path(it.sidecar_json).name}` (sha256 `{it.sha256[:16]}…`)")
    lines += [
        "",
        "## Required human action",
        "",
        "1. Review hillshade + FFT PNGs (in this report's directory). The criss-cross "
        "artifact, if present, is most clearly visible as bright spikes on the "
        "kx=0 or ky=0 lines of the FFT spectrum, and as a diamond/grid texture in the hillshade.",
        "2. For each file, set `attested_artifact_free: true|false` in the matching "
        "`.provenance.json` sidecar.",
        "3. Files with `attested_artifact_free: false` will be excluded from §C matching.",
        "",
    ]
    out_path.write_text("\n".join(lines))


def render_match_report(report: MatchReport, items: list[FileInfo], out_path: Path) -> None:
    name_by_path = {it.path: it.name for it in items}
    lines = [
        f"# v1.2 §C — Proposed user_file → sub_pair_id mapping",
        "",
        f"Threshold: name_score ≥ 0.30 AND IoU ≥ {report.threshold_iou:.2f}.",
        "Pause for human confirmation before any re-harmonization.",
        "",
        "## Proposed mapping (sorted; ✓ = meets IoU threshold)",
        "",
        "| sub_pair | user_file | name | IoU | user km² | CMGDS km² | ∩ km² |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for c in report.proposed:
        mark = "✓" if c.iou >= report.threshold_iou else "✗"
        short_user = name_by_path.get(c.user_file, Path(c.user_file).name)
        short_sub = c.sub_pair_id.split("__", 1)[1]
        lines.append(
            f"| `{short_sub}` | `{short_user}` {mark} | {c.name_score:.2f} | {c.iou:.2f} | "
            f"{c.user_area_km2:.2f} | {c.cmgds_area_km2:.2f} | {c.intersection_area_km2:.2f} |"
        )
    lines.append("")

    if report.collisions:
        lines += ["## Collisions (same user file matched by >1 sub-pair)", ""]
        for c in report.collisions:
            lines.append(f"- `{Path(c['user_file']).name}` → {c['sub_pairs']}")
        lines.append("")

    if report.sub_pair_unmatched:
        lines += ["## Sub-pairs with no acceptable user-file match", ""]
        for sp in report.sub_pair_unmatched:
            lines.append(f"- `{sp.split('__', 1)[1]}`")
        lines.append("")

    if report.user_unmatched:
        lines += ["## User files not used in proposed mapping", ""]
        for u in report.user_unmatched:
            lines.append(f"- `{Path(u).name}`")
        lines.append("")

    lines += [
        "## Rejected sub-pairs (stay rejected per addendum §C)",
        "",
        "- `20190318m1_LuciaChica1100m` — true geographic non-overlap with LR (M1.5 §D.4).",
        "- `20190319m1_8mPockmarkDetail` — true geographic non-overlap with LR (M1.5 §D.4).",
        "",
        "These do not become valid pairs even if a user file with a matching name exists; "
        "clean HR does not create LR coverage.",
        "",
        "## Required human action",
        "",
        "Review the table above. Confirm each ✓ row OR explicitly approve a ✗ row "
        "(below threshold). Resolve any collisions. Reply with the approved mapping; "
        "no re-harmonization (§D) happens until then.",
        "",
    ]
    out_path.write_text("\n".join(lines))
