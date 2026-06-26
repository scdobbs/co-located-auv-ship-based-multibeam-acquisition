"""HR platform classification — v1.5.1 §4 revision (informational only).

Per the user's 2026-06-04 correction: **inclusion is ratio-gated, not
platform-gated**. A 4 m surface-vessel grid is genuinely high-resolution
bathymetry and is a valid HR if it pairs with an independent LR whose
res_ratio lands in the training (5–25×) or eval-only (25–40×) band.
Platform name must not pre-empt the ratio test.

This module's job is therefore *recording*, not *deciding*:

  hr_class:    "auv" | "usv" | "surface_vessel"
  is_non_bathy: True when the description points to sidescan / sub-bottom /
                magnetometer (kept separate from platform classification —
                that IS a data-type rejection, distinct from "what carried
                the sensor").
  is_auv_grid:  legacy alias = (hr_class == "auv"); kept for backward
                compatibility with earlier rebuild/join layers but **NOT
                consulted as a Stage A filter** anymore.
"""

from __future__ import annotations

import re


_AUV_NAMES = (
    "MBARI Mapping AUV", "MBARI AUV", "Mapping AUV",
    "Sentry", "ABE", "REMUS", "ABYSS", "AUV ABYSS",
    "AsterX", "IDEFIX", "Bluefin", "Munin", "Iver",
    "Autosub", "D. Allan B.", "D Allan B",  # MBARI mapping AUV prior name
)
_USV_NAMES = ("Saildrone", "C-Worker", "DriX", "ASV ", "USV ", "C-Enduro")
_SURFACE_VESSEL_PREFIXES = ("R/V ", "RV ", "M/V ", "MV ", "NOAA Ship", "Ship ")
_AUV_SONARS = ("Reson SeaBat 7125", "Reson 7125", "Reson SeaBat 7150",
               "Reson SeaBat T50-S", "Imagenex", "EM2040 AUV")
# Non-bathy product hints — these stay excluded as a *data-type*
# rejection (distinct from platform). Sidescan/sub-bottom intensity
# rasters cannot serve as bathymetry HR.
_NON_BATHY_DESC = ("sidescan", "subbottom", "sub-bottom", "magnetometer",
                   "magnetic anomaly")
_BATHY_KEEPERS = ("bathymetry", "bathymetric", "topography", "depth grid",
                  "swath bathymetry", "near-bottom bathymetry")

_AUV_RE = re.compile("|".join(re.escape(s) for s in _AUV_NAMES), re.I)
_USV_RE = re.compile("|".join(re.escape(s) for s in _USV_NAMES), re.I)
_AUV_SONAR_RE = re.compile("|".join(re.escape(s) for s in _AUV_SONARS), re.I)


def classify(platform: str, sonar: str, description: str,
             native_res_m: float | None) -> tuple[bool, str, str]:
    """v1.5.1: return (is_auv_grid, hr_class, reason).

    ``hr_class`` is the canonical informational tag — *recorded*, not
    used as a Stage-A exclusion. ``is_auv_grid`` is kept as a legacy
    alias = (hr_class == 'auv').

    Inclusion in the HR pool is decided downstream by ratio + LR
    independence; the only platform-level rejection here is for explicit
    non-bathy products (sidescan / sub-bottom / magnetometer), which
    aren't bathymetry HR at all.
    """
    p = (platform or "").strip()
    s = (sonar or "").strip()
    d = (description or "").strip()
    d_l = d.lower()

    # 0. Non-bathy data-type rejection (NOT a platform decision).
    has_non_bathy_hint = any(h in d_l for h in _NON_BATHY_DESC)
    has_bathy_keeper = any(k in d_l for k in _BATHY_KEEPERS)
    if has_non_bathy_hint and not has_bathy_keeper:
        return (False, "non_bathy",
                "description indicates non-bathymetry product "
                "(sidescan / sub-bottom / magnetometer)")

    # 1. USV / ASV — surface autonomous platforms get their own class.
    if _USV_RE.search(p) or _USV_RE.search(d):
        return (False, "usv", "USV/ASV name in platform or description")

    # 2. AUV — named AUV in platform/description, or AUV sonar on R/V host.
    auv_named = bool(_AUV_RE.search(p) or _AUV_RE.search(d))
    has_auv_sonar = bool(_AUV_SONAR_RE.search(s) or _AUV_SONAR_RE.search(d))
    is_rv = any(p.startswith(pfx) for pfx in _SURFACE_VESSEL_PREFIXES)
    if auv_named or (is_rv and has_auv_sonar):
        return (True, "auv", "AUV name or AUV sonar present")
    if not p and has_auv_sonar:
        return (True, "auv", "AUV sonar identified despite blank platform")

    # 3. Surface vessel — any R/V-prefixed platform without AUV markers.
    if is_rv:
        return (False, "surface_vessel",
                f"platform looks like a research vessel ({p[:30]}); no AUV markers")

    # 4. Unknown / NotApplicable — record as surface_vessel by default
    # (conservative — the modelling step will see the platform string
    # and stratify if needed).
    if p.lower() in ("notapplicable", "n/a", "unknown", ""):
        return (False, "surface_vessel", "platform not specified; treated as surface")
    return (False, "surface_vessel",
            f"platform {p[:40]!r} not recognised as AUV / USV")


def footprint_suspect(area_km2: float, native_res_m: float | None,
                      is_auv_grid: bool, threshold_km2: float = 60.0) -> bool:
    """v1.4.1 §1: flag AUV-class HR whose footprint area is inconsistent
    with a near-bottom survey at its resolution.

    Default threshold = 60 km^2 (per directive). A 1 m AUV grid covering
    >60 km^2 would be ~60 million pixels — possible for very large
    multi-dive surveys, but typically the metadata bbox is inflating a
    sparse-coverage envelope.
    """
    if not is_auv_grid:
        return False
    if area_km2 < threshold_km2:
        return False
    # If resolution is coarser, larger footprints are more plausible.
    if native_res_m is not None and native_res_m >= 4.0:
        return area_km2 > threshold_km2 * 5.0
    return True
