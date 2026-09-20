"""Fleet monitor — one line per board, refreshed in the console. Read-only subscriber of the hub.

What the lab shows spread over its log, the MULTI CAPTURE table and udp_fw_versions.py, in one
place and with nothing that can touch a board: this subscriber has no control, so no $SET and no
$MODE can leave it, by construction (spec §4.11). It can run on the bench PC next to the lab, or on
another PC with `--hub <bench-pc-ip>`.

Per board: IP · MAC · board type · fw / lib / build (from the hub's $CFG cache and any live $CFG)
· datagrams/s · frame mode · sample-counter gaps · probe state, RSQI, DiagCode, SpO2, HR1, HR2,
HR3, and RFn/TIAn (each gain resistor next to the TIA voltage it produced) from the last $M4
· `elfsha`: the first 8 hex of the image's own SHA-256, the one field here that says whether two
boards run the same BINARY (`build` is a commit, and commits move for reasons that never reach
the chip)
· count of $ERR lines · `last`: "live" while the board spoke within the last 2 s, else the silence
in seconds. Below: the hub's own status (@STATUS) -- one row per hub and per subscriber, each
labelled by role ("hub" / "subscriber") and by the file actually running it (e.g.
"pulsenest_hub.py", "pulsenest_lab.py"), never by its position in the list.

Columns are kept narrow so there is room to add more: the IP shows its last two octets with the
common prefix in the header (full addresses when the boards are not on one subnet), the MAC its
last three octets, the probe state a shortened but never mid-word label. Every numeric cell goes
through fit(), which guarantees the column width -- a value too long loses decimals ("100.00" ->
"100.0") instead of shoving every column to its right, which is what SpO2 reaching 100 used to
do.

SpO2/HR1/HR2/HR3 are coloured by their own SQI, green above 0.9 and dark red below, over the mean
since the last redraw -- the criterion SIGNAL STATS uses in the lab. With one caveat: the lab
applies it to HR1/2/3 only, so for SpO2 the threshold is BORROWED, not validated (spo2_sqi is
computed differently). Treat the SpO2 colour as a hint.

Silence is the one thing this screen must never be quiet about: a board that stops (2 s) keeps
its row, painted white on red, and an alert line under the title names it; with no board at all
the alert says for how long. Rows are keyed by IP but identity is the MAC: a board back under a
new DHCP lease replaces its old row (counters carried over) instead of leaving a ghost — a row
that stays red is hardware that is really not there.

The frame is read the way UdpBoard does in the lab: fields by position after '$' (spec §4.2 —
[0]=mode [1]=SmpCnt ... [10]=SpO2 [14]=HR1 [20]=RSQI [21]=DiagCode [22]=ProbeState [34]=RF1
[35]=RF2). ProbeState is shown by its enumerator name from incunest_afe4490.h (DISCONNECTED,
OT_HIGH, APPLIED, AMB_SATURATING, ONLY_LED_SATURATING). Anything that does not parse is shown as
'?', never raised: a monitor must outlive a malformed line.

    python tools/fleet_monitor.py [--hub IP[:PORT]] [--refresh 1.0]
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, script_name          # noqa: E402
from pulsenest_hub_client import HubClient       # noqa: E402
from pulsenest_hub import AUX_PREFIXES           # noqa: E402  (one rule, one place)

# idfver is read but not shown: it is the same on every board of a fleet until a toolchain
# change, and this table is width-constrained. tools/udp_fw_versions.py prints it.
ID_KEYS = ("mac", "board", "fw", "lib", "build", "elfsha", "idfver")
LOST_S = 2.0
# enum class ProbeState in incunest_afe4490.h, minus the PROBE_ prefix -- the same names the lab
# shows (SIGNAL STATS / OT MONITOR). The first version of this table had invented labels AND the
# numbering shifted by one (2 read "PARTIAL" while the board was saying APPLIED). Never again:
# the label IS the enumerator's name, so a reader can grep it in the library.
# Shortened to keep the column at 12 chars, but never cut mid-word: a mechanical truncation
# would print "AMB_SATURATI", which reads like a typo. The enumerator is next to each label so
# it is still greppable in the library.
PROBE_STATES = {"0": "DISCONNECTED",    # PROBE_DISCONNECTED
                "1": "OT_HIGH",         # PROBE_OT_HIGH
                "2": "APPLIED",         # PROBE_APPLIED
                "3": "AMB_SAT",         # PROBE_AMB_SATURATING
                "4": "ONLY_LED_SAT"}    # PROBE_ONLY_LED_SATURATING
PROBE_W = max(len(v) for v in PROBE_STATES.values())

# SIGNAL STATS (pulsenest_lab.py) paints the HR1/HR2/HR3 mean green above this SQI and dark red
# below, over the MEAN of the SQI in its window -- not the last sample, which on a marginal
# signal would flash green/red every refresh. Same here, averaged over one refresh interval.
SQI_THRESHOLD = 0.9
# The lab does NOT colour SpO2: there is no criterion to copy. Extended here on request
# (2026-09-17) with the same 0.9, which is BORROWED, not validated -- spo2_sqi is computed
# differently from the HR ones (it is PI-weighted, and its upper bound is still an open
# question: project_spo2_pi_upper_bound_task). Read the SpO2 colour as a hint, not a verdict.
SQI_OF = {"spo2": "spo2_sqi", "hr1": "hr1_sqi", "hr2": "hr2_sqi", "hr3": "hr3_sqi"}


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
        self.moved_from = None   # previous IP of the same MAC, when a new lease replaced a row
        # SQI accumulated since the last redraw, per measurement: the colour follows the MEAN,
        # as SIGNAL STATS does, so a marginal signal does not flash at the refresh rate.
        self.sqi_sum = {k: 0.0 for k in SQI_OF}
        self.sqi_n = {k: 0 for k in SQI_OF}
        self.fields = {}      # spo2, hr1..hr3 + their SQIs, rsqi, diag, probe, vtia, rf

    def sqi_mean(self, key):
        """-> mean SQI of this measurement since the last redraw, or None if nothing arrived."""
        n = self.sqi_n.get(key, 0)
        return self.sqi_sum[key] / n if n else None

    def sqi_reset(self):
        for k in self.sqi_sum:
            self.sqi_sum[k], self.sqi_n[k] = 0.0, 0

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
        self.fields = {"spo2": f(10), "spo2_sqi": f(11),
                       "hr1": f(14), "hr1_sqi": f(15),
                       "hr2": f(16), "hr2_sqi": f(17),
                       "hr3": f(18), "hr3_sqi": f(19),
                       "rsqi": f(20), "diag": f(21),
                       "probe": PROBE_STATES.get(f(22), f(22)),
                       "vtia1": volts(23), "vtia2": volts(24),      # V_TIA_LED1 / V_TIA_LED2, volts
                       "rf1": f(34), "rf2": f(35)}
        for key, sqi_key in SQI_OF.items():
            try:
                self.sqi_sum[key] += float(self.fields[sqi_key])
                self.sqi_n[key] += 1
            except (KeyError, ValueError):
                pass


GREEN, RED, RESET = "\x1b[32m", "\x1b[31m", "\x1b[0m"


def fit(text, width):
    """Right-align `text` in EXACTLY `width` characters. A cell must never widen the table.

    A number too long loses decimals first -- "100.00" in a 5-wide column becomes "100.0", which
    is the honest thing to drop: SpO2 is specified to a few percent, so the second decimal was
    never information. Only if the integer part alone does not fit does the cell give up, and
    then it shows "#####" rather than a truncated number: a cut-off digit string is a different
    number, and a monitor that quietly reports the wrong value is worse than one that says it
    cannot show it.
    """
    if len(text) <= width:
        return f"{text:>{width}s}"
    whole, dot, frac = text.partition(".")
    if dot:
        for n in range(len(frac) - 1, 0, -1):
            shorter = f"{whole}.{frac[:n]}"
            if len(shorter) <= width:
                return f"{shorter:>{width}s}"
        if len(whole) <= width:
            return f"{whole:>{width}s}"
    return "#" * width


def sqi_cell(text, mean, width, colors):
    """A measurement cell coloured by its own SQI, the SIGNAL STATS way: green above the
    threshold, dark red below. Plain while no SQI has arrived yet."""
    cell = fit(text, width)
    if not colors or mean is None:
        return cell
    return (GREEN if mean > SQI_THRESHOLD else RED) + cell + RESET


def probe_cell(label, colors):
    """The probe column: APPLIED in green, every other state in red, '?' (no frame yet) plain.
    Width is applied to the bare label first — escape codes must not count as characters."""
    cell = f"{label:>{PROBE_W}s}"
    if not colors or label == "?":
        return cell
    return (GREEN if label == "APPLIED" else RED) + cell + RESET


RED_BG = "\x1b[41;97m"      # white on red: a board that fell silent, or no board at all


def ip_prefix(boards):
    """-> the first two octets shared by every board, or None when they differ.

    Worth folding into the header only while the whole fleet is on one subnet, which is the
    bench case (the hotspot). A subscriber watching a hub whose boards sit on two networks gets
    the full addresses instead: shortening them there would hide the very thing that differs.
    """
    prefixes = {".".join(b.ip.split(".")[:2]) for b in boards.values() if b.ip.count(".") == 3}
    return prefixes.pop() if len(prefixes) == 1 else None


def short_ip(ip, prefix):
    return ip[len(prefix) + 1:] if prefix and ip.startswith(prefix + ".") else ip


def short_mac(mac):
    """Last three octets. The first three are NOT common (V17 is 10:20:BA, the V18s 10:51:DB),
    so they cannot go in the header -- but the last three identify every board in the inventory."""
    parts = mac.split(":")
    return ":".join(parts[-3:]) if len(parts) == 6 else mac


def dedupe_by_mac(boards, b):
    """A board back under a new DHCP lease is the same hardware: keep ONE row (the newest IP),
    carry the session counters over, drop the ghost. Identity is the MAC, as in the lab (§4.8).
    A row that stays after this is a board that is genuinely not there any more."""
    mac = b.ident.get("mac")
    if not mac:
        return
    for other in list(boards.values()):
        if other is not b and other.ident.get("mac") == mac:
            newer, older = (b, other) if b.last_seen >= other.last_seen else (other, b)
            newer.dgrams += older.dgrams
            newer.gaps += older.gaps
            newer.errs += older.errs
            newer.moved_from = older.ip
            del boards[older.ip]


def render(boards, client, hub, t_start, colors=False, t_last_any=None):
    now = time.monotonic()
    silent = sorted((b for b in boards.values() if now - b.last_seen > LOST_S), key=lambda x: x.ip)
    prefix = ip_prefix(boards)
    out = [f"PulseNest {script_name(__file__)} — hub {hub[0]}:{hub[1]}  ({'connected' if client.connected else 'RECONNECTING'}"
           f", read-only)" + (f"  boards {prefix}.*" if prefix else "")
           + f"  up {now - t_start:5.0f} s     {time.strftime('%H:%M:%S')}"]
    # The alert line — the one thing on this screen that must never be quiet. A board that fell
    # silent, or no board at all, goes white on red across the width; otherwise the line is blank.
    if not boards:
        since = now - (t_last_any if t_last_any is not None else t_start)
        alert = (f"!! NO BOARD RECEIVED for {since:.0f} s — boards powered? hotspot broadcasting? "
                 f"hub receiving? (its counters are below)")
    elif silent:
        alert = "!! SILENT: " + "   ".join(f"{b.ip} {b.ident.get('board', '?')} for {now - b.last_seen:.0f} s"
                                          for b in silent)
    else:
        alert = ""
    out.append((RED_BG + alert + RESET) if (alert and colors) else alert)
    ip_w = 7 if prefix else 15
    hdr = (f"{'IP':{ip_w}s} {'MAC':8s} {'board':12s} {'fw':>5s} {'lib':>5s} {'build':>8s} "
           f"{'elfsha':>8s} "
           f"{'dg/s':>5s} {'mode':>4s} {'gaps':>5s} {'probe':>{PROBE_W}s} {'RSQI':>4s} {'diag':>5s} "
           f"{'SpO2':>5s} {'HR1':>6s} {'HR2':>6s} {'HR3':>6s} "
           f"{'RF1':>4s} {'TIA1':>4s} {'RF2':>4s} {'TIA2':>4s} {'ERR':>3s} {'last':>5s}")
    out.append(hdr)
    out.append("-" * len(hdr))
    for b in sorted(boards.values(), key=lambda x: x.ip):
        silence = now - b.last_seen
        lost = silence > LOST_S
        state = f"{silence:4.0f}s" if lost else "live"
        i, fl = b.ident, b.fields
        # A lost row is painted whole, so no cell gets a colour of its own there: its RESET
        # would cut the row's background in the middle.
        cell_colors = colors and not lost
        row = (f"{short_ip(b.ip, prefix):{ip_w}s} {short_mac(i.get('mac', '?')):8s} "
               f"{i.get('board', '?')[:12]:12s} "
               f"{i.get('fw', '?'):>5s} {i.get('lib', '?'):>5s} {i.get('build', '?')[:8]:>8s} "
               f"{i.get('elfsha', '?')[:8]:>8s} "
               f"{b.rate:5.0f} {b.mode:>4s} {b.gaps:5d} {probe_cell(fl.get('probe', '?'), cell_colors)} "
               f"{fit(fl.get('rsqi', '?'), 4)} {fit(fl.get('diag', '?'), 5)} "
               f"{sqi_cell(fl.get('spo2', '?'), b.sqi_mean('spo2'), 5, cell_colors)} "
               f"{sqi_cell(fl.get('hr1', '?'), b.sqi_mean('hr1'), 6, cell_colors)} "
               f"{sqi_cell(fl.get('hr2', '?'), b.sqi_mean('hr2'), 6, cell_colors)} "
               f"{sqi_cell(fl.get('hr3', '?'), b.sqi_mean('hr3'), 6, cell_colors)} "
               f"{fit(fl.get('rf1', '?'), 4)} {fit(fl.get('vtia1', '?'), 4)} "
               f"{fit(fl.get('rf2', '?'), 4)} {fit(fl.get('vtia2', '?'), 4)} "
               f"{b.errs:3d} {state:>5s}")
        out.append((RED_BG + row + RESET) if (colors and lost) else row)
        b.sqi_reset()
    if not boards:
        out.append("(no board seen yet)")
    out.append("")
    if client.last_status:
        # Relabelled, not passed through raw: the wire format is "hub ..."/"sub <addr> <name> ...",
        # and Alex found that ambiguous to read cold -- was the hub identified by being first in
        # the list, or by the literal word "hub"? Neither should be the answer. Every row now
        # says its role in a column of its own (hub / subscriber) and the file that is running it
        # (script_name(), same as every window title and console banner in this project), with
        # the rest of the fields passed through unchanged.
        for line in client.last_status.splitlines()[1:]:
            if line.startswith("hub "):
                m = re.search(r"file=(\S+)", line)
                fname = m.group(1) if m else "?"
                rest = re.sub(r"\bfile=\S+\s*", "", line[len("hub "):]).strip()
                out.append(f"  {'hub':<10s} {fname:<20s} {rest}")
            elif line.startswith("sub "):
                _, addr, remainder = line.split(" ", 2)
                fname, _, rest = remainder.partition(" ")
                out.append(f"  {'subscriber':<10s} {fname:<20s} {addr} {rest}")
    notes = [f"  {b.ip} is {b.ident.get('board', '?')} {b.ident.get('mac', '?')} back on a new "
             f"lease (was {b.moved_from}) — one row, counters carried"
             for b in sorted(boards.values(), key=lambda x: x.ip) if b.moved_from]
    notes += [f"  last $ERR {b.ip}: {b.last_err}"
              for b in sorted(boards.values(), key=lambda x: x.ip) if b.last_err]
    if notes:
        out.append("")
        out.extend(notes)
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

    client = HubClient(script_name(__file__), hub=hub, control=False, log=lambda m: None)
    client.connect()
    boards = {}
    aux = set()                    # IPs classified as auxiliary sources (AUX_PREFIXES)
    t_start = time.monotonic()
    t_last_any = None
    next_draw = next_status = 0.0
    screen = Screen()
    try:
        while True:
            item = client.recv(0.1)
            now = time.monotonic()
            if item is not None:
                ip, data = item
                t_last_any = now
                if ip in aux or (ip not in boards and data[:4] in AUX_PREFIXES):
                    # A phone doing OCR of the commercial monitor ($VN1) is not a board: the hub
                    # already refuses to query it and labels it `aux` in @STATUS (its D1), and a
                    # row of dashes here would be one more thing to explain during a campaign.
                    aux.add(ip)
                    continue
                b = boards.get(ip)
                if b is None:
                    b = boards[ip] = BoardView(ip)
                b.feed(data, now)
                dedupe_by_mac(boards, b)
            if now >= next_status:
                next_status = now + 5.0
                client.request_status()
            if now >= next_draw:
                next_draw = now + args.refresh
                screen.draw(render(boards, client, hub, t_start, colors=screen.enabled,
                                   t_last_any=t_last_any))
    except KeyboardInterrupt:
        pass
    finally:
        screen.close()
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
