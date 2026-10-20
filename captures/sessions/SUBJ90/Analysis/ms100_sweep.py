"""MS100 sweep (SUBJ90): plateaus taken from the VideoNest OCR of the simulator screen (the keyboard
REF_SPO2 events lagged the screen by 6-27 s). Rows mapped to epoch time through the `# @row N clock`
anchors. Each plateau drops its first SKIP_S seconds, then medians."""
import glob
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

S, OUT = sys.argv[1], sys.argv[2]
SKIP_S, FS, MIN_RUN_S = 10.0, 500.0, 5.0
parts = sorted(glob.glob(S + "/*_p[0-9][0-9].csv"))
frames, anchors, offset = [], [], 0
for p in parts:
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                continue
            m = re.search(r"@row (\d+) clock: .*host_epoch_us=(\d+)", line)
            if m:
                anchors.append((offset + int(m.group(1)), int(m.group(2))))
    df = pd.read_csv(p, comment="#")
    frames.append(df)
    offset += len(df)
df = pd.concat(frames, ignore_index=True)
arow, aep = np.array([a[0] for a in anchors]), np.array([a[1] for a in anchors], dtype=float)

ref = pd.read_csv(S + "/reference_spo2.csv", comment="#")
ref = ref[(ref.source == "videonest") & (ref.conf >= 0.9)].sort_values("t_epoch_us")
# runs of equal OCR value
runs = []
for _, r in ref.iterrows():
    if runs and runs[-1]["v"] == r.spo2:
        runs[-1]["t1"] = r.t_epoch_us
    else:
        runs.append({"v": int(r.spo2), "t0": r.t_epoch_us, "t1": r.t_epoch_us})
runs = [r for r in runs if (r["t1"] - r["t0"]) / 1e6 >= MIN_RUN_S]
# a run ends where the next one starts
for i in range(len(runs) - 1):
    runs[i]["t1"] = runs[i + 1]["t0"]
cols = ["R", "SpO2", "HR3", "PI", "R_CORR"]
rows = []
for r in runs:
    r0 = int(np.interp(r["t0"], aep, arow)) + int(SKIP_S * FS)
    r1 = int(np.interp(r["t1"], aep, arow))
    seg = df.iloc[r0:r1]
    if len(seg) < 5 * FS:
        continue
    valid = seg[seg.SpO2 >= 0]
    med = seg[cols].median()
    rows.append(dict(ref=r["v"], t=pd.Timestamp(r["t0"], unit="us", tz="Europe/Madrid").strftime("%H:%M:%S"),
                     n_s=round(len(seg) / FS, 1), R=round(med.R, 4), R_sd=round(seg.R.std(), 4),
                     SpO2=round(valid.SpO2.median(), 2) if len(valid) else np.nan,
                     inval=round(1 - len(valid) / len(seg), 2), HR3=round(med.HR3, 1), PI=round(med.PI, 2),
                     r=round(med.R_CORR, 4)))
t = pd.DataFrame(rows)
t["bias"] = (t.SpO2 - t.ref).round(2)
t["hr"] = (t.HR3 / 5).round() * 5
pd.set_option("display.width", 250)
print(t.to_string(index=False))
fits = {}
for g, sub in t.groupby("hr"):
    if len(sub) >= 3:
        b, a = np.polyfit(sub.R, sub.ref, 1)
        res = sub.ref - (a + b * sub.R)
        fits[g] = (a, b)
        print(f"HR {g:.0f}: ref = {a:.2f} {b:+.2f}*R   n={len(sub)}  rms={np.sqrt((res**2).mean()):.2f}")
b, a = np.polyfit(t.R, t.ref, 1)
res = t.ref - (a + b * t.R)
print(f"ALL:    ref = {a:.2f} {b:+.2f}*R   n={len(t)}  rms={np.sqrt((res**2).mean()):.2f}")
same = t.groupby(["ref", "hr"]).R.median().unstack()
print("\nR by setpoint x HR:\n", same.round(3).to_string())
t.to_csv(OUT + "/ms100_plateaus_ocr.csv", index=False)

fig, ax = plt.subplots(1, 2, figsize=(12, 5))
for g, sub in t.groupby("hr"):
    ax[0].plot(sub.R, sub.ref, "o", label=f"HR {g:.0f}")
    if g in fits:
        xx = np.linspace(0.45, 1.25, 10)
        ax[0].plot(xx, fits[g][0] + fits[g][1] * xx, "-", lw=0.8)
xx = np.linspace(0.45, 1.25, 10)
ax[0].plot(xx, 123.98 - 39.13 * xx, "k--", label="R-CURVE-STS0163-HOSPNAV (lib)")
ax[0].plot(xx, 114.92 - 30.55 * xx, "k:", label="R-CURVE-U401D-MS100-20260323")
ax[0].set_xlabel("R (R-METHOD-2)"); ax[0].set_ylabel("MS100 setpoint SpO2 [%]"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
for g, sub in t.groupby("hr"):
    ax[1].plot(sub.ref, sub.bias, "o-", label=f"HR {g:.0f}")
ax[1].axhline(0, color="k", lw=0.5); ax[1].set_xlabel("MS100 setpoint [%]"); ax[1].set_ylabel("lib SpO2 - setpoint [pt]"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
fig.suptitle("SUBJ90 2026-10-19: MS100 sweep, Pulse Amp 3 %, TLC 3500, Nellcor R-curve; Medle ST-S0163-26, 49.8 mA")
fig.tight_layout(); fig.savefig(OUT + "/ms100_sweep.png", dpi=110)
