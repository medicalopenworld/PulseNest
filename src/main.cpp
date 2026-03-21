#define SERIAL_DOWNSAMPLING_RATIO 10

#include "mow_afe4490.h"
#include "protocentral_afe44xx.h"

#include <Arduino.h>
#include <SPI.h>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdarg.h>

// ── Pin definitions ───────────────────────────────────────────────────────────
#define AFE4490_CS_PIN      21
#define AFE4490_PWDN_PIN     0
#define AFE4490_DRDY_PIN 45

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
// Library A — protocentral_afe44xx
// ═══════════════════════════════════════════════════════════════════════════════
AFE44XX       protocentral(AFE4490_CS_PIN, AFE4490_PWDN_PIN);
afe44xx_data  protocentral_data;

volatile unsigned long protocentral_last_intr_us  = 0;
volatile unsigned long protocentral_sample_count  = 0;
volatile bool          protocentral_drdy_flag     = false;
TaskHandle_t           g_protocentral_task        = nullptr;

void IRAM_ATTR protocentral_drdy_isr() {
    protocentral_last_intr_us = micros();
    protocentral_sample_count++;
    protocentral_drdy_flag = true;
}

void Protocentral_Task(void *pvParameters) {
    for (;;) {
        if (protocentral_drdy_flag) {
            noInterrupts();
            unsigned long ts  = protocentral_last_intr_us;
            unsigned long cnt = protocentral_sample_count;
            protocentral_drdy_flag = false;
            interrupts();

            protocentral.get_AFE44XX_Data(&protocentral_data);

            if (cnt % SERIAL_DOWNSAMPLING_RATIO == 0) {
                Serial.print("$P1,");
                Serial.print(cnt);
                Serial.print(",");
                Serial.print(ts);
                Serial.print(",");
                Serial.print(protocentral_data.IR_filtered_data * -1);  // ppg (inverted)
                Serial.print(",");
                Serial.print(protocentral_data.spo2);
                Serial.print(",");
                Serial.print(protocentral_data.heart_rate);
                Serial.print(",");
                Serial.print(protocentral_data.RED_data);
                Serial.print(",");
                Serial.print(protocentral_data.IR_data);
                Serial.print(",");
                Serial.print(protocentral_data.ambientRED_data);
                Serial.print(",");
                Serial.print(protocentral_data.ambientIR_data);
                Serial.print(",");
                Serial.print(protocentral_data.REDminusAmbient_data);
                Serial.print(",");
                Serial.print(protocentral_data.IRminusAmbient_data);
                Serial.print(",");
                Serial.print(protocentral_data.RED_filtered_data);
                Serial.print(",");
                Serial.println(protocentral_data.IR_filtered_data);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));  // 1 ms: yields CPU without missing samples. 2 ms (= sample period at 500 Hz) risks losing DRDY due to scheduler phase jitter.
    }
}

void start_protocentral() {
    protocentral_sample_count = 0;
    protocentral_drdy_flag    = false;
    protocentral.afe44xx_init();
    pinMode(AFE4490_DRDY_PIN, INPUT_PULLUP);
    attachInterrupt(AFE4490_DRDY_PIN, protocentral_drdy_isr, RISING);
    xTaskCreatePinnedToCore(Protocentral_Task, "PROTOCENTRAL", 4096, NULL, 1, &g_protocentral_task, 1);
    g_active_lib = ActiveLib::PROTOCENTRAL;
    Serial.println("# Switched to protocentral");
}

void stop_protocentral() {
    detachInterrupt(AFE4490_DRDY_PIN);
    protocentral_drdy_flag = false;
    if (g_protocentral_task) {
        vTaskDelete(g_protocentral_task);
        g_protocentral_task = nullptr;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Library B — mow_afe4490
// ═══════════════════════════════════════════════════════════════════════════════
MOW_AFE4490              mow;
TaskHandle_t             g_mow_task        = nullptr;
static volatile uint32_t mow_sample_count  = 0;

void Mow_Task(void *pvParameters) {
    for (;;) {
        AFE4490Data data;
        if (mow.getData(data)) {
            mow_sample_count++;
            if (mow_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {  // send only 1 out of N samples to avoid saturating the serial port
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
        vTaskDelay(pdMS_TO_TICKS(1));  // 1 ms: yields CPU without missing samples. 2 ms (= sample period at 500 Hz) risks losing DRDY due to scheduler phase jitter.
    }
}

void start_mow() {
    // Hard reset via PWDN (mow does not manage this pin)
    pinMode(AFE4490_PWDN_PIN, OUTPUT);
    digitalWrite(AFE4490_PWDN_PIN, LOW);
    vTaskDelay(pdMS_TO_TICKS(100));
    digitalWrite(AFE4490_PWDN_PIN, HIGH);
    vTaskDelay(pdMS_TO_TICKS(100));

    mow_sample_count = 0;
    mow.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN);
    xTaskCreatePinnedToCore(Mow_Task, "MOW", 4096, NULL, 3, &g_mow_task, 1);
    g_active_lib = ActiveLib::MOW;
    Serial.println("# Switched to mow_afe4490");
}

void stop_mow() {
    if (g_mow_task) {
        vTaskDelete(g_mow_task);
        g_mow_task = nullptr;
    }
    mow.stop();
}

// ── Command task ──────────────────────────────────────────────────────────────
// Accepts single-character commands over Serial (host → ESP32):
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
    SPI.begin(36, 37, 35, -1);  // CLK=36, MOSI=37, MISO=35, CS=-1 (managed per device).
                                // Called here and not inside each library: SPI is a shared bus —
                                // multiple devices can coexist via beginTransaction()/endTransaction().
                                // Calling SPI.begin() inside a library would risk reinitialising the
                                // bus and breaking other devices sharing it.

    xTaskCreatePinnedToCore(Cmd_Task, "CMD", 2048, NULL, 2, NULL, 0);  // Serial command handler: switches active library at runtime ('m' = mow, 'p' = protocentral).

    start_mow();  // default library at startup — send 'p' over Serial to switch to protocentral, 'm' to switch back
}

void loop() {}
