#!/usr/bin/env python3
"""
tia_linearity_sweep.py — experiment: characterize the AFE4490 TIA linearity
(knee/clip location) via the firmware-reconstructed V_TIA_LED1.

RESULT (2026-07-08, IncuNest 16.A, firmware pre-v0.34 per-branch values):
no knee at 0.5 V/branch; linear to ~0.90 V/branch; hard clip ~0.97 V/branch,
independent of AMBDAC (clip is inside the TIA, pre-ambient-subtraction) and
of RF (output node hits the rail).  In the differential domain: linear to
~1.8 V, clip ~1.94 V.  Convention settled: library >= v0.34 stores/streams
V_TIA (differential = 2 x I_PD x RF).

NOTE: CSVs recorded before 2026-07-09 contain PER-BRANCH values (V_TIA_LED1
column); newer runs record V_TIA_LED1 (values x2).

Method
------
Ramps LED1 current in fine steps and records V_TIA_LED1 from $M4 frames.
V_TIA grows proportionally to LED current until the TIA compresses.
The ramp is repeated with several AMBDAC values (shifts the ADC observation
window: v_adc = v_tia - 0.2*AMBDAC_uA, RG=x1) so every V_TIA region
is observed with the ADC unsaturated.  It is also repeated with two RF
settings: LED droop is a function of LED mA while TIA compression is a
function of V_TIA — if the knee lands on the same V_TIA (not the
same mA) for both RF values, the compression is in the TIA, not in the LED.

Usage
-----
1. CLOSE pulsenest_lab.py (this script binds the same UDP data port 5005).
2. ESP32 streaming over WiFi as usual.  Probe WITHOUT finger.
3. Run:  python tia_linearity_sweep.py
4. Results: tia_linearity_sweep_<date>.csv + console analysis
   (+ tia_linearity_sweep_<date>.png if matplotlib is available).

Protocol constants must match pulsenest_lab.py / include/wifi_config.h.
"""

import socket
import statistics
import sys
import time
from datetime import datetime

# ── Protocol (must match pulsenest_lab.py) ──────────────────────────────────
UDP_DATA_PORT = 5005          # ESP32 -> host data frames
UDP_CMD_PORT  = 5006          # host -> ESP32 commands
ADC_FS_COUNTS = 2 ** 21 - 1   # positive full-scale code (datasheet Table 7)
ADC_FSR       = 1.2           # V

# ── Experiment configuration ────────────────────────────────────────────────
RF_LIST        = ["50K", "100K"]   # TIA feedback resistance settings to test
AMBDAC_LIST    = [0, 3, 5, 8]      # uA — shifts the ADC observation window
LED_MIN_MA     = 2
LED_MAX_MA     = 150
LED_STEP_MA    = 2
SETTLE_S       = 0.4               # after each $SET before measuring
N_SAMPLES      = 250               # ~0.5 s @ 500 Hz
ADC_SAT_COUNTS = 2_050_000         # |counts| above this -> ADC clipped
V_ADC_VALID    = 1.05              # |v_adc| beyond this -> discard (near clip)
SAT_BREAK      = 3                 # consecutive ADC+ saturated steps -> next window
CMD_GAP_S      = 0.06              # >= one Cmd_Task cycle between $SET datagrams
BASE_LO, BASE_HI = 0.20, 0.80      # v_tia baseline slope segment [V]
KNEE_DROP      = 0.90              # local slope below 90% of baseline -> knee


def checksum_wrap(payload: str) -> bytes:
    chk = 0
    for c in payload[1:]:
        chk ^= ord(c)
    return f"{payload}*{chk:02X}\r\n".encode()


class Esp32Link:
    """UDP link: receives $M4 frames on UDP_DATA_PORT, sends commands to
    ESP32_IP:UDP_CMD_PORT (IP learned from the first incoming datagram)."""

    def __init__(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        try:
            self.rx.bind(("", UDP_DATA_PORT))
        except OSError:
            sys.exit(f"ERROR: cannot bind UDP port {UDP_DATA_PORT} — "
                     "close pulsenest_lab.py first.")
        self.rx.settimeout(1.0)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.esp32_ip = None

    def wait_esp32(self, timeout_s=15.0):
        print(f"Waiting for ESP32 datagrams on UDP :{UDP_DATA_PORT} ...")
        t_end = time.monotonic() + timeout_s
        while time.monotonic() < t_end:
            try:
                _, addr = self.rx.recvfrom(4096)
                self.esp32_ip = addr[0]
                print(f"ESP32 found at {self.esp32_ip}")
                return
            except socket.timeout:
                continue
        sys.exit("ERROR: no UDP data received — is the ESP32 streaming?")

    def send(self, payload: str):
        self.tx.sendto(checksum_wrap(payload), (self.esp32_ip, UDP_CMD_PORT))
        time.sleep(CMD_GAP_S)   # lwIP RX queue is shallow; pace the datagrams

    def send_raw(self, payload: str):
        # $MODE (and other non-$SET commands) must be sent WITHOUT checksum:
        # firmware does an exact strcmp on the argument text.
        self.tx.sendto(f"{payload}\n".encode(), (self.esp32_ip, UDP_CMD_PORT))
        time.sleep(CMD_GAP_S)

    def drain(self, seconds: float):
        t_end = time.monotonic() + seconds
        while time.monotonic() < t_end:
            try:
                self.rx.recvfrom(4096)
            except socket.timeout:
                pass

    def collect(self, n: int, timeout_s=6.0):
        """Collect n $M4 samples -> list of (led1_counts, v_tia_led1).
        parts[23] is V_TIA_LED1 with firmware >= v0.34 (differential)."""
        out = []
        t_end = time.monotonic() + timeout_s
        while len(out) < n and time.monotonic() < t_end:
            try:
                data, _ = self.rx.recvfrom(4096)
            except socket.timeout:
                continue
            for line in data.split(b"\n"):
                line = line.strip().rstrip(b"\r")
                if not line.startswith(b"$M4,"):
                    continue
                parts = line.decode(errors="replace").split(",")
                # 0:$M4 1:SmpCnt 2:Ts_us 3:LED2 4:LED1 ... 23:V_TIA_LED1 ...
                if len(parts) < 31:
                    continue
                try:
                    led1_counts = int(parts[4])
                    v_tia_led1  = float(parts[23])
                except ValueError:
                    continue
                out.append((led1_counts, v_tia_led1))
        return out


def main():
    link = Esp32Link()
    link.wait_esp32()

    stamp    = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path = f"tia_linearity_sweep_{stamp}.csv"

    # Fixed conditions: $M4 frames, LED2 off, Stage 2 gain x1 on channel 1.
    link.send_raw("$MODE,M4")
    link.send("$SET,led2,0")
    link.send("$SET,stg21,0dB")

    rows = []   # (rf, ambdac, led_mA, n, counts_mean, v_adc, v_tia_med, v_tia_std, valid) — diff domain
    led_values = list(range(LED_MIN_MA, LED_MAX_MA + 1, LED_STEP_MA))
    total = len(RF_LIST) * len(AMBDAC_LIST) * len(led_values)
    done  = 0
    t0    = time.monotonic()

    for rf in RF_LIST:
        link.send(f"$SET,tiagain1,{rf}")
        for amb in AMBDAC_LIST:
            link.send(f"$SET,ambdac,{amb}")
            sat_streak = 0
            for led in led_values:
                done += 1
                link.send(f"$SET,led1,{led}")
                link.drain(SETTLE_S)
                samples = link.collect(N_SAMPLES)
                if not samples:
                    print(f"  [{done}/{total}] RF={rf} AMBDAC={amb} LED={led} mA — NO DATA")
                    continue
                counts = [s[0] for s in samples]
                vtias  = [s[1] for s in samples]
                counts_mean = sum(counts) / len(counts)
                v_adc       = counts_mean / ADC_FS_COUNTS * ADC_FSR
                v_tia_med   = statistics.median(vtias)
                v_tia_std   = statistics.pstdev(vtias)
                adc_sat_pos = max(counts) >= ADC_SAT_COUNTS
                valid       = (abs(v_adc) <= V_ADC_VALID
                               and max(abs(c) for c in counts) < ADC_SAT_COUNTS)
                rows.append((rf, amb, led, len(samples), counts_mean, v_adc,
                             v_tia_med, v_tia_std, int(valid)))
                print(f"  [{done}/{total}] RF={rf} AMBDAC={amb} LED={led:3d} mA  "
                      f"V_ADC={v_adc:+.3f} V  V_TIA={v_tia_med:.4f} V  "
                      f"{'ok' if valid else 'DISCARD'}")
                if adc_sat_pos:
                    sat_streak += 1
                    if sat_streak >= SAT_BREAK:
                        print(f"    ADC saturated {SAT_BREAK}x — next window")
                        break
                else:
                    sat_streak = 0

    # ── CSV (cp1252, project convention) ────────────────────────────────────
    with open(csv_path, "w", encoding="cp1252", errors="replace") as f:
        f.write("# TIA linearity sweep — V_TIA domain (differential = 2 x I_PD x RF, "
                "firmware >= v0.34; CSVs before 2026-07-09 were per-branch)\n")
        f.write(f"# date={stamp} led2=0mA stg21=0dB settle={SETTLE_S}s "
                f"n={N_SAMPLES} probe=NO FINGER (expected)\n")
        f.write("RF,ambdac_uA,LED1_mA,n,LED1_counts_mean,V_ADC_LED1_V,"
                "V_TIA_LED1_median_V,V_TIA_LED1_std_V,adc_valid\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]:.1f},{r[5]:.5f},"
                    f"{r[6]:.5f},{r[7]:.5f},{r[8]}\n")
    print(f"\nCSV written: {csv_path}   ({len(rows)} rows, "
          f"{time.monotonic() - t0:.0f} s)")

    analyze(rows)
    plot(rows, f"tia_linearity_sweep_{stamp}.png")


def analyze(rows):
    """Per-RF piecewise slope table: local d(V_TIA)/d(LED mA) within each
    (RF, AMBDAC) segment, binned by V_TIA and normalized to the baseline
    slope measured in BASE_LO..BASE_HI V."""
    print("\n================ ANALYSIS ================")
    for rf in RF_LIST:
        slopes = []   # (v_tia_mid, slope) from consecutive valid points
        for amb in AMBDAC_LIST:
            seg = [r for r in rows if r[0] == rf and r[1] == amb and r[8]]
            seg.sort(key=lambda r: r[2])
            for a, b in zip(seg, seg[1:]):
                d_led = b[2] - a[2]
                if 0 < d_led <= 2 * LED_STEP_MA:
                    slopes.append(((a[6] + b[6]) / 2, (b[6] - a[6]) / d_led))
        base = [s for v, s in slopes if BASE_LO <= v <= BASE_HI]
        if not base:
            print(f"RF={rf}: not enough baseline points ({BASE_LO}-{BASE_HI} V)")
            continue
        base_slope = statistics.median(base)
        print(f"\nRF={rf}  baseline slope ({BASE_LO}-{BASE_HI} V): "
              f"{base_slope * 1000:.3f} mV/mA")
        print("  V_TIA bin [V]   slope/baseline   n")
        knee = None
        for lo10 in range(0, 22):
            lo, hi = lo10 / 10.0, lo10 / 10.0 + 0.1
            binned = [s for v, s in slopes if lo <= v < hi]
            if not binned:
                continue
            rel = statistics.median(binned) / base_slope
            print(f"    {lo:.1f}-{hi:.1f}        {rel:8.3f}       {len(binned)}")
            if knee is None and hi > BASE_HI and rel < KNEE_DROP:
                knee = (lo, hi)
        if knee:
            print(f"  --> knee (slope < {KNEE_DROP:.0%} of baseline) first seen "
                  f"in bin {knee[0]:.1f}-{knee[1]:.1f} V")
        else:
            print("  --> no knee detected within observed range")
    print("\nReference (2026-07-08 sweep, diff domain): linear to ~1.8 V, "
          "hard clip ~1.94 V, independent of AMBDAC and RF.  Same-knee-"
          "V_TIA across both RF values rules out LED droop as the cause.")


def plot(rows, png_path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not available — skipping plot)")
        return
    fig, axes = plt.subplots(1, len(RF_LIST), figsize=(7 * len(RF_LIST), 5),
                             squeeze=False)
    for ax, rf in zip(axes[0], RF_LIST):
        for amb in AMBDAC_LIST:
            seg = [r for r in rows if r[0] == rf and r[1] == amb and r[8]]
            seg.sort(key=lambda r: r[2])
            if seg:
                ax.plot([r[2] for r in seg], [r[6] for r in seg],
                        marker=".", label=f"AMBDAC={amb} uA")
        ax.axhline(1.0,  ls="--", c="orange", label="1.0 V (TIA full-scale, diff, spec)")
        ax.axhline(1.94, ls="--", c="red",    label="1.94 V (observed clip, diff)")
        ax.set_title(f"RF = {rf}")
        ax.set_xlabel("LED1 current [mA]")
        ax.set_ylabel("V_TIA_LED1 median [V]")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    print(f"Plot written: {png_path}")


if __name__ == "__main__":
    main()
