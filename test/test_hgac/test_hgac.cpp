#include <unity.h>
#include "incunest_afe4490.h"

// HGAC Phase 1 (RF-only descent) — see incunest_afe4490_spec.md §5.8.
// EXPERIMENT (OT-domain input, branch experiment/ot-domain-inputs, spec §5.1): SpO2 now
// consumes as.ot_led1/ot_led2 (gain-invariant), so _hgac_step_rf_down() no longer rescales the
// SpO2 EmaChannel by k — see test_hgac_no_longer_rescales_spo2_ema below.
//
// Physics reminder (v1: AMBDAC=0, Stage2 gain ×1 default): v_tia_diff == v_adc, i.e.
// v_tia_diff_led1 = led1_code * (1.2 / 2097151). Since 2026-07-24, PROBE_SATURATING is a
// distinct state from PROBE_NOT_APPLIED (see enum ProbeState) and HGAC's gate requires
// PROBE_APPLIED or PROBE_SATURATING — so the stimulus must trip TIA-linearity invalidity
// (v_tia_diff > kVTiaDiffFs = 1.0 V, i.e. LED1 not CH_VALID_RANGE) to open the gate at all. Use a
// code around 1,900,000 → v_tia_diff ≈ 1.087 V: above kVTiaDiffFs (invalid → SATURATING)
// but below the ADC positive rail (kAdcSatPos = 2,096,700 counts, no ADC clipping) and
// still comfortably above the 0.9 V HGAC actuation guard.
static constexpr int32_t SAT_LED1_CODE = 1900000;  // v_tia_diff_led1 ≈ 1.087 V (OFF_SPEC, not clipped)

// Sample-budget model (defaults: hgac_tiaguard_debounce_min_s=0.5s, hgac_settle_time_s=0.15s,
// rsqm_probe_state_min_s=0.2s, fs=500 Hz), verified against a standalone instrumented run:
//   - Gate opens at sample 100: PROBE_SATURATING debounce commits (100 = 0.2s*500Hz).
//     (LED1's v_tia_diff > kVTiaDiffFs sets tia_over_fs, so anyPositiveSaturation() is true —
//     RSQM classifies this as PROBE_SATURATING, which HGAC's Gate G0 (inlined in
//     _hgac_update()) treats like PROBE_APPLIED — see spec §5.8.)
//   - 1st descent (RF_100K->RF_50K) at sample 100 + 250 - 1 = 349.
//   - Settling (75 samples) active 350-424; gate reopens at 425.
//   - 2nd descent (RF_50K->RF_25K) at 425 + 250 - 1 = 674.
//   - Settling 675-749; gate reopens at 750.
//   - 3rd descent (RF_25K->RF_10K) at 750 + 250 - 1 = 999.
//   - Settling 1000-1074; gate reopens at 1075.
//   - Gain-floor alarm (debounced the same way) at 1075 + 250 - 1 = 1324.
static void feed_saturating_led1(INCUNEST_AFE4490& afe, int n) {
    for (int i = 0; i < n; i++) afe.test_feed_sample(SAT_LED1_CODE, 0, 0, 0);
}

// AFE4490RF is an enum class — cast to int for Unity's integer comparison macros.
static void assert_rf_led1(INCUNEST_AFE4490& afe, AFE4490RF expected) {
    TEST_ASSERT_EQUAL((int)expected, (int)afe.test_hgac_rf_led1());
}

void setUp() {}
void tearDown() {}

// ── Test 1: guard trips and RF steps down after the descent persistence window ──
void test_hgac_descent_after_persistence() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    assert_rf_led1(afe, AFE4490RF::RF_100K);  // constructor default

    feed_saturating_led1(afe, 349);
    assert_rf_led1(afe, AFE4490RF::RF_50K);  // stepped down exactly one LUT level
}

// ── Test 2: debounce — one sample short of the persistence window does not trigger ──
void test_hgac_descent_debounce() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);

    feed_saturating_led1(afe, 348);  // one short of the trigger sample
    assert_rf_led1(afe, AFE4490RF::RF_100K);  // unchanged — no premature action

    feed_saturating_led1(afe, 1);  // sample 349 completes the window
    assert_rf_led1(afe, AFE4490RF::RF_50K);
}

// ── Test 3 (OT-domain experiment): RF change no longer touches the SpO2 EMA ─────
// Before the OT-domain migration, _hgac_step_rf_down() rescaled the SpO2 EmaChannel by
// (mean*k, var*k^2) because the raw-ADC-domain input jumped by k. Now that SpO2 consumes OT
// (gain-invariant), that rescale is unnecessary AND would be wrong if still applied — this
// test proves the EMA state is left untouched by an RF change.
void test_hgac_no_longer_rescales_spo2_ema() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    afe.test_set_spo2_ir_ema(1000.0f, 25.0f);

    afe.test_hgac_step_rf_down_led1(AFE4490RF::RF_50K);  // RF_100K -> RF_50K

    TEST_ASSERT_EQUAL_FLOAT(1000.0f, afe.test_spo2_ir_ema_mean());  // unchanged
    TEST_ASSERT_EQUAL_FLOAT(25.0f,   afe.test_spo2_ir_ema_var());   // unchanged
}

// ── Test 4: Gate G0 blocks actuation during RSQM_DIAG_HW_SETTLING ───────────────
// After the first descent (which arms the settling countdown, 75 samples), continued
// saturation must NOT trigger a second descent until a full fresh persistence window has
// elapsed AFTER settling clears (the gate closing resets the debounce counter — see
// _hgac_update()).
void test_hgac_gate_blocks_during_settling() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);

    feed_saturating_led1(afe, 349);  // 1st descent: RF_100K -> RF_50K, arms settling
    assert_rf_led1(afe, AFE4490RF::RF_50K);

    feed_saturating_led1(afe, 251);  // through settling (350-424) + partial fresh window (425-600)
    assert_rf_led1(afe, AFE4490RF::RF_50K);  // not yet — total 600 < trigger at 674

    feed_saturating_led1(afe, 74);  // total 674: 2nd descent fires
    assert_rf_led1(afe, AFE4490RF::RF_25K);
}

// ── Test 5: gain-floor alarm sets HGAC_DIAG_GAIN_FLOOR once RF bottoms out ──────
void test_hgac_alarm_at_gain_floor() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);

    // 3 descents (RF_100K->50K->25K->10K) at samples 349/674/999, then the alarm's own
    // debounce completes at sample 1324 (see sample-budget model above). Feed extra margin.
    feed_saturating_led1(afe, 1400);

    assert_rf_led1(afe, AFE4490RF::RF_10K);
    TEST_ASSERT_TRUE(afe.test_hgac_alarm_gain_floor());
    TEST_ASSERT_TRUE((afe.test_diag_code() & HGAC_DIAG_GAIN_FLOOR) != 0);
}

// ── Test 6: HGAC disabled (default) never actuates ──────────────────────────────
void test_hgac_disabled_by_default() {
    INCUNEST_AFE4490 afe;  // hgac_enable defaults to false — never call setHgacEnable()

    feed_saturating_led1(afe, 1000);
    assert_rf_led1(afe, AFE4490RF::RF_100K);  // unchanged
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hgac_descent_after_persistence);
    RUN_TEST(test_hgac_descent_debounce);
    RUN_TEST(test_hgac_no_longer_rescales_spo2_ema);
    RUN_TEST(test_hgac_gate_blocks_during_settling);
    RUN_TEST(test_hgac_alarm_at_gain_floor);
    RUN_TEST(test_hgac_disabled_by_default);
    return UNITY_END();
}
