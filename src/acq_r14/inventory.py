"""ACQ-R14 step 1: inventory of every pair in the release (directive section 1) with its sources on OAK, its manifest
row, its co-registration / k / datum / scoring records and its exclusion reason. Reads only; writes
reports_post_grl_review/ACQ-R14/inventory.json. Light enough for a login node (manifests + small JSON/CSV records).

    python -B -m src.acq_r14.inventory
"""
from __future__ import annotations
import csv, glob, re, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np, pandas as pd
from . import common as C

MAN = C.REPO / "manifest"
DISC = C.REPO / "reports" / "discovery"
R02H = C.REPO / "reports_post_grl_review" / "ACQ-R02" / "harmonize"
R08B = C.REPO / "reports_post_grl_review" / "ACQ-R08b"
MGDS_CACHE = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/discovery_cache/acq_r08_2026-10-12/mgds")
PER_PAIR = {"development": C.ARCH / "R11/rehearsal/scores/per_pair_D1.csv",
            "blind_test_1": C.ARCH / "phase4/scores/per_pair_D1.csv",
            "blind_test_2": C.ARCH / "phase5/scores/per_pair_D1.csv"}
RASTERS = ("hr", "lr", "hr_valid", "lr_valid", "joint_valid")


def _row(df: pd.DataFrame, pid: str) -> dict | None:
    r = df[df.pair_id == pid]
    if len(r) == 0:
        return None
    d = r.iloc[0].to_dict()
    return {k: (None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v)) for k, v in d.items()}


def _resolve(p) -> Path | None:
    if p is None or p == "":
        return None
    q = Path(str(p))
    if q.is_absolute():
        if q.exists():
            return q
        # June-era rows carry scratch paths; the OAK copy is the canonical one (same relative layout)
        s = str(q)
        for root in ("/scratch/groups/hilley/auv_ship_colocated_bathy/", "/oak/stanford/groups/hilley/auv_ship_colocated_bathy/"):
            if s.startswith(root):
                cand = C.OAK / s[len(root):]
                if cand.exists():
                    return cand
        return None
    cand = C.OAK / q
    return cand if cand.exists() else None


def _records_by_pair() -> dict[str, dict]:
    """Index every development-era harmonization/co-registration record by pair_id."""
    out: dict[str, dict] = {}

    def add(kind, rec):
        if isinstance(rec, dict) and "pair_id" in rec:
            out.setdefault(rec["pair_id"], {})[kind] = rec

    def walk(kind, obj):
        if isinstance(obj, list):
            for x in obj:
                walk(kind, x)
        elif isinstance(obj, dict):
            if "pair_id" in obj:
                add(kind, obj)
            else:
                for v in obj.values():
                    walk(kind, v)

    for kind, name in (("stage_f", "stage_f_results.json"), ("stage_f5", "stage_f5_results.json"), ("stage_f_repair", "stage_f_repair_results.json"),
                       ("stage_c1", "stage_c1_harmonize_results.json"), ("stage_c1", "stage_c1_phase1_results.json"),
                       ("stage_c1", "stage_c1_arctic_harmonize.json")):
        p = DISC / name
        if p.exists():
            walk(kind, C.jload(p))
    for p in sorted(R02H.glob("*.json")):
        add("acq_r02", C.jload(p))
    return out


def _mgds_catalog() -> dict[str, dict]:
    """MGDS data-set uid -> {title, doi} from the ACQ-R08 harvest of the MGDS data service (API output, cached)."""
    out = {}
    for p in sorted(MGDS_CACHE.glob("*.xml")) if MGDS_CACHE.exists() else []:
        try:
            root = ET.fromstring(p.read_bytes())
        except ET.ParseError:
            continue
        for el in root.iter():
            if el.tag.split("}")[-1] == "data_set" and el.get("uid"):
                out.setdefault(el.get("uid"), {"title": el.get("title"), "doi": el.get("data_doi"), "created": el.get("created"),
                                               "investigators": el.get("investigators"), "release_date": el.get("release_date")})
    return out


def _coreg_from_notes(notes: str | None) -> dict | None:
    m = re.search(r"dx=(-?[\d.]+) m, dy=(-?[\d.]+) m, dz=(-?[\d.]+) m", notes or "")
    if not m:
        return None
    return {"dx_m": float(m.group(1)), "dy_m": float(m.group(2)), "dz_m": float(m.group(3)), "source": "manifest notes (Cal DIG offset correction)"}


def _vcheck() -> dict[str, dict]:
    p = C.REPO / "reports_post_grl_review/ACQ-R11b/vcheck_calibration_v2.csv"
    out = {}
    with open(p) as f:
        for r in csv.DictReader(f):
            out[r["pair_id"]] = r
    return out


def _per_pair() -> dict[str, dict]:
    out = {}
    for group, p in PER_PAIR.items():
        df = pd.read_csv(p)
        for _, r in df.iterrows():
            d = {k: C.nan_to_none(v.item() if hasattr(v, "item") else v) for k, v in r.to_dict().items()}
            d["_group"], d["_source"] = group, str(p.relative_to(C.ARCH))
            out[d["pair"]] = d
    return out


def _r08b_candidates() -> dict[str, dict]:
    df = pd.read_csv(R08B / "candidates_measured.csv")
    return {r.hr_id: r.to_dict() for _, r in df.iterrows()}


def _dir_sizes(d: Path) -> dict:
    out = {}
    for k in RASTERS:
        p = d / f"{k}.tif"
        out[k] = p.stat().st_size if p.exists() else None
    return out


def build_inventory() -> dict:
    v21 = pd.read_parquet(MAN / "pairs_v2_1.parquet")
    p4 = pd.read_parquet(MAN / "pairs_phase4_sealed.parquet")
    p5 = pd.read_parquet(MAN / "pairs_phase5_sealed_v4_1.parquet")
    dropped = pd.read_csv(MAN / "pairs_v2_1_dropped.csv")
    recs, cat, vch, pp, r08b = _records_by_pair(), _mgds_catalog(), _vcheck(), _per_pair(), _r08b_candidates()
    raw_meta = {s: C.jload(C.OAK / "raw" / s / "metadata.json") for s in ("cal_dig_morro_bay", "ccz_so268_1", "discol_so242_1", "tag_m127")
                if (C.OAK / "raw" / s / "metadata.json").exists()}
    entries = []

    def base(pid, group, role, unit, unit_class):
        return {"pair_id": pid, "group": group, "role": role, "unit": unit, "unit_class": unit_class, "in_corpus": True,
                "exclusion_reason": None, "src_dir": None, "rasters": {}, "sizes": {}, "products_dir": None,
                "products_usable": None, "products_reason": None, "manifest": None, "records": {}, "mgds": None,
                "raw_metadata": None, "datum_G": None, "scoring": pp.get(pid)}

    # ---- development: 38 units-v1 pairs + EW0207 ---------------------------------------------------------------
    for pid in C.DEV_PAIRS:
        unit = C.UNIT_OF[pid]
        ucls = "EW0207" if unit == "lu16" else ("ten" if unit in C.TEN else "six")
        e = base(pid, "development", "development" if unit != "lu16" else "development (EW0207, scored separately)", unit, ucls)
        e["manifest"] = _row(v21, pid)
        if e["manifest"] is None:
            raise SystemExit(f"{pid}: not in pairs_v2_1.parquet")
        e["records"] = recs.get(pid, {})
        cn = _coreg_from_notes(e["manifest"].get("notes"))
        if cn:
            e["records"]["notes_coreg"] = cn
        entries.append(e)

    # ---- blind test 1 (Phase 4): 3 confirmatory + 2 lockbox -----------------------------------------------------
    for pid, unit in list(C.CONFIRMATORY.items()) + list(C.LOCKBOX.items()):
        role = "confirmatory" if pid in C.CONFIRMATORY else "lockbox"
        e = base(pid, "blind_test_1", role, unit, role)
        e["manifest"] = _row(p4, pid)
        e["records"] = dict(recs.get(pid, {}))
        entries.append(e)

    # ---- blind test 2 (Phase 5): all 8 candidate sites ---------------------------------------------------------
    for pid in C.PHASE5:
        m = _row(p5, pid)
        e = base(pid, "blind_test_2", "candidate", m["leakage_unit"], "candidate")
        e["manifest"] = m
        hr_id = m["hr_doi"]  # "MGDS:<id>"
        e["r08b"] = {k: C.nan_to_none(v) for k, v in r08b.get(hr_id, {}).items() if k in
                     ("hr_id", "lr_cruise", "lr_sonar", "lr_year", "doi", "title", "releasable", "hr_res_m", "status", "status_reason")}
        entries.append(e)

    # ---- resolve sources, records and metadata for every in-corpus entry ---------------------------------------
    for e in entries:
        m, pid = e["manifest"], e["pair_id"]
        hr = _resolve(m.get("harmonized_path_hr"))
        if hr is None:
            raise SystemExit(f"{pid}: harmonized hr not found: {m.get('harmonized_path_hr')}")
        d = hr.parent
        e["src_dir"] = str(d)
        for k in RASTERS:
            p = d / f"{k}.tif"
            e["rasters"][k] = str(p) if p.exists() else None
        e["sizes"] = _dir_sizes(d)
        missing = [k for k in RASTERS if e["rasters"][k] is None]
        if missing:
            raise SystemExit(f"{pid}: missing rasters {missing} in {d}")
        # per-pair records next to the grids
        for name in ("step1_record.json", "sweep_record.json", "site_record.json", "grid_record.json", "hr_selection.json", "footprint.geojson"):
            if (d / name).exists():
                e["records"][name.split(".")[0]] = str(d / name)
        if (d / "review" / "shift_vector.json").exists():
            e["records"]["shift_vector"] = C.jload(d / "review" / "shift_vector.json")
        # ship products (contract v2.1), only where usable
        pdir = d / "ship_products_v2_1"
        usable, reason = m.get("ship_products_usable"), m.get("ship_products_usable_reason")
        if usable is None and e["group"] == "blind_test_2" and "site_record" in e["records"]:
            sr = C.jload(Path(e["records"]["site_record"]))
            usable, reason = sr.get("usable"), sr.get("usable_reason")
        e["products_usable"] = bool(usable) if usable is not None else False
        e["products_reason"] = reason
        e["products_dir"] = str(pdir) if (e["products_usable"] and pdir.exists()) else None
        if e["products_usable"] and not pdir.exists():
            C.fix("inventory", pid, "ship_products_usable is True but ship_products_v2_1/ is absent; shipped without ship products")
            e["products_usable"], e["products_reason"] = False, "ship_products_v2_1 directory absent at release time"
        # MGDS catalogue entry for the HR grid
        mm = re.search(r"__MGDS_(\d+)$", pid)
        if mm:
            e["mgds"] = {"uid": mm.group(1), **cat.get(mm.group(1), {})}
        # provider raw metadata (PANGAEA / USGS) for citation + license
        site = pid.split("__")[0] if pid.startswith("cal_dig_morro_bay") else pid
        if site in raw_meta:
            rm = raw_meta[site]
            e["raw_metadata"] = {role: {k: v for k, v in rm[role].items() if k in ("doi", "provider", "citation", "license", "landing_url", "primary_url", "source_urls")}
                                 for role in ("hr", "lr") if role in rm}
        # datum statistic G (development calibration table; Phase 5 records hold the boolean only)
        if pid in vch:
            r = vch[pid]
            e["datum_G"] = {"G_V95_rel": float(r["G_V95_rel"]) if r["G_V95_rel"] else None, "V95_m": float(r["V95_m"]) if r["V95_m"] else None,
                            "G_below_T_G": r["G_below_T_G"] == "True", "set": r["set"], "L_status": r["L_status"], "source": "ACQ-R11b/vcheck_calibration_v2.csv"}

    # ---- rows without rasters --------------------------------------------------------------------------------
    drop_reason = {r.pair_id: r.reason for _, r in dropped.iterrows()}
    for pid, (kind, reason) in C.EXCLUDED.items():
        e = base(pid, "excluded", kind, None, None)
        e["in_corpus"] = False
        e["exclusion_reason"] = reason if pid not in drop_reason else f"{drop_reason[pid]} | {reason}"
        e["manifest"] = _row(v21, pid)
        if e["manifest"]:
            e["unit"] = e["manifest"].get("leakage_unit")
        e["scoring"] = None
        entries.append(e)

    inv = {"generated": C.utcnow(), "directive": C.DIRECTIVE_ID, "release_version": C.RELEASE_VERSION,
           "counts": {"development": sum(e["group"] == "development" for e in entries),
                      "blind_test_1": sum(e["group"] == "blind_test_1" for e in entries),
                      "blind_test_2": sum(e["group"] == "blind_test_2" for e in entries),
                      "excluded": sum(e["group"] == "excluded" for e in entries)},
           "sources": {"pairs_v2_1": C.sha256(MAN / "pairs_v2_1.parquet"), "pairs_phase4_sealed": C.sha256(MAN / "pairs_phase4_sealed.parquet"),
                       "pairs_phase5_sealed_v4_1": C.sha256(MAN / "pairs_phase5_sealed_v4_1.parquet"),
                       **{f"per_pair_{g}": C.sha256(p) for g, p in PER_PAIR.items()}},
           "entries": entries}
    return inv


def main():
    inv = build_inventory()
    C.jdump(inv, C.INVENTORY)
    tot = sum(sum(v for v in e["sizes"].values() if v) for e in inv["entries"] if e["in_corpus"])
    C.log(f"inventory: {inv['counts']} ; raster bytes (5 grids per pair, before COG) = {tot / 1e9:.2f} GB -> {C.INVENTORY}")
    for e in inv["entries"]:
        if e["in_corpus"]:
            print(f"  {e['group']:13s} {e['pair_id']:48s} unit={e['unit']:6s} products={'Y' if e['products_dir'] else 'n'} "
                  f"records={sorted(e['records'])} scoring={'Y' if e['scoring'] else 'n'}")


if __name__ == "__main__":
    main()
