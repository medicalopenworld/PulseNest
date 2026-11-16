"""Family 1 (HR1) on the MIMIC PERform neonates: beats against the ECG (2026-11-16, plan HR1LAB step F2).

Our own captures have no ECG waveform, so the beat-level answer comes from a public set: the 100
neonates of the MIMIC PERform Testing Dataset (Charlton et al. 2022, Physiol Meas 43 085007; Zenodo
6950488, ODbL; MIMIC-III Waveform Database), 10 min each of the bedside monitor's PPG, ECG (lead II)
and impedance respiration at 125 Hz. Downloaded on 2026-11-16 with Alex's go (CSV, MD5 checked) to
C:/PRJ/MOW/datasets/mimic_perform/, outside any repository. The 100 training neonates are NOT used here:
they are kept for choosing parameters out of sample (part 2).

Questions (fixed with the plan before the first run, 2026-11-16)
  Q1 Beat level: sensitivity, PPV and F1 of each detector (HR1_THR, HR1_TERMA, HR1_SSF, HR1_MSPTD,
     papers' values, the common front end), scored as Charlton 2022 and compared with his neonatal
     results (MSPTD 95.9 %, qppg 95.2 %; the eight best 84.2-95.9 %).
  Q2 Where they fail: missed and extra beats by ECG heart-rate band (< 100, 100-140, 140-170, >= 170 bpm).
  Q3 Chains: each detector x rule (R0, R1, R2) against the ECG heart rate (60 / mean of the last 5
     reference RR): share of the scored times it publishes, share of what it publishes that is wrong
     (more than 10 % off, hr_bench.OK_REL), and the AUC of its quality index between right and wrong.
     Another instrument (a monitor's filtered 125 Hz pleth, mostly not a foot): ranks, not values.

Methods (fixed before the first run)
  PPG: negated (the pleth rises with the pulse; the bench expects raw OT, which falls) and upsampled x4
       to 500 Hz (scipy resample_poly) so it goes through exactly the board's chains: FrontEnd(500 Hz)
       -> 100 Hz, and HR3_SAC for R2 on the bench's 50 Hz HR3 windows. Each record is one run of the
       probe applied: the detectors and rules start cold at t = 0.
  Reference (pulsenest.hr1_bench.ecg_reference): two QRS detectors of our own and different design,
       beats agreed within 150 ms; a 20 s window is dropped where they disagree or the PPG is flat for
       more than 0.2 s (Charlton's rules; checked on 2026-11-16: the disagreements fall on ECG artefact,
       the flats are the pleth clipped at 0 or 1). The first window (0-20 s) is not scored: start-up is
       the dynamics criterion, measured elsewhere.
  Beat scores (hr1_bench.beat_scores): per record, lag -10..+10 s in 20 ms steps, tolerance 150 ms,
       Se = correct / reference, PPV = correct / detected, F1; median (IQR) over records, as Charlton.
  Chains: read every 0.5 s; the ECG rate is taken at the output time minus the record's lag and the
       detector's latency, from 6 reference beats inside one run of kept windows.
  Corrected after the first run (2026-11-16, before reading the chains' results as findings; found by
       plotting record 008 and the lag table): (1) on a regular neonatal rhythm the beat-count lag aliases
       by whole beats (plateaus 0.06-0.16, 0.46-0.64, 0.92-1.04, 1.38-1.46 s within 2 % of each other in
       record 008; lags from -9 to +9 s across records). Harmless for the beat counts (Q1, Q2 keep
       Charlton's +-10 s search), not for reading the ECG rate at the right time, so Q3's lag is searched
       within -1..+2 s; Q3 is also reported with the unrestricted lag as a sensitivity check. An attempt
       to align by the beat-rate pattern was dropped (spurious lags on short, scattered kept windows).
       (2) A fixed latency is wrong for MSPTD, whose beats arrive 0-11 s late: the ECG rate is read over
       the beats the value was computed from, ending at the last beat the rule had consumed, but never
       earlier than now minus the detector's longest decision delay (so a value kept after the beats
       stopped is still read against the rate now).
  Differences from Charlton, said before measuring: causal detectors run continuously over the
       record (his: offline, per 20 s window, zero-phase filters), one common front end (his: 0.67-8 Hz
       band-pass then each detector's own steps), our QRS detectors (his: jqrs and rpeakdetect).

Result (run 2026-11-16 01:12; report docs/hr1_methods_20261116.md): 86 of 100 records with kept
windows, 46 781 reference beats. Q1 median F1: MSPTD 97.9 %, SSF 97.5 % (Charlton 95.9 / 95.2), THR
93.9 %, TERMA 90.3 %; PPV >= 99.8 % for all: the errors are missed beats. Q2: all lose more above
170 bpm (TERMA a third, THR 22 %, SSF 14 %, MSPTD 13 %). Q3: R0 honest with every detector (0.4-1.8 %
wrong) at 49-86 % published, the detector setting the share (SSF 74 %, THR 63 %); TERMA + R0's errors
are mostly half the rate with high hr1_sqi; R1 publishes 87-96 % with 3-12 % wrong (stale medians
while its own quality is low); R2 in between. Best live chain HR1_SSF + R0.

Outputs in <out> (not versioned): beats_per_record.csv, chains_per_record.csv, summary.txt, f1_box.png.

    python experiments/hr1_mimic_perform_20261116.py [--data DIR] [--out DIR] [--limit N]
"""
import argparse
import csv
import datetime
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr_bench as hb          # noqa: E402
from pulsenest import hr1_bench as h1         # noqa: E402

DATA_DIR = r"C:\PRJ\MOW\datasets\mimic_perform\mimic_perform_test_n_csv"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "sessions",
                       "HR1_MIMIC_PERFORM_20261116")
FS_IN, UP, FS = 125.0, 4, 500.0
SKIP_S = 20.0
LAG3_LO_S, LAG3_HI_S = -1.0, 2.0      # Q3's lag window (see the docstring's correction)
BANDS = ((0, 100), (100, 140), (140, 170), (170, 400))
CHARLTON = {"HR1_MSPTD": 95.9, "HR1_SSF": 95.2}


def read_record(path):
    import pandas as pd
    d = pd.read_csv(path)
    return d["PPG"].to_numpy(float), d["ECG"].to_numpy(float)


def band_of(hr):
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= hr < hi:
            return i
    return None


def auc(q_right, q_wrong):
    if len(q_right) == 0 or len(q_wrong) == 0:
        return math.nan
    return hb.rank_auc(np.asarray(q_right), np.asarray(q_wrong))


def run_record(path):
    from scipy.signal import resample_poly
    ppg, ecg = read_record(path)
    ref, kept, n_win = h1.ecg_reference(ecg, ppg, FS_IN)
    kept = [w for w in kept if w[0] >= SKIP_S]
    x = resample_poly(-ppg, UP, 1)
    rows = h1.output_rows(len(x), FS)
    t_out = rows / FS
    d = {"OT_LED1": x, "ps": np.full(len(x), hb.APPLIED, dtype=np.int32), "fs": FS}
    anchor = h1.sac_anchor(d)(0, len(x))
    rec = {"record": os.path.basename(path)[:-9], "windows": n_win, "kept": len(kept), "n_ref": 0}
    beats_out, chains_out = [], []
    ref_in = ref[h1._inside(ref, kept)]
    rec["n_ref"] = len(ref_in)
    rr_ref = np.diff(ref)
    for D in h1.DETECTORS:
        det = D(100.0)
        b = h1.detect(x, FS, h1.FrontEnd(FS), det)
        tb = b[:, 0] / FS if len(b) else np.zeros(0)
        s = h1.beat_scores(ref, tb, kept)
        row = {"record": rec["record"], "detector": D.name, "kept_windows": len(kept),
               "n_ref": s["n_ref"], "n_det": s["n_det"], "n_correct": s["n_correct"],
               "se": s["se"], "ppv": s["ppv"], "f1": s["f1"], "lag_s": s["lag_s"]}
        # Q2: per heart-rate band, missed reference beats and detected beats (assigned to the band of
        # the nearest reference beat)
        for i in range(len(BANDS)):
            row[f"ref_b{i}"] = row[f"miss_b{i}"] = row[f"det_b{i}"] = 0
        if s["n_ref"] and math.isfinite(s["lag_s"]):
            r_in = s["ref"]
            k = np.searchsorted(ref, r_in)
            hr_local = np.where(k > 0, 60.0 / np.maximum(r_in - ref[np.maximum(k - 1, 0)], 1e-3), np.nan)
            for hr, ok in zip(hr_local, s["ok"]):
                if math.isfinite(hr) and band_of(hr) is not None:
                    bi = band_of(hr)
                    row[f"ref_b{bi}"] += 1
                    row[f"miss_b{bi}"] += int(not ok)
            dsh = tb - s["lag_s"]
            dsh = dsh[h1._inside(dsh, kept)]
            if len(dsh):
                kk = np.clip(np.searchsorted(r_in, dsh), 1, max(len(r_in) - 1, 1))
                near = np.where(np.abs(r_in[kk] - dsh) < np.abs(r_in[kk - 1] - dsh), kk, kk - 1) \
                    if len(r_in) > 1 else np.zeros(len(dsh), int)
                for j in near:
                    hr = hr_local[j]
                    if math.isfinite(hr) and band_of(hr) is not None:
                        row[f"det_b{band_of(hr)}"] += 1
        beats_out.append(row)
        # Q3: chains. The ECG rate is read over the beats the chain's value was computed from: ending at
        # the last beat the rule had consumed (never earlier than now minus the detector's longest
        # decision delay, so a value kept after the beats stopped is read against the rate now), shifted
        # by the beat-count lag searched within -1..+2 s only (corrected after the first run of
        # 2026-11-16, see the docstring). Sensitivity: the same with Charlton's unrestricted lag.
        lag3 = h1.beat_scores(ref, tb, kept, lag_lo_s=LAG3_LO_S, lag_hi_s=LAG3_HI_S)["lag_s"] if len(tb) else math.nan
        row["lag_q3_s"] = lag3
        lag3 = lag3 if math.isfinite(lag3) else 0.0
        lag_wide = s["lag_s"] if math.isfinite(s["lag_s"]) else 0.0
        for R in h1.RULES:
            hr, q, v, last = h1.apply_rule(b, FS, R(), rows, anchor=anchor if R.name == "R2" else None,
                                           latency_s=det.latency_s, return_last=True)
            t_ref = np.maximum(np.where(np.isfinite(last), last / FS, -1.0), t_out - det.latency_max_s)
            hr_ref = h1.ref_hr_at(ref, kept, t_ref - lag3)
            scored = np.isfinite(hr_ref) & (t_out >= SKIP_S)
            est = scored & np.isfinite(hr)
            right = est & (np.abs(hr / np.where(scored, hr_ref, 1.0) - 1.0) <= hb.OK_REL)
            wrong = est & ~right
            pub = scored & v
            hr_ref_w = h1.ref_hr_at(ref, kept, t_ref - lag_wide)
            sc_w = np.isfinite(hr_ref_w) & (t_out >= SKIP_S)
            wrong_w = sc_w & v & np.isfinite(hr) & (np.abs(hr / np.where(sc_w, hr_ref_w, 1.0) - 1.0) > hb.OK_REL)
            chains_out.append({"record": rec["record"], "chain": f"{D.name}+{R.name}",
                               "scored": int(scored.sum()), "published": int(pub.sum()),
                               "pub_wrong": int((wrong & v).sum()),
                               "pub_wide": int((sc_w & v).sum()), "pub_wrong_wide": int(wrong_w.sum()),
                               "q_right": q[right].tolist(), "q_wrong": q[wrong].tolist(),
                               "q_pub": q[pub].tolist(), "wrong_pub": wrong[pub].tolist()})
    return rec, beats_out, chains_out


def avail_at(q_pub, wrong_pub, scored, max_wrong):
    """Criteria 1 and 2 read together (project criteria, 2026-11-15): raise the threshold on the quality
    index over what the chain publishes; the largest share of the scored times still published with at
    most max_wrong of it wrong."""
    if scored == 0 or len(q_pub) == 0:
        return math.nan
    q = np.asarray(q_pub); w = np.asarray(wrong_pub, dtype=bool)
    order = np.argsort(-q, kind="stable")
    qs, ws = q[order], w[order]
    cum_w = np.cumsum(ws); n = np.arange(1, len(qs) + 1)
    last = np.r_[qs[1:] != qs[:-1], True]          # cut only between different quality values
    ok = last & (cum_w / n <= max_wrong)
    return 100.0 * n[ok].max() / scored if ok.any() else 0.0


def med_iqr(v):
    v = np.asarray([x for x in v if math.isfinite(x)])
    if len(v) == 0:
        return "n/a"
    p = np.percentile(v, [25, 50, 75])
    return f"{p[1]:.1f} ({p[0]:.1f}-{p[2]:.1f})"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=DATA_DIR)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.data, "*_data.csv")))
    if args.limit:
        files = files[:args.limit]
    lines = [f"hr1_mimic_perform_20261116 run {datetime.datetime.now().isoformat(timespec='seconds')}",
             f"records {len(files)} from {args.data}"]
    recs, beats, chains = [], [], []
    for i, f in enumerate(files):
        rec, b, c = run_record(f)
        recs.append(rec); beats += b; chains += c
        print(f"{i + 1:3d}/{len(files)} {rec['record']}: kept {rec['kept']}/{rec['windows']} windows, "
              f"{rec['n_ref']} reference beats", flush=True)

    kept_min = [r["kept"] * h1.REF_WIN_S / 60.0 for r in recs]
    lines.append(f"kept windows (after the first 20 s): median {np.median(kept_min):.1f} min per record, "
                 f"records with none {sum(1 for r in recs if r['kept'] == 0)}, reference beats "
                 f"{sum(r['n_ref'] for r in recs)}")
    lines.append("\nQ1 beat level, median (IQR) over the records with reference beats")
    lines.append(f"{'detector':11s} {'Se %':>18s} {'PPV %':>18s} {'F1 %':>18s} {'pooled F1':>9s}  Charlton F1")
    for D in h1.DETECTORS:
        rows = [r for r in beats if r["detector"] == D.name and r["n_ref"] > 0]
        nr = sum(r["n_ref"] for r in rows); nd = sum(r["n_det"] for r in rows); nc = sum(r["n_correct"] for r in rows)
        pf1 = 2 * nc / (nr + nd) * 100 if nr + nd else math.nan
        lines.append(f"{D.name:11s} {med_iqr([r['se'] for r in rows]):>18s} {med_iqr([r['ppv'] for r in rows]):>18s} "
                     f"{med_iqr([r['f1'] for r in rows]):>18s} {pf1:9.1f}  {CHARLTON.get(D.name, '')}")
    lines.append("\nQ2 by ECG heart-rate band (pooled): reference beats, missed %, detected / reference")
    for D in h1.DETECTORS:
        rows = [r for r in beats if r["detector"] == D.name]
        parts = []
        for i, (lo, hi) in enumerate(BANDS):
            nr = sum(r[f"ref_b{i}"] for r in rows); nm = sum(r[f"miss_b{i}"] for r in rows)
            nd = sum(r[f"det_b{i}"] for r in rows)
            parts.append(f"{lo}-{hi}: {nr} ref, {100 * nm / nr if nr else math.nan:.1f} % missed, "
                         f"{nd / nr if nr else math.nan:.3f} det/ref")
        lines.append(f"{D.name:11s} " + " | ".join(parts))
    lines.append("\nQ3 chains against the ECG rate (pooled over records): published %, wrong of published %, "
                 "AUC of the quality index right vs wrong; published % with the quality threshold raised until "
                 "at most 1 % / 5 % of it is wrong")
    for D in h1.DETECTORS:
        for R in h1.RULES:
            name = f"{D.name}+{R.name}"
            rows = [c for c in chains if c["chain"] == name]
            sc = sum(c["scored"] for c in rows); pb = sum(c["published"] for c in rows)
            wr = sum(c["pub_wrong"] for c in rows)
            qr = [x for c in rows for x in c["q_right"]]; qw = [x for c in rows for x in c["q_wrong"]]
            qp = [x for c in rows for x in c["q_pub"]]; wp = [x for c in rows for x in c["wrong_pub"]]
            pw = sum(c["pub_wide"] for c in rows); ww = sum(c["pub_wrong_wide"] for c in rows)
            lines.append(f"{name:15s} published {100 * pb / sc if sc else math.nan:5.1f} %  wrong "
                         f"{100 * wr / pb if pb else math.nan:5.1f} %  AUC {auc(qr, qw):.3f}  "
                         f"at 1 %: {avail_at(qp, wp, sc, 0.01):5.1f} %  at 5 %: {avail_at(qp, wp, sc, 0.05):5.1f} %"
                         f"  (scored {sc}; wrong with the unrestricted lag {100 * ww / pw if pw else math.nan:4.1f} %)")
    txt = "\n".join(lines)
    print("\n" + txt)
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(os.path.join(args.out, "beats_per_record.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(beats[0])); w.writeheader(); w.writerows(beats)
    with open(os.path.join(args.out, "chains_per_record.csv"), "w", newline="", encoding="utf-8") as f:
        keys = ["record", "chain", "scored", "published", "pub_wrong"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(chains)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 4))
        data = [[r["f1"] for r in beats if r["detector"] == D.name and r["n_ref"] > 0 and math.isfinite(r["f1"])]
                for D in h1.DETECTORS]
        ax.boxplot(data, whis=(10, 90), showfliers=False)
        ax.set_xticks(range(1, len(h1.DETECTORS) + 1), [D.name for D in h1.DETECTORS])
        ax.set_ylabel("F1 per record (%)"); ax.set_title("MIMIC PERform test neonates, beats against the ECG")
        ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(os.path.join(args.out, "f1_box.png"), dpi=110)
        plt.close(fig)
    except Exception as e:  # the figure is a convenience; the numbers are in summary.txt
        print(f"figure skipped: {e}")


if __name__ == "__main__":
    main()
