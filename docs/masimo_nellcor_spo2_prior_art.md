# Masimo SET and Nellcor OxiMax: algorithm and R-curve prior art for incunest_afe4490

Search date 2026-10-27, at Alex's request: an extensive search of Masimo SET and Nellcor OxiMax documentation,
patents and publications that can help our SpO2 algorithms and our R-curve. Produced in an analysis session; nothing
in the repositories was changed. Companion documents: `docs/r_curve_calibration_survey.md` (2026-10-26, curve forms,
calibration methods, factors that move the curve; not repeated here), `docs/spo2_r_curves.md` (our own fits),
`docs/ppg_neonatal_manufacturer_references.md`, and the library rationale §9 (R method), §12 (averaging),
§17 (artefact gate) and §18 (one curve or two).

Copied into `docs/` on 2026-10-27 by the development session with Alex's approval. One figure was corrected on
the way: §0.5 quoted the neonatal PI as 2.3–3.2 % with the SQI ramp mostly at 1, the estimate of that morning;
the measurement of the same day on the lib 0.108 replays (conversation log, session 2026-10-27 (2)) is given
instead.

Tags. **VERIFIED**: read in the primary source during this search (patent full text, manual, paper); the key
patent quotes and the two third-party figures the recommendations rest on were re-checked against the
downloaded text. **SECOND-HAND**: reported by another source.
**CLAIM**: manufacturer marketing (Masimo white papers, Medtronic white paper). **DERIVED**: our own algebra or
simulation. Patent status is the Google Patents legal-status line on 2026-10-27, not a legal opinion. US patents
filed before October 2006 have expired, so almost everything below can be implemented freely; the exceptions are
listed in §7.

---

## 0. Conclusions for incunest_afe4490

1. **Our estimator is Nellcor's, and it is also Masimo's DST with a one-coefficient canceller.** Nellcor fits red on
   IR sample-to-sample differences through the origin (US 5,351,685, Potratz 1991: "Because the ratio of the
   derivative of the red and infrared signals is a straight line, a linear regression may be performed"; US
   6,411,833 eq. 8). With a scalar canceller, Masimo's saturation-transform power curve is a single peak centred on
   our R, whose width is set by our correlation r: it carries exactly our (R, r) pair (§2.1). Everything Masimo adds
   comes from a 6-cell least-squares-lattice canceller that exploits spectral differences, and Masimo's own patent
   says it fails "in the unlikely event that the spectral content" of signal and noise "are similar".
2. **The r >= 0.8 gate is blind to venous or motion contamination by construction.** For two uncorrelated sources
   with positive ratios, r cannot fall below `2·sqrt(ra·rv)/(ra + rv)`: 0.954 for arterial 95 % plus venous 70 %,
   whatever the motion power, while the SpO2 error at equal power is −12.5 points (§2.2). Isolated motion artefact
   measured on a TI AFE4400 board gave r = 0.93–0.97 (Clarke 2015). This explains SUBJ10 (r 0.96, −16 points).
   The gate still catches uncorrelated noise; it cannot catch coherent motion.
3. **The cheapest real separation uses sums we already compute.** (a) Masimo's decorrelation closed form
   (US 5,632,272, expired 2014), solved over six 1 s sub-windows of our 100 ms block sums: in simulation, motion in
   bursts is read within ±3 points in 87–100 % of windows against 0–4 % for the regression; it cannot work when
   the motion is stationary over the window (§2.3). (b) R measured only on the pulse-harmonic bins (Masimo FST and
   SST, Nellcor's harmonic filter, Philips FAST): in exercising adults a heart-rate comb in front of the plain ratio
   matched the DST in 7 of 8 stages at 1/28 of its computing time (Alkhoury 2021). Both must be checked on our
   captures before anything goes into the library.
4. **Nellcor's expired patents give a complete, numeric recipe for averaging and signal quality** (§1.1): a Kalman
   filter on saturation (process noise 1.3 points/s, measurement noise from the regression residual in a centred
   1 s window plus a hardware floor, a second filter limiting the slope change to 0.2 points/s²), ensemble-averaging
   weights with explicit formulas, quality metrics (derivative skewness, red-IR uncorrelation, ratio-of-ratios
   variance over 3 s and 9 s, pulse amplitude against a 60 s history, period variability, harmonicity), display
   states UPDATE / HOLD / CLEAR with a 40 s age limit, and dynamic averaging that escalates from 7 s to pulse
   search at 20 s and pulse timeout at 40 s.
5. **Masimo's lesson is architectural.** Several estimators run in parallel, each with its own confidence, and a
   confidence-based arbitrator picks the output; signal confidence (Signal IQ) is kept apart from perfusion (PI).
   Our SQI is a PI ramp, so it measures signal strength, not trust. In current peak-to-peak units the median PI is
   1.6 % in SUBJ08 (two thirds of its samples under the fleet viewer's 0.9 threshold, 28 % at or above the
   ramp's 2.0 %), 3.2 % in SUBJ09 and 2.8 % in the 30-week preterm (lib 0.108 replays, 2026-10-27), so the ramp
   binds on a normal term neonate, while PI does not see artefact (a PI limit of 10 % kept 76 % of SUBJ10's
   moving windows on 20-oct). Masimo's model-conformity metrics (pulse
   density, harmonic energy ratio, canceller integrity) and Nellcor's metrics are the candidates to add to the
   measurement planned on 27-oct (Spearman's ρ of |SpO2 − reference| against PI, r and HR3_SQI); all expired.
6. **R-curve: neither maker ships a neonatal curve, and neither publishes numbers.** Both calibrate on adult
   volunteers and check neonates on small sets (Nellcor MAX-N 2.5 % on 42 neonates; Masimo 2.9 % on 16). Nellcor's
   neonatal mode only changes alarm limits. Both encode per-sensor curves: Nellcor as a base curve plus a correction
   `a + b·R + c·R²` (US 5,645,059), Masimo as a coding resistor naming the probe type. Masimo adds a bounded
   per-patient additive offset ("in vivo adjustment", ±6 points, reset when the sensor comes off). Our neonatal
   default, fitted against the Mindray N17 in a NICU, is therefore atypical: it transfers the N17's own neonatal
   bias, for which no peer-reviewed measurement exists.
7. **Our 2.7-point neonatal vs adult-finger offset has three documented causes of the right sign and size:**
   reference bias (commercial neonatal SpO2 reads about 2 points above SaO2 at 85–95 %, Rosychuk 2012; Nellcor reads
   up to 3 points above Masimo below 90 %), probe site (sole vs toe 1.3 points; pre- vs post-ductal ≥ 2 points in
   28 % of extremely preterm infants), and venous pulsation in warm tissue (warm digits read up to 3 points lower,
   Schramm 1997), which raises R as we observe. A DST-type reference monitor would also read above a regression on
   the same blood whenever venous pulsation is present, because it reports the highest-saturation component.
8. **The clinical evidence sets the cost function.** Aggressive suppression costs missed events (one new-generation
   Nellcor missed 69 % of bradycardias in preterm infants, Bohnhorst 2000). Data availability changes care (dropout
   3 % vs 24 %, Kästle 2000; faster weaning, Durbin 2002). Long averaging hides brief deep events, while a short
   window plus an explicit alarm delay cut alarms by 67 % (McClure 2016). Only hypoxaemic episodes of one minute or
   more predicted outcome (Poets 2015). Our v0.110 gate withholds without holding, so the numbers to track are
   withheld time, recovery time and missed events, not frozen values.

---

## 1. What each maker does, block by block (all VERIFIED in the patents and manuals unless tagged)

### 1.1 Nellcor / Covidien / Medtronic (Oxismart, OxiMax N-395 → N-600x → PM1000N)

| Block | Mechanism and numbers | Source, status |
|---|---|---|
| Pre-processing | ln of each channel; IIR band-pass, high-pass 0.5 Hz, low-pass roll-off 10–20 Hz; each pulse normalised to a similar amplitude ("samples exhibiting large amounts of noise are down weighted"); derivative ("whitening"). N-600x: derivative, fixed low-pass, divide by DC "to preserve the ratio" | US 5,853,364 / 6,411,833 (expired 2016); US 7,039,538 (expired 2024) |
| R estimator | slope of red-on-IR differences through the origin: `x = ΔI_IR·I_red`, `y = ΔI_red·I_IR`, "slope of y versus x will give R" | 6,411,833 eq. 8; 5,351,685 (expired) |
| Outlier rejection | points whose instantaneous ratio implies SpO2 < 0 or > 100 % are dropped before averaging | 5,853,364 |
| Kalman on saturation | `S_k = S_(k−1) + nQ`, √Q = 1.3 points/s; measurement noise = residual variance of `v − u·S` in a centred window ("A one second window is preferred") plus a hardware floor; smaller parts of a pulse weigh less; first value from classic least squares. A second Kalman on dSat/dt with nQ = 0.2 points/s². "if saturation changes by 10 points in two seconds ... it must be due to measurement noise" | 5,853,364 family (expired 2016–2021) |
| Two paths and arbitration | one path on the raw band-passed data, one on harmonic-comb-filtered, cardiac-gated averaged pulses; confidence at 100 % SpO2: above 95 % if `0.13·Variance + 0.053·Age < 1` (Variance in points, Age in s); the path at least 10 % more confident wins, otherwise interpolate; output age pulled back to 35 s when one path allows it | 5,853,364; 7,302,284 / 7,315,753 / 7,336,983 (Nellcor, expired) |
| Harmonic content | typical pulse energy: 1st harmonic 82.8 %, 2nd 14.4 %, 3rd 2.1 %, 4th 0.5 %; "some patients have nearly half the energy of their pulses contained in the second harmonic" | 5,853,364 Table 1 |
| Ensemble averaging (N-600x) | per sample `z_i = zprev_i + w·(x_t − zprev_i)`, zprev one pulse earlier, on DC-normalised derivatives with the same w on both channels; trigger = ECG R wave, else the optical period; cleared after more than 5 s without triggers, re-phased across shorter interruptions (gain or LED changes); four-sample crossfade; 1 s delay; buffer = one 20 BPM pulse + 10 % | 7,039,538 / 7,209,774 (expired) |
| Ensemble weight | `x = max(Short_RoR_Var, PQ_RoR_Var/1.5)·max(LongTerm_Amp_Ratio, 1)`; `w_RoR = 0.5·0.05/max(0.05, x)`; arrhythmia floor `0.05 + 0.5·bound((Period_Var − 0.1·Short_RoR_Var − 0.09)/0.16, 0, 1)`; `w = min(max(w_RoR, floor)·(1 + Pulse_Qual), 1)`; default 0.5; w = 1 means no averaging | 7,194,293 (expired) |
| Response modes | target age 3 s (Fast) and 5 s (Normal); manual: "responds to changes ... within five (5) to seven (7) seconds" (Normal), 2–4 s (Fast); neonate default Normal | 7,039,538; PM100N manual |
| Dynamic averaging | extended beyond 7 s under low perfusion, artefact, ambient light or interference; above 20 s pulse search (values still updated every second); above 25 s a low-priority "Extended Update"; 40 s (SpO2) or 50 s (pulse rate) pulse timeout, SpO2 shown as 0 | PM1000N service manual 2013; PM10N |
| Quality metrics | derivative skewness (pulse −1 to −2, motion near 0); uncorrelation `sqrt(1 − r²)`; ratio-of-ratios variance over 3 s and 9 s; long-term pulse amplitude ratio against a history of about 60 s (above 1 = motion); short-term amplitude ratio; period variability; pulse-qualification score; harmonicity; Overlap, PathLength and fall/rise time with a lumped SQ and an integral posting rule | 7,194,293; 7,006,856; 6,035,223 (all expired) |
| Per-pulse motion test | ratio of the derivative's positive to negative peak: 1 to 1.4 for pulses, about 1 for motion; a threshold of 1.4 "reject[s] approximately 95% of motion artifact" | 5,368,026 (expired 2013) |
| Display states | Disconnect (IR light zero for 2 s); Pulse lost (%IR modulation below "Allen's threshold" for more than 5 s); Non-pulse (`125·uncorrelation + % spectral energy "about 5 Hz" > 100`, as printed, probably meaning above 5 Hz; or %mod below 0.05 % for 10 s); Not sure gives HOLD; Pulse present gives UPDATE; nothing displayed older than 40 s | 5,853,364 |
| Sensor off | seven metrics (IR AC in dB, its variability, uncorrelation, DC variability, DC slope, derivative skew, harmonicity) into a small neural net; "maybe off" for 7 s before "off"; samples outside PULSE PRESENT are not used. Whitening by first difference "because motion artifact will typically occur at frequencies lower than the pulse rate. This is particularly the case with infants" | 6,035,223 (expired 2017) |
| Correlated-artefact sweep | first-difference both channels; for R over a range, skewness of `X − R·Y` over at least one pulse; the R whose difference has skew near 0 (pulse cancelled) is the arterial R | 7,392,075, **active until 2026-11-16** |
| Venous pulsation detector | "openness" of the red-IR Lissajous plot and pulse-shape skew | 8,123,695, **active until 2030-12-29** |
| Wavelet SpO2 (CardioDigital) | Lissajous slope of wavelet coefficients in 0.67–3.33 Hz; pulse-ridge amplitude ratio | 8,255,029 / 8,761,855 / 8,898,037, **active to 2028–2033** |
| Sensor-borne calibration | a resistor bin selects one of several ROM curves ("21 curves is more desirable"); newer sensors send a correction `S(R) = S_3(R) + a + b·R + c·R²` to a legacy curve; OxiMax memory carries "calibration data" and wavelength-dependent coefficients; one MAX-N calibration for adults and neonates | 5,645,059; 6,628,975; 6,591,123 (expired) |
| Alarm integral | SatSeconds: `I += abs(T − SpO2)` per second, settings off/10/25/50/100; Safety Net = 3 violations in 60 s; neonate default Off | 5,865,736 (expired 2017); manuals |
| Low perfusion | specified 0.03–20 % IR modulation; low-perfusion accuracy validated with simulators | manuals |

### 1.2 Masimo SET (Radical, Radical-7, Rad-97, Root)

| Block | Mechanism and numbers | Source, status |
|---|---|---|
| Front end | 625 Hz LED cycle, delta-sigma ADC, ambient subtraction, decimation to 62.5 Hz (519-tap FIR, 7.5 Hz); log-normalisation, DC removal; 301-tap band-pass 34–250 BPM | US 5,632,272 (expired 2014) |
| Conventional engine ("seed") | RMS ratio per bin of 24 samples (0.38 s) into a look-up table; a snapshot is rejected if the red-IR correlation is below 0.75 ("Signals which satisfy the signal model will have a correlation" above it) | 5,632,272 |
| DST | 117 trial saturations "from 34.8 to 105.0" %; for each, a reference from red and IR; least-squares-lattice joint process estimator with 6 cells, λ = 0.8 ("a low value improves tracking"), δ = 1e-6, IR as primary; output power over the last 120 of 270 samples; candidate peaks at least 2 % of the maximum; the highest-saturation peak is arterial, the lowest venous; "If the saturation value of the selected peak for a given bin is lower than the seed saturation ... the peak is replaced with the seed"; voter keeps the three highest bins; clip ±16 points; smoothing `y = 0.6·x + 0.4·y` when clean, a 3-pole IIR (0.985 / 0.900 / 0.94) in motion; peak width = motion indicator | 5,632,272 / 6,157,850 (expired) |
| Stated limit of the DST | "in the unlikely event that the spectral content of s ... and n ... are similar, this approach will not yield accurate results" | 5,632,272 |
| FST (Fast Saturation Transform) | complex FFT (Kaiser window, 512 points); per bin, red/IR if both magnitudes are at least 1 % of their maxima and the phase difference is below 0.1 rad; arterial = highest saturation (or the histogram peak), venous = lowest | 5,632,272; 6,650,917 claim 1 (expired); Radical-7 manual 2021: DST "in parallel with Fast Saturation Transform (FST)" |
| SST (Sine Saturation Transform) | sin/cos projection at the pulse frequency, refined 4 → 2 → 1 BPM by minimum residual energy; `SAT = g(z_red/z_IR)` at that frequency | 6,850,787 family (expired 2022–2023) |
| Spectral "scrubber" | ratio lines at the spectral peaks; noise coupling μ = largest, arterial r = smallest; scrubber engaged when `μ − r > 0.5` | 6,002,952 / 6,699,194 (expired 2017) |
| Closed-form separation | the decorrelation constraint `−R1 + (ra + rv)·R12 − ra·rv·R2 = 0` (R1 = Σred², R2 = ΣIR², R12 = Σred·IR), written "at two different times", gives ra + rv and ra·rv | 5,632,272 eqs 98–103 |
| Arbitration | five engines (conventional, DST, FST, SST, one undisclosed), each with a measurement and a confidence, into a confidence-based arbitrator (CLAIM, white paper LAB3213D); the only explicit rule found is "highest saturation wins, never below the seed" | 5,632,272; 6,157,850 claim 1 |
| Pulse recognition | candidate pulses from curvature; period 80–480 ms; neonatal notch window 50 samples (0.8 s); ascending part slower than descending (ratio at least 1.1); stick-model and angle checks; pulse density = sum of accepted periods / snapshot length, 0 to 1 | 6,463,311 family (expired 2019) |
| Signal IQ | one confidence marker per pulse; three tiers: normal, Low SIQ (value still shown, flagged), not displayed; alert when integrity, pulse density and harmonic ratio all cross their thresholds (0.3, 0.7 and 0.8 on 0–1 scales); neonatal variants of the distortion logic | 6,606,511; 6,684,090 (expired 2020); manual |
| Averaging | 2–4, 4–6, 8 (default), 10, 12, 14, 16 s; FastSat weights each stored value by its signal quality and its timing (CLAIM; no patent found) | Radical-7 manual 2021; LAB5267B |
| Variable-mode averager | `v = mode·(σ²vt/σ²tt)·(t_newest − t_WA) + v_WA` with confidence weights: mode 0 = weighted average (lag), mode 1 = weighted least-squares line evaluated at the newest sample (no lag); output clamped to the buffer range | 6,430,525 / 6,999,904 (expired 2020) |
| Probe-off | signal strength SS = peak-to-peak AC/DC in %; floor 0.02 %; between 0.02 % and 0.25 % (0.05 % in high sensitivity) require pulse density of at least `−1.3043·SS + 0.5261`; at least 60 % of the energy at the pulse rate and harmonics (50 % below 30 BPM); limits armed after more than 5 blocks without an acceptable pulse. Modes APOD / NORM / MAX; "Maximum sensitivity mode fixes perfusion limit to 0.02%" | 6,360,114 (expired 2020); manual |
| PI | IR only, pulsatile / non-pulsatile × 100; 0.02–20 %; a separate "Low Perfusion" message without a published threshold | manual; LAB3410F |
| Calibration | ROM look-up table "determined by statistical regression of experimental measurements obtained from human volunteers"; a coding resistor names the probe (adult, paediatric, neonatal); LED wavelength tolerance "±2-10 nm for the same drive current", so the drive current is tuned per sensor or kept fixed | 6,770,028; 5,758,644 (expired 2015) |
| In vivo adjustment | clinician-entered additive offset, ±6 % (1 % steps in the 2011 white paper, 0.1 % in the 2020 export manual), shown next to the value; reset when the sensor or cable is disconnected, on sensor re-initialisation, and after 8 h (2020 manual) | LAB7035A; LAB-5476J |
| Probe-off space | regions in multi-wavelength ratio space | 8,265,723, **active until 2031-04-14** |

---

## 2. Our R-METHOD-2 seen through their designs

### 2.1 Equivalences (DERIVED, confirmed numerically; derived independently by two search agents and by this session)

Our estimator: `R = Sxy/Sxx`, `r = Sxy/sqrt(Sxx·Syy)`, with x = IR and y = red DC-normalised, band-passed first
differences summed over the 6 s window.

- **Nellcor.** Same slope through the origin, with cross-multiplication instead of division by DC (§1.1). R-METHOD-2
  is Nellcor's measurement step; what Nellcor adds after it is the Kalman filter, the ensemble averager and the
  quality metrics.
- **Masimo DST with a scalar canceller.** With reference `ref = y − r·x` and primary x, the output power is

```
P(r) = (Sxx·Syy − Sxy²) / (Syy − 2r·Sxy + r²·Sxx)
     = Sxx / (1 + (r − R)²/w²),     R = Sxy/Sxx,   w = sqrt(Syy/Sxx)·sqrt(1 − r_corr²)
```

  A single Lorentzian peak at our R, with a width set by our correlation. With arterial part a (IR power A, ratio
  ra) and an uncorrelated venous or motion part v (power V, ratio rv): `P(ra) = A`, `P(rv) = V` and
  `P(R) = A + V`. The scalar transform sits on the flanks at the true ratios and peaks at their power-weighted mix,
  which is exactly our regression.
- **Masimo DST with a multi-tap canceller.** Over a long window the same algebra holds frequency bin by frequency
  bin: P(r) becomes a sum of Lorentzians, one per bin, centred at the bin's own ratio `Re Sxy(f)/Sxx(f)` and
  sharpened by its coherence. The DST is a power-weighted histogram of per-bin ratios, the same object as Masimo's
  FST, a comb-filtered regression and Addison's wavelet ratio surface. It separates arterial from venous only in
  bins where one of them dominates.

### 2.2 Why the correlation gate cannot catch venous or motion contamination (DERIVED)

For two uncorrelated sources with positive ratios, the regression correlation over any power mix is bounded below:

```
r_min = 2·sqrt(ra·rv) / (ra + rv)            the gate r >= 0.8 can fire only if rv/ra >= 4
R_reg = (ra·A + rv·V) / (A + V)              the error grows with the share of venous power
```

| Arterial 95 %, second source at | rv/ra | Lowest possible r | SpO2 error at equal power |
|---|---|---|---|
| 85 % | 1.35 | 0.989 | −5.0 pt |
| 80 % | 1.52 | 0.979 | −7.5 pt |
| 75 % | 1.69 | 0.967 | −10.0 pt |
| 70 % | 1.86 | 0.954 | −12.5 pt |
| 60 % | 2.21 | 0.926 | −17.5 pt |
| 50 % | 2.55 | 0.899 | −22.5 pt |

Measured confirmation (VERIFIED, Clarke 2015, Carleton MASc thesis, TI AFE4400 evaluation module with a Nellcor
DS-100A probe, 5 adults): clean pulses gave R 0.50–0.57 with r = 1.00; isolated motion artefact gave R 0.70–1.27
(SpO2-equivalent 76–95 %) with r = 0.93–0.97. The most copied open-source oximeter algorithm (MAX30102 by RF) uses
the same 0.8 threshold. Masimo's 0.75 correlation test is a model-conformity check on the snapshot, not its artefact
detector. Keep the r gate for what it does catch: uncorrelated noise (electronics, ambient flicker, one channel
clipping).

### 2.3 What separates arterial from venous: simulation (DERIVED)

Model: derivative-domain signals at 100 Hz; arterial pulse at 2.2 Hz (132 BPM) with 2nd and 3rd harmonics at
ratio ra (95 % on our curve 123.98 − 39.13·R); venous or motion component at ratio rv (70 %); 30 dB white noise.
Scripts in §9.

**Canceller length** (8 s window, motion power equal to pulse power; values are the SpO2 of the power peaks found,
the arterial one being the highest):

| Motion | Regression | DST 1 tap | DST 9 taps | DST 33 taps | DST 65–257 taps |
|---|---|---|---|---|---|
| none | 95.1 % | 95 | 95 | 95 | 95 |
| sine 0.8 Hz | 82.5 % (r 0.96) | 83 | 95 and 77 | 95 and 70 | – |
| slow band noise 0.5–1.5 Hz | 82.5 % | 83 | – | 95 and 70 | 95 and 70 |
| band noise 0.5–5 Hz | 82.5 % (r 0.94) | 83 | 81 | 81 | 95 and 84 (65 taps); 95, 87 and 71 (129 taps) |
| pulse-shaped motion at the heart rate, 60° phase | 82.5 % | 83 | – | 80 | 76–82, never 95 |
| venous only, no heartbeat | 70.0 % (r 1.00) | 70 | 70 | 70 | 70 |

**Cheap separations from sums we already have** (300 noise realisations per row; share of windows within ±3 points,
median error in brackets). "Sub-window decorrelation" solves the Masimo constraint of §1.2 by least squares over
six consecutive sub-windows (`R12_k·s − R2_k·p = R1_k`, rows divided by R2_k; ra = smaller root of `z² − s·z + p`),
and falls back to the regression when the system is ill-conditioned or the roots are complex. "Harmonic bins" is
`Σ Re(Y·conj(X)) / Σ |X|²` over ±1 bin around the first three harmonics (heart rate known, as HR3 provides).

| Motion pattern (V = motion power, A = pulse power) | Regression, 6 s | Sub-window decorrelation, 6 × 1 s | Harmonic bins, 6 s | Harmonic bins, 10.24 s |
|---|---|---|---|---|
| none | 100 % (0.0) | 100 % (0.0, fallback) | 100 % (0.0) | 100 % (0.0) |
| constant, V = A | 0 % (−12.5) | 28 % (−1.1) | 33 % (−3.9) | 53 % (−2.5) |
| onset half-way, 0 → A | 0 % (−8.2) | 100 % (+0.2) | 56 % (−2.2) | 81 % (−1.1) |
| bursts of 1 s every 3 s, V = 2A | 0 % (−14.3) | 100 % (+0.1) | 25 % (−5.6) | 45 % (−3.3) |
| random bursts of 0.7–2 s, V = 2A | 4 % (−16.6) | 87 % (−0.1) | not run | not run |

Reading:
- Separation needs either a canceller of at least about 0.6 s (65 taps at 100 Hz) or a change of mixing over time;
  the scalar DST adds nothing.
- Motion with the pulse's own waveform and frequency (an external periodic pressure at the heart rate, or venous
  pulsation transmitted through arteriovenous shunts) is not separable by any linear second-order method.
- With venous pulsation alone and no heartbeat, every method reports the venous saturation with r = 1.00.
- The sub-window decorrelation is exact when the arterial and motion powers vary differently across the window,
  which is what neonatal kicking does; it is ill-conditioned when both are stationary, where the harmonic bins
  help instead. The two are complementary.
- Longer windows help the harmonic bins (finer frequency resolution): HR3's 10.24 s frame is better than 6 s.

### 2.4 Limits of the simulation

- Two uncorrelated sources with fixed ratios; real motion also multiplies both channels (Yorkey's wavelength-
  independent η, US 5,645,060), a third source with R near 1. When SaO2 is below 85 % the arterial ratio exceeds 1,
  so "take the highest saturation" or "take the smaller root" picks the motion term: the over-reading at low
  saturation that every maker shows.
- The canceller is a batch least-squares filter fitted on the evaluated window, which is optimistic compared with an
  adaptive lattice.
- Synthetic pulse, no heart-rate variability, no DC-normalisation dynamics, Gaussian band-limited motion.
- The decision must come from our captures: SUBJ10 moving, SUBJ08 and SUBJ09 (HOSPNAV), SUBJ11 still, the adult
  finger and the MS100.

---

## 3. Independent evidence that should shape the design

Full tables with design, n, devices, settings and tags in `src_literature.md` (§9). Numbers below are VERIFIED in the
abstract or full text unless tagged.

**Motion and low perfusion (adult volunteers).**

| Study | Finding |
|---|---|
| Barker & Shah 1997 | time within 7 points of control: N-200 76 %, N-3000 87 %, Masimo prototype 99 % |
| Barker 2002 | performance index: Masimo 94 %, Agilent Viridia 84 %, Nellcor N-395 69 %, Criticare 28 % |
| Shah 2012 | hypoxaemia sensitivity with machine / volunteer motion: Masimo 100 / 95 %, Nellcor N-600 65 / 50 %, TruSat 20 / 15 % |
| Louie 2018 (independent, UCSF) | Masimo, Nellcor and Philips all above 3 % Arms during any motion, 1.8 % still; low PI increased error |
| Giuliano 2023 (GE-funded) | still, 80–90 %: bias Masimo +0.28, Nellcor +1.68; motion Arms GE 2.45, Masimo 3.19, Nellcor 4.15; very low PI: Masimo bias +2.36 |
| Kästle 2000 (Agilent authors) | dropout: Masimo 3.0 % of time, N-3000 24.1 % |

**Neonates: missed events, false alarms, availability.**

| Study | Finding |
|---|---|
| Bohnhorst 2000, 17 preterm infants | missed bradycardias: conventional 32 %, new Nellcor 69 %, Masimo 7 %; missed hypoxaemias 0, 5.4 % and 0.5 % |
| Hay 2002, NICU | frozen pulse rate during ECG changes: Masimo 0, N-395 6, Philips 11, Novametrix 46 |
| Workie 2005, 36 NICU infants | same alarms; dropouts Philips 247 vs Masimo 38 |
| Nizami 2015, 11 preterm infants | modern Nellcor and Masimo tie: about 50 % false SpO2 alarms each |
| Poets & Stebbens 1997, 10 preterm infants | movement artefact in 31 % of 2.5 s segments, and in 88 % of segments with SpO2 ≤ 80 % |
| Khoury 2021, delivery room, 60 newborns | time to stable signal, median: Nellcor 8.5 s, Masimo 12 s; false bradycardia Masimo 18/55, Nellcor 0 |

**Averaging and response.**

| Study | Finding |
|---|---|
| McClure 2016, 710 NICU infants | 2 → 16 s averaging: 53 % fewer alarms, each 2.15 times longer; a 15 s alarm delay on 2 s averaging: 67 % fewer alarms |
| Vagedes 2014 | event counts become nearly independent of averaging when the minimum event duration is 10–15 s |
| Poets 2015, COT cohort | hypoxaemia episodes of 1 min or more predicted death or disability (RR 1.66); shorter ones did not (RR 1.01) |
| Ahmed 2010, preterm infants | 16 s averaging under-counted events below 70 % and merged brief events |
| Masimo bulletin LAB3474C (CLAIM) | full step response: Radical at 4 s averaging about 11 s; Nellcor N-395 default about 25 s (units not printed, presumably seconds) |
| NICU settings seen | Masimo 8 s (UVA) and 10 s (CHLA, Foglia 2017); Nellcor 6 s via a GE Solar in NICU mode; our 6 s is inside that range |

**Offsets and low saturation.**

| Study | Finding |
|---|---|
| Rosychuk 2012, 114 infants < 33 weeks, Masimo V4 | SaO2 − SpO2 = −2.0 ± 5.8 at SpO2 85–95 % |
| Foglia 2017, 36 cyanotic infants | bias Masimo +0.8 (Arms 4.2), Nellcor +3.9 (Arms 6.3) |
| Dawson 2013, delivery room | Masimo − Nellcor = −3 points; below 70 %, Nellcor 20 points higher |
| Sedaghat-Yazdi 2008, Nellcor MAX-N | bias on the sole 2.9 vs on the toe 1.6; on the sole, 6.0 below 90 % SaO2 vs 1.8 at or above |
| Lakshminrusimha 2015, 96 infants < 28 weeks | pre- vs post-ductal difference ≥ 2 points in 28 % |
| van der Eijk 2012, ELBW | two probes on two feet differ by 2 points (median) |
| Courtney 2026 | same maker, other hardware path: −1.8 points |
| Gerstmann 2003, NICU, all brands | bias falls as SaO2 falls (over-reads low, under-reads high) |
| Harris 2016 / Georgiev 2024 | at SaO2 75–85 %, 14–31 % of readings ≥ 5 points off; at 70–85 % Arms 4.5 (OxiMax) to 9.8 (Philips) |
| BOOST-II 2013 | a Masimo calibration revision around 87–90 % changed the mortality result (RR 1.45 with the revised software) |
| Bachman 2019 / 2020, Masimo, 10 s | at SpO2 85 % the chance of PaO2 ≤ 40 mmHg reaches 25 % |
| Mindray | no peer-reviewed neonatal accuracy study of any Mindray oximeter, the N17 included; only the maker's manual figures (518B, 520N) |

---

## 4. R-curve: what Masimo and Nellcor add to the 2026-10-26 survey

1. **Encoding.** Nellcor: resistor bins select one of several ROM curves, and newer sensors carry a correction
   `a + b·R + c·R²` to a base curve (US 5,645,059); OxiMax memory adds wavelength-dependent coefficients. Masimo: ROM
   look-up table; a coding resistor names the probe type; later sensor memories can carry emission centroids,
   temperature coefficients, site and age (US 8,265,723 description). Precedent for our `$SET spo2_r_curve_*`: one
   base curve plus a small, documented correction per probe model or population.
2. **Neonatal handling.** One adult-volunteer calibration, checked on a small neonatal set; the neonatal ±3 claim
   includes one point added by hand for fetal haemoglobin (Masimo K092838). Nellcor's neonatal mode changes alarm
   limits only. No neonatal-specific curve was found for either maker (Philips does state that the patient category
   changes its calculation).
3. **Low saturation.** Both needed dedicated sensors or algorithms for 60–80 %: Masimo Blue with "a specific
   algorithm" (in-house Arms 3.78 in cyanotic infants, CLAIM), Nellcor LoSat and Max-I, and the 735/890 nm sensors
   calibrated on sheep. The DST scans down to 34.8 %, and Masimo shows NICU desaturations to about 30 % (CLAIM). FDA reports
   accuracy below 70 % in 20-point bands. Below 85 % every brand over-reads (§3).
4. **Individual bias.** Masimo's in vivo adjustment: additive, ±6 points, visible, entered only from a
   CO-oximeter-measured SaO2 (Masimo LAB6126A: calculated SaO2 from a blood-gas analyser can be off by more than
   5 points in 20 % of samples), reset on sensor off or after 8 h. A cleared-device precedent, kept apart from the
   population curve.
5. **Wavelength and drive current.** LED wavelength moves with drive current (tolerance ±2–10 nm at the same
   current); Masimo prefers a fixed drive current with gain control elsewhere. Our HGAC v1 is RF-only, which already
   follows this; LED current changes through `$SET` during an SpO2 window would move the curve.
6. **The curve belongs to the estimator.** A DST-type monitor reports the highest-saturation component, our
   regression reports the power-weighted mix. Under venous pulsation a DST reference reads higher than we do on the
   same blood, and any change of estimator (harmonic bins, sub-window decorrelation) needs the curve re-checked,
   which the register already does per R method.
7. **For the rationale §18 decision ("one curve or two").** Industry precedent is an adult calibration, a neonatal
   check and a bounded individual offset. Our neonatal default transfers the N17's neonatal behaviour, unmeasured.
   Attribution steps, cheapest first:
   - identify the N17's SpO2 module (Mindray, Masimo or Nellcor), since the brand offsets above then apply directly —
     **done 2026-10-27: Nellcor OxiMax in every N17 of the unit (unit staff; sticker on the module)**;
   - log for every session our probe site and the reference's (limb, pre- or post-ductal, sole, dorsum or toe), the
     reference's averaging, and the foot or incubator temperature;
   - recompute R with the harmonic bins and the sub-window decorrelation on the existing captures: if the 0.07 offset
     shrinks, it is venous admixture in processing; if it stays, it is reference, site or physiology locked to the
     heartbeat;
   - collect CO-oximetry SaO2 pairs when an arterial gas is drawn clinically, and run a second commercial brand next
     to the N17 in a few sessions.

---

## 5. Recommendations for incunest_afe4490, ranked by benefit per cost

| # | What | Evidence | Cost | Patents |
|---|---|---|---|---|
| 1 | **Offline A/B on our corpus: regression vs sub-window decorrelation vs harmonic-bin R** (an `experiments/` script, replay of the existing captures). Report per window the three R, their differences and the decorrelation validity; score against the reference on SUBJ10 moving, SUBJ08/09, SUBJ11, the adult finger and the MS100. The harmonic estimator must see the 2nd harmonic, which at 150–180 BPM lies at 5–6 Hz, above our 0.5–5 Hz SpO2 band: use the 0.5–15 Hz PI band or HR3's frame | §2.3; Alkhoury 2021; Masimo 5,632,272, 6,650,917, 6,850,787 | one script | expired |
| 2 | **SQI as a confidence index, PI as a separate perfusion flag.** Combine HR3's harmonic ratio (already computed), IR derivative skewness, ratio-of-ratios variance over 3 s from the block sums, agreement between R estimators (item 1), pulse amplitude against a 60 s history and uncorrelation for uncorrelated noise. Three tiers: normal, low confidence shown with a flag, withheld. Validate first, as planned on 27-oct (option D: Spearman's ρ of the error against each candidate on the 21 sessions with a reference), adding these metrics to PI, r and HR3_SQI | Nellcor 7,194,293, 7,006,856, 6,035,223; Masimo 6,684,090, 6,463,311; conversation log 27-oct | low | expired |
| 3 | **Adaptive averaging instead of the fixed 6 s window**: a scalar Kalman on R per 100 ms block (Nellcor: √Q = 1.3 points/s ≈ 1.1e-4 R² per block with our slope; measurement variance from the residual in a centred 1 s window plus a floor), or Masimo's variable-mode averager. Fast and Normal become target ages of 3 and 5 s; publish age and σ in SpO2 points. Check on the apnoea captures that the rate limit does not slow real desaturations | Nellcor 5,853,364, 7,039,538; Masimo 6,430,525 | low | expired |
| 4 | **Withhold-state KPIs and limits.** Since v0.110 withholds, track withheld time per hour, recovery time after motion, time to first value (ours: median 10.5 s, p90 36.6 s, against medians of 8.5–12 s for Nellcor and Masimo in Khoury 2021) and missed events against ECG. Escalate like Nellcor (pulse search, then timeout) instead of leaving a silent gap | Bohnhorst 2000; Hay 2002; Kästle 2000; Durbin 2002; PM1000N manual | low | – |
| 5 | **No-pulse and probe-off bench campaign**, then Masimo's probe-off rule and Nellcor's non-pulse rule as candidate criteria: MS100 with the pulse off, a non-pulsatile phantom, probe in air under a phototherapy lamp or radiant warmer, probe lying on a breathing chest, ventilator pseudo-pulses (neonatal rates of 30–60 per minute fall inside our 30 BPM floor), and a suprasystolic cuff labelled as very low perfusion, not as no pulse | Masimo 6,360,114, LAB4546A, LAB5324B, LAB4793B; Nellcor 5,853,364 | bench | expired |
| 6 | **Nellcor's skewness sweep** as a shape-based second opinion that still works when motion overlaps the pulse spectrum, provided the motion waveform is symmetric. About 30 R values with the skewness of `X − R·Y` over 1–3 s at the decimated rate. Offline first | Nellcor 7,392,075 | medium | **implement after 2026-11-16** |
| 7 | **R-curve management**: base curve plus correction terms per probe or population; do not bake the 2.7-point offset in before attribution (§4.7); an in vivo-style offset only with Masimo's limits; flag values below 85 % as reduced accuracy; whether to show flagged values below 70 % instead of withholding them is a clinical decision; keep LED current fixed during SpO2 windows | §4; survey 2026-10-26 | low | expired |
| 8 | **Beat-synchronous ensemble averaging** only if item 1 is not enough: it is another comb filter, needs reliable triggers and loses gain with neonatal heart-rate variability | Nellcor 7,039,538, 7,194,293, 5,485,847 | medium | expired |
| 9 | **Full time-domain DST** as an offline tool only: at least 0.6 s of taps, a comb pre-filter, highest-saturation peak. Feasible on the ESP32-S3 (NLMS with 32 taps for about 100 trial ratios at 50 Hz is about 0.35 Mflop/s) but tuning-heavy; with too few taps it can lock onto the venous peak and do worse than the regression | Masimo 5,632,272; Jensen 2009 code; Alkhoury 2021 | high | expired |
| 10 | **IncuNest alarm layer** (not the library): a short SpO2 window plus an explicit alarm delay and a minimum event duration of 10–15 s rather than long averaging; SatSeconds reduces nuisance alarms but adds no discrimination (Stefanescu 2016); Masimo's parallel slow and fast SpO2 as an option | McClure 2016; Vagedes 2014; Masimo 6,822,564 | low | expired |

## 6. Not to do, or not now

- Do not count on r for motion rejection (§2.2).
- Do not add a hold without a time bound and a visible flag; held values hid bradycardias and heart-rate changes in
  the NICU studies.
- Do not implement the active patents: Nellcor 7,392,075 before 2026-11-16, 8,123,695 (venous pulsation) before
  2030, the CardioDigital wavelet family before 2028–2033, Masimo 8,265,723 (probe-off space) before 2031.
- Do not use a simulator to claim accuracy, and do not use calculated SaO2 from a blood-gas analyser as a reference.
- ICA, singular-spectrum methods and accelerometer cancellation: costly, no neonatal validation, and no gain over a
  median of beat ratios at the wrist (Liang 2026).

## 7. Patent status of what we might reuse (Google Patents, 2026-10-27)

| Status | Patents |
|---|---|
| Expired | Nellcor 5,351,685; 5,853,364 family (6,083,172, 6,411,833 and continuations); 5,645,059; 5,645,060; 5,368,026; 5,485,847; 5,865,736; 6,035,223; 7,006,856; 7,016,715; 7,039,538; 7,194,293; 7,209,774; 7,302,284 / 7,315,753 / 7,336,983; 7,534,212. Masimo 5,632,272 family (DST, FST, closed form, filter bank); 5,758,644 / 6,011,986; 6,002,952 / 6,699,194; 6,360,114 / 6,654,624; 6,430,525 / 6,999,904; 6,463,311 family; 6,606,511; 6,684,090 / 7,024,233; 6,770,028; 6,822,564; 6,850,787 family (SST) |
| Active | Nellcor 7,392,075 (until 2026-11-16); 8,123,695 (until 2030-12-29); 8,255,029 (2028-09-11), 8,761,855 (2033-02-19), 8,898,037 (2033-03-23). Masimo 8,265,723 (2031-04-14), 11,224,381 (2028-09-02), 12,029,586 (2028-06-16) |

## 8. Corrections and caveats

- The search brief had errors that the sources corrected: US 7,024,233 is Masimo's data-confidence indicator, not a
  probe-off patent; US 7,209,774 and the parallel-saturation-module patents are Nellcor's; Rusch 1996 appeared in
  Comput Biol Med, not IEEE TBME.
- One search agent recommended bounding "the artefact-gate hold", assuming v0.110 holds the last value. It withholds
  (SpO2 = NaN, no hold), so the corresponding action is item 4 of §5.
- Masimo's white papers are marketing documents of 2004–2012 citing mostly congress abstracts. The Medtronic white
  paper and King 2025 are Medtronic-funded; Giuliano 2023 is GE-funded; Baquero 2011 has a Masimo consultant
  author. Each is tagged in the source files.
- Masimo's in vivo adjustment differs between document versions (step size, 8 h reset); the US 2021 manual does
  not include it.
- Masimo's 2021 manual expands FST as Fast Saturation Transform, while Masimo's own comparison chart labels Philips'
  engine "FST".
- Dawson 2010 (delivery-room SpO2 percentiles) carries an Expression of Concern from Pediatrics (March 2026); the
  reason was not accessible.
- The simulations are synthetic (§2.4); they rank ideas for the offline test, they do not replace it.

## 9. Sources and files

Primary sources were read on Google Patents (`https://patents.google.com/patent/<number>/en`), techdocs.masimo.com
(Radical-7 operator's manuals LAB-5475L 2021 and LAB-5476J 2020, Root LAB-9274D), Nellcor manuals (N-600x and N-595
service manuals, PM100N and PM10N operator's manuals, PM1000N service manual), Baker & McGonigle, "Nellcor Pulse
Oximetry Performance in Challenging Conditions" (Medtronic, 2021), the Masimo white papers in
`docs/masimo_whitepapers/` (not versioned), PubMed, PMC and Europe PMC. Key papers: Goldman 2000 J Clin Monit Comput
16:475 (abstract only); Clarke 2015 Carleton MASc thesis; Alkhoury 2021 J Clin Monit Comput 35:797 (PMC8286955);
Jensen 2009 EMBC 4039 with DTU MATLAB code; Lee 2026 Sensors 26:5676; Liang 2026 arXiv 2607.08001; and the clinical
studies of §3, with PMID and DOI in `src_literature.md`.

Working files are kept outside the repository, in `masimo_nellcor_research_20261027.zip` held by Alex: the five
detailed source reports with quotes and tags (`src_nellcor.md`, `src_masimo.md`, `src_masimo_whitepapers.md`,
`src_literature.md`, `src_algorithms_research.md`), the numpy simulations of §2.3 (`dst_sim.py` to `dst_sim4.py`)
and the downloaded patents, manuals and papers, which are third-party material and are not versioned.
