#include <unity.h>
#include <math.h>
#include <stdio.h>
#include "incunest_afe4490.h"

// Exhaustive validation of the sample-rate catalogue (spec §7.4).
//
// This is the test that makes a closed catalogue worth having: because the set is finite and
// enumerable, EVERY supported rate is a test case, and the invariants below are exactly the ones
// a validation report would have to assert. A continuous range could not be covered this way.
//
// Four conditions per entry:
//   1. q = (afeclk/hz)/4 exact       -> the real PRF equals the requested one, so every tau and
//                                       alpha derived from the nominal rate is correct.
//   2. hz multiple of 50             -> both analysis chains get an INTEGER decimation factor
//                                       and hold their 50 Hz rate (spec 5.3.1).
//   3. both sampling windows >= 50us -> TI's minimum (datasheet 8.3.1.1). The ambient window is
//                                       the binding one and sets the ~1660 Hz ceiling.
//   4. NUMAV_max >= 1                -> at least one ADC conversion fits in the window.

static constexpr uint32_t AFECLK          = 4000000u;  // counts/s, 1 count = 0.25 us
static constexpr uint32_t TIA_SETTLE_MIN  = 50u;       // counts (12.5 us)
static constexpr float    TIA_SETTLE_FRAC = 0.10f;
static constexpr uint32_t AMB_MARGIN      = 400u;      // counts (100 us), raised in v0.47
static constexpr uint32_t TI_MIN_WINDOW   = 200u;      // counts = 50 us

void setUp() {}
void tearDown() {}

void test_catalogue_is_not_empty() {
    TEST_ASSERT_EQUAL_UINT8(5, INCUNEST_AFE4490::sampleRateCount());
    TEST_ASSERT_EQUAL_UINT16(500, INCUNEST_AFE4490::sampleRateHz(AFE4490SampleRate::HZ_500));
    TEST_ASSERT_EQUAL_UINT16(1600, INCUNEST_AFE4490::sampleRateHz(AFE4490SampleRate::HZ_1600));
}

void test_every_rate_satisfies_its_invariants() {
    for (uint8_t i = 0; i < INCUNEST_AFE4490::sampleRateCount(); i++) {
        const uint16_t hz = kAFE_SAMPLE_RATE_HZ[i];
        char msg[96];

        // 1. exact q
        snprintf(msg, sizeof(msg), "%u Hz: q not exact (AFECLK %% (4*hz) != 0)", hz);
        TEST_ASSERT_EQUAL_UINT32_MESSAGE(0, AFECLK % (4u * hz), msg);
        const uint32_t q = (AFECLK / hz) / 4u;

        // 2. integer decimation factor for the analysis chains
        snprintf(msg, sizeof(msg), "%u Hz: not a multiple of 50 -> fractional decimation", hz);
        TEST_ASSERT_EQUAL_UINT16_MESSAGE(0, hz % 50u, msg);

        // 3. both sampling windows within TI's 50 us minimum
        uint32_t led_margin = (uint32_t)((float)q * TIA_SETTLE_FRAC);
        if (led_margin < TIA_SETTLE_MIN) led_margin = TIA_SETTLE_MIN;
        const uint32_t win_led = (q > led_margin + 2u) ? (q - 2u - led_margin) : 0u;
        const uint32_t win_amb = (q > AMB_MARGIN  + 2u) ? (q - 2u - AMB_MARGIN)  : 0u;
        snprintf(msg, sizeof(msg), "%u Hz: LED window %u counts < 50 us", hz, (unsigned)win_led);
        TEST_ASSERT_TRUE_MESSAGE(win_led >= TI_MIN_WINDOW, msg);
        snprintf(msg, sizeof(msg), "%u Hz: ambient window %u counts < 50 us", hz, (unsigned)win_amb);
        TEST_ASSERT_TRUE_MESSAGE(win_amb >= TI_MIN_WINDOW, msg);

        // The ambient start must never be programmed after its end (the >2487 Hz failure).
        snprintf(msg, sizeof(msg), "%u Hz: ALEDxSTC would exceed ALEDxENDC", hz);
        TEST_ASSERT_TRUE_MESSAGE(q >= AMB_MARGIN + 2u, msg);

        // 4. at least one ADC conversion fits
        snprintf(msg, sizeof(msg), "%u Hz: no ADC conversion fits (5000/hz < 1)", hz);
        TEST_ASSERT_TRUE_MESSAGE((5000u / hz) >= 1u, msg);
    }
}

// Every catalogue entry must round-trip through the numeric form, and nothing else may pass.
void test_numeric_form_accepts_only_catalogue_values() {
    for (uint8_t i = 0; i < INCUNEST_AFE4490::sampleRateCount(); i++) {
        AFE4490SampleRate r;
        TEST_ASSERT_TRUE(INCUNEST_AFE4490::isValidSampleRateHz(kAFE_SAMPLE_RATE_HZ[i], &r));
        TEST_ASSERT_EQUAL_UINT16(kAFE_SAMPLE_RATE_HZ[i], INCUNEST_AFE4490::sampleRateHz(r));
    }
    // All of these used to be accepted. 3000 and 5000 Hz invert the ambient timer pair, 250 Hz
    // collapses the anti-alias margin, 625 Hz would need a fractional decimation factor.
    static const uint16_t rejected[] = {63, 100, 250, 400, 625, 750, 2000, 3000, 5000, 0, 65535};
    for (unsigned k = 0; k < sizeof(rejected) / sizeof(rejected[0]); k++) {
        char msg[64];
        snprintf(msg, sizeof(msg), "%u Hz should not be accepted", rejected[k]);
        TEST_ASSERT_FALSE_MESSAGE(INCUNEST_AFE4490::isValidSampleRateHz(rejected[k]), msg);
    }
}

// A rejected rate must leave the configuration untouched, not fall back to a default.
void test_rejected_rate_leaves_configuration_untouched() {
    INCUNEST_AFE4490 afe;
    afe.setSampleRate(AFE4490SampleRate::HZ_1000);
    TEST_ASSERT_EQUAL_UINT16(20, afe.test_hr2_decim_factor());    // 1000/50
    afe.setSampleRate((uint16_t)3000);                            // rejected
    TEST_ASSERT_EQUAL_UINT16(20, afe.test_hr2_decim_factor());    // unchanged
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 50.0f, afe.test_hr2_decim_rate_hz());
}

// Both chains must hold their 50 Hz target across the whole catalogue, with an exact factor.
void test_chains_hold_50hz_across_catalogue() {
    INCUNEST_AFE4490 afe;
    for (uint8_t i = 0; i < INCUNEST_AFE4490::sampleRateCount(); i++) {
        afe.setSampleRate((AFE4490SampleRate)i);
        char msg[72];
        snprintf(msg, sizeof(msg), "%u Hz: HR2 chain rate", kAFE_SAMPLE_RATE_HZ[i]);
        TEST_ASSERT_FLOAT_WITHIN_MESSAGE(0.01f, 50.0f, afe.test_hr2_decim_rate_hz(), msg);
        snprintf(msg, sizeof(msg), "%u Hz: HR3 chain rate", kAFE_SAMPLE_RATE_HZ[i]);
        TEST_ASSERT_FLOAT_WITHIN_MESSAGE(0.01f, 50.0f, afe.test_hr3_decim_rate_hz(), msg);
        snprintf(msg, sizeof(msg), "%u Hz: decimation factor must be integer-exact",
                 kAFE_SAMPLE_RATE_HZ[i]);
        TEST_ASSERT_EQUAL_UINT16_MESSAGE(kAFE_SAMPLE_RATE_HZ[i] / 50u,
                                         afe.test_hr2_decim_factor(), msg);
    }
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_catalogue_is_not_empty);
    RUN_TEST(test_every_rate_satisfies_its_invariants);
    RUN_TEST(test_numeric_form_accepts_only_catalogue_values);
    RUN_TEST(test_rejected_rate_leaves_configuration_untouched);
    RUN_TEST(test_chains_hold_50hz_across_catalogue);
    return UNITY_END();
}
