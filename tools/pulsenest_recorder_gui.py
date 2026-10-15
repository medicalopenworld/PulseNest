"""The operator's face for pulsenest_recorder.py: one row per board, and the controls that make
a capture usable, beside the waveform that says whether the probe is still on the foot.

    python tools/pulsenest_recorder_gui.py [--location HOSP01] [--operator AC] [--hub IP[:PORT]]
                                          [--split-min 10] [--duration S]
    python tools/pulsenest_recorder_gui.py --config docs/session_configs/cot1.toml

Its arguments are pulsenest_recorder.add_session_args(), the console recorder's own, so the two
--help texts are the same by construction; the console adds only --event-port.

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
    at launch, read-only in the .toml's order (REFERENCE as a control that locks),
    then NEW EVENT, then the reading entry;
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
import datetime as _dt
import sys
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest.net import UDP_DATA_PORT, script_name, open_in_system     # noqa: E402
from pulsenest.hub_client import HubClient                               # noqa: E402
from tools.pulsenest_recorder import (Recorder, NotEnoughSpace, SessionExists,  # noqa: E402, F401
                                add_session_args, apply_session_config, CONFIG_FIELDS)
from pulsenest.fleet_trace import BoardTrace, MIN_PLOT_W, RED, LINK    # noqa: E402
from pulsenest.fleet_widgets import make_stats_widget, stats_width, stats_columns  # noqa: E402
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

# The four [subject] rows after SUBJECT, in the file's order (Alex, 2026-10-14).
SUBJECT_ROWS = (
    ("gest_age", "GEST AGE", "Gestational age at birth, as the chart writes it: 30w+2d\n"
                             "(`gest_age` in [subject] / --gest-age). Fetal haemoglobin, hence\n"
                             "the R curve, follows it."),
    ("age", "AGE", "Age as a number with its unit, d/w/m/y, joined with +: 14d, 3w+2d, 6m,\n"
                   "34y (`age` in [subject] / --age). A unit, not a count of days, because a\n"
                   "later campaign may measure children or adults."),
    ("weight_g", "WEIGHT", "Current weight in grams (`weight_g` in [subject] / --weight-g):\n"
                           "the tissue the probe sees."),
    ("skin", "SKIN", "`skin` in [subject] / --skin.\n" + "Monk Skin Tone (MST) scale, a whole number 1-10: 1 the lightest tone, 10 the darkest.\n"
                     "Ten swatches published by Google with Dr Ellis Monk (Harvard, 2022), free at\n"
                     "https://skintone.google -- print them, or open the page on the phone. Judge it AT THE\n"
                     "PROBE SITE (the foot), not the face, under daylight or the room's white light, holding\n"
                     "the swatch against the skin; write the closest number. Why MST and not Fitzpatrick:\n"
                     "Fitzpatrick grades sun reactivity with few dark tones; the FDA's January 2025 draft\n"
                     "guidance for pulse-oximeter clinical studies asks for MST. Why per session: a newborn's\n"
                     "pigmentation darkens over the first weeks, so this is the day's value, not the birth's.\n"
                     "Torn between two? Pick one and say so in `note`. It is the best documented SpO2 bias."),
)


def subject_text(key, value):
    """How a [subject] value reads in the panel: with its unit, or (not set)."""
    if value in (None, ""):
        return "(not set)"
    return {"gest_age": f"{value}", "age": f"{value}", "weight_g": f"{value} g",
            "skin": f"Monk {value}"}[key]
# The SpO2 entry is the one thing an operator does again and again at the cot side, so it is
# built for a finger, not a mouse (Alex, 2026-10-15): RECORD three times the height of a
# button, the SpO2 box the same height, and its own 14 x 16 px arrow buttons replaced by two
# push buttons beside it, each half that height and SPIN_BTN_W wide, with the arrow as text so
# it grows with the font. A stylesheet cannot do it: Qt's arrow glyph stays 7 px whatever the
# button measures, and the CSS-triangle trick draws a bar on windowsvista and on fusion (tried).
RECORD_H_FACTOR = 3
SPIN_BTN_W = 44
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
PR_NONE = 0     # the pulse-rate spinbox at its minimum reads "--": not recorded
CELL_PAD = 14   # a table cell's own left+right margins, on top of the text it holds


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
        # Everything the session was launched with (--config / the .toml, or the flags), in the
        # file's own order (Alex, 2026-10-14, after example.toml: location, operator, board,
        # probe, note; [subject] id, gest_age, age, weight_g, skin; [ref] model, probe-site,
        # videonest, avg), read-only here so a
        # typo is visible instead of silent. NEW EVENT moved to the operator's box (2026-10-14).
        # SUBJECT and
        # REFERENCE are the two a window started without them must still be able to set, so they
        # are controls that lock once a launch value is in force (see _mirror_state). CONDITION
        # left the panel the same day: it was stored in four places and read by none (the
        # console `cond` command and the META event remain for anyone who wants it).
        g = QtWidgets.QGroupBox("TOML session configuration")
        form = QtWidgets.QFormLayout(g)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        rec = self.win.rec

        def ro(label, text, tip):
            w = QtWidgets.QLabel(text)
            w.setWordWrap(True)
            w.setStyleSheet(f"color:{FG_DIM};")
            w.setToolTip(tip)
            form.addRow(label, w)
            return w

        # The file first (Alex, 2026-10-14: "the window said nowhere which .toml it was using"):
        # with three windows open, one per cot, the file name is how an operator tells them apart
        # before the subject is bound. Base name shown, full path in the tooltip.
        cfg = self.win.config
        if cfg:
            # A link (Alex, 2026-10-14): click opens the file in the system's editor, the same
            # EDIT the launcher offers. The window keeps running on what it read at launch;
            # an edit takes effect on the next START, as everywhere else.
            self.file_label = QtWidgets.QLabel(f'<a href="open" style="color:{LINK};">'
                                               f'{os.path.basename(cfg)}</a>')
            f = self.file_label.font()
            f.setPointSize(f.pointSize() + 1)        # a link reads as one: blue, a point larger
            self.file_label.setFont(f)
            self.file_label.setToolTip("The .toml this window was launched with. Click to open "
                                       f"it in the system's editor.\n{cfg}")
            self.file_label.linkActivated.connect(lambda _l, p=cfg: open_in_system(p))
            form.addRow("FILE", self.file_label)
        else:
            self.file_label = ro("FILE", "(no --config: flags only)",
                                 "Launched from flags, not from a .toml (--config).")
        self.location_label = ro("LOCATION", rec.site or "(not set)",
                                 "Site CODE (`location` in the .toml / --location), never a place\n"
                                 "name. Names the session directory and the CSV; set at launch.")
        self.operator_label = ro("OPERATOR", rec.operator or "(not set)",
                                 "Initials or role (`operator` in the .toml / --operator), never a\n"
                                 "full name. Set at launch.")
        self.board_label = ro("BOARD", f"*{rec.board_filter}" if rec.board_filter else "(any board)",
                              "MAC suffix this window records (`board` in the .toml / --board).\n"
                              "The header line shows the full MAC once the board speaks.")
        # OUR probe, not the reference monitor's -- ISO 80601-2-61 calibrates a monitor+probe pair,
        # and the library cannot know which physical sensor is clipped onto the baby, only a person
        # can. Top-level --probe, not --ref-probe: it says nothing about the commercial monitor.
        self.probe_label = ro("PROBE", "(not set)",
                              "OUR probe's physical model, e.g. Medle-neo. Set once, at launch\n"
                              "(`probe` in the .toml / --probe), shown here read-only so a typo\n"
                              "is visible instead of silent.")
        # SUBJECT is what the file says, nothing more (Alex, 2026-10-14: no box, no menu, no
        # format check in the window). The Recorder is the one place a code is checked (SUBJ +
        # digits, never a name), at launch and on its `subject` console command; a window
        # launched without one shows "(not set)" and stays locked, since binding from here is
        # gone -- the file is the whole story, so the subject goes in the file.
        self.subject_label = ro("SUBJECT", rec.want_subject or "(not set)",
                                "The coded subject this board is on (`subject` in the .toml /\n"
                                "--subject). Codes only, never a name: the code-to-person list\n"
                                "lives outside the repository. Shown as the file says; to change\n"
                                "it, stop the session and relaunch with the right file.")

        # The subject, as the bias analysis stratifies it ([subject] in the .toml / --gest-age
        # --age --weight-g --skin; the `subj` console command once known). Read-only labels
        # like the rest; refresh() mirrors what the Recorder holds.
        self.subject_labels = {}
        for key, title, tip in SUBJECT_ROWS:
            self.subject_labels[key] = ro(title, subject_text(key, rec.want_subject_info.get(key)), tip)
        self.launch_note_label = ro("NOTE", rec.want_note or "(none)",
                                    "`note` in the .toml / --note: written once, verbatim, as a NOTE\n"
                                    "event when the board binds to its subject. This is that text.\n"
                                    "Anything that happens later goes in NEW EVENT below.")
        self.ref_label = ro("MONITOR", "(not set)",
                            "The commercial monitor beside this baby: make and model, its\n"
                            "averaging window in seconds, where ITS probe is, and any note.\n"
                            "Set once, at launch ([ref] in the .toml / --ref-model, --ref-avg,\n"
                            "--ref-probe-site, --ref-note). Shown here read-only so you can\n"
                            "see it was typed correctly, not to be edited from the window.")

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
                              "monitor and sending to the hub. Then choose which phone. Given at "
                              "launch ([ref].videonest / --ref-videonest) it is locked here.")
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

        return g

    def _reading_group(self):
        # What the operator DOES, in one box (Alex, 2026-10-14): readings from the monitor and
        # the events typed as they happen. The TOML box to the left only shows.
        g = QtWidgets.QGroupBox("Readings from the monitor, and events")
        lay = QtWidgets.QGridLayout(g)
        self.note = QtWidgets.QLineEdit()
        self.note.setPlaceholderText("free text, Enter to record. Coded subjects only, no names.")
        self.note.setToolTip("What happened, in a few words: a feed, a nappy change, an alarm, a "
                             "probe moved, a desaturation. Enter writes it to session_events.csv "
                             "as an event of kind NOTE, with the time and this board's subject. "
                             "None of it can be reconstructed afterwards.")
        self.note.returnPressed.connect(self._note_entered)
        self.spo2 = QtWidgets.QSpinBox()
        self.spo2.setRange(50, 100)
        self.spo2.setValue(95)
        self.spo2.setSuffix(" %")
        self.spo2.setToolTip("SpO2 as shown on the COMMERCIAL monitor's screen, never a number "
                             "of ours. Range 50-100: a neonatal desaturation goes below 60.\n"
                             "Keys + and - change it from anywhere in the window; R records it.")
        big = self.spo2.font()
        big.setPointSize(big.pointSize() + 8)
        self.spo2.setFont(big)
        self.spo2.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)   # the two buttons below
        self.spo2_up = QtWidgets.QPushButton("\u25B2")
        self.spo2_down = QtWidgets.QPushButton("\u25BC")
        af = self.spo2_up.font()
        af.setPointSize(af.pointSize() + 4)       # the arrow is text: a bigger font, a bigger arrow
        self.spo2_up.setToolTip("One more. Key + does the same from anywhere in the window.")
        self.spo2_down.setToolTip("One less. Key - does the same from anywhere in the window.")
        for b, step in ((self.spo2_up, self.spo2.stepUp), (self.spo2_down, self.spo2.stepDown)):
            b.setFont(af)
            b.setFixedWidth(SPIN_BTN_W)
            b.setAutoRepeat(True)                  # hold it to run through the values
            b.setFocusPolicy(QtCore.Qt.NoFocus)    # the box keeps the keyboard: digits, arrows
            b.clicked.connect(step)
        self.pr = QtWidgets.QSpinBox()
        self.pr.setRange(PR_NONE, 250)
        self.pr.setSpecialValueText("--")
        self.pr.setValue(PR_NONE)
        self.pr.setToolTip("Pulse rate on the monitor, OPTIONAL: leave at -- unless you want a "
                           "pulse reference too. Since VideoNest build 8 dropped its pulse field, "
                           "this box is the only pulse reference a session can have.")
        self.record = QtWidgets.QPushButton("RECORD")
        self.record.setToolTip("Write the reading above as a REF_SPO2 event, stamped now. Check "
                               "the number against the monitor first; do not correct for delay.\n"
                               "Key R (or r) does the same from anywhere in the window.")
        self.record.clicked.connect(self._record)
        self.record.setDefault(True)
        rb = self.record.font()
        rb.setBold(True)
        self.record.setFont(rb)
        tall = RECORD_H_FACTOR * self.record.sizeHint().height()
        self.record.setMinimumHeight(tall)
        self.spo2.setMinimumHeight(tall)           # same height; the two buttons share it
        for b in (self.spo2_up, self.spo2_down):
            b.setMinimumHeight(tall // 2)
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
        entry = QtWidgets.QHBoxLayout()
        entry.setSpacing(2)
        entry.addWidget(self.spo2, 1)
        arrows = QtWidgets.QVBoxLayout()
        arrows.setSpacing(2)
        arrows.addWidget(self.spo2_up)
        arrows.addWidget(self.spo2_down)
        entry.addLayout(arrows)
        lay.addLayout(entry, 0, 1)
        lay.addWidget(QtWidgets.QLabel("PR"), 1, 0)
        lay.addWidget(self.pr, 1, 1)
        lay.addWidget(self.record, 2, 0, 1, 2)
        lay.addWidget(self.delete_last, 3, 0, 1, 2)
        lay.addWidget(self.delete_sel, 4, 0, 1, 2)      # under DELETE LAST (Alex, 2026-10-14)
        lay.addWidget(self.listing, 0, 2, 6, 1)         # ... so the table runs to the bottom
        # The keys, where the eye lands between readings (Alex, 2026-10-15). The window's event
        # filter does the work; this line and the three tooltips only say so.
        self.keys_help = QtWidgets.QLabel("keys:  +  -  change SpO2      R  = RECORD")
        self.keys_help.setStyleSheet(f"color:{FG_DIM};")
        self.keys_help.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        lay.addWidget(self.keys_help, 5, 0, 1, 2)
        lay.setRowStretch(5, 1)                         # spare height goes below the buttons
        lay.addWidget(QtWidgets.QLabel("NEW EVENT"), 6, 0)
        lay.addWidget(self.note, 6, 1, 1, 2)            # the full width, under the table
        lay.setColumnStretch(2, 1)
        self._set_dependents_enabled(False)
        return g

    def _set_dependents_enabled(self, on):
        for w in [self.vn_on, self.vn_id, self.note, self.flag_btn]:
            w.setEnabled(on)
        if hasattr(self, "record"):
            for w in (self.record, self.delete_last, self.delete_sel, self.spo2_up, self.spo2_down):
                w.setEnabled(on)

    # ── actions: every one is a console command, so there is one code path ──
    def _subj(self):
        """The subject the Recorder holds for this board; '' until bound."""
        return (self.src.subject or "") if self.src is not None else ""

    def _flag_toggled(self, on):
        if not self.flag_btn.isEnabled():
            return
        subj = self._subj()
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
        of SUBJECT (then a box) "applied" what it displayed: the baby was re-bound to SUBJ01 and
        the phone dropped (`videonest none`) -- two launch values destroyed by a stray click.
        So on every refresh, each control that does not have keyboard focus is set to what the
        Recorder holds, with its signals blocked: mirroring is not a command."""
        src, rec = self.src, self.win.rec
        if src is None or not src.mac:
            return
        shown = src.subject or rec.want_subject or "(not set)"
        if self.subject_label.text() != shown:
            self.subject_label.setText(shown)                # SIM from the console, or bound late
        if self.note.isEnabled() != bool(src.subject):
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
        if rec.expected_videonest_id:
            # A phone declared at launch (--ref-videonest / [ref].videonest) is read-only here, same
            # principle as MONITOR/PROBE below: shown so a typo is visible, not offered for the
            # operator to override by mistake. The backend refuses a switch anyway (Recorder's
            # `videonest` command), but a disabled control also cannot be clicked by mistake.
            self.vn_on.setEnabled(False)
            self.vn_id.setEnabled(False)

    def refresh_phones(self):
        """The device list fills itself from the phones actually heard. A phone that is not
        sending never appears, which is the answer to "is VideoNest working?" without a menu.

        NEVER auto-selects (removed 2026-09-23, root cause of a real misattribution): a fresh
        window's `by_vn` starts empty, so "only one phone heard so far" can mean "the one phone
        heard so far", not "the only phone in the campaign" -- with two cots' phones both live,
        whichever one happened to speak first inside THIS window's first second won, silently.
        Picking the reference is always an explicit operator action from here on, or a declared
        --ref-videonest/[ref].videonest at launch (which locks it, see expected_videonest_id)."""
        seen = sorted(self.win.rec.by_vn)
        if seen == [self.vn_id.itemText(i) for i in range(self.vn_id.count())]:
            return
        current = self.vn_id.currentText()
        self.vn_id.clear()
        self.vn_id.addItems(seen)
        if current in seen:
            self.vn_id.setCurrentText(current)

    def _note_entered(self):
        text, subj = self.note.text().strip(), self._subj()
        if text and subj:
            self.win.command(f"note {subj} {text}")
            self.note.clear()

    def _record(self):
        subj = self._subj()
        if not subj:
            return
        pr = self.pr.value()
        self.win.command(f"spo2 {subj} {self.spo2.value()}" + (f" {pr}" if pr > PR_NONE else ""))
        self.refresh_listing()

    # ── the annotation list ──
    def _readings(self):
        subj = self._subj()
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
            for key, w in self.subject_labels.items():
                w.setText(subject_text(key, src.subject_info.get(key)
                                       if src.subject_info.get(key) is not None
                                       else self.win.rec.want_subject_info.get(key)))
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



class ClockAnchorDialog(QtWidgets.QDialog):
    """The laptop's clock, filling the window, with milliseconds -- what the phone photographs.

    CLOCK ANCHOR used to write the event and nothing else, assuming the phone was already filming
    some clock; the window showed none, so the operator had to find one (Alex, 2026-09-22: "no me
    convence lo de fotografiar una página web"). Now the button writes the event AND puts the time
    on screen, 20 ms refresh, until a click or Esc. Read the photo afterwards: the digits in the
    picture are the laptop's clock, the photo's filename carries the phone's -- their difference is
    the offset between the two clocks, which is what places every phone reading on our timeline.
    """

    def __init__(self, parent, session_id):
        super().__init__(parent)
        self.setWindowTitle("CLOCK ANCHOR -- photograph this screen")
        self.setStyleSheet(f"background:{BG}; color:{FG};")
        v = QtWidgets.QVBoxLayout(self)
        self.clock = QtWidgets.QLabel("")
        self.clock.setAlignment(QtCore.Qt.AlignCenter)
        f = self.clock.font()
        f.setPointSize(96)
        f.setBold(True)
        self.clock.setFont(f)
        self.date = QtWidgets.QLabel("")
        self.date.setAlignment(QtCore.Qt.AlignCenter)
        f2 = self.date.font()
        f2.setPointSize(24)
        self.date.setFont(f2)
        hint = QtWidgets.QLabel(f"laptop clock, local time  ·  {session_id}  ·  click or Esc to close")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setStyleSheet(f"color:{FG_DIM};")
        v.addStretch(1)
        v.addWidget(self.clock)
        v.addWidget(self.date)
        v.addStretch(1)
        v.addWidget(hint)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)
        self._tick()

    def _tick(self):
        now = _dt.datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S.%f")[:-3])
        self.date.setText(now.strftime("%Y-%m-%d") + f"   {now.astimezone().strftime('%z')}")

    def mousePressEvent(self, _ev):
        self.close()

    def closeEvent(self, ev):
        self.timer.stop()
        super().closeEvent(ev)

# ============================================================================================
# the window
# ============================================================================================
class RecorderWindow(QtWidgets.QMainWindow):
    def __init__(self, rec, hub, duration_s=0.0, config=None):
        super().__init__()
        self.rec = rec
        self.config = config      # the .toml path (None when launched from flags)
        # A timed run stops the RECORDER, and tick() then closes the window the same way a full
        # disk does -- one path out of a session, not two.
        self.end_at = time.monotonic() + duration_s if duration_s > 0 else None
        self.hub_text = f"{hub[0]}:{hub[1]}"
        waiting = f" — waiting for board *{rec.board_filter}" if rec.board_filter else ""
        self.setWindowTitle(f"{script_name(__file__)} — {rec.session_id}{self.config_title()}"
                            f"{waiting}  (hub {hub[0]}:{hub[1]})")
        self.rows = {}            # key (mac, or ip until identified) -> BoardRow
        self.traces = {}          # ip -> BoardTrace
        self.aux_ips = set()
        self.plots_on = True
        self._closing = False
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=rec.log.info)
        self.client.connect()
        # Keys + / - / R act wherever the focus is (Alex, 2026-10-15: the operator looks at the
        # monitor, not at which widget is current). An application filter sees the key before the
        # focused widget does, which a QShortcut would not: a line edit swallows printable keys.
        QtWidgets.QApplication.instance().installEventFilter(self)

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

        # LOCATION and OPERATOR used to be here; since 2026-10-14 they read in each board's panel,
        # beside SUBJECT, MONITOR and PROBE, so everything a session is about sits in one place.
        self.disk = QtWidgets.QLabel()
        h.addWidget(self.disk)
        h.addStretch(1)
        anchor = QtWidgets.QPushButton("CLOCK ANCHOR")
        anchor.setToolTip("Press it, then photograph this screen with the phone: it fills the window "
                          "with the laptop's clock (milliseconds) and writes a CLOCK_ANCHOR event at "
                          "that instant. Afterwards, the digits in the photo are the laptop's time and "
                          "the photo's filename is the phone's: their difference is the offset between "
                          "the two clocks, which is what places every phone reading on our timeline. "
                          "Once per session is enough; twice (start and end) also measures drift.")
        anchor.clicked.connect(self._clock_anchor)
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

    def config_title(self):
        """' — cot1.toml' for the title bar, '' when launched from flags."""
        return f" — {os.path.basename(self.config)}" if self.config else ""

    # ── one code path for every action ──
    def _clock_anchor(self):
        self.command("anchor")
        self.clock_dialog = ClockAnchorDialog(self, self.rec.session_id)
        self.clock_dialog.showMaximized()

    # ── keys: + and - step the SpO2 box, R records (Alex, 2026-10-15) ──
    KEY_STEP = {QtCore.Qt.Key_Plus: 1, QtCore.Qt.Key_Minus: -1}

    def _key_row(self, target):
        """The row the keys act on: the one holding the key's target (the focused widget), else
        the first that can record."""
        for row in self.rows.values():
            if row.isAncestorOf(target):
                return row
        for row in self.rows.values():
            if row.record.isEnabled():
                return row
        return None

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and isinstance(obj, QtWidgets.QWidget)                 and obj.window() is self:                 # auto-repeat included: hold + to run up
            # `obj` is the widget the key goes to, i.e. the focused one. Typing into NEW EVENT
            # (or any free-text field) must keep its r, + and -; the SpO2 and PR boxes hold a
            # QLineEdit too, but no text of theirs needs those keys.
            typing = isinstance(obj, QtWidgets.QLineEdit) and                 not isinstance(obj.parent(), QtWidgets.QAbstractSpinBox)
            if not typing and ev.modifiers() in (QtCore.Qt.NoModifier, QtCore.Qt.KeypadModifier,
                                                 QtCore.Qt.ShiftModifier):
                row = self._key_row(obj)
                if row is not None:
                    if ev.key() in self.KEY_STEP and row.spo2_up.isEnabled():
                        (row.spo2.stepUp if self.KEY_STEP[ev.key()] > 0 else row.spo2.stepDown)()
                        return True
                    if ev.key() == QtCore.Qt.Key_R:
                        row.record.click()            # a click: nothing if RECORD is disabled
                        return True
        return super().eventFilter(obj, ev)

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
                                f"{self.config_title()}  (hub {self.hub_text})")
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
        QtWidgets.QApplication.instance().removeEventFilter(self)   # the keys die with the window
        for t in self.timers:          # BEFORE the socket is closed, or they fire on a dead one
            t.stop()
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("geometry", self.saveGeometry())
        self.client.close()
        self.rec.close()
        event.accept()


# ============================================================================================
# start-up: the two facts only a person knows, asked once
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
    ap = argparse.ArgumentParser(description=" ".join(__doc__.split("\n\n")[0].split()))
    add_session_args(ap)
    args = ap.parse_args(argv)
    # QApplication built BEFORE --config is read (moved 2026-09-23, was after): this window is
    # always launched with `pythonw`, which has no console, so `ap.error()` -- stderr, then exit
    # -- used to fail SILENTLY: a `.toml` with a duplicate `note` (TOML forbids repeating a key)
    # closed the process with no window, no dialog, nothing on screen (Alex, same day: "no vi
    # ningun mensaje de error"). A QMessageBox needs a QApplication to exist first, so it moves up
    # here rather than trying to detect pythonw specifically -- a dialog is also the more visible
    # answer even under plain `python`, where the console can be behind another window.
    pg.setConfigOptions(useOpenGL=False, antialias=False)
    app = QtWidgets.QApplication(sys.argv[:1])
    if args.config:
        try:
            apply_session_config(args, args.config)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(None, "not starting", str(exc))
            return 2
        except OSError as exc:
            QtWidgets.QMessageBox.critical(None, "not starting",
                                           f"cannot read {args.config}: {exc}")
            return 2
        except tomllib.TOMLDecodeError as exc:
            QtWidgets.QMessageBox.critical(None, "not starting",
                                           f"{args.config} is not valid TOML: {exc}")
            return 2
    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    location, operator = ask_session(app, args.location, args.operator)
    if not location:
        return 1
    try:
        rec = Recorder(args.out, location, operator, raw_mode=args.raw, csv_mode=args.csv,
                       csv_profile=args.csv_profile,
                       hub_text=f"{hub[0]}:{hub[1]}",
                       split_s=args.split_min * 60, split_bytes=int(args.split_mb * 1024 * 1024),
                       min_free_bytes=int(args.min_free_gb * 1e9),
                       board=args.board, subject=args.subject, videonest=args.ref_videonest,
                       note=args.note, probe=args.probe, ref_model=args.ref_model,
                       ref_avg=args.ref_avg, ref_probe_site=args.ref_probe_site,
                       ref_note=args.ref_note, gest_age=args.gest_age, age=args.age,
                       weight_g=args.weight_g, skin=args.skin)
    except (NotEnoughSpace, SessionExists, OSError) as exc:
        QtWidgets.QMessageBox.critical(None, "not starting", str(exc))
        return 2
    win = RecorderWindow(rec, hub, duration_s=args.duration, config=args.config)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
