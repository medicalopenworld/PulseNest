# pulsenest_lab — Specification v1.0

Python desktop application for real-time visualization, analysis, algorithm verification
and data capture of PPG/SpO2 signals from the AFE4490 via the `incunest_afe4490` firmware.

Part of the **PulseNest** project — Medical Open World.

---

## 1. Purpose and role

`pulsenest_lab.py` is the PC-side companion to the PulseNest firmware. It is not a utility
script — it is a first-class project deliverable with its own spec and versioning.

Responsibilities:
- Display real-time PPG/SpO2/HR signals received over USB serial from the ESP32-S3.
- Run Python replicas of the firmware SpO2 and HR algorithms for independent verification.
- Provide tunable algorithm windows to explore parameter sensitivity.
- Support SpO2 probe calibration (R-ratio regression).
- Capture and export data to CSV for offline analysis.
- Display FreeRTOS timing stats (CPU budget per algorithm).

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
| `SETTINGS_FILE` | `pulsenest_lab.ini` (same dir) | Qt QSettings persistence file |
| `CAPTURES_DIR` | `captures/` (same dir) | Output directory for all CSV captures; created at startup |
| `WINDOW_SIZE` | `500` | Rolling display buffer length (10 s @ 50 Hz) |
| `PPG_WINDOW_SIZE` | `500` | Same as WINDOW_SIZE (kept separate for clarity) |
| `SPO2_CAL_BUFSIZE` | `3000` | SpO2 calibration rolling buffer (60 s @ 50 Hz) |
| `SPO2_RECEIVED_FS` | `50.0` Hz | Effective sample rate after decimation (500 Hz / 10) |

---

## 4. Serial protocol

### 4.1 Frame types

All frames are ASCII lines terminated with `\r\n`. Fields are comma-separated.
Every frame ends with `*XX` where `XX` is the XOR checksum of the bytes between `$` and `*`.

#### $M1 — Full data frame (default)

```
$M1,<LibID>,<SmpCnt>,<Ts_us>,<RED>,<IR>,<RED_Amb>,<IR_Amb>,<RED_Sub>,<IR_Sub>,
    <PPG>,<SpO2>,<SpO2_SQI>,<SpO2_R>,<PI>,<HR1>,<HR1_SQI>,<HR2>,<HR2_SQI>,
    <HR3>,<HR3_SQI>*XX
```

| Field | Type | Description |
|-------|------|-------------|
| `LibID` | str | Active library identifier (e.g. `"INCUNEST"`) |
| `SmpCnt` | int | Sample counter (firmware, rolls over) |
| `Ts_us` | int | ESP32 timestamp in µs (`esp_timer_get_time()`) |
| `RED` | int32 | LED2VAL — RED raw ADC |
| `IR` | int32 | LED1VAL — IR raw ADC |
| `RED_Amb` | int32 | ALED2VAL — ambient after RED LED |
| `IR_Amb` | int32 | ALED1VAL — ambient after IR LED |
| `RED_Sub` | int32 | RED − RED_Amb — ambient-corrected RED |
| `IR_Sub` | int32 | IR − IR_Amb — ambient-corrected IR |
| `PPG` | int32 | Filtered PPG (bandpass, selected channel) |
| `SpO2` | float | SpO2 in % |
| `SpO2_SQI` | float | SpO2 Signal Quality Index [0–1] |
| `SpO2_R` | float | R ratio used for SpO2 |
| `PI` | float | Perfusion Index in % |
| `HR1` | float | HR via peak detection (bpm) |
| `HR1_SQI` | float | HR1 SQI [0–1] |
| `HR2` | float | HR via autocorrelation (bpm) |
| `HR2_SQI` | float | HR2 SQI [0–1] |
| `HR3` | float | HR via FFT+HPS (bpm) |
| `HR3_SQI` | float | HR3 SQI [0–1] |

#### $M2 — Minimal frame (raw ADC only)

```
$M2,<cnt>,<RED>,<IR>,<RED_Amb>,<IR_Amb>,<RED_Sub>,<IR_Sub>*XX
```

Used when firmware is in `IncunestFrameMode::RAW`. No algorithm outputs.

#### $TIMING — Algorithm timing stats

```
$TIMING,<hr1_mean_us>,<hr1_max_us>,<hr2_mean_us>,<hr2_max_us>,
        <hr3_mean_us>,<hr3_max_us>,<spo2_mean_us>,<spo2_max_us>,
        <cycle_mean_us>,<cycle_max_us>,
        <stack_afe_free>,<stack_hr2_free>,<stack_hr3_free>*XX
```

Emitted every ~5 s (every `ts_emit_interval` samples). Requires `INCUNEST_TIMING_STATS=1`.

#### $TASK — FreeRTOS task info (follows $TIMING)

```
$TASK,<name>,<cpu_pct>,<stack_words>*XX
```

One frame per task. Sequence terminated by `$TASKS_END`.

#### # lines — System messages

Lines starting with `#` are human-readable status messages from the firmware:
- `# SYS: ...` — startup info (chip, flash, heap)
- `# incunest_afe4490 started` — library started
- `# frame mode ...` — frame mode change

### 4.2 Checksum

XOR of all bytes between `$` and `*` (exclusive). Validated on every frame.
Frames with bad checksum are silently discarded.

### 4.3 Per-frame integrity check: RED_Sub / IR_Sub

When parsing live M1 frames, the script verifies:
```
RED_Sub == RED − RED_Amb
IR_Sub  == IR  − IR_Amb
```
If a mismatch is found, it is logged to the Serial Console as `[CHK] SUB MISMATCH #N`.
First 5 mismatches are always logged; thereafter one every 100. Counter: `_sub_mismatch_count`.

### 4.4 Data flow

```
ESP32 Serial (921600 baud)
      │
      ▼
_reader_thread  ──────────────────────────────────────
  readline() loop                                     │ thread boundary
  → _serial_queue (queue.Queue, no size limit)        │
      │                                               │
      ▼                                          UI thread
update_data()  (called by QTimer @ ~50 Hz)
  drain _serial_queue
  parse frame → update deque buffers
  throttled: refresh plots in open subwindows
```

`_reader_thread` runs in a daemon thread. It only reads bytes and enqueues lines — no parsing, no UI calls. This ensures no frames are dropped during slow rendering.

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

**Algorithm:** IIR DC removal → moving average LP filter (cutoff 5 Hz) → threshold-based peak detection (threshold = 0.6 × running max) → refractory period 0.2 s → RR intervals buffer (5 intervals) → HR = 60 / mean(RR).

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
│ [Port combo][CONNECT] │ Plot 1: RED (raw+sub)    │ Serial Console (log)     │
│ [RESET]               │ Plot 2: IR  (raw+sub)    │ (color-coded, scrolling) │
│ [PAUSE] [SAVE]        │ Plot 3: PPG              │                          │
│ [RECORD CHK]          │ Plot 4: SpO2 / HR1/2/3  │ SIGNAL STATS table       │
│ [Lab Capture]         │                          │                          │
│ [Decim spin]          │                          │ [TIMING] button          │
│ ──────────────        │                          │                          │
│ [PPG PLOTS]           │                          │                          │
│ [SERIAL COM]          │                          │                          │
│ [SPO2LAB]             │                          │                          │
│ [SPO2TEST]            │                          │                          │
│ [HR1TEST]             │                          │                          │
│ [HR2TEST]             │                          │                          │
│ [HR3TEST]             │                          │                          │
│ [HR3LAB]              │                          │                          │
│ [HR2LAB]              │                          │                          │
└──────────────────────────────────────────────────────────────────────────────┘
│ Status bar: mouse hint                                                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Data buffers

All buffers are `collections.deque(maxlen=WINDOW_SIZE)` (500 samples = 10 s at 50 Hz).
Named: `data_ppg`, `data_hr1`, `data_hr2`, `data_hr3`, `data_spo2`, `data_spo2_r`,
`data_pi`, `data_red`, `data_ir`, `data_red_amb`, `data_ir_amb`, `data_red_sub`,
`data_ir_sub`, `data_spo2_sqi`, `data_hr1_sqi`, `data_hr2_sqi`, `data_hr3_sqi`.

### 6.3 Signal STATS table

Located in the right panel. Rows = 17 signals. Columns: Signal | Last | Mean | Max-Min | Min | Max.

Signals (in order): RED, IR, RED_Amb, IR_Amb, RED_Sub, IR_Sub (rows 0–5, integer + narrow-space thousands separator `\u202f`), PPG, SpO2, SpO2_SQI, SpO2_R, PI, HR1, HR1_SQI, HR2, HR2_SQI, HR3, HR3_SQI (rows 6–16, 2 decimal places).

**SQI colour coding (Mean column):** HR1, HR2, HR3 rows (indices 11, 13, 15):
- Mean SQI > 0.9 → background `#1A5C1A` (dark green)
- Mean SQI ≤ 0.9 → background `#5C001A` (dark maroon)

**Manual highlighting:** clicking any cell toggles a gold border (`#FFD700`, 3 px) via `_StatsHighlightDelegate`. Highlighted cells persist in `pulsenest_lab.ini` (`PPGMonitor/stats_highlighted`, format `row,col;row,col`). The gold border is drawn on top of SQI background colours.

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
| CONNECT | Open/close serial port; starts/stops `_reader_thread` |
| RESET | Send `'r'` byte to ESP32 (triggers firmware reset) |
| PAUSE | Freeze display; drain queue to prevent memory buildup |
| SAVE | Toggle live CSV streaming (or snapshot if paused) |
| RECORD CHK | Toggle raw frame checksum log (`ppg_chk_*.csv`) |
| Lab Capture | Open `LabCaptureWindow` |
| Decim spin | Decimation ratio (default 10): 1 in N M1 frames are processed |
| Stats interval | Stats table update interval in seconds (default 1) |
| Subwindow buttons | Toggle-open/close each secondary window |

### 6.6 Throttle rates

All rates relative to the decimated data rate (~50 Hz after default decim=10):

| Constant | Value | Applies to |
|----------|-------|-----------|
| `_PPGPLOTS_REFRESH_EVERY` | 2 | PPGPlotsWindow (25 Hz) |
| `_SUBWIN_REFRESH_EVERY` | 5 | SpO2Lab, HR3Lab, HR2Lab (10 Hz) |
| `_SPOST_REFRESH_EVERY` | 5 | SpO2TestWindow (10 Hz) |
| `_HR1TEST_REFRESH_EVERY` | 5 | HR1TestWindow (10 Hz) |
| `_HR2TEST_REFRESH_EVERY` | 5 | HR2TestWindow (10 Hz) |
| `_HR3TEST_REFRESH_EVERY` | 5 | HR3TestWindow (10 Hz) |

Serial console lines are appended every `update_data()` cycle (no throttle; batched in `_console_lines`).

---

## 7. Subwindows

All subwindows are `QWidget` (not `QDialog`), non-modal, independently resizable.
Each has its geometry persisted in `pulsenest_lab.ini`. Toggle buttons in the sidebar
open/close them; closing a window unticks the sidebar button.

Every interactive control must have a tooltip built with `_make_tooltip(name, text)`:
purple background (`#5500AA`), bold gold name on first line, light grey description.

### 7.1 PPGPlotsWindow — "PPG Plots"

Detached window with 6 stacked plots, linked X axes:
1. RED raw + RED_Amb + RED_Sub (3 curves, toggleable via checkboxes)
2. IR raw + IR_Amb + IR_Sub (3 curves, toggleable)
3. PPG (filtered)
4. SpO2 [%]
5. HR1 [bpm] (peak detection)
6. HR2 [bpm] (autocorrelation)

Checkboxes for each curve's visibility persisted in .ini.

### 7.2 SerialComWindow — "Serial COM"

Monospace (`Consolas`) scrolling text area. Shows every line received from serial
(raw, before parsing). Lines starting with `#` and data frames both shown.

### 7.3 SpO2LabWindow — "SPO2LAB — Calibration"

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

### 7.4 SpO2TestWindow — "SPO2TEST"

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
[EXPORT CSV] button.

### 7.5 HR1TestWindow — "HR1TEST"

Purpose: verify Python HR1 replica matches firmware output.

Layout: left 4 plots + RR distribution + right panel.

**Plots:**
1. Signal chain: raw IR_Sub → DC-removed → LP-filtered
2. HR1 fw (green) + HR1 py (yellow)
3. Delta HR1
4. HR1 SQI fw + py

**Bar chart:** RR interval distribution (last N beats).

**Right panel:** parameter spinboxes, current-values table, [EXPORT CSV].

### 7.6 HR2TestWindow — "HR2TEST"

Purpose: verify Python HR2 replica matches firmware output.

Layout: left 4 plots + right panel.

**Plots:**
1. Autocorrelation curve (current window) with detected peak marker
2. Bandpass-filtered signal (0.5–5 Hz decimated)
3. HR2 fw (green) + HR2 py (yellow)
4. HR2 SQI fw + py

**Right panel:** BPF cutoff spinboxes, window/update interval spinboxes,
current-values table, [EXPORT CSV].

### 7.7 HR3TestWindow — "HR3TEST"

Purpose: verify Python HR3 (FFT+HPS) replica matches firmware output.

Layout: left 4 plots + right panel.

**Plots:**
1. FFT magnitude + HPS spectrum with detected peak marker
2. LP-filtered decimated signal (input to FFT)
3. HR3 fw (green) + HR3 py (yellow)
4. HR3 SQI fw + py

**Right panel:** LP cutoff, HPS harmonics count spinboxes, current-values table, [EXPORT CSV].

### 7.8 HR3LabWindow — "HR3LAB"

Purpose: diagnostic view combining FFT spectrum and HR algorithm comparison.

Layout: left (FFT spectrum with HPS peak line) + right (2 stacked: LP signal + HR1/HR2/HR3 comparison).

No parameter editing — purely observational.

### 7.9 HRLabWindow — "HR2LAB"

Purpose: interactive filter chain visualization for HR algorithm development.

3-column layout showing PPG signal chain variants side by side.
Each column shows a different filter combination to compare quality.

### 7.10 LabCaptureWindow

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

### 7.11 TimingWindow — "TIMING — CPU Budget & Load"

Purpose: display FreeRTOS algorithm timing stats from `$TIMING` / `$TASK` frames.

**Contents:**
- Bar chart: mean and max µs per algorithm (SpO2, HR1, HR2, HR3, full cycle)
- Stack free watermarks per task (afe4490, hr2, hr3)
- Task table: name, CPU%, stack words (from `$TASK` frames)

Updated on each received `$TIMING` + `$TASKS_END` batch.

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
| `PPGPlotsWindow/check_red_raw` … `check_ir_sub` | bool | Curve visibility |
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
| `LabCaptureWindow/geometry` | bytes | |
| `LabCaptureWindow/*` | mixed | Output dir, prefix, pre/post notes, column selection |

Settings are saved on window close and restored on startup.

---

## 10. Display conventions

### Color convention (curves and values)

| Color | Meaning |
|-------|---------|
| Green `#00CC44` | Data from firmware (`incunest_afe4490`) |
| Yellow `#FFDD44` | Data calculated by the Python script (HR1TEST, HR2TEST, HR3TEST, SpO2TEST) |
| Red tones | RED channel signals |
| Blue tones | IR channel signals |

### Tooltip convention

Every interactive control must use `_make_tooltip(name, text)`:
- Background: `#5500AA` (vivid purple)
- `name` in bold gold as first line
- `text` in light grey
- Fixed width 540 px, 8 px padding

### Action button style

`ACTION_BUTTON_STYLE` applies to all main action buttons:
- Normal: background `#555555`, white text, bold, 20px font
- Checked/active: background `#FF6666`
- Hover: background `#666666`

### Plot style

Dark background (`#121212`), light grid, white/colour curves.
Subwindow menu min-width: `QMenu { min-width: 360px; }` applied globally to prevent
pyqtgraph context menus from being too narrow to read.

---

## 11. Changelog

### v1.0 — 2026-04-14
- Initial spec. Documents the script as-shipped at the point of PulseNest repo separation
  from `acuesta-mow/incunest_afe4490_test`.
- Features covered: all subwindows, SpO2/HR1/HR2/HR3 algorithm replicas, LabCapture,
  SIGNAL STATS table (with gold cell highlighting and SQI colour coding),
  per-frame RED_Sub/IR_Sub integrity check, captures/ output directory,
  QMenu min-width fix, integer+thousands-separator formatting for raw ADC signals.
