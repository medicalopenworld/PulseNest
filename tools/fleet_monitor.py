"""Fleet monitor — one line per board, refreshed in the console. Read-only subscriber of the hub.

What the lab shows spread over its log, the MULTI CAPTURE table and udp_fw_versions.py, in one
place and with nothing that can touch a board: this subscriber has no control, so no $SET and no
$MODE can leave it, by construction (spec §4.11). It can run on the bench PC next to the lab, or on
another PC with `--hub <bench-pc-ip>`.

Per board: IP · MAC · board type · fw / lib / build (from the hub's $CFG cache and any live $CFG)
· datagrams/s · frame mode · sample-counter gaps · probe state, RSQI, DiagCode, SpO2, HR1,
V_TIA_LED1/2 (volts, 2 decimals) and RF from the last $M4 · count of $ERR lines · `last`: "live"
while the board spoke within the last 2 s, else the silence in seconds. Below: the hub's own status
(@STATUS: subscribers and who holds the control).

The frame is read the way UdpBoard does in the lab: fields by position after '$' (spec §4.2 —
[0]=mode [1]=SmpCnt ... [10]=SpO2 [14]=HR1 [20]=RSQI [21]=DiagCode [22]=ProbeState [34]=RF1
[35]=RF2). ProbeState is shown by its enumerator name from incunest_afe4490.h (DISCONNECTED,
OT_HIGH, APPLIED, AMB_SATURATING, ONLY_LED_SATURATING). Anything that does not parse is shown as
'?', never raised: a monitor must outlive a malformed line.

    python tools/fleet_monitor.py [--hub IP[:PORT]] [--refresh 1.0]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT          # noqa: E402
from pulsenest_hub_client import HubClient       # noqa: E402

ID_KEYS = ("mac", "board", "fw", "lib", "build")
LOST_S = 2.0
# enum class ProbeState in incunest_afe4490.h, minus the PROBE_ prefix -- the same names the lab
# shows (SIGNAL STATS / OT MONITOR). The first version of this table had invented labels AND the
# numbering shifted by one (2 read "PARTIAL" while the board was saying APPLIED). Never again:
# the label IS the enumerator's name, so a reader can grep it in the library.
PROBE_STATES = {"0": "DISCONNECTED", "1": "OT_HIGH", "2": "APPLIED",
                "3": "AMB_SATURATING", "4": "ONLY_LED_SATURATING"}
PROBE_W = max(len(v) for v in PROBE_STATES.values())


class BoardView:
    def __init__(self, ip):
        self.ip = ip
        self.ident = {}
        self.last_seen = time.monotonic()
        self.dgrams = 0
        self.win_t, self.win_n, self.rate = self.last_seen, 0, 0.0
        self.mode = "?"
        self.last_cnt = None
        self.gaps = 0
        self.errs = 0
        self.last_err = ""
        self.fields = {}      # spo2, hr1, rsqi, diag, probe, rf1, rf2

    def feed(self, data, now):
        self.last_seen = now
        self.dgrams += 1
        self.win_n += 1
        if now - self.win_t >= 2.0:
            self.rate = self.win_n / (now - self.win_t)
            self.win_t, self.win_n = now, 0
        for raw in data.split(b"\n"):
            line = raw.rstrip(b"\r")
            if not line:
                continue
            if line[:1] == b"$" and line[1:3] in (b"M1", b"M2", b"M3", b"M4") and line[3:4] == b",":
                self._data_frame(line)
            elif line.startswith(b"$CFG,"):
                self._cfg(line)
            elif line.startswith(b"$ERR"):
                self.errs += 1
                self.last_err = line.decode("ascii", "replace")[:40]

    def _cfg(self, line):
        for part in line.split(b","):
            k, sep, v = part.partition(b"=")
            if sep:
                k = k.decode("ascii", "replace")
                if k in ID_KEYS:
                    self.ident[k] = v.split(b"*")[0].decode("ascii", "replace")

    def _data_frame(self, line):
        p = line[1:].split(b"*")[0].split(b",")
        self.mode = p[0].decode("ascii", "replace")
        try:
            cnt = int(p[1])
            if self.last_cnt is not None and 0 < cnt - self.last_cnt - 1 <= 5000:
                self.gaps += cnt - self.last_cnt - 1
            self.last_cnt = cnt
        except (ValueError, IndexError):
            pass

        def f(i):
            try:
                return p[i].decode("ascii", "replace")
            except IndexError:
                return "?"

        def volts(i):
            try:
                return f"{float(p[i]):.2f}"
            except (IndexError, ValueError):
                return "?"
        self.fields = {"spo2": f(10), "hr1": f(14), "rsqi": f(20), "diag": f(21),
                       "probe": PROBE_STATES.get(f(22), f(22)),
                       "vtia1": volts(23), "vtia2": volts(24),      # V_TIA_LED1 / V_TIA_LED2, volts
                       "rf1": f(34), "rf2": f(35)}


def render(boards, client, hub, t_start):
    now = time.monotonic()
    out = [f"PulseNest {os.path.basename(__file__)} — hub {hub[0]}:{hub[1]}  ({'connected' if client.connected else 'RECONNECTING'}"
           f", read-only)  up {now - t_start:5.0f} s     {time.strftime('%H:%M:%S')}", ""]
    hdr = (f"{'IP':15s} {'MAC':17s} {'board':12s} {'fw':>5s} {'lib':>5s} {'build':>8s} "
           f"{'dg/s':>5s} {'mode':>4s} {'gaps':>5s} {'probe':>{PROBE_W}s} {'RSQI':>4s} {'diag':>5s} "
           f"{'SpO2':>5s} {'HR1':>6s} {'V_TIA1':>6s} {'V_TIA2':>6s} {'RF1/RF2':>10s} {'ERR':>3s} {'last':>5s}")
    out.append(hdr)
    out.append("-" * len(hdr))
    for b in sorted(boards.values(), key=lambda x: x.ip):
        silence = now - b.last_seen
        state = f"{silence:4.0f}s" if silence > LOST_S else "live"
        i, fl = b.ident, b.fields
        out.append(f"{b.ip:15s} {i.get('mac', '?'):17s} {i.get('board', '?')[:12]:12s} "
                   f"{i.get('fw', '?'):>5s} {i.get('lib', '?'):>5s} {i.get('build', '?')[:8]:>8s} "
                   f"{b.rate:5.0f} {b.mode:>4s} {b.gaps:5d} {fl.get('probe', '?'):>{PROBE_W}s} "
                   f"{fl.get('rsqi', '?'):>4s} {fl.get('diag', '?'):>5s} {fl.get('spo2', '?'):>5s} "
                   f"{fl.get('hr1', '?'):>6s} {fl.get('vtia1', '?'):>6s} {fl.get('vtia2', '?'):>6s} "
                   f"{(fl.get('rf1', '?') + '/' + fl.get('rf2', '?')):>10s} "
                   f"{b.errs:3d} {state:>5s}")
    if not boards:
        out.append("(no board seen yet)")
    out.append("")
    if client.last_status:
        for line in client.last_status.splitlines()[1:]:
            if line.startswith(("hub ", "sub ")):
                out.append("  " + line)
    if boards and any(b.last_err for b in boards.values()):
        out.append("")
        for b in boards.values():
            if b.last_err:
                out.append(f"  last $ERR {b.ip}: {b.last_err}")
    return "\n".join(out)


class Screen:
    """Redraw in place instead of clearing the console. `cls` spawns a shell, wipes the whole
    screen and then the text is printed: that blank instant, once a second, is the flicker. Here
    the cursor goes home, every line erases its own tail (\\x1b[K), whatever is left below is
    erased once (\\x1b[J), and the whole frame goes out in a single write."""

    def __init__(self):
        self.enabled = self._enable_vt()
        if self.enabled:
            sys.stdout.write("\x1b[?25l\x1b[2J\x1b[H")     # hide cursor, clear once, home
            sys.stdout.flush()

    @staticmethod
    def _enable_vt():
        if os.name != "nt":
            return True
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            h = k32.GetStdHandle(-11)                       # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if not k32.GetConsoleMode(h, ctypes.byref(mode)):
                return False
            return bool(k32.SetConsoleMode(h, mode.value | 0x0004))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False

    def draw(self, text):
        if not self.enabled:                                # not a VT console (or a pipe): plain frames
            if sys.stdout.isatty():
                os.system("cls" if os.name == "nt" else "clear")
            print(text)
            sys.stdout.flush()
            return
        sys.stdout.write("\x1b[H" + "\x1b[K\n".join(text.split("\n")) + "\x1b[K\x1b[J")
        sys.stdout.flush()

    def close(self):
        if self.enabled:
            sys.stdout.write("\x1b[?25h\n")                 # cursor back
            sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--refresh", type=float, default=1.0, help="seconds between screen refreshes")
    args = ap.parse_args()
    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    client = HubClient("fleet_monitor", hub=hub, control=False, log=lambda m: None)
    client.connect()
    boards = {}
    t_start = time.monotonic()
    next_draw = next_status = 0.0
    screen = Screen()
    try:
        while True:
            item = client.recv(0.1)
            now = time.monotonic()
            if item is not None:
                ip, data = item
                b = boards.get(ip)
                if b is None:
                    b = boards[ip] = BoardView(ip)
                b.feed(data, now)
            if now >= next_status:
                next_status = now + 5.0
                client.request_status()
            if now >= next_draw:
                next_draw = now + args.refresh
                screen.draw(render(boards, client, hub, t_start))
    except KeyboardInterrupt:
        pass
    finally:
        screen.close()
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
