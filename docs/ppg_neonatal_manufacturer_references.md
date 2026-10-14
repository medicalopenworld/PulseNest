# Official documentation of PPG system manufacturers

Sections of manuals, IFUs and validation protocols that refer to measurement in neonates.
Compiled for the PulseNest project (AFE4490 / IncuNest). First version 24 August 2026 (HTML + PDF);
converted to Markdown and extended with section 0 on 13 October 2026.

> **Conclusion.** Every manufacturer declares **±3 % (A<sub>rms</sub>) in neonates versus ±2 % in
> adults**, and three of them (Masimo, Mindray, Philips/Nellcor) state explicitly that the extra point is
> a margin *added by hand* for fetal haemoglobin, not a measured result. Only Mindray, Masimo and
> Medtronic publish clinical validation on real neonates; Nihon Kohden and Nonin extrapolate from induced
> hypoxia in adults.
>
> The silicon vendors (TI, Analog Devices/Maxim) publish **nothing** specific to neonates: the AFE4490
> has no neonatal guidance.

## 0. Market overview: manufacturers and main models

Minimal list of hospital pulse oximetry manufacturers (13 October 2026). It is worth separating who
**owns the SpO2 technology** (algorithm, calibration curve, validated sensors) from who **builds
monitors with licensed technology**: almost the whole hospital market runs on Masimo or Nellcor.

### SpO2 technology owners

| # | Manufacturer | SpO2 technology | Monitors / main models | Neonatal sensors | Notes |
|---|---|---|---|---|---|
| 1 | **Masimo** | SET (Signal Extraction Technology), rainbow | Radical-7, Rad-97, Rad-8, Rad-G, Root platform | RD SET Neo / NeoPt, LNCS | NICU reference, above all in the US. Own neonatal validation (§1). |
| 2 | **Medtronic (Covidien / Nellcor)** | OxiMax | Nellcor PM1000N (bedside), PM100N (portable), N-600x (legacy) | MAXN, SoftCare SC-NEO / SC-PR | The other major NICU reference. Own neonatal validation (§2). |
| 3 | **Nihon Kohden** | Proprietary (BluPRO) | Life Scope G9, G7, BSM series; OLV-3100 pulse oximeter | TL-271T / 274T, TL-260T | Very strong in Japan and Asia. No neonatal study (§5). |
| 4 | **Philips** | FAST-SpO2 (Fourier Artifact Suppression Technology) | IntelliVue MX750 / MX850, MX500, X3 series | Reuses the Nellcor range (MAX-N, SC-NEO…) and offers a Masimo module | The algorithm changes with patient category (§3). |
| 5 | **GE HealthCare** | TruSignal (lineage Biox → Ohmeda → Datex-Ohmeda) | CARESCAPE B650, B850, ONE | AllFit, Sensitive | Masimo and Nellcor options. Most detailed neonatal protocol (§6). |
| 6 | **Mindray** | Proprietary (uSpO2) | BeneVision N12 / N17 / N22, ePM, uMEC | 518B, 520N | Volume leader worldwide and in resource-limited hospitals. Best published neonatal validation (§4). Masimo and Nellcor options. |
| 7 | **Nonin** | PureSAT | 7500 series, Avant, Onyx, WristOx; OEM III / Xpod modules | 8001J Flex, 6000N / 7000N | Oriented to compact devices and OEM modules; inventor of the fingertip pulse oximeter. Smaller hospital footprint, but proprietary technology and relevant in the WHO-UNICEF context (§7). |

### Monitor manufacturers with licensed SpO2

| # | Manufacturer | Monitors | SpO2 | Notes |
|---|---|---|---|---|
| 8 | **Dräger** | Infinity Acute Care (M540), Vista 120 | Masimo SET or Nellcor | Essential in European neonatology for incubators and ventilators, not for its pulse oximetry. |

If the list had to grow to ten: **Edan** (iM series, H100B; low-cost proprietary technology) and
**Spacelabs** (Xprezzon, Qube; licensed). **Konica Minolta** (Pulsox) has historical merit but is marginal
today.

**For IncuNest** the references to follow are Masimo, Nellcor and Nihon Kohden: they are the three that
publish their own curves and neonatal accuracy data. Mindray and Edan are of interest as cost
comparables.

## 1. Masimo

### RD SET Sensors — Directions for Use (LAB-9028A)

Source: [techdocs.masimo.com/…/lab-9028a.pdf](https://techdocs.masimo.com/contentassets/572bbdb5f9ef4a73a0f78e7e4ac6f653/lab-9028a.pdf) — the most useful document of all.

- **"Site Selection" section**, by weight: `RD SET Neo` < 3 kg → foot; alternative palm/back of the hand.
  `RD SET NeoPt` (preterm) < 1 kg → foot.
- **"For NEONATES (< 3 kg) and PRETERMS" section**: *"For fragile skin, the stickiness of the medical grade
  adhesive can be diminished or eliminated by daubing the adhesive areas with a cotton ball or gauze"*.
  Cable towards the ankle; sensor on the **lateral side of the foot aligned with the 4th toe**.
- **Reattachment**: double-sided adhesive tabs, up to 3 stacked sets per optical window.
- **ROP warning**: *"High oxygen concentrations may predispose a premature infant to retinopathy.
  Therefore, the upper alarm limit for the oxygen saturation must be carefully selected…"*

> Footnote 5 (key): "The saturation accuracy of the Neonate and Preterm sensors were validated on adult
> volunteers and **1 % was added** to account for the properties of fetal hemoglobin."

### Rad-57 Operator's Manual (LAB-9204A)

Source: [techdocs.masimo.com/…/lab-9204a.pdf](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-9204a.pdf)

> Specification note 1 — the only real neonatal validation Masimo has published: "SpO2 and SpMet
> accuracy was determined on **16 neonatal NICU patients** ranging in age from **7 to 135 days** and
> weighting between **0.5 and 4.25 kg**. **79 data samples** were collected over a range of 70–100 %
> SaO2… with a resultant accuracy of **2.9 % SpO2**."

- **"Low SIQ" troubleshooting**: *"With neonates or infants, check that the peripheral blood flow to the
  sensor site has not been interrupted. For example, as may occur while **lifting or crossing their legs
  during a diaper change**."*
- M-LNCS/LNCS table: *Newborn* < 3 kg ±2 % no motion / ±3 % with motion; *Neonatal* < 3 kg ±3 %.
- Low Perfusion = the PI indicator does not exceed **0.25**.

### RD SET Blue — eIFU (LAB-9521A)

Source: [techdocs.masimo.com/…/lab-9521a-eifu.pdf](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-9521a-eifu.pdf)

The only sensor with paediatric/neonatal validation below 70 %: *"validated using convenience blood
samples from neonatal, infant, and pediatric patients with light to dark pigmented skin diagnosed with
congenital cyanotic cardiac lesions in the range of **60–100 % SpO2**".*

### rainbow SET IntelliVue Module (LAB-8486D)

Source: [techdocs.masimo.com/…/lab-8486d-master.pdf](https://techdocs.masimo.com/contentassets/69eaf746e9654d3299232b27cde9d55e/lab-8486d-master.pdf)

Neonatal defaults: Desat 80, Low 85, High 95; PR 100–200 bpm; RRac 30–150 rpm; neonatal/paediatric
SpO2 setting range 31–100 %. *Note (2026-10-14): these per-profile defaults were not found in the current
Radical-7 (LAB-5475L) and Rad-97 (LAB-9275H) operator's manuals, which print a single factory column
(SpO2 Low 88, High Off, PR 50–140). They may be specific to the IntelliVue module or an older revision;
see §8.*

## 2. Medtronic / Nellcor

### PM-1000N Service Manual

Source: [frankshospitalworkshop.com/…/Covidien Nellcor PM-1000N — Service manual.pdf](http://www.frankshospitalworkshop.com/equipment/documents/ecg/service_manuals/Covidien%20Nellcor%20PM-1000N%20Patient%20Monitor%20-%20Service%20manual.pdf)

- **Table 2-1 Accuracy**: Adult 70–100 % ±2; **Adult and Neonate Low Sat 60–80 % ±3**;
  **Neonate 70–100 % ±2**; with motion ±3; PR 20–250 bpm ±3.
- **Note 6**: low perfusion defined as *detected IR pulse modulation of 0.03 % to 1.5 %*.
  Monitor perfusion range: **0.03 % to 20 %**.
- **Table 2-2** (relevant to the I<sub>LED</sub> limit): red ≈660 nm, IR ≈900 nm,
  **optical power < 15 mW**, **dissipation 52.5 mW**.
- **Neonate mode**: separate alarm limits and, interestingly,
  *"the SPD alarm management parameter is not available for neonates"* (saturation pattern detection is
  disabled in neonates).

> Note 5 — neonatal validation: "Clinical functionality of the MAX-N sensor has been demonstrated on a
> population of hospitalized neonate patients. The observed SpO2 accuracy was **2.5 %** in a study of
> **42 patients** with ages of **1 to 23 days**, weight from **750 to 4,100 grams**, and 63 observations
> made spanning a range of **85 % to 99 % SaO2**."

### Nellcor sensor guide

Source: [pharmamed.be/…/24917_Guide-UK.pdf](https://www.pharmamed.be/media/product_files/24917_Guide-UK.pdf) — "The right sensor for each patient"

| Sensor | Weight range | Accuracy 70–100 % | Accuracy 60–80 % |
|---|---|---|---|
| MAXN (neonatal/adult) | < 3 kg or > 40 kg | ±2 | ±3 |
| MAXI (infant) | 3–20 kg | ±2 | ±3 |
| SC-NEO | 1.5–5 kg | ±2 | — |
| SC-PR (preterm) | < 1.5 kg | ±2 | — |

## 3. Philips

### IntelliVue MP40/50/60/70/90 — Instructions for Use, ch. 9 "Monitoring SpO2"

Source: [frankshospitalworkshop.com/…/Philips IntelliVue MP40,50,60,70,90 — User manual.pdf](http://www.frankshospitalworkshop.com/equipment/documents/ecg/user_manuals/Philips%20IntelliVue%20MP40,50,60,70,90%20Patient%20Monitor%20-%20User%20manual.pdf)

- *"When using the M1195A Infant Finger Sensor, select a finger or toe with a **diameter of between 7 and
  8 mm**. When applying a M1193A neonatal sensor **do not overtighten the strap**."*
- **CAUTION**: *"Do not use OxiCliq disposable sensors in a high humidity environment, such as in
  **neonatal incubators**…"*
- **CAUTION "Humidity"**: *"For neonatal patients, make sure that all sensor connectors and adapter cable
  connectors are **outside the incubator**. The humid atmosphere inside can cause inaccurate
  measurements."*
- **"Measuring SpO2", step 1**: *"Select the correct patient category setting (adult/pediatric and
  neonatal), as this is used to **optimize the calculation of the SpO2 and pulse numerics**."* → confirms
  that the algorithm changes with the patient category.
- Perfusion: *"ideally with a perfusion indicator value above 1.0"*.
- **WARNING**: inspect the site **every 2–3 h**; change it **at least every 4 h**.
- Accuracy per sensor: MAX-N (Neonate), SC-NEO, SC-PR, Oxiband OXI-A/N, OXI-P/I: **3 %** (70–100 %);
  MAX-R and OxiCliq N (Neonate): **3.5 %**; Oxiband OXI-A/N (Neonate): **4 %**.
- Neonatal alarm defaults: PR low 100 bpm, Brady 50, Tachy 240; Desat adjustable 30–100 % in Pedi/Neo.

### White paper "Measure with confidence — Pulse oximetry in Philips IntelliVue patient monitors"

Source: [documents.philips.com/…/c3ca0fdd20344125b018aaf7015bf571.pdf](https://www.documents.philips.com/assets/20191031/c3ca0fdd20344125b018aaf7015bf571.pdf)

Section **"Meeting needs in the NICU"**: OxyCRG (trends at 4 samples/s over 6 min), SpO2 histograms,
Neonatal Event Review (apnoea / bradycardia / desaturation), **Dual SpO2 pre- and post-ductal — "may
differ by as much as 25 %"** — and the CAR test (Car safety seat Assessment Record) for preterms < 37
weeks of gestation or < 2500 g birth weight.

## 4. Mindray — the best published neonatal validation

Source: [mindray.com/…/BeneVision-N-Series-Operators-Manual.pdf](https://www.mindray.com/content/dam/xpace/en_gb/resources/downloads/education/education-nseries/operators-manual/BeneVision-N-Series-Operators-Manual.pdf) — Appendix A and chapter 14

> "One percent was added to the accuracies for neonatal sensors to account for accuracy variation due to
> properties of fetal hemoglobin. Studies were performed to validate the accuracy of Pulse Oximeter with
> neonatal SpO2 sensors by contrast with a CO-Oximeter. Some **neonates aged from 1 day to 30 days with a
> gestation age of 22 weeks to full term** were involved in this study."

| Sensor | Neonates | Data pairs | A<sub>rms</sub> |
|---|---|---|---|
| 518B | 97 (51 M / 46 F) | 200 | **2.38 %** |
| 520N | 122 (65 M / 57 F) | 200 | **2.88 %** |

- Mindray module: 70–100 % ±2 % adult/paediatric, **±3 % neonatal mode**; < 70 % not specified.
  The integrated Nellcor and Masimo modules declare the same ±3 % in neonates.
- PI: measurement range **0.05–20 %** (Mindray) / **0.02–20 %** (Masimo).
- **WARNING** (ch. 14.2): *"Inspect the sensor site every two hours… Change the application site every
  four hours. **For neonates, or patients with poor peripheral blood circulation or sensitive skin,
  inspect the sensor site more frequently.**"*
- ~~There is an "SpO2 screen" intended exclusively for neonatal patients.~~ *Corrected 2026-10-14: no such
  screen exists in the N-series manual. The neonate-only screens are the OxyCRG family (OxyCRG, OxyCRG
  Expand with an SpO2 time-in-range statistics area, OxyCRG Review); see §8.*
- Declares conformity with **ISO 80601-2-61**.

## 5. Nihon Kohden

Probe manuals:
[TL-271T/274T](https://www.hamilton-medical.com/dam/jcr:4aa5b646-198c-4ef4-9c98-4908d3f1d14f/Nihon-kohden-spo2-probe-TL-271T-274T-TL-271T3-274T3_ifu_en_281951.pdf) ·
[TL-260T](https://www.hamilton-medical.com/dam/jcr:05222e52-52c9-4475-a6d9-d18ccc33f262/Nihon-kohden-multi-site-y-probe-TL-260T-instructions-for-use-en-281955.pdf) ·
[TL-220T](https://www.hamilton-medical.com/dam/jcr:872df19b-58f2-4814-a9a3-da94f7b3f3cb/Nihon-Kohden-SpO2-multi-site-probe-ops-0604-019889J-TL220T.pdf)

- **Suitable Weight / Attachment Site**: ≤ 3 kg neonate → **instep and sole of the foot**;
  3–20 kg infant → toe or finger. Concrete instruction: *"Attach the center of the light emitter to the
  little toe at the bottom of the foot where the toe joins the foot."*
- **Maximum recommended time on one site: 8 hours for the TL-27xT adhesive family** (IFU 281951;
  *corrected 2026-10-14, previously stated as 4 h*), 4 hours for the reusable finger probe
  ([Hamilton Medical knowledge base](https://www.hamilton-medical.com/Resource-center/Article-page~knowledge-base~853cb539-175e-4a40-8103-a1899f1fad57~Recommendations-for-stable-SpO2-measurement-with-Nihon-Kohden-sensors~.html)).
  And for the reusable TL-220T:
  *"Do not use this probe for long term measurement. Use a disposable probe such as TL-271T…"*
- **Thermal warning**: the site temperature *"may increase at the attached site by 2 or 3 °C and cause a
  burn"* — explicit risk list: fever, insufficient peripheral circulation, **neonate**, unconscious
  patient, elderly.
- Skin: *"Remove the probe carefully and slowly… **especially when removing it from a neonate, pay
  attention to the neonatal skin because it is delicate**"*; surgical tape *"may cause dermatopathy"* in
  neonates.
- Wavelengths: peaks at **650 and 950 nm**.
- **Accuracy (rms)**: 80–100 % ±2 %, 70–80 % ±3 %, < 70 % not specified — **validated only on healthy
  adult volunteers** (21–34 years, 14 subjects with varied pigmentation) by induced hypoxia according to
  ISO 80601-2-61:2011. **No neonatal study.**

## 6. GE HealthCare — the most detailed neonatal validation protocol

Source: ["U-TruSignal SpO2 Testing in Neonates" — GE protocol MWS DOC1964061, Study 123.04-2017-GES-0002](https://cdn.clinicaltrials.gov/large-docs/57/NCT03383757/Prot_SAP_000.pdf)
(manufacturer's own document, not a third party's)

- **Inclusion**: < 29 days already requiring arterial blood samples as standard of care.
  **Exclusion**: cardiac conditions (patent ductus arteriosus, persistent pulmonary hypertension, septal
  defects, congenital heart disease), MAP < 20 mmHg, congenital diaphragmatic hernia, high-frequency
  ventilation.
- **They record fetal haemoglobin (g/L) and HbF fraction (%)**, plus skin tone (modified Fitzpatrick
  scale).
- Data window: **5 s after a 12 s technical delay** from the blood draw.
- Analysis according to **ISO 80601-2-61 Annex EE** and the FDA Guidance for pulse oximeters
  (4 March 2013).
- TruSignal neonatal specification: 70–100 % **±3 digits** without motion and with clinical motion.

> **The methodological problem, in their own words:** ISO 80601-2-61:2011 requires ≥ 200 pairs from ≥ 10
> subjects spread over 5 plateaus of 70–100 % for the adult desaturation test.
> *"Unlike the invasive controlled desaturation test on adults in a laboratory environment in which the
> SaO2 can range from 70 % to 100 %, the SaO2 collected in this study is expected to be around 90 %.
> Since SaO2 values in this study may be clustered in 1 plateau around 90 %, **a minimum of 50 data pairs
> is considered adequate** to ensure proper function/clinical performance with neonates."* Target: 50–70
> pairs from 17–70 neonates per sensor, maximum 3 pairs per patient.

Results published on clinicaltrials.gov (NCT03383757, 2020-12-04): 117 neonates < 29 days (Tampere and
Bangalore), arterial CO-oximetry reference, **A<sub>rms</sub> 2.57 %** with both sensors (AllFit and
Sensitive), no adverse events.

## 7. Nonin — OEM modules, the closest case to PulseNest

Sources: [OEM III Module Specification and Technical Information](https://www.nonin.com/wp-content/uploads/2018/09/OEM-III-Module-Specifications.pdf) ·
[Xpod Operator's Manual](https://www.nonin.com/wp-content/uploads/2018/09/Xpod-Operators-Manual.pdf)

| Sensor | Adults / Paediatric | Neonates |
|---|---|---|
| Reusable finger clip | ±2 | ±3 |
| Flex | ±3 | ±3 |
| Soft sensor | ±2 | **N/A** |

- Pulse rate 18–300 bpm: ±3 digits in both populations.
- Wavelengths: red 660 nm, IR **910 nm @ 1.2 mW maximum average power**.
- Neonatal sensors: `8001J` Neonatal Flex; `6000N` / `7000N` neonatal disposables.
- Important note: *"Low perfusion **does not apply** to those sensors listed as N/A under the neonate
  column"* — i.e. they do not guarantee low-perfusion behaviour with several sensors in neonates.

## 8. Neonatal-specific features by manufacturer

Added 2026-10-14. Question: for each manufacturer, what is actually specific to neonates — sensors,
patient category / neonatal mode, alarms, screens — and in particular whether the screen itself is
neonate-specific. Sources are the current operator's manuals and IFUs; "not found" means the item was
searched for and not located in an accessible source. Confidence: [doc] verified in the official
document, [web] vendor web page, [sec] secondary source.

### Cross-cutting answer

| Aspect | Finding |
|---|---|
| **Base screen** | Identical for all patient categories in all eight manufacturers. Neonatal content comes as separate views or applications (OxyCRG, CCHD screening, delivery-room glide path), some of them only reachable when the category is Neo. |
| **SpO2 algorithm** | Only Philips states that the patient category changes the calculation. Masimo, Nellcor, GE, Mindray and Dräger keep the same SpO2 settings (averaging, sensitivity, response mode) for every category; Nonin has no category at all. |
| **Alarms** | SpO2 85 / 95 % is the neonatal consensus (Nellcor, Philips, Mindray, Dräger); Desat 75–80 %; PR 80–200 bpm depending on brand. Nellcor switches SatSeconds off and forbids SPD in neonatal mode. |
| **Sensors** | Foot in every brand. Weight thresholds: < 3 kg (Masimo, Nellcor, Philips, Nihon Kohden), < 2 kg (Nonin); preterm < 1 kg (Masimo NeoPt), < 1.5 kg (Nellcor SC-PR). |
| **Site inspection** | From every hour (Masimo, poorly perfused) to every 8 h (Nellcor MAX-N, Nihon Kohden adhesive); 2–3 h inspect / 4 h change is the usual rule. |

### Masimo (Radical-7, Rad-97, Root)

Sources: RD SET DFU [LAB-10131A](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-10131a-eifu.pdf),
Radical-7 OM [LAB-5475L](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-5475l_master.pdf),
Rad-97 OM [LAB-9275H](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-9275h_master.pdf),
Root Pathway addendum [LAB-10162A](https://techdocs.masimo.com/globalassets/techdocs/pdf/lab-10162a_master.pdf),
Eve product information [PLM-10842D](https://www.masimo.co.uk/siteassets/uk/documents/pdf/plm-10842d-product-information-eve-eu.pdf). All [doc].

- **Sensors**: RD SET Neo (< 3 kg, foot; alternative palm/back of hand), NeoPt / NeoPt-500 (preterm < 1 kg,
  foot or hand), Inf (3–10 kg, great toe). Single-patient adhesive/foam wrap. Neonatal-only instructions:
  daub the adhesive with cotton or gauze for fragile skin, lateral aspect of the foot aligned with the
  4th toe, never add tape. Site check "as frequently as every (1) hour with poorly perfused patients".
  Accuracy Neo/NeoPt A<sub>rms</sub> 3 % (no motion, motion, low perfusion) vs 1.5–2 % adult.
- **Patient category**: profiles Adult (blue), Pediatric (green), **Neonatal** (status bar "NEO", pink),
  Custom 1–8; "Save as Neo" stores a customised neonatal profile. The profile is a **stored settings
  container, not an algorithm mode**: Sensitivity (APOD / NORM / MAX), averaging (8 s, 2–16 s), FastSat
  and PR range 25–240 bpm are global and not tied to the profile. On Rad-97 the Neo profile additionally
  forces a neonatal NIBP cuff (ranges 40–130 / 20–100 mmHg).
- **Alarms**: both manuals print a **single** factory column (SpO2 Low 88 %, High Off, Rapid Desat −10 %,
  delay 15 s, PR 50–140 bpm); there is no per-profile default table. 3D Desat Index, Pi Delta and the
  Adaptive Threshold Alarm (Rad-97) are not labelled neonatal. With Pathway the first-10-minute alarms are
  High 99 / Low 88 / Rapid Desat −10 / delay 10 s.
- **Screens**: the standard layout is **not** neonate-specific (same numeric / trend / histogram views;
  only the label and colour change). Neonatal content exists as separate applications: **Pathway** (Root +
  Radical-7, delivery room: minute-by-minute SpO2 target bands from AHA 2015 NRP, min 1 60–65 % … min 10
  85–95 %; PR visual thresholds Low 100 / Critical 60 bpm; visual only, no audible alarms) and **Eve**
  (CCHD screening: right hand, then either foot, automatic pre/post-ductal synchronisation and pass
  calculation; "Dual SET Oximetry" simultaneous two-site display on Root; CE, not US/Canada).
- **Other**: RRa range 4–120 rpm for infants/neonates (adults 4–70); SpHb and RRp not indicated for
  neonates.

### Medtronic / Nellcor (PM1000N; PM100N shares the alarm management)

Sources: [PM1000N Operator's Manual 10104146E00](https://www.medtronic.com/content/dam/covidien/library/us/en/product/pulse-oximetry/PM1000N_OperatorsManual_EN_10104146E00.pdf) [doc],
[MAX-N DFU](https://www.ugap.fr/images/media-wp/2023/04/rfart_maxni_mdu.pdf.avif) [doc],
[SoftCare page](https://www.medtronic.com/en-gb/healthcare-professionals/products/patient-monitoring/pulse-oximetry/sensors/nellcor-softcare-nonadhesive-spo2-sensor.html) [web].

- **Sensors**: MAXN (< 3 kg or > 40 kg, sterile single-use adhesive), OxiCliq N (two-piece, same range),
  SC-PR (preterm < 1.5 kg, non-adhesive), SC-NEO (1.5–5 kg, non-adhesive), OXI-A/N reusable with wraps,
  D-YS multi-site > 1 kg. MAX-N: foot with the window on the sole next to the cable, alternative hand;
  wrap "firmly but not too tightly"; **inspect the site every 8 hours**; may be re-applied with adhesive
  dots. SoftCare: developed to reduce adhesive on neonatal skin; SC-NEO-I / SC-PR-I ±2 (57 patients,
  24–40 weeks, 710–5000 g).
- **Patient category**: it is literally an **"Alarm Mode"** (ADULT / NEONATE, MENU > Alarm Mode;
  institutional default settable by service). It changes **only the default limits and which alarm
  management features are available**; a baby icon appears between the limits. It does not change the
  SpO2 algorithm or averaging: Response Mode (NORMAL 5–7 s / FAST 2–4 s) is a separate, independent
  setting. PR range 20–250 bpm for all patients.
- **Alarms** (Table 4-3): neonate SpO2 85–95 % (adult 85–100), PR 90–190 bpm (adult 40–170).
  **SatSeconds default OFF in neonate** (adult 100; still adjustable 10/25/50/100/OFF). **SPD "Always
  OFF", not allowed** in neonate mode (adults only). Pulse Rate Delay OFF by default in both modes.
- **Screens**: none neonate-specific; same screen, baby icon and neonatal limits only. No OxyCRG,
  histogram or event review.
- **Other**: no incubator/humidity caution in the PM1000N manual (only the opaque-cover ambient-light
  warning).

### Philips (IntelliVue MX / X3, FAST-SpO2)

Sources: [MX100 / X3 IFU Release N](https://images.philips.com/is/content/PhilipsConsumer/Campaigns/CA08092022_nbp/Mx100_X3_ifu_eng.pdf) [doc],
[MP5 IFU Release G.0](https://avobus.com/pdf/Philips/Philips%20IntelliVue%20MP5%20Patient%20Monitor%20-%20User%20manual.pdf) [doc],
[Neonatal Event Review and Oxy-CRG brochure](https://www.documents.philips.com/doclib/enc/fetch/2000/4504/577242/577243/577247/582646/583147/PM_-_Neonatal_Event_Review_and_Oxy-CRG_brochure.pdf) [web],
[SpO2 white paper 2019](https://www.documents.philips.com/assets/20191031/c3ca0fdd20344125b018aaf7015bf571.pdf) [web].

- **Sensors**: M1193A / M1193T reusable neonatal **wrap** 1–4 kg, hand or foot ("do not overtighten the
  strap"); M1133A (adhesive-light) and M1134A (adhesive-free) single-patient wraps, foot/hand < 3 kg;
  M1132A infant 3–10 kg. Also Nellcor MAX-N, N-25, OxiCliq N, SCNEO-I and Masimo Neo/NeoPt via adapter.
- **Patient category**: Adult / Pedi / Neo in Admit Patient. The IFU states it "determines the algorithm
  the monitor uses to process and calculate some measurements, the safety limits … and the alarm limit
  ranges", and the SpO2 chapter: "used to optimize the calculation of the SpO2 and pulse numerics".
  **Philips is the only manufacturer that claims a category-dependent calculation**; what changes is not
  disclosed. Averaging time is user-selectable and not tied to the category. Profiles (e.g. "ICU
  neonatal") carry category + limits; Screens do not affect category or alarms.
- **Alarms** (Default Settings appendix, X3 and MP5): Neo SpO2 Low 85, High 95, Desat 80 (Adult/Pedi
  90 / 100 / 80); Desat delay 20 s; limit delay 10 s. Limit range Neo/Pedi 30–100 % (adult 50–100).
  Pulse range 30–300 bpm, 1-bpm steps 30–50 in Neo. ECG extreme-brady clamp 70 bpm for neonates. No alarm
  is disabled in Neo; 3D Desat Index (Masimo option) Off for all categories.
- **Screens**: the base layout is not neonate-specific. Neonatal content is added as views and
  applications: **OxyCRG** (three high-resolution trends btbHR, SpO2, Resp, "mainly used in neonatal
  monitoring", 3 cm/min, up to 9 min, MP20 and higher); **Neonatal Event Review** (event group "NER":
  4-min episodes at 4 samples/s, triggered by HR/SpO2/Resp alarms or user thresholds, counters
  A(D)/B(D)/AB(D)/D, 50 events per 24 h); **Car seat (CAR) test** in the NER group with a 1-s SpO2
  histogram; **Dual SpO2** pre/post-ductal (MP40+ / MX500+). The X3 / MX100 IFU has **no OxyCRG or NER
  chapter** (only "OxyCRG waves" reports).
- **Other**: inspect every 2–3 h, change site at least every 4 h; monitor and connectors outside the
  incubator; OxiCliq not in incubators; cover the sensor under IR warmers. Accuracy: M1193A 2 %, M1193T
  neonate 4 %, M1133A / M1134A neonate 3 %, Nellcor sensors via adapter 3 %.

### GE HealthCare (CARESCAPE B650 / B850 / ONE, TruSignal)

Sources: [CARESCAPE B850/B650 User's Manual SW v2, 2062971-003](https://storage.mtender.gov.md/get/8a51c17c-8b1e-4561-a0aa-78d356ebe21d-1728298723489) [doc],
[TruSignal sensor sheet DOC0710534](https://res.onemed.com/SE/Produktblad/414392.pdf) [doc],
[FDA K093881](https://www.accessdata.fda.gov/cdrh_docs/pdf9/K093881.pdf) [doc],
[ANSM safety notice 2012](https://archive.ansm.sante.fr/content/download/42793/555663/version/1/file/mes-120807-MoniteurCarescapeB650-GeHealthcare.pdf) [doc].

- **Sensors**: TS-SE-3 Sensitive Skin (reusable body + single-patient foam wrap/adhesive tape, "≤ 3 kg …
  premature infant/neonate through small adult", infant foam sandal OXY-SND); TS-AF-10/25 AllFit
  (single-patient adhesive, ≤ 3 kg to adult); TS-W-D wrap is ** > 3 kg only**; TS-PAW paediatric wrap
  3–20 kg. Suggested newborn site: adhesive sensor on the sole of the foot (motion artefact).
- **Patient category**: **there is no "patient type = Neonatal" selector**. Neonatal behaviour comes from
  the **NICU software package** (OR / PACU / ICU / ED / NICU, chosen at installation or in Care Unit
  Settings) plus profiles (Infant, Pediatric) and the NIBP cuff size. NICU changes ECG and NIBP only:
  QRS width "Narrow" default, Brady becomes a lethal alarm, V Tach high priority at 180 bpm (150
  otherwise), V Brady 60 bpm, A-Fib / 12RL / telemetry / automatic SPV/PPV unavailable, E-modules other
  than E-NSATX / E-MASIMO disabled. SpO2 settings are per technology, not per patient: Masimo averaging
  2–16 s (8 s) and sensitivity, Nellcor response Normal/Fast (NICU default Fast per the B650 SW 1.1
  addendum [web]), GE Ohmeda averaging adjustable.
- **Alarms**: **NICU numeric SpO2 / PR defaults not found** (they live in the paywalled Supplemental
  Information Manual); NICU SpO2 priority = Escalating. Nellcor SatSeconds available with pie-chart
  indicator and the 3-violations-in-60-s safety net. No GE "Desat" limit alarm found. Probe-off escalates
  no higher than Medium. ANSM notice: with the PDM Nellcor and SatSeconds off, the SpO2 limit alarm could
  fail; corrective action = enable SatSeconds.
- **Screens**: **none neonate-specific**. OxyCRG appears only in the glossary; no OxyCRG or neonatal view
  exists in B650 / B850 SW v2. Layout identical; only package and profile defaults change.
- **Other**: "WARNING — NEONATAL": inaccurate SpO2 is most likely in neonates and infants; accept the
  SpO2 reading only if the pulse rate is within 10 % of the ECG heart rate and the signal-strength shows
  ≥ 2–3 asterisks. Check the probe site every 4 h, "more frequently … for neonates".

### Mindray (BeneVision N-series; ePM / uMEC share the platform)

Sources: [N-series Operator's Manual, FDA rev 20.0](https://www.mindray.com/content/dam/xpace/en_us/resource-library/patient-monitoring/technical-document/continuous-patient-monitoring/H-046-011259-00-N-series-ops-manual-FDA-20.0.pdf) [doc],
[global rev 22.0 Vol. I](https://storage.mtender.gov.md/get/9d078324-2007-4c56-9018-b2eac2ca41cc-1703601102204) [doc],
[ePM 10M/12M specs](https://www.medaval.ie/docs/specs/Mindray-ePM10M-ePM12M-Specs.pdf) [web].

- **Sensors**: 518B / 518BLH reusable, Neonate, foot (518BLH "< 5 kg" per an MSF catalogue [sec]); 518C
  reusable foot + disposable bandage; 520N disposable adult/neonate finger or foot; 521N disposable
  neonate foot; 520I / 521I infant toe. **Weight ranges are not stated in the Mindray manual.** Also
  Masimo RD SET Neo / NeoPt / NeoPt-500, LNCS Neo-L / NeoPt and Nellcor MAXNI, OXI-A/N.
- **Patient category**: Adult / Ped / Neo in Patient Demographics; department configurations General /
  OR / ICU / **Neonatology** / CCU, each with Adult / Ped / Neo sets; the default Neo configuration may be
  loaded **by gestational-age segment**. Changing the category reloads the whole configuration. What
  changes: alarm defaults and ranges, NIBP (initial 90 mmHg, overpressure 147 mmHg, 90 s timeout), Resp
  lead II, OxyCRG availability. **SpO2 algorithm settings are not category-specific**: Masimo sensitivity
  Max / Normal / APOD, averaging 2–16 s (8 s), FastSAT off; Mindray SpO2 "Sensitivity" (= averaging)
  default Med. PR range Mindray 20–300, Masimo 25–240 bpm.
- **Alarms** (Appendix C): Neonate SpO2 **95 / 85 %** (adult/ped 100 / 90), medium priority; **Desat
  80 %, high priority**, all categories, switch-off only with password ("Guard Limits"); PR neonate
  **200 / 100** (adult 120 / 50, ped 160 / 75), neonate PR limit range 15–300. **SpO2 Low Escalation
  Time** setting. Nellcor Sat-Seconds; "SpO2 Too Low" after 3 violations per minute. FiO2 high default
  Neonate 90 %. Alarm volume Neonatology default 7.
- **Screens**: **there is no "SpO2 screen" in the N-series manual** (corrects §4). The neonate-only
  screens are: **OxyCRG** (default when Neonatology is selected; "available … only when the patient size
  is set to Neo"; 6-min HR + SpO2 trends, Resp / CO2 compressed waveform, ABD events A10 / A15 / A20, B,
  D, AB, AD, ABD with thresholds, 1+3 / 2+2 / 3+1-min storage); **OxyCRG Expand** (real-time ECG / Resp /
  SpO2 + OxyCRG + 90-min timer + **SpO2 statistics area** = time per SpO2 range, printable; "not intended
  for adult and pediatric"); **OxyCRG Review** (48 h, Neo only). The **Targeted Goal screen** (big
  numerics, target-range dashboard, statistics) is reachable by two-finger swipe only in Neo but is not
  Neo-exclusive. No SpO2 histogram or pre/post-ductal feature; dual SpO2 / ΔSpO2 exists for all
  categories. Tabular trend at 5-s interval "especially suited for neonatal applications".
- **Other**: inspect every 2 h, change every 4 h, "for neonates … inspect more frequently"; connectors
  outside the incubator; warning against a 100 % high limit (retrolental fibroplasia); TM70 telemetry not
  for neonates. ePM 10M / 12M: neonate ±3 %.

### Nihon Kohden (Life Scope G9 / G7 / BSM, OLV-3100)

Sources: [TL-27xT IFU 281951](https://www.hamilton-medical.com/dam/jcr:4aa5b646-198c-4ef4-9c98-4908d3f1d14f/Nihon-kohden-spo2-probe-TL-271T-274T-TL-271T3-274T3_ifu_en_281951.pdf) [doc],
[TL-051S GUDID](https://accessgudid.nlm.nih.gov/devices/14931921829384) [doc],
[G5/G7 510(k) K203435](https://fda.innolitics.com/device/K203435) [doc],
[Life Scope VS datasheet](https://eu.nihonkohden.com/media/LfOAuh9A11PIU847kzjr3MecQKpZiHjlpLzvaf0tf5fiDvpqZ7K7BLG7UCf6702xhvDH5W5IhmYVc0Ie/DatasheetLifeScopeVS_English.pdf) [doc],
[OLV-3100 PMDA document (Japanese)](https://www.pmda.go.jp/PmdaSearch/kikiDetail/ResultDataSetPDF/530225_21300BZZ00111000_A_01_02) [doc],
[NK Europe product guide 2014-15](https://pdf.medicalexpo.com/pdf/nihon-kohden-europe/product-guide-2014-2015/69520-139152-_6.html) [web].

- **Sensors**: TL-273T / 273T3 neonate ≤ 3 kg instep + sole (also adult ≥ 40 kg); TL-274T infant 3–20 kg
  finger/toe; TL-271T adult ≥ 30 kg; TL-051S disposable neonate ≤ 3 kg; TL-535U single-use neonate/preterm
  (Japan) [sec]. All single-patient adhesive; **no neonatal wrap or reusable neonatal probe found**.
  Maximum attachment time 8 h (adhesive family) / 4 h (reusable finger probe); skin temperature +2–3 °C,
  change site more often for neonates and low birth weight.
- **Patient category**: G5 / G7 cleared for all populations including neonates; arrhythmia detection
  child and older only; AF, ST, QTc / QRSd adult only. SpO2 engine selectable (Nihon Kohden, Masimo or
  Nellcor), PR 25–300 bpm "varies by SpO2 technology". **What the Neonate patient type changes
  (averaging, PR range, defaults): not found** — the G9 / G7 / BSM operator's manuals are behind paywalled
  previews.
- **Alarms**: **neonatal default limits not found**. OLV-3100: SpO2 and PR high/low plus a ΔSpO2 upper
  limit (two linked units); no neonatal mode.
- **Screens**: product guide for NICU lists **OCRG (oxycardiorespirogram), Dual SpO2 and aEEG**; "OCRG
  Display" is a section of the BSM-2300 / BSM-4100 manuals [sec]. Otherwise no neonate-specific layout
  found.
- **Other**: no neonatal A<sub>rms</sub> published; no incubator/humidity caution found.

### Dräger (Infinity Delta, Infinity M540 / IACS, Vista 120)

Sources: [Infinity Delta IFU (manualslib)](https://www.manualslib.es/manual/2297/Dräger-Infinity-Delta-Serie.html?page=598) [doc],
[Infinity M540 IFU (manualslib)](https://www.manualslib.com/manual/1928473/Dr-Ger-Infinity-M540.html) [doc],
[Delta brochure](https://cdn.abicart.com/shop/14115/art73/224588673-40299d-31671_N0889580_Delta_Brochure.pdf) [doc],
[IACS neonatal-mode safety notice 2013](https://medicaldevices.icij.org/events/hkg-draeger-infinity-acute-care-system-in-neonatal-mode) [doc].

- **SpO2 technology by family**: Delta / Delta XL / Kappa: Masimo SET, Nellcor OxiMax or Dräger
  OxiSure; M540 / IACS: Masimo SET / rainbow SET MCable or Nellcor OxiMax MCable; Vista 120: Dräger SpO2
  or Nellcor module.
- **Sensors**: Masimo LNOP NEO / NEO SS (< 10 kg foot), LNOP-YI reusable multisite < 3 kg, LNCS Neo
  (< 10 kg), NeoPt (< 1 kg), Inf (3–20 kg); Nellcor N-25, MAX-N. **Dräger's own OxiSure reusable sensors
  are "not intended for neonates".**
- **Patient category**: Adult (12–140 y) / Pediatric (0–16) / **Neonate (0–2)**, each with its own
  factory and hospital profiles (alarm limits, views, settings); switching to or from Neonate clears the
  weight; the Cockpit re-aligns to the docked M540's category. Delta: in neonatal mode arrhythmia is Off
  and "only bradycardia as low HR alarm"; apnoea detection neonatal/paediatric; CO, ST, arrhythmia adult
  and paediatric only. Averaging per technology (Masimo 2–16 s, Nellcor Normal 5–7 s / Fast 2–4 s,
  OxiSure Normal / Fast); **no separate neonatal algorithm**.
- **Alarms** (M540 IFU): SpO2 upper default 100 % (adult/ped) / **95 % (neonate)**, lower 85 %; **Desat
  75 %** (range 19 % to SpO2 low −1); PLS default adult 45–120, ped 50–150, **neonate 80–180** (range
  30–235). A Desat breach raises priority to high; Nellcor SatSeconds ≠ Off disables Desat. Delta
  brochure: "life-threatening desaturation alarm in neonatal mode only". 2013 safety notice (IACS VG2.0.3+,
  neonatal mode): pausing the yellow SpO2-low alarm suppressed the red life-threatening alarm. Vista 120
  neonatal defaults not found.
- **Screens**: Delta has **OxyCRG "in neonatal mode"** with a dedicated hard key (3 / 6-min beat-to-beat
  HR + SpO2 trend + Resp / etCO2 / tpO2 channel, time base 1–24 min, review summary of 75 events with
  detail for the last 50) and integrates Isolette C2000 / Caleo incubator and Babytherm data. **M540 /
  IACS and Vista 120 have no OxyCRG or neonatal view**; only configurable views and profiles per category.
- **Other**: inspect every 2 h, change site at least every 4 h; preterm on O2: do not set the high limit
  to 100 % (retrolental fibroplasia), tcpO2 recommended. Neonatal accuracy "reduced ±1 digit vs adult"
  (fetal Hb); OxiSure ±2 % (±3 % neonates); Vista 120 Dräger SpO2 ±3 % neonate, PR 25–300.

### Nonin (7500, Avant 9600, OEM III / Xpod)

Sources: [8001J / 8001JFW IFU](https://www.nonin.com/wp-content/uploads/8001J-8001JFW-IFU.pdf) [doc],
[6000CN / 7000N Operator's Manual](https://www.nonin.com/wp-content/uploads/6000CN-7000N_Operators-Manual.pdf) [doc],
[Model 7500 manual](https://www.nonin.com/wp-content/uploads/7500-English.pdf) [doc],
[Avant 9600 manual](https://medaval.ie/docs/manuals/Nonin-9600-Manual.pdf) [doc],
[OEM III support page](https://www.nonin.com/support/oem3/) [web], [Nonin FAQ](https://www.nonin.com/?p=831) [web].

- **Sensors**: 8001J Neonatal Flex (reusable silicone) + 8001JFW FlexiWrap single-use tape: neonates
  < 2 kg, "outstep of the left foot, directly under the toes", inspect at least every 4 h, do not stretch
  the tape; 8008J infant 2–20 kg toe [sec]. 6000CN (cloth) / 7000N (Flexi-Form) disposable
  neonate/adult: < 2 kg or > 30 kg, sole close to the toes, inspect every 6–8 h. Accuracy neonate 6000CN /
  7000N ±3 A<sub>rms</sub> (231 pairs, 26 subjects < 30 days, 75–100 %, on the 7500).
- **Patient category: none.** The 7500 and Avant 9600 have no patient-type selector; the indication
  "adult, pediatric, infant, and neonatal" is realised through the sensor choice ("may be used to monitor
  neonatal patients when used with an appropriate neonatal sensor"). Averaging is global (7500 Standard /
  Fast 4-beat vs Hybrid; 9600 4- or 8-beat). OEM III: no neonatal mode, only neonate A<sub>rms</sub>
  columns (±3 flex / 6000C, ±4 7000, ±3 low perfusion), PR 18–321 bpm.
- **Alarms**: single factory set, no neonatal set: SpO2 High Off (80–100), Low 85 % (50–95), PR High 200
  (75–275), Low 50 (30–110); low-perfusion alarm. No desat index or delay features.
- **Screens**: 3-digit LED numerics and pulse bar; nothing neonatal.
- **Other**: PR display 18–321 bpm (7500), 18–300 (9600); sensor operating temperature ≤ 40 °C (OEM III);
  no neonatal thermal statement found.

### Not found (2026-10-14)

- Masimo: an official document with per-profile neonatal alarm defaults; LNCS Neo / NeoPt DFU text; an
  English Eve operator addendum.
- GE: NICU numeric SpO2 / PR defaults; TruSignal IFU site-rotation interval; the ±3 % neonatal figure in
  the B650 / B850 user's manual (it is in the supplemental manual).
- Mindray: 518B / 520N weight ranges in Mindray documents; uMEC not researched.
- Nihon Kohden: any G9 / G7 / BSM operator's-manual text on what the Neonate type changes; neonatal
  default limits.
- Dräger: Vista 120 neonatal defaults; Masimo neonatal sensor compatibility with the M540 MCable.
- Nellcor: N-600x and PM100N manuals (403 on the hosting sites).

## Gaps and negative findings

- **Dräger**: `draeger.com` does not respond to automated download (timeout at 280 s, three attempts).
  The IFUs of the Infinity M540 and the Babylog VN500 exist and are public; still to be obtained by
  another route. No surprises expected: the M540 uses the Masimo SET module already covered (the VN500 is
  a ventilator and does not measure SpO2).
- **Texas Instruments / Analog Devices / Maxim**: no neonate-specific documentation. Neither the AFE4490
  datasheet nor the SpO2 application notes (MAX3010x, MAX86141, MAXREFDES117/1043) mention the neonatal
  population, fetal haemoglobin or irradiance limits on preterm skin. The responsibility is transferred
  entirely to the device manufacturer.

## What applies directly to PulseNest

1. **The accuracy target must be ±3 % A<sub>rms</sub>**, not ±2 %, documenting that 1 point is the HbF
   margin. Aligns with the metrological uncertainty task (ISO 80601-2-61 Annex JJ).
2. **The measurement site is the foot or the hand, never a finger**: lateral side of the foot aligned
   with the 4th toe (Masimo) or instep/sole (Nihon Kohden). Consistent with the preterm foot dimensions
   already documented.
3. **Optical and thermal ceiling**: < 15 mW optical power and 52.5 mW total dissipation in the sensor
   (Nellcor); +2–3 °C is Nihon Kohden's burn criterion. A hard reference for raising the LED current
   from 20 to 50 mA: the thermal/skin brake is quantified by Nellcor.
4. **Industry low-perfusion thresholds**: Nellcor 0.03–1.5 % IR modulation; Masimo PI < 0.25; Philips
   "ideally PI > 1.0"; declared PI range 0.02–20 %. Useful for the PI upper bound in `spo2_sqi` and for
   PI stability.
5. **ISO 80601-2-61 Annex EE does not apply literally to neonates**, and GE documents the accepted
   deviation (≥ 50 pairs around 90 % instead of 200 over 5 plateaus). The precedent to cite if clinical
   validation is ever done.

---

Compiled from the manufacturers' public documentation. Links point to the original PDFs; literal quotes
are reproduced in the original language of the document.
PulseNest project — Medical Open World.
