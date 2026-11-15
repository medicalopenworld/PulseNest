"""The methods of the time-lag family (HR2) against what the ward monitor showed.

Why this exists
---------------
Plan of 2026-11-15 (HR2LAB): before a live window shows the methods of family 2 side by side, the
bench says how they score. Today's HR2 (HR2_ACF, the unbiased normalised autocorrelation) is the
only method of the family; MPM (McLeod's normalised square difference) and YIN (the cumulative
mean normalised difference) were planned on 2026-09-02 because pitch detection designed them
against the octave error of the autocorrelation. All three come from one sweep of the same buffer
(pulsenest/hr_bench.py: lag_sweep, hr2_acf, hr2_mpm, hr2_yin). The comparison follows the weighted
criteria agreed with Alex on 2026-11-15: honesty when failing 35, availability 20, dynamics 15,
range and low perfusion 15, precision when right 10, cost 5; plus a map of where each method fails,
for a later phase that combines methods.

Questions (agreed with Alex on 2026-11-15, before any measurement)
---------
Q1  Do MPM or YIN fix the octave errors of HR2_ACF? Error classes per subject.
Q2  Honesty: share of the published windows that are wrong; AUC of the quality index.
Q3  Availability at the same published error: error against availability as the quality bar rises.
Q4  Dynamics: start-up from the probe applied to the first right value; steps of the MS100.
Q5  Range: the MS100 plateaus, 30 bpm above all (HR3_SAC fails there).
Q6  Map of gaps: where does the best lag method fail, and does it fail where HR3_SAC fails?

Fixed before measuring
----------------------
Front end: the library's HR2 chain (band-pass 0.5-5 Hz, 50 Hz, 400 samples = 8 s, every 0.5 s).
Parameters from the papers, not tuned: MPM k = 0.9 with clarity >= 0.5 to publish (the bar of
hr2_min_corr); YIN absolute threshold 0.10, nothing published without a dip under it.
Reference: the monitor reading nearest to the window's end (<= 6 s), scored only where 'stable';
correct = within 10 %. SUBJ08, SUBJ09, SUBJ11 show the ECG heart rate; SUBJ10 another pulse
oximeter (reported apart). The consensus of HR1 and HR2 is NOT a reference here: it contains the
board's HR2. Artefact stratum: windows where HR3_SAC fails its validity rule of 2026-11-12
(rho >= 0.5 and comb purity >= 0.3), a rule of another family.
Rows for comparison: HR3_SAC, HR3_SAC gated, HR3_HPS (bench, on the HR3 window ending at the same
sample), board HR1, board HR2 (the value published at the window's last sample).
Quality bars swept for Q3: each method's own quality, published from its default and raised.
Dynamics: start-up = time from the first applied sample of a run to the first published value
within 10 % of the reference; step = time from the first keyboard event of an MS100 plateau to the
first window within 5 % of the new rate that stays there for the next 3 windows (cap 30 s).
Post hoc (after the first run, marked as such in the report, nothing adopted): the same functions
with the pickers' parameters loosened, MPM k = 0.8 / 0.7 / 0.5 and YIN threshold 0.2 / 0.3 / 0.5,
and the NSDF with HR2_ACF's picker (first local maximum >= 0.5). It separates the function from
the picker after the first run showed the paper values jumping to multiples of the period.
Weighted total (replaces, on 2026-11-15 at Alex's request, a ranking that summed each method's
rank 1-3 times the weight: a rank counts order, not size, so a gap of 0.7 points took a whole
weight). Each criterion is put on a FIXED scale, set before recomputing and not taken from the
data (a scale between the best and worst of three methods would give a full weight to a tiny
spread): penalty = (value - best) / (worst - best), clipped to 0..1, times the weight; summed over
the six criteria, 0 = best on all, 100 = worst on all. SCALES: honesty, wrong of published, 0 to
20 %; availability, published at the same operating point as honesty (each method's own
publish rule, as the criteria of 2026-11-15 say), 100 to 0 %; dynamics, start-up + MS100 step median, 0 to 20 s;
range, MS100 right averaged over the plateaus, 100 to 0 %; precision, median absolute error when
right, 0 to 5 bpm; cost, not measured offline, 0 for all.

    python experiments/hr2_methods_20261115.py [--out DIR] [--cache DIR] [--subjects ...] [--no-figs]

Outputs in --out (default captures/sessions/HR2_METHODS_20261115/, not versioned): bench_vs_board.csv,
rate_vs_monitor.csv, honesty.csv, curve.csv, startup.csv, ms100.csv, ms100_steps.csv, joint.csv,
gaps.csv, weighted_total.csv, posthoc.csv, one PNG per session. --cache is the bench's cache of raw columns.

Result: see docs/hr2_methods_20261115.md.
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
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
ECG_SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ11")
MS100_SUBJECTS = ("SUBJ90",)
MONITOR_DIR = os.path.join(B.SESSIONS_DIR, "BIAS_ANALYSIS_SUBJ10_SUBJ11", "ocr_vs_eye")
RHO_MIN, PURITY_MIN = 0.5, 0.3
LAG = hb.HR2_METHODS
SAC, SAC_G, HPS = "HR3_SAC", "HR3_SAC gated", "HR3_HPS"
OTHERS = (SAC, SAC_G, HPS, "board HR1", "board HR2")
WEIGHTS = {"honesty": 35, "availability": 20, "dynamics": 15, "range": 15, "precision": 10, "cost": 5}
POSTHOC = (("MPM k0.8", "mpm", 0.8), ("MPM k0.7", "mpm", 0.7), ("MPM k0.5", "mpm", 0.5),
           ("YIN thr0.2", "yin", 0.2), ("YIN thr0.3", "yin", 0.3), ("YIN thr0.5", "yin", 0.5),
           ("NSDF + ACF picker", "nsdf_first", 0.5))
STEP_REL, STEP_HOLD, STEP_CAP_S = 0.05, 3, 30.0
HR_BANDS = ((0, 100), (100, 140), (140, 170), (170, 300))
# fixed scales of the weighted total: criterion -> (value that scores 0, value that scores the full weight)
SCALES = {"honesty": (0.0, 20.0), "availability": (100.0, 0.0), "dynamics": (0.0, 20.0),
          "range": (100.0, 0.0), "precision": (0.0, 5.0), "cost": (0.0, 1.0)}


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


def estimates(d, S, ends, rate):
    """name -> (HR per HR2 window, quality per window); the HR3 methods on the HR3 window that ends at
    the same sample (none in the first 2.24 s of a run, where the HR3 buffer is still filling)."""
    est = {k: (v[0], v[1]) for k, v in hb.hr2_family(S, rate, yin_window="shrinking").items()}
    W = len(ends)
    for k in (SAC, SAC_G, HPS):
        est[k] = (np.full(W, np.nan), np.zeros(W))
    has3 = np.zeros(W, dtype=bool)
    P, ends3, rate3 = hb.hr3_spectra(d)
    if P.shape[0]:
        pos = np.searchsorted(ends, ends3)
        m = (pos < W) & (ends[np.minimum(pos, W - 1)] == ends3)
        i2, i3 = pos[m], np.flatnonzero(m)
        has3[i2] = True
        hr_s, rho, _, _ = hb.hr3_sac(P, rate3)
        pur = hb.comb_purity(P, hr_s, rate3)
        g = np.isfinite(hr_s) & (rho >= RHO_MIN) & (pur >= PURITY_MIN)
        hr_h, q_h = hb.hps_estimate(P, *hb.hps(P, 3), rate3)
        est[SAC][0][i2], est[SAC][1][i2] = hr_s[i3], rho[i3]
        est[SAC_G][0][i2] = np.where(g, hr_s, np.nan)[i3]
        est[SAC_G][1][i2] = np.where(g, rho, 0.0)[i3]
        est[HPS][0][i2], est[HPS][1][i2] = hr_h[i3], q_h[i3]
    for col in ("HR1", "HR2"):
        v = d[col][ends]
        est[f"board {col}"] = (np.where(v > 0, v, np.nan), (v > 0).astype(float))
    return est, has3


def posthoc(S, rate):
    """name -> (HR, quality) of the post hoc variants (see the docstring)."""
    _, hi = hb.hr2_lag_range(rate, S.shape[1])
    r, m = hb.lag_sweep(S, hi + 1)
    out = {}
    for name, kind, v in POSTHOC:
        if kind == "mpm":
            hr, q, _, _ = hb.hr2_mpm(r, m, rate, S.shape[1], k=v)
        elif kind == "yin":
            hr, q, _, _ = hb.hr2_yin(r, m, rate, S.shape[1], threshold=v)
        else:      # the NSDF read by HR2_ACF's picker: r0 * (N - tau) / N replaced by m / 2
            Nf = hb.nsdf(r, m)
            fake_r = Nf * (S.shape[1] - np.arange(Nf.shape[1]))[None, :] / S.shape[1]
            fake_r[:, 0] = 1.0
            hr, q, _, _ = hb.hr2_acf(fake_r, rate, S.shape[1], min_corr=v)
        out[name] = (hr, q)
    return out


def weighted_total(metric, methods):
    """Rows of the weighted total: per criterion and method the value, the penalty on its fixed scale
    (SCALES) and the points (penalty x weight); then one TOTAL row per method (lower is better)."""
    rows, total = [], {k: 0.0 for k in methods}
    for crit, vals in metric.items():
        best, worst = SCALES[crit]
        for k in methods:
            v = vals[k]
            pen = 1.0 if v is None or (isinstance(v, float) and math.isnan(v)) else min(1.0, max(0.0, (v - best) / (worst - best)))
            pts = pen * WEIGHTS[crit]
            total[k] += pts
            rows.append({"criterion": crit, "weight": WEIGHTS[crit], "method": k, "metric": round(float(v), 3),
                         "penalty": round(pen, 3), "points": round(pts, 1)})
    for k in methods:
        rows.append({"criterion": "TOTAL (0 best, 100 worst)", "weight": 100, "method": k, "metric": "",
                     "penalty": "", "points": round(total[k], 1)})
    return rows


def run_starts(d, ends):
    """Per window: time (us) of the first applied sample of its run."""
    on = (d["ps"] == hb.APPLIED).astype(np.int8)
    starts = np.flatnonzero(np.diff(np.concatenate(([0], on))) == 1)
    k = np.searchsorted(starts, ends, side="right") - 1
    return d["t"][starts[np.maximum(k, 0)]], starts[np.maximum(k, 0)]


def honesty_row(hr, q, sel, ref):
    """Q1-Q3 on the windows of sel (all carry a stable reference)."""
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    pub = sel & np.isfinite(hr)
    ok = pub & (cl == 0)
    wrong = pub & (cl != 0)
    row = {"ref_windows": int(sel.sum()), "published_pct": pct(pub, sel), "ok_pct": pct(ok, sel),
           "wrong_of_published_pct": pct(wrong, pub)}
    for i, c in enumerate(hb.CLASSES[1:-1], start=1):
        row[c] = pct(pub & (cl == i), sel)
    row["auc_quality"] = round(hb.rank_auc(q[ok], q[wrong]), 3) if wrong.any() and ok.any() else math.nan
    err = (hr - ref)[ok]
    row["bias_ok_bpm"] = med(err)
    row["mae_ok_bpm"] = med(np.abs(err))
    return row


def curve_points(hr, q, sel, ref, bars):
    """(bar, availability % of sel, wrong % of published) as the quality bar rises."""
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    out = []
    for b in bars:
        pub = sel & np.isfinite(hr) & (q >= b)
        out.append((b, pct(pub, sel), pct(pub & (cl != 0), pub)))
    return out


def avail_at(points, max_wrong):
    ok = [a for b, a, w in points if not math.isnan(w) and w <= max_wrong]
    return max(ok) if ok else 0.0


def startup(est, t_run, t_end, ref, has_ref):
    """{method: [seconds from the run start to the first published value within 10 % of ref]}"""
    out = {k: [] for k in est}
    for t0 in np.unique(t_run):
        idx = np.flatnonzero(t_run == t0)
        if not has_ref[idx].any():
            continue
        for k, (hr, _) in est.items():
            good = idx[has_ref[idx] & np.isfinite(hr[idx]) & (np.abs(hr[idx] / np.where(has_ref[idx], ref[idx], 1) - 1) <= hb.OK_REL)]
            out[k].append((t_end[good[0]] - t0) / 1e6 if len(good) else math.nan)
    return out


def raw_plateaus(sd):
    """(first event time us, pr) of each MS100 plateau, before the bench's 15 s skip."""
    return [(t0 - hb.PLATEAU_SKIP_S * 1e6, pr) for t0, t1, pr in hb.ms100_plateaus(sd)]


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


def figure(path, name, t_end, mon_t, mon_v, est):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t0 = t_end[0]
    x = (t_end - t0) / 60e6
    hop = float(np.median(np.diff(x))) if len(x) > 1 else 0.0
    brk = np.flatnonzero(np.diff(x) > 1.5 * hop) + 1

    def line(y):
        return np.insert(x, brk, np.nan), np.insert(np.asarray(y, dtype=float), brk, np.nan)

    fig, ax = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    a = ax[0]
    a.plot(*line(est[SAC][0]), "-", lw=3, color="0.8", label="HR3_SAC")
    for k, c in zip(LAG, ("tab:red", "tab:green", "tab:blue")):
        a.plot(x, est[k][0], ".", ms=2.5, color=c, alpha=0.7, label=k)
    m = (mon_t >= t_end[0] - 30e6) & (mon_t <= t_end[-1] + 30e6)
    a.plot((mon_t[m] - t0) / 60e6, mon_v[m], "o", ms=4, mfc="none", color="k", label="monitor")
    a.set_ylabel("bpm"); a.set_ylim(20, 270); a.grid(alpha=0.3); a.legend(loc="upper right", ncol=5, fontsize=8)
    a.set_title(f"{name}: rate of each time-lag method against the ward monitor")
    b = ax[1]
    for k, c in zip(LAG, ("tab:red", "tab:green", "tab:blue")):
        b.plot(*line(est[k][1]), "-", lw=0.7, color=c, label=f"quality {k}")
    b.set_ylim(0, 1.05); b.set_ylabel("quality"); b.set_xlabel("minutes from the first window")
    b.grid(alpha=0.3); b.legend(loc="lower right", ncol=3, fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR2_METHODS_20261115"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    ap.add_argument("--no-figs", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    print(f"hr2_methods_20261115 run {datetime.datetime.now().isoformat(timespec='seconds')}")

    acc, bvb_rows, ms_rows, step_acc, start_acc, names = {}, [], [], {}, {}, None
    for subject in args.subjects:
        mon_path = os.path.join(MONITOR_DIR, f"{subject}_snapshots_eye.csv")
        mon_t, mon_v, mon_col = (hb.monitor_readings(mon_path) if os.path.exists(mon_path)
                                 else (np.zeros(0), np.zeros(0), "none"))
        sds = hb.session_dirs(B.SESSIONS_DIR, subject)
        offs = {sd: hb.phone_offset_us(sd) for sd in sds}
        known = [o for o in offs.values() if o is not None]
        fallback = float(np.median(known)) if known else 0.0
        print(f"\n{subject}: monitor column '{mon_col}', {len(mon_t)} readings")
        for sd in sds:
            name = os.path.basename(sd)
            d = hb.load_columns(sd, args.cache)
            S, ends, rate = hb.hr2_segments(d, buf_len=400)   # lib v0.120's 8 s, what this study measured
            if S.shape[0] == 0:
                print(f"  {name}: no HR2 window"); continue
            t_end = d["t"][ends]
            W = len(ends)
            est, has3 = estimates(d, S, ends, rate)
            names = list(est)
            ph = posthoc(S, rate)
            # the bench's HR2_ACF against the value the board published (does the bench mirror it?)
            a, b = est["HR2_ACF"][0], est["board HR2"][0]
            both = np.isfinite(a) & np.isfinite(b)
            cls_a = hb.error_class(a, np.where(both, b, np.nan))
            bvb_rows.append({"session": name, "windows": W, "same_validity_pct": pct(np.isfinite(a) == np.isfinite(b)),
                             "within_1bpm_pct": pct(np.abs(a[both] - b[both]) <= 1.0),
                             "within_10pct_pct": pct(cls_a[both] == 0),
                             "ratio_p01": round(float(np.percentile(a[both] / b[both], 1)), 3) if both.any() else math.nan,
                             "ratio_p99": round(float(np.percentile(a[both] / b[both], 99)), 3) if both.any() else math.nan})
            t_run, _ = run_starts(d, ends)
            if subject in MS100_SUBJECTS:
                plats = hb.ms100_plateaus(sd)
                ref = np.full(W, np.nan)
                for p0, p1, pr in plats:
                    ref[(t_end >= p0) & (t_end <= p1)] = pr
                stable = np.isfinite(ref)
                for p0, p1, pr in plats:
                    sel = (t_end >= p0) & (t_end <= p1)
                    for k, (hr, _) in est.items():
                        cl = hb.error_class(hr[sel], np.full(int(sel.sum()), pr))
                        ms_rows.append({"session": name, "pr_bpm": pr, "estimator": k, "windows": int(sel.sum()),
                                        "ok_pct": pct(cl == 0), "none_pct": pct(cl == hb.CLASSES.index("none")),
                                        "hr_med": med(hr[sel])})
                for k, v in step_times(est, t_end, raw_plateaus(sd)).items():
                    step_acc.setdefault(k, []).extend(v)
            else:
                off = offs[sd] if offs[sd] is not None else fallback
                ref, stable = hb.monitor_reference(mon_t + off, mon_v, t_end)
            for k, v in startup(est, t_run, t_end, ref, np.isfinite(ref)).items():
                start_acc.setdefault((subject, k), []).extend(v)
            st = acc.setdefault(subject, {"ref": [], "stable": [], "has3": [], "est": {k: ([], []) for k in names},
                                          "ph": {k: ([], []) for k in ph}, "mon_col": mon_col})
            for k, (hr, q) in ph.items():
                st["ph"][k][0].append(hr); st["ph"][k][1].append(q)
            st["ref"].append(ref); st["stable"].append(stable); st["has3"].append(has3)
            for k, (hr, q) in est.items():
                st["est"][k][0].append(hr); st["est"][k][1].append(q)
            print(f"  {name}: {W} windows, reference {int(np.isfinite(ref).sum())} (stable {int(stable.sum())}), "
                  + ", ".join(f"{k} valid {pct(np.isfinite(est[k][0]))} %" for k in LAG))
            if not args.no_figs and subject not in MS100_SUBJECTS:
                figure(os.path.join(args.out, f"{name}_hr2.png"), name, t_end, mon_t + off, mon_v, est)

    Z = {}
    for subject, st in acc.items():
        z = {k: np.concatenate(st[k]) for k in ("ref", "stable", "has3")}
        z["est"] = {k: (np.concatenate(st["est"][k][0]), np.concatenate(st["est"][k][1])) for k in names}
        z["ph"] = {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in st["ph"].items()}
        Z[subject] = z

    # Q1, Q2: every method against the reference; all / HR3_SAC valid / not valid
    rate_rows, curve_rows, joint_rows, gap_rows = [], [], [], []
    pooled = {k: {"sel": [], "ref": [], "hr": [], "q": []} for k in names}
    for subject, z in Z.items():
        if subject in MS100_SUBJECTS:
            continue
        sac_ok = np.isfinite(z["est"][SAC_G][0])
        for subset, sel in (("all", z["stable"]), ("HR3_SAC valid", z["stable"] & sac_ok),
                            ("HR3_SAC not valid", z["stable"] & z["has3"] & ~sac_ok)):
            for k in names:
                hr, q = z["est"][k]
                rate_rows.append({"subject": subject, "subset": subset, "estimator": k} | honesty_row(hr, q, sel, z["ref"]))
        # Q3: the curve, on each method's own quality
        for k in LAG:
            hr, q = z["est"][k]
            bars = np.round(np.arange(0.0, 1.0001, 0.05), 2)
            for b, av, w in curve_points(hr, q, z["stable"], z["ref"], bars):
                curve_rows.append({"subject": subject, "estimator": k, "bar": b, "available_pct": av, "wrong_of_published_pct": w})
            if subject in ECG_SUBJECTS:
                for key, arr in (("sel", z["stable"]), ("ref", z["ref"]), ("hr", hr), ("q", q)):
                    pooled[k][key].append(arr)
        # Q6: right or wrong together with HR3_SAC; failure rate by stratum and by rate band
        sel = z["stable"] & z["has3"]
        ok_s = hb.error_class(z["est"][SAC][0], np.where(sel, z["ref"], np.nan)) == 0
        for k in LAG + ("board HR1", HPS):
            ok_k = hb.error_class(z["est"][k][0], np.where(sel, z["ref"], np.nan)) == 0
            joint_rows.append({"subject": subject, "method": k, "ref_windows": int(sel.sum()),
                               "both_ok": pct(ok_s & ok_k & sel, sel), "only_sac_ok": pct(ok_s & ~ok_k & sel, sel),
                               "only_this_ok": pct(~ok_s & ok_k & sel, sel), "neither_ok": pct(~ok_s & ~ok_k & sel, sel)})
        for k in LAG + (SAC_G,):
            hr, q = z["est"][k]
            for lo, hi in HR_BANDS:
                sb = z["stable"] & (z["ref"] >= lo) & (z["ref"] < hi)
                if sb.sum() < 50:
                    continue
                r = honesty_row(hr, q, sb, z["ref"])
                gap_rows.append({"subject": subject, "method": k, "reference_band": f"{lo}-{hi}",
                                 "ref_windows": r["ref_windows"], "ok_pct": r["ok_pct"],
                                 "wrong_of_published_pct": r["wrong_of_published_pct"], "x1/2": r["x1/2"], "x2": r["x2"]})

    # pooled over the three ECG subjects: honesty, availability, precision
    pool_rows = []
    for k in LAG + OTHERS:
        if not pooled.get(k) or not pooled[k]["sel"]:
            if k in LAG:
                continue
            arrs = {key: [] for key in ("sel", "ref", "hr", "q")}
            for subject in ECG_SUBJECTS:
                if subject in Z:
                    arrs["sel"].append(Z[subject]["stable"]); arrs["ref"].append(Z[subject]["ref"])
                    arrs["hr"].append(Z[subject]["est"][k][0]); arrs["q"].append(Z[subject]["est"][k][1])
            if not arrs["sel"]:
                continue
        else:
            arrs = pooled[k]
        sel, ref, hr, q = (np.concatenate(arrs[key]) for key in ("sel", "ref", "hr", "q"))
        row = {"estimator": k} | honesty_row(hr, q, sel, ref)
        if k in LAG:
            pts = curve_points(hr, q, sel, ref, np.round(np.arange(0.0, 1.0001, 0.01), 2))
            row["available_at_1pct_wrong"] = avail_at(pts, 1.0)
            row["available_at_2pct_wrong"] = avail_at(pts, 2.0)
        pool_rows.append(row)

    ph_rows = []
    for name, _, _ in POSTHOC:
        zs = [Z[s] for s in ECG_SUBJECTS if s in Z]
        if not zs:
            continue
        sel = np.concatenate([z["stable"] for z in zs]); ref = np.concatenate([z["ref"] for z in zs])
        hr = np.concatenate([z["ph"][name][0] for z in zs]); q = np.concatenate([z["ph"][name][1] for z in zs])
        r = honesty_row(hr, q, sel, ref)
        pts = curve_points(hr, q, sel, ref, np.round(np.arange(0.0, 1.0001, 0.01), 2))
        ph_rows.append({"variant (post hoc)": name} | {k: r[k] for k in ("published_pct", "ok_pct", "wrong_of_published_pct",
                       "x1/2", "x1/3", "other", "auc_quality")} | {"available_at_1pct_wrong": avail_at(pts, 1.0)})
        for s_, z in zip([s for s in ECG_SUBJECTS if s in Z], zs):
            r = honesty_row(z["ph"][name][0], z["ph"][name][1], z["stable"], z["ref"])
            ph_rows[-1][f"ok_{s_}"] = r["ok_pct"]

    start_rows = []
    for (subject, k), v in start_acc.items():
        v = np.array(v, dtype=float)
        start_rows.append({"subject": subject, "estimator": k, "runs": len(v), "reached_pct": pct(np.isfinite(v)),
                           "startup_med_s": med(v), "startup_p90_s": round(float(np.nanpercentile(v, 90)), 1) if np.isfinite(v).any() else math.nan})
    step_rows = []
    for k, v in step_acc.items():
        s = np.array([e["s"] for e in v], dtype=float)
        step_rows.append({"estimator": k, "steps": len(s), "settled_pct": pct(np.isfinite(s)), "step_med_s": med(s),
                          "step_max_s": round(float(np.nanmax(s)), 1) if np.isfinite(s).any() else math.nan})

    # weighted total of the three HR2 methods, on the fixed scales of SCALES
    pr = {r["estimator"]: r for r in pool_rows}
    stp = {r["estimator"]: r for r in step_rows}
    st_ecg = {k: med([x for (s, kk), v in start_acc.items() if kk == k and s in ECG_SUBJECTS for x in v]) for k in LAG}
    ms = {k: [r["ok_pct"] for r in ms_rows if r["estimator"] == k] for k in LAG}
    ms_lo = {k: [r["ok_pct"] for r in ms_rows if r["estimator"] == k and r["pr_bpm"] <= 60] for k in LAG}
    metric = {
        "honesty": {k: pr[k]["wrong_of_published_pct"] for k in LAG},
        "availability": {k: pr[k]["published_pct"] for k in LAG},
        "dynamics": {k: (st_ecg[k] if not math.isnan(st_ecg[k]) else 99) + (stp.get(k, {}).get("step_med_s", 99) or 99) for k in LAG},
        "range": {k: float(np.mean(ms[k])) if ms[k] else 0.0 for k in LAG},
        "precision": {k: pr[k]["mae_ok_bpm"] for k in LAG},
        "cost": {k: 0.0 for k in LAG},
    }
    rank_rows = weighted_total(metric, LAG)
    for k in LAG:
        rank_rows.append({"criterion": "available at <= 1 % wrong (not scored)", "weight": "", "method": k,
                          "metric": pr[k]["available_at_1pct_wrong"], "penalty": "", "points": ""})
    for k in LAG:
        rank_rows.append({"criterion": "MS100 plateaus <= 60 bpm, ok % (not scored)", "weight": "", "method": k,
                          "metric": round(float(np.mean(ms_lo[k])), 1) if ms_lo[k] else math.nan, "penalty": "", "points": ""})

    for fn, rows in (("bench_vs_board.csv", bvb_rows), ("rate_vs_monitor.csv", rate_rows), ("honesty.csv", pool_rows),
                     ("curve.csv", curve_rows), ("startup.csv", start_rows), ("ms100.csv", ms_rows),
                     ("ms100_steps.csv", step_rows), ("joint.csv", joint_rows), ("gaps.csv", gap_rows),
                     ("weighted_total.csv", rank_rows), ("posthoc.csv", ph_rows)):
        write_csv(os.path.join(args.out, fn), rows)

    print("\nThe bench's HR2_ACF against the board's HR2:"); table(bvb_rows)
    cols = ["subject", "subset", "estimator", "ref_windows", "published_pct", "ok_pct", "wrong_of_published_pct",
            "x2", "x1/2", "x3", "x1/3", "other", "auc_quality", "bias_ok_bpm", "mae_ok_bpm"]
    print("\nEach method against the reference (% of the windows with a stable reading):")
    table(rate_rows, cols)
    print("\nPooled over SUBJ08, SUBJ09, SUBJ11 (ECG):"); table(pool_rows)
    print("\nStart-up from the probe applied:"); table(start_rows)
    print("\nMS100 steps:"); table(step_rows)
    if ms_rows:
        prs = sorted({r["pr_bpm"] for r in ms_rows})
        print("\nMS100 ok % per plateau (bpm); '.' = 100, 'x' = 0:")
        print(f"{'estimator':16} " + " ".join(f"{p:5.0f}" for p in prs))
        for k in names:
            cells = []
            for p in prs:
                v = [r["ok_pct"] for r in ms_rows if r["estimator"] == k and r["pr_bpm"] == p]
                okp = float(np.mean(v)) if v else math.nan
                cells.append("    ." if okp >= 99.95 else ("    x" if okp <= 0.05 else f"{okp:5.1f}"))
            print(f"{k:16} " + " ".join(cells))
    print("\nRight or wrong together with HR3_SAC:"); table(joint_rows)
    print("\nBy reference band:"); table(gap_rows)
    print("\nWeighted total (fixed scales):"); table(rank_rows)
    print("\nPost hoc, pooled over SUBJ08, SUBJ09, SUBJ11:"); table(ph_rows)


if __name__ == "__main__":
    main()
