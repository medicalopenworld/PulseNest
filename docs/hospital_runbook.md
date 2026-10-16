# Hospital campaign runbook — recording a session

What to do, in order, for the person at the cot side. The reasoning behind each rule is in
`pulsenest_recorder_spec.md`; this page only says what to do.

**The shape of a campaign:** up to three boards, one per baby, each baby also wearing a
commercial pulse oximeter, a phone running VideoNest pointed at each monitor, one laptop.
**Which babies, and how many, is decided on the day**, at the cot side; the day before prepares
the kits, not the babies. **One window per baby**, each recording one board into its own session
directory. Finishing one baby does not touch the other two.

---

## 1. The day before

- [ ] **Boards flashed and verified** — `docs/boards.md`. The launcher (§2) will say whether the
      three run the same firmware.
- [ ] **One `.toml` per kit** (board + its phone) in `docs/session_configs/`: copy `example.toml`
      to `cot1.toml`, `cot2.toml`, `cot3.toml` (the file name is not used anywhere) and fill in
      only what does not depend on the baby: `location` (a site code), `operator` (initials),
      `board` (last four hex digits of the board's MAC: `8850`, `825C`, `87A4`), `probe` (our
      probe's model) and, under `[ref]`, `videonest` (the device id of the phone that goes with
      this kit). **Leave `[subject]`, `note` and the rest of `[ref]` out**: they are the baby's and
      are filled in on the day (§2). A file without `subject` shows `(missing: add it to the
      file)` in the launcher; that is the expected state the day before.
- [ ] **Where the sessions go**: the launcher's **sessions in** line, under the free space, names
      the folder every START writes to (`captures/sessions` by default); **CHANGE FOLDER…** beside
      it points it at an external disk and remembers it. A remembered folder that is not there at
      start (the disk unplugged) falls back to the default and says so in amber.
- [ ] **Disk**: about **1 GB per board per hour**. Three boards for eight hours ≈ 24 GB; leave
      twice that free. The recorder refuses to start below 2 GB.
- [ ] **Laptop clock synchronised** (Settings → Time → Sync now). Everything is aligned through
      this clock.
- [ ] **Phones**: VideoNest installed, battery charged, **cloud photo sync OFF** (the photos are
      health data). Tape the device id to the case, and the kit's board digits next to it.
- [ ] **Consent forms** on paper, enough for the babies that may be chosen. The recorder does
      not ask.
- [ ] **Know the next free subject codes** (`SUBJnn`, in order, from the private code-to-person
      list). The codes are given out on the day, one per baby chosen; the list stays in the
      private file, never in the repository, never in a note.

---

## 1 bis. Preparing a laptop (once per machine)

The laptop needs Python, the repository and the desktop icon. Done once; nothing here is
repeated on the day.

- [ ] **Python 3.11 or newer** from python.org, with the installer's **"Add python.exe to PATH"**
      box ticked. Without it the icon script stops and says so (`pythonw.exe not on PATH`).
- [ ] **The five packages**, from any terminal:
      ```
      pip install PyQt5 pyqtgraph numpy scipy pyserial
      ```
- [ ] **The repository** cloned into a fixed folder, e.g. `C:\PRJ\MOW\PulseNest`. The icon points
      at that folder: if the folder is moved, repeat the next step.
- [ ] **The desktop icon**: open PowerShell in the repository folder and run
      ```
      .\scripts\make_session_shortcut.ps1
      ```
      It prints the shortcut it wrote and the program it launches. Running it again just
      rewrites the icon.
- [ ] **The network, in3wifi.** The boards and the phones send to the laptop at `192.168.137.1`,
      the address of the Windows Mobile Hotspot; a hospital has no internet connection to share,
      and Settings refuses the hotspot without one. The way round, once per laptop
      (administrator): run **`hdwwiz.exe`** as administrator (Win+R, `hdwwiz`, Ctrl+Shift+Enter;
      it is Device Manager → Action → Add legacy hardware) → Next → **Install the hardware that I
      manually select from a list** → Network adapters → Microsoft → **Microsoft KM-TEST Loopback
      Adapter** → Next → Finish. No address to set. It stays through reboots and updates. Then
      Settings → Network & internet → Mobile hotspot: name **in3wifi**, the boards' password, band
      **2.4 GHz** (the boards have no 5 GHz); remembered too. On the day, `.\scripts\hotspot.ps1 on`
      (§2) shares that adapter and the hotspot comes up with no internet at all. The hotspot itself
      is off after every reboot.
- [ ] **Check**: double-click `PulseNest Session` on the desktop. The launcher window opens
      (BOARDS ON THE AIR, PHONES HEARD, SESSION / SUBJECT config files) with no console behind it; the hub starts by itself.
      Close it. The `.toml` files of §1 can be written now or on the day before.

---

## 2. Starting

**On the day, first**, from PowerShell in the repository folder:

- [ ] **in3wifi up.** The launcher (next step) watches it on its NETWORK line: green when the
      laptop is `192.168.137.1`; red, with **TURN ON in3wifi…**, when it is down and nothing is
      on the air. The button explains what will change and asks before doing it; the same by
      hand is `.\scripts\hotspot.ps1 on` (its `status` lists the boards as they join, by MAC;
      `off` at the end). No internet is needed or shared. If the launcher says the loopback
      adapter is missing, it offers to open the Add Hardware wizard (§1 bis); it never installs
      it itself. Boards powered before this are fine:
      since fw 0.23 a board keeps looking for its networks and joins within 30 s; if the hotspot
      drops and comes back, the boards come back with it, no power cycle needed.
- [ ] **Phones on in3wifi.** Mobile data can stay on: VideoNest sends through the Wi-Fi network
      itself, whether or not it has internet (since 2026-10-15; before that, a phone with data on
      sent by the mobile network and nothing arrived). Android asks whether to stay on a network
      without internet: yes, and "don't ask again".

**Once the babies are chosen**, for each one:

- [ ] Consent signed. Give the baby the next free subject code and write the pair in the
      private list.
- [ ] Clip our probe on, put the kit's phone in front of that baby's monitor, and photograph the
      monitor's SpO2 settings screen (its averaging time).
- [ ] In the launcher (below), press **EDIT** on that kit's row and complete the file: the
      `[subject]` table — `id` (`SUBJnn`, **never a name**), `gest_age` at birth as the chart
      writes it (`"30w+2d"`), `age` with its unit (`"14d"`), `weight_g` (current), `skin` (Monk
      Skin Tone 1–10, judged at the probe site against the swatches; how, in `example.toml`) — `note` (free
      text, written once at start), and under `[ref]` the monitor: `model`, `avg` (the averaging
      time from the photo, in seconds — it decides whether the two SpO2 can be compared at all),
      `probe-site` only if *its* probe is not on a foot. Save; the row updates by itself. A
      `[subject]` line not known yet can be left out and given later on the recorder console
      (`subj SUBJ01 weight_g 1500`).
      Everything is read from the file at START; the recorder window only shows it (the phone
      is the one thing it can still choose, from the phones heard). A typo means: close the
      window, fix the file, START again.

**Double-click `PulseNest Session` on the desktop** (made once per laptop, §1 bis). The window
is the checklist, checked live:

- **BOARDS ON THE AIR** — every board streaming, and one line saying whether all run the same
  firmware. A board that goes quiet turns amber (`SILENT`), red after a minute.
- **PHONES HEARD** — every VideoNest phone sending, with its last frame and clock offset.
- **Disk** as hours of recording, and the **laptop clock** in large digits.
- **SESSION / SUBJECT config files** — one row per `.toml`: which live board it matches and
  whether its phone has been heard. A session reads its file once, at START: edit before
  (**EDIT** opens one in the system editor; the table follows). The folder named above the
  table is a link that opens it; **CHANGE FOLDER…** beside it points the table at another
  folder and remembers it. Hover anything for its tooltip.

Press **START** on each cot, and **FLEET MONITOR** for the console
overview. Each START opens one recorder window, as a process of its own: the launcher can be
closed afterwards and the recordings continue. The hub starts by itself.

From a terminal, the same thing is:

```
pythonw tools/pulsenest_recorder_gui.py --config docs/session_configs/cot1.toml
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
- [ ] **Copy the whole subject folder** — `<SUBJnn>/`, holding that baby's sessions
      `<SUBJnn>_<SITE>_<date>_<time>/`, in the folder the launcher names on its **sessions in**
      line (`captures/sessions` unless changed) —
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
