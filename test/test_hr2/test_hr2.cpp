#include <unity.h>
#include <math.h>
#include <stdlib.h>
#include "incunest_afe4490.h"

// HR2 constants (mirror of incunest_afe4490.cpp namespace)
static constexpr int HR2_BUF_LEN      = 400;   // decimated samples
static constexpr int HR2_DECIM_FACTOR = 10;
static constexpr int HR2_BUF_RAW      = HR2_BUF_LEN * HR2_DECIM_FACTOR;  // 4000 raw samples

// Helper: feed N raw samples of a sine at freq_hz into HR2.
static void feed_hr2_sine(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    for (int i = 0; i < n_samples; i++) {
        float x = 500000.0f + 50000.0f * sinf(2.0f * (float)M_PI * freq_hz * i / fs);
        afe.test_feed_hr2((int32_t)x);
    }
}

// Helper: same as feed_hr2_sine but with uniform noise ±5000 (~10% of amplitude, ~20 dB SNR).
// srand(42) called by the test before use for reproducibility.
static void feed_hr2_sine_noisy(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    for (int i = 0; i < n_samples; i++) {
        float noise = 5000.0f * (2.0f * (float)rand() / (float)RAND_MAX - 1.0f);
        float x = 500000.0f + 50000.0f * sinf(2.0f * (float)M_PI * freq_hz * i / fs) + noise;
        afe.test_feed_hr2((int32_t)x);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid until buffer is full ────────────────────────────────────
// HR2 needs HR2_BUF_LEN decimated samples before reporting. After half that,
// hr2_valid must be false.
void test_hr2_not_valid_until_buffer_full() {
    INCUNEST_AFE4490 afe;
    feed_hr2_sine(afe, 1.0f, 500.0f, HR2_BUF_RAW / 2);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr2_sqi());
}

// ── Test 2: 60 BPM (1 Hz sine) ───────────────────────────────────────────────
// At 50 Hz decimated rate, 1 Hz → period = 50 samples lag.
// HR2 should converge to 60 BPM ± 1.
// SQI: unbiased normalised autocorrelation at fundamental lag → SQI ≈ 1.0 for
// clean periodic signal (finite-window bias corrected). Threshold: > 0.95.
void test_hr2_60bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr2_sine(afe, 1.0f, 500.0f, HR2_BUF_RAW + 1000);  // fill + margin
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 60.0f, afe.test_hr2());
}

// ── Test 3: 120 BPM (2 Hz sine) ──────────────────────────────────────────────
// At 50 Hz decimated rate, 2 Hz → period = 25 samples lag.
// SQI: unbiased normalised autocorrelation → SQI ≈ 1.0 for clean signal. Threshold: > 0.95.
void test_hr2_120bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr2_sine(afe, 2.0f, 500.0f, HR2_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 120.0f, afe.test_hr2());
}

// ── Test 4: flat signal → hr2_valid false ────────────────────────────────────
// A constant DC signal has zero AC energy after the bandpass filter.
// The autocorrelation check (acorr0 < 1.0) must reject it.
void test_hr2_flat_signal_invalid() {
    INCUNEST_AFE4490 afe;
    for (int i = 0; i < HR2_BUF_RAW + 1000; i++)
        afe.test_feed_hr2(500000);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr2_sqi());
}

// ── Test 5: 60 BPM with noise (~20 dB SNR) ───────────────────────────────────
// Autocorrelation is robust to additive noise. With ±10% noise HR2 must still
// converge to 60 BPM ± 1 and SQI > 0.80 (unbiased; noise lowers peak but correction
// raises it slightly vs. biased). Noise barely changes autocorrelation shape.
void test_hr2_60bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr2_sine_noisy(afe, 1.0f, 500.0f, HR2_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.80f, afe.test_hr2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 60.0f, afe.test_hr2());
}

// ── Test 6: 120 BPM with noise (~20 dB SNR) ──────────────────────────────────
void test_hr2_120bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr2_sine_noisy(afe, 2.0f, 500.0f, HR2_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.80f, afe.test_hr2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 120.0f, afe.test_hr2());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hr2_not_valid_until_buffer_full);
    RUN_TEST(test_hr2_60bpm);
    RUN_TEST(test_hr2_120bpm);
    RUN_TEST(test_hr2_flat_signal_invalid);
    RUN_TEST(test_hr2_60bpm_noisy);
    RUN_TEST(test_hr2_120bpm_noisy);
    return UNITY_END();
}
