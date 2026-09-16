"""Report the firmware of every PulseNest board streaming to this PC — no GUI, nothing sent to the air.

A read-only subscriber of the hub (spec §4.11). On joining, the hub replays the last $CFG line of
every live board, so the identities arrive at once; the tool then listens for `--discover` seconds
to measure each board's datagram rate and pick up any fresher $CFG. It never sends a command: it
cannot, it is not the controller. If a board shows no $CFG, the hub's single "$CFG?" to it was
lost — ask again from the lab (HW CONFIG → Read from chip) or restart the board.

The $CFG frame is the only reliable source of a board's version: the OTA page shows none and the
serial banner is only visible over USB. Identify boards by MAC — hotspot IPs change between sessions.

Usage:  python tools/udp_fw_versions.py [--discover S] [--hub IP[:PORT]]
Runs alongside pulsenest_lab.py (it used to need the lab closed: both wanted the data port). With
no hub running on this PC it starts one.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import UDP_DATA_PORT          # noqa: E402  (the one place the ports live)
from pulsenest_hub_client import HubClient       # noqa: E402

ID_KEYS = ("board", "mac", "fw", "lib", "build", "libsha")


def parse_hub(text):
    host, _, port = text.partition(":")
    return (host or "127.0.0.1", int(port) if port else UDP_DATA_PORT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--discover", type=float, default=3.0, metavar="S", help="listen time (default %(default)s)")
    ap.add_argument("--hub", default="127.0.0.1", metavar="IP[:PORT]",
                    help="hub to subscribe to (default: this PC; a remote hub is read-only anyway)")
    args = ap.parse_args()

    hub = parse_hub(args.hub)
    client = HubClient("udp_fw_versions", hub=hub, control=False, log=print)
    if not client.connect():
        print(f"ERROR: no hub answering on {hub[0]}:{hub[1]}"
              + (" and none could be started" if hub[0].startswith("127.") else ""))
        return 1

    sources = {}     # ip -> [datagrams, bytes]
    cfg_lines = {}   # ip -> last $CFG line
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.discover:
        item = client.recv(0.2)
        if item is None:
            continue
        ip, data = item
        for line in data.decode("ascii", "replace").splitlines():
            if line.startswith("$CFG,"):
                cfg_lines[ip] = line
        if data[:2] == b"$M":                       # data frames only count towards the rate
            s = sources.setdefault(ip, [0, 0])
            s[0] += 1
            s[1] += len(data)
    client.close()

    print(f"Discovery ({args.discover:.0f} s) via hub {hub[0]}:{hub[1]}:")
    for ip, (n, b) in sorted(sources.items()):
        print(f"  {ip:16s} {n / args.discover:6.1f} datagrams/s  {b * 8 / args.discover / 1e6:5.2f} Mbit/s")
    if not sources:
        print("  (no board streaming)")

    print("\nFirmware per board:")
    for ip in sorted(set(sources) | set(cfg_lines)):
        line = cfg_lines.get(ip)
        if not line:
            print(f"  {ip:16s} no $CFG in the hub's cache — ask from the lab (HW CONFIG → Read from chip)")
            continue
        fields = {}
        for k in ID_KEYS:
            m = re.search(rf"(?:^|,){k}=([^,*]*)", line)
            fields[k] = m.group(1) if m else "?"
        silent = "" if ip in sources else "   (identity cached, board not streaming now)"
        print(f"  {ip:16s} " + "  ".join(f"{k}={fields[k]}" for k in ID_KEYS) + silent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
