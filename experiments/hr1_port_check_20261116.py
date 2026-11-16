"""Does the library's HR1 of v0.122 give the bench's HR1_THR + R0 on the stored captures?

Why this exists
---------------
Alex, 2026-11-16 ("Sí, pórtalo"): the common front end of the HR1 methods (pulsenest/hr1_bench.py
FrontEnd) goes into the library with today's detector and rule unchanged, the change that took the
board's HR1 from 47 to 66 % published at the same honesty in docs/hr1_methods_20261116.md (F3). Before
any board is flashed, the library's float32 implementation must reproduce the bench's float64 chain
(FrontEnd + ThrDetector with interpolation + RuleR0) output by output.

What it does
------------
For every stored session it writes OT_LED1 and ProbeState to a temporary binary file, runs the library's
host test executable test_hr1 (its optional test 12 replays the file through test_feed_hr1 and writes
hr1 and hr1_sqi every 0.5 s of each applied run), and compares each output with the bench at the same
row: same validity (hr1_sqi > 0), HR1 within 0.1 / 0.5 / 1 bpm, hr1_sqi within 0.01 / 0.05.

    python test_lib/runner/run_host_tests.py hr1        (builds test_hr1.exe from the working copy)
    python experiments/hr1_port_check_20261116.py [--exe <.../test_hr1.exe>] [--subjects ...]

Outputs in --out (default captures/sessions/HR1_PORT_20261116/, not versioned): port_check.csv.

Result (2026-11-16, library working copy of v0.122): 25 158 outputs of the 19 sessions, the same rows on
both sides; same validity in 99.97 %; where both have a value (24 386): HR1 within 0.1 bpm 99.77 %,
0.5 bpm 99.88 %, 1 bpm 99.89 %; hr1_sqi within 0.01 99.80 %. The few large differences (up to 32 bpm,
on isolated outputs of three sessions) are threshold crossings that float32 and float64 decide
differently, after which the 5-RR buffers differ for five beats. The port is the bench.
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
from pulsenest import hr1_bench as h1         # noqa: E402
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_lib", "runner", "build",
                   "test_hr1.exe")


def replay(exe, d, tmp):
    """Run the library on one session: {row: (hr1, hr1_sqi)}."""
    n = len(d["OT_LED1"])
    bin_path, csv_path = os.path.join(tmp, "capture.bin"), os.path.join(tmp, "hr1.csv")
    with open(bin_path, "wb") as f:
        f.write(np.int32(n).tobytes())
        f.write(np.float32(d["fs"]).tobytes())
        f.write(d["OT_LED1"].astype(np.float32).tobytes())
        f.write(d["ps"].astype(np.int8).tobytes())
    env = dict(os.environ, HR1_CAPTURE_BIN=bin_path, HR1_OUT_CSV=csv_path)
    r = subprocess.run([exe], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[int(row["row"])] = (float(row["hr1"]), float(row["hr1_sqi"]))
    return out


def bench(d):
    """The bench's HR1_THR + R0 on the common front end: {row: (hr, sqi)}, rows as the library's."""
    fs = d["fs"]
    on = (d["ps"] == hb.APPLIED).astype(np.int8)
    e = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    out = {}
    for r0, r1 in zip(e[::2], e[1::2]):
        x = d["OT_LED1"][r0:r1]
        rows = h1.output_rows(len(x), fs)
        if len(rows) == 0:
            continue
        b = h1.detect(x, fs, h1.FrontEnd(fs), h1.ThrDetector(h1.FrontEnd(fs).rate))
        hr, q, _ = h1.apply_rule(b, fs, h1.RuleR0(), rows)
        for r, a, s in zip(rows, hr, q):
            out[int(r0 + r)] = (float(a), float(s))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", default=EXE)
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR1_PORT_20261116"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    rows_out = []
    tot = {"n": 0, "same_valid": 0, "both": 0, "d01": 0, "d05": 0, "d1": 0, "s001": 0, "s005": 0}
    with tempfile.TemporaryDirectory() as tmp:
        for subject in args.subjects:
            for sd in hb.session_dirs(B.SESSIONS_DIR, subject):
                name = os.path.basename(sd)
                d = hb.load_columns(sd, args.cache)
                lib = replay(args.exe, d, tmp)
                ben = bench(d)
                keys = sorted(set(lib) & set(ben))
                missing = len(set(lib) ^ set(ben))
                if not keys:
                    print(f"{name}: no common output"); continue
                L = np.array([lib[k] for k in keys]); Bn = np.array([ben[k] for k in keys])
                vl, vb = L[:, 1] > 0, Bn[:, 1] > 0
                both = np.isfinite(L[:, 0]) & np.isfinite(Bn[:, 0])
                dh = np.abs(L[:, 0] - Bn[:, 0])[both]
                ds = np.abs(L[:, 1] - Bn[:, 1])[both]
                r = {"session": name, "outputs": len(keys), "rows_on_one_side_only": missing,
                     "same_validity_pct": round(100.0 * float(np.mean(vl == vb)), 2),
                     "hr1_within_0.1_pct": round(100.0 * float(np.mean(dh <= 0.1)), 2) if both.any() else math.nan,
                     "hr1_within_1_pct": round(100.0 * float(np.mean(dh <= 1.0)), 2) if both.any() else math.nan,
                     "sqi_within_0.01_pct": round(100.0 * float(np.mean(ds <= 0.01)), 2) if both.any() else math.nan,
                     "max_dhr_bpm": round(float(dh.max()), 3) if both.any() else math.nan}
                rows_out.append(r)
                tot["n"] += len(keys); tot["same_valid"] += int((vl == vb).sum()); tot["both"] += int(both.sum())
                tot["d01"] += int((dh <= 0.1).sum()); tot["d05"] += int((dh <= 0.5).sum()); tot["d1"] += int((dh <= 1.0).sum())
                tot["s001"] += int((ds <= 0.01).sum()); tot["s005"] += int((ds <= 0.05).sum())
                print(r, flush=True)
    with open(os.path.join(args.out, "port_check.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0])); w.writeheader(); w.writerows(rows_out)
    n, b = tot["n"], tot["both"]
    print(f"\nALL: {n} outputs; same validity {100 * tot['same_valid'] / n:.2f} %; where both have a value "
          f"({b}): HR1 within 0.1 bpm {100 * tot['d01'] / b:.2f} %, 0.5 bpm {100 * tot['d05'] / b:.2f} %, "
          f"1 bpm {100 * tot['d1'] / b:.2f} %; sqi within 0.01 {100 * tot['s001'] / b:.2f} %, "
          f"0.05 {100 * tot['s005'] / b:.2f} %")


if __name__ == "__main__":
    main()
