"""R curve for R-METHOD-2 as implemented in the library (v0.100), fitted on the HOSPNAV campaigns.

Same pair set, stationarity rule and bin fit as r_regression_test.py (so the numbers are
comparable with its table), but R comes from the library itself: incunest_offline_runner
(lib v0.100, raw-code replay with the library's current rsqm_ot_thr) writes R and R_CORR per
row in derived/replay_lib0.100/; here each usable reference reading is paired with the median
library R over the 8 s window before it, and r (R_CORR) likewise.

Outputs (this directory): fit_method2_summary.txt
"""
import csv
import glob
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from r_regression_test import PAIR_FILES, SESSIONS, WINDOW_S, binfit, stationary_mask

HERE = os.path.dirname(os.path.abspath(__file__))
REPLAY_DIR = os.path.join("derived", "replay_lib0.100")
R_MIN = 0.8                 # the library's default spo2_r_corr_min


def load_replay(session_dir):
    """Row time [us] (from the parts' clock anchors) + the library's R, r, SpO2_SQI per row."""
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    anchors_row, anchors_t, base = [], [], 0
    R, RC, SQI = [], [], []
    for path in parts:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("# @row ") and " clock: " in line:
                    anchors_row.append(base + int(line.split()[2]))
                    anchors_t.append(int(line.split("host_epoch_us=")[1].split()[0]))
        rp = os.path.join(session_dir, REPLAY_DIR, os.path.basename(path)[:-4] + "_replay.csv")
        df = pd.read_csv(rp, usecols=["R", "R_CORR", "SpO2_SQI"])
        R.append(df["R"].to_numpy(float)); RC.append(df["R_CORR"].to_numpy(float))
        SQI.append(df["SpO2_SQI"].to_numpy(float))
        base += len(df)
    R, RC, SQI = np.concatenate(R), np.concatenate(RC), np.concatenate(SQI)
    rows = np.arange(len(R), dtype=float)
    ar, at = np.array(anchors_row, float), np.array(anchors_t, float)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0]); per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    return {"t": t, "R": R, "r": RC, "sqi": SQI}


def window_median(s, t1):
    i0 = np.searchsorted(s["t"], t1 - WINDOW_S * 1e6, side="right")
    i1 = np.searchsorted(s["t"], t1, side="right")
    R, r = s["R"][i0:i1], s["r"][i0:i1]
    ok = np.isfinite(R)
    if ok.sum() < 100:
        return np.nan, np.nan, 0.0
    return float(np.median(R[ok])), float(np.nanmedian(r)), float(ok.mean())


def main():
    rows = []
    for subj, pf in PAIR_FILES.items():
        pairs = [p for p in csv.DictReader(open(pf, encoding="utf-8")) if p["usable"] == "1"]
        for name in sorted({p["session"] for p in pairs}):
            s = load_replay(os.path.join(SESSIONS, name))
            for p in (p for p in pairs if p["session"] == name):
                R, r, frac = window_median(s, float(p["t_epoch_us"]))
                rows.append(dict(subj=subj, session=name, t=float(p["t_epoch_us"]),
                                 ref=float(p["ref_spo2"]), R=R, r=r, frac=frac))
    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(), df["ref"].to_numpy())
    st = df[df["stat"] & np.isfinite(df["R"])]
    lines = [f"usable pairs {len(df)}, stationary with a library R {len(st)} "
             f"(SUBJ08 {int((st.subj == 'SUBJ08').sum())}, SUBJ09 {int((st.subj == 'SUBJ09').sum())}); "
             f"window {WINDOW_S:.0f} s; library R-METHOD-2 (lib v0.100 replay)",
             f"window r: median {st['r'].median():.3f}, p1 {st['r'].quantile(0.01):.3f}, "
             f"min {st['r'].min():.3f}; windows with r < {R_MIN}: {(st['r'] < R_MIN).sum()}"]

    def report(sub, label):
        R, y = sub["R"].to_numpy(), sub["ref"].to_numpy()
        a, b, rms, scat = binfit(R, y)
        res = np.nanmedian(np.abs(y - (a + b * R)))
        rho = spearmanr(R, y, nan_policy="omit")[0]
        lines.append(f"{label:34s} n={len(sub):5d}  medR {np.nanmedian(R):.3f}  rho {rho:+.2f}  "
                     f"fit SpO2 = {a:.2f} {b:+.2f}*R  RMSbin {rms:.2f}  scatter {scat:.2f}  |res| {res:.2f}")
        return a, b

    a, b = report(st, "pooled (both subjects)")
    for g in ("SUBJ08", "SUBJ09"):
        report(st[st.subj == g], f"  {g} alone")
    # leave-one-subject-out: fit on one, error on the other
    for fit_g, test_g in (("SUBJ08", "SUBJ09"), ("SUBJ09", "SUBJ08")):
        f = st[st.subj == fit_g]; tt = st[st.subj == test_g]
        fa, fb, *_ = binfit(f["R"].to_numpy(), f["ref"].to_numpy())
        err = tt["ref"].to_numpy() - (fa + fb * tt["R"].to_numpy())
        lines.append(f"  fit on {fit_g} -> {test_g}: median error {np.nanmedian(err):+.2f}, "
                     f"median |err| {np.nanmedian(np.abs(err)):.2f} pts")
    # error of the pooled fit per reference band
    lines.append("pooled-fit error by reference band (median, p10..p90):")
    for lo, hi in ((70, 85), (85, 90), (90, 95), (95, 101)):
        m = (st["ref"] >= lo) & (st["ref"] < hi)
        if m.sum() < 10:
            continue
        e = (a + b * st["R"][m]) - st["ref"][m]
        lines.append(f"  ref {lo}-{hi - 1}: n={int(m.sum()):4d}  {np.median(e):+.2f}  "
                     f"[{np.percentile(e, 10):+.2f}, {np.percentile(e, 90):+.2f}]")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(HERE, "fit_method2_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
