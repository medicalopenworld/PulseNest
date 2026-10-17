"""Offline test of alternative R estimators on the 20260923_HOSPNAV campaigns (SUBJ08 + SUBJ09).

Question: does estimating R as a regression slope (red vs IR, over every sample of the
window) track the reference SpO2 better than the RMS ratio the library uses today
(R-METHOD-1: R = (rms_ac_red/dc_red)/(rms_ac_ir/dc_ir), EMA tau_dc 2 s / tau_ac 6 s)?

Pair set: exactly the usable pairs of the existing analysis -- SUBJ08 pairs_replay.csv
(lib v0.96 replay, v0.95 rsqm_ot_thr) and SUBJ09 pairs.csv (firmware). Each pair is one
reference reading (VideoNest OCR) and the board's 8 s window before it. Every method below
is computed from the SAME OT_LED1 (IR) / OT_LED2 (red) samples of that window, so the
only difference between rows of the output table is the estimator.

Methods (x = IR, y = red, both AC normalised by the window's DC):
    lib       library R (median in window, column r_med of the pairs files) -- R-METHOD-1
    rms_raw   std(red)/dc_red / std(ir)/dc_ir over the window, no band-pass
              (window analogue of R-METHOD-1; sanity check against 'lib')
    rms_bp    same ratio after a 0.5-5 Hz zero-phase band-pass
    reg_ols   least-squares slope through the origin, y = R x  ->  R = sum(xy)/sum(x^2)
              (band-passed). Biased low when x (IR) carries noise (regression dilution).
    reg_tls   total least squares slope (principal axis of the x-y cloud): error shared
              by both axes, no dilution if the noise is similar in both channels
    reg_dols  OLS on the first differences of x and y (derivative variant)
    + r2      squared correlation of the x-y cloud: candidate quality index

Evaluation (stationary pairs only: reference moving <= 2 pts within +/-10 s, as in
pooled_fit.py):
    rho       Spearman rank correlation R vs reference (expected negative; more negative
              = R tracks SaO2 better)
    fit       weighted fit of reference on per-bin median R (as pooled_fit.py), RMS over bins
    scatter   weighted median over bins of IQR(R in bin) x |slope|, in SpO2 points: the
              vertical spread an R estimator adds at constant reference SpO2
    resid     median |residual| of single pairs under the pooled fit [pts]

Outputs (this directory): r_regression_summary.txt, r_regression_scatter.png
"""

import csv
import glob
import os

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS = os.path.dirname(HERE)
PAIR_FILES = {
    "SUBJ08": os.path.join(HERE, "pairs_replay.csv"),
    # one folder per subject since 2026-10-16: SESSIONS is .../SUBJ08, the other subject is beside it
    "SUBJ09": os.path.join(os.path.dirname(SESSIONS), "SUBJ09", "20260923_HOSPNAV_SUBJ09_ANALYSIS", "pairs.csv"),
}
FS_HZ = 500.0
WINDOW_S = 8.0              # must match REF_WINDOW_S of r_vs_ref_analysis.py
BP_HZ = (0.5, 5.0)          # pulsatile band (HR 30-300 bpm)
PROBE_ON = (1, 2)           # as in r_vs_ref_analysis.py for this campaign
R2_GATE = 0.9               # r2 gate for the "quality-gated" variant
METHODS = ("lib", "rms_raw", "rms_bp", "reg_ols", "reg_tls", "reg_dols")


def load_session(session_dir):
    """OT_LED1, OT_LED2, ProbeState and row epoch [us] of all parts of a session."""
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    ir, red, ps = [], [], []
    anchors_row, anchors_t = [], []
    base = 0
    for path in parts:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("# @row ") and " clock: " in line:
                    anchors_row.append(base + int(line.split()[2]))
                    anchors_t.append(int(line.split("host_epoch_us=")[1].split()[0]))
        df = pd.read_csv(path, comment="#", usecols=["OT_LED1", "OT_LED2", "ProbeState"],
                         on_bad_lines="skip")
        ir.append(df["OT_LED1"].to_numpy(float))
        red.append(df["OT_LED2"].to_numpy(float))
        ps.append(df["ProbeState"].to_numpy(int))
        base += len(df)
    ir, red, ps = np.concatenate(ir), np.concatenate(red), np.concatenate(ps)
    rows = np.arange(len(ir), dtype=float)
    ar, at = np.array(anchors_row, float), np.array(anchors_t, float)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0])
    per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    sos = butter(2, BP_HZ, btype="bandpass", fs=FS_HZ, output="sos")
    return {"t": t, "ir": ir, "red": red, "ps": ps,
            "ir_bp": sosfiltfilt(sos, ir), "red_bp": sosfiltfilt(sos, red)}


def window_estimates(s, t1):
    """All raw-signal estimators over the (t1 - WINDOW_S, t1] window."""
    i0 = np.searchsorted(s["t"], t1 - WINDOW_S * 1e6, side="right")
    i1 = np.searchsorted(s["t"], t1, side="right")
    ir, red = s["ir"][i0:i1], s["red"][i0:i1]
    out = {k: np.nan for k in METHODS[1:]}
    out["r2"] = np.nan
    out["full_on"] = bool(np.isin(s["ps"][i0:i1], PROBE_ON).all()) if i1 > i0 else False
    if i1 - i0 < 100:
        return out
    dc_ir, dc_red = ir.mean(), red.mean()
    if dc_ir <= 0 or dc_red <= 0:
        return out
    out["rms_raw"] = (red.std() / dc_red) / (ir.std() / dc_ir)
    x = s["ir_bp"][i0:i1] / dc_ir
    y = s["red_bp"][i0:i1] / dc_red
    sxx, syy, sxy = np.dot(x, x), np.dot(y, y), np.dot(x, y)
    if sxx <= 0 or sxy <= 0:
        return out
    out["rms_bp"] = np.sqrt(syy / sxx)
    out["reg_ols"] = sxy / sxx
    out["reg_tls"] = (syy - sxx + np.sqrt((syy - sxx) ** 2 + 4 * sxy ** 2)) / (2 * sxy)
    dx, dy = np.diff(x), np.diff(y)
    out["reg_dols"] = np.dot(dx, dy) / np.dot(dx, dx)
    out["r2"] = sxy ** 2 / (sxx * syy)
    return out


def stationary_mask(sess, t, y):
    m = np.zeros(len(t), bool)
    for name in np.unique(sess):
        idx = np.where(sess == name)[0]
        idx = idx[np.argsort(t[idx])]
        tt, yy = t[idx], y[idx]
        for k, i in enumerate(idx):
            w = np.abs(tt - tt[k]) <= 10e6
            m[i] = w.sum() >= 3 and np.ptp(yy[w]) <= 2
    return m


def binfit(r, y):
    """Weighted LS of reference on per-bin median R (bins = integer ref SpO2, >= 10 pairs)."""
    ok = np.isfinite(r)
    r, y = r[ok], y[ok]
    keys = [k for k in np.unique(np.round(y)) if (np.round(y) == k).sum() >= 10]
    xb = np.array([np.median(r[np.round(y) == k]) for k in keys])
    iqr = np.array([np.subtract(*np.percentile(r[np.round(y) == k], [75, 25])) for k in keys])
    yb = np.array(keys, float)
    w = np.array([(np.round(y) == k).sum() for k in keys], float)
    A = np.vstack([np.ones_like(xb), xb]).T * w[:, None]
    (a, b), *_ = np.linalg.lstsq(A, yb * w, rcond=None)
    rms = float(np.sqrt(np.average((yb - (a + b * xb)) ** 2, weights=w)))
    order = np.argsort(iqr)
    cw = np.cumsum(w[order]) / w.sum()
    scatter = float(iqr[order][np.searchsorted(cw, 0.5)] * abs(b))
    return a, b, rms, scatter


def main():
    rows = []
    for subj, pf in PAIR_FILES.items():
        pairs = [p for p in csv.DictReader(open(pf, encoding="utf-8")) if p["usable"] == "1"]
        for name in sorted({p["session"] for p in pairs}):
            s = load_session(os.path.join(SESSIONS, name))
            for p in (p for p in pairs if p["session"] == name):
                est = window_estimates(s, float(p["t_epoch_us"]))
                est.update(subj=subj, session=name, t=float(p["t_epoch_us"]),
                           ref=float(p["ref_spo2"]), lib=float(p["r_med"]))
                rows.append(est)
            print(f"{name}: done")
    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(),
                                 df["ref"].to_numpy())
    st = df[df["stat"]]

    lines = [f"usable pairs {len(df)}  stationary {len(st)} "
             f"(SUBJ08 {int((st.subj == 'SUBJ08').sum())}, SUBJ09 {int((st.subj == 'SUBJ09').sum())}); "
             f"window {WINDOW_S:.0f} s, band-pass {BP_HZ[0]}-{BP_HZ[1]} Hz",
             f"median r2 of the red-IR cloud: {st['r2'].median():.3f} "
             f"(p10 {st['r2'].quantile(0.1):.3f}); r2 >= {R2_GATE}: "
             f"{(st['r2'] >= R2_GATE).mean():.0%} of stationary pairs",
             f"median R lib vs rms_raw (sanity): {st['lib'].median():.3f} vs {st['rms_raw'].median():.3f}",
             "",
             f"{'method':9s} {'medR':>6s} {'rho08':>6s} {'rho09':>6s} {'rhoAll':>6s} "
             f"{'pooled fit':>17s} {'RMSbin':>6s} {'scatter':>7s} {'|res|':>5s} "
             f"{'fit SUBJ08':>17s} {'fit SUBJ09':>17s}"]

    def report(sub, label_suffix=""):
        for m in METHODS:
            r, y = sub[m].to_numpy(), sub["ref"].to_numpy()
            rho = {g: spearmanr(sub[sub.subj == g][m], sub[sub.subj == g]["ref"],
                                nan_policy="omit")[0] for g in ("SUBJ08", "SUBJ09")}
            rho_all = spearmanr(r, y, nan_policy="omit")[0]
            a, b, rms, scat = binfit(r, y)
            res = np.nanmedian(np.abs(y - (a + b * r)))
            fits = []
            for g in ("SUBJ08", "SUBJ09"):
                gg = sub[sub.subj == g]
                ga, gb, *_ = binfit(gg[m].to_numpy(), gg["ref"].to_numpy())
                fits.append(f"{ga:7.2f} {gb:+7.2f}R")
            lines.append(
                f"{m + label_suffix:9s} {np.nanmedian(r):6.3f} {rho['SUBJ08']:+6.2f} "
                f"{rho['SUBJ09']:+6.2f} {rho_all:+6.2f} {a:7.2f} {b:+7.2f}R  {rms:6.2f} "
                f"{scat:7.2f} {res:5.2f} {fits[0]:>17s} {fits[1]:>17s}")

    report(st)
    gated = st[st["r2"] >= R2_GATE]
    lines += ["", f"--- quality-gated: r2 >= {R2_GATE} ({len(gated)} pairs) ---"]
    report(gated)
    clean = st[st["full_on"]]
    lines += ["", f"--- probe-on for the whole window ({len(clean)} pairs) ---"]
    report(clean)

    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "r_regression_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 3, figsize=(15, 9), sharey=True)
    for ax, m in zip(axs.flat, METHODS):
        for g, c in (("SUBJ08", "tab:blue"), ("SUBJ09", "tab:orange")):
            gg = st[st.subj == g]
            ax.scatter(gg[m], gg["ref"], s=4, alpha=0.3, c=c, label=g)
        a, b, rms, scat = binfit(st[m].to_numpy(), st["ref"].to_numpy())
        rx = np.linspace(np.nanpercentile(st[m], 1), np.nanpercentile(st[m], 99), 50)
        ax.plot(rx, a + b * rx, "k-", lw=1)
        ax.set_title(f"{m}: SpO2 = {a:.1f} {b:+.1f} R, scatter {scat:.1f} pts")
        ax.set_xlabel("R")
        ax.grid(True, alpha=0.3)
    axs[0, 0].set_ylabel("reference SpO2 [%]")
    axs[1, 0].set_ylabel("reference SpO2 [%]")
    axs[0, 0].legend(markerscale=4)
    fig.suptitle("20260923_HOSPNAV SUBJ08+SUBJ09: R estimators vs reference (stationary pairs, 8 s windows)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "r_regression_scatter.png"), dpi=120)


if __name__ == "__main__":
    main()
