"""Candidate artefact gates for the library's SpO2, evaluated against the ward monitor.

Why this exists
---------------
SUBJ10 (term neonate, 2026-10-13, moving) read -16 points against the Mindray N17 with R 1.1-1.2
at a reference of 97 %, and 760/907 windows passed every gate the library has (probe applied,
r >= 0.8, PI <= 20 %, 70 <= a - b*R <= 110). r stayed at 0.96: the regression of red on IR fits
motion as well as it fits a pulse. On 2026-10-16 the per-subject spectrograms showed a clean
harmonic comb in SUBJ11 and none in SUBJ10, and HR3 (FFT + HPS) was valid in 18/760 SUBJ10
windows against 1500/1664 in SUBJ11. Nellcor (US 6,083,172), Philips FAST (US 6,631,281) and
Masimo SET (Signal IQ) all tie SpO2 validity to the identification of the pulse and its harmonic
structure, not to the red-IR correlation alone. This script measures what each candidate gate
would have done, before any of it goes into the library.

What it does
------------
Every session with a `reference_spo2.csv` is replayed with the CURRENT library (offline runner
built against it, `derived/replay_lib<ver>/`), so all subjects are judged by the same code.
SpO2 is recomputed per sample with the shipped curve (123.98 - 39.13*R) and the library's own
validity rule (ProbeState APPLIED, r >= 0.8, PI known and <= 20 %, 70 <= a - b*R <= 110, clamp
to 100) — the replay of fw 0.15 sessions would otherwise carry the MS100 default curve. Each
candidate gate is then ANDed sample by sample. Against each reference reading (VideoNest OCR,
confidence >= 0.9, the same 8 s window ending at the reading as tools/spo2_bias_analysis.py,
probe on >= 80 %, no ABNORMAL CONDITION) the window is "published" when >= 25 % of its samples
pass, and its value is the median of the passing samples.

    python experiments/spo2_artifact_gate_20261020.py [--replay replay_lib0.108] [--out DIR]

Outputs in --out (default captures/sessions/GATE_ANALYSIS_20261020/, not versioned):
gate_summary.csv (one row per subject x gate) and gate_windows.csv (one row per reference
window x gate). The conclusions go in findings.md beside them and in the library rationale.

Result (2026-10-20, lib v0.108, OT-input replays; report: GATE_ANALYSIS_20261020/findings.md)
------
- 'HR3 valid' is the gate: SUBJ10 published windows 81 % -> 2.6 %, Arms 16.3 -> 2.1, none beyond
  4 points; adult finger and MS100 untouched (>= 98 %); SUBJ11 98 -> 93 %, SUBJ08/09 97-100 -> 78-80 %,
  and what it withholds there was mostly bad (|bias| med 2.5-3.8, 20-45 % beyond 4 points).
- r >= 0.99 and PI <= 10 % fail as artefact gates; HR3_SQI thresholds add nothing; HR2~HR3 agreement
  a little; HR1 agreement costs too much; a 5-10 s value hold re-admits SUBJ10's wrong values.
- Costs: desaturations (ref < 90) withheld more (-27/-28 points in SUBJ08/09); first value after
  applying the probe median 6.1 -> 10.5 s, p90 6.8 -> 36.6 s.
- Decision (Alex, 2026-10-22): option A, withhold — lib v0.110 `spo2_pulse_gate_enable` (default on),
  `AFE4490Data::spo2_hold_reason`; fw 0.28 ($M4 field 37 SPO2_HOLD_REASON); rationale section 17.
- Side finding: the runner's raw-input mode never computes HR2/HR3 (slow path lives in FreeRTOS tasks).
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import spo2_bias_analysis as B   # noqa: E402
from pulsenest import session_events        # noqa: E402

CURVE_A, CURVE_B = 123.98, 39.13           # R-CURVE-STS0163-HOSPNAV-20261004 (shipped)
R_CORR_MIN, PI_MAX, SPO2_MIN, SPO2_MAX, CLAMP_MARGIN = 0.8, 20.0, 70.0, 100.0, 10.0
APPLIED = 2
WINDOW_S = 8.0
REF_CONF_MIN = 0.9
SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ01", "SUBJ90")
ARTEFACT_SUBJECTS = ("SUBJ10",)            # the subject the gate exists for


def gates(d):
    """name -> boolean per sample, ANDed with the library's current validity. Candidates only."""
    hr2, hr3, s2, s3 = d["hr2"], d["hr3"], d["hr2_sqi"], d["hr3_sqi"]
    both = (hr2 > 0) & (hr3 > 0)
    agree = both & (np.abs(hr2 - hr3) <= 0.10 * np.maximum(hr3, 1.0))
    out = {
        "G0 library today": np.ones_like(hr3, dtype=bool),
        "G1 HR3 valid": hr3 > 0,
        "G2 HR3_SQI>=0.3": s3 >= 0.3,
        "G2 HR3_SQI>=0.5": s3 >= 0.5,
        "G2 HR3_SQI>=0.7": s3 >= 0.7,
        "G3 HR2~HR3 (10 %)": agree,
        "G4 HR1~HR3 (10 %)": (d["hr1"] > 0) & (hr3 > 0) & (np.abs(d["hr1"] - hr3) <= 0.10 * np.maximum(hr3, 1.0)),
        "G5 r>=0.95": d["rc"] >= 0.95,
        "G5 r>=0.99": d["rc"] >= 0.99,
        "G6 PI<=10": d["pi"] <= 10.0,
        "G7 HR3 valid & HR2~HR3": (hr3 > 0) & agree,
    }
    return out


HOLDS_S = (5.0, 10.0)        # Nellcor-style HOLD: the last gated value stays up to H s, then CLEAR
HOLD_BASE = "G1 HR3 valid"


def held(d, mask, hold_s):
    """(published mask, value) when the last value that passed `mask` is kept for up to hold_s
    after the gate closes — never across a probe-off sample (the library resets there)."""
    ok = d["base"] & mask
    t = d["t"]; v = d["spo2"]; on = d["ps"] == APPLIED
    pub = ok.copy(); val = np.where(ok, v, np.nan)
    last_t, last_v = -np.inf, np.nan
    for i in range(len(t)):
        if not on[i]:
            last_t = -np.inf; continue
        if ok[i]:
            last_t, last_v = t[i], v[i]
        elif t[i] - last_t <= hold_s * 1e6:
            pub[i] = True; val[i] = last_v
    return pub, val


def load(session_dir, replay):
    board, _curve = B.parse_board_session(session_dir, replay=replay)
    extra = {k: [] for k in ("hr1", "hr2", "hr2_sqi", "hr3_sqi")}
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    for path in parts:
        rp = os.path.join(session_dir, "derived", replay, os.path.basename(path)[:-4] + "_replay.csv")
        with open(rp, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                extra["hr1"].append(float(row["HR1"]))
                extra["hr2"].append(float(row["HR2"]))
                extra["hr2_sqi"].append(float(row["HR2_SQI"]))
                extra["hr3_sqi"].append(float(row["HR3_SQI"]))
    d = {"t": board["t"], "ps": board["ps"], "r": board["r"], "rc": board["r_method2_reg_corr"],
         "pi": board["pi"], "hr3": board["hr"]}
    for k, v in extra.items():
        d[k] = np.array(v, dtype=np.float64)
        if len(d[k]) != len(d["t"]):
            raise ValueError(f"{session_dir}: {k} rows {len(d[k])} != {len(d['t'])}")
    raw = CURVE_A - CURVE_B * d["r"]
    d["spo2"] = np.minimum(raw, SPO2_MAX)
    with np.errstate(invalid="ignore"):
        d["base"] = ((d["ps"] == APPLIED) & np.isfinite(d["r"]) & (d["rc"] >= R_CORR_MIN)
                     & np.isfinite(d["pi"]) & (d["pi"] > 0) & (d["pi"] <= PI_MAX)
                     & (raw >= SPO2_MIN) & (raw <= SPO2_MAX + CLAMP_MARGIN))
    return d


def windows(subject, name, d, ref_t, ref_s, ref_c, anomalies, gate_masks):
    rows = []
    w_us = WINDOW_S * 1e6
    for t1, s, c in zip(ref_t, ref_s, ref_c):
        if c < REF_CONF_MIN:
            continue
        i0 = int(np.searchsorted(d["t"], t1 - w_us, side="right"))
        i1 = int(np.searchsorted(d["t"], t1, side="right"))
        if i1 - i0 < B.MIN_VALID_SAMPLES:
            continue
        sl = slice(i0, i1)
        if (d["ps"][sl] == APPLIED).mean() < B.APPLIED_MIN_FRAC:
            continue
        if session_events.covered_fraction(anomalies, t1 - w_us, t1) > B.ANOMALY_MAX_FRAC:
            continue
        for g, m in gate_masks.items():
            if isinstance(m, tuple):                     # held variant: (published, value)
                ok, vals = m[0][sl], m[1][sl]
            else:
                ok, vals = d["base"][sl] & m[sl], d["spo2"][sl]
            frac = float(ok.mean())
            pub = frac >= B.VALID_MIN_FRAC and ok.sum() >= B.MIN_VALID_SAMPLES
            ours = float(np.median(vals[ok])) if pub else math.nan
            rows.append({"subject": subject, "session": name, "t_epoch_us": int(t1), "gate": g,
                         "ref": s, "pass_frac": round(frac, 4), "published": int(pub),
                         "ours": ours, "bias": ours - s if pub else math.nan})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", default="replay_lib0.108")
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "GATE_ANALYSIS_20261020"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    all_rows, time_avail, onset = [], {}, {}
    for subject in SUBJECTS:
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            if not os.path.isdir(os.path.join(sd, "derived", args.replay)):
                print(f"  skip {os.path.basename(sd)}: no {args.replay}")
                continue
            d = load(sd, args.replay)
            gm = gates(d)
            for h in HOLDS_S:
                gm[f"G1 + hold {h:.0f} s"] = held(d, gm[HOLD_BASE], h)
            on = d["ps"] == APPLIED
            for g, m in gm.items():
                a = time_avail.setdefault((subject, g), [0, 0])
                pubm = m[0] if isinstance(m, tuple) else (d["base"] & m)
                a[0] += int((pubm & on).sum()); a[1] += int(on.sum())
            # onset: from each probe application (>= 30 s on) to the first published sample
            starts = np.flatnonzero(np.diff(on.astype(np.int8)) == 1) + 1
            for g in ("G0 library today", HOLD_BASE):
                pubm = d["base"] & gm[g]
                for i0 in starts:
                    i_end = i0 + int(np.argmax(~on[i0:])) if (~on[i0:]).any() else len(on)
                    if d["t"][i_end - 1] - d["t"][i0] < 30e6:
                        continue
                    k = np.flatnonzero(pubm[i0:i_end])
                    onset.setdefault(g, []).append((d["t"][i0 + k[0]] - d["t"][i0]) / 1e6 if len(k) else math.inf)
            rt, rs, rc = B.parse_reference(sd)
            anomalies = session_events.anomaly_intervals(sd, subject)
            rows = windows(subject, os.path.basename(sd), d, rt, rs, rc, anomalies, gm)
            all_rows += rows
            print(f"  {os.path.basename(sd)}: {len(d['t'])} samples, {len(rows) // len(gm)} reference windows")
    with open(os.path.join(args.out, "gate_windows.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0])); w.writeheader(); w.writerows(all_rows)
    summ = []
    gnames = list(gates({k: np.zeros(1) for k in ("hr1", "hr2", "hr3", "hr2_sqi", "hr3_sqi", "rc", "pi")}))
    gnames += [f"G1 + hold {h:.0f} s" for h in HOLDS_S]
    for subject in SUBJECTS:
        for g in gnames:
            rs = [r for r in all_rows if r["subject"] == subject and r["gate"] == g]
            if not rs:
                continue
            b = np.array([r["bias"] for r in rs if r["published"]])
            ta = time_avail.get((subject, g), [0, 1])
            summ.append({"subject": subject, "gate": g, "windows": len(rs),
                         "published_pct": round(100 * len(b) / len(rs), 1),
                         "time_published_pct": round(100 * ta[0] / max(ta[1], 1), 1),
                         "bias_med": round(float(np.median(b)), 2) if len(b) else math.nan,
                         "absbias_med": round(float(np.median(np.abs(b))), 2) if len(b) else math.nan,
                         "absbias_p90": round(float(np.percentile(np.abs(b), 90)), 2) if len(b) else math.nan,
                         "arms": round(float(np.sqrt(np.mean(b ** 2))), 2) if len(b) else math.nan,
                         "off_gt4_pct": round(100 * float(np.mean(np.abs(b) > 4)), 1) if len(b) else math.nan})
    with open(os.path.join(args.out, "gate_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0])); w.writeheader(); w.writerows(summ)
    hdr = f"{'subject':7} {'gate':24} {'win':>5} {'pub%':>6} {'time%':>6} {'bias':>6} {'|b|med':>7} {'|b|p90':>7} {'Arms':>6} {'>4pt%':>6}"
    print("\n" + hdr)
    for s in summ:
        print(f"{s['subject']:7} {s['gate']:24} {s['windows']:5d} {s['published_pct']:6.1f} {s['time_published_pct']:6.1f} "
              f"{s['bias_med']:6.2f} {s['absbias_med']:7.2f} {s['absbias_p90']:7.2f} {s['arms']:6.2f} {s['off_gt4_pct']:6.1f}")

    print("\nWindows the library publishes today and HR3-valid would withhold (G0 and not G1):")
    by = {}
    for r in all_rows:
        by.setdefault((r["subject"], r["session"], r["t_epoch_us"]), {})[r["gate"]] = r
    for subject in SUBJECTS:
        lost = [w["G0 library today"]["bias"] for k, w in by.items() if k[0] == subject
                and w["G0 library today"]["published"] and not w[HOLD_BASE]["published"]]
        kept = [w[HOLD_BASE]["bias"] for k, w in by.items() if k[0] == subject and w[HOLD_BASE]["published"]]
        if lost:
            a = np.abs(np.array(lost)); b = np.abs(np.array(kept)) if kept else np.array([np.nan])
            print(f"  {subject}: withheld {len(lost):4d}  |bias| med {np.median(a):5.2f}  >4 pt {100*np.mean(a > 4):5.1f} %"
                  f"   | kept {len(kept):4d}  |bias| med {np.nanmedian(b):5.2f}  >4 pt {100*np.nanmean(b > 4):5.1f} %")
    print("\nOnset (probe applied -> first published SpO2), applications >= 30 s:")
    for g, v in onset.items():
        v = np.array(v); f = v[np.isfinite(v)]
        print(f"  {g:20s} n={len(v):3d}  median {np.median(f):5.1f} s  p90 {np.percentile(f, 90):5.1f} s  never {int(np.sum(~np.isfinite(v)))}")


if __name__ == "__main__":
    main()
