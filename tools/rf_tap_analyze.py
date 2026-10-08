"""Analyse an rf_tap_bench run (constant illumination, RF tap ladder on every board, raw at 500 Hz).

Model. Under a constant source every phase sees the same photodiode current, so at a tap
V_TIA = I_amb(t) x RF_nominal x (1 + eps_tap) + V_off_phase: eps_tap is the real-to-nominal
deviation of that feedback resistor (datasheet +/-7 %), V_off an additive offset of the analog
chain (a few mV, so it dominates the low taps and makes plain level ratios meaningless), I_amb(t)
the light, which drifts (clouds). The slow ladder (phase B) interleaves a 100K reference rung
between taps: I_amb at each tap rung is interpolated from the reference rungs around it, and
eps_tap, V_off are solved by nonlinear least squares with the constraint mean(eps) = 0 over the
measured taps (the absolute resistance is not observable, only the tap-to-tap pattern).

Also: the fast ladder (phase C, eps from ~80 ms per tap, repeated: is a sub-second calibration
sweep viable?), the neighbouring-pair toggles (phase D: the one-tap OT step with the drift
cancelled; the residue after the library's settling freeze) and the same toggles with the freeze
off (phase E: the real switched-RC transient, sample by sample, and the samples needed to settle to
1 % and 0.1 % of the step). Figures to <out>/fig/, tables to <out>/*.csv, a report skeleton with the
tables to <out>/rf_tap_report_<date>.md (conclusions are written by hand after reading it).

    python tools/rf_tap_analyze.py [--date YYYY-MM-DD] [--in docs/rf_taps/raw] [--out docs/rf_taps]
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RF_OHM = {"10K": 10e3, "25K": 25e3, "50K": 50e3, "100K": 100e3, "250K": 250e3, "500K": 500e3, "1M": 1e6}
TAPS = list(RF_OHM)
REF = "100K"
PHASES = {"LED1": ("V_TIA_LED1", "RF1"), "ALED1": ("V_TIA_ALED1", "RF1"),
          "LED2": ("V_TIA_LED2", "RF2"), "ALED2": ("V_TIA_ALED2", "RF2")}
V_SAT = 1.15          # the rail is 1.1999 V; above this the level means nothing
FS = 500.0
SETTLE_BIT = 32768    # RSQM_DIAG_SWITCHED_RC_SETTLING in DiagCode


# ───────────────────────────────────────────── helpers ──
def segment(labels, idx0=0):
    """[(label, i_start, i_end)] runs of equal label (indices into the parent frame)."""
    out, i0 = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[i0]:
            out.append((labels[i0], idx0 + i0, idx0 + i))
            i0 = i
    return out


def steady(v, i0, i1, skip_s=1.0, tail_s=0.2):
    s0, s1 = i0 + int(skip_s * FS), i1 - int(tail_s * FS)
    if s1 - s0 < 10:
        s0, s1 = i0 + (i1 - i0) // 2, i1
    x = v[s0:s1]
    return float(x.mean()), float(x.std()), len(x), (s0 + s1) // 2


def fit_ladder(rungs, voff0):
    """rungs: list of dicts(tap, phase, t, v) for one board, phase B (unsaturated). Reference rungs
    give I(t) by linear interpolation in time (per phase); unknowns: eps per tap (mean 0), V_off
    per phase, I at the reference rungs (through eps_REF and V_off). Returns eps, V_off, rms."""
    taps = sorted({r["tap"] for r in rungs}, key=TAPS.index)
    phases = sorted({r["phase"] for r in rungs}, key=list(PHASES).index)
    ti, pi = {t: i for i, t in enumerate(taps)}, {p: i for i, p in enumerate(phases)}
    refs = {p: sorted([r for r in rungs if r["tap"] == REF and r["phase"] == p], key=lambda r: r["t"]) for p in phases}
    nonref = [r for r in rungs if r["tap"] != REF]

    def unpack(x):
        eps = dict(zip(taps, x[:len(taps)])); voff = dict(zip(phases, x[len(taps):]))
        return eps, voff

    def resid(x):
        eps, voff = unpack(x)
        out = []
        for r in nonref:
            p = r["phase"]
            tr = np.array([q["t"] for q in refs[p]]); vr = np.array([q["v"] for q in refs[p]])
            i_ref = (vr - voff[p]) / (RF_OHM[REF] * (1 + eps[REF]))        # I_amb at the reference rungs
            i_here = np.interp(r["t"], tr, i_ref)
            pred = i_here * RF_OHM[r["tap"]] * (1 + eps[r["tap"]]) + voff[p]
            out.append((r["v"] - pred) / r["v"])
        out.append(1e3 * np.mean(list(eps.values())))                        # anchor: mean eps = 0
        # One light level cannot separate V_off from the eps pattern: eps'_tap = eps_tap - d/(I RF_tap) + c
        # fits exactly as well for any d. A weak ridge on eps picks the smallest tap pattern consistent
        # with the data (the physical prior: resistors are within +/-7 %, offsets are free); the
        # sensitivity to that choice is reported alongside (offset_sensitivity below).
        out.extend(0.05 * np.array(list(eps.values())))
        return np.array(out)

    x0 = np.concatenate([np.zeros(len(taps)), [voff0.get(p, 0.0) for p in phases]])
    sol = least_squares(resid, x0, x_scale=np.concatenate([np.full(len(taps), 0.01), np.full(len(phases), 1e-3)]))
    eps, voff = unpack(sol.x)
    rr = resid(sol.x)[:len(nonref)]
    return eps, voff, float(np.sqrt(np.mean(rr ** 2)) * 100), taps


def offset_sensitivity(eps, i_amb):
    """% change of eps_tap per +1 mV of V_off along the unidentifiable direction (mean kept at 0)."""
    d = {tp: -1e-3 / (i_amb * RF_OHM[tp]) for tp in eps}
    c = -np.mean(list(d.values()))
    return {tp: (d[tp] + c) * 100 for tp in eps}


def fit_offset_linear(rungs):
    """Starting point for V_off: plain linear fit V = I RF + V_off per phase over one pass."""
    out = {}
    for p in set(r["phase"] for r in rungs):
        rs = [r for r in rungs if r["phase"] == p]
        x = np.array([RF_OHM[r["tap"]] for r in rs]); y = np.array([r["v"] for r in rs]); w = 1 / np.abs(y)
        A = np.vstack([x, np.ones_like(x)]).T
        sol = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)[0]
        out[p] = float(sol[1])
    return out


def load_extra_rungs(extra_dir, suffix):
    """Rung levels of a bench-v1 run (columns V_TIA_*, RF1_OHM/RF2_OHM labels, Ts_us) for one board:
    [(tap, phase, t_s, v_mean)], unsaturated, first second of every rung skipped."""
    import glob as _g
    files = sorted(_g.glob(os.path.join(extra_dir, "%s_*_m4.csv" % suffix)))
    if not files:
        return []
    df = pd.read_csv(files[-1], low_memory=False)
    t = (df["Ts_us"].to_numpy(float) - df["Ts_us"].iloc[0]) / 1e6
    out = []
    for p, (vcol, rfcol) in PHASES.items():
        v = df[vcol].to_numpy(float)
        rf = df[rfcol.replace("RF", "RF") + "_OHM"].astype(str).to_numpy()
        for tap, i0, i1 in segment(rf):
            if (i1 - i0) < 4 * FS:
                continue
            m, sd, n, imid = steady(v, i0, i1)
            if abs(m) <= 1.05 and sd < 0.01 * abs(m):   # drop rail-clipping rungs (the pre-ladder 1M of 10:08)
                out.append(dict(tap=tap, phase=p, t=float(t[imid]), v=m))
    return out


def fit_two_levels(rungs_now, rungs_extra, voff0):
    """Joint fit of the current run (I(t) from the 100K reference rungs) and a run at another light
    level (I(t) linear in time): common eps per tap (mean 0) and common V_off per phase. Two light
    levels break the V_off / eps degeneracy: eps' = eps - d/(I RF) + c cannot hold for two I at once.
    Returns eps, voff, rms_now, rms_extra, (I_extra_mid, I_now_mid)."""
    taps = sorted({r["tap"] for r in rungs_now} | {r["tap"] for r in rungs_extra}, key=TAPS.index)
    phases = sorted({r["phase"] for r in rungs_now}, key=list(PHASES).index)
    refs = {p: sorted([r for r in rungs_now if r["tap"] == REF and r["phase"] == p], key=lambda r: r["t"]) for p in phases}
    nonref = [r for r in rungs_now if r["tap"] != REF]
    t_mid_x = float(np.mean([r["t"] for r in rungs_extra]))
    n_t, n_p = len(taps), len(phases)

    def unpack(x):
        return dict(zip(taps, x[:n_t])), dict(zip(phases, x[n_t:n_t + n_p])), x[n_t + n_p], x[n_t + n_p + 1]

    def resid(x):
        eps, voff, ia, ib = unpack(x)
        out = []
        for r in nonref:
            p = r["phase"]
            tr = np.array([q["t"] for q in refs[p]]); vr = np.array([q["v"] for q in refs[p]])
            i_ref = (vr - voff[p]) / (RF_OHM[REF] * (1 + eps[REF]))
            pred = np.interp(r["t"], tr, i_ref) * RF_OHM[r["tap"]] * (1 + eps[r["tap"]]) + voff[p]
            out.append((r["v"] - pred) / r["v"])
        for r in rungs_extra:
            pred = (ia + ib * (r["t"] - t_mid_x)) * RF_OHM[r["tap"]] * (1 + eps[r["tap"]]) + voff[r["phase"]]
            out.append((r["v"] - pred) / r["v"])
        out.append(1e3 * np.mean(list(eps.values())))
        return np.array(out)

    i0_x = float(np.mean([r["v"] / RF_OHM[r["tap"]] for r in rungs_extra if r["tap"] == REF]))
    x0 = np.concatenate([np.zeros(n_t), [voff0.get(p, 0.0) for p in phases], [i0_x, 0.0]])
    sol = least_squares(resid, x0, x_scale=np.concatenate([np.full(n_t, 0.01), np.full(n_p, 1e-3), [i0_x * 0.1, i0_x * 1e-3]]))
    eps, voff, ia, ib = unpack(sol.x)
    rr = resid(sol.x)
    rms_now = float(np.sqrt(np.mean(rr[:len(nonref)] ** 2)) * 100)
    rms_x = float(np.sqrt(np.mean(rr[len(nonref):len(nonref) + len(rungs_extra)] ** 2)) * 100)
    i_now = float(np.mean([(r["v"] - voff[r["phase"]]) / (RF_OHM[REF] * (1 + eps[REF])) for r in rungs_now if r["tap"] == REF]))
    return eps, voff, rms_now, rms_x, (ia, i_now), taps


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=None)
    ap.add_argument("--in", dest="in_dir", default=os.path.join(ROOT, "docs", "rf_taps", "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "rf_taps"))
    ap.add_argument("--extra-run", default=None, metavar="DIR",
                    help="directory with a bench-v1 run (<suffix>_<stamp>_m4.csv) taken at ANOTHER light level: "
                         "joined to the slow-ladder fit, it separates V_off from the eps pattern")
    a = ap.parse_args()
    ev_files = sorted(glob.glob(os.path.join(a.in_dir, "*_events.csv")))
    date = a.date or os.path.basename(ev_files[-1])[:10]
    ev = pd.read_csv(os.path.join(a.in_dir, "%s_events.csv" % date))
    cfg_by_mac = {}
    for _, r in ev[ev["kind"] == "CFG"].iterrows():
        cfg_by_mac.setdefault(r["mac"], dict(kv.split("=", 1) for kv in str(r["text"]).split(",")[1:] if "=" in kv))
    fig_dir = os.path.join(a.out, "fig"); os.makedirs(fig_dir, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    T_levels, T_tol, T_steps, T_settle, T_fast = [], [], [], [], []
    report = ["# RF tap characterisation under constant light — %s\n" % date,
              "_Generated by `tools/rf_tap_analyze.py` from `docs/rf_taps/raw/%s_*.csv`; conclusions below the tables are written by hand._\n" % date]
    fig_eps, ax_eps = plt.subplots(figsize=(8, 4.5))
    fig_tr, axs_tr = plt.subplots(1, 2, figsize=(13, 4.4))
    boards = sorted(glob.glob(os.path.join(a.in_dir, "%s_*.csv" % date)))
    boards = [p for p in boards if not p.endswith("_events.csv")]
    for bi, path in enumerate(boards):
        df = pd.read_csv(path, low_memory=False)
        suffix = os.path.basename(path)[11:15]
        mac = next((m for m in cfg_by_mac if m.replace(":", "").endswith(suffix)), suffix)
        cfg = cfg_by_mac.get(mac, {})
        t = df["t_s"].to_numpy(float)
        gaps = np.diff(df["SmpCnt"].to_numpy())
        lost = int((gaps - 1)[gaps > 1].sum())
        print("\n%s %s  fw %s lib %s  rows %d (%.0f s)  lost rows %d" % ("=" * 28, mac, cfg.get("fw"), cfg.get("lib"), len(df), t[-1], lost))
        report.append("\n## Board %s (fw %s, lib %s) — %d rows, %.0f s, %d lost\n" % (mac, cfg.get("fw"), cfg.get("lib"), len(df), t[-1], lost))
        V = {p: df[c].to_numpy(float) for p, (c, _) in PHASES.items()}
        RF = {k: df[k].astype(str).to_numpy() for k in ("RF1", "RF2")}
        diag = df["DiagCode"].to_numpy(int)
        ph = df["phase"].astype(str).to_numpy()

        # ── phase B: slow ladder levels + fit ──
        iB = np.flatnonzero(ph == "B")
        rungs_fit, drift_track = [], []
        for p, (vcol, rfcol) in PHASES.items():
            for tap, i0, i1 in segment(RF[rfcol][iB], iB[0]):
                if (i1 - i0) < 4 * FS:
                    continue
                m, sd, n, imid = steady(V[p], i0, i1)
                sat = abs(m) > V_SAT
                # noise -> integration: SD of 50 ms block means (what a fast rung would see)
                blk = V[p][i0 + int(FS):i1 - int(0.2 * FS)]
                blk = blk[:len(blk) // 25 * 25].reshape(-1, 25).mean(axis=1)
                T_levels.append(dict(date=date, board_mac=mac, phase_protocol="B", tap=tap, rf_nom_ohm=RF_OHM[tap], phase=p,
                                     t_mid_s=round(float(t[imid]), 2), n=n, v_tia_mean_V=round(m, 7), v_tia_sd_V=round(sd, 7),
                                     sd_pct=round(sd / abs(m) * 100, 4) if m else np.nan,
                                     sd_of_50ms_means_pct=round(float(blk.std()) / abs(m) * 100, 4) if m and len(blk) > 2 else np.nan,
                                     i_pd_nA=round(m / RF_OHM[tap] * 1e9, 3), saturated=int(sat)))
                if not sat:
                    rungs_fit.append(dict(tap=tap, phase=p, t=float(t[imid]), v=m))
                if tap == REF and p == "LED1":
                    drift_track.append((float(t[imid]), m))
        voff0 = fit_offset_linear(rungs_fit)
        eps, voff, rms, taps_meas = fit_ladder(rungs_fit, voff0)
        sat_taps = [tp for tp in TAPS if tp not in taps_meas]
        dt = np.array(drift_track)
        drift_pct_min = float((dt[-1, 1] / dt[0, 1] - 1) * 100 / ((dt[-1, 0] - dt[0, 0]) / 60)) if len(dt) > 1 else np.nan
        i_amb = float(np.mean([(r["v"] - voff[r["phase"]]) / RF_OHM[REF] for r in rungs_fit if r["tap"] == REF]))
        sens = offset_sensitivity(eps, i_amb)
        print("  B: V_off %s | eps [%%] %s | rms %.3f %% | ref drift %+.2f %%/min | saturated %s"
              % (" ".join("%s %+.2f mV" % (p, voff[p] * 1e3) for p in voff), " ".join("%s %+.2f" % (tp, eps[tp] * 100) for tp in taps_meas), rms, drift_pct_min, sat_taps))
        print("     I_amb %.0f nA; eps shift per +1 mV of V_off: %s" % (i_amb * 1e9, " ".join("%s %+.2f" % (tp, sens[tp]) for tp in taps_meas)))
        two = None
        if a.extra_run:
            rungs_x = load_extra_rungs(a.extra_run, suffix)
            if rungs_x:
                eps2, voff2, rms2n, rms2x, (i_x, i_n), taps2 = fit_two_levels(rungs_fit, rungs_x, voff)
                two = dict(eps=eps2, voff=voff2, rms_now=rms2n, rms_extra=rms2x, i_extra=i_x, i_now=i_n, taps=taps2)
                print("  B+extra (two light levels, I %.0f / %.0f nA): V_off %s | eps [%%] %s | rms now %.3f %% extra %.3f %%"
                      % (i_x * 1e9, i_n * 1e9, " ".join("%s %+.2f mV" % (p, voff2[p] * 1e3) for p in voff2),
                         " ".join("%s %+.2f" % (tp, eps2[tp] * 100) for tp in taps2), rms2n, rms2x))

        # ── phase C: fast ladder, eps per repetition with V_off fixed (two-level when available) ──
        eps_use = two["eps"] if two else eps
        voff_c = two["voff"] if two else voff
        iC = np.flatnonzero(ph == "C")
        eps_fast = {tp: [] for tp in taps_meas}
        if len(iC):
            reps = []        # list of {tap: mean} per repetition, LED1 phase
            cur = {}
            for tap, i0, i1 in segment(RF["RF1"][iC], iC[0]):
                if (i1 - i0) < 15:
                    continue
                free = V["LED1"][i0:i1][(diag[i0:i1] & SETTLE_BIT) == 0]
                free = free[2:] if len(free) > 6 else free            # one more sample of margin
                if tap == "10K" and cur:
                    reps.append(cur); cur = {}
                cur[tap] = float(free.mean()) if len(free) else np.nan
            if cur:
                reps.append(cur)
            for rep in reps:
                if REF not in rep:
                    continue
                i_ref = (rep[REF] - voff_c["LED1"]) / (RF_OHM[REF] * (1 + eps_use[REF]))
                e = {tp: ((rep[tp] - voff_c["LED1"]) / (i_ref * RF_OHM[tp]) - 1) for tp in taps_meas if tp in rep and np.isfinite(rep[tp])}
                shift = np.mean(list(e.values()))                       # same anchor as B: mean 0
                for tp, val in e.items():
                    eps_fast[tp].append(val - shift)
            print("  C: %d fast repetitions; eps_fast - eps_%s [%%]: %s" % (len(reps), "two_level" if two else "slow", " ".join(
                "%s %+.2f±%.2f" % (tp, (np.mean(eps_fast[tp]) - eps_use[tp]) * 100, np.std(eps_fast[tp]) * 100) for tp in taps_meas if eps_fast[tp])))
            for tp in taps_meas:
                if eps_fast[tp]:
                    T_fast.append(dict(date=date, board_mac=mac, tap=tp, n_reps=len(eps_fast[tp]), eps_fast_mean_pct=round(np.mean(eps_fast[tp]) * 100, 3),
                                       eps_fast_sd_pct=round(np.std(eps_fast[tp]) * 100, 3), eps_ref_pct=round(eps_use[tp] * 100, 3),
                                       eps_ref_kind="two_level" if two else "one_level_ridge", diff_pct=round((np.mean(eps_fast[tp]) - eps_use[tp]) * 100, 3)))

        # ── phases D / E: toggles ──
        # A toggle state is a run of one RF label whose two neighbours share another label: its
        # level against the mean of the neighbours gives the pair step with the light drift
        # cancelled; the samples at its start and end give the two transients (into and out of it).
        voff_use = two["voff"] if two else voff
        for phase_name, freeze_on in (("D", True), ("E", False)):
            iX = np.flatnonzero(ph == phase_name)
            if not len(iX):
                continue
            for p, (vcol, rfcol) in PHASES.items():
                states = [st for st in segment(RF[rfcol][iX], iX[0]) if 0.1 * FS <= (st[2] - st[1]) <= 1.0 * FS]
                steps, trans = {}, {}
                for q in range(1, len(states) - 1):
                    tap, i0, i1 = states[q]
                    (ta, a0, a1), (tb, b0, b1) = states[q - 1], states[q + 1]
                    if ta != tb or ta == tap or tap not in RF_OHM or ta not in RF_OHM:
                        continue
                    m_mid = V[p][i0 + (i1 - i0) // 2:i1 - 2].mean()
                    m_nb = 0.5 * (V[p][a0 + (a1 - a0) // 2:a1 - 2].mean() + V[p][b0 + (b1 - b0) // 2:b1 - 2].mean())
                    if abs(m_mid) > V_SAT or abs(m_nb) > V_SAT or m_mid == m_nb:
                        continue
                    lo, hi = sorted((tap, ta), key=lambda x: RF_OHM[x])
                    v_hi, v_lo = (m_mid, m_nb) if tap == hi else (m_nb, m_mid)
                    steps.setdefault((lo, hi), []).append(((v_hi - voff_use[p]) / (v_lo - voff_use[p]) / (RF_OHM[hi] / RF_OHM[lo]) - 1) * 100)
                    for i_step, m_from, m_to in ((i0, m_nb, m_mid), (i1, m_mid, m_nb)):
                        seg_v = V[p][i_step - 2:i_step + 40]
                        if len(seg_v) < 42:
                            continue
                        key = (ta, tap) if i_step == i0 else (tap, ta)          # (from, to)
                        trans.setdefault(key, []).append((seg_v - m_to) / (m_from - m_to))   # 1 = old level, 0 = settled
                for (lo, hi), vals in steps.items():
                    T_steps.append(dict(date=date, board_mac=mac, phase_protocol=phase_name, phase=p, tap_from=lo, tap_to=hi,
                                        n_cycles=len(vals), ot_step_pct_mean=round(float(np.mean(vals)), 3), ot_step_pct_sd=round(float(np.std(vals)), 3),
                                        ot_step_pct_from_ladder=round(((1 + eps_use[hi]) / (1 + eps_use[lo]) - 1) * 100, 3) if hi in eps_use and lo in eps_use else np.nan))
                for (t_from, t_to), store in trans.items():
                    tr = np.median(np.array(store), axis=0)       # index 0 = two samples before the step
                    frozen = 0
                    if freeze_on:
                        while 2 + frozen < len(tr) and abs(tr[2 + frozen] - 1.0) < 0.02:
                            frozen += 1

                    def n_within(th):
                        for n in range(2, len(tr) - 3):
                            if np.all(np.abs(tr[n:n + 3]) < th):
                                return n - 2
                        return np.nan
                    row = dict(date=date, board_mac=mac, phase_protocol=phase_name, freeze_on=int(freeze_on), phase=p, tap_from=t_from, tap_to=t_to,
                               n_cycles=len(store), frozen_samples=frozen, samples_to_1pct=n_within(0.01), samples_to_0p1pct=n_within(0.001))
                    for n in (0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30):
                        row["dev_pct_at_%d" % n] = round(float(tr[2 + n]) * 100, 3) if 2 + n < len(tr) else np.nan
                    T_settle.append(row)
                    if phase_name == "E" and p == "LED1" and RF_OHM[t_to] > RF_OHM[t_from]:
                        x_ms = np.arange(-2, len(tr) - 2) * 1000.0 / FS
                        axs_tr[0].plot(x_ms, tr * 100, lw=1, alpha=0.8, label="%s %s>%s" % (mac[-5:], t_from, t_to))
                        axs_tr[1].semilogy(x_ms[2:], np.maximum(np.abs(tr[2:]) * 100, 1e-3), lw=1, alpha=0.8)
            n_tr = len([r for r in T_settle if r["board_mac"] == mac and r["phase_protocol"] == phase_name and r["phase"] == "LED1"])
            n_st = len([r for r in T_steps if r["board_mac"] == mac and r["phase_protocol"] == phase_name and r["phase"] == "LED1"])
            print("  %s (%s): %d pair steps, %d transients (LED1)" % (phase_name, "freeze ON" if freeze_on else "freeze OFF", n_st, n_tr))

        # ── tables for this board ──
        for tp in TAPS:
            T_tol.append(dict(date=date, board_mac=mac, fw=cfg.get("fw"), lib=cfg.get("lib"), tap=tp, rf_nom_ohm=RF_OHM[tp],
                              eps_pct=round(eps[tp] * 100, 3) if tp in eps else np.nan, saturated=int(tp not in eps),
                              eps_fast_mean_pct=round(np.mean(eps_fast[tp]) * 100, 3) if tp in eps_fast and eps_fast[tp] else np.nan,
                              eps_fast_sd_pct=round(np.std(eps_fast[tp]) * 100, 3) if tp in eps_fast and eps_fast[tp] else np.nan,
                              eps_shift_per_mV_offset_pct=round(sens[tp], 3) if tp in sens else np.nan, i_amb_nA=round(i_amb * 1e9, 1),
                              eps_two_level_pct=round(two["eps"][tp] * 100, 3) if two and tp in two["eps"] else np.nan,
                              **({"v_off_two_level_%s_mV" % p: round(two["voff"][p] * 1e3, 3) for p in PHASES} if two else {}),
                              i_amb_extra_nA=round(two["i_extra"] * 1e9, 1) if two else np.nan,
                              **{"v_off_%s_mV" % p: round(voff[p] * 1e3, 3) for p in PHASES}, rms_resid_pct=round(rms, 3),
                              ref_drift_pct_per_min=round(drift_pct_min, 3), anchor="mean eps over measured taps = 0"))
        ax_eps.errorbar([TAPS.index(tp) + bi * 0.1 - 0.1 for tp in taps_meas], [eps[tp] * 100 for tp in taps_meas],
                        yerr=[np.std(eps_fast[tp]) * 100 if eps_fast.get(tp) else 0 for tp in taps_meas], fmt="o-", label=mac[-5:])

        # report tables
        report.append("Offset `V_off` per phase [mV]: " + ", ".join("%s %+.2f" % (p, voff[p] * 1e3) for p in PHASES)
                      + ". Reference (100K) light drift %+.2f %%/min. Fit residual %.3f %% RMS. Saturated taps: %s.\n" % (drift_pct_min, rms, ", ".join(sat_taps) or "none"))
        report.append("I_amb %.0f nA. The split between `V_off` and the ε pattern is not identifiable from one light level (a ridge picks the smallest pattern); the last column gives how much each ε moves per +1 mV of offset.\n" % (i_amb * 1e9))
        if two:
            report.append("**Two light levels** (this run, I_amb %.0f nA, joined with the 10:08 run at %.0f nA): the degeneracy is broken; `V_off` = %s; residual %.3f %% (now) / %.3f %% (extra). The ε in the table's second column are these.\n"
                          % (two["i_now"] * 1e9, two["i_extra"] * 1e9, ", ".join("%s %+.2f mV" % (p, two["voff"][p] * 1e3) for p in PHASES), two["rms_now"], two["rms_extra"]))
        report.append("| tap | ε one level, ridge (B) [%] | ε two levels [%] | ε fast (C) mean ± SD [%] | SD per sample [%] | SD of 50 ms means [%] | ε shift per +1 mV offset [%] |\n|---|---|---|---|---|---|---|")
        for tp in TAPS:
            lv = [r for r in T_levels if r["board_mac"] == mac and r["tap"] == tp and r["phase"] == "LED1" and not r["saturated"]]
            report.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                tp, "%+.2f" % (eps[tp] * 100) if tp in eps else "sat",
                "%+.2f" % (two["eps"][tp] * 100) if two and tp in two["eps"] else "—",
                "%+.2f ± %.2f" % (np.mean(eps_fast[tp]) * 100, np.std(eps_fast[tp]) * 100) if tp in eps_fast and eps_fast[tp] else "—",
                "%.3f" % np.mean([r["sd_pct"] for r in lv]) if lv else "—", "%.3f" % np.nanmean([r["sd_of_50ms_means_pct"] for r in lv]) if lv else "—",
                "%+.2f" % sens[tp] if tp in sens else "—"))
        report.append("\n| pair | OT step, toggles D (freeze on) [%] | same from ladder ε (two-level) [%] | freeze OFF: samples to 1 % / 0.1 % of step (up ; down) | deviation at sample 0 / 1 / 2 / 4 after the step [% of step] |\n|---|---|---|---|---|")
        for lo, hi in list(zip(TAPS[:-1], TAPS[1:])) + [("10K", "1M")]:
            sD = [s for s in T_steps if s["board_mac"] == mac and s["phase_protocol"] == "D" and s["phase"] == "LED1" and s["tap_from"] == lo and s["tap_to"] == hi]
            eU = [s for s in T_settle if s["board_mac"] == mac and s["phase_protocol"] == "E" and s["phase"] == "LED1" and s["tap_from"] == lo and s["tap_to"] == hi]
            eD = [s for s in T_settle if s["board_mac"] == mac and s["phase_protocol"] == "E" and s["phase"] == "LED1" and s["tap_from"] == hi and s["tap_to"] == lo]
            if not (sD or eU):
                continue
            report.append("| %s ↔ %s | %s | %s | %s | %s |" % (
                lo, hi, "%+.2f ± %.2f (n=%d)" % (sD[0]["ot_step_pct_mean"], sD[0]["ot_step_pct_sd"], sD[0]["n_cycles"]) if sD else "—",
                "%+.2f" % sD[0]["ot_step_pct_from_ladder"] if sD and np.isfinite(sD[0]["ot_step_pct_from_ladder"]) else "—",
                "%s / %s ; %s / %s" % (eU[0]["samples_to_1pct"], eU[0]["samples_to_0p1pct"], eD[0]["samples_to_1pct"], eD[0]["samples_to_0p1pct"]) if eU and eD else "—",
                "%+.1f / %+.1f / %+.1f / %+.2f" % (eU[0]["dev_pct_at_0"], eU[0]["dev_pct_at_1"], eU[0]["dev_pct_at_2"], eU[0]["dev_pct_at_4"]) if eU else "—"))

    ax_eps.set_xticks(range(len(TAPS))); ax_eps.set_xticklabels(TAPS); ax_eps.axhline(0, color="k", lw=0.5)
    ax_eps.set_ylabel("ε = real/nominal − 1 [%] (mean over taps = 0)"); ax_eps.set_title("RF tap deviation per board — slow ladder; bars = SD of the fast sweeps"); ax_eps.grid(alpha=0.3); ax_eps.legend()
    fig_eps.tight_layout(); fig_eps.savefig(os.path.join(fig_dir, "%s_eps_per_tap.png" % date), dpi=130)
    axs_tr[0].set_title("Switched-RC settling after an RF change (freeze OFF, LED1, up-steps, median of 20 cycles)")
    axs_tr[0].set_xlabel("ms after the sample where the new RF applies"); axs_tr[0].set_ylabel("remaining deviation [% of step]")
    axs_tr[0].set_xlim(-4, 30); axs_tr[0].set_ylim(-5, 105); axs_tr[0].grid(alpha=0.3); axs_tr[0].legend(fontsize=6, ncol=3)
    axs_tr[1].set_title("same, |deviation| on a log scale"); axs_tr[1].set_xlabel("ms"); axs_tr[1].set_xlim(0, 30); axs_tr[1].set_ylim(1e-3, 200); axs_tr[1].grid(alpha=0.3, which="both")
    for y, lab in ((1, "1 %"), (0.1, "0.1 %")):
        axs_tr[1].axhline(y, color="k", lw=0.6, ls="--"); axs_tr[1].text(29, y * 1.2, lab, ha="right", fontsize=8)
    axs_tr[1].axvline(8 * 1000.0 / FS, color="r", lw=0.8, ls=":"); axs_tr[1].text(16.3, 50, "library freeze\n8 samples", color="r", fontsize=8)
    fig_tr.tight_layout(); fig_tr.savefig(os.path.join(fig_dir, "%s_transients_freeze_off.png" % date), dpi=130)
    plt.close("all")
    for name, rows in (("rf_tap_levels.csv", T_levels), ("rf_tap_tolerance.csv", T_tol), ("rf_tap_steps.csv", T_steps),
                       ("rf_tap_settling.csv", T_settle), ("rf_tap_fast_sweep.csv", T_fast)):
        new = pd.DataFrame(rows)
        p = os.path.join(a.out, name)
        if os.path.exists(p) and len(new):
            old = pd.read_csv(p)
            if "date" in old and "board_mac" in old:
                old = old[~((old["date"] == date) & old["board_mac"].isin(new["board_mac"]))]
                new = pd.concat([old, new], ignore_index=True)
        new.to_csv(p, index=False, lineterminator="\n")
        print("written %s (%d rows)" % (name, len(new)))
    rp = os.path.join(a.out, "rf_tap_report_%s.md" % date)
    skeleton = "\n".join(report) + "\n\n![eps](fig/%s_eps_per_tap.png)\n\n![transients](fig/%s_transients_freeze_off.png)\n" % (date, date)
    if os.path.exists(rp) and "<!-- tables-end -->" in open(rp, encoding="utf-8").read():
        old = open(rp, encoding="utf-8").read()
        open(rp, "w", encoding="utf-8", newline="\n").write(skeleton + "\n<!-- tables-end -->" + old.split("<!-- tables-end -->", 1)[1])
    else:
        open(rp, "w", encoding="utf-8", newline="\n").write(skeleton + "\n<!-- tables-end -->\n\n## Conclusions\n\n_(to be written)_\n")
    print("report skeleton -> %s" % rp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
