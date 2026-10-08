# RF tap reference — the real TIA feedback resistors and the analog offset of every board

Reference data for the seven TIA gain taps of the AFE4490 (10K … 1M) on every IncuNest board,
measured under constant illumination: the LEDs of the probe covered, the photodiode seeing ambient
light only, so the four phases (LED1, ALED1, LED2, ALED2) carry the same current and
`V_TIA = I_amb(t) · RF_nominal · (1 + ε_tap) + V_off_phase`. Produced by `tools/rf_tap_bench.py`
(protocol A–G below, every board in parallel, HGAC off) and `tools/rf_tap_analyze.py` (fit,
tables, figures, report skeleton). **Report with conclusions: `rf_tap_report_<date>.md`.**

## Files

| File | One row per | Content |
|---|---|---|
| `raw/<date>_<MAC>.csv` | `$M4` sample (500 Hz) | `t_s` (board clock), `SmpCnt`, raw ADC codes and `V_TIA` of LED1/ALED1/LED2/ALED2, `RF1`, `RF2`, `DiagCode`, protocol phase — the data; everything else is derived from it |
| `raw/<date>_events.csv` | command / frame | every `$SET` sent, every `$CFG`/`$LCFG` received, with host time and the board's last sample counter |
| `rf_tap_levels.csv` | board × tap × phase (slow ladder) | steady `V_TIA` (mean, SD, SD of 50 ms means), implied photodiode current, saturation |
| `rf_tap_tolerance.csv` | board × tap | `eps_two_level_pct` (the one to use), `eps_pct` (single-level ridge, superseded), `eps_fast_*` (fast sweep), `V_off` per phase (both fits), `I_amb`, `eps_shift_per_mV_offset_pct` |
| `rf_tap_steps.csv` | board × phase × pair × protocol phase | one-tap OT step from the toggles (`ot_step_pct_mean ± sd`, n cycles) and the same from the ladder ε |
| `rf_tap_settling.csv` | board × phase × transition × protocol phase | frozen samples, samples to 1 % / 0.1 % of the step, remaining deviation at samples 0…30 (freeze ON and OFF) |
| `rf_tap_fast_sweep.csv` | board × tap | ε from the 80 ms rungs, mean ± SD over the repetitions, against the two-level ε |
| `fig/` | | ε per tap; settling transients with the freeze off |

A re-run of the same date and board replaces its rows in the derived tables; other dates and
boards accumulate. Raw files are versioned on purpose (≈ 22 MB per board per run).

## Protocol (`tools/rf_tap_bench.py`)

A precheck · B slow ladder 10K → 1M → 10K, 10 s per rung, a 100K reference rung between taps
(light drift) · C fast ladder, 100 ms per rung, 10× · D neighbouring pairs toggled 20× at 200 ms
(freeze on) · E the same with the library's settling freeze off (`afe_settle_freeze_enable`, lib
v0.104) plus 10K ↔ 1M · G restore. Both colours are switched back to back; boards are selected by
MAC.

## Two lessons that shape the analysis

1. **The additive offset dominates the low taps** (a few mV against 1–10 mV of signal at 10K), so
   tap levels cannot be compared by plain ratios.
2. **One light level cannot separate the offset from the tap pattern**: ε'_tap = ε_tap − δ/(I·RF) + c
   fits exactly as well for any δ. The analysis needs two light levels (`--extra-run` joins a
   second run) or a dark reading. The single-level `eps_pct` column is a ridge (smallest pattern)
   and is kept only for traceability.

## Runs

- **2026-10-08** — three V18 (82:5C, 87:A4, 88:50), fw 0.22 / lib 0.104, two light levels (10:08
  run at I_amb ≈ 1.3–1.5 µA, bench v1 in `captures/rf_taps/`, not versioned; 10:50 run at
  0.7–0.8 µA, this directory). Report: `rf_tap_report_2026-10-08.md`.
