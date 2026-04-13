# incunest_afe4490_test

**incunest_afe4490_test** is a validation tool for the library incunest_afe4490.

**incunest_afe4490** is a library (driver + algorithms) for AFE4490, implemented in `incunest_afe4490.h` and `incunest_afe4490.cpp`

**AFE4490** is an Analog Front End chip designed by Texas Instruments for pulse oximetry applications using photoplethysmography (PPG)

This repository is developed as part of the **IncuNest** project, open-source neonatal incubator by [Medical Open World](https://medicalopenworld.org).

The goal is to verify PPG signal quality and SpO2/HR calculation in isolation, before integrating the AFE4490 into the main IncuNest firmware.
This repository includes firmware code and a Python script to visualize serial output.

## Hardware

| Component | Details |
|---|---|
| MCU | ESP32-S3 (Incunest board V15 / V16) |
| Sensor | AFE4490 via SPI |
| Framework | Arduino + PlatformIO |

## Build and flash

Requires [PlatformIO](https://platformio.org/).

```bash
# Build and flash — select the environment matching your board
pio run -e incunest_V15 -t upload --upload-port COM15
pio run -e incunest_V16 -t upload --upload-port COM15

# Serial monitor
pio device monitor --port COM15 --baud 921600
```

## PPG Plotter

Real-time signal visualizer. Requires Python 3 with `pyqtgraph`, `pyserial`, `numpy`, `scipy`.

```bash
pythonw ppg_plotter.py
```

## Project structure

```
lib/incunest_afe4490/          — AFE4490 library (driver + algorithms)
  incunest_afe4490.h           — API
  incunest_afe4490.cpp         — Implementation
incunest_afe4490_spec.md       — Library design specification
src/main.cpp                   — Test firmware
examples/basic/main.cpp        — Minimal integration example
ppg_plotter.py                 — Real-time PPG/SpO2/HR visualizer
test/                          — Native unit tests (PlatformIO)
conversation_log.md            — Session-by-session design decisions log
```
