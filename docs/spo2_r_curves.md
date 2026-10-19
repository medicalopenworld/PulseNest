# R-curve register — every SpO2 = a − b·R fitted or used in PulseNest

One row per pair of coefficients. A curve is valid only for the R method it was fitted with
(`incunest_afe4490_spec.md` §5.1); the library carries `spo2_r_curve_id` + `spo2_r_curve_r_method_id` and
flags a mismatch. Label scheme `R-CURVE-<probe>-<source>-<date>` (2026-10-02); **the date is the date of the
fit** (2026-10-20 rule), so one label is one (a, b). The library's own spec keeps only the curves it ships or
shipped and points here. Data folders are under `captures/sessions/` (not in git).

None of these is an ISO 80601-2-61 calibration (Annex DD: controlled desaturation against CO-oximetry). A
simulator never validates accuracy (EE.4).

| Label | a | b | R method | Probe (lot) | Site | Reference | Data, n | Range | Fit | State |
|---|---|---|---|---|---|---|---|---|---|---|
| `R-CURVE-U401D-MS100-20260323` | 114.9208 | 30.5547 | R-METHOD-0 | UpnMed U401-D(01AS-F), IR 905 nm | simulator | CONTEC MS100, "R-Curve Nellcor", 100 bpm | conversation log session 26 (2026-03-23) | sim 70-100 | OLS | **shipped** as default until lib v0.99; superseded. R-METHOD-0 (RMS-based) biases R up and flattens the slope — the 30.55 is the method, not the probe (see 2026-10-19 row) |
| `R-CURVE-STS0163-HOSPNAV-20260923` (first use) | 115.17 | 21.54 | R-METHOD-1 | Medle ST-S0163 (-25 or -26, not recorded) | neonatal foot | Mindray N17 via VideoNest OCR (averaging not recorded) | SUBJ08 + SUBJ09, 3471 stationary 8 s windows; `SUBJ08/Analysis/pooled_fit.py`, `findings.md` | 87-100 | OLS by bands, rms 1.53 | **discarded** 2026-10-02: slope is mostly R-METHOD-1 noise (regression dilution + out-of-band noise). Never applied. Label later reused — see next row |
| `R-CURVE-STS0163-HOSPNAV-20260923` (**current**, fitted 2026-10-04) | 123.98 | 39.13 | R-METHOD-2 | Medle ST-S0163 (-25 or -26, not recorded) | neonatal foot | Mindray N17 via VideoNest OCR (averaging not recorded) | SUBJ08 + SUBJ09 replayed with lib v0.100, 3455 stationary 8 s windows; `SUBJ08/Analysis/fit_method2.py` | 85-100 (31 windows below 85 read −3.4) | OLS, ρ −0.80, scatter 1.65, median \|res\| 0.91, LOSO 0.95-1.38 | **shipped** as default since lib v0.100. Validated on SUBJ11 (30 wk, 1.5 kg) 2026-10-16: bias −0.2, sd 1.2. Pending: relabel to the fit date (`…-20261004`) so the label is unique |
| SUBJ08 only (diagnostic) | 129.2 | 46.7 | R-METHOD-2 | Medle ST-S0163 | neonatal foot | Mindray N17 | SUBJ08 share of the row above | 85-100 | OLS | diagnostic: per-subject spread of the pooled fit; not a curve to apply |
| SUBJ09 only (diagnostic) | 118.8 | 32.1 | R-METHOD-2 | Medle ST-S0163 | neonatal foot | Mindray N17 | SUBJ09 share of the row above | 85-100 | OLS | diagnostic, as above |
| `R-CURVE-STS0163-ADULTFINGER-20261020` (diagnostic) | 111.94 | 25.15 | R-METHOD-2 | Medle ST-S0163-26 lot 260521002, 3 units | adult finger (SUBJ01, index/middle/ring) | unbranded home fingertip oximeter via VideoNest OCR | breath-hold 2026-10-18, 1205 stationary pairs; `SUBJ01/SUBJ01_BIAS_ANALYSIS/pairs.csv` (OLS added 2026-10-20, no lag compensation) | **93-99 only** | OLS, rms 0.67 | diagnostic: range too narrow for a slope (R 0.54-0.77). What matters is the bias: current curve +3.0 (Arms 3.2), MS100/U401-D curve −0.5 (Arms 1.0) after 4 s lag compensation. Reference is itself a Nellcor-type adult curve |
| `R-CURVE-STS0163-MS100-20261019` | 121.06 | 39.11 | R-METHOD-2 | Medle ST-S0163-26 lot 260521002 | simulator | CONTEC MS100, "R-Curve Nellcor", Pulse Amp 3 %, TLC 3500, read by VideoNest OCR | SUBJ90 sweep 2026-10-19, 18 plateaus at 75/140/160 bpm; `SUBJ90/Analysis/ms100_sweep.py`, `findings.md` | sim 72-100 | OLS, rms 1.0 (table concave below 80 %) | bench reference only: same slope as the current curve, intercept −2.9. R independent of heart rate (±0.003); chain noise sd(R) 0.002-0.008 (< 0.3 pt) |

## What the register says so far

- Slope: every R-METHOD-2 fit with a usable range gives 39.1 ± 0 (neonatal foot vs Mindray, simulator vs its
  Nellcor table). The flatter slopes (30.55, 21.54, 25.15) are R-METHOD-0/1 noise or a range too narrow.
- Intercept: the two Nellcor-convention references (MS100 table, home oximeter on an adult finger) agree with
  each other and sit ~3 pt below the Mindray-based neonatal fit. Open whether that is the Mindray or the
  tissue — see `conversation_log.md` 2026-10-19 (5-minute experiment: Alex's finger on the N17 adult sensor and
  a home oximeter at once).
- Not recorded in the 2026-09-23 campaign and needed in the next: probe suffix/lot per baby, the monitor's
  averaging window, the monitor's probe site (pre/post-ductal), arterial blood gases when taken clinically.

## Columns

Label · a, b (SpO2 = a − b·R) · R method · probe model, suffix and lot · application site · reference (make,
model, how it was read, averaging) · data folder, script, number of pairs · reference range covered · fit
method and residuals · state (shipped / discarded / diagnostic / bench) with the decision date.
