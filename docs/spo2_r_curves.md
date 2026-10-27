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
| `R-CURVE-STS0163-HOSPNAV-20260923` (first use) | 115.17 | 21.54 | R-METHOD-1 | Medle ST-S0163 (-25 or -26, not recorded) | neonatal foot | Mindray N17 with Nellcor OxiMax SpO2 module via VideoNest OCR (response mode not recorded) | SUBJ08 + SUBJ09, 3471 stationary 8 s windows; `SUBJ08/Analysis/pooled_fit.py`, `findings.md` | 87-100 | OLS by bands, rms 1.53 | **discarded** 2026-10-02: slope is mostly R-METHOD-1 noise (regression dilution + out-of-band noise). Never applied. Label later reused — see next row |
| `R-CURVE-STS0163-HOSPNAV-20260923` (**current**, fitted 2026-10-04) | 123.98 | 39.13 | R-METHOD-2 | Medle ST-S0163 (-25 or -26, not recorded) | neonatal foot | Mindray N17 with Nellcor OxiMax SpO2 module via VideoNest OCR (response mode not recorded) | SUBJ08 + SUBJ09 replayed with lib v0.100, 3455 stationary 8 s windows; `SUBJ08/Analysis/fit_method2.py` | 85-100 (31 windows below 85 read −3.4) | OLS, ρ −0.80, scatter 1.65, median \|res\| 0.91, LOSO 0.95-1.38 | **shipped** as default since lib v0.100. Validated on SUBJ11 (30 wk, 1.5 kg) 2026-10-16: bias −0.2, sd 1.2. Pending: relabel to the fit date (`…-20261004`) so the label is unique |
| SUBJ08 only (diagnostic) | 129.2 | 46.7 | R-METHOD-2 | Medle ST-S0163 | neonatal foot | Mindray N17 / Nellcor OxiMax | SUBJ08 share of the row above | 85-100 | OLS | diagnostic: per-subject spread of the pooled fit; not a curve to apply |
| SUBJ09 only (diagnostic) | 118.8 | 32.1 | R-METHOD-2 | Medle ST-S0163 | neonatal foot | Mindray N17 / Nellcor OxiMax | SUBJ09 share of the row above | 85-100 | OLS | diagnostic, as above |
| `R-CURVE-STS0163-ADULTFINGER-20261020` (diagnostic) | 111.94 | 25.15 | R-METHOD-2 | Medle ST-S0163-26 lot 260521002, 3 units | adult finger (SUBJ01, index/middle/ring) | unbranded home fingertip oximeter via VideoNest OCR | breath-hold 2026-10-18, 1205 stationary pairs; `SUBJ01/SUBJ01_BIAS_ANALYSIS/pairs.csv` (OLS added 2026-10-20, no lag compensation) | **93-99 only** | OLS, rms 0.67 | diagnostic: range too narrow for a slope (R 0.54-0.77). What matters is the bias: current curve +3.0 (Arms 3.2), MS100/U401-D curve −0.5 (Arms 1.0) after 4 s lag compensation. Reference is itself a Nellcor-type adult curve |
| `R-CURVE-STS0163-MS100-20261019` | 121.06 | 39.11 | R-METHOD-2 | Medle ST-S0163-26 lot 260521002 | simulator | CONTEC MS100, "R-Curve Nellcor", Pulse Amp 3 %, TLC 3500, read by VideoNest OCR | SUBJ90 sweep 2026-10-19, 18 plateaus at 75/140/160 bpm; `SUBJ90/Analysis/ms100_sweep.py`, `findings.md` | sim 72-100 | OLS, rms 1.0 (table concave below 80 %) | bench reference only: same slope as the current curve, intercept −2.9. R independent of heart rate (±0.003); chain noise sd(R) 0.002-0.008 (< 0.3 pt) |

## What the register says so far

- Slope: every R-METHOD-2 fit with a usable range gives 39.1 ± 0 (neonatal foot vs Mindray, simulator vs its
  Nellcor table). The flatter slopes (30.55, 21.54, 25.15) are R-METHOD-0/1 noise or a range too narrow.
- Intercept: the two Nellcor-convention references (MS100 table, home oximeter on an adult finger) agree with
  each other and sit ~3 pt below the neonatal fit. **2026-10-27: every N17 of the unit where SUBJ08-11 were
  captured carries a Nellcor OxiMax SpO2 module (unit staff; sticker on the module; not verifiable from the
  screen frames), so the neonatal reference is the same Nellcor convention** and the ~3 pt is not Mindray vs
  Nellcor. What it can still be: the site (neonatal foot vs adult finger under our probe), a bias of Nellcor's
  adult calibration on neonatal feet (bounded by its MAX-N validation: Arms 2.5 on 42 neonates, 85-99 %), or
  the home oximeter not being Nellcor-like. The applicable neonatal validation is Nellcor's, not Mindray's
  518B/520N. The decisive cheap test is unchanged and now compares against the very module the neonates were
  referenced to: Alex's finger on the N17's own adult sensor and the Medle at once (`conversation_log.md`
  2026-10-19). Nellcor response mode (Normal 5-7 s / Fast 2-4 s) was not recorded; the 8 s pairing window
  covers either.
- Not recorded in the 2026-09-23 campaign and needed in the next: probe suffix/lot per baby, the monitor's
  averaging window, the monitor's probe site (pre/post-ductal), arterial blood gases when taken clinically.

## Median R at the same displayed SpO2, across data sets (2026-10-25)

Same probe model and R-METHOD-2 everywhere; stationary 8 s windows; `n` = windows. Full analysis and the
alternatives in the library's `incunest_afe4490_design_rationale.md` §18.

| reference SpO2 | neonatal feet SUBJ08+09, Mindray N17 (n 3455) | preterm 30 wk SUBJ11, Mindray N17 (n 1121) | adult finger SUBJ01 18-oct, home oximeter (n 1179) | adult finger SUBJ01 23-oct, home oximeter (n 2022) | MS100 Nellcor table |
|---|---|---|---|---|---|
| 94 % | 0.757 | 0.766 | 0.712 | 0.705 | 0.692 |
| 96 % | 0.715 | 0.739 | 0.636 | 0.615 | 0.641 |
| 98 % | 0.650 | 0.665 | 0.580 | 0.585 | 0.590 |
| 99 % | 0.629 | 0.635 | 0.545 | 0.531 | 0.564 |

Neonates vs adult/simulator: R higher by 0.05-0.10 at every level (mean 0.07 ≈ 2.7 points), no trend: an
intercept offset, same slope. Within each group the sets agree within 0.02. Which side a CO-oximeter would
take is not known (both references are ±2-3 Arms transfer devices).

### (a, b) per data set and the scatter (2026-10-26)

`experiments/r_curve_scatter_20261026.py`; figure `spo2_r_curves_scatter_20261026.png` (left: every stationary
pair, one colour per campaign; right: median R per reference level with the IQR). Fit = the register's bin fit
(weighted LS on the per-bin median R, bins = integer reference SpO2 with ≥ 10 pairs); the simulator row is OLS
on its 18 plateaus. "a at b = 39.13" = median over pairs of (reference + 39.13·R), i.e. the intercept with the
shared slope; the offset is that intercept minus 123.98. The free slopes of the sets whose range is under 10
points (SUBJ11, SUBJ01) are not meaningful (narrow range + regression dilution, as above); compare on the
fixed-slope column.

| Data set | n | Ref. range | PI % (pp) | a | b | a at b = 39.13 | Offset vs shipped [pt] |
|---|---|---|---|---|---|---|---|
| SUBJ08 + SUBJ09 pooled (fit base, `R-CURVE-STS0163-HOSPNAV-20261004`) | 3455 | 79-100 | ≈ 2.5 * | 123.98 | 39.13 | 124.01 | +0.0 |
| SUBJ08 only | 2085 | 84-100 | ≈ 2.3 * | 129.22 | 46.70 | 123.59 | −0.4 |
| SUBJ09 only | 1370 | 79-100 | ≈ 3.1 * | 118.84 | 32.11 | 124.50 | +0.5 |
| SUBJ11, preterm 30 wk, Mindray N17 (live firmware columns) | 1121 | 92-100 | 2.8 | 120.85 | 34.49 | 124.19 | +0.2 |
| SUBJ01 adult finger 18-oct, home oximeter | 1179 | 93-99 | 7.6 | 115.28 | 30.43 | 120.83 | −3.2 |
| SUBJ01 adult finger 23-oct, 3 probes, home oximeter | 2022 | 93-99 | 3.2 | 113.03 | 26.34 | 120.52 | −3.5 |
| MS100 "Nellcor" table (`R-CURVE-STS0163-MS100-20261019`) | 18 | 72-100 | 4.5 | 121.06 | 39.11 | 121.11 | −2.9 |

\* The 2026-09-23 pairs files hold the pre-v0.101 RMS PI (medians 0.9 / 0.8 / 1.1); the table shows ×2.8, today's
peak-to-peak units (rationale §11), so the column is comparable with SUBJ11 and SUBJ01. The 2026-10-25 line
"neonatal PI 0.8-1.1 %" was that units slip; corrected 2026-10-27.

Nuance to the 2026-10-25 line "no trend": per level the neonatal-minus-adult difference in R is 0.05 at 94 %
and 0.09-0.10 at 99 % (2 to 4 points), so the offset is 2.7 points as a mean over levels and 3.2-3.5 as a mean
over pairs (the adult pairs sit mostly at 97-99 %). Whether that is a slightly flatter adult slope or noise
cannot be told on a 93-99 range.

## Columns

Label · a, b (SpO2 = a − b·R) · R method · probe model, suffix and lot · application site · reference (make,
model, how it was read, averaging) · data folder, script, number of pairs · reference range covered · fit
method and residuals · state (shipped / discarded / diagnostic / bench) with the decision date.

## Published curves, for comparison (search 2026-10-20)

The 2026-10-26 survey `docs/r_curve_calibration_survey.md` has the manufacturers' methods and curve forms, the
chronological list of calibration studies, the open blood-referenced fit (Blaney 2026 on OpenOximetry,
116.73 − 32.53·R, 660/910 nm finger) and the factors that move the curve with their magnitudes. The rows below
are kept as the comparison table.

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
  R range for 70-100 % is compressed (0.6-1.4 instead of 0.4-1.6). Candidates: the derivative/regression
  estimator (no RMS inflation), path-length ratio nearer 1 in thin tissue
  (not the red wavelength: our 668 nm measured red, vs 660, *lowers* R at 100 % by ≈ 6 % and compresses the
  70-100 % range by only ≈ 4 %, see `r_curve_calibration_survey.md` §6),
  (Atuar/Nitzan 2026, Monte Carlo of a finger at 660/940 nm: ℓIR/ℓR 0.69-0.80 — quoted there as red/IR 1.25-1.45 —
  moving with SaO2 at the standard position, ≤ 1.05 at an "iso-pathlength" geometry; the ratio is not a constant of
  the tissue but of tissue × saturation × geometry).
  The Life Meter wrist curve has the same slope (39.4) at a different offset: slope ≈ 39 is not exotic.
- Every curve fitted against another oximeter in a narrow range (Stubán 86-100, Life Meter, our adult finger)
  comes out with a slope that disagrees with the rest: range and reference noise, as in our own register.
- **Cheapest source of manufacturers' curves still unused:** the MS100 displays its R value for the active R-curve
  (BCI, Criticare, Datascope, Datex, PMS, Masimo, Nellcor, Nihon-Kohden, Ohmeda, Respironics) — reading R off the
  screen at 100/95/90/85/80/75/70 for each curve gives Contec's encoding of ten manufacturers' tables in minutes,
  and the ratio between the screen's R and our R-METHOD-2 R (0.61 vs 0.635 at 96 % with Nellcor) calibrates our R
  scale against the simulator's definition.

Sources: [US 12290358](https://patents.google.com/patent/US12290358B2/en) · [US 6801797](https://patents.google.com/patent/US6801797B2/en) ·
[Blaney 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC12238718/) · [Elron/Nitzan 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC9921559/) (no Part 2 exists) ·
[Atuar/Nitzan 2026, Opt Lett 51:2424](https://doi.org/10.1364/ol.588131) ·
[Stubán 2008](https://pp.bme.hu/ee/article/download/859/478) · [mizutanilab](https://github.com/mizutanilab/pulse-oximeter) ·
[SparkFun spo2_algorithm.cpp](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library/blob/master/src/spo2_algorithm.cpp) ·
[Reynolds 1991](https://researchnow.flinders.edu.au/en/publications/temperature-dependence-of-led-and-its-theoretical-effect-on-pulse/) ·
[Maxim guidelines](https://www.analog.com/en/resources/technical-articles/guidelines-for-spo2-measurement--maxim-integrated.html) ·
[OxiMax tech note](https://www.ece.mcmaster.ca/faculty/debruin/debruin/EE%204BD4/OxiMaxTechNote.pdf) · [OpenOximetry repo](https://physionet.org/content/openox-repo/)
