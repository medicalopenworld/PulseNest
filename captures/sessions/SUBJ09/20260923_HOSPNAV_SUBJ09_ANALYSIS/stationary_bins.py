"""Stationarity-filtered calibration check over pairs.csv (run r_vs_ref_analysis.py first).

Keeps only reference readings that are quasi-stationary (reference moved <= 2 pts
within +/-10 s), so the monitor's internal averaging delay cannot skew the pair,
then fits SpO2-on-R by weighted least squares over per-SpO2-bin median R values
(inverse-regression style, resistant to the noise-in-R attenuation that flattens
a direct fit).
"""

import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

rows = [r for r in csv.DictReader(open(os.path.join(HERE, "pairs.csv")))
        if r["usable"] == "1"]
by_sess = {}
for r in rows:
    by_sess.setdefault(r["session"], []).append(r)

stat = []
for sess, rs in by_sess.items():
    rs.sort(key=lambda r: int(r["t_epoch_us"]))
    t = np.array([int(r["t_epoch_us"]) for r in rs])
    y = np.array([float(r["ref_spo2"]) for r in rs])
    for i, r in enumerate(rs):
        m = np.abs(t - t[i]) <= 10e6
        if m.sum() >= 3 and np.ptp(y[m]) <= 2:
            stat.append(r)
print(f"stationary pairs: {len(stat)} / {len(rows)}")
ref = np.array([float(r["ref_spo2"]) for r in stat])
rr = np.array([float(r["r_med"]) for r in stat])
ours = np.array([float(r["our_spo2_med"]) for r in stat])
print(f"stationary bias ours-ref: median {np.median(ours - ref):+.1f}")

bins = {}
for v, x in zip(ref, rr):
    bins.setdefault(round(v), []).append(x)
ks = sorted(k for k in bins if len(bins[k]) >= 10)
print("ref bin -> n, median R:")
for k in ks:
    print(f"  {k}: n={len(bins[k]):4d}  R={np.median(bins[k]):.3f}")
xb = np.array([np.median(bins[k]) for k in ks], float)
yb = np.array(ks, float)
w = np.array([len(bins[k]) for k in ks], float)
A = np.vstack([np.ones_like(xb), xb]).T
W = np.diag(w)
coef, *_ = np.linalg.lstsq(W @ A, W @ yb, rcond=None)
a, b = coef
pred = a + b * xb
print(f"\nfit on bin medians: SpO2 = {a:.2f} {b:+.2f}*R   (current: 114.92 - 30.55*R)")
print(f"residuals per bin: {' '.join(f'{v:+.1f}' for v in (yb - pred))}")
rms = float(np.sqrt(np.average((yb - pred) ** 2, weights=w)))
print(f"weighted RMS over bins: {rms:.2f} pts")
