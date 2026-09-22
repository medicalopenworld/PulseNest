"""The capture CSV writer, shared by every program in this project that produces one.

Extracted from `pulsenest_lab.py` on 2026-09-20 so that `tools/pulsenest_recorder.py` can write
the same file live in a hospital: the writer lived inside a 16 000-line module that imports Qt,
and the recorder exists precisely to have no Qt in it. R3 of `capture_csv_format_spec.md` says
one writer per platform, shared by the lab, the recorder and the converter; this module is that
one writer, and moving it here is what makes the rule true rather than aspirational.

    from pulsenest_capture_csv import CaptureCsvWriter, CAPTURE_COLS, col_spec_all

    w = CaptureCsvWriter(path, col_spec_all(), host_t_us=True, label="10:51:DB:50:88:50")
    w.open(pre_notes="# CFG ...")
    w.write_row("$M4,123,...*06", host_t_us=1789935222613634)
    w.add_event("board restarted")
    w.close(post_notes="...")

Nothing here imports Qt, and nothing here touches the network: one raw frame in, one CSV row out.
That is deliberate — it is the piece whose mistakes are silent (a column indexed wrong produces a
well-formed row of garbage), so it is the piece that must be testable on its own.

`CaptureCsvWriter` writes today's format -- what Flow CSV Viewer and every tool in this project
already read, and what `--csv on` selects. `CaptureCsvWriterV04` (2026-09-22) writes the v0.4 of
`capture_csv_format_spec.md` from the same frames, named through `pulsenest_capture_dict`; the
`.pnraw` keeps everything needed to regenerate either.
"""
import pulsenest_capture_dict as D

# The canonical column table: (UI label, CSV name, index in the $M1 field list, mandatory).
# The index is the position in the comma-separated frame after the '$', so 1 = the first field
# after the tag. $M4-only fields (23-35) read "-1" in the narrower frame modes.
CAPTURE_COLS = [
    ("SmpCnt",     "FW_SmpCnt",      1,  False),
    ("Ts_us",      "FW_Ts_us",       2,  False),
    ("LED2 (RED)", "LED2",           3,  True),
    ("LED1 (IR)",  "LED1",           4,  True),
    ("ALED2",      "ALED2",          5,  True),
    ("ALED1",      "ALED1",          6,  True),
    ("LED2_SUB",   "LED2_SUB",       7,  True),
    ("LED1_SUB",   "LED1_SUB",       8,  True),
    ("PPG",        "FW_PPG",         9,  False),
    ("SpO2",       "FW_SpO2",       10,  False),
    ("SpO2_SQI",   "FW_SpO2_SQI",   11,  False),
    ("R",          "FW_R",          12,  False),
    ("PI",         "FW_PI",         13,  False),
    ("HR1",        "FW_HR1",        14,  False),
    ("HR1_SQI",    "FW_HR1_SQI",    15,  False),
    ("HR2",        "FW_HR2",        16,  False),
    ("HR2_SQI",    "FW_HR2_SQI",    17,  False),
    ("HR3",        "FW_HR3",        18,  False),
    ("HR3_SQI",    "FW_HR3_SQI",    19,  False),
    ("RSQI",       "FW_RSQI",       20,  False),
    ("DiagCode",   "FW_DiagCode",   21,  False),
    ("ProbeState", "FW_ProbeState", 22,  False),
    ("V_TIA_LED1",  "FW_V_TIA_LED1",  23, False),
    ("V_TIA_LED2",  "FW_V_TIA_LED2",  24, False),
    ("V_TIA_ALED1", "FW_V_TIA_ALED1", 25, False),
    ("V_TIA_ALED2", "FW_V_TIA_ALED2", 26, False),
    ("I_PD_LED1",   "FW_I_PD_LED1",   27, False),
    ("I_PD_LED2",   "FW_I_PD_LED2",   28, False),
    ("I_PD_ALED1",  "FW_I_PD_ALED1",  29, False),
    ("I_PD_ALED2",  "FW_I_PD_ALED2",  30, False),
    ("OT_LED1",     "FW_OT_LED1",     31, False),
    ("OT_LED2",     "FW_OT_LED2",     32, False),
    ("CH_MASKS",    "FW_CH_MASKS",    33, False),
    ("RF1_OHM",     "FW_RF1_OHM",     34, False),
    ("RF2_OHM",     "FW_RF2_OHM",     35, False),
]


def col_spec_all():
    """Every column, in canonical order: what a trial profile wants (P1-P3)."""
    return [(csv_name, idx) for _label, csv_name, idx, _mand in CAPTURE_COLS]


def col_spec_mandatory():
    """Only the columns marked mandatory: the four codes and the two subtractions."""
    return [(csv_name, idx) for _label, csv_name, idx, mand in CAPTURE_COLS if mand]


class CaptureCsvWriter:
    """One capture CSV: header, rows, notes and counters for a single board.

    Extracted from `PPGMonitor._write_lab_capture_row` and the `_lab_capture_*` attributes
    (v1.46, spec §4.8 F3) so that the single capture driven by LabCaptureWindow and a
    simultaneous multi-board capture are the same code rather than two copies of the column
    indexing — the part that silently produces a well-formed row of garbage when it is wrong.

    Owns no Qt object and touches no UI: the caller reads `count` / `target` and decides what to
    display. `write_row()` returns True on the sample that reaches the target, so the auto-stop
    policy also stays with the caller.

    Not thread-safe: one instance is written by one thread. The single capture is written by the
    drain on the main thread; the multi-board capture routes every board's lines through
    per-board queues so that all writers also run on the main thread (§4.8 F3).
    """

    # Only these frames carry samples. Anything else on the stream ($CFG? replies, $ERR, ...)
    # must never become a CSV row: the fields would be indexed against the column spec and
    # written as a well-formed row of garbage (e.g. "sr=500,numav=8,...").
    _DATA_TAGS = ("M1", "M2", "M3", "M4")

    # M2 parts layout: [0]=M2 [1]=cnt [2]=LED2 [3]=LED1 [4]=ALED2 [5]=ALED1 [6]=LED2_SUB [7]=LED1_SUB
    _M2_MAP = {3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7}

    # RF1/RF2 wire values ("500K", ...) -> ohms, for the RF1_OHM/RF2_OHM CSV columns.
    # Mirrors incunest_afe4490.h's AFE4490RF enum / afeRFToStr() exactly (7 fixed values) —
    # a closed lookup table, not a generic "K"/"M" suffix parser, so an unexpected string
    # (firmware mismatch, corrupted frame) falls through to "-1" instead of silently misparsing.
    _RF_STR_TO_OHM = {
        "10K": 10e3, "25K": 25e3, "50K": 50e3, "100K": 100e3,
        "250K": 250e3, "500K": 500e3, "1M": 1e6,
    }
    _RF_COLS = ("FW_RF1_OHM", "FW_RF2_OHM")

    # Arrival time of the datagram on the PC, in microseconds (D6). Optional first column: it is
    # the only clock shared by several boards, so it is what aligns their CSVs. Resolution is
    # limited to the datagram, not the sample: the five frames of a batch share one stamp
    # (~10 ms granularity at 100 datagrams/s).
    HOST_T_COL = "HOST_T_US"

    def __init__(self, filepath, col_spec, target=0, host_t_us=False, label=""):
        self.filepath  = filepath
        self.col_spec  = col_spec
        self.target    = target      # 0 = continuous
        self.host_t_us = host_t_us
        self.label     = label       # free text for logs (a board's ip/board/mac)
        self.count     = 0           # rows written
        self.skipped   = 0           # lines handed in that were not data frames
        self.events    = []          # (row, text): stream discontinuities, written with the post-notes
        self._f        = None

    @property
    def active(self):
        return self._f is not None

    def header(self):
        names = [csv_name for csv_name, _ in self.col_spec]
        return ([self.HOST_T_COL] if self.host_t_us else []) + names

    def open(self, pre_notes=""):
        """Open the file and write pre-notes + header. Raises on failure; the caller logs."""
        f = open(self.filepath, "w", buffering=1, encoding="cp1252", errors="replace")
        if pre_notes.strip():
            for txt in pre_notes.splitlines():
                f.write(f"# {txt}\n")
        f.write(",".join(self.header()) + "\n")
        self._f = f

    def format_row(self, raw_line, host_t_us=None):
        """The pure part: one raw frame -> list of CSV values, or None if it is not a data frame."""
        parts = raw_line[1:].split('*')[0].split(',')   # strip '$' and checksum
        n = len(parts)
        if n < 1 or parts[0] not in self._DATA_TAGS:
            return None
        is_m2 = (parts[0] == "M2")
        row_vals = []
        for csv_name, m1_idx in self.col_spec:
            if is_m2:
                mapped = self._M2_MAP.get(m1_idx, -1)
                val = parts[mapped] if 0 <= mapped < n else "-1"
            else:
                val = parts[m1_idx] if m1_idx < n else "-1"
            # RF1/RF2 arrive as a display string ("500K"), not a plain number like every other
            # column — convert to ohms so time-series tools (this CSV's whole purpose) can read
            # it. Unknown/out-of-range values (incl. our own "-1" fallback above, and firmware's
            # "?" for an invalid enum) fall through unconverted to "-1".
            if csv_name in self._RF_COLS:
                val = str(self._RF_STR_TO_OHM.get(val, -1))
            row_vals.append(val)
        if self.host_t_us:
            row_vals.insert(0, "-1" if host_t_us is None else str(host_t_us))
        return row_vals

    def write_row(self, raw_line, host_t_us=None):
        """Write one CSV row. Returns True on the row that reaches `target`. Called at 500 Hz.

        Self-limiting: once `target` rows are written nothing more is accepted, so a capture asked
        for N samples contains exactly N. Before v1.46 the only brake was the caller's auto-stop,
        deferred with `singleShot(0)`, so the drain wrote out the rest of the datagrams already
        queued: measured **605 rows for a target of 600**, on three runs of each of the two
        versions. Harmless for analysis, wrong for a file whose length is part of its identity,
        and unworkable for the multi-board capture, where N writers cannot depend on one caller's
        stop timing.
        """
        if self.target > 0 and self.count >= self.target:
            return False
        row_vals = self.format_row(raw_line, host_t_us)
        if row_vals is None:
            self.skipped += 1
            return False
        self._f.write(",".join(row_vals) + "\n")
        self.count += 1
        return self.target > 0 and self.count >= self.target

    def write_datagram(self, data, host_t_us=None):
        """Every data frame in one datagram -> rows. Returns how many rows were written.

        Added for the recorder (2026-09-20), which is handed whole datagrams rather than the
        single lines the lab's drain produces: a batch carries five frames (spec §4.8), and the
        non-data lines in it are counted as skipped rather than turned into garbage rows.
        Accepts bytes or str.
        """
        if isinstance(data, bytes):
            data = data.decode("ascii", "replace")
        written = 0
        for raw in data.split("\n"):
            line = raw.strip("\r").strip()
            if not line:
                continue
            before = self.count
            self.write_row(line, host_t_us)
            written += self.count - before
        return written

    def add_event(self, text, host_epoch_us=None):
        """Record something that happened mid-capture (a board restart, a source change). It is
        written as a '# event @row N: ...' line with the post-notes, not inline: the CSV body
        stays rows only, and a reader of the regression set learns where the splice is."""
        # `host_epoch_us` is what the v0.4 writer puts on its event line; this format has no
        # place for it (events go with the post-notes), so the same call works on both.
        self.events.append((self.count, text))

    def close(self, post_notes=""):
        """Flush events and post-notes, close the file, return the row count."""
        if self._f is not None:
            for row, txt in self.events:
                self._f.write(f"# event @row {row}: {txt}\n")
            if post_notes.strip():
                for txt in post_notes.splitlines():
                    self._f.write(f"# {txt}\n")
            self._f.close()
            self._f = None
        return self.count


# ============================================================================================
# v0.4 -- capture_csv_format_spec.md, decided 2026-09-22. The same discipline (one frame in, one
# row out, nothing else ever becomes a row), a different container: UTF-8, file keys instead of
# a copied wire frame, the configuration as the file's own snapshots, clock anchors instead of
# per-row time columns, and the writer checking the stream as it goes.
# ============================================================================================

class CaptureCsvWriterV04:
    """One v0.4 capture CSV for one board.

        w = CaptureCsvWriterV04(path, keys={"session_id": ..., "subject": ...}, profile="P1")
        w.config(b"$CFG,sr=500,...")       # any time, before or after open(); $TCFG/$LCFG too
        w.open()                           # keys, from-board evidence, @row 0 snapshots, header row
        w.write_datagram(data, host_epoch_us)
        w.add_event("probe moved to left foot", host_epoch_us)
        w.close()

    What it writes and why, by requirement of the spec:
      * R26 file keys `# key=value`, only the ones known -- a key with nothing to say is absent,
        never empty (R25: the header is evidence of what was believed at the time).
      * R24b `# from-board:` the wire frames verbatim, evidence only; nothing below reads them.
      * R24 `# @row N afe:|timing:|alg: cause=... key=value...` -- FULL pictures in dictionary
        names (pulsenest_capture_dict), integers in natural units (R24a), written at open and
        whenever the picture of a domain changes; a reader keeps the last line of each.
      * R12b `# @row N clock: smpcnt= fw_ts_us= host_epoch_us=` at the first row, every ~10 s of
        firmware time, at every check or event line, and at close -- a true (row, instant) tie
        every time, so the closing one is tied to the last row that exists.
      * R12a `gap: missing=K` (counter jumped), `stall: dt=...us` (counter contiguous, board time
        did not), `event: board restarted` (counter went back) -- each with its own clock line.
      * R12 no SmpCnt/Ts_us/HOST_T_US columns; R21a no RF columns (the `afe:` snapshot carries
        RF and says `cause=hgac` when HGAC moved it -- fw 0.15 announces every move).
      * R9 a field the frame mode does not carry is an EMPTY cell, never -1; the firmware's own
        sentinels pass through untouched.
      * R6/R7 UTF-8 without BOM, LF, ASCII header, no blank lines.
    Not thread-safe, like its sibling. Pure on its inputs -- frames, host stamps, wire config,
    keys -- which is what lets the converter reproduce a live file byte for byte (recorder spec
    section 10).
    """

    FORMAT = "incunest_csv/" + D.DICT_VERSION
    ANCHOR_EVERY_US = 10_000_000     # R12b: a clock anchor every ~10 s of firmware time
    STALL_US = 10_000                # R12a/F6: contiguous counter, dt above this = the board stalled
    # R26 order. `t0_fw_ts_us`/`t0_smpcnt` are not written as keys: the @row 0 clock line IS them.
    KEY_ORDER = ("format", "profile", "writer", "source_mac", "board", "fw", "lib", "build",
                 "libsha", "elfsha", "idfver", "t0_iso", "t0_epoch_us", "subject", "site",
                 "condition", "session_id", "part", "prev", "decimation", "led1", "led2", "probe")
    # Data columns of a trial profile: every wire field except the two the anchors carry (R12)
    # and the two the afe: snapshot carries (R21a), under their canonical names.
    COL_SPEC = [(D.COLUMN_CANON[csv], idx) for _label, csv, idx, _m in CAPTURE_COLS
                if csv not in ("FW_SmpCnt", "FW_Ts_us", "FW_RF1_OHM", "FW_RF2_OHM")]   # (class-body scope: no name lookup inside the comprehension)
    _DATA_TAGS = CaptureCsvWriter._DATA_TAGS
    _M2_MAP = CaptureCsvWriter._M2_MAP
    _M1_MAP = {9: 3}                 # $M1,SmpCnt,Ts_us,PPG_DISP: its one value is the PPG column
    _FRAMES = (D.CFG, D.TCFG, D.LCFG)
    # Which wire frames a domain's full picture needs (R24: full or nothing).
    _DOMAIN_NEEDS = {"afe": (D.CFG,), "timing": (D.TCFG,), "alg": (D.CFG, D.LCFG)}
    _DOMAIN_KEYS = {dom: [k for k in D.KEYS if k.domain == dom] for dom in ("afe", "timing", "alg")}
    # The wire key each dictionary key is read from: the numeric twin, first in its list. The
    # labels beside it (tia1=50k next to rf1_ohm=50000) are ignored on purpose (R24a).
    _WIRE_READ = {(k.wire[0], k.wire[1][0]): k for k in D.KEYS if k.wire}

    def __init__(self, filepath, keys=None, profile="P1", label="", keep_wire=True):
        self.filepath = filepath
        self.keys = dict(keys or {})
        self.keys.setdefault("format", self.FORMAT)
        self.keys.setdefault("profile", profile)
        self.label = label
        self.keep_wire = keep_wire
        self.count = 0            # data rows written
        self.skipped = 0          # lines that were neither data nor configuration
        self.gaps = self.missing = self.stalls = self.restarts = 0
        self._f = None
        self._wire = {}           # frame prefix -> last wire line seen (str)
        self._parsed = {"afe": {}, "timing": {}, "alg": {}}
        self._ident = {}          # id-domain keys read off $CFG (source_mac, fw, ...)
        self._written = {}        # domain -> the last picture written
        self._open_cause = "open" # what a domain's FIRST picture says, whenever it becomes known
        self._last_cnt = self._last_ts = None
        self._last_anchor_ts = None
        self._restart_pending = False
        self._cur = None          # (smpcnt, fw_ts_us, host_epoch_us) of the row being written

    @property
    def active(self):
        return self._f is not None

    def header(self):
        return [name for name, _ in self.COL_SPEC]

    # ── configuration ───────────────────────────────────────────────────────────────────────
    def config(self, line, cause=None):
        """A `$CFG`/`$TCFG`/`$LCFG` wire line -> the file's own record. Returns True if it was one.
        Before open(): remembered, written at open(). After: a snapshot for every domain whose
        picture changed, `cause` = the frame's own (fw 0.15: set|hgac), or `restart` when the
        counter went back since the last snapshot, or `set` when the frame does not say."""
        if isinstance(line, bytes):
            line = line.decode("ascii", "replace")
        line = line.strip()
        prefix = line.split(",", 1)[0]
        if prefix not in self._FRAMES:
            return False
        self._wire[prefix] = line
        wire_cause = None
        for part in line.split("*")[0].split(",")[1:]:
            k, sep, v = part.partition("=")
            if not sep:
                continue
            if k == "cause":
                wire_cause = v
            entry = self._WIRE_READ.get((prefix, k))
            if entry is None:
                continue
            val = self._natural(entry, v)
            if val is None:
                continue
            if entry.domain in self._parsed:
                self._parsed[entry.domain][entry.name] = val
            elif entry.domain == "id":
                self._ident[entry.name] = val
        if prefix == D.TCFG or (prefix == D.CFG and self._parsed["timing"]):
            # derivable, not on the wire: the period in AFE clock counts (Appendix B)
            prf = self._parsed["afe"].get("afe_prf_hz")
            if prf:
                self._parsed["timing"]["afe_prpcount"] = 4_000_000 // prf - 1
        if self._f is not None:
            if cause is None:
                cause = wire_cause if wire_cause in ("set", "hgac") else (
                    "restart" if self._restart_pending else "set")
            if self._emit_snapshots(cause) and self._cur is not None:
                self._anchor()
        return True

    @staticmethod
    def _natural(entry, text):
        """Wire text -> the dictionary's representation: integer in natural units, or the text."""
        _frame, _keys, scale = entry.wire
        if scale is None or entry.type == "str":
            return text
        if entry.type == "float":
            return text                       # already C fixed on the wire (%.4f), R24a
        try:
            return int(round(float(text) * scale))
        except ValueError:
            return None

    def _picture(self, domain):
        """The full picture of a domain, or None while a frame it needs has not been seen."""
        if any(f not in self._wire for f in self._DOMAIN_NEEDS[domain]):
            return None
        have = self._parsed[domain]
        return [(k.name, have[k.name]) for k in self._DOMAIN_KEYS[domain] if k.name in have]

    def _emit_snapshots(self, cause):
        """One `# @row N <domain>:` line per domain whose picture changed. Returns how many."""
        n = 0
        for dom in ("afe", "timing", "alg"):
            pic = self._picture(dom)
            if pic is None or pic == self._written.get(dom):
                continue
            # A domain's first picture is the opening state becoming known -- a $TCFG or $LCFG
            # that lands after the first rows did not CHANGE anything -- so it says open|part;
            # only a later, different picture carries the wire's own cause (set|hgac|restart).
            c = cause if dom in self._written else self._open_cause
            self._raw(f"# @row {self.count} {dom}: cause={c} "
                      + " ".join(f"{k}={v}" for k, v in pic))
            self._written[dom] = pic
            n += 1
        if n:
            self._restart_pending = False
        return n

    # ── file ────────────────────────────────────────────────────────────────────────────────
    def open(self, cause="open"):
        """Keys, wire evidence, the opening snapshots, the header row. `cause`: open | part."""
        f = open(self.filepath, "w", buffering=1, encoding="utf-8", newline="\n")
        self._f = f
        self._open_cause = cause
        keys = dict(self._ident)
        keys.update({k: v for k, v in self.keys.items() if v not in (None, "")})
        for k in self.KEY_ORDER:
            if k in keys:
                self._raw(f"# {k}={keys[k]}")
        if self.keep_wire:
            for prefix in self._FRAMES:
                if prefix in self._wire:
                    self._raw(f"# from-board: {self._wire[prefix]}")
        self._emit_snapshots(cause)
        self._raw(",".join(self.header()))

    def _raw(self, text):
        self._f.write(text + "\n")

    def _anchor(self):
        cnt, ts, host = self._cur
        self._raw(f"# @row {self.count} clock: smpcnt={cnt} fw_ts_us={ts}"
                  + (f" host_epoch_us={host}" if host is not None else ""))
        self._last_anchor_ts = ts

    # ── rows ────────────────────────────────────────────────────────────────────────────────
    def write_datagram(self, data, host_epoch_us=None):
        """Every line of one datagram: data frames -> rows (with the checks and anchors they
        trigger), configuration frames -> snapshots, anything else -> counted as skipped.
        Returns how many rows were written."""
        if isinstance(data, bytes):
            data = data.decode("ascii", "replace")
        before = self.count
        for raw in data.split("\n"):
            line = raw.strip("\r").strip()
            if not line:
                continue
            if not self.write_row(line, host_epoch_us) and not self.config(line):
                self.skipped += 1
        return self.count - before

    def write_row(self, raw_line, host_epoch_us=None):
        """One data frame -> one row. Returns False (and writes nothing) if it is not one."""
        parts = raw_line[1:].split("*")[0].split(",")
        n = len(parts)
        if n < 3 or parts[0] not in self._DATA_TAGS:
            return False
        try:
            cnt, ts = int(parts[1]), int(parts[2])
        except ValueError:
            return False
        self._cur = (cnt, ts, host_epoch_us)
        # The checks describe the join between the previous row and this one, so they carry
        # this row's N (= rows already written) and are followed by an anchor at the same N.
        if self._last_cnt is not None:
            if cnt < self._last_cnt:
                self.restarts += 1
                self._restart_pending = True
                self._raw(f"# @row {self.count} event: board restarted smpcnt={cnt}"
                          + (f" host_epoch_us={host_epoch_us}" if host_epoch_us is not None else ""))
                self._anchor()
            elif cnt != self._last_cnt + 1:
                self.gaps += 1
                self.missing += cnt - self._last_cnt - 1
                self._raw(f"# @row {self.count} gap: missing={cnt - self._last_cnt - 1}")
                self._anchor()
            elif ts - self._last_ts > self.STALL_US:
                self.stalls += 1
                self._raw(f"# @row {self.count} stall: dt={ts - self._last_ts}us")
                self._anchor()
        if self._last_anchor_ts is None or ts - self._last_anchor_ts >= self.ANCHOR_EVERY_US:
            self._anchor()
        remap = self._M2_MAP if parts[0] == "M2" else self._M1_MAP if parts[0] == "M1" else None
        vals = []
        for _name, idx in self.COL_SPEC:
            if remap is not None:
                idx = remap.get(idx, -1)
            vals.append(parts[idx] if 0 <= idx < n else "")   # R9(b): not available = empty
        self._raw(",".join(vals))
        self.count += 1
        self._last_cnt, self._last_ts = cnt, ts
        return True

    def add_event(self, text, host_epoch_us=None):
        """R34: `# @row N event: <text> smpcnt=<n> host_epoch_us=<t>`, written now, in place --
        the reader learns where in the rows it happened. `text` must be one line, ASCII-safe."""
        text = " ".join(str(text).split())
        tail = ""
        if self._cur is not None:
            tail += f" smpcnt={self._cur[0]}"
        if host_epoch_us is not None:
            tail += f" host_epoch_us={host_epoch_us}"
        self._raw(f"# @row {self.count} event: {text}{tail}")

    def close(self, post_notes=""):
        """`# @row N end: gaps=G stalls=S`, the closing anchor, and the file. Returns rows.
        `post_notes` (what the legacy writer takes) become `# note:` lines -- informational,
        R10a -- so the recorder closes either writer with the same call."""
        if self._f is not None:
            for txt in post_notes.splitlines():
                if txt.strip():
                    self._raw(f"# note: {' '.join(txt.split())}")
            if self.restarts or self.missing:
                # skipped (# STAT, $ERR, config lines) is normal traffic and stays in the log
                self._raw(f"# note: restarts={self.restarts} missing={self.missing}")
            self._raw(f"# @row {self.count} end: gaps={self.gaps} stalls={self.stalls}")
            if self._cur is not None:
                # Tied to the last row that exists (row count-1): an anchor is a true
                # (row, instant) pair, never an extrapolation to a row that was not written.
                cnt, ts, host = self._cur
                self._raw(f"# @row {self.count - 1} clock: smpcnt={cnt} fw_ts_us={ts}"
                          + (f" host_epoch_us={host}" if host is not None else ""))
            self._f.close()
            self._f = None
        return self.count


# Kept under the old name so nothing that imported it from pulsenest_lab.py breaks.
LabCaptureWriter = CaptureCsvWriter


if __name__ == "__main__":
    import sys
    print(__doc__.split("\n\n")[0])
    print("\nThis is a LIBRARY: import it, do not run it.\n"
          f"  {len(CAPTURE_COLS)} columns, {sum(1 for c in CAPTURE_COLS if c[3])} of them mandatory")
    sys.exit(2)
