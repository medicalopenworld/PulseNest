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
With no IP, every board currently streaming is measured.

Goes through the hub (spec §4.11) as its CONTROLLER — it has to, it sends $CFG?. The lab holds the
control while open, so run this with the lab closed; the hub itself may stay up (one is started if
none answers). The extra hop is two loopback datagrams, well under a millisecond against the tens
to hundreds being measured.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT, banner, script_name  # noqa: E402  (the one place the ports live)
from pulsenest_hub_client import HubClient       # noqa: E402


def discover(client, seconds):
    """Board IPs currently streaming through the hub, in first-seen order."""
    seen = []
    t_end = time.time() + seconds
    while time.time() < t_end:
        item = client.recv(0.2)
        if item is None:
            continue
        ip, data = item
        if data[:2] == b"$M" and ip not in seen:
            seen.append(ip)
    return seen


def probe(client, ip, timeout_s):
    """Round-trip time of one `$CFG?` in ms, or None on timeout."""
    # Drop whatever is already queued so an earlier reply cannot be mistaken for this one.
    while client.recv(0.0) is not None:
        pass
    t0 = time.perf_counter()
    if not client.send_to_board(ip, b"$CFG?\n"):
        return None
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        item = client.recv(min(0.05, max(0.0, deadline - time.perf_counter())))
        if item is None:
            continue
        src, data = item
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

    print(banner(__file__, "round-trip latency of a command, per board"))
    client = HubClient(script_name(__file__), control=True, log=print)
    if not client.connect():
        print(f"ERROR: no hub answering on 127.0.0.1:{UDP_DATA_PORT} and none could be started")
        return 1
    if not client.controller:
        print("ERROR: this tool sends $CFG? and must be the hub's controller - control is held by "
              f"{client.control_refused_by or 'another program'} (pulsenest_lab.py keeps it while open)")
        client.close()
        return 1

    targets = args.ips or discover(client, 3.0)
    if not targets:
        print("no board streaming through the hub and no IP given")
        client.close()
        return 1
    tag = f" [{args.label}]" if args.label else ""
    print(f"$CFG? round-trip latency{tag} - {args.n} probes per board, {args.gap:.2f} s apart\n")

    for ip in targets:
        rtts, timeouts = [], 0
        for i in range(args.n):
            r = probe(client, ip, args.timeout)
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
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
