# Hospital campaign runbook — recording a session

What to do, in order, to record a session with `tools/pulsenest_recorder.py`. Written for the
person at the cot side, to be followed without reading any other document. The reasoning behind
each rule is in `pulsenest_recorder_spec.md`; this page only says what to do.

Campaign shape: **three boards on three babies**, each baby also wearing a commercial pulse
oximeter, the phone running VideoNest pointed at one monitor, one laptop.

---

## 1. The day before

- [ ] **Boards flashed and verified.** `docs/boards.md` lists MAC, revision and last build. All
      three should report the same `fw`, `build` and `elfsha`.
- [ ] **Disk**: a session costs **0,5 GB per board per hour** (`--raw full`). Three boards for
      eight hours ≈ **12 GB**. Leave at least twice that free; the recorder refuses to start
      below 2 GB and stops cleanly if it gets there.
- [ ] **Laptop clock synchronised** (Windows: Settings → Time → Sync now). Everything is aligned
      afterwards through the host clock; a laptop that is ten minutes off makes the photos
      useless.
- [ ] **Phone**: VideoNest installed and pointed at the right monitor, battery charged, **cloud
      photo sync OFF** (§11 of the spec: the photos are health data).
- [ ] **Consent** status known for each subject.
- [ ] Subject codes agreed in advance: `SUBJ01`, `SUBJ02`, `SUBJ03`. **Never a name**, anywhere,
      not even in a free-text note.

---

## 2. Starting a session

Open one terminal in `C:\PRJ\MOW\PulseNest` and run:

```
python tools/pulsenest_recorder.py --site HOSP01 --operator AC
```

`--site` is a short code that names the session directory; `--operator` is initials or a role.
The hub starts on its own if it is not already running. Add `--event-port 5099` if a panel
process will send events.

Then, in order:

- [ ] **Wait for the three boards.** Type `status`. Every board should appear as
      `board_<MAC>` with `dgrams` climbing and `last` under a second. A board that is not
      listed is not being recorded.
- [ ] **Bind each board to its baby**, using the last four hex digits of the MAC:
      `subject 8850 SUBJ01`
- [ ] **Say what kind of session it is**: `tier T2` then `cond RESTING` (no subject = all three).
- [ ] **Our probe site, per baby**: `site SUBJ01 left foot`
- [ ] **The commercial monitor beside each baby** — the two that matter are the averaging and
      ITS probe site:
      `ref SUBJ01 model Masimo Radical-7`
      `ref SUBJ01 avg 8`
      `ref SUBJ01 site right hand`
- [ ] **Consent**: `consent obtained`
- [ ] **Clock anchor**: film the laptop clock with the phone for a few seconds, and while
      filming type `anchor`. This is what ties the video to the recording without trusting that
      two devices agree.

`help` lists every command. Everything typed here also lands in `events.csv` and inside each
`.pnraw`, so the session is self-describing even if `session.json` is lost.

---

## 3. During the session

- [ ] **Read the commercial monitor and write it down often**: `spo2 SUBJ01 96 142`
      (SpO2 and, if shown, pulse rate). Do not correct for delay; the instant of the keystroke
      is what is recorded. Aim for a reading per baby every few minutes, and always around
      anything interesting.
- [ ] **Mark what happens to the baby**: `mark handling` , `note probe repositioned on SUBJ02`.
      A desaturation, a feed, a nappy change, an alarm on the monitor — all of it is worth a
      line, and none of it can be reconstructed afterwards.
- [ ] **Glance at `status` now and then.** Watch for `SILENT`, and for `dgrams` not climbing.
- [ ] The tool writes a new part on every **10-minute wall-clock boundary** (`…_0002.pnraw` at
      10:20, `…_0003` at 10:30). That is normal, and it is how a photo taken at 10:37 is later
      found by filename.

---

## 4. Closing

- [ ] Type `quit` (or Ctrl+C). The tool writes `SESSION_END`, closes every file and prints the
      session directory and a per-board summary.
- [ ] Check the summary: `dgrams` similar on the three boards, `write errors` zero.
- [ ] **Copy the whole session directory** to a second disk before leaving. It is under
      `captures/sessions/<YYYYMMDD>_<HHMM>_<SITE>/`.
- [ ] Copy the phone's photos and videos to the same place.
- [ ] Nothing of this is committed to the repository (`captures/` is git-ignored, and session
      directories are never committed — not even `session.json`).

---

## 5. When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| A board is missing from `status` | It is not reaching the laptop: power, WiFi, or a new DHCP lease that has not sent a `$CFG` yet | Wait a few seconds; then check the board's power and the hotspot |
| `SILENT` beside a board | No datagram for 5 s | Usually the board rebooted or lost WiFi. It is recorded as a note and recording continues; when it comes back, **even on a new IP**, it continues in the same file |
| `dgrams` climbing but the baby is not connected | Normal: the board streams with no probe | Nothing |
| `write errors` above zero in `status` | A write failed on one board's stream | The other boards are unaffected. Note it and tell the team; the session is still usable |
| The recorder stops by itself | Disk below the floor (`SESSION_END reason=disk`) | Free space, start a new session; the closed one is intact |
| `no hub answering` | The hub did not start | Close other tools that may hold port 5005 and restart the recorder |
| A crash of any kind | | The `.pnraw` files are append-only and fsynced every 10 s: at most the last 10 s of that part is lost, and everything before it is readable |

**The recorder never writes to a board.** It cannot change a setting or reboot anything, by
construction. Configuration is done from the lab before the session.

---

## 6. Afterwards

Off-site, the converter turns each `.pnraw` into the capture CSV, plus `ref_videonest.csv` and
`ref_manual.csv`, and reports how the phone's OCR compared with what the operator typed. That
tool is being written; until then, keep the session directories exactly as they are.
