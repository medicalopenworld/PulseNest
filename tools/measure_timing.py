"""Capture $TIMING / $TASK frames from the board and report the PRF budget verdict.

Usage:  python tools/measure_timing.py [COMxx] [seconds]
        (port auto-detected if omitted — the first non-Bluetooth serial port; default 25 s)

Requirements:
  - Firmware built with INCUNEST_TIMING_STATS=1 (already set in platformio.ini). No reflash needed
    if the running image has it: frames are emitted every 2500 samples = 5 s at 500 Hz.
  - USB cable. `_emit_timing()` uses Serial.printf, so $TIMING goes over SERIAL ONLY, never UDP.

What it answers: whether the PRF can be raised. `_ts_cycle` (incunest_afe4490.cpp) wraps the 6 SPI
transactions plus the whole of `_process_sample()` under `_state_mutex` — everything that must fit
in 1/PRF. The report scores cycle_max against the budget of each PRF in the validated grid
(spec §7.4): < 60 % of budget = OK, < 90 % = tight, >= 90 % = does not fit.

Reference point: 2026-04-10, library v0.14 → cycle_max = 640 us (32 % of the 2000 us budget at
500 Hz). HGAC, RSQM, the probe-state detector, ppg_disp and switched-RC settling were all added
after that measurement, so expect a higher figure.

The ESP32 TIMING window in pulsenest_lab.py shows the same data from the GUI.
"""
import sys, time, serial
from serial.tools import list_ports

LABELS = ["hr1_mean", "hr1_max", "hr2fp_mean", "hr2fp_max", "hr3fp_mean", "hr3fp_max",
          "spo2_mean", "spo2_max", "cycle_mean", "cycle_max",
          "hr2cmp_mean", "hr2cmp_max", "hr3cmp_mean", "hr3cmp_max", "stack_free"]
GRID = [500, 800, 1000, 1250, 1600]


def pick_port(arg):
    if arg:
        return arg
    cands = [p for p in list_ports.comports() if "Bluetooth" not in p.description
             and "Bluetooth" not in (p.manufacturer or "")]
    if not cands:
        sys.exit("No non-Bluetooth serial port found - is the board plugged in over USB?")
    if len(cands) > 1:
        print("Candidates:", ", ".join(f"{p.device} ({p.description})" for p in cands))
    return cands[0].device


def checksum_ok(line):
    if "*" not in line:
        return False
    body, _, chk = line[1:].rpartition("*")
    c = 0
    for ch in body.encode():
        c ^= ch
    return f"{c:02X}" == chk.strip().upper()


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
    print(f"Listening on {port} for {dur:.0f} s …")
    frames, tasks, other = [], [], 0
    t0 = time.time()
    with serial.Serial(port, 115200, timeout=1) as s:
        while time.time() - t0 < dur:
            try:
                line = s.readline().decode("ascii", "replace").strip()
            except serial.SerialException as e:
                sys.exit(f"Serial error: {e}")
            if not line:
                continue
            if line.startswith("$TIMING,"):
                ok = checksum_ok(line)
                vals = line[1:].split("*")[0].split(",")[1:]
                if len(vals) == 15:
                    frames.append(([int(v) for v in vals], ok))
                    print(f"  [{time.time()-t0:5.1f}s] $TIMING frame #{len(frames)} "
                          f"({'chk ok' if ok else 'CHK FAIL'})")
            elif line.startswith("$TASK,"):
                tasks.append(line)
            else:
                other += 1

    if not frames:
        sys.exit(f"\nNo $TIMING frames in {dur:.0f} s ({other} other lines seen).\n"
                 "Either the firmware was not built with INCUNEST_TIMING_STATS=1, "
                 "or the board is not streaming.")

    print(f"\n{len(frames)} $TIMING frames, {other} other lines\n")
    print(f"{'metric':>12} " + " ".join(f"{'#'+str(i+1):>8}" for i in range(len(frames))) + f" {'worst':>8}")
    print("-" * (13 + 9 * len(frames) + 9))
    cols = list(zip(*[f[0] for f in frames]))
    for name, col in zip(LABELS, cols):
        print(f"{name:>12} " + " ".join(f"{v:>8}" for v in col) + f" {max(col):>8}")

    cycle_mean = max(cols[LABELS.index("cycle_mean")])
    cycle_max = max(cols[LABELS.index("cycle_max")])
    print(f"\ncycle: mean {cycle_mean} us, max {cycle_max} us")
    print(f"\n{'PRF':>6} {'budget':>9} {'mean use':>10} {'max use':>9}  verdict")
    for prf in GRID:
        budget = 1_000_000 / prf
        m, x = 100 * cycle_mean / budget, 100 * cycle_max / budget
        verdict = "OK" if x < 60 else ("TIGHT" if x < 90 else "OVER BUDGET")
        print(f"{prf:>6} {budget:>8.0f}us {m:>9.1f}% {x:>8.1f}%  {verdict}")

    if tasks:
        print("\n$TASK frames (last set):")
        for t in tasks[-4:]:
            print("  " + t)


if __name__ == "__main__":
    main()
