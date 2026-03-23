# mow_afe4490 — Specification v0.7

Medical Open World proprietary library for the AFE4490 chip (PPG/SpO2 pulse oximeter).
Designed for ESP32-S3 with Arduino + FreeRTOS. Phase 2 of the AFE4490 test project.
Coexists with `protocentral-afe4490-arduino` for behavioral comparison.

---

## 1. Internal architecture

### 1.1 DRDY management
The AFE4490 DRDY pin is managed **internally** by the library via ISR + FreeRTOS semaphore. The user does not need to handle interrupts.

```
AFE4490 chip (DRDY pin)
    │
    ▼
ISR → xSemaphoreGiveFromISR()
    │
    ▼
afe4490_task (internal)
    ├── reads SPI → 6 raw signals
    ├── processes PPG signal (bandpass filter)
    ├── computes HR (peak detection)
    ├── computes SpO2 (AC/DC ratio)
    └── xQueueSend() → FreeRTOS queue
    │
    ▼
sensors_Task (user)
    └── afe.getData(data)  ← reads from queue
```

### 1.2 Internal signals
The AFE4490 produces 6 signals per sample. All are read internally:

| Signal       | Description                              |
|--------------|------------------------------------------|
| LED1VAL      | IR raw                                   |
| LED2VAL      | RED raw                                  |
| ALED1VAL     | Ambient after LED1                       |
| ALED2VAL     | Ambient after LED2                       |
| LED1-ALED1   | IR ambient-corrected ← default           |
| LED2-ALED2   | RED ambient-corrected                    |

### 1.3 Processing chain
```
6 raw signals
    │
    ├─→ selected channel (setPPGChannel)
    │       └─→ bandpass filter (setFilter) → ppg + HR
    │
    └─→ LED1-ALED1 (IR corr.) + LED2-ALED2 (RED corr.) → AC/DC → SpO2
```

---

## 2. Public API

### 2.1 Data struct
```cpp
struct AFE4490Data {
    // Processed outputs
    int32_t ppg;        // filtered PPG of selected channel
    float   spo2;       // SpO2 in %
    float   spo2_r;     // R ratio: (AC_red/DC_red)/(AC_ir/DC_ir) — for calibration
    float   hr1;        // HR1 (peak detection) in bpm
    bool    spo2_valid; // true if SpO2 calculation is reliable
    bool    hr1_valid;  // true if HR1 calculation is reliable
    // The 6 raw signals from AFE4490
    int32_t led1;       // LED1VAL  — IR raw
    int32_t led2;       // LED2VAL  — RED raw
    int32_t aled1;      // ALED1VAL — ambient after LED1
    int32_t aled2;      // ALED2VAL — ambient after LED2
    int32_t led1_aled1; // LED1-ALED1 — IR ambient-corrected
    int32_t led2_aled2; // LED2-ALED2 — RED ambient-corrected
};
```

### 2.2 Initialization
```cpp
void begin(int pin_cs, int pin_drdy);
```
Initializes SPI, configures the chip with default values, attaches ISR to DRDY, and starts the internal FreeRTOS task.

**Default values after begin():**

| Parameter      | Default value                  |
|----------------|-------------------------------|
| Sample rate    | 500 Hz                        |
| LED1 current   | 11.7 mA                       |
| LED2 current   | 11.7 mA                       |
| LED range      | 150 mA (TX_REF = 0.75V)       |
| TIA gain (RF)  | 500 kΩ                        |
| TIA CF         | 5 pF                          |
| Stage 2 gain   | disabled                      |
| ENSEPGAIN      | 0 (single gain)               |
| NUMAV          | 7 (8 averages, max 9 at 500Hz)|
| PPG channel    | LED1_ALED1                    |
| Filter         | BUTTERWORTH, 0.5–20 Hz        |

### 2.3 Chip configuration
```cpp
void setSampleRate(uint16_t hz);        // valid range: 63–5000 Hz. Updates PRF and recalculates NUMAV_max.
void setNumAverages(uint8_t num);       // num = number of samples to average: 1 (no averaging) .. NUMAV_max+1
                                        // NUMAV_max = floor(5000 / PRF) - 1  (e.g.: PRF=500Hz → max=9 → up to 10 samples)
                                        // Absolute hardware limit: 16 samples (NUMAV=15)
                                        // If num > NUMAV_max for current PRF, clamped and logE emitted
void setLED1Current(float mA);          // depends on setLEDRange()
void setLED2Current(float mA);          // depends on setLEDRange()
void setLEDRange(uint8_t mA);           // 75 or 150 mA (with TX_REF=0.75V default)
void setTIAGain(AFE4490TIAGain gain);
void setTIACF(AFE4490TIACF cf);
void setStage2Gain(AFE4490Stage2Gain gain);
```

### 2.4 Signal and filter configuration
```cpp
void setPPGChannel(AFE4490Channel channel);
void setFilter(AFE4490Filter type, float f_low_hz = 0.5f, float f_high_hz = 20.0f);
```

### 2.5 Data retrieval
```cpp
bool getData(AFE4490Data& data);
// Returns true and fills data if an item is available in the queue.
// Returns false immediately if the queue is empty (non-blocking).
```

### 2.6 Shutdown
```cpp
void stop();
```
Cleanly shuts down the library:
1. Detaches the DRDY interrupt.
2. Waits for any in-progress SPI transaction to finish (acquires `_cfg_mutex`).
3. Deletes the internal FreeRTOS task.
4. Deletes the FreeRTOS queue, semaphore, and mutex.
5. Resets all algorithm state (SpO2, HR, filter).
6. Sets `_initialized = false`.

After `stop()`, `begin()` can be called again to restart from a clean state. Configuration (sample rate, LED current, filter, etc.) is preserved across `stop()`/`begin()` cycles.

**Typical use:** hot-swap between mow_afe4490 and protocentral at runtime without recompiling.

---

## 3. Enumerations

```cpp
enum class AFE4490Channel {
    LED1,        // IR raw
    LED2,        // RED raw
    ALED1,       // ambient after LED1
    ALED2,       // ambient after LED2
    LED1_ALED1,  // IR ambient-corrected (default)
    LED2_ALED2   // RED ambient-corrected
};

enum class AFE4490Filter {
    NONE,
    MOVING_AVERAGE,
    BUTTERWORTH
};

enum class AFE4490TIAGain {
    RF_10K,
    RF_25K,
    RF_50K,
    RF_100K,
    RF_250K,
    RF_500K,   // default
    RF_1M
};

enum class AFE4490TIACF {
    CF_5P,     // 5 pF (default)
    CF_10P,
    CF_20P,
    CF_30P,
    CF_55P,
    CF_155P,
    // any combination supported by register CF_LED[4:0]
};

enum class AFE4490Stage2Gain {
    GAIN_0DB,    // default (stage 2 disabled)
    GAIN_3_5DB,
    GAIN_6DB,
    GAIN_9_5DB,
    GAIN_12DB
};
```

---

## 4. Compile-time parameters

Overridable in `mow_afe4490.h` before compilation:

```cpp
#define MOW_AFE4490_QUEUE_SIZE      10   // number of samples in the FreeRTOS queue
#define MOW_AFE4490_TASK_PRIORITY   5    // internal task priority
```

**Full queue behaviour:** oldest item is discarded to always keep the most recent sample.

---

## 5. Algorithms

### 5.1 SpO2
Based on the ratio R of the AC and DC components of the ambient-corrected signals:

```
R = (AC_RED / DC_RED) / (AC_IR / DC_IR)

SpO2 = a - b × R
```

Coefficients `a` and `b` are empirical (calibration). Configurable via `setSpO2Coefficients()`.
`spo2_valid` is set when enough stable samples are available for the calculation.

### 5.2 HR
Peak detection on the filtered PPG signal (bandpass 0.5–20 Hz).
HR is calculated by measuring the interval between consecutive peaks (RR interval):

```
HR (bpm) = 60 / T_RR (seconds)
```

`hr1_valid` is set when enough consecutive peaks with a stable interval have been detected.

> Both algorithms developed from scratch. Protocentral code is not used as a base.

---

## 6. Hardware interface (SPI)

| Parameter   | Value                           | Source      |
|-------------|----------------------------------|-------------|
| Speed       | 2 MHz                           | Protocentral|
| Mode        | SPI_MODE0                       | Protocentral|
| Bit order   | MSBFIRST                        | Protocentral|
| Frame       | 1 address byte + 3 data bytes   | Datasheet   |

---

## 7. Constraints and rules

- **Never use `delay()`** — use `vTaskDelay()` with `pdMS_TO_TICKS()`
- **Thread-safe** — shared resources protected with mutex
- **SPI errors** — always check communication results
- **Medical device** — reliability is priority 1
- **Timing registers** — calculated automatically by the library from `setSampleRate()`. Not exposed to the user.
- **This spec must be updated** with any design change to the library, so that it can always regenerate the corresponding version

---

### 9.5 ADC Averaging — formula and constraints

Source: AFE4490 datasheet section 8.4.1, Equation 5.

Each ADC conversion phase has 25% of the repetition period (PRP). Each individual conversion takes 50µs. The maximum number of averages is limited by how many conversions fit in that window:

```
NUMAV_max = floor( (0.25 × PRP) / 50µs ) − 1
           = floor( 5000 / PRF ) − 1
```

| PRF (Hz) | PRP (µs) | 25% window (µs) | Max averages | Max NUMAV |
|---|---|---|---|---|
| 500 | 2000 | 500 | **10** | **9** |
| 625 | 1600 | 400 | 8 | 7 |
| 1000 | 1000 | 250 | 5 | 4 |
| 1250 | 800 | 200 | 4 | 3 |
| 2000 | 500 | 125 | 2 | 1 |
| 2500 | 400 | 100 | 2 | 1 |
| 5000 | 200 | 50 | 1 | 0 |

**Absolute hardware limit:** NUMAV ≤ 15. Any value ≥ 15 behaves as 16 averages. This limit is only relevant at very low PRF (< 313 Hz).

**`setNumAverages(uint8_t num)` behaviour:**
- `num` is the number of samples to average (1 = no averaging, equivalent to NUMAV=0).
- The library computes internally `NUMAV = num − 1`.
- If `num > NUMAV_max + 1` for the current PRF: clamped to the maximum and `logE` emitted with the actual applied value.
- If `num == 0`: treated as `num = 1` (no averaging).
- `setSampleRate()` recalculates NUMAV_max; if the configured NUMAV exceeds the new maximum, it is automatically clamped and `logE` is emitted.

**Effect on SNR:**
```
SNR_improvement = sqrt(num)    →  num=8: ×2.83,  num=10: ×3.16
```

**Default:** `num = 8` (NUMAV=7). Balance between SNR and latency at 500Hz.

---

## 8. Version history

| Version | Description                                                                 |
|---------|-----------------------------------------------------------------------------|
| v0.1    | Initial complete specification                                              |
| v0.2    | Added section 9 with comparative register tables (timing, analog, control, |
|         | init sequence). Sources: AFE44x0.h EVM TI v1.4, Datasheet AFE4490 Table 2,|
|         | Protocentral src/. mow_afe4490 values justified register by register.      |
|         | Updated defaults: NUMAV=7, ENSEPGAIN=0, Stage2 disabled.                   |
| v0.3    | Configurable NUMAV: added `setNumAverages(uint8_t num)` to the API.        |
|         | Section 9.5 with NUMAV_max formula, table by PRF, clamping behaviour and   |
|         | SNR effect. `setSampleRate()` recalculates NUMAV_max.                      |
|         | **First implementation:** `include/mow_afe4490.h` and                      |
|         | `src/mow_afe4490.cpp` generated. Pending hardware validation.              |
| v0.4    | `AFE4490Data` extended with the 6 raw AFE4490 signals (led1, led2,         |
|         | aled1, aled2, led1_aled1, led2_aled2). Struct is now equivalent in         |
|         | information to the protocentral output.                                    |
| v0.5    | Internal constants reorganised at the top of the anonymous namespace in    |
|         | `.cpp`, in snake_case. Algorithm time parameters expressed in physical      |
|         | units (seconds): `spo2_warmup_s`, `dc_iir_tau_s`, `ac_ema_tau_s`,         |
|         | `hr_refractory_s`. New members `_spo2_warmup_samples`,                     |
|         | `_hr_refractory_samples`, `_dc_iir_alpha`, `_ac_ema_beta` derived from     |
|         | `_sample_rate_hz` via `_recalc_rate_params()`, called in constructor and   |
|         | in `setSampleRate()`. SpO2 and HR algorithms now correct at any PRF.       |
| v0.6    | Biquad coefficients computed dynamically (`_recalc_biquad()`). Formula:    |
|         | bilinear transform on a 2nd-order Butterworth bandpass prototype.          |
|         | Coefficients moved from namespace constants to members `_bq_b0..a2`.       |
|         | Called from `_recalc_rate_params()` and `setFilter()`. The "not yet        |
|         | implemented" warning removed. `setFilter()` is now fully functional for    |
|         | any fs, f_low, f_high.                                                     |
| v0.7    | Added `stop()` (section 2.6): clean shutdown — detaches ISR, deletes       |
|         | internal task and FreeRTOS objects, resets algorithm state. Allows          |
|         | `begin()` to be called again. Added `_reset_algorithms()` (private).       |
|         | Enables hot-swap between mow_afe4490 and protocentral at runtime.          |

---

## 9. AFE4490 chip register configuration

This section documents the exact value of each AFE4490 register written by the library during initialisation, compared against the three reference sources analysed.

**Reference sources:**
- **AFE44x0.h (EVM TI v1.4):** TI official firmware for the AFE4490EVM evaluation kit. Written for MSP430. The C code is not reusable, but the register values and timing formulas are TI's authoritative reference.
- **Datasheet AFE4490 Table 2:** example values from the datasheet for PRF=500Hz, duty cycle=25%.
- **Protocentral (src/):** `src/protocentral_afe44xx.cpp` from the project — modified version of the Protocentral library adapted to the project.

---

### 9.1 Timing registers (PRF = 500 Hz, AFECLK = 4 MHz, 1 count = 0.25 µs)

| Register | AFE44x0.h (PRF=500) | Datasheet Table 2 | Protocentral (src/) | **mow_afe4490** | **Rationale** |
|---|---|---|---|---|---|
| PRPCOUNT | 7999 | 7999 (t29) | 7999 | **7999** | PRF=500Hz: (4,000,000/500)−1=7999 |
| LED2LEDSTC | 6000 | 6000 (t3) | 6000 | **6000** | LED2 starts exactly at the beginning of its phase (75% of period) |
| LED2LEDENDC | 7599 | 7999 (t4) | 7999 | **7999** | 25% duty cycle: 2000 counts = 500µs → maximises photons |
| LED2STC | 6080 | 6050 (t1) | 6000 | **6050** | 50 counts (12.5µs) margin for TIA settling. TI EVM uses 80 (excessive at 500Hz); Protocentral uses 0 (risky) |
| LED2ENDC | 7598 | 7998 (t2) | 7998 | **7998** | Closes 2 counts before end of phase |
| ALED2STC | 80 | 50 (t5) | 0 | **50** | Same 50-count margin for consistency with LED phases |
| ALED2ENDC | 1598 | 1998 (t6) | 1998 | **1998** | Uses full window except last 2 counts |
| LED1LEDSTC | 2000 | 2000 (t9) | 2000 | **2000** | LED1 starts at beginning of its phase (25% of period) |
| LED1LEDENDC | 3599 | 3999 (t10) | 3999 | **3999** | 25% duty cycle, same as LED2 |
| LED1STC | 2080 | 2050 (t7) | 2000 | **2050** | Same criterion as LED2STC: 50-count margin |
| LED1ENDC | 3598 | 3998 (t8) | 3998 | **3998** | Same as LED2ENDC |
| ALED1STC | 4080 | 4050 (t11) | 4000 | **4050** | Same criterion |
| ALED1ENDC | 5598 | 5998 (t12) | 5998 | **5998** | Same as ALED2ENDC |
| LED2CONVST | 7 | 4 (t13) | 2 | **4** | 1 count after ADC reset end (end=3). Required: "Must start one AFE clock cycle after the ADC reset pulse ends" |
| LED2CONVEND | 2000 | 1999 (t14) | 1999 | **1999** | 1 count before next reset (ADCRSTSTCT1=2000) |
| ALED2CONVST | 2007 | 2004 (t15) | 2002 | **2004** | 1 count after ADCRSTENDCT1=2003 |
| ALED2CONVEND | 4000 | 3999 (t16) | 3999 | **3999** | 1 count before ADCRSTSTCT2=4000 |
| LED1CONVST | 4007 | 4004 (t17) | 4002 | **4004** | 1 count after ADCRSTENDCT2=4003 |
| LED1CONVEND | 6000 | 5999 (t18) | 5999 | **5999** | 1 count before ADCRSTSTCT3=6000 |
| ALED1CONVST | 6007 | 6004 (t19) | 6002 | **6004** | 1 count after ADCRSTENDCT3=6003 |
| ALED1CONVEND | ⚠️ 8000 | 7999 (t20) | 7999 | **7999** | =PRPCOUNT. TI EVM formula overflows at 500Hz (designed for 100Hz) |
| ADCRSTSTCT0 | 0 | 0 (t21) | 0 | **0** | Start of period |
| ADCRSTENDCT0 | 5 | 3 (t22) | 0 | **3** | 3 counts = 0.75µs → −60 dB crosstalk. Protocentral uses 0 (unquantified risk). 6 counts would eliminate crosstalk entirely but unnecessary with hardware ambient cancellation |
| ADCRSTSTCT1 | 2000 | 2000 (t23) | 2000 | **2000** | Start of phase 2 |
| ADCRSTENDCT1 | 2005 | 2003 (t24) | 2000 | **2003** | ADCRSTSTCT1 + 3 counts |
| ADCRSTSTCT2 | 4000 | 4000 (t25) | 4000 | **4000** | Start of phase 3 |
| ADCRSTENDCT2 | 4005 | 4003 (t26) | 4000 | **4003** | ADCRSTSTCT2 + 3 counts |
| ADCRSTSTCT3 | 6000 | 6000 (t27) | 6000 | **6000** | Start of phase 4 |
| ADCRSTENDCT3 | 6005 | 6003 (t28) | 6000 | **6003** | ADCRSTSTCT3 + 3 counts |

**Notes on the Table 2 formula:**
- `PRPCOUNT = (AFECLK / PRF) − 1`
- 25% duty cycle: LED window = `(PRPCOUNT+1) / 4` counts
- TIA margin: 50 fixed counts regardless of PRF
- ADC reset: 3 fixed counts. For 6 counts (zero crosstalk), set CONVST to reset_end+1
- TI EVM formula uses 20% duty cycle and 80-count margin → **not valid at 500Hz** (ALED1CONVEND overflows)

---

### 9.2 Analog configuration

| Register / Field | AFE44x0.h (EVM) | Datasheet | Protocentral (src/) | **mow_afe4490** | **Rationale** |
|---|---|---|---|---|---|
| **TIAGAIN** | 0x00C006 | — | 0x000000 | **0x000000** | Minimal config: RF=500kΩ, CF=5pF, Stage2 off, ENSEPGAIN=0 |
| → ENSEPGAIN | 1 | — | 0 | **0** | With 0, both channels use TIAGAIN for the TIA. Simplifies configuration. Enable if independent gain per channel is needed |
| → Stage2 LED1 | EN, 0 dB | — | disabled | **disabled** | RF=500kΩ provides sufficient gain for typical PPG. Stage2 at 0dB adds no useful gain. Configurable via setter |
| → CF LED1 | 5 pF | — | 5 pF | **5 pF** | Datasheet minimum → maximum TIA bandwidth. Adjust if instability occurs |
| → RF LED1 | 1 MΩ | — | 500 kΩ | **500 kΩ** | Validated by Protocentral on real hardware. EVM's 1MΩ risks saturation. Configurable via setTIAGain() |
| **TIA_AMB_GAIN** | 0x004006 | — | 0x000001 | **0x000000** | With ENSEPGAIN=0, the RF of this register does not affect the main TIA. Relevant for FLTRCNRSEL, AMBDAC and Stage2 |
| → RF LED2/amb | 1 MΩ | — | 250 kΩ | **500 kΩ** | Ignored for TIA when ENSEPGAIN=0. Set equal to TIAGAIN to avoid surprises if ENSEPGAIN=1 is enabled later |
| → CF LED2/amb | 5 pF | — | 5 pF | **5 pF** | Same criterion as CF LED1 |
| → Stage2 LED2 | EN, 0 dB | — | disabled | **disabled** | Same criterion as Stage2 LED1 |
| → FLTRCNRSEL | 500 Hz | — | 500 Hz | **500 Hz** | Matches PRF. 1000 Hz option only makes sense if PRF is raised |
| → AMBDAC | 0 µA | — | 0 µA | **0 µA** | Ambient cancellation handled in hardware (LED1−ALED1VAL, LED2−ALED2VAL). AMBDAC only needed if ambient light saturates TIA before subtraction. Exposable via setter |
| **LEDCNTRL** | 0x011414 | — | 0x001414 | **0x001414** | RANGE_0 + code 20 + TX_REF=0.75V → 11.7mA per LED |
| → LED_RANGE | RANGE_1 | — | RANGE_0 | **RANGE_0** | Consistent with TX_REF=0.75V. FSR=150mA → resolution ~0.6mA/step |
| → LED1 code | 20 (0x14) | — | 20 (0x14) | **20 (0x14)** | 11.7mA: standard starting point for finger SpO2 validated by Protocentral. Configurable via setLEDCurrent() |
| → LED2 code | 20 (0x14) | — | 20 (0x14) | **20 (0x14)** | Same as LED1. In practice red and IR may need independent adjustment |
| → **Resulting current** | **≈3.9 mA** | — | **≈11.7 mA** | **≈11.7 mA** | EVM uses TX_REF=0.5V + RANGE_1 → 3.9mA; insufficient as a general default |
| **CONTROL2** | 0x020000 | — | 0x000000 | **0x000000** | All fields at reset value |
| → TX_REF | 0.5 V | 0.75 V (reset) | 0.75 V | **0.75 V** | Datasheet default. Supports up to 150mA with RANGE_0. EVM uses 0.5V due to its supply constraints |
| → PDN_AFE/RX/TX | all ON | — | all ON | **all ON** | Normal operating mode. PDN only for low-power use |
| → TXBRGMOD | H-bridge | — | H-bridge | **H-bridge** | Standard for 2-pin back-to-back LED |
| → XTAL | enabled | — | enabled | **enabled** | No crystal on in3ator but chip ignores it if not connected |
| → ADC_BYP | disabled | — | disabled | **disabled** | Normal mode; bypass only for chip testing |

---

### 9.3 Control registers

| Register / Field | AFE44x0.h (EVM) | Datasheet | Protocentral (src/) | **mow_afe4490** | **Rationale** |
|---|---|---|---|---|---|
| **CONTROL0** | 0x000000 | — | 0x000000→0x000008 | **0x000008 in init** | SW_RST ensures known state. Self-clearing. EVM does no explicit SW_RST — risk if chip was left in inconsistent state |
| **CONTROL1** | 0x000107 | — | 0x010707 | **0x000107** | TIMEREN=1, NUMAV=7, no outputs on ALM pins |
| → TIMEREN | 1 | — | 1 | **1** | Required for the internal timer to generate control signals |
| → NUMAV | 7 (8 avg.) | — | 7 (8 avg.) | **7** | Default = 8 averaged samples → SNR ×√8 ≈ 2.8×. Configurable via `setNumAverages()`. See NUMAV_max formula in section 9.5 |
| → CLKALMPIN | not config. | — | LED2_CONV\|LED1_CONV | **not config. (0x00)** | Protocentral outputs conversion signals on ALM pins (useful with oscilloscope). Unnecessary in production; may interfere with other uses of those pins on in3ator |
| → bit 16 | 0 | — | 1 ⚠️ | **0** | Not documented in AFE44x0.h or identified in datasheet. Protocentral enables it without apparent justification. Not replicated until its purpose is understood |
| **ALARM** | not config. | — | not config. | **not config.** | Not needed for basic operation. Will be added if chip diagnostics are implemented |

---

### 9.4 Initialisation sequence

| Step | AFE44x0.h (EVM) | Protocentral (src/) | **mow_afe4490** | **Rationale** |
|---|---|---|---|---|
| 1 | — | PDN low 500ms → PDN high 500ms | **PDN low 500ms → PDN high 500ms** | Hard reset before any SPI communication. 500ms is conservative but safe; datasheet does not specify minimum |
| 2 | CONTROL0=0x000000 | CONTROL0=0x000000 | **CONTROL0=0x000000** | Ensures SPI write mode (SPI_READ=0) |
| 3 | — | CONTROL0=0x000008 | **CONTROL0=0x000008 (SW_RST)** | Software reset complementary to hard reset |
| 4 | Timers first | TIAGAIN, TIA_AMB_GAIN, LEDCNTRL, CONTROL2 | **TIAGAIN, TIA_AMB_GAIN, LEDCNTRL, CONTROL2** | Analog front-end before enabling timers — avoids sampling with partial configuration |
| 5 | CONTROL1 (timer ON) | Timing registers | **Timing registers** | All timing registers before starting the timer |
| 6 | CONTROL0=SPI_READ | CONTROL1 (timer ON) | **CONTROL1 (timer ON — last)** | TIMEREN activated last when everything is configured |
| 7 | — | delay 1000ms | **delay 1000ms** | Stabilisation before first read. Protocentral value not justified in datasheet — possibly reducible, but safe for startup |
