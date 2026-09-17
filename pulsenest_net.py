"""What every host-side PulseNest program shares: the UDP ports, and how it names itself.

Two ports, one per END of the link. They are not two ports on one machine:

    UDP_DATA_PORT  5005   The port the HOST listens on. Every board sends everything here:
                          the $M* data frames, the $CFG/$TCFG/$LCFG/$DIAG replies, $ERR, and
                          the '#' console lines. The hub (when running) owns this socket.
    UDP_CMD_PORT   5006   The port each BOARD listens on. The host sends commands here
                          ($SET, $MODE, $CFG?, $LCFG?, ...). The firmware discards the sender's
                          address and answers to the IP compiled in wifi_config.h.

The firmware side is `include/wifi_config.h` (UDP_TARGET_PORT / UDP_CMD_PORT). That file carries
the WiFi credentials and is gitignored, so it cannot be the repository's source of truth; this
module is. Running it checks that the local wifi_config.h agrees:

    python pulsenest_net.py

Every host-side program imports from here -- pulsenest_lab.py, tools/tia_linearity_sweep.py and
the rest of tools/. Until 2026-09-16 each of them carried its own copy of both numbers.

It also holds script_name()/banner(), so that a running program always says which file it is:
the lab puts it in every window title, the console tools print it as their first line. With a
dozen scripts around, that is the one thing the screen could not tell you.
"""
import os
import re
import sys

UDP_DATA_PORT = 5005
UDP_CMD_PORT = 5006


def script_name(path):
    """-> the file name a running program should show, e.g. "fleet_monitor.py". Pass __file__."""
    return os.path.basename(os.path.abspath(path))


def banner(path, what=""):
    """First line of output of a console tool: the file that is running, then what it does.

    ASCII only, on purpose: these lines go to a Windows console that may be cp1252, where a box
    character or a dash would raise UnicodeEncodeError on the very first print.
    """
    name = script_name(path)
    return f"== {name} ==" + (f"  {what}" if what else "")


# Firmware mirror. Maps our name to the #define in include/wifi_config.h.
_FIRMWARE_MIRROR = {
    "UDP_DATA_PORT": ("UDP_TARGET_PORT", UDP_DATA_PORT),
    "UDP_CMD_PORT":  ("UDP_CMD_PORT",    UDP_CMD_PORT),
}


def check_firmware_mirror(path=None):
    """-> list of mismatch strings, empty when include/wifi_config.h agrees with this module."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "include", "wifi_config.h")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    problems = []
    for ours, (theirs, value) in _FIRMWARE_MIRROR.items():
        m = re.search(r"^\s*#define\s+%s\s+(\d+)" % re.escape(theirs), text, re.M)
        if m is None:
            problems.append(f"{theirs} not found in {path}")
        elif int(m.group(1)) != value:
            problems.append(f"{theirs} = {m.group(1)} in firmware, {ours} = {value} here")
    return problems


if __name__ == "__main__":
    issues = check_firmware_mirror()
    if issues:
        print("MISMATCH between pulsenest_net.py and include/wifi_config.h:")
        for line in issues:
            print("  " + line)
        sys.exit(1)
    print(banner(__file__, "the host-side source of truth for the UDP ports"))
    print(f"OK: wifi_config.h agrees (data :{UDP_DATA_PORT}, commands :{UDP_CMD_PORT})")
