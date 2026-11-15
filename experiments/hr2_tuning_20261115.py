"""The time-lag methods (HR2) with their parameters chosen on this signal, out of sample.

Why this exists
---------------
Second and third parts of docs/hr2_methods_20261115.md. The first part measured HR2_MPM and HR2_YIN
with their papers' values and found them jumping to multiples of the period. Alex (2026-11-15):
that is unfair to methods so close to HR2_ACF; repeat the comparison with a better
parametrisation, and then ask whether HR2_ACF itself should be parametrised better. Reviewing the
bench before this run found a defect in the first part's YIN: its difference summed over N - tau
samples, so it shrank as the lag grew and favoured long lags. The paper uses a fixed integration
window; pulsenest/hr_bench.py now does too (yin_difference, YIN_WINDOW = "fixed").

Questions (fixed on 2026-11-15, before this run)
---------
Part 2, the methods (the library's front end: 0.5-5 Hz, 8 s, every 0.5 s)
T1  YIN with the paper's fixed window and its threshold 0.10: how much of the first part's result
    came from the shrinking window?
T2  With parameters chosen on other subjects, do HR2_MPM or HR2_YIN reach or beat HR2_ACF with the
    library's values, on the weighted criteria of 2026-11-15?
T3  Are the chosen parameters stable from one fold to the next?
Part 3, HR2_ACF
A1  hr2_min_corr: does another value than 0.5 win out of sample?
A2  The front end: the band's high edge (3 / 4 / 5 Hz) and the buffer (4 / 6 / 8 s), chosen with
    hr2_min_corr by the same procedure; start-up and the 30 bpm floor beside the score.
A3  Is a change worth proposing to the library? (rule below)

Fixed before measuring
----------------------
Score, the one thing the choice maximises: ok % - 1.75 x wrong %, both as a share of the windows
with a stable reference; 1.75 = honesty 35 / availability 20, the weights agreed on 2026-11-15.
Correct = within 10 % of the reference (pulsenest/hr_bench.py error_class).
Out of sample = leave one subject out over the three ECG subjects (SUBJ08, SUBJ09, SUBJ11): the
parameters are chosen on two, scored on the third, three times; the held-out windows of the three
folds are pooled. SUBJ10 (another pulse oximeter) and the MS100 (SUBJ90) are never used to choose:
they are scored with the parameters chosen on all three ECG subjects.
Grids: HR2_ACF min_corr 0.30-0.80 step 0.05; HR2_MPM k 0.50-0.95 step 0.05 x clarity to publish
0.3-0.7 step 0.1; HR2_YIN threshold 0.05-0.60 step 0.05; front end f_high {3, 4, 5} Hz x buffer
{200, 300, 400} samples at 50 Hz. The low edge (0.5 Hz), the update (0.5 s) and the pickers' rules
are not touched. A 4 s buffer cannot hold the period of 30 bpm (the lag cap is n / 2 - 1 = 99).
Rule for A3: propose a change to the library only if, out of sample, the pooled score rises by at
least 2 points, no held-out subject loses more than 1 point, and the MS100 plateaus at or under 60
bpm are not worse; or if start-up falls by at least 1 s for at most 1 point of score.
Weighted total as in the first part (fixed scales, P1.SCALES; 0 best, 100 worst; it replaced the
rank-based ranking on 2026-11-15), with the out-of-sample rows for honesty, availability and
precision.

Post hoc (added after the first run of this script, marked as such in the report)
--------
P1  MPM and YIN chose the edge of their grids (k 0.5, threshold 0.6): the grids extended (k down to
    0.30, threshold up to 1.00), same procedure.
P2  "Available at 1 % wrong" above picks the quality bar on the pooled windows it scores (as the
    first part did). Here the bar is chosen on the two training subjects (the lowest bar whose
    published windows are at most 1 % wrong) and applied to the held-out one.
P3  The front ends the A3 rule lets through, checked where the choice never looked: HR2_ACF at
    5 Hz with 4, 6 and 8 s, at min_corr 0.5 and 0.4, per held-out subject, on SUBJ10 and on the
    MS100 (30 bpm and the plateaus at or under 60 bpm), start-up median and 90th percentile.

    python experiments/hr2_tuning_20261115.py [--out DIR] [--cache DIR]

Outputs in --out (default captures/sessions/HR2_TUNING_20261115/, not versioned): folds.csv,
oos.csv, per_subject.csv, ms100.csv, subj10.csv, steps.csv, weighted_total.csv, acf_frontend.csv,
posthoc_grids.csv, posthoc_bar.csv, posthoc_frontend.csv.
Helpers come from experiments/hr2_methods_20261115.py (the first part), so both parts score alike.

Result: see docs/hr2_methods_20261115.md, parts 2 and 3.
"""
import argparse
import datetime
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments import hr2_methods_20261115 as P1   # noqa: E402
from pulsenest import hr_bench as hb                  # noqa: E402
from tools import spo2_bias_analysis as B             # noqa: E402

ECG = P1.ECG_SUBJECTS
SUBJECTS = ECG + ("SUBJ10", "SUBJ90")
PENALTY = 35.0 / 20.0
ACF_GRID = [float(round(v, 2)) for v in np.arange(0.30, 0.8001, 0.05)]
MPM_GRID = [(float(round(k, 2)), float(round(c, 1))) for k in np.arange(0.50, 0.9501, 0.05) for c in np.arange(0.3, 0.7001, 0.1)]
YIN_GRID = [float(round(v, 2)) for v in np.arange(0.05, 0.6001, 0.05)]
MPM_GRID_X = [(float(round(k, 2)), float(round(c, 1))) for k in np.arange(0.30, 0.9501, 0.05) for c in np.arange(0.3, 0.7001, 0.1)]
YIN_GRID_X = [float(round(v, 2)) for v in np.arange(0.05, 1.0001, 0.05)]
FRONT_ENDS = [(fh, n) for fh in (3.0, 4.0, 5.0) for n in (200, 300, 400)]
LIB_FE = (hb.HR2_F_HIGH_HZ, 400)   # the library's front end when this ran (v0.120: 8 s); v0.121 took 6 s from part 3
BARS = np.round(np.arange(0.0, 1.0001, 0.01), 2)


def score_parts(hr, sel, ref):
    """(ok, wrong, n) counts on the windows of sel."""
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    pub = sel & np.isfinite(hr)
    return int((pub & (cl == 0)).sum()), int((pub & (cl != 0)).sum()), int(sel.sum())


def score(hr, sel, ref):
    ok, wrong, n = score_parts(hr, sel, ref)
    return 100.0 * (ok - PENALTY * wrong) / n if n else math.nan


def session_windows(subject, sd, d, fe, mon):
    """Windows of one session under front end fe, with the reference and run starts."""
    S, ends, rate = hb.hr2_segments(d, f_high=fe[0], buf_len=fe[1])
    if S.shape[0] == 0:
        return None
    t_end = d["t"][ends]
    W = len(ends)
    if subject in P1.MS100_SUBJECTS:
        ref = np.full(W, np.nan)
        for p0, p1, pr in hb.ms100_plateaus(sd):
            ref[(t_end >= p0) & (t_end <= p1)] = pr
        stable = np.isfinite(ref)
    else:
        mon_t, mon_v, off = mon
        ref, stable = hb.monitor_reference(mon_t + off, mon_v, t_end)
    t_run, _ = P1.run_starts(d, ends)
    return {"S": S, "rate": rate, "t_end": t_end, "ref": ref, "stable": stable, "t_run": t_run, "sd": sd}


def method_outputs(w, fe):
    """{(method, param): (hr, q)} for one session's windows."""
    S, rate = w["S"], w["rate"]
    n = S.shape[1]
    lo, hi = hb.hr2_lag_range(rate, n)
    r, m = hb.lag_sweep(S, hi + 1)
    out = {}
    for c in ACF_GRID:
        hr, q, _, _ = hb.hr2_acf(r, rate, n, min_corr=c)
        out[("HR2_ACF", c)] = (hr, q)
    if fe != LIB_FE:
        return out
    Nf = hb.nsdf(r, m)
    keys = hb.mpm_keys(Nf, lo, hi)
    for k, c in MPM_GRID_X:
        hr, q, _ = hb.mpm_pick(Nf, keys, rate, k, c)
        out[("HR2_MPM", (k, c))] = (hr, q)
    dy = hb.yin_difference(S, hi + 1)
    for t in YIN_GRID_X:
        hr, q, _, _ = hb.hr2_yin(r, m, rate, n, threshold=t, d=dy)
        out[("HR2_YIN fixed", t)] = (hr, q)
    hr, q, _, _ = hb.hr2_yin(r, m, rate, n, threshold=hb.YIN_THRESHOLD)
    out[("HR2_YIN shrinking", hb.YIN_THRESHOLD)] = (hr, q)
    return out


def concat(parts):
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR2_TUNING_20261115"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    print(f"hr2_tuning_20261115 run {datetime.datetime.now().isoformat(timespec='seconds')}")

    # Z[fe][subject] = {"ref", "stable", "t_end", "t_run", "out": {(method, param): (hr, q)}}
    Z = {fe: {} for fe in FRONT_ENDS}
    plats = {}
    for subject in SUBJECTS:
        mon_path = os.path.join(P1.MONITOR_DIR, f"{subject}_snapshots_eye.csv")
        mon_t, mon_v, _ = (hb.monitor_readings(mon_path) if os.path.exists(mon_path) else (np.zeros(0), np.zeros(0), "none"))
        sds = hb.session_dirs(B.SESSIONS_DIR, subject)
        offs = {sd: hb.phone_offset_us(sd) for sd in sds}
        known = [o for o in offs.values() if o is not None]
        fallback = float(np.median(known)) if known else 0.0
        for sd in sds:
            d = hb.load_columns(sd, args.cache)
            off = offs[sd] if offs[sd] is not None else fallback
            if subject in P1.MS100_SUBJECTS:
                plats.setdefault(subject, []).extend(P1.raw_plateaus(sd))
            for fe in FRONT_ENDS:
                w = session_windows(subject, sd, d, fe, (mon_t, mon_v, off))
                if w is None:
                    continue
                o = method_outputs(w, fe)
                st = Z[fe].setdefault(subject, {"parts": [], "out": {}})
                st["parts"].append({k: w[k] for k in ("ref", "stable", "t_end", "t_run")})
                for key, (hr, q) in o.items():
                    st["out"].setdefault(key, ([], []))
                    st["out"][key][0].append(hr); st["out"][key][1].append(q)
        print(f"  {subject}: {len(sds)} sessions, "
              f"{sum(len(p['ref']) for p in Z[LIB_FE].get(subject, {'parts': []})['parts'])} windows (library front end)")
    for fe in FRONT_ENDS:
        for subject, st in Z[fe].items():
            st.update(concat(st.pop("parts")))
            st["out"] = {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in st["out"].items()}

    def cands(method):
        if method == "HR2_ACF":
            return [(fe, ("HR2_ACF", c)) for fe in FRONT_ENDS for c in ACF_GRID]
        if method == "HR2_ACF min_corr":
            return [(LIB_FE, ("HR2_ACF", c)) for c in ACF_GRID]
        if method in ("HR2_MPM ext", "HR2_YIN ext"):
            grid = MPM_GRID_X if method == "HR2_MPM ext" else YIN_GRID_X
        else:
            grid = MPM_GRID if method == "HR2_MPM" else YIN_GRID
        name = "HR2_MPM" if method.startswith("HR2_MPM") else "HR2_YIN fixed"
        return [(LIB_FE, (name, p)) for p in grid]

    def pooled_score(cand, subjects):
        fe, key = cand
        zs = [Z[fe][s] for s in subjects if s in Z[fe]]
        hr = np.concatenate([z["out"][key][0] for z in zs])
        sel = np.concatenate([z["stable"] for z in zs]); ref = np.concatenate([z["ref"] for z in zs])
        return score(hr, sel, ref)

    def best(method, subjects):
        cs = cands(method)
        sc = [pooled_score(c, subjects) for c in cs]
        i = int(np.nanargmax(sc))
        return cs[i], sc[i]

    # leave one ECG subject out
    TUNED = ("HR2_ACF min_corr", "HR2_ACF", "HR2_MPM", "HR2_YIN")
    FIXED = {"HR2_ACF library": (LIB_FE, ("HR2_ACF", hb.HR2_MIN_CORR)),
             "HR2_MPM paper": (LIB_FE, ("HR2_MPM", (hb.MPM_K, hb.MPM_MIN_CLARITY))),
             "HR2_YIN paper, shrinking (part 1)": (LIB_FE, ("HR2_YIN shrinking", hb.YIN_THRESHOLD)),
             "HR2_YIN paper, fixed window": (LIB_FE, ("HR2_YIN fixed", hb.YIN_THRESHOLD))}
    fold_rows, held = [], {}
    for out_s in ECG:
        train = [s for s in ECG if s != out_s]
        for method in TUNED:
            cand, sc_tr = best(method, train)
            fold_rows.append({"held_out": out_s, "method": method, "front_end": f"{cand[0][0]:g} Hz / {cand[0][1] / 50:g} s",
                              "param": str(cand[1][1]), "train_score": round(sc_tr, 1),
                              "held_out_score": round(pooled_score(cand, [out_s]), 1)})
            held.setdefault(method, []).append((out_s, cand))
        for name, cand in FIXED.items():
            held.setdefault(name, []).append((out_s, cand))

    def assemble(entries):
        """Held-out windows of each fold under its own choice: dict of concatenated arrays."""
        parts = []
        for s, (fe, key) in entries:
            z = Z[fe][s]
            parts.append({"hr": z["out"][key][0], "q": z["out"][key][1], "ref": z["ref"], "stable": z["stable"],
                          "t_end": z["t_end"], "t_run": z["t_run"]})
        return concat(parts)

    oos_rows, subj_rows, start_rows, A = [], [], [], {}
    for name, entries in held.items():
        a = assemble(entries)
        A[name] = a
        row = {"method": name} | P1.honesty_row(a["hr"], a["q"], a["stable"], a["ref"])
        row["score"] = round(score(a["hr"], a["stable"], a["ref"]), 1)
        pts = P1.curve_points(a["hr"], a["q"], a["stable"], a["ref"], BARS)
        row["available_at_1pct_wrong"] = P1.avail_at(pts, 1.0)
        su = P1.startup({name: (a["hr"], a["q"])}, a["t_run"], a["t_end"], a["ref"], np.isfinite(a["ref"]))[name]
        row["startup_med_s"] = P1.med(su)
        oos_rows.append(row)
        for s, cand in entries:
            z = Z[cand[0]][s]
            hr = z["out"][cand[1]][0]
            subj_rows.append({"method": name, "subject": s, "score": round(score(hr, z["stable"], z["ref"]), 1)}
                             | {k: v for k, v in P1.honesty_row(hr, z["out"][cand[1]][1], z["stable"], z["ref"]).items()
                                if k in ("published_pct", "ok_pct", "wrong_of_published_pct", "x2", "x1/2")})

    # final choice on all three ECG subjects, scored on SUBJ10 and the MS100
    final = {m: best(m, list(ECG))[0] for m in TUNED} | FIXED
    ms_rows, s10_rows, step_rows = [], [], []
    for name, (fe, key) in final.items():
        if "SUBJ10" in Z[fe]:
            z = Z[fe]["SUBJ10"]
            s10_rows.append({"method": name, "front_end": f"{fe[0]:g} Hz / {fe[1] / 50:g} s", "param": str(key[1]),
                             "score": round(score(z["out"][key][0], z["stable"], z["ref"]), 1)}
                            | {k: v for k, v in P1.honesty_row(z["out"][key][0], z["out"][key][1], z["stable"], z["ref"]).items()
                               if k in ("published_pct", "ok_pct", "wrong_of_published_pct", "x2", "x1/2")})
        if "SUBJ90" in Z[fe]:
            z = Z[fe]["SUBJ90"]
            hr = z["out"][key][0]
            okp = {}
            for pr in np.unique(z["ref"][np.isfinite(z["ref"])]):
                sel = z["ref"] == pr
                okp[pr] = P1.pct(hb.error_class(hr[sel], np.full(int(sel.sum()), pr)) == 0)
            ms_rows.append({"method": name, "front_end": f"{fe[0]:g} Hz / {fe[1] / 50:g} s", "param": str(key[1]),
                            "mean_ok_pct": round(float(np.mean(list(okp.values()))), 1),
                            "le60_ok_pct": round(float(np.mean([v for p, v in okp.items() if p <= 60])), 1)}
                           | {f"{p:g}": v for p, v in sorted(okp.items())})
            st = P1.step_times({name: (hr, z["out"][key][1])}, z["t_end"], plats["SUBJ90"])[name]
            s = np.array([e["s"] for e in st], dtype=float)
            step_rows.append({"method": name, "steps": len(s), "settled_pct": P1.pct(np.isfinite(s)), "step_med_s": P1.med(s)})

    # A2: every front end of HR2_ACF with min_corr chosen out of sample within it
    fe_rows = []
    for fe in FRONT_ENDS:
        entries = []
        for out_s in ECG:
            train = [s for s in ECG if s != out_s]
            cs = [(fe, ("HR2_ACF", c)) for c in ACF_GRID]
            sc = [pooled_score(c, train) for c in cs]
            entries.append((out_s, cs[int(np.nanargmax(sc))]))
        a = assemble(entries)
        su = P1.startup({"x": (a["hr"], a["q"])}, a["t_run"], a["t_end"], a["ref"], np.isfinite(a["ref"]))["x"]
        r = P1.honesty_row(a["hr"], a["q"], a["stable"], a["ref"])
        fe_rows.append({"f_high_hz": fe[0], "buffer_s": fe[1] / 50, "min_corr_per_fold": "/".join(str(e[1][1][1]) for e in entries),
                        "score": round(score(a["hr"], a["stable"], a["ref"]), 1), "published_pct": r["published_pct"],
                        "ok_pct": r["ok_pct"], "wrong_of_published_pct": r["wrong_of_published_pct"], "x2": r["x2"],
                        "x1/2": r["x1/2"], "startup_med_s": P1.med(su)}
                       | {f"score_{s}": round(score(Z[fe][s]["out"][e[1][1]][0], Z[fe][s]["stable"], Z[fe][s]["ref"]), 1)
                          for s, e in zip(ECG, entries)})

    # weighted total of the three methods, tuned rows (ACF with the library's values), fixed scales
    LAGR = ("HR2_ACF library", "HR2_MPM", "HR2_YIN")
    oo = {r["method"]: r for r in oos_rows}
    ms = {r["method"]: r for r in ms_rows}
    sp = {r["method"]: r for r in step_rows}
    metric = {"honesty": {k: oo[k]["wrong_of_published_pct"] for k in LAGR},
              "availability": {k: oo[k]["published_pct"] for k in LAGR},
              "dynamics": {k: (oo[k]["startup_med_s"] if not math.isnan(oo[k]["startup_med_s"]) else 99)
                           + (sp[k]["step_med_s"] if k in sp and not math.isnan(sp[k]["step_med_s"]) else 99) for k in LAGR},
              "range": {k: ms[k]["mean_ok_pct"] if k in ms else 0.0 for k in LAGR},
              "precision": {k: oo[k]["mae_ok_bpm"] for k in LAGR},
              "cost": {k: 0.0 for k in LAGR}}
    rank_rows = P1.weighted_total(metric, LAGR)
    for k in LAGR:
        rank_rows.append({"criterion": "available at <= 1 % wrong (not scored; P2 for the bar out of sample)",
                          "weight": "", "method": k, "metric": oo[k]["available_at_1pct_wrong"], "penalty": "", "points": ""})

    # ---- post hoc ----
    # P1: extended grids, leave one subject out
    p1_rows = []
    for method in ("HR2_MPM ext", "HR2_YIN ext"):
        entries = []
        for out_s in ECG:
            cand, _ = best(method, [s for s in ECG if s != out_s])
            entries.append((out_s, cand))
        a = assemble(entries)
        r = P1.honesty_row(a["hr"], a["q"], a["stable"], a["ref"])
        p1_rows.append({"method (post hoc)": method, "param_per_fold": " / ".join(str(e[1][1][1]) for e in entries),
                        "score": round(score(a["hr"], a["stable"], a["ref"]), 1)}
                       | {k: r[k] for k in ("published_pct", "ok_pct", "wrong_of_published_pct", "x1/2", "auc_quality")})

    # P2: the 1 %-wrong quality bar chosen on the training subjects
    def bar_on(arrs, max_wrong=1.0):
        pts = P1.curve_points(arrs["hr"], arrs["q"], arrs["stable"], arrs["ref"], BARS)
        ok = [b for b, av, w in pts if not math.isnan(w) and w <= max_wrong]
        return min(ok) if ok else 1.01

    p2_rows = []
    for name in ("HR2_ACF library", "HR2_ACF min_corr", "HR2_MPM", "HR2_YIN"):
        held_parts, bars = [], []
        for out_s, cand in held[name]:
            train = [s for s in ECG if s != out_s]
            tr = concat([{"hr": Z[cand[0]][s]["out"][cand[1]][0], "q": Z[cand[0]][s]["out"][cand[1]][1],
                          "ref": Z[cand[0]][s]["ref"], "stable": Z[cand[0]][s]["stable"]} for s in train])
            b = bar_on(tr)
            bars.append(b)
            z = Z[cand[0]][out_s]
            hr = np.where(z["out"][cand[1]][1] >= b, z["out"][cand[1]][0], np.nan)
            held_parts.append({"hr": hr, "ref": z["ref"], "stable": z["stable"]})
        h = concat(held_parts)
        ok, wrong, n = score_parts(h["hr"], h["stable"], h["ref"])
        pub = int((h["stable"] & np.isfinite(h["hr"])).sum())
        p2_rows.append({"method (post hoc)": name, "bar_per_fold": " / ".join(f"{b:.2f}" for b in bars),
                        "available_pct": round(100.0 * pub / n, 1), "ok_pct": round(100.0 * ok / n, 1),
                        "wrong_of_published_pct": round(100.0 * wrong / pub, 1) if pub else math.nan})

    # P3: HR2_ACF front ends at 5 Hz, min_corr 0.5 and 0.4
    p3_rows = []
    for nbuf in (200, 300, 400):
        fe = (5.0, nbuf)
        for c in (0.5, 0.4):
            key = ("HR2_ACF", c)
            row = {"buffer_s (post hoc)": nbuf / 50, "min_corr": c}
            parts = []
            for s_ in ECG:
                z = Z[fe][s_]
                row[f"score_{s_}"] = round(score(z["out"][key][0], z["stable"], z["ref"]), 1)
                parts.append({"hr": z["out"][key][0], "q": z["out"][key][1], "ref": z["ref"], "stable": z["stable"],
                              "t_end": z["t_end"], "t_run": z["t_run"]})
            a = concat(parts)
            row["score_ECG"] = round(score(a["hr"], a["stable"], a["ref"]), 1)
            r = P1.honesty_row(a["hr"], a["q"], a["stable"], a["ref"])
            row["wrong_of_published_pct"] = r["wrong_of_published_pct"]
            su = np.array(P1.startup({"x": (a["hr"], a["q"])}, a["t_run"], a["t_end"], a["ref"], np.isfinite(a["ref"]))["x"], dtype=float)
            row["startup_med_s"] = P1.med(su)
            row["startup_p90_s"] = round(float(np.nanpercentile(su, 90)), 1) if np.isfinite(su).any() else math.nan
            row["startup_reached_pct"] = P1.pct(np.isfinite(su))
            z = Z[fe]["SUBJ10"]
            row["score_SUBJ10"] = round(score(z["out"][key][0], z["stable"], z["ref"]), 1)
            z = Z[fe]["SUBJ90"]
            hr = z["out"][key][0]
            okp = {}
            for pr in np.unique(z["ref"][np.isfinite(z["ref"])]):
                sel = z["ref"] == pr
                okp[pr] = P1.pct(hb.error_class(hr[sel], np.full(int(sel.sum()), pr)) == 0)
            row["ms100_30"] = okp.get(30.0, math.nan)
            row["ms100_le60"] = round(float(np.mean([v for p_, v in okp.items() if p_ <= 60])), 1)
            row["ms100_mean"] = round(float(np.mean(list(okp.values()))), 1)
            p3_rows.append(row)

    for fn, rows in (("posthoc_grids.csv", p1_rows), ("posthoc_bar.csv", p2_rows), ("posthoc_frontend.csv", p3_rows)):
        P1.write_csv(os.path.join(args.out, fn), rows)

    for fn, rows in (("folds.csv", fold_rows), ("oos.csv", oos_rows), ("per_subject.csv", subj_rows),
                     ("ms100.csv", ms_rows), ("subj10.csv", s10_rows), ("steps.csv", step_rows),
                     ("weighted_total.csv", rank_rows), ("acf_frontend.csv", fe_rows)):
        P1.write_csv(os.path.join(args.out, fn), rows)
    print("\nChoice per fold (chosen on two ECG subjects, scored on the third):"); P1.table(fold_rows)
    print("\nOut of sample, the three held-out subjects pooled:")
    P1.table(oos_rows, ["method", "ref_windows", "published_pct", "ok_pct", "wrong_of_published_pct", "x2", "x1/2", "x3",
                        "x1/3", "other", "auc_quality", "mae_ok_bpm", "available_at_1pct_wrong", "startup_med_s", "score"])
    print("\nPer held-out subject:"); P1.table(subj_rows)
    print("\nChosen on all three ECG subjects, scored on SUBJ10:"); P1.table(s10_rows)
    print("\nChosen on all three ECG subjects, MS100 plateaus (ok %):"); P1.table(ms_rows)
    print("\nMS100 steps:"); P1.table(step_rows)
    print("\nHR2_ACF front ends, min_corr chosen out of sample within each:"); P1.table(fe_rows)
    print("\nWeighted total (out of sample, fixed scales):"); P1.table(rank_rows)
    print("\nPost hoc P1, extended grids:"); P1.table(p1_rows)
    print("\nPost hoc P2, quality bar for 1 % wrong chosen on the training subjects:"); P1.table(p2_rows)
    print("\nPost hoc P3, HR2_ACF at 5 Hz, buffer and min_corr:"); P1.table(p3_rows)


if __name__ == "__main__":
    main()
