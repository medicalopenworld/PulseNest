// PulseNest — Test firmware for incunest_afe4490 validation
// v0.9 — ESP32-S3 (Incunest V15/V16), Arduino + FreeRTOS
// Board pins defined in platformio.ini build_flags per environment.

#define SERIAL_DOWNSAMPLING_RATIO 1

#include "incunest_afe4490.h"
#include "wifi_config.h"

#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiUDP.h>
#include <WebServer.h>
#include <Update.h>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
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

// Serial output mutex — prevents interleaving of frames from concurrent tasks.
// Created in setup() before tasks start; all Serial writes in tasks use these helpers.
static SemaphoreHandle_t g_serial_mutex = nullptr;

// Forward declaration: defined in the WiFi/UDP section below.
// Sends a line immediately via g_resp_udp when WiFi is active (no-op otherwise).
static void udp_send_line(const char* buf);

// Mutex-protected Serial.print — use for pre-built frame buffers.
// Also relays to UDP when WiFi is active so pulsenest_lab.py receives $CFG/$DIAG
// responses even when running cable-free (UDP-only mode).
static inline void Serial_print_locked(const char* s) {
    if (g_serial_mutex) xSemaphoreTake(g_serial_mutex, pdMS_TO_TICKS(20));
    Serial.print(s);
    if (g_serial_mutex) xSemaphoreGive(g_serial_mutex);
    udp_send_line(s);
}

// Mutex-protected Serial_printf — use for # comments and $ERR lines from tasks.
// Also relays to UDP when WiFi is active (same reasoning as Serial_print_locked).
inline void Serial_printf(const char *fmt, ...) {
    char buffer[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);
    if (g_serial_mutex) xSemaphoreTake(g_serial_mutex, pdMS_TO_TICKS(20));
    Serial.print(buffer);
    if (g_serial_mutex) xSemaphoreGive(g_serial_mutex);
    udp_send_line(buffer);
}

// XOR checksum of all bytes between '$' and '*' (NMEA style).
// p: pointer to character after '$'; len: number of bytes to XOR.
static uint8_t frame_xor_chk(const char* p, int len) {
    uint8_t chk = 0;
    while (len-- > 0) chk ^= (uint8_t)*p++;
    return chk;
}

// ── WiFi / UDP ────────────────────────────────────────────────────────────────
static WiFiUDP   g_udp;                         // data frames ESP32→PC (port UDP_TARGET_PORT, batched)
static WiFiUDP   g_cmd_udp;                     // command frames PC→ESP32 (port UDP_CMD_PORT)
static WiFiUDP   g_resp_udp;                    // response frames ESP32→PC (port UDP_TARGET_PORT, unbatched)
static bool      g_wifi_ready      = false;
static const char* g_udp_target_ip = nullptr;  // Set at connect time from WIFI_NETWORKS[]
static SemaphoreHandle_t g_resp_udp_mutex = nullptr;  // protects g_resp_udp across tasks

// OTA web server — serves a firmware-update page on port 80.
// OTA and UDP streaming coexist: WebServer uses TCP/80, data uses UDP/5005, commands use UDP/5006.
static WebServer g_ota_server(80);

// Batch buffer: accumulates UDP_BATCH_SIZE frames before one endPacket() call.
// M1 frame ≤ ~200 chars; 10 × 256 = 2560 bytes — well within WiFi MTU (~1460 bytes
// for a single fragment; lwIP will fragment transparently if needed).
static char     g_udp_batch_buf[UDP_BATCH_SIZE * 512];  // 512 per slot to fit $M4 frames (~310 chars)
static uint16_t g_udp_batch_len   = 0;
static uint8_t  g_udp_batch_count = 0;

// Append one frame to the batch; flush when UDP_BATCH_SIZE frames have accumulated.
// No-op if WiFi is not connected. Errors are silently ignored — USB-CDC is the fallback.
static inline void udp_send(const char* buf) {
    if (!g_wifi_ready) return;
    size_t len = strlen(buf);
    if (g_udp_batch_len + len >= sizeof(g_udp_batch_buf)) {
        // Safety flush: should not happen with correct UDP_BATCH_SIZE / frame-size assumptions.
        g_udp_batch_len   = 0;
        g_udp_batch_count = 0;
    }
    memcpy(g_udp_batch_buf + g_udp_batch_len, buf, len);
    g_udp_batch_len += (uint16_t)len;
    if (++g_udp_batch_count >= UDP_BATCH_SIZE) {
        g_udp.beginPacket(g_udp_target_ip, UDP_TARGET_PORT);
        g_udp.write(reinterpret_cast<const uint8_t*>(g_udp_batch_buf), g_udp_batch_len);
        g_udp.endPacket();
        g_udp_batch_len   = 0;
        g_udp_batch_count = 0;
    }
}

// Send a single response frame immediately over UDP (no batching).
// Used for $CFG, $TCFG, $DIAG, $ERR, and # comment lines routed via Serial_printf /
// Serial_print_locked. Protected by g_resp_udp_mutex so it is safe from any task.
// No-op if WiFi is not connected.
static void udp_send_line(const char* buf) {
    if (!g_wifi_ready) return;
    size_t len = strlen(buf);
    if (len == 0) return;
    if (g_resp_udp_mutex) xSemaphoreTake(g_resp_udp_mutex, pdMS_TO_TICKS(10));
    g_resp_udp.beginPacket(g_udp_target_ip, UDP_TARGET_PORT);
    g_resp_udp.write(reinterpret_cast<const uint8_t*>(buf), len);
    g_resp_udp.endPacket();
    if (g_resp_udp_mutex) xSemaphoreGive(g_resp_udp_mutex);
}

// ── Incunest frame mode ────────────────────────────────────────────────────────────
// M1 = PPG only (minimal bandwidth)
// M2 = PPG + SpO2 + HR3 + quality flags (lightweight monitoring)
// M3 = full AFE4490Data — all production fields (default)
// M4 = M3 + AFE4490DebugData analog signals (V_TIA, I_PD for all 4 channels)
enum class IncunestFrameMode { M1, M2, M3, M4 };
volatile IncunestFrameMode g_incunest_frame_mode = IncunestFrameMode::M3;

// ═══════════════════════════════════════════════════════════════════════════════
// Library — incunest_afe4490
// ═══════════════════════════════════════════════════════════════════════════════
INCUNEST_AFE4490              afe;
TaskHandle_t             g_incunest_task        = nullptr;
static volatile uint32_t incunest_sample_count  = 0;
static volatile uint32_t incunest_tx_dropped   = 0;  // frames skipped: TX buffer too full at frame start

// ── Ambient-subtraction consistency check — OBSOLETE (kept for reference)
// Originally used to detect 22-bit overflow in REG_LED1_ALED1VAL / REG_LED2_ALED2VAL.
// The root cause was fixed in incunest_afe4490.cpp: those hardware registers are no
// longer read; led1_sub/led2_sub are now computed in SW as int32_t (led1-aled1 /
// led2-aled2), which cannot overflow. This check would always report zero mismatches.
// #define CHK_AMB_SUB  // permanently disabled — see above
#ifdef CHK_AMB_SUB
static uint32_t chk_n         = 0;
static uint32_t chk_mismatches = 0;
static int32_t  chk_max_d_ir  = 0;
static int32_t  chk_max_d_red = 0;

static void chk_amb_sub(const AFE4490Data& d) {
    int32_t d_ir  = d.led1_sub - (d.led1 - d.aled1);
    int32_t d_red = d.led2_sub - (d.led2 - d.aled2);
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
        AFE4490DebugData dbg;
        if (afe.getData(data, &dbg)) {
            incunest_sample_count++;
#ifdef CHK_AMB_SUB
            chk_amb_sub(data);
#endif
            if (incunest_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {  // send only 1 out of N samples to avoid saturating the serial port
                // Diagnostic: count frames where TX buffer has < 30 bytes free (nearly full —
                // next Serial.print will likely block or drop bytes).
                if (Serial.availableForWrite() < 30) incunest_tx_dropped++;

                if (g_incunest_frame_mode == IncunestFrameMode::M1) {
                    // $M1,SmpCnt,Ts_us,PPG_DISP*XX
                    char buf[128];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M1,%lu,%lu,%ld",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)micros(),
                        (long)data.ppg_disp);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    if (!g_wifi_ready) Serial_print_locked(buf);
                    udp_send(buf);
                } else if (g_incunest_frame_mode == IncunestFrameMode::M2) {
                    // $M2,SmpCnt,Ts_us,PPG_DISP,SpO2,SpO2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState*XX
                    char buf[192];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M2,%lu,%lu,%ld,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)micros(),
                        (long)data.ppg_disp,
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi,
                        (unsigned)data.rsqi,
                        (unsigned long)data.diag_code,
                        (int)data.probe_state);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    if (!g_wifi_ready) Serial_print_locked(buf);
                    udp_send(buf);
                } else if (g_incunest_frame_mode == IncunestFrameMode::M3) {
                    // $M3,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,
                    //     SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState*XX
                    char buf[384];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M3,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)micros(),
                        (long)data.led2,       (long)data.led1,
                        (long)data.aled2,      (long)data.aled1,
                        (long)data.led2_sub,   (long)data.led1_sub,
                        (long)data.ppg_disp,
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,
                        data.spo2_r,
                        data.pi,
                        data.hr1_sqi > 0.0f ? data.hr1 : -1.0f,
                        data.hr1_sqi,
                        data.hr2_sqi > 0.0f ? data.hr2 : -1.0f,
                        data.hr2_sqi,
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi,
                        (unsigned)data.rsqi,
                        (unsigned long)data.diag_code,
                        (int)data.probe_state);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    if (!g_wifi_ready) Serial_print_locked(buf);  // suppress serial data frames when UDP active — keeps serial free for $SET/$CFG control traffic
                    udp_send(buf);
                } else {  // M4
                    // $M4 = M3 + V_TIA_LED1/2/ALED1/2 + I_PD_LED1/2/ALED1/2 (all in scientific notation)
                    char buf[512];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M4,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d"
                        ",%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)micros(),
                        (long)data.led2,       (long)data.led1,
                        (long)data.aled2,      (long)data.aled1,
                        (long)data.led2_sub,   (long)data.led1_sub,
                        (long)data.ppg_disp,
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,
                        data.spo2_r,
                        data.pi,
                        data.hr1_sqi > 0.0f ? data.hr1 : -1.0f,
                        data.hr1_sqi,
                        data.hr2_sqi > 0.0f ? data.hr2 : -1.0f,
                        data.hr2_sqi,
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi,
                        (unsigned)data.rsqi,
                        (unsigned long)data.diag_code,
                        (int)data.probe_state,
                        dbg.analog.v_tia_led1,  dbg.analog.v_tia_led2,
                        dbg.analog.v_tia_aled1, dbg.analog.v_tia_aled2,
                        dbg.analog.i_pd_led1,   dbg.analog.i_pd_led2,
                        dbg.analog.i_pd_aled1,  dbg.analog.i_pd_aled2);
                    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
                    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
                    if (!g_wifi_ready) Serial_print_locked(buf);
                    udp_send(buf);
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
    afe.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN, true);  // debug=true: combined queue items for atomic getData(data,dbg)
    afe.setPPGDispFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 20.0f);
    xTaskCreatePinnedToCore(Incunest_Task, "INCUNEST", 8192, NULL, 3, &g_incunest_task, 0);  // core 0: separates Serial TX from USB-CDC driver (core 1)
    Serial_printf("# incunest_afe4490 started\n");
}

void stop_incunest() {
    if (g_incunest_task) {
        vTaskDelete(g_incunest_task);
        g_incunest_task = nullptr;
    }
    afe.stop();
}

// tia_gain_str / tia_cf_str / stage2_str — moved to incunest_afe4490.h as
// afeRFToStr / afeCFToStr / afeRGToStr (inline). Removed local copies.
static const char* channel_str(AFE4490Channel ch) {
    switch (ch) {
        case AFE4490Channel::LED1:       return "LED1";
        case AFE4490Channel::LED2:       return "LED2";
        case AFE4490Channel::ALED1:      return "ALED1";
        case AFE4490Channel::ALED2:      return "ALED2";
        case AFE4490Channel::LED1_SUB: return "LED1_SUB";
        case AFE4490Channel::LED2_SUB: return "LED2_SUB";
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
    Serial_print_locked(buf);
}

// Emit a $CFG frame with the current AFE4490 configuration.
// Called from Cmd_Task (low priority) — safe to call Serial.print() here;
// the UART hardware buffer serialises writes from all tasks.
static void send_cfg_frame() {
    AFE4490Config cfg = afe.getConfig();
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char buf[600];
    int n = snprintf(buf, sizeof(buf) - 6,
        "$CFG,sr=%u,numav=%u,led1=%.2f,led2=%.2f,range=%u"
        ",ensepgain=%d"
        ",tia1=%s,rf1_ohm=%.0f,cf1=%s,cf1_pF=%.0f,stg21=%s,rg1_ohm=%.0f,rg1_x=%.4f,stage2en1=%d"
        ",tia2=%s,rf2_ohm=%.0f,cf2=%s,cf2_pF=%.0f,stg22=%s,rg2_ohm=%.0f,rg2_x=%.4f,stage2en2=%d"
        ",ambdac=%u,ri_ohm=%.0f"
        ",ch=%s,flt=%s"
        ",fl=%.2f,fh=%.2f,hr2l=%.2f,hr2h=%.2f,hr3h=%.2f"
        ",spo2a=%.4f,spo2b=%.4f"
        ",board=%s,mac=%02X:%02X:%02X:%02X:%02X:%02X",
        cfg.afe_sample_rate_hz, cfg.afe_adc_averages,
        cfg.afe_led1_current_mA, cfg.afe_led2_current_mA, (unsigned)cfg.afe_led_range_mA,
        cfg.afe_sep_tia_en ? 1 : 0,
        afeRFToStr(cfg.afe_tia_rf_led1), kAFE_RF_OHM[(int)cfg.afe_tia_rf_led1],
        afeCFToStr(cfg.afe_tia_cf_led1),   kAFE_CF_PF[(int)cfg.afe_tia_cf_led1],
        afeRGToStr(cfg.afe_stg2_rg_led1), kAFE_RG_OHM[(int)cfg.afe_stg2_rg_led1], kAFE_RG_GAIN[(int)cfg.afe_stg2_rg_led1],
        cfg.afe_stg2_en_led1 ? 1 : 0,
        afeRFToStr(cfg.afe_tia_rf_led2), kAFE_RF_OHM[(int)cfg.afe_tia_rf_led2],
        afeCFToStr(cfg.afe_tia_cf_led2),   kAFE_CF_PF[(int)cfg.afe_tia_cf_led2],
        afeRGToStr(cfg.afe_stg2_rg_led2), kAFE_RG_OHM[(int)cfg.afe_stg2_rg_led2], kAFE_RG_GAIN[(int)cfg.afe_stg2_rg_led2],
        cfg.afe_stg2_en_led2 ? 1 : 0,
        (unsigned)cfg.afe_ambdac_uA, kAFE_RI_OHM,
        channel_str(cfg.ppgdisp_channel), filter_str(cfg.ppgdisp_filter_type),
        cfg.ppgdisp_f_low_hz, cfg.ppgdisp_f_high_hz,
        cfg.hr2_f_low_hz, cfg.hr2_f_high_hz, cfg.hr3_f_high_hz,
        cfg.spo2_a, cfg.spo2_b,
        BOARD_VERSION,
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
    snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
    Serial_print_locked(buf);
    send_tcfg_frame();  // always emit timing config alongside $CFG
}

// parse_tia_gain / parse_tia_cf / parse_stage2 — moved to incunest_afe4490.h as
// afeStrToRF / afeStrToCF / afeStrToRG (inline). Removed local copies.

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
    } else if (strcmp(key, "ensepgain") == 0) {
        int v = atoi(val);
        if (v == 0 || v == 1) {
            afe.setEnSepGain(v == 1);
            Serial_printf("# SET ensepgain=%d\n", v);
        } else {
            Serial_printf("$ERR,ensepgain,invalid (0 or 1)\r\n");
            return;
        }
    // Joint TIA gain setters (both channels at once)
    } else if (strcmp(key, "tiagain") == 0) {
        AFE4490RF g;
        if (afeStrToRF(val, g)) {
            afe.setTIAGain(g);
            Serial_printf("# SET tiagain=%s (both channels)\n", val);
        } else {
            Serial_printf("$ERR,tiagain,invalid (10K/25K/50K/100K/250K/500K/1M)\r\n");
            return;
        }
    } else if (strcmp(key, "tiacf") == 0) {
        AFE4490TIACF cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACF(cf);
            Serial_printf("# SET tiacf=%s (both channels)\n", val);
        } else {
            Serial_printf("$ERR,tiacf,invalid (5p/10p/20p/30p/55p/155p)\r\n");
            return;
        }
    } else if (strcmp(key, "stg2") == 0) {
        AFE4490RG g;
        if (afeStrToRG(val, g)) {
            afe.setStage2Gain(g);
            Serial_printf("# SET stg2=%s (both channels)\n", val);
        } else {
            Serial_printf("$ERR,stg2,invalid (0dB/3.5dB/6dB/9.5dB/12dB)\r\n");
            return;
        }
    // Per-channel setters — LED1 (IR)
    } else if (strcmp(key, "tiagain1") == 0) {
        AFE4490RF g;
        if (afeStrToRF(val, g)) {
            afe.setTIAGainLED1(g);
            Serial_printf("# SET tiagain1=%s (LED1/IR)\n", val);
        } else {
            Serial_printf("$ERR,tiagain1,invalid (10K/25K/50K/100K/250K/500K/1M)\r\n");
            return;
        }
    } else if (strcmp(key, "tiacf1") == 0) {
        AFE4490TIACF cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACFLED1(cf);
            Serial_printf("# SET tiacf1=%s (LED1/IR)\n", val);
        } else {
            Serial_printf("$ERR,tiacf1,invalid (5p/10p/20p/30p/55p/155p)\r\n");
            return;
        }
    } else if (strcmp(key, "stg21") == 0) {
        AFE4490RG g;
        if (afeStrToRG(val, g)) {
            afe.setStage2GainLED1(g);
            Serial_printf("# SET stg21=%s (LED1/IR)\n", val);
        } else {
            Serial_printf("$ERR,stg21,invalid (0dB/3.5dB/6dB/9.5dB/12dB)\r\n");
            return;
        }
    // Per-channel setters — LED2 (RED)
    } else if (strcmp(key, "tiagain2") == 0) {
        AFE4490RF g;
        if (afeStrToRF(val, g)) {
            afe.setTIAGainLED2(g);
            Serial_printf("# SET tiagain2=%s (LED2/RED)\n", val);
        } else {
            Serial_printf("$ERR,tiagain2,invalid (10K/25K/50K/100K/250K/500K/1M)\r\n");
            return;
        }
    } else if (strcmp(key, "tiacf2") == 0) {
        AFE4490TIACF cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACFLED2(cf);
            Serial_printf("# SET tiacf2=%s (LED2/RED)\n", val);
        } else {
            Serial_printf("$ERR,tiacf2,invalid (5p/10p/20p/30p/55p/155p)\r\n");
            return;
        }
    } else if (strcmp(key, "stg22") == 0) {
        AFE4490RG g;
        if (afeStrToRG(val, g)) {
            afe.setStage2GainLED2(g);
            Serial_printf("# SET stg22=%s (LED2/RED)\n", val);
        } else {
            Serial_printf("$ERR,stg22,invalid (0dB/3.5dB/6dB/9.5dB/12dB)\r\n");
            return;
        }
    } else if (strcmp(key, "numav") == 0) {
        int n = atoi(val);
        if (n >= 1 && n <= 128) {
            afe.setAdcAverages((uint8_t)n);
            Serial_printf("# SET numav=%d\n", n);
        } else {
            Serial_printf("$ERR,numav,invalid (1-128)\r\n");
            return;
        }
    } else if (strcmp(key, "stage2en1") == 0) {
        int v = atoi(val);
        if (v == 0 || v == 1) {
            afe.setStage2En1(v != 0);
            Serial_printf("# SET stage2en1=%d\n", v);
        } else {
            Serial_printf("$ERR,stage2en1,invalid (0 or 1)\r\n");
            return;
        }
    } else if (strcmp(key, "stage2en2") == 0) {
        int v = atoi(val);
        if (v == 0 || v == 1) {
            afe.setStage2En2(v != 0);
            Serial_printf("# SET stage2en2=%d\n", v);
        } else {
            Serial_printf("$ERR,stage2en2,invalid (0 or 1)\r\n");
            return;
        }
    } else if (strcmp(key, "ambdac") == 0) {
        int uA = atoi(val);
        if (uA >= 0 && uA <= 10) {
            afe.setAmbDac((uint8_t)uA);
            Serial_printf("# SET ambdac=%d uA\n", uA);
        } else {
            Serial_printf("$ERR,ambdac,invalid (0-10)\r\n");
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

// ── OTA web server ────────────────────────────────────────────────────────────
// Self-contained HTML page — no CDN dependency, works offline.
static const char* g_ota_html =
    "<html><head><title>PulseNest OTA</title>"
    "<style>body{font-family:monospace;background:#111;color:#eee;padding:24px;}"
    "h2{color:#4f4;}input[type=file]{color:#eee;margin-right:8px;}"
    "input[type=submit]{background:#1a3a1a;color:#4f4;border:1px solid #4f4;"
    "padding:6px 14px;cursor:pointer;font-size:15px;}"
    "#p{margin-top:14px;font-size:18px;}</style></head>"
    "<body><h2>PulseNest OTA Flash</h2>"
    "<p>Select the <b>.bin</b> firmware file and click Flash.</p>"
    "<form id='f'>"
    "<input type='file' name='update' accept='.bin' required>"
    "<input type='submit' value='Flash'>"
    "</form><div id='p'></div>"
    "<script>"
    "document.getElementById('f').onsubmit=function(e){"
    "e.preventDefault();"
    "var p=document.getElementById('p'),x=new XMLHttpRequest();"
    "x.open('POST','/update');"
    "x.upload.onprogress=function(e){"
    "if(e.lengthComputable)p.innerHTML='Flashing: '+Math.round(e.loaded/e.total*100)+'%';};"
    "x.onload=function(){"
    "p.innerHTML=(x.status===200&&x.responseText==='OK')"
    "?'<b style=color:#4f4>Done — rebooting\u2026</b>'"
    ":'<b style=color:#f44>FAILED: '+x.responseText+'</b>';};"
    "x.send(new FormData(this));};"
    "</script></body></html>";

static void ota_server_init() {
    g_ota_server.on("/", HTTP_GET, []() {
        g_ota_server.sendHeader("Connection", "close");
        g_ota_server.send(200, "text/html", g_ota_html);
    });
    g_ota_server.on(
        "/update", HTTP_POST,
        []() {  // called after upload completes — send result and reboot
            g_ota_server.sendHeader("Connection", "close");
            g_ota_server.send(200, "text/plain", Update.hasError() ? "FAIL" : "OK");
            vTaskDelay(pdMS_TO_TICKS(300));
            ESP.restart();
        },
        []() {  // called for each upload chunk
            HTTPUpload& upload = g_ota_server.upload();
            if (upload.status == UPLOAD_FILE_START) {
                Serial_printf("# OTA start: %s\n", upload.filename.c_str());
                if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
            } else if (upload.status == UPLOAD_FILE_WRITE) {
                if (Update.write(upload.buf, upload.currentSize) != upload.currentSize)
                    Update.printError(Serial);
            } else if (upload.status == UPLOAD_FILE_END) {
                if (Update.end(true)) {
                    Serial_printf("# OTA success: %lu bytes — rebooting\n",
                                  (unsigned long)upload.totalSize);
                } else {
                    Update.printError(Serial);
                }
            }
        });
    g_ota_server.begin();
}

// ── Command processing (shared by Serial and UDP paths) ───────────────────────
// Extracted from Cmd_Task so both Serial and UDP commands use the same logic.
// buf must be NUL-terminated and mutable (apply_set_cmd modifies it in-place).
static void process_command(char* cmd_buf, int cmd_len) {
    if (strncmp(cmd_buf, "$MODE,", 6) == 0) {
        const char* mode = cmd_buf + 6;
        if      (strcmp(mode, "M1") == 0) { g_incunest_frame_mode = IncunestFrameMode::M1; Serial_printf("# Frame mode: $M1 (PPG only)\n"); }
        else if (strcmp(mode, "M2") == 0) { g_incunest_frame_mode = IncunestFrameMode::M2; Serial_printf("# Frame mode: $M2 (PPG+SpO2+HR3)\n"); }
        else if (strcmp(mode, "M3") == 0) { g_incunest_frame_mode = IncunestFrameMode::M3; Serial_printf("# Frame mode: $M3 (full)\n"); }
        else if (strcmp(mode, "M4") == 0) { g_incunest_frame_mode = IncunestFrameMode::M4; Serial_printf("# Frame mode: $M4 (debug)\n"); }
        else { Serial_printf("$ERR,MODE,invalid (M1/M2/M3/M4)\r\n"); }
    } else if (strcmp(cmd_buf, "$CFG?") == 0) {
        send_cfg_frame();
    } else if (strcmp(cmd_buf, "$DIAG?") == 0) {
        uint32_t diag_val = afe.runAfeDiagnostics();
        char buf[32];
        int n = snprintf(buf, sizeof(buf) - 6, "$DIAG,%06lX",
                         (unsigned long)diag_val);
        uint8_t chk = frame_xor_chk(buf + 1, n - 1);
        snprintf(buf + n, sizeof(buf) - n, "*%02X\r\n", chk);
        Serial_print_locked(buf);
    } else if (strcmp(cmd_buf, "$RESET") == 0) {
        Serial_printf("# Resetting...\n");
        vTaskDelay(pdMS_TO_TICKS(50));
        ESP.restart();
    } else if (strncmp(cmd_buf, "$SET,", 5) == 0) {
        char* star = strrchr(cmd_buf, '*');
        if (star && (star - cmd_buf) >= 5) {
            uint8_t expected = (uint8_t)strtoul(star + 1, nullptr, 16);
            uint8_t actual   = frame_xor_chk(cmd_buf + 1, (int)(star - cmd_buf) - 1);
            if (actual == expected) {
                *star = '\0';
                char* body  = cmd_buf + 5;  // skip "$SET,"
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
}

// ── Command task ──────────────────────────────────────────────────────────────
// Accepts commands over Serial AND UDP (port UDP_CMD_PORT) when WiFi is active:
//   '$MODE,M1\n'  → frame mode $M1 (PPG only — minimal bandwidth)
//   '$MODE,M2\n'  → frame mode $M2 (PPG + SpO2 + HR3 + quality flags)
//   '$MODE,M3\n'  → frame mode $M3 (full AFE4490Data — default)
//   '$MODE,M4\n'  → frame mode $M4 (M3 + AFE4490DebugData analog signals)
//   '$CFG?\n'     → emit $CFG frame with current AFE4490 configuration
//   '$SET,k,v*XX' → set hardware parameter k to value v (XOR checksum verified)
//   '$DIAG?\n'    → run AFE4490 diagnostics, emit $DIAG,XXXXXX*YY frame
//   '$RESET\n'    → soft-reset via ESP.restart() (works over Serial and UDP)
// Serial: multi-byte commands are accumulated until '\n'.
// UDP: each datagram contains one complete command line (no accumulation needed).
// OTA: g_ota_server.handleClient() is polled here when WiFi is active.
void Cmd_Task(void *pvParameters) {
    char cmd_buf[64];
    int  cmd_len = 0;
    for (;;) {
        // ── Serial path (always active) ───────────────────────────────────────
        while (Serial.available()) {
            char c = (char)Serial.read();
            if (c == '\r') continue;  // ignore CR from CRLF line endings
            if (c == '\n' || cmd_len >= (int)sizeof(cmd_buf) - 1) {
                cmd_buf[cmd_len] = '\0';
                process_command(cmd_buf, cmd_len);
                cmd_len = 0;
            } else {
                cmd_buf[cmd_len++] = c;
            }
        }
        // ── UDP command path + OTA server (WiFi only) ─────────────────────────
        if (g_wifi_ready) {
            // Drain ALL pending UDP command datagrams in one cycle.
            // Single-packet polling (if) caused rapid-fire $SET bursts (e.g. sweep combos)
            // to be processed one per 50 ms tick, so later params (ambdac) arrived after
            // the settle timer had already elapsed or were dropped by the lwIP buffer.
            int pkt;
            while ((pkt = g_cmd_udp.parsePacket()) > 0) {
                char udp_cmd[64];
                int n = g_cmd_udp.read(udp_cmd, (int)sizeof(udp_cmd) - 1);
                // Strip trailing \r\n so process_command sees a clean string.
                while (n > 0 && (udp_cmd[n - 1] == '\r' || udp_cmd[n - 1] == '\n')) n--;
                if (n > 0) {
                    udp_cmd[n] = '\0';
                    process_command(udp_cmd, n);
                }
            }
            g_ota_server.handleClient();
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    g_serial_mutex    = xSemaphoreCreateMutex();  // protects concurrent Serial writes from multiple tasks
    g_resp_udp_mutex  = xSemaphoreCreateMutex();  // protects g_resp_udp (used by Incunest_Task + Cmd_Task)
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

    // WiFi + UDP init (STA mode — tries each network in WIFI_NETWORKS[] order, always from index 0)
    WiFi.mode(WIFI_STA);
    {
        for (int i = 0; i < WIFI_NETWORK_COUNT && !g_wifi_ready; i++) {
            Serial.printf("# WiFi trying [%d/%d] %s", i + 1, WIFI_NETWORK_COUNT,
                          WIFI_NETWORKS[i].ssid);
            WiFi.begin(WIFI_NETWORKS[i].ssid, WIFI_NETWORKS[i].password);
            for (int j = 0; j < 20 && WiFi.status() != WL_CONNECTED; j++) {
                vTaskDelay(pdMS_TO_TICKS(500));
                Serial.print(".");
            }
            if (WiFi.status() == WL_CONNECTED) {
                g_udp_target_ip = WIFI_NETWORKS[i].udp_target_ip;
                g_wifi_ready    = true;
                g_udp.begin(UDP_TARGET_PORT);       // data frames ESP32→PC
                g_cmd_udp.begin(UDP_CMD_PORT);      // command frames PC→ESP32
                g_resp_udp.begin(0);                // response frames ESP32→PC (any local port)
                ota_server_init();
                Serial.printf("\n# WiFi connected [%s] — IP %s  UDP \u2192 %s:%d\n",
                              WIFI_NETWORKS[i].ssid, WiFi.localIP().toString().c_str(),
                              g_udp_target_ip, UDP_TARGET_PORT);
                Serial.printf("# OTA: http://%s/\n", WiFi.localIP().toString().c_str());
                Serial.printf("# CMD UDP: listening on port %d\n", UDP_CMD_PORT);
            } else {
                const char* reason;
                switch (WiFi.status()) {
                    case WL_NO_SSID_AVAIL:   reason = "SSID_NOT_FOUND"; break;
                    case WL_CONNECT_FAILED:  reason = "WRONG_PASSWORD"; break;
                    case WL_CONNECTION_LOST: reason = "CONNECTION_LOST"; break;
                    case WL_DISCONNECTED:    reason = "AUTH_REJECTED";   break;
                    default:                 reason = "UNKNOWN";         break;
                }
                Serial.printf("\n# WiFi FAILED %s — %s\n",
                              WIFI_NETWORKS[i].ssid, reason);
                WiFi.disconnect();
            }
        }
    }
    if (!g_wifi_ready) {
        Serial.println("# WiFi FAILED all networks — USB-CDC only");
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
