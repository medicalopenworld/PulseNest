"""One live PPG band per board — the window you open to see whether a probe has moved.

A read-only subscriber of the hub (spec §4.11), like tools/fleet_monitor.py and with the same
guarantee: it holds no control, so no $SET and no $MODE can leave it, by construction. Where the
fleet monitor shows numbers, this shows the waveform: one band per board, stacked, so a probe
that slips shows up as the shape going wrong at a glance — usually before any number moves.

    python tools/fleet_ppg_viewer.py [--hub IP[:PORT]] [--window 15] [--opengl]

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
from PyQt5 import QtCore, QtWidgets                           # noqa: E402

_fault_log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fleet_ppg_viewer_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

PPG_FIELD    = 9      # $M3/$M4: mode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP
PROBE_FIELD  = 22
DECIM        = 10     # 500 Hz -> 50 Hz on screen
LOST_S       = 2.0
WINDOW_S     = 15.0
REDRAW_MS    = 100
DRAIN_MS     = 20
ID_KEYS      = ("mac", "board")
PROBE_STATES = {"0": "DISCONNECTED", "1": "OT_HIGH", "2": "APPLIED",
                "3": "AMB_SAT", "4": "ONLY_LED_SAT"}
APPLIED      = "APPLIED"
GREEN, RED, GREY = "#44FF88", "#FF4444", "#888888"


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


class Viewer(QtWidgets.QMainWindow):
    """The window: one band per board, a drain timer and a redraw timer, nothing else."""

    def __init__(self, hub, window_s):
        super().__init__()
        self.setWindowTitle(f"{script_name(__file__)} — live PPG per board "
                            f"(hub {hub[0]}:{hub[1]}, read-only)")
        self.resize(1100, 800)
        self.window_s = window_s
        self.traces = {}
        self.bands = {}          # ip -> (PlotItem, PlotDataItem)
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
            self.layout_widget.removeItem(band[0])

    def band_for(self, ip):
        if ip in self.bands:
            return self.bands[ip]
        if self._empty is not None:
            self.layout_widget.removeItem(self._empty)
            self._empty = None
        plot = self.layout_widget.addPlot(row=len(self.bands), col=0)
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setXRange(-self.window_s, 0, padding=0)
        plot.setLabel("bottom", "seconds ago")
        curve = plot.plot(pen=pg.mkPen("#44AAFF", width=1))
        self.bands[ip] = (plot, curve)
        return self.bands[ip]

    def redraw(self):
        now = time.monotonic()
        for ip, tr in sorted(self.traces.items(), key=lambda kv: kv[1].first_seen):
            tr.trim(now)
            plot, curve = self.band_for(ip)
            plot.setTitle(tr.title(now), color=tr.state_colour(now), size="11pt")
            curve.setData([t - now for t in tr.t], list(tr.y))

    def closeEvent(self, event):
        self.drain_timer.stop()
        self.redraw_timer.stop()
        self.client.close()
        event.accept()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--window", type=float, default=WINDOW_S, metavar="S",
                    help="seconds of signal on screen (default %(default)s)")
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
    win = Viewer(hub, args.window)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
