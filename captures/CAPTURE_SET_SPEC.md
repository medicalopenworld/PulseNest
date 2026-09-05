# PulseNest capture set — specification

Design for the capture collection used to **verify, calibrate and compare** the PPG algorithms
(HR1/HR2/HR3, SpO2, RSQM, HGAC). Written 2026-09-05.

This is a shopping list, not a record of what exists: §5 tracks what is already captured and what
is missing. The 108 CSVs currently in `captures/` were recorded ad hoc and only partly qualify.

> **Scope.** This document belongs to PulseNest (the validation tool), not to the library: it is
> neither `incunest_afe4490_spec.md` (normative behaviour) nor the design rationale (why the
> algorithms are as they are). Related task: `project_regression_test_captures_task`.

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

---

## 2. Requirements for every capture

### 2.1 Duration

**≥ 65 s**: 5 s of detector warmup (discarded) + **≥ 60 s of usable signal**. At 60 BPM that is
≥ 60 beats — enough for an RR dispersion figure that means something. Rationale: with ~17 beats the
standard deviation of RR is dominated by how few samples there are.

For rhythm-transition captures (§3.2), ≥ 30 s **per stretch**.

### 2.2 Ground truth

Every capture must be classifiable into one of three tiers, and the tier must be evident from the
filename:

| Tier | Source of truth | Enables |
|---|---|---|
| **T1 — simulator** | The MS100 is programmed to a known rate and SpO2 | Absolute error of HR and SpO2 |
| **T2 — reference device** | A commercial pulse oximeter recording simultaneously | Error against a clinical reference |
| **T3 — none** | Human subject with no reference | Only agreement between algorithms and dispersion |

T3 captures are still useful (they carry real waveform morphology, which no simulator reproduces)
but **cannot settle a disagreement**. Do not build a calibration on T3 alone.

### 2.3 Columns and header

Minimum `LED1_SUB` (the input HR1/HR2/HR3 consume) plus the `#` configuration header already
emitted, which records board, sample rate, NUMAV, LED currents, TIA gain and CF. Without that
header a capture cannot be replayed through an equivalent chain. `$M4` frames preferred: they carry
the analog state (V_TIA, I_PD, OT) that RSQM and HGAC need.

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
* subject identifiers: **role or code, never a full name** — these repos are public.

---

## 3. The set to capture

### 3.1 Neonatal morphology — **the gap that blocks a decision today**

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| N1 | Preterm foot, resting, good perfusion | T2/T3 | 90 s | Reference morphology: notch position and depth |
| N2 | Preterm foot, low perfusion (PI < 0.5 %) | T2/T3 | 90 s | Detector behaviour at the edge of usable signal |
| N3 | Term neonate, resting | T2/T3 | 90 s | Contrast against N1 |

Without N1–N3 the MA-versus-biquad decision and the detector choice stay unresolved: everything
measured so far comes from adults and a simulator.

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
| I3 | Ambient light, fluorescent/LED mains ripple | T1 | 65 s | 100/120 Hz interference and its aliasing |
| I4 | Motion artefact, gentle | T3 | 65 s | `project_hr_artefact_task` |
| I5 | Motion artefact, vigorous | T3 | 65 s | Detector rejection, SQI behaviour |
| I6 | Probe partially detached | T3 | 65 s | RSQM `PROBE_NOT_APPLIED`, `project_limb_detection_task` |

### 3.4 SpO2 range

| # | Condition | Tier | Duration | Purpose |
|---|---|---|---|---|
| S1 | 100 / 96 / 90 / 85 / 80 % SpO2, steady | T1 | 65 s each | Calibration curve of R → SpO2 (`spo2_a`, `spo2_b`) |
| S2 | Desaturation 96 → 85 % | T1 | 60 s | Response time; ISO 80601-2-61 §201.12 requirements |

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

* **Verification** (does it meet spec?) — T1 only, since it needs a known truth.
* **Calibration** (fitting `spo2_a`/`spo2_b`, thresholds) — T1 and T2. **Never T3.**
* **Comparison between algorithms** — any tier: a shared input is enough.
* **Regression** (does today's build match yesterday's?) — any tier, since the reference is the
  previous result and not a truth.

---

## 5. Status

| Block | Have | Missing |
|---|---|---|
| §3.1 neonatal | — | **N1, N2, N3 — all of it** |
| §3.2 rhythm | 60 BPM (simulator) | R1, R3, R4, R5 |
| §3.3 interference | phototherapy steady and on/off, ~90 s | I3, I4, I5, I6 |
| §3.4 SpO2 | 90 %, 96 % | 100 %, 85 %, 80 %, S2 |
| §3.5 hardware | RF sweeps | H2 (needs ≥ v0.85 firmware) |
| Duration | Phototherapy 94 s ✓ | Finger captures are 20 s ✗ |
| Naming | ad hoc | tier prefix absent everywhere |

Existing captures are **not** to be renamed retroactively: their names appear in the experiment
scripts and in `conversation_log.md`. The convention applies from here on.
