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

## Published curves, for comparison (search 2026-10-20)

No hospital manufacturer publishes its curve: Nellcor stores a piece-wise rational function (constants c1-c4 per
RCAL wavelength bin, linear c5 − c6·R below 70 %; US 6,801,797 and family, no numbers), Masimo, Philips, Mindray
and Nihon Kohden keep lookup tables in ROM or in the sensor memory. What is public comes from chip vendors'
application notes, reference designs, patents and a few papers. **Coefficients are not comparable across rows**:
R depends on the wavelengths, the geometry (path-length ratio) and the R estimator (RMS, peak-to-baseline,
derivative regression, log ratio). Compare on the anchor columns instead.

| Curve | Form | R estimator / sensor / population | SpO2 @ R=1 | R @ 100 / 85 / 70 % | Source |
|---|---|---|---|---|---|
| **ours** `R-CURVE-STS0163-HOSPNAV-20260923` | 123.98 − 39.13·R | R-METHOD-2 (band-pass + derivative regression); Medle 665/905 nm, neonatal foot; Mindray N17 reference | 84.8 | 0.61 / 1.00 / 1.38 | this register |
| **ours** `R-CURVE-STS0163-MS100-20261019` | 121.06 − 39.11·R | R-METHOD-2; MS100 "Nellcor" table | 82.0 | 0.54 / 0.92 / 1.31 | this register |
| "Classic" linear, TI TIDA-00301 | 110 − 25·R | AC/DC ratio of ratios; 660/940 nm; attribution to a measured study not found — a textbook/reference-design convention | 85.0 | 0.40 / 1.00 / 1.60 | Blaney 2024 eq. 26; widely copied (TI forums, Tishreen 2022) |
| Blaney, Sassaroli & Fantini 2024, modified Beer-Lambert | SaO2 ≈ (A + B·R)/(C + D·R); linearised 108 − 23·R | theory with Prahl extinction coefficients, 660/940 nm, path-length ratio ℓIR/ℓR = 0.65; the classic line corresponds to 0.65-0.70 | 85.0 | 0.35 / 1.00 / 1.65 | J Biomed Opt 29 S33313 (PMC12238718) |
| Beer-Lambert, Prahl 660/900 nm, ℓIR/ℓR = 1 (computed here) | rational | pure theory, no scattering | — | 0.27 / 0.67 / 1.12 | Prahl tables |
| idem with ℓIR/ℓR = 0.65 | rational | | — | 0.41 / 1.03 / 1.72 | |
| Stubán & Masatsugu 2008 | 113.8 − 24.87·R | beat-by-beat AC/DC, reflectance finger; 9 adults, 511 pairs, 86-100 %, hypoxic air 14 % O2; reference Koike BePUL2 finger oximeter (±2 %) | 88.9 | 0.56 / 1.16 / 1.76 | Period Polytech EE 52 (pp.bme.hu 859) |
| Life Meter Srl, US 12,290,358 (2020) | 112.9 − 39.4·R | reflectance, underside of the wrist, ~600/900 nm; 4 subjects; reference Nonin 2500A on a finger | 73.5 | 0.33 / 0.71 / 1.09 | Google Patents |
| Maxim UG 6409 (MAX32664) | 104 − 17·R | Maxim default, reflectance sensor hub | 87.0 | 0.24 / 1.12 / 2.00 | mizutanilab/pulse-oximeter README (second-hand) |
| Maxim AN 6845 "Guidelines for SpO2 measurement" | 112.69 − 34.66·R + 1.596·R² | default a, b, c of the sensor-hub algorithm; the note says re-calibrate per enclosure (ISO 80601-2-61 hypoxia study) | 79.6 | 0.37 / 0.83 / 1.31 | same README; analog.com PDF not reachable today |
| Maxim MAXREFDES117 (2016), copied by SparkFun MAX3010x | 94.845 + 30.354·R − 45.06·R² (lookup table) | AC = peak minus interpolated valley baseline, per beat, median of 5; red/IR, reflectance | 80.1 | never reaches 100 (max 99.96 at R 0.34) / 0.91 / 1.15 | spo2_algorithm.cpp header |
| Reynolds et al. 1991 (BJA 67:638), linearised by a third party | 114.9 − 33.4·R | 660/950 nm transmission model used for the LED temperature study | 81.5 | 0.45 / 0.89 / 1.34 | second-hand; original figure not checked |
| Nitzan 2014 review (Med Devices 7:231) | SaO2 = (k1 − k2·R)/(k3 − k4·R) | generic form, "best-fit for the specific pulse oximeter"; no numbers | — | — | docs/mder-7-231.pdf |
| Nitzan / Elron 2023, 17 cyanotic newborns 51-85 % | SpO2 − SaO2 = a·SaO2 + b (Nellcor 660/900 and two-IR 761/820) | numbers only in figures; overestimation grows as SaO2 falls (path-length ratio) | — | — | Sensors 23:1434 (PMC9921559) |
| Nellcor (Covidien) | piece-wise rational + linear < 70 % | c1…c9 per RCAL bin, not published | — | — | US 6,801,797 / 8,078,246 |
| Masimo, Philips (FAST), Mindray, Nihon Kohden, GE TruSignal | lookup tables | unpublished; Masimo patents quote 660/905 nm | — | — | US 7,428,432 family |

What the comparison says:
- **Anchor R = 1 ↔ 85 %** holds for the classic line, the Beer-Lambert model with ℓIR/ℓR ≈ 0.65 and **our neonatal
  curve (84.8)**; the MS100 table gives 82. Our R scale is right where theory and convention put it at 85 %.
- **Our slope (39) is steeper than the classic 25 because our R at 100 % is higher (0.54-0.61 vs 0.40)**, i.e. our
  R range for 70-100 % is compressed (0.6-1.4 instead of 0.4-1.6). Candidates: the 665 nm red (less Hb extinction
  than at 660), the derivative/regression estimator (no RMS inflation), path-length ratio nearer 1 in thin tissue.
  The Life Meter wrist curve has the same slope (39.4) at a different offset: slope ≈ 39 is not exotic.
- Every curve fitted against another oximeter in a narrow range (Stubán 86-100, Life Meter, our adult finger)
  comes out with a slope that disagrees with the rest: range and reference noise, as in our own register.
- **Cheapest source of manufacturers' curves still unused:** the MS100 displays its R value for the active R-curve
  (BCI, Criticare, Datascope, Datex, PMS, Masimo, Nellcor, Nihon-Kohden, Ohmeda, Respironics) — reading R off the
  screen at 100/95/90/85/80/75/70 for each curve gives Contec's encoding of ten manufacturers' tables in minutes,
  and the ratio between the screen's R and our R-METHOD-2 R (0.61 vs 0.635 at 96 % with Nellcor) calibrates our R
  scale against the simulator's definition.

Sources: [US 12290358](https://patents.google.com/patent/US12290358B2/en) · [US 6801797](https://patents.google.com/patent/US6801797B2/en) ·
[Blaney 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC12238718/) · [Elron/Nitzan 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC9921559/) ·
[Stubán 2008](https://pp.bme.hu/ee/article/download/859/478) · [mizutanilab](https://github.com/mizutanilab/pulse-oximeter) ·
[SparkFun spo2_algorithm.cpp](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/blob/master/src/spo2_algorithm.cpp) ·
[Reynolds 1991](https://researchnow.flinders.edu.au/en/publications/temperature-dependence-of-led-and-its-theoretical-effect-on-pulse/) ·
[Maxim guidelines](https://www.analog.com/en/resources/technical-articles/guidelines-for-spo2-measurement--maxim-integrated.html) ·
[OxiMax tech note](https://www.ece.mcmaster.ca/faculty/debruin/debruin/EE%204BD4/OxiMaxTechNote.pdf) · [OpenOximetry repo](https://physionet.org/content/openox-repo/)
