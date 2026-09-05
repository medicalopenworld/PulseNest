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
# Refractory period: blind window after an accepted beat, during which further threshold
# crossings are ignored, so the dicrotic notch is not counted as a second beat. Fixed here,
# which under-protects bradycardia — see incunest_afe4490.cpp for the full reasoning.
HR1_REFRACTORY_S = 0.185
HR1_THRESH_FRAC  = 0.6
HR1_MAX_DECAY_TAU_S = 20.0     # v0.87: was a 0.9999 per-sample literal
HR_MIN_BPM, HR_MAX_BPM = 40.0, 260.0
WARMUP_S = 5.0

# TERMA windows, from Elgendi (PLOS One 2013). The published design rule is 2*W1 <= W2 <= 8*W1;
# 667/111 = 6.0 sits inside it. Tuned for adult PPG, which is what these captures are.
TERMA_W1_S, TERMA_W2_S, TERMA_BETA = 0.111, 0.667, 0.02
SSF_WINDOW_S = 0.128           # Zong's slope-sum window
SSF_LEVEL_WINDOW_S = 3.0       # local level for SSF's own threshold (~3 beats at 60 BPM)
SSF_THRESH_FACTOR  = 2.0       # threshold = factor x local SSF level
TERMA_LEVEL_WINDOW_S = 3.0     # window for TERMA's offset mean (was the whole capture)

# HR1's own quality gate, applied downstream of every detector below. The firmware reports a
# steady 60.0 BPM where all three detectors show CV 12-33 %, which means the published HR is not
# the raw detector output: hr1_sqi_cv_max discards stretches whose 5-interval CV is too high.
# Comparing detectors without it measures half the chain.
HR1_SQI_CV_MAX = 0.15
HR1_SQI_N_INTERVALS = 5


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
def slope_sum(ppg, fs=FS_HZ):
    """Sum of positive slopes over the preceding window: amplifies the systolic upstroke and
    flattens everything else."""
    dy = np.diff(ppg, prepend=ppg[0])
    pos = np.maximum(dy, 0.0)
    w = max(1, int(SSF_WINDOW_S * fs))
    c = np.concatenate(([0.0], np.cumsum(pos)))
    out = np.empty_like(ppg)
    for i in range(len(ppg)):
        out[i] = c[i + 1] - c[max(0, i - w + 1)]
    return out


def detect_ssf(ppg, fs=FS_HZ):
    """SSF with its OWN adaptive threshold.

    First pass used HR1's running max (tau = 20 s) to isolate the enhancement. That was the wrong
    call: with 20 s of memory a loud stretch leaves the threshold inflated for half a minute, and
    on PHOTOTHERAPY_ONOFF - where the lamp switches and the amplitude steps - SSF stopped detecting
    entirely. Zong's threshold is short-memory and tracks the local level, which is half of what
    the method is; wrapping it in someone else's criterion measured the wrapper, not the method."""
    ssf = slope_sum(ppg, fs)
    # Local level: mean of SSF over a few beats, so the threshold follows amplitude steps.
    level = moving_avg(ssf, SSF_LEVEL_WINDOW_S * fs)
    thr = SSF_THRESH_FACTOR * level
    cands, above = [], False
    for i, v in enumerate(ssf):
        if v > thr[i] and not above:
            above = True
            cands.append(i)
        elif v <= thr[i]:
            above = False
    # The SSF peak sits on the upstroke; report the signal maximum just after it.
    w = int(0.15 * fs)
    peaks = []
    for i in cands:
        seg = ppg[i:min(len(ppg), i + w)]
        peaks.append(i + int(np.argmax(seg)) if len(seg) else i)
    return apply_refractory(peaks, fs)


# ── detector 3: TERMA (Elgendi) ──────────────────────────────────────────────
def detect_terma(ppg, fs=FS_HZ):
    """Two event-related moving averages over the squared signal generate blocks of interest;
    the peak is the maximum inside each block wide enough to be a beat."""
    clipped = np.maximum(ppg, 0.0)          # only the systolic rise matters
    sq = clipped * clipped
    ma_peak = moving_avg(sq, TERMA_W1_S * fs)
    ma_beat = moving_avg(sq, TERMA_W2_S * fs)
    # Offset from a LOCAL mean, not the mean of the whole capture. The first pass used a global
    # mean; on PHOTOTHERAPY_ONOFF, where the lamp switches and the amplitude changes completely
    # between stretches, no stretch resembles that global figure and the detector found 99 beats
    # where ~89 fit. Elgendi computes the offset over the local window.
    local_mean = moving_avg(sq, TERMA_LEVEL_WINDOW_S * fs)
    thr = ma_beat + TERMA_BETA * local_mean

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


# ── HR1's quality gate ───────────────────────────────────────────────────────
def sqi_accepted(beats, fs=FS_HZ):
    """Mirror of HR1's SQI: over a sliding window of 5 intervals, accept the rate only while the
    coefficient of variation stays under hr1_sqi_cv_max. Returns the accepted intervals in ms."""
    if len(beats) < HR1_SQI_N_INTERVALS + 1:
        return np.array([])
    rr = np.diff(beats) / fs * 1000.0
    good = []
    for i in range(HR1_SQI_N_INTERVALS - 1, len(rr)):
        win = rr[i - HR1_SQI_N_INTERVALS + 1:i + 1]
        m = float(np.mean(win))
        if m > 0 and float(np.std(win, ddof=1)) / m <= HR1_SQI_CV_MAX:
            good.append(rr[i])
    return np.array(good)


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
        # Two conventions in the wild: the older PHOTOTHERAPY files say 60BPM, the MS100 series
        # says 100HR. Neither is authoritative - CAPTURE_SET_SPEC 2.5 makes truth.csv the record -
        # but truth_hr_bpm is still blank for the MS100 series, so the filename is what there is.
        if tok.endswith("BPM") and tok[:-3].isdigit():
            return float(tok[:-3])
        if tok.endswith("HR") and tok[:-2].isdigit():
            return float(tok[:-2])
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
    print(f"    {'detector':<9} {'beats':>6} {'BPM':>7} {'err':>8} {'RR SD':>8} {'CV':>7} {'rej':>4}"
          f" | {'BPM_sqi':>7} {'err':>8} {'kept':>5}")
    for name, fn in (("current", detect_current), ("SSF", detect_ssf), ("TERMA", detect_terma)):
        beats = fn(ppg)
        st = stats(beats)
        if not st:
            print(f"    {name:<9} {'--- too few beats ---':>40}")
            continue
        err = f"{st['bpm']-truth:+7.1f}" if truth else "      -"
        # With HR1's SQI gate: what the firmware would actually publish.
        good = sqi_accepted(beats)
        if len(good) >= 2:
            bpm_q = 60000.0 / float(np.mean(good))
            err_q = f"{bpm_q-truth:+7.1f}" if truth else "      -"
            frac = 100.0 * len(good) / max(1, len(beats) - 1)
        else:
            bpm_q, err_q, frac = float('nan'), "      -", 0.0
        print(f"    {name:<9} {st['n']:>6} {st['bpm']:>7.1f} {err:>8} "
              f"{st['sd']:>7.1f}ms {st['cv']:>6.2f}% {st['rejected']:>4} "
              f"| {bpm_q:>7.1f} {err_q:>8} {frac:>5.0f}%")


# The default working set comes from the capture manifest, not from a list of paths written
# here: the same list used to be duplicated in hr1_filter_experiment.py, and it carried
# subject names and ages into a public repository. See tools/capture_set.py.
from capture_set import hr1_experiment_captures

if __name__ == "__main__":
    paths = sys.argv[1:] or hr1_experiment_captures()
    if not paths:
        sys.exit("No captures found.")
    print("HR1 detector comparison — current threshold vs SSF (Zong) vs TERMA (Elgendi)")
    print(f"shared front end: DC removal (tau {HR1_DC_TAU_S} s) + Butterworth LP "
          f"{HR1_LP_CUTOFF_HZ:.0f} Hz; refractory {HR1_REFRACTORY_S*1000:.0f} ms; "
          f"warmup {WARMUP_S:.0f} s")
    for p in paths:
        run(p)
