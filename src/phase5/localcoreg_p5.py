"""ACQ-R13 §1 — local (quadrant) co-registration test; replaces the 30 m development bound (Steve's ruling 2026-10-14).

After the frozen global rigid shift (src/coregister.estimate_rigid_xyz, unchanged):
  1. quadrants: the bounding box of the pre-correction joint-valid cells (HR finite and ship real, on the HR grid) is split
     2 x 2 at its centre row / column;
  2. merge: a group that fails the frozen QA thresholds before estimation (joint-valid area >= 1 km2 and >= 1 256-px tile
     of the frozen stride-256 lattice lying wholly inside the group with >= 50 % joint-valid cells) is merged with its
     neighbour along its longer side (else any adjacent group), smallest first, until every group passes or one is left;
  3. each group's rigid shift by the same frozen estimator on the HR cells of that group (against the whole ship grid);
  4. rigid case: every group estimated and its horizontal shift within one ship grid cell (|lr.tif pixel|) of the global
     shift -> the global shift, applied exactly as the frozen chain applies it (bit-identical outputs);
     drift case: otherwise each group's own shift: the HR grid takes the global shift's origin (as the frozen correction)
     and each group's cells move by the residual (group - global) rounded to whole HR pixels (no interpolation of HR
     values; error <= half an HR pixel) with the group's own dz;
  5. after the masks: in the drift case every 256-px tile of the frozen lattice that crosses a group boundary gets
     joint_valid = 0 (so any tiler drops it); each used group must pass the frozen QA (estimated, joint area >= 1 km2,
     >= 1 tile wholly inside with >= 50 % joint-valid).  The case passes if rigid (with the frozen QA minus the 30 m bound)
     or drift with every group passing.
Nothing here prints or logs; group shifts are kept in the sealed site record only.
"""
from __future__ import annotations

import numpy as np

from src import coregister as cor

WIN = 256
MIN_KM2 = 1.0
QUADS = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (1, 1)}          # index -> (row half, col half): NW, NE, SW, SE


def _bbox(valid):
    rr = np.where(valid.any(axis=1))[0]; cc = np.where(valid.any(axis=0))[0]
    return int(rr[0]), int(rr[-1]) + 1, int(cc[0]), int(cc[-1]) + 1


def quadrant_masks(valid) -> dict:
    """{q: bool mask} for the 2 x 2 split of the valid bounding box (cells outside the box belong to no quadrant)."""
    r0, r1, c0, c1 = _bbox(valid)
    rm, cm = (r0 + r1) // 2, (c0 + c1) // 2
    rows = {0: (r0, rm), 1: (rm, r1)}; cols = {0: (c0, cm), 1: (cm, c1)}
    out = {}
    for q, (a, b) in QUADS.items():
        m = np.zeros(valid.shape, bool)
        m[rows[a][0]:rows[a][1], cols[b][0]:cols[b][1]] = True
        out[q] = m
    return out


def _tiles_inside(mask, valid) -> int:
    n = 0
    for r0 in range(0, mask.shape[0] - WIN + 1, WIN):
        for c0 in range(0, mask.shape[1] - WIN + 1, WIN):
            if mask[r0:r0 + WIN, c0:c0 + WIN].all() and valid[r0:r0 + WIN, c0:c0 + WIN].mean() >= 0.5:
                n += 1
    return n


def _qa(mask, valid, px) -> dict:
    km2 = float((valid & mask).sum()) * px * px / 1e6
    return {"area_ge_1km2": bool(km2 >= MIN_KM2), "tiles_ge_1": bool(_tiles_inside(mask, valid) >= 1)}


def groups(valid, px) -> list:
    """Quadrant groups (lists of quadrant indices) after the merge rule."""
    qm = quadrant_masks(valid)
    gs = [[q] for q in QUADS]

    def gmask(g):
        m = np.zeros(valid.shape, bool)
        for q in g:
            m |= qm[q]
        return m

    def ok(g):
        a = _qa(gmask(g), valid, px); return a["area_ge_1km2"] and a["tiles_ge_1"]

    def adjacent(g, h):
        return any(abs(QUADS[a][0] - QUADS[b][0]) + abs(QUADS[a][1] - QUADS[b][1]) == 1 for a in g for b in h)

    while len(gs) > 1:
        bad = [g for g in gs if not ok(g)]
        if not bad:
            break
        g = min(bad, key=lambda x: int((gmask(x) & valid).sum()))
        m = gmask(g); rr = np.where(m.any(axis=1))[0]; cc = np.where(m.any(axis=0))[0]
        h_, w_ = len(rr), len(cc)
        cand = [h for h in gs if h is not g and adjacent(g, h)]
        # neighbour along the longer side: wider than tall -> a vertical neighbour (shares a long horizontal edge)
        pref = [h for h in cand if any((abs(QUADS[a][0] - QUADS[b][0]) == 1 if w_ >= h_ else abs(QUADS[a][1] - QUADS[b][1]) == 1)
                                       and (QUADS[a][1] == QUADS[b][1] if w_ >= h_ else QUADS[a][0] == QUADS[b][0]) for a in g for b in h)]
        h = (pref or cand)[0]
        gs = [x for x in gs if x is not g and x is not h] + [sorted(g + h)]
    return [sorted(g) for g in gs], qm


def estimate(hr_da, lr_da, valid, px_hr, px_lr, glob) -> dict:
    """Group shifts and the rigid / drift decision.  glob = the frozen CoregResult."""
    gs, qm = groups(valid, px_hr)
    out = []
    for g in gs:
        m = np.zeros(valid.shape, bool)
        for q in g:
            m |= qm[q]
        rec = {"quadrants": g, "mask": m}
        try:
            r = cor.estimate_rigid_xyz(hr_da.where(m), lr_da)
            d = float(np.hypot(r.dx_m - glob.dx_m, r.dy_m - glob.dy_m))
            rec.update({"estimated": True, "dx_m": r.dx_m, "dy_m": r.dy_m, "dz_m": r.dz_m, "agrees_with_global": bool(d <= px_lr)})
        except Exception as e:
            rec.update({"estimated": False, "agrees_with_global": False, "error": type(e).__name__})
        out.append(rec)
    rigid = all(g["estimated"] and g["agrees_with_global"] for g in out)
    return {"case": "rigid" if rigid else "drift", "groups": out, "n_groups": len(out), "tolerance_m": px_lr}


def apply_drift(hr_da, glob, est):
    """The drift-case corrected HR: global-shift origin, each group moved by its residual in whole HR pixels, own dz."""
    src = np.asarray(hr_da.values, dtype="float64")
    ny, nx = src.shape
    xr_ = hr_da.x.values; yr_ = hr_da.y.values
    px = float(abs(xr_[1] - xr_[0])); py = float(abs(yr_[1] - yr_[0])); ydown = yr_[1] < yr_[0]
    out = np.full(src.shape, np.nan)
    for g in est["groups"]:
        if not g["estimated"]:
            continue
        kx = int(round((g["dx_m"] - glob.dx_m) / px))
        ky = int(round((g["dy_m"] - glob.dy_m) / py))
        kr = -ky if ydown else ky                               # +y (north) moves content to smaller row indices when y decreases with row
        shifted = np.full(src.shape, np.nan)
        rs0, rs1 = max(0, -kr), min(ny, ny - kr); cs0, cs1 = max(0, -kx), min(nx, nx - kx)
        if rs1 > rs0 and cs1 > cs0:
            shifted[rs0 + kr:rs1 + kr, cs0 + kx:cs1 + kx] = src[rs0:rs1, cs0:cs1]
        sel = g["mask"]
        out[sel] = shifted[sel] + g["dz_m"]
        g["pixel_offset_from_global"] = [kx, ky]               # v4.2: key renamed (a key holding "residual" is forbidden)
    corrected = hr_da.copy(data=out.astype(hr_da.dtype) if np.issubdtype(hr_da.dtype, np.floating) else out)
    corrected.attrs = {}; corrected.encoding = {}            # as apply_xyz's arithmetic: no inherited _FillValue (ACQ-R13 v4.1 fix)
    corrected = corrected.assign_coords(x=hr_da.x + glob.dx_m, y=hr_da.y + glob.dy_m)
    corrected.rio.write_crs(hr_da.rio.crs, inplace=True)
    return corrected


def finalize(joint, est, px_hr) -> tuple:
    """Drift case: zero joint_valid in lattice tiles crossing a group boundary; per-group post QA; the case verdict."""
    joint = joint.copy(); n_drop = 0
    if est["case"] == "drift":
        lab = np.full(joint.shape, -1, int)
        for i, g in enumerate(est["groups"]):
            lab[g["mask"]] = i
        for r0 in range(0, joint.shape[0] - WIN + 1, WIN):
            for c0 in range(0, joint.shape[1] - WIN + 1, WIN):
                t = lab[r0:r0 + WIN, c0:c0 + WIN]
                inside = t[t >= 0]
                if inside.size and (np.unique(inside).size > 1) and joint[r0:r0 + WIN, c0:c0 + WIN].any():
                    joint[r0:r0 + WIN, c0:c0 + WIN] = False; n_drop += 1
    post = []
    for g in est["groups"]:
        q = _qa(g["mask"], joint, px_hr)
        post.append({"quadrants": g["quadrants"], "estimated": g["estimated"], **q,
                     "passes_qa": bool(g["estimated"] and q["area_ge_1km2"] and q["tiles_ge_1"])})
    return joint, n_drop, post


def record(est, post, n_drop, case_pass) -> dict:
    """The site-record entry (group shifts kept, masks dropped; sealed record only)."""
    gs = [{k: v for k, v in g.items() if k != "mask"} for g in est["groups"]]
    return {"case": est["case"], "n_groups_used": est["n_groups"], "tolerance_m": round(est["tolerance_m"], 3), "groups": gs, "post_qa": post,
            "n_tiles_dropped_boundary": n_drop, "case_pass": bool(case_pass),
            "rule": "ACQ-R13 local co-registration (quadrants; one ship cell tolerance; frozen QA minus the 30 m bound)"}
