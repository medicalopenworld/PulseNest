#include <unity.h>
#include <math.h>
#include "incunest_afe4490.h"

// Bandpass designed with the library's own bilinear transform (BiquadFilter::init_bp), state cleared.
static INCUNEST_AFE4490::TestBiquadFilter make_bp(float f_low, float f_high, float fs) {
    INCUNEST_AFE4490::TestBiquadFilter f;
    f.init_bp(f_low, f_high, fs);
    f.reset();
    return f;
}

// Helper: feed N samples of a sine at freq_hz through the filter and return
// the peak amplitude of the last half (steady state).
static float sine_amplitude_after_filter(INCUNEST_AFE4490::TestBiquadFilter& f,
                                         float freq_hz, float fs,
                                         int n_samples) {
    float peak = 0.0f;
    for (int i = 0; i < n_samples; i++) {
        float x = sinf(2.0f * (float)M_PI * freq_hz * i / fs);
        float y = f.process(x);
        if (i >= n_samples / 2) {
            float a = fabsf(y);
            if (a > peak) peak = a;
        }
    }
    return peak;
}

void setUp() {}
void tearDown() {}

// ── Test 1: passband frequency passes through ─────────────────────────────────
// A sine at 5 Hz is well inside the default 0.5–20 Hz bandpass.
// After steady state the output amplitude should be close to 1.0.
void test_biquad_passband_passes() {
    INCUNEST_AFE4490::TestBiquadFilter f = make_bp(0.5f, 20.0f, 500.0f);
    float amp = sine_amplitude_after_filter(f, 5.0f, 500.0f, 2000);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 1.0f, amp);  // expect ~1.0 ± 0.1
}

// ── Test 2: DC is blocked ─────────────────────────────────────────────────────
// A bandpass filter must attenuate DC (0 Hz) to near zero.
void test_biquad_blocks_dc() {
    INCUNEST_AFE4490::TestBiquadFilter f = make_bp(0.5f, 20.0f, 500.0f);
    // Feed a constant value of 1.0 (DC)
    float last = 0.0f;
    for (int i = 0; i < 2000; i++)
        last = f.process(1.0f);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, last);  // expect ~0 ± 0.05
}

// ── Test 3: high frequency is attenuated ─────────────────────────────────────
// A sine at 100 Hz is well above the 20 Hz high cutoff.
// Output amplitude should be much less than 1.0.
void test_biquad_attenuates_high_freq() {
    INCUNEST_AFE4490::TestBiquadFilter f = make_bp(0.5f, 20.0f, 500.0f);
    float amp = sine_amplitude_after_filter(f, 100.0f, 500.0f, 2000);
    // 2nd-order bandpass rolloff is ~20 dB/decade; at 100 Hz vs 20 Hz cutoff
    // (5× ratio) expect amplitude < 0.25
    TEST_ASSERT_LESS_THAN_FLOAT(0.25f, amp);
}

// ── Test 4: HR2 filter (0.5–5 Hz) attenuates 20 Hz ───────────────────────────
// The HR2 bandpass is narrower (0.5–5 Hz). A 20 Hz sine (4× the cutoff) should
// be noticeably attenuated. 2nd-order rolloff → expect amplitude < 0.30.
void test_biquad_hr2_attenuates_20hz() {
    INCUNEST_AFE4490::TestBiquadFilter f = make_bp(0.5f, 5.0f, 500.0f);
    float amp = sine_amplitude_after_filter(f, 20.0f, 500.0f, 2000);
    TEST_ASSERT_LESS_THAN_FLOAT(0.30f, amp);
}

// ── Test 5: output decays to zero with zero input ────────────────────────────
// After a burst of signal, feeding zeros should let the filter drain to zero.
void test_biquad_drains_to_zero() {
    INCUNEST_AFE4490::TestBiquadFilter f = make_bp(0.5f, 20.0f, 500.0f);
    // Excite the filter
    for (int i = 0; i < 500; i++)
        f.process(sinf(2.0f * (float)M_PI * 5.0f * i / 500.0f));
    // Feed zeros
    float last = 0.0f;
    for (int i = 0; i < 2000; i++)
        last = f.process(0.0f);
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
