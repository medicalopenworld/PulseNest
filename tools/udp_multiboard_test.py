"""Regression test for multi-board UDP reception in pulsenest_lab.py (spec §4.8, v1.44/v1.45).

Simulated boards on loopback drive PPGMonitor offscreen. The data/command ports are patched to
15005/15006 so a real bench streaming to :5005 does not interfere. Frames are real $M4 lines
(embedded template, or a live one with --live-template), counter rewritten, checksum recomputed,
so the drain parses them exactly as it would real traffic.

Scenario
  1. Board A (127.0.0.1) streams first -> ACTIVE. Board B (127.0.0.2) starts 1 s later -> PRESENT:
     queried with $CFG?, identified by MAC, every line of it dropped before the pipeline.
  2. A stops -> flagged LOST after UDP_LOST_TIMEOUT_S; the active binding is not changed.
  3. A comes back from 127.0.0.3 with the same MAC (new DHCP lease) -> the active binding follows.
  4. The user picks B in the SOURCE combo -> B active, A' present and dropped; choice remembered by MAC.
  5. The user picks SERIAL -> both boards dropped, UDP button LISTEN.
  6. B (active again) goes silent -> UDP button LOST; nothing replaces it.
  7. Fresh UDP connection with B preferred: A' speaks first, B is promoted when identified.
  8. MULTI CAPTURE records both boards at once: one CSV each, exactly N rows, HOST_T_US present,
     $MODE sent to every board, and corrupted frames rejected by checksum instead of written.
  9-10. Stream discontinuities, and what counts as a partial datagram (five LINES, not five frames).
  11. A rival program holds the hub's control: the lab still receives, its UDP button says
     READ-ONLY, its $SET is not sent, and the control comes back on its own when the rival leaves.

Usage:  python tools/udp_multiboard_test.py [--live-template]
Exit code 0 when every check passes.
"""
import io
import os
import re
import socket
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import pulsenest_lab as P  # noqa: E402
import pulsenest_hub as H  # noqa: E402
import pulsenest_hub_client as HC  # noqa: E402
from PyQt5 import QtCore, QtWidgets  # noqa: E402

DATA_PORT, CMD_PORT = 15005, 15006
P.UDP_DATA_PORT = DATA_PORT
P.UDP_CMD_PORT = CMD_PORT
HC.AUTOSTART_ENABLED = False          # the test runs its own hub, in-process, on the spare port
P.UDP_LOST_TIMEOUT_S = 1.5
P.UDP_NET_SUMMARY_S = 4.0

# One real $M4 frame from board 16.A, lib v0.90, 2026-09-09 (HGAC on, RF 100K/100K, probe absent).
EMBEDDED_TEMPLATE = (
    b"$M4,782071,1567641472,2096921,2096921,205391,99581,1891530,1997340,1.1501e-08,-1.00,0.00,"
    b"nan,nan,-1.00,0.00,-1.00,0.00,-1.00,0.00,0,0,4,1.1999e+00,1.1999e+00,5.6981e-02,1.1753e-01,"
    b"5.9993e-06,5.9993e-06,2.8490e-07,5.8763e-07,1.1474e-04,1.0866e-04,0505,100K,100K*06"
)


def grab_live_template():
    """One real $M4 line from a board streaming to :5005, or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.5)
    try:
        s.bind(("", 5005))
    except OSError:
        return None
    t_end = time.time() + 4
    try:
        while time.time() < t_end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            for line in data.split(b"\n"):
                line = line.rstrip(b"\r")
                if line.startswith(b"$M4,") and b"*" in line:
                    return line
    finally:
        s.close()
    return None


def with_chk(body):
    chk = 0
    for c in body[1:]:
        chk ^= c
    return body + b"*%02X" % chk


class FakeBoard(threading.Thread):
    """Streams UDP_BATCH_SIZE frames per datagram at ~100 datagrams/s and answers $CFG?."""

    def __init__(self, ip, mac, board, template, start_cnt, rate_dgram_s=100, batch=5,
                 corrupt_every=0, diag_every=100):
        super().__init__(daemon=True)
        self.ip, self.mac, self.board = ip, mac, board
        self.corrupt_every = corrupt_every   # 0 = never; else break the checksum of every Nth frame
        self.corrupted = 0
        # fw 0.12: the library's five diagnostic lines travel in a datagram of their own, never as
        # slots of a data batch. Every `diag_every` data datagrams (the real board: every 500).
        self.diag_every = diag_every
        self.sent = 0
        self.diag_bursts = 0
        self.mode_cmds = 0
        self.template_fields = template.split(b"*")[0].split(b",")
        self.cnt = start_cnt
        self.period = 1.0 / rate_dgram_s
        self.batch = batch
        self.stop = threading.Event()
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data.bind((ip, 0))
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.bind((ip, CMD_PORT))
        self.cmd.settimeout(0.0)
        self.cfg_requests = 0

    def frame(self):
        f = list(self.template_fields)
        f[1] = str(self.cnt).encode()
        self.cnt += 1
        line = with_chk(b",".join(f))
        if self.corrupt_every and self.cnt % self.corrupt_every == 0:
            # Flip the last checksum nibble: a frame that must never reach a capture CSV.
            self.corrupted += 1
            line = line[:-1] + (b"0" if line[-1:] != b"0" else b"1")
        return line

    def cfg_frame(self):
        body = (f"$CFG,sr=500,numav=8,led1=49.80,led2=49.80,board={self.board},mac={self.mac},"
                f"fw=0.9,lib=0.90,build=fake,libsha=fake").encode()
        return with_chk(body)

    def diag_burst(self):
        """$TIMING + one $TASK per library task + $TASKS_END, as the firmware emits them every 5 s."""
        lines = [with_chk(b"$TIMING,7,25,11,25,19,42,11,29,434,721,600,610,1200,1500,5704,238,312"),
                 with_chk(b"$TASK,incunest_afe4490,217,5708"),
                 with_chk(b"$TASK,incunest_hr2,0,1800"),
                 with_chk(b"$TASK,incunest_hr3,0,1236"),
                 with_chk(b"$TASKS_END")]
        return b"".join(line + b"\r\n" for line in lines)

    def run(self):
        dst = ("127.0.0.1", DATA_PORT)
        while not self.stop.is_set():
            payload = b"".join(self.frame() + b"\r\n" for _ in range(self.batch))
            self.data.sendto(payload, dst)
            self.sent += 1
            if self.diag_every and self.sent % self.diag_every == 0:
                self.data.sendto(self.diag_burst(), dst)
                self.diag_bursts += 1
            try:
                while True:
                    req, _ = self.cmd.recvfrom(256)
                    if req.strip() == b"$CFG?":
                        self.cfg_requests += 1
                        self.data.sendto(self.cfg_frame() + b"\r\n", dst)
                    elif req.startswith(b"$MODE,"):
                        self.mode_cmds += 1
            except (BlockingIOError, OSError):
                pass
            time.sleep(self.period)
        self.data.close()
        self.cmd.close()


def spin(app, seconds):
    t_end = time.time() + seconds
    while time.time() < t_end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        time.sleep(0.002)


def main():
    template = EMBEDDED_TEMPLATE
    if "--live-template" in sys.argv:
        live = grab_live_template()
        if live is None:
            print("no live $M4 on :5005, using the embedded template")
        else:
            template = live
    print("template:", template[:60].decode(), "...")

    app = QtWidgets.QApplication([])
    # Isolate from the user's settings file. Redirecting SETTINGS_FILE covers everything:
    # _save_settings, _restore_settings and every subwindow's closeEvent, each of which builds
    # its own QSettings and would otherwise bypass a patched _save_settings — which is how an
    # earlier version of this test left MultiCaptureWindow's prefix and geometry in the real ini.
    # It also makes the run deterministic: no stored geometry, no stored board preference.
    P.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_lab_test.ini")
    if os.path.exists(P.SETTINGS_FILE):
        os.remove(P.SETTINGS_FILE)
    w = P.PPGMonitor()
    w._udp_preferred_mac = None
    w._udp_source_user_chosen = False
    logs = []
    w._sig_log.connect(lambda t: (logs.append(t), print("LOG ", t)), QtCore.Qt.QueuedConnection)
    w._sig_udpcom_line.connect(lambda t: print("NET ", t), QtCore.Qt.QueuedConnection)
    _orig_log = w.log
    w.log = lambda t: (logs.append(t), print("LOG*", t), _orig_log(t))
    cfg_seen = []
    _orig_cfg = w._on_cfg_frame_received

    def _cfg_wrap(line):
        m = re.search(r"mac=([^,*]+)", line)
        cfg_seen.append(m.group(1) if m else "?")
        _orig_cfg(line)

    w._on_cfg_frame_received = _cfg_wrap

    results = []

    def check(cond, msg):
        results.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + msg)

    mac_a, mac_b = "AA:AA:AA:AA:AA:01", "BB:BB:BB:BB:BB:02"
    a = FakeBoard("127.0.0.1", mac_a, "fakeA", template, start_cnt=1000)
    b = FakeBoard("127.0.0.2", mac_b, "fakeB", template, start_cnt=900000)

    # Since v1.60 the lab is a hub subscriber (spec 4.11): the fake boards send to the data port,
    # the hub owns it and forwards to the lab, tagged with each board's IP. Same test, one hop more.
    hub = H.Hub(port=DATA_PORT, cmd_port=CMD_PORT)
    hub.open()
    threading.Thread(target=hub.serve_forever, daemon=True).start()

    w._connect_udp()
    a.start()
    spin(app, 1.0)
    b.start()
    spin(app, 6.0)

    snap = {x["ip"]: x for x in w.udp_boards_snapshot()}
    print("\n--- phase 1: A active, B present ---")
    for x in snap.values():
        print(x)
    sa, sb = snap.get("127.0.0.1", {}), snap.get("127.0.0.2", {})
    check(w._esp32_ip == "127.0.0.1", "active = A (first to speak)")
    check(w._active_transport == "udp", "transport switched to udp")
    check(sa.get("state") == "ACTIVE", "A state ACTIVE")
    check(sb.get("state") == "PRESENT", "B state PRESENT")
    check(sa.get("mac") == mac_a, "A identified via its $CFG (main-thread request)")
    check(sb.get("mac") == mac_b, "B identified via reader-thread $CFG? query")
    check(b.cfg_requests >= 1, f"B received {b.cfg_requests} $CFG? request(s)")
    check(set(cfg_seen) == {mac_a}, f"only A's $CFG reached the pipeline ({sorted(set(cfg_seen))})")
    check(sb.get("frames", 0) > 0 and sb.get("not_active") == sb.get("frames") + sb.get("other_lines"),
          "B fully not_active (frames + other_lines == not_active)")
    check(sa.get("not_active") == 0, "A not_active == 0")
    check(w._gaps_B == 0 and sb.get("gaps_air") == 0 and sb.get("gaps_queue") == 0,
          "no cross-board gaps (counters 1000.. and 900000.. never mixed)")
    check(sa.get("frames", 0) > 0.8 * 500 * 7, "A ~500 frames/s ingested")
    # fw 0.12 invariant: a data datagram carries exactly UDP_BATCH_SIZE frames; the diagnostic
    # burst is a datagram of its own, so it shows in `datagrams` but not in `data_datagrams`.
    check(sa.get("data_datagrams", 0) > 0
          and sa.get("frames") == P.UDP_BATCH_SIZE * sa.get("data_datagrams"),
          f"A: frames == 5 x data_datagrams ({sa.get('frames')} vs {sa.get('data_datagrams')})")
    # Datagrams without data = the diagnostic bursts + one $CFG reply per $CFG? received (a reply
    # may still be in flight when the snapshot is taken, hence the +1).
    no_data = sa.get("datagrams", 0) - sa.get("data_datagrams", 0)
    check(a.diag_bursts > 0 and a.diag_bursts <= no_data <= a.diag_bursts + a.cfg_requests + 1,
          f"A: {no_data} datagrams without data = {a.diag_bursts} diagnostic bursts + "
          f"{a.cfg_requests} $CFG replies")
    check(sa.get("partial_datagrams") == 0 and sb.get("partial_datagrams") == 0,
          "partial == 0 on both boards with diagnostics in their own datagrams")

    print("\n--- phase 2: A goes silent -> LOST, no auto-switch ---")
    a.stop.set()
    a.join(1.0)
    spin(app, 3.0)
    snap = {x["ip"]: x for x in w.udp_boards_snapshot()}
    check(snap.get("127.0.0.1", {}).get("state") == "LOST", "A flagged LOST")
    check(w._esp32_ip == "127.0.0.1", "active binding unchanged while LOST (never auto-switch)")
    check(snap.get("127.0.0.2", {}).get("state") == "PRESENT", "B still PRESENT, not promoted")
    check(any("LOST" in t and "127.0.0.1" in t for t in logs), "LOST logged")

    print("\n--- phase 3: A returns from 127.0.0.3 with the same MAC (DHCP) -> follow ---")
    a2 = FakeBoard("127.0.0.3", mac_a, "fakeA", template, start_cnt=5000)
    a2.start()
    spin(app, 5.0)
    snap = {x["ip"]: x for x in w.udp_boards_snapshot()}
    for x in snap.values():
        print(x)
    s3 = snap.get("127.0.0.3", {})
    check(w._esp32_ip == "127.0.0.3", "active binding followed the MAC to 127.0.0.3")
    check("127.0.0.1" not in snap, "stale entry for the old IP removed")
    check(s3.get("state") == "ACTIVE", "A' state ACTIVE")
    check(0 <= s3.get("not_active", -1) <= 3 * P.UDP_BATCH_SIZE,
          "A' forwarded after the follow (only the <=3 datagrams before its $CFG reply dropped)")
    check(any("moved 127.0.0.1" in t for t in logs), "move logged")

    def snapshot():
        return {x["ip"]: x for x in w.udp_boards_snapshot()}

    def combo_index_of(ip):
        return next(i for i in range(w.combo_source.count()) if w.combo_source.itemData(i) == ("udp", ip))

    print("\n--- phase 4: user picks B in SOURCE -> B active, A' present ---")
    w._refresh_source_combo()
    check(w.combo_source.count() == 3, f"combo lists SERIAL + 2 boards ({w.combo_source.count()})")
    check(w.combo_source.itemData(w.combo_source.currentIndex()) == ("udp", "127.0.0.3"),
          "combo current item = active board")
    w.combo_source.setCurrentIndex(combo_index_of("127.0.0.2"))   # user action
    spin(app, 3.0)
    snap = snapshot()
    check(w._esp32_ip == "127.0.0.2" and w._active_transport == "udp", "B is the active source")
    check(snap["127.0.0.2"]["state"] == "ACTIVE" and snap["127.0.0.3"]["state"] == "PRESENT", "states swapped")
    d3, d2 = snap["127.0.0.3"]["not_active"], snap["127.0.0.2"]["not_active"]
    spin(app, 2.0)
    snap = snapshot()
    check(snap["127.0.0.3"]["not_active"] > d3 and snap["127.0.0.2"]["not_active"] == d2, "A' not_active, B forwarded")
    check(w._udp_preferred_mac == mac_b and w._udp_source_user_chosen, "choice remembered by MAC")
    check(w.btn_udp.text().startswith("UDP WiFi  ●  ON"), f"UDP button ON ({w.btn_udp.text()})")
    check(cfg_seen and cfg_seen[-1] == mac_b, "B's $CFG reached the pipeline after the switch")

    print("\n--- phase 5: user picks SERIAL -> boards ignored, UDP button LISTEN ---")
    w.combo_source.setCurrentIndex(0)
    spin(app, 1.5)
    check(w._active_transport == "serial", "transport = serial")
    s2 = snapshot()["127.0.0.2"]
    spin(app, 1.0)
    s2b = snapshot()["127.0.0.2"]
    check(s2b["frames"] > s2["frames"] and s2b["not_active"] == s2["not_active"],
          "B still flows to the UDP COM console (not dropped); the drain ignores it for algorithms")
    check(w.btn_udp.text().startswith("UDP WiFi  ●  LISTEN"), f"UDP button LISTEN ({w.btn_udp.text()})")

    print("\n--- phase 6: active board goes silent -> UDP button LOST ---")
    w.combo_source.setCurrentIndex(combo_index_of("127.0.0.2"))
    spin(app, 1.0)
    b.stop.set()
    b.join(1.0)
    spin(app, 3.5)
    snap = snapshot()
    check(snap["127.0.0.2"]["state"] == "LOST" and w._esp32_ip == "127.0.0.2", "B LOST, still the active source")
    check(w.btn_udp.text().startswith("UDP WiFi  ●  LOST"), f"UDP button LOST ({w.btn_udp.text()})")
    check(snap["127.0.0.3"]["state"] == "PRESENT", "A' not promoted")

    print("\n--- phase 7: fresh connection, B preferred: A' speaks first, B promoted on identification ---")
    w._disconnect_udp()
    w._udp_preferred_mac = mac_b
    w._udp_source_user_chosen = False
    w._connect_udp()
    spin(app, 1.0)                       # A' (still streaming) becomes the provisional active board
    check(w._esp32_ip == "127.0.0.3", "A' provisional active (first to speak)")
    b2 = FakeBoard("127.0.0.2", mac_b, "fakeB", template, start_cnt=700000)
    b2.start()
    spin(app, 4.0)
    snap = snapshot()
    check(w._esp32_ip == "127.0.0.2" and snap["127.0.0.2"]["state"] == "ACTIVE",
          "preferred board promoted over the first speaker")
    check(any("Preferred board" in t for t in logs), "promotion logged")
    check(w.combo_source.itemData(w.combo_source.currentIndex()) == ("udp", "127.0.0.2"), "combo follows")

    print("\n--- phase 8: MULTI CAPTURE both boards, one CSV each ---")
    # Never write into the project's captures/ directory from a test.
    tmpdir = os.path.join(tempfile.gettempdir(), "pulsenest_multicapture_test")
    if os.path.isdir(tmpdir):
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
    os.makedirs(tmpdir, exist_ok=True)
    P.CAPTURES_DIR = tmpdir
    # b2 corrupts one frame in 20: they must be counted and skipped, never written.
    b2.corrupt_every = 20
    win = P.MultiCaptureWindow(w)
    w.multi_capture_window = win
    win._spin_samples.setValue(1000)
    win._prefix.setText("TEST")
    win._pre_notes.setPlainText("phase 8")
    win._post_notes.setPlainText("phase 8 end")
    win._refresh_boards()
    check(len(win._checks) == 2, f"board table lists 2 boards ({len(win._checks)})")
    check(all(cb.isChecked() for cb in win._checks.values()), "boards ticked by default")
    n_mode_before = {b.ip: b.mode_cmds for b in (a2, b2)}
    win._on_start_stop()
    spin(app, 1.0)
    check(bool(w._multi_writers), "capture running")
    check(all(not cb.isEnabled() for cb in win._checks.values()), "tick boxes locked while recording")
    check(win.btn_start.text() == "STOP", f"button reads STOP ({win.btn_start.text()})")
    for _ in range(60):                      # let both boards reach 1000 rows
        spin(app, 0.3)
        if not w._multi_writers:
            break
    check(not w._multi_writers, "auto-stopped when every board reached the target")
    check(all(bd.mode_cmds > n_mode_before[bd.ip] for bd in (a2, b2)),
          f"$MODE sent to every board ({[bd.mode_cmds for bd in (a2, b2)]})")
    files = sorted(os.listdir(tmpdir))
    check(len(files) == 2, f"2 CSVs written ({files})")
    check(all(f.startswith("TEST_fake") and f.endswith(".csv") for f in files),
          f"filenames carry prefix and board ({files})")
    check(any(mac_a.replace(":", "")[-6:] in f for f in files)
          and any(mac_b.replace(":", "")[-6:] in f for f in files),
          "each filename carries its board's MAC tail")
    for f in files:
        txt = io.open(os.path.join(tmpdir, f), encoding="cp1252").read().splitlines()
        body = [l for l in txt if not l.startswith("#")]
        hdr, rows = body[0].split(","), body[1:]
        notes = [l for l in txt if l.startswith("#")]
        is_b = mac_b.replace(":", "")[-6:] in f
        tag = "B(corrupting)" if is_b else "A"
        ci, hi = hdr.index("FW_SmpCnt"), hdr.index("HOST_T_US")
        cnts = [int(r.split(",")[ci]) for r in rows]
        hosts = [int(r.split(",")[hi]) for r in rows]
        check(hdr[0] == "HOST_T_US", f"{tag}: HOST_T_US first column")
        check(len(rows) == 1000, f"{tag}: exactly 1000 rows ({len(rows)})")
        check(all(len(r.split(",")) == len(hdr) for r in rows), f"{tag}: every row full width")
        check("# phase 8" in notes and "# phase 8 end" in notes, f"{tag}: pre and post notes")
        check(any("fake" in n for n in notes), f"{tag}: board identity in the notes")
        check(hosts == sorted(hosts), f"{tag}: HOST_T_US monotonic")
        check(len(set(hosts)) >= len(rows) // 5 - 2, f"{tag}: ~one stamp per datagram ({len(set(hosts))})")
        holes = sum(1 for x, y in zip(cnts, cnts[1:]) if y - x != 1)
        if is_b:
            check(holes > 0, f"{tag}: corrupted frames missing from the CSV ({holes} holes)")
        else:
            check(holes == 0, f"{tag}: no holes ({holes})")
    check(b2.corrupted > 0, f"B produced {b2.corrupted} corrupted frames")
    check(any("rejected by checksum" in t for t in logs),
          "the rejected frames are reported in the log")
    win.main_monitor = None
    win.close()
    w.multi_capture_window = None

    # ── Phase 9: stream discontinuity — a board restart and a source change restart the buffers ──
    print("\n[phase 9] stream discontinuity")
    for cls in ("SpO2LabWindow", "SpO2TestWindow", "HR1TestWindow", "HR2TestWindow", "HR3TestWindow",
                "PILabWindow", "HR1LabWindow", "HR2LabWindow", "PPGSignalsWindow", "PPGSignals2Window"):
        check(callable(getattr(getattr(P, cls), "on_stream_discontinuity", None)),
              f"{cls} implements on_stream_discontinuity")
    active = a2 if w._esp32_ip == a2.ip else b2
    other = b2 if active is a2 else a2
    spin(app, 2.5)                                   # past the suppression window of earlier events
    d0 = w._stream_disc_count
    hi_before = max(w.data_sample_counter)
    check(hi_before > 5000, f"buffers hold the old counters before the restart ({hi_before})")
    active.cnt = 0                                   # the active board "restarts": counter from zero
    spin(app, 1.0)
    check(w._stream_disc_count == d0 + 1, f"restart detected exactly once ({w._stream_disc_count - d0})")
    check("counter went back" in w._stream_disc_last, f"reason names the counter ({w._stream_disc_last})")
    check(max(w.data_sample_counter) < 5000,
          f"buffers restarted: no old counter left ({max(w.data_sample_counter)})")
    check(any("[STREAM] discontinuity" in x for x in logs), "the discontinuity is logged")
    spin(app, 2.5)                                   # past the suppression window again
    w._select_udp_source(other.ip, by_user=True)     # the user picks the other board
    spin(app, 0.6)
    check(w._stream_disc_count == d0 + 2, f"a source change is a discontinuity too ({w._stream_disc_count - d0})")
    check("source changed" in w._stream_disc_last, f"reason names the source ({w._stream_disc_last})")
    check(w._esp32_ip == other.ip, "pipeline now fed by the other board")

    print("\n[phase 10] partial datagrams: a full datagram is five LINES, not five data frames")
    # Measured on the bench 2026-09-15: the library emits five diagnostic lines every 5 s
    # ($TIMING + three $TASK + $TASKS_END) and, since fw 0.11, they share the data queue, so they
    # take slots in otherwise full datagrams. Counting data frames alone flagged those as partial
    # batches — 26 of them in 75 s of three boards, and not one genuine short batch.
    a2.stop.set()
    b2.stop.set()
    a2.join(1.0)
    b2.join(1.0)
    spin(app, 0.5)
    src = active                       # stopped now; the test speaks for it from its own IP

    def partial_of(ip):
        return {x["ip"]: x for x in w.udp_boards_snapshot()}.get(ip, {}).get("partial_datagrams")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((src.ip, 0))

    def dgram(lines):
        sock.sendto(b"\r\n".join(lines) + b"\r\n", ("127.0.0.1", DATA_PORT))
        spin(app, 0.4)

    timing = with_chk(b"$TIMING,1,2,3,4,5,6,7,8,9,10,11,12,13,14,5700,230,300")
    p0 = partial_of(src.ip)
    dgram([src.frame() for _ in range(P.UDP_BATCH_SIZE)])
    check(partial_of(src.ip) == p0, "5 data frames: not partial")
    dgram([src.frame() for _ in range(P.UDP_BATCH_SIZE - 1)] + [timing])
    check(partial_of(src.ip) == p0, "4 data frames + $TIMING = 5 lines: not partial")
    dgram([src.frame() for _ in range(P.UDP_BATCH_SIZE - 2)])
    check(partial_of(src.ip) == p0 + 1, "3 lines only: partial (batch closed by the timeout)")
    dd0 = {x["ip"]: x for x in w.udp_boards_snapshot()}[src.ip]["data_datagrams"]
    dgram([timing])
    check(partial_of(src.ip) == p0 + 1, "a datagram with no data frame is not a partial batch")
    check({x["ip"]: x for x in w.udp_boards_snapshot()}[src.ip]["data_datagrams"] == dd0,
          "a diagnostic-only datagram does not count as a data datagram (frm/dgram unaffected)")
    sock.close()

    print("\n[phase 11] a second lab reads but cannot write: the UDP button says READ-ONLY")
    # Two instances of the lab happened by accident on 2026-09-17: both painted normally and
    # only the hub's log said the second had been refused the control. The button has to say it.
    w._disconnect_udp()
    spin(app, 0.5)
    rival = HC.HubClient("rival_lab", hub=("127.0.0.1", DATA_PORT), control=True, log=lambda m: None)
    check(rival.connect() and rival.controller, "a rival program takes the hub's control first")
    a2 = FakeBoard("127.0.0.1", mac_a, "fakeA", template, start_cnt=5000)
    a2.start()
    w._connect_udp()
    spin(app, 3.0)
    check(w._hub is not None and not w._hub.controller, "the lab is refused the control")
    check(w._active_transport == "udp", "it still receives and feeds the pipeline")
    check(w.btn_udp.text().startswith("UDP WiFi  ●  READ-ONLY"), f"button READ-ONLY ({w.btn_udp.text()})")
    check(any("READ-ONLY" in t and "rival_lab" in t for t in logs), "the log names who holds it")
    check(not w.send_set("led1", "20"), "a $SET from the read-only instance is not sent")
    rival.release_control()
    rival.close()
    spin(app, 8.0)          # the client re-claims every CTRL_RETRY_S
    check(w._hub.controller and w.btn_udp.text().startswith("UDP WiFi  ●  ON"),
          f"control returns when the rival leaves ({w.btn_udp.text()})")
    a2.stop.set()

    w._disconnect_udp()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed —", "OK" if ok else "FAILED")
    sys.stdout.flush()
    sys.stderr.flush()
    # _exit: skip PPGMonitor.closeEvent so the user's saved window geometry is left untouched.
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
