"""Compare HR1's moving average against a Butterworth biquad, on recorded captures.

Usage:  python tools/hr1_filter_experiment.py [capture.csv ...]
        (no arguments: runs the default set from captures/)

WHY THIS EXISTS
HR1 low-passes with a moving average before its threshold detector. The conversation log shows
that choice was not made on filtering grounds: when HR1 got its own filter, the library's biquad
still had hardcoded coefficients copied from Protocentral and could not follow the sample rate
(resolved in v0.6 by the bilinear transform). The moving average was simply the only filter that
adapted. Nobody revisited it in the ~80 versions since.

The open question is whether the moving average's one real advantage — LINEAR PHASE, which delays
the pulse without deforming it — outweighs its poor out-of-band rejection (first sidelobe at only
-13 dB, versus 40 dB/decade monotonic for a 2nd-order Butterworth). A biquad's phase distortion
shifts the detected edge in a frequency-dependent way, and that shows up as beat-to-beat jitter,
i.e. as artificial heart-rate variability.

WHAT IS MEASURED
Both arms share the DC removal and the detector, so any difference is attributable to the filter:

    LED1_SUB -> IIR DC removal -> [ moving average | biquad LP ] -> threshold detector -> RR

  * beats detected      — a filter too wide lets the dicrotic notch cross the threshold, which
                          shows up as extra detections (a doubled HR)
  * RR mean / SD / CV   — the jitter the filter introduces
  * max |RR deviation|  — worst single-interval error, the one an alarm would react to

LIMITATIONS (see the session log): the captures are adults and a simulator, not neonates, whose
dicrotic notch is sharper and closer to the systolic peak; the detector here is a mirror of the
firmware, not the firmware itself, so absolute HR will not match FW_HR1 exactly; and the
finger captures are ~20 s (~20 beats), enough to expose double-counting but thin for jitter
statistics — the phototherapy capture (~80 s) carries more weight there.
"""
import sys
import math
import glob
import os

import numpy as np

# ── Firmware constants (incunest_afe4490.cpp, v0.86b) ────────────────────────
FS_HZ            = 500.0
HR1_DC_TAU_S     = 1.6      # _hr1_dc_tau_s
HR1_MA_CUTOFF_HZ = 5.0      # hr1_ma_cutoff_hz
# Refractory period: blind window after an accepted beat, during which further threshold
# crossings are ignored, so the dicrotic notch is not counted as a second beat. Fixed here,
# which under-protects bradycardia — see incunest_afe4490.cpp for the full reasoning.
HR1_REFRACTORY_S = 0.185    # hr1_refractory_s
HR1_THRESH_FRAC  = 0.6      # threshold = 0.6 * running_max
HR1_MAX_DECAY    = 0.9999   # running_max decay per sample
HR_MIN_BPM       = 40.0
HR_MAX_BPM       = 260.0


def dc_remove(x, fs=FS_HZ, tau_s=HR1_DC_TAU_S):
    """IIR DC estimator then negate, exactly as _hr1_update() does."""
    alpha = math.exp(-1.0 / (tau_s * fs))
    dc, out = 0.0, np.empty_like(x)
    for i, v in enumerate(x):
        dc = alpha * dc + (1.0 - alpha) * v
        out[i] = -(v - dc)
    return out


def moving_average(x, fs=FS_HZ, cutoff_hz=HR1_MA_CUTOFF_HZ):
    """The current filter. N = round(fs / (2*cutoff)), incremental running sum."""
    n = max(1, int(round(fs / (2.0 * cutoff_hz))))
    csum = np.concatenate(([0.0], np.cumsum(x)))
    out = np.empty_like(x)
    for i in range(len(x)):
        lo = max(0, i - n + 1)
        out[i] = (csum[i + 1] - csum[lo]) / float(i - lo + 1)
    return out, n


def biquad_lp(x, fs=FS_HZ, cutoff_hz=HR1_MA_CUTOFF_HZ):
    """2nd-order Butterworth low-pass, bilinear transform — the SAME algebra as
    BiquadFilter::init_lp() in the library, so this is what would actually ship."""
    ohm = math.tan(math.pi * cutoff_hz / fs)
    ohm2 = ohm * ohm
    sq2 = math.sqrt(2.0)
    d = 1.0 + sq2 * ohm + ohm2
    b0 = ohm2 / d
    b1 = 2.0 * b0
    b2 = b0
    a1 = 2.0 * (ohm2 - 1.0) / d
    a2 = (1.0 - sq2 * ohm + ohm2) / d
    # Direct Form II transposed, as in BiquadFilter::process()
    v1 = v2 = 0.0
    out = np.empty_like(x)
    for i, v in enumerate(x):
        y = b0 * v + v1
        v1 = b1 * v - a1 * y + v2
        v2 = b2 * v - a2 * y
        out[i] = y
    return out


# The running max starts at zero and climbs with signal amplitude, so the threshold is far too
# low for the first seconds and the detector both misses and mis-times beats. The firmware does
# not care (it has been running for minutes), but a replay from sample 0 does. Beats inside this
# window are discarded rather than counted as jitter.
DETECTOR_WARMUP_S = 5.0


def detect_beats(ppg, fs=FS_HZ, warmup_s=DETECTOR_WARMUP_S):
    """Mirror of HR1's detector: rising-edge crossing of 0.6 * decaying running max,
    gated by the refractory period. Returns the sample indices of accepted beats."""
    refractory = int(HR1_REFRACTORY_S * fs)
    warmup = int(warmup_s * fs)
    running_max, above, last_idx = 0.0, False, None
    beats = []
    for i, v in enumerate(ppg):
        running_max = max(running_max * HR1_MAX_DECAY, v)
        thr = HR1_THRESH_FRAC * running_max
        if v > thr and not above:
            above = True
            if last_idx is None or (i - last_idx) > refractory:
                if i >= warmup:
                    beats.append(i)
                last_idx = i
        elif v <= thr:
            above = False
    return np.array(beats)


# HR1's quality gate: over a sliding window of 5 intervals, the rate is published only while
# their coefficient of variation stays under hr1_sqi_cv_max. It does not fix a bad detection - it
# discards the stretch containing it, at the cost of availability.
HR1_SQI_CV_MAX = 0.15
HR1_SQI_N_INTERVALS = 5


def sqi_accepted(beats, fs=FS_HZ):
    """Intervals (ms) that survive HR1's SQI gate."""
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


def truth_bpm(path):
    """Known rate from the filename: 60BPM (older captures) or 100HR (MS100 series)."""
    name = os.path.basename(path).upper().replace("-", "_")
    for tok in name.split("_"):
        if tok.endswith("BPM") and tok[:-3].isdigit():
            return float(tok[:-3])
        if tok.endswith("HR") and tok[:-2].isdigit():
            return float(tok[:-2])
    return None


def rr_stats(beats, fs=FS_HZ):
    """RR intervals in ms, plus the jitter figures. Only intervals inside the accepted HR
    range count — an interval outside it is a detection failure, not jitter."""
    if len(beats) < 3:
        return None
    rr_ms = np.diff(beats) / fs * 1000.0
    lo, hi = 60000.0 / HR_MAX_BPM, 60000.0 / HR_MIN_BPM
    valid = rr_ms[(rr_ms >= lo) & (rr_ms <= hi)]
    if len(valid) < 2:
        return None
    mean = float(np.mean(valid))
    sd = float(np.std(valid, ddof=1))
    return dict(n_beats=len(beats), n_valid=len(valid), mean_ms=mean, sd_ms=sd,
                cv_pct=100.0 * sd / mean, bpm=60000.0 / mean,
                max_dev_ms=float(np.max(np.abs(valid - mean))),
                n_out_of_range=len(rr_ms) - len(valid))


def paired_shift(beats_a, beats_b, fs=FS_HZ, tol_ms=120.0):
    """THE measurement that isolates the filter.

    Comparing each arm's RR spread is comparing noise with noise: an SD of 25-29 ms on a resting
    adult finger is physiological HRV, present identically in both arms, and it swamps whatever
    the filter contributes. Pairing the beats removes it — the same cardiac event seen through two
    filters — so what is left is purely the filters' difference:

      * mean shift — the differential GROUP DELAY. Systematic and harmless: it delays every beat
        equally, so RR intervals, and therefore HR, are unaffected.
      * SD of the shift — the differential JITTER. This is the figure that matters: it is the
        beat-to-beat timing noise the biquad's non-linear phase would add over the moving
        average's linear phase, and it lands straight in the reported HR.
    """
    tol = tol_ms * fs / 1000.0
    shifts = []
    for ba in beats_a:
        if len(beats_b) == 0:
            break
        j = int(np.argmin(np.abs(beats_b - ba)))
        d = beats_b[j] - ba
        if abs(d) <= tol:
            shifts.append(d / fs * 1000.0)
    if len(shifts) < 3:
        return None
    sh = np.asarray(shifts)
    return dict(n=len(sh), mean_ms=float(np.mean(sh)), sd_ms=float(np.std(sh, ddof=1)),
                max_ms=float(np.max(np.abs(sh))))


def load_capture(path):
    """Returns (LED1_SUB, FW_HR1 median) from a lab CSV. '#' lines are the config header."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        rows = [ln for ln in fh if not ln.startswith("#") and ln.strip()]
    if not rows:
        return None, None
    header = [c.strip() for c in rows[0].split(",")]
    try:
        i_sig = header.index("LED1_SUB")
    except ValueError:
        return None, None
    i_hr = header.index("FW_HR1") if "FW_HR1" in header else None
    sig, fw = [], []
    for ln in rows[1:]:
        parts = ln.split(",")
        if len(parts) <= i_sig:
            continue
        try:
            sig.append(float(parts[i_sig]))
            if i_hr is not None and len(parts) > i_hr:
                v = float(parts[i_hr])
                if v > 0:
                    fw.append(v)
        except ValueError:
            continue
    if len(sig) < int(5 * FS_HZ):
        return None, None
    return np.asarray(sig, dtype=float), (float(np.median(fw)) if fw else None)


def run(path):
    sig, fw_hr = load_capture(path)
    if sig is None:
        print(f"  {os.path.basename(path):<52} (skipped: no usable LED1_SUB)")
        return
    base = dc_remove(sig)
    ma, n_ma = moving_average(base)
    bq = biquad_lp(base)

    b_ma, b_bq = detect_beats(ma), detect_beats(bq)
    s_ma, s_bq = rr_stats(b_ma), rr_stats(b_bq)
    dur = len(sig) / FS_HZ
    analysed = max(0.0, dur - DETECTOR_WARMUP_S)
    print(f"\n  {os.path.basename(path)}")
    print(f"    {dur:.0f} s ({analysed:.0f} s analysed after warmup), MA length {n_ma} samples"
          + (f", firmware HR1 median {fw_hr:.1f} BPM" if fw_hr else ""))
    if not s_ma or not s_bq:
        print("    not enough beats detected to compare")
        return
    truth = truth_bpm(path)
    print(f"    {'':<8} {'beats':>6} {'BPM':>7} {'err':>7} {'CV':>7} | {'BPM_sqi':>7} {'err':>7} {'kept':>5}")
    for name, st, beats in (("MA", s_ma, b_ma), ("biquad", s_bq, b_bq)):
        err = f"{st['bpm']-truth:+6.1f}" if truth else "     -"
        good = sqi_accepted(beats)
        if len(good) >= 2:
            bpm_q = 60000.0 / float(np.mean(good))
            err_q = f"{bpm_q-truth:+6.1f}" if truth else "     -"
            kept = 100.0 * len(good) / max(1, len(beats) - 1)
            gated = f"{bpm_q:>7.1f} {err_q:>7} {kept:>4.0f}%"
        else:
            gated = f"{'--':>7} {'--':>7} {0:>4.0f}%"
        print(f"    {name:<8} {st['n_beats']:>6} {st['bpm']:>7.1f} {err:>7} "
              f"{st['cv_pct']:>6.2f}% | {gated}")
    dbeats = s_bq['n_beats'] - s_ma['n_beats']
    ps = paired_shift(b_ma, b_bq)
    if ps:
        print(f"    paired on {ps['n']} beats: group delay {ps['mean_ms']:+.1f} ms "
              f"(systematic, does not affect RR), differential jitter SD {ps['sd_ms']:.1f} ms, "
              f"worst {ps['max_ms']:.1f} ms")
    if dbeats:
        print(f"    -> biquad detects {abs(dbeats)} {'more' if dbeats > 0 else 'fewer'} beats")


# Shared with hr1_detector_experiment.py through the capture manifest instead of being
# duplicated here — and without subject names, which this list used to carry into a public
# repository. See tools/capture_set.py.
from capture_set import hr1_experiment_captures

if __name__ == "__main__":
    paths = sys.argv[1:] or hr1_experiment_captures()
    if not paths:
        sys.exit("No captures found. Pass paths explicitly.")
    print(f"HR1 filter comparison — moving average vs 2nd-order Butterworth, cutoff "
          f"{HR1_MA_CUTOFF_HZ:.0f} Hz at {FS_HZ:.0f} Hz")
    for p in paths:
        for match in sorted(glob.glob(p)) or [p]:
            run(match)
