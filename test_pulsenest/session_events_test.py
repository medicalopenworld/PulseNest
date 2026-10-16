"""Checks for pulsenest/session_events.py -- the ABNORMAL CONDITION stretches an analysis reads.
    python test_pulsenest/session_events_test.py
A synthetic session_events.csv covers the pairing rules (START/END per subject, session-wide `*`,
START while open, END without START, START never ended with and without SESSION_END); then
covered_fraction on windows that touch, straddle and miss the stretches; then, if the real
bench session of 2026-10-16 is on disk, its one flagged stretch comes back as recorded.
"""
import math, os, sys, tempfile
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root
from pulsenest import session_events as SE                           # noqa: E402

print(f"== {os.path.basename(__file__)} ==  session_events.csv -> flagged stretches")
ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))

HEADER = ("session_id,event_id,t_mono_us,t_epoch_us,iso_local,kind,subject,board_mac,"
          "value,value2,source,confidence,note\n")

def write_session(rows, with_end=True):
    """rows: (event_id, t_epoch_us, kind, subject). Returns the session directory."""
    d = tempfile.mkdtemp(prefix="pn_events_")
    with open(os.path.join(d, SE.EVENTS_FILE), "w", encoding="utf-8", newline="") as f:
        f.write(HEADER)
        f.write("S,0,0,1000,x,SESSION_START,*,*,,,keyboard,,\n")
        for eid, t, kind, subj in rows:
            f.write(f"S,{eid},0,{t},x,{kind},{subj},*,,,keyboard,,\n")
        if with_end:
            f.write("S,99,0,9000,x,SESSION_END,*,*,,,keyboard,,reason=operator\n")
    return d

warnings = []
warn = warnings.append

# -- 1. the plain case: one stretch per subject, one session-wide
d = write_session([
    (1, 2000, "ANOMALY_START", "SUBJ01"),
    (2, 3000, "ANOMALY_END", "SUBJ01"),
    (3, 4000, "ANOMALY_START", "SUBJ02"),
    (4, 4500, "ANOMALY_START", "*"),
    (5, 5000, "ANOMALY_END", "SUBJ02"),
    (6, 6000, "ANOMALY_END", "*"),
])
check("all subjects: three stretches, sorted by start",
      SE.anomaly_intervals(d, warn=warn) == [(2000, 3000), (4000, 5000), (4500, 6000)])
check("SUBJ01: its own plus the session-wide one",
      SE.anomaly_intervals(d, "subj01", warn=warn) == [(2000, 3000), (4500, 6000)])
check("SUBJ03 (never flagged): only the session-wide one",
      SE.anomaly_intervals(d, "SUBJ03", warn=warn) == [(4500, 6000)])
check("no warning in the plain case", warnings == [], str(warnings))

# -- 2. START while open, END without START
warnings.clear()
d = write_session([
    (1, 2000, "ANOMALY_START", "SUBJ01"),
    (2, 2500, "ANOMALY_START", "SUBJ01"),     # ignored: kept the first
    (3, 3000, "ANOMALY_END", "SUBJ01"),
    (4, 3500, "ANOMALY_END", "SUBJ01"),       # ignored: nothing open
])
check("second START while open is ignored, END without START is ignored",
      SE.anomaly_intervals(d, warn=warn) == [(2000, 3000)])
check("both ignored rows are reported, once each",
      len(warnings) == 2 and "event 2 " in warnings[0] and "event 4 " in warnings[1], str(warnings))

# -- 3. START never ended: closes at SESSION_END; without SESSION_END runs to infinity
warnings.clear()
d = write_session([(1, 2000, "ANOMALY_START", "SUBJ01")])
check("unterminated stretch ends at SESSION_END", SE.anomaly_intervals(d, warn=warn) == [(2000, 9000)])
check("ending at SESSION_END is not a warning", warnings == [], str(warnings))
d = write_session([(1, 2000, "ANOMALY_START", "SUBJ01")], with_end=False)
iv = SE.anomaly_intervals(d, warn=warn)
check("no SESSION_END: the stretch runs to math.inf", iv == [(2000, math.inf)])
check("...and that is a warning", len(warnings) == 1 and "never ended" in warnings[0], str(warnings))

# -- 4. a session without the file (older captures), and one with no flags
check("missing session_events.csv -> no events, no stretches",
      SE.events(tempfile.mkdtemp()) == [] and SE.anomaly_intervals(tempfile.mkdtemp()) == [])
d = write_session([(1, 2000, "NOTE", "SUBJ01"), (2, 2500, "REF_SPO2", "SUBJ01")])
check("events() returns every row", [r["kind"] for r in SE.events(d)] == ["SESSION_START", "NOTE", "REF_SPO2", "SESSION_END"])
check("no ANOMALY rows -> no stretches", SE.anomaly_intervals(d) == [])

# -- 5. covered_fraction
iv = [(2000, 3000), (4500, 6000)]
check("window fully outside -> 0", SE.covered_fraction(iv, 0, 1000) == 0.0)
check("window fully inside -> 1", SE.covered_fraction(iv, 2200, 2800) == 1.0)
check("window straddling the end of a stretch -> partial",
      abs(SE.covered_fraction(iv, 2500, 3500) - 0.5) < 1e-12)
check("window spanning both stretches and the gap between",
      abs(SE.covered_fraction(iv, 2000, 6000) - 2500 / 4000) < 1e-12)
check("overlapping intervals (`*` and a subject's) count once",
      abs(SE.covered_fraction([(2000, 4000), (3000, 5000)], 2000, 6000) - 0.75) < 1e-12)
check("open-ended stretch covers everything after it", SE.covered_fraction([(2000, math.inf)], 5000, 6000) == 1.0)
check("empty or inverted window -> 0",
      SE.covered_fraction(iv, 2500, 2500) == 0.0 and SE.covered_fraction(iv, 3000, 2000) == 0.0)

# -- 6. the real bench session of 2026-10-16, if present: one 1.4 s stretch on SUBJ67
real = os.path.join(os.path.dirname(_HERE), "captures", "sessions", "SUBJ67",
                    "SUBJ67_HOSPNAV_20261016_190031")
if os.path.isdir(real):
    warnings.clear()
    iv = SE.anomaly_intervals(real, "SUBJ67", warn=warn)
    check("real session: the ABNORMAL CONDITION press of 19:00:35 comes back as one stretch",
          iv == [(1792170035385949, 1792170036812816)] and warnings == [], f"{iv} {warnings}")
else:
    print("skip real session (not on this machine)")

n = len(ok)
print(f"\n{sum(ok)}/{n} checks passed — {'OK' if all(ok) else 'FAIL'}")
sys.exit(0 if all(ok) else 1)
