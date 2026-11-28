# R on the pulse harmonics vs R-METHOD-2 — seven neonates (2026-11-28)

Second run of the A/B of 2026-10-27 (`experiments/r_estimators_ab_20261027.py`, library rationale §17),
with the three neonates of the 2026-11-25 campaign added. Script: `experiments/r_harmonic_ab_20261128.py`.
Outputs (not versioned): `captures/sessions/R_HARMONIC_AB_20261128/`.

**Verdict: not confirmed by the criterion fixed beforehand, by one subject (4 of 7, 5 needed). The harmonic
R was never worse on a still neonate and improved every one of the three unseen ones.** Nothing changes in
the library; what to do with the result is Alex's decision.

## 1. The two estimators

- **REG** — R-METHOD-2, what the library ships: regression of the red derivative on the IR derivative over
  a 6 s window, both band-passed 0.5–5 Hz. It uses everything in that band.
- **HARM6 / HARM10** — R from the spectrum of the same two signals (band 0.5–15 Hz, Hann window of 6 s or
  10.24 s), taken only in ±1 bin around the first three harmonics of the pulse rate given by HR3. It has no
  value while HR3 is not valid, so it carries the pulse gate by construction.

Both go through the shipped curve (123.98 − 39.13·R) and the library's validity rule, and are paired with
the ward monitor exactly as in October: 8 s window ending at each reading, published when at least 25 % of
its samples are valid.

## 2. Criterion, fixed with Alex before measuring

Confirmed if, under the pulse gate, the harmonic R lowers Arms by at least 0.2 point in at least 5 of the 7
neonates, raises it by more than 0.2 in none of the still ones, and publishes at least 95 % of the windows
the regression publishes. SUBJ10, the motion subject, is reported apart and does not veto.

## 3. Data

| Subject | Date | Sessions | Reference windows | Source of the signals |
|---|---|---|---|---|
| SUBJ08 | 2026-09-23 | 4 | 1590 | lib 0.108 replay of the recorded OT |
| SUBJ09 | 2026-09-23 | 2 | 2125 | same |
| SUBJ10 | 2026-10-13 | 6 | 574 | same |
| SUBJ11 | 2026-10-13 | 3 | 1241 | same |
| SUBJ12 | 2026-11-25 | 5 | 2476 | the board's own capture (fw 0.32, lib v0.124b) |
| SUBJ13 | 2026-11-25 | 3 | 801 | same |
| SUBJ14 | 2026-11-25 | 2 | 1369 | same |

The new sessions need no replay: their captures carry `OT_LED1`, `OT_LED2`, `HR3` and `HR3_SQI`. Since lib
v0.123 `HR3` is no longer −1 when its SQI is 0, so their pulse gate is `HR3 > 0 and HR3_SQI > 0`.

**Check of the chain.** On the replays the Python regression reproduces the runner's R to 3·10⁻⁶ (median).
On the new sessions it is compared with the R the board published live: median difference 1–7·10⁻⁴, p99
0.7–4·10⁻². That is the precision of the recorded OT (seven significant digits), not an error of the mirror:
a replay of SUBJ11 from its recorded OT sits at 3.1·10⁻⁴ (median) and 3.7·10⁻³ (p99) from the R its board
published. Both estimators read the same recorded OT, so the comparison between them is fair.

## 4. Result under the pulse gate

| Subject | Published | REG bias | REG sd | REG Arms | HARM6 bias | HARM6 sd | HARM6 Arms | ΔArms | > 4 pt, REG → HARM6 |
|---|---|---|---|---|---|---|---|---|---|
| SUBJ08 | 1242 / 1242 | +0.94 | 2.20 | 2.42 | +1.18 | 1.97 | 2.42 | 0.00 | 7.0 → 6.5 % |
| SUBJ09 | 1706 / 1706 | −0.50 | 2.24 | 2.39 | −0.37 | 2.00 | 2.07 | **−0.32** | 7.4 → 4.4 % |
| SUBJ11 | 1152 / 1152 | −0.39 | 1.19 | 1.23 | −0.08 | 1.08 | 1.08 | −0.15 | 0.7 → 0.3 % |
| SUBJ12 | 1930 / 1902 | −3.70 | 2.80 | 4.85 | −3.19 | 2.31 | 3.97 | **−0.88** | 44.1 → 33.6 % |
| SUBJ13 | 630 / 629 | −0.57 | 2.35 | 2.47 | −0.47 | 2.03 | 2.08 | **−0.39** | 8.6 → 6.2 % |
| SUBJ14 | 745 / 739 | +1.00 | 2.76 | 2.77 | +0.38 | 1.54 | 1.56 | **−1.21** | 7.4 → 2.2 % |
| **six still, pooled** | 7405 / 7370 | −0.59 | 2.94 | 3.16 | −0.41 | 2.51 | 2.62 | −0.54 | 16.0 → 11.6 % |
| SUBJ10 (motion) | 15 / 15 | +2.00 | 0.55 | 2.05 | +0.59 | 4.52 | 4.62 | +2.57 | 0 → 20 % |

"Published" is REG / HARM6 windows. Bias is the median of ours − reference; Arms includes the bias.

**Against the criterion:** gains of 0.2 or more in 4 of 7 (SUBJ09, 12, 13, 14); SUBJ11 gains 0.15 and SUBJ08
nothing; no still neonate is worse; HARM6 publishes 99.5 % of what REG publishes. **Not confirmed: one
subject short.** HARM10 gives the same count (SUBJ13 −0.55, SUBJ14 −1.07, SUBJ12 −0.91, SUBJ09 −0.31,
SUBJ11 −0.17, SUBJ08 +0.06) and is worse on SUBJ10 (+5.63): the longer window adds nothing, as in October.

With each estimator's own intercept removed (the shipped intercept was fitted with the regression: REG
−0.59, HARM6 −0.41 over the still neonates) the count is the same, 4 of 7.

## 5. What the numbers say beyond the verdict

- **The October result repeats exactly on the old subjects** (SUBJ08 2.42 → 2.42, SUBJ09 2.39 → 2.07,
  SUBJ11 1.23 → 1.08, SUBJ10 2.05 → 4.62) and **is larger on the three unseen ones** (−0.39, −0.88, −1.21).
  The gain is not confined to the subjects the estimator was first tried on.
- **It is a gain in scatter, not in bias.** On the windows both publish, the sd falls in every still
  neonate: 2.20 → 1.97, 2.24 → 2.00, 1.19 → 1.08, 2.77 → 2.31, 2.35 → 2.03, 2.49 → 1.54.
- **It grows as the signal weakens.** The largest gain is SUBJ14, the worst-perfused subject (PI median
  0.66 %, regression r 0.82–0.91); the smallest are SUBJ11 and SUBJ08, already the cleanest. An absolute
  threshold of 0.2 point cannot be met where Arms is already 1.2: SUBJ11 improved by 12 %.
- **It does not explain SUBJ12.** Its bias moves from −3.70 to −3.19. Discarding everything outside the
  pulse harmonics leaves the 3-point offset in place, as it left the foot-finger offset in October: whatever
  causes it is locked to the heartbeat, or is not in the signal at all (reference, site).
- **SUBJ10 is 15 windows.** The harmonic R is clearly worse on them; the sample is too small to size the
  effect and large enough to say that harmonic selection is no protection against motion at the pulse rate.
- **The pulse gate is worth far more than the estimator.** Without it the regression's Arms on the new
  subjects is 6.89 (SUBJ12), 5.00 (SUBJ13) and 11.47 (SUBJ14); with it, 4.85, 2.47 and 2.77.

## 6. Limits

- The 8 s windows overlap (one reading per second): the counts are not independent samples, and no
  confidence interval is given.
- The reference is the ward monitor read by OCR, not blood.
- Old and new subjects come from different library versions for HR3 and the probe state (0.108 replay
  against v0.124b live). The R chain is the same Python code for all.
- The harmonic R was computed offline with a full FFT per 100 ms step. Its cost and its causal form in the
  library were not studied.

## 7. Options for Alex

1. **Close it as not confirmed**, as the criterion says, and leave the harmonic R out.
2. **Keep it as a candidate and take the next step**, without adopting it: add it to the offline runner
   and to the lab as a second R shown beside the shipped one, measure its cost on the ESP32-S3, and study the
   SUBJ10 windows. Adoption would still need its own decision and, since a curve belongs to its estimator, a
   re-fit of the curve.

The criterion was fixed to avoid reading tenths in favour of a preference, and it is not met. The size and
the consistency of the gain on the unseen subjects are nevertheless well above the tenths it was written
for, which is the argument for option 2.
