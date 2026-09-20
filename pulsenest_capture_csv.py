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

**This writes today's format, not the v0.4 of `capture_csv_format_spec.md`**, which needs a column
dictionary and a firmware change that do not exist yet. Today's format is what Flow CSV Viewer and
every tool in this project already read, and the `.pnraw` keeps everything needed to regenerate a
v0.4 file later, so the campaign is not waiting on the new format.
"""

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

    def add_event(self, text):
        """Record something that happened mid-capture (a board restart, a source change). It is
        written as a '# event @row N: ...' line with the post-notes, not inline: the CSV body
        stays rows only, and a reader of the regression set learns where the splice is."""
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


# Kept under the old name so nothing that imported it from pulsenest_lab.py breaks.
LabCaptureWriter = CaptureCsvWriter


if __name__ == "__main__":
    import sys
    print(__doc__.split("\n\n")[0])
    print("\nThis is a LIBRARY: import it, do not run it.\n"
          f"  {len(CAPTURE_COLS)} columns, {sum(1 for c in CAPTURE_COLS if c[3])} of them mandatory")
    sys.exit(2)
