"""Report the firmware of every PulseNest board streaming to this PC — no GUI needed.

1. Bind the UDP data port (:5005) and listen a few seconds to learn the source IPs and their rates.
2. Send "$CFG?" to each source (and to any IP given on the command line) on the command port :5006.
3. Parse every $CFG reply: board, MAC, PulseNest version, library version, build hashes.

The $CFG frame is the only reliable source of a board's version: the OTA page shows none and the
serial banner is only visible over USB. Identify boards by MAC — hotspot IPs change between sessions.

Usage:  python tools/udp_fw_versions.py [IP ...] [--discover S] [--reply S]
Must be run with pulsenest_lab.py closed (it owns :5005).
"""
import argparse
import re
import socket
import sys
import time

DATA_PORT = 5005   # UDP_TARGET_PORT in include/wifi_config.h
CMD_PORT = 5006    # UDP_CMD_PORT in include/wifi_config.h
ID_KEYS = ("board", "mac", "fw", "lib", "build", "libsha")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ips", nargs="*", help="extra IPs to query even if they are not streaming")
    ap.add_argument("--discover", type=float, default=3.0, metavar="S", help="listen time before querying")
    ap.add_argument("--reply", type=float, default=4.0, metavar="S", help="wait time for $CFG replies")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", DATA_PORT))
    except OSError as exc:
        print(f"ERROR: cannot bind :{DATA_PORT} ({exc}) — is pulsenest_lab.py running?")
        return 1
    sock.settimeout(0.2)

    sources = {}  # ip -> [datagrams, bytes]
    t_end = time.time() + args.discover
    while time.time() < t_end:
        try:
            data, (ip, _) = sock.recvfrom(4096)
        except socket.timeout:
            continue
        s = sources.setdefault(ip, [0, 0])
        s[0] += 1
        s[1] += len(data)
    print(f"Discovery ({args.discover:.0f} s):")
    for ip, (n, b) in sorted(sources.items()):
        print(f"  {ip:16s} {n / args.discover:6.1f} datagrams/s  {b * 8 / args.discover / 1e6:5.2f} Mbit/s")
    if not sources:
        print(f"  (no UDP traffic on :{DATA_PORT})")

    targets = sorted(set(sources) | set(args.ips))
    for ip in targets:
        sock.sendto(b"$CFG?\n", (ip, CMD_PORT))
    print(f"Sent $CFG? to: {', '.join(targets) if targets else '(none)'}")

    cfg_frames = {}  # ip -> line
    t_end = time.time() + args.reply
    while time.time() < t_end:
        try:
            data, (ip, _) = sock.recvfrom(4096)
        except socket.timeout:
            continue
        for line in data.decode("ascii", "replace").splitlines():
            if line.startswith("$CFG,"):
                cfg_frames[ip] = line
    sock.close()

    print("\nFirmware per board:")
    for ip in targets:
        line = cfg_frames.get(ip)
        if not line:
            print(f"  {ip:16s} no $CFG reply")
            continue
        fields = {}
        for k in ID_KEYS:
            m = re.search(rf"(?:^|,){k}=([^,*]*)", line)
            fields[k] = m.group(1) if m else "?"
        print(f"  {ip:16s} " + "  ".join(f"{k}={fields[k]}" for k in ID_KEYS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
