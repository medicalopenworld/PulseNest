#include <unity.h>
#include <math.h>
#include "incunest_afe4490.h"

// EXPERIMENT (OT-domain input, branch experiment/ot-domain-inputs): HR1 now consumes OT
// (dimensionless A/A, ~1e-5 typical per incunest_afe4490_spec.md) instead of raw
// ambient-corrected ADC counts. HR1 is peak-timing based (not a ratio like SpO2's R), so a
// uniform gain scale does not change peak timing — this is a pure domain/type change, no
// threshold recalibration needed (confirmed: _hr1_running_max/threshold are self-relative).

// Helper: feed N samples of a sine at freq_hz (with DC offset) into HR1, in OT-scale units.
static void feed_hr1_sine(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    const float ot_dc = 1.4e-5f;
    const float scale = 1.4e-10f;
    for (int i = 0; i < n_samples; i++) {
        float x = ot_dc + 50000.0f * scale * sinf(2.0f * (float)M_PI * freq_hz * i / fs);
        afe.test_feed_hr1(x);
    }
}

// Helper: same as feed_hr1_sine but with uniform noise (~10% of amplitude, ~20 dB SNR).
// srand(42) called by the test before use for reproducibility.
static void feed_hr1_sine_noisy(INCUNEST_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    const float ot_dc = 1.4e-5f;
    const float scale = 1.4e-10f;
    for (int i = 0; i < n_samples; i++) {
        float noise = 5000.0f * scale * (2.0f * (float)rand() / (float)RAND_MAX - 1.0f);
        float x = ot_dc + 50000.0f * scale * sinf(2.0f * (float)M_PI * freq_hz * i / fs) + noise;
        afe.test_feed_hr1(x);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid until 5 intervals have been detected ────────────────────
// After only 1 second of signal (< 2 complete cycles at 1 Hz = 60 BPM),
// hr1_valid must be false.
void test_hr1_not_valid_too_soon() {
    INCUNEST_AFE4490 afe;
    feed_hr1_sine(afe, 1.0f, 500.0f, 500);  // 1 second — not enough intervals
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr1_sqi());
}

// ── Test 2: 60 BPM (1 Hz sine) ───────────────────────────────────────────────
// After enough samples, HR1 should converge to 60 BPM ± 1.
// SQI: a synthetic sine has near-zero RR jitter → SQI ≈ 1.0. Threshold: > 0.95.
void test_hr1_60bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr1_sine(afe, 1.0f, 500.0f, 6000);  // 12 seconds — plenty of intervals
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr1_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 60.0f, afe.test_hr1());
}

// ── Test 3: 120 BPM (2 Hz sine) ──────────────────────────────────────────────
// SQI continuous: synthetic sine → low jitter → SQI > 0.95.
void test_hr1_120bpm() {
    INCUNEST_AFE4490 afe;
    feed_hr1_sine(afe, 2.0f, 500.0f, 6000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.95f, afe.test_hr1_sqi());
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 120.0f, afe.test_hr1());
}

// ── Test 4: out-of-range signal → hr1_valid false ────────────────────────────
// A flat (DC only) signal has no peaks — hr1_valid must stay false.
void test_hr1_flat_signal_invalid() {
    INCUNEST_AFE4490 afe;
    for (int i = 0; i < 6000; i++)
        afe.test_feed_hr1(1.4e-5f);  // constant DC (OT scale), no PPG pulses
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_hr1_sqi());
}

// ── Test 5: 60 BPM with noise (~20 dB SNR) ───────────────────────────────────
// With uniform noise ±10% of amplitude, HR1 must still converge to 60 BPM ± 2
// and SQI > 0.8. Noise raises RR jitter slightly, lowering SQI from 1.0 to ~0.99.
void test_hr1_60bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr1_sine_noisy(afe, 1.0f, 500.0f, 6000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.8f, afe.test_hr1_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 60.0f, afe.test_hr1());
}

// ── Test 6: 120 BPM with noise (~20 dB SNR) ──────────────────────────────────
void test_hr1_120bpm_noisy() {
    INCUNEST_AFE4490 afe;
    srand(42);
    feed_hr1_sine_noisy(afe, 2.0f, 500.0f, 6000);
    TEST_ASSERT_GREATER_THAN_FLOAT(0.8f, afe.test_hr1_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 120.0f, afe.test_hr1());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hr1_not_valid_too_soon);
    RUN_TEST(test_hr1_60bpm);
    RUN_TEST(test_hr1_120bpm);
    RUN_TEST(test_hr1_flat_signal_invalid);
    RUN_TEST(test_hr1_60bpm_noisy);
    RUN_TEST(test_hr1_120bpm_noisy);
    return UNITY_END();
}
