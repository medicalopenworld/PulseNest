"""Evidence for spec §4.8: run the OLD (pre-v1.44) and NEW (per-board) gap detectors over the SAME
recorded arrival sequence from the two live boards, so the difference is the algorithm alone.

OLD: one shared `_last_cnt` for every source; a delta outside 0 < gap <= 5000 is silently dropped.
NEW: one `last_cnt` per board, same plausibility window, gap split by `gap % UDP_BATCH_SIZE`.

Then inject a synthetic loss of one whole datagram (5 consecutive frames of one board) and re-run
both, to test the prediction that with two boards the OLD detector goes BLIND to datagram loss
(it manifests at a run boundary, where OLD compares against the other board's counter).

Result on 2026-09-09 with 17.A + 16.A streaming $M4 (counters 2.14 M samples apart): 19.4 % of the
deltas cross a board boundary; OLD rejects all of them as implausible and therefore reports 0 gaps
even when a whole datagram is removed, while NEW reports the 5 lost samples. Replayed per board,
both agree. Whether OLD cries wolf or goes blind depends on the counter difference versus its
0 < gap <= 5000 window: boards booted within ~10 s of each other produce false gaps instead.

Usage:  python tools/udp_gap_algo_compare.py [seconds]
Run with pulsenest_lab.py closed (it binds the data port).
"""
import socket
import sys
import time

DATA_PORT = 5005
BATCH = 5
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
PREFIXES = (b"M1", b"M2", b"M3", b"M4")


def record(dur):
    """[(ip, cnt), ...] in arrival order, plus datagram start indices."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    try:
        s.bind(("", DATA_PORT))
    except OSError as e:
        print(f"ERROR: cannot bind :{DATA_PORT} ({e}) — close pulsenest_lab.py")
        sys.exit(2)
    s.settimeout(0.5)
    seq, starts = [], []
    t_end = time.time() + dur
    while time.time() < t_end:
        try:
            data, (ip, _) = s.recvfrom(4096)
        except socket.timeout:
            continue
        starts.append(len(seq))
        for line in data.split(b"\n"):
            line = line.rstrip(b"\r")
            if line[:1] == b"$" and line[1:3] in PREFIXES and line[3:4] == b",":
                try:
                    seq.append((ip, int(line[4:].split(b",", 1)[0])))
                except (ValueError, IndexError):
                    pass
    s.close()
    return seq, starts


def old_algo(seq):
    """Pre-v1.44: one shared counter. Returns (samples_counted, events, rejected_deltas)."""
    last = None
    total = events = rejected = 0
    for _ip, cnt in seq:
        if last is not None:
            gap = cnt - last - 1
            if 0 < gap <= 5000:
                total += gap
                events += 1
            elif gap != 0:
                rejected += 1
        last = cnt
    return total, events, rejected


def new_algo(seq):
    """v1.44: per-board counter, gap classified by the batching invariant."""
    last = {}
    air = queue_drop = events = rejected = 0
    for ip, cnt in seq:
        if ip in last:
            gap = cnt - last[ip] - 1
            if 0 < gap <= 5000:
                events += 1
                if gap % BATCH == 0:
                    air += gap
                else:
                    queue_drop += gap
            elif gap != 0:
                rejected += 1
        last[ip] = cnt
    return air, queue_drop, events, rejected


def report(tag, seq):
    o_total, o_events, o_rej = old_algo(seq)
    n_air, n_q, n_events, n_rej = new_algo(seq)
    print(f"  {tag}")
    print(f"    OLD (shared counter): {o_total} samples in {o_events} events; "
          f"{o_rej} deltas rejected as implausible")
    print(f"    NEW (per board)     : air {n_air} + queue {n_q} samples in {n_events} events; "
          f"{n_rej} rejected")


seq, starts = record(DUR)
by_ip = {}
for ip, cnt in seq:
    r = by_ip.setdefault(ip, [cnt, cnt, 0])
    r[0] = min(r[0], cnt)
    r[1] = max(r[1], cnt)
    r[2] += 1
print(f"Recorded {len(seq)} data frames from {len(by_ip)} board(s) in {DUR:.0f} s, "
      f"{len(starts)} datagrams")
for ip, (lo, hi, n) in sorted(by_ip.items()):
    print(f"  {ip:16s} frames {n:6d}  counter {lo}..{hi}  uptime at start ~{lo / 500:.0f} s")
if len(by_ip) == 2:
    a, b = sorted(by_ip.values(), key=lambda r: r[0])
    print(f"  counter difference between boards: {b[0] - a[0]} samples "
          f"({(b[0] - a[0]) / 500:.0f} s) — the OLD detector's window is 5000 (10 s)")
# Interleaving: how often does a frame follow one from a *different* board?
switches = sum(1 for i in range(1, len(seq)) if seq[i][0] != seq[i - 1][0])
print(f"  board switches in the arrival sequence: {switches} of {len(seq) - 1} deltas "
      f"({100 * switches / max(len(seq) - 1, 1):.1f} %)")

print("\nAs recorded (the link as it is right now):")
report("both boards", seq)
for ip in sorted(by_ip):
    report(f"only {ip} (single-source, what the old reader saw with one board)",
           [t for t in seq if t[0] == ip])

# ── Injected loss: drop one whole datagram (5 consecutive frames of one board) ──
victim = max(by_ip, key=lambda ip: by_ip[ip][2])
cut = None
for i in starts:
    if i + BATCH <= len(seq) and all(t[0] == victim for t in seq[i:i + BATCH]) and i > len(seq) // 3:
        cut = i
        break
print(f"\nInjected loss of one whole datagram from {victim} "
      f"(5 frames at index {cut}) — a datagram lost on the air:")
if cut is not None:
    holed = seq[:cut] + seq[cut + BATCH:]
    report("both boards, one datagram missing", holed)
    report(f"only {victim}, same datagram missing",
           [t for t in holed if t[0] == victim])
