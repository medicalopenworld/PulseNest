# PulseNest capture set — specification

Design for the capture collection used to **verify, calibrate and compare** the PPG algorithms
(HR1/HR2/HR3, SpO2, RSQM, HGAC). Written 2026-09-05, revised 2026-09-05 (review pass).

This is a shopping list, not a record of what exists: §5 tracks what is already captured and what
is missing. The 108 CSVs currently in `captures/` were recorded ad hoc and only partly qualify.

> **Scope.** This document belongs to PulseNest (the validation tool), not to the library: it is
> neither `incunest_afe4490_spec.md` (normative behaviour) nor the design rationale (why the
> algorithms are as they are). Related task: `project_regression_test_captures_task`.

---

## 0. One term this document leans on: **double-counting**

Counting two beats where there is one. A cardiac pulse is not a single bump: it has a **systolic
peak**, and on the way down a **dicrotic notch** (the aortic valve closing) followed by a smaller
diastolic wave. When the detector is too permissive — filter too wide, threshold too low,
refractory too short — that secondary wave also crosses the threshold and is counted as a beat, so
the reported rate doubles: a neonate at 70 BPM reads 140.

Why it is the failure mode this whole set is built around:

* **It can mask bradycardia**, the event that most needs detecting in a neonate. A real 60 BPM
  bradycardia counted twice shows as a comfortable 120 BPM and no alarm fires.
* **The refractory protects unevenly.** HR1's 0.185 s covers up to 324 BPM, but the notch arrives
  at a delay that scales with the rhythm: the slower the rhythm, the more easily it falls *outside*
  the refractory. The guard is weakest exactly in bradycardia.
* **Neonatal morphology makes it worse** — the notch is sharper and closer to the peak than in an
  adult — and every measurement so far has been on adults and a simulator. Hence §3.1.

The opposite failure, missing beats, matters too (it fakes a bradycardia), but it is easier to spot:
it shows up as intervals outside the accepted range, while a doubled rate looks perfectly plausible.

**The guard that exists today: the refractory period.** After accepting a beat, HR1 ignores any
further threshold crossing for `hr1_refractory_s` = 0.185 s (`incunest_afe4490.cpp:97`) — a blind
window, named after the cardiac refractory period, during which the myocardium cannot be
re-excited. If the notch crosses the threshold inside that window it is discarded and no double
count happens.

It is a partial guard, and the numbers say where it fails:

| | Value | |
|---|---|---|
| Refractory | 0.185 s | allows beats up to 60/0.185 = **324 BPM** |
| Binding limit | 228 ms | the interval at `hr_max_bpm` + 3 = 263 BPM; a longer refractory would reject legitimate beats |
| Unused margin | 43 ms | between the two |

The notch does **not** arrive at a fixed delay: it sits at roughly a third of systole, so ~150 ms at
200 BPM but **250–350 ms at 60 BPM**. So the fixed window guards well in tachycardia — where
double-counting is least likely anyway — and poorly in **bradycardia**, the event that most needs
detecting. Spending the 43 ms of margin would not reach 250–350 ms either: no fixed value covers
both ends of the range. That is why §3.2 asks for bradycardia captures, and why an adaptive
refractory (proportional to the estimated RR interval) is on the detector strategy list.

**A second, slower guard that the captures must also exercise: the running max.** The detection
threshold is 0.6 × `_hr1_running_max`, and that maximum decays with `hr1_running_max_tau_s` = 20 s
(`incunest_afe4490.cpp:74`). It rises instantly on any large sample but takes ~20 s to come back
down, so a **single high-amplitude artefact raises the threshold for the next ~20 s** and beats are
missed for that whole stretch. Any capture meant to exercise artefact rejection must therefore be
long enough to contain the artefact *and* the recovery — see §3.3.

---

## 1. Why this exists — what the 2026-09-04/05 experiments could not answer

Every requirement below comes from a limit hit while comparing filters and detectors offline:

| Limit hit | Requirement it produces |
|---|---|
| Finger captures are 20 s → ~17 beats after warmup. Enough to expose double-counting, thin for jitter statistics | **§2.1 duration** |
| Absolute error is only computable where the rate is known; finger captures allow comparison between algorithms but never "who is right" | **§2.2 ground truth** |
| **No neonatal capture exists.** The neonatal dicrotic notch is sharper and closer to the systolic peak — the condition that decides whether a wider filter double-counts | **§3.1** |
| The 0.185 s refractory leaves the notch unprotected in bradycardia, and no capture covers < 60 BPM | **§3.2** |
| HR1's running max starts at zero and needs seconds to converge; the first 5 s of any capture are unusable | **§2.1 warmup margin** |
| Phototherapy captures are the hard case and all three detectors fail on them (CV 12–30 %) | **§3.3** |
| A capture must be replayable through the same chain, which needs the raw channel and the configuration | **§2.3 columns** |
| A rate in the filename cannot express a *transition* or a per-beat truth, and nothing records what result a capture is supposed to produce | **§2.5 manifest, §2.6 acceptance** |

---

## 2. Requirements for every capture

### 2.1 Duration

**≥ 65 s**: 5 s of detector warmup (discarded) + **≥ 60 s of usable signal**. At 60 BPM that is
≥ 60 beats — enough for an RR dispersion figure that means something. Rationale: with ~17 beats the
standard deviation of RR is dominated by how few samples there are.

For rhythm-transition captures (§3.2), ≥ 30 s **per stretch**. For artefact captures (§3.3),
≥ 120 s, because of the 20 s running-max recovery described in §0.

### 2.2 Ground truth

Every capture must be classifiable into one of four tiers, and the tier must be recorded in the
manifest (§2.5) and echoed in the filename:

| Tier | Source of truth | Enables |
|---|---|---|
| **T0 — clinical reference** | Controlled desaturation study with arterial CO-oximetry (`SaO2`) | **The only valid basis for SpO2 calibration** — see §4 |
| **T1 — simulator** | The MS100 programmed to a known rate and SpO2 | Absolute HR error; SpO2 *regression* only, not calibration |
| **T2 — reference device** | A commercial pulse oximeter, or a simultaneous ECG, recorded alongside | Error against a clinical reference; ECG gives per-beat truth (§2.6) |
| **T3 — none** | Human subject with no reference | Only agreement between algorithms and dispersion |

T3 captures are still useful (they carry real waveform morphology, which no simulator reproduces)
but **cannot settle a disagreement**. Do not build a calibration on T3 alone.

> **The cheapest upgrade available: record ECG alongside.** A synchronised ECG turns a human capture
> from T3 into T2 *with beat-level truth*, which is what a peak detector actually needs to be scored
> (§2.6). It is the only practical way to get real truth for the two blocks where the simulator
> cannot help — neonatal morphology (§3.1) and motion artefact (§3.3, I4/I5) — because a simulator
> reproduces neither. Worth solving before capturing N1–N3.

### 2.3 Columns and configuration record

Minimum `LED1_SUB` (the input HR1/HR2/HR3 consume). `$M4` frames preferred: they carry the analog
state (V_TIA, I_PD, OT) that RSQM and HGAC need.

**The configuration must be recorded automatically, per sample — not in the header.** The `#` block
looks like a machine record but is not one: it is the free-text "Pre-capture notes" field
(`pulsenest_lab.py:9943`), filled by pressing "Read chip config", which pastes a snapshot of that
instant. The text then persists between captures, so changing RF, ILED or PRF without pressing the
button again leaves a header that confidently states the *previous* configuration. It is the least
reliable record in the whole capture, precisely because it looks like the most reliable.

The trustworthy record is the **per-sample `RF1_OHM`/`RF2_OHM` columns**, sent by the firmware since
lib v0.37 and added to the Lab Capture column list in v0.86. They cannot go stale, and they express
what no header can: a configuration that *changes during the capture*, whether by manual `$SET` or
by HGAC. `kk_20260824_153041.csv` records seven distinct RF values in one file.

Required, therefore, for any capture that is to be part of the set:

* `RF1_OHM`/`RF2_OHM` columns enabled;
* ideally the same treatment extended to the rest of the analog configuration (ILED, RG, AMBDAC,
  PRF) — the header's remaining fields are still hand-pasted and carry the same staleness risk;
* the `#` header kept as a *human note* (subject, conditions, operator), which is what the field
  was designed for, never as the machine-readable configuration.

Ranking of the sources, worth stating explicitly because it is the opposite of what intuition
suggests: **per-sample columns > the signal itself > filename > `#` header.**

### 2.4 Naming

```
<TIER>_<SUBJECT-or-SIM>_<CONDITION>_<key params>_<YYYYMMDD>_<HHMMSS>.csv
```

`T1_SIM_PHOTOTHERAPY_60BPM_96SPO2_20260905_101500.csv`

Rules that the tooling depends on:
* the rate token ends in `BPM` and the SpO2 token in `SPO2` — `hr1_detector_experiment.py` parses
  the true rate from the filename;
* the tier prefix must be the first token, so T3 captures can be excluded from error metrics
  automatically;
* subject identifiers: **role or code, never a name** (`SUBJ07`, not a person). See §2.7.

The filename is a convenience, not the source of truth. Anything a filename cannot express — a
transition, a per-segment value, a tolerance — lives in the manifest.

### 2.5 Manifest — two files, split by who knows the fact

A filename can carry one scalar. It cannot carry *"140 BPM for 30 s, then 60 BPM"*, nor a tolerance,
nor a checksum. Without a manifest, every consumer re-implements filename parsing and the
transition captures of §3.2/§3.4 are unusable automatically — which defeats the purpose of the set.

But a single manifest would copy hardware settings that already live in each capture's `#` header,
creating a second source of truth that drifts. So the manifest is **two files with opposite rules**,
joined on `file`, built by `tools/build_capture_index.py`:

| | `captures/index.csv` | `captures/truth.csv` |
|---|---|---|
| Origin | the `#` header and the file itself | a person |
| Produced by | regenerated from scratch every run | hand-edited |
| Edit by hand | **never** — edits are overwritten | always |
| Versioned in git | no (a cache) | **yes** (irreproducible) |
| Fields | `sha256`, `bytes`, `n_samples`, `duration_s`, `prf_hz`, `numav`, `iled*_ma`, `rf_led*`, `cf_led*`, `stg2_led*`, `ambdac_ua`, `spo2_a/b`, `n_columns`, `has_analog_state`, `has_config_header` | `tier`, `condition`, `subject_code`, `truth_hr_bpm`, `truth_spo2_pct`, `truth_beats`, `usable_from_s`, `consent`, `notes` |

`index.csv` is a **queryable cache**, like a database index: if it ever disagrees with a capture's
header, the header wins and the index is rebuilt. Nothing in it is authoritative, so nothing is
duplicated in the sense that matters — there is exactly one place to correct any given fact.

`truth.csv` holds only what is written nowhere else in the capture. It is small, hand-maintained,
and the only part of the set that cannot be regenerated, which is why it is the one file committed.

Ground truth that varies over time is expressed in place: `truth_hr_bpm` is either a scalar or a
JSON list of segments, `[[t0, t1, value], …]`, quoted inside the CSV cell.

**Neither the filename nor the header is a source of truth — both are hand-written.** The day the
index was first built it flagged four captures named `RF100K`/`RF250k` whose headers all read
`TIA=250K`. The first reading was "the names lie". The data says otherwise: mean `LED1` is 357 k and
369 k in the two `RF100K` files against 932 k and 914 k in the two `RF250k` ones, a ratio of **2,54
≈ 250 k/100 k**. The TIA gain scales the signal linearly, so the **filenames are right and the
headers are stale** — consistent with §2.3, since the header is pasted by hand and the filename is
typed with more attention.

Two lessons, both now built into the tooling. The configuration must come from the per-sample
columns (§2.3), and when two hand-written records disagree, the **signal itself** adjudicates.
`build_capture_index.py --check` reports the contradiction and quotes the per-sample RF where it
exists, but deliberately does not declare a winner — it says `MISMATCH`, not which one lied.

Seeding rule: when the script meets a new capture it adds an **empty** row to `truth.csv`. It never
infers a truth value from the filename; hints go to a `name_hint` column that no test reads. A guess
that looks like data is worse than a blank.

### 2.6 Acceptance criteria — what turns comparison into verification

The set as originally written enables *comparison* ("which algorithm agrees more") but not
*verification* ("does it meet spec"), because nothing states what result is acceptable. Each
condition block in §3 needs a declared tolerance, checked automatically. Starting point:

| Metric | Criterion | Source |
|---|---|---|
| HR, steady rhythm | within ± 3 BPM or ± 3 % of truth, whichever is greater | pulse-rate accuracy convention, ISO 80601-2-61 |
| HR, after a transition | settles within the above in ≤ *T* s (T to be fixed; the estimator windows are 8 s HR2 / 10.24 s HR3, so T cannot be smaller) | §3.2 R4/R5 |
| SpO2 | A<sub>rms</sub> ≤ 4 % over 70–100 % | ISO 80601-2-61 — **requires T0**, see §4 |
| Peak detection | sensitivity and positive predictive value vs. the beat annotation | needs `truth_beats` |
| Regression | bit-identical or within a declared epsilon of the previous build | any tier |

**Beat-level truth is a different thing from rate truth.** A detector can report the correct
average rate while missing beats and inventing others in equal measure. Scoring a *detector* needs
the position of each beat, not the mean rate — hence `truth_beats`, obtainable from a simultaneous
ECG (§2.2) or, for short captures, from manual annotation reviewed once and frozen.

### 2.7 Personal data — captures are health data

Subject captures are physiological measurements of identifiable people; several existing ones are
of minors. The repository is public (`github.com/medicalopenworld/PulseNest`).

* Capture files are **not** committed (`.gitignore:40` — `captures/*`), so the CSVs themselves are
  not exposed.
* But **filenames are**: `tools/hr1_detector_experiment.py:245-248` and
  `tools/hr1_filter_experiment.py:241-244` list capture paths containing full name + age, three of
  them minors. That is enough to identify a person and link them to a physiological measurement.
* Adopt coded identifiers (`SUBJ01`…) with the mapping kept **outside** the repository, and record
  consent for any capture that leaves the lab.

> ⚠️ **`truth.csv` is committed and its `file` column lists every capture name.** Committing it
> before the renaming of §2.7 is done would publish the full list of subject names and ages in one
> place — worse than the eight scattered lines in the experiment scripts. **Rename first, commit
> second.**

---

## 3. The set to capture

### 3.1 Neonatal morphology — **the gap that blocks a decision today**

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| N1 | Preterm foot, resting, good perfusion | T2 | 90 s | Reference morphology: notch position and depth |
| N2 | Preterm foot, low perfusion (PI < 0.5 %) | T2 | 90 s | Detector behaviour at the edge of usable signal |
| N3 | Term neonate, resting | T2 | 90 s | Contrast against N1 |

Without N1–N3 the MA-versus-biquad decision and the detector choice stay unresolved: everything
measured so far comes from adults and a simulator.

> ⚠️ **This block is not a logistics item.** It is a measurement on human subjects of the most
> vulnerable class, and it needs ethics-committee approval, informed parental consent, and a
> protocol agreed with the clinical site before a single capture is taken. Plan it as a study, not
> as a session with the probe. T2 (not T3) is specified deliberately: a capture of a neonate that
> cannot be used to compute error would spend that ethical cost for nothing.

### 3.2 Rhythm range — bradycardia is the untested corner

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| R1 | 40 BPM steady | T1 | 65 s | Bottom of the accepted range; where the fixed refractory stops protecting against the notch |
| R2 | 60 / 100 / 140 / 180 BPM steady | T1 | 65 s each | Coverage across the neonatal range |
| R3 | 220 BPM steady | T1 | 65 s | Neonatal tachycardia, near `hr_max_bpm` = 260 |
| R4 | Transition 140 → 60 BPM | T1 | 30 s + 30 s | Response time and overshoot of each estimator |
| R5 | Transition 60 → 140 BPM | T1 | 30 s + 30 s | The same in the other direction |

### 3.3 Interference and artefact — the regime where everything fails today

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| I1 | LED phototherapy on, steady | T1 | 90 s | The case where all three detectors give CV 12–30 % |
| I2 | Phototherapy switching on/off | T1 | 90 s | Amplitude steps — what broke TERMA's global-mean threshold |
| I3 | Mains-lit ambient (fluorescent/LED), **harmonics near PRF** | T1 | 65 s | See note below |
| I4 | Motion artefact, gentle, isolated bursts | T2/T3 | 120 s | `project_hr_artefact_task`; long enough to include the 20 s running-max recovery |
| I5 | Motion artefact, vigorous, isolated bursts | T2/T3 | 120 s | Detector rejection, SQI behaviour |
| I6 | Probe partially detached | T3 | 65 s | RSQM `PROBE_NOT_APPLIED`, `project_limb_detection_task` |

> **I3 must target the right frequency.** At PRF 500 Hz the Nyquist limit is 250 Hz, so 100/120 Hz
> mains ripple does **not** alias — it lands in band and is attenuated normally. The dangerous
> interferer is the one near **f ≈ PRF**, which folds to DC: the 5th harmonic of 100 Hz (or the 4th
> of 120 Hz) sits exactly at 500 Hz. Any lamp used for I3 must therefore be verified to emit at
> that harmonic, otherwise the capture proves nothing. See `project_antialiasing_task`.

### 3.4 SpO2 range

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| S1 | 100 / 96 / 90 / 85 / 80 / 75 / 70 % SpO2, steady | T1 | 65 s each | **Regression and linearity only** — not calibration (§4) |
| S2 | Desaturation 96 → 85 % | T1 | 60 s | Response time; ISO 80601-2-61 §201.12 requirements |
| S3 | Controlled desaturation study, 70–100 % | **T0** | per protocol | The only valid source for `spo2_a`/`spo2_b` and for the declared A<sub>rms</sub> |

The 70–75 % points were added because the accuracy of a pulse oximeter is declared over 70–100 %;
stopping at 80 % leaves the bottom of the declared range unmeasured.

### 3.5 Hardware sweep (regression, not physiology)

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| H1 | Same signal at RF 100 k / 250 k / 500 k | T1 | 65 s each | HGAC and gain-change transients |
| H2 | Same signal at PRF 500 / 1000 Hz | T1 | 65 s each | The catalogue's second rate (spec §7.4) |

H2 has a prerequisite: firmware ≥ v0.85, whose closed catalogue is what makes 1000 Hz a supported
rate rather than an accident.

---

## 4. What each capture is for

Not every capture serves every purpose, and pretending otherwise is how a calibration ends up
resting on the wrong data:

* **Verification** (does it meet spec?) — T0/T1/T2, since it needs a known truth, and only against
  the acceptance criteria of §2.6.
* **HR calibration** (thresholds, refractory, filter cutoffs) — T0/T1/T2. **Never T3.**
* **SpO2 calibration** (fitting `spo2_a`/`spo2_b`) — **T0 only.**
* **Comparison between algorithms** — any tier: a shared input is enough.
* **Regression** (does today's build match yesterday's?) — any tier, since the reference is the
  previous result and not a truth.

> **Why a simulator cannot calibrate SpO2.** An optical simulator does not reproduce the physical
> relationship between the ratio-of-ratios and arterial saturation; it emits an R that maps to a
> target SpO2 through a *calibration table specific to a manufacturer's curve*. Fitting `spo2_a`/
> `spo2_b` against it calibrates the device against the simulator, not against blood, and the error
> is invisible because both sides then agree perfectly. ISO 80601-2-61 requires the accuracy of
> SpO2 to be established by controlled desaturation against arterial CO-oximetry (or a declared
> equivalent method). The simulator's legitimate roles are functional verification and regression —
> both real, both valuable, neither of them calibration.

---

## 5. Status

| Block | Have | Missing |
|---|---|---|
| §3.1 neonatal | — | **N1, N2, N3 — all of it** (blocked on ethics approval) |
| §3.2 rhythm | 60 BPM (simulator) | R1, R3, R4, R5 |
| §3.3 interference | phototherapy steady and on/off, ~90 s | I3, I4, I5, I6 |
| §3.4 SpO2 | 90 %, 96 % | 100 %, 85 %, 80 %, 75 %, 70 %, S2, **S3 (T0)** |
| §3.5 hardware | RF sweeps | H2 (needs ≥ v0.85 firmware) |
| Duration | Phototherapy 94 s ✓ | Finger captures are 20 s ✗ |
| Naming | ad hoc | tier prefix absent everywhere |
| Manifest (§2.5) | `index.csv` + `truth.csv` built 2026-09-05 | `truth.csv` is **93 empty rows** — every tier and truth value to be filled by hand |
| Acceptance criteria (§2.6) | — | **not declared** |
| Beat annotations (§2.6) | — | no capture has one |
| Storage (§6) | local only, ignored by git | **no versioning, no checksums** |

### 5.1 What the first index run revealed (2026-09-05)

Measured, not estimated — `tools/build_capture_index.py` over the 108 CSVs:

| Finding | Count | Consequence |
|---|---|---|
| Files with a header but **no data rows** | 15 | `labcap_diag_finger_2026-04-21*` — dead weight, candidates for deletion |
| Captures with actual data | 93 | the real size of the set |
| **No `#` configuration header at all** | **46 of 93 (49 %)** | no configuration record whatsoever. Includes the phototherapy captures and the subject captures the HR1 experiments consume |
| Header present but **hand-pasted, hence unverifiable** | 47 of 93 | §2.3 — a header is evidence of what was pasted, not of what the chip was doing |
| **Per-sample `RF1_OHM` (the only automatic record)** | **2 of 93** | the rest have no trustworthy configuration at all, only hand-written claims |
| Duration ≥ 65 s (§2.1) | **1 of 93** | median duration is 20.0 s |
| Both replayable **and** ≥ 65 s | **0** | **not one existing capture meets the two minimum requirements at once** |
| Filename contradicts header | 2 | `..._RF100K_...` with `TIA=250K` — see §2.5 |
| Carry analog state (`$M4`) | 16 of 93 | the rest cannot exercise RSQM/HGAC |

The honest reading: the existing collection is a useful **archive of waveform morphology** and
nothing more. It cannot support verification or calibration as it stands, and no amount of
re-labelling fixes that — the captures are too short, and only two of 93 carry an automatic record
of the configuration they were taken with. The set of §3 has to be captured, not reconstructed.

Regression is the exception and remains viable: its reference is yesterday's result, not a truth,
so it needs a fixed input rather than a documented one.

**The prerequisite before capturing anything new** is §2.3: enable `RF1_OHM`/`RF2_OHM` in Lab
Capture and, ideally, extend automatic per-sample recording to ILED, RG, AMBDAC and PRF. Capturing
the whole of §3 with hand-pasted headers would reproduce, on brand-new data, exactly the problem
that makes the current 93 unusable.

Existing captures are **not** to be renamed retroactively for convenience: their names appear in
`tools/hr1_detector_experiment.py` and `tools/hr1_filter_experiment.py`. They **are** to be renamed
for the reason in §2.7 — the cost is eight lines across those two files, and contrary to an earlier
draft of this document the names do **not** appear in `conversation_log.md` (verified: zero
occurrences). The naming convention of §2.4 applies from here on.

---

## 6. Where the set lives

The captures are excluded from git (`.gitignore:40`), which is right for 90 MB of ad-hoc recordings
but wrong for a test set: a suite that depends on files present on exactly one machine is not
reproducible, cannot run in CI, has no guarantee of immutability, and disappears with the disk.

Decide before the set grows:

* **Curate a small core** — the captures the automated tests actually consume, not all 108. A dozen
  well-chosen files is likely a few MB.
* **Version that core** — Git LFS, a tagged release asset, or a separate data repository. Whichever
  it is, record the `sha256` in the manifest so a test can refuse to run against a modified input.
* **Keep the bulk archive** outside the repository, listed in the manifest but not required by any
  test.
* Anything derived from a subject stays under the §2.7 rules wherever it is stored.
