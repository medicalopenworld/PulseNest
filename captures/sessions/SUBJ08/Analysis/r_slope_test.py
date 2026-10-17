"""Step 1d of the R-method plan: why does the R-curve slope go from ~21.5 (lib R-METHOD-1) to ~38
(band-passed R)?

SpO2 = a - b*R: a smaller b means R moves MORE per SpO2 point, i.e. the lib's R spans a wider range.
Hypothesis: power outside the pulse band (0.5-5 Hz) inflates the RMS ratio, and does so more at low
SpO2 (e.g. motion coinciding with desaturations). Per pair, over the same 8 s window of OT samples,
the AC power of each channel (normalised by its DC) is split by FFT into three bands:

    lo   0 < f < 0.5 Hz   baseline wander, motion, vasomotion
    in   0.5 - 5 Hz       pulse band
    hi   f > 5 Hz         electronic / quantisation noise, fast artefacts

    R_in  = sqrt(P_in_red / P_in_ir)                       ~ rms_bp
    R_all = sqrt(P_all_red / P_all_ir)                     ~ rms_raw (window analogue of the lib)
    F     = R_all / R_in = sqrt((1 + q_red) / (1 + q_ir)),  q = (P_lo + P_hi) / P_in
    F_lo, F_hi: the same with only the lo (or only the hi) band added back

If the slope change comes from out-of-band power, R_in * F_lo (or * F_hi) should reproduce the lib's
slope, and F should grow as the reference SpO2 falls. Same stationary pairs and fit as
r_regression_test.py. Output: r_slope_summary.txt
"""

import csv
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from r_regression_test import (FS_HZ, PAIR_FILES, SESSIONS, WINDOW_S, binfit, load_session,
                               stationary_mask)

HERE = os.path.dirname(os.path.abspath(__file__))
LO_HZ, HI_HZ = 0.5, 5.0


def band_powers(v):
    """Mean-square of v/mean(v) - 1 in the lo / in / hi bands (Hann-windowed periodogram, scaled
    so that the three bands add up to the variance: Parseval, one-sided)."""
    dc = v.mean()
    x = v / dc - 1.0
    w = np.hanning(len(x))
    spec = 2.0 * np.abs(np.fft.rfft((x - x.mean()) * w)) ** 2 / (len(x) * np.dot(w, w))
    f = np.fft.rfftfreq(len(x), 1.0 / FS_HZ)
    lo = spec[(f > 0) & (f < LO_HZ)].sum()
    inb = spec[(f >= LO_HZ) & (f <= HI_HZ)].sum()
    hi = spec[f > HI_HZ].sum()
    return lo, inb, hi


def main():
    pairs = {}
    for subj, pf in PAIR_FILES.items():
        for p in csv.DictReader(open(pf, encoding="utf-8")):
            if p["usable"] == "1":
                pairs.setdefault(p["session"], []).append((subj, p))
    rows = []
    for name, plist in sorted(pairs.items()):
        s = load_session(os.path.join(SESSIONS, name))
        for subj, p in plist:
            t1 = float(p["t_epoch_us"])
            i0 = np.searchsorted(s["t"], t1 - WINDOW_S * 1e6, side="right")
            i1 = np.searchsorted(s["t"], t1, side="right")
            if i1 - i0 < 1000 or s["ir"][i0:i1].mean() <= 0 or s["red"][i0:i1].mean() <= 0:
                continue
            lo_i, in_i, hi_i = band_powers(s["ir"][i0:i1])
            lo_r, in_r, hi_r = band_powers(s["red"][i0:i1])
            r_in = np.sqrt(in_r / in_i)
            rows.append({
                "subj": subj, "session": name, "t": t1, "ref": float(p["ref_spo2"]),
                "lib": float(p["r_med"]), "R_in": r_in,
                "R_all": np.sqrt((lo_r + in_r + hi_r) / (lo_i + in_i + hi_i)),
                "R_in_lo": np.sqrt((lo_r + in_r) / (lo_i + in_i)),
                "R_in_hi": np.sqrt((in_r + hi_r) / (in_i + hi_i)),
                "qlo_ir": lo_i / in_i, "qlo_red": lo_r / in_r,
                "qhi_ir": hi_i / in_i, "qhi_red": hi_r / in_r,
                "pi_in_ir": np.sqrt(in_i), "pi_in_red": np.sqrt(in_r),
            })
        print(f"{name}: {len(plist)} pairs")
    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(), df["ref"].to_numpy())
    st = df[df["stat"]].copy()
    st["F"] = st["R_all"] / st["R_in"]
    st["F_lo"] = st["R_in_lo"] / st["R_in"]
    st["F_hi"] = st["R_in_hi"] / st["R_in"]
    st["F_lib"] = st["lib"] / st["R_in"]

    lines = [f"stationary pairs {len(st)}; window {WINDOW_S:.0f} s; bands lo <{LO_HZ} Hz, "
             f"in {LO_HZ}-{HI_HZ} Hz, hi >{HI_HZ} Hz", "",
             "1) Slope of each R (pooled weighted bin fit, as r_regression_test.py)",
             f"{'R':9s} {'medR':>6s} {'rho':>6s} {'pooled fit':>17s} {'scatter':>7s}"]
    for col, lab in (("lib", "lib"), ("R_all", "R_all"), ("R_in_lo", "R_in+lo"),
                     ("R_in_hi", "R_in+hi"), ("R_in", "R_in")):
        a, b, rms, scat = binfit(st[col].to_numpy(), st["ref"].to_numpy())
        rho = spearmanr(st[col], st["ref"])[0]
        lines.append(f"{lab:9s} {st[col].median():6.3f} {rho:+6.2f} {a:7.2f} {b:+7.2f}R  {scat:7.2f}")

    lines += ["", "2) Inflation factors vs reference SpO2 (Spearman rho; negative = larger at low SpO2)",
              f"{'factor':8s} {'median':>7s} {'rho all':>8s} {'rho 08':>7s} {'rho 09':>7s}"]
    for col in ("F_lib", "F", "F_lo", "F_hi"):
        r = {g: spearmanr(st[st.subj == g][col], st[st.subj == g]["ref"])[0] for g in ("SUBJ08", "SUBJ09")}
        lines.append(f"{col:8s} {st[col].median():7.3f} {spearmanr(st[col], st['ref'])[0]:+8.2f} "
                     f"{r['SUBJ08']:+7.2f} {r['SUBJ09']:+7.2f}")

    lines += ["", "3) Out-of-band power / in-band power per channel, by reference SpO2 bin (medians)",
              f"{'SpO2':>5s} {'n':>5s} {'qlo_ir':>7s} {'qlo_red':>8s} {'qhi_ir':>7s} {'qhi_red':>8s} "
              f"{'F_lo':>6s} {'F_hi':>6s} {'F_lib':>6s} {'PIin_ir%':>8s}"]
    st["bin"] = (np.floor(st["ref"] / 2) * 2).astype(int)
    for k, g in st.groupby("bin"):
        if len(g) < 20:
            continue
        lines.append(f"{k:3d}-{k + 1:<2d}{len(g):5d} {g.qlo_ir.median():7.3f} {g.qlo_red.median():8.3f} "
                     f"{g.qhi_ir.median():7.4f} {g.qhi_red.median():8.4f} {g.F_lo.median():6.3f} "
                     f"{g.F_hi.median():6.3f} {g.F_lib.median():6.3f} {100 * g.pi_in_ir.median():8.3f}")
    lines += ["", "4) Same factors vs reference SpO2, Spearman rho of the raw quantities",
              "   " + "  ".join(f"{c} {spearmanr(st[c], st['ref'])[0]:+.2f}"
                                for c in ("qlo_ir", "qlo_red", "qhi_ir", "qhi_red", "pi_in_ir"))]

    lines += ["", "5) Per integer SpO2 bin (>= 10 pairs, the bins binfit uses): median R and who is in it",
              f"{'SpO2':>4s} {'n':>5s} {'%08':>4s} {'R_in':>6s} {'R_in+lo':>7s} {'lib':>6s} "
              f"{'ratio lo':>8s} {'ratio lib':>9s} {'qlo_red':>7s} {'qlo_ir':>6s}"]
    for k, g in st.groupby(np.round(st["ref"]).astype(int)):
        if len(g) < 10:
            continue
        lines.append(f"{k:4d} {len(g):5d} {100 * (g.subj == 'SUBJ08').mean():4.0f} {g.R_in.median():6.3f} "
                     f"{g.R_in_lo.median():7.3f} {g.lib.median():6.3f} "
                     f"{g.R_in_lo.median() / g.R_in.median():8.3f} {g.lib.median() / g.R_in.median():9.3f} "
                     f"{g.qlo_red.median():7.3f} {g.qlo_ir.median():6.3f}")
    lines += ["", "6) Per subject: slope of each R (own bins)"]
    for subj in ("SUBJ08", "SUBJ09"):
        g = st[st.subj == subj]
        fits = []
        for col in ("R_in", "R_in_lo", "lib"):
            a, b, *_ = binfit(g[col].to_numpy(), g["ref"].to_numpy())
            fits.append(f"{col} {a:7.2f} {b:+7.2f}R")
        lines.append(f"   {subj} (n {len(g)}, ref {g.ref.min():.0f}-{g.ref.max():.0f}): " + " | ".join(fits))

    # 7) binfit regresses SpO2 on the bin-median R, so bin-to-bin noise in R (an error in x) flattens
    # the slope (regression dilution). The inverse fit (bin-median R on SpO2, then b = -1/d) is not
    # attenuated by errors in R; if the two disagree, the difference is dilution.
    lines += ["", "7) Direct vs inverse fit (pooled, same bins): b_direct from SpO2-on-R, b_inverse = 1/|d| "
              "from R-on-SpO2", f"{'R':9s} {'b_direct':>8s} {'b_inverse':>9s} {'r(bins)':>7s}"]
    keys = [k for k in np.unique(np.round(st["ref"])) if (np.round(st["ref"]) == k).sum() >= 10]
    yb = np.array(keys, float)
    w = np.array([(np.round(st["ref"]) == k).sum() for k in keys], float)
    for col in ("lib", "R_in_lo", "R_in"):
        xb = np.array([st[col][np.round(st["ref"]) == k].median() for k in keys])
        d = np.polyfit(yb, xb, 1, w=np.sqrt(w))[0]
        b_dir = -np.polyfit(xb, yb, 1, w=np.sqrt(w))[0]
        r = np.corrcoef(xb, yb)[0, 1]
        lines.append(f"{col:9s} {b_dir:8.2f} {1 / abs(d):9.2f} {r:+7.2f}")

    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "r_slope_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
