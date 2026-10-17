# Breath-hold test — one-page checklist

An adult volunteer trained in breath-holding, three PulseNest boards and four home fingertip
oximeters, at a bench site. Goal: the first pairs below 85 % SpO2, the same Medle probe
on an adult finger instead of a neonatal foot (does the R curve depend on the site?), and the delay
of each device on a desaturation whose start is known. Not a clinical study and not an accuracy
claim: the reference is consumer oximeters (ISO 80601-2-61 Annex JJ: a non-traceable reference).
Session files: `docs/session_configs/subj12_{a_8850,b_87A4,c_825C}.toml`.

## Safety — not negotiable

- [ ] **An observer present the whole time**, who knows what a blackout looks like and what to do.
- [ ] **Seated or lying down.** Never standing.
- [ ] **No hyperventilation** before a hold: it delays the urge to breathe, not the hypoxia.
- [ ] **Submaximal holds.** A nadir of 80–85 % is plenty for us. Stop the series at any symptom.
- [ ] **3–5 min of normal breathing between holds.**
- [ ] Remember the lowest finger SpO2 comes **15–30 s after** the first breath (circulation time).

## Before (the day before or one hour before)

- [ ] Boards on fw 0.24 / lib 0.105 (`python tools/udp_fw_versions.py`: same `elfsha` on the three).
- [ ] Laptop on mains, sleep off, hotspot `in3wifi` up, disk ≥ 2 GB free.
- [ ] Phones charged, cloud photo sync **off**, VideoNest open on the phone that films one oximeter;
      the second phone films the other three oximeters as **continuous video** on a stand.
- [ ] Fill `age`, `weight_g`, `skin` and the `[ref]` lines in the three `.toml` (same values).
- [ ] Add `SUBJ12` to `captures/SUBJECT_CODES.txt`.

## Placement

- [ ] **Our three probes on the same hand** (left: index = A/8850 Medle -26, middle = B/87A4 U401-D,
      ring = C/825C Medle -25): same regional circulation (ISO JJ.1).
- [ ] Home oximeters: the one VideoNest reads on the left little finger if it fits; the other three
      on the right hand. Write which finger each is on in the `note` if it differs.
- [ ] Hands still, resting on a table at heart level, warm. Room light dim and steady.

## Starting

- [ ] `pythonw .\tools\pulsenest_session.py` → START on the three `subj12_*`.
- [ ] Each recorder window: subject bound, **no red warning** (in particular **no `HGAC OFF`**),
      ProbeState APPLIED on all three. Phone line live in the window that declared it.
- [ ] CLOCK ANCHOR: photograph the laptop clock with both phones.
- [ ] 2 min of quiet breathing as a baseline before the first hold.

## Each hold

Type the event notes in the window of **board A only**: each window is its own session, and the
other two are aligned to A by the wall clock in the analysis.

- [ ] NOTE `hold N start` at the last inhale.
- [ ] NOTE `first contraction` when the diaphragm starts.
- [ ] NOTE `hold N end` at the first breath.
- [ ] Wait until all oximeters are back above 95 % and 3–5 min have passed.
- [ ] Three to five holds in total, each a little longer than the last, never maximal.

## Closing

- [ ] 2 min of quiet breathing, then STOP in the three windows.
- [ ] Copy the phone video and the VideoNest folder (CSV + Snapshots) next to the sessions.
- [ ] Note anything unusual (a probe slipped, a sneeze, the observer talked to you) as a NOTE or here.
