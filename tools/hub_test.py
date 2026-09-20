"""In-process test of pulsenest_hub + pulsenest_hub_client on spare loopback ports.

Two fake boards (127.0.0.2 / 127.0.0.3, the addresses tools/udp_multiboard_test.py uses), a hub
on :15105, a controller client and a read-only client. Checks the contract the lab and the tools
will rely on: origin tagging, datagram boundaries, cache replay, single controller, read-only
enforcement, liveness (ping/pong), expiry, auxiliary sources ($VN1: forwarded, never queried,
labelled `aux`), and the hub's bounded identity query ($CFG?, retried
while unanswered).
No real bench involved; run any time:

    python tools/hub_test.py
"""
import os
import socket
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import pulsenest_hub as H          # noqa: E402
import pulsenest_hub_client as C   # noqa: E402

DATA_PORT, CMD_PORT = 15105, 15106
C.AUTOSTART_ENABLED = False
H.SUB_EXPIRE_S = 1.5          # fast expiry for the test
H.CFG_RETRY_S = 0.3           # fast identity retry for the test
C.PING_S = 0.3
C.MAX_MISSED_PONGS = 3

CRLF = (chr(13) + chr(10)).encode()

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


class FakeBoard(threading.Thread):
    def __init__(self, ip, mac, rate_s=0.02, answer_cfg=True):
        super().__init__(daemon=True)
        self.ip, self.mac, self.period = ip, mac, rate_s
        self.answer_cfg = answer_cfg       # False: the board never answers $CFG? (lost datagrams)
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data.bind((ip, 0))
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.bind((ip, CMD_PORT))
        self.cmd.settimeout(0.0)
        self.cnt = 0
        self.cfg_requests = 0
        self.cmds = []
        self.stop = threading.Event()

    def batch(self):
        lines = []
        for _ in range(5):
            self.cnt += 1
            lines.append(f"$M4,{self.cnt},0,1,2,3,4,5,6*00".encode())
        return b"\r\n".join(lines) + b"\r\n"

    def cfg(self):
        return f"$CFG,sr=500,board=fake,mac={self.mac},fw=0.13,lib=0.93,build=test*00\r\n".encode()

    def run(self):
        dst = ("127.0.0.1", DATA_PORT)
        while not self.stop.is_set():
            self.data.sendto(self.batch(), dst)
            try:
                while True:
                    req, _ = self.cmd.recvfrom(256)
                    self.cmds.append(req)
                    if req.strip() == b"$CFG?":
                        self.cfg_requests += 1
                        if self.answer_cfg:
                            self.data.sendto(self.cfg(), dst)
            except (BlockingIOError, OSError):
                pass
            time.sleep(self.period)
        self.data.close()
        self.cmd.close()


def drain(client, seconds):
    """Collect (ip, payload) items for `seconds`."""
    out, t_end = [], time.monotonic() + seconds
    while time.monotonic() < t_end:
        item = client.recv(0.05)
        if item is not None:
            out.append(item)
    return out


def main():
    print(f"== {os.path.basename(__file__)} ==  hub + client, in process, on :{DATA_PORT}")
    hub = H.Hub(port=DATA_PORT, cmd_port=CMD_PORT)
    hub.open()
    hub_thread = threading.Thread(target=hub.serve_forever, daemon=True)
    hub_thread.start()

    a = FakeBoard("127.0.0.2", "AA:AA:AA:AA:AA:02")
    b = FakeBoard("127.0.0.3", "AA:AA:AA:AA:AA:03")
    a.start(); b.start()
    time.sleep(0.6)

    # ── the hub alone: boards registered, one $CFG? each, cache filled ──────────────────────
    check("hub registered both boards", set(hub.boards) == {"127.0.0.2", "127.0.0.3"}, str(set(hub.boards)))
    check("hub asked each board $CFG? exactly once", (a.cfg_requests, b.cfg_requests) == (1, 1),
          f"{a.cfg_requests},{b.cfg_requests}")
    check("hub cached a $CFG line per board",
          all(bd.cfg.get(b"$CFG,") for bd in hub.boards.values()))
    check("hub forwarded nothing while nobody subscribed", hub.n_fanout == 0, str(hub.n_fanout))

    # ── controller joins ───────────────────────────────────────────────────────────────────
    logs = []
    ctrl = C.HubClient("lab", hub=("127.0.0.1", DATA_PORT), control=True, log=logs.append)
    check("controller connects", ctrl.connect())
    check("controller granted", ctrl.controller)
    first = drain(ctrl, 0.5)
    cfgs = [(ip, p) for ip, p in first if p.startswith(b"$CFG,")]
    check("cache replayed to the new subscriber: one $CFG per board, tagged with its IP",
          sorted(ip for ip, _ in cfgs) == ["127.0.0.2", "127.0.0.3"] and len(cfgs) == 2, str(cfgs)[:120])
    data = [(ip, p) for ip, p in first if p.startswith(b"$M4,")]
    check("data forwarded from both boards", {ip for ip, _ in data} == {"127.0.0.2", "127.0.0.3"})
    check("datagram boundaries preserved: 5 lines per forwarded datagram",
          all(p.count(b"\r\n") == 5 for _, p in data), str([p.count(b"\r\n") for _, p in data][:8]))
    check("payload is byte-identical to what the board sent (starts with $M4, ends with CRLF)",
          all(p.startswith(b"$M4,") and p.endswith(b"\r\n") for _, p in data))

    # ── controller writes; reader cannot ────────────────────────────────────────────────────
    n0 = len(a.cmds)
    check("controller's command reaches the addressed board only",
          ctrl.send_to_board("127.0.0.2", b"$SET,led1,20*00\r\n") and time.sleep(0.2) is None
          and len(a.cmds) == n0 + 1 and a.cmds[-1] == b"$SET,led1,20*00\r\n"
          and not any(c.startswith(b"$SET") for c in b.cmds), f"a={a.cmds[-1:]}, b={b.cmds[-1:]}")

    rlogs = []
    reader = C.HubClient("monitor", hub=("127.0.0.1", DATA_PORT), control=False, log=rlogs.append)
    check("reader connects", reader.connect())
    check("reader is not controller", not reader.controller)
    rdata = drain(reader, 0.4)
    check("reader receives the same stream", {ip for ip, _ in rdata} == {"127.0.0.2", "127.0.0.3"})
    nb0 = len(b.cmds)
    check("reader's send_to_board is refused client-side", reader.send_to_board("127.0.0.3", b"$SET,x,1\r\n") is False)
    # bypass the client guard: send a raw @TO as a reader — the HUB must refuse it
    reader._send_hub(b"@TO 127.0.0.3\r\n$SET,x,1\r\n")
    drain(reader, 0.3)
    check("hub refuses @TO from a non-controller (board got nothing, client logged the refusal)",
          len(b.cmds) == nb0 and any("command refused" in m for m in rlogs), f"{b.cmds[nb0:]}, {rlogs}")

    # ── second controller refused while the first lives; granted after release ─────────────
    c2logs = []
    ctrl2 = C.HubClient("sweep", hub=("127.0.0.1", DATA_PORT), control=True, log=c2logs.append)
    check("second controller connects (as read-only)", ctrl2.connect() and not ctrl2.controller)
    check("refusal names the holder", ctrl2.control_refused_by is not None and "lab" in (ctrl2.control_refused_by or ""),
          str(ctrl2.control_refused_by))
    ctrl.release_control()
    time.sleep(0.1)
    ctrl2.want_control = True
    check("after release, the second claim is granted", ctrl2._hello(0.5) and ctrl2.controller)
    check("hub sees exactly one controller", sum(s.is_controller for s in hub.subs.values()) == 1)

    # ── liveness: pong bookkeeping; expiry of a silent subscriber releases control ─────────
    drain(ctrl2, 0.8)
    check("pongs arrive (hub alive, last_pong parsed)", ctrl2.hub_alive and ctrl2.last_pong is not None
          and ctrl2.last_pong.get(b"ctrl") == b"sweep", str(ctrl2.last_pong))
    # ctrl2 goes silent (no recv → no pings): the hub must forget it and free the control.
    # ctrl keeps pinging meanwhile (drain calls recv), so it stays subscribed and, having
    # released control, must NOT get it back by itself.
    drain(ctrl, H.SUB_EXPIRE_S + 0.8)
    check("silent subscriber expired and control released", hub.controller is None
          and not any(s.name == "sweep" for s in hub.subs.values())
          and any(s.name == "lab" for s in hub.subs.values()),
          f"ctrl={hub.controller} subs={[s.name for s in hub.subs.values()]}")

    # ── @STATUS ────────────────────────────────────────────────────────────────────────────
    ctrl.request_status()
    drain(ctrl, 0.3)
    st = ctrl.last_status or ""
    check("@STATUS lists both boards and the live subscribers",
          st.startswith("@STATUS") and "board 127.0.0.2" in st and "board 127.0.0.3" in st and "sub " in st, st[:200])

    # ── hub death: client notices via missed pongs and reconnects when it is back ─────────
    hub.stop(); hub_thread.join(2.0)
    t0 = time.monotonic()
    while ctrl.connected and time.monotonic() - t0 < 5.0:
        ctrl.recv(0.1)
    check("client declares the hub dead after missed pongs", not ctrl.connected, f"{time.monotonic()-t0:.1f}s")
    hub2 = H.Hub(port=DATA_PORT, cmd_port=CMD_PORT)
    hub2.open()
    threading.Thread(target=hub2.serve_forever, daemon=True).start()
    t0 = time.monotonic()
    got = []
    while time.monotonic() - t0 < 5.0 and not got:
        item = ctrl.recv(0.2)
        if item is not None and item[1].startswith(b"$M4,"):
            got.append(item)
    check("client reconnects to a new hub and data flows again", bool(got) and ctrl.connected)
    # The boards process their command socket on their own 20 ms loop: give them a moment.
    t0 = time.monotonic()
    while (a.cfg_requests, b.cfg_requests) != (2, 2) and time.monotonic() - t0 < 1.5:
        ctrl.recv(0.05)
    check("new hub asked the boards $CFG? once each again (2 total per board)",
          (a.cfg_requests, b.cfg_requests) == (2, 2), f"{a.cfg_requests},{b.cfg_requests}")

    # ── identity query: retried while unanswered, bounded ─────────────────────────────────
    # Without a $CFG a subscriber has no MAC, and one that keys its rows by MAC (fleet_monitor)
    # cannot tell a board back on a new DHCP lease from a second board. So the query is retried
    # -- and capped, because a board that never answers must not be asked for ever.
    mute = FakeBoard("127.0.0.4", "AA:AA:AA:AA:AA:04", answer_cfg=False)
    mute.start()
    t0 = time.monotonic()
    while mute.cfg_requests < H.CFG_MAX_REQUESTS and time.monotonic() - t0 < 5.0:
        ctrl.recv(0.1)
    check("a board that does not answer $CFG? is asked again, up to the cap",
          mute.cfg_requests == H.CFG_MAX_REQUESTS, f"{mute.cfg_requests} requests")
    n_at_cap = mute.cfg_requests
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.5:
        ctrl.recv(0.1)
    check("and not once more after the cap", mute.cfg_requests == n_at_cap,
          f"{mute.cfg_requests} > {n_at_cap}")
    mute.stop.set()

    # ── @STOP / --stop: the detached hub has no window and no Ctrl+C ──────────────────────
    stop_hub = H.Hub(port=DATA_PORT + 4, cmd_port=CMD_PORT + 4)
    stop_hub.open()
    stop_thread = threading.Thread(target=stop_hub.serve_forever, daemon=True)
    stop_thread.start()
    time.sleep(0.3)

    # A "remote" @STOP must be refused. It cannot be sent over loopback (127.x counts as local),
    # so the handler is driven directly with a non-local address -- the same path a datagram
    # from another machine would take.
    stop_hub._on_hub_message(("8.8.8.8", 1234), b"@STOP" + CRLF, time.monotonic())
    time.sleep(0.2)
    check("@STOP from a non-local address is refused and the hub stays up",
          stop_thread.is_alive() and not stop_hub._stop.is_set())

    stopped, reply = H.stop_running_hub(DATA_PORT + 4)
    check("stop_running_hub() reports the hub acknowledged", stopped and reply == "@OK STOP",
          f"{stopped}, {reply!r}")
    stop_thread.join(2.0)
    check("and the hub really exited", not stop_thread.is_alive())

    stopped, reply = H.stop_running_hub(DATA_PORT + 6, timeout=0.4)
    check("no hub on the port: not stopped, and no reply to report",
          stopped is False and reply is None, f"{stopped}, {reply!r}")

    # The third case, and the one that actually happened: something answers and says no. An
    # older hub does not know @STOP, and reporting that as "nothing answered" denies what the
    # user can see running. Simulated with a plain socket that replies like that hub did.
    import socket as _sock
    old_hub = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
    old_hub.bind(("127.0.0.1", DATA_PORT + 8))

    def _answer_refusal():
        data, peer = old_hub.recvfrom(256)
        old_hub.sendto(b"@REFUSED STOP unknown-verb" + CRLF, peer)

    threading.Thread(target=_answer_refusal, daemon=True).start()
    stopped, reply = H.stop_running_hub(DATA_PORT + 8)
    old_hub.close()
    check("a hub that refuses is reported as refusing, not as absent",
          stopped is False and reply == "@REFUSED STOP unknown-verb", f"{stopped}, {reply!r}")

    # ── idle exit: a hub with idle_exit_s set shuts itself down once nobody is subscribed ──
    # The CLI defaults to this (DEFAULT_IDLE_EXIT_MIN); Hub()'s own default stays 0 (never),
    # so building one directly -- as every check above just did -- is unaffected.
    idle_hub = H.Hub(port=DATA_PORT + 2, cmd_port=CMD_PORT + 2, idle_exit_s=0.3)
    idle_hub.open()
    t0 = time.monotonic()
    idle_hub.serve_forever()  # blocks -- no subscriber ever joins, so idle exit must fire
    check("a hub with idle_exit_s set exits on its own with nobody subscribed",
          time.monotonic() - t0 < 3.0, f"took {time.monotonic() - t0:.2f}s")

    # ── an auxiliary source ($VN1) is forwarded but never queried (D1) ────────────────────
    # VideoNest is a phone doing OCR of the commercial monitor. It has no configuration to give
    # and does not listen on the command port, so a $CFG? aimed at it is noise three times over;
    # and drawing it as a board in fleet_monitor during a campaign is worse than noise.
    class FakePhone(threading.Thread):
        def __init__(self, ip):
            super().__init__(daemon=True)
            self.ip = ip
            self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.data.bind((ip, 0))
            self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.cmd.bind((ip, CMD_PORT))
            self.cmd.settimeout(0.0)
            self.queries = 0
            self.seq = 0
            self.stop = threading.Event()

        def run(self):
            while not self.stop.is_set():
                try:
                    self.cmd.recvfrom(1024)
                    self.queries += 1
                except (BlockingIOError, OSError):
                    pass
                self.seq += 1
                frame = f"$VN1,{self.seq},96,0.91,1790000012000*00".encode() + CRLF   # build 8: no pr
                self.data.sendto(frame, ("127.0.0.1", DATA_PORT))
                time.sleep(0.05)

    phone = FakePhone("127.0.0.5")
    phone.start()
    seen_vn1 = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.5:
        item = reader.recv(0.1)
        if item and item[0] == "127.0.0.5":
            seen_vn1 += 1
    check("an auxiliary source is forwarded to subscribers like any other", seen_vn1 > 5,
          f"{seen_vn1} datagrams")
    check("the hub never sends $CFG? to an auxiliary source", phone.queries == 0,
          f"{phone.queries} queries")
    reader.request_status()
    t0 = time.monotonic()
    while reader.last_status is None and time.monotonic() - t0 < 2.0:
        reader.recv(0.1)
    st = reader.last_status or ""
    check("@STATUS labels it `aux <kind>`, not `board`",
          "aux 127.0.0.5 videonest" in st and "board 127.0.0.5" not in st,
          [l for l in st.splitlines() if "127.0.0.5" in l])
    check("@PONG counts boards and aux apart",
          reader.last_pong and reader.last_pong.get(b"aux") == b"1",
          str(reader.last_pong))
    phone.stop.set()

    # ── no SO_REUSEADDR: a second hub on the same port must fail its bind ──────────────────
    dup = H.Hub(port=DATA_PORT, cmd_port=CMD_PORT)
    try:
        dup.open()
        check("second hub on the same port fails to bind", False, "bind succeeded")
        dup.close()
    except OSError:
        check("second hub on the same port fails to bind", True)

    for x in (ctrl, ctrl2, reader):
        x.close()
    a.stop.set(); b.stop.set()
    hub2.stop()
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} checks passed — {'OK' if n_ok == len(results) else 'FAILURES'}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
