"""Spatial join + scoring + independence screen (v1.4 §5 + §6).

Reads ``hr_catalog.gpkg`` (HR records, polygon footprints) and
``lr_candidates.gpkg`` (LR ship surveys per HR query), joins on real
boundary polygons, applies the independence screen, and emits the
candidate-pairs catalog.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyproj
from shapely.geometry import shape
from shapely.ops import transform


log = logging.getLogger(__name__)


# Composite / synthesis datasets that MUST NOT appear as LR (§6).
_COMPOSITE_PATTERNS = (
    r"\bGMRT\b", r"\bGEBCO\b", r"composite", r"synth", r"mosaic.*global",
    r"USGS.*composite", r"\bSRTM\b",
)
_COMPOSITE_RE = re.compile("|".join(_COMPOSITE_PATTERNS), re.I)

# Sonar tokens used for same-platform / different-sonar distinction (§6).
_AUV_SONARS = ("reson", "imagenex", "seabat 7125", "seabat 7150", "seabat t50")
_HULL_SONARS = ("em122", "em120", "em302", "em304", "em710", "em712", "em2040",
                "seabeam 2112", "seabeam 1050", "atlas hydrosweep")


@dataclass
class CandidatePair:
    candidate_id: str
    hr_id: str; hr_repo: str; hr_doi: str
    hr_platform: str; hr_sonar: str; hr_native_res_m: float | None
    hr_format: str; hr_file_ids: str; hr_license: str
    lr_id: str; lr_source: str; lr_cruise_id: str
    lr_platform: str; lr_sonar: str
    lr_has_processed_grid: Any
    lr_native_res_est_m: float | None
    lr_metadata_url: str
    overlap_km2: float
    overlap_frac_hr: float
    res_ratio: float | None
    depth_min_m: float | None
    depth_max_m: float | None
    terrain_hint: str
    independence_verdict: str
    independence_reason: str
    score: float
    rank: int
    status: str = "proposed"
    geometry: Any = None


def _project_for_area(geom):
    """Reproject a WGS84 polygon to an equal-area CRS for accurate km^2."""
    cx, cy = geom.centroid.x, geom.centroid.y
    # Albers-style azimuthal equal-area centered on the polygon — good for
    # local areas regardless of latitude.
    proj_str = f"+proj=laea +lat_0={cy} +lon_0={cx} +ellps=WGS84"
    tr = pyproj.Transformer.from_crs("EPSG:4326", proj_str, always_xy=True).transform
    return transform(tr, geom)


def _terrain_hint(depth_min: float | None, depth_max: float | None,
                  hr_platform: str, hr_title: str,
                  hr_description: str = "", hr_geographic_feature: str = "") -> tuple[str, str]:
    """v1.5.1 §3 — return ``(terrain_class, source)``.

    Searches MGDS rich text (description, geographic_feature) in addition
    to title/platform; depth-based fallback covers blank-text cases.
    `source` ∈ {"metadata", "inferred", "unknown"}.
    """
    feat = (hr_geographic_feature or "").lower()
    text = " ".join([hr_platform, hr_title, hr_description, hr_geographic_feature]).lower()
    # Vent / hydrothermal field
    if any(w in feat for w in ("vent", "hydrothermal", "tag", "lucky", "moose", "menez")):
        return "hydrothermal_vent", "metadata"
    if any(w in text for w in ("hydrothermal vent", "vent field", "tag hydrothermal",
                                "lucky strike", "moose")):
        return "hydrothermal_vent", "inferred"
    # Volcanic / seamount / spreading-center
    if any(w in feat for w in ("seamount", "epr", "jdf", "axial", "loihi", "ridge",
                                "spreading", "volcan")):
        return "volcanic_or_seamount", "metadata"
    if any(w in text for w in ("seamount", "spreading center", "spreading ridge",
                                "volcanic", "volcano", "kolumbo", "axial",
                                "loihi", "juan de fuca", "east pacific rise")):
        return "volcanic_or_seamount", "inferred"
    # Canyon
    if "canyon" in feat:
        return "canyon", "metadata"
    if "canyon" in text:
        return "canyon", "inferred"
    # Nodule field (CCZ-ish)
    if any(w in feat for w in ("clarion", "clipperton", "ccz", "nodule")):
        return "nodule_field", "metadata"
    if any(w in text for w in ("nodule field", "manganese nodule", "clarion-clipperton",
                                "discol", "ccz")):
        return "nodule_field", "inferred"
    # Pockmark / mud-volcano / cold seep (margin features)
    if any(w in text for w in ("pockmark", "mud volcano", "cold seep", "seep field")):
        return "continental_margin", "inferred"
    # Depth-based fallback (least specific)
    if depth_min is not None and depth_max is not None:
        try:
            dm = float(depth_min); dx = float(depth_max)
            d = -(dm + dx) / 2.0 if dm < 0 else (dm + dx) / 2.0
            if 0 < d < 1500:
                return "continental_margin", "inferred"
            if 1500 <= d < 3500:
                return "continental_margin", "inferred"
            if d >= 3500:
                return "abyssal_plain", "inferred"
        except (TypeError, ValueError):
            pass
    return "unknown", "unknown"


def _independence(hr_row: pd.Series, lr_row: pd.Series) -> tuple[str, str]:
    """Apply §6 screening."""
    lr_text = " ".join(str(lr_row.get(k) or "") for k in
                       ("lr_id", "source", "cruise_id", "platform", "sonar"))
    if _COMPOSITE_RE.search(lr_text):
        return ("composite_excluded",
                "LR appears to be a composite/synthesis product; per §6 use the "
                "underlying ship survey via the composite's source-polygon, not "
                "the composite itself.")
    # Same-platform / same-sonar rejection
    hr_platform_l = str(hr_row.get("platform") or "").lower()
    lr_platform_l = str(lr_row.get("platform") or "").lower()
    hr_sonar_l = str(hr_row.get("sonar") or "").lower()
    lr_sonar_l = str(lr_row.get("sonar") or "").lower()
    # AUV vs hull sonar — the hull MBES on the deploying ship is a valid LR.
    auv_sonar = any(s in hr_sonar_l for s in _AUV_SONARS) or "auv" in (hr_row.get("platform_type") or "").lower()
    hull_sonar = any(s in lr_sonar_l for s in _HULL_SONARS)
    if hr_platform_l and lr_platform_l and hr_platform_l == lr_platform_l and not hull_sonar:
        return ("same_platform_reject",
                f"HR and LR share platform ({hr_platform_l}) and LR is not a "
                f"hull MBES; reject self-pair.")
    if hr_sonar_l and lr_sonar_l and hr_sonar_l == lr_sonar_l and auv_sonar:
        return ("same_platform_reject",
                f"LR sonar is identical to HR AUV sonar ({hr_sonar_l}); reject.")
    if not lr_sonar_l:
        return ("needs_check", "LR sonar not recorded; human must verify.")
    if not hull_sonar and not auv_sonar:
        return ("needs_check", "Could not classify sonar types; verify by hand.")
    return ("independent", "Different platform/sonar than HR; valid LR candidate.")


def _score(overlap_km2: float, overlap_frac_hr: float, res_ratio: float | None,
           lr_has_processed_grid: Any, terrain_hint: str,
           independence_verdict: str, footprint_suspect: bool = False,
           is_auv_grid: bool = True) -> float:
    """Composite score (higher = better) — v1.4.1 §5.

    Primary signal: ``overlap_frac_hr`` (now meaningful after geometry fix)
    + ``res_ratio`` in the 5-25x super-resolution band. Raw overlap area
    is a weak tiebreaker; license + province-gap boost.
    """
    if independence_verdict in ("composite_excluded", "same_platform_reject"):
        return -1.0
    if not is_auv_grid:
        return -0.5
    s = 0.0
    # Primary: meaningful overlap fraction (0..1)
    s += min(overlap_frac_hr, 1.0) * 4.0
    # Resolution ratio in the useful band
    if res_ratio is not None:
        if 5.0 <= res_ratio <= 25.0:
            s += 2.5
        elif 3.0 <= res_ratio < 5.0:
            s += 1.0
        elif 25.0 < res_ratio <= 40.0:
            s += 0.5
        elif res_ratio > 40.0:
            s -= 1.0  # high_ratio
        elif res_ratio < 1.5:
            s -= 1.5  # ratio_too_low
    # Processed grid availability
    if lr_has_processed_grid is True:
        s += 1.0
    elif lr_has_processed_grid is False:
        s -= 0.25
    # Province gap boost
    if terrain_hint in ("hydrothermal_vent", "volcanic_or_seamount", "nodule_field"):
        s += 0.5
    if terrain_hint == "abyssal_plain":
        s += 0.3
    # Raw area is a weak tiebreaker (log scale)
    s += math.log10(max(overlap_km2, 0.01)) * 0.3
    # Demotions
    if independence_verdict == "needs_check":
        s -= 0.5
    if footprint_suspect:
        s -= 1.5
    return s


def build(hr_path: Path, lr_path: Path, out_path: Path) -> Path:
    hr = gpd.read_file(hr_path, layer="hr")
    lr = gpd.read_file(lr_path, layer="lr")
    if hr.crs is None or str(hr.crs).lower() != "epsg:4326":
        hr = hr.to_crs("EPSG:4326")
    if lr.crs is None or str(lr.crs).lower() != "epsg:4326":
        lr = lr.to_crs("EPSG:4326")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    geoms = []
    for _, hr_row in hr.iterrows():
        hr_id = hr_row["hr_id"]
        hr_geom = hr_row.geometry
        if hr_geom is None or hr_geom.is_empty:
            continue
        # LR records keyed on this HR (or all candidates)
        candidates = lr[lr["hr_id_query"] == hr_id]
        if candidates.empty:
            continue
        hr_area_km2 = _project_for_area(hr_geom).area / 1e6
        for _, lr_row in candidates.iterrows():
            lr_geom = lr_row.geometry
            if lr_geom is None or lr_geom.is_empty:
                continue
            inter = hr_geom.intersection(lr_geom)
            if inter.is_empty:
                continue
            inter_km2 = _project_for_area(inter).area / 1e6
            overlap_frac_hr = inter_km2 / hr_area_km2 if hr_area_km2 > 0 else 0.0
            hr_res = hr_row.get("native_res_m")
            lr_res_est = lr_row.get("native_res_est_m")
            try:
                hr_res = float(hr_res) if hr_res is not None and not pd.isna(hr_res) else None
            except (TypeError, ValueError):
                hr_res = None
            try:
                lr_res_est = float(lr_res_est) if lr_res_est is not None and not pd.isna(lr_res_est) else None
            except (TypeError, ValueError):
                lr_res_est = None
            res_ratio = (lr_res_est / hr_res) if (lr_res_est is not None and hr_res not in (None, 0)) else None
            terrain, terrain_source = _terrain_hint(
                hr_row.get("depth_min_m"), hr_row.get("depth_max_m"),
                hr_row.get("platform") or "", hr_row.get("title") or "",
                hr_description=hr_row.get("description") or "",
                hr_geographic_feature=hr_row.get("geographic_feature") or "",
            )
            verdict, reason = _independence(hr_row, lr_row)
            score = _score(inter_km2, overlap_frac_hr, res_ratio,
                           lr_row.get("has_processed_grid"), terrain, verdict,
                           footprint_suspect=bool(hr_row.get("footprint_suspect")),
                           is_auv_grid=bool(hr_row.get("is_auv_grid", True)))
            cid = f"{hr_id}::{lr_row['lr_id']}"
            rows.append({
                "candidate_id": cid,
                "hr_id": hr_id, "hr_repo": hr_row.get("source") or "",
                "hr_doi": hr_row.get("doi") or "",
                "hr_platform": hr_row.get("platform") or "",
                "hr_sonar": hr_row.get("sonar") or "",
                "hr_native_res_m": hr_res,
                "hr_format": hr_row.get("format") or "",
                "hr_file_ids": hr_row.get("file_ids") or "",
                "hr_license": hr_row.get("license") or "",
                "lr_id": lr_row["lr_id"], "lr_source": lr_row.get("source") or "",
                "lr_cruise_id": lr_row.get("cruise_id") or "",
                "lr_platform": lr_row.get("platform") or "",
                "lr_sonar": lr_row.get("sonar") or "",
                "lr_has_processed_grid": lr_row.get("has_processed_grid"),
                "lr_native_res_est_m": lr_res_est,
                "lr_metadata_url": lr_row.get("metadata_url") or "",
                "overlap_km2": float(inter_km2),
                "overlap_frac_hr": float(overlap_frac_hr),
                "res_ratio": res_ratio,
                "depth_min_m": hr_row.get("depth_min_m"),
                "depth_max_m": hr_row.get("depth_max_m"),
                "terrain_hint": terrain,
                "terrain_source": terrain_source,
                "independence_verdict": verdict,
                "independence_reason": reason,
                "score": score,
                "rank": 0,  # filled below
                "status": "proposed",
                "is_auv_grid": bool(hr_row.get("is_auv_grid", True)),
                "hr_class": hr_row.get("hr_class") or "auv",
                "is_non_bathy": bool(hr_row.get("is_non_bathy", False)),
                "footprint_suspect": bool(hr_row.get("footprint_suspect")),
                "platform_verdict": hr_row.get("platform_verdict") or "",
                "lr_res_source": lr_row.get("lr_res_source") or "",
                "area_implausible": bool(hr_row.get("footprint_suspect")),
            })
            geoms.append(inter)

    if not rows:
        log.warning("no candidate pairs produced")
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("score", ascending=False).reset_index(drop=True)
        df["rank"] = df.index + 1
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    # Reorder geometry to match the dataframe sort if non-empty
    if not df.empty:
        gdf = gdf.sort_values("rank").reset_index(drop=True)
    gdf.to_file(out_path, driver="GPKG", layer="pairs")
    log.info("candidate pairs: %d -> %s", len(gdf), out_path)
    # v1.4.1 §5 — also emit a collapsed "triage" view: one best LR per HR
    # (best = max score among that HR's candidates), filtered to AUV grids
    # that pass the platform filter and aren't footprint_suspect.
    if not df.empty:
        triage_pool = df[
            (df.get("is_auv_grid", True) == True)
            & (df.get("footprint_suspect", False) == False)
            & (df["independence_verdict"].isin(["independent", "needs_check"]))
        ]
        if not triage_pool.empty:
            best = (triage_pool.sort_values("score", ascending=False)
                    .groupby("hr_id", as_index=False).head(1))
            best = best.sort_values("score", ascending=False).reset_index(drop=True)
            best["rank"] = best.index + 1
            triage_geoms = [geoms[df.index.get_loc(i)] for i in best.index] if False else \
                           [gdf.geometry.iloc[gdf[gdf["candidate_id"] == cid].index[0]] for cid in best["candidate_id"]]
            triage_gdf = gpd.GeoDataFrame(best, geometry=triage_geoms, crs="EPSG:4326")
            triage_gdf.to_file(out_path, driver="GPKG", layer="triage")
            log.info("triage view: %d (best LR per HR) -> layer 'triage'", len(triage_gdf))
    return out_path
