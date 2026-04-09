#include <unity.h>
#include <math.h>
#include "mow_afe4490.h"

// Default calibration coefficients (must match mow_afe4490.cpp)
static constexpr float SPO2_A = 114.9208f;
static constexpr float SPO2_B =  30.5547f;

// Warmup = 5 s × 500 Hz = 2500 samples. Use 6000 for full convergence.
static constexpr int WARMUP_SAMPLES = 6000;

// Helper: feed N samples of dual-channel sines (same freq, different AC amplitude).
// IR:  DC=100000, AC=A_ir
// RED: DC=100000, AC=A_red
// R = (A_red/DC) / (A_ir/DC) = A_red/A_ir  (√2 factors cancel in RMS)
static void feed_spo2_sine(MOW_AFE4490& afe,
                            float a_ir, float a_red,
                            float freq_hz, int n_samples) {
    const float fs = 500.0f;
    const float dc = 100000.0f;
    for (int i = 0; i < n_samples; i++) {
        float phase = 2.0f * (float)M_PI * freq_hz * i / fs;
        int32_t ir  = (int32_t)(dc + a_ir  * sinf(phase));
        int32_t red = (int32_t)(dc + a_red * sinf(phase));
        afe.test_feed_spo2(ir, red);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid during warmup ──────────────────────────────────────────
void test_spo2_not_valid_during_warmup() {
    MOW_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, 1000);  // only 2 seconds
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
}

// ── Test 2: no finger (DC too low) → invalid ─────────────────────────────────
// spo2_min_dc = 1000. Feeding DC=500 should keep spo2_valid false.
void test_spo2_no_finger_invalid() {
    MOW_AFE4490 afe;
    for (int i = 0; i < WARMUP_SAMPLES; i++)
        afe.test_feed_spo2(500, 500);  // DC below threshold
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
}

// ── Test 3: SpO2 ≈ 98% ───────────────────────────────────────────────────────
// R = (114.9208 - 98) / 30.5547 ≈ 0.5538
// With a_ir=10000, a_red=5538 → R ≈ 0.5538
void test_spo2_98_percent() {
    MOW_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, WARMUP_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 98.0f, afe.test_spo2());
}

// ── Test 4: SpO2 ≈ 90% ───────────────────────────────────────────────────────
// R = (114.9208 - 90) / 30.5547 ≈ 0.8156
// With a_ir=10000, a_red=8156 → R ≈ 0.8156
void test_spo2_90_percent() {
    MOW_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 8156.0f, 1.0f, WARMUP_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 90.0f, afe.test_spo2());
}

// ── Test 5: SpO2 slightly above 100 → clamped to 100 and reported valid ──────
// a_red=4500 → R ≈ 0.45 → raw SpO2 ≈ 101.2 → within clamp margin → 100.0
void test_spo2_clamp_above_100() {
    MOW_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 4500.0f, 1.0f, WARMUP_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 100.0f, afe.test_spo2());
}

// ── Test 6: SpO2 far above 100 → invalid (outside clamp margin) ──────────────
// a_red=3000 → R ≈ 0.30 → raw SpO2 ≈ 105.8 → exceeds clamp margin → invalid
void test_spo2_too_high_invalid() {
    MOW_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 3000.0f, 1.0f, WARMUP_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_spo2_not_valid_during_warmup);
    RUN_TEST(test_spo2_no_finger_invalid);
    RUN_TEST(test_spo2_98_percent);
    RUN_TEST(test_spo2_90_percent);
    RUN_TEST(test_spo2_clamp_above_100);
    RUN_TEST(test_spo2_too_high_invalid);
    return UNITY_END();
}
