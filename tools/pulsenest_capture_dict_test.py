"""Checks on tools/pulsenest_capture_dict.py -- the R18 dictionary is data, so the tests are about
the data holding together with what surrounds it: the live column list, the firmware's own wire
frames, and the spec's worked example. Run:  python tools/pulsenest_capture_dict_test.py"""
import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]

from pulsenest_capture_csv import CAPTURE_COLS                         # noqa: E402
import pulsenest_capture_dict as D                                     # noqa: E402

n_ok = n_bad = 0
def check(cond, what):
    global n_ok, n_bad
    if cond: n_ok += 1
    else:
        n_bad += 1; print("FAIL:", what)

NAME_RE  = re.compile(r"^[A-Za-z][A-Za-z0-9]*(_[A-Za-z0-9]+)*$")      # R19: words joined by _
UNITS    = {"count", "us", "ms", "s", "adc_code", "LSB", "A/A", "1e-10 A/A", "%", "flag", "ratio",
            "bpm", "index", "bitmask", "enum", "V", "mV", "A", "uA", "mA", "pA", "ohm", "pF", "Hz",
            "mHz", "text"}
PROV     = {D.FW_MEASURED, D.FW_COMPUTED, D.HOST, D.DERIVABLE, D.CONFIG, D.OPERATOR}
DOMAINS  = {"id", "session", "clock", "afe", "timing", "alg"}

# ── 1. internal consistency ──────────────────────────────────────────────────────────────────
names = [c.name for c in D.COLUMNS]
check(len(names) == len(set(names)), "column names unique")
all_col_names = [s for c in D.COLUMNS for s in (c.name, *c.synonyms)]
check(len(all_col_names) == len(set(all_col_names)), "no column synonym collides with another name")
keys = [k.name for k in D.KEYS]
check(len(keys) == len(set(keys)), "key names unique")
for c in D.COLUMNS:
    check(NAME_RE.match(c.name), f"column grammar {c.name}")
    check(c.unit in UNITS, f"column unit {c.name}: {c.unit}")
    check(c.provenance in PROV, f"column provenance {c.name}")
    check(c.type in ("int", "float"), f"column type {c.name}")
for k in D.KEYS:
    check(NAME_RE.match(k.name) and k.name == k.name.lower(), f"key grammar (lower_snake) {k.name}")
    check(k.unit in UNITS, f"key unit {k.name}: {k.unit}")
    check(k.provenance in PROV, f"key provenance {k.name}")
    check(k.domain in DOMAINS, f"key domain {k.name}")
    if k.domain in ("afe", "timing", "alg"):
        check(k.name.startswith(("afe_", "ppgdisp_", "hr2_", "hr3_", "spo2_", "rsqm_", "hgac_")),
              f"snapshot key {k.name} has a domain prefix")
    # R24a: reals only in alg:, and only for dimensionless coefficients
    if k.type == "float":
        check(k.domain == "alg" and k.unit == "ratio", f"real allowed only for alg coefficients: {k.name}")
    if k.wire:
        frame, wkeys, scale = k.wire
        check(frame in (D.CFG, D.TCFG, D.LCFG) and len(wkeys) >= 1, f"wire shape {k.name}")
        check((scale is None) == (k.type == "str"), f"scale None iff the value is text: {k.name}")

# ── 2. every column ever written resolves, both spellings to the same canon ──────────────────
for label, csv_name, _idx, _mand in CAPTURE_COLS:
    check(label in D.COLUMN_CANON, f"CAPTURE_COLS label {label} in dictionary")
    check(csv_name in D.COLUMN_CANON, f"CAPTURE_COLS csv name {csv_name} in dictionary")
    check(D.COLUMN_CANON.get(label) == D.COLUMN_CANON.get(csv_name) == csv_name.removeprefix("FW_"),
          f"{label}/{csv_name} resolve to the same canon, the csv name without FW_")
for legacy in ("IR", "IR_Amb", "IR_Sub", "RED", "RED_Amb", "RED_Sub", "HOST_T_US"):   # F2 + host column
    check(legacy in D.COLUMN_CANON, f"legacy name {legacy} resolves")
check(D.COLUMN_CANON["IR_Sub"] == "LED1_SUB" and D.COLUMN_CANON["RED_Amb"] == "ALED2", "IR/RED mapping (R23)")
check(D.COLUMN_BY_NAME["OT1_E10"].unit == "1e-10 A/A", "OT1_E10 carries its scale in name and unit")

# ── 3. the firmware's wire frames and the dictionary agree, both ways ────────────────────────
fw = io.open(os.path.join(ROOT, "main", "pulsenest_main.cpp"), encoding="utf-8").read()
def fw_keys(func):
    body = fw[fw.index(f"static void {func}("):]
    body = body[:body.index("\n}\n")]
    return set(re.findall(r'[,"](\w+)=%', body))
for frame, func in ((D.CFG, "send_cfg_frame"), (D.TCFG, "send_tcfg_frame"), (D.LCFG, "send_lcfg_frame")):
    on_wire = fw_keys(func)
    in_dict = {w for (f, w) in D.WIRE_TO_KEY if f == frame}
    check(on_wire, f"{frame}: found the format string in the firmware")
    check(on_wire - in_dict == set(), f"{frame}: every wire key is in the dictionary -- missing {sorted(on_wire - in_dict)}")
    check(in_dict - on_wire == set(), f"{frame}: every dictionary wire key is on the wire -- stale {sorted(in_dict - on_wire)}")
check(len({w for (f, w) in D.WIRE_TO_KEY if f == D.TCFG}) == 28, "$TCFG: t1..t28")
check(D.WIRE_TO_KEY[(D.CFG, "tia1")] == D.WIRE_TO_KEY[(D.CFG, "rf1_ohm")] == "afe_rf1_ohm", "redundant wire twins collapse (R24a)")
check(D.WIRE_TO_KEY[(D.CFG, "ts_us")] == "fw_ts_us" and D.WIRE_TO_KEY[(D.CFG, "cause")] == "cause", "fw 0.15 keys resolve")

# ── 4. the spec's worked example (Appendix B) uses only dictionary keys, in the right domain ──
spec = io.open(os.path.join(ROOT, "capture_csv_format_spec.md"), encoding="utf-8").read()
appx = spec[spec.index("## Appendix B"):]
lines = re.findall(r"^# @row \d+ (afe|timing|alg): (.*)$", appx, re.M)
check(len(lines) >= 5, f"Appendix B has snapshot lines ({len(lines)})")
for domain, rest in lines:
    for tok in rest.split():
        k, _, v = tok.partition("=")
        if k == "cause":
            continue
        entry = D.KEY_BY_NAME.get(k)
        check(entry is not None, f"Appendix B {domain}: key {k} is in the dictionary")
        if entry:
            check(entry.domain == domain, f"Appendix B: {k} written under {domain}:, dictionary says {entry.domain}")
            if entry.type == "int":
                check(re.fullmatch(r"-?\d+", v) is not None, f"Appendix B: {k}={v} should be an integer (R24a/R30)")
snapshot_keys = {k.name for k in D.KEYS if k.domain in ("afe", "timing", "alg")}
used = {tok.partition("=")[0] for _d, rest in lines for tok in rest.split()} - {"cause"}
check(snapshot_keys <= used, f"every snapshot key appears in Appendix B -- unused {sorted(snapshot_keys - used)}")

print(f"{n_ok}/{n_ok + n_bad} checks")
sys.exit(1 if n_bad else 0)
