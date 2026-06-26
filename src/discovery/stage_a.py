"""v1.5 Stage A — criteria-based selection (the Gate-A deliverable).

Reads the existing M3.1 catalogs and produces:
  * one row per distinct AUV HR (best independent LR companion);
  * tier assignment by resolution ratio (training / eval_only / excluded /
    needs_LR_res / needs_geometry);
  * geo-cluster tags for leakage-safe downstream splits;
  * storage projection;
  * a Gate-A YAML/markdown summary.

Read-only / append-only: never touches the manifest, harmonized rasters,
or prior Tier 1/2 pairs.
"""

from __future__ import annotations

import json
import logging
import math
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import requests
import yaml
from shapely.ops import transform


log = logging.getLogger(__name__)


# Per v1.5 §2 (human-confirmed 2026-06-04) + v1.5.1 §4 5× floor.
RATIO_TRAIN_MAX = 25.0
RATIO_EVAL_MAX = 40.0
RATIO_MIN_USEFUL = 5.0      # below this, SR is not meaningful (catches the
                            # 4 m surface grid × 10 m LR ≈ 2.5× case).

NCEI_PRODUCTS_LAYER = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/"
    "multibeam_datasets/MapServer/0"
)
_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.5 stage_a)"}
_THROTTLE = 0.3


# ---------- LR enrichment: has_processed_grid via NCEI Products layer ----------

def fetch_processed_survey_ids(lr_gdf: gpd.GeoDataFrame, cache_dir: Path) -> set[str]:
    """For each unique HR query bbox, ask NCEI which surveys are in the
    Multibeam Products (processed) layer. Return the union of SURVEY_IDs.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "processed_survey_ids.json"
    if cache_file.exists():
        return set(json.loads(cache_file.read_text()))

    # Group queries by hr_id_query so we re-use the same bbox set as the
    # original LR harvest.
    out: set[str] = set()
    hr_groups = lr_gdf.groupby("hr_id_query")
    for hr_id, g in hr_groups:
        bb = g.total_bounds  # (minx, miny, maxx, maxy)
        params = {
            "where": "DATA_TYPE='MB PRODUCT'",
            "geometry": json.dumps({
                "xmin": float(bb[0]), "ymin": float(bb[1]),
                "xmax": float(bb[2]), "ymax": float(bb[3]),
                "spatialReference": {"wkid": 4326},
            }),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "SURVEY_ID,SURVEY_NAME,DATASET_NAME",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 200,
        }
        try:
            r = requests.get(f"{NCEI_PRODUCTS_LAYER}/query", params=params,
                             timeout=60, headers=_HEADERS)
            data = r.json() if r.status_code == 200 else {}
            feats = data.get("features") or []
            for f in feats:
                attrs = f.get("attributes") or {}
                # The Footprints LR survey_id field is a human-readable string
                # (e.g. "AT05L04"); the Products SURVEY_ID is an integer
                # (e.g. 4347). Match via SURVEY_NAME or DATASET_NAME prefix.
                name = attrs.get("SURVEY_NAME")
                if name:
                    out.add(str(name))
                dsn = attrs.get("DATASET_NAME") or ""
                if dsn:
                    # Strip trailing "_PRODUCTS_*" suffix → bare survey name.
                    bare = dsn.split("_PRODUCTS")[0].split("_PRODUCT")[0]
                    if bare:
                        out.add(bare)
        except Exception as e:
            log.warning("processed-grid query for %s failed: %s", hr_id, e)
        time.sleep(_THROTTLE)
    cache_file.write_text(json.dumps(sorted(out)))
    return out


def enrich_has_processed_grid(lr_gdf: gpd.GeoDataFrame, cache_dir: Path) -> gpd.GeoDataFrame:
    """Set ``has_processed_grid`` on every LR row by membership in the
    NCEI Multibeam Products layer."""
    products = fetch_processed_survey_ids(lr_gdf, cache_dir)
    out = lr_gdf.copy()
    out["has_processed_grid"] = out["survey_id"].astype(str).isin(products)
    log.info("LR has_processed_grid: %d/%d True",
             int(out["has_processed_grid"].sum()), len(out))
    return out


# ---------- HR size from cached MGDS XML ----------

_MGDS_NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}


def hr_size_from_mgds_cache(cache_dir: Path) -> dict[str, int]:
    """Parse the cached MGDS geoms XML (one per data_set_uid) → total bytes
    summed across all files belonging to that data_set_uid.
    """
    out: dict[str, int] = defaultdict(int)
    geoms = cache_dir / "mgds_AUV_Bathymetry_geoms.xml"
    if not geoms.exists():
        return dict(out)
    root = ET.fromstring(geoms.read_bytes())
    files = root.find("m:files", _MGDS_NS)
    if files is None:
        return dict(out)
    for f in files:
        ds_uid = f.get("data_set_uid") or ""
        fi = f.find("m:file_info", _MGDS_NS)
        if fi is None:
            continue
        try:
            sz = int(fi.get("data_file_size") or 0)
        except ValueError:
            sz = 0
        out[ds_uid] += sz
    return dict(out)


# ---------- best-LR-per-HR selection ----------

def best_lr_per_hr(pairs_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Greedy: pick the highest-scoring LR per distinct HR.

    v1.5.1 §4 revision (2026-06-04): **ratio-only gating**. Any grid
    (AUV / USV / surface_vessel) enters the HR pool — the platform tag
    is *recorded*, not used as a filter. The only platform-level
    exclusion left is ``is_non_bathy`` (sidescan / sub-bottom /
    magnetometer products mis-labelled as bathymetry at MGDS).
    """
    if pairs_gdf.empty:
        return pairs_gdf
    ok = pairs_gdf[
        pairs_gdf["independence_verdict"].isin(["independent", "needs_check"])
        & (pairs_gdf.get("is_non_bathy", False) == False)
    ]
    return (ok.sort_values("score", ascending=False)
            .groupby("hr_id", as_index=False).head(1)
            .reset_index(drop=True))


# ---------- tier classification ----------

@dataclass
class Tier:
    name: str   # training / eval_only / excluded / needs_LR_res / needs_geometry
    reason: str


def classify_tier(row: pd.Series, footprint_suspect_map: dict[str, bool],
                  lr_res_source_map: dict[str, str],
                  geometry_source_map: dict[str, str],
                  lr_has_processed_grid_map: dict[str, bool]) -> Tier:
    hr_id = row["hr_id"]
    gsrc = geometry_source_map.get(hr_id, "metadata_bbox")
    if gsrc == "stage_b_failed_no_crs":
        return Tier("excluded",
                    "Stage B could not extract CRS from raster files "
                    "(.grd lacks projection); CRS recovery not yet attempted")
    if gsrc == "crs_failed_verification":
        return Tier("excluded",
                    "CRS recovery: inferred CRS failed verification against "
                    "MGDS ISO bbox — recovered extent landed outside the "
                    "stated geographic region")
    if gsrc == "crs_unrecoverable":
        return Tier("excluded",
                    "CRS recovery: grid header ranges fit neither geographic "
                    "nor UTM pattern cleanly, or no ISO bbox available to "
                    "verify any inferred CRS — recovery declined")
    if footprint_suspect_map.get(hr_id, False):
        return Tier("needs_geometry",
                    "HR is footprint_suspect — true valid-data extent must be "
                    "computed in Stage B before ratio is trustworthy")
    src = lr_res_source_map.get(row["lr_id"], "unknown")
    rr = row.get("res_ratio")
    if rr is None or pd.isna(rr):
        # v1.5.1 §1: raw-LR cruises are NOT dropped at the gate. If the
        # ratio is unestimable AND the LR has no processed grid, route to
        # Stage C gridding (which will measure resolution from the raw
        # .all/.gsf files). Selection includes these rows.
        has_proc = lr_has_processed_grid_map.get(row["lr_id"], False)
        if not has_proc:
            return Tier("raw_lr_to_grid",
                        f"LR is raw-only (lr_res_source={src}); routed to "
                        "Stage C gridding — ratio measured post-grid")
        return Tier("needs_LR_res",
                    f"lr_res_source={src}; LR has processed grid but res "
                    "is missing from metadata")
    try:
        rr = float(rr)
    except (TypeError, ValueError):
        return Tier("needs_LR_res", "ratio not coercible to float")
    if rr < RATIO_MIN_USEFUL:
        return Tier("excluded", f"ratio {rr:.1f} < {RATIO_MIN_USEFUL} (essentially same GSD)")
    if rr <= RATIO_TRAIN_MAX:
        return Tier("training", f"ratio {rr:.1f} in training band ≤ {RATIO_TRAIN_MAX}")
    if rr <= RATIO_EVAL_MAX:
        return Tier("eval_only", f"ratio {rr:.1f} in eval band {RATIO_TRAIN_MAX}-{RATIO_EVAL_MAX}")
    return Tier("excluded", f"ratio {rr:.1f} > {RATIO_EVAL_MAX} (super-resolution not meaningful)")


# ---------- geo clustering for leakage-safe splits ----------

def geo_cluster_tag(gdf: gpd.GeoDataFrame, cluster_radius_km: float = 50.0) -> pd.Series:
    """Assign each HR a geo_cluster id via greedy distance clustering on
    polygon centroids (great-circle distance with haversine).
    """
    if gdf.empty:
        return pd.Series(dtype=object)
    centroids = gdf.geometry.centroid
    lons = centroids.x.values
    lats = centroids.y.values
    cluster_id = np.full(len(gdf), -1, dtype=int)
    next_id = 0
    R = 6371.0  # km
    for i in range(len(gdf)):
        if cluster_id[i] != -1:
            continue
        cluster_id[i] = next_id
        # Vectorised haversine between i and all later points
        dlat = np.radians(lats - lats[i])
        dlon = np.radians(lons - lons[i])
        a = (np.sin(dlat / 2) ** 2
             + np.cos(np.radians(lats[i])) * np.cos(np.radians(lats)) * np.sin(dlon / 2) ** 2)
        dist = 2 * R * np.arcsin(np.sqrt(a))
        close = (dist < cluster_radius_km) & (cluster_id == -1)
        cluster_id[close] = next_id
        next_id += 1
    return pd.Series([f"cluster_{i:03d}" for i in cluster_id], index=gdf.index)


# ---------- pilot picker ----------

def pick_pilot(selection: gpd.GeoDataFrame, target_size: int = 12) -> list[str]:
    """Choose ~10-15 HR ids for the M5.0 pilot.

    Includes (per directive §10):
      * at least one known-good (manifest seed currently in training tier)
      * at least one former footprint_suspect (now `needs_geometry`)
      * at least one raw-LR case (here approximated as has_processed_grid=False)
      * the rest = top-score-per-province in training tier
    """
    if selection.empty:
        return []
    picks: list[str] = []
    s = selection.copy()
    # Known-good = manifest seed AND training tier
    seeds = s[(s["hr_source"].isin(["PANGAEA", "SCIENCEBASE", "MANIFEST"]))
              & (s["tier"] == "training")]
    if not seeds.empty:
        picks.append(seeds.sort_values("score", ascending=False).iloc[0]["hr_id"])
    # Former suspect (now needs_geometry)
    sus = s[s["tier"] == "needs_geometry"]
    if not sus.empty:
        picks.append(sus.sort_values("score", ascending=False).iloc[0]["hr_id"])
    # Raw LR case (has_processed_grid False) — already filtered out at
    # selection time per Stage A policy, so this slot is "highest-scoring
    # row in needs_LR_res" instead.
    needs = s[s["tier"] == "needs_LR_res"]
    if not needs.empty:
        picks.append(needs.sort_values("score", ascending=False).iloc[0]["hr_id"])
    # Fill the rest from training tier, max one per (terrain, geo_cluster)
    remaining = target_size - len(picks)
    pool = s[~s["hr_id"].isin(picks)]
    pool = pool[pool["tier"] == "training"].sort_values("score", ascending=False)
    seen_keys = set()
    for _, r in pool.iterrows():
        key = (r.get("terrain_hint") or "?", r.get("geo_cluster") or "?")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        picks.append(r["hr_id"])
        if len(picks) - len([p for p in picks if p in seeds["hr_id"].values or p in sus["hr_id"].values or p in needs["hr_id"].values]) >= remaining - 3:
            break
        if len(picks) >= target_size:
            break
    return picks[:target_size]


# ---------- top-level orchestrator ----------

@dataclass
class StageAOutput:
    selection: gpd.GeoDataFrame   # one row per HR
    storage_estimate: dict[str, Any]
    pilot_ids: list[str]
    summary_md_path: Path
    yaml_path: Path


def run(hr_path: Path, lr_path: Path, pairs_path: Path,
        out_dir: Path, mgds_cache_dir: Path, ncei_cache_dir: Path,
        pilot_size: int = 12,
        ratio_train_max: float = RATIO_TRAIN_MAX,
        ratio_eval_max: float = RATIO_EVAL_MAX) -> StageAOutput:
    out_dir.mkdir(parents=True, exist_ok=True)
    hr = gpd.read_file(hr_path, layer="hr")
    lr = gpd.read_file(lr_path, layer="lr")
    pairs = gpd.read_file(pairs_path, layer="pairs")

    # 1. Enrich LR with has_processed_grid (live NCEI query against products layer).
    lr_enriched = enrich_has_processed_grid(lr, ncei_cache_dir)
    has_proc_by_lr_id = dict(zip(lr_enriched["lr_id"], lr_enriched["has_processed_grid"]))
    lr_res_source_by_id = dict(zip(lr_enriched["lr_id"], lr_enriched["lr_res_source"]))

    # 2. Restrict pairs to HR that pass platform filter (already done in join),
    #    then pick best LR per HR.
    pairs = pairs.copy()
    pairs["lr_has_processed_grid"] = pairs["lr_id"].map(has_proc_by_lr_id)
    # v1.5.1 §1: do NOT filter on processed-grid availability — that's
    # informational only. v1.5 §4 anticipates raw-LR cruises entering
    # Stage C (mb-system gridding). Tag the field so Stage C can route,
    # but selection runs on independence + AUV-grid filter alone.
    best = best_lr_per_hr(pairs)

    # 3. Tier classification.
    footprint_suspect_by_id = dict(zip(hr["hr_id"], hr.get("footprint_suspect", False)))
    geometry_source_by_id = dict(zip(
        hr["hr_id"],
        hr.get("geometry_source", pd.Series(["metadata_bbox"] * len(hr))).fillna("metadata_bbox"),
    ))
    tiers = [classify_tier(r, footprint_suspect_by_id, lr_res_source_by_id,
                           geometry_source_by_id, has_proc_by_lr_id)
             for _, r in best.iterrows()]
    best["tier"] = [t.name for t in tiers]
    best["tier_reason"] = [t.reason for t in tiers]

    # 4. Inject HR-side fields needed for the pilot picker + report
    hr_indexed = hr.set_index("hr_id")
    for col in ("source", "platform", "sonar", "native_res_m", "doi", "title",
                "footprint_km2", "hr_class", "is_non_bathy"):
        if col in hr_indexed.columns:
            best[f"hr_{col}" if col != "source" else "hr_source"] = best["hr_id"].map(hr_indexed[col])

    # 5. Geo clusters (on HR footprints).
    best["geo_cluster"] = geo_cluster_tag(best, cluster_radius_km=50.0)

    # 6. Storage projection.
    hr_size_by_uid = hr_size_from_mgds_cache(mgds_cache_dir)
    def _hr_bytes(hr_id: str) -> int:
        if hr_id.startswith("MGDS:"):
            return hr_size_by_uid.get(hr_id.split(":", 1)[1], 0)
        return 0  # seeds are already on disk
    best["hr_size_bytes_estimate"] = best["hr_id"].apply(_hr_bytes)
    by_tier_size = best.groupby("tier")["hr_size_bytes_estimate"].sum().to_dict()
    storage_estimate = {
        "hr_bytes_total": int(best["hr_size_bytes_estimate"].sum()),
        "hr_bytes_training": int(by_tier_size.get("training", 0)),
        "hr_bytes_eval_only": int(by_tier_size.get("eval_only", 0)),
        # LR sizes are not exposed by NCEI per-survey. Approximate per
        # processed-grid product at ~150 MB median (empirical from TAG /
        # AtlantOS / per-cruise BAG samples).
        "lr_bytes_per_grid_est": 150 * 1024 * 1024,
    }
    n_train = int((best["tier"] == "training").sum())
    n_eval = int((best["tier"] == "eval_only").sum())
    n_raw_lr = int((best["tier"] == "raw_lr_to_grid").sum())
    storage_estimate["lr_bytes_training"] = n_train * storage_estimate["lr_bytes_per_grid_est"]
    storage_estimate["lr_bytes_eval_only"] = n_eval * storage_estimate["lr_bytes_per_grid_est"]
    storage_estimate["projected_total_bytes_processed_only"] = (
        storage_estimate["hr_bytes_training"] + storage_estimate["hr_bytes_eval_only"]
        + storage_estimate["lr_bytes_training"] + storage_estimate["lr_bytes_eval_only"]
    )
    # Raw-LR cruises (tier='raw_lr_to_grid') are NOT included in the
    # processed-only projection. They route through Stage C gridding; raw
    # .all/.gsf cruise files are typically 1-10 GB per cruise-day and
    # total raw-LR ingest is plausibly 50-500 GB. Stage C dry-run will
    # measure this precisely; do not commit a single number here.
    storage_estimate["raw_lr_cruises_in_selection"] = n_raw_lr
    storage_estimate["raw_lr_per_cruise_typical_gb_low"] = 1
    storage_estimate["raw_lr_per_cruise_typical_gb_high"] = 10

    # 7. Pilot picks.
    pilot_ids = pick_pilot(best, target_size=pilot_size)

    # 8. Persist outputs.
    sel_path = out_dir / "stage_a_selection.gpkg"
    best.to_file(sel_path, driver="GPKG", layer="selection")
    yaml_path = out_dir / "stage_a_selection.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "ratio_train_max": float(ratio_train_max),
        "ratio_eval_max": float(ratio_eval_max),
        "ratio_min_useful": float(RATIO_MIN_USEFUL),
        # v1.5.1 §1: no processed-grid throttle. Raw-LR cruises stay in
        # selection and are routed through Stage C mb-system gridding.
        "lr_processed_grid_required": False,
        "raw_lr_routed_to_stage_c": True,
        "selection_counts": {t: int((best["tier"] == t).sum()) for t in best["tier"].unique()},
        "pilot_ids": list(pilot_ids),
        "storage_estimate_bytes": storage_estimate,
        "selection_gpkg": str(sel_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }, sort_keys=False))

    # Append-only: never overwrite an existing dated gate. Subsequent runs
    # on the same day get _v2, _v3, … so prior gate summaries persist.
    today = datetime.now().strftime('%Y%m%d')
    md_path = out_dir / f"stage_a_gate_{today}.md"
    v = 2
    while md_path.exists():
        md_path = out_dir / f"stage_a_gate_{today}_v{v}.md"
        v += 1
    _write_gate_a_md(best, storage_estimate, pilot_ids, md_path,
                     ratio_train_max, ratio_eval_max)
    return StageAOutput(best, storage_estimate, pilot_ids, md_path, yaml_path)


# ---------- Gate A report ----------

def _gb(n: int) -> str:
    return f"{n / (1024 ** 3):.2f} GB"


def _write_gate_a_md(best: gpd.GeoDataFrame, storage: dict, pilot_ids: list[str],
                     out_path: Path, train_max: float, eval_max: float) -> None:
    by_tier = best.groupby("tier").size().to_dict()
    by_terrain = best.groupby(["tier", "terrain_hint"]).size().unstack(fill_value=0)
    by_cluster_train = (best[best["tier"] == "training"].groupby("geo_cluster").size()
                        .sort_values(ascending=False))
    by_class = best.groupby("hr_class").size().to_dict() if "hr_class" in best.columns else {}
    lines = [
        f"# v1.5 Gate A (v1.5.1 revision) — selection sign-off "
        f"({datetime.now().date().isoformat()})",
        "",
        "**No mass download has happened.** This summarises the projected bulk "
        "acquisition. Human sign-off is required before Stage B / C starts.",
        "",
        "## Criteria (v1.5.1 §4 revision — ratio-only gating)",
        "",
        f"- Training tier: `{RATIO_MIN_USEFUL:.0f} ≤ res_ratio ≤ {train_max:.0f}`",
        f"- Eval-only tier: `{train_max:.0f} < res_ratio ≤ {eval_max:.0f}`",
        f"- Excluded: `res_ratio > {eval_max:.0f}` OR `< {RATIO_MIN_USEFUL:.0f}`",
        "- **No processed-grid filter** (v1.5.1 §1): raw LR cruises enter Stage C "
        "gridding rather than being dropped at Gate A.",
        "- **No platform filter at the selection gate** (v1.5.1 §4): inclusion "
        "is ratio-gated, not platform-gated. `hr_class` ∈ {auv, usv, "
        "surface_vessel} is recorded for stratification.",
        "- Non-bathy products (sidescan / sub-bottom / magnetometer) excluded "
        "as a data-type rejection.",
        "- Independence verdict ∈ {`independent`, `needs_check`}; no composite "
        "or same-platform LR.",
        "- One row per distinct HR; best independent LR companion.",
        "",
        "## HR class distribution (informational; not used as a gate)",
        "",
        "| hr_class | count |",
        "|---|---:|",
    ]
    for cls in ("auv", "usv", "surface_vessel"):
        lines.append(f"| {cls} | {by_class.get(cls, 0)} |")
    lines += [
        "",
        "## Tier counts",
        "",
        "| tier | HR count |",
        "|---|---:|",
    ]
    for t in ("training", "eval_only", "raw_lr_to_grid", "needs_geometry",
              "needs_LR_res", "excluded"):
        lines.append(f"| {t} | {by_tier.get(t, 0)} |")
    lines += [
        f"| **total selection** | **{len(best)}** |",
        "",
        "## By terrain (selected HR)",
        "",
        "| tier × terrain | " + " | ".join(by_terrain.columns.tolist()) + " |",
        "|---|" + "---|" * len(by_terrain.columns),
    ]
    for tier, row in by_terrain.iterrows():
        lines.append(f"| **{tier}** | " + " | ".join(str(v) for v in row.values) + " |")
    lines += [
        "",
        "## Geographic clusters (training tier; 50 km radius)",
        "",
        "| cluster | training HR | terrain sample |",
        "|---|---:|---|",
    ]
    train = best[best["tier"] == "training"]
    for cluster, n in by_cluster_train.head(15).items():
        sample = train[train["geo_cluster"] == cluster]
        terrains = sample["terrain_hint"].mode()
        terrain_s = terrains.iloc[0] if len(terrains) else "—"
        lines.append(f"| {cluster} | {n} | {terrain_s} |")
    if len(by_cluster_train) > 15:
        lines.append(f"| _… +{len(by_cluster_train) - 15} more clusters_ | | |")
    n_raw = storage.get("raw_lr_cruises_in_selection", 0)
    lines += [
        "",
        "## Storage projection",
        "",
        "**Processed-grid portion (HR + processed LR):**",
        "",
        f"- HR (training): **{_gb(storage['hr_bytes_training'])}**",
        f"- HR (eval-only): **{_gb(storage['hr_bytes_eval_only'])}**",
        f"- LR (training, processed grids): ~{_gb(storage['lr_bytes_training'])} "
        f"({(storage['lr_bytes_training'] // storage['lr_bytes_per_grid_est'])} grids × ~150 MB est.)",
        f"- LR (eval-only, processed grids): ~{_gb(storage['lr_bytes_eval_only'])}",
        f"- **Processed subtotal: ~{_gb(storage['projected_total_bytes_processed_only'])}** "
        f"under `$DATA_ROOT` (`/scratch/groups/hilley/auv_ship_colocated_bathy/`).",
        "- HR-side bytes are exact for MGDS (sum of `data_file_size` from "
        "cached geoms XML). Processed-LR sizes are heuristic — true sizes "
        "only known after Stage C fetches the grids.",
        "",
        "**Raw-LR cruises (routed through Stage C gridding, per v1.5.1 §1):**",
        "",
        f"- Raw-LR cruises in selection (`raw_lr_to_grid` tier): **{n_raw}**",
        "- Raw `.all` / `.gsf` cruise files are typically 1–10 GB per "
        "cruise-day; total raw-LR ingest is plausibly **50–500 GB** "
        "depending on cruise length and sonar.",
        "- A Stage C dry-run (NCEI MBBDB byte-size lookups for the cruise "
        "files) will produce a precise number before any raw fetch starts.",
        "- The processed-grid subtotal above does **not** include raw-LR "
        "cruises; those are intentionally deferred for sizing.",
        "",
        "## M5.0 pilot picks (auto, " + str(len(pilot_ids)) + " HR)",
        "",
    ]
    pilot_rows = best[best["hr_id"].isin(pilot_ids)].copy()
    pilot_rows["pilot_order"] = pilot_rows["hr_id"].apply(lambda x: pilot_ids.index(x))
    pilot_rows = pilot_rows.sort_values("pilot_order")
    lines += [
        "| # | hr_id | tier | ratio | hr_class | hr_native_res_m | terrain | cluster |",
        "|---:|---|---|---:|---|---:|---|---|",
    ]
    for i, r in enumerate(pilot_rows.itertuples(), 1):
        rr = getattr(r, "res_ratio", None)
        rr_s = "—" if rr is None or (isinstance(rr, float) and math.isnan(rr)) else f"{rr:.1f}"
        hr_res = getattr(r, "hr_native_res_m", None)
        hr_res_s = "—" if hr_res is None or (isinstance(hr_res, float) and math.isnan(hr_res)) else f"{hr_res:.2f}"
        lines.append(
            f"| {i} | `{r.hr_id}` | {r.tier} | {rr_s} | "
            f"{getattr(r, 'hr_class', '')} | {hr_res_s} | "
            f"{getattr(r, 'terrain_hint', '')} | {getattr(r, 'geo_cluster', '')} |"
        )
    # Excluded-by-reason tally (v1.5.2 §0). Split ratio-rejects from
    # CRS-related failures so a future recovery pass can target the
    # right population.
    excluded = best[best["tier"] == "excluded"].copy()
    def _classify_reason(s: str) -> str:
        s = s or ""
        if "ratio" in s and "> 40" in s: return "ratio_gt_40 (untouchable)"
        if "ratio" in s and "< 5"  in s: return "ratio_lt_5 (untouchable)"
        if "CRS could not" in s or "lacks projection" in s: return "stage_b_failed_no_crs (recoverable)"
        if "failed verification" in s: return "crs_failed_verification"
        if "recovery declined" in s: return "crs_unrecoverable"
        return "other"
    excluded["reason_class"] = excluded["tier_reason"].apply(_classify_reason)
    by_reason = excluded.groupby("reason_class").size().sort_values(ascending=False)
    lines += [
        "",
        "## Excluded — breakdown by reason (v1.5.2 §0)",
        "",
        "| reason | count |",
        "|---|---:|",
    ]
    for k, v in by_reason.items():
        lines.append(f"| {k} | {int(v)} |")
    lines += [
        f"| **total excluded** | **{len(excluded)}** |",
        "",
        "Ratio rejects (`ratio_gt_40` / `ratio_lt_5`) are genuine and never "
        "recovered. CRS-failure rows are the recovery target; the recovery "
        "pass writes `crs_recovered` (re-tiered above) / `crs_failed_verification` "
        "/ `crs_unrecoverable` and these stay excluded for the right reasons.",
        "",
        "## Read-only guarantees",
        "",
        "- Existing `manifest/pairs.parquet` is not touched by this stage.",
        "- DISCOL, the 18 Cal DIG sub-pairs, CCZ, TAG remain exactly as they are.",
        "- No raster download yet; Stages B–G run only after this gate is signed off.",
        "",
        "## What to confirm",
        "",
        "1. Tier thresholds (train ≤25×, eval ≤40×) — accept or adjust.",
        "2. Raw-LR cruises remain in selection and route to Stage C gridding "
        "(v1.5.1 §1) — confirm. The processed-grid subtotal is the only "
        "number sized here; raw-LR total is deferred to a Stage C dry-run.",
        "3. Storage budget — confirm `$DATA_ROOT` can host the processed "
        "subtotal **plus** the deferred raw-LR fetch (50–500 GB plausible).",
        "4. Pilot composition — accept or hand-edit `stage_a_selection.yaml`.",
        "",
    ]
    out_path.write_text("\n".join(lines))
