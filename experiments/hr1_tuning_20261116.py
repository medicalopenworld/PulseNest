"""Part 2 of the family-1 study: parameters chosen on the MIMIC PERform training neonates, reported on the
test neonates and on our captures (2026-11-16; proposal approved by Alex: "Sí, mide").

Why this exists
---------------
Part 1 (docs/hr1_methods_20261116.md, F2 and F3) measured the four detectors with the papers' values and
ported the common front end to the library (v0.122: HR1_THR + R0 behind it). It also showed what the
papers' values cost on neonates: SSF's 0.34 s eye-closing loses beats above ~176 bpm and lets the dicrotic
wave in at 30 bpm, its 8 s learning period delays the start, today's detector loses one beat in nine,
and R1 without a gate publishes stale medians. This part chooses those parameters out of sample.

Fixed before measuring (proposal of 2026-11-16, approved)
---------------------------------------------------------
Grids (pulsenest/hr1_bench.py, the common front end with the low-pass corner as a factor):
  HR1_SSF  eye-closing fixed 0.20 / 0.25 / 0.30 s, or k x the median of the last 5 onset intervals with
           k = 0.4 / 0.5 / 0.6 (kept within 0.15-0.6 s, 0.25 s until two onsets are known)
           x slope window 0.10 / 0.13 / 0.17 s x learning period 2 / 4 / 8 s x low-pass 8 / 15 Hz  (108)
  HR1_THR  threshold 0.4 / 0.5 / 0.6 / 0.7 x refractory 0.185 s fixed, 0.4 or 0.5 x the median of the last
           5 RR (same bounds) x low-pass 8 / 15 Hz  (24)
  rules    R0, R1, and R1 publishing only with the accepted share of the last 8 RR >= 5/8 or >= 6/8, with
           or without R0's gate (CV of the accepted RR <= 15 %)
Stage 1, detector: the highest pooled beat F1 on the 100 training neonates (Charlton 2022's scoring as in
  F2: ECG reference beats, kept 20 s windows, the first 20 s not scored, lag -10..+10 s), among the
  configurations that keep the MS100 (concrete form of "the plateaus from 30 to 240 bpm stay right":
  every plateau of SUBJ90 in that range right, within 10 %, in at least 90 % of its outputs, with R0).
  Ties within 0.3 points of the best F1: the shortest learning period (SSF), then a fixed bound over an
  RR-proportional one, then the longest bound (eye-closing, refractory), then the paper's / library's
  slope window and threshold, then 15 Hz.
Stage 2, rule: on each selected detector, the highest ok - 1.75 x wrong (both in % of the training
  outputs with an ECG rate) among the rules with at most 2 % wrong of what they publish; chain outputs
  read every 0.5 s and scored as F2's Q3 (lag within -1..+2 s, the ECG rate over the beats the value was
  computed from).
Report: the selected chains and the library's chain v0.122 (HR1_THR 0.6, 0.185 s, 15 Hz, R0) on the test
  neonates (beats and chains) and on our captures (F3's measures and weighted total).
Adoption rule against v0.122: a lower weighted total on our captures, a wrong-of-published share on the
  MIMIC test neonates at most 0.5 points above v0.122's, and the MS100 plateaus 30-240 still right.

Result (run 2026-11-16 10:12; report docs/hr1_methods_20261116.md, part 2): no SSF configuration keeps
the MS100 (all 108 read 60 at the 30 bpm plateau); THR's threshold is the lever (pooled F1 95.2 % at 0.4
against 93.4 % at 0.6), the RR-proportional refractory lowers it; selected THR 0.4, 0.185 s, 15 Hz and,
on training, R1 with q >= 5/8 (the CV gate adds nothing). On the test neonates THR 0.4 + R1 q>=5/8 is
wrong 2.72 % of what it publishes and drops the MS100 to 44 %: not adopted. THR 0.4 + R0 passes the
adoption rule: MIMIC test published 71.3 % (v0.122 63.4) with 0.43 % wrong (0.57), our captures total 12.7
(14.5), published 74.6 % (66.4), MS100 kept. Extra check (perturbed MS100 sweep of 2026-09-08): 0.4 is
1.9 points worse at 60 bpm with a squeezed probe, 2.6-4.9 points better at 140-250 bpm.

Corrected range check (--corrected; 2026-11-16, after Alex reviewed the MS100's 30 bpm plateau: its
dicrotic wave looks like a systolic pulse. Measured: the MS100 stretches one template with the RR, and real
pulses below 40 bpm are single humps whose secondary slope sum is a tenth of the MS100's,
experiments/hr1_lowrate_pulse_20261116.py). Fixed before the corrected run; only the range check
changes, everything else (F1 on the training neonates, tie rule, stage 2, test, adoption) stays:
  (a) the MS100 plateaus from 60 to 240 bpm right in at least 90 % of their outputs with R0 (30 bpm out);
  (b) real slow pulses: the PhysioNet 2015 true-bradycardia records with a PPG (adult ICU, 250 Hz,
      negated and upsampled x2 to 500 Hz for the bench), 10 s windows where the two QRS detectors agree,
      the ECG median rate is under 50 bpm, the PPG is not flat for more than 0.2 s and beats once per ECG
      interval (one peak of prominence >= 0.5 of the window's amplitude); each detector's beats scored as
      Charlton (lag -10..+10 s, 150 ms) pooled over those windows: PPV >= 95 % and Se >= 90 %.
  The adoption rule's "MS100 kept" becomes (a) and (b). Outputs in <out>/corrected/.

Result of the corrected run (2026-11-16 11:15): SSF 6 of 108 pass, all with the eye-closing 0.6 x RR and
the 0.10 s slope window (on the real slow pulses only RR-proportional eye-closings with the 0.10 s window
pass, no fixed one); THR 18 of 24, threshold 0.4 out at every refractory (real slow pulses PPV 87.7-92.8 %).
Selected SSF ec 0.6xRR slope 0.10 learn 2 LP 15 + R0 (the only rule under the floor) and THR 0.5, 0.185 s,
15 Hz + R1 q>=5/8 + CV. On the test neonates SSF + R0 is wrong 1.19 % of what it publishes (limit 1.07)
and THR 0.5 + R1 2.69 %: not adopted. THR 0.5 + R0 passes the adoption rule: MIMIC test published 67.7 %
(v0.122 63.4) with 0.49 % wrong (0.57), our captures total 13.6 (14.5), published 71.2 % (66.4), MS100
60-240 and the real slow pulses (Se 98.1, PPV 96.4 %) kept. Diagnostic (--slowhp, not a selection): the
false beats on the real slow pulses come from the front end's 0.5 Hz high-pass, whose undershoot after a
slow pulse climbs back during the diastole (secondary slope-sum ratio 0.020 on the raw PPG, 0.296 after
0.5 Hz, 0.163 after 0.3 Hz); behind 0.3 Hz THR 0.4 and SSF with the papers' values reach PPV 98.2-98.5 %.
Perturbed MS100 sweep (--probepert) at threshold 0.5: 1.9 points worse at 60 bpm, 0-3 better at 140-250.

Part 3, the high-pass corner (--hp; 2026-11-16, approved by Alex: "Sí, mide el corte", after the corrected
run's diagnostic put the false beats on real slow pulses on the front end's 0.5 Hz high-pass). Fixed before
measuring:
  - the corner of the common front end's high-pass as one more factor of both grids: 0.5 (v0.122) / 0.3 /
    0.2 Hz (SSF 324 configurations, THR 72); the rest of the front end unchanged;
  - stage 1 with the corrected range check ((a) and (b) above), stage 2, the test and the adoption rule as
    in the corrected run; ties within 0.3 points: the higher corner first (the change has to earn its
    place), then the tie rule above;
  - reported beside, not selected: the chain the corrected run adopted (THR 0.5, 0.185 s, 15 Hz, 0.5 Hz,
    + R0);
  - if more than one chain passes the adoption rule, the proposal is the one with the lowest weighted total
    on our captures;
  - what a lower corner costs (more baseline wander, a longer recovery after a step of the OT: probe
    applied, HGAC gain change) is scored, as before, by the weighted total on our captures.
  Outputs in <out>/hp/; caches of the front end before its high-pass (mimic_*_prehp.pkl, brady_prehp.pkl).

Result of part 3 (run 2026-11-16 11:37): behind 0.3 Hz SSF passes the range check in 96 of 108
configurations (0.5 Hz: 6), best F1 97.48 % (0.5 Hz: 96.45); 79 within 0.3 points, none at 0.5 Hz;
selected SSF ec 0.30 s, slope 0.17, learn 2, LP 15, HP 0.3 (97.24 %). THR: the lower corners pass the
slow pulses but lose F1 (best 94.41 / 93.71 / 92.67 % at 0.5 / 0.3 / 0.2 Hz); selected THR 0.5, 0.185 s,
15 Hz, 0.5 Hz. Stage 2 picks R1 q>=5/8 + CV for both, and both fail the test neonates' honesty (2.00 and
2.69 % wrong). SSF + R0 and THR 0.5 + R0 pass the adoption rule; proposal (lowest total): SSF (part 3) +
R0, MIMIC test F1 96.4 % (v0.122 91.5), published 78.1 % (63.4) with 0.40 % wrong (0.57); our captures
total 11.9 (14.5), published 86.2 % (66.4), MAE 1.51 bpm (1.77); slow pulses PPV 98.1 %; MS100 60-240
kept (its 30 bpm plateau reads 61). Perturbed MS100 sweep (probepert_check(cfgs=...)): 3.4 points worse
at 60 bpm, 4.0-9.5 better at 140-250 bpm.

    python experiments/hr1_tuning_20261116.py [--workers N] [--out DIR] [--corrected | --hp | --slowhp | --probepert]

Outputs in --out (default captures/sessions/HR1_TUNING_20261116/, not versioned): stage1_ssf.csv,
stage1_thr.csv, stage2_rules.csv, test_report.txt, corpus_report.txt, and the data cache.
"""
import argparse
import csv
import datetime
import glob
import itertools
import math
import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from pulsenest import hr_bench as hb                       # noqa: E402
from pulsenest import hr1_bench as h1                      # noqa: E402
from experiments import hr1_methods_20261116 as P3         # noqa: E402
from tools import spo2_bias_analysis as B                  # noqa: E402

MIMIC = r"C:\PRJ\MOW\datasets\mimic_perform"
OUT_DIR = os.path.join(B.SESSIONS_DIR, "HR1_TUNING_20261116")
FS_IN, UP, FS = 125.0, 4, 500.0
SKIP_S = 20.0
LAG3 = (-1.0, 2.0)
LPS = (8.0, 15.0)
SSF_EC = (("fixed", 0.20), ("fixed", 0.25), ("fixed", 0.30), ("rr", 0.4), ("rr", 0.5), ("rr", 0.6))
SSF_SLOPE = (0.10, 0.13, 0.17)
SSF_LEARN = (2.0, 4.0, 8.0)
THR_FRAC = (0.4, 0.5, 0.6, 0.7)
THR_REFR = (("fixed", 0.185), ("rr", 0.4), ("rr", 0.5))
RULE_SET = (("R0", None), ("R1", (0.0, None)), ("R1 q>=5/8", (5 / 8, None)), ("R1 q>=6/8", (6 / 8, None)),
            ("R1 q>=5/8 + CV", (5 / 8, 0.15)), ("R1 q>=6/8 + CV", (6 / 8, 0.15)))
MS100_MIN_OK = 90.0
TIE_F1 = 0.3
# corrected range check (--corrected)
BRADY_DIR = r"C:\PRJ\MOW\datasets\physionet_challenge2015\training"
MS100_MIN_BPM_CORRECTED = 60.0
BRADY_WIN_S, BRADY_HR_MAX, BRADY_PPV_MIN, BRADY_SE_MIN = 10.0, 50.0, 95.0, 90.0
LIB_V0122 = {"det": "THR", "frac": 0.6, "refr": ("fixed", 0.185), "lp": 15.0}
# part 3 (--hp): the front end's high-pass corner as a factor
HPS = (0.5, 0.3, 0.2)
HP_DEFAULT = h1.HR1_HP_HZ
PART2_CORRECTED = {"det": "THR", "frac": 0.5, "refr": ("fixed", 0.185), "lp": 15.0}


# ============================================================================= configurations

def ssf_grid():
    return [{"det": "SSF", "ec": ec, "slope": sw, "learn": ln, "lp": lp}
            for ec, sw, ln, lp in itertools.product(SSF_EC, SSF_SLOPE, SSF_LEARN, LPS)]


def thr_grid():
    return [{"det": "THR", "frac": fr, "refr": rf, "lp": lp} for fr, rf, lp in itertools.product(THR_FRAC, THR_REFR, LPS)]


def with_hp(grid, hps):
    """Part 3: every configuration at every high-pass corner (None: the front end's 0.5 Hz, no key)."""
    return grid if hps is None else [dict(c, hp=hp) for hp in hps for c in grid]


def label(c):
    hp = f" HP {c['hp']:.1f}" if "hp" in c else ""
    if c["det"] == "SSF":
        ec = f"ec {c['ec'][1]:.2f}s" if c["ec"][0] == "fixed" else f"ec {c['ec'][1]:.1f}xRR"
        return f"SSF {ec} slope {c['slope']:.2f} learn {c['learn']:.0f} LP {c['lp']:.0f}{hp}"
    rf = f"refr {c['refr'][1]:.3f}s" if c["refr"][0] == "fixed" else f"refr {c['refr'][1]:.1f}xRR"
    return f"THR {c['frac']:.1f} {rf} LP {c['lp']:.0f}{hp}"


def make_detector(c, rate):
    if c["det"] == "SSF":
        kw = {"slope_w_s": c["slope"], "learn_s": c["learn"]}
        if c["ec"][0] == "fixed":
            kw["eye_closing_s"] = c["ec"][1]
        else:
            kw["eye_closing_rr"] = c["ec"][1]
        return h1.SsfDetector(rate, **kw)
    kw = {"threshold_frac": c["frac"]}
    if c["refr"][0] == "fixed":
        kw["refractory_s"] = c["refr"][1]
    else:
        kw["refractory_rr"] = c["refr"][1]
    return h1.ThrDetector(rate, **kw)


def make_rule(r):
    name, g = r
    if g is None:
        return h1.RuleR0()
    return h1.RuleR1(q_min=g[0], cv_max=g[1])


def tie_key(c):
    """Order among the configurations within TIE_F1 of the best (lower first), as fixed above; part 3
    puts the higher high-pass corner first."""
    hp = (-c.get("hp", HP_DEFAULT),)
    if c["det"] == "SSF":
        bound = c["ec"]
        return hp + (c["learn"], 0 if bound[0] == "fixed" else 1, -bound[1], abs(c["slope"] - 0.17), -c["lp"])
    bound = c["refr"]
    return hp + (0 if bound[0] == "fixed" else 1, -bound[1], abs(c["frac"] - 0.6), -c["lp"])


# ============================================================================= data

def pre_hp(x, fs, lp_hz):
    """The front end up to its high-pass (LowPass4, negate, one sample in `factor`), as FrontEnd.process
    on one block from reset. Returns (z, factor)."""
    fe = h1.FrontEnd(fs, lp_hz=lp_hz)
    y = np.asarray(x, dtype=np.float64)
    for sec in fe._lp:
        y = sec.process(y)
    return -y[np.arange(fe.factor - 1, len(y), fe.factor)], fe.factor


def front(rec, c):
    """The front end's output at 100 Hz for the configuration's corners: the cached output (parts 2 and
    2 corrected, 0.5 Hz) or the high-pass, precharged as in FrontEnd, on the cached signal before it."""
    lp, hp = int(c["lp"]), c.get("hp", HP_DEFAULT)
    if f"z{lp}" in rec:
        return h1._Section.biquad(h1._biquad_hp(hp, FS / rec["fac"], h1.HR1_HP_Q)).process(rec[f"z{lp}"])
    if hp != HP_DEFAULT:
        raise ValueError("this cache holds the front end's output at the default high-pass only")
    return rec[f"y{lp}"]


def prepare(split, cache_dir, prehp=False):
    """Per record of a MIMIC split: ECG reference beats, kept windows (first 20 s dropped), raw length at
    500 Hz and, for each low-pass corner, the common front end's output at 100 Hz (or, with prehp, the
    signal before its high-pass, for part 3). Cached."""
    path = os.path.join(cache_dir, f"mimic_{split}{'_prehp' if prehp else ''}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    from scipy.signal import resample_poly
    sys.path.insert(0, os.path.join(_ROOT, "experiments"))
    from experiments import hr1_mimic_perform_20261116 as F2
    files = sorted(glob.glob(os.path.join(MIMIC, f"mimic_perform_{split}_n_csv", "*_data.csv")))
    recs = {}
    for fpath in files:
        ppg, ecg = F2.read_record(fpath)
        ref, kept, _ = h1.ecg_reference(ecg, ppg, FS_IN)
        kept = [w for w in kept if w[0] >= SKIP_S]
        x = resample_poly(-ppg, UP, 1)
        rec = {"ref": ref, "kept": kept, "n": len(x)}
        for lp in LPS:
            if prehp:
                rec[f"z{int(lp)}"], rec["fac"] = pre_hp(x, FS, lp)
            else:
                fe = h1.FrontEnd(FS, lp_hz=lp)
                rec[f"y{int(lp)}"], _ = fe.process(x)
                rec["fac"] = fe.factor
        recs[os.path.basename(fpath)[:-9]] = rec
    with open(path, "wb") as f:
        pickle.dump(recs, f)
    return recs


def prepare_brady(cache_dir, prehp=False):
    """PhysioNet 2015 true-bradycardia records with a PPG: agreed ECG beats, the 10 s slow concordant
    windows (see the docstring) and the front end's output (or, with prehp, the signal before its
    high-pass) for each low-pass corner. Cached."""
    path = os.path.join(cache_dir, "brady_prehp.pkl" if prehp else "brady.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    from scipy.signal import resample_poly, find_peaks, butter, sosfiltfilt
    from experiments import hr1_lowrate_pulse_20261116 as LP
    recs = {}
    for name in LP.true_bradycardia(BRADY_DIR):
        fs, sigs = LP.read_wfdb(os.path.join(BRADY_DIR, name))
        pleth = next((v for k, v in sigs.items() if "PLETH" in k.upper()), None)
        ecg_key = next((k for k in sigs if k.upper() in ("II", "I", "III", "V", "AVR", "AVL", "AVF", "MCL")), None)
        if pleth is None or ecg_key is None:
            continue
        ecg = np.nan_to_num(sigs[ecg_key]); ppg = np.nan_to_num(pleth)
        a = h1.qrs_pan_tompkins(ecg, fs) / fs
        b = h1.qrs_envelope(ecg, fs) / fs
        ia, ib, ua, ub = h1._pair(a, b, 0.15)
        ref = a[ia]; bad = np.concatenate([a[ua], b[ub]])
        flats = [(s / fs, e / fs) for s, e in h1.flat_runs(ppg, fs)]
        yf = sosfiltfilt(butter(4, 10.0, fs=fs, output="sos"), ppg)
        windows = []
        dur = len(ppg) / fs
        for k in range(int(dur // BRADY_WIN_S)):
            t0, t1 = k * BRADY_WIN_S, (k + 1) * BRADY_WIN_S
            rw = ref[(ref >= t0) & (ref < t1)]
            if len(rw) < 3 or np.any((bad >= t0) & (bad < t1)) or any(s < t1 and e > t0 for s, e in flats):
                continue
            if 60.0 / float(np.median(np.diff(rw))) >= BRADY_HR_MAX:
                continue
            seg = yf[int(t0 * fs):int(t1 * fs)]
            pk, _ = find_peaks(seg, prominence=0.5 * (np.percentile(seg, 99) - np.percentile(seg, 1)),
                               distance=int(0.25 * fs))
            pk_t = t0 + pk / fs
            if all(np.sum((pk_t >= r0 + 0.1) & (pk_t < r1 + 0.1)) == 1 for r0, r1 in zip(rw[:-1], rw[1:])):
                windows.append((t0, t1))
        if not windows:
            continue
        x = resample_poly(-ppg, 2, 1) if abs(fs - 250.0) < 1e-6 else None
        if x is None:
            continue
        rec = {"ref": ref, "kept": windows, "n": len(x)}
        for lp in LPS:
            if prehp:
                rec[f"z{int(lp)}"], rec["fac"] = pre_hp(x, FS, lp)
            else:
                fe = h1.FrontEnd(FS, lp_hz=lp)
                rec[f"y{int(lp)}"], _ = fe.process(x)
                rec["fac"] = fe.factor
        recs[name] = rec
    with open(path, "wb") as f:
        pickle.dump(recs, f)
    return recs


def ms100_data(cache):
    out = []
    for sd in hb.session_dirs(B.SESSIONS_DIR, "SUBJ90"):
        d = hb.load_columns(sd, cache)
        out.append((os.path.basename(sd), d, hb.ms100_plateaus(sd)))
    return out


# ============================================================================= worker

_W = {}


def _init(train_pkl, ms100_pkl, brady_pkl=None):
    with open(train_pkl, "rb") as f:
        _W["train"] = pickle.load(f)
    with open(ms100_pkl, "rb") as f:
        _W["ms100"] = pickle.load(f)
    if brady_pkl:
        with open(brady_pkl, "rb") as f:
            _W["brady"] = pickle.load(f)


def brady_check(c, brady):
    """Pooled Se and PPV of a detector on the real slow concordant windows (corrected check (b))."""
    nr = nd = nc = 0
    for rec in brady.values():
        det = make_detector(c, FS / rec["fac"])
        b = beats_rows(front(rec, c), rec["fac"], det)
        s = h1.beat_scores(rec["ref"], b[:, 0] / FS if len(b) else np.zeros(0), rec["kept"])
        nr += s["n_ref"]; nd += s["n_det"]; nc += s["n_correct"]
    return (100.0 * nc / nr if nr else 0.0), (100.0 * nc / nd if nd else 0.0)


def beats_rows(y, fac, det):
    """Detector on the 100 Hz front-end output: beats in raw rows (500 Hz) as hr1_bench.detect gives."""
    det.reset()
    b = det.push(y)
    if not b:
        return np.zeros((0, 3))
    a = np.asarray(b, float)
    a[:, 0] = a[:, 0] * fac + (fac - 1)
    a[:, 1] = a[:, 1] * fac + (fac - 1)
    return a


def ms100_check(c, ms100):
    """Every SUBJ90 plateau with a rate in 30-240 bpm: % of its outputs right with R0."""
    res = []
    for name, d, plats in ms100:
        fs = d["fs"]
        for r0, r1 in P3.applied_runs(d):
            x = d["OT_LED1"][r0:r1]
            rows = h1.output_rows(len(x), fs)
            if len(rows) == 0:
                continue
            fe = h1.FrontEnd(fs, lp_hz=c["lp"], hp_hz=c.get("hp", HP_DEFAULT))
            det = make_detector(c, fe.rate)
            b = h1.detect(x, fs, fe, det)
            hr, q, v = h1.apply_rule(b, fs, h1.RuleR0(), rows, latency_s=det.latency_s)
            t = d["t"][r0 + rows]
            for p0, p1, pr in plats:
                if not (30.0 <= pr <= 240.0):
                    continue
                sel = (t >= p0) & (t <= p1)
                if sel.sum() == 0:
                    continue
                ok = v[sel] & (np.abs(hr[sel] / pr - 1.0) <= hb.OK_REL)
                res.append((name, pr, 100.0 * float(ok.mean())))
    return res


def stage1_task(c):
    tot = {"n_ref": 0, "n_det": 0, "n_cor": 0}
    f1s = []
    for rec in _W["train"].values():
        if not rec["kept"]:
            continue
        det = make_detector(c, FS / rec["fac"])
        b = beats_rows(front(rec, c), rec["fac"], det)
        s = h1.beat_scores(rec["ref"], b[:, 0] / FS if len(b) else np.zeros(0), rec["kept"])
        if s["n_ref"] == 0:
            continue
        tot["n_ref"] += s["n_ref"]; tot["n_det"] += s["n_det"]; tot["n_cor"] += s["n_correct"]
        f1s.append(s["f1"] if math.isfinite(s["f1"]) else 0.0)
    pooled = 200.0 * tot["n_cor"] / (tot["n_ref"] + tot["n_det"]) if tot["n_ref"] + tot["n_det"] else 0.0
    ms = ms100_check(c, _W["ms100"])
    out = {"config": c, "label": label(c), "pooled_f1": pooled, "median_f1": float(np.median(f1s)) if f1s else 0.0,
           "se": 100.0 * tot["n_cor"] / tot["n_ref"] if tot["n_ref"] else 0.0,
           "ppv": 100.0 * tot["n_cor"] / tot["n_det"] if tot["n_det"] else 0.0, "ms100": ms}
    if "brady" in _W:                                   # corrected range check
        ms = [m for m in ms if m[1] >= MS100_MIN_BPM_CORRECTED]
        se_b, ppv_b = brady_check(c, _W["brady"])
        out.update(brady_se=se_b, brady_ppv=ppv_b)
        out["ms100_ok"] = (bool(ms) and all(p >= MS100_MIN_OK for _, _, p in ms)
                           and ppv_b >= BRADY_PPV_MIN and se_b >= BRADY_SE_MIN)
    else:
        out["ms100_ok"] = bool(ms) and all(p >= MS100_MIN_OK for _, _, p in ms)
    out["ms100_worst"] = min((p for _, _, p in ms), default=0.0)
    return out


# ============================================================================= chains on MIMIC

def chain_eval(rec, c, rule):
    """F2's Q3 on one record: arrays over the scored outputs (published, right) and the quality."""
    det = make_detector(c, FS / rec["fac"])
    b = beats_rows(front(rec, c), rec["fac"], det)
    rows = h1.output_rows(rec["n"], FS)
    t_out = rows / FS
    if not rec["kept"] or len(b) == 0:
        return np.zeros(0, bool), np.zeros(0, bool), np.zeros(0)
    tb = b[:, 0] / FS
    lag = h1.beat_scores(rec["ref"], tb, rec["kept"], lag_lo_s=LAG3[0], lag_hi_s=LAG3[1])["lag_s"]
    lag = lag if math.isfinite(lag) else 0.0
    hr, q, v, last = h1.apply_rule(b, FS, make_rule(rule), rows, latency_s=det.latency_s, return_last=True)
    t_ref = np.maximum(np.where(np.isfinite(last), last / FS, -1.0), t_out - det.latency_max_s)
    hr_ref = h1.ref_hr_at(rec["ref"], rec["kept"], t_ref - lag)
    scored = np.isfinite(hr_ref) & (t_out >= SKIP_S)
    right = scored & np.isfinite(hr) & (np.abs(hr / np.where(scored, hr_ref, 1.0) - 1.0) <= hb.OK_REL)
    return v[scored], right[scored], q[scored]


def chain_summary(recs, c, rule):
    pub, rig, qq = [], [], []
    for rec in recs.values():
        v, r, q = chain_eval(rec, c, rule)
        pub.append(v); rig.append(r); qq.append(q)
    v, r, q = np.concatenate(pub), np.concatenate(rig), np.concatenate(qq)
    n = len(v)
    ok = v & r
    wrong = v & ~r
    out = {"scored": n, "published_pct": 100.0 * v.mean() if n else math.nan,
           "ok_pct": 100.0 * ok.mean() if n else math.nan, "wrong_pct": 100.0 * wrong.mean() if n else math.nan,
           "wrong_of_published_pct": 100.0 * wrong.sum() / v.sum() if v.sum() else math.nan}
    out["score"] = out["ok_pct"] - 1.75 * out["wrong_pct"]
    out["auc"] = hb.rank_auc(q[ok], q[wrong]) if (ok.any() and wrong.any()) else math.nan   # among the published
    return out


def beat_summary(recs, c):
    tot = {"n_ref": 0, "n_det": 0, "n_cor": 0}
    f1s = []
    for rec in recs.values():
        if not rec["kept"]:
            continue
        det = make_detector(c, FS / rec["fac"])
        b = beats_rows(front(rec, c), rec["fac"], det)
        s = h1.beat_scores(rec["ref"], b[:, 0] / FS if len(b) else np.zeros(0), rec["kept"])
        if s["n_ref"] == 0:
            continue
        tot["n_ref"] += s["n_ref"]; tot["n_det"] += s["n_det"]; tot["n_cor"] += s["n_correct"]
        f1s.append(s["f1"] if math.isfinite(s["f1"]) else 0.0)
    return {"pooled_f1": 200.0 * tot["n_cor"] / (tot["n_ref"] + tot["n_det"]),
            "median_f1": float(np.median(f1s)), "se": 100.0 * tot["n_cor"] / tot["n_ref"],
            "ppv": 100.0 * tot["n_cor"] / tot["n_det"]}


# ============================================================================= our captures (F3's measures)

def corpus_report(chains, cache):
    """F3's measures for a list of (name, config, rule): pooled ECG honesty/availability/precision,
    start-up, MS100 plateaus and steps, weighted total on F3's fixed scales."""
    names = [n for n, _, _ in chains]
    acc, ms_rows, step_acc, start_acc = {}, [], {}, {}
    for subject in P3.SUBJECTS:
        mon_path = os.path.join(P3.MONITOR_DIR, f"{subject}_snapshots_eye.csv")
        mon_t, mon_v, _ = (hb.monitor_readings(mon_path) if os.path.exists(mon_path)
                           else (np.zeros(0), np.zeros(0), "none"))
        sds = hb.session_dirs(B.SESSIONS_DIR, subject)
        offs = {sd: hb.phone_offset_us(sd) for sd in sds}
        known = [o for o in offs.values() if o is not None]
        fallback = float(np.median(known)) if known else 0.0
        for sd in sds:
            d = hb.load_columns(sd, cache)
            fs = d["fs"]
            est = {k: ([], []) for k in names}
            ends, run0 = [], []
            for r0, r1 in P3.applied_runs(d):
                x = d["OT_LED1"][r0:r1]
                rows = h1.output_rows(len(x), fs)
                if len(rows) == 0:
                    continue
                for name, c, rule in chains:
                    fe = h1.FrontEnd(fs, lp_hz=c["lp"], hp_hz=c.get("hp", HP_DEFAULT))
                    det = make_detector(c, fe.rate)
                    b = h1.detect(x, fs, fe, det)
                    hr, q, v = h1.apply_rule(b, fs, make_rule(rule), rows, latency_s=det.latency_s)
                    est[name][0].append(np.where(v, hr, np.nan)); est[name][1].append(q)
                ends.append(r0 + rows); run0.append(np.full(len(rows), r0))
            if not ends:
                continue
            ends = np.concatenate(ends); run0 = np.concatenate(run0)
            est = {k: (np.concatenate(a), np.concatenate(b)) for k, (a, b) in est.items()}
            t_end = d["t"][ends]; t_run = d["t"][run0]
            if subject in P3.MS100_SUBJECTS:
                plats = hb.ms100_plateaus(sd)
                ref = np.full(len(ends), np.nan)
                for p0, p1, pr in plats:
                    ref[(t_end >= p0) & (t_end <= p1)] = pr
                stable = np.isfinite(ref)
                for p0, p1, pr in plats:
                    sel = (t_end >= p0) & (t_end <= p1)
                    for k, (hr, _) in est.items():
                        cl = hb.error_class(hr[sel], np.full(int(sel.sum()), pr))
                        ms_rows.append({"estimator": k, "pr_bpm": pr, "ok_pct": P3.pct(cl == 0)})
                raw = [(p0 - hb.PLATEAU_SKIP_S * 1e6, pr) for p0, p1, pr in plats]
                for k, vv in P3.step_times(est, t_end, raw).items():
                    step_acc.setdefault(k, []).extend(vv)
            else:
                off = offs[sd] if offs[sd] is not None else fallback
                ref, stable = hb.monitor_reference(mon_t + off, mon_v, t_end)
            for k, vv in P3.startup(est, t_run, t_end, ref, np.isfinite(ref)).items():
                start_acc.setdefault((subject, k), []).extend(vv)
            st = acc.setdefault(subject, {"ref": [], "stable": [], "est": {k: ([], []) for k in names}})
            st["ref"].append(ref); st["stable"].append(stable)
            for k, (hr, q) in est.items():
                st["est"][k][0].append(hr); st["est"][k][1].append(q)
    zs = [acc[s] for s in P3.ECG_SUBJECTS if s in acc]
    sel = np.concatenate([np.concatenate(z["stable"]) for z in zs])
    ref = np.concatenate([np.concatenate(z["ref"]) for z in zs])
    pool = {}
    for k in names:
        hr = np.concatenate([np.concatenate(z["est"][k][0]) for z in zs])
        q = np.concatenate([np.concatenate(z["est"][k][1]) for z in zs])
        r = P3.honesty_row(hr, q, sel, ref)
        r["available_at_1pct_wrong"] = P3.avail_at(hr, q, sel, ref, 1.0)
        pool[k] = r
    st_ecg = {k: P3.med([x for (s, kk), v in start_acc.items() if kk == k and s in P3.ECG_SUBJECTS for x in v])
              for k in names}
    stp = {k: P3.med([e["s"] for e in step_acc.get(k, [])]) for k in names}
    ms = {k: [r["ok_pct"] for r in ms_rows if r["estimator"] == k] for k in names}
    ms_range = {k: [r for r in ms_rows if r["estimator"] == k and 30.0 <= r["pr_bpm"] <= 240.0] for k in names}
    metric = {
        "honesty": {k: pool[k]["wrong_of_published_pct"] for k in names},
        "availability": {k: pool[k]["published_pct"] for k in names},
        "dynamics": {k: (st_ecg[k] if not math.isnan(st_ecg[k]) else 99) + (stp[k] if not math.isnan(stp[k]) else 99)
                     for k in names},
        "range": {k: float(np.mean(ms[k])) if ms[k] else 0.0 for k in names},
        "precision": {k: pool[k]["mae_ok_bpm"] for k in names},
        "cost": {k: 0.0 for k in names},
    }
    rows, total = P3.weighted_total(metric, names)
    return pool, metric, total, ms_range, st_ecg


# ============================================================================= extra check

def probepert_check(fracs=(0.6, 0.4), cfgs=None):
    """The evidence behind hr1_threshold_fraction 0.6 (spec 10.4): the perturbed MS100 captures of
    2026-09-08 (probe squeezed at ~20/30/40/50 s), with the v0.122 chain at each threshold. Same metric
    as experiments/hr1_probepert_sweep.py: share of samples with hr1_sqi > 0 and |HR - truth| <= 3 bpm
    after 10 s, recovery after each squeeze (end of the first bad stretch, censored at 9.5 s), and the
    detected beats per expected beat. Not part of the adoption rule: reported beside it.
    cfgs: list of (name, configuration) to run instead, each with its own detector and front end
    (part 3); the default is HR1_THR at each threshold of `fracs` behind the v0.122 front end."""
    sys.path.insert(0, os.path.join(_ROOT, "experiments"))
    from hr1_decay_sweep import load_capture, CAPTURES
    events, warm, tol = (20.0, 30.0, 40.0, 50.0), 10.0, 3.0
    caps = [c for c in (load_capture(os.path.join(CAPTURES, f)) for f in sorted(os.listdir(CAPTURES))
                        if "PROBEPERT" in f and f.endswith(".csv")) if c]
    caps.sort(key=lambda c: c[3])
    lines = [f"perturbed MS100 captures (truth bpm): {[int(c[3]) for c in caps]}"]
    if cfgs is None:
        cfgs = [(f"threshold {f}", None, f) for f in fracs]
    else:
        cfgs = [(n, c, None) for n, c in cfgs]
    for name, cfg, frac in cfgs:
        goods, recs_all, ratio = [], [], []
        for ot, ps, fs, truth in caps:
            ot, ps = np.asarray(ot, float), np.asarray(ps, int)
            on = (ps == hb.APPLIED).astype(np.int8)
            e = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
            hr_all = np.full(len(ot), np.nan); q_all = np.zeros(len(ot))
            nb, nexp = 0, 0.0
            for r0, r1 in zip(e[::2], e[1::2]):
                x = ot[r0:r1]
                if cfg is None:
                    b = h1.detect(x, fs, h1.FrontEnd(fs), h1.ThrDetector(100.0, threshold_frac=frac))
                else:
                    fe = h1.FrontEnd(fs, lp_hz=cfg["lp"], hp_hz=cfg.get("hp", HP_DEFAULT))
                    b = h1.detect(x, fs, fe, make_detector(cfg, fe.rate))
                hr, q, _ = h1.apply_rule(b, fs, h1.RuleR0(), np.arange(len(x)))
                hr_all[r0:r1], q_all[r0:r1] = hr, q
                nb += len(b); nexp += (r1 - r0) / fs * truth / 60.0
            t = np.arange(len(ot)) / fs
            good = (ps == hb.APPLIED) & (q_all > 0) & (np.abs(hr_all - truth) <= tol)
            goods.append(100.0 * good[t >= warm].mean())
            recs = []
            for ev in events:
                win = np.flatnonzero((t >= ev - 0.5) & (t < ev + 9.5))
                bad = win[~good[win]]
                if len(bad) == 0:
                    recs.append(0.0); continue
                after = win[(win > bad[0]) & good[win]]
                recs.append((t[after[0]] - ev) if len(after) else 9.5)
            recs_all.append(float(np.mean(recs)))
            ratio.append(nb / nexp)
        lines.append(f"{name}: good % {np.round(goods, 1).tolist()}; recovery s {np.round(recs_all, 2).tolist()}; "
                     f"detected / expected {np.round(ratio, 3).tolist()}")
    return lines


def slow_hp_check(cache_dir):
    """Why the real slow pulses make false beats (diagnostic of the corrected run, not a selection):
    where the false beats fall in the ECG interval, and the detectors with the papers' / library's values
    behind front ends that differ only in the high-pass corner; plus the secondary slope-sum ratio and the
    undershoot below the foot of the concordant slow beats after each front end (same beats and metric
    as experiments/hr1_lowrate_pulse_20261116.py, which measured them on the raw PPG)."""
    from scipy.signal import resample_poly
    from experiments import hr1_lowrate_pulse_20261116 as LP
    brady = prepare_brady(cache_dir)
    xs = {}
    for name in brady:
        _, sigs = LP.read_wfdb(os.path.join(BRADY_DIR, name))
        xs[name] = resample_poly(-np.nan_to_num(next(v for k, v in sigs.items() if "PLETH" in k.upper())), 2, 1)
    cfgs = {"THR 0.6 (library)": LIB_V0122,
            "THR 0.4": {"det": "THR", "frac": 0.4, "refr": ("fixed", 0.185), "lp": 15.0},
            "SSF (papers)": {"det": "SSF", "ec": ("fixed", 0.34), "slope": 0.17, "learn": 8.0, "lp": 15.0},
            "SSF ec 0.5xRR": {"det": "SSF", "ec": ("rr", 0.5), "slope": 0.17, "learn": 8.0, "lp": 15.0}}
    lines = ["Real slow pulses, false beats and the front end's high-pass (Se / PPV %, pooled):",
             f"  {'high-pass':>9s} " + " ".join(f"{k:>18s}" for k in cfgs)]
    for hp in (0.5, 0.3, 0.2, 0.1):
        cells, phases = [], {}
        for k, c in cfgs.items():
            nr = nd = nc = 0
            ph = []
            for name, rec in brady.items():
                fe = h1.FrontEnd(FS, lp_hz=c["lp"], hp_hz=hp)
                y, _ = fe.process(xs[name])
                rows = beats_rows(y, fe.factor, make_detector(c, fe.rate))
                bt = rows[:, 0] / FS if len(rows) else np.zeros(0)
                sc = h1.beat_scores(rec["ref"], bt, rec["kept"])
                nr += sc["n_ref"]; nd += sc["n_det"]; nc += sc["n_correct"]
                ref = rec["ref"]
                d = bt - sc["lag_s"]
                for x in d[h1._inside(d, rec["kept"])]:
                    j = int(np.searchsorted(ref, x))
                    if 0 < j < len(ref) and min(x - ref[j - 1], ref[j] - x) > h1.REF_TOL_S:
                        ph.append((x - ref[j - 1]) / (ref[j] - ref[j - 1]))
            cells.append(f"{100 * nc / nr:5.1f} / {100 * nc / nd:5.1f}")
            phases[k] = ph
        lines.append(f"  {hp:7.1f}Hz " + " ".join(f"{x:>18s}" for x in cells))
        if hp == 0.5:
            for k, ph in phases.items():
                hist = np.histogram(ph, bins=10, range=(0.0, 1.0))[0].tolist() if ph else []
                lines.append(f"      {k}: {len(ph)} false beats, by tenth of the ECG interval {hist}")
    lines.append("Concordant slow beats after the front end (raw PPG: ratio median 0.020, p90 0.083):")
    for hp in (0.5, 0.3, 0.2):
        ratios, under = [], []
        for name, rec in brady.items():
            fe = h1.FrontEnd(FS, lp_hz=15.0, hp_hz=hp)
            y, _ = fe.process(xs[name])
            r = rec["ref"][h1._inside(rec["ref"], rec["kept"])]
            for sb, _ in LP.concordant_slow_beats(y, r, fe.rate):
                ratios.append(LP.secondary_ratio(sb, fe.rate))
                under.append(float(sb[int(np.argmax(sb)):].min()))
        ratios = np.asarray(ratios)
        lines.append(f"  high-pass {hp:.1f} Hz: {len(ratios)} beats; secondary slope-sum ratio median "
                     f"{np.median(ratios):.3f} (p90 {np.percentile(ratios, 90):.3f}), over 1/3 in "
                     f"{100 * np.mean(ratios > 1 / 3):.1f} %; undershoot below the foot, median "
                     f"{-np.median(under):.2f} of the pulse")
    return lines


# ============================================================================= main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--cache", default=os.path.join(B.SESSIONS_DIR, "HR_BENCH_CACHE"))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--probepert", action="store_true", help="only the extra check on the perturbed MS100 sweep")
    ap.add_argument("--corrected", action="store_true",
                    help="the corrected range check: MS100 60-240 bpm and real slow pulses (see the docstring)")
    ap.add_argument("--hp", action="store_true",
                    help="part 3: the front end's high-pass corner as a factor, with the corrected range check")
    ap.add_argument("--slowhp", action="store_true",
                    help="only the diagnostic of the corrected run: false beats on real slow pulses vs the high-pass")
    args = ap.parse_args(argv)
    if args.probepert:
        print("\n".join(probepert_check()))
        return
    if args.slowhp:
        print("\n".join(slow_hp_check(args.out)))
        return
    os.makedirs(args.out, exist_ok=True)
    corrected = args.corrected or args.hp
    out_dir = os.path.join(args.out, "hp" if args.hp else "corrected") if corrected else args.out
    os.makedirs(out_dir, exist_ok=True)
    mode = (" (part 3: high-pass corner, corrected range check)" if args.hp
            else " (corrected range check)" if args.corrected else "")
    lines = [f"hr1_tuning_20261116 run {datetime.datetime.now().isoformat(timespec='seconds')}{mode}"]
    print(lines[0], flush=True)
    train = prepare("train", args.out, prehp=args.hp)
    test = prepare("test", args.out, prehp=args.hp)
    ms100 = ms100_data(args.cache)
    ms_pkl = os.path.join(args.out, "ms100.pkl")
    with open(ms_pkl, "wb") as f:
        pickle.dump(ms100, f)
    brady, brady_pkl = None, None
    if corrected:
        brady = prepare_brady(args.out, prehp=args.hp)
        brady_pkl = os.path.join(args.out, "brady_prehp.pkl" if args.hp else "brady.pkl")
        nwin = sum(len(r["kept"]) for r in brady.values())
        lines.append(f"real slow pulses: {len(brady)} PhysioNet records, {nwin} slow concordant 10 s windows, "
                     f"{sum(len(r['ref'][h1._inside(r['ref'], r['kept'])]) for r in brady.values())} ECG beats in them")
    print(f"data: {len(train)} training, {len(test)} test records; MS100 sessions {len(ms100)}", flush=True)

    # stage 1
    selected = {}
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                             initargs=(os.path.join(args.out, f"mimic_train{'_prehp' if args.hp else ''}.pkl"),
                                       ms_pkl, brady_pkl)) as ex:
        hps = HPS if args.hp else None
        for fam, grid in (("SSF", with_hp(ssf_grid(), hps)), ("THR", with_hp(thr_grid(), hps))):
            res = list(ex.map(stage1_task, grid))
            res.sort(key=lambda r: -r["pooled_f1"])
            with open(os.path.join(out_dir, f"stage1_{fam.lower()}.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["config", "pooled_f1", "median_f1", "se", "ppv", "range_ok", "ms100_worst_plateau_pct",
                            "slow_se", "slow_ppv"])
                for r in res:
                    w.writerow([r["label"], f"{r['pooled_f1']:.2f}", f"{r['median_f1']:.2f}", f"{r['se']:.2f}",
                                f"{r['ppv']:.2f}", r["ms100_ok"], f"{r['ms100_worst']:.1f}",
                                f"{r.get('brady_se', float('nan')):.2f}", f"{r.get('brady_ppv', float('nan')):.2f}"])
            ok = [r for r in res if r["ms100_ok"]]
            lines.append(f"\nStage 1, {fam}: {len(res)} configurations, {len(ok)} pass the range check "
                         f"({'MS100 60-240 and real slow pulses' if corrected else 'MS100 30-240'}); "
                         f"top 8 by pooled F1:")
            for r in res[:8]:
                slow = (f"  slow pulses Se {r['brady_se']:5.1f} PPV {r['brady_ppv']:5.1f}" if "brady_se" in r else "")
                lines.append(f"  {r['label']:44s} pooled F1 {r['pooled_f1']:5.2f}  median {r['median_f1']:5.2f}  "
                             f"Se {r['se']:5.2f}  PPV {r['ppv']:5.2f}  range {'ok' if r['ms100_ok'] else 'FAIL'} "
                             f"(worst MS100 plateau {r['ms100_worst']:.0f} %){slow}")
            if not ok:
                lines.append("  no configuration passes the range check"); continue
            if hps:
                for hp in hps:
                    okh = [r for r in ok if r["config"]["hp"] == hp]
                    lines.append(f"  high-pass {hp:.1f} Hz: {sum(r['config']['hp'] == hp for r in res)} configurations, "
                                 f"{len(okh)} pass; best eligible "
                                 + (f"{okh[0]['label']} (pooled F1 {okh[0]['pooled_f1']:.2f})" if okh else "none"))
            best = ok[0]["pooled_f1"]
            tied = [r for r in ok if r["pooled_f1"] >= best - TIE_F1]
            pick = min(tied, key=lambda r: tie_key(r["config"]))
            selected[fam] = pick["config"]
            lines.append(f"  best eligible {best:.2f}; {len(tied)} within {TIE_F1} points; selected: {pick['label']} "
                         f"(pooled F1 {pick['pooled_f1']:.2f})")
            print("\n".join(lines[-12:]), flush=True)

    # stage 2
    lines.append("\nStage 2, rules on the selected detectors (training neonates):")
    lines.append(f"  {'chain':60s} {'pub %':>6s} {'ok %':>6s} {'wrong %':>8s} {'wrong/pub %':>11s} {'score':>7s}")
    chosen = {}
    st2 = []
    for fam, c in selected.items():
        best = None
        for rule in RULE_SET:
            s = chain_summary(train, c, rule)
            eligible = s["wrong_of_published_pct"] <= 2.0
            st2.append({"chain": f"{label(c)} + {rule[0]}", **s, "eligible": eligible})
            lines.append(f"  {label(c) + ' + ' + rule[0]:60s} {s['published_pct']:6.1f} {s['ok_pct']:6.1f} "
                         f"{s['wrong_pct']:8.2f} {s['wrong_of_published_pct']:11.2f} {s['score']:7.2f}"
                         f"{'' if eligible else '  (over the 2 % floor)'}")
            if eligible and (best is None or s["score"] > best[1]):
                best = (rule, s["score"])
        chosen[fam] = best[0] if best else ("R0", None)
        lines.append(f"  selected for {fam}: {chosen[fam][0]}")
    with open(os.path.join(out_dir, "stage2_rules.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(st2[0])); w.writeheader(); w.writerows(st2)
    print("\n".join(lines[-(len(st2) + 4):]), flush=True)

    # report on the test neonates
    finals = [("v0.122 (THR 0.6, 0.185 s, 15 Hz) + R0", LIB_V0122, ("R0", None))]
    for fam, c in selected.items():
        finals.append((f"{label(c)} + {chosen[fam][0]}", c, chosen[fam]))
        if chosen[fam][0] != "R0":
            finals.append((f"{label(c)} + R0", c, ("R0", None)))
    if args.hp and not any(c == dict(PART2_CORRECTED, hp=HP_DEFAULT) and r[0] == "R0" for _, c, r in finals):
        finals.append((f"{label(PART2_CORRECTED)} + R0 (corrected run, beside)", PART2_CORRECTED, ("R0", None)))
    lines.append("\nTest neonates (never used for choosing):")
    lines.append(f"  {'chain':60s} {'F1 pool':>7s} {'F1 med':>7s} {'pub %':>6s} {'wrong/pub %':>11s} {'score':>7s} {'AUC':>6s}")
    test_res = {}
    for name, c, rule in finals:
        bs = beat_summary(test, c)
        cs = chain_summary(test, c, rule)
        test_res[name] = (bs, cs)
        lines.append(f"  {name:60s} {bs['pooled_f1']:7.2f} {bs['median_f1']:7.2f} {cs['published_pct']:6.1f} "
                     f"{cs['wrong_of_published_pct']:11.2f} {cs['score']:7.2f} {cs['auc']:6.3f}")
    print("\n".join(lines[-(len(finals) + 2):]), flush=True)

    # our captures
    pool, metric, total, ms_range, st_ecg = corpus_report(finals, args.cache)
    lines.append("\nOur captures (F3's measures; ECG subjects pooled; MS100):")
    lo = MS100_MIN_BPM_CORRECTED if corrected else 30.0
    lines.append(f"  {'chain':60s} {'total':>6s} {'pub %':>6s} {'wrong %':>8s} {'start s':>8s} {'range %':>8s} "
                 f"{'MAE':>5s} {f'MS100 {lo:.0f}-240 worst':>18s}")
    for name, _, _ in finals:
        worst = min((r["ok_pct"] for r in ms_range[name] if r["pr_bpm"] >= lo), default=float("nan"))
        lines.append(f"  {name:60s} {total[name]:6.1f} {metric['availability'][name]:6.1f} "
                     f"{metric['honesty'][name]:8.2f} {st_ecg[name]:8.2f} {metric['range'][name]:8.1f} "
                     f"{metric['precision'][name]:5.2f} {worst:18.1f}")

    # adoption rule
    base = finals[0][0]
    lines.append("\nAdoption rule against v0.122 (fixed before measuring):")
    cfg = {name: c for name, c, _ in finals}
    passed = {}
    for name, _, _ in finals[1:]:
        a = total[name] < total[base]
        b = test_res[name][1]["wrong_of_published_pct"] <= test_res[base][1]["wrong_of_published_pct"] + 0.5
        worst = min((r["ok_pct"] for r in ms_range[name] if r["pr_bpm"] >= lo), default=0.0)
        cc = worst >= MS100_MIN_OK
        if corrected:
            se_b, ppv_b = brady_check(cfg[name], brady)
            cc = cc and ppv_b >= BRADY_PPV_MIN and se_b >= BRADY_SE_MIN
            lines.append(f"  {name:60s} real slow pulses Se {se_b:.1f} PPV {ppv_b:.1f}")
        passed[name] = a and b and cc
        lines.append(f"  {name:60s} total lower: {a}; MIMIC test honesty within 0.5: {b}; range kept: {cc} "
                     f"-> {'ADOPT' if passed[name] else 'no'}")
    if args.hp:
        ok_names = [n for n, p in passed.items() if p]
        lines.append("  proposal (lowest weighted total among the chains that pass): "
                     + (min(ok_names, key=lambda n: total[n]) if ok_names else "none, v0.122 stays"))
    txt = "\n".join(lines)
    print("\n" + "\n".join(lines[-(len(finals) + 10):]), flush=True)
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
