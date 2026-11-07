# Nomenclature

Rules and canonical names used across PulseNest: the `incunest_afe4490` library, the ESP32-S3
firmware, the `$M1`–`$M4` frames, the CSV captures, `pulsenest_lab.py`, the recorder and the IncuNest
Display_HMI. Until 2026-11-07 this dictionary lived only in an assistant memory file outside the
repository; this file is the authoritative copy. The authority on the **name of every field of
`AFE4490Data` and of every library parameter** is `incunest_afe4490_spec.md` in the library
repository (§2.1, §3, §5): this file does not repeat those lists, it records the rules, the ISO
80601-2-61 mapping and the terms that no identifier carries.

**Rule of maintenance (CLAUDE.md):** when a term is introduced or renamed, update this file in the
same commit.

## 1. Rules

1. **One source of authority per domain.** Hardware signals (chip ADC) follow the AFE4490
   datasheet register names. Derived signals carry a suffix naming the operation. Clinical output
   quantities follow ISO 80601-2-61 or the oximetry literature. Quality metrics carry an explicit
   project domain prefix.
2. **No domain mixing.** Raw ADC signals keep hardware names: never `ir`, `red`, `ambient` for a
   chip signal. The hardware to physiological crossing happens on entry to a clinical algorithm,
   where `led1_sub` / `led2_sub` become the local `ir` / `red`.
3. **No semantic collision.** One identifier, one meaning per scope. The mathematical constant pi is
   `kPi`; the perfusion index is `pi`.
4. **Operation suffixes for derived signals:** `_sub` (LED minus ambient), `_disp` (modified for
   display only), `_dc`, `_ac` (components inside an algorithm).
5. **`v_tia` is bare and always differential** (datasheet Eq. 2, 2·I_PD·RF; full scale 1.0 V,
   ideal operating point 0.6 V). No `_diff` / `_branch` suffix: the code holds no per-branch value.
   Threshold constants follow `<domain>_v_tia_<qualifier>` (`hgac_v_tia_thr`). CSV epochs: before
   2026-07-09 per-branch values (×0.5); 2026-07-09 to library v0.51 headers `V_TIA_DIFF_*`; from
   v0.52 headers `V_TIA_*`, same differential value.
6. **One canonical name per quantity.** Namespace prefixes (`spo2_r`, `hr1_sqi`) are allowed in C++
   for grouping.
7. **Same case per layer:** C++ and Python `snake_case` (`led1_sub`); frame labels `UPPER_SNAKE`
   (`LED1_SUB`); documentation canonical form plus unit (`led1_sub` · ADC counts).
8. **LED current as an actuator is `ILED1` / `ILED2`** in prose, tables and HGAC design (datasheet
   name). `led1` / `led2` are reserved for the raw ADC signals; `LEDmA`, `LED1Current` are
   deprecated. Existing code identifiers (`afe_led1_current_mA`) do not change.
9. **`R` and `r`.** Everything under `spo2_r_` is the ratio of ratios R. The regression correlation
   of R-METHOD-2 is `spo2_r_method2_reg_corr` (`$M4` field 36, CSV `R_METHOD2_REG_CORR`); never a
   bare `r_` that reads as R. Old names `R_CORR` / `spo2_r_corr_min` (fw 0.19 to 0.26) stay readable
   as synonyms in `capture_dict.py`. On screen it is still "r". Library rationale §16.

## 2. Signals

| Canonical | Layer | Meaning |
|---|---|---|
| `led1`, `led2`, `aled1`, `aled2` | chip (LED1VAL, LED2VAL, ALED1VAL, ALED2VAL) | IR, RED and the ambient sample after each, raw ADC counts |
| `led1_sub`, `led2_sub` | derived | LED minus ambient; the input of every physiological algorithm and of HGAC |
| `ppg_disp` | derived | display only: `-BPF(ot_led1)`; its scaling modes in §4 |
| `ir`, `red`, `dc_*`, `ac_*` | algorithm-local | physiological names, never outside an algorithm |
| `ot_led1`, `ot_led2` | `AFE4490AnalogState` | optical transmittance per channel, `(i_pd_led - i_pd_aled) / ILED` [A/A]: the electro-optical ratio of the whole chain (LED efficiency × tissue × photodiode), not tissue transmittance alone |
| `ILED1`, `ILED2`, `RF`, `RG`, `AMBDAC` | chip actuators | LED currents, TIA feedback resistance, stage-2 gain, ambient cancellation DAC |

## 3. Clinical quantities and ISO 80601-2-61

| Canonical | C++ | ISO 80601-2-61:2026 | Notes |
|---|---|---|---|
| `SpO2` | `spo2` | 201.3.261 | functional oxygen saturation [%] |
| `R` | `spo2_r` | 201.3.239 "modulation ratio / ratio of ratios" | SpO2 derives from R through an empirical calibration curve (`R-CURVE-*` labels) |
| `pi` | `pi` | not defined; manufacturer term (Masimo) | AC/DC × 100 on IR, peak-to-peak since v0.101. ISO's official equivalent is `%mod`, 201.3.245 "percent modulation"; `pi` is its implementation, there is no separate field |
| `HR1`, `HR2`, `HR3` | `hr1`.. | not defined | pulse rate by peak detection, autocorrelation, FFT+HPS. ISO and the manufacturers call a PPG-derived rate *pulse rate* (PR); the HR/PR label decision is parked (2026-11-02) |
| `rsqi` | `rsqi` | Table GG.1 "signal quality indicator" | 0 invalid, 1 valid |
| `DiagCode` | `diag_code` | 201.12.4.102 "signal inadequacy" | bitmask; `RSQM_DIAG_*` bits symmetric with `AFE_DIAG_*` |
| `ProbeState` | `probe_state` | 201.13.101 "probe fault"; Table GG.3 "probe not detected" | five states, values fixed on the wire (`$M2` to `$M4`, CSV): see the library spec §3 |
| `SpO2HoldReason` | `spo2_hold_reason` | not defined | why `spo2` is NaN; `HOLD_*` constants (v0.113) |

## 4. Display of the plethysmographic waveform

| Term | Source | Definition | In the project |
|---|---|---|---|
| `normalized` | ISO 80601-2-61 201.3.241 | "displayed at constant pulse amplitude independent of the actual pulse magnitude of the signal being displayed" | mode `NORM` of `AFE4490PPGDispMode` (library v0.116). **In prose: "vertically scaled"**: the waveform's shape does not change, only the Y gain; "normalized" is kept for traceability to the standard, since in signal processing it suggests removing the mean and dividing by sigma. `NORM_PI` is a hybrid that 201.3.241 does not quite cover: the maximum amplitude A depends on the perfusion index. Its justification is 201.12.4.102 note 3: a non-normalized waveform works as a signal-inadequacy indicator for %mod, "a normalized waveform by itself does not satisfy this requirement and can mask an unreliable signal". `NO_NORM` is the unscaled mode: ppm of `ot_led1` after the band-pass, inverted so the pulse rises (named `OT_AC` in the drafts until 2026-11-07; Alex: the incubator user need not know what OT or AC are, and NO_NORM names the feature the selector modifies) |
| `frame`, `SLEW`, `headroom` | this project (library v0.116, spec §5.9; rationale §21.5, §21.8) | the amplitude tracker of the scaled modes keeps a *frame* [lo, hi] around the waveform; *SLEW* names the tracker (slew-limited rise, exponential fall); *headroom* H maps the frame's extrema to ±1/H | `PPGDispTracker`, `ppgdisp_norm_rise_per_s` / `_win_s` / `_tau_s` / `_headroom`. In prose: "frame" (not "envelope", which the PI literature uses for something else), "rise" and "fall" (not attack/release, the audio terms) |
| `sweep speed` | manufacturers (Philips, Nellcor, Masimo); inherited from ECG paper at 25 mm/s, where 1 mm = 40 ms | horizontal advance of the trace [mm/s] | **ISO 80601-2-61 does not define the horizontal axis** (no "sweep", "mm/s" or "time base" anywhere in the standard; checked 2026-11-07): 25 mm/s is clinical convention, not a requirement (12.5 and 50 optional). The IncuNest HMI today draws 17.3 mm/s (128 points over 460 px at 5.2 px/mm, 25 Hz). Control "sweep (mm/s)" of PPGDISPLAB; library rationale §21.7 |

## 5. Algorithm vocabulary

| Term | Meaning |
|---|---|
| `ACF` | autocorrelation function; HR2 is `HR2_ACF` |
| `NSDF`, `MPM` | normalised square difference function; McLeod pitch method, minimises NSDF with a *clarity* metric (planned) |
| `CMND`, `YIN` | cumulative mean normalized difference; YIN (not an acronym, de Cheveigné and Kawahara 2002) takes its minimum (planned). Grep `\bACF\b`: `setTIACF` matches by substring |
| `HPS` | harmonic product spectrum, fundamental × 2nd × 3rd harmonic over the FFT; used by HR3 |
| double-counting | the dicrotic notch and the diastolic wave counted as a beat: pulse rate doubled, which can mask a bradycardia (60 counted as 120). The refractory period protects less the slower the rhythm |
| missed beat | a beat not detected: fakes a bradycardia, but produces out-of-range intervals and is easier to catch |
| dicrotic notch | notch on the falling edge from aortic valve closure; more marked and closer to the peak in neonates; what HR1's low-pass must attenuate |
| refractory period | blind window after an accepted beat (`hr1_refractory_s`); the current guard against double-counting |
| `reg_ols`, `reg_tls`, `reg_dols` | offline R estimators (`r_regression_test.py`): ordinary least squares red on IR through the origin; total least squares (principal axis); OLS on first differences. `reg_dols` is R-METHOD-2 in the library. Working labels, not literature terms |
| AMBDAC post-TIA limitation | in the AFE4490 ambient cancellation is injected after the TIA, so it does not protect the TIA's dynamic range: intense ambient light saturates it whatever the AMBDAC does (fixed pre-TIA from the AFE4404). `docs/afe_replacement_study.md` |

## 6. Field vocabulary (captures)

| Term | Definition |
|---|---|
| session | one start/stop interval of `pulsenest_recorder_gui.py` with **at most one subject**. Folder `captures/sessions/<SUBJ>/<SUBJ>_<SITE>_<YYYYMMDD>_<HHMMSS>/`, `session.toml` = the launch file. Simultaneous subjects are separate sessions in separate recorder instances (each has its own board, probe, reference oximeter and VideoNest phone). Older flat ids `<YYYYMMDD>_<HHMMSS>_<SITE>[_<SUBJECT>]` are still read by the converter |
| campaign | the sessions of **one subject** at one site on one day, `<YYYYMMDD>_<SITE>_<SUBJECT>`; derived from the session ids, no file of its own. 2026-09-23 at HOSPNAV was two campaigns (SUBJ08, SUBJ09), not one. `pulsenest_recorder_spec.md` §3 |
| `SUBJnn`, `<SITE>` | subject code and site tag. The subject code list is confidential and lives outside the repository |
