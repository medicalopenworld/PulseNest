"""Common offline bench of the heartbeat resolvers (the HR1, HR2 and HR3 families).

What every study of a pulse-rate method needs, in one place: the stored sessions with a cache of
their raw columns, the references of the pulse rate, the error classes, the methods of the spectrum
family measured so far and the SpO2 artefact gate. Offline only: nothing here runs on a board.

Extracted on 2026-11-14 from experiments/hr3_spectral_variants_20261021.py (front end, harmonic
product, consensus reference, gate) and experiments/spectral_autocorrelation_20261112.py (local
contrast, spectral autocorrelation, comb purity). Those two stay as dated studies and are not
imported; experiments/hr3_methods_20261114.py checks that this module reproduces their numbers.
New here: the cache of raw columns (the earlier cache held spectra, of no use to the time-lag
family), the reference read from the ward monitor's screen and the cepstrum of the band.

References of the pulse rate, in order of independence:
  monitor    what the ward monitor showed in the VideoNest snapshots, read by eye on 2026-10-16/17,
             one reading every 10 s (the ECG heart rate where the patient had ECG, else the
             monitor's own pulse rate). The only reference that exists during artefacts.
  consensus  the board's HR1 and HR2 agreeing within 3 % over the window: clean stretches only,
             and not independent of HR1 or HR2.
  plateau    the rate set on the MS100 simulator, from the session's keyboard events.

Method labels (docs/nomenclature.md): HR3_HPS = today's HR3, HR3_SAC = spectral autocorrelation
with local contrast, HR3_CEP = cepstrum of the band; HR2_ACF = today's HR2, HR2_MPM = McLeod pitch
method, HR2_YIN = YIN.

Added on 2026-11-15 (docs/hr2_methods_20261115.md): the time-lag family. hr2_segments is the
library's HR2 chain on the raw columns; lag_sweep is the one sweep r(tau), m(tau) the three methods
share; hr2_acf, hr2_mpm and hr2_yin read it, with the papers' values for MPM and YIN.
Parts 2 and 3 the same day: yin_difference (YIN's fixed integration window, now the default),
mpm_keys / mpm_pick (MPM split so a sweep of k does not search the key maxima again), and
hr2_segments with f_high and buf_len for the front-end variants (experiments/hr2_tuning_20261115.py).

Family 1 (beats in time) lives in pulsenest/hr1_bench.py (2026-11-16): it is causal and fed in
blocks, unlike the window methods here, and it reuses this module's sessions, references and HR3_SAC.
HR1_SQI joined COLUMNS the same day (cache tag cols_v2) so that bench can check its mirror of the board.

Since lab v1.112 pulsenest_lab.py's HR3LAB window (HR3LabCalc) calls hps, hps_estimate, hr3_sac,
comb_purity, log_floor, band_cepstrum and pick_quefrency on each live HR3 window, one row at a
time and with their defaults: a change to any of them, or to a default, changes that window too
(test_pulsenest/hr3lab_test.py compares the two). Since lab v1.113 its HR2LAB window (HR2LabCalc)
calls hr2_family on each live HR2 buffer, under the same rule (test_pulsenest/hr2lab_test.py).
"""
import csv
import glob
import math
import os

import numpy as np

from pulsenest import session_events

# ── library constants (incunest_afe4490.cpp; lab HR3TestCalc) ───────────────────────────────
DECIM_TARGET_HZ = 50.0
LP_HIGH_HZ      = 15.0        # hr3_f_high_hz
BUF_LEN         = 512         # hr3_buf_len
UPDATE_N        = 25          # hr3_update_interval_s * 50 Hz
SNR_LOCAL_W     = 5           # hr3_snr_local_w
HR_MIN, HR_MAX  = 30.0, 260.0
HR_GUARD        = 3.0
APPLIED         = 2

# ── bench constants ─────────────────────────────────────────────────────────────────────────
PLATEAU_SKIP_S    = 15.0      # after the first event of a plateau (buffer 10.24 s + settling)
CONS_VALID_FRAC   = 0.5       # HR1 and HR2 valid on >= this fraction of the window's samples
CONS_AGREE        = 0.03      # |HR1 - HR2| <= 3 % of their mean -> consensus reference
ARTEFACT_DISAGREE = 0.20      # both valid, > 20 % apart -> artefact class
OK_REL            = 0.10      # |err| <= 10 % of the reference counts as correct
HARMONIC_TOL      = 0.08      # ratio within 8 % of a harmonic ratio -> that harmonic error
HARMONIC_RATIOS   = (2.0, 0.5, 3.0, 1.0 / 3.0, 1.5, 2.0 / 3.0)
CLASSES           = ("ok", "x2", "x1/2", "x3", "x1/3", "x3/2", "x2/3", "other", "none")
MONITOR_MAX_GAP_S = 6.0       # a window takes the reading nearest to its end, at most this far
MONITOR_NEIGHBOUR_S = 15.0    # the readings before and after it count as neighbours within this
MONITOR_STABLE_REL = 0.10     # ... and the reference is 'stable' when they are within 10 % of it
F_LO_HZ, F_HI_HZ  = 0.49, 15.0    # band read by the spectral autocorrelation and the cepstrum
D_MAX_HZ          = 7.5       # lags computed by the spectral autocorrelation (half the band)
CONTRAST_HALF_W   = 8         # bins each side for the local median
TOOTH_HALF_W      = 3         # bins each side of n * f0 counted as a tooth
CEP_NFFT          = 2048      # zero padding of the band's sequence: quefrency step 5 ms at 50 Hz / 512
# SpO2 rule of experiments/spo2_artifact_gate_20261020.py
CURVE_A, CURVE_B = 123.98, 39.13
R_CORR_MIN, PI_MAX, SPO2_MIN, SPO2_MAX, CLAMP_MARGIN = 0.8, 20.0, 70.0, 100.0, 10.0
GATE_WINDOW_S   = 8.0
REF_CONF_MIN    = 0.9

COLUMNS = ("OT_LED1", "OT_LED2", "ProbeState", "HR1", "HR1_SQI", "HR2", "HR3", "HR3_SQI")
CACHE_TAG = "cols_v2"         # v2 (2026-11-16): HR1_SQI added, for the HR1 bench's mirror of the board


# ============================================================================= sessions

def session_dirs(sessions_dir, subject):
    """The subject's session folders that carry a reference file, in time order."""
    return [sd for sd in sorted(glob.glob(os.path.join(sessions_dir, subject, f"{subject}_*_20*")))
            if os.path.exists(os.path.join(sd, "reference_spo2.csv"))]


def parse_columns(session_dir):
    """COLUMNS per row from the board CSV parts, the AFE rate and the row times (host epoch us, the
    '# @row N clock:' anchors interpolated as tools/spo2_bias_analysis.parse_board_session)."""
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    if not parts:
        raise FileNotFoundError(f"no board CSV parts in {session_dir}")
    out = {k: [] for k in COLUMNS}
    anchors_row, anchors_t, rates = [], [], []
    base_row, idx = 0, None
    for path in parts:
        part_row = 0
        with open(path, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if line[0] == "#":
                    if line.startswith("# @row ") and " clock: " in line:
                        anchors_row.append(base_row + int(line.split()[2]))
                        anchors_t.append(int(line.split("host_epoch_us=")[1].split()[0]))
                    elif " afe: " in line and "afe_prf_hz=" in line:
                        rates.append(float(line.split("afe_prf_hz=")[1].split()[0]))
                    continue
                if line.startswith("LED2,"):
                    cols = {n: i for i, n in enumerate(line.split(","))}
                    idx = [cols[c] for c in COLUMNS]
                    continue
                v = line.split(",")
                try:
                    vals = [v[i] for i in idx]
                except (TypeError, IndexError):
                    continue
                for k, s in zip(COLUMNS, vals):
                    out[k].append(s)
                part_row += 1
        base_row += part_row
    if not rates:
        raise ValueError(f"{session_dir}: no afe_prf_hz snapshot")
    if len(set(rates)) > 1:
        raise ValueError(f"{session_dir}: AFE rate changed within the session: {sorted(set(rates))}")
    if len(anchors_row) < 2:
        raise ValueError(f"{session_dir}: fewer than 2 clock anchors")
    d = {k: np.array(out[k], dtype=np.float64) for k in COLUMNS}
    d["ps"] = d.pop("ProbeState").astype(np.int32)
    rows = np.arange(len(d["OT_LED1"]), dtype=np.float64)
    ar, at = np.array(anchors_row, dtype=np.float64), np.array(anchors_t, dtype=np.float64)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0])
    per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    d["t"] = t
    d["fs"] = rates[0]
    return d


def load_columns(session_dir, cache_dir=None):
    """parse_columns with a per-session cache (parsing the CSV parts takes most of a run)."""
    if cache_dir is None:
        return parse_columns(session_dir)
    cp = os.path.join(cache_dir, f"{os.path.basename(session_dir)}.{CACHE_TAG}.npz")
    if os.path.exists(cp):
        z = np.load(cp)
        d = {k: z[k] for k in z.files if k != "fs"}
        d["fs"] = float(z["fs"])
        return d
    d = parse_columns(session_dir)
    os.makedirs(cache_dir, exist_ok=True)
    np.savez(cp, **d)
    return d


# ============================================================================= HR3 front end

def _biquad_lp(f_high, fs, q):
    ohm = math.tan(math.pi * f_high / fs); ohm2 = ohm * ohm; inv_q = 1.0 / q
    den = 1.0 + inv_q * ohm + ohm2
    b0 = ohm2 / den
    return b0, 2.0 * b0, b0, 2.0 * (ohm2 - 1.0) / den, (1.0 - inv_q * ohm + ohm2) / den


def _run_biquad(x, coef):
    """DF-II transposed, precharged to steady state on x[0] (BiquadFilter::process after reset)."""
    b0, b1, b2, a1, a2 = coef
    y = np.empty_like(x)
    x0 = float(x[0])
    den = 1.0 + a1 + a2
    y_ss = x0 * (b0 + b1 + b2) / den if den != 0.0 else 0.0
    v1 = y_ss - b0 * x0
    v2 = b2 * x0 - a2 * y_ss
    for i in range(len(x)):
        xi = float(x[i])
        yi = b0 * xi + v1
        v1 = b1 * xi - a1 * yi + v2
        v2 = b2 * xi - a2 * yi
        y[i] = yi
    return y


def hr3_spectra(d):
    """Every HR3 window of the session: (P [W x N/2+1], raw row index of each window's last sample,
    decimated rate). Runs of ProbeState APPLIED are processed independently, as the library resets
    on any other state."""
    fs = d["fs"]
    factor = max(1, int(round(fs / DECIM_TARGET_HZ)))
    c1 = _biquad_lp(LP_HIGH_HZ, fs, 0.54119610)
    c2 = _biquad_lp(LP_HIGH_HZ, fs, 1.30656296)
    hann = np.hanning(BUF_LEN)
    on = (d["ps"] == APPLIED).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    P_all, end_rows = [], []
    for r0, r1 in zip(edges[::2], edges[1::2]):           # [r0, r1) applied
        x = d["OT_LED1"][r0:r1]
        if len(x) < factor * (BUF_LEN + UPDATE_N):
            continue
        y = -_run_biquad(_run_biquad(x, c1), c2)
        dec = y[factor - 1::factor]                        # Decimator::step keeps every factor-th
        first = ((BUF_LEN - 1) // UPDATE_N + 1) * UPDATE_N - 1
        idx = np.arange(first, len(dec), UPDATE_N)
        if len(idx) == 0:
            continue
        win = np.lib.stride_tricks.sliding_window_view(dec, BUF_LEN)[idx - (BUF_LEN - 1)]
        seg = (win - win.mean(axis=1, keepdims=True)) * hann
        X = np.fft.rfft(seg, axis=1)
        P_all.append(X.real ** 2 + X.imag ** 2)
        end_rows.append(r0 + (idx + 1) * factor - 1)
    if not P_all:
        return np.zeros((0, BUF_LEN // 2 + 1)), np.zeros(0, dtype=np.int64), fs / factor
    return np.vstack(P_all), np.concatenate(end_rows), fs / factor


def band_bins(rate):
    """(bin resolution in Hz, first and last bin of the F_LO_HZ..F_HI_HZ band)."""
    bin_res = rate / BUF_LEN
    return bin_res, int(math.ceil(F_LO_HZ / bin_res)), int(math.floor(F_HI_HZ / bin_res))


# ============================================================================= HR3_HPS

def hps(P, n_harmonics):
    """(C, Cs): the harmonic product of the first n_harmonics (3 = the library, 2 = candidate B1)
    for the peak search, and its non-negative form for the SQI. Bin 0 unused."""
    k_max = (BUF_LEN // 2) // 3
    k = np.arange(1, k_max + 1)
    prod = P[:, k].copy()
    for n in range(2, n_harmonics + 1):
        prod = prod * P[:, n * k]
    C = np.zeros((P.shape[0], k_max + 1)); C[:, 1:] = prod
    return C, np.maximum(C, 0.0)


def hps_estimate(P, C, Cs, rate):
    """Per window: HR (bpm, NaN when none) and SQI: the library's search band, interpolation and
    two-bin local SQI on the combined spectrum; the rate is published only while the SQI is > 0."""
    n = BUF_LEN
    bin_res = rate / n
    nyq = n // 2
    k_max = nyq // 3
    s_min = max(1, int(math.ceil((HR_MIN - HR_GUARD) / 60.0 / bin_res)))
    s_max = min(int(math.floor((HR_MAX + HR_GUARD) / 60.0 / bin_res)), nyq - 2, k_max)
    W = P.shape[0]
    hr = np.full(W, np.nan); sqi = np.zeros(W)
    if s_min >= s_max or W == 0:
        return hr, sqi
    band = C[:, s_min:s_max + 1]
    peak = s_min + np.argmax(band, axis=1)                  # first maximum
    rows = np.arange(W)
    pm, pc, pp = P[rows, peak - 1], P[rows, peak], P[rows, peak + 1]
    lm, lc, lp = (np.log(np.where(a > 0, a, 1e-30)) for a in (pm, pc, pp))
    den = lm - 2 * lc + lp
    delta = np.where(den != 0, 0.5 * (lm - lp) / np.where(den != 0, den, 1), 0.0)
    freq = (peak + delta) * bin_res
    hr_all = 60.0 * freq
    ok = (freq > 0) & (hr_all >= HR_MIN) & (hr_all <= HR_MAX)
    ok &= Cs[rows, peak] > 0
    hr[ok] = hr_all[ok]
    safe_delta = np.where(ok, delta, 0.0)
    b1 = np.clip(np.floor(peak + safe_delta).astype(int), 1, k_max)
    b2 = np.minimum(b1 + 1, k_max)
    num = Cs[rows, b1] + Cs[rows, b2]
    lo = b1 - SNR_LOCAL_W; hi = b2 + SNR_LOCAL_W
    win = np.zeros(W); n_win = np.zeros(W)
    for off in range(-SNR_LOCAL_W, SNR_LOCAL_W + 2 + 1):
        kk = b1 + off
        valid = (kk >= 1) & (kk <= k_max) & (kk >= lo) & (kk <= hi)
        win += np.where(valid, Cs[rows, np.clip(kk, 0, k_max)], 0.0)
        n_win += valid
    good = ok & (win > 0) & (n_win > 2)
    snr = np.where(win > 0, num / np.where(win > 0, win, 1), 0.0)
    base = 2.0 / np.maximum(n_win, 1)
    s = np.clip((snr - base) / (1.0 - base), 0.0, 1.0)
    sqi[good] = s[good]
    hr[sqi <= 0.0] = np.nan
    return hr, sqi


# ============================================================================= HR3_SAC

def local_median(P, w):
    Pp = np.pad(P, ((0, 0), (w, w)), mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(Pp, 2 * w + 1, axis=1)
    return np.median(v, axis=2)


def local_contrast(P, b_lo, b_hi, margin_db, cap_db):
    """dB by which each bin of the band stands out of its neighbourhood: L - moving median(L,
    +-CONTRAST_HALF_W) - margin, clipped to [0, cap]."""
    L = 10.0 * np.log10(np.maximum(P[:, 1:b_hi + CONTRAST_HALF_W + 1], 1e-30))
    C = np.clip(L - local_median(L, CONTRAST_HALF_W) - margin_db, 0.0, cap_db)
    return C[:, b_lo - 1:b_hi]


def log_floor(P, b_lo, b_hi, dyn_db):
    """Height of each bin of the band above a floor dyn_db under the band's maximum, in dB."""
    L = 10.0 * np.log10(np.maximum(P[:, b_lo:b_hi + 1], 1e-30))
    top = L.max(axis=1, keepdims=True)
    return np.clip(L - (top - dyn_db), 0.0, dyn_db)


def pearson_lags(Z, d_max):
    """R[w, d] = Pearson correlation of Z[k] and Z[k+d] over the overlap (each side's own mean)."""
    W, N = Z.shape
    R = np.zeros((W, d_max + 1))
    c1 = np.concatenate([np.zeros((W, 1)), np.cumsum(Z, axis=1)], axis=1)
    c2 = np.concatenate([np.zeros((W, 1)), np.cumsum(Z * Z, axis=1)], axis=1)
    for d in range(d_max + 1):
        n = N - d
        sa, sb = c1[:, N - d] - c1[:, 0], c1[:, N] - c1[:, d]
        qa, qb = c2[:, N - d] - c2[:, 0], c2[:, N] - c2[:, d]
        num = (Z[:, :N - d] * Z[:, d:]).sum(axis=1) - sa * sb / n
        den = np.sqrt(np.maximum(qa - sa * sa / n, 0.0) * np.maximum(qb - sb * sb / n, 0.0))
        R[:, d] = np.divide(num, den, out=np.zeros(W), where=den > 1e-12)
    return R


def _pick(c, lft, rgt, alpha):
    """Column of the smallest index whose local maximum reaches alpha of the highest, the parabolic
    offset of that maximum, its height, and whether the row has any local maximum."""
    loc = (c > lft) & (c >= rgt) & (c > 0)
    cm = np.where(loc, c, -np.inf)
    rmax = cm.max(axis=1)
    has = np.isfinite(rmax)
    cand = loc & (c >= alpha * np.where(has, rmax, 0.0)[:, None])
    j = np.argmax(cand, axis=1)
    rows = np.arange(c.shape[0])
    pc, pl, pr = c[rows, j], lft[rows, j], rgt[rows, j]
    den = pl - 2 * pc + pr
    delta = np.where(den < 0, 0.5 * (pl - pr) / np.where(den < 0, den, -1.0), 0.0)
    return j, np.clip(delta, -0.5, 0.5), pc, has


def pick_lag(R, s_min, s_max, alpha, bin_res):
    """Per window: (HR bpm or NaN, rho at the chosen lag). Local maxima of R inside [s_min, s_max];
    alpha < 1 takes the smallest lag whose maximum reaches alpha of the highest (the comb also
    correlates at 2 f0, 3 f0)."""
    d = np.arange(s_min, s_max + 1)
    j, delta, pc, has = _pick(R[:, d], R[:, d - 1], R[:, d + 1], alpha)
    hr = 60.0 * (d[j] + delta) * bin_res
    ok = has & (hr >= HR_MIN) & (hr <= HR_MAX)
    return np.where(ok, hr, np.nan), np.where(ok, pc, 0.0)


def hr3_sac(P, rate, margin_db=6.0, cap_db=30.0, alpha=0.8):
    """Spectral autocorrelation of the local contrast ('logc6 first' of 2026-11-12):
    (HR, rho, contrast sequence, rho against lag)."""
    bin_res, b_lo, b_hi = band_bins(rate)
    d_max = int(math.ceil(D_MAX_HZ / bin_res))
    s_min = max(2, int(math.ceil((HR_MIN - HR_GUARD) / 60.0 / bin_res)))
    s_max = int(math.floor((HR_MAX + HR_GUARD) / 60.0 / bin_res))
    C = local_contrast(P, b_lo, b_hi, margin_db, cap_db)
    R = pearson_lags(C, d_max)
    hr, rho = pick_lag(R, s_min, s_max, alpha, bin_res)
    return hr, rho, C, R


def comb_purity(P, hr, rate):
    """Fraction of the band's LINEAR power inside the teeth of the comb at the given rate
    (n * f0 +- TOOTH_HALF_W bins, every n inside the band), rescaled so that a flat spectrum gives 0."""
    bin_res, b_lo, b_hi = band_bins(rate)
    W, nb = P.shape
    lag = np.where(np.isfinite(hr), hr / 60.0 / bin_res, np.nan)
    mask = np.zeros((W, nb), dtype=bool)
    rows = np.arange(W)
    for n in range(1, int(b_hi // 5) + 2):
        c = np.where(np.isfinite(lag), np.rint(n * np.where(np.isfinite(lag), lag, 0.0)), -1).astype(int)
        for off in range(-TOOTH_HALF_W, TOOTH_HALF_W + 1):
            k = c + off
            ok = (c > 0) & (k >= b_lo) & (k <= b_hi)
            mask[rows[ok], k[ok]] = True
    band = P[:, b_lo:b_hi + 1]
    mb = mask[:, b_lo:b_hi + 1]
    tot = band.sum(axis=1)
    frac = np.divide((band * mb).sum(axis=1), tot, out=np.zeros(W), where=tot > 0)
    base = mb.sum(axis=1) / band.shape[1]
    pur = np.where(base < 0.999, (frac - base) / np.where(base < 0.999, 1.0 - base, 1.0), 0.0)
    return np.where(np.isfinite(hr), np.clip(pur, 0.0, 1.0), 0.0)


# ============================================================================= HR3_CEP

def band_cepstrum(S, bin_res, nfft=CEP_NFFT):
    """Magnitude of the Fourier transform, along frequency, of each row of S (a sequence over the
    band, bins bin_res apart), mean removed, Hann-tapered and zero-padded to nfft. Column n is the
    quefrency n / (nfft * bin_res) seconds: a comb of spacing f0 shows as a peak at 1 / f0 and at
    its multiples. With S a log spectrum this is the cepstrum of the band; its square is the
    Fourier pair of the autocorrelation of S, which is what HR3_SAC reads.
    Returns (A [W x n_max+2], quefrency step in s), cut just above the period of HR_MIN - HR_GUARD."""
    dq = 1.0 / (nfft * bin_res)
    n_max = int(math.floor(60.0 / (HR_MIN - HR_GUARD) / dq))
    taper = np.hanning(S.shape[1])
    out = np.empty((S.shape[0], n_max + 2))
    for i0 in range(0, S.shape[0], 2048):
        Z = (S[i0:i0 + 2048] - S[i0:i0 + 2048].mean(axis=1, keepdims=True)) * taper
        out[i0:i0 + 2048] = np.abs(np.fft.rfft(Z, n=nfft, axis=1))[:, :n_max + 2]
    return out, dq


def pick_quefrency(A, dq, alpha=0.8):
    """Per window: (HR bpm or NaN, height of the chosen peak over the RMS of the search range).
    Local maxima of A between the periods of HR_MAX + HR_GUARD and HR_MIN - HR_GUARD; the smallest
    quefrency whose maximum reaches alpha of the highest (the cepstrum also peaks at 2 T0, 3 T0)."""
    n_min = max(2, int(math.ceil(60.0 / (HR_MAX + HR_GUARD) / dq)))
    n_max = int(math.floor(60.0 / (HR_MIN - HR_GUARD) / dq))
    n = np.arange(n_min, n_max + 1)
    c = A[:, n]
    j, delta, pc, has = _pick(c, A[:, n - 1], A[:, n + 1], alpha)
    hr = 60.0 / ((n[j] + delta) * dq)
    rms = np.sqrt((c * c).mean(axis=1))
    ok = has & (hr >= HR_MIN) & (hr <= HR_MAX)
    q = np.divide(pc, rms, out=np.zeros(len(pc)), where=rms > 0)
    return np.where(ok, hr, np.nan), np.where(ok, q, 0.0)


# ============================================================================= HR2 front end (time-lag family)

HR2_F_LOW_HZ, HR2_F_HIGH_HZ = 0.5, 5.0   # hr2_f_low_hz, hr2_f_high_hz: one-biquad Butterworth band-pass
HR2_BUF_LEN     = 300                    # hr2_buf_len: 6 s at 50 Hz since lib v0.121 (400 = 8 s before;
                                         # the studies of 2026-11-15 pass 400 explicitly)
HR2_UPDATE_N    = 25                     # hr2_update_interval_s * 50 Hz
HR2_LAG_CAP     = 137                    # hr2_acorr_lag_cap
HR2_MIN_CORR    = 0.5                    # hr2_min_corr: HR2_ACF publishes from this peak height
HR2_ENERGY_EPS  = 1e-16                  # hr2_ot_energy_eps
# Fixed on 2026-11-15 before measuring, from the methods' own papers, not tuned on this signal:
MPM_K           = 0.9    # McLeod & Wyvill 2005: first key maximum reaching k of the highest
MPM_MIN_CLARITY = 0.5    # the same bar as HR2_ACF's hr2_min_corr, so both publish on the same rule
YIN_THRESHOLD   = 0.10   # de Cheveigne & Kawahara 2002: absolute threshold on the CMND
# YIN's difference over a fixed integration window (the paper's eq. 6), the default since the second
# part of 2026-11-15: the first part summed over N - tau samples, which shrinks d with the lag and
# pushes YIN to multiples of the period. "shrinking" keeps that first part reproducible.
YIN_WINDOW      = "fixed"
# Chosen for PPG on 2026-11-15, out of sample (docs/hr2_methods_20261115.md part 2: on all three ECG
# subjects, 8 s buffer); what HR2LAB runs since lab v1.114. Not library values: MPM and YIN were
# not adopted.
MPM_K_PPG           = 0.5
MPM_MIN_CLARITY_PPG = 0.5
YIN_THRESHOLD_PPG   = 0.6


def _biquad_bp(f_low, f_high, fs):
    """BiquadFilter::init_bp (lab _Biquad.init_bp): 2nd-order Butterworth band-pass."""
    k = 2.0 * fs
    o_lo, o_hi = k * math.tan(math.pi * f_low / fs), k * math.tan(math.pi * f_high / fs)
    o0sq, bw = o_lo * o_hi, o_hi - o_lo
    den = k * k + bw * k + o0sq
    return bw * k / den, 0.0, -bw * k / den, 2.0 * (o0sq - k * k) / den, (k * k - bw * k + o0sq) / den


def hr2_segments(d, f_high=HR2_F_HIGH_HZ, buf_len=HR2_BUF_LEN):
    """Every HR2 window of the session: (S [W x HR2_BUF_LEN] the decimated band-passed buffer, oldest
    first, raw row index of each window's last sample, decimated rate). The library's chain: band-pass
    at the AFE rate, precharged, negated (peaks up), one sample in `factor` kept, a window every
    HR2_UPDATE_N decimated samples once the buffer is full. Runs of ProbeState APPLIED are processed
    independently, as the library resets on any other state. f_high and buf_len default to the
    library's; other values are bench variants (docs/hr2_methods_20261115.md, part 3)."""
    fs = d["fs"]
    factor = max(1, int(round(fs / DECIM_TARGET_HZ)))
    c = _biquad_bp(HR2_F_LOW_HZ, f_high, fs)
    on = (d["ps"] == APPLIED).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    S_all, end_rows = [], []
    for r0, r1 in zip(edges[::2], edges[1::2]):
        x = d["OT_LED1"][r0:r1]
        if len(x) < factor * (buf_len + HR2_UPDATE_N):
            continue
        dec = -_run_biquad(x, c)[factor - 1::factor]
        first = ((buf_len - 1) // HR2_UPDATE_N + 1) * HR2_UPDATE_N - 1
        idx = np.arange(first, len(dec), HR2_UPDATE_N)
        if len(idx) == 0:
            continue
        S_all.append(np.lib.stride_tricks.sliding_window_view(dec, buf_len)[idx - (buf_len - 1)].copy())
        end_rows.append(r0 + (idx + 1) * factor - 1)
    if not S_all:
        return np.zeros((0, buf_len)), np.zeros(0, dtype=np.int64), fs / factor
    return np.vstack(S_all), np.concatenate(end_rows), fs / factor


def hr2_lag_range(rate, n=HR2_BUF_LEN):
    """(min_lag, max_lag) in decimated samples, as _hr2_compute: the periods of HR_MAX + HR_GUARD and
    HR_MIN - HR_GUARD, capped by HR2_LAG_CAP and n / 2 - 1. 11 and 111 at 50 Hz."""
    lo = max(1, int(60.0 / (HR_MAX + HR_GUARD) * rate))
    hi = min(int(60.0 / (HR_MIN - HR_GUARD) * rate), HR2_LAG_CAP, n // 2 - 1)
    return lo, hi


def lag_sweep(S, max_lag):
    """The one sweep the three methods share, for lags 0..max_lag:
      r[tau] = sum_i x[i] x[i+tau]             m[tau] = sum_i (x[i]^2 + x[i+tau]^2),  i = 0..N-tau-1
    m comes from a prefix sum of x^2 at no extra cost per lag."""
    W, N = S.shape
    r = np.empty((W, max_lag + 1))
    for tau in range(max_lag + 1):
        r[:, tau] = np.einsum("ij,ij->i", S[:, :N - tau], S[:, tau:])
    c = np.concatenate([np.zeros((W, 1)), np.cumsum(S * S, axis=1)], axis=1)
    tau = np.arange(max_lag + 1)
    m = c[:, N - tau] + (c[:, N:N + 1] - c[:, tau])
    return r, m


def _parabola(y_prev, y, y_next, peak=True):
    """Offset of the vertex of the parabola through three equally spaced points, within +-0.5."""
    den = y_prev - 2.0 * y + y_next
    good = den < 0 if peak else den > 0
    return np.clip(np.where(good, 0.5 * (y_prev - y_next) / np.where(good, den, 1.0), 0.0), -0.5, 0.5)


def _publish(lag, has, q, rate):
    """(HR bpm or NaN, quality or 0, lag or NaN) with the library's range check."""
    with np.errstate(divide="ignore", invalid="ignore"):
        hr = 60.0 * rate / lag
    ok = has & np.isfinite(hr) & (hr >= HR_MIN) & (hr <= HR_MAX)
    return np.where(ok, hr, np.nan), np.where(ok, q, 0.0), np.where(ok, lag, np.nan)


def hr2_acf(r, rate, n=HR2_BUF_LEN, min_corr=HR2_MIN_CORR):
    """HR2_ACF, today's HR2 (_hr2_compute): unbiased normalised autocorrelation
    A[tau] = r[tau] N / (r[0] (N - tau)); the first interior strict local maximum inside the lag range
    at or above min_corr; parabolic interpolation; quality = the peak value.
    Returns (HR, quality, lag in decimated samples, A over lags 0..max_lag)."""
    W, L = r.shape
    lo, hi = hr2_lag_range(rate, n)
    tau = np.arange(L)
    r0 = r[:, 0]
    energy = r0 >= HR2_ENERGY_EPS
    A = r * n / (np.where(energy, r0, 1.0)[:, None] * (n - tau)[None, :])
    A[~energy] = 0.0
    j = np.arange(lo + 1, hi)                             # interior of [lo, hi]
    loc = (A[:, j] > A[:, j - 1]) & (A[:, j] > A[:, j + 1]) & (A[:, j] >= min_corr)
    has = energy & loc.any(axis=1)
    k = j[np.argmax(loc, axis=1)]
    rows = np.arange(W)
    lag = k + _parabola(A[rows, k - 1], A[rows, k], A[rows, k + 1])
    hr, q, lag = _publish(lag, has, A[rows, k], rate)
    return hr, q, lag, A


def nsdf(r, m):
    """McLeod's normalised square difference function 2 r / m, in [-1, 1]."""
    return np.divide(2.0 * r, m, out=np.zeros_like(r), where=m > 0)


def mpm_keys(Nf, lo, hi):
    """The key maxima of each NSDF row inside [lo, hi]: the highest point of each positive lobe after
    the first negative-going zero crossing (the lobe at lag 0 is skipped), confirmed by a lower point
    after it. A list of integer lags per window, in increasing order."""
    W, L = Nf.shape
    out = []
    for w in range(W):
        y = Nf[w]
        keys = []
        neg = np.flatnonzero(y < 0)
        if len(neg):
            pos = np.concatenate(([False], y[neg[0]:] > 0, [False]))
            e = np.flatnonzero(np.diff(pos.astype(np.int8)))
            for a, b in zip(e[::2] + neg[0], e[1::2] + neg[0]):     # positive lobe [a, b)
                j = a + int(np.argmax(y[a:b]))
                if j + 1 >= L or y[j + 1] >= y[j] or not (lo <= j <= hi):
                    continue                                         # not confirmed, or out of range
                keys.append(j)
        out.append(keys)
    return out


def mpm_pick(Nf, keys, rate, k=MPM_K, min_clarity=MPM_MIN_CLARITY):
    """McLeod's choice among the key maxima of each window: the first reaching k of the highest,
    published from min_clarity; parabolic interpolation. Returns (HR, clarity, lag)."""
    W = Nf.shape[0]
    lag = np.full(W, np.nan)
    q = np.zeros(W)
    for w, ks in enumerate(keys):
        if not ks:
            continue
        y = Nf[w]
        top = max(y[j] for j in ks)
        j = next(j for j in ks if y[j] >= k * top)
        if y[j] < min_clarity:
            continue
        lag[w] = j + float(_parabola(y[j - 1], y[j], y[j + 1]))
        q[w] = y[j]
    return _publish(lag, np.isfinite(lag), q, rate)


def hr2_mpm(r, m, rate, n=HR2_BUF_LEN, k=MPM_K, min_clarity=MPM_MIN_CLARITY):
    """HR2_MPM, the McLeod pitch method on the NSDF (mpm_keys, then mpm_pick): among the key maxima
    inside the lag range, the first reaching k of the highest; parabolic interpolation; clarity = the
    NSDF at that key maximum, published from min_clarity.
    Returns (HR, clarity, lag, NSDF over lags 0..max_lag)."""
    Nf = nsdf(r, m)
    lo, hi = hr2_lag_range(rate, n)
    hr, q, lag = mpm_pick(Nf, mpm_keys(Nf, lo, hi), rate, k, min_clarity)
    return hr, q, lag, Nf


def yin_difference(S, max_lag):
    """YIN's difference function over a fixed integration window (de Cheveigne & Kawahara 2002, eq. 6),
    for lags 0..max_lag: the newest Wi = N - max_lag samples against their copies tau earlier,
      d[tau] = sum_{i=N-Wi..N-1} (x[i] - x[i-tau])^2,
    the same number of terms at every lag. (m - 2 r sums over N - tau terms instead, so it shrinks as
    the lag grows; that version is YIN_WINDOW = "shrinking".)"""
    W, N = S.shape
    wi = N - max_lag
    seg = S[:, N - wi:]
    d = np.empty((W, max_lag + 1))
    for tau in range(max_lag + 1):
        e = seg - S[:, N - wi - tau:N - tau]
        d[:, tau] = np.einsum("ij,ij->i", e, e)
    return d


def cmnd(d):
    """YIN's cumulative mean normalised difference of the difference function d (yin_difference, or
    m - 2 r for the shrinking window): d'[0] = 1, d'[tau] = d[tau] tau / sum_{j=1..tau} d[j]."""
    d = np.maximum(np.array(d, dtype=float), 0.0)
    d[:, 0] = 0.0
    cs = np.cumsum(d, axis=1)
    tau = np.arange(d.shape[1])
    out = np.divide(d * tau, cs, out=np.ones_like(d), where=cs > 0)
    out[:, 0] = 1.0
    return out


def hr2_yin(r, m, rate, n=HR2_BUF_LEN, threshold=YIN_THRESHOLD, d=None):
    """HR2_YIN: the first lag inside the range where the CMND drops under the absolute threshold, then
    downhill to its local minimum (which must be confirmed inside the range); parabolic
    interpolation; quality = 1 - d' at that minimum. No dip under the threshold: nothing published
    (the paper falls back to the global minimum; a monitor should not). d: the difference function
    (yin_difference, fixed window); None = m - 2 r (shrinking window).
    Returns (HR, quality, lag, d' over lags 0..max_lag)."""
    D = cmnd(m - 2.0 * r if d is None else d)
    W, L = D.shape
    lo, hi = hr2_lag_range(rate, n)
    j = np.arange(lo, hi)                                   # candidates with a right neighbour
    below = D[:, j] < threshold
    has = below.any(axis=1)
    j0 = np.argmax(below, axis=1)
    stop = (D[:, j + 1] >= D[:, j]) & (np.arange(len(j))[None, :] >= j0[:, None])
    has &= stop.any(axis=1)
    k = np.maximum(j[np.argmax(stop, axis=1)], 1)
    rows = np.arange(W)
    lag = k + _parabola(D[rows, k - 1], D[rows, k], D[rows, k + 1], peak=False)
    hr, q, lag = _publish(lag, has, np.clip(1.0 - D[rows, k], 0.0, 1.0), rate)
    return hr, q, lag, D


HR2_METHODS = ("HR2_ACF", "HR2_MPM", "HR2_YIN")


def hr2_family(S, rate, yin_window=YIN_WINDOW, mpm_k=MPM_K, mpm_min_clarity=MPM_MIN_CLARITY,
               yin_threshold=YIN_THRESHOLD):
    """The three time-lag methods on the same windows, from one sweep (plus YIN's fixed-window
    difference): {label: (HR, quality, lag, curve over lags 0..max_lag + 1)}. MPM and YIN default
    to the papers' values; HR2LAB passes the *_PPG ones."""
    _, hi = hr2_lag_range(rate, S.shape[1])
    r, m = lag_sweep(S, hi + 1)
    dy = yin_difference(S, hi + 1) if yin_window == "fixed" else None
    return {"HR2_ACF": hr2_acf(r, rate, S.shape[1]),
            "HR2_MPM": hr2_mpm(r, m, rate, S.shape[1], k=mpm_k, min_clarity=mpm_min_clarity),
            "HR2_YIN": hr2_yin(r, m, rate, S.shape[1], threshold=yin_threshold, d=dy)}


# ============================================================================= references

def ms100_plateaus(session_dir):
    """[(t_start_us, t_end_us, pr_bpm)] from the keyboard REF_SPO2 events carrying a pulse rate,
    retractions applied; a plateau is a run of equal pr."""
    rows = session_events.events(session_dir)
    retracted = set()
    for r in rows:
        if r.get("kind") == "RETRACT":
            for tok in (r.get("note") or "").split():
                if tok.startswith("retracts="):
                    retracted.add(tok.split("=", 1)[1])
    readings = [(int(r["t_epoch_us"]), float(r["value2"])) for r in rows
                if r.get("kind") == "REF_SPO2" and r.get("value2") not in (None, "")
                and r.get("event_id") not in retracted]
    plateaus = []
    for t, pr in readings:
        if plateaus and plateaus[-1][2] == pr:
            plateaus[-1][1] = t
        else:
            plateaus.append([t, t, pr])
    return [(t0 + PLATEAU_SKIP_S * 1e6, t1, pr) for t0, t1, pr in plateaus if t1 > t0 + PLATEAU_SKIP_S * 1e6]


def consensus_reference(d, end_rows, factor):
    """Per window: (ref bpm or NaN, artefact flag) from the board's HR1/HR2 over the window."""
    n_raw = BUF_LEN * factor
    ref = np.full(len(end_rows), np.nan); art = np.zeros(len(end_rows), dtype=bool)
    hr1, hr2 = d["HR1"], d["HR2"]
    for i, e in enumerate(end_rows):
        sl = slice(max(0, e - n_raw + 1), e + 1)
        a, b = hr1[sl], hr2[sl]
        va, vb = a > 0, b > 0
        if va.mean() < CONS_VALID_FRAC or vb.mean() < CONS_VALID_FRAC:
            continue
        ma, mb = float(np.median(a[va])), float(np.median(b[vb]))
        m = 0.5 * (ma + mb)
        if abs(ma - mb) <= CONS_AGREE * m:
            ref[i] = m
        elif abs(ma - mb) > ARTEFACT_DISAGREE * m:
            art[i] = True
    return ref, art


def monitor_readings(path, column=None):
    """(phone epoch us, value, column name) of the by-eye transcription of the monitor snapshots.
    column: 'hr_ecg' (the ECG heart rate) or 'pr' (the monitor's own pulse rate); by default the
    ECG heart rate when the file has it. Rows without a number are skipped. The file keeps the
    snapshot's time to the second (phone clock)."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    if column is None:
        column = "hr_ecg" if rows and "hr_ecg" in rows[0] else "pr"
    t, v = [], []
    for r in rows:
        try:
            x = float(r[column])
        except (KeyError, TypeError, ValueError):
            continue
        t.append(float(r["phone_ms"]) * 1000.0); v.append(x)
    order = np.argsort(t)
    return np.array(t)[order], np.array(v)[order], column


def phone_offset_us(session_dir):
    """Median of host clock minus phone clock over the session's VideoNest rows
    (reference_spo2.csv, offset_ms), in us; None when the session has none."""
    off = []
    with open(os.path.join(session_dir, "reference_spo2.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(line for line in f if not line.startswith("#")):
            try:
                off.append(float(r["offset_ms"]))
            except (KeyError, TypeError, ValueError):
                continue
    return float(np.median(off)) * 1000.0 if off else None


def monitor_reference(read_t, read_v, t_end):
    """Per window: (reference or NaN, stable flag). The reference is the reading nearest to the
    window's end, at most MONITOR_MAX_GAP_S away (the monitor's number and the window both look
    back about 10 s). Stable: the readings before and after it, when within MONITOR_NEIGHBOUR_S,
    are within MONITOR_STABLE_REL of it, so a rate in transition is not scored as an error."""
    ref = np.full(len(t_end), np.nan); stable = np.zeros(len(t_end), dtype=bool)
    if len(read_t) == 0 or len(t_end) == 0:
        return ref, stable
    last = len(read_t) - 1
    i = np.searchsorted(read_t, t_end)
    i0, i1 = np.clip(i - 1, 0, last), np.clip(i, 0, last)
    near = np.where(np.abs(read_t[i0] - t_end) <= np.abs(read_t[i1] - t_end), i0, i1)
    ok = np.abs(read_t[near] - t_end) <= MONITOR_MAX_GAP_S * 1e6
    ref[ok] = read_v[near[ok]]

    def close(j):
        is_neighbour = (j != near) & (np.abs(read_t[j] - read_t[near]) <= MONITOR_NEIGHBOUR_S * 1e6)
        return ~is_neighbour | (np.abs(read_v[j] / read_v[near] - 1.0) <= MONITOR_STABLE_REL)

    stable = ok & close(np.clip(near - 1, 0, last)) & close(np.clip(near + 1, 0, last))
    return ref, stable


# ============================================================================= scoring

def harmonic_class(hr, ref):
    """0 ok (<= OK_REL), 1 harmonic error, 2 other error, -1 no value / no reference (the classes of
    the 2026-10-21 and 2026-11-12 studies)."""
    out = np.full(len(hr), -1, dtype=int)
    m = np.isfinite(hr) & np.isfinite(ref)
    ratio = np.where(m, hr / np.where(m, ref, 1), np.nan)
    ok = m & (np.abs(ratio - 1) <= OK_REL)
    harm = m & ~ok & np.any([np.abs(ratio / q - 1) <= HARMONIC_TOL for q in HARMONIC_RATIOS], axis=0)
    out[m] = 2; out[harm] = 1; out[ok] = 0
    return out


def error_class(hr, ref):
    """Index into CLASSES per window; -1 where there is no reference. 'none' = a reference and no
    value. A value within OK_REL of the reference is ok; otherwise the harmonic ratio it sits on
    (within HARMONIC_TOL), or 'other'."""
    out = np.full(len(hr), -1, dtype=int)
    has_ref = np.isfinite(ref)
    m = has_ref & np.isfinite(hr)
    ratio = np.where(m, hr / np.where(m, ref, 1.0), np.nan)
    out[has_ref] = CLASSES.index("none")
    out[m] = CLASSES.index("other")
    for i, q in enumerate(HARMONIC_RATIOS):
        out[m & (np.abs(ratio / q - 1.0) <= HARMONIC_TOL)] = 1 + i
    out[m & (np.abs(ratio - 1.0) <= OK_REL)] = 0
    return out


def rank_auc(pos, neg):
    """P(pos > neg), ties half."""
    if len(pos) == 0 or len(neg) == 0:
        return math.nan
    allv = np.concatenate([pos, neg])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv)); ranks[order] = np.arange(1, len(allv) + 1)
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.zeros(len(cnt)); np.add.at(sums, inv, ranks)
    ranks = sums[inv] / cnt[inv]
    r_pos = ranks[:len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


# ============================================================================= SpO2 artefact gate

def gate_columns(board):
    """The columns the SpO2 gate reads, from tools/spo2_bias_analysis.parse_board_session's dict
    (a replay of the session), with the SpO2 of the neonatal curve and the base validity rule."""
    d = {"t": board["t"], "ps": board["ps"], "r": board["r"], "rc": board["r_method2_reg_corr"],
         "pi": board["pi"]}
    raw = CURVE_A - CURVE_B * d["r"]
    d["spo2"] = np.minimum(raw, SPO2_MAX)
    with np.errstate(invalid="ignore"):
        d["base"] = ((d["ps"] == APPLIED) & np.isfinite(d["r"]) & (d["rc"] >= R_CORR_MIN)
                     & np.isfinite(d["pi"]) & (d["pi"] > 0) & (d["pi"] <= PI_MAX)
                     & (raw >= SPO2_MIN) & (raw <= SPO2_MAX + CLAMP_MARGIN))
    return d


def gate_windows(d, ref_t, ref_s, ref_c, anomalies, masks, *, min_valid_samples, applied_min_frac,
                 anomaly_max_frac, valid_min_frac):
    """{rule: [(reference SpO2, published, ours)]} over the reference readings, as
    experiments/spo2_artifact_gate_20261020.py. The four limits are those of
    tools/spo2_bias_analysis (passed in: this package does not import a program)."""
    out = {g: [] for g in masks}
    w_us = GATE_WINDOW_S * 1e6
    for t1, s, c in zip(ref_t, ref_s, ref_c):
        if c < REF_CONF_MIN:
            continue
        i0 = int(np.searchsorted(d["t"], t1 - w_us, side="right"))
        i1 = int(np.searchsorted(d["t"], t1, side="right"))
        if i1 - i0 < min_valid_samples:
            continue
        sl = slice(i0, i1)
        if (d["ps"][sl] == APPLIED).mean() < applied_min_frac:
            continue
        if session_events.covered_fraction(anomalies, t1 - w_us, t1) > anomaly_max_frac:
            continue
        for g, m in masks.items():
            ok = d["base"][sl] & m[sl]
            frac = float(ok.mean())
            pub = frac >= valid_min_frac and ok.sum() >= min_valid_samples
            out[g].append((s, pub, float(np.median(d["spo2"][sl][ok])) if pub else math.nan))
    return out


def hold_mask(n_rows, ps, end_rows, valid):
    """Per-sample validity: each window's result holds from its last sample to the next window's,
    and only while the probe stays applied (the library resets on any other state)."""
    m = np.zeros(n_rows, dtype=bool)
    if len(end_rows) == 0:
        return m
    on = ps == APPLIED
    ends = np.concatenate([end_rows[1:], [n_rows]])
    for s, e, v in zip(end_rows, ends, valid):
        if v:
            seg = on[s:e]
            off = np.flatnonzero(~seg)
            m[s:s + (off[0] if len(off) else len(seg))] = True
    return m
