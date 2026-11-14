"""The methods of the spectrum family (HR3) against what the ward monitor showed.

Why this exists
---------------
Phase 1 of the work plan drafted on 2026-11-13: decide which methods form family 3 and by what
rule. The two earlier studies (hr3_spectral_variants_20261021.py, spectral_autocorrelation_20261112.py)
scored the rate against the consensus of the board's HR1 and HR2, which exists only on clean
stretches: 37 / 56 / 0 / 38 % of the HR3 windows of SUBJ08 / 09 / 10 / 11. There the spectral
autocorrelation already reads no double and no half, so a combination has nothing to fix; what
matters is outside. The ward monitor's rate was photographed every 10 s and read by eye on
2026-10-16/17 (captures/sessions/BIAS_ANALYSIS_SUBJ10_SUBJ11/ocr_vs_eye/): the ECG heart rate for
SUBJ08, SUBJ09 and SUBJ11, the monitor's own pulse rate for SUBJ10 (no ECG there). It is the first
reference that exists during artefacts.

Questions (proposal agreed with Alex on 2026-11-14, before any measurement)
---------
Q1  Outside the clean windows, on which octave is each method?
Q2  Where does today's HR3 publish one third of the rate, and what do the others say there?
Q3  Is the cepstrum (HR3_CEP) right, and does it fail where HR3_SAC fails or elsewhere?
Q4  Does a combination fix anything HR3_SAC alone does not?
Q5  What rule would form hr3 and hr3_sqi, and what does it do to the SpO2 gate?
Q6  Does any method of HR3 cover the simulator's 30 bpm?

Fixed before measuring
----------------------
Front end, windows and constants: pulsenest/hr_bench.py (the library's HR3 chain: 512 samples at
50 Hz, Hann, every 0.5 s). Reference: the monitor reading nearest to the window's end (<= 6 s),
scored only where 'stable' (neighbouring readings within 10 %); correct = within 10 %.
  HR3_HPS      today's HR3 (product of 3 harmonics, published while its SQI > 0)
  B1 (HPS2)    the two-harmonic product of 2026-10-21
  HR3_SAC      spectral autocorrelation of the local contrast ('logc6 first' of 2026-11-12)
  HR3_CEP x    cepstrum of the band 0.49-15 Hz, three preparations of the same spectrum:
               cep40 / cep60 = dB above a floor 40 / 60 dB under the band maximum, cepc6 = the local
               contrast HR3_SAC reads. Peak searched between the periods of 263 and 27 bpm, the
               smallest quefrency whose maximum reaches 0.8 of the highest; quality = peak / RMS.
  R2 x         HR3_SAC, published only if HR3_CEP x agrees within 10 %
  R3 x         HR3_SAC, unless the two differ by a factor 2 or 3 and only the cepstrum agrees with
               the board's HR2 at that instant
  board HR1, board HR2   what the firmware published at the window's last sample
SpO2 gate: the rule of 2026-10-20 on replay_lib0.108, as the two earlier studies.
No threshold was tuned. Anything added after seeing the data is marked "post hoc" in the report.
Post hoc (after the first run, nothing tuned): 'HR3_SAC gated' = HR3_SAC published only while
rho >= 0.5 and comb purity >= 0.3, the validity rule of 2026-11-12 applied to the rate; and the
joint table of HR3_SAC with every other method, not only with the cepstrum.

    python experiments/hr3_methods_20261114.py [--out DIR] [--cache DIR] [--subjects ...]
                                               [--replay replay_lib0.108] [--no-figs] [--no-gate]

Outputs in --out (default captures/sessions/HR3_METHODS_20261114/, not versioned): baseline.csv
(this bench against the tables of 2026-11-12), reference.csv, rate_vs_monitor.csv, hps_third.csv,
cep_vs_sac.csv, gate.csv, ms100.csv, one PNG per session. --cache (default
captures/sessions/HR_BENCH_CACHE/) keeps each session's raw columns; delete it at will.

Result (2026-11-14; report: docs/hr3_methods_20261114.md)
------
- The bench reproduces every row of the 2026-11-12 tables (largest difference 0.0), and where a
  window has both references the consensus is within 10 % of the monitor in 100.0 % of them.
- Against the ECG (SUBJ08 / 09 / 11, windows with a stable reading): HR3_SAC right 97.9 / 98.5 /
  99.8 %, wrong 0.9 / 0.8 / 0.1 % with no octave errors, and 96.9 / 97.0 / 99.7 % right outside the
  clean windows. Today's HR3 right 63.9 / 67.6 / 82.9 %, wrong 5.9 / 4.0 / 5.3 %.
- Today's HR3 publishes one third of the heart rate in 6.6 / 4.0 / 4.2 % of its valid windows
  (55-59 bpm against 166-175 on the ECG); HR3_SAC is right in 97-100 % of those.
- The cepstrum is right in 93.7 / 91.6 / 99.1 % (cep40), errs on the octave (half, third) and adds
  under one point to HR3_SAC. The octave vote (R3) fixes nothing. Agreement (R2) is a validity
  check: wrong values 0.1 / 0.3 / 0.0 % for 92.8 / 91.3 / 99.1 % published.
- SpO2 gate: two rate methods agreeing is not a gate (SUBJ10: 33.1 % published, Arms 14.93); comb
  purity with rho is. Dropping from today's gate the windows where HR3_HPS disagrees with HR3_SAC
  lowers the Arms 2.47 -> 2.14 and 2.39 -> 2.07 in SUBJ08 and SUBJ09.
- MS100 at 30 bpm: only HR3_HPS, B1 and the board's HR1 read it; HR3_SAC 0 %, the cepstrum 1-40 %.
- By-product: the board's HR1 is right in 99.5-99.9 % of what it publishes (42-59 % of the
  windows); HR2 in 94-98 % (78-98 %).
- Nothing adopted; decisions for Alex at the end of the report.
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
from pulsenest import session_events          # noqa: E402
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
MS100_SUBJECTS = ("SUBJ90",)
MONITOR_DIR = os.path.join(B.SESSIONS_DIR, "BIAS_ANALYSIS_SUBJ10_SUBJ11", "ocr_vs_eye")
BASELINE_DIR = os.path.join(B.SESSIONS_DIR, "SPECTRAL_ACF_20261112")
CEP_NAMES = ("cep40", "cep60", "cepc6")
RHO_MIN, PURITY_MIN = 0.5, 0.3             # the gate of 2026-11-12, not retuned
HPS, B1, SAC, SAC_GATED = "HR3_HPS", "B1 (HPS2)", "HR3_SAC", "HR3_SAC gated"
BASELINE_NAMES = {HPS: "HR3 today (HPS3 + SQI>0)", B1: "B1 (HPS2 + SQI>0)", SAC: "logc6 first"}
OCTAVE_RATIOS = (2.0, 0.5, 3.0, 1.0 / 3.0)


def within(a, b, rel):
    """|a / b - 1| <= rel where both are finite."""
    m = np.isfinite(a) & np.isfinite(b)
    return m & (np.abs(a / np.where(m, b, 1.0) - 1.0) <= rel)


def estimates(d, P, end_rows, rate):
    """name -> (HR per window, quality per window), and the comb purity at HR3_SAC's rate."""
    est = {}
    est[HPS] = hb.hps_estimate(P, *hb.hps(P, 3), rate)
    est[B1] = hb.hps_estimate(P, *hb.hps(P, 2), rate)
    hr_s, rho, C6, R = hb.hr3_sac(P, rate)
    est[SAC] = (hr_s, rho)
    pur = hb.comb_purity(P, hr_s, rate)
    gated = np.isfinite(hr_s) & (rho >= RHO_MIN) & (pur >= PURITY_MIN)       # post hoc, see the docstring
    est[SAC_GATED] = (np.where(gated, hr_s, np.nan), np.where(gated, rho, 0.0))
    bin_res, b_lo, b_hi = hb.band_bins(rate)
    seqs = {"cep40": hb.log_floor(P, b_lo, b_hi, 40.0), "cep60": hb.log_floor(P, b_lo, b_hi, 60.0), "cepc6": C6}
    for name in CEP_NAMES:
        A, dq = hb.band_cepstrum(seqs[name], bin_res)
        est[f"HR3_CEP {name}"] = hb.pick_quefrency(A, dq)
    for col in ("HR1", "HR2"):
        v = d[col][end_rows]
        est[f"board {col}"] = (np.where(v > 0, v, np.nan), (v > 0).astype(float))
    hr2 = est["board HR2"][0]
    for name in CEP_NAMES:
        hc = est[f"HR3_CEP {name}"][0]
        agree = within(hc, hr_s, hb.OK_REL)
        est[f"R2 {name}"] = (np.where(agree, hr_s, np.nan), np.where(agree, rho, 0.0))
        both = np.isfinite(hc) & np.isfinite(hr_s)
        ratio = np.where(both, hc / np.where(both, hr_s, 1.0), np.nan)
        octave = both & ~agree & np.any([np.abs(ratio / q - 1.0) <= hb.HARMONIC_TOL for q in OCTAVE_RATIOS], axis=0)
        cep_wins = octave & within(hc, hr2, hb.OK_REL) & ~within(hr_s, hr2, hb.OK_REL)
        est[f"R3 {name}"] = (np.where(cep_wins, hc, hr_s), rho)
    return est, pur, C6, R


def pct(mask, of=None):
    n = len(mask) if of is None else int(of.sum())
    return round(100.0 * float(mask.sum()) / n, 1) if n else math.nan


def med(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return round(float(np.median(v)), 2) if len(v) else math.nan


def class_row(hr, sel, ref):
    """Share of each error class over the windows of sel (which all carry a reference)."""
    cl = hb.error_class(hr, np.where(sel, ref, np.nan))
    row = {"ref_windows": int(sel.sum())}
    for i, c in enumerate(hb.CLASSES):
        row[c] = pct(cl[sel] == i)
    avail = sel & np.isfinite(hr)
    row["ok_of_avail"] = pct(cl[avail] == 0)
    return row


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def table(rows, cols=None):
    if not rows:
        return
    cols = cols or list(rows[0])
    wd = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(f"{c:>{wd[c]}}" for c in cols))
    for r in rows:
        print("  ".join(f"{str(r[c]):>{wd[c]}}" for c in cols))


def figure(path, name, t_end, mon_t, mon_v, cons, est, pur):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t0 = t_end[0]
    x = (t_end - t0) / 60e6
    hop = float(np.median(np.diff(x))) if len(x) > 1 else 0.0
    brk = np.flatnonzero(np.diff(x) > 1.5 * hop) + 1       # windows are missing here: break the lines

    def line(y):
        return np.insert(x, brk, np.nan), np.insert(np.asarray(y, dtype=float), brk, np.nan)

    fig, ax = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    a = ax[0]
    a.plot(*line(cons), "-", lw=4, color="0.8", label="consensus HR1 = HR2")
    a.plot(x, est["HR3_CEP cep40"][0], ".", ms=2, color="tab:green", alpha=0.6, label="HR3_CEP cep40")
    a.plot(*line(est[SAC][0]), "-", lw=1.2, color="tab:blue", label="HR3_SAC")
    a.plot(x, est[HPS][0], ".", ms=2.5, color="tab:red", label="HR3_HPS (today)")
    m = (mon_t >= t_end[0] - 30e6) & (mon_t <= t_end[-1] + 30e6)
    a.plot((mon_t[m] - t0) / 60e6, mon_v[m], "o", ms=4, mfc="none", color="k", label="monitor")
    a.set_ylabel("bpm"); a.set_ylim(20, 270); a.grid(alpha=0.3); a.legend(loc="upper right", ncol=5, fontsize=8)
    a.set_title(f"{name}: rate of each HR3 method against the ward monitor")
    b = ax[1]
    b.plot(*line(est[SAC][1]), "-", lw=0.7, color="tab:blue", label="rho (HR3_SAC)")
    b.plot(*line(pur), "-", lw=0.7, color="tab:orange", label="comb purity")
    b.plot(*line(est[HPS][1]), "-", lw=0.7, color="tab:red", label="hr3_sqi (HPS)")
    b.set_ylim(0, 1.05); b.set_ylabel("quality"); b.set_xlabel("minutes from the first window")
    b.grid(alpha=0.3); b.legend(loc="lower right", ncol=3, fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR3_METHODS_20261114"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--replay", default="replay_lib0.108")
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    ap.add_argument("--no-figs", action="store_true")
    ap.add_argument("--no-gate", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    print(f"hr3_methods_20261114 run {datetime.datetime.now().isoformat(timespec='seconds')}")

    acc, gate_acc, plateau_rows, est_names = {}, {}, [], None
    for subject in args.subjects:
        mon_path = os.path.join(MONITOR_DIR, f"{subject}_snapshots_eye.csv")
        if os.path.exists(mon_path):
            mon_t, mon_v, mon_col = hb.monitor_readings(mon_path)
        else:
            mon_t, mon_v, mon_col = np.zeros(0), np.zeros(0), "none"
        sds = hb.session_dirs(B.SESSIONS_DIR, subject)
        offs = {sd: hb.phone_offset_us(sd) for sd in sds}
        known = [o for o in offs.values() if o is not None]
        fallback = float(np.median(known)) if known else 0.0
        print(f"\n{subject}: monitor column '{mon_col}', {len(mon_t)} readings; phone clock offset per session [ms]: "
              + ", ".join("none" if o is None else f"{o / 1000:.0f}" for o in offs.values())
              + f" (fallback {fallback / 1000:.0f})")
        for sd in sds:
            name = os.path.basename(sd)
            d = hb.load_columns(sd, args.cache)
            P, end_rows, rate = hb.hr3_spectra(d)
            if P.shape[0] == 0:
                print(f"  {name}: no HR3 window"); continue
            factor = int(round(d["fs"] / rate))
            t_end = d["t"][end_rows]
            W = len(end_rows)
            plats = hb.ms100_plateaus(sd) if subject in MS100_SUBJECTS else []
            plat = np.full(W, np.nan)
            for t0, t1, pr in plats:
                plat[(t_end >= t0) & (t_end <= t1)] = pr
            if subject in MS100_SUBJECTS:
                cons, art = np.full(W, np.nan), np.zeros(W, dtype=bool)
            else:
                cons, art = hb.consensus_reference(d, end_rows, factor)
            off = offs[sd] if offs[sd] is not None else fallback
            mon, stable = hb.monitor_reference(mon_t + off, mon_v, t_end)
            est, pur, C6, R = estimates(d, P, end_rows, rate)
            est_names = list(est)
            st = acc.setdefault(subject, {k: [] for k in ("cons", "art", "plat", "mon", "stable", "pur")}
                                | {"est": {e: ([], []) for e in est_names}, "mon_col": mon_col})
            for k, v in (("cons", cons), ("art", art), ("plat", plat), ("mon", mon), ("stable", stable), ("pur", pur)):
                st[k].append(v)
            for e, (hr, q) in est.items():
                st["est"][e][0].append(hr); st["est"][e][1].append(q)
            print(f"  {name}: {W} windows, consensus {int(np.isfinite(cons).sum())}, monitor {int(np.isfinite(mon).sum())} "
                  f"(stable {int(stable.sum())}), HR3_HPS valid {pct(np.isfinite(est[HPS][0]))} %")
            for t0, t1, pr in plats:
                sel = (t_end >= t0) & (t_end <= t1)
                for e, (hr, q) in est.items():
                    cl = hb.error_class(hr[sel], np.full(int(sel.sum()), pr))
                    plateau_rows.append({"session": name, "pr_bpm": pr, "estimator": e, "windows": int(sel.sum()),
                                         "ok_pct": pct(cl == 0), "none_pct": pct(cl == hb.CLASSES.index("none")),
                                         "hr_med": med(hr[sel])})
            if not args.no_gate and subject not in MS100_SUBJECTS and os.path.isdir(os.path.join(sd, "derived", args.replay)):
                board, _ = B.parse_board_session(sd, replay=args.replay)
                g = hb.gate_columns(board)
                rt, rs, rc = B.parse_reference(sd)
                anomalies = session_events.anomaly_intervals(sd, subject)
                n = len(g["t"])
                hr0, hr_s, rho = est[HPS][0], est[SAC][0], est[SAC][1]
                v_sac = np.isfinite(hr_s) & (rho >= RHO_MIN)
                rules = {
                    "no gate (base rule only)": np.ones(W, dtype=bool),
                    "HR3_HPS valid (today)": np.isfinite(hr0),
                    "HR3_HPS valid and agrees with HR3_SAC": np.isfinite(hr0) & within(hr0, hr_s, hb.OK_REL),
                    f"HR3_SAC rho>={RHO_MIN} & purity>={PURITY_MIN}": v_sac & (pur >= PURITY_MIN),
                    "HR3_SAC and HR3_CEP cep40 agree": np.isfinite(est["R2 cep40"][0]),
                    f"... agree & purity>={PURITY_MIN}": np.isfinite(est["R2 cep40"][0]) & (pur >= PURITY_MIN),
                    f"purity>={PURITY_MIN} alone": pur >= PURITY_MIN,
                }
                masks = {k: (np.ones(n, dtype=bool) if k.startswith("no gate") else hb.hold_mask(n, d["ps"], end_rows, v))
                         for k, v in rules.items()}
                res = hb.gate_windows(g, rt, rs, rc, anomalies, masks, min_valid_samples=B.MIN_VALID_SAMPLES,
                                      applied_min_frac=B.APPLIED_MIN_FRAC, anomaly_max_frac=B.ANOMALY_MAX_FRAC,
                                      valid_min_frac=B.VALID_MIN_FRAC)
                for label, rows in res.items():
                    gate_acc.setdefault((subject, label), []).extend(rows)
            if not args.no_figs:
                figure(os.path.join(args.out, f"{name}_hr3.png"), name, t_end, mon_t + off, mon_v, cons, est, pur)

    # ── per subject ──
    S = {}
    for subject, st in acc.items():
        z = {k: np.concatenate(st[k]) for k in ("cons", "art", "plat", "mon", "stable", "pur")}
        z["est"] = {e: (np.concatenate(st["est"][e][0]), np.concatenate(st["est"][e][1])) for e in est_names}
        z["mon_col"] = st["mon_col"]
        S[subject] = z

    # baseline: the tables of 2026-11-12 recomputed on this bench (consensus or plateau reference)
    base_rows, old = [], {(r["subject"], r["estimator"]): r for r in read_csv(os.path.join(BASELINE_DIR, "summary.csv"))}
    for subject, z in S.items():
        ref = z["plat"] if subject in MS100_SUBJECTS else z["cons"]
        has_ref = np.isfinite(ref) & (ref >= hb.HR_MIN) & (ref <= hb.HR_MAX)
        for e, old_name in BASELINE_NAMES.items():
            hr = z["est"][e][0]
            cl = hb.harmonic_class(hr, ref)
            ratio = hr[has_ref] / ref[has_ref]
            now = {"avail_pct": pct(np.isfinite(hr)), "ref_windows": int(has_ref.sum()), "ok_pct": pct(cl[has_ref] == 0),
                   "double_pct": pct(np.abs(ratio / 2 - 1) <= hb.HARMONIC_TOL),
                   "half_pct": pct(np.abs(ratio * 2 - 1) <= hb.HARMONIC_TOL), "none_pct": pct(~np.isfinite(hr[has_ref]))}
            o = old.get((subject, old_name))
            row = {"subject": subject, "estimator": e, "windows": len(hr)}
            worst = 0.0
            for k, v in now.items():
                row[k] = v
                if o is not None and o.get(k) not in (None, "", "nan") and not (isinstance(v, float) and math.isnan(v)):
                    worst = max(worst, abs(float(o[k]) - float(v)))
            row["max_diff_vs_20261112"] = round(worst, 2) if o is not None else "no baseline"
            base_rows.append(row)
    old_gate = {(r["subject"], r["rule"]): r for r in read_csv(os.path.join(BASELINE_DIR, "gate.csv"))}
    gate_map = {"HR3_HPS valid (today)": "HR3 today (HPS3 + SQI>0)",
                f"HR3_SAC rho>={RHO_MIN} & purity>={PURITY_MIN}": f"logc6 rho>=0.5 & purity>={PURITY_MIN}",
                "no gate (base rule only)": "no gate (base rule only)"}
    gsum = []
    for (subject, label), rows in gate_acc.items():
        b = np.array([o - s for s, pub, o in rows if pub])
        row = {"subject": subject, "rule": label, "windows": len(rows),
               "published_pct": round(100 * len(b) / max(len(rows), 1), 1),
               "bias_med": round(float(np.median(b)), 2) if len(b) else math.nan,
               "arms": round(float(np.sqrt(np.mean(b ** 2))), 2) if len(b) else math.nan,
               "off_gt4_pct": round(100 * float(np.mean(np.abs(b) > 4)), 1) if len(b) else math.nan}
        o = old_gate.get((subject, gate_map.get(label, "")))
        row["diff_vs_20261112"] = ("" if o is None else
                                   f"{abs(float(o['published_pct']) - row['published_pct']):.1f} / "
                                   f"{abs(float(o['arms']) - row['arms']):.2f}")
        gsum.append(row)

    # the references against each other
    ref_rows = []
    for subject, z in S.items():
        if subject in MS100_SUBJECTS:
            continue
        W = len(z["mon"])
        both = z["stable"] & np.isfinite(z["cons"])
        ratio = z["cons"][both] / z["mon"][both]
        ref_rows.append({"subject": subject, "monitor_shows": z["mon_col"], "windows": W,
                         "monitor_pct": pct(np.isfinite(z["mon"])), "monitor_stable_pct": pct(z["stable"]),
                         "consensus_pct": pct(np.isfinite(z["cons"])), "both": int(both.sum()),
                         "consensus_within_10pct_of_monitor": pct(np.abs(ratio - 1) <= hb.OK_REL) if both.any() else math.nan,
                         "ratio_med": med(ratio), "ratio_p05": round(float(np.percentile(ratio, 5)), 3) if both.any() else math.nan,
                         "ratio_p95": round(float(np.percentile(ratio, 95)), 3) if both.any() else math.nan})

    # Q1, Q3, Q4: every method against the monitor, all / clean / not clean
    rate_rows = []
    for subject, z in S.items():
        if subject in MS100_SUBJECTS:
            continue
        clean = np.isfinite(z["cons"])
        for subset, sel in (("all", z["stable"]), ("clean", z["stable"] & clean), ("not clean", z["stable"] & ~clean)):
            for e in est_names:
                rate_rows.append({"subject": subject, "subset": subset, "estimator": e}
                                 | class_row(z["est"][e][0], sel, z["mon"]))

    # Q2: where HR3_HPS publishes one third
    third_rows = []
    i_third, i_ok = hb.CLASSES.index("x1/3"), 0
    for subject, z in S.items():
        if subject in MS100_SUBJECTS:
            continue
        hr0 = z["est"][HPS][0]
        sel = z["stable"] & np.isfinite(hr0)
        cl = hb.error_class(hr0, np.where(sel, z["mon"], np.nan))
        third, good = sel & (cl == i_third), sel & (cl == i_ok)
        row = {"subject": subject, "hps_valid_with_ref": int(sel.sum()), "hps_ok_pct": pct(good, sel),
               "hps_third_pct": pct(third, sel), "hps_third_windows": int(third.sum()),
               "third_in_clean_pct": pct(third & np.isfinite(z["cons"]), third),
               "monitor_med_there": med(z["mon"][third]), "hps_med_there": med(hr0[third])}
        for e in (SAC, "HR3_CEP cep40", "HR3_CEP cepc6", "board HR1", "board HR2"):
            c2 = hb.error_class(z["est"][e][0], np.where(third, z["mon"], np.nan))
            row[f"{e} ok there"] = pct(c2[third] == 0)
        row |= {"rho_med_third": med(z["est"][SAC][1][third]), "rho_med_ok": med(z["est"][SAC][1][good]),
                "purity_med_third": med(z["pur"][third]), "purity_med_ok": med(z["pur"][good]),
                "sqi_med_third": med(z["est"][HPS][1][third]), "sqi_med_ok": med(z["est"][HPS][1][good])}
        third_rows.append(row)

    # Q3: do the cepstrum and the spectral autocorrelation fail together? (the other methods were
    # added to this table after the first run, to see what each could add to HR3_SAC)
    joint_rows = []
    others = [f"HR3_CEP {n}" for n in CEP_NAMES] + [HPS, B1, "board HR1", "board HR2"]
    for subject, z in S.items():
        if subject in MS100_SUBJECTS:
            continue
        sel = z["stable"]
        ok_s = hb.error_class(z["est"][SAC][0], np.where(sel, z["mon"], np.nan)) == 0
        for e in others:
            ok_c = hb.error_class(z["est"][e][0], np.where(sel, z["mon"], np.nan)) == 0
            joint_rows.append({"subject": subject, "other": e, "ref_windows": int(sel.sum()),
                               "both_ok": pct(ok_s & ok_c & sel, sel), "only_sac_ok": pct(ok_s & ~ok_c & sel, sel),
                               "only_other_ok": pct(~ok_s & ok_c & sel, sel), "neither_ok": pct(~ok_s & ~ok_c & sel, sel)})

    for fn, rows in (("baseline.csv", base_rows), ("reference.csv", ref_rows), ("rate_vs_monitor.csv", rate_rows),
                     ("hps_third.csv", third_rows), ("cep_vs_sac.csv", joint_rows), ("gate.csv", gsum),
                     ("ms100.csv", plateau_rows)):
        write_csv(os.path.join(args.out, fn), rows)

    # ── console ──
    print("\nBaseline (consensus / plateau reference) against the tables of 2026-11-12:")
    table(base_rows)
    print("\nThe references against each other (windows with a stable monitor reading and a consensus):")
    table(ref_rows)
    cols = ["subject", "subset", "estimator", "ref_windows"] + list(hb.CLASSES) + ["ok_of_avail"]
    print("\nEach method against the monitor, % of the windows with a stable reading:")
    table(rate_rows, cols)
    print("\nWhere HR3_HPS publishes one third of the monitor's rate:")
    for r in third_rows:
        print("  " + "; ".join(f"{k} {v}" for k, v in r.items()))
    print("\nHR3_SAC and each other method, right or wrong together (% of the windows with a stable reading):")
    table(joint_rows)
    if gsum:
        print(f"\nSpO2 artefact gate (ward monitor SpO2, {args.replay}); last column = |published| / |Arms| difference with 2026-11-12:")
        table(gsum)
    if plateau_rows:
        prs = sorted({r["pr_bpm"] for r in plateau_rows})
        print("\nMS100 ok % per plateau (bpm); '.' = 100, 'x' = 0:")
        print(f"{'estimator':16} " + " ".join(f"{p:5.0f}" for p in prs))
        for e in est_names:
            cells = []
            for p in prs:
                v = [r["ok_pct"] for r in plateau_rows if r["estimator"] == e and r["pr_bpm"] == p]
                okp = float(np.mean(v)) if v else math.nan
                cells.append("    ." if okp >= 99.95 else ("    x" if okp <= 0.05 else f"{okp:5.1f}"))
            print(f"{e:16} " + " ".join(cells))


if __name__ == "__main__":
    main()
