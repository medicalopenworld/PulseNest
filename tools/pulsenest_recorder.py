"""pulsenest_recorder -- the robust, headless recorder for hospital sessions (raw stream first).

Subscribes to the hub read-only and appends every datagram, byte for byte, to one `.pnraw`
stream per source, with the host's two clocks stamped at reception. No Qt, no third-party
package, nothing that paints: pyqtgraph has killed pulsenest_lab.py 28 times, and this tool
exists so that a bad paint never costs a capture again. Format and behaviour are specified in
`pulsenest_recorder_spec.md`; this file is that spec's first implementation and covers §3, §4,
§5, §6, §7, §8 and the console half of §9. The live capture CSV (§2) and the converter (§10)
come later: the raw stream carries every `$M4` field, RF included, so nothing is lost by
recording raw first and converting off-site.

    python tools/pulsenest_recorder.py --site HOSP01 [--operator AC] [--raw full|exceptions]
                                       [--hub 127.0.0.1[:5005]] [--out captures/sessions]

While it runs, the console accepts one command per line (§9 says a session must be possible
with no GUI at all):

    spo2 SUBJ01 96 [142]      a manual reading from the commercial monitor (value, optional PR)
    mark [SUBJ01] [text]      an operator mark; with no subject it is session-wide
    note [SUBJ01] <text>      a free-text note (no personal data -- coded subjects only)
    site SUBJ01 <text>        probe site of OUR probe for a subject ("left foot")
    anchor                    CLOCK_ANCHOR: written when the laptop clock is being filmed
    subject <MAC suffix> SUBJ01   bind a board to a subject (a REF_SPO2 then carries its MAC)
    truth T2 [SUBJ01]         what the capture can be checked against (T0..T3 or a word)
    cond RESTING [SUBJ01]     condition; no subject = every board
    ref SUBJ01 model|avg|site|note <value>
                              the commercial monitor beside that baby: model, averaging in
                              seconds, and ITS probe site -- pre- vs postductal differ in a
                              neonate, and an unrecorded difference is read later as our error
    consent obtained          section 11: required before anything leaves the laptop
    help [command]            the list, or the detail of one: `help mark`
    status                    one line per source: datagrams, bytes, last seen
    q | quit                  close the session (Ctrl+C does the same)

The same lines are accepted on a local UDP port (--event-port) so that a separate panel process
can send them (§9, process isolation): if the panel dies, recording continues.

Layout (§3): captures/sessions/<YYYYMMDD>_<HHMM>_<SITE>/ with session.json, session_events.csv,
pulsenest_recorder.log and raw/board_<MAC>_<NNNN>.pnraw. A source is named by its MAC as soon as its $CFG
arrives (the hub replays the cached $CFG on subscription, so normally at once); until then its
datagrams wait in memory for up to 3 s, after which they go to unknown_<IP>_<NNNN>.pnraw rather
than be dropped. A phone sending $VN1 frames is an auxiliary source, aux_vn_<ID> when its
frames carry a trailing id field and aux_vn_<IP> when they do not.

Design rules that are enforced here rather than promised:
- The recorder never sends to a board: HubClient(control=False), and there is no code path that
  calls send_to_board().
- Append only; flush every 1 s; fsync every 10 s, on split and on close; session_events.csv fsyncs on
  every row.
- One writer per source, each write in its own try/except: a failure on one board's stream is
  logged and counted and does not touch the others.
- Free space is checked at start (refuse below --min-free-gb) and every minute (stop cleanly
  rather than fill the disk).

`read_pnraw()` at the bottom is the reader the converter will build on; the test uses it to
prove that what was written round-trips exactly.
"""
import argparse
import csv
import datetime as _dt
import io
import json
import logging
import os
import platform
import re
import shutil
import socket
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from pulsenest_net import UDP_DATA_PORT, script_name           # noqa: E402
from pulsenest_hub_client import HubClient                      # noqa: E402
from pulsenest_capture_csv import CaptureCsvWriter, col_spec_all  # noqa: E402

RECORDER_VERSION = "0.1"
FORMAT_TAG = b"@PNRAW1"

# --- durability knobs (spec section 8) -------------------------------------------------------
FLUSH_S = 1.0
FSYNC_S = 10.0
FREE_SPACE_CHECK_S = 60.0
IDENTIFY_WAIT_S = 3.0            # how long a new IP's datagrams wait in memory for a $CFG (MAC)
# How long a source may stay quiet before it is called silent. Two values, because the sources
# have nothing in common in this respect: a board emits 100 datagrams/s, so 5 s of nothing is
# already 500 lost; a phone doing OCR emits when it has a reading, measured 2026-09-20 at 0,81 Hz
# with a median gap of 0,9 s, a p90 of 2,7 s and a longest of 6,5 s -- and its sequence numbers
# were CONTINUOUS throughout, so nothing was lost, it simply speaks slowly. At 5 s the phone
# tripped the alarm three times in four minutes for behaving normally, and an alarm that cries
# wolf is worse than no alarm: the one time the phone is really dead, nobody will look.
SOURCE_SILENT_S = 5.0            # boards
AUX_SILENT_S = 30.0              # auxiliary sources: ~4x the longest gap measured
SPLIT_MIN_DEFAULT = 10   # wall-clock aligned (see _split_if_due); 256 MB is the ceiling, not the usual trigger
SPLIT_MB_DEFAULT = 256

# --- what "a measurement frame the CSV represents" means for --raw exceptions -----------------
# Token count INCLUDING the tag, what pulsenest_lab.py checks (`len(row) < 36` for $M4). A batch
# datagram is skipped in `exceptions` mode only if EVERY line in it is a known measurement frame
# with exactly this many tokens; anything else -- $CFG, $ERR, # STAT, a 37th field, a frame mode
# nobody expected -- is written and counted.
EXPECTED_TOKENS = {b"$M4": 36}
# The frame tags that carry a sample counter in field 1. Matched in full, never as a bare
# `$M` prefix: another source on this wire may legitimately use a `$Mn` tag (VideoNest has
# one), and reading its sequence number as our sample counter would invent gaps and
# restarts out of nothing.
BOARD_FRAME_TAGS = (b"$M1,", b"$M2,", b"$M3,", b"$M4,")

# ============================================================================================
# console help
# ============================================================================================
# One entry per command: (usage, one-line summary, the detail `help <command>` prints).
# The detail is where the *reason* lives -- an operator at a cot side has no spec to hand, and
# the two or three rules that protect a capture (read the monitor's own screen, never correct
# for delay, name the baby) are worth having one keystroke away.
COMMAND_HELP = {
    "spo2": (
        "spo2 SUBJ01 <spo2%> [pr]",
        "a reading you took from the commercial monitor",
        "Records what the commercial oximeter shows for that baby: SpO2 in per cent, and the\n"
        "pulse rate too if the monitor shows one. Range 50-100, because a neonatal desaturation\n"
        "goes below 60 and a value you cannot type ends up in a notebook and is lost.\n"
        "\n"
        "Two rules that protect this reference:\n"
        "  * Read the number off the MONITOR's screen, never off ours. fleet_monitor.py shows\n"
        "    VideoNest's SpO2, which is the same monitor read by OCR; copying it here would make\n"
        "    the manual reading a copy of the automatic one instead of a check on it.\n"
        "  * Do not correct for delay. The instant of the keystroke is what is recorded, and the\n"
        "    monitor averages over seconds anyway. No correction is applied, and none should be\n"
        "    invented later.\n"
        "\n"
        "The board bound to that subject is stamped on the event, so bind it first with `subject`.",
    ),
    "correct": (
        "correct <event id> <spo2%> [pr]",
        "fix a reading you mistyped; the original stays in the file",
        "A mistyped reading is not erased -- nothing in a session is. A CORRECT event is written\n"
        "naming the reading it fixes, and every consumer applies it. The reading keeps its own\n"
        "time: the click happened when it happened, only the number was wrong. The event id is\n"
        "the number printed when the reading was recorded (`event 41: REF_SPO2 ...`).",
    ),
    "retract": (
        "retract <event id>",
        "withdraw a reading; it stays in the file, marked retracted",
        "For a reading that should not have been taken at all -- wrong baby, monitor was\n"
        "alarming, you pressed twice. A RETRACT event names it; the effective list drops it, the\n"
        "file keeps both, and an analysis can still see what was withdrawn and when.",
    ),
    "mark": (
        "mark [SUBJ01] <text>",
        "something happened; with no subject it is session-wide",
        "A moment worth finding again: handling, a feed, a nappy change, an alarm on the monitor,\n"
        "a probe that was moved. None of it can be reconstructed afterwards.\n"
        "\n"
        "Name the baby when it concerns one baby:  mark SUBJ02 nappy change\n"
        "Leave it out when it concerns the room:   mark phototherapy lamp on\n"
        "\n"
        "A subject written inside the free text instead of its own field is a subject no query\n"
        "will ever find. The first word is read as a subject only if it looks like SUBJ<digits>.\n"
        "The mark is copied into every board's .pnraw and CSV whoever it names, so each file\n"
        "stands alone.",
    ),
    "note": (
        "note [SUBJ01] <text>",
        "free text, same attribution rules as mark",
        "Like `mark`, for anything longer or less of a single instant. No personal data, ever:\n"
        "coded subjects only, no names, no ward, no room -- these files are health data and the\n"
        "note travels inside every stream.",
    ),
    "anchor": (
        "anchor",
        "CLOCK_ANCHOR: type it while filming the laptop clock",
        "Film the laptop's clock with the phone for a few seconds and type this while filming.\n"
        "It is what ties the video to the recording without trusting that two devices agree on\n"
        "the time -- and they do not: the phone's own timestamp was measured running 164-350 ms\n"
        "behind arrival here.",
    ),
    "subject": (
        "subject <MAC suffix> SUBJ01",
        "bind a board to a baby",
        "Ties one board to one coded subject, by the last four hex digits of its MAC (the `status`\n"
        "line shows them). Do this first: a `spo2` reading carries the bound board's MAC, and the\n"
        "CSV is renamed at close to T2_SUBJ01_RESTING_<date>_<time>.csv only when the subject,\n"
        "the truth class and the condition are all known.",
    ),
    "truth": (
        "truth T2|oximeter [SUBJ01]",
        "what this capture can be checked against; no subject = every board",
        "The class of reference that accompanies the capture, CAPTURE_SET_SPEC 2.2. It goes first\n"
        "in the CSV filename so the analysis tools can tell what a capture is allowed to prove.\n"
        "The scale climbs with the quality of the evidence:\n"
        "  T0  none       a person and nothing to compare with -- morphology only\n"
        "  T1  simulator  the MS100 at a programmed rate and SpO2\n"
        "  T2  oximeter   a commercial pulse oximeter or an ECG beside the baby (also `ecg`)\n"
        "  T3  arterial   arterial CO-oximetry; the only basis for an SpO2 calibration\n"
        "A code or a word, either is accepted. A hospital campaign is T2, and a session whose\n"
        "site is HOSPnn starts at T2 so the command is there to correct, not to remember.",
    ),
    "refs": (
        "refs SUBJ01 <src>[,<src>...]|none",
        "which references exist for that baby; the truth class follows",
        "The set of references recorded beside that baby, any combination of:\n"
        "  simulator           the MS100 is the subject\n"
        "  videonest_udp       VideoNest is sending $VN1 frames to the hub\n"
        "  videonest_csv       VideoNest is logging its own CSV on the phone\n"
        "  videonest_pictures  the phone is photographing the monitor\n"
        "  operator            you are typing `spo2` readings\n"
        "The T-class is derived, never typed: any reference beside the baby is T2, a simulator\n"
        "alone is T1, none is T0. `truth` still exists to force a class, e.g. T3 for an arterial\n"
        "study, which no tick box can claim.",
    ),
    "cond": (
        "cond RESTING [SUBJ01]",
        "condition; no subject = every board",
        "What the baby is doing, in one word: RESTING, FEEDING, HANDLING. It becomes part of the\n"
        "CSV filename, so keep it short and reuse the same words across sessions.",
    ),
    "site": (
        "site SUBJ01 <text>",
        "where OUR probe is on that baby",
        "The site of the PulseNest probe: 'left foot', 'right foot'. Not the same field as the\n"
        "commercial monitor's site, which is `ref SUBJ01 site` -- and the difference between the\n"
        "two is exactly why both must be recorded: in a neonate with a patent ductus, preductal\n"
        "(right hand) and postductal (foot) SpO2 genuinely differ by several points, and an\n"
        "unrecorded difference is read later as OUR error.",
    ),
    "ref": (
        "ref SUBJ01 model|avg|site|note <value>",
        "the commercial monitor beside that baby",
        "  ref SUBJ01 model Masimo Radical-7   make and model\n"
        "  ref SUBJ01 avg 8                    its averaging window, in seconds\n"
        "  ref SUBJ01 site right hand          where ITS probe is\n"
        "  ref SUBJ01 note ...                 anything else\n"
        "\n"
        "`avg` and `site` are not bureaucracy. The averaging sets the window our own SpO2 has to\n"
        "be averaged over before the two numbers can be compared at all; the site decides whether\n"
        "a difference is physiology or error (see `help site`).",
    ),
    "consent": (
        "consent obtained|pending|n/a",
        "consent state for this session",
        "Must be `obtained` before anything from this session leaves the laptop. `n/a` is for a\n"
        "bench run with no human subject.",
    ),
    "status": (
        "status",
        "one line per source: datagrams, gaps, CSV rows, last seen",
        "What to look at: every board you expect is listed; `dgrams` climbing; `last` under a\n"
        "second; `gaps` at zero; `csv` climbing at about 500 rows per second per board. A source\n"
        "marked SILENT has said nothing for 5 s (30 s for a phone, which speaks slowly).",
    ),
    "quit": (
        "quit",
        "close the session (Ctrl+C does the same)",
        "Writes SESSION_END, closes every file, renames each CSV to its canonical name and prints\n"
        "where everything is. Copy the whole session directory to a second disk before leaving.",
    ),
    "help": (
        "help [command]",
        "this list, or the detail of one command",
        "`help` lists every command; `help mark` explains one.",
    ),
}


# CAPTURE_SET_SPEC 2.2. The number climbs with the quality of the evidence (Alex, 2026-09-21:
# the original scale had T0 = arterial and T3 = none, which reads backwards).
TRUTH_CLASSES = ("T0", "T1", "T2", "T3")
# What the operator actually knows and ticks (Alex, 2026-09-21: "the T codes add almost nothing;
# what carries information is WHICH references exist, and they are not exclusive"). The class
# is derived from the set, never typed: any reference beside the baby is T2, a simulator alone is
# T1, nothing is T0. T3 (arterial) cannot come from this list -- it is a study, not a tick box.
TRUTH_SOURCES = ("simulator", "videonest_udp", "videonest_csv", "videonest_pictures", "operator")


def truth_from_sources(sources):
    srcs = set(sources)
    if srcs & {"videonest_udp", "videonest_csv", "videonest_pictures", "operator"}:
        return "T2"
    if "simulator" in srcs:
        return "T1"
    return "T0"

TRUTH_WORDS = {"none": "T0", "simulator": "T1", "sim": "T1", "oximeter": "T2", "ecg": "T2",
               "reference": "T2", "arterial": "T3"}

EVENT_KINDS = ("REF_SPO2", "MARK", "NOTE", "PROBE_SITE", "CARE", "ALARM", "CLOCK_ANCHOR",
               "META", "CORRECT", "RETRACT", "SESSION_START", "SESSION_END")
# CORRECT / RETRACT (2026-09-21): the operator can edit or delete a reading in the GUI, but every
# file of a session is append-only and recorded evidence is never rewritten. So an edit is a new
# event -- kind CORRECT, value/value2 = the new SpO2/PR, note `corrects=<event_id>` -- and a
# delete is a RETRACT with note `retracts=<event_id>`. The reading keeps its ORIGINAL time: the
# instant of the click is what was measured, only the number was mistyped. A consumer that wants
# the effective list applies them in order; `Recorder.readings()` is that list, computed here.   # META: session metadata typed in (subject, truth, condition, reference monitor, consent)
# `session_id` first, and it is not decoration (Alex, 2026-09-20). This is the one file in a
# session directory that travels on its own -- it gets opened in Excel, copied, and its rows
# pasted next to another session's to compare -- and it was the only one that could not say where
# it came from: the `.pnraw` says so in its `@PNRAW1 session=...` header, `session.json` in its
# `session_id` field, the log in its first line. A prefix on the FILENAME would not have helped
# the commonest case anyway, which is rows merged into one sheet where no filename survives.
EVENTS_HEADER = ["session_id", "event_id", "t_mono_us", "t_epoch_us", "iso_local", "kind",
                 "subject", "board_mac", "value", "value2", "source", "confidence", "note"]

_MAC_RE = re.compile(rb"[,\s]mac=([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
_KV_RE = re.compile(rb"[,\s]([a-z_]+)=([^,\s*]+)")
# A phone naming itself at the END of its frame:
#     $VN1,<seq>,<spo2>,<conf>,<ts_ms>,<id>*<cks>
# Appended, never inserted, so a frame without it still parses (and is still
# recorded, named by IP as before). 1-8 ASCII letters/digits set by the operator in
# the app and taped to the phone: identity that survives a DHCP lease, which is what
# the MAC does for a board.
_SUBJ_RE = re.compile(r"^SUBJ\d+$", re.I)


def normalise_subject(text):
    """`subj7` -> `SUBJ07`, `SUBJ12` -> `SUBJ12`, anything else -> None.

    The subject code is the ONLY link between a capture and a person, and the mapping lives
    outside this repository (section 11). A free-text subject is how a real name ends up in
    session_events.csv, in every .pnraw, in every CSV header and in the filename -- so this is
    checked where the value is SET, not only where it is quoted. Zero-padded to two digits so
    `SUBJ7` and `SUBJ07` cannot become two babies.
    """
    t = (text or "").strip().upper()
    if not _SUBJ_RE.match(t):
        return None
    digits = t[4:]
    return "SUBJ" + (digits.zfill(2) if len(digits) < 2 else digits)


def safe_condition(text):
    """A condition ends up in a filename, so it may only hold what a filename can."""
    t = re.sub(r"[^A-Za-z0-9-]+", "-", (text or "").strip().upper()).strip("-")
    return t[:24]
_VN_ID_RE = re.compile(rb"^\$VN1(?:,[^,*]*){4},([A-Za-z0-9_-]{1,32})\*")


# ============================================================================================
# clocks
# ============================================================================================
class NotEnoughSpace(RuntimeError):
    """Refusing to start: less free space than the floor. Its own type so main() can report it as
    one line rather than a traceback -- what an operator at a cot side needs to read."""


def _free_bytes(path):
    """Free bytes on the volume holding `path`, walking up to the first parent that exists (the
    session directory has not been created yet when this is asked)."""
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def now_us():
    """(t_mono_us, t_epoch_us): the two host clocks of spec section 4, taken together."""
    return int(time.monotonic() * 1e6), int(time.time() * 1e6)


def iso_local(t_epoch_us):
    return _dt.datetime.fromtimestamp(t_epoch_us / 1e6).astimezone().isoformat(timespec="milliseconds")


def mac_compact(mac):
    return mac.replace(":", "").upper()


def next_wall_boundary_us(t_epoch_us, period_s):
    """The next multiple of `period_s` on the LOCAL wall clock, strictly after t_epoch_us.
    Local, not UTC, because the boundary has to match the clock a person in the room reads (and
    the half-hour offsets some regions use, which a UTC-based multiple would miss). A period
    that does not divide an hour just runs from the top of the hour."""
    period_us = int(period_s * 1e6)
    if period_us <= 0:
        return t_epoch_us
    t = _dt.datetime.fromtimestamp(t_epoch_us / 1e6)
    hour = t.replace(minute=0, second=0, microsecond=0)
    hour_us = int(hour.timestamp() * 1e6)
    n = (t_epoch_us - hour_us) // period_us + 1
    return hour_us + n * period_us


# ============================================================================================
# one raw stream (one source, split into parts)
# ============================================================================================
class RawStream:
    """Append-only `.pnraw` writer for ONE source. Owns the current part file, the record
    sequence (continues across parts, so a gap in seq is a dropped record), splitting and the
    flush/fsync cadence. Every write is wrapped by the Recorder, not here: this class raises,
    the caller decides what a failure on one source means for the others."""

    def __init__(self, raw_dir, session_id, source_key, source_label, log,
                 split_s=SPLIT_MIN_DEFAULT * 60, split_bytes=SPLIT_MB_DEFAULT * 1024 * 1024):
        self.raw_dir = raw_dir
        self.session_id = session_id
        self.source_key = source_key          # MAC or IP text, as the header's source=
        self.source_label = source_label      # file stem: board_<MAC> | unknown_<IP> | aux_vn_<IP>
        self.log = log
        self.split_s = split_s
        self.split_bytes = split_bytes
        self.part = 0
        self.seq = 0
        self.f = None
        self.part_bytes = 0
        self.part_due_epoch_us = 0      # wall-clock instant this part must close at
        self.files = []
        self.records = 0
        self.bytes = 0
        self.errors = 0
        self._dirty = False
        self._last_flush = time.monotonic()
        self._last_fsync = time.monotonic()

    # ── parts ────────────────────────────────────────────────────────────────────────────
    def path(self, part):
        return os.path.join(self.raw_dir, f"{self.source_label}_{part:04d}.pnraw")

    def open_part(self, t_mono_us, t_epoch_us):
        self.part += 1
        p = self.path(self.part)
        os.makedirs(self.raw_dir, exist_ok=True)
        self.f = open(p, "ab", buffering=0)   # unbuffered: what was written is in the OS at once
        self.part_bytes = 0
        self.part_due_epoch_us = next_wall_boundary_us(t_epoch_us, self.split_s)
        self.files.append(os.path.relpath(p, os.path.dirname(self.raw_dir)).replace(os.sep, "/"))
        header = (f"@PNRAW1 session={self.session_id} source={self.source_key} "
                  f"part={self.part:04d} started={iso_local(t_epoch_us)}\n").encode("ascii")
        self._write(header)
        return p

    def _split_if_due(self, t_mono_us, t_epoch_us):
        """Split on the WALL CLOCK boundary (10:30:00, 10:40:00 ... for a 10 min period), not N
        minutes after this part happened to open. Decided 2026-09-20 with Alex: it makes a part's
        span readable without an index -- part 0004 of any session covers 10:30 to 10:40, so a
        photo taken at 10:37 is found by name -- and it lines every board's parts up with each
        other, which N-minutes-since-open does not. The byte ceiling stays as the net for a rate
        high enough to fill a part early (at 500 Hz it never fires: ~83 MB per 10 min)."""
        if self.f is None:
            return
        if t_epoch_us >= self.part_due_epoch_us or self.part_bytes >= self.split_bytes:
            why = (f"{int(self.split_s // 60)} min boundary"
                   if t_epoch_us >= self.part_due_epoch_us else f"{self.part_bytes} B reached")
            nxt = os.path.basename(self.path(self.part + 1))
            self.note(t_mono_us, t_epoch_us, f"part closed: {why} -> {nxt}")
            self.close_part()
            self.open_part(t_mono_us, t_epoch_us)

    def close_part(self):
        if self.f is not None:
            try:
                os.fsync(self.f.fileno())
            finally:
                self.f.close()
                self.f = None

    # ── records ──────────────────────────────────────────────────────────────────────────
    def datagram(self, t_mono_us, t_epoch_us, ip, data):
        """`@D <seq> <t_mono_us> <t_epoch_us> <ip> <len>\\n<bytes>\\n` -- the datagram verbatim,
        not unescaped, not validated (spec section 5)."""
        if self.f is None:
            self.open_part(t_mono_us, t_epoch_us)
        self._split_if_due(t_mono_us, t_epoch_us)
        self.seq += 1
        head = f"@D {self.seq} {t_mono_us} {t_epoch_us} {ip} {len(data)}\n".encode("ascii")
        self._write(head + data + b"\n")
        self.records += 1

    def event(self, t_mono_us, t_epoch_us, event_id, kind, text):
        if self.f is None:
            return
        self._write(f"@E {t_mono_us} {t_epoch_us} {event_id} {kind} {text}\n".encode("utf-8"))

    def note(self, t_mono_us, t_epoch_us, text):
        if self.f is None:
            return
        self._write(f"@M {t_mono_us} {t_epoch_us} {text}\n".encode("utf-8"))

    def _write(self, b):
        self.f.write(b)
        self.part_bytes += len(b)
        self.bytes += len(b)
        self._dirty = True

    # ── cadence ──────────────────────────────────────────────────────────────────────────
    def tick(self, now):
        """Called often. fsync every FSYNC_S when something was written. (The file is opened
        unbuffered, so 'flush' is implicit; the periodic fsync is what pushes it to the platter.)"""
        if self.f is None or not self._dirty:
            return
        if now - self._last_fsync >= FSYNC_S:
            os.fsync(self.f.fileno())
            self._last_fsync = now
            self._dirty = False

    def close(self):
        self.close_part()


# ============================================================================================
# a source: a board (by MAC), a not-yet-identified IP, or an auxiliary VideoNest phone
# ============================================================================================
class Source:
    def __init__(self, ip, first_mono_us, first_epoch_us):
        self.ip = ip
        self.ips = [{"ip": ip, "from": iso_local(first_epoch_us), "to": None}]
        self.mac = None
        self.kind = "board"                   # board | videonest
        self.vn_id = None                     # a phone's self-declared id, if its frames carry one
        self.ident = {}                       # k=v pairs from the $CFG (board, fw, lib, build, ...)
        self.cfg_raw = None
        self.stream = None
        self.csv = None                       # CaptureCsvWriter, for boards only (section 2)
        self.csv_path = None                  # the part being written
        self.csv_paths = []                   # every part of this source, in order
        self.csv_part = 0
        self.csv_stamp = ""                   # <date>_<time> of the FIRST part: every part shares it
        self.csv_due_epoch_us = 0             # wall-clock instant this part must close at
        self.csv_rows_total = 0               # rows across parts; src.csv.count is this part's
        self.pending = []                     # (t_mono_us, t_epoch_us, ip, data) until named
        self.first_mono_us = first_mono_us
        self.last_seen_mono = first_mono_us / 1e6
        self.silent = False
        self.dgrams = 0
        self.dgrams_skipped = 0               # not written under --raw exceptions
        self.samples = 0                      # measurement frames seen (counter followed, not parsed)
        self.last_smpcnt = None
        self.gaps = 0                         # counter jumps forward: datagrams lost on the air
        self.samples_lost = 0
        self.restarts = 0                     # counter went backwards: the board rebooted
        self.subject = None
        self.probe_site = None
        self.truth = None                     # CAPTURE_SET_SPEC section 2.2: T0 none .. T3 arterial
        self.truth_sources = []               # subset of TRUTH_SOURCES, in that order
        self.condition = None                 # RESTING, FEEDING, ...
        # The commercial monitor this baby is also wearing. Two of these are not bureaucracy
        # (spec section 7): `probe_site`, because preductal (right hand) and postductal (foot)
        # SpO2 genuinely differ in a neonate with a patent ductus and the difference would
        # otherwise be read as OUR error; and `averaging_s`, which sets the window our own SpO2
        # has to be averaged over before the two numbers can be compared at all.
        self.reference = {"make_model": None, "averaging_s": None, "probe_site": None, "notes": ""}

    def label(self):
        if self.kind == "videonest":
            return f"aux_vn_{self.vn_id or self.ip}"
        if self.mac:
            return f"board_{mac_compact(self.mac)}"
        return f"unknown_{self.ip}"

    def key(self):
        return self.mac or self.vn_id or self.ip

    def to_json(self):
        d = {"kind": self.kind, "ips": self.ips, "files": self.stream.files if self.stream else [],
             "vn_id": self.vn_id,
             "datagrams": self.dgrams, "datagrams_skipped": self.dgrams_skipped,
             "samples": self.samples, "gaps": self.gaps,
             "csv": os.path.basename(self.csv_path) if self.csv_path else None,
             "csv_files": [os.path.basename(p) for p in self.csv_paths],
             # `active`, not a null check: close() returns the part's count and leaves it in
             # place, so after the Recorder has added it to csv_rows_total a plain `self.csv.count`
             # counts the last part twice (measured: 122 410 reported against 95 065 written).
             "csv_rows": self.csv_rows_total + (self.csv.count if (self.csv and self.csv.active) else 0),
             "samples_lost": self.samples_lost, "restarts": self.restarts,
             "subject": self.subject, "probe_site": self.probe_site}
        if self.kind == "board":
            d["mac"] = self.mac
            d["truth"] = self.truth
            d["truth_sources"] = list(self.truth_sources)
            d["condition"] = self.condition
            d["reference_monitor"] = self.reference
            d["board_rev"] = self.ident.get("board")
            d["firmware"] = {k: self.ident.get(k) for k in ("fw", "lib", "build", "libsha",
                                                              "elfsha", "idfver")}
            d["firmware"]["cfg_raw"] = self.cfg_raw
        return d


# ============================================================================================
# the recorder core -- no sockets in here, so the test can drive it directly
# ============================================================================================
class Recorder:
    def __init__(self, out_root, site, operator="", raw_mode="full", csv_mode="on", hub_text="",
                 split_s=SPLIT_MIN_DEFAULT * 60, split_bytes=SPLIT_MB_DEFAULT * 1024 * 1024,
                 identify_wait_s=IDENTIFY_WAIT_S, min_free_bytes=0, log=None, clock=now_us):
        if raw_mode not in ("full", "exceptions", "off"):
            raise ValueError("raw_mode must be full | exceptions | off")
        if csv_mode not in ("on", "off"):
            raise ValueError("csv_mode must be on | off")
        self.csv_mode = csv_mode
        self.clock = clock
        self.raw_mode = raw_mode
        self.split_s = split_s
        self.split_bytes = split_bytes
        self.identify_wait_s = identify_wait_s
        self.min_free_bytes = min_free_bytes
        t_mono, t_epoch = self.clock()
        self.started = {"iso": iso_local(t_epoch), "t_mono_us": t_mono, "t_epoch_us": t_epoch}
        stamp = _dt.datetime.fromtimestamp(t_epoch / 1e6)
        self.site = re.sub(r"[^A-Za-z0-9]", "", site.upper())[:12] or "SITE"
        self.session_id = f"{stamp:%Y%m%d_%H%M}_{self.site}"
        # A hospital session is T2 by construction (a commercial monitor beside every baby), so
        # start there: the `truth` command exists to correct, not to be remembered under stress.
        self.default_truth = "T2" if self.site.startswith("HOSP") else None
        self.dir = os.path.join(out_root, self.session_id)
        self.raw_dir = os.path.join(self.dir, "raw")
        self.operator = operator
        self.hub_text = hub_text
        self.sources = {}                     # ip -> Source
        self.by_mac = {}                      # mac -> Source (the one that owns the stream)
        self.by_vn = {}                       # a phone's declared id -> Source, same idea
        self.event_id = 0
        self._readings = []          # effective REF_SPO2 list, see readings()
        self.events_written = 0
        self.errors = 0
        self.csv_errors = 0
        self.stopped = False
        self.stop_reason = None
        self.consent = "pending"     # section 11: must be `obtained` before anything leaves the laptop
        self._last_free_check = 0.0
        self.free_bytes = None

        # The directory and session.json exist BEFORE the first datagram is recorded (section 3).
        # Check the disk BEFORE creating anything: a refused start should leave no trace, not an
        # empty session directory that looks like a session nobody recorded into.
        self.free_bytes = _free_bytes(out_root)
        if self.min_free_bytes and self.free_bytes is not None and self.free_bytes < self.min_free_bytes:
            raise NotEnoughSpace(f"{self.free_bytes / 1e9:.1f} GB free on {os.path.abspath(out_root)}, "
                                 f"floor is {self.min_free_bytes / 1e9:.1f} GB")
        os.makedirs(self.dir, exist_ok=True)
        self.log = log or self._make_logger()
        self._check_free_space(force=True)
        self.events_path = os.path.join(self.dir, "session_events.csv")
        self._events_f = open(self.events_path, "a", newline="", encoding="utf-8")
        if os.path.getsize(self.events_path) == 0:
            self._events_f.write(",".join(EVENTS_HEADER) + "\n")
            self._events_f.flush()
            os.fsync(self._events_f.fileno())
        self.write_session_json()
        self.event("SESSION_START", note=f"recorder {RECORDER_VERSION} raw={raw_mode}")
        self.log.info("session %s opened in %s (raw=%s)", self.session_id, self.dir, raw_mode)

    def _make_logger(self):
        lg = logging.getLogger(f"recorder.{self.session_id}")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(os.path.join(self.dir, "pulsenest_recorder.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        lg.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        lg.addHandler(sh)
        return lg

    # ── datagrams ────────────────────────────────────────────────────────────────────────
    def feed(self, ip, data, t_mono_us=None, t_epoch_us=None):
        """One datagram from the hub (the @FROM line already stripped). Never raises: every
        failure is logged and counted, and the other sources are not affected."""
        if t_mono_us is None:
            t_mono_us, t_epoch_us = self.clock()
        src = self.sources.get(ip)
        if src is None:
            src = self.sources[ip] = Source(ip, t_mono_us, t_epoch_us)
            src.truth = self.default_truth
            if data.startswith(b"$VN1"):
                src.kind = "videonest"
            self.log.info("new source %s%s", ip, " (VideoNest)" if src.kind == "videonest" else "")
        if src.silent:
            src.silent = False
            self._note(src, t_mono_us, t_epoch_us, f"source back after silence ip={ip}")
        src.last_seen_mono = t_mono_us / 1e6
        src.dgrams += 1
        try:
            if src.kind == "videonest":
                src = self._identify_phone(src, data, t_mono_us, t_epoch_us)
            if src.kind == "board" and src.mac is None:
                self._try_identify(src, data, t_mono_us, t_epoch_us)
            elif src.kind == "board" and data.startswith(b"$CFG,"):
                self._refresh_ident(src, data)
            if src.stream is None:
                if src.kind == "videonest":
                    self._open_stream(src, t_mono_us, t_epoch_us)
                else:
                    src.pending.append((t_mono_us, t_epoch_us, ip, data))
                    if (t_mono_us - src.first_mono_us) / 1e6 >= self.identify_wait_s:
                        self._note_unknown(src, t_mono_us, t_epoch_us)
                    return
            self._record(src, t_mono_us, t_epoch_us, ip, data)
            if src.kind == "board":
                self._watch_counter(src, data, t_mono_us, t_epoch_us)
            # The CSV comes last and in its own guard: a malformed frame, an unexpected field
            # count or a bug of ours costs rows HERE and leaves the .pnraw untouched.
            self._csv_rows(src, data, t_epoch_us)
        except Exception as exc:                          # one source's failure stays its own
            self.errors += 1
            if src.stream is not None:
                src.stream.errors += 1
            self.log.error("write failed for %s: %r", src.label(), exc)

    def _record(self, src, t_mono_us, t_epoch_us, ip, data):
        if self.raw_mode == "off":
            return
        if self.raw_mode == "exceptions" and is_plain_measurement_batch(data):
            src.dgrams_skipped += 1
            return
        src.stream.datagram(t_mono_us, t_epoch_us, ip, data)

    def _csv_rows(self, src, data, t_epoch_us):
        """One datagram -> its data rows in the board's CSV. Never lets the CSV break the raw."""
        if src.csv is not None and src.csv.active:
            self._split_csv_if_due(src, t_epoch_us)
        if src.csv is None or not src.csv.active:
            return
        try:
            src.csv.write_datagram(data, t_epoch_us)
        except Exception as exc:
            self.csv_errors += 1
            self.log.error("csv row failed for %s: %r", src.label(), exc)

    def _watch_counter(self, src, data, t_mono_us, t_epoch_us):
        """Follow the firmware's sample counter to tell the operator what the raw file alone
        would not: **this board is losing packets**, or **this board rebooted**. Added
        2026-09-20 after a 25 min bench session lost 40 samples on one board at 18:15:47 — real
        WiFi loss, four minutes away from any split — with nothing on screen to say so.

        It reads the counter and nothing else: what goes into the `.pnraw` is still the datagram
        verbatim (§5), and a line it cannot parse is skipped rather than raising. The CSV writer
        will do the authoritative per-frame check (`# gap`, capture_csv_format_spec R12a); this
        is situational awareness at the cot side, and a count in `session.json`."""
        for ln in data.split(b"\n"):
            if ln[:4] not in BOARD_FRAME_TAGS:
                continue
            try:
                n = int(ln.split(b",", 2)[1])
            except (IndexError, ValueError):
                continue
            src.samples += 1
            prev = src.last_smpcnt
            src.last_smpcnt = n
            if prev is None:
                continue
            if n == prev + 1:
                continue
            if n < prev:
                # The counter only goes backwards when the board restarted (§8: normal, noted).
                src.restarts += 1
                self._note(src, t_mono_us, t_epoch_us,
                           f"board restarted: sample counter {prev} -> {n}")
                self.log.warning("%s restarted (counter %d -> %d)", src.label(), prev, n)
            else:
                lost = n - prev - 1
                src.gaps += 1
                src.samples_lost += lost
                self._note(src, t_mono_us, t_epoch_us,
                           f"gap: {lost} samples lost, counter {prev} -> {n}")
                self.log.warning("%s gap: %d samples lost (%d -> %d)", src.label(), lost, prev, n)

    def _identify_phone(self, src, data, t_mono_us, t_epoch_us):
        """Read a phone's self-declared id and treat it the way a board's MAC is treated: the
        same phone on a new DHCP lease continues in the SAME file. Returns the source that owns
        the stream from here on (itself, or the one it was merged into)."""
        if src.vn_id is not None:
            return src
        m = _VN_ID_RE.match(data.split(b"\n", 1)[0].rstrip(b"\r"))
        if not m:
            return src                        # a frame with no id: named by IP, as before
        src.vn_id = m.group(1).decode("ascii")
        owner = self.by_vn.get(src.vn_id)
        if owner is not None and owner is not src:
            owner.ips[-1]["to"] = iso_local(t_epoch_us)
            owner.ips.append({"ip": src.ip, "from": iso_local(t_epoch_us), "to": None})
            owner.dgrams += src.dgrams
            old_ip, owner.ip = owner.ip, src.ip
            self.sources[src.ip] = owner
            for rec in src.pending:
                owner.stream.datagram(*rec)
            src.pending = []
            self._note(owner, t_mono_us, t_epoch_us,
                       f"source moved ip={old_ip} -> {src.ip} (vn_id={owner.vn_id})")
            self.log.info("%s moved %s -> %s", owner.label(), old_ip, src.ip)
            return owner
        self.by_vn[src.vn_id] = src
        self.log.info("phone %s identifies as %s", src.ip, src.vn_id)
        return src

    def _try_identify(self, src, data, t_mono_us, t_epoch_us):
        m = _MAC_RE.search(data) if data.startswith(b"$CFG,") else None
        if not m:
            return
        mac = m.group(1).decode("ascii").upper()
        src.mac = mac
        src.cfg_raw = data.split(b"\n", 1)[0].rstrip(b"\r").decode("ascii", "replace")
        src.ident = {k.decode(): v.decode("ascii", "replace") for k, v in _KV_RE.findall(data)}
        owner = self.by_mac.get(mac)
        if owner is not None and owner is not src:
            # The same board back on a new DHCP lease: continue in ITS file (section 5).
            owner.ips[-1]["to"] = iso_local(t_epoch_us)
            owner.ips.append({"ip": src.ip, "from": iso_local(t_epoch_us), "to": None})
            owner.dgrams += src.dgrams
            owner.samples += src.samples
            owner.cfg_raw, owner.ident = src.cfg_raw, src.ident
            old_ip = owner.ip
            owner.ip = src.ip
            self.sources[src.ip] = owner
            owner.pending.extend(src.pending)
            self._note(owner, t_mono_us, t_epoch_us, f"source moved ip={old_ip} -> {src.ip}")
            src.pending = []
            for rec in owner.pending:
                owner.stream.datagram(*rec)
            owner.pending = []
            self.log.info("%s moved %s -> %s", owner.label(), old_ip, src.ip)
            # From here on this IP's datagrams are the owner's; the caller's `src` is stale,
            # so redirect it before the caller records.
            src.stream = owner.stream
            src.mac = owner.mac
            return
        self.by_mac[mac] = src
        self._open_stream(src, t_mono_us, t_epoch_us)
        ident = " ".join(f"{k}={src.ident[k]}" for k in ("board", "fw", "lib", "build", "elfsha")
                         if k in src.ident)
        self._note(src, t_mono_us, t_epoch_us, f"identified: mac={mac} {ident}".rstrip())
        self.log.info("identified %s as %s (%s)", src.ip, mac, ident)

    def _refresh_ident(self, src, data):
        src.cfg_raw = data.split(b"\n", 1)[0].rstrip(b"\r").decode("ascii", "replace")
        src.ident = {k.decode(): v.decode("ascii", "replace") for k, v in _KV_RE.findall(data)}

    def _open_csv(self, src, t_epoch_us):
        """The live capture CSV of section 2, one per board, in the format every tool in this
        project already reads -- Flow CSV Viewer included, which is the reason it cannot wait for
        the v0.4 format and its column dictionary. Written AFTER the .pnraw record and inside its
        own try/except (section 2.2), so a parsing bug costs rows here and nothing there.

        The name is provisional: the subject is bound by a person seconds or minutes after the
        board starts streaming, so the file opens as <MAC>_<date>_<time>.csv and is renamed at
        close to the CAPTURE_SET_SPEC 2.4 shape once truth, subject and condition are known."""
        if self.csv_mode == "off" or src.kind != "board":
            return
        if not src.csv_stamp:
            src.csv_stamp = _dt.datetime.fromtimestamp(t_epoch_us / 1e6).strftime("%Y%m%d_%H%M%S")
        prev = f"p{src.csv_part:02d}" if src.csv_part else ""   # the part that is closing, if any
        src.csv_part += 1
        name = (f"{mac_compact(src.mac) if src.mac else src.ip}_{src.csv_stamp}"
                f"_p{src.csv_part:02d}.csv")
        src.csv_path = os.path.join(self.dir, name)
        src.csv_paths.append(src.csv_path)
        src.csv = CaptureCsvWriter(src.csv_path, col_spec_all(), host_t_us=True,
                                   label=src.mac or src.ip)
        notes = [f"session={self.session_id}", f"writer=pulsenest_recorder/{RECORDER_VERSION}",
                 f"source_ip={src.ip}", f"part={src.csv_part}"]
        if prev:
            # R33's `prev`, as a PART NUMBER and not a file name: a live part opens under a
            # provisional name and every part is renamed at close, so a name written here would
            # point at a file that no longer exists. All parts of a capture share a stem.
            notes.append(f"prev={prev}")
        if src.cfg_raw:
            notes.append(f"from-board: {src.cfg_raw}")
        src.csv.open("\n".join(notes))
        src.csv_due_epoch_us = (next_wall_boundary_us(t_epoch_us, self.split_s)
                                if self.split_s else 0)
        self.log.info("%s -> %s", src.label(), name)

    def _split_csv_if_due(self, src, t_epoch_us):
        """Close this part and open the next, on the SAME wall-clock boundary as the .pnraw.

        The same boundary is the point: part 3 of the CSV and part 3 of the .pnraw then cover the
        same ten minutes, so the two can be paired without reading either. Aligned to the clock
        rather than to the start of the session, for the reason in section 2.3: a person reading
        a file name should be able to say what window it holds.
        """
        if not src.csv_due_epoch_us or t_epoch_us < src.csv_due_epoch_us:
            return
        try:
            src.csv_rows_total += src.csv.close(f"rows={src.csv.count} skipped={src.csv.skipped} "
                                                f"split=wall-clock")
            self._open_csv(src, t_epoch_us)
        except OSError as exc:
            self.csv_errors += 1
            self.log.error("csv split failed for %s: %r", src.label(), exc)
            src.csv_due_epoch_us = 0          # stop trying; the current part keeps the rows

    def _open_stream(self, src, t_mono_us, t_epoch_us):
        if self.raw_mode == "off":
            src.stream = _NullStream()
            src.pending = []
            return
        src.stream = RawStream(self.raw_dir, self.session_id, src.key(), src.label(), self.log,
                               self.split_s, self.split_bytes)
        src.stream.open_part(t_mono_us, t_epoch_us)
        self._open_csv(src, t_epoch_us)
        for rec in src.pending:                       # what waited for the name, in order
            src.stream.datagram(*rec)
            self._csv_rows(src, rec[3], rec[1])
        src.pending = []
        self.write_session_json()

    def _note_unknown(self, src, t_mono_us, t_epoch_us):
        self.log.warning("no $CFG from %s after %.0f s: recording as %s",
                         src.ip, self.identify_wait_s, src.label())
        self._open_stream(src, t_mono_us, t_epoch_us)
        self._note(src, t_mono_us, t_epoch_us,
                   f"unidentified: no $CFG within {self.identify_wait_s:.0f} s, named by ip")

    def _note(self, src, t_mono_us, t_epoch_us, text):
        if src.stream is not None:
            try:
                src.stream.note(t_mono_us, t_epoch_us, text)
            except Exception as exc:
                self.errors += 1
                self.log.error("note failed for %s: %r", src.label(), exc)

    # ── events (section 6) ───────────────────────────────────────────────────────────────
    def event(self, kind, subject="*", board_mac="*", value="", value2="", source="keyboard",
              confidence="", note=""):
        """One row in session_events.csv (flush + fsync at once) and an @E copy in every open stream."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        t_mono_us, t_epoch_us = self.clock()
        self.event_id += 1
        row = [self.session_id, self.event_id, t_mono_us, t_epoch_us, iso_local(t_epoch_us),
               kind, subject, board_mac, value, value2, source, confidence, note]
        w = csv.writer(self._events_f, lineterminator="\n")
        w.writerow(row)
        self._events_f.flush()
        os.fsync(self._events_f.fileno())
        self.events_written += 1
        self._track_reading(kind, self.event_id, iso_local(t_epoch_us), t_epoch_us, subject,
                            board_mac, value, value2, note)
        text = f"subject={subject} board={board_mac}"
        if value != "":
            text += f" value={value}"
        if value2 != "":
            text += f" value2={value2}"
        text += f" source={source}"
        if note:
            text += " note=" + note.replace("\n", " ")
        for src in self._owners():
            self._note_event(src, t_mono_us, t_epoch_us, kind, text)
            # The same event, in the CSV's own idiom: '# event @row N: ...' with the post-notes.
            if src.csv is not None and src.csv.active:
                src.csv.add_event(f"{kind} {text}")
        self.log.info("event %d %s %s", self.event_id, kind, text)
        return self.event_id

    def _track_reading(self, kind, eid, iso, t_epoch_us, subject, board_mac, value, value2, note):
        if kind == "REF_SPO2":
            self._readings.append({"id": eid, "iso": iso, "t_epoch_us": t_epoch_us,
                                   "subject": subject, "board_mac": board_mac, "spo2": value,
                                   "pr": value2, "corrected_by": None, "retracted_by": None})
        elif kind in ("CORRECT", "RETRACT"):
            ref = int(note.split("=", 1)[1])
            for r in self._readings:
                if r["id"] == ref:
                    if kind == "CORRECT":
                        r["spo2"], r["pr"], r["corrected_by"] = value, value2, eid
                    else:
                        r["retracted_by"] = eid

    def _reading(self, eid):
        for r in self._readings:
            if r["id"] == eid and r["retracted_by"] is None:
                return r
        return None

    def readings(self, subject=None, include_retracted=False):
        """The effective list of commercial-monitor readings: REF_SPO2 with CORRECTs applied and
        RETRACTs removed, in the order they were taken. For the GUI's annotation list."""
        return [dict(r) for r in self._readings
                if (subject is None or r["subject"] == subject)
                and (include_retracted or r["retracted_by"] is None)]

    def _note_event(self, src, t_mono_us, t_epoch_us, kind, text):
        if src.stream is not None:
            try:
                src.stream.event(t_mono_us, t_epoch_us, self.event_id, kind, text)
            except Exception as exc:
                self.errors += 1
                self.log.error("@E failed for %s: %r", src.label(), exc)

    def console(self, line):
        """A console / panel command (section 9). Returns a reply string; 'quit' stops."""
        parts = line.strip().split()
        if not parts:
            return ""
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd in ("q", "quit", "exit"):
                self.stop("operator")
                return "closing"
            if cmd == "spo2":
                if len(args) < 2:
                    return "usage: spo2 SUBJ01 <spo2%> [pr]"
                subj, val = args[0].upper(), int(args[1])
                if not 50 <= val <= 100:
                    return "SpO2 must be 50..100"
                pr = int(args[2]) if len(args) > 2 else ""
                mac = self._mac_for_subject(subj)
                eid = self.event("REF_SPO2", subject=subj, board_mac=mac, value=val, value2=pr)
                return f"event {eid}: REF_SPO2 {subj}={val}" + (f" PR={pr}" if pr != "" else "")
            if cmd in ("correct", "retract"):
                # `correct 41 97 [pr]` / `retract 41`: by the event id printed when it was recorded.
                if not args or not args[0].isdigit():
                    return f"usage: {cmd} <event id>" + (" <spo2%> [pr]" if cmd == "correct" else "")
                target = self._reading(int(args[0]))
                if target is None:
                    return f"no reading with event id {args[0]} (or already retracted)"
                if cmd == "retract":
                    eid = self.event("RETRACT", subject=target["subject"], board_mac=target["board_mac"],
                                     note=f"retracts={target['id']}")
                    return f"event {eid}: RETRACT reading {target['id']} ({target['subject']}={target['spo2']})"
                if len(args) < 2:
                    return "usage: correct <event id> <spo2%> [pr]"
                val = int(args[1])
                if not 50 <= val <= 100:
                    return "SpO2 must be 50..100"
                pr = int(args[2]) if len(args) > 2 else ""
                old = target["spo2"]          # event() applies the correction to this very dict
                eid = self.event("CORRECT", subject=target["subject"], board_mac=target["board_mac"],
                                 value=val, value2=pr, note=f"corrects={target['id']}")
                return (f"event {eid}: CORRECT reading {target['id']} {target['subject']}"
                        f" {old}->{val}" + (f" PR={pr}" if pr != "" else ""))
            if cmd in ("mark", "note"):
                # An optional leading SUBJnn, exactly as `spo2` and `site` take one. Without it
                # the event is session-wide, which is right for "phototherapy on" and wrong for
                # "nappy change": before this (2026-09-20) the only way to say which baby a mark
                # concerned was to write it in the free text, where no query will ever find it.
                subj, text = "*", " ".join(args)
                if args and _SUBJ_RE.match(args[0]):
                    subj, text = args[0].upper(), " ".join(args[1:])
                kind = "MARK" if cmd == "mark" else "NOTE"
                eid = self.event(kind, subject=subj, board_mac=self._mac_for_subject(subj),
                                 note=text)
                return f"event {eid}: {kind}" + (f" {subj}" if subj != "*" else " (session-wide)")
            if cmd == "anchor":
                eid = self.event("CLOCK_ANCHOR", note="laptop clock filmed")
                return f"event {eid}: CLOCK_ANCHOR at {iso_local(self.clock()[1])}"
            if cmd == "site":
                if len(args) < 2:
                    return "usage: site SUBJ01 <probe site text>"
                subj, text = args[0].upper(), " ".join(args[1:])
                for s in self._owners():
                    if s.subject == subj:
                        s.probe_site = text
                eid = self.event("PROBE_SITE", subject=subj, board_mac=self._mac_for_subject(subj),
                                 note=text)
                self.write_session_json()
                return f"event {eid}: PROBE_SITE {subj} {text}"
            if cmd == "subject":
                if len(args) < 2:
                    return "usage: subject <MAC or last 4 hex> SUBJ01"
                s = self._source_for_mac(args[0])
                if s is None:
                    return f"no board matching {args[0]}"
                subj = normalise_subject(args[1])
                if subj is None:
                    return (f"{args[1]!r} is not a subject code. It must be SUBJ followed by "
                            f"digits (SUBJ01, SUBJ12) -- never a name, an initial or a bed "
                            f"number: this code travels into every file of the session.")
                s.subject = subj
                self.event("META", subject=s.subject, board_mac=s.mac or "*",
                           note=f"subject={s.subject} board={s.label()}")
                self.write_session_json()
                return f"{s.label()} -> {s.subject}"
            if cmd == "refs":
                # `refs SUBJ01 videonest_udp,operator` -- the set of references that exist for
                # that baby; `refs SUBJ01 none` clears it. The T-class follows from the set.
                if len(args) != 2 or not _SUBJ_RE.match(args[0]):
                    return "usage: refs SUBJ01 <src>[,<src>...]|none   (" + ",".join(TRUTH_SOURCES) + ")"
                subj = args[0].upper()
                wanted = [] if args[1].lower() == "none" else args[1].lower().split(",")
                bad = [w for w in wanted if w not in TRUTH_SOURCES]
                if bad:
                    return "unknown reference " + ", ".join(bad) + "; known: " + ", ".join(TRUTH_SOURCES)
                targets = [t for t in self._owners() if t.kind == "board" and t.subject == subj]
                if not targets:
                    return f"no board for {subj}"
                ordered = [x for x in TRUTH_SOURCES if x in wanted]
                for t in targets:
                    t.truth_sources = list(ordered)
                    t.truth = truth_from_sources(ordered)
                self.event("META", subject=subj, board_mac=self._mac_for_subject(subj),
                           note=f"refs={','.join(ordered) or 'none'} truth={targets[0].truth}")
                self.write_session_json()
                return f"refs={','.join(ordered) or 'none'} truth={targets[0].truth} on {subj}"
            if cmd in ("truth", "cond"):
                # `truth T2` / `cond RESTING` apply to every board; a trailing SUBJnn narrows it.
                if not args:
                    return f"usage: {cmd} <value> [SUBJ01]"
                value = args[0].upper() if cmd == "truth" else " ".join(args).upper()
                subj = None
                if len(args) > 1 and args[-1].upper().startswith("SUBJ"):
                    subj = args[-1].upper()
                    value = args[0].upper() if cmd == "truth" else " ".join(args[:-1]).upper()
                if cmd == "cond":
                    value = safe_condition(value)
                    if not value:
                        return "a condition must hold at least one letter or digit"
                if cmd == "truth":
                    value = TRUTH_WORDS.get(value.lower(), value)
                    if value not in TRUTH_CLASSES:
                        return ("truth must be one of " + ", ".join(TRUTH_CLASSES) + " or a word: "
                                + ", ".join(sorted(TRUTH_WORDS)))
                targets = [s for s in self._owners()
                           if s.kind == "board" and (subj is None or s.subject == subj)]
                if not targets:
                    return f"no board {'for ' + subj if subj else 'yet'}"
                for s in targets:
                    setattr(s, "truth" if cmd == "truth" else "condition", value)
                self.event("META", subject=subj or "*", note=f"{cmd}={value}")
                self.write_session_json()
                return f"{cmd}={value} on " + ", ".join(s.subject or s.label() for s in targets)
            if cmd == "ref":
                # The commercial monitor beside this baby (spec section 7).
                if len(args) < 3 or args[1].lower() not in ("model", "avg", "site", "note"):
                    return "usage: ref SUBJ01 model|avg|site|note <value...>"
                subj, key, value = args[0].upper(), args[1].lower(), " ".join(args[2:])
                targets = [s for s in self._owners() if s.subject == subj]
                if not targets:
                    return f"no board bound to {subj} (use: subject <MAC suffix> {subj})"
                field = {"model": "make_model", "avg": "averaging_s", "site": "probe_site",
                         "note": "notes"}[key]
                if key == "avg":
                    value = float(value)
                for s in targets:
                    s.reference[field] = value
                self.event("META", subject=subj, board_mac=targets[0].mac or "*",
                           note=f"reference_monitor.{field}={value}")
                self.write_session_json()
                return f"{subj} reference_monitor.{field} = {value}"
            if cmd == "consent":
                if not args or args[0].lower() not in ("obtained", "pending", "n/a"):
                    return "usage: consent obtained|pending|n/a"
                self.consent = args[0].lower()
                self.event("META", note=f"consent={self.consent}")
                self.write_session_json()
                return f"consent = {self.consent}"
            if cmd in ("help", "?"):
                if args:
                    what = args[0].lower().lstrip("-")
                    entry = COMMAND_HELP.get(what)
                    if entry is None:
                        return (f"no command {what!r}. Known: "
                                + ", ".join(sorted(COMMAND_HELP)))
                    usage, summary, detail = entry
                    return f"{usage}\n  {summary}\n\n{detail}"
                width = max(len(u) for u, _, _ in COMMAND_HELP.values())
                lines = [f"  {u:<{width}s}  {summary}"
                         for u, summary, _ in COMMAND_HELP.values()]
                return "\n".join(lines + ["", "  `help <command>` explains one of them."])
            if cmd == "status":
                return self.status_text()
            return f"unknown command {cmd!r} — type `help`"
        except Exception as exc:
            return f"error: {exc}"

    def owners(self):
        """Every distinct source, boards and phones, in first-seen order. Public: the GUI
        draws from this and must not reach for a private name."""
        return self._owners()

    def _owners(self):
        seen, out = set(), []
        for s in self.sources.values():
            if id(s) not in seen:
                seen.add(id(s))
                out.append(s)
        return out

    def _mac_for_subject(self, subj):
        if subj == "*":
            return "*"
        for s in self._owners():
            if s.subject == subj and s.mac:
                return s.mac
        return "*"

    def _source_for_mac(self, text):
        t = text.upper().replace(":", "")
        for s in self._owners():
            if s.mac and mac_compact(s.mac).endswith(t):
                return s
        return None

    # ── housekeeping (section 8) ─────────────────────────────────────────────────────────
    def tick(self, now=None):
        """Call a few times a second: fsync cadence, silence notes, disk check."""
        now = time.monotonic() if now is None else now
        t_mono_us, t_epoch_us = self.clock()
        for src in self._owners():
            if src.stream is None and src.pending and src.kind == "board":
                if (t_mono_us - src.first_mono_us) / 1e6 >= self.identify_wait_s:
                    try:
                        self._note_unknown(src, t_mono_us, t_epoch_us)
                    except Exception as exc:
                        self.errors += 1
                        self.log.error("could not open stream for %s: %r", src.ip, exc)
            if src.stream is not None:
                try:
                    src.stream.tick(now)
                except Exception as exc:
                    self.errors += 1
                    self.log.error("fsync failed for %s: %r", src.label(), exc)
                quiet_s = SOURCE_SILENT_S if src.kind == "board" else AUX_SILENT_S
                if not src.silent and now - src.last_seen_mono >= quiet_s:
                    src.silent = True
                    self._note(src, t_mono_us, t_epoch_us,
                               f"source silent for {quiet_s:.0f} s")
                    self.log.warning("%s silent", src.label())
        if now - self._last_free_check >= FREE_SPACE_CHECK_S:
            self._check_free_space()

    def _check_free_space(self, force=False):
        self._last_free_check = time.monotonic()
        try:
            self.free_bytes = shutil.disk_usage(self.dir).free
        except OSError:
            self.free_bytes = None
            return
        if self.min_free_bytes and self.free_bytes < self.min_free_bytes and not force:
            self.log.error("free space %.1f GB below floor %.1f GB: stopping cleanly",
                           self.free_bytes / 1e9, self.min_free_bytes / 1e9)
            self.stop("disk")
        elif self.min_free_bytes and self.free_bytes < 2 * self.min_free_bytes:
            self.log.warning("free space %.1f GB", self.free_bytes / 1e9)

    def status_text(self):
        lines = []
        for s in self._owners():
            st = s.stream
            files = st.files[-1] if st is not None and st.files else "-"
            loss = (f"gaps={s.gaps} lost={s.samples_lost}" if s.gaps else "gaps=0")
            lines.append(f"{s.label():28s} ip={s.ip:15s} dgrams={s.dgrams:7d} "
                         f"skipped={s.dgrams_skipped:6d} {loss:18s} "
                         f"{('restarts=' + str(s.restarts) + ' ') if s.restarts else ''}"
                         f"bytes={(st.bytes if st else 0):10d} "
                         f"subject={s.subject or '-'} csv={(s.csv.count if s.csv else 0):7d} "
                         f"last={time.monotonic() - s.last_seen_mono:5.1f}s "
                         f"{'SILENT ' if s.silent else ''}{files}")
        return "\n".join(lines) if lines else "(no sources yet)"

    # ── session.json (section 7) ─────────────────────────────────────────────────────────
    def session_dict(self, closed=None):
        return {
            "schema": "pulsenest_session/1",
            "session_id": self.session_id,
            "site_code": self.site,
            "operator": self.operator,
            "started": self.started,
            "closed": closed,
            "host": {"hostname": platform.node(), "recorder_version": RECORDER_VERSION,
                     "hub": self.hub_text, "python": platform.python_version(),
                     "timezone": time.strftime("%Z"), "raw_mode": self.raw_mode},
            "sources": [s.to_json() for s in self._owners()],
            "events": self.events_written,
            "write_errors": self.errors, "csv_errors": self.csv_errors,
            "consent": self.consent,
            "notes": "",
        }

    def write_session_json(self, closed=None):
        p = os.path.join(self.dir, "session.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.session_dict(closed), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    # ── stop ─────────────────────────────────────────────────────────────────────────────
    def _name_csv(self, src):
        """Rename EVERY part of this source's CSV to the CAPTURE_SET_SPEC 2.4 shape, now that the
        metadata typed during the session is known. Provisional names kept when it is not.

        All parts or none: a directory holding `T2_SUBJ01_RESTING_..._p01.csv` beside
        `1051DB508850_..._p02.csv` would read as two different captures.
        """
        if not (src.truth and src.subject and src.condition):
            return
        stem = "_".join([src.truth, src.subject, src.condition.replace(" ", "-"), src.csv_stamp])
        renamed = []
        for path in src.csv_paths:
            if not os.path.exists(path):
                renamed.append(path)
                continue
            part = os.path.basename(path).rsplit("_", 1)[-1]        # 'pNN.csv'
            target = os.path.join(self.dir, f"{stem}_{part}")
            try:
                os.replace(path, target)
                renamed.append(target)
            except OSError as exc:
                self.log.warning("could not rename %s: %r", os.path.basename(path), exc)
                renamed.append(path)
        src.csv_paths = renamed
        if renamed:
            src.csv_path = renamed[-1]

    def stop(self, reason="operator"):
        if not self.stopped:
            self.stopped = True
            self.stop_reason = reason

    def close(self):
        """SESSION_END, every stream fsynced and closed, session.json updated. Idempotent."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        try:
            self.event("SESSION_END", note=f"reason={self.stop_reason or 'operator'}")
        except Exception as exc:
            self.log.error("SESSION_END failed: %r", exc)
        for src in self._owners():
            if src.csv is not None and src.csv.active:
                try:
                    rows = src.csv.close(f"rows={src.csv.count} skipped={src.csv.skipped} "
                                         f"gaps={src.gaps} samples_lost={src.samples_lost}")
                    src.csv_rows_total += rows
                    self._name_csv(src)
                    self.log.info("%s csv: %d rows in %d part(s), %d non-data lines skipped -> %s",
                                  src.label(), src.csv_rows_total, len(src.csv_paths),
                                  src.csv.skipped, os.path.basename(src.csv_path))
                except Exception as exc:
                    self.csv_errors += 1
                    self.log.error("csv close failed for %s: %r", src.label(), exc)
            if src.stream is not None:
                try:
                    src.stream.close()
                except Exception as exc:
                    self.errors += 1
                    self.log.error("close failed for %s: %r", src.label(), exc)
        t_mono, t_epoch = self.clock()
        drift = (t_epoch - t_mono) - (self.started["t_epoch_us"] - self.started["t_mono_us"])
        closed = {"iso": iso_local(t_epoch), "t_mono_us": t_mono, "t_epoch_us": t_epoch,
                  "clock_drift_us": drift}
        self.write_session_json(closed)
        try:
            self._events_f.flush()
            os.fsync(self._events_f.fileno())
            self._events_f.close()
        except OSError:
            pass
        self.log.info("session %s closed (%s); %d events, %d write errors -> %s",
                      self.session_id, self.stop_reason, self.events_written, self.errors, self.dir)


class _NullStream:
    """--raw off: a source still needs somewhere for its bookkeeping, and nothing on disk."""
    files = []
    bytes = 0
    errors = 0
    records = 0

    def datagram(self, *a):
        pass

    def event(self, *a):
        pass

    def note(self, *a):
        pass

    def tick(self, now):
        pass

    def close(self):
        pass


# ============================================================================================
# frame classification for --raw exceptions
# ============================================================================================
def is_plain_measurement_batch(data):
    """True when every line of the datagram is a known measurement frame with exactly the
    expected token count -- i.e. a datagram the capture CSV represents completely. A batch is
    judged as a whole: one odd line and the whole datagram is kept."""
    lines = [ln for ln in data.split(b"\n") if ln.strip(b"\r")]
    if not lines:
        return False
    for ln in lines:
        ln = ln.rstrip(b"\r")
        tag, _, _ = ln.partition(b",")
        want = EXPECTED_TOKENS.get(tag)
        if want is None:
            return False
        body = ln.split(b"*", 1)[0]
        if body.count(b",") + 1 != want:
            return False
    return True


# ============================================================================================
# reader -- the converter's seed, and the test's proof of round-trip
# ============================================================================================
def read_pnraw(path):
    """Yield the records of one `.pnraw` file as tuples:
        ("H", header_fields_dict)
        ("D", seq, t_mono_us, t_epoch_us, ip, data_bytes)
        ("E", t_mono_us, t_epoch_us, event_id, kind, text)
        ("M", t_mono_us, t_epoch_us, text)
    Follows the <len> of every @D, so a source line that happened to start with '@' could not
    fool it. Refuses a file whose first line is not @PNRAW1 (spec section 5)."""
    with open(path, "rb") as f:
        first = f.readline()
        if not first.startswith(FORMAT_TAG + b" "):
            raise ValueError(f"{path}: not a PNRAW1 file (first line {first[:20]!r})")
        hdr = dict(kv.split("=", 1) for kv in first[len(FORMAT_TAG) + 1:].decode().split()
                   if "=" in kv)
        yield ("H", hdr)
        while True:
            line = f.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                # A recorder line without its newline is a torn tail (the laptop died mid-write),
                # not a shorter record: say so instead of handing back half a line as data.
                raise ValueError(f"{path}: truncated tail, last line {line[:40]!r}")
            if line.startswith(b"@D "):
                p = line.split(b" ", 5)
                n = int(p[5])
                data = f.read(n)
                if len(data) != n:
                    raise ValueError(f"{path}: truncated @D {p[1].decode()} ({len(data)}/{n} B)")
                nl = f.read(1)
                if nl not in (b"\n", b""):
                    raise ValueError(f"{path}: @D {p[1].decode()} not followed by newline")
                yield ("D", int(p[1]), int(p[2]), int(p[3]), p[4].decode(), data)
            elif line.startswith(b"@E "):
                p = line.rstrip(b"\n").split(b" ", 5)
                yield ("E", int(p[1]), int(p[2]), int(p[3]), p[4].decode(),
                       p[5].decode("utf-8", "replace") if len(p) > 5 else "")
            elif line.startswith(b"@M "):
                p = line.rstrip(b"\n").split(b" ", 3)
                yield ("M", int(p[1]), int(p[2]), p[3].decode("utf-8", "replace") if len(p) > 3 else "")
            else:
                raise ValueError(f"{path}: unexpected line outside a record: {line[:40]!r}")


# ============================================================================================
# main loop -- the only place that touches sockets
# ============================================================================================
class _ConsoleReader(threading.Thread):
    """stdin lines -> queue. A thread because stdin has no timeout; daemon so it never blocks
    the exit."""

    def __init__(self, sink):
        super().__init__(daemon=True)
        self.sink = sink

    def run(self):
        try:
            for line in sys.stdin:
                self.sink(line)
        except (OSError, ValueError):
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", required=True, help="short site code for the session id (HOSP01, BENCH)")
    ap.add_argument("--operator", default="", help="initials or role, never a full name")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]")
    ap.add_argument("--out", default=os.path.join(_ROOT, "captures", "sessions"))
    ap.add_argument("--raw", default="full", choices=("full", "exceptions", "off"))
    ap.add_argument("--csv", default="on", choices=("on", "off"),
                    help="write the live capture CSV per board beside the .pnraw")
    ap.add_argument("--split-min", type=float, default=SPLIT_MIN_DEFAULT,
                    help="split the raw stream on this wall-clock period, in minutes")
    ap.add_argument("--split-mb", type=float, default=SPLIT_MB_DEFAULT)
    ap.add_argument("--min-free-gb", type=float, default=2.0)
    ap.add_argument("--event-port", type=int, default=0,
                    help="local UDP port that accepts the console commands from a panel process")
    ap.add_argument("--duration", type=float, default=0.0, help="seconds; 0 = until quit")
    args = ap.parse_args(argv)

    host, _, port = args.hub.partition(":")
    hub = (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)
    try:
        rec = Recorder(args.out, args.site, args.operator, args.raw, args.csv,
                       hub_text=f"{hub[0]}:{hub[1]}",
                       split_s=args.split_min * 60, split_bytes=int(args.split_mb * 1024 * 1024),
                       min_free_bytes=int(args.min_free_gb * 1e9))
    except NotEnoughSpace as exc:
        print(f"NOT STARTING: {exc}.", file=sys.stderr)
        print("Free space, or lower the floor with --min-free-gb.", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"NOT STARTING: cannot write to {args.out}: {exc}", file=sys.stderr)
        return 2
    log = rec.log

    client = HubClient(script_name(__file__), hub=hub, control=False, log=log.info)
    if not client.connect():
        log.warning("no hub yet at %s:%d -- will keep trying", *hub)

    lines = []
    lock = threading.Lock()

    def sink(line):
        with lock:
            lines.append(line)

    _ConsoleReader(sink).start()
    ev_sock = None
    if args.event_port:
        ev_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ev_sock.bind(("127.0.0.1", args.event_port))
        ev_sock.setblocking(False)
        log.info("panel commands accepted on udp://127.0.0.1:%d", args.event_port)

    print(f"recording into {rec.dir}  (commands: spo2 SUBJ01 96 [pr] | mark [SUBJ01] | note | anchor | "
          f"site | subject | status | quit)")
    t_end = time.monotonic() + args.duration if args.duration > 0 else None
    next_tick = 0.0
    try:
        while not rec.stopped:
            item = client.recv(0.1)
            if item is not None:
                ip, data = item
                rec.feed(ip, data)
            if ev_sock is not None:
                try:
                    while True:
                        d, addr = ev_sock.recvfrom(4096)
                        reply = rec.console(d.decode("utf-8", "replace"))
                        if reply:
                            ev_sock.sendto(reply.encode("utf-8"), addr)
                except (BlockingIOError, OSError):
                    pass
            with lock:
                pending, lines = lines, []
            for ln in pending:
                reply = rec.console(ln)
                if reply:
                    print(reply)
            now = time.monotonic()
            if now >= next_tick:
                next_tick = now + 0.25
                rec.tick(now)
            if t_end is not None and now >= t_end:
                rec.stop("duration")
    except KeyboardInterrupt:
        rec.stop("SIGINT")
    finally:
        client.close()
        rec.close()
        print(rec.status_text())
        print(f"session closed -> {rec.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
