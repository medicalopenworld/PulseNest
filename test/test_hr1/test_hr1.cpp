#include <unity.h>
#include <math.h>
#include "mow_afe4490.h"

// Helper: feed N samples of a sine at freq_hz (with DC offset) into HR1.
// Amplitude 50000 matches typical AFE4490 ADC range.
static void feed_hr1_sine(MOW_AFE4490& afe, float freq_hz, float fs, int n_samples) {
    for (int i = 0; i < n_samples; i++) {
        float x = 500000.0f + 50000.0f * sinf(2.0f * (float)M_PI * freq_hz * i / fs);
        afe.test_feed_hr1((int32_t)x);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid until 5 intervals have been detected ────────────────────
// After only 1 second of signal (< 2 complete cycles at 1 Hz = 60 BPM),
// hr1_valid must be false.
void test_hr1_not_valid_too_soon() {
    MOW_AFE4490 afe;
    feed_hr1_sine(afe, 1.0f, 500.0f, 500);  // 1 second — not enough intervals
    TEST_ASSERT_FALSE(afe.test_hr1_valid());
}

// ── Test 2: 60 BPM (1 Hz sine) ───────────────────────────────────────────────
// After enough samples, HR1 should converge to 60 BPM ± 5.
void test_hr1_60bpm() {
    MOW_AFE4490 afe;
    feed_hr1_sine(afe, 1.0f, 500.0f, 6000);  // 12 seconds — plenty of intervals
    TEST_ASSERT_TRUE(afe.test_hr1_valid());
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 60.0f, afe.test_hr1());
}

// ── Test 3: 120 BPM (2 Hz sine) ──────────────────────────────────────────────
void test_hr1_120bpm() {
    MOW_AFE4490 afe;
    feed_hr1_sine(afe, 2.0f, 500.0f, 6000);
    TEST_ASSERT_TRUE(afe.test_hr1_valid());
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 120.0f, afe.test_hr1());
}

// ── Test 4: out-of-range signal → hr1_valid false ────────────────────────────
// A flat (DC only) signal has no peaks — hr1_valid must stay false.
void test_hr1_flat_signal_invalid() {
    MOW_AFE4490 afe;
    for (int i = 0; i < 6000; i++)
        afe.test_feed_hr1(500000);  // constant DC, no PPG pulses
    TEST_ASSERT_FALSE(afe.test_hr1_valid());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hr1_not_valid_too_soon);
    RUN_TEST(test_hr1_60bpm);
    RUN_TEST(test_hr1_120bpm);
    RUN_TEST(test_hr1_flat_signal_invalid);
    return UNITY_END();
}
