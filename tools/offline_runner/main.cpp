// incunest_offline_runner — Offline batch processor for incunest_afe4490 algorithms
// Runner version: v0.22 — native/offline (no hardware), library API v0.98
// Spec: incunest_afe4490_spec.md §9
// Author: Medical Open World — http://medicalopenworld.org — <contact@medicalopenworld.org>
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
};

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
    bool valid() const { return led1 >= 0 && led2 >= 0 && aled1 >= 0 && aled2 >= 0; }
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
        // Legacy IncuNest dialect
        else if (c == "ir")      ix.led1  = i;
        else if (c == "red")     ix.led2  = i;
        else if (c == "ir_amb")  ix.aled1 = i;
        else if (c == "red_amb") ix.aled2 = i;
        else if (c == "fw_spo2") ix.fw_spo2 = i;
    }
    return ix;
}

// ── Parse one CSV part: rows + (first seen) $CFG map ─────────────────────────
static bool parse_csv(const fs::path& path, std::vector<CsvRow>& rows,
                      std::map<std::string, std::string>& cfg) {
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
            continue;
        }
        if (!have_header) {
            ix = find_columns(split_csv(line));
            if (!ix.valid()) {
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
            row.fw_ps   = (int)get_i32(ix.fw_ps);
        }
        rows.push_back(row);
    }
    return !rows.empty();
}

// ── Replay one part through an already-configured library instance ───────────
struct PartStats {
    int n = 0, probe_on = 0, spo2_producing = 0, ps_match = 0, ps_compared = 0;
};

static PartStats replay_part(INCUNEST_AFE4490& afe, const std::vector<CsvRow>& rows,
                             const fs::path& out_path, long long* smp_idx) {
    std::ofstream out(out_path);
    PartStats st;
    if (!out.is_open()) {
        fprintf(stderr, "ERROR: cannot write %s\n", out_path.string().c_str());
        return st;
    }
    bool has_fw = rows[0].has_fw;
    out << "SmpIdx,ProbeState,OT_LED1,OT_LED2,R,PI,SpO2,SpO2_SQI,"
           "HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI";
    if (has_fw) out << ",FW_SpO2,FW_R,FW_ProbeState,delta_SpO2,delta_R";
    out << "\n";
    char buf[512];
    for (const CsvRow& r : rows) {
        afe.test_feed_sample(r.led1, r.led2, r.aled1, r.aled2);
        int   ps   = (int)afe.test_probe_state();
        float spo2 = afe.test_spo2();
        float rr   = afe.test_spo2_r();
        snprintf(buf, sizeof(buf),
                 "%lld,%d,%.5g,%.5g,%.5f,%.3g,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f",
                 *smp_idx, ps,
                 afe.test_last_ot_led1(), afe.test_last_ot_led2(),
                 rr, afe.test_pi(), spo2, afe.test_spo2_sqi(),
                 afe.test_hr1(), afe.test_hr1_sqi(),
                 afe.test_hr2(), afe.test_hr2_sqi(),
                 afe.test_hr3(), afe.test_hr3_sqi());
        out << buf;
        if (has_fw) {
            snprintf(buf, sizeof(buf), ",%.2f,%.5f,%d,%.2f,%.5f",
                     r.fw_spo2, r.fw_r, r.fw_ps,
                     spo2 - r.fw_spo2, rr - r.fw_r);
            out << buf;
            st.ps_compared++;
            if (ps == r.fw_ps) st.ps_match++;
        }
        out << "\n";
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
        "Usage: incunest_offline_runner <file.csv | directory> [--ot-thr <A/A>] [--out DIR]\n";
    fs::path target;
    fs::path out_dir;
    std::string ot_arg;
    float ot_thr = -1.0f;   // <0 = keep library default
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--ot-thr") == 0 && i + 1 < argc) {
            ot_arg = argv[++i];
            ot_thr = std::stof(ot_arg);
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
    // The session directory holds only what was recorded: a replay is derived, and is named
    // by what it depends on, so another library version or threshold never overwrites it.
    if (out_dir.empty()) {
        fs::path base = fs::is_directory(target) ? target : target.parent_path();
        std::string name = std::string("replay_lib") + INCUNEST_AFE4490_VERSION;
        if (ot_thr > 0) name += "_ot" + ot_arg;
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

    printf("incunest_offline_runner v0.22 (lib %s) — %zu file(s)%s -> %s\n",
           INCUNEST_AFE4490_VERSION, files.size(),
           ot_thr > 0 ? "" : ", ot-thr = library default", out_dir.string().c_str());
    if (ot_thr > 0) printf("  rsqm_ot_thr override: %g A/A\n", ot_thr);

    std::string cur_group;
    INCUNEST_AFE4490* afe = nullptr;
    long long smp_idx = 0;
    int rc = 0;
    for (const auto& fpath : files) {
        std::vector<CsvRow> rows;
        std::map<std::string, std::string> cfg;
        if (!parse_csv(fpath, rows, cfg)) { rc = 1; continue; }

        std::string grp = group_of(fpath);
        if (grp != cur_group) {                 // new session: fresh library instance
            delete afe;
            afe = new INCUNEST_AFE4490();
            cur_group = grp;
            smp_idx = 0;
            if (cfg.empty()) {
                fprintf(stderr, "WARNING: %s has no $CFG header; using library defaults\n",
                        fpath.filename().string().c_str());
            } else if (!apply_cfg(*afe, cfg, fpath.filename().string().c_str())) {
                delete afe; afe = nullptr; cur_group.clear(); rc = 1;
                continue;                       // refuse to replay misconfigured
            }
            if (ot_thr > 0) afe->setRsqmOtThr(ot_thr);
        }

        fs::path out_path = out_dir / (fpath.stem().string() + "_replay.csv");
        PartStats st = replay_part(*afe, rows, out_path, &smp_idx);
        printf("  %s -> %s  (%d samples, probe-on %.1f%%, SpO2 producing %.1f%%",
               fpath.filename().string().c_str(), out_path.filename().string().c_str(),
               st.n, st.n ? 100.0 * st.probe_on / st.n : 0.0,
               st.n ? 100.0 * st.spo2_producing / st.n : 0.0);
        if (st.ps_compared)
            printf(", ProbeState match %.1f%%", 100.0 * st.ps_match / st.ps_compared);
        printf(")\n");
    }
    delete afe;
    return rc;
}
