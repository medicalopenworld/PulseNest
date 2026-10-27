"""R estimators A/B on the referenced corpus: regression (R-METHOD-2) vs sub-window decorrelation vs
harmonic-bin R (2026-10-27).

Why this exists
---------------
The Masimo/Nellcor prior-art report (docs/masimo_nellcor_spo2_prior_art.md, section 2) shows that the
red-IR correlation r of R-METHOD-2 cannot fall below 2*sqrt(ra*rv)/(ra+rv) for two uncorrelated sources,
0.954 for arterial 95 % plus venous 70 %, so the r >= 0.8 gate cannot see venous or motion admixture
(SUBJ10: r 0.96 with -16 points). Two separations that use sums the library already keeps were simulated
there (section 2.3) and never tried on real captures: Masimo's decorrelation closed form (US 5,632,272
eq. 98-103, expired) solved over sub-windows, and R measured on the pulse-harmonic bins only. Alex
approved the offline A/B on 2026-10-27 (recommendation 1 of the report). It also serves rationale
section 18: if an estimator that discards the venous component moves the neonatal pairs, the 0.07 offset
between neonatal foot and adult finger is venous admixture in the processing.

What it does
------------
Every session with a reference and a `derived/replay_lib0.108_inputot/` replay (OT columns, HR3) is
re-processed in Python, mirroring the library's R-METHOD-2 chain from the recorded OT: per applied
segment, DC = EMA tau 2 s seeded on the first sample; x = BP(ot_ir)/DC_ir, y = BP(ot_red)/DC_red with
the library's one-biquad band-pass (0.5-5 Hz, precharged); first differences dx, dy; the products
dx*dy, dx^2, dy^2 summed per 100 ms block; a window of 60 blocks (6 s). From the same block sums:

    REG   R = sum(dx*dy) / sum(dx^2) over the window            -- the library (checked against the replay)
    DEC   Masimo's constraint -R1 + (ra+rv)*R12 - ra*rv*R2 = 0 (R1 = sum dy^2, R2 = sum dx^2,
          R12 = sum dx*dy) written for the 6 sub-windows of 1 s and solved by least squares for
          s = ra+rv, p = ra*rv; ra = smaller root of z^2 - s*z + p. Invalid (ill-conditioned, i.e. the
          mixing does not vary across the window, or complex/negative roots) -> the regression's R.
    HARM  R = sum Re(Y*conj(X)) / sum |X|^2 over +-1 bin around the first three harmonics of HR3 (Hann
          window, 6 s and 10.24 s), on the 0.5-15 Hz band (the 2nd harmonic of a 150-180 BPM neonate is
          at 5-6 Hz, above the SpO2 band); NaN while HR3 is not valid.

SpO2 = 123.98 - 39.13*R for every estimator (the shipped curve; the curve belongs to the estimator and
a re-fit is the register's job, not this script's). Each estimator is scored with the library's own
validity rule (probe applied, r >= 0.8, PI known and <= 20 %, 70 <= a - b*R <= 110) with and without
the HR3 pulse gate, against the ward monitor / home oximeter / simulator readings (VideoNest OCR,
confidence >= 0.9, 8 s window ending at the reading, probe on >= 80 %, no ABNORMAL CONDITION, published
when >= 25 % of the samples pass; the value is the median of the passing samples), exactly as
experiments/spo2_artifact_gate_20261020.py. Attribution: the intercept at the shared slope 39.13
(median of ref + 39.13*R over stationary windows) per estimator and population.

    python experiments/r_estimators_ab_20261027.py [--replay replay_lib0.108_inputot] [--out DIR]

Outputs in --out (default captures/sessions/R_ESTIMATORS_AB_20261027/, not versioned): ab_windows.csv
(one row per reference window x estimator x gate) and ab_summary.csv; tables on stdout.

Result (2026-10-27; 21 sessions with the lib 0.108 OT replay: SUBJ08 4, SUBJ09 3, SUBJ10 7, SUBJ11 3,
SUBJ01 3 of 10, SUBJ90 1 of 2)
------
- REG reproduces the replay's R to 2.5e-6 (median) and 7e-6 (p99): the Python chain is the library's.
- DEC is ill-conditioned 91-98 % of the time (valid in 2-9 % of applied samples), so it falls back to the
  regression almost always, and where it acts it is noisier: SUBJ08 Arms 3.03 -> 3.47 (no pulse gate) and
  2.42 -> 3.46 (gated). On SUBJ10 without the pulse gate it lowers the error without fixing it (|bias|
  median 15.7 -> 10.2 points, 70 % of windows still beyond 4 points).
- HARM is NaN without a valid HR3, so it carries the pulse gate by construction. Under the gate it equals
  or slightly beats the regression on the still neonates (SUBJ09 Arms 2.39 -> 2.07, > 4 pt 7.4 -> 4.4 %;
  SUBJ11 1.23 -> 1.08; SUBJ08 2.42 -> 2.42) and is worse on the 15 SUBJ10 windows that pass the gate
  (Arms 2.05 -> 4.62). The 10.24 s frame adds nothing over 6 s. Adult finger and MS100 are unchanged
  (their error is the calibration offset).
- Attribution (rationale section 18): the neonatal-foot vs adult-finger offset at the shared slope is
  3.25 points with REG, 3.08 with DEC, 3.10 with HARM6 and 3.19 with HARM10; the per-level median R
  differences (0.04-0.05 at 94 %, 0.09-0.10 at 99 %) do not move. Discarding the content outside the
  pulse harmonics does not remove the offset: it is not venous admixture that the processing could
  separate; what remains is the reference, the site, or physiology locked to the heartbeat.
- Conclusion: nothing changes in the library. The pulse gate (v0.110) stays the artefact criterion;
  HARM is a candidate second estimator only if a later campaign confirms the 0.1-0.3 Arms gain on still
  neonates; DEC as formulated (6 x 1 s) is not usable on this corpus.
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np
from scipy.signal import lfilter, lfilter_zi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import spo2_bias_analysis as B   # noqa: E402
from pulsenest import session_events        # noqa: E402

CURVE_A, CURVE_B = 123.98, 39.13           # R-CURVE-STS0163-HOSPNAV-20261004 (shipped)
R_CORR_MIN, PI_MAX, SPO2_MIN, SPO2_MAX, CLAMP_MARGIN = 0.8, 20.0, 70.0, 100.0, 10.0
APPLIED = 2
WINDOW_S = 8.0
REF_CONF_MIN = 0.9
SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ01", "SUBJ90")
NEONATAL = ("SUBJ08", "SUBJ09", "SUBJ11")

DC_TAU_S = 2.0                 # spo2_ema_mean_tau_s
SPO2_BP = (0.5, 5.0)           # spo2_bp_f_low_hz / spo2_bp_f_high_hz
HARM_BP = (0.5, 15.0)          # the PI band: keeps the 2nd/3rd harmonics of a neonatal pulse
BLOCK_S = 0.1                  # alg_window_block_s
SPO2_WINDOW_S = 6.0            # spo2_window_s
DIV_EPS = 1e-9                 # spo2_div_eps
REG_EPS = 1e-30                # spo2_reg_eps
K_SUB = 6                      # sub-windows of the decorrelation (1 s each at 6 s)
COND_MIN = 0.02                # smallest/largest singular value below this: mixing does not vary
HARM_WINDOWS_S = (6.0, 10.24)
N_HARM = 3

ESTIMATORS = ("REG", "DEC", "HARM6", "HARM10")


# ----------------------------------------------------------------------------- the library's chain

def biquad_bp(f_low, f_high, fs):
    """INCUNEST_AFE4490::BiquadFilter::init_bp: 2nd-order Butterworth band-pass, bilinear transform."""
    k = 2.0 * fs
    o_low = k * math.tan(math.pi * f_low / fs)
    o_hi = k * math.tan(math.pi * f_high / fs)
    o0sq, bw = o_low * o_hi, o_hi - o_low
    d = k * k + bw * k + o0sq
    b = np.array([bw * k / d, 0.0, -bw * k / d])
    a = np.array([1.0, 2.0 * (o0sq - k * k) / d, (k * k - bw * k + o0sq) / d])
    return b, a


def filt_precharged(b, a, x):
    """lfilter started in the steady state of the first sample: the library's precharge (biquad) and
    the EmaChannel seed (mean = first sample)."""
    zi = lfilter_zi(b, a) * x[0]
    y, _ = lfilter(b, a, x, zi=zi)
    return y


def ema(x, tau_s, fs):
    alpha = 1.0 - math.exp(-1.0 / (tau_s * fs))
    return filt_precharged(np.array([alpha]), np.array([1.0, -(1.0 - alpha)]), x)


def block_sums(v, L):
    nb = len(v) // L
    return v[:nb * L].reshape(nb, L).sum(axis=1)


def window_sums(c, N):
    """c = cumsum of block sums (with a leading 0); window sum ending at block k (k >= N) over blocks
    k-N+1..k, NaN before: the library publishes its first value one block after the window is full."""
    out = np.full(len(c) - 1, np.nan)
    out[N:] = c[N + 1:] - c[1:-N]
    return out


def decorrelation(cxy, cxx, cyy, N, K):
    """Sub-window least-squares solution of Masimo's constraint over the window ending at block k.
    Returns ra (NaN where invalid). c* are cumsums with a leading 0."""
    nb = len(cxx) - 1
    m = N // K
    ks = np.arange(nb)
    a_rows, c_rows = [], []
    for j in range(K):
        lo = ks - N + 1 + j * m           # first block of sub-window j
        hi = lo + m                       # one past its last block
        ok = lo >= 0
        lo_c, hi_c = np.where(ok, lo, 0), np.where(ok, hi, 0)
        sxx = cxx[hi_c] - cxx[lo_c]
        sxy = cxy[hi_c] - cxy[lo_c]
        syy = cyy[hi_c] - cyy[lo_c]
        with np.errstate(divide="ignore", invalid="ignore"):
            a_rows.append(np.where(ok & (sxx > 0), sxy / sxx, np.nan))
            c_rows.append(np.where(ok & (sxx > 0), syy / sxx, np.nan))
    A = np.array(a_rows)                  # (K, nb): a_j = R12_j / R2_j
    C = np.array(c_rows)                  # (K, nb): c_j = R1_j / R2_j
    valid = np.all(np.isfinite(A), axis=0) & np.all(np.isfinite(C), axis=0)
    SA2, SA, SAC, SC = (A * A).sum(0), A.sum(0), (A * C).sum(0), C.sum(0)
    # normal equations of  min sum_j (a_j*s - p - c_j)^2 :  SA2*s - SA*p = SAC ;  SA*s - K*p = SC
    det = -SA2 * K + SA * SA
    with np.errstate(divide="ignore", invalid="ignore"):
        s = (-K * SAC + SA * SC) / det
        p = (SA2 * SC - SA * SAC) / det
        # conditioning of M = [a_j, -1]: eigenvalues of M^T M = [[SA2, -SA], [-SA, K]]
        tr, dt = SA2 + K, SA2 * K - SA * SA
        disc_e = np.sqrt(np.maximum(tr * tr - 4 * dt, 0.0))
        lam_max, lam_min = (tr + disc_e) / 2, (tr - disc_e) / 2
        cond = np.sqrt(np.maximum(lam_min, 0.0) / lam_max)
        disc = s * s - 4 * p
        ra = (s - np.sqrt(np.maximum(disc, 0.0))) / 2
    valid &= np.isfinite(det) & (det != 0) & (cond >= COND_MIN) & (disc >= 0) & (p > 0) & (s > 0)
    return np.where(valid, ra, np.nan), valid


def harmonic_r(dx, dy, ticks, f0, W, fs, chunk=400):
    """R over +-1 bin around the first N_HARM harmonics of f0 (Hz), Hann window of W samples ending at
    each tick sample (inclusive). NaN where f0 is not valid or the window does not fit the segment."""
    out = np.full(len(ticks), np.nan)
    starts = ticks - W + 1
    ok = (starts >= 1) & np.isfinite(f0) & (f0 > 0)
    if not ok.any():
        return out
    win = np.hanning(W)
    freqs = np.fft.rfftfreq(W, 1.0 / fs)
    df = freqs[1]
    n_bins = len(freqs)
    vx = np.lib.stride_tricks.sliding_window_view(dx, W)
    vy = np.lib.stride_tricks.sliding_window_view(dy, W)
    idx_ok = np.flatnonzero(ok)
    for c0 in range(0, len(idx_ok), chunk):
        sel = idx_ok[c0:c0 + chunk]
        X = np.fft.rfft(vx[starts[sel]] * win, axis=1)
        Y = np.fft.rfft(vy[starts[sel]] * win, axis=1)
        num = np.zeros(len(sel)); den = np.zeros(len(sel))
        for h in range(1, N_HARM + 1):
            centre = np.rint(h * f0[sel] / df).astype(int)
            for off in (-1, 0, 1):
                kb = np.clip(centre + off, 0, n_bins - 1)
                Xk = X[np.arange(len(sel)), kb]; Yk = Y[np.arange(len(sel)), kb]
                num += np.real(Yk * np.conj(Xk)); den += np.abs(Xk) ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            out[sel] = np.where(den > 0, num / den, np.nan)
    return out


def process_segment(ir, red, hr3, fs):
    """One applied segment -> per-sample arrays of R per estimator, r (regression) and the DEC validity."""
    n = len(ir)
    L = max(1, int(round(fs * BLOCK_S)))
    N = max(1, min(120, int(round(SPO2_WINDOW_S * fs / L))))
    res = {k: np.full(n, np.nan) for k in ESTIMATORS}
    res["r"] = np.full(n, np.nan)
    res["dec_valid"] = np.zeros(n, dtype=bool)
    if n < 2 * L:
        return res
    dc_ir, dc_red = ema(ir, DC_TAU_S, fs), ema(red, DC_TAU_S, fs)
    b5, a5 = biquad_bp(*SPO2_BP, fs)
    b15, a15 = biquad_bp(*HARM_BP, fs)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.where(dc_ir > DIV_EPS, filt_precharged(b5, a5, ir) / dc_ir, 0.0)
        y = np.where(dc_red > DIV_EPS, filt_precharged(b5, a5, red) / dc_red, 0.0)
        x15 = np.where(dc_ir > DIV_EPS, filt_precharged(b15, a15, ir) / dc_ir, 0.0)
        y15 = np.where(dc_red > DIV_EPS, filt_precharged(b15, a15, red) / dc_red, 0.0)
    dx = np.zeros(n); dy = np.zeros(n); dx[1:] = np.diff(x); dy[1:] = np.diff(y)
    dx15 = np.zeros(n); dy15 = np.zeros(n); dx15[1:] = np.diff(x15); dy15[1:] = np.diff(y15)
    bxy, bxx, byy = block_sums(dx * dy, L), block_sums(dx * dx, L), block_sums(dy * dy, L)
    nb = len(bxy)
    cxy, cxx, cyy = (np.concatenate([[0.0], np.cumsum(v)]) for v in (bxy, bxx, byy))
    sxy, sxx, syy = window_sums(cxy, N), window_sums(cxx, N), window_sums(cyy, N)
    with np.errstate(divide="ignore", invalid="ignore"):
        eps_ok = (sxx > REG_EPS) & (syy > REG_EPS)
        r_reg = np.where(eps_ok, sxy / sxx, np.nan)
        corr = np.where(eps_ok, sxy / np.sqrt(sxx * syy), np.nan)
    ra, dec_ok = decorrelation(cxy, cxx, cyy, N, K_SUB)
    ra = np.where(np.isfinite(r_reg), ra, np.nan)      # DEC lives inside the regression's window
    r_dec = np.where(np.isfinite(ra), ra, r_reg)
    ticks = (np.arange(nb) + 1) * L - 1                # sample index at which block k completes
    f0 = np.where(hr3[ticks] > 0, hr3[ticks] / 60.0, np.nan)
    harm = {W_s: harmonic_r(dx15, dy15, ticks, f0, int(round(W_s * fs)), fs) for W_s in HARM_WINDOWS_S}
    # per-sample: the value of the last completed block at or before sample i (NaN before the first)
    kb = (np.arange(n) + 1) // L - 1
    have = kb >= 0
    kb_c = np.where(have, kb, 0)

    def spread(v):
        return np.where(have, v[kb_c], np.nan)
    res["REG"], res["DEC"], res["r"] = spread(r_reg), spread(r_dec), spread(corr)
    res["HARM6"], res["HARM10"] = spread(harm[6.0]), spread(harm[10.24])
    res["dec_valid"] = np.where(have, dec_ok[kb_c] & np.isfinite(ra[kb_c]), False)
    return res


# ----------------------------------------------------------------------------- sessions

def load(session_dir, replay):
    board, _curve = B.parse_board_session(session_dir, replay=replay)
    ot1, ot2, hr3 = [], [], []
    for path in sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv"))):
        rp = os.path.join(session_dir, "derived", replay, os.path.basename(path)[:-4] + "_replay.csv")
        with open(rp, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ot1.append(float(row["OT_LED1"])); ot2.append(float(row["OT_LED2"])); hr3.append(float(row["HR3"]))
    d = {"t": board["t"], "ps": board["ps"], "r_lib": board["r"], "rc_lib": board["r_method2_reg_corr"],
         "pi": board["pi"], "hr3": np.array(hr3), "ir": np.array(ot1), "red": np.array(ot2)}
    if len(d["ir"]) != len(d["t"]):
        raise ValueError(f"{session_dir}: OT rows {len(d['ir'])} != {len(d['t'])}")
    fs = 1e6 / np.median(np.diff(d["t"]))
    d["fs"] = float(round(fs))
    n = len(d["t"])
    for k in ESTIMATORS + ("r",):
        d[k] = np.full(n, np.nan)
    d["dec_valid"] = np.zeros(n, dtype=bool)
    on = d["ps"] == APPLIED
    edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(np.int8), [0]])))
    for i0, i1 in zip(edges[::2], edges[1::2]):
        seg = process_segment(d["ir"][i0:i1], d["red"][i0:i1], d["hr3"][i0:i1], d["fs"])
        for k, v in seg.items():
            d[k][i0:i1] = v
    # the library's validity, per estimator (its own R in the range check; r and PI gates shared)
    with np.errstate(invalid="ignore"):
        common = on & np.isfinite(d["r"]) & (d["r"] >= R_CORR_MIN) & np.isfinite(d["pi"]) & (d["pi"] > 0) & (d["pi"] <= PI_MAX)
        d["base"], d["spo2"] = {}, {}
        for k in ESTIMATORS:
            raw = CURVE_A - CURVE_B * d[k]
            d["base"][k] = common & np.isfinite(raw) & (raw >= SPO2_MIN) & (raw <= SPO2_MAX + CLAMP_MARGIN)
            d["spo2"][k] = np.minimum(raw, SPO2_MAX)
    d["pulse"] = d["hr3"] > 0
    return d


def check_against_replay(d):
    """REG must reproduce the replay's R (float32 on the board, float64 here)."""
    m = np.isfinite(d["REG"]) & np.isfinite(d["r_lib"])
    if not m.any():
        return math.nan, math.nan, 0
    diff = np.abs(d["REG"][m] - d["r_lib"][m])
    return float(np.median(diff)), float(np.percentile(diff, 99)), int(m.sum())


def windows(subject, name, d, ref_t, ref_s, ref_c, anomalies):
    rows = []
    w_us = WINDOW_S * 1e6
    stat_w = B.STAT_HALF_WINDOW_S * 1e6
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
        near = np.abs(ref_t - t1) <= stat_w
        stationary = int(near.sum() >= 3 and np.ptp(ref_s[near]) <= B.STAT_MAX_PTP)
        dec_frac = float(d["dec_valid"][sl].mean())
        for gate_name, gate in (("G0 no pulse gate", np.ones(i1 - i0, dtype=bool)), ("G1 HR3 valid", d["pulse"][sl])):
            for est in ESTIMATORS:
                ok = d["base"][est][sl] & gate
                frac = float(ok.mean())
                pub = frac >= B.VALID_MIN_FRAC and ok.sum() >= B.MIN_VALID_SAMPLES
                r_med = float(np.median(d[est][sl][ok])) if pub else math.nan
                ours = float(np.median(d["spo2"][est][sl][ok])) if pub else math.nan
                rows.append({"subject": subject, "session": name, "t_epoch_us": int(t1), "gate": gate_name,
                             "estimator": est, "ref": s, "stationary": stationary, "pass_frac": round(frac, 4),
                             "published": int(pub), "r_med": r_med, "ours": ours,
                             "bias": ours - s if pub else math.nan, "dec_valid_frac": round(dec_frac, 3)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", default="replay_lib0.108_inputot")
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "R_ESTIMATORS_AB_20261027"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    all_rows = []
    for subject in SUBJECTS:
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            if not os.path.isdir(os.path.join(sd, "derived", args.replay)):
                print(f"  skip {os.path.basename(sd)}: no {args.replay}")
                continue
            d = load(sd, args.replay)
            med, p99, n = check_against_replay(d)
            rt, rs, rc = B.parse_reference(sd)
            anomalies = session_events.anomaly_intervals(sd, subject)
            rows = windows(subject, os.path.basename(sd), d, rt, rs, rc, anomalies)
            all_rows += rows
            on = d["ps"] == APPLIED
            print(f"  {os.path.basename(sd)}: fs {d['fs']:.0f}, {len(d['t'])} samples, "
                  f"|REG - replay R| median {med:.1e} p99 {p99:.1e} ({n} samples); DEC valid in "
                  f"{100 * d['dec_valid'][on].mean():.0f} % of applied samples; "
                  f"{len(rows) // (2 * len(ESTIMATORS))} reference windows")
    with open(os.path.join(args.out, "ab_windows.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0])); w.writeheader(); w.writerows(all_rows)

    summ = []
    for subject in SUBJECTS:
        for gate in ("G0 no pulse gate", "G1 HR3 valid"):
            for est in ESTIMATORS:
                rs = [r for r in all_rows if r["subject"] == subject and r["gate"] == gate and r["estimator"] == est]
                if not rs:
                    continue
                b = np.array([r["bias"] for r in rs if r["published"]])
                summ.append({"subject": subject, "gate": gate, "estimator": est, "windows": len(rs),
                             "published_pct": round(100 * len(b) / len(rs), 1),
                             "bias_med": round(float(np.median(b)), 2) if len(b) else math.nan,
                             "absbias_med": round(float(np.median(np.abs(b))), 2) if len(b) else math.nan,
                             "absbias_p90": round(float(np.percentile(np.abs(b), 90)), 2) if len(b) else math.nan,
                             "arms": round(float(np.sqrt(np.mean(b ** 2))), 2) if len(b) else math.nan,
                             "off_gt4_pct": round(100 * float(np.mean(np.abs(b) > 4)), 1) if len(b) else math.nan})
    with open(os.path.join(args.out, "ab_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0])); w.writeheader(); w.writerows(summ)
    print(f"\n{'subject':7} {'gate':17} {'est':7} {'win':>5} {'pub%':>6} {'bias':>6} {'|b|med':>7} {'|b|p90':>7} {'Arms':>6} {'>4pt%':>6}")
    for s in summ:
        print(f"{s['subject']:7} {s['gate']:17} {s['estimator']:7} {s['windows']:5d} {s['published_pct']:6.1f} "
              f"{s['bias_med']:6.2f} {s['absbias_med']:7.2f} {s['absbias_p90']:7.2f} {s['arms']:6.2f} {s['off_gt4_pct']:6.1f}")

    # SUBJ10, the artefact subject: the windows the library publishes without the pulse gate
    print("\nSUBJ10 windows published without the pulse gate (G0), per estimator: |bias| median / > 4 pt")
    for est in ESTIMATORS:
        b = np.array([r["bias"] for r in all_rows if r["subject"] == "SUBJ10" and r["gate"] == "G0 no pulse gate"
                      and r["estimator"] == est and r["published"]])
        if len(b):
            print(f"  {est:7} n {len(b):4d}  |bias| med {np.median(np.abs(b)):5.2f}  > 4 pt {100 * np.mean(np.abs(b) > 4):5.1f} %")

    # attribution: intercept at the shared slope per estimator and population (stationary windows, G1)
    print(f"\nIntercept at slope {CURVE_B} (median of ref + {CURVE_B}*R), stationary windows published under G1:")
    groups = {"neonatal feet (08+09+11)": NEONATAL, "adult finger (01)": ("SUBJ01",), "MS100 (90)": ("SUBJ90",)}
    print(f"  {'population':26} " + " ".join(f"{e:>14}" for e in ESTIMATORS))
    for gname, subs in groups.items():
        cells = []
        for est in ESTIMATORS:
            rs = [r for r in all_rows if r["subject"] in subs and r["gate"] == "G1 HR3 valid" and r["estimator"] == est
                  and r["published"] and r["stationary"] and np.isfinite(r["r_med"])]
            if rs:
                a = np.median([r["ref"] + CURVE_B * r["r_med"] for r in rs])
                cells.append(f"{a:8.2f} (n{len(rs):4d})")
            else:
                cells.append(f"{'-':>14}")
        print(f"  {gname:26} " + " ".join(cells))
    print("\nMedian R per reference level, neonatal feet vs adult finger (stationary, G1):")
    for lvl in (94, 96, 98, 99):
        line = f"  {lvl:3d} %:"
        for est in ESTIMATORS:
            vals = {}
            for gname, subs in (("neo", NEONATAL), ("adult", ("SUBJ01",))):
                rr = [r["r_med"] for r in all_rows if r["subject"] in subs and r["gate"] == "G1 HR3 valid"
                      and r["estimator"] == est and r["published"] and r["stationary"] and round(r["ref"]) == lvl]
                vals[gname] = (np.median(rr), len(rr)) if len(rr) >= 10 else (math.nan, len(rr))
            line += f"  {est}: neo {vals['neo'][0]:.3f}({vals['neo'][1]}) adult {vals['adult'][0]:.3f}({vals['adult'][1]})"
        print(line)


if __name__ == "__main__":
    main()
