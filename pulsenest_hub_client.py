"""Client side of the PulseNest hub -- subscribe, keep alive, receive tagged datagrams, and
(for the one controller) send commands to boards through the hub.

Shared by every host-side program: pulsenest_lab.py (subscriber + controller), the bench tools
(read-only) and the fleet monitor. Stdlib only. Protocol in pulsenest_hub.py's docstring.

    from pulsenest_hub_client import HubClient
    c = HubClient("udp_fw_versions")              # read-only; HubClient("lab", control=True) to write
    c.connect()                                   # starts a local hub if none answers (see below)
    while True:
        item = c.recv(0.5)                        # (board_ip, datagram_bytes) or None on timeout
        ...
    c.send_to_board("192.168.137.62", b"$CFG?\\n")  # controller only; False when refused
    c.close()

Liveness. The client pings the hub every PING_S from inside recv(); the hub answers @PONG. The
DATA stream is NOT used as a sign of life: boards falling silent is a bench event, the hub dying
is a host event, and the two must never be confused. After MAX_MISSED_PONGS unanswered pings the
hub is declared dead and recv() reconnects on its own (re-subscribing, re-claiming control,
re-launching the hub if allowed). Callers see it as a log line and a short gap.

Auto-start. Only when the hub address is loopback (a hub on a remote PC would be useless: the
boards send to the bench PC) and the port is free. The hub is launched DETACHED with python.exe --
not pythonw.exe -- so the usual `taskkill /F /IM pythonw.exe` that restarts the lab leaves it
alive, and it outlives the program that started it. If two programs race, the second hub fails
its bind and exits; both end up talking to the one that won.

Threads. recv() must be called from ONE thread (the reader). send_to_board() may be called from
any thread: a UDP sendto() is atomic and the socket object tolerates concurrent send/recv.
"""
import os
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pulsenest_net import UDP_DATA_PORT  # noqa: E402

PING_S            = 2.0
MAX_MISSED_PONGS  = 3          # 6 s of silence from the hub = dead
CONNECT_TIMEOUT_S = 1.0        # wait for @OK after @SUB/@CTRL
RECONNECT_EVERY_S = 2.0
HUB_SCRIPT        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulsenest_hub.py")

# Tests flip this off: they start their own Hub on a spare port, in-process.
AUTOSTART_ENABLED = True


def _console_python():
    """python.exe next to whatever runs us (pythonw.exe under the lab), so the detached hub is
    not a pythonw process."""
    exe = sys.executable or "python"
    d, base = os.path.split(exe)
    if base.lower().startswith("pythonw"):
        cand = os.path.join(d, "python" + base[7:])
        if os.path.exists(cand):
            return cand
    return exe


def launch_hub(port=UDP_DATA_PORT, extra_args=()):
    """Start pulsenest_hub.py detached. Returns the Popen (the caller usually ignores it)."""
    cmd = [_console_python(), HUB_SCRIPT, "--port", str(port), "--quiet", *extra_args]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              cwd=os.path.dirname(HUB_SCRIPT), close_fds=True)
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


class HubClient:
    def __init__(self, name, hub=("127.0.0.1", UDP_DATA_PORT), control=False, autostart=True,
                 log=None):
        self.name = str(name)[:32].replace(" ", "_")
        self.hub = (hub[0], int(hub[1]))
        self.want_control = bool(control)
        self.autostart = bool(autostart) and hub[0].startswith("127.")
        self.log = log or (lambda msg: None)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        self.sock.bind(("", 0))                    # any port: the hub answers where we speak from
        self.sock.setblocking(False)
        self.connected = False
        self.controller = False
        self.hub_alive = False
        self.control_refused_by = None             # "name since" text when @CTRL was refused
        self.last_pong = None                      # dict of the last @PONG fields
        self.last_status = None                    # text of the last @STATUS reply
        self.launched = 0                          # how many times we started a hub
        self._last_ping_t = 0.0
        self._missed = 0
        self._next_reconnect = 0.0
        self._lock = threading.Lock()              # guards sendto from several threads (belt)

    # ── connection ────────────────────────────────────────────────────────────────────────────
    def connect(self, timeout=CONNECT_TIMEOUT_S):
        """Subscribe (and claim control if asked). Returns True on @OK. On silence, launches a
        local hub once and retries."""
        if self._hello(timeout):
            return True
        if self.autostart and AUTOSTART_ENABLED:
            self.log(f"[HUB] no hub answering on {self.hub[0]}:{self.hub[1]} — starting one")
            try:
                launch_hub(self.hub[1])
                self.launched += 1
            except OSError as exc:
                self.log(f"[HUB] could not start pulsenest_hub.py: {exc}")
                return False
            # Give it a moment to bind; if the port was held by something that is not a hub, the
            # new hub exits at once and this keeps failing — which is the right diagnosis.
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if self._hello(0.5):
                    return True
            self.log(f"[HUB] started a hub but it does not answer: is :{self.hub[1]} held by a "
                     f"program that is not the hub (an old tool binding the data port)?")
        return False

    def _hello(self, timeout):
        verb = b"@CTRL " if self.want_control else b"@SUB "
        self._send_hub(verb + self.name.encode("ascii", "replace") + b"\r\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._recv_raw(deadline - time.monotonic())
            if msg is None:
                break
            data, addr = msg
            kind = self._handle_control(data)
            if kind in ("ok-sub", "ok-ctrl", "refused-ctrl"):
                self.connected = True
                self.hub_alive = True
                self._missed = 0
                self._last_ping_t = time.monotonic()
                return True
        return False

    def close(self):
        if self.connected:
            self._send_hub(b"@UNSUB\r\n")
        self.connected = self.controller = self.hub_alive = False
        try:
            self.sock.close()
        except OSError:
            pass

    def release_control(self):
        if self.controller:
            self._send_hub(b"@RELEASE\r\n")
            self.controller = False

    # ── receiving ─────────────────────────────────────────────────────────────────────────────
    def recv(self, timeout=0.5):
        """-> (board_ip, datagram) for the next forwarded board datagram, or None after `timeout`.
        Pings, pongs and reconnection happen in here."""
        now = time.monotonic()
        if not self.connected:
            if now >= self._next_reconnect:
                self._next_reconnect = now + RECONNECT_EVERY_S
                if self.connect(0.5):
                    self.log(f"[HUB] connected to {self.hub[0]}:{self.hub[1]}"
                             + (" as controller" if self.controller else " read-only"))
                    return None
            time.sleep(min(timeout, 0.2))
            return None
        if now - self._last_ping_t >= PING_S:
            self._ping(now)
        deadline = now + timeout
        while True:
            remaining = deadline - time.monotonic()
            msg = self._recv_raw(max(0.0, remaining))
            if msg is None:
                return None
            data, addr = msg
            if data.startswith(b"@FROM "):
                head, _, payload = data.partition(b"\n")
                ip = head[6:].rstrip(b"\r").decode("ascii", "replace")
                return ip, payload
            self._handle_control(data)
            if remaining <= 0:
                return None

    def _ping(self, now):
        if self._missed >= MAX_MISSED_PONGS:
            self.log(f"[HUB] hub at {self.hub[0]}:{self.hub[1]} stopped answering — reconnecting")
            self.connected = self.controller = self.hub_alive = False
            self._missed = 0
            self._next_reconnect = 0.0
            return
        self._send_hub(b"@PING\r\n")
        self._missed += 1        # cleared by the @PONG
        self._last_ping_t = now

    def _handle_control(self, data):
        """Hub-plane replies. Returns a short kind string for the callers that care."""
        head = data.split(b"\n", 1)[0].rstrip(b"\r")
        parts = head.split()
        if not parts:
            return "?"
        verb = parts[0]
        if verb == b"@PONG":
            self._missed = 0
            self.hub_alive = True
            self.last_pong = dict(p.split(b"=", 1) for p in parts[1:] if b"=" in p)
            return "pong"
        if verb == b"@OK":
            what = parts[1] if len(parts) > 1 else b""
            if what == b"CTRL":
                self.controller = True
                self.control_refused_by = None
                return "ok-ctrl"
            if what == b"SUB":
                return "ok-sub"
            return "ok"
        if verb == b"@REFUSED":
            what = parts[1] if len(parts) > 1 else b""
            if what == b"CTRL":
                self.controller = False
                self.control_refused_by = b" ".join(parts[2:]).decode("ascii", "replace")
                self.log(f"[HUB] control refused: held by {self.control_refused_by}")
                return "refused-ctrl"
            if what == b"PING":
                # The hub forgot us (it restarted, or we were silent too long): re-subscribe.
                self.connected = self.controller = False
                self._next_reconnect = 0.0
                return "refused-ping"
            if what == b"TO":
                self.log(f"[HUB] command refused: {b' '.join(parts[2:]).decode('ascii', 'replace')}")
                return "refused-to"
            return "refused"
        if verb == b"@STATUS":
            self.last_status = data.decode("utf-8", "replace")
            return "status"
        return "?"

    # ── sending ───────────────────────────────────────────────────────────────────────────────
    def send_to_board(self, ip, data):
        """Controller only. Returns False (and logs once per refusal) when not the controller."""
        if not self.controller:
            return False
        return self._send_hub(b"@TO " + ip.encode("ascii", "replace") + b"\r\n" + data)

    def request_status(self):
        """Ask for @STATUS; the reply shows up in `last_status` after the next recv() calls."""
        self.last_status = None
        return self._send_hub(b"@STATUS\r\n")

    def _send_hub(self, payload):
        try:
            with self._lock:
                self.sock.sendto(payload, self.hub)
            return True
        except OSError as exc:
            self.log(f"[HUB] sendto hub failed: {exc}")
            return False

    def _recv_raw(self, timeout):
        import select
        try:
            r, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        except (OSError, ValueError):
            return None
        if not r:
            return None
        try:
            return self.sock.recvfrom(65535)
        except BlockingIOError:
            return None
        except OSError:
            # Windows: ICMP unreachable (hub gone) surfaces here. Treated as silence; the
            # ping/pong logic decides.
            return None


if __name__ == "__main__":
    # The only file in the repository root that is imported and never run. Rather than rename it
    # (a `_lib` suffix is not a Python idiom, and `_client` already says what it is), it answers
    # the question itself when someone tries.
    print(__doc__.split("\n\n")[0])
    print("\nThis is a LIBRARY: import it, do not run it.\n"
          "  the hub itself        python pulsenest_hub.py      (usually started by the first client)\n"
          "  a read-only viewer    python tools/fleet_monitor.py\n"
          "  the versions report   python tools/udp_fw_versions.py\n"
          "  the lab               start pythonw pulsenest_lab.py\n"
          "  the ports in use      python pulsenest_net.py")
    sys.exit(2)
