"""RF tap bench under constant illumination: the TIA gain taps of every board, logged raw at 500 Hz.

Setup (Alex, 2026-10-08): the LEDs of the three probes are covered, so the photodiode sees ambient
light only -- the same current in the four phases (LED1, ALED1, LED2, ALED2) and roughly the same
on the three boards. With a constant source V_TIA = I_amb x RF_nominal x (1 + eps_tap) + V_off at
each tap: the +/-7 % feedback-resistor tolerance of the datasheet, the additive offset of the
analog chain and the switched-RC settling after a gain change become measurable with no pulse in
the way. Analyse with tools/rf_tap_analyze.py; the plan and the results are in docs/rf_taps/.

Protocol, every selected board in parallel, HGAC off throughout, both colours switched back to back:
  A  precheck: --hold s at the taps found (level, noise, ProbeState)
  B  slow ladder 10K -> 1M -> 10K, --hold s per rung, a 100K reference rung between every two taps
     (clouds: the light drift is tracked by the reference, and A-B-A cancels what is left)
  C  fast ladder 10K -> 1M -> 10K at --fast s per rung, --fast-reps times (is a sub-second
     calibration sweep viable?)
  D  neighbouring pairs 10K<>25K ... 500K<>1M, --toggles cycles each, --toggle s per state (the
     one-tap step with no drift, and the settling after the library's freeze)
  E  D again, plus 10K<>1M, with the library's settling freeze OFF (lib v0.104
     afe_settle_freeze_enable): the real switched-RC transient, sample by sample
  G  restore: original taps, freeze ON, original hgac_enable; $LCFG/$CFG read back
Every $M4 row of every board goes to <out>/<date>_<MACsuffix>.csv (raw codes and V_TIA of the four
phases, RF1, RF2, DiagCode, protocol phase) and every command and $CFG/$LCFG to
<out>/<date>_events.csv. Boards are selected by MAC (hotspot IPs change between sessions). Needs the
hub's control: close pulsenest_lab.py first.

    python tools/rf_tap_bench.py [--mac 82:5C 87:A4 88:50] [--hold 10] [--fast 0.1 --fast-reps 10]
                                 [--toggles 20 --toggle 0.2] [--out docs/rf_taps/raw]
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
REF = "100K"
# $M4 field numbers (parts[0] is "$M4"): raw codes 3..8, V_TIA 23..26, RF labels 34/35, DiagCode 21
RAW_COLS = [("LED1", 4), ("ALED1", 6), ("LED2", 3), ("ALED2", 5),
            ("V_TIA_LED1", 23), ("V_TIA_ALED1", 25), ("V_TIA_LED2", 24), ("V_TIA_ALED2", 26),
            ("RF1", 34), ("RF2", 35), ("DiagCode", 21)]


def checksum_line(payload):
    chk = 0
    for c in payload[1:]:
        chk ^= ord(c)
    return ("%s*%02X\r\n" % (payload, chk)).encode()


def parse_kv(line):
    return dict(kv.split("=", 1) for kv in line.split("*")[0].split(",")[1:] if "=" in kv)


class Board:
    def __init__(self, ip, cfg, out_dir, date):
        self.ip, self.cfg, self.lcfg = ip, cfg, {}
        self.mac = cfg.get("mac", "?")
        self.suffix = self.mac.replace(":", "")[-4:]
        self.path = os.path.join(out_dir, "%s_%s.csv" % (date, self.suffix))
        self.f = open(self.path, "w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow(["t_s", "SmpCnt"] + [c for c, _ in RAW_COLS] + ["phase"])
        self.rows, self.t0_us, self.last_smpcnt = 0, None, 0


class Bench:
    def __init__(self, a):
        self.a = a
        self.macs = [m.upper() for m in a.mac]
        os.makedirs(a.out, exist_ok=True)
        self.date = time.strftime("%Y-%m-%d")
        self.phase = "-"
        self.client = HubClient(script_name(__file__), control=True, log=lambda s: print("   ", s))
        self.boards, self.pending = {}, {}
        self.events_path = os.path.join(a.out, "%s_events.csv" % self.date)
        self.events_f = open(self.events_path, "w", newline="", encoding="utf-8")
        self.events_w = csv.writer(self.events_f)
        self.events_w.writerow(["host_t", "phase", "ip", "mac", "last_smpcnt", "kind", "text"])

    # ── logging ──
    def event(self, kind, text, b=None):
        self.events_w.writerow(["%.3f" % time.monotonic(), self.phase, b.ip if b else "", b.mac if b else "",
                                b.last_smpcnt if b else "", kind, text])
        self.events_f.flush()
        if kind in ("PHASE", "LCFG", "ERR"):
            print("  [%s] %s %s" % (kind, b.mac if b else "", text[:110]))

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
            for line in data.decode("ascii", "replace").splitlines():
                if line.startswith("$CFG,"):
                    cfg = parse_kv(line)
                    mac = cfg.get("mac", "").upper()
                    if ip in self.boards:
                        self.boards[ip].cfg = cfg
                        self.event("CFG", line.split("*")[0], self.boards[ip])
                    elif any(mac.endswith(m) for m in self.macs):
                        self.boards[ip] = Board(ip, cfg, self.a.out, self.date)
                        self.event("CFG", line.split("*")[0], self.boards[ip])
                    else:
                        self.pending[ip] = cfg
                    continue
                b = self.boards.get(ip)
                if b is None:
                    continue
                if line.startswith("$M4,"):
                    parts = line.split("*")[0].split(",")
                    if len(parts) < 37:
                        continue
                    try:
                        ts_us = int(parts[2]); b.last_smpcnt = int(parts[1])
                    except ValueError:
                        continue
                    if b.t0_us is None:
                        b.t0_us = ts_us
                    b.w.writerow(["%.6f" % ((ts_us - b.t0_us) / 1e6), parts[1]] + [parts[i] for _, i in RAW_COLS] + [self.phase])
                    b.rows += 1
                elif line.startswith("$LCFG,"):
                    b.lcfg = parse_kv(line)
                    self.event("LCFG", line.split("*")[0], b)
                elif line.startswith("$ERR"):
                    self.event("ERR", line, b)
                elif line.startswith("# SET"):
                    self.event("MSG", line, b)

    # ── commands ──
    def send(self, b, payload):
        self.event("CMD", payload, b)
        if not self.client.send_to_board(b.ip, checksum_line(payload)):
            raise RuntimeError("not the hub's controller")

    def set_tap(self, tap, settle=0.05):
        """Both colours, back to back, on every board; one short gap per board so the firmware's
        $CFG replies do not pile up. Returns after `settle` s of extra quiet."""
        for b in self.boards.values():
            self.send(b, "$SET,tiagain1,%s" % tap)
            self.send(b, "$SET,tiagain2,%s" % tap)
            self.pump(0.02)
        self.pump(settle)

    def set_all(self, key, per_board_or_val):
        for ip, b in self.boards.items():
            val = per_board_or_val[ip] if isinstance(per_board_or_val, dict) else per_board_or_val
            self.send(b, "$SET,%s,%s" % (key, val))
            self.pump(0.1)

    def begin(self, name, text):
        self.phase = name
        self.event("PHASE", "%s: %s" % (name, text))

    # ── protocol ──
    def run(self):
        a = self.a
        print(banner(__file__, "RF tap ladder under constant light, every board, raw at 500 Hz"))
        if not self.client.connect():
            print("ERROR: no hub"); return 1
        self.pump(3.0)
        if not self.client.controller:
            print("ERROR: control held by %s - close pulsenest_lab.py" % self.client.control_refused_by); return 1
        missing = [m for m in self.macs if not any(b.mac.upper().endswith(m) for b in self.boards.values())]
        if missing:
            print("ERROR: no $CFG from %s (seen %s)" % (missing, [c.get("mac") for c in self.pending.values()])); return 1
        for b in self.boards.values():
            self.send(b, "$LCFG?")
        self.pump(2.0)
        for b in self.boards.values():
            print("board %s  ip %s  fw %s lib %s  tia1 %s tia2 %s  hgac_enable %s  settle_freeze %s"
                  % (b.mac, b.ip, b.cfg.get("fw"), b.cfg.get("lib"), b.cfg.get("tia1"), b.cfg.get("tia2"),
                     b.lcfg.get("hgac_enable"), b.lcfg.get("afe_settle_freeze_enable", "n/a (lib < 0.104)")))
        has_switch = all("afe_settle_freeze_enable" in b.lcfg for b in self.boards.values())
        orig = {ip: (b.cfg["tia1"], b.cfg["tia2"], b.lcfg.get("hgac_enable", "1")) for ip, b in self.boards.items()}
        pairs = list(zip(TAPS[:-1], TAPS[1:]))
        try:
            self.set_all("hgac_enable", "0"); self.pump(0.5)
            self.begin("A", "precheck at the taps found, %g s" % a.hold)
            self.pump(a.hold)
            up = [x for tap in TAPS for x in ((tap, REF) if tap != REF else (tap,))]
            ladder = up + up[-2::-1]
            self.begin("B", "slow ladder with %s reference between taps, %d rungs x %g s" % (REF, len(ladder), a.hold))
            for tap in ladder:
                self.set_tap(tap); self.pump(a.hold)
            fast = TAPS + TAPS[-2::-1]
            self.begin("C", "fast ladder %d rungs x %g s, %d repetitions" % (len(fast), a.fast, a.fast_reps))
            for _ in range(a.fast_reps):
                for tap in fast:
                    self.set_tap(tap, settle=0.0); self.pump(a.fast)
            self.begin("D", "neighbouring pairs, %d cycles x %g s per state, freeze ON" % (a.toggles, a.toggle))
            self.toggle_pairs(pairs)
            if has_switch:
                self.set_all("afe_settle_freeze_enable", "0"); self.pump(1.0)
                self.begin("E", "pairs + 10K<>1M with the settling freeze OFF")
                self.toggle_pairs(pairs + [("10K", "1M")])
                self.set_all("afe_settle_freeze_enable", "1"); self.pump(1.0)
            else:
                self.event("PHASE", "E skipped: no afe_settle_freeze_enable on these boards")
        finally:
            self.begin("G", "restore")
            if has_switch:
                self.set_all("afe_settle_freeze_enable", "1")
            self.set_all("tiagain1", {ip: o[0] for ip, o in orig.items()})
            self.set_all("tiagain2", {ip: o[1] for ip, o in orig.items()})
            self.set_all("hgac_enable", {ip: o[2] for ip, o in orig.items()})
            self.pump(1.0)
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

    def toggle_pairs(self, pairs):
        for lo, hi in pairs:
            self.event("PHASE", "%s pair %s <> %s" % (self.phase, lo, hi))
            self.set_tap(lo); self.pump(self.a.toggle)
            for _ in range(self.a.toggles):
                self.set_tap(hi, settle=0.0); self.pump(self.a.toggle)
                self.set_tap(lo, settle=0.0); self.pump(self.a.toggle)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mac", nargs="+", default=["82:5C", "87:A4", "88:50"], help="MAC suffixes of the boards")
    ap.add_argument("--hold", type=float, default=10.0, help="seconds per slow rung (default %(default)s)")
    ap.add_argument("--fast", type=float, default=0.1, help="seconds per fast rung (default %(default)s)")
    ap.add_argument("--fast-reps", type=int, default=10)
    ap.add_argument("--toggles", type=int, default=20, help="cycles per neighbouring pair")
    ap.add_argument("--toggle", type=float, default=0.2, help="seconds per toggle state")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "rf_taps", "raw"))
    return Bench(ap.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
