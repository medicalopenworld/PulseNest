"""Read a session's event log (session_events.csv) for an analysis.

The recorder writes one row per event (pulsenest_recorder_spec.md section 8). This module
answers the questions an analysis asks of that file without each script re-parsing it:

    events(session_dir)                      every row, as dicts, in file order
    anomaly_intervals(session_dir, subject)  the stretches the operator flagged with the
                                             ABNORMAL CONDITION toggle (console `flag on|off`),
                                             as [(t_start_us, t_end_us)] on the host epoch clock
    covered_fraction(intervals, t0_us, t1_us)  how much of a window the intervals cover, 0..1

An ANOMALY_START opens a stretch for its subject (`*` = every subject) and the next ANOMALY_END
for that subject closes it. A START while one is open is ignored (the stretch began at the first
START); an END with nothing open is ignored; a stretch still open at the end of the file closes
at SESSION_END, or stays open (end = math.inf) when the session has no SESSION_END row (a crash:
nothing after the flag can be trusted). Each ignored row is reported through `warn`, which
defaults to logging.warning, so a script sees it once and the analysis never silently drops or
keeps a stretch the operator meant otherwise.
"""
import csv
import logging
import math
import os

EVENTS_FILE = "session_events.csv"


def events(session_dir):
    """Every row of the session's event log as a dict (strings), in file order.
    A session without the file (pre-2026-09-20 captures) yields an empty list."""
    path = os.path.join(session_dir, EVENTS_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def anomaly_intervals(session_dir, subject=None, warn=logging.warning):
    """[(t_start_us, t_end_us)] of the stretches flagged ABNORMAL CONDITION, host epoch clock,
    sorted by start. `subject=None` returns every stretch; `subject="SUBJ01"` returns the ones
    for that subject plus the session-wide ones (subject `*`). An unterminated stretch ends at
    SESSION_END, or at math.inf when there is none."""
    rows = events(session_dir)
    session_end = math.inf
    for r in rows:
        if r.get("kind") == "SESSION_END":
            session_end = int(r["t_epoch_us"])
    open_at = {}                          # subject -> t_start_us
    out = []
    name = os.path.basename(os.path.normpath(session_dir))
    for r in rows:
        kind = r.get("kind")
        if kind not in ("ANOMALY_START", "ANOMALY_END"):
            continue
        subj = r.get("subject") or "*"
        t = int(r["t_epoch_us"])
        if kind == "ANOMALY_START":
            if subj in open_at:
                warn(f"{name}: event {r.get('event_id')} ANOMALY_START for {subj} while one is "
                     f"open since {open_at[subj]}; kept the first")
                continue
            open_at[subj] = t
        else:
            if subj not in open_at:
                warn(f"{name}: event {r.get('event_id')} ANOMALY_END for {subj} with no open "
                     f"ANOMALY_START; ignored")
                continue
            out.append((subj, open_at.pop(subj), t))
    for subj, t0 in open_at.items():
        if session_end is math.inf:
            warn(f"{name}: ANOMALY_START for {subj} at {t0} never ended and the session has no "
                 f"SESSION_END; the stretch runs to the end of the data")
        out.append((subj, t0, session_end))
    if subject is not None:
        subject = subject.upper()
        out = [x for x in out if x[0] in (subject, "*")]
    return sorted((t0, t1) for _, t0, t1 in out)


def covered_fraction(intervals, t0_us, t1_us):
    """Fraction (0..1) of the window [t0_us, t1_us] that lies inside any of `intervals`
    (as returned by anomaly_intervals). Overlapping intervals (a session-wide `*` stretch and
    a subject's own) count once. An empty or inverted window yields 0.0."""
    length = t1_us - t0_us
    if length <= 0:
        return 0.0
    covered = 0.0
    cur_lo = cur_hi = None
    for a, b in sorted(intervals):
        lo = max(a, t0_us)
        hi = min(b, t1_us)
        if hi <= lo:
            continue
        if cur_hi is not None and lo <= cur_hi:
            cur_hi = max(cur_hi, hi)
        else:
            if cur_hi is not None:
                covered += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
    if cur_hi is not None:
        covered += cur_hi - cur_lo
    return min(1.0, covered / length)
