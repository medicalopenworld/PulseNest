"""Does the HR1 bench reproduce the board's HR1? (2026-11-16, plan HR1LAB step F1)

Before the family-1 study scores anything, the bench's copy of today's chain (pulsenest/hr1_bench.py:
LibFrontEnd + ThrDetector at the AFE rate without interpolation + RuleR0) is run on every stored
session and compared, every 0.5 s, with the HR1 and HR1_SQI the board published at the same row.
The same check HR2 passed in docs/hr2_methods_20261115.md ("The bench mirrors the board").

Rows compared: probe applied (each run of ProbeState APPLIED processed apart, as the library resets
on any other state). Reported per session: same validity (published HR1 with HR1_SQI > 0 on both or
on neither), HR1 within 1 % where both publish, HR1_SQI within 0.05, and the largest difference.
The board's float32 against the bench's float64 can move a threshold crossing by one sample, so a few
differences are expected; an octave or a systematic offset would not be.

Result (run 2026-11-16, 19 sessions, SUBJ08-11 HOSPNAV and the two MS100 sessions): same validity
in 97.9-100 % of the rows, HR1 within 1 % in 99.1-100 % where both publish, HR1_SQI within 0.05 in
99.1-100 %; largest single difference 6.1 bpm (isolated rows). Four SUBJ10 sessions have no row
where both publish (motion; the same validity there is 99.6-100 %). The bench mirrors the board.

Outputs: printed table and <out>/hr1_board_mirror.csv (not versioned).

    python experiments/hr1_board_mirror_20261116.py
"""
import argparse
import csv
import datetime
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr_bench as hb          # noqa: E402
from pulsenest import hr1_bench as h1         # noqa: E402
from tools import spo2_bias_analysis as B     # noqa: E402

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")


def pct(m):
    return 100.0 * float(np.mean(m)) if len(m) else float("nan")


def mirror_session(d):
    """Bench R0 against the board at every 0.5 s row of the applied runs: (hr_b, sqi_b, hr_k, sqi_k)."""
    fs = d["fs"]
    on = (d["ps"] == hb.APPLIED).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    cols = [[], [], [], []]
    for r0, r1 in zip(edges[::2], edges[1::2]):
        x = d["OT_LED1"][r0:r1]
        rows = h1.output_rows(len(x), fs)
        if len(rows) == 0:
            continue
        beats = h1.detect(x, fs, h1.LibFrontEnd(fs), h1.ThrDetector(fs, interpolate=False))
        hr, sqi, _ = h1.apply_rule(beats, fs, h1.RuleR0(), rows)
        cols[0].append(hr); cols[1].append(sqi)
        cols[2].append(d["HR1"][r0 + rows]); cols[3].append(d["HR1_SQI"][r0 + rows])
    return [np.concatenate(c) if c else np.zeros(0) for c in cols]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "HR1_BOARD_MIRROR_20261116"))
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    print(f"hr1_board_mirror_20261116 run {datetime.datetime.now().isoformat(timespec='seconds')}")
    rows_out = []
    hdr = f"{'session':34s} {'rows':>6s} {'same valid %':>12s} {'HR1 1 % %':>10s} {'SQI .05 %':>10s} {'max |dHR|':>9s}"
    print(hdr)
    for subject in args.subjects:
        for sd in hb.session_dirs(B.SESSIONS_DIR, subject):
            name = os.path.basename(sd)
            d = hb.load_columns(sd, args.cache)
            hr_b, sqi_b, hr_k, sqi_k = mirror_session(d)
            if len(hr_b) == 0:
                print(f"{name:34s} no applied run"); continue
            pub_b = np.isfinite(hr_b) & (sqi_b > 0)
            pub_k = np.isfinite(hr_k) & (hr_k > 0) & (sqi_k > 0)
            both = np.isfinite(hr_b) & np.isfinite(hr_k) & (hr_k > 0)
            rel = np.abs(hr_b[both] / hr_k[both] - 1.0)
            r = {"session": name, "rows": len(hr_b), "same_validity_pct": pct(pub_b == pub_k),
                 "hr1_within_1pct_pct": pct(rel <= 0.01),
                 "sqi_within_0.05_pct": pct(np.abs(sqi_b[both] - sqi_k[both]) <= 0.05),
                 "max_abs_dhr_bpm": float(np.max(np.abs(hr_b[both] - hr_k[both]))) if both.any() else float("nan")}
            rows_out.append(r)
            print(f"{name:34s} {r['rows']:6d} {r['same_validity_pct']:12.1f} {r['hr1_within_1pct_pct']:10.1f} "
                  f"{r['sqi_within_0.05_pct']:10.1f} {r['max_abs_dhr_bpm']:9.1f}")
    with open(os.path.join(args.out, "hr1_board_mirror.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]))
        w.writeheader(); w.writerows(rows_out)


if __name__ == "__main__":
    main()
