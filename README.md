# PulseNest

**PulseNest** is a validation tool for the library incunest_afe4490.

**incunest_afe4490** is a library (driver + algorithms) for AFE4490, implemented in `incunest_afe4490.h` and `incunest_afe4490.cpp`. It has a HAL for Arduino-ESP32, ESP-IDF and the host (unit tests); this test firmware uses the ESP-IDF one.

**AFE4490** is an Analog Front End chip designed by Texas Instruments for pulse oximetry applications using photoplethysmography (PPG)

This repository is developed as part of the **IncuNest** project, open-source neonatal incubator by [Medical Open World](https://medicalopenworld.org).

The goal is to verify PPG signal quality and SpO2/HR calculation in isolation, before integrating the AFE4490 into the main IncuNest firmware.
This repository holds the test firmware and the two desktop programs that go with it: the
**session launcher** for a recording campaign, and the **lab** for the bench. See *Running it*.

## Hardware

| Component | Details |
|---|---|
| MCU | ESP32-S3 (Incunest board V15 / V16 / V17 / V18) |
| Sensor | AFE4490 via SPI |
| Framework | ESP-IDF v6.0.1 (native, no Arduino) — since 2026-09-15 |

See **[docs/boards.md](docs/boards.md)** for the inventory of every physical board (MAC, revision,
which build preset to use), how to identify one, and the flashing procedures.

## Build and flash

Requires [ESP-IDF v6.0.1](https://docs.espressif.com/projects/esp-idf/en/v6.0.1/esp32s3/get-started/)
(esp32s3 target). `scripts/build.ps1` exports the IDF environment itself.

```powershell
# Build — select the preset matching your board (V15 / V16 / V17 / V18)
.\scripts\build.ps1 V18

# Build and flash over the air (board already running PulseNest; verify its MAC first).
# Waits for the board to come back and checks it reports the elfsha of the image just built.
.\scripts\build.ps1 V18 -Ota 192.168.137.14

# Build and flash a blank board over USB
.\scripts\build.ps1 V18 -Usb COM15

# Serial monitor (UART0, 921600 baud)
idf.py -B build_V18 -p COM15 -b 921600 monitor

# Host unit tests (CMake + Unity, needs cmake/ninja/g++ on PATH)
python tools/host_tests/run_host_tests.py
```

## Running it

Both programs need Python 3.11 or newer (the session files are TOML) with:

```
pip install PyQt5 pyqtgraph numpy scipy pyserial
```

The boards stream over WiFi/UDP to the PC. One process, the hub (`tools/pulsenest_hub.py`),
owns that UDP port and hands the stream to every program that asks; **it starts by itself** the
first time a program needs it, so nothing has to be launched by hand or in a given order. Several
programs can run at once on the same stream.

### Session launcher — recording a campaign

`tools/pulsenest_session.py` is the one window a person opens on the day: what is on the air
(boards, firmware agreement, phones), free disk as hours of recording, the clock, and one row per
cot with a **START** button. Each START opens one recorder window for that cot, as a process of
its own, so closing the launcher never touches a recording.

```powershell
.\scripts\make_session_shortcut.ps1      # once per laptop: a "PulseNest Session" desktop icon
pythonw tools\pulsenest_session.py       # the same, from a terminal
```

To use it: copy `docs/session_configs/example.toml` to one file per cot (`subj01.toml`, …), fill
in the subject code, the board (last four hex digits of its MAC), the probe and the reference
monitor, then open the launcher and press START on each cot. Files are re-read when edited.
Recordings land in `captures/sessions/<date>_<time>_<site>_<subject>/`. The step-by-step checklist
for the person at the cot side is **[docs/hospital_runbook.md](docs/hospital_runbook.md)**.

### Lab — the bench

`pulsenest_lab.py` is the engineer's tool: live PPG/SpO2/HR plots, Python replicas of the
firmware algorithms for verification, remote control of the AFE4490 (`$SET`), parametric sweeps
and CSV capture. It reads the boards over UDP through the hub, or one board over USB serial.

```powershell
pythonw pulsenest_lab.py
```

Switch on **UDP WiFi** (or **SERIAL**) in the toolbar, pick the board, and open the windows from
the buttons on the right: SIGNALS, SPO2LAB, HR2LAB, PILAB, LIB CONFIG, HW CONFIG, AFE SWEEP, …
The **SESSION** button starts the launcher above. The full
description is **[pulsenest_lab_spec.md](pulsenest_lab_spec.md)**; a crash leaves `crash.log` or
`faulthandler.log` beside the script.

### Other tools

| Program | What for |
|---|---|
| `tools/fleet_monitor.py` | One line per board in the console: firmware, rate, gaps |
| `tools/fleet_ppg_viewer.py` | One live PPG band per board, to see whether a probe has moved |
| `tools/pulsenest_recorder_gui.py --config <cot>.toml` | What START runs: the recorder window for one cot |
| `tools/pulsenest_convert.py <session dir> --csv v04` | Rebuild a session's CSVs from its `.pnraw` and prove they match |
| `tools/udp_fw_versions.py` | Firmware of every board on the air, nothing sent |

## Project structure

The folder says what a Python file *is*, not when it was written:

| Folder | What lives there | Rule |
|---|---|---|
| repo root | `pulsenest_lab.py` | The project's main program (its state files and the launch hooks live beside it) |
| `pulsenest/` | `net`, `hub_client`, `capture_csv`, `capture_dict`, `capture_set`, `fleet_trace`, `fleet_widgets` | Importable package: anything more than one program imports (`from pulsenest.net import ...`) |
| `tools/` | session launcher, hub, recorder, recorder GUI, converter, fleet monitor, PPG viewer, UDP utilities, capture index | Programs an operator or maintainer runs on purpose; importable as `tools.<name>` |
| `tests/` | `*_test.py` | Python tests, one per module they check (`python tests/<name>.py`). C++ host tests stay in `test/` |
| `experiments/` | one-off studies and bench campaigns | Dated, with the result recorded in the docstring; not maintained as tools |
| `scripts/` | `build.ps1`, `gen_build_version.py` | Build system only |

Every script outside the root puts the repo root on `sys.path` with one line and imports from
`pulsenest.` / `tools.` / the root modules, so it runs from any working directory:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
```

```
lib/incunest_afe4490/          — AFE4490 library (driver + algorithms), symlink to its own repo
main/pulsenest_main.cpp        — Test firmware (ESP-IDF); CMakeLists.txt, sdkconfig.defaults, sdkconfig.board.V1x
examples/basic/main.cpp        — Minimal integration example
pulsenest_lab.py               — Real-time PPG/SpO2/HR visualizer (pulsenest_lab_spec.md)
pulsenest/                     — Shared host-side modules (see table)
tools/                         — Operator programs and the hub (tools/pulsenest_hub.py); tools/pulsenest_recorder.py has pulsenest_recorder_spec.md
tools/pulsenest_session.py     — Campaign launcher (desktop icon: scripts/make_session_shortcut.ps1); docs/hospital_runbook.md
tests/                         — Python tests;  test/ — host unit tests (Unity), built by tools/host_tests/
experiments/                   — One-off studies;  analysis/ — their figures and CSV outputs
scripts/build.ps1              — Build / OTA / USB flash per board
conversation_log.md            — Session-by-session design decisions log
```
