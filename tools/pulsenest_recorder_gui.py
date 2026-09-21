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
    numbers in a T2 session are read off the COMMERCIAL monitor, and a big number of our own
    beside the entry box invites copying it;
  * a control panel to the right of each SIGNAL STATS table: the values that do not change
    during the session (subject, references, condition, a note line), then the reading entry;
  * every row folds to a single header line, so three boards fit on a laptop screen and a row
    that needs no attention takes no room.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, script_name                     # noqa: E402
from pulsenest_hub_client import HubClient                               # noqa: E402
from pulsenest_recorder import (Recorder, NotEnoughSpace, TRUTH_SOURCES,  # noqa: E402
                                mac_compact, SPLIT_MIN_DEFAULT)
from fleet_ppg_viewer import (BoardTrace, make_stats_widget, stats_width,  # noqa: E402
                              stats_columns, MIN_PLOT_W, RED, GREY)
import pyqtgraph as pg                                                   # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                               # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_fault_log = open(os.path.join(_HERE, "pulsenest_recorder_gui_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

SETTINGS_FILE = os.path.join(_HERE, "pulsenest_recorder_gui.ini")
DRAIN_MS, REDRAW_MS, TICK_MS = 20, 100, 250
WINDOW_S = 15.0
AMBER = "#FFB000"
SUBJECTS = [f"SUBJ{n:02d}" for n in range(1, 13)]
CONDITIONS = ["RESTING", "FEEDING", "HANDLING", "KANGAROO", "PHOTOTHERAPY", "SLEEPING"]
# Label the operator reads -> key the recorder stores. Same order as TRUTH_SOURCES.
REF_LABELS = {"simulator": "simulator", "videonest_udp": "VideoNest UDP",
              "videonest_csv": "VideoNest CSV", "videonest_pictures": "VideoNest pictures",
              "operator": "operator annotation"}
PR_NONE = 0     # the pulse-rate spinbox at its minimum reads "--": not recorded


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
        head.addWidget(self.fold)
        head.addWidget(self.title)
        head.addWidget(self.counters, 1)
        head.addWidget(self.warn)
        outer.addLayout(head)

        # ── body ──
        self.body = QtWidgets.QWidget()
        body = QtWidgets.QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self.plot_w = pg.PlotWidget()
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
        g = QtWidgets.QGroupBox("Session values (do not change during the session)")
        form = QtWidgets.QFormLayout(g)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.subject = QtWidgets.QComboBox()
        self.subject.addItem("")
        self.subject.addItems(SUBJECTS)
        self.subject.setToolTip("The coded subject this board is on. Codes only, never a name: "
                                "the code-to-person list lives outside the repository. Everything "
                                "else in this panel waits for this.")
        self.subject.currentTextChanged.connect(self._subject_changed)
        form.addRow("SUBJECT", self.subject)

        refs_box = QtWidgets.QWidget()
        refs = QtWidgets.QVBoxLayout(refs_box)
        refs.setContentsMargins(0, 0, 0, 0)
        refs.setSpacing(0)
        self.refs = {}
        for k in TRUTH_SOURCES:
            cb = QtWidgets.QCheckBox(REF_LABELS[k])
            cb.toggled.connect(self._refs_changed)
            self.refs[k] = cb
            refs.addWidget(cb)
        refs_box.setToolTip("Every reference that exists for this baby -- tick all that apply. "
                            "This is what an analysis can compare our SpO2 against; the T-class "
                            "in the filename is derived from it, nobody types it.")
        form.addRow("REFERENCES", refs_box)

        self.condition = QtWidgets.QComboBox()
        self.condition.setEditable(True)
        self.condition.addItem("")
        self.condition.addItems(CONDITIONS)
        self.condition.setToolTip("What the baby is doing, one word. It becomes part of the CSV "
                                  "filename, so reuse the same words across sessions.")
        # `activated` is the operator picking from the list; `editingFinished` is a typed
        # word plus Enter. Not `currentTextChanged`: that is one command per keystroke.
        self.condition.activated.connect(self._condition_changed)
        self.condition.lineEdit().editingFinished.connect(self._condition_changed)
        form.addRow("CONDITION", self.condition)

        self.note = QtWidgets.QLineEdit()
        self.note.setPlaceholderText("free text, Enter to record. Coded subjects only, no names.")
        self.note.returnPressed.connect(self._note_entered)
        form.addRow("NOTE", self.note)
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
        self.listing.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.listing.horizontalHeader().setStretchLastSection(True)
        self.listing.verticalHeader().setVisible(False)
        self.listing.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.listing.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.listing.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.listing.setMinimumWidth(260)
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
        for w in list(self.refs.values()) + [self.condition, self.note]:
            w.setEnabled(on)
        if hasattr(self, "record"):
            for w in (self.record, self.delete_last, self.delete_sel):
                w.setEnabled(on)

    # ── actions: every one is a console command, so there is one code path ──
    def _subject_changed(self, text):
        if not text or self.src is None or not self.src.mac:
            self._set_dependents_enabled(False)
            return
        self.win.command(f"subject {suffix(self.src.mac)} {text}")
        self._set_dependents_enabled(True)
        # Re-apply what the operator may already have chosen while the subject was blank.
        self._refs_changed()
        self._condition_changed()

    def _refs_changed(self, *_):
        subj = self.subject.currentText()
        if not subj or not self.refs["operator"].isEnabled():
            return
        ticked = [k for k, cb in self.refs.items() if cb.isChecked()]
        if ticked or (self.src is not None and self.src.truth_sources):
            self.win.command(f"refs {subj} {','.join(ticked) if ticked else 'none'}")

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
        if self.body.isVisible():
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
        self.setWindowTitle(f"{script_name(__file__)} — {rec.session_id}  (hub {hub[0]}:{hub[1]})")
        self.rows = {}            # key (mac, or ip until identified) -> BoardRow
        self.traces = {}          # ip -> BoardTrace
        self.aux_ips = set()
        self.plots_on = True
        self._closing = False
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=rec.log.info)
        self.client.connect()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)
        v.addWidget(self._session_bar())
        self.rows_box = QtWidgets.QVBoxLayout()
        self.rows_box.setSpacing(4)
        v.addLayout(self.rows_box, 1)
        self.empty = QtWidgets.QLabel("waiting for a board…")
        self.empty.setStyleSheet(f"color:{GREY}; font-size:14pt;")
        self.empty.setAlignment(QtCore.Qt.AlignCenter)
        self.rows_box.addWidget(self.empty)
        self.log_line = QtWidgets.QLabel(f"recording into {rec.dir}")
        self.log_line.setStyleSheet(f"color:{GREY};")
        v.addWidget(self.log_line)
        self._restore_geometry()

        for ms, fn in ((DRAIN_MS, self.drain), (REDRAW_MS, self.redraw), (TICK_MS, self.tick)):
            t = QtCore.QTimer(self)
            t.timeout.connect(fn)
            t.start(ms)

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
        h.addWidget(QtWidgets.QLabel("CONSENT"))
        self.consent = QtWidgets.QComboBox()
        self.consent.addItems(["pending", "obtained", "n/a"])
        self.consent.setCurrentText(self.rec.consent)
        self.consent.setToolTip("Must be `obtained` before anything from this session leaves the "
                                "laptop. `n/a` is a bench run with no human subject.")
        self.consent.currentTextChanged.connect(lambda t: self.command(f"consent {t}"))
        h.addWidget(self.consent)
        h.addSpacing(16)
        self.disk = QtWidgets.QLabel()
        h.addWidget(self.disk)
        h.addStretch(1)
        anchor = QtWidgets.QPushButton("CLOCK ANCHOR")
        anchor.setToolTip("Press while filming this laptop's clock with the phone. It ties the "
                          "video to the recording without trusting two clocks to agree.")
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
        now = time.monotonic()
        for _ in range(256):
            item = self.client.recv(0.0)
            if item is None:
                break
            ip, data = item
            self.rec.feed(ip, data)
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
            self.disk.setStyleSheet(f"color:{RED if fb < 2 * self.rec.min_free_bytes else GREY};")

    # ── rows: one per board, keyed by MAC once the board has said who it is ──
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
        row.trace, row.src = tr, src
        return row

    def redraw(self):
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
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("geometry", self.saveGeometry())
        self.client.close()
        self.rec.close()
        event.accept()


# ============================================================================================
# start-up: the two facts only a person knows, asked once
# ============================================================================================
def ask_session(app, location, operator):
    if location:
        return location, operator
    dlg = QtWidgets.QDialog()
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
    ap.add_argument("--location", default="", help="site CODE for the session id (BENCH, HOSP01); asked if absent")
    ap.add_argument("--operator", default="", help="initials or role, never a full name")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(_HERE), "captures", "sessions"))
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
    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    pg.setConfigOptions(useOpenGL=False, antialias=False)
    app = QtWidgets.QApplication(sys.argv[:1])
    location, operator = ask_session(app, args.location, args.operator)
    if not location:
        return 1
    try:
        rec = Recorder(args.out, location, operator, hub_text=f"{hub[0]}:{hub[1]}",
                       split_s=args.split_min * 60,
                       min_free_bytes=int(args.min_free_gb * 1e9))
    except (NotEnoughSpace, OSError) as exc:
        QtWidgets.QMessageBox.critical(None, "not starting", str(exc))
        return 2
    win = RecorderWindow(rec, hub, duration_s=args.duration)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
