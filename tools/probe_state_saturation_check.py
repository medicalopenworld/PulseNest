"""Does LED-only saturation with tissue present lock the probe in an absent state with HGAC off?

The chain under test (incunest_afe4490.cpp, RSQM ladder + HGAC gate; lib v0.90 names —
until v0.89 the absent state below was PROBE_NOT_APPLIED, value 1):

    thin tissue + high RF  ->  LED phase saturates, ambient phase clean
                           ->  PROBE_ONLY_LED_SATURATING   ("assumed air", v0.61; own state since v0.90)
                           ->  HGAC gated off              (HGAC gate: isProbeAbsent() is true)
                           ->  nobody lowers RF, saturation persists
                           ->  still absent                (stable lock)

Reads a Lab Capture CSV, decodes CH_MASKS per sample, and reports:
  * a compressed timeline of (probe state, RF1, which phase saturates)
  * every stretch of LED-only saturation, with the state it produced and whether RF moved
  * the verdict: locked (LED-only sat + an absent state + RF constant for >= LOCK_S) or not

CH_MASKS is %04X: bits[3:0]=adc_sat_pos, [7:4]=adc_sat_neg, [11:8]=tia_over_fs, [15:12]=tia_over_lin.
Within each nibble: bit0=LED1, bit1=ALED1, bit2=LED2, bit3=ALED2 (enum AFE4490Ch).

Usage:  python tools/probe_state_saturation_check.py captures/SATCHECK_*.csv
"""
import sys
import numpy as np

LOCK_S  = 5.0
STATES  = {0: "DISCONNECTED", 1: "OT_HIGH", 2: "APPLIED", 3: "AMB_SATURATING",
           4: "ONLY_LED_SATURATING"}          # lib v0.90 names; 1 and 3 keep their values
LED_BITS, AMB_BITS = 0x5, 0xA          # LED1|LED2 , ALED1|ALED2


def load(path):
    header, rows = None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split(",")
            if header is None:
                header = parts
                continue
            rows.append(parts)
    idx = {name: header.index(name) for name in
           ("FW_Ts_us", "FW_ProbeState", "FW_CH_MASKS", "FW_RF1_OHM", "FW_RF2_OHM",
            "FW_OT_LED1", "FW_OT_LED2", "FW_DiagCode")}
    out = {k: [] for k in idx}
    for r in rows:
        if len(r) <= max(idx.values()):
            continue
        try:
            out["FW_Ts_us"].append(float(r[idx["FW_Ts_us"]]))
            out["FW_ProbeState"].append(int(float(r[idx["FW_ProbeState"]])))
            out["FW_CH_MASKS"].append(int(r[idx["FW_CH_MASKS"]].strip(), 16))
            out["FW_RF1_OHM"].append(float(r[idx["FW_RF1_OHM"]]))
            out["FW_RF2_OHM"].append(float(r[idx["FW_RF2_OHM"]]))
            out["FW_OT_LED1"].append(float(r[idx["FW_OT_LED1"]]))
            out["FW_OT_LED2"].append(float(r[idx["FW_OT_LED2"]]))
            out["FW_DiagCode"].append(int(float(r[idx["FW_DiagCode"]])))
        except ValueError:
            continue
    return {k: np.array(v) for k, v in out.items()}


def sat_kind(mask):
    """-> 'none' | 'led' | 'amb' | 'both' from adc_sat_pos | tia_over_fs, per phase."""
    pos = (mask & 0xF) | ((mask >> 8) & 0xF)          # any positive saturation, either mechanism
    led = bool(pos & LED_BITS)
    amb = bool(pos & AMB_BITS)
    return "both" if (led and amb) else "amb" if amb else "led" if led else "none"


def rf_str(ohm):
    return "%dK" % round(ohm / 1e3) if ohm < 1e6 else "%.0fM" % (ohm / 1e6)


def main(path):
    d = load(path)
    t  = (d["FW_Ts_us"] - d["FW_Ts_us"][0]) / 1e6
    fs = 1e6 / np.median(np.diff(d["FW_Ts_us"]))
    st = d["FW_ProbeState"]
    rf = d["FW_RF1_OHM"]
    kinds = np.array([sat_kind(m) for m in d["FW_CH_MASKS"]])
    n = len(t)
    print("%s\n%d muestras, %.1f s, fs=%.0f Hz\n" % (path, n, t[-1], fs))

    # ── compressed timeline: a row whenever (state, RF, sat kind) changes ─────
    print("%-8s %-8s %-13s %-5s %-6s %8s %8s" % ("t_ini", "dur_s", "estado", "RF1", "satura", "OT1ppm", "OT2ppm"))
    key = list(zip(st, np.round(rf), kinds))
    i = 0
    while i < n:
        j = i
        while j + 1 < n and key[j + 1] == key[i]:
            j += 1
        dur = t[j] - t[i] + 1.0 / fs
        if dur >= 0.2:                       # hide sub-200 ms flicker
            print("%-8.1f %-8.1f %-13s %-5s %-6s %8.0f %8.0f"
                  % (t[i], dur, STATES.get(st[i], "?"), rf_str(rf[i]), kinds[i],
                     np.mean(d["FW_OT_LED1"][i:j + 1]) * 1e6,
                     np.mean(d["FW_OT_LED2"][i:j + 1]) * 1e6))
        i = j + 1

    # ── the question ────────────────────────────────────────────────────────
    print("\n=== saturacion SOLO LED (ambiente limpio) ===")
    led_only = kinds == "led"
    if not led_only.any():
        print("no hay ninguna muestra con saturacion solo-LED -> la cadena no se ejercito")
        return
    # stretches of led-only
    edges = np.flatnonzero(np.diff(np.concatenate(([0], led_only.astype(int), [0]))))
    locked = False
    for a, b in zip(edges[::2], edges[1::2]):
        seg_st = st[a:b]
        seg_rf = rf[a:b]
        dur = (b - a) / fs
        states = {STATES.get(s, "?"): int((seg_st == s).sum() / fs * 10) / 10.0
                  for s in np.unique(seg_st)}
        rf_moved = len(np.unique(np.round(seg_rf))) > 1
        na = np.isin(seg_st, (1, 4)).mean()               # OT_HIGH or ONLY_LED_SATURATING
        print("  t=%.1f-%.1f s (%.1f s): estados %s | RF %s%s"
              % (t[a], t[min(b, n - 1)], dur, states,
                 rf_str(seg_rf[0]), " -> " + rf_str(seg_rf[-1]) if rf_moved else " constante"))
        if na > 0.9 and not rf_moved and dur >= LOCK_S:   # na: absent share (1 or 4)
            locked = True

    print("\nVEREDICTO:", end=" ")
    if locked:
        print("BLOQUEO CONFIRMADO — saturacion solo-LED, estado ausente (ONLY_LED_SATURATING / OT_HIGH),\n"
              "           y RF no se movio durante >= %.0f s. HGAC no actuo porque isProbeAbsent() es true.\n"
              "           Con tejido presente, es un falso negativo estable que nadie corrige." % LOCK_S)
    else:
        print("sin bloqueo estable en esta captura (o RF se movio, o el estado no fue ausente).")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
        print("\n" + "=" * 78 + "\n")
