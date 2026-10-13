"""The session launcher -- the one window a person opens to run a campaign without a terminal.

    pythonw tools/pulsenest_session.py [--configs docs/session_configs] [--hub IP[:PORT]]

Why it exists (Alex, 2026-10-13). A campaign is three recorder windows, one per cot, each started
from a terminal with `--config <cot>.toml`, plus the fleet monitor; docs/hospital_runbook.md asks
the person at the cot side to open a terminal in the repo and type the three lines. For anyone who
is not the author that terminal is the hard part, and the day-before checks (boards on the same
firmware, phones heard, disk, clock) are a list on paper. This window is that list, checked live,
with a START button beside each cot.

What it is NOT. Not part of pulsenest_lab.py: the lab is the controller (it can $SET a board) and
the program pyqtgraph has crashed; nothing a session depends on should depend on it (the lab's
SESSION button only starts this window, detached). Not a second recorder: every START runs the
exact command line of the runbook as a DETACHED process -- the flags with which the hub itself is
started -- so closing or crashing this window never touches a recording, and a cot stays one
process per baby. Not an editor: the TOML is edited by hand (Alex, 2026-10-14); EDIT opens it in
the system's editor, and the file stays the whole story, read by the recorder exactly as from the
command line (FULL substitution: nothing is merged in here).

Read-only by construction: a hub subscriber without control, like the fleet monitor, so no $SET
and no $MODE can leave it. No pyqtgraph in here -- plain widgets only, so the one window that is
open all day has nothing in it that has ever crashed.
"""
import argparse
import datetime
import faulthandler
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
from pulsenest.net import UDP_DATA_PORT, script_name                     # noqa: E402
from pulsenest.hub_client import (HubClient, console_python, windowed_python,  # noqa: E402
                                  spawn_detached as spawn)
from pulsenest.fleet_trace import GREEN, RED, GREY                        # noqa: E402
from tools.pulsenest_recorder import load_session_config, mac_compact, vn_device_id  # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                                # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_fault_log = open(os.path.join(_HERE, "pulsenest_session_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

SETTINGS_FILE   = os.path.join(_HERE, "pulsenest_session.ini")
DEFAULT_CONFIGS = os.path.join(_ROOT, "docs", "session_configs")
SESSIONS_DIR    = os.path.join(_ROOT, "captures", "sessions")   # the recorder's default --out
RECORDER_GUI    = os.path.join(_HERE, "pulsenest_recorder_gui.py")
FLEET_MONITOR   = os.path.join(_HERE, "fleet_monitor.py")
PPG_VIEWER      = os.path.join(_HERE, "fleet_ppg_viewer.py")
EXAMPLE_NAME    = "example.toml"      # the template: listed, never started by START ALL

MB_PER_MIN_PER_BOARD = 17     # measured (docs/hospital_runbook.md section 1): .pnraw + live CSV
DISK_FLOOR_GB        = 2      # the recorder refuses to start below this
LOST_S               = 5.0    # the recorder's own header says SILENT after 5 s without a datagram
DRAIN_MS, REFRESH_MS = 50, 1000
ID_KEYS = ("board", "mac", "fw", "lib", "build", "libsha", "elfsha")   # as tools/udp_fw_versions.py

BG, FG, FG_DIM, AMBER = "#121212", "#E0E0E0", "#9A9A9A", "#FFB000"
DARK_QSS = f"""
QWidget {{ background-color: {BG}; color: {FG}; }}
QGroupBox {{ color: {FG_DIM}; font-weight: bold; border: 1px solid #333333;
             border-radius: 4px; margin-top: 8px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; }}
QTableWidget {{ background-color: #181818; gridline-color: #2A2A2A; }}
QHeaderView::section {{ background-color: #222222; color: {FG_DIM}; border: none; padding: 3px; }}
QPushButton {{ background-color: #2A2A2A; border: 1px solid #3A3A3A; border-radius: 3px; padding: 4px 10px; }}
QPushButton:disabled {{ color: #666666; }}
"""


# ── what is on the air (no Qt: the test drives this directly) ──────────────────────────────

def parse_cfg(line):
    """A $CFG line -> {key: value} for ID_KEYS ('?' when absent), as udp_fw_versions.py reads it."""
    out = {}
    for k in ID_KEYS:
        m = re.search(rf"(?:^|,){k}=([^,*]*)", line)
        out[k] = m.group(1) if m else "?"
    return out


class BoardSeen:
    __slots__ = ("ip", "fields", "dgrams", "first_seen", "last_seen", "rate", "_rate_n", "_rate_t")

    def __init__(self, ip, now):
        self.ip, self.fields = ip, {}
        self.dgrams, self.first_seen, self.last_seen = 0, now, now
        self.rate, self._rate_n, self._rate_t = 0.0, 0, now

    @property
    def mac(self):
        return self.fields.get("mac", "?")

    def silent(self, now):
        return now - self.last_seen > LOST_S


class Fleet:
    """Boards and phones heard through the hub, and the checks the runbook asks for."""

    def __init__(self):
        self.boards = {}     # ip -> BoardSeen
        self.phones = {}     # device id -> (ip, last_seen)

    def feed(self, ip, data, now):
        if data.startswith(b"$VN1"):
            dev = vn_device_id(data)
            if dev:
                self.phones[dev] = (ip, now)
            return
        b = self.boards.get(ip)
        if b is None:
            b = self.boards[ip] = BoardSeen(ip, now)
        b.last_seen = now
        if data[:2] == b"$M":
            b.dgrams += 1
            b._rate_n += 1
        else:
            for line in data.decode("ascii", "replace").splitlines():
                if line.startswith("$CFG,"):
                    b.fields = parse_cfg(line)

    def tick(self, now):
        """Once a second: the datagram rate of every board over the last interval."""
        for b in self.boards.values():
            dt = now - b._rate_t
            if dt >= 1.0:
                b.rate = b._rate_n / dt
                b._rate_n, b._rate_t = 0, now

    def by_mac(self):
        """Boards that have said who they are, merged by MAC (a new DHCP lease is the same
        hardware; the freshest address wins), as the recorder binds them."""
        out = {}
        for b in self.boards.values():
            if b.mac != "?" and (b.mac not in out or b.last_seen > out[b.mac].last_seen):
                out[b.mac] = b
        return out

    def firmware_agreement(self):
        """-> (ok, text): do all identified boards run the same image (fw + elfsha)?"""
        boards = self.by_mac()
        if not boards:
            return False, "no board identified yet"
        images = {(b.fields.get("fw"), b.fields.get("elfsha")) for b in boards.values()}
        if len(images) == 1:
            fw, sha = next(iter(images))
            return True, f"{len(boards)} board(s), same firmware: fw {fw}, elfsha {sha}"
        return False, ("boards run DIFFERENT images: "
                       + ", ".join(f"{m[-5:]}=fw {b.fields.get('fw')}/{b.fields.get('elfsha')}"
                                   for m, b in sorted(boards.items())))

    def match_board(self, suffix):
        """A cot's `board` (MAC suffix of any length) against what is on the air.
        -> ("ok", mac) | ("none", "") | ("ambiguous", "mac1, mac2") | ("blank", "")."""
        suffix = mac_compact(suffix or "")
        if not suffix:
            return "blank", ""
        hits = sorted(m for m in self.by_mac() if mac_compact(m).endswith(suffix))
        if len(hits) == 1:
            return "ok", hits[0]
        if not hits:
            return "none", ""
        return "ambiguous", ", ".join(hits)

    def phone_heard(self, dev):
        return bool(dev) and dev in self.phones


# ── the cots: one TOML each ────────────────────────────────────────────────────────────────

class Cot:
    __slots__ = ("path", "name", "cfg", "error", "proc", "started_at")

    def __init__(self, path):
        self.path, self.name = path, os.path.basename(path)
        self.cfg, self.error, self.proc, self.started_at = None, "", None, None
        try:
            self.cfg = load_session_config(path)
        except Exception as exc:            # a file that cannot be read must show WHY, not vanish
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def is_example(self):
        return self.name == EXAMPLE_NAME

    def field(self, key):
        return (self.cfg or {}).get(key, "") or ""

    def status(self):
        """-> (text, colour) of the process this window started for the cot, if any."""
        if self.proc is None:
            return "", FG_DIM
        rc = self.proc.poll()
        if rc is None:
            return f"running (pid {self.proc.pid})", GREEN
        return (f"exited rc={rc}", RED if rc else FG_DIM)

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None


def cots_in(directory):
    """Every .toml in the folder, example last, each parsed once (errors kept, not raised)."""
    try:
        names = sorted(n for n in os.listdir(directory) if n.lower().endswith(".toml"))
    except OSError:
        return []
    names.sort(key=lambda n: (n == EXAMPLE_NAME, n))
    return [Cot(os.path.join(directory, n)) for n in names]


# ── starting programs ──────────────────────────────────────────────────────────────────────

# spawn() is hub_client.spawn_detached: the one rule for an independent process (own process
# group, detached, no inherited stdio; a console of its own for a console program), shared with
# the hub's own start and the lab's SESSION button. The test replaces it with a fake.

def hub_args(hub):
    """--hub only when it is not the default, so a cot's command line is the runbook's."""
    return [] if hub == ("127.0.0.1", UDP_DATA_PORT) else ["--hub", f"{hub[0]}:{hub[1]}"]


def cot_command(cot, hub):
    return [windowed_python(), RECORDER_GUI, "--config", cot.path, *hub_args(hub)]


def monitor_command(hub):
    return [console_python(), FLEET_MONITOR, *hub_args(hub)]


def viewer_command(hub):
    return [windowed_python(), PPG_VIEWER, *hub_args(hub)]


def launcher_command(hub):
    """This window itself, for the lab's SESSION button (started with spawn(), like everything)."""
    return [windowed_python(), os.path.abspath(__file__), *hub_args(hub)]


def disk_line(n_boards):
    """Free space where sessions are written, as hours of recording for `n_boards` boards."""
    where = SESSIONS_DIR if os.path.isdir(SESSIONS_DIR) else _ROOT
    free_gb = shutil.disk_usage(where).free / 1e9
    hours = free_gb * 1000 / (MB_PER_MIN_PER_BOARD * 60 * max(1, n_boards))
    colour = RED if free_gb < DISK_FLOOR_GB else AMBER if hours < 10 else GREEN
    return (f"{free_gb:.1f} GB free on {os.path.splitdrive(where)[0] or where}: about {hours:.0f} h "
            f"for {max(1, n_boards)} board(s) at {MB_PER_MIN_PER_BOARD} MB/min each"
            + (f"  -- below the {DISK_FLOOR_GB} GB floor, the recorder will refuse to start"
               if free_gb < DISK_FLOOR_GB else ""), colour)


# ── the window ─────────────────────────────────────────────────────────────────────────────

def _item(text, colour=None, mono=False):
    it = QtWidgets.QTableWidgetItem(text)
    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
    if colour:
        it.setForeground(QtGui.QBrush(QtGui.QColor(colour)))
    if mono:
        f = QtGui.QFont("monospace")
        f.setStyleHint(QtGui.QFont.TypeWriter)
        it.setFont(f)
    return it


class Launcher(QtWidgets.QMainWindow):
    BOARD_COLS = ("IP", "MAC", "fw", "lib", "build", "elfsha", "dgrams/s", "seen")
    COT_COLS = ("file", "subject", "board", "on the air", "phone", "status", "", "")

    def __init__(self, configs_dir, hub, client):
        super().__init__()
        self.configs_dir, self.hub, self.client = configs_dir, hub, client
        self.fleet = Fleet()
        self.cots = []
        self.extra = {}          # "monitor"/"viewer" -> Popen
        self.setWindowTitle(f"{script_name(__file__)}  —  session launcher  —  hub {hub[0]}:{hub[1]}")
        self.setStyleSheet(DARK_QSS)
        self._build()
        self.reload_configs()
        saved = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("geometry")
        if saved is None or not self.restoreGeometry(saved):
            self.resize(1100, 700)
        self._drain_timer = QtCore.QTimer(self, interval=DRAIN_MS, timeout=self.drain)
        self._refresh_timer = QtCore.QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        self._drain_timer.start()
        self._refresh_timer.start()

    # -- layout --
    def _build(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        top = QtWidgets.QHBoxLayout()
        self.clock = QtWidgets.QLabel("--:--:--")
        f = QtGui.QFont()
        f.setPointSize(28)
        f.setBold(True)
        self.clock.setFont(f)
        self.clock.setToolTip("The laptop's clock. Every reading, photo and datagram is placed on "
                              "this timeline -- synchronise it before the session (Settings -> Time -> "
                              "Sync now). The CLOCK ANCHOR photo in each recorder window is taken of "
                              "this clock in large digits.")
        self.disk = QtWidgets.QLabel("")
        self.disk.setWordWrap(True)
        top.addWidget(self.clock)
        top.addSpacing(20)
        top.addWidget(self.disk, 1)
        v.addLayout(top)

        gb = QtWidgets.QGroupBox("BOARDS ON THE AIR  (read-only: this window cannot change a board)")
        gl = QtWidgets.QVBoxLayout(gb)
        self.boards = QtWidgets.QTableWidget(0, len(self.BOARD_COLS))
        self.boards.setHorizontalHeaderLabels(self.BOARD_COLS)
        self.boards.verticalHeader().setVisible(False)
        self.boards.horizontalHeader().setStretchLastSection(True)
        self.boards.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.boards.setMaximumHeight(150)
        gl.addWidget(self.boards)
        self.firmware = QtWidgets.QLabel("")
        self.firmware.setToolTip("docs/hospital_runbook.md section 1: all boards should report the "
                                 "same fw, build and elfsha. elfsha is the fingerprint of the image "
                                 "itself; two boards with the same elfsha run the same binary.")
        gl.addWidget(self.firmware)
        self.phones = QtWidgets.QLabel("")
        self.phones.setToolTip("VideoNest phones heard through the hub, by the device id each one "
                               "puts in its $VN1 frames. A phone that is not here is not sending: app "
                               "closed or backgrounded, phone off the WiFi, wrong destination address.")
        gl.addWidget(self.phones)
        v.addWidget(gb)

        gb2 = QtWidgets.QGroupBox(f"COTS  (one .toml per cot in {self.configs_dir})")
        g2 = QtWidgets.QVBoxLayout(gb2)
        self.table = QtWidgets.QTableWidget(0, len(self.COT_COLS))
        self.table.setHorizontalHeaderLabels(self.COT_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        g2.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        self.btn_all = QtWidgets.QPushButton("START ALL COTS")
        self.btn_all.setToolTip("One recorder window per .toml (the example is skipped). Each is "
                                "its own process; this window can be closed afterwards.")
        self.btn_all.clicked.connect(self.start_all)
        self.btn_monitor = QtWidgets.QPushButton("FLEET MONITOR")
        self.btn_monitor.setToolTip("tools/fleet_monitor.py in a console of its own: one line per "
                                    "board, refreshed every second. Read-only.")
        self.btn_monitor.clicked.connect(lambda: self.start_extra("monitor"))
        self.btn_viewer = QtWidgets.QPushButton("PPG VIEWER")
        self.btn_viewer.setToolTip("tools/fleet_ppg_viewer.py: one live PPG band per board, to see "
                                   "whether a probe has moved. Read-only. Optional -- the recorder "
                                   "window shows its own waveform.")
        self.btn_viewer.clicked.connect(lambda: self.start_extra("viewer"))
        self.btn_folder = QtWidgets.QPushButton("OPEN CONFIGS FOLDER")
        self.btn_folder.clicked.connect(lambda: open_in_system(self.configs_dir))
        self.btn_reload = QtWidgets.QPushButton("RELOAD")
        self.btn_reload.setToolTip("Re-read the .toml files (after editing one by hand).")
        self.btn_reload.clicked.connect(self.reload_configs)
        for b in (self.btn_all, self.btn_monitor, self.btn_viewer, self.btn_folder, self.btn_reload):
            row.addWidget(b)
        row.addStretch(1)
        self.extra_status = QtWidgets.QLabel("")
        row.addWidget(self.extra_status)
        g2.addLayout(row)
        v.addWidget(gb2, 1)

    # -- data in --
    def drain(self):
        now = time.monotonic()
        for _ in range(200):
            item = self.client.recv(0.0)
            if item is None:
                break
            self.fleet.feed(item[0], item[1], now)

    def reload_configs(self):
        running = {c.path: c for c in self.cots if c.proc is not None}
        self.cots = cots_in(self.configs_dir)
        for c in self.cots:                      # a reload must not forget a process we started
            if c.path in running:
                c.proc, c.started_at = running[c.path].proc, running[c.path].started_at
        self.table.setRowCount(len(self.cots))
        for r, cot in enumerate(self.cots):
            btn = QtWidgets.QPushButton("START")
            btn.clicked.connect(lambda _=False, c=cot: self.start_cot(c))
            self.table.setCellWidget(r, 6, btn)
            edit = QtWidgets.QPushButton("EDIT")
            edit.setToolTip("Opens the file in the system's editor. Edit, save, then RELOAD here; a "
                            "cot already running keeps the values it was started with.")
            edit.clicked.connect(lambda _=False, c=cot: open_in_system(c.path))
            self.table.setCellWidget(r, 7, edit)
        self.refresh()

    # -- data out --
    def refresh(self):
        now = time.monotonic()
        self.fleet.tick(now)
        self.clock.setText(datetime.datetime.now().strftime("%H:%M:%S"))
        # boards that will record: the ones on the air; before any is heard, the cots prepared
        n = len(self.fleet.by_mac()) or len([c for c in self.cots if not c.is_example]) or 1
        text, colour = disk_line(n)
        self.disk.setText(text)
        self.disk.setStyleSheet(f"color: {colour};")

        boards = sorted(self.fleet.boards.values(), key=lambda b: (b.mac, b.ip))
        self.boards.setRowCount(len(boards))
        for r, b in enumerate(boards):
            silent = b.silent(now)
            col = GREY if silent else None
            seen = "SILENT %.0f s" % (now - b.last_seen) if silent else "live"
            vals = (b.ip, b.mac, b.fields.get("fw", "?"), b.fields.get("lib", "?"),
                    b.fields.get("build", "?"), b.fields.get("elfsha", "?"),
                    "%.0f" % b.rate, seen)
            for c, val in enumerate(vals):
                self.boards.setItem(r, c, _item(val, RED if (c == 7 and silent) else col, mono=c in (1, 5)))
        ok, text = self.fleet.firmware_agreement()
        self.firmware.setText(("OK  " if ok else "CHECK  ") + text)
        self.firmware.setStyleSheet(f"color: {GREEN if ok else AMBER};")
        if self.fleet.phones:
            parts = []
            for dev, (ip, last) in sorted(self.fleet.phones.items()):
                age = now - last
                parts.append(f"{dev} ({ip}{', silent %.0f s' % age if age > LOST_S else ''})")
            self.phones.setText("Phones heard: " + ", ".join(parts))
            self.phones.setStyleSheet(f"color: {FG};")
        else:
            self.phones.setText("Phones heard: none yet (VideoNest not sending, or no phone in this campaign)")
            self.phones.setStyleSheet(f"color: {FG_DIM};")

        for r, cot in enumerate(self.cots):
            self._cot_row(r, cot)
        self.btn_all.setEnabled(any(not c.is_example and not c.running and c.cfg for c in self.cots))
        parts = []
        for key, proc in self.extra.items():
            rc = proc.poll()
            parts.append(f"{key}: " + ("running" if rc is None else f"exited rc={rc}"))
        self.extra_status.setText("   ".join(parts))
        self.btn_monitor.setEnabled(not self._extra_running("monitor"))
        self.btn_viewer.setEnabled(not self._extra_running("viewer"))

    def _cot_row(self, r, cot):
        self.table.setItem(r, 0, _item(cot.name, FG_DIM if cot.is_example else None))
        if cot.error:
            self.table.setItem(r, 1, _item(cot.error, RED))
            for c in (2, 3, 4):
                self.table.setItem(r, c, _item(""))
        else:
            self.table.setItem(r, 1, _item(cot.field("subject") or "(chosen in the window)",
                                           None if cot.field("subject") else FG_DIM))
            self.table.setItem(r, 2, _item(cot.field("board"), mono=True))
            kind, detail = self.fleet.match_board(cot.field("board"))
            text, colour = {
                "ok":        (detail, GREEN),
                "none":      ("not on the air", AMBER),
                "ambiguous": (f"AMBIGUOUS: {detail}", RED),
                "blank":     ("(no board in the file)", FG_DIM),
            }[kind]
            self.table.setItem(r, 3, _item(text, colour, mono=kind == "ok"))
            dev = cot.field("ref_videonest")
            if not dev:
                self.table.setItem(r, 4, _item("(none declared)", FG_DIM))
            elif self.fleet.phone_heard(dev):
                self.table.setItem(r, 4, _item(f"{dev} heard", GREEN))
            else:
                self.table.setItem(r, 4, _item(f"{dev} NOT heard", AMBER))
        text, colour = cot.status()
        self.table.setItem(r, 5, _item(text, colour))
        btn = self.table.cellWidget(r, 6)
        if btn is not None:
            btn.setEnabled(bool(cot.cfg) and not cot.running)
            btn.setText("RUNNING" if cot.running else "START")

    def _extra_running(self, key):
        p = self.extra.get(key)
        return p is not None and p.poll() is None

    # -- actions --
    def start_cot(self, cot):
        if cot.running or not cot.cfg:
            return
        cot.proc = spawn(cot_command(cot, self.hub))
        cot.started_at = time.time()
        self.refresh()

    def start_all(self):
        for cot in self.cots:
            if not cot.is_example and cot.cfg and not cot.running:
                self.start_cot(cot)

    def start_extra(self, key):
        if self._extra_running(key):
            return
        if key == "monitor":
            self.extra[key] = spawn(monitor_command(self.hub), console=True)
        else:
            self.extra[key] = spawn(viewer_command(self.hub))
        self.refresh()

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("geometry", self.saveGeometry())
        s.sync()
        self._drain_timer.stop()
        self._refresh_timer.stop()
        self.client.close()
        event.accept()        # the processes started here are detached: they keep running


def open_in_system(path):
    """The system's own editor / file browser; never ours."""
    if os.name == "nt":
        os.startfile(path)          # noqa: S606  (Windows: the registered application)
    else:
        subprocess.Popen(["xdg-open", path])


def parse_hub(text):
    host, _, port = text.partition(":")
    return (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PulseNest session launcher: the cots, what is on the air, "
                                             "and a START button per cot. Read-only.")
    ap.add_argument("--configs", default=DEFAULT_CONFIGS, metavar="DIR",
                    help="folder with one .toml per cot (default docs/session_configs)")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    args = ap.parse_args(argv)
    hub = parse_hub(args.hub)
    app = QtWidgets.QApplication(sys.argv)
    client = HubClient(script_name(__file__), hub=hub, control=False)
    client.connect()          # starts the hub if none answers; reconnects by itself otherwise
    w = Launcher(os.path.abspath(args.configs), hub, client)
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
