#pragma once

// mow_afe4490 — Medical Open World AFE4490 driver + PPG algorithms (HR, SpO2)
// v0.6 — ESP32-S3, Arduino + FreeRTOS
// Spec: mow_afe4490_spec.md

#include <Arduino.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <freertos/queue.h>
#include <stdint.h>

// ── Compile-time configuration (override before including this header) ────────
#ifndef MOW_AFE4490_QUEUE_SIZE
#define MOW_AFE4490_QUEUE_SIZE      10
#endif

#ifndef MOW_AFE4490_TASK_PRIORITY
#define MOW_AFE4490_TASK_PRIORITY   5
#endif

#ifndef MOW_AFE4490_TASK_STACK
#define MOW_AFE4490_TASK_STACK      4096
#endif

// ── Public data struct ────────────────────────────────────────────────────────
struct AFE4490Data {
    // Processed outputs
    int32_t ppg;        // filtered PPG of selected channel
    float   spo2;       // SpO2 in %
    uint8_t hr;         // heart rate in bpm
    bool    spo2_valid; // SpO2 is reliable
    bool    hr_valid;   // HR is reliable
    // Raw ADC outputs (6 signals from AFE4490)
    int32_t led1;       // LED1VAL  — IR raw
    int32_t led2;       // LED2VAL  — RED raw
    int32_t aled1;      // ALED1VAL — ambient after LED1
    int32_t aled2;      // ALED2VAL — ambient after LED2
    int32_t led1_aled1; // LED1-ALED1 — IR ambient-corrected
    int32_t led2_aled2; // LED2-ALED2 — RED ambient-corrected
};

// ── Enumerations ──────────────────────────────────────────────────────────────
enum class AFE4490Channel {
    LED1,       // IR raw
    LED2,       // RED raw
    ALED1,      // ambient after LED1
    ALED2,      // ambient after LED2
    LED1_ALED1, // IR ambient-corrected (default)
    LED2_ALED2  // RED ambient-corrected
};

enum class AFE4490Filter {
    NONE,
    MOVING_AVERAGE,
    BUTTERWORTH  // default: 0.5–20 Hz Butterworth bandpass
};

enum class AFE4490TIAGain {
    RF_10K,
    RF_25K,
    RF_50K,
    RF_100K,
    RF_250K,
    RF_500K,  // default
    RF_1M
};

enum class AFE4490TIACF {
    CF_5P,    // 5 pF (default)
    CF_10P,
    CF_20P,
    CF_30P,
    CF_55P,
    CF_155P
};

enum class AFE4490Stage2Gain {
    GAIN_0DB,    // Stage 2 disabled (default)
    GAIN_3_5DB,
    GAIN_6DB,
    GAIN_9_5DB,
    GAIN_12DB
};

// ── MOW_AFE4490 class ─────────────────────────────────────────────────────────
class MOW_AFE4490 {
public:
    MOW_AFE4490();
    ~MOW_AFE4490();

    // Initialization — configures chip with defaults, attaches DRDY ISR, starts task
    void begin(int pin_cs, int pin_drdy);

    // Chip configuration setters (callable before or after begin())
    void setSampleRate(uint16_t hz);        // 63–5000 Hz; recalculates NUMAV_max
    void setNumAverages(uint8_t num);       // 1=no averaging; clamped to floor(5000/PRF)
    void setLED1Current(float mA);
    void setLED2Current(float mA);
    void setLEDRange(uint8_t mA);           // 75 or 150 mA
    void setTIAGain(AFE4490TIAGain gain);
    void setTIACF(AFE4490TIACF cf);
    void setStage2Gain(AFE4490Stage2Gain gain);

    // Signal and filter configuration
    void setPPGChannel(AFE4490Channel channel);
    void setFilter(AFE4490Filter type, float f_low_hz = 0.5f, float f_high_hz = 20.0f);

    // Data retrieval — non-blocking; returns true if data was available
    bool getData(AFE4490Data& data);

    // Shutdown — detaches ISR, deletes internal task and FreeRTOS objects, resets state.
    // After stop(), begin() can be called again to restart.
    void stop();

    // SpO2 calibration coefficients (SpO2 = a - b*R)
    void setSpO2Coefficients(float a, float b);

    // ISR entry point (must be public for static trampoline)
    void _drdy_isr();

private:
    // SPI primitives
    void     _write_reg(uint8_t addr, uint32_t data);
    uint32_t _read_spi_raw(uint8_t addr);   // assumes SPI_READ already enabled
    uint32_t _read_reg(uint8_t addr);       // handles SPI_READ enable/disable

    // Sign-extend 22-bit two's complement ADC output
    static int32_t _sign_extend_22(uint32_t raw);

    // Recomputes rate-dependent algorithm parameters from _sample_rate_hz
    void _recalc_rate_params();
    // Recomputes Butterworth bandpass biquad coefficients from _sample_rate_hz, _filter_f_low, _filter_f_high
    void _recalc_biquad();

    // Chip init
    void _chip_init();
    void _apply_timing_regs();
    void _apply_analog_regs();
    void _apply_control_regs();
    uint32_t _build_tiagain();

    // FreeRTOS task
    static void _task_trampoline(void* pv);
    void _task_body();

    // Signal processing
    struct BiquadState { float v1, v2; };
    float _biquad_step(float x, BiquadState& st);
    void  _process_sample(int32_t led1, int32_t led2, int32_t aled1, int32_t aled2,
                          int32_t led1_aled1, int32_t led2_aled2);

    // Algorithms
    void _update_spo2(int32_t ir_corr, int32_t red_corr);
    void _update_hr(float ppg_filtered);
    void _reset_algorithms();

    // ── Hardware ──
    int _pin_cs;
    int _pin_drdy;

    // ── FreeRTOS ──
    SemaphoreHandle_t _drdy_sem;
    SemaphoreHandle_t _cfg_mutex;
    QueueHandle_t     _data_queue;
    TaskHandle_t      _task_handle;
    bool              _initialized;

    // ── Chip configuration ──
    uint16_t          _sample_rate_hz;
    uint8_t           _num_averages;     // user-visible count (1 = no averaging)
    float             _led1_current_mA;
    float             _led2_current_mA;
    uint8_t           _led_range_mA;     // 75 or 150
    AFE4490TIAGain    _tia_gain;
    AFE4490TIACF      _tia_cf;
    AFE4490Stage2Gain _stage2_gain;

    // ── Signal processing configuration ──
    AFE4490Channel    _ppg_channel;
    AFE4490Filter     _filter_type;
    float             _filter_f_low;
    float             _filter_f_high;

    // ── Biquad coefficients (computed dynamically by _recalc_biquad) ──
    float _bq_b0, _bq_b1, _bq_b2, _bq_a1, _bq_a2;

    // ── Biquad state (one per signal path) ──
    BiquadState _bq_ppg;

    // ── Moving average state ──
    static constexpr int ma_len = 8;
    float    _ma_buf[ma_len];
    int      _ma_idx;
    float    _ma_sum;

    // ── Rate-dependent algorithm parameters (derived from _sample_rate_hz) ──
    uint32_t          _spo2_warmup_samples;
    uint32_t          _hr_refractory_samples;
    float             _dc_iir_alpha;
    float             _ac_ema_beta;

    // ── SpO2 state ──
    float    _dc_ir;
    float    _dc_red;
    float    _ac2_ir;
    float    _ac2_red;
    uint32_t _spo2_sample_count;
    float    _spo2_a;
    float    _spo2_b;

    // ── HR state ──
    float    _hr_running_max;
    bool     _hr_above_thresh;
    uint32_t _hr_last_peak_idx;
    uint32_t _hr_sample_idx;
    int32_t  _hr_intervals[5];
    uint8_t  _hr_interval_count;

    // ── Output snapshot (written by task, pushed to queue) ──
    AFE4490Data _current_data;

    // ── Static ISR trampoline ──
    static MOW_AFE4490* _g_instance;
    static void IRAM_ATTR _drdy_isr_static();
};
