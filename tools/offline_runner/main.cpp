// mow_offline_runner — Offline batch processor for mow_afe4490 algorithms
// Library version: v0.16 — native/offline (no hardware)
// Spec: mow_afe4490_spec.md §9
// Author: Medical Open World — http://medicalopenworld.org — <contact@medicalopenworld.org>

#define MOW_OFFLINE 1
#include "mow_afe4490.h"

#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

// ── CSV row (raw signals + optional firmware outputs) ─────────────────────────
struct CsvRow {
    int32_t red    = 0;  // LED2VAL  — RED raw
    int32_t ir     = 0;  // LED1VAL  — IR raw
    int32_t amb_red = 0; // ALED2VAL — ambient after LED2
    int32_t amb_ir  = 0; // ALED1VAL — ambient after LED1
    int32_t red_sub = 0; // LED2-ALED2
    int32_t ir_sub  = 0; // LED1-ALED1
    // Optional firmware outputs (present if CSV contains FW_* columns)
    bool    has_fw  = false;
    float   fw_hr1  = 0.0f;
    float   fw_hr2  = 0.0f;
    float   fw_hr3  = 0.0f;
    float   fw_spo2 = 0.0f;
};

// ── File summary ──────────────────────────────────────────────────────────────
struct FileSummary {
    std::string filename;
    int         n_samples      = 0;
    double      spo2_sum       = 0.0;
    double      spo2_sqi_sum   = 0.0;
    int         spo2_valid     = 0;
    double      hr1_sum        = 0.0;
    double      hr1_sqi_sum    = 0.0;
    int         hr1_valid      = 0;
    double      hr2_sum        = 0.0;
    int         hr2_valid      = 0;
    double      hr3_sum        = 0.0;
    int         hr3_valid      = 0;
};

// ── Helpers ───────────────────────────────────────────────────────────────────
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
        // Trim whitespace
        size_t start = cell.find_first_not_of(" \t\r\n");
        size_t end   = cell.find_last_not_of(" \t\r\n");
        cols.push_back(start == std::string::npos ? "" : cell.substr(start, end - start + 1));
    }
    return cols;
}

static std::string timestamp_str() {
    time_t now = std::time(nullptr);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", std::localtime(&now));
    return buf;
}

// ── Parse a single CSV file → vector of rows ─────────────────────────────────
static bool parse_csv(const fs::path& path, std::vector<CsvRow>& rows) {
    std::ifstream f(path);
    if (!f.is_open()) {
        fprintf(stderr, "ERROR: cannot open %s\n", path.string().c_str());
        return false;
    }

    // Skip comment/empty lines before the header
    std::string header_line;
    while (std::getline(f, header_line)) {
        if (!header_line.empty() && header_line[0] != '#') break;
    }
    if (header_line.empty()) {
        fprintf(stderr, "ERROR: no header found in %s\n", path.string().c_str());
        return false;
    }

    // Locate required columns by name (case-insensitive)
    auto cols = split_csv(header_line);
    int idx_red = -1, idx_ir = -1, idx_amb_red = -1, idx_amb_ir = -1;
    int idx_red_sub = -1, idx_ir_sub = -1;
    int idx_fw_hr1 = -1, idx_fw_hr2 = -1, idx_fw_hr3 = -1, idx_fw_spo2 = -1;

    for (int i = 0; i < (int)cols.size(); i++) {
        std::string c = to_lower(cols[i]);
        if      (c == "red")      idx_red     = i;
        else if (c == "ir")       idx_ir      = i;
        else if (c == "ambred")   idx_amb_red = i;
        else if (c == "ambir")    idx_amb_ir  = i;
        else if (c == "redsub")   idx_red_sub = i;
        else if (c == "irsub")    idx_ir_sub  = i;
        else if (c == "fw_hr1")   idx_fw_hr1  = i;
        else if (c == "fw_hr2")   idx_fw_hr2  = i;
        else if (c == "fw_hr3")   idx_fw_hr3  = i;
        else if (c == "fw_spo2")  idx_fw_spo2 = i;
    }

    if (idx_red < 0 || idx_ir < 0 || idx_amb_red < 0 || idx_amb_ir < 0 ||
        idx_red_sub < 0 || idx_ir_sub < 0) {
        fprintf(stderr, "ERROR: %s is missing one or more required columns "
                "(RED, IR, AmbRED, AmbIR, REDSub, IRSub)\n", path.string().c_str());
        return false;
    }

    bool has_fw = (idx_fw_hr1 >= 0 && idx_fw_hr2 >= 0 &&
                   idx_fw_hr3 >= 0 && idx_fw_spo2 >= 0);

    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto c2 = split_csv(line);
        int n = (int)c2.size();

        auto get_i32 = [&](int idx) -> int32_t {
            if (idx < 0 || idx >= n) return 0;
            try { return (int32_t)std::stol(c2[idx]); } catch (...) { return 0; }
        };
        auto get_f32 = [&](int idx) -> float {
            if (idx < 0 || idx >= n) return 0.0f;
            try { return std::stof(c2[idx]); } catch (...) { return 0.0f; }
        };

        CsvRow row;
        row.red     = get_i32(idx_red);
        row.ir      = get_i32(idx_ir);
        row.amb_red = get_i32(idx_amb_red);
        row.amb_ir  = get_i32(idx_amb_ir);
        row.red_sub = get_i32(idx_red_sub);
        row.ir_sub  = get_i32(idx_ir_sub);
        row.has_fw  = has_fw;
        if (has_fw) {
            row.fw_hr1  = get_f32(idx_fw_hr1);
            row.fw_hr2  = get_f32(idx_fw_hr2);
            row.fw_hr3  = get_f32(idx_fw_hr3);
            row.fw_spo2 = get_f32(idx_fw_spo2);
        }
        rows.push_back(row);
    }

    return !rows.empty();
}

// ── Process one file ──────────────────────────────────────────────────────────
static void process_file(const fs::path& input_path, std::ofstream& summary_csv) {
    std::vector<CsvRow> rows;
    if (!parse_csv(input_path, rows)) return;

    // Result CSV alongside the input file
    fs::path result_path = input_path.parent_path() /
        (input_path.stem().string() + "_result.csv");
    std::ofstream out(result_path);
    if (!out.is_open()) {
        fprintf(stderr, "ERROR: cannot write %s\n", result_path.string().c_str());
        return;
    }

    bool has_fw = rows[0].has_fw;

    // Header
    out << "SmpIdx,RED,IR,AmbRED,AmbIR,REDSub,IRSub,"
           "SpO2,SpO2SQI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI";
    if (has_fw)
        out << ",FW_HR1,FW_HR2,FW_HR3,FW_SpO2,delta_HR1,delta_HR2,delta_HR3,delta_SpO2";
    out << "\n";

    // Instantiate library in offline mode — constructor calls _reset_algorithms() + Hann precompute
    MOW_AFE4490 afe;

    FileSummary summary;
    summary.filename = input_path.filename().string();

    for (int idx = 0; idx < (int)rows.size(); idx++) {
        const CsvRow& r = rows[idx];

        afe.test_feed_spo2(r.ir_sub, r.red_sub);
        afe.test_feed_hr1(r.ir_sub);
        afe.test_feed_hr2(r.ir_sub);
        afe.test_feed_hr3(r.ir_sub);

        float spo2     = afe.test_spo2();
        float spo2_sqi = afe.test_spo2_sqi();
        float hr1      = afe.test_hr1();
        float hr1_sqi  = afe.test_hr1_sqi();
        float hr2      = afe.test_hr2();
        float hr2_sqi  = afe.test_hr2_sqi();
        float hr3      = afe.test_hr3();
        float hr3_sqi  = afe.test_hr3_sqi();

        // Write result row
        out << idx << ","
            << r.red << "," << r.ir << "," << r.amb_red << "," << r.amb_ir << ","
            << r.red_sub << "," << r.ir_sub << ","
            << spo2 << "," << spo2_sqi << ","
            << hr1  << "," << hr1_sqi  << ","
            << hr2  << "," << hr2_sqi  << ","
            << hr3  << "," << hr3_sqi;

        if (has_fw) {
            out << "," << r.fw_hr1  << "," << r.fw_hr2
                << "," << r.fw_hr3  << "," << r.fw_spo2
                << "," << (hr1  - r.fw_hr1)
                << "," << (hr2  - r.fw_hr2)
                << "," << (hr3  - r.fw_hr3)
                << "," << (spo2 - r.fw_spo2);
        }
        out << "\n";

        // Accumulate summary stats
        summary.n_samples++;
        if (spo2_sqi > 0.0f) {
            summary.spo2_sum     += spo2;
            summary.spo2_sqi_sum += spo2_sqi;
            summary.spo2_valid++;
        }
        if (hr1_sqi > 0.0f) {
            summary.hr1_sum     += hr1;
            summary.hr1_sqi_sum += hr1_sqi;
            summary.hr1_valid++;
        }
        if (hr2_sqi > 0.0f) { summary.hr2_sum += hr2; summary.hr2_valid++; }
        if (hr3_sqi > 0.0f) { summary.hr3_sum += hr3; summary.hr3_valid++; }
    }

    out.close();
    printf("  -> %s  (%d samples)\n", result_path.filename().string().c_str(),
           summary.n_samples);

    // Append to batch summary
    auto mean = [](double sum, int n) -> double { return n > 0 ? sum / n : 0.0; };
    double valid_spo2_pct = summary.n_samples > 0
        ? 100.0 * summary.spo2_valid / summary.n_samples : 0.0;

    summary_csv << timestamp_str()          << ","
                << summary.filename         << ","
                << summary.n_samples        << ","
                << mean(summary.spo2_sum,     summary.spo2_valid)   << ","
                << mean(summary.spo2_sqi_sum, summary.spo2_valid)   << ","
                << mean(summary.hr1_sum,      summary.hr1_valid)    << ","
                << mean(summary.hr1_sqi_sum,  summary.hr1_valid)    << ","
                << mean(summary.hr2_sum,      summary.hr2_valid)    << ","
                << mean(summary.hr3_sum,      summary.hr3_valid)    << ","
                << valid_spo2_pct           << "\n";
    summary_csv.flush();
}

// ── Main ──────────────────────────────────────────────────────────────────────
int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: mow_offline_runner <file.csv | directory>\n");
        return 1;
    }

    fs::path target(argv[1]);
    if (!fs::exists(target)) {
        fprintf(stderr, "ERROR: path does not exist: %s\n", argv[1]);
        return 1;
    }

    // Collect CSV files to process
    std::vector<fs::path> files;
    if (fs::is_directory(target)) {
        for (const auto& entry : fs::directory_iterator(target)) {
            if (entry.is_regular_file() &&
                to_lower(entry.path().extension().string()) == ".csv" &&
                entry.path().stem().string().find("_result") == std::string::npos &&
                entry.path().filename().string() != "batch_summary.csv")
                files.push_back(entry.path());
        }
        std::sort(files.begin(), files.end());
    } else {
        files.push_back(target);
    }

    if (files.empty()) {
        fprintf(stderr, "No CSV files found in %s\n", argv[1]);
        return 1;
    }

    // Open (or append) batch summary
    fs::path summary_path = fs::is_directory(target)
        ? target / "batch_summary.csv"
        : target.parent_path() / "batch_summary.csv";

    bool summary_exists = fs::exists(summary_path);
    std::ofstream summary_csv(summary_path, std::ios::app);
    if (!summary_csv.is_open()) {
        fprintf(stderr, "ERROR: cannot open batch_summary.csv for writing\n");
        return 1;
    }
    if (!summary_exists)
        summary_csv << "Timestamp,File,N_samples,SpO2_mean,SpO2_SQI_mean,"
                       "HR1_mean,HR1_SQI_mean,HR2_mean,HR3_mean,valid_spo2_pct\n";

    printf("mow_offline_runner — processing %zu file(s)\n", files.size());
    for (const auto& f : files) {
        printf("  %s\n", f.filename().string().c_str());
        process_file(f, summary_csv);
    }
    printf("Done. Summary: %s\n", summary_path.string().c_str());
    return 0;
}
