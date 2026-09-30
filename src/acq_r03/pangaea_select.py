"""ACQ-R03 §1.2 — select the PANGAEA raw-swath files that can hold soundings under the HR footprints.

Rules (directive §1): file URLs come only from the dataset's tab export (`?format=textfile`), verbatim; a row
whose URL does not end in its own file name is reported and skipped; never a directory URL; `.all` only,
never `.wcd`.  Each HR footprint is buffered by the repo's nav-subset rule (4 km).

* M114/1 (864677): per-file WKT ship track intersects the buffered footprint (fallback: the row's
  east/west/south/north bounds box where the WKT is missing or invalid).
* M112/1 (892317): the table carries no geometry.  This script only emits the ordered `.all` candidate list
  (start time from the Kongsberg file name); `m112_positions.py` derives positions and writes the selection.

Outputs (report dir): pangaea_selection_<cruise>.csv, pangaea_selection_<cruise>_urls.txt,
pangaea_selection_summary.json (+ pangaea_892317_all_candidates.csv for the positions step).
Usage: python -m src.acq_r03.pangaea_select [--cruise PANGAEA_864677]
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd
from shapely import wkt as shp_wkt
from shapely.geometry import box
from shapely.ops import transform as shp_transform

from src.acq_r03 import common as R


def rows_with_urls(df: pd.DataFrame, info: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Keep rows whose complete URL ends in the row's own file name; report the others."""
    name_c, url_c, size_c = info["name_col"], info["url_col"], info["size_col"]
    df = df[df[url_c].astype(str).str.startswith("http")].copy()
    ok, bad = [], []
    for i, r in df.iterrows():
        name, url = str(r[name_c]).strip(), str(r[url_c]).strip()
        if not name or not url.endswith("/" + name):
            bad.append({"row": int(i), "file_name": name, "url": url, "reason": "url does not end in the row's file name"})
            continue
        if not name.lower().endswith(".all"):
            continue                          # .wcd (water column) and anything else: never fetched
        ok.append({"file_name": name, "advertised_kbyte": float(r[size_c]), "advertised_bytes": R.kbyte_to_bytes(r[size_c]),
                   "url": url, "start_time": R.kongsberg_start_time(name), "_row": int(i)})
    return pd.DataFrame(ok), bad


def select_m114(df: pd.DataFrame, info: dict):
    poly, epsg, area_km2, buf_km2 = R.hr_footprint_buffered(info["hr"])
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform
    cand, bad = rows_with_urls(df, info)
    geoms, methods = [], []
    raw = df.set_index(df.index)
    for _, r in cand.iterrows():
        row = raw.loc[r["_row"]]
        g = None
        w = str(row.get(info["geometry"], "")).strip()
        if w.upper().startswith(("LINESTRING", "MULTILINESTRING", "POINT")):
            try:
                g = shp_wkt.loads(w); methods.append("wkt_track")
            except Exception:
                g = None
        if g is None or g.is_empty:
            try:
                g = box(float(row["Longitude west"]), float(row["Latitude south"]), float(row["Longitude east"]), float(row["Latitude north"]))
                methods.append("bounds_box")
            except Exception:
                g = None; methods.append("no_geometry")
        geoms.append(shp_transform(tr, g) if g is not None else None)
    cand["geometry_method"] = methods
    cand["selected"] = [bool(g is not None and g.intersects(poly)) for g in geoms]
    cand["min_dist_to_buffered_footprint_m"] = [round(float(g.distance(poly)), 1) if g is not None else None for g in geoms]
    return cand, bad, {"hr": info["hr"], "utm": epsg, "hr_footprint_km2": round(area_km2, 3), "buffered_km2": round(buf_km2, 3),
                       "buffer_m": R.BUFFER_M, "method": "per-file WKT ship track ∩ buffered footprint (fallback: bounds box)",
                       "geometry_methods": pd.Series(methods).value_counts().to_dict()}


def publish(cruise: str, sel: pd.DataFrame, info: dict, method_note: dict, bad: list, n_all: int, bytes_all: int):
    R.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    s = sel[sel.selected].sort_values("file_name")
    out = s[["file_name", "advertised_kbyte", "advertised_bytes", "url"]].rename(columns={"advertised_kbyte": "advertised_size_kbyte", "advertised_bytes": "advertised_size_bytes"})
    out.to_csv(R.REPORT_DIR / f"pangaea_selection_{cruise}.csv", index=False)
    (R.REPORT_DIR / f"pangaea_selection_{cruise}_urls.txt").write_text("".join(u + "\n" for u in out.url))
    sel.drop(columns=["_row"], errors="ignore").to_csv(R.REPORT_DIR / f"pangaea_candidates_{cruise}.csv", index=False)
    summ = {"cruise_dir": cruise, "dataset": info["dataset"], "doi": info["doi"], "cruise": info["cruise"], "unit": info["unit"], "hr": info["hr"],
            "n_all_files_whole_cruise": int(n_all), "gb_whole_cruise": round(bytes_all / 1e9, 3),
            "n_selected": int(len(out)), "gb_selected": round(float(out.advertised_size_bytes.sum()) / 1e9, 3),
            "rows_skipped_url_name_mismatch": bad, "selection": method_note, "generated": R.utc_now(),
            "files": {"csv": f"pangaea_selection_{cruise}.csv", "urls": f"pangaea_selection_{cruise}_urls.txt", "candidates": f"pangaea_candidates_{cruise}.csv"}}
    p = R.REPORT_DIR / "pangaea_selection_summary.json"
    allsum = json.loads(p.read_text()) if p.exists() else {}
    allsum[cruise] = summ
    R.write_json(p, allsum)
    return summ


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", default="PANGAEA_864677,PANGAEA_892317")
    a = ap.parse_args(argv)
    for cruise in a.cruise.split(","):
        info = R.PANGAEA_UNITS[cruise]
        df = R.parse_tab_export(R.fetch_tab_export(info["dataset"]))
        if cruise == "PANGAEA_864677":
            cand, bad, note = select_m114(df, info)
            n_all, b_all = len(cand), int(cand.advertised_bytes.sum())
            summ = publish(cruise, cand, info, note, bad, n_all, b_all)
        else:
            cand, bad = rows_with_urls(df, info)
            cand = cand.sort_values("start_time").reset_index(drop=True)
            cand.drop(columns=["_row"]).to_csv(R.REPORT_DIR / f"pangaea_{info['dataset']}_all_candidates.csv", index=False)
            summ = {"cruise_dir": cruise, "n_all_files_whole_cruise": int(len(cand)), "gb_whole_cruise": round(cand.advertised_bytes.sum() / 1e9, 3),
                    "rows_skipped_url_name_mismatch": bad, "status": "candidates only; positions from m112_positions.py",
                    "n_wcd_rows_excluded": int((df["File format"].str.upper() == "WCD").sum())}
            p = R.REPORT_DIR / "pangaea_selection_summary.json"
            allsum = json.loads(p.read_text()) if p.exists() else {}
            allsum[cruise] = {**allsum.get(cruise, {}), **summ}
            R.write_json(p, allsum)
        print(json.dumps({k: v for k, v in summ.items() if k != "rows_skipped_url_name_mismatch"}, indent=1, default=str))
        print("rows skipped (url/name mismatch):", len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
