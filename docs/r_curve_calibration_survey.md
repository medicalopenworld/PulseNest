# R-curve calibration survey — how manufacturers and the literature obtain SpO2 = f(R), and what moves the curve

Search date 2026-10-26 (Alex's request: exhaustive list of R-curve calibrations, manufacturers first, then the
scientific and medical literature, each with how the curve was obtained; then the factors that shift the curve
and by how much; the curve is not necessarily a line a − b·R). Companion to `docs/spo2_r_curves.md` (our own
fits and the comparison table of published coefficients) and to the library rationale §18.

Conventions. R = (AC/DC)_red / (AC/DC)_IR unless stated; some sources use the log ratio
ln(I_max/I_min)_red / ln(I_max/I_min)_IR, equal to the first for small pulses. "bias" = SpO2 − SaO2. "pt" =
SpO2 percentage points. VERIFIED = read in the source during this search; SECOND-HAND = quoted by another
source; "not published" = looked for and not found in any fetched source. Full URL list at the end.

---

## 1. Cross-cutting findings

1. **No hospital manufacturer publishes its curve.** No operator's manual, 510(k) summary or patent prints a
   table of R vs SpO2 or numeric coefficients for a commercial oximeter. What is public is the *form* (patents),
   the *method* (ISO 80601-2-61 Annex DD, FDA 2013), illustrative points (R = 1 ↔ ≈ 85 %) and chip-vendor demo
   curves. Simulators (Fluke, Contec, Pronk, Viamed) store the tables in firmware and print none.
2. **The curve is not a straight line in any primary manufacturer source.** Nellcor: rational (Möbius) above
   70 % plus a linear segment below, later piece-wise sets or cubic-spline knots stored in the sensor. Masimo,
   GE, Philips, Nihon Kohden: look-up tables from regression on volunteer data. Analog Devices: "a rational
   function which can be approximated by a polynomial". Maxim: 184-entry table "approximated as" a quadratic.
   The linear a − b·R is a textbook/chip-vendor convenience valid near 85 %.
3. **One calibration method, codified:** controlled desaturation of healthy adult volunteers, arterial blood vs
   CO-oximeter, 70-100 % SaO2, ≥ 24 participants × ≈ 20 samples (ISO 2026), pigmentation mix required.
   Neonatal sensors are calibrated on adults (FDA 2013 §4.1.2; ISO 2026 201.12.1.101 d). A transfer-standard
   route (compare with an already calibrated oximeter, no blood) is allowed for development only (ISO EE.4,
   Annex JJ) and was used by GE for TruSignal (K093881).
4. **Per-sensor wavelength correction is universal:** Nellcor RCAL resistor selects a coefficient bin per LED
   wavelength; Nihon Kohden's probe resistor sets an analog gain on the red channel; Covidien digital sensors
   carry "gamma coefficients" from a spectrometer measurement of the LED; ISO EE.5: "Most pulse oximeter
   monitors contain a set of modulation ratios where each modulation ratio is for a specific range of optical
   properties (i.e. range of wavelengths)".
5. **Different curves exist for low saturation**, obtained by changing the wavelengths and the validation
   population, not the patient's age: Nellcor 735/890 nm (sheep calibration, fetal/cardiac), Masimo Blue
   (60-80 %, ±4 %, wavelengths undisclosed, validated on cyanotic infants).
6. **The only public, blood-referenced, finger-transmission fit with printed coefficients** is Blaney et al.
   2026 on the OpenOximetry repository (98 patients, 2991 arterial draws, 660/910 nm): linear
   SaO2 = 116.73 − 32.53·R, or the modified Beer-Lambert rational with path-length ratio β = 0.987 and a
   +10.2 % offset, Arms 2.42 % either way.
7. **What moves the curve by ≥ 2 pt** (section 5): the wavelength pair and the red/IR path-length ratio at
   low SaO2 (instruments differed by up to 21 pt at 56 % SaO2 in 1989), sensor fit and optical shunt, low
   perfusion combined with pigmentation, venous pulsation (−1.4 to −18 pt), anaemia below 75 % SaO2,
   dyshaemoglobins, and the neonatal scatter itself (+2.9 ± 5.8 pt). LED temperature drift is negligible; LED
   current and centre-wavelength tolerance matter only below ≈ 85 % SaO2 (≈ 0.3 pt per nm at 50 %).

---

## 2. Manufacturers — curve form, how obtained, how encoded

| Manufacturer | Curve form (source) | How the curve was obtained | Per-sensor / population handling | Status |
|---|---|---|---|---|
| **Nellcor / Covidien / Medtronic** (OxiMax) | Above 70 %: `SpO2 = 100·(c2 − c4·R) / ((c3 − c4)·R + (c2 − c1))`; below 70 %: `c5 − c6·R`, breakpoint 70 % in software; later two coefficient sets switched at a breakpoint stored in the sensor (example 68 %), or **spline knots** (R at fixed SpO2 points 5-10 % apart, cubic interpolation) — US 6,801,797 (VERIFIED). "Although theoretically based, the four constants c1-c4 are empirically determined… insufficient primarily due to the complexities of light scattering." Illustrative values in the patent (R 0.5/0.6/0.7 ↔ 100/95/90 %) are placeholders. | Invasive hypoxia study on healthy adults, 70-100 %, laboratory CO-oximeter, per ISO 80601-2-61 (K123581 N-600x, VERIFIED; 2002 accuracy grid "healthy non-smoking adult volunteers", SECOND-HAND). 735/890 nm low-sat sensors calibrated on sheep with femoral catheter, IL 282 / OSM-3, 100 % to < 10 % (US 5,421,329, VERIFIED). | RCAL resistor encodes the red LED wavelength (table: 150 Ω → 940/660, 160 → 950/660, 170 → 940/670, 180 → 950/670 nm; US 4,621,643); "the values of the sets of constants (c1-c4) vary with each resistor coding bin". OxiMax tech note: orange-shifted red LEDs "shift and rotate" the curve, more at low saturation; a single curve "degrades accuracy particularly below 85 %". Digital sensors: LED spectrum measured with a spectrometer and mapped to "gamma coefficients" from the hypoxia study, stored in the sensor (US 12,076,141). MAX-N ±2 digits adult / ±3 neonate; neonatal validation 42 neonates, 63 pairs 85-99 % (our `ppg_neonatal_manufacturer_references.md`). | Numbers not published |
| **Masimo** (SET, rainbow, RD SET) | ROM **look-up table** of RD/IR → SpO2 from "statistical regression of experimental measurements obtained from human volunteers"; "an RD/IR value of 1.0 … approximately 85 %" (US 7,274,955, US 7,428,432: example 660/905 nm; VERIFIED). Compensation by shifting/rotating the curve for site temperature, pH, Hct, COHb, MetHb (patent claims). Cyanotic-infant patent US 8,682,407: the constant red/IR path-length assumption "may not be valid when cyanotic infants are included"; proposes a calibration *surface* adding the DC-response ratio. | "SpO2 is empirically calibrated to functional arterial oxygen saturation in healthy adult volunteers with normal levels of COHb and MetHb", 60-100 %, laboratory CO-oximeter; sensors validated "on healthy adult male and female volunteers with light to dark skin pigmentation in induced hypoxia studies 70-100 %"; neonatal: 16 NICU infants, 7-135 days, 0.5-4.25 kg, 79 samples 70-100 %, Arms 2.9 % (Rad-57 manual LAB-9204A, VERIFIED). Masimo 510(k) K092838: neonatal ±3 % = adult data "and 1 % was added" for HbF. | One curve family per sensor construction class (Philips FAST note tests LNOP NeoL as representative of ~40 Masimo neonatal sensor models). **Documented curve discontinuity:** pre-V4.8 software merged two curves (lower one added 2002), leaving a gap at 87-90 % and values above 87 % elevated by up to 2 pt; found in 176 preterm infants in 35 UK/Irish units (Johnston 2011, VERIFIED); it contaminated SUPPORT/BOOST-II (NEJM 2013, SECOND-HAND). Blue sensor: 60-80 % ±4 %, 70-100 % ±3.3 %, validated on cyanotic infants (Cox 2005: standard LNOP curve had slope 0.514 vs SaO2 in 53-86 %, Blue 1.01-1.02). | Numbers not published |
| **Philips** (FAST; M1191, M1020, IntelliVue) | "Validated calibration table" converting the ratio to SpO2 (K062455, VERIFIED). Patient category (adult/paediatric vs neonatal) "is used to optimize the calculation of the SpO2 and pulse numerics" (manufacturer references doc). | "Calibration curves… based on controlled hypoxia studies with healthy non-smoking adult volunteers over a specified saturation range (SaO2 from 100 %-70 %)"; FAST application note 2024: ≈ 50 % female, ages 19-39, "skin tone: from light to dark brown", "more than 300 blood samples… equally spread over the range from 70 % to 100 %" per tested sensor (VERIFIED). | Representative-sensor testing per construction class; neonatal sensors validated on adults (Masimo NeoL on Philips: Arms 1.87 %; 2.32/1.85/1.44 by decade). "A functional tester cannot be used to assess the accuracy… it can be used to demonstrate that a particular monitor reproduces a calibration curve". | Numbers not published; ProSim 8 uses a Fluke-derived curve for Philips |
| **Nonin** (PureSAT) | Not disclosed (no patent found). | Induced hypoxia on 14 healthy non-smoking light-to-dark-skinned subjects, independent lab, arterial CO-oximetry (K131021, VERIFIED); white paper: 13 subjects "industry standard breathe-down" (SECOND-HAND). ±2 digits 70-100 %. | Simulator vendors carry sensor-specific Nonin curves (ProSim 8 manufacturer-supplied). | Numbers not published |
| **Nihon Kohden** | `S = f(φ)`, φ = pulsatile absorbance ratio red/IR; f depends on the red wavelength, form not disclosed (US 5,267,562, VERIFIED). | ClinicalTrials protocols at UCSF (NCT05297500): ≥ 10 subjects incl. 2 dark, ≥ 200 points, 70-100 %, Arms ≤ 2 % (SECOND-HAND). Nonin and NK extrapolate neonatal claims from adults (manufacturer references doc). | Red LED tolerance "on the order of ±10 nm": probe resistor sets an analog gain `φ(660) = A_n·φ(n)` so "the main unit needs no wavelength decoding or correction table"; prior art used a ROM table. | Numbers not published |
| **GE / Datex-Ohmeda** (TruSignal, Biox) | R = slope of the best-fit line of red vs IR samples, "then used in an empirical calibration formula" (US 5,934,277, VERIFIED); formula not disclosed. Wukitsch 1988 (J Clin Monit) is an *Ohmeda* paper (not Nellcor). | **Transfer standard:** "induced hypoxia studies on ten healthy adult volunteers (18-42 y, light to dark pigmentation)… compared to a reference oximeter system whose readings were converted to CO-oximeter based… values using empirical linear regression… Arterial blood samples were not taken" (K093881, VERIFIED). | — | Numbers not published; ProSim 8 uses a Fluke curve |
| **Mindray** | Not disclosed. | 510(k) K183277: ±2 % 70-100 % (SECOND-HAND). Only Mindray, Masimo and Medtronic publish neonatal validation (518B: 97 neonates, Arms 2.38 %; 520N: 122, 2.88 %). | — | Not published |
| **BCI / Smiths** | Not disclosed. | 10 healthy adults 21-36 y, Arms ≈ 2.95 % under motion (K070732); 1996: SD 1.92 % 70-100, 2.31 % 50-69 (K962156) (SECOND-HAND). | — | Not published |
| **Criticare, Novametrix/Respironics, Edan** | Nothing primary found; present only as curve names in simulator lists. | — | — | Not published |
| **Contec** (CMS-50 family) | Not disclosed. 510(k) K082641: "No clinical data provided", bench only (VERIFIED). Its MS100 simulator embeds ten other makers' curves (BCI, Criticare, Datascope, Datex, PMS M1190, Masimo, Nellcor, Nihon-Kohden, Ohmeda & Nova, Respironics) and none for Contec's own oximeters. | — | — | Not published |

### 2.1 Chip and module vendors (demo curves, explicitly "re-calibrate per device")

| Vendor | Curve (VERIFIED unless noted) | How obtained | Note |
|---|---|---|---|
| **Texas Instruments** AFE4490 (TIDA-00301, SLAA655) | `SpO2 = 110 − 25·R`, R from AC_rms/DC; "When the ratio is 1, the SpO2 value is about 85 %" | "This model is often used in the literature… However, it relies on the calibration curves"; constants "derived empirically during in-vivo calibration… against SaO2 from arterial blood samples… for a large group of subjects" | AFE44x0 EVM guide has no calibration section |
| **Maxim / Analog Devices** MAX3010x (MAXREFDES117) | 184-entry table indexed by R×100, "approximated as −45.060·R² + 30.354·R + 94.845"; R from peak minus interpolated valley, median of ≤ 5 beats; table: index 100 → 80 % | Origin of the numbers not documented anywhere; AN 6845 says a, b, c must be re-fitted "when Maxim's sensors are used with different optical shields and form factors" (hypoxia study per ISO) | Fixed-point formula "did not achieve the accuracy due to register overflow" |
| **Analog Devices** ADPD4100 (SECOND-HAND, article not fetched) | `SpO2 = f(RoR)`, "a rational function which can be approximated by a polynomial" (US 12,329,503) | "Calibration will be required for all SpO2 designs"; "200 measurements equally spaced between 100 % and 70 %" vs CO-oximeter → table or equation | No default coefficients |
| **OSRAM** SFH 7050 app note | No curve; error-vs-wavelength-shift plot: "the lower the SpO2 level, the higher the overall error due to wavelength shift… 940 nm is uncritical compared to the 660 nm LED"; centroid TK 0.13 nm/K (660), 0.25 nm/K (940) | Suggests temperature-based wavelength compensation | — |
| **Apple** (Blood Oxygen white paper, SECOND-HAND, 403) | "Predefined mapping" of the red/IR modulation ratio; patent app 2024 "asymmetric distance-dependent calibration" | — | No numbers |

### 2.2 Simulators — how curves are encoded

- **Fluke ProSim 8** (manual Rev. 3, VERIFIED): built-in types Nellcor, Masimo, Masimo Rainbow, Nonin, GE/Ohmeda,
  Philips, Nihon Kohden, Mindray, BCI. "With manufacturer R-curve: Nellcor, Masimo, Nonin, and Nihon Kohden"
  (accuracy ±1 count + UUT spec); "With Fluke Biomedical R-curve: Mindray, GE-Ohmeda, Philips/HP, and BCI"
  (±3 counts 91-100 %, ±5 at 81-90 %, ±7 at 71-80 %, "below 71 % monotonic with unspecified accuracy"). That
  degradation is an indirect measure of how far makers' curves diverge at low saturation. Custom curves via Ansur:
  a **table**, one integer "SpO2 ratio" per SpO2 % from 30 to 100, uploaded by USB; built-in tables not exported.
  Fluke white paper: the R-curve is "unique to each manufacturer… integrated into the firmware of the monitor";
  "a SpO2 tester is a secondary standard which transfers equivalence from prior devices".
- **Contec MS100 / Gima 54600** (local manual, VERIFIED): "As different manufactures may use different R-curve, the
  stimulator is embedded parts of current popular R-curve in advance"; ten presets; no values printed; the screen
  shows the R in use (our observation 2026-10-19: TLC scales DC and AC together, R invariant). Reading R off the
  screen at 100/95/90/85/80/75/70 for each preset is still the cheapest way to get Contec's encoding of ten
  makers' tables (`docs/spo2_r_curves.md`).
- **Pronk OxSim Flex** (manual 2019, VERIFIED): "SpO2 is then calculated according to an equation which is a
  polynomial in R and which depends on the exact wavelengths used… pretty much a straight line between 100 %
  saturation having a R value of around 0.6… and 81 % saturation having a R value of 1.0". Autoprobe is accurate
  85-100 %; below 85 % the maker's probe type must be selected (Nellcor-D, Masimo-D, Phlip-Glv, Nonin-Pur,
  GE-Ohmeda, Datex, BCI, M-Rainbow, Phlip/HP, GE-TufSat); "Testing with LNOP blue sensors Sat. accuracy is ±4 %
  between 60 %-80 %".
- Fluke Index 2: "10 preloaded manufacturers' R-curves", six user spaces. Viamed DL-3000: 84 curves, only
  "verified and authorised by the respective pulse oximeter manufacturer" curves count as calibration
  (SECOND-HAND). ISO 2026 201.12.1.101.3 h): "Functional testers or patient simulators shall not be used for
  verification [of] the SpO2 accuracy".

### 2.3 Regulatory frame (what every manufacturer's curve has to pass)

- **FDA 2013 guidance** (VERIFIED): ISO 80601-2-61 Annex EE.2 method, "10 or more healthy subjects that vary in
  age and sex", "200 or more data points", "at least 2 darkly pigmented subjects or 15 %", typical Arms 3.0
  (transmission) / 3.5 (ear clip, reflectance); sub-ranges 70-80/80-90/90-100 in labelling. Neonates: "report
  performance of neonatal sensors on adult subjects… due to the uncertainty of determining the accuracy of
  sensors intended for use in neonates"; new neonatal sensors add convenience arterial samples "clustered around
  90 % SaO2".
- **ISO 80601-2-61:2026** (local PDF, VERIFIED): Annex DD normative: ≈ 20 samples × ≥ 24 participants ≥ 480
  pairs, ≈ 1/3 per decade; 201.12.1.101.6: 20 ± 4 pairs each (16-30), ≥ 90 % of participants with a pair < 85 %,
  ≥ 75 % with a pair 70-80 %, ≥ 33 % each sex, perceived skin-tone scale with printed swatches; pigmentation
  differential bias (ITA −50° vs +50°, 80-90 %) ≤ 2.5 % with 95 % confidence; SpO2 indicated as **functional**
  saturation; CO-oximeter 1 % (1 SD) or better, a < 2 % Arms claim needs 0.5 %; DD.2.3.2: ≥ 60 s after an FiO2
  change before sampling, consecutive samples ≥ 20 s apart, readings stabilised ≥ 30 s, example 5 plateaus × 4
  samples. Annex JJ transfer standard: Arms ≤ 2.0 vs CO-oximeter on ≥ 48 participants, averaging 6-10 s; using
  one "increases the RMS by about 0,28" (4644 pairs, 195 studies); "not acceptable for final verification".
- **FDA 2025 draft** (VERIFIED): ≥ 150 participants, three Monk groups each ≥ 25 %, ≥ 50 % of MST 8-10 with
  forehead ITA ≤ −50°, 20-24 pairs per participant, Arms < 3 % (upper 95 % CI), differential bias < 3.5 pt
  (70-85 %) and < 1.5 pt (85-100 %).

---

## 3. Published curves with numbers — catalogue by form

Coefficients are **not comparable across rows** (R depends on wavelengths, geometry, estimator). The table in
`docs/spo2_r_curves.md` §"Published curves" already lists the classic line, Blaney 2024, Stubán 2008, Life Meter,
Maxim, Reynolds 1991 and Nitzan; the rows below are the additions from this search.

| Curve | Form and numbers | R estimator, wavelengths, geometry | How obtained (reference, n, range) | Source |
|---|---|---|---|---|
| **Blaney, Frias, Durbha, Fantini, Koomson 2026** (arXiv 2609.30122) | Case 1 linear `SaO2 = 116.73 − 32.53·R` (R at 100/85/70 % = 0.51/0.98/1.44, derived). Case 2 mBLL rational `SaO2 = [−ε_Hb,r + ε_Hb,i·β·R] / [(ε_HbO2,r − ε_Hb,r) + (ε_Hb,i − ε_HbO2,i)·β·R] + o`, β = ⟨ℓ⟩_IR/⟨ℓ⟩_red = 0.987, o = +10.21 %. Case 3 spectrum-weighted (red FWHM 25 nm, IR 50 nm): β = 0.957, o = 9.85 %, melanin-dependent. Arms 2.420 / 2.416 / 2.418 %; 200-fold held-out 2.49 %. Residual slope vs melanin +2.8 / +1.2 / +0.1 pt per unit melanin volume fraction (abstract VERIFIED; coefficients from the full text, agent-read) | peak/valley with moving-median baselines, quality gating; 660/910 nm; finger transmission; OpenOximetry PPG at 86 Hz | **Arterial CO-oximetry**, 98 patients, 2991 draws, SaO2 65.2-99.4 % (median 85.0), RoR 0.376-1.740 (median 0.986) | https://arxiv.org/abs/2609.30122 |
| Al-Halawani, Qassem, Kyriacou 2024 (Monte Carlo) | commercial reference `110 − 25R`; light skin `109 − 25.95R`; moderate `109.2 − 32.69R`; dark `110.6 − 50.31R` (Eqs. 4a-4d, VERIFIED) | `[(I_d − I_s)/I_s]_660 / […]_940`; 660/940 nm; finger transmission 13 mm; melanosome 2.55/15.5/30.5 % | simulation, SaO2 70-100 % in 5 % steps; simulated bias 1.7 % light vs 9.3 % dark with the reference line | https://pmc.ncbi.nlm.nih.gov/articles/PMC11321364/ |
| Verkruysse et al. (Philips) 2017 | `SpO2 = 118.0 − 45.9·R` (constants printed; equation as image) | median peak − valley after 0.5-1.5 Hz band-pass; camera filters 675/842 nm; forehead, remote reflectance | 26 individuals, 31 points, ≈ 83-100 %, reference = median of 4 contact oximeters (no blood); Arms 1.15 % | https://doi.org/10.1213/ANE.0000000000001381 |
| Dassel et al. 1992 (fetal lambs, scalp reflectance) | printed `red/IR = 4.088 − 0.038·SaO2` (r 0.96) → inverted `SaO2 ≈ 107.6 − 26.3·R` | 15-s averages of relative intensity changes; wavelengths not seen | 53 measurements, 4 fetal lambs, SaO2 17-82 %, fetal arterial samples; precision 4.7 % | https://doi.org/10.1203/00006450-199203000-00014 |
| Conn, Schwarz, Borkholder 2019 (toilet-seat thigh reflectance) | slopes −36.9 and −33.1 pt per unit R in 2 desaturated subjects ("within 11 % of the literature value of −33.3"); offsets differ per subject | wavelengths not stated | 11 subjects, 91 pairs vs finger oximeter, Arms 2.3 % | https://pmc.ncbi.nlm.nih.gov/articles/PMC6356186/ |
| Saiko 2024 (rPPG model) | `SpO2 = C1 − C2·R`, model 660/840 nm: 119.1 − 41.8R; pulsation depth 0.6 mm: 119.2 − 45.2R | R ∝ exp(−2(µeff,1 − µeff,2)·Z): depends on the depth of the pulsatile volume | theory | https://pmc.ncbi.nlm.nih.gov/articles/PMC11351970/ |
| Pan et al. 2025 (skin-tone-specific curves) | three curves by skin tone, figures only (r 0.996-0.998) | log ratio; 660/940 nm fingertip transmission (WIT-S200) | 71 adults (34 "yellow", 20 "white", 17 "dark"), 1699 ABG (ABL90), plateaus 100→70 %; MAE 0.9 → 0.3-0.5 pt after tone-specific curves | https://link.springer.com/article/10.1007/s42452-025-07129-4 |
| Cox & Fernandes 2005 (Masimo Blue vs standard, cyanotic infants) | not an R-curve: `SpO2 = 39.65 + 0.514·SaO2` for the standard adult-derived LNOP curve (bias +4.7, precision 5.2) vs `−1.155 + 1.013·SaO2` (Blue thumb) in 53-86 % SaO2 | — | 21 ICU children, 160 ABGs with CO-oximetry | Masimo-hosted PDF (see URL list) |
| Elron, Bromiker, … Nitzan 2023 (17 cyanotic newborns, feet) | Beer-Lambert rational with ℓ2/ℓ1 = 1 for a 761/820 nm prototype; post-hoc `SpO2 − SaO2 = a·SaO2 + b` (a, b in figures only) | ln(I_D/I_S) ratio; Nellcor OxiMax 660/900 vs prototype 761/820 nm | post-ductal arterial samples, SaO2 ≈ 51-85 %; before correction bias +4.1 (red/IR) / +5.5 (two-IR), SD 5.5/4.5; after linear correction SD 6.5 vs 3.6 %, Arms 6.3 vs 3.5 | https://pmc.ncbi.nlm.nih.gov/articles/PMC9921559/ |
| Nellcor US 6,801,797 | rational above 70 % + linear below (§2), knots 5-10 % apart | — | hypoxia studies, numbers not published | https://patents.google.com/patent/US6801797B2/en |
| Kyriacou 2006 (oesophageal reflectance, City) | `SpO2 = 110 − 25·R` "a linear approximation to an empirical calibration curve established by measurements on a large group of healthy volunteers with SaO2 generally greater than 70 % (Webster 1997)" | (ac660/dc660)/(ac940/dc940); 655/880 nm reflectance | clinical validation 50 cardiothoracic patients: bias 0.02 ± 0.88 % vs blood gas (SECOND-HAND within the review) | City repository PDF |
| Wu et al. 2023 (self-calibrated, freedivers) | no fixed curve: the ratio of mean path lengths is fitted per measurement to the DPF model as a function of SaO2; conventional comparator uses fixed ⟨L⟩ ratio 0.87 | 760/840 nm forehead reflectance, 3-4 cm | 9 subjects, 23 arterial samples, SaO2 41-100 %: MAE 4.2 % vs 11.3 % conventional | https://doi.org/10.1117/1.JBO.28.11.115002 |
| Nitzan et al. 2014 (calibration-free) | `SpO2 = (ε_d1 − R·ε_d2) / [R(ε_o2 − ε_d2) + (ε_d1 − ε_o1)]` with ℓ2/ℓ1 = 1 for two close IR wavelengths | laser diodes 780/808 nm, finger transmission | 15 males, no blood; 780-808 pair within 2.5 % of a BCI oximeter with Zijlstra coefficients (Prahl/Cope coefficients gave 80-91 %); ±0.2 nm ≈ ±0.5 % | https://www.mdpi.com/1424-8220/14/4/7420/htm |

Slope summary (dSpO2/dR): −23 to −26 for the classic transmission lines; −32.5 on the open blood-referenced
finger set; −33 to −37 thigh reflectance; −42 to −46 shallow forehead/camera reflectance; Monte Carlo predicts
the slope steepens with melanin in transmission (−26 → −50) at the same intercept. Our own neonatal-foot and
MS100 fits (−39, `docs/spo2_r_curves.md`) sit between the finger set and the reflectance values.

---

## 4. Calibration studies in the scientific and medical literature — chronological list (how each curve was obtained)

Entries without numbers are kept because they define the method or the reason the curve has its shape. "not seen"
= coefficient not printed in anything fetched.

| Year | Study | What it establishes about the curve | How obtained |
|---|---|---|---|
| 1980 | Yoshiya, Shimada, Tanaka, Med Biol Eng Comput 18:27 | first fingertip pulse oximeter paper; oximeter vs blood gas `y = 0.907x + 8.592`, r 0.983 (SECOND-HAND) | blood gas reference, n not seen |
| 1987 | Pologe, Int Anesthesiol Clin 25:137 | empirical Ohmeda curve (figure); artefact drives R → 1 and SpO2 → 85 % | — |
| 1988 | Wukitsch, Petterson, Tobler, Pologe (Ohmeda), J Clin Monit 4:290 | theory/technology/practice of the empirical curve; paywalled | — |
| 1988 | Harris et al., J Clin Monit 4:175; 1989 Mendelson & Kent, IEEE TBME 36:844 | HbF and HbA absorption "nearly identical" 600-1050 nm: the adult curve transfers to neonates optically | in vitro spectra |
| 1988 | Mendelson & Ochs, IEEE TBME 35:798 | reflectance SpO2 from normalised red/IR PPG ratio, 10 adults (numbers not seen) | — |
| 1989 | Severinghaus, Naifeh, Koh, J Clin Monit 5:72 | makers' curves were extrapolated below ≈ 80 %: 14 oximeters, 50 volunteers, plateaus ≈ 86/74/62/50 %; "ambiguity" at 55.8 % from 3.3 to −21.2 pt; slopes "deviated from 1 in proportion to" the error | arterial, OSM-3 |
| 1991 | Schmitt, IEEE TBME 38:1194 | photon-diffusion expressions for AC/DC vs SaO2; red/IR path-length difference makes the curve depend on tissue attenuation, blood volume and placement; fixed curves err "less than a few percent when SaO2 exceeds 70 %", "substantially greater" below | theory |
| 1991 | Reynolds et al., BJA 67:638; de Kock et al., J Med Eng Technol 15:111 | LED temperature shift 0.11 nm/°C (660) and 0.16 nm/°C (950): negligible; LED intensity ×10 → +8 nm → 2.5 pt at 50 % SaO2, little at ≥ 85 % | Beer-Lambert model + bench |
| 1992 | Dassel et al., Pediatr Res 31:266 | reflectance fetal-scalp line (table §3) | 4 fetal lambs, 53 arterial samples, 17-82 % |
| 1992 | Reynolds et al., Med Biol Eng Comput 30:629 | in-vitro pulsating cuvette: Datex Satlite `SpO2 = 0.88·SaO2 + 11.2` (slope < 1 of a commercial curve) | bench oximeter |
| 1993 | de Kock & Tarassenko, Med Biol Eng Comput 31:291 | Twersky scattering model fits whole-blood cuvette R vs SaO2 within 1 SD; R:IR nearly independent of depth | 660/950 nm cuvette |
| 1993 | Thilo et al., J Pediatr 122:620 | 30 infants, 120 samples: Nellcor N-100 read 1.61 ± 2.69 pt above Ohmeda Biox 3700; one tracks functional, the other fractional SaO2: "a fundamental difference in the calibration algorithms" | OSM-3 ± HbF correction |
| 1994 | Marble, Burns, Cheung, Appl Opt 33:1279 | 3-D diffusion model predicts response changes of probes with different LED spectra | in vitro + in vivo |
| 1996 | Dassel et al., J Clin Monit 12:421 | newborn forehead reflectance: R/IR "virtually unchanged" for 0-80 mmHg probe pressure, "markedly increased" > 150 mmHg | 12 healthy newborns |
| 1996 | Rusch, Sankar, Scharf, Comput Biol Med 26:143 | FFT/DCT R estimators "as accurate without averaging as weighted-moving-average algorithms" | — |
| 1997 | Kästle et al. (HP), HP Journal 48(1):39 | "Volunteer study for sensor calibration" and neonatal sensor validation (not retrievable) | invasive volunteer study |
| 1997 | Mannheimer, Casciani, Fein, Nierlich (Nellcor), IEEE TBME 44:148 | 735/890 nm reads more accurately below 70 % than 660/900; stability best when the fractional path-length change is equal at both wavelengths | numerical model + animals |
| 1997 | Webster (ed.), Design of Pulse Oximeters, ch. Calibration | source of the textbook line `110 − 25R` (attribution SECOND-HAND via Kyriacou 2006) | — |
| 2000 | Nitzan et al., J Biomed Opt 5:155 | two adjacent IR wavelengths (767/811 nm) with equal path lengths: calibration-free formula; 17 males, no blood | — |
| 2000 | Zourabian et al., J Biomed Opt 5:391 | trans-abdominal fetal oximetry: optimal 670-720 / 825-925 nm; ratio-of-ratios equation with DPF terms (not seen) | — |
| 2004 | Zonios, Shankar, Iyer (Respironics), IEEE TBME 51:818 | "exact solution" as basis for a semi-empirical calibration at low saturation and variable probe geometry | fetal sheep, spiral probe |
| 2005 | Bickler, Feiner, Severinghaus, Anesthesiology 102:715 | pigmentation shifts the curve: at 60-70 % bias +3.56 ± 2.45 (dark) vs +0.37 ± 3.20 (light); per device dark−light 2.35 (Nonin), 3.38 (Novametrix), 4.30 (Nellcor) | 21 volunteers, OSM3 |
| 2005 | Cox & Fernandes, Respir Care 50:1517 | adult-derived curve has half the slope in cyanotic infants 53-86 % (table §3) | 21 children, 160 ABG |
| 2006 | Kyriacou, Physiol Meas 27:R1 | commercial curves are look-up tables; volunteers desaturated only to ≈ 75-80 %, shape below extrapolated; `110 − 25R` used by the City system | review |
| 2007 | Mannheimer, Anesth Analg 105:S10 | scattering is absorbed by "the empirical process that manufacturers use to calibrate the system"; off-label sites not covered | review |
| 2007 | Aoyagi et al., Anesth Analg 105:S53 | multiwavelength theory (Schuster radiative model); 3 wavelengths remove the tissue term, 5 the venous term | theory + full-range experiment |
| 2007 | Feiner, Severinghaus, Bickler, Anesth Analg 105:S18 | at 70-80 %: Masimo clip +2.61, disposable −1.58; Nellcor clip +2.59, disposable +3.6; Nonin clip −0.60, disposable +2.43; "up to 10 % differences among instruments in dark-skinned subjects at low SaO2" | 36 volunteers |
| 2008 | Stubán & Niwayama, Periodica Polytechnica EE 52:91 | `113.8 − 24.87·R` 86-100 %, linear vs quadratic differ by R² 0.0001 in that range; full-range table "non-linear, parabolic" | 9 subjects, 511 pairs, reference = another oximeter |
| 2008 | Kyriacou et al., Anesth Analg 107:905 | oesophageal reflectance in 4 neonates + 1 child: bias +0.3, LoA +1.7/−1.0 vs toe oximeter | pilot |
| 2011 | Johnston et al., Arch Dis Child F&N 96:F429 | the Masimo 87-90 % gap (§2) | 176 preterm infants |
| 2014 | Nitzan, Romem, Koppel, Med Devices 7:231; Nitzan et al., Sensors 14:7420 | rational empirical `(k1 − k2R)/(k3 − k4R)`; calibration-free two-IR formula (table §3); commercial calibration "ethically not below ≈ 80 %"; HbF max error 3 % theory / 4 % experiment | review; 15 males |
| 2014 | Ross, Newth, Khemani, Pediatrics 133:22 | where the adult curve fails in children: bias +6.6 (median 6, Arms 9.1) at SpO2 81-85 %; +1.5 (Arms 4.2) at 91-97 % | 225 ventilated children, 1980 pairs, CO-oximetry |
| 2017 | Verkruysse et al. (Philips), Anesth Analg 124:136 | camera forehead line `118.0 − 45.9R` (table §3); shallow sampling → steeper slope | 26 subjects, contact-oximeter reference |
| 2019 | Conn et al., JMIR mHealth 7:e12419 | thigh reflectance slopes −33 to −37 with subject-specific offsets | 2 desaturated + 11 validation subjects |
| 2019 | Chatterjee & Kyriacou, J Phys Conf Ser 1151:012005 | Monte Carlo simulated reflectance calibration curve (figure) | simulation |
| 2020 | Arsath et al. (IIT Madras), arXiv 2004.06301 | reflectance R-SpO2 linear per subject (r ≥ 0.9) but intercept and slope are subject- and site-specific (finger/wrist/forehead); "a generic R-value based calibration model… is an erroneous approach"; 5-point per-patient calibration MAE 1.81 % | 28 pulmonary patients, 60-100 %, Nellcor + ABG |
| 2023 | Elron et al., Sensors 23:1434 | cyanotic newborns (table §3); mechanism ℓ2/ℓ1 ∝ √(µa1/µa2): hypoxaemia raises red absorption, ratio rises, a fixed curve overestimates; "about 12 % at low SaO2 and small above 80 %" | 17 newborns, arterial |
| 2023 | Wu et al., J Biomed Opt 28:115002 | self-calibrated path-length ratio (table §3) | 9 freedivers, 23 arterial samples 41-100 % |
| 2023 | Gerboni et al. (Empatica), Front Digit Health 5:1258915 | wrist reflectance 660/940: "empirical calibration built from R and a Lambert-Beer model" + linear regression; Arms 2.4 % (2.2 in Fitzpatrick V-VI vs 2.5 I-IV) | 15 subjects, 373 pairs, 67-100 %, ABL90 |
| 2023 | Cao et al., IEEE EMBC | SNR-dependent bias in R from max/min estimation; scales with melanin via SNR | model |
| 2024 | Blaney, Sassaroli, Fantini, J Biomed Opt 29:S33313 | mBLL rational `(A + B·R)/(C + D·R)`; `110 − 25R` corresponds to a partial-path-length ratio ≈ 0.65 (SaO2 1.0-0.9) rising to ≈ 0.70 at lower SaO2; an idealised homogeneous model spans 0.50-1.00; linearisation exact only near R0 = 1 ↔ 85 % | theory with Prahl coefficients |
| 2024 | Blaney et al., J Biomed Opt 29:S33311 (dual-ratio) | melanin changes recovered SpO2 ≈ 1 % (single distance ≈ 0.5 % in vivo); heterogeneous pulsatile haemodynamics ≈ 10 % | MC + in vivo |
| 2024 | Al-Halawani, Qassem, Kyriacou, J Biomed Opt 29:S33305 | transmission MC lines by skin tone (table §3); dark skin needs an exponential-type correction (≈ ×1.8 mean R ratio); mismatch 2.1 % at 90 % before correction | simulation |
| 2024 | Narayana Swamy et al. (Nottingham), J Biomed Opt 29:S33308 | transmission (4.1 mm finger): SpO2-R curve unchanged by skin tone (p 0.84); reflectance: shifted at 1 and 2.5 mm separation (p ≈ 1e-4), not at 4.5 mm (p 0.97); red PI lower in dark skin → lower R → overestimation with a light-skin curve | 4-layer MC |
| 2024 | Quaresima, Ferrari, Scholkmann, J Biomed Opt 29:S33307 | history: HP 47201A 8-wavelength ear oximeter needed no calibration (1.7 % above 90 %, reads low below ≈ 65 %); Aoyagi 1974 pulsatile ratio removed the bloodless zero; calibration "determined empirically and depends on the device" | review |
| 2025 | Fong et al., Sci Data 12:570 — **OpenOximetry repository** (PhysioNet, restricted free access) | ISO-style desaturation plateaus 70-100 %, ≈ 20 min each, ABL90 arterial CO-oximetry, Monk + spectrophotometer skin colour, finger diameter, raw PPG 86 Hz for a subset (660/910 nm per Blaney 2026), not time-synchronised in v1.1; **R is not stored**, it must be computed from the raw PPG | 233 patients in cohort, 17 756 SaO2 samples from 218 (per Blaney 2026) |
| 2025 | Al-Halawani et al., Sensors 25:372 | reflectance MC: perfusion index at 660 nm 0.048 (light) → 0.022 (dark) at 70 %; RMSE vs transmittance algorithms 0.40 / 0.91 / 8.41 % light/moderate/dark | simulation |
| 2025 | Pan et al., Discover Applied Sciences 7:989 | skin-tone-specific curves (table §3) | 71 adults, 1699 ABG |
| 2025 | Pologe et al., PLoS One 20:e0333109 | laser oximeter error variance 3.54 vs 5.5 for two LED oximeters; LED spectral bandwidth claimed as root cause of pigmentation bias | 18 participants, arterial |
| 2026 | Atuar, Duadi, Nitzan, Fixler, Opt Lett 51:2424 + SPIE | path-length ratio 660/940 at the standard transmission position 1.25-1.45, varying with SaO2 60-100 %; 760/840 1.05-1.12; ≤ 1.05 at the iso-pathlength angle, where the curve "overlaps closely with the theoretical model" | finger MC |
| 2026 | Blaney & Fantini, J Biomed Opt 31:070501 | with broad-linewidth LEDs the curve depends on melanin ("spectral coloring"); not with monochromatic laser diodes | hybrid diffusion/MC |
| 2026 | Blaney, Frias, Durbha, Fantini, Koomson, arXiv 2609.30122 | the open blood-referenced fit (table §3) | OpenOximetry, 98 patients, 2991 draws |

Not retrievable this search (coefficients "not seen"): Webster 1997 (book), Severinghaus & Kelleher 1992, Fine &
Weinreb 1995, Zourabian 2000 equations, López-Silva 2003, Aoyagi 2003, HP Journal 1997, Chan 2013, Lee 2016,
Tamura 2019, AN 6845 (timeouts), Apple white paper (403).

---

## 5. Factors that shift the curve, with magnitudes

### 5.1 Optical and device factors

| Factor | Direction | Magnitude | Conditions | Source |
|---|---|---|---|---|
| Red LED centre wavelength, unit to unit | error grows with (1 − SaO2); ≈ 0 at ≥ 85 %; sign follows the shift | tolerance "±2-10 nm" at the same drive current (probe-calibration patent); Epitex 660 nm LED spec 650-670 nm. Beer-Lambert model: 8 nm shift → 2.5 pt at 50 % SaO2 (≈ 0.3 pt/nm), "little loss of accuracy" at ≥ 85 %. Reflectance MC 2026: IR 940 → 949.5 nm raised RMSE by +1.04 ± 0.20; worst pair 652.5/949.5 nm RMSE 2.64 vs 1.32 | adult finger model | de Kock 1991; bioRxiv 2026; US 4,621,643 |
| LED wavelength drift with temperature | red-shift | 0.11 nm/°C (660), 0.16 nm/°C (950): 5.5 / 7.8 nm over 0-50 °C; effect on SpO2 "negligible" | bench | Reynolds 1991 BJA |
| LED drive current / intensity (AGC) | red-shift with current → error only at low SaO2 | "+8 nm as its intensity is increased ten-fold" → 2.5 pt at 50 % SaO2, little at ≥ 85 % | bench + model | de Kock 1991 |
| LED spectral width, secondary peaks, detector responsivity slope | shifts the effective wavelength; error mostly at low SaO2; makes the curve melanin-dependent | MC: monochromatic RMSE 1.32 vs LED spectrum (FWHM 17/42 nm) 2.10 (+59 %). Tsiakaka 2020: generic 660/20 nm + 940/50 nm LEDs with `110 − 25R`: deviation up to 8 pt in 90-100 % for the worst photodiode, ≈ 7 pt generic. Blaney 2026: residual melanin slope +2.8 pt per unit melanin fraction with the linear fit → +0.1 after linewidth correction (not statistically resolved) | models | bioRxiv 2026; Tsiakaka 2020; Blaney & Fantini 2026 |
| Wavelength bins (RCAL) | compensates the previous rows | patent: "if the frequency varies the results of the instrument can be inaccurate"; red "of primary concern" because the Hb extinction slope is steep there; no per-bin error number | — | US 4,621,643; US 8,224,412 |
| Transmission vs reflectance geometry | reflectance more sensitive to melanin, site and spacing | transmission: "no measurable difference in SpO2… between the two skin types" (p 0.84); reflectance curves differ (p 6e-5), dark skin reads higher at the same R. Newborn head reflectance: "up to 13.4 % in oxygen saturation between the forehead and the occipital area". FDA typical Arms 3.0 transmission vs 3.5 reflectance/ear | 4-layer MC; 7 term newborns | Narayana Swamy 2024; Dassel 1997; FDA 2013 |
| Emitter-detector spacing, path-length ratio, scattering | slope changes with spacing; path-length ratio drifts with SaO2 → over-reading in hypoxaemia | reflectance MC 667/941: intercept "practically invariant", slope "changes greatly" within 1-3.5 mm, recommend > 3.5 mm. Nellcor sheep: good performance at ≥ 10 mm separation; 660 nm at 14 mm had different head vs neck calibrations. Path-length ratio 660/940: 1.25-1.45 across 60-100 % SaO2 (760/840: 1.05-1.12). `110 − 25R` ↔ ratio 0.65 → 0.70 as SaO2 falls. Heterogeneous pulsatile haemodynamics ≈ 10 % in simulation. Cyanotic newborns: SD 6.5 (660/900) vs 3.6 (761/820) | MC, sheep, neonates | Kirillin 2025; US 5,782,237; Atuar 2026; Blaney 2024; Elron 2023 |
| Optical shunt / penumbra (badly fitting sensor) | under-reads at high SaO2, over-reads at low; slope of SpO2 vs SaO2 decreases | 12 volunteers 100 → 70 %: "one oximeter underestimated at all SaO2 values, three others underestimated at high SaO2 and overestimated at low SaO2… could indicate that a patient was only mildly hypoxemic when hypoxemia was profound"; "calibration curves changed greatly". Penumbra case report: direction only | adults | Barker 1993; Kelleher & Ruff 1989; ISO DD.2.3.2 h) opaque cover |
| Ambient light | mostly failures / erroneous values | under an OR light: failure rates "approximately 5 % to 50 % depending on the oximeter and source"; magnitude in points not found | 8 volunteers, 5 oximeters | Trivedi 1997 |
| R estimator (peak-valley / log vs derivative-regression vs FFT) and DC definition | changes R noise and bias; different slope per method | no head-to-head found. FFT/DCT "as accurate without averaging as WMA"; derivative + regression claimed better than ln(peak/valley) (patent, no number). Our register: R-METHOD-0/1 fits gave slopes 21-31 vs 39 with R-METHOD-2 on the same probe | — | Rusch 1996; US 5,577,500; `docs/spo2_r_curves.md` |
| Averaging time | hides desaturations, not the curve | 3 → 16 s: desaturation count ×0.18 (preterm) / ×0.28 (children), duration ×3.3 / ×1.9 | 15 preterm, 49 children | Vagedes 2019 |

### 5.2 Physiological and subject factors

| Factor | Direction | Magnitude | Conditions | Source |
|---|---|---|---|---|
| Skin pigmentation, laboratory | over-reading in dark skin, "approximately in proportion to desaturation" | 60-70 %: dark +3.56 ± 2.45 vs light +0.37 ± 3.20; dark−light 2.35 (Nonin), 3.38 (Novametrix), 4.30 (Nellcor). 70-80 %: Masimo clip +2.61 / disposable −1.58, Nellcor clip +2.59 / disposable +3.6, Nonin clip −0.60 / disposable +2.43; "up to 10 %" between instruments in dark skin at low SaO2. 11 fingertip devices: 5/11 Arms > 3 %, 9/11 worse in the darkest ITA group. 146 adults, 9763 pairs: missed hypoxaemia at PI < 1 %: light 1.1 %, medium 8.2 %, dark 21.1 % | healthy adults, finger | Bickler 2005; Feiner 2007; Leeb 2024; Gudelunas 2024 |
| Skin pigmentation, clinical | over-reading | occult hypoxaemia 11.7 % Black vs 3.6 % White (17 vs 6.2 % multicentre); over-read vs White 1.7 (Asian), 1.2 (Black), 1.1 (Hispanic) pt; preterm < 32 wk: bias +1.73 (Black) vs +0.72 (White), occult hypoxaemia 9.2 vs 7.7 % | ICU; NICU | Sjoding 2020; Fawzy 2022; Vesoulis 2021 |
| Skin pigmentation, physics | transmission: no effect on R; reflectance: red AC attenuated more than red DC → R lower → SpO2 higher; broad LEDs: melanin enters via spectral colouring | transmission MC p 0.84; reflectance MC bias −1.8 ± 0.1 (2.55 % melanin) to +3.9 ± 1.2 pt (30.5 % at 70 %); transmission MC with melanin-filtered LED spectra: bias 1.7 % light vs 9.3 % dark; dual-ratio in vivo ≈ 0.5-1 % | models | Narayana Swamy 2024; bioRxiv 2026; Al-Halawani 2024; Blaney 2024/2026 |
| Regulatory tolerance | — | ISO 2026: differential bias (ITA −50° vs +50°, 80-90 %) ≤ 2.5 %; FDA 2025 draft: < 3.5 pt (70-85 %), < 1.5 pt (85-100 %) between Monk groups | — | ISO 201.12.1.101.2; FDA 2025 |
| Low perfusion / low PI | positive bias plus dropouts; failure below a systolic threshold | PI 1.0-1.5, 0.5-1.0, < 0.5 % all related to bias (p < 1e-5); in light skin only PI predicted bias. Stationary RMSE 1.8 % vs > 3 % with motion (3/4 devices). Oximeters fail at radial systolic 25-47 mmHg (hand elevation 25, brachial clamp 37-47, norepinephrine 58 mmHg). Post-bypass: only 2/20 oximeters within 4 pt in 95 % of readings. Industry: Nellcor 0.03 % modulation floor; Masimo PI < 0.25 = low perfusion; Philips "ideally PI > 1.0" | adults | Gudelunas 2024; Louie 2018; Severinghaus & Spellman 1990; Clayton 1991 |
| Venous pulsation / congestion | under-reading (venous blood enters the AC term) | bias −18 pt with marked central venous pulsation, 0 after IABP; severe tricuspid regurgitation +2 to −11 pt; septic low SVR "small (1.4 %) but significant" under-reading; probe pressure 60-120 mmHg reduces R/IR variability (reflectance forehead) | adults | Sami 1991; Stewart & Rowbottom 1991; Secker & Spiers 1997; Dassel 1995 |
| Motion | errors both ways, dropouts, worse at low SaO2 | time within 7 pt of control: 76 % (N-200), 87 % (N-3000), 99 % (Masimo SET prototype); SpO2 specificity 93-97 (Masimo) vs 67-77 (N-600) vs 82-83 % (TruSat) | volunteers | Barker & Shah 1997; Shah 2012; Louie 2018 |
| Anaemia / Hb concentration | under-reading at low SaO2; none at high | at SaO2 54.5 %: bias "from 0 at Hb > 14 g/dl to about −14 % at 8 < Hb < 9 g/dl"; extra anaemic bias +0.13 (98.5 %), −1.31 (87.5), −2.71 (75.1), −5.18 (61.3), −9.95 pt (53.6 %); "zero at 97 % SaO2… evident below 75 %". Dogs: accurate to Hct 10 %, below −5.4 ± 18.8 % | volunteer Hb 8; dogs | Severinghaus & Koh 1990; Lee 1991 |
| COHb | over-reading: "SpO2 is approximately the sum of COHb and O2Hb" | dogs COHb 0-75 %: oximeters read > 90 % while O2Hb fell below 30 %; normal clinical COHb 1.3-1.8 % ⇒ functional-vs-fractional offset of that order | dogs; adults | Barker & Tremper 1987; Veyckemans 1989 |
| MetHb | pushes SpO2 toward ≈ 85 % | over-estimation proportional to MetHb up to ≈ 35 %, then plateau 84-86 %; with MetHb fixed, dSpO2/dSaO2 only 0.16-0.32 | dogs, 3 oximeters | Barker 1989 |
| Fetal haemoglobin | spectra nearly identical; neonatal biases both ways, not attributable to HbF | review of 10 studies: bias −3.6 (SD 2.3) to +4.2 (SD 2.4); under-estimation 2.8-3.6 % with HbF > 50 % (Jennis 1987) vs +4.2 (HbF < 50 %) / +0.9 (> 50 %) (Praud 1989) vs no influence (Durand 1986, Ramanathan 1987, Rajadurai 1992); Masimo adds +1 % to the neonatal Arms claim | neonates 24-42 wk | Harris 1988; Pritišanac 2021; K092838 |
| Bilirubin | no direct effect (apparent over-reading is the raised COHb of haem catabolism) | 29 icteric patients 2.3-84.3 mg/dl: raw bias 2.9 ± 2.2 vs 1.7 ± 2.7; after COHb correction limits identical | adults | Veyckemans 1989 |
| IV dyes | under-reading (absorb near 660 nm) | methylene blue "mean nadir of 65 %"; dogs: MB 1-5 mg/kg dose-dependent decreases for up to 30 min (MetHb 19.9 % after 5 mg/kg), ICG up to 10 min, fluorescein none; effect MB > ICG > indigo carmine | 5 volunteers; dogs | Scheller 1986; Sidi 1987 |
| Nail polish, henna | under-reading or no reading | ICU (SaO2 − SpO2): black +1.6 ± 3.0, purple +1.2 ± 2.6, dark blue +1.1 ± 3.5, others +0.2-0.9; sensor rotated 90° 2.8 → 1.3 (n.s.); black polish failure rate 88 % in one study; black henna "gave no reading", red henna none | adults | Coté 1988; Hinkelbein 2007; SR 2023; Al-Majed 1994 |
| Site / probe type | site-specific offsets, largest in reflectance and at low SaO2 | at SaO2 ≈ 56 %: same maker, different sites differ by several points (Kontron finger 5.9 / ear 5.8 / forehead 7.1; Radiometer finger −21.2 / ear −9.6); disposable vs clip 2-4 pt at 70-80 %; newborn head reflectance up to 13.4 pt between sites; nose/forehead "performed poorly" in poor perfusion; critically ill: bias forehead −1.39 vs digits −2.61/−3.84; newborn < 4 h: right hand 95.7, foot 94.9 % (ductal physiology, not calibration) | various | Severinghaus 1989; Feiner 2007; Dassel 1997; Clayton 1991; Bucher 2010 |
| Tissue temperature / vasoconstriction | local warming lowered SpO2, cooling raised it (venous-shunt mechanism); vasoconstriction mainly causes failure | 15 volunteers, hands at 15 and 45 °C: significant both ways, magnitude not in abstract; norepinephrine raised the failure threshold to systolic 58 mmHg | adults | Schramm 1997; Severinghaus & Spellman 1990 |
| Oedema | direction known (non-pulsatile absorber/scatterer lowers PI, lengthens path); **magnitude not found** | — | — | Mannheimer 2007 (qualitative) |
| Sickle cell disease | over-reads fractional HbO2, slightly under-reads functional SaO2 | +3.4 pt vs fractional, −1.1 pt vs functional; p50 28-38 mmHg | 22 pairs in crisis | Ortiz 1999 |
| Cyanotic CHD / children at low SaO2 | over-reading below ≈ 90 %, growing as SaO2 falls | 258 samples: SpO2 over-reads 5.3 (Masimo Blue), 7.4 (LNCS), 7.4 pt (Nellcor), LoA ≈ ±15; "similarly poor at SaO2 < 60 %"; 225 ventilated children: +6.6 pt at SpO2 81-85 %, +1.5 at 91-97 % | children | Kim 2019; Ross 2014 |
| Neonates vs adults | over-reading, large scatter; ISO criteria fail below 91 % | NICU 27 237 pairs: "SpO2 overestimated SaO2 by 2.9 ± 5.8 %"; 20.9 % of in-target SpO2 had SaO2 below target; "for SpO2 below 91 %, ISO quality criteria were no longer fulfilled". Preterm Arms by band: 7.9 (90-100), 10.8 (80-89), 16.9 (70-79), 27.9 % (< 70). 1990 Nellcor N-200 in 22 preterms: `SpO2 = 0.75·SaO2 + 24.4` | preterm/term | Wackernagel 2020; Vesoulis 2021; PubMed 1372809 |
| Low saturation range (< 80 %) | instrument-specific; most common "underestimation of saturation and failing precision"; slopes deviate from 1 | 14 makers at O2Hb 55.8 %: from 3.3 (Physio-Control ear) to −21.2 (Ohmeda, Radiometer finger), Nellcor −15.1; 735/890 nm better below 70 % | adults | Severinghaus 1989; Mannheimer 1997 |

### 5.3 Calibration-study factors (errors built into the curve itself)

| Factor | Effect | Magnitude / requirement | Source |
|---|---|---|---|
| Reference definition | SpO2 must be calibrated to **functional** SaO2 (CO-oximeter); fractional differs by COHb + MetHb | ISO 2026: "shall be indicated as functional oxygen saturation"; CO-oximeter 1 % (1 SD) or better, 0.5 % for a < 2 % claim; PaO2-derived SaO2 "not appropriate". Gap in normal adults 1.3-1.8 pt (COHb); in sickle cell the two references differed by 4.5 pt; Thilo 1993: two brands differed by 1.6 pt in neonates for this reason | ISO; Veyckemans 1989; Ortiz 1999; Thilo 1993 |
| Subjects, pigmentation mix, data distribution | sets the Arms confidence and the detectability of differential bias | FDA 2013: ≥ 10 subjects, ≥ 200 points, ≥ 2 dark or 15 %; ISO 2026: ≥ 24 participants, 20 ± 4 pairs, ≈ 1/3 per decade, ≥ 90 % with a pair < 85 %, ≥ 33 % each sex; FDA 2025 draft: ≥ 150 participants, three Monk groups ≥ 25 % each | FDA 2013; ISO; FDA 2025 |
| Plateau stability and timing | unstable plateaus mismatch SaO2 and SpO2 through the delay chain | ≥ 60 s after an FiO2 change, samples ≥ 20 s apart, readings stable ≥ 30 s; lab practice 2-3 min plateaus (Bickler/Feiner), 30 s (Severinghaus 1989), ≈ 20 min per desaturation (OpenOximetry) | ISO DD.2.3.2 |
| Accuracy metric | Arms hides saturation-dependent bias | Arms ≤ 3.0 (70-100), sub-ranges disclosed; "as saturation decreases, local bias can be amplified"; Arms "represents the best-case scenario" | ISO 201.12.1.101.1 |
| Another oximeter as transfer standard | adds its own error; development only | Annex JJ: Arms ≤ 2.0 vs CO-oximeter on ≥ 48 participants; using one "increases the RMS by about 0,28"; "not acceptable for final verification". Our Mindray N17 and home oximeters are not formal transfer standards | ISO Annex JJ |
| Fit range | a curve fitted in a narrow or high range extrapolates wrongly downward | Stubán 86-100 %: linear vs quadratic indistinguishable there, "parabolic" full range; our adult-finger and MS100 fits disagree in slope with the pooled neonatal fit for the same reason (`docs/spo2_r_curves.md`) | Stubán 2008; register |

---

## 6. What this means for PulseNest (665/905 nm, Medle ST-S0163, neonatal foot transmission)

- No table can be transplanted. Even the four "manufacturer-supplied" simulator curves are reproductions of
  someone else's firmware for someone else's LEDs; with our 665 nm red (vs 660) and 905 nm IR the bins differ.
  The form that the physics and the one open blood-referenced data set both support is the mBLL rational with
  a fitted path-length ratio and an offset, linearised near 85 %; a line is adequate for 85-100 % and wrong below.
- The things we can control that move the curve by ≥ 2 pt: LED current (AGC changes the red wavelength: 2.5 pt
  at 50 % SaO2 per decade of current), sensor fit on a small foot (optical shunt flattens the slope), the R
  estimator (our three methods gave slopes 21-39 on the same probe), the DC definition and the fit range.
- The things we cannot control but must document per session: perfusion (PI), pigmentation (Monk, recorded
  per baby since 2026-10-16), site (pre/post-ductal), Hb and dyshaemoglobins when a blood gas exists, oedema.
- OpenOximetry is the only public route to a CO-oximetry-referenced curve for our estimator: compute R-METHOD-2
  from its raw 660/910 nm PPG and fit; the result would still be an adult finger curve, i.e. what every
  manufacturer ships for neonates.
- For the next hospital campaign: capture the monitor's pulse rate and its averaging, the probe suffix/lot, and
  any clinical arterial gas with its CO-oximeter functional SaO2 (not the PaO2-derived value).

---

## 7. Sources

Manufacturers and patents: US 4,621,643 · US 6,801,797 · US 5,421,329 · US 7,376,454 · US 12,076,141 · US 8,224,412 (Nellcor/Covidien) · US 7,274,955 · US 7,428,432 · US 8,682,407 (Masimo) · US 5,267,562 (Nihon Kohden) · US 5,934,277 (Datex-Ohmeda) · US 5,782,237 · US 5,577,500 · Masimo Rad-57 manual LAB-9204A (techdocs.masimo.com) · Masimo Blue PLM-11604A · Philips FAST application note 2024 (documents.philips.com/assets/20240123/4d8a39e19cdc484ab75bb10000a02b35.pdf) · 510(k) K062455, K123581, K093881, K132696, K131021, K070732, K962156, K083557, K183277, K081937, K082641, K090671, K092838 (fda.innolitics.com / accessdata.fda.gov) · Nellcor OxiMax tech note (ece.mcmaster.ca) · Johnston 2011 PMC3195299 · Cox 2005 (masimo.fr clinical-evidence PDF) · Medtronic low-perfusion page.

Simulators: Fluke ProSim 8 manual Rev. 3 (flukebiomedical.com/sites/default/files/resources/ProSim8_umeng0300.pdf) · Ansur ProSim 6/8 manual · Fluke white paper 6001759 · Index 2 datasheet · Pronk OxSim Flex manual Rev. 01-29-19 (mtk-biomed.com mirror) · Contec/Gima M54600EN.pdf (local) · Viamed DL-3000 instructions.

Chip vendors: TI TIDU475, SLAA655, SLAU480, E2E thread 1279146 · SparkFun MAX3010x spo2_algorithm.h/.cpp · MAX30102_by_RF · Analog Devices AN 6845 and ADPD article (not fetched) · OSRAM SFH 7050 note (rs-online mirror).

Regulatory: FDA 2013 guidance (fda.gov/media/72470) · FDA 2025 draft (fda.gov/media/184896) · ISO 80601-2-61:2026 (`docs/ISO_80601-2-61-2026.pdf`, doc pages 27-32, 100-105, 130-134; PDF page = doc page + 12).

Literature (PubMed IDs where used): Yoshiya 1980 (7382587) · Pologe 1987 (3323061) · Wukitsch 1988 (3057122) · Harris 1988 (2463343) · Mendelson & Ochs 1988 (3192229) · Severinghaus 1989 (2723709) · Mendelson & Kent 1989 (2474489) · Schmitt 1991 (1774081) · Reynolds 1991 (1751282) · de Kock 1991 (1941984) · Dassel 1992 (1561013) · Reynolds 1992 (1297018) · de Kock & Tarassenko 1993 (8412383) · Thilo 1993 (7681875) · Marble 1994 (20862152) · Dassel 1995/1996/1997 (7560225, 8982906, 9307887) · Rusch 1996 (8904288) · Mannheimer 1997 (9216128) · Barker 1993 (8342837) · Kelleher & Ruff 1989 (2817477) · Trivedi 1997 (9172022) · Nitzan 2000 (10938779) · Zourabian 2000 (11092427) · Zonios 2004 (15132508) · Bickler 2005 (15791098) · Kyriacou 2006 (City eprint 14690) · Mannheimer 2007 (18048891) · Aoyagi 2007 (18048900) · Feiner 2007 (18048893) · Stubán 2008 (pp.bme.hu/ee/article/download/859/478) · Kyriacou 2008 (18713903) · Nitzan 2014 review (PMC4099100) · Nitzan 2014 Sensors (PMC4029673) · Ross 2014 (24344108) · Verkruysse 2017 (PMC5145250) · Conn 2019 (PMC6356186) · Chatterjee 2019 (City eprint 21891) · Arsath 2020 (arXiv 2004.06301) · Vagedes 2019 (31240765) · Sjoding 2020 (NEJMc2029240) · Vesoulis 2021 (PMC8508473) · Pritišanac 2021 (PMC8145233) · Fawzy 2022 (JAMA IM 2792653) · Elron 2023 (PMC9921559) · Wu 2023 (PMC10704087) · Gerboni 2023 (fdgth.2023.1258915) · Gudelunas 2024 (38109495) · Leeb 2024 (EBioMedicine, DOAJ) · Blaney 2024 (PMC12238718; JBO S33311) · Al-Halawani 2024 (PMC11321364) · Narayana Swamy 2024 (PMC11358849) · Saiko 2024 (PMC11351970) · Quaresima 2024 (PMC11330276) · Fong 2025 (Sci Data 12:570; PhysioNet openox-repo) · Al-Halawani 2025 (City eprint 34569) · Pan 2025 (s42452-025-07129-4) · Pologe 2025 (journal.pone.0333109) · Kirillin 2025 (journals.ioffe.ru/articles/63184) · Atuar 2026 (doi 10.1364/ol.588131) · Blaney & Fantini 2026 (JBO 31:070501) · Blaney 2026 (arXiv 2609.30122) · bioRxiv 2026.04.20.719559 · Tsiakaka 2020 (PMC7309008) · Louie 2018 (29200008) · Severinghaus & Spellman 1990 (2393126) · Clayton 1991 (1996757, 2024056) · Sami 1991 (1812874) · Stewart 1991 (1887977) · Secker 1997 (9059094) · Barker & Shah 1997 (9009926) · Shah 2012 (22626683) · Severinghaus & Koh 1990 (2352007) · Lee 1991 (2064035) · Barker & Tremper 1987 (3578881) · Barker 1989 (2912291) · Veyckemans 1989 (2912292) · Scheller 1986 (3777490) · Sidi 1987 (3123569) · Coté 1988 (3382042) · Hinkelbein 2007 (17098348) · nail-polish SR 2023 (PMC10468177) · Al-Majed 1994 (8165737) · forehead vs digit (PMC8796114) · Bucher 2010 (PMC2879243) · Schramm 1997 (9127780) · Ortiz 1999 (9927356) · Kim 2019 (30938906) · Wackernagel 2020 (32043645) · Jubran & Tobin 1990 (2347228) · Nellcor N-200 preterm 1990 (1372809).
