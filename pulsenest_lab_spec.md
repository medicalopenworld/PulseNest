# pulsenest_lab — Specification v1.40

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

## 2.1 Crash diagnostics

The script is normally launched via `pythonw` (no console), so any unhandled error is
otherwise invisible. Two independent, complementary handlers are installed at the very
top of the module, before any other import:

| Handler | Catches | Output file |
|---------|---------|-------------|
| `sys.excepthook = _crash_handler` | Unhandled **Python** exceptions (any thread reachable by the interpreter) | `crash.log` (appended, timestamped) |
| `faulthandler.enable(file=..., all_threads=True)` | **Native-level** crashes (segfault, Qt/pyqtgraph C++ abort) that bypass `sys.excepthook` entirely | `faulthandler.log` (appended; file handle kept open for the process lifetime, never closed) |

Both log files live next to `pulsenest_lab.py` and are not cleared between runs. If the
process disappears with no visible cause, check `faulthandler.log` first — an empty
`crash.log` combined with a populated `faulthandler.log` indicates a native crash (e.g.
triggered by pyqtgraph axis autorange on extreme-scale data), not a Python-level bug.

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

### 4.2 Data frames ($M1–$M4)

All frames are ASCII lines terminated with `\r\n`. Fields are comma-separated.
Every frame ends with `*XX` where `XX` is the XOR checksum of the bytes between `$` and `*`.
Frames with bad checksum are silently discarded.

Frame mode is selected with the `$MODE,Mx` command (no checksum — see §4.3):

| Mode | Content | Firmware boot | pulsenest_lab default |
|------|---------|---------------|-----------------------|
| `$M1` | `$M1,<SmpCnt>,<Ts_us>,<PPG_DISP>*XX` — minimal | | |
| `$M2` | `$M2,<SmpCnt>,<Ts_us>,<PPG_DISP>,<SpO2>,<SpO2_SQI>,<HR3>,<HR3_SQI>,<RSQI>,<DiagCode>,<ProbeState>*XX` | | |
| `$M3` | Full `AFE4490Data` (22 fields, table below) | ✔ | |
| `$M4` | M3 + analog debug: `V_TIA`×4, `I_PD`×4, `OT_LED1`, `OT_LED2`, `CH_MASKS`, `RF1`, `RF2` | | ✔ |

**The two defaults differ, and that matters.** The ESP32 always boots in `$M3`
(`main.cpp` `g_incunest_frame_mode`); `$M4` is what pulsenest_lab *requests* (saved in the .ini).
`$MODE` carries no checksum, is not acknowledged, and the post-reset restore depends on a single
`# incunest_afe4490 started` banner arriving on the active transport — so the requested mode is
never evidence of the mode in force. **Field 0 of every data frame is the only ground truth**, and
the script must treat it as such: see §6.5.1.

#### $M3 — Full data frame

```
$M3,<SmpCnt>,<Ts_us>,<LED2>,<LED1>,<ALED2>,<ALED1>,<LED2_SUB>,<LED1_SUB>,
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
| `PPG_DISP` | float | Display PPG, OT domain (lib v0.69): BPF(OT_LED1/OT_LED2) → negated (display only). NOT normalized — a candidate `ppg_disp_norm` (PI-weighted [0..1]) is backlog. [A/A, tiny magnitude ~1e-5..1e-6] |
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

#### $M4 — Debug frame (default)

`$M4` = the 22 `$M3` fields followed by 11 analog debug fields from
`AFE4490DebugData::analog` (`AFE4490AnalogState`, lib ≥ v0.35), plus 2 RF fields
(lib ≥ v0.37) — 13 fields total:

```
...,<V_TIA_LED1>,<V_TIA_LED2>,<V_TIA_ALED1>,<V_TIA_ALED2>,
    <I_PD_LED1>,<I_PD_LED2>,<I_PD_ALED1>,<I_PD_ALED2>,
    <OT_LED1>,<OT_LED2>,<CH_MASKS>,
    <RF1>,<RF2>*XX
```

| Field | Format | Description |
|-------|--------|-------------|
| `V_TIA_*` | `%.4e` | TIA differential output voltage per channel [V] |
| `I_PD_*` | `%.4e` | Photodiode current per channel [A] |
| `OT_LED1`, `OT_LED2` | `%.4e` | Optical transmittance `(I_PD_LEDx − I_PD_ALEDx) / I_LEDx` [A/A], firmware-computed in `_compute_analog_state()` |
| `CH_MASKS` | `%04X` hex | Validity masks packed in 4 nibbles: bits[3:0]=`adc_sat_pos`, [7:4]=`adc_sat_neg`, [11:8]=`tia_over_fs`, [15:12]=`tia_over_lin`. Within each nibble, bit = channel per `AFE4490Ch`: LED1=0, ALED1=1, LED2=2, ALED2=3. `0000` = all channels CLEAN |
| `RF1`, `RF2` | string | Actual TIA feedback resistor in use for LED1/LED2 at this sample (e.g. `"500K"`, via `afeRFToStr()`) — the live config value, whoever set it (manual `$SET` or HGAC Phase 1 descent), so it is not a static config value. Renamed from `HGAC_RF1`/`HGAC_RF2` in lib v0.81/spec v1.29 — the old name wrongly implied HGAC always computed it |

The script requires ≥ 34 fields to accept the `$M4` analog block (frames from
firmware older than lib v0.35+`CH_MASKS` are parsed as `$M3` with zeroed analog data).
OT values are **not** computed locally anymore — they are read from the frame.

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
| `tiacf1` | 0–31 | LED1 TIA feedback capacitor code (CF1) — `CF_LED[4:0]`, 32 steps 5–250 pF |
| `stg21` | 0–4 | LED1 stage-2 gain index (RG1) |
| `stage2en1` | 0, 1 | Enable stage-2 for LED1 |
| `tiagain2` | 0–6 | LED2 TIA feedback resistor index (RF2) |
| `tiacf2` | 0–31 | LED2 TIA feedback capacitor code (CF2) — `CF_LED[4:0]`, 32 steps 5–250 pF |
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
     ensepgain=<v>,...,board=<v>,mac=<v>,fw=<v>,lib=<v>,build=<v>,libsha=<v>*XX
```

Emitted at startup, after `$SET`, and in response to `$CFG?`. Parsed by
`_on_cfg_frame_received()` → populates `_last_cfg` dict and updates `HWConfigWindow`.

**Provenance fields (firmware change, 2026-09-05/06).** `fw` = PulseNest firmware version
(`PULSENEST_FW_VERSION`, promoted from a literal inside the startup banner), `lib` =
`INCUNEST_AFE4490_VERSION`, and **two** git hashes, because the firmware is built from two
repositories and a change in one does not move the other's hash:

| Field | Repository | Macro |
|---|---|---|
| `build` | this project (`src/main.cpp` and everything around it) | `PULSENEST_GIT_HASH` |
| `libsha` | `incunest_afe4490` | `INCUNEST_GIT_HASH` |

They matter because the `FW_*` columns of a CSV become uninterpretable as soon as the algorithms
change, and a version number alone does not identify a build — during development most builds are
uncommitted work on top of the same version, which is what the hash pins down. A **`-dirty`
suffix** marks a working tree with uncommitted changes, i.e. a build that matches no commit and
cannot be reproduced from the hash alone. That is the normal case while developing, so staying
silent about it would be misleading.

`scripts/pre_build_hash.py` produces both. It previously looked for the library only under
`.pio/libdeps/<env>/incunest_afe4490`, a path that does not exist when the library is consumed
through the `lib/` symlink (the usual local setup), so the hash silently fell back to `unknown` —
which is exactly what the first captures after the OTA recorded. It now tries `lib/` first, then
libdeps, and takes the project root from `env["PROJECT_DIR"]` because PlatformIO `exec()`s the
script without setting `__file__`.

The firmware-side buffer was raised 600 → 720 bytes at the same time, **with an explicit truncation
guard**: `snprintf` was already truncating silently at the limit and the checksum was appended
afterwards regardless, so an over-long frame would have arrived as well-formed but incomplete. It
now emits `$ERR,CFG,frame truncated` instead.

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
- `# RESET_REASON: <reason>` — sent once over UDP after every boot (WiFi reconnect);
  logged as `[RESET] ESP32 rebooted — reason: <reason>`. Reasons: POWERON, SW_RESET,
  PANIC, INT_WDT, TASK_WDT, BROWNOUT, etc. Used to diagnose sporadic firmware resets.

Any other `#` line is appended to the Serial Console window (if open) but not logged.

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

Replicates `INCUNEST_AFE4490::_spo2_update()`.

**Constants:**

| Name | Value | Description |
|------|-------|-------------|
| `_DC_IIR_TAU_S` | 2.0 s | DC IIR time constant — mirrors `spo2_ema_mean_tau_s` |
| `_AC_EMA_TAU_S` | 6.0 s | AC² EMA time constant — mirrors `spo2_ema_var_tau_s`; ≥ 6 s is mandated by ISO 80601-2-61:2026 Annex JJ.2 d) |
| `_SPO2_MIN_DC` | 1000 | Minimum DC level to report SpO2. **No firmware counterpart** — the firmware dropped its own DC gate when probe presence moved to RSQM (lib v0.42); kept as a divide-by-small guard for offline replay of older captures |
| `_WARMUP_S` | 18.0 s | Warmup before reporting — mirrors `spo2_warmup_s` (= 3 × τ_var) |
| `SPO2_A` | 114.9208 | Calibration coefficient (SpO2 = A − B·R) |
| `SPO2_B` | 30.5547 | Calibration coefficient |
| `_SPO2_MIN` | 70.0 % | Valid SpO2 range lower bound |
| `_SPO2_MAX` | 100.0 % | Valid SpO2 range upper bound |

**Algorithm:** seed on first sample → IIR DC filter → AC extraction → EMA of AC² → R = (RMS_AC_red/DC_red) / (RMS_AC_ir/DC_ir) → SpO2 = A − B·R.

**Seeding (required for comparability):** the first sample sets `dc = x` and `ac2 = 0` and
returns `None`, mirroring `EmaChannel::update()` since lib v0.55. Ramping the DC up from zero
would leave `d = x − mean ≈ x` for the first ~3τ, inflating the AC² estimate — and therefore PI
and R — precisely during warmup. SPO2LAB exists to compare `R_loc` against `R_fw`, so an
algorithmic difference here reads as a firmware discrepancy that is not there.

**Note:** these constants are a mirror of the `defaults` namespace in `incunest_afe4490.cpp`.
Any drift produces a fake firmware-vs-local discrepancy in SPO2LAB, so they must be re-checked
whenever the library changes its SpO2 defaults.

`update(ir, red, fs)` returns a dict with `dc_ir`, `dc_red`, `rms_ac_ir`, `rms_ac_red`, `R`, `spo2`, `spo2_valid`, or `None` during warmup/invalid.

### 5.2 SpO2TestCalc

Extended version of `SpO2LocalCalc` with user-adjustable parameters (used in SpO2TestWindow).
All constants are exposed as instance attributes overridable at runtime from the UI spinboxes.

**EXPERIMENT (OT-domain input, branch `experiment/ot-domain-inputs`, mirrors lib v0.41):**
`update(ot_ir, ot_red, probe_state, fs)` — input is `OT_LED1`/`OT_LED2` [A/A] (gain-invariant
optical transmittance), not the raw ambient-corrected `LED1_SUB`/`LED2_SUB` used before this
migration, plus `probe_state` (RSQM's `ProbeState` ordinal — 0/1/2 for
DISCONNECTED/NOT_APPLIED/APPLIED, read from the already-parsed `ProbeState` column/field).
`OT_LED1`/`OT_LED2` only travel in the `$M4` frame — SpO2TestWindow requires `$M4` (live) or
a CSV captured in `$M4`; it shows a status-bar warning and stops feeding the calc otherwise.

**Presence detection is RSQM's responsibility alone — `SpO2TestCalc` never classifies
presence itself.** Two earlier attempts at a self-contained "no-finger"/"no-signal" gate
inside this class were tried and removed in turn: `spo2_min_i_pd_a` (absolute
`I_PD_LED1`/`I_PD_LED2` magnitude, mirroring firmware v0.38) and `spo2_min_ot_dc` (absolute OT
DC floor, mirroring firmware v0.40) — both mostly duplicated RSQM's own
disconnected/not-applied classification with a weaker, uncalibrated criterion (a
transmittance probe with no finger shows HIGH OT, not low i_pd/DC).

While `probe_state != PROBE_APPLIED` (2) — covering both NOT_APPLIED and DISCONNECTED
identically: internal state (`_dc_ir`/`_dc_red`/`_ac2_ir`/`_ac2_red`/`_sample_count`) is reset
every sample (idempotent, no stored "previous probe_state" needed — mirrors lib v0.41), and
`pi`/`spo2`/`spo2_r` are `nan`. What remains inside the class is only a purely numerical
division-safety guard, `FW_SPO2_DIV_EPS` (`1e-9`, not user-adjustable) — on `dc_ir` (PI calc
divisor) and `dc_red`/`rms_ac_ir` (R calc divisors). No UI parameter for presence detection
exists anymore — the "Min OT DC [ppm]"/"Min I_PD [µA]" spinboxes from earlier versions were
both removed; SpO2TestWindow's parameter panel is back to its original five: a, b, DC τ, AC τ,
warmup.

`DC LED1/LED2` and `RMS AC LED1/LED2` are displayed in ppm (×1e6) in SpO2TestWindow's plots
and value table, consistent with `OT_LED1`/`OT_LED2` in SIGNAL STATS.

### 5.3 HR1 variants — `HR1Variant` framework

**v1.33.** HR1 is the algorithm under active redesign, so its implementations are organised as a
family of variants sharing one base class. The base owns everything downstream of the peak
decision; a variant owns only how a sample becomes that decision. Two variants therefore differ
in exactly what they are meant to differ in, which is what makes a comparison between them
honest.

`HR1Param` / `HR1Curve` (namedtuples) let a variant declare its tunable parameters and its
diagnostic curves. HR1LAB builds its controls and its plots from those declarations, so adding a
variant costs one subclass plus one line in the `HR1_VARIANTS` registry — no UI code.

**Owned by `HR1Variant` (shared, never redefined by a variant):**

| Element | Detail |
|---|---|
| Probe gating | While `probe_state != PROBE_APPLIED`: `reset()` every sample, `hr_bpm`/`hr_sqi` → `nan`/`0` |
| Gap detection | `sample_counter` continuity; runs regardless of `probe_state` |
| Refractory veto | Variant reports the raw decision; the base vetoes it. `_refractory_samples(fs)` is overridable, for an RR-adaptive refractory |
| RR → HR → SQI | Buffer of `FW_RR_BUF_LEN` intervals, `HR = fs·60/mean(RR)`, `SQI = clamp(1 − CV/0.15, 0, 1)`, forced to 0 outside [`FW_HR_MIN_BPM`, `FW_HR_MAX_BPM`] |
| Peak marker | Display value forced to 0 for `FW_PEAK_MARKER_N` samples after a peak |
| Availability | `availability` ∈ [0,1]: fraction of the last `AVAILABILITY_WIN_S` (30 s) with `SQI > 0`. The metric that decides between variants — under interference the published HR stays accurate while the SQI gate discards most intervals |

**Implemented by a variant:** `_init_variant()`, `_reset_variant()`, `_recalc_variant(fs)` and
`_detect(sample, fs) -> (peak_raw, display_value)`, where `peak_raw` ignores the refractory
period and `display_value` is the waveform to plot.

#### 5.3.2 `HR1BiquadCalc` — the BPF variant

**v1.35.** Replaces SPEC's IIR DC remover + moving average with a single 2nd-order Butterworth
bandpass, ported from the library's `BiquadFilter::init_bp()` (same bilinear algebra, same DF-II
transposed structure, same steady-state precharge) so the bench measures what the firmware would
run. Verified against `scipy.signal.butter(1, [f_lo, f_hi], 'band')`: coefficients agree to 1e-17
and the -3 dB points land exactly on the requested corners.

Parameters: `bpf_low_hz` (default 0.5 Hz) and `bpf_high_hz` (default 5.0 Hz) replace
`dc_iir_tau_s`, `ma_cutoff_hz` and `ma_max_len`. Detector parameters (`running_max_decay`,
`threshold_factor`, `refractory_s`) are unchanged from SPEC, so any difference between the two
rows can only come from the filtering. The defaults isolate one variable: the low corner moves to
the 0.5 Hz the library already uses for `ppg_disp`, while the high corner stays where SPEC's
moving average already sits (-3 dB at ~4.4 Hz).

`_recalc_variant()` clamps the corners (`low < high`, both below 0.45·fs) — an inverted pair
yields a negative bandwidth and a silent NaN.

#### 5.3.0 Running-max decay — owned by the base

**v1.38.** The decay of the running maximum moved from a per-sample factor
(`running_max_decay = 0.9999`) to `max_decay_tau_s` in seconds, resyncing with the library's
`hr1_max_decay_tau_s` / `setHR1MaxDecayTauS()` (lib v0.87). A per-sample factor is not a
communicable quantity: 0.9999 is 20 s at 500 Hz but 6.25 s at 1600 Hz.

`max_decay_beats` (default 0 = the fixed tau above, i.e. firmware behaviour) makes the memory a
number of beats instead: `tau = N x RR`, so the threshold falls by the same fraction on every beat
at any rate. The lower bound on this parameter is proportional to RR — the threshold must not
collapse between beats — so expressed in seconds it differs 6x across the declared 40-300 BPM
range, which no single fixed value can satisfy.

`_update_decay_alpha()` lives in `HR1Variant` and recomputes the factor only on a rate change or a
new RR interval, never per sample. Both SPEC and BPF consume `self._decay_alpha_v`.

Verified: at 500 Hz with defaults, output is identical sample-by-sample to the pre-change
implementation at 45/60/140/250 BPM. (The library's spec says 20 s reproduces 0.9999 "exactly";
it does so to 5e-9 — the exact value is 19.999 s — with no effect on any detection.)

#### 5.3.1 `HR1TestCalc` — the SPEC variant

Replicates `INCUNEST_AFE4490::_hr1_update()`. **Frozen by definition:** it tracks the library and
never explores. New ideas go in a sibling `HR1Variant` subclass, never here — HR1TEST's value as
a verification window depends on this variant not drifting from the firmware.

**Algorithm:** IIR DC removal → moving average LP filter (cutoff 5 Hz) → threshold-based peak detection (threshold = 0.6 × running max) → refractory period 185 ms → RR intervals buffer (5 intervals) → HR = 60 / mean(RR).

SQI: `1 − CV/0.15` where CV = std(RR)/mean(RR); clamped to [0, 1]. SQI = 0 if < 2 peaks.

**EXPERIMENT (OT-domain input, mirrors lib v0.39):** `update(ot_led1, fs, sample_counter=None)`
— input is `OT_LED1` [A/A], not raw `LED1_SUB`. No threshold recalibration needed: peak timing
(relative running-max threshold) and CV are invariant to a uniform input scale. Requires `$M4`
— HR1TestWindow's full-rate (500 Hz, pre-decimation) live feed now listens for `$M4` frames
instead of `$M1` (which never carries `OT_LED1`); shows a status-bar warning and stops feeding
the calc when frame mode is not `$M4`.

**v1.24: `probe_state` (mirrors lib v0.42):** `update(ot_led1, fs, probe_state, sample_counter=None)`
— `probe_state` (RSQM's classification, `PROBE_DISCONNECTED`/`NOT_APPLIED`/`APPLIED` = 0/1/2
class constants) consumed, never computed here. While `probe_state != PROBE_APPLIED`:
`reset()` runs every sample (idempotent), `hr_bpm`/`hr_sqi` forced to `nan`/`0`. Gap detection
(via `sample_counter`) still runs regardless of `probe_state` — it tracks frame continuity, not
finger presence.

### 5.4 HR2TestCalc

Replicates `INCUNEST_AFE4490::_hr2_update_for_test()` via `_estimate_hr_autocorr_v2()`.

**Algorithm:** 2nd-order Butterworth bandpass [0.5–5 Hz] → decimate ×10 (500 → 50 Hz) → circular buffer 400 samples (8 s) → every 25 decimated samples: unbiased normalised autocorrelation (FFT-based, `scipy.signal.correlate`) → find first significant peak above min_lag → HR = 60 / peak_lag.

SQI = normalised autocorrelation value at peak [0–1].

Two internal cross-correlation implementations:
- `_estimate_hr_xcorr_v1()` — cross-correlation variant (reference, not used in production path)
- `_estimate_hr_autocorr_v2()` — true autocorrelation (production, matches firmware)

**EXPERIMENT (OT-domain input, mirrors lib v0.39):** `update(ot_led1, fs)` — input is `OT_LED1`
[A/A], not raw `LED1_SUB`. Firmware recalibrated its near-zero-energy guard to
`hr2_ot_energy_eps` for the OT scale; this mirror's own guard (`acorr0 != 0`) is already
scale-agnostic, so no constant changed here. Requires `$M4`.

**v1.24: `probe_state` (mirrors lib v0.42):** `update(ot_led1, fs, probe_state)` — same design
as HR1TestCalc above: while `probe_state != PROBE_APPLIED`, `reset()` runs every sample and
`hr_bpm`/`hr_sqi` are forced to `nan`/`0`.

### 5.5 HR3TestCalc / HRFFTCalc

Replicates `INCUNEST_AFE4490::_hr3_update_for_test()`.

**Algorithm:** 2nd-order Butterworth LP 10 Hz (anti-aliasing) → decimate ×10 → circular buffer 512 samples (10.24 s) → every 25 decimated samples: Hann window → real FFT → Harmonic Product Spectrum (HPS, 2nd and 3rd harmonics) → peak in [25, 240] BPM → HR = peak_freq × 60.

SQI = HPS peak prominence in the search range [0–1].

`HRFFTCalc` is the base class. `HR3TestCalc` extends it with user-adjustable parameters for the HR3TestWindow.

**EXPERIMENT (OT-domain input, mirrors lib v0.39):** `HR3TestCalc.update(ot_led1, fs,
sample_counter=None)` — input is `OT_LED1` [A/A], not raw `LED1_SUB`. No threshold
recalibration needed: the HPS ratio/SQI are invariant to a uniform input scale. Requires
`$M4`. Note: `HRFFTCalc`/`self.hr3_calc` ("HR3LAB" diagnostics, distinct from `HR3TestCalc`)
was intentionally left unmigrated — still fed raw `LED1_SUB` — out of scope for this
experiment (analogous to `SpO2LocalCalc`/SpO2LAB and `PICalc`/PILAB, also unmigrated).

**v1.24: `probe_state` (mirrors lib v0.42):** `HR3TestCalc.update(ot_led1, fs, probe_state,
sample_counter=None)` — same design as HR1TestCalc/HR2TestCalc above: while
`probe_state != PROBE_APPLIED`, `reset()` runs every sample and `hr_bpm`/`hr_sqi` are forced
to `nan`/`0`. Gap detection (via `sample_counter`) still runs regardless of `probe_state`.
`HRFFTCalc`/`self.hr3_calc` remains out of scope, as above — no `probe_state` added there.

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

**Header row** (`stats_header`, left to right): the `SIGNAL STATS` title, a stretch, the quick
HW controls (§6.3.1), then `Update interval:` + `spin_stats_interval`.

#### 6.3.1 Quick HW controls — HGAC / RF1 / RF2

Three combo boxes in the SIGNAL STATS header. They are both a **live mirror** of the hardware
state and **direct actuation**: selecting a value sends `$SET` immediately, with **no Set button**.
The purpose is not having to open HW CONFIG to see or change the RF in use.

| Control | Widget | Items | `$SET` key | Mirror source |
|---------|--------|-------|-----------|---------------|
| `HGAC:` | `combo_quick_hgac` | `OFF`, `ON` (index = value) | `hgac_enable` | `hgac_enable` in `$LCFG` |
| `RF1:` | `combo_quick_rf["tiagain1"]` | `TIA_GAINS` (`10K`…`1M`) | `tiagain1` | `$M4` field 34, **and every** `$CFG` `tia1` |
| `RF2:` | `combo_quick_rf["tiagain2"]` | `TIA_GAINS` (`10K`…`1M`) | `tiagain2` | `$M4` field 35, **and every** `$CFG` `tia2` |

**Required behaviour** — each item exists to prevent a specific failure:

1. **Signal is `activated`, never `currentIndexChanged`.** `activated` fires only on user
   interaction. Mirroring an HGAC-driven RF change into the combo must not feed back as a
   command, or `$SET → new RF → new $M4 → $SET` loops forever. `setCurrentIndex()` from the
   mirror path is therefore silent by construction.
2. **Mouse wheel blocked unconditionally** (`_WheelBlockFilter(always=True)`). With no Set
   button, one accidental scroll would step through the item list firing a `$SET` per step,
   each triggering its own hardware settling window.
3. **RF combos are disabled while HGAC is enabled.** HGAC v1 is RF-only and actuates whenever
   ProbeState is `APPLIED` or `SATURATING`, so it reverts any manual RF within ~200 ms.
   Switching `HGAC:` to `OFF` is what hands RF over to the user. Disabled combos are styled
   `_QUICK_CSS_OFF` (grey) instead of `_QUICK_CSS_ON` (green = firmware value, §10).
4. **RF1 additionally disabled when `ENSEPGAIN=0`** (read from the cached `$CFG`): the chip
   then ignores `tiagain1` and drives both channels from `tiagain2`, so editing RF1 would
   silently do nothing. Re-evaluated on every `$CFG` frame.
5. **Mirror runs in the render tick (200 ms), never in the 20 ms drain.** `_last_hgac_rf` is
   tracked in `_process_frames_tick()` (a `split` and a tuple compare); `_sync_quick_hw_controls()`
   pushes it into the combos from `_refresh_plots_tick()`, per §6 drain/render separation.
6. **In `$M1`–`$M3` the per-sample mirror has no source** (fields 34-35 are absent), so `$CFG`
   (`tia1`/`tia2`) is the *only* source and **every** `$CFG` frame must re-apply it — not just
   the first. Treating `$CFG` as a one-shot seed (`if _last_hgac_rf is None`) is a known bug:
   it froze the header combos at the first value while HW CONFIG, fed unconditionally by
   `update_from_cfg()`, tracked every change — the RF appeared to update in HW CONFIG but not
   in the main window. Re-applying on every `$CFG` is idempotent in `$M4`: the next sample
   overwrites `_last_hgac_rf` from fields 34/35 with the same value.
7. **`_quick_rf_shown` is only advanced once both combos actually show the value.** If
   `findText()` fails (unknown RF string: firmware/script mismatch, corrupted frame) the marker
   is left untouched so the next render tick retries, instead of recording a value that was
   never displayed.

`_last_hgac_rf` is tracked regardless of whether HW CONFIG is open. The coalesced `$CFG?`
refresh that mirrors an HGAC RF change into HW CONFIG's own combos still only fires when that
window exists.

**Methods** (all on `PPGMonitor`): `_on_quick_hgac_activated()`, `_on_quick_rf_activated()`,
`_sync_quick_hgac_combo()`, `_apply_quick_rf_enabled()`, `_sync_quick_hw_controls()`.

Located in the right panel. Rows = 30 signals (`_STATS_SIGNALS`) + a separator row after
the 4 raw ADC rows (`tbl_row = sig_idx if sig_idx < 4 else sig_idx + 1`). Columns:

| Col | Name | Description |
|-----|------|-------------|
| 0 | Signal | Row label |
| 1 | V_TIA | Estimated TIA differential output voltage (V) — raw rows only |
| 2 | V_ADC | Estimated ADC input voltage (V) — raw rows only |
| 3 | % SD/Mean | Coefficient of variation as percentage (LED1_SUB/LED2_SUB rows; R estimate on R row) |
| 4 | Mean | Mean value over stats interval |
| 5 | SD | Standard deviation |
| 6 | Max-Min | Peak-to-peak range |
| 7 | Min | Minimum value |
| 8 | Max | Maximum value |

**Signal ordering (IR-first, mirrors firmware $M3 frame):**
LED1 (IR), LED2 (RED), ALED1, ALED2 (sig_idx 0–3, raw ADC — integer + narrow-space thousands separator `\u202f`),
LED1_SUB, LED2_SUB (4–5),
PPG_DISP, SpO2, SpO2_SQI, R, PI, HR1, HR1_SQI, HR2, HR2_SQI, HR3, HR3_SQI, RSQI, DiagCode,
ProbeState (6–19, 2 dp),
V_TIA_LED1/LED2/ALED1/ALED2 (20–23, 6 dp V), I_PD_LED1/LED2/ALED1/ALED2 (24–27, µA 3 dp),
OT_LED1 [ppm], OT_LED2 [ppm] (28–29, displayed ×1e6 for readability, 2 dp — **read from the
$M4 frame**, not computed locally; $M4 mode only. Wire protocol unchanged: firmware still
sends raw A/A in `%.4e` — the ×1e6 + 2dp formatting is local to the Python display only).

**V_TIA / V_ADC columns (cols 1–2):** populated only for rows 0–3 (LED1, LED2, ALED1, ALED2).
Calculated from the current ADC mean using the AFE4490 gain chain (V_TIA is the differential
TIA output = 2 × I_PD × RF; the code has no separate branch value):
- V_ADC = (mean_counts / 2²¹) × 1.2 V  (ADC full scale ±1.2 V, 22-bit signed)
- V_TIA = 2 × (V_ADC / (2 × RG) + I_CANCEL) × RI  (datasheet eq.2, p.30)
  where RI = 100 kΩ (fixed), RG from current `$CFG` stg21/stg22 field, I_CANCEL = ambdac × 1 µA.

**V_TIA / V_ADC color coding (background of cols 1–2):**

The two columns answer different questions and deliberately use different criteria:
**V_TIA = HGAC policy** (what the controller is doing), **V_ADC = ADC/TIA physics** (what the
silicon can represent). HGAC actuates on `v_tia`, never on `v_adc`, so importing its thresholds
into the V_ADC column would misrepresent them.

**V_TIA — one colour per HGAC actuation state.** Thresholds are read live from `$LCFG`
(`hgac_v_tia_high2` / `high1` / `low1`) into `self._hgac_thr`, seeded from
`_HGAC_THR_DEFAULTS` (0.90 / 0.75 / 0.20) until the first frame arrives. They are
runtime-tunable (`$SET hgac_*`, LIB CONFIG window), so they must **never** be hardcoded here —
the gauge drifted out of sync twice that way. Comparison operators mirror `_hgac_track()`
exactly (`>= high2`, `>= high1`, `< low1`), so green is the half-open interval `[LOW1, HIGH1)`.

| Color | Hex | LED rows (0,1) | ALED rows (2,3) |
|-------|-----|----------------|------------------|
| Gray text on `#121212` | `#5A5A5A` | channel CLIPPED (CH_MASKS) — overrides all below | same |
| Red | `#4A0800` | `≥ HIGH2` — guard: urgent RF reduction | `≥ HIGH2` — ambient high |
| Yellow | `#3A2D00` | `≥ HIGH1` (leveling reducing RF) or `< LOW1` (leveling raising RF) | — (no intermediate ambient threshold exists) |
| Green | `#0F3A0F` | `[LOW1, HIGH1)` — leveling dead band, HGAC does nothing | `< HIGH2` |
| Default | `#121212` | Row not in {0,1,2,3} or no data | — |

There is no "ideal operating point": HGAC holds a dead **band**, it does not chase a setpoint —
so the gauge shows a band, not a target. The ALED row has no yellow because HGAC's ambient alarm
(`RSQM_DIAG_AMBIENT_HIGH`) requires **both** ambient EMA `≥ HIGH2` **and** RF already at the
floor; red therefore means "ambient high", not "alarm raised".

**V_ADC — physics only, identical bands on all 4 rows** (ADC saturation is channel-agnostic).
Mirrors the library's channel-state taxonomy:

| Color | Condition | Library state |
|-------|-----------|---------------|
| Red | `≥ _ADC_SAT_V` (≈1.1997 V = `adc::SAT_POS`, measured on 16.A) | CLIPPED_RANGE — reading is a bound |
| Yellow | `_TIA_FS_V` (1.0 V) – `_ADC_SAT_V` | EXTENDED_RANGE — past TI's guarantee, still linear |
| Green | `< _TIA_FS_V` | VALID_RANGE — inside TI's full-scale guarantee |

No low-end warning on V_ADC: physics says nothing about "too small". That judgement is HGAC's
and lives in the V_TIA column (`LOW1`).

**Tooltips** for these 8 cells are generated by `_refresh_vtg_tooltips()`, called when the table
is built and again from `_on_lcfg_frame_received()` on every `$LCFG`, so the documented numbers
always match the thresholds in force. Each tooltip states whether the values are live or
defaults, and carries this caveat: the cell shows the **mean over the stats window** while HGAC
decides on **EMAs** (τ≈0.1 s guard, τ≈2 s leveling), so the colour *approximates* HGAC's state
and may disagree transiently — a red cell does not prove the guard is acting.

> **Known minor inconsistency (not changed):** the displayed V_ADC uses
> `_ADC_FS_COUNTS = 2²¹−1` as divisor while `_ADC_SAT_V` and the library's `adc::SCALE` use
> `2²¹`. The difference is ~0.5 ppm (irrelevant at display resolution), but the library's
> reasoning (`namespace adc`) says `2²¹` is the correct divisor.

**Validity gray-out (CH_MASKS, lib v0.35 — CLIPPED criterion):** the parser ORs every received
`CH_MASKS` field into `_stats_ch_masks_or`; at each table update the accumulator is collapsed
into a per-channel CLIPPED bitmap and reset:
`_clipped = (_m | _m>>4 | _m>>12) & 0xF` — nibbles `adc_sat_pos` | `adc_sat_neg` | `tia_over_lin`
(bit = channel per `AFE4490Ch`). The `tia_over_fs` nibble (OFF_SPEC, 1.0–1.8 V diff) is
**excluded**: out of TI spec but empirically linear on IncuNest 16.A — the value is still real.
CLIPPED = the value is a bound, not reality (mirrors library `CH_CLIPPED_RANGE`).
Row→channel map `_STATS_ROW_TO_CH = {0:0, 1:2, 2:1, 3:3}`.
Effects when a channel was CLIPPED at any point in the stats window:
- V_TIA / V_ADC cells (rows 0–3) → gray text `#5A5A5A` on neutral background `#121212`
  (the voltage gauge color is suppressed — it would be computed from bound values and mislead).
- V_TIA_* rows (20–23) and I_PD_* rows (24–27) → gray text `#5A5A5A` on cols 4–8
  if their own channel was CLIPPED (`_STATS_ROW_TO_CH[(sig_idx − 20) % 4]`).
- OT_LED1 row (28) → gray text `#5A5A5A` if LED1 **or** ALED1 CLIPPED;
  OT_LED2 row (29) likewise for LED2/ALED2.
Visual rule: **gray text = "this number is not real"**, uniform across the whole table.
Backgrounds are reserved for semantic gauges (voltage ranges, SQI).

**SQI colour coding (Mean column, col 4):** HR1, HR2, HR3 rows (indices 11, 13, 15):
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
| HGAC / RF1 / RF2 | Quick HW controls, see §6.3.1 — apply on selection, no Set button |
| Frame mode combo | `$M1`–`$M4`; mirrors the mode in force and requests a change, see §6.5.1 |
| UDP WiFi button | Toggle UDP receiver on/off; switches active transport |
| UDP port spin | UDP listen port (default 5005) |
| Subwindow buttons | Toggle-open/close each secondary window |

#### 6.5.1 Frame mode combo — mirror, not a setting

`frame_mode_combo` (sidebar) is a **live mirror of the mode the firmware is actually sending**,
and secondarily a request for a change. Same philosophy as the quick RF combos (§6.3.1): what the
hardware is doing is the only thing worth displaying.

| Attribute | Meaning |
|-----------|---------|
| `frame_mode` | Mode **requested** of the firmware. Persisted (`PPGMonitor/frame_mode`). Not evidence of anything. |
| `_frame_mode_live` | Mode **in force**, read from field 0 of every data frame in the drain path. `None` until the first frame. Ground truth. |
| `_frame_mode_shown` | Last live value pushed into the combo (change detection). |
| `_frame_mode_mism_since` | `perf_counter()` of the first render tick of the current mismatch. |
| `_frame_mode_retries` | `$MODE` re-sends spent on the current mismatch (max `_FRAME_MODE_MAX_RETRIES`). |

**Required behaviour:**

1. **The wire is tracked before checksum validation and before decimation**
   (`_process_frames_tick()`, a 2-char slice: `line[1:3] in _FRAME_MODES and line[3:4] == ','`).
   Tracking after decimation would starve the mirror at high decimation ratios; tracking after the
   checksum check would lose it exactly when the link is degraded, which is when it matters.
2. **The combo displays `_frame_mode_live`**, falling back to `frame_mode` only until the first
   data frame arrives (`_update_frame_button()`).
3. **A user selection sends `$MODE` and leaves the combo where the user put it.**
   `_send_frame_cmd()` does not correct the combo inline — the next render tick re-asserts the
   live value, so a change that took shows the new mode and one that did not snaps back to the
   real one. Correcting it inline would flicker old → new on every successful change.
4. **A mismatch that persists `_FRAME_MODE_MISM_S` (1 s) re-sends `$MODE`**, up to
   `_FRAME_MODE_MAX_RETRIES` (5), one per mismatch episode-tick, logging each attempt
   (`_sync_frame_mode_live()`, render tick). 1 s is comfortably longer than the 500 ms post-reset
   restore delay, so the normal boot transient (firmware in `$M3` until the restore lands) never
   triggers a re-send.
5. **Bounded, then quiet.** After 5 failed re-sends the script stops and keeps showing the live
   mode. Hammering a dead channel helps nobody, and the display is still honest.
6. **`_send_frame_cmd()` logs when there is no command channel** instead of returning silently —
   a silent return left the combo advertising a mode the firmware had never been told about.
7. **The live mode chooses the CSV header** of a live recording (`toggle_save()`), not the
   requested one: an `$M4` header over `$M3` rows mislabels every column.

**Methods:** `_update_frame_button()`, `_on_frame_mode_combo_changed()`, `_send_frame_cmd()`,
`_sync_frame_mode_live()`.

**Known gap:** the reconciliation runs in the render tick, which early-returns while the display
is frozen (`_render_pending`), so a mismatch is not corrected while FREEZE DISPLAY is on. Same
limitation as the §6.3.1 mirrors.

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
5. DC OT_LED1 (IR) + DC OT_LED2 (RED) [ppm]
6. RMS AC OT_LED1 (IR) + RMS AC OT_LED2 (RED) [ppm]

**Right panel:** parameter spinboxes (DC tau, AC tau, A, B, warmup — no presence-detection
parameter anymore, see §5.2), live current-values table, [EXPORT CSV] button, [LOAD CSV] for
offline reprocessing.

**EXPERIMENT (OT-domain input):** requires frame mode `$M4` — feeds on `OT_LED1`/`OT_LED2`
and `ProbeState`, none of which travel in `$M1`/`$M2`/`$M3`. Live mode shows a status-bar
warning and stops feeding the calc when the active mode is not `$M4`. [LOAD CSV] only accepts
`$M4` rows — a file with no `$M4` samples raises a clear error instead of silently
reprocessing stale/zero data.

### 7.8 HR1TestWindow — "HR1TEST"

Purpose: verify Python HR1 replica matches firmware output.

Layout: left 4 plots + RR distribution + right panel.

**Plots:**
1. Signal chain: raw OT_LED1 → DC-removed → LP-filtered
2. HR1 fw (green) + HR1 py (yellow)
3. Delta HR1
4. HR1 SQI fw + py

**Bar chart:** RR interval distribution (last N beats).

**Right panel:** parameter spinboxes, current-values table, [EXPORT CSV], [LOAD CSV].

**EXPERIMENT (OT-domain input):** requires frame mode `$M4` — the full-rate (500 Hz,
pre-decimation) live feed listens for `$M4` frames (`OT_LED1` field) instead of `$M1`, which
never carries it. Status-bar warning shown when not in `$M4`. [LOAD CSV] only accepts `$M4`
rows.

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

**EXPERIMENT (OT-domain input):** requires frame mode `$M4` — feeds on `OT_LED1`, not in
`$M1`/`$M3`. Status-bar warning shown when not in `$M4`. [LOAD CSV] only accepts `$M4` rows.

### 7.10 HR3TestWindow — "HR3TEST"

Purpose: verify Python HR3 (FFT+HPS) replica matches firmware output.

Layout: left 4 plots + right panel.

**Plots:**
1. FFT magnitude + HPS spectrum with detected peak marker
2. LP-filtered decimated signal (input to FFT)
3. HR3 fw (green) + HR3 py (yellow)
4. HR3 SQI fw + py

**Right panel:** LP cutoff, HPS harmonics count spinboxes, current-values table, [EXPORT CSV], [LOAD CSV].

**EXPERIMENT (OT-domain input):** requires frame mode `$M4` — feeds on `OT_LED1`, not in
`$M1`/`$M3`. Status-bar warning shown when not in `$M4`. [LOAD CSV] only accepts `$M4` rows.

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

### 7.12 HR2LabWindow — "HR2LAB"

**v1.36:** renamed from `HRLabWindow` — the class, `btn_hrlab`, `toggle_hrlab`, `_open_hrlab_default`, the `plot_hrlab` timing slot and the `hrlab_open` / `HRLabWindow` settings keys all lacked the "2" the window has shown since HR3LAB appeared. Existing `.ini` keys were migrated in place, so saved geometry and open-state survive.

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
- Column selection checkboxes (subset of M1 fields, plus $M4-only fields added 2026-08-22:
  V_TIA_LED1/2/ALED1/2, I_PD_LED1/2/ALED1/2, OT_LED1/2, CH_MASKS, and RF1_OHM/RF2_OHM added
  2026-08-24 — all read "-1" outside $M4 mode)
- `RF1_OHM`/`RF2_OHM` are the one exception to "write the wire field verbatim": the frame's
  `RF1`/`RF2` (§4.2) carry a display string (`"500K"`), which a time-series/plotting tool
  can't read as a number. `_write_lab_capture_row()` converts it to ohms via `_RF_STR_TO_OHM`
  (a closed lookup mirroring `AFE4490RF`/`afeRFToStr()`, not a generic suffix parser) before
  writing the row — unrecognized strings (including our own "-1" fallback, or firmware's "?"
  for an invalid enum) fall through to "-1". Hence the `_OHM` suffix in the CSV column name,
  unlike the frame field itself
- Mode: continuous / timed (N samples)
- Progress bar (timed mode)
- [START] / [STOP]
- **Column profiles** (added 2026-09-05): two preset buttons that tick the checkboxes.
  *Data (raw only)* keeps the 10 columns that cannot be reconstructed later — `SmpCnt`, `Ts_us`,
  the four raw channels, `RF1_OHM`/`RF2_OHM`, plus `LED1_SUB`/`LED2_SUB` (derivable, but flagged
  mandatory since they are the offline runner's input). ~36 % of the file size: ~2.7 MB per 90 s
  against ~7.5 MB. *Witness (everything)* keeps all 35 columns; its purpose is not the data but
  the cross-check — it is the only way to verify that the offline runner reproduces what the
  firmware computed, so one per session suffices.
- **Read chip config automatically** checkbox (default ON, added 2026-09-05) — see below.
- **Disable HGAC during capture** checkbox (default OFF, added 2026-09-05) — see below.

**Output file:** `lab_capture_*.csv` in `CAPTURES_DIR`. All state persisted in .ini.

**Automatic configuration recording (2026-09-05).** The `#` header used to be whatever the
operator had left in the "Pre-capture notes" box, filled by pressing *Read chip config*, which
pastes a snapshot of that instant. The text persists between captures, so changing RF, ILED or PRF
without pressing the button again leaves a header confidently stating the *previous*
configuration. Verified case: the four `SUBJ01_A57_RF100K/RF250k_20260823_*` captures all carry
`TIA=250K` in the header while the mean `LED1` amplitude (357 k/369 k against 932 k/914 k, ratio
2,54 ≈ 250 k/100 k) proves two were taken at 100 kΩ. **The header was the least reliable record in
the file, precisely because it looked like the most reliable one.**

With the checkbox on, `_begin_capture()` becomes a small state machine, because `$CFG?` is
answered asynchronously:

1. If *Disable HGAC* is also on, `$SET,hgac_enable,0` goes out **first** — otherwise the header
   would record a state about to change.
2. `$CFG?` is sent and `_pending_capture` holds the capture arguments. A 2.5 s `QTimer` guards it.
3. The reply reaches `_on_cfg_received()`, which starts the capture with that text as the header.
4. On STOP, `$CFG?` is sent again; the reply is compared against the opening one (ignoring its
   timestamp line) and written as a post-note saying whether the configuration **changed during
   the capture** — which is exactly what HGAC moving RF would do, and is invisible today.

Failure handling is deliberately asymmetric: **a missing reply at the start aborts the capture**
(for a verification set, no capture beats one of unknown provenance), while a missing reply at the
end still closes the file, noting `NOT READ` — the recorded samples must not be lost over a
metadata read. `_restore_hgac()` runs on every exit path: normal stop, timeout, abort, and
`closeEvent`.

Both checkboxes are disabled while capturing: they describe what the hardware was doing while the
file was written, so toggling them mid-capture would make the header a lie.

The header text itself is built by `_on_cfg_frame_received()` from the `$CFG` key-values, and its
last line reports provenance: `Firmware: PulseNest v<fw>   incunest_afe4490 v<lib>   build <hash>`.
A `?` in any of the three means the board runs a build older than 2026-09-05. Note that adding a
field to the frame is not enough on its own — the formatter drops anything it does not name, which
is exactly how the first flashed capture came out without its version line.

⚠️ **Freezing HGAC removes the only thing that corrects saturation.** With the checkbox on, nothing
lowers RF when the TIA hits the rail, and the whole file is clipped: the first test capture after
the OTA showed `LED1` and `LED2` pinned at 2 096 921 (21-bit full scale is 2 097 151) for every
sample, with RF=100K and ILED 49.8 mA. Settle the gain at a valid operating point and check it in
SIGNAL STATS **before** ticking the box. A clipped capture is not even usable for regression, since
it contains no signal.

**HGAC freeze.** HGAC changes RF mid-capture, injecting gain-change transients into the signal, and
PI/R carry a known bias while the EMAs settle afterwards. For characterisation captures the analog
chain must stay frozen or the algorithm's behaviour cannot be told apart from its reaction to a
gain change. Default OFF because for the RF-sweep captures of `CAPTURE_SET_SPEC.md` §3.5 H1,
observing that transient *is* the purpose. The forced state is written into the header, so a
capture without HGAC is never confused with one where HGAC merely did not act. Only a state known
to have been on is restored — restoring one that was never read would be a guess.

**Row filter (mandatory).** `_write_lab_capture_row()` writes a row **only** for data frames —
`$M1`, `$M2`, `$M3`, `$M4`. Any other line arriving on the stream (`$CFG` replies, `$ERR`, …) is
discarded and does not advance the sample counter. Without this filter the non-data fields get
indexed against the column spec and land in the file as a well-formed row of garbage (e.g.
`sr=500,numav=8,led1=49.80,…` with exactly as many fields as the header), which silently corrupts the
capture and makes CSV readers infer text columns. This is not hypothetical: it happened once the
HGAC-driven auto-`$CFG?` refresh was added, which injects `$CFG` replies into the stream *during* a
capture.

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

Purpose: view and change RSQM / HGAC library parameters in real time via `$SET`/`$LCFG` protocol.

**Contents (RSQM group):**
- OT threshold (`rsqm_ot_thr`) — NOT_APPLIED vs APPLIED boundary [A/A]
- DISCONNECTED LED_sub threshold (`rsqm_disconn_led_sub_thr`) [ADC counts]
- DISCONNECTED I_PD threshold (`rsqm_disconn_i_pd_thr`) [nA displayed, A stored]
- Probe debounce (`rsqm_probe_state_min_s`) [s] — converted to samples from `fs` internally
- (RSQM's `signal_weak_std` and `ema_mean/var_tau_s` were removed with the estimator cleanup — lib v0.56/v0.57.)

**Contents (HGAC group, added 2026-08-09):** — see incunest_afe4490 §5.8
- HGAC (`hgac_enable`) — combo Disabled/Enabled (index 0/1 → $SET value); master enable (Disabled = HGAC never actuates)
- HIGH2 guard (`hgac_v_tia_high2`) [V] — fast-EMA guard threshold
- HIGH1 level ↑ (`hgac_v_tia_high1`) [V] — slow-EMA leveling upper
- LOW1 level ↓ (`hgac_v_tia_low1`) [V] — slow-EMA leveling lower
- Fast EMA τ (`hgac_ema_fast_tau_s`) [s] — guard estimator
- Slow EMA τ (`hgac_ema_slow_tau_s`) [s] — leveling estimator
- Ambient EMA τ (`hgac_ema_ambient_tau_s`) [s] — ALED estimator for the AMBIENT_HIGH alarm

- [Read from chip ($LCFG?)] — requests `$LCFG?` from firmware
- [Set all] — sends `$SET` for `hgac_enable` and every RSQM + HGAC parameter in the window
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

**Output file:** CSV path from the window's text field (default `afe_sweep_test.csv`; header written
only if the file does not exist). 92 columns, in order:
1. `probe_state_expected`, `probe_state_calculated`, `probe_state_check` (OK/NOT OK)
2. `label`, `datetime`, `LED1mA`, `LED2mA`, `RF1`, `RF2`, `RG1`, `RG2`, `ambdac_uA`, `n_samples`
3. For each of 6 signals (LED2, LED1, ALED2, ALED1, LED2_Sub, LED1_Sub), grouped by stat type:
   all `_mean`, then all `_min`, `_max`, `_pp`, `_std` (30 columns)
4. RSQM: `rsqi_ok_pct`, `diag_code_{mean,min,max}`, `probe_state_fw_{mean,min,max}`
5. `V_TIA_{LED1,LED2,ALED1,ALED2}_{mean,std,min,max}` [V] — per-sample values received
   from the `$M4` frame (firmware `_compute_analog_state()`), buffered during MEASURING
6. `I_PD_{LED1,LED2,ALED1,ALED2}_uA_{mean,std,min,max}` [µA] — same source, ×1e6
7. `I_PD_LED{1,2}_ALED{1,2}_diff_uA_{mean,std,min,max}` [µA] — per-sample LED−ALED difference
8. `OT_LED1`, `OT_LED2` — optical transmittance `(mean(I_PD_LED) − mean(I_PD_ALED)) / I_LED`
   [A/A, dimensionless], same formula as firmware `_rsqm_update()`; I_LED from the combo's
   LED mA value. Empty if I_PD buffers are empty (non-$M4 mode) or LED mA is not numeric.

#### _ComboSpin widget

All sweep-parameter spins use a custom `_ComboSpin` widget (QComboBox subclass) with a
QSpinBox-compatible API:

- `value()` → `currentIndex() - 1` (None item at index 0 returns -1; real items start at 0)
- `setValue(v)` → `setCurrentIndex(v + 1)`

This allows the same `_build_combos()` / `_apply_combo()` logic to treat `value() < 0` as "skip this parameter".

---

### 7.19 HR1LabWindow — "HR1LAB"

**v1.34.** Bench for exploring HR1 peak-detection variants. Sidebar button in ANALYSIS, above
HR2LAB. Requires frame mode `$M4` (runs on `OT_LED1`).

Every variant in `HR1_VARIANTS` gets one collapsible row and is fed **the same sample in the same
call** (`feed_sample()`), so comparing them live is rigorous: they see an identical signal. The
window is for **exploration, not validation** — provoke a failure by hand (move the finger, change
ambient light, switch the phototherapy lamp on) and watch which variant breaks and why. Deciding
between the survivors is a separate batch run over the capture set with known truth, and is not
part of this window.

**Row (`HR1LabRow`)** — built entirely from the variant's declarations, so a new variant needs no
UI code:

| Zone | Content |
|---|---|
| Header | Collapse arrow, variant `NAME`, `run` checkbox, live `HR` / `SQI` / `AVAIL` |
| Left | Plot of the curves declared in `DIAG_CURVES`, detection markers scattered on `diag_display`, event marks as dashed vertical lines. X axis in seconds before now (5 s window) |
| Detection marker | **v1.40:** bright yellow, size 20, white outline — it marks where the signal crosses the threshold and a beat is declared, the single most important event in the plot |
| Threshold while refractory | **v1.40:** a curve declared with `dim_refr=True` is drawn twice from one array, split by NaN with `connect='finite'`: solid in its own colour where detection is live, dark dashed (35 % brightness) where the refractory period is vetoing it. The base records that state per sample in `diag_refractory`. One array and one time axis, so the two halves cannot disagree |
| Right | One spin box per `HR1Param` (int or float by `decimals`), plus RESET TO DEFAULTS |

Changing a parameter resets that variant's state — the old state was produced by different
coefficients. Unchecking `run` freezes a variant without removing its row; re-checking it restarts
it, so no time discontinuity enters the RR buffer. A collapsed row keeps running: only its display
is hidden, and the freed height goes to the expanded rows.

**Window controls:**

| Control | Effect |
|---|---|
| Context bar | `PROBE` (probe state), `OT_LED1` (the signal every variant consumes), `PI` (from the main window) — what you are physically doing to the signal |
| PAUSE / CONTINUE (key `P`) | **v1.39.** Freezes the feed: traces, metrics and the save buffer stop where they are, so the frozen view can be studied and saved. CONTINUE starts a fresh recording — variants, marks and buffer cleared — because resuming into the old state would splice two moments of signal into one RR interval and one timeline |
| MARK (key `M`) | Stamps a dashed line across every trace at the current instant, so a failure can be tied to the action that caused it. The mark points at the newest buffered sample, so marking and pausing immediately still keeps it |
| SAVE LAST 30s | Writes `captures/hr1lab_<timestamp>.csv` — `t_s,ot_led1,probe_state,mark`. Saves the **signal**, not the variant outputs, so the same stretch can be replayed later through any variant. While paused it writes the buffer as it stood at PAUSE: nothing has entered it since |
| RESET ALL | Clears every variant's state and drops the marks; parameters are kept |

Fed at 500 Hz from the serial path, next to the HR1TEST mirror; redrawn at 10 Hz
(`_HR1LAB_REFRESH_EVERY`), timed as `plot_hr1lab` in PYTHON TIMING.

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

**v1.37 — file layout follows the sidebar.** QSettings writes sections and keys in its own
internal order, unrelated to the UI. `PPGMonitor._reorder_settings_file()` runs as the last step
of `closeEvent` — after every subwindow has written its geometry — and rewrites the file so that:

- `[PPGMonitor]` comes first, then one section per window **in sidebar-button order**; sections
  with no button (`TimingWindow`, `AFECharTestWindow`) are kept at the end.
- Inside `[PPGMonitor]`, the general settings come first, then the `*_open` keys in sidebar-button
  order, then any `*_open` key not in the table (`timing_open`, `afe_char_open`).

The order is declared once in `PPGMonitor._INI_BUTTON_ORDER` as `(open-state key, section)` pairs,
which must be kept in sync with the `addWidget()` sequence that builds the sidebar. Anything absent
from that tuple is still written — it just lands at the end, so a forgotten entry degrades the
layout and never loses a setting.

The pass only moves lines: no value is added, changed or removed, and keys whose value QSettings
wrapped across lines stay attached to their continuation lines. It is cosmetic by design and
swallows any parsing surprise, leaving the file exactly as QSettings wrote it.
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
| `HR2LabWindow/geometry` | bytes | |
| `HR1LabWindow/geometry` | bytes | |
| `SerialComWindow/geometry` | bytes | |
| `UdpComWindow/geometry` | bytes | |
| `HWConfigWindow/geometry` | bytes | |
| `DiagnosticsWindow/geometry` | bytes | |
| `AFESweepTestWindow/geometry` | bytes | |
| `AFESweepTestWindow/*` | mixed | All sweep parameter spin values |
| `PythonTimingWindow/geometry` | bytes | |
| `LabCaptureWindow/geometry` | bytes | |
| `LabCaptureWindow/*` | mixed | Output dir, prefix, pre/post notes, column selection |
| `LabCaptureWindow/auto_read_cfg` | bool | Read chip config automatically. **Default `true`** |
| `LabCaptureWindow/disable_hgac` | bool | Freeze HGAC during capture. Default `false` |
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

Voltage-based cell background colors in SIGNAL STATS table cols 1–2:
- Green `#0F3A0F` — optimal operating range
- Yellow `#3A2D00` — caution (approaching saturation or insufficient signal)
- Red `#4A0800` — saturation or signal too low
- Gray **text** `#5A5A5A` on neutral `#121212` — channel CLIPPED (CH_MASKS from $M4: ADC rail
  or TIA hard clip) — estimate not valid, gauge color suppressed. Same criterion and color as
  the analog-chain rows (V_TIA_*, I_PD_*, OT_*).
  OFF_SPEC (`tia_over_fs`) is never grayed — the value is still real.
- Default `#121212` — no data or non-ADC row

Threshold sources differ per column and must not be mixed (see §6.3 for the full tables):
- **V_TIA** — HGAC actuation thresholds (`hgac_v_tia_high2/high1/low1`), read **live** from
  `$LCFG` because they are runtime-tunable. Each colour marks a distinct HGAC state; green is
  the leveling dead band, not a target.
- **V_ADC** — chip physics only: TIA full-scale guarantee 1.0 V (§9.2.2/Fig. 135 "TIA max"; the
  datasheet has no symbol named "V_OD") and the guarded ADC rail `adc::SAT_POS` ≈ 1.1997 V
  (ADC FS = ±1.2 V). No HGAC policy here — HGAC actuates on `v_tia`, not `v_adc`.

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

### v1.32 — 2026-09-04

**Fix: quick RF1/RF2 combos in the SIGNAL STATS header froze in frame modes `$M1`–`$M3`.**
`_on_cfg_frame_received()` only wrote `_last_hgac_rf` when it was still `None`, so `$CFG` acted
as a one-shot seed. In `$M4` that was invisible (fields 34/35 refresh it every sample), but in
`$M1`–`$M3` — where those fields do not exist — `$CFG` is the only source, so the header combos
stayed at the first value read while HW CONFIG (fed unconditionally by `update_from_cfg()`)
followed every RF change, whether from HGAC or a manual `$SET`. The `is None` gate is gone; see
§6.3.1 points 6 and 7.

Also in `_sync_quick_hw_controls()`: `_quick_rf_shown` is now advanced only when both combos
actually displayed the value, so a `findText()` miss is retried on the next render tick instead
of being recorded as shown.

**Fix: the sidebar frame mode was an assumption, never a measurement — new §6.5.1.** Reported as
"the board boots in `$M3` but the script says `$M4`". The script displayed `frame_mode` (from the
.ini, default `$M4`) while the ESP32 always boots in `$M3`, and every mechanism meant to reconcile
the two could fail silently:

- `_on_cfg_frame_received`'s sibling banner handler hardcoded `self.frame_mode = "M4"` **before**
  the block 22 lines below read `self.frame_mode` to "restore the saved frame mode" — so the
  restore always sent `$M4` and overwrote the saved setting, whatever the user had picked.
- `_send_frame_cmd()` returned silently when `_is_cmd_ready()` was false, leaving the combo
  advertising a mode never requested of anyone.
- `$MODE` has no checksum and its `# Frame mode: ...` confirmation was only logged, never checked:
  one lost datagram meant permanent divergence.
- If the `# incunest_afe4490 started` banner did not reach the **active** transport's queue
  (`_is_active`), the entire post-reset sequence was skipped — `$MODE`, `$CFG?` *and* the HGAC
  re-enable — with nothing in the log.
- Even on the happy path there was a ≥500 ms + RTT window per reset with the firmware in `$M3`
  and the UI claiming `$M4`. A Lab Capture started in that window silently records `-1` in every
  `$M4` column (`_write_lab_capture_row()`'s fallback for absent fields).

Now field 0 of every data frame is tracked as `_frame_mode_live`, the combo mirrors it, and a
mismatch persisting >1 s re-sends `$MODE` (max 5, logged) — which closes all of the above at once,
whichever message was lost. The hardcoded `"M4"` is gone, so the saved mode is genuinely restored.
Data parsing was never affected: it has always been driven by field 0 (`lib_id`).

Not done: `_post_reset_cfg_pending` (set on `_reset_esp32()`, cleared on the banner, **never
read**) is still dead code — it was the intended fallback for the missed-banner case, now covered
by the `$MODE` retry, but `$CFG?` and the HGAC re-enable still have no fallback of their own.

### v1.31 — 2026-08-26

**`SpO2LocalCalc` had drifted from the firmware it exists to replicate — found while tabulating
every EMA time constant in the library.** SPO2LAB compares `R_loc` against `R_fw` to derive the
calibration coefficients, so each of these made that comparison invalid:

| Constant | Was | Now | Firmware source |
|----------|-----|-----|-----------------|
| `_DC_IIR_TAU_S` | 1.6 s | **2.0 s** | `spo2_ema_mean_tau_s` |
| `_AC_EMA_TAU_S` | 1.0 s | **6.0 s** | `spo2_ema_var_tau_s` |
| `_WARMUP_S` | 5.0 s | **18.0 s** | `spo2_warmup_s` |

- **Seeding added** (`dc = x`, `ac2 = 0` on the first sample): the firmware has done this since
  lib v0.55 to remove a warmup bias that inflates AC² — the Python replica still ramped from
  zero. This was an algorithmic difference, not just a constant.
- Class docstring rewritten: it claimed `spo2_a=104, spo2_b=17` while the code already had
  114.9208 / 30.5547, and named `_update_spo2()` (renamed `_spo2_update()` in the library).
- `_SPO2_MIN_DC` documented as having **no firmware counterpart** (the DC gate moved to RSQM in
  lib v0.42); kept deliberately as a divide-by-small guard for replaying older captures.

Library side (`incunest_afe4490.h`): the SpO2 state comment still documented `τ_mean` as 1.6 s and
`τ_var` as 1.0 s — corrected to 2.0 s / 6.0 s, with the ISO 80601-2-61:2026 Annex JJ.2 d)
justification for the 6 s minimum added inline. Comment-only, no behaviour change, so no library
version bump; `incunest_afe4490_spec.md` already documented the correct values.

**Impact:** calibration points captured in SPO2LAB before this change are not comparable with new
ones — the local R was computed with a 1.0 s AC window instead of 6.0 s.

### v1.30 — 2026-08-24

**Quick HW controls in the SIGNAL STATS header: `HGAC`, `RF1`, `RF2` — see §6.3.1.** Alex wanted
the two RF values visible without opening HW CONFIG, and editable without a Set button. Two
findings shaped the result:

- The value was already tracked (`_last_hgac_rf`, from `$M4` fields 34-35) but **only while HW
  CONFIG was open** — the tracking block was inside `if self.hw_config_window is not None`, so
  the data was only followed when the window you wanted to avoid opening was open. Now tracked
  unconditionally; the coalesced `$CFG?` mirror into HW CONFIG's combos stays conditional.
- **A pair of RF combos alone would have been unusable.** `_auto_enable_hgac()` sends
  `$SET,hgac_enable,1` on every firmware start, and HGAC v1 is RF-only actuating on
  `APPLIED||SATURATING`, so any manual RF would revert within ~200 ms. Hence the third control:
  the `HGAC:` combo is what hands RF over to the user, and the RF combos grey out while HGAC
  owns them.

- New `PPGMonitor.send_set(key, value, log_prefix, suppress_cfg_note)`: single source of truth
  for the `$SET` payload + XOR checksum, previously duplicated in `HWConfigWindow._send_set()`,
  `LIBConfigWindow._send_set()` and `_auto_enable_hgac()`. `HWConfigWindow._send_set()` now
  delegates to it; `LIBConfigWindow._send_set()` deliberately left alone (different
  "not connected" message, confirms via `$LCFG`, and does not clear `_cfg_notify_lab_capture`).
  `suppress_cfg_note=False` exists for `$LCFG`-confirmed keys so the flag is not left cleared
  for an unrelated later `$CFG`.
- `_WheelBlockFilter` gained `always=False`; the quick controls use `always=True`.
- `$CFG` handler seeds `_last_hgac_rf` from `tia1`/`tia2` when unset, and re-evaluates the
  `ENSEPGAIN` gating of RF1. `$LCFG` handler caches `hgac_enable` into `_hgac_enabled`.
  (The "when unset" part was a bug — fixed in v1.32, see §6.3.1 point 6.)

### v1.29 — 2026-08-24

**`LabCaptureWindow` gains `RF1_OHM`/`RF2_OHM` — the `_COLS` list still stopped at
`CH_MASKS` (index 33) even though `main.cpp`'s `$M4` frame has carried the actual
per-sample RF (indices 34-35, string, e.g. `"500K"`) since lib v0.37.** Found while
deciding which columns to keep for a multi-subject capture database: without a per-sample
RF value there is no way to correlate a PPG/SpO2/HR transient with an RF change, and
`V_TIA`/`I_PD` alone can't be used to reconstruct it (`RF = V_TIA / I_PD` needs both, and
only `V_TIA_LED1/2` was being kept).

- `_COLS` gained `RF1_OHM`, `RF2_OHM` (indices 34-35, `FW_RF1_OHM`/`FW_RF2_OHM`). Optional,
  checked by default, same "-1" fallback outside `$M4` mode as the other `$M4`-only columns.
- §4.2 `$M4` frame table extended to document all 13 analog/RF fields (was documented as
  11, missing the 2 RF fields that were already being sent).
- **Caught before use (same session, Alex):** the first version of this change wrote the
  wire string (`"500K"`) straight to the CSV, like every other column does — but unlike
  every other column, that value is not a plain number, so no time-series/plotting tool
  can read it, which defeats the whole point of adding it. `_write_lab_capture_row()` now
  converts it to ohms via `_RF_STR_TO_OHM` before writing the row (see §7.13).
- **Also caught before use (Alex): the frame field itself was named `HGAC_RF1`/`HGAC_RF2`,
  wrongly implying HGAC always computes the value** — it's just the live RF config, which
  a manual `$SET` can set too. Renamed end-to-end: `incunest_afe4490.h`'s
  `AFE4490DebugData::hgac_rf_led1/led2` → `rf_led1/led2` (lib v0.81), `main.cpp`'s frame
  comments, and this CSV column (`HGAC_RF1/RF2` → `RF1_OHM/RF2_OHM`, keeping the `_OHM`
  suffix from the point above). The `$M4` wire field itself is now documented as `RF1`/`RF2`
  (§4.2) — same rationale, no HGAC implication.

### v1.28 — 2026-08-22

**`LabCaptureWindow` gains the 11 `$M4`-only columns — found missing while investigating the
switched-RC settling fix (lib v0.79).** Alex needed `OT_LED1` at full temporal resolution to
verify a 9-sample settling window and found it wasn't selectable anywhere: `SAVE DATA` has the
column in its header but the row data is decimated by `spin_decim` (documented behaviour, not a
bug — `_write_lab_capture_row()` runs *before* decimation, at the full 500 Hz, so it's the correct
tool, but its `_COLS` list predates `$M4`'s extra fields).

- `_COLS` gained `V_TIA_LED1/2/ALED1/2`, `I_PD_LED1/2/ALED1/2`, `OT_LED1/2`, `CH_MASKS` (indices
  23-33, matching `main.cpp`'s `$M4` frame layout). All optional, unchecked-by-default behaviour
  unchanged for the existing columns.
- These new columns read `"-1"` (the existing out-of-range fallback in `_write_lab_capture_row()`)
  when the active frame mode isn't `$M4` — noted in the class docstring and this section, since the
  generic per-checkbox tooltip ("Optional column: X") doesn't say so.
- No change to `SAVE DATA` — it remains decimated by design; `LabCaptureWindow` is the tool for
  full-rate, short-transient captures like a settling window.

### v1.27 — 2026-07-24

**Mirrors lib v0.45: new `ProbeState.PROBE_SATURATING = 3`, split out of `PROBE_NOT_APPLIED`.**

- `PROBE_SATURATING = 3` added to the local `ProbeState` ordinal mirror in `SpO2TestCalc`,
  `HR1TestCalc`, `HR2TestCalc`, `HR3TestCalc` (each already gates on `!= PROBE_APPLIED`, so no
  other code change needed in these classes — `PROBE_SATURATING` is excluded automatically,
  same as before).
- `AFESweepTestWindow._PROBE_STATES` combo gained the `(3, "PROBE_SATURATING")` entry, and its
  tooltip text updated, so the offline verification tool can select/check the new state.
- SIGNAL STATS `ProbeState` cell: new `_PROBE_SATURATING_BG` (orange `#7A3D00`), distinct from
  `PROBE_NOT_APPLIED`'s amber — a saturating channel means signal is present but out of range,
  a different diagnostic situation from "no probe applied" that previously shared the same
  amber color. *(2026-08-10: recolored to blue `#0050A0` at Alex's request.)*
- `ProbeState` row tooltip (SIGNAL STATS table) rewritten to document the new priority order
  (DISCONNECTED > SATURATING > NOT_APPLIED > APPLIED) and that SATURATING does not imply a
  patient is present.
- `rsqm_ot_thr` tooltip in `LIBConfigWindow` clarified: only checked once the channel is
  already known `CH_VALID_RANGE` — an invalid/saturated channel is `PROBE_SATURATING` regardless of
  this threshold.

### v1.26 — 2026-07-23

**Follow-up to v1.25: the SIGNAL STATS `ProbeState` tooltip was missed when `rsqm_ot_thr`'s
default was widened.** Found by Alex.

- `ProbeState` row tooltip (SIGNAL STATS table) still hardcoded the old `8.5×10⁻⁵` threshold
  in both the NOT_APPLIED and APPLIED descriptions. Updated to `1.0×10⁻⁴`, matching the
  current `rsqm_ot_thr` default (`incunest_afe4490.h:765`) and the `LIBConfigWindow` tooltip
  fixed in v1.25. APPLIED description also now explicitly notes `rsqm_ot_thr` is
  runtime-configurable via `$LCFG` (it wasn't clear from the old wording that this was a
  live-adjustable parameter, not a fixed constant).

### v1.25 — 2026-07-19

**Mirrors lib v0.44-experiment: `rsqm_ot_thr` tooltip updated for widened default.**

- `LIBConfigWindow._PARAMS` tooltip for `rsqm_ot_thr` updated: default widened 8.5e-5 → 1.0e-4.
  Reason: first real-HW test on the OT-domain experiment (CONTEC MS100 simulator, probe
  applied) found `probe_state` never reached PROBE_APPLIED at 8.5e-5 — the simulator is very
  sensitive to probe placement and OT frequently read above that value with the probe on.
  Practical mitigation, not an empirical calibration with a real probe/patient. The actual
  runtime default lives in firmware (`incunest_afe4490.h`); this is a display-only change —
  the spinbox default is populated from `$LCFG` readback, not hardcoded here.

### v1.24 — 2026-07-16

**Mirrors lib v0.42-experiment: same `probe_state` design as v1.23's SpO2 applied to
HR1TestCalc/HR2TestCalc/HR3TestCalc.**

- `HR1TestCalc.update()`, `HR2TestCalc.update()`, `HR3TestCalc.update()` all gain a
  `probe_state` parameter (RSQM's `ProbeState` ordinal, 0/1/2 = DISCONNECTED/NOT_APPLIED/
  APPLIED — same class constants added to all three: `PROBE_DISCONNECTED`/`NOT_APPLIED`/
  `APPLIED`) — consumed, never computed internally, matching §5.1's design exactly.
- While `probe_state != PROBE_APPLIED`: `reset()` runs every sample (idempotent, no stored
  "previous probe_state"), and `hr_bpm`/`hr_sqi` are forced to `nan`/`0` — unifying the `NaN`
  sentinel across all 4 mirror classes (SpO2/HR1/HR2/HR3). HR1's and HR3's gap-detection logic
  (via `sample_counter`) still runs regardless of `probe_state` — it tracks frame continuity,
  not finger presence, so it must not be gated by it.
- Call sites updated to thread `probe_state` through: `HR1TestWindow`/`HR2TestWindow`/
  `HR3TestWindow`'s `_process_csv_offline()` offline loaders (new `rows_probe_state` column
  parsed alongside `rows_ot_led1`); `HR2TestWindow.update_algorithms()` (new
  `data_probe_state` parameter, threaded from its `PPGMonitor` caller); the raw-frame live
  feeds — HR1's `$M4`-gated fast path, HR3's `$M3`/`$M4`/`$M2`/`$M1` branches (`$M1` carries no
  `ProbeState` field at all, so `PROBE_DISCONNECTED` is hardcoded there, matching
  `data_probe_state.append(0)` in the same branch).
- `HRFFTCalc`/`self.hr3_calc` (the separate "HR3LAB" diagnostics class — confirmed via code to
  have no inheritance relationship with `HR3TestCalc` despite similar naming) deliberately
  left untouched, out of scope, same as the OT-domain migration before it.
- Native test suite (`incunest_afe4490` lib v0.42): `test_hr1/hr2/hr3.cpp` each gained
  `test_hr1/hr2/hr3_not_applied_resets` (feeds a converged valid signal, forces
  `PROBE_DISCONNECTED` for 1000 samples, asserts `sqi=0`/`nan` + state reset, then asserts a
  fresh buffer/interval-count is required after returning to `PROBE_APPLIED`, and again for
  `PROBE_NOT_APPLIED`). 36/36 native tests (test_biquad pre-existing unrelated failure),
  `py_compile` clean. See §5.2–§5.4.

### v1.23 — 2026-07-16

**Mirrors lib v0.41-experiment: presence detection fully delegated to RSQM; `NaN` replaces
`-1.0f` as the invalid-output sentinel, unified across warmup/not-applied/division-guard.**

- `SpO2TestCalc.update()` gains a third parameter, `probe_state` (RSQM's `ProbeState` ordinal,
  0/1/2 = DISCONNECTED/NOT_APPLIED/APPLIED) — consumed, never computed internally. Removes
  `spo2_min_ot_dc` (the v1.22 "no-signal" floor) entirely: while `probe_state != PROBE_APPLIED`
  (both NOT_APPLIED and DISCONNECTED treated identically), internal state
  (`_dc_ir`/`_dc_red`/`_ac2_ir`/`_ac2_red`/`_sample_count`) resets every sample (idempotent —
  no "previous probe_state" stored), and `pi`/`spo2`/`spo2_r` become `nan`.
- `FW_SPO2_MIN_OT_DC`/`FW_SPO2_AC_DIV_EPS` collapsed into a single `FW_SPO2_DIV_EPS` (`1e-9`,
  not user-adjustable) — a purely numerical division-safety guard on `dc_ir`/`dc_red`/
  `rms_ac_ir` (the actual divisors), now that presence detection is `probe_state`'s job.
- Output contract unified: `sqi==0` now always means `spo2`/`spo2_r`/`pi` are `nan`, across all
  three invalid paths (warmup, not-applied, division guard) — previously only some paths
  produced `nan`, others left the dict's values from the last successful call.
- UI: the "Min OT DC [ppm]" spinbox (added in v1.22) removed entirely — no presence-detection
  parameter remains in SpO2TestWindow's panel, back to the original 5 (a, b, DC τ, AC τ,
  warmup). CSV loader and live feed now also read/pass `ProbeState` (already-parsed column)
  into `SpO2TestCalc`.
- Native test suite (`test_spo2.cpp`, `incunest_afe4490`): `test_spo2_low_dc_invalid` replaced
  by `test_spo2_not_applied_resets` (feeds a converged valid signal, forces
  `PROBE_DISCONNECTED` for 1000 samples, asserts `sqi=0`/`nan` outputs/EMA reset, then asserts
  a fresh warmup is required after returning to `PROBE_APPLIED`, and again for
  `PROBE_NOT_APPLIED`). 7/7 `test_spo2` + 33/33 other native tests, ESP32-S3 build OK.

### v1.22 — 2026-07-15

**Mirrors lib v0.40-experiment: removed the `spo2_min_i_pd_a` "no-finger" gate added in
v1.19.** Analysis showed it rarely detected an actual no-finger condition (a transmittance
probe with no finger shows HIGH OT, not low i_pd) and mostly duplicated, with a
weaker/uncalibrated criterion, RSQM's own `PROBE_DISCONNECTED` classification.

- `SpO2TestCalc.update()` simplified to `(ot_ir, ot_red, fs)` — no more `i_pd_ir`/`i_pd_red`.
- Replaced by `spo2_min_ot_dc` (A/A, `1e-6` placeholder default), applied only to
  `dc_ir`/`dc_red`. AC keeps a separate, non-user-adjustable numerical guard
  `FW_SPO2_AC_DIV_EPS` (`1e-9`, on `rms_ac_ir` only) — conflating the two into one shared
  threshold was tried first and broke 4/7 native `test_spo2` cases (AC legitimately gets tiny
  at low PI, e.g. PI=0.5% on typical DC gives AC≈7e-8, far below a physiologically-motivated
  DC floor).
- UI: "Min I_PD [µA]" spinbox → "Min OT DC [ppm]" (`_spin_min_ot_dc_ppm`), tooltip rewritten.
- CSV offline loader and live feed for SpO2TestWindow no longer read/pass
  `I_PD_LED1`/`I_PD_LED2` (still parsed/displayed elsewhere — SIGNAL STATS, AFESweepTestWindow
  — just no longer fed to `SpO2TestCalc`).
- Native test suite: `test_spo2.cpp` test 2 renamed `test_spo2_no_finger_invalid` →
  `test_spo2_low_dc_invalid`, now feeds flat OT below `spo2_min_ot_dc` instead of low i_pd.
  7/7 `test_spo2` + 33/33 other native tests pass (see incunest_afe4490_spec.md v0.40
  changelog for the library-side change).

### v1.21 — 2026-07-15
- SIGNALS2 (`PPGSignals2Window`): `spin_window_s` (the "Window (s)" duration spinbox)
  font-size increased 32px → 40px, then further to 56px (first bump read as still too small)
  + `setMinimumHeight(64)` so the larger glyphs aren't clipped. Slot-3 curve/dot color changed
  from pink `#FF66FF` to red `#FF4444` (`_SLOT_COLORS`) — same red tone already used elsewhere
  in the app for LED2/RED curves, for visual consistency.
- Clarified after the fact: the "font still too small" feedback was actually about the 9
  signal-selection combos (`_COMBO_STYLE`), not `spin_window_s`. Combo font-size doubled
  17px → 34px; each graph's combo-group column widened `setFixedWidth` 220px → 420px so
  long signal names (e.g. `V_TIA_ALED1`) aren't clipped at the larger size. Slot-1
  color changed from white `#FFFFFF` to yellow `#FFDD44` (`_SLOT_COLORS`) — same yellow tone
  used elsewhere in the app (e.g. SpO2 fw curve).
- Both sizes walked back down: `spin_window_s` font-size 56px → 37px (one third smaller);
  combo font-size 34px → 18px, with the combo-group column reverted 420px → 220px (18px is
  close enough to the original 17px that the wider column is no longer needed).
- Combo font-size nudged back up 18px → 28px; combo-group column widened 220px → 360px
  (scaled proportionally) so long signal names stay readable at 28px.
- `_COMBO_STYLE` (fixed constant) → `_combo_style(color)` (static method): each combo's own
  displayed text is now tinted with its slot's `_SLOT_COLORS` entry (yellow/cyan/red),
  matching its plotted curve. The dropdown list itself stays neutral `#E0E0E0` so all entries
  remain legible regardless of slot.

### v1.20 — 2026-07-15
- Added `faulthandler.enable(file=..., all_threads=True)` at module top (before any other
  import), writing to `faulthandler.log`. Diagnostic addition to investigate abrupt,
  untraceable process termination reported since SIGNALS2 was added — the existing
  `sys.excepthook`-based `_crash_handler` only catches unhandled **Python** exceptions
  (written to `crash.log`); it cannot catch a native-level crash (segfault, Qt/pyqtgraph C++
  abort), which is the leading hypothesis given `crash.log` was empty despite repeated
  crashes. See new §2.1. Suspected trigger (not yet confirmed): SIGNALS2's default preset
  (`_DEFAULTS`, `PPGSignals2Window`) mixes signals ~11 orders of magnitude apart (`LED1_SUB`
  raw ADC ~1e6 vs `OT_LED1` ~1e-5) on the same shared Y axis — a known edge case for
  pyqtgraph's axis autorange. Not fixed yet, pending confirmation via `faulthandler.log` on
  next crash.

### v1.19 — 2026-07-15

**Experiment (`experiment/ot-domain-inputs`): the 4 mirror classes migrated to OT-domain
input**, completing the Python side of the OT migration (firmware side was already done —
see `project_ot_domain_experiment_task.md`). See §5.2–§5.5 and §7.7–§7.10 for details.

- `SpO2TestCalc`, `HR1TestCalc`, `HR2TestCalc`, `HR3TestCalc`: `update()` now takes
  `OT_LED1`/`OT_LED2` [A/A] instead of raw `LED1_SUB`/`LED2_SUB`. `SpO2TestCalc` additionally
  takes `I_PD_LED1`/`I_PD_LED2` [A] for its no-finger gate (`spo2_min_i_pd_a`, replacing the
  counts-based `spo2_min_dc`); its numerical div-by-zero guard moved from a fixed `1.0` to
  `spo2_ot_div_eps` (`1e-9`). HR1/HR2/HR3 needed no threshold recalibration (invariant to a
  uniform input scale).
- All 4 `*TestWindow` classes now require frame mode `$M4` (`OT_LED1`/`OT_LED2`/`I_PD_*` only
  travel in `$M4`): live mode shows a status-bar warning and stops feeding the calc when not
  in `$M4`; [LOAD CSV] only accepts `$M4` rows (both `ppg_chk_*` and `ppg_data_raw_*` CSV
  formats) and raises a clear error on a file with none.
- `HR1TestWindow`'s full-rate (500 Hz, pre-decimation) live feed switched from listening for
  `$M1` frames to `$M4` frames, since `$M1` never carries `OT_LED1`.
- SpO2TestWindow's `DC`/`RMS AC` plots, legend, and value-table rows now display in ppm (×1e6,
  OT is A/A ~1e-5) instead of raw ADC counts — same convention as `OT_LED1 [ppm]`/`OT_LED2
  [ppm]` in SIGNAL STATS (v1.16). The "Min DC" parameter spinbox became "Min I_PD" (µA).
- Out of scope (intentionally left on raw `LED1_SUB`/`LED2_SUB`, analogous unmigrated mirrors):
  `SpO2LocalCalc`/SpO2LabWindow ("SPO2LAB"), `HRFFTCalc`/`self.hr3_calc` ("HR3LAB"), `PICalc`
  ("PILAB").
- **Pre-existing bug found and fixed as a side effect of this work:** the "raw" CSV format
  branch (`FrameMode` header, i.e. normal captures saved via the main [SAVE] button) of
  `_process_csv_offline()` in `SpO2TestWindow`, `HR1TestWindow`, and `HR2TestWindow` used to
  read the firmware reference columns (SpO2/R/SQI or HR1/HR2 + SQI) one column too early —
  e.g. SpO2TestWindow's `spo2_fw` actually read `PPG_DISP`, `R_fw` read `SpO2_SQI`, `sqi_fw`
  read `SpO2`. Rewriting these branches to require `$M4` used the correct `row[2+partsIdx]`
  mapping throughout, which incidentally fixed the pre-existing off-by-one (verified against
  a synthetic CSV row with one distinct value per column — see commit `ca14dbf`).
  `HR3TestWindow`'s equivalent code and the `is_chk` CSV format branch (all 4 windows) were
  already correctly indexed before this session.

### v1.18 — 2026-07-15
- SIGNALS2: font size increased for the 9 signal-selection combos (13px → 17px) and for the
  shared `Window (s)` label/spinbox and `PAUSE`/`CONTINUE` button (14/16/15px → 22/32/32px),
  so they stand out clearly from the rest of the controls. Verified visually via a forced
  `signals2_open=true` in `pulsenest_lab.ini` + screenshot capture.

### v1.17 — 2026-07-14
- New `PPGSignals2Window` (`SIGNALS2` button, next to `SIGNALS`): 3 freely-configurable plots,
  each with 3 slots individually selectable (via `QComboBox`) from any of the 30 signals
  currently parsed from `$M1`-`$M4` (raw channels, OT, V_TIA, I_PD, SpO2/HR/R/PI, RSQI,
  DiagCode, ProbeState, CH_MASKS) — unlike `PPGSignalsWindow` (`SIGNALS`), which is fixed to
  the 6 raw AFE4490 channels. Curve colors fixed per slot (white/cyan/magenta) across all 3
  graphs; plot titles show the selected signal names color-coded. Default selection on first
  launch: Graph 1 = LED1_SUB/OT_LED1/SpO2, Graph 2 = LED2_SUB/OT_LED2/R, Graph 3 =
  HR1/HR2/HR3 — a starting point for cross-checking the OT-domain input migration
  (`experiment/ot-domain-inputs`).
  - Layout: each graph's 3-combo group sits to the **left** of its own plot (3 stacked rows),
    with a shared top bar (window duration `spin_window_s` + `PAUSE`/`CONTINUE` button — same
    controls and pattern as `PPGSignalsWindow`).
  - Each of the 9 slots keeps its own independent rolling buffer (up to `SIG_MAX_S` seconds,
    same sample-counter-diff accumulation as `PPGSignalsWindow`), cleared and re-seeded from
    current history whenever that slot's signal selection changes.
  - Selections, window duration, and geometry persisted in settings.
  - Note: signals of very different scale share one Y axis per plot (no auto dual-axis) —
    group similar-magnitude signals together.

### v1.16 — 2026-07-14
- SIGNAL STATS: `OT_LED1`/`OT_LED2` rows renamed `OT_LED1 [ppm]`/`OT_LED2 [ppm]` and their
  displayed value multiplied by 1e6 (A/A → ppm), 2 decimal places (was 6 dp, raw A/A). Display
  formatting only — the `$M4` wire protocol is unchanged (firmware still sends raw A/A in
  `%.4e`); the ×1e6 conversion happens in `_fmt()` at render time (§6.3).

### v1.15 — 2026-07-11
- SIGNAL STATS rows 0–3 (raw ADC): CLIPPED indication changed from gray background `#3A3A3A`
  to gray text `#5A5A5A` on neutral background `#121212` in the V_TIA/V_ADC cells (same
  convention as the analog-chain rows). The voltage gauge color is suppressed when CLIPPED —
  it would be computed from bound values and mislead. `_VTG_GRAY` constant removed.
- Resulting uniform rule: gray text = "this number is not real"; backgrounds reserved for
  semantic gauges (voltage ranges, SQI).

### v1.14 — 2026-07-11
- SIGNAL STATS validity gray-out refined (option B, physical criterion): gray now means
  **CLIPPED** (`adc_sat_pos` | `adc_sat_neg` | `tia_over_lin`), not "not CLEAN" — the
  `tia_over_fs` (OFF_SPEC) nibble is excluded because 1.0–1.8 V diff is empirically linear
  and the value is still real (graying it would lose information during HGAC sweeps).
- Gray text extended from OT rows to the whole analog chain: V_TIA_* (rows 20–23) and
  I_PD_* (rows 24–27) now gray when their own channel was CLIPPED during the stats window.
- Gray text color darkened: `#808080` → `#5A5A5A` (`_STATS_INVALID_FG`).
- Tooltips of the 10 analog rows + the 4 V_TIA/V_ADC column legends explain CLIPPED vs OFF_SPEC.

### v1.13 — 2026-07-11
- $M4 frame extended (requires firmware with lib ≥ v0.35 + CH_MASKS): fields 31–33 =
  `OT_LED1`, `OT_LED2` [A/A, `%.4e`] and `CH_MASKS` (`%04X` hex — validity masks packed in
  4 nibbles: adc_sat_pos / adc_sat_neg / tia_over_fs / tia_over_lin; bit = channel per
  `AFE4490Ch`). §4.2 rewritten to document all four frame modes ($M1–$M4) — previous text
  described the pre-2026-06-09 formats.
- SIGNAL STATS OT_LED1/OT_LED2 rows now **read from the $M4 frame** (firmware
  `_compute_analog_state()`), replacing the local `(I_PD_LED − I_PD_ALED)/I_LED` calculation
  from `$CFG` LED currents.
- CH_MASKS first consumer (closes project_vtia_gray_task): V_TIA/V_ADC cells gray
  background `#3A3A3A` when the channel was not CLEAN during the stats window; OT rows gray
  text `#808080` when a source channel was not CLEAN (mirrors library `otLedxValid()`).
  New deque `data_ch_masks`; accumulator `_stats_ch_masks_or` (OR per stats window).
- Serial COM / UDP COM / live-recording CSV headers: `+OT_LED1,OT_LED2,CH_MASKS`.
- §6.3 updated to current layout (30 signal rows; V_TIA/V_ADC are cols 1–2 — the
  previous "cols 7–8" text predated the column reorder).
- Firmware side (PulseNest `src/main.cpp`): `UDP_QUEUE_FRAME_SIZE` 256 → 288 (M4 ≈ 260 bytes;
  batch 5×288 = 1440 < 1472 MTU).

### v1.12 — 2026-07-11
- Tooltip texts updated for library v0.36 rename `RSQM_*` → `RSQM_DIAG_*` (DiagCode bits 13+):
  SIGNAL STATS DiagCode tooltip (now also notes the flags are anticipatory — intended consumer
  is the future HGAC; HW_SETTLING unreachable until HGAC exists) and LIB CONFIG
  `rsqm_signal_weak_std` tooltip. No functional changes.

### v1.11 — 2026-07-09
- AFE SWEEP TEST CSV: `OT1`/`OT2` renamed to `OT_LED1`/`OT_LED2` and moved to the end of the
  header (92 columns total, unchanged count). New computation: `(mean(I_PD_LED) − mean(I_PD_ALED))
  / I_LED` [A/A] from the $M4 I_PD buffers — same formula as firmware `_update_rsqm()` and the
  main window OT_LED columns. The old columns were always empty (legacy formula used
  `self.parent()`, which is `None` by the window-parenting rule) — bug fixed by the rewrite.
- Spec §7.18 output-file section rewritten to describe the real 92-column header (was stale at 40).

### v1.10 — 2026-07-08
- Fix: main window `closeEvent` crashed with `AttributeError` when `self.ser` was `None`
  (UDP-only sessions / serial never opened): `hasattr(self, 'ser')` guard replaced by
  `getattr(self, 'ser', None) is not None`. The exception aborted `closeEvent` before the
  subwindow-closing block, leaving all secondary windows open (they use `parent=None`)
  and the app running after the main window closed.
- Fix: `lib_config_window` (LIB CONFIG) added to the `closeEvent` subwindow-closing list
  (it was the only subwindow missing since v1.7).

### v1.9 — 2026-07-08
- V_TIA convention switched to DIFFERENTIAL (naming rule 4b): all `v_tia`/`V_TIA` identifiers,
  CSV columns, table headers and tooltips renamed to `v_tia`/`V_TIA`
  (V_TIA = 2 × I_PD × RF; per-branch = /2; bare `v_tia` forbidden).
- SIGNAL STATS V_TIA column (§6.3): local computation now includes the ×2 factor and the
  I_CANCEL (AMBDAC) term — matches firmware `_compute_analog_state()` (library v0.34).
  Color thresholds unchanged (they were already defined in the differential domain).
- $M4 CSV capture columns renamed: `V_TIA_LED1..V_TIA_ALED2` → `V_TIA_LED1..V_TIA_ALED2`.
  CSVs recorded before this version contain per-branch values (×0.5 vs new firmware).
- Requires firmware/library ≥ v0.34 ($M4 streams differential values).

### v1.8 — 2026-07-08
- Added `# RESET_REASON:` handling (§4.4): firmware now emits its reset reason once over UDP
  after every boot; the lab logs it as `[RESET] ESP32 rebooted — reason: <reason>`.
  Added to diagnose sporadic ESP32 resets triggered by `$SET` commands (~1 in 3-4 HW CONFIG changes).

### v1.7 — 2026-06-23
- Added LIBConfigWindow (LIB CONFIG): 7 RSQM parameters configurable at runtime via
  `$LCFG` frame and `$LCFG?` command (see git c45d0bb..dc2836d era).

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
- Updated SIGNAL STATS table (§6.3): expanded to 9 columns, IR-first row ordering, V_TIA/V_ADC columns with voltage-based color coding. *(V_TIA renamed V_TIA in v1.9.)*
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
