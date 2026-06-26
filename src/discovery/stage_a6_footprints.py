"""Phase 2 Stage A.6 (job part) — compute unbuffered valid-data footprints for
the 71 non-seed clean HR.

The 10 ``manifest_seed_clean`` HR already have authoritative footprints in the
manifest (they ARE the untouchable-21 pairs) so they are NOT recomputed here;
the light post-processor (`stage_a6_hygiene`) reuses the manifest WKT for them.

Output: ``reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg`` (layer
``hr``) with geometry (EPSG:4326, UNBUFFERED) + ``footprint_type``
(valid_polygon | bbox_fallback) + bucket + catalog geometry_source. Heavy
(decimated raster reads), so run via Slurm.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.discovery.stage_a6_common import REPO, clean_hr_buckets
from src.discovery.stage_a5_subset import hr_footprint_4326, HR_CATALOG

log = logging.getLogger("stage_a6_fp")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    buckets = clean_hr_buckets()
    cat = gpd.read_file(HR_CATALOG).set_index("hr_id")
    nonseed = [h for h, b in buckets.items() if b != "manifest_seed_clean"]
    log.info("computing footprints for %d non-seed clean HR", len(nonseed))

    rows = []
    for i, hr in enumerate(nonseed, 1):
        row = cat.loc[hr] if hr in cat.index else None
        if row is not None and getattr(row, "ndim", 1) > 1:
            row = row.iloc[0]
        geom_src = (row.get("geometry_source") if row is not None else None)
        poly, depth, used_bbox, note = hr_footprint_4326(hr, row)
        ftype = "bbox_fallback" if used_bbox else "valid_polygon"
        if poly is None:
            ftype = "none"
        log.info("[%2d/%d] %-14s %-14s depth=%s %s", i, len(nonseed), hr, ftype,
                 None if depth != depth else round(depth, 1), note[:50])
        rows.append({"hr_id": hr, "bucket": buckets[hr], "footprint_type": ftype,
                     "depth_m": depth, "catalog_geometry_source": str(geom_src),
                     "note": note, "geometry": poly})

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    out = REPO / f"reports/discovery/stage_a6_hr_footprints_{date.today().isoformat()}.gpkg"
    gdf.to_file(out, driver="GPKG", layer="hr")
    n_bbox = int((gdf.footprint_type == "bbox_fallback").sum())
    n_none = int((gdf.footprint_type == "none").sum())
    log.info("wrote %s | valid=%d bbox_fallback=%d none=%d", out,
             len(gdf) - n_bbox - n_none, n_bbox, n_none)
    print(f"DONE: {len(gdf)} footprints; bbox_fallback={n_bbox} none={n_none} -> {out}")


if __name__ == "__main__":
    main()
