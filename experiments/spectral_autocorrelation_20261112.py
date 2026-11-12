"""Autocorrelation of the HR3 spectrum along frequency: does it see the harmonic comb the eye sees?

Why this exists
---------------
Alex (2026-11-12) looked at the spectrograms of SUBJ08-11 (tools/spo2_spectra.py: dB, top 60 dB,
magma) and sees the fundamental plus >= 3 harmonics over a dark background wherever the PPG is the
arterial pulse, and other components where it is not. The HPS reads three bins per candidate
(k, 2k, 3k) and never looks at the darkness between the teeth. Proposal: autocorrelate the spectrum
along the frequency axis, so the lag of the maximum is the tooth spacing (the pulse rate) and the
height of the maximum says how comb-like the whole 0.5-15 Hz band is. Prior art: spectral
autocorrelation and the cepstrum in speech pitch detection; Datex-Ohmeda US 7,139,599 (cepstral
domain pulse oximetry, expired).

What it does
------------
Same sessions, HR3 front end, references and SpO2 artefact gate as
experiments/hr3_spectral_variants_20261021.py (loaded from its file, not copied, so the numbers
are comparable with that report). Per HR3 window (512 samples at 50 Hz, every 0.5 s), on the band
0.49-14.94 Hz (bins 5..153), rho[d] is the correlation of a sequence with itself shifted d bins:

  lin      cosine similarity of the linear power P[k]
  logD     L = clip(10 log10 P, Lmax - D, Lmax) - (Lmax - D); cosine similarity of L   (black = 0)
  logzD    Pearson correlation of L                                (mean removed: valleys count)
  logcM    local contrast: C = clip(10 log10 P - median over +-8 bins - M dB, 0, cap); Pearson
           correlation of C. logc6 = margin 6 dB, cap 30 dB; logc10 = margin 10; logc6h15 = cap 15.

Lmax is the window's maximum inside the band; D = 30, 40, 60 dB. The three first families are the
proposal; the local contrast was added after the first run on SUBJ10 (the tilt of the spectrum
correlates with itself at every small lag). The estimate is the lag of a local maximum of rho
inside 27-263 bpm: 'first' = the smallest lag whose maximum is >= ALPHA of the highest one (the
comb also correlates at 2 f0, 3 f0), 'max' = the highest. Parabolic interpolation. The quality
index is rho at that lag.

Comb purity (also added): the fraction of the band's LINEAR power inside the teeth n * f0 +- 3
bins at the rate logc6 found, rescaled so that a flat spectrum gives 0.

    python experiments/spectral_autocorrelation_20261112.py [--out DIR] [--cache DIR]
                                [--subjects ...] [--replay replay_lib0.108] [--no-figs] [--no-gate]

Outputs in --out (default captures/sessions/SPECTRAL_ACF_20261112/, not versioned): summary.csv
(subject x estimator), comb_vs_hr3.csv (subject: availability under a rho threshold and the windows
where today's HR3 is contradicted by the comb), gate.csv (subject x validity rule, the SpO2 gate of
2026-10-20), ms100.csv (plateau x estimator), one PNG per session (spectrogram, local contrast,
HPS, rho against lag, rates, quality indices). --cache (default <out>/cache) keeps each session's
spectra and board columns, about 400 MB for the 19 sessions; delete it at will.

Result (2026-11-12; report: docs/spectral_autocorrelation_20261112.md)
------
- Baseline reproduced: SUBJ10 gate 'HR3 valid' 2.6 % published / Arms 2.05, no gate 81.8 % / 16.25.
- As proposed (lin, logD, logzD) the rate is right on clean windows (94-99.9 % of the HR1 = HR2
  consensus windows of SUBJ08/09/11; log60 without mean removal 38-63 %) but rho does not
  discriminate: SUBJ10 gate 77-80 % published / Arms 16 for every threshold up to 0.7.
- With the local contrast (logc6, first maximum): 99.1 / 99.5 / 100.0 % right on the consensus
  windows of SUBJ08 / SUBJ09 / SUBJ11 (HR3 today 89.5 / 92.5 / 90.2, B1 95.8 / 95.8 / 96.2), no
  double or half readings; a rate with rho >= 0.7 in 89 / 88 / 26 / 99 % of the applied windows of
  SUBJ08-11 (HR3 today 69 / 71 / 7 / 88). MS100: 100 % from 60 to 240 bpm, 0 % at 30 bpm (teeth 5
  bins apart, no darkness between them). With 'max' instead of 'first' the MS100 reads double at
  60-120 bpm.
- rho is not an SpO2 gate: it says a pulse is visible, not that the signal is clean (SUBJ10,
  rho >= 0.8: 5.4 % published, bias -7.95). The comb purity is: rho >= 0.5 and purity >= 0.3 gives
  54.3 % / 2.36, 85.9 % / 2.40, 3.2 % / 2.36, 95.9 % / 1.30 (published / Arms, SUBJ08-11) against
  today's 52.5 / 2.47, 80.3 / 2.39, 2.6 / 2.05, 93.1 / 1.23, and Arms falls steadily as the purity
  threshold rises in SUBJ08 and SUBJ09.
- Today's HR3 publishes one third of the pulse rate (55-58 bpm against the comb's 166-174) in
  6.4 / 4.5 / 19.2 / 5.8 % of its valid windows of SUBJ08-11; those windows pass the gate. No
  numeric reference there (ratio 3.0 and three spectrograms inspected).
- Nothing adopted; Alex's call.
"""
import argparse
import csv
import datetime
import glob
import importlib.util
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import spo2_bias_analysis as B   # noqa: E402
from pulsenest import session_events        # noqa: E402

# the 2026-10-21 study's front end, references and gate, from its file (experiments is not a package)
_spec = importlib.util.spec_from_file_location(
    "hr3_spectral_variants_20261021",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "hr3_spectral_variants_20261021.py"))
hv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hv)

SUBJECTS = ("SUBJ08", "SUBJ09", "SUBJ10", "SUBJ11", "SUBJ90")
F_LO_HZ, F_HI_HZ = 0.49, 15.0
D_MAX_FIG_HZ = 7.5            # lags computed and drawn (half the band)
ALPHA = 0.8                   # 'first' picker: smallest lag whose local maximum is >= ALPHA * highest
DYN_DB = (30.0, 40.0, 60.0)
THRESHOLDS = (0.3, 0.5, 0.7, 0.8, 0.9)
CONTRAST_HALF_W = 8           # bins each side for the local median (as WHITEN_HALF_W on 2026-10-21)
CONTRAST_VARIANTS = {"logc6": (6.0, 30.0), "logc10": (10.0, 30.0), "logc6h15": (6.0, 15.0)}   # margin, cap [dB]
TOOTH_HALF_W = 3              # bins each side of n * f0 counted as the tooth (Hann main lobe +-2, +1)
GATE_VARIANTS = ("lin", "log40", "logz40", "logc6", "logc10", "logc6h15")
FIG_VARIANT = "logc6"
HR3_TODAY = "HR3 today (HPS3 + SQI>0)"
B1 = "B1 (HPS2 + SQI>0)"
CACHE_KEYS = ("HR1", "HR2", "HR3", "HR3_SQI", "ps", "t")


# ============================================================================= lag correlations

def cosine_lags(Z, d_max):
    """R[w, d] = sum Z[k] Z[k+d] / sqrt(sum Z[k]^2 * sum Z[k+d]^2) over the overlap."""
    W, N = Z.shape
    R = np.zeros((W, d_max + 1))
    c2 = np.concatenate([np.zeros((W, 1)), np.cumsum(Z * Z, axis=1)], axis=1)
    for d in range(d_max + 1):
        num = (Z[:, :N - d] * Z[:, d:]).sum(axis=1)
        den = np.sqrt((c2[:, N - d] - c2[:, 0]) * (c2[:, N] - c2[:, d]))
        R[:, d] = np.divide(num, den, out=np.zeros(W), where=den > 0)
    return R


def pearson_lags(Z, d_max):
    """R[w, d] = Pearson correlation of Z[k] and Z[k+d] over the overlap (each side's own mean)."""
    W, N = Z.shape
    R = np.zeros((W, d_max + 1))
    c1 = np.concatenate([np.zeros((W, 1)), np.cumsum(Z, axis=1)], axis=1)
    c2 = np.concatenate([np.zeros((W, 1)), np.cumsum(Z * Z, axis=1)], axis=1)
    for d in range(d_max + 1):
        n = N - d
        sa, sb = c1[:, N - d] - c1[:, 0], c1[:, N] - c1[:, d]
        qa, qb = c2[:, N - d] - c2[:, 0], c2[:, N] - c2[:, d]
        num = (Z[:, :N - d] * Z[:, d:]).sum(axis=1) - sa * sb / n
        den = np.sqrt(np.maximum(qa - sa * sa / n, 0.0) * np.maximum(qb - sb * sb / n, 0.0))
        R[:, d] = np.divide(num, den, out=np.zeros(W), where=den > 1e-12)
    return R


def log_clip(Pb, dyn_db):
    """Height above the black level, in dB: 0 = at or below Lmax - dyn_db, dyn_db = the band maximum."""
    L = 10.0 * np.log10(np.maximum(Pb, 1e-30))
    top = L.max(axis=1, keepdims=True)
    return np.clip(L - (top - dyn_db), 0.0, dyn_db)


def local_contrast(P, b_lo, b_hi, margin_db, cap_db):
    """dB by which each bin stands out of its neighbourhood: L - moving median(L, +-CONTRAST_HALF_W)
    - margin, clipped to [0, cap]. A noise bin exceeds its local median by 6.4 dB 5 % of the time
    (exponential periodogram), so margin 6 dB blanks the floor; the cap keeps the fundamental from
    outweighing the harmonics (the eye's compression)."""
    L = 10.0 * np.log10(np.maximum(P[:, 1:b_hi + CONTRAST_HALF_W + 1], 1e-30))
    floor = hv.local_median(L, CONTRAST_HALF_W)
    C = np.clip(L - floor - margin_db, 0.0, cap_db)
    return C[:, b_lo - 1:b_hi]


def variants(P, b_lo, b_hi, d_max):
    Pb = P[:, b_lo:b_hi + 1]
    out, contrast = {"lin": cosine_lags(Pb, d_max)}, {}
    for dyn in DYN_DB:
        L = log_clip(Pb, dyn)
        out[f"log{dyn:.0f}"] = cosine_lags(L, d_max)
        out[f"logz{dyn:.0f}"] = pearson_lags(L, d_max)
    for name, (margin, cap) in CONTRAST_VARIANTS.items():
        contrast[name] = local_contrast(P, b_lo, b_hi, margin, cap)
        out[name] = pearson_lags(contrast[name], d_max)
    return out, contrast


def pick(R, s_min, s_max, alpha, bin_res):
    """Per window: (HR bpm or NaN, rho at the chosen lag). Local maxima of R inside [s_min, s_max]."""
    W = R.shape[0]
    d = np.arange(s_min, s_max + 1)
    c, lft, rgt = R[:, d], R[:, d - 1], R[:, d + 1]
    loc = (c > lft) & (c >= rgt) & (c > 0)
    cm = np.where(loc, c, -np.inf)
    rmax = cm.max(axis=1)
    has = np.isfinite(rmax)
    cand = loc & (c >= alpha * np.where(has, rmax, 0.0)[:, None])
    j = np.argmax(cand, axis=1)
    rows = np.arange(W)
    pc, pl, pr = c[rows, j], lft[rows, j], rgt[rows, j]
    den = pl - 2 * pc + pr
    delta = np.where(den < 0, 0.5 * (pl - pr) / np.where(den < 0, den, -1.0), 0.0)
    delta = np.clip(delta, -0.5, 0.5)
    hr = 60.0 * (d[j] + delta) * bin_res
    ok = has & (hr >= hv.HR_MIN) & (hr <= hv.HR_MAX)
    return np.where(ok, hr, np.nan), np.where(ok, pc, 0.0)


def comb_purity(P, hr, bin_res, b_lo, b_hi):
    """Fraction of the band's LINEAR power inside the teeth of the comb at the estimated rate
    (n * f0 +- TOOTH_HALF_W bins, every n inside the band), rescaled so that a flat spectrum gives 0:
    (fraction - covered bins / band bins) / (1 - covered bins / band bins)."""
    W, nb = P.shape
    lag = np.where(np.isfinite(hr), hr / 60.0 / bin_res, np.nan)
    mask = np.zeros((W, nb), dtype=bool)
    n_max = int(b_hi // 5) + 1
    rows = np.arange(W)
    for n in range(1, n_max + 1):
        c = np.where(np.isfinite(lag), np.rint(n * np.where(np.isfinite(lag), lag, 0.0)), -1).astype(int)
        for off in range(-TOOTH_HALF_W, TOOTH_HALF_W + 1):
            k = c + off
            ok = (c > 0) & (k >= b_lo) & (k <= b_hi)
            mask[rows[ok], k[ok]] = True
    band = P[:, b_lo:b_hi + 1]
    mb = mask[:, b_lo:b_hi + 1]
    tot = band.sum(axis=1)
    frac = np.divide((band * mb).sum(axis=1), tot, out=np.zeros(W), where=tot > 0)
    base = mb.sum(axis=1) / band.shape[1]
    pur = np.where(base < 0.999, (frac - base) / np.where(base < 0.999, 1.0 - base, 1.0), 0.0)
    return np.where(np.isfinite(hr), np.clip(pur, 0.0, 1.0), 0.0)


# ============================================================================= session

def load_session(sd, cache_dir):
    """Board columns, the HR3 spectra of every window and their last rows; cached per session
    (parsing the CSV parts takes most of the run)."""
    cp = os.path.join(cache_dir, os.path.basename(sd) + ".npz")
    if os.path.exists(cp):
        z = np.load(cp)
        d = {k: z[k] for k in CACHE_KEYS}
        d["fs"] = float(z["fs"])
        return d, z["P"], z["end_rows"], float(z["rate"])
    d = hv.parse_parts(sd)
    P, end_rows, rate = hv.spectra(d)
    np.savez(cp, P=P, end_rows=end_rows, rate=rate, fs=d["fs"], **{k: d[k] for k in CACHE_KEYS})
    return d, P, end_rows, rate


def with_gaps(x, cols, hop):
    """Insert NaN columns where consecutive windows are more than 1.5 hops apart (nearest shading
    would otherwise stretch the neighbours across the gap)."""
    xs, cs = [x[0]], [cols[:, 0]]
    nan = np.full(cols.shape[0], np.nan)
    for i in range(1, len(x)):
        if x[i] - x[i - 1] > 1.5 * hop:
            xs += [x[i - 1] + hop, x[i] - hop]; cs += [nan, nan]
        xs.append(x[i]); cs.append(cols[:, i])
    return np.array(xs), np.stack(cs, axis=1)


def figure(path, name, t_end_us, P, bin_res, R, hr0, sqi0, hr_r, rho_r, ref, C, b_lo, pur):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    x = mdates.date2num([datetime.datetime.fromtimestamp(v / 1e6) for v in t_end_us])
    hop = 0.5 / 86400.0
    f = np.arange(P.shape[1]) * bin_res
    fm = f <= F_HI_HZ
    fig, axes = plt.subplots(6, 1, figsize=(18, 18), sharex=True,
                             gridspec_kw={"height_ratios": [3, 3, 2.2, 3, 1.6, 1.4]})
    dB = 10 * np.log10(np.maximum(P[:, fm], 1e-30)).T
    vmax = np.percentile(dB, 99.5)
    xg, cg = with_gaps(x, dB, hop)
    axes[0].pcolormesh(xg, f[fm], cg, shading="nearest", cmap="magma", vmin=vmax - 60, vmax=vmax)
    axes[0].set_title("IR (OT_LED1) power spectrogram, 10.24 s Hann windows every 0.5 s, dB (top 60 dB)", fontsize=10)
    axes[0].set_ylabel("Hz"); axes[0].set_ylim(0, F_HI_HZ)
    margin, cap = CONTRAST_VARIANTS[FIG_VARIANT]
    fc = (b_lo + np.arange(C.shape[1])) * bin_res
    xg, cg = with_gaps(x, C.T, hop)
    axes[1].pcolormesh(xg, fc, cg, shading="nearest", cmap="magma", vmin=0, vmax=cap)
    axes[1].set_title(f"Local contrast ({FIG_VARIANT}): dB above the median of the +-{CONTRAST_HALF_W} neighbouring bins, "
                      f"minus {margin:.0f} dB, clipped to 0-{cap:.0f} dB (what the autocorrelation reads)", fontsize=10)
    axes[1].set_ylabel("Hz"); axes[1].set_ylim(0, F_HI_HZ)
    k_max = (hv.BUF_LEN // 2) // 3
    k = np.arange(1, k_max + 1)
    H = np.zeros((P.shape[0], k_max + 1)); H[:, 1:] = P[:, k] * P[:, 2 * k] * P[:, 3 * k]
    fk = np.arange(k_max + 1) * bin_res
    band = (fk >= 0.5) & (fk <= 260 / 60)
    Hn = 10 * np.log10(np.maximum(H, 1e-300) / np.maximum(H[:, band].max(axis=1, keepdims=True), 1e-300)).T
    xg, cg = with_gaps(x, Hn, hop)
    axes[2].pcolormesh(xg, fk, cg, shading="nearest", cmap="magma", vmin=-40, vmax=0)
    axes[2].set_title("HPS = P[k] P[2k] P[3k], dB below each column's maximum inside 0.5-4.33 Hz", fontsize=10)
    axes[2].set_ylabel("Hz"); axes[2].set_ylim(0, D_MAX_FIG_HZ)
    lag = np.arange(R.shape[1]) * bin_res
    xg, cg = with_gaps(x, R.T, hop)
    axes[3].pcolormesh(xg, lag, cg, shading="nearest", cmap="magma", vmin=0, vmax=1)
    for yb in (0.5, 260 / 60):
        axes[3].axhline(yb, color="lime", lw=0.6, ls=":", alpha=0.8)
    axes[3].set_title(f"rho[d] ({FIG_VARIANT}): Pearson correlation of the local contrast with itself shifted d "
                      "(0 = black, 1 = yellow; dotted: 30-260 bpm)", fontsize=10)
    axes[3].set_ylabel("lag d [Hz]"); axes[3].set_ylim(0, D_MAX_FIG_HZ)
    ax = axes[4]
    ax.plot(x, hr0, ".", ms=2.5, color="tab:green", label="HR3 today (HPS, published while SQI > 0)")
    ax.plot(x, np.where(rho_r >= 0.5, hr_r, np.nan), ".", ms=2.0, color="tab:orange",
            label=f"rate from rho ({FIG_VARIANT}, first maximum), shown while rho >= 0.5")
    ax.plot(x, ref, ".", ms=1.2, color="k", alpha=0.6, label="reference (HR1 = HR2 within 3 %, or MS100 setting)")
    ax.set_ylim(0, 270); ax.set_ylabel("bpm"); ax.grid(True, alpha=0.3); ax.legend(loc="upper right", fontsize=8, ncol=3)
    ax = axes[5]
    ax.plot(x, rho_r, "-", lw=0.7, color="tab:orange", label=f"rho at the chosen lag ({FIG_VARIANT})")
    ax.plot(x, pur, "-", lw=0.7, color="tab:blue", label="comb purity (linear power inside the teeth)")
    ax.plot(x, sqi0, "-", lw=0.7, color="tab:green", label="HR3 SQI today")
    ax.set_ylim(-0.02, 1.02); ax.set_ylabel("quality"); ax.grid(True, alpha=0.3); ax.legend(loc="upper right", fontsize=8, ncol=3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.set_xlabel("local wall-clock time of each window's last sample [HH:MM:SS]")
    fig.suptitle(f"{name}: spectrum, HPS and autocorrelation of the spectrum along frequency", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ============================================================================= main

def pct(mask, of=None):
    n = len(mask) if of is None else int(of.sum())
    return round(100.0 * float(mask.sum()) / n, 1) if n else math.nan


def write_csv(path, rows):
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(B.SESSIONS_DIR, "SPECTRAL_ACF_20261112"))
    ap.add_argument("--cache", default=None, help="default: <out>/cache")
    ap.add_argument("--replay", default="replay_lib0.108")
    ap.add_argument("--subjects", nargs="*", default=list(SUBJECTS))
    ap.add_argument("--no-figs", action="store_true")
    ap.add_argument("--no-gate", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    cache = args.cache or os.path.join(args.out, "cache")
    os.makedirs(cache, exist_ok=True)

    acc, gate_acc, plateau_rows = {}, {}, []
    est_names = None
    for subject in args.subjects:
        for sd in sorted(glob.glob(os.path.join(B.SESSIONS_DIR, subject, f"{subject}_*_20*"))):
            if not os.path.exists(os.path.join(sd, "reference_spo2.csv")):
                continue
            name = os.path.basename(sd)
            d, P, end_rows, rate = load_session(sd, cache)
            if P.shape[0] == 0:
                print(f"  {name}: no HR3 window"); continue
            factor = int(round(d["fs"] / rate))
            bin_res = rate / hv.BUF_LEN
            k_max = (hv.BUF_LEN // 2) // 3
            t_end = d["t"][end_rows]
            if subject in hv.MS100_SUBJECTS:
                ref = np.full(len(end_rows), np.nan); art = np.zeros(len(end_rows), dtype=bool)
                plats = hv.ms100_plateaus(sd)
                for t0, t1, pr in plats:
                    ref[(t_end >= t0) & (t_end <= t1)] = pr
            else:
                ref, art = hv.consensus_reference(d, end_rows, factor)
                plats = []
            # today's HR3 and the 2-harmonic product (B1), the library's peak search and SQI
            comb = hv.combine((P, P, P), k_max, False)
            est = {}
            for b_name, label in (("B0 HPS3", HR3_TODAY), ("B1 HPS2", B1)):
                C, Cs = comb[b_name]
                est[label] = hv.estimate(P, C, Cs, rate)
            # autocorrelation of the spectrum along frequency
            b_lo = int(math.ceil(F_LO_HZ / bin_res)); b_hi = int(math.floor(F_HI_HZ / bin_res))
            d_max = int(math.ceil(D_MAX_FIG_HZ / bin_res))
            s_min = max(2, int(math.ceil((hv.HR_MIN - hv.HR_GUARD) / 60.0 / bin_res)))
            s_max = int(math.floor((hv.HR_MAX + hv.HR_GUARD) / 60.0 / bin_res))
            Rs, contrast = variants(P, b_lo, b_hi, d_max)
            for v, R in Rs.items():
                est[f"{v} first"] = pick(R, s_min, s_max, ALPHA, bin_res)
                est[f"{v} max"] = pick(R, s_min, s_max, 1.0, bin_res)
            hr0, sqi0 = est[HR3_TODAY]
            hr_r, rho_r = est[f"{FIG_VARIANT} first"]
            pur = comb_purity(P, hr_r, bin_res, b_lo, b_hi)
            est[f"purity @ {FIG_VARIANT}"] = (hr_r, pur)
            est_names = list(est)
            st = acc.setdefault(subject, {"ref": [], "art": [], "est": {e: ([], []) for e in est_names}})
            st["ref"].append(ref); st["art"].append(art)
            for e, (hr, q) in est.items():
                st["est"][e][0].append(hr); st["est"][e][1].append(q)
            m = np.isfinite(hr0)
            agree = np.abs(hr_r[m] / hr0[m] - 1) <= hv.OK_REL
            print(f"  {name}: {len(end_rows)} windows, ref {int(np.isfinite(ref).sum())}, artefact {int(art.sum())}, "
                  f"HR3 valid {100 * m.mean():.1f} %, {FIG_VARIANT} agrees with HR3 in "
                  f"{100 * np.nanmean(agree) if m.any() else math.nan:.1f} % of them, rho med {np.median(rho_r):.2f}")
            for t0, t1, pr in plats:
                sel = (t_end >= t0) & (t_end <= t1)
                for e, (hr, q) in est.items():
                    h = hr[sel]; cl = hv.harmonic_class(h, np.full(len(h), pr))
                    plateau_rows.append({"session": name, "pr_bpm": pr, "estimator": e, "windows": int(sel.sum()),
                                         "ok_pct": round(100 * float(np.mean(cl == 0)), 1) if sel.any() else math.nan,
                                         "harmonic_pct": round(100 * float(np.mean(cl == 1)), 1) if sel.any() else math.nan,
                                         "hr_med": round(float(np.nanmedian(h)), 2) if np.isfinite(h).any() else math.nan,
                                         "q_med": round(float(np.median(q[sel])), 3) if sel.any() else math.nan})
            if not args.no_gate and subject not in hv.MS100_SUBJECTS and os.path.isdir(os.path.join(sd, "derived", args.replay)):
                g = hv.gate_load(sd, args.replay)
                rt, rs, rc = B.parse_reference(sd)
                anomalies = session_events.anomaly_intervals(sd, subject)
                n = len(g["t"])
                masks = {"no gate (base rule only)": np.ones(n, dtype=bool)}
                for label in (HR3_TODAY, B1):
                    masks[label] = hv.hold_mask(n, d["ps"], end_rows, np.isfinite(est[label][0]))
                for v in GATE_VARIANTS:
                    hr, rho = est[f"{v} first"]
                    for T in THRESHOLDS:
                        masks[f"{v} rho>={T:.1f}"] = hv.hold_mask(n, d["ps"], end_rows, np.isfinite(hr) & (rho >= T))
                for T in THRESHOLDS:
                    masks[f"purity>={T:.1f}"] = hv.hold_mask(n, d["ps"], end_rows, pur >= T)
                    masks[f"{FIG_VARIANT} rho>=0.5 & purity>={T:.1f}"] = hv.hold_mask(
                        n, d["ps"], end_rows, (rho_r >= 0.5) & (pur >= T))
                for label, rows in hv.gate_windows(g, rt, rs, rc, anomalies, masks).items():
                    gate_acc.setdefault((subject, label), []).extend(rows)
            if not args.no_figs:
                figure(os.path.join(args.out, f"{name}_sac.png"), name, t_end, P, bin_res, Rs[FIG_VARIANT],
                       hr0, sqi0, hr_r, rho_r, ref, contrast[FIG_VARIANT], b_lo, pur)

    # ── per subject x estimator; the comb against today's HR3 ──
    summ, cmp_rows = [], []
    for subject, st in acc.items():
        ref = np.concatenate(st["ref"]); art = np.concatenate(st["art"])
        has_ref = np.isfinite(ref) & (ref >= hv.HR_MIN) & (ref <= hv.HR_MAX)   # a 20 bpm plateau is out of range by design
        ref1 = np.where(has_ref, ref, 1.0)
        hr0 = np.concatenate(st["est"][HR3_TODAY][0])
        v0 = np.isfinite(hr0)
        for e in est_names:
            hr = np.concatenate(st["est"][e][0]); q = np.concatenate(st["est"][e][1])
            cl = hv.harmonic_class(hr, ref)
            ratio = hr[has_ref] / ref[has_ref]
            both = v0 & np.isfinite(hr)
            summ.append({"subject": subject, "estimator": e, "windows": len(hr),
                         "avail_pct": pct(np.isfinite(hr)),
                         "ref_windows": int(has_ref.sum()),
                         "ok_pct": pct(cl[has_ref] == 0),
                         "double_pct": pct(np.abs(ratio / 2 - 1) <= hv.HARMONIC_TOL),
                         "half_pct": pct(np.abs(ratio * 2 - 1) <= hv.HARMONIC_TOL),
                         "none_pct": pct(~np.isfinite(hr[has_ref])),
                         "agree_hr3_pct": pct(np.abs(hr[both] / hr0[both] - 1) <= hv.OK_REL),
                         "q_ref_med": round(float(np.median(q[has_ref])), 3) if has_ref.any() else math.nan,
                         "q_art_med": round(float(np.median(q[art])), 3) if art.any() else math.nan,
                         "art_windows": int(art.sum()),
                         "auc": round(hv.rank_auc(q[has_ref], q[art]), 3)})
        hr = np.concatenate(st["est"][f"{FIG_VARIANT} first"][0])
        rho = np.concatenate(st["est"][f"{FIG_VARIANT} first"][1])
        pur = np.concatenate(st["est"][f"purity @ {FIG_VARIANT}"][1])
        g7 = np.isfinite(hr) & (rho >= 0.7)
        ok0 = v0 & has_ref & (np.abs(hr0 / ref1 - 1) <= hv.OK_REL)
        ok7 = g7 & has_ref & (np.abs(hr / ref1 - 1) <= hv.OK_REL)
        contra = v0 & g7 & (np.abs(hr0 / np.where(g7, hr, 1.0) - 1) > hv.OK_REL)
        cmp_rows.append({"subject": subject, "windows": len(hr),
                         "hr3_avail_pct": pct(v0),
                         "comb_avail_rho05_pct": pct(np.isfinite(hr) & (rho >= 0.5)),
                         "comb_avail_rho07_pct": pct(g7),
                         "comb_avail_rho08_pct": pct(np.isfinite(hr) & (rho >= 0.8)),
                         "ref_windows": int(has_ref.sum()),
                         "hr3_ok_ref_pct": pct(ok0, has_ref),
                         "comb_rho07_avail_ref_pct": pct(g7 & has_ref, has_ref),
                         "comb_rho07_ok_of_avail_ref_pct": pct(ok7, g7 & has_ref),
                         "hr3_valid_windows": int(v0.sum()),
                         "hr3_contradicted_windows": int(contra.sum()),
                         "hr3_contradicted_pct": pct(contra, v0),
                         "hr3_med_bpm_there": round(float(np.median(hr0[contra])), 1) if contra.any() else math.nan,
                         "comb_med_bpm_there": round(float(np.median(hr[contra])), 1) if contra.any() else math.nan,
                         "purity_med": round(float(np.median(pur)), 2)})
    gsum = []
    for (subject, label), rows in gate_acc.items():
        b = np.array([o - s for s, pub, o in rows if pub])
        gsum.append({"subject": subject, "rule": label, "windows": len(rows),
                     "published_pct": round(100 * len(b) / max(len(rows), 1), 1),
                     "bias_med": round(float(np.median(b)), 2) if len(b) else math.nan,
                     "arms": round(float(np.sqrt(np.mean(b ** 2))), 2) if len(b) else math.nan,
                     "off_gt4_pct": round(100 * float(np.mean(np.abs(b) > 4)), 1) if len(b) else math.nan})
    write_csv(os.path.join(args.out, "summary.csv"), summ)
    write_csv(os.path.join(args.out, "comb_vs_hr3.csv"), cmp_rows)
    write_csv(os.path.join(args.out, "ms100.csv"), plateau_rows)
    write_csv(os.path.join(args.out, "gate.csv"), gsum)

    # ── console ──
    print(f"\n{'subject':7} {'estimator':26} {'win':>6} {'avail%':>6} {'nref':>5} {'ok%':>5} {'x2%':>5} {'x.5%':>5} {'none%':>5} "
          f"{'=HR3%':>5} {'qRef':>5} {'qArt':>5} {'nart':>5} {'auc':>5}")
    for s in summ:
        print(f"{s['subject']:7} {s['estimator']:26} {s['windows']:6d} {s['avail_pct']:6.1f} {s['ref_windows']:5d} {s['ok_pct']:5.1f} "
              f"{s['double_pct']:5.1f} {s['half_pct']:5.1f} {s['none_pct']:5.1f} {s['agree_hr3_pct']:5.1f} {s['q_ref_med']:5.2f} "
              f"{s['q_art_med']:5.2f} {s['art_windows']:5d} {s['auc']:5.2f}")
    print(f"\nThe comb ({FIG_VARIANT}, first maximum) against today's HR3:")
    print(f"{'subject':7} {'win':>6} | {'HR3%':>5} {'r>=.5':>6} {'r>=.7':>6} {'r>=.8':>6} | {'nref':>5} {'okHR3':>6} {'avail.7':>7} {'ok.7':>6} | "
          f"{'HR3 valid':>9} {'contradicted':>12} {'%':>5} {'HR3 med':>7} {'comb med':>8} | {'pur med':>7}")
    for r in cmp_rows:
        print(f"{r['subject']:7} {r['windows']:6d} | {r['hr3_avail_pct']:5.1f} {r['comb_avail_rho05_pct']:6.1f} {r['comb_avail_rho07_pct']:6.1f} "
              f"{r['comb_avail_rho08_pct']:6.1f} | {r['ref_windows']:5d} {r['hr3_ok_ref_pct']:6.1f} {r['comb_rho07_avail_ref_pct']:7.1f} "
              f"{r['comb_rho07_ok_of_avail_ref_pct']:6.1f} | {r['hr3_valid_windows']:9d} {r['hr3_contradicted_windows']:12d} "
              f"{r['hr3_contradicted_pct']:5.1f} {r['hr3_med_bpm_there']:7.1f} {r['comb_med_bpm_there']:8.1f} | {r['purity_med']:7.2f}")
    if gsum:
        print(f"\nSpO2 artefact gate (ward monitor reference, {args.replay}):")
        print(f"{'subject':7} {'rule':28} {'win':>5} {'pub%':>6} {'bias':>6} {'Arms':>6} {'>4pt%':>6}")
        for s in gsum:
            print(f"{s['subject']:7} {s['rule']:28} {s['windows']:5d} {s['published_pct']:6.1f} {s['bias_med']:6.2f} {s['arms']:6.2f} {s['off_gt4_pct']:6.1f}")
    if plateau_rows:
        prs = sorted({r["pr_bpm"] for r in plateau_rows})
        print("\nMS100 ok % per plateau (bpm); '.' = 100, 'x' = 0:")
        print(f"{'estimator':26} " + " ".join(f"{p:5.0f}" for p in prs))
        for e in est_names:
            cells = []
            for p in prs:
                rs_ = [r for r in plateau_rows if r["estimator"] == e and r["pr_bpm"] == p]
                okp = float(np.mean([r["ok_pct"] for r in rs_])) if rs_ else math.nan
                cells.append("    ." if okp >= 99.95 else ("    x" if okp <= 0.05 else f"{okp:5.1f}"))
            print(f"{e:26} " + " ".join(cells))


if __name__ == "__main__":
    main()
