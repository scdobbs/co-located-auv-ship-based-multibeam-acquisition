"""C1 float-grid re-harvest — Step 1: download float Grid datasets + render-gate
+ reader-proof FIRST (before any gridding/harmonizing).

Reuse, not new code:
  - MGDS file download via phase1's Document_Accept.php pattern + geoms cache.
  - render gate: src/discovery/hr_format_gate (is_rgb_visualization/is_float_elevation).
  - reader: gmt_grd / rasterio(NETCDF:) / netCDF4 to get real depth stats (R0 standard).

Per the directive's skepticism note: the catalog calls these "Grid", but the
catalog also mislabeled the renders. PROVE each is real float elevation at the
byte + depth level here; if a "float" is actually a 3-band render, STOP it and
report — do not grid/harmonize.

Downloads to $DATA_ROOT/reharvest_c1/MGDS_<uid>/. Run on a compute node (egress).
"""
from __future__ import annotations
import gzip, json, logging, os, re, shutil
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import requests

from src.discovery.hr_format_gate import is_rgb_visualization, is_float_elevation
from src import gmt_grd

log = logging.getLogger("c1")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
OUT = DATA / "reharvest_c1"
GEOMS = DATA / "discovery_cache/mgds/mgds_AUV_Bathymetry_geoms.xml"
RESULT = REPO / "reports/discovery/stage_c1_reharvest_gate.json"
NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
MGDS_DOWNLOAD = "https://api.marine-geo.org/services/download/Document_Accept.php"
MGDS_PARAMS = {"client": "DataLink"}

# netCDF-preferred dataset per site (the directive's first-listed uids); ASCII
# fallbacks (32557/30218/30046/24619) only if the netCDF fails the gate.
CANDIDATES = [
    {"site": "Beaufort_Amundsen", "uid": "31753", "fmt": "netCDF", "lr_cruise": "2009_Amundsen", "site_depth_m": 586},
    {"site": "Axial_Seamount", "uid": "32556", "fmt": "netCDF", "lr_cruise": "EW0207/EW9904/TN383", "site_depth_m": 1500},
    {"site": "SantaMonica_Mound", "uid": "32319", "fmt": "grid", "lr_cruise": "NA076", "site_depth_m": 866},
    {"site": "SantaMonica_Mound", "uid": "32317", "fmt": "grid", "lr_cruise": "NA076", "site_depth_m": 866},
    {"site": "Pescadero_Basin", "uid": "24618", "fmt": "netCDF", "lr_cruise": "FK181031", "site_depth_m": 3788},
    {"site": "Cascadia_Pythia", "uid": "31253", "fmt": "netCDF", "lr_cruise": "TN299", "site_depth_m": 1087},
]


def files_for(uid):
    root = ET.fromstring(GEOMS.read_bytes())
    out = []
    for f in root.find("m:files", NS) or []:
        if f.get("data_set_uid") != uid:
            continue
        fi = f.find("m:file_info", NS)
        sz = int(fi.get("data_file_size") or 0) if fi is not None else 0
        if f.get("data_uid"):
            out.append((f.get("data_uid"), sz))
    return out


def download(data_uid, expected, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    # idempotent: skip if a file for this data_uid already present at ~expected size
    for ex in dest_dir.glob(f"*__uid{data_uid}*"):
        if ex.stat().st_size > 0 and (expected == 0 or abs(ex.stat().st_size - expected) < max(1024, 0.02 * expected)):
            return ex, "cached"
    r = requests.get(MGDS_DOWNLOAD, params={**MGDS_PARAMS, "data_uid": data_uid},
                     timeout=600, stream=True, headers={"User-Agent": "auv-ship-acq/0.1 (Sherlock)"})
    r.raise_for_status()
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^";]+)"?', cd)
    name = m.group(1) if m else f"data_uid_{data_uid}.bin"
    name = f"{Path(name).stem}__uid{data_uid}{Path(name).suffix or '.bin'}"
    dest = dest_dir / name
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    return dest, "downloaded"


def decompress(path: Path) -> Path:
    """If gzip-compressed (MGDS serves .grd.gz/.asc.gz), decompress to a sibling
    file (persisted on scratch for reuse) and return it; else return as-is."""
    with open(path, "rb") as f:
        magic = f.read(2)
    if magic != b"\x1f\x8b":
        return path
    out = path.with_name(re.sub(r"\.gz$", "", path.name))
    if out.suffix.lower() not in (".grd", ".asc", ".nc", ".tif", ".tiff"):
        out = out.with_suffix(".grd")          # MGDS bathy grids
    if out.exists() and out.stat().st_size > 0:
        return out
    with gzip.open(path, "rb") as fi, open(out, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
    return out


def depth_stats(path: Path, tmp: Path):
    """Robust read to real depth percentiles across .grd/.nc/.asc/.tif."""
    import rasterio
    arr = None; reader = None
    # 1) GMT classic .grd
    try:
        if gmt_grd.is_gmt_grd(path):
            out = tmp / (path.stem + ".tif")
            gmt_grd.convert(path, out, crs="EPSG:4326")
            with rasterio.open(out) as ds:
                a = ds.read(1).astype("float64"); nd = ds.nodata
            arr = np.where((nd is not None) & np.isclose(a, nd if nd is not None else -9999, atol=1e-3), np.nan, a)
            reader = "gmt_grd"
    except Exception:
        pass
    # 2) rasterio direct / NETCDF:
    if arr is None:
        for cand in (str(path), "NETCDF:" + str(path)):
            try:
                with rasterio.open(cand) as ds:
                    a = ds.read(1).astype("float64"); nd = ds.nodata
                if nd is not None:
                    a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
                arr = a; reader = "rasterio:" + ("netcdf" if cand.startswith("NETCDF") else "direct")
                break
            except Exception:
                continue
    # 3) netCDF4 z var
    if arr is None:
        try:
            import netCDF4 as nc
            with nc.Dataset(str(path)) as ds:
                zname = next((v for v in ("z", "Band1", "elevation", "depth", "topo") if v in ds.variables), None)
                if zname:
                    a = np.asarray(ds.variables[zname][:], dtype="float64")
                    arr = np.where(np.isfinite(a), a, np.nan); reader = f"netCDF4:{zname}"
        except Exception:
            pass
    if arr is None:
        return {"reader": None, "error": "unreadable by gmt/rasterio/netCDF4"}
    v = arr[np.isfinite(arr)]
    if v.size > 5_000_000:
        v = v[:: v.size // 5_000_000 + 1]
    if v.size == 0:
        return {"reader": reader, "error": "no finite values"}
    return {"reader": reader, "n_finite": int(v.size),
            "min": round(float(v.min()), 2), "p1": round(float(np.percentile(v, 1)), 2),
            "p50": round(float(np.percentile(v, 50)), 2), "p99": round(float(np.percentile(v, 99)), 2),
            "max": round(float(v.max()), 2),
            "frac_negative": round(float((v < 0).mean()), 3),
            "frac_0_255": round(float(((v >= 0) & (v <= 255)).mean()), 3)}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "c1"; tmp.mkdir(parents=True, exist_ok=True)
    results = []
    for c in CANDIDATES:
        uid = c["uid"]; dest_dir = OUT / f"MGDS_{uid}"
        rec = {**c, "files": []}
        log.info("=== %s ds=%s (%s) ===", c["site"], uid, c["fmt"])
        for data_uid, sz in files_for(uid):
            try:
                raw, how = download(data_uid, sz, dest_dir)
                path = decompress(raw)
            except Exception as e:
                rec["files"].append({"data_uid": data_uid, "error": f"download: {str(e)[:80]}"}); continue
            # skip change-detection difference grids (not bathymetry)
            if re.search(r"diff", path.name, re.I):
                rec["files"].append({"data_uid": data_uid, "file": path.name, "GATE": "SKIP_diff_grid",
                                     "note": "change-detection difference grid, not depth"}); continue
            render, why = is_rgb_visualization(path)
            fr = {"data_uid": data_uid, "file": path.name, "size_mb": round(path.stat().st_size / 1e6, 1),
                  "fetch": how, "is_rgb_render": render, "render_reason": why}
            if render:
                fr["GATE"] = "FAIL_render"          # STOP: a "Grid" that is actually a render
            else:
                fr["is_float_elevation"] = is_float_elevation(path)
                fr["depth_stats"] = depth_stats(path, tmp)
                ds_ = fr["depth_stats"]
                # reader-proof verdict: real negative depths, not 0-255 byte cluster,
                # within plausible range of the site depth
                p50 = ds_.get("p50")
                plausible = bool(p50 is not None and p50 < -10
                                 and ds_.get("frac_negative", 0) > 0.8
                                 and abs(abs(p50) - c["site_depth_m"]) < max(800, 0.6 * c["site_depth_m"]))
                fr["GATE"] = "PASS_float_elevation" if plausible else "REVIEW_depth_mismatch"
                fr["site_depth_expected_m"] = c["site_depth_m"]
            rec["files"].append(fr)
            log.info("  %-40s %s p50=%s", fr["file"][:40], fr.get("GATE"),
                     fr.get("depth_stats", {}).get("p50"))
        # dataset-level verdict
        gates = [f.get("GATE") for f in rec["files"]]
        rec["dataset_verdict"] = ("FAIL_render" if any(g == "FAIL_render" for g in gates)
                                  else "PASS" if any(g == "PASS_float_elevation" for g in gates)
                                  else "REVIEW")
        results.append(rec)
    RESULT.write_text(json.dumps(results, indent=2, default=str))
    log.info("=== SUMMARY ===")
    for r in results:
        log.info("  %-20s ds=%s -> %s", r["site"], r["uid"], r["dataset_verdict"])
    log.info("wrote %s", RESULT)


if __name__ == "__main__":
    main()
