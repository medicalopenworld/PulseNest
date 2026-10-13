"""Causal (streaming) versions of the R estimators of r_regression_test.py -- step 1a/1b/1c of the
R-method plan (memory project_spo2_r_estimation_alternatives_task, approved 2026-10-02).

r_regression_test.py filtered each session with a zero-phase band-pass (sosfiltfilt) and computed
every estimator over the 8 s window of each pair: it used future samples, which the firmware cannot.
Here every estimator is computed sample by sample, forward only, exactly as the library would:

    dc   = EMA(ot, tau_dc)                                  per channel, causal
    bp   = Butterworth band-pass, forward only (sosfilt)     per channel
    x    = bp_ir / dc_ir,   y = bp_red / dc_red
    rms_bp   R = sqrt(EMA(y^2) / EMA(x^2))                   tau_ac
    reg_ols  R = EMA(x*y) / EMA(x^2)                          tau_ac
    reg_dols R = EMA(dx*dy) / EMA(dx^2),  dx = x[n] - x[n-k]  tau_ac

Each pair reads the streaming R at the reference instant ("inst") and its median over the pair's
8 s window ("med", like the library's r_med column). Same pairs, same stationary mask, same fit and
scatter metric as r_regression_test.py; the zero-phase reg_dols is recomputed here as the baseline.

Also reported for the baseline configuration (step 1c): leave-one-subject-out -- fit on one subject,
predict the other (bias and median |error| of single pairs, in SpO2 points).

Output (this directory): r_causal_summary.txt
"""

import csv
import os

import numpy as np
import pandas as pd
from scipy.signal import butter, lfilter, sosfilt, sosfilt_zi
from scipy.stats import spearmanr

from r_regression_test import (FS_HZ, PAIR_FILES, SESSIONS, WINDOW_S, binfit, load_session,
                               stationary_mask, window_estimates)

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = {"band": (0.5, 5.0), "order": 2, "tau_dc": 2.0, "tau_ac": 6.0, "k": 1}
# one-at-a-time sensitivity around BASE (step 1b)
VARIANTS = [("base", {})] + [
    (f"band {lo}-{hi}", {"band": (lo, hi)}) for lo, hi in
    ((0.3, 5.0), (0.7, 5.0), (0.5, 4.0), (0.5, 8.0))] + [
    ("order 4", {"order": 4})] + [
    (f"tau_ac {t:g}", {"tau_ac": t}) for t in (2.0, 4.0, 8.0)] + [
    (f"tau_dc {t:g}", {"tau_dc": t}) for t in (1.0, 6.0)] + [
    (f"k {k}", {"k": k}) for k in (5, 10, 25)]
EST = ("rms_bp", "reg_ols", "reg_dols")


def ema(v, tau_s, v0=0.0):
    a = 1.0 - np.exp(-1.0 / (tau_s * FS_HZ))
    return lfilter([a], [1.0, a - 1.0], v, zi=[(1.0 - a) * v0])[0]


def causal_r(s, cfg):
    sos = butter(cfg["order"], cfg["band"], btype="bandpass", fs=FS_HZ, output="sos")
    zi = sosfilt_zi(sos)
    xs = []
    for ch in ("ir", "red"):
        v = s[ch]
        dc = ema(v, cfg["tau_dc"], v[0])
        bp = sosfilt(sos, v, zi=zi * v[0])[0]
        with np.errstate(divide="ignore", invalid="ignore"):
            xs.append(np.where(dc > 0, bp / dc, 0.0))
    x, y = xs
    k = cfg["k"]
    dx = np.concatenate([np.zeros(k), x[k:] - x[:-k]])
    dy = np.concatenate([np.zeros(k), y[k:] - y[:-k]])
    t = cfg["tau_ac"]
    exx = ema(x * x, t)
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"rms_bp": np.sqrt(ema(y * y, t) / exx),
                "reg_ols": ema(x * y, t) / exx,
                "reg_dols": ema(dx * dy, t) / ema(dx * dx, t)}


def evaluate(df, col):
    r, y = df[col].to_numpy(), df["ref"].to_numpy()
    rho = spearmanr(r, y, nan_policy="omit")[0]
    a, b, rms, scat = binfit(r, y)
    fits = {}
    for g in ("SUBJ08", "SUBJ09"):
        gg = df[df.subj == g]
        fits[g] = binfit(gg[col].to_numpy(), gg["ref"].to_numpy())[:2]
    return rho, a, b, scat, fits


def loso(df, col):
    """Fit on one subject, predict the other: bias and median |error| of single pairs."""
    out = []
    for train, test in (("SUBJ08", "SUBJ09"), ("SUBJ09", "SUBJ08")):
        tr, te = df[df.subj == train], df[df.subj == test]
        a, b, *_ = binfit(tr[col].to_numpy(), tr["ref"].to_numpy())
        err = (a + b * te[col].to_numpy()) - te["ref"].to_numpy()
        out.append(f"fit {train} -> {test}: bias {np.nanmedian(err):+5.2f}, "
                   f"median |err| {np.nanmedian(np.abs(err)):4.2f} pts")
    return out


def main():
    pairs = {}
    for subj, pf in PAIR_FILES.items():
        for p in csv.DictReader(open(pf, encoding="utf-8")):
            if p["usable"] == "1":
                pairs.setdefault(p["session"], []).append((subj, p))
    rows = []
    for name, plist in sorted(pairs.items()):
        s = load_session(os.path.join(SESSIONS, name))
        streams = {v: causal_r(s, {**BASE, **o}) for v, o in VARIANTS}
        for subj, p in plist:
            t1 = float(p["t_epoch_us"])
            i0 = np.searchsorted(s["t"], t1 - WINDOW_S * 1e6, side="right")
            i1 = np.searchsorted(s["t"], t1, side="right")
            row = {"subj": subj, "session": name, "t": t1, "ref": float(p["ref_spo2"]),
                   "lib": float(p["r_med"]),
                   "zp_reg_dols": window_estimates(s, t1)["reg_dols"]}
            for v, st in streams.items():
                for e in EST:
                    w = st[e][i0:i1]
                    w = w[np.isfinite(w)]
                    row[f"{v}|{e}|med"] = np.median(w) if len(w) else np.nan
                    row[f"{v}|{e}|inst"] = st[e][i1 - 1] if i1 > i0 else np.nan
            rows.append(row)
        print(f"{name}: {len(plist)} pairs")
    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(), df["ref"].to_numpy())
    st = df[df["stat"]]

    lines = [f"stationary pairs {len(st)} (SUBJ08 {(st.subj == 'SUBJ08').sum()}, "
             f"SUBJ09 {(st.subj == 'SUBJ09').sum()}); window {WINDOW_S:.0f} s; base {BASE}", "",
             f"{'variant':14s} {'estimator':9s} {'read':4s} {'rho':>6s} {'pooled fit':>17s} "
             f"{'scatter':>7s} {'fit SUBJ08':>17s} {'fit SUBJ09':>17s}"]

    def line(label, est, read, col):
        rho, a, b, scat, fits = evaluate(st, col)
        f8, f9 = fits["SUBJ08"], fits["SUBJ09"]
        lines.append(f"{label:14s} {est:9s} {read:4s} {rho:+6.2f} {a:7.2f} {b:+7.2f}R  {scat:7.2f} "
                     f"{f8[0]:7.2f} {f8[1]:+7.2f}R {f9[0]:7.2f} {f9[1]:+7.2f}R")

    line("lib R-METHOD-1", "", "med", "lib")
    line("zero-phase", "reg_dols", "win", "zp_reg_dols")
    lines.append("")
    for e in EST:
        for read in ("med", "inst"):
            line("base", e, read, f"base|{e}|{read}")
    lines += ["", "--- sensitivity, reg_dols (one parameter changed at a time) ---"]
    for v, _ in VARIANTS:
        for read in ("med", "inst"):
            line(v, "reg_dols", read, f"{v}|reg_dols|{read}")
    lines += ["", "--- leave-one-subject-out ---"]
    for label, col in (("lib R-METHOD-1", "lib"), ("zero-phase reg_dols", "zp_reg_dols"),
                       ("causal reg_dols med", "base|reg_dols|med"),
                       ("causal reg_dols inst", "base|reg_dols|inst")):
        lines += [f"{label}:"] + ["    " + s for s in loso(st, col)]

    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "r_causal_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
