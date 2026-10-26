"""R vs displayed SpO2, every stationary pair of every data set with a usable range (2026-10-26).

Asked by Alex on 2026-10-26 after the "one curve or two?" analysis (library rationale section 18): the
per-bin median table needs the (a, b) of each column, and a scatter of every (R, SpO2) pair analysed,
one colour per campaign.

Data sets (same probe model, Medle ST-S0163; library R-METHOD-2; 8 s windows; stationary = reference
moving <= 2 pt within +/-10 s, as in every fit of the register):
    SUBJ08, SUBJ09   neonatal feet, Mindray N17 reference, lib v0.100 replay (fit base of the shipped curve)
    SUBJ11           30-week preterm, Mindray N17, live firmware columns (BIAS_ANALYSIS_SUBJ10_SUBJ11)
    SUBJ01 18-oct    adult finger, home fingertip oximeter (SUBJ01_BIAS_ANALYSIS/pairs.csv)
    SUBJ01 23-oct    adult finger, three probes, home oximeter (SUBJ01_BIAS_ANALYSIS/20261023/pairs.csv)
    SUBJ90           CONTEC MS100 simulator, "R-Curve Nellcor" table (SUBJ90/Analysis/plateaus.csv)

Per data set: n, reference range, bin fit SpO2 = a - b*R (weighted LS on per-bin median R, bins = integer
reference SpO2 with >= 10 pairs, the register's method), and the intercept at the shared slope 39.13
(median over pairs of ref + 39.13*R), whose difference to 123.98 is the offset in SpO2 points.

Result (2026-10-26): table in docs/spo2_r_curves.md ("(a, b) per data set", 2026-10-26) and the figure
docs/spo2_r_curves_scatter_20261026.png. The script reproduces the register's fits (pooled 123.98 - 39.13,
SUBJ08 129.22 - 46.70, SUBJ09 118.84 - 32.11, MS100 121.06 - 39.11). Intercept at the shared slope 39.13:
neonatal feet 123.6-124.5 (within 0.5 pt of the shipped curve, SUBJ11 included); adult finger 120.5-120.8
(-3.2 / -3.5 pt); simulator Nellcor table 121.1 (-2.9 pt). The per-level offset grows from 0.05 in R at 94 %
to 0.09-0.10 at 99 % (2 to 4 pt), so "2.7 pt" is the mean over levels and 3.2-3.5 the mean over pairs.

Outputs: docs/spo2_r_curves_scatter_20261026.png and the table on stdout.
"""
import csv
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS = os.path.join(ROOT, "captures", "sessions")
sys.path.insert(0, os.path.join(SESSIONS, "SUBJ08", "Analysis"))
import fit_method2 as fm  # noqa: E402  (SUBJ08/Analysis: loaders of the shipped curve's fit)
from r_regression_test import PAIR_FILES, binfit, stationary_mask  # noqa: E402

PAIR_FILES["SUBJ09"] = os.path.join(SESSIONS, "SUBJ09", "Analysis", "pairs.csv")
A_CUR, B_CUR = 123.98, 39.13          # R-CURVE-STS0163-HOSPNAV-20261004 (shipped)
A_NEL, B_NEL = 121.06, 39.11          # R-CURVE-STS0163-MS100-20261019 (MS100 "Nellcor" table)
OUT_PNG = os.path.join(ROOT, "docs", "spo2_r_curves_scatter_20261026.png")


def hospnav_pairs():
    """SUBJ08 + SUBJ09: median library R (lib v0.100 replay) over the 8 s window before each usable
    reference reading; stationary mask as in fit_method2.py."""
    rows = []
    for subj, pf in PAIR_FILES.items():
        pairs = [p for p in csv.DictReader(open(pf, encoding="utf-8")) if p["usable"] == "1"]
        for name in sorted({p["session"] for p in pairs}):
            sdir = os.path.join(SESSIONS, subj, name)
            s = fm.load_replay(sdir)
            for p in (p for p in pairs if p["session"] == name):
                R, r, _ = fm.window_median(s, float(p["t_epoch_us"]))
                rows.append(dict(subj=subj, session=name, t=float(p["t_epoch_us"]),
                                 ref=float(p["ref_spo2"]), R=R, pi=float(p.get("pi_med", "nan") or "nan")))
    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(), df["ref"].to_numpy())
    df = df[df["stat"] & np.isfinite(df["R"])]
    return {s: df[df.subj == s][["R", "ref", "pi"]].reset_index(drop=True) for s in ("SUBJ08", "SUBJ09")}


def bias_pairs(path, subject=None):
    """pairs.csv of tools/spo2_bias_analysis.py: usable + stationary rows with a finite window R."""
    df = pd.read_csv(path)
    if subject:
        df = df[df.subject == subject]
    df = df[(df.usable == 1) & (df.stationary == 1) & np.isfinite(df.r_med)]
    return df.rename(columns={"r_med": "R", "ref_spo2": "ref", "pi_med": "pi"})[["R", "ref", "pi"]].reset_index(drop=True)


def ms100_pairs():
    df = pd.read_csv(os.path.join(SESSIONS, "SUBJ90", "Analysis", "plateaus.csv"))
    return pd.DataFrame({"R": df["R"], "ref": df["ref"].astype(float), "pi": df["PI"]})


def fits(d):
    """(a, b) of SpO2 = a - b*R: the register's bin fit when there are bins of >= 10 pairs, plain OLS on
    the points otherwise (the simulator sweep: 18 plateaus); plus the intercept at the shared slope."""
    R, y = d["R"].to_numpy(float), d["ref"].to_numpy(float)
    if len(d) >= 50:
        a, slope = binfit(R, y)[:2]
    else:
        slope, a = np.polyfit(R, y, 1)
    a_fixed = float(np.median(y + B_CUR * R))
    return a, -slope, a_fixed


def bin_medians(d, min_n=10):
    g = d.groupby(d["ref"].round().astype(int))
    out = [(k, len(x), x["R"].median(), *np.percentile(x["R"], [25, 75])) for k, x in g if len(x) >= min_n]
    return pd.DataFrame(out, columns=["ref", "n", "R", "q25", "q75"])


def main():
    hv = hospnav_pairs()
    sets = [
        ("SUBJ08 neonatal foot, Mindray", hv["SUBJ08"], "#1f4e9c", "o"),
        ("SUBJ09 neonatal foot, Mindray", hv["SUBJ09"], "#4fa3e0", "o"),
        ("SUBJ11 preterm 30 wk foot, Mindray",
         bias_pairs(os.path.join(SESSIONS, "BIAS_ANALYSIS_SUBJ10_SUBJ11", "pairs.csv"), "SUBJ11"), "#7b3fb5", "o"),
        ("SUBJ01 adult finger 18-oct, home oximeter",
         bias_pairs(os.path.join(SESSIONS, "SUBJ01", "SUBJ01_BIAS_ANALYSIS", "pairs.csv")), "#f28e2b", "s"),
        ("SUBJ01 adult finger 23-oct (3 probes), home oximeter",
         bias_pairs(os.path.join(SESSIONS, "SUBJ01", "SUBJ01_BIAS_ANALYSIS", "20261023", "pairs.csv")), "#d62728", "s"),
        ("MS100 simulator, Nellcor table", ms100_pairs(), "#222222", "D"),
    ]
    table = [("SUBJ08+SUBJ09 pooled (fit base of the shipped curve)",
              pd.concat([hv["SUBJ08"], hv["SUBJ09"]], ignore_index=True))] + [(n, d) for n, d, _, _ in sets]
    print(f"{'data set':55s} {'n':>5s} {'range':>8s} {'PI%':>5s} {'a':>7s} {'b':>6s} {'a@39.13':>8s} {'offset':>7s}")
    for name, d in table:
        a, b, af = fits(d)
        print(f"{name:55s} {len(d):5d} {d.ref.min():3.0f}-{d.ref.max():3.0f} {np.nanmedian(d.pi):5.2f} "
              f"{a:7.2f} {b:6.2f} {af:8.2f} {af - A_CUR:+7.2f}")
    print("\nper-bin median R (bins with >= 10 pairs; simulator: every plateau):")
    for name, d in table:
        bm = bin_medians(d, min_n=10 if len(d) >= 50 else 1)
        print(f"  {name}: " + "  ".join(f"{int(r.ref)}:{r.R:.3f}({int(r.n)})" for r in bm.itertuples()))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7), sharey=True)
    rng = np.random.default_rng(0)
    R_line = np.linspace(0.35, 1.45, 50)
    for ax in (ax1, ax2):
        ax.plot(R_line, A_CUR - B_CUR * R_line, "k-", lw=1.6,
                label=f"shipped: {A_CUR} - {B_CUR}*R (neonatal foot, Mindray)")
        ax.plot(R_line, A_NEL - B_NEL * R_line, "k--", lw=1.3,
                label=f"MS100 Nellcor table: {A_NEL} - {B_NEL}*R")
        ax.axhline(100, color="0.7", lw=0.8)
        ax.set_xlabel("R  (R-METHOD-2, library)")
        ax.set_xlim(0.35, 1.45)
        ax.set_ylim(70, 101.5)
        ax.grid(True, alpha=0.3)
    ax1.set_ylabel("reference SpO2 shown by the monitor / oximeter / simulator [%]")
    for name, d, col, mk in sets:
        jit = 0.0 if len(d) < 50 else rng.uniform(-0.25, 0.25, len(d))
        ax1.scatter(d["R"], d["ref"] + jit, s=14 if len(d) < 50 else 6, c=col, marker=mk,
                    alpha=0.9 if len(d) < 50 else 0.35, linewidths=0, label=f"{name} (n {len(d)})")
        bm = bin_medians(d, min_n=10 if len(d) > 50 else 1)
        ax2.errorbar(bm["R"], bm["ref"], xerr=[bm["R"] - bm["q25"], bm["q75"] - bm["R"]], fmt=mk, color=col,
                     ms=7, mec="k", mew=0.6, capsize=2, lw=1, label=f"{name}")
    ax1.set_title("every stationary pair (integer reference, jitter +/-0.25 for visibility)")
    ax2.set_title("median R per reference level (bins >= 10 pairs; bars = IQR of R)")
    ax1.legend(fontsize=8, loc="lower left")
    ax2.legend(fontsize=8, loc="lower left")
    fig.suptitle("Medle ST-S0163, R-METHOD-2: R vs displayed reference SpO2, all data sets (2026-10-26)")
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=140)
    print(f"\nwrote {OUT_PNG}")


if __name__ == "__main__":
    main()
