// mow_afe4490 — Test firmware: mow_afe4490 vs protocentral-afe4490-arduino
// v0.7 — ESP32-S3 (in3ator V15), Arduino + FreeRTOS
// Switches between both libraries at runtime via Serial command ('m' / 'p').

#define SERIAL_DOWNSAMPLING_RATIO 1

#include "mow_afe4490.h"
#include "protocentral_afe44xx.h"

#include <Arduino.h>
#include <SPI.h>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdarg.h>
#include <esp_chip_info.h>
#include <esp_mac.h>

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

// XOR checksum of all bytes between '$' and '*' (NMEA style).
// p: pointer to character after '$'; len: number of bytes to XOR.
static uint8_t frame_xor_chk(const char* p, int len) {
    uint8_t chk = 0;
    while (len-- > 0) chk ^= (uint8_t)*p++;
    return chk;
}

// ── Runtime library selection ─────────────────────────────────────────────────
enum class ActiveLib { PROTOCENTRAL, MOW };
volatile ActiveLib g_active_lib = ActiveLib::MOW;  // default at startup

// ── Mow frame mode ────────────────────────────────────────────────────────────
enum class MowFrameMode { M1, M2 };  // M1=full frame (default), M2=raw ADC only
volatile MowFrameMode g_mow_frame_mode = MowFrameMode::M1;

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
                // $P1,SmpCnt,Ts_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI
                char buf[384];
                int n = snprintf(buf, sizeof(buf) - 6,
                    "$P1,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f",
                    cnt, ts,
                    (long)protocentral_data.RED_data,
                    (long)protocentral_data.IR_data,
                    (long)protocentral_data.ambientRED_data,
                    (long)protocentral_data.ambientIR_data,
                    (long)protocentral_data.REDminusAmbient_data,
                    (long)protocentral_data.IRminusAmbient_data,
                    (long)(protocentral_data.IR_filtered_data * -1), // PPG
                    (double)protocentral_data.spo2,
                    -1.0f,  // SpO2SQI — not available in protocentral
                    -1.0f,  // SpO2_R  — not available in protocentral
                    -1.0f,  // PI      — not available in protocentral
                    (double)protocentral_data.heart_rate,
                    -1.0f,  // HR1SQI  — not available in protocentral
                    -1.0f,  // HR2     — not available in protocentral
                    -1.0f,  // HR2SQI  — not available in protocentral
                    -1.0f,  // HR3     — not available in protocentral
                    -1.0f); // HR3SQI  — not available in protocentral
                uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                Serial.print(buf);
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
static volatile uint32_t mow_tx_dropped   = 0;  // frames skipped: TX buffer too full at frame start

// ── Ambient-subtraction consistency check (temporary — remove #define to disable)
// Verifies that the hardware-subtracted values (led1_aled1, led2_aled2) equal the
// software difference of the individually-read raw registers.
// Reports a one-line summary every 500 samples (~1 s at 500 Hz).
// #define CHK_AMB_SUB
#ifdef CHK_AMB_SUB
static uint32_t chk_n         = 0;
static uint32_t chk_mismatches = 0;
static int32_t  chk_max_d_ir  = 0;
static int32_t  chk_max_d_red = 0;

static void chk_amb_sub(const AFE4490Data& d) {
    int32_t d_ir  = d.led1_aled1 - (d.led1 - d.aled1);
    int32_t d_red = d.led2_aled2 - (d.led2 - d.aled2);
    if (d_ir != 0 || d_red != 0) chk_mismatches++;
    if (abs(d_ir)  > chk_max_d_ir)  chk_max_d_ir  = abs(d_ir);
    if (abs(d_red) > chk_max_d_red) chk_max_d_red = abs(d_red);
    if (++chk_n % 500 == 0)
        Serial_printf("# CHK n=%lu mis=%lu max_d_ir=%ld max_d_red=%ld\n",
                      chk_n, chk_mismatches, chk_max_d_ir, chk_max_d_red);
}
#endif  // CHK_AMB_SUB

void Mow_Task(void *pvParameters) {
    for (;;) {
        AFE4490Data data;
        if (mow.getData(data)) {
            mow_sample_count++;
#ifdef CHK_AMB_SUB
            chk_amb_sub(data);
#endif
            if (mow_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {  // send only 1 out of N samples to avoid saturating the serial port
                // Diagnostic: count frames where TX buffer has < 30 bytes free (nearly full —
                // next Serial.print will likely block or drop bytes).
                if (Serial.availableForWrite() < 30) mow_tx_dropped++;

                if (g_mow_frame_mode == MowFrameMode::M1) {
                    // $M1,SmpCnt,Ts_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI
                    char buf[384];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M1,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f",
                        (unsigned long)mow_sample_count,
                        (unsigned long)micros(),
                        (long)data.led2,       // RED
                        (long)data.led1,       // IR
                        (long)data.aled2,      // AmbRED
                        (long)data.aled1,      // AmbIR
                        (long)data.led2_aled2, // REDSub
                        (long)data.led1_aled1, // IRSub
                        (long)data.ppg,        // PPG
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,                           // SpO2SQI
                        data.spo2_r,
                        data.pi,                                 // PI: Perfusion Index [%]
                        data.hr1_sqi > 0.0f ? data.hr1 : -1.0f,
                        data.hr1_sqi,                            // HR1SQI
                        data.hr2_sqi > 0.0f ? data.hr2 : -1.0f,
                        data.hr2_sqi,                            // HR2SQI
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi);                           // HR3SQI
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    Serial.print(buf);
                } else {
                    char buf[128];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M2,%lu,%ld,%ld,%ld,%ld,%ld,%ld",
                        (unsigned long)mow_sample_count,
                        (long)data.led2, (long)data.led1,
                        (long)data.aled2, (long)data.aled1,
                        (long)data.led2_aled2, (long)data.led1_aled1);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    Serial.print(buf);
                }

                // Periodic TX health report (~every 10 s at 500 Hz)
                if (mow_sample_count % 5000 == 0)
                    Serial_printf("# STAT n=%lu tx_dropped=%lu\n",
                                  (unsigned long)mow_sample_count, (unsigned long)mow_tx_dropped);
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
    mow.setFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 20.0f);
    xTaskCreatePinnedToCore(Mow_Task, "MOW", 8192, NULL, 3, &g_mow_task, 0);  // core 0: separates Serial TX from USB-CDC driver (core 1)
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
                g_mow_frame_mode = MowFrameMode::M1;
                start_mow();
            } else if (cmd == 'p') {
                stop_mow();
                stop_protocentral();
                vTaskDelay(pdMS_TO_TICKS(200));
                g_mow_frame_mode = MowFrameMode::M1;
                start_protocentral();
            } else if (cmd == '1' && g_active_lib == ActiveLib::MOW) {
                g_mow_frame_mode = MowFrameMode::M1;
                Serial.println("# Frame mode: $M1 (full)");
            } else if (cmd == '2' && g_active_lib == ActiveLib::MOW) {
                g_mow_frame_mode = MowFrameMode::M2;
                Serial.println("# Frame mode: $M2 (raw)");
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    Serial.setTxBufferSize(1024);  // enlarge USB-CDC TX buffer (default ~256) to reduce corruption at 500 Hz
    Serial.begin(921600);

    // System info — shown in ppg_plotter log on startup/reset (prefix "# SYS:")
    {
        esp_chip_info_t chip;
        esp_chip_info(&chip);
        uint8_t mac[6];
        esp_read_mac(mac, ESP_MAC_WIFI_STA);
        Serial.printf("# SYS: ESP32-S3 rev.%d, %d cores @ %d MHz\n",
            chip.revision, chip.cores, ESP.getCpuFreqMHz());
        Serial.printf("# SYS: Flash %lu MB | PSRAM %lu MB (free %lu KB)\n",
            (unsigned long)(ESP.getFlashChipSize() / (1024UL * 1024)),
            (unsigned long)(ESP.getPsramSize()     / (1024UL * 1024)),
            (unsigned long)(ESP.getFreePsram()     / 1024UL));
        Serial.printf("# SYS: Heap free %lu KB | IDF %s\n",
            (unsigned long)(esp_get_free_heap_size() / 1024UL),
            esp_get_idf_version());
        Serial.printf("# SYS: MAC %02X:%02X:%02X:%02X:%02X:%02X\n",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    }

    SPI.begin(36, 37, 35, -1);  // CLK=36, MOSI=37, MISO=35, CS=-1 (managed per device).
                                // Called here and not inside each library: SPI is a shared bus —
                                // multiple devices can coexist via beginTransaction()/endTransaction().
                                // Calling SPI.begin() inside a library would risk reinitialising the
                                // bus and breaking other devices sharing it.

    xTaskCreatePinnedToCore(Cmd_Task, "CMD", 2048, NULL, 2, NULL, 0);  // Serial command handler: switches active library at runtime ('m' = mow, 'p' = protocentral).

    start_mow();  // default library at startup — send 'p' over Serial to switch to protocentral, 'm' to switch back
}

void loop() {}
