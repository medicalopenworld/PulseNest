"""Offline checks for pulsenest/hr_bench.py -- the bench every pulse-rate study is scored on.

A bench that scores wrong does not raise: it prints a well-formed table of the wrong percentages.
So the pieces that decide a score are checked here on signals whose answer is known, with no
capture and no board: the three methods of the spectrum family on a synthetic harmonic comb, the
error classes, and the pairing of a window with the monitor's reading.

    python test_pulsenest/hr_bench_test.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest import hr_bench as hb  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  the common bench of the heartbeat resolvers")
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


RATE = 50.0


def comb_spectrum(bpm, amps=(1.0, 0.5, 0.25, 0.12, 0.06), noise=0.02, seed=1):
    """One HR3 window (power spectrum, 1 x N/2+1) of a pulse with the given harmonic amplitudes."""
    t = np.arange(hb.BUF_LEN) / RATE
    f0 = bpm / 60.0
    x = sum(a * np.sin(2 * np.pi * n * f0 * t + 0.3 * n) for n, a in enumerate(amps, start=1))
    x = x + noise * np.random.default_rng(seed).standard_normal(hb.BUF_LEN)
    seg = (x - x.mean()) * np.hanning(hb.BUF_LEN)
    return (np.abs(np.fft.rfft(seg)) ** 2)[None, :]


def rel_err(a, b):
    return abs(float(a) / b - 1.0)


# ── the three methods on a clean comb, across the neonatal range ──
rates = (90, 120, 150, 174, 200, 240)
bin_res, b_lo, b_hi = hb.band_bins(RATE)
worst = {"HPS": 0.0, "SAC": 0.0, "CEP40": 0.0, "CEPC6": 0.0}
purity_min, rho_min = 1.0, 1.0
for bpm in rates:
    P = comb_spectrum(bpm)
    hr_h, _ = hb.hps_estimate(P, *hb.hps(P, 3), RATE)
    hr_s, rho, C6, _ = hb.hr3_sac(P, RATE)
    A40, dq = hb.band_cepstrum(hb.log_floor(P, b_lo, b_hi, 40.0), bin_res)
    Ac6, _ = hb.band_cepstrum(C6, bin_res)
    worst["HPS"] = max(worst["HPS"], rel_err(hr_h[0], bpm))
    worst["SAC"] = max(worst["SAC"], rel_err(hr_s[0], bpm))
    worst["CEP40"] = max(worst["CEP40"], rel_err(hb.pick_quefrency(A40, dq)[0][0], bpm))
    worst["CEPC6"] = max(worst["CEPC6"], rel_err(hb.pick_quefrency(Ac6, dq)[0][0], bpm))
    purity_min = min(purity_min, float(hb.comb_purity(P, hr_s, RATE)[0]))
    rho_min = min(rho_min, float(rho[0]))
check("the harmonic product reads a clean comb within 1 % from 90 to 240 bpm", worst["HPS"] <= 0.01, worst["HPS"])
check("the spectral autocorrelation reads it within 1 %", worst["SAC"] <= 0.01, worst["SAC"])
check("the cepstrum on a 40 dB floor reads it within 1 %", worst["CEP40"] <= 0.01, worst["CEP40"])
check("the cepstrum of the local contrast reads it within 1 %", worst["CEPC6"] <= 0.01, worst["CEPC6"])
check("a clean comb has purity above 0.9 and rho above 0.8", purity_min > 0.9 and rho_min > 0.8, f"{purity_min} {rho_min}")

# ── a spectrum with no comb gives nothing to trust ──
noise = (np.abs(np.fft.rfft(np.random.default_rng(7).standard_normal(hb.BUF_LEN) * np.hanning(hb.BUF_LEN))) ** 2)[None, :]
hr_n, rho_n, _, _ = hb.hr3_sac(noise, RATE)
pur_n = float(hb.comb_purity(noise, hr_n, RATE)[0])
check("white noise has a low comb purity, whatever rate the autocorrelation picks", pur_n < 0.3, pur_n)

# ── the quefrency axis ──
A, dq = hb.band_cepstrum(np.ones((1, b_hi - b_lo + 1)), bin_res)
check("the quefrency step is 1 / (nfft * bin resolution)", abs(dq - 1.0 / (hb.CEP_NFFT * bin_res)) < 1e-15, dq)
check("the cepstrum is cut just above the period of the lowest rate searched",
      (A.shape[1] - 2) * dq <= 60.0 / (hb.HR_MIN - hb.HR_GUARD) < (A.shape[1] - 1) * dq, A.shape)

# ── error classes ──
ref = np.full(8, 150.0)
hr = np.array([150.0, 164.0, 300.0, 75.0, 50.0, 450.0, 120.0, np.nan])
cl = [hb.CLASSES[i] for i in hb.error_class(hr, ref)]
check("each value falls in its class", cl == ["ok", "ok", "x2", "x1/2", "x1/3", "x3", "other", "none"], cl)
check("no reference gives no class", list(hb.error_class(np.array([150.0, np.nan]), np.array([np.nan, np.nan]))) == [-1, -1])
check("the older three-way classes agree on ok / harmonic / other",
      list(hb.harmonic_class(hr, ref)) == [0, 0, 1, 1, 1, 1, 2, -1], list(hb.harmonic_class(hr, ref)))

# ── a window and the monitor's reading ──
read_t = np.array([0.0, 10.0, 20.0, 30.0, 60.0]) * 1e6
read_v = np.array([150.0, 152.0, 200.0, 198.0, 160.0])
t_end = np.array([1.0, 6.0, 14.0, 26.0, 37.0, 45.0, 58.0]) * 1e6
r, stable = hb.monitor_reference(read_t, read_v, t_end)
check("a window takes the reading nearest to its end",
      list(r[:4]) == [150.0, 152.0, 152.0, 198.0], list(r))
check("a window more than 6 s from any reading has no reference", np.isnan(r[4]) and np.isnan(r[5]) and r[6] == 160.0, list(r))
check("a reading next to a jump of more than 10 % is not stable",
      list(stable) == [True, False, False, True, False, False, True], list(stable))
check("no readings, no reference", not np.isfinite(hb.monitor_reference(np.zeros(0), np.zeros(0), t_end)[0]).any())

# ── a window's result holds until the next one, and only while the probe stays applied ──
ps = np.array([2, 2, 2, 2, 1, 2, 2, 2, 2, 2])
m = hb.hold_mask(10, ps, np.array([1, 3, 7]), np.array([True, True, False]))
check("the hold stops at the first sample that is not applied and skips invalid windows",
      list(m.astype(int)) == [0, 1, 1, 1, 0, 0, 0, 0, 0, 0], list(m.astype(int)))

print(f"\n{sum(ok)}/{len(ok)} checks passed -- {'OK' if all(ok) else 'FAILURES'}")
sys.exit(0 if all(ok) else 1)
