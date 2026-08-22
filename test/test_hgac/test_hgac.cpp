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

// ── An RF change freezes input for the whole settle window, then releases it (v0.72) ──
// _task_body() feeds frozen last-valid raw values while RSQM_DIAG_SWITCHED_RC_SETTLING is active, the
// same mechanism as the post-diagnostic holdoff — enforcing the bit instead of just labelling it.
// _should_freeze_input() (the condition _task_body() checks) is exercised directly here since
// _task_body() itself is SPI/task-only and not testable in the native/offline build.
void test_rf_change_freezes_input_for_settle_window() {
    INCUNEST_AFE4490 afe;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());  // nothing armed yet
    afe.test_hgac_change_rf_led1(AFE4490RF::RF_10K);    // arms _switched_rc_settling_countdown
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
    uint32_t samples = afe.test_compute_switched_rc_settling_samples();
    // Countdown decrements inside _process_sample() (_rsqm_update()) on every sample, frozen or
    // not — feed exactly that many and it must be released, not one earlier or one later.
    for (uint32_t i = 0; i < samples - 1; i++) {
        afe.test_feed_sample(0, 0, 0, 0);
        TEST_ASSERT_TRUE(afe.test_should_freeze_input());
    }
    afe.test_feed_sample(0, 0, 0, 0);
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
}

// ── A manual RF change (not via HGAC) also arms the settle window (v0.74) ──
// Before this, only _hgac_change_rf() armed _switched_rc_settling_countdown - a manual RF change (e.g. a
// $SET,tiagain1,... from the script) got no input-freeze protection at all, even though the same
// physical front-end transient occurs regardless of who changed RF. setTIAGain()/setTIAGainLED1/2()
// now arm it themselves, so a manual change is protected exactly like an HGAC one.
void test_manual_rf_change_also_arms_settling() {
    INCUNEST_AFE4490 afe;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setTIAGainLED1(AFE4490RF::RF_10K);  // manual call, bypassing HGAC entirely
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
}

// ── Re-applying the SAME gain does not spuriously re-arm settling ──
void test_setting_same_gain_does_not_rearm_settling() {
    INCUNEST_AFE4490 afe;                    // RF_100K default
    afe.setTIAGainLED1(AFE4490RF::RF_100K);  // no-op value — nothing actually changed
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setTIAGain(AFE4490RF::RF_100K);      // joint setter, same no-op check
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
}

// ── ILED, AMBDAC, and RG (Stage2 gain) changes also arm the settle window (v0.76) ──
// Datasheet §7.7 t5 footnote (1) names "LED current setting... and so forth" alongside TIA gain
// as triggers for the same switched-RC settling requirement. AMBDAC and RG (Stage 2) share the
// identical feedback path (Eq. 2) as RF, so the same reasoning applies to them too.
void test_led_current_change_arms_settling() {
    INCUNEST_AFE4490 afe;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setLED1Current(10.0f);  // default ~49.8 mA
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
}

void test_ambdac_change_arms_settling() {
    INCUNEST_AFE4490 afe;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setAmbDac(5);  // default 0
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
}

void test_stage2_gain_change_arms_settling() {
    INCUNEST_AFE4490 afe;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setStage2Gain(AFE4490RG::RG_200K);  // default RG_100K (0 dB, bypass-equivalent)
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
}

// ── Re-applying the same ILED/AMBDAC/RG value does not spuriously re-arm settling ──
void test_setting_same_led_ambdac_rg_does_not_rearm_settling() {
    INCUNEST_AFE4490 afe;
    afe.setLED1Current(afe.getConfig().afe_led1_current_mA);
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setAmbDac(0);
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setStage2Gain(AFE4490RG::RG_100K);
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
}

// ── Toggling Stage 2 bypass also arms the settle window (v0.77) ──
// STAGE2EN steps the effective gain between unity (bypassed) and RG (enabled) - the same kind of
// front-end transient as setStage2Gain() itself, just via the enable bit instead of the gain value.
void test_stage2_en_toggle_arms_settling() {
    INCUNEST_AFE4490 afe;
    bool was_en = afe.getConfig().afe_stg2_en_led1;
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
    afe.setStage2En1(!was_en);
    TEST_ASSERT_TRUE(afe.test_should_freeze_input());
}

// ── Re-setting Stage 2 enable to its current value does not spuriously re-arm settling ──
void test_setting_same_stage2_en_does_not_rearm_settling() {
    INCUNEST_AFE4490 afe;
    bool was_en = afe.getConfig().afe_stg2_en_led1;
    afe.setStage2En1(was_en);
    TEST_ASSERT_FALSE(afe.test_should_freeze_input());
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

// ── Changing RF via HGAC recalculates CF for the NEW RF, not left stale from the old one ──
// RF and CF for one color share the SAME 24-bit register (TIAGAIN), written in a single SPI
// transaction inside setTIAGainLED1() — see incunest_afe4490_spec.md §5.8.4 ("CF/RF atomicity").
// This exercises that guarantee through the HGAC entry point specifically (_hgac_change_rf),
// not just the public setTIAGain() already covered by test_tia_cf.cpp.
void test_hgac_change_rf_recalculates_cf() {
    INCUNEST_AFE4490 afe;                                        // RF_100K default, 500 Hz
    TEST_ASSERT_EQUAL_FLOAT(100.0f, afe.getConfig().afe_tia_cf_led1_pF);
    afe.test_hgac_change_rf_led1(AFE4490RF::RF_10K);
    AFE4490Config cfg = afe.getConfig();
    TEST_ASSERT_EQUAL((int)AFE4490RF::RF_10K, (int)cfg.afe_tia_rf_led1);
    TEST_ASSERT_EQUAL_FLOAT(250.0f, cfg.afe_tia_cf_led1_pF);      // clamps to the grid ceiling at RF_10K
    // 5tau <= settle budget holds for the NEW (RF, CF) pairing, not a stale 100K/100pF one.
    const float settle_s = 200.0f / 4000000.0f;                  // 500 Hz LED window margin (see test_tia_cf.cpp)
    float tau_s = kAFE_RF_OHM[(int)AFE4490RF::RF_10K] * cfg.afe_tia_cf_led1_pF * 1e-12f;
    TEST_ASSERT_TRUE(5.0f * tau_s <= settle_s * (1.0f + kAFE_CF_MATCH_TOL));
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
    RUN_TEST(test_rf_change_freezes_input_for_settle_window);
    RUN_TEST(test_manual_rf_change_also_arms_settling);
    RUN_TEST(test_setting_same_gain_does_not_rearm_settling);
    RUN_TEST(test_led_current_change_arms_settling);
    RUN_TEST(test_ambdac_change_arms_settling);
    RUN_TEST(test_stage2_gain_change_arms_settling);
    RUN_TEST(test_setting_same_led_ambdac_rg_does_not_rearm_settling);
    RUN_TEST(test_stage2_en_toggle_arms_settling);
    RUN_TEST(test_setting_same_stage2_en_does_not_rearm_settling);
    RUN_TEST(test_hgac_change_rf_leaves_spo2_ema_untouched);
    RUN_TEST(test_hgac_change_rf_recalculates_cf);
    RUN_TEST(test_hgac_ambient_alarm_at_floor);
    RUN_TEST(test_hgac_led_only_sat_is_probe_in_air);
    return UNITY_END();
}
