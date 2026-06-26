"""Phase 2 Stage A.6 (post-processing) — dedup + fetch list + bbox census + tags.

Consumes:
  - reports/discovery/stage_a6_hr_footprints_<date>.gpkg  (71 non-seed clean HR)
  - manifest/pairs.parquet  (untouchable 21; footprint_wkt)
  - reports/stage_a5_footprint_subset_<date>.json + .gpkg  (A.5 subsets + buffered footprints)

Produces:
  - reports/stage_b_fetch_list_<date>.csv      (cleaned, deduplicated fetch plan)
  - reports/discovery/stage_a6_duplicates_<date>.csv
  - reports/discovery/stage_a6_hr_footprints_<date>.gpkg gains a `duplicate_of` col
  - reports/stage_a6_prefetch_hygiene_<date>.md (written separately / by hand)

Read-only against the manifest; recommendations only. Light (no raster reads,
no network) — reuses cached nav + A.5 buffered footprints.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt as shp_wkt
from shapely.ops import unary_union

from src.discovery.stage_a6_common import (
    REPO, MANIFEST, STAGE_A_JSON, STAGE_A5_JSON, DROPPED_HR, QUARANTINED_HR,
    THIN_OVERLAP, clean_hr_buckets, served_by_cruise, seed_ids,
)

log = logging.getLogger("stage_a6")
TODAY = date.today().isoformat()
IOU_DUP = 0.8
CONTAIN_DUP = 0.9


# --------------------------------------------------------------------------- #
def _manifest_footprints() -> dict[str, object]:
    """pair_id -> footprint geometry in EPSG:4326 from the untouchable 21.

    The manifest ``footprint_wkt`` column actually stores a path to the pair's
    ``footprint.geojson`` (the HR∩LR overlap polygon, typically in the pair's
    UTM target_crs); we load and reproject each to 4326 for spatial dedup.
    """
    m = pd.read_parquet(MANIFEST)
    out = {}
    for _, r in m.iterrows():
        w = r.get("footprint_wkt")
        if not isinstance(w, str) or not w.strip():
            continue
        try:
            if Path(w).exists():
                g = gpd.read_file(w)
                if g.crs is not None and str(g.crs).lower() != "epsg:4326":
                    g = g.to_crs(4326)
                out[r["pair_id"]] = unary_union(list(g.geometry))
            else:
                out[r["pair_id"]] = shp_wkt.loads(w)
        except Exception as e:
            log.warning("manifest %s footprint load failed: %s", r["pair_id"], e)
    return out


def _seed_to_pair(hr_id: str) -> str:
    """Map a seed HR id to its manifest pair_id."""
    if hr_id.startswith("MANIFEST:"):
        return hr_id.split(":", 1)[1]
    if hr_id == "PANGAEA:tag_m127":
        return "tag_m127"
    return hr_id.split(":", 1)[-1]


def _iou(a, b) -> float:
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    union = a.union(b).area
    return inter / union if union else 0.0


def _containment(a, b) -> float:
    """max fraction of the smaller polygon covered by the other."""
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    return max(inter / a.area if a.area else 0, inter / b.area if b.area else 0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    buckets = clean_hr_buckets()
    seeds = seed_ids()
    served = served_by_cruise()
    mfoot = _manifest_footprints()
    fp_path = REPO / f"reports/discovery/stage_a6_hr_footprints_{TODAY}.gpkg"
    fp = gpd.read_file(fp_path).set_index("hr_id")
    a5 = json.loads(STAGE_A5_JSON.read_text())
    a5_by_cruise = {c["cruise"]: c for c in a5["per_cruise"]}
    a5_fp = gpd.read_file(REPO / f"reports/discovery/stage_a5_hr_footprints_{TODAY}.gpkg")

    # ---- Step 2: duplicate sweep (id + spatial) over all 81 ----
    dup_rows = []
    duplicate_hr: dict[str, str] = {}     # hr_id -> manifest pair_id
    for hr, bucket in buckets.items():
        # id / site-name match
        if bucket == "manifest_seed_clean" or hr in seeds:
            pid = _seed_to_pair(hr)
            duplicate_hr[hr] = pid
            dup_rows.append({"hr_id": hr, "bucket": bucket, "duplicate_of": pid,
                             "match_type": "id_seed", "iou": None, "containment": None})
            continue
        # spatial match against manifest footprints (non-seed HR only)
        g = fp.loc[hr].geometry if hr in fp.index else None
        best = (None, 0.0, 0.0)
        for pid, mg in mfoot.items():
            iou = _iou(g, mg); con = _containment(g, mg)
            if iou > best[1] or con > best[2]:
                best = (pid, max(iou, best[1]), max(con, best[2]))
            if iou >= IOU_DUP or con >= CONTAIN_DUP:
                duplicate_hr[hr] = pid
                dup_rows.append({"hr_id": hr, "bucket": bucket, "duplicate_of": pid,
                                 "match_type": "spatial", "iou": round(iou, 3),
                                 "containment": round(con, 3)})
                break
    log.info("duplicates: %d (seeds=%d, spatial=%d)", len(dup_rows),
             sum(d["match_type"] == "id_seed" for d in dup_rows),
             sum(d["match_type"] == "spatial" for d in dup_rows))

    dead = DROPPED_HR | QUARANTINED_HR | set(duplicate_hr)

    # ---- Step 3: live_HR per cruise -> cleaned fetch list ----
    stage_a = json.loads(STAGE_A_JSON.read_text())
    whole_gb = {c["cruise"]: c["fetch_estimate_gb"] for c in stage_a["per_cruise"]}
    targets = {c["cruise"] for c in stage_a["per_cruise"]
               if c["fetch_estimate_gb"] >= 10.0}

    fetch_rows = []
    for cruise in sorted(served):
        live = [h for h in served[cruise] if h not in dead]
        if not live:
            fetch_rows.append({"cruise": cruise, "live_HR": "", "n_live_HR": 0,
                               "fetch_mode": "DROP", "whole_GB": round(whole_gb[cruise], 2),
                               "subset_GB": 0.0, "footprint_bbox": "",
                               "reason": "no live HR (all dropped/dup/quarantined)"})
            continue
        if cruise in targets:
            a5c = a5_by_cruise.get(cruise, {})
            a5_used = set(a5c.get("hr_used", []))
            if a5_used == set(live):
                subset_gb = a5c.get("subset_gb", 0.0)
                note = "reuse A.5 subset (live HR unchanged)"
            else:
                subset_gb = _resubset(cruise, live, a5_fp)
                note = f"re-subset vs live HR (A.5 used {sorted(a5_used)})"
            bbox = ";".join(h for h in live if h in fp.index
                            and fp.loc[h].footprint_type == "bbox_fallback")
            fetch_rows.append({"cruise": cruise, "live_HR": ";".join(live),
                               "n_live_HR": len(live), "fetch_mode": "subset",
                               "whole_GB": round(whole_gb[cruise], 2),
                               "subset_GB": round(subset_gb, 3),
                               "footprint_bbox": bbox, "reason": note})
        else:
            bbox = ";".join(h for h in live if h in fp.index
                            and fp.loc[h].footprint_type == "bbox_fallback")
            fetch_rows.append({"cruise": cruise, "live_HR": ";".join(live),
                               "n_live_HR": len(live), "fetch_mode": "whole",
                               "whole_GB": round(whole_gb[cruise], 2),
                               "subset_GB": round(whole_gb[cruise], 2),
                               "footprint_bbox": bbox, "reason": "small cruise (<10 GB)"})

    # ---- budget ----
    kept = [r for r in fetch_rows if r["fetch_mode"] != "DROP"]
    revised = sum(r["subset_GB"] for r in kept)
    dropped_cruises = [r["cruise"] for r in fetch_rows if r["fetch_mode"] == "DROP"]
    new_hr = sorted(h for h, b in buckets.items() if h not in dead)

    # ---- Step 4: bbox census ----
    bbox_all = fp[fp.footprint_type == "bbox_fallback"].index.tolist()
    bbox_in_fetch = sorted({h for r in kept for h in r["footprint_bbox"].split(";") if h})

    # ---- write outputs ----
    pd.DataFrame(dup_rows).to_csv(
        REPO / f"reports/discovery/stage_a6_duplicates_{TODAY}.csv", index=False)
    fl = pd.DataFrame(fetch_rows).sort_values("subset_GB", ascending=False)
    fl.to_csv(REPO / f"reports/stage_b_fetch_list_{TODAY}.csv", index=False)
    # annotate footprint gpkg with duplicate_of + thin tag
    fp2 = fp.reset_index()
    fp2["duplicate_of"] = fp2["hr_id"].map(duplicate_hr)
    fp2.to_file(fp_path, driver="GPKG", layer="hr")

    summary = {
        "generated": TODAY,
        "n_clean_hr": len(buckets),
        "n_duplicates_total": len(dup_rows),
        "n_dup_seed": sum(d["match_type"] == "id_seed" for d in dup_rows),
        "n_dup_spatial": sum(d["match_type"] == "spatial" for d in dup_rows),
        "n_new_hr_after_dedup": len(new_hr),
        "baseline_a5_gb": a5["revised_total_gb"],
        "revised_fetch_gb": round(revised, 2),
        "n_cruises_kept": len(kept),
        "n_cruises_dropped": len(dropped_cruises),
        "dropped_cruises": dropped_cruises,
        "bbox_footprints_all": bbox_all,
        "bbox_in_cleaned_fetch": bbox_in_fetch,
        "thin_overlap_tags": sorted(THIN_OVERLAP & {r["cruise"] for r in kept}),
    }
    (REPO / f"reports/discovery/stage_a6_summary_{TODAY}.json").write_text(
        json.dumps(summary, indent=2, default=str))

    print("\n=========== STAGE A.6 SUMMARY ===========")
    print(f"clean HR                 : {len(buckets)}")
    print(f"duplicates (seed/spatial): {summary['n_dup_seed']}/{summary['n_dup_spatial']}")
    print(f"new HR after dedup       : {len(new_hr)}")
    print(f"cruises kept / dropped   : {len(kept)} / {len(dropped_cruises)}")
    print(f"dropped cruises          : {dropped_cruises}")
    print(f"A.5 budget               : {a5['revised_total_gb']} GB")
    print(f"REVISED fetch budget     : {revised:.2f} GB")
    print(f"bbox footprints (all 81) : {bbox_all}")
    print(f"bbox in cleaned fetch    : {bbox_in_fetch}")
    print(f"thin-overlap tags        : {summary['thin_overlap_tags']}")


def _resubset(cruise: str, live: list[str], a5_fp: gpd.GeoDataFrame) -> float:
    """Re-subset a target cruise against the union of its LIVE HR buffered
    footprints (from the A.5 gpkg), reusing cached nav + listings (no network)."""
    from src.discovery.stage_a5_subset import (
        iter_cruise_files, parse_fnv_track, NAVCACHE, GEOPORTAL, DIRLIST,
    )
    from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
    sub = a5_fp[(a5_fp.cruise == cruise) & (a5_fp.hr_id.isin(live))]
    if sub.empty:
        return 0.0
    fp_union = unary_union(list(sub.geometry))
    iso = data_dir_from_iso(cruise, GEOPORTAL)
    url, _ = resolve_data_dir(iso, DIRLIST) if iso else (None, "")
    if not url:
        return 0.0
    recs = iter_cruise_files(url, DIRLIST)
    swath = [r for r in recs if r.kind == "swath"]
    nav = {r.key: r for r in recs if r.kind == "nav"}
    cdir = NAVCACHE / cruise
    gb = 0.0
    for s in swath:
        nr = nav.get(s.key)
        track = None
        if nr is not None and (cdir / nr.name).exists():
            track = parse_fnv_track(cdir / nr.name)
        if track is None or track.intersects(fp_union):  # over-include unknowns
            gb += s.bytes / 1024**3
    return gb


if __name__ == "__main__":
    main()
