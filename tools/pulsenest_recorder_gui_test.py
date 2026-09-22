"""Offscreen checks for tools/pulsenest_recorder_gui.py — the window an operator actually uses.

Builds the real Qt window against a real Recorder writing to a temporary directory, with a fake
hub client, then drives the controls the way a person does and reads what reached the FILES.
Needs neither a hub nor a board:

    python tools/pulsenest_recorder_gui_test.py

What it is checking, and why each one earns its place. The window's whole reason to exist is to
reduce human error, so the checks are about the guard rails rather than about pixels:

* **every control ends in a console command** — one code path with the headless recorder, which
  is the design rule the window is built on. Verified by reading the events file, not by trusting
  the button;
* **nothing is enabled before a subject is bound**, because an unattributed reading is nearly
  worthless with three babies in the room;
* **an edit or a delete never rewrites a file**: the effective list changes, the file grows. A
  CORRECT keeps the reading's own time, since the click happened when it happened;
* **the header warns while something is wrong** (no subject, no condition, gaps, silence) rather
  than only when someone asks;
* **closing asks first**, and Ctrl+C is not a way out of a session.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pulsenest_recorder_gui as G  # noqa: E402
from PyQt5 import QtWidgets          # noqa: E402

# Before a window exists: closeEvent saves geometry, and a test must never touch the real .ini.
G.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_recorder_gui_test.ini")
if os.path.exists(G.SETTINGS_FILE):
    os.remove(G.SETTINGS_FILE)

print(f"== {os.path.basename(__file__)} ==  offscreen checks of the recorder window")

ok = []


def type_subject(row, text):
    """What an operator does: type into the box and press Enter. `setCurrentText` alone changes
    the text without emitting `editingFinished`, so a test that used it was not exercising the
    path the window actually runs."""
    row.subject.setCurrentText(text)
    row.subject.lineEdit().editingFinished.emit()


def check(msg, cond, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg + (f"  [{detail}]" if detail and not cond else ""))


class QuietLog:
    def __getattr__(self, _):
        return lambda *a, **k: None


class FakeClient:
    """The hub, absent. The window must not care: it feeds the recorder from what it receives."""

    def recv(self, _):
        return None

    def connect(self):
        return True

    def close(self):
        pass


G.HubClient = lambda *a, **k: FakeClient()
_answers = {"value": QtWidgets.QMessageBox.Yes}
QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: _answers["value"])

app = QtWidgets.QApplication([])
out = tempfile.mkdtemp()
rec = G.Recorder(out, "BENCH", "AC", log=QuietLog())
win = G.RecorderWindow(rec, ("127.0.0.1", 15999))

MAC = "10:20:BA:14:75:60"
rec.feed("192.168.1.50", f"$CFG,mac={MAC},board=V18,fw=0.14\n".encode())
win.traces["192.168.1.50"] = G.BoardTrace("192.168.1.50", 0.0, 15.0)
win.redraw()
row = list(win.rows.values())[0]

# ── a row appears per board, keyed by MAC ────────────────────────────────────────────────────
check("one row per board, keyed by its MAC once the board says who it is",
      list(win.rows) == [MAC] and row.src is not None and row.src.mac == MAC, list(win.rows))
check("nothing but SUBJECT is usable before a subject is bound",
      row.subject.isEnabled() and not row.record.isEnabled()
      and not row.condition.isEnabled() and not row.vn_on.isEnabled())
check("the header says UNBOUND and warns, without anyone asking",
      "UNBOUND" in row.counters.text() and "no subject" in row.warn.text(),
      row.counters.text() + " | " + row.warn.text())

# ── binding a subject goes through the console, and opens the rest ───────────────────────────
type_subject(row, "SUBJ01")
check("choosing a subject binds the board through the console command",
      rec.sources["192.168.1.50"].subject == "SUBJ01" and row.record.isEnabled())

# The subject code is the only link between a capture and a person, so what the box REFUSES
# matters more than what it accepts. A free-text subject is how a real name reaches every file.
for bad in ("Maria", "bed 4", "SUBJ", "S01", "12"):
    type_subject(row, bad)
    if rec.sources["192.168.1.50"].subject != "SUBJ01":
        break
check("a name, a bed number or a malformed code is refused and changes nothing",
      rec.sources["192.168.1.50"].subject == "SUBJ01" and row.subject.currentText() == "",
      rec.sources["192.168.1.50"].subject)
check("and the refusal says so instead of failing silently",
      "not a subject code" in win.log_line.text(), win.log_line.text())
type_subject(row, "subj7")
check("a short code is normalised, so SUBJ7 and SUBJ07 cannot become two babies",
      rec.sources["192.168.1.50"].subject == "SUBJ07", rec.sources["192.168.1.50"].subject)
type_subject(row, "SUBJ13")
check("the menu is not a ceiling: the thirteenth baby of a campaign can be typed",
      rec.sources["192.168.1.50"].subject == "SUBJ13" and row.subject.findText("SUBJ13") >= 0
      and len(G.SUBJECTS) == 12, str(len(G.SUBJECTS)))
type_subject(row, "SUBJ01")

# ── the one reference control: which phone is filming THIS cot ───────────────────────────────
# Five tick boxes became one (Alex, 2026-09-22). `operator annotation` was always on -- it is the
# panel to the right -- and the other three change nothing about what this window records.
src = rec.sources["192.168.1.50"]
check("the panel offers one reference control, not a list of things it does not record",
      hasattr(row, "vn_on") and hasattr(row, "vn_id") and not hasattr(row, "refs"))
rec.feed("192.168.1.99", b"$VN1,1,89,0.95,2026-09-22 00:21:26.261,J6plusACM*3D\n")
row.refresh_phones()
check("the device list fills itself from the phones actually heard, never from a fixed menu",
      [row.vn_id.itemText(i) for i in range(row.vn_id.count())] == ["J6plusACM"],
      str([row.vn_id.itemText(i) for i in range(row.vn_id.count())]))
row.vn_id.setCurrentText("J6plusACM")
row.vn_on.setChecked(True)
check("ticking it names that phone as this baby's reference, through the console command",
      rec.videonest_id == "J6plusACM", str(rec.videonest_id))
row.vn_on.setChecked(False)
check("unticking clears it: this baby has no VideoNest reference",
      rec.videonest_id is None, str(rec.videonest_id))
row.vn_id.setCurrentText("J6plusACM")
row.vn_on.setChecked(True)

# ── condition ────────────────────────────────────────────────────────────────────────────────
row.condition.setCurrentIndex(1)
row.condition.activated.emit(1)
check("the condition reaches the recorder when it is chosen, not per keystroke",
      src.condition == "RESTING", str(src.condition))
win.redraw()          # the header is written by redraw(), ten times a second in a real session
check("the header stops warning once subject and condition are known",
      row.warn.text() == "" and "SUBJ01" in row.counters.text(), repr(row.warn.text()))

# ── readings ─────────────────────────────────────────────────────────────────────────────────
for spo2, pr in ((96, 140), (97, G.PR_NONE), (95, 138)):
    row.spo2.setValue(spo2)
    row.pr.setValue(pr)
    row._record()
check("the list holds every reading, newest first",
      row.listing.rowCount() == 3 and row.listing.item(0, 1).text() == "95",
      [row.listing.item(i, 1).text() for i in range(row.listing.rowCount())])
check("an omitted pulse rate shows -- and is stored as empty, not as a zero",
      row.listing.item(1, 2).text() == "--" and rec.readings("SUBJ01")[1]["pr"] == "")

middle = int(row.listing.item(1, 3).text())
taken_at = [r for r in rec.readings("SUBJ01") if r["id"] == middle][0]["t_epoch_us"]
win.command(f"correct {middle} 93 120")
row.refresh_listing()
fixed = [r for r in rec.readings("SUBJ01") if r["id"] == middle][0]
check("a corrected reading shows its new value, marked, and KEEPS ITS OWN TIME",
      row.listing.item(1, 1).text() == "93 *" and row.listing.item(1, 2).text() == "120"
      and fixed["t_epoch_us"] == taken_at, row.listing.item(1, 1).text())

row._delete_last()
check("DELETE LAST withdraws the newest reading of that subject",
      row.listing.rowCount() == 2 and row.listing.item(0, 1).text() == "93 *")
row.listing.selectRow(1)
row._delete_selected()
check("DELETE selected withdraws the one the operator picked", row.listing.rowCount() == 1)

_answers["value"] = QtWidgets.QMessageBox.No
row.listing.selectRow(0)
row._delete_selected()
check("answering No to the confirmation withdraws nothing", row.listing.rowCount() == 1)
_answers["value"] = QtWidgets.QMessageBox.Yes

check("the effective list drops the withdrawn readings; the recorder still has them all",
      len(rec.readings("SUBJ01")) == 1 and len(rec.readings("SUBJ01", include_retracted=True)) == 3)

# ── notes and the session bar ────────────────────────────────────────────────────────────────
row.note.setText("probe on left foot")
row._note_entered()
check("a note is attributed to the subject and the box clears", row.note.text() == "")
win.plots.setChecked(False)
check("PLOTS off hides the waveform and leaves everything else recording",
      not win.plots_on and not row.plot_w.isVisible())
win.plots.setChecked(True)

# ── ABNORMAL CONDITION: a toggle, not a pause ─────────────────────────────────────────────────
row.flag_btn.setChecked(True)
win.redraw()
check("the toggle writes flag on through the console, and the recorder agrees",
      rec.sources["192.168.1.50"].flagged and row.flag_btn.isChecked())
row.flag_btn.setChecked(False)
win.redraw()
check("toggling it off clears the flag -- reversible, unlike a dropped interval",
      not rec.sources["192.168.1.50"].flagged)
check("both are on disk as a start/end pair, never a gap",
      "ANOMALY_START" in open(rec.events_path, encoding="utf-8").read()
      and "ANOMALY_END" in open(rec.events_path, encoding="utf-8").read())

# ── the four monitor fields: read-only, typed on the command line ────────────────────────────
check("with none set, the panel says so plainly",
      row.ref_label.text() == "(not set)")
rec.console("ref SUBJ01 model Masimo Radical-7")
rec.console("ref SUBJ01 avg 8")
rec.console("ref SUBJ01 site right hand")
win.redraw()
check("once set, the panel shows them -- a QLabel, so the window cannot type into it",
      "Masimo Radical-7" in row.ref_label.text() and "avg 8s" in row.ref_label.text()
      and "right hand" in row.ref_label.text()
      and isinstance(row.ref_label, QtWidgets.QLabel),
      row.ref_label.text())

# ── OUR probe's model: same read-only principle, a separate field from the ref monitor's ─────
check("with none set, PROBE says so plainly too",
      row.probe_label.text() == "(not set)")
rec.console("probe SUBJ01 Medle-neo")
win.redraw()
check("once set, PROBE shows it, distinct from MONITOR and from ProbeState",
      row.probe_label.text() == "Medle-neo" and "Medle-neo" not in row.ref_label.text(),
      row.probe_label.text())


row.fold.setChecked(False)
check("a row folds to its header line, and the header keeps updating",
      not row.body.isVisible() and row.title.text() != "")
win.redraw()
row.fold.setChecked(True)

# ── closing ──────────────────────────────────────────────────────────────────────────────────
_answers["value"] = QtWidgets.QMessageBox.No
win.close()
check("closing asks first, and No keeps the session open",
      not rec.stopped and not getattr(rec, "_closed", False))
_answers["value"] = QtWidgets.QMessageBox.Yes
win.close()
check("Yes closes every file and writes SESSION_END", getattr(rec, "_closed", False))
# The timers must be stopped BEFORE the socket, and the client must stay shut. Left running they
# fired on a dead socket, and HubClient answered by launching a pulsenest_hub.py process while
# logging once per iteration: 80 296 lines into a real session directory (2026-09-21).
check("closing stops every timer, so none can fire on a closed socket",
      win.timers and not any(t.isActive() for t in win.timers),
      str([t.isActive() for t in win.timers]))
check("and a redraw or a drain after closing is a no-op, not a reconnect",
      (win.drain() or win.redraw() or win.tick()) is None and win._closing)
check("the geometry is remembered for the next session", os.path.exists(G.SETTINGS_FILE))

# ── the annotation list's columns fit their content ──────────────────────────────────────────
# Relative, never in pixels: the offscreen platform has no fonts and falls back to Helvetica 12
# at about 17 px per character, where the real desktop draws Segoe UI 9 at about 7. A pixel
# figure measured here would be meaningless; the proportions are not.
_head = row.listing.horizontalHeader()
_w = [_head.sectionSize(i) for i in range(4)]
check("PR is the narrowest column and id is narrower than SpO2's, as their contents are",
      _w[2] < _w[1] and _w[3] <= _w[1] and _w[2] < _w[0], str(_w))
check("only the time column stretches, so the id cannot swallow the leftover width",
      not _head.stretchLastSection()
      and _head.sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch
      and all(_head.sectionResizeMode(i) == QtWidgets.QHeaderView.Fixed for i in (1, 2, 3)))

# ── the window is dark, and everything written on it can be read ─────────────────────────────
def _luminance(hex_colour):
    """WCAG 2.1 relative luminance of an #rrggbb string."""
    ch = []
    for i in (1, 3, 5):
        v = int(hex_colour[i:i + 2], 16) / 255.0
        ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


check("the window sets the project's dark palette instead of inheriting the desktop's",
      G.BG == "#121212" and G.FG == "#E0E0E0" and "QWidget" in G.DARK_QSS
      and G.DARK_QSS in win.styleSheet(), G.BG)
# Every colour this window paints text in, against the ground it is painted on. The APPLIED
# green and the amber warning came from a dark-background tool; on the light default they were
# at 1.5:1 and 1.9:1, which is why the window looked wrong before it looked inconsistent.
worst = {}
for name, colour in (("body", G.FG), ("dim", G.FG_DIM), ("warning amber", G.AMBER),
                     ("alarm red", G.RED), ("probe applied green", "#44FF88")):
    worst[name] = round(contrast(colour, G.BG), 1)
check("every text colour clears 4.5:1 against the window's own background",
      all(v >= 4.5 for v in worst.values()), str(worst))
check("and each one would have FAILED on the white the window used to inherit",
      contrast("#44FF88", "#FFFFFF") < 2.0 and contrast(G.AMBER, "#FFFFFF") < 3.0,
      f"{contrast('#44FF88', '#FFFFFF'):.1f}, {contrast(G.AMBER, '#FFFFFF'):.1f}")

# ── what actually reached the disk: the only evidence that matters ───────────────────────────
rows = open(rec.events_path, encoding="utf-8").read().splitlines()
kinds = [r.split(",")[5] for r in rows[1:]]
# By shape, not by a count of METAs: every tick box and every subject is one META, so a magic
# number breaks the day a check touches one more control -- for the wrong reason.
check("the readings, their correction and their retractions are in the file, in order",
      [k for k in kinds if k not in ("META", "SESSION_START", "SESSION_END")]
      == ["REF_SPO2", "REF_SPO2", "REF_SPO2", "CORRECT", "RETRACT", "RETRACT", "NOTE",
          "ANOMALY_START", "ANOMALY_END"], kinds)
check("the session is bracketed by its start and end, and every change of a value is a META",
      kinds[0] == "SESSION_START" and kinds[-1] == "SESSION_END"
      and kinds.count("META") >= 6, f"{kinds.count('META')} METAs")
# Nine METAs for one subject, seven tick-box changes and one condition: every change of a session
# value is its own event on purpose. The file is an audit trail, so "the operator ticked VideoNest
# UDP, then thought better of it" is worth more than a tidy final state with no history.
check("nothing was ever rewritten: the retracted readings are still in the file",
      sum(1 for r in rows if ",REF_SPO2," in r) == 3 and sum(1 for r in rows if ",RETRACT," in r) == 2)
sj = open(os.path.join(rec.dir, "session.json"), encoding="utf-8").read()
check("reference_spo2.csv holds the readings the operator typed, and was written live",
      os.path.exists(rec.ref_path)
      and sum(1 for l in open(rec.ref_path, encoding="utf-8") if ",operator,AC,reading," in l) == 3)
check("session.json carries the site code and which phone was this baby's reference",
      '"site_code": "BENCH"' in sj and '"videonest_id": "J6plusACM"' in sj
      and '"videonest_seen"' in sj, sj[:120])

# ── --board must filter what the WINDOW shows, not only what the recorder writes ─────────────
# Alex, 2026-09-22: `--board 8850` on the bench still showed three rows. rec.feed() was already
# correct -- an ignored board is popped from rec.sources -- but drain() built its trace and row
# straight off the wire, checking rec.sources.get(ip) without ever asking rec.ignored. A separate
# Recorder/window here, fed through the REAL drain() (a queued FakeClient, not manual .feed()
# calls), because that is exactly the path the bug lived in and manual feeding would not see it.
class QueuedClient:
    def __init__(self):
        self.queue = []

    def recv(self, _):
        return self.queue.pop(0) if self.queue else None

    def connect(self):
        return True

    def close(self):
        pass


qc = QueuedClient()
G.HubClient = lambda *a, **k: qc
recF = G.Recorder(tempfile.mkdtemp(), "ACMHOME", "AC", log=QuietLog(), board="8850")
winF = G.RecorderWindow(recF, ("127.0.0.1", 15998))
for ip, mac in (("10.0.0.1", "10:51:DB:50:88:50"), ("10.0.0.2", "10:51:DB:50:82:5C"),
               ("10.0.0.3", "10:51:DB:50:87:A4")):
    qc.queue.append((ip, f"$CFG,mac={mac},board=V18\n".encode()))
winF.drain()
winF.redraw()
check("--board shows only the matching board, not all three seen on the wire",
      list(winF.traces) == ["10.0.0.1"] and list(winF.rows) == ["10:51:DB:50:88:50"],
      f"traces={list(winF.traces)} rows={list(winF.rows)}")
# More traffic from the wrong boards must not resurrect anything already torn down.
qc.queue.append(("10.0.0.2", b"$M4,4,1,1," + b",".join([b"1"] * 20) + b",2\n"))
qc.queue.append(("10.0.0.3", b"$M4,4,1,1," + b",".join([b"1"] * 20) + b",2\n"))
winF.drain()
winF.redraw()
check("and stays that way as the wrong boards keep talking",
      list(winF.rows) == ["10:51:DB:50:88:50"], list(winF.rows))
winF._closing = True
recF.stop("test")
winF.client.close()
recF.close()

# ── --config: a TOML session file, full substitution ─────────────────────────────────────────
import argparse as _argparse
import tomllib as _tomllib

cfg_dir = tempfile.mkdtemp()
cfg_path = os.path.join(cfg_dir, "subj01.toml")
open(cfg_path, "w", encoding="utf-8").write("""
location  = "HOSP01"
operator  = "AC"
board     = "8850"
subject   = "SUBJ01"
note      = "term neonate, resting after a feed"
probe     = "Medle-neo"

[ref]
model = "Masimo Radical-7"
avg   = 8
probe-site = "left thumb"
videonest  = "J6plusACM"
""")


def blank_args():
    return _argparse.Namespace(**{f: "" for f in G.CONFIG_FIELDS})


ns = blank_args()
G.apply_session_config(ns, cfg_path)
check("--config fills all eleven fields from the file, avg as a string like a typed flag would be",
      vars(ns) == {"location": "HOSP01", "operator": "AC", "board": "8850", "subject": "SUBJ01",
                   "videonest": "J6plusACM", "note": "term neonate, resting after a feed",
                   "probe": "Medle-neo", "ref_model": "Masimo Radical-7", "ref_avg": "8",
                   "ref_probe_site": "left thumb", "ref_note": ""}, vars(ns))

for field in G.CONFIG_FIELDS:
    conflicting = blank_args()
    setattr(conflicting, field, "x")
    try:
        G.apply_session_config(conflicting, cfg_path)
        ok.append(False)
        print(f"FAIL --config must refuse when --{field.replace('_','-')} is also given")
    except ValueError as exc:
        ok.append(f"--{field.replace('_','-')}" in str(exc))
check("full substitution: EVERY one of the ten fields, given alongside --config, is refused",
      True)  # the loop above recorded one PASS/FAIL per field; this line is just a section marker

try:
    G.apply_session_config(blank_args(), os.path.join(cfg_dir, "missing.toml"))
    check("a missing config file raises", False)
except OSError:
    check("a missing config file raises OSError, not a traceback the operator has to read", True)

bad_path = os.path.join(cfg_dir, "bad.toml")
open(bad_path, "w", encoding="utf-8").write("this is [[[ not toml")
try:
    G.apply_session_config(blank_args(), bad_path)
    check("malformed TOML raises", False)
except _tomllib.TOMLDecodeError:
    check("malformed TOML raises TOMLDecodeError, named clearly rather than crashing opaquely", True)

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if all(ok) else 1)
