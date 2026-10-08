"""Analyse an rf_tap_bench run (constant illumination, RF tap ladder on every board).

Under a constant source every phase sees the same photodiode current, so at a tap
V_TIA = I_amb x RF_nominal x (1 + eps_tap) + V_off, where eps_tap is the real-to-nominal deviation
of that feedback resistor (datasheet: +/-7 %) and V_off an additive offset of the analog chain.
The offset dominates at the low taps (a few mV against V_TIA of 7-16 mV at 10K), so the taps cannot
be compared by simple ratios: this script fits the model jointly over both passes of the ladder,
with I_amb allowed to drift linearly in time (the light), one V_off per phase, and one eps per tap
anchored so that the mean eps over the measured taps is zero (the absolute resistance is not
observable, only the tap-to-tap pattern). Saturated rungs (|V_TIA| at the rail) are excluded.

Also reported: the step a one-tap HGAC move produces on OT (eps_to - eps_from), the settling left
after the library's switched-RC freeze (first free sample vs steady level), the ambient drift, and
the phase-to-phase offset differences (what survives in LED - ALED).

Outputs (docs/rf_taps/, long format, a re-run of the same date and board replaces its rows):
  rf_tap_levels.csv     one row per board x pass x tap x phase: steady V_TIA, SD, implied I_pd,
                        saturation, frozen samples, settle time, first-free-sample deviation
  rf_tap_tolerance.csv  one row per board x tap: eps_tap [%] and its uncertainty (half the up/down
                        pass disagreement), plus the
                        fitted V_off per phase and I_amb at the run's midpoint
  rf_tap_steps.csv      one row per board x neighbouring tap pair: the OT step [%] of that move

    python tools/rf_tap_analyze.py [--stamp YYYYMMDD_HHMMSS] [--in captures/rf_taps] [--out docs/rf_taps]
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RF_OHM = {"10K": 10e3, "25K": 25e3, "50K": 50e3, "100K": 100e3, "250K": 250e3, "500K": 500e3, "1M": 1e6}
TAPS = list(RF_OHM)
# phase -> (V_TIA column, the RF column that drives it)
PHASES = {"LED1": ("V_TIA_LED1", "RF1_OHM"), "ALED1": ("V_TIA_ALED1", "RF1_OHM"),
          "LED2": ("V_TIA_LED2", "RF2_OHM"), "ALED2": ("V_TIA_ALED2", "RF2_OHM")}
V_SAT = 0.95          # |V_TIA| above this: the TIA/ADC is at its rail, the level means nothing
SKIP_HEAD_S = 1.0     # steady window of a rung: skip the first second (settling + any residue)
SKIP_TAIL_S = 0.2
MIN_RUNG_S = 2.0      # shorter runs of one RF label are transients between commands, not rungs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--in", dest="in_dir", default=os.path.join(ROOT, "captures", "rf_taps"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "rf_taps"))
    a = ap.parse_args()
    events = sorted(glob.glob(os.path.join(a.in_dir, "*_events.csv")))
    stamp = a.stamp or os.path.basename(events[-1])[:15]
    ev = pd.read_csv(os.path.join(a.in_dir, "%s_events.csv" % stamp))
    cfg_by_mac = {}
    for _, r in ev[ev["kind"] == "CFG"].iterrows():
        cfg_by_mac.setdefault(r["mac"], dict(kv.split("=", 1) for kv in str(r["text"]).split(",")[1:] if "=" in kv))
    os.makedirs(a.out, exist_ok=True)
    date = "%s-%s-%s" % (stamp[:4], stamp[4:6], stamp[6:8])
    levels, tol, steps = [], [], []
    for path in sorted(glob.glob(os.path.join(a.in_dir, "*_%s_m4.csv" % stamp))):
        df = pd.read_csv(path, low_memory=False)
        suffix = os.path.basename(path)[:4]
        mac = next((m for m in cfg_by_mac if m.replace(":", "").endswith(suffix)), suffix)
        cfg = cfg_by_mac.get(mac, {})
        fs = float(cfg.get("sr", 500))
        t = (df["Ts_us"].to_numpy(float) - df["Ts_us"].iloc[0]) / 1e6
        gaps = np.diff(df["SmpCnt"].to_numpy())
        print("\n%s  %s  fw %s lib %s  rows %d (%.0f s)  lost rows %d"
              % ("=" * 30, mac, cfg.get("fw"), cfg.get("lib"), len(df), len(df) / fs, int((gaps - 1)[gaps > 1].sum())))
        obs = []    # (phase, tap, pass, t_mid, V) for the fit
        for ph, (vcol, rfcol) in PHASES.items():
            v = df[vcol].to_numpy(float)
            rungs = [r for r in segment(df[rfcol].astype(str).to_numpy()) if (r[2] - r[1]) >= MIN_RUNG_S * fs]
            n_up = (len(rungs) + 1) // 2
            for k, (tap, i0, i1) in enumerate(rungs):
                pas = "up" if k < n_up else "down"
                s0, s1 = i0 + int(SKIP_HEAD_S * fs), i1 - int(SKIP_TAIL_S * fs)
                steady = v[s0:s1]
                mean, sd = float(steady.mean()), float(steady.std())
                sat = abs(mean) > V_SAT
                frozen, settle, first_dev = settling(v, i0, mean, sd, fs)
                levels.append(dict(date=date, board_mac=mac, fw=cfg.get("fw"), lib=cfg.get("lib"), tap=tap,
                                   rf_nom_ohm=RF_OHM[tap], **{"pass": pas}, phase=ph, t_mid_s=round(float(t[(s0 + s1) // 2]), 1),
                                   n=len(steady), v_tia_mean_V=round(mean, 7), v_tia_sd_V=round(sd, 7),
                                   i_pd_nA=round(mean / RF_OHM[tap] * 1e9, 3), saturated=int(sat),
                                   frozen_samples=frozen, settle_s=settle, first_free_dev_pct_of_step=first_dev))
                if not sat:
                    obs.append((ph, tap, pas, float(t[(s0 + s1) // 2]), mean))
        fit = fit_model(obs)
        if fit is None:
            print("  not enough unsaturated rungs to fit"); continue
        eps, _se, voff, i0, i1, resid_pct, t_ref = fit
        # uncertainty: half the disagreement between the two passes fitted on their own (the
        # formal least-squares error is meaningless here: 12 levels, correlated light drift)
        halves = [fit_model([o for o in obs if o[2] == pas]) for pas in ("up", "down")]
        eps_se = {tp: (abs(halves[0][0][tp] - halves[1][0][tp]) / 2 if all(h and tp in h[0] for h in halves) else float("nan"))
                  for tp in eps}
        print("  I_amb %.1f nA at t = %.0f s, drift %+.3f %%/min;  V_off per phase: %s"
              % (i0 * 1e9, t_ref, i1 / i0 * 100 * 60, "  ".join("%s %+.2f mV" % (p, voff[p] * 1e3) for p in PHASES)))
        print("  eps_tap (real/nominal - 1, mean over measured taps = 0) [%]:  "
              + "  ".join("%s %+.2f±%.2f" % (tp, eps[tp], eps_se[tp]) for tp in TAPS if tp in eps)
              + "   | RMS residual %.3f %%" % resid_pct)
        meas = [tp for tp in TAPS if tp in eps]
        for tp in TAPS:
            tol.append(dict(date=date, board_mac=mac, fw=cfg.get("fw"), lib=cfg.get("lib"), tap=tp, rf_nom_ohm=RF_OHM[tp],
                            eps_pct=round(eps[tp], 3) if tp in eps else np.nan, eps_se_pct=round(eps_se[tp], 3) if tp in eps else np.nan,
                            saturated=int(tp not in eps), i_amb_nA=round(i0 * 1e9, 1), i_amb_drift_pct_per_min=round(i1 / i0 * 6000, 3),
                            **{"v_off_%s_mV" % p: round(voff[p] * 1e3, 3) for p in PHASES}, rms_resid_pct=round(resid_pct, 3),
                            anchor="mean eps over measured taps = 0"))
        for lo, hi in zip(TAPS[:-1], TAPS[1:]):
            ok = lo in eps and hi in eps
            steps.append(dict(date=date, board_mac=mac, tap_from=lo, tap_to=hi, ratio_nominal=RF_OHM[hi] / RF_OHM[lo],
                              ot_step_pct=round(((1 + eps[hi] / 100) / (1 + eps[lo] / 100) - 1) * 100, 3) if ok else np.nan,
                              ot_step_se_pct=round(float(np.hypot(eps_se[hi], eps_se[lo])), 3) if ok else np.nan))
        print("  one-tap OT step up the ladder [%]: " + "  ".join(
            "%s>%s %+.2f" % (s["tap_from"], s["tap_to"], s["ot_step_pct"]) for s in steps if s["board_mac"] == mac and np.isfinite(s["ot_step_pct"])))
        lv = [r for r in levels if r["board_mac"] == mac and not r["saturated"]]
        fr = [r["frozen_samples"] for r in lv if r["phase"] == "LED1"]
        fd = [abs(r["first_free_dev_pct_of_step"]) for r in lv if r["phase"] in ("LED1", "LED2") and np.isfinite(r["first_free_dev_pct_of_step"])]
        st = [r["settle_s"] for r in lv if np.isfinite(r["settle_s"])]
        print("  settling: frozen samples %s; first free sample within %.2f %% of the step (max); settle to 3 SD: median %.3f s, max %.3f s"
              % (sorted(set(fr)), max(fd) if fd else float("nan"), float(np.median(st)) if st else float("nan"), max(st) if st else float("nan")))
    out = {"rf_tap_levels.csv": pd.DataFrame(levels), "rf_tap_tolerance.csv": pd.DataFrame(tol), "rf_tap_steps.csv": pd.DataFrame(steps)}
    for name, new in out.items():
        p = os.path.join(a.out, name)
        if os.path.exists(p):
            old = pd.read_csv(p)
            old = old[~((old["date"] == date) & old["board_mac"].isin(new["board_mac"]))]
            new = pd.concat([old, new], ignore_index=True)
        new.to_csv(p, index=False, lineterminator="\n")
        print("written %s (%d rows)" % (p, len(new)))
    return 0


def fit_model(obs):
    """Linear least squares of V = (I0 + I1 (t - t_ref)) RF (1 + eps_tap) + V_off_phase, linearised in
    eps (eps << 1, I1 t << I0): V ~ I0 RF + I1 (t - t_ref) RF + I0 RF eps_tap + V_off_phase. The eps
    are anchored by the constraint sum(eps) = 0 (one row of the system). Returns eps [%] and their
    standard errors per tap, V_off per phase, I0, I1, the RMS relative residual and t_ref."""
    taps = sorted({o[1] for o in obs}, key=TAPS.index)
    phases = sorted({o[0] for o in obs}, key=list(PHASES).index)
    if len(taps) < 3 or len(obs) < len(taps) + len(phases) + 2:
        return None
    t_ref = float(np.mean([o[3] for o in obs]))
    # first pass without eps to get I0 for the linearisation
    A0 = np.array([[RF_OHM[o[1]], (o[3] - t_ref) * RF_OHM[o[1]]] + [1.0 if o[0] == p else 0.0 for p in phases] for o in obs])
    y = np.array([o[4] for o in obs])
    w = 1.0 / np.abs(y)                                     # relative weighting: every tap counts the same
    sol0 = np.linalg.lstsq(A0 * w[:, None], y * w, rcond=None)[0]
    I0 = sol0[0]
    cols = ["I0", "I1"] + ["off_" + p for p in phases] + ["eps_" + tp for tp in taps]
    A = np.array([[RF_OHM[o[1]], (o[3] - t_ref) * RF_OHM[o[1]]] + [1.0 if o[0] == p else 0.0 for p in phases]
                  + [I0 * RF_OHM[o[1]] if o[1] == tp else 0.0 for tp in taps] for o in obs])
    Aw = A * w[:, None]; yw = y * w
    # anchor: sum(eps) = 0, as a heavily weighted extra equation
    big = 1e3 * np.abs(Aw).max()
    anchor = np.zeros(len(cols)); anchor[len(cols) - len(taps):] = big
    Aw = np.vstack([Aw, anchor]); yw = np.append(yw, 0.0)
    sol, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    pred = A @ sol
    resid_rel = (y - pred) / y
    dof = max(len(obs) - (len(cols) - 1), 1)
    s2 = float(np.sum(((yw - Aw @ sol)[:-1]) ** 2)) / dof
    cov = s2 * np.linalg.pinv(Aw.T @ Aw)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    k = len(cols) - len(taps)
    eps = {tp: float(sol[k + i]) * 100 for i, tp in enumerate(taps)}
    eps_se = {tp: float(se[k + i]) * 100 for i, tp in enumerate(taps)}
    voff = {p: float(sol[2 + i]) for i, p in enumerate(phases)}
    return eps, eps_se, voff, float(sol[0]), float(sol[1]), float(np.sqrt(np.mean(resid_rel ** 2)) * 100), t_ref  # eps_se: formal, replaced by the caller


def segment(labels):
    """[(label, i_start, i_end)] for every run of equal RF label."""
    out, i0 = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[i0]:
            out.append((labels[i0], i0, i))
            i0 = i
    return out


def settling(v, i0, mean, sd, fs):
    """Frozen samples right after the rung starts, settle time from the first free sample (|v - mean|
    within 3 SD for 0.2 s) and that sample's deviation from the steady level in % of the step. The
    library holds the input for datasheet t5 (8 samples at 500 Hz) and the $M4 rows carry the frozen
    values, so what happens inside the freeze is not observable here."""
    if i0 == 0:
        return 0, float("nan"), float("nan")
    frozen = 0
    while i0 + frozen + 1 < len(v) and v[i0 + frozen + 1] == v[i0 + frozen]:
        frozen += 1
    j = i0 + frozen + 1
    step = mean - v[i0 - 1]
    first_dev = (v[j] - mean) / step * 100 if abs(step) > 0 else float("nan")
    band = max(3 * sd, 1e-6)
    n_hold = int(0.2 * fs)
    seg = v[j:j + int(SKIP_HEAD_S * fs) + n_hold]
    ok = np.abs(seg - mean) <= band
    run = 0
    for k in range(len(ok)):
        run = run + 1 if ok[k] else 0
        if run >= n_hold:
            return frozen, round((k - n_hold + 1) / fs, 4), round(first_dev, 2)
    return frozen, float("nan"), round(first_dev, 2)


if __name__ == "__main__":
    sys.exit(main())
