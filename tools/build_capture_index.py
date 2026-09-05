#!/usr/bin/env python3
"""Build the capture index for the PulseNest capture set.

Two files, deliberately separate (see captures/CAPTURE_SET_SPEC.md section 2.5):

  captures/index.csv   DERIVED  - everything readable from the capture itself (the '#' header,
                                  the row count, the file hash). Regenerated from scratch on
                                  every run. Never edit by hand; edits are lost.
  captures/truth.csv   AUTHORED - everything only a person knows (tier, condition, ground truth,
                                  consent, notes). Rows are ADDED for new captures and existing
                                  rows are never modified, so manual work is safe across runs.

Joining the two on 'file' gives the manifest the tests consume. Keeping them apart is what stops
the same fact from living in two places: the header is authoritative for hardware settings, and
index.csv is only a queryable cache of it.

Usage:
    python tools/build_capture_index.py            # rebuild index, extend truth
    python tools/build_capture_index.py --check    # verify hashes, report drift, write nothing
"""

import argparse
import csv
import hashlib
import os
import re
import sys

CAPTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
INDEX_PATH = os.path.join(CAPTURES_DIR, "index.csv")
TRUTH_PATH = os.path.join(CAPTURES_DIR, "truth.csv")

INDEX_FIELDS = [
    "file", "sha256", "bytes", "n_samples", "duration_s",
    "header_datetime", "board", "mac",
    "prf_hz", "numav",
    "iled1_ma", "iled2_ma", "led_range_ma",
    "rf_led1", "rf_led2", "cf_led1", "cf_led2", "stg2_led1", "stg2_led2",
    "ensepgain", "ambdac_ua",
    "ppg_channel", "ppg_filter", "hr2_bpf", "hr3_lpf",
    "spo2_a", "spo2_b",
    "n_columns", "has_analog_state", "has_config_header",
    # Per-sample RF reported by the firmware (RF1_OHM/RF2_OHM columns, lib >= v0.37). This is the
    # ONLY automatic record of the analog configuration: the '#' header is hand-pasted into the
    # "Pre-capture notes" box and goes stale, and the filename is hand-typed. When present, this
    # wins over both. Lists every distinct value, so an RF change mid-capture is visible.
    "rf_led1_from_data", "rf_led2_from_data",
]

TRUTH_FIELDS = [
    "file", "tier", "condition", "subject_code",
    "truth_hr_bpm", "truth_spo2_pct", "truth_beats",
    "usable_from_s", "consent", "notes", "name_hint",
]

# ---------------------------------------------------------------- header parsing

# The header is emitted by pulsenest_lab.py. Each pattern is anchored to its line so a missing
# field yields "" rather than a wrong value silently borrowed from a neighbouring line.
HEADER_PATTERNS = {
    "header_datetime": r"^#\s*AFE4490 config\D+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    "board":           r"^#\s*Board:\s*(\S+)",
    "mac":             r"Board:.*MAC:\s*([0-9A-Fa-f:]+)",
    "prf_hz":          r"^#\s*Sample rate:\s*([\d.]+)\s*Hz",
    "numav":           r"Sample rate:.*NUMAV:\s*(\d+)",
    "iled1_ma":        r"^#\s*LED1:\s*([\d.]+)\s*mA",
    "iled2_ma":        r"^#\s*LED1:.*LED2:\s*([\d.]+)\s*mA",
    "led_range_ma":    r"^#\s*LED1:.*Range:\s*([\d.]+)\s*mA",
    "ensepgain":       r"^#\s*ENSEPGAIN:\s*(\d+)",
    "rf_led1":         r"^#\s*LED1:\s*TIA=(\S+)",
    "cf_led1":         r"^#\s*LED1:\s*TIA=\S+\s+CF=(\S+)",
    "stg2_led1":       r"^#\s*LED1:\s*TIA=\S+\s+CF=\S+\s+STG2=(\S+)",
    "rf_led2":         r"^#\s*LED2:\s*TIA=(\S+)",
    "cf_led2":         r"^#\s*LED2:\s*TIA=\S+\s+CF=(\S+)",
    "stg2_led2":       r"^#\s*LED2:\s*TIA=\S+\s+CF=\S+\s+STG2=(\S+)",
    "ambdac_ua":       r"^#\s*AMBDAC:\s*(-?[\d.]+)",
    "ppg_channel":     r"^#\s*PPG channel:\s*(\S+)",
    "ppg_filter":      r"PPG channel:.*Filter:\s*(.+?)\s*$",
    "hr2_bpf":         r"^#\s*HR2 BPF:\s*(.+?)\s{2,}HR3",
    "hr3_lpf":         r"HR3 LPF:\s*(.+?)\s*$",
    "spo2_a":          r"^#\s*SpO2:\s*a=([\d.eE+-]+)",
    "spo2_b":          r"^#\s*SpO2:.*b=([\d.eE+-]+)",
}


def parse_capture(path):
    """Return the derived record for one capture, or None if it has no usable header."""
    rec = {k: "" for k in INDEX_FIELDS}
    rec["file"] = os.path.basename(path)

    sha = hashlib.sha256()
    n_rows = 0
    header_lines = []
    col_line = None
    first_ts = last_ts = None
    ts_col = None
    rf_cols = {}
    rf_seen = {}

    with open(path, "rb") as fb:
        for raw in fb:
            sha.update(raw)
            # The header is not pure UTF-8: pulsenest_lab.py emits a few cp1252 bytes (en dash,
            # micro sign). Decoding as UTF-8 with errors="replace" would bake U+FFFD into the
            # index, so try UTF-8 first and fall back to cp1252, which is what those bytes are.
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError:
                line = raw.decode("cp1252", errors="replace").rstrip("\r\n")
            if not line:
                continue
            if line.startswith("#"):
                header_lines.append(line)
                continue
            if col_line is None:
                col_line = line
                cols = col_line.split(",")
                rec["n_columns"] = len(cols)
                rec["has_analog_state"] = "yes" if any(c.startswith("FW_V_TIA") for c in cols) else "no"
                ts_col = cols.index("FW_Ts_us") if "FW_Ts_us" in cols else None
                rf_cols = {}
                for field, name in (("rf_led1_from_data", "FW_RF1_OHM"),
                                    ("rf_led2_from_data", "FW_RF2_OHM")):
                    if name in cols:
                        rf_cols[field] = cols.index(name)
                continue
            n_rows += 1
            parts = None
            if ts_col is not None:
                parts = line.split(",")
                if len(parts) > ts_col:
                    try:
                        v = float(parts[ts_col])
                    except ValueError:
                        v = None
                    if v is not None:
                        if first_ts is None:
                            first_ts = v
                        last_ts = v
            if rf_cols:
                if parts is None:
                    parts = line.split(",")
                for field, idx in rf_cols.items():
                    if len(parts) > idx:
                        val = parts[idx].strip()
                        if val and val != "-1":
                            rf_seen.setdefault(field, set()).add(val)

    if col_line is None:
        return None

    rec["sha256"] = sha.hexdigest()
    rec["bytes"] = os.path.getsize(path)
    rec["n_samples"] = n_rows
    # A capture with no '#' block cannot be replayed through an equivalent chain (spec 2.3).
    # Recorded explicitly rather than inferred from an empty prf_hz, so it can be filtered on.
    rec["has_config_header"] = "yes" if header_lines else "no"

    for field, values in rf_seen.items():
        # Sorted numerically where possible so "100000" precedes "250000" rather than sorting
        # as text. Multiple values mean the RF changed during the capture (manual $SET or HGAC).
        try:
            rec[field] = "|".join(str(int(float(v))) for v in sorted(values, key=float))
        except ValueError:
            rec[field] = "|".join(sorted(values))

    header = "\n".join(header_lines)
    for field, pattern in HEADER_PATTERNS.items():
        m = re.search(pattern, header, re.MULTILINE)
        if m:
            rec[field] = m.group(1).strip()

    # Duration: prefer the firmware timestamp span; fall back to sample count over PRF.
    if first_ts is not None and last_ts is not None and last_ts > first_ts:
        rec["duration_s"] = round((last_ts - first_ts) / 1e6, 2)
    elif rec["prf_hz"]:
        try:
            rec["duration_s"] = round(n_rows / float(rec["prf_hz"]), 2)
        except (ValueError, ZeroDivisionError):
            pass

    return rec


# ---------------------------------------------------------------- truth seeding

TIER_RE = re.compile(r"^(T[0-3])_")
BPM_RE = re.compile(r"(\d+)\s*BPM", re.IGNORECASE)
SPO2_RE = re.compile(r"(\d+)\s*SPO2", re.IGNORECASE)


def seed_truth_row(fname):
    """Create an EMPTY authored row. Nothing is inferred into a truth field on purpose:
    a guess that looks like data is worse than a blank. Hints from the filename go to
    'name_hint', which no test reads."""
    row = {k: "" for k in TRUTH_FIELDS}
    row["file"] = fname

    hints = []
    m = TIER_RE.match(fname)
    if m:
        row["tier"] = m.group(1)          # only trusted when the convention was actually applied
    m = BPM_RE.search(fname)
    if m:
        hints.append("bpm=" + m.group(1))
    m = SPO2_RE.search(fname)
    if m:
        hints.append("spo2=" + m.group(1))
    if "SIMUL" in fname.upper() or fname.upper().startswith("T1_SIM"):
        hints.append("looks like simulator")
    if "PHOTOTHERAPY" in fname.upper():
        hints.append("phototherapy")
    row["name_hint"] = "; ".join(hints)
    return row


def load_existing_truth():
    if not os.path.exists(TRUTH_PATH):
        return {}, []
    with open(TRUTH_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or TRUTH_FIELDS
    return {r["file"]: r for r in rows}, fields


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify the index against the files on disk; write nothing")
    args = ap.parse_args()

    names = sorted(f for f in os.listdir(CAPTURES_DIR) if f.lower().endswith(".csv"))
    names = [n for n in names if n not in ("index.csv", "truth.csv")]
    if not names:
        print("No captures found in", CAPTURES_DIR)
        return 1

    records = []
    skipped = []
    for n in names:
        rec = parse_capture(os.path.join(CAPTURES_DIR, n))
        if rec is None:
            skipped.append(n)
        else:
            records.append(rec)

    if args.check:
        return run_check(records, skipped)

    with open(INDEX_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        w.writeheader()
        w.writerows(records)

    existing, fields = load_existing_truth()
    added = [seed_truth_row(r["file"]) for r in records if r["file"] not in existing]
    out_rows = list(existing.values()) + added
    out_rows.sort(key=lambda r: r["file"])
    with open(TRUTH_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRUTH_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    print("index.csv : %d captures" % len(records))
    print("truth.csv : %d rows (%d new, %d preserved)" % (len(out_rows), len(added), len(existing)))
    if skipped:
        print("\nskipped -- header only, no data rows (%d):" % len(skipped))
        for n in skipped[:5]:
            print("   ", n)
        if len(skipped) > 5:
            print("    ... and %d more" % (len(skipped) - 5))

    missing = [r["file"] for r in out_rows if not r.get("tier")]
    if missing:
        print("\n%d captures still have no tier -- fill truth.csv by hand:" % len(missing))
        for m in missing[:10]:
            print("   ", m)
        if len(missing) > 10:
            print("    ... and %d more" % (len(missing) - 10))
    return 0


def run_check(records, skipped):
    """Compare the on-disk files against a previously written index."""
    if not os.path.exists(INDEX_PATH):
        print("No index.csv -- run without --check first.")
        return 1
    with open(INDEX_PATH, "r", encoding="utf-8", newline="") as f:
        stored = {r["file"]: r for r in csv.DictReader(f)}

    now = {r["file"]: r for r in records}
    problems = 0

    for name, rec in sorted(now.items()):
        if name not in stored:
            print("NEW      %s" % name)
            problems += 1
        elif stored[name]["sha256"] != rec["sha256"]:
            print("CHANGED  %s" % name)
            problems += 1
    for name in sorted(stored):
        if name not in now:
            print("MISSING  %s" % name)
            problems += 1

    # Contradictions between the two HAND-WRITTEN records of the configuration: the filename and
    # the '#' header. Neither is authoritative — the header is pasted by hand into the
    # "Pre-capture notes" box and goes stale when a setting changes without pressing "Read chip
    # config" again; the filename is typed by hand too. The automatic record is the per-sample
    # RF1_OHM/RF2_OHM column (lib >= v0.37); where it exists it settles the question, and where it
    # does not, the signal amplitude does (RF scales v_tia linearly). Reported, not adjudicated.
    for name, rec in sorted(now.items()):
        m = re.search(r"RF(\d+)\s*K", name, re.IGNORECASE)
        if m and rec.get("rf_led1"):
            claimed = m.group(1).upper().lstrip("0")
            actual = rec["rf_led1"].upper().replace("K", "").lstrip("0")
            if claimed != actual:
                data = rec.get("rf_led1_from_data") or ""
                verdict = ("  -- per-sample data says %s" % data) if data else \
                          "  -- no per-sample RF column; check the signal amplitude"
                print("MISMATCH %s: name says RF%sK, header says %s%s"
                      % (name, m.group(1), rec["rf_led1"], verdict))
                problems += 1

    if skipped:
        print("EMPTY    %d capture(s) with header but no data rows" % len(skipped))
    print("\n%d issue(s)." % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
