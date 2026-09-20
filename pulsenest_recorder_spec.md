# pulsenest_recorder — Specification v0.3 (draft for review)

What the robust recorder writes to disk: file types, formats, contents and metadata. Written
2026-09-19, before the tool exists, because the files outlive the tool and are the part that
cannot be fixed afterwards.

Part of the **PulseNest** project — Medical Open World.

Related: `captures/CAPTURE_SET_SPEC.md` (what a capture must contain to be usable),
`pulsenest_lab_spec.md` §4.11 (the hub and its subscribers), `docs/boards.md` (board inventory).

---

## 1. What this is for

A hospital campaign with **three boards on three babies at once**, each baby also wearing a
commercial pulse oximeter. The recorder runs headless for hours on the bench laptop, subscribed
to the hub, and must not lose data because a window painted badly. `pulsenest_lab.py` is not a
candidate: pyqtgraph's paint code has killed it 28 times.

Three independent sources of commercial-oximeter truth, by design — the first campaign is the
worst moment to depend on any single one of them:

| | Source | Rate | Written by |
|---|---|---|---|
| **1** | **VideoNest** `$VN1` frames over UDP (on-device OCR of the monitor screen) | 1–5 Hz | the phone, over the hub |
| **2** | VideoNest's periodic photos | per its own setting | the phone, locally |
| **3** | **Manual entry**: SpO2 combo (see §9) + `RECORD` in the recorder | when the operator looks | the recorder |

They are not redundant copies of one number. 1 is dense but can be wrong (the OCR is new and
still misreads); 3 is sparse but is a person reading a screen; 2 is the evidence that settles a
disagreement between the two. **All three are recorded, none is trusted over the others at
capture time**, and reconciling them is an offline job.

---

## 2. Two streams per board, and which one is the truth

The recorder writes **both**, live, in this order:

1. **`.pnraw`** — every datagram appended byte for byte with a host timestamp (§5).
2. **The capture CSV** — produced by `LabCaptureWriter`, the code the lab already uses, in the
   format every tool in this project reads.

**The CSV is the deliverable. The raw stream is a safety net, and it is optional (§2.3).**

### 2.1 Why both, when either alone would do

Writing only the CSV means every field is interpreted **on site, once**. A column table that is
wrong, a firmware field added last week, a frame mode nobody expected, a `$ERR` worth reading —
these are silently absent, or present as a well-formed row of garbage, which
`LabCaptureWriter`'s own docstring warns about. Nothing can be recovered afterwards, and the
discovery happens a week later, with the babies long gone.

Writing only the raw stream defers **all** verification. Bytes on disk that nobody has converted
are not yet known to be usable data; they are a promise that a tool — one that does not exist
yet — will read them. It is also unreadable by anyone outside this project, which in a hospital
is a real cost: a CSV can be opened by a colleague, by Excel, by the clinical team.

Together they cost little and cover each other. Two properties come out of the pairing that
neither has alone:

* **The live CSV is a test of the whole pipeline, running in front of you.** If it looks right at
  the bench, the session is known-good on the spot, not next week.
* **The two must agree.** Converting the raw stream offline must reproduce the live CSV **byte for
  byte**. If they differ, either the converter has a bug or the live writer dropped rows — a
  real-data regression test that needs no fixture and can be run on a bench session before the
  campaign.

### 2.2 Order of writing, and who may break whom

The raw record is written **first**, then the CSV row is attempted inside its own `try/except`,
per board. If parsing raises — a malformed frame, an unexpected field count, a bug of ours —
that board loses CSV rows and **the raw stream does not notice**. The priority lives in the order
of the statements, not in a comment.

When raw is off (§2.3) the CSV writer is the only writer, so it also becomes the only thing that
can fail: it keeps the same `try/except`, and every line it could not turn into a row is counted
and logged, never discarded silently.

### 2.3 `--raw` : full | exceptions | off

The raw stream is expensive and, most days, never read again. It is therefore a **mode**, chosen
per session:

| Mode | What is written to `.pnraw` | Cost per board |
|---|---|---|
| `full` | every datagram | ≈ **0,5 GB/h** |
| `exceptions` *(recommended once the pipeline is trusted)* | only what the CSV cannot represent: `$CFG`, `$TCFG`, `$LCFG`, `$TIMING`, `$TASK(S)`, `$ERR`, `# STAT`, unparseable or corrupt frames, and **any measurement frame whose field count is not the one expected** | **240 kB/h** (measured 2026-09-20, three V18, 2 min: 38 datagrams kept of 12 037) |
| `off` | nothing; `raw/` is not created | 0 |

`exceptions` is the mode this design is really aiming at, and the reason it works is worth
stating: with every column enabled, the capture CSV already carries **all 36 fields** of an `$M4`
frame — everything but the frame tag and the checksum. The gigabytes are spent on measurement
datagrams that the CSV represents perfectly well. What the CSV cannot represent is the rest, and
the rest is a few kilobytes an hour.

Measured on the bench 2026-09-20, `--raw exceptions` against the three V18 for two minutes:
**11 999 of 12 037 datagrams skipped per board, 8 kB written — 240 kB/h against 500 MB/h**, a
factor of about 2 000. What it kept was the diagnostic traffic (`$TIMING`, `$TASK`, `$TASKS` at
about one every 5 s, `# STAT`, and the three configuration frames), and **not one measurement
frame**: today's firmware emits exactly 36 tokens in every `$M4`, which is itself worth knowing.

The field-count check is what makes `exceptions` safe against the failure that motivated raw in
the first place. A firmware that grows a 37th field produces frames the CSV would quietly
truncate; comparing the field count against the expected one turns that silent truncation into a
recorded exception plus a log line, at the cost of one `len()` per frame.

**Default: `full` for the first campaigns**, while the pipeline has not yet been exercised on
real hospital data, then `exceptions`. `off` exists for the bench.

Compression is **not** applied while recording — only when the session is closed (D2). A plain
append-only file is the thing most likely to survive a laptop dying mid-session, and that
survival is the whole point of the file.

---

## 3. One directory per session

```
captures/sessions/<SESSION_ID>/
    session.json                  metadata, the only hand-edited file (§7)
    session_events.csv            operator marks and manual readings (§6)
    pulsenest_recorder.log        the tool's own log: connections, errors, disk, splits
    T2_SUBJ01_RESTING_20260926_101500.csv   the live capture CSV, one per board (§2)
    raw/                          only when --raw is full or exceptions (§2.3)
        board_<MAC>_0001.pnraw    one stream per board, split into parts (§5)
        board_<MAC>_0002.pnraw
        aux_vn_<IP>_0001.pnraw    VideoNest's $VN1 stream, same format
    derived/                      produced OFF-SITE by the converter, never during the session
        T2_SUBJ01_RESTING_20260926_101500.csv   rebuilt from raw; must equal the live one
        ref_videonest.csv
        ref_manual.csv
```

`SESSION_ID` = `<YYYYMMDD>_<HHMM>_<SITE>` with `SITE` a short code typed at start.

**`SITE` is a code, not a description** (decided 2026-09-20, the same rule §2.7 of
`CAPTURE_SET_SPEC` already applies to people). A place name plus a date plus "a baby" identifies
a person even when no name is written anywhere, so the site is coded and what it means lives
**outside the repository**, in the private file that maps `SUBJnn` to a person. Three prefixes,
and nothing else:

| Code | When |
|---|---|
| `BENCH` | our own bench: no subject, or an adult from the team. Identifies nobody |
| `HOSP01`, `HOSP02` … | clinical sites, numbered in the order they appear |
| `SITE01`, `SITE02` … | anywhere else: a home, an office, someone's flat |

No names, no ward, no room, no city, no street — see §11. What *is* worth recording, because it
is measurement context and identifies nobody, goes in `session.json`'s `notes`: indoors or out,
the kind of lighting, fluorescent tubes overhead, anything that shapes the ambient channel.

The writer only sanitises (upper case, letters and digits, 12 characters, `SITE` if what is left
is empty); the discipline is the operator's.

**The directory is created and `session.json` is written before the first datagram is recorded.**
A session directory that exists but is empty is a sound state; data without metadata is not.

---

## 4. Clocks

Three clocks are recorded, never one:

| Field | Source | Property | Use |
|---|---|---|---|
| `t_mono_us` | `time.monotonic()` | never jumps, never goes back; arbitrary origin | ordering and intervals **within** a session, aligning boards with each other |
| `t_epoch_us` | `time.time()` | absolute, can jump (NTP, DST, manual change) | aligning with photos, with `$VN1`'s own stamp, with the monitor's clock |
| `t_src` | inside the datagram | the source's own clock (`Ts_us` on a board, `timestamp_ms` on `$VN1`) | source-side gaps, and phone-clock drift |

Both host clocks are stamped on **every** datagram, at reception. The reason to carry both is
that they fail differently: a laptop that resyncs its clock mid-session leaves `t_epoch_us` with
a step in it, and only `t_mono_us` still says what happened before what.

`host_t_us` in today's multi-board capture (`pulsenest_lab.py:14622`) is monotonic with an
arbitrary origin — enough to align boards on the bench, **not** enough here, where the whole
point is to line our signal up against a photograph of someone else's screen.

`session.json` records the offset between the two at start and at close, so a drift is visible.

---

## 5. `.pnraw` — the raw stream format

Append-only. One record per datagram. A record is a header line, then the datagram verbatim,
then a newline:

```
@D <seq> <t_mono_us> <t_epoch_us> <ip> <len>\n
<len bytes, exactly as received>\n
```

* `seq` counts records from 1 in a source's first part and never resets on a split within that source (so a
  gap in `seq` is a dropped record, which the recorder never does silently — it logs it).
* `len` is the byte count of the datagram, so the reader never has to guess where it ends.
  This is what keeps the **5 measurements per datagram** invariant intact (spec §4.8): the
  batching is part of the data, not an accident of line breaks.
* The datagram is **not** unescaped, reordered, validated or checksum-checked. A corrupt frame
  is data about the session.
* `@FROM` is stripped: the hub's tag is redundant with the header's `<ip>` field, and keeping
  both invites them to disagree.

Two other record types share the file, so that a raw stream is self-contained:

```
@E <t_mono_us> <t_epoch_us> <event_id> <kind> <text>\n     an operator event (§6), copied into
                                                            every open raw stream
@M <t_mono_us> <t_epoch_us> <text>\n                        a recorder note: part split, board lost,
                                                            source back on a new IP, disk warning
```

File header, first line of every file:

```
@PNRAW1 session=<SESSION_ID> source=<MAC|IP> part=<NNNN> started=<ISO8601 local, with offset>\n
```

`PNRAW1` is the format version. A reader that does not recognise it must refuse to convert
rather than guess.

**Who wrote a line: `@` is the answer.** The authoritative rule is structural — the `<len>`
bytes after a `@D` are the source's, everything outside those blocks is the recorder's — and a
reader that follows the lengths is never in doubt. But the reason this format is text at all is
that a person can `head` it and `grep` it, and by that reading `#PNRAW1` (the tool) and
`# STAT ...` (the firmware) looked alike. Hence the header starts with `@` like every other line
the recorder writes:

| Starts with | Written by | Examples |
|---|---|---|
| `@` | **the recorder** | `@PNRAW1`, `@D`, `@E`, `@M` |
| anything else | **the source, verbatim** | `$M4`, `$CFG`, `$ERR`, `# STAT`, `$VN1` |

`#` is therefore left to the firmware, which already uses it. `@` does not collide: neither the
firmware nor VideoNest emits it, and the hub's own `@FROM`/`@STATUS` never reach the file.
A grep-level rule, not a guarantee — a source that one day emitted a line starting with `@`
would fool the eye but not a length-following reader, which is the one that converts.

A complete example file, with real frames and real lengths, is `docs/pnraw_example.pnraw`.

**Why a text framing and not a binary one.** Everything on this wire is ASCII; a text file can be
read with `head`, searched with `grep` and repaired by hand if its tail is torn, which a binary
container cannot. The length prefix buys exactness without giving that up.

**Splitting into parts.** A new part on every **10-minute boundary of the local wall clock** (10:30:00, 10:40:00 …), or at **256 MB**, whichever comes first (D4, closed 2026-09-20). In Spanish *partir el fichero*; not "rotate", Unix log jargon that says nothing about what happens: the current part is closed (fsync) and the next one opened, recording never stops, `seq` continues.

**Why the boundary and not "N minutes after this part opened".** A part then *spans a readable stretch of the clock a person in the room reads*: part 0004 of any session covers 10:30 to 10:40, so a photo taken at 10:37 is found by filename with no index, and every board's parts line up with every other board's — which elapsed-time splitting does not give, since each board opens its first part whenever its first datagram arrives. Local, not UTC: the boundary has to match the clock on the wall, including the half-hour offsets some regions use.

**Why 10 minutes.** Not a measured figure in v0.1 — it was 15 because 15 is a round number. What the period does *not* change is how much data a dying laptop costs: that is fixed by the 10 s fsync (§8), whatever the part size. What it does change is the unit of damage if one file is corrupted or copied badly, how soon a closed part is available to copy or compress, and the size of a file someone has to open or `grep`: **83 MB at 10 min against 125 MB at 15**, per board at 500 Hz. The cost of splitting is one fsync, one close and one open — about a millisecond, no frame lost, `seq` unbroken — and 144 files instead of 96 for three boards over 8 h. Ten also reads better than a quarter of an hour on a clock. The 256 MB ceiling stays as the net for a rate high enough to fill a part early; at 500 Hz it never fires. A closed part can
be copied or compressed while the session runs, and a file lost to a bad write costs one part,
not the session.

**Naming by MAC, not IP.** Identity is the MAC everywhere in this project (IPs change daily). The
hub asks a new source for `$CFG?` immediately, so the MAC normally arrives within milliseconds:
the recorder **buffers up to 3 s in memory** waiting for it, then opens `board_<MAC>_0001.pnraw`.
If no `$CFG` arrives, it opens `unknown_<IP>_0001.pnraw` and keeps buffering nothing — data is
never dropped for want of a name — and `session.json` records the `ip → mac` mapping with the
times each was seen.

---

## 6. `session_events.csv` — what only a person knows

The one file whose content exists nowhere else. Written with **flush + fsync on every row**
(events are rare and each one is expensive to lose), and mirrored as an `@E` record into every
open raw stream so that each stream stands alone.

```csv
session_id,event_id,t_mono_us,t_epoch_us,iso_local,kind,subject,board_mac,value,value2,source,confidence,note
```

| Field | Meaning |
|---|---|
| `session_id` | the session this row belongs to, repeated on every row — see below |
| `event_id` | monotonic within the session; the join key for the `@E` copies |
| `kind` | `REF_SPO2`, `MARK`, `NOTE`, `PROBE_SITE`, `CARE`, `ALARM`, `CLOCK_ANCHOR`, `SESSION_START`, `SESSION_END` |
| `subject` | `SUBJ01`… or `*` for a session-wide event |
| `board_mac` | the board this concerns, or `*` for all (a `MARK` is normally `*`) |
| `value` | for `REF_SPO2`, the SpO2 % read on the commercial monitor; empty otherwise |
| `value2` | optional second number (pulse rate, if the operator also read it) |
| `source` | `keyboard` (manual), `videonest`, `photo`, `serial` — how the value was obtained |
| `confidence` | free scale for automatic sources; empty for `keyboard` |
| `note` | free text, **no personal data** (§11) |

**Why `session_id` is a column and the filename is not prefixed** (Alex, 2026-09-20). This is the
one file in a session directory that travels on its own: it gets opened in Excel, copied, and its
rows pasted beside another session's to compare. It was also the only one that could not say where
it came from — the `.pnraw` says so in its `@PNRAW1 session=…` header, `session.json` in its
`session_id` field, `pulsenest_recorder.log` in its first line. Prefixing every filename with the
session id was considered and rejected: it would have to reach the `.pnraw` too
(`20260920_1812_SOAK_board_1051DB508850_0001.pnraw`), and it would not help the commonest case
anyway, which is rows merged into one sheet where no filename survives. A column does. It costs
~19 bytes on a file with a few dozen rows per session.

*Files written before 2026-09-20 have no `session_id` column*; a reader takes the session from the
directory name. Recorded files are not rewritten to add it — append-only applies to what was
recorded, not only to the recording.

`CLOCK_ANCHOR` is the event written when the operator films the laptop's clock (§7), so the
video can be tied to `t_epoch_us` without trusting that two devices agree.

Manual readings land here with `source=keyboard`. VideoNest's `$VN1` frames do **not**: they are
raw stream data, and the converter turns them into `derived/ref_videonest.csv`. The rule is the
one from §2 — in the hospital the recorder writes what arrived, and only what arrived.

---

## 7. `session.json` — the metadata

Written at start, updated at close, hand-editable afterwards (it is the `truth.csv` of a
session: the part no machine can produce). Proposed shape:

```jsonc
{
  "schema": "pulsenest_session/1",
  "session_id": "20260926_0930_HOSP01",
  "site_code": "HOSP01",
  "operator": "AC",                     // initials or role, never a full name
  "started": { "iso": "2026-09-26T09:30:12+02:00", "t_mono_us": 812345678,
               "t_epoch_us": 1790000000000000 },
  "closed":  { "iso": "...", "t_mono_us": 0, "t_epoch_us": 0,
               "clock_drift_us": 0 },   // (epoch-mono) at close minus at start
  "host": { "hostname": "...", "recorder_version": "0.1", "hub_version": "...",
            "python": "3.13.x", "timezone": "Europe/Madrid" },
  "sources": [
    {
      "kind": "board",
      "mac": "10:20:BA:14:75:60",
      "ips": [ { "ip": "192.168.137.62", "from": "...", "to": "..." } ],
      "board_rev": "V17",               // from docs/boards.md
      "firmware": { "build": "7770c6c", "elfsha": "a60928ae2b710aab", "lib": "v0.93",
                    "cfg_raw": "$CFG,..." },   // verbatim, as cached by the hub
      "subject": "SUBJ01",
      "tier": "T2",                     // CAPTURE_SET_SPEC §2.2
      "condition": "RESTING",
      "probe_site": "left foot",
      "files": [ "raw/board_1020BA147560_0001.pnraw", "..." ],
      "reference_monitor": {
        "make_model": "unknown (first visit)",
        "averaging_s": null,            // Masimo defaults to 8 s; Nellcor normal/fast
        "probe_site": "right hand",     // pre- vs post-ductal matters, see below
        "notes": ""
      }
    },
    { "kind": "videonest", "ips": [...], "app_version": "...", "frame_format": "VN1",
      "watching_subject": "SUBJ01", "files": [ "raw/aux_vn_192.168.137.45_0001.pnraw" ] }
  ],
  "consent": "pending",                 // pending | obtained | n/a  (CAPTURE_SET_SPEC §2.7)
  "notes": ""
}
```

Two fields are not bureaucracy and should be filled even when everything else is rushed:

* **`probe_site` for both probes.** In a neonate with a patent ductus arteriosus, preductal
  (right hand) and postductal (foot) SpO2 differ by several points. If the two sites are not
  recorded, that physiological difference will be read later as *our* error.
* **`averaging_s` of the commercial monitor.** It sets the window our own SpO2 has to be averaged
  over before the two numbers can be compared at all.

Everything about the boards that the firmware already knows (`$CFG`) is copied in **verbatim and
unparsed**, and also stays in the raw stream. It is a convenience, not a source of truth:
`CAPTURE_SET_SPEC` §2.3 ranks per-sample columns above any header, and this file is a header.

---

## 8. Durability, and how the recorder behaves when things go wrong

* **Append only.** No file is ever rewritten, truncated or reopened for writing.
* **Flush** every 1 s; **fsync** every 10 s and on every split; **fsync immediately** for
  `session_events.csv`.
* **One writer per source, each with its own try/except.** An exception writing one board's
  stream must not stop the other two: it is logged, counted, and that source is retried.
* **Free space** is checked at start (refuse to start below a configurable floor) and every
  minute (warn loudly, then stop cleanly rather than fill the disk).
* **A source going silent is normal** (a board reboots, the phone locks) and is recorded as an
  `@M` note, never as an error that stops anything. A board returning on a new IP continues in
  the same file if its MAC matches.
* **The recorder never writes to the boards.** Read-only subscriber (`HubClient(control=False)`),
  so no `$SET` and no `$MODE` can leave it by construction. Configuration is done beforehand from
  the lab.
* **Stopping** is explicit (a key, or SIGINT), writes `SESSION_END`, closes every file, updates
  `session.json` and prints where everything is.

---

## 9. The manual-entry panel

A numeric SpO2 selector and a `RECORD` button, per the third system. Details worth fixing now:

* **Range 50–100 %**, step 1, not 60–100: a neonatal desaturation goes below 60, and a value the
  operator cannot enter is a value that gets written in a notebook and lost. An optional pulse
  rate field beside it (`value2`), skippable.
* **Which board/subject the reading belongs to** is chosen on the panel — with three babies, an
  unattributed reading is nearly worthless. Default: the last one used.
* **The panel must not show our own SpO2.** A person reading a screen while a second number sits
  next to it does not record the first one — they record the difference they expect. Keeping our
  estimate off the panel is the cheapest thing that can be done for the quality of this reference,
  and it costs nothing.
* **The timestamp is the instant of the click.** The monitor averages over seconds, so the lag
  between reading and clicking is irrelevant; no correction is applied, and none should be
  invented later.
* **Process isolation.** The panel is a separate process from the writer, and sends its events to
  the recorder over local UDP. If the panel dies or is closed, **recording continues**; if the
  recorder dies, the panel says so instead of silently accepting clicks. The headless core also
  accepts the same events typed on its own console, so a session can run with no GUI at all.

---

## 10. What the converter produces (off-site)

Run after the session, never during it. Input: a session directory. Output: `derived/`.
With the live CSV in place (§2) the converter is no longer on the critical path: its first job is
to **verify** — rebuild each board's CSV from raw and compare it byte for byte with the live one —
and only then to produce what the live writer could not. With `--raw exceptions` there is nothing
to rebuild and it reports on the exceptions instead; with `--raw off` it only handles the
reference streams below.

* **One CSV per board**, in the existing capture format — the same columns, the same
  `# ...` note lines, the same `# event @row N: ...` lines that `LabCaptureWriter` writes, so
  every tool that reads a capture today reads these unchanged.
  **The board's own `#` lines are labelled.** In a capture CSV, `#` has so far meant "written by
  a person about this capture" (pre-notes, `# event @row N:`, post-notes). The firmware also
  emits lines beginning with `#` (`# STAT frame_dropped=...`), and dropping those in raw would
  make the two indistinguishable — the same ambiguity as the `.pnraw` header, one floor down.
  So the converter writes them as **`# from-board: # STAT ...`**, and any consumer can tell an
  annotation from a message. Named per
  `CAPTURE_SET_SPEC` §2.4 (`<TIER>_<SUBJECT>_<CONDITION>_<params>_<date>_<time>.csv`) from
  `session.json`, so nobody types a long filename in a hospital.
* **`ref_videonest.csv`**: `t_epoch_us, t_mono_us, seq, spo2, conf, phone_ts_ms, drift_ms,
  checksum_ok` — one row per `$VN1` frame, with the NMEA checksum verified here (never at
  capture time) and the phone-to-host clock drift made explicit.
* **`ref_manual.csv`**: `session_events.csv` filtered to `kind=REF_SPO2`, in the same column shape as
  `ref_videonest.csv`, so the two are directly comparable.
* **A reconciliation report**: manual vs VideoNest at matching instants, which is what says
  whether the OCR can be trusted for the next campaign.

**Acceptance test for the converter**: feed it a raw stream recorded from a board and compare its
CSV byte for byte with what `LabCaptureWriter` produces from the same datagrams. Equal, or the
converter is wrong.

---

## 11. Personal data

Captures are health data, and several subjects are minors (`CAPTURE_SET_SPEC` §2.7).

* Coded subject identifiers only (`SUBJ01`), in every file, including free-text notes. The
  mapping to real people lives **outside** this repository.
* **Coded site identifiers too** (`BENCH`, `HOSP01`, `SITE01` — §3): the same reasoning, since a
  place and a date narrow down a person as effectively as a name. The code→place mapping lives in
  the same private file as the subject mapping.
* `captures/` is not committed (`.gitignore`), and **session directories are not committed
  either** — not even `session.json`, which names sites and operators.
* VideoNest's photos are part of the same body of data: same storage rules, and the phone's
  cloud sync must be off before the campaign.
* `consent` is recorded per session and must be `obtained` before any capture leaves the laptop.

---

## 12. Open decisions

| # | Question | Recommendation |
|---|---|---|
| D1 | Hub: `$VN1` as an auxiliary source | **Closed 2026-09-20: done.** `pulsenest_hub.AUX_PREFIXES` classifies on the first datagram; an aux source is forwarded like any other, never asked `$CFG?`, counted apart in `@PONG` and shown as `aux <kind>` in `@STATUS`. `fleet_monitor.py` and `fleet_ppg_viewer.py` import the same table and give it no row and no band. Verified against the three real boards plus a phone. |
| D2 | Compress closed `.pnraw` parts automatically? | Not during the session. Offer `--compress-on-close`, default off for the first campaign. Text compresses ≈ 8×, so it is the cheap way to keep `full` affordable if `exceptions` is not trusted yet. |
| D3 | ~~Live thin CSV?~~ **Closed**: the full live capture CSV (§2) replaces it — a once-per-second summary is not needed beside a file that is the deliverable. |  |
| D4 | Split period and alignment | **Closed 2026-09-20: 10 min on the local wall-clock boundary**, 256 MB ceiling. Reasoning in §5. |
| D5 | Should `session_events.csv` also be mirrored to a plain `.txt` log in operator-readable form? | The `@M`/`@E` lines in `pulsenest_recorder.log` already cover it. |

---

## 13. Implementation status — `tools/pulsenest_recorder.py` v0.1 (2026-09-20)

The first implementation, written for the campaign of the week of 2026-09-21. **Raw stream
first**: it implements §3, §4, §5, §6, §7, §8 and the console half of §9, and defers the live
capture CSV (§2) and the converter (§10). The reasoning: the CSV that will be written is now the
v0.4 format of `capture_csv_format_spec.md`, whose prerequisites (the column and key dictionary,
a new writer, a firmware notice when HGAC moves RF) do not fit before the campaign — while the
raw `$M4` frames carry every field, RF per sample included, so nothing recorded raw is lost and
the converter can produce the v0.4 CSV, `afe:` snapshots included, off-site afterwards.

Verified 2026-09-20: `tools/pulsenest_recorder_test.py`, **60 offline and in-process checks**
(a fake clock drives the core; then the real hub on a spare loopback port with two fake boards),
a 25 min session on the bench with the three V18 boards (the three split at 18:20:00.000, .008 and .014 — a 14 ms spread, which is the alignment the wall-clock boundary buys), and an earlier 8 s session: identified by MAC at once from the
hub's cache replay, 500,3 samples/s per board, 0 counter gaps, 5 frames per `@D`, 0,50 GB/h per
board — the figure §2.3 estimated.

What the implementation fixed in this document's wording, or added:

* **Split period: 10 min, aligned to the local wall clock** (D4 closed, §5). `next_wall_boundary_us()`
  computes the next multiple from the top of the hour, so a part that opens at 10:23:45 closes at
  10:30:00, and every board's parts line up. `--split-min` changes it; `--split-mb` is the ceiling.
* **The sample counter is followed, so the operator learns what the file alone would not.**
  A 25 min bench session on 2026-09-20 lost **40 samples on one board at 18:15:47** — real WiFi
  loss, four minutes away from any split — and nothing on screen said so. The recorder now reads
  the counter of each measurement frame (**only** the counter: what lands in the `.pnraw` is still
  the datagram verbatim, §5, and an unparseable line is skipped) and keeps, per source, `samples`,
  `gaps`, `samples_lost` and `restarts`. A forward jump is a gap; a counter going **backwards** is
  a **board restart**, not a gap. Both become `@M` notes, a warning in `pulsenest_recorder.log`, columns in
  `status` and fields in `session.json`. The authoritative per-frame check stays with the CSV
  writer (`capture_csv_format_spec` R12a); this is situational awareness at the cot side.
* **Session metadata is typed, not hand-edited** (§7): `subject <MAC suffix> SUBJnn`, `tier`,
  `cond`, `ref SUBJnn model|avg|site|note` and `consent`. Each writes a **`META` event** (a kind
  added to §6's list) as well as updating `session.json`, so the metadata is auditable and
  survives in the `.pnraw` even if `session.json` is lost. `ref` covers the block §7 calls
  non-negotiable: the commercial monitor's model, its averaging in seconds and **its** probe
  site. `consent` is session state (`obtained | pending | n/a`), no longer the literal
  `"pending"`.
* **A runbook for the person at the cot side**: `docs/hospital_runbook.md` — the order of
  commands at the start, what to type during the session, how to close it, and a table of what
  to do when something looks wrong.
* **VideoNest, measured end to end for the first time (2026-09-20).** The phone at
  192.168.1.143 sending to the bench PC's LAN address on :5005 — the hub binds every interface, so
  the phone does not have to be on the hotspot with the boards. 30 s recorded alongside the three
  V18: **42 frames (≈1,4 Hz), 0 bad NMEA checksums, 0 sequence gaps**, classified `aux` by the hub
  and written to `raw/aux_vn_192.168.1.143_0001.pnraw`. Frame seen:
  `$VN1,314,96,0,0.98,1789927282311*23` (the build-7 shape; **build 8 dropped the `pr` field**,
  see below).
  Two numbers worth keeping. **The phone's timestamp runs 164–350 ms behind host arrival (median
  206)** — that is clock offset *plus* OCR and send time, and it is exactly what §10's `drift_ms`
  column is for; at the accuracy a video frame needs (tens of ms) it must be corrected, not
  ignored. And **the pulse rate field was 0 in every frame** while SpO2 read 96 at confidence
  0.98: whatever the camera was pointed at, PR was not being recognised. Worth settling before the
  campaign, since `value2` of a manual `REF_SPO2` is then the only pulse-rate reference.
* **VideoNest build 8 (2026-09-20) drops `pr` from the frame**: `$VN1,<seq>,<spo2>,<conf>,<ts_ms>`,
  four fields where there were five, and the NMEA checksum is over the new, shorter body. It read 0
  in every frame anyway (measured above). **Nothing in this repository had to change to keep
  working**: the hub matches the four-byte tag and never parses the body, the recorder classifies on
  the same prefix, and the checksum is verified by the converter, which does not exist yet — the
  decision in §5 not to interpret what is recorded is what made a wire-format change a
  documentation task. What did change: the fixtures, `ref_videonest.csv`'s columns (§10, no `pr`),
  and one defensive fix — `_watch_counter` matched any `$M` tag when reading a board's sample
  counter and now matches `$M1,`…`$M4,` in full, because **another source on this wire may use a
  `$Mn` tag** (build 8 names one `M5`) and reading its sequence number as our sample counter would
  invent gaps and restarts. **Closed the same day**: `$M5` is an option in VideoNest to send that tag instead of
  `$VN1`, and it will not be used. The rule it settles is worth stating once: **`$Mn` is the
  boards' namespace** — `$M1`…`$M4` exist, `$M5` was a name our own firmware had considered —
  and a source that is not a board must not take a name from it. If one ever did, the hub
  would classify the phone as a board again (its `AUX_PREFIXES` holds `$VN1` only), query it
  three times, and draw it in both fleet tools; adding `$M5` to `AUX_PREFIXES` instead would
  permanently hand a name of ours to something that is not a board. The guard in
  `BOARD_FRAME_TAGS` stays regardless: it costs nothing and it is simply more correct.
* **`session_id` as the first column of `session_events.csv`** (§6), rather than a session-id
  prefix on every filename.
* **`session_events.csv`, not `events.csv`** (Alex, 2026-09-20). It pairs with `session.json`, so
  everything at session level shares a prefix, and it reads as *the* events of this session rather
  than some events. The word `events` stays, because it is already the vocabulary of the `@E`
  record, the `event_id` column, `EVENT_KINDS` and the `# event @row N` line of the CSV format —
  renaming it to "annotations" would break that chain for nothing. Deliberately **not**
  `<SESSION_ID>_events.csv`: the directory is the unit that gets copied (§3), and if files ever
  need to identify themselves outside it, all three must, not one.
* **The log is named after the program that writes it**: `pulsenest_recorder.log`, not
  `recorder.log` (Alex, 2026-09-20), the convention `pulsenest_hub.log` and
  `fleet_ppg_viewer_faulthandler.log` already follow — inside a session directory the reader
  should not have to guess who wrote a file.
* **Vocabulary: "split" / "part"**, never "rotate": in Spanish *partir el fichero* / *parte* (Alex, 2026-09-20). CLI `--split-min`, `--split-mb`; code `_split_if_due()`.
* **`seq` continues across parts** within a source (it does not restart at 1 in part 0002): a
  gap in `seq` anywhere in a source's parts is a dropped record. §5's "per file from 1" meant
  "from 1 in the source's first file".
* **A torn tail is reported, not returned as data.** `read_pnraw()` — the reader the converter
  will build on — follows every `@D`'s `<len>`, and refuses a file whose last line has no
  newline (`truncated tail`) or whose last `@D` is short (`truncated @D <seq>`), as well as a
  file that does not start with `@PNRAW1`.
* **Console commands** (§9, no GUI): `spo2 SUBJ01 96 [pr]` (range 50–100 enforced), `mark
  [text]`, `note <text>`, `anchor` (CLOCK_ANCHOR), `site SUBJ01 <text>` (PROBE_SITE, also into
  `session.json`), `subject <MAC suffix> SUBJ01` (binds a board to a subject so a `REF_SPO2`
  carries its `board_mac`), `status`, `quit`. The same lines are accepted on `--event-port` (a
  local UDP port) for the panel process of §9; the panel itself is not written yet.
* **`--raw off`** writes no `raw/` at all but still keeps `session_events.csv`, `session.json` and the
  log, so a bench run with the lab doing the CSV loses nothing of the operator's.
* **`--raw exceptions`** judges a datagram as a whole: it is skipped only when every line is a
  `$M4` with exactly 36 tokens (tag included, the count `pulsenest_lab.py` checks); `$CFG`,
  `$TCFG`, `$LCFG`, `$TIMING`, `# STAT`, `$ERR`, a short frame, a 37th field or a frame mode
  other than `$M4` keep the whole datagram. `session.json` counts what was skipped per source.
* **Identity**: the MAC is taken from the first `$CFG` of an IP; the identity fields (`board`,
  `fw`, `lib`, `build`, `libsha`, `elfsha`, `idfver`) and the `$CFG` line verbatim land in
  `session.json` under `firmware`. A later `$CFG` from the same IP refreshes them (an OTA
  mid-session). `$VN1` as first datagram makes the source `videonest` (§12 D1 still open on the
  hub's side: the recorder classifies on its own).
* **A board back on a new IP** (same MAC) is merged into the owner source: its datagrams
  continue in the same part, `ips[]` in `session.json` gets the new lease with `from`/`to`
  times, and an `@M source moved ip=… -> …` note marks the row.
* **Silence** ≥ 5 s is noted once (`@M source silent for 5 s`) and its end too (`source back
  after silence`). Neither stops anything (§8).
* **`session.json`** is rewritten atomically (temp file + `os.replace`) at open, whenever a
  stream opens or a subject/site changes, and at close with `closed{}` including
  `clock_drift_us` = (epoch − mono) at close minus at start.
* **Free space**: refused at start below `--min-free-gb` (default 2 GB) — checked *before* anything
  is created, so a refused start leaves no empty session directory, and reported as two lines on
  stderr with exit code 2 rather than a traceback — checked every minute,
  warns below twice the floor and stops cleanly below it (`SESSION_END reason=disk`).
* Files are opened unbuffered (`buffering=0`), so §8's "flush every 1 s" is implicit; fsync
  every 10 s, on every split and on close; `session_events.csv` fsyncs on every row.

Not yet: the live CSV (§2), the converter (§10), the panel process (§9), `--compress-on-close`
(D2), and the hub-side classification of the phone (D1).
