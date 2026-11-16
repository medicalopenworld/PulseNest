"""Offline checks for pulsenest/hr1_bench.py -- family 1 (beats in time) of the heartbeat resolvers.

On signals whose answer is known, with no capture and no board: the common front end's response, the
block invariance that lets HR1LAB and the study share the code, the library's HR1 against a literal
per-sample port of _hr1_update (refractory quirk included), each detector on synthetic pulses across
the neonatal range, the three publication rules, and the beat matcher. Characterisation lines (INFO)
print what the papers' values do outside their design range; they are findings, not failures.

    python test_pulsenest/hr1_bench_test.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr1_bench as h1  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  family 1 of the heartbeat resolvers")
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


FS = 500.0

# ── common front end: rate and response ──
fe = h1.FrontEnd(FS)
check("front end decimates 500 Hz to 100 Hz", fe.factor == 5 and fe.rate == 100.0)
fe1250 = h1.FrontEnd(1250.0)
check("at 1250 Hz the factor is derived as the library's lroundf (13 -> 96.15 Hz)",
      fe1250.factor == 13 and abs(fe1250.rate - 96.1538) < 1e-3)


def gain_db(f, fs=FS, dur=40.0):
    t = np.arange(int(dur * fs)) / fs
    fe = h1.FrontEnd(fs)
    y, _ = fe.process(1000.0 + np.sin(2 * np.pi * f * t))
    tail = y[len(y) // 2:]
    return 20 * math.log10((tail.max() - tail.min()) / 2.0)


expect = {0.5: -3.01, 1.0: -0.26, 4.33: 0.0, 8.7: -0.06, 13.0: -1.2}
for f, g in expect.items():
    m = gain_db(f)
    check(f"front end gain at {f} Hz is {g:+.2f} dB within 0.3 dB", abs(m - g) <= 0.3, f"{m:+.2f} dB")
m25 = gain_db(25.0)
check("front end attenuates 25 Hz by more than 15 dB", m25 < -15.0, f"{m25:+.1f} dB")

# ── block invariance: the study's whole-run feed and the lab's 20 ms blocks give the same beats ──
x, _ = h1.synth_ppg(FS, 40, bpm=150, noise=0.05, wander=0.5, seed=3)
for D in h1.DETECTORS:
    whole = h1.detect(x, FS, h1.FrontEnd(FS), D(100.0))
    blk = h1.detect(x, FS, h1.FrontEnd(FS), D(100.0), block=10)
    same = whole.shape == blk.shape and np.allclose(whole, blk, atol=1e-6, equal_nan=True)
    check(f"{D.name} gives the same beats fed whole or in 20 ms blocks", same,
          f"{whole.shape} vs {blk.shape}")
whole = h1.detect(x, FS, h1.LibFrontEnd(FS), h1.ThrDetector(FS, interpolate=False))
blk = h1.detect(x, FS, h1.LibFrontEnd(FS), h1.ThrDetector(FS, interpolate=False), block=10)
check("library front end + HR1_THR are block invariant",
      whole.shape == blk.shape and np.allclose(whole, blk, atol=1e-6, equal_nan=True))

# ── HR1LAB's traces (what each detector decides on) record without changing a beat ──
n_dec = len(h1.FrontEnd(FS).process(x)[0])
for D in (h1.ThrDetector, h1.SsfDetector, h1.TermaDetector):
    plain = h1.detect(x, FS, h1.FrontEnd(FS), D(100.0), block=10)
    d = D(100.0)
    if D is h1.SsfDetector:
        d.t1_trace = []
    else:
        d.trace = []
    traced = h1.detect(x, FS, h1.FrontEnd(FS), d, block=10)
    same = plain.shape == traced.shape and np.array_equal(plain, traced, equal_nan=True)
    if D is h1.ThrDetector:
        rec = len(d.trace) == n_dec
    elif D is h1.SsfDetector:
        rec = len(d.t1_trace) > 0 and d.t1_trace[0][0] == 0 and len(d.ssf.v) == n_dec
    else:
        idx = np.concatenate([np.arange(m0, m0 + len(p)) for m0, p, _ in d.trace])
        rec = idx[0] == 0 and np.array_equal(idx, np.arange(len(idx))) and len(idx) == n_dec - d.lag
    check(f"{D.name}: recording its trace leaves every beat as it was, and the trace covers the run",
          same and rec, f"same {same} recorded {rec}")


# ── the library's HR1, literal per-sample port of _hr1_update (v0.121) ──
def lib_hr1_literal(x, fs):
    a_dc = math.exp(-1.0 / (h1.LIB_DC_TAU_S * fs))
    a_max = math.exp(-1.0 / (h1.LIB_MAX_DECAY_TAU_S * fs))
    L = min(int(round(fs / 10.0)), h1.LIB_MA_MAX_LEN)
    refr = int(h1.LIB_REFRACTORY_S * fs)
    dc = rmax = ma_sum = 0.0
    buf = [0.0] * L
    ma_i = idx = last = cnt = 0
    above = False
    iv = [0] * 5
    hr = np.full(len(x), np.nan); sqi = np.zeros(len(x))
    for k, ir in enumerate(x.tolist()):
        idx += 1
        dc = a_dc * dc + (1.0 - a_dc) * ir
        raw = -(ir - dc)
        ma_sum -= buf[ma_i]; buf[ma_i] = raw; ma_sum += raw; ma_i = (ma_i + 1) % L
        v = ma_sum / L
        rmax = max(rmax * a_max, v)
        thr = h1.LIB_THRESHOLD_FRAC * rmax
        if v > thr and not above:
            above = True
            el = idx - last
            if last > 0 and el > refr:
                iv = [el] + iv[:4]
                cnt = min(cnt + 1, 5)
            last = idx
        elif v <= thr:
            above = False
        if cnt < 5:
            continue
        avg = sum(iv) / 5.0
        h = fs * 60.0 / avg
        if 30.0 <= h <= 260.0:
            cv = math.sqrt(sum((i - avg) ** 2 for i in iv) / 5.0) / avg
            hr[k], sqi[k] = h, min(1.0, max(0.0, 1.0 - cv / 0.15))
    return hr, sqi


for bpm, notch, seed in ((90, 0.9, 5), (160, 0.3, 6), (45, 1.0, 7)):
    x, _ = h1.synth_ppg(FS, 40, bpm=bpm, notch=notch, noise=0.04, seed=seed)
    rows = h1.output_rows(len(x), FS)
    beats = h1.detect(x, FS, h1.LibFrontEnd(FS), h1.ThrDetector(FS, interpolate=False))
    hb_, qb, _ = h1.apply_rule(beats, FS, h1.RuleR0(), rows)
    hl, ql = lib_hr1_literal(x, FS)
    hl, ql = hl[rows], ql[rows]
    same = (np.array_equal(np.isfinite(hb_), np.isfinite(hl))
            and np.allclose(hb_[np.isfinite(hl)], hl[np.isfinite(hl)], rtol=1e-9)
            and np.allclose(qb[np.isfinite(hl)], ql[np.isfinite(hl)], atol=1e-9))
    check(f"bench = literal _hr1_update at {bpm} bpm, notch {notch} (refractory quirk included)", same)

# ── each detector on clean synthetic pulses (papers' values) ──
DESIGN = {"HR1_THR": (60, 240), "HR1_TERMA": (60, 240), "HR1_SSF": (60, 170), "HR1_MSPTD": (60, 240)}
for D in h1.DETECTORS:
    worst = 1.0
    for bpm in (60, 90, 120, 150, 170, 200, 240):
        if not DESIGN[D.name][0] <= bpm <= DESIGN[D.name][1]:
            continue
        rr = 60.0 / bpm * (1.0 + 0.02 * np.random.default_rng(bpm).standard_normal(int(bpm) + 5))
        x, pk = h1.synth_ppg(FS, 60, rr_s=list(rr), noise=0.01, seed=bpm)
        b = h1.detect(x, FS, h1.FrontEnd(FS), D(100.0))
        lo, hi = 12 * FS, 50 * FS
        tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], b[(b[:, 0] > lo) & (b[:, 0] < hi), 0],
                                       tol=0.15 * FS, max_lag=0.3 * 60 / bpm * FS)
        worst = min(worst, 2 * tp / max(2 * tp + fp + fn, 1))
    rng = DESIGN[D.name]
    check(f"{D.name} F1 >= 0.98 on clean pulses {rng[0]}-{rng[1]} bpm, RR varying 2 %", worst >= 0.98,
          f"worst {worst:.3f}")

x, pk = h1.synth_ppg(FS, 60, bpm=170, noise=0.01, seed=170)
b = h1.detect(x, FS, h1.FrontEnd(FS), h1.MsptdDetector(100.0))
lo, hi = 12 * FS, 50 * FS
tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], b[(b[:, 0] > lo) & (b[:, 0] < hi), 0], tol=0.15 * FS,
                               max_lag=0.1 * FS)
print(f"INFO HR1_MSPTD on an exactly periodic 170 bpm pulse: {tp} right, {fp} extra, {fn} missed "
      "(lambda = the scale with the most maxima lands on 1.5 P instead of P / 2, where the "
      "comparison at lag P is decided by noise; as published)")

x, pk = h1.synth_ppg(FS, 60, bpm=240, noise=0.01, seed=240)
b = h1.detect(x, FS, h1.FrontEnd(FS), h1.SsfDetector(100.0))
lo, hi = 12 * FS, 50 * FS
tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], b[(b[:, 0] > lo) & (b[:, 0] < hi), 0], tol=0.15 * FS,
                               max_lag=0.075 * FS)
check("HR1_SSF's 0.34 s eye-closing loses beats at 240 bpm, as published", fn > 0.2 * (tp + fn),
      f"tp {tp} fn {fn}")
for D in h1.DETECTORS:
    x, pk = h1.synth_ppg(FS, 90, bpm=30, noise=0.01, seed=30)
    b = h1.detect(x, FS, h1.FrontEnd(FS), D(100.0))
    lo, hi = 12 * FS, 80 * FS
    tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], b[(b[:, 0] > lo) & (b[:, 0] < hi), 0],
                                   tol=0.15 * FS, max_lag=0.4 * FS)
    print(f"INFO {D.name} at 30 bpm, papers' values: {tp} right, {fp} extra, {fn} missed")

# ── rules ──
r0 = h1.RuleR0()
for t, rr in enumerate([0.5] * 5):
    r0.on_beat(rr, t)
hr, q, v = r0.state(5.0)
check("R0: five RR of 0.5 s -> 120 bpm, sqi 1, published", abs(hr - 120) < 1e-9 and q == 1.0 and v)
r0.on_beat(0.25, 6)
hr, q, v = r0.state(6.0)
cv = np.std([0.5, 0.5, 0.5, 0.5, 0.25]) / np.mean([0.5, 0.5, 0.5, 0.5, 0.25])
check("R0: one doubled beat -> mean of 5, sqi = 1 - CV / 0.15 clamped", abs(hr - 60 / 0.45) < 1e-9
      and abs(q - max(0.0, 1 - cv / 0.15)) < 1e-9 and v == (q > 0))

r1 = h1.RuleR1()
t = 0.0
for _ in range(6):
    t += 0.5; r1.on_beat(0.5, t)
t += 0.25; r1.on_beat(0.25, t)
hr, q, v = r1.state(t)
check("R1: a doubled beat is rejected, 120 bpm kept, quality 6/8", abs(hr - 120) < 1e-9 and v and abs(q - 6 / 8) < 1e-9)
for _ in range(2):
    t += 0.38; r1.on_beat(0.38, t)
check("R1: a rejected run that does not agree (the doubled beat + two 0.38 s) does not restart",
      r1.acc == [0.5] * 5)
t += 0.38; r1.on_beat(0.38, t)
hr, q, v = r1.state(t)
check("R1: three agreeing RR of 0.38 s, 24 % away, restart the buffer (real change of rate)",
      r1.acc == [0.38] * 3 and not v)
for _ in range(2):
    t += 0.38; r1.on_beat(0.38, t)
hr, q, v = r1.state(t)
check("R1: after the restart it publishes 157.9 bpm", v and abs(hr - 60 / 0.38) < 1e-9)
check("R1: invalid 3 s after the last accepted beat", not r1.state(t + 3.01)[2] and r1.state(t + 2.99)[2])

r2 = h1.RuleR2()
t = 0.0
for _ in range(5):
    t += 0.5; r2.on_beat(0.5, t, anchor_s=0.52)
t += 0.25; r2.on_beat(0.25, t, anchor_s=0.52)
t += 0.5; r2.on_beat(0.5, t, anchor_s=None)
hr, q, v = r2.state(t)
check("R2: RR within 15 % of HR3_SAC's period accepted, a doubled beat and a beat without anchor rejected",
      v and abs(hr - 120) < 1e-9 and r2.hist[-2:] == [0, 0])

# ── beat matcher ──
ref = np.arange(10) * 50.0
tp, fp, fn, lag = h1.match_beats(ref, np.concatenate([ref[1:] + 7.0, [1000.0]]), tol=5.0, max_lag=20.0)
check("match_beats: constant lag found, one missed and one extra counted", tp == 9 and fp == 1 and fn == 1
      and abs(lag - 7.0) <= 1.25)

# ── part 2 options: RR-proportional refractory / eye-closing, R1's gates ──
rr = 60.0 / 240 * (1.0 + 0.02 * np.random.default_rng(7).standard_normal(250))
x, pk = h1.synth_ppg(FS, 60, rr_s=list(rr), noise=0.02, seed=7)
for name, mk in (("HR1_SSF eye-closing 0.5 x RR", lambda: h1.SsfDetector(100.0, eye_closing_rr=0.5)),
                 ("HR1_THR refractory 0.5 x RR", lambda: h1.ThrDetector(100.0, refractory_rr=0.5))):
    a = h1.detect(x, FS, h1.FrontEnd(FS), mk())
    b = h1.detect(x, FS, h1.FrontEnd(FS), mk(), block=10)
    check(f"{name}: the same beats fed whole or in 20 ms blocks",
          a.shape == b.shape and np.allclose(a, b, atol=1e-6, equal_nan=True))
    lo, hi = 12 * FS, 50 * FS
    tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], a[(a[:, 0] > lo) & (a[:, 0] < hi), 0],
                                   tol=0.15 * FS, max_lag=0.075 * FS)
    check(f"{name}: no beat lost at 240 bpm", fn == 0 and fp == 0, f"tp {tp} fp {fp} fn {fn}")
x, pk = h1.synth_ppg(FS, 90, bpm=30, noise=0.01, seed=30)
a = h1.detect(x, FS, h1.FrontEnd(FS), h1.SsfDetector(100.0, eye_closing_rr=0.5))
lo, hi = 12 * FS, 80 * FS
tp, fp, fn, _ = h1.match_beats(pk[(pk > lo) & (pk < hi)], a[(a[:, 0] > lo) & (a[:, 0] < hi), 0], tol=0.15 * FS,
                               max_lag=0.4 * FS)
check("HR1_SSF eye-closing 0.5 x RR does not count the dicrotic wave at 30 bpm", fp <= 1, f"extra {fp}")
g = h1.RuleR1(q_min=6 / 8)
t = 0.0
for rr_ in [0.5] * 6 + [0.25, 0.25, 0.5]:
    t += rr_; g.on_beat(rr_, t)
check("R1 with q >= 6/8: two rejected of the last 8 still publishes, a third would not",
      g.state(t)[2] and abs(g.state(t)[1] - 6 / 8) < 1e-9)
g.on_beat(0.25, t + 0.25)
check("R1 with q >= 6/8: three rejected of the last 8 withholds", not g.state(t + 0.25)[2])
c, plain = h1.RuleR1(cv_max=0.15), h1.RuleR1()
t = 0.0
for rr_ in [0.5, 0.7, 0.3, 0.5, 0.5]:         # the first three are accepted before R1 has a median: CV 25 %
    t += rr_; c.on_beat(rr_, t); plain.on_beat(rr_, t)
check("R1 with the CV gate withholds 5 accepted RR whose CV is 25 %; plain R1 publishes them",
      len(c.acc) == 5 and not c.state(t)[2] and plain.state(t)[2])

# ── ECG reference and Charlton's beat scores (F2) ──
FE = 125.0
rng = np.random.default_rng(11)
rr = 0.4 * (1.0 + 0.03 * rng.standard_normal(170))
r_true = 0.5 + np.concatenate([[0.0], np.cumsum(rr)])
r_true = r_true[r_true < 60.0]
te = np.arange(int(60 * FE)) / FE
ecg = 0.02 * rng.standard_normal(len(te)) + 0.2 * np.sin(2 * np.pi * 0.3 * te)
for r in r_true:
    ecg += np.exp(-0.5 * ((te - r) / 0.008) ** 2) - 0.3 * np.exp(-0.5 * ((te - r - 0.02) / 0.008) ** 2)
    ecg += 0.3 * np.exp(-0.5 * ((te - r - 0.2) / 0.04) ** 2)          # T wave
for name, fn in (("A (Pan-Tompkins)", h1.qrs_pan_tompkins), ("B (envelope)", h1.qrs_envelope)):
    q = fn(ecg, FE) / FE
    tp, fp, fnn, lag = h1.match_beats(r_true, q, tol=0.03)
    check(f"QRS detector {name} finds every R wave within 30 ms on a synthetic ECG at ~150 bpm with T waves",
          fp == 0 and fnn == 0, f"tp {tp} fp {fp} fn {fnn}")
ppg_flat = np.sin(2 * np.pi * 2.5 * te)
ppg_flat[int(25 * FE):int(25.5 * FE)] = 1.0                            # clipped 0.5 s in the 2nd window
ref, kept, nw = h1.ecg_reference(ecg, ppg_flat, FE)
check("ecg_reference keeps the clean windows and drops the one with a flat PPG", nw == 3 and kept == [(0.0, 20.0), (40.0, 60.0)],
      f"{kept}")
det = np.delete(ref, [10, 20]) + 0.25
det = np.sort(np.concatenate([det, [ref[30] + 0.25 + 0.2]]))
s = h1.beat_scores(ref, det, [(0.0, 60.0)])
check("beat_scores: lag 0.25 s found (one 20 ms step), two missed, one extra", abs(s["lag_s"] - 0.25) <= 0.02
      and s["n_correct"] == len(ref) - 2 and s["n_det"] == len(ref) - 1, f"{s['lag_s']} {s['n_correct']} {s['n_det']}")
reg = np.arange(0, 30, 0.4)
hrr = h1.ref_hr_at(reg, [(0.0, 20.0), (20.0, 40.0)], np.array([1.0, 5.0, 25.0]))
check("ref_hr_at: 150 bpm from 5 RR inside kept windows, nan before 5 RR", np.isnan(hrr[0])
      and abs(hrr[1] - 150) < 1e-6 and abs(hrr[2] - 150) < 1e-6)

print(f"\n{sum(ok)}/{len(ok)} checks passed")
sys.exit(0 if all(ok) else 1)
