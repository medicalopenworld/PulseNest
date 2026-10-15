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
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
from pulsenest.net import UDP_DATA_PORT, script_name, open_in_system     # noqa: E402
from pulsenest.hub_client import (HubClient, console_python, windowed_python,  # noqa: E402
                                  spawn_detached as spawn)
from pulsenest.fleet_trace import GREEN, RED, GREY, LINK                  # noqa: E402
from tools.pulsenest_recorder import (load_session_config, mac_compact,   # noqa: E402
                                      vn_device_id, vn_offset_ms)
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
LAB_SCRIPT      = os.path.join(_ROOT, "pulsenest_lab.py")
EXAMPLE_NAME    = "example.toml"      # the template: listed, not for starting

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


PHONE_STALE_S = 60.0    # a phone not heard for this long is a failed reference, not a late one


def seen_text(age):
    """'live' / 'SILENT 12 s' and the colour, for a source whose last datagram is `age` s old."""
    if age <= LOST_S:
        return "live", GREEN
    return "SILENT %.0f s" % age, (RED if age > PHONE_STALE_S else AMBER)


class Seen:
    """One source heard through the hub: a board (by IP) or a phone (by device id)."""
    __slots__ = ("ip", "fields", "dgrams", "first_seen", "last_seen", "rate", "_rate_n", "_rate_t",
                 "last_frame", "last_offset_ms")

    def __init__(self, ip, now):
        self.ip, self.fields = ip, {}
        self.dgrams, self.first_seen, self.last_seen = 0, now, now
        self.rate, self._rate_n, self._rate_t = 0.0, 0, now
        self.last_frame, self.last_offset_ms = "", None     # phones: the raw $VN1 and its offset

    @property
    def mac(self):
        return self.fields.get("mac", "?")

    def heard(self, now):
        self.last_seen = now
        self.dgrams += 1
        self._rate_n += 1

    def age(self, now):
        return now - self.last_seen

    def silent(self, now):
        return self.age(now) > LOST_S

    def tick(self, now):
        dt = now - self._rate_t
        if dt >= 1.0:
            self.rate = self._rate_n / dt
            self._rate_n, self._rate_t = 0, now


BoardSeen = Seen      # the test and the docstrings call a board's entry by this name


class Fleet:
    """Boards and phones heard through the hub, and the checks the runbook asks for."""

    def __init__(self):
        self.boards = {}     # ip -> Seen
        self.phones = {}     # device id -> Seen (ip = the phone's address)

    def feed(self, ip, data, now, epoch_ms=None):
        """One datagram from the hub. `epoch_ms` is the wall-clock arrival (default: now), the
        reference for a phone frame's offset, as in the recorder."""
        if data.startswith(b"$VN1"):
            dev = vn_device_id(data)
            if dev:
                p = self.phones.get(dev)
                if p is None:
                    p = self.phones[dev] = Seen(ip, now)
                p.ip = ip
                p.heard(now)
                p.last_frame = data.split(b"\n", 1)[0].decode("ascii", "replace").strip()
                p.last_offset_ms = vn_offset_ms(data, time.time() * 1000 if epoch_ms is None else epoch_ms)
            return
        b = self.boards.get(ip)
        if b is None:
            b = self.boards[ip] = Seen(ip, now)
        if data[:2] == b"$M":
            b.heard(now)
        else:
            b.last_seen = now
            for line in data.decode("ascii", "replace").splitlines():
                if line.startswith("$CFG,"):
                    b.fields = parse_cfg(line)

    def tick(self, now):
        """Once a second: the datagram rate of every source over the last interval."""
        for s in list(self.boards.values()) + list(self.phones.values()):
            s.tick(now)

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
        -> ("ok", mac) | ("none", "") | ("ambiguous", "mac1, mac2") | ("blank", "").
        An "ok" match may be a board that has gone SILENT: the caller asks board_of(mac)."""
        suffix = mac_compact(suffix or "")
        if not suffix:
            return "blank", ""
        hits = sorted(m for m in self.by_mac() if mac_compact(m).endswith(suffix))
        if len(hits) == 1:
            return "ok", hits[0]
        if not hits:
            return "none", ""
        return "ambiguous", ", ".join(hits)

    def board_of(self, mac):
        return self.by_mac().get(mac)

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
        return ended_text(rc)

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None


def ended_text(rc):
    """What a process that is no longer running tells the operator, from its return code: the
    recorder window exits 0 when its session was closed, 1 when its start dialog was cancelled,
    2 when it refused to start (its own message said why); anything else is a crash (Alex,
    2026-10-15: "exited rc=..." meant nothing at the cot side)."""
    return {0: ("ended", FG_DIM), 1: ("cancelled", FG_DIM),
            2: ("refused to start (see its message)", RED)}.get(rc, (f"crashed (code {rc})", RED))


def cots_in(directory):
    """Every .toml in the folder, example last, each parsed once (errors kept, not raised)."""
    try:
        names = sorted(n for n in os.listdir(directory) if n.lower().endswith(".toml"))
    except OSError:
        return []
    names.sort(key=lambda n: (n == EXAMPLE_NAME, n))
    return [Cot(os.path.join(directory, n)) for n in names]


def configs_signature(directory):
    """What the folder looks like: (name, mtime, size) per .toml. The window re-reads the files
    when this changes -- polled once a second rather than QFileSystemWatcher, which misses an
    editor that saves by writing a new file and renaming it over the old one."""
    try:
        out = []
        for n in sorted(os.listdir(directory)):
            if n.lower().endswith(".toml"):
                st = os.stat(os.path.join(directory, n))
                out.append((n, st.st_mtime_ns, st.st_size))
        return tuple(out)
    except OSError:
        return ()


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


def lab_command():
    """pulsenest_lab.py, detached, from the repo root (its state files live beside it). No --hub:
    the lab has no such flag; it subscribes to the default port by itself."""
    return [windowed_python(), LAB_SCRIPT]


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
    PHONE_COLS = ("device id", "IP", "frames/s", "seen", "offset ms", "last frame (raw, as it arrived)")
    COT_COLS = ("file", "subject", "board", "on the air", "phone", "status", "", "")
    # Every column header carries what the operator needs to read it (Alex, 2026-10-15: the
    # launcher's tooltips must say everything an operator has to know).
    BOARD_TIPS = (
        "The board's address on the WiFi, given by the phone's hotspot (DHCP): it can change "
        "between days, which is why a .toml names the board by its MAC, never by IP.",
        "The board's hardware address, printed on it and listed in docs/boards.md. Fixed for "
        "life: the `board` field of a .toml is the end of this value (the last 4 digits do).",
        "Firmware version the board reports in its $CFG. All boards should agree (see the line "
        "under the table).",
        "Version of the incunest_afe4490 library built into that firmware.",
        "Short git hash of the firmware build.",
        "Fingerprint of the firmware image itself: two boards with the same elfsha run the "
        "same binary, whatever the version numbers say.",
        "Datagrams per second arriving from the board, about 100 when it streams. 0 and "
        "SILENT: switched off, out of WiFi range, or on another network.",
        "live = a datagram in the last 5 s. SILENT n s = nothing for n seconds: amber, red "
        "after a minute.",
    )
    PHONE_TIPS = (
        "The id the VideoNest app was given in its settings; the .toml's `videonest` field "
        "must be exactly this.",
        "The phone's WiFi address, for finding it; the recorder names phones by id, not IP.",
        "Frames per second from the phone, about 1 when it films a monitor.",
        "live = a frame in the last 5 s; SILENT n s otherwise: app closed or in the "
        "background, phone off the WiFi.",
        "Arrival on this PC minus the emission stamp in the frame, in milliseconds: the "
        "network delay plus the offset between the phone's clock and ours, positive when ours "
        "is ahead. Blank when the frame carries no stamp.",
        "The last $VN1 frame exactly as it arrived, to see what the phone is actually sending.",
    )
    COT_TIPS = (
        "The .toml file, one per kit (board + phone). Its name is not used anywhere: "
        "example.toml is the template and cannot be started.",
        "The coded subject in the file ([subject] id). Missing = add it to the file before "
        "START: the recorder refuses to start without one.",
        "The MAC suffix the file names (`board`). The session records that board only.",
        "Which board on the air matches the file: its MAC and whether it is live, 'not on "
        "the air' (amber) when none matches, AMBIGUOUS (red) when the suffix fits two boards: "
        "lengthen it in the file.",
        "The phone the file names ([ref].videonest) and whether it has been heard.",
        "The recorder window this launcher started for this file: running (pid), ended, "
        "cancelled, refused to start, or crashed. Blank = not started from here.",
        "START opens one recorder window for this file, as a process of its own: this "
        "launcher can be closed afterwards and the recording continues. One session per "
        "file at a time: RUNNING while it is.",
        "EDIT opens the file in the system editor. Save, and this table follows; a session "
        "already running keeps the values it was started with.",
    )

    def __init__(self, configs_dir, hub, client):
        super().__init__()
        self.configs_dir, self.hub, self.client = configs_dir, hub, client
        self.fleet = Fleet()
        self.cots = []
        self.extra = {}          # "monitor"/"viewer" -> Popen
        self.setWindowTitle(f"{script_name(__file__)}  —  session launcher  —  hub {hub[0]}:{hub[1]}")
        self.setStyleSheet(DARK_QSS)
        self._build()
        self._configs_sig = configs_signature(configs_dir)
        self.reload_configs()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        saved = s.value("geometry")
        if saved is None or not self.restoreGeometry(saved):
            self.resize(1100, 700)
        split = s.value("splitter")
        if split is not None:
            self.splitter.restoreState(split)
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
        self.disk.setToolTip(f"Free space where sessions are written ({SESSIONS_DIR}), as hours of "
                             f"recording at {MB_PER_MIN_PER_BOARD} MB/min per board (raw stream + live "
                             f"CSV, measured). Amber under 10 h; red under {DISK_FLOOR_GB} GB, where "
                             "the recorder refuses to start.")
        top.addWidget(self.clock)
        top.addSpacing(20)
        top.addWidget(self.disk, 1)
        v.addLayout(top)

        # Three tables in a vertical splitter: each one's height is the user's to drag, and the
        # saved geometry remembers the split.
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        v.addWidget(self.splitter, 1)

        gb = QtWidgets.QGroupBox("BOARDS ON THE AIR  (read-only: this window cannot change a board)")
        gl = QtWidgets.QVBoxLayout(gb)
        self.boards = self._table(self.BOARD_COLS, self.BOARD_TIPS)
        self.boards.setToolTip("Every board the hub hears, whether or not a file names it. "
                               "Read-only: nothing here changes a board.")
        gl.addWidget(self.boards)
        self.firmware = QtWidgets.QLabel("")
        self.firmware.setToolTip("docs/hospital_runbook.md section 1: all boards should report the "
                                 "same fw, build and elfsha. elfsha is the fingerprint of the image "
                                 "itself; two boards with the same elfsha run the same binary.")
        gl.addWidget(self.firmware)
        self.splitter.addWidget(gb)

        gbp = QtWidgets.QGroupBox("PHONES HEARD  (VideoNest, by the device id in its $VN1 frames)")
        glp = QtWidgets.QVBoxLayout(gbp)
        self.phones = self._table(self.PHONE_COLS, self.PHONE_TIPS)
        self.phones.setToolTip("A phone that is not here is not sending: app closed or backgrounded, "
                               "phone off the WiFi, wrong destination address. The hub replays nothing "
                               "for phones, so a phone appears once it has sent since this window opened.\n"
                               "offset ms = arrival on this PC minus the emission stamp in the frame: "
                               "network (milliseconds) plus the offset between the phone's clock and "
                               "ours, positive when ours is ahead -- the recorder's offset_ms column. "
                               "Blank for a frame without the emission stamp.\n"
                               "last frame: the $VN1 exactly as it arrived, uninterpreted.")
        glp.addWidget(self.phones)
        self.splitter.addWidget(gbp)

        # One line (Alex, 2026-10-15): what the files are, where, and the one thing to know
        # about editing them -- the recorder reads its .toml once, at START.
        self.files_box = gb2 = QtWidgets.QGroupBox("SESSION / SUBJECT config files")
        g2 = QtWidgets.QVBoxLayout(gb2)
        # The folder is a link that opens it (OPEN CONFIGS FOLDER stood among the buttons until
        # 2026-10-15), with CHANGE FOLDER... right beside it: the two speak of the same folder.
        head = QtWidgets.QHBoxLayout()
        self.files_link = QtWidgets.QLabel(self._files_line())
        self.files_link.setOpenExternalLinks(False)
        self.files_link.linkActivated.connect(lambda _: open_in_system(self.configs_dir))
        self.files_link.setToolTip("Click the folder to open it in the file manager: to copy "
                                   "example.toml into a new file, or to delete one.")
        self.btn_change = QtWidgets.QPushButton("CHANGE FOLDER\u2026")
        self.btn_change.setToolTip("Pick ANY .toml inside the folder you want (the dialog shows "
                                   "the files, so you can tell the folder by them); its folder is "
                                   "taken. The table and the link follow, and the choice is "
                                   "remembered for the next start. A session already running "
                                   "keeps running; it just leaves this table.")
        self.btn_change.clicked.connect(self.change_folder)
        head.addWidget(self.files_link)
        head.addWidget(self.btn_change)
        head.addStretch(1)
        g2.addLayout(head)
        self.table = self._table(self.COT_COLS, self.COT_TIPS)
        self.table.setToolTip("One row per .toml in the folder. A session reads its file once, "
                              "at START; edit before, not after.")
        g2.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        # START ALL COTS stood here until 2026-10-15: one click could open a session on every
        # cot file in the folder, wanted or not (Alex). A cot is started one at a time, from its
        # own row. The engineer's tool takes the place.
        self.btn_lab = QtWidgets.QPushButton("PULSENEST LAB")
        self.btn_lab.setToolTip("pulsenest_lab.py, the engineer's tool: live plots, the library's "
                                "Python replicas, $SET control of a board. Not needed for a "
                                "session. One copy at a time from here; if the lab is already "
                                "open (it may have started this window), use that one.")
        self.btn_lab.clicked.connect(lambda: self.start_extra("lab"))
        self.btn_monitor = QtWidgets.QPushButton("FLEET MONITOR")
        self.btn_monitor.setToolTip("tools/fleet_monitor.py in a console of its own: one line per "
                                    "board, refreshed every second. Read-only.")
        self.btn_monitor.clicked.connect(lambda: self.start_extra("monitor"))
        self.btn_viewer = QtWidgets.QPushButton("PPG VIEWER")
        self.btn_viewer.setToolTip("tools/fleet_ppg_viewer.py: one live PPG band per board, to see "
                                   "whether a probe has moved. Read-only. Optional -- the recorder "
                                   "window shows its own waveform.")
        self.btn_viewer.clicked.connect(lambda: self.start_extra("viewer"))
        for b in (self.btn_lab, self.btn_monitor, self.btn_viewer):
            row.addWidget(b)
        row.addStretch(1)
        self.extra_status = QtWidgets.QLabel("")
        self.extra_status.setToolTip("The programs started from the buttons on the left: running, "
                                     "ended, cancelled, refused to start, or crashed.")
        row.addWidget(self.extra_status)
        g2.addLayout(row)
        self.splitter.addWidget(gb2)
        self.splitter.setStretchFactor(2, 1)

    def _files_line(self):
        """The line under the box title: the folder as a link (relative to the repo when inside
        it, so it fits; the full path otherwise), and the one thing to know about editing."""
        d = self.configs_dir
        if os.path.normcase(d).startswith(os.path.normcase(_ROOT + os.sep)):
            d = os.path.relpath(d, _ROOT)
        return (f'.toml in <a href="open" style="color:{LINK};">{d}</a>   '
                "\u2014   a session reads its file once, at START")

    def set_configs_dir(self, directory):
        """Point the table at another folder: title, table and the remembered choice follow."""
        self.configs_dir = os.path.abspath(directory)
        self.files_link.setText(self._files_line())
        self._configs_sig = configs_signature(self.configs_dir)
        self.reload_configs()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("configs_dir", self.configs_dir)
        s.sync()

    def change_folder(self):
        # A file dialog, not a folder dialog: the system's "select folder" shows folders only,
        # so the operator could not tell the right one by what is in it (Alex, 2026-10-15). Any
        # .toml of the wanted folder will do; its folder is what is taken.
        chosen, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Pick any .toml in the folder to use", self.configs_dir, "Session files (*.toml)")
        if chosen:
            self.set_configs_dir(os.path.dirname(chosen))

    @staticmethod
    def _table(cols, tips=()):
        t = QtWidgets.QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        for c, tip in enumerate(tips):
            t.horizontalHeaderItem(c).setToolTip(tip)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        return t

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
            btn.setToolTip("One recorder window for this file, as a process of its own. Check the "
                           "row first: subject present, board on the air, phone heard.")
            btn.clicked.connect(lambda _=False, c=cot: self.start_cot(c))
            self.table.setCellWidget(r, 6, btn)
            edit = QtWidgets.QPushButton("EDIT")
            edit.setToolTip("Opens the file in the system's editor. Save, and this table follows; "
                            "a session already running keeps the values it was started with.")
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
            seen, seen_colour = seen_text(b.age(now))
            col = GREY if b.silent(now) else None
            vals = (b.ip, b.mac, b.fields.get("fw", "?"), b.fields.get("lib", "?"),
                    b.fields.get("build", "?"), b.fields.get("elfsha", "?"),
                    "%.0f" % (0 if b.silent(now) else b.rate), seen)
            for c, val in enumerate(vals):
                self.boards.setItem(r, c, _item(val, seen_colour if c == 7 else col, mono=c in (1, 5)))
        ok, text = self.fleet.firmware_agreement()
        self.firmware.setText(("OK  " if ok else "CHECK  ") + text)
        self.firmware.setStyleSheet(f"color: {GREEN if ok else AMBER};")

        phones = sorted(self.fleet.phones.items())
        self.phones.setRowCount(len(phones))
        for r, (dev, p) in enumerate(phones):
            seen, seen_colour = seen_text(p.age(now))
            col = GREY if p.silent(now) else None
            vals = (dev, p.ip, "%.1f" % (0 if p.silent(now) else p.rate), seen,
                    "" if p.last_offset_ms is None else str(p.last_offset_ms), p.last_frame)
            for c, val in enumerate(vals):
                self.phones.setItem(r, c, _item(val, seen_colour if c == 3 else col, mono=c in (0, 5)))

        sig = configs_signature(self.configs_dir)
        if sig != self._configs_sig:
            self._configs_sig = sig
            self.reload_configs()      # calls refresh() again on the fresh list; nothing below is stale
            return

        for r, cot in enumerate(self.cots):
            self._cot_row(r, cot)
        parts = []
        for key, proc in self.extra.items():
            rc = proc.poll()
            parts.append(f"{key}: " + ("running" if rc is None else ended_text(rc)[0]))
        self.extra_status.setText("   ".join(parts))
        self.btn_monitor.setEnabled(not self._extra_running("monitor"))
        self.btn_viewer.setEnabled(not self._extra_running("viewer"))
        self.btn_lab.setEnabled(not self._extra_running("lab"))

    def _cot_row(self, r, cot):
        self.table.setItem(r, 0, _item(cot.name, FG_DIM if cot.is_example else None))
        if cot.error:
            self.table.setItem(r, 1, _item(cot.error, RED))
            for c in (2, 3, 4):
                self.table.setItem(r, c, _item(""))
        else:
            self.table.setItem(r, 1, _item(cot.field("subject") or "(missing: add it to the file)",
                                           None if cot.field("subject") else FG_DIM))
            self.table.setItem(r, 2, _item(cot.field("board"), mono=True))
            now = time.monotonic()
            kind, detail = self.fleet.match_board(cot.field("board"))
            text, colour = {
                "ok":        (detail, GREEN),
                "none":      ("not on the air", AMBER),
                "ambiguous": (f"AMBIGUOUS: {detail}", RED),
                "blank":     ("(no board in the file)", FG_DIM),
            }[kind]
            if kind == "ok":
                b = self.fleet.board_of(detail)
                if b is not None and b.silent(now):        # a board switched off is not on the air
                    seen, colour = seen_text(b.age(now))
                    text = f"{detail}  {seen}"
            self.table.setItem(r, 3, _item(text, colour, mono=kind == "ok"))
            dev = cot.field("ref_videonest")
            p = self.fleet.phones.get(dev) if dev else None
            if not dev:
                self.table.setItem(r, 4, _item("(none declared)", FG_DIM))
            elif p is None:
                self.table.setItem(r, 4, _item(f"{dev} NOT heard", AMBER))
            else:
                age = p.age(now)
                _, colour = seen_text(age)
                self.table.setItem(r, 4, _item(f"{dev} heard {age:.0f} s ago", colour))
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

    def start_extra(self, key):
        if self._extra_running(key):
            return
        if key == "monitor":
            self.extra[key] = spawn(monitor_command(self.hub), console=True)
        elif key == "lab":
            self.extra[key] = spawn(lab_command())
        else:
            self.extra[key] = spawn(viewer_command(self.hub))
        self.refresh()

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("splitter", self.splitter.saveState())
        s.sync()
        self._drain_timer.stop()
        self._refresh_timer.stop()
        self.client.close()
        event.accept()        # the processes started here are detached: they keep running


def saved_configs_dir():
    """The folder chosen last time with CHANGE FOLDER, if it still exists; else the default."""
    s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
    saved = s.value("configs_dir")
    return saved if saved and os.path.isdir(saved) else DEFAULT_CONFIGS


def parse_hub(text):
    host, _, port = text.partition(":")
    return (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PulseNest session launcher: the cots, what is on the air, "
                                             "and a START button per cot. Read-only.")
    ap.add_argument("--configs", default=None, metavar="DIR",
                    help="folder with one .toml per cot (default: the folder chosen last time with "
                         "CHANGE FOLDER, else docs/session_configs)")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    args = ap.parse_args(argv)
    hub = parse_hub(args.hub)
    app = QtWidgets.QApplication(sys.argv)
    client = HubClient(script_name(__file__), hub=hub, control=False)
    client.connect()          # starts the hub if none answers; reconnects by itself otherwise
    w = Launcher(os.path.abspath(args.configs or saved_configs_dir()), hub, client)
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
