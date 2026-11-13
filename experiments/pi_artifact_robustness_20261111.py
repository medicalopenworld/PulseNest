"""PI under motion artefacts: a robust PI and an artefact ratio, measured on the neonatal captures.

Why this exists
---------------
PI-METHOD-1 is 2*sqrt(2) * RMS(band-passed OT_IR) / mean(OT_IR) over a 6 s boxcar. One brief
motion artefact puts its energy in the window for exactly 6 s, so PI rises for 6 s (Alex,
2026-11-11, seen live). A synthetic bump (0.4 s, 5x the beat) gave PI x2.3 for 6.4 s; the median
of the energy of the six 1 s sub-windows gave x1.05. Alex's concern: an artefact-immune PI may lose
what PI does for other algorithms (the SpO2 SQI ramp, `spo2_pi_max`). Proposal measured here: two
outputs instead of one,
    PI_box = today's number (energy of the whole window),
    PI_rob = 2*sqrt(2) * sqrt(median of the six 1 s sub-window mean energies) / mean(OT_IR),
    Q      = PI_box / PI_rob   (about 1 at rest, large when part of the window is not pulse).

What it does
------------
Every HOSPNAV session with `derived/replay_lib0.108_inputot/` (the current PI definition, OT
input) is read sample by sample: OT_LED1, ProbeState, the library's PI, HR3, HR3_SQI, R, r.
PI-METHOD-1 is replicated in Python (the library's band-pass coefficients, reset and precharge
while the probe is not applied, 100 ms block sums, 6 s window) and checked against the replay's PI;
PI_rob and Q come from the same block sums. Then:
  A  replica check (replica vs library PI);
  B  per subject: level, PI_rob / PI_box, stability (|PI(t+6 s)/PI(t) - 1|);
  C  isolated bursts (one 1 s chunk with >= 9x the local median energy, alone in +-7 s): peak of
     each PI against its value before the burst, and time above +20 %;
  D  Q as an artefact indicator: time above thresholds, split by HR3 valid / not valid;
  E  against the ward monitor (8 s windows ending at each reference reading, as
     tools/spo2_bias_analysis.py): |bias| and share beyond 4 points by Q band, with and without
     the pulse gate; the SpO2 SQI ramp fed with PI_box and with PI_rob in good and bad windows;
  F  `spo2_pi_max`: time with PI_box > 20 % and what PI_rob and Q read there.

    python experiments/pi_artifact_robustness_20261111.py [--replay replay_lib0.108_inputot]

Outputs in captures/sessions/PI_ROBUST_ANALYSIS_20261111/ (not versioned): pi_blocks_<subject>.csv
is not written (too large); summary.txt is the printed report.

Result (2026-11-11; report: docs/pi_artifact_robustness_20261111.md)
------
- Replica = library PI within 0.1 % (median). 173 min applied, 69 isolated bursts.
- Median of six 1 s chunks: same burst peak as today's PI (x1.5-2.0), 2-3 s shorter; real neonatal
  artefacts last >= 3 s. Median of twelve (section G): peak x1.2-1.5, 0.3-2.1 s, wander halved,
  1-2 % lower at rest, 6 s of latency.
- Q = PI_box / PI_rob predicts SpO2 error: beyond 4 points 2.4 % of windows with Q < 1.2 against
  18.6 % with Q > 1.5, pulse gate on. The SQI ramp rates bad windows as high as good ones.
- Q does not replace spo2_pi_max (sustained events: Q 1.1-1.35). No decision taken.
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np
from scipy.signal import lfilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import spo2_bias_analysis as B   # noqa: E402
from pulsenest import session_events        # noqa: E402

FS = 500.0
BLOCK = 50                                  # 100 ms at 500 Hz (alg_window_block_s)
WIN_BLOCKS = 60                             # pi_window_s = 6 s
SUB_BLOCKS = 10                             # 1 s sub-windows for the robust energy
PI_K = 2.0 * math.sqrt(2.0)                 # pi_rms_to_pp_ratio
APPLIED = 2
SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11")
CURVE_A, CURVE_B = 123.98, 39.13
R_CORR_MIN, PI_MAX, SPO2_MIN, SPO2_MAX, CLAMP_MARGIN = 0.8, 20.0, 70.0, 100.0, 10.0
SQI_LO, SQI_HI = 0.5, 2.0                   # spo2_sqi_pi_lo / hi
WINDOW_S, REF_CONF_MIN = 8.0, 0.9
BURST_RATIO = 9.0                           # 1 s energy >= 9x local median = amplitude x3
Q_THRESHOLDS = (1.2, 1.5, 2.0)
MEDIAN_N = (5, 7, 9, 11, 12)                # medians of N x 1 s chunks besides the six of PI_rob.
                                            # Odd N tolerates (N-1)/2 s of artefact; an even N
                                            # tolerates N/2 - 1, the same as N - 1 (Alex, 2026-11-11)
# PI-METHOD-2 as shipped in lib v0.120 (2026-11-13): 7 s window, median of the 61 overlapping 1 s
# sub-windows (one per 100 ms block), DC over the same 7 s. Replica of _pi_update_sample(); with
# --lib2-replay the library's own PI from that replay is compared with it (section A2).
M2_WIN_BLOCKS = 70
M2_KEY = "PI-METHOD-2 (7 s, 61 x 1 s)"
VARIANTS = tuple(f"median of {n} x 1 s" for n in MEDIAN_N) + ("q25 of 6 x 1 s", "2nd lowest of 6 x 1 s", M2_KEY)
G_ORDER = ("box", "median of 5 x 1 s", "rob", "median of 7 x 1 s", "median of 9 x 1 s",
           "median of 11 x 1 s", "median of 12 x 1 s", "q25 of 6 x 1 s", "2nd lowest of 6 x 1 s", M2_KEY)


def bp_coeffs(f_low, f_high, fs):
    """BiquadFilter::init_bp."""
    k = 2.0 * fs
    ol = k * math.tan(math.pi * f_low / fs); oh = k * math.tan(math.pi * f_high / fs)
    o0 = ol * oh; bw = oh - ol; d = k * k + bw * k + o0
    return [bw * k / d, 0.0, -bw * k / d], [1.0, 2.0 * (o0 - k * k) / d, (k * k - bw * k + o0) / d]


B_BP, A_BP = bp_coeffs(0.5, 15.0, FS)


def load(session_dir, replay, lib2_replay=None):
    board, _ = B.parse_board_session(session_dir, replay=replay)
    ot, sqi3, pi2 = [], [], []
    for path in sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv"))):
        rp = os.path.join(session_dir, "derived", replay, os.path.basename(path)[:-4] + "_replay.csv")
        with open(rp, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ot.append(float(row["OT_LED1"])); sqi3.append(float(row["HR3_SQI"]))
        if lib2_replay:   # the PI column of a replay made with lib >= 0.120 (PI-METHOD-2)
            rp2 = os.path.join(session_dir, "derived", lib2_replay, os.path.basename(path)[:-4] + "_replay.csv")
            with open(rp2, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    pi2.append(float(row["PI"]))
    d = {"t": board["t"], "ps": board["ps"], "r": board["r"], "rc": board["r_method2_reg_corr"],
         "pi": board["pi"], "hr3": board["hr"], "ot": np.array(ot), "hr3_sqi": np.array(sqi3),
         "pi2": np.array(pi2) if pi2 else None}
    if len(d["ot"]) != len(d["t"]):
        raise ValueError(f"{session_dir}: OT rows {len(d['ot'])} != {len(d['t'])}")
    return d


def pi_blocks(d):
    """Replica of PI-METHOD-1 at block cadence plus PI_rob. Returns per-block arrays over every
    applied run: sample index of the block's last sample, PI_box, PI_rob, and the 1 s energy
    ending at the block (for the burst detector); `seg` numbers the applied run."""
    on = d["ps"] == APPLIED
    dt = np.diff(d["t"], prepend=d["t"][0])
    brk = (~on) | (dt > 50e3)                              # probe off or a gap in the stream
    idx, box, rob, e1, seg = [], [], [], [], []
    var = {k: [] for k in VARIANTS}
    edges = np.flatnonzero(np.diff(np.concatenate(([True], brk, [True])).astype(np.int8)))
    for s in range(0, len(edges) - 1, 2):
        i0, i1 = edges[s], edges[s + 1]                    # [i0, i1) applied and gapless
        nb = (i1 - i0) // BLOCK
        if nb <= WIN_BLOCKS:
            continue
        x = d["ot"][i0:i0 + nb * BLOCK]
        # precharge as BiquadFilter::process() after reset(): steady state of a band-pass is 0
        zi = [-B_BP[0] * x[0], B_BP[2] * x[0]]
        y, _ = lfilter(B_BP, A_BP, x, zi=zi)
        ac = (y * y).reshape(nb, BLOCK).sum(1); dc = x.reshape(nb, BLOCK).sum(1)
        cac = np.concatenate(([0.0], np.cumsum(ac))); cdc = np.concatenate(([0.0], np.cumsum(dc)))
        cac12 = np.concatenate((cac, np.full(max(0, 2 * WIN_BLOCKS + 1 - len(cac)), cac[-1])))   # short run: padded, masked below
        j = np.arange(WIN_BLOCKS, nb + 1)                  # window = blocks [j-60, j)
        n_raw = WIN_BLOCKS * BLOCK
        dcm = (cdc[j] - cdc[j - WIN_BLOCKS]) / n_raw
        e_box = (cac[j] - cac[j - WIN_BLOCKS]) / n_raw
        subs = np.stack([(cac[j - k * SUB_BLOCKS] - cac[j - (k + 1) * SUB_BLOCKS]) / (SUB_BLOCKS * BLOCK)
                         for k in range(WIN_BLOCKS // SUB_BLOCKS)])
        e_rob = np.median(subs, axis=0)
        idx.append(i0 + j * BLOCK - 1)
        box.append(PI_K * np.sqrt(e_box) / dcm * 100.0)
        rob.append(PI_K * np.sqrt(e_rob) / dcm * 100.0)
        e1.append(subs[0] / (dcm * dcm))                   # last 1 s, normalised by DC^2
        # variants of the robust energy (section G): lower quantiles of the same six chunks
        var["q25 of 6 x 1 s"].append(PI_K * np.sqrt(np.percentile(subs, 25, axis=0)) / dcm * 100.0)
        var["2nd lowest of 6 x 1 s"].append(PI_K * np.sqrt(np.sort(subs, axis=0)[1]) / dcm * 100.0)
        # median of the last N chunks of 1 s; the DC stays the 6 s mean of PI-METHOD-1, so only
        # the numerator changes. NaN until N s of signal (N > 6).
        for n_ch in MEDIAN_N:
            need = n_ch * SUB_BLOCKS
            jn = np.minimum(np.maximum(j, need), max(nb, need))
            subs_n = np.stack([(cac12[jn - k * SUB_BLOCKS] - cac12[jn - (k + 1) * SUB_BLOCKS]) / (SUB_BLOCKS * BLOCK)
                               for k in range(n_ch)])
            vn = PI_K * np.sqrt(np.median(subs_n, axis=0)) / dcm * 100.0
            vn[j < need] = np.nan
            var[f"median of {n_ch} x 1 s"].append(vn)
        # PI-METHOD-2 as shipped: window of M2_WIN_BLOCKS, DC over that window, median of the
        # overlapping 1 s sub-windows ending at every block of the window. NaN until 7 s.
        j2 = np.minimum(np.maximum(j, M2_WIN_BLOCKS), nb)
        dcm2 = (cdc[j2] - cdc[j2 - M2_WIN_BLOCKS]) / (M2_WIN_BLOCKS * BLOCK)
        subs2 = np.stack([(cac[j2 - k] - cac[j2 - k - SUB_BLOCKS]) / (SUB_BLOCKS * BLOCK)
                          for k in range(M2_WIN_BLOCKS - SUB_BLOCKS + 1)])
        v2 = PI_K * np.sqrt(np.median(subs2, axis=0)) / dcm2 * 100.0
        v2[j < M2_WIN_BLOCKS] = np.nan
        var[M2_KEY].append(v2)
        seg.append(np.full(len(j), s // 2))
    cat = lambda v: np.concatenate(v) if v else np.array([])
    out = {"i": cat(idx).astype(int), "box": cat(box), "rob": cat(rob), "e1": cat(e1), "seg": cat(seg)}
    for k in VARIANTS:
        out[k] = cat(var[k])
    return out


def q(v, p):
    v = v[np.isfinite(v)]
    return float(np.percentile(v, p)) if len(v) else math.nan


def bursts(b):
    """Isolated bursts: index (into the block arrays) of the block where a 1 s chunk with
    >= BURST_RATIO x the local median energy ends, with no other such chunk within +-7 s."""
    out = []
    n_all = 0
    for s in np.unique(b["seg"]):
        k = np.flatnonzero(b["seg"] == s)
        if len(k) < 400:                                   # < 40 s of valid PI: no local baseline
            continue
        e = b["e1"][k][::SUB_BLOCKS]                        # non-overlapping seconds
        kk = k[::SUB_BLOCKS]
        hot = np.zeros(len(e), dtype=bool)
        for m in range(len(e)):
            lo, hi = max(0, m - 15), min(len(e), m + 16)
            hot[m] = e[m] >= BURST_RATIO * np.median(e[lo:hi])
        n_all += int(hot.sum())
        for m in np.flatnonzero(hot):
            lo, hi = max(0, m - 7), min(len(e), m + 8)
            if hot[lo:hi].sum() == 1 and m >= 8 and m + 8 < len(e):
                out.append(int(kk[m]))
    return out, n_all


def burst_response(b, k0, key):
    """Peak of PI against its value 1.5 s before the burst's chunk ends, and the time above
    +20 %, over the 8 s after the chunk starts."""
    pre = b[key][k0 - 15]
    w = b[key][k0 - 10:k0 + 70] / pre
    return float(np.nanmax(w)), float((w > 1.2).sum() * 0.1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", default="replay_lib0.108_inputot")
    ap.add_argument("--lib2-replay", default=None,
                    help="a replay made with lib >= 0.120: its PI column is PI-METHOD-2, compared in A2")
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "PI_ROBUST_ANALYSIS_20261111"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    lines = []

    def P(s=""):
        print(s); lines.append(s)

    per = {}
    win_rows = []
    for subject in SUBJECTS:
        acc = {k: [] for k in ("box", "rob", "lib", "lib2", "hr3ok", "stab_box", "stab_rob",
                               "pk_box", "pk_rob", "du_box", "du_rob")}
        for vk in VARIANTS:
            for pre in ("", "stab_", "pk_", "du_"):
                acc[pre + vk] = []
        n_burst_all = n_blocks = 0
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            if not os.path.isdir(os.path.join(sd, "derived", args.replay)):
                continue
            if args.lib2_replay and not os.path.isdir(os.path.join(sd, "derived", args.lib2_replay)):
                continue
            d = load(sd, args.replay, args.lib2_replay)
            b = pi_blocks(d)
            if not len(b["i"]):
                continue
            n_blocks += len(b["i"])
            acc["box"].append(b["box"]); acc["rob"].append(b["rob"])
            acc["lib"].append(d["pi"][b["i"]]); acc["hr3ok"].append(d["hr3_sqi"][b["i"]] > 0)
            acc["lib2"].append(d["pi2"][b["i"]] if d["pi2"] is not None else np.full(len(b["i"]), np.nan))
            for vk in VARIANTS:
                acc[vk].append(b[vk])
            for s in np.unique(b["seg"]):
                k = np.flatnonzero(b["seg"] == s)
                for key in ("box", "rob") + VARIANTS:
                    v = b[key][k]
                    if len(v) > WIN_BLOCKS:
                        acc["stab_" + key].append(np.abs(v[WIN_BLOCKS:] / v[:-WIN_BLOCKS] - 1.0))
            iso, n_all = bursts(b)
            n_burst_all += n_all
            for k0 in iso:
                for key in ("box", "rob") + VARIANTS:
                    pk, du = burst_response(b, k0, key)
                    acc["pk_" + key].append(pk); acc["du_" + key].append(du)
            # ── reference windows ──
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            rt, rs, rc = B.parse_reference(sd)
            anomalies = session_events.anomaly_intervals(sd, subject)
            raw = CURVE_A - CURVE_B * d["r"]
            spo2 = np.minimum(raw, SPO2_MAX)
            # PI per sample from the block arrays (hold the last block value), NaN before the first
            pos = np.searchsorted(b["i"], np.arange(len(d["t"])), side="right") - 1
            ok_pos = pos >= 0
            box_s = np.where(ok_pos, b["box"][np.maximum(pos, 0)], np.nan)
            rob_s = np.where(ok_pos, b["rob"][np.maximum(pos, 0)], np.nan)
            stale = ok_pos & (np.arange(len(d["t"])) - b["i"][np.maximum(pos, 0)] >= BLOCK)
            box_s[stale] = np.nan; rob_s[stale] = np.nan
            with np.errstate(invalid="ignore"):
                base = ((d["ps"] == APPLIED) & np.isfinite(d["r"]) & (d["rc"] >= R_CORR_MIN)
                        & np.isfinite(box_s) & (box_s <= PI_MAX)
                        & (raw >= SPO2_MIN) & (raw <= SPO2_MAX + CLAMP_MARGIN))
            pulse = d["hr3_sqi"] > 0
            w_us = WINDOW_S * 1e6
            for t1, s, c in zip(rt, rs, rc):
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
                for gate, m in (("no pulse gate", base[sl]), ("pulse gate", base[sl] & pulse[sl])):
                    if m.mean() < B.VALID_MIN_FRAC or m.sum() < B.MIN_VALID_SAMPLES:
                        continue
                    ours = float(np.median(spo2[sl][m]))
                    pb = float(np.nanmedian(box_s[sl][m])); pr = float(np.nanmedian(rob_s[sl][m]))
                    qq = float(np.nanmax(box_s[sl][m] / rob_s[sl][m]))
                    win_rows.append({"subject": subject, "gate": gate, "ref": s, "bias": ours - s,
                                     "pi_box": pb, "pi_rob": pr, "q_max": qq})
        if not n_blocks:
            continue
        per[subject] = {k: (np.concatenate(v) if v and isinstance(v[0], np.ndarray) else np.array(v))
                        for k, v in acc.items()}
        per[subject]["n_burst_all"] = n_burst_all

    P("A. Replica of PI-METHOD-1 against the library's PI (replay), per block")
    P("subject   blocks   median |replica/lib - 1|   p95")
    for sj, a in per.items():
        ok = np.isfinite(a["lib"]) & (a["lib"] > 0)
        e = np.abs(a["box"][ok] / a["lib"][ok] - 1.0)
        P(f"{sj}   {ok.sum():7d}   {q(e, 50) * 100:8.3f} %              {q(e, 95) * 100:6.3f} %"
          f"   blocks > 1 %: {(e > 0.01).sum()}, > 5 %: {(e > 0.05).sum()}")

    if args.lib2_replay:
        P()
        P(f"A2. Replica of PI-METHOD-2 against the library's PI ({args.lib2_replay}), per block")
        P("subject   blocks   median |replica/lib - 1|   p95     max      (outliers: HGAC RF steps and stream gaps, as in A)")
        for sj, a in per.items():
            ok = np.isfinite(a["lib2"]) & (a["lib2"] > 0) & np.isfinite(a[M2_KEY])
            e = np.abs(a[M2_KEY][ok] / a["lib2"][ok] - 1.0)
            P(f"{sj}   {ok.sum():7d}   {q(e, 50) * 100:8.3f} %              {q(e, 95) * 100:6.3f} %  {e.max() * 100 if len(e) else math.nan:6.3f} %"
              f"   blocks > 1 %: {(e > 0.01).sum()}, > 5 %: {(e > 0.05).sum()}")

    P()
    P("B. Level and stability (all applied time with a full window)")
    P("subject   minutes  PI_box med  PI_rob med  rob/box med [p5..p95]   rob/box med (HR3 valid)   6 s change med: box / rob")
    for sj, a in per.items():
        r = a["rob"] / a["box"]
        P(f"{sj}   {len(a['box']) / 600:6.1f}   {q(a['box'], 50):8.2f}   {q(a['rob'], 50):8.2f}    "
          f"{q(r, 50):5.3f} [{q(r, 5):.3f}..{q(r, 95):.3f}]       {q(r[a['hr3ok']], 50):5.3f}"
          f"                 {q(a['stab_box'], 50) * 100:5.1f} % / {q(a['stab_rob'], 50) * 100:5.1f} %"
          f"   p90 {q(a['stab_box'], 90) * 100:5.1f} % / {q(a['stab_rob'], 90) * 100:5.1f} %")

    P()
    P(f"C. Isolated bursts (one 1 s chunk >= {BURST_RATIO:.0f}x the local median energy, alone in +-7 s)")
    P("subject   bursts (isolated / all hot seconds)   peak PI_box   peak PI_rob   s above +20 %: box / rob")
    for sj, a in per.items():
        n = len(a["pk_box"])
        if not n:
            P(f"{sj}   0 / {a['n_burst_all']}"); continue
        P(f"{sj}   {n:4d} / {a['n_burst_all']:5d}                       x{q(a['pk_box'], 50):4.2f}"
          f" (p90 x{q(a['pk_box'], 90):4.2f})   x{q(a['pk_rob'], 50):4.2f} (p90 x{q(a['pk_rob'], 90):4.2f})"
          f"   {q(a['du_box'], 50):3.1f} / {q(a['du_rob'], 50):3.1f}")

    P()
    P("D. Q = PI_box / PI_rob as an artefact indicator: share of time above a threshold")
    P("subject   HR3 valid share   " + "   ".join(f"Q>{t}: all / HR3 valid / HR3 not valid" for t in Q_THRESHOLDS))
    for sj, a in per.items():
        Q = a["box"] / a["rob"]; h = a["hr3ok"]
        cells = []
        for t in Q_THRESHOLDS:
            cells.append(f"{(Q > t).mean() * 100:5.1f} / {(Q[h] > t).mean() * 100 if h.any() else math.nan:5.1f}"
                         f" / {(Q[~h] > t).mean() * 100 if (~h).any() else math.nan:5.1f} %")
        P(f"{sj}   {h.mean() * 100:5.1f} %          " + "        ".join(cells))

    P()
    P("E. Against the ward monitor (8 s windows; Q = max of PI_box/PI_rob over the window's valid samples)")
    bands = ((0.0, 1.2), (1.2, 1.5), (1.5, 99.0))
    for gate in ("no pulse gate", "pulse gate"):
        P(f"-- {gate} --")
        P("subject   windows   |bias| med   >4 pt     " + "   ".join(f"Q {lo}-{hi if hi < 99 else 'inf'}: n, |bias| med, >4 pt" for lo, hi in bands))
        for sj in list(per) + ["ALL"]:
            rows = [r for r in win_rows if r["gate"] == gate and (sj == "ALL" or r["subject"] == sj)]
            if not rows:
                continue
            ab = np.array([abs(r["bias"]) for r in rows]); qm = np.array([r["q_max"] for r in rows])
            cells = []
            for lo, hi in bands:
                m = (qm >= lo) & (qm < hi)
                cells.append(f"{m.sum():4d}, {q(ab[m], 50):4.1f}, {(ab[m] > 4).mean() * 100 if m.any() else math.nan:5.1f} %")
            P(f"{sj}   {len(rows):6d}   {q(ab, 50):6.1f}     {(ab > 4).mean() * 100:5.1f} %    " + "      ".join(cells))
        rows = [r for r in win_rows if r["gate"] == gate]
        ab = np.array([abs(r["bias"]) for r in rows])
        sqi = lambda p: np.clip((p - SQI_LO) / (SQI_HI - SQI_LO), 0.0, 1.0)
        sb = sqi(np.array([r["pi_box"] for r in rows])); sr = sqi(np.array([r["pi_rob"] for r in rows]))
        good, bad = ab <= 4, ab > 4
        P(f"   SQI ramp, mean: good windows (n={good.sum()}) box {sb[good].mean():.2f} / rob {sr[good].mean():.2f};"
          f"  bad windows (n={bad.sum()}) box {sb[bad].mean() if bad.any() else math.nan:.2f} / rob {sr[bad].mean() if bad.any() else math.nan:.2f}")

    P()
    P("F. spo2_pi_max (20 %): share of applied time with PI_box > 20 %, and PI_rob / Q there")
    for sj, a in per.items():
        m = a["box"] > PI_MAX
        if not m.any():
            P(f"{sj}   never"); continue
        Q = a["box"][m] / a["rob"][m]
        P(f"{sj}   {m.mean() * 100:5.2f} % of time ({m.sum() / 10:.0f} s);  PI_rob there: med {q(a['rob'][m], 50):.1f} %,"
          f" > 20 % in {(a['rob'][m] > PI_MAX).mean() * 100:.0f} % of it;  Q med {q(Q, 50):.2f}, Q > 1.5 in {(Q > 1.5).mean() * 100:.0f} %")

    P()
    P("G. Variants of the robust PI (same captures, same bursts); PI_box = today's PI, median of 6 = PI_rob")
    P("subject   variant                   tolerates   /box med (HR3 valid)   6 s change med (p90)   burst peak med (p90)   s above +20 % med (p90)")
    for sj, a in per.items():
        for vk in G_ORDER:
            name = {"box": "PI_box (today)", "rob": "median of 6 x 1 s"}.get(vk, vk)
            tol = "-"
            if name.startswith("median of"):
                n_ch = int(name.split()[2]); tol = f"{(n_ch - 1) // 2} s"
            elif vk == M2_KEY:
                tol = "2 s"
            r = a[vk] / a["box"]
            P(f"{sj}   {name:24s}  {tol:>4s}        {q(r[a['hr3ok']], 50):5.3f}"
              f"                 {q(a['stab_' + vk], 50) * 100:5.1f} % ({q(a['stab_' + vk], 90) * 100:5.1f} %)"
              f"       x{q(a['pk_' + vk], 50):4.2f} (x{q(a['pk_' + vk], 90):4.2f})"
              f"          {q(a['du_' + vk], 50):3.1f} ({q(a['du_' + vk], 90):3.1f})")
        P()

    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.out, "windows.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["subject", "gate", "ref", "bias", "pi_box", "pi_rob", "q_max"])
        w.writeheader(); w.writerows(win_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
