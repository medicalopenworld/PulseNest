// PulseNest — Test firmware for incunest_afe4490 validation — ESP-IDF build (phase 1 port)
// ESP32-S3 (IncuNest V15–V18), ESP-IDF + FreeRTOS. Board pins from Kconfig (main/Kconfig.projbuild).
// Ported line by line from src/main.cpp (Arduino): same tasks, framing, guards, commands and
// OTA — only the platform calls changed. src/main.cpp stays the reference until bench parity.

#define SERIAL_DOWNSAMPLING_RATIO 1

#include "incunest_afe4490.h"
#include "wifi_config.h"

#include <cerrno>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include "sdkconfig.h"
#include "build_version.h"          // PULSENEST_GIT_HASH / INCUNEST_GIT_HASH, generated every build
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_app_desc.h"           // esp_app_get_description(): ELF SHA-256 and IDF version
#include "esp_event.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "nvs_flash.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <stdarg.h>
#include <esp_chip_info.h>
#include <esp_mac.h>
#include <esp_system.h>   // esp_reset_reason()
#include <lwip/sockets.h>
#include <lwip/inet.h>

// ── Firmware version ──────────────────────────────────────────────────────────
// Was a bare "v0.9" literal inside the startup banner, reachable only over serial and
// therefore absent from every capture. Promoted to a macro so it can also travel in the
// $CFG frame: a capture whose FW_* columns cannot be attributed to a firmware version is
// uninterpretable once the algorithms change. INCUNEST_GIT_HASH comes from build_version.h
// (scripts/gen_build_version.py, every build) and identifies the exact build, which the version alone does
// not — during development most builds are uncommitted work on top of the same version.
#define PULSENEST_FW_VERSION "0.13"

// ── Pin definitions ────────────────────────────────────────────────────────────────────
// From Kconfig (main/Kconfig.projbuild, menu "PulseNest board"): one build directory per board,
// as PlatformIO had one environment per board. Same macro names as the Arduino build so the
// rest of this file is unchanged.
#define SPI_SCK_PIN       CONFIG_PULSENEST_SPI_SCK_PIN
#define SPI_MISO_PIN      CONFIG_PULSENEST_SPI_MISO_PIN
#define SPI_MOSI_PIN      CONFIG_PULSENEST_SPI_MOSI_PIN
#define AFE4490_CS_PIN    CONFIG_PULSENEST_AFE_CS_PIN
#define AFE4490_DRDY_PIN  CONFIG_PULSENEST_AFE_DRDY_PIN
#define AFE4490_PWDN_PIN  CONFIG_PULSENEST_AFE_PWDN_PIN
#define BOARD_VERSION     CONFIG_PULSENEST_BOARD_VERSION

// Serial output mutex — prevents interleaving of frames from concurrent tasks.
// Created in setup() before tasks start; all Serial writes in tasks use these helpers.
static SemaphoreHandle_t g_serial_mutex = nullptr;

// ── Console: UART0 through the ESP-IDF driver ────────────────────────────────────────────
// Same port and speed as the Arduino build (UART0 — this firmware never enables the S3's native
// USB). TX ring of 1024 B as before: ~11 ms at 921600, what keeps a burst from stalling the 500 Hz
// task; it does not make writes non-blocking. RX ring of 256 B for command lines. stdout is routed
// through the same driver (uart_vfs_dev_use_driver) and left unbuffered, so the library's
// console_printf() ($TIMING) and the printf() calls of app_main() share one path and one order.
#define CONSOLE_UART    UART_NUM_0
#define CONSOLE_BAUD    921600     // pulsenest_lab.py monitor speed; the ROM/bootloader log stays at 115200
#define CONSOLE_TX_BUF  1024
#define CONSOLE_RX_BUF  256
static void console_init(void) {
    uart_config_t cfg = {};
    cfg.baud_rate  = CONSOLE_BAUD;
    cfg.data_bits  = UART_DATA_8_BITS;
    cfg.parity     = UART_PARITY_DISABLE;
    cfg.stop_bits  = UART_STOP_BITS_1;
    cfg.flow_ctrl  = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;
    uart_driver_install(CONSOLE_UART, CONSOLE_RX_BUF, CONSOLE_TX_BUF, 0, NULL, 0);
    uart_param_config(CONSOLE_UART, &cfg);
    uart_vfs_dev_use_driver(CONSOLE_UART);
    setvbuf(stdout, NULL, _IONBF, 0);
}
// Bytes the TX ring can still take without blocking — Serial.availableForWrite() in Arduino.
static inline int console_tx_free(void) {
    size_t n = 0;
    return uart_get_tx_buffer_free_size(CONSOLE_UART, &n) == ESP_OK ? (int)n : 0;
}
static inline void console_write(const char* s) {
    uart_write_bytes(CONSOLE_UART, s, strlen(s));
}
static uint32_t sys_flash_size(void) {
    uint32_t bytes = 0;
    esp_flash_get_size(NULL, &bytes);
    return bytes;
}
// esp_wifi keeps its calibration data in NVS.
static void nvs_init(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

// Forward declaration: defined in the WiFi/UDP section below.
// Sends a line immediately via g_resp_udp when WiFi is active (no-op otherwise).
static void udp_send_line(const char* buf);
// Forward declaration: defined after the UDP queues. Console + diagnostic queue, never sendto().
static void diag_printf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

// Mutex-protected Serial.print — use for pre-built frame buffers.
// Also relays to UDP when WiFi is active so pulsenest_lab.py receives $CFG/$DIAG
// responses even when running cable-free (UDP-only mode).
static inline void Serial_print_locked(const char* s) {
    if (g_serial_mutex) xSemaphoreTake(g_serial_mutex, pdMS_TO_TICKS(20));
#ifdef PULSENEST_SERIAL_NONBLOCKING
    if (console_tx_free() >= (int)strlen(s)) console_write(s);
#else
    console_write(s);
#endif
    if (g_serial_mutex) xSemaphoreGive(g_serial_mutex);
    udp_send_line(s);
}

// Mutex-protected Serial_printf — use for # comments and $ERR lines from tasks.
// Also relays to UDP when WiFi is active (same reasoning as Serial_print_locked).
// NOT from a measurement task (Incunest_Task, or the library's acquisition task through the console
// tee): the relay is a synchronous sendto() under a mutex. Those use diag_printf() (fw 0.13).
inline void Serial_printf(const char *fmt, ...) {
    char buffer[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);
    if (g_serial_mutex) xSemaphoreTake(g_serial_mutex, pdMS_TO_TICKS(20));
#ifdef PULSENEST_SERIAL_NONBLOCKING
    if (console_tx_free() >= (int)strlen(buffer)) console_write(buffer);
#else
    console_write(buffer);
#endif
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

// Frames not sent because they did not fit: their buffer (frame_finish) or the UDP queue slot
// (udp_enqueue). Reported in the periodic "# STAT" line and by a rate-limited $ERR. One counter
// per queue, so measurements and diagnostics never hide each other's losses.
static volatile uint32_t incunest_frame_dropped = 0;
static volatile uint32_t incunest_diag_dropped  = 0;

// Closes a "$..." frame in place: checks snprintf's return BEFORE using it, then appends
// "*XX\r\n". Returns false when the payload did not fit in buf_size-6 — the frame must then be
// dropped, not sent: `n` is what snprintf WOULD have written, so buf+n reads past the buffer
// and buf_size-n underflows to a huge size_t (stack corruption). $CFG had this guard; the data
// frames $M1..$M4 did not. The %f fields of $M3/$M4 cannot be bounded by the format
// (tools/frame_size_bounds.py: worst case 727 B against a 512 B buffer), so this is the only
// thing between a pathological sample and memory corruption. The $ERR is rate-limited on
// purpose: Serial_printf() once per sample at 500 Hz would stall the acquisition task.
static bool frame_finish(char* buf, size_t buf_size, int n, const char* tag) {
    if (n < 0 || (size_t)n >= buf_size - 6) {
        const uint32_t k = incunest_frame_dropped + 1;   // not ++: volatile, C++20
        incunest_frame_dropped = k;
        if (k == 1 || k % 500 == 0)
            Serial_printf("$ERR,%s,frame too long (%d bytes, buffer %u), dropped x%lu\r\n",
                          tag, n, (unsigned)buf_size, (unsigned long)k);
        return false;
    }
    uint8_t chk = frame_xor_chk(buf + 1, n - 1);
    snprintf(buf + n, buf_size - n, "*%02X\r\n", chk);
    return true;
}

// ── WiFi / UDP ────────────────────────────────────────────────────────────────
// Data frames (hot path, 500 Hz): raw lwIP socket — avoids WiFiUDP overhead and
// endPacket() blocking. Batching in UDP_Task reduces packet rate to ~100/sec.
static int             g_udp_sock   = -1;           // raw socket: data frames ESP32→PC
static struct sockaddr_in g_udp_dest;               // pre-filled destination (IP + port)
static int       g_cmd_sock  = -1;                  // lwIP socket on UDP_CMD_PORT: command frames PC→ESP32
// Control lines ESP32→PC ($CFG, $ERR, '#'…) go through g_udp_sock too — same destination as the
// data frames — serialised by g_resp_udp_mutex (udp_send_line) against each other.
static bool      g_wifi_ready      = false;
static const char* g_udp_target_ip = nullptr;       // Set at connect time from WIFI_NETWORKS[]
static SemaphoreHandle_t g_resp_udp_mutex = nullptr;  // serialises udp_send_line() across tasks

// OTA web server — esp_http_server on port 80 (its own task; no handleClient() polling).
// OTA and UDP streaming coexist: TCP/80 for the page and the image, UDP/5005 data, UDP/5006 commands.
static httpd_handle_t g_ota_server = nullptr;

// ── UDP queues (producers → UDP_Task) ─────────────────────────────────────────
// Two queues, one per kind of line, so that a measurement datagram carries UDP_BATCH_SIZE
// measurement frames and nothing else (fw 0.12):
//   g_udp_data_queue  $M1..$M4, one per sample, from Incunest_Task (500 Hz, core 0).
//   g_udp_diag_queue  the library's $TIMING / $TASK / $TASKS_END burst (five lines every 5 s),
//                     from the console tee on the library's acquisition task (core 1); and, since
//                     fw 0.13, every other line a measurement task emits (`# STAT`, the
//                     frame-too-long `$ERR`) through diag_printf() — so no measurement task ever
//                     calls the network stack.
// Both producers only xQueueSend(..., 0): non-blocking, ~µs. UDP_Task batches the data queue
// UDP_BATCH_SIZE frames per datagram (500/s → ~100 datagrams/s, well below lwIP's TX buffers and
// within the 1472 B UDP MTU) and, right after each batch, drains the diagnostic queue into a
// datagram of its own. In fw 0.11 the diagnostic lines shared the data queue: they took slots in
// two consecutive data batches every 5 s, so "five frames per datagram" was false 0.4 % of the
// time, the host's partial-batch counter fired on a healthy link, and a burst of diagnostics
// competed with the measurements for the same 64 slots (measured 2026-09-15, conversation_log).
#define UDP_QUEUE_FRAME_SIZE  288   // queue slot; $M4 measured 265 B (probe off), 274 B (probe on).
                                    // A line that does not fit is DROPPED and counted (udp_enqueue),
                                    // never truncated. Worst case cannot be bounded by the format:
                                    // tools/frame_size_bounds.py.
#define UDP_QUEUE_DEPTH       64    // data: ~128 ms headroom at 500 Hz
#define UDP_DIAG_QUEUE_DEPTH  8     // diagnostics: one burst is five lines
#define UDP_BATCH_SIZE        5     // frames per datagram: 5×288 = 1440 bytes < 1472 MTU
#define UDP_MTU               1472  // max UDP payload without IP fragmentation (Ethernet/WiFi)

// Compile-time guard: worst-case batch (all frames at max size) must fit within MTU.
// If this fails, reduce UDP_BATCH_SIZE or UDP_QUEUE_FRAME_SIZE. Covers the diagnostic datagram
// too: udp_flush_diag() packs at most UDP_BATCH_SIZE lines into the same buffer.
static_assert(UDP_QUEUE_FRAME_SIZE * UDP_BATCH_SIZE <= UDP_MTU,
    "UDP batch worst-case exceeds MTU — reduce UDP_BATCH_SIZE or UDP_QUEUE_FRAME_SIZE");

static QueueHandle_t g_udp_data_queue = nullptr;
static QueueHandle_t g_udp_diag_queue = nullptr;

// Deposit one line into `q`. Returns immediately — sendto() happens in UDP_Task, not here.
// Drops silently if the queue is full (USB-CDC is the fallback); a line that does not fit the
// slot is dropped and counted in `*dropped`.
static inline void udp_enqueue(QueueHandle_t q, const char* buf, volatile uint32_t* dropped) {
#ifdef PULSENEST_NO_DATA_STREAM
    // Bench experiment only (build with -DPULSENEST_NO_DATA_STREAM): suppress the data stream
    // so the station's radio is genuinely idle. Command replies are unaffected - they go out
    // through udp_send_line()/g_resp_udp, not through these queues - which is what makes it
    // possible to measure command latency on an idle station. Never ship this flag.
    (void)q; (void)buf; (void)dropped;
    return;
#endif
    if (!g_wifi_ready || g_udp_sock < 0 || q == nullptr) return;
    const size_t len = strlen(buf);
    if (len >= UDP_QUEUE_FRAME_SIZE) {
        // Does not fit the queue slot: DROP, never truncate. strlcpy() used to cut the frame
        // here, losing "*XX\r\n"; the stub was then glued to the next frame in the batch and
        // the host reported two BAD CHK with no clue why. Typical $M4: 265 B against 288.
        const uint32_t k = *dropped + 1;   // not ++: volatile, C++20
        *dropped = k;
        // diag_printf, not Serial_printf: this runs on Incunest_Task or on the library's acquisition
        // task (console tee), and neither may call sendto(). The recursion diag_printf → udp_enqueue
        // is one level deep by construction: the $ERR line is ~80 B and always fits the slot.
        if (k == 1 || k % 500 == 0)
            diag_printf("$ERR,%.2s,frame too long for UDP slot (%u bytes, slot %d), dropped x%lu\r\n",
                        buf + 1, (unsigned)len, UDP_QUEUE_FRAME_SIZE, (unsigned long)k);
        return;
    }
    char frame[UDP_QUEUE_FRAME_SIZE];
    memcpy(frame, buf, len + 1);
    xQueueSend(q, frame, 0);  // non-blocking: drop if full
}

// Measurement frames ($M1..$M4), from Incunest_Task.
static inline void udp_send(const char* buf) {
    udp_enqueue(g_udp_data_queue, buf, &incunest_frame_dropped);
}

// The library's diagnostic lines ($TIMING, $TASK, $TASKS_END — INCUNEST_TIMING_STATS) go to the
// console; this tee also puts them on the UDP stream, so the ESP32 TIMING window of
// pulsenest_lab.py works with no UART attached (fw 0.11, lib v0.92). Runs on the library's
// 500 Hz task: it only queues, and the lines already end in "*XX\r\n" like every frame. Their
// own queue since fw 0.12, so they never take a slot in a measurement datagram.
static void lib_console_sink(const char* line, size_t len) {
    (void)len;
    udp_enqueue(g_udp_diag_queue, line, &incunest_diag_dropped);
}

// A diagnostic line from a MEASUREMENT task: console + the diagnostic UDP queue, never
// udp_send_line(). Serial_printf() is the same thing with a synchronous sendto() at the end —
// fine for Cmd_Task and UDP_Task, and exactly what Incunest_Task and the library's acquisition
// task must not do (fw 0.13; the Arduino build once stalled the 500 Hz task for 100-500 ms on a
// blocking Serial.print(), same failure mode). No wait anywhere: the console mutex is tried with
// zero timeout and the UART ring is only written if the line fits — the UDP copy is the one that
// matters on the bench, and the queue drops rather than blocks.
static void diag_printf(const char* fmt, ...) {
    char buffer[UDP_QUEUE_FRAME_SIZE];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);
    if (g_serial_mutex == nullptr || xSemaphoreTake(g_serial_mutex, 0) == pdTRUE) {
        if (console_tx_free() >= (int)strlen(buffer)) console_write(buffer);
        if (g_serial_mutex) xSemaphoreGive(g_serial_mutex);
    }
    udp_enqueue(g_udp_diag_queue, buffer, &incunest_diag_dropped);
}

// ── UDP_Task: async batching sender ──────────────────────────────────────────
// Runs at priority 1 on core 1 (independent of Incunest_Task on core 0).
// Batches up to UDP_BATCH_SIZE frames into one datagram and calls sendto() via
// raw lwIP socket. Packet rate: 500 Hz / 5 = ~100 datagrams/sec — well below
// lwIP TX buffer limits. sendto() is non-blocking when socket TX buffer has space.
static void udp_sendto_batch(const char* batch, size_t len) {
    if (len > UDP_MTU)
        Serial_printf("# WARN UDP batch %u bytes > MTU %d — fragmentation risk\n",
                      (unsigned)len, UDP_MTU);
    if (sendto(g_udp_sock, batch, len, 0,
               reinterpret_cast<struct sockaddr*>(&g_udp_dest), sizeof(g_udp_dest)) < 0)
        Serial_printf("# ERR UDP sendto failed errno=%d\n", errno);
}

// Drain the diagnostic queue into datagrams of its own, at most UDP_BATCH_SIZE lines each.
// Called right after a data batch went out, so `batch` is free again: sendto() has copied it into
// lwIP's own buffer (pbuf) before returning. Also called when the data queue is idle, so a burst
// emitted with the stream stopped does not sit in the queue until the next frame.
static void udp_flush_diag(char* batch, size_t cap, char* frame) {
    size_t len = 0;
    int n = 0;
    while (xQueueReceive(g_udp_diag_queue, frame, 0) == pdTRUE) {
        const size_t flen = strlen(frame);
        if (len > 0 && (n == UDP_BATCH_SIZE || len + flen > cap)) {   // datagram full: send, start another
            udp_sendto_batch(batch, len);
            len = 0;
            n = 0;
        }
        memcpy(batch + len, frame, flen);
        len += flen;
        n++;
    }
    if (len > 0) udp_sendto_batch(batch, len);
}

static void UDP_Task(void *pvParameters) {
    (void)pvParameters;
    static char batch[UDP_QUEUE_FRAME_SIZE * UDP_BATCH_SIZE];
    char frame[UDP_QUEUE_FRAME_SIZE];
    for (;;) {
        // Block until at least one frame is available (or 100 ms timeout)
        if (xQueueReceive(g_udp_data_queue, frame, pdMS_TO_TICKS(100)) != pdTRUE) {
            if (g_wifi_ready && g_udp_sock >= 0) udp_flush_diag(batch, sizeof(batch), frame);
            continue;
        }
        if (!g_wifi_ready || g_udp_sock < 0) continue;

        // Start batch with first frame
        size_t batch_len = strlen(frame);
        memcpy(batch, frame, batch_len);

        // Accumulate up to UDP_BATCH_SIZE frames, waiting up to 12 ms per frame.
        // At 500 Hz (1 frame/2 ms), this fills the batch in ~10 ms → ~100 datagrams/s.
        // If a frame doesn't arrive within 12 ms, send the partial batch and continue — the only
        // way a measurement datagram carries fewer than UDP_BATCH_SIZE frames (host: `partial`).
        for (int i = 1; i < UDP_BATCH_SIZE; i++) {
            if (xQueueReceive(g_udp_data_queue, frame, pdMS_TO_TICKS(12)) != pdTRUE) break;
            size_t flen = strlen(frame);
            if (batch_len + flen > sizeof(batch)) break;
            memcpy(batch + batch_len, frame, flen);
            batch_len += flen;
        }
        udp_sendto_batch(batch, batch_len);

        // Diagnostics ride in a datagram of their own, right behind the measurements they came with.
        udp_flush_diag(batch, sizeof(batch), frame);
    }
}

// Send a single response frame immediately over UDP (no batching).
// Used for $CFG, $TCFG, $DIAG, $ERR, and # comment lines routed via Serial_printf /
// Serial_print_locked from Cmd_Task, UDP_Task and the OTA server — never from a measurement task
// (fw 0.13: those go through diag_printf() and the diagnostic queue). Serialised by
// g_resp_udp_mutex. The take used to have a 10 ms timeout whose result was ignored, so on expiry
// the line went out unprotected and the mutex was given without being held; with only
// non-critical callers left, waiting for it is the right thing. No-op if WiFi is not connected.
static void udp_send_line(const char* buf) {
    if (!g_wifi_ready) return;
    size_t len = strlen(buf);
    if (len == 0) return;
    if (g_udp_sock < 0) return;
    if (g_resp_udp_mutex) xSemaphoreTake(g_resp_udp_mutex, portMAX_DELAY);
    sendto(g_udp_sock, buf, len, 0, reinterpret_cast<struct sockaddr*>(&g_udp_dest), sizeof(g_udp_dest));
    if (g_resp_udp_mutex) xSemaphoreGive(g_resp_udp_mutex);
}

// ── WiFi station (esp_wifi) ─────────────────────────────────────────────────────────────────
// Replaces the Arduino WiFi object. app_main() keeps the same loop as before — try each network in
// WIFI_NETWORKS[] order, wait up to 10 s, report why it failed — driven by these helpers.
static EventGroupHandle_t g_wifi_events      = nullptr;
#define WIFI_EVT_CONNECTED    BIT0
#define WIFI_EVT_DISCONNECTED BIT1
static char               g_wifi_ip[16]      = "0.0.0.0";
static uint8_t            g_wifi_last_reason = 0;      // wifi_err_reason_t of the last disconnect

static void wifi_event_handler(void*, esp_event_base_t base, int32_t id, void* data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        g_wifi_last_reason = ((const wifi_event_sta_disconnected_t*)data)->reason;
        xEventGroupClearBits(g_wifi_events, WIFI_EVT_CONNECTED);
        xEventGroupSetBits(g_wifi_events, WIFI_EVT_DISCONNECTED);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t* e = (const ip_event_got_ip_t*)data;
        snprintf(g_wifi_ip, sizeof(g_wifi_ip), IPSTR, IP2STR(&e->ip_info.ip));
        xEventGroupClearBits(g_wifi_events, WIFI_EVT_DISCONNECTED);
        xEventGroupSetBits(g_wifi_events, WIFI_EVT_CONNECTED);
    }
}

static void wifi_sta_init(void) {
    g_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
}

static void wifi_sta_begin(const char* ssid, const char* password) {
    wifi_config_t cfg = {};
    strncpy((char*)cfg.sta.ssid, ssid, sizeof(cfg.sta.ssid) - 1);
    strncpy((char*)cfg.sta.password, password, sizeof(cfg.sta.password) - 1);
    cfg.sta.threshold.authmode = password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    xEventGroupClearBits(g_wifi_events, WIFI_EVT_CONNECTED | WIFI_EVT_DISCONNECTED);
    g_wifi_last_reason = 0;
    esp_wifi_disconnect();
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    esp_wifi_connect();
}

static inline bool wifi_sta_connected(void) {
    return (xEventGroupGetBits(g_wifi_events) & WIFI_EVT_CONNECTED) != 0;
}

// The Arduino build mapped wl_status_t to these labels; esp_wifi gives the 802.11 reason code.
static const char* wifi_sta_fail_reason(void) {
    switch (g_wifi_last_reason) {
        case WIFI_REASON_NO_AP_FOUND:              return "SSID_NOT_FOUND";
        case WIFI_REASON_AUTH_FAIL:
        case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
        case WIFI_REASON_HANDSHAKE_TIMEOUT:        return "WRONG_PASSWORD";
        case WIFI_REASON_BEACON_TIMEOUT:
        case WIFI_REASON_ASSOC_LEAVE:              return "CONNECTION_LOST";
        case WIFI_REASON_AUTH_EXPIRE:
        case WIFI_REASON_ASSOC_FAIL:
        case 0:                                    return "TIMEOUT";
        default:                                   return "UNKNOWN";
    }
}

// A non-blocking lwIP UDP socket bound to `port` (the command port), or -1.
static int udp_listen(uint16_t port) {
    int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s < 0) return -1;
    struct sockaddr_in a = {};
    a.sin_family      = AF_INET;
    a.sin_port        = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(s, reinterpret_cast<struct sockaddr*>(&a), sizeof(a)) < 0) { close(s); return -1; }
    fcntl(s, F_SETFL, fcntl(s, F_GETFL, 0) | O_NONBLOCK);
    return s;
}

// SPI bus for the AFE4490: SPI2, no DMA (4-byte frames travel in the transaction's own fields).
// The bus is the application's, as SPI.begin() was; the library adds its device on it (its HAL).
static void spi_bus_init(void) {
    spi_bus_config_t bus = {};
    bus.mosi_io_num     = SPI_MOSI_PIN;
    bus.miso_io_num     = SPI_MISO_PIN;
    bus.sclk_io_num     = SPI_SCK_PIN;
    bus.quadwp_io_num   = -1;
    bus.quadhd_io_num   = -1;
    bus.max_transfer_sz = 64;
    const esp_err_t err = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED);
    if (err != ESP_OK) Serial_printf("# SPI bus init FAILED: %s\n", esp_err_to_name(err));
}

// ── Incunest frame mode ────────────────────────────────────────────────────────────
// M1 = PPG only (minimal bandwidth)
// M2 = PPG + SpO2 + HR3 + quality flags (lightweight monitoring)
// M3 = full AFE4490Data — all production fields (default)
// M4 = M3 + AFE4490DebugData analog signals (V_TIA, I_PD for all 4 channels,
//      OT_LED1/OT_LED2, CH_MASKS validity masks — lib v0.35)
//      + RF1/RF2 (current RF per domain, string — lib v0.37, renamed from HGAC_RF1/RF2 in
//        v0.81: it's just the live config value, not something HGAC exclusively computes;
//        HGAC_ALARM removed v0.50)
enum class IncunestFrameMode { M1, M2, M3, M4 };
// Boot frame mode. $M4 since 2026-09-10 (decision by Alex), because $M3 was a default nobody
// wanted: the script needs $M4 for its algorithm replicas (HR1LAB reads OT_LED1, which only
// $M4 carries), so it used to persist a requested mode, re-assert it after every reset and run
// a 200 ms watchdog to keep it there. Booting in the mode the bench actually uses deletes all
// of that, and with it the risk of two host instances fighting over the mode.
// Cost, measured on 40 real frames: $M4 is 265 B against $M3's 140 B, so 1.07 vs 0.57 Mbit/s
// and 15 vs 8 ms of air per second per board at 72 Mbit/s. Note the margin in the 288 B queue
// slot is now 22 B from boot instead of 147 B (see the $M4 slot truncation task).
// This is PulseNest's own default, not the library's: motherBoard is unaffected.
volatile IncunestFrameMode g_incunest_frame_mode = IncunestFrameMode::M4;

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
            incunest_sample_count = incunest_sample_count + 1;   // not ++: volatile, C++20
#ifdef CHK_AMB_SUB
            chk_amb_sub(data);
#endif
            if (incunest_sample_count % SERIAL_DOWNSAMPLING_RATIO == 0) {  // send only 1 out of N samples to avoid saturating the serial port
                // Diagnostic: count frames where TX buffer has < 30 bytes free (nearly full —
                // next Serial.print will likely block or drop bytes).
                if (console_tx_free() < 30) incunest_tx_dropped = incunest_tx_dropped + 1;

                if (g_incunest_frame_mode == IncunestFrameMode::M1) {
                    // $M1,SmpCnt,Ts_us,PPG_DISP*XX  (PPG_DISP: OT domain [A/A] since v0.69, was ADC counts)
                    char buf[128];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M1,%lu,%lu,%.4e",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)esp_timer_get_time(),
                        data.ppg_disp);
                    if (frame_finish(buf, sizeof(buf), n, "M1")) {
                        if (!g_wifi_ready) Serial_print_locked(buf);
                        udp_send(buf);
                    }
                } else if (g_incunest_frame_mode == IncunestFrameMode::M2) {
                    // $M2,SmpCnt,Ts_us,PPG_DISP,SpO2,SpO2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState*XX
                    // (PPG_DISP: OT domain [A/A] since v0.69, was ADC counts)
                    char buf[192];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M2,%lu,%lu,%.4e,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)esp_timer_get_time(),
                        data.ppg_disp,
                        data.spo2_sqi > 0.0f ? data.spo2 : -1.0f,
                        data.spo2_sqi,
                        data.hr3_sqi > 0.0f ? data.hr3 : -1.0f,
                        data.hr3_sqi,
                        (unsigned)data.rsqi,
                        (unsigned long)data.diag_code,
                        (int)data.probe_state);
                    if (frame_finish(buf, sizeof(buf), n, "M2")) {
                        if (!g_wifi_ready) Serial_print_locked(buf);
                        udp_send(buf);
                    }
                } else if (g_incunest_frame_mode == IncunestFrameMode::M3) {
                    // $M3,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,
                    //     SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState*XX
                    // (PPG_DISP: OT domain [A/A] since v0.69, was ADC counts)
                    char buf[384];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M3,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%.4e,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)esp_timer_get_time(),
                        (long)data.led2,       (long)data.led1,
                        (long)data.aled2,      (long)data.aled1,
                        (long)data.led2_sub,   (long)data.led1_sub,
                        data.ppg_disp,
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
                    if (frame_finish(buf, sizeof(buf), n, "M3")) {
                        if (!g_wifi_ready) Serial_print_locked(buf);  // suppress serial data frames when UDP active — keeps serial free for $SET/$CFG control traffic
                        udp_send(buf);
                    }
                } else {  // M4
                    // $M4 = M3 + V_TIA_LED1/2/ALED1/2 + I_PD_LED1/2/ALED1/2 (scientific notation)
                    //     + OT_LED1/OT_LED2 [A/A] + CH_MASKS (validity masks, lib v0.35)
                    //     + RF1/RF2 (current RF per domain, string, lib v0.37; renamed from
                    //       HGAC_RF1/RF2 in v0.81 — it's the live config value regardless of
                    //       who set it, manual $SET or HGAC; HGAC_ALARM removed v0.50).
                    // CH_MASKS = 4 nibbles packed as %04X:
                    //   bits[3:0]=adc_sat_pos, [7:4]=adc_sat_neg, [11:8]=tia_over_fs, [15:12]=tia_over_lin
                    //   within each nibble, bit = channel per AFE4490Ch: LED1=0, ALED1=1, LED2=2, ALED2=3
                    const unsigned ch_masks =
                        (unsigned)dbg.analog.adc_sat_pos
                        | ((unsigned)dbg.analog.adc_sat_neg  << 4)
                        | ((unsigned)dbg.analog.tia_over_fs  << 8)
                        | ((unsigned)dbg.analog.tia_over_lin << 12);
                    // PPG_DISP: OT domain [A/A] since v0.69, was ADC counts.
                    char buf[512];
                    int n = snprintf(buf, sizeof(buf) - 6,
                        "$M4,%lu,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%.4e,%.2f,%.2f,%.5f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%u,%lu,%d"
                        ",%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%.4e,%04X"
                        ",%s,%s",
                        (unsigned long)incunest_sample_count,
                        (unsigned long)esp_timer_get_time(),
                        (long)data.led2,       (long)data.led1,
                        (long)data.aled2,      (long)data.aled1,
                        (long)data.led2_sub,   (long)data.led1_sub,
                        data.ppg_disp,
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
                        dbg.analog.i_pd_aled1,  dbg.analog.i_pd_aled2,
                        dbg.analog.ot_led1,     dbg.analog.ot_led2,
                        ch_masks,
                        afeRFToStr(dbg.rf_led1), afeRFToStr(dbg.rf_led2));
                    if (frame_finish(buf, sizeof(buf), n, "M4")) {
                        if (!g_wifi_ready) Serial_print_locked(buf);
                        udp_send(buf);
                    }
                }

                // Periodic TX health report (~every 10 s at 500 Hz)
                if (incunest_sample_count % 5000 == 0)
                    diag_printf("# STAT n=%lu tx_dropped=%lu frame_dropped=%lu diag_dropped=%lu\n",
                                (unsigned long)incunest_sample_count, (unsigned long)incunest_tx_dropped,
                                (unsigned long)incunest_frame_dropped, (unsigned long)incunest_diag_dropped);
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(1));  // no data yet: yield 1 ms to avoid busy-waiting. Only runs when getData() returns false.
        }
    }
}

void start_incunest() {
    // Hard reset via PWDN (afe does not manage this pin)
    {
        gpio_config_t io = {};
        io.pin_bit_mask = 1ULL << AFE4490_PWDN_PIN;
        io.mode         = GPIO_MODE_OUTPUT;
        gpio_config(&io);
    }
    gpio_set_level((gpio_num_t)AFE4490_PWDN_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_set_level((gpio_num_t)AFE4490_PWDN_PIN, 1);
    vTaskDelay(pdMS_TO_TICKS(100));

    incunest_sample_count = 0;
    incunest_afe4490_hal_console_set_sink(lib_console_sink);   // before begin(): see hal.h
    afe.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN, true);  // debug=true: combined queue items for atomic getData(data,dbg)
    afe.setPPGDispFilter(0.5f, 20.0f);
    // HGAC on from boot. Decision by Alex 2026-09-10: whether the gain control runs is the
    // board's business, not the host's. Until now the library booted it OFF and the script sent
    // $SET,hgac_enable,1 on every detected restart - a host writing to the board with no user
    // action, which is also what would make two host instances unsafe (one re-enabling HGAC
    // under a capture the other deliberately ran with it off, silently, since $CFG does not
    // carry hgac_enable).
    // Set HERE and not by changing the library default: `hgac_enable = false` in
    // incunest_afe4490.h is deliberate and shared with the IncuNest motherBoard, the clinical
    // firmware. Flipping it there would turn the loop on in an incubator as a side effect of a
    // bench convenience. PulseNest opts in for itself; the library default stays OFF.
    afe.setHgacEnable(true);
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
    // v0.69: OT domain — only LED1(IR)/LED2(RED) remain (see incunest_afe4490.h AFE4490Channel).
    switch (ch) {
        case AFE4490Channel::LED2: return "LED2";
        default:                    return "LED1";
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
    if (frame_finish(buf, sizeof(buf), n, "TCFG")) Serial_print_locked(buf);
}

// Emit a $CFG frame with the current AFE4490 configuration.
// Called from Cmd_Task (low priority) — safe to call Serial.print() here;
// the UART hardware buffer serialises writes from all tasks.
static void send_cfg_frame() {
    AFE4490Config cfg = afe.getConfig();
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    // Fingerprint of THIS image: the first 8 bytes of the ELF SHA-256 that ESP-IDF embeds in
    // every application (esp_app_desc_t), which nothing in this project read until now. 16 hex
    // characters tell any two builds apart and still read next to build=; `esptool image-info`
    // prints the full 32 bytes for comparing a board against a .bin on disk. Built by hand
    // rather than with snprintf("%02x"): the compiler cannot prove a 2-char bound for %x and
    // -Wformat-truncation is an error here.
    static const char kHex[] = "0123456789abcdef";
    const esp_app_desc_t* app_desc = esp_app_get_description();
    char elf_sha8[17];
    for (int i = 0; i < 8; ++i) {
        elf_sha8[i * 2]     = kHex[(app_desc->app_elf_sha256[i] >> 4) & 0x0F];
        elf_sha8[i * 2 + 1] = kHex[app_desc->app_elf_sha256[i] & 0x0F];
    }
    elf_sha8[16] = '\0';
    // 720: measured on the bench 2026-09-18, three boards, the real frame is 447-453 B (the
    // "~560" this comment used to claim was an overestimate); elfsha/idfver add 38, so 485-491
    // against the 714 snprintf may use — 223 B of margin. Sized with margin because a truncated
    // frame would still get a valid checksum appended below and reach the host as a well-formed
    // but incomplete $CFG.
    char buf[720];
    int n = snprintf(buf, sizeof(buf) - 6,
        "$CFG,sr=%u,numav=%u,led1=%.2f,led2=%.2f,range=%u"
        ",ensepgain=%d"
        ",tia1=%s,rf1_ohm=%.0f,cf1=%s,cf1_pF=%.0f,stg21=%s,rg1_ohm=%.0f,rg1_x=%.4f,stage2en1=%d"
        ",tia2=%s,rf2_ohm=%.0f,cf2=%s,cf2_pF=%.0f,stg22=%s,rg2_ohm=%.0f,rg2_x=%.4f,stage2en2=%d"
        ",ambdac=%u,ri_ohm=%.0f"
        ",ch=%s"
        ",fl=%.2f,fh=%.2f,hr2l=%.2f,hr2h=%.2f,hr3h=%.2f"
        ",spo2a=%.4f,spo2b=%.4f"
        ",board=%s,mac=%02X:%02X:%02X:%02X:%02X:%02X"
        // Provenance: which firmware produced this capture. Without it the FW_* columns of a
        // CSV become uninterpretable as soon as the algorithms change — see
        // captures/CAPTURE_SET_SPEC.md §2.3.
        ",fw=%s,lib=%s,build=%s,libsha=%s,elfsha=%s,idfver=%s",
        cfg.afe_sample_rate_hz, cfg.afe_adc_averages,
        cfg.afe_led1_current_mA, cfg.afe_led2_current_mA, (unsigned)cfg.afe_led_range_mA,
        cfg.afe_sep_tia_en ? 1 : 0,
        afeRFToStr(cfg.afe_tia_rf_led1), kAFE_RF_OHM[(int)cfg.afe_tia_rf_led1],
        afeCFToStr(cfg.afe_tia_cf_led1_code), cfg.afe_tia_cf_led1_pF,
        afeRGToStr(cfg.afe_stg2_rg_led1), kAFE_RG_OHM[(int)cfg.afe_stg2_rg_led1], kAFE_RG_GAIN[(int)cfg.afe_stg2_rg_led1],
        cfg.afe_stg2_en_led1 ? 1 : 0,
        afeRFToStr(cfg.afe_tia_rf_led2), kAFE_RF_OHM[(int)cfg.afe_tia_rf_led2],
        afeCFToStr(cfg.afe_tia_cf_led2_code), cfg.afe_tia_cf_led2_pF,
        afeRGToStr(cfg.afe_stg2_rg_led2), kAFE_RG_OHM[(int)cfg.afe_stg2_rg_led2], kAFE_RG_GAIN[(int)cfg.afe_stg2_rg_led2],
        cfg.afe_stg2_en_led2 ? 1 : 0,
        (unsigned)cfg.afe_ambdac_uA, kAFE_RI_OHM,
        channel_str(cfg.ppgdisp_channel),
        cfg.ppgdisp_f_low_hz, cfg.ppgdisp_f_high_hz,
        cfg.hr2_f_low_hz, cfg.hr2_f_high_hz, cfg.hr3_f_high_hz,
        cfg.spo2_a, cfg.spo2_b,
        BOARD_VERSION,
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5],
        // build = this project's commit, libsha = the library's, each covering only the paths
        // that reach this image (scripts/gen_build_version.py). They say WHICH COMMIT the image
        // was built from — what they cannot say is whether two images are the same, because
        // include/wifi_config.h is gitignored and build_Vxx/sdkconfig is not versioned: both
        // compile in and move no hash. elfsha is the image's own fingerprint and answers exactly
        // that, and idfver pins the toolchain, which nothing captured until now. Meaningful
        // because CONFIG_APP_REPRODUCIBLE_BUILD is on: otherwise the compile timestamp inside
        // the image would make elfsha differ for identical sources.
        PULSENEST_FW_VERSION, INCUNEST_AFE4490_VERSION,
        PULSENEST_GIT_HASH, INCUNEST_GIT_HASH,
        elf_sha8, app_desc->idf_ver);
    // Fail loudly rather than emit a truncated frame the host would accept as valid.
    if (!frame_finish(buf, sizeof(buf), n, "CFG")) return;
    Serial_print_locked(buf);
    send_tcfg_frame();  // always emit timing config alongside $CFG
}

// Emit a $LCFG frame with the current RSQM / HGAC algorithm library parameters.
static void send_lcfg_frame() {
    AFE4490Config cfg = afe.getConfig();
    char buf[320];
    int n = snprintf(buf, sizeof(buf) - 6,
        "$LCFG,rsqm_ot_thr=%.4e"
        ",rsqm_disconn_led_sub_thr=%.1f,rsqm_disconn_i_pd_thr=%.4e"
        ",rsqm_probe_state_min_s=%.3f"
        ",hgac_enable=%d,hgac_v_tia_high2=%.3f,hgac_v_tia_high1=%.3f,hgac_v_tia_low1=%.3f"
        ",hgac_ema_fast_tau_s=%.3f,hgac_ema_slow_tau_s=%.3f,hgac_ema_ambient_tau_s=%.3f",
        cfg.rsqm_ot_thr,
        cfg.rsqm_disconn_led_sub_thr, cfg.rsqm_disconn_i_pd_thr,
        cfg.rsqm_probe_state_min_s,
        cfg.hgac_enable ? 1 : 0, cfg.hgac_v_tia_high2, cfg.hgac_v_tia_high1, cfg.hgac_v_tia_low1,
        cfg.hgac_ema_fast_tau_s, cfg.hgac_ema_slow_tau_s, cfg.hgac_ema_ambient_tau_s);
    if (frame_finish(buf, sizeof(buf), n, "LCFG")) Serial_print_locked(buf);
}

// parse_tia_gain / parse_tia_cf / parse_stage2 — moved to incunest_afe4490.h as
// afeStrToRF / afeStrToCF / afeStrToRG (inline). Removed local copies.

// Warn (do not block) when a MANUAL CF override exceeds datasheet Equation 1
// (§8.3.1.1: RF × CF ≤ Rx Sample Time / 10). Auto-CF uses a stricter criterion and can never
// trip this; only a hand-picked $SET tiacf* can. The setting is still applied — this reports
// that the chip is being driven outside its documented range so it is visible in the lab log.
static void warn_if_cf_over_eq1() {
    AFE4490Config c = afe.getConfig();
    const float lim1 = afe.getCFMaxEq1PF(c.afe_tia_rf_led1);
    const float lim2 = afe.getCFMaxEq1PF(c.afe_tia_rf_led2);
    if (c.afe_tia_cf_led1_pF > lim1)
        Serial_printf("# WARN cf1=%.0f pF exceeds datasheet Eq.1 limit %.0f pF (RF=%s) - applied anyway\n",
                      c.afe_tia_cf_led1_pF, lim1, afeRFToStr(c.afe_tia_rf_led1));
    if (c.afe_tia_cf_led2_pF > lim2)
        Serial_printf("# WARN cf2=%.0f pF exceeds datasheet Eq.1 limit %.0f pF (RF=%s) - applied anyway\n",
                      c.afe_tia_cf_led2_pF, lim2, afeRFToStr(c.afe_tia_rf_led2));
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
        AFE4490CFCode cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACF(afeCFCodeToPF(cf));
            Serial_printf("# SET tiacf=%s (both channels)\n", val);
            warn_if_cf_over_eq1();
        } else {
            Serial_printf("$ERR,tiacf,invalid (5p..250p, 32 steps)\r\n");
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
        AFE4490CFCode cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACFLED1(afeCFCodeToPF(cf));
            Serial_printf("# SET tiacf1=%s (LED1/IR)\n", val);
            warn_if_cf_over_eq1();
        } else {
            Serial_printf("$ERR,tiacf1,invalid (5p..250p, 32 steps)\r\n");
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
        AFE4490CFCode cf;
        if (afeStrToCF(val, cf)) {
            afe.setTIACFLED2(afeCFCodeToPF(cf));
            Serial_printf("# SET tiacf2=%s (LED2/RED)\n", val);
            warn_if_cf_over_eq1();
        } else {
            Serial_printf("$ERR,tiacf2,invalid (5p..250p, 32 steps)\r\n");
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
    // ── RSQM / algorithm library parameters ──────────────────────────────────
    } else if (strcmp(key, "rsqm_ot_thr") == 0) {
        afe.setRsqmOtThr(atof(val));
        Serial_printf("# SET rsqm_ot_thr=%.4e\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "rsqm_disconn_led_sub_thr") == 0) {
        afe.setRsqmDisconnLedSubThr(atof(val));
        Serial_printf("# SET rsqm_disconn_led_sub_thr=%.1f\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "rsqm_disconn_i_pd_thr") == 0) {
        afe.setRsqmDisconnIPdThr(atof(val));
        Serial_printf("# SET rsqm_disconn_i_pd_thr=%.4e\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "rsqm_probe_state_min_s") == 0) {
        float s = atof(val);
        if (s > 0.0f && s <= 10.0f) {
            afe.setRsqmProbeStateMinS(s);
            Serial_printf("# SET rsqm_probe_state_min_s=%.3f\n", s);
            send_lcfg_frame();
        } else {
            Serial_printf("$ERR,rsqm_probe_state_min_s,invalid (0.0–10.0)\r\n");
        }
        return;
    // ── HGAC parameters (Phase 1: RF-only descent) ───────────────────────────
    } else if (strcmp(key, "hgac_enable") == 0) {
        int v = atoi(val);
        if (v == 0 || v == 1) {
            afe.setHgacEnable(v == 1);
            Serial_printf("# SET hgac_enable=%d\n", v);
            send_lcfg_frame();
        } else {
            Serial_printf("$ERR,hgac_enable,invalid (0 or 1)\r\n");
        }
        return;
    } else if (strcmp(key, "hgac_v_tia_high2") == 0) {
        afe.setHgacVTiaHigh2(atof(val));
        Serial_printf("# SET hgac_v_tia_high2=%.3f\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "hgac_v_tia_high1") == 0) {
        afe.setHgacVTiaHigh1(atof(val));
        Serial_printf("# SET hgac_v_tia_high1=%.3f\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "hgac_v_tia_low1") == 0) {
        afe.setHgacVTiaLow1(atof(val));
        Serial_printf("# SET hgac_v_tia_low1=%.3f\n", atof(val));
        send_lcfg_frame();
        return;
    } else if (strcmp(key, "hgac_ema_fast_tau_s") == 0) {
        float s = atof(val);
        if (s > 0.0f && s <= 10.0f) {
            afe.setHgacEmaFastTauS(s);
            Serial_printf("# SET hgac_ema_fast_tau_s=%.3f\n", s);
            send_lcfg_frame();
        } else {
            Serial_printf("$ERR,hgac_ema_fast_tau_s,invalid (0.0–10.0)\r\n");
        }
        return;
    } else if (strcmp(key, "hgac_ema_slow_tau_s") == 0) {
        float s = atof(val);
        if (s > 0.0f && s <= 30.0f) {
            afe.setHgacEmaSlowTauS(s);
            Serial_printf("# SET hgac_ema_slow_tau_s=%.3f\n", s);
            send_lcfg_frame();
        } else {
            Serial_printf("$ERR,hgac_ema_slow_tau_s,invalid (0.0–30.0)\r\n");
        }
        return;
    } else if (strcmp(key, "hgac_ema_ambient_tau_s") == 0) {
        float s = atof(val);
        if (s > 0.0f && s <= 30.0f) {
            afe.setHgacEmaAmbientTauS(s);
            Serial_printf("# SET hgac_ema_ambient_tau_s=%.3f\n", s);
            send_lcfg_frame();
        } else {
            Serial_printf("$ERR,hgac_ema_ambient_tau_s,invalid (0.0–30.0)\r\n");
        }
        return;
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
    "<p>Select the <b>.bin</b> firmware file and click Flash."
    " (Command line: <code>curl --data-binary @firmware.bin http://&lt;ip&gt;/update</code>)</p>"
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
    "x.send(this.update.files[0]);};"          // the image as the raw body — no multipart to parse
    "</script></body></html>";

static esp_err_t ota_get_handler(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html");
    httpd_resp_set_hdr(req, "Connection", "close");
    return httpd_resp_send(req, g_ota_html, HTTPD_RESP_USE_STRLEN);
}

// POST /update — the firmware image is the raw request body, written straight into the next OTA
// slot. Under Arduino this ran inside Cmd_Task (WebServer::handleClient()); here it runs in
// esp_http_server's own task. Both write flash while the 500 Hz task runs, and the DRDY ISR is not
// IRAM-safe in either build, so samples are lost during the flash — unchanged behaviour.
static esp_err_t ota_post_handler(httpd_req_t* req) {
    static char chunk[4096];
    const esp_partition_t* part = esp_ota_get_next_update_partition(NULL);
    esp_ota_handle_t ota = 0;
    int  remaining = req->content_len;
    bool ok = part != NULL && remaining > 0;
    Serial_printf("# OTA start: %d bytes -> %s\n", remaining, part ? part->label : "?");
    if (ok) ok = esp_ota_begin(part, OTA_SIZE_UNKNOWN, &ota) == ESP_OK;
    while (ok && remaining > 0) {
        const int want = remaining < (int)sizeof(chunk) ? remaining : (int)sizeof(chunk);
        const int n = httpd_req_recv(req, chunk, want);
        if (n == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (n <= 0 || esp_ota_write(ota, chunk, n) != ESP_OK) { ok = false; break; }
        remaining -= n;
    }
    if (ok) ok = esp_ota_end(ota) == ESP_OK && esp_ota_set_boot_partition(part) == ESP_OK;
    else if (ota) esp_ota_abort(ota);
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Connection", "close");
    httpd_resp_sendstr(req, ok ? "OK" : "FAIL");
    if (ok) {
        Serial_printf("# OTA success: %d bytes — rebooting\n", req->content_len);
        vTaskDelay(pdMS_TO_TICKS(300));
        esp_restart();
    }
    Serial_printf("# OTA FAILED\n");
    return ESP_OK;
}

static void ota_server_init() {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port      = 80;
    cfg.lru_purge_enable = true;
    if (httpd_start(&g_ota_server, &cfg) != ESP_OK) {
        Serial_printf("# OTA server FAILED to start\n");
        return;
    }
    static const httpd_uri_t root   = { "/",       HTTP_GET,  ota_get_handler,  NULL };
    static const httpd_uri_t update = { "/update", HTTP_POST, ota_post_handler, NULL };
    httpd_register_uri_handler(g_ota_server, &root);
    httpd_register_uri_handler(g_ota_server, &update);
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
    } else if (strcmp(cmd_buf, "$LCFG?") == 0) {
        send_lcfg_frame();
    } else if (strcmp(cmd_buf, "$DIAG?") == 0) {
        uint32_t diag_val = afe.runAfeDiagnostics();
        char buf[32];
        int n = snprintf(buf, sizeof(buf) - 6, "$DIAG,%06lX",
                         (unsigned long)diag_val);
        if (frame_finish(buf, sizeof(buf), n, "DIAG")) Serial_print_locked(buf);
    } else if (strcmp(cmd_buf, "$RESET") == 0) {
        Serial_printf("# Resetting...\n");
        vTaskDelay(pdMS_TO_TICKS(50));
        esp_restart();
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
//   '$CFG?\n'     → emit $CFG frame with current AFE4490 hardware configuration
//   '$LCFG?\n'    → emit $LCFG frame with current RSQM / algorithm library parameters
//   '$SET,k,v*XX' → set hardware or library parameter k to value v (XOR checksum verified)
//   '$DIAG?\n'    → run AFE4490 diagnostics, emit $DIAG,XXXXXX*YY frame
//   '$RESET\n'    → soft-reset via esp_restart() (works over Serial and UDP)
// Serial: multi-byte commands are accumulated until '\n'.
// UDP: each datagram contains one complete command line (no accumulation needed).
// OTA: served by esp_http_server's own task (ota_server_init) — nothing to poll here.
void Cmd_Task(void *pvParameters) {
    char cmd_buf[64];
    int  cmd_len = 0;
    for (;;) {
        // ── Serial path (always active) ───────────────────────────────────────
        uint8_t rx;
        while (uart_read_bytes(CONSOLE_UART, &rx, 1, 0) == 1) {
            char c = (char)rx;
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
            char udp_cmd[64];
            int  n;
            while (g_cmd_sock >= 0 &&
                   (n = recvfrom(g_cmd_sock, udp_cmd, sizeof(udp_cmd) - 1, MSG_DONTWAIT, NULL, NULL)) > 0) {
                // Strip trailing \r\n so process_command sees a clean string.
                while (n > 0 && (udp_cmd[n - 1] == '\r' || udp_cmd[n - 1] == '\n')) n--;
                if (n > 0) {
                    udp_cmd[n] = '\0';
                    process_command(udp_cmd, n);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── setup / loop ──────────────────────────────────────────────────────────────
// Human-readable reset reason — key diagnostic for sporadic resets on $SET commands.
// PANIC = code crash (race/null ptr), TASK_WDT/INT_WDT = deadlock or long block,
// BROWNOUT = supply dip (LED/AMBDAC changes alter current draw).
static const char* reset_reason_str(esp_reset_reason_t r) {
    switch (r) {
        case ESP_RST_POWERON:   return "POWERON";
        case ESP_RST_EXT:       return "EXT_PIN";
        case ESP_RST_SW:        return "SW_RESET";
        case ESP_RST_PANIC:     return "PANIC (exception/abort)";
        case ESP_RST_INT_WDT:   return "INT_WDT (interrupt watchdog)";
        case ESP_RST_TASK_WDT:  return "TASK_WDT (task watchdog)";
        case ESP_RST_WDT:       return "WDT (other watchdog)";
        case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
        case ESP_RST_BROWNOUT:  return "BROWNOUT (supply dip)";
        case ESP_RST_SDIO:      return "SDIO";
        default:                return "UNKNOWN";
    }
}

extern "C" void app_main(void) {
    g_serial_mutex    = xSemaphoreCreateMutex();  // protects concurrent Serial writes from multiple tasks
    g_resp_udp_mutex  = xSemaphoreCreateMutex();  // protects g_resp_udp (used by Incunest_Task + Cmd_Task)
    g_udp_data_queue  = xQueueCreate(UDP_QUEUE_DEPTH, UDP_QUEUE_FRAME_SIZE);
    g_udp_diag_queue  = xQueueCreate(UDP_DIAG_QUEUE_DEPTH, UDP_QUEUE_FRAME_SIZE);
    // UART0 console with a 1024 B TX ring (see console_init) and NVS for the WiFi driver.
    console_init();
    nvs_init();
    // UART0 has nothing to enumerate; this delay only gives an already-attached monitor time to
    // catch the banner.
    vTaskDelay(pdMS_TO_TICKS(500));

    // Startup banner. No __DATE__/__TIME__: measured 2026-09-18, two builds of identical sources
    // differed in exactly 68 bytes and this string was the only cause — the other 65 are the
    // consequences (the app descriptor's ELF SHA-256 and the image checksum at the end).
    // CONFIG_APP_REPRODUCIBLE_BUILD removes ESP-IDF's own timestamp; this one was ours, and it
    // alone made every rebuild a different binary, which is what elfsha= exists to detect.
    // Nothing is lost: build/libsha say which commit, elfsha= which image, idfver= which toolchain.
    printf("# PulseNest v" PULSENEST_FW_VERSION "+sha." PULSENEST_GIT_HASH
                  " | incunest_afe4490 v" INCUNEST_AFE4490_VERSION
                  "+sha." INCUNEST_GIT_HASH
                  " | Board: %s — Medical Open World\n", BOARD_VERSION);

    // System info — shown in pulsenest_lab log on startup/reset (prefix "# SYS:")
    {
        esp_chip_info_t chip;
        esp_chip_info(&chip);
        uint8_t mac[6];
        esp_read_mac(mac, ESP_MAC_WIFI_STA);
        printf("# SYS: ESP32-S3 rev.%d, %d cores @ %d MHz\n",
            (int)chip.revision, chip.cores, CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ);
        printf("# SYS: Flash %lu MB | PSRAM %lu MB (free %lu KB)\n",
            (unsigned long)(sys_flash_size() / (1024UL * 1024)),
            (unsigned long)(heap_caps_get_total_size(MALLOC_CAP_SPIRAM) / (1024UL * 1024)),
            (unsigned long)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)  / 1024UL));
        printf("# SYS: Heap free %lu KB | IDF %s\n",
            (unsigned long)(esp_get_free_heap_size() / 1024UL),
            esp_get_idf_version());
        printf("# SYS: MAC %02X:%02X:%02X:%02X:%02X:%02X\n",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        printf("# SYS: Reset reason: %s\n",
            reset_reason_str(esp_reset_reason()));
    }

    // WiFi + UDP init (STA mode — tries each network in WIFI_NETWORKS[] order, always from index 0)
    wifi_sta_init();
    // Disable WiFi modem sleep. The Arduino core defaults a station to WIFI_PS_MIN_MODEM, which
    // lets the radio sleep between the access point's DTIM beacons. Whether that costs anything
    // depends entirely on whether the board is streaming, and both regimes were measured on
    // 2026-09-10 with tools/udp_cmd_latency.py ($CFG? round trip, i.e. the downlink path):
    //
    //   Streaming 100 datagrams/s (normal operation): modem sleep costs nothing measurable.
    //     16.A p50 19 ms without this call, 16-22 ms with it. A board transmitting every 10 ms
    //     is almost never actually asleep, and the floor is Cmd_Task's 50 ms poll.
    //
    //   Idle radio (built with -DPULSENEST_NO_DATA_STREAM, same board, same session):
    //     modem sleep ON  -> p50 259 ms, mean 233, mass at 200-280 ms (the AP's DTIM cycle)
    //     modem sleep OFF -> p50  55 ms, mean  38, nothing above 63 ms
    //     A 4.7x median penalty. THIS is what the call buys, and it matters for any board
    //     whose stream is off - which is exactly motherBoard's case once the PulseNest stream
    //     becomes activable on demand (it already disables modem sleep, Wifi_OTA.cpp).
    //
    //   Methodological warning. 17.A first measured 44-47 ms across three streaming runs and
    //   dropped to 15 ms right after being flashed with this call. That looked like proof and
    //   was not: flashing also reboots and re-associates. Reflashed WITHOUT the call it still
    //   measured 21 ms, so the 45 ms had been a degraded association - that board had been up
    //   for hours and had re-associated by itself after dropping off the hotspot. A long-lived
    //   station can carry ~2.5x the command latency, and a reboot cures it.
    //
    // Second reason, not proven: motherBoard's comment says mobile hotspots drop power-saving
    // clients, and 17.A dropped off the Windows hotspot twice on 2026-09-09 while still
    // powered. This removes that variable; judging it needs a long session.
    // Set after mode() so it applies to every WiFi.begin() attempt in the retry loop below.
    // esp_wifi_set_ps() directly (the Arduino build reached it through WiFi.setSleep()).
    esp_wifi_set_ps(WIFI_PS_NONE);
    {
        for (int i = 0; i < WIFI_NETWORK_COUNT && !g_wifi_ready; i++) {
            printf("# WiFi trying [%d/%d] %s", i + 1, WIFI_NETWORK_COUNT,
                          WIFI_NETWORKS[i].ssid);
            wifi_sta_begin(WIFI_NETWORKS[i].ssid, WIFI_NETWORKS[i].password);
            for (int j = 0; j < 20 && !wifi_sta_connected(); j++) {
                vTaskDelay(pdMS_TO_TICKS(500));
                printf(".");
            }
            if (wifi_sta_connected()) {
                g_udp_target_ip = WIFI_NETWORKS[i].udp_target_ip;
                // Raw socket for data frames (hot path — no endPacket() overhead)
                g_udp_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
                if (g_udp_sock >= 0) {
                    memset(&g_udp_dest, 0, sizeof(g_udp_dest));
                    g_udp_dest.sin_family = AF_INET;
                    g_udp_dest.sin_port   = htons(UDP_TARGET_PORT);
                    inet_aton(g_udp_target_ip, &g_udp_dest.sin_addr);
                } else {
                    printf("# UDP socket FAILED errno=%d\n", errno);
                }
                g_wifi_ready    = true;
                g_cmd_sock = udp_listen(UDP_CMD_PORT);  // command frames PC→ESP32
                if (g_cmd_sock < 0) Serial_printf("# CMD UDP socket FAILED errno=%d\n", errno);
                ota_server_init();
                printf("\n# WiFi connected [%s] — IP %s  UDP \u2192 %s:%d\n",
                              WIFI_NETWORKS[i].ssid, g_wifi_ip,
                              g_udp_target_ip, UDP_TARGET_PORT);
                printf("# OTA: http://%s/\n", g_wifi_ip);
                printf("# CMD UDP: listening on port %d\n", UDP_CMD_PORT);
                // Relay reset reason over UDP so it reaches the host cable-free.
                {
                    char rr_buf[64];
                    snprintf(rr_buf, sizeof(rr_buf), "# RESET_REASON: %s\n",
                             reset_reason_str(esp_reset_reason()));
                    udp_send_line(rr_buf);
                }
            } else {
                const char* reason = wifi_sta_fail_reason();
                printf("\n# WiFi FAILED %s — %s\n",
                              WIFI_NETWORKS[i].ssid, reason);
                esp_wifi_disconnect();
            }
        }
    }
    if (!g_wifi_ready) {
        printf("# WiFi FAILED all networks — UART only\n");
    }

    spi_bus_init();
                                // CS=-1: managed per device via AFE4490_CS_PIN.
                                // Called here and not inside the library: SPI is a shared bus —
                                // multiple devices can coexist via beginTransaction()/endTransaction().
                                // Calling SPI.begin() inside a library would risk reinitialising the
                                // bus and breaking other devices sharing it.

    // CMD stack 8192: $SET → apply_set_cmd → send_cfg_frame (buf[600]) + send_tcfg_frame
    // (buf[512]) + vsnprintf float formatting + lwIP/WiFiUDP + OTA handleClient all run on
    // this stack. 4096 overflowed sporadically (stack canary PANIC, ~1 in 3-4 $SET commands).
    xTaskCreatePinnedToCore(Cmd_Task,  "CMD",      8192, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(UDP_Task,  "UDP_DATA", 4096, NULL, 1, NULL, 1);  // core 1: independent of Incunest_Task (core 0); WiFi calls are thread-safe across cores

    start_incunest();
}

