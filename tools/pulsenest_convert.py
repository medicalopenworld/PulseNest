"""pulsenest_convert.py -- rebuild a session's CSVs from its .pnraw record, and prove it.

    python tools/pulsenest_convert.py captures/sessions/20260922_1210_BENCH            # verify
    python tools/pulsenest_convert.py <session dir> --csv v04                          # v0.4 files
    python tools/pulsenest_convert.py <session dir> --csv v04 --out /some/where

Recorder spec section 10, capture_csv_format_spec.md Phase 3. The .pnraw is the record: every
datagram verbatim with its arrival stamps, plus the session's events (@E). This tool feeds those
records, in order and with their own stamps, through the SAME `Recorder` that wrote them live --
same class, same writers, same naming, same splitting on the same wall-clock boundaries -- so
its output is not "similar to" the live files, it is the live files. Which is the check it runs
by default: with `--csv on` it rebuilds today's format and compares every board CSV byte for
byte with the one written live (`identical` / `DIFFERS` per file, exit code = files that
differ). With `--csv v04` it produces the v0.4 container for a session that was recorded live in
today's format -- how every campaign file becomes v0.4 without the live path ever moving.

What is replayed and what is not:
  * @D datagrams: all of them, through `Recorder.feed()` with their recorded stamps.
  * @E events: the operator's (REF_SPO2, NOTE, META, ...) are re-issued through `Recorder.event()`
    with their parsed fields, and the STATE they carried is re-applied first (a subject bound to a
    board, a condition, a probe model, a reference-monitor field, the phone id) -- live, a console
    command changed state and then logged the event; here the event is what is left of the
    command, so it is read back into state. SESSION_START/SESSION_END are the Recorder's own and
    are not replayed (the end's `reason=` is kept so the closing event says the same).
  * @M notes: the Recorder's own observations (identified, gap, restarted); regenerated, not read.
  * `--raw`: always off here -- the record is the input, never rewritten.
Output goes under `<session>/derived/<session_id>/` unless `--out` says otherwise; the live
files are never touched.
"""
import argparse
import csv
import datetime as _dt
import glob
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(_HERE), _HERE]
from pulsenest_recorder import Recorder, read_pnraw, normalise_subject   # noqa: E402

_SESSION_RE = re.compile(r"^(\d{8}_\d{4})_([A-Z0-9]+)(?:_([A-Za-z0-9]+))?$")
_EVENT_TEXT_RE = re.compile(r"^subject=(\S*) board=(\S*)(?: value=(\S*))?(?: value2=(\S*))?"
                            r" source=(\S*)(?: note=(.*))?$")


def load_session(session_dir):
    """Every record of every .pnraw part of a session, in arrival order, events de-duplicated
    (an @E is copied into every open stream; one copy is enough). Returns (session_id,
    started_epoch_us, records) with records as ("D", t_mono, t_epoch, ip, data) and
    ("E", t_mono, t_epoch, eid, kind, text)."""
    parts = sorted(glob.glob(os.path.join(session_dir, "raw", "*.pnraw")))
    if not parts:
        raise SystemExit(f"no raw/*.pnraw under {session_dir}")
    session_id = None
    recs, seen_events = [], set()
    for p in parts:
        for r in read_pnraw(p):
            if r[0] == "H":
                session_id = session_id or r[1].get("session")
            elif r[0] == "D":
                _t, _seq, t_mono, t_epoch, ip, data = r
                recs.append(("D", t_mono, t_epoch, ip, data))
            elif r[0] == "E":
                _t, t_mono, t_epoch, eid, kind, text = r
                if eid in seen_events:
                    continue
                seen_events.add(eid)
                recs.append(("E", t_mono, t_epoch, eid, kind, text))
    # session_events.csv is the complete event log; the @E copies in the .pnraw are not -- an
    # event fired before a board's stream opened (the `--note`/`--probe` metadata applied at the
    # moment of binding) reaches no stream at all. When the log is there, it is the source.
    # Which events reached SOME stream: the ones that did not fired before any stream was open
    # -- the metadata applied at the moment of binding -- and the Recorder regenerates those
    # itself when handed the same launch values (see convert()).
    in_streams = set(seen_events)
    ev_path = os.path.join(session_dir, "session_events.csv")
    if os.path.exists(ev_path):
        recs = [r for r in recs if r[0] == "D"]
        with io.open(ev_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    t_mono, t_epoch, eid = int(row["t_mono_us"]), int(row["t_epoch_us"]), int(row["event_id"])
                except (KeyError, ValueError):
                    continue
                recs.append(("E", t_mono, t_epoch, eid, row["kind"], row))
    recs.sort(key=lambda r: (r[1], 0 if r[0] == "D" else 1))   # arrival order; an event after the datagram it shares a stamp with
    return session_id, recs, in_streams


def session_start_epoch_us(session_id, session_dir):
    """The instant the live Recorder was constructed, to the minute: its session id carries it,
    and the id must come out identical (it is a header key in every file)."""
    m = _SESSION_RE.match(session_id or "")
    if not m:
        raise SystemExit(f"session id {session_id!r} does not look like <YYYYMMDD_HHMM>_<SITE>[_<tag>]")
    stamp, site, tag = m.groups()
    t0 = _dt.datetime.strptime(stamp, "%Y%m%d_%H%M").astimezone()
    meta = {}
    sj = os.path.join(session_dir, "session.json")
    if os.path.exists(sj):
        try:
            meta = json.load(io.open(sj, encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    return int(t0.timestamp() * 1e6), site, tag, meta


class ReplayClock:
    """`Recorder(clock=...)` reads (t_mono_us, t_epoch_us) from here; the converter sets it to
    each record's own stamps before handing the record over, so every stamp the writers see is
    the one the live Recorder saw."""
    def __init__(self, t_mono_us, t_epoch_us):
        self.t = (t_mono_us, t_epoch_us)

    def __call__(self):
        return self.t


def _apply_state(rec, kind, subject, board, note):
    """Re-apply what the live console command did to the Recorder's state before it logged
    this event. Everything the board CSV depends on: subject binding, condition, probe model."""
    if kind != "META":
        return
    if note.startswith("subject=") and " board=" in note:
        # `subject <mac> SUBJnn` -> "subject=SUBJ01 board=board_1051DB508850"
        label = note.split(" board=", 1)[1].strip()
        for s in rec._owners():
            if s.label() == label:
                s.subject = normalise_subject(subject) or s.subject
    elif note.startswith("cond="):
        value = note[len("cond="):]
        for s in rec._owners():
            if s.kind == "board" and (subject == "*" or s.subject == subject):
                s.condition = value
    elif note.startswith("probe="):
        for s in rec._owners():
            if s.kind == "board" and s.subject == subject:
                s.probe_model = note[len("probe="):]
    elif note.startswith("reference_monitor."):
        field, _, value = note[len("reference_monitor."):].partition("=")
        for s in rec._owners():
            if s.kind == "board" and s.subject == subject:
                s.reference[field] = float(value) if field == "averaging_s" else value
    elif note.startswith("videonest="):
        v = note[len("videonest="):]
        rec.videonest_id = None if v == "none" else v


def convert(session_dir, out_root=None, csv_mode="on", split_min=None, log=None):
    """Rebuild the session under out_root. Returns the Recorder (closed) for inspection."""
    session_dir = os.path.abspath(session_dir)
    session_id, recs, in_streams = load_session(session_dir)
    t0_epoch, site, tag, meta = session_start_epoch_us(session_id, session_dir)
    started = meta.get("started") or {}
    if "t_mono_us" in started and "t_epoch_us" in started:
        t0_mono, t0_epoch = int(started["t_mono_us"]), int(started["t_epoch_us"])   # exact, not to the minute
    else:
        t0_mono = recs[0][1] if recs else 0
    out_root = out_root or os.path.join(session_dir, "derived")
    os.makedirs(out_root, exist_ok=True)
    clock = ReplayClock(t0_mono, t0_epoch)
    # The launch values (session.json `launch`, 2026-09-22): the Recorder applies them itself at
    # binding, regenerating the same events at the same moment. Older sessions: what the id says.
    launch = meta.get("launch") or {}
    subject = normalise_subject(launch.get("subject") or "") or (normalise_subject(tag) if tag else None)
    board = meta.get("board_filter") or (None if subject else (tag or None))
    ref = launch.get("ref") or {}
    kw = {}
    if split_min is not None:
        kw["split_s"] = split_min * 60
    rec = Recorder(out_root, site, operator=meta.get("operator", ""), raw_mode="off",
                   csv_mode=csv_mode, hub_text="replay", clock=clock, log=log,
                   board=board, subject=subject, videonest=launch.get("videonest"),
                   note=launch.get("note"), probe=launch.get("probe"),
                   ref_model=ref.get("model"), ref_avg=ref.get("avg"),
                   ref_probe_site=ref.get("site"), ref_note=ref.get("note"), **kw)
    regenerates = bool(launch)
    if rec.session_id != session_id:
        rec.log.warning("replayed session id %s differs from the record's %s", rec.session_id, session_id)
    stop_reason = "operator"
    for r in recs:
        clock.t = (r[1], r[2])
        if r[0] == "D":
            rec.feed(r[3], r[4], r[1], r[2])
        else:
            _t, _tm, _te, _eid, kind, payload = r
            if kind == "SESSION_START":
                continue
            if isinstance(payload, dict):                 # a session_events.csv row
                subject_, board_ = payload["subject"], payload["board_mac"]
                value, value2, source = payload["value"], payload["value2"], payload["source"]
                confidence, note = payload.get("confidence", ""), payload["note"]
            else:                                         # an @E line's text
                m = _EVENT_TEXT_RE.match(payload)
                subject_, board_, value, value2, source, note = (m.groups() if m
                                                                 else ("*", "*", None, None, "keyboard", payload))
                confidence = ""
            note = note or ""
            if kind == "SESSION_END":
                if note.startswith("reason="):
                    stop_reason = note[len("reason="):]
                continue
            if _eid not in in_streams:
                # Fired before any stream was open: the metadata applied at binding. With the
                # launch values known the Recorder has just regenerated it itself (same event,
                # same moment, before the CSV opened); without them, keep its state and nothing
                # else -- re-issuing it now would put a line into a CSV that was not open then.
                if not regenerates:
                    _apply_state(rec, kind, subject_, board_, note)
                continue
            _apply_state(rec, kind, subject_, board_, note)
            rec.event(kind, subject=subject_, board_mac=board_, value=value or "",
                      value2=value2 or "", source=source or "keyboard", confidence=confidence or "",
                      note=note)
    rec.stop_reason = stop_reason
    rec.close()
    return rec


def verify(session_dir, rec):
    """Compare every live board CSV with its rebuilt twin, byte for byte. Returns
    [(name, 'identical' | 'DIFFERS' | 'missing')]."""
    live = sorted(f for f in glob.glob(os.path.join(session_dir, "*.csv"))
                  if os.path.basename(f) not in ("reference_spo2.csv", "session_events.csv"))
    out = []
    for f in live:
        twin = os.path.join(rec.dir, os.path.basename(f))
        if not os.path.exists(twin):
            out.append((os.path.basename(f), "missing"))
            continue
        a, b = io.open(f, "rb").read(), io.open(twin, "rb").read()
        out.append((os.path.basename(f), "identical" if a == b else "DIFFERS"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("session", help="a session directory (with raw/*.pnraw)")
    ap.add_argument("--csv", default="on", choices=("on", "v04"),
                    help="on = today's format, compared byte for byte with the live files; v04 = the v0.4 container")
    ap.add_argument("--out", default="", metavar="DIR", help="output root (default <session>/derived)")
    ap.add_argument("--split-min", type=float, default=None, help="part length; default = the recorder's")
    args = ap.parse_args(argv)
    rec = convert(args.session, args.out or None, args.csv, args.split_min)
    print(f"rebuilt -> {rec.dir}")
    if args.csv == "on":
        results = verify(args.session, rec)
        for name, verdict in results:
            print(f"  {verdict:9s} {name}")
        bad = sum(1 for _n, v in results if v != "identical")
        print(f"{len(results) - bad}/{len(results)} live CSVs reproduced byte for byte")
        return bad
    return 0


if __name__ == "__main__":
    sys.exit(main())
