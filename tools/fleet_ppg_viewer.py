"""One live PPG band per board — the window you open to see whether a probe has moved.

A read-only subscriber of the hub (spec §4.11), like tools/fleet_monitor.py and with the same
guarantee: it holds no control, so no $SET and no $MODE can leave it, by construction. Where the
fleet monitor shows numbers, this shows the waveform: one band per board, stacked, so a probe
that slips shows up as the shape going wrong at a glance — usually before any number moves.

    python tools/fleet_ppg_viewer.py [--hub IP[:PORT]] [--window 15] [--opengl]

The window size and the seconds on screen are remembered in `tools/fleet_ppg_viewer.ini`
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
  Philips): SpO2 in cyan, pulse rate in green, each as digits over a small unit line that also
  names the measurement (`% SpO2`, `bpm HR3`) — two lines, not three, because with a separate
  label above them the panel ran out of vertical room and pushed the rows out of line. Three
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
"""
import argparse
import faulthandler
import os
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, banner, script_name  # noqa: E402
from pulsenest_hub_client import HubClient                    # noqa: E402
import pyqtgraph as pg                                        # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                    # noqa: E402

_fault_log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fleet_ppg_viewer_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

PPG_FIELD    = 9      # $M3/$M4: mode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP
SPO2_FIELD, SPO2_SQI_FIELD = 10, 11
HR3_FIELD,  HR3_SQI_FIELD  = 18, 19
PROBE_FIELD  = 22
DECIM        = 10     # 500 Hz -> 50 Hz on screen
LOST_S       = 2.0
WINDOW_S     = 15.0
REDRAW_MS    = 100
DRAIN_MS     = 20
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fleet_ppg_viewer.ini")
ID_KEYS      = ("mac", "board")
PROBE_STATES = {"0": "DISCONNECTED", "1": "OT_HIGH", "2": "APPLIED",
                "3": "AMB_SAT", "4": "ONLY_LED_SAT"}
APPLIED      = "APPLIED"
GREEN, RED, GREY = "#44FF88", "#FF4444", "#888888"
# Bedside-monitor palette: SpO2 cyan, pulse rate green. That pairing is the de facto convention
# of the multiparameter monitors (Philips IntelliVue, GE CARESCAPE) rather than anything
# standardised — no standard assigns colours to numerics. What IS standardised is the alarm
# palette (IEC 60601-1-8: red high priority, yellow medium, cyan low/informational), which is
# the reason a normal reading is never painted red on these machines, and why the dashes below
# are grey rather than red. In the lab green means "firmware" (project_color_convention), but
# every number in this window comes from the firmware, so the colour disambiguates nothing here.
SPO2_COLOUR  = "#00D0FF"
HR_COLOUR    = "#00FF6A"
DASH_COLOUR  = "#666666"
SQI_GOOD     = 0.9    # same threshold SIGNAL STATS uses to call a reading trustworthy
DIM_FACTOR   = 0.30   # how far a below-threshold reading fades. One knob: it was 0.5-ish by
                      # hand-picked hex and did not read as clearly "do not trust this".


def dim(colour, factor=DIM_FACTOR):
    """-> the same hue at `factor` of its brightness. Derived rather than a second hand-picked
    hex, so the two colours cannot drift apart and there is one number to turn."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))


SPO2_DIM = dim(SPO2_COLOUR)
HR_DIM = dim(HR_COLOUR)
BIG_PT       = 44     # the digits
SMALL_PT     = 12     # the unit line under them
WIDEST_VALUE = "000"      # three digits: SpO2 reaches 100, and the rate can pass it too
WIDEST_UNIT  = "bpm HR3"


class BoardTrace:
    """The data behind one band: a time-windowed ring of PPG samples, plus who the board is.

    No Qt in here on purpose — this is what the offscreen test drives directly.
    """

    def __init__(self, ip, now, window_s=WINDOW_S):
        self.ip = ip
        self.ident = {}
        self.first_seen = self.last_seen = now
        self.window_s = window_s
        self.t = deque()          # arrival time of each kept sample (monotonic seconds)
        self.y = deque()
        self.probe = "?"
        self.spo2 = self.spo2_sqi = self.hr3 = self.hr3_sqi = None
        self.samples = 0          # samples seen, before decimation
        self._decim = 0
        self.moved_from = None    # previous IP of the same MAC

    @property
    def mac(self):
        return self.ident.get("mac")

    def label(self):
        who = f"{self.mac[-8:]} {self.ident.get('board', '?')}" if self.mac else self.ip
        return who

    def feed(self, data, now):
        """One forwarded datagram. Never raises: a malformed line is skipped, not fatal."""
        self.last_seen = now
        for raw in data.split(b"\n"):
            line = raw.rstrip(b"\r")
            if not line:
                continue
            if line[:1] == b"$" and line[1:3] in (b"M1", b"M2", b"M3", b"M4") and line[3:4] == b",":
                self._data_frame(line, now)
            elif line.startswith(b"$CFG,"):
                for part in line.split(b","):
                    k, sep, v = part.partition(b"=")
                    if sep and k.decode("ascii", "replace") in ID_KEYS:
                        self.ident[k.decode("ascii", "replace")] = \
                            v.split(b"*")[0].decode("ascii", "replace")

    def _data_frame(self, line, now):
        p = line[1:].split(b"*")[0].split(b",")
        self.samples += 1
        if len(p) > PROBE_FIELD:
            self.probe = PROBE_STATES.get(p[PROBE_FIELD].decode("ascii", "replace"), "?")
        def number(idx):
            try:
                return float(p[idx])
            except (IndexError, ValueError):
                return None
        self.spo2, self.spo2_sqi = number(SPO2_FIELD), number(SPO2_SQI_FIELD)
        self.hr3, self.hr3_sqi = number(HR3_FIELD), number(HR3_SQI_FIELD)
        self._decim += 1
        if self._decim < DECIM:
            return
        self._decim = 0
        try:
            value = float(p[PPG_FIELD])
        except (IndexError, ValueError):
            return            # $M1/$M2 carry PPG elsewhere or the field is junk: skip the sample
        self.t.append(now)
        self.y.append(value)

    def trim(self, now):
        """Drop what fell out of the window. By time, not by a fixed length: a board streaming
        at a different rate must still show the same number of SECONDS as its neighbours."""
        limit = now - self.window_s
        while self.t and self.t[0] < limit:
            self.t.popleft()
            self.y.popleft()

    def silent_for(self, now):
        return now - self.last_seen

    def is_lost(self, now):
        return self.silent_for(now) > LOST_S

    def state_colour(self, now):
        if self.is_lost(now):
            return RED
        if self.probe == APPLIED:
            return GREEN
        return RED if self.probe != "?" else GREY

    def numbers_html(self, now):
        """The panel beside the band. Built here, not in the widget, so the offline test can
        read exactly what a person would see without constructing a window."""
        def block(value, sqi, unit, bright, dim):
            invalid = value is None or value <= 0 or self.is_lost(now)
            if invalid:
                text, colour = "--", DASH_COLOUR
            else:
                text = f"{value:.0f}"
                colour = bright if (sqi is not None and sqi > SQI_GOOD) else dim
            # Two lines, digits then unit. There used to be a third, a small label above, and
            # between the three of them and 44pt digits the panel ran out of vertical room and
            # pushed the rows out of line. The unit line carries the identity instead — "% SpO2"
            # rather than "%" — so nothing is lost by dropping the label. (The unit was written
            # inline, meant to sit beside the digits; at this size it never fitted the panel
            # width and wrapped. It reads better underneath, so now it is deliberate.)
            # <nobr> on both lines: at 100 the digits used to exceed the panel width, wrap,
            # and add a third line that pushed every row out of alignment. The height of this
            # panel must not depend on the value it is showing.
            return (f"<div style='margin-bottom:2px;'>"
                    f"<div style='font-size:{BIG_PT}pt; font-weight:bold; color:{colour}; "
                    f"line-height:100%;'><nobr>{text}</nobr></div>"
                    f"<div style='font-size:{SMALL_PT}pt; color:{colour};'>"
                    f"<nobr>{unit}</nobr></div></div>")

        return ("<div style='text-align:right;'>"
                + block(self.spo2, self.spo2_sqi, "% SpO2", SPO2_COLOUR, SPO2_DIM)
                + block(self.hr3, self.hr3_sqi, "bpm HR3", HR_COLOUR, HR_DIM)
                + "</div>")

    def title(self, now):
        if self.is_lost(now):
            return f"{self.label()}  —  LOST {self.silent_for(now):.0f} s"
        return f"{self.label()}  —  {self.probe}"


def merge_by_mac(traces, trace):
    """A board back on a new DHCP lease is the same hardware: one band, not two. Same rule as
    fleet_monitor.py. Returns the IP whose band disappeared, or None."""
    mac = trace.mac
    if not mac:
        return None
    for ip, other in list(traces.items()):
        if other is not trace and other.mac == mac:
            newer, older = ((trace, other) if trace.last_seen >= other.last_seen
                            else (other, trace))
            newer.samples += older.samples
            newer.moved_from = older.ip
            del traces[older.ip]
            return older.ip
    return None


def panel_width():
    """How wide the numbers panel has to be for its worst case, from the real font metrics.

    It was a flat 190 px, which fitted two digits and wrapped at three — SpO2 reaching 100 was
    enough to add a line and shift every row. Measuring it here also makes it right on a display
    with a scaling factor, where a pixel guess made against one monitor is wrong on the next.
    """
    big = QtGui.QFont()
    big.setPointSize(BIG_PT)
    big.setBold(True)
    small = QtGui.QFont()
    small.setPointSize(SMALL_PT)
    return max(QtGui.QFontMetrics(big).horizontalAdvance(WIDEST_VALUE),
               QtGui.QFontMetrics(small).horizontalAdvance(WIDEST_UNIT)) + 24


class Viewer(QtWidgets.QMainWindow):
    """The window: one band per board, a drain timer and a redraw timer, nothing else."""

    def __init__(self, hub, window_s):
        super().__init__()
        self.setWindowTitle(f"{script_name(__file__)} — live PPG per board "
                            f"(hub {hub[0]}:{hub[1]}, read-only)")
        self._restore_geometry()
        self.window_s = window_s
        self.traces = {}
        self.bands = {}          # ip -> (PlotItem, PlotDataItem, LabelItem)
        self._next_row = 0       # monotonic: see band_for()
        self._panel_w = panel_width()
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=print)
        self.client.connect()

        self.layout_widget = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self.layout_widget)
        self._empty = self.layout_widget.addLabel("waiting for a board…", color="#888888",
                                                  size="14pt")

        self.drain_timer = QtCore.QTimer(self)
        self.drain_timer.timeout.connect(self.drain)
        self.drain_timer.start(DRAIN_MS)
        self.redraw_timer = QtCore.QTimer(self)
        self.redraw_timer.timeout.connect(self.redraw)
        self.redraw_timer.start(REDRAW_MS)

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
        if band is not None:
            for item in band[:1] + band[2:]:   # the plot and the numbers; the curve lives in it
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
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setXRange(-self.window_s, 0, padding=0)
        plot.setLabel("bottom", "seconds ago")
        curve = plot.plot(pen=pg.mkPen("#44AAFF", width=1))
        numbers = self.layout_widget.addLabel("", row=row, col=1, justify="right")
        numbers.item.setTextWidth(self._panel_w)
        # Fixed column, so the waveform's right edge does not move when a number gains a digit.
        self.layout_widget.ci.layout.setColumnFixedWidth(1, self._panel_w)
        self.layout_widget.ci.layout.setColumnStretchFactor(0, 1)
        self.bands[ip] = (plot, curve, numbers)
        return self.bands[ip]

    def redraw(self):
        now = time.monotonic()
        for ip, tr in sorted(self.traces.items(), key=lambda kv: kv[1].first_seen):
            tr.trim(now)
            plot, curve, numbers = self.band_for(ip)
            plot.setTitle(tr.title(now), color=tr.state_colour(now), size="11pt")
            curve.setData([t - now for t in tr.t], list(tr.y))
            numbers.item.setHtml(tr.numbers_html(now))

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
