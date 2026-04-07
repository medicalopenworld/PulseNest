#pragma once

// mow_afe4490 — Medical Open World AFE4490 driver + PPG algorithms (HR, SpO2)
// v0.7 — ESP32-S3, Arduino + FreeRTOS
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
    int32_t ppg;         // filtered PPG of selected channel
    float   spo2;        // SpO2 in %
    float   spo2_r;      // R ratio used for SpO2 calculation: (AC_red/DC_red)/(AC_ir/DC_ir)
    bool    spo2_valid;  // SpO2 is reliable
    float   hr1;         // HR1 (peak detection) in bpm
    bool    hr1_valid;   // HR1 is reliable
    float   hr2;         // HR2 (autocorrelation) in bpm
    bool    hr2_valid;   // HR2 is reliable
    // Raw ADC outputs (6 signals from AFE4490)
    int32_t led1;        // LED1VAL  — IR raw
    int32_t led2;        // LED2VAL  — RED raw
    int32_t aled1;       // ALED1VAL — ambient after LED1
    int32_t aled2;       // ALED2VAL — ambient after LED2
    int32_t led1_aled1;  // LED1-ALED1 — IR ambient-corrected
    int32_t led2_aled2;  // LED2-ALED2 — RED ambient-corrected
    // ── Diagnostic (temporary — may be removed in final release) ──
    float hr1_ppg;       // HR1 internal signal (DC-removed + MA); set to 0.0 on detected peak
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

    // Initialization — configures chip with defaults, attaches DRDY ISR, starts task.
    // Requires SPI.begin() to have been called beforehand by the application.
    // This library does not call SPI.begin() internally to avoid interfering with
    // other SPI devices sharing the same bus.
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

    // HR2 bandpass filter cutoffs (default 0.5–5 Hz); callable before or after begin()
    void setHR2Filter(float f_low_hz = 0.5f, float f_high_hz = 5.0f);

    // Data retrieval — non-blocking; returns true if data was available
    bool getData(AFE4490Data& data);

    // Shutdown — detaches ISR, deletes internal task and FreeRTOS objects, resets state.
    // After stop(), begin() can be called again to restart.
    void stop();

    // SpO2 calibration coefficients (SpO2 = a - b*R).
    // Defaults are experimentally calibrated for UpnMed U401-D(01AS-F), Nellcor Non-Oximax type.
    void setSpO2Coefficients(float a, float b);

    // ISR entry point (must be public for static trampoline)
    void _drdy_isr();

private:
    // ── Private types ─────────────────────────────────────────────────────────

    struct BiquadState { float v1, v2; };

    // BiquadFilter groups coefficients, state and cutoff frequencies for one filter instance.
    // _recalc_biquad() writes b0/b1/b2/a1/a2 from f_low/f_high and _sample_rate_hz.
    // _biquad_step() and _biquad_precharge() operate on state in-place.
    struct BiquadFilter {
        float f_low, f_high;          // cutoff frequencies (Hz) — parameterisable at runtime
        float b0, b1, b2, a1, a2;    // DF-II transposed coefficients
        BiquadState state;
        bool  needs_precharge;        // true after reset; consumed on first sample
    };

    // ── SPI primitives ────────────────────────────────────────────────────────
    void     _write_reg(uint8_t addr, uint32_t data);
    uint32_t _read_spi_raw(uint8_t addr);   // assumes SPI_READ already enabled
    uint32_t _read_reg(uint8_t addr);       // handles SPI_READ enable/disable

    // Sign-extend 22-bit two's complement ADC output
    static int32_t _sign_extend_22(uint32_t raw);

    // Recomputes rate-dependent algorithm parameters from _sample_rate_hz
    void _recalc_rate_params();
    // Recomputes Butterworth bandpass biquad coefficients into filt from _sample_rate_hz and filt.f_low/f_high
    void _recalc_biquad(BiquadFilter& filt);

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
    float _biquad_process(float x, BiquadFilter& filt);  // precharge on first call, then step
    void  _process_sample(int32_t led1, int32_t led2, int32_t aled1, int32_t aled2,
                          int32_t led1_aled1, int32_t led2_aled2);

    // Algorithms
    void _update_spo2(int32_t ir_corr, int32_t red_corr);
    void _update_hr1(int32_t led1_aled1);
    void _update_hr2(int32_t led1_aled1);
    void _reset_algorithms();

    // ── Hardware ──
    int _pin_cs;
    int _pin_drdy;

    // ── FreeRTOS ──
    SemaphoreHandle_t _drdy_sem;
    SemaphoreHandle_t _spi_mutex;    // protects SPI bus access (_write_reg / _read_spi_raw)
    SemaphoreHandle_t _state_mutex;  // protects internal processing state (_ppg_channel, filter
                                     // buffers, SpO2/HR accumulators) shared between _process_sample()
                                     // and the config setters that do not access the SPI bus
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

    // ── PPG display filter (Butterworth bandpass or MA, configurable via setFilter()) ──
    BiquadFilter      _ppg_bpf;          // default: 0.5–20 Hz

    // ── Moving average state (PPG display filter — used when _filter_type == MOVING_AVERAGE) ──
    static constexpr int ma_len = 8;
    float    _ma_buf[ma_len];
    int      _ma_idx;
    float    _ma_sum;

    // ── HR1 moving average state (independent of PPG display filter) ──
    static constexpr int hr1_ma_max_len = 64;  // supports up to 640 Hz @ 5 Hz cutoff
    float    _hr1_ma_buf[hr1_ma_max_len];
    uint32_t _hr1_ma_len;   // computed from sample_rate in _recalc_rate_params()
    int      _hr1_ma_idx;
    float    _hr1_ma_sum;

    // ── Rate-dependent algorithm parameters (derived from _sample_rate_hz) ──
    uint32_t          _spo2_warmup_samples;
    uint32_t          _hr1_refractory_samples;
    float             _dc_iir_alpha;
    float             _ac_ema_beta;
    float             _hr1_dc_alpha;

    // ── SpO2 state ──
    float    _dc_ir;
    float    _dc_red;
    float    _ac2_ir;
    float    _ac2_red;
    uint32_t _spo2_sample_count;
    float    _spo2_a;
    float    _spo2_b;

    // ── HR1 state ──
    float    _hr1_dc;
    uint32_t _hr1_peak_marker_countdown;
    float    _hr1_running_max;
    bool     _hr1_ppg_above_thresh;
    uint32_t _hr1_last_peak_idx;
    uint32_t _hr1_sample_idx;
    int32_t  _hr1_intervals[5];
    uint8_t  _hr1_interval_count;

    // ── HR2 — autocorrelation-based HR algorithm ──────────────────────────────
    // Bandpass-filters led1_aled1 (0.5–5 Hz), decimates by hr2_decim_factor,
    // accumulates a circular buffer of hr2_buf_len samples, then periodically
    // computes normalised autocorrelation to find the fundamental RR period.
    static constexpr int hr2_buf_len         = 400;  // 8 s at 50 Hz (fs/hr2_decim_factor)
    static constexpr int hr2_acorr_max_lag   = 100;  // 30 BPM at 50 Hz: 50*60/30 = 100 samples
    static constexpr int hr2_decim_factor    = 10;   // 500 Hz → 50 Hz
    static constexpr int hr2_update_interval = 25;   // recompute every 0.5 s (25 decimated samples)

    BiquadFilter _hr2_bpf;                   // bandpass filter (default 0.5–5 Hz)
    float    _hr2_buf[hr2_buf_len];          // circular buffer of decimated filtered samples
    float    _hr2_seg[hr2_buf_len];          // linearized copy for autocorrelation (avoids stack pressure)
    int      _hr2_buf_idx;                   // next write position in _hr2_buf
    uint32_t _hr2_buf_count;                 // samples written (capped at hr2_buf_len)
    uint32_t _hr2_decim_counter;             // decimation phase counter
    uint32_t _hr2_update_counter;            // decimated samples since last autocorr computation

    // ── Output snapshot (written by task, pushed to queue) ──
    AFE4490Data _current_data;

    // ── Static ISR trampoline ──
    // _g_instance holds a pointer to the single active MOW_AFE4490 object so that
    // _drdy_isr_static (a plain C-compatible function required by attachInterrupt)
    // can forward the interrupt to the correct instance.
    //
    // LIMITATION: only one MOW_AFE4490 instance is supported at a time. A second
    // instance would overwrite _g_instance and its DRDY interrupts would be routed
    // to the wrong object. To support two AFE4490 chips, either:
    //   - add a second static ISR + pointer pair, or
    //   - switch to ESP-IDF gpio_isr_handler_add(), which passes a void* argument
    //     per handler, eliminating the need for a singleton pointer altogether.
    static MOW_AFE4490* _g_instance;
    static void IRAM_ATTR _drdy_isr_static();

#ifdef UNIT_TEST
public:
    // Expose internals for unit testing only — not part of the public API

    // Biquad filter
    using TestBiquadFilter = BiquadFilter;
    void  test_recalc_biquad(BiquadFilter& f)           { _recalc_biquad(f); }
    float test_biquad_process(float x, BiquadFilter& f) { return _biquad_process(x, f); }

    // HR1
    void  test_feed_hr1(int32_t led1_aled1) { _update_hr1(led1_aled1); }
    float test_hr1()                        { return _current_data.hr1; }
    bool  test_hr1_valid()                  { return _current_data.hr1_valid; }

    // HR2
    void  test_feed_hr2(int32_t led1_aled1) { _update_hr2(led1_aled1); }
    float test_hr2()                        { return _current_data.hr2; }
    bool  test_hr2_valid()                  { return _current_data.hr2_valid; }

    // SpO2
    void  test_feed_spo2(int32_t ir_corr, int32_t red_corr) { _update_spo2(ir_corr, red_corr); }
    float test_spo2()                       { return _current_data.spo2; }
    float test_spo2_r()                     { return _current_data.spo2_r; }
    bool  test_spo2_valid()                 { return _current_data.spo2_valid; }
#endif
};
