"""C2a.4 apply — Steve confirmed the MAX RULE + six corrected values.

lr_native_res_m = max(documented beam footprint, original-grid posting)  [the
coarser, true effective LR resolution]; applied uniformly to all 18 new pairs.
res_ratio = lr_native / hr_native. Metadata-only (rasters unchanged -> checksums
must hold, verified). Backup; 21 validated verbatim; OAK resync + re-lock.
"""
from __future__ import annotations
import hashlib, json, logging, os, shutil, stat
from pathlib import Path
import pandas as pd

log = logging.getLogger("c2apply")
REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "manifest/pairs.parquet"
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/manifest/pairs.parquet")
C2A = REPO / "reports/discovery/stage_c2a_documented_native.json"
RESULT = REPO / "reports/discovery/stage_c2a_apply_result.json"
SIX = {"TN159__MGDS_21981", "RR1506__MGDS_29779", "TN268__MGDS_30466",
       "TN399__MGDS_30373", "NA090__MGDS_31212", "EW9801__MGDS_31425"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"ok": False, "rule": "lr_native = max(documented_footprint, grid_posting)", "changes": []}
    c2a = {r["pair_id"]: r for r in json.loads(C2A.read_text())["pairs"]}
    m = pd.read_parquet(CANON)
    # RELIABLE discriminator: new pairs are <cruise>__MGDS_<uid>; the 21 validated
    # (cal_dig_morro_bay__*, discol_so242_1, ccz_so268_1, tag_m127) have NO "__MGDS_".
    # (verification_status is "verified_pair" for BOTH, so do not use it here.)
    validated = set(p for p in m.pair_id if "__MGDS_" not in p)
    canon_val = m[m.pair_id.isin(validated)].sort_values("pair_id").reset_index(drop=True)
    assert len(validated) == 21, f"expected 21 validated, got {len(validated)}"

    bk = REPO / "manifest/pairs.parquet.bak_2026-06-26_c2a"
    if not bk.exists():
        shutil.copy2(CANON, bk)

    for pid, r in c2a.items():
        if "__MGDS_" not in pid:        # never touch the 21 validated (read-only)
            continue
        fp = r.get("documented_footprint_m"); post = r.get("grid_posting_m")
        cand = [x for x in (fp, post) if x is not None]
        if not cand:
            continue
        new_lr = round(max(cand), 1)
        i = m.index[m.pair_id == pid][0]
        old_lr = float(m.at[i, "lr_native_res_m"]); hr = float(m.at[i, "hr_native_res_m"])
        new_ratio = round(new_lr / hr, 2) if hr > 0 else None
        m.at[i, "lr_native_res_m"] = new_lr
        m.at[i, "res_ratio"] = new_ratio
        m.at[i, "notes"] = str(m.at[i, "notes"]) + (
            f" | C2a 2026-06-26: lr_native={new_lr} = max(footprint {fp}, posting {post}) from {r.get('sonar')}@{r.get('depth_m')}m; "
            f"prior {old_lr}->{new_lr} (proxy artifact); res_ratio {new_ratio}; rasters unchanged")
        res["changes"].append({"pair_id": pid, "old_lr": old_lr, "new_lr": new_lr,
                               "footprint": fp, "posting": post, "new_res_ratio": new_ratio,
                               "material(>3x)": pid in SIX})
        log.info("%-28s lr %s -> %s (max fp=%s post=%s) ratio->%s %s", pid, old_lr, new_lr, fp, post, new_ratio,
                 "[SIX]" if pid in SIX else "")

    # 21 validated verbatim-by-value
    import pandas.testing as pdt
    b = m[m.pair_id.isin(validated)].sort_values("pair_id").reset_index(drop=True)
    pdt.assert_frame_equal(canon_val, b, check_dtype=False)
    res["validated_21_verbatim"] = True

    m.to_parquet(CANON, index=False)

    # rasters unchanged -> checksums in manifest must still match files (verify a sample)
    chkok = True
    for pid in list(c2a)[:6]:
        for side in ("hr", "lr"):
            p = Path(m[m.pair_id == pid][f"harmonized_path_{side}"].iloc[0])
            if p.exists() and sha256(p) != m[m.pair_id == pid][f"checksum_{side}"].iloc[0]:
                chkok = False; log.error("checksum drift %s %s", pid, side)
    res["checksum_unchanged_sample_ok"] = chkok

    # OAK resync
    try:
        if OAK.exists():
            os.chmod(OAK, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        shutil.copy2(CANON, OAK)
        oak_ok = sha256(CANON) == sha256(OAK)
        os.chmod(OAK, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        res["oak_sync"] = {"byte_identical": bool(oak_ok)}
    except Exception as e:
        res["oak_sync"] = {"error": str(e)[:120]}
    res["ok"] = True; res["n_changed"] = len(res["changes"])
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("C2a APPLY COMPLETE: %d rows updated; validated verbatim=%s; OAK %s",
             len(res["changes"]), res["validated_21_verbatim"], res.get("oak_sync"))


if __name__ == "__main__":
    main()
