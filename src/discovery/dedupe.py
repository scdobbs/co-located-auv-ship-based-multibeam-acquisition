"""v1.4.1 §2 — collapse MGDS sibling rows into one HR per survey family.

Detection signature (per directive): same platform + same native
resolution + consecutive/related DOIs + near-identical true footprint.

Algorithm:
  1. Group by (platform_norm, native_res rounded to 2 decimals).
  2. Within each group, cluster rows whose footprint IoU > 0.90 OR whose
     DOI integers are within ±5 of each other.
  3. Keep the largest cluster member as canonical; record sibling
     ``hr_id`` and DOIs in the canonical row's ``sibling_hr_ids`` /
     ``sibling_dois`` fields.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import geopandas as gpd
import pandas as pd


log = logging.getLogger(__name__)


def _doi_int(doi: str) -> int | None:
    """Extract trailing integer from a DOI for sibling-detection."""
    if not doi:
        return None
    m = re.search(r"(\d+)\D*$", doi)
    return int(m.group(1)) if m else None


def _norm_platform(p: str) -> str:
    p = (p or "").lower().strip()
    p = re.sub(r"^r/v\s+", "", p)
    p = re.sub(r"\s+reson.*$", "", p)
    p = re.sub(r"\s+kongsberg.*$", "", p)
    return p


def _iou(a, b) -> float:
    try:
        inter = a.intersection(b).area
        union = a.union(b).area
        return float(inter / union) if union > 0 else 0.0
    except Exception:
        return 0.0


def dedupe(hr_gdf: gpd.GeoDataFrame, iou_threshold: float = 0.90,
           doi_window: int = 5) -> gpd.GeoDataFrame:
    df = hr_gdf.copy()
    df["_doi_int"] = df["doi"].fillna("").apply(_doi_int)
    df["_plat_norm"] = df["platform"].fillna("").apply(_norm_platform)
    df["_res_round"] = df["native_res_m"].round(2)
    df["sibling_hr_ids"] = ""
    df["sibling_dois"] = ""
    df["_keep"] = True

    # MGDS-only rows have data_set_uid as integer-like — only de-dup MGDS.
    # Manifest seeds keep their identity (they're separate pairs by design).
    mgds_mask = df["source"] == "MGDS"
    other = df[~mgds_mask].copy()
    mgds = df[mgds_mask].copy()

    for (plat, res), group in mgds.groupby(["_plat_norm", "_res_round"], dropna=False):
        if len(group) < 2:
            continue
        idxs = list(group.index)
        merged: set = set()
        for i_pos, i in enumerate(idxs):
            if i in merged:
                continue
            cluster_members = [i]
            r_geom = mgds.at[i, "geometry"]
            r_doi = mgds.at[i, "_doi_int"]
            for j in idxs[i_pos + 1:]:
                if j in merged:
                    continue
                iou = _iou(r_geom, mgds.at[j, "geometry"])
                s_doi = mgds.at[j, "_doi_int"]
                doi_close = (r_doi is not None and s_doi is not None
                             and pd.notna(r_doi) and pd.notna(s_doi)
                             and abs(int(r_doi) - int(s_doi)) <= doi_window)
                if iou >= iou_threshold or (doi_close and iou >= 0.50):
                    cluster_members.append(j)
                    merged.add(j)
            if len(cluster_members) > 1:
                # Pick canonical = member with most files (longest file_ids)
                cluster_df = mgds.loc[cluster_members]
                lengths = cluster_df["file_ids"].fillna("").str.len()
                canonical_idx = lengths.idxmax()
                sibling_idx = [i for i in cluster_members if i != canonical_idx]
                # Mark canonical and stash siblings
                sib_ids = mgds.loc[sibling_idx, "hr_id"].tolist()
                sib_dois = [d for d in mgds.loc[sibling_idx, "doi"].tolist() if d]
                df.loc[canonical_idx, "sibling_hr_ids"] = ",".join(sib_ids)
                df.loc[canonical_idx, "sibling_dois"] = ",".join(sib_dois)
                # Drop siblings
                for sidx in sibling_idx:
                    df.loc[sidx, "_keep"] = False
                log.info("collapsed %d siblings under %s (%s)",
                         len(sibling_idx), df.loc[canonical_idx, "hr_id"],
                         (df.loc[canonical_idx, "title"] or "")[:60])

    out = df[df["_keep"]].drop(columns=["_doi_int", "_plat_norm", "_res_round", "_keep"])
    log.info("dedupe: %d -> %d HR records", len(hr_gdf), len(out))
    return out
