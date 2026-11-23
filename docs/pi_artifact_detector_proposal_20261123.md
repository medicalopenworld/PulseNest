# A separate artefact detector, and the next step of PI immunity: proposal (2026-11-23)

Proposal for Alex's decision, written before any measurement. Nothing here is implemented, and
nothing in the library, its spec or its rationale was changed. Handed over to the development
session on 2026-11-23 by the session "Señal ppg_disp en AFE4490Data".

## 1. Where we are

- **PI-METHOD-2** (lib v0.120): median of the overlapping 1 s sub-windows of a 7 s window, one per
  100 ms block (61). Burst peak ×1.29–1.69 (×1.47–2.02 before), time above +20 % 2.4–5.0 s (5.8–7.0
  before) on SUBJ08–11. Known bias: 1–1.5 % low at rest at 120–180 bpm; up to +6–10 % at 40–45 bpm.
  `spo2_pi_max` keeps reading the whole-window energy (`_pi_box`). Rationale §23.
- **What it cannot do, by construction:** ignore a burst longer than (7 − 3·1)/2 = 2 s, nor a
  real change of amplitude after the movement, nor an artefact that fills the window. The
  remaining excursion ×1.2–1.6 is made of exactly those events (`docs/pi_artifact_robustness_20261111.md`).
- **Q = PI_box / PI-METHOD-2** (`pi_burst_ratio`): named, not published, not used. Measured on
  2026-11-11: with the pulse gate on, SpO2 beyond 4 points in 2.4 % of windows with Q < 1.2 and in
  18.6 % with Q > 1.5. Blind to artefacts that fill the window (Q 1.1–1.35 there).
- **Alex's rule (2026-11-14):** a detector that does not use the pulsatile structure is
  improvable, because energy is not pulse. It is called an *indicator* and treated as provisional.

## 2. Prior art that bears on it

Already collected in the project (each row points to where it is analysed):

| What | Source | Bearing |
|---|---|---|
| PI per accepted pulse; rejected pulses do not enter; trend = 30 s trimmed mean of 25 per-pulse values, unstable periods deleted | Masimo US 8,652,060 / 11,234,655 (in force to ~2029-01); `pi_motion_prior_art_20261111.md` | The industry form of "PI from qualified pulses". A median of accepted sub-windows is a different construction |
| Baseline PI from clean signal; under motion show min(baseline, current) | Masimo US 8,280,473 family, continuations in force to 2027–2028 | **Avoid** "hold the lower of baseline and current" while those claims run |
| Motion metric = current pulse amplitude against a ~60 s history; short-term ratio to the previous pulse | Nellcor US 7,194,293 / 7,006,856 (expired) | Free. The long-baseline form of Q, which sees what the within-window Q cannot |
| Signal IQ per pulse (integrity, pulse density, harmonic ratio) | Masimo US 6,606,511 family (expired 2020) | Free. A confidence per pulse, kept apart from PI |
| Pulse qualification by shape and rate (stick model, rise/fall ratio, rate–amplitude curve) | Masimo US 6,463,311 (expired 2019) | Free; tight above 160 bpm (survey ch. 1, gap 4) |
| Changing pulse-qualification constants after N rejected pulses | Covidien US 7,922,665 claim 1 (to 2030-02-10); US 9,131,878 (to 2027-05-07) | **Avoid** adapting the detector's thresholds on rejection counts |
| Head-to-head of published PPG quality indices (13 adult ICU patients, visual labels): Karlen consecutive-pulse correlation 0.902, Sukor morphology 0.848, Orphanidou template 0.818 | Pereira 2020; `pulse_rate_methods_survey_20261123.md` ch. 1 gap 4 | The best simple index is a **correlation between consecutive pulses**, which is pulsatile structure |
| Skewness best of eight window SQIs (perfusion, kurtosis, skewness, relative power, entropy, …) | Elgendi 2016, [PMC5597264](https://pmc.ncbi.nlm.nih.gov/articles/PMC5597264/) (search result, not verified) | An energy-free shape index; Nellcor already uses the derivative's skewness |
| Movement of preterm infants quantified from the pulse-oximeter PPG (wavelet) | Zuzarte et al. 2018, [PMC6344309](https://pmc.ncbi.nlm.nih.gov/articles/PMC6344309) (search result, not verified) | The only neonatal work found that detects movement from the oximeter signal itself |
| Display under failed validation: hold then blank (Nihon Kohden 30 s, Nellcor 40 s), -?- (Philips) | maker manuals; index §4.2 | Feeds step 2 of the display values (≤ 10 s hold), not this proposal |

Not found: any published detector that scores sub-windows by periodicity at an externally given
period, or a PI taken as the median of such accepted sub-windows. Not a freedom-to-operate opinion.

## 3. Proposal A: a separate artefact detector, built on the pulsatile structure

**Idea.** Judge each 1 s sub-window of the PI window by whether it repeats itself one pulse
period later, the period coming from the families that look at the whole 6–10 s (HR3, else HR2).
It is Karlen's consecutive-pulse correlation without beat segmentation, and the same per-second
granularity PI-METHOD-2 already uses.

```
T      = 60 / hr3        (hr3 valid; else 60 / hr2 if valid; else no period → "no pulse", see below)
x      = IR, band-passed as PI's AC, decimated to 50 Hz (HR2's chain)
r_T(k) = Σ x[n]·x[n−T] / sqrt(Σ x[n]² · Σ x[n−T]²)    over the samples of sub-window k
pulse(k) = r_T(k) ≥ r_min          (r_min to be measured; 0.5–0.7 expected)
```

Outputs (internal first; published only if they earn it):

- `artefact_frac` = share of sub-windows of the PI window with `pulse(k)` false. **Sees a window
  full of artefact** (r_T low everywhere), which Q cannot.
- Q kept beside it as the **energy indicator**, in two forms to measure: within the window (today's
  definition) and against a long clean baseline (Nellcor style: current PI over the median PI of the
  accepted sub-windows of the last ~60 s), which also sees a sustained excess.

Why this and not more energy statistics: an energy test cannot tell a movement from a real change
of amplitude (the ×1.2–1.6 left today); a movement rarely repeats at the pulse period, a real
change of amplitude does.

**Limits to say up front.**

- Needs a period. When neither HR3 nor HR2 is valid there is nothing to compare against, and the
  window is "no pulse" already (the SpO2 pulse gate is closed); the detector reports "unknown",
  never "clean".
- HR3 looks at 10.24 s: during a long movement it can lock on the movement's own rhythm. HR3 on the
  raw spectrum was chosen because it does not return a valid value during motion (spec §5.4,
  load-bearing rule), so the risk is bounded but has to be measured.
- Periodic movement at the pulse rate (rocking, a ventilator near the heart rate) passes. No PPG-only
  method sees it.
- Below ~50 bpm T exceeds the sub-window: r_T then compares one second with the same phase of the
  previous beat, which still works but on part of a beat.
- Patent to check: the Covidien US 9,314,209 that may read on HR2's lag picker (survey, HR2 G4) is
  about picking a lag; r_T reads a lag already chosen. Counsel should see both together.

**Cost on the board.** Per 100 ms block, 3 running sums over 5 decimated samples per sub-window:
negligible beside HR2's sweep. One buffer of 7 s + T at 50 Hz (≤ 450 floats).

## 4. Proposal B: PI-METHOD-3, the median of the accepted sub-windows

```
PI-METHOD-3 = 2√2 · sqrt( median over { k : pulse(k) } of AC²(k) ) / mean(DC) × 100
```

- It is PI-METHOD-2 with the rejected seconds removed before the median: the prior art's stricter
  form (rationale §23, "dropping the sub-windows HR3 rejects"), now possible because the judgement
  is per sub-window and not per 10 s window.
- It ignores a burst of any length as long as enough clean seconds remain; it keeps a real change of
  amplitude (those seconds stay periodic).
- With too few accepted sub-windows (proposal to measure: accepted ones covering less than 3 s of
  the 7 s window) PI is NaN: no older value in its place (data contract, rule 4). What the display does
  then is the business of `pi_disp` (step 2 of the display values: hold ≤ 10 s with the "not current"
  mark), not of PI.
- `spo2_pi_max` keeps reading `_pi_box`; `NORM_PI` and `spo2_sqi` would read the new PI as they read
  PI-METHOD-2 today.
- Not to do (patents above): no min(baseline, current); no thresholds that change after a count of
  rejections.

## 5. How it would be measured (after Alex's yes)

Offline, extending `experiments/pi_artifact_robustness_20261111.py`, on the SUBJ08–11 corpus and the
69 isolated bursts, against the monitor reference:

1. **r_T itself:** distribution at rest (HR3 valid, quiet stretches) and in the bursts; choose r_min
   out of sample (leave one subject out). Report the share of resting seconds rejected (cost).
2. **PI-METHOD-3 against PI-METHOD-2:** bias at rest, burst peak, time above +20 %, 6 s wander; and
   on the long events (> 2 s) that PI-METHOD-2 cannot remove.
3. **Detector against SpO2 error** (table E of the 2026-11-11 report): beyond 4 points by
   `artefact_frac` band and by Q band, with and without the pulse gate; whether `artefact_frac` adds
   to the gate where Q does not (windows filled by artefact).
4. **Long-baseline Q** beside within-window Q, same table.
5. **Synthetic:** a burst longer than 2 s; a window filled by a non-periodic artefact; a periodic
   artefact at the pulse rate (to show the known blind spot); 30, 45 and 240 bpm.
6. **What is not covered:** no independent motion reference (no accelerometer, no video
   annotation yet); four neonates.

## 6. Decisions for Alex

1. **Detector basis:** periodicity at the known period (r_T) as the detector, Q only as an energy
   indicator beside it, as section 3 proposes?
2. **Measure PI-METHOD-3** (section 4) together with the detector, or the detector first?
3. **Long-baseline Q** (Nellcor style) in the same measurement, or left out?
4. **Outputs:** keep `artefact_frac` and Q internal (quality logic only) until measured, or plan a
   published field (it would be a new field of `AFE4490Data` and a minor library version)?
5. **Display:** confirm that what PI shows while too few seconds are clean belongs to step 2 of the
   display values (hold ≤ 10 s, marked), not to this work.

Nothing is tagged or released without Alex's yes.
