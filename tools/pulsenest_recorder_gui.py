"""The operator's face for pulsenest_recorder.py: one row per board, and the controls that make
a capture usable, beside the waveform that says whether the probe is still on the foot.

    python tools/pulsenest_recorder_gui.py [--location HOSP01] [--operator AC] [--hub IP[:PORT]]
                                          [--split-min 10] [--duration S]

Why this exists (Alex, 2026-09-21). A robust tool is not one with the least interface; it is one
that reaches its goal with the least risk, and most of the risk in a hospital session is human:
a board recorded for an hour with no subject bound, a reading typed for the wrong baby, a phone
that stopped sending and nobody noticed, a session closed by a stray Ctrl+C. The console of
pulsenest_recorder.py protects the files; this window protects the operator.

What it is NOT: a second recorder. It imports `Recorder` from tools/pulsenest_recorder.py and
feeds it from a Qt timer, exactly as the console loop does. Every button ends in a call the
console already makes (`rec.console("subject 7560 SUBJ01")`), so there is ONE code path for
binding a subject, one for a reading, one for closing a session, and the 85 checks of
pulsenest_recorder_test.py cover what happens on disk. The waveform comes from
fleet_ppg_viewer.py's `BoardTrace`, unchanged. Nothing here writes a file of its own except the
window geometry.

Layout, from fleet_ppg_viewer.py with three changes Alex asked for:
  * the bedside numbers (SpO2, HR3, the heart) between plot and table are gone -- the reference
    numbers in a session are read off the COMMERCIAL monitor, and a big number of our own
    beside the entry box invites copying it;
  * a control panel to the right of each SIGNAL STATS table: the values that do not change
    during the session (subject, references, condition, a note line), then the reading entry;
  * every row folds to a single header line, so three boards fit on a laptop screen and a row
    that needs no attention takes no room.

Dark, in the palette pulsenest_lab.py uses (`#121212` on `#E0E0E0`), and stated in a stylesheet
rather than left to the desktop: the plot and the statistics panel are dark whatever Windows says,
and the state colours are chosen for a dark ground.

The one risk this window adds, said plainly: the waveform is pyqtgraph, which has killed
pulsenest_lab.py 28 times, and here a crash stops the recording. Two mitigations: the .pnraw is
flushed datagram by datagram so nothing already written is lost, and PLOTS turns the waveform
off for a long session. The 10-minute parts make reopening a session a continuation.
"""
import argparse
import faulthandler
import os
import sys
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, script_name                     # noqa: E402
from pulsenest_hub_client import HubClient                               # noqa: E402
from pulsenest_recorder import (Recorder, NotEnoughSpace,                # noqa: E402
                                mac_compact, SPLIT_MIN_DEFAULT, normalise_subject)
from fleet_ppg_viewer import (BoardTrace, make_stats_widget, stats_width,  # noqa: E402
                              stats_columns, MIN_PLOT_W, RED)
import pyqtgraph as pg                                                   # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                               # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_fault_log = open(os.path.join(_HERE, "pulsenest_recorder_gui_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

SETTINGS_FILE = os.path.join(_HERE, "pulsenest_recorder_gui.ini")
DRAIN_MS, REDRAW_MS, TICK_MS = 20, 100, 250
WINDOW_S = 15.0
AMBER = "#FFB000"
FLAG_COLOUR = "#CC66FF"   # deliberately not red/amber: those mean "this needs fixing", this means
                          # "the operator said so", a different kind of fact
# The project's dark palette, as pulsenest_lab.py sets it (`#121212` on `#E0E0E0`). Stated here
# rather than left to the desktop theme: this window is read across a room, beside a plot and a
# statistics panel that are dark whatever the desktop says, and its state colours (APPLIED green,
# amber warnings) are chosen for a dark ground.
BG, BG_RAISED, FG, FG_DIM = "#121212", "#1E1E1E", "#E0E0E0", "#AAAAAA"
DARK_QSS = f"""
QWidget {{ background-color: {BG}; color: {FG}; }}
QGroupBox {{ color: {FG_DIM}; font-weight: bold; border: 1px solid #333333;
             border-radius: 4px; margin-top: 8px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; }}
QFrame {{ border: 1px solid #2A2A2A; border-radius: 4px; }}
QComboBox, QSpinBox, QLineEdit {{ background-color: {BG_RAISED}; color: {FG};
                                  border: 1px solid #3A3A3A; border-radius: 3px; padding: 2px; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: #666666;
                                                             background-color: #181818; }}
QComboBox QAbstractItemView {{ background-color: {BG_RAISED}; color: {FG};
                               selection-background-color: #335577; }}
QCheckBox:disabled {{ color: #666666; }}
QPushButton {{ background-color: #2E2E2E; color: {FG}; border: 1px solid #4A4A4A;
               border-radius: 4px; padding: 4px 10px; }}
QPushButton:hover {{ background-color: #3A3A3A; }}
QPushButton:pressed, QPushButton:checked {{ background-color: #4A4A4A; }}
QPushButton:disabled {{ color: #666666; border-color: #2A2A2A; }}
QTableWidget {{ background-color: #111111; color: {FG}; gridline-color: #2A2A2A;
                border: 1px solid #2A2A2A; }}
QHeaderView::section {{ background-color: #2A2A2A; color: {FG_DIM}; border: 0; padding: 2px; }}
QToolButton {{ border: none; }}
QScrollBar:vertical {{ background: #111111; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3A3A3A; min-height: 20px; border-radius: 4px; }}
QMessageBox, QDialog {{ background-color: {BG}; color: {FG}; }}
"""
# A menu for the common case, not a ceiling: the combo is editable, so a campaign that reaches
# SUBJ13 types it. Twelve was a cap that would simply have blocked the thirteenth baby.
SUBJECTS = [f"SUBJ{n:02d}" for n in range(1, 13)]
CONDITIONS = ["RESTING", "FEEDING", "HANDLING", "KANGAROO", "PHOTOTHERAPY", "SLEEPING"]
PR_NONE = 0     # the pulse-rate spinbox at its minimum reads "--": not recorded
CELL_PAD = 14   # a table cell's own left+right margins, on top of the text it holds


def suffix(mac):
    return mac_compact(mac)[-4:] if mac else "????"


# ============================================================================================
# one board
# ============================================================================================
class BoardRow(QtWidgets.QFrame):
    """Header line (always visible) over a body (waveform, statistics, controls) that folds."""

    def __init__(self, win, key, trace):
        super().__init__()
        self.win, self.key, self.trace = win, key, trace
        self.src = None                    # the Recorder's Source, once known
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        # ── header ──
        head = QtWidgets.QHBoxLayout()
        self.fold = QtWidgets.QToolButton()
        self.fold.setArrowType(QtCore.Qt.DownArrow)
        self.fold.setCheckable(True)
        self.fold.setChecked(True)
        self.fold.setToolTip("Show or hide this board's waveform and controls. The header stays.")
        self.fold.toggled.connect(self._toggle)
        self.title = QtWidgets.QLabel()
        f = self.title.font()
        f.setPointSize(f.pointSize() + 1)
        f.setBold(True)
        self.title.setFont(f)
        self.counters = QtWidgets.QLabel()
        self.counters.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.warn = QtWidgets.QLabel()
        self.warn.setStyleSheet(f"color:{AMBER}; font-weight:bold;")
        # A toggle, not a click-and-forget button: its pressed state IS the flagged state, so the
        # header can never disagree with what a person would remember pressing.
        self.flag_btn = QtWidgets.QPushButton("ABNORMAL CONDITION")
        self.flag_btn.setCheckable(True)
        self.flag_btn.setEnabled(False)
        self.flag_btn.setToolTip("Mark this stretch as questionable validity -- probe loosely\n"
                                 "applied, motion, an alarm interfering. Recording never stops;\n"
                                 "this writes a start/end pair so the marked stretch stays on disk\n"
                                 "and an analysis can honour it or ignore it. Not a pause: a pause\n"
                                 "risks forgetting to resume, which loses good data. Press again\n"
                                 "to clear it -- a wrong flag costs nothing, a dropped stretch does.")
        self.flag_btn.toggled.connect(self._flag_toggled)
        head.addWidget(self.fold)
        head.addWidget(self.title)
        head.addWidget(self.counters, 1)
        head.addWidget(self.warn)
        head.addWidget(self.flag_btn)
        outer.addLayout(head)

        # ── body ──
        self.body = QtWidgets.QWidget()
        body = QtWidgets.QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self.plot_w = pg.PlotWidget(background=BG)
        self.plot_w.setMinimumWidth(MIN_PLOT_W)
        self.plot_w.setMinimumHeight(120)
        self.plot_w.showGrid(x=True, y=True, alpha=0.2)
        self.plot_w.setXRange(-WINDOW_S, 0, padding=0)
        self.plot_w.setLabel("bottom", "seconds ago")
        self.curve = self.plot_w.plot(pen=pg.mkPen("#44AAFF", width=1))
        self.stats = make_stats_widget(stats_width())
        self.stats.setFixedWidth(stats_width())
        body.addWidget(self.plot_w, 1)
        body.addWidget(self.stats)
        body.addWidget(self._session_values_group())
        body.addWidget(self._reading_group())
        outer.addWidget(self.body)

    # ── the controls ──
    def _session_values_group(self):
        # NOT "values that do not change": they can all be changed, and each change is its own
        # timestamped META event. What a later change cannot do is give the file two names.
        g = QtWidgets.QGroupBox("This board: who, against what, doing what")
        form = QtWidgets.QFormLayout(g)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.subject = QtWidgets.QComboBox()
        self.subject.setEditable(True)
        self.subject.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.subject.addItem("")
        self.subject.addItems(SUBJECTS)
        self.subject.lineEdit().setPlaceholderText("SUBJ01")
        self.subject.setToolTip("The coded subject this board is on. Codes only, never a name: "
                                "the code-to-person list lives outside the repository. Everything "
                                "else in this panel waits for this.\n\n"
                                "This is the one value not to change mid-session: one capture file "
                                "belongs to one baby. If the probe moves to another baby, stop the "
                                "session and start a new one.\n\n"
                                "The menu is a shortcut, not a limit -- type SUBJ13 and it is "
                                "accepted. What is NOT accepted is anything that is not SUBJ "
                                "followed by digits: no names, no initials, no bed numbers.")
        # `activated` for a pick from the menu, `editingFinished` for a typed code plus Enter.
        # NOT currentTextChanged: that fires on every keystroke, and "S", "SU", "SUB" are each a
        # refusal the operator did not ask for.
        self.subject.activated.connect(lambda _i: self._subject_changed())
        self.subject.lineEdit().editingFinished.connect(self._subject_changed)
        form.addRow("SUBJECT", self.subject)

        # One reference control, not five (Alex, 2026-09-22). `operator annotation` was always on
        # -- it is the panel to the right -- and `simulator`, `VideoNest CSV` and `VideoNest
        # pictures` change nothing about what THIS window records, so they belonged in truth.csv
        # and not here. What is left is the one thing this window cannot work out for itself:
        # every phone on the wire reaches every session, so which one is filming THIS cot has to
        # be said.
        vn_box = QtWidgets.QWidget()
        vn = QtWidgets.QHBoxLayout(vn_box)
        vn.setContentsMargins(0, 0, 0, 0)
        self.vn_on = QtWidgets.QCheckBox("VideoNest UDP")
        self.vn_on.setToolTip("Tick when a phone running VideoNest is filming this baby's "
                              "monitor and sending to the hub. Then choose which phone.")
        self.vn_id = QtWidgets.QComboBox()
        self.vn_id.setMinimumWidth(120)
        self.vn_id.setToolTip("The device id the phone puts in its own frames -- the same word "
                              "its photographs are named after. The list fills itself as phones "
                              "are heard on the wire, so a phone that is not sending does not "
                              "appear, which is itself the answer to 'is it working?'.")
        self.vn_on.toggled.connect(self._videonest_changed)
        self.vn_id.activated.connect(lambda _i: self._videonest_changed())
        vn.addWidget(self.vn_on)
        vn.addWidget(self.vn_id, 1)
        form.addRow("REFERENCE", vn_box)

        self.condition = QtWidgets.QComboBox()
        self.condition.setEditable(True)
        self.condition.addItem("")
        self.condition.addItems(CONDITIONS)
        self.condition.setToolTip("What the baby is doing, one word. Change it whenever it "
                                  "changes -- each change is a timestamped event in the files, so "
                                  "the history is kept. But the CSV FILENAME takes the last value "
                                  "only, so if a baby goes from RESTING to FEEDING, the name will "
                                  "say FEEDING for the whole capture. Reuse the same words across "
                                  "sessions.")
        # `activated` is the operator picking from the list; `editingFinished` is a typed
        # word plus Enter. Not `currentTextChanged`: that is one command per keystroke.
        self.condition.activated.connect(self._condition_changed)
        self.condition.lineEdit().editingFinished.connect(self._condition_changed)
        form.addRow("CONDITION", self.condition)

        self.note = QtWidgets.QLineEdit()
        self.note.setPlaceholderText("free text, Enter to record. Coded subjects only, no names.")
        self.note.returnPressed.connect(self._note_entered)
        form.addRow("NOTE", self.note)

        # Read-only, and typed on the command line (--ref-model etc.), not here (Alex, 2026-09-22):
        # these four do not change during a session, so a live control for them would sit idle.
        # Shown anyway, so a typo on the command line is visible instead of silently wrong.
        self.ref_label = QtWidgets.QLabel("(not set)")
        self.ref_label.setWordWrap(True)
        self.ref_label.setStyleSheet(f"color:{FG_DIM};")
        self.ref_label.setToolTip("The commercial monitor beside this baby: make and model, its\n"
                                  "averaging window in seconds, where ITS probe is, and any note.\n"
                                  "Set once, on the command line: --ref-model, --ref-avg,\n"
                                  "--ref-probe-site, --ref-note. Shown here read-only so you can\n"
                                  "see it was typed correctly, not to be edited from the window.")
        form.addRow("MONITOR", self.ref_label)

        # Same principle, one field: OUR probe, not the reference monitor's -- ISO 80601-2-61
        # calibrates a monitor+probe pair, and the library cannot know which physical sensor is
        # clipped onto the baby, only a person can. Top-level --probe, not --ref-probe: it says
        # nothing about the commercial monitor.
        self.probe_label = QtWidgets.QLabel("(not set)")
        self.probe_label.setStyleSheet(f"color:{FG_DIM};")
        self.probe_label.setToolTip("OUR probe's physical model, e.g. Medle-neo. Set once, on\n"
                                    "the command line (--probe), shown here read-only so a typo\n"
                                    "is visible instead of silent.")
        form.addRow("PROBE", self.probe_label)
        self._set_dependents_enabled(False)
        return g

    def _reading_group(self):
        g = QtWidgets.QGroupBox("Reading from the commercial monitor")
        lay = QtWidgets.QGridLayout(g)
        self.spo2 = QtWidgets.QSpinBox()
        self.spo2.setRange(50, 100)
        self.spo2.setValue(95)
        self.spo2.setSuffix(" %")
        self.spo2.setToolTip("SpO2 as shown on the COMMERCIAL monitor's screen, never a number "
                             "of ours. Range 50-100: a neonatal desaturation goes below 60.")
        big = self.spo2.font()
        big.setPointSize(big.pointSize() + 8)
        self.spo2.setFont(big)
        self.pr = QtWidgets.QSpinBox()
        self.pr.setRange(PR_NONE, 250)
        self.pr.setSpecialValueText("--")
        self.pr.setValue(PR_NONE)
        self.pr.setToolTip("Pulse rate on the monitor, OPTIONAL: leave at -- unless you want a "
                           "pulse reference too. Since VideoNest build 8 dropped its pulse field, "
                           "this box is the only pulse reference a session can have.")
        self.record = QtWidgets.QPushButton("RECORD")
        self.record.setToolTip("Write the reading above as a REF_SPO2 event, stamped now. Check "
                               "the number against the monitor first; do not correct for delay.")
        self.record.clicked.connect(self._record)
        self.record.setDefault(True)
        rb = self.record.font()
        rb.setBold(True)
        self.record.setFont(rb)
        self.delete_last = QtWidgets.QPushButton("DELETE LAST")
        self.delete_last.setToolTip("Withdraw the most recent reading of this subject -- you pressed "
                                    "twice, or read the wrong monitor. Nothing is erased: a RETRACT "
                                    "event is written and the list drops the reading.")
        self.delete_last.clicked.connect(self._delete_last)
        # The annotation list: every effective reading of this subject, newest first. Double-click
        # a row to edit its numbers; select and DELETE to withdraw it. Both are new events on the
        # append-only files, never a rewrite -- see pulsenest_recorder_spec.md section 9.
        self.listing = QtWidgets.QTableWidget(0, 4)
        self.listing.setHorizontalHeaderLabels(["time", "SpO2", "PR", "id"])
        head = self.listing.horizontalHeader()
        # Measured, not guessed. `ResizeToContents` gave 143 px to a time of eight characters and
        # 104 px to a two-digit id, because it takes a delegate's size hint plus Qt's cell
        # margins rather than the width of the text. Each column is asked for the widest value it
        # can ever hold, in the font it will actually be drawn in; only the time column stretches,
        # so leftover width lands somewhere that can use it.
        fm = QtGui.QFontMetrics(self.listing.font())

        def wide_enough(*texts):
            # The widest thing the column must ever hold -- its header, or its longest value --
            # plus room for the cell's own margins. Not the header and the value together.
            return max(fm.horizontalAdvance(t) for t in texts) + CELL_PAD
        for col, texts in ((1, ("SpO2", "100 *")), (2, ("PR", "888")), (3, ("id", "8888"))):
            head.setSectionResizeMode(col, QtWidgets.QHeaderView.Fixed)
            self.listing.setColumnWidth(col, wide_enough(*texts))
        # Only the time column stretches, so leftover width lands where it is harmless instead of
        # being swallowed by the id, which is what `setStretchLastSection` was doing.
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        head.setStretchLastSection(False)
        self.listing.verticalHeader().setVisible(False)
        self.listing.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.listing.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.listing.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.listing.setMinimumWidth(wide_enough("time", "88:88:88")
                                     + sum(self.listing.columnWidth(c) for c in (1, 2, 3)))
        self.listing.setToolTip("Every reading recorded for this subject, newest first. "
                                "Double-click to edit, select and DELETE to withdraw. An edited "
                                "reading shows *; the file keeps the original and the correction.")
        self.listing.doubleClicked.connect(self._edit_selected)
        self.delete_sel = QtWidgets.QPushButton("DELETE selected")
        self.delete_sel.clicked.connect(self._delete_selected)
        self._listed = None            # signature of what the table shows, to redraw only on change
        lay.addWidget(QtWidgets.QLabel("SpO2"), 0, 0)
        lay.addWidget(self.spo2, 0, 1)
        lay.addWidget(QtWidgets.QLabel("PR"), 1, 0)
        lay.addWidget(self.pr, 1, 1)
        lay.addWidget(self.record, 2, 0, 1, 2)
        lay.addWidget(self.delete_last, 3, 0, 1, 2)
        lay.addWidget(self.listing, 0, 2, 4, 1)
        lay.addWidget(self.delete_sel, 4, 2)
        lay.setColumnStretch(2, 1)
        for w in (self.record, self.delete_last, self.delete_sel):
            w.setEnabled(False)
        return g

    def _set_dependents_enabled(self, on):
        for w in [self.vn_on, self.vn_id, self.condition, self.note, self.flag_btn]:
            w.setEnabled(on)
        if hasattr(self, "record"):
            for w in (self.record, self.delete_last, self.delete_sel):
                w.setEnabled(on)

    # ── actions: every one is a console command, so there is one code path ──
    def _subject_changed(self, *_):
        text = self.subject.currentText().strip()
        if not text or self.src is None or not self.src.mac:
            self._set_dependents_enabled(False)
            return
        subj = normalise_subject(text)
        if subj is None:
            # Refused, and said out loud. The alternative -- silently accepting it -- is how a
            # name or a bed number ends up in every file of the session.
            self.win.log_line.setText(f"{text!r} is not a subject code: SUBJ01, SUBJ12, …")
            self.subject.setCurrentText("")
            self._set_dependents_enabled(False)
            return
        if self.subject.findText(subj) < 0:
            self.subject.addItem(subj)          # a code beyond the menu, kept for the session
        self.subject.setCurrentText(subj)
        if self.src.subject == subj:
            self._set_dependents_enabled(True)
            return
        self.win.command(f"subject {suffix(self.src.mac)} {subj}")
        self._videonest_changed()
        self._set_dependents_enabled(True)
        # Re-apply what the operator may already have chosen while the subject was blank.
        self._videonest_changed()
        self._condition_changed()

    def _flag_toggled(self, on):
        if not self.flag_btn.isEnabled():
            return
        subj = self.subject.currentText()
        if subj:
            self.win.command(f"flag {'on' if on else 'off'} {subj}")

    def _videonest_changed(self, *_):
        if not self.vn_on.isEnabled():
            return
        want = self.vn_id.currentText().strip() if self.vn_on.isChecked() else ""
        if want == (self.win.rec.videonest_id or ""):
            return
        self.win.command(f"videonest {want or 'none'}")

    def _mirror_state(self):
        """Widgets follow the Recorder, never the other way round unless the operator acts.

        Found in the 2026-09-22 rehearsal: a window launched from a TOML with subject=SIM and
        videonest=J6plusACM showed SUBJ01 (the combo's first item) and an unticked VideoNest box,
        because nothing ever wrote the Recorder's values INTO the widgets. One click into and out
        of SUBJECT then "applied" what the box displayed: the baby was re-bound to SUBJ01 and
        the phone dropped (`videonest none`) -- two launch values destroyed by a stray click.
        So on every refresh, each control that does not have keyboard focus is set to what the
        Recorder holds, with its signals blocked: mirroring is not a command."""
        src, rec = self.src, self.win.rec
        if src is None or not src.mac:
            return
        if not self.subject.hasFocus() and (src.subject or "") != self.subject.currentText().strip():
            if src.subject and self.subject.findText(src.subject) < 0:
                self.subject.addItem(src.subject)            # SIM, or a code beyond the menu
            self.subject.blockSignals(True)
            self.subject.setCurrentText(src.subject or "")
            self.subject.blockSignals(False)
            self._set_dependents_enabled(bool(src.subject))
        vn = rec.videonest_id or ""
        if not (self.vn_on.hasFocus() or self.vn_id.hasFocus()):
            if self.vn_on.isChecked() != bool(vn):
                self.vn_on.blockSignals(True)
                self.vn_on.setChecked(bool(vn))
                self.vn_on.blockSignals(False)
            if vn and self.vn_id.currentText() != vn:
                if self.vn_id.findText(vn) < 0:
                    self.vn_id.addItem(vn)                      # declared before it was heard
                self.vn_id.setCurrentText(vn)
        if not self.condition.hasFocus() and (src.condition or "") != self.condition.currentText().strip():
            self.condition.blockSignals(True)
            self.condition.setCurrentText(src.condition or "")
            self.condition.blockSignals(False)

    def refresh_phones(self):
        """The device list fills itself from the phones actually heard. A phone that is not
        sending never appears, which is the answer to "is VideoNest working?" without a menu."""
        seen = sorted(self.win.rec.by_vn)
        if seen == [self.vn_id.itemText(i) for i in range(self.vn_id.count())]:
            return
        current = self.vn_id.currentText()
        self.vn_id.clear()
        self.vn_id.addItems(seen)
        if current in seen:
            self.vn_id.setCurrentText(current)
        elif len(seen) == 1 and self.vn_on.isChecked():
            self._videonest_changed()          # only one phone: it is the one

    def _condition_changed(self, *_):
        subj, cond = self.subject.currentText(), self.condition.currentText().strip()
        if subj and cond and self.condition.isEnabled():
            if self.src is not None and self.src.condition != cond.upper():
                self.win.command(f"cond {cond} {subj}")

    def _note_entered(self):
        text, subj = self.note.text().strip(), self.subject.currentText()
        if text and subj:
            self.win.command(f"note {subj} {text}")
            self.note.clear()

    def _record(self):
        subj = self.subject.currentText()
        if not subj:
            return
        pr = self.pr.value()
        self.win.command(f"spo2 {subj} {self.spo2.value()}" + (f" {pr}" if pr > PR_NONE else ""))
        self.refresh_listing()

    # ── the annotation list ──
    def _readings(self):
        subj = self.subject.currentText()
        return list(reversed(self.win.rec.readings(subj))) if subj else []

    def refresh_listing(self):
        rows = self._readings()
        sig = tuple((r["id"], r["spo2"], r["pr"], r["corrected_by"]) for r in rows)
        if sig == self._listed:
            return
        self._listed = sig
        self.listing.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = [r["iso"][11:19], f"{r['spo2']}" + (" *" if r["corrected_by"] else ""),
                     f"{r['pr']}" if r["pr"] != "" else "--", str(r["id"])]
            for j, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.listing.setItem(i, j, item)

    def _selected_id(self):
        sel = self.listing.selectionModel().selectedRows()
        return int(self.listing.item(sel[0].row(), 3).text()) if sel else None

    def _delete_last(self):
        rows = self._readings()
        if rows and self._confirm_delete(rows[0]):
            self.win.command(f"retract {rows[0]['id']}")
            self.refresh_listing()

    def _delete_selected(self):
        eid = self._selected_id()
        if eid is None:
            self.win.log_line.setText("select a reading in the list first")
            return
        r = [x for x in self._readings() if x["id"] == eid]
        if r and self._confirm_delete(r[0]):
            self.win.command(f"retract {eid}")
            self.refresh_listing()

    def _confirm_delete(self, r):
        return QtWidgets.QMessageBox.question(
            self, "withdraw this reading?",
            f"{r['iso'][11:19]}  SpO2 {r['spo2']}" + (f"  PR {r['pr']}" if r["pr"] != "" else "")
            + f"  (event {r['id']})\n\nIt stays in the file marked as retracted.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes

    def _edit_selected(self, *_):
        eid = self._selected_id()
        r = [x for x in self._readings() if x["id"] == eid]
        if not r:
            return
        r = r[0]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"correct reading {eid} taken at {r['iso'][11:19]}")
        form = QtWidgets.QFormLayout(dlg)
        spo2 = QtWidgets.QSpinBox()
        spo2.setRange(50, 100)
        spo2.setValue(int(r["spo2"]))
        pr = QtWidgets.QSpinBox()
        pr.setRange(PR_NONE, 250)
        pr.setSpecialValueText("--")
        pr.setValue(int(r["pr"]) if r["pr"] != "" else PR_NONE)
        form.addRow("SpO2 %", spo2)
        form.addRow("PR (-- = none)", pr)
        form.addRow(QtWidgets.QLabel("The time of the reading does not change: only the number "
                                     "was mistyped.\nThe original stays in the file; a CORRECT "
                                     "event is added."))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_pr = pr.value()
            if spo2.value() != r["spo2"] or (new_pr if new_pr > PR_NONE else "") != r["pr"]:
                self.win.command(f"correct {eid} {spo2.value()}" + (f" {new_pr}" if new_pr > PR_NONE else ""))
                self.refresh_listing()

    def _toggle(self, shown):
        self.body.setVisible(shown)
        self.fold.setArrowType(QtCore.Qt.DownArrow if shown else QtCore.Qt.RightArrow)

    # ── drawing ──
    def refresh(self, now, plots_on):
        tr, src = self.trace, self.src
        tr.trim(now)
        fresh = tr.maybe_snapshot(now)
        colour = tr.state_colour(now)
        self.title.setText(tr.title(now))
        self.title.setStyleSheet(f"color:{colour};")
        if src is not None:
            part = len(src.stream.files) if src.stream is not None and src.stream.files else 0
            csv_rows = src.csv.count if src.csv is not None else 0
            self.counters.setText(f"{src.subject or 'UNBOUND':8s} dgrams {src.dgrams:7d}  "
                                  f"gaps {src.gaps:3d}  csv rows {csv_rows:8d}  part {part:02d}")
            warns = []
            if not src.subject:
                warns.append("no subject bound")
            elif not src.condition:
                warns.append("no condition")
            if src.gaps:
                warns.append(f"{src.gaps} gap(s), {src.samples_lost} samples lost")
            if src.silent:
                warns.append("SILENT")
            if src.restarts:
                warns.append(f"{src.restarts} restart(s)")
            self.warn.setText("   ".join(warns))
            self.warn.setStyleSheet(f"color:{RED if (src.silent or not src.subject) else AMBER}; "
                                    "font-weight:bold;")
            ref = src.reference
            bits = []
            if ref.get("make_model"):
                bits.append(ref["make_model"])
            if ref.get("averaging_s") is not None:
                bits.append(f"avg {ref['averaging_s']:.0f}s")
            if ref.get("probe_site"):
                bits.append(ref["probe_site"])
            self.ref_label.setText(" \u00b7 ".join(bits) if bits else "(not set)")
            if ref.get("notes"):
                self.ref_label.setToolTip(self.ref_label.toolTip().split("\n\n")[0]
                                          + f"\n\nNote: {ref['notes']}")
            self.probe_label.setText(src.probe_model or "(not set)")
            if self.flag_btn.isChecked() != src.flagged:
                self.flag_btn.blockSignals(True)     # reflect state, do not re-fire the command
                self.flag_btn.setChecked(src.flagged)
                self.flag_btn.blockSignals(False)
            self.flag_btn.setStyleSheet(
                f"background-color:{FLAG_COLOUR}; color:#1A0B26; font-weight:bold;"
                if src.flagged else "")
        if src is not None:
            self._mirror_state()
        if self.body.isVisible():
            self.refresh_phones()
            self.refresh_listing()
            if plots_on:
                self.curve.setData([t - now for t in tr.t], list(tr.y))
            if fresh or self.stats.document().isEmpty():
                bar = self.stats.verticalScrollBar()
                where = bar.value()
                self.stats.setHtml(tr.stats_html(*stats_columns()))
                bar.setValue(where)


# ============================================================================================
# the window
# ============================================================================================
class RecorderWindow(QtWidgets.QMainWindow):
    def __init__(self, rec, hub, duration_s=0.0):
        super().__init__()
        self.rec = rec
        # A timed run stops the RECORDER, and tick() then closes the window the same way a full
        # disk does -- one path out of a session, not two.
        self.end_at = time.monotonic() + duration_s if duration_s > 0 else None
        self.hub_text = f"{hub[0]}:{hub[1]}"
        waiting = f" — waiting for board *{rec.board_filter}" if rec.board_filter else ""
        self.setWindowTitle(f"{script_name(__file__)} — {rec.session_id}{waiting}"
                            f"  (hub {hub[0]}:{hub[1]})")
        self.rows = {}            # key (mac, or ip until identified) -> BoardRow
        self.traces = {}          # ip -> BoardTrace
        self.aux_ips = set()
        self.plots_on = True
        self._closing = False
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=rec.log.info)
        self.client.connect()

        self.setStyleSheet(DARK_QSS)
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)
        v.addWidget(self._session_bar())
        self.rows_box = QtWidgets.QVBoxLayout()
        self.rows_box.setSpacing(4)
        v.addLayout(self.rows_box, 1)
        self.empty = QtWidgets.QLabel(
            f"waiting for board *{rec.board_filter}…" if rec.board_filter else "waiting for a board…")
        self.empty.setStyleSheet(f"color:{FG_DIM}; font-size:14pt;")
        self.empty.setAlignment(QtCore.Qt.AlignCenter)
        self.rows_box.addWidget(self.empty)
        self.log_line = QtWidgets.QLabel(f"recording into {rec.dir}")
        self.log_line.setStyleSheet(f"color:{FG_DIM};")
        v.addWidget(self.log_line)
        self._restore_geometry()

        # Kept, not discarded: closeEvent has to STOP these. Left as locals they survived as
        # children of the window and kept firing after the socket was shut, which cost 80 296 log
        # lines and a spawned hub process in one real session (2026-09-21).
        self.timers = []
        for ms, fn in ((DRAIN_MS, self.drain), (REDRAW_MS, self.redraw), (TICK_MS, self.tick)):
            t = QtCore.QTimer(self)
            t.timeout.connect(fn)
            t.start(ms)
            self.timers.append(t)

    def _session_bar(self):
        bar = QtWidgets.QGroupBox("Session")
        h = QtWidgets.QHBoxLayout(bar)

        def field(label, value):
            h.addWidget(QtWidgets.QLabel(label))
            w = QtWidgets.QLabel(f"<b>{value}</b>")
            h.addWidget(w)
            h.addSpacing(16)
            return w
        field("LOCATION", self.rec.site)
        field("OPERATOR", self.rec.operator or "-")
        self.disk = QtWidgets.QLabel()
        h.addWidget(self.disk)
        h.addStretch(1)
        anchor = QtWidgets.QPushButton("CLOCK ANCHOR")
        anchor.setToolTip("Only needed if you are FILMING or PHOTOGRAPHING the commercial monitor.\n\n"
                          "Point the phone at this laptop's clock for a few seconds and press this "
                          "while it is in shot. That puts the laptop's time inside the video and an "
                          "event at the same instant in the recording, which is what lets a reading "
                          "read off the video afterwards be placed on our timeline. Without it the "
                          "two devices have to be trusted to agree, and they do not: the phone's "
                          "own timestamps were measured running 164-350 ms behind arrival here.")
        anchor.clicked.connect(lambda: self.command("anchor"))
        h.addWidget(anchor)
        self.plots = QtWidgets.QPushButton("PLOTS")
        self.plots.setCheckable(True)
        self.plots.setChecked(True)
        self.plots.setToolTip("Waveforms on or off. Off costs nothing in the files and removes "
                              "the one component that has ever crashed a PulseNest window.")
        self.plots.toggled.connect(self._plots_toggled)
        h.addWidget(self.plots)
        stop = QtWidgets.QPushButton("STOP SESSION")
        stop.setStyleSheet(f"color:{RED}; font-weight:bold;")
        stop.setToolTip("Closes every file, renames the CSVs to their canonical names and exits. "
                        "Asks first.")
        stop.clicked.connect(self.close)
        h.addWidget(stop)
        return bar

    # ── one code path for every action ──
    def command(self, line):
        reply = self.rec.console(line)
        self.log_line.setText(f"> {line}    {reply}")
        return reply

    def _plots_toggled(self, on):
        self.plots_on = on
        for row in self.rows.values():
            row.plot_w.setVisible(on)
            if not on:
                row.curve.setData([], [])

    # ── network ──
    def drain(self):
        if self._closing:
            return
        now = time.monotonic()
        for _ in range(256):
            item = self.client.recv(0.0)
            if item is None:
                break
            ip, data = item
            self.rec.feed(ip, data)
            if ip in self.rec.ignored:
                # Not this window's baby (--board matched someone else, or matched nobody yet).
                # A board's first datagrams arrive before its $CFG is parsed, so a trace or a row
                # can already exist here for an ip that only just turned out to be the wrong one
                # -- torn down rather than left on screen (Alex, 2026-09-22: three boards showed
                # with --board 8850).
                self._forget_ip(ip)
                continue
            if ip in self.aux_ips:
                continue
            src = self.rec.sources.get(ip)
            if src is not None and src.kind != "board":
                self.aux_ips.add(ip)
                continue
            tr = self.traces.get(ip)
            if tr is None:
                tr = self.traces[ip] = BoardTrace(ip, now, WINDOW_S)
            tr.feed(data, now)

    def tick(self):
        if self._closing:
            return
        self.rec.tick()
        if self.end_at is not None and time.monotonic() >= self.end_at:
            self.rec.stop("duration")
        if self.rec.stopped and not self._closing:
            if self.rec.stop_reason != "duration":
                QtWidgets.QMessageBox.critical(self, "recording stopped",
                                               f"The recorder stopped itself: {self.rec.stop_reason}.\n"
                                               f"See pulsenest_recorder.log in {self.rec.dir}.")
            self.close()
        fb = self.rec.free_bytes
        if fb is not None:
            self.disk.setText(f"disk {fb / 1e9:.0f} GB free")
            self.disk.setStyleSheet(f"color:{RED if fb < 2 * self.rec.min_free_bytes else FG_DIM};")

    # ── rows: one per board, keyed by MAC once the board has said who it is ──
    def _forget_ip(self, ip):
        self.traces.pop(ip, None)
        row = self.rows.pop(ip, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        if not self.rows and self.empty is None:
            self.empty = QtWidgets.QLabel(
                f"waiting for board *{self.rec.board_filter}…" if self.rec.board_filter else "waiting for a board…")
            self.empty.setStyleSheet(f"color:{FG_DIM}; font-size:14pt;")
            self.empty.setAlignment(QtCore.Qt.AlignCenter)
            self.rows_box.addWidget(self.empty)

    def _row_for(self, ip, tr):
        src = self.rec.sources.get(ip)
        key = src.mac if (src is not None and src.mac) else ip
        row = self.rows.get(key)
        if row is None and key != ip and ip in self.rows:
            row = self.rows.pop(ip)          # identified: re-key from IP to MAC
            row.key = key
            self.rows[key] = row
        if row is None:
            if self.empty is not None:
                self.empty.setParent(None)
                self.empty = None
            row = self.rows[key] = BoardRow(self, key, tr)
            self.rows_box.addWidget(row)
            self.setWindowTitle(f"{script_name(__file__)} — {self.rec.session_id}"
                                f"  (hub {self.hub_text})")
        row.trace, row.src = tr, src
        return row

    def redraw(self):
        if self._closing:
            return
        now = time.monotonic()
        for ip, tr in sorted(self.traces.items(), key=lambda kv: kv[1].first_seen):
            self._row_for(ip, tr).refresh(now, self.plots_on)

    # ── settings and closing ──
    def _restore_geometry(self):
        saved = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("geometry")
        if saved is not None and self.restoreGeometry(saved):
            return
        screen = QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            self.resize(1400, 900)
        else:
            self.resize(int(area.width() * 0.9), int(area.height() * 0.9))
            self.move(area.left() + 20, area.top() + 20)

    def closeEvent(self, event):
        if not self._closing and not self.rec.stopped:
            ask = QtWidgets.QMessageBox.question(
                self, "stop the session?",
                f"Close every file of session {self.rec.session_id} and exit?\n"
                "Nothing is lost either way; this only asks because a session cannot be resumed "
                "into the same files.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if ask != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.rec.stop("operator")
        self._closing = True
        for t in self.timers:          # BEFORE the socket is closed, or they fire on a dead one
            t.stop()
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("geometry", self.saveGeometry())
        self.client.close()
        self.rec.close()
        event.accept()


# ============================================================================================
# start-up: the two facts only a person knows, asked once
# ============================================================================================
# The ten fields a session file can set -- what a baby's session IS, never how the tool behaves
# (--hub, --out, --raw, --split-min, --duration, --min-free-gb stay command-line only: they are
# the same for all three cots and belong to the laptop, not the baby).
CONFIG_FIELDS = ("location", "operator", "board", "subject", "videonest", "note", "probe",
                 "ref_model", "ref_avg", "ref_probe_site", "ref_note")


def load_session_config(path):
    """A TOML session file -> {field: value}, every value a string ("" if absent).

    [ref] groups everything about the ONE commercial monitor a session is checked against --
    including which phone is filming it, since a phone reads that same monitor's screen rather
    than being a fact about the baby on its own (Alex, 2026-09-22, thinking ahead to a possible
    second physical oximeter some day: this is the shape that could grow into `[[ref]]`, one
    table per monitor, without a second reshape of the file):

        location = "HOSP01"
        operator = "AC"
        board    = "8850"
        subject  = "SUBJ01"
        note     = "term neonate, resting after a feed"
        probe    = "Medle-neo"   # OUR probe's model -- ISO 80601-2-61 calibrates monitor+probe
                                 # together, and the library cannot know which sensor is on the baby

        [ref]
        model      = "Masimo Radical-7"
        avg        = 8
        probe-site = "left thumb"
        videonest  = "J6plusACM"

    `note` is free text (written verbatim as a NOTE event) and its sanitised form also seeds the
    starting CONDITION -- there is no separate `cond` field, because a short, controlled-vocabulary
    word was not worth a launch parameter of its own when a note already says more and can be
    corrected in the window the moment it changes.

    Raises OSError if the file cannot be read, tomllib.TOMLDecodeError if it is not valid TOML.
    Neither is caught here -- the caller decides how to report it.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    ref = data.get("ref") or {}

    def text(v):
        return "" if v is None else str(v)
    return {
        "location": text(data.get("location")), "operator": text(data.get("operator")),
        "board": text(data.get("board")), "subject": text(data.get("subject")),
        "videonest": text(ref.get("videonest")), "note": text(data.get("note")),
        "probe": text(data.get("probe")),
        "ref_model": text(ref.get("model")), "ref_avg": text(ref.get("avg")),
        "ref_probe_site": text(ref.get("probe-site")), "ref_note": text(ref.get("note")),
    }


def apply_session_config(args, path):
    """Load `path` into `args`, in place. FULL substitution: raises ValueError if any of the ten
    fields was ALSO typed on the command line, rather than silently choosing one -- the same
    discipline as the ambiguous --board suffix (one session, one baby, one source of truth for
    who it is)."""
    typed = [f for f in CONFIG_FIELDS if getattr(args, f)]
    if typed:
        names = ", ".join("--" + f.replace("_", "-") for f in typed)
        raise ValueError(f"--config replaces {names} entirely; drop --config or drop {names}")
    for field, value in load_session_config(path).items():
        setattr(args, field, value)


def ask_session(app, location, operator):
    if location:
        return location, operator
    dlg = QtWidgets.QDialog()
    dlg.setStyleSheet(DARK_QSS)
    dlg.setWindowTitle("new recording session")
    form = QtWidgets.QFormLayout(dlg)
    loc = QtWidgets.QComboBox()
    loc.setEditable(True)
    loc.addItems(["BENCH", "HOSP01", "SITE01"])
    loc.setToolTip("A CODE, never a place: BENCH, HOSP01, SITE01. The code-to-place list stays "
                   "outside the repository, beside the subject list. A place plus a date plus a "
                   "subject identifies a person.")
    op = QtWidgets.QLineEdit(operator)
    op.setPlaceholderText("initials or role, never a full name")
    form.addRow("LOCATION code", loc)
    form.addRow("OPERATOR", op)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    if dlg.exec_() != QtWidgets.QDialog.Accepted:
        return None, None
    return loc.currentText().strip(), op.text().strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="", metavar="FILE.toml",
                    help="read location/operator/board/subject/videonest/cond/ref-* from this "
                         "TOML file instead of typing them -- one per cot, prepared the day "
                         "before. FULL substitution: giving --config together with any of those "
                         "flags is refused, not merged")
    ap.add_argument("--location", default="", help="site CODE for the session id (BENCH, HOSP01); asked if absent")
    ap.add_argument("--operator", default="", help="initials or role, never a full name")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(_HERE), "captures", "sessions"),
                    metavar="DIR",
                    help="where session directories are created (default captures/sessions). "
                         "Point it at a second disk and the recording is written there directly, "
                         "instead of being copied afterwards")
    ap.add_argument("--csv", default="v04", choices=("v04", "on", "off"),
                    help="live capture CSV per board: on = today's format, v04 = capture_csv_format_spec.md v0.4, off")
    ap.add_argument("--raw", default="full", choices=("full", "exceptions", "off"),
                    help="the .pnraw stream in raw/: `full` keeps every datagram verbatim, "
                         "`exceptions` only the ones around a gap or a restart, `off` writes no "
                         "raw/ directory at all. The CSV is unaffected. Off halves the ~17 MB per "
                         "minute per board and gives up the only copy of what arrived on the wire, "
                         "so a parsing bug found later can no longer be repaired from it")
    ap.add_argument("--board", default="", metavar="SUFFIX",
                    help="record ONLY the board whose MAC ends in this (any length: 8850, "
                         "508850). One window, one board, one baby")
    ap.add_argument("--subject", default="", metavar="SUBJnn",
                    help="bind this coded subject as soon as the board is identified")
    ap.add_argument("--videonest", default="", metavar="ID",
                    help="device id of the phone pointed at THIS baby's monitor")
    ap.add_argument("--note", default="", metavar="TEXT",
                    help="a free-text note about this baby's session, applied once the subject "
                         "is known: written verbatim as a NOTE event, and its sanitised form "
                         "also seeds the starting CONDITION (correctable in the window)")
    ap.add_argument("--probe", default="", metavar="MODEL",
                    help="OUR probe's physical model (e.g. Medle-neo) -- the library cannot know "
                         "which sensor is plugged in, applied once the subject is known")
    ap.add_argument("--ref-model", default="", metavar="TEXT", help="commercial monitor: make and model")
    ap.add_argument("--ref-avg", default="", metavar="SECONDS", help="commercial monitor: its averaging window")
    ap.add_argument("--ref-probe-site", default="", metavar="TEXT", help="commercial monitor: where ITS probe is")
    ap.add_argument("--ref-note", default="", metavar="TEXT", help="commercial monitor: anything else")
    ap.add_argument("--min-free-gb", type=float, default=2.0)
    ap.add_argument("--split-min", type=float, default=SPLIT_MIN_DEFAULT, metavar="MIN",
                    help=f"split both the .pnraw and the live CSV on this wall-clock period "
                         f"(default {SPLIT_MIN_DEFAULT:.0f}). At 500 Hz a board writes about "
                         f"8.7 MB of CSV per minute, so 10 min is a part of roughly 87 MB -- "
                         f"lower it if the tool that opens the CSV struggles")
    ap.add_argument("--duration", type=float, default=0.0, metavar="S",
                    help="close the session cleanly after this many seconds (0 = until the "
                         "operator stops it). For an unattended bench soak")
    args = ap.parse_args(argv)
    if args.config:
        try:
            apply_session_config(args, args.config)
        except ValueError as exc:
            ap.error(str(exc))
        except OSError as exc:
            ap.error(f"cannot read {args.config}: {exc}")
        except tomllib.TOMLDecodeError as exc:
            ap.error(f"{args.config} is not valid TOML: {exc}")
    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    pg.setConfigOptions(useOpenGL=False, antialias=False)
    app = QtWidgets.QApplication(sys.argv[:1])
    location, operator = ask_session(app, args.location, args.operator)
    if not location:
        return 1
    try:
        rec = Recorder(args.out, location, operator, raw_mode=args.raw, csv_mode=args.csv,
                       hub_text=f"{hub[0]}:{hub[1]}",
                       split_s=args.split_min * 60,
                       min_free_bytes=int(args.min_free_gb * 1e9),
                       board=args.board, subject=args.subject, videonest=args.videonest,
                       note=args.note, probe=args.probe, ref_model=args.ref_model,
                       ref_avg=args.ref_avg, ref_probe_site=args.ref_probe_site,
                       ref_note=args.ref_note)
    except (NotEnoughSpace, OSError) as exc:
        QtWidgets.QMessageBox.critical(None, "not starting", str(exc))
        return 2
    win = RecorderWindow(rec, hub, duration_s=args.duration)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
