# Hospital campaign runbook — recording a session

What to do, in order, for the person at the cot side. The reasoning behind each rule is in
`pulsenest_recorder_spec.md`; this page only says what to do.

**The shape of a campaign:** three boards on three babies, each baby also wearing a commercial
pulse oximeter, a phone running VideoNest pointed at each monitor, one laptop. **One window per
baby**, each recording one board into its own session directory. Finishing one baby does not
touch the other two.

---

## 1. The day before

- [ ] **Boards flashed and verified** — `docs/boards.md`. The launcher (§2) will say whether the
      three run the same firmware.
- [ ] **One `.toml` per cot** in `docs/session_configs/`: copy `example.toml` to `subj01.toml`,
      `subj02.toml`, `subj03.toml` and fill in, for that baby:
      `subject` (`SUBJnn`, **never a name**), `location` (a site code), `operator` (initials),
      `board` (last four hex digits of the board's MAC: `8850`, `825C`, `87A4`), `probe` (our
      probe's model), `note` (free text, written once at start), and under `[ref]` the commercial
      monitor: `model`, `probe-site`, `videonest` (the phone's device id), `avg` (its averaging
      time in seconds — photograph the monitor's SpO2 settings screen to get it; it decides
      whether the two SpO2 can be compared at all).
- [ ] **Disk**: about **1 GB per board per hour**. Three boards for eight hours ≈ 24 GB; leave
      twice that free. The recorder refuses to start below 2 GB.
- [ ] **Laptop clock synchronised** (Settings → Time → Sync now). Everything is aligned through
      this clock.
- [ ] **Phones**: VideoNest installed and pointed at the right monitor, battery charged, **cloud
      photo sync OFF** (the photos are health data). Tape the device id to the case.
- [ ] **Consent** on paper beforehand. The recorder does not ask.
- [ ] Subject codes agreed: `SUBJ01`, `SUBJ02`, `SUBJ03`. The code-to-person list stays in the
      private file, never in the repository, never in a note.

---

## 2. Starting

**Double-click `PulseNest Session` on the desktop** (made once per laptop with
`.\scripts\make_session_shortcut.ps1`). The window is the checklist, checked live:

- **BOARDS ON THE AIR** — every board streaming, and one line saying whether all run the same
  firmware. A board that goes quiet turns amber (`SILENT`), red after a minute.
- **PHONES HEARD** — every VideoNest phone sending, with its last frame and clock offset.
- **Disk** as hours of recording, and the **laptop clock** in large digits.
- **COTS** — one row per `.toml`: which live board it matches and whether its phone has been
  heard. Files are re-read by themselves when edited (**EDIT** opens one in the system editor).

Press **START** on each cot, or **START ALL COTS**, and **FLEET MONITOR** for the console
overview. Each START opens one recorder window, as a process of its own: the launcher can be
closed afterwards and the recordings continue. The hub starts by itself.

From a terminal, the same thing is:

```
pythonw tools/pulsenest_recorder_gui.py --config docs/session_configs/subj01.toml
```

Then, in each recorder window:

- [ ] **Wait for its board.** The header says `waiting for board *8850` until the board speaks;
      then it shows the MAC, the subject, `dgrams` climbing and `part`.
- [ ] **Check the panel "This board: the session, as launched".** It shows what the `.toml`
      said — SUBJECT, LOCATION, OPERATOR, BOARD, PROBE, NOTE, MONITOR, REFERENCE — read-only. A
      typo means: close the window, fix the file, START again. Nothing is edited in the window.
- [ ] **REFERENCE** shows the phone named in the file. If the file named none, tick
      `VideoNest UDP` here and choose the phone — the list only shows phones actually heard.
- [ ] **A header that says `UNBOUND` or warns in amber needs you**: no subject, gaps, a silent
      board, a board that rebooted.
- [ ] **CLOCK ANCHOR**, once per session (twice, start and end, also measures drift): press it,
      the window fills with the laptop's clock in large digits; **photograph that screen with the
      VideoNest phone**, then click to close. The event is written when you press.

---

## 3. During the session

- [ ] **Read the commercial monitor and press `RECORD` often** — the SpO2 from the monitor's own
      screen, the pulse rate too if you want a pulse reference. A reading every few minutes per
      baby, and always around anything interesting. Do not correct for delay.
- [ ] **The list beside `RECORD` is every reading taken.** Double-click to correct, select and
      `DELETE selected` to withdraw. The file keeps the original and the correction.
- [ ] **NEW EVENT**: type what happens and press Enter — a feed, a nappy change, an alarm on the
      monitor, the probe moved (`probe on left foot`), a desaturation. None of it can be
      reconstructed afterwards.
- [ ] **ABNORMAL CONDITION** when the data is briefly suspect — probe loose, motion, an alarm
      interfering. Recording never stops; the button turns purple and writes a start/end pair.
      Press again when it passes. **Never a pause.**
- [ ] **Watch each header**: `gaps` climbing means datagrams lost on the air; `SILENT` means
      nothing for five seconds. **A phone that stops is the likeliest failure** — glance at the
      phone itself, or at PHONES HEARD in the launcher.
- [ ] A new part is written every **10 minutes** (`…_p02.csv`, `…_p03`). That is normal.

---

## 4. Closing

- [ ] **`STOP SESSION`** or close the window; it asks first.
- [ ] **Open one CSV before leaving** (Flow CSV Viewer): the check that the session is good here,
      not a week later.
- [ ] **Copy the whole session directory** — `captures/sessions/<date>_<time>_<SITE>_<SUBJnn>/` —
      and the phone's photos and videos to a second disk. The photos never reach the laptop by
      themselves.
- [ ] Nothing of this is committed to the repository.

---

## 5. When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `waiting for board *8850` never ends | The board is not reaching the laptop | Check the board's power and the hotspot; the launcher shows what is on the air |
| The phone is missing from the REFERENCE list or from PHONES HEARD | VideoNest is not sending | Wake the phone, check the app; the boards are unaffected |
| `SILENT` in the header | No datagram for five seconds | Usually a reboot or lost WiFi; recording continues in the same file when it comes back |
| `gaps` climbing | Datagrams lost on the air | Usually the hotspot; the gap is recorded |
| The window closes by itself | Disk below the floor, or `--duration` expired | The session closed cleanly |
| The waveform freezes or the window dies | pyqtgraph, which has crashed before | Only that baby stops; everything written is on disk. START again from the launcher, press `PLOTS` off |
| REFERENCE is greyed and shows the wrong phone | `[ref].videonest` in the file was wrong | Close the window, fix the file, START again |
| Any crash | | The `.pnraw` and the CSV are append-only and end on a complete record |

**The recorder never writes to a board.** Configuration is done from the lab before the session.

---

## 6. Afterwards

`tools/pulsenest_convert.py <session dir> --csv v04` rebuilds the CSVs from the `.pnraw` and
proves they match. `reference_spo2.csv` in the session directory holds the phone's readings and
yours side by side, with the clock offset per frame.
