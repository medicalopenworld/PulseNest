"""R -> SpO2 analysis of campaign 20260923_HOSPNAV_SUBJ08.

Pairs each reference-monitor reading (VideoNest OCR, reference_spo2.csv) with the
board's R over the monitor's averaging window, then compares the current linear
calibration (SpO2 = spo2a - spo2b * R) against what the reference implies.

Outputs (all in this directory):
    pairs.csv         one row per reference reading with the paired board stats
    summary.txt       per-session and aggregate numbers, fitted curve
    r_vs_ref.png      scatter R vs reference SpO2 + current and fitted curves
    timeseries.png    per-session time series: ours vs reference

Run from anywhere: paths are resolved relative to this file.
"""

import csv
import glob
import math
import os
import sys

import numpy as np

# --replay: take the board signals from the offline runner's *_replay.csv files
# (incunest_offline_runner v0.20, lib >= v0.96 with the v0.95 rsqm_ot_thr) instead of
# the columns the firmware produced that day. Clock anchors still come from the
# original parts -- replay rows are 1:1 with original rows.
REPLAY = "--replay" in sys.argv
REPLAY_DIR = os.path.join("derived", "replay_lib0.96")   # runner v0.21 output, per session
SUFFIX = "_replay" if REPLAY else ""

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))  # repo root
from pulsenest import session_events  # noqa: E402
SESSIONS_DIR = os.path.dirname(HERE)
CAMPAIGN_GLOB = "SUBJ08_HOSPNAV_20260923_*"

REF_WINDOW_S = 8.0          # assumed monitor averaging window (model not recorded)
APPLIED_MIN_FRAC = 0.8      # window usable if >= this fraction of samples probe-on
VALID_MIN_FRAC = 0.25       # ... and >= this fraction of samples VALID (see below)
ANOMALY_MAX_FRAC = 0.0      # ... and no part of it flagged ABNORMAL CONDITION by the
# operator (ANOMALY_START/END in session_events.csv, 2026-10-16). The fraction is kept
# as a column, so a re-analysis can ignore the flag. The 2026-09-23 campaign has none.
# Probe-on states accepted FOR THIS CAMPAIGN: 2 (PROBE_APPLIED) and 1 (PROBE_OT_HIGH).
# On 2026-09-23 the firmware still ran rsqm_ot_thr = 1.0e-4 (raised to 1.5e-4 in lib
# v0.95 the day after, from this subject's own data): SUBJ08's OT_HIGH stretches were
# an applied probe on thin tissue, not a probe in air (Alex, 2026-09-24).
ACCEPTED_PROBE_STATES = (1, 2)
# A sample is VALID when the probe is on, R is finite and the SpO2 output is
# producing (> 1: the firmware emits ~0 while its own gates hold the output back).

# Current calibration, from the $CFG header of every capture of the campaign.
SPO2_A = 114.9208
SPO2_B = 30.5547


def parse_board_session(session_dir):
    """All CSV parts of the (single) board, in order.

    Returns dict of numpy arrays: t_epoch_us, r, spo2, spo2_sqi, pi, probe_state.
    Row time comes from the '# @row N clock:' markers (host_epoch_us), linearly
    interpolated between markers and extrapolated at the nominal rate outside.
    """
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    if not parts:
        raise FileNotFoundError(f"no board CSV parts in {session_dir}")
    replay_cols = {k: [] for k in ("r", "spo2", "sqi", "pi", "ps")}
    if REPLAY:
        for path in parts:
            rp = os.path.join(session_dir, REPLAY_DIR,
                              os.path.basename(path)[:-4] + "_replay.csv")
            with open(rp, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    replay_cols["r"].append(float(row["R"]))
                    replay_cols["spo2"].append(float(row["SpO2"]))
                    replay_cols["sqi"].append(float(row["SpO2_SQI"]))
                    replay_cols["pi"].append(float(row["PI"]))
                    replay_cols["ps"].append(int(row["ProbeState"]))
    cols = {}
    rows_t = []
    out = {k: [] for k in ("t", "r", "spo2", "sqi", "pi", "ps")}
    base_row = 0  # rows accumulated from previous parts
    anchors_row, anchors_t = [], []
    for path in parts:
        part_row = 0
        with open(path, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                if not line:
                    continue
                if line.startswith("#"):
                    if " clock: " in line and line.startswith("# @row "):
                        n = int(line.split()[2])
                        host = line.split("host_epoch_us=")[1].split()[0]
                        anchors_row.append(base_row + n)
                        anchors_t.append(int(host))
                    continue
                if line.startswith("LED2,"):  # column header
                    names = line.split(",")
                    cols = {n: i for i, n in enumerate(names)}
                    continue
                v = line.split(",")
                try:
                    out["r"].append(float(v[cols["R"]]))
                    out["spo2"].append(float(v[cols["SpO2"]]))
                    out["sqi"].append(float(v[cols["SpO2_SQI"]]))
                    out["pi"].append(float(v[cols["PI"]]))
                    out["ps"].append(int(v[cols["ProbeState"]]))
                except (KeyError, ValueError, IndexError):
                    continue  # malformed row: count nothing, keep going
                part_row += 1
        base_row += part_row
    n_rows = len(out["r"])
    if REPLAY:
        if len(replay_cols["r"]) != n_rows:
            raise ValueError(f"{session_dir}: replay rows {len(replay_cols['r'])} != original {n_rows}")
        out = replay_cols
    if len(anchors_row) < 2:
        raise ValueError(f"{session_dir}: fewer than 2 clock anchors")
    # piecewise-linear row -> epoch mapping (numpy interp extrapolates flat, so
    # extend the ends at the local sample period instead)
    rows = np.arange(n_rows, dtype=np.float64)
    ar = np.array(anchors_row, dtype=np.float64)
    at = np.array(anchors_t, dtype=np.float64)
    t = np.interp(rows, ar, at)
    per0 = (at[1] - at[0]) / (ar[1] - ar[0])
    per1 = (at[-1] - at[-2]) / (ar[-1] - ar[-2])
    t[rows < ar[0]] = at[0] + (rows[rows < ar[0]] - ar[0]) * per0
    t[rows > ar[-1]] = at[-1] + (rows[rows > ar[-1]] - ar[-1]) * per1
    return {
        "t": t,
        "r": np.array(out["r"]),
        "spo2": np.array(out["spo2"]),
        "sqi": np.array(out["sqi"]),
        "pi": np.array(out["pi"]),
        "ps": np.array(out["ps"], dtype=np.int32),
    }


def parse_reference(session_dir):
    """VideoNest OCR readings: arrays t_epoch_us, spo2, conf."""
    t, spo2, conf = [], [], []
    with open(os.path.join(session_dir, "reference_spo2.csv"),
              encoding="utf-8", newline="") as f:
        rd = csv.DictReader(row for row in f if not row.startswith("#"))
        for row in rd:
            if row.get("kind") != "reading" or not row.get("spo2"):
                continue
            t.append(int(row["t_epoch_us"]))
            spo2.append(float(row["spo2"]))
            conf.append(float(row["conf"] or 0))
    return np.array(t, dtype=np.float64), np.array(spo2), np.array(conf)


def pair_session(name, board, ref_t, ref_spo2, ref_conf, anomalies=()):
    """One output row per reference reading. `anomalies`: [(t0_us, t1_us)] flagged."""
    pairs = []
    w_us = REF_WINDOW_S * 1e6
    for i in range(len(ref_t)):
        t1 = ref_t[i]
        sel = (board["t"] > t1 - w_us) & (board["t"] <= t1)
        n = int(sel.sum())
        row = {
            "session": name, "t_epoch_us": int(t1),
            "ref_spo2": ref_spo2[i], "ref_conf": ref_conf[i],
            "n_samples": n, "applied_frac": math.nan, "valid_frac": math.nan,
            "r_med": math.nan, "our_spo2_med": math.nan,
            "sqi_med": math.nan, "pi_med": math.nan,
            "anomaly_frac": session_events.covered_fraction(anomalies, t1 - w_us, t1),
            "usable": 0,
        }
        if n:
            ps = board["ps"][sel]
            r = board["r"][sel]
            spo2 = board["spo2"][sel]
            app = np.isin(ps, ACCEPTED_PROBE_STATES)
            valid = app & np.isfinite(r) & (spo2 > 1)
            row["applied_frac"] = float(app.mean())
            row["valid_frac"] = float(valid.mean())
            if valid.any():
                row["r_med"] = float(np.median(r[valid]))
                row["our_spo2_med"] = float(np.median(spo2[valid]))
                row["sqi_med"] = float(np.median(board["sqi"][sel][valid]))
                row["pi_med"] = float(np.median(board["pi"][sel][valid]))
            row["usable"] = int(row["applied_frac"] >= APPLIED_MIN_FRAC
                                and row["valid_frac"] >= VALID_MIN_FRAC
                                and row["anomaly_frac"] <= ANOMALY_MAX_FRAC)
        pairs.append(row)
    return pairs


def theil_sen(x, y):
    """Median-of-slopes fit, robust to OCR glitches; subsampled if huge."""
    n = len(x)
    idx = np.arange(n)
    slopes = []
    for i in range(n - 1):
        dx = x[i + 1:] - x[i]
        dy = y[i + 1:] - y[i]
        ok = np.abs(dx) > 1e-6
        slopes.extend((dy[ok] / dx[ok]).tolist())
    b = float(np.median(slopes))
    a = float(np.median(y - b * x))
    return a, b


def main():
    session_dirs = sorted(
        d for d in glob.glob(os.path.join(SESSIONS_DIR, CAMPAIGN_GLOB))
        if os.path.isdir(d)
    )
    all_pairs = []
    lines = []
    per_session = {}
    for d in session_dirs:
        name = os.path.basename(d)
        board = parse_board_session(d)
        ref_t, ref_spo2, ref_conf = parse_reference(d)
        anomalies = session_events.anomaly_intervals(d, "SUBJ08")
        pairs = pair_session(name, board, ref_t, ref_spo2, ref_conf, anomalies)
        all_pairs.extend(pairs)
        per_session[name] = (board, ref_t, ref_spo2)
        dur_min = (board["t"][-1] - board["t"][0]) / 60e6
        app = float(np.isin(board["ps"], ACCEPTED_PROBE_STATES).mean())
        usable = [p for p in pairs if p["usable"]]
        lines.append(
            f"{name}: {len(board['t'])} samples ({dur_min:.1f} min), "
            f"probe-on (state 1|2) {100 * app:.1f}%, ref readings {len(pairs)}, "
            f"usable pairs {len(usable)}"
            + (f", {len(anomalies)} stretch(es) flagged ABNORMAL CONDITION, "
               f"{sum(p['anomaly_frac'] > ANOMALY_MAX_FRAC for p in pairs)} pairs dropped"
               if anomalies else "")
        )
        if usable:
            bias = np.array([p["our_spo2_med"] - p["ref_spo2"] for p in usable])
            lines.append(
                f"    bias ours-ref: median {np.median(bias):+.1f} pts "
                f"(p10 {np.percentile(bias, 10):+.1f}, p90 {np.percentile(bias, 90):+.1f}); "
                f"ref range {min(p['ref_spo2'] for p in usable):.0f}-"
                f"{max(p['ref_spo2'] for p in usable):.0f}"
            )

    # ---- aggregate ----
    usable = [p for p in all_pairs if p["usable"]]
    lines.append("")
    lines.append(f"TOTAL usable pairs: {len(usable)} / {len(all_pairs)}")
    if usable:
        r = np.array([p["r_med"] for p in usable])
        y = np.array([p["ref_spo2"] for p in usable])
        ours = np.array([p["our_spo2_med"] for p in usable])
        bias = ours - y
        lines.append(
            f"bias ours-ref: median {np.median(bias):+.1f} pts, "
            f"mean {bias.mean():+.1f}, sd {bias.std():.1f}"
        )
        lines.append(
            f"R (median per window): {np.median(r):.3f} "
            f"(p10 {np.percentile(r, 10):.3f}, p90 {np.percentile(r, 90):.3f})"
        )
        lines.append(
            f"ref SpO2: {np.median(y):.0f} (min {y.min():.0f}, max {y.max():.0f}) "
            f"- narrow range means only the offset is estimable, not the slope"
        )
        # what the current curve says at the median R, vs what the monitor said
        lines.append(
            f"current curve at median R: "
            f"{SPO2_A - SPO2_B * np.median(r):.1f} vs ref median {np.median(y):.0f}"
        )
        # offset-only correction (slope kept): a' = median(ref + b*R)
        a_off = float(np.median(y + SPO2_B * r))
        lines.append(
            f"offset-only recalibration (slope {SPO2_B} kept): "
            f"spo2a {SPO2_A:.4f} -> {a_off:.4f} ({a_off - SPO2_A:+.1f} pts)"
        )
        # free linear fit, for the record (unreliable with a narrow SpO2 range)
        a_ts, b_ts = theil_sen(r, y)
        lines.append(
            f"free Theil-Sen fit (INDICATIVE ONLY, narrow ref range): "
            f"SpO2 = {a_ts:.2f} {b_ts:+.2f}*R  (current: {SPO2_A} - {SPO2_B}*R)"
        )

    # ---- pairs.csv ----
    out_csv = os.path.join(HERE, f"pairs{SUFFIX}.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(all_pairs[0].keys()))
        wr.writeheader()
        wr.writerows(all_pairs)

    # ---- plots ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if usable:
        fig, ax = plt.subplots(figsize=(8, 6))
        sc = ax.scatter(r, y, s=12, c=[p["pi_med"] for p in usable],
                        cmap="viridis", label="pairs (ref vs our R)")
        fig.colorbar(sc, ax=ax, label="PI (median in window)")
        rx = np.linspace(min(r.min(), 0.4), max(r.max(), 1.1), 100)
        ax.plot(rx, SPO2_A - SPO2_B * rx, "r-",
                label=f"current: {SPO2_A:.1f} - {SPO2_B:.1f} R")
        ax.plot(rx, a_off - SPO2_B * rx, "g--",
                label=f"offset-only: {a_off:.1f} - {SPO2_B:.1f} R")
        ax.set_xlabel("R (ratio of ratios, median of window)")
        ax.set_ylabel("reference SpO2 [%]")
        ax.set_title("20260923_HOSPNAV_SUBJ08: R vs reference SpO2 "
                     f"({REF_WINDOW_S:.0f} s windows, probe-on >= {APPLIED_MIN_FRAC:.0%})")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, f"r_vs_ref{SUFFIX}.png"), dpi=130)

        fig, ax = plt.subplots(figsize=(7, 7))
        sc = ax.scatter(y, ours, s=12, c=[p["pi_med"] for p in usable],
                        cmap="viridis")
        fig.colorbar(sc, ax=ax, label="PI (median in window)")
        lim = (min(y.min(), ours.min()) - 2, max(y.max(), ours.max()) + 2)
        ax.plot(lim, lim, "k--", lw=1, label="identity (ours = reference)")
        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_aspect("equal")
        ax.set_xlabel("reference SpO2 (VideoNest OCR) [%]")
        ax.set_ylabel("our SpO2 (library, median of window) [%]")
        ax.set_title("20260923_HOSPNAV_SUBJ08: our SpO2 vs reference SpO2\n"
                     f"n={len(y)}, median bias {np.median(bias):+.1f} pts")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, f"spo2_vs_ref{SUFFIX}.png"), dpi=130)

    import datetime
    import matplotlib.dates as mdates

    def to_dt(t_us):
        # local wall clock, the one CLOCK ANCHOR and the room clock show
        return [datetime.datetime.fromtimestamp(v / 1e6) for v in t_us]

    # One shared wall-clock axis for the whole campaign: session boundaries are then
    # facts on a common scale, not an artefact of per-panel axis margins.
    fig, ax = plt.subplots(figsize=(16, 5))
    for i, (name, (board, ref_t, ref_spo2)) in enumerate(per_session.items()):
        app = np.isin(board["ps"], ACCEPTED_PROBE_STATES)
        our = np.where(app, board["spo2"], np.nan)
        ax.plot(to_dt(board["t"][::25]), our[::25], "-", lw=0.7, color="tab:blue",
                label="ours (probe-on only)" if i == 0 else None)
        ax.plot(to_dt(ref_t), ref_spo2, ".", ms=3, color="tab:red",
                label="reference (OCR)" if i == 0 else None)
        for edge in (board["t"][0], board["t"][-1]):
            ax.axvline(to_dt([edge])[0], color="gray", lw=0.8, ls="--", alpha=0.7)
        ax.text(to_dt([board["t"][0]])[0], 103, "  " + name.split("_")[1],
                fontsize=8, color="gray", va="top")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.set_title("20260923_HOSPNAV_SUBJ08: campaign on one clock "
                 "(dashed lines = session start/end)")
    ax.set_ylabel("SpO2 [%]")
    ax.set_ylim(40, 105)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlabel("local wall-clock time [HH:MM:SS]")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, f"timeseries{SUFFIX}.png"), dpi=130)

    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, f"summary{SUFFIX}.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
