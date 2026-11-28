"""R on the pulse harmonics vs R-METHOD-2 on seven neonates: the A/B of 2026-10-27 with the 2026-11-25
campaign added (2026-11-28).

Why this exists
---------------
experiments/r_estimators_ab_20261027.py left the harmonic-bin R as "a candidate second estimator only if
a later campaign confirms the 0.1-0.3 Arms gain on still neonates" (rationale section 17). The campaign
of 2026-11-25 brought three more neonates (SUBJ12, SUBJ13, SUBJ14). Alex asked on 2026-11-28 for the
comparison to be run again with them. The criterion was fixed with him before any number was looked at:

    CONFIRMED if, under the pulse gate, the harmonic R lowers Arms by >= 0.2 point in at least 5 of the
    7 neonates, raises it by more than 0.2 in none of the still ones, and publishes >= 95 % of the
    windows the regression publishes. SUBJ10 (the motion subject) is reported apart: it does not veto,
    the pulse gate is what must act there.

What it does
------------
Nothing new in the estimators: `process_segment`, the validity rule and the pairing are imported from
the 2026-10-27 script, unchanged. Two things differ:

- Where the signals come from. SUBJ08-SUBJ11 are read from their lib 0.108 OT replays, as in October.
  SUBJ12-SUBJ14 have no replay and need none: their board captures (fw 0.32, lib v0.124b) carry
  OT_LED1 / OT_LED2 / HR3 / HR3_SQI. Since lib v0.123 HR3 is no longer -1 when its SQI is 0, so the pulse
  gate of these sessions is HR3 > 0 AND HR3_SQI > 0, which is what `hr3 > 0` meant in the lib 0.108
  replays. The Python chain is checked against the R the board itself published.
- What is reported. Per subject and gate: windows, published %, bias (median), sd, Arms, > 4 points; then
  the criterion, and the same with each estimator's own intercept removed (a curve belongs to its
  estimator: the shipped intercept was fitted with the regression, so a constant shift of the harmonic R
  would be charged to it as error).

    python experiments/r_harmonic_ab_20261128.py [--out DIR]

Outputs in --out (default captures/sessions/R_HARMONIC_AB_20261128/, not versioned): ab_windows.csv,
ab_summary.csv; tables on stdout. Report: docs/r_harmonic_ab_20261128.md.

Result (2026-11-28; 25 sessions, 10 176 reference windows)
------
- NOT confirmed by the criterion: Arms falls by >= 0.2 in 4 of 7 (SUBJ09 2.39 -> 2.07, SUBJ12 4.85 -> 3.97,
  SUBJ13 2.47 -> 2.08, SUBJ14 2.77 -> 1.56); SUBJ11 1.23 -> 1.08 (-0.15) and SUBJ08 2.42 -> 2.42 fall short;
  no still neonate is worse; HARM6 publishes 99.5 % of REG's windows. Same count with each estimator's own
  intercept, and with the 10.24 s window.
- The October numbers repeat exactly on the old subjects and the gain is larger on the three unseen ones.
  Six still neonates pooled: Arms 3.16 -> 2.62, sd 2.94 -> 2.51, beyond 4 points 16.0 -> 11.6 %. The gain is
  in scatter and grows as the signal weakens (SUBJ14: PI 0.66 %, sd 2.49 -> 1.54 on the common windows).
- It does not explain SUBJ12: bias -3.70 -> -3.19. SUBJ10: 15 windows, 2.05 -> 4.62, worse.
- The Python regression sits 1-7e-4 (median) from the R the boards published live: the precision of the
  recorded OT (a replay of SUBJ11 from its recorded OT sits 3.1e-4 from its board's R), not a mirror error.
- Nothing changes in the library. Whether the harmonic R stays a candidate is Alex's decision.
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments import r_estimators_ab_20261027 as AB   # noqa: E402
from pulsenest import session_events                      # noqa: E402
from tools import spo2_bias_analysis as B                 # noqa: E402

REPLAY = "replay_lib0.108_inputot"
SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ12", "SUBJ13", "SUBJ14")
MOTION_SUBJECT = "SUBJ10"                 # reported apart: it does not veto (criterion)
ESTIMATORS = ("REG", "HARM6", "HARM10")
GATES = ("G0 no pulse gate", "G1 HR3 valid")
GATE_OF_CRITERION = "G1 HR3 valid"       # the library ships with the pulse gate on
GAIN_MIN, LOSS_MAX, N_GAIN_MIN, PUB_RATIO_MIN = 0.2, 0.2, 5, 0.95


def load_board(session_dir):
    """A session without a replay: the estimators' inputs straight from the board's own CSV parts."""
    board, _curve = B.parse_board_session(session_dir)
    ot1, ot2, hr3, sqi = [], [], [], []
    for path in sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv"))):
        cols = {}
        with open(path, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                if not line or line.startswith("#"):
                    continue
                if line.startswith("LED2,"):
                    cols = {n: i for i, n in enumerate(line.split(","))}
                    continue
                v = line.split(",")
                try:                       # the same rows parse_board_session keeps, plus these columns
                    float(v[cols["R"]]); float(v[cols["SpO2"]]); float(v[cols["SpO2_SQI"]])
                    float(v[cols["PI"]]); int(v[cols["ProbeState"]])
                    a, b, h, q = (float(v[cols[k]]) for k in ("OT_LED1", "OT_LED2", "HR3", "HR3_SQI"))
                    float(v[cols["R_METHOD2_REG_CORR"]])
                except (KeyError, ValueError, IndexError):
                    continue
                ot1.append(a); ot2.append(b); hr3.append(h); sqi.append(q)
    hr3, sqi = np.array(hr3), np.array(sqi)
    if len(hr3) != len(board["t"]):
        raise ValueError(f"{session_dir}: OT rows {len(hr3)} != {len(board['t'])}")
    hr3_gated = np.where((hr3 > 0) & (sqi > 0), hr3, -1.0)      # what `HR3 > 0` meant up to lib v0.122
    d = {"t": board["t"], "ps": board["ps"], "r_lib": board["r"], "rc_lib": board["r_method2_reg_corr"],
         "pi": board["pi"], "hr3": hr3_gated, "ir": np.array(ot1), "red": np.array(ot2)}
    d["fs"] = float(round(1e6 / np.median(np.diff(d["t"]))))
    n = len(d["t"])
    for k in AB.ESTIMATORS + ("r",):
        d[k] = np.full(n, np.nan)
    d["dec_valid"] = np.zeros(n, dtype=bool)
    on = d["ps"] == AB.APPLIED
    edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(np.int8), [0]])))
    for i0, i1 in zip(edges[::2], edges[1::2]):
        seg = AB.process_segment(d["ir"][i0:i1], d["red"][i0:i1], d["hr3"][i0:i1], d["fs"])
        for k, v in seg.items():
            d[k][i0:i1] = v
    with np.errstate(invalid="ignore"):
        common = (on & np.isfinite(d["r"]) & (d["r"] >= AB.R_CORR_MIN) & np.isfinite(d["pi"]) & (d["pi"] > 0)
                  & (d["pi"] <= AB.PI_MAX))
        d["base"], d["spo2"] = {}, {}
        for k in AB.ESTIMATORS:
            raw = AB.CURVE_A - AB.CURVE_B * d[k]
            d["base"][k] = common & np.isfinite(raw) & (raw >= AB.SPO2_MIN) & (raw <= AB.SPO2_MAX + AB.CLAMP_MARGIN)
            d["spo2"][k] = np.minimum(raw, AB.SPO2_MAX)
    d["pulse"] = d["hr3"] > 0
    return d


def stats(b):
    if not len(b):
        return {k: math.nan for k in ("bias", "sd", "arms", "gt4")}
    return {"bias": float(np.median(b)), "sd": float(np.std(b)), "arms": float(np.sqrt(np.mean(b ** 2))),
            "gt4": 100 * float(np.mean(np.abs(b) > 4))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "R_HARMONIC_AB_20261128"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    rows = []
    for subject in SUBJECTS:
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            name = os.path.basename(sd)
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            if not glob.glob(os.path.join(sd, "*_p[0-9][0-9].csv")):
                print(f"  skip {name}: no board parts")
                continue
            if os.path.isdir(os.path.join(sd, "derived", REPLAY)):
                d, src = AB.load(sd, REPLAY), "replay 0.108"
            else:
                try:
                    d, src = load_board(sd), "board"
                except (ValueError, KeyError, FileNotFoundError) as e:
                    print(f"  skip {name}: {e}")
                    continue
            med, p99, n = AB.check_against_replay(d)
            rt, rs, rc = B.parse_reference(sd)
            anomalies = session_events.anomaly_intervals(sd, subject)
            w = [r for r in AB.windows(subject, name, d, rt, rs, rc, anomalies) if r["estimator"] in ESTIMATORS]
            rows += w
            print(f"  {name} [{src}]: fs {d['fs']:.0f}, {len(d['t'])} samples, |REG - published R| median "
                  f"{med:.1e} p99 {p99:.1e} ({n}); {len(w) // (len(GATES) * len(ESTIMATORS))} reference windows",
                  flush=True)
    with open(os.path.join(args.out, "ab_windows.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)

    def sel(subjects, gate, est, stationary=False):
        return [r for r in rows if r["subject"] in subjects and r["gate"] == gate and r["estimator"] == est
                and (not stationary or r["stationary"])]

    # each estimator's own intercept: its median bias over the still neonates under the gate of the criterion
    still = tuple(s for s in SUBJECTS if s != MOTION_SUBJECT)
    own = {}
    for est in ESTIMATORS:
        b = np.array([r["bias"] for r in sel(still, GATE_OF_CRITERION, est) if r["published"]])
        own[est] = float(np.median(b)) if len(b) else math.nan

    summ = []
    for subject in SUBJECTS + ("pooled still",):
        subs = still if subject == "pooled still" else (subject,)
        for gate in GATES:
            for est in ESTIMATORS:
                rs_ = sel(subs, gate, est)
                if not rs_:
                    continue
                b = np.array([r["bias"] for r in rs_ if r["published"]])
                s = stats(b)
                s2 = stats(b - own[est])
                summ.append({"subject": subject, "gate": gate, "estimator": est, "windows": len(rs_),
                             "published": len(b), "published_pct": round(100 * len(b) / len(rs_), 1),
                             "bias_med": round(s["bias"], 2), "sd": round(s["sd"], 2), "arms": round(s["arms"], 2),
                             "off_gt4_pct": round(s["gt4"], 1), "arms_own_intercept": round(s2["arms"], 2)})
    with open(os.path.join(args.out, "ab_summary.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(summ[0])); wr.writeheader(); wr.writerows(summ)

    print(f"\n{'subject':13} {'gate':17} {'est':7} {'win':>5} {'pub':>5} {'pub%':>6} {'bias':>6} {'sd':>5} "
          f"{'Arms':>5} {'>4pt%':>6} {'Arms*':>6}   (* own intercept: " +
          ", ".join(f"{e} {own[e]:+.2f}" for e in ESTIMATORS) + ")")
    for s in summ:
        print(f"{s['subject']:13} {s['gate']:17} {s['estimator']:7} {s['windows']:5d} {s['published']:5d} "
              f"{s['published_pct']:6.1f} {s['bias_med']:6.2f} {s['sd']:5.2f} {s['arms']:5.2f} "
              f"{s['off_gt4_pct']:6.1f} {s['arms_own_intercept']:6.2f}")

    # the criterion, fixed before measuring
    by = {(s["subject"], s["gate"], s["estimator"]): s for s in summ}
    print(f"\nCriterion (gate {GATE_OF_CRITERION}): gain >= {GAIN_MIN} in >= {N_GAIN_MIN} of {len(SUBJECTS)} "
          f"neonates, no still one worse by > {LOSS_MAX}, published >= {100 * PUB_RATIO_MIN:.0f} % of REG's")
    for est in ("HARM6", "HARM10"):
        for key, label in (("arms", "shipped curve"), ("arms_own_intercept", "own intercept")):
            gains, losses, line = 0, 0, []
            for subject in SUBJECTS:
                a, h = by.get((subject, GATE_OF_CRITERION, "REG")), by.get((subject, GATE_OF_CRITERION, est))
                if not a or not h or not math.isfinite(a[key]) or not math.isfinite(h[key]):
                    line.append(f"{subject} n/a")
                    continue
                delta = h[key] - a[key]
                gains += delta <= -GAIN_MIN
                if subject != MOTION_SUBJECT:
                    losses += delta > LOSS_MAX
                line.append(f"{subject} {delta:+.2f}")
            a, h = by[("pooled still", GATE_OF_CRITERION, "REG")], by[("pooled still", GATE_OF_CRITERION, est)]
            ratio = h["published"] / a["published"] if a["published"] else math.nan
            ok = gains >= N_GAIN_MIN and losses == 0 and ratio >= PUB_RATIO_MIN
            print(f"  {est:6} {label:14} dArms: " + "  ".join(line) + f"   | gains {gains}, still worse {losses}, "
                  f"published {100 * ratio:.1f} % of REG -> {'CONFIRMED' if ok else 'NOT confirmed'}")

    # windows both estimators publish (same windows, paired): the like-for-like dispersion
    print("\nPaired on the windows REG and HARM6 both publish (gate of the criterion): sd of bias, REG vs HARM6")
    for subject in SUBJECTS:
        a = {(r["session"], r["t_epoch_us"]): r["bias"] for r in sel((subject,), GATE_OF_CRITERION, "REG") if r["published"]}
        h = {(r["session"], r["t_epoch_us"]): r["bias"] for r in sel((subject,), GATE_OF_CRITERION, "HARM6") if r["published"]}
        common = sorted(set(a) & set(h))
        if len(common) < 10:
            print(f"  {subject}: {len(common)} common windows")
            continue
        ba, bh = np.array([a[k] for k in common]), np.array([h[k] for k in common])
        print(f"  {subject}: n {len(common):4d}  REG bias {np.median(ba):+.2f} sd {np.std(ba):.2f} Arms {np.sqrt(np.mean(ba**2)):.2f}"
              f"  |  HARM6 bias {np.median(bh):+.2f} sd {np.std(bh):.2f} Arms {np.sqrt(np.mean(bh**2)):.2f}"
              f"  |  only REG {len(a) - len(common)}, only HARM6 {len(h) - len(common)}")


if __name__ == "__main__":
    main()
