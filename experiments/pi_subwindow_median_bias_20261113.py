"""Bias and wander of a median-of-sub-windows PI against the exact window RMS on a CLEAN pulse,
as a function of the pulse rate, the sub-window length L, the step s and the window W.
Study of 2026-11-13 for PI-METHOD-2 (lib v0.120; library rationale §23). Alex's questions: at
30 BPM a 1 s sub-window holds half a beat, so does the RMS need 2 s? and does a small step (100 ms)
average that error away?

Synthetic pulse: systolic gaussian + dicrotic bump, mean removed (stands in for the band-pass),
500 Hz. For each (HR, L, s, W) the window start is swept over one full beat (all phases) and the
median-of-N sub-window energies is compared with the true mean energy of the window; the ratio of
the PIs (square roots) is reported as its mean over phases (= bias) and its min–max (= wander as
the window slides). `box jitter` is the phase wander of the whole-window PI itself.

Result (2026-11-13), PI_median / PI_box, mean (min–max):
    L     s    W   N |  30 BPM           40 BPM           45 BPM         60  90 BPM           150 BPM
    1 s   1 s  7 s  7 | 0.96 (0.56–1.25) 1.09 (0.91–1.17) 1.06 (0.93–1.12) 1  1.00 (0.89–1.10) 1.00 (0.93–1.06)
    1 s   0.1  7 s 61 | 1.00 (0.85–1.12) 1.10 (1.06–1.15) 1.06 (1.01–1.09) 1  1.00 (0.95–1.05) 1.00 (0.95–1.04)
    2 s   1 s  8 s  7 | 1.00             0.96 (0.91–1.05) 1.00 (0.91–1.08) 1  1.00             1.00
    2 s   0.1  8 s 61 | 1.00             0.96 (0.92–0.98) 1.00 (0.94–1.05) 1  1.00             1.00
- The fine step removes the wander (range halves or better), NOT the bias: at 40–45 BPM L = 1 s
  stays +6–10 % because the median of the phase distribution is not its mean (the mean is the
  true RMS). A sinusoid gives the exact RMS over any half period; the bias is the harmonics'.
- L = 2 s removes the bias (≤ 4 % at 40 BPM, 0 elsewhere) and halves the wander again, but costs
  1.5 s of burst tolerance per second of L: tolerance = (W − 3·L)/2 with a fine step.
- Decision (Alex): L = 1 s, step 100 ms, W = 7 s (tolerates 2 s; bias only below 50 BPM, of the
  order of the 2√2 assumption's own 0–12 %).
One pulse shape; the bias on a real bradycardic neonate is not measured.

    python experiments/pi_subwindow_median_bias_20261113.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np   # noqa: E402

FS = 500.0


def pulse(hr_bpm, n_s):
    t = np.arange(int(n_s * FS)) / FS
    T = 60.0 / hr_bpm
    ph = (t / T) % 1.0
    p = np.exp(-((ph - 0.20) / 0.07) ** 2) + 0.40 * np.exp(-((ph - 0.48) / 0.12) ** 2)
    p -= p.mean()
    return p


def study(hr, L, s, W):
    x = pulse(hr, W + 60.0 / hr + 2)
    e = x * x
    cs = np.concatenate([[0.0], np.cumsum(e)])
    nL, ns, nW = int(L * FS), int(s * FS), int(W * FS)
    N = (nW - nL) // ns + 1
    T = int(60.0 / hr * FS)
    med, box = [], []
    for start in range(0, T, max(1, T // 60)):          # all phases of the window start
        subs = [(cs[start + k * ns + nL] - cs[start + k * ns]) / nL for k in range(N)]
        med.append(np.median(subs))
        box.append((cs[start + nW] - cs[start]) / nW)
    med, box = np.array(med), np.array(box)
    r = np.sqrt(med / box)                                 # PI ratio (sqrt of energies)
    return N, r.mean(), r.min(), r.max(), np.sqrt(box).std() / np.sqrt(box).mean()


def main():
    print(f"{'HR':>4} {'L':>4} {'s':>5} {'W':>3} {'N':>3} | median/box: mean   min   max | box jitter")
    for W in (7.0, 8.0):
        for L in (1.0, 2.0):
            for s in (1.0, 0.5, 0.1):
                for hr in (30, 40, 45, 60, 90, 120, 150):
                    N, m, lo, hi, bj = study(hr, L, s, W)
                    print(f"{hr:4d} {L:4.1f} {s:5.1f} {W:3.0f} {N:3d} |          {m:6.3f} {lo:6.3f} {hi:6.3f} |   {bj:6.3f}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
