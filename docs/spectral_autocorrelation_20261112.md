# Autocorrelation of the HR3 spectrum along frequency, measured (2026-11-12)

Script: `experiments/spectral_autocorrelation_20261112.py`. Data: the 17 HOSPNAV sessions of
SUBJ08–11 with a reference and the two MS100 sessions (one with the 20–240 bpm sweep), 23 940 HR3
windows. Front end, references and SpO2 artefact gate: those of
`experiments/hr3_spectral_variants_20261021.py`, loaded from its file. Outputs (tables and one
figure per session) in `captures/sessions/SPECTRAL_ACF_20261112/`, not versioned. Nothing in the
library was changed and nothing is adopted.

## Question

Alex, looking at the spectrograms of SUBJ08–11 (`tools/spo2_spectra.py`: dB, top 60 dB): where the
PPG is the arterial pulse the eye sees the fundamental plus three or more harmonics over a dark
background; where it is not, other components appear. The HPS reads three bins per candidate
(k, 2k, 3k) and never looks at the darkness between the teeth. Proposal: autocorrelate the spectrum
along the frequency axis,

```
rho[d] = correlation of the spectrum with itself shifted d bins
rate   = 60 · d* · (50 Hz / 512), d* the lag of the maximum   (the spacing of the teeth)
```

and ask four things: (1) does rho show a clear ridge at f0 on clean stretches; (2) does it fall
under motion and separate better than `hr3_sqi > 0`; (3) does its rate agree with HR3; (4) is the
logarithm needed, and with which dynamic range D.

Prior art: spectral autocorrelation and the cepstrum in speech pitch detection (the power cepstrum
is the Fourier transform of the autocorrelation of the log spectrum); Datex-Ohmeda US 7,139,599,
*Cepstral domain pulse oximetry* (expired; `docs/pi_motion_prior_art_20261111.md`).

## Variants

Per HR3 window (512 samples at 50 Hz, Hann, every 0.5 s), on the band 0.49–14.94 Hz (149 bins).

| Name | Sequence correlated with itself | In the proposal |
|---|---|---|
| `lin` | linear power (cosine similarity) | yes |
| `logD` | dB above the black level, black = D dB under the window's maximum (cosine similarity) | yes |
| `logzD` | the same with the mean removed (Pearson correlation); D = 30, 40, 60 dB | yes |
| `logc6` | local contrast: dB above the median of the ±8 neighbouring bins, minus 6 dB, clipped to 0–30 dB (Pearson). `logc10`: margin 10 dB. `logc6h15`: cap 15 dB | added after the first run on SUBJ10 |

Rate: the smallest lag inside 27–263 bpm whose local maximum reaches 0.8 of the highest one,
parabolic interpolation. Quality: rho at that lag.

Comb purity (added): the fraction of the band's **linear** power inside the teeth n·f0 ± 3 bins at
the rate `logc6` found, rescaled so that a flat spectrum gives 0.

## Results

**A. The baseline is the 2026-10-21 one.** SUBJ10 gate "HR3 valid": 2.6 % published, Arms 2.05; no
gate: 81.8 %, Arms 16.25.

**B. (Question 1) With the local contrast there is a clear ridge at f0, and the rate is right.**
Windows with a reference (HR1 = HR2 within 3 %; MS100: the setting), rate within 10 % of it:

| Estimator | SUBJ08 (2342 w) | SUBJ09 (4194 w) | SUBJ11 (1446 w) | MS100 30–240 (1207 w) |
|---|---|---|---|---|
| HR3 today (HPS3, SQI > 0) | 89.5 % | 92.5 % | 90.2 % | 100 % |
| B1 (HPS2, SQI > 0) | 95.8 % | 95.8 % | 96.2 % | 100 % |
| `lin` | 98.5 % | 98.1 % | 99.7 % | 87.5 % |
| `logz40` | 96.2 % | 94.3 % | 98.8 % | 87.5 % |
| `logc6` | 99.1 % | 99.5 % | 100.0 % | 87.5 % |

`logc6` gives no double-rate and no half-rate reading in any neonate. The MS100's 87.5 % is every
plateau from 60 to 240 bpm at 100 % and the 30 bpm plateau at 0 %.

**C. (Question 2) rho does not separate motion: it says a pulse is visible, not that the signal
is clean. The comb purity does.** SpO2 gate against the ward monitor, published windows / Arms:

| Validity rule | SUBJ08 (2417 w) | SUBJ09 (2124 w) | SUBJ10 (571 w) | SUBJ11 (1238 w) |
|---|---|---|---|---|
| no gate | 99.1 % / 2.86 | 99.6 % / 3.19 | 81.8 % / 16.25 | 98.3 % / 1.44 |
| HR3 today | 52.5 % / 2.47 | 80.3 % / 2.39 | 2.6 % / 2.05 | 93.1 % / 1.23 |
| B1 | 53.5 % / 2.31 | 84.3 % / 2.40 | 2.1 % / 2.47 | 96.3 % / 1.34 |
| `logz40` rho ≥ 0.7 | 58.5 % / 3.11 | 97.6 % / 3.17 | 77.4 % / 16.22 | 96.7 % / 1.38 |
| `logc6` rho ≥ 0.7 | 59.8 % / 2.69 | 96.2 % / 2.77 | 13.8 % / 10.01 | 97.5 % / 1.35 |
| `logc6` rho ≥ 0.9 | 52.8 % / 2.08 | 81.9 % / 2.26 | 0.4 % / 7.76 | 95.7 % / 1.32 |
| rho ≥ 0.5 and purity ≥ 0.3 | 54.3 % / 2.36 | 85.9 % / 2.40 | 3.2 % / 2.36 | 95.9 % / 1.30 |
| rho ≥ 0.5 and purity ≥ 0.5 | 52.7 % / 2.23 | 80.0 % / 2.24 | 0.9 % / 2.45 | 95.6 % / 1.31 |
| rho ≥ 0.5 and purity ≥ 0.9 | 31.2 % / 1.83 | 63.3 % / 1.88 | 0 % | 17.5 % / 1.37 |

In SUBJ10 the comb is clearly there in windows whose SpO2 is 8 points low (`logc6` rho ≥ 0.8:
5.4 % published, bias −7.95): the pulse lines stand over a low-frequency mass that carries most of
the power, and R is computed from all of it. The purity matches today's gate and is graded: Arms
falls steadily as its threshold rises in SUBJ08 and SUBJ09, where `hr3_sqi` is close to binary.

**D. (Question 3) The rate agrees with HR3 where HR3 is right, and the comb is available far more
often.** Share of all probe-applied windows with a rate:

| | SUBJ08 | SUBJ09 | SUBJ10 | SUBJ11 | MS100 |
|---|---|---|---|---|---|
| HR3 today | 69.4 % | 70.6 % | 6.8 % | 88.3 % | 92.7 % |
| `logc6`, rho ≥ 0.7 | 89.2 % | 88.3 % | 25.8 % | 98.9 % | 80.0 % |
| of which right, on reference windows | 99.9 % | 100.0 % | no reference | 100.0 % | 100.0 % |

`logc6` is within 10 % of HR3 in 91.8–94.2 % of the windows where HR3 is valid in SUBJ08, SUBJ09
and SUBJ11. The rest is result F.

**E. (Question 4) The logarithm alone is not enough; the local contrast is the ingredient, and D
stops mattering.** `lin`, `logD` and `logzD` find the rate on clean windows (table B) but their rho
is useless as a quality index: the tilt of the spectrum (the low-frequency mass decaying with
frequency) correlates with itself at every small lag, so rho stays high whatever the signal
(SUBJ10 gate: 77–80 % published, Arms 16, for every threshold up to 0.7; rank AUC between consensus
and artefact windows 0.38–0.75 in SUBJ08 and SUBJ09, on only 10 and 18 artefact windows). D = 60 dB without mean removal breaks even the rate (38–63 %
right). Subtracting each bin's neighbourhood median removes the tilt, which is what the eye does
when it sees lines against a local background. Margin 6 or 10 dB and cap 15 or 30 dB give the same
rate accuracy; margin 10 dB loses availability in SUBJ10 (35 % of the windows with any estimate,
against 85 %).

**F. Today's HR3 publishes one third of the pulse rate in 4.5–6.4 % of its valid windows.**
Windows where HR3 is valid, the comb has rho ≥ 0.7 and the two differ by more than 10 %:

| | SUBJ08 | SUBJ09 | SUBJ10 | SUBJ11 |
|---|---|---|---|---|
| windows (of HR3-valid) | 278 of 4348 (6.4 %) | 234 of 5258 (4.5 %) | 37 of 193 (19.2 %) | 195 of 3342 (5.8 %) |
| HR3 median | 58.3 bpm | 57.1 bpm | 56.3 bpm | 55.2 bpm |
| comb median | 174.4 bpm | 172.3 bpm | 149.8 bpm | 166.3 bpm |

The ratio is 3.0 in SUBJ08, SUBJ09 and SUBJ11: the HPS at k = f0/3 multiplies the low-frequency
mass at f0/3 and 2·f0/3 by the fundamental itself at 3k. These windows pass the "HR3 valid" gate.
There is no reference in them (HR1 and HR2 do not agree there and the monitor's pulse rate was not
captured); the reading rests on the ratio, on the three figures inspected (SUBJ10 103205 and
103822, SUBJ11 115518), and on 55–58 bpm not being a neonatal pulse rate.

## Limits

- The pulse-rate reference is the HR1/HR2 consensus, which exists only on clean windows. Under
  motion the comb's rate was checked by eye on three sessions, not numerically.
- SUBJ10's gate rows hold 2 to 18 published windows; their Arms differences are not significant.
- The contrast and purity parameters (±8 bins, 6 dB, 30 dB, 0.8, ±3 bins) were set a priori after
  seeing SUBJ10's first run and three settings were tried; nothing was tuned or cross-validated,
  and SUBJ10 is not an independent test of them.
- 30 bpm fails by construction: the teeth are 5 bins apart and each is about 5 wide, so there is
  no darkness between them. 60 bpm and above are right. A longer window or a narrower
  neighbourhood was not tried.
- With the highest maximum instead of the first one above 0.8 of it, the MS100 reads double at
  60–120 bpm (25 % of its reference windows). The picker rule is load-bearing.
- IR channel only. SpO2 or PI computed from the teeth alone was not tested.
- numpy on recorded OT; no firmware cost measured.

## Decisions for Alex

1. Whether to take the comb detector (`logc6`) further as an HR3 candidate: mirror in the lab,
   low-rate handling, cost on the ESP32-S3.
2. Whether to study the purity as the continuous quality index for SpO2 and PI: error of both
   against purity, and PI from the teeth only (links to
   `docs/pi_artifact_robustness_20261111.md` and to the pending joint SQI analysis).
3. Today's HR3 at f0/3: independent of the two above, and it affects the gate in service.
