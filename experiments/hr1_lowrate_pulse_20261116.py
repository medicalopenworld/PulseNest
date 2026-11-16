"""What a real PPG pulse looks like at a very low heart rate (2026-11-16, Alex's request).

Why this exists
---------------
Part 2 of the family-1 study (docs/hr1_methods_20261116.md) excluded every HR1_SSF configuration because
all of them read 60 on the MS100's 30 bpm plateau. Alex then looked at that plateau: its dicrotic wave
is so marked it looks like a systolic pulse. Measured the same day: the MS100 stretches one template
with the RR (in time / RR its eight plateaus coincide; the second wave sits at 31 % of the cycle, 0.66 s
after the peak at 30 bpm, with an upstroke of its own). Physiology says the dicrotic notch ends the
ejection, which shortens only ~1.6-1.7 ms per bpm (Weissler's index), so a real pulse at 30 bpm should
keep its notch near 0.3-0.4 s after the onset and then decay. The MIMIC PERform neonates do not go below
87 bpm. This script looks at real pulses below 40-50 bpm.

Data
----
PhysioNet/CinC Challenge 2015, "Reducing false arrhythmia alarms in the ICU" (training set, 750 adult ICU
records of 5 min, two ECG leads and a PPG and/or ABP at 250 Hz; ODC-By; downloaded 2026-11-16 with Alex's
go to C:/PRJ/MOW/datasets/physionet_challenge2015/, outside any repository). Bradycardia alarm = HR below
40 bpm for 5 consecutive beats; the alarm sounds at 5:00. Used here: the records whose bradycardia alarm
is TRUE (file ALARMS) and that carry a PLETH channel.

Method (fixed before looking at the pulses)
-------------------------------------------
- ECG beats: the two QRS detectors of pulsenest/hr1_bench.py on the first ECG lead, kept where they agree
  within 150 ms; each beat's RR from the next agreed beat.
- PPG beat i: from the PPG foot after R_i (minimum of the PPG between R_i and R_i + 0.6 x RR_i) to the
  foot after R_{i+1}; zero-phase low-pass 10 Hz; amplitude normalised (foot 0, maximum 1).
- Classes per beat by its ECG RR: slow (RR > 1.5 s, < 40 bpm), low (1.0-1.5 s, 40-60 bpm), baseline
  (0.6-1.0 s, 60-100 bpm), the same patients.
- Per beat: time of the systolic peak from the foot; the dicrotic notch = the first local minimum of the
  downslope after the peak with a later local maximum (diastolic wave) at least 0.02 above it; the
  diastolic wave's time and height; and whether a second upstroke as tall as half the pulse appears
  more than 0.6 s after the foot (what the MS100 makes at 30 bpm).

Added after the first look at the beats (2026-11-16, before any conclusion): in the slow ECG intervals the
PPG sometimes beats twice (a full second pulse: ECG beats missed by both QRS detectors, or ectopy), which
the first statistics counted as "second upstrokes". So the shape is read on the CONCORDANT slow beats
only (one PPG peak of prominence >= 0.5 per slow ECG interval), and a measure of what a slope-sum
detector reacts to is added: the largest slope sum (positive slopes over 0.17 s) after the systolic
peak + 0.15 s, over the main upstroke's.

Result (2026-11-16): 46 true bradycardia alarms, 39 with PPG and slow ECG beats. CONCORDANT slow beats:
641 from 30 records, RR median 1.62 s (~37 bpm): a single hump, foot -> peak median 0.31 s, back to
baseline by ~1.1 s, then flat; a second upstroke of half the pulse in 1.2 % of them; secondary slope-sum
ratio median 0.020 (90th percentile 0.083). The MS100 at 30 bpm: 0.182 (60 bpm 0.103, 120 bpm 0.135),
with its second wave 0.66 s after the peak, out of a 0.34 s eye-closing: its 30 bpm pulse is not what a
real slow pulse looks like (adults in an ICU; no neonatal data below 87 bpm was found).

    python experiments/hr1_lowrate_pulse_20261116.py [--data DIR] [--out DIR]

Outputs in --out (default captures/sessions/HR1_LOWRATE_PULSE_20261116/, not versioned): beats.csv,
summary.txt, one PNG per record (slow, low and baseline beats on an absolute time axis).
"""
import argparse
import csv
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr1_bench as h1          # noqa: E402

DATA = r"C:\PRJ\MOW\datasets\physionet_challenge2015\training"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "sessions",
                   "HR1_LOWRATE_PULSE_20261116")
CLASSES = (("slow (<40 bpm)", 1.5, 99.0), ("low (40-60 bpm)", 1.0, 1.5), ("baseline (60-100 bpm)", 0.6, 1.0))


def read_wfdb(base):
    """WFDB record with a MATLAB v4 .mat signal file: (fs, {description: physical signal})."""
    from scipy.io import loadmat
    with open(base + ".hea", encoding="utf-8", errors="replace") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    head = lines[0].split()
    nsig, fs = int(head[1]), float(head[2].split("/")[0])
    val = loadmat(base + ".mat")["val"].astype(float)
    sigs = {}
    for k, ln in enumerate(lines[1:1 + nsig]):
        p = ln.split()
        gain_field = p[2]
        g = gain_field.split("/")[0]
        if "(" in g:
            gain, base_v = float(g.split("(")[0]), float(g.split("(")[1].rstrip(")"))
        else:
            gain, base_v = float(g), float(p[4]) if len(p) > 4 else 0.0
        gain = gain if gain != 0 else 200.0
        desc = " ".join(p[8:]) if len(p) > 8 else f"sig{k}"
        sigs[desc] = (val[k] - base_v) / gain
    return fs, sigs


def true_bradycardia(data_dir):
    out = []
    with open(os.path.join(data_dir, "ALARMS"), encoding="utf-8") as f:
        for ln in f:
            p = [x.strip() for x in ln.split(",")]
            if len(p) >= 3 and p[1].lower().startswith("brady") and p[2] == "1":
                out.append(p[0])
    return out


def beat_features(s, fs):
    """Systolic peak time, dicrotic notch / diastolic wave (time, height), second upstroke flag."""
    from scipy.signal import find_peaks
    k = int(np.argmax(s))
    feat = {"t_peak": k / fs, "t_notch": math.nan, "t_diast": math.nan, "h_diast": math.nan,
            "second_upstroke": False}
    after = s[k:]
    mins, _ = find_peaks(-after)
    for m in mins:
        rest = after[m:]
        mx, _ = find_peaks(rest)
        if len(mx) and rest[mx[0]] - after[m] >= 0.02:
            feat["t_notch"] = (k + m) / fs
            feat["t_diast"] = (k + m + mx[0]) / fs
            feat["h_diast"] = float(rest[mx[0]])
            break
    late = np.arange(len(s)) / fs > 0.6
    if late.any():
        sl = s[late]
        rise = sl - np.minimum.accumulate(sl)
        feat["second_upstroke"] = bool(rise.max() >= 0.5)
    return feat


def slope_sum(s, fs, w_s=0.17):
    """qppg's slope sum (positive slopes over w_s) of a normalised beat."""
    dy = np.maximum(np.diff(s, prepend=s[0]), 0.0)
    w = max(1, int(round(w_s * fs)))
    return np.convolve(dy, np.ones(w))[:len(dy)]


def secondary_ratio(s, fs):
    """Largest slope sum after the systolic peak + 0.15 s, over the main upstroke's: what makes a
    slope-sum detector count a second beat."""
    ss = slope_sum(s, fs)
    k = int(np.argmax(s))
    main_up = ss[:k + 1].max() if k > 0 else ss.max()
    late = ss[k + int(0.15 * fs):]
    return float(late.max() / main_up) if len(late) and main_up > 0 else 0.0


def concordant_slow_beats(y, r, fs):
    """Slow ECG intervals (RR > 1.5 s) in which the PPG beats once: one PPG peak of prominence >= 0.5 of
    the local pulse amplitude between R_i + 0.1 s and R_(i+1) + 0.1 s. Returns the beats from the foot
    before that peak to the foot before the next interval's peak, normalised."""
    from scipy.signal import find_peaks
    rng = np.percentile(y, 99) - np.percentile(y, 1)
    pk, _ = find_peaks(y, prominence=0.5 * rng, distance=int(0.25 * fs))
    out = []
    for i in range(len(r) - 2):
        rr = r[i + 1] - r[i]
        if rr <= 1.5:
            continue
        lo, hi = r[i] + 0.1, r[i + 1] + 0.1
        p_in = pk[(pk >= lo * fs) & (pk < hi * fs)]
        p_nx = pk[(pk >= hi * fs) & (pk < (r[i + 2] + 0.1) * fs)]
        if len(p_in) != 1 or len(p_nx) != 1:
            continue
        a = max(0, p_in[0] - int(0.5 * fs)); f0 = a + int(np.argmin(y[a:p_in[0]]))
        b = max(0, p_nx[0] - int(0.5 * fs)); f1 = b + int(np.argmin(y[b:p_nx[0]]))
        s = y[f0:f1 + 1]
        if len(s) < int(0.5 * fs) or s.max() <= s[0]:
            continue
        out.append(((s - s[0]) / (s.max() - s[0]), rr))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    from scipy.signal import butter, sosfiltfilt
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    recs = true_bradycardia(args.data)
    rows, used, conc, conc_segs = [], [], [], []
    for name in recs:
        fs, sigs = read_wfdb(os.path.join(args.data, name))
        pleth = next((v for k, v in sigs.items() if "PLETH" in k.upper()), None)
        ecg_key = next((k for k in sigs if k.upper() in ("II", "I", "III", "V", "AVR", "AVL", "AVF", "MCL")), None)
        if pleth is None or ecg_key is None:
            continue
        ecg = np.nan_to_num(sigs[ecg_key]); ppg = np.nan_to_num(pleth)
        a = h1.qrs_pan_tompkins(ecg, fs) / fs
        b = h1.qrs_envelope(ecg, fs) / fs
        ia, _, _, _ = h1._pair(a, b, 0.15)
        r = a[ia]
        if len(r) < 10:
            continue
        y = sosfiltfilt(butter(4, 10.0, fs=fs, output="sos"), ppg)
        segs = {c[0]: [] for c in CLASSES}
        for i in range(len(r) - 2):
            rr = r[i + 1] - r[i]
            cls = next((c[0] for c in CLASSES if c[1] <= rr < c[2]), None)
            if cls is None:
                continue
            i0, i1 = int(r[i] * fs), int((r[i] + 0.6 * rr) * fs)
            j0, j1 = int(r[i + 1] * fs), int((r[i + 1] + 0.6 * (r[i + 2] - r[i + 1])) * fs)
            if i1 >= len(y) or j1 >= len(y) or i1 <= i0 or j1 <= j0:
                continue
            f0 = i0 + int(np.argmin(y[i0:i1])); f1 = j0 + int(np.argmin(y[j0:j1]))
            s = y[f0:f1 + 1]
            if len(s) < int(0.3 * fs) or s.max() - s.min() <= 0:
                continue
            s = (s - s[0]) / (s.max() - s[0]) if s.max() > s[0] else s * 0
            feat = beat_features(s, fs)
            rows.append({"record": name, "class": cls, "rr_s": rr, **feat})
            segs[cls].append(s)
        if any(len(v) for k, v in segs.items() if k.startswith("slow")):
            used.append(name)
            fig, ax = plt.subplots(figsize=(10, 4))
            for cls, col in zip([c[0] for c in CLASSES], ("tab:red", "tab:orange", "tab:blue")):
                for s in segs[cls][:12]:
                    ax.plot(np.arange(len(s)) / fs, s, color=col, alpha=0.35, lw=0.8)
                ax.plot([], [], color=col, label=f"{cls} ({len(segs[cls])} beats)")
            ax.set_xlabel("s from the PPG foot"); ax.set_ylabel("normalised PPG"); ax.grid(alpha=0.3)
            ax.legend(fontsize=8); ax.set_title(f"{name}: real PPG beats by ECG rate (PhysioNet 2015, true bradycardia)")
            fig.tight_layout(); fig.savefig(os.path.join(args.out, f"{name}_beats.png"), dpi=90); plt.close(fig)
        # concordant slow beats: the PPG beats once per slow ECG interval
        for s, rr in concordant_slow_beats(y, r, fs):
            conc.append({"record": name, "rr_s": rr, "secondary_ratio": secondary_ratio(s, fs),
                         **beat_features(s, fs)})
            conc_segs.append(s)
    if not rows:
        print("no beats"); return
    with open(os.path.join(args.out, "beats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    lines = [f"true bradycardia records: {len(recs)}; with PLETH and ECG beats in the slow class: {len(used)} {used}"]
    for cls, _, _ in CLASSES:
        R = [r_ for r_ in rows if r_["class"] == cls]
        if not R:
            continue
        tp = np.array([r_["t_peak"] for r_ in R]); tn = np.array([r_["t_notch"] for r_ in R])
        td = np.array([r_["t_diast"] for r_ in R]); hd = np.array([r_["h_diast"] for r_ in R])
        su = np.array([r_["second_upstroke"] for r_ in R])
        rr = np.array([r_["rr_s"] for r_ in R])
        lines.append(f"{cls}: {len(R)} beats from {len(set(r_['record'] for r_ in R))} records, RR median {np.median(rr):.2f} s; "
                     f"foot->peak median {np.median(tp):.3f} s; notch found in {100 * np.mean(np.isfinite(tn)):.0f} %, "
                     f"at {np.nanmedian(tn):.3f} s (IQR {np.nanpercentile(tn, 25):.3f}-{np.nanpercentile(tn, 75):.3f}); "
                     f"diastolic wave at {np.nanmedian(td):.3f} s, height {np.nanmedian(hd):.2f}; "
                     f"second upstroke >= 0.5 after 0.6 s in {100 * su.mean():.1f} %")
    if conc:
        sr = np.array([c["secondary_ratio"] for c in conc]); su = np.array([c["second_upstroke"] for c in conc])
        tn = np.array([c["t_notch"] for c in conc]); tp = np.array([c["t_peak"] for c in conc])
        lines.append(f"CONCORDANT slow beats (the PPG beats once per slow ECG interval): {len(conc)} from "
                     f"{len(set(c['record'] for c in conc))} records, RR median {np.median([c['rr_s'] for c in conc]):.2f} s; "
                     f"foot->peak median {np.median(tp):.3f} s; notch found in {100 * np.mean(np.isfinite(tn)):.0f} %; "
                     f"second upstroke >= 0.5 in {100 * su.mean():.1f} %; secondary slope-sum ratio median "
                     f"{np.median(sr):.3f}, 90th percentile {np.percentile(sr, 90):.3f}, max {sr.max():.3f}")
        with open(os.path.join(args.out, "concordant_slow_beats.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(conc[0])); w.writeheader(); w.writerows(conc)
        L = int(np.median([len(s) for s in conc_segs]))
        M = np.full((len(conc_segs), L), np.nan)
        for i, s in enumerate(conc_segs):
            M[i, :min(L, len(s))] = s[:L]
        fig, ax = plt.subplots(figsize=(10, 4))
        for s in conc_segs[::max(1, len(conc_segs) // 40)]:
            ax.plot(np.arange(len(s)) / fs, s, color="tab:red", alpha=0.15, lw=0.8)
        ax.plot(np.arange(L) / fs, np.nanmedian(M, axis=0), color="k", lw=2,
                label=f"median of {len(conc_segs)} concordant beats < 40 bpm")
        ax.set_xlabel("s from the PPG foot"); ax.set_ylabel("normalised PPG"); ax.grid(alpha=0.3); ax.legend()
        ax.set_title("Real PPG pulses below 40 bpm (PhysioNet 2015, true bradycardia, PPG and ECG concordant)")
        fig.tight_layout(); fig.savefig(os.path.join(args.out, "concordant_slow_beats.png"), dpi=90); plt.close(fig)
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
