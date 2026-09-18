"""Offline checks for tools/fleet_monitor.py -- the table, not the network.

Feeds synthetic $CFG and $M4 datagrams straight into BoardView/render(), so it needs neither a
hub nor a board and runs in a fraction of a second:

    python tools/fleet_monitor_test.py

Covers what the columns promise (2026-09-17): the shortened IP/MAC/probe labels and the fallback
to full addresses across subnets, the column order SpO2 HR1 HR2 HR3 RF1 TIA1 RF2 TIA2, the fields
each cell reads, row/header alignment, and the SQI colouring -- green above 0.9 over the MEAN
since the last redraw (not the last sample), no colour before any SQI arrives, and a lost row
painted whole with no inner colour that would cut its background.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fleet_monitor as F  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  offline checks of the fleet_monitor table")

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def strip(t):
    return re.sub(r"\x1b\[[0-9;]*m", "", t)


class _C:
    connected = True
    last_status = None


def frame(spo2, spo2_sqi, hr1, hr1_sqi, hr2, hr2_sqi, hr3, hr3_sqi):
    """$M4 with the fields this tool reads at their spec positions."""
    p = ["M4", "100", "0"] + ["0"] * 33
    p[10], p[11] = spo2, spo2_sqi
    p[14], p[15] = hr1, hr1_sqi
    p[16], p[17] = hr2, hr2_sqi
    p[18], p[19] = hr3, hr3_sqi
    p[20], p[21], p[22] = "1", "0", "2"          # RSQI, diag, probe=APPLIED
    p[23], p[24] = "0.873", "1.201"              # V_TIA_LED1/2
    p[34], p[35] = "50K", "100K"
    return ("$" + ",".join(p) + "*00\r\n").encode()


cfg = (b"$CFG,sr=500,board=incunest_V17,mac=10:20:BA:14:75:60,fw=0.13,lib=0.93,build=cccf6ee,"
       b"elfsha=752b9e01df703576,idfver=v6.0.1*00\r\n")
now = time.monotonic()
boards = {}
b = boards["192.168.137.131"] = F.BoardView("192.168.137.131")
b.feed(cfg, now)
b.feed(frame("97.5", "0.95", "61.2", "0.99", "60.8", "0.95", "0.0", "0.10"), now)

txt = F.render(boards, _C(), ("127.0.0.1", 5005), now, colors=True)
plain = strip(txt).split("\n")
hdr = next(l for l in plain if l.startswith("IP"))
row = next(l for l in plain if "incunest_V17" in l)

# P1 / P2
title = plain[0]
check("P1 common prefix shown for the fleet, not inside the column",
      "boards 192.168.*" in title and hdr.startswith("IP      "), title[-40:] + " | " + hdr[:12])
check("P1 cell shows the last two octets", row.startswith("137.131 "), row[:12])
check("P2 MAC shows the last three octets", " 14:75:60 " in row, row[:30])
# P3
check("P3 probe label shortened, never mid-word", " APPLIED " in row and F.PROBE_W == 12,
      f"W={F.PROBE_W}")
check("P3 no mid-word truncation in the table", F.PROBE_STATES["3"] == "AMB_SAT"
      and F.PROBE_STATES["4"] == "ONLY_LED_SAT")
# P4 / P5
check("P4+P5 column order: SpO2 HR1 HR2 HR3 RF1 TIA1 RF2 TIA2",
      re.search(r"SpO2\s+HR1\s+HR2\s+HR3\s+RF1\s+TIA1\s+RF2\s+TIA2\s+ERR\s+last", hdr) is not None, hdr)
check("P4 each resistor is followed by the voltage it produced",
      re.search(r"50K\s+0\.87\s+100K\s+1\.20", row) is not None, row)
check("P5 HR2 and HR3 read from fields 16 and 18", re.search(r"60\.8\s+0\.0\s", row) is not None, row)
# widths
check("still narrower than the 163 it started from, now with elfsha too",
      len(hdr) <= 160, f"{len(hdr)} chars")
check("elfsha shown, truncated to 8 hex - enough to tell two images apart",
      re.search(r"build\s+elfsha\s", hdr) is not None and " 752b9e01 " in row,
      hdr[:60] + " | " + row[:70])
# Deliberate: idfver is parsed into the identity but kept out of the table -- it is the same
# on every board until a toolchain change, and the width is the scarce resource here.
check("idfver parsed but deliberately NOT a column",
      "idfver" in F.ID_KEYS and "v6.0.1" not in row, row[:80])
check("every row matches the header width", all(len(strip(l)) == len(hdr) for l in plain
                                                if "incunest_V17" in l), f"{len(row)} vs {len(hdr)}")

# P6: colour by the MEAN of the SQI, green above 0.9
b2 = boards["192.168.137.131"]
b2.feed(frame("97.5", "0.95", "61.2", "0.99", "60.8", "0.95", "0.0", "0.10"), now)
col = F.render(boards, _C(), ("127.0.0.1", 5005), now, colors=True)
green_cells = re.findall(r"\x1b\[32m\s*([\d.]+)\s*\x1b\[0m", col)
red_cells = re.findall(r"\x1b\[31m\s*([\d.]+)\s*\x1b\[0m", col)
check("P6 SpO2/HR1/HR2 green (SQI 0.95/0.99/0.95 > 0.9)",
      {"97.5", "61.2", "60.8"} <= set(green_cells), str(green_cells))
check("P6 HR3 red (SQI 0.10)", "0.0" in red_cells, str(red_cells))

# the mean, not the last sample: two frames, one good one bad -> 0.5 -> red
b3 = F.BoardView("192.168.137.9")
boards2 = {"192.168.137.9": b3}
b3.feed(cfg, now)
b3.feed(frame("97.0", "1.00", "61.0", "1.00", "61.0", "1.00", "61.0", "1.00"), now)
b3.feed(frame("97.0", "0.00", "61.0", "0.00", "61.0", "1.00", "61.0", "1.00"), now)
txt2 = F.render(boards2, _C(), ("127.0.0.1", 5005), now, colors=True)
g2 = re.findall(r"\x1b\[32m\s*([\d.]+)\s*\x1b\[0m", txt2)
r2 = re.findall(r"\x1b\[31m\s*([\d.]+)\s*\x1b\[0m", txt2)
check("P6 colour follows the MEAN since the last redraw (1.00 then 0.00 -> red)",
      "97.0" in r2 and "97.0" not in g2, f"green={g2} red={r2}")
check("P6 accumulators reset after each redraw", b3.sqi_n["hr1"] == 0, str(b3.sqi_n))

# no colour before any SQI has arrived, and none at all on a lost row
b4 = F.BoardView("192.168.137.50")
plain4 = strip(F.render({"x": b4}, _C(), ("127.0.0.1", 5005), now, colors=True))
check("no colour while nothing has arrived yet", "\x1b[32m" not in plain4)
b3.last_seen = now - 9
lost_txt = F.render(boards2, _C(), ("127.0.0.1", 5005), now, colors=True)
lost_row = [l for l in lost_txt.split("\n") if "incunest_V17" in l][0]
check("a lost row is painted whole, with no inner colour",
      lost_row.startswith(F.RED_BG) and "\x1b[32m" not in lost_row and lost_row.count("\x1b[0m") == 1,
      lost_row[:60])

# two subnets -> full addresses
mixed = {"192.168.137.9": F.BoardView("192.168.137.9"), "10.0.0.5": F.BoardView("10.0.0.5")}
hdr_m = [l for l in strip(F.render(mixed, _C(), ("127.0.0.1", 5005), now)).split("\n") if l.startswith("IP")][0]
mixed_title = strip(F.render(mixed, _C(), ("127.0.0.1", 5005), now)).splitlines()[0]
check("P1 falls back to full addresses across subnets",
      "boards " not in mixed_title and hdr_m.startswith("IP" + " " * 13), hdr_m[:20])

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
sys.exit(0 if all(ok) else 1)
