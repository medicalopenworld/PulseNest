// incunest_offline_runner — Offline batch processor for incunest_afe4490 algorithms
// Runner version: v0.25 — native/offline (no hardware), library API v0.99
// Spec: incunest_afe4490_spec.md §9
// Author: Medical Open World — http://medicalopenworld.org — <contact@medicalopenworld.org>
//
// v0.25 (2026-10-04): (1) every replay from raw codes now checks itself against the board: when the
//   capture carries OT_LED1/OT_LED2, the replayed OT of every row is compared with the recorded one
//   and each part prints the largest relative deviation (row and channel) and the share of rows
//   within OT_TOL. The recorded OT has 5 significant figures up to fw 0.16 (rounding <= 5e-5) and 7
//   from fw 0.17, so a deviation above 1e-4 is not rounding: it is a replay that does not reproduce
//   the board (the v0.24 HGAC-record artefacts would have shown x2.5 here). (2) `--input ot`: the
//   algorithms (SpO2, HR1, HR2, HR3 and the R candidates) are fed the recorded OT and the recorded
//   ProbeState, in the production order, skipping the analog reconstruction, RSQM and HGAC — for
//   algorithm experiments whose input must be exactly what the board computed. It needs the
//   ProbeState column (refused, not guessed, when absent; P5 carries it since 2026-10-04). HR2/HR3 run through
//   their synchronous test wrappers here; in the raw-code replay they never run on the host (their
//   slow paths live in FreeRTOS tasks the host HAL does not create), so those columns stay empty there.
//
// v0.24 (2026-10-03): (1) the replay now FOLLOWS the capture's `# @row N afe:` records (v0.4 format):
//   the recorder writes one whenever the board's HGAC changes RF (cause=hgac) and at every part start
//   (cause=part). Until now the library instance kept the header's $CFG for the whole session, so
//   after the first HGAC move it divided the raw codes by the wrong RF: on SUBJ09 the replayed OT_LED2
//   jumped +150 % / -60 % where the board's moved 1-4 %, for 82-89 % of those sessions -- the
//   ProbeState, SQIs and every R transient after such a step were replay artefacts (rationale §9,
//   corrected). Only keys whose value changes are applied, so a record that repeats the current
//   configuration (part starts) does not touch the library's state. The record's row is the row at
//   which the HOST learnt of the change (frames arrive 5 per datagram), measured -4..+4 rows from the
//   raw code's own jump: applied there, one sample of old-RF-on-new-codes (x2.5) went through the
//   filters and the settling freeze held it for 10 more -- a 20 ms spike that polluted the candidate
//   for 30 s after every HGAC move. So an RF change is aligned to the jump of that channel's raw
//   code nearest the record (within +-50 rows, ratio within 30 % of the RF ratio) and the whole
//   record is applied at that row; the summary prints the offset used.
//   (2) DC-estimator experiment for the candidate (library rationale §10): the same
//   regression runs four times, differing only in the DC each channel's band-passed signal is
//   divided by -- the library's EMA (tau 2 s; R_CAND, unchanged), a 2nd-order low-pass at 0.2 Hz
//   critically damped as one biquad (R_CAND_CD) and as two cascaded EMAs of 0.796 s (R_CAND_CE,
//   the same transfer function in the EMA's arithmetic), and Butterworth (R_CAND_BW). Each DC runs
//   in float, as the firmware would, with a double twin alongside; the per-part summary prints the
//   largest relative deviation seen so far in the session, which is what float32 costs with poles
//   this close to z = 1.
//
// v0.23 (2026-10-03): computes the R-method candidate R_CAND_LABEL (causal regression on
//   derivatives, "reg_dols") next to the library, on the very OT samples and ProbeState the
//   library's SpO2 receives, and appends it as R_CAND, with its correlation R_CAND_CORR (r of the
//   derivative regression: ~0.99 with a pulse, ~0 without -- the SQI candidate), to every replay row. Step 2
//   of the R-method plan (library rationale): replay the corpus, check the candidate gets worse
//   nowhere, before it goes into the library. The per-part summary compares both R streams.
//
// v0.22 (2026-10-02): replays with the capture's own R curve through setSpO2RCurve() (lib v0.98):
//   fw >= 0.16 names it in $CFG (spo2_r_curve_*); fw <= 0.15 printed only spo2a/spo2b, read as the
//   MS100 default when they match it and as an explicitly unlabelled curve otherwise.
//
// v0.21 (2026-09-29): output moves out of the session directory, which holds only what was
//   recorded, into <input dir>/derived/replay_lib<ver>[_ot<thr>]/ (--out DIR overrides).
//
// v0.20 (2026-09-24): rewritten for the current library API and the PulseNest capture CSVs.
//   * Feeds raw ADC codes through test_feed_sample() — the full _process_sample() path
//     (analog state -> RSQM -> SpO2/HR1/HR2/HR3), so ProbeState is recomputed by the
//     library itself, debounce included, instead of trusting the recorded column.
//   * Two column dialects, detected by header name: PulseNest captures
//     (LED2,LED1,ALED2,ALED1,...) and legacy IncuNest exports (RED,IR,RED_Amb,...).
//   * Configures the library from the capture's own "# from-board: $CFG,..." header line
//     (PRF, NUMAV, LED currents/range, per-channel RF/CF/RG/STAGE2EN, AMBDAC, SpO2
//     coefficients, filter cutoffs) — no hand-typed configuration to go stale.
//   * --ot-thr <A/A> overrides rsqm_ot_thr for the replay (e.g. 1.0e-4 to reproduce the
//     2026-09-23 firmware for equivalence checking, default = library default).
//   * Parts of one session (<stem>_pNN.csv) share ONE library instance, in order, so
//     filter/EMA state is continuous across part boundaries, as it was on the board.
//   * When the capture carries firmware outputs (SpO2, R, ProbeState) the replay row
//     also emits them and the deltas, for equivalence checking after warm-up.
//
// Host build: the library selects its host HAL by itself (no ESP_PLATFORM); UNIT_TEST
// opens the test_feed_* API.
#include "incunest_afe4490.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

// ── R-method candidate: causal regression on derivatives ("reg_dols") ─────────
// x = BP(ot_ir)/DC_ir, y = BP(ot_red)/DC_red;  R = EMA(dx·dy) / EMA(dx²),  dx = x[n] − x[n−1].
// The derivative weights the systolic upstroke, where both channels move together, and
// de-weights slow venous/motion components; the band-pass removes the out-of-band power that
// inflates R-METHOD-1's red RMS more than its IR RMS. Offline on HOSPNAV SUBJ08/09 (3471 stationary
// pairs): scatter 5.07 -> 1.63 SpO2 points, Spearman rho -0.44 -> -0.80.
// Built only from library pieces, so it can move into the library as is: the band-pass is the
// library's one-biquad BiquadFilter::init_bp (2 poles; a 4-pole Butterworth measured the same,
// 1.62), with its steady-state precharge; DC is an EMA initialised to the first sample, as
// EmaChannel; reset and warm-up (3 × tau_ac) follow _spo2_update(): any ProbeState other than
// PROBE_APPLIED resets, and R is NaN until the warm-up is over.
// Label per the R-method naming (PILAB step numbering): STEP1 1.2 band-pass, STEP2 2.6
// derivative regression, STEP3 3.1 EMA DC.
static const char* R_CAND_LABEL    = "R-METHOD-CAND-1.2(0.5-5Hz)/2.6(6s)/3.1(2s)";
// DC variants (v0.24, rationale §10). 3.2 is PILAB's STEP3 "LPF" slot; "3.1x2" is two EMAs in cascade.
static const char* R_CAND_CD_LABEL = "R-METHOD-CAND-1.2(0.5-5Hz)/2.6(6s)/3.2(LP2 0.2Hz Q0.5)";
static const char* R_CAND_CE_LABEL = "R-METHOD-CAND-1.2(0.5-5Hz)/2.6(6s)/3.1x2(0.796s)";
static const char* R_CAND_BW_LABEL = "R-METHOD-CAND-1.2(0.5-5Hz)/2.6(6s)/3.2(LP2 0.2Hz Q0.707)";
static const float DC_LP_FC_HZ = 0.2f, DC_CE_TAU_S = 0.7957747f;   // 1 / (2*pi*0.2 Hz)

struct CandBiquad {                     // transcription of INCUNEST_AFE4490::BiquadFilter (band-pass)
    float b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0, v1 = 0, v2 = 0;
    bool  precharge = true;
    void init_bp(float f_lo, float f_hi, float fs) {
        float k = 2.0f * fs;
        float o_lo = k * tanf(3.14159265358979f * f_lo / fs);
        float o_hi = k * tanf(3.14159265358979f * f_hi / fs);
        float o0sq = o_lo * o_hi, bw = o_hi - o_lo, d = k * k + bw * k + o0sq;
        b0 = bw * k / d; b1 = 0.0f; b2 = -bw * k / d;
        a1 = 2.0f * (o0sq - k * k) / d; a2 = (k * k - bw * k + o0sq) / d;
    }
    void reset() { v1 = 0.0f; v2 = 0.0f; precharge = true; }
    float process(float x) {
        if (precharge) {
            float denom = 1.0f + a1 + a2;
            float y_ss  = (denom != 0.0f) ? x * (b0 + b1 + b2) / denom : 0.0f;
            v1 = y_ss - b0 * x;
            v2 = b2 * x - a2 * y_ss;
            precharge = false;
        }
        float y = b0 * x + v1;
        v1 = b1 * x - a1 * y + v2;
        v2 = b2 * x - a2 * y;
        return y;
    }
};

// ── DC estimators under test (rationale §10) ──────────────────────────────────
// All are "start at the first sample" (the EMA by construction, the biquads by the library's
// steady-state precharge, whose y_ss = x for a low-pass). T = float is what the firmware would run;
// T = double is the twin that shows what float32 loses when the poles sit this close to z = 1.
template <typename T> struct DcEmaT {                         // EmaChannel's mean: one pole
    float tau_s; T a = 0, dc = 0; bool first = true;
    explicit DcEmaT(float tau) : tau_s(tau) {}
    void init(float fs) { a = (T)1 - std::exp((T)-1 / ((T)tau_s * (T)fs)); reset(); }
    void reset() { first = true; dc = 0; }
    T update(T x) { if (first) { dc = x; first = false; } else dc += a * (x - dc); return dc; }
};
template <typename T> struct DcEma2T {                        // two EMAs in cascade: a double real pole
    DcEmaT<T> s1, s2;
    explicit DcEma2T(float tau) : s1(tau), s2(tau) {}
    void init(float fs) { s1.init(fs); s2.init(fs); }
    void reset() { s1.reset(); s2.reset(); }
    T update(T x) { return s2.update(s1.update(x)); }
};
template <typename T> struct DcLp2T {                         // BiquadFilter::init_lp, DF-II transposed
    float fc_hz, q; T b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0, v1 = 0, v2 = 0; bool precharge = true;
    DcLp2T(float fc, float q_) : fc_hz(fc), q(q_) {}
    void init(float fs) {
        T Ohm = std::tan((T)3.14159265358979 * (T)fc_hz / (T)fs), Ohm2 = Ohm * Ohm, inv_q = (T)1 / (T)q;
        T d = (T)1 + inv_q * Ohm + Ohm2;
        b0 = Ohm2 / d; b1 = (T)2 * b0; b2 = b0;
        a1 = (T)2 * (Ohm2 - (T)1) / d; a2 = ((T)1 - inv_q * Ohm + Ohm2) / d;
        reset();
    }
    void reset() { v1 = 0; v2 = 0; precharge = true; }
    T update(T x) {
        if (precharge) {
            T denom = (T)1 + a1 + a2;
            T y_ss  = denom != (T)0 ? x * (b0 + b1 + b2) / denom : (T)0;
            v1 = y_ss - b0 * x; v2 = b2 * x - a2 * y_ss; precharge = false;
        }
        T y = b0 * x + v1; v1 = b1 * x - a1 * y + v2; v2 = b2 * x - a2 * y;
        return y;
    }
};
template <template <typename> class DC> struct DcChecked {   // float estimator + double twin
    DC<float> f; DC<double> d; double max_rel = 0.0;
    template <typename... A> explicit DcChecked(A... a) : f(a...), d(a...) {}
    void init(float fs) { f.init(fs); d.init(fs); }
    void reset() { f.reset(); d.reset(); }
    float update(float x) {
        float vf = f.update(x); double vd = d.update((double)x);
        if (vd != 0.0) { double rel = std::fabs((double)vf - vd) / std::fabs(vd); if (rel > max_rel) max_rel = rel; }
        return vf;
    }
};

template <typename DC> struct RCand {
    static constexpr float F_LO = 0.5f, F_HI = 5.0f, TAU_AC_S = 6.0f;
    static constexpr float DIV_EPS = 1e-12f;
    CandBiquad bp_ir, bp_red;
    DC dc_ir, dc_red;
    float a_ac = 0, x_prev = 0, y_prev = 0, sxy = 0, sxx = 0, syy = 0;
    float corr = NAN;   // r = sxy / sqrt(sxx*syy) of the last update: ~0.99 with a pulse, ~0 without
    uint32_t count = 0, warmup = 0;

    template <typename... A> explicit RCand(A... a) : dc_ir(a...), dc_red(a...) {}
    void init(float fs) {
        bp_ir.init_bp(F_LO, F_HI, fs); bp_red.init_bp(F_LO, F_HI, fs);
        dc_ir.init(fs); dc_red.init(fs);
        a_ac = 1.0f - expf(-1.0f / (TAU_AC_S * fs));
        warmup = (uint32_t)roundf(3.0f * TAU_AC_S * fs);
        reset();
    }
    void reset() {
        bp_ir.reset(); bp_red.reset(); dc_ir.reset(); dc_red.reset();
        count = 0; sxy = 0.0f; sxx = 0.0f; syy = 0.0f; corr = NAN;
    }
    double dc_max_rel() const { return std::max(dc_ir.max_rel, dc_red.max_rel); }

    float update(float ot_ir, float ot_red, bool applied) {
        if (!applied) { reset(); return NAN; }
        float dci = dc_ir.update(ot_ir), dcr = dc_red.update(ot_red);
        float x = dci > DIV_EPS ? bp_ir.process(ot_ir)  / dci : 0.0f;
        float y = dcr > DIV_EPS ? bp_red.process(ot_red) / dcr : 0.0f;
        if (count > 0) {
            float dx = x - x_prev, dy = y - y_prev;
            sxy += a_ac * (dx * dy - sxy);
            sxx += a_ac * (dx * dx - sxx);
            syy += a_ac * (dy * dy - syy);
        }
        x_prev = x; y_prev = y; count++;
        if (count < warmup || sxx <= DIV_EPS * DIV_EPS || syy <= DIV_EPS * DIV_EPS) { corr = NAN; return NAN; }
        corr = sxy / sqrtf(sxx * syy);
        return sxy / sxx;
    }
};

struct CandSet {   // the same regression over four DC estimators, fed the same samples
    RCand<DcChecked<DcEmaT>>  ema{2.0f};
    RCand<DcChecked<DcLp2T>>  cd{DC_LP_FC_HZ, 0.5f};
    RCand<DcChecked<DcEma2T>> ce{DC_CE_TAU_S};
    RCand<DcChecked<DcLp2T>>  bw{DC_LP_FC_HZ, 0.70710678f};
    void init(float fs) { ema.init(fs); cd.init(fs); ce.init(fs); bw.init(fs); }
};

// ── CSV row (raw signals + optional firmware outputs) ─────────────────────────
struct CsvRow {
    int32_t led1    = 0;  // IR raw        (PulseNest LED1  / IncuNest IR)
    int32_t led2    = 0;  // RED raw       (PulseNest LED2  / IncuNest RED)
    int32_t aled1   = 0;  // IR ambient    (PulseNest ALED1 / IncuNest IR_Amb)
    int32_t aled2   = 0;  // RED ambient   (PulseNest ALED2 / IncuNest RED_Amb)
    bool    has_fw  = false;
    float   fw_spo2 = 0.0f;
    float   fw_r    = 0.0f;
    int     fw_ps   = -1;
    float   ot1     = NAN;   // recorded OT_LED1 / OT_LED2 [A/A]; NAN when the capture has no such column
    float   ot2     = NAN;
};

static const double OT_TOL = 1e-4;   // relative; 5-figure rounding is <= 5e-5

static std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c){ return std::tolower(c); });
    return s;
}

static std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> cols;
    std::stringstream ss(line);
    std::string cell;
    while (std::getline(ss, cell, ',')) {
        size_t start = cell.find_first_not_of(" \t\r\n");
        size_t end   = cell.find_last_not_of(" \t\r\n");
        cols.push_back(start == std::string::npos ? "" : cell.substr(start, end - start + 1));
    }
    return cols;
}

// ── $CFG header → key/value map ───────────────────────────────────────────────
// The capture header carries the exact board configuration:
//   # from-board: $CFG,sr=500,numav=8,led1=49.80,...,spo2_r_curve_b=30.5547,...*67 (fw <= 0.15: spo2b=)
static std::map<std::string, std::string> parse_cfg_line(const std::string& line) {
    std::map<std::string, std::string> kv;
    size_t at = line.find("$CFG,");
    if (at == std::string::npos) return kv;
    std::string body = line.substr(at + 5);
    size_t star = body.rfind('*');          // NMEA-style checksum, not a value
    if (star != std::string::npos) body = body.substr(0, star);
    for (const auto& tok : split_csv(body)) {
        size_t eq = tok.find('=');
        if (eq != std::string::npos)
            kv[to_lower(tok.substr(0, eq))] = tok.substr(eq + 1);
    }
    return kv;
}

static AFE4490RF rf_from_string(const std::string& s, bool* ok) {
    static const std::map<std::string, AFE4490RF> m = {
        {"10k", AFE4490RF::RF_10K},  {"25k", AFE4490RF::RF_25K},
        {"50k", AFE4490RF::RF_50K},  {"100k", AFE4490RF::RF_100K},
        {"250k", AFE4490RF::RF_250K},{"500k", AFE4490RF::RF_500K},
        {"1m", AFE4490RF::RF_1M},
    };
    auto it = m.find(to_lower(s));
    *ok = (it != m.end());
    return *ok ? it->second : AFE4490RF::RF_500K;
}

static AFE4490RG rg_from_ohms(long ohms, bool* ok) {
    *ok = true;
    switch (ohms) {
        case 100000: return AFE4490RG::RG_100K;
        case 150000: return AFE4490RG::RG_150K;
        case 200000: return AFE4490RG::RG_200K;
        case 300000: return AFE4490RG::RG_300K;
        case 400000: return AFE4490RG::RG_400K;
    }
    *ok = false;
    return AFE4490RG::RG_100K;
}

// Apply the capture's $CFG to a fresh library instance. Returns false (with a message)
// if a value it does not understand shows up — refuse to replay with a wrong config.
static bool apply_cfg(INCUNEST_AFE4490& afe, const std::map<std::string, std::string>& cfg,
                      const char* label) {
    auto has = [&](const char* k) { return cfg.count(k) > 0; };
    auto s   = [&](const char* k) { return cfg.at(k); };
    auto f   = [&](const char* k) { return std::stof(cfg.at(k)); };
    auto l   = [&](const char* k) { return std::stol(cfg.at(k)); };
    bool ok = true;

    if (has("sr"))     afe.setSampleRate((uint16_t)l("sr"));
    if (has("numav"))  afe.setAdcAverages((uint8_t)l("numav"));
    if (has("range"))  afe.setLEDRange((uint8_t)l("range"));
    if (has("led1"))   afe.setLED1Current(f("led1"));
    if (has("led2"))   afe.setLED2Current(f("led2"));
    if (has("ensepgain")) afe.setEnSepGain(l("ensepgain") != 0);
    if (has("tia1"))   { afe.setTIAGainLED1(rf_from_string(s("tia1"), &ok));
                         if (!ok) { fprintf(stderr, "ERROR: %s: unknown tia1=%s\n", label, s("tia1").c_str()); return false; } }
    if (has("tia2"))   { afe.setTIAGainLED2(rf_from_string(s("tia2"), &ok));
                         if (!ok) { fprintf(stderr, "ERROR: %s: unknown tia2=%s\n", label, s("tia2").c_str()); return false; } }
    if (has("cf1_pf")) afe.setTIACFLED1(f("cf1_pf"));
    if (has("cf2_pf")) afe.setTIACFLED2(f("cf2_pf"));
    if (has("rg1_ohm")) { afe.setStage2GainLED1(rg_from_ohms(l("rg1_ohm"), &ok));
                          if (!ok) { fprintf(stderr, "ERROR: %s: unknown rg1_ohm=%s\n", label, s("rg1_ohm").c_str()); return false; } }
    if (has("rg2_ohm")) { afe.setStage2GainLED2(rg_from_ohms(l("rg2_ohm"), &ok));
                          if (!ok) { fprintf(stderr, "ERROR: %s: unknown rg2_ohm=%s\n", label, s("rg2_ohm").c_str()); return false; } }
    if (has("stage2en1")) afe.setStage2En1(l("stage2en1") != 0);
    if (has("stage2en2")) afe.setStage2En2(l("stage2en2") != 0);
    if (has("ambdac")) afe.setAmbDac((uint8_t)l("ambdac"));
    // The R curve the board used. fw >= 0.16 names it (spo2_r_curve_*); fw <= 0.15 printed only the
    // coefficients (spo2a/spo2b), and the one curve such firmware ever shipped is the MS100 default —
    // anything else is replayed under an explicit "unlabelled" id rather than a guessed one.
    if (has("spo2_r_curve_id") && has("spo2_r_curve_r_method_id")
        && has("spo2_r_curve_a") && has("spo2_r_curve_b")) {
        if (!afe.setSpO2RCurve(s("spo2_r_curve_id").c_str(), s("spo2_r_curve_r_method_id").c_str(),
                               f("spo2_r_curve_a"), f("spo2_r_curve_b"))) {
            fprintf(stderr, "ERROR: %s: invalid R curve in $CFG\n", label);
            return false;
        }
    } else if (has("spo2a") && has("spo2b")) {
        bool is_default = fabsf(f("spo2a") - 114.9208f) < 1e-3f && fabsf(f("spo2b") - 30.5547f) < 1e-3f;
        afe.setSpO2RCurve(is_default ? "R-CURVE-U401D-MS100-20260323" : "R-CURVE-UNLABELLED-FW-0.15",
                          is_default ? "R-METHOD-0" : "R-METHOD-UNKNOWN", f("spo2a"), f("spo2b"));
    }
    if (has("fl") && has("fh"))    afe.setPPGDispFilter(f("fl"), f("fh"));
    if (has("hr2l") && has("hr2h")) afe.setHR2Filter(f("hr2l"), f("hr2h"));
    if (has("hr3h"))   afe.setHR3Filter(f("hr3h"));
    return true;
}

// ── Column dialects ───────────────────────────────────────────────────────────
struct ColIdx {
    int led1 = -1, led2 = -1, aled1 = -1, aled2 = -1;
    int fw_spo2 = -1, fw_r = -1, fw_ps = -1;
    int ot1 = -1, ot2 = -1;
    bool valid() const { return led1 >= 0 && led2 >= 0 && aled1 >= 0 && aled2 >= 0; }
    bool has_ot() const { return ot1 >= 0 && ot2 >= 0; }
};

static ColIdx find_columns(const std::vector<std::string>& header) {
    ColIdx ix;
    for (int i = 0; i < (int)header.size(); i++) {
        std::string c = to_lower(header[i]);
        // PulseNest capture dialect
        if      (c == "led1")  ix.led1  = i;
        else if (c == "led2")  ix.led2  = i;
        else if (c == "aled1") ix.aled1 = i;
        else if (c == "aled2") ix.aled2 = i;
        else if (c == "spo2")  ix.fw_spo2 = i;
        else if (c == "r")     ix.fw_r  = i;
        else if (c == "probestate") ix.fw_ps = i;
        else if (c == "ot_led1") ix.ot1 = i;
        else if (c == "ot_led2") ix.ot2 = i;
        // Legacy IncuNest dialect
        else if (c == "ir")      ix.led1  = i;
        else if (c == "red")     ix.led2  = i;
        else if (c == "ir_amb")  ix.aled1 = i;
        else if (c == "red_amb") ix.aled2 = i;
        else if (c == "fw_spo2") ix.fw_spo2 = i;
        // Firmware outputs prefixed FW_ (recorder captures of 2026-09-22 and earlier)
        else if (c == "fw_r")          ix.fw_r  = i;
        else if (c == "fw_probestate") ix.fw_ps = i;
        else if (c == "fw_ot_led1")    ix.ot1   = i;
        else if (c == "fw_ot_led2")    ix.ot2   = i;
    }
    return ix;
}

// ── `# @row N afe: cause=... afe_rf2_ohm=250000 ...` → the board's analog configuration from data
// row N on (0-based within the part). Applied in replay_part() before feeding that row.
struct AfeRecord {
    long row = 0;
    std::map<std::string, std::string> kv;   // afe_* keys as written
};

static bool parse_afe_record(const std::string& line, AfeRecord* rec) {
    // "# @row 126570 afe: cause=hgac afe_prf_hz=500 ... afe_rf2_ohm=250000 ..."
    if (line.rfind("# @row ", 0) != 0) return false;
    size_t sp = line.find(' ', 7);
    if (sp == std::string::npos || line.compare(sp, 6, " afe: ") != 0) return false;
    try { rec->row = std::stol(line.substr(7, sp - 7)); } catch (...) { return false; }
    std::stringstream ss(line.substr(sp + 6));
    std::string tok;
    while (ss >> tok) {
        size_t eq = tok.find('=');
        if (eq != std::string::npos && tok.rfind("afe_", 0) == 0)
            rec->kv[tok.substr(0, eq)] = tok.substr(eq + 1);
    }
    return !rec->kv.empty();
}

static AFE4490RF rf_from_ohms(long ohms, bool* ok) {
    *ok = true;
    switch (ohms) {
        case 10000:   return AFE4490RF::RF_10K;
        case 25000:   return AFE4490RF::RF_25K;
        case 50000:   return AFE4490RF::RF_50K;
        case 100000:  return AFE4490RF::RF_100K;
        case 250000:  return AFE4490RF::RF_250K;
        case 500000:  return AFE4490RF::RF_500K;
        case 1000000: return AFE4490RF::RF_1M;
    }
    *ok = false;
    return AFE4490RF::RF_500K;
}

// Apply the keys of `rec` whose value differs from `state` (the configuration the instance has);
// `state` is updated. Returns the number of changes applied; unknown values are reported, not applied.
static int apply_afe_record(INCUNEST_AFE4490& afe, const AfeRecord& rec,
                            std::map<std::string, std::string>& state, const char* label) {
    int n = 0;
    for (const auto& [k, v] : rec.kv) {
        auto it = state.find(k);
        if (it != state.end() && it->second == v) continue;
        bool ok = true;
        long l = 0; float f = 0.0f;
        try { f = std::stof(v); l = std::lround(f); } catch (...) { ok = false; }
        if (ok) {
            if      (k == "afe_rf1_ohm")       { AFE4490RF rf = rf_from_ohms(l, &ok); if (ok) afe.setTIAGainLED1(rf); }
            else if (k == "afe_rf2_ohm")       { AFE4490RF rf = rf_from_ohms(l, &ok); if (ok) afe.setTIAGainLED2(rf); }
            else if (k == "afe_cf1_pf")        afe.setTIACFLED1(f);
            else if (k == "afe_cf2_pf")        afe.setTIACFLED2(f);
            else if (k == "afe_rg1_ohm")       { AFE4490RG rg = rg_from_ohms(l, &ok); if (ok) afe.setStage2GainLED1(rg); }
            else if (k == "afe_rg2_ohm")       { AFE4490RG rg = rg_from_ohms(l, &ok); if (ok) afe.setStage2GainLED2(rg); }
            else if (k == "afe_stg2en1")       afe.setStage2En1(l != 0);
            else if (k == "afe_stg2en2")       afe.setStage2En2(l != 0);
            else if (k == "afe_ambdac_ua")     afe.setAmbDac((uint8_t)l);
            else if (k == "afe_iled1_ua")      afe.setLED1Current(f / 1000.0f);
            else if (k == "afe_iled2_ua")      afe.setLED2Current(f / 1000.0f);
            else if (k == "afe_iled_range_ma") afe.setLEDRange((uint8_t)l);
            else if (k == "afe_sep_gain")      afe.setEnSepGain(l != 0);
            else if (k == "afe_prf_hz")        afe.setSampleRate((uint16_t)l);
            else if (k == "afe_numav")         afe.setAdcAverages((uint8_t)l);
            else continue;                      // afe_ri_ohm and the like: nothing to set
        }
        if (!ok) { fprintf(stderr, "WARNING: %s: @row %ld %s=%s not understood, not applied\n", label, rec.row, k.c_str(), v.c_str()); continue; }
        state[k] = v;
        n++;
    }
    return n;
}

// Row at which channel `ch` (0 = LED1, 1 = LED2) of `rows` jumps by about `k` (new RF / old RF),
// searched within +-ALIGN_W rows of `row`: the first row of the new gain. -1 when no such jump.
static const long ALIGN_W = 50;
static long align_rf_change(const std::vector<CsvRow>& rows, long row, int ch, double k) {
    long best = -1; double best_err = 1e9;
    const double lk = std::log(k);
    long lo = std::max<long>(1, row - ALIGN_W), hi = std::min<long>((long)rows.size() - 1, row + ALIGN_W);
    for (long j = lo; j <= hi; j++) {
        double a = ch ? rows[j - 1].led2 : rows[j - 1].led1, b = ch ? rows[j].led2 : rows[j].led1;
        if (std::fabs(a) < 1000.0 || std::fabs(b) < 1000.0 || (a > 0) != (b > 0)) continue;
        double err = std::fabs(std::log(b / a) - lk);
        if (err < best_err) { best_err = err; best = j; }
    }
    return (best >= 0 && best_err < std::log(1.3)) ? best : -1;
}

// The board's own RF change happened before that jump: its settling freeze repeats the last sample's
// four codes into the capture, so the jump follows a run of identical rows. Returns the first
// repeated row of the run that ends at `jump` (where the board changed RF), or `jump` if there is none.
static long held_run_start(const std::vector<CsvRow>& rows, long jump) {
    auto same = [&](long a, long b) {
        return rows[a].led1 == rows[b].led1 && rows[a].led2 == rows[b].led2 &&
               rows[a].aled1 == rows[b].aled1 && rows[a].aled2 == rows[b].aled2;
    };
    long h = jump;
    while (h - 2 >= 0 && jump - h < ALIGN_W && same(h - 1, h - 2)) h--;
    return h;
}

// When no jump can be seen (the LED codes clip at full scale before and after the change), the held
// run alone marks the board's change: the first repeated row of the run nearest `row` within
// +-ALIGN_W. Four codes repeating exactly does not happen with a live signal (ambient noise alone
// moves them). -1 when there is none.
static long nearest_held_run(const std::vector<CsvRow>& rows, long row) {
    long best = -1;
    long lo = std::max<long>(1, row - ALIGN_W), hi = std::min<long>((long)rows.size() - 1, row + ALIGN_W);
    for (long k = lo; k <= hi; k++) {
        const bool rep  = rows[k].led1 == rows[k - 1].led1 && rows[k].led2 == rows[k - 1].led2 &&
                          rows[k].aled1 == rows[k - 1].aled1 && rows[k].aled2 == rows[k - 1].aled2;
        const bool prev = k >= 2 && rows[k - 1].led1 == rows[k - 2].led1 && rows[k - 1].led2 == rows[k - 2].led2 &&
                          rows[k - 1].aled1 == rows[k - 2].aled1 && rows[k - 1].aled2 == rows[k - 2].aled2;
        if (rep && !prev && (best < 0 || std::labs(k - row) < std::labs(best - row))) best = k;
    }
    return best;
}

// ── Parse one CSV part: rows + (first seen) $CFG map + the part's afe records ─
static bool parse_csv(const fs::path& path, std::vector<CsvRow>& rows,
                      std::map<std::string, std::string>& cfg, std::vector<AfeRecord>& afe_recs,
                      bool input_ot) {
    std::ifstream f(path);
    if (!f.is_open()) {
        fprintf(stderr, "ERROR: cannot open %s\n", path.string().c_str());
        return false;
    }
    std::string line;
    ColIdx ix;
    bool have_header = false;
    while (std::getline(f, line)) {
        if (line.empty()) continue;
        if (line[0] == '#') {
            if (cfg.empty() && line.find("$CFG,") != std::string::npos)
                cfg = parse_cfg_line(line);
            AfeRecord rec;
            if (parse_afe_record(line, &rec)) afe_recs.push_back(rec);
            continue;
        }
        if (!have_header) {
            ix = find_columns(split_csv(line));
            if (input_ot && !(ix.has_ot() && ix.fw_ps >= 0)) {
                fprintf(stderr, "ERROR: %s: --input ot needs the OT_LED1, OT_LED2 and ProbeState columns "
                        "(P5 captures before 2026-10-04 afternoon lack ProbeState)\n", path.string().c_str());
                return false;
            }
            if (!input_ot && !ix.valid()) {
                fprintf(stderr, "ERROR: %s is missing the raw ADC columns "
                        "(LED1/LED2/ALED1/ALED2 or IR/RED/IR_Amb/RED_Amb)\n",
                        path.string().c_str());
                return false;
            }
            have_header = true;
            continue;
        }
        auto c2 = split_csv(line);
        int n = (int)c2.size();
        auto get_i32 = [&](int idx) -> int32_t {
            if (idx < 0 || idx >= n) return 0;
            try { return (int32_t)std::stol(c2[idx]); } catch (...) { return 0; }
        };
        auto get_f32 = [&](int idx, float dflt) -> float {
            if (idx < 0 || idx >= n) return dflt;
            try { return std::stof(c2[idx]); } catch (...) { return dflt; }
        };
        CsvRow row;
        row.led1  = get_i32(ix.led1);
        row.led2  = get_i32(ix.led2);
        row.aled1 = get_i32(ix.aled1);
        row.aled2 = get_i32(ix.aled2);
        row.has_fw = (ix.fw_spo2 >= 0);
        if (row.has_fw) {
            row.fw_spo2 = get_f32(ix.fw_spo2, NAN);
            row.fw_r    = get_f32(ix.fw_r, NAN);
        }
        if (ix.fw_ps >= 0) row.fw_ps = (int)get_i32(ix.fw_ps);
        if (ix.has_ot()) {
            row.ot1 = get_f32(ix.ot1, NAN);
            row.ot2 = get_f32(ix.ot2, NAN);
        }
        rows.push_back(row);
    }
    return !rows.empty();
}

// ── Replay one part through an already-configured library instance ───────────
struct PartStats {
    int n = 0, probe_on = 0, spo2_producing = 0, ps_match = 0, ps_compared = 0;
    std::vector<float> r_lib, r_cand;   // both finite on the same sample
    std::vector<float> r_cd, r_ce, r_bw;   // the DC variants, where finite
    int lib_valid = 0, cand_valid = 0;
    double lib_cand_max_abs = 0.0;       // max |R_lib − R_CAND| where both finite (lib v0.100: same method)
    // Replayed vs recorded OT (raw-code replay of a capture with OT columns)
    long ot_compared = 0, ot_within = 0, ot_max_row = -1;
    int  ot_max_ch = 0;
    double ot_max_rel = 0.0;
    long missing_ot = 0;                 // --input ot: rows without a recorded OT, fed as not applied
    long ot_startup = 0;                 // rows of the replay's cold-start freeze, not compared
};

static void compare_ot(PartStats& st, long row, int ch, float replayed, float recorded) {
    if (!std::isfinite(recorded) || recorded == 0.0f || !std::isfinite(replayed)) return;
    double rel = std::fabs((double)replayed - recorded) / std::fabs((double)recorded);
    st.ot_compared++;
    if (rel <= OT_TOL) st.ot_within++;
    if (rel > st.ot_max_rel) { st.ot_max_rel = rel; st.ot_max_row = row; st.ot_max_ch = ch; }
}

static float pct(std::vector<float> v, float q) {
    if (v.empty()) return NAN;
    size_t i = (size_t)(q * (v.size() - 1));
    std::nth_element(v.begin(), v.begin() + i, v.end());
    return v[i];
}

static PartStats replay_part(INCUNEST_AFE4490& afe, CandSet& cand, const std::vector<CsvRow>& rows,
                             const std::vector<AfeRecord>& afe_recs, std::map<std::string, std::string>& afe_state,
                             const fs::path& out_path, long long* smp_idx, int* afe_changes,
                             bool input_ot, bool* ot_live) {
    std::ofstream out(out_path);
    PartStats st;
    if (!out.is_open()) {
        fprintf(stderr, "ERROR: cannot write %s\n", out_path.string().c_str());
        return st;
    }
    bool has_fw = rows[0].has_fw;
    out << "SmpIdx,ProbeState,OT_LED1,OT_LED2,R,R_CORR,PI,SpO2,SpO2_SQI,"
           "HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI";
    if (has_fw) out << ",FW_SpO2,FW_R,FW_ProbeState,delta_SpO2,delta_R";
    out << ",R_CAND,R_CAND_CORR,R_CAND_CD,R_CAND_CD_CORR,R_CAND_CE,R_CAND_CE_CORR,R_CAND_BW,R_CAND_BW_CORR\n";
    char buf[512];
    // Where each record really applies: an RF change is aligned to the raw code's jump (see header).
    std::vector<long> apply_row(afe_recs.size());
    {
        std::map<std::string, std::string> st = afe_state;
        for (size_t i = 0; i < afe_recs.size(); i++) {
            const AfeRecord& rec = afe_recs[i];
            apply_row[i] = rec.row;
            if (!input_ot && !st.empty()) {
                for (int ch = 0; ch < 2; ch++) {
                    const char* key = ch ? "afe_rf2_ohm" : "afe_rf1_ohm";
                    auto n = rec.kv.find(key); auto o = st.find(key);
                    if (n == rec.kv.end() || o == st.end() || n->second == o->second) continue;
                    double k = std::stod(n->second) / std::stod(o->second);
                    long j = align_rf_change(rows, rec.row, ch, k);
                    long h = j >= 0 ? held_run_start(rows, j) : nearest_held_run(rows, rec.row);
                    std::string how =
                        j >= 0 ? "jump at " + std::to_string(j - rec.row) + " rows after " +
                                 std::to_string(j - h) + " held rows; applied at " + std::to_string(h - rec.row)
                      : h >= 0 ? "jump NOT FOUND (codes clipped?); held run at " + std::to_string(h - rec.row) +
                                 " rows; applied there"
                               : "jump and held run NOT FOUND within +-50 rows; applied at the record's row";
                    printf("      afe record @row %ld: %s %s -> %s, raw %s %s\n", rec.row, key,
                           o->second.c_str(), n->second.c_str(), ch ? "LED2" : "LED1", how.c_str());
                    if (h >= 0) apply_row[i] = h;
                    break;      // both channels in one record change on the same row
                }
            }
            for (const auto& [k2, v2] : rec.kv) st[k2] = v2;
        }
    }
    size_t next_rec = 0;
    long row_i = 0;
    for (const CsvRow& r : rows) {
        while (next_rec < afe_recs.size() && apply_row[next_rec] <= row_i) {
            if (afe_state.empty()) {            // the session's first record describes the $CFG already applied
                afe_state = afe_recs[next_rec].kv;
            } else if (input_ot) {
                // The recorded OT already carries every analog change; of a record only the sample
                // rate still matters to the algorithms.
                AfeRecord prf_only;
                prf_only.row = afe_recs[next_rec].row;
                auto it = afe_recs[next_rec].kv.find("afe_prf_hz");
                if (it != afe_recs[next_rec].kv.end()) prf_only.kv[it->first] = it->second;
                *afe_changes += apply_afe_record(afe, prf_only, afe_state,
                                                 out_path.filename().string().c_str());
            } else {
                *afe_changes += apply_afe_record(afe, afe_recs[next_rec], afe_state,
                                                 out_path.filename().string().c_str());
            }
            next_rec++;
        }
        const long part_row = row_i++;
        ProbeState ps_e;
        float oi, orr;   // the OT the algorithms receive this sample
        if (input_ot) {
            // Production order (_process_sample): SpO2, HR1, HR2 fast path, HR3 fast path. A row with
            // no recorded OT is fed as not applied: the algorithms reset rather than invent a value.
            const bool have = std::isfinite(r.ot1) && std::isfinite(r.ot2);
            if (!have) st.missing_ot++;
            ps_e = have ? (ProbeState)r.fw_ps : ProbeState::PROBE_DISCONNECTED;
            oi  = have ? r.ot1 : 0.0f;
            orr = have ? r.ot2 : 0.0f;
            afe.test_feed_spo2(oi, orr, ps_e);
            afe.test_feed_hr1(oi, ps_e);
            afe.test_feed_hr2(oi, ps_e);
            afe.test_feed_hr3(oi, ps_e);
        } else {
            afe.test_feed_sample(r.led1, r.led2, r.aled1, r.aled2);
            ps_e = afe.test_probe_state();
            // What _spo2_update() saw: the last valid analog state's OT (frozen while settling).
            oi  = afe.test_last_ot_led1();
            orr = afe.test_last_ot_led2();
            // A fresh instance starts in its settling freeze holding OT = 0, while the board had been
            // running for a while: compare from the session's first live sample on.
            if (!*ot_live && (oi != 0.0f || orr != 0.0f)) *ot_live = true;
            if (*ot_live) {
                compare_ot(st, part_row, 1, oi, r.ot1);
                compare_ot(st, part_row, 2, orr, r.ot2);
            } else if (std::isfinite(r.ot1)) {
                st.ot_startup++;
            }
        }
        int   ps   = (int)ps_e;
        float spo2 = afe.test_spo2();
        float rr   = afe.test_spo2_r();
        snprintf(buf, sizeof(buf),
                 "%lld,%d,%.7g,%.7g,%.5f,%.4f,%.3g,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f",
                 *smp_idx, ps, oi, orr,
                 rr, afe.test_spo2_r_corr(), afe.test_pi(), spo2, afe.test_spo2_sqi(),
                 afe.test_hr1(), afe.test_hr1_sqi(),
                 afe.test_hr2(), afe.test_hr2_sqi(),
                 afe.test_hr3(), afe.test_hr3_sqi());
        out << buf;
        if (has_fw) {
            snprintf(buf, sizeof(buf), ",%.2f,%.5f,%d,%.2f,%.5f",
                     r.fw_spo2, r.fw_r, r.fw_ps,
                     spo2 - r.fw_spo2, rr - r.fw_r);
            out << buf;
            if (!input_ot && r.fw_ps >= 0) {    // in --input ot the ProbeState IS the recorded one
                st.ps_compared++;
                if (ps == r.fw_ps) st.ps_match++;
            }
        }
        // The candidate sees what _spo2_update() saw: the same OT and the same ProbeState.
        const bool  applied = ps == (int)ProbeState::PROBE_APPLIED;
        float rc  = cand.ema.update(oi, orr, applied);
        float rcd = cand.cd.update(oi, orr, applied);
        float rce = cand.ce.update(oi, orr, applied);
        float rbw = cand.bw.update(oi, orr, applied);
        snprintf(buf, sizeof(buf), ",%.5f,%.4f,%.5f,%.4f,%.5f,%.4f,%.5f,%.4f\n",
                 rc, cand.ema.corr, rcd, cand.cd.corr, rce, cand.ce.corr, rbw, cand.bw.corr);
        out << buf;
        if (std::isfinite(rcd)) st.r_cd.push_back(rcd);
        if (std::isfinite(rce)) st.r_ce.push_back(rce);
        if (std::isfinite(rbw)) st.r_bw.push_back(rbw);
        if (std::isfinite(rr)) st.lib_valid++;
        if (std::isfinite(rc)) st.cand_valid++;
        if (std::isfinite(rr) && std::isfinite(rc)) {
            st.r_lib.push_back(rr); st.r_cand.push_back(rc);
            st.lib_cand_max_abs = std::max(st.lib_cand_max_abs, std::fabs((double)rr - rc));
        }
        (*smp_idx)++;
        st.n++;
        if (ps == 1 || ps == 2) st.probe_on++;
        if (spo2 > 1.0f) st.spo2_producing++;
    }
    return st;
}

// ── Main ──────────────────────────────────────────────────────────────────────
int main(int argc, char* argv[]) {
    static const char* USAGE =
        "Usage: incunest_offline_runner <file.csv | directory> [--ot-thr <A/A>] [--input raw|ot] [--out DIR]\n";
    fs::path target;
    fs::path out_dir;
    std::string ot_arg;
    float ot_thr = -1.0f;   // <0 = keep library default
    bool input_ot = false;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--ot-thr") == 0 && i + 1 < argc) {
            ot_arg = argv[++i];
            ot_thr = std::stof(ot_arg);
        } else if (std::strcmp(argv[i], "--input") == 0 && i + 1 < argc) {
            std::string v = to_lower(argv[++i]);
            if (v != "raw" && v != "ot") { fprintf(stderr, "%s", USAGE); return 1; }
            input_ot = (v == "ot");
        } else if (std::strcmp(argv[i], "--out") == 0 && i + 1 < argc) {
            out_dir = argv[++i];
        } else if (target.empty()) {
            target = argv[i];
        } else {
            fprintf(stderr, "%s", USAGE);
            return 1;
        }
    }
    if (target.empty() || !fs::exists(target)) {
        fprintf(stderr, "%s", USAGE);
        return 1;
    }
    if (input_ot && ot_thr > 0) {
        fprintf(stderr, "--ot-thr acts on the RSQM, which --input ot bypasses (it uses the recorded ProbeState)\n");
        return 1;
    }
    // The session directory holds only what was recorded: a replay is derived, and is named
    // by what it depends on, so another library version or threshold never overwrites it.
    if (out_dir.empty()) {
        fs::path base = fs::is_directory(target) ? target : target.parent_path();
        std::string name = std::string("replay_lib") + INCUNEST_AFE4490_VERSION;
        if (ot_thr > 0) name += "_ot" + ot_arg;
        if (input_ot) name += "_inputot";
        out_dir = base / "derived" / name;
    }
    std::error_code ec;
    fs::create_directories(out_dir, ec);
    if (ec) {
        fprintf(stderr, "cannot create %s: %s\n", out_dir.string().c_str(), ec.message().c_str());
        return 1;
    }

    // Collect input CSVs (skip our own outputs)
    std::vector<fs::path> files;
    if (fs::is_directory(target)) {
        for (const auto& e : fs::directory_iterator(target)) {
            std::string name = e.path().filename().string();
            if (e.is_regular_file() &&
                to_lower(e.path().extension().string()) == ".csv" &&
                name.find("_replay") == std::string::npos &&
                name.find("_result") == std::string::npos &&
                to_lower(name).find("reference_spo2") == std::string::npos &&
                to_lower(name).find("events") == std::string::npos)
                files.push_back(e.path());
        }
        std::sort(files.begin(), files.end());
    } else {
        files.push_back(target);
    }
    if (files.empty()) {
        fprintf(stderr, "No CSV files found in %s\n", target.string().c_str());
        return 1;
    }

    // Group parts of one session: strip a trailing _pNN from the stem
    auto group_of = [](const fs::path& p) {
        std::string stem = p.stem().string();
        size_t at = stem.rfind("_p");
        if (at != std::string::npos && stem.size() - at == 4 &&
            std::isdigit((unsigned char)stem[at + 2]) && std::isdigit((unsigned char)stem[at + 3]))
            return stem.substr(0, at);
        return stem;
    };

    printf("incunest_offline_runner v0.25 (lib %s) — %zu file(s), input = %s%s -> %s\n",
           INCUNEST_AFE4490_VERSION, files.size(),
           input_ot ? "recorded OT + ProbeState" : "raw ADC codes",
           (ot_thr > 0 || input_ot) ? "" : ", ot-thr = library default", out_dir.string().c_str());
    if (ot_thr > 0) printf("  rsqm_ot_thr override: %g A/A\n", ot_thr);
    printf("  R_CAND = %s\n  R_CAND_CD = %s\n  R_CAND_CE = %s\n  R_CAND_BW = %s\n",
           R_CAND_LABEL, R_CAND_CD_LABEL, R_CAND_CE_LABEL, R_CAND_BW_LABEL);

    std::string cur_group;
    INCUNEST_AFE4490* afe = nullptr;
    CandSet cand;
    std::map<std::string, std::string> afe_state;   // the configuration the instance has (afe_* keys)
    long long smp_idx = 0;
    bool ot_live = false;                            // the session's replay has left its cold-start freeze
    int rc = 0;
    for (const auto& fpath : files) {
        std::vector<CsvRow> rows;
        std::map<std::string, std::string> cfg;
        std::vector<AfeRecord> afe_recs;
        if (!parse_csv(fpath, rows, cfg, afe_recs, input_ot)) { rc = 1; continue; }

        std::string grp = group_of(fpath);
        if (grp != cur_group) {                 // new session: fresh library instance
            delete afe;
            afe = new INCUNEST_AFE4490();
            cur_group = grp;
            smp_idx = 0;
            ot_live = false;
            afe_state.clear();
            if (cfg.empty()) {
                fprintf(stderr, "WARNING: %s has no $CFG header; using library defaults\n",
                        fpath.filename().string().c_str());
            } else if (!apply_cfg(*afe, cfg, fpath.filename().string().c_str())) {
                delete afe; afe = nullptr; cur_group.clear(); rc = 1;
                continue;                       // refuse to replay misconfigured
            }
            if (ot_thr > 0) afe->setRsqmOtThr(ot_thr);
            cand.init(cfg.count("sr") ? std::stof(cfg.at("sr")) : 500.0f);
        }

        fs::path out_path = out_dir / (fpath.stem().string() + "_replay.csv");
        int afe_changes = 0;
        PartStats st = replay_part(*afe, cand, rows, afe_recs, afe_state, out_path, &smp_idx, &afe_changes,
                                   input_ot, &ot_live);
        printf("  %s -> %s  (%d samples, probe-on %.1f%%, SpO2 producing %.1f%%",
               fpath.filename().string().c_str(), out_path.filename().string().c_str(),
               st.n, st.n ? 100.0 * st.probe_on / st.n : 0.0,
               st.n ? 100.0 * st.spo2_producing / st.n : 0.0);
        if (st.ps_compared)
            printf(", ProbeState match %.1f%%", 100.0 * st.ps_match / st.ps_compared);
        if (!afe_recs.empty()) printf(", afe records %zu / changes applied %d", afe_recs.size(), afe_changes);
        printf(")\n");
        if (st.ot_compared)
            printf("      %s replayed vs recorded OT: %.3f%% of %ld values within %.0e; max rel %.2e "
                   "(row %ld, OT_LED%d)\n",
                   st.ot_within == st.ot_compared ? "OK  " : "!!  ",
                   100.0 * st.ot_within / st.ot_compared, st.ot_compared, OT_TOL,
                   st.ot_max_rel, st.ot_max_row, st.ot_max_ch);
        if (st.ot_startup)
            printf("      (first %ld rows: the replay's cold-start freeze, not compared)\n", st.ot_startup);
        if (!st.ot_compared && !st.ot_startup && !input_ot)
            printf("      (no OT columns in the capture: replay not checked against the board)\n");
        if (st.missing_ot)
            printf("      !!  %ld rows without a recorded OT, fed as not applied\n", st.missing_ot);
        // R of both methods where both are valid: median and the 1-99 % span
        printf("      R valid: lib %.1f%%, cand %.1f%%; both: lib p50 %.3f [p1 %.3f, p99 %.3f], "
               "cand p50 %.3f [p1 %.3f, p99 %.3f]\n",
               st.n ? 100.0 * st.lib_valid / st.n : 0.0, st.n ? 100.0 * st.cand_valid / st.n : 0.0,
               pct(st.r_lib, 0.5f), pct(st.r_lib, 0.01f), pct(st.r_lib, 0.99f),
               pct(st.r_cand, 0.5f), pct(st.r_cand, 0.01f), pct(st.r_cand, 0.99f));
        if (!st.r_lib.empty())
            printf("      lib R vs R_CAND (same method since lib v0.100): max |delta| %.1e over %zu samples\n",
                   st.lib_cand_max_abs, st.r_lib.size());
        printf("      DC variants p50 [p1, p99]: cd %.3f [%.3f, %.3f], ce %.3f [%.3f, %.3f], bw %.3f [%.3f, %.3f]; "
               "DC float vs double max rel (session so far): ema %.1e, cd %.1e, ce %.1e, bw %.1e\n",
               pct(st.r_cd, 0.5f), pct(st.r_cd, 0.01f), pct(st.r_cd, 0.99f),
               pct(st.r_ce, 0.5f), pct(st.r_ce, 0.01f), pct(st.r_ce, 0.99f),
               pct(st.r_bw, 0.5f), pct(st.r_bw, 0.01f), pct(st.r_bw, 0.99f),
               cand.ema.dc_max_rel(), cand.cd.dc_max_rel(), cand.ce.dc_max_rel(), cand.bw.dc_max_rel());
    }
    delete afe;
    return rc;
}
