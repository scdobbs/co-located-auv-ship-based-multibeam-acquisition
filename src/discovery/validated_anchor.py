"""P2-PRE-1 — immutable anchor for the 21 validated pairs (the calibration anchor).

The 2026-06-26 C2a incident: a writer keyed "validated vs new" off
`verification_status` (which is `verified_pair` for BOTH validated and new), so
it (a) wrongly rewrote the 21 validated and (b) its "21 unchanged" guard passed
on an EMPTY set. This module makes the anchor a hardcoded reference of 21 known
values, so any guard built on it *cannot* pass on an empty set.

Use:
  - `is_validated(pair_id)` / `is_new(pair_id)` — discriminate by `__MGDS_`
    (the ONLY reliable discriminator; new pairs are <cruise>__MGDS_<uid>, the
    21 validated are not). Never use `verification_status`.
  - `assert_validated_anchor(df)` — call BEFORE and AFTER every canonical write.
    Asserts all 21 anchor pair_ids are present with their documented lr_native;
    raises on any mismatch or if fewer than 21 are found.
  - `assert_validated_grids(harm_root)` — Phase-2: assert the 21 validated grids'
    sha256 are unchanged (the anchor for the OAK data, not just the index).
"""
from __future__ import annotations
import hashlib
from pathlib import Path

# Documented LR native resolution (m) from the acquisition DOIs — NOT a derived
# proxy. Cal DIG mosaic = 10 m; DISCOL EM122 = 38 m; CCZ = 50 m; TAG = 30 m.
VALIDATED_LR_NATIVE_M = {
    "cal_dig_morro_bay__20180426m2_Channel1000": 10.0,
    "cal_dig_morro_bay__20180427m1_Channel700": 10.0,
    "cal_dig_morro_bay__20180427m3_PockmarkNorth": 10.0,
    "cal_dig_morro_bay__20180428m1_Cable": 10.0,
    "cal_dig_morro_bay__201804_LuciaChica2m": 10.0,
    "cal_dig_morro_bay__20190314m4_LuciaChica970m": 10.0,
    "cal_dig_morro_bay__20190315m1_HeadlessCanyon": 10.0,
    "cal_dig_morro_bay__20190316m1_BankTop": 10.0,
    "cal_dig_morro_bay__20190317m1_1000mGully": 10.0,
    "cal_dig_morro_bay__20190317m2_600mGully": 10.0,
    "cal_dig_morro_bay__20190318m2_Transect601060m": 10.0,
    "cal_dig_morro_bay__20190510m1_BankFlankHoles": 10.0,
    "cal_dig_morro_bay__20190510m2_BankFlankIncipCh": 10.0,
    "cal_dig_morro_bay__20190511m1_6thHeadlessCany": 10.0,
    "cal_dig_morro_bay__20190511m2_BankTopEofCanyon3": 10.0,
    "cal_dig_morro_bay__basin_flank": 10.0,
    "cal_dig_morro_bay__luciachica_2007": 10.0,
    "cal_dig_morro_bay__pockmark_south": 10.0,
    "ccz_so268_1": 50.0,
    "discol_so242_1": 38.0,
    "tag_m127": 30.0,
}
N_VALIDATED = 21
assert len(VALIDATED_LR_NATIVE_M) == N_VALIDATED, "anchor must list exactly 21"
VALIDATED_PAIR_IDS = frozenset(VALIDATED_LR_NATIVE_M)


def is_validated(pair_id: str) -> bool:
    # the 21 validated never carry the new-pair "__MGDS_" suffix
    return "__MGDS_" not in str(pair_id)


def is_new(pair_id: str) -> bool:
    return "__MGDS_" in str(pair_id)


def assert_validated_anchor(df, *, tol: float = 0.05) -> None:
    """Raise unless ALL 21 anchor pairs are present in df with their documented
    lr_native. Cannot pass on an empty/partial set (requires all 21)."""
    present = set(df["pair_id"]) & VALIDATED_PAIR_IDS
    missing = VALIDATED_PAIR_IDS - present
    if missing:
        raise AssertionError(f"validated anchor: {len(missing)} of 21 missing from manifest: {sorted(missing)[:5]}...")
    bad = []
    idx = {r["pair_id"]: r for r in df.to_dict("records")}
    for pid, exp in VALIDATED_LR_NATIVE_M.items():
        got = idx[pid].get("lr_native_res_m")
        try:
            if got is None or abs(float(got) - exp) > tol:
                bad.append((pid, got, exp))
        except (TypeError, ValueError):
            bad.append((pid, got, exp))
    if bad:
        raise AssertionError(f"validated anchor lr_native mismatch ({len(bad)}): {bad[:5]}")
    # structural: exactly 21 matched
    assert len([p for p in VALIDATED_PAIR_IDS if p in idx]) == N_VALIDATED, "anchor cardinality != 21"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def compute_validated_grid_sha256(harm_root: Path) -> dict:
    """sha256 of each validated pair's hr.tif/lr.tif (cal_dig is nested)."""
    out = {}
    for pid in VALIDATED_PAIR_IDS:
        if pid.startswith("cal_dig_morro_bay__"):
            d = harm_root / "cal_dig_morro_bay" / pid.split("__", 1)[1]
        else:
            d = harm_root / pid
        for side in ("hr", "lr"):
            p = d / f"{side}.tif"
            if p.exists():
                out[f"{pid}/{side}"] = _sha256(p)
    return out


def assert_validated_grids(harm_root: Path, reference: dict) -> None:
    """Raise unless the 21 validated grids' sha256 match the reference. Requires
    the reference to be non-empty and every referenced grid to match."""
    if not reference:
        raise AssertionError("validated grid reference is empty — refusing to pass")
    cur = compute_validated_grid_sha256(harm_root)
    bad = [k for k, v in reference.items() if cur.get(k) != v]
    if bad:
        raise AssertionError(f"validated grid sha256 drift ({len(bad)}): {bad[:5]}")
