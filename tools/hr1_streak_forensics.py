"""Forensics for HR1's SQI=0 streaks on a real-probe capture.

Why this exists
---------------
Bench session 2026-09-15, three IDF boards recording the same subject at ~52 bpm for 30 s on
clean signal (ProbeState APPLIED, DiagCode 0, RSQI 1): `FW_HR1` went to -1 for ONE ~5.8 s run on
two of the three boards, at different instants, while HR2 and HR3 kept publishing without a
flinch. 5.8 s is 5 RR intervals at 52 bpm — the length of the RR buffer — which points at a
single anomalous interval rather than a bad stretch of signal.

What it does
------------
1. Replays the SPEC variant (`pulsenest_lab.HR1TestCalc`) over the captured OT_LED1 and compares
   its SQI=0 streaks against the firmware's, sample by sample. On V17 the replay reproduces the
   firmware's streak to within a sample, which is what licenses reading its internals.
2. Establishes ground-truth beats independently (find_peaks on the same filtered waveform,
   0.7 s minimum distance — RR is ~1.16 s, so it cannot merge beats but does reject the dicrotic
   notch) and reports, for every beat, its amplitude against the threshold in force, so a miss
   is attributable either to a small beat or to a stale threshold.
3. Sweeps `max_decay_tau_s`, counting both misses and EXTRA detections: a fast decay that
   recovers beats by letting noise cross the threshold would be a worse failure (an invented
   beat masks a real bradycardia), so a fix is only a fix if the extras stay at zero.
4. Contrasts the SQI rule (mean/std over 5 RR, as specified) against a robust median/MAD rule on
   the SAME detections, to separate "the detector missed a beat" from "the SQI reacted to it".

Reading of the 2026-09-15 capture (see conversation_log.md)
----------------------------------------------------------
V17 misses exactly one beat, at t=12.507 s: its amplitude is 8.82e-07 against a threshold of
1.04e-06 (85 % of it). The running maximum still held the 7.94 s peak (2.17e-06) because tau=20 s
decays it only ~20 % in 4.5 s, while the beat-to-beat amplitude of this recording swings by far
more than that (amplitude CV 37 % on V17, 43 % on .169, but only 23 % on .14 — the board that
never fails). The resulting 2.323 s interval then sits in the 5-RR buffer for five beats: 5.86 s
of SQI=0. tau=1.5 s (the value already recommended from the perturbed MS100 sweep) removes the
miss on all three boards with zero extra detections.

Usage:  python tools/hr1_streak_forensics.py [pattern] [--png]
        pattern defaults to MULTI_IDF_PROBE_*.csv
"""

import argparse
import glob
import os
import sys

import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pulsenest_lab as P   # noqa: E402

CAPTURES  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
COLS      = ("FW_Ts_us", "FW_OT_LED1", "FW_ProbeState", "FW_HR1", "FW_HR1_SQI",
             "FW_HR2", "FW_HR3", "FW_PI")
TAU_GRID  = (20.0, 5.0, 3.0, 2.0, 1.5, 1.0, 0.5)
MATCH_S   = 0.35     # a detection this close to a true beat counts as that beat
SETTLE_S  = 8.0      # replay start-up (DC remover + RR buffer), excluded from the scoring


def load(path):
    header, rows = None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split(",")
            if header is None:
                header = p
                continue
            rows.append(p)
    if header is None or not rows:
        return None, 0.0
    out = {}
    for c in COLS:
        if c not in header:
            return None, 0.0
        i = header.index(c)
        out[c] = np.array([float(r[i]) for r in rows])
    dts = np.diff(out["FW_Ts_us"])
    dts = dts[(dts > 0) & (dts < 1e5)]
    return out, float(np.round(1e6 / np.median(dts)))


def replay(ot, fs, **params):
    """Replay SPEC over the capture. -> (ma, running_max, threshold, hr, sqi, peak_idx).

    The DC estimator is pre-charged with the head of the capture: the firmware has been running
    for minutes, so letting the replay spend 4-5 tau settling would fabricate a difference.
    """
    c = P.HR1TestCalc()
    for k, v in params.items():
        if not hasattr(c, k):
            raise AttributeError(
                f"HR1TestCalc has no {k!r}: a mistyped parameter would otherwise be set as a new "
                f"attribute, nobody would read it, and the sweep would come out flat")
        setattr(c, k, v)
    c.reset()
    c._recalc_params(fs)
    c._dc_est = float(np.mean(ot[: int(0.5 * fs)]))
    n = len(ot)
    ma = np.empty(n); rmax = np.empty(n); thr = np.empty(n)
    hr = np.empty(n); sqi = np.empty(n); pk = []
    for i in range(n):
        c.update(float(ot[i]), fs, 2)
        ma[i]   = c.diag['ma_filtered'][-1]
        rmax[i] = c.diag['running_max'][-1]
        thr[i]  = c.diag['threshold'][-1]
        hr[i]   = c.hr_bpm
        sqi[i]  = c.hr_sqi
        if c.diag_peak_mask[-1] > 0:
            pk.append(i)
    return ma, rmax, thr, hr, sqi, np.array(pk)


def true_beats(ma, fs):
    """Beats established independently of the detector under test. -> peak indices.

    The refractory has to follow the rate. A fixed 0.7 s (the first version of this tool, written
    for a 52 bpm bench capture) is a 85 bpm ceiling: from 140 bpm up it keeps every other beat,
    and every real beat the detector finds in between is then scored as an "extra" - the extra
    column exploded with the rate and said nothing about tau. So: one permissive pass to estimate
    the median RR, then the real pass with a refractory of 0.6 x that RR. The rate written in the
    filename is deliberately not used: the truth must not depend on the label it is checking.

    Validated against counts known by other means: 100 beats in the 150 s at 40 bpm, 25 in the
    52 bpm bench capture (unchanged from the fixed-refractory version, so the 2026-09-15 finding
    stands), and N x duration / 60 at each MS100 rate, whose simulator is a metronome.
    """
    prom = np.std(ma) * 0.5
    coarse, _ = find_peaks(ma, distance=int(0.20 * fs), prominence=prom)   # 300 bpm ceiling
    if len(coarse) < 3:
        return coarse
    rr = np.median(np.diff(coarse)) / fs
    tb, _ = find_peaks(ma, distance=max(1, int(0.6 * rr * fs)), prominence=prom)
    return tb


def runs(mask):
    """-> [(start, end_exclusive)] of every True run."""
    d = np.diff(np.concatenate(([0], mask.view(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def match(tb, pk, fs):
    """-> (missed true beats, extra detections)."""
    missed = [i for i in tb if not len(pk) or np.min(np.abs(pk - i)) > MATCH_S * fs]
    extra  = [p for p in pk if not len(tb) or np.min(np.abs(tb - p)) > MATCH_S * fs]
    return missed, extra


def sqi_per_beat(pk, fs, robust, buf_len=None, cv_max=None):
    """Post-detection chain per beat. -> [(t, hr, sqi)] once the buffer is full."""
    buf_len = buf_len or P.HR1Variant.FW_RR_BUF_LEN
    cv_max  = cv_max  or P.HR1Variant.FW_SQI_CV_MAX
    out, rrs = [], []
    for k in range(1, len(pk)):
        rrs.append((pk[k] - pk[k - 1]) / fs)
        if len(rrs) > buf_len:
            rrs.pop(0)
        if len(rrs) < buf_len:
            continue
        a = np.array(rrs)
        if robust:
            centre = np.median(a)
            spread = np.median(np.abs(a - centre)) * 1.4826    # -> sigma-equivalent
        else:
            centre, spread = a.mean(), a.std()
        hr  = 60.0 / centre if centre > 0 else 0.0
        cv  = spread / centre if centre > 0 else 1.0
        sqi = float(np.clip(1.0 - cv / cv_max, 0.0, 1.0))
        if hr < P.HR1Variant.FW_HR_MIN_BPM or hr > P.HR1Variant.FW_HR_MAX_BPM:
            sqi = 0.0
        out.append((pk[k] / fs, hr, sqi))
    return out


def plot(path, d, fs, ma, rmax, thr, pk, ma2, rmax2, thr2, pk2, tb, window, tau_fast):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = np.arange(len(ma)) / fs
    lo, hi = window
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    panels = ((ma, rmax, thr, pk, "tau = %.0f s (firmware default)" % P.HR1Variant.FW_MAX_DECAY_TAU_S),
              (ma2, rmax2, thr2, pk2, "tau = %.1f s" % tau_fast))
    for ax, (m, rx, th, p, ttl) in zip(axes, panels):
        w = (t > lo) & (t < hi)
        ax.plot(t[w], m[w],  color="#44FF88", lw=1.0, label="MA filtered")
        ax.plot(t[w], rx[w], color="#FF8844", lw=1.0, label="running max")
        ax.plot(t[w], th[w], color="#FFDD44", lw=1.2, ls="--", label="threshold")
        sel  = [x for x in p  if lo * fs < x < hi * fs]
        tbs  = [x for x in tb if lo * fs < x < hi * fs]
        ax.plot(t[sel], m[sel], "v", color="#FFFFFF", ms=7, mec="k", label="detection")
        ax.plot(t[tbs], m[tbs], "o", color="none", mec="#FF3366", ms=11, mew=1.6, label="true beat")
        ax.set_title(ttl, fontsize=10)
        ax.set_ylabel("OT_LED1 AC [A/A]")
        ax.grid(alpha=.25)
        ax.legend(loc="upper left", fontsize=8, ncol=5)
    axes[1].set_xlabel("t [s]")
    fig.suptitle(os.path.basename(path), fontsize=11)
    fig.tight_layout()
    out = os.path.splitext(path)[0] + "_hr1_streak.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print("  figura: %s" % out)


def report(path, make_png=False, tau_fast=1.5):
    d, fs = load(path)
    if d is None:
        print("  (saltada, faltan columnas) %s" % os.path.basename(path))
        return
    ot = d["FW_OT_LED1"]
    t  = np.arange(len(ot)) / fs
    ma, rmax, thr, hr, sqi, pk = replay(ot, fs)
    tb = true_beats(ma, fs)
    rr = np.diff(tb) / fs
    fw_bad  = d["FW_HR1_SQI"] <= 0.0
    sim_bad = sqi <= 0.0
    settled = slice(int(SETTLE_S * fs), None)

    print("=" * 96)
    print("%s   fs=%.0f Hz   %.0f s" % (os.path.basename(path), fs, len(ot) / fs))
    print("  senal: %d latidos, RR %.3f-%.3f s (%.1f bpm), CV de amplitud %.1f %%, PI med %.2f"
          % (len(tb), rr.min(), rr.max(), 60.0 / rr.mean(),
             100 * np.std(ma[tb]) / np.mean(ma[tb]), np.median(d["FW_PI"])))
    print("  FW  HR1_SQI=0 %5.1f %%   rachas %s"
          % (100 * fw_bad.mean(), ["%.2f-%.2f s" % (t[a], t[b - 1]) for a, b in runs(fw_bad)]))
    print("  SIM HR1_SQI=0 %5.1f %%   rachas %s   (tras %.0f s de asentamiento)"
          % (100 * sim_bad[settled].mean(),
             ["%.2f-%.2f s" % (t[a], t[b - 1]) for a, b in runs(sim_bad) if a >= SETTLE_S * fs],
             SETTLE_S))

    missed, extra = match(tb, pk, fs)
    print("  latidos perdidos por SPEC: %s" % (["%.3f s" % (m / fs) for m in missed] or "ninguno"))
    for m in missed:
        k = int(np.flatnonzero(tb == m)[0])
        prev = ma[tb[k - 1]] if k else float("nan")
        print("    t=%.3f s: amplitud %.4e (%.0f %% de la anterior), umbral %.4e -> %.0f %% del umbral;"
              " running_max %.4e" % (m / fs, ma[m], 100 * ma[m] / prev, thr[m],
                                     100 * ma[m] / thr[m], rmax[m]))

    print("  barrido de tau (tras %.0f s):  %-9s %-9s %-7s %s"
          % (SETTLE_S, "SQI=0", "perdidos", "extra", "rachas"))
    for tau in TAU_GRID:
        _, _, _, _, s2, p2 = replay(ot, fs, max_decay_tau_s=tau)
        m2, e2 = match(tb, p2, fs)
        e2 = [x for x in e2 if x > SETTLE_S * fs]      # the t=0 start-up detection is not a finding
        print("    tau=%5.1f s              %6.1f %%   %2d/%-6d %-7d %s"
              % (tau, 100 * (s2[settled] <= 0).mean(), len(m2), len(tb), len(e2),
                 ["%.1f-%.1f s" % (t[a], t[b - 1])
                  for a, b in runs(s2 <= 0) if a >= SETTLE_S * fs] or "-"))

    print("  regla del SQI sobre las MISMAS detecciones (latidos tras %.0f s):" % SETTLE_S)
    for label, robust in (("media/desv (spec)", False), ("mediana/MAD", True)):
        rows  = [r for r in sqi_per_beat(pk, fs, robust) if r[0] > SETTLE_S]
        valid = [r for r in rows if r[2] > 0]
        if not rows:
            continue
        print("    %-18s %2d/%2d validos (%3.0f %%), HR publicado %.1f-%.1f bpm%s"
              % (label, len(valid), len(rows), 100.0 * len(valid) / len(rows),
                 min(r[1] for r in valid) if valid else float("nan"),
                 max(r[1] for r in valid) if valid else float("nan"),
                 "" if len(valid) == len(rows)
                 else "; vetado en %s (habria publicado %.0f bpm)"
                      % (", ".join("%.1f s" % r[0] for r in rows if r[2] <= 0),
                         np.mean([r[1] for r in rows if r[2] <= 0]))))

    if make_png and len(missed):
        ma2, rmax2, thr2, _, _, pk2 = replay(ot, fs, max_decay_tau_s=tau_fast)
        centre = missed[0] / fs
        plot(path, d, fs, ma, rmax, thr, pk, ma2, rmax2, thr2, pk2, tb,
             (max(0.0, centre - 5.5), centre + 9.5), tau_fast)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", default="MULTI_IDF_PROBE_*.csv",
                    help="glob dentro de captures/")
    ap.add_argument("--png", action="store_true", help="figura por captura con latido perdido")
    ap.add_argument("--tau", type=float, default=1.5, help="tau rapido de la figura")
    args = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(CAPTURES, args.pattern)))
    if not paths:
        print("sin capturas para %s" % args.pattern)
        return
    for p in paths:
        report(p, make_png=args.png, tau_fast=args.tau)


if __name__ == "__main__":
    main()
