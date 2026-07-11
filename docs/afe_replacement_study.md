# AFE Replacement Feasibility Study

**Project:** IncuNest (Medical Open World)
**Date:** 2026-07-11
**Context:** Motivated by AFE4490 AMBDAC post-TIA limitation documented in `project_agc_design.md` section 3.
**Scope:** Evaluate modern AFE candidates to replace the AFE4490 in the IncuNest pulse oximeter, with emphasis on clinical-grade transmissive probe compatibility.

---

## 1. Problem Statement (AFE4490 AMBDAC Limitation)

Full reference: `project_agc_design.md` section 3.

The AFE4490 injects ambient cancellation current (AMBDAC) **after the TIA** (Eq. 2 p.30 of datasheet: outside the RF/RI gain factor). This means:

- The TIA is unprotected against large ambient photocurrent. The only defense is reducing RF, which sacrifices signal gain.
- With O2 constraint (V_TIA_DIFF <= 0.9 V) and RG=x1, the ADC (+-1.2 V) is never the active constraint, making RG>1 rarely useful and AMBDAC (useful only as AMBDAC+RG pack) equally marginal.
- AMBDAC is an **offset relocator** (subtracts equally across all 4 phases), not a true ambient canceller. The datasheet assumes perfect cancellation that does not materialize in practice.
- **Critical IncuNest scenario:** Neonatal phototherapy generates intense continuous ambient light. The AFE4490 has no pre-TIA electronic defense; mitigation is limited to optical shielding or a more modern AFE.

TI corrected this architecture starting with the AFE4404 (2015): pre-TIA cancellation.

## 2. Transmissive vs. Reflective Measurement Modes

### 2.1 Physical Principle

| Aspect | Transmissive | Reflective |
|---|---|---|
| Geometry | LED and PD on opposite sides of tissue | LED and PD on same side of tissue |
| Optical path | Through tissue (finger, earlobe, neonatal foot) | Backscattered from tissue (wrist, forehead) |
| Typical probe | Finger clip, ear clip, neonatal wrap with cable (1-3 m) | Flat sensor on PCB or patch |
| LED current needed | High (50-200 mA): longer path, more attenuation | Low (1-50 mA): shorter path |
| PD location | Remote, connected by cable | On PCB, adjacent to LEDs |
| Clinical standard | DB9 / Nellcor-compatible connectors, back-to-back LEDs (2-wire) | Proprietary, multi-wire, on-board |

### 2.2 Market Segmentation

**Medical / clinical pulse oximetry** continues to use **transmissive probes** as the primary measurement mode:

- **ISO 80601-2-61:2026** references transmissive probes as the standard configuration for SpO2 measurement in hospital-grade pulse oximeters.
- All major clinical probe manufacturers (Nellcor/Medtronic, Masimo, Medle, Nonin) produce transmissive finger/foot/ear probes with standardized connectors.
- Transmissive mode provides higher signal-to-noise ratio due to the well-defined optical path through arterial beds.
- FDA-cleared / CE-marked bedside monitors (Philips, GE, Drager, Mindray) exclusively use transmissive probes for SpO2.
- Reflective probes exist in clinical settings (forehead sensors) but are secondary / backup, not the primary measurement.

**Wearable / consumer devices** use **reflective optics** exclusively:

- Smartwatches (Apple Watch, Samsung Galaxy Watch, Garmin), smart rings (Oura), fitness bands: all use reflective PPG with on-PCB LEDs and PDs.
- The wrist / finger dorsal anatomy is not suitable for transmissive measurement.
- Lower regulatory burden (consumer wellness vs. medical device).

### 2.3 AFE Specialization

The AFE chip itself does not inherently "know" whether it operates in transmissive or reflective mode, it just drives LEDs and reads photodiode current. However, certain architectural features make an AFE more or less suitable for each mode:

| Feature | Transmissive (clinical) | Reflective (wearable) |
|---|---|---|
| LED driver current | >= 100 mA (high attenuation) | 1-50 mA (low path loss) |
| LED driver topology | **H-Bridge** (back-to-back 2-wire probes) | Common anode sink (separate LED pins) |
| PD input design | High-impedance, cable-tolerant, EMC-robust | On-PCB, low parasitic capacitance |
| Probe diagnostics | LED open/short, PD open/short, cable on/off | Rarely needed (no cable) |
| Ambient cancellation range | Large (phototherapy, room light through tissue) | Moderate (skin surface scatter) |
| Power budget | Mains-powered monitor, no constraint | Battery, ultra-low-power critical |
| Regulatory positioning | IEC 60601, ISO 80601-2-61 | Consumer / wellness |

**Key finding:** The AFE4490 is the **only device in the TI AFE family** that includes an H-Bridge LED driver, which is essential for driving standard clinical probes with back-to-back (anti-parallel) IR+RED LEDs on 2 wires. All newer TI AFEs (4404, 4410, 4420, 4900, 4950, 4432) use common-anode current-sink drivers that require **separate LED connections** (minimum 3 wires: common anode + 2 cathodes), incompatible with standard 2-wire Nellcor/DB9 clinical probes without external H-Bridge circuitry.

## 3. TI AFE Family Comparison

### 3.1 General Comparison Table

| AFE | Year | Positioning | LEDs / PDs | Ambient cancellation | LED I_max | H-Bridge | Probe diag | Package |
|---|---|---|---|---|---|---|---|---|
| AFE4490 | 2012 | **Clinical pulse oximetry** | 2 / 1 | Post-TIA, 0-10 uA | 200 mA (4 ranges) | **YES** | **YES** (LED+PD open/short, cable) | VQFN-40 (6x6 mm) |
| AFE4400 | 2012 | Clinical SpO2 (reduced 4490) | 2 / 1 | Post-TIA | 100 mA | YES | Partial | VQFN-40 (6x6 mm) |
| AFE4403 | 2014 | Low-power SpO2 | 2 / 1 | Post-TIA | 100 mA | YES | Partial | DSBGA |
| AFE4404 | 2015 | Wearable HR/SpO2 | 3 / 1 | **Pre-TIA**: +-7 uA, per-phase | 100 mA | No | No | DSBGA |
| AFE4410 | 2018 | Wearable multi-LED | 3+1 / 1 | Pre-TIA, **auto AGC** | 100 mA | No | No | DSBGA |
| AFE4420 | 2019 | Wearable multi-sensor | 4 / 4 | Pre-TIA: +-254 uA | 125 mA | No | No | DSBGA |
| AFE4900 | 2018 | **Medical**: PPG+ECG | 4 / 3 | Pre-TIA: +-126 uA | 200 mA | **No** | ECG lead-off only | DSBGA-30 (2.6x2.1 mm) |
| AFE4950 | 2021 | **Medical**: PPG+BioZ/ECG | 8 / 4 | Pre-TIA: 256 uA + 64 uA | 250 mA | **No** | ECG lead-off only | DSBGA-36 (2.6x2.5 mm) |
| AFE4432 | 2021 | Wearable premium | multi | Pre-TIA: 2 DACs, auto | varies | No | No | DSBGA |

### 3.2 Ambient Cancellation Architecture

| AFE | Injection point | Range | Granularity | Per-phase | Automatic |
|---|---|---|---|---|---|
| AFE4490 | **Post-TIA** (stage 2) | 0-10 uA (referred to input via xRF/RI) | 1 uA | NO (same for all 4 phases) | No |
| AFE4404 | Pre-TIA (INP node) | +-7 uA | 0.47 uA | YES | No |
| AFE4410 | Pre-TIA | +-7 uA | fine | YES | YES (on-chip loop) |
| AFE4420 | Pre-TIA | +-254 uA (7-bit) | ~4 uA | YES | Partial |
| AFE4900 | Pre-TIA | +-126 uA | fine | YES | Optional |
| AFE4950 | Pre-TIA | 256 uA amb + 64 uA LED (8-bit each) | fine | YES | Optional |
| AFE4432 | Pre-TIA | 255 uA + 64 uA, 2 separate DACs | 8/9-bit | YES | YES |

Pre-TIA advantage: ambient current is subtracted BEFORE the TIA converts it to voltage, protecting the TIA itself (allows high RF with large ambient) and enabling per-phase cancellation. This is exactly what the AFE4490 cannot do.

## 4. Candidate Evaluation

### 4.1 Evaluation Criteria

Per `project_afe_replacement_study_task.md`:

1. **LED drive current** vs. clinical probes (I_F up to 50 mA typ. Medle; max rated per probe spec)
2. **Probe diagnostics** (LED open/short, PD open/short, cable detection)
3. **Transmissive topology** with remote PD by cable (1-3 m): noise, cable capacitance, EMC robustness
4. **Pre-TIA ambient cancellation**: range sufficient for neonatal phototherapy
5. **Regulatory positioning** (IEC 60601 / ISO 80601-2-61)
6. **Availability, price, longevity**
7. **Migration cost**: incunest_afe4490 library, HGAC algorithm, IncuNest PCB

### 4.2 Candidate A: TI AFE4900

| Criterion | Assessment | Score |
|---|---|---|
| LED current | Up to 200 mA, 8-bit. Sufficient for Medle (50 mA) and most clinical probes | PASS |
| Probe diagnostics | **NO optical probe diagnostics.** ECG lead-off detection only (AC/DC, 12.5-100 nA). No LED open/short, no PD open/short, no cable on/off detection | FAIL |
| Transmissive topology | Common-anode LED drivers (current sink). **Cannot drive back-to-back LEDs** (standard Nellcor 2-wire probes). Would require external H-Bridge circuit or custom 3+ wire probes. PD inputs designed for on-board/short-cable use. DSBGA package (2.6x2.1 mm) limits routing for clinical PCB | FAIL |
| Pre-TIA ambient cancellation | +-126 uA at TIA input, per-phase, programmable. Substantial improvement over AFE4490. Adequate for moderate phototherapy scenarios | PASS |
| Regulatory positioning | "IEC 60601 Test report available on request" listed in features. Positioned for medical (PPG+ECG). TI markets it for SpO2 | PARTIAL |
| Availability / price | ACTIVE. ~$4.10 @ 3ku (DigiKey TR). Significantly cheaper than AFE4490 (~$20) | PASS |
| Migration cost | Major: new register map, no H-Bridge (PCB redesign for external bridge or custom probe), library rewrite, HGAC simplification (pre-TIA cancellation absorbs F2/F4). ECG chain is bonus for IncuNest | HIGH |

**Verdict: NOT directly suitable.** The missing H-Bridge and absence of optical probe diagnostics are disqualifying for drop-in replacement with standard clinical probes. Could work with external H-Bridge + external probe diagnostics circuit, but this adds PCB complexity and cost, partially negating the advantage of a more modern AFE.

### 4.3 Candidate B: TI AFE4950

| Criterion | Assessment | Score |
|---|---|---|
| LED current | 25-250 mA range, 8-bit. Best in class for LED drive capability | PASS |
| Probe diagnostics | **NO optical probe diagnostics.** ECG lead-off only (AC/DC, 2.9-92.5 nA). Same gap as AFE4900 | FAIL |
| Transmissive topology | Common-anode drivers. Same H-Bridge limitation as AFE4900. 8 LED outputs / 4 PD inputs offer flexibility but no 2-wire probe support. DSBGA-36 (2.6x2.5 mm) | FAIL |
| Pre-TIA ambient cancellation | Dual DAC: 256 uA ambient + 64 uA LED offset, 8-bit each. Best ambient cancellation in TI medical family. Sufficient for phototherapy | PASS |
| Regulatory positioning | Medical positioning (PPG+BioZ+ECG). No explicit IEC 60601 mention found in public docs | PARTIAL |
| Availability / price | ACTIVE. EVM: $299. IC price not found in public sources; likely higher than AFE4900 due to higher integration | UNKNOWN |
| Migration cost | Very high: same H-Bridge gap as AFE4900, plus more complex register map (8 LEDs, 4 PDs, BioZ). Library rewrite. BioZ chain unused for IncuNest | VERY HIGH |

**Verdict: NOT suitable.** Same fundamental H-Bridge gap as AFE4900, with higher complexity. The dual-DAC ambient cancellation is impressive but does not compensate for the probe compatibility problem. Overkill for a 2-LED transmissive pulse oximeter.

### 4.4 Candidate C: ADI ADPD4100 / ADPD4101

| Criterion | Assessment | Score |
|---|---|---|
| LED current | Up to 200 mA per driver (current sink), up to 400 mA combined per time slot. Sufficient | PASS |
| Probe diagnostics | No documented LED/PD open/short diagnostics for optical path. Designed for integrated sensors | FAIL |
| Transmissive topology | Current sink drivers (no H-Bridge). However, TI E2E and ADI documentation mention clinical use with "long wires" and reverse-biased protection diode for cable-connected probes. 8 LED outputs, 8 PD inputs. Larger package LFCSP (3.5x4.6 mm) more PCB-friendly than DSBGA | PARTIAL |
| Pre-TIA ambient cancellation | Analog ambient rejection before ADC ("ADC saturation level applies to pulsed signal only, because ambient signal is rejected prior to ADC conversion"). Effective for moderate ambient | PASS |
| Regulatory positioning | Not explicitly medical. ADI markets it for wearables and general optical sensing. No IEC 60601 mention | FAIL |
| Availability / price | ACTIVE. Widely available (DigiKey, Mouser). Price comparable to AFE4900 range | PASS |
| Migration cost | Complete rewrite: different vendor, different register architecture, different driver ecosystem. No H-Bridge. Would need external probe interface | VERY HIGH |

**Verdict: NOT suitable for IncuNest.** No H-Bridge, no probe diagnostics, no medical positioning. The high LED current and ambient rejection are good, but the migration cost is prohibitive for no clear advantage over AFE4900.

### 4.5 Candidate D: ADI MAX86171

| Criterion | Assessment | Score |
|---|---|---|
| LED current | 3 high-current 8-bit LED drivers, 9 LED output pins. Max current not confirmed in public docs but designed for high-current PPG applications | LIKELY PASS |
| Probe diagnostics | No documented optical probe diagnostics | FAIL |
| Transmissive topology | Current sink drivers. 2 PD inputs with independent 19.5-bit ADCs. Designed for PoC and pulse oximetry applications. No H-Bridge | FAIL |
| Pre-TIA ambient cancellation | Analog ALC (sample-and-hold), cancels up to 200 uA DC photocurrent | PASS |
| Regulatory positioning | Mentioned for pulse oximetry and PoC (point-of-care) fluorescence. ADI (formerly Maxim) has medical device heritage | PARTIAL |
| Availability / price | ACTIVE | PASS |
| Migration cost | Complete rewrite: different vendor, different architecture. Only 2 PD inputs (sufficient for SpO2) | VERY HIGH |

**Verdict: NOT suitable.** Same H-Bridge gap. Interesting for PoC applications but no advantage over TI options for IncuNest's specific use case.

## 5. Critical Finding: The H-Bridge Problem

The most significant finding of this study is that **no modern AFE from any vendor (TI, ADI/Maxim) includes an H-Bridge LED driver**. This feature exists only in the older TI clinical family (AFE4490, AFE4400, AFE4403).

### 5.1 Why H-Bridge Matters

Standard clinical pulse oximetry probes (Nellcor DB9, Masimo LNCS, and compatible) use **back-to-back (anti-parallel) LEDs** connected with **2 wires**:

```
Wire A ──┬── IR LED (anode) ──┬── Wire B
         └── RED LED (cathode)─┘
```

- Current A->B lights IR, current B->A lights RED.
- The H-Bridge driver reverses polarity to select which LED is active.
- This 2-wire scheme is the universal standard for clinical transmissive probes across all manufacturers.

Without H-Bridge, driving these probes requires:
1. **External H-Bridge circuit** on PCB (4 MOSFETs + driver logic), adding BOM cost, board area, and design complexity; OR
2. **Custom probes** with separate LED connections (3+ wires), abandoning compatibility with standard multi-manufacturer clinical probes, which is an **exclusionary requirement** for IncuNest.

### 5.2 Why TI Dropped H-Bridge

The market shift from clinical bedside monitors (transmissive, 2-wire probes) to wearable devices (reflective, on-PCB LEDs) eliminated the need for H-Bridge drivers. Modern AFEs optimize for:
- Common-anode configuration (simpler, lower power)
- Multiple LED wavelengths (3-8 LEDs, each with its own pin)
- On-board or short-flex PD connections
- Ultra-small packages (DSBGA, <3 mm)

TI has not released a new clinical-grade transmissive AFE since the AFE4490 (2012). The AFE4900/4950, while medically positioned, target wearable medical devices (patches, wristbands), not traditional bedside monitors with cable-connected probes.

## 6. Conclusions and Recommendations

### 6.1 No Drop-in Replacement Exists

None of the evaluated candidates can replace the AFE4490 as a drop-in solution for IncuNest's use case (clinical transmissive pulse oximetry with standard multi-manufacturer probes). The H-Bridge LED driver and integrated optical probe diagnostics are unique to the AFE4490 family.

### 6.2 AFE4490 Remains Viable

- **Status:** ACTIVE (TI has not announced NRND or EOL as of 2026-07-11).
- **Availability:** In stock at major distributors (DigiKey, Mouser).
- **Longevity risk:** Low in the medium term. TI maintains legacy medical parts for extended periods due to regulatory certification dependencies.
- **The AMBDAC limitation is real but manageable:** HGAC v1 (ILED+RF only, AMBDAC=0) is the correct strategy for the AFE4490; the pre-TIA cancellation of modern AFEs would simplify HGAC but is not available without losing H-Bridge.

### 6.3 If Migration Becomes Necessary

If the AFE4490 reaches EOL or the AMBDAC limitation proves critical in phototherapy scenarios, the recommended path is:

1. **AFE4900 + external H-Bridge** (best balance of medical positioning, pre-TIA +-126 uA, LED current, IEC 60601 report, price ~$4). The external H-Bridge adds ~$1-2 BOM and ~30 mm2 PCB area but preserves standard probe compatibility.
2. **Add external probe diagnostics** (comparator-based LED/PD fault detection, similar to what the AFE4490 does internally).
3. **Library rewrite** would be substantial but the HGAC solver would simplify significantly (pre-TIA cancellation absorbs failure modes F2/F4 from `project_agc_design.md`).

### 6.4 Relationship to HGAC

This study does NOT block HGAC development. HGAC proceeds on the AFE4490. If a future migration to AFE4900 occurs, the HGAC solver would need adaptation but the core objectives (O1-O10) remain valid; the pre-TIA cancellation would make several objectives easier to achieve.

### 6.5 Phototherapy Mitigation (Current Platform)

For the AFE4490, the neonatal phototherapy scenario should be addressed by:
- Optical shielding of the probe (standard clinical practice)
- HGAC awareness of ambient saturation via RSQM flags
- Accepting reduced RF (and thus reduced SNR) when ambient is high, as the only available electronic defense

---

## Appendix A: Data Sources

- [TI AFE4490 datasheet (SBAS602H)](https://www.ti.com/lit/ds/symlink/afe4490.pdf) - local copy: `docs/afe4490.pdf`
- [TI AFE4900 datasheet (SBAS861B)](https://www.ti.com/lit/ds/symlink/afe4900.pdf)
- [TI AFE4950 product page](https://www.ti.com/product/AFE4950)
- [ADI ADPD4100/4101 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/adpd4100-4101.pdf)
- [ADI MAX86171 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX86171.pdf)
- [DigiKey AFE4490 listing](https://www.digikey.com/en/products/detail/texas-instruments/AFE4490RHAT/3907577)
- [DigiKey AFE4900 listing](https://www.digikey.com/en/products/base-product/texas-instruments/296/AFE4900/10241)
- ISO 80601-2-61:2026 - local copy: `docs/ISO_80601-2-61-2026.pdf`
- `project_agc_design.md` section 3 (AMBDAC limitation analysis)
- `project_probe_dependent_specs.md` (Medle probe specifications)
