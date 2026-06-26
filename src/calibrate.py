"""v1.1 addendum §D.2 — threshold calibration.

Plot PSR + eig_ratio distributions across the M1 Cal DIG sub-pairs and
label the addendum's known-good vs known-suspect tiles. Propose
``min_peak_sharpness`` and ``peak_anisotropy_max`` only if the two clusters
are separable; otherwise report ambiguous and pause for human direction.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


log = logging.getLogger(__name__)


# Per addendum §D.2 / §D.3
KNOWN_GOOD = {
    "20180426m1_PockmarkNorthDet",
    "20180427m3_PockmarkNorth",
}
KNOWN_SUSPECT = {
    "20190315m1_HeadlessCanyon",
}


def _label(short_id: str) -> str:
    if short_id in KNOWN_GOOD:
        return "known_good"
    if short_id in KNOWN_SUSPECT:
        return "known_suspect"
    return "unlabeled"


def calibrate(manifest_df: pd.DataFrame, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cdig = manifest_df[manifest_df["pair_id"].str.startswith("cal_dig")].copy()
    cdig = cdig.dropna(subset=["coreg_peak_psr", "coreg_peak_eig_ratio"])
    cdig["short_id"] = cdig["pair_id"].str.split("__", n=1).str[1]
    cdig["label"] = cdig["short_id"].map(_label)

    # Stratified summary
    summary: dict[str, dict] = {}
    for lab in ("known_good", "known_suspect", "unlabeled"):
        rows = cdig[cdig["label"] == lab]
        summary[lab] = {
            "n": int(len(rows)),
            "psr_min": float(rows["coreg_peak_psr"].min()) if len(rows) else None,
            "psr_median": float(rows["coreg_peak_psr"].median()) if len(rows) else None,
            "psr_max": float(rows["coreg_peak_psr"].max()) if len(rows) else None,
            "eig_min": float(rows["coreg_peak_eig_ratio"].min()) if len(rows) else None,
            "eig_median": float(rows["coreg_peak_eig_ratio"].median()) if len(rows) else None,
            "eig_max": float(rows["coreg_peak_eig_ratio"].max()) if len(rows) else None,
        }

    # Threshold proposal: only if known-good cluster is *cleanly* separable
    # from known-suspect. We attempt a tight envelope around known-good and
    # check whether known-suspect sits outside it on at least one axis.
    good = cdig[cdig["label"] == "known_good"]
    susp = cdig[cdig["label"] == "known_suspect"]
    proposal: dict[str, object] = {"separable": False}
    if len(good) >= 1 and len(susp) >= 1:
        psr_good_min = float(good["coreg_peak_psr"].min())
        eig_good_max = float(good["coreg_peak_eig_ratio"].max())
        # Suspect is excluded if it fails PSR floor OR exceeds eig ceiling
        susp_psr = float(susp["coreg_peak_psr"].iloc[0])
        susp_eig = float(susp["coreg_peak_eig_ratio"].iloc[0])
        psr_sep = susp_psr < psr_good_min
        eig_sep = susp_eig > eig_good_max
        if psr_sep or eig_sep:
            proposal = {
                "separable": True,
                "min_peak_sharpness": psr_good_min,
                "peak_anisotropy_max": eig_good_max,
                "rationale_psr": f"known-good PSR floor = {psr_good_min:.2f}; suspect PSR = {susp_psr:.2f} "
                                 f"({'below' if psr_sep else 'inside'} floor)",
                "rationale_eig": f"known-good eig_ratio ceiling = {eig_good_max:.2f}; suspect eig = {susp_eig:.2f} "
                                 f"({'above' if eig_sep else 'inside'} ceiling)",
            }
        else:
            proposal = {
                "separable": False,
                "rationale_psr": f"known-good PSR floor = {psr_good_min:.2f}; suspect PSR = {susp_psr:.2f} (inside)",
                "rationale_eig": f"known-good eig_ratio ceiling = {eig_good_max:.2f}; suspect eig = {susp_eig:.2f} (inside)",
                "note": (
                    "Known-good and known-suspect tiles are NOT separable by PSR or "
                    "eig_ratio alone with the current NCC computation. Possible causes: "
                    "(1) the duplicate pockmark surveys may share the same systematic USBL "
                    "bias and so are not truly known-good in a morphology-lock sense; "
                    "(2) the gradient-NCC signal is weak after HR→LR aggregation. "
                    "Recommend human review of overlay PNGs to expand the labeled set."
                ),
            }

    # Scatter plot
    colours = {"known_good": "tab:green", "known_suspect": "tab:red", "unlabeled": "tab:gray"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    for lab, grp in cdig.groupby("label"):
        ax.scatter(grp["coreg_peak_psr"], grp["coreg_peak_eig_ratio"],
                   c=colours[lab], label=f"{lab} (n={len(grp)})", s=70, edgecolors="k")
    # Annotate every point with its short id
    for _, r in cdig.iterrows():
        ax.annotate(r["short_id"], (r["coreg_peak_psr"], r["coreg_peak_eig_ratio"]),
                    fontsize=7, alpha=0.7, xytext=(3, 3), textcoords="offset points")
    if proposal.get("separable"):
        ax.axvline(proposal["min_peak_sharpness"], ls="--", color="tab:blue", alpha=0.6,
                   label=f"PSR floor {proposal['min_peak_sharpness']:.2f}")
        ax.axhline(proposal["peak_anisotropy_max"], ls="--", color="tab:purple", alpha=0.6,
                   label=f"eig_ratio ceiling {proposal['peak_anisotropy_max']:.2f}")
    ax.set_xlabel("PSR (peak-to-sidelobe ratio)")
    ax.set_ylabel("eig_ratio (Hessian eigenvalue ratio at peak)")
    ax.set_yscale("log")
    ax.set_title("Cal DIG QC metrics: PSR vs eig_ratio")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)

    # Marginal histograms
    ax = axes[1]
    ax.hist([
        good["coreg_peak_psr"].values if len(good) else [],
        susp["coreg_peak_psr"].values if len(susp) else [],
        cdig[cdig["label"] == "unlabeled"]["coreg_peak_psr"].values,
    ], bins=8, label=["known_good", "known_suspect", "unlabeled"],
       color=[colours["known_good"], colours["known_suspect"], colours["unlabeled"]],
       stacked=False)
    ax.set_xlabel("PSR")
    ax.set_ylabel("count")
    ax.set_title("PSR distribution by label")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = out_dir / "calibration_psr_vs_eig.png"
    fig.savefig(plot_path, dpi=140)
    plt.close(fig)

    return {
        "summary": summary,
        "proposal": proposal,
        "plot": str(plot_path),
        "n_tiles": int(len(cdig)),
    }
