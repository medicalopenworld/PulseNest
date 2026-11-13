# PI under motion artefacts: robust PI and artefact ratio, measured (2026-11-11)

Script: `experiments/pi_artifact_robustness_20261111.py`. Data: the 17 HOSPNAV sessions of SUBJ08–11
with `derived/replay_lib0.108_inputot/` (current PI definition, OT input), 173 min of probe-applied
signal with a full PI window. Reference: the ward monitor (Mindray N17, VideoNest OCR), 8 s windows
as `tools/spo2_bias_analysis.py`. Nothing in the library was changed.

## Question

`PI-METHOD-1` is 2√2 · RMS(band-passed OT_IR) / mean(OT_IR) over a 6 s boxcar. A brief motion
artefact stays in the sum for exactly 6 s, so PI rises for 6 s (Alex, seen live). Proposal under
test: publish two numbers,

```
PI_box = today's PI (energy of the whole 6 s window)
PI_rob = 2√2 · sqrt(median of the mean energies of the six 1 s sub-windows) / mean(OT_IR)
Q      = PI_box / PI_rob        (about 1 at rest; large when part of the window is not pulse)
```

and check (1) that PI_rob ignores artefacts without biasing PI at rest, and (2) that Q keeps, or
improves, what PI does today for the SpO2 quality (Alex's concern: an immune PI could lose it).

## Results

**A. The replica is the library's PI.** Median |replica / library − 1| 0.06–0.14 % per subject
(p95 ≤ 0.54 %).

**B. At rest PI_rob reads slightly lower.** PI_rob / PI_box with HR3 valid: 0.986 (SUBJ08), 0.993
(SUBJ09), 0.918 (SUBJ10, moving almost all the time), 0.993 (SUBJ11).

**C. On real artefacts the median of six does much less than on the synthetic bump.** Isolated
bursts (one 1 s chunk with ≥ 9× the local median energy, alone in ±7 s; 69 in all):

| Subject | bursts | peak PI_box | peak PI_rob | time above +20 %: box / rob |
|---|---|---|---|---|
| SUBJ08 | 20 | ×2.02 | ×1.95 | 7.0 s / 5.0 s |
| SUBJ09 | 24 | ×1.81 | ×1.71 | 6.7 s / 4.2 s |
| SUBJ10 | 19 | ×1.64 | ×1.69 | 5.8 s / 2.5 s |
| SUBJ11 | 6 | ×1.47 | ×1.60 | 6.0 s / 2.8 s |

The peak is the same; only the duration shortens. A median of six only ignores a disturbance that
touches at most two of the six seconds; these neonatal events raise the energy for three seconds or
more (a movement, not a tap). The synthetic test (0.4 s bump: ×2.3 for 6.4 s against ×1.05)
describes a tap on the bench, not a baby.

**G. Variants.** Lower quantiles of the same six chunks do not lower the peak and read 4–8 % low
at rest. The median of **twelve** 1 s chunks (12 s) is the only variant that helps on every count:

| Variant (pooled range over the four subjects) | /PI_box at rest | 6 s change, median | burst peak | time above +20 % |
|---|---|---|---|---|
| PI_box (today) | 1 | 8–14 % (SUBJ10 51 %) | ×1.5–2.0 | 5.8–7.0 s |
| median of 6 × 1 s | 0.92–0.99 | 8–11 % (49 %) | ×1.6–1.95 | 2.5–5.0 s |
| 25th percentile of 6 × 1 s | 0.80–0.97 | 8–9 % (48 %) | ×1.4–2.0 | 1.9–3.8 s |
| 2nd lowest of 6 × 1 s | 0.78–0.96 | 8–9 % (48 %) | ×1.4–2.0 | 1.5–3.2 s |
| median of 12 × 1 s | 0.94–0.99 | 5–6 % (30 %) | ×1.2–1.5 | 0.3–2.1 s |

Its price is latency: a real change of perfusion takes about 6 s to show (half the chunks), not 3 s.

**D. Q follows the artefacts.** Share of time with Q > 1.5: SUBJ11 (quiet) 1.2 %, SUBJ08 6.9 %,
SUBJ09 6.6 %, SUBJ10 (moving) 28.9 %. With HR3 valid 0.5–3.5 % (SUBJ10 20 %); with HR3 not valid
6–15 % (SUBJ10 30 %).

**E. Q predicts the SpO2 error, and adds to the pulse gate.** Windows against the monitor, pooled
(Q = maximum over the window):

| | windows | beyond 4 points | Q < 1.2 | Q 1.2–1.5 | Q > 1.5 |
|---|---|---|---|---|---|
| no pulse gate | 5346 | 18.3 % | 2.4 % of 2790 | 14.1 % of 871 | 46.8 % of 1685 |
| pulse gate (library today) | 4114 | 5.4 % | 2.4 % of 2872 | 6.9 % of 662 | 18.6 % of 580 |

With the pulse gate on, a window with Q > 1.5 is still eight times as likely to be beyond 4 points
as one with Q < 1.2 (SUBJ09: 23.5 % against 1.1 %). The cost of withholding on Q > 1.5: 14 % of the
published windows, of which 81 % were good. In SUBJ10 without the pulse gate Q > 1.5 flags 427 of
467 windows (the pulse gate withholds 452).

**The SQI ramp is counter-productive today, and PI_rob alone does not fix it.** Mean SQI (ramp
0.5–2 %) in windows beyond 4 points against windows within: 0.98 against 0.90 with PI_box, 0.95
against 0.89 with PI_rob (no pulse gate); 0.90 / 0.89 and 0.84 / 0.87 with the pulse gate. Bad
windows carry the same or a higher SQI than good ones.

**F. Q does not replace `spo2_pi_max`.** PI_box > 20 % is rare (SUBJ08 4 s, SUBJ09 6 s, SUBJ10
39 s, SUBJ11 never), PI_rob is also above 20 % in 24–71 % of that time, and Q there is low (median
1.10–1.35): these are sustained events that fill the whole window, which a ratio between two
statistics of the same window cannot see.

## Conclusions

1. The 6 s rise is confirmed and is by construction.
2. The median of six 1 s sub-windows is not enough for neonatal artefacts: same peak, 2–3 s shorter.
   The median of twelve halves the excursion and the beat-to-beat wander of PI, at 6 s of latency
   and 1–2 % lower readings at rest.
3. Alex's concern holds in one place only: `spo2_pi_max` must keep reading the total energy
   (PI_box). Everywhere else today's PI does not protect SpO2: its SQI ramp rates bad windows as
   high as good ones.
4. Q is the useful new output: it separates good from bad SpO2 windows and adds to the pulse gate.
   It is blind to artefacts that fill the whole window.

## Not measured / limits

- Four neonates, one probe model, one monitor; the bursts are 69 events.
- The burst detector uses the same energy the PIs are built from; no independent motion reference
  (accelerometer, video annotation).
- Q thresholds were not optimised, nor a Q built on the 12 s median.
- What manufacturers do with PI under motion was not consulted (prior art pending).
- No decision taken; nothing changed in the library, its spec or its rationale.

## Addendum: odd numbers of sub-windows (Alex, 2026-11-11)

A median of N chunks of 1 s tolerates (N−1)/2 s of artefact when N is odd; an even N tolerates
N/2 − 1, the same as N − 1, so it adds window without adding immunity. Medians of 5, 7, 9 and 11
chunks were added to section G beside 6 and 12. In every variant only the numerator changes: the DC
stays the 6 s mean of PI-METHOD-1. Each cell: SUBJ08 / SUBJ09 / SUBJ10 / SUBJ11; bursts per subject
20 / 24 / 19 / 6.

| Variant | tolerates | /PI_box at rest (HR3 valid) | 6 s change, median [%] | burst peak, median | time above +20 %, median [s] |
|---|---|---|---|---|---|
| PI_box (today) | – | 1 / 1 / 1 / 1 | 12.2 / 13.6 / 50.5 / 8.2 | ×2.02 / 1.81 / 1.64 / 1.47 | 7.0 / 6.7 / 5.8 / 6.0 |
| median of 5 | 2 s | 0.985 / 0.993 / 0.924 / 0.991 | 11.0 / 11.3 / 53.1 / 8.6 | ×2.30 / 2.18 / 2.05 / 1.72 | 5.2 / 5.0 / 2.9 / 2.7 |
| median of 6 | 2 s | 0.986 / 0.993 / 0.918 / 0.993 | 10.3 / 10.7 / 49.3 / 7.9 | ×1.95 / 1.71 / 1.69 / 1.60 | 5.0 / 4.2 / 2.5 / 2.8 |
| median of 7 | 3 s | 0.984 / 0.990 / 0.906 / 0.991 | 9.2 / 9.1 / 45.6 / 7.2 | ×1.75 / 1.49 / 1.66 / 1.59 | 4.8 / 2.7 / 1.6 / 2.4 |
| median of 9 | 4 s | 0.985 / 0.988 / 0.905 / 0.990 | 7.6 / 7.5 / 37.5 / 5.8 | ×1.73 / 1.58 / 1.53 / 1.49 | 4.0 / 2.3 / 0.9 / 2.4 |
| median of 11 | 5 s | 0.985 / 0.986 / 0.923 / 0.989 | 6.3 / 6.4 / 32.0 / 4.9 | ×1.59 / 1.59 / 1.45 / 1.36 | 2.0 / 2.2 / 2.1 / 0.6 |
| median of 12 | 5 s | 0.985 / 0.985 / 0.936 / 0.989 | 5.9 / 6.0 / 29.5 / 4.6 | ×1.53 / 1.38 / 1.43 / 1.24 | 2.1 / 2.0 / 1.9 / 0.3 |

Reading:

- The bias at rest does not depend on N: 1–1.5 % low in SUBJ08/09/11, 6–9 % in SUBJ10.
- The 6 s wander falls steadily with N (about half at 11–12). Part of this is plain smoothing by a
  longer window, not immunity.
- The burst peak falls with N but not smoothly, and the median of 5 is worse than today's PI on the
  peak (a shorter window averages less). With 6–24 bursts per subject, differences of ×0.1–0.2
  between neighbouring N are within the noise; the trend over N is not.
- 11 and 12 are equivalent within that noise, as the tolerance argument predicts; 12 is not better
  for having one more second.
- No N removes the excursion: even 11–12 leave ×1.2–1.6, because part of these events is longer
  than 5 s or is a real change of amplitude after the movement.

## Addendum: decision and what ships (2026-11-13)

Alex chose **PI-METHOD-2 = median of the overlapping 1 s sub-windows of a 7 s window, one
sub-window per 100 ms block (61 of them)**, lib v0.120. The whole-window PI is kept internally for
`spo2_pi_max`. Why 1 s and not 2 s, why 7 s and not 9–12 s, why a step of one block and not 1 s —
with the simulated bias of the median against the pulse rate (`experiments/pi_subwindow_median_bias_20261113.py`)
and the prior art of `docs/pi_motion_prior_art_20261111.md` — is in the library's
`incunest_afe4490_design_rationale.md` §23. The row of this report nearest to what ships is
"median of 7 × 1 s" (non-overlapping, DC at 6 s); the shipped variant was added to section G of
the script (`PI-METHOD-2 (7 s, 61 x 1 s)`) and the library's own output on the corpus is checked
against it in section A2 (`--lib2-replay replay_lib0.120_inputot`); results in the conversation log
of 2026-11-13.
