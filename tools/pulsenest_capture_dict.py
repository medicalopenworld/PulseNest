"""The capture dictionary -- capture_csv_format_spec.md R18, decided 2026-09-22 (D2 closed).

Data, no logic. One entry per CSV column and per header/snapshot key: canonical name, meaning, unit,
type, provenance, the version that introduced it, and the names it is also known by. Everything
that writes or reads a capture names things through this file: the v0.4 writer takes its column
row and its `afe:`/`timing:`/`alg:` keys from here, the reader resolves the 121 legacy files'
24 distinct header rows through the synonyms, and the converter needs nothing else to turn a
`$CFG`/`$TCFG`/`$LCFG` wire frame into snapshot keys.

Rules this file obeys (R18/R19/R24a and the project's naming memories):
  * a name never changes meaning; renaming = adding a synonym; nothing is reused;
  * columns keep the hardware vocabulary (LED1/ALED1, never IR/RED -- those are synonyms under the
    header's `led1=IR led2=RED` mapping only, R23); ADC output is `adc_code`, never `count`;
  * keys carry a domain prefix and a unit suffix and hold ONE representation per register, an
    integer in natural units (`afe_rf1_ohm=50000`, not `tia1=50k` and `rf1_ohm=50000` twice);
    reals only in `alg:` and only for dimensionless coefficients (`spo2_cal_a`);
  * a scaled OT says its scale in its name (`OT1_E10`, the `_ppm` rule generalised).

`wire` says where a key comes from on the wire and how: (frame, wire keys, scale) -- the canonical
integer is `round(float(wire value) * scale)`; where the frame prints a register two or three ways
the numeric twin is listed first and the labels after it, so a converter reads the first wire key
it finds. `scale=None` marks a string copied verbatim.
"""
from collections import namedtuple

DICT_VERSION = "1"          # the N of `# format=incunest_csv/N` this dictionary describes

Column = namedtuple("Column", "name synonyms meaning unit type provenance since")
Key    = namedtuple("Key",    "name domain wire meaning unit type provenance since")

# provenance vocabulary (R18)
FW_MEASURED = "fw measured"     # read off the chip
FW_COMPUTED = "fw computed"     # the firmware's own algorithm output; not recomputable from a cold start
HOST        = "host"            # stamped by the machine that wrote the file
DERIVABLE   = "derivable"       # stateless function of other columns/keys; a reader may drop or recompute it
CONFIG      = "config"          # a setting, not a measurement
OPERATOR    = "operator"        # typed by a person; nothing electrical can supply it

# ── columns ──────────────────────────────────────────────────────────────────────────────────
# Canonical = the lab's own labels, which already follow the hardware vocabulary. `FW_*` are the
# recorder/lab CSV headers of 2026; `IR*/RED*` the 23 files the offline runner reads (F2).
COLUMNS = [
    Column("SmpCnt",      ("FW_SmpCnt",),   "firmware sample counter, +1 per conversion, wraps at 2^32", "count",    "int",   FW_MEASURED, "legacy"),
    Column("Ts_us",       ("FW_Ts_us",),    "esp_timer_get_time() at the SPI read of this sample (64-bit since fw 0.14)", "us", "int", FW_MEASURED, "legacy"),
    Column("LED2",        ("FW_LED2", "RED", "LED2 (RED)"), "LED2 (RED) phase ADC output",       "adc_code", "int", FW_MEASURED, "legacy"),
    Column("LED1",        ("FW_LED1", "IR", "LED1 (IR)"),   "LED1 (IR) phase ADC output",        "adc_code", "int", FW_MEASURED, "legacy"),
    Column("ALED2",       ("FW_ALED2", "RED_Amb"),     "ambient phase after LED2, ADC output",   "adc_code", "int", FW_MEASURED, "legacy"),
    Column("ALED1",       ("FW_ALED1", "IR_Amb"),      "ambient phase after LED1, ADC output",   "adc_code", "int", FW_MEASURED, "legacy"),
    Column("LED2_SUB",    ("FW_LED2_SUB", "RED_Sub"),  "LED2 - ALED2 (chip's own subtraction; == LED2-ALED2 in 75 000/75 000 rows, F5)", "adc_code", "int", DERIVABLE, "legacy"),
    Column("LED1_SUB",    ("FW_LED1_SUB", "IR_Sub"),   "LED1 - ALED1",                            "adc_code", "int", DERIVABLE, "legacy"),
    Column("PPG",         ("FW_PPG",),      "display PPG: band-passed OT of the display channel (ppgdisp_*)", "A/A", "float", FW_COMPUTED, "legacy"),
    Column("SpO2",        ("FW_SpO2",),     "firmware SpO2; -1 when SpO2_SQI == 0",              "%",        "float", FW_COMPUTED, "legacy"),
    Column("SpO2_SQI",    ("FW_SpO2_SQI",), "SpO2 validity, 0 = invalid, 1 = valid (project_sqi_definition)", "flag", "float", FW_COMPUTED, "legacy"),
    Column("R",           ("FW_R",),        "ratio of ratios (AC/DC RED over AC/DC IR) behind SpO2", "ratio",  "float", FW_COMPUTED, "legacy"),
    Column("PI",          ("FW_PI",),       "perfusion index, AC/DC of the IR channel",           "%",        "float", FW_COMPUTED, "legacy"),
    Column("HR1",         ("FW_HR1",),      "HR1 (peak detection); -1 when HR1_SQI == 0",         "bpm",      "float", FW_COMPUTED, "legacy"),
    Column("HR1_SQI",     ("FW_HR1_SQI",),  "HR1 validity, 0/1",                                  "flag",     "float", FW_COMPUTED, "legacy"),
    Column("HR2",         ("FW_HR2",),      "HR2 (autocorrelation); -1 when HR2_SQI == 0",        "bpm",      "float", FW_COMPUTED, "legacy"),
    Column("HR2_SQI",     ("FW_HR2_SQI",),  "HR2 validity, 0/1",                                  "flag",     "float", FW_COMPUTED, "legacy"),
    Column("HR3",         ("FW_HR3",),      "HR3 (FFT + harmonic product spectrum); -1 when HR3_SQI == 0", "bpm", "float", FW_COMPUTED, "legacy"),
    Column("HR3_SQI",     ("FW_HR3_SQI",),  "HR3 validity, 0/1",                                  "flag",     "float", FW_COMPUTED, "legacy"),
    Column("RSQI",        ("FW_RSQI",),     "RSQM raw-signal quality index",                      "index",    "int",   FW_COMPUTED, "legacy"),
    Column("DiagCode",    ("FW_DiagCode",), "RSQM diagnostic flags (RSQM_DIAG_*, incunest_afe4490.h)", "bitmask", "int", FW_COMPUTED, "legacy"),
    Column("ProbeState",  ("FW_ProbeState",), "RSQM probe state (ProbeState enum, incunest_afe4490.h)", "enum",  "int",   FW_COMPUTED, "legacy"),
    Column("V_TIA_LED1",  ("FW_V_TIA_LED1",),  "TIA output voltage, LED1 phase (closed-form from the code and afe_rf1_ohm, F5)", "V", "float", DERIVABLE, "legacy"),
    Column("V_TIA_LED2",  ("FW_V_TIA_LED2",),  "TIA output voltage, LED2 phase",                "V",        "float", DERIVABLE, "legacy"),
    Column("V_TIA_ALED1", ("FW_V_TIA_ALED1",), "TIA output voltage, ambient after LED1",        "V",        "float", DERIVABLE, "legacy"),
    Column("V_TIA_ALED2", ("FW_V_TIA_ALED2",), "TIA output voltage, ambient after LED2",        "V",        "float", DERIVABLE, "legacy"),
    Column("I_PD_LED1",   ("FW_I_PD_LED1",),   "photodiode current, LED1 phase (V_TIA / RF, AMBDAC and stage 2 undone)", "A", "float", DERIVABLE, "legacy"),
    Column("I_PD_LED2",   ("FW_I_PD_LED2",),   "photodiode current, LED2 phase",                "A",        "float", DERIVABLE, "legacy"),
    Column("I_PD_ALED1",  ("FW_I_PD_ALED1",),  "photodiode current, ambient after LED1",        "A",        "float", DERIVABLE, "legacy"),
    Column("I_PD_ALED2",  ("FW_I_PD_ALED2",),  "photodiode current, ambient after LED2",        "A",        "float", DERIVABLE, "legacy"),
    Column("OT_LED1",     ("FW_OT_LED1",),     "optical transmission LED1: (I_PD_LED1 - I_PD_ALED1) / I_LED1, as the firmware prints it (%.4e)", "A/A", "float", DERIVABLE, "legacy"),
    Column("OT_LED2",     ("FW_OT_LED2",),     "optical transmission LED2",                     "A/A",      "float", DERIVABLE, "legacy"),
    Column("CH_MASKS",    ("FW_CH_MASKS",),    "per-channel RSQM masks packed as a bit field",  "bitmask",  "int",   FW_COMPUTED, "legacy"),
    Column("RF1_OHM",     ("FW_RF1_OHM",),     "TIA feedback resistor LED1 at this sample; leaves the columns for the afe: snapshot once R21a is live", "ohm", "int", CONFIG, "legacy"),
    Column("RF2_OHM",     ("FW_RF2_OHM",),     "TIA feedback resistor LED2 at this sample",     "ohm",      "int",   CONFIG, "legacy"),
    # host column of the recorder/lab CSVs of 2026; v0.4 replaces it with clock anchors (R12/R15)
    Column("HOST_T_US",   (),                  "host epoch at datagram arrival (legacy column; v0.4: `clock:` anchors)", "us", "int", HOST, "legacy"),
    # new in v0.4 (R20/F8/F9): the lossless fixed-point signal of P0
    Column("OT1_E10",     (),  "OT_LED1 as an integer in units of 1e-10 A/A, computed by the writer from the codes (F9: round-trips LED-ALED within 0.44 code)", "1e-10 A/A", "int", DERIVABLE, "0.4"),
    Column("OT2_E10",     (),  "OT_LED2 in units of 1e-10 A/A",                                 "1e-10 A/A", "int", DERIVABLE, "0.4"),
]

# ── keys ─────────────────────────────────────────────────────────────────────────────────────
# domain: id (R17/R26 identity and provenance), session (R26, host/operator), clock (R12b anchors
# and every `@row` line), afe / timing / alg (the three R24 snapshots).
CFG, TCFG, LCFG = "$CFG", "$TCFG", "$LCFG"

KEYS = [
    # identity and provenance -- straight off $CFG, strings copied verbatim
    Key("source_mac", "id", (CFG, ("mac",),    None), "board WiFi STA MAC, the file's source identity (R2)", "text", "str", FW_MEASURED, "0.4"),
    Key("board",      "id", (CFG, ("board",),  None), "board revision (incunest_V17/V18)",                    "text", "str", FW_MEASURED, "0.4"),
    Key("fw",         "id", (CFG, ("fw",),     None), "PulseNest firmware version",                           "text", "str", FW_MEASURED, "0.4"),
    Key("lib",        "id", (CFG, ("lib",),    None), "incunest_afe4490 version",                             "text", "str", FW_MEASURED, "0.4"),
    Key("build",      "id", (CFG, ("build",),  None), "PulseNest git commit the image was built from",        "text", "str", FW_MEASURED, "0.4"),
    Key("libsha",     "id", (CFG, ("libsha",), None), "incunest_afe4490 git commit",                          "text", "str", FW_MEASURED, "0.4"),
    Key("elfsha",     "id", (CFG, ("elfsha",), None), "first 8 bytes of the image's ELF SHA-256: the image itself", "text", "str", FW_MEASURED, "0.4"),
    Key("idfver",     "id", (CFG, ("idfver",), None), "ESP-IDF version the image was built with",             "text", "str", FW_MEASURED, "0.4"),

    # session -- the R26 header keys the host or the operator supply
    Key("format",      "session", None, "container version, incunest_csv/N (R41)",                "text", "str", HOST,     "0.4"),
    Key("profile",     "session", None, "P0..P4, which columns and rate this file carries (section I)", "text", "str", HOST, "0.4"),
    Key("writer",      "session", None, "program and version that wrote the file",                "text", "str", HOST,     "0.4"),
    Key("t0_iso",      "session", None, "wall clock at open, ISO 8601 local with offset",         "text", "str", HOST,     "0.4"),
    Key("t0_epoch_us", "session", None, "host epoch at open",                                     "us",   "int", HOST,     "0.4"),
    Key("t0_fw_ts_us", "session", None, "firmware Ts_us of the first row",                        "us",   "int", HOST,     "0.4"),
    Key("t0_smpcnt",   "session", None, "firmware SmpCnt of the first row",                       "count","int", HOST,     "0.4"),
    Key("subject",     "session", None, "coded subject, SUBJnn or SIM -- never a name (R27)",     "text", "str", OPERATOR, "0.4"),
    Key("site",        "session", None, "coded site, BENCH / HOSPnn / SITEnn (R16/R27)",          "text", "str", OPERATOR, "0.4"),
    Key("condition",   "session", None, "subject condition slug at open, [A-Z0-9-]",              "text", "str", OPERATOR, "0.4"),
    Key("session_id",  "session", None, "recorder session directory name",                       "text", "str", HOST,     "0.4"),
    Key("part",        "session", None, "part number of this file within the session (R33)",     "count","int", HOST,     "0.4"),
    Key("prev",        "session", None, "previous part, pNN (R33)",                               "text", "str", HOST,     "0.4"),
    Key("decimation",  "session", None, "rows kept per firmware sample, 1 = every one",            "count","int", HOST,     "0.4"),
    Key("led1",        "session", None, "wavelength on LED1 for this board+probe, IR (R23)",      "text", "str", OPERATOR, "0.4"),
    Key("led2",        "session", None, "wavelength on LED2, RED (R23)",                          "text", "str", OPERATOR, "0.4"),
    Key("probe",       "session", None, "OUR probe's physical model -- operator-entered, always (R23, D12)", "text", "str", OPERATOR, "0.4"),

    # clock and @row lines
    Key("cause",         "clock", (CFG, ("cause",), None), "why this snapshot exists: open | set | hgac | restart | query | boot", "text", "str", FW_MEASURED, "0.4"),
    Key("smpcnt",        "clock", None, "SmpCnt of the row an anchor or event refers to",           "count", "int", FW_MEASURED, "0.4"),
    Key("fw_ts_us",      "clock", (CFG, ("ts_us",), 1), "firmware esp_timer microseconds: of the anchored row, or of the moment a $CFG's configuration became true (fw 0.15)", "us", "int", FW_MEASURED, "0.4"),
    Key("host_epoch_us", "clock", None, "host epoch of the anchored row's datagram",                "us",    "int", HOST,        "0.4"),

    # afe: -- the AFE4490 analog registers, one representation each, integers in natural units (R24a)
    Key("afe_prf_hz",        "afe", (CFG, ("sr",),                 1),    "pulse repetition frequency (sample rate)",         "Hz",  "int", CONFIG, "0.4"),
    Key("afe_numav",         "afe", (CFG, ("numav",),              1),    "ADC averages per conversion",                      "count","int", CONFIG, "0.4"),
    Key("afe_iled1_ua",      "afe", (CFG, ("led1",),               1000), "LED1 drive current (wire prints mA)",              "uA",  "int", CONFIG, "0.4"),
    Key("afe_iled2_ua",      "afe", (CFG, ("led2",),               1000), "LED2 drive current",                               "uA",  "int", CONFIG, "0.4"),
    Key("afe_iled_range_ma", "afe", (CFG, ("range",),              1),    "LED current full-scale range (50 / 75 / 100 mA)",  "mA",  "int", CONFIG, "0.4"),
    Key("afe_sep_gain",      "afe", (CFG, ("ensepgain",),          1),    "separate TIA gain per LED (ENSEPGAIN)",             "flag","int", CONFIG, "0.4"),
    Key("afe_rf1_ohm",       "afe", (CFG, ("rf1_ohm", "tia1"),     1),    "TIA feedback resistor, LED1 (RF: 10k..1M, 7 values)", "ohm", "int", CONFIG, "0.4"),
    Key("afe_cf1_pf",        "afe", (CFG, ("cf1_pF", "cf1"),       1),    "TIA feedback capacitor, LED1",                     "pF",  "int", CONFIG, "0.4"),
    Key("afe_rg1_ohm",       "afe", (CFG, ("rg1_ohm", "stg21", "rg1_x"), 1), "stage 2 gain resistor, LED1 (0 = stage 2 off)", "ohm", "int", CONFIG, "0.4"),
    Key("afe_stg2en1",       "afe", (CFG, ("stage2en1",),          1),    "stage 2 enabled, LED1",                             "flag","int", CONFIG, "0.4"),
    Key("afe_rf2_ohm",       "afe", (CFG, ("rf2_ohm", "tia2"),     1),    "TIA feedback resistor, LED2",                      "ohm", "int", CONFIG, "0.4"),
    Key("afe_cf2_pf",        "afe", (CFG, ("cf2_pF", "cf2"),       1),    "TIA feedback capacitor, LED2",                     "pF",  "int", CONFIG, "0.4"),
    Key("afe_rg2_ohm",       "afe", (CFG, ("rg2_ohm", "stg22", "rg2_x"), 1), "stage 2 gain resistor, LED2",                  "ohm", "int", CONFIG, "0.4"),
    Key("afe_stg2en2",       "afe", (CFG, ("stage2en2",),          1),    "stage 2 enabled, LED2",                             "flag","int", CONFIG, "0.4"),
    Key("afe_ambdac_ua",     "afe", (CFG, ("ambdac",),             1),    "ambient cancellation DAC current",                 "uA",  "int", CONFIG, "0.4"),
    Key("afe_ri_ohm",        "afe", (CFG, ("ri_ohm",),             1),    "input resistor of the TIA network (board constant)", "ohm", "int", CONFIG, "0.4"),

    # timing: -- the 28 timer registers of $TCFG, datasheet names; counts of the 4 MHz AFE clock
    Key("afe_led2stc",     "timing", (TCFG, ("t1",),  1), "LED2 sample start",                   "count", "int", CONFIG, "0.4"),
    Key("afe_led2endc",    "timing", (TCFG, ("t2",),  1), "LED2 sample end",                     "count", "int", CONFIG, "0.4"),
    Key("afe_led2ledstc",  "timing", (TCFG, ("t3",),  1), "LED2 pulse start",                    "count", "int", CONFIG, "0.4"),
    Key("afe_led2ledendc", "timing", (TCFG, ("t4",),  1), "LED2 pulse end",                      "count", "int", CONFIG, "0.4"),
    Key("afe_aled2stc",    "timing", (TCFG, ("t5",),  1), "ambient-after-LED2 sample start",     "count", "int", CONFIG, "0.4"),
    Key("afe_aled2endc",   "timing", (TCFG, ("t6",),  1), "ambient-after-LED2 sample end",       "count", "int", CONFIG, "0.4"),
    Key("afe_led1stc",     "timing", (TCFG, ("t7",),  1), "LED1 sample start",                   "count", "int", CONFIG, "0.4"),
    Key("afe_led1endc",    "timing", (TCFG, ("t8",),  1), "LED1 sample end",                     "count", "int", CONFIG, "0.4"),
    Key("afe_led1ledstc",  "timing", (TCFG, ("t9",),  1), "LED1 pulse start",                    "count", "int", CONFIG, "0.4"),
    Key("afe_led1ledendc", "timing", (TCFG, ("t10",), 1), "LED1 pulse end",                      "count", "int", CONFIG, "0.4"),
    Key("afe_aled1stc",    "timing", (TCFG, ("t11",), 1), "ambient-after-LED1 sample start",     "count", "int", CONFIG, "0.4"),
    Key("afe_aled1endc",   "timing", (TCFG, ("t12",), 1), "ambient-after-LED1 sample end",       "count", "int", CONFIG, "0.4"),
    Key("afe_led2convst",  "timing", (TCFG, ("t13",), 1), "LED2 ADC conversion start",           "count", "int", CONFIG, "0.4"),
    Key("afe_led2convend", "timing", (TCFG, ("t14",), 1), "LED2 ADC conversion end",             "count", "int", CONFIG, "0.4"),
    Key("afe_aled2convst", "timing", (TCFG, ("t15",), 1), "ambient-after-LED2 conversion start", "count", "int", CONFIG, "0.4"),
    Key("afe_aled2convend","timing", (TCFG, ("t16",), 1), "ambient-after-LED2 conversion end",   "count", "int", CONFIG, "0.4"),
    Key("afe_led1convst",  "timing", (TCFG, ("t17",), 1), "LED1 ADC conversion start",           "count", "int", CONFIG, "0.4"),
    Key("afe_led1convend", "timing", (TCFG, ("t18",), 1), "LED1 ADC conversion end",             "count", "int", CONFIG, "0.4"),
    Key("afe_aled1convst", "timing", (TCFG, ("t19",), 1), "ambient-after-LED1 conversion start", "count", "int", CONFIG, "0.4"),
    Key("afe_aled1convend","timing", (TCFG, ("t20",), 1), "ambient-after-LED1 conversion end",   "count", "int", CONFIG, "0.4"),
    Key("afe_adcrststct0", "timing", (TCFG, ("t21",), 1), "ADC reset pulse 0 start",             "count", "int", CONFIG, "0.4"),
    Key("afe_adcrstendct0","timing", (TCFG, ("t22",), 1), "ADC reset pulse 0 end",               "count", "int", CONFIG, "0.4"),
    Key("afe_adcrststct1", "timing", (TCFG, ("t23",), 1), "ADC reset pulse 1 start",             "count", "int", CONFIG, "0.4"),
    Key("afe_adcrstendct1","timing", (TCFG, ("t24",), 1), "ADC reset pulse 1 end",               "count", "int", CONFIG, "0.4"),
    Key("afe_adcrststct2", "timing", (TCFG, ("t25",), 1), "ADC reset pulse 2 start",             "count", "int", CONFIG, "0.4"),
    Key("afe_adcrstendct2","timing", (TCFG, ("t26",), 1), "ADC reset pulse 2 end",               "count", "int", CONFIG, "0.4"),
    Key("afe_adcrststct3", "timing", (TCFG, ("t27",), 1), "ADC reset pulse 3 start",             "count", "int", CONFIG, "0.4"),
    Key("afe_adcrstendct3","timing", (TCFG, ("t28",), 1), "ADC reset pulse 3 end",               "count", "int", CONFIG, "0.4"),
    Key("afe_prpcount",    "timing", None, "pulse repetition period, 4 MHz counts: 4e6 / afe_prf_hz - 1 (not on the wire)", "count", "int", DERIVABLE, "0.4"),

    # alg: -- library parameters; from $CFG (display/HR/SpO2 corners) and $LCFG (RSQM, HGAC)
    Key("ppgdisp_channel",      "alg", (CFG,  ("ch",),    None), "display channel, LED1 or LED2 (AFE4490Config field name)", "text", "str", CONFIG, "0.4"),
    Key("ppgdisp_f_low_mhz",    "alg", (CFG,  ("fl",),    1000), "display band-pass low corner (wire prints Hz)",       "mHz",  "int",   CONFIG, "0.4"),
    Key("ppgdisp_f_high_mhz",   "alg", (CFG,  ("fh",),    1000), "display band-pass high corner",                       "mHz",  "int",   CONFIG, "0.4"),
    Key("hr2_f_low_mhz",        "alg", (CFG,  ("hr2l",),  1000), "HR2 band-pass low corner",                            "mHz",  "int",   CONFIG, "0.4"),
    Key("hr2_f_high_mhz",       "alg", (CFG,  ("hr2h",),  1000), "HR2 band-pass high corner",                           "mHz",  "int",   CONFIG, "0.4"),
    Key("hr3_f_high_mhz",       "alg", (CFG,  ("hr3h",),  1000), "HR3 low-pass corner",                                 "mHz",  "int",   CONFIG, "0.4"),
    Key("spo2_cal_a",           "alg", (CFG,  ("spo2a",), 1),    "SpO2 = a - b*R calibration, a (dimensionless: a real is allowed, R24a)", "ratio", "float", CONFIG, "0.4"),
    Key("spo2_cal_b",           "alg", (CFG,  ("spo2b",), 1),    "SpO2 = a - b*R calibration, b",                       "ratio", "float", CONFIG, "0.4"),
    Key("rsqm_ot_thr_e10",      "alg", (LCFG, ("rsqm_ot_thr",),              1e10), "OT below which the probe is not on tissue (wire prints A/A as %.4e)", "1e-10 A/A", "int", CONFIG, "0.4"),
    Key("rsqm_disconn_led_sub_thr", "alg", (LCFG, ("rsqm_disconn_led_sub_thr",), 1), "|LED-ALED| below which the probe reads as disconnected", "LSB", "int", CONFIG, "0.4"),
    Key("rsqm_disconn_i_pd_thr_pa", "alg", (LCFG, ("rsqm_disconn_i_pd_thr",),   1e12), "|i_pd| below which the probe reads as disconnected (wire prints A)", "pA", "int", CONFIG, "0.4"),
    Key("rsqm_probe_state_min_ms",  "alg", (LCFG, ("rsqm_probe_state_min_s",),  1000), "probe-state debounce (wire prints s)",           "ms",   "int",   CONFIG, "0.4"),
    Key("hgac_enable",          "alg", (LCFG, ("hgac_enable",),          1),    "HGAC master enable",                                 "flag", "int",   CONFIG, "0.4"),
    Key("hgac_v_tia_high2_mv",  "alg", (LCFG, ("hgac_v_tia_high2",),     1000), "guard: lower RF urgently above this v_tia (fast EMA; wire prints V)", "mV", "int", CONFIG, "0.4"),
    Key("hgac_v_tia_high1_mv",  "alg", (LCFG, ("hgac_v_tia_high1",),     1000), "leveling: lower RF above this (slow EMA)",          "mV",   "int",   CONFIG, "0.4"),
    Key("hgac_v_tia_low1_mv",   "alg", (LCFG, ("hgac_v_tia_low1",),      1000), "leveling: raise RF below this (slow EMA)",          "mV",   "int",   CONFIG, "0.4"),
    Key("hgac_ema_fast_tau_ms", "alg", (LCFG, ("hgac_ema_fast_tau_s",),  1000), "guard EMA time constant (wire prints s)",           "ms",   "int",   CONFIG, "0.4"),
    Key("hgac_ema_slow_tau_ms", "alg", (LCFG, ("hgac_ema_slow_tau_s",),  1000), "leveling EMA time constant",                        "ms",   "int",   CONFIG, "0.4"),
    Key("hgac_ema_ambient_tau_ms", "alg", (LCFG, ("hgac_ema_ambient_tau_s",), 1000), "ambient EMA time constant",                    "ms",   "int",   CONFIG, "0.4"),
    Key("hgac_rf_changes",      "alg", (CFG,  ("hgac_rf_changes",), 1), "RF moves HGAC has applied since boot (fw 0.15); a jump > 1 between snapshots means moves landed inside one 50 ms tick", "count", "int", FW_COMPUTED, "0.4"),
]

# ── lookup tables (built once from the lists above; the only code in this file) ──────────────
COLUMN_BY_NAME = {c.name: c for c in COLUMNS}
KEY_BY_NAME    = {k.name: k for k in KEYS}
# any column name ever written -> canonical
COLUMN_CANON   = {s: c.name for c in COLUMNS for s in (c.name, *c.synonyms)}
# (frame, wire key) -> canonical key, e.g. ("$CFG", "tia1") -> "afe_rf1_ohm"
WIRE_TO_KEY    = {(k.wire[0], w): k.name for k in KEYS if k.wire for w in k.wire[1]}
