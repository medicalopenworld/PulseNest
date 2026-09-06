"""Sweep HR1's running-max decay over the MS100 captures, in both parameterisations.

Why this exists
---------------
`hr1_max_decay_tau_s` has no rationale of its own: the library's spec states the 20 s default
"reproduces 0.9999 exactly at 500 Hz, so default behaviour is unchanged" — it is the inherited
per-sample literal in seconds. This sweep replaces that with a measured, defensible value.

What it measures, and why not availability alone
------------------------------------------------
A short tau lets the threshold collapse between beats, and the detector can then latch onto
noise fairly regularly: high availability with an invented heart rate, indistinguishable from
success unless the truth is known. Inventing beats is the dangerous failure — it raises HR and
masks a real bradycardia, the event that justifies the monitor. So the metric is availability
CONDITIONED on being right:

    good = fraction of samples with SQI > 0 AND |HR - truth| <= 3 BPM      (the ISO limit)

Reported alongside it: raw availability (SQI > 0, what HR1LAB shows live) and the mean HR error
while publishing. Where `avail` is high and `good` is low, the detector is confidently wrong.

Selection rule
--------------
Not the maximum of the metric: the LARGEST tau that meets the requirement across the whole
40-250 BPM range. A larger tau means a more stable threshold and less risk of inventing beats,
so the defensible number is the most conservative one that satisfies the requirement, with the
widest margin — not the winner of a contest.

The first WARMUP_S seconds of every capture are dropped: SPEC's one-pole DC remover needs
4-5 tau (~7 s) to settle, and scoring that would penalise the filter, not the decay.

What this needs, and what the MS100 set cannot give it (measured 2026-09-06)
--------------------------------------------------------------------------
First run over the 11 MS100 captures: **the decay does not discriminate at all**. From 55 to
250 BPM every configuration from tau=1 s to tau=20 s scores 96-100 % (100 % for BPF), and the
40 BPM capture scores 18-36 % for all of them with no monotonic trend — that spread is noise
over ~33 beats, not a signal.

The reason is the material, not the parameter: the MS100 is a simulator, so its signal is clean
and has no baseline wander. Tau governs RECOVERY from amplitude changes, and a recording with no
amplitude changes cannot separate one tau from another. Measuring a parameter on material that
does not contain the phenomenon it governs produces a confident non-answer.

What does discriminate: a capture with the truth known AND the phenomenon present — record the
MS100 (which fixes the true rate) while deliberately disturbing the probe, so baseline wander and
amplitude steps are in the signal. Name it per CAPTURE_SET_SPEC.md §2.4 (rate token ending in BPM)
and this script picks it up.

Separately, the 40 BPM capture is not limited by the decay at all: `good == avail` and the
published HR is 40.0 exactly (median, p5 and p95). It publishes only ~27 % of the time because at
a low rate one missed beat poisons the 5-interval RR buffer, and 5 beats at 40 BPM is 7.5 s of
silence. That belongs to `hr1_sqi_cv_max` and the RR buffer length, not to tau.

Usage:  python tools/hr1_decay_sweep.py [--quick]
"""

import argparse
import math
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pulsenest_lab as P   # noqa: E402

CAPTURES   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
WARMUP_S   = 10.0
HR_TOL_BPM = 3.0            # ISO 80601-2-61 accuracy limit

# Truth rate in the filename. CAPTURE_SET_SPEC.md §2.4 specifies a token ending in BPM
# ("T1_SIM_PHOTOTHERAPY_60BPM_96SPO2_..."); the earlier MS100 files use <N>HR. Accept both.
TRUTH_RE   = r"_(\d+)(?:BPM|HR)_"

TAU_GRID   = (1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 20.0)
BEAT_GRID  = (2.0, 3.0, 5.0, 8.0, 13.0)


def load_capture(path):
    """-> (ot_led1, probe_state, fs, truth_bpm) from a lab capture CSV."""
    truth = re.search(TRUTH_RE, os.path.basename(path))
    if not truth:
        return None
    header, rows = None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split(",")
            if header is None:
                header = parts
                continue
            rows.append(parts)
    if header is None or not rows:
        return None
    try:
        i_ot = header.index("FW_OT_LED1")
        i_ps = header.index("FW_ProbeState")
        i_ts = header.index("FW_Ts_us")
    except ValueError:
        return None

    ot, ps, ts = [], [], []
    for r in rows:
        if len(r) <= max(i_ot, i_ps, i_ts):
            continue
        try:
            ot.append(float(r[i_ot]))
            ps.append(int(float(r[i_ps])))
            ts.append(float(r[i_ts]))
        except ValueError:
            continue
    if len(ot) < 1000:
        return None

    d = np.diff(np.array(ts))
    d = d[d > 0]
    fs = float(1e6 / np.median(d)) if len(d) else 500.0
    for std in (500, 1000, 800, 1250, 1600, 250, 100, 50):
        if abs(fs - std) < std * 0.2:
            fs = float(std)
            break
    return np.array(ot), np.array(ps), fs, float(truth.group(1))


def score(cls, params, ot, ps, fs, truth):
    """-> (good, avail, mean_abs_err) over the samples after warm-up."""
    c = cls()
    for k, v in params.items():
        setattr(c, k, v)
    c.reset()
    skip = int(WARMUP_S * fs)
    n_scored = good = avail = 0
    err_sum = 0.0
    for i in range(len(ot)):
        c.update(float(ot[i]), fs, int(ps[i]), None)
        if i < skip or ps[i] != c.PROBE_APPLIED:
            continue
        n_scored += 1
        if c.hr_sqi > 0.0:
            avail += 1
            err = abs(c.hr_bpm - truth)
            err_sum += err
            if err <= HR_TOL_BPM:
                good += 1
    if n_scored == 0:
        return float("nan"), float("nan"), float("nan")
    return (good / n_scored, avail / n_scored,
            (err_sum / avail) if avail else float("nan"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="Coarse grid and 30 s per capture — for a first look")
    args = ap.parse_args()

    tau_grid  = (2.0, 5.0, 20.0) if args.quick else TAU_GRID
    beat_grid = (3.0, 5.0) if args.quick else BEAT_GRID

    # Any lab capture whose name declares the truth rate qualifies, not just the MS100
    # set — see the "What this needs" note at the top of the file.
    paths = sorted(os.path.join(CAPTURES, f) for f in os.listdir(CAPTURES)
                   if f.endswith(".csv") and re.search(TRUTH_RE, f))
    caps = []
    for p in paths:
        c = load_capture(p)
        if c is None:
            print("  (saltada, formato inesperado) %s" % os.path.basename(p))
            continue
        ot, ps, fs, truth = c
        if args.quick:
            keep = int((WARMUP_S + 30.0) * fs)
            ot, ps = ot[:keep], ps[:keep]
        caps.append((os.path.basename(p), ot, ps, fs, truth))
    caps.sort(key=lambda t: t[4])
    print("%d capturas, verdad %d-%d BPM, warm-up %.0f s, tolerancia +-%.0f BPM\n"
          % (len(caps), caps[0][4], caps[-1][4], WARMUP_S, HR_TOL_BPM))

    configs = ([("tau %4.1f s" % t, {"max_decay_tau_s": t}) for t in tau_grid]
               + [("N %4.1f beats" % n, {"max_decay_beats": n}) for n in beat_grid])

    for variant in (P.HR1TestCalc, P.HR1BiquadCalc):
        print("=" * 78)
        print("VARIANTE %s — %s" % (variant.NAME, variant.DESCRIPTION))
        print("=" * 78)
        hdr = "%-14s" % "config" + "".join("%7d" % c[4] for c in caps) + "%9s" % "peor"
        print(hdr)
        best = []
        for label, params in configs:
            t0 = time.time()
            goods = []
            for _, ot, ps, fs, truth in caps:
                g, _, _ = score(variant, params, ot, ps, fs, truth)
                goods.append(g)
            worst = min(goods)
            best.append((worst, label, params))
            print("%-14s" % label
                  + "".join("%6.0f%%" % (100 * g) for g in goods)
                  + "%8.0f%%" % (100 * worst)
                  + "   (%.0fs)" % (time.time() - t0))

        # Selection: the most conservative config that clears the bar
        for bar in (0.90, 0.75, 0.50):
            ok = [b for b in best if b[0] >= bar]
            if ok:
                # most conservative = longest memory among those that qualify
                pick = max(ok, key=lambda b: b[2].get("max_decay_tau_s",
                                                      b[2].get("max_decay_beats", 0)))
                print("\n  Umbral %.0f%% en TODAS las capturas -> %d configs lo cumplen."
                      % (100 * bar, len(ok)))
                print("  Mas conservadora de ellas: %s (peor caso %.0f%%)"
                      % (pick[1], 100 * pick[0]))
                break
        else:
            print("\n  Ninguna config alcanza el 50%% en todas las capturas.")
        print()


if __name__ == "__main__":
    main()
