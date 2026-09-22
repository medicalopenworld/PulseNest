# Hospital campaign runbook — recording a session

What to do, in order, to record a session with `tools/pulsenest_recorder_gui.py`. Written for the
person at the cot side, to be followed without reading any other document. The reasoning behind
each rule is in `pulsenest_recorder_spec.md`; this page only says what to do.

Campaign shape: **three boards on three babies**, each baby also wearing a commercial pulse
oximeter, a phone running VideoNest pointed at one monitor, one laptop.

**One window per baby.** A session is a baby, not a run of the program, so there is one window per
cot and finishing with one baby does not touch the other two. Each window records exactly one
board and writes its own session directory.

---

## 1. The day before

- [ ] **Boards flashed and verified.** `docs/boards.md` lists MAC, revision and last build. All
      three should report the same `fw`, `build` and `elfsha`.
- [ ] **Write down which board goes to which cot**, by the **last four hex digits of its MAC** —
      that is what you will type. The three V18 are `8850`, `825C` and `87A4`.
- [ ] **Disk**: measured, **17 MB per minute per board** (`.pnraw` plus the live CSV), so about
      **1 GB per board per hour**. Three boards for eight hours ≈ **24 GB**. Leave at least twice
      that free; the recorder refuses to start below 2 GB and stops cleanly if it gets there.
      `--raw off` halves it and gives up the verbatim copy of what arrived on the wire.
- [ ] **Laptop clock synchronised** (Windows: Settings → Time → Sync now). Everything is aligned
      afterwards through the laptop's clock; a laptop that is ten minutes off makes the photos
      useless.
- [ ] **Phone**: VideoNest installed and pointed at the right monitor, battery charged, **cloud
      photo sync OFF** (§11 of the spec: the photos are health data).
- [ ] **Know the phone's device id** — the word VideoNest puts in every frame and in every
      photograph's filename, e.g. `J6plusACM`. Tape it to the case. You will choose it in the
      window, and it is what says which cot that phone is filming.
- [ ] **Photograph the commercial monitor's SpO2 settings screen and its model label**, for each
      monitor. The **averaging time** is the number that decides whether our SpO2 can be compared
      with theirs at all, and it is not recorded anywhere else. Beware: Nellcor's *SatSeconds* is
      an alarm delay, **not** an averaging window.
- [ ] **Consent** obtained beforehand, on paper. The recorder does not ask and does not check;
      it is written into the `consent` column of `captures/truth.csv` afterwards.
- [ ] Subject codes agreed in advance: `SUBJ01`, `SUBJ02`, `SUBJ03`. **Never a name**, anywhere,
      not even in a free-text note. The window refuses anything that is not `SUBJ` plus digits.

---

## 2. Starting

**Prepare one TOML file per cot the day before** — copy `docs/session_configs/example.toml` to
`subj01.toml`, `subj02.toml`, `subj03.toml`, and fill in that baby's board, subject, phone and
monitor from the photo taken in §1. Nothing about these files is secret and nothing in them is a
name — `location` and `subject` are codes — so they can sit anywhere convenient, e.g. next to the
runbook, or on a USB stick brought to site.

Open one terminal in `C:\PRJ\MOW\PulseNest` and launch **one window per baby**:

```
pythonw tools/pulsenest_recorder_gui.py --config subj01.toml
pythonw tools/pulsenest_recorder_gui.py --config subj02.toml
pythonw tools/pulsenest_recorder_gui.py --config subj03.toml
```

`--config` reads `location`, `operator`, `board`, `subject`, `videonest`, `note` and the four
`ref.*` fields in one go — the ten things a session needs to say who it is about, as opposed to
`--hub`/`--out`/`--raw`/`--split-min`/`--duration`, which are how the tool behaves and are the
same for all three cots. **Full substitution**: typing any of those ten on the command line
*alongside* `--config` is refused outright, never silently merged, so the file is always the
whole story or none of it. If a value needs to change on the day — the phone died, a different
oximeter arrived — edit the file, or drop `--config` for that window and type the flags by hand
(below); do not mix the two.

Without a prepared file, the equivalent by hand is:

```
pythonw tools/pulsenest_recorder_gui.py --location HOSP01 --operator AC --board 8850 --subject SUBJ01 --videonest J6plusACM --note "term neonate, resting after a feed" --ref-model "Masimo Radical-7" --ref-avg 8 --ref-probe-site "left thumb"
```

`--location` is a **coded** place, never a described one: `BENCH` for our bench, `HOSP01`,
`HOSP02`… for clinical sites, `SITE01`… for anywhere else. A place plus a date plus a subject
identifies a person even with no name written anywhere; what the code means lives in the private
mapping file, beside the `SUBJnn` one.

`--board` is a MAC suffix of any length. If it matches two boards the session refuses to start,
rather than recording a baby nobody asked for. `--subject`, `--videonest` and `--note` can be
left out and chosen in the window instead. `--note` is worth typing here anyway: it is written
verbatim as a NOTE event **and** its sanitised form seeds the starting CONDITION, so a session
launched with `--note` already has a canonical CSV name instead of the provisional `<MAC>_…` one
— though for a long note that name can come out truncated and ugly (`TERM-NEONATE-RESTING-AFT`,
measured), which is fine: it is only a starting point, fix it in the window's CONDITION field the
moment it looks wrong.

`--ref-model`, `--ref-avg`, `--ref-probe-site` and `--ref-note` describe the commercial monitor
beside that baby, from the photograph you took the day before (§1). They do not change during the
session, so they are typed once, in the file or on the command line, rather than in the window —
the window shows them under **MONITOR**, read-only, so a typo is visible instead of silent.
`--ref-avg` is the number that
decides whether our SpO2 can be compared with theirs at all; leave it out and correct it later
from the console tool (`ref SUBJ01 avg 8`) if you did not have the photo to hand yet.

The hub starts on its own if it is not already running.

Then, in each window:

- [ ] **Wait for its board.** The window says `waiting for board *8850` until the board speaks.
      When it appears, the header line shows the MAC, the subject, `dgrams` climbing and `part`.
- [ ] **A header that says `UNBOUND`, or warns in amber, is a window that needs you.** That is the
      whole point of the header: no subject, no condition, gaps, a silent board, a board that
      rebooted.
- [ ] **REFERENCE**: tick `VideoNest UDP` in the window watching the cot the phone is filming, and
      choose its device id. **The list only shows phones actually heard on the wire**, so if the id
      is not there, VideoNest is not sending — that is the answer, before you open any menu. Leave
      it unticked in the other two windows.
- [ ] **CONDITION**: `RESTING`, `FEEDING`, `HANDLING`… Change it whenever it changes; each change
      is a timestamped event. The CSV **filename** takes the last value, and without a condition
      the file keeps its provisional `<MAC>_…` name.
- [ ] **NOTE**: where our probe is, e.g. `probe on left foot`. This matters more than it looks —
      in a baby with a patent ductus, a foot and a right hand genuinely read differently, and an
      unrecorded difference is read later as our error.
- [ ] **Clock anchor**, only if you are filming or photographing a monitor: point the phone at the
      laptop's clock for a few seconds and press `CLOCK ANCHOR` while it is in shot. That is what
      places a reading taken from the video on our timeline without trusting two clocks to agree.
- [ ] **MONITOR** shows what `--ref-*` recorded. If it says `(not set)`, either you did not pass
      those flags or something in them was wrong — correct it from the console tool rather than
      losing the reference for the whole session.

---

## 3. During the session

- [ ] **Read the commercial monitor and press `RECORD` often.** Type the SpO2 in the spinbox,
      the pulse rate too if the monitor shows one and you want a pulse reference; leave it at `--`
      otherwise. A reading per baby every few minutes, and always around anything interesting.
      **Read the number off the monitor's own screen, never off ours.** Do not correct for delay:
      the instant of the click is what is recorded, and the monitor averages over seconds anyway.
- [ ] **The list beside `RECORD` is every reading you have taken.** Double-click one to correct a
      mistyped number, or select it and `DELETE selected` to withdraw it. Nothing is erased: the
      file keeps the original and the correction, and a corrected reading keeps its own time.
      `DELETE LAST` withdraws the most recent.
- [ ] **Mark what happens to the baby** in the NOTE box: a feed, a nappy change, an alarm on the
      monitor, a probe that was moved, a desaturation. None of it can be reconstructed afterwards.
- [ ] **Watch the header line of each window.** `gaps` climbing means datagrams were lost on the
      air; `SILENT` means nothing has arrived for five seconds.
- [ ] **A phone that stops is the likeliest failure of a session** — battery, app backgrounded,
      camera nudged. Nothing on our side will say so loudly, so glance at the phone itself.
- [ ] Each window writes a new part on every **10-minute wall-clock boundary**, in both the
      `.pnraw` and the CSV (`…_p02.csv` at 10:20, `…_p03` at 10:30). That is normal, and it is
      what keeps a CSV small enough to open.

- [ ] **`ABNORMAL CONDITION`**, if the data is briefly suspect — probe loosely applied, motion,
      an alarm interfering — and not worth losing. Press it on; recording never stops. Press it
      off again once it passes. **Never a pause**: a pause risks forgetting to resume, which loses
      data that was perfectly good; a wrong flag costs nothing to undo. The button turns purple
      while active, so it cannot be forgotten silently the way a paused recording could be.

---

## 4. Closing

- [ ] Press **`STOP SESSION`**, or close the window: it asks first, so a stray click cannot end a
      recording. There is no Ctrl+C to get wrong.
- [ ] **Open one CSV in Flow CSV Viewer before leaving.** This is the check that says the session
      is good *here* instead of a week later. Each part is about 87 MB.
- [ ] At close each CSV is renamed to `SUBJ01_RESTING_<date>_<time>_pNN.csv` — all parts or
      none. A file still called `<MAC>_…` means the condition was never set.
- [ ] **Copy the whole session directory** to a second disk before leaving. Each baby has its own,
      under `captures/sessions/<YYYYMMDD>_<HHMM>_<SITE>_<SUBJnn>/`.
- [ ] Copy the phone's photos and videos to the same place. They never reach the laptop by
      themselves.
- [ ] Nothing of this is committed to the repository (`captures/` is git-ignored, and session
      directories are never committed — not even `session.json`).

---

## 5. When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `waiting for board *8850` and it never appears | The board is not reaching the laptop: power, WiFi, or a new lease that has not sent a `$CFG` yet | Wait a few seconds, then check the board's power and the hotspot |
| The device id is missing from the REFERENCE list | VideoNest is not sending: app closed or backgrounded, phone off the WiFi, wrong destination address | Wake the phone and check VideoNest; the boards are unaffected |
| `SILENT` in the header | No datagram for five seconds | Usually the board rebooted or lost WiFi. It is recorded as a note and recording continues; when it comes back, **even on a new address**, it continues in the same file |
| `gaps` climbing | Datagrams lost on the air | Usually the hotspot. The rows are not recoverable but the gap is recorded, so the capture stays honest |
| `dgrams` climbing with no baby connected | Normal: the board streams with no probe | Nothing |
| The window closes by itself | Disk below the floor, or `--duration` expired | The session closed cleanly and is intact |
| The waveform freezes or the window dies | pyqtgraph, which has killed the lab window 28 times | Only that baby's recording stops; the other two are separate programs. Everything written is on disk. Relaunch, and press `PLOTS` to record without the waveform |
| A crash of any kind | | The `.pnraw` and the CSV are append-only and end on a complete record. What is lost is metadata: `SESSION_END`, the clock drift, and the rename — the files keep their provisional `<MAC>_…` names |

**The recorder never writes to a board.** It cannot change a setting or reboot anything, by
construction. Configuration is done from the lab before the session.

---

## 6. Afterwards

Off-site, the converter turns each `.pnraw` back into the capture CSV and reports how the phone's
readings compared with what the operator typed. That tool is being written; until then, keep the
session directories exactly as they are.

`reference_spo2.csv` is already written during the session: the phone's readings and yours, one
row each, side by side, so the phone's can be reviewed against the photographs — with what you
typed at that same minute right beside them — without waiting for anything.
