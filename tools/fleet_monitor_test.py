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

# The width guarantee. Reported by Alex 2026-09-18: at SpO2 100.00 -- six characters in a
# five-wide column -- every column to its right shifted by one, for as long as the reading held.
sat = F.BoardView("192.168.137.77")
sat.feed(cfg, now)
sat.feed(frame("100.00", "0.99", "100.00", "0.99", "250.00", "0.99", "61.0", "0.99"), now)
sat_txt = strip(F.render({"s": sat}, _C(), ("127.0.0.1", 5005), now, colors=True))
sat_hdr = next(l for l in sat_txt.split("\n") if l.startswith("IP"))
sat_row = next(l for l in sat_txt.split("\n") if "incunest_V17" in l)
check("SpO2 at 100 does not widen its column: the row still matches the header",
      len(sat_row) == len(sat_hdr), f"{len(sat_row)} vs {len(sat_hdr)}")
# SpO2 (5 wide) drops its second decimal; HR1, at the same 100.00 but 6 wide, keeps it. The
# first version of this check asserted "100.00" was absent from the whole row and failed on
# HR1 -- the assertion was wrong, not the formatter.
check("SpO2 drops the decimal it can afford while the wider HR columns keep theirs",
      re.search(r"\s100\.0\s+100\.00\s+250\.00\s", sat_row) is not None, sat_row[:130])
check("a 3-digit HR still fits its 6-wide column untouched", " 250.00 " in sat_row, sat_row[:120])
check("fit() never invents a number: what cannot fit shows as #####",
      F.fit("123456", 5) == "#####" and F.fit("1234.56", 5) == " 1234")

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

# ── the SOURCES block: a phone is shown, apart from the boards, never as one of them ────────
VN1_B8 = b"$VN1,355,96,0.98,1789927310955*26\r\n"     # build 8: seq,spo2,conf,ts (no pr)
now = time.monotonic()
a = F.AuxView("192.168.1.143", "videonest")
a.feed(VN1_B8, now)
check("AuxView reads what it shows from a build-8 frame",
      (a.seq, a.spo2, a.conf) == ("355", "96", "0.98"), f"{a.seq},{a.spo2},{a.conf}")
a.feed(b"$VN1,356,97\r\n", now)          # truncated: must not raise, must not invent
check("a truncated frame updates what it has and leaves the rest alone",
      (a.seq, a.spo2, a.conf) == ("356", "97", "0.98"), f"{a.seq},{a.spo2},{a.conf}")
a.feed(b"rubbish\r\n", now)
check("a line that is not $VN1 is ignored", a.seq == "356")

idd = F.AuxView("192.168.1.143", "videonest")
idd.feed(b"$VN1,901,95,0.97,1790000012000,VN02*00\r\n", now)
# the 2026-09-22 two-stamp frame, off the real phone: the id is still the last field
idd.feed(b"$VN1,1245,89,0.98,1790084454887,1790084455216,1,J6plusACM*02\r\n", now)
check("the two-stamp frame names the phone by its LAST field, not the emission stamp",
      idd.vn_id == "J6plusACM" and idd.seq == "1245" and idd.spo2 == "89", str(idd.vn_id))
idd.feed(b"$VN1,901,95,0.97,1790000012000,VN02*00\r\n", now)
check("AuxView reads the phone's trailing id, and the fields before it are unmoved",
      (idd.vn_id, idd.seq, idd.spo2, idd.conf) == ("VN02", "901", "95", "0.97"),
      f"{idd.vn_id},{idd.seq},{idd.spo2},{idd.conf}")
idd_txt = strip(F.render({}, _C(), ("127.0.0.1", 5005), now, aux={idd.ip: idd}))
check("the SOURCES block has an ID column, and shows a dash when a frame carries none",
      "ID" in idd_txt and "VN02" in idd_txt
      and "-" in strip(F.render({}, _C(), ("127.0.0.1", 5005), now, aux={a.ip: a})).splitlines()[-1],
      [l for l in idd_txt.splitlines() if "videonest" in l])

a = F.AuxView("192.168.1.143", "videonest")      # a fresh one: the frames above left it mid-edit
a.feed(VN1_B8, now)
one_board = {"192.168.137.62": F.BoardView("192.168.137.62")}
one_board["192.168.137.62"].feed(
    b"$CFG,sr=500,board=incunest_V18,mac=10:51:DB:50:87:A4,fw=0.14*00\r\n", now)
txt = strip(F.render(one_board, _C(), ("127.0.0.1", 5005), now, aux={a.ip: a}))
check("the phone gets its own SOURCES block, not a row in the board table",
      "SOURCES (non-board)" in txt and "videonest" in txt
      and "192.168.1.143" not in txt.split("SOURCES")[0], txt.splitlines()[3][:60])
check("the SOURCES row shows the reference SpO2, the confidence and the rate",
      any(l.startswith("videonest") and " 96" in l and "0.98" in l for l in txt.splitlines()),
      [l for l in txt.splitlines() if l.startswith("videonest")])
check("with no auxiliary source there is no SOURCES block at all",
      "SOURCES" not in strip(F.render(one_board, _C(), ("127.0.0.1", 5005), now)))

stale = F.AuxView("192.168.1.143", "videonest")
stale.last_seen = now - 60
txt_stale = strip(F.render(one_board, _C(), ("127.0.0.1", 5005), now, aux={stale.ip: stale}))
check("a phone that went quiet reaches the alert line, like a silent board",
      "!! SILENT:" in txt_stale and "videonest" in txt_stale.split("\n")[1],
      txt_stale.splitlines()[1][:80])

# An auxiliary source ($VN1: a phone doing OCR of the commercial monitor) is not a board and
# must never get a row of its own -- the rule lives once, in pulsenest_hub.AUX_PREFIXES, and both
# the hub and this tool read it from there.
class _CS(_C):
    last_status = ("@STATUS\n"
                   "hub file=pulsenest_hub.py port=5005 up=12s board_dgrams=9 fanout=9\n"
                   "sub 127.0.0.1:5123 fleet_monitor.py ctrl=0 last=0.1s sent=9")


one = {"192.168.137.62": F.BoardView("192.168.137.62")}
scr = strip(F.render(one, _CS(), ("127.0.0.1", 5005), time.monotonic()))
check("every block carries a heading, so none reads as a continuation of the one above",
      "BOARDS" in scr and "HUB AND SUBSCRIBERS" in scr
      and all(not l.startswith("  ") for l in scr.splitlines()),
      [l for l in scr.splitlines() if l.startswith("  ")][:2])
hub_block = scr[scr.find("HUB AND SUBSCRIBERS"):].split("\n")
check("the hub and its subscribers are a table with its own header and rule",
      len(hub_block) > 3 and hub_block[1].startswith("ROLE")
      and set(hub_block[2]) == {"-"} and hub_block[3].startswith("hub "),
      hub_block[:4])

check("$VN1 is an auxiliary prefix, shared with the hub",
      F.AUX_PREFIXES.get(b"$VN1") == "videonest", str(F.AUX_PREFIXES))
check("a measurement frame is not mistaken for one", b"$M4," [:4] not in F.AUX_PREFIXES)

print(f"\n{sum(ok)}/{len(ok)} checks passed — {'OK' if all(ok) else 'FAILURES'}")
sys.exit(0 if all(ok) else 1)
