"""The lab's HR1 mirror (HR1TestCalc, lab v1.115) gives the bench's chain that lib v0.122 was checked against.

HR1TestCalc is fed one sample at a time, as PPGMonitor feeds it live; the bench's chain
(pulsenest.hr1_bench: FrontEnd + ThrDetector + RuleR0) is the one experiments/hr1_port_check_20261116.py
compared with the library's host build (same validity in 99.97 % of 25 158 outputs). If the mirror and
the bench agree here, HR1TEST compares the board against the library as it is.

Checks: on synthetic pulses (60, 150, 240 bpm, noise, a stretch with the probe not applied) the mirror's
HR1 and SQI equal the bench's every 0.5 s; HR1 reaches the rate; the diagnostic buffers stay at the AFE
rate; RESET TO DEFAULTS restores the library's values.

    python test_pulsenest/hr1test_mirror_test.py
"""
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402
import pulsenest_lab as P  # noqa: E402
from pulsenest import hr1_bench as h1  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  HR1TestCalc mirrors lib v0.122")
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


FS = 500.0
APPLIED, OFF = 2, 0


def run_both(x, ps):
    """Mirror and bench on the same signal: arrays of (hr, sqi) at the bench's output rows."""
    calc = P.HR1TestCalc()
    hr_m, sq_m, rows_all = [], [], []
    on = (ps == APPLIED).astype(np.int8)
    e = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    want = set()
    for r0, r1 in zip(e[::2], e[1::2]):
        for r in h1.output_rows(r1 - r0, FS):
            want.add(int(r0 + r))
    for i in range(len(x)):
        calc.update(float(x[i]), FS, int(ps[i]))
        if i in want:
            rows_all.append(i); hr_m.append(calc.hr_bpm); sq_m.append(calc.hr_sqi)
    hr_b, sq_b = {}, {}
    for r0, r1 in zip(e[::2], e[1::2]):
        seg = x[r0:r1]
        rows = h1.output_rows(len(seg), FS)
        b = h1.detect(seg, FS, h1.FrontEnd(FS), h1.ThrDetector(100.0))
        hr, q, _ = h1.apply_rule(b, FS, h1.RuleR0(), rows)
        for r, a, s in zip(rows, hr, q):
            hr_b[int(r0 + r)], sq_b[int(r0 + r)] = a, s
    hb_ = np.array([hr_b[r] for r in rows_all]); sb_ = np.array([sq_b[r] for r in rows_all])
    return np.array(hr_m, float), np.array(sq_m, float), hb_, sb_, calc


for bpm in (60, 150, 240):
    rr = 60.0 / bpm * (1.0 + 0.02 * np.random.default_rng(bpm).standard_normal(int(bpm) + 5))
    x, _ = h1.synth_ppg(FS, 40, rr_s=list(rr), noise=0.03, wander=0.3, seed=bpm)
    ps = np.full(len(x), APPLIED, dtype=np.int8)
    ps[int(18 * FS):int(20 * FS)] = OFF                       # probe off for 2 s, then a new run
    hm, sm, hbn, sbn, calc = run_both(x, ps)
    fin = np.isfinite(hbn) & (hbn > 0)
    same_valid = np.array_equal(sm > 0, sbn > 0)
    close = np.allclose(np.where(fin, hm, 0.0), np.where(fin, hbn, 0.0), atol=1e-6) and np.allclose(sm, sbn, atol=1e-9)
    check(f"{bpm} bpm: the mirror equals the bench every 0.5 s (probe off 2 s mid-way)", same_valid and close,
          f"valid {np.sum(sm > 0)} vs {np.sum(sbn > 0)}")
    last = hm[-1]
    check(f"{bpm} bpm: HR1 reaches the rate within 2 %", math.isfinite(last) and abs(last / bpm - 1) < 0.02, f"{last}")
    check(f"{bpm} bpm: the diagnostic buffers stay at the AFE rate",
          len(calc.diag_front_end) == min(calc.DIAG_BUF_LEN, len(x) - int(20 * FS)))

calc = P.HR1TestCalc()
calc.f_low_hz, calc.f_high_hz, calc.threshold_factor = 1.0, 8.0, 0.5
calc.reset_to_defaults()
check("RESET TO DEFAULTS restores the library's values (0.5 / 15 Hz, 0.6, 0.185 s)",
      (calc.f_low_hz, calc.f_high_hz, calc.threshold_factor, calc.refractory_s) == (0.5, 15.0, 0.6, 0.185))

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
