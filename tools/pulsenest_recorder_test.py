"""Offline and in-process checks for tools/pulsenest_recorder.py.

Part 1 drives the Recorder core directly with synthetic datagrams and a fake clock -- no hub, no
board, a temp directory, a fraction of a second. Part 2 runs the real hub in-process on a spare
loopback port with two fake boards (the pattern of tools/hub_test.py) and lets the recorder's
own main loop pieces record them for a moment.

    python tools/pulsenest_recorder_test.py

What is checked (pulsenest_recorder_spec.md, sections in brackets):
[3] the directory and session.json exist before the first datagram; the session id shape
[5] @PNRAW1 header; @D framing with exact <len>; a datagram containing a line that starts with
    '@' round-trips (the reader follows lengths, not prefixes); seq continues across parts;
    naming by MAC once $CFG arrives, unknown_<IP> after the wait, aux_vn_<IP> for $VN1; a board
    back on a new IP continues in the same file with an @M note; split by size
[2.3] --raw exceptions keeps $CFG / # STAT / short frames and skips complete $M4 batches
[6] session_events.csv header and rows; an @E copy in every open stream; REF_SPO2 range 50..100
[7] session.json: sources with mac, ips, files, firmware, subject/probe_site; closed + drift
[8] a write failure on one stream is counted and does not stop another; SESSION_END on close
[9] the console commands
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pulsenest_recorder as R  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  recorder core + in-process hub")

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


class FakeClock:
    """Deterministic (t_mono_us, t_epoch_us); advance() moves both."""

    def __init__(self):
        self.mono = 812_345_678
        self.epoch = 1_790_000_012_000_000

    def __call__(self):
        return self.mono, self.epoch

    def advance(self, s):
        self.mono += int(s * 1e6)
        self.epoch += int(s * 1e6)


class QuietLog:
    def __init__(self):
        self.lines = []

    def _add(self, lvl, msg, *a):
        self.lines.append(f"{lvl} " + (msg % a if a else msg))

    def info(self, msg, *a):
        self._add("I", msg, *a)

    def warning(self, msg, *a):
        self._add("W", msg, *a)

    def error(self, msg, *a):
        self._add("E", msg, *a)


M4 = (b"$M4,%d,1567641472,2096921,2096921,205391,99581,1891530,1997340,1.1501e-08,97.40,0.98,"
      b"0.5123,1.84,142.10,0.95,141.80,0.97,142.00,0.99,1,0,1,1.1999e+00,1.1999e+00,5.6981e-02,"
      b"1.1753e-01,5.9993e-06,5.9993e-06,2.8490e-07,5.8763e-07,1.1474e-04,1.0866e-04,0505,100K,100K*06")
CFG_A = (b"$CFG,sr=500,board=incunest_V17,mac=10:20:BA:14:75:60,fw=0.13,lib=0.93,build=cccf6ee,"
         b"elfsha=752b9e01df703576,idfver=v6.0.1*00\r\n")
CFG_B = b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:88:50,fw=0.13,lib=0.93,build=7770c6c*00\r\n"
STAT = b"# STAT frame_dropped=0 udp_tx=100 spi_mean=230 spi_max=412\r\n"
VN1 = b"$VN1,1234,96,0.91,1790000012000*08\r\n"   # build 8 (2026-09-20): seq,spo2,conf,ts -- no pr


def batch(start, n=5, tag=M4):
    return b"\r\n".join(tag % (start + i) for i in range(n)) + b"\r\n"


tmp = tempfile.mkdtemp(prefix="pnrec_")
try:
    # ── Part 1: the core ─────────────────────────────────────────────────────────────────────
    clk = FakeClock()
    log = QuietLog()
    rec = R.Recorder(tmp, "bench-01", operator="AC", raw_mode="full", split_bytes=6000,
                     identify_wait_s=3.0, log=log, clock=clk)

    check("[3] session dir and session.json exist before any datagram",
          os.path.isdir(rec.dir) and os.path.exists(os.path.join(rec.dir, "session.json")))
    check("[3] session id = <YYYYMMDD>_<HHMM>_<SITE>, site sanitised",
          rec.session_id.endswith("_BENCH01") and len(rec.session_id) == len("20260926_0930_BENCH01"),
          rec.session_id)
    check("[6] session_events.csv has the header and SESSION_START",
          open(rec.events_path, encoding="utf-8").read().startswith(",".join(R.EVENTS_HEADER))
          and "SESSION_START" in open(rec.events_path, encoding="utf-8").read())

    # board A: $CFG first (as the hub replays the cache), then batches
    rec.feed("192.168.137.62", CFG_A, *clk())
    a = rec.sources["192.168.137.62"]
    check("[5] MAC taken from $CFG, stream named board_<MAC>",
          a.mac == "10:20:BA:14:75:60" and a.stream is not None
          and a.stream.files[0] == "raw/board_1020BA147560_0001.pnraw", str(a.stream and a.stream.files))
    check("[7] identity fields parsed from $CFG",
          a.ident.get("board") == "incunest_V17" and a.ident.get("elfsha") == "752b9e01df703576")
    for i in range(3):
        clk.advance(0.01)
        rec.feed("192.168.137.62", batch(782071 + 5 * i), *clk())

    # board B: batches BEFORE its $CFG -> buffered, then flushed in order once named
    clk.advance(0.01)
    rec.feed("192.168.137.70", batch(1), *clk())
    b = rec.sources["192.168.137.70"]
    check("[5] datagrams before $CFG wait in memory, no file yet", b.stream is None and len(b.pending) == 1)
    clk.advance(0.5)
    rec.feed("192.168.137.70", CFG_B, *clk())
    recs_b = list(R.read_pnraw(os.path.join(rec.dir, b.stream.files[0])))
    d_b = [r for r in recs_b if r[0] == "D"]
    check("[5] buffered datagram written first, in order, then the $CFG",
          len(d_b) == 2 and d_b[0][5] == batch(1) and d_b[1][5] == CFG_B and d_b[0][1] == 1 and d_b[1][1] == 2)

    # board C: never answers $CFG -> unknown_<IP> after the wait
    clk.advance(0.01)
    rec.feed("192.168.137.99", batch(500), *clk())
    clk.advance(3.5)
    rec.feed("192.168.137.99", batch(505), *clk())
    c = rec.sources["192.168.137.99"]
    check("[5] no $CFG within 3 s -> unknown_<IP> stream, nothing dropped",
          c.stream is not None and c.stream.files[0] == "raw/unknown_192.168.137.99_0001.pnraw"
          and c.stream.records == 2, str(c.stream and (c.stream.files, c.stream.records)))

    # a phone: aux source from the first byte
    clk.advance(0.01)
    rec.feed("192.168.137.45", VN1, *clk())
    v = rec.sources["192.168.137.45"]
    check("[5] $VN1 -> aux_vn_<IP>, recorded at once",
          v.kind == "videonest" and v.stream.files[0] == "raw/aux_vn_192.168.137.45_0001.pnraw"
          and v.stream.records == 1)

    # a phone that names itself: file by ID, and the SAME file across a DHCP lease change --
    # which is exactly what a board gets from its MAC, and what an IP-only phone could not have.
    VN_ID = b"$VN1,900,96,0.98,1790000012000,VN01*00\r\n"
    clk.advance(0.01)
    rec.feed("192.168.137.46", VN_ID, *clk())
    ph = rec.sources["192.168.137.46"]
    check("[5] a phone's trailing id names its stream, not the IP",
          ph.vn_id == "VN01" and ph.stream.files[0] == "raw/aux_vn_VN01_0001.pnraw",
          str(ph.vn_id) + " " + str(ph.stream and ph.stream.files))
    clk.advance(0.01)
    rec.feed("192.168.137.62", batch(782090), *clk())   # unrelated board traffic in between
    clk.advance(0.01)
    rec.feed("192.168.1.77", VN_ID, *clk())             # same phone, new lease
    check("[5] the same phone on a new IP continues in the same file",
          rec.sources["192.168.1.77"] is ph and ph.ip == "192.168.1.77" and len(ph.ips) == 2
          and ph.stream.records >= 2, f"{ph.ip} {len(ph.ips)} {ph.stream.records}")
    notes_ph = [r[3] for r in R.read_pnraw(os.path.join(rec.dir, ph.stream.files[0])) if r[0] == "M"]
    check("[5] and the move is noted in its own stream",
          any("source moved" in n and "vn_id=VN01" in n for n in notes_ph), str(notes_ph))
    check("[5] a phone with no id is still recorded, named by IP as before",
          rec.sources["192.168.137.45"].vn_id is None
          and rec.sources["192.168.137.45"].stream.files[0].endswith("aux_vn_192.168.137.45_0001.pnraw"))

    # silence thresholds: a phone speaking at ~1 Hz must not trip the board alarm
    clk.advance(10)                      # 10 s: past the board threshold, inside the phone's
    rec.tick(clk.mono / 1e6)             # tick() judges against last_seen_mono: same clock
    check("[8] a phone quiet for 10 s is NOT called silent (boards would be, at 5 s)",
          not ph.silent and R.AUX_SILENT_S > R.SOURCE_SILENT_S,
          f"silent={ph.silent} {R.SOURCE_SILENT_S}/{R.AUX_SILENT_S}")
    clk.advance(25)                      # now past AUX_SILENT_S too
    rec.tick(clk.mono / 1e6)
    ph_notes = [r[3] for r in R.read_pnraw(os.path.join(rec.dir, ph.stream.files[0]))
                if r[0] == "M"]
    check("[8] and it IS called silent once its own threshold passes, naming that threshold",
          ph.silent and any("source silent for 30 s" in n for n in ph_notes),
          str(ph_notes[-2:]))


    # a datagram whose payload has a line starting with '@' must round-trip: lengths, not prefixes
    tricky = b"$ERR,test\r\n@FROM 1.2.3.4\r\n# STAT x=1\r\n"
    clk.advance(0.01)
    rec.feed("192.168.137.62", tricky, *clk())

    # an event: session_events.csv row + @E in every open stream (A, B, C, V)
    clk.advance(0.01)
    reply = rec.console("subject 7560 SUBJ01")
    check("[9] subject assignment by MAC suffix", reply.startswith("board_1020BA147560 -> SUBJ01"), reply)
    reply = rec.console("spo2 subj01 96 142")
    check("[9] spo2 command -> REF_SPO2 with PR", reply.startswith("event ") and "REF_SPO2 SUBJ01=96 PR=142" in reply, reply)
    check("[9] SpO2 out of range refused", rec.console("spo2 SUBJ01 45") == "SpO2 must be 50..100")
    check("[9] unknown command answered, not raised", rec.console("frobnicate").startswith("unknown command"))
    rec.console("site SUBJ01 left foot")
    rec.console("mark probe repositioned")

    # who a mark belongs to: session-wide by default, a subject when one is named
    r_all = rec.console("mark phototherapy lamp on")
    r_one = rec.console("mark SUBJ01 nappy change")
    r_note = rec.console("note subj01 probe repositioned")
    rows_m = open(rec.events_path, encoding="utf-8").read().splitlines()
    cols = R.EVENTS_HEADER
    marks = [r.split(",") for r in rows_m if ",MARK," in r or ",NOTE," in r]
    wide = [m for m in marks if m[cols.index("subject")] == "*"]
    mine = [m for m in marks if m[cols.index("subject")] == "SUBJ01"]
    check("[6] a mark with no subject stays session-wide, as before",
          "(session-wide)" in r_all and len(wide) >= 1
          and wide[-1][cols.index("board_mac")] == "*", r_all)
    check("[6] a mark naming a subject carries it AND that subject's board mac",
          "MARK SUBJ01" in r_one and len(mine) >= 1
          and mine[0][cols.index("board_mac")] == "10:20:BA:14:75:60", r_one)
    check("[6] note takes a subject too, case-insensitively, and keeps the text separate",
          "NOTE SUBJ01" in r_note
          and any(m[cols.index("note")] == "probe repositioned" for m in mine), r_note)
    check("[6] a text that merely starts with a word is not mistaken for a subject",
          "(session-wide)" in rec.console("mark subject moved"), "")

    # a reading can be corrected or retracted, by new events, never by rewriting the file
    r1 = rec.console("spo2 SUBJ01 96 140")
    id1 = int(r1.split()[1].rstrip(":"))
    rec.console("spo2 SUBJ01 97")
    before = len(rec.readings("SUBJ01"))
    rc = rec.console(f"correct {id1} 98 142")
    eff = [r for r in rec.readings("SUBJ01") if r["id"] == id1][0]
    check("[6] correct: the effective reading shows the new values and keeps its own time and id",
          rc.startswith("event") and "96->98" in rc and eff["spo2"] == 98 and eff["pr"] == 142
          and eff["corrected_by"] is not None and len(rec.readings("SUBJ01")) == before, rc)
    rr = rec.console(f"retract {id1}")
    check("[6] retract: the reading leaves the effective list but not the file",
          rr.startswith("event") and all(r["id"] != id1 for r in rec.readings("SUBJ01"))
          and any(r["id"] == id1 and r["retracted_by"] for r in rec.readings("SUBJ01", include_retracted=True))
          and f",RETRACT,SUBJ01," in open(rec.events_path, encoding="utf-8").read(), rr)
    check("[6] a retracted or unknown reading cannot be corrected or retracted again",
          rec.console(f"correct {id1} 90").startswith("no reading")
          and rec.console("retract 99999").startswith("no reading")
          and rec.console("correct x 90").startswith("usage"))
    check("[6] the events file holds the original, the correction and the retraction, in order",
          [ln.split(",")[5] for ln in open(rec.events_path, encoding="utf-8").read().splitlines()
           if f",{id1}," in ln or f"={id1}" in ln][:3] == ["REF_SPO2", "CORRECT", "RETRACT"])

    # one session, one baby (Alex, 2026-09-21): --board and --subject
    import tempfile as _tf
    CFG_8850 = b"$CFG,mac=10:51:DB:50:88:50,board=incunest_V18\n"
    CFG_825C = b"$CFG,mac=10:51:DB:50:82:5C,board=incunest_V18\n"
    M4 = b"$M4,4,1,1," + b",".join([b"1"] * 20) + b",2\n"
    recB = R.Recorder(_tf.mkdtemp(), "HOSP01", "AC", log=QuietLog(), clock=FakeClock(),
                      board="8850", subject="subj3")
    recB.feed("10.0.0.1", CFG_8850)
    recB.feed("10.0.0.2", CFG_825C)
    for ip in ("10.0.0.1", "10.0.0.2"):
        recB.feed(ip, M4)
    kept = [x for x in recB.owners() if x.kind == "board"]
    check("[3] --board records only the board whose MAC ends in the suffix",
          len(kept) == 1 and kept[0].mac == "10:51:DB:50:88:50" and "10.0.0.2" in recB.ignored,
          str([x.mac for x in kept]))
    check("[3] --subject binds the baby before the first row, and normalises it",
          kept[0].subject == "SUBJ03" and recB.want_subject == "SUBJ03", str(kept[0].subject))
    check("[3] the session directory carries the subject, so three windows cannot collide",
          recB.session_id.endswith("_SUBJ03"), recB.session_id)
    recB.stop("t")
    recB.close()

    # An ambiguous suffix must be refused, never resolved by taking the first match: that would
    # record a baby nobody asked for, under another baby's name.
    recC = R.Recorder(_tf.mkdtemp(), "HOSP01", "AC", log=QuietLog(), clock=FakeClock(),
                      board="8850")
    recC.feed("10.0.0.1", CFG_8850)
    recC.feed("10.0.0.2", b"$CFG,mac=AA:BB:CC:DD:88:50,board=incunest_V18\n")
    check("[3] a suffix matching two boards stops the session instead of picking one",
          recC.stopped and recC.stop_reason == "ambiguous board suffix", str(recC.stop_reason))
    recC.close()
    try:
        R.Recorder(_tf.mkdtemp(), "HOSP01", log=QuietLog(), clock=FakeClock(), subject="Maria")
        refused = False
    except ValueError:
        refused = True
    check("[3] --subject refuses anything that is not a subject code", refused)

    # the live CSV splits with the .pnraw, or a four-hour session ends in a 2 GB file
    check("[2] the live CSV is written in parts, numbered from p01",
          os.path.basename(a.csv_paths[0]).endswith("_p01.csv") and a.csv_part >= 1,
          os.path.basename(a.csv_paths[0]))
    check("[2] a part knows the session, its number, and what came before it",
          "part=1" in open(a.csv_paths[0], encoding="utf-8").readline(4096)
          or any("part=1" in ln for ln in open(a.csv_paths[0], encoding="utf-8").read().split("\n")[:8]))

    # session metadata only a person knows (spec section 7), typed instead of hand-edited
    check("[7] truth with no subject applies to every board",
          rec.console("truth T2").startswith("truth=T2 on") and a.truth == "T2" and b.truth == "T2")
    check("[7] truth takes a word and stores the code; the scale climbs with the evidence",
          rec.console("truth none SUBJ01").startswith("truth=T0 on") and a.truth == "T0"
          and R.TRUTH_WORDS["arterial"] == "T3" and R.TRUTH_WORDS["oximeter"] == "T2")
    check("[7] an unknown truth class is refused, not stored",
          rec.console("truth T7").startswith("truth must be one of") and a.truth == "T0")
    check("[7] a bench session starts with no truth class at all", rec.default_truth is None)
    rec.console("truth oximeter")
    check("[7] refs: the set is stored in order and the truth class follows from it",
          rec.console("refs SUBJ01 operator,videonest_udp").startswith("refs=videonest_udp,operator truth=T2")
          and a.truth_sources == ["videonest_udp", "operator"] and a.truth == "T2")
    check("[7] refs: a simulator alone is T1, none is T0, an unknown word is refused",
          rec.console("refs SUBJ01 simulator").endswith("truth=T1 on SUBJ01")
          and rec.console("refs SUBJ01 none").startswith("refs=none truth=T0")
          and rec.console("refs SUBJ01 photos").startswith("unknown reference photos")
          and a.truth_sources == [])
    rec.console("truth oximeter")
    check("[7] condition narrowed to one subject leaves the others alone",
          rec.console("cond resting SUBJ01").startswith("cond=RESTING on")
          and a.condition == "RESTING" and b.condition is None)
    check("[7] ref needs a board bound to that subject",
          rec.console("ref SUBJ99 site right hand") .startswith("no board bound to SUBJ99"))
    rec.console("ref SUBJ01 model Masimo Radical-7")
    rec.console("ref SUBJ01 avg 8")
    rec.console("ref SUBJ01 site right hand")
    check("[7] reference monitor: model, averaging (numeric) and ITS probe site",
          a.reference == {"make_model": "Masimo Radical-7", "averaging_s": 8.0,
                          "probe_site": "right hand", "notes": ""}, str(a.reference))
    # help: the list, one command's detail, and the check that keeps the two in step
    listed = rec.console("help")
    check("[9] help lists every command with its usage and a summary",
          all(c in listed for c in ("spo2", "mark", "ref", "truth", "status", "quit"))
          and "help <command>" in listed, listed[:60])
    one = rec.console("help mark")
    check("[9] help <command> gives usage, summary and the reasoning behind it",
          one.startswith("mark [SUBJ01] <text>") and "no query" in one, one[:60])
    check("[9] help is case-insensitive and tolerates a leading dash",
          rec.console("help MARK") == one and rec.console("help --mark") == one)
    check("[9] an unknown command is answered with the list, not a traceback",
          rec.console("help frobnicate").startswith("no command 'frobnicate'"))
    # The one that matters: every command the console accepts must be documented, and every
    # documented command must exist. A help text that drifts from the code is worse than none.
    import re as _re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "pulsenest_recorder.py"), encoding="utf-8").read()
    body = src[src.index("    def console(self, line)"):src.index("    def _owners(self)")]
    accepted = set(_re.findall(r'cmd == "(\w+)"', body))
    accepted |= {c for grp in _re.findall(r'cmd in \(([^)]*)\)', body)
                 for c in _re.findall(r'"(\w+)"', grp)}
    aliases = {"q", "exit", "?"}
    check("[9] every command the console accepts is documented in COMMAND_HELP",
          (accepted - aliases) <= set(R.COMMAND_HELP), sorted((accepted - aliases) - set(R.COMMAND_HELP)))
    check("[9] and every documented command is one the console accepts",
          set(R.COMMAND_HELP) <= accepted, sorted(set(R.COMMAND_HELP) - accepted))

    rows = open(rec.events_path, encoding="utf-8").read().splitlines()
    check("[6] the header names session_id first",
          rows[0].startswith("session_id,event_id,"), rows[0])
    check("[6] every row carries the session id, so merged sheets keep their origin",
          all(r.startswith(rec.session_id + ",") for r in rows[1:]), rows[1][:40])
    ref = [r for r in rows if ",REF_SPO2," in r]
    check("[6] session_events.csv row starts with session_id, then subject, mac, value, value2, source",
          len(ref) >= 1 and ref[0].split(",")[0] == rec.session_id
          and ref[0].split(",")[6:11] == ["SUBJ01", "10:20:BA:14:75:60", "96", "142", "keyboard"],
          ref[0] if ref else "none")

    # split by size on A (split_bytes=6000: each batch is ~1.4 kB)
    for i in range(12):
        clk.advance(0.01)
        rec.feed("192.168.137.62", batch(790000 + 5 * i), *clk())
    check("[5] split by size produced several parts", a.stream.part >= 3 and len(a.stream.files) == a.stream.part,
          f"part={a.stream.part} files={len(a.stream.files)}")

    # board A comes back on a new IP: same file, @M note, ips list grows
    clk.advance(0.01)
    rec.feed("192.168.137.80", CFG_A, *clk())
    clk.advance(0.01)
    rec.feed("192.168.137.80", batch(800000), *clk())
    check("[5] same MAC on a new IP continues in the same stream",
          rec.sources["192.168.137.80"] is a and a.ip == "192.168.137.80" and len(a.ips) == 2
          and a.ips[0]["to"] is not None and rec.by_mac[a.mac] is a)

    # a failure on one stream must not stop the others: break B's file handle
    b.stream.f.close()
    clk.advance(0.01)
    rec.feed("192.168.137.70", batch(20), *clk())
    clk.advance(0.01)
    rec.feed("192.168.137.62", batch(800005), *clk())
    check("[8] write failure on one source is counted, the other keeps recording",
          rec.errors >= 1 and b.stream.errors >= 1 and any("write failed for board_1051DB508850" in l for l in log.lines)
          and a.stream.records >= 20)
    b.stream.f = open(b.stream.path(b.stream.part), "ab", buffering=0)   # heal it for close()

    # packet loss and board restart, seen through the firmware's sample counter
    clk6 = FakeClock()
    log6 = QuietLog()
    rec6 = R.Recorder(tmp, "LOSS", raw_mode="full", log=log6, clock=clk6)
    rec6.feed("10.2.2.2", CFG_A, *clk6())
    s6 = rec6.sources["10.2.2.2"]
    clk6.advance(0.01); rec6.feed("10.2.2.2", batch(100), *clk6())      # 100..104
    clk6.advance(0.01); rec6.feed("10.2.2.2", batch(145), *clk6())      # 40 lost
    check("[8] a jump in the sample counter is counted as a gap and noted, not silently kept",
          s6.gaps == 1 and s6.samples_lost == 40
          and any("gap: 40 samples lost" in l for l in log6.lines), f"{s6.gaps} {s6.samples_lost}")
    clk6.advance(0.01); rec6.feed("10.2.2.2", batch(0), *clk6())        # counter back to 0
    check("[8] a counter going backwards is a restart, not a gap",
          s6.restarts == 1 and s6.gaps == 1 and any("restarted" in l for l in log6.lines))
    check("[8] status shows the loss where the operator will see it",
          "gaps=1 lost=40" in rec6.status_text() and "restarts=1" in rec6.status_text(),
          rec6.status_text())
    notes6 = [r[3] for r in R.read_pnraw(os.path.join(rec6.dir, s6.stream.files[0])) if r[0] == "M"]
    rec6.close()
    sj6 = json.load(open(os.path.join(rec6.dir, "session.json"), encoding="utf-8"))
    check("[5] gap and restart are @M notes in the stream, and counters land in session.json",
          any("gap: 40 samples lost" in n for n in notes6) and any("board restarted" in n for n in notes6)
          and sj6["sources"][0]["samples_lost"] == 40 and sj6["sources"][0]["restarts"] == 1)
    check("[8] counting never alters what was written: the datagrams round-trip verbatim",
          [d[5] for d in R.read_pnraw(os.path.join(rec6.dir, s6.stream.files[0])) if d[0] == "D"]
          == [CFG_A, batch(100), batch(145), batch(0)])

    # wall-clock split boundaries (the helper alone, then a split driven by the fake clock)
    import datetime as _dt
    base = _dt.datetime(2026, 9, 26, 10, 23, 45).timestamp() * 1e6
    b10 = R.next_wall_boundary_us(base, 600)
    b15 = R.next_wall_boundary_us(base, 900)
    check("[5] next wall boundary: 10:23:45 -> 10:30:00 at 10 min, 10:30:00 at 15 min",
          _dt.datetime.fromtimestamp(b10 / 1e6).strftime("%H:%M:%S") == "10:30:00"
          and _dt.datetime.fromtimestamp(b15 / 1e6).strftime("%H:%M:%S") == "10:30:00")
    exact = _dt.datetime(2026, 9, 26, 10, 30, 0).timestamp() * 1e6
    check("[5] a boundary instant moves to the NEXT one (strictly after), never loops",
          _dt.datetime.fromtimestamp(R.next_wall_boundary_us(exact, 600) / 1e6).strftime("%H:%M:%S") == "10:40:00")

    clk5 = FakeClock()
    clk5.epoch = int(_dt.datetime(2026, 9, 26, 10, 29, 50).timestamp() * 1e6)   # 10 s before 10:30
    rec5 = R.Recorder(tmp, "WALL", raw_mode="full", log=QuietLog(), clock=clk5)
    rec5.feed("10.1.1.1", CFG_A, *clk5())
    s5 = rec5.sources["10.1.1.1"]
    for _ in range(4):                       # 5 s apart: crosses 10:30:00, then 10:40:00
        clk5.advance(5); rec5.feed("10.1.1.1", batch(1), *clk5())
    parts_after_first = s5.stream.part
    clk5.advance(600); rec5.feed("10.1.1.1", batch(2), *clk5())
    starts = [r[1]["started"][11:19] for f in s5.stream.files
              for r in R.read_pnraw(os.path.join(rec5.dir, f)) if r[0] == "H"]
    rec5.close()
    check("[5] split happens AT the wall-clock boundary, not N min after opening",
          parts_after_first == 2 and starts[1].startswith("10:30:0"), f"parts={parts_after_first} {starts}")
    check("[5] each part starts on its boundary; a gap in traffic does not create empty parts",
          len(starts) == 3 and starts[2].startswith("10:4") and "min boundary" in
          " ".join(r[3] for f in s5.stream.files
                   for r in R.read_pnraw(os.path.join(rec5.dir, f)) if r[0] == "M"), str(starts))

    # the live capture CSV (section 2): written after the raw record, one per board
    csv_files = [f for f in os.listdir(rec.dir) if f.endswith(".csv") and f != "session_events.csv"]
    check("[2] one live CSV per board, none for a phone or an unnamed source",
          len(csv_files) == 3 and all(any(f.startswith(mac_part) for f in csv_files)
                                      for mac_part in ("1020BA147560", "1051DB508850")),
          str(sorted(csv_files)))
    check("[2] its rows are the data frames of the datagrams, non-data lines skipped",
          a.csv.count > 0 and a.csv.skipped > 0, f"{a.csv.count} rows, {a.csv.skipped} skipped")
    head = open(a.csv_path, encoding="cp1252").read().splitlines()
    notes = [l for l in head if l.startswith("#")]
    check("[2] pre-notes name the session and carry the board's $CFG verbatim",
          head[0] == f"# session={rec.session_id}"
          and any(l.startswith("# from-board: $CFG,") for l in notes), notes[:3])
    check("[2] part 1 says it is part 1 and claims no predecessor",
          "# part=1" in notes and not any(l.startswith("# prev=") for l in notes), notes[:5])
    # By content, not by line number: the pre-notes grow (a `part=`, a `prev=`) and a test that
    # counts them fails for the wrong reason. The header is the first line that is not a note.
    header_line = next(l for l in head if not l.startswith("#"))
    check("[2] the header starts with the host clock, the one shared across boards",
          header_line.startswith("HOST_T_US,FW_SmpCnt,"), header_line[:40])
    n_before = a.csv.count
    rec.feed("192.168.137.62", CFG_A, *clk())          # a $CFG must never become a row
    check("[2] a $CFG on the stream adds no row", a.csv.count == n_before)

    # exceptions-mode classifier
    check("[2.3] complete $M4 batch is a plain measurement batch", R.is_plain_measurement_batch(batch(1)))
    short = b"$M4,1,2,3*00\r\n" + batch(2, 4)
    check("[2.3] a short-count frame in a batch keeps the whole datagram", not R.is_plain_measurement_batch(short))
    check("[2.3] $CFG, # STAT, $M3 are exceptions",
          not R.is_plain_measurement_batch(CFG_A) and not R.is_plain_measurement_batch(STAT)
          and not R.is_plain_measurement_batch(b"$M3,1,2,3*00\r\n"))
    extra = batch(1).replace(b"100K,100K*06", b"100K,100K,EXTRA*06")   # a 37th token before the '*'
    check("[2.3] a 37th field is an exception (silent truncation made visible)", not R.is_plain_measurement_batch(extra))

    # close: SESSION_END, files closed, session.json with closed{} and sources
    clk.advance(1.0)
    rec.stop("test")
    rec.close()
    sj = json.load(open(os.path.join(rec.dir, "session.json"), encoding="utf-8"))
    srcA = [s for s in sj["sources"] if s.get("mac") == "10:20:BA:14:75:60"][0]
    # The count the operator will quote must be the count the files hold. It was not: the last
    # part was added twice (122 410 reported against 95 065 written, on the bench).
    check("[2] the row count in session.json is what the parts actually hold",
          sum(sum(1 for ln in open(p, encoding="cp1252") if ln and not ln.startswith("#")) - 1
              for p in a.csv_paths) == srcA["csv_rows"], str(srcA["csv_rows"]))
    check("[7] session.json: schema, closed with drift, operator", sj["schema"] == "pulsenest_session/1"
          and sj["closed"] is not None and sj["closed"]["clock_drift_us"] == 0 and sj["operator"] == "AC")
    check("[7] session.json carries the typed metadata",
          srcA["truth"] == "T2" and srcA["condition"] == "RESTING"
          and srcA["reference_monitor"]["averaging_s"] == 8.0
          and srcA["reference_monitor"]["probe_site"] == "right hand",
          str(srcA.get("reference_monitor")))
    check("[6] every metadata change is an auditable META event, not just a JSON edit",
          sum(1 for r in rows if ",META," in r) >= 6, str(sum(1 for r in rows if ",META," in r)))
    check("[7] session.json source A: ips (2), files (parts), firmware, subject, probe_site",
          len(srcA["ips"]) == 2 and len(srcA["files"]) == a.stream.part and srcA["firmware"]["elfsha"] == "752b9e01df703576"
          and srcA["subject"] == "SUBJ01" and srcA["probe_site"] == "left foot" and srcA["board_rev"] == "incunest_V17")
    check("[7] session.json lists the unidentified and the VideoNest source",
          any(s["kind"] == "videonest" for s in sj["sources"]) and any(s.get("mac") is None and s["kind"] == "board" for s in sj["sources"]))
    rows = open(rec.events_path, encoding="utf-8").read().splitlines()
    check("[8] SESSION_END is the last event",
          rows[-1].split(",")[R.EVENTS_HEADER.index("kind")] == "SESSION_END"
          and "reason=test" in rows[-1], rows[-1][:60])

    # read back every part of A and prove the round-trip
    all_recs = []
    for rel in a.stream.files:
        all_recs.extend(R.read_pnraw(os.path.join(rec.dir, rel)))
    hdrs = [r for r in all_recs if r[0] == "H"]
    ds = [r for r in all_recs if r[0] == "D"]
    es = [r for r in all_recs if r[0] == "E"]
    ms = [r for r in all_recs if r[0] == "M"]
    check("[5] every part starts with @PNRAW1 naming session, source=MAC and its part number",
          len(hdrs) == a.stream.part and all(h[1]["source"] == "10:20:BA:14:75:60" for h in hdrs)
          and [int(h[1]["part"]) for h in hdrs] == list(range(1, a.stream.part + 1)))
    check("[5] seq is continuous across parts (1..N, no gap)", [d[1] for d in ds] == list(range(1, len(ds) + 1)))
    check("[5] @D payloads round-trip byte for byte, incl. the one with a line starting '@'",
          ds[0][5] == CFG_A and tricky in [d[5] for d in ds] and all(d[5].endswith(b"\r\n") for d in ds))
    check("[5] @D carries the ip and both clocks", ds[0][4] == "192.168.137.62" and ds[0][2] == 812_345_678 and ds[0][3] > 1_790_000_000_000_000)
    kinds = [e[4] for e in es]
    check("[6] @E copies: REF_SPO2, PROBE_SITE, MARK, SESSION_END in the stream",
          all(k in kinds for k in ("REF_SPO2", "PROBE_SITE", "MARK", "SESSION_END")) and any("value=96" in e[5] for e in es))
    check("[5] @M notes: identified, part closed, source moved",
          any(m[3].startswith("identified: mac=10:20:BA:14:75:60") for m in ms)
          and any(m[3].startswith("part closed") for m in ms) and any("source moved" in m[3] for m in ms))
    check("[5] an @E after the move landed in the moved board's stream too", any("MARK" == e[4] for e in es))
    unk = list(R.read_pnraw(os.path.join(rec.dir, c.stream.files[0])))
    check("[5] unknown_<IP> stream: header source=IP, its two datagrams, the 'unidentified' note",
          unk[0][1]["source"] == "192.168.137.99" and sum(1 for r in unk if r[0] == "D") == 2
          and any(r[0] == "M" and r[3].startswith("unidentified") for r in unk))

    # reader refuses a non-PNRAW1 file and a truncated @D
    bad = os.path.join(tmp, "bad.pnraw")
    open(bad, "wb").write(b"#PNRAW1 nope\n")
    try:
        list(R.read_pnraw(bad)); refused = False
    except ValueError:
        refused = True
    check("[5] reader refuses a file without the @PNRAW1 header", refused)
    p1 = os.path.join(rec.dir, a.stream.files[0])
    trunc = os.path.join(tmp, "trunc.pnraw")
    raw = open(p1, "rb").read()
    cut = raw.rfind(b"@D ") + 60                   # inside the last @D record's payload
    open(trunc, "wb").write(raw[:cut])
    try:
        list(R.read_pnraw(trunc)); refused = False
    except ValueError as exc:
        refused = "truncated" in str(exc)
    check("[5] reader reports a torn tail as truncated, not as data", refused)

    # --raw exceptions end to end
    clk2 = FakeClock()
    rec2 = R.Recorder(tmp, "EXC", raw_mode="exceptions", log=QuietLog(), clock=clk2)
    rec2.feed("10.0.0.1", CFG_A, *clk2())
    for i in range(5):
        clk2.advance(0.01); rec2.feed("10.0.0.1", batch(1 + 5 * i), *clk2())
    clk2.advance(0.01); rec2.feed("10.0.0.1", STAT, *clk2())
    clk2.advance(0.01); rec2.feed("10.0.0.1", short, *clk2())
    s2 = rec2.sources["10.0.0.1"]
    check("[2.3] exceptions mode: 5 complete batches skipped, $CFG + # STAT + short frame kept",
          s2.dgrams == 8 and s2.dgrams_skipped == 5 and s2.stream.records == 3, f"{s2.dgrams} {s2.dgrams_skipped} {s2.stream.records}")
    rec2.close()

    # refusing to start below the floor: one line, no traceback, and NO directory left behind
    nodisk = os.path.join(tmp, "nodisk")
    try:
        R.Recorder(nodisk, "FULL", min_free_bytes=10 ** 15, log=QuietLog(), clock=FakeClock())
        refused = False
    except R.NotEnoughSpace as exc:
        refused = "floor is" in str(exc)
    check("[8] refuses to start below the free-space floor, leaving no session directory",
          refused and not os.path.exists(nodisk))

    # --raw off: no raw/ directory at all
    rec3 = R.Recorder(tmp, "OFF", raw_mode="off", log=QuietLog(), clock=FakeClock())
    rec3.feed("10.0.0.2", CFG_A); rec3.feed("10.0.0.2", batch(1))
    rec3.close()
    check("[2.3] raw off: no raw/ directory, session_events.csv and session.json still written",
          not os.path.exists(os.path.join(rec3.dir, "raw")) and os.path.exists(os.path.join(rec3.dir, "session_events.csv")))

    # ── Part 2: real hub in-process, two fake boards, the recorder's I/O pieces ────────────
    import socket
    import pulsenest_hub as H
    import pulsenest_hub_client as C
    C.AUTOSTART_ENABLED = False
    H.CFG_RETRY_S = 0.3
    DATA_PORT, CMD_PORT = 15205, 15206

    class FakeBoard(threading.Thread):
        def __init__(self, ip, cfg):
            super().__init__(daemon=True)
            self.ip, self.cfg = ip, cfg
            self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.data.bind((ip, 0))
            self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.cmd.bind((ip, CMD_PORT))
            self.cmd.settimeout(0.0)
            self.cnt = 0
            self.stop = threading.Event()
            self.sent = 0

        def run(self):
            while not self.stop.is_set():
                try:
                    q, _ = self.cmd.recvfrom(1024)
                    if q.startswith(b"$CFG?"):
                        self.data.sendto(self.cfg, ("127.0.0.1", DATA_PORT))
                except (BlockingIOError, OSError):
                    pass
                self.data.sendto(batch(self.cnt), ("127.0.0.1", DATA_PORT))
                self.cnt += 5
                self.sent += 1
                time.sleep(0.02)

    hub = H.Hub(port=DATA_PORT, cmd_port=CMD_PORT)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    time.sleep(0.2)
    b1, b2 = FakeBoard("127.0.0.2", CFG_A), FakeBoard("127.0.0.3", CFG_B)
    b1.start(); b2.start()

    rec4 = R.Recorder(tmp, "LIVE", raw_mode="full", log=QuietLog())
    client = C.HubClient("recorder_test", hub=("127.0.0.1", DATA_PORT), control=False, autostart=False)
    check("[8] the recorder's client is read-only by construction",
          client.connect() and not client.controller and client.send_to_board("127.0.0.2", b"$CFG?\n") is False)
    t_stop = time.monotonic() + 1.5
    while time.monotonic() < t_stop:
        item = client.recv(0.05)
        if item is not None:
            rec4.feed(*item)
        rec4.tick()
    b1.stop.set(); b2.stop.set()
    client.close()
    rec4.stop("test"); rec4.close()
    labels = sorted(s.label() for s in rec4._owners())
    check("[5] live: both fake boards recorded under their MACs",
          labels == ["board_1020BA147560", "board_1051DB508850"], str(labels))
    total = sum(s.stream.records for s in rec4._owners())
    check("[5] live: datagrams recorded (batching preserved: 5 frames per @D)",
          total >= 40 and all(d[5].count(b"$M4,") == 5 for s in rec4._owners()
                              for d in R.read_pnraw(os.path.join(rec4.dir, s.stream.files[0])) if d[0] == "D" and d[5].startswith(b"$M4")),
          f"total={total}")
    hub.stop_event.set() if hasattr(hub, "stop_event") else None

finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_ok, n = sum(ok), len(ok)
print(f"\n{n_ok}/{n} checks passed — {'OK' if n_ok == n else 'FAILURES'}")
sys.exit(0 if n_ok == n else 1)
