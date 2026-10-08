# RF tap reference — the real TIA feedback resistors of every board

Reference data for the seven TIA gain taps of the AFE4490 (10K … 1M) on every IncuNest board,
measured under constant illumination: the LEDs of the probe covered, the photodiode seeing ambient
light only, so the four phases (LED1, ALED1, LED2, ALED2) carry the same current and
`V_TIA = I_amb · RF_nominal · (1 + ε_tap) + V_off`. Produced by `tools/rf_tap_bench.py` (the ladder
10K → 1M → 10K, every board in parallel, HGAC off) and `tools/rf_tap_analyze.py` (the fit and these
files). Raw rows live in `captures/rf_taps/` (not versioned). First run: 2026-10-08, three V18.

## Files

| File | One row per | Content |
|---|---|---|
| `rf_tap_levels.csv` | board × pass × tap × phase | steady `V_TIA` (mean, SD over the rung minus its first second), implied photodiode current, saturation flag, samples frozen by the library's switched-RC settling, settle time after the freeze, first free sample's deviation in % of the step |
| `rf_tap_tolerance.csv` | board × tap | `eps_pct` = real/nominal − 1 of that tap, anchored so the mean over the measured taps is 0 (the absolute value is not observable, only the tap-to-tap pattern); `eps_se_pct` = half the disagreement between the up and the down pass; fitted `V_off` per phase, `I_amb` and its drift |
| `rf_tap_steps.csv` | board × neighbouring tap pair | `ot_step_pct` = the level step of OT that a one-tap move produces, (1+ε_to)/(1+ε_from) − 1 |

A re-run of the same date and board replaces its rows; other dates and boards accumulate.

## Model and why the taps cannot be compared by plain ratios

The additive offset `V_off` of the analog chain (TIA + second stage + ADC) is a few millivolts and
differs per chip: +1.0 mV (82:5C), −5.0 mV (87:A4), −6.6 mV (88:50) on 2026-10-08, the same in
the four phases of a board to within 0.6 mV. At 10K the signal was 7–16 mV, so a ratio of raw
levels between 10K and 100K is off by 30–45 % — resistor tolerance has nothing to do with it. The
analysis therefore fits, jointly over both passes, `I_amb` with a linear drift in time (the
light), one `V_off` per phase and one `ε` per tap. Residual after the fit: 0.25–0.45 % RMS.

## What the 2026-10-08 run says

- **ε pattern, nearly the same on the three chips** (±0.3 %): 10K +0.2, 25K −0.4, 50K −0.3,
  100K −0.7, 250K +1.1, 500K +0.05 %. The datasheet allows ±7 % per resistor; what we see is a
  systematic pattern of the design well inside it, not random per-chip scatter.
- **One-tap steps** (what an HGAC move does to OT): 100K→250K +1.4…+2.2 %, 250K→500K −0.9…−1.2 %,
  the rest below 0.7 %.
- **1M is not measurable in this light** (1.3–1.5 µA × 1 MΩ > the 1.2 V rail): less light next time.
- **Settling after the library's freeze** (7–8 samples, datasheet t5): the first free sample is
  within 2–3.5 % of the step, median settle time 0 s; a few rungs at 500K show a ≤ 0.4 % tail
  within the first second. What happens inside the freeze is not observable from `$M4`.
- **Light drift** −1.6 %/min on the three boards (the room), handled by the model.
- **Phase offsets**: ALED1/ALED2 sit 0.5 mV below LED1/LED2 on 82:5C, 0.1 mV on the others. That
  difference does not cancel in LED − ALED: at 10K it is 50 nA of apparent photocurrent.
- **Caveat, LED2 phase**: in this run `tiagain1` was sent to the three boards before `tiagain2`,
  so the LED2/ALED2 step landed 0.45 s after LED1's; the steady levels are unaffected (first
  second skipped) and the bench now sends both colours back to back.
- **Open discrepancy** with the 2026-10-08 simulator run (MS100, OT with LEDs on, V_TIA ≈ 0.4 V):
  there the 50K ↔ 25K step on OT was ≈ 1 %, here ε(25K) − ε(50K) ≈ 0.1 %. A level-dependent
  effect (0.4 V vs 0.07 V) or the pulse averaging of that run; to be settled with more light.
