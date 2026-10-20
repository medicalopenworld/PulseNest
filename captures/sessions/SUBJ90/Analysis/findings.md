# SUBJ90 — MS100 SpO2 sweep, 2026-10-19 22:14-22:26

Session `SUBJ90_ERRENIEGA_20261019_221421` (board 825C, fw 0.24 / lib 0.105, Medle ST-S0163-26, LEDs 49.8 mA,
HGAC off, R-METHOD-2, curve `R-CURVE-STS0163-HOSPNAV-20260923` = 123.98 − 39.13·R). Simulator: Nellcor R-curve,
Pulse Amp 3 %, TLC 3500, source UUT. Setpoints read by VideoNest (J6plusACM, OCR conf ≥ 0.9); keyboard
`REF_SPO2` events lagged the screen by 6-27 s and were NOT used (see §5). Script `ms100_sweep.py`, table
`plateaus.csv`, figure `ms100_sweep.png`; spectra in `../Spectra/`.

Plateau = OCR run ≥ 5 s, first 10 s dropped (6 s SpO2 window + 2 s EMA + OCR latency), medians of the rest.

## 1. R does not depend on heart rate

| Setpoint | R @ 75 bpm | R @ 140 bpm | R @ 160 bpm |
|---|---|---|---|
| 100 | 0.528 (51 % invalid) | 0.477 (99 % invalid) | — |
| 96 | 0.635 | 0.636 | — |
| 92 | 0.764 | 0.763 | 0.764 |
| 88 | 0.877 | 0.880 | — |
| 84 | 0.964 | 0.965 | 0.967 |
| 80 | 1.049 | 1.052 | — |
| 76 | 1.136 | 1.137 | 1.137 |
| 72 | 1.202 | — | — |

Same R to ±0.003 (≈ 0.1 pt) at 75, 140 and 160 bpm, including 160 bpm where the 2nd harmonic (5.3 Hz) is
outside the 0.5-5 Hz HR2 band. HR3 locked at 74.9 / 140.0 / 160.1 (valid 98 % of the columns; clean harmonic
comb in both channels, see spectrogram). Descending (75 bpm) and ascending (140 bpm) passes agree → no
hysteresis, no drift over 12 min.

## 2. Chain noise

Within a plateau R has sd 0.002-0.008 (0.1-0.3 pt of SpO2); r (R_CORR) 0.987-0.997; PI 4.3-4.5 %. This is
the floor the AFE + R-METHOD-2 chain adds to a curve: < 0.3 pt. Everything above that in a clinical capture is
the subject or the reference.

## 3. The lib's curve against the MS100 Nellcor table

Linear fit of setpoint on R, all 18 plateaus: **setpoint = 121.06 − 39.11·R** (rms 1.0). The lib's neonatal
curve is 123.98 − 39.13·R: **identical slope (39.11 vs 39.13), intercept +2.9 pt**. Bias of the lib's SpO2
against the setpoint: +1.5…+2.3 pt at 84-92, +2.8…+3.5 at 76-80, +5.0 at 72 (the MS100 table is concave:
ΔR per 4 pt shrinks from 0.13 at 96→92 to 0.07 at 76→72, so a straight line overshoots at the low end).

What this is and is not:
- The MS100 is optical (it senses our LED pulses and re-emits modulated light), so R per setpoint is the
  simulator's Nellcor table, independent of our probe's λ to first order. The March curve on the same
  simulator (`R-CURVE-U401D-MS100-20260323`, 114.92 − 30.55·R) differs mainly by R-METHOD-0 (RMS-based, biased
  flat), not by the U401-D probe — consistent with the 2026-10-02 finding (R-METHOD-1 flattens 37.6 → 21.5).
- The +2.9 pt is "Mindray N17 on neonatal foot" versus "Nellcor convention as the MS100 encodes it". The adult
  finger of 2026-10-18 (home oximeter, Nellcor-type curve) gave the same picture: the neonatal curve +3.0,
  the MS100 curve −0.5. Two Nellcor-convention references agree with each other and sit 3 pt below the
  Mindray-based fit. Whether that is the Mindray or the tissue is still the 5-minute experiment (Alex's
  finger on the N17 adult sensor and a home oximeter at once). ISO EE.4: none of this is accuracy.

## 4. SpO2 invalid at 100 %

At setpoint 100 the lib's SpO2 is invalid 51 % of the time at 75 bpm (R 0.528 → 103.3, at the edge of
`spo2_clamp_margin` 3) and 99 % at 140 bpm (R 0.477 → 105.3). R at 100 % is the only setpoint where the two
passes differ (0.528 vs 0.477): the red modulation is tiny there and R is relatively noisy. With the neonatal
curve, a healthy subject at 100 % would show "—" part of the time. Nellcor and Masimo clamp to 100. Design
question for the lib (not decided): widen the clamp margin, or clamp whenever r and PI are fine and the
excess is below a few points. Also note the 100 % plateaus had the highest R_sd (0.076, 0.085).

## 5. Protocol lessons

- The keyboard `REF_SPO2` lagged the simulator screen by 6-27 s: deliberate (Alex pressed RECORD ~10 s after
  each change, the way a pulse oximeter averages its last 6-10 s), but the simulator switches instantly, so
  keyboard-delimited plateaus straddled two setpoints: the ascending pass looked 5-7 pt off and HR seemed to
  matter — an artefact. **For a simulator the OCR is the time source; the keyboard value is at most a label.**
  Keep VideoNest on for every sweep.
- The session opened at 96 (simulator default) with 36 s before the first change: fine as the warm-up.
- 18 usable plateaus in 12 min; 20 s per step was comfortable (plateaus of 8-25 s after the 10 s skip).
- PI reads 4.3-4.5 % for Pulse Amp 3 % (ratio 1.47), constant across the sweep. Not (max − min)/max → 3.05 %
  as deduced on 2026-10-19 from the screen; the definition of Pulse Amp is still open. Quick test: Pulse Amp
  1 / 3 / 10 % at a fixed setpoint and read the lib's PI.
