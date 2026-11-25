"""The chains of family 1 (HR1) on our own captures, against what the ward monitor showed (2026-11-16, plan HR1LAB step F3).

Why this exists
---------------
Step F2 (experiments/hr1_mimic_perform_20261116.py) scored the four detectors and three publication
rules beat by beat on the MIMIC PERform neonates, another instrument. This step asks whether what F2
found holds on our instrument: our OT at 500 Hz from our probe on the HOSPNAV neonates (SUBJ08-11) and
the MS100 simulator (SUBJ90), against the same references and criteria as the family 2 and 3 studies
(docs/hr2_methods_20261115.md, docs/hr3_methods_20261114.md), so the families can be compared.
Our captures have no ECG waveform: the reference is the heart rate the ward monitor showed (read by
eye from the VideoNest photos, one every 10 s), so this step scores rates, not beats.

Questions (fixed with the plan before measuring, 2026-11-15/16)
---------
Q1  Honesty: share of the published values that are wrong, error classes, AUC of the quality index.
Q2  Availability at each chain's own operating point; availability at <= 1 % / <= 5 % wrong (shown).
Q3  Dynamics: start-up from the probe applied to the first right value; the MS100 steps.
Q4  Range: the MS100 plateaus (30-250 bpm), right share per plateau.
Q5  Precision when right: median absolute error.
Q6  Map of gaps: by reference rate band; in the artefact stratum (HR3_SAC not valid); right or wrong
    together with HR3_SAC (is a family-1 chain a complement?).
Weighted total on the fixed scales of 2026-11-15 (as hr2_methods_20261115.py).

Predictions from F2, written before this run (to be confirmed or not, nothing tuned):
P1  With R0 every detector is honest (<= 2 % wrong) and the detector sets the availability: SSF above
    today's THR, TERMA lowest (MSPTD, offline, highest).
P2  TERMA + R0's errors are mostly half the rate, published with a high hr1_sqi.
P3  R1 without a threshold on its quality publishes the most and is wrong the most often.

Fixed before measuring
----------------------
Chains: pulsenest/hr1_bench.py, the common front end (LowPass4 15 Hz, 100 Hz, high-pass 0.5 Hz) and the
four detectors with the papers' values, times the rules R0, R1, R2 (R2 anchored to the bench's HR3_SAC,
valid when rho >= 0.5 and comb purity >= 0.3). Each run of ProbeState APPLIED processed apart, read every
0.5 s; a value is published where the rule says valid (R0: hr1_sqi > 0). Quality index: hr1_sqi for R0,
the accepted share of the last 8 RR for R1 / R2.
Rows for comparison: board HR1 (today's chain on the board, published where HR1 > 0 and HR1_SQI > 0),
board HR2, HR3_SAC gated (the last HR3 window of the bench ending at or before the output row, at most
0.5 s earlier, same run).
Reference: the monitor reading nearest to the output time (<= 6 s), scored only where stable; right =
within 10 %. SUBJ08, SUBJ09, SUBJ11 show the ECG heart rate (pooled as "ECG"); SUBJ10 another pulse
oximeter (reported apart). MS100: the plateau's rate (hr_bench.ms100_plateaus, first 15 s skipped).
Dynamics: start-up = time from the first applied sample of a run to the first published value within
10 % of the reference; step = time from the first keyboard event of an MS100 plateau to the first output
within 5 % of the new rate that stays there for the next 3 outputs (cap 30 s).
Weighted total: honesty 35 (0-20 % wrong of published), availability 20 (100-0 % published, own
operating point), dynamics 15 (start-up median + step median, 0-20 s), range 15 (MS100 right, mean over
the plateaus, 100-0 %), precision 10 (median absolute error when right, 0-5 bpm), cost 5 (not measured
offline, 0 for all). 0 = best on all, 100 = worst.

Result (run 2026-11-16 01:31; report docs/hr1_methods_20261116.md, section F3): P1, P2 and P3 hold.
ECG subjects, R0: published MSPTD 85.8 %, SSF 82.0 %, THR 66.4 %, TERMA 43.2 %, the board's HR1 47.2 %,
all <= 0.6 % wrong; R1 88-94 % published, 0.5-3.3 % wrong, up to 13 % in the artefact stratum. The
common front end alone takes today's detector from 47 to 66 % and its start-up from 12 to 2.5 s (SUBJ08);
weighted total 26.1 (board) -> 14.5. SSF reads 60 at 30 bpm and 120 at 240 bpm on the MS100 (its 0.34 s
eye-closing) and starts 8.5 s late (learning period). SSF + R0 and HR3_SAC together right in 91 % of the
outputs, HR3_SAC alone 83 %.

    python experiments/hr1_methods_20261116.py [--out DIR] [--cache DIR] [--subjects ...] [--no-figs]

Outputs in --out (default captures/sessions/HR1_METHODS_20261116/, not versioned): rate_vs_monitor.csv,
honesty.csv, startup.csv, ms100.csv, ms100_steps.csv, joint.csv, gaps.csv, weighted_total.csv,
one PNG per ward session.
"""
import argparse
import csv
import datetime
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr_bench as hb          # noqa: E402
from pulsenest import hr1_bench as h1         # noqa: E402
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
ECG_SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ11")
MS100_SUBJECTS = ("SUBJ90",)
MONITOR_DIR = os.path.join(B.SESSIONS_DIR, "BIAS_ANALYSIS_SUBJ10_SUBJ11", "ocr_vs_eye")
CHAINS = tuple(f"{D.name}+{R.name}" for D in h1.DETECTORS for R in h1.RULES)
SAC_G, SAC, BOARD1, BOARD2 = "HR3_SAC gated", "HR3_SAC", "board HR1", "board HR2"
SCORED = CHAINS + (BOARD1,)
OTHERS = (BOARD1, BOARD2, SAC_G)
WEIGHTS = {"honesty": 35, "availability": 20, "dynamics": 15, "range": 15, "precision": 10, "cost": 5}
SCALES = {"honesty": (0.0, 20.0), "availability": (100.0, 0.0), "dynamics": (0.0, 20.0),
          "range": (100.0, 0.0), "precision": (0.0, 5.0), "cost": (0.0, 1.0)}
STEP_REL, STEP_HOLD, STEP_CAP_S = 0.05, 3, 30.0
HR_BANDS = ((0, 140), (140, 160), (160, 180), (180, 300))

def ecg_subjects(subjects):
    """The subjects of this run scored against the ward monitor's ECG: a monitor file exists and
    the subject is not the simulator. The tuple above is the 2026-11 default; a run on other
    subjects (--subjects) pools what it was given."""
    return tuple(s for s in subjects if s not in MS100_SUBJECTS
                 and os.path.exists(os.path.join(MONITOR_DIR, f"{s}_snapshots_eye.csv")))



def pct(mask, of=None):
    n = len(mask) if of is None else int(of.sum())
    return round(100.0 * float(np.sum(mask)) / n, 1) if n else math.nan


def med(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return round(float(np.median(v)), 2) if len(v) else math.nan


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)


def table(rows, cols=None):
    if not rows:
        return
    cols = cols or list(dict.fromkeys(k for r in rows for k in r))
    wd = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(f"{c:>{wd[c]}}" for c in cols))
    for r in rows:
        print("  ".join(f"{str(r.get(c, '')):>{wd[c]}}" for c in cols))


def applied_runs(d):
    on = (d["ps"] == hb.APPLIED).astype(np.int8)
    e = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    return list(zip(e[::2], e[1::2]))


def estimates(d):
    """Every chain read every 0.5 s on each applied run, plus the comparison rows.
    Returns (ends [raw rows], run_start [raw row of each output's run], est {name: (hr, q)})."""
    fs = d["fs"]
    make_anchor = h1.sac_anchor(d)
    est = {k: ([], []) for k in CHAINS}
    ends, run0 = [], []
    for r0, r1 in applied_runs(d):
        x = d["OT_LED1"][r0:r1]
        rows = h1.output_rows(len(x), fs)
        if len(rows) == 0:
            continue
        anchor = make_anchor(r0, r1)
        for D in h1.DETECTORS:
            det = D(100.0)
            b = h1.detect(x, fs, h1.FrontEnd(fs), det)
            for R in h1.RULES:
                hr, q, v = h1.apply_rule(b, fs, R(), rows, anchor=anchor if R is h1.RuleR2 else None,
                                         latency_s=det.latency_s)
                est[f"{D.name}+{R.name}"][0].append(np.where(v, hr, np.nan))
                est[f"{D.name}+{R.name}"][1].append(q)
        ends.append(r0 + rows); run0.append(np.full(len(rows), r0))
    if not ends:
        return np.zeros(0, int), np.zeros(0, int), {}
    ends = np.concatenate(ends); run0 = np.concatenate(run0)
    est = {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in est.items()}
    h1v, s1 = d["HR1"][ends], d["HR1_SQI"][ends]
    est[BOARD1] = (np.where((h1v > 0) & (s1 > 0), h1v, np.nan), np.where(h1v > 0, s1, 0.0))
    h2v = d["HR2"][ends]
    est[BOARD2] = (np.where(h2v > 0, h2v, np.nan), (h2v > 0).astype(float))
    P, e3, rate3 = hb.hr3_spectra(d)
    est[SAC] = (np.full(len(ends), np.nan), np.zeros(len(ends)))
    est[SAC_G] = (np.full(len(ends), np.nan), np.zeros(len(ends)))
    if len(e3):
        hr_s, rho, _, _ = hb.hr3_sac(P, rate3)
        pur = hb.comb_purity(P, hr_s, rate3)
        g = np.isfinite(hr_s) & (rho >= h1.SAC_RHO_MIN) & (pur >= h1.SAC_PURITY_MIN)
        k = np.searchsorted(e3, ends, side="right") - 1
        kk = np.maximum(k, 0)
        fresh = (k >= 0) & (e3[kk] >= run0) & (ends - e3[kk] <= 0.5 * fs)
        est[SAC] = (np.where(fresh, hr_s[kk], np.nan), np.where(fresh, rho[kk], 0.0))
        est[SAC_G] = (np.where(fresh & g[kk], hr_s[kk], np.nan), np.where(fresh & g[kk], rho[kk], 0.0))
    return ends, run0, est


def honesty_row(hr, q, sel, ref):
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    pub = sel & np.isfinite(hr)
    ok = pub & (cl == 0)
    wrong = pub & (cl != 0)
    row = {"ref_outputs": int(sel.sum()), "published_pct": pct(pub, sel), "ok_pct": pct(ok, sel),
           "wrong_of_published_pct": pct(wrong, pub)}
    for i, c in enumerate(hb.CLASSES[1:-1], start=1):
        row[c] = pct(pub & (cl == i), sel)
    row["auc_quality"] = round(hb.rank_auc(q[ok], q[wrong]), 3) if wrong.any() and ok.any() else math.nan
    err = (hr - ref)[ok]
    row["bias_ok_bpm"] = med(err)
    row["mae_ok_bpm"] = med(np.abs(err))
    return row


def avail_at(hr, q, sel, ref, max_wrong_pct):
    """Highest share of sel still published when the quality bar rises, with at most max_wrong wrong."""
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    pub0 = sel & np.isfinite(hr)
    qs = q[pub0]; wr = (cl != 0)[pub0]
    if len(qs) == 0 or sel.sum() == 0:
        return math.nan
    order = np.argsort(-qs, kind="stable")
    qs, wr = qs[order], wr[order]
    n = np.arange(1, len(qs) + 1)
    cut = np.r_[qs[1:] != qs[:-1], True]
    ok = cut & (100.0 * np.cumsum(wr) / n <= max_wrong_pct)
    return round(100.0 * n[ok].max() / sel.sum(), 1) if ok.any() else 0.0


def startup(est, t_run, t_end, ref, has_ref):
    out = {k: [] for k in est}
    for t0 in np.unique(t_run):
        idx = np.flatnonzero(t_run == t0)
        if not has_ref[idx].any():
            continue
        for k, (hr, _) in est.items():
            good = idx[has_ref[idx] & np.isfinite(hr[idx])
                       & (np.abs(hr[idx] / np.where(has_ref[idx], ref[idx], 1) - 1) <= hb.OK_REL)]
            out[k].append((t_end[good[0]] - t0) / 1e6 if len(good) else math.nan)
    return out


def step_times(est, t_end, plats):
    out = {k: [] for k in est}
    for (t0, pr), (_, prev) in zip(plats[1:], plats[:-1]):
        if pr == prev:
            continue
        sel = np.flatnonzero((t_end >= t0) & (t_end <= t0 + STEP_CAP_S * 1e6))
        for k, (hr, _) in est.items():
            inside = np.isfinite(hr[sel]) & (np.abs(hr[sel] / pr - 1) <= STEP_REL)
            hit = math.nan
            for i in range(len(sel) - STEP_HOLD):
                if inside[i:i + STEP_HOLD + 1].all():
                    hit = (t_end[sel[i]] - t0) / 1e6
                    break
            out[k].append({"from": prev, "to": pr, "s": hit})
    return out


def weighted_total(metric, methods):
    rows, total = [], {k: 0.0 for k in methods}
    for crit, vals in metric.items():
        best, worst = SCALES[crit]
        for k in methods:
            v = vals[k]
            pen = 1.0 if v is None or (isinstance(v, float) and math.isnan(v)) else min(1.0, max(0.0, (v - best) / (worst - best)))
            total[k] += pen * WEIGHTS[crit]
            rows.append({"criterion": crit, "weight": WEIGHTS[crit], "method": k, "metric": round(float(v), 3),
                         "penalty": round(pen, 3), "points": round(pen * WEIGHTS[crit], 1)})
    for k in methods:
        rows.append({"criterion": "TOTAL (0 best, 100 worst)", "weight": 100, "method": k, "metric": "",
                     "penalty": "", "points": round(total[k], 1)})
    return rows, total


def figure(path, name, t_end, mon_t, mon_v, est):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t0 = t_end[0]
    x = (t_end - t0) / 60e6
    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(x, est[SAC_G][0], "-", lw=3, color="0.8", label=SAC_G)
    for k, c in ((BOARD1, "k"), ("HR1_THR+R0", "tab:red"), ("HR1_SSF+R0", "tab:green"),
                 ("HR1_TERMA+R0", "tab:orange"), ("HR1_SSF+R1", "tab:blue")):
        ax.plot(x, est[k][0], ".", ms=2.5, color=c, alpha=0.7, label=k)
    m = (mon_t >= t_end[0] - 30e6) & (mon_t <= t_end[-1] + 30e6)
    ax.plot((mon_t[m] - t0) / 60e6, mon_v[m], "o", ms=5, mfc="none", color="m", label="monitor")
    ax.set_ylabel("bpm"); ax.set_ylim(20, 270); ax.grid(alpha=0.3); ax.legend(loc="upper right", ncol=4, fontsize=8)
    ax.set_xlabel("minutes from the first output"); ax.set_title(f"{name}: family-1 chains against the ward monitor")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR1_METHODS_20261116"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    ap.add_argument("--no-figs", action="store_true")
    args = ap.parse_args(argv)
    ecg = ecg_subjects(args.subjects)
    ecg_names = ", ".join(ecg)
    os.makedirs(args.out, exist_ok=True)
    print(f"hr1_methods_20261116 run {datetime.datetime.now().isoformat(timespec='seconds')}")

    acc, ms_rows, step_acc, start_acc, names = {}, [], {}, {}, None
    for subject in args.subjects:
        mon_path = os.path.join(MONITOR_DIR, f"{subject}_snapshots_eye.csv")
        mon_t, mon_v, mon_col = (hb.monitor_readings(mon_path) if os.path.exists(mon_path)
                                 else (np.zeros(0), np.zeros(0), "none"))
        sds = hb.session_dirs(B.SESSIONS_DIR, subject)
        offs = {sd: hb.phone_offset_us(sd) for sd in sds}
        known = [o for o in offs.values() if o is not None]
        fallback = float(np.median(known)) if known else 0.0
        print(f"\n{subject}: monitor column '{mon_col}', {len(mon_t)} readings", flush=True)
        for sd in sds:
            name = os.path.basename(sd)
            d = hb.load_columns(sd, args.cache)
            ends, run0, est = estimates(d)
            if len(ends) == 0:
                print(f"  {name}: no applied run"); continue
            names = list(est)
            t_end = d["t"][ends]
            t_run = d["t"][run0]
            if subject in MS100_SUBJECTS:
                plats = hb.ms100_plateaus(sd)
                ref = np.full(len(ends), np.nan)
                for p0, p1, pr in plats:
                    ref[(t_end >= p0) & (t_end <= p1)] = pr
                stable = np.isfinite(ref)
                for p0, p1, pr in plats:
                    sel = (t_end >= p0) & (t_end <= p1)
                    for k, (hr, _) in est.items():
                        cl = hb.error_class(hr[sel], np.full(int(sel.sum()), pr))
                        ms_rows.append({"session": name, "pr_bpm": pr, "estimator": k, "outputs": int(sel.sum()),
                                        "ok_pct": pct(cl == 0), "none_pct": pct(cl == hb.CLASSES.index("none")),
                                        "hr_med": med(hr[sel])})
                raw = [(t0 - hb.PLATEAU_SKIP_S * 1e6, pr) for t0, t1, pr in plats]
                for k, v in step_times(est, t_end, raw).items():
                    step_acc.setdefault(k, []).extend(v)
                off = 0.0
            else:
                off = offs[sd] if offs[sd] is not None else fallback
                ref, stable = hb.monitor_reference(mon_t + off, mon_v, t_end)
            for k, v in startup(est, t_run, t_end, ref, np.isfinite(ref)).items():
                start_acc.setdefault((subject, k), []).extend(v)
            st = acc.setdefault(subject, {"ref": [], "stable": [], "est": {k: ([], []) for k in names}})
            st["ref"].append(ref); st["stable"].append(stable)
            for k, (hr, q) in est.items():
                st["est"][k][0].append(hr); st["est"][k][1].append(q)
            print(f"  {name}: {len(ends)} outputs, reference {int(np.isfinite(ref).sum())} (stable {int(stable.sum())})"
                  + ", ".join(f"; {k} {pct(np.isfinite(est[k][0]))} %" for k in ("HR1_THR+R0", "HR1_SSF+R0", BOARD1)),
                  flush=True)
            if not args.no_figs and subject not in MS100_SUBJECTS:
                figure(os.path.join(args.out, f"{name}_hr1.png"), name, t_end, mon_t + off, mon_v, est)

    Z = {}
    for subject, st in acc.items():
        Z[subject] = {"ref": np.concatenate(st["ref"]), "stable": np.concatenate(st["stable"]),
                      "est": {k: (np.concatenate(st["est"][k][0]), np.concatenate(st["est"][k][1])) for k in names}}

    # Q1, Q2, Q5 per subject; Q6 strata, bands, joint with HR3_SAC
    rate_rows, gap_rows, joint_rows = [], [], []
    for subject, z in Z.items():
        if subject in MS100_SUBJECTS:
            continue
        has3 = np.isfinite(z["est"][SAC][0])
        sac_ok = np.isfinite(z["est"][SAC_G][0])
        for subset, sel in (("all", z["stable"]), ("HR3_SAC valid", z["stable"] & sac_ok),
                            ("HR3_SAC not valid", z["stable"] & has3 & ~sac_ok)):
            for k in SCORED + (BOARD2, SAC_G):
                hr, q = z["est"][k]
                rate_rows.append({"subject": subject, "subset": subset, "estimator": k} | honesty_row(hr, q, sel, z["ref"]))
        sel = z["stable"] & has3
        ok_s = hb.error_class(z["est"][SAC_G][0], np.where(sel, z["ref"], np.nan)) == 0
        for k in SCORED:
            ok_k = hb.error_class(z["est"][k][0], np.where(sel, z["ref"], np.nan)) == 0
            joint_rows.append({"subject": subject, "method": k, "ref_outputs": int(sel.sum()),
                               "both_ok": pct(ok_s & ok_k & sel, sel), "only_sac_ok": pct(ok_s & ~ok_k & sel, sel),
                               "only_this_ok": pct(~ok_s & ok_k & sel, sel), "neither_ok": pct(~ok_s & ~ok_k & sel, sel)})
        for k in SCORED + (SAC_G,):
            hr, q = z["est"][k]
            for lo, hi in HR_BANDS:
                sb = z["stable"] & (z["ref"] >= lo) & (z["ref"] < hi)
                if sb.sum() < 50:
                    continue
                r = honesty_row(hr, q, sb, z["ref"])
                gap_rows.append({"subject": subject, "method": k, "reference_band": f"{lo}-{hi}",
                                 "ref_outputs": r["ref_outputs"], "published_pct": r["published_pct"], "ok_pct": r["ok_pct"],
                                 "wrong_of_published_pct": r["wrong_of_published_pct"], "x1/2": r["x1/2"], "x2": r["x2"]})

    # pooled over the three ECG subjects
    pool_rows = []
    zs = [Z[s] for s in ecg if s in Z]
    if zs:
        sel = np.concatenate([z["stable"] for z in zs]); ref = np.concatenate([z["ref"] for z in zs])
        for k in SCORED + (BOARD2, SAC_G):
            hr = np.concatenate([z["est"][k][0] for z in zs]); q = np.concatenate([z["est"][k][1] for z in zs])
            row = {"estimator": k} | honesty_row(hr, q, sel, ref)
            row["available_at_1pct_wrong"] = avail_at(hr, q, sel, ref, 1.0)
            row["available_at_5pct_wrong"] = avail_at(hr, q, sel, ref, 5.0)
            # P2: the share of the wrong values that are half the rate, and of those with quality >= 0.8
            cl = hb.error_class(hr, np.where(sel, ref, np.nan))
            half = sel & np.isfinite(hr) & (cl == hb.CLASSES.index("x1/2"))
            row["half_rate_n"] = int(half.sum())
            row["half_rate_q08_n"] = int((half & (q >= 0.8)).sum())
            pool_rows.append(row)

    start_rows = []
    for (subject, k), v in start_acc.items():
        v = np.array(v, dtype=float)
        start_rows.append({"subject": subject, "estimator": k, "runs": len(v), "reached_pct": pct(np.isfinite(v)),
                           "startup_med_s": med(v),
                           "startup_p90_s": round(float(np.nanpercentile(v, 90)), 1) if np.isfinite(v).any() else math.nan})
    step_rows = []
    for k, v in step_acc.items():
        s = np.array([e["s"] for e in v], dtype=float)
        step_rows.append({"estimator": k, "steps": len(s), "settled_pct": pct(np.isfinite(s)), "step_med_s": med(s),
                          "step_max_s": round(float(np.nanmax(s)), 1) if np.isfinite(s).any() else math.nan})

    pr = {r["estimator"]: r for r in pool_rows}
    stp = {r["estimator"]: r for r in step_rows}
    st_ecg = {k: med([x for (s, kk), v in start_acc.items() if kk == k and s in ecg for x in v]) for k in SCORED}
    ms = {k: [r["ok_pct"] for r in ms_rows if r["estimator"] == k] for k in SCORED}
    ms_lo = {k: [r["ok_pct"] for r in ms_rows if r["estimator"] == k and r["pr_bpm"] <= 60] for k in SCORED}
    metric = {
        "honesty": {k: pr[k]["wrong_of_published_pct"] for k in SCORED},
        "availability": {k: pr[k]["published_pct"] for k in SCORED},
        "dynamics": {k: (st_ecg[k] if not math.isnan(st_ecg[k]) else 99)
                     + (stp.get(k, {}).get("step_med_s", 99) if not math.isnan(stp.get(k, {}).get("step_med_s", 99)) else 99)
                     for k in SCORED},
        "range": {k: float(np.mean(ms[k])) if ms[k] else 0.0 for k in SCORED},
        "precision": {k: pr[k]["mae_ok_bpm"] for k in SCORED},
        "cost": {k: 0.0 for k in SCORED},
    }
    wt_rows, total = weighted_total(metric, SCORED)
    for k in SCORED:
        wt_rows.append({"criterion": "available at <= 1 % wrong (not scored)", "weight": "", "method": k,
                        "metric": pr[k]["available_at_1pct_wrong"], "penalty": "", "points": ""})
        wt_rows.append({"criterion": "MS100 plateaus <= 60 bpm, ok % (not scored)", "weight": "", "method": k,
                        "metric": round(float(np.mean(ms_lo[k])), 1) if ms_lo[k] else math.nan, "penalty": "", "points": ""})

    for fn, rows in (("rate_vs_monitor.csv", rate_rows), ("honesty.csv", pool_rows), ("startup.csv", start_rows),
                     ("ms100.csv", ms_rows), ("ms100_steps.csv", step_rows), ("joint.csv", joint_rows),
                     ("gaps.csv", gap_rows), ("weighted_total.csv", wt_rows)):
        write_csv(os.path.join(args.out, fn), rows)

    print(f"\nPooled over the ECG subjects ({ecg_names}), every 0.5 s with a stable monitor reading:")
    table(pool_rows, ["estimator", "ref_outputs", "published_pct", "ok_pct", "wrong_of_published_pct", "x1/2", "x2",
                      "x3/2", "other", "auc_quality", "mae_ok_bpm", "available_at_1pct_wrong", "available_at_5pct_wrong",
                      "half_rate_n", "half_rate_q08_n"])
    print("\nSUBJ10 (another pulse oximeter as reference), all outputs with a stable reading:")
    table([r for r in rate_rows if r["subject"] == "SUBJ10" and r["subset"] == "all"],
          ["estimator", "ref_outputs", "published_pct", "wrong_of_published_pct", "x1/2", "auc_quality"])
    print("\nArtefact stratum (HR3_SAC not valid), ECG subjects:")
    table([r for r in rate_rows if r["subject"] in ecg and r["subset"] == "HR3_SAC not valid"],
          ["subject", "estimator", "ref_outputs", "published_pct", "wrong_of_published_pct"])
    print("\nStart-up (s) from the probe applied to the first right value:")
    table(sorted(start_rows, key=lambda r: (r["subject"], r["estimator"])))
    print("\nMS100 steps:"); table(step_rows)
    print("\nMS100 plateaus, ok % (mean over plateaus) and <= 60 bpm:")
    table([{"estimator": k, "ok_mean": round(float(np.mean(ms[k])), 1) if ms[k] else math.nan,
            "ok_le60": round(float(np.mean(ms_lo[k])), 1) if ms_lo[k] else math.nan} for k in SCORED])
    print("\nMap of gaps by reference band:"); table(gap_rows)
    print("\nRight or wrong together with HR3_SAC gated:"); table(joint_rows)
    print("\nWeighted total (fixed scales):")
    table([{"method": k, "total": round(total[k], 1)} | {c: metric[c][k] for c in metric} for k in
           sorted(SCORED, key=lambda kk: total[kk])])


if __name__ == "__main__":
    main()
