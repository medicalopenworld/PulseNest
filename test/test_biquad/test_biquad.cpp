#include <unity.h>
#include <math.h>
#include "mow_afe4490.h"

// Helper: feed N samples of a sine at freq_hz through the filter and return
// the peak amplitude of the last half (steady state).
static float sine_amplitude_after_filter(MOW_AFE4490& afe,
                                         MOW_AFE4490::TestBiquadFilter& f,
                                         float freq_hz, float fs,
                                         int n_samples) {
    float peak = 0.0f;
    for (int i = 0; i < n_samples; i++) {
        float x = sinf(2.0f * (float)M_PI * freq_hz * i / fs);
        float y = afe.test_biquad_process(x, f);
        if (i >= n_samples / 2) {
            float a = fabsf(y);
            if (a > peak) peak = a;
        }
    }
    return peak;
}

static MOW_AFE4490 afe;

void setUp() {}
void tearDown() {}

// ── Test 1: passband frequency passes through ─────────────────────────────────
// A sine at 5 Hz is well inside the default 0.5–20 Hz bandpass.
// After steady state the output amplitude should be close to 1.0.
void test_biquad_passband_passes() {
    MOW_AFE4490::TestBiquadFilter f = {0.5f, 20.0f, 0,0,0,0,0, {0,0}, true};
    afe.test_recalc_biquad(f);
    float amp = sine_amplitude_after_filter(afe, f, 5.0f, 500.0f, 2000);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 1.0f, amp);  // expect ~1.0 ± 0.1
}

// ── Test 2: DC is blocked ─────────────────────────────────────────────────────
// A bandpass filter must attenuate DC (0 Hz) to near zero.
void test_biquad_blocks_dc() {
    MOW_AFE4490::TestBiquadFilter f = {0.5f, 20.0f, 0,0,0,0,0, {0,0}, true};
    afe.test_recalc_biquad(f);
    // Feed a constant value of 1.0 (DC)
    float last = 0.0f;
    for (int i = 0; i < 2000; i++)
        last = afe.test_biquad_process(1.0f, f);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, last);  // expect ~0 ± 0.05
}

// ── Test 3: high frequency is attenuated ─────────────────────────────────────
// A sine at 100 Hz is well above the 20 Hz high cutoff.
// Output amplitude should be much less than 1.0.
void test_biquad_attenuates_high_freq() {
    MOW_AFE4490::TestBiquadFilter f = {0.5f, 20.0f, 0,0,0,0,0, {0,0}, true};
    afe.test_recalc_biquad(f);
    float amp = sine_amplitude_after_filter(afe, f, 100.0f, 500.0f, 2000);
    // 2nd-order bandpass rolloff is ~20 dB/decade; at 100 Hz vs 20 Hz cutoff
    // (5× ratio) expect amplitude < 0.25
    TEST_ASSERT_LESS_THAN_FLOAT(0.25f, amp);
}

// ── Test 4: HR2 filter (0.5–5 Hz) attenuates 20 Hz ───────────────────────────
// The HR2 bandpass is narrower (0.5–5 Hz). A 20 Hz sine (4× the cutoff) should
// be noticeably attenuated. 2nd-order rolloff → expect amplitude < 0.30.
void test_biquad_hr2_attenuates_20hz() {
    MOW_AFE4490::TestBiquadFilter f = {0.5f, 5.0f, 0,0,0,0,0, {0,0}, true};
    afe.test_recalc_biquad(f);
    float amp = sine_amplitude_after_filter(afe, f, 20.0f, 500.0f, 2000);
    TEST_ASSERT_LESS_THAN_FLOAT(0.30f, amp);
}

// ── Test 5: output decays to zero with zero input ────────────────────────────
// After a burst of signal, feeding zeros should let the filter drain to zero.
void test_biquad_drains_to_zero() {
    MOW_AFE4490::TestBiquadFilter f = {0.5f, 20.0f, 0,0,0,0,0, {0,0}, true};
    afe.test_recalc_biquad(f);
    // Excite the filter
    for (int i = 0; i < 500; i++)
        afe.test_biquad_process(sinf(2.0f * (float)M_PI * 5.0f * i / 500.0f), f);
    // Feed zeros
    float last = 0.0f;
    for (int i = 0; i < 2000; i++)
        last = afe.test_biquad_process(0.0f, f);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, last);
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_biquad_passband_passes);
    RUN_TEST(test_biquad_blocks_dc);
    RUN_TEST(test_biquad_attenuates_high_freq);
    RUN_TEST(test_biquad_hr2_attenuates_20hz);
    RUN_TEST(test_biquad_drains_to_zero);
    return UNITY_END();
}
