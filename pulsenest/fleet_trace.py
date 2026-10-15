"""The data behind one PPG band, shared by the fleet PPG viewer and the recorder GUI -- no Qt.

Extracted from tools/fleet_ppg_viewer.py on 2026-10-13: the recorder GUI imported the viewer to get
BoardTrace and the statistics panel, and importing a program drags its side effects along (its
faulthandler log, its settings path). What lives here is what more than one window draws from:
the $M* field positions, the colours and sizes of the numbers panel, the statistics rows, the
running Stat, BoardTrace itself and merge_by_mac. The Qt-measured widgets are in
pulsenest/fleet_widgets.py; fit(), the cell rule, is here so the console monitor can use it
without Qt.
"""
import math
from collections import deque
from html import escape

# fit() belonged to the fleet monitor, the table tool and where the rule was argued out
# and debugged (a cell must never widen its column; it drops decimals, then gives up with
# '#####' rather than print a truncated digit string, which is a different number). Imported
# rather than copied: two implementations of that rule would drift. Here the column is a real
# table column measured for VAL_CHARS, so fit() is asked for that many characters and its job
# is the same one: keep a cell from making its column wider than it was measured to be.
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


PPG_FIELD    = 9      # $M3/$M4: mode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP
SPO2_FIELD, SPO2_SQI_FIELD = 10, 11
HR3_FIELD,  HR3_SQI_FIELD  = 18, 19
PROBE_FIELD  = 22
DECIM        = 10     # 500 Hz -> 50 Hz on screen
LOST_S       = 2.0
WINDOW_S     = 15.0
MIN_PLOT_W   = 300    # the window refuses to be narrower than its panels plus this
ID_KEYS      = ("mac", "board")
PROBE_STATES = {"0": "DISCONNECTED", "1": "OT_HIGH", "2": "APPLIED",
                "3": "AMB_SAT", "4": "ONLY_LED_SAT"}
APPLIED      = "APPLIED"
GREEN, RED, GREY = "#44FF88", "#FF4444", "#888888"
LINK = "#44AAFF"           # a clickable path or file name; the same blue as the PPG trace
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
