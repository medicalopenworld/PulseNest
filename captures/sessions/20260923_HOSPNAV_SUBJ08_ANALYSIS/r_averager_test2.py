"""Second pass on r_averager_test.py: signed lag vs the reference (our SpO2 may LEAD the hospital
monitor, which averages too) and settling to the POST-step level after each HGAC RF step."""
import csv
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r_averager_test import AVG, CURVE, FS_HZ, PAIR_FILES, R_GATE, SESSIONS, hgac_rows, load_session, products, r_streams  # noqa: E402

OUT = os.path.join(HERE, "r_averager_summary2.txt")


def main():
    pairs = {}
    for subj, pf in PAIR_FILES.items():
        for p in csv.DictReader(open(pf, encoding="utf-8")):
            if p["usable"] == "1":
                pairs.setdefault(p["session"], []).append((subj, p))
    lag_rows, step_rows, detail = [], [], []
    for name, plist in sorted(pairs.items()):
        sdir = os.path.join(SESSIONS, name)
        s = load_session(sdir)
        st = r_streams(*products(s))
        on = np.isin(s["ps"], (1, 2))
        tref = np.array([float(p["t_epoch_us"]) for _, p in plist])
        yref = np.array([float(p["ref_spo2"]) for _, p in plist])
        o = np.argsort(tref)
        tref, yref = tref[o], yref[o]
        # only sessions where the reference actually moves (range >= 6 pts) can resolve a lag
        if len(tref) >= 300 and np.ptp(yref) >= 6:
            for a, (R, r) in st.items():
                res = []
                for L in np.arange(-30.0, 30.5, 0.5):
                    idx = np.searchsorted(s["t"], tref + L * 1e6, side="right") - 1
                    ok = (idx >= 0) & (idx < len(R))
                    ours = np.full(len(tref), np.nan)
                    ours[ok] = CURVE[0] + CURVE[1] * R[idx[ok]]
                    m = np.isfinite(ours)
                    if m.sum() < 100:
                        continue
                    d = ours[m] - yref[m]
                    d = d - np.median(d)
                    res.append((L, float(np.sqrt(np.mean(d * d)))))
                res = np.array(res)
                k = int(np.argmin(res[:, 1]))
                # width of the minimum: lags within +2 % RMS of the best
                near = res[res[:, 1] <= res[k, 1] * 1.02, 0]
                lag_rows.append((name, a, res[k, 0], res[k, 1], near.min(), near.max(), len(tref), float(np.ptp(yref))))
        for j, row0 in enumerate(hgac_rows(sdir)):
            pre0, pre1 = row0 - int(5 * FS_HZ), row0 - int(0.2 * FS_HZ)
            end = row0 + int(40 * FS_HZ)
            if pre0 < 0 or end > len(s["t"]) or not on[pre0:end].all():
                continue
            for a, (R, r) in st.items():
                seg, rseg = R[row0:end], r[row0:end]
                Rpre = np.nanmedian(R[pre0:pre1])
                Rpost = np.nanmedian(seg[int(30 * FS_HZ):])
                if not (np.isfinite(Rpre) and np.isfinite(Rpost)):
                    continue
                dev = np.abs(seg - Rpost) * abs(CURVE[1])
                bad = (dev > 1.0) | (rseg < R_GATE) | ~np.isfinite(seg)
                t_set = (np.max(np.nonzero(bad)[0]) + 1) / FS_HZ if bad.any() else 0.0
                n20 = int(20 * FS_HZ)
                step_rows.append((name, j, a, t_set, float(np.nanmax(dev[:n20])), float(np.nanmin(rseg[:n20])),
                                  (Rpost - Rpre) * CURVE[1]))
                if a in ("ema6", "box6", "box12"):
                    # SpO2 trace at 1 s steps for the first 25 s, relative to the post level
                    tr = [(seg[int(k * FS_HZ)] - Rpost) * CURVE[1] for k in range(0, 25, 1)]
                    detail.append((name[9:13], j, a, " ".join("%+5.1f" % v for v in tr)))
        print(name, flush=True)

    L = ["--- signed lag of our SpO2 vs the reference (bias removed); negative = ours LEADS the monitor ---",
         "    per session: best lag / RMS [pts] / lags within 2 % of the best RMS; sessions with reference range >= 6 pts"]
    lr = pd.DataFrame(lag_rows, columns=["session", "avg", "lag", "rms", "lo", "hi", "n", "range"])
    for a, *_ in AVG:
        g = lr[lr.avg == a]
        per = "  ".join("%s:%+.1fs/%.2f[%+.0f,%+.0f]" % (r.session[9:13] + r.session[-2:], r.lag, r.rms, r.lo, r.hi) for r in g.itertuples())
        L.append("%-9s median lag %+5.1f s   %s" % (a, g.lag.median(), per))
    sr = pd.DataFrame(step_rows, columns=["session", "step", "avg", "t_set", "maxdev", "minr", "shift"])
    nsteps = sr.step.nunique() if len(sr) else 0
    L += ["", "--- settling to the POST-step level after HGAC RF steps (%d steps) ---" % (len(sr) // max(len(AVG), 1)),
          "    t_set = last instant with |SpO2 - post level| > 1 pt or r < gate within 40 s; max dev / min r in the first 20 s;",
          "    shift = post - pre level in SpO2 pts (what the RF step did to R permanently)"]
    for a, *_ in AVG:
        g = sr[sr.avg == a]
        L.append("%-9s t_set median %5.1f s  p90 %5.1f s | max dev median %5.2f pts p90 %5.2f | min r median %.3f | shift median %+5.2f pts (|shift| p90 %.2f)"
                 % (a, g.t_set.median(), g.t_set.quantile(0.9), g.maxdev.median(), g.maxdev.quantile(0.9),
                    g.minr.median(), g["shift"].median(), g["shift"].abs().quantile(0.9)))
    L += ["", "--- per step, SpO2 relative to the post level, 1 s steps from the RF change (first 25 s) ---"]
    for d in detail:
        L.append("%s step %d %-6s %s" % d)
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
