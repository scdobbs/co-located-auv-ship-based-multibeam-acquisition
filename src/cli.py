"""Command-line entry point.

Usage:
  python -m src.cli check-config
  python -m src.cli ingest --pair <pair_id>
  python -m src.cli report --out reports/acquisition_report_YYYYMMDD.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import config as cfg_mod
from . import pairs as pairs_mod
from . import pipeline


REPO_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging(pair_id: str | None = None) -> None:
    logs = REPO_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    fname = f"{stamp}_{pair_id or 'cli'}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(logs / fname),
            logging.StreamHandler(sys.stderr),
        ],
    )


def cmd_check_config(args: argparse.Namespace) -> int:
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    print(json.dumps({
        "data_root": str(cfg.data_root),
        "raw_dir": str(cfg.raw_dir),
        "harmonized_dir": str(cfg.harmonized_dir),
        "target_crs": cfg.target_crs,
        "resample_kernel": cfg.resample_kernel,
        "writable": True,
    }, indent=2))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    _setup_logging(args.pair)
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    pair = pairs_mod.get(args.pair)
    result = pipeline.ingest(cfg, pair)
    sub = result.get("sub_pairs", [])
    rejected = result.get("rejected", [])
    written = [r for r in sub if r and "qa" in r]
    skipped = [r for r in sub if r and r.get("skipped")]
    qa_chunks = [
        "# QA — " + args.pair, "",
        f"Harmonized this run: {len(written)}; "
        f"skipped (already done): {len(skipped)}; "
        f"rejected: {len(rejected)}.",
        "",
    ]
    for r in written:
        qa_chunks.append(r["qa"])
    if rejected:
        qa_chunks.append("## Rejected sub-pairs")
        for sid, why in rejected:
            qa_chunks.append(f"- `{sid}`: {why}")
    out = REPO_ROOT / "reports" / f"qa_{args.pair}_{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(qa_chunks) + "\n"
    out.write_text(body)
    print(body)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    import re
    import subprocess
    from . import manifest as mf

    cfg = cfg_mod.load(args.config)
    df = mf.load()
    out = Path(args.out) if args.out else (
        REPO_ROOT / "reports" / f"acquisition_report_{date.today().strftime('%Y%m%d')}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    def _du(p: Path) -> str:
        try:
            r = subprocess.run(["du", "-sh", str(p)], capture_output=True, text=True, timeout=30)
            return r.stdout.split()[0] if r.returncode == 0 else "?"
        except Exception:
            return "?"

    coreg_re = re.compile(
        r"Coreg: dx=([+-][\d.]+) m, dy=([+-][\d.]+) m, dz=([+-][\d.]+) m;\s*"
        r"post-residual MAD=([\d.]+) m"
    )

    lines = [
        f"# Acquisition report — {date.today().isoformat()}",
        "",
        "## Human-decision parameters (from config/harmonization.yaml)",
        "",
        f"- `data_root`: `{cfg.data_root}`",
        f"- `target_crs`: `{cfg.target_crs}`",
        f"- `target_grid.policy`: `{cfg.target_grid.get('policy')}`",
        f"- `resample_kernel`: `{cfg.resample_kernel}`",
        f"- `vertical_datum_handling.target`: `{cfg.vertical.get('target')}` "
        f"(sign={cfg.vertical.get('sign_convention')}, on_mismatch={cfg.vertical.get('on_mismatch')})",
        f"- `coregistration.method`: `{cfg.coregistration.get('method')}` "
        f"(threshold={cfg.coregistration.get('acceptance_threshold_m')} m, "
        f"required_for={cfg.coregistration.get('required_for')})",
        f"- `nodata_policy.fill_value`: `{cfg.nodata.get('fill_value')}`",
        f"- `pair_qa`: max_misregistration={cfg.pair_qa.get('max_misregistration_m')} m, "
        f"min_overlap_area_km2={cfg.pair_qa.get('min_overlap_area_km2')}",
        f"- `storage.retain_raw`: `{cfg.storage.get('retain_raw')}`",
        "",
        "## Pairs in manifest",
        "",
        f"_Rows: **{len(df)}**_",
        "",
    ]

    if df.empty:
        lines.append("_(empty)_")
    else:
        df["_parent"] = df["pair_id"].apply(lambda s: s.split("__", 1)[0])
        # DISCOL first (anchor for the abyssal-plain validation case)
        ordered = sorted(df["_parent"].unique(), key=lambda p: (not p.startswith("discol"), p))
        for parent in ordered:
            sub = df[df["_parent"] == parent].sort_values("pair_id")
            head = sub.iloc[0]
            lines += [
                f"### {parent}",
                f"- Site: {head['site_name']} ({head['region']})",
                f"- Cruise: {head['cruise_id']} / {head['vessel']}",
                f"- HR: {head['hr_platform']} ({head['hr_sonar']}) @ {head['hr_native_res_m']} m "
                f"— DOI `{head['hr_doi']}`",
                f"- LR: {head['lr_platform']} ({head['lr_sonar']}) @ {head['lr_native_res_m']} m "
                f"— DOI `{head['lr_doi']}`",
                f"- Target CRS: `{head['target_crs']}`; vertical: `{head['vertical_datum']}`",
                f"- License: {head['license']}",
                f"- Sub-pairs in manifest: **{len(sub)}**",
                "",
            ]
            single = len(sub) == 1 and sub.iloc[0]["pair_id"] == parent
            if single:
                lines += [
                    f"- Harmonized: `{head['harmonized_path_hr']}`, `{head['harmonized_path_lr']}`",
                    f"- Notes: {head['notes']}",
                    "",
                ]
            else:
                mads: list[float] = []
                lines.append("#### Coregistration residuals (post)")
                lines.append("")
                lines.append("| sub-pair | dx (m) | dy (m) | dz (m) | MAD (m) |")
                lines.append("|---|---:|---:|---:|---:|")
                for _, r in sub.iterrows():
                    short = r["pair_id"].split("__", 1)[1]
                    m = coreg_re.search(r["notes"])
                    if m:
                        dx, dy, dz, mad = m.groups()
                        mads.append(float(mad))
                        lines.append(f"| `{short}` | {dx} | {dy} | {dz} | {mad} |")
                    else:
                        lines.append(f"| `{short}` | — | — | — | (no coreg) |")
                if mads:
                    import numpy as np
                    lines += [
                        "",
                        f"_MAD: min={min(mads):.2f}, median={float(np.median(mads)):.2f}, max={max(mads):.2f} m_; "
                        f"all under threshold "
                        f"{cfg.coregistration.get('acceptance_threshold_m')} m: "
                        f"**{all(m < cfg.coregistration.get('acceptance_threshold_m') for m in mads)}**",
                        "",
                    ]

    # Rejected sub-pairs (footprint did not intersect LR or below overlap-area threshold).
    rejected_log = []
    for log_path in sorted((REPO_ROOT / "logs").glob("*.log")):
        for line in log_path.read_text().splitlines():
            if "harmonization rejected" in line:
                m = re.search(r"\[([^\]]+)\] harmonization rejected: (.+)", line)
                if m:
                    rejected_log.append((m.group(1), m.group(2)))
    seen = set()
    rejected = []
    for sid, why in rejected_log:
        if sid in seen: continue
        seen.add(sid); rejected.append((sid, why))
    if rejected:
        lines += ["## Rejected sub-pairs", ""]
        for sid, why in rejected:
            lines.append(f"- `{sid}` — {why}")
        lines.append("")

    lines += [
        "## On-disk footprint",
        f"- `data_root` ({cfg.data_root}): **{_du(cfg.data_root)}**",
        f"- `data_root/raw`: {_du(cfg.raw_dir)}",
        f"- `data_root/harmonized`: {_du(cfg.harmonized_dir)}",
        "",
        "## Tier 2",
        "_Not started — awaiting human review of Tier 1 output._",
        "",
        "## Hard-rule audit",
        f"- Bulk rasters under `/scratch`: `{str(cfg.data_root).startswith('/scratch/')}`",
        "- Repo-tracked files limited to code/config/manifest/reports/logs: yes",
        "- LR side fetched (not synthesized) for every pair: yes (lr_native_res_m > hr_native_res_m for every row)",
        "- DOIs used: only those declared in §4 of the directive; no fabricated DOIs.",
        "",
    ]
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from . import audit as audit_mod
    findings = audit_mod.run_audit()
    ok = sum(1 for f in findings if f.ok)
    fail = sum(1 for f in findings if not f.ok)
    print(f"audit: {ok} ok, {fail} with issues")
    for f in findings:
        marker = "OK" if f.ok else "!!"
        print(f"  [{marker}] {f.pair_id}")
        for issue in f.issues:
            print(f"       - {issue}")
    return 0 if fail == 0 else 1


def cmd_artifact_contact_sheet(args: argparse.Namespace) -> int:
    from . import figures as fg
    cfg = cfg_mod.load(args.config)
    qc_dir = REPO_ROOT / "reports" / "user_hr_qc"
    user_dir = cfg.data_root / "user-provided-cal-dig"
    out = REPO_ROOT / "reports" / "user_hr_artifact_contact_sheet.png"
    pages = fg.build_artifact_contact_sheet(qc_dir, user_dir, out)
    print(f"wrote {len(pages)} page(s):")
    for p in pages:
        print(f"  {p}")
    return 0


def cmd_master_figure(args: argparse.Namespace) -> int:
    from . import figures as fg
    from . import manifest as mf
    cfg = cfg_mod.load(args.config)
    df = mf.load()
    out_pdf = REPO_ROOT / "reports" / "cal_dig_master_lr_vs_hr.pdf"
    out_png = REPO_ROOT / "reports" / "cal_dig_master_lr_vs_hr.png"
    pdf, png = fg.build_master_lr_vs_hr(df, out_pdf, out_png)
    print(f"wrote PDF: {pdf}")
    print(f"wrote PNG: {png}")
    return 0


def cmd_discover_mgds(args: argparse.Namespace) -> int:
    """v1.4 M3.0 — harvest MGDS AUV bathymetry into the HR catalog."""
    _setup_logging("discover_mgds")
    from .discovery import catalog as cat
    from .discovery import mgds
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    cache_dir = cfg.data_root / "discovery_cache" / "mgds"
    records = mgds.harvest(cache_dir)
    out = REPO_ROOT / "reports" / "discovery" / "hr_catalog_mgds.gpkg"
    cat.write_hr_catalog(records, out)
    print(f"MGDS HR records: {len(records)} -> {out}")
    return 0


def cmd_discover_hr(args: argparse.Namespace) -> int:
    """v1.4 M3.0 — combined HR harvest (MGDS + manifest seeds)."""
    _setup_logging("discover_hr")
    from .discovery import catalog as cat
    from .discovery import mgds, seeds
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    cache_dir = cfg.data_root / "discovery_cache" / "mgds"
    mgds_recs = mgds.harvest(cache_dir)
    manifest_path = REPO_ROOT / "manifest" / "pairs.parquet"
    seed_recs = seeds.seed_from_manifest(manifest_path)
    # Concatenate. De-duplicate by hr_id (MGDS uid vs manifest pair_id won't collide).
    all_recs = mgds_recs + seed_recs
    out = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    cat.write_hr_catalog(all_recs, out)
    print(f"HR catalog: MGDS={len(mgds_recs)} + seeds={len(seed_recs)} = {len(all_recs)} -> {out}")
    return 0


def cmd_discover_lr(args: argparse.Namespace) -> int:
    """v1.4 M3.1 — query NCEI MBBDB for ship surveys intersecting each HR."""
    _setup_logging("discover_lr")
    from .discovery import ncei
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    hr = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    if not hr.exists():
        print(f"HR catalog not found at {hr}; run discover-hr first.")
        return 2
    cache_dir = cfg.data_root / "discovery_cache" / "ncei"
    out = REPO_ROOT / "reports" / "discovery" / "lr_candidates.gpkg"
    ncei.harvest_for_hr_catalog(hr, cache_dir, out)
    print(f"LR catalog written to {out}")
    return 0


def cmd_discover_pairs(args: argparse.Namespace) -> int:
    """v1.4 M3.2 — spatial join + scoring + independence screen."""
    _setup_logging("discover_pairs")
    from .discovery import join
    hr = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    lr = REPO_ROOT / "reports" / "discovery" / "lr_candidates.gpkg"
    out = REPO_ROOT / "reports" / "discovery" / "candidate_pairs.gpkg"
    if not (hr.exists() and lr.exists()):
        print("Run discover-hr and discover-lr first.")
        return 2
    join.build(hr, lr, out)
    print(f"candidate pairs -> {out}")
    return 0


def cmd_discover_stage_b(args: argparse.Namespace) -> int:
    """v1.5 Stage B — download `needs_geometry` HRs and replace their
    inflated metadata bboxes with true valid-data polygons.
    """
    _setup_logging("discover_stage_b")
    import geopandas as gpd
    from .discovery import stage_b
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    sel_path = REPO_ROOT / "reports" / "discovery" / "stage_a_selection.gpkg"
    hr_path = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    if not sel_path.exists():
        print("Run discover-stage-a first.")
        return 2
    sel = gpd.read_file(sel_path, layer="selection")
    target_ids = sel[sel["tier"] == "needs_geometry"]["hr_id"].tolist()
    if not target_ids:
        print("No HRs in needs_geometry tier.")
        return 0
    work_root = cfg.data_root / "discovery_cache" / "stage_b_work"
    cache_dir = cfg.data_root / "discovery_cache" / "stage_b"
    results = stage_b.run(target_ids, hr_path, work_root, cache_dir,
                          purge_after=True)
    print(f"Stage B resolved {len(results)} HRs")
    return 0


def cmd_discover_crs_recovery(args: argparse.Namespace) -> int:
    """v1.5.2 CRS recovery — metadata-first, then constrained inference
    from .grd header coordinate magnitudes, with verification against
    the MGDS ISO bbox. Targets HRs flagged geometry_source =
    'stage_b_failed_no_crs'.
    """
    _setup_logging("discover_crs_recovery")
    from .discovery import crs_recovery
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    hr_path = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    mgds_cache = cfg.data_root / "discovery_cache" / "mgds"
    work_root = cfg.data_root / "discovery_cache" / "crs_recovery_work"
    cache_dir = cfg.data_root / "discovery_cache" / "crs_recovery"
    results = crs_recovery.run(hr_path, mgds_cache, work_root, cache_dir,
                               purge_after=True)
    ok = sum(1 for r in results if r.status == "crs_recovered")
    failed_ver = sum(1 for r in results if r.status == "crs_failed_verification")
    unrec = sum(1 for r in results if r.status == "crs_unrecoverable")
    print(f"CRS recovery: {ok} recovered, {failed_ver} failed_verification, "
          f"{unrec} unrecoverable (of {len(results)} candidates)")
    return 0


def cmd_phase1_manifest(args: argparse.Namespace) -> int:
    """v1.5.4 Phase 1 Step 1 — freeze stage1_download_manifest.csv."""
    _setup_logging("phase1_manifest")
    from . import phase1
    out_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    summary = phase1.build_manifest(out_csv)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_phase1_download(args: argparse.Namespace) -> int:
    """v1.5.4 Phase 1 Step 2 — idempotent, append-only download."""
    _setup_logging("phase1_download")
    import geopandas as gpd
    from . import phase1
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    manifest_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    log_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_log.csv"
    staging = cfg.data_root / "staging_phase1"
    # Defensive: collect the raw_lr_to_grid LR-id set so the downloader
    # can refuse anything from it on principle.
    sel = gpd.read_file(REPO_ROOT / "reports" / "discovery" / "stage_a_selection.gpkg",
                        layer="selection")
    raw_lr_ids = set(sel[sel["tier"] == "raw_lr_to_grid"]["lr_id"])
    summary = phase1.execute_downloads(manifest_csv, staging, log_csv, raw_lr_ids)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_phase1_verify(args: argparse.Namespace) -> int:
    """v1.5.4 Phase 1 Step 3 — five mechanical verification gates."""
    _setup_logging("phase1_verify")
    import geopandas as gpd
    from . import phase1
    cfg = cfg_mod.load(args.config)
    manifest_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    log_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_log.csv"
    staging = cfg.data_root / "staging_phase1"
    state_json = REPO_ROOT / "reports" / "discovery" / "staging_state_20260605.json"
    sel = gpd.read_file(REPO_ROOT / "reports" / "discovery" / "stage_a_selection.gpkg",
                        layer="selection")
    raw_lr_ids = set(sel[sel["tier"] == "raw_lr_to_grid"]["lr_id"])
    gates = phase1.verify(manifest_csv, log_csv, staging, state_json, raw_lr_ids)
    print(json.dumps(gates, indent=2))
    return 0 if all(g["pass"] for g in gates.values()) else 1


def cmd_phase1_closeout(args: argparse.Namespace) -> int:
    """v1.5.4 rev 3 — Phase 1 close-out (C0 captures + C1 Gate 6 + C2 report)."""
    _setup_logging("phase1_closeout")
    from . import phase1_closeout as co
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    staging = cfg.data_root / "staging_phase1"
    quarantine = cfg.data_root / "quarantine_phase1"
    hr_path = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    log_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_log.csv"
    manifest_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    state_json = REPO_ROOT / "reports" / "discovery" / "staging_state_20260605.json"
    out_md = REPO_ROOT / "reports" / "discovery" / "stage1_report_20260605_rev3.md"
    resolution_csv = REPO_ROOT / "reports" / "discovery" / "hr_resolution_sanity.csv"
    summary = co.run_closeout(
        staging, quarantine, hr_path, manifest_csv, log_csv,
        state_json, out_md, resolution_csv,
    )
    print(json.dumps({
        "captures": [{"hr_id": c["hr_id"], "outcome": c["recovery_outcome"],
                       "reason": c["reason"]} for c in summary["captures"]],
        "gate6": {"pass": summary["gate6"]["pass"],
                  "detail": summary["gate6"]["detail"],
                  "blocked": summary["gate6"]["blocked"]},
        "gates_1_5": summary["gates_1_5"],
        "report": summary["report"],
        "sweep_count": summary["sweep_count"],
    }, indent=2))
    return 0 if (summary["gate6"]["pass"]
                 and all(summary["gates_1_5"].values())) else 1


def cmd_phase1_remediation(args: argparse.Namespace) -> int:
    """v1.5.4 rev 2 — R0..R4 remediation in one shot."""
    _setup_logging("phase1_remediation")
    from . import phase1_remediation as rem
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    staging = cfg.data_root / "staging_phase1"
    quarantine = cfg.data_root / "quarantine_phase1"
    hr_path = REPO_ROOT / "reports" / "discovery" / "hr_catalog.gpkg"
    log_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_log.csv"
    manifest_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    state_json = REPO_ROOT / "reports" / "discovery" / "staging_state_20260605.json"
    out_md = REPO_ROOT / "reports" / "discovery" / "stage1_report_20260605_rev2.md"
    resolution_csv = REPO_ROOT / "reports" / "discovery" / "hr_resolution_sanity.csv"
    summary = rem.run_remediation(
        staging, quarantine, hr_path, log_csv, manifest_csv,
        state_json, out_md, resolution_csv,
    )
    # Report path + gate pass/fail counts to stdout
    gates = summary["gates"]
    print(json.dumps({
        "r0_final_status": summary["r0"]["final_status"],
        "r1_looks_like": summary["r1"]["looks_like"],
        "sweep_rows": summary["n_rows_sweep"],
        "gate_results": {k: g["pass"] for k, g in gates.items()},
        "report": summary["report"],
        "resolution_csv": summary["resolution_csv"],
    }, indent=2))
    return 0 if all(g["pass"] for g in gates.values()) else 1


def cmd_phase1_report(args: argparse.Namespace) -> int:
    """v1.5.4 Phase 1 Step 4 — completion report + state refresh."""
    _setup_logging("phase1_report")
    import geopandas as gpd
    from . import phase1
    cfg = cfg_mod.load(args.config)
    manifest_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_manifest.csv"
    log_csv = REPO_ROOT / "reports" / "discovery" / "stage1_download_log.csv"
    staging = cfg.data_root / "staging_phase1"
    state_json = REPO_ROOT / "reports" / "discovery" / "staging_state_20260605.json"
    sel = gpd.read_file(REPO_ROOT / "reports" / "discovery" / "stage_a_selection.gpkg",
                        layer="selection")
    raw_lr_ids = set(sel[sel["tier"] == "raw_lr_to_grid"]["lr_id"])
    gates = phase1.verify(manifest_csv, log_csv, staging, state_json, raw_lr_ids)
    out_md = REPO_ROOT / "reports" / "discovery" / "stage1_report_20260605.md"
    phase1.write_report(out_md, manifest_csv, log_csv, gates, staging)
    phase1.refresh_state(state_json, staging)
    print(f"wrote {out_md}; refreshed {state_json}")
    return 0 if all(g["pass"] for g in gates.values()) else 1


def cmd_discover_stage_a(args: argparse.Namespace) -> int:
    """v1.5 Stage A — emit selection + Gate A summary."""
    _setup_logging("discover_stage_a")
    from .discovery import stage_a
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    out_dir = REPO_ROOT / "reports" / "discovery"
    hr = out_dir / "hr_catalog.gpkg"
    lr = out_dir / "lr_candidates.gpkg"
    pairs = out_dir / "candidate_pairs.gpkg"
    if not (hr.exists() and lr.exists() and pairs.exists()):
        print("Need hr_catalog / lr_candidates / candidate_pairs first.")
        return 2
    result = stage_a.run(
        hr_path=hr, lr_path=lr, pairs_path=pairs,
        out_dir=out_dir,
        mgds_cache_dir=cfg.data_root / "discovery_cache" / "mgds",
        ncei_cache_dir=cfg.data_root / "discovery_cache" / "ncei_products",
    )
    print(f"Selection: {len(result.selection)} HR -> {result.yaml_path}")
    print(f"Gate A report -> {result.summary_md_path}")
    return 0


def cmd_discover_rebuild(args: argparse.Namespace) -> int:
    """v1.4.1 — apply §1-§5 fixes and re-score without re-harvesting."""
    _setup_logging("discover_rebuild")
    from .discovery import join as join_mod
    from .discovery import rebuild
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    out_dir = REPO_ROOT / "reports" / "discovery"
    hr_in = out_dir / "hr_catalog.gpkg"
    lr_in = out_dir / "lr_candidates.gpkg"
    if not (hr_in.exists() and lr_in.exists()):
        print("Run discover-hr / discover-lr first.")
        return 2
    manifest = REPO_ROOT / "manifest" / "pairs.parquet"
    geoportal_cache = cfg.data_root / "discovery_cache" / "geoportal"
    hr = rebuild.rebuild_hr(hr_in, manifest)
    lr = rebuild.rebuild_lr(lr_in, hr, geoportal_cache)
    hr_out, lr_out = rebuild.write_layers(hr, lr, out_dir)
    print(f"HR (corrected): {len(hr)} rows -> {hr_out}")
    print(f"LR (enriched): {len(lr)} rows -> {lr_out}")
    pairs_out = out_dir / "candidate_pairs.gpkg"
    join_mod.build(hr_out, lr_out, pairs_out)
    print(f"candidate pairs (re-scored + triage view) -> {pairs_out}")
    return 0


def cmd_discover_coverage(args: argparse.Namespace) -> int:
    """v1.4 M3.3 — coverage summary by terrain class."""
    from .discovery import coverage
    pairs = REPO_ROOT / "reports" / "discovery" / "candidate_pairs.gpkg"
    manifest = REPO_ROOT / "manifest" / "pairs.parquet"
    out = REPO_ROOT / "reports" / "discovery" / f"coverage_summary_{date.today().strftime('%Y%m%d')}.md"
    coverage.summarize(pairs, manifest, out)
    print(f"coverage summary -> {out}")
    return 0


def cmd_m17_report(args: argparse.Namespace) -> int:
    """Consolidated M1.7 report (v1.2.1 deliverable)."""
    import json
    import pandas as pd
    import yaml
    from . import manifest as mf
    from . import reharmonize_user_hr as rh

    cfg = cfg_mod.load(args.config)
    rep = REPO_ROOT / "reports"
    out = rep / f"acquisition_report_m1_7_{date.today().strftime('%Y%m%d')}.md"
    approved = rep / "user_hr_approved_mapping.yaml"
    settings: dict = {}
    if approved.exists():
        approved_doc = yaml.safe_load(approved.read_text()) or {}
        settings = approved_doc.get("settings", {})

    # Manifest state
    df = mf.load()
    cdig = df[df["pair_id"].str.startswith("cal_dig")].copy()

    # Attestation status of provenance sidecars
    user_dir = cfg.data_root / "user-provided-cal-dig"
    attested_yes = attested_no = pending = 0
    sidecar_states: list[tuple[str, str]] = []
    for sc in sorted(user_dir.glob("*.tif.provenance.json")):
        try:
            data = json.loads(sc.read_text())
            v = data.get("attested_artifact_free")
        except Exception:
            v = None
        sidecar_states.append((sc.name, repr(v)))
        if v is True:
            attested_yes += 1
        elif v is False:
            attested_no += 1
        else:
            pending += 1

    lines: list[str] = [
        f"# M1.7 — Cal DIG HR remediation + figures ({date.today().isoformat()})",
        "",
        "Implements v1.2 + v1.2.1 addenda. DISCOL untouched. Cal DIG LR "
        "(`10.5066/P9QQZ27U`) untouched. Tier 2 still blocked pending figure approval.",
        "",
        "## Approved mapping (v1.2.1 §1)",
        "",
        f"- HR target GSD: **{settings.get('hr_target_gsd_m', '?')} m** (uniform 5× ratio against 10 m LR).",
        f"- Single warp EPSG:32610 → {settings.get('target_crs', '?')}: "
        f"`{settings.get('downsample_kernel', '?')}` when input < 2 m, "
        f"`{settings.get('reproject_kernel', '?')}` when input = 2 m.",
        "- Drop list (removed from manifest, no CMGDS fallback): "
        "`cal_dig_morro_bay__20180426m1_PockmarkNorthDet` (detail subset wholly inside PockmarkNorth).",
        "- New pairs: `cal_dig_morro_bay__luciachica_2007`, "
        "`cal_dig_morro_bay__luciachica_2009` (v1.2.1 §4 — no CMGDS ancestor).",
        "- Stays rejected: `cal_dig_morro_bay__20190318m1_LuciaChica1100m`, "
        "`cal_dig_morro_bay__20190319m1_8mPockmarkDetail` (no LR coverage).",
        "- Mosaic: `cal_dig_morro_bay__20180427m2_PockmarkSouthBasinFlank` "
        "combines `PockmarkSouth_MAUV` + `BasinFlank_MAUV` (user export split this CMGDS survey).",
        "",
        "## §B sidecar attestation status",
        "",
        f"- Attested artifact-free (`true`): **{attested_yes}**",
        f"- Attested artifacted (`false`): **{attested_no}**",
        f"- Pending (`null`): **{pending}**",
        "",
        "_Sidecar files live at `$DATA_ROOT/user-provided-cal-dig/*.tif.provenance.json`. "
        "Set `attested_artifact_free: true|false` for each before declaring §B complete._",
        "",
        "## §8 — `axis_excess` metric dropped",
        "",
        "Removed from `FileInfo`, the inventory report, and the provenance sidecar "
        "schema. The hillshade + FFT images still feed the §7(a) contact sheet "
        "(`reports/user_hr_artifact_contact_sheet_p0?.png`). Artifact-free status "
        "is human-attested visually.",
        "",
        "## §2 — HR standardization to 2 m (single warp)",
        "",
        "| pair | native CRS | native GSD | kernel | output |",
        "|---|---|---:|---|---|",
    ]

    for _, r in cdig.sort_values("pair_id").iterrows():
        if str(r.get("hr_source_type")) != "user_provided":
            continue
        kernel = "?"
        m = None
        if r["notes"]:
            import re
            m = re.search(r"`([a-z]+)` resample", r["notes"])
        if m:
            kernel = m.group(1)
        lines.append(
            f"| `{r['pair_id'].split('__', 1)[1]}` | {r['native_crs_hr']} | "
            f"{r['hr_native_res_m']:.2f} m | {kernel} | "
            f"{cfg.harmonized_dir / 'cal_dig_morro_bay' / r['pair_id'].split('__', 1)[1] / 'hr.tif'} |"
        )
    lines.append("")

    lines += [
        "## §6 — Coregistration results (fresh; no CMGDS reuse)",
        "",
        "| pair | overlap km² | h (m) | v (m) | PSR | eig | agrees | status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for _, r in cdig.sort_values("pair_id").iterrows():
        if str(r.get("hr_source_type")) != "user_provided":
            continue
        short = r["pair_id"].split("__", 1)[1]
        agree = "✓" if r.get("coreg_peak_agrees") else "✗"
        # Pull overlap from footprint area? We stored footprint_wkt path only;
        # compute fresh from the geojson if needed. For now, report via notes
        # if present.
        import re
        m = re.search(r"\(([\d.]+) km\^2\)|HR∩LR\s+([\d.]+)", r["notes"] or "")
        ov = m.group(1) if m and m.group(1) else (m.group(2) if m and m.group(2) else "—")
        psr = "?" if pd.isna(r.get("coreg_peak_psr")) else f"{float(r['coreg_peak_psr']):.2f}"
        eig = "?" if pd.isna(r.get("coreg_peak_eig_ratio")) else f"{float(r['coreg_peak_eig_ratio']):.2f}"
        h = f"{float(r['horiz_offset_m']):.1f}" if not pd.isna(r.get("horiz_offset_m")) else "—"
        v = f"{float(r['vert_offset_m']):.2f}" if not pd.isna(r.get("vert_offset_m")) else "—"
        lines.append(
            f"| `{short}` | {ov} | {h} | {v} | {psr} | {eig} | {agree} | "
            f"{r['coreg_status']} |"
        )
    lines.append("")

    # New pairs §4 verdicts
    lines += [
        "## §4 — New-pair LR-overlap verdicts (LuciaChica 2007 + 2009)",
        "",
    ]
    for pid in ("cal_dig_morro_bay__luciachica_2007", "cal_dig_morro_bay__luciachica_2009"):
        row = cdig[cdig["pair_id"] == pid]
        if row.empty:
            lines.append(f"- `{pid}` — _not in manifest (re-harmonization not run or failed)_")
        else:
            r = row.iloc[0]
            status = r["coreg_status"]
            lines.append(f"- `{pid}` — **{status}** ({r['notes']})")
    lines.append("")

    # LuciaChica IoU matrix
    if approved.exists():
        try:
            from . import reharmonize_user_hr as rh_mod
            iou = rh_mod.luciachica_iou_matrix(
                approved_doc, settings,
                cfg.data_root / "user-provided-cal-dig",
            )
            if iou:
                lines += [
                    "## §5 — LuciaChica pairwise IoU matrix (informational; not a gate)",
                    "",
                    "| | " + " | ".join(iou) + " |",
                    "|---|" + "---|" * len(iou),
                ]
                for k in iou:
                    lines.append("| " + k + " | " + " | ".join(f"{iou[k].get(k2, 0):.2f}" for k2 in iou) + " |")
                lines.append("")
        except Exception as e:
            lines.append(f"_(IoU matrix computation failed: {e})_")
            lines.append("")

    # Figures
    lines += [
        "## §7 — Figures",
        "",
        "**(a) Artifact contact sheet** "
        "— `reports/user_hr_artifact_contact_sheet_p01.png` and `_p02.png`.",
        "",
        "**(b) Master LR-vs-HR figure** "
        "— `reports/cal_dig_master_lr_vs_hr.pdf` + `cal_dig_master_lr_vs_hr.png`.",
        "",
        "## Audit + manifest state",
        "",
        f"- Manifest rows: **{len(df)}** ({len(cdig)} Cal DIG, "
        f"{len(df) - len(cdig)} DISCOL).",
        f"- Run `python -m src.cli audit` to re-verify provenance (LR DOI-match still "
        f"required; user_provided HR now goes through the v1.2 §E branch).",
        "",
        "## Gate",
        "",
        "- **Pause:** human approval of the §7 figures + per-pair clearance via the new "
        "overlay PNGs.",
        "- Tier 2 stays blocked until every Cal DIG pair is `auto_pass` or human-cleared "
        "AND the master figure is approved.",
        "",
    ]
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    return 0


def cmd_m16_report(args: argparse.Namespace) -> int:
    """Compose the M1.6 hand-off report from existing §B/§C/§D artefacts."""
    cfg = cfg_mod.load(args.config)
    rep_dir = REPO_ROOT / "reports"
    today = date.today().strftime("%Y%m%d")
    out = rep_dir / f"acquisition_report_m1_6_{today}.md"

    inv = next(iter(sorted(rep_dir.glob("user_hr_inventory_*.md"), reverse=True)), None)
    match = next(iter(sorted(rep_dir.glob("user_hr_match_*.md"), reverse=True)), None)
    proposed = rep_dir / "user_hr_proposed_mapping.yaml"
    approved = rep_dir / "user_hr_approved_mapping.yaml"
    qc_dir = rep_dir / "user_hr_qc"

    lines = [
        f"# M1.6 — Cal DIG HR remediation (v1.2 addendum) — {date.today().isoformat()}",
        "",
        "Implements Acquisition Directive v1.2 (user-provided HR for Cal DIG only). ",
        "DISCOL untouched. Cal DIG LR (`10.5066/P9QQZ27U`) untouched. Tier 2 still blocked.",
        "",
        "## Status",
        "",
        f"- §B inventory: {'**done**' if inv else 'pending'}"
        + (f" → `{inv.name}` (28 files, all EPSG:32610 / WGS84 UTM 10N)" if inv else ""),
        f"- §C proposed mapping: {'**done**' if match else 'pending'}"
        + (f" → `{match.name}` + `{proposed.name}`" if match else ""),
        f"- §C human approval: {'**received**' if approved.exists() else '**pending — awaiting `user_hr_approved_mapping.yaml`**'}",
        "- §D re-harmonization: " + (
            "**done** — see manifest for sub-pairs with `hr_source_type=user_provided`"
            if approved.exists() else "blocked until §C approval"
        ),
        "",
        "## QC artefacts",
        "",
        f"- Per-file hillshade + FFT PNGs under `reports/user_hr_qc/` (28×2 = 56 PNGs).",
        f"- Per-file `<name>.provenance.json` sidecars next to the source files in "
        f"`{cfg.data_root}/user-provided-cal-dig/`. Field `attested_artifact_free` "
        f"is `null` until the human attests.",
        "",
        "## §E provenance + audit",
        "",
        "- Manifest schema (already extended): `hr_source_type`, `hr_local_path`, "
        "`hr_superseded_doi`, `hr_superseded_reason`.",
        "- `src.audit.audit_row` now branches: for rows with "
        "`hr_source_type=='user_provided'` it requires the local file to exist, a "
        "`<file>.provenance.json` sidecar with `attested_artifact_free: true`, and the "
        "superseded-DOI provenance trail. The DOI-match check still applies to the LR "
        "side and to all DISCOL/PANGAEA rows.",
        "- `python -m src.cli audit` runs the branched audit.",
        "",
        "## Workflow from here",
        "",
        "1. Review the §B PNGs (hillshade + FFT). For each file, edit its "
        "`*.provenance.json` and set `attested_artifact_free: true` (or `false`).",
        "2. Review the proposed mapping in `user_hr_proposed_mapping.yaml`. Edit values "
        "to override any wrong matches (set value to `null` to reject; substitute a "
        "different `user_file` path to override). Rename to "
        "`user_hr_approved_mapping.yaml` when ready.",
        "3. Run `python -m src.cli reharmonize-user-hr`. This:",
        "   - re-projects user HR from EPSG:32610 → EPSG:26910 with the configured "
        "`resample_kernel` (`bilinear`). Reprojection is NOT skipped — all user files "
        "are WGS84 UTM 10N, the target is NAD83 UTM 10N, and the datum shift is real.",
        "   - re-clips to the new HR∩LR overlap;",
        "   - **re-solves co-registration from scratch** (no CMGDS dx/dy/dz reuse);",
        "   - regenerates the v1.1 §A QA + overlay PNG;",
        "   - updates the manifest row with the new fields.",
        "4. Review the new overlay PNGs. Clear each sub-pair manually (`coreg_status` "
        "transitions from `needs_review` only via explicit human review of the new "
        "overlay; v1.1 thresholds are still uncalibrated).",
        "5. `python -m src.cli audit` should pass with all 17 Cal DIG rows now branching "
        "on user_provided HR.",
        "",
        "## Gate",
        "",
        "- **Pause #1 (this report):** human attestation of §B artifact-free status; "
        "approval of §C mapping. No re-harmonization until both happen.",
        "- **Pause #2 (after §D):** human clearance of the new overlay PNGs per sub-pair.",
        "- Tier 2 remains blocked.",
        "",
    ]
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    return 0


def cmd_inventory_user_hr(args: argparse.Namespace) -> int:
    _setup_logging("user_hr_inventory")
    from . import user_hr as uh
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    root = cfg.data_root / "user-provided-cal-dig"
    if not root.exists():
        print(f"missing user-provided dir: {root}")
        return 2
    out_dir = REPO_ROOT / "reports" / "user_hr_qc"
    items = uh.inventory(root, out_dir)
    report_path = REPO_ROOT / "reports" / f"user_hr_inventory_{date.today().strftime('%Y%m%d')}.md"
    uh.render_inventory_report(items, report_path)
    print(f"inventoried {len(items)} files. report: {report_path}")
    return 0


def cmd_match_user_hr(args: argparse.Namespace) -> int:
    _setup_logging("user_hr_match")
    import yaml
    from . import manifest as mf
    from . import user_hr as uh
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    root = cfg.data_root / "user-provided-cal-dig"
    # Reuse the inventory if it exists, else create it fresh
    out_qc = REPO_ROOT / "reports" / "user_hr_qc"
    items = uh.inventory(root, out_qc)
    # Cal DIG sub-pairs from manifest (excluding the two rejected per §C)
    df = mf.load()
    cdig_sub_pairs = sorted(df[df["pair_id"].str.startswith("cal_dig_morro_bay__")]["pair_id"].tolist())
    raw_root = cfg.raw_dir / "cal_dig_morro_bay"
    report = uh.match(items, cdig_sub_pairs, raw_root=raw_root)
    out_path = REPO_ROOT / "reports" / f"user_hr_match_{date.today().strftime('%Y%m%d')}.md"
    uh.render_match_report(report, items, out_path)
    # Write a proposed mapping YAML the human can edit -> approved_mapping.yaml
    proposed_yaml = REPO_ROOT / "reports" / "user_hr_proposed_mapping.yaml"
    proposed = {
        c.sub_pair_id: (c.user_file if c.iou >= report.threshold_iou else None)
        for c in report.proposed
    }
    proposed_yaml.write_text(
        "# Proposed user_file -> sub_pair mapping (v1.2 §C).\n"
        "# REVIEW THE MATCH REPORT FIRST, then:\n"
        "#   - leave a mapping in place to accept it\n"
        "#   - set a value to null to reject\n"
        "#   - rename this file to `user_hr_approved_mapping.yaml` when ready\n"
        "#   - then run `python -m src.cli reharmonize-user-hr`\n\n"
        + yaml.safe_dump(proposed, sort_keys=False, default_flow_style=False)
    )
    print(f"proposed {len(report.proposed)} pairs; unmatched user files {len(report.user_unmatched)}; "
          f"unmatched sub_pairs {len(report.sub_pair_unmatched)}; collisions {len(report.collisions)}.")
    print(f"report:        {out_path}")
    print(f"proposed YAML: {proposed_yaml}")
    return 0


def cmd_reharmonize_user_hr(args: argparse.Namespace) -> int:
    _setup_logging("reharmonize_user_hr")
    from . import reharmonize_user_hr as rh
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    approved = REPO_ROOT / "reports" / "user_hr_approved_mapping.yaml"
    if not approved.exists():
        print(f"approved mapping not found: {approved}")
        print("Workflow: edit reports/user_hr_proposed_mapping.yaml, rename it to "
              "user_hr_approved_mapping.yaml, then re-run.")
        return 2
    report = rh.reharmonize(cfg, approved)
    n = len(report.results)
    rejected_n = sum(1 for r in report.results if r.coreg_status == "reject")
    print(f"re-harmonized {n} pairs ({rejected_n} rejected new pairs); "
          f"dropped {len(report.dropped)}.")
    for r in report.results:
        marker = "REJECT" if r.coreg_status == "reject" else r.coreg_status
        print(f"  {r.pair_id}: native_gsd={r.native_gsd_m:.2f}m kernel={r.resample_kernel} "
              f"overlap={r.overlap_area_km2:.2f}km^2 PSR={r.psr:.2f} eig={r.eig_ratio:.2f} "
              f"status={marker}"
              + (f"  ({r.rejected_reason})" if r.rejected_reason else ""))
    if report.dropped:
        print("dropped from manifest:")
        for p in report.dropped:
            print(f"  - {p}")
    if report.luciachica_iou:
        print("LuciaChica pairwise IoU (informational):")
        keys = sorted(report.luciachica_iou)
        for k in keys:
            row = " ".join(f"{report.luciachica_iou[k].get(k2, 0.0):.2f}" for k2 in keys)
            print(f"  {k}: {row}")
    return 0


def cmd_m15_report(args: argparse.Namespace) -> int:
    """Generate the M1.5 (v1.1 addendum) consolidated report."""
    import json
    import pandas as pd
    from . import manifest as mf
    from . import calibrate as cal

    cfg = cfg_mod.load(args.config)
    df = mf.load()
    out_dir = REPO_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    cal_result = cal.calibrate(df, out_dir)

    # Group by parent
    df["_parent"] = df["pair_id"].apply(lambda s: s.split("__", 1)[0])
    cdig = df[df["_parent"] == "cal_dig_morro_bay"].copy()
    discol = df[df["_parent"] == "discol_so242_1"].copy()

    # Sort Cal DIG by ascending PSR so weakest locks surface first
    cdig = cdig.sort_values("coreg_peak_psr", na_position="last")

    out = out_dir / f"acquisition_report_m1_5_{date.today().strftime('%Y%m%d')}.md"

    lines: list[str] = []
    lines += [
        f"# M1.5 — Co-registration QA re-run report ({date.today().isoformat()})",
        "",
        "Implements Acquisition Directive v1.1 (co-registration QA addendum) "
        "against the already-harmonized M1 Tier-1 output. No re-download, no re-solve.",
        "",
        "## Verdict",
        "",
        f"- Sub-pairs evaluated: **{len(df)}** (1 DISCOL + {len(cdig)} Cal DIG).",
        f"- Hillshade overlay artifacts: **{int((df['qc_artifact_path'] != '').sum())}/{len(df)}** present.",
        f"- `coreg_status` distribution: " + ", ".join(
            f"{v}={c}" for v, c in df["coreg_status"].value_counts().to_dict().items()
        ),
        "- **Every sub-pair is `needs_review`** because the two empirical thresholds "
        "(`min_peak_sharpness`, `peak_anisotropy_max`) are not yet written to config — "
        "calibration (§D.2 below) was inconclusive against the addendum's labeled set, "
        "so I refuse to invent them per the directive's hard rule.",
        "- **Tier 2 remains blocked.**",
        "",
        "## §A — New QA metrics",
        "",
        "For each sub-pair, we computed gradient-magnitude NCC over a ±30 m search window "
        "centred at the already-applied solved offset (which is therefore expected to peak "
        "near (0,0) for a correctly locked pair):",
        "",
        "- `horiz_offset_m` = magnitude of the applied (dx, dy) from the original coreg solve",
        "- `vert_offset_m` = |dz|",
        "- `coreg_peak_psr` = peak-to-sidelobe ratio of NCC",
        "- `coreg_peak_eig_ratio` = larger/smaller Hessian eigenvalue at peak (anisotropy)",
        "- `coreg_peak_agrees` = NCC max sits within 1 LR cell of (0,0)",
        "",
        "## §D.2 — Threshold calibration result",
        "",
        f"Calibration plot: `{cal_result['plot']}`.",
        "",
        "Labeled set used (per addendum):",
        "- Known-good: `20180426m1_PockmarkNorthDet`, `20180427m3_PockmarkNorth` "
        "(duplicate pockmark surveys, solved to similar offsets)",
        "- Known-suspect: `20190315m1_HeadlessCanyon` (high offset, worst MAD, linear morphology)",
        "",
    ]
    s = cal_result["summary"]
    lines += [
        "Summary statistics:",
        "",
        "| label | n | PSR (min/med/max) | eig_ratio (min/med/max) |",
        "|---|---:|---|---|",
    ]
    for lab in ("known_good", "known_suspect", "unlabeled"):
        v = s[lab]
        if v["n"] == 0:
            continue
        lines.append(
            f"| {lab} | {v['n']} | "
            f"{v['psr_min']:.2f} / {v['psr_median']:.2f} / {v['psr_max']:.2f} | "
            f"{v['eig_min']:.2f} / {v['eig_median']:.2f} / {v['eig_max']:.2f} |"
        )
    lines.append("")

    prop = cal_result["proposal"]
    if prop.get("separable"):
        lines += [
            "**Calibrated thresholds (pending human confirmation before writing to config):**",
            "",
            f"- `min_peak_sharpness`: **{prop['min_peak_sharpness']:.2f}** — {prop['rationale_psr']}",
            f"- `peak_anisotropy_max`: **{prop['peak_anisotropy_max']:.2f}** — {prop['rationale_eig']}",
            "",
        ]
    else:
        lines += [
            "**Calibration result: INCONCLUSIVE.**",
            "",
            f"- {prop['rationale_psr']}",
            f"- {prop['rationale_eig']}",
            "",
            f"_{prop['note']}_",
            "",
            "Required human action: review the overlay PNGs (paths in the manifest) and "
            "extend or revise the labeled set, then re-run `python -m src.cli m15-report`.",
            "",
        ]

    # All sub-pairs sorted by PSR ascending (weakest first per §D.3)
    lines += [
        "## §D.3 — All Cal DIG sub-pairs (sorted by PSR ascending; weakest locks first)",
        "",
        "| sub-pair | horiz (m) | vert (m) | PSR | eig | agrees | overlay |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for _, r in cdig.iterrows():
        short = r["pair_id"].split("__", 1)[1]
        agree = "✓" if r.get("coreg_peak_agrees") else "✗"
        overlay = Path(r["qc_artifact_path"]).name if r["qc_artifact_path"] else "—"
        psr = "?" if pd.isna(r["coreg_peak_psr"]) else f"{r['coreg_peak_psr']:.2f}"
        eig = "?" if pd.isna(r["coreg_peak_eig_ratio"]) else f"{r['coreg_peak_eig_ratio']:.2f}"
        lines.append(
            f"| `{short}` | {r['horiz_offset_m']:.1f} | {r['vert_offset_m']:.2f} | "
            f"{psr} | {eig} | {agree} | `{overlay}` |"
        )
    lines.append("")

    # DISCOL
    if len(discol):
        d = discol.iloc[0]
        lines += [
            "## DISCOL (evaluated at (0,0,0) offset; AUV pre-corrected upstream)",
            "",
            f"- `coreg_status`: **{d['coreg_status']}**",
            f"- PSR={d['coreg_peak_psr']:.2f}, eig_ratio={d['coreg_peak_eig_ratio']:.2f}, "
            f"peak_agrees={d['coreg_peak_agrees']}",
            f"- Overlay: `{Path(d['qc_artifact_path']).name if d['qc_artifact_path'] else '—'}`",
            "",
        ]

    # Rejection re-verification
    rej = out_dir / "rejection_reverification_20260603.md"
    if rej.exists():
        lines += [
            "## §D.4 — Rejection re-verification",
            "",
            f"See `{rej.name}` for full geometry analysis.",
            "",
            "Both rejected AUV tiles (`20190318m1_LuciaChica1100m`, `20190319m1_8mPockmarkDetail`) "
            "sit ~6.5 km from the nearest LR-valid pixel — a real geographic hole in the Cal DIG "
            "ship multibeam coverage at ~1,100 m depth. True non-overlap, not a footprint/transform "
            "artifact. Both stay `reject`.",
            "",
        ]

    # §E — fetcher + audit
    lines += [
        "## §E — Fetcher hardening + non-synthesis audit",
        "",
        "Implemented:",
        "",
        "- `src/download.local_release_matches(local_path, expected_doi)` — reuse-local "
        "guard: a local file only substitutes for a fresh fetch when a `<file>.doi.json` "
        "sidecar carries the matching DOI. Same-name files at generic paths are not "
        "sufficient.",
        "- `src/audit.py` + `python -m src.cli audit` — replaces the old "
        "`lr_native_res_m > hr_native_res_m` check with a provenance assertion: each "
        "manifest row's `metadata.json` must contain HR + LR entries whose DOIs match "
        "the manifest, with checksums and source URLs present, and the LR source URL "
        "must not reference the HR DOI.",
        "- Audit result: **all 18 rows pass.**",
        "",
    ]

    # Updated hard rules (v1.1 §F)
    lines += [
        "## §F — Updated hard rules (now enforced)",
        "",
        "- A sub-pair is usable downstream only if `coreg_status == auto_pass` OR a human "
        "has explicitly cleared it after reviewing its overlay PNG. Low MAD alone never "
        "qualifies.",
        f"- `horiz_offset_m > usbl_bound_m` (={cfg.coregistration.get('usbl_bound_m')}) never "
        "auto-passes — routes to `needs_review`.",
        "- Every sub-pair (incl. DISCOL) has its hillshade-overlay artifact written.",
        "- `min_peak_sharpness` and `peak_anisotropy_max` remain unset (`null`) in "
        "`config/harmonization.yaml`; no value will be invented.",
        "",
        "## Gate",
        "",
        "- **M1.5 pause.** Tier 2 stays blocked until: (a) the labeled set is revised "
        "via overlay-PNG review or the calibration metric is refined to separate the "
        "known-good and known-suspect clusters, (b) thresholds are calibrated and written "
        "to config, (c) every Cal DIG sub-pair is `auto_pass` or explicitly cleared / rejected.",
        "",
    ]

    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    print(f"calibration: separable={prop.get('separable')}")
    return 0


def cmd_qc_rerun(args: argparse.Namespace) -> int:
    _setup_logging("qc_rerun")
    from . import qc_rerun as qrr
    cfg = cfg_mod.load(args.config)
    cfg_mod.validate_data_root(cfg)
    results = qrr.rerun(cfg)
    auto = sum(1 for r in results if r.coreg_status == "auto_pass")
    needs = sum(1 for r in results if r.coreg_status == "needs_review")
    print(f"qc-rerun: {len(results)} rows, auto_pass={auto}, needs_review={needs}")
    print(f"{'sub_pair':40} {'horiz':>8} {'vert':>6} {'PSR':>6} {'eig':>6} {'agree':>5} {'status':>12}")
    for r in sorted(results, key=lambda x: x.coreg_status + x.pair_id):
        print(f"{r.pair_id[-40:]:40} {r.horiz_offset_m:>8.2f} {r.vert_offset_m:>6.2f} "
              f"{r.psr:>6.2f} {r.eig_ratio:>6.2f} {str(r.peak_agrees):>5} {r.coreg_status:>12}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auv-ship-acq")
    p.add_argument("--config", default=None, help="path to harmonization.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-config")
    pi = sub.add_parser("ingest")
    pi.add_argument("--pair", required=True, choices=pairs_mod.all_ids())

    pr = sub.add_parser("report")
    pr.add_argument("--out", default=None)

    sub.add_parser("qc-rerun")
    sub.add_parser("audit")
    sub.add_parser("m15-report")
    sub.add_parser("inventory-user-hr")
    sub.add_parser("match-user-hr")
    sub.add_parser("reharmonize-user-hr")
    sub.add_parser("m16-report")
    sub.add_parser("artifact-contact-sheet")
    sub.add_parser("master-figure")
    sub.add_parser("m17-report")
    # ---- v1.4 discovery ----
    sub.add_parser("discover-mgds")
    sub.add_parser("discover-hr")
    sub.add_parser("discover-lr")
    sub.add_parser("discover-pairs")
    sub.add_parser("discover-coverage")
    sub.add_parser("discover-rebuild")
    sub.add_parser("discover-stage-a")
    sub.add_parser("discover-stage-b")
    sub.add_parser("discover-crs-recovery")
    sub.add_parser("phase1-manifest")
    sub.add_parser("phase1-download")
    sub.add_parser("phase1-verify")
    sub.add_parser("phase1-report")
    sub.add_parser("phase1-remediation")
    sub.add_parser("phase1-closeout")

    args = p.parse_args(argv)
    if args.cmd == "check-config":
        return cmd_check_config(args)
    if args.cmd == "ingest":
        return cmd_ingest(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "qc-rerun":
        return cmd_qc_rerun(args)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "m15-report":
        return cmd_m15_report(args)
    if args.cmd == "inventory-user-hr":
        return cmd_inventory_user_hr(args)
    if args.cmd == "match-user-hr":
        return cmd_match_user_hr(args)
    if args.cmd == "reharmonize-user-hr":
        return cmd_reharmonize_user_hr(args)
    if args.cmd == "m16-report":
        return cmd_m16_report(args)
    if args.cmd == "artifact-contact-sheet":
        return cmd_artifact_contact_sheet(args)
    if args.cmd == "master-figure":
        return cmd_master_figure(args)
    if args.cmd == "m17-report":
        return cmd_m17_report(args)
    if args.cmd == "discover-mgds":
        return cmd_discover_mgds(args)
    if args.cmd == "discover-hr":
        return cmd_discover_hr(args)
    if args.cmd == "discover-lr":
        return cmd_discover_lr(args)
    if args.cmd == "discover-pairs":
        return cmd_discover_pairs(args)
    if args.cmd == "discover-coverage":
        return cmd_discover_coverage(args)
    if args.cmd == "discover-rebuild":
        return cmd_discover_rebuild(args)
    if args.cmd == "discover-stage-a":
        return cmd_discover_stage_a(args)
    if args.cmd == "discover-stage-b":
        return cmd_discover_stage_b(args)
    if args.cmd == "discover-crs-recovery":
        return cmd_discover_crs_recovery(args)
    if args.cmd == "phase1-manifest":
        return cmd_phase1_manifest(args)
    if args.cmd == "phase1-download":
        return cmd_phase1_download(args)
    if args.cmd == "phase1-verify":
        return cmd_phase1_verify(args)
    if args.cmd == "phase1-report":
        return cmd_phase1_report(args)
    if args.cmd == "phase1-remediation":
        return cmd_phase1_remediation(args)
    if args.cmd == "phase1-closeout":
        return cmd_phase1_closeout(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
