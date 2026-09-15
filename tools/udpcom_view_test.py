"""Offscreen check of the three UDP COM view modes (v1.52)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath("."))
import pulsenest_lab as P

P.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_udpcom_test.ini")
if os.path.exists(P.SETTINGS_FILE):
    os.remove(P.SETTINGS_FILE)

from PyQt5 import QtWidgets
app = QtWidgets.QApplication([])

ok = fail = 0
def check(cond, what):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {what}")
    else:    fail += 1; print(f"  FAIL {what}")

def body(w):
    return w.console.toPlainText().split("\n") if w.console.toPlainText() else []

DATA = ["15:32:47.412, 2001,$M4,%d,123456,1,2,3*7F" % i for i in range(1, 6)]
EVT  = "# NET 192.168.137.62 incunest_V17 ... maxlen 274"

w = P.UdpComWindow(None)
print("1. default mode")
check(w._view_mode == P.UdpComWindow.VIEW_LIVE_TOP, "defaults to LIVE + EVENTS")
check(w.live_label.isVisibleTo(w), "live label shown")

print("2. LIVE + EVENTS")
w.append_lines(DATA)
check(w.live_label.text() == DATA[-1], "live label holds the LAST data frame")
check(body(w) == [], "console untouched by data frames")
w.append_line(EVT)
check(body(w) == [EVT], "event goes to the console")
w.append_lines(DATA[:2] + ["15:32:47.9, 2001,$TIMING,1,2,3*11"])
check("$TIMING" in w.console.toPlainText(), "$TIMING in the batch is kept as an event")
check(w.live_label.text() == DATA[1], "live label updated by the newer batch")

print("3. LIVE AT BOTTOM")
w._set_view_mode(P.UdpComWindow.VIEW_LIVE_BOTTOM)
check(not w.live_label.isVisibleTo(w), "live label hidden")
check(body(w)[-1] == DATA[1], "live line is the last console row")
n_before = len(body(w))
w.append_lines(DATA)
check(len(body(w)) == n_before, "a new batch does NOT add rows")
check(body(w)[-1] == DATA[-1], "the last row was rewritten in place")
w.append_line(EVT)
rows = body(w)
check(rows[-1] == DATA[-1], "live line still last after an event")
check(rows[-2] == EVT, "event inserted above the live line")

print("4. SCROLL (pre-v1.52 behaviour)")
w._set_view_mode(P.UdpComWindow.VIEW_SCROLL)
rows_before = body(w)
check(rows_before[-1] != DATA[-1], "live line removed from the console")
w.append_lines(DATA)
check(body(w)[-5:] == DATA, "every frame appended, one row each")

print("5. trim limits")
w.append_lines(["x,1,$M4,%d" % i for i in range(3000)])
check(w.console.blockCount() <= P.UdpComWindow._MAX_BLOCKS_SCROLL, f"SCROLL capped at 500 (got {w.console.blockCount()})")
w._set_view_mode(P.UdpComWindow.VIEW_LIVE_TOP)
for i in range(3000):
    w.append_line(f"# event {i}")
check(w.console.blockCount() <= P.UdpComWindow._MAX_BLOCKS_EVENTS, f"events capped at 2000 (got {w.console.blockCount()})")

print("6. PAUSE freezes both")
w._paused = True
w.append_lines(["15:32:48.0, 2001,$M4,999,0,0*00"])
check(w.live_label.text() != "15:32:48.0, 2001,$M4,999,0,0*00", "live line frozen while paused")
w._paused = False

print("7. persistence")
w.close()
w2 = P.UdpComWindow(None)
check(w2._view_mode == P.UdpComWindow.VIEW_LIVE_TOP, "mode restored from the ini")

print(f"\n{ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
