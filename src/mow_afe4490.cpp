// mow_afe4490.cpp — Medical Open World AFE4490 driver + PPG algorithms (HR, SpO2)
// v0.6 — ESP32-S3, Arduino + FreeRTOS
// Spec: mow_afe4490_spec.md

#include "mow_afe4490.h"
#include "esp_log.h"
#include <math.h>
#include <string.h>

static const char* TAG = "mow_afe4490";

namespace {
    // ── Algorithm time constants (physical units) ────────────────────────────
    constexpr float    spo2_warmup_s       = 5.0f;    // s  — warmup before reporting SpO2
    constexpr float    dc_iir_tau_s        = 1.6f;    // s  — DC IIR time constant
    constexpr float    ac_ema_tau_s        = 1.0f;    // s  — AC² EMA time constant
    constexpr float    hr_refractory_s     = 0.300f;  // s  — HR refractory period (~200 bpm max)

    // ── PPG filter ────────────────────────────────────────────────────────────
    constexpr float    ppg_f_low_hz        = 0.5f;    // Hz — default lower cutoff frequency
    constexpr float    ppg_f_high_hz       = 20.0f;   // Hz — default upper cutoff frequency
    constexpr float    pi                  = 3.14159265358979f;

    // ── SpO2 ──────────────────────────────────────────────────────────────────
    constexpr float    spo2_a_default      = 104.0f;  // calibration coefficient
    constexpr float    spo2_b_default      =  17.0f;  // calibration coefficient
    constexpr float    spo2_min            =  70.0f;  // % — valid lower bound
    constexpr float    spo2_max            = 100.0f;  // % — valid upper bound
    constexpr float    spo2_min_dc         = 1000.0f; // ADC counts — no-finger threshold

    // ── HR ────────────────────────────────────────────────────────────────────
    constexpr float    hr_min_bpm          =  40.0f;  // bpm
    constexpr float    hr_max_bpm          = 240.0f;  // bpm

    // ── AFE4490 register addresses ────────────────────────────────────────────
    constexpr uint8_t REG_CONTROL0      = 0x00;
    constexpr uint8_t REG_LED2STC       = 0x01;
    constexpr uint8_t REG_LED2ENDC      = 0x02;
    constexpr uint8_t REG_LED2LEDSTC    = 0x03;
    constexpr uint8_t REG_LED2LEDENDC   = 0x04;
    constexpr uint8_t REG_ALED2STC      = 0x05;
    constexpr uint8_t REG_ALED2ENDC     = 0x06;
    constexpr uint8_t REG_LED1STC       = 0x07;
    constexpr uint8_t REG_LED1ENDC      = 0x08;
    constexpr uint8_t REG_LED1LEDSTC    = 0x09;
    constexpr uint8_t REG_LED1LEDENDC   = 0x0A;
    constexpr uint8_t REG_ALED1STC      = 0x0B;
    constexpr uint8_t REG_ALED1ENDC     = 0x0C;
    constexpr uint8_t REG_LED2CONVST    = 0x0D;
    constexpr uint8_t REG_LED2CONVEND   = 0x0E;
    constexpr uint8_t REG_ALED2CONVST   = 0x0F;
    constexpr uint8_t REG_ALED2CONVEND  = 0x10;
    constexpr uint8_t REG_LED1CONVST    = 0x11;
    constexpr uint8_t REG_LED1CONVEND   = 0x12;
    constexpr uint8_t REG_ALED1CONVST   = 0x13;
    constexpr uint8_t REG_ALED1CONVEND  = 0x14;
    constexpr uint8_t REG_ADCRSTSTCT0   = 0x15;
    constexpr uint8_t REG_ADCRSTENDCT0  = 0x16;
    constexpr uint8_t REG_ADCRSTSTCT1   = 0x17;
    constexpr uint8_t REG_ADCRSTENDCT1  = 0x18;
    constexpr uint8_t REG_ADCRSTSTCT2   = 0x19;
    constexpr uint8_t REG_ADCRSTENDCT2  = 0x1A;
    constexpr uint8_t REG_ADCRSTSTCT3   = 0x1B;
    constexpr uint8_t REG_ADCRSTENDCT3  = 0x1C;
    constexpr uint8_t REG_PRPCOUNT      = 0x1D;
    constexpr uint8_t REG_CONTROL1      = 0x1E;
    constexpr uint8_t REG_TIAGAIN       = 0x20;
    constexpr uint8_t REG_TIA_AMB_GAIN  = 0x21;
    constexpr uint8_t REG_LEDCNTRL      = 0x22;
    constexpr uint8_t REG_CONTROL2      = 0x23;
    constexpr uint8_t REG_ALARM         = 0x29;
    constexpr uint8_t REG_LED2VAL       = 0x2A;
    constexpr uint8_t REG_ALED2VAL      = 0x2B;
    constexpr uint8_t REG_LED1VAL       = 0x2C;
    constexpr uint8_t REG_ALED1VAL      = 0x2D;
    constexpr uint8_t REG_LED2_ALED2VAL = 0x2E;
    constexpr uint8_t REG_LED1_ALED1VAL = 0x2F;
    constexpr uint8_t REG_DIAG          = 0x30;

    // CONTROL0 bits
    constexpr uint32_t ctrl0_spi_read   = 0x000001UL;
    constexpr uint32_t ctrl0_sw_rst     = 0x000008UL;

    // CONTROL1 bits
    constexpr uint32_t ctrl1_timeren    = 0x000100UL;

    // TIAGAIN / TIA_AMB_GAIN: RF bits [2:0]
    // enum order: RF_10K=0..RF_1M=6 → register codes
    constexpr uint32_t rf_code[7] = { 5, 4, 3, 2, 1, 0, 6 };

    // TIAGAIN / TIA_AMB_GAIN: CF bits [7:3] (5 pF base + parallel caps)
    // enum order: CF_5P=0..CF_155P=5 → register bits
    constexpr uint32_t cf_code[6] = { 0x000, 0x008, 0x010, 0x020, 0x040, 0x080 };

    // TIAGAIN: STG2GAIN bits [10:8] + STAGE2EN bit[14]
    // enum order: GAIN_0DB=0..GAIN_12DB=4 → register bits (0 = disabled, rest = enabled)
    constexpr uint32_t stg2_code[5] = {
        0x000000UL,                   // GAIN_0DB: stage 2 disabled
        0x000100UL | 0x004000UL,      // GAIN_3_5DB: STG2=1 + EN
        0x000200UL | 0x004000UL,      // GAIN_6DB
        0x000300UL | 0x004000UL,      // GAIN_9_5DB
        0x000400UL | 0x004000UL       // GAIN_12DB
    };
}

// ── Static member ─────────────────────────────────────────────────────────────
// Singleton pointer used by the static ISR trampoline (_drdy_isr_static) to reach
// the class instance. Static members must be defined exactly once in a .cpp file;
// the declaration in the header only reserves the name.
MOW_AFE4490* MOW_AFE4490::_g_instance = nullptr;

// ── Constructor / destructor ──────────────────────────────────────────────────
MOW_AFE4490::MOW_AFE4490()
    : _pin_cs(-1), _pin_drdy(-1),
      _drdy_sem(nullptr), _spi_mutex(nullptr), _state_mutex(nullptr),
      _data_queue(nullptr), _task_handle(nullptr),
      _initialized(false),
      _sample_rate_hz(500), _num_averages(8),
      _led1_current_mA(11.7f), _led2_current_mA(11.7f), _led_range_mA(150),
      _tia_gain(AFE4490TIAGain::RF_500K),
      _tia_cf(AFE4490TIACF::CF_5P),
      _stage2_gain(AFE4490Stage2Gain::GAIN_0DB),
      _ppg_channel(AFE4490Channel::LED1_ALED1),
      _filter_type(AFE4490Filter::BUTTERWORTH),
      _filter_f_low(ppg_f_low_hz), _filter_f_high(ppg_f_high_hz),
      _bq_b0(0.0f), _bq_b1(0.0f), _bq_b2(0.0f), _bq_a1(0.0f), _bq_a2(0.0f),
      _bq_ppg({0.0f, 0.0f}), _bq_ppg_needs_precharge(true),
      _ma_idx(0), _ma_sum(0.0f),
      _spo2_warmup_samples(0), _hr1_refractory_samples(0),
      _dc_iir_alpha(0.0f), _ac_ema_beta(0.0f),
      _dc_ir(0.0f), _dc_red(0.0f),
      _ac2_ir(0.0f), _ac2_red(0.0f),
      _spo2_sample_count(0),
      _spo2_a(spo2_a_default), _spo2_b(spo2_b_default),
      _hr1_running_max(0.0f), _hr1_ppg_above_thresh(false),
      _hr1_last_peak_idx(0), _hr1_sample_idx(0),
      _hr1_interval_count(0)
{
    memset(_ma_buf, 0, sizeof(_ma_buf));
    memset(_hr1_intervals, 0, sizeof(_hr1_intervals));
    _current_data = {0, 0.0f, 0, false, false, 0, 0, 0, 0, 0, 0};
    _recalc_rate_params();
}

MOW_AFE4490::~MOW_AFE4490() {
    if (_task_handle) {
        vTaskDelete(_task_handle);
        _task_handle = nullptr;
    }
    if (_data_queue)   vQueueDelete(_data_queue);
    if (_drdy_sem)     vSemaphoreDelete(_drdy_sem);
    if (_spi_mutex)    vSemaphoreDelete(_spi_mutex);
    if (_state_mutex)  vSemaphoreDelete(_state_mutex);
    if (_g_instance == this) _g_instance = nullptr;
}

// ── begin() ───────────────────────────────────────────────────────────────────
// Requires SPI.begin() to have been called beforehand. This library intentionally
// does not call SPI.begin() to avoid reinitialising the bus and interfering with
// other SPI devices. Only SPI.beginTransaction() / endTransaction() are used here.
void MOW_AFE4490::begin(int pin_cs, int pin_drdy) {
    _pin_cs   = pin_cs;
    _pin_drdy = pin_drdy;
    _g_instance = this;

    pinMode(_pin_cs, OUTPUT);
    digitalWrite(_pin_cs, HIGH);

    _drdy_sem    = xSemaphoreCreateBinary();
    _spi_mutex   = xSemaphoreCreateMutex();
    _state_mutex = xSemaphoreCreateMutex();
    _data_queue  = xQueueCreate(MOW_AFE4490_QUEUE_SIZE, sizeof(AFE4490Data));

    if (!_drdy_sem || !_spi_mutex || !_state_mutex || !_data_queue) {
        ESP_LOGE(TAG, "FreeRTOS object creation failed");
        return;
    }

    xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _chip_init();
    xSemaphoreGive(_spi_mutex);

    _initialized = true;

    pinMode(_pin_drdy, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(_pin_drdy), _drdy_isr_static, RISING);

    xTaskCreatePinnedToCore(
        _task_trampoline, "mow_afe4490",
        MOW_AFE4490_TASK_STACK, this,
        MOW_AFE4490_TASK_PRIORITY, &_task_handle, 1);

    ESP_LOGI(TAG, "Started: PRF=%u Hz, NUMAV=%u", _sample_rate_hz, _num_averages);
}

// ── Configuration setters ─────────────────────────────────────────────────────
void MOW_AFE4490::setSampleRate(uint16_t hz) {
    if (hz < 63 || hz > 5000) {
        ESP_LOGE(TAG, "setSampleRate: %u Hz out of range [63, 5000]", hz);
        return;
    }

    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);

    _sample_rate_hz = hz;

    // Recalculate NUMAV_max = floor(5000 / PRF) - 1, HW limit = 15
    uint8_t numav_max = (uint8_t)((5000u / hz) - 1u);
    if (numav_max > 15) numav_max = 15;

    if ((_num_averages - 1u) > numav_max) {
        uint8_t clamped = numav_max + 1u;
        ESP_LOGE(TAG, "setSampleRate: num_averages clamped %u→%u at %u Hz",
                 _num_averages, clamped, hz);
        _num_averages = clamped;
    }

    _recalc_rate_params();

    if (_initialized) {
        _apply_timing_regs();
        _apply_control_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setNumAverages(uint8_t num) {
    if (num == 0) num = 1;

    uint8_t numav_max = (uint8_t)((5000u / _sample_rate_hz) - 1u);
    if (numav_max > 15) numav_max = 15;

    if ((uint8_t)(num - 1u) > numav_max) {
        uint8_t clamped = numav_max + 1u;
        ESP_LOGE(TAG, "setNumAverages: %u clamped to %u (max at %u Hz)",
                 num, clamped, _sample_rate_hz);
        num = clamped;
    }

    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _num_averages = num;
    if (_initialized) {
        _apply_control_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setLED1Current(float mA) {
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _led1_current_mA = constrain(mA, 0.0f, (float)_led_range_mA);
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setLED2Current(float mA) {
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _led2_current_mA = constrain(mA, 0.0f, (float)_led_range_mA);
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setLEDRange(uint8_t mA) {
    if (mA != 75 && mA != 150) {
        ESP_LOGE(TAG, "setLEDRange: must be 75 or 150 mA");
        return;
    }
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _led_range_mA = mA;
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setTIAGain(AFE4490TIAGain gain) {
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _tia_gain = gain;
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setTIACF(AFE4490TIACF cf) {
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _tia_cf = cf;
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setStage2Gain(AFE4490Stage2Gain gain) {
    if (_initialized) xSemaphoreTake(_spi_mutex, portMAX_DELAY);
    _stage2_gain = gain;
    if (_initialized) {
        _apply_analog_regs();
        xSemaphoreGive(_spi_mutex);
    }
}

void MOW_AFE4490::setPPGChannel(AFE4490Channel channel) {
    if (_initialized) xSemaphoreTake(_state_mutex, portMAX_DELAY);
    _ppg_channel = channel;
    // Reset filter state: changing channel means a different signal enters the filter
    _bq_ppg = {0.0f, 0.0f};
    _bq_ppg_needs_precharge = true;
    memset(_ma_buf, 0, sizeof(_ma_buf));
    _ma_idx = 0;
    _ma_sum = 0.0f;
    if (_initialized) xSemaphoreGive(_state_mutex);
}

void MOW_AFE4490::setFilter(AFE4490Filter type, float f_low_hz, float f_high_hz) {
    if (_initialized) xSemaphoreTake(_state_mutex, portMAX_DELAY);
    _filter_type   = type;
    _filter_f_low  = f_low_hz;
    _filter_f_high = f_high_hz;
    if (type == AFE4490Filter::BUTTERWORTH) _recalc_biquad();
    // Reset filter state
    _bq_ppg = {0.0f, 0.0f};
    _bq_ppg_needs_precharge = true;
    memset(_ma_buf, 0, sizeof(_ma_buf));
    _ma_idx = 0;
    _ma_sum = 0.0f;
    if (_initialized) xSemaphoreGive(_state_mutex);
}

void MOW_AFE4490::setSpO2Coefficients(float a, float b) {
    if (_initialized) xSemaphoreTake(_state_mutex, portMAX_DELAY);
    _spo2_a = a;
    _spo2_b = b;
    if (_initialized) xSemaphoreGive(_state_mutex);
}

// ── getData() ─────────────────────────────────────────────────────────────────
bool MOW_AFE4490::getData(AFE4490Data& data) {
    return xQueueReceive(_data_queue, &data, 0) == pdTRUE;
}

// ── stop() ────────────────────────────────────────────────────────────────────
void MOW_AFE4490::stop() {
    if (!_initialized) return;

    detachInterrupt(digitalPinToInterrupt(_pin_drdy));

    // Take mutex to wait for any in-progress SPI transaction to finish
    if (_spi_mutex) xSemaphoreTake(_spi_mutex, portMAX_DELAY);

    if (_task_handle) {
        vTaskDelete(_task_handle);
        _task_handle = nullptr;
    }

    // Delete FreeRTOS objects (mutex last since we hold it)
    if (_data_queue)  { vQueueDelete(_data_queue);       _data_queue  = nullptr; }
    if (_drdy_sem)    { vSemaphoreDelete(_drdy_sem);     _drdy_sem    = nullptr; }
    if (_spi_mutex)   { vSemaphoreDelete(_spi_mutex);    _spi_mutex   = nullptr; }
    if (_state_mutex) { vSemaphoreDelete(_state_mutex);  _state_mutex = nullptr; }

    _initialized = false;
    _reset_algorithms();

    ESP_LOGI(TAG, "Stopped");
}

// ── _reset_algorithms() ───────────────────────────────────────────────────────
void MOW_AFE4490::_reset_algorithms() {
    _dc_ir  = 0.0f; _dc_red  = 0.0f;
    _ac2_ir = 0.0f; _ac2_red = 0.0f;
    _spo2_sample_count = 0;
    _hr1_running_max    = 0.0f;
    _hr1_ppg_above_thresh   = false;
    _hr1_last_peak_idx  = 0;
    _hr1_sample_idx     = 0;
    _hr1_interval_count = 0;
    memset(_hr1_intervals, 0, sizeof(_hr1_intervals));
    _bq_ppg = {0.0f, 0.0f};
    memset(_ma_buf, 0, sizeof(_ma_buf));
    _ma_idx = 0; _ma_sum = 0.0f;
    _current_data = {0, 0.0f, 0, false, false, 0, 0, 0, 0, 0, 0};
}

// ── SPI primitives ────────────────────────────────────────────────────────────
void MOW_AFE4490::_write_reg(uint8_t addr, uint32_t data) {
    SPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
    digitalWrite(_pin_cs, LOW);
    SPI.transfer(addr);
    SPI.transfer((data >> 16) & 0xFF);
    SPI.transfer((data >>  8) & 0xFF);
    SPI.transfer( data        & 0xFF);
    digitalWrite(_pin_cs, HIGH);
    SPI.endTransaction();
}

// Raw read — caller must have enabled SPI_READ in CONTROL0 beforehand
uint32_t MOW_AFE4490::_read_spi_raw(uint8_t addr) {
    SPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
    digitalWrite(_pin_cs, LOW);
    SPI.transfer(addr);
    uint32_t data = ((uint32_t)SPI.transfer(0x00) << 16) |
                    ((uint32_t)SPI.transfer(0x00) <<  8) |
                     (uint32_t)SPI.transfer(0x00);
    digitalWrite(_pin_cs, HIGH);
    SPI.endTransaction();
    return data;
}

uint32_t MOW_AFE4490::_read_reg(uint8_t addr) {
    _write_reg(REG_CONTROL0, ctrl0_spi_read);
    uint32_t val = _read_spi_raw(addr);
    _write_reg(REG_CONTROL0, 0x000000UL);
    return val;
}

int32_t MOW_AFE4490::_sign_extend_22(uint32_t raw) {
    // AFE4490 ADC output is 22-bit two's complement in bits [21:0]
    return ((int32_t)(raw << 10)) >> 10;
}

// ── Chip init ─────────────────────────────────────────────────────────────────
void MOW_AFE4490::_chip_init() {
    // Step 2: Set SPI write mode
    _write_reg(REG_CONTROL0, 0x000000UL);

    // Step 3: Software reset
    _write_reg(REG_CONTROL0, ctrl0_sw_rst);
    vTaskDelay(pdMS_TO_TICKS(10));

    // Step 4: Analog front-end
    _apply_analog_regs();

    // Step 5: Timing registers
    _apply_timing_regs();

    // Step 6: CONTROL1 (enables timer — must be last)
    _apply_control_regs();

    // Step 7: Stabilization
    vTaskDelay(pdMS_TO_TICKS(1000));
}

void MOW_AFE4490::_apply_timing_regs() {
    // Datasheet Table 2 formulas, PRF = _sample_rate_hz
    // AFECLK = 4 MHz → 1 count = 0.25 µs
    const uint32_t afeclk      = 4000000UL;
    const uint32_t tia_margin  = 50;   // counts (12.5 µs)
    const uint32_t adc_reset   = 3;    // counts (0.75 µs → -60 dB crosstalk)

    uint32_t phase = afeclk / _sample_rate_hz;
    uint32_t prp   = phase - 1;
    uint32_t q     = phase / 4;        // quarter period

    // LED drive windows (25% duty cycle)
    _write_reg(REG_LED2LEDSTC,   3*q);          // t3
    _write_reg(REG_LED2LEDENDC,  prp);           // t4
    _write_reg(REG_LED2STC,      3*q + tia_margin); // t1
    _write_reg(REG_LED2ENDC,     prp - 1);       // t2
    _write_reg(REG_ALED2STC,     tia_margin);    // t5
    _write_reg(REG_ALED2ENDC,    q - 2);         // t6
    _write_reg(REG_LED1LEDSTC,   q);             // t9
    _write_reg(REG_LED1LEDENDC,  2*q - 1);       // t10
    _write_reg(REG_LED1STC,      q + tia_margin); // t7
    _write_reg(REG_LED1ENDC,     2*q - 2);       // t8
    _write_reg(REG_ALED1STC,     2*q + tia_margin); // t11
    _write_reg(REG_ALED1ENDC,    3*q - 2);       // t12

    // ADC reset pulses (3 counts at each phase boundary)
    _write_reg(REG_ADCRSTSTCT0,  0);             // t21
    _write_reg(REG_ADCRSTENDCT0, adc_reset);     // t22
    _write_reg(REG_ADCRSTSTCT1,  q);             // t23
    _write_reg(REG_ADCRSTENDCT1, q  + adc_reset); // t24
    _write_reg(REG_ADCRSTSTCT2,  2*q);           // t25
    _write_reg(REG_ADCRSTENDCT2, 2*q + adc_reset); // t26
    _write_reg(REG_ADCRSTSTCT3,  3*q);           // t27
    _write_reg(REG_ADCRSTENDCT3, 3*q + adc_reset); // t28

    // ADC conversion windows (CONVST = adc_reset_end + 1, CONVEND = next_reset_start - 1)
    _write_reg(REG_LED2CONVST,   adc_reset + 1);            // t13
    _write_reg(REG_LED2CONVEND,  q - 1);                    // t14
    _write_reg(REG_ALED2CONVST,  q  + adc_reset + 1);       // t15
    _write_reg(REG_ALED2CONVEND, 2*q - 1);                  // t16
    _write_reg(REG_LED1CONVST,   2*q + adc_reset + 1);      // t17
    _write_reg(REG_LED1CONVEND,  3*q - 1);                  // t18
    _write_reg(REG_ALED1CONVST,  3*q + adc_reset + 1);      // t19
    _write_reg(REG_ALED1CONVEND, prp);                      // t20

    _write_reg(REG_PRPCOUNT,     prp);                      // t29
}

uint32_t MOW_AFE4490::_build_tiagain() {
    uint32_t reg = rf_code[(int)_tia_gain];       // bits [2:0]
    reg         |= cf_code[(int)_tia_cf];         // bits [7:3]
    reg         |= stg2_code[(int)_stage2_gain];  // bits [10:8] + bit[14]
    return reg;
}

void MOW_AFE4490::_apply_analog_regs() {
    uint32_t tia = _build_tiagain();

    // TIAGAIN and TIA_AMB_GAIN get the same RF/CF/Stage2 bits.
    // ENSEPGAIN=0 (bit 15 of TIAGAIN): both channels share TIAGAIN → TIA_AMB_GAIN RF irrelevant.
    // FLTRCNRSEL=0 (500 Hz, bit 15 of TIA_AMB_GAIN), AMBDAC=0.
    _write_reg(REG_TIAGAIN,      tia);
    _write_reg(REG_TIA_AMB_GAIN, tia);

    // LEDCNTRL: LED_RANGE | (code_led1 << 8) | code_led2
    // I (mA) = (code / 256) * full_scale_mA
    float fs = (float)_led_range_mA;
    uint8_t code1 = (uint8_t)constrain(roundf((_led1_current_mA / fs) * 256.0f), 0.0f, 255.0f);
    uint8_t code2 = (uint8_t)constrain(roundf((_led2_current_mA / fs) * 256.0f), 0.0f, 255.0f);
    uint32_t range_bit = (_led_range_mA == 75) ? 0x010000UL : 0x000000UL;
    _write_reg(REG_LEDCNTRL, range_bit | ((uint32_t)code1 << 8) | code2);

    // CONTROL2: TX_REF=0x00 (0.75 V), all subsystems powered on, H-bridge, crystal enabled
    _write_reg(REG_CONTROL2, 0x000000UL);
}

void MOW_AFE4490::_apply_control_regs() {
    // CONTROL1: TIMEREN | NUMAV
    uint8_t numav = (_num_averages > 0) ? (_num_averages - 1u) : 0u;
    _write_reg(REG_CONTROL1, ctrl1_timeren | numav);
}

void MOW_AFE4490::_recalc_rate_params() {
    float fs              = (float)_sample_rate_hz;
    _spo2_warmup_samples   = (uint32_t)(spo2_warmup_s   * fs);
    _hr1_refractory_samples = (uint32_t)(hr_refractory_s * fs);
    _dc_iir_alpha          = expf(-1.0f / (dc_iir_tau_s * fs));
    _ac_ema_beta           = 1.0f - expf(-1.0f / (ac_ema_tau_s * fs));
    _recalc_biquad();
}

void MOW_AFE4490::_recalc_biquad() {
    // 2nd-order Butterworth bandpass via bilinear transform.
    // Analog prototype: H(s) = BW·s / (s² + BW·s + Ω₀²)
    float fs    = (float)_sample_rate_hz;
    float k     = 2.0f * fs;
    float o_low = k * tanf(pi * _filter_f_low  / fs);
    float o_hi  = k * tanf(pi * _filter_f_high / fs);
    float o0sq  = o_low * o_hi;
    float bw    = o_hi - o_low;
    float d     = k*k + bw*k + o0sq;
    _bq_b0 =  bw * k / d;
    _bq_b1 =  0.0f;
    _bq_b2 = -bw * k / d;
    _bq_a1 =  2.0f * (o0sq - k*k) / d;
    _bq_a2 =  (k*k - bw*k + o0sq) / d;
}

// ── FreeRTOS task ─────────────────────────────────────────────────────────────
// FreeRTOS requires the task entry point to be a plain C function (static or free function).
// _task_trampoline satisfies that requirement: it receives the MOW_AFE4490 instance pointer
// via the pvParameters argument and immediately forwards execution to _task_body(), which is
// the actual member function with full access to private state. This pattern (trampoline +
// member body) is the standard idiom for running a C++ method as a FreeRTOS task.
void MOW_AFE4490::_task_trampoline(void* pv) {
    static_cast<MOW_AFE4490*>(pv)->_task_body();
    vTaskDelete(nullptr); // should never reach here
}

void MOW_AFE4490::_task_body() {
    for (;;) {
        // Block until DRDY fires (100 ms watchdog — warns if chip stops outputting)
        if (xSemaphoreTake(_drdy_sem, pdMS_TO_TICKS(100)) != pdTRUE) {
            ESP_LOGW(TAG, "DRDY timeout: no sample in 100 ms");
            continue;
        }

        // _spi_mutex: protects the SPI bus while reading all 6 channels.
        xSemaphoreTake(_spi_mutex, portMAX_DELAY);
        // Enable SPI read mode once, burst-read all 6 channels, disable
        _write_reg(REG_CONTROL0, ctrl0_spi_read);
        int32_t led2      = _sign_extend_22(_read_spi_raw(REG_LED2VAL));
        int32_t aled2     = _sign_extend_22(_read_spi_raw(REG_ALED2VAL));
        int32_t led1      = _sign_extend_22(_read_spi_raw(REG_LED1VAL));
        int32_t aled1     = _sign_extend_22(_read_spi_raw(REG_ALED1VAL));
        int32_t led2_diff = _sign_extend_22(_read_spi_raw(REG_LED2_ALED2VAL));
        int32_t led1_diff = _sign_extend_22(_read_spi_raw(REG_LED1_ALED1VAL));
        _write_reg(REG_CONTROL0, 0x000000UL);
        xSemaphoreGive(_spi_mutex);

        // _state_mutex: protects internal processing state (_ppg_channel, filter
        // buffers, SpO2/HR accumulators) against concurrent config setter calls.
        xSemaphoreTake(_state_mutex, portMAX_DELAY);
        _process_sample(led1, led2, aled1, aled2, led1_diff, led2_diff);
        xSemaphoreGive(_state_mutex);
    }
}

// ── ISR ───────────────────────────────────────────────────────────────────────
// Trampoline required because attachInterrupt() only accepts a plain C function pointer;
// C++ member functions are not compatible. _drdy_isr_static is registered with
// attachInterrupt() and forwards the call to the actual member ISR (_drdy_isr) via
// the singleton pointer _g_instance. The null-check guards against a spurious interrupt
// arriving after stop() has cleared _g_instance.
void IRAM_ATTR MOW_AFE4490::_drdy_isr_static() {
    if (_g_instance) _g_instance->_drdy_isr();
}

void IRAM_ATTR MOW_AFE4490::_drdy_isr() {
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(_drdy_sem, &woken);
    portYIELD_FROM_ISR(woken);
}

// ── Signal processing ─────────────────────────────────────────────────────────

// Direct Form II Transposed biquad
float MOW_AFE4490::_biquad_step(float x, BiquadState& st) {
    float y  = _bq_b0 * x + st.v1;
    st.v1    = _bq_b1 * x - _bq_a1 * y + st.v2;
    st.v2    = _bq_b2 * x - _bq_a2 * y;
    return y;
}

// Pre-charge biquad state to steady-state for a DC input x0, so that the first
// output sample is ~0 instead of a large transient. Derivation for DF-II transposed:
//   y_ss  = x0 * (b0+b1+b2) / (1+a1+a2)   (= 0 for this bandpass filter)
//   v1_ss = y_ss - b0*x0
//   v2_ss = b2*x0 - a2*y_ss
void MOW_AFE4490::_biquad_precharge(float x0, BiquadState& st) {
    float y_ss = x0 * (_bq_b0 + _bq_b1 + _bq_b2) / (1.0f + _bq_a1 + _bq_a2);
    st.v1 = y_ss - _bq_b0 * x0;
    st.v2 = _bq_b2 * x0 - _bq_a2 * y_ss;
}

void MOW_AFE4490::_process_sample(int32_t led1, int32_t led2, int32_t aled1, int32_t aled2,
                                   int32_t led1_aled1, int32_t led2_aled2) {
    // Select PPG source
    float raw_ppg;
    switch (_ppg_channel) {
        case AFE4490Channel::LED1:       raw_ppg = (float)led1;       break;
        case AFE4490Channel::LED2:       raw_ppg = (float)led2;       break;
        case AFE4490Channel::ALED1:      raw_ppg = (float)aled1;      break;
        case AFE4490Channel::ALED2:      raw_ppg = (float)aled2;      break;
        case AFE4490Channel::LED2_ALED2: raw_ppg = (float)led2_aled2; break;
        default: /* LED1_ALED1 */        raw_ppg = (float)led1_aled1; break;
    }

    // Apply filter
    float filtered;
    switch (_filter_type) {
        case AFE4490Filter::BUTTERWORTH:
            if (_bq_ppg_needs_precharge) {
                _biquad_precharge(raw_ppg, _bq_ppg);
                _bq_ppg_needs_precharge = false;
            }
            filtered = _biquad_step(raw_ppg, _bq_ppg);
            break;
        case AFE4490Filter::MOVING_AVERAGE: {
            _ma_sum -= _ma_buf[_ma_idx];
            _ma_buf[_ma_idx] = raw_ppg;
            _ma_sum += raw_ppg;
            _ma_idx = (_ma_idx + 1) % ma_len;
            filtered = _ma_sum / (float)ma_len;
            break;
        }
        default: /* NONE */
            filtered = raw_ppg;
            break;
    }

    _current_data.ppg        = -(int32_t)filtered;  // negated: AFE raw falls on systole; invert for conventional PPG polarity (peaks up)
    _current_data.led1       = led1;
    _current_data.led2       = led2;
    _current_data.aled1      = aled1;
    _current_data.aled2      = aled2;
    _current_data.led1_aled1 = led1_aled1;
    _current_data.led2_aled2 = led2_aled2;

    // SpO2 uses ambient-corrected channels (unfiltered, spec §1.3)
    _update_spo2(led1_aled1, led2_aled2);

    // HR uses filtered PPG (negated: same polarity as _current_data.ppg — peaks up)
    _update_hr1(-filtered);

    // Push to queue; if full, drop oldest to keep most recent
    if (xQueueSend(_data_queue, &_current_data, 0) != pdTRUE) {
        AFE4490Data dummy;
        xQueueReceive(_data_queue, &dummy, 0);
        xQueueSend(_data_queue, &_current_data, 0);
    }
}

// ── SpO2 algorithm ────────────────────────────────────────────────────────────
// R = (AC_rms_RED / DC_RED) / (AC_rms_IR / DC_IR)
// SpO2 = a - b * R
void MOW_AFE4490::_update_spo2(int32_t ir_corr, int32_t red_corr) {
    float ir  = (float)ir_corr;
    float red = (float)red_corr;

    // IIR DC extraction
    _dc_ir  = _dc_iir_alpha * _dc_ir  + (1.0f - _dc_iir_alpha) * ir;
    _dc_red = _dc_iir_alpha * _dc_red + (1.0f - _dc_iir_alpha) * red;

    // EMA of AC²
    float ac_ir  = ir  - _dc_ir;
    float ac_red = red - _dc_red;
    _ac2_ir  = _ac_ema_beta * ac_ir  * ac_ir  + (1.0f - _ac_ema_beta) * _ac2_ir;
    _ac2_red = _ac_ema_beta * ac_red * ac_red + (1.0f - _ac_ema_beta) * _ac2_red;

    _spo2_sample_count++;

    // Skip during warmup or if DC is too low (no finger)
    if (_spo2_sample_count < _spo2_warmup_samples ||
        _dc_ir < spo2_min_dc || _dc_red < spo2_min_dc) {
        _current_data.spo2_valid = false;
        return;
    }

    float rms_ac_ir  = sqrtf(_ac2_ir);
    float rms_ac_red = sqrtf(_ac2_red);

    // Avoid division by near-zero
    if (_dc_ir < 1.0f || _dc_red < 1.0f || rms_ac_ir < 1.0f) {
        _current_data.spo2_valid = false;
        return;
    }

    float R    = (rms_ac_red / _dc_red) / (rms_ac_ir / _dc_ir);
    float spo2 = _spo2_a - _spo2_b * R;

    if (spo2 >= spo2_min && spo2 <= spo2_max) {
        _current_data.spo2       = spo2;
        _current_data.spo2_valid = true;
    } else {
        _current_data.spo2_valid = false;
    }
}

// ── HR algorithm ──────────────────────────────────────────────────────────────
// Adaptive-threshold peak detection on filtered PPG.
// Threshold = 0.6 × running_max; refractory = _hr1_refractory_samples.
// HR reported from average of 5 consecutive RR intervals.
void MOW_AFE4490::_update_hr1(float ppg_filtered) {
    _hr1_sample_idx++;

    // Running max: slow exponential decay keeps it tracking signal amplitude
    _hr1_running_max = fmaxf(_hr1_running_max * 0.9999f, ppg_filtered);

    float threshold = 0.6f * _hr1_running_max;

    // Threshold crossing (rising edge only)
    if (ppg_filtered > threshold && !_hr1_ppg_above_thresh) {
        _hr1_ppg_above_thresh = true;

        uint32_t elapsed = _hr1_sample_idx - _hr1_last_peak_idx;
        if (_hr1_last_peak_idx > 0 && elapsed > _hr1_refractory_samples) {
            // Shift interval buffer and store new interval
            for (int i = 4; i > 0; i--) _hr1_intervals[i] = _hr1_intervals[i - 1];
            _hr1_intervals[0] = (int32_t)elapsed;
            if (_hr1_interval_count < 5) _hr1_interval_count++;
        }
        _hr1_last_peak_idx = _hr1_sample_idx;

    } else if (ppg_filtered <= threshold) {
        _hr1_ppg_above_thresh = false;
    }

    // Need 5 intervals for a stable estimate
    if (_hr1_interval_count < 5) {
        _current_data.hr_valid = false;
        return;
    }

    float sum = 0.0f;
    for (int i = 0; i < 5; i++) sum += (float)_hr1_intervals[i];
    float avg_interval = sum / 5.0f;

    float hr = ((float)_sample_rate_hz * 60.0f) / avg_interval;

    if (hr >= hr_min_bpm && hr <= hr_max_bpm) {
        _current_data.hr       = (uint8_t)roundf(hr);
        _current_data.hr_valid = true;
    } else {
        _current_data.hr_valid = false;
    }
}
