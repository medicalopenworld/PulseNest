"""tau x k sweep on the perturbed MS100 captures (presses at ~20/30/40/50 s).

Two metrics per cell:
  good%   : share of scored samples with SQI>0 and |HR-truth| <= 3 BPM (after 10 s warm-up)
  rec (s) : mean time from each press event to the first 'good' sample after it. This is the
            metric tau actually governs; good% is flattened by the SQI's 5-RR blackout, which every
            tau pays equally.
"""
import os, sys
sys.path.insert(0, r"C:\PRJ\MOW\PulseNest"); sys.path.insert(0, r"C:\PRJ\MOW\PulseNest\tools")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pulsenest_lab as P
from hr1_decay_sweep import load_capture, CAPTURES

EVENTS   = (20.0, 30.0, 40.0, 50.0)   # approximate press instants (1, 2, 3, 4 presses)
WARMUP_S = 10.0
TOL      = 3.0
TAUS     = (0.5, 1.0, 1.5, 2.0, 3.0, 20.0)
KS       = (0.6, 1.0)


def run(cls, params, ot, ps, fs, truth):
    c = cls()
    for k, v in params.items():
        setattr(c, k, v)
    c.reset()
    n = len(ot)
    good = np.zeros(n, dtype=bool)
    for i in range(n):
        c.update(float(ot[i]), fs, int(ps[i]), None)
        good[i] = (ps[i] == c.PROBE_APPLIED) and c.hr_sqi > 0.0 and abs(c.hr_bpm - truth) <= TOL
    t = np.arange(n) / fs
    scored = t >= WARMUP_S
    g = good[scored].mean() if scored.any() else float("nan")
    recs = []
    for e in EVENTS:
        # The published HR stays valid for a few beats after the press starts (the RR buffer has
        # not yet taken a bad interval), so "first good sample after e" finds the stale reading.
        # Measure instead the end of the blackout: the first good sample after the first bad
        # stretch that begins after e. Censored at the next event.
        lo, hi = e - 0.5, e + 9.5
        win = np.flatnonzero((t >= lo) & (t < hi))
        bad = win[~good[win]]
        if len(bad) == 0:
            recs.append(0.0)                       # never lost the reading
            continue
        after = win[(win > bad[0]) & good[win]]
        recs.append((t[after[0]] - e) if len(after) else (hi - e))
    return g, float(np.mean(recs)), recs


caps = []
for f in sorted(os.listdir(CAPTURES)):
    if "PROBEPERT" in f and f.endswith(".csv"):
        c = load_capture(os.path.join(CAPTURES, f))
        if c: caps.append(c)
caps.sort(key=lambda x: x[3])
hrs = [int(c[3]) for c in caps]
print("capturas perturbadas (verdad BPM):", hrs)
print("rec = tiempo medio (s) desde cada rafaga hasta la primera lectura correcta; 9.5 = no volvio\n")

for variant in (P.HR1TestCalc, P.HR1BiquadCalc):
    print("=" * 96)
    print("VARIANTE %s" % variant.NAME)
    print("%-5s %-4s | %s | %s" % ("tau", "k",
          "good%: " + " ".join("%4d" % h for h in hrs),
          "rec s: " + " ".join("%4d" % h for h in hrs)))
    for k in KS:
        for tau in TAUS:
            gs, rs = [], []
            for ot, ps, fs, tr in caps:
                g, r, _ = run(variant, {"max_decay_tau_s": tau, "threshold_factor": k}, ot, ps, fs, tr)
                gs.append(g); rs.append(r)
            print("%-5.1f %-4.1f |        %s | %s  | peor good %3.0f%%  peor rec %4.1f s"
                  % (tau, k, " ".join("%4.0f" % (100 * g) for g in gs),
                     "       " + " ".join("%4.1f" % r for r in rs), 100 * min(gs), max(rs)))
        print()
