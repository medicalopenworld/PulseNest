#include <unity.h>
#include <math.h>
#include <stdlib.h>
#include "incunest_afe4490.h"

// HR3 constants (mirror of incunest_afe4490.cpp namespace)
static constexpr int HR3_BUF_LEN      = 512;   // decimated samples
static constexpr int HR3_DECIM_FACTOR = 10;
static constexpr int HR3_BUF_RAW      = HR3_BUF_LEN * HR3_DECIM_FACTOR;  // 5120 raw samples

// Helper: feed N raw samples of a PPG-like signal (fundamental + 2nd + 3rd harmonic) into HR3.
// HR3 uses the Harmonic Product Spectrum (HPS = P[k]*P[2k]*P[3k]), which requires energy
// at the harmonic frequencies to produce a clear peak. A pure sine would yield near-zero HPS
// at all bins and SQI ≈ 0. All harmonics stay below the 10 Hz LP filter cutoff for freq_hz ≤ 3 Hz.
static void feed_hr3_sine(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    for (int i = 0; i < n_samples; i++) {
        float t = (float)i / fs;
        float x = 500000.0f
                + 40000.0f * sinf(2.0f * (float)M_PI * freq_hz * t)   // fundamental
                + 20000.0f * sinf(4.0f * (float)M_PI * freq_hz * t)   // 2nd harmonic
                +  8000.0f * sinf(6.0f * (float)M_PI * freq_hz * t);  // 3rd harmonic
        afe.test_feed_hr3((int32_t)x);
    }
}

// Helper: same as feed_hr3_sine but with uniform noise ±4000 (~10% of fundamental, ~20 dB SNR).
// srand(42) called by the test before use for reproducibility.
static void feed_hr3_sine_noisy(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    for (int i = 0; i < n_samples; i++) {
        float t = (float)i / fs;
        float noise = 4000.0f * (2.0f * (float)rand() / (float)RAND_MAX - 1.0f);
        float x = 500000.0f
                + 40000.0f * sinf(2.0f * (float)M_PI * freq_hz * t)   // fundamental
                + 20000.0f * sinf(4.0f * (float)M_PI * freq_hz * t)   // 2nd harmonic
                +  8000.0f * sinf(6.0f * (float)M_PI * freq_hz * t)   // 3rd harmonic
                + noise;
        afe.test_feed_hr3((int32_t)x);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid until buffer is full ────────────────────────────────────
// HR3 needs HR3_BUF_LEN decimated samples before computing FFT. After half that,
// hr3_valid must be false.
void test_hr3_not_valid_until_buffer_full() {
    INCUNEST_AFE4490 afe;
    feed_hr3_sine(afe, 1.0f, 500.0f, HR3_BUF_RAW / 2);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr3_sqi());
}

// ── Test 2: 60 BPM (1 Hz sine) ───────────────────────────────────────────────
// At 50 Hz decimated rate, 1 Hz → bin index 1 in a 512-point FFT (resolution ~0.098 Hz).
// HR3 should converge to 60 BPM ± 2 via parabolic interpolation on the HPS peak.
// SQI: dominant HPS peak at 1 Hz → SQI = 1.0. Threshold: > 0.95.
void test_hr3_60bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr3_sine(afe, 1.0f, 500.0f, HR3_BUF_RAW + 1000);  // fill + margin
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr3_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 60.0f, afe.test_hr3());
}

// ── Test 3: 120 BPM (2 Hz sine) ──────────────────────────────────────────────
// SQI: dominant HPS peak at 2 Hz → SQI ≈ 0.73. Threshold: > 0.65.
// HR precision limited by FFT bin width (~0.098 Hz = ~5.9 BPM at 2 Hz).
void test_hr3_120bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr3_sine(afe, 2.0f, 500.0f, HR3_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.65f, afe.test_hr3_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 120.0f, afe.test_hr3());
}

// ── Test 3b: 85 BPM (worst-case inter-bin frequency) ─────────────────────────
// 85 BPM = 1.4167 Hz → bin 14.506, exactly halfway between bins 14 and 15.
// Without HPS interpolation, the cubic product loss reduces SQI to ~0.5 even
// for a clean signal. With parabolic HPS interpolation SQI must stay > 0.80.
void test_hr3_85bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr3_sine(afe, 85.0f / 60.0f, 500.0f, HR3_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.80f, afe.test_hr3_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 85.0f, afe.test_hr3());
}

// ── Test 4: flat signal → hr3_valid false ────────────────────────────────────
// A constant DC signal has zero AC energy after the LP filter.
// The FFT output is flat → no dominant HPS peak → SQI must be 0.
void test_hr3_flat_signal_invalid() {
    INCUNEST_AFE4490 afe;
    for (int i = 0; i < HR3_BUF_RAW + 1000; i++)
        afe.test_feed_hr3(500000);  // constant DC, no PPG pulses
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr3_sqi());
}

// ── Test 5: 60 BPM with noise (~20 dB SNR) ───────────────────────────────────
// With ±10% noise the HPS peak should remain dominant. HR3 must converge to
// 60 BPM ± 2 and SQI > 0.95.
void test_hr3_60bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr3_sine_noisy(afe, 1.0f, 500.0f, HR3_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr3_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 60.0f, afe.test_hr3());
}

// ── Test 6: 120 BPM with noise (~20 dB SNR) ──────────────────────────────────
void test_hr3_120bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr3_sine_noisy(afe, 2.0f, 500.0f, HR3_BUF_RAW + 1000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.65f, afe.test_hr3_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 120.0f, afe.test_hr3());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hr3_not_valid_until_buffer_full);
    RUN_TEST(test_hr3_60bpm);
    RUN_TEST(test_hr3_120bpm);
    RUN_TEST(test_hr3_85bpm);
    RUN_TEST(test_hr3_flat_signal_invalid);
    RUN_TEST(test_hr3_60bpm_noisy);
    RUN_TEST(test_hr3_120bpm_noisy);
    return UNITY_END();
}
