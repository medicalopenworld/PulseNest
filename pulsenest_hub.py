"""PulseNest hub -- owns the host's UDP data port and fans the boards' stream out to subscribers.

Why it exists. A UDP unicast datagram is delivered to exactly one socket, and the boards send
everything to one compiled IP (wifi_config.h). So only one program on the bench PC could ever
read the stream, and every bench tool had to be run with pulsenest_lab.py closed. The hub is that
one program: it binds UDP_DATA_PORT, and re-sends every datagram, byte for byte, to whoever asked.
The air does not change (the boards keep one stream over WiFi); the copies travel over loopback or
the wired side of the PC, which is free. Running on the PC that straddles the hotspot and the LAN,
it is also the only place from which a second PC can be served without spending hotspot air.

What it deliberately is not. It has no GUI and no third-party dependency (stdlib only), and it
does NOT interpret the frames: it looks at the first byte, prepends the origin, and forwards.
Nothing here converts a number, so a malformed frame cannot raise. The single exception is the
configuration cache, which keeps the last $CFG/$TCFG/$LCFG line of each board AS TEXT (prefix
match only) so that a late subscriber learns the board identities without putting a byte on the
air. It is meant to be the most boring process on the machine.

Two planes on ONE socket, told apart by the first byte:

    '$', '#', ...   board plane, unchanged: a datagram from a board. Forwarded to subscribers.
    '@'             hub plane: a subscriber talking to the hub. One message per datagram, ASCII,
                    first line = verb + arguments, the rest of the datagram = payload (for @TO).

Subscriber -> hub                     Hub -> subscriber
    @SUB <name>                           @OK SUB            then the cache: @FROM lines (below)
    @CTRL <name>                          @OK CTRL   |  @REFUSED CTRL <holder> <since>
    @PING                                 @PONG boards=<n> subs=<n> ctrl=<name|-> up=<s>
    @STATUS                               @STATUS\\r\\n<one line per board and subscriber>
    @TO <ip>\\r\\n<payload>                 (payload -> <ip>:UDP_CMD_PORT) | @REFUSED TO <reason>
    @RELEASE                              @OK RELEASE
    @UNSUB                                (nothing)
    @STOP                                 @OK STOP  |  @REFUSED STOP local-only
                                          @FROM <ip>\\r\\n<original datagram, verbatim>

Rules.
- A subscriber is known by the source address of its messages; the hub answers THERE, from its
  own socket, so the subscriber needs no well-known port and a remote PC's firewall sees plain
  UDP replies to its own outbound traffic. A subscriber that stops pinging for SUB_EXPIRE_S is
  forgotten.
- Exactly ONE controller at a time. @TO is forwarded only for the controller; everyone else is
  read-only by construction. Control is granted if nobody holds it or the holder expired, and
  only to a local address unless --allow-remote-control is given: writing to a medical device
  from another machine must be a deliberate choice, never the default.
- The hub itself only ever asks a board for its identity: "$CFG?" when it first sees a board
  IP, and again when that board comes back after BOARD_LOST_S of silence (it may have rebooted
  into a new build -- an OTA is routine here). The query is UDP and can be lost, so it is
  retried every CFG_RETRY_S up to CFG_MAX_REQUESTS times *until the board answers*, and not
  once more: without a $CFG the subscribers have no MAC, and a subscriber that keys its rows by
  MAC (fleet_monitor) cannot tell a board back on a new DHCP lease from a second board. Nothing
  else is ever sent to a board.
- Datagram boundaries are preserved: what the board sent as one datagram, the subscriber gets as
  one datagram (with the @FROM line in front). pulsenest_lab.py's batching invariant depends on it.
- No SO_REUSEADDR. Two hubs must not "coexist" with one of them silently receiving nothing
  (measured 2026-09-10); the second bind must FAIL, loudly.
- A slow or dead subscriber is dropped by expiry; sendto() never blocks on UDP, so it cannot
  stall the loop. On Windows an ICMP port-unreachable surfaces as an OSError on the socket: it is
  caught and ignored, the loop goes on.

Run it by hand for the log on the console, or let a subscriber start it (pulsenest_hub_client
launches it detached, with python.exe so a `taskkill /IM pythonw.exe` of the lab leaves it alive):

    python pulsenest_hub.py [--port 5005] [--allow-remote-control] [--idle-exit-min 5]
    python pulsenest_hub.py --stop          # ask the running one to exit

--stop exists because the running hub is detached and has no window: there is no Ctrl+C and no
console to close, and `taskkill /IM python.exe` would take the monitor and every tool with it.
It sends @STOP over the data port, which only a local address may use -- deliberately NOT opened
by --allow-remote-control, a flag about commanding boards; whoever administers the bench PC has
a shell on it already.

It shuts itself down after DEFAULT_IDLE_EXIT_MIN minutes with nobody subscribed (2026-09-18: the
auto-started hub had no exit path at all and one instance ran for 34+ hours after everyone using
it was gone; --idle-exit-min 0 disables this and runs forever, as before).
"""
import argparse
import logging
import logging.handlers
import os
import select
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pulsenest_net import UDP_DATA_PORT, UDP_CMD_PORT, banner, script_name  # noqa: E402

HUB_SIGIL      = b"@"
PING_S         = 2.0     # what a subscriber is expected to send (pulsenest_hub_client does)
SUB_EXPIRE_S   = 10.0    # a subscriber silent for this long is forgotten (and loses control)
BOARD_LOST_S   = 2.0     # a board silent for this long is LOST: @STATUS says so, and on its
                         # return the hub replays its cache and asks $CFG? again
CFG_RETRY_S    = 3.0     # gap between identity queries to a board that has not answered yet
CFG_MAX_REQUESTS = 3     # ... and how many times in total, per appearance
CFG_PREFIXES   = (b"$CFG,", b"$TCFG,", b"$LCFG,")
RATE_WINDOW_S  = 2.0     # datagram rate window for @STATUS
DEFAULT_IDLE_EXIT_MIN = 5.0   # the CLI's --idle-exit-min default (Hub.__init__'s own default
                              # stays 0 = never, so a test that builds a Hub() directly is
                              # unaffected): the auto-started hub inherits this by not passing
                              # the flag at all, and Alex found one that had been left running
                              # 34+ hours with nobody subscribed -- nothing was watching for that
LOG_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulsenest_hub.log")

log = logging.getLogger("pulsenest_hub")


def _local_addresses():
    """Every IP that means 'this machine', so a subscriber talking to the hub through the LAN
    address of the same PC still counts as local for control."""
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return ips


def is_loopback(ip):
    return ip.startswith("127.")


class Board:
    """One source IP that sent board-plane datagrams."""
    __slots__ = ("ip", "first_seen", "last_seen", "datagrams", "bytes", "cfg", "cfg_requests",
                 "cfg_last_req", "_win_t", "_win_n", "rate")

    def __init__(self, ip, now):
        self.ip = ip
        self.first_seen = self.last_seen = now
        self.datagrams = 0
        self.bytes = 0
        self.cfg = {}            # prefix -> last raw line (bytes, no line ending)
        self.cfg_requests = 0    # identity queries sent for this appearance (see CFG_MAX_REQUESTS)
        self.cfg_last_req = 0.0
        self._win_t, self._win_n, self.rate = now, 0, 0.0

    def seen(self, now, nbytes):
        self.last_seen = now
        self.datagrams += 1
        self.bytes += nbytes
        self._win_n += 1
        if now - self._win_t >= RATE_WINDOW_S:
            self.rate = self._win_n / (now - self._win_t)
            self._win_t, self._win_n = now, 0

    def cache_cfg(self, data):
        """Keep the last $CFG/$TCFG/$LCFG line. Prefix match only; the text is never read."""
        if not any(p[:1] in data for p in (b"$",)):
            return
        for line in data.split(b"\n"):
            line = line.rstrip(b"\r")
            for p in CFG_PREFIXES:
                if line.startswith(p):
                    self.cfg[p] = line
                    break


class Subscriber:
    __slots__ = ("addr", "name", "joined", "last_seen", "sent", "is_controller")

    def __init__(self, addr, name, now):
        self.addr = addr
        self.name = name
        self.joined = self.last_seen = now
        self.sent = 0
        self.is_controller = False

    def label(self):
        return f"{self.addr[0]}:{self.addr[1]} {self.name}"


class Hub:
    """The hub proper. Usable in-process (tests start one on a spare port in a thread) or as the
    process run by main()."""

    def __init__(self, port=UDP_DATA_PORT, bind_ip="", allow_remote_control=False,
                 idle_exit_s=0.0, cmd_port=UDP_CMD_PORT):
        self.port = port
        self.bind_ip = bind_ip
        self.cmd_port = cmd_port
        self.allow_remote_control = allow_remote_control
        self.idle_exit_s = idle_exit_s
        self.sock = None
        self.boards = {}        # ip -> Board
        self.subs = {}          # (ip, port) -> Subscriber
        self.controller = None  # (ip, port) or None
        self.ctrl_since = None
        self.started = None
        self.local_ips = _local_addresses()
        self._stop = threading.Event()
        self._idle_since = None
        # counters for @STATUS / log
        self.n_board_dgrams = 0
        self.n_fanout = 0
        self.n_refused = 0
        self.n_sock_errors = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────
    def open(self):
        """Bind the data port. Raises OSError (EADDRINUSE / WSAEADDRINUSE 10048) if taken --
        that is the desired behaviour, see the module docstring."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        s.bind((self.bind_ip, self.port))
        s.setblocking(False)
        self.sock = s
        self.started = time.monotonic()
        log.info("%s listening on :%d (commands to boards on :%d, remote control %s, "
                 "idle exit %s)", script_name(__file__), self.port, self.cmd_port,
                 "ALLOWED" if self.allow_remote_control else "local only",
                 f"after {self.idle_exit_s:.0f}s" if self.idle_exit_s > 0 else "disabled")

    def stop(self):
        self._stop.set()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def serve_forever(self):
        """The loop. One select() per iteration, housekeeping every ~0.5 s."""
        if self.sock is None:
            self.open()
        next_house = time.monotonic() + 0.5
        try:
            while not self._stop.is_set():
                try:
                    r, _, _ = select.select([self.sock], [], [], 0.5)
                except (OSError, ValueError):
                    break
                now = time.monotonic()
                if r:
                    # Drain everything queued: at 100 datagrams/s per board a select() per
                    # datagram would be wasteful, and recvfrom on a non-blocking socket is cheap.
                    for _ in range(256):
                        try:
                            data, addr = self.sock.recvfrom(65535)
                        except BlockingIOError:
                            break
                        except OSError as exc:
                            # Windows: ICMP port unreachable from a dead subscriber lands here as
                            # WSAECONNRESET. Not fatal; expiry will drop that subscriber.
                            self.n_sock_errors += 1
                            log.debug("socket error on recv: %s", exc)
                            break
                        if data[:1] == HUB_SIGIL:
                            self._on_hub_message(addr, data, now)
                        else:
                            self._on_board_datagram(addr, data, now)
                if now >= next_house:
                    next_house = now + 0.5
                    if self._housekeeping(now):
                        break
        finally:
            self.close()
            log.info("hub stopped")

    # ── board plane ───────────────────────────────────────────────────────────────────────────
    def _on_board_datagram(self, addr, data, now):
        ip = addr[0]
        b = self.boards.get(ip)
        if b is None:
            b = self.boards[ip] = Board(ip, now)
            log.info("board %s seen for the first time — asking $CFG?", ip)
            self._ask_cfg(b, now)
        elif now - b.last_seen > BOARD_LOST_S:
            # Back after a silence. Two things: subscribers that joined meanwhile never got this
            # board's configuration (the join replay covers live boards only), so hand out what
            # we have; and a board that went away may have rebooted with a new build (an OTA is
            # routine on this bench), so ask it once more — the fresh $CFG refreshes the cache
            # and reaches everyone as live traffic.
            log.info("board %s back after %.0f s — replaying its configuration, asking $CFG? again",
                     ip, now - b.last_seen)
            for sub in list(self.subs.values()):
                self._replay_board(sub.addr, b)
            b.cfg_requests = 0
            self._ask_cfg(b, now)
        b.seen(now, len(data))
        b.cache_cfg(data)
        self.n_board_dgrams += 1
        if self.subs:
            self._fanout(ip, data)

    def _ask_cfg(self, b, now):
        """Ask this board who it is. Bounded: CFG_MAX_REQUESTS per appearance, and only while it
        has not answered -- the reply is cached, so one good answer ends the queries."""
        b.cfg_requests += 1
        b.cfg_last_req = now
        self._send((b.ip, self.cmd_port), b"$CFG?\n")

    def _fanout(self, ip, data):
        payload = b"@FROM " + ip.encode("ascii") + b"\r\n" + data
        for sub in list(self.subs.values()):
            if self._send(sub.addr, payload):
                sub.sent += 1
                self.n_fanout += 1

    # ── hub plane ─────────────────────────────────────────────────────────────────────────────
    def _on_hub_message(self, addr, data, now):
        head, _, rest = data.partition(b"\n")
        parts = head.rstrip(b"\r").split()
        verb = parts[0][1:].upper() if parts else b""
        args = parts[1:]
        sub = self.subs.get(addr)
        if sub is not None:
            sub.last_seen = now

        if verb == b"PING":
            if sub is not None:
                self._send(addr, self._pong())
            else:
                # A ping from someone we forgot (expired, or hub restarted): tell it so it
                # re-subscribes instead of waiting for frames that will never come.
                self._send(addr, b"@REFUSED PING not-subscribed\r\n")
        elif verb in (b"SUB", b"CTRL"):
            name = (args[0].decode("ascii", "replace") if args else "?")[:32]
            if sub is None:
                sub = self.subs[addr] = Subscriber(addr, name, now)
                log.info("subscriber %s joined (%s)", sub.label(), verb.decode())
            else:
                sub.name = name
            if verb == b"CTRL":
                self._grant_control(sub, now)
            else:
                self._send(addr, b"@OK SUB\r\n")
            self._replay_cache(addr)
        elif verb == b"TO":
            self._forward_command(addr, sub, args, rest)
        elif verb == b"RELEASE":
            if self.controller == addr:
                self._release_control("released by the controller")
            self._send(addr, b"@OK RELEASE\r\n")
        elif verb == b"UNSUB":
            if sub is not None:
                self._forget(addr, "unsubscribed")
        elif verb == b"STATUS":
            self._send(addr, self.status_text().encode("utf-8", "replace"))
        elif verb == b"STOP":
            # `python pulsenest_hub.py --stop`. The process is detached and has no window, so
            # without this the only way to stop it was hunting its PID by command line — the
            # kind of incantation nobody remembers. LOCALHOST ONLY, and deliberately not opened
            # up by --allow-remote-control: that flag is about commanding boards, and whoever
            # administers the bench PC already has a shell on it.
            if addr[0] in self.local_ips or is_loopback(addr[0]):
                log.info("stop requested by %s:%d — exiting", addr[0], addr[1])
                self._send(addr, b"@OK STOP\r\n")
                self._stop.set()
            else:
                self.n_refused += 1
                self._send(addr, b"@REFUSED STOP local-only\r\n")
                log.info("stop refused to %s:%d (not local)", addr[0], addr[1])
        else:
            self._send(addr, b"@REFUSED " + (parts[0] if parts else b"?")[:16] + b" unknown-verb\r\n")

    def _grant_control(self, sub, now):
        addr = sub.addr
        if self.controller is not None and self.controller != addr:
            holder = self.subs.get(self.controller)
            if holder is not None and now - holder.last_seen <= SUB_EXPIRE_S:
                self.n_refused += 1
                since = time.strftime("%H:%M:%S", time.localtime(self.ctrl_since))
                self._send(addr, f"@REFUSED CTRL {holder.name} {since}\r\n".encode("ascii", "replace"))
                log.info("control refused to %s: held by %s since %s", sub.label(), holder.name, since)
                return
            self._release_control("holder expired")
        if not self.allow_remote_control and addr[0] not in self.local_ips and not is_loopback(addr[0]):
            self.n_refused += 1
            self._send(addr, b"@REFUSED CTRL remote-control-disabled\r\n")
            log.info("control refused to %s: remote control is disabled", sub.label())
            return
        if self.controller != addr:
            self.controller = addr
            self.ctrl_since = time.time()
            sub.is_controller = True
            log.info("control granted to %s", sub.label())
        self._send(addr, b"@OK CTRL\r\n")

    def _release_control(self, why):
        if self.controller is None:
            return
        holder = self.subs.get(self.controller)
        if holder is not None:
            holder.is_controller = False
        log.info("control released (%s): was %s", why, holder.label() if holder else self.controller)
        self.controller = None
        self.ctrl_since = None

    def _forward_command(self, addr, sub, args, payload):
        if sub is None or self.controller != addr:
            self.n_refused += 1
            self._send(addr, b"@REFUSED TO not-controller\r\n")
            return
        if not args:
            self._send(addr, b"@REFUSED TO missing-ip\r\n")
            return
        ip = args[0].decode("ascii", "replace")
        if not payload:
            self._send(addr, b"@REFUSED TO empty-payload\r\n")
            return
        self._send((ip, self.cmd_port), payload)

    def _replay_cache(self, addr):
        """A new subscriber gets the last configuration lines of every LIVE board, wrapped exactly
        like live traffic, so its normal parser learns the identities with no special case. A
        board silent for more than BOARD_LOST_S is left out: handing a newcomer the identity of a
        board that is not there would let it pick a dead board as its source. Its configuration
        is replayed to everyone the moment it speaks again (_on_board_datagram)."""
        now = time.monotonic()
        for b in sorted(self.boards.values(), key=lambda x: x.first_seen):
            if now - b.last_seen <= BOARD_LOST_S:
                self._replay_board(addr, b)

    def _replay_board(self, addr, b):
        for p in CFG_PREFIXES:
            line = b.cfg.get(p)
            if line is not None:
                self._send(addr, b"@FROM " + b.ip.encode("ascii") + b"\r\n" + line + b"\r\n")

    def _pong(self):
        ctrl = self.subs.get(self.controller).name if self.controller in self.subs else "-"
        up = time.monotonic() - self.started if self.started else 0.0
        return (f"@PONG boards={len(self.boards)} subs={len(self.subs)} ctrl={ctrl} up={up:.0f}\r\n"
                .encode("ascii", "replace"))

    def status_text(self):
        now = time.monotonic()
        lines = ["@STATUS", f"hub file={script_name(__file__)} port={self.port} "
                            f"up={now - (self.started or now):.0f}s "
                            f"board_dgrams={self.n_board_dgrams} fanout={self.n_fanout} "
                            f"refused={self.n_refused} sock_errors={self.n_sock_errors}"]
        for b in sorted(self.boards.values(), key=lambda x: x.first_seen):
            silence = now - b.last_seen
            state = "LOST" if silence > BOARD_LOST_S else "live"
            lines.append(f"board {b.ip} {state} last={silence:.1f}s dgram/s={b.rate:.0f} "
                         f"dgrams={b.datagrams} cfg={'yes' if b.cfg.get(b'$CFG,') else 'no'}")
        for s in sorted(self.subs.values(), key=lambda x: x.joined):
            lines.append(f"sub {s.addr[0]}:{s.addr[1]} {s.name} ctrl={int(s.is_controller)} "
                         f"last={now - s.last_seen:.1f}s sent={s.sent}")
        return "\r\n".join(lines) + "\r\n"

    # ── housekeeping ──────────────────────────────────────────────────────────────────────────
    def _housekeeping(self, now):
        """Retry unanswered identity queries; expire silent subscribers; idle exit.
        Returns True when the hub should exit."""
        for b in self.boards.values():
            if (not b.cfg.get(b"$CFG,") and b.cfg_requests < CFG_MAX_REQUESTS
                    and now - b.last_seen <= BOARD_LOST_S
                    and now - b.cfg_last_req > CFG_RETRY_S):
                log.info("board %s has not answered $CFG? (%d) — asking again", b.ip, b.cfg_requests)
                self._ask_cfg(b, now)
        for addr, s in list(self.subs.items()):
            if now - s.last_seen > SUB_EXPIRE_S:
                self._forget(addr, f"silent for {now - s.last_seen:.0f} s")
        if self.idle_exit_s > 0:
            if self.subs:
                self._idle_since = None
            elif self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since > self.idle_exit_s:
                log.info("no subscribers for %.0f s — idle exit", self.idle_exit_s)
                return True
        return False

    def _forget(self, addr, why):
        s = self.subs.pop(addr, None)
        if s is None:
            return
        if self.controller == addr:
            self._release_control(why)
        log.info("subscriber %s left (%s)", s.label(), why)

    def _send(self, addr, payload):
        try:
            self.sock.sendto(payload, addr)
            return True
        except OSError as exc:
            self.n_sock_errors += 1
            log.debug("sendto %s failed: %s", addr, exc)
            return False


# ── process entry point ───────────────────────────────────────────────────────────────────────
def _setup_logging(quiet):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if not quiet and sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def stop_running_hub(port, timeout=1.5):
    """Ask the hub on `port` to exit. -> (stopped, reply): `reply` is None when nothing answered.

    The two failures are told apart on purpose. "Nobody answered" and "something answered and
    said no" look the same from the caller's side if you only return a bool, and the first
    version of this did exactly that: run against a hub started before @STOP existed, it
    reported "no hub answered" while a hub was plainly running and had in fact replied
    @REFUSED STOP unknown-verb. A message that denies what the user can see is worse than none.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(b"@STOP\r\n", ("127.0.0.1", port))
        data, _ = s.recvfrom(1024)
        return data.startswith(b"@OK STOP"), data.split(b"\r\n")[0].decode("ascii", "replace")
    except OSError:
        return False, None    # nobody listening, or it died before replying
    finally:
        s.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="PulseNest hub: owns the UDP data port, fans the "
                                             "boards' stream out to read-only subscribers")
    ap.add_argument("--stop", action="store_true",
                    help="tell the hub running on this machine to exit, and exit")
    ap.add_argument("--port", type=int, default=UDP_DATA_PORT, help="data port to own (default %(default)s)")
    ap.add_argument("--allow-remote-control", action="store_true",
                    help="let a subscriber on ANOTHER machine become the controller (default: local only)")
    ap.add_argument("--idle-exit-min", type=float, default=DEFAULT_IDLE_EXIT_MIN,
                    help="exit after this many minutes without subscribers "
                         "(default %(default)s; 0 = never)")
    ap.add_argument("--quiet", action="store_true", help="log to file only")
    a = ap.parse_args(argv)
    _setup_logging(a.quiet)
    if a.stop:
        stopped, reply = stop_running_hub(a.port)
        if stopped:
            print(banner(__file__, f"the hub on :{a.port} was asked to stop, and acknowledged"))
            return 0
        if reply is None:
            print(banner(__file__, f"no hub answered on :{a.port} — nothing to stop"))
        else:
            print(banner(__file__, f"a hub on :{a.port} answered but did not stop: {reply}"))
            if "unknown-verb" in reply:
                print("  It was started before --stop existed. Stop it once by PID and the next "
                      "one will understand:\n"
                      "    Get-CimInstance Win32_Process -Filter \"name='python.exe'\" |\n"
                      "      Where-Object { $_.CommandLine -match 'pulsenest_hub' } |\n"
                      "      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        return 1
    if not a.quiet:
        print(banner(__file__, f"owns UDP :{a.port}, fans the boards' stream out to subscribers"))
    hub = Hub(port=a.port, allow_remote_control=a.allow_remote_control,
              idle_exit_s=a.idle_exit_min * 60.0)
    try:
        hub.open()
    except OSError as exc:
        # 10048 (Windows) / 98 (Linux): the port is taken. Loud and specific, on purpose.
        log.error("cannot bind :%d — %s. Another hub, or a tool binding the data port directly "
                  "(an old pulsenest_lab.py?), owns it.", a.port, exc)
        return 2
    try:
        hub.serve_forever()
    except KeyboardInterrupt:
        hub.stop()
        hub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
