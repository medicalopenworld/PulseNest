# pulsenest_lab — Specification v1.7

Python desktop application for real-time visualization, analysis, algorithm verification
and data capture of PPG/SpO2 signals from the AFE4490 via the `incunest_afe4490` firmware.

Part of the **PulseNest** project — Medical Open World.

---

## 1. Purpose and role

`pulsenest_lab.py` is the PC-side companion to the PulseNest firmware. It is not a utility
script — it is a first-class project deliverable with its own spec and versioning.

Responsibilities:
- Display real-time PPG/SpO2/HR signals received over USB serial or WiFi/UDP from the ESP32-S3.
- Run Python replicas of the firmware SpO2 and HR algorithms for independent verification.
- Provide tunable algorithm windows to explore parameter sensitivity.
- Support SpO2 probe calibration (R-ratio regression).
- Capture and export data to CSV for offline analysis.
- Display FreeRTOS timing stats (CPU budget per algorithm).
- Remote-control AFE4490 hardware parameters in real time ($SET/$CFG protocol).
- Execute parametric AFE sweeps and log results to CSV (AFE SWEEP TEST window).

---

## 2. Dependencies

| Package | Purpose |
|---------|---------|
| `PyQt5` | UI framework (widgets, layouts, signals/slots) |
| `pyqtgraph` | Fast real-time plotting (OpenGL-accelerated) |
| `numpy` | Signal buffers, FFT, autocorrelation |
| `scipy` | Butterworth filter design (`scipy.signal`), peak finding |
| `pyserial` | Serial port access |

Python ≥ 3.9. No PlatformIO or hardware required to run the script.

---

## 3. Configuration constants

Defined at module level, after imports.

| Constant | Value | Meaning |
|----------|-------|---------|
| `PORT` | `'COM15'` | Default serial port (overridable via UI combo) |
| `BAUD` | `921600` | Serial baud rate — must match firmware |
| `UDP_DEFAULT_PORT` | `5005` | Default UDP listen port — must match `wifi_config.h` |
| `SETTINGS_FILE` | `pulsenest_lab.ini` (same dir) | Qt QSettings persistence file |
| `CAPTURES_DIR` | `captures/` (same dir) | Output directory for all CSV captures; created at startup |
| `WINDOW_SIZE` | `500` | Rolling display buffer length (10 s @ 50 Hz) |
| `PPG_WINDOW_SIZE` | `500` | Same as WINDOW_SIZE (kept separate for clarity) |
| `SPO2_CAL_BUFSIZE` | `3000` | SpO2 calibration rolling buffer (60 s @ 50 Hz) |
| `SPO2_RECEIVED_FS` | `50.0` Hz | Effective sample rate after decimation (500 Hz / 10) |

---

## 4. Protocols

### 4.1 Transport layer

Two transports operate in parallel:

| Transport | Direction | Role |
|-----------|-----------|------|
| USB serial (921600 baud) | bidirectional | Data frames + command I/O; always used |
| UDP WiFi (default port 5005) | ESP32 → PC | High-speed data frames; toggled independently |

Only the **active transport** feeds the algorithm/display pipeline. Serial stays open
in both cases to receive `$CFG`/`$DIAG`/`$ERR` responses and to send `$SET`/`$CFG?`/`$DIAG?` commands.

**UDP first-packet activation:** `_active_transport` is NOT switched to `"udp"` when `_connect_udp()` is
called. It switches only when the first UDP datagram arrives (`_on_udp_active()` slot, main thread).
Until then the button shows `UDP WiFi ● LISTEN` and serial remains the active transport.
This prevents the app from appearing frozen when WiFi is not reachable but USB is connected.

| `btn_udp` state | `_active_transport` |
|---|---|
| OFF | `"serial"` |
| LISTEN (UDP thread running, no datagrams yet) | `"serial"` |
| ON (first datagram received) | `"udp"` |

Each transport has its own reader thread: `_serial_reader` and `_udp_reader`.
Both threads enqueue raw bytes into `_serial_queue` or `_udp_queue`. The processing loop
in `_process_frames_tick()` drains the **active** queue only.

### 4.2 Data frames ($M1, $M2)

All frames are ASCII lines terminated with `\r\n`. Fields are comma-separated.
Every frame ends with `*XX` where `XX` is the XOR checksum of the bytes between `$` and `*`.
Frames with bad checksum are silently discarded.

#### $M1 — Full data frame (default)

```
$M1,<SmpCnt>,<Ts_us>,<LED2>,<LED1>,<ALED2>,<ALED1>,<LED2_SUB>,<LED1_SUB>,
    <PPG_DISP>,<SpO2>,<SpO2_SQI>,<R>,<PI>,<HR1>,<HR1_SQI>,<HR2>,<HR2_SQI>,
    <HR3>,<HR3_SQI>,<RSQI>,<DiagCode>,<ProbeState>*XX
```

| Field | Type | Description |
|-------|------|-------------|
| `SmpCnt` | int | Sample counter (firmware, rolls over) |
| `Ts_us` | int | ESP32 timestamp in µs (`micros()`) |
| `LED2` | int32 | LED2VAL — RED raw ADC [counts] |
| `LED1` | int32 | LED1VAL — IR raw ADC [counts] |
| `ALED2` | int32 | ALED2VAL — ambient after RED LED [counts] |
| `ALED1` | int32 | ALED1VAL — ambient after IR LED [counts] |
| `LED2_SUB` | int32 | LED2 − ALED2 — RED ambient-corrected [counts] |
| `LED1_SUB` | int32 | LED1 − ALED1 — IR ambient-corrected [counts] |
| `PPG_DISP` | int32 | Display PPG: LED1_SUB → BPF → negated (display only) [counts] |
| `SpO2` | float | SpO2 [%] |
| `SpO2_SQI` | float | SpO2 Signal Quality Index [0–1] |
| `R` | float | Modulation ratio: (AC_red/DC_red)/(AC_ir/DC_ir) [dimensionless] |
| `PI` | float | Perfusion Index: AC_ir/DC_ir × 100 [%] |
| `HR1` | float | HR via peak detection [bpm] |
| `HR1_SQI` | float | HR1 SQI [0–1] |
| `HR2` | float | HR via autocorrelation [bpm] |
| `HR2_SQI` | float | HR2 SQI [0–1] |
| `HR3` | float | HR via FFT+HPS [bpm] |
| `HR3_SQI` | float | HR3 SQI [0–1] |
| `RSQI` | uint8 | Raw Signal Quality Index: 0=invalid, 1=valid |
| `DiagCode` | uint32 | Diagnostic bitmask (AFE hardware faults + RSQM flags) |
| `ProbeState` | int | 0=DISCONNECTED, 1=NOT_APPLIED, 2=APPLIED |

#### $M2 — Minimal frame (raw ADC only)

```
$M2,<cnt>,<LED2>,<LED1>,<ALED2>,<ALED1>,<LED2_SUB>,<LED1_SUB>*XX
```

Used when firmware is in `IncunestFrameMode::RAW`. No algorithm outputs.

### 4.3 Diagnostic and control frames

All sent by the script over **serial** (regardless of active transport).

#### $CFG? — Request current configuration

```
$CFG?*XX
```

Firmware responds with a `$CFG` frame (see §4.5).

#### $SET — Set a hardware parameter

```
$SET,<key>,<value>*XX
```

Firmware applies the change and responds with an updated `$CFG` frame to confirm.
On error the firmware responds with `$ERR,<reason>*XX`.

Parameters accepted by `$SET`:

| Key | Values | Description |
|-----|--------|-------------|
| `led1` | 0–255 | LED1 (IR) drive DAC code |
| `led2` | 0–255 | LED2 (RED) drive DAC code |
| `ledrange` | 75, 150 | LED current full-scale range (mA) |
| `ensepgain` | 0, 1 | Enable separate gain for LED1/LED2 TIA |
| `tiagain1` | 0–6 | LED1 TIA feedback resistor index (RF1) |
| `tiacf1` | 0–3 | LED1 TIA feedback capacitor index (CF1) |
| `stg21` | 0–4 | LED1 stage-2 gain index (RG1) |
| `stage2en1` | 0, 1 | Enable stage-2 for LED1 |
| `tiagain2` | 0–6 | LED2 TIA feedback resistor index (RF2) |
| `tiacf2` | 0–3 | LED2 TIA feedback capacitor index (CF2) |
| `stg22` | 0–4 | LED2 stage-2 gain index (RG2) |
| `stage2en2` | 0, 1 | Enable stage-2 for LED2 |
| `ambdac` | 0–10 | Ambient cancellation current (µA, 2 µA/step) |
| `sr` | timing | Sample rate register |
| `numav` | int | Number of averages |
| `t1`–`t28` | int | Raw AFE4490 timing registers |

#### $DIAG? — Request hardware diagnostic

```
$DIAG?*XX
```

Firmware runs the AFE4490 internal diagnostic test and responds with `$DIAG`.

### 4.4 Firmware response frames

All emitted by the firmware asynchronously.

#### $CFG — Configuration report

```
$CFG,led1=<v>,led2=<v>,range=<v>,tia1=<v>,cf1=<v>,stg21=<v>,stage2en1=<v>,
     tia2=<v>,cf2=<v>,stg22=<v>,stage2en2=<v>,ambdac=<v>,sr=<v>,numav=<v>,
     ensepgain=<v>*XX
```

Emitted at startup, after `$SET`, and in response to `$CFG?`. Parsed by
`_on_cfg_frame_received()` → populates `_last_cfg` dict and updates `HWConfigWindow`.

#### $LCFG — Library/algorithm parameter report

```
$LCFG,rsqm_ot_thr=<v>,rsqm_signal_weak_std=<v>,rsqm_disconn_led_sub_thr=<v>,
      rsqm_disconn_i_pd_thr=<v>,rsqm_probe_state_min_s=<v>,
      rsqm_ema_mean_tau_s=<v>,rsqm_ema_var_tau_s=<v>*XX
```

Emitted after a RSQM `$SET` command and in response to `$LCFG?`. Parsed by
`_on_lcfg_frame_received()` → updates `LIBConfigWindow`.

#### $TCFG — Raw timing registers

```
$TCFG,t1=<v>,...,t28=<v>*XX
```

Emitted alongside `$CFG` for timing-register changes. Parsed by `_on_tcfg_frame_received()`.

#### $DIAG — Diagnostic result

```
$DIAG,<raw_hex>*XX
```

32-bit diagnostic register. Parsed by `_on_diag_frame_received()` → updates `DiagnosticsWindow`.

#### $TIMING — Algorithm timing stats

```
$TIMING,<hr1_mean_us>,<hr1_max_us>,<hr2fp_mean_us>,<hr2fp_max_us>,
        <hr3fp_mean_us>,<hr3fp_max_us>,<spo2_mean_us>,<spo2_max_us>,
        <cycle_mean_us>,<cycle_max_us>,
        <hr2cmp_mean_us>,<hr2cmp_max_us>,<hr3cmp_mean_us>,<hr3cmp_max_us>,
        <stack_free>*XX
```

Emitted every ~5 s. Requires `INCUNEST_TIMING_STATS=1`.

#### $TASK — FreeRTOS task info

```
$TASK,<name>,<cpu_pct_x10>,<stack_words>*XX
```

One frame per task, after `$TIMING`. Sequence terminated by `$TASKS_END`.

#### $ERR — Error response

```
$ERR,<reason>*XX
```

Firmware rejected a `$SET` command. Logged to Serial Console and shown in `HWConfigWindow` status bar.

#### # lines — System messages

Lines starting with `#` are human-readable status messages from the firmware:
- `# SYS: ...` — startup info (chip, flash, heap)
- `# incunest_afe4490 started` — library started
- `# frame mode ...` — frame mode change

### 4.5 Checksum

XOR of all bytes between `$` and `*` (exclusive). Validated on every data frame.
Frames with bad checksum are silently discarded.

### 4.6 Per-frame integrity check: RED_Sub / IR_Sub

When parsing live M1 frames, the script verifies:
```
RED_Sub == RED − RED_Amb
IR_Sub  == IR  − IR_Amb
```
If a mismatch is found, it is logged to the Serial Console as `[CHK] SUB MISMATCH #N`.
First 5 mismatches are always logged; thereafter one every 100. Counter: `_sub_mismatch_count`.

### 4.7 Data flow

```
ESP32 SERIAL (921600 baud)          ESP32 UDP WiFi (port 5005)
      │                                        │
      ▼                                        ▼
_serial_reader thread                   _udp_reader thread
  readline() loop                         recvfrom() loop
  → _serial_queue (Queue)                 → _udp_queue (Queue)
      │                                        │
      └──────────────┬─────────────────────────┘
                     ▼  active transport only
            _process_frames_tick()  (QTimer ~20ms)
              drain queue
              parse frames → update deque buffers
              update algorithms (HR1TEST, HR2TEST, etc.)
                     │
                     ▼
            _render_timer tick (QTimer ~50ms)
              render plots in open subwindows
```

Two separate timers decouple data ingestion from rendering:
- `_process_frames_tick()`: runs at ~20 ms, drains the queue, updates all deque buffers,
  runs Python algorithm replicas (`HR1TestCalc`, `HR2TestCalc`, etc.).
- `_render_timer` tick: runs at ~50 ms, refreshes plots in all open subwindows using current buffers.

`_reader_thread` / `_udp_reader` run in daemon threads. They only read bytes and enqueue lines
— no parsing, no UI calls. This ensures no frames are dropped during slow rendering.

---

## 5. Algorithm classes

All classes are Python replicas of the firmware algorithms for independent verification.
They use the same constants as the firmware (matching `incunest_afe4490.cpp`).

### 5.1 SpO2LocalCalc

Replicates `INCUNEST_AFE4490::_update_spo2()`.

**Constants:**

| Name | Value | Description |
|------|-------|-------------|
| `_DC_IIR_TAU_S` | 1.6 s | DC IIR time constant |
| `_AC_EMA_TAU_S` | 1.0 s | AC² EMA time constant |
| `_SPO2_MIN_DC` | 1000 | Minimum DC level to report SpO2 |
| `_WARMUP_S` | 5.0 s | Warmup before reporting |
| `SPO2_A` | 114.9208 | Calibration coefficient (SpO2 = A − B·R) |
| `SPO2_B` | 30.5547 | Calibration coefficient |
| `_SPO2_MIN` | 70.0 % | Valid SpO2 range lower bound |
| `_SPO2_MAX` | 100.0 % | Valid SpO2 range upper bound |

**Algorithm:** IIR DC filter → AC extraction → EMA of AC² → R = (RMS_AC_red/DC_red) / (RMS_AC_ir/DC_ir) → SpO2 = A − B·R.

`update(ir, red, fs)` returns a dict with `dc_ir`, `dc_red`, `rms_ac_ir`, `rms_ac_red`, `R`, `spo2`, `spo2_valid`, or `None` during warmup/invalid.

### 5.2 SpO2TestCalc

Extended version of `SpO2LocalCalc` with user-adjustable parameters (used in SpO2TestWindow).
All constants are exposed as instance attributes overridable at runtime from the UI spinboxes.

### 5.3 HR1TestCalc

Replicates `INCUNEST_AFE4490::_update_hr1()`.

**Algorithm:** IIR DC removal → moving average LP filter (cutoff 5 Hz) → threshold-based peak detection (threshold = 0.6 × running max) → refractory period 185 ms → RR intervals buffer (5 intervals) → HR = 60 / mean(RR).

SQI: `1 − CV/0.15` where CV = std(RR)/mean(RR); clamped to [0, 1]. SQI = 0 if < 2 peaks.

### 5.4 HR2TestCalc

Replicates `INCUNEST_AFE4490::_update_hr2()` via `_estimate_hr_autocorr_v2()`.

**Algorithm:** 2nd-order Butterworth bandpass [0.5–5 Hz] → decimate ×10 (500 → 50 Hz) → circular buffer 400 samples (8 s) → every 25 decimated samples: unbiased normalised autocorrelation (FFT-based, `scipy.signal.correlate`) → find first significant peak above min_lag → HR = 60 / peak_lag.

SQI = normalised autocorrelation value at peak [0–1].

Two internal cross-correlation implementations:
- `_estimate_hr_xcorr_v1()` — cross-correlation variant (reference, not used in production path)
- `_estimate_hr_autocorr_v2()` — true autocorrelation (production, matches firmware)

### 5.5 HR3TestCalc / HRFFTCalc

Replicates `INCUNEST_AFE4490::_update_hr3()`.

**Algorithm:** 2nd-order Butterworth LP 10 Hz (anti-aliasing) → decimate ×10 → circular buffer 512 samples (10.24 s) → every 25 decimated samples: Hann window → real FFT → Harmonic Product Spectrum (HPS, 2nd and 3rd harmonics) → peak in [25, 240] BPM → HR = peak_freq × 60.

SQI = HPS peak prominence in the search range [0–1].

`HRFFTCalc` is the base class. `HR3TestCalc` extends it with user-adjustable parameters for the HR3TestWindow.

---

## 6. Main window — PPGMonitor

### 6.1 Layout

```
QMainWindow — "AFE4490 Advanced Monitor (by Medical Open World)" — 1800×1100
Dark theme: background #121212, text #E0E0E0

┌──────────────────────────────────────────────────────────────────────────────┐
│ LEFT SIDEBAR          │ CENTER (4 live plots)    │ RIGHT PANEL              │
│ (fixed width ~220px)  │ (stretches)              │ (fixed width ~340px)     │
├──────────────────────────────────────────────────────────────────────────────┤
│ [Port combo][CONNECT] │ Plot 1: IR + IR_Amb      │ Serial Console (log)     │
│ [RESET]               │        + IR_Sub          │ (color-coded, scrolling) │
│ [PAUSE] [SAVE]        │ Plot 2: RED + RED_Amb    │                          │
│ [RECORD CHK]          │        + RED_Sub         │ SIGNAL STATS table       │
│ [Lab Capture]         │ Plot 3: PPG (display)    │                          │
│ [Decim spin]          │ Plot 4: SpO2 / HR1/2/3   │ [TIMING] button          │
│ ──────────────        │                          │                          │
│ [UDP WiFi] toggle     │                          │                          │
│ [UDP port spin]       │                          │                          │
│ ──────────────        │                          │                          │
│ [PPG PLOTS]           │                          │                          │
│ [PPG SIGNALS]         │                          │                          │
│ [ALGO RESULTS]        │                          │                          │
│ [SERIAL COM]          │                          │                          │
│ [UDP COM]             │                          │                          │
│ LAB group:            │                          │                          │
│ [HR2LAB]              │                          │                          │
│ [HR3LAB]              │                          │                          │
│ [SPO2LAB]             │                          │                          │
│ [PILAB]               │                          │                          │
│ TEST group:           │                          │                          │
│ [SPO2TEST]            │                          │                          │
│ [HR1TEST]             │                          │                          │
│ [HR2TEST]             │                          │                          │
│ [HR3TEST]             │                          │                          │
│ [HW CONFIG]           │                          │                          │
│ [DIAGNOSTICS]         │                          │                          │
│ [AFE SWEEP]           │                          │                          │
│ [PYTHON TIMING]       │                          │                          │
└──────────────────────────────────────────────────────────────────────────────┘
│ Status bar: mouse hint                                                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Data buffers

All buffers are `collections.deque(maxlen=WINDOW_SIZE)` (500 samples = 10 s at 50 Hz).
Named: `data_ppgdisp`, `data_hr1`, `data_hr2`, `data_hr3`, `data_spo2`, `data_spo2_r`,
`data_pi`, `data_red`, `data_ir`, `data_red_amb`, `data_ir_amb`, `data_red_sub`,
`data_ir_sub`, `data_spo2_sqi`, `data_hr1_sqi`, `data_hr2_sqi`, `data_hr3_sqi`.

### 6.3 SIGNAL STATS table

Located in the right panel. Rows = 17 signals. Columns:

| Col | Name | Description |
|-----|------|-------------|
| 0 | Signal | Row label |
| 1 | % SD/Mean | Coefficient of variation as percentage |
| 2 | Mean | Mean value over stats interval |
| 3 | SD | Standard deviation |
| 4 | Max-Min | Peak-to-peak range |
| 5 | Min | Minimum value |
| 6 | Max | Maximum value |
| 7 | V_TIA | Estimated TIA differential output voltage (V) — raw rows only |
| 8 | V_ADC | Estimated ADC input voltage (V) — raw rows only |

**Signal ordering (IR-first, mirrors firmware $M1 frame):**
IR, RED, IR_Amb, RED_Amb (rows 0–3, raw ADC — integer + narrow-space thousands separator `\u202f`),
IR_Sub, RED_Sub (rows 4–5, ambient-subtracted),
PPGdisp, SpO2, SpO2_SQI, SpO2_R, PI, HR1, HR1_SQI, HR2, HR2_SQI, HR3, HR3_SQI (rows 6–16, 2 dp).

**V_TIA / V_ADC columns (cols 7–8):** populated only for rows 0–3 (IR, RED, IR_Amb, RED_Amb).
Calculated from the current ADC mean using the AFE4490 gain chain:
- V_ADC = (mean_counts / 2²¹) × 1.2 V  (ADC full scale ±1.2 V, 22-bit signed)
- V_TIA = (V_ADC / (2 × RG)) × RI = V_ADC × (RI / (2×RG))  (datasheet eq.2, p.30)
  where RI = 100 kΩ (fixed), RG from current `$CFG` stg21/stg22 field.

**V_TIA / V_ADC color coding (background of cols 7–8):**

| Color | Hex | Condition — LED rows (0,1) | Condition — ALED rows (2,3) |
|-------|-----|---------------------------|------------------------------|
| Red | `#4A0800` | V_TIA > 0.95 V or < 0.15 V; V_ADC > 1.10 V or < 0.20 V | V_TIA > 0.70 V; V_ADC > 0.80 V |
| Yellow | `#3A2D00` | V_TIA 0.80–0.95 V or 0.15–0.40 V; V_ADC 0.95–1.10 V or 0.20–0.45 V | V_TIA 0.30–0.70 V; V_ADC 0.35–0.80 V |
| Green | `#0F3A0F` | V_TIA 0.40–0.80 V; V_ADC 0.45–0.95 V | V_TIA < 0.30 V; V_ADC < 0.35 V |
| Default | `#121212` | Row not in {0,1,2,3} or no data | — |

**SQI colour coding (Mean column, col 2):** HR1, HR2, HR3 rows (indices 11, 13, 15):
- Mean SQI > 0.9 → background `#1A5C1A` (dark green)
- Mean SQI ≤ 0.9 → background `#5C001A` (dark maroon)

**Manual highlighting:** clicking any cell toggles a gold border (`#FFD700`, 3 px) via `_StatsHighlightDelegate`. Highlighted cells persist in `pulsenest_lab.ini` (`PPGMonitor/stats_highlighted`, format `row,col;row,col`). The gold border is drawn on top of SQI/voltage background colours.

Stats are accumulated over `spin_stats_interval` seconds (default 1 s, user-configurable) and cleared after each table update.

### 6.4 Serial Console (log panel)

`QTextEdit` (read-only). Each line timestamped `[HH:MM:SS]`. Colour by level:
- success (`#00FF88`) — keywords: "online", "saved"
- warning (`#FFDD44`) — keywords: "recording", "paused"
- error (`#FF4444`) — keywords: "error", "failed", "cannot", "not connected", "no port"
- info (`#44AAFF`) — all other

### 6.5 Controls

| Control | Action |
|---------|--------|
| Port combo | List available COM ports; last used restored from .ini |
| CONNECT | Open/close serial port; starts/stops `_serial_reader` thread |
| RESET | Send `'r'` byte to ESP32 (triggers firmware reset) |
| PAUSE | Freeze display; drain queue to prevent memory buildup |
| SAVE | Toggle live CSV streaming (or snapshot if paused) |
| RECORD CHK | Toggle raw frame checksum log (`ppg_chk_*.csv`) |
| Lab Capture | Open `LabCaptureWindow` |
| Decim spin | Decimation ratio (default 10): 1 in N M1 frames are processed |
| Stats interval | Stats table update interval in seconds (default 1) |
| UDP WiFi button | Toggle UDP receiver on/off; switches active transport |
| UDP port spin | UDP listen port (default 5005) |
| Subwindow buttons | Toggle-open/close each secondary window |

### 6.6 Throttle rates

All rates relative to the render timer tick (~50 ms = ~20 Hz):

| Constant | Value | Applies to |
|----------|-------|-----------|
| `_PPGPLOTS_REFRESH_EVERY` | 1 | PPGPlotsWindow, PPGSignalsWindow, AlgoResultsWindow (20 Hz) |
| `_SUBWIN_REFRESH_EVERY` | 2 | SpO2Lab, HR3Lab, HR2Lab (10 Hz) |
| `_SPOST_REFRESH_EVERY` | 2 | SpO2TestWindow (10 Hz) |
| `_HR1TEST_REFRESH_EVERY` | 2 | HR1TestWindow (10 Hz) |
| `_HR2TEST_REFRESH_EVERY` | 2 | HR2TestWindow (10 Hz) |
| `_HR3TEST_REFRESH_EVERY` | 2 | HR3TestWindow (10 Hz) |
| `_PILAB_REFRESH_EVERY` | 2 | PILabWindow (10 Hz) |

Serial console lines are appended every `_process_frames_tick()` cycle (no throttle; batched in `_console_lines`).

---

## 7. Subwindows

All subwindows are `QWidget` or `QMainWindow` (non-modal), independently resizable.
Each has its geometry persisted in `pulsenest_lab.ini`. Toggle buttons in the sidebar
open/close them; closing a window unticks the sidebar button.
All windows are created with `parent=None` so they appear as independent windows in Alt-Tab.

Every interactive control must have a tooltip built with `_make_tooltip(name, text)`:
purple background (`#5500AA`), bold gold name on first line, light grey description.

### 7.1 PPGPlotsWindow — "PPG Plots"

Detached window with 6 stacked plots, linked X axes:
1. IR raw + IR_Amb + IR_Sub (3 curves, toggleable via checkboxes)
2. RED raw + RED_Amb + RED_Sub (3 curves, toggleable)
3. PPGdisp (display-ready filtered signal)
4. SpO2 [%]
5. HR1 [bpm] (peak detection) + HR2 [bpm] (autocorrelation) + HR3 [bpm] (FFT+HPS)
6. (additional HR comparison row)

Checkboxes for each curve's visibility persisted in .ini.
IR-first row ordering mirrors SIGNAL STATS.

### 7.2 PPGSignalsWindow — "PPG SIGNALS"

Focused view on the 6 raw/subtracted ADC channels (IR, RED, IR_Amb, RED_Amb, IR_Sub, RED_Sub).
IR-first ordering. Stacked plots with linked X axes.

### 7.3 AlgoResultsWindow — "ALGO RESULTS"

Focused view on algorithm outputs: SpO2, SpO2_SQI, SpO2_R, PI, HR1/HR2/HR3 with SQI.
No parameter controls — purely observational.

### 7.4 SerialComWindow — "Serial COM"

Monospace (`Consolas`) scrolling text area. Shows every line received from serial
(raw, before parsing). Lines starting with `#` and data frames both shown.
Pause button stops auto-scroll while new lines are still received.

### 7.5 UdpComWindow — "UDP COM"

Equivalent of SerialComWindow for the WiFi/UDP transport.
Shows every raw frame received via UDP. Has a header label showing the UDP source address
and port once the first packet is received.

### 7.6 SpO2LabWindow — "SPO2LAB — Calibration"

Purpose: calibrate SpO2 probe coefficients (A, B) by regression over reference points.

Layout: left 4 plots (rolling 60 s) + right control panel.

**Plots (left):**
1. SpO2 fw + SpO2 py [%]
2. R ratio fw + R ratio py
3. DC IR + DC RED (ADC counts)
4. RMS AC IR + RMS AC RED

**Right panel:**
- Sensor metadata fields (probe model, lot, reference device, operator, notes)
- Reference SpO2 spinbox (spin_spo2_ref)
- [ADD POINT] — appends current mean R and reference SpO2 to calibration table
- Calibration table: index, SpO2_ref, R_fw_mean, R_local_mean
- Regression result display: A, B, R² (computed live on each ADD POINT)
- [EXPORT CSV] — saves calibration table + regression to `spo2_cal_*.csv`
- [CLEAR] — resets calibration table

### 7.7 SpO2TestWindow — "SPO2TEST"

Purpose: verify Python SpO2 replica matches firmware output in real time.

Layout: left 6 stacked plots + right parameter/values panel.

**Plots:**
1. SpO2 fw (green) + SpO2 py (yellow)
2. Delta SpO2 (fw − py)
3. R ratio fw + R ratio py
4. SpO2 SQI
5. DC IR + DC RED
6. RMS AC IR + RMS AC RED

**Right panel:** parameter spinboxes (DC tau, AC tau, A, B, warmup), live current-values table,
[EXPORT CSV] button, [LOAD CSV] for offline reprocessing.

### 7.8 HR1TestWindow — "HR1TEST"

Purpose: verify Python HR1 replica matches firmware output.

Layout: left 4 plots + RR distribution + right panel.

**Plots:**
1. Signal chain: raw IR_Sub → DC-removed → LP-filtered
2. HR1 fw (green) + HR1 py (yellow)
3. Delta HR1
4. HR1 SQI fw + py

**Bar chart:** RR interval distribution (last N beats).

**Right panel:** parameter spinboxes, current-values table, [EXPORT CSV], [LOAD CSV].

### 7.9 HR2TestWindow — "HR2TEST"

Purpose: verify Python HR2 replica matches firmware output.

Layout: left 4 plots + right panel.

**Plots:**
1. Autocorrelation curve (current window) with detected peak marker
2. Bandpass-filtered signal (0.5–5 Hz decimated)
3. HR2 fw (green) + HR2 py (yellow)
4. HR2 SQI fw + py

**Right panel:** BPF cutoff spinboxes, window/update interval spinboxes,
current-values table, [EXPORT CSV], [LOAD CSV].

### 7.10 HR3TestWindow — "HR3TEST"

Purpose: verify Python HR3 (FFT+HPS) replica matches firmware output.

Layout: left 4 plots + right panel.

**Plots:**
1. FFT magnitude + HPS spectrum with detected peak marker
2. LP-filtered decimated signal (input to FFT)
3. HR3 fw (green) + HR3 py (yellow)
4. HR3 SQI fw + py

**Right panel:** LP cutoff, HPS harmonics count spinboxes, current-values table, [EXPORT CSV], [LOAD CSV].

### 5.6 PICalc

Configurable 3-step Perfusion Index pipeline. Not a firmware replica — it is an investigation
tool to evaluate different estimator strategies.

See full description in §7.11 (PILabWindow).

---

### 7.11 PILabWindow — "PILAB"

Purpose: investigate the Perfusion Index (PI) computation pipeline by comparing two
independently configured PI estimators side by side on live or recorded data.

#### PICalc — configurable 3-step PI pipeline (class)

`PICalc` implements a configurable pipeline for computing PI from raw `led1_sub` / `led2_sub` samples.

**Pipeline steps:**

| Step | Role | Methods |
|------|------|---------|
| STEP1 — DC subtraction | Removes baseline to isolate AC component | S1_EMA (EMA τ_sub), S1_BPF (Butterworth BPF), S1_NONE (pass-through) |
| STEP2 — AC estimator | Estimates pulse amplitude | S2_EMA_RMS (EMA of x², τ_ac), S2_WIN_RMS (windowed RMS), S2_PEAKPK ((max−min)/2), S2_SPECTRAL (FFT energy at f_HR±Δ), S2_HARMONICS (FFT energy sum at n·f_HR) |
| STEP3 — DC denominator | Estimates DC for the PI denominator (independent of STEP1) | S3_EMA (EMA τ_norm), S3_LPF (Butterworth LPF), S3_WIN_MEAN (windowed mean) |

**Output:** `PI_ir = AC_ir / DC_ir × 100 %`, `PI_red = AC_red / DC_red × 100 %`, `R = PI_red / PI_ir`.

**Firmware M1 defaults (Instance A):** STEP1 = S1_EMA τ_sub=2 s; STEP2 = S2_EMA_RMS τ_ac=6 s (ISO 80601-2-61:2026 JJ.2 d); STEP3 = S3_EMA τ_norm=2 s.

`reconfigure(fs)` recalculates EMA alphas and filter coefficients from current parameters and resets state.
`update(ir, red, fs)` processes one sample; calls `reconfigure` lazily if `fs` changed.
`reset()` clears all accumulators without touching configuration.

#### PILabWindow layout

```
┌─────────────────────────────────────────────────────────┐
│ LEFT (4 stacked plots, X linked)  │ RIGHT panel         │
│                                   │ [LOAD CSV][LIVE]    │
│ Plot 1: led1_sub + DC_sub A/B     │ [PAUSE]         [?] │
│                                   │ ┌─────────┬───────┐ │
│ Plot 2: AC_r [ADC] A/B            │ │Instance │Inst.  │ │
│                                   │ │A(orange)│B(blue)│ │
│ Plot 3: PI_ir [%] A/B             │ │ STEP1   │ STEP1 │ │
│                                   │ │ STEP2   │ STEP2 │ │
│ Plot 4: R = PI_red/PI_ir A/B      │ │ STEP3   │ STEP3 │ │
│                                   │ └─────────┴───────┘ │
│                                   │ Value table 4×2     │
│                                   │ PI_ir/PI_red/R/AC_r  │
└─────────────────────────────────────────────────────────┘
```

**Plots:**
1. Raw `led1_sub` (grey) + DC_sub from STEP1 for A (orange) and B (blue) — shows DC tracking quality.
2. AC amplitude (STEP2 output) for A and B — compares estimator magnitude.
3. PI_ir [%] for A and B — final PI result (AC/DC × 100).
4. R ratio for A and B — modulation ratio entering SpO2 formula.

**Config columns A / B:** always visible side by side (not tabs). Each column has an independent
`_make_config_tab()` panel with STEP1/2/3 method combo + associated parameter spinboxes + [APPLY] button.
Font sizes: combos/spins 17 px, form labels 17 px.

**Value table:** 4 rows × 2 cols (A / B). Font 24 px data, 20 px headers. Rows: PI_ir [%], PI_red [%], R, AC_r_ir.

**Help button `?`:** opens a `QDialog` with HTML explaining the four plots and the pipeline.

**Feed architecture:**
- `feed_sample(ir, red, fs, ts_us)` — called per sample in `_process_frames_tick()`.
- `update_plots()` — called from render tick every `_PILAB_REFRESH_EVERY` ticks (10 Hz).

**Offline mode:** [LOAD CSV] reads a captured CSV file and replays samples through both pipelines.
[LIVE] switches back to live mode. [PAUSE] freezes plots without stopping collection.

**Integration:** PILAB button is in the **LAB group** of the sidebar (alongside HR2LAB, HR3LAB, SPO2LAB).

### 7.12 HR3LabWindow — "HR3LAB"

Purpose: diagnostic view combining FFT spectrum and HR algorithm comparison.

Layout: left (FFT spectrum with HPS peak line) + right (2 stacked: LP signal + HR1/HR2/HR3 comparison).

No parameter editing — purely observational.

### 7.12 HRLabWindow — "HR2LAB"

Purpose: interactive filter chain visualization for HR algorithm development.

3-column layout showing PPG signal chain variants side by side.
Each column shows a different filter combination to compare quality.

### 7.13 LabCaptureWindow

Purpose: controlled capture with metadata for lab sessions.

**Controls:**
- Output directory (browse button)
- Filename prefix
- Pre-notes text area (written as `#`-comment lines at start of CSV)
- Post-notes text area (written as `#`-comment lines at end of CSV)
- Column selection checkboxes (subset of M1 fields)
- Mode: continuous / timed (N samples)
- Progress bar (timed mode)
- [START] / [STOP]

**Output file:** `lab_capture_*.csv` in `CAPTURES_DIR`. All state persisted in .ini.

### 7.14 Esp32TimingWindow — "TIMING — CPU Budget & Load"

Purpose: display FreeRTOS algorithm timing stats from `$TIMING` / `$TASK` frames.

**Contents:**
- Bar chart: mean and max µs per algorithm (SpO2, HR1, HR2 FP, HR3 FP, HR2 CMP, HR3 CMP, full cycle)
- Stack free watermarks per task
- Task table: name, CPU%, stack words (from `$TASK` frames)

Updated on each received `$TIMING` + `$TASKS_END` batch.

### 7.15 PythonTimingWindow — "PYTHON TIMING"

Purpose: measure the execution time of the Python algorithm replicas running in the script.

**Contents:**
- Section A — Tick timers: `_process_frames_tick()` (serial+UDP drain) and `_refresh_plots_tick()` total.
- Per-algorithm mean/max µs: HR1TestCalc, HR2TestCalc, HR3TestCalc, SpO2LocalCalc.
- Updated every ~1 s. Useful for verifying the Python algorithms stay within the 20 ms budget.

### 7.16 HWConfigWindow — "HW CONFIG"

Purpose: view and change AFE4490 hardware parameters in real time via `$SET`/`$CFG` protocol.

**Contents:**
- LED1 / LED2 current DAC code + LED range selector (75/150 mA)
- Separate-gain enable toggle
- TIA gain (RF1/RF2) and feedback capacitor (CF1/CF2) per channel
- Stage-2 gain (RG1/RG2) and enable per channel
- Ambient DAC current (ambdac 0–10 µA)
- Sample rate and number of averages
- Raw timing registers t1–t28 with constraint checker
- [Read from chip ($CFG?)] — requests `$CFG?` from firmware
- [Set all] — sends `$SET` for every parameter in the window
- [Save to file] / [Load from file] — persist/restore configuration as CSV
- Status bar: shows last command sent and confirmation status

Controls are marked **dirty** (yellow border) when their value differs from the last `$CFG` received,
and **clean** (no border) after a matching `$CFG` confirms the change.

### 7.17 LIBConfigWindow — "LIB CONFIG"

Purpose: view and change RSQM / algorithm library parameters in real time via `$SET`/`$LCFG` protocol.

**Contents (RSQM group):**
- OT threshold (`rsqm_ot_thr`) — NOT_APPLIED vs APPLIED boundary [A/A]
- Signal weak STD (`rsqm_signal_weak_std`) — SIGNAL_WEAK threshold [ADC counts]
- DISCONNECTED LED_sub threshold (`rsqm_disconn_led_sub_thr`) [ADC counts]
- DISCONNECTED I_PD threshold (`rsqm_disconn_i_pd_thr`) [nA displayed, A stored]
- Probe debounce (`rsqm_probe_state_min_s`) [s] — converted to samples from `fs` internally
- EMA mean τ (`rsqm_ema_mean_tau_s`) [s]
- EMA var τ (`rsqm_ema_var_tau_s`) [s]
- [Read from chip ($LCFG?)] — requests `$LCFG?` from firmware
- [Set all] — sends `$SET` for every parameter in the window
- Status bar: shows last command sent and confirmation status

Controls are marked **dirty** (red text) when edited but not yet confirmed by firmware, and **clean** after a matching `$LCFG` arrives.

### 7.18 DiagnosticsWindow — "DIAGNOSTICS"

Purpose: run the AFE4490 hardware diagnostic test and display the result.

**Contents:**
- [Run Diagnostic] button — sends `$DIAG?` to firmware
- Decoded diagnostic register bits: LED driver status, TIA open/short, ambient ADC, etc.
- Raw hex value display

### 7.18 AFESweepTestWindow — "AFE SWEEP TEST"

Purpose: parametric sweep over AFE4490 hardware parameters to characterize the analog front-end.
Sends `$SET` commands, waits for settling, collects statistics, then moves to the next combination.

**Sweep parameters (all can be set to FIX or VAR min/mid/max, or None to skip):**

| Parameter | Range | Description |
|-----------|-------|-------------|
| LED1 mA | 0–255 (DAC code) | IR LED current |
| LED2 mA | 0–255 (DAC code) | RED LED current |
| RF1 / RF2 | 10K–1M (7 values) | TIA feedback resistor per channel |
| RG1 / RG2 | 0–12 dB (5 values) | Stage-2 gain per channel |
| AMBDAC | 0–10 µA (11 values) | Ambient cancellation current |

**Sweep Parameter grid columns:** `FIX` | `VAR min` | `VAR mid` | `VAR max`

Setting a spin to "None" removes that parameter from the sweep (fewer combinations).
Setting all VAR spins to "None" results in 0 combos (sweep cannot start).

The combo count is recalculated live on any spin change and shown in the Control area.

**Control area:**
- N samples spin: how many M1 frames to average per combination (default 20)
- Settling time spin: milliseconds to wait after `$SET` before collecting data (default 200 ms)
- [START SWEEP] / [STOP SWEEP] toggle
- Progress bar: current combo / total combos
- Status label: state machine status

**State machine:** IDLE → SETTLING (sends `$SET`, waits settling_ms) → MEASURING (collects N samples) → next combo or IDLE.

**Output file:** `afe_sweep_YYYYMMDD_HHMMSS.csv` in `CAPTURES_DIR`. 40 columns:
`label`, `datetime`, `LED1mA`, `LED2mA`, `RF1`, `RF2`, `RG1`, `RG2`, `ambdac_uA`, `n_samples`,
then for each of 6 signals (LED2, LED1, ALED2, ALED1, LED2_Sub, LED1_Sub): `_mean`, `_min`, `_max`, `_pp`, `_std`.

#### _ComboSpin widget

All sweep-parameter spins use a custom `_ComboSpin` widget (QComboBox subclass) with a
QSpinBox-compatible API:

- `value()` → `currentIndex() - 1` (None item at index 0 returns -1; real items start at 0)
- `setValue(v)` → `setCurrentIndex(v + 1)`

This allows the same `_build_combos()` / `_apply_combo()` logic to treat `value() < 0` as "skip this parameter".

---

## 8. File outputs

All files are saved to `CAPTURES_DIR` (`captures/` subdirectory). The directory is created
at startup (`os.makedirs(CAPTURES_DIR, exist_ok=True)`).

| File | Filename pattern | Trigger | Contents |
|------|-----------------|---------|---------|
| Live stream | `ppg_data_stream_YYYYMMDD_HHMMSS.csv` | SAVE toggle (not paused) | All M1 fields at decimated rate; columns: `Timestamp_PC`, `Diff_us_PC` + 20 M1 fields |
| Snapshot | `ppg_data_snap_YYYYMMDD_HHMMSS.csv` | SAVE toggle (while paused) | Current rolling buffer contents (last 10 s) |
| CHK diagnostic | `ppg_chk_YYYYMMDD_HHMMSS.csv` | RECORD CHK toggle | `Timestamp_PC`, `Diff_us_PC`, `CHK_OK` (0/1), `RawFrame` |
| SpO2 calibration | `spo2_cal_YYYYMMDD_HHMMSS.csv` | EXPORT CSV in SpO2LabWindow | Calibration table + regression coefficients |
| SpO2 test export | `spo2test_YYYYMMDD_HHMMSS.csv` | EXPORT CSV in SpO2TestWindow | `t_s`, `spo2_fw`, `spo2_py`, `spo2_delta`, `R_fw`, `R_py` |
| HR1 test export | `hr1test_YYYYMMDD_HHMMSS.csv` | EXPORT CSV in HR1TestWindow | HR1 fw vs py time series |
| HR2 test export | `hr2test_YYYYMMDD_HHMMSS.csv` | EXPORT CSV in HR2TestWindow | `t_s`, `hr_fw`, `hr_py`, `delta`, `sqi_fw`, `sqi_py` |
| HR3 test export | `hr3test_YYYYMMDD_HHMMSS.csv` | EXPORT CSV in HR3TestWindow | `t_s`, `hr_fw`, `hr_py`, `delta`, `sqi_fw`, `sqi_py` |
| Lab capture | `lab_capture_YYYYMMDD_HHMMSS.csv` | START in LabCaptureWindow | Pre-notes, user-selected M1 columns, post-notes |
| AFE sweep | `afe_sweep_YYYYMMDD_HHMMSS.csv` | START SWEEP in AFESweepTestWindow | 40-column combo results (see §7.18) |

All CSV files include a `#`-prefixed header comment with timestamp and relevant parameters.

---

## 9. Settings persistence

**File:** `pulsenest_lab.ini` (Qt QSettings, IniFormat, same directory as the script).

| Key | Type | Description |
|-----|------|-------------|
| `PPGMonitor/geometry` | bytes | Main window size/position |
| `PPGMonitor/right_splitter` | bytes | Right panel splitter state |
| `PPGMonitor/spin_decim` | int | Decimation ratio |
| `PPGMonitor/spin_stats_interval` | float | Stats table update interval (s) |
| `PPGMonitor/combo_port` | str | Last selected COM port |
| `PPGMonitor/stats_highlighted` | str | Highlighted cells (`row,col;row,col`) |
| `PPGMonitor/*_open` | bool | Whether each subwindow was open on exit |
| `PPGPlotsWindow/geometry` | bytes | |
| `PPGPlotsWindow/check_ir_raw` … `check_red_sub` | bool | Curve visibility (IR-first) |
| `PPGSignalsWindow/geometry` | bytes | |
| `AlgoResultsWindow/geometry` | bytes | |
| `SpO2LabWindow/geometry` | bytes | |
| `SpO2LabWindow/splitter` | bytes | |
| `SpO2LabWindow/spin_spo2_ref` | float | Last reference SpO2 value |
| `SpO2TestWindow/geometry` | bytes | |
| `HR1TestWindow/geometry` | bytes | |
| `HR2TestWindow/geometry` | bytes | |
| `HR3TestWindow/geometry` | bytes | |
| `HR3LabWindow/geometry` | bytes | |
| `HRLabWindow/geometry` | bytes | |
| `SerialComWindow/geometry` | bytes | |
| `UdpComWindow/geometry` | bytes | |
| `HWConfigWindow/geometry` | bytes | |
| `DiagnosticsWindow/geometry` | bytes | |
| `AFESweepTestWindow/geometry` | bytes | |
| `AFESweepTestWindow/*` | mixed | All sweep parameter spin values |
| `PythonTimingWindow/geometry` | bytes | |
| `LabCaptureWindow/geometry` | bytes | |
| `LabCaptureWindow/*` | mixed | Output dir, prefix, pre/post notes, column selection |
| `PILabWindow/geometry` | bytes | |

Settings are saved on window close and restored on startup.

**Port restoration rule:** if the saved `combo_port` is not in the current system port list,
the combo is left unselected (no auto-connect). The user must select a port manually and click
SERIAL ON. This prevents the script from connecting to the wrong port (e.g. a Bluetooth COM
port that happens to be first alphabetically).

---

## 10. Display conventions

### Color convention (curves and values)

| Color | Meaning |
|-------|---------|
| Green `#00CC44` | Data from firmware (`incunest_afe4490`) |
| Yellow `#FFDD44` | Data calculated by the Python script (HR1TEST, HR2TEST, HR3TEST, SpO2TEST) |
| Red tones | RED channel signals |
| Blue tones | IR channel signals |

### V_TIA / V_ADC color coding

Voltage-based cell background colors in SIGNAL STATS table cols 7–8:
- Green `#0F3A0F` — optimal operating range
- Yellow `#3A2D00` — caution (approaching saturation or insufficient signal)
- Red `#4A0800` — saturation or signal too low
- Default `#121212` — no data or non-ADC row

Thresholds derived from AFE4490 datasheet: VCMREF = 0.9 V internal, ADC FS = ±1.2 V,
V_OD(s) = 1.0 V differential. See §6.3 for per-row thresholds.

### Tooltip convention

Every interactive control must use `_make_tooltip(name, text, src="")`:
- Background: `#5500AA` (vivid purple)
- `name` in bold gold as first line
- `text` in light grey
- Optional `src` shown in smaller italic grey as source code reference
- Fixed width 540 px, 8 px padding

### Action button style

`ACTION_BUTTON_STYLE` applies to all main action buttons:
- Normal: background `#555555`, white text, bold, 20px font
- Checked/active: background `#FF6666`
- Hover: background `#666666`

### Dirty / clean indicator (HWConfigWindow)

Controls whose value differs from the last `$CFG` received are marked dirty with a yellow border.
Controls matching the firmware's confirmed value are clean (no border).

### Plot style

Dark background (`#121212`), light grid, white/colour curves.
Subwindow menu min-width: `QMenu { min-width: 360px; }` applied globally to prevent
pyqtgraph context menus from being too narrow to read.

---

## 11. Naming conventions

- `_led1` / `_led2` — raw hardware readings (LED1VAL, LED2VAL, ALED1VAL, ALED2VAL), unfiltered.
- `_ir` / `_red` — values after physiological interpretation (inside SpO2/HR algorithm classes).
- Parameter names follow the domain prefix rule: `afe_`, `ppgdisp_`, `hr1_`, `hr2_`, `hr3_`, `spo2_`, `hr_`.

---

## 12. Changelog

### v1.6 — 2026-06-15
- Fixed startup port fallback bug (`_populate_ports`): when the saved `combo_port` is not in
  the available port list, the combo is now left unselected (index -1) instead of falling back
  to index 0. Prevents silent connection to the wrong port (e.g. Bluetooth COM ports), which
  caused the Windows Bluetooth driver to freeze Qt's message pump after ~30 s.
- Added heartbeat timer `_hb` (500 ms, writes `debug_hb.log`) for autonomous freeze regression
  testing via `freeze_test.py`.

### v1.5 — 2026-06-14
- Fixed UDP first-packet activation (§4.1): `_active_transport` stays `"serial"` until first UDP datagram arrives.
  `_connect_udp()` now shows `LISTEN` state; `_on_udp_active()` slot switches to `"udp"` on main thread.
  Fixes apparent app freeze when WiFi unreachable but USB connected.

### v1.4 — 2026-06-14
- Added `PICalc` class (§5.6): configurable 3-step PI pipeline (STEP1/STEP2/STEP3), firmware M1 defaults.
- Added PILabWindow (§7.11): 4 stacked plots, two always-visible config columns A/B, value table, help dialog.
- Updated sidebar (§6.1): LAB group (HR2LAB, HR3LAB, SPO2LAB, PILAB) and TEST group labelled explicitly.
- Updated throttle rates (§6.6): added `_PILAB_REFRESH_EVERY = 2` (10 Hz).
- Updated settings (§9): added `PILabWindow/geometry` and `PPGMonitor/pilab_open`.
- Updated tooltip convention (§10): `_make_tooltip` now accepts optional `src` parameter.

### v1.3 — 2026-05-27
- Added WiFi/UDP transport (§4.1, §4.7): `_udp_reader` thread, `_udp_queue`, `btn_udp` toggle, UdpComWindow.
- Added `$SET` / `$CFG` / `$TCFG` / `$DIAG` / `$ERR` protocol documentation (§4.3, §4.4).
- Updated SIGNAL STATS table (§6.3): expanded to 9 columns, IR-first row ordering, V_TIA/V_ADC columns with voltage-based color coding.
- Added PPGSignalsWindow (§7.2), AlgoResultsWindow (§7.3), UdpComWindow (§7.5).
- Added HWConfigWindow (§7.16): real-time AFE4490 parameter control via $SET/$CFG.
- Added DiagnosticsWindow (§7.17): hardware diagnostic via $DIAG?.
- Added AFESweepTestWindow (§7.18): parametric sweep with _ComboSpin widget, "None" option, live combo count.
- Added PythonTimingWindow (§7.15): Python algorithm execution timing.
- Updated Esp32TimingWindow (§7.14): extended $TIMING format with hr2cmp/hr3cmp stats.
- Updated data flow (§4.7): two-timer architecture (_process_frames_tick + _render_timer).
- Updated main window sidebar layout (§6.1) with new buttons.
- Added `afe_sweep_YYYYMMDD_HHMMSS.csv` to file outputs (§8).
- Added naming conventions section (§11).
- Added dirty/clean indicator to display conventions (§10).

### v1.0 — 2026-04-14
- Initial spec. Documents the script as-shipped at the point of PulseNest repo separation
  from `acuesta-mow/incunest_afe4490_test`.
- Features covered: all subwindows, SpO2/HR1/HR2/HR3 algorithm replicas, LabCapture,
  SIGNAL STATS table (with gold cell highlighting and SQI colour coding),
  per-frame RED_Sub/IR_Sub integrity check, captures/ output directory,
  QMenu min-width fix, integer+thousands-separator formatting for raw ADC signals.
