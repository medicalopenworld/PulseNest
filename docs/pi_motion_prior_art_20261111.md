# Perfusion index under motion: what the manufacturers publish (prior art, 2026-11-11)

Companion to `docs/pi_artifact_robustness_20261111.md` (our measurement) and
`docs/masimo_nellcor_spo2_prior_art.md` (SpO2 algorithms; its PI rows are not repeated here).
Author: Alex Cuesta with Claude. Status: literature and patent survey, no decision taken, nothing
changed in the library. Every statement is tagged **[source]** (the document says it) or
**[inferred]** (our reading). Where nobody publishes a figure the text says *not published*.

## Question

`PI-METHOD-1` is `2√2 · RMS(band-passed OT_IR 0.5–15 Hz) / mean(OT_IR)` over a 6 s boxcar. A motion
artefact raises PI for the whole window (seen live on neonates, 2026-11-11). The candidate
`PI-METHOD-2` is a 7 s window with the median of seven 1 s sub-windows, plus a ratio
`Q = PI_box / PI_rob` as an artefact flag. Before deciding: how do Masimo, Nellcor, Philips,
Nihon Kohden, Mindray, GE/Datex-Ohmeda, Nonin, Edan, Contec and the chip vendors define PI, over
what window, and what do they do with it during motion?

## Sources consulted (all on 2026-11-11)

| Manufacturer | Document | Where |
|---|---|---|
| Masimo | Radical-7 Operator's Manual LAB-5475L (Pi Settings p. 69–70, About Pi Delta p. 100–101, display range) | https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-5475l_master.pdf |
| Masimo | Rad-97 Operator's Manual LAB-9275D (Additional Settings for Pi p. 70) | https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-9275d_master.pdf |
| Masimo | Whitepapers LAB3410F (Perfusion Index), LAB4583B / LAB7698A (PVi), LAB5318B (Signal IQ) | local `docs/masimo_whitepapers/` (not in git); LAB4583B also at https://anesthesiology.queensu.ca/sites/anesthesiology/files/inline-files/LAB4583B_Technical_Bulletin_Pleth_Variability_Index.pdf |
| Masimo | US 6,334,065 *Stereo pulse oximeter* (PI definition) | https://patents.google.com/patent/US6334065B1/en |
| Masimo | US 8,280,473 *Perfusion index smoother* and continuations US 8,983,564; 10,194,847; 10,799,163; 11,006,867; 11,759,130; pending 18/166,257 | https://patents.google.com/patent/US8280473B2/en , …/US8983564B2/en , …/US11006867B2/en , …/US11759130B2/en |
| Masimo | US 8,652,060 and US 11,234,655 *Perfusion trend indicator* | https://patents.google.com/patent/US8652060B2/en , …/US11234655B2/en |
| Masimo (Willow Labs) | US 9,066,666 *Patient monitor for monitoring microcirculation* (PI definition only) | https://patents.google.com/patent/US9066666B2/en |
| Nellcor / Covidien | PM10N Operator's Manual (pulse amplitude blip bar, Interference, dynamic averaging §10.5, specifications) | https://www.lungsask.ca/sites/default/files/PM10N_Op_Manual.pdf |
| Nellcor / Covidien | PM1000N Service Manual (§3 dynamic averaging 7/20/25/40 s, §4.6 display) | http://www.frankshospitalworkshop.com/equipment/documents/ecg/service_manuals/Covidien%20Nellcor%20PM-1000N%20Patient%20Monitor%20-%20Service%20manual.pdf |
| Nellcor / Covidien | US 7,006,856 *Signal quality metrics design…* | https://patents.google.com/patent/US7006856B2/en |
| Nellcor / Covidien | US 9,211,090 (family of 7,194,293) *Selection of ensemble averaging weights…* | https://patents.google.com/patent/US9211090B2/en |
| Medtronic | White paper *Nellcor pulse oximetry performance in challenging conditions* | https://www.medtronic.com/content/dam/medtronic-wide/public/western-europe/products/patient-monitoring/pulse-oximetry/nellcor-in-difficult-conditions-white-paper.pdf |
| Philips | *FAST SpO2 algorithm* (2025-02-10; perfusion indicator p. 7–8, averaging p. 9) | https://www.documents.philips.com/assets/20250210/64a30873c01245d3bb7cb28001801c43.pdf |
| Philips | IntelliVue MX400–MX800 Instructions for Use Rel. K/J (ch. 9 SpO2: p. 193 signal quality, p. 194 averaging, p. 200 Perfusion Numeric; INOP table; defaults) | https://medaval.ie/docs/manuals/Intellivue-Manual.pdf |
| Philips | US 9,788,793 *Method and system to identify motion artifacts…* (accelerometer + SQI) | https://patents.google.com/patent/US9788793B2/en |
| Nihon Kohden | *SpO2 Monitoring Performance Digest* (2023-09; §6.2 p. 16, §6.3–6.4, table 5 p. 21) | https://sg.nihonkohden.com/sites/sg/files/2023-09/SpO2-performance-digest.pdf |
| Nihon Kohden | US 8,548,546 *Pulse oximetry and pulse oximeter* (histogram-mode SpO2) | https://patents.google.com/patent/US8548546B2/en |
| Mindray | BeneVision N22/N19/N17/N15/N12 Operator's Manual rev. 6.0 (July 2022; §12.4 display, §12.6.3, §12.6.6, specifications, prompt messages) | https://www.mindray.com/content/dam/xpace/en_us/resource-library/patient-monitoring/technical-document/continuous-patient-monitoring/H-046-016393-00-N-Series-ops-manual-Canada-6.0.pdf |
| Mindray | BeneVision N Series Advanced User Guide; ePM / iPM user guides | https://www.mindray.com/content/dam/xpace/en_gb/resources/downloads/education/education-nseries/guides/BeneVision_NSeries_Advanced_User_Guide.pdf ; https://www.mindray.com/content/dam/xpace/en_gb/resources/downloads/education/education-epm/guides/ePM_User_Guide.pdf |
| GE / Datex-Ohmeda | 3900/3900P TruTrak+ User's Manual (PIr p. 1-2, 2-8, 2-10; averaging modes 2-4) | http://www.frankshospitalworkshop.com/equipment/documents/pulse_oximeter/user_manuals/GE_3900_-_User_manual.pdf |
| GE / Datex-Ohmeda | TruSat User's Manual (Spanish edition; PIr §1, §2, troubleshooting, specifications) | https://es.vitalaire.com/sites/vitalaire_es/files/sds/2021/06/10/trusat.pdf |
| GE | White paper *Accuracy of TruSignal SpO2 technology* (PIr × 3 = IR Mod %) | https://clinicalview.gehealthcare.com/white-paper/accuracy-trusignal-spo2-technology |
| Ohmeda | EP 0807402 A1 / US 5,766,127 *Photoplethysmographic perfusion index monitoring* (1996) | https://patents.google.com/patent/EP0807402A1/en |
| Datex-Ohmeda | US 7,139,599 *Cepstral domain pulse oximetry* and EP 1611847 A1 *Validating pulse oximetry signals in the potential presence of artifact* | https://patents.google.com/patent/US7139599B2/en , https://patents.google.com/patent/EP1611847A1/en |
| Nonin | OEM III Module Specification 4518-000-10 Rev J (data formats, flags, averaging) | https://www.nonin.com/wp-content/uploads/2018/09/OEM-III-Module-Specifications.pdf |
| Nonin | *PureSAT SpO2 averaging* page; 3231 spec sheet | https://www.nonin.com/resource/puresat-spo2-averaging/ ; https://www.nonin.com/wp-content/uploads/2018/09/Spec-Sheet-3231-USB.pdf |
| Woolsthorpe (not Nonin) | US 7,184,809 *Pulse amplitude indexing method and apparatus* | https://patents.google.com/patent/US7184809B1/en |
| Edan | iM3 User Manual §8.7 (PI) | https://www.manualslib.com/manual/1608126/Edan-Im3.html?page=65 |
| Contec | *What is normal PI %* knowledge page | https://www.contecmedsystems.com/info/what-is-normal-pi-62684513.html |
| Bluetooth SIG | Pulse Oximeter Service (PLXS) 1.0.1, PAI definition | https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/PLXS_v1.0.1/out/en/index-en.html |
| TI | SLAA655 (local `docs/slaa655.pdf`); E2E thread *AFE4490 perfusion index (PI), how to calculate?* | https://e2e.ti.com/support/data-converters-group/data-converters/f/data-converters-forum/356371/afe4490-perfusion-index-pi-how-to-calculate |
| Maxim / ADI | *Guidelines for SpO2 measurement* (AN 6845); *PPG algorithms specifications* | https://www.analog.com/media/en/technical-documentation/tech-articles/guidelines-for-spo2-measurement--maxim-integrated.pdf ; https://www.analog.com/en/resources/app-notes/maxim-integrated-ppg-algorithms-specifications.html |
| Renesas | OB1203 *Pulse oximeter algorithm for SpO2, heart rate and respiration rate* | https://www.renesas.com/en/document/apn/ob1203-pulse-oximeter-algorithm-spo2-heart-rate-and-respiration-rate |
| Neonatal | Unal et al., BMC Pediatr 2016;16:164 (PMC5054614); Jegatheesan et al., BMJ Open 2017;7:e017580 (PMC5778276); Kroese et al., PI of healthy term infants during transition (PMC4799258); Reproducibility of PVi in premature infants (PMC5943392); Granelli & Östman-Smith, Acta Paediatr 2007;96:1455 | Europe PMC / PMC |

Not reachable today: the Nellcor N-600x operator's manual (expired certificate), the GE TruSat
technical reference (iFixit login), the Mindray SpO2 quick guide (image-only PDF). Nothing in
them is expected to change the conclusions.

## Per manufacturer

### Masimo (SET; Radical-7, Rad-97, Root)

1. **Definition [source].** PI = pulsatile infrared signal / non-pulsatile infrared signal × 100 %
   (LAB4583B eq. 2; LAB3410F: "percentage of the nonpulsatile signal, both … derived from the
   amount of infrared (940 nm) light absorbed"). In the patents PI = (IRmax − IRmin) / IRDC
   (US 6,334,065; US 8,280,473; US 9,066,666), i.e. **peak-to-peak of one pulse over the DC of that
   pulse**; US 8,652,060 states it per pulse: "AC is the peak amplitude minus the valley amplitude
   for a pulse, DC is the peak amplitude for that pulse". Range 0.02–20 % (whitepapers); Radical-7
   display range 0.00 to 20 (manual, Specifications); Pi low-limit alarm default 0.3, settable
   0.03–18 (manual p. 70).
2. **Window [source].** Two user settings only: Pi *Averaging Time* = **Long (default) or Short**
   (Radical-7 p. 70, Rad-97 p. 70). *The seconds behind Long and Short are not published* in either
   manual. Pi Delta uses as baseline "30 seconds of currently averaged Pi" (p. 100). SpO2 averaging
   (2–4, 4–6, 8 default, 10, 12, 14, 16 s) is a separate setting and the manuals do not say that it
   applies to Pi. In US 8,280,473 one PI calculator is pulse-by-pulse and another computes a "bulk
   PI" over "a fixed or variable interval of pleth data including more than one pulse" (no seconds
   given).
3. **During motion [source].** US 8,280,473 (and the description shared by all continuations):
   motion-induced noise "tends to push PI too high", so a **baseline PI is established during
   quality signal conditions** (inputs: the motion/distortion flag of US 6,606,511, a signal-quality
   flag, the waveform quality of US 6,334,065); when the current signal has motion-induced noise
   and the current PI is **not lower** than the baseline, **the baseline is displayed**; if the current
   PI is lower, it becomes the new baseline. The claims that are still in force (US 8,983,564,
   11,006,867, 11,759,130; Google's adjusted expiry 2027-10 to 2028-05; a continuation 18/166,257 is
   pending) recite: compute PI by two techniques, one per pulse and one over an interval with more
   than one pulse, and take **the lowest** (or an average, or "statistical analysis") as the output.
   Display: the PI bar may be "static over one or more pulses", pulse with the pulse rate, or "hold
   the last reading and optionally fade until the next reading"; a neonatal marker at about 1.25 %.
   The manual adds a separate "Low Perfusion Index" message ("signal strength is too weak", no
   threshold) and the Signal IQ confidence (per-pulse spikes; "Low Signal IQ" message). Whether Pi
   is blanked under Low SIQ is *not published*; an older manual blanks SpCO/SpMet/SpHb with dashes
   under low SIQ, and Masimo training material says a parameter "may display dashes" when SIQ is
   very low. **[inferred]** Pi stays displayed under motion, held at the pre-motion (lower) value.
4. **Patents on stabilising PI.** (a) *Perfusion index smoother* family above. (b) *Perfusion
   trend indicator* US 8,652,060 / 11,234,655 (adjusted expiry 2029-01): PI per pulse, one value
   every 1.2 s, **30 s windows of 25 values; sort, delete the 5 highest and the 5 lowest, mean of
   the remaining 15** (the summary says "median", the embodiment is this trimmed mean); **PI values
   from unstable periods (poor signal quality, distortion, noise, per US 6,606,511) are deleted
   from the window before the mean**; a minimum count of values is required (number not given);
   trend alarm on a drop of 1–5 % over 5–60 min. The trimmed-mean steps are dependent claims 7–8
   of US 11,234,655.
5. **Beat-based or window-based.** **Beat-based [source]**: per-pulse peak-to-peak PI, with a
   multi-pulse "bulk" PI as the second estimator in the smoother. Rejected or unstable pulses are
   excluded before any mean (trend patent).
6. **Neonates [source].** No Masimo document gives artefact durations. Clinical use: Granelli 2007
   (Radical SET, 10 000 newborns, single pre/post-ductal reading; p95 = 4.5 %); Unal 2016 (Radical-7,
   values written down every 10 s for 3 min, "PI values up to 8.0 while baby was crying", measurement
   repeated after a steady state; cites Granelli: PI > 4.5 "may be the result of vasodilatation due
   to child screaming and must be repeated"); Jegatheesan 2017 (Rad-7, **8 s averaging**, PI logged
   every 2 s, **median PI of a 72 s record** (IQR 42–126 s) per screen, 17.8 % of points dropped for
   low SpO2 signal quality; "a single transient measurement has limited value"); Kroese 2016 (Radical-7,
   maximum sensitivity, 2 s samples, 60 s averaging intervals, pleth confirmed "artifact free",
   PI ≤ 0.02 or ≥ 20 rejected, 97 % of points kept); PVi reproducibility study in preterms
   (PMC5943392): same-limb PI ICC 0.77–0.84, zero values discarded as poor signal, PVi absent for
   a mean of 85 s "while PI was still displayed".

### Nellcor / Covidien / Medtronic (OxiMax; N-600x, PM10N, PM100N, PM1000N)

1. **Definition [source].** The bedside monitors show **no numeric PI**: a "pulse amplitude (blip
   bar)" that "indicates pulse beat and the relative (non-normalized) pulse amplitude. As the
   detected pulse becomes stronger, more bars light with each pulse" (PM10N §2, PM1000N §4.6), and a
   non-normalised pleth "reflecting relative pulsatile strength". The specification is a "perfusion
   range 0.03 % to 20 %" and low perfusion = "detected IR pulse modulation amplitude 0.03 %–1.5 %"
   (PM10N specifications; PM1000N §2). Modulation is therefore **IR, peak-to-peak, in % of DC**
   [inferred from "pulse modulation amplitude"]. The Medtronic white paper quotes forehead pulse
   amplitudes "normally 0.5–2.0 %".
2. **Window.** *Not published* for the blip bar (it is per pulse: "with each pulse"). SpO2/PR:
   dynamic averaging from 7 s upwards.
3. **During motion [source].** The *Interference* indicator "lights when the monitoring system
   detects degraded quality in the incoming signal" (ambient light, electrical noise, patient
   movement…) and is "common … to intermittently light as the monitoring system dynamically adjusts
   the amount of data required"; dynamic averaging extends beyond 7 s under "low perfusion, signal
   artifact, ambient light, electrocautery, other interference"; above 20 s *Pulse Search*
   (values still updated every second); above 25 s *Extended Update* alarm; at 40 s (SpO2) / 50 s
   (PR) *Pulse Timeout*, SpO2 reported as 0. Nothing is said about the blip bar under motion
   [source: absent]. **[inferred]** the bar keeps showing the amplitude of whatever the algorithm
   accepts as a pulse.
4. **Patents.** US 7,194,293 / 9,211,090 (expired 2024): the motion metric is a **ratio of the
   current pulse amplitude to a long-term average pulse amplitude** (response time "perhaps a
   minute" when all pulses qualify, several times longer when most are disqualified); values
   "substantially larger than 1.0 typically indicate motion" and lower the ensemble weights; a
   short-term ratio to the previous pulse reacts when motion starts or stops; pulses are qualified
   by a neural net (amplitude, shape, frequency). US 7,006,856 (expired 2023): signal-quality
   metrics tempered by a PID filter decide whether the measured value is displayed at all;
   "pulse amplitude" is only listed as a possible indicator. **No Nellcor/Covidien patent on a
   displayed perfusion value under motion was found** (queries: perfusion index / indicator /
   percent modulation × display × motion × Covidien / Nellcor).
5. **Beat-based [source]**: every published Nellcor metric is per qualified pulse.
6. **Neonates.** The white paper names "the involuntary movement of a neonate" as a motion case
   and reports motion studies in adults only; Louie 2018 defines low perfusion as Masimo PI < 2 % on
   the non-moving hand. No neonatal PI data.

### Philips (FAST SpO2; IntelliVue)

1. **Definition [source].** "The perfusion indicator value gives a value for the pulsatile
   portion of the measured signal (AC) caused by the pulsating arterial blood flow in relation to
   the non-pulsatile portion of this signal (DC)" (FAST doc p. 7); "numerical value for the
   pulsatile portion of the measured signal caused by arterial pulsation" (IFU p. 191). Wavelength
   not stated; "Philips FAST SpO2 uses a patented method to compensate for [saturation] to make the
   perfusion indicator value independent of actual saturation" (p. 8; the patent was not
   identified). Typical values: adults 0.3–10, **neonates 0.3–5**; > 1 optimal, 0.3–1 acceptable,
   < 0.3 marginal, reposition (IFU p. 200). Peak-to-peak vs RMS: *not published*.
2. **Window [source].** The SpO2 *Average* setting (5, 10 or 20 s; **default 10 s in Adult, Pedi and
   Neo profiles**) is "the time over which the SpO2 value, pulse rate **and perfusion** are averaged
   before displaying" (FAST doc p. 9; IFU p. 194 and defaults table). "Use slow averaging where you
   expect the artifact content to be relatively high."
3. **During motion [source].** INOP *NoisySignal* ("excessive patient movement or electrical
   interference is causing irregular pulse patterns"): **numeric replaced by -?-**, which covers
   Perf (the *Searching* INOP says the monitor "is analyzing the patient signal to derive Pulse,
   SpO2 and Perf values"). *Extd.Update* and *Poor Signal* keep the numeric with a question mark.
   A separate *signal quality indicator* (filled triangle) exists for FAST SpO2, and a *Perfusion
   Change Indicator* shows the change relative to a user-set reference. FAST works in the frequency
   domain (FFT; fundamental and harmonics; "the ability to reject artifacts this way is particularly
   important … with low perfusion and/or patient movement").
4. **Patents.** US 9,788,793 (active): accelerometer on the probe, measurements labelled with/without
   motion per beat or per second, SQI threshold raised by motion strength (correlated vs
   uncorrelated with the PPG), low-SQI measurements discarded or down-weighted, displayed values =
   average of recent motion-free measurements, alarms suspended for a 10 s motion window. **It does
   not mention PI.** No Philips patent on the perfusion indicator itself was found.
5. **Beat-based or window-based.** **[inferred] window-based**: Perf shares the 5/10/20 s averaging
   window and the FFT frame of FAST; the pulse rate "is no longer" tied to detecting each pulse (IFU
   p. 193).
6. **Neonates [source].** Typical neonatal Perf 0.3–5; adapter cable outside the incubator;
   nothing on artefact duration.

### Nihon Kohden (NPi algorithm; OLV, BSM/Life Scope)

1. **Definition [source].** "The percentage of pulsatile signal in the entire transmitted infrared
   radiation (IR) signal … called the Pulse-amplitude Index (PI)" (digest §6.2 p. 16). Detection
   limit PI 0.02 % for a 10 mm finger, extended to about 0.01 % in MAX sensitivity (§6.3); "an
   amplitude of about 10 mm in the ×1 sensitivity setting means a PI of 1 %". Display range: *not
   published* in the digest.
2. **Window.** *Not published.* SpO2 response setting fast/normal/slow = 4/8/16 s (§6.4), tested at
   140 bpm "equivalent to a typical neonatal heart rate".
3. **During motion [source].** NPi removes artefact by **narrow-band filtering around the
   fundamental found by frequency analysis**, computes the amplitude ratio φ per beat by regression,
   and applies "a weighted moving average according to the degree of variation in the φ obtained
   every beat" (§7.1). Messages (table 5, p. 21): *WEAK PULSE* ("PI is very small", SpO2 still
   shown); *LOW QUALITY SIGNAL* ("pulse wave is unstable and signal quality is low … when the quality
   is too low to obtain SpO2 value, **the measured value remains unchanged for 30 seconds and is
   displayed as '---'**"); *CANNOT DETECT PULSE* ("too much noise due to body movement", '---').
   What PI shows during those messages is *not published*.
4. **Patents.** US 8,548,546 (expired 2025): five wavelengths, 0.2 s regression slopes, correlation
   product ≥ 0.9 to keep a segment, 5 s histogram of SaO2, mode as output; **no PI**. No Nihon Kohden
   patent on PI under motion was found.
5. **Beat-based [source]** for φ (per beat, regression); PI method *not published*.
6. **Neonates.** Accuracy validation in 19 NICU patients (TL-535U); NPi "especially effective …
   restless patients … neonatal patients presenting with respiratory variation"; no PI data.

### Mindray (BeneVision N series, ePM, iPM)

1. **Definition [source].** N-series manual rev. 6.0 §12.4: "Perfusion indicator: the pulsatile
   portion of the measured signal caused by arterial pulsation" and "Perfusion index (PI): gives the
   numerical value for the pulsatile portion … an indicator of the pulsatile strength. You can also
   use it to assess the SpO2 signal strength", followed by the note "**PI is displayed for Masimo
   SpO2**" (that manual version; with the Masimo module the PI range is 0.02–20 %). Mindray's own
   module: PI 0.05–20 % (see `docs/ppg_neonatal_manufacturer_references.md`). Thresholds in the
   N-series advanced guide and ePM/iPM guides: > 1.0 optimal, 0.3–1.0 acceptable, < 0.3 low perfusion
   (red), reposition. **Caution for our reference monitor:** the ward's N17 carries a Nellcor OxiMax
   module (memory, 2026-10-27); which module computes the PI the VideoNest OCR reads, and with what
   definition, is *not published* and should be checked on the unit.
2. **Window.** *Not published* for PI. Masimo-module averaging 2–4 … 16 s (§12.6.6); Mindray-module
   sensitivity High/Medium/Low (seconds *not published* in this manual).
3. **During motion.** Prompts *SpO2 Searching Pulse* and *SpO2 Low Perfusion* ("sensor is not
   properly placed or the patient's perfusion index is too low"). Nothing about PI under motion
   [source: absent].
4. **Patents.** None found (queries: Shenzhen Mindray × perfusion index × motion/interference).
5. **Beat- or window-based.** *Not published.*
6. **Neonates.** Nothing beyond the accuracy tables already in `docs/ppg_neonatal_manufacturer_references.md`.

### GE / Datex-Ohmeda (TruSignal; TruSat, 3900, S/5)

1. **Definition [source].** "PIr pulsatile value is a measure of the relative size of [the pulsatile]
   portion of the signal" and "a numeric representation of the relative height of the waveform"
   (3900 manual p. 1-4, 2-8); "PIr is a relative value that varies from patient to patient"
   (p. 1-2). TruSat: range **0.01–9.99, resolution 0.01**, values updated every 1 s ± 0.25 s
   (specifications). GE white paper footnote: **PIr × 3 = IR Mod %**, so PIr is an IR modulation
   on its own scale. Peak-to-peak vs RMS: *not published*; the 1996 Ohmeda patent (below) uses a
   summed path-length change.
2. **Window [source].** SpO2/PR averaging modes Short 3 s, Medium 6 s, Long/TruTrak+ 12 s (3900
   p. 2-4, 2-10); the PIr window is *not published*.
3. **During motion [source].** TruSat troubleshooting: "a series of dashes is shown for the
   measurement" under "low signal quality due to sensor disconnection, misplacement, low perfusion
   or interference"; the pulse-strength bar (10 segments) shows "low pulse strength" when only the
   four lowest segments oscillate. 3900: CHECK SENSOR SITE when the pleth height becomes too small.
   PIr during motion: *not published*.
4. **Patents.** EP 0807402 / US 5,766,127 (Ohmeda 1996, withdrawn/expired): PI = sum of per-sample
   normalised intensity changes (both wavelengths, weighted by extinction coefficients) over a half
   cardiac cycle, or **the max–min of a 2 s window (61 samples at 30 Hz) recomputed every 1 s**; no
   index over any period in which gain or LED drive changed; results "should generally be smoothed
   over time" (method not given). US 7,139,599 / EP 1611847 (Datex-Ohmeda 2002/2004, expired /
   withdrawn): time-domain PI per pulse (sum of normalised deltas over the rising half,
   PI = (Snda_red·0.0563 + Snda_IR·0.3103)·scale) and a **spectral PI from the amplitudes of the
   fundamental and harmonic peaks identified by the cepstrum**, "less susceptible to corruption by
   motion artifacts" because the motion peaks are ignored.
5. **Beat- or window-based.** Patents: both (per half-cycle, 2 s window, spectral). Product:
   *not published*.
6. **Neonates.** None.

### Nonin (PureSAT; OEM III, Xpod, 3230/3231)

1. **Definition [source].** The OEM III emits an 8-bit "plethysmographic pulse amplitude" and
   perfusion **flags**, not a PI numeric: LPRF/MPRF "Low / Marginal Perfusion: amplitude
   representation of low / medium signal quality (holds for entire duration)" and RPRF/YPRF/GPRF
   red/yellow/green perfusion "(occurs only during pulse)"; minimum 0.3 % modulation for accurate
   operation. Newer sensors (3231 spec sheet) output a "pulse amplitude index"; the Bluetooth PLX
   profile defines PAI as "a percentage indicator indicating the perfusion level". Formula *not
   published*.
2. **Window [source].** SpO2/PR: 4-beat (standard) or 8-beat (extended) exponential average,
   latency 2 beats; PureSAT "pulse-by-pulse averaging … responds in 3 seconds or less at ≥ 60 BPM".
   PAI window *not published*.
3. **During motion [source].** Flags ARTF ("a detected pulse beat didn't match the current pulse
   interval"), OOT ("absence of consecutive good pulse signals"); HR/SpO2 fields are "4-beat
   average values not including display holds"; missing data coded 511/127. "This device has motion
   tolerant software that minimizes the likelihood of motion artifact being misinterpreted as good
   pulse quality."
4. **Patents.** US 7,184,809 (Woolsthorpe, not Nonin; expired 2025): IR amplitude relative to the
   first minimum, normalised to DC, per pulse ("the highest available amplitude per pulse"), used to
   index the SpO2 calibration; no motion handling.
5. **Beat-based [source]** throughout.
6. **Neonates.** Accuracy tables only.

### Edan, Contec

- **Edan iM3 §8.7 [source]:** PI "ranging from 0 to 10 … when PI is below 2, it indicates the low
  perfusion and the poor signal quality", reposition. Formula, window, motion: *not published*.
- **Contec [source]:** "normal PI ranges from 0.02 % to 20 %". Nothing else published.

### Reference chips and application notes

- **TI SLAA655 [source]:** R = (ACrms/DC)_red / (ACrms/DC)_IR; the AC/DC ratio is called the
  "perfusion index %"; no window, no motion handling. TI E2E (TI staff): PI = AC/DC × 100 (channel
  and AC measure unspecified).
- **Maxim / ADI [source]:** AN 6845: "the ratio of the AC signal to the DC level is called the
  perfusion index"; the PPG algorithm specification requires PI ≥ 0.2 % for SpO2 and "> 30 s of
  continuous RED/IR PPG signal with 'Low PI', 'Low SNR' and 'Motion' flags set off". Window *not
  published*.
- **Renesas OB1203 [source]:** reflective PI "estimated from the infrared signal RMS or average
  deviation and the mean DC count level", displayed "in equivalent peak-to-peak percentage of DC";
  a zero-order Kalman filter removes outliers from SpO2/HR; "a lower bound should be set on the
  perfusion index below which SpO2 values are not reported". This is the only published vendor
  method that, like ours, derives PI from an RMS-type statistic of a window.

## Comparative table

| Vendor | PI definition | Channel / AC measure | Range shown | Window / averaging | Under motion or bad signal | Beat- or window-based |
|---|---|---|---|---|---|---|
| Masimo | pulsatile / non-pulsatile × 100 | IR; peak − valley of a pulse over its DC (patents) | 0.02–20 (display 0.00–20) | *Long* (default) / *Short*, seconds not published; Pi Delta baseline 30 s; trend: 30 s trimmed mean of 25 per-pulse values | baseline PI from clean pulses; under motion display min(baseline, current) (patents, in force); unstable-period PI deleted from windows; separate Signal IQ; "Low Perfusion Index" message | beat-based (+ multi-pulse "bulk" estimator) |
| Nellcor | no numeric; blip bar = relative non-normalised pulse amplitude; spec "perfusion 0.03–20 %" = IR modulation | IR, modulation % | bar only | per pulse (bar); SpO2 7 → 40 s dynamic | Interference indicator; Pulse Search > 20 s; Pulse Timeout 40 s; bar behaviour not published | beat-based (qualified pulses) |
| Philips | AC / DC of the measured signal, saturation-compensated | wavelength and AC measure not published | adults 0.3–10, neonates 0.3–5 | shares the SpO2 *Average* 5/10/20 s, default 10 s (Neo too) | NoisySignal / Interference INOP: Perf replaced by **-?-**; Poor Signal / Low Perf: value with "?"; signal-quality triangle; Perfusion Change indicator | window-based (FFT) [inferred] |
| Nihon Kohden | % of pulsatile in total transmitted IR ("Pulse-amplitude Index") | IR | limit 0.02 % (0.01 % MAX) | not published; SpO2 4/8/16 s | WEAK PULSE (value kept); LOW QUALITY SIGNAL: value held 30 s then "---"; CANNOT DETECT PULSE: "---" | per-beat φ; PI not published |
| Mindray | numerical value of the pulsatile portion; "assess the SpO2 signal strength" | not published | 0.05–20 (Mindray), 0.02–20 (Masimo module) | not published | Low Perfusion / Searching Pulse prompts; nothing on PI | not published |
| GE / Datex-Ohmeda | PIr "relative size of the pulsatile portion"; PIr × 3 = IR Mod % | IR (via Mod %) | 0.01–9.99 | 1 s update; SpO2 3/6/12 s; PIr window not published; 1996 patent: 2 s max–min every 1 s | dashes under low signal quality / interference; spectral PI from cepstral peaks (patent, expired) | per half-cycle or 2 s window (patents); product not published |
| Nonin | flags (low/marginal/red/yellow/green perfusion) + 8-bit pulse amplitude; PAI on newer devices | not published; ≥ 0.3 % modulation | — | 4-/8-beat exponential (SpO2/PR) | ARTF, OOT flags; "display holds" excluded from averaged values | beat-based |
| Edan | 0–10 scale; < 2 = low perfusion | not published | 0–10 | not published | not published | not published |
| TI / Maxim / Renesas | AC/DC × 100; Renesas from IR RMS → p-p equivalent | IR | — | not published; Maxim needs 30 s clean signal | Maxim: Low PI / Low SNR / Motion flags gate SpO2; Renesas: PI lower bound gates SpO2 | window-based (Renesas) |
| **PulseNest today** | 2√2·RMS(BP 0.5–15 Hz) / mean | IR; RMS → p-p equivalent | 0–20 (`spo2_pi_max`) | 6 s boxcar | rises for 6 s after any artefact; SQI ramp 0.5–2 % | window-based |

## Lessons for PulseNest (PI-METHOD-2 and Q)

1. **The industry PI is per accepted beat, and rejected beats do not enter it.** Masimo computes
   PI pulse by pulse and, for trends, deletes the values of unstable periods before a 30 s trimmed
   mean; Nellcor's amplitude bar and motion metric are per qualified pulse; Nonin's values exclude
   "display holds". Our window-RMS integrates artefact energy for the whole window by construction.
   A median of 1 s sub-windows is a surrogate for "the median of per-beat PI over the window" that
   does not need beat segmentation (at 120–180 bpm a 1 s chunk holds 2–3 beats). The 7 s / median of 7
   proposal is therefore in the spirit of the prior art; the stricter version would be to drop the
   chunks where HR3 (or the pulse gate) rejects the signal, as Masimo drops unstable pulses, and take
   the median of the rest.
2. **Artefact only raises PI, so the robust statistic is one-sided.** Masimo's smoother holds the
   pre-motion baseline and shows min(baseline, current); its trend uses a trimmed mean that cuts the
   five highest of 25. Our measurement found that lower quantiles of six chunks read 4–8 % low at
   rest; Masimo accepts a low-side bias by design. Two consequences: (a) a lower quantile (or a
   median over an odd N) is the right family, a plain mean is not; (b) the *display* value may
   legitimately hold the last clean value during a flagged artefact (as Masimo, and as Nihon Kohden
   holds SpO2 for 30 s), which removes the 6 s rise that Alex saw without changing the estimator.
   Patent note, not legal advice: the claims in force (US 8,983,564 / 11,006,867 / 11,759,130, until
   2027–2028) cover "two PI techniques, one per pulse and one over several pulses, output the
   lowest"; a median of N equal sub-windows of one technique is a different construction, but the
   "hold the baseline under a motion flag" idea is the subject of that family's description.
3. **Published PI windows are longer than ours.** Philips averages Perf with the SpO2 window, 10 s
   by default also in neonates (5–20 s); Masimo trends PI over 30 s and offers Long/Short without
   numbers; GE's 1996 patent used 2 s updated every 1 s. Nobody publishes 6 s. Our data said that the
   median of 12 halves the excursion at 6 s of latency; a 10–12 s median would sit inside the
   Philips range and is defensible as the *display* PI, while `spo2_pi_max` and the SQI keep reading
   the shorter window (lesson 5). The decision between 7 s and 10–12 s is a latency choice that the
   prior art does not settle.
4. **Q has no published equivalent as an output, but its ingredients are the industry's motion
   metric.** Nellcor's motion detector is the ratio of the current pulse amplitude to a long-term
   (about 1 min) average amplitude, with a short-term ratio to the previous pulse for onset; Masimo
   selects between two PI estimators; Philips, GE and Nihon Kohden replace the numeric by -?- or
   "---" rather than publish a ratio. So Q belongs **inside** the quality logic (an input to SQI and to
   the pulse gate), not on the display; and a Q built against a *long-term* clean baseline (Nellcor
   style) is worth measuring beside the within-window Q, because the within-window Q is blind to
   artefacts that fill the whole window (our result F).
5. **Nobody shows an inflated PI silently, and nobody lets the quality index be a perfusion
   number.** Philips blanks Perf under NoisySignal; Nihon Kohden and GE show dashes; Masimo holds
   the lower value and keeps a separate confidence (Signal IQ). This supports the 27-oct proposal
   (SQI = confidence, PI = perfusion) and says what to do with PI when the pulse gate is closed: hold
   the last valid value, with a mark, for a bounded time (Nihon Kohden: 30 s), then blank. It also
   confirms keeping `spo2_pi_max` on the total window energy (PI_box), since the limit guards against
   sustained non-pulse energy, which the robust PI is designed to ignore.
6. **Neonatal evidence is thin and supports repetition, not a window length.** Crying drives PI to
   8 (Unal 2016), the screening literature repeats the reading after a steady state (Granelli,
   Unal), Jegatheesan takes the median of a 72 s record with 18 % of points dropped for low Signal
   IQ, Kroese rejects PI ≤ 0.02 or ≥ 20 and checks the pleth by eye. No study reports artefact
   durations; our 69 bursts (events of 3 s or more, peak ×1.5–2.0) are the only such numbers we have.
   Typical neonatal Perf 0.3–5 (Philips) and the Granelli percentiles agree with
   `docs/pi_reference_ranges_by_age.md`.

## Not found (explicitly not published)

- The seconds behind Masimo's Pi *Long* / *Short* averaging, and whether the SpO2 averaging time or
  FastSat affects Pi.
- Whether any vendor computes PI as RMS rather than peak-to-peak (only Renesas says RMS, converted
  to a peak-to-peak equivalent).
- Any manual stating what the PI numeric shows while a motion / noisy-signal condition is flagged,
  except Philips (Perf replaced by -?-) and, for SpO2 rather than PI, Nihon Kohden (held 30 s, then
  "---") and GE (dashes).
- A median of sub-windows, or a percentile of per-beat PI, in any claim: the closest are Masimo's
  trimmed mean of 25 per-pulse values over 30 s (dependent claims of US 11,234,655) and Masimo's
  "lowest of two estimators" (independent claims of the smoother continuations).
- Any Nellcor/Covidien, Philips, Nihon Kohden or Mindray patent on the displayed perfusion value
  under motion.
- Typical neonatal motion-artefact durations or a recommended PI averaging for neonates.
- The Philips patent behind the saturation-independent perfusion indicator.
- Which SpO2 module produces the PI numeric on the ward's Mindray N17 and how it is defined.
