# Capture CSV format — requirements (draft v0.4, 2026-09-20, for review)

The list of requirements the CSV must satisfy, written **before** the format itself. Alex's twelve
points (2026-09-19) are the seed; each is kept, corrected or extended, and the missing ones added.
Open points carry alternatives and a recommendation. Nothing is implemented yet: `LabCaptureWriter`
(`pulsenest_lab.py:11034`) writes the format this document will replace.

**v0.2 reframes the scope (Alex, 2026-09-20).** The *default* content is not what a person captures
on a laptop: it is what **hundreds of incubators, unattended, for years, on paid and scarce
bandwidth** will write. Trials and campaigns extend that default through declared **profiles**
(§I). **No single trial decides the default** — the default is decided by the field population, its
consumers and the communications budget; a trial that needs more declares a profile.

**v0.3 closes R21 (Alex, 2026-09-20).** RF is not a per-row column in any profile any more: it is
piecewise-constant, not drifting, so it takes the *event* shape already defined for `$CFG` (R24),
never the *anchor* shape reserved for the clock (R12b) — "ancla" was the wrong word for it. This
exposes a real gap: the firmware only emits `$CFG` from `$SET` and `$CFG?`, never from HGAC's own
control loop where it actually moves RF, so the saving is blocked on a new firmware emission point
(R21a, prerequisite 6). Appendix B works an example end to end.

**v0.4 makes the configuration record the file's own (Alex, 2026-09-20).** v0.3 still copied the
board's `$CFG` wire frame into the CSV. Read in full (F13), that frame is a transport convenience,
not an archive: it mixes AFE settings, algorithm parameters, identity and provenance, prints most
registers two or three ways for the human eye, and splits the rest across `$TCFG` and `$LCFG`. A
reader that depends on it depends on three frames and on how PulseNest's firmware happens to
print them — and the incubator that writes P0 has none of them. So the CSV now carries **its own
full configuration snapshot**: dictionary names, integers in natural units, one representation per
register, at `@row 0` and at every change, in three domain lines (`afe:`, `timing:`, `alg:`, R24).
The wire frame becomes optional evidence (`# from-board:`, R24b). Full rather than partial even
for an HGAC move: a reader needs only the last line of each domain, never the history (R32/R33).

Two populations of files, therefore, one container:

| Population | Written by | Purpose | Constraint that rules |
|---|---|---|---|
| **Field** (P0) | the incubator firmware | clinical record, post-market evidence, real neonatal PPG for algorithm work | bandwidth / storage per device per day |
| **Trials** (P1–P4) | the lab, the recorder, the converter | validation against a reference, algorithm development, analog diagnostics, regression | completeness; disk on a laptop is not a constraint |

Related: `captures/CAPTURE_SET_SPEC.md` (§2.3 ranking of sources, §2.4 naming, §2.5 manifest,
§2.7 personal data), `pulsenest_recorder_spec.md` (§2 two streams, §4 clocks, §10 converter),
`incunest_afe4490_spec.md` §9.2 (the offline runner's input contract).

---

## 0. Facts the list is built on (measured 2026-09-19/20)

| # | Fact | Where |
|---|---|---|
| F1 | **`FW_Ts_us` wraps every 71 min 35 s.** `(unsigned long)esp_timer_get_time()` printed with `%lu`; `__SIZEOF_LONG__` is 4 on the ESP32-S3 toolchain, so the 64-bit timer is truncated modulo 2^32 µs. Largest value in any capture: 67,7 min. | `main/pulsenest_main.cpp:637-640` |
| F2 | Two column vocabularies are live: `LED1/ALED1/LED1_SUB` (78 files, the lab) and `IR/IR_Amb/IR_Sub` (23 files; the only names the offline runner accepts). 24 distinct header rows across 121 CSVs. | `tools/offline_runner/main.cpp:100-117` |
| F3 | 72 of 121 files are cp1252, not UTF-8. | `pulsenest_lab.py:11097` |
| F4 | 25 rows in 12 files have `FW_SmpCnt = -1` (non-data frames written as rows by old versions). 62 board restarts inside captures. | survey of `captures/*.csv` |
| F5 | `LED*_SUB == LED − ALED` in 75 000/75 000 rows. `V_TIA`, `I_PD`, `OT` are closed-form in ADC code + RF, RG/STG2EN, AMBDAC, ILED, Ri. RF is per-sample (`$M4` fields 34–35, present in 28 captures); ILED/RG/AMBDAC change only via `$SET`, and every non-timing `$SET` emits a fresh `$CFG`. HGAC changes RF only. | `incunest_afe4490.cpp:1267-1287`, `main:1138` |
| F6 | **Sample loss since June 2026: 0 gaps in 1 165 942 rows.** April 2026: 8 real gaps (1–100 samples) plus 60 structural jumps from a broken writer. **Stalls with a contiguous counter** (read blocked, dt > 10 ms): 10 since June, worst 87,6 ms. `FW_Ts_us` is stamped at the *read*, not the conversion (dt 730 / 2000 / 5345 µs on a healthy bench file). | survey |
| F7 | ESP32 timer drift against the host: **+3 … +42 ppm** on V17/V18 (≤ 0,15 s/h); host-vs-board residual 55–75 ms (UDP jitter, batches of 5). | 8 multi-board captures with `HOST_T_US` |
| F8 | Bytes per row at 500 Hz, `kk.csv` (75 000 rows), plain / gzip: 35 columns **264 / 63**; `FW_SmpCnt,FW_Ts_us` **19,0 / 5,8**; `LED1,LED2,ALED1,ALED2` **24,6 / 10,1**; `ALED1,ALED2` alone **10,6 / 4,0**; `OT1,OT2` as firmware prints (`%.4e`) 22,0 / 4,4; **`OT1,OT2` fixed-point integer, unit 1e-10: 14,0 / 5,4** = byte-identical to `LED1_SUB,LED2_SUB`; `OT1,OT2` fixed + `ALED1,ALED2` 24,6 / 10,0 = the four codes. | measured |
| F9 | Fixed-point OT at 1e-10: one unit = 0,87 ADC code; `LED−ALED` round-trips within 0,44 code; 4579 distinct values in 10 s, same as the code (the firmware's `%.4e` gives 2648). Recomputed OT matches the firmware's to 1e-4 (its print floor). | measured |
| F10 | `$M4` frame: 274 B against a 288 B slot — 14 B of margin for new per-sample fields. | `main:225` |
| F11 | Flow CSV Viewer publishes **no** format documentation. Excel keeps 15 significant digits (an epoch in µs has 16). | waveworks.dk |
| F12 | Field budget arithmetic per incubator per day, `OT1,OT2` fixed-point, plain / gzip: 500 Hz **600 / ~230 MB**; 125 Hz **150 / ~60 MB**; 1 Hz outputs only (SpO2, PR, PI, SQI, probe state, RF) **2,2 / < 1 MB**; a 60 s waveform window at 125 Hz per event ≈ 100 kB. | arithmetic on F8 |
| F13 | **The `$CFG` wire frame is not an archive record.** 447–491 B measured on three boards; in one frame: AFE settings (PRF, averages, ILED, range, RF/CF/RG/stage 2 per channel, AMBDAC, Ri), algorithm and display parameters (display channel, five filter corners, `spo2a/b`), identity (board, MAC) and provenance (fw, lib, build, libsha, elfsha, idfver). Most registers appear two or three ways (`tia1=50k` and `rf1_ohm=50000`; `cf1` code and `cf1_pF`; `stg21`, `rg1_ohm`, `rg1_x`). Timing is a second frame, `$TCFG` (28 raw registers, `t1…t28`); RSQM/HGAC parameters a third, `$LCFG`, printed with `%.4e`/`%.3f`. A timing-only `$SET` emits `$TCFG` and no `$CFG`. HGAC's RF moves emit nothing. | `main/pulsenest_main.cpp:735-827, 831-845, 1132` |

---

## A. Scope and architecture

- **R1 — One container, one dictionary, several profiles.** *(Alex #1, reframed v0.2)* A
  domain-independent **container** (syntax, metadata block, anchors, special values); one versioned
  **column dictionary** shared by every profile; **profiles by purpose** (§I) that select columns,
  rate and metadata. The container must be writable by an ESP32: integers, `#` lines, `key=value`,
  no floating-point formatting required.
- **R1b — No trial decides the default.** P0 is fixed by the field population, its consumers and the
  communications budget. Anything a trial needs beyond P0 is a declared profile, never a change to P0.
- **R2 — One file, one source.** One board / phone / ECG per file; alignment across files on anchors.
- **R3 — One writer per platform.** `LabCaptureWriter` for lab, recorder and converter; the incubator
  firmware for P0. Live CSV and CSV rebuilt from `.pnraw` byte-identical (recorder spec §2.1).
- **R4 — One reader per language.** `read_capture()` (Python) and the runner's parser (C++) apply the
  synonym table, the encoding fallback, the `#` rule, the special values, and expose derived views
  (`OT1/OT2` from codes, `LED_SUB` from OT) so a consumer never cares which profile wrote the file.

## B. Container syntax

- **R5** `#` for everything that is not data; exactly one header row = first non-`#` line; no units row.
- **R6** UTF-8 without BOM; header ASCII-only. Readers fall back to cp1252 for the legacy files (F3).
- **R7** Comma, dot decimal, LF (readers accept CRLF), no quotes, no spaces, **no blank lines**.
- **R8** Integers without decimal point; reals in C fixed/scientific notation, no `+`; masks in hex
  with `0x`. *(Alt: decimal masks.)*
- **R9** Three special values, never mixed: (a) *invalid per source* → the source's sentinel, documented
  per column (`-1` for HR/SpO2 at SQI 0); (b) *not available* → **empty cell**, never `-1` (a valid ADC
  code, F4); (c) `nan`/`inf` from the source pass through. *(Alt (b): `NaN`, decided by the Flow fixture.)*
- **R10** A row is a measurement frame and nothing else; anything else the board says (`$CFG`,
  `$ERR`, `# STAT`) is at most an informational `# from-board:` line (R24b), never data and never
  normative; a frame with an unexpected field count is not converted, is annotated and counted.
- **R10a — One sigil for every special line, and what its number means (new 2026-09-20, Alex's
  question; simplified v0.4).** Three kinds of `#` line carry no row marker because they describe
  the whole file, not a moment in it: the file-level keys of R26 (`# format=`, `# profile=`, …), a
  human `# note: …`, and the informational `# from-board: …` of R24b. **Everything else — an
  anchor, a writer check, a configuration snapshot — starts `# @row N <type>:`**, the same token in
  the same position, one grammar, so a reader finds every one of them with a single search. `N` is
  **the count of data rows already written when the line is emitted, equivalently the 0-indexed row
  that comes next and is not yet on disk** — at the very start of the file that is `0`; the three
  opening snapshots and the opening anchor all say `@row 0`, in the order written. `<type>` is a
  lower-case word (`clock`, `gap`, `stall`, `end`, `event`, `afe`, `timing`, `alg`), then a colon,
  then space-separated `key=value` pairs. The clock anchor (R12b) is one `<type>` among the others,
  not a grammar of its own — which is why "ancla" should never have implied a special character.
  *(v0.3 had a second spelling, the verbatim comma-separated wire frame after `@row N`; v0.4
  removes it — the wire frame is no longer normative, R24b.)*

## C. Time and sample identity — **decided 2026-09-19: row = sample, anchors, writer checks**

- **R12 — No per-row counter or timestamp in the data columns.** *(Alex, replaces v0.1 R12)* Evidence
  F6: nothing lost since June; `FW_Ts_us` stamps the read, not the sample. The two columns were 43 %
  of the minimal profile (19 of 44 B). Their information is slow (rate, offset, drift, stalls) and
  moves to anchors and events. Row index = sample index unless an event says otherwise.
- **R12a — The writer verifies live, per frame** (line shape fixed 2026-09-20, R10a): `Δcnt == 1`,
  else `# @row N gap: missing=K`; per block: `rows / Δtime ≈ PRF`, else `# @row N stall: dt=…us`
  (the loss a contiguous counter hides, F6). Both counted on screen and summarised at close:
  `# @row N end: gaps=G stalls=S` (`N` = total rows written, R10a; no separate `rows=` key, it
  would only repeat `N`).
- **R12b — Anchors:** `# @row N clock: smpcnt=C fw_ts_us=T host_epoch_us=H` at open (`N=0`), every
  10 s, at every other event's row (same `N`, its own line), at close (~25 kB/h). Offline,
  `rows == Δsmpcnt` per block proves continuity; any row's instant follows by interpolation
  (F7: drift ≤ 42 ppm → error < 1 ms between anchors).
- **R13 — Source clock wrap (F1)** no longer affects the CSV (anchors unwrap trivially). It stays a
  firmware defect to fix (`%llu`), no longer blocking the campaign.
- **R14 — Original rate by default in trials.** A decimation is declared (`# decimation=N`, a
  proposed key, nothing exists today) and is provable from the anchors (`rows` vs `Δsmpcnt`). Never
  interpolate; a gap stays a gap; never invent a row. P0 may run at a lower rate by budget (§I).
- **R15 — Host time: anchors only. Decided (D1 → B).** Per-row host time is not needed: alignment
  between boards, with references (`$VN1`, photos, manual RECORD) and across a board restart all
  follow from the anchors at the accuracy the references need (seconds for an 8 s-averaging monitor,
  tens of ms for a VideoNest frame). `HOST_T_US` keeps its historical meaning (monotonic, arbitrary
  origin) as a legacy synonym.
- **R16 — Filename** `<SUBJECT>_<SITE>_<BOARD>_<CONDITION>[_<params>]_<YYYYMMDD>_<HHMMSS>[_pNN].csv`,
  local time; offset and start epoch in the header; `<BOARD>` = last three MAC bytes; `<SITE>` = probe
  site. P0 filenames are the incubator's business (device id + local date/time) and follow the same rule.
  **`<SITE>` is a coded place, never a described one**: `BENCH`, `HOSP01`, `SITE01` (recorder spec
  §3). A place plus a date plus a subject identifies a person with no name written anywhere; the
  code→place mapping lives outside the repository, beside the `SUBJnn` one (R27).
- **R17 — Source identity and provenance inside the file, as file-level keys** (v0.4, was "the
  `$CFG` verbatim"): `source_mac`, `board`, `fw`, `lib`, `build`, `libsha`, `elfsha`, `idfver` in the
  R26 header. They never change within a file except across a board restart, which is an event
  (R35) and repeats the keys that changed. The wire frame, if the writer has it, may follow as
  `# from-board:` evidence (R24b) but is not what a reader parses.

## D. Columns and dictionary

- **R18 — A versioned canonical dictionary**, one for every profile, **covering columns and
  configuration keys alike** — **exists since 2026-09-22: `pulsenest_capture_dict.py`**, data only
  (37 columns with every name ever written as a synonym, 92 keys across `id`/`session`/`clock`/`afe`/
  `timing`/`alg` with their wire origin and scale), checked by `tools/pulsenest_capture_dict_test.py`
  against `CAPTURE_COLS`, the firmware's three frame format strings (both directions, so a new wire
  key fails the test until it is named) and Appendix B. *Original requirement:* covering columns and
  configuration keys alike** (v0.4): name, meaning, unit, type, range, sentinel, provenance
  (`fw measured` / `fw computed` / `host` / `derivable` / `config`), domain (`afe`, `timing`, `alg`
  for keys), version introduced. A name never changes meaning; renaming = adding a synonym; new
  columns at the end; nothing reused. Readers resolve by name, ignore unknown columns and keys,
  fail on a missing required one. Configuration keys follow the project's own naming — domain
  prefix, unit suffix (`afe_rf1_ohm`, `afe_iled1_ua`, `afe_ambdac_ua`, `hgac_ema_fast_tau_ms`) —
  and the library's `AFE4490Config` field names are the natural source for them; the wire frame's
  `sr`, `led1`, `tia1` are not.
- **R19 — Naming grammar. Closed 2026-09-22 (D2): the lab's labels are the column canon, `FW_*` and
  `IR*/RED*` synonyms; keys lower_snake with domain prefix and unit suffix; the fixed-point signal is
  `OT1_E10`/`OT2_E10` (a scaled OT names its scale, the project's `_ppm` rule generalised).**
  Grammar `[<origin>_]<quantity>[_<channel>][_<unit or scale>]`. The two options as they were put:
  **A** *(recommended)*: freeze existing names as they are; grammar for new names only.
  **B**: new all-caps canon with today's names as synonyms. New names needed now: `OT1`, `OT2` with
  their scale (`OT1_E10` = OT in units of 1e-10 A/A, or ppm with 4 decimals — +2 B, reads as a unit;
  the `_ppm` convention of the project applies if that is chosen).
- **R20 — Representation of the signal: codes or OT are the same cost; the ambient is the only
  thing with a price.** *(replaces v0.1 R20/R21 after F8/F9)* `OT1,OT2` fixed-point (computed by the
  writer from the codes, unit 1e-10) is lossless for `LED−ALED`, costs 14,0 B/row, and `OT+ALED`
  costs exactly what the four codes cost. What `OT`-only removes is `ALED1,ALED2`: **10,6 B/row plain
  (19 MB/h per board), 4,0 B gzipped (7 MB/h)** — and everything in Appendix A. Which representation
  a profile carries is decided per profile (§I), not once for all files.
- **R21 — Three classes of column, RF reclassified (revised 2026-09-20).** Raw (`LED/ALED`);
  derived — stateless (`_SUB`, `V_TIA`, `I_PD`, `OT`: recomputable) versus stateful algorithm
  outputs (`SpO2`, `HR*`, `SQI*`, `PI`, `R`, `DiagCode`, `ProbeState`: **not** recomputable from a
  cold start; they are the device's own output, what a reference session compares against the monitor). **RF is
  no longer a per-sample column in any profile** (previous cost: gzip 0, plain 13 B/row) — it moves
  to a change-event, R21a, alongside the rest of `$CFG`. RF is still needed to invert OT to codes
  and to correct real-versus-nominal RF (all OT corrections are multiplicative given RF and
  `$CFG`); not needed to run the algorithms.
- **R21a — RF as a change-event, not an anchor (closed 2026-09-20, Alex).** *(Replaces the "may be
  carried as change events… in P0" note in v0.2.)* RF is piecewise-constant: it holds until `$SET`
  or HGAC moves it, and HGAC's own design imposes a ≥ 3×τ_fast (~0,3 s) cooldown between moves
  (`project_agc_design.md` §4B) — it does not drift continuously. That is the shape of an *event*
  (R24), not of an *anchor* (R12b, reserved for the clock's continuous drift, F7); "ancla" was the
  wrong word for it. Cost, worst case with HGAC actively hunting: one event line per ~150 rows at
  500 Hz, against 13 B/row for that whole stretch — two-plus orders of magnitude cheaper in the
  *plain* file, which is the number the field budget sees (compression is at-rest only, R29). With
  an applied probe in steady state it is close to free.
  **Prerequisite 6 — landed 2026-09-22 (lib v0.94 `hgacRfChangeCount()`, fw 0.15 `$CFG`
  `cause=hgac ts_us=<move> hgac_rf_changes=<n>`; pending OTA to the campaign boards).** The
  paragraph that follows is the analysis that led there, kept as written on 2026-09-20.
  **Blocking prerequisite** (prerequisite 6): `send_cfg_frame()` today fires only from `$SET` and
  `$CFG?` (`main/pulsenest_main.cpp:1138,1236`); HGAC's control loop, where it actually changes RF,
  calls neither (confirmed by reading the call sites — no `send_cfg_frame()` or equivalent from the
  HGAC path). Without a new emission point there, moving RF out of the columns would silently lose
  the one thing HGAC exists to produce. ILED, RG and AMBDAC are unaffected: they change only via
  `$SET` (F5). *(v0.4: the event is a full `afe:` snapshot, R24, not a partial `$CFG` — so what the
  firmware must add is "tell the host RF moved"; how the CSV records it is the writer's business.)*
- **R22 — Canonical column order** (readability only): host anchors are `#` lines; then signal
  columns in dictionary order; then configuration; then outputs.
- **R23 — Channel versus wavelength.** `LED1=IR`, `LED2=RED` is a board+probe convention; the header
  declares `# led1=IR led2=RED probe=<model>`; `IR`/`RED` are synonyms under that mapping only.
  `probe` is **operator-entered, always** (2026-09-22): ISO 80601-2-61 calibrates a monitor+probe
  pair, and nothing electrical distinguishes one probe model from another — the library has no
  way to fill this key in on its own, unlike every other R26 identity key, which comes straight
  off `$CFG`. `tools/pulsenest_recorder.py`'s `probe SUBJnn <model>` console command and
  `--probe`/`probe=` launch field are what write it.

## E. Metadata

- **R24 — The configuration record is the file's own: full snapshots, at `@row 0` and at every
  change** (Alex, v0.4; replaces the verbatim `$CFG` of v0.1–v0.3). Three lines, one per domain,
  each a **complete** picture of its domain in dictionary names (R18), `# @row N <domain>:
  cause=<c> key=value …`:

  | Line | Carries | Written when | ≈ size |
  |---|---|---|---|
  | `afe:` | everything the code→physical conversion needs (F5's inputs: `afe_rf1_ohm`, `afe_rf2_ohm`, `afe_rg1_ohm`, `afe_rg2_ohm`, `afe_stg2en1/2`, `afe_ambdac_ua`, `afe_iled1_ua`, `afe_iled2_ua`, `afe_ri_ohm`) plus `afe_prf_hz`, `afe_numav`, `afe_iled_range_ma`, `afe_cf1_pf`, `afe_cf2_pf`, `afe_sep_gain` | `@row 0`; every `$SET` touching it; **every HGAC RF move** | 220 B |
  | `timing:` | the 28 AFE4490 timer registers, by datasheet name (`afe_led2stc` … `afe_adcrstendct3`), plus `afe_prpcount` | `@row 0`; a timing `$SET` | 430 B |
  | `alg:` | library and display parameters: `rsqm_*`, `hgac_*`, HR2/HR3 filter corners, `spo2_cal_a/b`, `ppgdisp_*` | `@row 0`; a parameter `$SET` | 300 B |

  `cause` ∈ `open`, `set`, `hgac`, `restart`, `part`. A reader keeps **the last line of each
  domain** and nothing else: no history to replay, which is what R32 (truncated file) and R33
  (parts) need. Full rather than partial even for HGAC (R21a): the 220 B buy a stateless reader
  and a free consistency check — an `afe:` with `cause=hgac` may differ from the previous one **in
  RF only** (F5); any other difference is a firmware finding. Worst case, HGAC hunting at one move
  per ~0,3 s: ≈ 2,6 MB/h *while it lasts*, against 23 MB/h always for the column it replaces; in
  steady state nothing. Identity and provenance are **not** in these lines — they are R17/R26 keys.
- **R24a — One representation per register, integers in natural units** (the wire frame's
  `tia1=50k` + `rf1_ohm=50000` + `cf1` + `cf1_pF` redundancy is gone, F13). The physical value, never
  the register code: `afe_rf1_ohm=50000`, `afe_cf1_pf=5`, `afe_iled1_ua=25000`, `afe_ambdac_ua=0`,
  `afe_prf_hz=500`. A reader needs no AFE4490 register tables; the library's catalog turns the
  value back into a code when a device needs it. Every AFE quantity is quantised (7 RF values, ILED
  in steps of 50/256 mA, AMBDAC in 1 µA steps), so an integer is exact where a `%.2f` is a rounded
  copy. **Reals are allowed in `alg:` only**, for dimensionless coefficients with no natural integer
  unit (`spo2_cal_a`, `spo2_cal_b`, EMA/filter parameters when expressed as Hz with decimals are
  instead written in mHz or ms — `hgac_ema_fast_tau_ms=300`, `hr2_f_low_mhz=500`); C fixed notation,
  dot decimal, never `%e` (D11).
- **R24b — The wire frame is evidence, not the record.** A writer that receives `$CFG`/`$TCFG`/
  `$LCFG` (the lab, the recorder: P1–P3) *may* keep them verbatim as `# from-board: $CFG,…` lines
  (R10), without `@row`, informational only; P0 has none and needs none. If a `from-board:` line and
  the snapshot disagree, the **snapshot is normative** and the disagreement is a finding to report,
  never a value to prefer (R25: header = evidence of what was believed). Human notes stay
  `# note: …`. *(The `$M5` idea — ILED/RG/AMBDAC per sample — is superseded by `afe:` on change.)*
- **R25 — Where each fact lives:** inside the file what machine and writer know at capture time;
  in `session.json`/`truth.csv` what a person knows and may correct; outside the repository and the
  file the code↔person mapping. Header = evidence of what was believed; `truth.csv` wins on conflict.
- **R26 — Machine keys `# key=value`**: `format, profile, writer, source_mac, board, fw, lib, build,
  libsha, elfsha, idfver` (identity and provenance, R17), `t0_iso, t0_epoch_us, t0_fw_ts_us,
  t0_smpcnt, subject, site, condition, session_id, part, prev, decimation, led1, led2, probe`.
  All ASCII, one per line, before the first `@row` line.
- **R27 — No personal data**, anywhere in the file or its name — doubly so for P0, written in
  hospitals worldwide by devices nobody supervises: device id and coded patient id only. **The
  site is coded like the subject** (`BENCH` / `HOSP01` / `SITE01`, R16): no ward, no room, no
  city. Measurement context that identifies nobody — indoors or out, the lighting — belongs in a
  note, not in the site code.

## F. Size

- **R28 — Budget:** see F8 and F12. Trials: `P1` ≈ 120 B/row ≈ 215 MB/h (gz ≈ 60); `P3` 264 B/row.
  Field: decided by the daily budget per incubator (D7/D8).
- **R29 — Compression at rest only** (`.csv.gz` at close), never while writing.
- **R30 — Integers as integers** (`afe_rf1_ohm=50000`, not `50000.0`); fixed-point where a profile
  says so (`OT1_E10`). Why the preference, for anything a device writes (Alex's question, v0.4):
  the AFE quantities are quantised, so the integer is exact and the real is a rounded copy (F9:
  `%.4e` kept 2648 of 4579 values); an integer has one spelling, a real has one per language and
  per locale (R3's byte-identical rebuild; the cp1252 lesson of F3); exact equality is what the
  `cause=hgac` check of R24 rests on; and the unit lands in the name (`_ohm`, `_ua`) instead of in
  someone's memory. Reals stay where the source produces them (R8/R9) and in `alg:` (R24a).
- **R31 — Nothing derivable in a profile's mandatory set**; no duplicate column; no relative-seconds column.

## G. Robustness and continuity

- **R32** Usable when truncated; append-only; optional `# end …` on clean close; `sha256` in `index.csv`.
- **R33** Parts: `# part=N`, `# prev=pNN` (**a part number, not a file name** — amended
  2026-09-21: a live part opens under a provisional name, because the subject is bound by a
  person minutes after the board starts streaming, and every part is renamed to the canonical
  stem at close; a name written into the header at open would point at a file that no longer
  exists. All parts of one capture share a stem, so the number is unambiguous), same header, **and the three snapshots of R24 with
  `cause=part` at `@row 0`** — every part is self-contained, a reader never opens the previous one
  to know the configuration; anchors prove the join.
- **R34** Events `# @row N event: <text> smpcnt=<n> host_epoch_us=<t>` (R10a ordering); rich events
  in `session_events.csv`.
- **R35** Board restart mid-file: **same file + event (decided, D4 → A)**; the reader offers to split.

## H. Compatibility and governance

- **R36** Targets: pandas, MATLAB, R, Excel (tolerable), offline runner, Flow (fixture-tested, F11).
- **R37** The 121 existing files stay readable through synonyms and the encoding fallback.
- **R38** The offline runner accepts the canonical names and derives what it needs (`_SUB` from
  codes, or from `OT` + `RF` + `$CFG`).
- **R39** A canonical fixture per profile in `docs/`.
- **R40** Where the spec lives — OPEN (D5): PulseNest *(recommended)* or the library repo.
- **R41** Format versioning: breaking changes bump `incunest_csv/N`; additions do not.

## I. Profiles by purpose

Every file declares `# profile=`. The dictionary is one; a profile is a selection.

| Profile | Written by | Signal | Also | Rate | Cost |
|---|---|---|---|---|---|
| **P0 field** *(default)* | incubator firmware | `OT1,OT2` fixed-point | 1 Hz outputs: SpO2, PR, PI, SQI, probe state; `afe:`/`timing:`/`alg:` snapshots (R24; RF rides in `afe:`, R21a); device id; coded patient id; site | **OPEN (D8)**: 500 Hz / 125 Hz / 1 Hz-only + event windows | F12: 600/230 · 150/60 · 2,2/<1 MB per day |
| **P1 validation against a reference** (hospital, commercial oximeter) | recorder | `LED1,LED2,ALED1,ALED2` | firmware outputs (SpO2, HR1–3, SQIs, PI, RSQI, DiagCode, ProbeState), anchors, events, snapshots (R24), optional `from-board:` (R24b) | original | ≈ 120 B/row · 215 / 60 MB/h |
| **P2 algorithm development** (bench, simulator) | lab / recorder | as P1 | as P1 without host anchors | original | ≈ 110 B/row |
| **P3 analog diagnostics** (HGAC, TIA linearity, AMBDAC, interference) | lab | 34 remaining `$M4` fields (RF removed, R21a) | snapshots on every change incl. HGAC's own; `from-board:` kept | original | 264 B/row · 476 / 114 MB/h |
| **P4 regression** | tests | what the test fixes (normally P2 frozen) | — | original | — |

A P0 device can be switched remotely to P3 for a bounded time when it misbehaves — the log-level
pattern — which is how field diagnostics are obtained without paying for them everywhere.

---

## Appendix A — What cannot be done with `OT1,OT2` only (RF and `$CFG` recorded)

**Impossible — the information is absent:**
1. Measure the **optical interferer**: level, spectrum and flicker of phototherapy, room lighting,
   light leaking past a probe. `ALED` is the only direct measurement of the environment.
2. Evaluate the **ambient subtraction itself**: the residual a flickering source leaves between the
   LED sample and the ambient sample.
3. Replay the RSQM's **ambient-saturation / probe-absent** decisions; develop the Δi_amb detector
   and limb detection.
4. Know **where the signal sat in the ADC and TIA range**: saturation (`CH_MASKS`), linearity zone
   (OFF_SPEC band), headroom. RF recovers the *difference* of TIA voltages, not each level.
5. Replay or validate **HGAC**, which acts on absolute `V_TIA` levels.
6. Front-end studies: LED2 leakage into ALED2, ALED peaks during diagnostics, HW vs SW subtraction,
   `$TCFG` timing-window effects, TIA linearity sweeps.
7. Attribute the **cause** of a change: a lifting probe is "a change" in OT and "light came in" in `ALED`.
8. **Traceability to the raw sensor reading**: the record holds a quantity we computed, not the ADC output.

**Possible, although it looks otherwise:**
- Correct later for real-versus-nominal RF (±7 %), quantised ILED, Ri/RG tolerance: every OT
  correction is multiplicative given per-sample RF and the `$CFG`.
- Recover `LED1_SUB/LED2_SUB` exactly (±0,44 code).

**Intact:** everything physiological and algorithmic — HR1/HR2/HR3, SpO2 (R is a ratio of AC/DC on
OT), PI, SQIs, neonatal morphology, beat annotation, comparison with a reference, regression, and a
real neonatal PPG database. Of `CAPTURE_SET_SPEC` §3: blocks N, R, S and H2 in full; **I** (interference)
and **H1** (electrical gain-change transient) are lost.

In one sentence: OT-only loses analog-front-end and light-environment diagnostics and keeps
everything clinical.

---

## Appendix B — Worked example (snapshots, anchors, a `$SET`, a gap, a stall, two HGAC RF changes)

Profile P1, header abbreviated to the keys this example needs (R26 lists the rest). Every special
line follows R10a: `# @row N <type>:` first, `N` = data rows already written = the 0-indexed row
that comes next. A quick reference before the file itself:

| `@row N` is followed by… | Who wrote it | Shape |
|---|---|---|
| `afe:` / `timing:` / `alg:` | the writer, from what the board reported — the **normative configuration** (R24) | `cause=… key=value…`, full within its domain, dictionary names, integers |
| `clock:` | the writer, on a timer (R12b) | `smpcnt=… fw_ts_us=… host_epoch_us=…` |
| `gap:` / `stall:` / `end:` | the writer, checking the stream (R12a) | `key=value…` |
| `event:` | the writer, a generic occurrence (R34) | `<text> key=value…` |

No `@row`: the R26 file keys, `# note:`, and the optional `# from-board:` copy of a wire frame
(R24b). Values below are illustrative — library defaults where known, the datasheet's 500 Hz
example for the timers.

**Part 1 — open, a `$SET` on a library threshold (not RF), a gap, a stall, HGAC halving RF1:**

```
# format=incunest_csv/1
# profile=P1
# writer=pulsenest_lab/1.73
# source_mac=10:20:BA:14:75:60
# board=V18
# fw=0.13
# lib=0.93
# build=7770c6c
# elfsha=a60928ae2b710aab
# idfver=v6.0.1
# led1=IR
# led2=RED
# probe=Medle-neo
# from-board: $CFG,sr=500,numav=1,led1=25.00,led2=25.00,range=50,ensepgain=1,tia1=50k,rf1_ohm=50000,cf1=5p,cf1_pF=5,stg21=off,rg1_ohm=0,rg1_x=1.0000,stage2en1=0,tia2=50k,rf2_ohm=50000,cf2=5p,cf2_pF=5,stg22=off,rg2_ohm=0,rg2_x=1.0000,stage2en2=0,ambdac=0,ri_ohm=100000,ch=LED1,fl=0.50,fh=5.00,hr2l=0.50,hr2h=5.00,hr3h=8.00,spo2a=110.0000,spo2b=25.0000,board=V18,mac=10:20:BA:14:75:60,fw=0.13,lib=0.93,build=7770c6c,libsha=3f1c2a9,elfsha=a60928ae2b710aab,idfver=v6.0.1
# @row 0 afe: cause=open afe_prf_hz=500 afe_numav=1 afe_iled1_ua=25000 afe_iled2_ua=25000 afe_iled_range_ma=50 afe_sep_gain=1 afe_rf1_ohm=50000 afe_cf1_pf=5 afe_rg1_ohm=0 afe_stg2en1=0 afe_rf2_ohm=50000 afe_cf2_pf=5 afe_rg2_ohm=0 afe_stg2en2=0 afe_ambdac_ua=0 afe_ri_ohm=100000
# @row 0 timing: cause=open afe_led2stc=6050 afe_led2endc=7998 afe_led2ledstc=6000 afe_led2ledendc=7999 afe_aled2stc=50 afe_aled2endc=1998 afe_led1stc=2050 afe_led1endc=3998 afe_led1ledstc=2000 afe_led1ledendc=3999 afe_aled1stc=4050 afe_aled1endc=5998 afe_led2convst=4 afe_led2convend=1999 afe_aled2convst=2004 afe_aled2convend=3999 afe_led1convst=4004 afe_led1convend=5999 afe_aled1convst=6004 afe_aled1convend=7999 afe_adcrststct0=0 afe_adcrstendct0=3 afe_adcrststct1=2000 afe_adcrstendct1=2003 afe_adcrststct2=4000 afe_adcrstendct2=4003 afe_adcrststct3=6000 afe_adcrstendct3=6003 afe_prpcount=7999
# @row 0 alg: cause=open hgac_enable=1 hgac_v_tia_high2_mv=900 hgac_v_tia_high1_mv=750 hgac_v_tia_low1_mv=200 hgac_ema_fast_tau_ms=100 hgac_ema_slow_tau_ms=2000 hgac_ema_ambient_tau_ms=2000 rsqm_ot_thr_e10=1000000 rsqm_disconn_led_sub_thr=50 rsqm_disconn_i_pd_thr_pa=50000 rsqm_probe_state_min_ms=500 hr2_f_low_mhz=500 hr2_f_high_mhz=5000 hr3_f_high_mhz=8000 ppgdisp_channel=led1 ppgdisp_f_low_mhz=500 ppgdisp_f_high_mhz=5000 spo2_cal_a=110.0 spo2_cal_b=25.0
# @row 0 clock: smpcnt=118402 fw_ts_us=41822193 host_epoch_us=1758352443102000
OT1_E10,OT2_E10,ALED1,ALED2,SpO2,HR3,SQI,ProbeState
1842301,1798234,812004,809912,98,142,1,APPLIED
1842298,1798190,812010,809905,98,142,1,APPLIED
1842305,1798250,812002,809920,98,142,1,APPLIED
1842303,1798212,812005,809911,98,142,1,APPLIED
# @row 4 alg: cause=set hgac_enable=1 hgac_v_tia_high2_mv=900 hgac_v_tia_high1_mv=780 hgac_v_tia_low1_mv=200 hgac_ema_fast_tau_ms=100 hgac_ema_slow_tau_ms=2000 hgac_ema_ambient_tau_ms=2000 rsqm_ot_thr_e10=1000000 rsqm_disconn_led_sub_thr=50 rsqm_disconn_i_pd_thr_pa=50000 rsqm_probe_state_min_ms=500 hr2_f_low_mhz=500 hr2_f_high_mhz=5000 hr3_f_high_mhz=8000 ppgdisp_channel=led1 ppgdisp_f_low_mhz=500 ppgdisp_f_high_mhz=5000 spo2_cal_a=110.0 spo2_cal_b=25.0
# @row 4 clock: smpcnt=118406 fw_ts_us=41830193 host_epoch_us=1758352443110000
1842300,1798210,812006,809910,98,142,1,APPLIED
1842303,1798222,812009,809902,98,142,1,APPLIED
1842297,1798245,812001,809915,98,142,1,APPLIED
1842304,1798233,812007,809908,98,142,1,APPLIED
# @row 8 gap: missing=2
# @row 8 clock: smpcnt=118412 fw_ts_us=41842193 host_epoch_us=1758352443122000
1842299,1798190,812004,809919,98,142,1,APPLIED
1842301,1798205,812011,809901,98,142,1,APPLIED
1842296,1798260,812003,809913,98,142,1,APPLIED
# @row 11 stall: dt=87600us
# @row 11 clock: smpcnt=118415 fw_ts_us=41933793 host_epoch_us=1758352443213600
1842302,1798218,812008,809917,98,142,1,APPLIED
1842300,1798241,812005,809904,98,142,1,APPLIED
# @row 13 afe: cause=hgac afe_prf_hz=500 afe_numav=1 afe_iled1_ua=25000 afe_iled2_ua=25000 afe_iled_range_ma=50 afe_sep_gain=1 afe_rf1_ohm=25000 afe_cf1_pf=5 afe_rg1_ohm=0 afe_stg2en1=0 afe_rf2_ohm=50000 afe_cf2_pf=5 afe_rg2_ohm=0 afe_stg2en2=0 afe_ambdac_ua=0 afe_ri_ohm=100000
# @row 13 clock: smpcnt=118417 fw_ts_us=41937793 host_epoch_us=1758352443217600
1842251,1798195,406012,809916,98,141,1,APPLIED
1842249,1798207,406006,809906,98,141,1,APPLIED
```

*(2 485 ordinary rows omitted — `@row 15` through `@row 2499` — nothing changes.)*

**Part 2 — HGAC halves RF2 as well, the other channel:**

```
# @row 2500 afe: cause=hgac afe_prf_hz=500 afe_numav=1 afe_iled1_ua=25000 afe_iled2_ua=25000 afe_iled_range_ma=50 afe_sep_gain=1 afe_rf1_ohm=25000 afe_cf1_pf=5 afe_rg1_ohm=0 afe_stg2en1=0 afe_rf2_ohm=25000 afe_cf2_pf=5 afe_rg2_ohm=0 afe_stg2en2=0 afe_ambdac_ua=0 afe_ri_ohm=100000
# @row 2500 clock: smpcnt=120904 fw_ts_us=46911793 host_epoch_us=1758352448191600
1842252,1798188,406008,404955,98,141,1,APPLIED
1842248,1798172,406003,404948,98,141,1,APPLIED
```

*(2 498 ordinary rows omitted — `@row 2502` through `@row 4999`.)*

**Part 3 — the next periodic anchor, and close:**

```
# @row 5000 clock: smpcnt=123404 fw_ts_us=51911793 host_epoch_us=1758352453191600
1842245,1798165,406009,404951,98,141,1,APPLIED
1842253,1798183,406004,404946,98,141,1,APPLIED
```

*(8 ordinary rows omitted — `@row 5002` through `@row 5009`.)*

```
# @row 5010 end: gaps=1 stalls=1
# @row 5009 clock: smpcnt=123413 fw_ts_us=51929793 host_epoch_us=1758352453209600
```

Reading it in order:

- **The header — identity and provenance as file keys, the wire frame as evidence.** `board`, `fw`,
  `lib`, `build`, `elfsha`, `idfver` are R26 keys, one per line, parsed once. The `# from-board:`
  line is the `$CFG` the lab actually received, kept because it is cheap and it is evidence
  (R24b); a P0 file written by an incubator simply would not have it. Nothing below reads it.
- **`@row 0` — the opening state, three snapshots and an anchor.** `afe:` is everything F5's
  formulas need to turn a code into V_TIA, I_PD or OT — RF, RG, stage 2, AMBDAC, ILED, Ri — plus
  PRF, averages and CF; `timing:` the 28 timer registers by datasheet name plus the period count;
  `alg:` the library's parameters, integers in ms/mHz/pA where a unit exists, reals for the two
  dimensionless SpO2 coefficients (R24a). Each `cause=open`. The `clock` line ties that state to
  the board's sample counter, its own microsecond timer and the host's clock — the three numbers
  any later row's instant is interpolated from (R12b). Compare `afe:` with the `from-board:` line
  above it: same facts, one representation each, no `tia1=50k` beside `rf1_ohm=50000`.
- **`@row 4` — a `$SET`, not an RF change.** Alex (or a script) moved `hgac_v_tia_high1` from 0,750
  to 0,780. That is an `alg` parameter, so only `alg:` is re-written — **in full**, `cause=set`;
  `afe:` and `timing:` are not repeated because nothing in them changed. A reader that kept the last
  line of each domain now holds the new state with no history to replay. RF is untouched; the
  `clock` line that follows is required by R12b for every event, not evidence that RF moved.
- **`@row 8` — a gap.** Two samples' worth of UDP payload never arrived; `missing=2` says so, and
  the `smpcnt` on the next `clock` line jumps by 3 (2 lost + the one that did arrive) instead of 1.
  Row indices stay sequential in the file regardless — `rows == Δsmpcnt` (minus the missing count)
  is exactly what lets a reader prove it later (R12b).
- **`@row 11` — a stall.** The counter stays contiguous (`smpcnt` +1, per F6), but the board's own
  read was blocked for 87 600 µs — the campaign's worst measured case — and `fw_ts_us` shows the
  full delay directly; no samples were lost, real time simply passed without one being taken.
- **`@row 13` — HGAC halves RF1.** R21a/R24: a **full** `afe:` line, `cause=hgac`, identical to the
  `@row 0` one except `afe_rf1_ohm=25000` — and that "except" is checkable by a script, because the
  two lines share every other key and integers compare exactly (R30). No `$M4`-style column ever
  carried this: the file says it happened at exactly this row and what the whole AFE state is from
  here on, which is everything a reader needs — constant until the next `afe:` line. `ALED1` drops
  from ≈812 000 to ≈406 000 right there, almost exactly halved,
  because it is a raw code and RF1 gates that channel's whole gain — the drop *is* why HGAC moved
  it. `OT1` barely moves (1 842 251 vs the rows before), because `OT = V_TIA / RF` and halving RF
  cancels the gain change: the R-invariance the AGC design relies on
  (`project_gain_changes_ratio_influence_task`) is visible directly in these two columns. `ALED2`
  and `OT2` (RF2's channel) are untouched, because only `rf1` appears in the change-event.
- **`@row 2500` — HGAC halves RF2.** The same mechanism, the other channel, 2 485 ordinary rows
  later: another full `afe:`, now with both `afe_rf1_ohm=25000` and `afe_rf2_ohm=25000`. `ALED2`
  drops from ≈809 900 to ≈404 950, `OT2` barely moves, and `ALED1`/`OT1` stay exactly where the
  row-13 event left them — which the line itself confirms, since `afe_rf1_ohm` has not changed.
- **`@row 5000` — a periodic anchor, tied to no event.** `smpcnt`, `fw_ts_us` and `host_epoch_us`
  have advanced by the elapsed time since `@row 0` — 10 089 600 µs, a little over 10 s: 5 000 rows
  at 2 000 µs plus the 4 000 µs the gap's two missing samples still cost in real time plus the
  stall's 85 600 µs overshoot (its row already carried a nominal 2 000 µs; 87 600 − 2 000 is the
  excess). That is what R12b's "~10 s cadence" means: paced by the clock, not by a fixed row count.
- **`@row 5010` — close.** `end: gaps=1 stalls=1` is the session's own tally, matching the one gap
  and one stall this file actually hit; the accompanying `clock` line is the last of R12b's
  triggers, "at close", so a truncated read still ends on a provable instant. It says `@row 5009`,
  not `5010`: an anchor is a true (row, instant) pair, and row 5010 was never written — the
  closing anchor ties the LAST row that exists to its counter and its clocks (writer, 2026-09-22).

---

## The v0.4 work plan — decided 2026-09-22: implement it

Alex, 2026-09-22: "me da miedo ir mañana al hospital sin haberlo implementado; vamos a implementar
v0.4, prepara un plan." The concern raised before that decision stands and shapes the order below:
**two of v0.4's pieces cannot exist before the campaign** — the RF-as-event rule R21a needs a
firmware change (prerequisite 6: the board must announce HGAC's RF moves; today only `$SET` and
`$CFG?` produce a `$CFG`), and the dictionary R18 does not exist yet and every other piece names
things from it. So the plan builds everything that does not depend on those two, in an order that
never puts the live capture path at risk, and keeps today's writer one flag away at all times.

What makes the risk acceptable: **the `.pnraw` is the record**, verbatim datagrams, append-only,
and the converter regenerates any CSV from it. A CSV format can be wrong and fixed later; a lost
datagram cannot.

### What the recorder can actually see — the constraint that shapes Phase 2

The recorder is read-only by construction (`HubClient(control=False)`, nothing ever calls
`send_to_board()`), so it can only write what reaches it on the wire. Measured in the code:

| Frame | Who asks for it | Reaches the recorder? | Feeds |
|---|---|---|---|
| `$CFG` | the hub, on first sight and on return (`_ask_cfg`) | **yes, always** | R17/R26 identity keys; `afe:` snapshot; `alg:` in part (`fl fh hr2l hr2h hr3h spo2a spo2b`) |
| `$TCFG` (`t1`..`t28`) | nobody, unless `pulsenest_lab.py` asks | only if the lab happened to ask, or the hub replays a cached one | `timing:` snapshot |
| `$LCFG` (`rsqm_*`, `hgac_*`) | nobody, unless the lab asks `$LCFG?` | same | the rest of `alg:` |

The hub already caches and replays all three prefixes (`CFG_PREFIXES`, `_replay_board`), it just
never *asks* for the last two. **D14 below**: the smallest fix is the hub asking `$TCFG?` and
`$LCFG?` right after `$CFG?` on first sight and on return — the same class of action it already
takes, in the one component that is allowed to speak to a board. Until D14 is decided, Phase 2
writes `# @row 0 afe:` from `$CFG` and emits `timing:`/`alg:` **only when the frame has been
seen**, never invented.

### Phase 0 — Safety rails (done 2026-09-22, amended)

* **No new flag.** The plan proposed `--csv-format legacy|v04`; both tools already have `--csv on|off`,
  and `on` *is* the rehearsed writer. Adding a second switch that can only say "legacy" until Phase 2
  is dead code with a runbook line attached — so instead `v04` becomes a **third value of `--csv`**
  when Phase 2 lands (`--csv on|off|v04`, default `on` until Phase 5 flips it). The 117+63 checks
  keep guarding `on` unchanged; whatever happens at the hospital, the default is the writer that was
  rehearsed.
* **Bench corpus frozen: `captures/v04_corpus/`** (git-ignored like every capture). Two sessions:
  `20260922_0219_BENCH_SUBJ01` (one board + the phone's `$VN1` stream, copied from the rehearsal)
  and a 120 s three-board session recorded at fw 0.15 / lib 0.94, so its `$CFG` frames carry
  `cause=`/`ts_us=`/`hgac_rf_changes=`. Every later phase is tested against these bytes; the
  acceptance test of Phase 3 needs them.
* **D14 closed the same day** (below): the hub now asks `$LCFG?` right after `$CFG?`, so the
  `alg:` snapshot has a source on every board the hub sees; `$TCFG` never needed asking — the
  firmware sends it glued to every `$CFG` (`send_cfg_frame()` → `send_tcfg_frame()`).

### Phase 1 — The dictionary, R18 (and it closes D2/R19)

Deliverable: `pulsenest_capture_dict.py` — data, no logic — one entry per column and per
configuration key: name, meaning, unit, type, range, sentinel, provenance (`fw measured` /
`fw computed` / `host` / `derivable` / `config`), domain, version introduced. Columns: the 35 of
`CAPTURE_COLS` under canonical names (R19 grammar `[<origin>_]<quantity>[_<channel>][_<unit>]`,
project naming rules: domain prefix, unit suffix, `adc_code` never `count`) with today's names as
**synonyms**, so nothing that reads a legacy file breaks (R37). Keys: every `$CFG` field mapped
to `afe_*`/`alg_*` with R24a's one-representation rule (`tia1=100K`+`rf1_ohm=100000`+`cf1=100p`+
`cf1_pF=100` collapse to `afe_rf1_ohm=100000 afe_cf1_pf=100`), `t1..t28` to `afe_<register>` names
from the datasheet, `$LCFG` to `rsqm_*`/`hgac_*` with unit suffixes (`_s` → `_ms` integers where the
value is a time). Test: every `CAPTURE_COLS` entry and every field of a real `$CFG`/`$TCFG`/`$LCFG`
line resolves; no two entries share a name; the dictionary is what `header()` will read.
**This phase is pure data and touches no writer. It is the one to do first tonight.**

### Phase 2 — The writer, `CaptureCsvWriter` v0.4 (shared by lab, recorder, converter — R3)

**Done 2026-09-22 as `CaptureCsvWriterV04`, a second class in `pulsenest_capture_csv.py`** (the
legacy class is untouched — a second class was less risk than a mode switch inside every method),
38 checks in `tools/capture_csv_v04_test.py`, replaying the frozen corpus too. Wired into
`pulsenest_recorder.py` and the window as **`--csv v04`** (default still `on`); a 25 s bench
session writes the header below, three snapshots, anchors every 10 s, `end:` on close. Departures
from the list that follows, all deliberate: (a) **item 8 is void — RF left the columns**, because
prerequisite 6 landed the same day (fw 0.15 `cause=hgac`); (b) a domain's FIRST snapshot says the
open cause (`open`|`part`) whenever it becomes known — a `$TCFG` that lands three rows in did not
*change* anything; (c) the closing anchor is tied to the last row written, `@row N-1` (Appendix B
corrected); (d) `alg:` is written only once both `$CFG` and `$LCFG` have been seen — full or
nothing (R24) — which is why D14 mattered; (e) `hgac_rf_changes` is telemetry about events and
goes in no snapshot (an `alg:` line must not move when only RF did). Item 6's `stall` uses F6's
10 ms; items 2, 5 and 7 as written. The original plan, kept for the record:

Same class, new mode; `legacy` stays as the other branch of the same methods. In dependency order:
1. **Header, R5–R8/R17/R26**: UTF-8 no BOM; `# format=incunest_csv/1`, `# profile=P1`, `# writer=`,
   `# source_mac= board= fw= lib= build= libsha= elfsha= idfver=` **parsed from `$CFG`**, then
   `# led1=IR led2=RED probe=<model>` (R23; `probe` operator-entered, D12), `# subject= site=
   condition= session_id= part= prev=` (R33), `# from-board: $CFG,…` demoted to evidence (R24b).
   Everything `session.json` holds that R26 lists moves here (plan §2 as it was: host, recorder
   version, hub, timezone, start; the close-only facts stay in the `# end` line).
2. **Anchors, R12b**: `# @row 0 clock: smpcnt=C fw_ts_us=T host_epoch_us=H` at open, then every
   1 000 rows, at every part boundary and at close. The host clock leaves the data columns (R12,
   `HOST_T_US` goes; R15 decided anchors only).
3. **Snapshots, R24/R24a**: `# @row 0 afe:` from `$CFG`; `# @row 0 timing:` from `$TCFG` and
   `# @row 0 alg:` from `$LCFG` **when seen**; `cause=open`. Integers in natural units, reals only in
   `alg:` (R30). A later `$CFG`/`$TCFG`/`$LCFG` on the wire (a `$SET` from the lab, a board back after
   a restart) → a new snapshot with `cause=set|restart`, and a `# from-board:` copy.
4. **Grammar, R10a**: every special line `# @row N <type>:` with N = data rows already written.
5. **Events, R34/R35**: `# @row N event: <text> smpcnt=<n> host_epoch_us=<t>`; restart = same file +
   event (D4).
6. **Live checks, R12a**: `Δcnt == 1`, field count, monotonic clock — a failed check is a line, never
   a dropped row.
7. **Close, R32**: `# end rows=… skipped=… gaps=… lost=… restarts=…`; parts R33 unchanged.
8. **RF — the documented deviation**: **R21 keeps `RF1_OHM`/`RF2_OHM` as per-sample columns in v0.4
   until prerequisite 6 lands.** With HGAC on, the board moves RF without telling anyone; the
   columns are today the only record of those moves, and R21a-as-event would silently lose them.
   The header says so: `# rf_as_columns=1 reason=fw-prereq-6`. When the firmware announces RF, the
   flag flips and the columns go, exactly as R21a specifies.
Tests: extend `tools/capture_csv_test.py` — one fixture per special line; the Appendix B example
regenerated from the writer, byte for byte, so the spec's example is the test's expected output.

### Phase 3 — The converter, `tools/pulsenest_convert.py` (.pnraw → v0.4 CSV)

**Done 2026-09-22.** `tools/pulsenest_convert.py <session>` replays every `@D` record, with its
recorded stamps, through the same `Recorder` that wrote the session live (`Recorder(clock=…)`,
`raw_mode="off"`), re-issuing the operator's events from `session_events.csv` (the complete log —
an `@E` fired before a stream opened is in no `.pnraw`) and re-applying the state they carried
(subject binding, condition, probe, reference fields, phone id). **Acceptance test met**: with
`--csv on` the three live CSVs of the frozen corpus (3 × 20 000 rows, three boards) come back
**byte for byte identical**, and so does a scripted session with console commands, a gap and a
`# STAT` line, in both formats (`tools/pulsenest_convert_test.py`, 10 checks). `--csv v04` on the
same corpus writes the v0.4 container: 60 042 lines per board, header off the board's own `$CFG`,
`afe:`/`timing:` at `@row 0` (no `alg:` — that session predates D14, so no `$LCFG` is in its
record: the converter invents nothing), anchors every 10 s. Byte-equality in `v04` is between the
live `--csv v04` file and the converted one; against the *legacy* live file the check is the one
above. The original plan, kept:

Reads with `read_pnraw()` (already in `pulsenest_recorder.py`), replays every `("D", …)` record
through the Phase 2 writer, honours `@E`/`@M` as events, splits on the same wall-clock boundaries,
writes `reference_spo2.csv` from `$VN1` records and `session_events.csv` (the same `_ref_row`
logic, imported not copied). **Acceptance test, unchanged from §10 of the recorder spec: its output
equals the live writer's, byte for byte**, on the Phase 0 corpus. Until Phase 5 the live writer is
`legacy`, so this test runs the converter in both modes: `legacy` must equal the live files bit
for bit; `v04` must equal the Appendix B shape.
**This is what makes v0.4 available for every campaign file regardless of what was written live** —
the campaign is not "without v0.4" if the converter exists, even if the flag never flips.

### Phase 4 — Readers (R4/R36/R37/R38)

`read_capture()` in one place: resolves names through the dictionary's synonyms, falls back to
cp1252 for the 121 legacy files, exposes derived views (`_SUB`, OT from codes). `capture_set.py`,
`build_capture_index.py`, `hr1_detector_experiment.py` and the runner read through it, not through
their own header parsing. **Flow CSV Viewer fixture (R36/F11)**: one v0.4 file opened by hand in
Flow and the result recorded in `docs/` — that is the check the whole live-CSV decision rests on,
and it has never been done for the new shape.

### Phase 5 — Flip the live writer (only after 3 and 4 are green on the bench)

Default `--csv-format v04` in both tools; `legacy` stays available; runbook says which flag to
type if a v0.4 file will not open on site. **Not before a bench session of at least one full
10-minute part in `v04`, opened in Flow, with the converter reproducing it byte for byte.**

### Phase 6 — Deferred, by dependency not by choice

* **R21a / prerequisite 6**: firmware emits a `$CFG` (or a lighter RF frame) where HGAC applies a
  move. Library + firmware work, OTA to three boards, verification. Then `rf_as_columns` goes.
* **P0** (incubator writer, D7/D8) — the field budget decision is Alex's and nothing here needs it.
* `session.json` retired in favour of the header — only once Phase 5 has run for a while.

### Before the hospital: what is realistic

Tonight: Phase 0 and Phase 1 entirely, Phase 2 items 1–4 and 8 (header, anchors, `afe:`
snapshot, grammar, RF flag), Phase 3 for the `D` records. That yields a converter that turns any
campaign `.pnraw` into a v0.4 CSV, tested against the bench corpus — and a live path that has not
moved. Items 2.5–2.7, Phase 4's readers and the Flow fixture, and Phase 5's flip are the next day
or after the campaign; none of them is needed for the data to come home v0.4-ready.

### 7. Why today's headers differ between the two live writers (analysed, 2026-09-22)

Alex asked why the `#` lines at the top of a capture differ between `pulsenest_lab.py` and
`tools/pulsenest_recorder(_gui).py`, and whether v0.4 is meant for both. Both questions have
concrete answers.

**They share one writer class** — `CaptureCsvWriter` in `pulsenest_capture_csv.py` (`LabCaptureWriter`
is its old name, kept as an alias) — so the difference is not in the writer, it is in what each
caller hands it as `pre_notes`. Today, three genuinely different shapes exist, none of them v0.4:

1. **`pulsenest_lab.py`** (`_on_cfg_frame_received`, `pulsenest_lab.py:13437`): a hand-formatted,
   human-readable paragraph — `"AFE4490 config — <timestamp>\n  Board: ...\n  Firmware: ...\n  Sample rate: ...\n"` — built as one long f-string. Predates the v0.4 design entirely; not
   machine-parseable without regexing specific label text.
2. **`tools/pulsenest_recorder.py`** (`_open_csv`): a short set of true `# key=value` bookkeeping
   lines (`session=`, `writer=`, `source_ip=`, `part=`, `prev=`, `probe=`) plus **one** line,
   `# from-board: <the raw $CFG wire string, verbatim, unparsed>` — deliberately interim, stated
   in the method's own docstring: it "cannot wait for the v0.4 format and its column dictionary"
   because Flow CSV Viewer already reads today's shape and R18 (the dictionary) does not exist yet.
3. **v0.4 itself** (this document, R17/R22/R26): fully parsed, one key per line, in canonical
   order — identity and provenance first, `from-board:` demoted to optional evidence, everything
   else derived from three structured domain snapshots at `@row 0` rather than living in the
   header at all. **Designed, implemented nowhere.**

**Is v0.4 for both?** Yes, by explicit intent — **R3**: "One writer per platform. `LabCaptureWriter`
for lab, recorder and converter." Neither tool has migrated yet; both are pre-v0.4 shapes that
happened to be built independently, years apart, for different reasons, which is the entire
explanation for why they read differently today. Unifying them is exactly "The v0.4 work plan"
above (§1's dictionary first) — not done as a side effect of this question, since a mid-campaign
rewrite of either writer was not what was asked and is not warranted this week.

**What was changed today, narrowly**: `pulsenest_lab.py`'s Board/MAC and Firmware/Image lines are
now adjacent (were separated by eight lines of AFE analog configuration), because together they
ARE the ISO "monitor" — our monitor is this board running `incunest_afe4490`, and the rest of that
paragraph is *configuration* of the monitor, not its identity. R22 already states this ordering
principle for v0.4 (host anchors, then identity, then configuration, then outputs); the pre-v0.4
header now follows it too, without waiting for the rest of the migration.

---

## Decisions

| | Requirement | Status / recommendation |
|---|---|---|
| D1 | R15 host time | **Closed 2026-09-19: anchors only (B)** |
| D2 | R19 names: freeze existing (A) or new canon (B) | **Closed 2026-09-22 by the plan: new canon (B) in the dictionary, today's names kept as synonyms (R37)** — nothing that reads a legacy file breaks |
| D3 | ~~witness composition~~ | replaced by §I profile table |
| D4 | R35 restart | **Closed: same file + event (A)** |
| D5 | R40 where the spec lives | open — PulseNest recommended |
| D6 | R8/R9 hex prefix, empty cell | decided by the Flow fixture (R36) |
| **D7** | **Field data path and daily budget per incubator** (SD collected by hand? uploaded? MB/day?) | **needed from Alex — it decides D8** |
| **D8** | **P0 waveform tier**: 500 Hz / 125 Hz / 1 Hz outputs + event windows | open; F12 gives the arithmetic |
| D9 | P0 signal representation: `OT1,OT2` only, or `OT1,OT2 + ALED1,ALED2` (+10,6 B/row plain, +4,0 gz) | open; Appendix A lists what the ambient buys |
| **D10** | **R21: RF as column or as change-event** | **Closed 2026-09-20: change-event (R21a), everywhere, not just P0** — recorded as a full `afe:` snapshot (R24, v0.4); blocked on prerequisite 6 (firmware) |
| **D11** | **R24: configuration record — wire frame verbatim, or the file's own snapshot** | **Closed 2026-09-20 (Alex): own snapshot, full, three domains, integers; wire frame demoted to `from-board:` evidence.** Reals admitted in `alg:` only, for dimensionless coefficients |
| D13 | **v0.4 first in the converter (post-processing `.pnraw`) or in the live writer?** | **Plan: converter first, live writer behind `--csv-format` defaulting to `legacy` until Phase 5.** The `.pnraw` makes v0.4 available for every campaign file either way; the live path that was rehearsed stays untouched until the converter reproduces it byte for byte |
| D14 | `timing:`/`alg:` snapshots need `$TCFG`/`$LCFG`, which nobody asked for | **Closed 2026-09-22: the hub asks `$LCFG?` right after `$CFG?`** (`pulsenest_hub.py` `_ask_cfg`, `hub_test.py` 41/41). `$TCFG` needed no request: the firmware sends it with every `$CFG`. So the recorder sees all three frames for every board the hub identifies, and Phase 2 writes the three snapshots at `@row 0` without inventing anything |
| D12 | R23's `probe=<model>` key — read from `$CFG`, or operator-entered? | **Closed 2026-09-22 (Alex): always operator-entered.** ISO 80601-2-61 calibrates a monitor+probe pair; nothing electrical distinguishes one probe model from another, unlike every other R26 identity key. `pulsenest_recorder.py`'s `probe`/`--probe` now write it |

## Prerequisites this list creates

1. `LabCaptureWriter`: UTF-8, empty cell for "not available", `# format=` and `# profile=` lines,
   the R26 identity/provenance keys parsed out of `$CFG`, the three snapshots of R24 built from
   `$CFG`/`$TCFG`/`$LCFG` at open and on every change (`from-board:` verbatim optional), live
   gap/stall checks, anchors, `# end` summary, fixed-point `OT1/OT2` computed from codes.
   **1b. DONE 2026-09-22 — `pulsenest_capture_dict.py`.** The dictionary (R18) must exist first: every `afe_*`, `timing`, `alg` key named, with
   unit and type, before a single snapshot is written — a snapshot with unnamed keys is a wire
   frame again.
2. Firmware: `FW_Ts_us` as 64-bit (F1) — no longer blocking, still a defect.
3. Flow CSV Viewer fixture test (R36).
4. Shared `read_capture()` with the synonym table and derived views (R4/R37); runner alignment (R38).
5. For P0: a writer in the incubator firmware and the budget decision (D7/D8).
6. **DONE 2026-09-22 — lib v0.94 + fw 0.15 (OTA pending).** `_hgac_change_rf()` stamps and counts
   the move; `Cmd_Task` polls `hgacRfChangeCount()` every 50 ms and emits a `$CFG` with
   `cause=hgac,ts_us=<esp_timer at the move>,hgac_rf_changes=<n>` — Serial and UDP, so the hub
   caches and replays it like any `$CFG`. `ts_us` lets the writer place the `afe:` snapshot on
   the exact row; the count exposes moves that landed inside one tick. Original text:
   **Firmware, new (2026-09-20, R21a/D10):** tell the host that HGAC moved RF — a `$CFG` (or a
   lighter frame carrying the new RF) emitted at the point where HGAC applies the move, not only
   from the `$SET` and `$CFG?` handlers that call `send_cfg_frame()` today
   (`main/pulsenest_main.cpp:1138,1236`). The CSV writer turns it into a full `afe:` snapshot
   (R24); the wire shape is the firmware's business. Touches the same code as
   `project_hgac_implementation_task` and `project_gain_changes_ratio_influence_task`. Blocks R21a
   until done — without it, RF columns stay in every profile as today.
