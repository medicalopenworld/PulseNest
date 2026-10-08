"""RF tap bench under constant illumination: walk every TIA gain tap on every board and log V_TIA.

Setup (2026-10-09, Alex): the LEDs of the three probes are covered, so the photodiode sees ambient
light only -- the same current in the four phases (LED1, ALED1, LED2, ALED2) and roughly the same
on the three boards. With a constant source, V_TIA = I_amb x RF_real at each tap, so the ratio of
V_TIA between two taps divided by the nominal RF ratio is the ratio of their real-to-nominal
resistance -- the +/-7 % feedback-resistor tolerance of the datasheet, measured tap by tap, with no
pulse in the way (unlike the 2026-10-08 simulator run). The first samples after each step also
show whatever settling the library's switched-RC freeze (datasheet t5, 8 samples at 500 Hz) leaves.

Protocol, all selected boards in parallel: HGAC off, tiagain1 = tiagain2 = tap, ladder
10K -> 25K -> ... -> 1M -> ... -> 10K (every pair twice, A-B-A against light drift), --hold s per
rung; every $M4 row of every board goes to captures/rf_taps/<MAC>_<stamp>_m4.csv and every command
and $CFG/$LCFG to <stamp>_events.csv; the boards are restored (original taps, original hgac_enable).
Boards are selected by MAC (hotspot IPs change between sessions). Needs the hub's control: close
pulsenest_lab.py first. Analyse with tools/rf_tap_analyze.py.

    python tools/rf_tap_bench.py [--mac 82:5C 87:A4 88:50] [--hold 10] [--out captures/rf_taps]
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import banner, script_name  # noqa: E402
from pulsenest_hub_client import HubClient      # noqa: E402

TAPS = ["10K", "25K", "50K", "100K", "250K", "500K", "1M"]
M4_COLS = ["SmpCnt", "Ts_us", "LED2", "LED1", "ALED2", "ALED1", "LED2_SUB", "LED1_SUB", "PPG", "SpO2",
           "SpO2_SQI", "R", "PI", "HR1", "HR1_SQI", "HR2", "HR2_SQI", "HR3", "HR3_SQI", "RSQI",
           "DiagCode", "ProbeState", "V_TIA_LED1", "V_TIA_LED2", "V_TIA_ALED1", "V_TIA_ALED2",
           "I_PD_LED1", "I_PD_LED2", "I_PD_ALED1", "I_PD_ALED2", "OT_LED1", "OT_LED2", "CH_MASKS",
           "RF1_OHM", "RF2_OHM", "R_CORR"]


def checksum_line(payload):
    chk = 0
    for c in payload[1:]:
        chk ^= ord(c)
    return ("%s*%02X\r\n" % (payload, chk)).encode()


def parse_kv(line):
    return dict(kv.split("=", 1) for kv in line.split("*")[0].split(",")[1:] if "=" in kv)


class Board:
    def __init__(self, ip, cfg, out_dir, stamp):
        self.ip = ip
        self.cfg = cfg
        self.lcfg = {}
        self.mac = cfg.get("mac", "?")
        self.suffix = self.mac.replace(":", "")[-4:]
        self.path = os.path.join(out_dir, "%s_%s_m4.csv" % (self.suffix, stamp))
        self.f = open(self.path, "w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow(["host_t"] + M4_COLS)
        self.rows = 0
        self.last_smpcnt = 0


class Bench:
    def __init__(self, macs, hold_s, out_dir):
        self.macs = [m.upper() for m in macs]
        self.hold_s = hold_s
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.client = HubClient(script_name(__file__), control=True, log=lambda s: print("   ", s))
        self.boards = {}                      # ip -> Board
        self.pending_cfg = {}                 # ip -> cfg of a board not (yet) selected
        self.events_path = os.path.join(out_dir, "%s_events.csv" % self.stamp)
        self.events_f = open(self.events_path, "w", newline="", encoding="utf-8")
        self.events_w = csv.writer(self.events_f)
        self.events_w.writerow(["host_t", "ip", "mac", "kind", "text"])

    def event(self, kind, text, ip="", mac=""):
        self.events_w.writerow(["%.3f" % time.monotonic(), ip, mac, kind, text])
        self.events_f.flush()
        print("  [%s] %s %s" % (kind, mac or ip, text[:100]))

    def pump(self, seconds):
        t_end = time.monotonic() + seconds
        while True:
            left = t_end - time.monotonic()
            if left <= 0:
                return
            item = self.client.recv(min(0.2, left))
            if item is None:
                continue
            ip, data = item
            now = time.monotonic()
            for line in data.decode("ascii", "replace").splitlines():
                if line.startswith("$CFG,"):
                    cfg = parse_kv(line)
                    mac = cfg.get("mac", "").upper()
                    if ip in self.boards:
                        self.boards[ip].cfg = cfg
                        self.event("CFG", line.split("*")[0], ip, mac)
                    elif any(mac.endswith(m) for m in self.macs):
                        self.boards[ip] = Board(ip, cfg, self.out_dir, self.stamp)
                        self.event("CFG", line.split("*")[0], ip, mac)
                    else:
                        self.pending_cfg[ip] = cfg
                    continue
                b = self.boards.get(ip)
                if b is None:
                    continue
                if line.startswith("$M4,"):
                    parts = line.split("*")[0].split(",")
                    if len(parts) < 37:
                        continue
                    b.w.writerow(["%.3f" % now] + parts[1:37])
                    b.rows += 1
                    try:
                        b.last_smpcnt = int(parts[1])
                    except ValueError:
                        pass
                elif line.startswith("$LCFG,"):
                    b.lcfg = parse_kv(line)
                    self.event("LCFG", line.split("*")[0], ip, b.mac)
                elif line.startswith("$ERR") or line.startswith("# SET"):
                    self.event("MSG", line, ip, b.mac)

    def send(self, b, payload):
        self.event("CMD", payload, b.ip, b.mac)
        if not self.client.send_to_board(b.ip, checksum_line(payload)):
            raise RuntimeError("not the hub's controller")

    def set_all(self, key, val, per_board=None):
        """$SET key=val on every board (per_board: ip -> value overrides val)."""
        for ip, b in self.boards.items():
            self.send(b, "$SET,%s,%s" % (key, per_board[ip] if per_board else val))
            self.pump(0.15)   # the firmware answers each $SET with a $CFG; spread them out

    def run(self):
        print(banner(__file__, "RF tap ladder under constant light, every board, through the hub"))
        if not self.client.connect():
            print("ERROR: no hub"); return 1
        self.pump(3.0)
        if not self.client.controller:
            print("ERROR: control held by %s - close pulsenest_lab.py" % self.client.control_refused_by)
            return 1
        missing = [m for m in self.macs if not any(b.mac.upper().endswith(m) for b in self.boards.values())]
        if missing:
            print("ERROR: no $CFG from board(s) %s (seen: %s)" % (missing, [c.get("mac") for c in self.pending_cfg.values()]))
            return 1
        for b in self.boards.values():
            self.send(b, "$LCFG?")
        self.pump(2.0)
        for b in self.boards.values():
            print("board %s  ip %s  fw %s lib %s  tia1 %s tia2 %s  led1 %s  hgac_enable %s"
                  % (b.mac, b.ip, b.cfg.get("fw"), b.cfg.get("lib"), b.cfg.get("tia1"), b.cfg.get("tia2"),
                     b.cfg.get("led1"), b.lcfg.get("hgac_enable")))
        orig = {ip: (b.cfg["tia1"], b.cfg["tia2"], b.lcfg.get("hgac_enable", "1")) for ip, b in self.boards.items()}
        ladder = TAPS + TAPS[-2::-1]          # 10K ... 1M ... 10K
        try:
            self.set_all("hgac_enable", "0")
            self.pump(1.0)
            for tap in ladder:
                self.event("PHASE", "tap %s on both colours, hold %g s" % (tap, self.hold_s))
                # Both colours back to back per board, so the LED1 and LED2 steps land within a few
                # ms of each other (the 2026-10-08 run sent tiagain1 to every board, then tiagain2:
                # the LED2 phase stepped 0.45 s after LED1 and looked like a slow settle).
                for ip, b in self.boards.items():
                    self.send(b, "$SET,tiagain1,%s" % tap)
                    self.send(b, "$SET,tiagain2,%s" % tap)
                    self.pump(0.15)
                self.pump(self.hold_s)
        finally:
            self.event("PHASE", "restore")
            self.set_all("tiagain1", None, {ip: o[0] for ip, o in orig.items()})
            self.set_all("tiagain2", None, {ip: o[1] for ip, o in orig.items()})
            self.set_all("hgac_enable", None, {ip: o[2] for ip, o in orig.items()})
            self.pump(2.0)
            for b in self.boards.values():
                self.send(b, "$LCFG?")
            self.pump(2.0)
            for b in self.boards.values():
                b.f.close()
            self.events_f.close()
            self.client.close()
        for b in self.boards.values():
            print("%s: %d rows -> %s" % (b.mac, b.rows, b.path))
        print("events -> %s" % self.events_path)
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mac", nargs="+", default=["82:5C", "87:A4", "88:50"], help="MAC suffixes of the boards to walk")
    ap.add_argument("--hold", type=float, default=10.0, help="seconds per rung (default %(default)s)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "rf_taps"))
    a = ap.parse_args()
    return Bench(a.mac, a.hold, a.out).run()


if __name__ == "__main__":
    sys.exit(main())
