# Pulse-rate methods for standard red/IR pulse-oximeter probes: do HR1, HR2 and HR3 contain the best methods known?

Literature survey for `incunest_afe4490`, 2026-11-22 to 2026-11-23. Analysis-session product: nothing in the
PulseNest or library repositories was changed by the survey itself.

**Scope (set by Alex).** Methods that obtain the pulse rate, beat times or inter-beat intervals from the PPG of a
standard red + infrared pulse-oximeter probe. Excluded: anything that needs an accelerometer or any other reference
sensor (an ECG or arterial-pressure input also excludes a method), and wearable or exercise applications. Methods
from speech, music, radar, ECG, fetal Doppler and pressure signals appear only as **[transfer]** candidates: their
numbers are never evidence about PPG.

## How the survey was done

| Stage | What | Size |
|---|---|---|
| Sweep, round 1 | 32 search angles, one agent each (Europe PMC, PubMed, Crossref, arXiv, Google Patents, web) | 1,710 queries, 375 sources read in full, 501 method entries |
| Completeness critics | three critics (estimation theory, pulse-oximetry industry, clinical benchmarking) | 15 follow-up searches, 36 entries flagged as doubtful |
| Sweep, round 2 | the 15 follow-ups | 651 queries, 191 sources read in full, 146 entries |
| Consolidation | duplicates merged into one catalogue per method group | 316 canonical methods, 88 of high priority |
| Verification | each high-priority item checked against its primary source, adversarially | 76 items (88 entries): 62 corrected in detail, 14 with a material claim wrong, 0 refuted outright |
| Synthesis | one section per topic, from the verified records only | 5 sections (chapters 1-5) |
| Adversarial review | planned for all five sections | done for chapter 2 (HR2) only: its 8 major findings are applied. Chapters 1, 3, 4 and 5 are verified drafts not reviewed adversarially (stopped to save usage) |

**Reading the numbers.** Every number comes from a verification record (`verify/<item>.md`) or from the project's own
documents (`docs/hr1_methods_20261116.md` = H1M, `hr2_methods_20261115.md` = H2M, `hr3_methods_20261114.md` = H3M).
Catalogue items that were not verified are cited as "not verified". Patent status is as read on Google Patents on
2026-11-22/23 and is not a legal opinion.

## The answer

**The owner can claim that no published method has been shown to beat HR1, HR2 or HR3 on standard-probe PPG. The
owner cannot yet claim that they contain the best methods known.** The difference is evidence, not method:

| Family | Verdict | Why |
|---|---|---|
| HR1 (beats in time) | **Qualified yes for the detector; no for the rules** | On the only public neonatal ECG-referenced benchmark (MIMIC PERform, 100 test neonates) the project has measured the two detectors that lead every published ranking, MSPTD and qppg/SSF. Its retuned SSF chain is level with them (pooled F1 96.4 %). The top five published detectors lie within about 1.3 F1 points, less than the 2-point effect of changing the protocol. Production is still `HR1_THR` (F1 91.5 %, misses 21.9 % of beats at 170 bpm and above). MorphSSF (the only detector reported above MSPTD, by its authors) and Pulses are untested. No interval-to-rate rule has ever been compared with another outside the project. |
| HR2 (time lag) | **Partly** | No single-window lag picker measured on PPG beats `HR2_ACF` (own bench, 3 neonates). Every leading lag method outside the project keeps several candidates and links windows; HR2 links nothing, and no study shows on PPG that linking helps. A Covidien patent in force (US 9,314,209, to 2034-05-24) may read on the production picker: freedom to operate needs counsel. |
| HR3 (spectrum) | **Partly, on own data only** | `HR3_SAC` is the best spectral estimator measured anywhere on neonatal standard-probe PPG against ECG (right in 97.9-99.8 % of windows, 3 neonates), and it removes production HPS's f0/3 picks. But no study compares spectral estimators on clinical PPG at all, SWIPE' and harmonic-model maximum likelihood were never run, `HR3_SAC` is not in the library, fails at 30 bpm and is weak above 180 bpm. |
| Across windows and families | **No** | The library has almost no layer above its estimators: one display gate (`hr_disp`, HR2 x HR3 agreement) never measured against a reference, per-family withholding, no tracking, no hold, no arbitrator. Every maker that discloses anything has these layers (Nellcor, Masimo, Philips, Nonin), with no published numbers. Published evidence for tracking and fusion is transfer or ICU ECG + pressure. |
| Inputs and evidence base | **No better input-side method shown** | Using red with IR for the rate, decomposition (EMD family) and learned models have no verified evidence of fewer wrong rates than HR1/HR2/HR3, and none has neonatal data. This rests on absence of evidence: no study compares IR-only against red + IR for the rate against ECG. |

**The common weakness is the evidence base, not the inventory.** HR2 and HR3 have never been scored on an open
ECG-referenced neonatal set, the project's own HR2/HR3 evidence is three neonates scored against a monitor number
read by eye every 10 s, and no benchmark covers 200-240 bpm or neonatal bradycardia.

## What to do first, across the families

Ranked by what the claim needs first, then by expected gain. Details, numbers and sources in the chapters.

| # | Action | Family | Failure it addresses | Board cost | Patents to watch |
|---|---|---|---|---|---|
| 1 | Score HR2 (`HR2_ACF`) and HR3 (`HR3_HPS`, `HR3_SAC`) on the MIMIC PERform neonates (tune on training, report test once, by rate band) | HR2, HR3 | No external neonatal number for any lag or spectral estimator | none (offline) | none |
| 2 | Mine the neonatal MIMIC-III Waveform DB records (8,486 record sets) for 200-240 bpm stretches; per-band miss tables for THR, SSF part 3, MSPTD, `HR3_SAC` | all | Missed beats and wrong rates at preterm rates; benchmark has 1.4 % of windows at 200 bpm or above | none | none |
| 3 | Use the coming preterm campaign as the held-out set, with the ECG waveform and a breathing signal | all | Test neonates already read three times; breathing hypothesis untested | none | none |
| 4 | Measure `hr_disp` against the ECG; design an arbitrator on the measured complementarity (oracle union of SSF + `R0` and gated `HR3_SAC`: right 91.0 % against 83.4 %) | across | The only shipping arbitrator is unmeasured | small | Nellcor 1995 scheme expired and free; avoid TI US 10,321,831 (Viterbi over spectral peaks, to 2036-08-16) and Mindray US 11,154,250 claim 6 (to 2037-09-14) |
| 5 | A check for confident sub-multiple errors (HR1 half rate, HPS one third): test whether breathing at HR/2 or HR/3 explains them | HR1, HR3, across | No quality index sees them; they are the worst failures | small | Covidien harmonic-rejection tests in force (to 2033-2034) |
| 6 | `HR3_SAC` at low rates: MS100 at 35-55 bpm, rate-matched window | HR3 | `HR3_SAC` right in 0 % at 30 bpm | small | none found |
| 7 | YIN's 1 - d' read at `HR2_ACF`'s lag as `hr2_sqi` | HR2 | Honesty and availability at a fixed error | one extra pass over the lags | none |
| 8 | MorphSSF (causal, period range to 240 bpm) and Pulses on the bench | HR1 | The two published contenders not measured | 4.7 kB code, 37 kB RAM (MorphSSF, authors' figures) | none found |
| 9 | SWIPE' (and, if cheap, harmonic NLS with order selection) on the HR3 bench | HR3 | "Best known" cannot be claimed without it | moderate | none found |
| 10 | Linking windows: fixed-lag Viterbi over a few HR2/HR3 candidates, against the plain pickers | HR2, HR3, across | Single-window decisions with no memory | about 10^3 operations per 0.5 s (estimate) | TI US 10,321,831 if candidates are spectral |
| 11 | Freedom-to-operate opinion on `HR2_ACF` against Covidien US 9,314,209 | HR2 | Eliminatory criterion | none | US 9,314,209 claim 1, to 2034-05-24 |
| 12 | Red with IR for the rate, one controlled test against ECG | inputs | Never tested here or anywhere | depends on method | maker patents (Masimo DST/FST, Philips, Nihon Kohden, Mortara): status per patent in chapter 5 |

Not recommended (verified): learned beat detectors (PPG-PT is eliminatory on cost; the others tie classical detectors
on clinical PPG or win only against weak baselines), EMD-family decomposition (sub-bpm precision gain on clean data
only, cardiac band capped at 150 bpm), respiration-harmonic cancellation (it deletes the pulse line when the heart rate
is a multiple of the breathing rate, common in preterm infants), beat-synchronous ensemble averaging on the rate path
(it reinforces a wrong period), TERMA with the papers' values.

## Working material

The survey's working folder is kept locally outside the repository: catalogue `catalogue/g1..g8_*.md` (316
methods), verification records `verify/*.md` (76), finder notes `finders/*.md` (47) and the downloaded sources
(about 3,500 third-party documents, which are not published here).

---


## Chapter 1 - HR1: beats in time (detectors, fiducial points, interval-to-rate rules, per-pulse qualification)

*Status: verified draft; not reviewed adversarially.*


Section of the pulse-rate survey report. Written 2026-11-23 from the verified records of the survey (verifier verdicts and
corrections applied), the consolidated catalogues and the project's own documents.

**Question.** Does HR1 (production `HR1_THR` + `R0`; measured `HR1_SSF`, `HR1_MSPTD`, `HR1_TERMA`; rules `R0`, `R1`, `R2`)
contain the best beat detectors and interval rules known for standard-probe PPG, above all for neonates? Which known methods are
better or complementary, and with what verified evidence?

**Shorthand used below.**
- **C22** = Charlton et al. 2022, the 15-detector benchmark. **C25** = Charlton et al. 2025 (MSPTDfast). **T18** = Desai & Shi
  2026, table 18 (MorphSSF paper). All three score the same 100 MIMIC PERform test neonates. Their numbers are median beat F1
  per record (±150 ms against ECG QRS beats), and the protocols differ, so compare values only within one paper.
- **H1M** = PulseNest `docs/hr1_methods_20261116.md`, the project's own family-1 study:
  - F2: the MIMIC PERform test neonates against ECG beats, on the project's causal bench and with its own QRS reference;
  - F3: the project's captures against the ward monitor's ECG heart rate (3 neonates);
  - parts 2 and 3: parameters chosen on the 100 training neonates.
- **"Wrong"** = more than 10 % from the ECG heart rate.
- `[record]` = the survey's verification record that holds the fact. Transfer evidence from other signals (fetal ECG or Doppler,
  music, speech, arterial pressure, camera PPG) is marked **[transfer]**. It is never evidence about PPG.

---

### 1. Verdict

**Beat detection: a qualified yes. Interval rules and per-pulse qualification: no. No evidence exists to name a best one.**

**What the project has measured.** On the only public neonatal set with ECG-referenced beats (MIMIC PERform, 100 test
neonates), it has measured, against ECG beats, the two detectors that lead every published neonatal ranking:
- MSPTD: median F1 95.9, first of 15 in C22;
- qppg/SSF: 95.2 in C22.

**What the published rankings can and cannot separate.**
- The top five published detectors lie within about 1.3 F1 points of each other.
- No paper tests one detector against another on neonates.
- Changing the protocol alone moves the same detector by about 2 points: MSPTD scores 95.9 in C22 and 93.8-93.95 in C25 and T18
  [hr1_msptd].

**The project's proposed SSF.** It was retuned out of sample (part 3: eye-closing 0.30 s, slope window 0.17 s, learning 2 s,
front-end high-pass 0.3 Hz). On the test neonates it reaches:
- pooled F1 96.4 %, against 95.7 % for the project's offline MSPTD (H1M);
- with `R0`: published 78.1 % of the time, 0.40 % wrong.

**What the owner can claim.** HR1 has been measured against the best-ranked open beat detectors on neonatal standard-probe PPG.
Its proposed SSF chain is level with them, and no published detector has shown a separable advantage over them.

**What the owner cannot claim:**
1. **That the library's HR1 is the best known.** Production is still `HR1_THR` + `R0` (library v0.124b). Its median sensitivity
   is 88.5 %, and it misses 21.9 % of beats at 170 bpm and above (H1M F2).
2. **That HR1 contains every leading detector.** Two published contenders are untested:
   - MorphSSF, the only detector reported above MSPTD on the neonates: +0.37 median F1, measured by its own authors, in sample,
     not held out;
   - Pulses: about 95.4 in C22 (read from a figure), and best of four on 2,055 adult sleep recordings.
3. **That `R0`, `R1` or `R2` are the best known rules.** No interval-to-rate rule and no per-pulse qualifier has ever been
   compared with another on probe PPG against ECG outside the project. The maker rules (Nonin, Masimo, Nellcor) come with no
   published data.
4. **Anything about 210-240 bpm, neonatal bradycardia or motion.** The benchmark has:
   - 1.4 % of windows at 200 bpm or above, 0.07 % at 220 bpm or above, and about 0.1 % below 100 bpm;
   - clean-ECG windows only.

   The project has also read its test neonates three times.

**Evidence strength.**
- The detector ranking is an independent head-to-head on clinical neonatal PPG, but on one dataset.
- Everything about rules, qualifiers and the 200-240 bpm range is the project's own bench, patents, or other signals.

---

### 2. Best known methods for this topic

The leading detector rows are separated by a protocol effect (about 2 points) larger than their differences. "Best known" here means
best ranked or most cited in the verified evidence, not proven best.

| Method | Why it counts as best known | Evidence strength | In the project? | Key source |
|---|---|---|---|---|
| **MSPTD / MSPTDfast v2** (multi-scale local-extremum scalogram, 6 s windows) | Neonatal median F1 rank on the MIMIC PERform test neonates: <br>- C22: first, 95.9 (15 detectors, range 50.7-95.9) <br>- C25: tied with MSPTDfast v2, about 93.8 (read from a figure) <br>- T18: second, 93.95 <br>Pooled adults + neonates (C25): MSPTDfast v2 96.8, significantly above qppgfast 95.9, at 0.0074 % vs 0.0491 % of signal duration in run time. <br>Fewest misses at 170 bpm and above on the project's bench (12.6 %) [hr1_msptd] | head_to_head_on_clinical_ppg (independent of Bishop & Ercole; one dataset) | measured_not_adopted. <br>- The project ran the local-maximum half only, offline. <br>- Beats arrive up to 11 s late. | Charlton et al. 2022, doi 10.1088/1361-6579/ac826d; Charlton et al. 2025, doi 10.1088/1361-6579/adb89e; Bishop & Ercole 2018, doi 10.1007/978-3-319-65798-1_39 |
| **Slope sum function** (Zong 2003 / qppg / qppgfast) | In the top group of every neonatal ranking but never first: <br>- C22: 95.2 <br>- C25: about 93.1 <br>- T18: 93.30 <br>The best causal chain on the project's bench after retuning (part 3) [hr1_ssf] | head_to_head_on_clinical_ppg | measured_not_adopted. <br>- Part-3 SSF + `R0` is proposed for lib v0.123. <br>- It is not in v0.124b. | Zong et al. 2003, doi 10.1109/CIC.2003.1291140; C22 |
| **MorphSSF** (slope sum + autocorrelation period + 0.6T running-maximum dilation) | The only detector reported above MSPTD on the neonates. <br>T18, test / train: 94.32 / 95.29 against 93.95 / 94.75 for MSPTD. <br>MIMIC test, pooled: +0.16 pp over MSPTDfast v2 (p = 0.0004). <br>Authors only; all datasets used for development; nothing held out [hr1_morphssf] | own_benchmark_on_clinical_ppg | absent | Desai & Shi 2026, Physiol Meas 47:115013, doi 10.1088/1361-6579/aec110 |
| **Pulses** (Lazaro; low-pass differentiator, RR-decaying threshold) | C22 neonates: about 95.4 (figure reading ±0.2, not separable from qppg and AMPD). <br>MESA (2,055 adult finger PPG recordings, ECG reference): best of four, F1 0.940 against COppg 0.930. <br>C22 does not count it among its eight robust detectors [hr1_pulses] | head_to_head_on_clinical_ppg | catalogued_not_evaluated (the `HR1_DRV` slot) | C22; Kotzen et al. 2021, CinC, doi 10.22489/CinC.2021.088 |
| **RR-consistency gate `R0`** (mean of 5 RR, published while CV < 0.15) | Not a literature "best". It is the only interval rule measured on neonates against ECG, and it is honest with every detector: 0.4-1.8 % wrong (H1M F2). <br>The CV of RR is also the first feature of published morphology gates [rule_morphology_classifier_gating] | own_benchmark_on_clinical_ppg | implemented | H1M; library spec §5.2 |
| **Masimo per-pulse recognition and pulse density** (US 6,463,311 B1) | The market leader's only disclosed per-pulse layer: <br>- curvature edges paired into triangular pulses; <br>- stick-model fit with rate-dependent limits; <br>- rise/fall ratio; <br>- amplitude against rate; <br>- median accepted period; <br>- pulse density. <br>Expired 2019-12-23. No data [hr1_masimo_pulse_recognition] | patent_or_claim_only | catalogued_not_evaluated | US 6,463,311 B1 (Google Patents, full text) |
| **Nellcor per-pulse rate path** (US 7,534,212 B2 + US 7,922,665 B2) | Interval rule: a variable-weight geometric IIR on qualified pulse periods, about 7 s response. Expired 2026-05-08. <br>Per-pulse qualification: neural nets trained on more than 300,000 manually classified pulses. In force to 2030-02-10. <br>No accuracy data [ctx_nellcor_oximax_rate_path, ml_beat_qualifier] | patent_or_claim_only | catalogued_not_evaluated | US 7,534,212 B2; US 7,922,665 B2 |
| **Per-beat fiducial: tangent intersection, 50 % upstroke point** | Best beat-to-beat timing in the comparisons that used ECG RR: <br>- Hemon 2016 (Masimo ear probe, IR, 12 adults): RMSE 5.69 ms for the tangent against 6.74 for maximum slope and 16.3 for the peak; <br>- Peralta 2019 (18 adults, red+IR finger): the 50 % point is best, not significantly better than maximum slope. <br>Adults, artefact-free [hr1_fid_tangent, hr1_fid_mid50] | head_to_head_on_clinical_ppg (adult, rest or tilt) | absent. <br>`HR1_THR` times the interpolated crossing of 0.6 x the running maximum. | Hemon & Phillips 2016, doi 10.1007/s10877-015-9695-6; Peralta et al. 2019, doi 10.1088/1361-6579/ab009b |
| **Learned beat detector PPG-PT** (GPT-style decoder, 443,493 parameters) | The abstract calls its result "state-of-the-art"; the results section calls it "comparable". <br>Median F1 98.04 on MIMIC PERform testing, pooled. <br>The comparators were copied from C22 under a different reference; no neonatal split [ml_ppg_pt] | own_benchmark_on_clinical_ppg | absent | Davies, Monsen & Mandic 2024, arXiv 2407.20775 |

Below the leading group and not "best known" on neonates (verified):
- **ABD** (Aboy 2005): below qppg/SSF and MSPTD in all three neonatal comparisons. C22: 94.6. C25: 92.5. T18: 92.88 [hr1_abd].
- **TERMA**: in C22 among the eight good detectors but below the leaders (H1M cites the C22 neonatal range 84.2-95.9 for that group). H1M F2: median F1 90.3, losing 33.4 % of beats at 170 bpm and above.

---

### 3. What the project already has that matches the best known

#### 3.1 A neonatal ECG-referenced bench that reproduces the published ranking

**The scoring follows C22.** H1M F2 runs the detectors causally on the 100 MIMIC PERform test neonates:
- 86 records scored;
- 46,781 reference beats;
- reference = two QRS detectors agreeing within 150 ms;
- ±150 ms tolerance.

**The order matches C22:** MSPTD and SSF, then THR, then TERMA.

| Detector (papers' values) | Median F1 % | Pooled F1 % | Se % | Missed at >= 170 bpm |
|---|---|---|---|---|
| `HR1_MSPTD` (offline) | 97.9 | 95.7 | 96.0 | 12.6 % |
| `HR1_SSF` | 97.5 | 96.1 | 95.4 | 14.0 % |
| `HR1_THR` (production) | 93.9 | 91.5 | 88.5 | 21.9 % |
| `HR1_TERMA` | 90.3 | 87.7 | 82.5 | 33.4 % |

- **Missed beats, not false ones.** PPV is 99.8 % or more for all four, so every error is a missed beat. C22 found the same in
  neonates and reports a neonatal PPG SNR of -10.9 dBc, against -5.9 dBc in adults [ctx_ppgbeats_mimic_perform].
- **Pooled F1 against median F1.** Pooled F1 favours SSF over MSPTD. SSF misses fewer beats at 100-140 bpm (3.9 vs 4.8 %) and at
  140-170 bpm (6.3 vs 6.6 %) [hr1_msptd].

#### 3.2 The retuned SSF is level with the best published detectors

**How it was chosen.** Part 3 of H1M chose the parameters on the 100 training neonates and reported them on the test neonates
and the project's captures. Chosen: eye-closing 0.30 s, slope window 0.17 s, learning 2 s, low-pass 15 Hz, high-pass 0.3 Hz.

**Against production (`HR1_THR` 0.6 + `R0`, front end v0.122):**

| Instrument | SSF part 3 + `R0` | Production |
|---|---|---|
| Test neonates, pooled F1 | 96.4 % | 91.5 % |
| Test neonates, published | 78.1 % | 63.4 % |
| Test neonates, wrong | 0.40 % | 0.57 % |
| Captures (3 ECG neonates), published | 86.2 % | 66.4 % |
| Captures, wrong | 0.40 % | 0.30 % |
| Captures, MAE | 1.51 bpm | 1.77 bpm |
| Captures, weighted total (lower is better) | 11.9 | 14.5 |

- **Range and dynamics.** Both start in 2.5 s and keep every MS100 plateau from 60 to 240 bpm. On real slow adult pulses
  (PhysioNet/CinC 2015) SSF reaches Se / PPV 98.6 / 98.1 % (H1M).
- **Limits** [hr1_ssf]:
  - It still reads 61 on the MS100 30 bpm plateau, because it counts the simulator's second wave.
  - Its missed beats per rate band after retuning have not been tabulated.
  - With the papers' parameters, the 0.34 s eye-closing locked out beats above about 176 bpm.

#### 3.3 The front end and the high-pass corner

**The common front end (lib v0.122) is the cheapest measured gain.** With the same detector and rule (board figures against the
bench chain):

| | Board, before v0.122 | Common front end |
|---|---|---|
| Published | 47.2 % | 66.4 % |
| Wrong | 0.3 % | 0.3 % |
| Start-up | 12 s | 2.5 s |

**The project found that the 0.5 Hz high-pass makes false beats on real slow pulses.** The undershoot after the peak climbs back
during diastole and looks like a second upstroke:
- at 0.5 Hz, 21.1 % of slow beats exceed qppg's threshold;
- at 0.3 Hz, 0.6 % do.

This finding is what made SSF eligible (H1M part 2 corrected, part 3).

#### 3.4 Interval-to-rate rules and their measured trade-off

**`R0` (production).**
- Honest with every detector: 0.4-1.8 % wrong on the test neonates, 0.3-0.6 % on the captures.
- Its weakness is availability, and the detector sets it: with the papers' values, TERMA 49 %, THR 63 % and SSF 74 % published
  (F2).
- Since lib v0.123, HR1 is NaN at `hr1_sqi` 0 and expires 2 s after the last crossing (spec §5.2).

**`R1`** (median of 5 accepted RR, 20 % rejection, modelled on Nonin).
- It publishes the most, at the cost of more error: 87-96 % published, 3.4-11.9 % wrong on the test neonates (F2).
- Even with gates it fails honesty on the test neonates. SSF part 3 + `R1` q >= 5/8 + CV publishes 87.5 % with 2.00 % wrong,
  above the 1.07 % limit. On the captures it publishes 93.4 % with 0.20 % wrong.

**`R2`** (RR accepted within 15 % of the `HR3_SAC` period).
- 75-81 % published, 1.8-2.8 % wrong (F2).
- It rescues TERMA: `HR3_SAC`'s period rejects the doubled RR.
- It depends on family 3, so it is not an independent check.

**Confident half-rate errors.** TERMA + `R0` shows the failure mode a CV gate cannot see. 173 of its 330 wrong values are half the
rate, 147 of them with `hr1_sqi` >= 0.8 (F2, post hoc).

#### 3.5 HR1 as a complement to HR3_SAC

On the captures (ECG subjects), with the papers' SSF values:
- SSF + `R0` is right in 7.6 % of outputs where `HR3_SAC` is not, and wrong in 5.0 % where `HR3_SAC` is right.
- Together they are right in 91.0 %; `HR3_SAC` alone in 83.4 %.

Above 180 bpm (SUBJ08), the share of outputs published and right is:

| Chain | Published and right |
|---|---|
| MSPTD + `R0` | 61.8 % |
| SSF + `R0` | 51.7 % |
| `HR3_SAC` | 51.0 % |
| THR + `R0` | 27.3 % |

Sources: H1M F3; [hr3_sac].

#### 3.6 What the project has that the literature does not offer

None of the published neonatal benchmarks gives four things the project's bench does:
- chain-level honesty (wrong share of what is published);
- availability at a capped wrong rate (1 % / 5 %);
- per-band miss tables;
- real slow-pulse checks.

C22, C25 and T18 report beat F1 only. The project's weighted criteria (honesty, availability, dynamics, range, precision, cost)
have no published counterpart for HR1.

---

### 4. Gaps, ranked

Ranked by what the owner's claim needs first, then by the expected gain.

#### Gap 1 - Evidence at 200-240 bpm and on held-out neonates (priority HIGH)

**Failure it addresses.** The missed beats at high rates, which are the dominant HR1 error on neonates.

| Detector | Missed at >= 170 bpm (F2) |
|---|---|
| THR | 21.9 % |
| SSF (papers' values) | 14.0 % |
| MSPTD | 12.6 % |

Above 180 bpm (SUBJ08), no chain is published and right more than 61.8 % of the time (H1M F3).

**Evidence (verified).**
- **The benchmark barely covers the range.** In the MIMIC PERform test neonates: median HR 156 bpm, P99 203. 11 % of windows are
  at 180 bpm or above, 1.4 % at 200 or above, 0.07 % at 220 or above; no published ranking covers 210-240 bpm
  [ctx_ppgbeats_mimic_perform].
- **Retuning is unmeasured at high rates.** Part-3 SSF has no per-band miss table; its pooled F1 moved only from 96.1 to 96.4
  [hr1_ssf].
- **The test neonates are no longer untouched.** Parts 2, 2-corrected and 3 have read them [ctx_ppgbeats_mimic_perform; H1M
  Limits].
- **A larger pool exists.** MIMIC-III Waveform DB 1.0 holds 8,486 neonatal record sets, with PLETH plus some ECG present 95 % of
  the time. Its limits: no beat labels, an ECG peak-picked at 2-14 ms sample intervals, and the monitor's processed pleth
  [ctx_mimic3wdb_neonatal_pool].

**Test on the bench.**
1. From the part-3 outputs already computed, tabulate missed beats by ECG-rate band.
2. Mine the neonatal mimic3wdb records for stretches where the ECG rate is 200-240 bpm. Score THR, SSF part 3 and MSPTD on them:
   misses, and half-rate outputs with `hr1_sqi` >= 0.8.
3. Use the hospital's new preterm infants as the fresh held-out set for any final claim.

**Cost on the board.** None (offline evidence).

**Patents in force.** None involved.

#### Gap 2 - MorphSSF, the one detector reported above the frontier (priority HIGH for the claim; expected gain small)

**Failure it addresses.**
- Missed beats at high rates. MorphSSF suppresses at 0.6T of a running period rather than a fixed eye-closing. Its fixed
  equivalent, SSF's 0.34 s, locked out beats above about 176 bpm.
- Owner's claim 2 in section 1 cannot be made without it.

**Evidence (verified, [hr1_morphssf]).**
- **Neonates (T18):** median F1 94.32 / 95.29 (test / train), against MSPTD 93.95 / 94.75 and qppgfast 93.30 / 93.93. No
  neonatal significance test.
- **Overall:** mean rank 1.29 against 2.86 (p = 0.29). MIMIC test: +0.16 pp against MSPTDfast v2 (p = 0.0004).
- **How it was tested:** by its authors only, with all 7 datasets used for development and none held out.
- **Against it:**
  - its autocorrelation period flags octave errors in 6.11 % of neonatal windows;
  - 5.99 % of true neonatal RR fall below 0.6T (7.67 % when HR > 120 bpm), so real beats risk suppression;
  - the default period range stops at 200 bpm;
  - its internal conditioning passes only 21 % of a 30 bpm sine.
- **Causal variant:**
  - -0.27 pp F1;
  - latency 1.22-1.37 s (medians);
  - 22 s warm-up;
  - warm-up restarts remove 12.5 % of MIMIC-test time.
- No public code.

**Test on the bench.**
1. Implement the causal variant from Algorithm 1 behind the 0.3 Hz front end, with the period range widened to 240 bpm.
2. Score on F2 (F1 by rate band, octave flags) and on `R0` chains (published, wrong, availability at 1 % wrong).
3. Check MS100 60-240 bpm, the real slow pulses and start-up. Compare with part-3 SSF.

**Cost on the board.** The authors' fixed-point C on an emulated Cortex-M4:
- 4.7 kB of code;
- 37.4 kB of static RAM, including a 12 kB input buffer;
- 321-377 thousand instructions per 20 s window (QEMU counts).

This is affordable. The constraint is the latency.

**Patents in force.** None cited or found [hr1_morphssf].

#### Gap 3 - Pulses, the measured derivative detector the catalogue never ran (priority MEDIUM)

**Failure it addresses.**
- The `HR1_DRV` slot is "catalogued, not evaluated".
- Owner's claim 2 in section 1 needs it.
- Missed beats.

**Evidence (verified, [hr1_pulses]).**
- **C22 neonates:** about 95.4 (figure reading). Not separable from qppg (95.2) or AMPD (95.2), with no test.
- **MESA (2,055 adult finger PPG recordings, ECG):** F1 0.940 against COppg 0.930, HeartPy 0.927 and IMS 0.908.
- **C22 does not rate it robust:** it failed PPG-DaLiA sitting, so it is not among the eight robust detectors.
- **Liability, computed from the code:** at the expected next beat, the threshold is still 0.54, 0.60 and 0.68 of the last
  derivative peak at 170, 200 and 240 bpm. That is the same mechanism as `HR1_THR`'s 0.6 rule, which loses beats when amplitude
  swings with breathing.

**Test on the bench.** One causal port on F2. Count missed beats at 170 bpm and above against part-3 SSF, then run its `R0`
chain.

**Cost on the board.**
- About 1.5 s of FIR differentiator delay plus 300 ms of look-ahead in a causal port.
- A new start-up rule (the original takes its first threshold from the first 10 s).
- The ecg-kit code is GPL-2.0, so write it from the algorithm, as for qppg.

**Patents in force.** None cited.

#### Gap 4 - A per-pulse qualification gate that would let a higher-availability rule ship (priority MEDIUM)

**Failure it addresses.**
- `R0`'s availability: SSF part 3 publishes 78.1 % on the test neonates and 86.2 % on the captures.
- `R1`'s honesty. Gated, it publishes 87.5 % / 93.4 % but is wrong 2.00 % on the test neonates. Ungated, it was wrong 3-13 %
  under artefact (H1M).
- Confident half-rate output (TERMA-type).

**Evidence (verified; none against rate error in neonates).**
- **Masimo US 6,463,311 (expired 2019-12-23).** Pulses are rejected for:
  - a rate above 250 bpm;
  - a stick-model fit outside its limit: 0.15 below 130 bpm, exponential from 130 to 160, 0.1 above 160;
  - a rise/fall duration ratio below 1.1;
  - a shallow ascending angle;
  - amplitude off the rate-amplitude curve.

  Pulse density = accepted periods / snapshot. No data. The tight limit above 160 bpm may withhold at 165-175 bpm
  [hr1_masimo_pulse_recognition].
- **Belal 2001/2002**, neonatal and paediatric pulses, visual labels, no ECG [ml_beat_qualifier]:
  - fuzzy classifier: Se 82 %, Sp 93 % on 1,420 test pulses;
  - ANFIS: AUC 0.92, Se 87 %, Sp 74 % on 2,843 pulses, better than a threshold rule only on specificity.
- **Pereira 2020** (13 adult neuro-ICU patients, 15,824 fingertip 30 s segments, visual labels). Accuracy: Karlen consecutive-pulse
  correlation 0.902, Sukor 0.848, Orphanidou 0.818; the authors' SVM 0.951 [rule_template_similarity_sqi].
- **Sukor 2011** (13 healthy adults, induced motion, ECG): HR error 0.49 ± 0.66 bpm with gating against 7.23 ± 5.78 without. Own
  method against no gating [rule_morphology_classifier_gating].
- **PCPD** (BIDMC, findpeaks-seeded reference, not ECG) [ml_pcpd]:
  - rejects synthetic pulse-free noise: F1 97.06 against MSPTD 91.57;
  - but loses on clean data: 97.03 against 98.79.
- **Key limit:** none of these gates sees regular every-other-beat loss. A template window doubles with the RR, and pulse density
  cannot see regular halving [rule_template_similarity_sqi, hr1_masimo_pulse_recognition].

**Test on the bench.** After `R1` q >= 5/8 on SSF part 3, add one gate at a time:
- Masimo pulse density;
- consecutive-pulse correlation;
- the Masimo shape rules rescaled to 100 Hz.

For each gate, measure availability at <= 1 % wrong on the test neonates, and the wrong share in the stratum of the captures
where `HR3_SAC` is not valid.

**Cost on the board.** A few features per beat: negligible.

**Patents in force.**
- **US 7,922,665 B2 claim 1, active to 2030-02-10:** modifying a pulse-qualification constant after a designated number of
  rejected pulses (claim 7: four). Claim 31 covers the same when amplitudes are below a threshold. Do not switch gate constants
  on rejection counts.
- **US 9,131,878 B2, active to 2027-05-07:** claims pulse-qualification constants.

Sources: [ml_beat_qualifier], [rule_hold_then_blank_policy].

#### Gap 5 - Missed-beat re-search anchored on a period (priority MEDIUM)

**Failure it addresses.**
- Beats lost when breathing swings the pulse amplitude. Production Se is 88.5 % because a beat lower than 60 % of a recent one
  does not cross (H1M).
- `R0` availability.

**Evidence (verified, [rule_searchback_missed_beat]).**
- **The only in-scope host is Aboy 2005.** An IBI longer than 1.75 x the median triggers a re-search of the candidate maxima. It
  was tested on paediatric ICU pulse-oximeter pleth with ICP and ABP, on the authors' own data, and the step was not ablated.
- **Not tested by the benchmarks.** Charlton's ABD code computes the correction but does not apply it, so the C22 neonatal ABD F1
  does not test it.
- **Blind insertion is rejected.** De Cooman 2014 (ECG/ABP, no PPG) and Huang 2020 (wearable + accelerometer) insert beats
  blindly, which could mask the onset of a neonatal bradycardia.
- **What it cannot fix.** A median-relative gap test cannot fire on a regular every-other-beat loss.
- **Already in the project's code, outside the PPG chains.** The bench's ECG reference QRS detector already has the Pan-Tompkins
  search-back. The measured SSF already lowers its threshold after 2.5 s without a pulse.

**Test on the bench.** When an RR exceeds 1.75 x the `HR3_SAC` period (or the median before the gap), re-search the gap for a real
candidate above a lower threshold. Never insert a beat without a candidate. Measure:
- Se / PPV by band;
- `R0` published and wrong;
- the delay to report a bradycardia step (MS100).

**Cost on the board.** Candidate buffer of about 2 s: small.

**Patents in force.** None found.

#### Gap 6 - A bounded-latency causal MSPTD / MSPTDfast v2 (priority LOW)

**Failure it addresses.**
- Misses at high rates: MSPTD is the least bad at 170 bpm and above.
- Availability: MSPTD + `R0` publishes 85.8 % with 0.4 % wrong on the captures.
- But its beats arrive up to 11 s late (dynamics criterion).

**Evidence (verified, [hr1_msptd]).**
- MSPTDfast v2 equals MSPTD on the pooled MIMIC test (96.8 both), at about one seventh of the run time.
- Its authors state it was not designed for real time, and nobody has tested a causal, bounded-latency version.
- The project's run is the peak half only.
- Weak points:
  - right on only 47.7 % of the 30 bpm plateau;
  - can lock onto 1.5 periods on exactly periodic pulses.
- The expected gain over part-3 SSF is small (pooled F1 95.7 against 96.4).

**Test on the bench.** A sliding 6 s window with a 1 s hop, committing beats only after a fixed age (for example 2-3 s). Compare
with part-3 SSF on F2, F3 and start-up.

**Cost on the board.** About 1e4-1e5 comparisons per 5 s at 20-50 Hz (verifier estimate). The code is MIT.

**Patents in force.** None found.

#### Gap 7 - Linking beats across windows: soft rate prior, beat-phase/period models (priority LOW)

**Failure it addresses.**
- HR1 has no memory beyond 5 RR.
- `R2`'s 15 % gate is hard.
- Nothing models beat phase and period jointly.

**Evidence (verified, all transfer or patent; none on PPG).**
- **Su & Wu 2017 [transfer]:** dynamic programming over beats with a log-interval prior, on fetal abdominal ECG. F1 median 98.28 %,
  mean 86.37 % (SD 22.9). Oracle best channel, no ablation [tf_rate_prior_dp_beats].
- **Katebi 2020 [transfer]:** an explicit-duration HSMM on fetal Doppler. F1 97.5 % on 5 fetuses, with no rival detector run
  [hr1_hsmm].
- **Krebs 2015 [transfer]:** beat-phase/period HMM on music only [tf_beat_phase_period_hmm].
- **Nellcor US 7,534,212 (expired 2026-05-08):** a per-pulse geometric IIR on qualified periods. No data
  [ctx_nellcor_oximax_rate_path].
- **Risks named by the verifiers:**
  - filling gaps fabricates beats (honesty);
  - lock onto 2T when beats are missed systematically;
  - HR1 would depend on HR3 and lose its independence for an arbitrator;
  - the project's `R2` chains already lose to SSF + `R0` on H+A (7.9-9.7 vs 5.9, H1M F2).

**Test on the bench.** A fixed-lag causal DP with a soft log-interval prior from `HR3_SAC`, compared with `R2`. Count inserted
beats against PPV and the response to a bradycardia step.

**Cost on the board.** A DP over a few candidates per beat: small. A full beat-phase HMM at 100 Hz: moderate.

**Patents in force.**
- TI US 10,321,831 claim 1, active to 2036-08-16: Viterbi path metrics over spectral peaks. It applies only if the candidates
  are spectral.
- US 7,922,665: see Gap 4.

#### Gap 8 - Per-beat normalised fiducial (50 % point or tangent intersection) (priority LOW)

**Failure it addresses.** RR jitter that feeds `R0`'s CV gate.

**Evidence (verified, [hr1_fid_tangent, hr1_fid_mid50]).**
- Hemon 2016: tangent 5.69 ms against maximum slope 6.74 ms RMSE.
- Peralta 2019: 50 % point best, not significantly better than maximum slope.
- Adults, rest or tilt, artefact-free.
- The mean rate does not depend on the fiducial.
- About 1 ms less jitter is about 0.003 of CV at 180 bpm, against a 0.15 gate. `HR1_THR` already interpolates its crossing at
  100 Hz.

**Test on the bench.** Re-time SSF/THR beats at the per-beat 50 % point, then re-run `R0`.

**Cost on the board.** Trivial.

**Patents in force.** None.

#### Gap 9 - Learned beat detectors (priority LOW)

**Failure it addresses.** Reviewer expectation only.

**Evidence (verified).**
- **PPG-PT** [ml_ppg_pt]:
  - result pooled over adults and neonates, in-domain fine-tuning on MIMIC PERform Training, comparators copied under another
    reference;
  - about 0.6-0.9 GFLOP per 10 s window, and the per-window min-max quantisation prevents streaming.
- **Peak-map networks** [ml_peakmap_net]:
  - no neonatal data and nothing above about 150 bpm;
  - TAU ties Elgendi across domains (BIDMC 1.30 vs 1.25 bpm);
  - Li 2026 beats neurokit2 defaults only on ±30 ms F1, with in-domain training.

**Test on the bench.** Only to record why it was not adopted: re-run the public PPG-PT weights on the test neonates with the
project's scoring.

**Cost on the board.** PPG-PT is eliminatory on cost.

**Patents in force.** None cited.

#### Considered and not recommended for HR1 (verified)

**Local interval estimation (CLIE)** [hr2_clie_lag_fusion]:
- One EMBC 2018 abstract on sleep-lab PPG (33 subjects): interval accuracy above peak-to-peak and derivative detectors, but no
  numbers.
- Built for BCG; tested only at 40-140 bpm.

**Nellcor beat-synchronous ensemble averaging** (US 7,039,538, expired 2024-03-08) [prep_ensemble_avg]:
- The trigger comes from the rate's own period, so a wrong period is reinforced.
- About 1 s of delay.
- At most an optional pre-filter.

**Edan multi-scale extremum search with predicted-window tracking** (CN 101991410 B, active to 2029-08-31, China only)
[hr1_edan]:
- Zero data.
- Its regularity test accepts doubled RR, the half-rate lock TERMA + `R0` already showed.

**Nihon Kohden band-pass and zero-crossing** (US 7,438,688 B2, active to 2027-05-10) [hr1_zero_crossing]:
- No data.
- Its rate is tied to a spectral seed, so it inherits f0/3 picks.
- Claims 1 and 8 require a parallel filter bank. A single seeded band-pass avoids them.

**Nonin 4-beat exponential average with interval-match flag** [rule_nonin_exponential_interval_match]:
- The tolerance is undisclosed, and the specification does not say mismatched beats are excluded.
- Regularly missed beats match each other, so the test accepts them.

**ABD** [hr1_abd]:
- Below the leaders on all three neonatal comparisons.
- About 59 times slower than MSPTDfast.
- Its benchmarked seed stops at 200 bpm.

---

### 5. What the evidence does NOT show

These absences were searched for by the survey's finders and verifiers, and checked again for this section where stated.

1. **No between-detector significance test on neonates.**
   - No paper tests one detector against another on the neonatal subset.
   - The top five lie within about 1.3 F1 points.
   - Changing the protocol moves one detector by about 2 points.
   - C25's significant result (MSPTDfast v2 above qppgfast) is pooled over adults and neonates [hr1_msptd, hr1_ssf].
2. **No second neonatal beat-level dataset.** All published neonatal ranking evidence uses the same 100 MIMIC PERform test
   neonates, run through the same ppg-beats toolbox. That data has three limits:
   - it is the monitor's processed pleth at 125 Hz, probe site not stated;
   - a median of only 4.0 of 10 min per neonate was scored in C22;
   - the ECG reference is automatic.

   Other public infant pleth + ECG sets exist (BCH sleep corpus, NSRR CHAT), but no per-detector results on them were found
   [ctx_ppgbeats_mimic_perform].
3. **No ranking at neonatal tachycardia or bradycardia.** The benchmark is almost empty at 220 bpm and above (0.07 %) and below
   100 bpm (about 0.1 %). The project's real slow-pulse check uses adult ICU records (H1M Limits).
4. **No published comparison of interval-to-rate rules on probe PPG against ECG.**
   - The makers' rules are disclosed in patents and manuals without data. This covers the Nonin exponential average, the Masimo
     median of accepted periods with pulse density, and the Nellcor per-pulse IIR.
   - The device studies compare whole black boxes and cannot rank algorithms [ctx_device_bench_neonatal_vs_ecg].
5. **No per-pulse qualifier validated against rate error in neonates.**
   - Belal's neonatal and paediatric classifiers were scored against visual validity labels.
   - The template and morphology gates were scored on adults with visual labels or induced motion.
   - None was shown to catch regular beat-halving.
6. **No learned detector with a neonatal-stratified result, and none tested above about 150 bpm** [ml_ppg_pt, ml_peakmap_net].
7. **No beat-level tracker (HSMM, DP, beat-phase HMM) evaluated for rate on standard-probe PPG.** An HSMM PPG segmentation exists
   (Hasanzadeh 2023, abstract only), but no in-scope rate result could be read [hr1_hsmm].
8. **No ECG-referenced neonatal beat benchmark under motion.** All benchmark windows are clean-ECG windows.
9. **No timing (fiducial) study in neonates, at high rates or under motion** [hr1_fid_tangent, hr1_fid_mid50].
10. **No maker beat detector disclosed with numbers.** This covers Masimo, Nellcor, Nonin, Edan, Nihon Kohden and Mindray.
11. **Search run for this section on 2026-11-23** (Europe PMC). Query: neonate/preterm/infant AND photoplethysmogram/pleth AND
    beat/peak/pulse detection, 2024-2026. Result: 93 hits.
    - None adds a neonatal probe-PPG beat-detector benchmark beyond C25 and T18.
    - A 2026 systematic review of AI-based neonatal heart-rate monitoring (Soni et al., World J Clin Pediatr, doi
      10.5409/wjcp.119386, PMID 42626232, abstract read) covers non-contact methods.
12. **Catalogued but not verified (cite only as not verified):**
    - a dedicated-probe neonatal beat count against ECG (Johansson, Oberg & Sedin 1999; detector undisclosed);
    - Fischer 2017 embedded contour segmentation with a per-pulse artefact flag;
    - RR-proportional refractories in other detectors (Kavsaoglu, ATM);
    - spectrally seeded detector windows (Li 2020, Bizzego DBD);
    - Fukuda JP 2021-016702 A (per-beat recursive threshold, legal status as read by the finder).

---

### 6. Sources

Read depth as recorded by the verifiers. "Full" = full text read; "abstract" = abstract only; "figure" = values digitised from a
figure.

**Neonatal and clinical benchmarks**
- Charlton PH, Kotzen K, Mejia-Mejia E, et al. Detecting beats in the photoplethysmogram: benchmarking open-source algorithms.
  Physiol Meas 2022;43(8):085007. doi 10.1088/1361-6579/ac826d, PMC9393905, PMID 35853440. Full text + figure 6b digitised.
- Charlton PH, Arguello-Prada EJ, Mant J, Kyriacou PA. The MSPTDfast photoplethysmography beat detection algorithm.
  Physiol Meas 2025;46(3):035002. doi 10.1088/1361-6579/adb89e, PMC11894679. Full text (table 4); neonatal values from figure 5b.
- Desai S, Shi W. MorphSSF: a fast slope-sum adaptive-period dilation algorithm for PPG beat detection. Physiol Meas
  2026;47(11):115013. doi 10.1088/1361-6579/aec110, PMID 43013975. Full text of the accepted manuscript (tables 17-19, 24-26, 28).
- Kotzen K, Charlton PH, Landesberg A, Behar JA. Benchmarking PPG peak detection algorithms using the ECG as a reference.
  Computing in Cardiology 2021;48. doi 10.22489/CinC.2021.088. Full text.
- MIMIC PERform datasets, Zenodo, doi 10.5281/zenodo.6950488 (version used by the project) / 10.5281/zenodo.6807402. Data file
  recount by the verifiers.
- PhysioNet MIMIC-III Waveform Database 1.0, https://physionet.org/content/mimic3wdb/1.0/. Project page and record lists read.

**Detectors**
- Bishop SM, Ercole A. Multi-scale peak and trough detection optimised for periodic and quasi-periodic neuroscience data. Acta
  Neurochir Suppl 2018;126:189-195. doi 10.1007/978-3-319-65798-1_39, PMID 29492559. Abstract; ppg-beats code (MIT) full.
- Zong W, Heldt T, Moody GB, Mark RG. An open-source algorithm to detect onset of arterial blood pressure pulses. Computers in
  Cardiology 2003;30:259-262. doi 10.1109/CIC.2003.1291140. Full text; wabp.c and qppg/qppgfast code full.
- Vest AN et al. An open source benchmarked toolbox for cardiovascular waveform and interval analysis. Physiol Meas
  2018;39:105004. doi 10.1088/1361-6579/aae021. Metadata (code source).
- Lazaro J, Gil E, Vergara JM, Laguna P. Pulse rate variability analysis for discrimination of sleep-apnea-related decreases in
  the amplitude fluctuations of pulse photoplethysmographic signal in children. IEEE JBHI 2014;18(1):240-246.
  doi 10.1109/JBHI.2013.2267096, PMID 24403422. Abstract; ecg-kit `PPG_pulses_detector.m` (GPL-2.0) full.
- Aboy M, McNames J, Thong T, et al. An automatic beat detection algorithm for pressure signals. IEEE TBME 2005;52(10):1662-1670.
  doi 10.1109/TBME.2005.855725, PMID 16235652. Full text.
- Elgendi M et al. Systolic peak detection in acceleration photoplethysmograms. PLoS ONE 2013;8:e76585.
  doi 10.1371/journal.pone.0076585. Full text (table 4).
- Chierico P et al. Improving wearable PPG monitoring with morphology-aware and learning-driven heartbeat detection. Sensors
  2026;26(21):6912. doi 10.3390/s26216912, PMC13766509. Full text.
- Davies HJ, Monsen J, Mandic DP. Interpretable pre-trained transformers for heart time-series data. arXiv 2407.20775 (2024).
  Full text.
- Zuo C, Zhao Y, Ye J. TAU: temporal attentive U-Net for PPG peak detection. arXiv 2503.10733 (2025). Full text.
- Li J et al. Peak-Detector: explainable peak detection via instruction-tuned LLMs. arXiv 2605.16452 (2026). Full text.

**Interval rules, qualification, search-back, quality gates**
- Nonin Medical. OEM III Module Specification and Technical Information, P/N 4518-001-10 Rev J, 2007. Full.
- Vikne H et al. PLoS One 2025;20:e0326674. doi 10.1371/journal.pone.0326674. Full text (Nonin pulse-rate RMSE, adults).
- Belal SY et al. A fuzzy system for detecting distorted plethysmogram pulses in neonates and paediatric patients. Physiol Meas
  2001;22(2):397-412. doi 10.1088/0967-3334/22/2/311. Abstract.
- Belal SY et al. Automatic detection of distorted plethysmogram pulses in neonates and paediatric patients using ANFIS. Artif
  Intell Med 2002;24(2):149-165. doi 10.1016/s0933-3657(01)00099-9. Abstract.
- Pereira T et al. A supervised approach to robust photoplethysmography quality assessment. IEEE JBHI 2020;24(3):649-657.
  doi 10.1109/JBHI.2019.2909065, PMC9553283. Full text.
- Karlen W et al. Photoplethysmogram signal quality estimation using repeated Gaussian filters and cross-correlation. Physiol Meas
  2012;33(10):1617-1629. doi 10.1088/0967-3334/33/10/1617. Abstract.
- Orphanidou C et al. Signal-quality indices for the ECG and PPG. IEEE JBHI 2015;19(3):832-838. doi 10.1109/JBHI.2014.2338351.
  Full text.
- Sukor JA, Redmond SJ, Lovell NH. Signal quality measures for pulse oximetry through waveform morphology analysis. Physiol Meas
  2011;32(3):369-384. doi 10.1088/0967-3334/32/3/008. Abstract.
- Clifford GD et al. False alarm reduction in critical care. Physiol Meas 2016;37(8):E5-E23. doi 10.1088/0967-3334/37/8/E5,
  PMC5017205. Full text (§6.11, forced detection).
- Silva I et al. Robust detection of heart beats in multimodal data. Physiol Meas 2015;36(8):1629-1644.
  doi 10.1088/0967-3334/36/8/1629, PMC4668947. Full text (§3.7).

**Fiducial timing**
- Hemon MCA, Phillips JP. Comparison of foot finding methods for deriving instantaneous pulse rates from PPG signals. J Clin Monit
  Comput 2016;30(2):157-168. doi 10.1007/s10877-015-9695-6, PMID 25902897. Full text (accepted manuscript).
- Peralta E, Lazaro J, Bailon R, Marozas V, Gil E. Optimal fiducial points for pulse rate variability analysis from forehead and
  finger PPG signals. Physiol Meas 2019;40(2):025007. doi 10.1088/1361-6579/ab009b. Full text.
- Pelaez-Coca MD, Hernando A, Lazaro J, Gil E. Impact of the PPG sampling rate in the PRV indices evaluating several fiducial
  points. IEEE JBHI 2022;26(2):539-549. doi 10.1109/JBHI.2021.3099208. Full text (author manuscript).
- Mohammadpoor Faskhodi M et al. PLoS One 2024;19:e0298354. doi 10.1371/journal.pone.0298354. Full text.

**Transfer candidates [transfer]**
- Su L, Wu HT. Front Appl Math Stat 2017;3. doi 10.3389/fams.2017.00002 (arXiv 1609.02938). Full text.
- Ellis DPW. Beat tracking by dynamic programming. J New Music Res 2007;36(1):51-60. doi 10.1080/09298210701653344. Full preprint.
- Katebi N et al. Unsupervised hidden semi-Markov model for automatic beat onset detection in 1D Doppler ultrasound. Physiol Meas
  2020;41(8):085007. doi 10.1088/1361-6579/aba006. Full text.
- Hasanzadeh N, Valaee S, Salehinejad H. Multi-observation HSMM for PPG semantic segmentation. ICASSP 2023.
  doi 10.1109/ICASSP49357.2023.10096539. Abstract.
- Krebs F, Boeck S, Widmer G. An efficient state-space model for joint tempo and meter tracking. ISMIR 2015 (zenodo 1414966).
  Full text.

**Maker patents** (status as read on Google Patents by the verifiers, 2026-11-22/23; not a legal opinion)
- US 6,463,311 B1 (Masimo, pulse recognition). Expired 2019-12-23. Full text.
- US 7,534,212 B2 (Nellcor, alternate heart-rate determination, Avg_Period IIR). Expired 2026-05-08. Full text.
- US 7,039,538 B2 (Nellcor, separate ensemble averaging). Expired 2024-03-08. Full text.
- US 7,922,665 B2 (Nellcor, pulse-rate calculation with alternate weighting; neural-net qualification). Active to 2030-02-10. Full
  text.
- US 9,131,878 B2. Active to 2027-05-07. Stored page (status and claims summary).
- US 7,438,688 B2 (Nihon Kohden, band-pass bank + zero crossing). Active to 2027-05-10. Full text.
- CN 101991410 B (Edan, pulse-rate searching). Active, anticipated expiry 2029-08-31, China only. Full text (machine translation).
- TI US 10,321,831 B2 (Viterbi over spectral peaks). Active, anticipated expiry 2036-08-16. Stored page.

**Device-level yardsticks** (cannot rank algorithms)
- Bohnhorst B, Peter CS, Poets CF. Crit Care Med 2000;28:1565-1568. doi 10.1097/00003246-200005000-00050. Abstract.
- Dawson JA et al. Acta Paediatr 2013;102:955-960. doi 10.1111/apa.12329. Abstract.
- Coleman J et al. Gates Open Res 2021;5:93. doi 10.12688/gatesopenres.13237.2, PMC8630397. Full text.

**Project documents** (read only)
- PulseNest `docs/hr1_methods_20261116.md` (H1M: F1-F3, parts 2, 2-corrected and 3, Limits).
- PulseNest `docs/algorithm_prior_art_index.md` §2.1.
- `incunest_afe4490_spec.md` §5.2 (library v0.124b: `HR1_THR`, `R0`, v0.123 expiry and NaN at SQI 0).

**Verification records used** (survey working folder `verify/`, kept locally outside the repository)
- Beat detectors and the benchmark: `hr1_msptd`, `hr1_ssf`, `hr1_morphssf`, `hr1_pulses`, `hr1_abd`, `ctx_ppgbeats_mimic_perform`,
  `ctx_mimic3wdb_neonatal_pool`.
- Fiducials and maker detectors: `hr1_fid_mid50`, `hr1_fid_tangent`, `hr1_masimo_pulse_recognition`, `hr1_edan`,
  `hr1_zero_crossing`, `hr1_hsmm`.
- Rules and maker rate paths: `rule_nonin_exponential_interval_match`, `rule_searchback_missed_beat`, `rule_hold_then_blank_policy`,
  `ctx_nellcor_oximax_rate_path`, `prep_ensemble_avg`, `hr2_clie_lag_fusion`.
- Quality gates and learned detectors: `rule_template_similarity_sqi`, `rule_morphology_classifier_gating`, `ml_beat_qualifier`,
  `ml_pcpd`, `ml_ppg_pt`, `ml_peakmap_net`.
- Transfer and context: `tf_rate_prior_dp_beats`, `tf_beat_phase_period_hmm`, `ctx_device_bench_neonatal_vs_ecg`, `hr3_sac`.

---

## Chapter 2 - HR2: periodicity in the time-lag domain

*Status: verified draft, adversarial review applied.*


Section of the final report of the pulse-rate method survey (2026-11-23).

**Question.** Does HR2 contain the best lag-domain estimators known for a standard red + IR transmissive
probe? HR2 today is the production `HR2_ACF`, plus `HR2_MPM` and `HR2_YIN` (measured) and `HR2_AMDF` (named
only). And what do the best known lag methods have that HR2 lacks: octave guards, multi-candidate tracking,
fusion of lag functions, the makers' search/lock rules?

**Conventions.**
- "H2M" is the project's `docs/hr2_methods_20261115.md`; "SPEC" is `incunest_afe4490_spec.md`.
- "Verified" means a record checked by the survey's verifiers (notes in `verify/<item>.md`). Items marked
  "not verified" come from the consolidated catalogue only.
- **Transfer** marks evidence from speech, music, fetal Doppler, ECG, pressure, bed BCG or radar. It is never
  evidence about PPG.
- "Wrong" means more than 10 % from the reference rate, as in the project.

---

### 1. Verdict

**Partly.**

**What the owner can claim.** No single-window lag picker measured on PPG beats `HR2_ACF`. "Best known" is
not claimed: several single-window rules were never measured (eSRPD ratio test, Covidien half-lag and angle
tests, lag-dependent bar, CLIE, AMDF; see G7, G9, G10).
- `HR2_ACF` takes the first normalised-ACF peak above an absolute bar. The makers' lag pickers use the same
  kind of rule (BCI 1995, first lobe above S(0)/4). YIN's threshold step is a first dip under an absolute bar
  on a different function (CMNDF).
- The only lag-against-lag head-to-head on NEONATAL PPG with an ECG reference is the project's bench:
  3 neonates, the ward monitor's ECG rate, 15,815 windows, 122-195 bpm. On it the canonical alternatives did
  not beat `HR2_ACF`.
  - With the papers' values: YIN (fixed window, threshold 0.10) publishes 16.4 % wrong, McLeod (k 0.9)
    17.5 %, against 4.4 %. (The 17.7 % for YIN in H2M part 1 came from a shrinking-window bench defect.)
  - Tuned out of sample, they tie or trail: weighted totals 22.2 (ACF), 22.3 (MPM) and 24.3 (YIN), where
    lower is better.
- One adult clinical-PPG comparison involving a lag function exists: Garde 2014 (CapnoBase, authors' own,
  clean anaesthesia data, 60-120 s windows). Its correntropy (kernel lag) function plus AR spectrum gave
  0.76 against 0.58 bpm for a plain AR spectrum, not significant: the lag function did not help the rate.

**What the owner cannot claim.**
- **That HR2 contains the best known lag *trackers*.** Every leading lag method outside the project (pYIN,
  Praat, RAPT/Kaldi, CORAL) keeps several candidates per window and runs a path finder across windows. HR2
  links nothing.
  - No study shows that this helps on standard-probe PPG.
  - The speech gains [transfer] are of two kinds. Ikuma's 62 -> 88 % correct is over a tallest-peak picker,
    which `HR2_ACF` is not. The pYIN gains (RPA 62.36 -> 83.31; recall from below 0.951 to 0.977-0.984) are
    over a first-dip-under-a-bar rule with speech thresholds, the same rule class as `HR2_ACF`, and come from
    candidates plus decoder together. Whether they carry over to `HR2_ACF`'s PPG-tuned 0.5 bar is untested.
  - `HR2_ACF`'s octave errors are only 1.2 % of the windows.
- **That HR2's quality index is the best known.** The evidence for YIN's 1 - d' is indirect: it ranked YIN's
  own picks (AUC 0.96, on 79.4 % published) better than the peak height ranked `HR2_ACF`'s picks (AUC 0.85, on
  85.4 % published), post hoc, on 3 neonates. Nobody has read 1 - d' at `HR2_ACF`'s lag (G1).
- **That the results hold beyond 3 neonates and 122-195 bpm.**
- **That HR2 reads the bottom of the range.** On the MS100 30 bpm plateau the bench reads it right in 50.3 %
  of the windows, but the board's HR2 was right in only 25.2 % on the same simulator sessions (H3M §G). The
  discrepancy is unresolved (G5).

**An open patent question.** Freedom to operate is open for the production picker itself: US 9,314,209
claim 1 is in force to 2034-05-24. This is not a legal opinion.

**Evidence strength.** One in-house neonatal benchmark on clinical PPG; on adult clinical PPG one
authors' own comparison (Garde 2014) and a few single-arm or abstract-only results (CLIE, CORAL, the MorphSSF
ACF step). Everything else is transfer or patent text.

---

### 2. Best known methods for this topic

| Method | Why it counts as best known | Evidence strength | In the project? | Key source (identifier) |
|---|---|---|---|---|
| First peak of a normalised ACF above an absolute bar (`HR2_ACF`) | No source measures a first-ACF-peak-above-a-bar rule against a tallest-peak ACF; in YIN's didactic Table I the absolute-threshold step only takes 1.69 -> 0.78 % on CMNDF (the big drop, 10.0 -> 1.95 %, comes from the difference function) [transfer]. The makers' lag pickers share the rule (BCI 1995, first lobe above S(0)/4; MAX30102_by_RF seed, unbiased ACF ratio >= 0.5). The case for it rests on the project's PPG bench, where it is the picker that fits. | own_benchmark_on_clinical_ppg | implemented (SPEC §5.3) | H2M; de Cheveigne & Kawahara 2002, doi 10.1121/1.1458024; US 5,558,096 A |
| YIN: cumulative mean normalised difference, first dip under a threshold; 1 - d' as the aperiodicity | The canonical lag estimator. In formal speech evaluations: gross error 1.03 % against 5.0 % for the ACF (2002, Table II); 0.55 % over 4 databases (2001). Best clean-speech GPE in Stroembergsson 2016 (1.39 %), but only on frames with agreed voicing. | head_to_head_on_clinical_ppg (project bench, independent of the authors) | measured, not adopted | doi 10.1121/1.1458024; H2M |
| McLeod pitch method: NSDF, first key maximum >= k x highest, clarity | A widely used normalised-difference picker. No independent comparison found in the literature. | head_to_head_on_clinical_ppg (project bench) | measured, not adopted | McLeod & Wyvill, ICMC 2005 (citation only, not read); H2M |
| pYIN: multi-threshold candidates plus HMM / Viterbi | Best signal-processing tracker at 10 dB in SwiftF0 (harmonic mean 79.99, against 76.10 for Praat). Its candidate set plus decoder (librosa pYIN) lifted RPA from 62.36 to 83.31 over raw YIN on PTDB (Yu 2026). | other_signal_only | absent | Mauch & Dixon 2014, doi 10.1109/ICASSP.2014.6853678 |
| Praat AC: window-corrected ACF, octave cost, Viterbi path finder | Best clean FFE of 15 methods in Jouvet 2017 (5.05 %) and of 3 in Stroembergsson 2016 (7.05 %). Ikuma 2025 is the only third-party ablation of a lag path finder: 62 -> 88 % correct. | other_signal_only | absent. The unbiased N/(N - tau) normaliser is the rectangular-window case of Boersma's window correction (my reading). | Boersma 1993, IFA Proc 17:97-110; Ikuma et al., arXiv 2501.04789 |
| RAPT / Kaldi: NCCF candidates plus DP | RAPT was best of 15 at 10 dB in Jouvet 2017 (FFE 8.5 %, against 10.2 % for Praat). The item itself was not verified. | other_signal_only | absent. Its two-segment energy normalisation is a close relative of the NSDF the project measured. | Ghahremani et al. 2014, doi 10.1109/ICASSP.2014.6854049; Jouvet & Laprie 2017, doi 10.23919/EUSIPCO.2017.8081482 |
| CLIE: lag-adaptive ACF, inverse AMDF and max-amplitude pairs, fused by Bayes, with a Q index | The only lag-function fusion with any in-scope evidence: sleep-lab finger PPG, abstract only, no numbers. | own_benchmark_on_clinical_ppg (abstract only) | absent | Hoog Antink et al., EMBC 2018, doi 10.1109/EMBC.2018.8512908; Brueser et al. 2013, doi 10.1088/0967-3334/34/2/123 |
| CORAL correloform: multi-window ACF, subharmonic summation, DP across windows | The only published lag method on PPG that combines an octave guard with linking across windows. | own_benchmark_on_clinical_ppg (authors only, gated, in-sample, no comparator) | absent | Trueb et al. 2026, arXiv 2608.14973 (preprint) |
| Lag-domain subharmonic summation: score T by the evidence at 2T and 3T | Best GPE at 10 dB in its authors' speech benchmark. The largest measured ablation gain for an octave guard. | other_signal_only | absent. Its frequency-domain counterpart was measured for HR3 and lost the subharmonic defence. | Singh & Demuynck 2025, arXiv 2509.16480 |
| eSRPD: period-synchronous NCCF, anti-doubling ratio test, forward check | Lowest total gross error, and lowest too-low gross error, in Sun's 9-detector table (2 speakers, in-sample). Out of sample it had the worst clean FFE of 15. | other_signal_only | absent | Bagshaw et al. 1993, doi 10.21437/Eurospeech.1993-241 |
| Maker search / lock state machines around a lag picker | What pulse-oximeter makers describe for linking lag windows. BCI: START -> CONFIRM -> NORMAL, the next period searched in 2/3-1.5 x the last, a confidence counter 0-5. Covidien: Search and Locked Modes on a 6 s ACF. | patent_or_claim_only | absent | US 5,558,096 A (expired); US 9,247,887 B2 and US 9,314,209 B2 (in force) |
| MorphSSF period step: biased ACF of the SSF, first interior maximum >= 0.6 x the largest, 20 s windows | The only external lag-domain octave statistic on clinical neonatal PPG. | own_benchmark_on_clinical_ppg (authors) | absent (a different variant) | Desai & Shi 2026, doi 10.1088/1361-6579/aec110 |

---

### 3. What the project already has that matches the best known

**3.1 Production `HR2_ACF` (SPEC §5.3).**
- Band-pass 0.5-5 Hz at the AFE rate, then decimation to 50 Hz.
- A 300-sample buffer (6 s since v0.121), recomputed every 0.5 s.
- An unbiased normalised ACF over lags 11-111, which covers 30-260 bpm plus a 3 bpm guard band.
- The first local maximum >= `hr2_min_corr` (0.5), with parabolic interpolation.
- `hr2_sqi` is the peak height.
- IR only.

**3.2 Its measurements (H2M).** 8 s buffer, 3 ECG neonates, 15,815 windows:

| Measure | Value |
|---|---|
| Published | 85.4 % |
| Right | 81.7 % |
| Wrong, as a share of what it publishes | 4.4 % |
| Half / third / other, as a share of windows with a reference | 0.9 / 0.3 / 2.6 % (it never reads double) |
| AUC of `hr2_sqi` | 0.85 |
| Wrong of published above 170 bpm (SUBJ08 / 09 / 11) | 4.9 / 7.9 / 8.4 %, against 1.0 / 5.1 / 2.3 % at 140-170 bpm |
| Available at 1 % wrong, out of sample (bar chosen on the other two subjects) | 50.2 % (63.2 % with `min_corr` 0.4) |
| MS100 simulator | bench: right in 50.3 % at 30 bpm; board: 25.2 % on the same sessions (H3M §G), unresolved; 100 % from 60 to 240 bpm |
| SUBJ10 (motion; another pulse oximeter as the reference) | 15.3 % published, 36 % of those wrong |

The 6 s buffer now in production was checked post hoc against the 8 s buffer:
- score 74.9 against 75.1;
- wrong of published 4.8 % against 4.4 %;
- start-up 6.0 s against 8.0 s at the median, and 10.6 s against 15.6 s at P90;
- 30 bpm unchanged at 50.3 %.

The bench mirrors the board on the ward sessions: the same class (within 10 %) in 99.5-100 % of the windows
(SUBJ10, motion: 89-100 %). The check does not cover the MS100 plateaus, where the two disagree at 30 bpm.

**3.3 The canonical alternatives, measured head to head (H2M parts 1-2).**

| | Published | Wrong of published | AUC | Score (fixed before the run) | Weighted total (0 best) |
|---|---|---|---|---|---|
| `HR2_ACF`, library | 85.4 % | 4.4 % | 0.85 | **75.1** | **22.2** |
| `HR2_MPM`, paper k = 0.9 | 74.7 % | 17.5 % (half the rate in 6.6 % of windows) | 0.71 | 38.7 | 46.0 |
| `HR2_YIN`, paper threshold 0.10, fixed window | 37.9 % | 16.4 % | - | 20.9 | - |
| `HR2_MPM`, tuned (k 0.5) | 72.6 % | 3.7 % | 0.91 | 65.1 | 22.3 |
| `HR2_YIN`, tuned (threshold 0.6) | 79.4 % | 4.9 % | **0.96** | 68.8 | 24.3 |

The tuned rows are out of sample (leave one subject out).

What these measurements show:
- **The picker decides, not the function.** The NSDF read with `HR2_ACF`'s picker gives the same result as
  `HR2_ACF`: 85.7 % published, 4.5 % wrong, AUC 0.85.
- **Tuning pushes every picker towards `HR2_ACF`'s rule.** The tuned values sit on the edges of their grids.
  Extended post hoc, MPM goes to k = 0.3 (score 65.5) and YIN to a threshold of 0.75-0.85 (score 71.3).
- **The cause on neonatal PPG.** The ACF at one period is often lower than at 2-5 periods. One SUBJ11 window
  at 164 bpm reads 0.75 at T, 0.85 at 2T and 0.88 at 5T. Relative pickers designed for speech therefore jump
  to multiples.
- **Coverage of `HR3_SAC`'s gaps is almost nil.**
  - `HR3_SAC` fails in 2.1 / 1.5 / 0.2 % of the windows (SUBJ08 / 09 / 11).
  - Within those windows `HR2_ACF` is right in about 10 / 20 / 0 %, which is 0.0-0.3 % of all windows
    (verified re-reading of H2M Q6).
- **What family 2 adds over HR3:**
  - about 2 s less start-up;
  - 30 bpm, with tuned MPM or YIN.

**3.4 The display fusion already shipped (SPEC §5.10, lib v0.124).** `hr_disp` shows the SQI-weighted mean of
HR2 and HR3 under these conditions:
- the two agree within 8 bpm;
- the better SQI is >= 0.8 and the worse one >= 0.5;
- the agreement has lasted longer than 1 s; after a break longer than 2 s that wait starts again.

On 19 replayed sessions it shows a rate 55 % of the time with the probe applied. It was never measured
against a reference. It is the only state that runs across windows and involves HR2.

**3.5 How HR2 maps onto the best known.**

| Feature of the best known lag methods | In HR2? |
|---|---|
| Normalisation of the lag function | Yes. The unbiased ACF is the rectangular-window correction, and the NSDF was measured equal. |
| Absolute-bar first-peak picker | Yes |
| Quality index | Yes, but the one measured better (YIN's 1 - d') is not adopted |
| Octave guard | Only the bar itself; HR2 never reads double |
| Several candidates per window and a path finder | No |
| Search / lock rules | No |
| Fusion of several lag functions, or of red with IR | No |

---

### 4. Gaps, ranked

#### G1 - YIN's 1 - d' as HR2's quality index (HIGH)

- **Failure addressed.** Honesty and availability at a fixed error. `HR2_ACF`'s peak height separates right
  from wrong with an AUC of only 0.85. At 1 % wrong it keeps 50.2 % of the windows (63.2 % with
  `min_corr` 0.4).
- **Evidence** (own bench; verified record hr2_yin):
  - Indirect: these figures score YIN's own picks, not `HR2_ACF`'s lag; the test below is what settles it.
  - Out of sample, tuned YIN's 1 - d' has an AUC of 0.96.
  - At 1 % wrong it keeps 70.6 % of the windows, with the same bar in all three folds.
  - Against a re-tuned `HR2_ACF` the real gap is 7.4 points, not about 20.
  - The analysis is post hoc (P2), on 3 neonates.
  - H2M decision 2 already proposes it as a candidate quality index for `HR2_ACF`'s lag.
  - The literature offers nothing on PPG beyond this.
- **Bench test.**
  - Compute d'(tau) on the same sweep and read 1 - d' at `HR2_ACF`'s chosen lag, not at YIN's own lag.
  - Score the AUC and the availability at 1 % wrong against the peak height.
  - Do it first on H2M with leave-one-subject-out, then on the MIMIC PERform neonates (G2), with SUBJ10 as a
    warning.
- **Board cost.** One prefix sum and one pass over the lags on top of today's sweep (H2M's estimate, not
  measured). Deterministic.
- **Patents.** None identified by the survey. YIN is a 2002 publication.

#### G2 - Evaluation beyond three neonates (HIGH)

- **Failure addressed.**
  - Every HR2 claim rests on 3 neonates, all at 122-195 bpm, with the ECG rate read by eye every 10 s.
  - `HR2_ACF` is weaker above 170 bpm (wrong in 4.9-8.4 % of what it publishes).
  - Nothing real was tested below 120 bpm.
- **Evidence** (verified records ctx_ppgbeats_mimic_perform and hr2_acf_first_peak):
  - HR2 and HR3 were never scored on the MIMIC PERform neonates. That set has 100 test and 100 training
    records of bedside-monitor pleth with an ECG beat reference.
  - The test neonates' heart rates: median 156, P99 203, 11 % of windows at or above 180 bpm.
  - The only external lag-domain octave number on this set is MorphSSF's: octave flags in 6.11 % of neonatal
    windows, against 0.72 % in adults. It comes from a different variant (biased ACF of the SSF, relative 0.6
    bar, 20 s windows; the flag also counts doubling), so it is not comparable with the project's 1.2 %. It
    does corroborate that neonatal PPG gives far more period-multiple errors than adult PPG.
- **Bench test.**
  - Run the library's HR2 chain (0.5-5 Hz, 50 Hz, 6 s) on the training neonates and tune there.
  - Report the test neonates once, by rate band, with the band at or above 170 bpm separately. Report
    published, wrong, half / third / other, AUC, and availability at 1 % wrong.
  - Repeat on the coming preterm campaign as the held-out set.
- **Board cost.** None (offline).
- **Constraints.**
  - The MIMIC pleth is processed by the monitor and has no raw red / IR, so G8 cannot be tested there.
  - Only clean-ECG windows were kept, which is optimistic for motion.
  - The project has already read the test neonates three times.
- **Patents.** None.

#### G3 - Linking windows: several lag candidates and a causal path finder, or a search / lock tracker (MEDIUM)

This is the largest structural difference between HR2 and the best known lag methods.

- **Failure addressed.**
  - HR2 publishes nothing in 14.6 % of the windows.
  - It is wrong in 4.4 % of what it publishes, and in 4.9-8.4 % above 170 bpm.
  - Under motion (SUBJ10) it is wrong in 36 % of what it publishes.
  - It publishes one lag per window, with no memory.
- **Evidence** (verified; all transfer unless stated).
  - **Path finder added to a weak picker (Ikuma 2025, third party; 703 sustained-vowel recordings, mostly
    disordered voices, 53 normal; 15,941 intervals).**
    - Praat's path finder raised the correct intervals from 62 % to 88 %, and cut subharmonic errors from
      35.4 % to 9.3 %.
    - But the baseline is Praat with its path costs set to zero, which takes the strongest ACF candidate. That
      is a tallest-peak picker, which `HR2_ACF` is not.
    - The path finder turned 1.6 % of correct intervals into f0/M errors.
    - Where subharmonics are strong (SHR > -10 dB), it was correct in only 3.4 %.
  - **pYIN (synthesised singing, scored within a semitone).**
    - Median recall 0.977-0.984, against below 0.951 for YIN.
    - Smoothing YIN's single answer (YIN+S) did not raise recall, though it had the best precision. The gain
      in recall needs several candidates.
  - **Yu 2026 (speech).**
    - Librosa pYIN as a whole, against raw YIN at a threshold of 0.15: RPA 62.36 -> 83.31 on PTDB.
    - Adding Viterbi to strong estimators changed RPA by -1.75 to +1.62 points.
    - The abstract reports that Viterbi locks into octave errors.
  - **Frame-selective DP (Yarra 2018, speech).** With the same candidates, no DP gives 1.04 % non-candidate
    errors and frame-selective DP 1.01 %. The gain comes from the candidates and their confidences, not from
    the DP.
  - **CORAL, the only PPG case (not evidence free of caveats).**
    - 4 paediatric polysomnography subjects, 75-155 bpm: r 0.971, RMSE 3.9 bpm, MAE 2.35.
    - Values are reported only above an SQI bar and after 10 s of smoothing, with parameters tuned in-sample.
    - No comparator, no ablation, and the DP is offline.
    - The authors concede it locks to half rate under alternating patterns.
  - **Fetal Doppler (Shi 2023; transfer; gated tracking after a lag estimator).**
    - Average absolute error 1.65 bpm, then 1.03 with a Kalman filter.
    - 0.74 with an SQI-weighted Kalman filter, at 87 % coverage.
    - Tuned on the same 10 subjects.
  - **Makers: no data at all.**
    - BCI (expired): a tracking range of 2/3-1.5 x the last period and a confidence counter.
    - Covidien Locked Mode: a 6 s ACF updated every 1 s (the same geometry as HR2); a band-pass around the
      last rate (+-10-25 %); a 24 bpm clip; a dropout counter.
    - Covidien runs the unlocked and locked modes in parallel, because the tracking band-pass "may start to
      track noise".
    - What is free: the bare state machine, the tracking band-pass and the hold, which sit in abandoned
      applications; and the whole Nellcor 1995 scheme (US 5,853,364 / 7,865,224 / 7,931,599, all expired):
      FFT re-seeds gated by a positive local ACF maximum and by 15 % continuity, best-rate arbitration on
      confidence, a Kalman filter on the rate, and hold-then-blank. No data. Its caveat: the ACF gate only
      checks re-seeds, so a confidently wrong comb is never corrected.
    - What is not: the qualification tests that keep the lock off noise. They are in granted patents in force
      to 2033-2035.
  - **Lock-in risk on neonates** (verified record ctx_cardioresp_ratio_occurrence).
    - Breathing sits near HR/2 or HR/3 for about 40-50 % of regular-breathing time (an order of magnitude).
    - A bradycardia step from 160 to 80 bpm falls outside a +-25 % lock band (160 x 0.75 = 120).
- **Bench test.** On the H2M windows and the MIMIC training neonates, compare three causal variants with
  plain `HR2_ACF`:
  - (a) up to 3 candidates per window, anchored at the first peak, plus first peaks under the bar; a cost on
    the change of log lag; a fixed-lag Viterbi of 2-4 hops (1-2 s);
  - (b) a BCI-style tracking range of 2/3-1.5 x with a confidence counter, falling back to the plain picker;
  - (c) a hill-climb from the last period, as in MAX30102_by_RF.

  Measure published, wrong, AUC, the time to follow the MS100 steps, and the recovery after a synthetic
  160 -> 80 bpm step. Adopt only under the H2M rule: at least +2 points of pooled score, and no held-out
  subject losing more than 1 point. When in doubt, withhold rather than hold.
- **Board cost.** About 100 lag states x (2J + 1) transitions per 0.5 s update, plus 100 x L back-pointers.
  This is my estimate (of the order of 10^3 operations), not a measurement. Deterministic.
- **Patents.**
  - **TI US 10,321,831 B2 (to 2036-08-16).** It claims Viterbi path metrics over spectral peaks, for
    transmission or reflection PPG, with no accelerometer. A lag-domain path does not literally take "a
    frequency domain spectrum" (the verifier's reading, not a legal opinion).
  - **Covidien qualification tests:** US 9,186,101 (half-lag test, to 2033-07-25); US 9,392,974 (angle /
    radius test, to 2034-03-20); US 9,220,423 (harmonic rejection, to 2033-10-30).
  - **Other Covidien claims in force:** US 9,186,108 claim 4 (a band-pass centred on the rate, with a skew
    metric, to 2033-10-30); US 9,392,976 claim 4 (a band-pass of an ACF combined from two template sizes, to
    2034-09-04).
  - **Nellcor US 7,922,665 claim 1 (to 2030-02-10).** It covers changing a qualification constant after N
    rejected pulses. Avoid that in the failure logic.
  - **Mindray US 11,154,250 claim 6 (to 2037-09-14).** It covers weighted maps of peak positions across
    windows. Check any cross-window vote histogram against it.

#### G4 - Freedom to operate of the production picker itself (MEDIUM)

- **Failure addressed.** A patent in force is an eliminatory criterion, and one may touch `HR2_ACF` as
  shipped.
- **Evidence** (verified record hr2_lag_dependent_bar; patent text only).
  - Covidien US 9,314,209 B2, claim 1 (Active, to 2034-05-24), covers any threshold that "varies as a
    predetermined function of lag values", together with a peak test and display in a pulse oximeter.
  - The project's unbiased ACF compared with a constant 0.5 is, mathematically, a biased ACF compared with a
    bar that falls linearly with lag: 0.5 (N - tau) / N.
  - Prior art with a constant bar exists: YIN (2002), and BCI US 5,558,096 (1995; the first lobe above S(0)/4
    on non-normalised sums).
  - CSD Labs US 10,856,811 is limited to phonocardiograms; on a plain reading of its claims it does not read on
    PPG.
- **Test.** A freedom-to-operate opinion from counsel. No bench work.
- **Board cost.** None.
- **Patents.** As above. This is not a legal opinion.

#### G5 - The bottom of the range: 30 bpm (MEDIUM)

- **Failure addressed.** The design range starts at 30 bpm.
  - On the bench `HR2_ACF` reads the MS100's 30 bpm plateau in 50.3 % of the windows, with both the 8 s and
    the 6 s buffer; the board's HR2 read it in only 25.2 % (H3M §G). Reconciling the two is part of the test.
  - `HR3_SAC` reads it in 0 %, and the proposed `HR1_SSF` reads 61 there (verified record hr1_ssf). If both
    proposed replacements are adopted, HR2 is the only family left that reads 30 bpm at all, and it does so
    half the time.
  - Tuned MPM and YIN read it in 100 %.
- **Evidence.** The project's simulator bench only:
  - it has no plateau between 30 and 60 bpm;
  - no real neonate below 120 bpm has been tested;
  - no external lag method was tested at 30-60 bpm on real PPG (CLIE stops at 40 bpm; CORAL's PPG data start
    at 75 bpm).
- **Bench test.**
  - Use the pending MS100 capture at 35-55 bpm.
  - Diagnose why the first peak misses at 30 bpm, although the 6 s buffer holds three periods (SPEC §5.3).
  - Compare `HR2_ACF` with tuned YIN's dip rule as a low-rate fallback, and with 1 - d' gating.
- **Board cost.** None to diagnose. A low-rate fallback reuses the same sweep.
- **Patents.** Covidien's lag-dependent bar (US 9,314,209, in force) is stricter below about 65 bpm (0.75 at
  30 bpm), so it would make this worse.

#### G6 - Beat-amplitude (envelope) normalisation before the ACF (MEDIUM)

- **Failure addressed.** The stated cause of tall lag peaks at 2T-5T: periodic amplitude modulation and
  baseline wander. It may also rescue relative pickers.
- **Evidence** (verified record hr2_envelope_normalisation; patent only).
  - US 2014/0073877 A1 (Covidien, abandoned), claims 1-4:
    - draw upper and lower envelopes that do not cross;
    - subtract the lower one and scale by (upper - lower);
    - remove the mean and autocorrelate;
    - its example window is 6 s.
  - It has no data, no population and no comparator.
  - A synthetic, noiseless toy removed the c(kT) > c(T) pattern. It is not evidence about PPG.
  - It does not target `HR2_ACF`'s main errors ("other", 2.6 %) or the misses above 170 bpm.
  - Scaling to unit amplitude can make noise look like strong beats, which weakens the peak-height SQI.
- **Bench test.** An offline A/B on H2M and the project's captures, with the library's NORM envelope tracker
  (SPEC §5.9) in front of the ACF. Score half / third / other, AUC, and SUBJ10.
- **Board cost.** Small: the envelope tracker already exists. Deterministic.
- **Patents.** No blocking claim found. US 9,241,670 B2 (to 2034-07-26) claims half-wave positive / negative
  conditioning, not envelope division (the verifier's reading of the claims, not a legal opinion).

#### G7 - Fusion of several lag functions, and the CLIE Q index (MEDIUM)

- **Failure addressed.** Availability and honesty. Q = peak / area is a ready-made quality index for a fused
  lag function.
- **Evidence** (verified record hr2_clie_lag_fusion).
  - **Mechanism.** Three functions over one candidate lag on each side of the centre: a lag-adaptive ACF, an
    inverse modified AMDF, and maximum-amplitude pairs. Each becomes a pseudo-PDF; they are multiplied and the
    argmax taken. The Q gate is 0.3.
  - **The only in-scope evidence is the EMBC 2018 abstract.** Sleep-lab PPG, 33 subjects, more than 900,000
    beats; the authors' 2021 self-citation calls it a finger clip.
    - It beat three peak detectors on intervals and HRV, and degraded least under simulated noise.
    - It gives no numbers, and its prior hurt clean signals.
  - **Elsewhere (camera plus bed BCG, 5 subjects).** Video PPG alone: 25.5 ms at 50.4 % coverage. All channels
    fused with the prior: 24.4 ms at 90.5 %. The fusion bought coverage, not accuracy.
  - **Limits.**
    - Tested at 40-140 bpm only, with no neonates and no octave-error rate.
    - Every result comes from the authors' group.
    - All three functions peak at multiples, so the two-lag window does not fix multiples.
- **Bench test.** Implement the three functions on IR in the H2M harness. Compare Q with 1 - d' and with the
  peak height: AUC, and availability at 1 % wrong.
- **Board cost.** Comparable to one extra lag sweep per function (my estimate). Deterministic.
- **Patents.** Not checked: the Google Patents query was blocked. The earlier BCG work had Philips co-authors,
  so search before adopting.

#### G8 - Red with IR in the lag function (LOW)

- **Failure addressed.** Motion and noise that differ between wavelengths. HR2 uses IR only.
- **Evidence** (verified record prep_mortara_acf_mix; patent only).
  - **Mortara US 6,564,077 B2 (expired 2021-11-17).**
    - It models IR as x = R s + r n and red as y = s + n.
    - For each lag it chooses r to maximise the normalised ACF of x - r y.
    - It then takes the global (tallest) ACF maximum, which is the period-multiple failure HR2 avoids. Only the
      mixing step is reusable.
    - The patent never outputs a rate and has no data.
    - It removes only noise whose ratio differs from R.
  - **Fixed-weight red / IR combinations lose the pulse in desaturation.** On the project's curve,
    ln IR - ln red leaves (1 - R) x IR: about 0.26 at SpO2 95 %, 0.13 at 90 %, and zero near 85 % (verified
    record prep_hayes_log_difference).
  - **Fusion gains need channels with independent noise**, and red and IR are not independent.
- **Bench test.** On the project's own captures (MIMIC has no red / IR): one r per window, then `HR2_ACF`'s
  picker. Look at SUBJ10 and the motion bursts.
- **Board cost.** One extra sweep per candidate r. Deterministic.
- **Patents.** Expired; free.

#### G9 - Explicit octave guards inside the lag function (LOW)

- **Failure addressed.** Readings at half and at a third of the rate: 0.9 % and 0.3 % of the windows. The
  headroom is about 1.2 points.
- **Evidence** (verified).
  - **Lag subharmonic summation.**
    - Singh 2025 (speech, transfer): GPE at 10 dB of 0.34 on TUG, against 0.38 for YIN and 0.43 for Kaldi.
      Removing the summation costs about 13 GPE points at 0 dB.
    - On a lag function that rises with lag, it raises 2T as much as T. On the SUBJ11 values (0.75 / 0.85 /
      0.88), 2T scores 2.60 against 2.46 for T with equal weights, and 1.51 against 1.39 with alpha = 0.5 (the
      verifier's arithmetic).
    - It guards against doubling, which HR2 never makes.
  - **Praat's octave cost.** At its default of 0.01 per octave it would pick 5T on the same window (0.857
    against 0.75).
  - **eSRPD.**
    - Its candidate thresholds (0.75-0.88) go against the project's finding that the 1T peak is often the
      lower one.
    - Only its forward check and its one-frame hold are worth testing as add-ons.
  - **Resonating comb (Böck 2015, music).**
    - It gains over a highest-peak ACF, not over a first-peak rule.
    - In a verifier's toy it flips to half rate when every other beat is 50 % stronger, at 170-200 bpm.
  - **ESACF.** Not verified. There is no error-rate evidence for it anywhere.
- **Bench test.** Add eSRPD's forward check behind `HR2_ACF`'s picker: the candidate must also hold on the
  next segment pair. Score half / third. Do not adopt a relative or summed picker without a measured gain.
- **Board cost.** Negligible.
- **Patents.** Several of these guards are in force:
  - the lag-dependent bar, US 9,314,209 (to 2034-05-24);
  - the half-lag test, US 9,186,101 (to 2033-07-25), whose claim 1 says "a fraction of" the lag;
  - the angle / radius cycle test, US 9,392,974 (to 2034-03-20);
  - Cameron's picket-fence confirmation, US 9,451,892 / 9,451,893 (status not verified).

#### G10 - Closing `HR2_AMDF` (LOW)

- **Failure addressed.** None measured. The project names the method, so it should close it.
- **Evidence.**
  - None verified on PPG.
  - The catalogue (not verified) reports that Drugman & Alwan 2011 dropped the AMDF as among the worst in
    noise.
  - The AMDF is the absolute-value relative of YIN's squared difference d(tau), which the project measured.
- **Test.** Read the AMDF with `HR2_ACF`'s picker on the H2M sweep, as was done for the NSDF. Close it if it
  equals or trails `HR2_ACF`.
- **Board cost.** Negligible.
- **Patents.** None identified.

---

### 5. What the evidence does NOT show (absences searched for)

**Searches that found nothing.**
- No ablation of a lag tracker (Viterbi, HMM or DP, with against without) on standard-probe PPG:
  - Europe PMC, (photoplethysmography or pulse oximetry) x (Viterbi or HMM or pYIN or dynamic programming) x
    (heart or pulse rate): 227 hits, first 60 titles scanned, none;
  - Praat x PPG: 25 hits, none a rate method;
  - "pulse rate" AND "pitch tracking": 0 hits.
- No use of SRPD or eSRPD on PPG, pulse rate or heart rate (0 relevant hits).
- No paper evaluates Mortara's red / IR ACF mixing.

**Comparisons that do not exist.**
- No comparison of YIN, MPM or AMDF on PPG outside the project's own bench. The project's earlier family-2
  search was one short search, not proof of absence.
- The only physiological use of YIN found is fetal Doppler (Voicu 2012), with no numbers in the abstract.

**Data that do not exist.**
- No maker document measures a lag-domain pulse rate: not BCI 1995, the Covidien 2012 family, Mortara, nor
  the Nellcor 1995 comb with its autocorrelation re-seed gate.
- No external octave-error figure exists for HR2's exact picker (unbiased ACF, absolute 0.5 bar) on PPG.
  MorphSSF's 6.11 % is a different variant.
- No lag method has been tested on real PPG at either end of the neonatal range:
  - above about 200 bpm (MIMIC PERform test neonates reach P99 203; CORAL's PPG reaches 155 bpm; CLIE 140 bpm);
  - between 30 and 60 bpm.

**Claims that no source supports.**
- That a lag-domain octave guard fixes sub-multiples on a lag function that rises with lag.
- That breathing causes the tall peaks at 2T-5T. The project labels this a hypothesis and has not measured it.
  Cardiorespiratory rate coincidences are common, but a coincidence is not an error rate.
- That any HR2 variant covers `HR3_SAC`'s gaps on the project's data.

**Not measured.**
- The board cost of MPM, YIN or any tracker.
- `hr_disp`, against a reference.
- Patents on CLIE / Brueser were not checked.

---

### 6. Sources

**Project documents (read-only).**
- `C:/PRJ/MOW/PulseNest/docs/hr2_methods_20261115.md` (H2M, parts 1-3): full.
- `C:/PRJ/MOW/incunest_afe4490/incunest_afe4490_spec.md` §5.3 (HR2) and §5.10 (`hr_disp`): read.
- `C:/PRJ/MOW/PulseNest/docs/algorithm_prior_art_index.md` §2.2: read.
- Survey files:
  - survey context `PROJECT_CONTEXT.md`;
  - catalogue `catalogue/g2_hr2_lag.md`;
  - verifier notes `verify/hr2_*.md`, `tf_covidien_locked_mode.md`, `prep_mortara_acf_mix.md`,
    `prep_hayes_log_difference.md`, `ctx_frame_selective_dp.md`, `ctx_ppgbeats_mimic_perform.md`,
    `ctx_cardioresp_ratio_occurrence.md`, `rule_kalman_sqi_tracking_fusion.md`, `hr3_mindray_psa.md` and
    `ml_octave_validator.md`.

**Literature** (read depth as recorded by the verifiers):

| Source | Identifier | Read depth |
|---|---|---|
| de Cheveigne A, Kawahara H. YIN. JASA 2002;111(4):1917-1930 | doi 10.1121/1.1458024 | full text |
| de Cheveigne A, Kawahara H. Comparative evaluation of F0 estimation algorithms. Eurospeech 2001 | no DOI | full text |
| Mauch M, Dixon S. PYIN. ICASSP 2014:659-663 | doi 10.1109/ICASSP.2014.6853678 | full text |
| Yu C-Y et al. Pitch smoothing using relative interval networks. 2026 | arXiv 2609.39852 | full text (method, Table 1) |
| Yarra C, Deshmukh OD, Ghosh PK. A frame selective dynamic programming approach. JASA 2018;143(4):2289-2300 | doi 10.1121/1.5031129 | full text |
| Ikuma T, Kunduk M, McWhorter AJ. F0 estimators with subharmonic voice signals. 2025 | arXiv 2501.04789 | full text |
| Boersma P. Accurate short-term analysis of the fundamental frequency and the harmonics-to-noise ratio. IFA Proc 1993;17:97-110 | no DOI | full text |
| Stroembergsson S. Interspeech 2016:525-529 | doi 10.21437/Interspeech.2016-240 | full text |
| Jouvet D, Laprie Y. EUSIPCO 2017 | doi 10.23919/EUSIPCO.2017.8081482 | full text |
| Drugman T, Alwan A. Interspeech 2011 | doi 10.21437/Interspeech.2011-519 | full text |
| Nieradzik L. SwiftF0. 2025 | arXiv 2508.18440 | full text (tables) |
| Meka N et al. SoFilNet. 2026 | arXiv 2610.18120 | baseline table |
| Ghahremani P et al. Kaldi pitch. ICASSP 2014 | doi 10.1109/ICASSP.2014.6854049 | full text (section 3.5) |
| McLeod P, Wyvill G. A smarter way to find pitch. ICMC 2005:138-141 | - | citation only, not read (numbers from H2M) |
| Voicu I, Girault JM, Menigot S. IRBM 2012;33(4):263-271 | doi 10.1016/j.irbm.2012.06.002 | abstract |
| Brueser C, Winter S, Leonhardt S. Physiol Meas 2013;34(2):123-138 | doi 10.1088/0967-3334/34/2/123 | abstract |
| Hoog Antink C et al. Biomed Opt Express 2015;6(8):2895-2907 | doi 10.1364/BOE.6.002895 | full text |
| Hoog Antink C, Leonhardt S, Walter M. EMBC 2018:3558-3561 | doi 10.1109/EMBC.2018.8512908 | abstract |
| Hoog Antink C et al. Sci Rep 2021 (the self-citation naming a finger clip) | doi 10.1038/s41598-021-87489-0 | methods paragraph |
| Brueser C et al. IEEE JBHI 2015;19(1):227-235 | doi 10.1109/JBHI.2014.2311582 | abstract |
| Trueb J, Kasbe A, Srinivasan A. CORAL. 2026 (preprint) | arXiv 2608.14973 | full text, with supplement |
| Singh A, Demuynck K. Harmonic summation-based robust pitch estimation. 2025 | arXiv 2509.16480 | full text |
| Ellis DPW. Beat tracking by dynamic programming. JNMR 2007;36(1):51-60 | doi 10.1080/09298210701653344 | full text |
| Bagshaw PC, Hiller SM, Jack MA. Eurospeech 1993:1003-1006 | doi 10.21437/Eurospeech.1993-241 | full text |
| Sun X. A pitch determination algorithm based on the subharmonic-to-harmonic ratio. ICSLP 2000 | doi 10.21437/ICSLP.2000-902 | full text |
| Boeck S, Krebs F, Widmer G. ISMIR 2015:625-631 | doi 10.5281/zenodo.1416026 | full text |
| Schreiber H, Urbano J, Mueller M. TISMIR 2020;3(1):111-125 | doi 10.5334/tismir.43 | full text, section 7 |
| Desai S, Shi W. MorphSSF. Physiol Meas 2026;47(11):115013 | doi 10.1088/1361-6579/aec110 | full text (accepted manuscript) |
| Charlton PH et al. Detecting beats in the photoplethysmogram. Physiol Meas 2022;43(8):085007 | doi 10.1088/1361-6579/ac826d | full text |
| Shi X et al. Fetal heart rate from Doppler with an SQI-assisted Kalman filter. Sensors 2023;23(24):9698 | doi 10.3390/s23249698 | full text |
| Joshi R et al. Cardiorespiratory coupling in preterm infants. J Appl Physiol 2019;126(1):202-213 | doi 10.1152/japplphysiol.00722.2018 | abstract and Table 2 |
| PICS database, PhysioNet picsdb 1.0.0 (the survey's own re-run) | PhysioNet | data and script |
| MAX30102_by_RF, algorithm_by_RF.cpp | github.com/aromring/MAX30102_by_RF | code read in full |

**Patents.** Status as shown on Google Patents pages saved 2026-11-22/23; most live re-fetches on 2026-11-23
were refused.

| Patent | Status | Read depth |
|---|---|---|
| US 5,558,096 A (Biochem International / BCI) | Expired - Lifetime, 2015-07-21 | full description |
| US 9,314,209 B2 (Covidien, spec A) | Active, to 2034-05-24 | full text, all claims |
| US 9,247,887 B2 (Covidien, spec B) | Active, to 2033-12-30 | full text of the cited figures; claims |
| US 9,186,101 B2 (half-lag test) | Active, to 2033-07-25 | claims |
| US 9,392,974 B2 (angle / radius test) | Active, to 2034-03-20 | claims |
| US 9,392,976 B2 (combined ACF) | Active, to 2034-09-04 | claims |
| US 9,186,108 B2 (skew metric) | Active, to 2033-10-30 | claims 1-7 |
| US 9,220,423 B2 (harmonic rejection) | Active, to 2033-10-30 | page of a family member |
| US 2014/0073877 A1 (envelope technique); US 2014/0073952, 0073959, 0073869, 0073974, 0073948, 0073949 | Abandoned | full text or claims, and status |
| US 9,241,670 B2 (normalisation) | Active, to 2034-07-26 | all claims |
| US 10,856,811 B2 (CSD Labs) | Active, to 2035-11-03 | rate section, all claims |
| US 6,564,077 B2 (Mortara) | Expired - Lifetime, 2021-11-17 | full text |
| US 7,865,224 B2 (Nellcor, adaptive comb with FFT re-seed) | Expired - Fee Related, 2021-06-30 | via the verifier notes |
| US 7,922,665 B2 (Nellcor) | Active, to 2030-02-10 | claims, via the verifier notes |
| US 10,321,831 B2 (TI) | Active, anticipated expiration 2036-08-16 | claims and the PPG passages |
| US 11,154,250 B2 (Mindray) | Active, to 2037-09-14 | claims, via the verifier notes |
| US 9,451,892 and US 9,451,893 (Cameron Health) | not verified | catalogue only |

---

## Chapter 3 - HR3: spectrum and frequency refinement

*Status: verified draft; not reviewed adversarially.*


Section of the final report of the pulse-rate method survey. Written 2026-11-23.

**Question.** Does HR3 (production `HR3_HPS`; measured B1/HPS2, harmonic sum, Hermes SHS, cepstrum `HR3_CEP`, `HR3_SAC`) contain the best spectral fundamental-frequency estimators known? Which known methods address its failures (f0/3 picks; 30 bpm with a 10.24 s window), what do the makers do spectrally for the rate, and what verified evidence is there?

**How to read the citations.**
- Project documents (read-only): H3M = `PulseNest/docs/hr3_methods_20261114.md`; SAC = `docs/spectral_autocorrelation_20261112.md`; H1M = `docs/hr1_methods_20261116.md`; RAT 17.1 = `incunest_afe4490_design_rationale.md` §17.1 (measured 2026-10-21).
- [V: item] = a verified record of this survey (`verify/<item>.md`). Items marked "not verified" come only from the consolidated catalogue `catalogue/g3_hr3_spectrum.md` and carry no numbers here.
- **Transfer** = speech, music, radar, camera, BCG, ECG or pressure evidence. It is never evidence about PPG.
- "Right" / "wrong" = within / more than 10 % from the reference, as in the project's benches.

### 1. Verdict

**Partly, and only on the project's own data.** `HR3_SAC` (autocorrelation along frequency of a local-contrast spectrum; measured, not adopted) is the best spectral rate estimator that has been measured anywhere on standard-probe neonatal PPG against an ECG reference. On 3 neonates it is right in 97.9 / 98.5 / 99.8 % of the windows, with harmonic errors of 0.2 / 0.1 / 0.1 %, and right in 96.6-100 % of the windows where production HPS reads one third of the rate [H3M B, C]. No study compares spectral fundamental estimators on clinical-probe PPG, neonatal or not. So nothing outside the project ranks `HR3_SAC` against SWIPE', harmonic-model maximum likelihood, PEFAC or the makers' engines. Those rankings exist only in speech and music, they are unstable across benchmarks, and none of those methods has been run on PPG.

What the owner **can** claim (own-benchmark strength):
- HPS is a known weak salience (sub-multiple picks), and the project has measured how weak it is.
- A better salience exists in the project (`HR3_SAC`). It fixes the f0/3 picks and the octave errors in sample: 3 neonates at 122-195 bpm, against the monitor's ECG heart-rate number read every 10 s.
- Frequency refinement is not a limiting factor: the MS100 maximum error with HPS is 0.18 bpm [RAT 17.1].

What the owner **cannot** claim:
- That HR3 contains the best known methods. SWIPE' and the harmonic-model family were never run, and `HR3_SAC` is not in the library.
- That `HR3_SAC` works out of sample, above about 180 bpm or below 60 bpm. Gated, it published a right value in only 51.0 % of 980 outputs above 180 bpm in SUBJ08 [H1M]. It is right in 0 % at 30 bpm on the MS100, and 35-55 bpm is untested.
- Anything about linking windows. Every maker engine read links or tracks across windows; HR3 does not. The obvious tracker designs are claimed in patents in force to 2036-2037 (TI, Mindray).

### 2. Best known methods for this topic

| Method | Why it counts as best known | Evidence strength | In the project? | Key source (identifier) |
|---|---|---|---|---|
| Spectral autocorrelation along frequency on a flattened spectrum (`HR3_SAC`; Lahat 1987 lifter-flattened spectral ACF; ACLOS; Rheem SAMDF) | Best measured spectral method on neonatal clinical-probe PPG against ECG: right 97.9-99.8 %, harmonic errors ≤ 0.2 % [H3M B]. Lahat 1987 already combined spectral flattening, spectral ACF, median smoothing across frames and an ACF-maximum quality index [V: hr3_sac] | own_benchmark_on_clinical_ppg (in sample, 3 neonates) | measured_not_adopted (C++ port behind an off-by-default flag) | H3M; SAC; Lahat et al., IEEE TASSP 35(6):741-750, 1987, doi 10.1109/TASSP.1987.1165224 |
| SWIPE' (sawtooth kernel on the square-root spectrum, prime harmonics, window of 8 candidate periods) | Most consistent independent winner among spectral saliences at positive SNR in speech. Best of 10 on 65 Parkinson's vowels (MAE 3.06 Hz, Tsanas 2014). Lowest GPE curve at positive SNR, and 6.17 Hz MAE at 20 dB against 12.82 for fast NLS (Wang 2022). Mid-pack in other benchmarks [V: hr3_swipe_prime] | other_signal_only (transfer) | absent | Camacho & Harris, JASA 124(3):1638-1652, 2008, doi 10.1121/1.2951592; Camacho 2007 dissertation |
| Harmonic-model maximum likelihood (exact or fast NLS) with MAP model-order selection and a GLRT | Statistically efficient: reaches the CRLB above -5 dB at 2-4 cycles, with the order known (Nielsen 2017). Independent speech tests contradict its practical superiority: highest GER at high SNR (Rehr 2014) [V: hr3_nls_order] | other_signal_only (transfer) | catalogued_not_evaluated (its harmonic-sum approximation was measured and rejected, RAT 17.1 B2) | Nielsen et al., Signal Processing 135:188-197, 2017, doi 10.1016/j.sigpro.2017.01.011 |
| Bayesian harmonic-model tracker (fast-NLS likelihood + Markov priors on f0, order and voicing; forward recursion) | The principled causal tracker over a harmonic salience. Gain over its own frame-wise salience on Keele babble: GER 0.57/0.41/0.30/0.24 → 0.53/0.36/0.27/0.24 at -5/0/5/10 dB (0-12 % relative) [V: hr3_bayes_tracker] | other_signal_only (transfer) | absent | Shi et al., IEEE/ACM TASLP 27(11):1737-1751, 2019, doi 10.1109/TASLP.2019.2930917 |
| Harmonic sum / subharmonic summation (Noll 1969; Hermes SHS) | White-noise ML approximation. In the 5-41-cycle HR3 window it is practically equal to exact NLS [V: hr3_nls_order]. Most accurate on clean neonatal windows (98-99 %), but it loses the sub-harmonic defence and admits motion windows to the SpO2 gate (Arms 10-11) [RAT 17.1] | own_benchmark_on_clinical_ppg (reference = HR1/HR2 consensus, not ECG) | measured_not_adopted | RAT 17.1 |
| Harmonic product spectrum (Schroeder 1968, Noll 1969): **production baseline, not best** | Classic. Precise when it publishes: right in 91.6/94.4/94.0 % of its valid windows. But it is silent in 11.8-30.2 % of windows and reads f0/3 in 4.0-6.6 % of valid windows [H3M B, C]. Outside the project the evidence is mixed and transfer only [V: hr3_hps] | own_benchmark_on_clinical_ppg | implemented | Schroeder, JASA 43(4):829-834, 1968, doi 10.1121/1.1910902; H3M |
| Philips FAST harmonic-family scoring with needle strings (maker) | Closest commercial analogue of HR3. Up to 10 red/IR needles per 1 s cycle on 8 s FFTs; strings with 25 s statistics; 1:2/1:3/2:3 family scoring (28-310 bpm); trimmed-mean output [V: ctx_philips_fast_rate_path] | patent_or_claim_only for the engine (device studies cannot isolate it, and the displayed PR may be beat-based) | catalogued_not_evaluated | US 6,631,281 B1 (expired 2019-06-10) |
| Nellcor adaptive comb (fundamental + 3 harmonics) with a gated 10 s FFT re-seed (maker) | The only maker rate path read that checks a spectral candidate against an autocorrelation local maximum, and against the candidate of 10 s earlier (15 %), before using it [V: tf_nellcor_adaptive_comb] | patent_or_claim_only | catalogued_not_evaluated | US 5,853,364 A; US 7,865,224 B2 (expired 2021-06-30) |

#### 2.1 What the makers do spectrally for the rate

All from patents read in full or in their rate sections. **No maker patent reports any rate accuracy**, and the device-level studies cannot tell which engine produced the displayed rate.

- **Masimo** (US 5,632,272, expired 2014-05-27) [V: ctx_masimo_set_rate_path].
  - An IR snapshot of 570 samples at 62.5 Hz is log-normalised and band-passed (34-250 bpm), which leaves 270 samples (4.3 s).
  - A Chirp-Z spectrum covers 30-250 bpm. Without motion, the rate is the **first peak at or above 1/20 of the largest**. With motion, the highest peak after an adaptive canceller built from the SpO2 value is taken.
  - The rate is slew-limited to 20 bpm per 2 s and smoothed exponentially.
  - On neonates the first-peak rule would take breathing (30-80/min) whenever it exceeds 5 % of the cardiac line. It is biased toward the sub-multiple error that HR3 already makes.
- **Philips FAST** (US 6,631,281, expired 2019-06-10) [V: ctx_philips_fast_rate_path].
  - Candidate lists, family scoring, and plausibility against the last output; a 13 s trimmed mean extended up to 70 s.
  - A sub-harmonic family is chosen if it has at least 0.3× the winner's strength. This favours lower families, the wrong direction for f0/3.
  - The patent itself remarks that neonatal harmonics may be cleaner than the fundamental.
  - Philips' 2023 note says the displayed PR is "based on detected pulsations per minute".
- **Nellcor** (US 5,853,364 / 7,865,224, expired) [V: tf_nellcor_adaptive_comb].
  - A Nehorai-Porat adaptive comb (N = 4 teeth) tracks the IR rate.
  - A 512-point FFT every 10 s re-seeds it only when all of these hold: the comb's confidence is below 50 (or it is uninitialised); the candidate's prospective confidence is at least 50 and its S/N ≥ 0.7; it lies within 10 bpm of a positive autocorrelation local maximum; and it is within 15 % of the candidate 10 s earlier.
  - Claim 8 of US 7,865,224 claims the rate as a frequency with a peak in both the power spectrum and the autocorrelation.
  - The rate is held for up to 40 s, then blanked.
- **Mindray PSA** [V: hr3_mindray_psa]. Patents in force: US 11,154,250 B2 (to 2037-09-14), US 11,872,060 B2 (to 2037-02-10), EP 3473171 B1 (to 2036-06-15).
  - If a fundamental + multiple pair has agreeing per-peak SpO2, the lowest line is taken directly.
  - Otherwise a 20-peak cache over a 20 s fill folds multiples (up to 4×) into the candidate fundamental, with a stability threshold (example: 16 s).
  - There are no data. The design favours the lowest line, so a steady f0/3 respiratory line would collect the pulse's weight.
  - US claim 6 covers weighted time-varying maps of peak positions in general.
- **Nihon Kohden.**
  - US 8,649,837 B2 [V: hr3_nk_rule_table]: a six-level harmonic-confirmation rule table with a fallback to the previous rate ±10 %, claimed for subjects "in an exercised state". Expired (fee related, lapse effective 2026-02-11). Its level 2 would accept a respiratory fundamental whose 3rd harmonic is the cardiac line.
  - US 7,438,688 B2 [V: hr1_zero_crossing]: the largest FFT peak selects one of 8 fixed band-pass filters, then zero crossings are counted. Active to 2027-05-10.
  - US 8,175,669 B2 [V: prep_spectral_ratio_labelling]: the band with the minimum red/IR ratio is the fundamental. Its claims cover SpO2 only. Active to 2030-07-05.
- **GE** (US 2008/0167541 A1, abandoned 2012-01-03) [V: hr3_ge_resp_notch]. The only maker document that notches the respiratory line before taking the highest weighted peak. The notch is about 10 bpm wide at RR, with optional notches at its harmonics. In an optional embodiment there are no notches when the modulation is at least 0.5 %. No data.
- **Common pattern.**
  - No maker takes the plain argmax of a harmonic product.
  - They keep candidate lists, and score harmonic families or confirm harmonics.
  - They prefer the lower line, which guards against 2× and 3× errors, not against f0/3.
  - They link or track across windows.

#### 2.2 Methods considered and not best for this signal (verified)

- **SHR** (Sun 2000) [V: hr3_shr; V: hr3_hps].
  - It resolves only the 2:1 ambiguity, and by design keeps the lower pitch when sub-harmonic energy is real. That is the opposite of what HR3 needs with breathing at f0/3.
  - Camacho 2007 ranks it 7th of 13 on speech.
  - The "28.2 % vs 0.78 %" contrast between HPS and SHR holds for one male speaker only. On the female speaker HPS (1.61 %) was second best of nine.
- **Aboy clipped harmonic sum** (Aboy 2005, h(w) = Σ min(2p(w), p(kw))) [V: hr3_aboy_clipped_sum].
  - It was validated only inside a whole beat detector, on 6 PICU patients (pleth Se 96.45 / +P 95.54 %), by its authors, with the spectral stage not isolated.
  - In a toy spectrum with the project's harmonic levels, f0/3 wins once breathing exceeds about 0.3 of the cardiac line.
- **CWT ridge** [V: tf_cwt_ridge]. Arbitrated with a spectral candidate, it reads on US 8,285,352 claim 1 (Nellcor, active to 2031-07-28), which is eliminatory.
- **deppG de-shape** (cepstral mask × STFT, Cicone & Wu 2017) [V: tf_deppg_deshape].
  - It would likely remove harmonic-product f0/3 picks, but it does not suppress a real respiratory line at f0/3.
  - It was tested on CapnoBase only, with no neonates, and extracts one global curve offline.
- **Respiratory-harmonic cancellation (radar)** [V: prep_resp_harmonic_cancel]. All the evidence is chest radar in resting adults, at about 140 bpm at most. At neonatal HR:breathing ratios of 2-3 the cancellation would remove the pulse line.
- **ConMed periodic template bank** (US 8,005,523 B2, lapsed) [V: ctx_conmed_template_bank]. Its anti-harmonic penalty targets answers above f0. In a toy run it chose f0/3 at 170 bpm under 30 % respiratory modulation.
- **Masimo first peak ≥ 1/20, Mindray PSA, Nihon Kohden level 2.** All favour the lowest line (section 2.1).
- **Not verified, catalogue only:** PEFAC, SRH, two-way mismatch, spectral smoothness, the Fraunhofer decay test (US 2008/0027299 A1), harmonic MUSIC, Capon, ESPRIT-MLT, AM-FM guard lines (Chen 2021), the Hakimi band prior (neonatal NIRS), HP pincushion (US 6,122,535), the Masimo 1997 rule table and PPRT (US 6,002,952), the Masimo SST least-squares zoom (US 6,850,787), and the DFT interpolators.

### 3. What the project already has that matches the best known

**Production `HR3_HPS`** [V: hr3_hps; spec §5.4 and code read by that verifier]
- Mechanism: 512 samples at 50 Hz (10.24 s), mean removed, Hann, FFT, `P[k]·P[2k]·P[3k]`, argmax, Gaussian (log-power parabola) interpolation, two-bin SQI; published while `hr3_sqi > 0`.
- Against the ECG number (SUBJ08 / 09 / 11, windows with a stable reading) [H3M B]: right 63.9 / 67.6 / 82.9 %; no value 30.2 / 28.4 / 11.8 %; wrong 5.9 / 4.0 / 5.3 %.
- Of its valid windows [H3M C]:
  - right 91.6 / 94.4 / 94.0 %;
  - one third of the rate in 6.6 / 4.0 / 4.2 % (234 / 197 / 139 windows), at ECG medians of 175 / 172 / 166 bpm;
  - `hr3_sqi` in those windows is 0.68 / 0.45 / 0.80, against 1.00 where right. Those values are published and pass the SpO2 gate.
- MS100: 100 % on every plateau from 30 to 240 bpm, maximum error 0.18 bpm [RAT 17.1].
- The neonates' 2nd harmonic sits 10-12 dB and the 3rd 18-21 dB below the fundamental [RAT 17.1].

**Measured against the HR1/HR2 consensus, not adopted** [RAT 17.1]
- B1, the two-harmonic product `P[k]·P[2k]`: the only gain without a cost to the SpO2 gate. Availability went 69.4 → 76.0, 70.6 → 76.5 and 88.3 → 94.7 %. Against ECG it trades thirds for halves: right 72.9 / 75.2 / 89.8 %, errors at one half 2.1 / 1.8 / 4.4 % [H3M B].
- B2 harmonic sum and B3 Hermes SHS: most accurate on clean signal (98-99 %). But they lose the sub-harmonic defence: SUBJ10 windows are admitted to the SpO2 gate at Arms 10-11.
- B4 floored product, and floor-removing preprocessing (Ricker, DoG, CFAR, whitening): they fill availability, but they remove the artefact detector the SpO2 gate relies on.

**`HR3_SAC`** (measured, not adopted) [H3M; SAC; H1M; V: hr3_sac]
- Mechanism: local contrast (dB above the median of ±8 bins, minus 6 dB, clipped 0-30 dB); Pearson autocorrelation along frequency; the first lag in 27-263 bpm whose maximum reaches 0.8 of the highest.
- Against the ECG number [H3M B, C]:
  - right 97.9 / 98.5 / 99.8 %; wrong 0.9 / 0.8 / 0.1 %; on a harmonic ratio 0.2 / 0.1 / 0.1 %;
  - outside the clean windows, right 96.9 / 97.0 / 99.7 %;
  - right in 96.6 / 98.0 / 100 % of the windows where HPS reads f0/3.
- Gated (rho ≥ 0.5 and comb purity ≥ 0.3, a rule added post hoc) [H3M E]: published 77.3 / 79.4 / 97.0 %, wrong 0.1 / 0.1 / 0.0 %. On SUBJ10 (motion; the reference is another pulse oximeter): 10.0 % published, 0.5 % wrong. Ungated on SUBJ10: right 51.7 %, wrong 32.6 % (11.7 % on a harmonic ratio) [H3M B].
- In H1M (gated) [H1M]:
  - published 78.3 %, wrong 0.1 %, MAE 0.87 bpm; start-up median 10.5 s;
  - above 180 bpm (SUBJ08, 980 outputs), published right 51.0 %, against 61.8 % for MSPTD + R0 and 51.7 % for SSF + R0;
  - over 15 554 outputs, right in 83.4 % alone and in 91.0 % together with SSF + R0.
- MS100 [H3M G; SAC limits]: 0 % at 30 bpm and 100 % from 60 to 240 bpm, with no plateau in between. At 30 bpm the comb's teeth are 5 bins apart and about 5 bins wide.
- ESP32-S3 port [H3M addendum]: 4.5 ms mean (5.9 ms worst) per window, against 1.9 ms for today's HR3; HR3 task CPU 0.86 %; about 4.8 kB of class members and 2.7 kB of image.
- Precedent [V: hr3_sac]: Lahat 1987 flattened the spectrum with a lifter bank, autocorrelated it, median-smoothed the pitch across frames and judged voicing from the ACF maxima. The radar NLHS paper (Shimomura 2025) is **not** independent support: against SSA-VHPS on the same input it lost (82.04 against 52.12 ms IBI RMSE).

**`HR3_CEP`** (cepstrum, three preparations) [H3M B, D, E]
- Right 93.7 / 91.6 / 99.1 % (cep40), with half and third errors; dropped.
- As a validity check on `HR3_SAC`, it lets 12× more wrong values through under motion than the rho/purity gate (6.1 against 0.5 % of SUBJ10 windows).

**Selectors and votes** [H3M D, E]. Post hoc, no selector between `HR3_SAC` and any other measured method can gain more than 0.9 % of windows. A 2-of-3 octave vote (R3) changed nothing or lost a little.

**Frequency refinement.** The code implements Gaussian (log-power parabolic) interpolation; spec §5.4 step 4 still says "parabolic interpolation", a documentation mismatch [V: hr3_hps]. With a 0.098 Hz (5.9 bpm) bin, the MS100 maximum error is 0.18 bpm [RAT 17.1], far inside the 10 % "wrong" threshold.

**Above HR3.** The library's `hr_disp` shows the SQI-weighted mean of HR2 and HR3 only when they agree within 8 bpm. It has never been measured against a reference [V: rule_agreement_gate_between_estimators].

### 4. Gaps, ranked

#### G1 (HIGH): `HR3_SAC` has only in-sample evidence, and it is weak above 180 bpm

- **Failure addressed.**
  - The claim that `HR3_SAC` fixes HR3 rests on 3 neonates (122-195 bpm), a monitor ECG number read from photos every 10 s (stable readings only), and parameters fixed after seeing SUBJ10, with no cross-validation [H3M limits; V: hr3_sac].
  - Above 180 bpm, gated, it published a right value in only 51.0 % of 980 outputs (SUBJ08) [H1M]. Its overall wrong share is 0.1 %, so the shortfall appears to be withholding, but H1M does not break wrong values down by rate.
- **Evidence.** Own benchmark only.
  - On the 200 MIMIC PERform neonates, `HR3_SAC` ran only as the anchor of HR1 rule R2, never alone [V: hr3_sac].
  - HR2 and HR3 were never scored on that set. Its test neonates have a median HR of 156 bpm, P99 203 bpm, 11 % of windows at ≥ 180 bpm and about 0.1 % below 100 bpm [V: ctx_ppgbeats_mimic_perform].
- **Test.** Freeze the parameters first. Then run `HR3_SAC` alone (ungated and gated), `HR3_HPS` and B1 on the 100 + 100 MIMIC PERform neonates against ECG beats, and on the coming preterm campaign. Report right / wrong / withheld and the harmonic class per rate band (< 100, 100-140, 140-170, 170-200, > 200 bpm).
- **Cost on the board.** None for the test (offline).
- **Patents in force.** None found on spectral autocorrelation for pulse rate (one Google Patents keyword query, not exhaustive) [V: hr3_sac].

#### G2 (HIGH): below 60 bpm `HR3_SAC` fails, and 35-55 bpm is unmeasured

- **Failure addressed.**
  - At 30 bpm `HR3_SAC` is right in 0 % of the MS100 plateau, and production HPS in 100 % [H3M G].
  - The cause is structural. With a 10.24 s window the teeth are 5 bins apart and about 5 bins wide, so the ±8-bin local contrast finds no valley between them. "A longer window or a narrower neighbourhood was not tried" [SAC limits].
  - Neonatal bradycardia sits exactly in this range.
- **Evidence.** Project only; no external method is shown to fix it.
  - SWIPE''s rate-matched window needs 8 periods, i.e. 16 s at 30 bpm. Its ablation gain comes mostly from a wide-range music set; on speech a fixed window did as well on 2 of 3 databases [V: hr3_swipe_prime].
  - HR2_ACF covers 30 bpm only half the time (MS100 plateau 50.3 %) [V: hr2_acf_first_peak].
  - Real neonatal data below 100 bpm are almost absent from MIMIC PERform [V: ctx_ppgbeats_mimic_perform].
- **Test.**
  - MS100 plateaus at 35, 40, 45, 50 and 55 bpm (H3M decision 2).
  - Offline on the same captures: a contrast neighbourhood scaled to the candidate's tooth spacing (or ±4 / ±2 bins), and a switch rule (HPS or B1 below a threshold, `HR3_SAC` above). Score both at 30-240 bpm and on the neonates.
  - Mine bradycardia episodes from the mimic3wdb neonatal records that carry ECG [V: ctx_mimic3wdb_neonatal_pool].
- **Cost on the board.** HPS is already computed, so a switch costs nothing. A scaled neighbourhood changes only the median filter width.
- **Patents in force.** Covidien US 9,247,887 B2 (active to 2033-12-30) claims splitting the signal into low and high frequency components around about 75 bpm, comparing metrics and selecting one [V: tf_covidien_locked_mode]. A switch between two estimators on the estimate is a different construction, but it needs a freedom-to-operate reading before adoption.

#### G3 (MEDIUM): production HPS publishes f0/3 values now, and no stop-gap has been measured

- **Failure addressed.**
  - In the field today, HPS reads one third of the rate in 4.0-6.6 % of its valid windows, and those values pass the SpO2 gate [H3M C].
  - Removing the windows where HPS disagrees with `HR3_SAC` lowers the gate's Arms from 2.47 to 2.14 (SUBJ08) and from 2.39 to 2.07 (SUBJ09), for 3-4 points of publication [H3M F].
- **Evidence.**
  - Project: in those windows `hr3_sqi` has medians of 0.45-0.80 against 1.00 where right, and comb purity 0.59-0.74 against 0.82-0.97 [H3M C]. B1 swaps thirds for halves (2.1 / 1.8 / 4.4 %) [H3M B].
  - Outside: no f0/3-specific test has any PPG evidence.
    - The Aboy clipped sum still picks f0/3 once breathing exceeds about 0.3 of the cardiac line [V: hr3_aboy_clipped_sum].
    - The GE notch has no data, and its 0.5 % modulation gate would switch it off at typical neonatal PI [V: hr3_ge_resp_notch].
    - The Fraunhofer decay test (A(f) > A(2f) > A(3f)) is not verified.
- **Test.** On the H3M bench, try a swept floor on `hr3_sqi`, a decay admissibility test, and "withhold HPS when it reads about 1/3 or 1/2 of `HR3_SAC`". Report right / wrong / withheld against ECG, and the SpO2-gate Arms.
- **Cost on the board.** Negligible (comparisons on bins already computed). The gap is moot once `HR3_SAC` replaces HPS.
- **Patents in force.** None found. The GE application is abandoned; the catalogue reports the Fraunhofer application as lapsed (not verified).

#### G4 (MEDIUM): SWIPE' was never run, so "best known" cannot be claimed

- **Failure addressed.** A claim that HR3 holds the best known spectral saliences needs the strongest transfer candidate measured on the project's bench.
- **Evidence (transfer only)** [V: hr3_swipe_prime].
  - Proposer: GER 0.13 / 0.83 / 0.63 % on speech, against SHS 0.15 / 1.00 / 1.10, SHR 0.69 / 1.50 / 5.10 and the cepstrum 6.10 / 4.20 / 14.00 %. Ablation: 2.20 % with the raw spectrum instead of the square root, and 2.90 % with a fixed window, against 0.67 %.
  - Independent, in its favour: best of 10 on Parkinson's vowels (Tsanas 2014); lowest oracle-voicing MAE in babble at -5, 5 and 10 dB (Shi 2019).
  - Independent, against it: mid-pack in Singh 2025; behind Praat, pYIN and RAPT on octave accuracy in SwiftF0; 61-96 % RPA depending on the implementation (Marttila 2025).
  - With about 3 usable PPG harmonics, the prime restriction only strips the credit from 2f0 and 3f0 that sub-multiples collect. Energy from breathing at f0/3 is not removed by the negative lobes.
- **Test.** Run SWIPE' offline (square-root spectrum, prime cosine kernel; fixed 10.24 s window and power-of-two matched windows) on the H3M windows and the MIMIC neonates, against `HR3_SAC`. Report harmonic-class errors, the HPS f0/3 windows and 30-60 bpm.
- **Cost on the board.** Unmeasured: a few kernel inner products per candidate. Matched windows add FFT sizes, and need 16 s at 30 bpm.
- **Patents in force.** None identified (academic method of 2007-2008; no patent search was made).

#### G5 (MEDIUM): the respiratory cause of the f0/3 picks is a hypothesis

- **Failure addressed.** The choice of remedy (notch, cancellation, red/IR labelling, harmonic tests, tracking) depends on whether breathing at f0/3 causes the picks. H3M labels it "Hypothesis, not measured"; three snapshots showed 62, 42 and 66 breaths/min [H3M C].
- **Evidence.** Neonatal physiology from ECG and respiration, with no PPG [V: ctx_cardioresp_ratio_occurrence]:
  - PICS re-run: HR/breathing median 2.07; breathing within 10 % of HR/2 in 30.5 % and of HR/3 in 14.1 % of valid windows (breaths unvetted);
  - Joshi 2019 (20 preterm infants): ratio about 3.1;
  - only the combined 40-50 % near HR/2 or HR/3 is stable across sources.
  
  A coincidence is not an error: HPS reads f0/3 in 4-7 % of windows, against 14-34 % of the time near HR/3.
- **Test.** Transcribe the respiration rate from the monitor snapshots of the f0/3 episodes (H3M decision 6; a few dozen). On mimic3wdb neonates with RESP impedance, compute P(f0/3 pick | breathing within 10 % of HR/3) for HPS, B1 and `HR3_SAC`.
- **Cost on the board.** None.
- **Patents in force.** Not applicable.

#### G6 (MEDIUM): nothing links HR3 windows

- **Failure addressed.** Each 10.24 s window is published alone. Under motion, ungated `HR3_SAC` is wrong in 32.6 % of SUBJ10 windows (11.7 % on a harmonic ratio) [H3M B]. On clean data its headroom is ≤ 0.9 % wrong.
- **Evidence.**
  - Makers: every engine read links windows. FAST builds strings with 25 s statistics and checks plausibility; Nellcor's re-seed requires 15 % continuity; HP has tendency limits; Mindray keeps a persistence cache [V: ctx_philips_fast_rate_path, tf_nellcor_adaptive_comb, tf_spectral_peak_continuity].
  - Device studies show the cost of linking: frozen PR in Hay 2002 (Philips 11 vs Masimo 0 episodes; 7-infant sub-study, Masimo co-funded) and in Goldstein 2004 (47 vs 8 episodes) [V: ctx_device_bench_neonatal_vs_ecg].
  - Transfer: a Markov tracker adds 0-12 % relative over its own NLS salience (Shi 2019) [V: hr3_bayes_tracker]. Viterbi locks onto persistent sub-multiples (Ikuma 2025: 3.4 % correct with strong subharmonics) [V: hr2_praat_wacf_viterbi]. Cheap deterministic links exist: Lahat 1987's median smoothing, and Rheem 1993's doubling/halving decision from the previous segment's pitch [V: hr3_sac].
  - The greedy single-candidate gate has no evidence of its own on probe PPG. OxiMA bundles it with other steps, on 10 adults, against a Masimo reference, up to 180 bpm [V: tf_spectral_peak_continuity].
- **Test.** On the H3M bench and the MIMIC neonates, compare gated `HR3_SAC` with three additions: a 3-window median; a previous-period ×2 / ×3 check; a fixed-lag DP over the top-3 lags (after a freedom-to-operate check). Add MS100 steps of 160 → 80 bpm. Report wrong, withheld, the longest freeze and the time to follow a real step.
- **Cost on the board.** A few comparisons per window; a fixed-lag DP over 3 candidates is small.
- **Patents in force.**
  - TI US 10,321,831 B2 (active to 2036-08-16) [V: hr2_pyin_viterbi]. Claim 1: Viterbi path metrics over spectral peaks above a threshold, on transmission or reflection PPG, with no accelerometer.
  - Mindray [V: hr3_mindray_psa]: US 11,154,250 B2 claim 6 (weighted time-varying maps of peak positions; to 2037-09-14); US 11,872,060 B2 (to 2037-02-10); EP 3473171 B1 (to 2036-06-15, narrower).
  - Fukuda JP 2019-122552 A (a ±8 bpm band around a reference; Japan; to 2038-01-16) [V: tf_spectral_peak_continuity].
  - Free: Philips FAST and Nellcor (expired); Lahat and Rheem (papers).
  - This gap belongs equally to the arbitrator.

#### G7 (LOW): HR3 does not use the red channel

- **Failure addressed.** A possible discriminant against f0/3. Philips FAST requires the same red/IR ratio in every family member, and Nihon Kohden US 8,175,669 takes the band of minimum red/IR ratio [V: prep_spectral_ratio_labelling].
- **Evidence.** Patents only, with no rate number anywhere. The physics is unclear: Masimo's own model puts respiration in the venous/noise part, so labelling might down-weight a respiratory f0/3 line, or might not.
- **Test.** In the HPS f0/3 windows, compare the red/IR ratio at the f0/3 line with that at the cardiac line.
- **Cost on the board.** One more 512-point FFT per window (not measured).
- **Patents in force.** Nihon Kohden US 8,175,669 B2 (active to 2030-07-05) claims SpO2 from the ratio at the maximum-amplitude spectral pair. Keep any harmonic-bin ratio out of the SpO2 path. No rate claim was found.

#### G8 (LOW): harmonic-model maximum likelihood, order selection and GLRT were not run

- **Failure addressed.** Documenting that the family was considered, and a possible structural SQI (GLRT of order 0 against order L).
- **Evidence (transfer)** [V: hr3_nls_order; V: hr3_bayes_tracker].
  - In a window of ≥ 5 cycles, exact NLS equals the harmonic sum already rejected (RAT 17.1 B2).
  - Christensen 2011 measured order selection with f0 given, and found NLS weaker when a second periodic source is present.
  - Rehr 2014: NLS had the highest GER at high SNR and ran 55× slower than the cepstrum.
  - Wang 2022: fast NLS had 12.82 Hz MAE at 20 dB, against 6.08-6.17 for SHR and SWIPE.
  - The Bayesian tracker's grid is about 1150 f0 cells × orders per frame, unmeasured on an ESP32-S3.
- **Test.** Only if an SQI is wanted beyond rho/purity (gated `HR3_SAC` is already wrong in 0.0-0.1 %): the GLRT value as a separator of right and wrong windows on the H3M bench (AUC).
- **Cost on the board.** A grid of least-squares fits per window; unmeasured.
- **Patents in force.** None identified.

#### G9 (LOW): frequency refinement has no method gap, and one documentation mismatch

- **Failure addressed.** Precision (weight 10). The MS100 maximum error is 0.18 bpm [RAT 17.1], and gated `HR3_SAC` has an MAE of 0.87 bpm on the ECG subjects [H1M], against a 10 % "wrong" threshold.
- **Evidence.** The alternatives (zero padding, iterative DFT interpolation, harmonic-weighted CRB refinement, the Masimo SST least-squares zoom) are catalogued, not verified, and act on precision only.
- **Test.** None needed. Correct spec §5.4 step 4 from "parabolic" to Gaussian (log-power parabola) [V: hr3_hps].
- **Cost on the board.** None.
- **Patents in force.** None identified.

### 5. What the evidence does NOT show (absences searched for)

- **No comparison of spectral fundamental estimators on clinical-probe PPG against ECG, neonatal or not.**
  - The verifiers found no PPG use of HPS (Europe PMC, Crossref, arXiv), SWIPE / SWIPE', SHR (Europe PMC: 26 hits, 0 on PPG or oximetry), NLS with order selection, or the Bayesian pitch tracker [V: hr3_hps, hr3_swipe_prime, hr3_shr, hr3_nls_order, hr3_bayes_tracker].
  - Two more Europe PMC queries were made for this section on 2026-11-23. Spectral, harmonic or sub-harmonic pulse-rate estimation on neonatal PPG: 36 hits. Harmonic product, sub-harmonic, spectral autocorrelation, cepstrum or harmonic sum with PPG or pulse oximetry: 133 hits, first 60 titles scanned. Nothing was in scope.
- **No external support that spectral autocorrelation beats HPS.** The radar NLHS study compared against a variable HPS, searched 48-102 bpm only, and lost on the same input [V: hr3_sac].
- **No maker reports the accuracy of its spectral rate engine**, and no device study isolates the engine. For Philips, the displayed PR may be beat-based [V: ctx_philips_fast_rate_path]. Device rankings conflict and are partly sponsored [V: ctx_device_bench_neonatal_vs_ecg].
- **No evidence at neonatal rates for any transfer candidate.**
  - Speech f0 is 50-400 Hz.
  - The radar and camera studies stop at about 100-140 bpm.
  - The CapnoBase comparisons use 32-120 s windows, stop at 180 bpm and do not separate the families [V: ctx_capnobase_cross_family].
- **No measurement that breathing causes the f0/3 picks** [H3M C; V: ctx_cardioresp_ratio_occurrence].
- **No evidence that tracking improves a strong salience on PPG.** In speech the gain over a strong harmonic salience is small, and tracking locks onto persistent sub-multiples [V: hr3_bayes_tracker, hr2_praat_wacf_viterbi].
- **No real neonatal data between 30 and 100 bpm**, either on the project's bench or in MIMIC PERform (about 0.1 % of windows below 100 bpm). The MS100 has no plateau between 30 and 60 bpm [H3M G; V: ctx_ppgbeats_mimic_perform].
- **No spectral estimator evaluated specifically at low perfusion against ECG.** ESPRIT-MLT is an SpO2 paper (not verified).
- **No patent found on spectral autocorrelation for pulse rate** (one keyword query; not exhaustive) [V: hr3_sac].

### 6. Sources

Read depth as recorded by the verifiers (full text / abstract / metadata / claims).

**Project (read-only, full or relevant sections)**
- PulseNest `docs/hr3_methods_20261114.md` (H3M): full.
- `docs/spectral_autocorrelation_20261112.md` (SAC): results and limits.
- `docs/hr1_methods_20261116.md` (H1M): relevant sections.
- `docs/algorithm_prior_art_index.md`: via the catalogue.
- `incunest_afe4490_design_rationale.md` §17.1 (RAT 17.1): full section.
- `incunest_afe4490_spec.md` §5.4 and `incunest_afe4490.cpp` `_hr3_compute()`: read by the hr3_hps verifier.

**Transfer: speech and music pitch**
- Schroeder MR 1968, JASA 43(4):829-834, doi 10.1121/1.1910902. Metadata.
- Noll AM 1969, Proc. Symp. Computer Processing in Communications, pp. 779-797. Citation only.
- Lahat M, Niederjohn RJ, Krubsack DA 1987, IEEE TASSP 35(6):741-750, doi 10.1109/TASSP.1987.1165224. Abstract.
- Rheem JY, Bae MJ, Ann SG 1993, Eurospeech 1993 pp. 2021-2024, doi 10.21437/Eurospeech.1993-457. One page.
- Kunieda N, Shimamura T, Suzuki J 1996 (ACLOS), ICASSP 1996 vol. 1 pp. 232-235, doi 10.1109/ICASSP.1996.540333. Abstract.
- Sun X 2000 (SHR), ICSLP 2000 vol. 4 pp. 676-679, doi 10.21437/ICSLP.2000-902. Full text.
- Camacho A 2007, SWIPE dissertation, Univ. of Florida. Full text (ch. 2-4).
- Camacho A, Harris JG 2008, JASA 124(3):1638-1652, doi 10.1121/1.2951592, PMID 19045655. Abstract.
- Tsanas A et al. 2014, JASA 135(5):2885-2901, doi 10.1121/1.4870484, PMC4032429. Full text.
- Wang D et al. 2022, Sensors 22(16):6026, doi 10.3390/s22166026, PMC9414051. Full text.
- Singh A, Demuynck K 2025, arXiv 2509.16480. Full text.
- Marttila D, Reiss JD 2025, arXiv 2507.11233. Full text.
- Nieradzik L 2025 (SwiftF0), arXiv 2508.18440. Full text.
- Herbst CT 2021, J Voice 35(3):365-375, doi 10.1016/j.jvoice.2019.11.005. Abstract.
- Nielsen JK et al. 2017, Signal Processing 135:188-197, doi 10.1016/j.sigpro.2017.01.011. Full text.
- Christensen MG et al. 2011, EURASIP J Adv Signal Process 2011:13, doi 10.1186/1687-6180-2011-13. Full text.
- Christensen MG 2011, IEEE WASPAA pp. 169-172, doi 10.1109/ASPAA.2011.6082304. Full text.
- Rehr R, Krawczyk M, Gerkmann T 2014, DAGA 2014 pp. 487-488. Full text.
- Shi L et al. 2019, IEEE/ACM TASLP 27(11):1737-1751, doi 10.1109/TASLP.2019.2930917 (arXiv 1905.08557). Full text.
- Ikuma T, Kunduk M, McWhorter AJ 2025, arXiv 2501.04789. Full text (results).

**Transfer: radar, camera, BCG, pressure**
- Shimomura K, Lee CH, Sakamoto T 2025 (NLHS, radar), arXiv 2507.20664. Full text.
- Debnath U et al. 2026 (camera, HPS ablation), Front Physiol, doi 10.3389/fphys.2026.1909505, PMC13541287. Full text.
- Bai Z et al. 2024 (HarSum, BCG and radar), Bioengineering 11(12):1219, doi 10.3390/bioengineering11121219. Full text.
- Aboy M et al. 2005, IEEE TBME 52(10):1662-1670, doi 10.1109/TBME.2005.855725. Full text.
- Villarroel M et al. 2019 (camera, preterm), npj Digit Med 2:128, doi 10.1038/s41746-019-0199-5, PMC6908711. Full text.
- Radar respiratory cancellation:
  - Xu D et al. 2026, Sensors 26(17):5587, doi 10.3390/s26175587. Full text.
  - Tang H et al. 2025, arXiv 2503.07062. Full text.
  - Sameera JN et al. 2024, IEEE TMTT 72(1):750, doi 10.1109/TMTT.2023.3324444. Full text.

**Clinical-probe PPG (non-neonatal) and datasets**
- Cicone A, Wu HT 2017 (deppG), Front Physiol 8:701, doi 10.3389/fphys.2017.00701, PMC5615790. Full text.
- Garde A et al. 2014, PLoS One 9:e86427, doi 10.1371/journal.pone.0086427. Full text.
- Karlen W et al. 2013, CCIS 273 pp. 31-42, doi 10.1007/978-3-642-29752-6_3. Full text (via tf_quadrature_fll_karlen).
- Harvey J et al. 2019 (OxiMA), IEEE TBME 66(2):311-318, doi 10.1109/TBME.2018.2837499. Full text.
- Charlton PH et al. 2022, Physiol Meas 43:085007, doi 10.1088/1361-6579/ac826d. Full text.
- PhysioNet mimic3wdb 1.0 (neonatal record sets). Database pages and sampled headers.

**Neonatal physiology (ECG + respiration, no PPG)**
- Joshi R et al. 2019, J Appl Physiol 126(1):202-213, doi 10.1152/japplphysiol.00722.2018, PMC6383641. Abstract + table 2.
- Krishnamurthi N et al. 2026, Pediatr Res, doi 10.1038/s41390-026-04783-1. Full text.
- Lucchini M et al. 2018, Physiol Meas 39(6):064001, doi 10.1088/1361-6579/aac553. Full text.
- PICS database (PhysioNet picsdb 1.0.0). Re-run by the survey's own script.

**Patents** (Google Patents pages read 2026-11-22/23; statuses as shown there; not a legal opinion)
- US 5,632,272 A (Masimo): expired 2014-05-27. Rate module, full text.
- US 6,684,090 B2 (Masimo): expired 2020-02-11. Relevant sections.
- US 6,631,281 B1 (Philips FAST): expired 2019-06-10. Full text.
- Philips FAST app note 4522 991 83651 (Nov 2023). Full text.
- US 5,853,364 A and US 7,865,224 B2 (Nellcor): expired (2016-06-07; 2021-06-30, fee related). Rate sections and claims.
- US 11,154,250 B2 (Mindray): active to 2037-09-14. Full text.
- US 11,872,060 B2 (Mindray): active to 2037-02-10. Claims.
- EP 3473171 B1 (Mindray): active to 2036-06-15. Claims.
- US 8,649,837 B2 (Nihon Kohden): expired, fee related (lapse effective 2026-02-11). Full text.
- US 7,438,688 B2 (Nihon Kohden): active to 2027-05-10. Claims.
- US 8,175,669 B2 (Nihon Kohden): active to 2030-07-05. Description paras 100-173 and claims.
- US 2008/0167541 A1 (GE): abandoned 2012-01-03. Full text.
- US 10,321,831 B2 (TI): active, anticipated expiration 2036-08-16 (copy of 2026-11-23). Claims.
- US 8,285,352 B2 (Nellcor, CWT): active to 2031-07-28. Claims.
- US 9,247,887 B2 (Covidien): active to 2033-12-30. Full text and claims.
- US 8,005,523 B2 / EP 1928309 B1 (ConMed template bank): lapsed. Full text.
- JP 2019-122552 A (Fukuda Denshi): granted, to 2038-01-16. Machine translation.

**Device-level studies** (whole devices; they cannot rank engines)
- Gehring H et al. 2000, Anesthesiology 93(3A):A-584. Abstract + table.
- Hay WW et al. 2002, J Perinatol 22:360-366, doi 10.1038/sj.jp.7210740. Abstract.
- Goldstein MR et al. 2004, Proc ATS A50. Abstract.
- Workie FA et al. 2005, Am J Perinatol 22:357-360, doi 10.1055/s-2005-872704. Abstract.

**Searches made for this section (2026-11-23)**
- Europe PMC REST: two queries on spectral, harmonic or sub-harmonic pulse-rate estimation with PPG or pulse oximetry (and neonates). 36 and 133 hits; titles scanned (all 36; the first 60 of 133); none in scope. Saved under `dl/verify/t3_gap/`.

---

## Chapter 4 - Across windows and across families: tracking, arbitration, fusion, quality indices and publication policy

*Status: verified draft; not reviewed adversarially.*


Section of the final report of the pulse-rate method survey (2026-11-23). Question: the library publishes `hr1`, `hr2`, `hr3`
and three SQIs side by side, with nothing linking windows and no arbitrator. What are the best-known and best-evidenced ways to
link windows, to arbitrate or fuse estimators, to grade confidence and to decide when to publish, hold or blank, and what does
the project lack?

Conventions. Every number comes from a verified record of this survey (verifier notes under `verify/`) or from the project's own
documents: **H1M** = PulseNest `docs/hr1_methods_20261116.md`, **H2M** = `docs/hr2_methods_20261115.md`, **H3M** =
`docs/hr3_methods_20261114.md`, **IDX** = `docs/algorithm_prior_art_index.md`, **SPEC** = `incunest_afe4490_spec.md` v0.124b,
**RAT** = `incunest_afe4490_design_rationale.md`. "Wrong" in project numbers = more than 10 % from the ECG heart rate.
**[transfer]** marks evidence from another signal (speech, music, ICU ECG or arterial pressure, fetal ECG or Doppler, camera PPG,
breathing rate); it is never evidence about pulse rate from a red/IR probe. Patent statuses are as read on Google Patents by the
verifiers (2026-11-22/23); they are readings of claims, not legal opinions.

---

### 1. Verdict

**No: the owner cannot state that the library contains the best known layer above its estimators, because the library has
almost none, and nobody has shown which layer is best for this probe.** What ships is an inherited HR2 x HR3 agreement gate
(`hr_disp`, v0.124: within 8 bpm, SQI 0.8 / 0.5, 1 s on / 2 s off) whose constants were never measured against a reference, a
per-family withhold rule (each `hrN` is NaN when its own test fails; `R0` for HR1), and no tracking, no hold (`DISP_HELD` is
reserved), no fusion. On the literature side, no published arbitrator, tracker or fusion of beat, lag and spectral pulse-rate
estimators has been validated on standard red/IR probe PPG against ECG with an ablation (verifiers' Europe PMC screens: none in
60 titles for Viterbi/HMM, none in 40 for median fusion). The best evidence for each idea is transfer evidence (SQI-gated hold and
Kalman tracking on ICU ECG + arterial pressure, Li 2008; path finders and candidate HMMs on speech, Boersma 1993, Ikuma 2025,
Mauch & Dixon 2014; median of three estimators on speech, Drugman 2018), expired maker patents with no data (Nellcor 1995
two-engine arbitration and hold-then-blank, Philips FAST strings, Masimo Signal IQ), and device-level neonatal studies that show
the harm of long holds (frozen pulse rate, missed bradycardias). **What the owner can claim with evidence:** (a) `R0` sits at the
honest end of published publication rules (0.4-1.8 % wrong on the 100 MIMIC PERform test neonates, 0.3-0.6 % on own captures;
H1M), and the library withholds instead of holding, which is what the neonatal device evidence favours; (b) on the project's own
still neonates an arbitrator can add availability, not correctness: no selector between `HR3_SAC` and any other measured method
gains more than 0.9 % of windows (H3M), while `HR1_SSF` + `R0` covers windows where gated `HR3_SAC` withholds (oracle union right
in 91.0 % against 83.4 %; H1M); (c) under motion a structure gate on one estimator was more honest than the agreement of two
estimators of the same IR channel (0.5 % against 6.1 % of windows wrong, SUBJ10, weak reference; H3M); (d) YIN's 1 - d' is a
better quality index for the HR2 lag than the ACF peak height (AUC 0.96 against 0.85; H2M). **What it cannot claim:** that
`hr_disp` is a good arbitrator, that any hold length is safe, that its three SQIs are comparable across families, or that any
SQI detects the confident sub-multiple errors (HR1 half rate, HR3_HPS one third) that are the project's worst failures.
Evidence strength: project benches (3 ECG neonates at 122-195 bpm, rate read by eye every 10 s; 100 MIMIC test neonates, clean
ECG windows only) for (a)-(d); other_signal_only for every tracking and fusion method; patent_or_claim_only for every maker
arbitrator.

---

### 2. Best known methods for this topic

| Method | Why it counts as best known | Evidence strength | In the project? | Key source (identifier) |
|---|---|---|---|---|
| **SQI-gated hold, optionally an SQI-scaled scalar Kalman filter per source** (random walk; R scaled by exp(1/SQI^2 - 1); no update when SQI < 0.5; fusion weighted by inverse (innovation/SQI)^2) | The only cross-window layer with an ablation of its parts on clinical data [transfer: ICU ECG + arterial pressure, 437 adults, noise added to the ECG only, gold standard = the method's own output on clean data]: at EM 6 dB, single detectors 53.8 / 39.0 bpm rMSE, gated sample-and-hold 5.4, Kalman 3.8, fused with the clean ABP 1.1; the Kalman **without** the SQI gate 27.7. On one source the Kalman barely beats the gated hold: 149 against 146 of 201 false bradycardia alarms suppressed (Li 2009, ABP), "only marginally superior" in the authors' words. Fetal Doppler [transfer, 10 subjects, tuned in sample]: AAE 1.65 -> 1.03 (plain Kalman, 100 %) -> 0.74 bpm (SQI-Kalman, 87 % coverage) | other_signal_only | catalogued_not_evaluated (IDX §2.5 names "Kalman and similar" as a layer above the families; Li 2008 is not cited in the project) | Li, Mark & Clifford 2008, Physiol Meas 29(1):15-32, doi 10.1088/0967-3334/29/1/002; Li et al. 2009, Biomed Eng Online 8:13, doi 10.1186/1475-925X-8-13; Shi et al. 2023, Sensors 23(24):9698, doi 10.3390/s23249698 |
| **Tracking over per-window candidates** (Viterbi, path finder, forward or fixed-lag HMM over K period candidates with a jump cost) | Largest measured gains for weak frame-wise pickers [transfer, speech]: Praat ACF with the path finder 62 -> 88 % correct, subharmonic errors 35.4 -> 9.3 % (the baseline is a tallest-peak picker, which `HR2_ACF` is not); librosa pYIN against raw YIN, RPA 62.36 -> 83.31 (PTDB; candidates and decoder together); pYIN median recall 0.977-0.984 against YIN below 0.951. Small or negative for strong estimators (-1.75 to +1.62 points); a forward harmonic-model HMM lowers GER 0.41 -> 0.36 at 0 dB babble. Documented lock-in: the path finder turns 1.6 % of correct intervals into sub-harmonic errors and is right in only 3.4 % of strong-subharmonic intervals; Viterbi smoothers "could lock into octave errors" (Yu 2026). Frame-selective DP: almost no gain over no DP with the same candidates (1.04 against 1.01 % non-candidate errors) | other_signal_only | absent | Boersma 1993, Proc Inst Phonetic Sci Amsterdam 17:97-110 (no DOI); Ikuma et al. 2025, arXiv 2501.04789; Mauch & Dixon 2014, ICASSP, doi 10.1109/ICASSP.2014.6853678; Yu et al. 2026, arXiv 2609.39852; Shi et al. 2019, IEEE/ACM TASLP 27(11):1737-1751, doi 10.1109/TASLP.2019.2930917; Yarra et al. 2018, JASA 143(4):2289-2300, doi 10.1121/1.5031129 |
| **Rule-based trust-weighted Kalman over many estimators of one signal** | Beat the best single estimator where trained fusers lost [transfer, 65 real sustained vowels]: RMSE 6.22 Hz (best single, SWIPE) -> 4.95 Hz (hand-designed adaptive Kalman), against 7.58 (OLS) and 6.53 (IRLS) for the trained ensembles and 24.71 Hz for the median of 10. Trust priors and SQI rules were set on the same data | other_signal_only | absent | Tsanas et al. 2014, JASA 135(5):2885-2901, doi 10.1121/1.4870484, PMID 24815269 |
| **Median of three diverse estimators** | Zero-cost baseline that beat learned selectors in the one head-to-head [transfer, clean studio speech, 6 voices]: GPE 1.95 % against best single 2.76, MLP index selector 2.39, KNN regression 2.53, CREPE 3.51. The members were chosen on the same evaluation. It fails when several members are erratic (Tsanas 2014: the median of 10 was worse than the best single on real and on synthetic data) | other_signal_only | absent (a 2-of-3 octave vote, R3, was measured: no gain, H3M §E) | Drugman et al. 2018, IEEE SPL 25(11):1745-1749, doi 10.1109/LSP.2018.2874155 |
| **Agreement gate between estimators that fail differently** | The cheapest honesty layer. On the project's bench the `HR3_SAC` + cepstrum agreement cut wrong values to 0.1 / 0.3 / 0.0 % of windows on still neonates at 92.8 / 91.3 / 99.1 % published; under motion it let through 6.1 % wrong at 43.5 % published, against 0.5 % at 10.0 % for a structure gate (rho + comb purity). Outside the project only other signals: camera PPG in 30 preterm infants, an AR self-consistency check gave 2.3 bpm MAE at 75.4 % of valid time against FFT 2.6 and beat counting 3.3 at 79.4 % [transfer: camera PPG, a check inside one estimator]; Smart Fusion of breathing rate, 71.5 % within 2 bpm at 54.2 % availability against up to 60.5 % at 100 % ungated [transfer: respiratory rate] | own_benchmark_on_clinical_ppg | implemented (`hr_disp`, HR2 x HR3, never measured against a reference); `HR3_SAC` x cepstrum measured, not adopted | H3M §E; SPEC §5.10; Villarroel et al. 2019, npj Digit Med 2:128, doi 10.1038/s41746-019-0199-5; Charlton et al. 2016, Physiol Meas 37(4):610-626, doi 10.1088/0967-3334/37/4/610 |
| **Maker arbitration by confidence, with a gated re-seed and a rate Kalman** (Nellcor 1995): adaptive comb rate against pattern-matcher rate; at least 10 % more confidence wins, otherwise the two are interpolated; a Kalman limits rate change (SD 5 bpm); every 10 s an FFT may re-seed the comb only if the comb's confidence is below 50 (or it is uninitialised), the candidate's S/N is at least 0.7, it lies within 10 bpm of a positive autocorrelation local maximum and within 15 % of the candidate 10 s earlier; the rate is shown above 50 % confidence, held up to 40 s, then blanked | The most complete disclosed cross-window and cross-engine layer for a red/IR oximeter, and expired. **No data, population or statistics** (one figure against an N200) | patent_or_claim_only | catalogued_not_evaluated (IDX §4.3) | Baker & Yorkey, US 5,853,364 A (expired) and US 7,865,224 B2 (expired, fee related, 2021-06-30) |
| **Primary / alternate beat source with per-pulse adaptive averaging** (Nellcor 2004): the primary rate comes from non-averaged pulses; the alternate from the beat-synchronously averaged waveform is used only when the primary has just rejected a pulse; the rate is a variable-weight IIR on qualified periods (weight grows with consecutive agreement, capped for about 7 s response) | A disclosed, expired arbitration rule between two beat sources. No data in any patent; the device studies do not isolate it | patent_or_claim_only | catalogued_not_evaluated | Baker, US 7,534,212 B2 (expired 2026-05-08); EP 1 737 337 B1 (expired) |
| **String tracking of spectral candidates across 1 s cycles** (Philips FAST): up to 10 red/IR spectral "needles" per 8 s section, linked into strings with 25 s statistics, scored into harmonic families with the same red/IR ratio, plausibility against the last output, a 13 s trimmed mean that extends back up to 70 s and holds the old value if empty | An expired maker design that links windows and uses red/IR ratio identity to bind harmonics. No data in the patent; Philips devices showed frozen pulse rates in neonates (Hay 2002: 11 events in a 7-infant arm; Goldstein 2004: 47 episodes), but no source ties that to the patent's linking | patent_or_claim_only | catalogued_not_evaluated | Kaestle, US 6,631,281 B1 (expired 2019-06-10) |
| **Quality: lag aperiodicity, YIN 1 - d'** | The best quality index of family 2 on the project's ECG neonates, out of sample: AUC 0.96 against 0.85 for the ACF peak height; at 1 % wrong it keeps 70.6 % of windows against 50.2 % (63.2 % with `hr2_min_corr` 0.4). Post hoc, 3 neonates | head_to_head_on_clinical_ppg (project re-run of a literature method) | measured_not_adopted | H2M part 2 (P2); de Cheveigne & Kawahara 2002, JASA 111(4) |
| **Quality: spectral comb structure** (`HR3_SAC` rho >= 0.5 and comb purity >= 0.3) | On the project's ECG neonates: published 77.3 / 79.4 / 97.0 % with 0.1 / 0.1 / 0.0 % wrong; on the moving neonate 10.0 % with 0.5 % wrong (weak reference). Thresholds fixed on 2026-11-12 after seeing SUBJ10, not tuned further | own_benchmark_on_clinical_ppg | measured_not_adopted (H3M decision 4: proposed for the phase across families) | H3M §E, §F |
| **Quality: beat-template similarity and feature classifiers** | The only independent head-to-head of published PPG SQIs [fingertip ICU PPG, 13 adults, visual labels, not rate error]: Karlen's consecutive-pulse cross-correlation best of six (accuracy 0.902); a feature SVM 0.951; on fingertip AF the baselines fall to 0.34-0.67. Rate-error gains after gating come only from the authors' own studies on adults with induced motion: 7.23 -> 0.49 bpm (Sukor 2011), 17.3 -> 2.3 bpm (Chong 2014). On a standard probe with an AFE4400 (5 adults) the template SQI (AUC 0.84 / 0.71) lost to an ambient-phase SQI (0.91 / 0.90) | head_to_head_on_clinical_ppg (labels, not rate) | catalogued_not_evaluated | Pereira et al. 2020, IEEE JBHI 24(3):649-657, doi 10.1109/JBHI.2019.2909065; Sukor et al. 2011, doi 10.1088/0967-3334/32/3/008; Chong et al. 2014, doi 10.1007/s10439-014-1080-y; Clarke 2015, MASc thesis, Carleton University |
| **Quality: Masimo three-measure confidence** (red/IR canceller integrity; pulse-rate density = accepted periods / 6.4 s; harmonic ratio; alert when all three fall below 0.3 / 0.7 / 0.8) | An expired, cheap, deterministic maker layer; no data; no study tests it against rate error. The harmonic ratio and the pulse density are blind to a regular sub-multiple | patent_or_claim_only | catalogued_not_evaluated | Al-Ali et al., US 6,684,090 B2 (expired 2020-02-11); US 6,606,511 B1 (expired) |
| **Publication policy: withhold on failure; hold only with an expiry; never a long freeze** | Device-level neonatal studies against ECG show the harm of long holds and long averaging: frozen pulse rate (within 1 bpm for more than 20 s while the ECG rate moved by 25 bpm or more) in 8 / 47 / 59 / 61 episodes for Masimo / Philips / N-595 / N-395 (Goldstein 2004, 30 neonates, 179 h, Masimo-hosted abstract); bradycardias below 80 bpm for more than 5 s missed by 69 % (Nellcor new generation), 32 % (conventional) and 7 % (Masimo) of 54 events (Bohnhorst 2000, 17 preterm infants). Maker holds: Nellcor 40 s then blank; Nonin 10 s in display mode only. No study compares hold durations | head_to_head_on_clinical_ppg (device level) | catalogued_not_evaluated (contract: withhold; `DISP_HELD` reserved with a 10 s limit; a 5 / 10 s SpO2 hold was measured and rejected, RAT §17) | Goldstein et al. 2004, Proc ATS A50; Bohnhorst et al. 2000, Crit Care Med 28(5):1565-8, doi 10.1097/00003246-200005000-00050; Hay et al. 2002, J Perinatol 22:360-6, doi 10.1038/sj.jp.7210740; US 5,853,364 A |
| **Locked oscillator as a follower** (quadrature FLL; adaptive notch whose adaptation is frozen on low SQI) | The only locked-oscillator pulse-rate result on a clinical probe: 42 CapnoBase subjects, 53-142 bpm, NRMS 2.15 % (peak output) / 3.90 % (frequency output) against 2.54 % for a 50 s FFT and 5.54 % for Pan-Tompkins, not significantly different; the FFT was better on artefact sections (1.67 against 2.73 / 2.93 %); one lock on 2 f0 (NRMS 24 %); 41-47 us per sample against 1937 us for the FFT. Freezing adaptation on bad SQI cut AAE by 73 % [transfer: synthetic signals] | own_benchmark_on_clinical_ppg | absent (HR4 is a named candidate family; nothing evaluated) | Karlen et al. 2013, CCIS 273:31-42, doi 10.1007/978-3-642-29752-6_3; Fallet 2018, EPFL thesis 8493, doi 10.5075/epfl-thesis-8493 |

Left out of the table because the evidence read is weaker: learned fusion and learned arbiters (gap G2), particle filters
(non-deterministic), beat-phase and period HMMs (music only), learned octave validators (music tempo only), greedy
single-candidate continuity gates (OxiMA: 10 adult males, another oximeter as reference, no ablation of the rule; RT-TRAQ fetal
tracker worse than an offline method in 8 of 9 visits), and the Covidien search/lock state machine (no data; the tests that keep
its lock safe are patented until 2033-2035).

---

### 3. What the project already has that matches the best known

**Per-family withhold with a quality gate (the "SQI gate" half of Li 2008).** Each family writes NaN when its own test fails
(SPEC §2.1.1 rule 3); the library never keeps an older result in place of one that failed (rule 4); `hr1` expires once the
interval in progress exceeds 2 s (v0.123). `R0` (mean of 5 RR, published while their CV < 0.15) is honest on neonates:

| Chain | MIMIC test neonates: published / wrong of published | Own captures (ECG subjects): published / wrong | Source |
|---|---|---|---|
| `HR1_THR` + `R0` (v0.122) | 63.4 / 0.57 % | 66.4 / 0.30 % | H1M part 3 |
| `HR1_SSF` (part 3) + `R0` (proposed) | 78.1 / 0.40 % | 86.2 / 0.40 % | H1M part 3 |
| `HR1_SSF` (part 3) + `R1` with its gates | 87.5 / 2.00 % | 93.4 / 0.20 % | H1M part 3 |
| `HR2_ACF` | not run on MIMIC | 85.4 / 4.4 % | H2M |
| `HR3_SAC` gated (rho + purity) | not run on MIMIC | 78.3 / 0.1 % | H1M F3 |

**An agreement gate across families that ships: `hr_disp` (v0.124; SPEC §5.10, RAT §26).** HR2 and HR3 must both have a value,
be closer than 8 bpm, with the better SQI at least 0.8 and the worse at least 0.5; their SQI-weighted mean is shown once the
agreement has lasted more than 1 s; a break longer than 2 s asks for the wait again. It is IncuNest CommTask's rule moved
unchanged into the library; the port matches CommTask in 99.85 % of 252 126 turns. It shows a pulse rate in 55 % of the
probe-applied time on the 19 stored sessions and in 0-11 % of each SUBJ10 session. **Its constants have no provenance and it has
never been compared with the ECG.** It matches the best-known "agreement gate" in kind; its stated purpose is to discard
HR3_HPS's one-third readings (4.5-19 % of HR3's valid windows depending on the subject, SPEC §5.10).

**A publication contract that matches the device evidence.** Display quantities are finite or NaN with a state (no probe,
acquiring, current, held, inadequate); a held value may never be shown for more than 10 s (WHO/UNICEF 2019); v0.124 holds
nothing (SPEC §2.1.2). The SpO2 pulse gate withholds without holding; a Nellcor-style hold of 5 or 10 s was measured and hurt,
because HR3's 10.24 s buffer is already contaminated when motion starts (SUBJ10 published 7-10 % of windows again at -12 to -13
points; RAT §17).

**Measured combinations (none adopted).**
- `R2` (an HR1 interval accepted only within 15 % of `HR3_SAC`'s period): 75-81 % published with 1.8-2.8 % wrong on MIMIC;
  77.7-82.0 % with 0.1-0.4 % wrong on own captures. It rescues TERMA's half rates, but HR1 then depends on HR3 and is no longer
  an independent check (H1M Q3, F3); start-up 12.5 s, because it waits for `HR3_SAC`.
- `R3`, a 2-of-3 octave vote (`HR3_SAC`, cepstrum, board HR2): no gain, because `HR3_SAC` has no octave errors to fix (H3M §E).
- `HR3_SAC` x cepstrum agreement: honest on still neonates, less honest than a structure gate under motion (section 2).
- The oracle ceiling. Against ungated `HR3_SAC` on still neonates, what any other measured method gets right where `HR3_SAC`
  does not is at most 0.9 % of windows (cepstrum 0.9 / 0.9 / 0.1; board HR2 0.2 / 0.3 / 0.0; board HR1 0.0 / 0.2 / 0.0; H3M §D,
  post hoc). Against **gated** `HR3_SAC` (confirmed in `experiments/hr1_methods_20261116.py`), `HR1_SSF` + `R0` is right where it
  is not in 7.6 % of outputs and wrong where it is right in 5.0 %; the oracle union is right in 91.0 % against 83.4 % (H1M F3,
  "Map of gaps"). Reading: on still neonates the room for an arbitrator is availability where the structure gate withholds, not
  the correction of `HR3_SAC`. HR2 covers almost none of `HR3_SAC`'s failures (right in 0.0-0.3 % of all windows, H2M Q6; about
  10 / 20 / 0 % of the windows where `HR3_SAC` fails, hr2_acf_first_peak verifier).

**Quality indices already measured.** `hr2_sqi` AUC 0.85 against YIN 1 - d' 0.96 (H2M); `R0`'s `hr1_sqi` AUC 0.85 for SSF on own
captures and 0.926 on MIMIC; `R1`'s own quality AUC 0.89-0.95 (H1M); gated `HR3_SAC` AUC 0.885-0.89 (H1M F3, H2M). And their
known blind spot: TERMA + `R0` produced 147 half-rate values with `hr1_sqi` >= 0.8 among its 330 wrong values on MIMIC (H1M Q3);
HR3_HPS's one-third readings carry `hr3_sqi` medians of 0.45-0.80 and pass the SpO2 gate (H3M §C).

**Where every family is weak (an arbitrator cannot fix this by choosing).** Above 180 bpm on SUBJ08, published-right shares are
MSPTD + `R0` 61.8 %, SSF + `R0` 51.7 %, `HR3_SAC` 51.0 % (H1M F3). Under motion (SUBJ10, another oximeter as reference):
`HR3_SAC` wrong in 32.6 % of windows (11.7 % on a harmonic ratio), `HR2_ACF` publishes 15.3 % with 36 % of it wrong, the `R0`
chains are 12-88 % wrong on 2-24 % published (H3M §B, H2M part 2, H1M F3).

---

### 4. Gaps, ranked

#### G1 (high). The only shipping arbitrator, `hr_disp`, has never been measured

- **Failure addressed.** The number a display shows comes from 8 bpm / 0.8 / 0.5 / 1 s / 2 s constants inherited from CommTask
  (RAT §26: never measured against a reference). Its availability is bounded by HR2's (HR2 publishes about 15 % of windows under
  motion, H2M) and its purpose (discard HPS thirds) disappears if `HR3_SAC` replaces HPS (inference from H3M §B-C).
- **Evidence.** Own only: a value shown in 55 % of probe-applied time, 0-11 % in SUBJ10 (RAT §26). The agreement-gate literature
  is respiratory or camera PPG [transfer]; the project's own agreement test showed that under motion two estimators of one IR
  channel agree on wrong values (H3M §E).
- **Test.** Replay `hr_disp` (HR2 and HR3 from `OT_LED1`, as `test_disp` does) on the H1M/H3M ECG subjects, SUBJ10 and the MS100,
  once with HPS and once with `HR3_SAC` as HR3; report published / wrong / start-up / step recovery against gated `HR3_SAC` alone
  and `HR1_SSF` + `R0` alone; then choose the five constants out of sample (leave one subject out, as in H2M).
- **Cost on the board.** Nothing new (scalar comparisons per sample).
- **Patents.** None identified for a plain agreement-within-tolerance gate.

#### G2 (high). No arbitrator built on the project's measured complementarity

- **Failure addressed.** Three rates are published side by side; gated `HR3_SAC` withholds where `HR1_SSF` + `R0` is right in
  7.6 % of outputs (H1M F3), and HR1 starts in 2.5 s where `HR3_SAC` needs 10.5 s (H1M "Dynamics").
- **Evidence.** Oracle ceiling (own): 91.0 % against 83.4 %, but SSF is also wrong where `HR3_SAC` is right in 5.0 %, so the
  arbitrator must not simply prefer whichever publishes. Rule-based beat learned in the two head-to-heads that exist [transfer]:
  supervised fusers lost to a median (Drugman 2018: MLP index selector 2.39 % against median 1.95 % GPE) and to a hand-designed
  Kalman (Tsanas 2014: OLS 7.58 and IRLS 6.53 Hz against 4.95). Zhu's Bayesian fusion of PPG respiratory-rate estimators (1.98
  against 2.39 for the best single and 2.22 breaths/min for the rule-based benchmark) is unsupervised and batch over 8 min
  records, so not causal, and adding signal quality did not help it on PPG respiratory rate (Zhu 2018). Learning helped only the
  accept/hold/reject decision (Drugman: VDE 3.11 % against 5.42-5.58 %). Maker designs (Nellcor two engines, Nellcor
  primary/alternate source, Masimo parallel engines) exist but report no numbers.
- **Test.** On own captures and on the 100 MIMIC PERform test neonates (HR2 and HR3 have never been scored there), compare:
  (a) gated `HR3_SAC` alone; (b) median of `hr1`, `hr2`, `hr3`; (c) primary/alternate: gated `HR3_SAC` primary, `HR1_SSF` + `R0`
  only while `HR3_SAC` withholds and only within 15 % of the last published value; (d) an `HR1_SSF` x `HR3_SAC` agreement gate
  (built and measured nowhere). Score published / wrong / start-up per rate band (170 bpm and above) and per motion stratum.
  Keep HR1 free of HR3 seeding (`R0`, not `R2`) so that the arbitrator keeps two independent views.
- **Cost on the board.** Negligible (a few comparisons per output); deterministic.
- **Patents in force (forms to avoid).** A CWT candidate and a spectral candidate selected or combined: Nellcor US 8,285,352 B2
  claim 1, to 2031-07-28. A pulse-qualification constant changed after a designated number of rejected pulses: Nellcor US
  7,922,665 B2 claim 1, to 2030-02-10. A weighted time-varying map of spectral peak positions across windows driving a
  compensation: Mindray US 11,154,250 B2 claim 6, to 2037-09-14; US 11,872,060 B2 claim 8, to 2037-02-10; EP 3473171 B1 (narrower),
  to 2036-06-15. A rate-filter weight lowered when a value is not qualified: Covidien US 9,392,974 B2 dependent claim 8, to
  2034-03-20. Free (expired): Nellcor 1995 arbitration (US 5,853,364, US 7,865,224), Nellcor primary/alternate (US 7,534,212,
  expired 2026-05-08), Masimo three measures (US 6,684,090, expired 2020-02-11).

#### G3 (high). No quality index sees the confident sub-multiple errors

- **Failure addressed.** The project's worst errors are regular and confident: TERMA + `R0` half rates with `hr1_sqi` >= 0.8 (147
  of 330 wrong values on MIMIC; 25 of about 43 on own captures, all with `hr1_sqi` >= 0.8), HPS one-third values with `hr3_sqi`
  0.45-0.80 that pass the SpO2 gate (H3M §C). An arbitrator that weights by these SQIs would trust them.
- **Evidence.** Verified blind spots: a beat-template SQI cannot see a half-rate output from regularly missed beats, because
  template and RR double together (rule_template_similarity_sqi verifier); Masimo's harmonic ratio and pulse density cannot see
  a regular sub-multiple (rule_masimo_signal_iq and hr1_masimo_pulse_recognition verifiers); the project's comb purity on an f0/3
  comb contains every true harmonic (catalogue g7 overview, not separately verified). Lag checks catch multiples of the rate, not
  sub-multiples: Nellcor's autocorrelation condition only gates re-seeds of the comb (tf_nellcor_adaptive_comb verifier). What can
  see a sub-multiple is a check across domains, beats counted in time against the spectral or lag period. No published study
  measures it on PPG.
- **Test.** For each SQI (`hr1_sqi`, `R1` quality, `hr2_sqi`, YIN 1 - d', `hr3_sqi`, `HR3_SAC` rho and purity, a template SQI)
  report the AUC of right against wrong overall and inside the sub-multiple class alone, on the H1M/H2M/H3M windows. Add one
  cross-family consistency index (|60 / median RR - f0| / f0, HR1 on `R0`, HR3 = `HR3_SAC`) and count the sub-multiple values it
  flags.
- **Cost on the board.** Negligible. YIN 1 - d' costs one prefix sum and one pass over the lags beyond today's sweep (H2M
  estimate, not measured on a board).
- **Patents.** None found on YIN 1 - d' (2002 paper), on `HR3_SAC` (one keyword query, not exhaustive) or on a beat-count against
  spectrum consistency check. Avoid as SQI ingredients Covidien's lag-dependent first-peak bar (US 9,314,209 B2, to 2034-05-24)
  and its half-lag, harmonic and area qualification tests (to 2033-2035).

#### G4 (high). No reference for fast rate changes, so no hold, tracker or arbitrator can be judged on its release

- **Failure addressed.** Every cross-window layer trades honesty against the time it takes to follow a real change, and the
  device evidence (frozen pulse rate, missed bradycardias) is exactly that failure. The project's rate reference is a monitor
  number read by eye every 10 s, and windows where it changes by more than 10 % are excluded: fast changes are not judged (H3M
  Limits).
- **Evidence.** The metric definitions exist and are verified: frozen pulse rate = within 1 bpm for more than 20 s while the ECG
  rate changes by 25 bpm or more (Goldstein 2004); missed bradycardia = ECG below 80 bpm for more than 5 s not shown (Bohnhorst
  2000); false bradycardia at onset (Khoury 2021: 18 of 55 with Masimo against 0 of 55 with Nellcor, delivery room); recovery
  time after motion (Shah 2005-2006, adults). ECG heart-rate-meter yardstick [transfer: ECG meters; pulse plethysmographs are
  outside EC13's scope]: low, high and asystole alarms within a mean of 10 s over 5 trials with none above 13 s; error within
  +-10 % or +-5 bpm; neonatal range at least 30-250 bpm (YY 1079-2008, written with reference to the performance part of ANSI/AAMI
  EC13:2002).
- **Test.** Build episodes with ECG-rate steps and bradycardias from the MIMIC-III waveform pool (8,486 neonatal record sets;
  PLETH with some ECG lead about 95 % of the time) and from the coming preterm campaign (beat-level ECG if the new photo
  protocol works, H1M); add MS100 steps and the 250 bpm plateau. Report the four metrics above for every candidate layer of G2,
  G5 and G6.
- **Cost on the board.** None (bench only).
- **Patents.** None.

#### G5 (medium). No hold policy has been measured for the pulse rate (`DISP_HELD` is reserved)

- **Failure addressed.** `hr_disp` shows dashes after one bad second; a value is shown 55 % of the time overall and 0-11 % under
  motion (RAT §26). A bounded hold could raise what a display shows without a new estimator.
- **Evidence.** [transfer, ICU ECG and ABP] a gated sample-and-hold nearly equals a Kalman filter on one source (146 against 149
  of 201 false bradycardia alarms suppressed; 5.4 against 3.8 bpm rMSE at EM 6 dB; Li 2008, Li 2009). Device-level neonatal
  evidence against long freezes (Goldstein, Hay, Bohnhorst; section 2). Own evidence that the last value before motion is already
  contaminated (SpO2 hold, RAT §17). No study compares hold durations. Maker holds range from 10 s (Nonin, display mode) to 40 s
  (Nellcor) and 50 s (Nellcor PM10N pulse timeout).
- **Test.** For `hr_disp` and for the G2 arbitrator: hold 0 / 2 / 5 / 10 s of (a) the last value and (b) the last value from a
  window that ended before the quality drop (the "value from some seconds before" left open in RAT §26); measure the gain in shown
  time, the wrong share among held values and the G4 release metrics (frozen > 20 s, time to show an MS100 or ECG bradycardia
  step).
- **Cost on the board.** A few bytes and a timer.
- **Patents.** The hold/clear rule of US 5,853,364 is expired. US 7,922,665 and US 9,131,878 (in force to 2030-02-10 and
  2027-05-07) claim qualification constants, not holds.

#### G6 (medium). Nothing tracks the rate across windows

- **Failure addressed.** HR2 and HR3 decide each 0.5 s window alone; brief octave flips and motion lines are published as they
  come. The headroom on still neonates is small (`HR2_ACF` reads half or a third in 1.2 % of windows; `HR3_SAC` harmonic errors
  at most 0.2 %), larger under motion (SUBJ10: `HR3_SAC` 11.7 % on a harmonic ratio).
- **Evidence.** All transfer (section 2, rows 1-3): the gains are large only for weak frame-wise pickers, and trackers lock onto
  persistent sub-multiples (Ikuma 2025, Yu 2026), which is the neonatal breathing case (breathing near HR/2 or HR/3 in roughly
  40-50 % of regular-breathing time in the neonatal sources; ECG and respiration, no PPG; ctx_cardioresp verifier). A random-walk
  Kalman follows a consistent wrong value; in Li 2008 the SQI gate, not the Kalman, carried the gain (27.7 against 3.8 bpm).
  Philips FAST and Nellcor show the maker forms, without data; greedy single-candidate continuity (OxiMA, Fukuda) has no ablation
  and risks staying on a wrong lock.
- **Test.** Offline on the H2M/H3M windows: (a) an SQI-gated scalar Kalman on `hr3` (Q and R as in Li 2008, then chosen out of
  sample); (b) a fixed-lag forward/Viterbi over K = 3 **lag** candidates of HR2 (first peaks above 0.5, YIN 1 - d' as emission);
  (c) a seeded oscillator follower (Karlen's FLL) re-seeded by gated `HR3_SAC`, with adaptation frozen when the SQI is low.
  Report wrong / published, the G4 release metrics and the lag after an MS100 step.
- **Cost on the board.** Kalman: a few multiplies per update. K-candidate Viterbi: K^2 additions per hop plus an L x K traceback
  buffer. FLL: tens of operations per sample (41-47 us per sample on an iPod in Karlen 2013).
- **Patents.** Viterbi path metrics over **spectral** peaks above a threshold, with a transmission or reflection optical sensor
  and no accelerometer in claim 1: TI US 10,321,831 B2, Active, anticipated expiration 2036-08-16 (Google Patents copy of
  2026-11-23; the live re-fetch was blocked). A freedom-to-operate check is needed before any Viterbi over HR3 peaks; a lag-domain
  tracker has pYIN (2014, open source) as prior art. Mindray claim 6 (G2) also bears on any weighted cross-window map of spectral
  peaks. Loop forms: avoid SNR-scheduled loop filters (Murata US 9,717,462 B2, to 2034-09-16) and two-filter discriminators (ADI
  US 9,901,306 B2, to 2036-04-21); the plain zero-crossing FLL (US 4,955,379) is expired. Covidien Locked Mode: only the bare
  state machine, the tracking band-pass and the hold are free (abandoned applications); its qualification tests are in force to
  2033-2035.

#### G7 (medium). No motion flag shared by the arbitrator

- **Failure addressed.** Under motion every family degrades together (one IR channel), and agreement then certifies wrong values
  (H3M §E). An arbitrator needs an index that does not come from the three rate methods.
- **Evidence.** On a standard finger probe driven by a TI AFE4400 (5 adults, labels = commanded motion), the ambient-phase SQI
  had AUC 0.91 / 0.90 against 0.88 / 0.67 for the red-IR correlation and 0.84 / 0.71 for template correlation (Clarke 2015).
  Masimo's integrity is a red/IR adaptive-canceller residual (US 6,684,090, expired; the polarity of its threshold is not
  implementable as written). The project's own SpO2 work: the red/IR regression r stays at 0.96 under coherent motion (RAT §17),
  so r alone is not the flag.
- **Test.** On the SUBJ08-11 captures: AUC of the ambient-phase AC power ratio, the red-IR residual energy and `HR3_SAC` purity
  for windows where the families are wrong; then use the best as a gate inside the G2 arbitrator.
- **Cost on the board.** Low (the ambient phase and red are already acquired at 500 Hz).
- **Patents.** None found for the ambient-phase index; Masimo's three-measure layer is expired.

#### G8 (low). Errors are not reported against breathing

- **Failure addressed.** The project's one-third (HPS) and lag-multiple (HR2) errors are attributed to breathing at HR/2 or HR/3,
  labelled "hypothesis, not measured" (H3M §C).
- **Evidence.** Breathing near HR/2 or HR/3 in about 40-50 % of regular-breathing time in the neonatal sources (the split
  between HR/2 and HR/3 varies by source), while HPS reads f0/3 in only 4-7 % of windows: a coincidence of rates is not an error
  rate.
- **Test.** Transcribe the breathing rate from the snapshots (H3M decision 6) or take MIMIC RESP; report P(wrong | breathing
  within 10 % of HR/k) for each family and each arbitrator.
- **Cost.** None (bench only). **Patents.** None.

---

### 5. What the evidence does NOT show (absences searched for)

- **No arbitration, tracking or fusion of pulse-rate estimators validated on standard red/IR probe PPG against ECG with an
  ablation.** Verifier screens: Europe PMC (PPG or pulse oximetry) x (Viterbi or HMM or pYIN or dynamic programming) x (heart or
  pulse rate), 227 hits, first 60 titles: none; (PPG or pulse oximeter) x (median of, majority vote, median fusion) x (rate
  estimators), 116 hits, first 40 titles: none. The in-scope tracker results found (OxiMA, Karlen's FLL) have no ablation of the
  tracking step, or found no gain over a plain spectrum.
- **Nothing neonatal and nothing at 170-240 bpm** for any tracker, fusion or hold rule; the Karlen FLL covered 53-142 bpm; Li 2008
  used adult ICU data.
- **No maker patent reports the accuracy of its arbitrator, tracker or quality layer**, and the device-level studies never isolate
  the layer (several are sponsor-run or sponsor-hosted, and their rankings conflict).
- **No study compares hold durations** or tests a hold rule against alternatives.
- **No study tests Masimo-type three-measure confidence, or any template SQI, against rate error, and none on neonates.**
  Template-SQI neonatal screen: 247 Europe PMC hits, top 30 titles, none.
- **No head-to-head in which learned fusion beats rule-based fusion on a rate**; learning helped only the accept/hold/reject
  decision (speech).
- **No evidence that a cross-window tracker repairs a persistent sub-multiple**; the evidence found is that trackers lock onto
  them.
- **No SQI shown to detect a regular sub-multiple output on PPG.**
- **Almost no neonatal PPG below 100 bpm in the public benchmark** (MIMIC PERform test neonates: about 0.1 % of windows below
  100 bpm), so bradycardia release cannot be scored there.

Excluded but notable (wearable or exercise data, out of scope by the owner's rules): TROIKA spectral peak tracking; CITRUS (ring
and wrist; candidate agreement, causal Viterbi and a learned accept/hold/reject policy; reporting the most confident 50 % of
motion windows cut MAE from 10.8 to 6.2 bpm); BeliefPPG.

---

### 6. Sources

Read depth as recorded by the verifiers (full text / abstract / claims / snippet); the project documents were read for this
section.

**Project documents**
- PulseNest `docs/hr1_methods_20261116.md` (H1M): Q3, F3, part 3, Limits - full sections.
- PulseNest `docs/hr2_methods_20261115.md` (H2M): Results, parts 2-3, Decisions - full sections.
- PulseNest `docs/hr3_methods_20261114.md` (H3M): Results A-H, Limits, Decisions - full sections.
- PulseNest `docs/algorithm_prior_art_index.md` (IDX) §2.5, §4.3, §6 - sections.
- `incunest_afe4490_spec.md` v0.124b §2.1.1, §2.1.2, §5.5, §5.10, §14 - sections.
- `incunest_afe4490_design_rationale.md` §17, §22.1, §26 - sections.
- PulseNest `experiments/hr1_methods_20261116.py`, lines 335-365 (the H1M complement uses gated `HR3_SAC`) - code.

**Tracking, fusion and arbitration** (all transfer unless stated)
- Li Q, Mark RG, Clifford GD. Physiol Meas 2008;29(1):15-32. doi 10.1088/0967-3334/29/1/002, PMID 18175857 - full text. [ICU ECG + ABP]
- Li Q, Mark RG, Clifford GD. Biomed Eng Online 2009;8:13. doi 10.1186/1475-925X-8-13, PMID 19586547 - full text. [ABP]
- Shi X et al. Sensors 2023;23(24):9698. doi 10.3390/s23249698, PMID 38139544 - full text. [fetal Doppler]
- Tsanas A et al. JASA 2014;135(5):2885-2901. doi 10.1121/1.4870484, PMID 24815269 - full text. [speech]
- Drugman T et al. IEEE SPL 2018;25(11):1745-1749. doi 10.1109/LSP.2018.2874155; arXiv 1903.01290 - full text. [speech]
- Zhu T et al. EMBC 2015:6138-6141. doi 10.1109/EMBC.2015.7319793, PMID 26737693 - abstract. [PPG respiratory rate]
- Zhu T, Javed H, Clifton DA. Healthc Technol Lett 2021;8(2):25-30. doi 10.1049/htl2.12003 - full text. [PPG respiratory rate]
- Zhu T et al. Physiol Meas 2018;39:065008. doi 10.1088/1361-6579/aac856 - abstract. [PPG respiratory rate]
- Boersma P. Proc Inst Phonetic Sciences Univ Amsterdam 1993;17:97-110 (no DOI) - full text. [speech]
- Ikuma T, Kunduk M, McWhorter AJ. arXiv 2501.04789 (2025) - full text. [disordered voice]
- Mauch M, Dixon S. ICASSP 2014:659-663. doi 10.1109/ICASSP.2014.6853678 - full text. [singing]
- Yu C-Y, Peng C-J, Su L, Fazekas G. arXiv 2609.39852 (2026) - full text. [speech, music]
- Shi L et al. IEEE/ACM TASLP 2019;27(11):1737-1751. doi 10.1109/TASLP.2019.2930917; arXiv 1905.08557 - full text. [speech]
- Yarra C, Deshmukh OD, Ghosh PK. JASA 2018;143(4):2289-2300. doi 10.1121/1.5031129 - full text. [speech]
- Villarroel M et al. npj Digit Med 2019;2:128. doi 10.1038/s41746-019-0199-5, PMID 31872068 - full text. [camera PPG, preterm infants]
- Charlton PH et al. Physiol Meas 2016;37(4):610-626. doi 10.1088/0967-3334/37/4/610 - full text. [PPG respiratory rate]
- Karlen W et al. IEEE TBME 2013;60(7):1946-53. doi 10.1109/TBME.2013.2246160 - abstract. [PPG respiratory rate]
- Harvey J et al. (OxiMA). IEEE TBME 2019;66(2):311-318. doi 10.1109/TBME.2018.2837499 - full text (tables lost). [standard finger probe, adults; reference = another oximeter]
- Joarder R, Kasap B, Ghiasi S. (RT-TRAQ). Smart Health 2023. doi 10.1016/j.smhl.2023.100392 - full text. [transabdominal fetal oximetry]
- Karlen W et al. CCIS 2013;273:31-42. doi 10.1007/978-3-642-29752-6_3; 2011 paper doi 10.5220/0003134200300035 - full text. [CapnoBase clinical probe, children and adults]
- Fallet S. EPFL thesis 8493, 2018. doi 10.5075/epfl-thesis-8493 - full text of the relevant chapters. [ICU PPG alarms, camera PPG, synthetic]

**Quality indices**
- Pereira T et al. IEEE JBHI 2020;24(3):649-657. doi 10.1109/JBHI.2019.2909065, PMID 30951482 - full text.
- Sukor JA, Redmond SJ, Lovell NH. Physiol Meas 2011;32(3):369-384. doi 10.1088/0967-3334/32/3/008 - abstract.
- Chong JW et al. Ann Biomed Eng 2014;42(11):2238-2250. doi 10.1007/s10439-014-1080-y - abstract.
- Karlen W et al. Physiol Meas 2012;33(10):1617-29. doi 10.1088/0967-3334/33/10/1617 - abstract.
- Clarke GWJ. Signal quality analysis in pulse oximetry: modelling and detection of motion artifact. MASc thesis, Carleton University, 2015 (no DOI) - full text.
- de Cheveigne A, Kawahara H. YIN, a fundamental frequency estimator for speech and music. JASA 2002;111(4) - full text (hr2_yin verifier).

**Device-level studies and yardsticks (standard probes unless stated)**
- Bohnhorst B, Peter CS, Poets CF. Crit Care Med 2000;28(5):1565-8. doi 10.1097/00003246-200005000-00050, PMID 10834712 - abstract.
- Hay WW Jr et al. J Perinatol 2002;22:360-366. doi 10.1038/sj.jp.7210740, PMID 12082469 - abstract.
- Goldstein MR et al. Proc ATS 2004, A50 (conference abstract, Masimo-hosted copy) - full abstract.
- Khoury R et al. J Perinatol 2021;41(4):885-890. doi 10.1038/s41372-020-00881-y, PMID 33250516 - abstract.
- Shah N, Estanol L, Patel V. Anesth Analg 2006;102:S-108; Shah N, Estanol L. Anesthesiology 2006;105:A242 (recovery times) - full abstracts.
- YY 1079-2008 Electrocardiographic monitors (China), written with reference to ANSI/AAMI EC13:2002 - relevant pages read. [ECG meters]
- Krishnamurthi N et al. Pediatr Res 2026, doi 10.1038/s41390-026-04783-1 - full text; Joshi R et al. J Appl Physiol 2019;126(1):202-213, doi 10.1152/japplphysiol.00722.2018 - abstract and table 2. [ECG + respiration, no PPG]
- MIMIC-III Waveform Database v1.0 (PhysioNet, ODbL) - record headers sampled by the verifier.

**Patents** (status as read on Google Patents, 2026-11-22/23)
- US 5,853,364 A; US 7,865,224 B2 (Nellcor; adaptive comb, arbitration, hold-then-blank) - expired; full text of the rate sections.
- US 7,534,212 B2; EP 1 737 337 B1 (Nellcor; primary/alternate source, per-pulse IIR) - expired; full text.
- US 7,922,665 B2 (Nellcor; constants changed after N rejected pulses) - Active to 2030-02-10; claims.
- US 9,131,878 B2 (Covidien) - Active to 2027-05-07; claim 1.
- US 6,631,281 B1 (Philips FAST) - expired 2019-06-10; full text.
- US 6,684,090 B2; US 6,606,511 B1; US 7,024,233 B2 (Masimo Signal IQ) - expired; full text.
- US 9,247,887 B2, US 9,314,209 B2, US 9,186,101 B2, US 9,186,108 B2, US 9,392,974 B2, US 9,392,976 B2 (Covidien search/lock and
  qualification) - Active to 2033-2034; claims. Abandoned applications: US 2014/0073952, 0073959, 0073869, 0073974, 0073948, 0073949.
- US 10,321,831 B2 (TI; Viterbi over spectral peaks) - Active, anticipated expiration 2036-08-16; claims and PPG paragraphs.
- US 11,154,250 B2; US 11,872,060 B2; EP 3473171 B1 (Mindray; peak-position map across windows) - Active to 2037-09-14, 2037-02-10, 2036-06-15; claims.
- US 8,285,352 B2 (Nellcor; CWT + spectral candidate) - Active to 2031-07-28; claims.
- US 9,717,462 B2 (Murata loop filter) - Active to 2034-09-16; US 9,901,306 B2 (ADI discriminator) - Active to 2036-04-21; US 4,955,379 (zero-crossing FLL) - expired; claims or full text.
- JP 2019-122552 A (Fukuda; beat-seeded spectral band) - granted, to 2038-01-16, Japan only - machine translation.

---

## Chapter 5 - Inputs and evidence base: red + IR, decomposition and denoising, learned models, benchmarks, datasets, standards, device studies, neonatal facts

*Status: verified draft; not reviewed adversarially.*


Section of the final report of the pulse-rate survey. Written 2026-11-23.

**Question.** Do any input-side methods (both wavelengths, decomposition, denoising) or learned models have verified
evidence that they would improve the rate over what HR1, HR2 and HR3 do? What does the published evidence base
(benchmarks, datasets, standards, device studies, neonatal physiology) allow the owner to claim, and what must the owner
measure to claim more?

**How to read this section.**
- Every number comes from a verified record of the survey (`verify/<item>.md`, cited as V:<item>) or from the project's
  own documents: H1M = `docs/hr1_methods_20261116.md`, H2M = `docs/hr2_methods_20261115.md`, H3M =
  `docs/hr3_methods_20261114.md`, IDX = `docs/algorithm_prior_art_index.md`, SPEC = `incunest_afe4490_spec.md`,
  RAT = `incunest_afe4490_design_rationale.md`. Three facts were checked for this section and are marked
  [checked for T5]: the two red-vs-IR papers and the pulse-rate clauses of ISO 80601-2-61:2026.
- Catalogue items that no verifier checked are cited only as "not verified".
- **Transfer evidence** (speech, music, radar, fetal ECG or Doppler, arterial pressure, ECG meters) is labelled
  `[transfer]`. It is never evidence about PPG.
- "Wrong" means more than 10 % from the reference heart rate, as in the project's scoring.

---------------------------------------------------------------------------------------------------------------

### 1. Verdict

**No input-side method and no learned model has verified evidence that it would make the pulse rate less often wrong
than what HR1, HR2 and HR3 already do, and none has neonatal data.** Using red with IR for the rate exists only in maker
patents (Masimo DST/FST, Philips FAST, Nihon Kohden, Mortara, Nellcor's ensemble weights) that report no number. The
device studies that test those makers' monitors cannot isolate the red step, and their rankings conflict and follow the
sponsor. No study anywhere compares the same rate algorithm on IR alone against red + IR against an ECG. On a single
channel, red and IR give about the same rate error (two reflective-module studies in adults). Decomposition (EMD family)
gains at most sub-bpm precision on clean CapnoBase, with a cardiac band capped at 150 bpm. Respiration-harmonic
cancellation is radar-only and would delete the pulse line when the heart rate is a multiple of the breathing rate, which
is common in preterm infants. Learned beat detectors tie the classical detectors on clinical PPG, or win only against
weak baselines, in-domain or on synthetic noise; learned fusers lost to a median and to a hand-designed Kalman filter in
the two speech head-to-heads. **What the owner can claim:** (a) IR-only input is not shown to be dominated by any
published input-side method; (b) HR1 contains the detectors at the top of the only public neonatal ECG-referenced
benchmark (MSPTD and qppg/SSF, within about 1 F1 point of everything published there), measured causally by the project
on the same 100 test neonates. **What the owner cannot claim:** that HR2 or HR3 are "the best known". No published
neonatal benchmark of any lag or spectral rate estimator exists, and the project's own HR2/HR3 evidence is three
neonates scored against a monitor number read by eye, with parameters set on the same data. Nor can the owner claim to
match or beat makers: no rate-stratified or harmonic-error device study exists. **Evidence strength:** the statement
"no better input-side method" rests on absence of evidence (patents with no data, device-level studies, own-method
benchmarks, transfer evidence), not on a test that found red + IR or decomposition worse.

---------------------------------------------------------------------------------------------------------------

### 2. Best known methods and evidence sources for this topic

#### 2.1 Input-side methods and learned models

| Method | Why it counts as best known | Evidence strength | In the project? | Key source (identifier) |
|---|---|---|---|---|
| Masimo DST/SET red-IR noise-reference canceller, motion-gated, for the rate | The reference dual-wavelength rate path of a maker whose monitors lead several neonatal device benches; IR alone when still | patent_or_claim_only (patent has no data; device studies do not isolate it) | catalogued_not_evaluated (for SpO2 only) | US 5,632,272 (Masimo; expired 2014-05-27) |
| Spectral red/IR ratio labelling of rate candidates (Masimo FST and ratio lines; Philips FAST needles; Nihon Kohden minimum-ratio band) | The makers' way of using red to qualify spectral candidates; the closest to HR3 | patent_or_claim_only | catalogued_not_evaluated (the Philips FAST row mentions PR; the others SpO2 only) | US 6,631,281 (Philips, expired 2019-06-10); US 5,632,272; US 8,175,669 (Nihon Kohden, active to 2030-07-05) |
| Hayes & Smith red/IR log-difference equalisation | The only red + IR pre-processor measured on a standard transmission finger probe | own_benchmark_on_clinical_ppg (artefact power only; no rate) | absent | Hayes PhD thesis, Loughborough 1998 (figshare 9518504); Hayes & Smith IEEE TBME 2001, doi 10.1109/10.915711 |
| Mortara red/IR mix that maximises the normalised autocorrelation | The only maker text that couples a red/IR mix to a lag function | patent_or_claim_only (no data at all) | absent | US 6,564,077 B2 (expired 2021-11-17) |
| Nellcor beat-synchronous ensemble averaging, primary/alternate rate source | The maker denoising stage tied to a rate path | patent_or_claim_only | catalogued_not_evaluated | US 7,039,538 B2 (expired 2024-03-08); US 7,534,212 B2 (expired 2026-05-08) |
| EMD / EEMD / CEEMD decomposition before a spectral rate | The most cited decomposition for PPG rate; best precision row on CapnoBase | own_benchmark_on_clinical_ppg | catalogued_not_evaluated | Garde et al., Computing in Cardiology 2013;40:799-802 |
| Respiration-harmonic cancellation before f0 estimation `[transfer]` | The only class aimed at breathing lines in the heart band | other_signal_only (radar) | absent | Xu et al. Sensors 2026, doi 10.3390/s26175587 |
| PPG-PT pre-trained transformer as a beat detector | The only learned beat detector with a number on MIMIC PERform (pooled adults + neonates) | own_benchmark_on_clinical_ppg | absent | Davies, Monsen, Mandic, arXiv 2407.20775 |
| Neural peak-probability detectors (TAU, CNN-SWT, U-Net) | The learned class with head-to-head numbers on clinical finger PPG | head_to_head_on_clinical_ppg, biased (in-domain training, weak baselines) | catalogued_not_evaluated (class level, IDX §2.5) | arXiv 2503.10733; arXiv 2605.16452 |
| Learned per-pulse qualification (Belal ANFIS; Nellcor neural nets) | The only learned classifier on neonatal pulse-oximeter pulses; a maker uses one in its rate path | own_benchmark_on_clinical_ppg (visual labels, no rate error) | catalogued_not_evaluated (IDX §2.1) | Belal et al. Artif Intell Med 2002, doi 10.1016/s0933-3657(01)00099-9; US 7,922,665 B2 (active to 2030-02-10) |
| Learned fusion / arbitration of several rate estimates `[transfer]` | The learned answer to the missing arbitrator | other_signal_only (speech pitch; PPG respiratory rate) | absent | Drugman et al. IEEE SPL 2018, doi 10.1109/LSP.2018.2874155; Tsanas et al. JASA 2014, doi 10.1121/1.4870484 |

#### 2.2 Evidence base: benchmarks, datasets, standards, device studies, neonatal facts

| Source | Why it counts as best known | Evidence strength | In the project? | Key source (identifier) |
|---|---|---|---|---|
| ppg-beats benchmark on the MIMIC PERform neonates | The only public neonatal ECG-referenced set with published per-detector results; ranking stable across three papers | head_to_head_on_clinical_ppg | implemented (HR1 only) | Charlton et al. Physiol Meas 2022, doi 10.1088/1361-6579/ac826d |
| MIMIC-III Waveform Database, neonatal pool | The largest open NICU PLETH + ECG at 125 Hz | none (dataset) | absent (only the MIMIC PERform subset is used) | PhysioNet mimic3wdb 1.0 |
| CapnoBase cross-family HR table | The only clinical-probe table across beat, spectral and decomposition methods | head_to_head_on_clinical_ppg (one group, not neonatal) | absent | Garde et al. PLoS One 2014, doi 10.1371/journal.pone.0086427 |
| Commercial oximeter pulse rate against ECG in newborns | The only neonatal comparisons of maker rate paths against ECG | head_to_head_on_clinical_ppg (whole devices) | catalogued_not_evaluated | Bohnhorst 2000 PMID 10834712; Dawson 2013 PMID 23800004; Khoury 2021 PMID 33250516 |
| Adult motion / low-perfusion device benches | The metric definitions makers and competitors publish (PR within 10 %, more than 25 bpm off, zero-out, recovery) | head_to_head_on_clinical_ppg (whole devices, sponsor-dependent) | catalogued_not_evaluated | Gehring 2000 Anesthesiology 93:A-584; Vikne 2025 doi 10.1371/journal.pone.0326674 |
| ISO 80601-2-61:2026 pulse-rate clauses | The binding standard of the device class | none (standard) | implemented in part (range disclosure; numbers taken from WHO-UNICEF 2019) | ISO 80601-2-61:2026 §201.12.1.104, §201.12.4.101 [checked for T5] |
| EC13 heart-rate-meter tests (via YY 1079-2008) `[transfer]` | The closest numeric test suite for a rate meter | other_signal_only (ECG standard; excludes PPG devices) | absent | YY 1079-2008; Pstras 2025 doi 10.3389/fphys.2025.1638809 |
| Cardiorespiratory ratio in neonates | Quantifies how often breathing sits near HR/2 or HR/3 | other_signal_only (ECG + respiration, no PPG) | absent | Joshi et al. J Appl Physiol 2019;126(1):202-213, doi 10.1152/japplphysiol.00722.2018; Krishnamurthi et al. Pediatr Res 2026, doi 10.1038/s41390-026-04783-1 |
| Red alone vs IR alone, same detector | The only direct test of the channel choice | other_signal_only (reflective modules, adults) | absent as a benchmark; supports IR-only | Ricci et al. Sensors 2026, doi 10.3390/s26102986 [checked for T5] |

---------------------------------------------------------------------------------------------------------------

### 3. What the project already has that matches the best known

#### 3.1 Channel choice

- HR1, HR2 and HR3 read only `ot_led1` (IR, ambient-subtracted transmittance normalised by LED current). Red
  (`ot_led2`) is acquired at the same rate and today serves SpO2 only (SPEC §3, §5; V:prep_hayes_log_difference). The
  red-IR regression correlation of the SpO2 path (R-METHOD-2, gate 0.8) is the only place where red and IR are judged
  together (IDX §4.2). Red travels in `$M4` frames (`OT_LED1`, `OT_LED2`; `pulsenest_lab_spec.md` frame table), so
  captures recorded in that mode can replay any red-based test offline.
- The published single-channel evidence does not contradict the IR-only choice [checked for T5]:
  - Ricci et al. 2026: 30 healthy adults at rest, reflective MAX30101 and ADPD144RI modules, the same peak detector on
    each wavelength, ECG reference. Finger HR error: MAX30101 red 1.06 +/- 1.52 % vs IR 1.31 +/- 2.20 %; ADPD144RI red
    5.71 +/- 6.10 % vs IR 6.07 +/- 7.19 %. The authors: "RED and IR signals show comparable performance across sites".
  - Longmore et al. 2019: four participants (the authors), MAX30102 reflective modules at 8 sites, reference a
    commercial pulse oximeter (not ECG): "the difference between the red and infrared channels for heart rate
    measurement was not statistically significant at all test sites".
  - Neither uses a standard transmissive probe, a neonate or a red + IR combination. What follows from them is only
    "red alone is not better than IR alone".

#### 3.2 Input-side changes the project measured against ECG

These are the only input-side measurements on neonatal PPG in scope, and they are the project's own.

| Change | Data | Result | Source |
|---|---|---|---|
| HR1 front-end high-pass corner 0.5 / 0.3 / 0.2 Hz | 100 training neonates (stage 1, pooled F1 of the best eligible configuration) | SSF 96.45 / **97.48** / 97.42 %; THR 94.41 / 93.71 / 92.67 % | H1M Part 3 |
| Proposed HR1 chain (SSF, eye-closing 0.30 s, slope 0.17 s, high-pass 0.3 Hz, + R0) vs v0.122 (THR + R0, 0.5 Hz) | 100 test neonates | pooled F1 96.4 vs 91.5 %; published 78.1 vs 63.4 %; wrong of published 0.40 vs 0.57 % | H1M Part 3 |
| HR2 band-pass high edge 3 / 4 / 5 Hz (buffers 4-8 s, min_corr chosen out of sample) | 3 ECG neonates, leave-one-subject-out | score 66.7-68.2 / 72.4-73.5 / 74.5-76.4; wrong of published 8.4-9.5 / 5.6-7.4 / 4.7-6.5 %; the library's 5 Hz kept | H2M Part 3, A2 |
| HR2 buffer 8 s -> 6 s | same | start-up 2 s faster at the median and 5 s at the 90th percentile, for 0.2 points of score; adopted in lib v0.121 | H2M Part 3, A3 |
| HR3 local-contrast spectrum (inside HR3_SAC) | 3 ECG neonates | right 97.9 / 98.5 / 99.8 %, octave errors <= 0.1 %; right in 96.6-100 % of the windows where HPS reads f0/3 | H3M; V:hr3_sac |

The local contrast of HR3_SAC (dB above a +/-8-bin median) is itself a spectral flattening step. It is the input-side
change with the largest measured effect in the whole survey, and it is the project's own (in-sample, three subjects).

#### 3.3 Benchmarks and data already used

- **MIMIC PERform test and training neonates (HR1 only).** The project runs its causal chains on the 100 test neonates
  with Charlton's reference rules and its own QRS detectors (H1M F2): median F1 MSPTD 97.9, SSF 97.5, THR 93.9,
  TERMA 90.3 %; pooled MSPTD 95.7, SSF 96.1, THR 91.5 %. All four lose beats rather than invent them (PPV >= 99.8 %).
  Beats missed at >= 170 bpm: THR 21.9, TERMA 33.4, SSF 14.0, MSPTD 12.6 % (H1M Q2). Charlton 2022 on the same
  neonates: MSPTD 95.9, qppg 95.2 % (V:ctx_ppgbeats_mimic_perform). Same order; the project's higher values reflect its
  stricter reference windows (H1M).
- **PhysioNet/CinC 2015 adult ICU records with a true bradycardia alarm** for real slow pulses: 641 slow beats from 30
  records; 21 records, 164 windows and 1,125 ECG beats for the Se/PPV check (H1M Part 2 corrected). No open neonatal PPG
  below 87 bpm was found (H1M Limits).
- **Own captures.** SUBJ08, SUBJ09, SUBJ11: the ward monitor's ECG heart-rate number, photographed every 10 s and read
  by eye, 122-195 bpm, stable readings only. SUBJ10: the monitor's pulse rate, i.e. another oximeter (H3M). MS100
  plateaus 20/30-240 bpm (H1M, H2M, H3M).
- **HR2 and HR3 have never been scored on MIMIC PERform** (V:ctx_ppgbeats_mimic_perform, check 4).

#### 3.4 Standards and the scoring scale

- SPEC §5.2 takes the reported range 30-260 bpm and the +/-3 bpm margin from WHO-UNICEF 2019 §6.5 (range to include
  30-240 bpm, accuracy +/-3 bpm, valid-data update <= 10 s) and cites ISO 80601-2-61 only for the disclosure of displayed
  ranges; RAT §8 records why. This matches the ISO text [checked for T5]. §201.12.1.104 requires pulse-rate accuracy to
  be disclosed as the RMS difference against a reference (an electronic simulator, ECG heart rate, palpation,
  auscultation, a qualified second oximeter or any other sufficiently accurate method), over the full range or in
  segments, and sets **no numeric limit**. §201.12.4.101 requires a "not current" indication when the data update period
  exceeds 30 s and says it "should be shorter than 30 s for continuous neonatal monitoring". The motion and
  low-perfusion clauses (§201.12.1.102-103) apply only if the maker claims accuracy there, and they concern SpO2
  against SaO2.
- **Documentation fix.** A row of RAT's filter-comparison results table ("Reference scale: ISO 80601-2-61 HR accuracy
  +/-3 BPM") attributes the +/-3 bpm to ISO. ISO sets no number; the +/-3 bpm is WHO-UNICEF's, as RAT §8 itself states.
- The project's "wrong" (more than 10 % from ECG) matches numerically the "PR off by more than 10 %" of the adult motion
  benches (Shah 2005), but those benches use a same-model oximeter on the still hand as reference
  (V:ctx_device_bench_adult_motion).

#### 3.5 Learned models

None in the rate path. IDX §2.5 lists "learned models as a class of their own" as not evaluated, with "no neonatal
training set"; IDX §4.1 catalogues Nellcor's sensor-off neural net. No learned method appears in H1M, H2M or H3M.

---------------------------------------------------------------------------------------------------------------

### 4. Gaps, ranked

#### Gap 1 (HIGH). HR2 and HR3 have no score on an open ECG-referenced neonatal set

- **Failure it addresses.** The project cannot state anything about HR2/HR3 beyond three neonates read from a monitor
  number, with parameters set on the same data. The two known failures (HR3_HPS publishing f0/3; HR2_ACF lag multiples
  and more wrong values above 170 bpm) are measured only there.
- **Evidence.**
  - No published neonatal benchmark of any lag or spectral rate estimator exists (section 5).
  - On the MIMIC PERform neonates, MorphSSF's own period estimator (a biased ACF of the slope-sum signal, first
    sufficiently strong peak, 20 s windows) is within 10 % of half or twice the ECG RR in **6.11 %** of neonatal windows,
    against **0.72 %** in adults (Desai & Shi 2026, table 19; V:ctx_ppgbeats_mimic_perform). This is direct neonatal PPG
    evidence that the HR2-type failure exists on this data, at a rate well above the 1.2 % (half 0.9 %, third 0.3 %)
    measured for HR2_ACF on the project's own neonates (V:hr2_acf_first_peak). The estimator differs from HR2_ACF, and
    the flag also counts doubling.
  - The test neonates cover the f0/3 zone. Independent recount: median HR 156 bpm, P99 203, 11.0 % of windows at
    >= 180 bpm, 1.4 % at >= 200, 0.07 % at >= 220, 0.13 % below 100 (V:ctx_ppgbeats_mimic_perform).
  - Only a median of 4.0 of 10 min per neonate survives Charlton's reference rules, so the set is clean-ECG and
    optimistic for motion (V:ctx_ppgbeats_mimic_perform; H1M Limits).
- **Test.** Run HR2_ACF (with YIN 1 - d' as a candidate quality index), HR3_HPS and HR3_SAC on the 100 training
  neonates first, then once on the test neonates, with H1M's reference and rate-level scoring (wrong > 10 %, half/third
  classes, per-HR band, availability). Then mine the MIMIC-III WDB neonatal pool for segments at 165-220 bpm: 8,486
  neonatal record sets, about 834,000 recorded hours (95 % interval 587,000 to 1.1 million), PLETH + any ECG in 95 % of
  recorded time, PLETH + lead II in 41 % (V:ctx_mimic3wdb_neonatal_pool). MIMIC PERform used 33 h, less than 0.01 % of it.
- **Cost on the board.** None (offline). Limits: the monitor's pleth (filtered, auto-scaled, 125 Hz), not raw OT, so
  rankings transfer and thresholds do not; the ECG was peak-picked, with 2-14 ms sample intervals; no gestational age
  without a PhysioNet credential.
- **Patents.** None.

#### Gap 2 (HIGH). No fresh, held-out neonatal set with beat-level ECG and a breathing signal

- **Failure it addresses.** Every final claim. The MIMIC PERform test neonates have been read by three project runs
  (H1M Limits), and parameters were chosen on the training neonates of the same database, so the benchmark is no longer
  independent of the project (V:ctx_ppgbeats_mimic_perform). The own-capture reference is a number every 10 s that the
  monitor itself averages (H3M Limits).
- **Evidence.** HR3_SAC's parameters were fixed after seeing SUBJ10 (H3M Limits). HR2 parts 2-3 are leave-one-subject-out
  over three subjects (H2M). SSF part 3 is the only out-of-sample HR1 choice, and its test set is the thrice-read one.
- **Test.** The coming preterm campaign: record the monitor's ECG waveform (beat level), its impedance respiration and the
  project's raw red + IR OT together. Freeze every candidate's parameters and the scoring script before the first look.
- **Cost on the board.** None.
- **Patents.** None.

#### Gap 3 (HIGH). The breathing explanation of the f0/3 picks and lag multiples is untested

- **Failure it addresses.** It decides whether any respiration-aware input method (harmonic cancellation, a respiratory
  notch, red/IR ratio labelling of candidate lines) can help at all. The project labels the cause "Hypothesis, not
  measured" (H3M §C) and notes that the respiration rate was not measured for HR2 (H2M Limits).
- **Evidence (neonatal physiology from ECG + respiration, no PPG).**
  - Krishnamurthi et al. 2026: 191 extremely preterm infants, 30 s segments. About 12 % of good-quality segments are
    synchronised, and 2:1 (breathing at HR/2) is the commonest ratio; only 21 % of the data had sufficient quality.
  - Clark et al. 2012: cardiorespiratory interaction in 3.3 of 18 patient-years (18 %), 1,202 NICU patients.
  - Joshi et al. 2019: 20 preterm infants at PMA about 31 wk; HR 152-156 bpm, breathing 47-51/min, ratio about 3.1.
  - PICS re-run (10 preterm infants): HR/BR median 2.07; breathing within 10 % of HR/2 in 30.5 % and of HR/3 in 14.1 %
    of regular-breathing windows; the breath peaks are unvetted. Only the combined share (about 40-50 % near HR/2 or
    HR/3) is roughly stable across sources (V:ctx_cardioresp_ratio_occurrence).
  - A coincidence is not an error rate: HR3_HPS reads f0/3 in 4-7 % of its valid windows at 165-175 bpm (H3M;
    V:hr3_hps), while breathing sits near HR/3 in 14-34 % of the time depending on the source.
- **Test.** Read the respiration rate in the f0/3 episodes (monitor snapshots, H3M decision 6) and, on MIMIC, from the
  RESP channel. Report P(HR3_HPS f0/3 | breathing within 10 % of HR/3), P(HR2_ACF multiple | breathing near HR/k), and
  the same for HR3_SAC.
- **Cost on the board.** None.
- **Patents.** None for the measurement. GE US 2008/0167541 A1, a respiration-notch spectral weighting, is abandoned and
  free (V:hr3_ge_resp_notch).

#### Gap 4 (MEDIUM). Red as a second input has never been tried for the rate, here or anywhere with an ECG reference

- **Failure it addresses.** Motion bursts (SUBJ10: 11.7 % of HR3_SAC windows on a harmonic ratio, V:hr3_bayes_tracker),
  and possibly the f0/3 picks if they are respiratory. HR1/HR2/HR3 have no motion reference other than the signal itself.
- **Evidence (all verified; none is a rate error against ECG for the red step).**
  - **Masimo DST canceller** (US 5,632,272). When the IR spectral peak is wide (motion), a noise reference built from the
    red/IR ratio drives an LSL joint-process canceller (6-10 cells, lambda 0.98) on IR, and the tallest spectral peak is
    taken. When still: IR alone, first peak >= 1/20 of the largest over 30-250 bpm. The patent has no data. Device level,
    product against product: Gehring 2000, PR more than 25 bpm off 1.1 % (Masimo) vs 5.3-53 %; Bohnhorst 2000,
    bradycardias missed 7 % vs 69 %; but Khoury 2021, false bradycardia at birth 18/55 (32.7 %) vs 0/55 (Nellcor); Murphy
    2019, initial bradycardia 55 % vs 6 % between randomised groups; a Medtronic internal study, RMSD 25.2 vs 8.6 bpm; a
    GE white paper, 42.1 % out of specification vs 16.9 %. None isolates the canceller (V:prep_masimo_dst_canceller). Its
    still-path rule would pick neonatal breathing, since 30-80/min lies inside 30-250 bpm.
  - **Spectral red/IR ratio labelling** (Masimo FST, Philips FAST needles, Nihon Kohden minimum-ratio band): no patent
    gives a rate number and the device studies cannot isolate the step (V:prep_spectral_ratio_labelling). The physics is
    unsettled: Masimo's own model puts respiration in the venous/noise part, so a respiratory f0/3 line might carry a
    different ratio from the arterial line, but nobody has measured it.
  - **Hayes & Smith log-difference** (standard transmission finger probe, IR as measurement, red as control):
    out-of-band probe-coupling artefact up to 70 % and distal bending up to 90 % of signal power brought below the clean
    floor (mean 7.2 %); no ECG and no rate error; the artefacts were induced above 3 x f0 by design. On the project's
    neonatal curve (SpO2 = 123.98 - 39.13 R), the surviving pulse is about 31 % of IR at 97 % SpO2, 26 % at 95 %, 13 % at
    90 % and zero near 85 % (V:prep_hayes_log_difference): the rate would vanish during desaturations.
  - **Mortara max-ACF mix** (US 6,564,077): selects the red/IR mix at the global ACF maximum over [Tmin, Tmax], i.e. a
    tallest-peak picker, HR2's failure mode; no data (V:prep_mortara_acf_mix).
  - **Red-IR correlation as a motion flag.** Clarke 2015 MASc thesis (5 healthy adults, TI AFE4400 + Nellcor DS-100A
    finger probe): red-IR correlation AUC 0.88 at high motion; an ambient-light SQI did better (AUC 0.91 / 0.90), and
    template cross-correlation reached 0.84 / 0.71 (V:rule_template_similarity_sqi).
- **Test (offline, on `$M4` captures that carry `OT_LED2`).** (a) In the HR3_HPS f0/3 windows, compare the red/IR
  ratio of the f0/3 line with that of the cardiac line. (b) In motion bursts, put a motion-gated red-IR canceller or the
  log-difference in front of HR3_SAC and HR2_ACF, and score against the SUBJ08/09/11 ECG number (SUBJ10 only as an
  indication). (c) As a motion flag for an arbitrator, compare red-IR correlation with the AFE ambient-phase signal.
  Score as in H3M.
- **Cost on the board.** A second band-pass, one LMS or one extra FFT of red per window: small next to HR3_SAC's
  4.5 ms per window (H3M addendum). Not measured.
- **Patents in force.** Masimo DST/FST (expired 2014), Philips FAST (expired 2019) and Mortara (expired 2021) are free.
  Nihon Kohden US 8,175,669 B2 is active to 2030-07-05; its claims cover SpO2 from the ratio at the maximum-amplitude
  spectral bins, not the rate, but they may read on the project's measured-not-adopted harmonic-bin R estimator
  (V:prep_spectral_ratio_labelling). Edan CN 101991410 B (active to 2029-08-31, China only) describes, in its description
  and not its claims, a red-IR residual that holds the HR (V:hr1_edan).

#### Gap 5 (MEDIUM). No metrics or bench tests comparable with makers and rate-meter standards

- **Failure it addresses.** Without them the project cannot compare its honesty and availability with commercial
  monitors, nor document the hold/withhold policy an arbitrator will need.
- **Evidence.**
  - Neonatal device studies against ECG test whole black boxes, mostly by reading screen values every 1-30 s
    (V:ctx_device_bench_neonatal_vs_ecg). Bohnhorst 2000: 17 preterm infants, bradycardia < 80 bpm for > 5 s; missed by
    32 % conventional, 69 % Nellcor (pre-OxiMax), 7 % Masimo. Dawson 2013: 44 term newborns, bias 0.2 +/- 9 bpm Masimo vs
    -0.8 +/- 11 bpm Nellcor. Kamlin 2008: -2 +/- 26 bpm in the delivery room. Khoury 2021: false bradycardia 18/55 vs
    0/55. Goldstein 2004 (30 neonates, 179 h; Masimo-hosted conference abstract): frozen PR, within 1 bpm for > 20 s
    during a >= 25 bpm ECG change, in 8 (Masimo) / 47 (Philips) / 59 (N-595) / 61 (N-395) episodes. Iglesias 2018: 69 %
    of bradycardia onsets missed, with a lag resolved only to 5 s. No study stratifies by rate or reports harmonic
    errors, and none covers rates above 160 bpm.
  - Adult benches (V:ctx_device_bench_adult_motion). Gehring 2000 (10 volunteers, ECG), time with |PR - HR| > 25 bpm:
    Masimo 1.1, N-395 5.3, Agilent 8.5, N-3000 37, Datex 3900 53 %. Shah 2005-2006 (Masimo-hosted; reference a same-model
    oximeter on the still hand), PR within 10 %: Masimo 82.9-95.4 %, others 57.4-85.7 %. Vikne 2025 (17 adults at rest,
    ECG): pooled RMSE 2.2-5.1 bpm; no device met +/-6 bpm limits of agreement at 85-100 % SaO2.
  - EC13 via YY 1079-2008 `[transfer]`: error within +/-10 % or +/-5 bpm, whichever is greater; neonatal range at least
    30-250 bpm; inputs at 350 bpm or at the mid-point between 350 bpm and the maximum must not read below the maximum;
    inputs at 0 or 25-50 % of the minimum must not read above the minimum; low/high/asystole alarms within 10 s as the
    mean of 5 trials, no trial over 13 s. EC13, IEC 60601-2-27:2011 and the FDA guidance exclude pulse-plethysmographic
    devices (V:ctx_ec13_hr_meter_tests).
- **Test.** Report on every bench: time within 10 % of ECG; withheld time; Bohnhorst's missed bradycardia; the
  Goldstein/Hay frozen-PR rule; false bradycardia during the first minute after probe application (Khoury); recovery time
  after motion; the ISO RMS against ECG per rate segment. Run the EC13 over-range and step tests on the MS100 (its range
  stops at 250 bpm, so the 350 bpm input needs a synthetic source). Co-record the ward monitor's pulse rate and ECG heart
  rate together: the only same-patient maker comparison available (the unit's SpO2 modules are Nellcor OxiMax, per
  V:hr3_mindray_psa).
- **Cost on the board.** None.
- **Patents.** None for metrics.

#### Gap 6 (MEDIUM). The range edges are absent from every benchmark the project uses

- **Failure it addresses.** The range and low-perfusion criterion (weight 15): HR3_SAC fails at 30 bpm on the MS100,
  HR2_ACF reads the 30 bpm plateau 50.3 % of the time, SSF part 3 reads 61 at the 30 bpm plateau (H1M, H2M, H3M), and
  the missed beats concentrate above 170 bpm.
- **Evidence.** Test neonates: 1.4 % of windows >= 200 bpm, 0.07 % >= 220, 0.13 % < 100 (V:ctx_ppgbeats_mimic_perform).
  No open neonatal PPG below 87 bpm (H1M Limits). MS100: no plateau between 30 and 60 bpm, and its 30 bpm plateau tests
  the simulator's stretched template, not a slow heart (H1M Part 2 corrected). EC13 asks for at least 30-250 bpm
  neonatal; the library reports 30-260 bpm (SPEC §5.2). Occurrence statistics (Alonzo 2018; SVT in about 0.1 % of NICU
  admissions) and RR-driven PPG simulators are catalogued but not verified.
- **Test.** Mine MIMIC-III WDB neonatal numerics for HR > 200 and < 80 bpm and score those segments; the pending MS100
  capture at 35-55 bpm (H3M decision 2); an RR-driven PPG simulator with respiratory modulation added (not verified).
- **Cost on the board.** None.
- **Patents.** None.

#### Gap 7 (LOW). Learned models: documented as not adopted, but only one test could settle it

- **Failure it addresses.** A reviewer's first question ("why no network?"); not a known failure of HR1/HR2/HR3.
- **Evidence.**
  - PPG-PT: median F1 98.04 % on MIMIC PERform Testing, pooled over 100 adults + 100 neonates, against qppg 96.9 and
    MSPTD 97.5 % copied from Charlton 2022, which used a different ECG reference and window exclusion. Fine-tuned
    in-domain on MIMIC PERform Training; no neonatal split (Charlton's neonatal values are 95.9 / 95.2); about
    0.6-0.9 GFLOP per 10 s window. The abstract says "state-of-the-art", the results section "comparable" (V:ml_ppg_pt).
  - TAU, trained on wrist PPG-DaLiA only: on finger BIDMC, 10 s HR MAE 1.30 vs Elgendi 1.25 bpm; CapnoBase 0.36 vs 0.39;
    worse at 8 s on BIDMC (1.90 vs 1.75) (V:ml_peakmap_net).
  - Li 2026, in-domain 4-fold CV, +/-30 ms, neurokit2 default comparators: BIDMC F1 0.986 / 0.983 / 0.969 vs Elgendi
    0.952 and MSPTD 0.929 (an MSPTD measured elsewhere at 98.79 % on BIDMC). HR MAE gains are at most 0.8 bpm, and two
    networks are worse than Elgendi on one set each. Its own model's PPG F1 advantage is not significant on BIDMC
    (p = 0.22) (V:ml_peakmap_net, V:ml_beat_qualifier).
  - PCPD: clean BIDMC F1 97.03 vs MSPTD 98.79, qppg 98.61, ERMA 98.90 %; better only with synthetic pulse-free noise
    inserted (97.06 vs 91.57 / 87.32 %); reference peaks seeded with a 0.4 s minimum distance, i.e. <= 150 bpm (V:ml_pcpd).
  - Belal 2002 ANFIS on neonatal and paediatric pulses: AUC 0.92, Se 87 %, Sp 74 %, accuracy 81 %; better than a 95 % CI
    threshold rule only in specificity (P = 0.008); visual labels, no ECG, no rate error (V:ml_beat_qualifier).
  - Learned fusion `[transfer]`. Drugman 2018: a median of 3 estimators (GPE 1.95 %) beat MLP selection (2.39), KNN
    (2.53) and CREPE (3.51), while the MLP won the voicing decision (VDE 3.11 vs 5.4-5.6 %). Tsanas 2014: learned OLS
    (7.58 Hz RMSE) and IRLS (6.53) ensembles lost to the best single estimator (6.22) and to a hand-designed adaptive
    Kalman filter (4.95, tuned on the same data). Zhu 2015 (PPG respiratory rate; batch, non-causal): 1.98 vs best single
    2.39 vs benchmark 2.22 breaths/min (V:ml_learned_fusion).
  - Learned octave validators exist only in music tempo `[transfer]` (Schreiber & Mueller 2017: A1 69.0 -> 77.4 % on
    Combined, significant losses on SMC and ISMIR04). HR3_SAC has 0.0 % half or third errors, and a hand octave vote (R3)
    gained nothing on the project's data (V:ml_octave_validator).
- **Test.** Re-run the public PPG-PT weights on the test neonates with the project's scoring: the only test that would
  settle it (V:ml_ppg_pt). If a per-pulse qualifier or an octave validator is wanted, train a tiny classifier on the
  MIMIC PERform training neonates (ECG-labelled) and compare it with a deterministic rule on the same features.
- **Cost on the board.** PPG-PT is eliminated by cost and by its per-window rescaling (no streaming). A small classifier
  fits, but it must be frozen and unit-tested to stay deterministic and auditable.
- **Patents in force.** Nellcor US 7,922,665 B2, to 2030-02-10: claim 1 covers modifying a pulse-qualification constant
  once a designated number of pulses has been rejected (V:ml_beat_qualifier). Covidien US 9,220,423 B2, to 2033-10-30,
  claims sorted-difference signals; its neural-net-built table is in the description only (V:ml_octave_validator).

#### Gap 8 (LOW). Decomposition, respiration-harmonic cancellation and ensemble averaging: record why not adopted

- **Failure it addresses.** None measured; these are the stages a reader expects to see considered.
- **Evidence.**
  - EMD family (V:prep_emd_family). Garde 2013: 42 CapnoBase records, 60 s windows, median HR RMS error 0.35 bpm; plain AR
    PSD 0.58 bpm in Garde 2014, with 120 s windows and a wider 0.5-3 Hz band. No test separates the two, and in Garde
    2014 no HR difference against CSD was significant (Wilcoxon). Lei 2020 (90 ICU patients): CEEMD+ICA+NMF 99.95 % vs
    plain EMD 99.93 %. Every cardiac band in the sources stops at 150 bpm; no source reports octave errors; EEMD is random
    unless seeded, and sifting counts depend on the data.
  - CapnoBase cross-family table (V:ctx_capnobase_cross_family): CSD 0.76, AR 0.58, Karlen beat segmentation 0.48,
    EMD + AR 0.35 bpm median RMS (29 children aged 4.8 +/- 5.4 y and 13 adults under anaesthesia; windows 32-120 s; CSD
    band to 180 bpm). All 15 beat detectors exceed 93 % F1 on CapnoBase (Charlton 2022). The families do not separate on
    clean non-neonatal data.
  - Respiration-harmonic cancellation `[transfer]`, radar only (V:prep_resp_harmonic_cancel). Xu 2026 (10 seated
    subjects aged 12-53), share of estimates within 5 %: DFT/EEMD 87.5-98.2 % vs 95.3-98.6 %. Tang 2025: RMSE 14.41 ->
    6.37 -> 1.20 bpm on one 280 s segment, most of the gain from a harmonic acceptance test. With HR:breathing ratios of
    2-3, a breathing harmonic sits on the heart line in about 45 % of preterm regular-breathing windows, so the
    cancellation would remove the pulse.
  - Nellcor ensemble averaging (V:prep_ensemble_avg): the primary rate source uses non-averaged waveforms; the averaged
    one is used only after the primary rejects a pulse. A comb locked at 2T or 3T still passes f0/2 or f0/3, and the
    stage adds about 1 s of delay. No patent gives data.
  - VMD, SSA, ICA, wavelet beat detectors, CFSA and learned denoisers are catalogued but not verified.
- **Test.** None needed unless Gap 3 shows that breathing drives the errors; then one offline A/B of a respiration notch
  or cancellation in front of HR3_HPS only, on the ECG subjects.
- **Cost on the board.** EMD/EEMD: data-dependent sifting, non-deterministic unless seeded, heavy. Ensemble averaging:
  one period buffer.
- **Patents in force.** Nellcor US 8,801,622 B2 (alternate weighting, to 2028-06-26) and US 7,922,665 B2 (to 2030-02-10)
  belong to the same rate-path family; the averaging patents themselves have expired (V:prep_ensemble_avg).

---------------------------------------------------------------------------------------------------------------

### 5. What the evidence does NOT show (absences searched for)

- **No same-algorithm comparison of the rate from IR alone against red + IR, against an ECG, on any population.** The
  round-2 dual-wavelength search (about 45 queries over PubMed, Europe PMC, Crossref, arXiv, patents and theses; finder
  notes `finders/r2_clinical_bench_3.md`) found none. The single-channel comparisons are reflective modules in adults
  (section 3.1).
- **No maker patent on a rate path reports any accuracy number** (Masimo, Nellcor, Philips, Nihon Kohden, Mortara;
  V:prep_* and V:ctx_*_rate_path records).
- **No device study isolates an algorithmic step, stratifies by heart rate or reports harmonic (half/third) errors,**
  and none covers rates above 160 bpm (V:ctx_device_bench_neonatal_vs_ecg). Rankings change with the study and the
  sponsor (V:ctx_device_bench_adult_motion).
- **No published neonatal benchmark of any lag (HR2-type) or spectral (HR3-type) pulse-rate estimator** on standard-probe
  PPG. The only neonatal ECG-referenced benchmark (MIMIC PERform) scores beat detectors; its only lag-type number is
  MorphSSF's 6.11 % octave flags (V:ctx_ppgbeats_mimic_perform).
- **No significance test between detectors on neonates** in Charlton 2022, MSPTDfast 2025 or MorphSSF 2026. MorphSSF's
  neonatal lead (94.32 vs 93.95 %) is in-sample and by its authors (V:ctx_ppgbeats_mimic_perform, V:hr1_morphssf).
- **No decomposition paper reports octave or sub-harmonic error shares, and no decomposition or dual-wavelength method
  has neonatal data** (V:prep_emd_family; catalogue g5, thin spots).
- **No learned detector has a neonatal-only result; no learned octave validator or fusion model has been tested on PPG
  pulse rate; no learned SQI is trained on rate error** (V:ml_* records; catalogue g6, thin spots).
- **No PPG study measures how often breathing near HR/k produces a rate error.** The physiological sources measure the
  coincidence, from ECG and respiration only (V:ctx_cardioresp_ratio_occurrence).
- **No standard sets a numeric pulse-rate accuracy limit** for pulse oximeters (ISO 80601-2-61:2026 §201.12.1.104
  [checked for T5]). The ECG rate-meter standards that do set limits exclude pulse-plethysmographic devices
  (V:ctx_ec13_hr_meter_tests); the English EC13 text was not read, and its numbers come from the Chinese YY 1079-2008.
- **No open neonatal PPG below 87 bpm** was found (H1M Limits), and the open neonatal sets used have essentially nothing
  above 220 bpm.

---------------------------------------------------------------------------------------------------------------

### 6. Sources

Read depth is that of the verifier (V:<item>) unless marked [checked for T5].

#### Project documents (read for this section)
- `C:/PRJ/MOW/PulseNest/docs/hr1_methods_20261116.md` (F2, Q1-Q3, Parts 2-3, Limits): sections read.
- `C:/PRJ/MOW/PulseNest/docs/hr2_methods_20261115.md` (Methods, Limits, Parts 2-3): sections read.
- `C:/PRJ/MOW/PulseNest/docs/hr3_methods_20261114.md` (reference, methods, addendum, Limits, decisions): sections read.
- `C:/PRJ/MOW/PulseNest/docs/algorithm_prior_art_index.md` (§2.5, §4-§6): sections read.
- `C:/PRJ/MOW/incunest_afe4490/incunest_afe4490_spec.md` (§3 enumerations, §5.2 range table): grep of the parts.
- `C:/PRJ/MOW/incunest_afe4490/incunest_afe4490_design_rationale.md` (filter-comparison table; §8 range provenance): grep.
- `C:/PRJ/MOW/PulseNest/pulsenest_lab_spec.md` (frame tables, `$M4` fields): grep.

#### Benchmarks and datasets
- Charlton PH et al. Detecting beats in the photoplethysmogram: benchmarking open-source algorithms. Physiol Meas
  2022;43(8):085007. doi 10.1088/1361-6579/ac826d, PMID 35853440, PMC9393905. Full text and figure 6
  (V:ctx_ppgbeats_mimic_perform).
- Charlton PH, Arguello-Prada EJ, Mant J, Kyriacou PA. The MSPTDfast photoplethysmography beat detection algorithm.
  Physiol Meas 2025;46(3):035002. doi 10.1088/1361-6579/adb89e, PMC11894679. Full text and figure 5.
- Desai S, Shi W. MorphSSF. Physiol Meas 2026;47(11):115013. doi 10.1088/1361-6579/aec110. Full text of the accepted
  manuscript (tables 17-19).
- Charlton PH. MIMIC PERform Datasets. Zenodo doi 10.5281/zenodo.6950488 (the version the project used),
  10.5281/zenodo.6807402, 10.5281/zenodo.15906524. Data file used for an independent HR recount.
- PhysioNet MIMIC-III Waveform Database 1.0 (mimic3wdb): project page, RECORDS-neonates, WFDB headers (independent sample
  of 80 neonatal record sets). Full text of the page; files read (V:ctx_mimic3wdb_neonatal_pool).
- Garde A, Karlen W, Ansermino JM, Dumont GA. Estimating respiratory and heart rates from the correntropy spectral density
  of the photoplethysmogram. PLoS One 2014;9(1):e86427. doi 10.1371/journal.pone.0086427, PMID 24466088, PMC3899260.
  Full text (V:ctx_capnobase_cross_family).
- Garde A, Karlen W, Dehkordi P, Ansermino JM, Dumont GA. Empirical mode decomposition for respiratory and heart rate
  estimation from the photoplethysmogram. Computing in Cardiology 2013;40:799-802 (cinc.org/archives/2013/pdf/0799.pdf).
  Full text.
- Cicone A, Wu H-T. Front Physiol 2017;8:701. doi 10.3389/fphys.2017.00701, PMC5615790. Full text (Table 1).
- PhysioNet/CinC Challenge 2015 records: used by the project (H1M Part 2 corrected); not separately verified.
- Not verified (catalogue g8 only): MIMIC-III-Ext-PPG (doi 10.1038/s41597-026-07335-8), WAVES
  (doi 10.1038/s41597-023-02037-x), BCH Sleep Corpus (doi 10.1093/sleep/zsaf273), NSRR CHAT/CCSHS/CFS/MESA, Kenyan
  neonatal pleth (doi 10.5061/dryad.1c59zw3vb), King 2025 NICU perfusion grid (doi 10.1038/s41372-025-02364-4),
  RR-driven PPG simulators, Alonzo 2018 HR percentiles.

#### Red + IR, decomposition and denoising
- Ricci F, Vivarelli C, Mattei E, Calcagnini G. Signal quality of reflective-mode photoplethysmograms across anatomical
  sites. Sensors 2026;26(10):2986. doi 10.3390/s26102986, PMC13210545. Full text via PMC XML (methods, Tables 5-6)
  [checked for T5].
- Longmore SK et al. A comparison of reflective photoplethysmography for detection of heart rate, blood oxygen
  saturation, and respiration rate at various anatomical locations. Sensors 2019;19(8):1874. doi 10.3390/s19081874,
  PMC6514840. Full text via PMC XML (methods, participants, results) [checked for T5].
- Hayes MJ. Artefact reduction in photoplethysmography. PhD thesis, Loughborough University, November 1998 (figshare
  9518504). OCR full text of sections 3-5 (V:prep_hayes_log_difference). Hayes MJ, Smith PR. IEEE Trans Biomed Eng
  2001;48(4):452-61, doi 10.1109/10.915711, PMID 11322533 (abstract); Appl Opt 1998;37(31):7437-46,
  doi 10.1364/ao.37.007437 (abstract).
- Clarke GWJ. Signal quality analysis in pulse oximetry: modelling and detection of motion artifact. MASc thesis,
  Carleton University 2015. Full text, Table 5.1 (V:rule_template_similarity_sqi, V:prep_masimo_dst_canceller).
- US 5,632,272 (Masimo): full text of the pulse-rate module and FST; Expired - Lifetime, 2014-05-27
  (V:prep_masimo_dst_canceller).
- US 6,631,281 B1 (Philips FAST): full description; Expired - Lifetime, 2019-06-10 (V:ctx_philips_fast_rate_path).
- US 6,002,952 A and US 6,650,917 B2 (Masimo): sections and claims; expired (V:prep_spectral_ratio_labelling).
- US 8,175,669 B2 (Nihon Kohden): description paras 100-173 and claims 1-6; Active to 2030-07-05
  (V:prep_spectral_ratio_labelling).
- US 6,564,077 B2 (Mortara / Welch Allyn): abstract, summary, ACF sections, claims; Expired - Lifetime, 2021-11-17
  (V:prep_mortara_acf_mix).
- US 7,039,538 B2 and US 7,534,212 B2 (Nellcor): full text; expired 2024-03-08 and 2026-05-08. US 8,801,622 B2 (active to
  2028-06-26): status and half-rate paragraph (V:prep_ensemble_avg).
- CN 101991410 B (Edan): Google Patents page; Active, anticipated expiration 2029-08-31, China only (V:hr1_edan).
- US 2008/0167541 A1 (GE): abandoned 2012-01-03 (V:hr3_ge_resp_notch).
- Lei R, Ling BW-K, Feng P, Chen J. Sensors 2020;20(11):3238, doi 10.3390/s20113238, PMC7309083. Full text
  (V:prep_emd_family).
- Motin MA, Karmakar CK, Palaniswami M. IEEE JBHI 2018;22(3):766-774, doi 10.1109/JBHI.2017.2679108. Abstract.
- Merino-Monge M et al. Sensors 2026;26(8):2409, doi 10.3390/s26082409, PMC13120323. Full text (review).
- Xu D et al. Sensors 2026;26(17):5587, doi 10.3390/s26175587, PMC13568033. Full text `[transfer]` (radar).
- Tang H et al. arXiv 2503.07062 (2025). Full text `[transfer]` (radar).
- Tazen M et al. IEEE Access 2023;11:46111, doi 10.1109/ACCESS.2023.3272895. Full text `[transfer]` (radar).
- Sameera JN et al. IEEE TMTT 2024;72(1):750, doi 10.1109/TMTT.2023.3324444. Full text `[transfer]` (radar).

#### Learned models
- Davies HJ, Monsen J, Mandic DP. Interpretable pre-trained transformers for heart time-series data. arXiv 2407.20775 v2.
  Full text (V:ml_ppg_pt).
- Zuo C, Zhao Y, Ye J. TAU. arXiv 2503.10733, full text. Li J et al. Peak-Detector. arXiv 2605.16452, full text.
  Vargova E, Nemcova A. Lekar a technika 2024;54(4):139-143, doi 10.14311/CTJ.2024.4.05, full text (V:ml_peakmap_net).
- Chierico P et al. Sensors 2026;26(21):6912, doi 10.3390/s26216912, PMID 43029710, PMC13766509. Full text (V:ml_pcpd).
- Belal SY et al. Physiol Meas 2001;22(2):397-412, doi 10.1088/0967-3334/22/2/311 (abstract); Artif Intell Med
  2002;24(2):149-65, doi 10.1016/s0933-3657(01)00099-9 (abstract). US 7,922,665 B2 (Nellcor): full text; Active to
  2030-02-10 (V:ml_beat_qualifier).
- Drugman T et al. IEEE Signal Process Lett 2018;25(11):1745-1749, doi 10.1109/LSP.2018.2874155 (arXiv 1903.01290), full
  text `[transfer]`. Tsanas A et al. J Acoust Soc Am 2014;135(5):2885-2901, doi 10.1121/1.4870484, full text
  `[transfer]`. Zhu T et al. EMBC 2015, doi 10.1109/EMBC.2015.7319793 (abstract); Healthc Technol Lett 2021;8(2):25-30,
  doi 10.1049/htl2.12003 (full text) (V:ml_learned_fusion).
- Schreiber H, Mueller M. ISMIR 2017, pp. 235-242, full text `[transfer]`. US 9,220,423 B2 (Covidien): Active to
  2033-10-30 (V:ml_octave_validator).
- Not verified (catalogue g6 only): end-to-end CNN regressors (TF-IG arXiv 2610.28693; Samavati 2026,
  doi 10.1049/htl2.70083), Solosenko 2022 CWT-CNN event classifier (doi 10.3389/fphys.2022.928098), PPG foundation
  models, learned denoisers, deep SQI classifiers.

#### Device studies
- Bohnhorst B, Peter CS, Poets CF. Crit Care Med 2000;28(5):1565-8, doi 10.1097/00003246-200005000-00050, PMID 10834712.
  Abstract.
- Hay WW Jr et al. J Perinatol 2002;22(5):360-6, doi 10.1038/sj.jp.7210740. Abstract and funding note.
- Dawson JA et al. Acta Paediatr 2013;102(10):955-60, doi 10.1111/apa.12329, PMID 23800004. Abstract.
- Kamlin CO et al. J Pediatr 2008;152:756-60, doi 10.1016/j.jpeds.2008.01.002. Abstract.
- Khoury R et al. J Perinatol 2021;41(4):885-890, doi 10.1038/s41372-020-00881-y, PMID 33250516. Abstract.
- Murphy MC et al. Arch Dis Child Fetal Neonatal Ed 2019;104(5):F547-F550, doi 10.1136/archdischild-2017-314366. Abstract.
- Iglesias B et al. Arch Dis Child Fetal Neonatal Ed 2018;103:F233-7, doi 10.1136/archdischild-2016-311492. Abstract.
- Goldstein MR et al. Proc ATS International Conference 2004, A50 (Masimo-hosted conference abstract, no DOI). Full
  abstract.
- Nizami S et al. Cardiovasc Eng Technol 2015;6(3):383-91, doi 10.1007/s13239-015-0229-7; Workie FA et al. Am J
  Perinatol 2005;22:357-360, doi 10.1055/s-2005-872704; Villarroel M et al. Healthc Technol Lett 2014;1:87-91,
  doi 10.1049/htl.2014.0077. Abstracts / full text (V:ctx_device_bench_neonatal_vs_ecg).
- Gehring H et al. Anesthesiology 2000;93(3A):A-584 (Masimo-hosted abstract; table read from the image); Respir Care
  2002;47(1):48-60, PMID 11749687 (abstract).
- Shah N et al. Anesthesiology 2005;103:A879; Anesth Analg 2006;102:S-148 and S-108; Anesthesiology 2006;105:A1433 and
  A242 (Masimo-hosted abstracts with tables); J Clin Anesth 2012;24(5):385-91, doi 10.1016/j.jclinane.2011.10.012
  (abstract).
- Vikne H et al. PLoS One 2025;20(6):e0326674, doi 10.1371/journal.pone.0326674, PMC12184948. Full text (Tables 7-8).
- Hyle M, Vainio P. GE Healthcare white paper JB25949XX (full text); Baker CR, McGonigle S. Medtronic white paper
  EMEA-PM-2200041, citing internal study 13-PM-0357 (full text of Table 4) (V:ctx_device_bench_adult_motion).

#### Standards
- ISO 80601-2-61:2026, the project's licensed copy `docs/ISO_80601-2-61-2026.pdf`: §201.12.1.102-104, §201.12.4.101,
  AA.2.13 and Table GG.5 read [checked for T5].
- YY 1079-2008 Electrocardiographic monitors (written with reference to the performance part of ANSI/AAMI EC13:2002):
  full text of the relevant clauses. IEC 60601-2-27:2011 preview; FDA Cardiac Monitor Guidance 1998
  (fda.gov/media/71947/download); Pstras L et al. Front Physiol 2025, doi 10.3389/fphys.2025.1638809, PMC12505149
  (V:ctx_ec13_hr_meter_tests). The English EC13 was not read.
- WHO & UNICEF 2019, Technical specifications and guidance for oxygen therapy devices, §6.5 and Table A1.11: as cited by
  SPEC §5.2 and RAT §8; not re-read for this section.

#### Neonatal physiology
- Krishnamurthi N et al. Pediatr Res 2026, doi 10.1038/s41390-026-04783-1. Full text (V:ctx_cardioresp_ratio_occurrence).
- Clark MT et al. J Appl Physiol 2012;112(5):859-867, doi 10.1152/japplphysiol.01152.2011, PMC3311658. Abstract.
- Joshi R et al. J Appl Physiol 2019;126(1):202-213, doi 10.1152/japplphysiol.00722.2018, PMID 30382810. Abstract and
  full-text table.
- Lucchini M et al. Physiol Meas 2018;39(6):064001, doi 10.1088/1361-6579/aac553, PMC6063316. Full text (its derived
  shares carry caveats; not used for numbers here).
- Gee AH, Barbieri R. PICS database, PhysioNet picsdb 1.0.0 (2017); the finder's script was re-run by the verifier.

---
