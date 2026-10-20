"""One live PPG band per board — the window you open to see whether a probe has moved.

A read-only subscriber of the hub (spec §4.11), like tools/fleet_monitor.py and with the same
guarantee: it holds no control, so no $SET and no $MODE can leave it, by construction. Where the
fleet monitor shows numbers, this shows the waveform: one band per board, stacked, so a probe
that slips shows up as the shape going wrong at a glance — usually before any number moves.

    python tools/fleet_ppg_viewer.py [--hub IP[:PORT]] [--window 15] [--opengl]

The window size, the seconds on screen and the size of the statistics panel are remembered in
`tools/fleet_ppg_viewer.ini`. The seconds on screen can also be changed live from the SECONDS ON
SCREEN selector at the top of the window (2026-10-17).
(per machine, not versioned), so the first-run defaults — a size taken from the screen rather
than a fixed number of pixels that cannot know how many bands there will be — only ever matter
once.

Deliberately narrow. It does not capture, does not command a board, carries no algorithms and no
configuration; all of that lives elsewhere. If it dies, it is relaunched and nothing else notices
— which is the whole point of being a separate process hanging off the hub.

**It is also a controlled experiment.** pyqtgraph's paint code has killed pulsenest_lab.py 28
times (`faulthandler.log`, `project_signals2_crash_investigation_task`), and the one lead never
tested is `useOpenGL=True`, which the lab sets and pyqtgraph's own authors flag as a source of
segfaults. This viewer starts with **OpenGL off** and `--opengl` turns it on, with faulthandler
writing to its own file. Left running for hours it answers the question either way, and it can
crash as often as it likes without costing a capture.

What it draws, and why those choices:

- **`PPG_DISP`** (field `p[9]` of `$M*`): already band-passed and negated for display by the
  library, so the band shows a pulse the way a person expects to see one.
- **One Y axis per band, never shared.** Amplitudes differ by orders of magnitude between boards
  and probe sites; a shared axis would flatten every trace but the largest.
- **A common X axis in seconds-ago**, from the datagram's arrival time at this PC. Each board has
  its own clock and its own sample counter, so arrival time is the only thing comparable across
  boards — the same reasoning behind `host_t_us` in multi-board capture (§4.8 F3). A board that
  goes quiet stops advancing and leaves a growing gap at the right edge, which is itself the
  signal that something is wrong.
- **Decimated to ~50 Hz** (1 sample in 10). The pulse shape needs nothing faster, and it keeps
  the redraw cheap — which, given what this program is testing, is not a detail.
- **Identity by MAC, not IP**, as everywhere else: a board back on a new DHCP lease keeps its
  band instead of growing a second one.
- **Title and frame coloured by ProbeState** (green APPLIED, red anything else, and LOST after
  2 s of silence). The state often names the problem before the waveform shows it.
- **Two large numbers beside each band**, in the idiom of a bedside oximeter (Masimo, Nellcor,
  Philips): SpO2 in cyan, pulse rate in green, each as digits under a small unit line that
  also names the measurement (`% SpO2`, `bpm HR3`) — two lines, not three, because with a
  separate label as well the panel ran out of vertical room and pushed the rows out of line.
  A small red heart sits to the left of the rate, as on the machines this borrows from, and it
  follows the same colour code as the digits so that it never beats beside a `--`. Three
  conventions from those machines are worth copying exactly, because they are about not
  misleading the person reading across the room:
  * an invalid reading shows **`--`**, never the last good number and never a sentinel. The
    firmware sends `-1.00`; showing that would read as a measurement.
  * the digits **dim** when the measurement's own SQI is below 0.9 — the same threshold SIGNAL
    STATS uses in the lab — so a number you should not trust does not shout as loudly as one
    you can.
  * the number is large enough to read from where you stand, which is the whole point.
  The rate is labelled **HR3**, not "PR": this is a bench tool with three heart-rate algorithms
  running side by side, and hiding which one produced the number would be the wrong kind of
  faithfulness to the commercial idiom.
- **A statistics panel on the right of each band** — the same table SIGNAL STATS shows in the
  lab, down to its font and its colours: per signal, **mean, SD, min and max** over the last
  second, always the four. 25 signals of the frame are always there, in the order of struct
  AFE4490Data and then AFE4490AnalogState — the same order as SIGNAL STATS in the lab (raw codes,
  ambient-subtracted, PPG, SpO2, SpO2 SQI, R, r reg corr, PI, HR1-3 and their SQIs, RSQI, then
  V_TIA, I_PD, OT; 2026-10-20). The panel is as tall as its band and **scrolls** to the rows that
  do not fit — in a short band that means the raw codes show and SpO2/HR are a scroll away.
  **A click on any cell boxes it in yellow** (the gold of SIGNAL STATS's highlight in the lab);
  a second click removes the box (2026-10-20). Per board, header and label column included. The
  box is kept by row label on the board's trace, so it survives the 1 s rewrite of the table and a
  board coming back on a new address, and it is **saved per board MAC** in fleet_ppg_viewer.ini
  (group `stats_highlighted`, `<label>=<col>;…`) at every click, like the lab's SIGNAL STATS: a
  board's boxes come back on the next run as soon as its $CFG names its MAC. Every cell always carries a
  2 px border in its own background colour, in place of 2 px of padding, so a box changes colour
  only and the table does not move.

  It is a read-only `QTextEdit` in a proxy item rather than a drawn label, for three reasons
  that were all learned the hard way. A widget brings a real scrollbar. It clips itself, so
  nothing can end up painted outside the window. And its content has no say in how tall the
  band is — when it did, the bands stopped being equal: the label asked for its document's
  height, the document was truncated to what fit the plot, and the plot's height came from the
  row, so a band one pixel taller fitted one more row, asked for more height, and fitted
  another. Every band row now carries the same stretch factor, and the loop cannot come back.

  The font is SIGNAL STATS's (`monospace` as the lab asks for it) at this panel's own smaller
  size. Note what that means here: Qt resolves that family to a **proportional** face, which is
  invisible in the lab because a `QTableWidget` aligns by cells — so this panel aligns by table
  columns too, never by padding spaces.

  **The averaging window is one second and does NOT follow the redraw.** The window redraws ten
  times a second; a statistic over 100 ms is mostly noise, and SIGNAL STATS averages over its
  own interval (1 s by default). Keeping the two cadences separate is deliberate — how often a
  number is *judged* is not the same question as how often it is *shown*. (The big numbers'
  SQI dimming still reads a single sample; aligning that is an open decision, 2026-09-19.)
"""
import argparse
import faulthandler
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest.net import UDP_DATA_PORT, banner, script_name  # noqa: E402
from pulsenest.net import AUX_PREFIXES           # noqa: E402  (one rule, one place)
from pulsenest.hub_client import HubClient                    # noqa: E402
import pyqtgraph as pg                                        # noqa: E402
from PyQt5 import QtCore, QtWidgets                           # noqa: E402

_fault_log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fleet_ppg_viewer_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

from pulsenest.fleet_trace import BoardTrace, MIN_PLOT_W, STATS_ROWS, WINDOW_S, merge_by_mac  # noqa: E402
from pulsenest.fleet_widgets import (make_stats_widget, panel_width, stats_cell_at,  # noqa: E402
                                     stats_columns, stats_width)

REDRAW_MS    = 100
DRAIN_MS     = 20
# What the SECONDS ON SCREEN selector offers. 5 s shows the shape of each beat; 30-120 s a breath
# hold from start to recovery; 300 s the whole of one. At 50 Hz on screen (fleet_trace.DECIM) 300 s
# is 15 000 points per board, which pyqtgraph redraws at 10 Hz without effort.
WINDOW_CHOICES_S = (5, 10, 15, 30, 60, 120, 300)
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fleet_ppg_viewer.ini")


class _StatsClick(QtCore.QObject):
    """Left click on a statistics cell -> Viewer.toggle_stats_cell(ip, row, col). An event filter
    on the panel's viewport: the panel stays read-only (NoTextInteraction), nothing is selected."""

    def __init__(self, viewer, ip, edit):
        super().__init__(edit)
        self.viewer, self.ip, self.edit = viewer, ip, edit

    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            cell = stats_cell_at(self.edit, event.pos())
            if cell is not None:
                self.viewer.toggle_stats_cell(self.ip, *cell)
                return True
        return False


class Viewer(QtWidgets.QMainWindow):
    """The window: one band per board — waveform, bedside numbers, statistics — with a drain
    timer and a redraw timer. Nothing else: no capture, no control."""

    def __init__(self, hub, window_s):
        super().__init__()
        self.setWindowTitle(f"{script_name(__file__)} — live PPG per board "
                            f"(hub {hub[0]}:{hub[1]}, read-only)")
        self._restore_geometry()
        self.window_s = window_s
        self.traces = {}
        self.aux = set()       # IPs classified as auxiliary sources (AUX_PREFIXES): no band
        self.bands = {}          # ip -> (PlotItem, PlotDataItem, LabelItem, LabelItem)
        self.band_rows = {}      # ip -> its layout row, kept apart so drop_band() stays simple
        self._next_row = 0       # monotonic: see band_for()
        self._panel_w = panel_width()
        self._stats_w = stats_width()
        self._stats_cols = stats_columns()
        # Boxed statistics cells, saved per board MAC like the lab saves SIGNAL STATS's (2026-10-20).
        # A band appears on a board's first datagram but its MAC only with its $CFG, so the saved
        # boxes are applied when the MAC becomes known (_apply_saved_boxes), once per MAC.
        self._saved_boxes = self._load_boxes()
        self._boxes_applied = set()
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=print)
        self.client.connect()

        self.layout_widget = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self.layout_widget)
        self._build_toolbar()
        # The WINDOW refuses to be narrower than its two panels plus a usable waveform. This is
        # the lesson from the three empty tables: the panel columns are fixed width, so when the
        # window is narrower than they are, the grid overflows to the right and what does not
        # fit is simply not drawn — no scrollbar, no clue, just an empty panel. Putting the
        # minimum on the window makes that state unreachable instead of detectable. (It is NOT
        # on the layout widget: that was the first attempt, and a QScrollArea around it only
        # moved the table behind a horizontal bar, which is the same invisibility with a handle.)
        self.setMinimumWidth(self._panel_w + self._stats_w + MIN_PLOT_W + 24)   # + margins
        self._empty = self.layout_widget.addLabel("waiting for a board…", color="#888888",
                                                  size="14pt")

        self.drain_timer = QtCore.QTimer(self)
        self.drain_timer.timeout.connect(self.drain)
        self.drain_timer.start(DRAIN_MS)
        self.redraw_timer = QtCore.QTimer(self)
        self.redraw_timer.timeout.connect(self.redraw)
        self.redraw_timer.start(REDRAW_MS)

    # ── the seconds-on-screen selector (2026-10-17) ───────────────────────────────────────
    def _build_toolbar(self):
        bar = self.addToolBar("view")
        bar.setMovable(False)
        bar.addWidget(QtWidgets.QLabel(" SECONDS ON SCREEN "))
        self.window_combo = QtWidgets.QComboBox()
        choices = sorted(set(WINDOW_CHOICES_S) | {int(round(self.window_s))})
        for v in choices:
            self.window_combo.addItem(f"{v} s", v)
        self.window_combo.setCurrentIndex(choices.index(int(round(self.window_s))))
        self.window_combo.setToolTip(
            "How many seconds of signal each band shows, for every board at once.\n"
            "Shorter shows the shape of each beat; longer, a whole breath hold.\n"
            "Going longer does not bring back what already scrolled off: the band fills\n"
            "in from the right. Remembered in fleet_ppg_viewer.ini.\n\n"
            "Source: Viewer.window_s -> BoardTrace.window_s (trim) and each plot's X range.")
        self.window_combo.currentIndexChanged.connect(
            lambda i: self.set_window_s(self.window_combo.itemData(i)))
        bar.addWidget(self.window_combo)

    def set_window_s(self, seconds):
        """Change the seconds on screen live: every trace trims to it, every band rescales."""
        self.window_s = float(seconds)
        for tr in self.traces.values():
            tr.window_s = self.window_s
        for plot, *_ in self.bands.values():
            plot.setXRange(-self.window_s, 0, padding=0)

    # ── the statistics panel ──────────────────────────────────────────────────────────────
    # ── settings ──────────────────────────────────────────────────────────────────────────
    def _restore_geometry(self):
        """The saved window, or on a first run a size taken from the screen.

        It used to be a flat 1100x800, which cut the last band off as soon as there were three
        boards — a fixed pixel height cannot know how many bands there will be, nor how tall
        the display is. 88 % of the available height is a starting point; after that the file
        remembers whatever the user chose, which is the only size that is actually right.
        """
        saved = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("geometry")
        if saved is not None and self.restoreGeometry(saved):
            return
        screen = QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            self.resize(1100, 800)
            return
        self.resize(min(1200, int(area.width() * 0.6)), int(area.height() * 0.88))
        self.move(area.left() + 40, area.top() + 20)

    def _save_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("window_s", self.window_s)

    # ── network ───────────────────────────────────────────────────────────────────────────
    def drain(self):
        """Single-threaded on purpose: no locks, no cross-thread Qt calls. All this does per
        datagram is decimate and append, so it cannot starve the GUI; at ~300 datagrams/s across
        three boards a 20 ms tick sees six of them."""
        now = time.monotonic()
        for _ in range(256):
            item = self.client.recv(0.0)
            if item is None:
                break
            ip, data = item
            if ip in self.aux or (ip not in self.traces and data[:4] in AUX_PREFIXES):
                # $VN1: a phone, not a board. No band for it (the hub's D1, one floor up).
                self.aux.add(ip)
                continue
            tr = self.traces.get(ip)
            if tr is None:
                tr = self.traces[ip] = BoardTrace(ip, now, self.window_s)
            tr.feed(data, now)
            gone = merge_by_mac(self.traces, tr)
            if gone is not None:
                self.drop_band(gone)

    # ── drawing ───────────────────────────────────────────────────────────────────────────
    def drop_band(self, ip):
        band = self.bands.pop(ip, None)
        self.band_rows.pop(ip, None)
        if band is not None:
            for item in band[:1] + band[2:]:   # plot, numbers, statistics; the curve is in the plot
                self.layout_widget.removeItem(item)

    def band_for(self, ip):
        if ip in self.bands:
            return self.bands[ip]
        if self._empty is not None:
            self.layout_widget.removeItem(self._empty)
            self._empty = None
        # A counter, not len(self.bands). Dropping a band (a board back on a new DHCP lease,
        # which happens daily here) leaves its row in the layout while shrinking the dict, so
        # len() then names a row that is still occupied and pyqtgraph would place the next
        # board's plot ON TOP of an existing one — GraphicsLayout.removeItem() clears its own
        # rows[r][c] bookkeeping but the grid row stays. An emptied row collapses to no height,
        # so never reusing one costs nothing visually.
        row = self._next_row
        self._next_row += 1
        plot = self.layout_widget.addPlot(row=row, col=0)
        # Explicit minima on every item in the row, so the grid's own minimum is something this
        # window is known to satisfy. Left to their size hints, a PlotItem asks for room enough
        # for its axes and title (350 px and up, and it grows with the title text) and the
        # statistics label for its whole 25-line document — and a QGraphicsGridLayout that
        # cannot meet its minimum does not shrink, it overflows past the edge of the view.
        plot.setMinimumWidth(MIN_PLOT_W)
        plot.setMinimumHeight(60)
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setXRange(-self.window_s, 0, padding=0)
        plot.setLabel("bottom", "seconds ago")
        curve = plot.plot(pen=pg.mkPen("#44AAFF", width=1))
        numbers = self.layout_widget.addLabel("", row=row, col=1, justify="right")
        numbers.item.setTextWidth(self._panel_w)
        numbers.setMaximumWidth(self._panel_w)
        numbers.setMinimumWidth(0)
        numbers.setMinimumHeight(0)
        stats = QtWidgets.QGraphicsProxyWidget()
        edit = make_stats_widget(self._stats_w)
        # Click a cell: a yellow box on it, click again: gone (2026-10-20, Alex). Per board.
        edit.viewport().installEventFilter(_StatsClick(self, ip, edit))
        edit.viewport().setCursor(QtCore.Qt.PointingHandCursor)
        edit.setToolTip("Click a cell to box it in yellow; click again to remove the box.")
        stats.setWidget(edit)
        stats.setMinimumSize(0, 0)
        # The band's height is the plot's business, not the panel's. Both of these are needed
        # and were measured: with the proxy's PREFERRED height left at the QTextEdit's own size
        # hint (which follows the document, 25 rows of it), three bands came out 497/497/445 --
        # the layout satisfies preferred heights in order and the last row takes the remainder.
        # At zero, every row has the same preferred height (the plot's) and the same stretch,
        # so they are equal: 480/480/480.
        stats.setPreferredHeight(0)
        stats.setMaximumWidth(self._stats_w)
        self.layout_widget.ci.addItem(stats, row=row, col=2)
        # Every band row stretches the same, so no band can grow because of what its panel
        # happens to contain. That loop is what made the bands different heights.
        self.layout_widget.ci.layout.setRowStretchFactor(row, 1)
        # Fixed columns, so the waveform's right edge does not move when a number gains a digit
        # and the statistics stay aligned down the window, band under band.
        self.layout_widget.ci.layout.setColumnFixedWidth(1, self._panel_w)
        self.layout_widget.ci.layout.setColumnFixedWidth(2, self._stats_w)
        self.layout_widget.ci.layout.setColumnStretchFactor(0, 1)
        self.bands[ip] = (plot, curve, numbers, stats)
        self.band_rows[ip] = row
        return self.bands[ip]

    def redraw(self):
        now = time.monotonic()
        for ip, tr in sorted(self.traces.items(), key=lambda kv: kv[1].first_seen):
            tr.trim(now)
            fresh = tr.maybe_snapshot(now)
            plot, curve, numbers, stats = self.band_for(ip)
            fresh = self._apply_saved_boxes(tr) or fresh
            plot.setTitle(tr.title(now), color=tr.state_colour(now), size="11pt")
            curve.setData([t - now for t in tr.t], list(tr.y))
            numbers.item.setHtml(tr.numbers_html(now))
            # Only when the second closed. Rewriting the document ten times a second would cost
            # ten times the work for the same table, and it would fight the user's scrollbar.
            if fresh or stats.widget().document().isEmpty():
                self._render_stats(stats, tr)

    def _render_stats(self, stats, tr):
        bar = stats.widget().verticalScrollBar()
        where = bar.value()
        stats.widget().setHtml(tr.stats_html(*self._stats_cols))
        bar.setValue(where)             # keep the reader where they scrolled to

    def toggle_stats_cell(self, ip, row, col):
        """Box or unbox one statistics cell of one board, and show it now rather than at the
        next 1 s rewrite. Row 0 is the header ('signal', mean, sd, min, max)."""
        tr, band = self.traces.get(ip), self.bands.get(ip)
        if tr is None or band is None or not 0 <= row <= len(STATS_ROWS):
            return
        tr.toggle_highlight("signal" if row == 0 else STATS_ROWS[row - 1][0], col)
        self._render_stats(band[3], tr)
        self._save_boxes(tr)

    # ── boxed cells, persisted per MAC ──
    _BOXES_GROUP = "stats_highlighted"

    @staticmethod
    def _mac_key(mac):
        return mac.replace(":", "").upper()          # an .ini key without separators

    @staticmethod
    def encode_boxes(cells):
        """{(label, col)} -> '<label>=<col>;…', sorted so the file does not churn."""
        return ";".join(f"{label}={col}" for label, col in sorted(cells))

    @staticmethod
    def decode_boxes(text):
        """Inverse of encode_boxes(). Labels no longer in STATS_ROWS (a renamed or removed row)
        and malformed tokens are dropped rather than boxing the wrong cell."""
        labels = {"signal"} | {row[0] for row in STATS_ROWS}
        cells = set()
        for token in (text or "").split(";"):
            label, sep, col = token.rpartition("=")
            if sep and label in labels and col.isdigit() and int(col) <= 4:
                cells.add((label, int(col)))
        return cells

    def _load_boxes(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.beginGroup(self._BOXES_GROUP)
        boxes = {key: self.decode_boxes(s.value(key, "", type=str)) for key in s.childKeys()}
        s.endGroup()
        return boxes

    def _apply_saved_boxes(self, tr):
        """Once per MAC, as soon as it is known: add that board's saved boxes to its trace (a box
        made before the $CFG arrived is kept too) and write the union back. -> True if the panel
        needs repainting."""
        if not tr.mac or tr.mac in self._boxes_applied:
            return False
        self._boxes_applied.add(tr.mac)
        saved = self._saved_boxes.get(self._mac_key(tr.mac), set())
        changed = not saved <= tr.highlighted
        tr.highlighted |= saved
        if tr.highlighted != saved:
            self._save_boxes(tr)
        return changed

    def _save_boxes(self, tr):
        """Write this board's boxes now (an empty set removes its key). Before the MAC is known
        there is nothing to file them under; _apply_saved_boxes() writes them when it is."""
        if not tr.mac:
            return
        key = self._mac_key(tr.mac)
        self._saved_boxes[key] = set(tr.highlighted)
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.beginGroup(self._BOXES_GROUP)
        if tr.highlighted:
            s.setValue(key, self.encode_boxes(tr.highlighted))
        else:
            s.remove(key)
        s.endGroup()

    def closeEvent(self, event):
        self.drain_timer.stop()
        self.redraw_timer.stop()
        self._save_settings()
        self.client.close()
        event.accept()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--window", type=float, default=None, metavar="S",
                    help=f"seconds of signal on screen (default {WINDOW_S:.0f}, or whatever was "
                         f"last used — it is remembered in fleet_ppg_viewer.ini)")
    ap.add_argument("--opengl", action="store_true",
                    help="turn pyqtgraph's OpenGL back on — the suspect in the lab's paint "
                         "crashes, off here by default so this viewer can test it")
    args = ap.parse_args()
    print(banner(__file__, "one live PPG band per board, read-only"))

    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    # The experiment, and it must run before any plot widget exists. pyqtgraph's own source
    # calls the QPicture replay in AxisItem.paint a place where "sometimes we get a segfault",
    # and the lab runs it with OpenGL on.
    pg.setConfigOptions(antialias=True, useOpenGL=args.opengl)
    print(f"   pyqtgraph useOpenGL={args.opengl}  (faulthandler -> "
          f"tools/fleet_ppg_viewer_faulthandler.log)")

    app = QtWidgets.QApplication(sys.argv)
    # Explicit on the command line wins; otherwise what the last run left in the .ini; otherwise
    # the default. Saved on close either way, so --window is also how you change it for good.
    window_s = args.window
    if window_s is None:
        window_s = float(QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
                         .value("window_s", WINDOW_S))
    win = Viewer(hub, window_s)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
