"""One live PPG band per board — the window you open to see whether a probe has moved.

A read-only subscriber of the hub (spec §4.11), like tools/fleet_monitor.py and with the same
guarantee: it holds no control, so no $SET and no $MODE can leave it, by construction. Where the
fleet monitor shows numbers, this shows the waveform: one band per board, stacked, so a probe
that slips shows up as the shape going wrong at a glance — usually before any number moves.

    python tools/fleet_ppg_viewer.py [--hub IP[:PORT]] [--window 15] [--opengl]

The window size, the seconds on screen and the size of the statistics panel are remembered in
`tools/fleet_ppg_viewer.ini`
(per machine, not versioned), so the first-run defaults — a size taken from the screen rather
than a fixed number of pixels that cannot know how many bands there will be — only ever matter
once.

Deliberately narrow. It does not capture, does not command a board, carries no algorithms and no
configuration; all of that lives elsewhere. If it dies, it is relaunched and nothing else notices
— which is the whole point of being a separate process hanging off the hub.

**It is also a controlled experiment.** pyqtgraph's paint code has killed pulsenest_lab.py 28
times (`faulthandler.log`, `project_signals2_crash_investigation_task`), and the one lead never
tested is `useOpenGL=True`, which the lab sets and pyqtgraph's own authors flag as a source of
segfaults. This viewer starts with **OpenGL off** and `--opengl` turns it on, with faulthandler
writing to its own file. Left running for hours it answers the question either way, and it can
crash as often as it likes without costing a capture.

What it draws, and why those choices:

- **`PPG_DISP`** (field `p[9]` of `$M*`): already band-passed and negated for display by the
  library, so the band shows a pulse the way a person expects to see one.
- **One Y axis per band, never shared.** Amplitudes differ by orders of magnitude between boards
  and probe sites; a shared axis would flatten every trace but the largest.
- **A common X axis in seconds-ago**, from the datagram's arrival time at this PC. Each board has
  its own clock and its own sample counter, so arrival time is the only thing comparable across
  boards — the same reasoning behind `host_t_us` in multi-board capture (§4.8 F3). A board that
  goes quiet stops advancing and leaves a growing gap at the right edge, which is itself the
  signal that something is wrong.
- **Decimated to ~50 Hz** (1 sample in 10). The pulse shape needs nothing faster, and it keeps
  the redraw cheap — which, given what this program is testing, is not a detail.
- **Identity by MAC, not IP**, as everywhere else: a board back on a new DHCP lease keeps its
  band instead of growing a second one.
- **Title and frame coloured by ProbeState** (green APPLIED, red anything else, and LOST after
  2 s of silence). The state often names the problem before the waveform shows it.
- **Two large numbers beside each band**, in the idiom of a bedside oximeter (Masimo, Nellcor,
  Philips): SpO2 in cyan, pulse rate in green, each as digits under a small unit line that
  also names the measurement (`% SpO2`, `bpm HR3`) — two lines, not three, because with a
  separate label as well the panel ran out of vertical room and pushed the rows out of line.
  A small red heart sits to the left of the rate, as on the machines this borrows from, and it
  follows the same colour code as the digits so that it never beats beside a `--`. Three
  conventions from those machines are worth copying exactly, because they are about not
  misleading the person reading across the room:
  * an invalid reading shows **`--`**, never the last good number and never a sentinel. The
    firmware sends `-1.00`; showing that would read as a measurement.
  * the digits **dim** when the measurement's own SQI is below 0.9 — the same threshold SIGNAL
    STATS uses in the lab — so a number you should not trust does not shout as loudly as one
    you can.
  * the number is large enough to read from where you stand, which is the whole point.
  The rate is labelled **HR3**, not "PR": this is a bench tool with three heart-rate algorithms
  running side by side, and hiding which one produced the number would be the wrong kind of
  faithfulness to the commercial idiom.
- **A statistics panel on the right of each band** — the same table SIGNAL STATS shows in the
  lab, down to its font and its colours: per signal, **mean, SD, min and max** over the last
  second, always the four. All 24 signals of the frame are always there, ordered by how often
  they answer the question in front of you (PPG, PI, R, SpO2, HR1-3 and their SQIs, then the
  analog chain, then the raw converter codes); the panel is as tall as its band and **scrolls**
  to the rows that do not fit.

  It is a read-only `QTextEdit` in a proxy item rather than a drawn label, for three reasons
  that were all learned the hard way. A widget brings a real scrollbar. It clips itself, so
  nothing can end up painted outside the window. And its content has no say in how tall the
  band is — when it did, the bands stopped being equal: the label asked for its document's
  height, the document was truncated to what fit the plot, and the plot's height came from the
  row, so a band one pixel taller fitted one more row, asked for more height, and fitted
  another. Every band row now carries the same stretch factor, and the loop cannot come back.

  The font is SIGNAL STATS's (`monospace` as the lab asks for it) at this panel's own smaller
  size. Note what that means here: Qt resolves that family to a **proportional** face, which is
  invisible in the lab because a `QTableWidget` aligns by cells — so this panel aligns by table
  columns too, never by padding spaces.

  **The averaging window is one second and does NOT follow the redraw.** The window redraws ten
  times a second; a statistic over 100 ms is mostly noise, and SIGNAL STATS averages over its
  own interval (1 s by default). Keeping the two cadences separate is deliberate — how often a
  number is *judged* is not the same question as how often it is *shown*. (The big numbers'
  SQI dimming still reads a single sample; aligning that is an open decision, 2026-09-19.)
"""
import argparse
import faulthandler
import math
import os
import sys
import time
from collections import deque
from html import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, banner, script_name  # noqa: E402
from pulsenest_hub import AUX_PREFIXES           # noqa: E402  (one rule, one place)
from pulsenest_hub_client import HubClient                    # noqa: E402
# fit() belongs to the fleet monitor, which is the table tool and where the rule was argued out
# and debugged (a cell must never widen its column; it drops decimals, then gives up with
# '#####' rather than print a truncated digit string, which is a different number). Imported
# rather than copied: two implementations of that rule would drift. Here the column is a real
# table column measured for VAL_CHARS, so fit() is asked for that many characters and its job
# is the same one: keep a cell from making its column wider than it was measured to be.
from fleet_monitor import fit                                 # noqa: E402
import pyqtgraph as pg                                        # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                    # noqa: E402

_fault_log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fleet_ppg_viewer_faulthandler.log"), "a")
faulthandler.enable(file=_fault_log, all_threads=True)

PPG_FIELD    = 9      # $M3/$M4: mode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP
SPO2_FIELD, SPO2_SQI_FIELD = 10, 11
HR3_FIELD,  HR3_SQI_FIELD  = 18, 19
PROBE_FIELD  = 22
DECIM        = 10     # 500 Hz -> 50 Hz on screen
LOST_S       = 2.0
WINDOW_S     = 15.0
REDRAW_MS    = 100
DRAIN_MS     = 20
MIN_PLOT_W   = 300    # the window refuses to be narrower than its panels plus this
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fleet_ppg_viewer.ini")
ID_KEYS      = ("mac", "board")
PROBE_STATES = {"0": "DISCONNECTED", "1": "OT_HIGH", "2": "APPLIED",
                "3": "AMB_SAT", "4": "ONLY_LED_SAT"}
APPLIED      = "APPLIED"
GREEN, RED, GREY = "#44FF88", "#FF4444", "#888888"
# Bedside-monitor palette: SpO2 cyan, pulse rate green. That pairing is the de facto convention
# of the multiparameter monitors (Philips IntelliVue, GE CARESCAPE) rather than anything
# standardised — no standard assigns colours to numerics. What IS standardised is the alarm
# palette (IEC 60601-1-8: red high priority, yellow medium, cyan low/informational), which is
# the reason a normal reading is never painted red on these machines, and why the dashes below
# are grey rather than red. In the lab green means "firmware" (project_color_convention), but
# every number in this window comes from the firmware, so the colour disambiguates nothing here.
SPO2_COLOUR  = "#00D0FF"
HR_COLOUR    = "#00FF6A"
DASH_COLOUR  = "#666666"
SQI_GOOD     = 0.9    # same threshold SIGNAL STATS uses to call a reading trustworthy
DIM_FACTOR   = 0.30   # how far a below-threshold reading fades. One knob: it was 0.5-ish by
                      # hand-picked hex and did not read as clearly "do not trust this".


def dim(colour, factor=DIM_FACTOR):
    """-> the same hue at `factor` of its brightness. Derived rather than a second hand-picked
    hex, so the two colours cannot drift apart and there is one number to turn."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))


SPO2_DIM = dim(SPO2_COLOUR)
HR_DIM = dim(HR_COLOUR)
RED_DIM = dim(RED)
BIG_PT       = 44     # the digits
SMALL_PT     = 12     # the unit line above them
# The heart beside the rate. U+2665 (BLACK HEART SUIT) deliberately, not U+2764: the latter
# renders as a colour emoji on Windows, which would ignore the CSS that dims it along with the
# reading. Small enough not to compete with the digits, large enough to read across the room.
HEART        = "\u2665"
HEART_PT     = 18
WIDEST_VALUE = "000"      # three digits: SpO2 reaches 100, and the rate can pass it too
WIDEST_UNIT  = "bpm HR3"

# ── the statistics panel ────────────────────────────────────────────────────────────────────
# One second, and NOT the redraw period. The panel repaints every REDRAW_MS (100 ms), but a mean
# over 100 ms is 50 samples of a 500 Hz stream and reads as noise; SIGNAL STATS uses its own
# interval (1 s by default) and so does the fleet monitor. How often a statistic is computed is
# a different question from how often it is shown, and tying them together is what makes those
# two tools disagree about the same board.
STATS_WINDOW_S = 1.0
# 8 pt and 8-character columns: on this display (about 190 dpi effective) that is a 40-character
# table ~480 px wide, against the 603 px the same table took at 9 pt with 9-wide columns. The
# panel has to leave the waveform room to be a waveform; 8 characters still hold a signed
# seven-digit ADC code, which is the widest thing any row can print.
STATS_PT   = 8
# The family SIGNAL STATS asks for in its stylesheet, so both tables read as the same object.
# Qt resolves it here to a PROPORTIONAL face (MS Shell Dlg 2), which is why this panel is an
# HTML table and not padded text: spaces do not align in a proportional font.
STATS_FAMILY = "monospace"
VAL_CHARS  = "-8388608"   # the widest cell any row can print: a signed 24-bit ADC code
# SIGNAL STATS's colours (pulsenest_lab.py, stats_table stylesheet) as the starting point, then
# tuned on the bench: the body text a step down from #E0E0E0 so a wall of 24 rows does not
# compete with the two large numbers beside it, alternate rows lifted off pure black so the eye
# can follow one across four columns, and the header brighter and bold so it reads as a heading
# rather than as the first row of data. Four values, all here.
STATS_BG   = "#111111"
STATS_BODY = "#B4B4B4"      # was #E0E0E0
STATS_ROW_ALT = "#2E2E2E"   # every other row, lifted off the background
STATS_HEAD = "#C8CEE0"
STATS_HEAD_BG = "#33395A"   # was #1E1E2E
# (label, field index in the $M* frame, display scale, decimals), in the order they are read
# when something looks wrong -- which is also the order in which a short band keeps them.
# Field positions are spec §4.2, the same table fleet_monitor.py reads. Scales follow the lab's
# display conventions: OT and PPG_DISP in ppm, photodiode current in µA, everything else raw.
STATS_ROWS = [
    ("PPG ppm",   9, 1e6, 2),
    ("PI %",     13, 1.0, 2),
    ("R",        12, 1.0, 4),
    ("SpO2 %",   10, 1.0, 2),
    ("SpO2 SQI", 11, 1.0, 3),
    ("HR1 bpm",  14, 1.0, 1),
    ("HR1 SQI",  15, 1.0, 3),
    ("HR2 bpm",  16, 1.0, 1),
    ("HR2 SQI",  17, 1.0, 3),
    ("HR3 bpm",  18, 1.0, 1),
    ("HR3 SQI",  19, 1.0, 3),
    ("RSQI",     20, 1.0, 2),
    # Then the analog chain, in the order it is consulted when a reading looks wrong: is the
    # TIA near its rail, is the tissue transmitting, how much current is the photodiode giving,
    # and only last the raw converter codes — which are the rows a reader can reconstruct from
    # the others (LED1 = LED1_SUB + ALED1), and therefore the right ones to lose first.
    ("V_TIA1 V", 23, 1.0, 3),
    ("V_TIA2 V", 24, 1.0, 3),
    ("OT1 ppm",  31, 1e6, 2),
    ("OT2 ppm",  32, 1e6, 2),
    ("I_PD1 µA", 27, 1e6, 3),
    ("I_PD2 µA", 28, 1e6, 3),
    ("LED1_SUB",  8, 1.0, 0),
    ("LED2_SUB",  7, 1.0, 0),
    ("LED1",      4, 1.0, 0),
    ("LED2",      3, 1.0, 0),
    ("ALED1",     6, 1.0, 0),
    ("ALED2",     5, 1.0, 0),
]
STATS_FIELDS = tuple(sorted({row[1] for row in STATS_ROWS}))
STATS_COLS   = ("mean", "sd", "min", "max")


class Stat:
    """Running mean / SD / min / max of one signal over the current window.

    Welford rather than sum-of-squares: the raw ADC rows run to ~2e6 and squaring them spends
    the precision exactly where the SD is small, which is the case worth seeing (a channel that
    has gone quiet). SD is the population one (÷n), as SIGNAL STATS computes it, so the two
    panels can be compared digit for digit.
    """

    __slots__ = ("n", "mean", "m2", "lo", "hi")

    def __init__(self):
        self.reset()

    def reset(self):
        self.n = 0
        self.mean = self.m2 = 0.0
        self.lo = self.hi = None

    def add(self, v):
        self.n += 1
        d = v - self.mean
        self.mean += d / self.n
        self.m2 += d * (v - self.mean)
        if self.lo is None or v < self.lo:
            self.lo = v
        if self.hi is None or v > self.hi:
            self.hi = v

    def snapshot(self):
        """-> (mean, sd, min, max), or None if nothing arrived in the window."""
        if not self.n:
            return None
        return (self.mean, math.sqrt(self.m2 / self.n), self.lo, self.hi)


class BoardTrace:
    """The data behind one band: a time-windowed ring of PPG samples, plus who the board is.

    No Qt in here on purpose — this is what the offscreen test drives directly.
    """

    def __init__(self, ip, now, window_s=WINDOW_S):
        self.ip = ip
        self.ident = {}
        self.first_seen = self.last_seen = now
        self.window_s = window_s
        self.t = deque()          # arrival time of each kept sample (monotonic seconds)
        self.y = deque()
        self.probe = "?"
        self.spo2 = self.spo2_sqi = self.hr3 = self.hr3_sqi = None
        self.samples = 0          # samples seen, before decimation
        self._decim = 0
        self.moved_from = None    # previous IP of the same MAC
        self.stats = {idx: Stat() for idx in STATS_FIELDS}
        self.stats_shot = {}      # field -> the last CLOSED window's (mean, sd, min, max)
        self._stats_t0 = now

    @property
    def mac(self):
        return self.ident.get("mac")

    def label(self):
        who = f"{self.mac[-8:]} {self.ident.get('board', '?')}" if self.mac else self.ip
        return who

    def feed(self, data, now):
        """One forwarded datagram. Never raises: a malformed line is skipped, not fatal."""
        self.last_seen = now
        for raw in data.split(b"\n"):
            line = raw.rstrip(b"\r")
            if not line:
                continue
            if line[:1] == b"$" and line[1:3] in (b"M1", b"M2", b"M3", b"M4") and line[3:4] == b",":
                self._data_frame(line, now)
            elif line.startswith(b"$CFG,"):
                for part in line.split(b","):
                    k, sep, v = part.partition(b"=")
                    if sep and k.decode("ascii", "replace") in ID_KEYS:
                        self.ident[k.decode("ascii", "replace")] = \
                            v.split(b"*")[0].decode("ascii", "replace")

    def _data_frame(self, line, now):
        p = line[1:].split(b"*")[0].split(b",")
        self.samples += 1
        if len(p) > PROBE_FIELD:
            self.probe = PROBE_STATES.get(p[PROBE_FIELD].decode("ascii", "replace"), "?")
        def number(idx):
            try:
                return float(p[idx])
            except (IndexError, ValueError):
                return None
        self.spo2, self.spo2_sqi = number(SPO2_FIELD), number(SPO2_SQI_FIELD)
        self.hr3, self.hr3_sqi = number(HR3_FIELD), number(HR3_SQI_FIELD)
        # Every sample feeds the statistics, before the decimation gate: the panel says what the
        # signal did, not what the 50 Hz picture of it did. Bounded by len(p) instead of catching
        # IndexError because an $M3 frame is short by 13 fields and that would be 18k exceptions
        # a second for nothing.
        n_fields = len(p)
        for idx in STATS_FIELDS:
            if idx < n_fields:
                try:
                    self.stats[idx].add(float(p[idx]))
                except ValueError:
                    pass
        self._decim += 1
        if self._decim < DECIM:
            return
        self._decim = 0
        try:
            value = float(p[PPG_FIELD])
        except (IndexError, ValueError):
            return            # $M1/$M2 carry PPG elsewhere or the field is junk: skip the sample
        self.t.append(now)
        self.y.append(value)

    def maybe_snapshot(self, now):
        """Close the averaging window if it is due. -> True if the displayed numbers changed.

        Called from the redraw, but on its own clock (STATS_WINDOW_S): the panel repaints ten
        times a second and the statistics behind it change once a second, which is also the only
        rate at which four columns of digits are readable.
        """
        if now - self._stats_t0 < STATS_WINDOW_S:
            return False
        self.stats_shot = {idx: st.snapshot() for idx, st in self.stats.items()}
        for st in self.stats.values():
            st.reset()
        self._stats_t0 = now
        return True

    def stats_rows_text(self):
        """The panel as rows of text: [label, mean, sd, min, max] each. The offline test reads
        this — it is exactly what the table shows, without the markup."""
        out = [["signal", *STATS_COLS]]
        for label, idx, scale, dec in STATS_ROWS:
            shot = self.stats_shot.get(idx)
            if shot is None:
                cells = ["---"] * len(STATS_COLS)     # nothing arrived in the last window
            else:
                cells = [f"{v * scale:.{dec}f}" for v in shot]
            out.append([label, *(fit(c, len(VAL_CHARS)).strip() for c in cells)])
        return out

    def stats_html(self, label_w, value_w):
        """The rows as an HTML table, aligned by columns.

        Not by padded spaces: the font is SIGNAL STATS's, which Qt resolves to a proportional
        face, and in a proportional font a space is not a character width. Column widths come
        from the caller, measured once from the real font metrics.
        """
        rows = self.stats_rows_text()
        # The background goes on every cell, not on the <tr>: Qt's rich text paints a row
        # background only where a cell asks for one, so striping set on the row alone leaves
        # the gaps between cells black and the stripe comes out dotted.
        def cells_of(row, style):
            out = [f"<td width='{label_w}' style='{style}'>{escape(row[0])}</td>"]
            out += [f"<td width='{value_w}' align='right' style='{style}'>{escape(c)}</td>"
                    for c in row[1:]]
            return "".join(out)

        head_style = (f"background-color:{STATS_HEAD_BG}; color:{STATS_HEAD}; "
                      f"font-weight:bold;")
        html = [f"<table cellspacing='0' cellpadding='2' style='color:{STATS_BODY};'>",
                f"<tr>{cells_of(rows[0], head_style)}</tr>"]
        for n, row in enumerate(rows[1:], start=1):
            stripe = f"background-color:{STATS_ROW_ALT};" if n % 2 == 0 else ""
            html.append(f"<tr>{cells_of(row, stripe)}</tr>")
        html.append("</table>")
        return "".join(html)

    def trim(self, now):
        """Drop what fell out of the window. By time, not by a fixed length: a board streaming
        at a different rate must still show the same number of SECONDS as its neighbours."""
        limit = now - self.window_s
        while self.t and self.t[0] < limit:
            self.t.popleft()
            self.y.popleft()

    def silent_for(self, now):
        return now - self.last_seen

    def is_lost(self, now):
        return self.silent_for(now) > LOST_S

    def state_colour(self, now):
        if self.is_lost(now):
            return RED
        if self.probe == APPLIED:
            return GREEN
        return RED if self.probe != "?" else GREY

    def numbers_html(self, now):
        """The panel beside the band. Built here, not in the widget, so the offline test can
        read exactly what a person would see without constructing a window."""
        def block(value, sqi, unit, bright, dim, heart=False):
            invalid = value is None or value <= 0 or self.is_lost(now)
            good = sqi is not None and sqi > SQI_GOOD
            if invalid:
                text, colour = "--", DASH_COLOUR
            else:
                text = f"{value:.0f}"
                colour = bright if good else dim
            # Two lines, unit then digits. There used to be a third, a small label above, and
            # between the three of them and 44pt digits the panel ran out of vertical room and
            # pushed the rows out of line. The unit line carries the identity instead — "% SpO2"
            # rather than "%" — so nothing is lost by dropping the label. It sits ABOVE the
            # digits, where it reads as their heading rather than as an afterthought.
            # <nobr> on both lines: at 100 the digits used to exceed the panel width, wrap,
            # and add a third line that pushed every row out of alignment. The height of this
            # panel must not depend on the value it is showing.
            digits = (f"font-size:{BIG_PT}pt; font-weight:bold; color:{colour}; "
                      f"line-height:100%;")
            if heart:
                # The heart follows the reading's own colour code rather than staying a fixed
                # red: a bright heart beside "--" would announce a beat that is not there.
                hue = DASH_COLOUR if invalid else (RED if good else RED_DIM)
                # A TABLE, not a span, and the reason is worth keeping. Qt accepts
                # `vertical-align:top` into the char format (it really does become
                # QTextCharFormat::AlignTop) and then paints the glyph on the baseline anyway;
                # measured in pixels, the heart had not moved. A table CELL's `valign` it does
                # honour: the heart's top then lands within 1 px of the digits' top.
                # `align='right'` floats the table, which is what keeps the line flush right --
                # text-align cannot move a table, and the alternative (a full-width spacer
                # cell) narrows the digit cell enough to wrap at three digits, the one thing
                # this panel must never do. Nothing follows this block, so the float has
                # nothing to overlap. The separating space rides inside the heart's own cell,
                # where it is a space at HEART_PT: at 44pt it would be wider than
                # panel_width() measured and the rate would wrap.
                value = (f"<table cellspacing='0' cellpadding='0' border='0' align='right'>"
                         f"<tr><td valign='top' style='font-size:{HEART_PT}pt; color:{hue};'>"
                         f"{HEART}&nbsp;</td>"
                         f"<td style='{digits}'><nobr>{text}</nobr></td></tr></table>")
            else:
                value = f"<div style='{digits}'><nobr>{text}</nobr></div>"
            return (f"<div style='margin-bottom:6px;'>"
                    f"<div style='font-size:{SMALL_PT}pt; color:{colour}; "
                    f"line-height:100%;'><nobr>{unit}</nobr></div>{value}</div>")

        return ("<div style='text-align:right;'>"
                + block(self.spo2, self.spo2_sqi, "% SpO2", SPO2_COLOUR, SPO2_DIM)
                + block(self.hr3, self.hr3_sqi, "bpm HR3", HR_COLOUR, HR_DIM, heart=True)
                + "</div>")

    def title(self, now):
        if self.is_lost(now):
            return f"{self.label()}  —  LOST {self.silent_for(now):.0f} s"
        return f"{self.label()}  —  {self.probe}"


def merge_by_mac(traces, trace):
    """A board back on a new DHCP lease is the same hardware: one band, not two. Same rule as
    fleet_monitor.py. Returns the IP whose band disappeared, or None."""
    mac = trace.mac
    if not mac:
        return None
    for ip, other in list(traces.items()):
        if other is not trace and other.mac == mac:
            newer, older = ((trace, other) if trace.last_seen >= other.last_seen
                            else (other, trace))
            newer.samples += older.samples
            newer.moved_from = older.ip
            del traces[older.ip]
            return older.ip
    return None


def panel_width():
    """How wide the numbers panel has to be for its worst case, from the real font metrics.

    It was a flat 190 px, which fitted two digits and wrapped at three — SpO2 reaching 100 was
    enough to add a line and shift every row. Measuring it here also makes it right on a display
    with a scaling factor, where a pixel guess made against one monitor is wrong on the next.
    """
    big = QtGui.QFont()
    big.setPointSize(BIG_PT)
    big.setBold(True)
    small = QtGui.QFont()
    small.setPointSize(SMALL_PT)
    heart = QtGui.QFont()
    heart.setPointSize(HEART_PT)
    # The widest line is the rate: heart, space, three digits. Measuring the digits alone would
    # hand back exactly the wrapping this function exists to prevent.
    value_w = (QtGui.QFontMetrics(big).horizontalAdvance(WIDEST_VALUE)
               + QtGui.QFontMetrics(heart).horizontalAdvance(HEART + " "))
    return max(value_w,
               QtGui.QFontMetrics(small).horizontalAdvance(WIDEST_UNIT)) + 24


def stats_font():
    """SIGNAL STATS's family at this panel's size. The same QFont is measured and painted."""
    f = QtGui.QFont(STATS_FAMILY)
    f.setPointSize(STATS_PT)
    return f


def stats_columns():
    """-> (label column px, value column px), measured from the real font metrics."""
    fm = QtGui.QFontMetrics(stats_font())
    label_w = max(fm.horizontalAdvance(row[0]) for row in STATS_ROWS) + 8
    value_w = max(fm.horizontalAdvance(VAL_CHARS),
                  max(fm.horizontalAdvance(c) for c in STATS_COLS)) + 8
    return label_w, value_w


def stats_width():
    """Width of the whole statistics panel, scrollbar included."""
    label_w, value_w = stats_columns()
    bar = QtWidgets.QApplication.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent)
    return label_w + value_w * len(STATS_COLS) + bar + 12


def make_stats_widget(width):
    """The panel: a read-only QTextEdit in the band, not a drawn label.

    A widget for three reasons. It brings a real scrollbar, which is how the rows that do not
    fit stay reachable. It clips itself, so no part of it can be painted outside the window --
    the failure that made three panels read as empty. And with its minimum height at zero its
    content has no say in how tall the band is, which is what stopped the bands being equal.
    """
    edit = QtWidgets.QTextEdit()
    edit.setReadOnly(True)
    edit.setFont(stats_font())
    edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
    edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    edit.setFrameShape(QtWidgets.QFrame.NoFrame)
    edit.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)   # read-only means read-only
    # The scrollbar is styled too: a native light-grey bar in the middle of a black window
    # reads as a piece of some other application.
    edit.setStyleSheet(
        f"QTextEdit {{ background-color:{STATS_BG}; color:{STATS_BODY}; border:none; }}"
        f"QScrollBar:vertical {{ background:{STATS_BG}; width:10px; margin:0; }}"
        f"QScrollBar::handle:vertical {{ background:#3A3A3A; min-height:20px; border-radius:4px; }}"
        f"QScrollBar::handle:vertical:hover {{ background:#585858; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:{STATS_BG}; }}")
    edit.setFixedWidth(width)
    edit.setMinimumHeight(0)
    edit.document().setDocumentMargin(2)
    return edit


class Viewer(QtWidgets.QMainWindow):
    """The window: one band per board — waveform, bedside numbers, statistics — with a drain
    timer and a redraw timer. Nothing else: no capture, no control."""

    def __init__(self, hub, window_s):
        super().__init__()
        self.setWindowTitle(f"{script_name(__file__)} — live PPG per board "
                            f"(hub {hub[0]}:{hub[1]}, read-only)")
        self._restore_geometry()
        self.window_s = window_s
        self.traces = {}
        self.aux = set()       # IPs classified as auxiliary sources (AUX_PREFIXES): no band
        self.bands = {}          # ip -> (PlotItem, PlotDataItem, LabelItem, LabelItem)
        self.band_rows = {}      # ip -> its layout row, kept apart so drop_band() stays simple
        self._next_row = 0       # monotonic: see band_for()
        self._panel_w = panel_width()
        self._stats_w = stats_width()
        self._stats_cols = stats_columns()
        self.client = HubClient(script_name(__file__), hub=hub, control=False, log=print)
        self.client.connect()

        self.layout_widget = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self.layout_widget)
        # The WINDOW refuses to be narrower than its two panels plus a usable waveform. This is
        # the lesson from the three empty tables: the panel columns are fixed width, so when the
        # window is narrower than they are, the grid overflows to the right and what does not
        # fit is simply not drawn — no scrollbar, no clue, just an empty panel. Putting the
        # minimum on the window makes that state unreachable instead of detectable. (It is NOT
        # on the layout widget: that was the first attempt, and a QScrollArea around it only
        # moved the table behind a horizontal bar, which is the same invisibility with a handle.)
        self.setMinimumWidth(self._panel_w + self._stats_w + MIN_PLOT_W + 24)   # + margins
        self._empty = self.layout_widget.addLabel("waiting for a board…", color="#888888",
                                                  size="14pt")

        self.drain_timer = QtCore.QTimer(self)
        self.drain_timer.timeout.connect(self.drain)
        self.drain_timer.start(DRAIN_MS)
        self.redraw_timer = QtCore.QTimer(self)
        self.redraw_timer.timeout.connect(self.redraw)
        self.redraw_timer.start(REDRAW_MS)

    # ── the statistics panel ──────────────────────────────────────────────────────────────
    # ── settings ──────────────────────────────────────────────────────────────────────────
    def _restore_geometry(self):
        """The saved window, or on a first run a size taken from the screen.

        It used to be a flat 1100x800, which cut the last band off as soon as there were three
        boards — a fixed pixel height cannot know how many bands there will be, nor how tall
        the display is. 88 % of the available height is a starting point; after that the file
        remembers whatever the user chose, which is the only size that is actually right.
        """
        saved = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("geometry")
        if saved is not None and self.restoreGeometry(saved):
            return
        screen = QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            self.resize(1100, 800)
            return
        self.resize(min(1200, int(area.width() * 0.6)), int(area.height() * 0.88))
        self.move(area.left() + 40, area.top() + 20)

    def _save_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("window_s", self.window_s)

    # ── network ───────────────────────────────────────────────────────────────────────────
    def drain(self):
        """Single-threaded on purpose: no locks, no cross-thread Qt calls. All this does per
        datagram is decimate and append, so it cannot starve the GUI; at ~300 datagrams/s across
        three boards a 20 ms tick sees six of them."""
        now = time.monotonic()
        for _ in range(256):
            item = self.client.recv(0.0)
            if item is None:
                break
            ip, data = item
            if ip in self.aux or (ip not in self.traces and data[:4] in AUX_PREFIXES):
                # $VN1: a phone, not a board. No band for it (the hub's D1, one floor up).
                self.aux.add(ip)
                continue
            tr = self.traces.get(ip)
            if tr is None:
                tr = self.traces[ip] = BoardTrace(ip, now, self.window_s)
            tr.feed(data, now)
            gone = merge_by_mac(self.traces, tr)
            if gone is not None:
                self.drop_band(gone)

    # ── drawing ───────────────────────────────────────────────────────────────────────────
    def drop_band(self, ip):
        band = self.bands.pop(ip, None)
        self.band_rows.pop(ip, None)
        if band is not None:
            for item in band[:1] + band[2:]:   # plot, numbers, statistics; the curve is in the plot
                self.layout_widget.removeItem(item)

    def band_for(self, ip):
        if ip in self.bands:
            return self.bands[ip]
        if self._empty is not None:
            self.layout_widget.removeItem(self._empty)
            self._empty = None
        # A counter, not len(self.bands). Dropping a band (a board back on a new DHCP lease,
        # which happens daily here) leaves its row in the layout while shrinking the dict, so
        # len() then names a row that is still occupied and pyqtgraph would place the next
        # board's plot ON TOP of an existing one — GraphicsLayout.removeItem() clears its own
        # rows[r][c] bookkeeping but the grid row stays. An emptied row collapses to no height,
        # so never reusing one costs nothing visually.
        row = self._next_row
        self._next_row += 1
        plot = self.layout_widget.addPlot(row=row, col=0)
        # Explicit minima on every item in the row, so the grid's own minimum is something this
        # window is known to satisfy. Left to their size hints, a PlotItem asks for room enough
        # for its axes and title (350 px and up, and it grows with the title text) and the
        # statistics label for its whole 25-line document — and a QGraphicsGridLayout that
        # cannot meet its minimum does not shrink, it overflows past the edge of the view.
        plot.setMinimumWidth(MIN_PLOT_W)
        plot.setMinimumHeight(60)
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setXRange(-self.window_s, 0, padding=0)
        plot.setLabel("bottom", "seconds ago")
        curve = plot.plot(pen=pg.mkPen("#44AAFF", width=1))
        numbers = self.layout_widget.addLabel("", row=row, col=1, justify="right")
        numbers.item.setTextWidth(self._panel_w)
        numbers.setMaximumWidth(self._panel_w)
        numbers.setMinimumWidth(0)
        numbers.setMinimumHeight(0)
        stats = QtWidgets.QGraphicsProxyWidget()
        stats.setWidget(make_stats_widget(self._stats_w))
        stats.setMinimumSize(0, 0)
        # The band's height is the plot's business, not the panel's. Both of these are needed
        # and were measured: with the proxy's PREFERRED height left at the QTextEdit's own size
        # hint (which follows the document, 25 rows of it), three bands came out 497/497/445 --
        # the layout satisfies preferred heights in order and the last row takes the remainder.
        # At zero, every row has the same preferred height (the plot's) and the same stretch,
        # so they are equal: 480/480/480.
        stats.setPreferredHeight(0)
        stats.setMaximumWidth(self._stats_w)
        self.layout_widget.ci.addItem(stats, row=row, col=2)
        # Every band row stretches the same, so no band can grow because of what its panel
        # happens to contain. That loop is what made the bands different heights.
        self.layout_widget.ci.layout.setRowStretchFactor(row, 1)
        # Fixed columns, so the waveform's right edge does not move when a number gains a digit
        # and the statistics stay aligned down the window, band under band.
        self.layout_widget.ci.layout.setColumnFixedWidth(1, self._panel_w)
        self.layout_widget.ci.layout.setColumnFixedWidth(2, self._stats_w)
        self.layout_widget.ci.layout.setColumnStretchFactor(0, 1)
        self.bands[ip] = (plot, curve, numbers, stats)
        self.band_rows[ip] = row
        return self.bands[ip]

    def redraw(self):
        now = time.monotonic()
        for ip, tr in sorted(self.traces.items(), key=lambda kv: kv[1].first_seen):
            tr.trim(now)
            fresh = tr.maybe_snapshot(now)
            plot, curve, numbers, stats = self.band_for(ip)
            plot.setTitle(tr.title(now), color=tr.state_colour(now), size="11pt")
            curve.setData([t - now for t in tr.t], list(tr.y))
            numbers.item.setHtml(tr.numbers_html(now))
            # Only when the second closed. Rewriting the document ten times a second would cost
            # ten times the work for the same table, and it would fight the user's scrollbar.
            if fresh or stats.widget().document().isEmpty():
                bar = stats.widget().verticalScrollBar()
                where = bar.value()
                stats.widget().setHtml(tr.stats_html(*self._stats_cols))
                bar.setValue(where)             # keep the reader where they scrolled to

    def closeEvent(self, event):
        self.drain_timer.stop()
        self.redraw_timer.stop()
        self._save_settings()
        self.client.close()
        event.accept()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--window", type=float, default=None, metavar="S",
                    help=f"seconds of signal on screen (default {WINDOW_S:.0f}, or whatever was "
                         f"last used — it is remembered in fleet_ppg_viewer.ini)")
    ap.add_argument("--opengl", action="store_true",
                    help="turn pyqtgraph's OpenGL back on — the suspect in the lab's paint "
                         "crashes, off here by default so this viewer can test it")
    args = ap.parse_args()
    print(banner(__file__, "one live PPG band per board, read-only"))

    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)

    # The experiment, and it must run before any plot widget exists. pyqtgraph's own source
    # calls the QPicture replay in AxisItem.paint a place where "sometimes we get a segfault",
    # and the lab runs it with OpenGL on.
    pg.setConfigOptions(antialias=True, useOpenGL=args.opengl)
    print(f"   pyqtgraph useOpenGL={args.opengl}  (faulthandler -> "
          f"tools/fleet_ppg_viewer_faulthandler.log)")

    app = QtWidgets.QApplication(sys.argv)
    # Explicit on the command line wins; otherwise what the last run left in the .ini; otherwise
    # the default. Saved on close either way, so --window is also how you change it for good.
    window_s = args.window
    if window_s is None:
        window_s = float(QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
                         .value("window_s", WINDOW_S))
    win = Viewer(hub, window_s)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
