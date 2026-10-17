"""SpO2 bias of the library against the ward monitor, for one or more subjects.

Pairs every reference reading (VideoNest OCR rows of `reference_spo2.csv`) with the
board's R, SpO2, PI, r (R_CORR) and HR over the monitor's averaging window that ends at
the reading, then compares the R curve the board ran that day (read from the `alg:`
snapshot of each capture, never hardcoded) with what the reference implies. Generalises
the per-campaign `r_vs_ref_analysis.py` / `fit_method2.py` of the 2026-09-23 analysis
directories: same window, same usability rule, same stationarity rule and bin fit, so the
numbers stay comparable with those reports.

    python tools/spo2_bias_analysis.py SUBJ10 SUBJ11 [--out DIR] [--replay replay_lib0.100]
           [--probe-states 1,2] [--window 8] [--exclude SESSION ...]

Sessions are `captures/sessions/<SUBJ>/<SUBJ>_<SITE>_<date>_<time>/`. A session without a
`reference_spo2.csv` (or with none of the declared kind) yields no pairs and is listed.
`--replay <name>` takes R, R_CORR, PI, SpO2, SpO2_SQI, ProbeState from
`<session>/derived/<name>/*_replay.csv` (offline runner output, rows 1:1 with the parts)
instead of the columns the firmware produced that day. `--curve a,b` evaluates that curve
instead of the day's: our SpO2 is then recomputed as a - b*R(window) (required with --replay,
whose SpO2 column carries whatever curve the runner applied).

Outputs in --out (default `captures/sessions/<SUBJ>/<SUBJ>_BIAS_ANALYSIS` for one subject,
`captures/sessions/BIAS_ANALYSIS_<SUBJ>_<SUBJ>...` for several):
    pairs.csv            one row per reference reading with the paired board statistics
    summary.txt          per-session, per-subject and pooled numbers; fits; LOSO; residual
                         vs PI / r / HR / reference confidence
    r_vs_ref.png         R vs reference SpO2, one colour per subject, curve of the day
    spo2_vs_ref.png      our SpO2 vs reference SpO2, identity line
    residual_vs_pi.png   residual (ours - ref) vs PI, r and HR
    timeseries_<SUBJ>.png  ours vs reference on one wall clock per subject
"""

import argparse
import csv
import datetime
import glob
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import session_events  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "captures", "sessions")

APPLIED_MIN_FRAC = 0.8      # window usable if >= this fraction of samples probe-on
VALID_MIN_FRAC = 0.25       # ... and >= this fraction of samples VALID
ANOMALY_MAX_FRAC = 0.0      # ... and no part of it flagged ABNORMAL CONDITION
STAT_HALF_WINDOW_S = 10.0   # stationarity: >= 3 readings within +-10 s and ptp(ref) <= 2
STAT_MAX_PTP = 2.0
MIN_VALID_SAMPLES = 100     # a window needs this many valid samples for a median R
BAND_EDGES = ((70, 85), (85, 90), (90, 95), (95, 101))

CURVE_KEYS_A = ("spo2_r_curve_a", "spo2_cal_a", "spo2a")
CURVE_KEYS_B = ("spo2_r_curve_b", "spo2_cal_b", "spo2b")


# ----------------------------------------------------------------------------- parsing

def _snapshot_value(line, keys):
    for k in keys:
        m = re.search(rf"(?:^|\s){re.escape(k)}=(\S+)", line)
        if m:
            return m.group(1)
    return None


def parse_board_session(session_dir, replay=None):
    """All CSV parts of the (single) board, in order.

    Returns dict of numpy arrays (t_epoch_us, r, spo2, sqi, pi, ps, r_corr, hr) and the
    curve of the day {id, a, b, r_method}. Row time comes from the '# @row N clock:'
    anchors, linearly interpolated, extrapolated at the local period outside.
    """
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    if not parts:
        raise FileNotFoundError(f"no board CSV parts in {session_dir}")
    out = {k: [] for k in ("r", "spo2", "sqi", "pi", "ps", "r_corr", "hr")}
    curve = {"id": None, "a": math.nan, "b": math.nan, "r_method": None, "build": None, "inherited": None}
    cols = {}
    base_row = 0
    anchors_row, anchors_t = [], []
    for path in parts:
        part_row = 0
        with open(path, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                if not line:
                    continue
                if line.startswith("#"):
                    if line.startswith("# build="):
                        curve["build"] = line[len("# build="):].strip()
                    elif line.startswith("# @row ") and " clock: " in line:
                        anchors_row.append(base_row + int(line.split()[2]))
                        anchors_t.append(int(line.split("host_epoch_us=")[1].split()[0]))
                    elif " alg: " in line and curve["id"] is None and "cause=open" in line:
                        curve["id"] = _snapshot_value(line, ("spo2_r_curve_id",)) or "R-CURVE-UNLABELLED"
                        curve["r_method"] = _snapshot_value(line, ("spo2_r_method_id",)) or "R-METHOD-UNKNOWN"
                        a = _snapshot_value(line, CURVE_KEYS_A)
                        b = _snapshot_value(line, CURVE_KEYS_B)
                        if a is not None and b is not None:
                            curve["a"], curve["b"] = float(a), float(b)
                    continue
                if line.startswith("LED2,"):
                    cols = {n: i for i, n in enumerate(line.split(","))}
                    continue
                v = line.split(",")
                try:
                    out["r"].append(float(v[cols["R"]]))
                    out["spo2"].append(float(v[cols["SpO2"]]))
                    out["sqi"].append(float(v[cols["SpO2_SQI"]]))
                    out["pi"].append(float(v[cols["PI"]]))
                    out["ps"].append(int(v[cols["ProbeState"]]))
                    out["hr"].append(float(v[cols["HR3"]]) if "HR3" in cols else math.nan)
                    out["r_corr"].append(float(v[cols["R_CORR"]]) if "R_CORR" in cols else math.nan)
                except (KeyError, ValueError, IndexError):
                    continue  # malformed row: count nothing, keep going
                part_row += 1
        base_row += part_row
    n_rows = len(out["r"])
    if replay:
        rep = {k: [] for k in out}
        for path in parts:
            rp = os.path.join(session_dir, "derived", replay,
                              os.path.basename(path)[:-4] + "_replay.csv")
            with open(rp, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    rep["r"].append(float(row["R"]))
                    rep["spo2"].append(float(row["SpO2"]))
                    rep["sqi"].append(float(row["SpO2_SQI"]))
                    rep["pi"].append(float(row["PI"]))
                    rep["ps"].append(int(row["ProbeState"]))
                    rep["r_corr"].append(float(row["R_CORR"]) if "R_CORR" in row else math.nan)
                    rep["hr"].append(float(row["HR3"]) if "HR3" in row else math.nan)
        if len(rep["r"]) != n_rows:
            raise ValueError(f"{session_dir}: replay rows {len(rep['r'])} != original {n_rows}")
        out = rep
    if len(anchors_row) < 2:
        raise ValueError(f"{session_dir}: fewer than 2 clock anchors")
    rows = np.arange(n_rows, dtype=np.float64)
    ar = np.array(anchors_row, dtype=np.float64)
    at = np.array(anchors_t, dtype=np.float64)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0])
    per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    board = {k: np.array(v, dtype=(np.int32 if k == "ps" else np.float64)) for k, v in out.items()}
    board["t"] = t
    return board, curve


def parse_reference(session_dir):
    """VideoNest OCR readings: arrays t_epoch_us, spo2, conf. Missing file -> empty."""
    t, spo2, conf = [], [], []
    path = os.path.join(session_dir, "reference_spo2.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            rd = csv.DictReader(row for row in f if not row.startswith("#"))
            for row in rd:
                if row.get("kind") != "reading" or not row.get("spo2"):
                    continue
                t.append(int(row["t_epoch_us"]))
                spo2.append(float(row["spo2"]))
                conf.append(float(row["conf"] or 0))
    return np.array(t, dtype=np.float64), np.array(spo2), np.array(conf)


# ----------------------------------------------------------------------------- pairing

def pair_session(subject, name, board, ref_t, ref_spo2, ref_conf, anomalies, window_s, states):
    """One output row per reference reading."""
    pairs = []
    w_us = window_s * 1e6
    for i in range(len(ref_t)):
        t1 = ref_t[i]
        i0 = int(np.searchsorted(board["t"], t1 - w_us, side="right"))
        i1 = int(np.searchsorted(board["t"], t1, side="right"))
        n = i1 - i0
        row = {
            "subject": subject, "session": name, "t_epoch_us": int(t1),
            "ref_spo2": ref_spo2[i], "ref_conf": ref_conf[i],
            "n_samples": n, "applied_frac": math.nan, "valid_frac": math.nan,
            "r_med": math.nan, "our_spo2_med": math.nan, "sqi_med": math.nan,
            "pi_med": math.nan, "r_corr_med": math.nan, "hr_med": math.nan,
            "anomaly_frac": session_events.covered_fraction(anomalies, t1 - w_us, t1),
            "usable": 0, "stationary": 0,
        }
        if n:
            sl = slice(i0, i1)
            ps, r, spo2 = board["ps"][sl], board["r"][sl], board["spo2"][sl]
            app = np.isin(ps, states)
            valid = app & np.isfinite(r) & (spo2 > 1)
            row["applied_frac"] = float(app.mean())
            row["valid_frac"] = float(valid.mean())
            if valid.sum() >= MIN_VALID_SAMPLES:
                row["r_med"] = float(np.median(r[valid]))
                row["our_spo2_med"] = float(np.median(spo2[valid]))
                row["sqi_med"] = float(np.median(board["sqi"][sl][valid]))
                row["pi_med"] = float(np.median(board["pi"][sl][valid]))
                row["r_corr_med"] = float(np.nanmedian(board["r_corr"][sl][valid]))
                row["hr_med"] = float(np.nanmedian(board["hr"][sl][valid]))
            row["usable"] = int(row["applied_frac"] >= APPLIED_MIN_FRAC
                                and row["valid_frac"] >= VALID_MIN_FRAC
                                and row["anomaly_frac"] <= ANOMALY_MAX_FRAC
                                and math.isfinite(row["r_med"]))
        pairs.append(row)
    # stationarity of the reference around each reading (same rule as r_regression_test)
    for p in pairs:
        w = [q for q in pairs if abs(q["t_epoch_us"] - p["t_epoch_us"]) <= STAT_HALF_WINDOW_S * 1e6]
        vals = [q["ref_spo2"] for q in w]
        p["stationary"] = int(len(w) >= 3 and (max(vals) - min(vals)) <= STAT_MAX_PTP)
    return pairs


# ----------------------------------------------------------------------------- statistics

def binfit(r, y):
    """Weighted LS of reference on per-bin median R (bins = integer ref SpO2, >= 10 pairs).

    Returns a, b, rms, scatter (median per-bin IQR of R times |b|, in SpO2 points), nbins.
    """
    ok = np.isfinite(r)
    r, y = r[ok], y[ok]
    keys = [k for k in np.unique(np.round(y)) if (np.round(y) == k).sum() >= 10]
    if len(keys) < 2:
        return math.nan, math.nan, math.nan, math.nan, len(keys)
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
    return float(a), float(b), rms, scatter, len(keys)


def spearman(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return math.nan
    from scipy.stats import spearmanr
    return float(spearmanr(x[ok], y[ok])[0])


def q(v, p):
    return float(np.percentile(v, p))


# ----------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("subjects", nargs="+", help="subject codes, e.g. SUBJ10 SUBJ11")
    ap.add_argument("--sessions-dir", default=SESSIONS_DIR)
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--window", type=float, default=8.0,
                    help="monitor averaging window [s] ending at each reading (default 8)")
    ap.add_argument("--probe-states", default="1,2",
                    help="ProbeState values counted as probe-on (default 1,2: OT_HIGH, APPLIED)")
    ap.add_argument("--exclude", nargs="*", default=[], help="session names to skip")
    ap.add_argument("--replay", default=None, help="derived/<name> replay to read instead of the live columns")
    ap.add_argument("--curve", default=None, help="a,b of the curve to evaluate (required with --replay)")
    args = ap.parse_args(argv)
    states = tuple(int(s) for s in args.probe_states.split(","))
    if args.replay and not args.curve:
        ap.error("--replay needs --curve a,b")
    forced_curve = None
    if args.curve:
        a, b = (float(v) for v in args.curve.split(","))
        forced_curve = {"id": f"given({a},{b})", "a": a, "b": b, "r_method": "given"}
    if args.out is None:
        if len(args.subjects) == 1:
            s = args.subjects[0]
            args.out = os.path.join(args.sessions_dir, s, f"{s}_BIAS_ANALYSIS")
        else:
            args.out = os.path.join(args.sessions_dir, "BIAS_ANALYSIS_" + "_".join(args.subjects))
    os.makedirs(args.out, exist_ok=True)

    all_pairs, lines, per_session, curves = [], [], {}, {}
    lines.append(f"spo2_bias_analysis: subjects {' '.join(args.subjects)}; window {args.window:.0f} s; "
                 f"probe-on states {states}; usable = probe-on >= {APPLIED_MIN_FRAC:.0%}, valid >= "
                 f"{VALID_MIN_FRAC:.0%}, no ABNORMAL CONDITION, >= {MIN_VALID_SAMPLES} valid samples"
                 + (f"; replay {args.replay}" if args.replay else "; live firmware columns"))
    for subject in args.subjects:
        dirs = sorted(d for d in glob.glob(os.path.join(args.sessions_dir, subject, f"{subject}_*_*_*"))
                      if os.path.isdir(d) and os.path.basename(d) not in args.exclude)
        if not dirs:
            lines.append(f"{subject}: no sessions found")
            continue
        for d in dirs:
            name = os.path.basename(d)
            board, curve = parse_board_session(d, args.replay)
            if forced_curve:
                curve = forced_curve
                board["spo2"] = np.where(np.isfinite(board["r"]) & (board["spo2"] > 1),
                                         curve["a"] - curve["b"] * board["r"], board["spo2"])
            curves[name] = curve
            ref_t, ref_spo2, ref_conf = parse_reference(d)
            anomalies = session_events.anomaly_intervals(d, subject)
            pairs = pair_session(subject, name, board, ref_t, ref_spo2, ref_conf, anomalies,
                                 args.window, states)
            all_pairs.extend(pairs)
            per_session[name] = (subject, board, ref_t, ref_spo2)
            dur_min = (board["t"][-1] - board["t"][0]) / 60e6
            app = float(np.isin(board["ps"], states).mean())
            usable = [p for p in pairs if p["usable"]]
            lines.append(
                f"{name}: {len(board['t'])} samples ({dur_min:.1f} min), probe-on {100 * app:.1f}%, "
                f"ref readings {len(pairs)}, usable pairs {len(usable)}, stationary+usable "
                f"{sum(p['stationary'] for p in usable)}; curve "
                + (f"{curve['id']} ({curve['a']:.2f} - {curve['b']:.2f} R, {curve['r_method']})"
                   if curve["id"] else "NO alg: snapshot (see below)")
                + (f"; {len(anomalies)} ABNORMAL stretch(es), "
                   f"{sum(p['anomaly_frac'] > ANOMALY_MAX_FRAC for p in pairs)} pairs dropped"
                   if anomalies else ""))
            if usable:
                bias = np.array([p["our_spo2_med"] - p["ref_spo2"] for p in usable])
                lines.append(f"    bias ours-ref: median {np.median(bias):+.1f} pts (p10 {q(bias, 10):+.1f}, "
                             f"p90 {q(bias, 90):+.1f}); ref range "
                             f"{min(p['ref_spo2'] for p in usable):.0f}-{max(p['ref_spo2'] for p in usable):.0f}; "
                             f"PI median {np.median([p['pi_med'] for p in usable]):.2f} %, "
                             f"r median {np.nanmedian([p['r_corr_med'] for p in usable]):.3f}")

    # A session whose capture carries no `alg:` snapshot (the hub's $LCFG answer never reached the
    # recorder) inherits the curve of another session of this run with the same firmware build:
    # the curve is compiled into the firmware and nothing changed it on the day ($SET is not used).
    for name, c in curves.items():
        if c["id"] is None:
            donor = next((n for n, d in curves.items() if d["id"] is not None and d["build"] == c["build"]
                          and d["inherited"] is None), None)
            if donor is None:
                raise SystemExit(f"{name}: no alg: snapshot and no session with build {c['build']} "
                                 f"to inherit the curve from; give --curve a,b")
            c.update({k: curves[donor][k] for k in ("id", "a", "b", "r_method")}, inherited=donor)
            lines.append(f"  {name}: NO alg: snapshot in the capture; curve inherited from {donor} "
                         f"(same build {c['build']})")

    if not all_pairs:
        lines.append("no reference readings at all")
        print("\n".join(lines))
        return 1

    # ---- pairs.csv ----
    with open(os.path.join(args.out, "pairs.csv"), "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(all_pairs[0].keys()))
        wr.writeheader()
        wr.writerows(all_pairs)

    usable = [p for p in all_pairs if p["usable"]]
    stat = [p for p in usable if p["stationary"]]
    ids = sorted({c["id"] for c in curves.values()})
    one_curve = len(ids) == 1
    lines.append("")
    lines.append(f"TOTAL usable pairs {len(usable)} / {len(all_pairs)}; stationary {len(stat)}; "
                 f"curve(s) of the day: {', '.join(ids)}")

    def arr(rows, k):
        return np.array([p[k] for p in rows], dtype=float)

    def describe(rows, label):
        if len(rows) < 3:
            lines.append(f"{label:40s} n={len(rows)}: too few pairs")
            return
        r, y, ours = arr(rows, "r_med"), arr(rows, "ref_spo2"), arr(rows, "our_spo2_med")
        bias = ours - y
        rho = spearman(r, y)
        a, b, rms, scat, nb = binfit(r, y)
        lines.append(f"{label:40s} n={len(rows):5d}  bias med {np.median(bias):+.2f} mean {bias.mean():+.2f} "
                     f"sd {bias.std():.2f} |bias| med {np.median(np.abs(bias)):.2f}  medR {np.median(r):.3f}  "
                     f"ref {np.median(y):.0f} [{y.min():.0f}-{y.max():.0f}]  rho {rho:+.2f}  "
                     f"binfit {a:.2f} {b:+.2f} R ({nb} bins, scatter {scat:.2f})")

    lines.append("")
    lines.append("Per subject and pooled, USABLE pairs (bias = ours - ref, points; binfit = weighted LS on "
                 "per-integer-SpO2 bins of median R):")
    describe(usable, "pooled")
    for s in args.subjects:
        describe([p for p in usable if p["subject"] == s], f"  {s}")
    lines.append("Same, STATIONARY pairs only (the set the curves were fitted on):")
    describe(stat, "pooled")
    for s in args.subjects:
        describe([p for p in stat if p["subject"] == s], f"  {s}")

    # error of the day's curve by reference band
    if one_curve:
        c = curves[next(iter(curves))]
        lines.append(f"Error of the day's curve {c['id']} by reference band, stationary pairs "
                     f"(median [p10, p90]):")
        for lo, hi in BAND_EDGES:
            rows = [p for p in stat if lo <= p["ref_spo2"] < hi]
            if len(rows) < 10:
                continue
            e = arr(rows, "our_spo2_med") - arr(rows, "ref_spo2")
            lines.append(f"  ref {lo}-{hi - 1}: n={len(rows):4d}  {np.median(e):+.2f}  [{q(e, 10):+.2f}, {q(e, 90):+.2f}]")

    # leave-one-subject-out on the stationary set
    if len(args.subjects) > 1:
        lines.append("Leave-one-subject-out (binfit on the others, error on the held-out subject, stationary):")
        for s in args.subjects:
            fit_rows = [p for p in stat if p["subject"] != s]
            test_rows = [p for p in stat if p["subject"] == s]
            if len(fit_rows) < 20 or len(test_rows) < 3:
                lines.append(f"  -> {s}: too few pairs")
                continue
            a, b, *_ = binfit(arr(fit_rows, "r_med"), arr(fit_rows, "ref_spo2"))
            if not math.isfinite(a):
                lines.append(f"  -> {s}: fit on the others has < 2 bins")
                continue
            err = (a + b * arr(test_rows, "r_med")) - arr(test_rows, "ref_spo2")
            lines.append(f"  others ({a:.2f} {b:+.2f} R) -> {s}: n={len(test_rows)} median error "
                         f"{np.median(err):+.2f}, median |err| {np.median(np.abs(err)):.2f} pts")

    # residual dependence
    lines.append("Residual (ours - ref) vs window statistics, usable pairs, Spearman rho (pooled / per subject):")
    for k, label in (("pi_med", "PI"), ("r_corr_med", "r (R_CORR)"), ("hr_med", "HR3"),
                     ("ref_conf", "OCR confidence"), ("sqi_med", "SpO2_SQI")):
        res = arr(usable, "our_spo2_med") - arr(usable, "ref_spo2")
        x = arr(usable, k)
        per = []
        for s in args.subjects:
            m = np.array([p["subject"] == s for p in usable])
            per.append(f"{s} {spearman(x[m], res[m]):+.2f}")
        lines.append(f"  {label:15s} pooled {spearman(x, res):+.2f}   " + "  ".join(per))
    # PI quintiles
    pi = arr(usable, "pi_med")
    res = arr(usable, "our_spo2_med") - arr(usable, "ref_spo2")
    okp = np.isfinite(pi)
    if okp.sum() >= 25:
        edges = np.percentile(pi[okp], [0, 20, 40, 60, 80, 100])
        lines.append("  residual by PI quintile (median): " + "  ".join(
            f"[{edges[i]:.2f}-{edges[i + 1]:.2f}%] {np.median(res[okp & (pi >= edges[i]) & (pi <= edges[i + 1])]):+.2f}"
            for i in range(5)))

    # ---- plots ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    colors = {s: c for s, c in zip(args.subjects, plt.rcParams["axes.prop_cycle"].by_key()["color"])}
    title = " ".join(args.subjects) + (f" ({args.replay})" if args.replay else "")

    if usable:
        fig, ax = plt.subplots(figsize=(8, 6))
        for s in args.subjects:
            rows = [p for p in usable if p["subject"] == s]
            ax.scatter(arr(rows, "r_med"), arr(rows, "ref_spo2"), s=10, alpha=0.6, color=colors[s],
                       label=f"{s} (n={len(rows)})")
        rall = arr(usable, "r_med")
        rx = np.linspace(min(rall.min(), 0.4), max(rall.max(), 1.1), 100)
        for cid in ids:
            c = next(v for v in curves.values() if v["id"] == cid)
            ax.plot(rx, c["a"] - c["b"] * rx, "k-", lw=1.2, label=f"{cid}: {c['a']:.1f} - {c['b']:.1f} R")
        a, b, *_ = binfit(arr(stat, "r_med"), arr(stat, "ref_spo2")) if len(stat) >= 20 else (math.nan, math.nan)
        if math.isfinite(a):
            ax.plot(rx, a + b * rx, "k--", lw=1, label=f"binfit, stationary: {a:.1f} {b:+.1f} R")
        ax.set_xlabel("R (median of window)")
        ax.set_ylabel("reference SpO2 [%]")
        ax.set_title(f"{title}: R vs reference SpO2 ({args.window:.0f} s windows)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, "r_vs_ref.png"), dpi=130)

        fig, ax = plt.subplots(figsize=(7, 7))
        y, ours = arr(usable, "ref_spo2"), arr(usable, "our_spo2_med")
        for s in args.subjects:
            rows = [p for p in usable if p["subject"] == s]
            ax.scatter(arr(rows, "ref_spo2"), arr(rows, "our_spo2_med"), s=10, alpha=0.6,
                       color=colors[s], label=s)
        lim = (min(y.min(), ours.min()) - 2, max(y.max(), ours.max()) + 2)
        ax.plot(lim, lim, "k--", lw=1, label="identity")
        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_aspect("equal")
        ax.set_xlabel("reference SpO2 (VideoNest OCR) [%]")
        ax.set_ylabel("our SpO2 (median of window) [%]")
        ax.set_title(f"{title}: ours vs reference, n={len(y)}, median bias {np.median(ours - y):+.1f} pts")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, "spo2_vs_ref.png"), dpi=130)

        fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
        for ax, (k, label) in zip(axes, (("pi_med", "PI [%]"), ("r_corr_med", "r (R_CORR)"), ("hr_med", "HR3 [BPM]"))):
            for s in args.subjects:
                rows = [p for p in usable if p["subject"] == s]
                ax.scatter(arr(rows, k), arr(rows, "our_spo2_med") - arr(rows, "ref_spo2"), s=8,
                           alpha=0.6, color=colors[s], label=s)
            ax.axhline(0, color="k", lw=0.8)
            ax.set_xlabel(label)
            ax.set_ylabel("ours - ref [pts]")
            ax.grid(True, alpha=0.3)
        axes[0].legend(fontsize=8)
        fig.suptitle(f"{title}: residual vs window statistics")
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, "residual_vs_pi.png"), dpi=130)

    def to_dt(t_us):
        return [datetime.datetime.fromtimestamp(v / 1e6) for v in t_us]

    for s in args.subjects:
        items = [(n, v) for n, v in per_session.items() if v[0] == s]
        if not items:
            continue
        fig, ax = plt.subplots(figsize=(16, 5))
        for i, (name, (_, board, ref_t, ref_spo2)) in enumerate(items):
            app = np.isin(board["ps"], states)
            our = np.where(app, board["spo2"], np.nan)
            ax.plot(to_dt(board["t"][::25]), our[::25], "-", lw=0.7, color="tab:blue",
                    label="ours (probe-on only)" if i == 0 else None)
            ax.plot(to_dt(ref_t), ref_spo2, ".", ms=3, color="tab:red",
                    label="reference (OCR)" if i == 0 else None)
            for edge in (board["t"][0], board["t"][-1]):
                ax.axvline(to_dt([edge])[0], color="gray", lw=0.8, ls="--", alpha=0.7)
            ax.text(to_dt([board["t"][0]])[0], 103, "  " + name.split("_")[-1], fontsize=8, color="gray", va="top")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.set_title(f"{s}: campaign on one clock (dashed = session start/end)")
        ax.set_ylabel("SpO2 [%]")
        ax.set_ylim(40, 105)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="lower right")
        ax.set_xlabel("local wall-clock time")
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, f"timeseries_{s}.png"), dpi=130)
        plt.close(fig)

    text = "\n".join(lines) + "\n"
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
