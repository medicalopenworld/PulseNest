"""Offline checks for tools/fleet_ppg_viewer.py — the data behind the bands, and the window.

Feeds synthetic $CFG and $M4 datagrams into BoardTrace directly, so it needs neither a hub nor a
board, then builds the real Qt window offscreen to check a band appears per board and the curves
receive the points. Runs in a couple of seconds:

    python tools/fleet_ppg_viewer_test.py

Covers what the viewer promises: PPG read from the right field, decimation, the window trimmed by
TIME (not by a point count), identity and colour by ProbeState, LOST after 2 s of silence, one
band per MAC across a DHCP change, and that a malformed line never raises.
"""
import math
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_ppg_viewer as V  # noqa: E402

# Before anything constructs a Viewer: its closeEvent writes settings, and a test must never
# land in the user's real fleet_ppg_viewer.ini.
import tempfile  # noqa: E402
V.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "fleet_ppg_viewer_test.ini")
if os.path.exists(V.SETTINGS_FILE):
    os.remove(V.SETTINGS_FILE)

print(f"== {os.path.basename(__file__)} ==  offline checks of the PPG viewer")

ok = []


def check(cond, msg, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg + (f"  [{detail}]" if detail and not cond else ""))


def frame(ppg, probe="2", mode="M4", spo2="97.5", spo2_sqi="0.99",
          hr3="61.0", hr3_sqi="0.99", extra=None):
    """A $M4 with the fields this viewer reads at their spec positions, junk elsewhere.

    `extra` is {field index: text} for the statistics rows, which read the whole frame.
    """
    p = [mode, "1000", "0"] + ["0"] * 33
    p[V.PPG_FIELD] = ppg
    p[V.PROBE_FIELD] = probe
    p[V.SPO2_FIELD], p[V.SPO2_SQI_FIELD] = spo2, spo2_sqi
    p[V.HR3_FIELD], p[V.HR3_SQI_FIELD] = hr3, hr3_sqi
    for idx, text in (extra or {}).items():
        p[idx] = text
    return ("$" + ",".join(p) + "*00\r\n").encode()


PI_FIELD = 13          # spec §4.2, the field the statistics test drives


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

# ── the bedside numbers ───────────────────────────────────────────────────────────────────
num = V.BoardTrace("192.168.137.80", now)
num.feed(CFG, now)
num.feed(frame("1.0e-05", spo2="97.5", spo2_sqi="0.99", hr3="61.4", hr3_sqi="0.95"), now)
html = num.numbers_html(now)
check(">98<" in html or ">97<" in html, "SpO2 shown as whole digits", html[:200])
check(">61<" in html, "HR3 shown as whole digits")
check(V.SPO2_COLOUR in html and V.HR_COLOUR in html,
      "both bright: each SQI is above the 0.9 threshold")
check("% SpO2" in html and "bpm HR3" in html,
      "the unit line names the measurement, so no separate label is needed", html[:200])
# Counting <div>s was the first version of this check and it counted wrong (7, not 5) while
# the HTML was right. Assert the thing that matters instead: one big line and one unit line
# per measurement, and no trace of the 11pt label that used to sit above them.
check(html.count("44pt") == 2 and html.count("12pt") == 2 and "11pt" not in html,
      "two lines per measurement, not three: the small label above is gone", html[:200])

# A firmware -1.00 is not a measurement: a monitor shows --, never the sentinel and never the
# last good value.
num.feed(frame("1.0e-05", spo2="-1.00", spo2_sqi="0.00", hr3="-1.00", hr3_sqi="0.00"), now)
html = num.numbers_html(now)
check(html.count("--") == 2 and "-1" not in html,
      "an invalid reading shows -- , never the -1.00 sentinel", html[:200])
check(V.DASH_COLOUR in html and V.SPO2_COLOUR not in html,
      "and it is greyed, not coloured as if it were a reading")

# Below the SQI threshold the digits dim: still shown, visibly less trustworthy.
num.feed(frame("1.0e-05", spo2="95.0", spo2_sqi="0.40", hr3="61.0", hr3_sqi="0.99"), now)
html = num.numbers_html(now)
check(V.SPO2_DIM in html and V.HR_COLOUR in html,
      "a low-SQI SpO2 dims while a good HR3 stays bright", html[:200])

# A board that fell silent must not keep displaying its last numbers.
check(num.numbers_html(now + 9).count("--") == 2,
      "once LOST, both numbers go to --")

# ── the statistics panel ──────────────────────────────────────────────────────────────────
st = V.BoardTrace("192.168.137.70", now)
st.feed(CFG, now)
for i in range(V.DECIM):                       # a ramp 1..10 in PI, one full decimation group
    st.feed(frame("1.0e-05", extra={PI_FIELD: f"{i + 1}.0"}), now)
check(st.stats_shot == {} and st.stats_rows_text()[1][1:] == ["---"] * 4,
      "before the first window closes there is no statistic, and the panel says ---",
      str(st.stats_rows_text()[1]))
check(st.maybe_snapshot(now + 0.5) is False, "the window does not close early", "0.5 s")
check(st.maybe_snapshot(now + V.STATS_WINDOW_S) is True,
      f"it closes after STATS_WINDOW_S ({V.STATS_WINDOW_S} s), on its own clock and not the redraw")
mean, sd, lo, hi = st.stats_shot[PI_FIELD]
# The point of doing this before the decimation gate: 10 samples went in, 1 point reached the
# curve, and the statistic must describe the signal, not the 50 Hz picture of it.
check(abs(mean - 5.5) < 1e-9 and lo == 1.0 and hi == 10.0 and len(st.y) == 1,
      "mean/min/max come from every sample, not from the decimated ones",
      f"mean={mean} min={lo} max={hi} points={len(st.y)}")
check(abs(sd - math.sqrt(sum((v - 5.5) ** 2 for v in range(1, 11)) / 10)) < 1e-9,
      "SD is the population one (/n), as SIGNAL STATS computes it", str(sd))
check(st.stats[PI_FIELD].n == 0, "and the accumulator restarts for the next window")

# Nothing arrives in the next window: the panel must go back to --- rather than keep showing a
# second-old mean as if it were current. This is what a silent board looks like.
st.maybe_snapshot(now + 2 * V.STATS_WINDOW_S)
check(all(row[1:] == ["---"] * 4 for row in st.stats_rows_text()[1:]),
      "a window with no samples shows ---, never the previous one",
      str(st.stats_rows_text()[1]))

# One table, always the four statistics.
for i in range(4):
    st.feed(frame("1.0e-05", extra={PI_FIELD: "2.0", 4: "1048576", 31: "1.2300e-05"}), now)
st.maybe_snapshot(now + 3 * V.STATS_WINDOW_S)
full = st.stats_rows_text()
check(len(full) == len(V.STATS_ROWS) + 1,
      f"one table with all {len(V.STATS_ROWS)} signals (plus a header), no mode to choose",
      str(len(full) - 1))
check(full[0] == ["signal", "mean", "sd", "min", "max"],
      "mean, SD, min and max, always the four", repr(full[0]))
check(len({len(row) for row in full}) == 1,
      "every row has the same cells", str(sorted({len(row) for row in full})))
check(all(len(c) <= len(V.VAL_CHARS) for row in full[1:] for c in row[1:]),
      "and no cell is longer than the width its column was measured for",
      str([c for row in full[1:] for c in row[1:] if len(c) > len(V.VAL_CHARS)]))
by_label = {row[0]: row[1:] for row in full}
check(by_label["PI %"] == ["2.00", "0.00", "2.00", "2.00"],
      "a steady signal reads mean=min=max and SD 0", str(by_label["PI %"]))
check(by_label["OT1 ppm"][0] == "12.30", "OT is shown in ppm, as the lab does",
      str(by_label["OT1 ppm"]))
check(by_label["LED1"][0] == "1048576", "raw ADC rows keep every digit",
      str(by_label["LED1"]))

# The markup: a real <table>, because the font SIGNAL STATS asks for is proportional here and
# padded spaces do not align in a proportional font.
label_w, value_w = 90, 70
html = st.stats_html(label_w, value_w)
check(html.count("<tr") == len(V.STATS_ROWS) + 1 and "<pre" not in html,
      "every signal is a table row, not a padded line", html[:80])
check(html.count(f"width='{value_w}'") == 4 * (len(V.STATS_ROWS) + 1)
      and html.count("align='right'") == 4 * (len(V.STATS_ROWS) + 1),
      "the four value columns are a measured width and right-aligned")
check(V.STATS_HEAD_BG in html and V.STATS_BODY in html,
      "and it wears SIGNAL STATS's colours")

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
from PyQt5 import QtCore, QtWidgets  # noqa: E402

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
check(all(len(b[1].getData()[0]) == 5 for b in win.bands.values()),
      "each curve got its 5 decimated points",
      str([len(b[1].getData()[0]) for b in win.bands.values()]))
xs = win.bands["192.168.137.1"][1].getData()[0]
check(all(x <= 0 for x in xs), "x is seconds AGO: never positive", str(xs[:3]))
# Reported by Alex: at SpO2 100 and at a 3-digit rate the digits wrapped and the rows fell
# out of line. The property to hold is that the panel's HEIGHT does not depend on the value.
band = win.bands["192.168.137.1"]
heights, shown = {}, {}
for spo2, hr3 in (("97.0", "61.0"), ("100.0", "155.0"), ("-1.00", "-1.00")):
    tr = win.traces["192.168.137.1"]
    tr.feed(frame("1.0e-05", spo2=spo2, spo2_sqi="0.99", hr3=hr3, hr3_sqi="0.99"), time.monotonic())
    win.redraw()
    heights[(spo2, hr3)] = round(band[2].item.boundingRect().height(), 1)
    shown[(spo2, hr3)] = band[2].item.toPlainText()
check(len(set(heights.values())) == 1,
      "the numbers panel is the same height at 2 digits, 3 digits and --", str(heights))
# Read inside the loop: the first version of this check looked at the panel AFTER the loop,
# by which point the invalid case had overwritten it, and asserted "100" against "--".
check("100" in shown[("100.0", "155.0")] and "155" in shown[("100.0", "155.0")],
      "and the three-digit values really are displayed",
      repr(shown[("100.0", "155.0")]))

titles = [b[0].titleLabel.text for b in win.bands.values()]
check(all("APPLIED" in t for t in titles), "the band titles carry the probe state", str(titles))
check(all("SpO2" in b[2].item.toHtml() for b in win.bands.values()),
      "every band got its numbers panel next to the plot")
# ── bands appear while running, and a dropped one must not free its row ──────────────────
# Found by reading the code for Alex's question: rows were numbered len(self.bands), so after
# a band was dropped the next board landed on a row that was still occupied and was drawn on
# top of it. Boards change IP here daily, so this was reachable.
rows_before = {id(b[0]): win.layout_widget.ci.items[b[0]][0][0] for b in win.bands.values()}
third = win.traces["192.168.137.3"] = V.BoardTrace("192.168.137.3", time.monotonic())
third.feed(CFG.replace(b"10:51:DB:50:87:A4", b"CC:CC:CC:CC:CC:03"), time.monotonic())
third.feed(frame("1.0e-05"), time.monotonic())
win.redraw()
check(len(win.bands) == 3, "a board that appears while running gets its band, no restart",
      str(len(win.bands)))

win.drop_band("192.168.137.2")                       # as a DHCP merge would
fourth = win.traces["192.168.137.4"] = V.BoardTrace("192.168.137.4", time.monotonic())
fourth.feed(CFG.replace(b"10:51:DB:50:87:A4", b"DD:DD:DD:DD:DD:04"), time.monotonic())
fourth.feed(frame("1.0e-05"), time.monotonic())
win.redraw()
used = [win.layout_widget.ci.items[b[0]][0][0] for b in win.bands.values()]
check(len(used) == len(set(used)),
      "after dropping one, a new board does not land on an occupied row", str(sorted(used)))
del win.traces["192.168.137.3"], win.traces["192.168.137.4"]
for ip in ("192.168.137.3", "192.168.137.4"):
    win.drop_band(ip)

# ── the statistics panel in the real window ───────────────────────────────────────────────
check(all("signal" in b[3].widget().toPlainText() for b in win.bands.values()),
      "every band got a statistics panel too")
check(all(b[3].widget().isReadOnly() for b in win.bands.values()),
      "and it is read-only, like everything else in this window")
# Alex: the rows that do not fit must be reachable, not dropped. The panel is a widget with a
# real scrollbar, so every row is always in the document whatever the band's height.
check(all(b[3].widget().toPlainText().count("RSQI") == 1 for b in win.bands.values()),
      "every row is in the panel, however short the band -- the scrollbar reaches them")
check(all(b[3].widget().verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAsNeeded
          for b in win.bands.values()),
      "with a vertical scrollbar when there is more table than band")
# Alex: the bands stopped being equal once the tables appeared. They must not depend on what
# their panel contains -- that was a feedback loop (taller band -> one more row -> taller band).
heights = [round(b[0].geometry().height()) for b in win.bands.values()]
check(max(heights) - min(heights) <= 1, "and every band is the same height", str(heights))
# Reported by Alex: no rows in any of the three tables. The content was there -- the column
# was. Claiming a minimum width for the layout (panel + 4 columns + a floor for the waveform,
# 1272 px) put the statistics past the right edge of a 1200 px window, behind a horizontal
# scrollbar, which reads as an empty panel. Nothing may claim a width the window has to scroll.
check(win.centralWidget() is win.layout_widget,
      "the plots are the central widget: nothing to scroll, nothing hidden behind a bar")
check(win.layout_widget.minimumWidth() == 0 and win.layout_widget.minimumHeight() == 0,
      "the layout claims nothing: no scrollbar can hide a panel behind it",
      f"{win.layout_widget.minimumWidth()}x{win.layout_widget.minimumHeight()}")
# The panel columns are fixed width, so a window narrower than they are does not squeeze them
# -- it overflows, and what is past the edge is simply not drawn. The WINDOW carries the
# minimum instead, which makes that state unreachable rather than merely detectable.
check(win.minimumWidth() >= V.panel_width() + V.stats_width(),
      "the window cannot be made narrower than its own panels",
      f"min {win.minimumWidth()} px vs panels {V.panel_width() + V.stats_width()} px")
win.resize(400, 900)                     # refused down to the minimum
win.show()                               # a window that was never shown has no layout pass,
app.processEvents()                      # and then every geometry below is the pre-layout one
win.redraw()
right_edge = max(b[3].geometry().right() for b in win.bands.values())   # the proxy item
check(right_edge <= win.layout_widget.width() + 1,
      "every statistics panel ends inside the window, at any size",
      f"panel right {right_edge:.0f} px, window {win.layout_widget.width()} px")
check(all(b[0].geometry().width() > 100 for b in win.bands.values()),
      "and the waveform still has room to be a waveform",
      str([round(b[0].geometry().width()) for b in win.bands.values()]))
# What a squeezed panel loses must be what a reader can reconstruct: LED1 = LED1_SUB + ALED1.
tail = [r[0] for r in V.STATS_ROWS[-4:]]
check(tail == ["LED1", "LED2", "ALED1", "ALED2"],
      "the raw converter codes are last, so they are the first rows to go", str(tail))
heights = [round(b[0].geometry().height()) for b in win.bands.values()]
check(max(heights) - min(heights) <= 1,
      "still equal after a resize, with the panels unchanged", str(heights))

# ── the settings file: a first run sizes itself, and the choice survives ──────────────────
check(win.height() > 400, "a first run takes its height from the screen, not a fixed 800 px",
      f"{win.width()}x{win.height()}")
win.resize(1400, 1234)
app.processEvents()
win.close()                      # closeEvent writes the geometry
check(os.path.exists(V.SETTINGS_FILE), "closing writes the settings file")

again = V.Viewer(("127.0.0.1", 15999), 15.0)
check(again.height() == 1234 and again.width() == 1400,
      "and the next run comes up the size it was left",
      f"{again.width()}x{again.height()}")
again.close()

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
# _exit skips Qt's teardown, which can hang on a window that never had an event loop — but it
# also skips flushing, and redirected to a file that swallowed the whole report the first time.
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if all(ok) else 1)
