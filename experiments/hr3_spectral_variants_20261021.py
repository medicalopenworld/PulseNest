"""HR3 spectral variants: spectrum preprocessing x harmonic combination, judged on recorded sessions.

Why this exists
---------------
HR3 picks the pulse fundamental with a Harmonic Product Spectrum, P[k]*P[2k]*P[3k] on the raw power
spectrum (lib v0.109, _hr3_compute()). A product is a multiplicative AND: one harmonic down in the
noise floor kills the candidate although the fundamental is clean, and a near-sinusoidal PPG gives
HPS ~ 0 everywhere and SQI ~ 0 (conversation log 2026-04-12). The preterm PPG at 160-180 bpm is
the case we care about, and the SpO2 artefact gate under decision since 2026-10-20 is "HR3 valid".
Alex (2026-10-21) proposed two independent improvements:
  A. preprocess the spectrum before combining harmonics, to remove the floor that respiration,
     motion below 1 Hz and broadband noise put under the peaks: convolution with a zero-sum
     kernel (positive centre, negative side lobes: Ricker, difference of Gaussians, CFAR blocks),
     or whitening by the local floor;
  B. replace the product with a sum (Noll 1969 Harmonic Sum Spectrum; Hermes 1988 subharmonic
     summation with decaying weights) or a floored product, so a weak harmonic subtracts a bounded
     amount instead of annulling the candidate.
The two are orthogonal, so this script runs the full A x B grid on the same spectra and reports the
metrics agreed in the proposal. Nothing goes into the library until Alex decides on the tables.

What it does
------------
Every session with a reference_spo2.csv (SUBJ01 adult finger, SUBJ08/09/10/11 HOSPNAV neonates,
SUBJ90 MS100 simulator) is read from its board CSV parts: OT_LED1 at the AFE rate, ProbeState, and
the board's own HR1/HR2/HR3/HR3_SQI. The library's HR3 front end is reproduced in numpy exactly as
the lab's HR3TestCalc mirror (lab spec 5.5): per applied run, 4th-order Butterworth low-pass
hr3_f_high_hz = 15 Hz (two precharged biquads), output negated, decimation to 50 Hz, 512-sample
buffer, a window every 25 decimated samples once the buffer is full: mean subtraction, Hann (N-1),
FFT, P = |X|^2. The spectrum of each window is computed ONCE; the variants only change what comes
after it, and the Gaussian sub-bin interpolation on the raw P and the two-bin local SQI are the
library's for every variant (the SQI is provisional: it is re-derived for the chosen variant).

Grid. Preprocessing (A), applied to P and clipped at 0 where it can go negative:
  A0 none
  A1 floor subtraction, S = max(0, P (*) h), h a zero-sum kernel. Shapes: Ricker, DoG (sigma ratio
     1:1.6), CFAR (+ block, 1-bin guard, - reference blocks). Widths: positive half-width 2 bins
     (the Hann main lobe) constant for every harmonic, or scaled by n for the n-th harmonic term
     (one convolution per harmonic, read with stride n).
  A2 whitening, S = P / (median of P over +-8 bins + eps).
Combination (B), over candidates k in the library's search band (27-263 bpm, k <= N/6):
  B0 HPS 3 harmonics  S1[k]*S2[2k]*S3[3k]        (the library today)
  B1 HPS 2 harmonics  S1[k]*S2[2k]
  B2 HSS unit weights S1[k]+S2[2k]+S3[3k]
  B3 HSS Hermes       S1[k]+0.84*S2[2k]+0.7056*S3[3k]
  B4 floored HPS      sum of log(Sn[nk]+c), c = 5 % of the window's band maximum (a floor at the
                      noise median left B4 identical to B0 everywhere: no harmonic sits in the noise)
8 x 5 = 40 variants. --keep-negative-sums leaves A1's negatives in place for B2/B3 (a harmonic
falling in a valley then penalises the candidate, Klapuri-style); off by default so every variant
sees the same S.

References. (i) MS100 sessions: the pulse rate the operator typed with each REF_SPO2 (events with
pr), one plateau per run of equal pr, windows ending 15 s after the first event up to the last.
(ii) Other sessions: consensus of the board's time-domain methods, median HR1 and median HR2 over
the window's 10.24 s, both valid on >= 50 % of the samples and within 3 % of each other; windows
where both are valid but disagree by > 20 % are the artefact class for the SQI separation. The
ward monitor's pulse rate was not captured (the reference CSVs carry no pr), so there is no
monitor reference for the neonates.

Metrics, per subject x variant: availability (valid HR3 over applied windows), error against the
reference (median and p90 of |err|, % within 5 %), harmonic-error rate (ratio to the reference
within 8 % of 2, 1/2, 3, 1/3, 3/2, 2/3), SQI median in consensus and artefact windows with the
rank AUC between them, and - the decision metric - the 2026-10-20 artefact gate "HR3 valid"
re-run with each variant's validity held sample by sample (published windows and Arms per subject,
SpO2 as in spo2_artifact_gate_20261020.py, replay_lib0.108 OT-input replays). Premise check: the
harmonic ratios P[2f0]/P[f0] and P[3f0]/P[f0] at the reference bin, per subject and per 20-bpm band.
Validation: A0 x B0 must reproduce the board's recorded HR3 (value 0.5 s after each window) in
every session; the per-session agreement is printed first and the run is void if it fails.

    python experiments/hr3_spectral_variants_20261021.py [--out DIR] [--keep-negative-sums]
                                                         [--replay replay_lib0.108] [--subjects ...]

Outputs in --out (default captures/sessions/HR3_VARIANTS_20261021/, not versioned):
variant_summary.csv (subject x variant), ms100_plateaus.csv (plateau x variant), gate_summary.csv
(subject x variant, the artefact gate), harmonics.csv (one row per reference window), and
validation.csv (A0 x B0 against the board). Conclusions go in findings.md beside them and in the
library rationale.

Result (2026-10-21; report: captures/sessions/HR3_VARIANTS_20261021/findings.md)
------
- Validation: against the runner's in-order replay (3 sessions, 1939 windows) A0 x B0 gives the same
  value (<= 0.05 bpm) or the same NaN in 100 % of the windows; against the board's column 59-100 %
  within 0.2 bpm per session, <= 1.25 % beyond 5 bpm (Task C asynchrony).
- Premise not supported: neonatal harmonics are 10-12 dB (2nd) and 18-21 dB (3rd) down, not in the
  noise (a noise-median floor left B4 == B0 everywhere). Today's HR3 is right in 89.5-92.5 % of the
  neonates' consensus windows and 100 % of the MS100 plateaus 30-240 (max |e| 0.18 bpm); what it
  lacks is availability (69-88 % vs 99.8 % adult) through the SQI > 0 rule.
- Every floor-removing preprocessing (Ricker/DoG constant width, whitening) raises clean-neonate
  availability to 97.6-99.7 % AND restores HR3 on SUBJ10's motion (6.8 -> 57-92 % of windows): the
  2026-10-20 gate 'HR3 valid' goes from 2.6 % published / Arms 2.0 back to 57-81 % / Arms 15-16 on
  SUBJ10, and SUBJ09 back to the no-gate numbers. The product + SQI rule IS the artefact detector.
- Sums (B2/B3) lose the subharmonic defence (SUBJ10 Arms 10-11 even with A0; 84-89 % correct with
  whitening). Kernels scaled by n fail at 30-60 bpm (lobes reach the next harmonic, 5 bins apart at
  30 bpm); CFAR blocks fail at 30 bpm. With A1 + product the SQI saturates at 1 (AUC 0.5).
- One safe gain: P[k]*P[2k] (A0 x B1): clean-neonate availability +6 to +7 points, harmonic errors
  halved, MS100 100 %, SUBJ10 gate 2.1 % published, gate Arms within 0.2 of today's. Alex's call.
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import spo2_bias_analysis as B   # noqa: E402
from pulsenest import session_events        # noqa: E402

# ── library constants (incunest_afe4490.cpp / lab HR3TestCalc) ──────────────────────────────
DECIM_TARGET_HZ = 50.0
LP_HIGH_HZ      = 15.0        # hr3_f_high_hz
BUF_LEN         = 512         # hr3_buf_len
UPDATE_N        = 25          # hr3_update_interval_s * 50 Hz
SNR_LOCAL_W     = 5           # hr3_snr_local_w
HR_MIN, HR_MAX  = 30.0, 260.0
HR_GUARD        = 3.0
APPLIED         = 2

# ── experiment constants ───────────────────────────────────────────────────────────────────
SUBJECTS        = ("SUBJ01", "SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
MS100_SUBJECTS  = ("SUBJ90",)
PLATEAU_SKIP_S  = 15.0        # after the first event of a plateau (buffer 10.24 s + settling)
CONS_VALID_FRAC = 0.5         # HR1 and HR2 valid on >= this fraction of the window's samples
CONS_AGREE      = 0.03        # |HR1 - HR2| <= 3 % of their mean -> consensus reference
ARTEFACT_DISAGREE = 0.20      # both valid, > 20 % apart -> artefact class
OK_REL          = 0.10        # |err| <= 10 % of the reference counts as correct (the consensus
                              # reference is itself a 10 s median; harmonic errors start at 33 %)
LOG_FLOOR_FRAC  = 0.05        # B4: c = this fraction of the window's band maximum (-13 dB knee)
HARMONIC_TOL    = 0.08        # ratio within 8 % of one of the harmonic ratios -> harmonic error
HARMONIC_RATIOS = (2.0, 0.5, 3.0, 1.0 / 3.0, 1.5, 2.0 / 3.0)
VALID_LAG_S     = 0.1         # the board's HR3 is read this long after each window (Task C latency;
                              # at 0.5 s the next window is already there)
VALID_TOL_BPM   = 0.2
REPLAY_EXACT    = "replay_lib0.109_inputot"   # runner v0.28: HR3 in order after each sample -> same window
HERMES          = (1.0, 0.84, 0.84 ** 2)
KERNEL_HALF_W   = 2.0         # positive half-width in bins (Hann main lobe: first zero at +-2)
WHITEN_HALF_W   = 8           # bins each side for the local median floor
# spo2_artifact_gate_20261020.py's SpO2 rule (copied, not imported: experiments are not a package)
CURVE_A, CURVE_B = 123.98, 39.13
R_CORR_MIN, PI_MAX, SPO2_MIN, SPO2_MAX, CLAMP_MARGIN = 0.8, 20.0, 70.0, 100.0, 10.0
GATE_WINDOW_S   = 8.0
REF_CONF_MIN    = 0.9


# ============================================================================= board CSV parts

def parse_parts(session_dir):
    """OT_LED1, ProbeState, HR1, HR2, HR3, HR3_SQI per row, the AFE rate, and row times (host epoch
    us, the '# @row N clock:' anchors interpolated as tools/spo2_bias_analysis.parse_board_session)."""
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    if not parts:
        raise FileNotFoundError(f"no board CSV parts in {session_dir}")
    cols_needed = ("OT_LED1", "ProbeState", "HR1", "HR2", "HR3", "HR3_SQI")
    out = {k: [] for k in cols_needed}
    anchors_row, anchors_t, rates = [], [], []
    base_row, cols, idx = 0, {}, None
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
                    idx = [cols[c] for c in cols_needed]
                    continue
                v = line.split(",")
                try:
                    vals = [v[i] for i in idx]
                    for k, s in zip(cols_needed, vals):
                        out[k].append(s)
                except (TypeError, IndexError):
                    continue
                part_row += 1
        base_row += part_row
    if not rates:
        raise ValueError(f"{session_dir}: no afe_prf_hz snapshot")
    if len(set(rates)) > 1:
        raise ValueError(f"{session_dir}: AFE rate changed within the session: {sorted(set(rates))}")
    if len(anchors_row) < 2:
        raise ValueError(f"{session_dir}: fewer than 2 clock anchors")
    d = {k: np.array(out[k], dtype=np.float64) for k in cols_needed}
    d["ps"] = d.pop("ProbeState").astype(np.int32)
    n = len(d["OT_LED1"])
    rows = np.arange(n, dtype=np.float64)
    ar, at = np.array(anchors_row, dtype=np.float64), np.array(anchors_t, dtype=np.float64)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0])
    per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    d["t"] = t
    d["fs"] = rates[0]
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


def spectra(d):
    """Every HR3 window of the session: (P [W x N/2+1], raw row index of each window's last sample).
    Runs of ProbeState APPLIED are processed independently, as the library resets on any other state."""
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
        n_dec = len(dec)
        # compute at decimated index i when (i+1) % UPDATE_N == 0 and i >= BUF_LEN-1
        first = ((BUF_LEN - 1) // UPDATE_N + 1) * UPDATE_N - 1
        idx = np.arange(first, n_dec, UPDATE_N)
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


# ============================================================================= preprocessing (A)

def kernel(shape, half_w):
    """Zero-sum 1-D kernel whose positive lobe spans +-half_w bins."""
    if shape == "cfar":
        c = max(1, int(round(half_w)))                     # centre block +-c, guard 1, ref blocks 2c+1
        nc = 2 * c + 1
        h = np.zeros(nc + 2 + 2 * nc)
        h[nc + 1: 2 * nc + 1] = 1.0 / nc
        h[:nc] = -0.5 / nc
        h[-nc:] = -0.5 / nc
        return h
    if shape == "ricker":
        s = half_w
        L = int(math.ceil(4 * s))
        x = np.arange(-L, L + 1, dtype=np.float64)
        h = (1.0 - x ** 2 / s ** 2) * np.exp(-x ** 2 / (2 * s ** 2))
    elif shape == "dog":
        s1 = half_w / 1.2416                               # zero crossing of G(s1)-G(1.6 s1) at 1.2416 s1
        s2 = 1.6 * s1
        L = int(math.ceil(4 * s2))
        x = np.arange(-L, L + 1, dtype=np.float64)
        h = np.exp(-x ** 2 / (2 * s1 ** 2)) / s1 - np.exp(-x ** 2 / (2 * s2 ** 2)) / s2
    else:
        raise ValueError(shape)
    h -= h.mean()                                          # exact zero sum after sampling
    return h / h[len(h) // 2]                              # unit centre tap


def convolve_rows(P, h):
    pad = len(h) // 2
    Pp = np.pad(P, ((0, 0), (pad, pad)), mode="edge")
    out = np.empty_like(P)
    hr = h[::-1]
    for j in range(P.shape[1]):
        out[:, j] = Pp[:, j:j + len(h)] @ hr
    return out


def local_median(P, w):
    Pp = np.pad(P, ((0, 0), (w, w)), mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(Pp, 2 * w + 1, axis=1)
    return np.median(v, axis=2)


def preprocess(P, k_max, keep_negative=False):
    """name -> (S1, S2, S3): the spectrum each harmonic term reads (S_n[n*k]). Clipped at 0 unless
    keep_negative (then the caller clips for the products)."""
    clip = (lambda a: a) if keep_negative else (lambda a: np.maximum(a, 0.0))
    out = {"A0 none": (P, P, P)}
    for shape in ("ricker", "dog", "cfar"):
        Sc = clip(convolve_rows(P, kernel(shape, KERNEL_HALF_W)))
        out[f"A1 {shape} const"] = (Sc, Sc, Sc)
        out[f"A1 {shape} x n"] = tuple(clip(convolve_rows(P, kernel(shape, KERNEL_HALF_W * n)))
                                        for n in (1, 2, 3))
    floor = local_median(P, WHITEN_HALF_W)
    eps = 1e-3 * float(np.median(floor[:, 1:3 * k_max + 1])) if P.shape[0] else 1e-30
    W = P / (floor + max(eps, 1e-30))
    out["A2 whiten"] = (W, W, W)
    return out


# ============================================================================= combination (B)

def combine(S, k_max, keep_negative):
    """name -> (C [W x k_max+1] for the peak search, Cs >= 0 for the SQI). Bin 0 unused."""
    S1, S2, S3 = S
    k = np.arange(1, k_max + 1)
    T1, T2, T3 = S1[:, k], S2[:, 2 * k], S3[:, 3 * k]
    if keep_negative:
        P1, P2, P3 = np.maximum(T1, 0), np.maximum(T2, 0), np.maximum(T3, 0)
    else:
        P1, P2, P3 = T1, T2, T3
    # floor at a fraction of the fundamental band's maximum: log(P + c) = log c + log(1 + P/c), a
    # soft compression whose knee sits LOG_FLOOR_FRAC below the peak; harmonics under the knee
    # stop deciding. (A floor at the noise median left B4 identical to B0 on every session.)
    c = LOG_FLOOR_FRAC * np.maximum(P1, 0).max(axis=1, keepdims=True)
    c = np.maximum(c, 1e-30)
    res = {
        "B0 HPS3":   (P1 * P2 * P3, None),
        "B1 HPS2":   (P1 * P2, None),
        "B2 HSS":    (T1 + T2 + T3, None),
        "B3 Hermes": (HERMES[0] * T1 + HERMES[1] * T2 + HERMES[2] * T3, None),
        "B4 logHPS": (np.log(P1 + c) + np.log(P2 + c) + np.log(P3 + c), (P1 + c) * (P2 + c) * (P3 + c)),
    }
    out = {}
    for name, (Cb, Cs) in res.items():
        C = np.zeros((Cb.shape[0], k_max + 1)); C[:, 1:] = Cb
        if Cs is None:
            Cs_full = np.maximum(C, 0.0)
        else:
            Cs_full = np.zeros_like(C); Cs_full[:, 1:] = Cs
        out[name] = (C, Cs_full)
    return out


# ============================================================================= peak + SQI

def estimate(P, C, Cs, rate):
    """Per window: HR (bpm, NaN when none) and SQI, the library's search band, interpolation and
    two-bin local SQI on the combined spectrum."""
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
    # the library leaves the previous value when the band maximum is 0 (peak_bin = -1); here that is
    # a window with no energy at all, which does not happen after mean subtraction of a real signal
    ok &= Cs[rows, peak] > 0          # Cs is the non-negative form of C (exp of the log sums)
    hr[ok] = hr_all[ok]
    # SQI only where the HR passed the range check (the library's order). A window whose
    # combined peak sits where P has no local maximum gets a wild delta from the Gaussian
    # interpolation; the library then fails the range check and publishes nothing.
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
    hr[sqi <= 0.0] = np.nan          # the library publishes hr3 only while hr3_sqi > 0 (cpp line 3018)
    return hr, sqi


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


def harmonic_class(hr, ref):
    """0 ok (<= 5 %), 1 harmonic error, 2 other error, -1 no value / no reference."""
    out = np.full(len(hr), -1, dtype=int)
    m = np.isfinite(hr) & np.isfinite(ref)
    ratio = np.where(m, hr / np.where(m, ref, 1), np.nan)
    ok = m & (np.abs(ratio - 1) <= OK_REL)
    harm = m & ~ok & np.any([np.abs(ratio / q - 1) <= HARMONIC_TOL for q in HARMONIC_RATIOS], axis=0)
    out[m] = 2; out[harm] = 1; out[ok] = 0
    return out


def rank_auc(pos, neg):
    """P(SQI_consensus > SQI_artefact), ties half."""
    if len(pos) == 0 or len(neg) == 0:
        return math.nan
    allv = np.concatenate([pos, neg])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv)); ranks[order] = np.arange(1, len(allv) + 1)
    # average ranks for ties
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.zeros(len(cnt)); np.add.at(sums, inv, ranks)
    ranks = sums[inv] / cnt[inv]
    r_pos = ranks[:len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


# ============================================================================= artefact gate (20-10)

def gate_load(session_dir, replay):
    board, _ = B.parse_board_session(session_dir, replay=replay)
    d = {"t": board["t"], "ps": board["ps"], "r": board["r"], "rc": board["r_method2_reg_corr"],
         "pi": board["pi"]}
    raw = CURVE_A - CURVE_B * d["r"]
    d["spo2"] = np.minimum(raw, SPO2_MAX)
    with np.errstate(invalid="ignore"):
        d["base"] = ((d["ps"] == APPLIED) & np.isfinite(d["r"]) & (d["rc"] >= R_CORR_MIN)
                     & np.isfinite(d["pi"]) & (d["pi"] > 0) & (d["pi"] <= PI_MAX)
                     & (raw >= SPO2_MIN) & (raw <= SPO2_MAX + CLAMP_MARGIN))
    return d


def gate_windows(d, ref_t, ref_s, ref_c, anomalies, masks):
    """{variant: [(ref, published, ours)]} over the reference windows, as spo2_artifact_gate_20261020."""
    out = {g: [] for g in masks}
    w_us = GATE_WINDOW_S * 1e6
    for t1, s, c in zip(ref_t, ref_s, ref_c):
        if c < REF_CONF_MIN:
            continue
        i0 = int(np.searchsorted(d["t"], t1 - w_us, side="right"))
        i1 = int(np.searchsorted(d["t"], t1, side="right"))
        if i1 - i0 < B.MIN_VALID_SAMPLES:
            continue
        sl = slice(i0, i1)
        if (d["ps"][sl] == APPLIED).mean() < B.APPLIED_MIN_FRAC:
            continue
        if session_events.covered_fraction(anomalies, t1 - w_us, t1) > B.ANOMALY_MAX_FRAC:
            continue
        for g, m in masks.items():
            ok = d["base"][sl] & m[sl]
            frac = float(ok.mean())
            pub = frac >= B.VALID_MIN_FRAC and ok.sum() >= B.MIN_VALID_SAMPLES
            out[g].append((s, pub, float(np.median(d["spo2"][sl][ok])) if pub else math.nan))
    return out


def hold_mask(n_rows, ps, end_rows, valid):
    """Per-sample validity: each window's result holds from its last sample to the next window's,
    and only while the probe stays applied (the library resets on any other state)."""
    m = np.zeros(n_rows, dtype=bool)
    if len(end_rows) == 0:
        return m
    on = ps == APPLIED
    starts = end_rows
    ends = np.concatenate([end_rows[1:], [n_rows]])
    for s, e, v in zip(starts, ends, valid):
        if v:
            seg = on[s:e]
            off = np.flatnonzero(~seg)
            m[s:s + (off[0] if len(off) else len(seg))] = True
    return m


# ============================================================================= main

def q(v, p):
    return float(np.percentile(v, p)) if len(v) else math.nan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR3_VARIANTS_20261021"))
    ap.add_argument("--replay", default="replay_lib0.108")
    ap.add_argument("--keep-negative-sums", action="store_true")
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    per_subject = {}          # subject -> list of per-window dicts (variant -> hr, sqi) + refs
    validation, plateau_rows, harm_rows, gate_acc = [], [], [], {}
    variant_names = None
    for subject in args.subjects:
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            name = os.path.basename(sd)
            d = parse_parts(sd)
            P, end_rows, rate = spectra(d)
            factor = int(round(d["fs"] / rate))
            k_max = (BUF_LEN // 2) // 3
            if P.shape[0] == 0:
                print(f"  {name}: no HR3 window"); continue
            bin_res = rate / BUF_LEN
            t_end = d["t"][end_rows]
            # references
            if subject in MS100_SUBJECTS:
                ref = np.full(len(end_rows), np.nan); art = np.zeros(len(end_rows), dtype=bool)
                plats = ms100_plateaus(sd)
                for t0, t1, pr in plats:
                    ref[(t_end >= t0) & (t_end <= t1)] = pr
            else:
                ref, art = consensus_reference(d, end_rows, factor)
                plats = []
            # variants
            results = {}
            pre = preprocess(P, k_max, args.keep_negative_sums)
            for a_name, S in pre.items():
                for b_name, (C, Cs) in combine(S, k_max, args.keep_negative_sums).items():
                    hr, sqi = estimate(P, C, Cs, rate)
                    results[f"{a_name} | {b_name}"] = (hr, sqi)
            variant_names = list(results)
            # validation of A0 x B0 against the board's HR3 (VALID_LAG_S later, same applied run)
            hr0 = results["A0 none | B0 HPS3"][0]
            lag = int(VALID_LAG_S * d["fs"])
            j = np.minimum(end_rows + lag, len(d["HR3"]) - 1)
            same_run = np.all([d["ps"][np.minimum(end_rows + s, len(d["ps"]) - 1)] == APPLIED
                               for s in range(0, lag + 1, max(1, lag // 10))], axis=0)
            bh = d["HR3"][j]
            both = same_run & np.isfinite(hr0) & (bh > 0)
            dv = np.abs(hr0[both] - bh[both])
            either = same_run & (np.isfinite(hr0) | (bh > 0))
            # the runner's in-order replay, where it exists, is the exact comparison (same window)
            rep_within, rep_med, rep_n = math.nan, math.nan, 0
            rdir = os.path.join(sd, "derived", REPLAY_EXACT)
            if os.path.isdir(rdir):
                rep_hr = []
                for path in sorted(glob.glob(os.path.join(sd, "*_p[0-9][0-9].csv"))):
                    rp = os.path.join(rdir, os.path.basename(path)[:-4] + "_replay.csv")
                    with open(rp, encoding="utf-8", newline="") as f:
                        rep_hr += [float(row["HR3"]) for row in csv.DictReader(f)]
                rep_hr = np.array(rep_hr)
                if len(rep_hr) == len(d["HR3"]):
                    rb = rep_hr[np.minimum(end_rows + 1, len(rep_hr) - 1)]
                    m = np.isfinite(hr0) | (rb > 0)
                    agree = (np.isfinite(hr0) & (rb > 0) & (np.abs(np.where(np.isfinite(hr0), hr0, 0) - rb) <= 0.05)) | (~np.isfinite(hr0) & ~(rb > 0))
                    rep_n = int(m.sum())
                    rep_within = round(100 * float(agree[m].mean()), 1) if rep_n else math.nan
                    bb = np.isfinite(hr0) & (rb > 0)
                    rep_med = round(float(np.median(np.abs(hr0[bb] - rb[bb]))), 4) if bb.any() else math.nan
            validation.append({"session": name, "windows": int(same_run.sum()), "both_valid": int(both.sum()),
                               "either_valid": int(either.sum()),
                               "within_tol_pct": round(100 * float(np.mean(dv <= VALID_TOL_BPM)), 1) if len(dv) else math.nan,
                               "abs_diff_med": round(float(np.median(dv)), 3) if len(dv) else math.nan,
                               "abs_diff_p99": round(q(dv, 99), 3) if len(dv) else math.nan,
                               "gt5bpm_pct": round(100 * float(np.mean(dv > 5)), 2) if len(dv) else math.nan,
                               "replay_windows": rep_n, "replay_same_pct": rep_within, "replay_abs_diff_med": rep_med})
            print(f"  {name}: {len(end_rows)} windows, fs {d['fs']:.0f}, ref {int(np.isfinite(ref).sum())}, "
                  f"artefact {int(art.sum())}, A0xB0 vs board: {validation[-1]['within_tol_pct']} % within "
                  f"{VALID_TOL_BPM} bpm (n={len(dv)}), med {validation[-1]['abs_diff_med']}")
            # premise: harmonic ratios at the reference bin
            m = np.isfinite(ref)
            for i in np.flatnonzero(m):
                k0 = ref[i] / 60.0 / bin_res
                def pk(nh):
                    c = int(round(nh * k0)); w = nh
                    lo, hi = max(1, c - w), min(P.shape[1] - 1, c + w)
                    return float(P[i, lo:hi + 1].max())
                p1, p2, p3 = pk(1), pk(2), pk(3)
                harm_rows.append({"subject": subject, "session": name, "t_epoch_us": int(t_end[i]),
                                  "ref_bpm": round(float(ref[i]), 1), "p1": p1,
                                  "r2_db": round(10 * math.log10(p2 / p1), 2) if p1 > 0 else math.nan,
                                  "r3_db": round(10 * math.log10(p3 / p1), 2) if p1 > 0 else math.nan})
            # per-window store
            ps_list = per_subject.setdefault(subject, {"ref": [], "art": [], "res": {v: ([], []) for v in variant_names}})
            ps_list["ref"].append(ref); ps_list["art"].append(art)
            for v, (hr, sqi) in results.items():
                ps_list["res"][v][0].append(hr); ps_list["res"][v][1].append(sqi)
            # MS100 plateaus
            for t0, t1, pr in plats:
                sel = (t_end >= t0) & (t_end <= t1)
                for v, (hr, sqi) in results.items():
                    h = hr[sel]; cl = harmonic_class(h, np.full(len(h), pr))
                    plateau_rows.append({"session": name, "pr_bpm": pr, "variant": v, "windows": int(sel.sum()),
                                         "valid_pct": round(100 * float(np.isfinite(h).mean()), 1) if sel.any() else math.nan,
                                         "hr_med": round(float(np.nanmedian(h)), 2) if np.isfinite(h).any() else math.nan,
                                         "abs_err_max": round(float(np.nanmax(np.abs(h - pr))), 2) if np.isfinite(h).any() else math.nan,
                                         "ok_pct": round(100 * float(np.mean(cl == 0)), 1) if sel.any() else math.nan,
                                         "harmonic_pct": round(100 * float(np.mean(cl == 1)), 1) if sel.any() else math.nan,
                                         "sqi_med": round(float(np.median(sqi[sel])), 3) if sel.any() else math.nan})
            # artefact gate (needs the replay; MS100 sessions are not gate targets)
            if subject not in MS100_SUBJECTS and os.path.isdir(os.path.join(sd, "derived", args.replay)):
                g = gate_load(sd, args.replay)
                rt, rs, rc = B.parse_reference(sd)
                anomalies = session_events.anomaly_intervals(sd, subject)
                masks = {"G0 library today": np.ones(len(g["t"]), dtype=bool)}
                for v, (hr, _) in results.items():
                    masks[v] = hold_mask(len(g["t"]), d["ps"], end_rows, np.isfinite(hr))
                for v, rows in gate_windows(g, rt, rs, rc, anomalies, masks).items():
                    gate_acc.setdefault((subject, v), []).extend(rows)

    # ── validation table ──
    with open(os.path.join(args.out, "validation.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(validation[0])); w.writeheader(); w.writerows(validation)

    # ── per subject x variant summary ──
    summ = []
    for subject, st in per_subject.items():
        ref = np.concatenate(st["ref"]); art = np.concatenate(st["art"])
        has_ref = np.isfinite(ref) & (ref >= HR_MIN) & (ref <= HR_MAX)   # a 20 bpm plateau is out of range by design
        for v in variant_names:
            hr = np.concatenate(st["res"][v][0]); sqi = np.concatenate(st["res"][v][1])
            cl = harmonic_class(hr, ref)
            n_ref = int(has_ref.sum())
            err = np.abs(hr[has_ref] - ref[has_ref]); err = err[np.isfinite(err)]
            rel = err / ref[has_ref][np.isfinite(hr[has_ref])]
            pos, neg = sqi[has_ref & np.isfinite(hr)], sqi[art & np.isfinite(hr)]
            summ.append({"subject": subject, "variant": v, "windows": len(hr),
                         "avail_pct": round(100 * float(np.isfinite(hr).mean()), 1),
                         "ref_windows": n_ref,
                         "avail_ref_pct": round(100 * float(np.isfinite(hr[has_ref]).mean()), 1) if n_ref else math.nan,
                         "abs_err_med": round(float(np.median(err)), 2) if len(err) else math.nan,
                         "abs_err_p90": round(q(err, 90), 2) if len(err) else math.nan,
                         "ok_pct": round(100 * float(np.mean(cl[has_ref] == 0)), 1) if n_ref else math.nan,
                         "harmonic_pct": round(100 * float(np.mean(cl[has_ref] == 1)), 1) if n_ref else math.nan,
                         "other_err_pct": round(100 * float(np.mean(cl[has_ref] == 2)), 1) if n_ref else math.nan,
                         "art_windows": int(art.sum()),
                         "art_avail_pct": round(100 * float(np.isfinite(hr[art]).mean()), 1) if art.any() else math.nan,
                         "sqi_ref_med": round(float(np.median(pos)), 3) if len(pos) else math.nan,
                         "sqi_art_med": round(float(np.median(neg)), 3) if len(neg) else math.nan,
                         "sqi_auc": round(rank_auc(pos, neg), 3)})
    with open(os.path.join(args.out, "variant_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0])); w.writeheader(); w.writerows(summ)
    if plateau_rows:
        with open(os.path.join(args.out, "ms100_plateaus.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(plateau_rows[0])); w.writeheader(); w.writerows(plateau_rows)
    if harm_rows:
        with open(os.path.join(args.out, "harmonics.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(harm_rows[0])); w.writeheader(); w.writerows(harm_rows)

    # ── gate summary ──
    gsum = []
    for (subject, v), rows in gate_acc.items():
        b = np.array([o - s for s, pub, o in rows if pub])
        gsum.append({"subject": subject, "variant": v, "windows": len(rows),
                     "published_pct": round(100 * len(b) / max(len(rows), 1), 1),
                     "bias_med": round(float(np.median(b)), 2) if len(b) else math.nan,
                     "absbias_med": round(float(np.median(np.abs(b))), 2) if len(b) else math.nan,
                     "arms": round(float(np.sqrt(np.mean(b ** 2))), 2) if len(b) else math.nan,
                     "off_gt4_pct": round(100 * float(np.mean(np.abs(b) > 4)), 1) if len(b) else math.nan})
    if gsum:
        with open(os.path.join(args.out, "gate_summary.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(gsum[0])); w.writeheader(); w.writerows(gsum)

    # ── console ──
    print("\nValidation A0 x B0 against the board's HR3:")
    for r in validation:
        print(f"  {r['session']:36} n={r['both_valid']:5d}/{r['either_valid']:5d}  within {VALID_TOL_BPM} bpm {r['within_tol_pct']:5.1f} %  "
              f"med {r['abs_diff_med']}  p99 {r['abs_diff_p99']}  >5 bpm {r['gt5bpm_pct']} %"
              + (f"  | replay: same {r['replay_same_pct']} % of {r['replay_windows']}, med {r['replay_abs_diff_med']}"
                 if r["replay_windows"] else ""))
    print("\nPremise: harmonic ratios at the reference bin (median dB), per subject and 20-bpm band:")
    if harm_rows:
        for subject in per_subject:
            hs = [r for r in harm_rows if r["subject"] == subject]
            if not hs:
                continue
            bands = {}
            for r in hs:
                bands.setdefault(int(r["ref_bpm"] // 20) * 20, []).append((r["r2_db"], r["r3_db"]))
            line = "  ".join(f"{b}-{b+19}: {np.nanmedian([x[0] for x in v]):5.1f}/{np.nanmedian([x[1] for x in v]):5.1f} (n={len(v)})"
                             for b, v in sorted(bands.items()))
            print(f"  {subject}: {line}")
    hdr = f"{'subject':7} {'variant':30} {'win':>6} {'avail%':>6} {'nref':>5} {'|e|med':>6} {'|e|p90':>6} {'ok%':>5} {'harm%':>5} {'oth%':>5} {'nart':>5} {'artav%':>6} {'sqiR':>5} {'sqiA':>5} {'auc':>5}"
    print("\n" + hdr)
    for s in summ:
        print(f"{s['subject']:7} {s['variant']:30} {s['windows']:6d} {s['avail_pct']:6.1f} {s['ref_windows']:5d} {s['abs_err_med']:6.2f} "
              f"{s['abs_err_p90']:6.2f} {s['ok_pct']:5.1f} {s['harmonic_pct']:5.1f} {s['other_err_pct']:5.1f} {s['art_windows']:5d} "
              f"{s['art_avail_pct']:6.1f} {s['sqi_ref_med']:5.2f} {s['sqi_art_med']:5.2f} {s['sqi_auc']:5.2f}")
    if gsum:
        print(f"\nArtefact gate 'HR3 valid' with each variant (SpO2 vs ward monitor, {args.replay}):")
        print(f"{'subject':7} {'variant':30} {'win':>5} {'pub%':>6} {'bias':>6} {'|b|med':>6} {'Arms':>6} {'>4pt%':>6}")
        for s in gsum:
            print(f"{s['subject']:7} {s['variant']:30} {s['windows']:5d} {s['published_pct']:6.1f} {s['bias_med']:6.2f} "
                  f"{s['absbias_med']:6.2f} {s['arms']:6.2f} {s['off_gt4_pct']:6.1f}")
    if plateau_rows:
        print("\nMS100 plateaus, A0 x B0:")
        for r in plateau_rows:
            if r["variant"] == "A0 none | B0 HPS3":
                print(f"  {r['session']:36} {r['pr_bpm']:5.0f} bpm  n={r['windows']:4d} valid {r['valid_pct']:5.1f} %  "
                      f"med {r['hr_med']:7.2f}  max|e| {r['abs_err_max']:6.2f}  ok {r['ok_pct']:5.1f} %  harm {r['harmonic_pct']:5.1f} %  sqi {r['sqi_med']:.2f}")
        prs = sorted({r["pr_bpm"] for r in plateau_rows})
        print("\nMS100 ok % per plateau (bpm) and variant; '.' = 100, 'x' = 0:")
        print(f"{'variant':30} " + " ".join(f"{p:5.0f}" for p in prs))
        for v in variant_names:
            cells = []
            for p in prs:
                rs = [r for r in plateau_rows if r["variant"] == v and r["pr_bpm"] == p]
                okp = float(np.mean([r["ok_pct"] for r in rs])) if rs else math.nan
                cells.append("    ." if okp >= 99.95 else ("    x" if okp <= 0.05 else f"{okp:5.1f}"))
            print(f"{v:30} " + " ".join(cells))


if __name__ == "__main__":
    main()
