"""Does the C++ port of HR3_SAC give the Python bench's numbers on the stored captures?

Why this exists
---------------
Step 1 of the proposal of 2026-11-14 to measure the cost of HR3_SAC on the board: before any
board is flashed, the kernel written in C++ on the library's branch experiment/hr3-sac (compile
flag INCUNEST_AFE4490_EXP_HR3_SAC, off by default, nothing published) must reproduce
pulsenest/hr_bench.py window by window. The bench is float64 numpy on its own copy of the HR3 front
end; the port is float32 inside the library, behind the library's real filter, decimator and FFT.

What it does
------------
For every stored session it writes OT_LED1 and ProbeState to a temporary binary file, runs the
library's host test executable test_hr3_sac (its optional test 6 replays the file through
test_feed_hr3 and writes one line per HR3 window), and compares each window with the bench:
today's HR3 (so that a difference in the front end is seen on its own), the HR3_SAC rate, rho and
the comb purity. Windows are matched by the row of their last sample.

    python test/run_host_tests.py hr3_sac            (in the library branch: builds the executable)
    python experiments/hr3_sac_port_check_20261114.py --exe <.../test/build/test_hr3_sac.exe>
                                                      [--subjects ...] [--cache DIR] [--out DIR]

Outputs in --out (default captures/sessions/HR3_SAC_PORT_20261114/, not versioned): port_check.csv
(one row per session) and the console table.

Result (2026-11-14; library branch experiment/hr3-sac, uncommitted working tree on adbc4cb)
------
- The 23 940 HR3 windows of the 19 sessions match one to one (same last row on both sides).
- Today's HR3: the port's value is within 0.5 bpm of the bench's in 100.00 % of the windows, so
  the bench's copy of the front end and the library's real one agree.
- HR3_SAC rate: within 0.1 bpm in 99.41 %, within 1 bpm in 99.70 %; median difference 0.002 bpm,
  99th percentile 0.043 bpm; rho differs by 0.0002 and the comb purity by 0.000004 (medians).
- 71 windows differ (a value on one side only: 54; another lag: 16): they have no comb (median
  rho 0.00, purity 0.00), where float32 against float64 tips a threshold. 13 of the 16 are SUBJ10.
- Of the windows a validity rule would publish (rho >= 0.5 and purity >= 0.3: 17 525 in the bench,
  17 527 in the port), none has rates more than 1 bpm apart; 2 are valid on one side only.
- The port is the bench, for every window that matters. The board is not measured yet (step 2).
"""
import argparse
import csv
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr_bench as hb          # noqa: E402
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
RATE_TOL_BPM = (0.1, 0.5, 1.0)


def replay(exe, d, tmp):
    """Run the port on one session: {row of the window's last sample: (hr3, sqi, rate, rho, purity)}."""
    n = len(d["OT_LED1"])
    bin_path, csv_path = os.path.join(tmp, "capture.bin"), os.path.join(tmp, "windows.csv")
    with open(bin_path, "wb") as f:
        f.write(np.int32(n).tobytes())
        f.write(np.float32(d["fs"]).tobytes())
        f.write(d["OT_LED1"].astype(np.float32).tobytes())
        f.write(d["ps"].astype(np.int8).tobytes())
    env = dict(os.environ, HR3_SAC_CAPTURE_BIN=bin_path, HR3_SAC_OUT_CSV=csv_path)
    r = subprocess.run([exe], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[int(row["row"])] = tuple(float(row[k]) for k in ("hr3", "hr3_sqi", "sac_rate", "sac_rho", "sac_purity"))
    return out


def agree(a, b, tol):
    """Share of windows where both have no value, or both have one within tol."""
    fa, fb = np.isfinite(a), np.isfinite(b)
    ok = (~fa & ~fb) | (fa & fb & (np.abs(np.where(fa & fb, a - b, 0.0)) <= tol))
    return 100.0 * float(ok.mean()) if len(a) else math.nan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True, help="the library's host test executable test_hr3_sac")
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR3_SAC_PORT_20261114"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    rows, acc = [], {k: [] for k in ("hps_b", "hps_c", "rate_b", "rate_c", "rho_b", "rho_c", "pur_b", "pur_c")}
    with tempfile.TemporaryDirectory() as tmp:
        for subject in args.subjects:
            for sd in hb.session_dirs(B.SESSIONS_DIR, subject):
                name = os.path.basename(sd)
                d = hb.load_columns(sd, args.cache)
                if abs(d["fs"] - 500.0) > 1e-6:
                    print(f"  {name}: AFE rate {d['fs']} Hz, not 500: skipped"); continue
                P, end_rows, rate = hb.hr3_spectra(d)
                if P.shape[0] == 0:
                    print(f"  {name}: no HR3 window"); continue
                hps_b = hb.hps_estimate(P, *hb.hps(P, 3), rate)[0]
                rate_b, rho_b, _, _ = hb.hr3_sac(P, rate)
                pur_b = hb.comb_purity(P, rate_b, rate)
                port = replay(args.exe, d, tmp)
                both = np.array([r in port for r in end_rows])
                c = np.array([port[r] for r in end_rows[both]]) if both.any() else np.zeros((0, 5))
                hps_c, rate_c, rho_c, pur_c = c[:, 0], c[:, 2], c[:, 3], c[:, 4]
                hb_, rb, ob, pb = hps_b[both], rate_b[both], rho_b[both], pur_b[both]
                fin = np.isfinite(rb) & np.isfinite(rate_c)
                dr = np.abs(rb[fin] - rate_c[fin])
                row = {"session": name, "bench_windows": len(end_rows), "port_windows": len(port),
                       "matched": int(both.sum()),
                       "hr3_same_0.5bpm_pct": round(agree(hb_, hps_c, 0.5), 2)}
                for tol in RATE_TOL_BPM:
                    row[f"sac_same_{tol}bpm_pct"] = round(agree(rb, rate_c, tol), 2)
                row |= {"sac_value_in_one_only": int((np.isfinite(rb) != np.isfinite(rate_c)).sum()),
                        "sac_diff_gt_3bpm": int((dr > 3.0).sum()),
                        "sac_diff_max_bpm": round(float(dr.max()), 3) if len(dr) else math.nan,
                        "rho_diff_max": round(float(np.abs(ob[fin] - rho_c[fin]).max()), 5) if fin.any() else math.nan,
                        "purity_diff_max": round(float(np.abs(pb[fin] - pur_c[fin]).max()), 5) if fin.any() else math.nan}
                rows.append(row)
                for k, v in (("hps_b", hb_), ("hps_c", hps_c), ("rate_b", rb), ("rate_c", rate_c),
                             ("rho_b", ob), ("rho_c", rho_c), ("pur_b", pb), ("pur_c", pur_c)):
                    acc[k].append(v)
                print(f"  {name}: {row['matched']}/{row['bench_windows']} windows matched, HR3_SAC within 0.5 bpm "
                      f"{row['sac_same_0.5bpm_pct']} %, different lag in {row['sac_diff_gt_3bpm']}")
    if not rows:
        print("no session"); return
    z = {k: np.concatenate(v) for k, v in acc.items()}
    fin = np.isfinite(z["rate_b"]) & np.isfinite(z["rate_c"])
    dr = np.abs(z["rate_b"][fin] - z["rate_c"][fin])
    total = {"session": "ALL", "bench_windows": sum(r["bench_windows"] for r in rows),
             "port_windows": sum(r["port_windows"] for r in rows), "matched": len(z["rate_b"]),
             "hr3_same_0.5bpm_pct": round(agree(z["hps_b"], z["hps_c"], 0.5), 2)}
    for tol in RATE_TOL_BPM:
        total[f"sac_same_{tol}bpm_pct"] = round(agree(z["rate_b"], z["rate_c"], tol), 2)
    total |= {"sac_value_in_one_only": int((np.isfinite(z["rate_b"]) != np.isfinite(z["rate_c"])).sum()),
              "sac_diff_gt_3bpm": int((dr > 3.0).sum()), "sac_diff_max_bpm": round(float(dr.max()), 3),
              "rho_diff_max": round(float(np.abs(z["rho_b"][fin] - z["rho_c"][fin]).max()), 5),
              "purity_diff_max": round(float(np.abs(z["pur_b"][fin] - z["pur_c"][fin]).max()), 5)}
    rows.append(total)
    with open(os.path.join(args.out, "port_check.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print("\nALL: " + "; ".join(f"{k} {v}" for k, v in total.items() if k != "session"))
    print(f"median |rate difference| {np.median(dr):.4f} bpm, 99th percentile {np.percentile(dr, 99):.4f} bpm; "
          f"median |rho difference| {np.median(np.abs(z['rho_b'][fin] - z['rho_c'][fin])):.6f}; "
          f"median |purity difference| {np.median(np.abs(z['pur_b'][fin] - z['pur_c'][fin])):.6f}")
    # where do the two differ? (a value in one only, or more than 1 bpm apart)
    fb, fc = np.isfinite(z["rate_b"]), np.isfinite(z["rate_c"])
    same = (~fb & ~fc) | (fb & fc & (np.abs(np.where(fb & fc, z["rate_b"] - z["rate_c"], 0.0)) <= 1.0))
    rho_any = np.maximum(z["rho_b"], z["rho_c"])
    print(f"windows that differ: {int((~same).sum())} of {len(same)} ({100 * (~same).mean():.2f} %); "
          f"median rho there {np.median(rho_any[~same]):.2f} (all windows {np.median(rho_any):.2f}), "
          f"median purity there {np.median(np.maximum(z['pur_b'], z['pur_c'])[~same]):.2f}")
    # the windows a validity rule would publish (rho >= 0.5 and purity >= 0.3, either side)
    vb = fb & (z["rho_b"] >= 0.5) & (z["pur_b"] >= 0.3)
    vc = fc & (z["rho_c"] >= 0.5) & (z["pur_c"] >= 0.3)
    print(f"windows valid under rho >= 0.5 and purity >= 0.3: bench {int(vb.sum())}, port {int(vc.sum())}, "
          f"valid in one only {int((vb != vc).sum())}; both valid and more than 1 bpm apart {int((vb & vc & ~same).sum())}")


if __name__ == "__main__":
    main()
