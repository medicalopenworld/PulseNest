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

// Emit a $TCFG frame with all 28 raw timing register values read from the chip.
// Format: $TCFG,t1=<v>,...,t28=<v>*XX
static void send_tcfg_frame() {
    AFE4490TimingConfig t = afe.getTimingConfig();
    char buf[512];
    int n = snprintf(buf, sizeof(buf) - 6,
        "$TCFG"
        ",t1=%lu,t2=%lu,t3=%lu,t4=%lu,t5=%lu,t6=%lu,t7=%lu"
        ",t8=%lu,t9=%lu,t10=%lu,t11=%lu,t12=%lu,t13=%lu,t14=%lu"
        ",t15=%lu,t16=%lu,t17=%lu,t18=%lu,t19=%lu,t20=%lu"
        ",t21=%lu,t22=%lu,t23=%lu,t24=%lu,t25=%lu,t26=%lu,t27=%lu,t28=%lu",
        (unsigned long)t.t1,  (unsigned long)t.t2,  (unsigned long)t.t3,  (unsigned long)t.t4,
        (unsigned long)t.t5,  (unsigned long)t.t6,  (unsigned long)t.t7,  (unsigned long)t.t8,
        (unsigned long)t.t9,  (unsigned long)t.t10, (unsigned long)t.t11, (unsigned long)t.t12,
        (unsigned long)t.t13, (unsigned long)t.t14, (unsigned long)t.t15, (unsigned long)t.t16,
        (unsigned long)t.t17, (unsigned long)t.t18, (unsigned long)t.t19, (unsigned long)t.t20,
        (unsigned long)t.t21, (unsigned long)t.t22, (unsigned long)t.t23, (unsigned long)t.t24,
        (unsigned long)t.t25, (unsigned long)t.t26, (unsigned long)t.t27, (unsigned long)t.t28);
    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
    Serial.print(buf);
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
    send_tcfg_frame();  // always emit timing config alongside $CFG
}

// ── $SET command helpers ───────────────────────────────────────────────────────
// Parse enum strings used in $CFG frames (same vocabulary as tia_gain_str etc.)
static bool parse_tia_gain(const char* s, AFE4490TIAGain& out) {
    if      (strcmp(s, "10K")  == 0) { out = AFE4490TIAGain::RF_10K;  return true; }
    else if (strcmp(s, "25K")  == 0) { out = AFE4490TIAGain::RF_25K;  return true; }
    else if (strcmp(s, "50K")  == 0) { out = AFE4490TIAGain::RF_50K;  return true; }
    else if (strcmp(s, "100K") == 0) { out = AFE4490TIAGain::RF_100K; return true; }
    else if (strcmp(s, "250K") == 0) { out = AFE4490TIAGain::RF_250K; return true; }
    else if (strcmp(s, "500K") == 0) { out = AFE4490TIAGain::RF_500K; return true; }
    else if (strcmp(s, "1M")   == 0) { out = AFE4490TIAGain::RF_1M;   return true; }
    return false;
}
static bool parse_tia_cf(const char* s, AFE4490TIACF& out) {
    if      (strcmp(s, "5p")   == 0) { out = AFE4490TIACF::CF_5P;   return true; }
    else if (strcmp(s, "10p")  == 0) { out = AFE4490TIACF::CF_10P;  return true; }
    else if (strcmp(s, "20p")  == 0) { out = AFE4490TIACF::CF_20P;  return true; }
    else if (strcmp(s, "30p")  == 0) { out = AFE4490TIACF::CF_30P;  return true; }
    else if (strcmp(s, "55p")  == 0) { out = AFE4490TIACF::CF_55P;  return true; }
    else if (strcmp(s, "155p") == 0) { out = AFE4490TIACF::CF_155P; return true; }
    return false;
}
static bool parse_stage2(const char* s, AFE4490Stage2Gain& out) {
    if      (strcmp(s, "0dB")   == 0) { out = AFE4490Stage2Gain::GAIN_0DB;   return true; }
    else if (strcmp(s, "3.5dB") == 0) { out = AFE4490Stage2Gain::GAIN_3_5DB; return true; }
    else if (strcmp(s, "6dB")   == 0) { out = AFE4490Stage2Gain::GAIN_6DB;   return true; }
    else if (strcmp(s, "9.5dB") == 0) { out = AFE4490Stage2Gain::GAIN_9_5DB; return true; }
    else if (strcmp(s, "12dB")  == 0) { out = AFE4490Stage2Gain::GAIN_12DB;  return true; }
    return false;
}

// Process a validated $SET command (key and value already split, checksum verified).
// Hardware params (LED, TIA, gain) are applied hot via the library setters.
// Sample rate requires stop/restart to recalculate timing registers and algorithm state.
static void apply_set_cmd(const char* key, const char* val) {
    if (strcmp(key, "led1") == 0) {
        afe.setLED1Current(atof(val));
        Serial_printf("# SET led1=%.2f mA\n", atof(val));
    } else if (strcmp(key, "led2") == 0) {
        afe.setLED2Current(atof(val));
        Serial_printf("# SET led2=%.2f mA\n", atof(val));
    } else if (strcmp(key, "ledrange") == 0) {
        int r = atoi(val);
        if (r == 75 || r == 150) {
            afe.setLEDRange((uint8_t)r);
            Serial_printf("# SET ledrange=%d mA\n", r);
        } else {
            Serial_printf("$ERR,ledrange,invalid (75 or 150)\r\n");
            return;
        }
    } else if (strcmp(key, "tiagain") == 0) {
        AFE4490TIAGain g;
        if (parse_tia_gain(val, g)) {
            afe.setTIAGain(g);
            Serial_printf("# SET tiagain=%s\n", val);
        } else {
            Serial_printf("$ERR,tiagain,invalid (10K/25K/50K/100K/250K/500K/1M)\r\n");
            return;
        }
    } else if (strcmp(key, "tiacf") == 0) {
        AFE4490TIACF cf;
        if (parse_tia_cf(val, cf)) {
            afe.setTIACF(cf);
            Serial_printf("# SET tiacf=%s\n", val);
        } else {
            Serial_printf("$ERR,tiacf,invalid (5p/10p/20p/30p/55p/155p)\r\n");
            return;
        }
    } else if (strcmp(key, "stg2") == 0) {
        AFE4490Stage2Gain g;
        if (parse_stage2(val, g)) {
            afe.setStage2Gain(g);
            Serial_printf("# SET stg2=%s\n", val);
        } else {
            Serial_printf("$ERR,stg2,invalid (0dB/3.5dB/6dB/9.5dB/12dB)\r\n");
            return;
        }
    } else if (strcmp(key, "numav") == 0) {
        int n = atoi(val);
        if (n >= 1 && n <= 128) {
            afe.setNumAverages((uint8_t)n);
            Serial_printf("# SET numav=%d\n", n);
        } else {
            Serial_printf("$ERR,numav,invalid (1-128)\r\n");
            return;
        }
    } else if (strcmp(key, "sr") == 0) {
        int hz = atoi(val);
        if (hz >= 63 && hz <= 5000) {
            Serial_printf("# SET sr=%d Hz — restarting...\n", hz);
            stop_incunest();
            afe.setSampleRate((uint16_t)hz);
            start_incunest();
        } else {
            Serial_printf("$ERR,sr,invalid (63-5000)\r\n");
            return;
        }
    } else {
        // Timing registers t1–t28 (register addresses 0x01–0x1C)
        static const struct { const char* key; uint8_t addr; } timing_regs[] = {
            {"t1",0x01},{"t2",0x02},{"t3",0x03},{"t4",0x04},
            {"t5",0x05},{"t6",0x06},{"t7",0x07},{"t8",0x08},
            {"t9",0x09},{"t10",0x0A},{"t11",0x0B},{"t12",0x0C},
            {"t13",0x0D},{"t14",0x0E},{"t15",0x0F},{"t16",0x10},
            {"t17",0x11},{"t18",0x12},{"t19",0x13},{"t20",0x14},
            {"t21",0x15},{"t22",0x16},{"t23",0x17},{"t24",0x18},
            {"t25",0x19},{"t26",0x1A},{"t27",0x1B},{"t28",0x1C},
        };
        for (const auto& r : timing_regs) {
            if (strcmp(key, r.key) == 0) {
                uint32_t v = (uint32_t)strtoul(val, nullptr, 10);
                if (v > 65535UL) {
                    Serial_printf("$ERR,%s,out of range (0-65535)\r\n", key);
                    return;
                }
                afe.setTimingReg(r.addr, v);
                Serial_printf("# SET %s(0x%02X)=%lu\n", key, r.addr, (unsigned long)v);
                send_tcfg_frame();
                return;  // $TCFG emitted; no $CFG needed for timing-only changes
            }
        }
        Serial_printf("$ERR,%s,unknown key\r\n", key);
        return;
    }
    send_cfg_frame();
}

// ── Command task ──────────────────────────────────────────────────────────────
// Accepts commands over Serial (host → ESP32):
//   '1'           → frame mode $M1 (full)
//   '2'           → frame mode $M2 (raw ADC only)
//   '$CFG?\n'     → emit $CFG frame with current AFE4490 configuration
//   '$SET,k,v*XX' → set hardware parameter k to value v (XOR checksum verified)
// Multi-byte commands are accumulated until '\n'.
void Cmd_Task(void *pvParameters) {
    char cmd_buf[64];
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
                } else if (strncmp(cmd_buf, "$SET,", 5) == 0) {
                    // Verify XOR checksum: $SET,key,val*XX
                    char* star = strrchr(cmd_buf, '*');
                    if (star && (star - cmd_buf) >= 5) {
                        uint8_t expected = (uint8_t)strtoul(star + 1, nullptr, 16);
                        uint8_t actual   = frame_xor_chk(cmd_buf + 1, (int)(star - cmd_buf) - 1);
                        if (actual == expected) {
                            *star = '\0';  // terminate before '*'
                            // Split "SET,key,val" into key and val
                            char* body = cmd_buf + 5;  // skip "$SET,"
                            char* comma = strchr(body, ',');
                            if (comma) {
                                *comma = '\0';
                                apply_set_cmd(body, comma + 1);
                            }
                        } else {
                            Serial_printf("$ERR,checksum,got %02X expected %02X\r\n", actual, expected);
                        }
                    }
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
