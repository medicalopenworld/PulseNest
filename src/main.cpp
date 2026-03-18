#define SERIAL_DOWNSAMPLING_RATIO 10

#include "mow_afe4490.h"
#include "protocentral_afe44xx.h"

#include <Arduino.h>
#include <SPI.h>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdarg.h>

/// Pin definitions
#define AFE44XX_CS_PIN      21
#define AFE44XX_PWDN_PIN     0
#define AFE44XX_ADC_RDY_PIN 45

inline void Serial_printf(const char *fmt, ...) {
    char buffer[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);
    Serial.print(buffer);
}

// ── Runtime library selection ─────────────────────────────────────────────────
enum class ActiveLib { PROTOCENTRAL, MOW };
volatile ActiveLib g_active_lib = ActiveLib::MOW;  // default at startup

// ═══════════════════════════════════════════════════════════════════════════════
// Librería A — protocentral_afe44xx
// ═══════════════════════════════════════════════════════════════════════════════
AFE44XX       afe44xx(AFE44XX_CS_PIN, AFE44XX_PWDN_PIN);
afe44xx_data  afe44xx_raw_data;

volatile unsigned long last_intr_time_us = 0;
volatile unsigned long sample_counter    = 0;
volatile bool          afe4490_ADC_ready = false;
TaskHandle_t           g_spo2_task       = nullptr;

void IRAM_ATTR afe4490ADCReady() {
    last_intr_time_us = micros();
    sample_counter++;
    afe4490_ADC_ready = true;
}

void SPO2_Task(void *pvParameters) {
    for (;;) {
        if (afe4490_ADC_ready) {
            noInterrupts();
            unsigned long ts  = last_intr_time_us;
            unsigned long cnt = sample_counter;
            afe4490_ADC_ready = false;
            interrupts();

            afe44xx.get_AFE44XX_Data(&afe44xx_raw_data);

            if (cnt % SERIAL_DOWNSAMPLING_RATIO == 0) {
                Serial.print("$P1,");
                Serial.print(cnt);
                Serial.print(",");
                Serial.print(ts);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.IR_filtered_data * -1);  // ppg (inverted)
                Serial.print(",");
                Serial.print(afe44xx_raw_data.spo2);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.heart_rate);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.RED_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.IR_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.ambientRED_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.ambientIR_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.REDminusAmbient_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.IRminusAmbient_data);
                Serial.print(",");
                Serial.print(afe44xx_raw_data.RED_filtered_data);
                Serial.print(",");
                Serial.println(afe44xx_raw_data.IR_filtered_data);
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Librería B — mow_afe4490
// ═══════════════════════════════════════════════════════════════════════════════
MOW_AFE4490            mow;
TaskHandle_t           g_mow_output_task = nullptr;
static volatile uint32_t mow_sample_count = 0;

void Mow_Output_Task(void *pvParameters) {
    for (;;) {
        AFE4490Data data;
        if (mow.getData(data)) {
            mow_sample_count++;
            if (mow_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {
                Serial.print("$M0,");
                Serial.print(mow_sample_count);
                Serial.print(",");
                Serial.print(micros());
                Serial.print(",");
                Serial.print(data.ppg);
                Serial.print(",");
                Serial.print(data.spo2_valid ? data.spo2 : -1.0f);
                Serial.print(",");
                Serial.print(data.hr_valid ? (int)data.hr : -1);
                Serial.print(",");
                Serial.print(data.led2);        // RED raw
                Serial.print(",");
                Serial.print(data.led1);        // IR raw
                Serial.print(",");
                Serial.print(data.aled2);       // AmbRED
                Serial.print(",");
                Serial.print(data.aled1);       // AmbIR
                Serial.print(",");
                Serial.print(data.led2_aled2);  // REDSub
                Serial.print(",");
                Serial.print(data.led1_aled1);  // IRSub
                Serial.print(",");
                Serial.print(data.led2_aled2);  // REDFilt (placeholder — no filtered data yet)
                Serial.print(",");
                Serial.println(data.led1_aled1); // IRFilt (placeholder — no filtered data yet)
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// ── Library start / stop ──────────────────────────────────────────────────────
void start_mow() {
    // Hard reset via PWDN (mow does not manage this pin)
    pinMode(AFE44XX_PWDN_PIN, OUTPUT);
    digitalWrite(AFE44XX_PWDN_PIN, LOW);
    vTaskDelay(pdMS_TO_TICKS(100));
    digitalWrite(AFE44XX_PWDN_PIN, HIGH);
    vTaskDelay(pdMS_TO_TICKS(100));

    mow_sample_count = 0;
    mow.begin(AFE44XX_CS_PIN, AFE44XX_ADC_RDY_PIN);
    xTaskCreatePinnedToCore(Mow_Output_Task, "MOW_OUT", 4096, NULL, 3,
                            &g_mow_output_task, 1);
    g_active_lib = ActiveLib::MOW;
    Serial.println("# Switched to mow_afe4490");
}

void stop_mow() {
    if (g_mow_output_task) {
        vTaskDelete(g_mow_output_task);
        g_mow_output_task = nullptr;
    }
    mow.stop();
}

void start_protocentral() {
    sample_counter    = 0;
    afe4490_ADC_ready = false;
    afe44xx.afe44xx_init();
    pinMode(AFE44XX_ADC_RDY_PIN, INPUT_PULLUP);
    attachInterrupt(AFE44XX_ADC_RDY_PIN, afe4490ADCReady, RISING);
    xTaskCreatePinnedToCore(SPO2_Task, "SPO2", 4096, NULL, 1, &g_spo2_task, 1);
    g_active_lib = ActiveLib::PROTOCENTRAL;
    Serial.println("# Switched to protocentral");
}

void stop_protocentral() {
    detachInterrupt(AFE44XX_ADC_RDY_PIN);
    afe4490_ADC_ready = false;
    if (g_spo2_task) {
        vTaskDelete(g_spo2_task);
        g_spo2_task = nullptr;
    }
}

// ── Command task ──────────────────────────────────────────────────────────────
// Accepts single-character commands over Serial:
//   'm' → switch to mow_afe4490
//   'p' → switch to protocentral
void Cmd_Task(void *pvParameters) {
    for (;;) {
        if (Serial.available()) {
            char cmd = (char)Serial.read();
            if (cmd == 'm') {
                stop_protocentral();
                stop_mow();
                vTaskDelay(pdMS_TO_TICKS(200));
                start_mow();
            } else if (cmd == 'p') {
                stop_mow();
                stop_protocentral();
                vTaskDelay(pdMS_TO_TICKS(200));
                start_protocentral();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    SPI.begin(36, 37, 35, -1);  // CLK=36, MOSI=37, MISO=35, CS=-1 (managed per device)

    xTaskCreatePinnedToCore(Cmd_Task, "CMD", 2048, NULL, 2, NULL, 0);

    start_mow();  // default library at startup
}

void loop() {}
