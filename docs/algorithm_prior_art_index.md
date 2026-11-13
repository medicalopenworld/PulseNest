# Prior-art index of the algorithms of incunest_afe4490

Started 2026-11-12 at Alex's request. One place that lists, per family of method, the patents,
papers, maker documents and application notes the project has already collected for pulse rate,
SpO2, PI and signal quality, and says for each one what it serves, whether we use it, measured it or
left it, and whether the citation was checked against its source.

**What this is not.** It is not a new literature search: this first pass only consolidates what the
reports below already say, and no citation was re-checked while writing it. It is not a
freedom-to-operate analysis: the patent status is the legal-status line the source report read on
Google Patents on its own date, not a legal opinion. It does not repeat the analysis: every row
points to the report and section that holds it. The exceptions are §2.4 and §2.5, added on
2026-11-13 from a short web search that asked whether the literature has families beyond ours, and
the rows keyed H2, from a search on family 2 of 2026-11-12.

**Entry criterion.** What the library uses, what we measured or discarded, and what Nellcor, Masimo,
Philips and the other makers publish. Not exhaustive.

**Row unit.** One row per method and source. A patent that describes several methods appears in
several tables, each time with the method that belongs there.

## 0. How to read the tables

Sources consolidated, with the key used in the *Detail* column and the date each one was written:

| Key | Document | Date |
|---|---|---|
| MN | `docs/masimo_nellcor_spo2_prior_art.md` | 2026-10-27 |
| PIM | `docs/pi_motion_prior_art_20261111.md` (local file, not versioned on 2026-11-12) | 2026-11-11 |
| RC | `docs/r_curve_calibration_survey.md` | 2026-10-26 |
| RCU | `docs/spo2_r_curves.md` | register, kept up to date |
| SAC | `docs/spectral_autocorrelation_20261112.md` | 2026-11-12 |
| PIA | `docs/pi_artifact_robustness_20261111.md` | 2026-11-11 |
| SPEC | `incunest_afe4490_spec.md` in the library repository (§5 algorithms, §13 references) | — |
| RAT | `incunest_afe4490_design_rationale.md` in the library repository | — |
| WS | web search of 2026-11-13; summary in `conversation_log.md`, block of that date | 2026-11-13 |
| H2 | search on family 2 (lag estimators) by an analysis session: one patent read in part, the rest search summaries; summary in `conversation_log.md`, block of 2026-11-13 | 2026-11-12 |

Columns:

- **Type.** P patent; A article, book or thesis; M maker document (manual, white paper, 510(k));
  N application note, reference design or open-source code; S standard.
- **Patent status.** As the source report recorded it on its date. *not recorded* = the report gives
  none. The filing year of the patents is not recorded in this pass.
- **Serves.** PR pulse rate; PI perfusion index; SpO2 the estimate of R or of the saturation; CAL the
  R-to-SpO2 curve; AVG averaging and response time; Q confidence index; VAL pulse validation (publish
  or withhold); PROBE probe state.
- **In this project.** *used* (spec section); *measured, not adopted* (report); *discarded*
  (rationale section); *listed* (named as an option, not run); *context* (shapes a decision without
  being a method of ours); *not evaluated*.
- **Citation.** *read* = the source report states it read the primary source (its VERIFIED or
  [source] tag); *second-hand*; *claim* = maker marketing; *no record* = cited without any statement
  that the source was read; *from memory* = cited in conversation, never looked up. Two more values
  for the rows of WS: *summary* = the page was opened and read through an automatic summary, not in
  full; *search result* = known only from the title and snippet a search returned.

## 1. What each family of analysis can serve

HR1, HR2 and HR3 are three analyses of the pulsatile structure of the PPG, each in its own domain,
and the pulse rate is only the first product of each. The table says what the collected prior art
and our own measurements show each family can feed.

| Family | Pulse rate | PI | SpO2 | Confidence index | Pulse validation | Probe state |
|---|---|---|---|---|---|---|
| 1. Beats in time (`HR1`) | today | makers: peak to valley per accepted beat | makers: ratio per beat, beat-synchronous averaging | today (`hr1_sqi`); makers: pulse density | makers: per-pulse tests | makers: pulse density inside the probe-off rule |
| 2. Periodicity in time lag (`HR2_*`) | today; one maker argues against it for an arrhythmic pulse (§2.2) | none recorded | listed, not run (RAT §9, option 6) | today (`hr2_sqi`) | none recorded | none recorded |
| 3. Spectrum (`HR3_*`) | today | makers: amplitude of the harmonic peaks | measured: R on the harmonic bins; makers: Masimo FST and SST, Philips FAST | today (`hr3_sqi`); measured: comb purity | today: the SpO2 gate is `hr3_sqi > 0` | makers: share of the energy at the pulse rate and its harmonics |
| 3, its cepstrum (`HR3_CEP`, not evaluated) | speech only | makers: locates the peaks for a spectral PI | title of one patent only | none recorded | title of one patent application only | none recorded |
| 4. Oscillator locked to the signal (`HR4_*`, candidate) | makers and articles: the oscillator's frequency | none recorded | none recorded | one maker: a signal-to-noise estimate that steers the loop | none recorded | none recorded |

*none recorded* means absent from our reports, not absent from the literature.

Families 1 to 3 are implemented in the library. Family 4 is a candidate (Alex, 2026-11-13), taken
from the web search of that day: nothing is planned or evaluated (§2.4). §2.5 lists the two other
domains that search found in which a pulse is searched and a rate obtained (time-frequency plane,
phase space); neither has a number.

Identifiers. Since 2026-11-12 the number in an HR name is the domain of the analysis and the suffix
is the method (SPEC §5.5; RAT §22). `HR2_ACF` (implemented), `HR2_MPM` and `HR2_YIN` (planned) and
`HR1_DRV` (a derivative-based peak detector, named `HR4` until that day; catalogued, not planned)
are in SPEC §5.5. The number 4 was reserved for the cepstrum from 2026-11-12 to 2026-11-13; since
then the cepstrum is a method of family 3 and 4 names the locked oscillator (RAT §22.2). `HR1_THR`
(today's HR1), `HR2_AMDF`, `HR3_HPS` (today's HR3), `HR3_SAC` (the spectral autocorrelation of SAC),
`HR3_CEP` (a cepstral method) and `HR4_PLL` (a phase-locked loop) are working labels, not library
identifiers.

## 2. Analyses of the pulsatile structure

### 2.1 Family 1 — beats in time

Finds each beat. Products: beat times, amplitude and shape of each beat.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Peak detection with an adaptive threshold and a refractory period (ECG QRS) | Pan & Tompkins 1985, IEEE TBME 32(3) | A | — | PR | used: HR1 is a simplified adaptation (SPEC §5.2) | no record | SPEC §13.1 |
| Systolic peak from two event-related moving averages (TERMA), about 111 ms and 667 ms | Elgendi et al. 2013, PLoS ONE 8(10) e76585 | A | — | PR | discarded: recommended, then reversed once measured behind the HR1 quality gate (RAT §5.3, §5.4) | no record | SPEC §13.1; RAT §5.3 |
| Slope sum function onset detector | Zong et al. (reference incomplete) | A | — | PR | listed (RAT §5.3) | no record | RAT §5.3 |
| Derivative, local-extrema and Hilbert-envelope detectors | "Billauer; Li; FDPPG variants"; "Hilbert-transform PPG onset literature" (references incomplete) | A | — | PR | listed (RAT §5.3) | no record | RAT §5.3 |
| Pulse recognition from curvature: period 80–480 ms, neonatal notch window, rise slower than fall, stick model; pulse density = accepted periods / snapshot length | Masimo US 6,463,311 family | P | expired 2019 | VAL, Q | not evaluated; candidate for the SQI (MN §5 item 2) | read | MN §1.2 |
| Per-pulse motion test: ratio of the derivative's positive to negative peak (1 to 1.4 pulse, about 1 motion) | Nellcor US 5,368,026 | P | expired 2013 | VAL | not evaluated | read | MN §1.1 |
| Beat-synchronous ensemble averaging, trigger = ECG R wave or the optical period | Nellcor US 7,039,538 / 7,209,774; 5,485,847 | P | expired | SpO2, PR | not evaluated; only if the harmonic-bin R is not enough (MN §5 item 8) | read | MN §1.1 |
| Ensemble weights and motion metric: pulse amplitude against a long-term average (above 1 = motion), ratio-of-ratios variance, period variability, pulses qualified by a neural net | Nellcor US 7,194,293 / 9,211,090 | P | expired 2024 | Q, VAL, SpO2 | not evaluated; the long-term amplitude ratio is worth measuring (PIM lesson 4) | read | MN §1.1; PIM Nellcor |
| PI per pulse = (IRmax − IRmin) / IRDC | Masimo US 6,334,065; US 9,066,666 | P | not recorded | PI | not used: PI-METHOD-1 is a window RMS shown as a peak-to-peak equivalent (RAT §11) | read | PIM Masimo |
| Modulation % = 100·AC/DC with AC = max − min per pulse, DC = (max + min)/2 | Nellcor US 6,675,031 | P | not recorded | PI | not used (RAT §11) | no record | RAT §11 |
| Pulse amplitude per pulse normalised to DC, used to index the SpO2 calibration | Woolsthorpe US 7,184,809 | P | expired 2025 | PI, CAL | not evaluated | read | PIM Nonin |
| PI as the sum of normalised intensity changes over half a cardiac cycle, or max − min of a 2 s window every 1 s | Ohmeda EP 0807402 A1 / US 5,766,127 | P | withdrawn / expired | PI | not evaluated | read | PIM GE |
| R per beat: peak minus interpolated valley, median of up to 5 beats | Maxim MAXREFDES117 | N | — | SpO2 | listed: "per-beat peak-to-trough" (RAT §9, option 7) | read | RC §2.1 |
| Amplitude ratio per beat by regression, then a moving average weighted by its beat-to-beat variation (NPi) | Nihon Kohden, SpO2 Monitoring Performance Digest 2023 §7.1 | M | — | SpO2 | not evaluated | read | PIM Nihon Kohden |
| 4-beat or 8-beat exponential average; flag when a beat does not match the current pulse interval | Nonin OEM III module specification | M | — | AVG, VAL | not evaluated | read | PIM Nonin |
| Median of beat ratios as the baseline that ICA, singular-spectrum and accelerometer cancellation do not beat at the wrist | Liang 2026, arXiv 2607.08001 | A | — | SpO2 | context: those methods are on the "not to do" list (MN §6) | read | MN §6, §9 |
| Pattern matching of crests and valleys, mean period over 512 samples (about 9 s at 57 Hz): the rate path for an arrhythmic pulse without motion | Nellcor US 7,865,224 | P | expired 2021 | PR | not evaluated | read (first third of the text) | H2 |

### 2.2 Family 2 — periodicity in time lag

Measures how much the signal resembles itself one period later. Products: the period and the
strength of the periodicity.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Fundamental frequency from the normalised autocorrelation and the cumulative mean normalised difference (YIN) | de Cheveigné & Kawahara 2002, JASA 111(4) | A | — | PR | used: HR2 derives from it (SPEC §5.3); `HR2_YIN` planned (SPEC §5.5) | no record | SPEC §13.2 |
| Autocorrelation methods for pitch | Rabiner & Schafer 1978, *Digital Processing of Speech Signals* | A | — | PR | used as background (SPEC §5.3) | no record | SPEC §13.2 |
| McLeod pitch method: normalised square difference function with a clarity metric | none cited | — | — | PR, Q | planned: `HR2_MPM` (SPEC §5.5) | no record | SPEC §5.5 |
| Average magnitude difference function | none cited | — | — | PR | candidate named 2026-11-12 (`HR2_AMDF`), not evaluated | no record | — |
| R from the autocorrelation at the pulse lag | own option (Alex, 2026-10-02) | — | — | SpO2 | listed, not run (RAT §9, option 6) | — | RAT §9 |
| A maker's reason for not taking the rate from an autocorrelation: with an arrhythmic pulse it may show no strong local maximum | Nellcor US 7,865,224 | P | expired 2021 | PR | context for `HR2_ACF` and its planned variants | read (first third of the text) | H2 |

H2 found no maker that takes the pulse rate from a lag estimator alone, and no comparison of YIN,
MPM or AMDF on PPG, nor anything neonatal. It is one short search, not an absence in the literature.

### 2.3 Family 3 — spectrum

Looks at how the energy is distributed over the fundamental and its harmonics. Products: the
fundamental, the power of each harmonic, the power between them. All its methods start from the
spectrum; the cepstrum, at the end of this section, transforms it once more.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Harmonic product spectrum | Schroeder 1968, JASA 43(4) | A | — | PR | used: HR3 (SPEC §5.4) | no record | SPEC §13.3 |
| FFT-based rate on PPG in a wearable | Paradkar & Chowdhary 2017, IEEE EMBC | A | — | PR | context (SPEC §13.3) | no record | SPEC §13.3 |
| Autocorrelation of the spectrum along frequency (speech pitch) | Lahat et al. 1987; log-spectrum variant Kunieda et al. 1996 | A | — | PR, Q | measured, not adopted (SAC); `HR3_SAC` | from memory | SAC |
| FFT every 1 s, harmonic families scored, six artefact criteria, the failing cycle discarded | Philips FAST: US 6,631,281; *FAST SpO2 algorithm* 2025 | P, M | expired | PR, SpO2, VAL | context: precedent of the SpO2 artefact gate (RAT §17) | patent: no record; document: read | RAT §9, §17; PIM Philips |
| Ratio red/IR per FFT bin where both magnitudes reach 1 % of their maxima and the phase difference is below 0.1 rad; arterial = highest saturation (FST) | Masimo US 5,632,272; US 6,650,917 claim 1 | P | expired | SpO2 | measured, not adopted: R on ±1 bin around the first three harmonics of HR3 (`experiments/r_estimators_ab_20261027.py`, RAT §17) | read | MN §1.2, §2.3; RAT §17 |
| Sine and cosine projection at the pulse frequency, refined 4, 2, 1 BPM by minimum residual (SST) | Masimo US 6,850,787 family | P | expired 2022–2023 | SpO2, PR | not evaluated on its own (same family as the harmonic-bin R) | read | MN §1.2 |
| Spectral "scrubber": ratio lines at the spectral peaks, largest = noise coupling, smallest = arterial | Masimo US 6,002,952 / 6,699,194 | P | expired 2017 | SpO2, VAL | not evaluated | read | MN §1.2 |
| Harmonic comb filter with cardiac-gated averaged pulses as a second SpO2 path; typical harmonic energy 82.8 / 14.4 / 2.1 / 0.5 % | Nellcor US 5,853,364 (Table 1); US 7,302,284 / 7,315,753 / 7,336,983 | P | expired | SpO2, Q | not evaluated | read | MN §1.1 |
| FFT every 10 s whose job is to find or correct the frequency of the adaptive comb filter of §2.4 | Nellcor US 7,865,224 | P | expired 2021 | PR | context: a finder beside a tracker | read (first third of the text) | H2 |
| Heart-rate comb in front of the plain ratio matches the DST in 7 of 8 exercise stages at 1/28 of its computing time | Alkhoury 2021, J Clin Monit Comput 35:797 | A | — | SpO2 | context: evidence for measuring the harmonic-bin R (MN §0.3) | read | MN §0.3, §5 |
| Narrow-band filtering around the fundamental found by frequency analysis (NPi) | Nihon Kohden, Performance Digest 2023 §7.1 | M | — | SpO2, VAL | not evaluated | read | PIM Nihon Kohden |
| Wavelet SpO2: Lissajous slope of wavelet coefficients in 0.67–3.33 Hz, pulse-ridge amplitude ratio | CardioDigital / Nellcor US 8,255,029; 8,761,855; 8,898,037 | P | in force to 2028–2033 | SpO2 | not to implement (MN §6) | read | MN §1.1, §7 |

Our own measurements in this family, for reference: HPS with two harmonics and floor-removing
preprocessing (`experiments/hr3_spectral_variants_20261021.py`, not adopted; RAT §17.1); local
contrast and comb purity (SAC, not adopted).

*The cepstrum (`HR3_CEP`, working label).* Transforms the logarithm of the spectrum once more; the
spacing of the harmonics shows as one peak on a time-like axis (quefrency). It was a family of its
own, with the number 4, until 2026-11-13, and is a method of this family since (RAT §22.2): it
starts from the same FFT, and the power cepstrum and the autocorrelation of the log spectrum are a
Fourier pair. No cepstral method has been evaluated.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Cepstrum pitch determination | Noll, JASA 41(2) (SPEC prints 1969) | A | — | PR | not evaluated; cited as historical context for HR3 | no record | SPEC §13.3 |
| Cepstral domain pulse oximetry: PI from the amplitudes of the fundamental and harmonic peaks that the cepstrum identifies, motion peaks ignored; also a time-domain PI per pulse | Datex-Ohmeda US 7,139,599 | P | expired | PI; SpO2 by its title only | not evaluated | read (PI part) | PIM GE; SAC |
| Validating pulse oximetry signals in the potential presence of artifact | Datex-Ohmeda EP 1611847 A1 | P | withdrawn | VAL by its title only | not evaluated | read (title and PI part) | PIM GE |

### 2.4 Family 4 — an oscillator locked to the signal (candidate)

A model oscillator has its phase and frequency steered sample by sample until it follows the pulse;
there is no window. The rate is the oscillator's frequency and the quality of the lock is a
by-product. Found by the web search of 2026-11-13 (WS) and kept by Alex that day as the candidate
for the number 4, which the cepstrum had until then. Nothing is planned or evaluated; `HR4_PLL` is a
working label. Three things to keep in mind, argued in RAT §22.2: a locked oscillator follows a
rate but does not find it, so it needs a starting frequency from family 2 or 3 and inherits an
octave error of that seed; nothing is measured on our captures or on neonates; two of the patents
below are listed in force and their claims were not read.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Phase-locked loop on the PPG: phase comparator, oscillator and a loop filter that switches between noise, following and normal modes from an autocorrelation signal-to-noise estimate and the phase error | Murata US 9,717,462 | P | listed active, anticipated expiry 2034-09-16 (Google Patents, 2026-11-13) | PR, Q | not evaluated | summary | WS |
| Many digital phase-locked loops with different parameters run in parallel; those whose output correlates best with the samples are kept and their frequencies combined | Verily US 9,826,940 | P | listed active, adjusted expiry 2036-02-19 (Google Patents, 2026-11-13) | PR | not evaluated | summary (claims not read) | WS |
| Adaptive lattice notch filter as a frequency estimator; sequential notches remove the cardiac component and its harmonics to reach the respiratory rate | Park & Lee 2014, BioMedical Engineering OnLine 13:170 | A | — | PR | not evaluated | search result | WS |
| Adaptive comb filter in time on the derivative of the normalised IR: fundamental and four harmonics, the frequency fitted sample by sample so that the energy outside the comb is least. By the patent's own account a robust tracker of the rate but not a good finder; it can lock onto a harmonic or a sub-harmonic after minutes of motion, and at 30 bpm it needs 32-bit floating point to be stable | Nellcor US 7,865,224 (Baker & Yorkey); also US 6,836,679 (from memory, same family as US 5,853,364 of §2.3) | P | US 7,865,224 expired 2021; US 6,836,679 not recorded | PR | not evaluated | US 7,865,224: read (first third of the text); US 6,836,679: search result | H2; WS |

### 2.5 Candidate domains outside the families (web search of 2026-11-13)

Alex's question: is there any family besides time, time lag, spectrum and cepstrum? Eleven searches
and seven sources opened; not exhaustive. Almost everything found is adult, wrist-worn and about
motion; nothing is neonatal. The reference used for the taxonomy is the chapter *Photoplethysmography
Signal Processing and Synthesis* (Mejía-Mejía, Allen, Budidha, El-Hajj, Kyriacou and Charlton, in
*Photoplethysmography*, Elsevier 2021; preprint on peterhcharlton.github.io), which sorts PPG
analysis into time domain, frequency domain (spectral and time-frequency), machine learning and
nonlinear analysis in phase space. Outcome (Alex, 2026-11-13): of the three domains found that give
a pulse rate, the oscillator locked to the signal became the candidate family 4 (§2.4); the two
below were not taken up and have no number or identifier.

**Two domains that give a pulse rate.**

*Time-frequency plane.* The pulse is a ridge in a map of time against frequency; its height is the
instantaneous rate. The chapter files it under the frequency domain, so whether it is a family of
its own or a branch of family 3 is open.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Ridge of the pulse band in the wavelet scalogram, rescaled to an instantaneous frequency that gives the pulse rate | CardioDigital / Nellcor, "Method of analyzing and processing signals": US 8,255,029; US 9,192,336; US 10,182,764 | P | US 8,255,029: see §2.3; the others not recorded | PR | not to implement (same patents as the wavelet SpO2 row of §2.3) | search result | WS |
| De-shape short-time Fourier transform plus synchrosqueezing (deppG): instantaneous heart and respiratory rate from one PPG channel, tested during intense activity | Cicone & Wu 2017, arXiv 1701.02072 | A | — | PR | not evaluated | summary (abstract) | WS |
| Wavelet transform, Hilbert transform and empirical mode decomposition split the signal into components and a peak detector reads the cardiac one; judged very hard to embed for their processing cost | Mejía-Mejía et al. 2021, §3.6.1 | A | — | PR | context | read | WS |

*Phase space.* The signal is plotted against delayed copies of itself and the shape of the
trajectory (the attractor) is analysed; one loop is one pulse. It builds on a time lag, as family 2
does, but reads a geometry instead of a similarity.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Time-delay embedding in 2 to 4 dimensions, delay from one sample to 1/m of the pulse duration; needs no identification of individual pulse waves; symmetric projection (SPAR) onto the plane orthogonal to (1,1,1) reduces baseline drift; density plot for morphology and variability | Mejía-Mejía et al. 2021, §3.5 | A | — | Q, PR | not evaluated | read | WS |
| SPAR beat detector: a beat is a crossing of a Poincaré section by the projected attractor; delay = 1/N of the cycle length, itself the autocorrelation maximum between 0.4 and 1.5 s; on wrist PPG (WESAD, adults) its F1 is close to an existing detector at rest and lower under stress (about 63 % against 69 %) | Pettit, Charlton & Aston 2024, Front. Physiol. 15:1228439 | A | the paper declares a patent of one author on SPAR; number and status not read | PR, VAL | not evaluated; takes its delay from family 2 | summary | WS |

**Two groups that give no rate.**

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Statistics of the amplitudes with no time order: eight quality indices compared on 106 recordings of 60 s (perfusion, kurtosis, skewness, relative power, non-stationarity, zero crossing, entropy, agreement of two detectors); skewness best | Elgendi 2016, Bioengineering 3(4):21 | A | — | Q | not evaluated; Nellcor's derivative skewness is in §4.3 | search result (abstract) | WS |
| Learned models as a class of their own: regression, trees, support vector machines, neural networks; used for blood pressure, atrial fibrillation and quality assessment | Mejía-Mejía et al. 2021, §3.4; review: Nie et al. 2024, arXiv 2401.12783 | A | — | Q, PR | not evaluated; no neonatal training set | chapter: read (§3.4.4); review: search result | WS |

**Found, and not a family under the rule of the number (the domain of the analysis).**

- *Subspace and parametric spectra* (MUSIC, ESPRIT, a harmonic model fitted by least squares):
  another way to estimate the spectrum, so methods of family 3. Sources not read: an Analog Devices
  article on MUSIC for wrist PPG; a 2021 Frontiers in Human Neuroscience paper with ESPRIT.
- *Decomposition* (empirical mode decomposition, singular spectrum analysis, independent component
  analysis): a stage before a family, which then reads the cardiac component. TROIKA (Zhang, Pi &
  Liu 2015, IEEE TBME; search result) chains singular spectrum analysis, a sparse high-resolution
  spectrum and spectral peak tracking. See also the last row of §2.1.
- *Template of the beat* (dynamic time warping against an ideal period; Li & Clifford 2012,
  second-hand): needs the beat segmented, so a product of family 1.
- *Tracking across windows* (TROIKA's peak tracking with verification, Kalman and similar): a layer
  above the families. It bears on how a family would form one output from several methods
  (RAT §22.1). The makers' arbitrators between rate or SpO2 paths are in §4.3.
- *Higher-order statistics and cyclostationarity:* no pulse-rate estimator on PPG was found; the
  cyclostationary work found is on radar.

## 3. Methods of one output that do not rest on the pulse structure

### 3.1 SpO2: estimators of R

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| R as (AC/DC)red / (AC/DC)IR, an approximation of the ratio of log absorbance changes | Webster 1997, *Design of Pulse Oximeters*; ISO 80601-2-61 Annex EE | A, S | — | SpO2 | used: R-METHOD-1, kept as the alternative (SPEC §5.1; RAT §9) | Webster: no record; ISO: read | SPEC §13.4; RAT §9 |
| R from the RMS of AC over DC in each channel | TI SLAA655, TIDA-00301 | N | — | SpO2, PI | used: the form of R-METHOD-1 | read | RC §2.1; PIM chips |
| RMS ratio per block of 24 samples into a look-up table; the block is rejected if the red–IR correlation is below 0.75 | Masimo US 5,632,272 ("conventional engine") | P | expired 2014 | SpO2, VAL | context: the same pair as our R plus r gate | read | MN §1.2 |
| Regression of red on IR sample-to-sample differences, two-variable least squares; the goodness of fit detects motion and poor data | Ohmeda US 5,503,148 | P | expired 2014-11-01 | SpO2, VAL | used: direct antecedent of R-METHOD-2 and of its r gate (RAT §9) | read 2026-10-05 | RAT §9 |
| Slope of red on IR differences through the origin, after ln, band-pass and derivative | Nellcor US 5,351,685; US 6,411,833 eq. 8; US 5,853,364 | P | expired | SpO2 | used: R-METHOD-2 is this measurement step (MN §2.1) | read | MN §0.1, §1.1, §2.1 |
| R as the slope of the best-fit line of red against IR samples | Datex-Ohmeda US 5,934,277 | P | not recorded | SpO2 | context: same family as R-METHOD-2 | read | RC §2 |
| Saturation transform (DST): 117 trial saturations, a reference per trial, adaptive canceller of 6 cells, highest-saturation power peak = arterial | Masimo US 5,632,272 / 6,157,850; Goldman et al. 2000, J Clin Monit Comput 16:475; Jensen 2009, EMBC (code) | P, A | expired | SpO2, VAL | discarded for the library; offline tool at most (MN §5 item 9). With one coefficient it equals our regression (MN §2.1) | patents: read; Goldman: abstract only | MN §1.2, §2; RAT §9 |
| Closed-form separation of arterial and venous ratios from the decorrelation constraint at two times | Masimo US 5,632,272 eqs 98–103 | P | expired | SpO2 | measured, discarded: over six 1 s sub-windows it is ill-conditioned 91–98 % of the time (RAT §17) | read | MN §1.2, §2.3; RAT §17 |
| Skewness sweep: for each trial R, the skewness of X − R·Y; the R that cancels the pulse is arterial | Nellcor US 7,392,075 | P | in force until 2026-11-16 | SpO2 | not evaluated; offline first, after expiry (MN §5 item 6) | read | MN §1.1, §5 |
| Motion as a third source that multiplies both channels (wavelength-independent η) | Nellcor US 5,645,060 | P | expired | SpO2 | context: a limit of our simulation (MN §2.4) | read | MN §2.4 |
| Five wavelengths, 0.2 s regression slopes kept if correlated, 5 s histogram of saturation, mode as output | Nihon Kohden US 8,548,546 | P | expired 2025 | SpO2 | not evaluated | read | PIM Nihon Kohden |
| Isolated motion artefact measured on a TI AFE4400 board gives red–IR correlation 0.93–0.97 | Clarke 2015, Carleton MASc thesis | A | — | VAL | context: why the r gate cannot catch coherent motion (RAT §17) | read | MN §2.2 |

### 3.2 SpO2: calibration curve

Only the references that define a form of curve or a way to encode it. The catalogue of published
curves with numbers is RC §3 and RCU; the chronological list of calibration studies is RC §4.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Empirical calibration against arterial CO-oximetry in induced hypoxia | ISO 80601-2-61 Annex EE.2 and DD; FDA guidance 2013 | S | — | CAL | context: the reference method; our curves are fitted against a ward monitor (RCU; RAT §18) | read | RC §2.3 |
| Line `SpO2 = 110 − 25·R` | TI SLAA655, TIDA-00301; Webster 1997 through Kyriacou 2006 | N, A | — | CAL | used: the linear form; our coefficients are our own fits (SPEC §5.1; RCU) | TI: read; Kyriacou: second-hand | RC §2.1, §3 |
| Table of 184 entries, close to a quadratic in R | Maxim MAXREFDES117; AN 6845 | N | — | CAL | not used | read | RC §2.1 |
| Rational form above 70 % and a line below; spline knots; one set of constants per sensor bin | Nellcor US 6,801,797 / 8,078,246 | P | not recorded | CAL | listed among the alternatives of RAT §18 | read | RC §2, §3; RCU |
| Sensor-borne coding: a resistor encodes the red wavelength and selects a ROM curve; later a correction `a + b·R + c·R²` to a base curve, and memory in the sensor | Nellcor US 4,621,643; US 5,645,059; US 6,628,975; US 6,591,123; US 12,076,141 | P | 5,645,059, 6,628,975 and 6,591,123 expired; the others not recorded | CAL | context: precedent for one base curve plus a documented correction per probe (MN §4.1) | read | RC §2; MN §1.1, §4 |
| ROM look-up table from a regression on volunteers; a coding resistor names the probe type | Masimo US 7,274,955; US 7,428,432; US 6,770,028; US 5,758,644 | P | 5,758,644 expired 2015; the others not recorded | CAL | not used (we use a formula) | read | RC §2; MN §1.2 |
| Calibration surface that adds the DC-response ratio, for cyanotic infants | Masimo US 8,682,407 | P | not recorded | CAL | not evaluated | read | RC §2 |
| Clinician-entered additive offset, bounded to ±6 points and reset when the sensor comes off | Masimo LAB7035A; LAB-5476J | M | — | CAL | context: precedent for a bounded individual offset (MN §4.4) | read | MN §1.2, §4 |
| `S = f(φ)` with f depending on the red wavelength; a probe resistor sets an analog gain instead of a table | Nihon Kohden US 5,267,562 | P | not recorded | CAL | not evaluated | read | RC §2 |
| Rational form from the modified Beer–Lambert law with a path-length ratio and an offset | Blaney et al. 2026, arXiv 2609.30122 | A | — | CAL | listed (RC §3; RCU) | abstract read; coefficients second-hand | RC §3 |
| Curves stored in patient simulators as a table of one R per SpO2 point | Fluke ProSim 8 manual; Contec MS100 manual | M | — | CAL | used: the MS100's Nellcor preset is our bench reference (RCU) | read | RC §2.2 |

### 3.3 SpO2: averaging and response time

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Kalman filter on saturation: process noise 1.3 points/s, measurement noise from the regression residual in a 1 s window; a second filter on the slope | Nellcor US 5,853,364 family | P | expired 2016–2021 | AVG | not evaluated; candidate for adaptive averaging (MN §5 item 3) | read | MN §1.1 |
| Response modes of 3 s and 5 s target age; dynamic averaging that grows from 7 s, pulse search at 20 s, timeout at 40 s | Nellcor US 7,039,538; PM100N, PM10N, PM1000N manuals | P, M | expired 2024 | AVG, VAL | context for our fixed 6 s window (RAT §12) | read | MN §1.1; PIM Nellcor |
| Averaging times 2–4 to 16 s, 8 s by default; FastSat | Masimo Radical-7 manual; LAB5267B | M | — | AVG | context (RAT §12) | manual: read; FastSat: claim | MN §1.2 |
| Variable-mode averager between a weighted average and a weighted least-squares line | Masimo US 6,430,525 / 6,999,904 | P | expired 2020 | AVG | not evaluated (MN §5 item 3) | read | MN §1.2 |
| One averaging time of 5, 10 or 20 s (10 s by default, neonates included) for SpO2, pulse and perfusion | Philips IntelliVue instructions for use; *FAST SpO2 algorithm* | M | — | AVG, PI | context (PIM lesson 3) | read | PIM Philips |
| Zero-order Kalman filter that removes outliers from SpO2 and rate | Renesas OB1203 application note | N | — | AVG | not evaluated | read | PIM chips |
| Alarm integral (SatSeconds); parallel slow and fast SpO2 | Nellcor US 5,865,736; Masimo US 6,822,564 | P | expired | AVG | context for the IncuNest alarm layer, not the library (MN §5 item 10) | read | MN §1.1, §5 |

### 3.4 PI: definitions on a window and stabilisation

Per-beat PI is in §2.1 and spectral PI in §2.3 (cepstrum rows). Our own measurement of a median of 1 s sub-windows
is PIA.

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| PI = pulsatile over non-pulsatile infrared signal × 100; percent modulation | Masimo LAB3410F, LAB4583B; ISO 80601-2-61 201.3.245 and Annex II | M, S | — | PI | used: the definition (SPEC §5.1; RAT §11) | read | PIM Masimo; RAT §11 |
| PI from the RMS of a window, shown as a peak-to-peak equivalent | Renesas OB1203 application note | N | — | PI | used: the only published maker method built like PI-METHOD-1 | read | PIM chips |
| Baseline PI taken during good signal; under motion the lower of baseline and current is shown. Claims: PI by two techniques, per pulse and over several pulses, output the lowest | Masimo US 8,280,473 and continuations US 8,983,564; 10,194,847; 10,799,163; 11,006,867; 11,759,130 | P | continuations in force to 2027–2028 | PI | not used; bears on any robust PI we adopt (PIM lesson 2) | read | PIM Masimo |
| PI trend: one value per pulse, 30 s windows of 25 values, trimmed mean, values of unstable periods deleted | Masimo US 8,652,060 / 11,234,655 | P | in force to about 2029-01 | PI | not used; the closest published claim to a robust statistic over sub-windows | read | PIM Masimo |
| Perfusion indicator made independent of the saturation by a "patented method" | Philips *FAST SpO2 algorithm*; the patent was not identified | M | — | PI | context | read | PIM Philips |
| PIr, a relative pulsatile value; PIr × 3 = infrared modulation % | GE white paper on TruSignal; 3900 and TruSat manuals | M | — | PI | context | read | PIM GE |

## 4. Decisions built on the analyses

Three questions, kept apart by the decision they feed and not by the metric they use, since the same
metric (the share of energy in the harmonics, for example) appears in all three. Boundary with §3:
what corrects the value is in §3; what judges it is here.

### 4.1 Probe state — is there a probe on tissue with a pulse?

Result: a state. Ours: `ProbeState` (SPEC §3, §5.6).

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Probe-off rule: signal strength floor 0.02 %; between 0.02 and 0.25 % a minimum pulse density; at least 60 % of the energy at the pulse rate and harmonics | Masimo US 6,360,114 / 6,654,624; Radical-7 manual | P, M | expired 2020 | PROBE | not evaluated; candidate after a no-pulse bench campaign (MN §5 item 5) | read | MN §1.2 |
| Sensor-off detector: seven metrics into a small neural net; "maybe off" for 7 s before "off" | Nellcor US 6,035,223 | P | expired 2017 | PROBE | not evaluated | read | MN §1.1 |
| States Disconnect, Pulse lost and Non-pulse from the IR level, the modulation and the spectral energy above about 5 Hz | Nellcor US 5,853,364 | P | expired | PROBE, VAL | context (RAT §17) | read | MN §1.1 |
| Probe-off regions in a multi-wavelength ratio space | Masimo US 8,265,723 | P | in force until 2031-04-14 | PROBE | not to implement (MN §6) | read | MN §1.2, §7 |

### 4.2 Pulse validation — is this beat or this window an arterial pulse?

Result: the value is published or withheld. Ours: `hr3` is published only while `hr3_sqi > 0`, and
that is the SpO2 artefact gate (SPEC §5.4; RAT §17).

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| SpO2 validity tied to the identification of the pulse and of its harmonic structure | Nellcor US 6,083,172; Philips US 6,631,281; Masimo Signal IQ | P | expired | VAL | used: the idea behind the HR3 gate (RAT §17) | no record of the date | RAT §17 |
| Red–IR correlation as a check that the signal fits the model | Masimo US 5,632,272 (0.75); Ohmeda US 5,503,148; open-source MAX30102 algorithm "by RF" (0.8) | P, N | expired | VAL | used: `spo2_r_method2_reg_corr_min` = 0.8; blind to coherent motion (MN §2.2; RAT §17) | read | MN §2.2; RAT §9, §17 |
| Signal-quality metrics, tempered by a PID filter, decide whether the value is displayed at all | Nellcor US 7,006,856 | P | expired 2023 | VAL, Q | not evaluated | read | MN §1.1; PIM Nellcor |
| Accelerometer on the probe; quality threshold raised with the motion strength; low-quality measurements discarded | Philips US 9,788,793 | P | in force | VAL | not evaluated (needs an accelerometer) | read | PIM Philips |
| What is shown when validation fails: hold then clear at 40 s (Nellcor); held 30 s then dashes (Nihon Kohden); -?- (Philips); dashes (GE); value dimmed (Masimo) | maker manuals | M | — | VAL | context: v0.110 withholds without holding (RAT §17; PIM lesson 5) | read | MN §1; PIM table |
| SpO2 reported only above a PI floor and with the low-PI, low-SNR and motion flags off | Maxim PPG algorithm specification; Renesas OB1203 application note | N | — | VAL | context | read | PIM chips |

### 4.3 Confidence index — how far to trust the published value?

Result: a graded number. Ours: `spo2_sqi` (a ramp on PI), `hr1_sqi`, `hr2_sqi`, `hr3_sqi`; measured
and not adopted: comb purity (SAC) and the artefact ratio Q (PIA).

| What it does | Source | Type | Patent status | Serves | In this project | Citation | Detail |
|---|---|---|---|---|---|---|---|
| Signal IQ: one confidence marker per pulse, three tiers; alert when integrity, pulse density and harmonic ratio cross 0.3, 0.7 and 0.8 | Masimo US 6,606,511; US 6,684,090 / 7,024,233; Radical-7 manual | P, M | expired 2020 | Q | not evaluated; "SQI = confidence, PI = perfusion" (MN §5 item 2) | read | MN §1.2 |
| Metrics: derivative skewness, red–IR uncorrelation, ratio-of-ratios variance over 3 s and 9 s, pulse amplitude against a 60 s history, period variability, harmonicity | Nellcor US 7,194,293; US 7,006,856; US 6,035,223 | P | expired | Q | not evaluated; candidates for the joint SQI analysis (MN §5 item 2) | read | MN §1.1 |
| Several engines in parallel, each with a confidence, and an arbitrator that picks the output | Masimo US 5,632,272; US 6,157,850 claim 1; white paper LAB3213D | P, M | expired | Q | context: the architectural lesson (MN §0.5) | patents: read; white paper: claim | MN §1.2 |
| Three pulse-rate paths (adaptive comb filter, FFT, pattern matching) and a "best rate" arbitrator that picks one by confidence: fall-off of the harmonic energy, probability of arrhythmia, share of motion, signal-to-noise of the comb, red–IR uncorrelation; a Kalman filter on the change of rate | Nellcor US 7,865,224 | P | expired 2021 | Q, PR | not evaluated; the library publishes `hr1`, `hr2` and `hr3` side by side, with no arbitrator | read (first third of the text) | H2 |
| Two SpO2 paths and a confidence formula on variance and age; the more confident path wins | Nellcor US 5,853,364; US 7,302,284 / 7,315,753 / 7,336,983 | P | expired | Q | not evaluated | read | MN §1.1 |

## 5. Left out on purpose

- **Clinical evidence.** The comparative studies (missed events, bias by brand, averaging in the
  NICU, accuracy at low saturation) are evidence, not methods: MN §3. Neonatal PI ranges:
  `docs/pi_reference_ranges_by_age.md`.
- **Calibration studies and the factors that move the curve:** RC §4 and §5.
- **Third-party documents themselves.** This repository is public; where to obtain them is in
  `docs/third_party_references.md`.

## 6. Open items for the verification pass

1. **SPEC §13 has no record of a check.** Its twelve references were never compared with their
   sources. One looks wrong: Noll's "Cepstrum pitch determination" is printed as 1969 with JASA
   volume 41; from memory, volume 41 is 1967 and Noll's 1969 paper is the one on the harmonic
   product spectrum.
2. **Citations made from memory, never looked up:** Lahat et al. 1987 (spectral autocorrelation)
   and Kunieda et al. 1996 (autocorrelation of the log spectrum), both for SAC. Also from memory, to
   fill the rows without a source in §2.2: McLeod & Wyvill 2005 for the pitch method; Ross et al.
   1974 for the average magnitude difference function.
3. **Incomplete references in RAT §5.3:** Zong (slope sum function), Billauer, Li, and the
   Hilbert-envelope literature carry no title or year.
4. **Patent status to refresh.** Nellcor US 7,392,075 (skewness sweep) expires on 2026-11-16. The
   patents marked *not recorded* need their legal status read; none of the filing years is recorded.
5. **Patents listed in a report without a description:** Masimo US 11,224,381 and US 12,029,586 (in
   force, MN §7); Nellcor US 7,016,715 and US 7,534,212 (expired, MN §7); US 7,376,454, US 8,224,412,
   US 5,782,237 and US 5,577,500 (RC §7).
6. **The cepstral patent.** Our reports record only the PI part of Datex-Ohmeda US 7,139,599; what
   it does for SpO2 and for the pulse rate has to be read.
7. **Empty cells of §1.** Family 2 has no prior art recorded beyond the pulse rate and its own
   quality; whether the makers use the periodicity for PI, validation or probe state was not
   searched. On the rate itself there is only H2, one short search.
8. **§2.4 and §2.5 rest on one short search.** To read in full: the rows marked *summary* and
   *search result*, the wavelet-ridge patents, the SPAR patent the 2024 paper declares, and the two
   sources that could not be opened (the Analog Devices article on MUSIC; Hess's classification of
   pitch determination algorithms, which the search summarised as time-domain against short-term
   analysis). Nothing neonatal was found. For family 4, first the claims of the two patents listed
   in force (Murata US 9,717,462, Verily US 9,826,940) and a citation for the plain phase-locked
   loop as old art (RAT §22.2).
9. **H2 is a partial reading.** Two thirds of Nellcor US 7,865,224 are unread, and its family
   relation to US 5,853,364 and US 6,836,679 is not checked. Known only from search summaries and
   left out of the tables: an application US 2022/0192529 (holder not verified) with rate engines in
   time and in frequency chosen by a confidence score; how the Masimo US 6,002,952 family obtains
   the pulse rate; the plausibility scoring of rate candidates in a Philips FAST application note;
   Sicbaldi 2025 (Comput. Biol. Med.), a comparison of open-source rate algorithms on wrist PPG whose
   text could not be opened.
