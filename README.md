# mow_afe4490_test

**mow_afe4490_test** is validation tool for the library mow_afe4490.
**mow_afe4490** is a library (driver + algorithms) for AFE4490
**AFE4490** is an Analog Front End chip designed by Texas Instruments for pulse oximetry applications using photoplethysmography (PPG)
This repository is developed as part of the **IncuNest** project, open-source neonatal incubator by [Medical Open World](https://medicalopenworld.org).

The goal is to verify PPG signal quality and SpO2/HR calculation in isolation, before integrating the AFE4490 into the main IncuNest firmware. It also serves as a comparison testbed between the Protocentral library and the in-house `mow_afe4490` library.
This repository includes firmware code and python scripts to visualize serial output

## Hardware

| Component | Details |
|---|---|
| MCU | ESP32-S3 (in3ator board V15) |
| Sensor | AFE4490 via SPI |
| Framework | Arduino + PlatformIO |

## Build and flash

Requires [PlatformIO](https://platformio.org/).

```bash
# Build
pio run

# Flash (adjust port as needed)
pio run --target upload --upload-port COM15

# Serial monitor
pio device monitor --port COM15 --baud 115200
```

To select which library to use, switch at runtime via serial commands:
- `m` → mow_afe4490
- `p` → Protocentral AFE44XX

## PPG Plotter

Real-time signal visualizer. Requires Python 3 with `pyqtgraph`, `pyserial`, `numpy`, `scipy`.

```bash
python ppg_plotter.py
```

## Project structure

```
include/mow_afe4490.h     — In-house AFE4490 library (API)
src/mow_afe4490.cpp       — In-house AFE4490 library (implementation)
mow_afe4490_spec.md       — Library design specification
src/main.cpp              — Test firmware (dual-library harness)
ppg_plotter.py            — Real-time PPG/SpO2/HR visualizer
conversation_log.md       — Session-by-session design decisions log
```
