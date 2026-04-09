// mow_afe4490 — Basic Example
// v0.7 — ESP32-S3, Arduino + FreeRTOS
// Spec: mow_afe4490_spec.md
//
// Minimal example showing how to integrate mow_afe4490 into an application.
// Reads PPG, SpO2 and heart rate from an AFE4490 chip and prints results
// over Serial at 115200 baud.
//
// Hardware assumed:
//   - ESP32-S3
//   - AFE4490 connected via SPI
//   - Standard finger clip SpO2 probe (red ~660 nm, IR ~940 nm)
//
// Key concepts:
//   1. SPI.begin() must be called by the application — the library does NOT
//      call it internally, because SPI is a shared bus that may be used by
//      other devices.
//   2. mow.begin() configures the chip, attaches the DRDY ISR and starts an
//      internal FreeRTOS task. You do not need to manage any of that.
//   3. getData() is non-blocking. Call it in a loop; it returns true only
//      when a new processed sample is ready.
//   4. Never use delay() in FreeRTOS tasks — always use vTaskDelay().

#include <Arduino.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "mow_afe4490.h"

// ── Pin definitions ───────────────────────────────────────────────────────────
// Adapt these to your board's actual wiring.
#define AFE4490_CS_PIN    21   // SPI chip select (active low)
#define AFE4490_DRDY_PIN  45   // Data-ready interrupt — input, managed by library
#define AFE4490_PWDN_PIN   0   // Power-down / hard reset — output, managed here

// ── Library instance ──────────────────────────────────────────────────────────
MOW_AFE4490 mow;

// ── Reader task ───────────────────────────────────────────────────────────────
// Polls the library queue and prints results over Serial.
// The library runs its own internal task (ISR → SPI read → signal processing →
// queue push). This task only consumes the processed output.
void ReaderTask(void *pvParameters) {
    AFE4490Data data;

    for (;;) {
        if (mow.getData(data)) {
            // PPG waveform — raw ADC counts, bandpass-filtered
            Serial.print("PPG: ");
            Serial.print(data.ppg);

            // SpO2 — valid flag indicates enough samples have been accumulated
            Serial.print("  SpO2: ");
            if (data.spo2_sqi > 0.0f) {
                Serial.print(data.spo2, 1);
                Serial.print(" %");
            } else {
                Serial.print("--");
            }

            // HR via peak detection
            Serial.print("  HR1: ");
            if (data.hr1_sqi > 0.0f) {
                Serial.print(data.hr1, 0);
                Serial.print(" bpm");
            } else {
                Serial.print("--");
            }

            // HR via autocorrelation (more robust, higher latency)
            Serial.print("  HR2: ");
            if (data.hr2_sqi > 0.0f) {
                Serial.print(data.hr2, 0);
                Serial.print(" bpm");
            } else {
                Serial.print("--");
            }

            Serial.println();
        }

        // Yield to other tasks. 1 ms is sufficient — the library pushes data
        // at the configured sample rate (default 500 Hz = 2 ms/sample).
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// ── setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    while (!Serial) {}  // wait for Serial ready (USB CDC on ESP32-S3)

    // Step 1: initialise the SPI bus.
    // Pins: CLK=36, MOSI=37, MISO=35, CS=-1 (CS is managed per device via CS_PIN).
    // Must be done before mow.begin().
    SPI.begin(36, 37, 35, -1);

    // Step 2: hard-reset the AFE4490 via PWDN pin.
    // The library does not manage PWDN — do it here before begin().
    pinMode(AFE4490_PWDN_PIN, OUTPUT);
    digitalWrite(AFE4490_PWDN_PIN, LOW);
    vTaskDelay(pdMS_TO_TICKS(100));
    digitalWrite(AFE4490_PWDN_PIN, HIGH);
    vTaskDelay(pdMS_TO_TICKS(100));

    // Step 3: start the library.
    // This configures the chip registers, attaches the DRDY interrupt and
    // launches the internal processing task. Default settings:
    //   - Sample rate : 500 Hz
    //   - PPG channel : LED1_ALED1 (IR ambient-corrected)
    //   - Filter      : Butterworth bandpass 0.5–20 Hz
    //   - TIA gain    : 500 kΩ
    //   - SpO2 formula: SpO2 = 104 - 17·R  (generic, assumes ~940 nm IR LED)
    mow.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN);

    // ── Optional configuration (call after begin) ─────────────────────────────

    // Change the PPG bandpass filter (default 0.5–20 Hz is fine for most cases)
    // mow.setFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 20.0f);

    // Use Webster (1997) coefficients instead of the default (source-traceable)
    // NOTE: both sets assume ~940 nm IR. For 905 nm probes (e.g. UpnMed U401-D)
    //       an empirical calibration against a certified reference is required.
    // mow.setSpO2Coefficients(110.0f, 25.0f);

    // Increase LED current if the PPG signal is too weak
    // mow.setLED1Current(10.0f);  // IR  LED, mA
    // mow.setLED2Current(10.0f);  // RED LED, mA

    // Step 4: create the application task that reads and prints data.
    xTaskCreatePinnedToCore(ReaderTask, "READER", 4096, NULL, 3, NULL, 1);
}

// ── loop ──────────────────────────────────────────────────────────────────────
// Nothing here — all work is done in FreeRTOS tasks.
void loop() {}
