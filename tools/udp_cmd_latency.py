"""Measure the round-trip latency of a command over UDP, per board.

Sends `$CFG?` to a board's command port and times how long its `$CFG` reply takes to arrive on the
data port. This measures the **downlink** path (PC -> ESP32), the one the data stream does not
exercise: the boards transmit continuously, so their radio is busy anyway, but a command has to be
*received*, and with WiFi modem sleep enabled (`WIFI_PS_MIN_MODEM`, the Arduino default in station
mode) a station only listens around the access point's DTIM beacons. The signature of modem sleep
is therefore a latency floor and quantisation at the beacon interval, typically 100 ms, instead of
the few milliseconds of a station that never sleeps.

Probes are deliberately spaced by an interval that is not a multiple of the beacon period, so the
samples land on different phases of the beacon cycle rather than always the same one.

Usage:  python tools/udp_cmd_latency.py [-n 40] [--gap 0.37] [IP ...]
With no IP, every board currently streaming to the data port is measured.
Run with pulsenest_lab.py closed (it binds the data port).
"""
import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, UDP_CMD_PORT  # noqa: E402  (the one place the ports live)


def discover(sock, seconds):
    """Source IPs currently streaming, in first-seen order."""
    seen = []
    t_end = time.time() + seconds
    while time.time() < t_end:
        try:
            _data, (ip, _port) = sock.recvfrom(4096)
        except socket.timeout:
            continue
        if ip not in seen:
            seen.append(ip)
    return seen


def probe(sock, ip, timeout_s):
    """Round-trip time of one `$CFG?` in ms, or None on timeout."""
    # Drop whatever is already buffered so an earlier reply cannot be mistaken for this one.
    sock.settimeout(0)
    try:
        while True:
            sock.recvfrom(65535)
    except (BlockingIOError, socket.timeout, OSError):
        pass
    sock.settimeout(0.05)
    t0 = time.perf_counter()
    sock.sendto(b"$CFG?\n", (ip, UDP_CMD_PORT))
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        try:
            data, (src, _port) = sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            continue
        if src != ip or b"$CFG," not in data:
            continue
        return (time.perf_counter() - t0) * 1e3
    return None


def stats(vals):
    v = sorted(vals)
    n = len(v)

    def pct(p):
        return v[min(n - 1, int(p * n))]

    return {"n": n, "min": v[0], "p50": pct(0.50), "p90": pct(0.90), "max": v[-1],
            "mean": sum(v) / n}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ips", nargs="*", help="boards to measure (default: all that are streaming)")
    ap.add_argument("-n", type=int, default=40, help="probes per board (default 40)")
    ap.add_argument("--gap", type=float, default=0.37,
                    help="seconds between probes; keep it off any multiple of 0.1 s (default 0.37)")
    ap.add_argument("--timeout", type=float, default=1.0, help="per-probe timeout in s")
    ap.add_argument("--label", default="", help="tag printed with the results (e.g. before/after)")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    try:
        sock.bind(("0.0.0.0", UDP_DATA_PORT))
    except OSError as exc:
        print(f"ERROR: cannot bind :{UDP_DATA_PORT} ({exc}) - close pulsenest_lab.py")
        return 1
    sock.settimeout(0.2)

    targets = args.ips or discover(sock, 3.0)
    if not targets:
        print(f"no board streaming to :{UDP_DATA_PORT} and no IP given")
        return 1
    tag = f" [{args.label}]" if args.label else ""
    print(f"$CFG? round-trip latency{tag} - {args.n} probes per board, {args.gap:.2f} s apart\n")

    for ip in targets:
        rtts, timeouts = [], 0
        for i in range(args.n):
            r = probe(sock, ip, args.timeout)
            if r is None:
                timeouts += 1
            else:
                rtts.append(r)
            if i < args.n - 1:
                time.sleep(args.gap)
        if not rtts:
            print(f"{ip:16s} no reply ({timeouts} timeouts)")
            continue
        s = stats(rtts)
        print(f"{ip:16s} n={s['n']:3d}  min {s['min']:7.1f}  p50 {s['p50']:7.1f}  "
              f"p90 {s['p90']:7.1f}  max {s['max']:7.1f}  mean {s['mean']:7.1f} ms"
              + (f"  timeouts {timeouts}" if timeouts else ""))
        # Histogram in 20 ms bins: modem sleep shows as mass away from zero, a station that
        # never sleeps piles up in the first bin.
        bins = {}
        for r in rtts:
            bins[int(r // 20) * 20] = bins.get(int(r // 20) * 20, 0) + 1
        for lo in sorted(bins):
            print(f"{'':16s}   {lo:4d}-{lo + 19:4d} ms | {'#' * bins[lo]} {bins[lo]}")
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
