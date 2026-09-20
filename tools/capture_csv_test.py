"""Offline checks for pulsenest_capture_csv.py -- the piece whose mistakes are silent.

A column indexed wrong does not raise: it writes a well-formed row of the wrong numbers, and
nobody notices until the analysis. So the indexing, the frame-mode fallbacks, the RF conversion
and the refusal to turn a non-data line into a row are checked here, with no board and no hub:

    python tools/capture_csv_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_capture_csv import (CaptureCsvWriter, CAPTURE_COLS, col_spec_all,  # noqa: E402
                                   col_spec_mandatory)

print(f"== {os.path.basename(__file__)} ==  the shared capture CSV writer")
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


# $M4 with a recognisable value in every field: field k holds k, except the last two (RF strings).
M4 = "$M4," + ",".join(str(i) for i in range(1, 34)) + ",500K,10K*06"
M1 = "$M1,7,8,9*00"
M2 = "$M2,11,12,13,14,15,16,17,18,19,20*00"

w = CaptureCsvWriter("unused", col_spec_all(), host_t_us=True)
row = w.format_row(M4, host_t_us=1789935222613634)
hdr = w.header()
check("the header is HOST_T_US then every dictionary column in order",
      hdr[0] == "HOST_T_US" and hdr[1:] == [c[1] for c in CAPTURE_COLS], hdr[:4])
check("each column reads its own field of the frame",
      row[hdr.index("FW_SmpCnt")] == "1" and row[hdr.index("LED1")] == "4"
      and row[hdr.index("FW_HR3")] == "18" and row[hdr.index("FW_CH_MASKS")] == "33",
      str(row[:6]))
check("RF arrives as a display string and is written in ohms",
      row[hdr.index("FW_RF1_OHM")] == "500000.0" and row[hdr.index("FW_RF2_OHM")] == "10000.0",
      row[-2:])
check("an RF value outside the closed table falls back to -1, never a guess",
      w.format_row("$M4," + ",".join("0" for _ in range(33)) + ",700K,?*00")[-2:] == ["-1", "-1"])
check("the host clock leads the row, and -1 when it is not known",
      row[0] == "1789935222613634" and w.format_row(M4)[0] == "-1")

# narrower frame modes
r1 = w.format_row(M1)
check("$M1: the fields it does not have read -1, never a shifted value",
      r1[hdr.index("FW_SmpCnt")] == "7" and r1[hdr.index("FW_HR3")] == "-1", str(r1[:5]))
r2 = w.format_row(M2)
check("$M2 is remapped, not read positionally (its layout differs)",
      r2[hdr.index("LED2")] == "12" and r2[hdr.index("LED1_SUB")] == "17", str(r2[:8]))

# the thing that must never happen
for line in ("$CFG,sr=500,numav=8,led1=49.80*00", "# STAT frame_dropped=0", "$ERR,x", "$VN1,1,96,0.9,1*00"):
    check(f"a non-data line is refused, not turned into a row: {line[:12]}",
          w.format_row(line) is None)

# a whole datagram, which is what the recorder hands over
tmp = tempfile.mkdtemp(prefix="csvw_")
path = os.path.join(tmp, "t.csv")
w2 = CaptureCsvWriter(path, col_spec_mandatory())
w2.open(pre_notes="session=X\nfrom-board: $CFG,sr=500*00")
batch = "\r\n".join([M4] * 5) + "\r\n" + "# STAT x=1\r\n"
n = w2.write_datagram(batch.encode(), host_t_us=1)
w2.add_event("board restarted")
w2.close(post_notes="rows=5")
body = open(path, encoding="cp1252").read().splitlines()
check("a batch of five frames writes five rows, and the # STAT line is skipped, not written",
      n == 5 and w2.count == 5 and w2.skipped == 1, f"{n} {w2.count} {w2.skipped}")
check("pre-notes, header, rows, event and post-notes, in that order",
      body[0].startswith("# session=") and body[2].startswith("LED2,")
      and len([l for l in body if not l.startswith("#")]) == 6
      and any(l.startswith("# event @row 5: board restarted") for l in body)
      and body[-1] == "# rows=5", body[:3] + body[-2:])
check("the mandatory spec is the four codes and the two subtractions",
      [c for c, _ in col_spec_mandatory()] == ["LED2", "LED1", "ALED2", "ALED1", "LED2_SUB", "LED1_SUB"])

# target: a capture asked for N rows contains exactly N
w3 = CaptureCsvWriter(os.path.join(tmp, "t2.csv"), col_spec_mandatory(), target=3)
w3.open()
reached = [w3.write_row(M4) for _ in range(6)]
w3.close()
check("a target of 3 writes exactly 3 rows and says so on the third",
      w3.count == 3 and reached == [False, False, True, False, False, False], f"{w3.count} {reached}")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(ok)}/{len(ok)} checks passed -- {'OK' if all(ok) else 'FAILURES'}")
sys.exit(0 if all(ok) else 1)
