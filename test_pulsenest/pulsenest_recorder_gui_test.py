"""Offscreen checks for tools/pulsenest_recorder_gui.py — the window an operator actually uses.

Builds the real Qt window against a real Recorder writing to a temporary directory, with a fake
hub client, then drives the controls the way a person does and reads what reached the FILES.
Needs neither a hub nor a board:

    python test_pulsenest/pulsenest_recorder_gui_test.py

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
import re
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.pulsenest_recorder_gui as G  # noqa: E402
from PyQt5 import QtWidgets, QtCore  # noqa: E402
from PyQt5.QtTest import QTest       # noqa: E402

# Before a window exists: closeEvent saves geometry, and a test must never touch the real .ini.
G.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_recorder_gui_test.ini")
if os.path.exists(G.SETTINGS_FILE):
    os.remove(G.SETTINGS_FILE)

print(f"== {os.path.basename(__file__)} ==  offscreen checks of the recorder window")

ok = []


def bind(rec, row, text):
    """Binding goes through the Recorder's console (the window has no SUBJECT control since
    2026-10-14); the row then mirrors what the Recorder holds."""
    reply = rec.console(f"subject 7560 {text}")
    row.refresh(time.monotonic(), False)
    return reply


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
check("the bottom line names the session folder as a link that opens it, in a larger font; "
      "console replies have a line of their own",
      rec.dir in win.dir_line.text() and 'href="open"' in win.dir_line.text()
      and win.dir_line.receivers(win.dir_line.linkActivated) == 1
      and win.dir_line.font().pointSize() == win.log_line.font().pointSize() + 3
      and win.log_line.text() == "" and win.log_line.isHidden(), win.dir_line.text())

# ── a row appears per board, keyed by MAC ────────────────────────────────────────────────────
check("one row per board, keyed by its MAC once the board says who it is",
      list(win.rows) == [MAC] and row.src is not None and row.src.mac == MAC, list(win.rows))
check("nothing is usable before a subject is bound, and SUBJECT reads (not set)",
      not row.record.isEnabled() and not row.note.isEnabled() and not row.vn_on.isEnabled()
      and row.subject_label.text() == "(not set)" and not hasattr(row, "subject"),
      row.subject_label.text())
check("the header says UNBOUND and warns, without anyone asking",
      "UNBOUND" in row.counters.text() and "no subject" in row.warn.text(),
      row.counters.text() + " | " + row.warn.text())

# ── binding a subject goes through the console, and opens the rest ───────────────────────────
bind(rec, row, "SUBJ01")
check("a subject bound on the console shows in the panel and opens the rest",
      rec.sources["192.168.1.50"].subject == "SUBJ01" and row.subject_label.text() == "SUBJ01"
      and row.record.isEnabled() and row.note.isEnabled())

# The subject code is the only link between a capture and a person. The check lives in the
# Recorder (the one code path), not in the window, which only shows what the Recorder holds.
for bad in ("Maria", "bed 4", "SUBJ", "S01", "12"):
    reply = bind(rec, row, bad)
    if rec.sources["192.168.1.50"].subject != "SUBJ01":
        break
check("a name, a bed number or a malformed code is refused by the Recorder and changes nothing",
      rec.sources["192.168.1.50"].subject == "SUBJ01" and row.subject_label.text() == "SUBJ01"
      and "not a subject code" in reply, rec.sources["192.168.1.50"].subject + " | " + reply)
bind(rec, row, "subj7")
check("a short code is normalised, so SUBJ7 and SUBJ07 cannot become two babies",
      rec.sources["192.168.1.50"].subject == "SUBJ07", rec.sources["192.168.1.50"].subject)
bind(rec, row, "SUBJ01")

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

# -- the panel mirrors the Recorder (2026-09-22 rehearsal: a stray click re-bound SUBJ01 over SIM) --
rec.console("subject 7560 SIM")
rec.console("videonest none")
row.refresh(time.monotonic(), False)
check("after a console change SUBJECT shows what the Recorder holds (SIM)",
      row.subject_label.text() == "SIM" and rec.sources["192.168.1.50"].subject == "SIM", row.subject_label.text())
check("and the VideoNest box is unticked because the Recorder has no phone", not row.vn_on.isChecked())
check("no phone named: the line beside REFERENCE is blank", row.vn_live.text() == "")
n_events = rec.event_id
row.refresh(time.monotonic(), False)               # a refresh is a mirror, never a command
check("a refresh issues no command: SIM stays, no new event",
      rec.sources["192.168.1.50"].subject == "SIM" and rec.event_id == n_events and rec.videonest_id is None)
rec.console("videonest J6plusACM")
row.refresh(time.monotonic(), False)
check("a phone declared on the console appears ticked and named in the panel",
      row.vn_on.isChecked() and row.vn_id.currentText() == "J6plusACM")
# -- beside REFERENCE: what the phone last sent (Alex, 2026-10-15) --
check("beside REFERENCE: the phone's last SpO2 and confidence, green while frames keep coming",
      row.vn_live.text().startswith("SpO2 89  conf 0.95") and G.GREEN in row.vn_live.styleSheet(),
      row.vn_live.text())
rec.by_vn["J6plusACM"].vn_last_mono -= 40
row.refresh(time.monotonic(), False)
check("40 s without a frame: SILENT in red, the last reading still shown",
      row.vn_live.text().startswith("SILENT 40 s") and "SpO2 89" in row.vn_live.text()
      and G.RED in row.vn_live.styleSheet(), row.vn_live.text())
rec.by_vn["J6plusACM"].vn_last_mono += 40
rec.console("videonest Nokia2")
row.refresh(time.monotonic(), False)
check("a phone named but never heard: 'not heard yet' in amber",
      row.vn_live.text() == "not heard yet" and G.AMBER in row.vn_live.styleSheet(), row.vn_live.text())
rec.console("videonest J6plusACM")
row.refresh(time.monotonic(), False)
rec.console("subject 7560 SUBJ01")
row.refresh(time.monotonic(), False)

# ── CLOCK ANCHOR: the event, and the laptop clock on screen to be photographed ───────────────
n_before = rec.event_id
win._clock_anchor()
dlg = win.clock_dialog
check("CLOCK ANCHOR writes the CLOCK_ANCHOR event", rec.event_id == n_before + 1
      and ",CLOCK_ANCHOR," in open(rec.events_path, encoding="utf-8").read())
check("and shows the laptop clock with milliseconds, ticking",
      re.fullmatch(r"\d\d:\d\d:\d\d\.\d\d\d", dlg.clock.text()) is not None and dlg.timer.isActive(),
      dlg.clock.text())
dlg.close()
check("a click or Esc closes it and stops its timer", not dlg.timer.isActive())

# ── header (CONDITION left the window 2026-10-14; the console `cond` command remains) ──────
win.redraw()          # the header is written by redraw(), ten times a second in a real session
check("the header stops warning once the subject is known",
      row.warn.text() == "" and "SUBJ01" in row.counters.text(), repr(row.warn.text()))
check("no CONDITION control in the panel any more", not hasattr(row, "condition"))

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

# ── five widths the operator can drag, remembered in the .ini (Alex, 2026-10-15) ─────────────
check("the row's body is a splitter of four (plot, stats, session panel, readings box) and the "
      "readings box splits entry | table: five draggable widths, none collapsible",
      isinstance(row.split, QtWidgets.QSplitter) and row.split.count() == 4
      and row.split.widget(0) is row.plot_w and row.split.widget(1) is row.stats
      and isinstance(row.readings_split, QtWidgets.QSplitter) and row.readings_split.count() == 2
      and row.readings_split.widget(0) is row.entry_w and row.readings_split.widget(1) is row.listing
      and not row.split.childrenCollapsible() and not row.readings_split.childrenCollapsible())
check("the stats panel has a floor, not a fixed width (it is dragged too)",
      row.stats.maximumWidth() > row.stats.minimumWidth() >= G.stats_width())
# Shown (offscreen) and wider than the sum of the panes' minimums, or setSizes is clamped to
# them (the offscreen fonts make those minimums large). The sizes asked for sit above each
# pane's minimum, so taking them is a choice and not a floor.
def _min_w(w):
    return max(w.minimumWidth(), w.minimumSizeHint().width())
_want = [_min_w(row.split.widget(i)) + extra for i, extra in enumerate((120, 40, 60, 200))]   # the last holds entry+table's extras
_want_r = [_min_w(row.readings_split.widget(i)) + extra for i, extra in enumerate((50, 70))]
win.resize(sum(_want) + 4 * 6 + 300, 900)
win.show()
app.processEvents()
_second = G.BoardRow(win, "second", G.BoardTrace("10.9.9.9", 0.0, 15.0))
win.rows["second"] = _second
win.rows_box.addWidget(_second)
app.processEvents()
row.split.setSizes(_want)
row.split.splitterMoved.emit(_want[0], 1)
for _ in range(3):                  # the inner splitter learns its new width through posted layout events
    app.processEvents()
row.readings_split.setSizes(_want_r)
row.readings_split.splitterMoved.emit(_want_r[0], 1)
for _ in range(3):
    app.processEvents()
check("a drag in one row moves every row, and the window keeps the state",
      _second.split.sizes() == row.split.sizes() and _second.readings_split.sizes() == row.readings_split.sizes()
      and win.split_state["split_body"] is not None and win.split_state["split_readings"] is not None,
      f"{row.split.sizes()} vs {_second.split.sizes()}")
win.rows.pop("second")
_second.setParent(None)
app.processEvents()
_sizes_saved = (row.split.sizes(), row.readings_split.sizes())
check("the sizes asked for were taken (the window is wide enough for them)",
      _sizes_saved[0][1:3] == _want[1:3] and _sizes_saved[1][0] == _want_r[0],
      f"{_sizes_saved} vs {_want} {_want_r}")

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
_ini = QtCore.QSettings(G.SETTINGS_FILE, QtCore.QSettings.IniFormat)
check("and so are the five widths, under their two keys",
      _ini.value("split_body") is not None and _ini.value("split_readings") is not None,
      str(_ini.allKeys()))

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
      == ["CLOCK_ANCHOR", "REF_SPO2", "REF_SPO2", "REF_SPO2", "CORRECT", "RETRACT", "RETRACT", "NOTE",
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
# The same board back on a new address (reboot onto another network, new lease), its first
# datagrams before its $CFG (Alex, 2026-10-16: "a veces aparece una nueva fila").
_m4 = b"$M4,4,1,1," + b",".join([b"1"] * 20) + b",2\n"
qc.queue.append(("10.0.0.7", _m4))
winF.drain()
winF.redraw()
_rows_mid = list(winF.rows)
qc.queue.append(("10.0.0.7", b"$CFG,mac=10:51:DB:50:88:50,board=V18\n"))
qc.queue.append(("10.0.0.7", _m4))
winF.drain()
winF.redraw()
check("a board back on a new address: the row made before its $CFG folds into the MAC's row, "
      "the old address's trace goes, one row and one trace remain",
      list(winF.rows) == ["10:51:DB:50:88:50"] and list(winF.traces) == ["10.0.0.7"]
      and winF.rows["10:51:DB:50:88:50"].trace.ip == "10.0.0.7",
      f"mid={_rows_mid} rows={list(winF.rows)} traces={list(winF.traces)}")
winF._closing = True
recF.stop("test")
winF.client.close()
recF.close()

# ── --config: a TOML session file, the one source of who a session is about ─────────────────────────────────────────
import argparse as _argparse
import tomllib as _tomllib

cfg_dir = tempfile.mkdtemp()
cfg_path = os.path.join(cfg_dir, "subj01.toml")
open(cfg_path, "w", encoding="utf-8").write("""
location  = "HOSP01"
operator  = "AC"
board     = "8850"
note      = "term neonate, resting after a feed"
probe     = "Medle-neo"

[subject]
id       = "SUBJ01"
gest_age = "30w+2d"
age      = "14d"
weight_g = 1500
skin     = 3

[ref]
model = "Masimo Radical-7"
avg   = 8
probe-site = "left thumb"
videonest  = "J6plusACM"
""")


cfg = G.load_session_config(cfg_path)
check("the session file fills all fifteen fields, numbers as strings",
      cfg == {"location": "HOSP01", "operator": "AC", "board": "8850", "subject": "SUBJ01",
              "ref_videonest": "J6plusACM", "note": "term neonate, resting after a feed",
              "probe": "Medle-neo", "ref_model": "Masimo Radical-7", "ref_avg": "8",
              "ref_probe_site": "left thumb", "ref_note": "",
              "gest_age": "30w+2d", "age": "14d", "weight_g": "1500", "skin": "3"}, str(cfg))
kw = G.recorder_kwargs(cfg)
check("and maps onto the Recorder's keyword arguments (the flags are gone, 2026-10-16: the file is the one source)",
      kw["subject"] == "SUBJ01" and kw["videonest"] == "J6plusACM" and kw["board"] == "8850"
      and kw["ref_probe_site"] == "left thumb" and kw["weight_g"] == "1500" and len(kw) == 13
      and not hasattr(G, "apply_session_config") and not hasattr(G, "CONFIG_FIELDS"), str(kw))
old_path = os.path.join(tempfile.gettempdir(), "pulsenest_old_shape.toml")
open(old_path, "w", encoding="utf-8").write('location = "HOSP01"\nsubject = "SUBJ01"\n')
try:
    G.load_session_config(old_path)
    ok.append(False)
    print("FAIL a top-level `subject = ...` (the shape before 2026-10-14) must be refused")
except ValueError as exc:
    check("a top-level `subject = ...` (the old shape) is refused, and the reply spells out [subject]",
          "[subject]" in str(exc) and "id = 'SUBJ01'" in str(exc), str(exc))
_ap = _argparse.ArgumentParser()
G.add_session_args(_ap)
_flags = {a.option_strings[0] for a in _ap._actions if a.option_strings}
check("--config is required and the fifteen metadata flags are gone; the tool flags stay",
      "--config" in _flags and all(f not in _flags for f in ("--location", "--operator", "--board", "--subject",
                                                              "--note", "--probe", "--gest-age", "--skin",
                                                              "--ref-videonest", "--ref-model"))
      and {"--out", "--hub", "--csv", "--raw", "--duration"} <= _flags
      and next(a for a in _ap._actions if "--config" in a.option_strings).required, str(sorted(_flags)))

try:
    G.load_session_config(os.path.join(cfg_dir, "missing.toml"))
    check("a missing config file raises", False)
except OSError:
    check("a missing config file raises OSError, not a traceback the operator has to read", True)

bad_path = os.path.join(cfg_dir, "bad.toml")
open(bad_path, "w", encoding="utf-8").write("this is [[[ not toml")
try:
    G.load_session_config(bad_path)
    check("malformed TOML raises", False)
except _tomllib.TOMLDecodeError:
    check("malformed TOML raises TOMLDecodeError, named clearly rather than crashing opaquely", True)

# ── what was given at launch reads in the panel and cannot be changed from it (Alex, 2026-10-14) ──
out3 = tempfile.mkdtemp()
rec3 = G.Recorder(out3, "HOSP01", "ACM", log=QuietLog(), subject="SUBJ05", board="7560",
                  note="probe on left foot", probe="Medle ST-S0163-26",
                  gest_age="30w+2d", age="14d", weight_g="1500", skin="3")
win3 = G.RecorderWindow(rec3, ("127.0.0.1", 15999))
rec3.feed("192.168.1.60", f"$CFG,mac={MAC},board=V18,fw=0.14\n".encode())
win3.traces["192.168.1.60"] = G.BoardTrace("192.168.1.60", 0.0, 15.0)
win3.redraw()
row3 = list(win3.rows.values())[0]
row3._mirror_state()
win3.show()                     # same geometry as the last window: restored from the .ini
app.processEvents()
check("a new window starts its rows with the widths saved by the last one",
      (row3.split.sizes(), row3.readings_split.sizes()) == _sizes_saved,
      f"{row3.split.sizes()} {row3.readings_split.sizes()} vs {_sizes_saved}")
check("a subject given at launch is bound and read in the panel as a plain label",
      rec3.sources["192.168.1.60"].subject == "SUBJ05" and row3.subject_label.text() == "SUBJ05"
      and isinstance(row3.subject_label, QtWidgets.QLabel), rec3.sources["192.168.1.60"].subject)
# Built for a finger (Alex, 2026-10-15): RECORD three times a button's height, the SpO2 box as
# high, and its own 14 x 16 px arrows replaced by two push buttons beside it that step the box.
_plain = QtWidgets.QPushButton("RECORD"); _plain.setFont(row.record.font())
_v = row.spo2.value()
row.spo2_up.click(); row.spo2_up.click(); row.spo2_down.click()
check("RECORD is three times a button's height, the SpO2 box as high, its arrow buttons half that and wide, and they step the box",
      row.record.minimumHeight() == 3 * _plain.sizeHint().height()
      and row.spo2.minimumHeight() == row.record.minimumHeight()
      and row.spo2_up.minimumHeight() == row.record.minimumHeight() // 2
      and row.spo2_up.width() == G.SPIN_BTN_W and row.spo2_down.width() == G.SPIN_BTN_W
      and row.spo2.buttonSymbols() == QtWidgets.QAbstractSpinBox.NoButtons
      and row.spo2.value() == _v + 1 and row.spo2_up.isEnabled(),
      f"record {row.record.minimumHeight()} plain {_plain.sizeHint().height()} spo2 {row.spo2.minimumHeight()} "
      f"up {row.spo2_up.width()}x{row.spo2_up.minimumHeight()} value {_v}->{row.spo2.value()}")
row.spo2.setValue(_v)

# Keys + / - / R from anywhere in the window (a live recorder: win3) (Alex, 2026-10-15); typing into NEW EVENT keeps them.
_n, _v = row3.listing.rowCount(), row3.spo2.value()
row3.record.setFocus()
QTest.keyClick(row3.record, QtCore.Qt.Key_Plus); QTest.keyClick(row3.record, QtCore.Qt.Key_Plus)
QTest.keyClick(row3.record, QtCore.Qt.Key_Minus)
QTest.keyClick(row3.record, QtCore.Qt.Key_R)
check("keys + and - step the SpO2 box and R records, with the focus on a button",
      row3.spo2.value() == _v + 1 and row3.listing.rowCount() == _n + 1
      and row3.listing.item(0, 1).text() == str(_v + 1),
      f"value {_v}->{row3.spo2.value()} rows {_n}->{row3.listing.rowCount()}")
row3.spo2.setFocus()
QTest.keyClick(row3.spo2, QtCore.Qt.Key_Minus); QTest.keyClick(row3.spo2, QtCore.Qt.Key_R)
check("the same keys work with the focus in the SpO2 box itself",
      row3.spo2.value() == _v and row3.listing.rowCount() == _n + 2,
      f"value {row3.spo2.value()} rows {row3.listing.rowCount()}")
row3.note.setFocus()
QTest.keyClick(row3.note, QtCore.Qt.Key_R); QTest.keyClick(row3.note, QtCore.Qt.Key_Plus)
check("typed into NEW EVENT, r and + are text: nothing recorded, the box unchanged",
      row3.note.text() == "r+" and row3.listing.rowCount() == _n + 2 and row3.spo2.value() == _v,
      f"note {row3.note.text()!r} rows {row3.listing.rowCount()}")
row3.note.clear()
check("the keys are said on a visible line and in the three tooltips",
      "+" in row3.keys_help.text() and "R" in row3.keys_help.text()
      and "Key R" in row3.record.toolTip() and "Keys + and -" in row3.spo2.toolTip()
      and "Key +" in row3.spo2_up.toolTip() and "Key -" in row3.spo2_down.toolTip())


check("the four [subject] values read in the panel with their units, read-only labels",
      [row3.subject_labels[k].text() for k in ("gest_age", "age", "weight_g", "skin")]
      == ["30w+2d", "14d", "1500 g", "Monk 3"] and isinstance(row3.subject_labels["skin"], QtWidgets.QLabel),
      str([row3.subject_labels[k].text() for k in row3.subject_labels]))
rec3.console("subj SUBJ05 weight_g 1620")
row3.refresh(time.monotonic(), False)
check("a value set later on the console (`subj ... weight_g`) is mirrored into the panel",
      row3.subject_labels["weight_g"].text() == "1620 g", row3.subject_labels["weight_g"].text())
check("LOCATION and OPERATOR read in the board's panel, read-only labels",
      row3.location_label.text() == "HOSP01" and row3.operator_label.text() == "ACM"
      and isinstance(row3.location_label, QtWidgets.QLabel))
check("the window's bar no longer carries them", not hasattr(win3, "location_field"))
check("BOARD, PROBE and the launch NOTE read in the panel too, in the file's order",
      row3.board_label.text() == "*7560" and row3.launch_note_label.text() == "probe on left foot"
      and row3.probe_label.text() == "Medle ST-S0163-26",
      f"{row3.board_label.text()} | {row3.launch_note_label.text()} | {row3.probe_label.text()}")
labels = [row3.findChild(QtWidgets.QFormLayout).itemAt(i, QtWidgets.QFormLayout.LabelRole).widget().text()
          for i in range(row3.findChild(QtWidgets.QFormLayout).rowCount())]
check("panel order = the file first, then example.toml order, then NEW EVENT",
      labels == ["FILE", "LOCATION", "OPERATOR", "BOARD", "PROBE", "SUBJECT", "GEST AGE", "AGE", "WEIGHT", "SKIN",
                 "NOTE", "MONITOR", "REFERENCE", ""], str(labels))   # "": the phone line under REFERENCE
check("NEW EVENT sits in the operator's box, under the entry | table splitter, full width",
      row3.note.parentWidget() is row3.readings_split.parentWidget() and
      row3.note.parentWidget().layout().getItemPosition(
          row3.note.parentWidget().layout().indexOf(row3.note))[:2] == (1, 1)
      and row3.note.parentWidget().layout().getItemPosition(
          row3.note.parentWidget().layout().indexOf(row3.readings_split))[:2] == (0, 0)
      and row3.note.parentWidget().title() == "Readings from the monitor, and events"
      and row3.subject_labels["skin"].parentWidget().title() == "TOML session configuration")
check("the FILE row says '(no file)' for a window built without a .toml (only the tests do)",
      row3.findChild(QtWidgets.QFormLayout).itemAt(0, QtWidgets.QFormLayout.FieldRole).widget().text()
      == "(no file)")
win3c = G.RecorderWindow(rec3, ("127.0.0.1", 15999), config=os.path.join("docs", "session_configs", "cot1.toml"))
check("with --config, the title bar carries the .toml's base name",
      " — cot1.toml" in win3c.windowTitle(), win3c.windowTitle())
rec3.feed("192.168.1.60", f"$CFG,mac={MAC},board=V18,fw=0.14\n".encode())
win3c.traces["192.168.1.60"] = G.BoardTrace("192.168.1.60", 0.0, 15.0)
win3c.redraw()
row3c = list(win3c.rows.values())[0]
check("with --config, FILE is a link named after the file; a click opens it in the system editor",
      "cot1.toml</a>" in row3c.file_label.text() and row3c.file_label.receivers(row3c.file_label.linkActivated) == 1,
      row3c.file_label.text())
win3c.close()
check("DELETE selected sits under DELETE LAST in the entry, and the table is the entry's neighbour",
      row3.delete_sel.parentWidget() is row3.entry_w and
      row3.entry_w.layout().getItemPosition(row3.entry_w.layout().indexOf(row3.delete_sel))[:2] == (4, 0)
      and row3.listing.parentWidget() is row3.readings_split)
win3.close()

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if all(ok) else 1)
