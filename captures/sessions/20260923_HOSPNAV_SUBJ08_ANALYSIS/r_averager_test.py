"""EMA vs sliding window as the averager of R-METHOD-2's products (Sxy, Sxx, Syy) -- 2026-10-06.

Same causal chain as r_causal_test.py BASE (2nd-order Butterworth 0.5-5 Hz forward only,
DC = EMA 2 s, first differences k=1); only the averager of the three products changes:
    ema6   EMA tau 6 s            (library today; NaN during 3*tau warm-up, as spo2_warmup_s)
    ema3   EMA tau 3 s            (noise-matched to box6 for white noise)
    box4   rectangular 4 s        (the 3-4 s the neonatal literature points to)
    box6   rectangular 6 s window (NaN until full, like PI v0.101)
    box12  rectangular 12 s       (noise-matched to ema6)
Metrics: accuracy vs reference (stationary pairs, inst/med reads, LOSO), noise of R inside the
pairs' 8 s windows, r-gate rejection, lag of our SpO2 vs the reference stream, recovery after HGAC RF
steps (capture records "# @row N afe: cause=hgac").
"""
import csv
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt, sosfilt_zi

AN = r"C:\PRJ\MOW\PulseNest\captures\sessions\20260923_HOSPNAV_SUBJ08_ANALYSIS"
sys.path.insert(0, AN)
from r_regression_test import FS_HZ, PAIR_FILES, SESSIONS, WINDOW_S, load_session, stationary_mask  # noqa: E402
from r_causal_test import ema, evaluate, loso  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r_averager_summary.txt")   # lives next to r_causal_test.py since 2026-10-07
CURVE = (123.98, -39.13)          # R-CURVE-STS0163-HOSPNAV-20260923 (R-METHOD-2)
R_GATE = 0.8
AVG = [("ema6", "ema", 6.0), ("ema3", "ema", 3.0), ("box4", "box", 4.0),
       ("box6", "box", 6.0), ("box12", "box", 12.0)]


def box(v, T):
    n = int(round(T * FS_HZ))
    c = np.cumsum(np.concatenate([[0.0], v]))
    out = np.full(len(v), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def avg(v, kind, T):
    if kind == "box":
        return box(v, T)
    o = ema(v, T)
    o[: int(3 * T * FS_HZ)] = np.nan
    return o


def products(s):
    sos = butter(2, (0.5, 5.0), btype="bandpass", fs=FS_HZ, output="sos")
    zi = sosfilt_zi(sos)
    xs = []
    for ch in ("ir", "red"):
        v = s[ch]
        dc = ema(v, 2.0, v[0])
        bp = sosfilt(sos, v, zi=zi * v[0])[0]
        with np.errstate(divide="ignore", invalid="ignore"):
            xs.append(np.where(dc > 0, bp / dc, 0.0))
    x, y = xs
    dx = np.concatenate([[0.0], np.diff(x)])
    dy = np.concatenate([[0.0], np.diff(y)])
    return dx * dy, dx * dx, dy * dy


def r_streams(pxy, pxx, pyy):
    out = {}
    for name, kind, T in AVG:
        sxy, sxx, syy = avg(pxy, kind, T), avg(pxx, kind, T), avg(pyy, kind, T)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[name] = (sxy / sxx, sxy / np.sqrt(sxx * syy))
    return out


def hgac_rows(session_dir):
    rows, base = [], 0
    for path in sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv"))):
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    if line.startswith("# @row ") and "cause=hgac" in line:
                        rows.append(base + int(line.split()[2]))
                elif line.strip():
                    n += 1
        base += n - 1        # minus the header line
    return rows


def main():
    pairs = {}
    for subj, pf in PAIR_FILES.items():
        for p in csv.DictReader(open(pf, encoding="utf-8")):
            if p["usable"] == "1":
                pairs.setdefault(p["session"], []).append((subj, p))
    rows, lag_rows, step_rows = [], [], []
    gate = {a[0]: [0, 0] for a in AVG}
    for name, plist in sorted(pairs.items()):
        sdir = os.path.join(SESSIONS, name)
        s = load_session(sdir)
        st = r_streams(*products(s))
        on = np.isin(s["ps"], (1, 2))
        for a, (R, r) in st.items():
            m = on & np.isfinite(r)
            gate[a][0] += int((r[m] < R_GATE).sum())
            gate[a][1] += int(m.sum())
        # accuracy + noise at the reference pairs
        for subj, p in plist:
            t1 = float(p["t_epoch_us"])
            i0 = np.searchsorted(s["t"], t1 - WINDOW_S * 1e6, side="right")
            i1 = np.searchsorted(s["t"], t1, side="right")
            row = {"subj": subj, "session": name, "t": t1, "ref": float(p["ref_spo2"])}
            for a, (R, r) in st.items():
                w = R[i0:i1]
                w = w[np.isfinite(w)]
                row[a + "|med"] = np.median(w) if len(w) else np.nan
                row[a + "|inst"] = R[i1 - 1] if i1 > i0 else np.nan
                row[a + "|sd"] = np.std(w) if len(w) > 100 else np.nan
            rows.append(row)
        # lag of our SpO2 (curve on R) vs the reference stream, all usable pairs of the session
        tref = np.array([float(p["t_epoch_us"]) for _, p in plist])
        yref = np.array([float(p["ref_spo2"]) for _, p in plist])
        o = np.argsort(tref)
        tref, yref = tref[o], yref[o]
        if len(tref) >= 60:
            for a, (R, r) in st.items():
                best = None
                for L in np.arange(0.0, 30.5, 0.5):
                    idx = np.searchsorted(s["t"], tref + L * 1e6, side="right") - 1
                    ok = (idx >= 0) & (idx < len(R))
                    ours = np.full(len(tref), np.nan)
                    ours[ok] = CURVE[0] + CURVE[1] * R[idx[ok]]
                    m = np.isfinite(ours)
                    if m.sum() < 30:
                        continue
                    d = ours[m] - yref[m]
                    d = d - np.median(d)          # bias removed: shape and lag only
                    rms = float(np.sqrt(np.mean(d * d)))
                    if best is None or rms < best[1]:
                        best = (L, rms)
                if best:
                    lag_rows.append((name, a, best[0], best[1], len(tref)))
        # recovery after each HGAC RF step
        steps = hgac_rows(sdir)
        for row0 in steps:
            pre0, pre1 = row0 - int(5 * FS_HZ), row0 - int(0.2 * FS_HZ)
            end = row0 + int(40 * FS_HZ)
            if pre0 < 0 or end > len(s["t"]) or not on[pre0:end].all():
                continue
            for a, (R, r) in st.items():
                Rpre = np.nanmedian(R[pre0:pre1])
                if not np.isfinite(Rpre):
                    continue
                seg, rseg = R[row0:end], r[row0:end]
                dev = np.abs(seg - Rpre) * abs(CURVE[1])             # SpO2 points
                bad = (dev > 1.0) | (rseg < R_GATE) | ~np.isfinite(seg)
                t_rec = (np.max(np.nonzero(bad)[0]) + 1) / FS_HZ if bad.any() else 0.0
                n20 = int(20 * FS_HZ)
                step_rows.append((name, a, t_rec, float(np.nanmax(dev[:n20])), float(np.nanmin(rseg[:n20]))))
        print(name, len(plist), "pairs;", len(steps), "hgac steps", flush=True)

    df = pd.DataFrame(rows)
    df["stat"] = stationary_mask(df["session"].to_numpy(), df["t"].to_numpy(), df["ref"].to_numpy())
    stn = df[df["stat"]]
    L = ["stationary pairs %d; curve SpO2 = %.2f %+.2f*R; gate r >= %.1f" % (len(stn), CURVE[0], CURVE[1], R_GATE), ""]
    L.append("%-9s %-4s %6s %17s %7s %17s %17s" % ("averager", "read", "rho", "pooled fit", "scatter", "fit SUBJ08", "fit SUBJ09"))
    for a, *_ in AVG:
        for read in ("inst", "med"):
            rho, A, B, scat, fits = evaluate(stn, a + "|" + read)
            f8, f9 = fits["SUBJ08"], fits["SUBJ09"]
            L.append("%-9s %-4s %+6.2f %7.2f %+7.2fR  %7.2f %7.2f %+7.2fR %7.2f %+7.2fR"
                     % (a, read, rho, A, B, scat, f8[0], f8[1], f9[0], f9[1]))
    L += ["", "--- leave-one-subject-out (inst) ---"]
    for a, *_ in AVG:
        L += [a + ":"] + ["    " + x for x in loso(stn, a + "|inst")]
    L += ["", "--- noise: SD of R inside the 8 s window of each stationary pair, in SpO2 pts (median / p90 over pairs) ---"]
    for a, *_ in AVG:
        sd = stn[a + "|sd"].to_numpy() * abs(CURVE[1])
        sd = sd[np.isfinite(sd)]
        L.append("%-9s %5.2f / %5.2f pts" % (a, np.median(sd), np.percentile(sd, 90)))
    L += ["", "--- r gate: share of probe-applied samples with r < 0.8 (all sessions) ---"]
    for a, *_ in AVG:
        L.append("%-9s %5.2f %%" % (a, 100.0 * gate[a][0] / max(gate[a][1], 1)))
    L += ["", "--- lag of our SpO2 vs the reference stream (bias removed): best shift [s] and RMS [pts], per session ---"]
    lr = pd.DataFrame(lag_rows, columns=["session", "avg", "lag", "rms", "n"])
    for a, *_ in AVG:
        g = lr[lr.avg == a]
        per = "  ".join("%s:%.1fs/%.2f" % (r.session[9:13], r.lag, r.rms) for r in g.itertuples())
        L.append("%-9s median lag %4.1f s  mean RMS %4.2f   %s" % (a, g.lag.median(), g.rms.mean(), per))
    nsteps = len(step_rows) // len(AVG)
    L += ["", "--- recovery after HGAC RF steps (%d steps with 5 s before / 40 s after fully applied) ---" % nsteps,
          "    recovery = time until SpO2 deviation <= 1 pt AND r >= gate for the rest of the 40 s; max dev and min r in the first 20 s"]
    sr = pd.DataFrame(step_rows, columns=["session", "avg", "t_rec", "maxdev", "minr"])
    for a, *_ in AVG:
        g = sr[sr.avg == a]
        L.append("%-9s recovery median %5.1f s  p90 %5.1f s | max dev median %5.2f pts p90 %5.2f | min r median %.3f"
                 % (a, g.t_rec.median(), g.t_rec.quantile(0.9), g.maxdev.median(), g.maxdev.quantile(0.9), g.minr.median()))
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
