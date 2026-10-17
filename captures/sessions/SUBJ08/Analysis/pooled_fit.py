"""Pooled two-subject calibration fit over the 20260923_HOSPNAV campaigns.

Inputs: this campaign's pairs_replay.csv (SUBJ08 replayed by incunest_offline_runner
v0.20 with the v0.95 rsqm_ot_thr) and ../../SUBJ09/20260923_HOSPNAV_SUBJ09_ANALYSIS/pairs.csv
(SUBJ09, firmware columns — that subject barely spent time in OT_HIGH, so a replay
changes little). Same stationarity filter and binned inverse regression as
stationary_bins.py, then one weighted fit over the pooled bins and per-subject
residuals under the pooled curve.
"""

import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS = os.path.dirname(HERE)


def stationary_pairs(pairs_path):
    rows = [r for r in csv.DictReader(open(pairs_path)) if r["usable"] == "1"]
    by_sess = {}
    for r in rows:
        by_sess.setdefault(r["session"], []).append(r)
    out = []
    for rs in by_sess.values():
        rs.sort(key=lambda r: int(r["t_epoch_us"]))
        t = np.array([int(r["t_epoch_us"]) for r in rs])
        y = np.array([float(r["ref_spo2"]) for r in rs])
        for i, r in enumerate(rs):
            m = np.abs(t - t[i]) <= 10e6
            if m.sum() >= 3 and np.ptp(y[m]) <= 2:
                out.append((float(r["r_med"]), float(r["ref_spo2"])))
    return out


def binfit(pairs, label):
    bins = {}
    for r, y in pairs:
        bins.setdefault(round(y), []).append(r)
    ks = sorted(k for k in bins if len(bins[k]) >= 10)
    xb = np.array([np.median(bins[k]) for k in ks], float)
    yb = np.array(ks, float)
    w = np.array([len(bins[k]) for k in ks], float)
    A = np.vstack([np.ones_like(xb), xb]).T
    W = np.diag(w)
    (a, b), *_ = np.linalg.lstsq(W @ A, W @ yb, rcond=None)
    rms = float(np.sqrt(np.average((yb - (a + b * xb)) ** 2, weights=w)))
    print(f"{label}: SpO2 = {a:.2f} {b:+.2f}*R   RMS {rms:.2f} pts over {len(ks)} bins")
    return a, b


p8 = stationary_pairs(os.path.join(HERE, "pairs_replay.csv"))
# Since 2026-10-16 sessions sit under one folder per subject: HERE is .../SUBJ08/<this>, so the
# other subject's analysis is two levels up, then down into SUBJ09/.
p9 = stationary_pairs(os.path.join(os.path.dirname(SESSIONS), "SUBJ09", "20260923_HOSPNAV_SUBJ09_ANALYSIS", "pairs.csv"))
print(f"stationary pairs: SUBJ08 {len(p8)}, SUBJ09 {len(p9)}")
binfit(p8, "SUBJ08 (replay)   ")
binfit(p9, "SUBJ09            ")
a, b = binfit(p8 + p9, "POOLED n=2        ")
for label, pairs in (("SUBJ08", p8), ("SUBJ09", p9)):
    res = [y - (a + b * r) for r, y in pairs]
    print(f"  pooled-curve residuals {label}: median {np.median(res):+.2f}  "
          f"p10 {np.percentile(res, 10):+.1f}  p90 {np.percentile(res, 90):+.1f}")
