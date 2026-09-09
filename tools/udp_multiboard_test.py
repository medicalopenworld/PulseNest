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

Usage:  python tools/udp_multiboard_test.py [--live-template]
Exit code 0 when every check passes.
"""
import os
import re
import socket
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import pulsenest_lab as P  # noqa: E402
from PyQt5 import QtCore, QtWidgets  # noqa: E402

DATA_PORT, CMD_PORT = 15005, 15006
P.UDP_DEFAULT_PORT = DATA_PORT
P.UDP_CMD_PORT = CMD_PORT
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

    def __init__(self, ip, mac, board, template, start_cnt, rate_dgram_s=100, batch=5):
        super().__init__(daemon=True)
        self.ip, self.mac, self.board = ip, mac, board
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
        return with_chk(b",".join(f))

    def cfg_frame(self):
        body = (f"$CFG,sr=500,numav=8,led1=49.80,led2=49.80,board={self.board},mac={self.mac},"
                f"fw=0.9,lib=0.90,build=fake,libsha=fake").encode()
        return with_chk(body)

    def run(self):
        dst = ("127.0.0.1", DATA_PORT)
        while not self.stop.is_set():
            payload = b"".join(self.frame() + b"\r\n" for _ in range(self.batch))
            self.data.sendto(payload, dst)
            try:
                while True:
                    req, _ = self.cmd.recvfrom(256)
                    if req.strip() == b"$CFG?":
                        self.cfg_requests += 1
                        self.data.sendto(self.cfg_frame() + b"\r\n", dst)
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
    # Isolate from the user's settings file: never write it (class-level, so timers and slots bound
    # in __init__ get the no-op too) and start without a stored board preference.
    P.PPGMonitor._save_settings = lambda self: None
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
    check(sb.get("frames", 0) > 0 and sb.get("dropped") == sb.get("frames") + sb.get("other_lines"),
          "B fully dropped (frames + other_lines == dropped)")
    check(sa.get("dropped") == 0, "A nothing dropped")
    check(w._gaps_B == 0 and sb.get("gaps_air") == 0 and sb.get("gaps_queue") == 0,
          "no cross-board gaps (counters 1000.. and 900000.. never mixed)")
    check(sa.get("frames", 0) > 0.8 * 500 * 7, "A ~500 frames/s ingested")

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
    check(0 <= s3.get("dropped", -1) <= 3 * P.UDP_BATCH_SIZE,
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
    d3, d2 = snap["127.0.0.3"]["dropped"], snap["127.0.0.2"]["dropped"]
    spin(app, 2.0)
    snap = snapshot()
    check(snap["127.0.0.3"]["dropped"] > d3 and snap["127.0.0.2"]["dropped"] == d2, "A' dropped, B forwarded")
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
    check(s2b["frames"] > s2["frames"] and s2b["dropped"] == s2["dropped"],
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

    a2.stop.set()
    b2.stop.set()
    a2.join(1.0)
    b2.join(1.0)
    w._disconnect_udp()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed —", "OK" if ok else "FAILED")
    sys.stdout.flush()
    sys.stderr.flush()
    # _exit: skip PPGMonitor.closeEvent so the user's saved window geometry is left untouched.
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
