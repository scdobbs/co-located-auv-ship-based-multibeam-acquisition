"""Phase 2 Stage C.5 — spectral SR-signal sweep.

Reframes the corpus from the (mis-fitting) LR/AUV ratio gate to a per-pair
"recoverable SR signal at factor k" measure: target = LR_native / k. For each
pair and k in {2,4,8} measure whether the AUV carries *recoverable* morphology
in the SR band [f_LR, k*f_LR] (structured/predictable) vs unpredictable
roughness (the hallucination zone).

Metric (calibrated in S0, applied in S1):
  - sr_signal   = fraction of HR radial-PSD energy in the SR band
  - slope       = log-log PSD slope in the SR band (red/structured << 0 vs white ~0)
  - edge_coh    = LR<->HR magnitude-squared coherence at the band edge f_LR
                  (does fine structure correlate with coarse -> predictable)
  - verdict     = recoverable_signal / marginal / roughness_only  (S0 thresholds)

Analysis only: resampling to a common projected grid is a spectral artifact,
NOT Stage-F harmonization; writes no validated pair.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.transform import from_origin


def _utm_epsg(lon, lat):
    z = int((lon + 180) // 6) + 1
    return 32600 + z if lat >= 0 else 32700 + z


def load_to_common(lr_path, hr_path, bounds_lonlat, target_res_m, maxdim=1024):
    """Resample LR and HR onto a common local-UTM grid over the footprint at
    target_res_m. The grid is capped to maxdim per side (centre-cropping the
    target extent) so the SR band stays resolvable while FFT cost is bounded.
    bounds_lonlat = (w, s, e, n). Returns (lr, hr, dx_m) on identical grids."""
    w, s, e, n = bounds_lonlat
    epsg = _utm_epsg((w + e) / 2, (s + n) / 2)
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    W = max(16, int((xmax - xmin) / target_res_m))
    H = max(16, int((ymax - ymin) / target_res_m))
    if W > maxdim:                                  # centre-crop target extent
        cx = (xmin + xmax) / 2
        xmin, xmax = cx - maxdim * target_res_m / 2, cx + maxdim * target_res_m / 2
        W = maxdim
    if H > maxdim:
        cy = (ymin + ymax) / 2
        ymin, ymax = cy - maxdim * target_res_m / 2, cy + maxdim * target_res_m / 2
        H = maxdim
    dst_tr = from_origin(xmin, ymax, target_res_m, target_res_m)
    out = {}
    for key, path in (("lr", lr_path), ("hr", hr_path)):
        dst = np.full((H, W), np.nan, dtype="float32")
        for cand in (str(path), f"NETCDF:{path}"):
            try:
                with rasterio.open(cand) as src:
                    src_crs = src.crs or "EPSG:4326"
                    arr = src.read(1, masked=True).astype("float32").filled(np.nan)
                    reproject(arr, dst, src_transform=src.transform, src_crs=src_crs,
                              dst_transform=dst_tr, dst_crs=f"EPSG:{epsg}",
                              src_nodata=np.nan, dst_nodata=np.nan,
                              resampling=Resampling.bilinear)
                break
            except Exception:
                continue
        out[key] = dst
    return out["lr"], out["hr"], target_res_m


def _prep(arr):
    """Detrend (planar) + Hann window a 2D array; NaN -> filled with mean."""
    a = np.array(arr, dtype="float64")
    m = np.isfinite(a)
    if m.sum() < 64:
        return None
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    A = np.c_[xx[m], yy[m], np.ones(m.sum())]
    coef, *_ = np.linalg.lstsq(A, a[m], rcond=None)
    trend = coef[0] * xx + coef[1] * yy + coef[2]
    a = np.where(m, a - trend, 0.0)
    wy = np.hanning(a.shape[0])[:, None]
    wx = np.hanning(a.shape[1])[None, :]
    return a * (wy * wx)


def _radial(F2, dx):
    """Radial bins, LOG-spaced (equal bins per octave) so a half-octave local
    window holds a consistent number of bins at any frequency — avoids the
    low-frequency bin-starvation that linear bins cause. Returns (edges, idx)."""
    H, W = F2.shape
    fy = np.fft.fftfreq(H, d=dx)[:, None]
    fx = np.fft.fftfreq(W, d=dx)[None, :]
    fr = np.sqrt(fy ** 2 + fx ** 2)
    fmax = min(np.abs(fy).max(), np.abs(fx).max())
    fmin = 1.0 / (max(H, W) * dx)            # smallest resolvable frequency
    nb = 48
    edges = np.logspace(np.log10(fmin), np.log10(fmax), nb + 1)
    idx = np.clip(np.digitize(fr.ravel(), edges) - 1, 0, nb - 1)
    return edges, idx, fr


def radial_psd(arr, dx):
    p = _prep(arr)
    if p is None:
        return None, None
    F = np.fft.fft2(p)
    P = (np.abs(F) ** 2).ravel()
    edges, idx, _ = _radial(np.abs(F) ** 2, dx)
    nb = len(edges) - 1
    psd = np.array([P[idx == b].mean() if (idx == b).any() else np.nan for b in range(nb)])
    fc = np.sqrt(edges[:-1] * edges[1:])   # geometric centre (log bins)
    return fc, psd


def coherence(lr, hr, dx):
    """Azimuthally-averaged magnitude-squared coherence vs radial frequency."""
    pl, ph = _prep(lr), _prep(hr)
    if pl is None or ph is None:
        return None, None
    Fl, Fh = np.fft.fft2(pl), np.fft.fft2(ph)
    edges, idx, _ = _radial(np.abs(Fl) ** 2, dx)
    nb = len(edges) - 1
    cross = (Fl * np.conj(Fh)).ravel()
    pll = (np.abs(Fl) ** 2).ravel()
    phh = (np.abs(Fh) ** 2).ravel()
    coh = np.full(nb, np.nan)
    for b in range(nb):
        sel = idx == b
        if sel.sum() >= 4:
            num = np.abs(cross[sel].sum()) ** 2
            den = pll[sel].sum() * phh[sel].sum()
            coh[b] = num / den if den > 0 else np.nan
    fc = np.sqrt(edges[:-1] * edges[1:])
    return fc, coh


def _cap_pair(lr, hr, dx, maxdim=1024):
    """Crop a central window (<= maxdim) over the most-filled region, at NATIVE
    resolution — preserves the high frequencies the SR band needs, bounds FFT."""
    H, W = hr.shape
    if max(H, W) <= maxdim:
        return lr, hr, dx
    # center on the centroid of finite HR data
    m = np.isfinite(hr)
    if m.any():
        ys, xs = np.where(m)
        cy, cx = int(ys.mean()), int(xs.mean())
    else:
        cy, cx = H // 2, W // 2
    h = maxdim // 2
    y0 = min(max(0, cy - h), max(0, H - maxdim)); y1 = y0 + min(maxdim, H)
    x0 = min(max(0, cx - h), max(0, W - maxdim)); x1 = x0 + min(maxdim, W)
    return lr[y0:y1, x0:x1], hr[y0:y1, x0:x1], dx


def sr_metrics(lr, hr, dx, lr_native_m, k, maxdim=1024):
    """SR-signal, slope, edge coherence for factor k. Band = [f_lr, k*f_lr]."""
    if lr.shape != hr.shape:
        # align shapes (crop to common) before capping
        H = min(lr.shape[0], hr.shape[0]); W = min(lr.shape[1], hr.shape[1])
        lr, hr = lr[:H, :W], hr[:H, :W]
    lr, hr, dx = _cap_pair(lr, hr, dx, maxdim)
    fc, psd_hr = radial_psd(hr, dx)
    fcl, psd_lr = radial_psd(lr, dx)
    if fc is None or fcl is None:
        return None
    f_lr = 1.0 / lr_native_m
    f_hi = k * f_lr
    band = np.isfinite(psd_hr) & (fc >= f_lr) & (fc <= f_hi)
    # SR-band power EXCESS of HR over the (smooth) upsampled-LR baseline:
    #   real fine structure >> 1; circular (HR==upsampled LR) ~ 1; white > 1.
    hr_band = float(np.nansum(psd_hr[band]))
    lr_band = float(np.nansum(np.where(band, psd_lr, np.nan)))
    sr_excess = round(hr_band / lr_band, 2) if lr_band > 0 else None
    # log-log slope of HR PSD in the SR band: red/structured (<<0) vs white (~0)
    slope = np.nan
    if band.sum() >= 3:
        lx, ly = np.log10(fc[band]), np.log10(psd_hr[band])
        good = np.isfinite(lx) & np.isfinite(ly) & (psd_hr[band] > 0)
        if good.sum() >= 3:
            slope = float(np.polyfit(lx[good], ly[good], 1)[0])
    # LR<->HR coherence at the band edge: low = independent acquisitions;
    # high = the HR structure is already in the LR (circular / leaked).
    fco, coh = coherence(lr, hr, dx)
    edge_coh = np.nan
    if fco is not None:
        j = int(np.argmin(np.abs(fco - f_lr)))
        win = coh[max(0, j - 1):j + 2]
        edge_coh = float(np.nanmean(win)) if np.isfinite(win).any() else np.nan
    return {"k": k, "f_lr": round(f_lr, 5),
            "sr_excess": sr_excess,
            "slope": None if slope != slope else round(slope, 2),
            "edge_coh": None if edge_coh != edge_coh else round(edge_coh, 3),
            "sr_band_cells": int(band.sum())}


def band_rms(arr, dx, f_lo, f_hi, maxdim=1024):
    """Physical RMS height (metres) of the field's structure in the radial
    frequency band [f_lo, f_hi], plus the characteristic wavelength (m).
    Band-pass via FFT then RMS over valid cells — gives geomorphic amplitude,
    not an energy fraction. Planar-detrended (no taper, to keep amplitude)."""
    a = np.array(arr, dtype="float64")
    m = np.isfinite(a)
    if m.sum() < 64:
        return None, None
    H, W = a.shape
    if max(H, W) > maxdim:                       # central crop for cost
        ys, xs = np.where(m)
        cy, cx = int(ys.mean()), int(xs.mean())
        h = maxdim // 2
        y0 = min(max(0, cy - h), max(0, H - maxdim)); x0 = min(max(0, cx - h), max(0, W - maxdim))
        a = a[y0:y0 + maxdim, x0:x0 + maxdim]; m = np.isfinite(a); H, W = a.shape
    yy, xx = np.mgrid[0:H, 0:W]
    A = np.c_[xx[m], yy[m], np.ones(m.sum())]
    coef, *_ = np.linalg.lstsq(A, a[m], rcond=None)
    trend = coef[0] * xx + coef[1] * yy + coef[2]
    res = np.where(m, a - trend, 0.0)
    F = np.fft.fft2(res)
    fy = np.fft.fftfreq(H, d=dx)[:, None]; fx = np.fft.fftfreq(W, d=dx)[None, :]
    fr = np.sqrt(fy ** 2 + fx ** 2)
    bm = (fr >= f_lo) & (fr <= f_hi)
    band = np.real(np.fft.ifft2(F * bm))
    rms = float(np.sqrt(np.mean(band[m] ** 2)))
    p = np.abs(F * bm) ** 2
    fcent = float(np.sum(fr * p) / np.sum(p)) if np.sum(p) > 0 else None
    char = (1.0 / fcent) if fcent and fcent > 0 else None
    return round(rms, 3), (round(char, 1) if char else None)


def local_slope(fc, psd, f_target, octave=0.5):
    """Log-log PSD slope in a half-octave window centred on f_target — measures
    structure at the SPECIFIC scale a factor-k task must produce (not 'is this
    red anywhere'). Returns (slope, n_bins)."""
    lo, hi = f_target * 2 ** (-octave), f_target * 2 ** (octave)
    band = np.isfinite(psd) & (fc >= lo) & (fc <= hi) & (psd > 0)
    if band.sum() < 3:
        return None, int(band.sum())
    s = float(np.polyfit(np.log10(fc[band]), np.log10(psd[band]), 1)[0])
    return s, int(band.sum())


def perk_curve(lr, hr, dx, lr_native_m, ks, maxdim=1024):
    """Per-k factor-specific recoverability curve on a (finer) common grid.
    For each k the target frequency is k/LR_native = k*f_lr; recoverability is
    the LOCAL slope there (red=structured/recoverable, flat=white/roughness),
    plus the global edge coherence (circular guard). Also returns uq_above: the
    AUV energy fraction above the target band (the per-pair uncertainty target).
    Truncates at the grid Nyquist (only k with k*f_lr < Nyquist are resolvable)."""
    if lr.shape != hr.shape:
        H = min(lr.shape[0], hr.shape[0]); W = min(lr.shape[1], hr.shape[1])
        lr, hr = lr[:H, :W], hr[:H, :W]
    lr, hr, dx = _cap_pair(lr, hr, dx, maxdim)
    fc, ph = radial_psd(hr, dx)
    if fc is None:
        return None
    f_lr = 1.0 / lr_native_m
    nyq = float(np.nanmax(fc))
    fco, coh = coherence(lr, hr, dx)
    edge_coh = np.nan
    if fco is not None:
        j = int(np.argmin(np.abs(fco - f_lr)))
        win = coh[max(0, j - 1):j + 2]
        edge_coh = float(np.nanmean(win)) if np.isfinite(win).any() else np.nan
    valid = np.isfinite(ph) & (fc > 0)
    total = np.nansum(ph[valid])
    out = {"f_lr": round(f_lr, 5), "nyquist": round(nyq, 4),
           "edge_coh": None if edge_coh != edge_coh else round(edge_coh, 3),
           "per_k": {}}
    for k in ks:
        f_t = k * f_lr
        if f_t >= nyq * 0.9:
            out["per_k"][str(k)] = {"resolvable": False}
            continue
        s, nb = local_slope(fc, ph, f_t)
        uq = float(np.nansum(np.where(valid & (fc > f_t), ph, np.nan)) / total) if total > 0 else None
        out["per_k"][str(k)] = {"resolvable": True, "f_target": round(f_t, 5),
                                "slope_local": None if s is None else round(s, 2),
                                "n_bins": nb,
                                "uq_above_target": None if uq is None else round(uq, 4)}
    return out


def perk_verdict(slope_local, edge_coh, thr):
    """Per-k verdict from the LOCAL slope at the k target scale + circular guard."""
    if slope_local is None:
        return "no_spectrum"
    if slope_local >= thr["slope_white"]:
        return "roughness_only"            # flat at this scale -> hallucination
    if edge_coh is not None and edge_coh >= thr["coh_circular"]:
        return "circular_leak"
    if slope_local <= thr["slope_red"]:
        return "recoverable_signal"
    return "marginal"


def verdict(m, thr):
    """Two axes (both calibrated on known references):
      - SLOPE: red/power-law (<<0) = self-similar predictable structure;
        flat (~0) = white roughness = hallucination zone.
      - EDGE COHERENCE: low = independent LR/HR acquisitions (valid pair);
        high = HR already in LR (circular/leaked) -> NOT a valid SR pair.
    """
    if m is None or m.get("slope") is None:
        return "no_spectrum"
    slope = m["slope"]
    coh = m.get("edge_coh")
    # 1) flat spectrum -> white roughness (hallucination), regardless of coherence
    if slope >= thr["slope_white"]:
        return "roughness_only"
    # 2) red but LR<->HR coherent -> the structure is already in the LR (leaked)
    if coh is not None and coh >= thr["coh_circular"]:
        return "circular_leak"
    # 3) red and independent -> genuine recoverable structure
    if slope <= thr["slope_red"]:
        return "recoverable_signal"
    return "marginal"
