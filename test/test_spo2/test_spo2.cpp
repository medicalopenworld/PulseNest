#include <unity.h>
#include <math.h>
#include "incunest_afe4490.h"

// EXPERIMENT (OT-domain input, branch experiment/ot-domain-inputs): SpO2 now consumes OT
// (dimensionless A/A, ~1e-5 typical per incunest_afe4490_spec.md) instead of raw
// ambient-corrected ADC counts. Presence detection (finger/probe applied) is RSQM's
// responsibility alone (ProbeState, passed into _spo2_update()) — SpO2 never computes its own
// no-finger/no-signal classification, only a purely numerical division-safety guard
// (spo2_div_eps). See _spo2_update() rationale in incunest_afe4490.cpp.
//
// Output contract: sqi==0.0f always implies pi==spo2==spo2_r==NaN (never a stale value),
// unified across warmup, PROBE_DISCONNECTED/PROBE_NOT_APPLIED, and the division-safety guard.
//
// (SPO2_A/SPO2_B calibration coefficients and WARMUP_SAMPLES were removed 2026-08-19: both were
// dead code — hardcoded duplicates of incunest_afe4490.cpp's spo2_a_default/spo2_b_default and
// spo2_warmup_s, defined but never referenced by any assertion. If a future test needs them,
// derive from afe.getConfig().spo2_a / .spo2_b / .spo2_warmup_s instead of re-hardcoding, per
// the same fix applied to test_hgac.cpp's WEAK_CODE/SAT_CODE — see conversation_log.md.)
//
// R/SpO2-accuracy tests need much longer than the nominal warmup: the AC^2 EMA (tau_var=6s)
// is fed d=x-mean, and mean (tau_mean=2s) itself has not fully settled either — the
// compounded two-stage IIR settles far slower than the naive 3*tau_var=18s estimate.
// Verified empirically (standalone simulation): R keeps drifting until ~60s (30000 samples)
// from a cold start; converges to within <0.1% of the theoretical value by 40000 samples.
// This is a property of the EMA cascade itself, independent of the OT-domain migration —
// not something this experiment changes or fixes.
static constexpr int CONVERGED_SAMPLES = 40000;

// Typical OT DC magnitude (per spec: APPLIED ~1.4e-5).
static constexpr float OT_DC = 1.4e-5f;

// Helper: feed N samples of dual-channel sines (same freq, different AC amplitude), scaled
// into OT units. IR: DC=OT_DC, AC=a_ir*scale. RED: DC=OT_DC, AC=a_red*scale.
// R = (AC_red/DC)/(AC_ir/DC) = a_red/a_ir (DC cancels, same as the original count-domain test).
static void feed_spo2_sine(INCUNEST_AFE4490& afe,
                            float a_ir, float a_red,
                            float freq_hz, int n_samples,
                            ProbeState probe_state = ProbeState::PROBE_APPLIED) {
    const float fs = 500.0f;
    const float scale = 1.4e-10f;  // brings a_ir~10000-scale amplitudes into OT-DC-scale AC
    for (int i = 0; i < n_samples; i++) {
        float phase = 2.0f * (float)M_PI * freq_hz * i / fs;
        float ot_ir  = OT_DC + a_ir  * scale * sinf(phase);
        float ot_red = OT_DC + a_red * scale * sinf(phase);
        afe.test_feed_spo2(ot_ir, ot_red, probe_state);
    }
}

void setUp() {}
void tearDown() {}

// ── Test 1: not valid during warmup — outputs are NaN, not stale ─────────────
void test_spo2_not_valid_during_warmup() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, 1000);  // well short of warmup
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
    TEST_ASSERT_TRUE(isnan(afe.test_spo2()));
    TEST_ASSERT_TRUE(isnan(afe.test_spo2_r()));
}

// ── Test 2: PROBE_DISCONNECTED/NOT_APPLIED forces invalid + resets state ─────
// SpO2 never classifies presence itself — it only consumes probe_state. Feeding a real,
// already-converged signal, then switching to PROBE_DISCONNECTED must: force sqi=0 and
// pi/spo2/spo2_r to NaN, reset the internal EMAs, and require a fresh warmup once
// probe_state returns to PROBE_APPLIED (no instant resume from stale pre-disconnect state).
void test_spo2_not_applied_resets() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, CONVERGED_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());  // valid before disconnecting

    // Sustained disconnect: probe_state alone must force invalidity, regardless of what OT
    // values are fed (even a plausible-looking DC/AC pair must NOT produce a valid reading).
    for (int i = 0; i < 1000; i++)
        afe.test_feed_spo2(OT_DC, OT_DC, ProbeState::PROBE_DISCONNECTED);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
    TEST_ASSERT_TRUE(isnan(afe.test_spo2()));
    TEST_ASSERT_TRUE(isnan(afe.test_spo2_r()));
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_ir_ema_mean());  // EMA reset, not just gated
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_ir_ema_var());

    // Re-applying (PROBE_APPLIED) must require a fresh warmup, not resume instantly from
    // whatever the pre-disconnect state was.
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, 1000);  // well short of warmup
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
    TEST_ASSERT_TRUE(isnan(afe.test_spo2()));

    // PROBE_NOT_APPLIED gets the same treatment as PROBE_DISCONNECTED (both non-APPLIED).
    for (int i = 0; i < 1000; i++)
        afe.test_feed_spo2(OT_DC, OT_DC, ProbeState::PROBE_NOT_APPLIED);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_ir_ema_mean());
}

// ── Test 3: SpO2 ≈ 98% ───────────────────────────────────────────────────────
// R = (114.9208 - 98) / 30.5547 ≈ 0.5538
// With a_ir=10000, a_red=5538 → R ≈ 0.5538
void test_spo2_98_percent() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 5538.0f, 1.0f, CONVERGED_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 98.0f, afe.test_spo2());
}

// ── Test 4: SpO2 ≈ 90% ───────────────────────────────────────────────────────
// R = (114.9208 - 90) / 30.5547 ≈ 0.8156
// With a_ir=10000, a_red=8156 → R ≈ 0.8156
void test_spo2_90_percent() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 8156.0f, 1.0f, CONVERGED_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(2.0f, 90.0f, afe.test_spo2());
}

// ── Test 5: SpO2 slightly above 100 → clamped to 100 and reported valid ──────
// a_red=4500 → R ≈ 0.45 → raw SpO2 ≈ 101.2 → within clamp margin → 100.0
void test_spo2_clamp_above_100() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 4500.0f, 1.0f, CONVERGED_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 100.0f, afe.test_spo2());
}

// ── Test 6: SpO2 far above 100 → invalid (outside clamp margin) ──────────────
// a_red=3000 → R ≈ 0.30 → raw SpO2 ≈ 105.8 → exceeds clamp margin → invalid
void test_spo2_too_high_invalid() {
    INCUNEST_AFE4490 afe;
    feed_spo2_sine(afe, 10000.0f, 3000.0f, 1.0f, CONVERGED_SAMPLES);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, afe.test_spo2_sqi());
    TEST_ASSERT_TRUE(isnan(afe.test_spo2()));
}

// ── Test 7 (new, OT-domain-specific): R is invariant to a fixed gain scale ───
// If both ot_ir and ot_red were scaled by the same constant k (as an RF change would do to
// the raw-ADC-domain led1_sub/led2_sub, but NOT to OT — this test proves OT already cancels
// it), R and SpO2 must be identical. Demonstrates the OT-domain migration's core claim.
void test_spo2_r_invariant_to_uniform_scale() {
    INCUNEST_AFE4490 afe_a, afe_b;
    feed_spo2_sine(afe_a, 10000.0f, 5538.0f, 1.0f, CONVERGED_SAMPLES);
    // afe_b fed with the SAME OT values scaled by an arbitrary constant (simulating what a
    // gain change would have done in the OLD raw-count domain) — R must match afe_a exactly,
    // because in OT domain a uniform scale is exactly what a real gain change looks like:
    // nothing, since OT is already gain-invariant. This test feeds pre-scaled OT directly
    // (no HGAC involved) to isolate the claim to the SpO2 math itself.
    const float k = 0.37f;  // arbitrary scale factor, would be kAFE_RF_OHM ratio in reality
    const float fs = 500.0f;
    const float scale = 1.4e-10f;
    for (int i = 0; i < CONVERGED_SAMPLES; i++) {
        float phase = 2.0f * (float)M_PI * 1.0f * i / fs;
        float ot_ir  = k * (OT_DC + 10000.0f * scale * sinf(phase));
        float ot_red = k * (OT_DC + 5538.0f  * scale * sinf(phase));
        afe_b.test_feed_spo2(ot_ir, ot_red, ProbeState::PROBE_APPLIED);
    }
    TEST_ASSERT_EQUAL_FLOAT(1.0f, afe_b.test_spo2_sqi());
    TEST_ASSERT_FLOAT_WITHIN(0.05f, afe_a.test_spo2(), afe_b.test_spo2());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, afe_a.test_spo2_r(), afe_b.test_spo2_r());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_spo2_not_valid_during_warmup);
    RUN_TEST(test_spo2_not_applied_resets);
    RUN_TEST(test_spo2_98_percent);
    RUN_TEST(test_spo2_90_percent);
    RUN_TEST(test_spo2_clamp_above_100);
    RUN_TEST(test_spo2_too_high_invalid);
    RUN_TEST(test_spo2_r_invariant_to_uniform_scale);
    return UNITY_END();
}
