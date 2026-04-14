// PulseNest — Test firmware for incunest_afe4490 validation
// v0.9 — ESP32-S3 (Incunest V15/V16), Arduino + FreeRTOS
// Board pins defined in platformio.ini build_flags per environment.

#define SERIAL_DOWNSAMPLING_RATIO 1

#include "incunest_afe4490.h"

#include <Arduino.h>
#include <SPI.h>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdarg.h>
#include <esp_chip_info.h>
#include <esp_mac.h>

// ── Pin definitions ───────────────────────────────────────────────────────────
// Defined in platformio.ini build_flags per board environment (incunest_V15 / incunest_V16).
// Required: AFE4490_CS_PIN, AFE4490_DRDY_PIN, AFE4490_PWDN_PIN,
//           AFE4490_SCK_PIN, AFE4490_MISO_PIN, AFE4490_MOSI_PIN
#if !defined(AFE4490_CS_PIN) || !defined(AFE4490_DRDY_PIN) || !defined(AFE4490_PWDN_PIN) || \
    !defined(SPI_SCK_PIN) || !defined(SPI_MISO_PIN) || !defined(SPI_MOSI_PIN)
  #error "Board pin definitions missing — select a valid environment (incunest_V15 or incunest_V16)"
#endif

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

// ── Incunest frame mode ────────────────────────────────────────────────────────────
enum class IncunestFrameMode { M1, M2 };  // M1=full frame (default), M2=raw ADC only
volatile IncunestFrameMode g_incunest_frame_mode = IncunestFrameMode::M1;

// ═══════════════════════════════════════════════════════════════════════════════
// Library — incunest_afe4490
// ═══════════════════════════════════════════════════════════════════════════════
INCUNEST_AFE4490              afe;
TaskHandle_t             g_incunest_task        = nullptr;
static volatile uint32_t incunest_sample_count  = 0;
static volatile uint32_t incunest_tx_dropped   = 0;  // frames skipped: TX buffer too full at frame start

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

void Incunest_Task(void *pvParameters) {
    for (;;) {
        AFE4490Data data;
        if (afe.getData(data)) {
            incunest_sample_count++;
#ifdef CHK_AMB_SUB
            chk_amb_sub(data);
#endif
            if (incunest_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {  // send only 1 out of N samples to avoid saturating the serial port
                // Diagnostic: count frames where TX buffer has < 30 bytes free (nearly full —
                // next Serial.print will likely block or drop bytes).
                if (Serial.availableForWrite() < 30) incunest_tx_dropped++;

                if (g_incunest_frame_mode == IncunestFrameMode::M1) {
                    // $M1,SmpCnt,Ts_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,PPG,SpO2,SpO2_SQI,SpO2_R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI
                    char buf[384];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M1,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)micros(),
                        (long)data.led2,       // RED
                        (long)data.led1,       // IR
                        (long)data.aled2,      // RED_Amb
                        (long)data.aled1,      // IR_Amb
                        (long)data.led2_aled2, // RED_Sub
                        (long)data.led1_aled1, // IR_Sub
                        (long)data.ppg,        // PPG
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,                           // SpO2_SQI
                        data.spo2_r,
                        data.pi,                                 // PI: Perfusion Index [%]
                        data.hr1_sqi > 0.0f ? data.hr1 : -1.0f,
                        data.hr1_sqi,                            // HR1_SQI
                        data.hr2_sqi > 0.0f ? data.hr2 : -1.0f,
                        data.hr2_sqi,                            // HR2_SQI
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi);                           // HR3_SQI
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    Serial.print(buf);
                } else {
                    char buf[128];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M2,%lu,%ld,%ld,%ld,%ld,%ld,%ld",
                        (unsigned long)incunest_sample_count,
                        (long)data.led2, (long)data.led1,
                        (long)data.aled2, (long)data.aled1,
                        (long)data.led2_aled2, (long)data.led1_aled1);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    Serial.print(buf);
                }

                // Periodic TX health report (~every 10 s at 500 Hz)
                if (incunest_sample_count % 5000 == 0)
                    Serial_printf("# STAT n=%lu tx_dropped=%lu\n",
                                  (unsigned long)incunest_sample_count, (unsigned long)incunest_tx_dropped);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));  // 1 ms: yields CPU without missing samples. 2 ms (= sample period at 500 Hz) risks losing DRDY due to scheduler phase jitter.
    }
}

void start_incunest() {
    // Hard reset via PWDN (afe does not manage this pin)
    pinMode(AFE4490_PWDN_PIN, OUTPUT);
    digitalWrite(AFE4490_PWDN_PIN, LOW);
    vTaskDelay(pdMS_TO_TICKS(100));
    digitalWrite(AFE4490_PWDN_PIN, HIGH);
    vTaskDelay(pdMS_TO_TICKS(100));

    incunest_sample_count = 0;
    afe.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN);
    afe.setFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 20.0f);
    xTaskCreatePinnedToCore(Incunest_Task, "INCUNEST", 8192, NULL, 3, &g_incunest_task, 0);  // core 0: separates Serial TX from USB-CDC driver (core 1)
    Serial.println("# incunest_afe4490 started");
}

void stop_incunest() {
    if (g_incunest_task) {
        vTaskDelete(g_incunest_task);
        g_incunest_task = nullptr;
    }
    afe.stop();
}

// ── AFE4490Config enum → string helpers ───────────────────────────────────────
static const char* tia_gain_str(AFE4490TIAGain g) {
    switch (g) {
        case AFE4490TIAGain::RF_10K:  return "10K";
        case AFE4490TIAGain::RF_25K:  return "25K";
        case AFE4490TIAGain::RF_50K:  return "50K";
        case AFE4490TIAGain::RF_100K: return "100K";
        case AFE4490TIAGain::RF_250K: return "250K";
        case AFE4490TIAGain::RF_500K: return "500K";
        case AFE4490TIAGain::RF_1M:   return "1M";
        default:                      return "?";
    }
}
static const char* tia_cf_str(AFE4490TIACF cf) {
    switch (cf) {
        case AFE4490TIACF::CF_5P:   return "5p";
        case AFE4490TIACF::CF_10P:  return "10p";
        case AFE4490TIACF::CF_20P:  return "20p";
        case AFE4490TIACF::CF_30P:  return "30p";
        case AFE4490TIACF::CF_55P:  return "55p";
        case AFE4490TIACF::CF_155P: return "155p";
        default:                    return "?";
    }
}
static const char* stage2_str(AFE4490Stage2Gain g) {
    switch (g) {
        case AFE4490Stage2Gain::GAIN_0DB:   return "0dB";
        case AFE4490Stage2Gain::GAIN_3_5DB: return "3.5dB";
        case AFE4490Stage2Gain::GAIN_6DB:   return "6dB";
        case AFE4490Stage2Gain::GAIN_9_5DB: return "9.5dB";
        case AFE4490Stage2Gain::GAIN_12DB:  return "12dB";
        default:                            return "?";
    }
}
static const char* channel_str(AFE4490Channel ch) {
    switch (ch) {
        case AFE4490Channel::LED1:       return "LED1";
        case AFE4490Channel::LED2:       return "LED2";
        case AFE4490Channel::ALED1:      return "ALED1";
        case AFE4490Channel::ALED2:      return "ALED2";
        case AFE4490Channel::LED1_ALED1: return "LED1_ALED1";
        case AFE4490Channel::LED2_ALED2: return "LED2_ALED2";
        default:                         return "?";
    }
}
static const char* filter_str(AFE4490Filter f) {
    switch (f) {
        case AFE4490Filter::NONE:           return "NONE";
        case AFE4490Filter::MOVING_AVERAGE: return "MA";
        case AFE4490Filter::BUTTERWORTH:    return "BW";
        default:                            return "?";
    }
}

// Emit a $CFG frame with the current AFE4490 configuration.
// Called from Cmd_Task (low priority) — safe to call Serial.print() here;
// the UART hardware buffer serialises writes from all tasks.
static void send_cfg_frame() {
    AFE4490Config cfg = afe.getConfig();
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char buf[320];
    int n = snprintf(buf, sizeof(buf) - 6,
        "$CFG,sr=%u,numav=%u,led1=%.2f,led2=%.2f,range=%u"
        ",tia=%s,cf=%s,stg2=%s,ch=%s,flt=%s"
        ",fl=%.2f,fh=%.2f,hr2l=%.2f,hr2h=%.2f,hr3h=%.2f"
        ",spo2a=%.4f,spo2b=%.4f"
        ",board=%s,mac=%02X:%02X:%02X:%02X:%02X:%02X",
        cfg.sample_rate_hz, cfg.num_averages,
        cfg.led1_current_mA, cfg.led2_current_mA, (unsigned)cfg.led_range_mA,
        tia_gain_str(cfg.tia_gain), tia_cf_str(cfg.tia_cf), stage2_str(cfg.stage2_gain),
        channel_str(cfg.ppg_channel), filter_str(cfg.filter_type),
        cfg.filter_f_low_hz, cfg.filter_f_high_hz,
        cfg.hr2_f_low_hz, cfg.hr2_f_high_hz, cfg.hr3_f_high_hz,
        cfg.spo2_a, cfg.spo2_b,
        BOARD_VERSION,
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
    Serial.print(buf);
}

// ── Command task ──────────────────────────────────────────────────────────────
// Accepts commands over Serial (host → ESP32):
//   '1'      → frame mode $M1 (full)
//   '2'      → frame mode $M2 (raw ADC only)
//   '$CFG?\n'→ emit $CFG frame with current AFE4490 configuration
// Multi-byte commands are accumulated until '\n'.
void Cmd_Task(void *pvParameters) {
    char cmd_buf[32];
    int  cmd_len = 0;
    for (;;) {
        while (Serial.available()) {
            char c = (char)Serial.read();
            if (c == '\r') continue;  // ignore CR from CRLF line endings
            if (c == '\n' || cmd_len >= (int)sizeof(cmd_buf) - 1) {
                cmd_buf[cmd_len] = '\0';
                if (cmd_len == 1 && cmd_buf[0] == '1') {
                    g_incunest_frame_mode = IncunestFrameMode::M1;
                    Serial.println("# Frame mode: $M1 (full)");
                } else if (cmd_len == 1 && cmd_buf[0] == '2') {
                    g_incunest_frame_mode = IncunestFrameMode::M2;
                    Serial.println("# Frame mode: $M2 (raw)");
                } else if (strcmp(cmd_buf, "$CFG?") == 0) {
                    send_cfg_frame();
                }
                cmd_len = 0;
            } else {
                cmd_buf[cmd_len++] = c;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    Serial.setTxBufferSize(1024);  // enlarge USB-CDC TX buffer (default ~256) to reduce corruption at 500 Hz
    Serial.begin(921600);
    vTaskDelay(pdMS_TO_TICKS(500));  // wait for USB CDC to stabilise before printing

    // Startup banner
    Serial.printf("# PulseNest v0.9 | incunest_afe4490 v" INCUNEST_AFE4490_VERSION
                  "+sha." INCUNEST_GIT_HASH
                  " | build: " __DATE__ " " __TIME__
                  " | Board: %s — Medical Open World\n", BOARD_VERSION);

    // System info — shown in pulsenest_lab log on startup/reset (prefix "# SYS:")
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

    SPI.begin(SPI_SCK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, -1);
                                // CS=-1: managed per device via AFE4490_CS_PIN.
                                // Called here and not inside the library: SPI is a shared bus —
                                // multiple devices can coexist via beginTransaction()/endTransaction().
                                // Calling SPI.begin() inside a library would risk reinitialising the
                                // bus and breaking other devices sharing it.

    xTaskCreatePinnedToCore(Cmd_Task, "CMD", 4096, NULL, 2, NULL, 0);

    start_incunest();
}

void loop() {}
