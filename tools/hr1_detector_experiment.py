"""Compare HR1 beat detectors on recorded captures: current threshold vs SSF vs TERMA.

Usage:  python tools/hr1_detector_experiment.py [capture.csv ...]
        (no arguments: runs the default set from captures/)

WHY THIS EXISTS
The filter experiment (tools/hr1_filter_experiment.py) showed the detector, not the low-pass, is
HR1's weak link: under phototherapy interference, with a true rate of 60 BPM, HR1 reads 75.5 BPM
with the moving average and 66.1 with a biquad. Both fail; a better filter only masks a detector
that crosses a threshold without ever asking whether the crossing looks like a pulse.

The three candidates (see incunest_afe4490_design_rationale.md section 5.3):

  CURRENT  rising-edge crossing of 0.6 x a decaying running max, plus a refractory period.
           The threshold comes from a GLOBAL maximum, which interference inflates.

  SSF      Zong's slope sum function: sum the positive slope over a ~128 ms window, which
           amplifies the systolic upstroke and flattens everything else, then threshold that.
           Same decision rule as CURRENT, so the comparison isolates the ENHANCEMENT.

  TERMA    Elgendi's two event-related moving averages over the squared signal: one of ~111 ms
           (peak width) and one of ~667 ms (beat length). Where the peak average exceeds the beat
           average plus a small offset, a block of interest opens; blocks wider than W1 are beats
           and the maximum inside each is the peak. The threshold is LOCAL, which is the point.

All three share the same input (DC removal + low-pass) and the same refractory guard, so
differences are attributable to the decision rule.

READING THE RESULTS
Simulator captures carry a known true rate (60 BPM), so error is absolute. Finger captures have no
ground truth: there FW_HR1 is the firmware's own answer, and agreement between detectors plus RR
dispersion is all that can be said. The captures are adults and a simulator, NOT neonates.
"""
import sys
import math
import os

import numpy as np

FS_HZ            = 500.0
HR1_DC_TAU_S     = 1.6
HR1_LP_CUTOFF_HZ = 5.0
HR1_REFRACTORY_S = 0.185
HR1_THRESH_FRAC  = 0.6
HR1_MAX_DECAY_TAU_S = 20.0     # v0.87: was a 0.9999 per-sample literal
HR_MIN_BPM, HR_MAX_BPM = 40.0, 260.0
WARMUP_S = 5.0

# TERMA windows, from Elgendi (PLOS One 2013). The published design rule is 2*W1 <= W2 <= 8*W1;
# 667/111 = 6.0 sits inside it. Tuned for adult PPG, which is what these captures are.
TERMA_W1_S, TERMA_W2_S, TERMA_BETA = 0.111, 0.667, 0.02
SSF_WINDOW_S = 0.128           # Zong's slope-sum window


# ── shared preprocessing ─────────────────────────────────────────────────────
def preprocess(x, fs=FS_HZ):
    """DC removal + negate (peaks up) + 2nd-order Butterworth low-pass — HR1's own front end."""
    alpha = math.exp(-1.0 / (HR1_DC_TAU_S * fs))
    dc = 0.0
    y = np.empty_like(x)
    for i, v in enumerate(x):
        dc = alpha * dc + (1.0 - alpha) * v
        y[i] = -(v - dc)
    ohm = math.tan(math.pi * HR1_LP_CUTOFF_HZ / fs)
    ohm2, sq2 = ohm * ohm, math.sqrt(2.0)
    d = 1.0 + sq2 * ohm + ohm2
    b0, b1, b2 = ohm2 / d, 2.0 * ohm2 / d, ohm2 / d
    a1, a2 = 2.0 * (ohm2 - 1.0) / d, (1.0 - sq2 * ohm + ohm2) / d
    v1 = v2 = 0.0
    out = np.empty_like(y)
    for i, v in enumerate(y):
        o = b0 * v + v1
        v1 = b1 * v - a1 * o + v2
        v2 = b2 * v - a2 * o
        out[i] = o
    return out


def moving_avg(x, n):
    """Centred moving average of window n, via cumulative sum."""
    n = max(1, int(n))
    c = np.concatenate(([0.0], np.cumsum(x)))
    out = np.empty_like(x)
    half = n // 2
    for i in range(len(x)):
        lo, hi = max(0, i - half), min(len(x), i - half + n)
        out[i] = (c[hi] - c[lo]) / float(hi - lo)
    return out


def apply_refractory(cands, fs=FS_HZ, warmup_s=WARMUP_S):
    """Common guard: drop a candidate that falls inside the refractory of the previous accepted
    beat, and discard everything inside the warmup (the running max needs seconds to converge)."""
    refr = int(HR1_REFRACTORY_S * fs)
    warm = int(warmup_s * fs)
    out, last = [], None
    for i in cands:
        if last is not None and (i - last) <= refr:
            continue
        last = i
        if i >= warm:
            out.append(i)
    return np.array(out, dtype=int)


# ── detector 1: current ──────────────────────────────────────────────────────
def detect_current(ppg, fs=FS_HZ):
    decay = math.exp(-1.0 / (HR1_MAX_DECAY_TAU_S * fs))
    running_max, above = 0.0, False
    cands = []
    for i, v in enumerate(ppg):
        running_max = max(running_max * decay, v)
        thr = HR1_THRESH_FRAC * running_max
        if v > thr and not above:
            above = True
            cands.append(i)
        elif v <= thr:
            above = False
    return apply_refractory(cands, fs)


# ── detector 2: SSF (Zong) ───────────────────────────────────────────────────
def detect_ssf(ppg, fs=FS_HZ):
    """Slope sum: at each sample, the sum of positive slopes over the preceding window. Same
    decision rule as CURRENT so the comparison isolates the enhancement, not the criterion."""
    dy = np.diff(ppg, prepend=ppg[0])
    pos = np.maximum(dy, 0.0)
    w = max(1, int(SSF_WINDOW_S * fs))
    c = np.concatenate(([0.0], np.cumsum(pos)))
    ssf = np.empty_like(ppg)
    for i in range(len(ppg)):
        lo = max(0, i - w + 1)
        ssf[i] = c[i + 1] - c[lo]
    return detect_current(ssf, fs)


# ── detector 3: TERMA (Elgendi) ──────────────────────────────────────────────
def detect_terma(ppg, fs=FS_HZ):
    """Two event-related moving averages over the squared signal generate blocks of interest;
    the peak is the maximum inside each block wide enough to be a beat."""
    clipped = np.maximum(ppg, 0.0)          # only the systolic rise matters
    sq = clipped * clipped
    ma_peak = moving_avg(sq, TERMA_W1_S * fs)
    ma_beat = moving_avg(sq, TERMA_W2_S * fs)
    thr = ma_beat + TERMA_BETA * float(np.mean(sq))   # offset threshold

    w1 = int(TERMA_W1_S * fs)
    cands, start = [], None
    for i in range(len(sq)):
        if ma_peak[i] > thr[i]:
            if start is None:
                start = i
        else:
            if start is not None:
                if (i - start) >= w1:            # blocks narrower than a peak are noise
                    seg = ppg[start:i]
                    if len(seg):
                        cands.append(start + int(np.argmax(seg)))
                start = None
    if start is not None and (len(sq) - start) >= w1:
        seg = ppg[start:]
        if len(seg):
            cands.append(start + int(np.argmax(seg)))
    return apply_refractory(cands, fs)


# ── metrics ──────────────────────────────────────────────────────────────────
def stats(beats, fs=FS_HZ):
    if len(beats) < 3:
        return None
    rr = np.diff(beats) / fs * 1000.0
    lo, hi = 60000.0 / HR_MAX_BPM, 60000.0 / HR_MIN_BPM
    good = rr[(rr >= lo) & (rr <= hi)]
    if len(good) < 2:
        return None
    mean = float(np.mean(good))
    return dict(n=len(beats), bpm=60000.0 / mean, sd=float(np.std(good, ddof=1)),
                cv=100.0 * float(np.std(good, ddof=1)) / mean, rejected=len(rr) - len(good))


def load(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        rows = [ln for ln in fh if not ln.startswith("#") and ln.strip()]
    if not rows:
        return None, None
    hdr = [c.strip() for c in rows[0].split(",")]
    if "LED1_SUB" not in hdr:
        return None, None
    i_sig = hdr.index("LED1_SUB")
    i_hr = hdr.index("FW_HR1") if "FW_HR1" in hdr else None
    sig, fw = [], []
    for ln in rows[1:]:
        p = ln.split(",")
        if len(p) <= i_sig:
            continue
        try:
            sig.append(float(p[i_sig]))
            if i_hr is not None and len(p) > i_hr:
                v = float(p[i_hr])
                if v > 0:
                    fw.append(v)
        except ValueError:
            continue
    if len(sig) < int(10 * FS_HZ):
        return None, None
    return np.asarray(sig, float), (float(np.median(fw)) if fw else None)


def truth_bpm(path):
    """Simulator captures name their rate: ..._60BPM_... . Finger captures have no ground truth."""
    name = os.path.basename(path).upper()
    for tok in name.replace("-", "_").split("_"):
        if tok.endswith("BPM") and tok[:-3].isdigit():
            return float(tok[:-3])
    return None


def run(path):
    sig, fw = load(path)
    if sig is None:
        return
    truth = truth_bpm(path)
    ppg = preprocess(sig)
    print(f"\n  {os.path.basename(path)}   ({len(sig)/FS_HZ:.0f} s"
          + (f", true rate {truth:.0f} BPM" if truth else "")
          + (f", firmware HR1 {fw:.1f} BPM" if fw else "") + ")")
    print(f"    {'detector':<9} {'beats':>6} {'BPM':>7} {'err':>8} {'RR SD':>8} {'CV':>7} {'rej':>4}")
    for name, fn in (("current", detect_current), ("SSF", detect_ssf), ("TERMA", detect_terma)):
        st = stats(fn(ppg))
        if not st:
            print(f"    {name:<9} {'--- too few beats ---':>40}")
            continue
        err = f"{st['bpm']-truth:+7.1f}" if truth else "      -"
        print(f"    {name:<9} {st['n']:>6} {st['bpm']:>7.1f} {err:>8} "
              f"{st['sd']:>7.1f}ms {st['cv']:>6.2f}% {st['rejected']:>4}")


DEFAULTS = [
    "captures/PHOTOTHERAPY_500HZ_SIMUL_60BPM_96SPO2_20260624_083336.csv",
    "captures/PHOTOTHERAPY_ONOFF_60BPM_90SPO2_20260618_180045.csv",
    "captures/PHOTOTHERAPY_400HZ_SIMUL_60BPM_96SPO2_20260624_083632.csv",
    "captures/ALEX_CUESTA_57_RF100K_20260823_184201.csv",
    "captures/ALEX_CUESTA_57_RF250k_20260823_184045.csv",
    "captures/IKER_CUESTA_19_AL_REVES_20260823_180835.csv",
    "captures/LEO_CUESTA_15_20260823_175947.csv",
]

if __name__ == "__main__":
    paths = sys.argv[1:] or [p for p in DEFAULTS if os.path.exists(p)]
    if not paths:
        sys.exit("No captures found.")
    print("HR1 detector comparison — current threshold vs SSF (Zong) vs TERMA (Elgendi)")
    print(f"shared front end: DC removal (tau {HR1_DC_TAU_S} s) + Butterworth LP "
          f"{HR1_LP_CUTOFF_HZ:.0f} Hz; refractory {HR1_REFRACTORY_S*1000:.0f} ms; "
          f"warmup {WARMUP_S:.0f} s")
    for p in paths:
        run(p)
