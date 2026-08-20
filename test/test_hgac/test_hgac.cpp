#include <unity.h>
#include "incunest_afe4490.h"

// HGAC (RF-only, two EMA per gain domain) — see incunest_afe4490_spec.md §5.8.
//   fast EMA (τ≈0.1 s) → HIGH2 guard (urgent, integrates severity×time)
//   slow EMA (τ≈2 s)   → HIGH1/LOW1 leveling dead-band on the clean DC
// valid() gates each check (no action during an EMA's warmup after a reset); a gain change
// reset()s that domain's EMAs, so the warmup doubles as a cooldown between steps.
//
// v1 physics (AMBDAC=0, Stage2 ×1): v_tia == v_adc = code * (1.2 / 2097151). The tests drive
// a FIXED ADC code (not a photocurrent), so v_tia does NOT fall when RF steps — this lets a
// sustained stimulus walk RF to a rail, which is what the guard/leveling tests rely on.

// Saturating: midpoint between tia_axis::FS_V (opens PROBE_SATURATING) and adc::FSR (the ADC
// rail) — guaranteed above HIGH2 too (tia_axis's own static_assert orders HIGH2_V < FS_V), and
// below the rail (no clipping). Derived from named constants, not a bare magic code, so it can't
// silently drift out of the intended zone if those move (see weak_code_below_low1 below, and
// conversation_log.md 2026-08-19).
static constexpr float   SAT_V    = (tia_axis::FS_V + adc::FSR) / 2.0f;  // ≈ 1.1 V
static constexpr int32_t SAT_CODE = (int32_t)(SAT_V / adc::SCALE);

static void assert_rf1(INCUNEST_AFE4490& afe, AFE4490RF e) {
    TEST_ASSERT_EQUAL((int)e, (int)afe.test_hgac_rf_led1());
}
static void feed(INCUNEST_AFE4490& afe, int32_t code, int n) {
    for (int i = 0; i < n; i++) afe.test_feed_sample(code, code, code, code);
}
// Weak-but-applied ADC code: led==aled → OT=0 → PROBE_APPLIED; v_tia 25% below the object's
// OWN hgac_v_tia_low1 (not a hardcoded voltage), so a future change to that policy default
// can't silently break this test the way it did when LOW1 moved 0.25→0.20 (2026-08-19).
static int32_t weak_code_below_low1(INCUNEST_AFE4490& afe) {
    float weak_v = afe.getConfig().hgac_v_tia_low1 * 0.75f;
    return (int32_t)(weak_v / adc::SCALE);
}

void setUp() {}
void tearDown() {}

// ── Guard (fast EMA, HIGH2): sustained saturation walks RF down to the floor and holds it ──
void test_hgac_guard_descends_to_floor() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    assert_rf1(afe, AFE4490RF::RF_100K);        // constructor default
    feed(afe, SAT_CODE, 4000);
    assert_rf1(afe, AFE4490RF::RF_10K);         // reached and held the RF floor
}

// ── Warmup: nothing acts before the fast EMA matures (valid()==false → no action) ──
void test_hgac_no_action_during_warmup() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    // gate commits ~100 samples; fast warmup = 3·0.1·500 = 150 → first step no earlier than ~250.
    feed(afe, SAT_CODE, 120);
    assert_rf1(afe, AFE4490RF::RF_100K);        // still untouched
}

// ── Disabled by default: never actuates ──
void test_hgac_disabled_by_default() {
    INCUNEST_AFE4490 afe;                        // hgac_enable defaults to false
    feed(afe, SAT_CODE, 4000);
    assert_rf1(afe, AFE4490RF::RF_100K);
}

// ── Leveling (slow EMA, LOW1): a weak-but-applied signal raises RF toward the ceiling ──
void test_hgac_leveling_raises_rf() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    afe.setHgacEmaSlowTauS(0.02f);               // shrink the slow warmup so the test stays short
    feed(afe, weak_code_below_low1(afe), 6000);
    // v_tia 25% below LOW1 → RF raised above the RF_100K default (toward RF_1M).
    TEST_ASSERT_TRUE((int)afe.test_hgac_rf_led1() > (int)AFE4490RF::RF_100K);
}

// ── Changing RF resets this domain's EMAs → a fresh warmup must pass before acting again ──
void test_hgac_change_rf_resets_and_rewarms() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    feed(afe, SAT_CODE, 4000);
    assert_rf1(afe, AFE4490RF::RF_10K);          // at the floor
    afe.test_hgac_change_rf_led1(AFE4490RF::RF_100K);  // force back up: resets EMAs + arms settling
    assert_rf1(afe, AFE4490RF::RF_100K);
    // Right after: settling (~8, datasheet t5 @500Hz) + fresh warmup (150) → 100 saturating
    // samples can't re-descend yet.
    feed(afe, SAT_CODE, 100);
    assert_rf1(afe, AFE4490RF::RF_100K);
}

// ── A gain change leaves the SpO2 EmaChannel untouched (OT-domain: no rescale needed) ──
void test_hgac_change_rf_leaves_spo2_ema_untouched() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    afe.test_set_spo2_ir_ema(1000.0f, 25.0f);
    afe.test_hgac_change_rf_led1(AFE4490RF::RF_50K);   // RF_100K -> RF_50K
    TEST_ASSERT_EQUAL_FLOAT(1000.0f, afe.test_spo2_ir_ema_mean());  // unchanged
    TEST_ASSERT_EQUAL_FLOAT(25.0f,   afe.test_spo2_ir_ema_var());   // unchanged
}

// ── Ambient alarm: at the RF floor with ambient (ALED) also above HIGH2 → AMBIENT_HIGH ──
void test_hgac_ambient_alarm_at_floor() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    afe.setHgacEmaAmbientTauS(0.02f);            // shrink ambient warmup for the test
    // All phases saturate (LED and ALED): the guard walks RF to the floor, and at the floor the
    // ambient EMA is still above HIGH2 → ambient saturates on its own → alarm.
    feed(afe, SAT_CODE, 4000);
    assert_rf1(afe, AFE4490RF::RF_10K);
    TEST_ASSERT_TRUE((afe.test_diag_code() & RSQM_DIAG_AMBIENT_HIGH) != 0);
}

// ── LED-only saturation (ambient phase clean) = probe in air → NOT_APPLIED, HGAC frozen ──
// Option 3 (v0.61): removing the finger saturates the LED phase (its own light reaches the PD
// directly) but NOT the ambient phase, so RSQM classifies it NOT_APPLIED and HGAC must NOT chase
// RF down to the floor — otherwise the reading is ruined for when the finger returns.
void test_hgac_led_only_sat_is_probe_in_air() {
    INCUNEST_AFE4490 afe;
    afe.setHgacEnable(true);
    // LED phases saturate, ambient (ALED) phases clean → probe in air (not an ambient problem).
    for (int i = 0; i < 4000; i++) afe.test_feed_sample(SAT_CODE, SAT_CODE, 0, 0);
    assert_rf1(afe, AFE4490RF::RF_100K);   // NOT_APPLIED → HGAC frozen → RF unchanged from default
    TEST_ASSERT_TRUE((afe.test_diag_code() & RSQM_DIAG_AMBIENT_HIGH) == 0);  // no ambient alarm
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_hgac_guard_descends_to_floor);
    RUN_TEST(test_hgac_no_action_during_warmup);
    RUN_TEST(test_hgac_disabled_by_default);
    RUN_TEST(test_hgac_leveling_raises_rf);
    RUN_TEST(test_hgac_change_rf_resets_and_rewarms);
    RUN_TEST(test_hgac_change_rf_leaves_spo2_ema_untouched);
    RUN_TEST(test_hgac_ambient_alarm_at_floor);
    RUN_TEST(test_hgac_led_only_sat_is_probe_in_air);
    return UNITY_END();
}
