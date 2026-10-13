# PulseNest

**PulseNest** is a validation tool for the library incunest_afe4490.

**incunest_afe4490** is a library (driver + algorithms) for AFE4490, implemented in `incunest_afe4490.h` and `incunest_afe4490.cpp`

**AFE4490** is an Analog Front End chip designed by Texas Instruments for pulse oximetry applications using photoplethysmography (PPG)

This repository is developed as part of the **IncuNest** project, open-source neonatal incubator by [Medical Open World](https://medicalopenworld.org).

The goal is to verify PPG signal quality and SpO2/HR calculation in isolation, before integrating the AFE4490 into the main IncuNest firmware.
This repository includes firmware code and a Python script to visualize serial output.

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

# Build and flash over the air (board already running PulseNest; verify its MAC first)
.\scripts\build.ps1 V18 -Ota 192.168.137.14

# Build and flash a blank board over USB
.\scripts\build.ps1 V18 -Usb COM15

# Serial monitor (UART0, 921600 baud)
idf.py -B build_V18 -p COM15 -b 921600 monitor

# Host unit tests (CMake + Unity, needs cmake/ninja/g++ on PATH)
python tools/host_tests/run_host_tests.py
```

## PPG Plotter

Real-time signal visualizer. Requires Python 3 with `pyqtgraph`, `pyserial`, `numpy`, `scipy`.

```bash
pythonw pulsenest_lab.py
```

## Project structure

The folder says what a Python file *is*, not when it was written:

| Folder | What lives there | Rule |
|---|---|---|
| repo root | `pulsenest_lab.py` | The project's main program (its state files and the launch hooks live beside it) |
| `pulsenest/` | `net`, `hub_client`, `capture_csv`, `capture_dict`, `capture_set`, `fleet_trace`, `fleet_widgets` | Importable package: anything more than one program imports (`from pulsenest.net import ...`) |
| `tools/` | hub, recorder, recorder GUI, converter, fleet monitor, PPG viewer, UDP utilities, capture index | Programs an operator or maintainer runs on purpose; importable as `tools.<name>` |
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
tests/                         — Python tests;  test/ — host unit tests (Unity), built by tools/host_tests/
experiments/                   — One-off studies;  analysis/ — their figures and CSV outputs
scripts/build.ps1              — Build / OTA / USB flash per board
conversation_log.md            — Session-by-session design decisions log
```
