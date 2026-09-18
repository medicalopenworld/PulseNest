"""Offline checks for tools/fleet_ppg_viewer.py — the data behind the bands, and the window.

Feeds synthetic $CFG and $M4 datagrams into BoardTrace directly, so it needs neither a hub nor a
board, then builds the real Qt window offscreen to check a band appears per board and the curves
receive the points. Runs in a couple of seconds:

    python tools/fleet_ppg_viewer_test.py

Covers what the viewer promises: PPG read from the right field, decimation, the window trimmed by
TIME (not by a point count), identity and colour by ProbeState, LOST after 2 s of silence, one
band per MAC across a DHCP change, and that a malformed line never raises.
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_ppg_viewer as V  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  offline checks of the PPG viewer")

ok = []


def check(cond, msg, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg + (f"  [{detail}]" if detail and not cond else ""))


def frame(ppg, probe="2", mode="M4"):
    """A $M4 with PPG_DISP and ProbeState at their spec positions, junk elsewhere."""
    p = [mode, "1000", "0"] + ["0"] * 33
    p[V.PPG_FIELD] = ppg
    p[V.PROBE_FIELD] = probe
    return ("$" + ",".join(p) + "*00\r\n").encode()


CFG = (b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:87:A4,fw=0.13,lib=0.93*00\r\n")
now = time.monotonic()

# ── the field it reads, and the decimation ────────────────────────────────────────────────
tr = V.BoardTrace("192.168.137.128", now)
tr.feed(CFG, now)
for i in range(V.DECIM):
    tr.feed(frame(f"{1e-5 * (i + 1):.6e}"), now)
check(len(tr.y) == 1, f"1 point kept per {V.DECIM} samples", f"{len(tr.y)} points")
check(tr.samples == V.DECIM, "every sample counted before decimation", str(tr.samples))
check(abs(tr.y[-1] - 1e-4) < 1e-9, "the value comes from PPG_DISP (field 9)", str(tr.y[-1]))
check(tr.probe == "APPLIED", "ProbeState read and named by its enumerator", tr.probe)
check(tr.label() == "50:87:A4 incunest_V18", "labelled by MAC tail and board", tr.label())

# ── the window is trimmed by time, not by a point count ───────────────────────────────────
old = V.BoardTrace("192.168.137.9", now - 60, window_s=2.0)
for k in range(30):                       # 3 points, spread over 30 decimated samples
    old.feed(frame("1.0e-05"), now - 3.0)
for k in range(30):
    old.feed(frame("2.0e-05"), now - 0.5)
before = len(old.y)
old.trim(now)
check(before == 6 and len(old.y) == 3,
      "trim() drops what fell out of the 2 s window and keeps the rest",
      f"{before} -> {len(old.y)}")

# ── state, colour and silence ─────────────────────────────────────────────────────────────
check(tr.state_colour(now) == V.GREEN, "APPLIED is green")
tr.feed(frame("1.0e-05", probe="4"), now)
check(tr.probe == "ONLY_LED_SAT" and tr.state_colour(now) == V.RED,
      "any other probe state is red", tr.probe)
check(not tr.is_lost(now) and tr.is_lost(now + 3),
      "LOST after 2 s of silence, not before")
check("LOST" in tr.title(now + 7) and "7 s" in tr.title(now + 7),
      "the title says how long it has been quiet", tr.title(now + 7))
fresh = V.BoardTrace("192.168.137.50", now)
check(fresh.state_colour(now) == V.GREY, "grey until a frame says what the probe is doing")

# ── one band per MAC across a DHCP change ─────────────────────────────────────────────────
traces = {}
a = traces["192.168.137.7"] = V.BoardTrace("192.168.137.7", now - 30)
a.feed(CFG, now - 30)
check(V.merge_by_mac(traces, a) is None, "nothing to merge with a single board")
b = traces["192.168.137.99"] = V.BoardTrace("192.168.137.99", now)
b.feed(frame("1.0e-05"), now)
check(V.merge_by_mac(traces, b) is None and len(traces) == 2,
      "without a MAC yet, the new address is its own band")
b.feed(CFG, now)
gone = V.merge_by_mac(traces, b)
check(gone == "192.168.137.7" and set(traces) == {"192.168.137.99"},
      "its $CFG arrives: same MAC, so the old band goes", f"{gone}, {set(traces)}")
check(b.moved_from == "192.168.137.7", "and it remembers where it came from", str(b.moved_from))

# ── a malformed line must never take the viewer down ──────────────────────────────────────
junk = V.BoardTrace("192.168.137.60", now)
for bad in (b"$M4,broken\r\n", b"$M4," + b"," * 40 + b"\r\n", b"$M4,1,2,3,x,y,z*00\r\n",
            b"\r\n", b"rubbish", b"$CFG,mac=\r\n"):
    junk.feed(bad, now)          # must not raise
check(True, "malformed lines are skipped, never raised")

# ── the real window, offscreen: a band per board, curves fed ──────────────────────────────
from PyQt5 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication([])
V.HubClient.connect = lambda self, timeout=1.0: False      # no hub in a test
win = V.Viewer(("127.0.0.1", 15999), 15.0)
t0 = time.monotonic()
for ip, mac in (("192.168.137.1", "AA:AA:AA:AA:AA:01"), ("192.168.137.2", "BB:BB:BB:BB:BB:02")):
    tr = win.traces[ip] = V.BoardTrace(ip, t0)
    tr.feed(CFG.replace(b"10:51:DB:50:87:A4", mac.encode()), t0)
    for _ in range(V.DECIM * 5):
        tr.feed(frame("1.5e-05"), t0)
win.redraw()
check(len(win.bands) == 2, "one band per board", str(len(win.bands)))
check(all(len(c.getData()[0]) == 5 for _, c in win.bands.values()),
      "each curve got its 5 decimated points",
      str([len(c.getData()[0]) for _, c in win.bands.values()]))
xs = win.bands["192.168.137.1"][1].getData()[0]
check(all(x <= 0 for x in xs), "x is seconds AGO: never positive", str(xs[:3]))
titles = [p.titleLabel.text for p, _ in win.bands.values()]
check(all("APPLIED" in t for t in titles), "the band titles carry the probe state", str(titles))
win.close()

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
# _exit skips Qt's teardown, which can hang on a window that never had an event loop — but it
# also skips flushing, and redirected to a file that swallowed the whole report the first time.
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if all(ok) else 1)
