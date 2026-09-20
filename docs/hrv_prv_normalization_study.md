# HRV / PRV: why RMSSD is not normalised by the RR interval

> **Status: background study, 2026-09-17. No decision taken, nothing implemented.**
> Heart rate variability is *not* part of PulseNest or of `incunest_afe4490` today, and neither
> ISO 80601-2-61 nor the WHO/UNICEF procurement specification asks for it. This note exists so the
> reasoning and the sources are not lost if the question comes back.

Acronyms used here: **HRV** = heart rate variability; **PRV** = pulse rate variability (the same
idea measured on a pulse waveform instead of an ECG); **RR** (or **NN**) = the interval between two
consecutive beats; **RMSSD** = root mean square of successive differences; **SDNN** = standard
deviation of the intervals.

## The question

RMSSD is an absolute quantity in milliseconds. Why is each successive difference not divided by the
RR interval (or by the mean of the two intervals being subtracted), so the index becomes a
percentage and stops depending on how fast the heart is beating?

## Short answer

It *is* done, and it has a name: **CVSD**, the coefficient of variation of successive differences,

    CVSD = RMSSD / meanNN

with its counterpart **CVNN = SDNN / meanNN**. Standard analysis libraries compute it (NeuroKit2
documents both). What CVSD is not, is the canonical index — and the reason is not oversight. A
linear division by RR only *half* corrects the problem, because the dependency between variability
and mean heart rate is not linear.

## 1. The premise is right: RMSSD does depend on mean heart rate

`RR = 60000 / HR` is an inverse, so the same swing in beats per minute produces a much larger swing
in milliseconds when the mean rate is slow. Sacha (Front Physiol 2013;4:306) states it directly:

> "the same changes of HR cause much higher fluctuations of R-R intervals for the slow average HR
> than for the fast one"

There is also a hard physical bound: at high rates the RR interval has no room to fluctuate widely
without going negative. Monfredi et al. (Hypertension 2014;64:1334-43) characterised the relation
quantitatively and found it to be **exponential**, affecting SDNN, RMSSD, total power and the
entropy measures alike.

## 2. Why the division by RR did not become the standard

**a) The linear correction under-corrects.** The FINCAVAS cohort study tested eight corrections —
multiplying or dividing the index by `mean_RR^x`, x from 0.5 to 16. The best was division by
**RR squared**, not by RR. Overshooting is real too:

> "Though higher orders of correction resulted in better predictive capacity, it also induced
> moderate/strong positive correlation to HR (in the case of HRVDIV-4, HRVDIV-8, and HRVDIV-16)"

So `RMSSD/RR` sits halfway: it removes part of the dependency and leaves a residue. Worse, the best
exponent depends on the population, on the physiological phase (rest vs recovery) and on the index.
A correction that has to be calibrated per context cannot be the universal default, which is why
the standard kept the raw value and left correction as an explicit, declared analysis step.

**b) Normative inertia.** The 1996 ESC/NASPE Task Force report fixed RMSSD in milliseconds. Three
decades of reference values, post-infarction prognostic thresholds and meta-analyses are expressed
in ms; changing the unit invalidates them.

*Terminology trap:* in HRV the word "normalised" is already taken. The Task Force **normalized
units (n.u.)** normalise the LF and HF spectral bands against total power, not against RR. If CVSD
is ever adopted here, it must not be called "normalised RMSSD".

**c) Physiological reading.** RMSSD in ms measures the absolute magnitude of respiratory sinus
arrhythmia — the modulation of rhythm by the breathing cycle — which is the classical correlate of
vagal tone: acetylcholine on the sinus node lengthens the interval by milliseconds. Dividing by the
mean RR mixes two distinct physiological signals, since mean rate is itself governed by the same
sympathovagal balance. Part of the effect being measured can be divided away.

**d) What is *not* the reason.** Added noise. `meanNN` is an average over N intervals and is very
stable, so normalising costs almost nothing in uncertainty. That argument does not hold up.

## 3. When normalising is the right call

Whenever groups or conditions with **different mean heart rates** are compared — which is exactly
the paediatric and neonatal case (120-180 bpm against an adult's 60-70), and any intervention that
moves the baseline rate (drug, fever, exercise, skin-to-skin care). Comparing raw RMSSD in ms
across such groups compares quantities that differ partly by arithmetic alone.

Recommended practice if it is ever implemented here: **report raw RMSSD in ms** (comparability with
the literature) **alongside CVSD**, stating the correction exponent used. Never the corrected value
on its own.

## 4. Implications for PulseNest (own analysis, not sourced)

1. **What a PPG yields is PRV, not HRV.** The peak-to-peak interval of the photoplethysmogram
   carries the variability of pulse transit time, which is itself modulated by respiration and
   blood pressure. PRV approximates HRV at rest and diverges under movement or peripheral
   vasoconstriction — precisely the conditions of a preterm infant in an incubator.

2. **Timing resolution at PRF = 500 Hz.** With a 2 ms grid and nearest-sample peak picking, the
   fiducial-point error is uniform over +/-1 ms (sigma = 0.577 ms). Two independent marks per
   interval and one shared mark between successive intervals give sigma = sqrt(6) x 0.577 =
   1.41 ms on each successive difference, and quantisation adds **in quadrature**:

       RMSSD_measured ~= sqrt(RMSSD_true^2 + 1.41^2)

   That is +1 % at RMSSD = 10 ms, +4 % at 5 ms, +11 % at 3 ms: an upward bias, negligible for
   healthy variability and material only at the low end. In practice the PPG peak is broad, so
   fiducial-point jitter from the detector will dominate over quantisation. The cure is parabolic
   interpolation of the peak, not a higher PRF.

## Sources

- Sacha J. *Why should one normalize heart rate variability with respect to average heart rate.*
  Front Physiol 2013;4:306. https://pmc.ncbi.nlm.nih.gov/articles/PMC3804770/
- Monfredi O et al. *Biophysical characterization of the underappreciated and important
  relationship between heart rate variability and heart rate.* Hypertension 2014;64:1334-43.
  https://pubmed.ncbi.nlm.nih.gov/25225208/
- *Effect of heart rate correction on pre- and post-exercise heart rate variability to predict risk
  of mortality* (FINCAVAS cohort). https://pmc.ncbi.nlm.nih.gov/articles/PMC4042064/
- *Parsimonious Correction of Heart Rate Variability for Its Dependency on Heart Rate.*
  Hypertension 2016. https://pubmed.ncbi.nlm.nih.gov/27672028/
- Task Force of the ESC and NASPE. *Heart Rate Variability: Standards of Measurement,
  Physiological Interpretation and Clinical Use.* Circulation 1996;93:1043-65 / Eur Heart J
  1996;17:354-81. https://onlinelibrary.wiley.com/doi/10.1111/j.1542-474X.1996.tb00275.x
- NeuroKit2 — HRV indices (definitions of CVNN and CVSD).
  https://neuropsychology.github.io/NeuroKit/functions/hrv.html
- *Heart Rate Variability in Preterm and Term Neonates*, Arq Bras Cardiol.
  https://www.scielo.br/j/abc/a/vCXyrhPxvzTwnxVRZcNYwbR/?format=pdf&lang=en
