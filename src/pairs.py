"""Tier-1 verified pair definitions.

DOIs are fixed per the directive (§4 Tier 1). Do not edit without a human
decision and a matching update to the directive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Provider = Literal["pangaea", "sciencebase", "cmgds"]


@dataclass(frozen=True)
class DatasetRef:
    doi: str
    provider: Provider
    platform: str
    sonar: str
    native_res_m: float
    native_crs: str
    license: str


@dataclass(frozen=True)
class Pair:
    pair_id: str
    site_name: str
    region: str
    cruise_id: str
    vessel: str
    acquisition_date: str
    terrain_class: str
    depth_range_m: tuple[float, float]
    hr: DatasetRef
    lr: DatasetRef
    target_crs: str
    vertical_datum: str
    coregistration_required: bool
    verification_status: str
    notes: str = ""
    # v1.3 §5: distinguishes Tier 1 (pre-`hr_source_type`-tracked) rows
    # ("doi") from Tier 2 PANGAEA-on-both-sides rows ("pangaea_doi"). Used
    # only by the manifest writer; both go through the same audit branch
    # (DOI match required).
    hr_source_type: str = "doi"


PAIRS: dict[str, Pair] = {
    "discol_so242_1": Pair(
        pair_id="discol_so242_1",
        site_name="DISCOL Experimental Area",
        region="Peru Basin",
        cruise_id="SO242/1",
        vessel="RV SONNE",
        acquisition_date="2015",
        terrain_class="abyssal_plain",
        depth_range_m=(4100.0, 4200.0),
        hr=DatasetRef(
            doi="10.1594/PANGAEA.905580",
            provider="pangaea",
            platform="AUV ABYSS (REMUS 6000)",
            sonar="Reson 7125",
            native_res_m=2.0,
            native_crs="EPSG:32716",
            license="CC-BY-4.0",
        ),
        lr=DatasetRef(
            doi="10.1594/PANGAEA.905579",
            provider="pangaea",
            platform="RV SONNE hull",
            sonar="Kongsberg EM122",
            native_res_m=38.0,
            native_crs="EPSG:32716",
            license="CC-BY-4.0",
        ),
        target_crs="EPSG:32716",
        vertical_datum="MSL_negative_down",
        coregistration_required=False,
        verification_status="verified_pair",
        notes=(
            "AUV ABYSS HR already corrected against ship EM122 in the source release. "
            "Adjacent topographic high present within the DEA footprint."
        ),
    ),
    # ---- Tier 2 (v1.3) — GEOMAR PANGAEA cruises (HR + LR both on PANGAEA) ----
    # CCZ vertical slice (v1.3 §6). Ship companion `10.1594/PANGAEA.915764`
    # was human-confirmed 2026-06-03 (processed/gridded EM122 of the same
    # German License Area as the AUV). HR native = 3 m (not 2 m as the
    # directive's summary said); kept at native per §3 ("HR is already
    # native — no downsampling"). Both rasters already in EPSG:32611
    # (UTM 11N), so reprojection is a no-op (harmonize.py skips when CRS
    # already matches target).
    # Tier 2 §6 — TAG hydrothermal field, M127 / RV METEOR (2016).
    # Ship companion = `10.1594/PANGAEA.899408` (M127 EM122 working-area
    # product, 30 m gridded GeoTIFF). Confirmed 2026-06-04 after the
    # AtlantOS dataset `868686` (initially picked) was found to provide
    # only transit-track multibeam that does NOT reach the TAG station
    # itself — Transit 1 ends 2 km south of the AUV and Transit 2 starts
    # ~48 km east. `899408` is the dedicated TAG working-area product and
    # its 30 m grid bbox (-45.22, 25.77) → (-44.40, 26.55) fully encloses
    # the AUV (-44.825, 26.128) → (-44.818, 26.138).
    # Both rasters are in EPSG:4326 (lat/lon WGS84). Target CRS = UTM 23N
    # (-48 to -42 longitude band, which the AUV at -44.8 sits in).
    "tag_m127": Pair(
        pair_id="tag_m127",
        site_name="TAG Hydrothermal Field",
        region="Mid-Atlantic Ridge, 26°N",
        cruise_id="M127",
        vessel="RV METEOR",
        acquisition_date="2016",
        terrain_class="hydrothermal_vent",
        depth_range_m=(3500.0, 3700.0),
        hr=DatasetRef(
            doi="10.1594/PANGAEA.899415",
            provider="pangaea",
            platform="AUV ABYSS (REMUS 6000)",
            sonar="Reson 7125",
            native_res_m=2.0,
            native_crs="EPSG:4326",
            license="CC-BY-4.0",
        ),
        lr=DatasetRef(
            doi="10.1594/PANGAEA.899408",
            provider="pangaea",
            platform="RV METEOR hull",
            sonar="Kongsberg EM122",
            native_res_m=30.0,
            native_crs="EPSG:4326",
            license="CC-BY-4.0",
        ),
        target_crs="EPSG:32623",
        vertical_datum="MSL_negative_down",
        coregistration_required=True,
        verification_status="verified_pair",
        notes=(
            "Tier 2 vertical-slice continuation (v1.3 §6). Ship LR is the "
            "M127 EM122 working-area 30 m gridded product at TAG. HR is the "
            "ABYSS 2 m WGS84 GeoTIFF. Expected ratio ~15x — at the low end "
            "of v1.3's 15-25x band for deep EM122. Per v1.3 §4, GEOMAR "
            "grids may be ship-referenced; verify the coreg solve produced "
            "real offsets. Both rasters are in EPSG:4326; reproject to "
            "EPSG:32623 (UTM 23N — TAG sits in the -48 to -42 longitude band)."
        ),
        hr_source_type="pangaea_doi",
    ),
    "ccz_so268_1": Pair(
        pair_id="ccz_so268_1",
        site_name="Clarion-Clipperton Zone — German License Area",
        region="Equatorial NE Pacific (CCZ)",
        cruise_id="SO268/1",
        vessel="RV SONNE",
        acquisition_date="2019",
        terrain_class="nodule_field",
        depth_range_m=(4050.0, 4150.0),
        hr=DatasetRef(
            doi="10.1594/PANGAEA.915765",
            provider="pangaea",
            platform="AUV ABYSS (REMUS 6000)",
            sonar="Reson 7125",
            native_res_m=3.0,
            native_crs="EPSG:32611",
            license="CC-BY-4.0",
        ),
        lr=DatasetRef(
            doi="10.1594/PANGAEA.915764",
            provider="pangaea",
            platform="RV SONNE hull",
            sonar="Kongsberg EM122",
            native_res_m=50.0,
            native_crs="EPSG:32611",
            license="CC-BY-4.0",
        ),
        target_crs="EPSG:32611",
        vertical_datum="MSL_negative_down",
        coregistration_required=True,
        verification_status="verified_pair",
        notes=(
            "Tier 2 vertical slice (v1.3 §6). GEOMAR ship grids are often "
            "already ship-referenced, so coreg offsets may be small — "
            "verify a near-zero solve actually ran (per v1.3 §4). HR native "
            "3 m / LR native 50 m → ratio ~17x."
        ),
        hr_source_type="pangaea_doi",
    ),
    "cal_dig_morro_bay": Pair(
        pair_id="cal_dig_morro_bay",
        site_name="Cal DIG I / Morro Bay",
        region="Offshore South-Central California",
        cruise_id="Cal DIG I",
        vessel="NOAA Rainier/Fairweather (+ R/V Sally Ride gap-fill)",
        acquisition_date="2016-2019",
        terrain_class="continental_margin",
        depth_range_m=(100.0, 1600.0),
        hr=DatasetRef(
            doi="10.5066/P97QM7NF",
            provider="cmgds",
            platform="MBARI-donated AUV",
            sonar="Reson 7125 400 kHz",
            native_res_m=1.0,
            native_crs="EPSG:26910",
            license="public_domain_usgs",
        ),
        lr=DatasetRef(
            doi="10.5066/P9QQZ27U",
            provider="cmgds",
            platform="NOAA hull",
            sonar="Simrad EM 700 series",
            native_res_m=10.0,
            native_crs="EPSG:26910",
            license="public_domain_usgs",
        ),
        target_crs="EPSG:26910",
        vertical_datum="MSL_negative_down",
        coregistration_required=True,
        verification_status="verified_pair",
        notes=(
            "AUV navigation partially processed (relative < 2 m, absolute ~30 m USBL); "
            "not pre-adjusted to ship multibeam. Coregister AUV->ship over the overlap "
            "before treating the pair as valid."
        ),
    ),
}


def get(pair_id: str) -> Pair:
    if pair_id not in PAIRS:
        raise KeyError(f"unknown pair_id={pair_id!r}; known: {list(PAIRS)}")
    return PAIRS[pair_id]


def all_ids() -> list[str]:
    return list(PAIRS)
