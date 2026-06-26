"""v1.4 §7 coverage-by-province summary.

Counts + total overlap area per terrain class, combining existing
manifest pairs with the new candidate-pair catalog. Read-only against
the manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


def summarize(candidate_pairs_path: Path, manifest_path: Path,
              out_md_path: Path) -> Path:
    """Write a short Markdown table of counts per terrain class."""
    cand = gpd.read_file(candidate_pairs_path, layer="pairs") if candidate_pairs_path.exists() else gpd.GeoDataFrame()
    df_manifest = pd.read_parquet(manifest_path) if Path(manifest_path).exists() else pd.DataFrame()

    lines = ["# Coverage by province (v1.4 §7)", ""]
    lines.append("Read-only summary — existing manifest pairs + new candidate proposals.")
    lines.append("")
    lines.append("## Existing manifest (already harmonized / acquired)")
    if df_manifest.empty:
        lines.append("_(empty)_")
    else:
        by_terrain = df_manifest.groupby("terrain_class").size().to_dict()
        lines.append("| terrain | count |")
        lines.append("|---|---:|")
        for k, v in sorted(by_terrain.items()):
            lines.append(f"| {k} | {v} |")
        lines.append(f"| **total** | **{len(df_manifest)}** |")
    lines.append("")
    lines.append("## Candidate proposals (v1.4 discovery)")
    if cand.empty:
        lines.append("_(no candidates yet)_")
    else:
        # Count by terrain_hint and independence_verdict
        lines.append("### By terrain hint")
        lines.append("| terrain_hint | independent | needs_check | excluded/reject | total |")
        lines.append("|---|---:|---:|---:|---:|")
        for terrain, sub in cand.groupby("terrain_hint"):
            ind = (sub["independence_verdict"] == "independent").sum()
            nck = (sub["independence_verdict"] == "needs_check").sum()
            excl = sub["independence_verdict"].isin(["composite_excluded", "same_platform_reject"]).sum()
            lines.append(f"| {terrain} | {ind} | {nck} | {excl} | {len(sub)} |")
        lines += [
            "",
            "### Independence verdict roll-up",
            "| verdict | count | mean score | total overlap km² |",
            "|---|---:|---:|---:|",
        ]
        for v, sub in cand.groupby("independence_verdict"):
            lines.append(f"| {v} | {len(sub)} | {sub['score'].mean():.2f} | {sub['overlap_km2'].sum():.1f} |")
        lines += [
            "",
            "### Top 10 by score",
            "| rank | hr_id | lr_cruise | overlap km² | ratio | terrain | verdict |",
            "|---:|---|---|---:|---:|---|---|",
        ]
        for _, r in cand.head(10).iterrows():
            rr = r.get("res_ratio")
            rr_s = "—" if rr is None or (isinstance(rr, float) and pd.isna(rr)) else f"{rr:.1f}"
            lines.append(f"| {int(r['rank'])} | `{r['hr_id']}` | `{r['lr_cruise_id']}` | "
                         f"{r['overlap_km2']:.1f} | {rr_s} | {r['terrain_hint']} | {r['independence_verdict']} |")
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text("\n".join(lines))
    return out_md_path
