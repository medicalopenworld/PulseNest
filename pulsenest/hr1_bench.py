"""Family 1 of the heartbeat resolvers (HR1: beats in time) on the offline bench.

Plan of 2026-11-15/16 for HR1LAB (memory project_hr1lab_plan_20261115): chains = detector x
publication rule, compared as whole chains (library rationale §5.4: a quality gate downstream absorbs
exactly the errors a detector compared alone shows). Everything here is CAUSAL and processes blocks:
state is carried from one block to the next, so the study feeds whole runs and the lab (HR1LAB) feeds
its 20 ms drain blocks through the same code, and both get the same beats (test_pulsenest/
hr1_bench_test.py checks the block invariance).

Front ends
  FrontEnd       the COMMON front end of every HR1 method (Alex, 2026-11-16: one biquad filter for all,
                 the moving average of today's HR1 has no advantage left): HR3's 4th-order Butterworth
                 low-pass at 15 Hz at the AFE rate (shareable on the board), negated (peaks up),
                 decimated to 100 Hz (Charlton 2022's rate), 2nd-order Butterworth high-pass at 0.5 Hz
                 (HR2's corner). Keeps the 2nd and 3rd harmonics up to 260 bpm.
  LibFrontEnd    the library's HR1 front end (v0.121): DC IIR tau 1.6 s from zero, negated, moving
                 average of fs / 10 samples (capped at 64). Only to check that the bench reproduces the
                 board's HR1 (experiments/hr1_board_mirror_20261116.py); not a candidate.

Detectors (times in samples of their input rate; each beat = (t_beat, t_decided, rr_s or nan))
  ThrDetector    HR1_THR, the library's detector: rising crossing of 0.6 x a running max decaying with
                 tau 1.5 s, refractory 0.185 s. Faithful to a quirk of _hr1_update: a crossing inside the
                 refractory is not a beat but restarts the interval, so the next interval is measured
                 from it (rr is given explicitly for that reason). On the common front end the crossing
                 is interpolated linearly (10 ms samples); on the library front end it is not.
  TermaDetector  HR1_TERMA, two event-related moving averages (Elgendi et al. 2013, PLoS ONE 8(10)
                 e76585; "ERMA" in Charlton's ppg-beats, MIT licence, read 2026-11-16): clip negatives,
                 square, MA 111 ms (peak) and 667 ms (beat), offset alpha = 0.02 x mean of the squared
                 signal, blocks where MA_peak > MA_beat + alpha lasting >= 111 ms, beat = maximum of the
                 signal in the block. Causal adaptation: the published MAs run forward and backward
                 (filtfilt = a triangular window of 2W - 1, centred); here each MA runs twice forward and
                 the peak MA is delayed so both are centred on the same sample (latency W2 - 1, 0.66 s);
                 the mean for alpha is the running mean since the probe was applied (published: the whole
                 recording). Its own 0.5-8 Hz band-pass is replaced by the common front end.
  SsfDetector    HR1_SSF, qppg: slope sum function (Zong et al. 2003, Computers in Cardiology 30:259-262,
                 wabp; adapted to PPG by Q. Li, PhysioNet Cardiovascular Signal Toolbox, Vest et al. 2018).
                 Written here from the algorithm, not translated from the GPL code. Slope window 0.17 s,
                 eye-closing 0.34 s, learning period 8 s replayed (as the original, which starts over),
                 threshold Ta = 3 x mean SSF, T1 = Ta / 3, Ta decays by 1 after 2.5 s without a pulse, floor
                 5; the beat is the onset (valley) found from the 2/3 point of the SSF rise. Causal
                 adaptation: the original rescales the record to +-2000 with its whole min/max; here the
                 scale is the learning period's min/max. Note: the 0.34 s eye-closing locks out beats
                 above ~176 bpm with the published value.
  MsptdDetector  HR1_MSPTD, multi-scale peak and trough detection (Bishop & Ercole 2018, Acta Neurochir
                 Suppl 126, doi 10.1007/978-3-319-65798-1_39; Charlton's implementation, MIT): 6 s windows with 20 % overlap,
                 linear detrend, local-maximum scalogram at scales 1..ceil(N/2)-1, lambda = the scale with
                 the most maxima, peak = a maximum at every scale up to lambda, refined to the highest
                 sample within +-50 ms. A window is processed when it is complete: offline reference,
                 latency up to 6 s.

Publication rules (times in seconds)
  RuleR0         today's: mean of the last 5 RR, hr1_sqi = clamp(1 - CV / 0.15), published when 5 RR,
                 30-260 bpm and sqi > 0. No timeout (as the library).
  RuleR1         own, after Nonin's "flag the beat that does not match the current pulse interval": an RR
                 more than 20 % away from the median of the last 5 accepted is rejected; 3 rejected in a row
                 that agree among themselves (within 20 % of their median) restart the buffer (a real change
                 of rate); published = median of the last 5 accepted; quality = accepted share of the last 8
                 candidates; invalid 3 s after the last accepted beat.
  RuleR2         own: an RR is accepted only within 15 % of HR3_SAC's period when HR3_SAC is valid (rho >=
                 0.5, comb purity >= 0.3); then as R1 (median of 5, quality, 3 s). Not independent of family
                 3: reported apart.
The R1/R2 values were fixed with Alex on 2026-11-16 before measuring.

Part 2 of the study (experiments/hr1_tuning_20261116.py) added options, off by default so part 1 and
the library mirror are unchanged: ThrDetector(refractory_rr=k) and SsfDetector(eye_closing_rr=k), a
refractory / eye-closing of k x the median of the last 5 intervals kept within RR_BOUNDS_S (0.15-0.6 s;
the eye-closing starts at SSF_EC_INIT_S); RuleR1(q_min, cv_max), R1 publishing only while the accepted
share of the last 8 RR reaches q_min and, with cv_max, while the CV of the accepted RR stays under it.

HR1LAB (lab v1.116) draws what each detector decides on, recorded only when asked: ThrDetector.trace
(the threshold at every sample), SsfDetector.t1_trace (each change of T1 after the learning period; the
slope sum is SsfDetector.ssf.v) and TermaDetector.trace (MA_peak and MA_beat + offset on the centred
axis). Recording changes no beat (test_pulsenest/hr1_bench_test.py).

Synthetic signals (synth_ppg) and beat matching (match_beats) serve the tests now and the beat-level
F1 on MIMIC PERform later; the neonatal templates (plan F5) will replace the parametric pulse.
"""
import math

import numpy as np
from scipy.signal import lfilter, lfilter_zi

from pulsenest import hr_bench as hb

# ── common front end ─────────────────────────────────────────────────────────────────────────
HR1_TARGET_HZ = 100.0
HR1_LP_HZ     = hb.LP_HIGH_HZ                 # 15 Hz, the LowPass4 of HR3
HR1_LP_Q      = (0.54119610, 1.30656296)      # 4th-order Butterworth pole pairs (LowPass4)
HR1_HP_HZ     = 0.5
HR1_HP_Q      = 1.0 / math.sqrt(2.0)
OUT_STEP_S    = 0.5                           # the chains are read every 0.5 s (as HR2 / HR3 windows)

# ── library HR1 (incunest_afe4490.cpp, v0.121) ───────────────────────────────────────────────
LIB_DC_TAU_S        = 1.6
LIB_LP_CUTOFF_HZ    = 5.0
LIB_MA_MAX_LEN      = 64
LIB_MAX_DECAY_TAU_S = 1.5
LIB_THRESHOLD_FRAC  = 0.6
LIB_REFRACTORY_S    = 0.185
LIB_SQI_CV_MAX      = 0.15
LIB_N_RR            = 5

# ── papers' values (part 1 of the study) ─────────────────────────────────────────────────────
TERMA_W1_S, TERMA_W2_S, TERMA_BETA = 0.111, 0.667, 0.02
SSF_SLOPE_W_S, SSF_EYE_CLOSING_S, SSF_LEARN_S = 0.17, 0.34, 8.0
SSF_NO_PULSE_S, SSF_T_MIN = 2.5, 5.0
MSPTD_WIN_S, MSPTD_OVERLAP, MSPTD_TOL_S = 6.0, 0.2, 0.05

# ── part 2 (2026-11-16): an RR-proportional refractory / eye-closing is kept within these bounds ──
RR_BOUNDS_S = (0.15, 0.6)
SSF_EC_INIT_S = 0.25          # adaptive eye-closing before two onsets are known

# ── rules R1 / R2 (fixed 2026-11-16) ─────────────────────────────────────────────────────────
R1_TOL, R1_RESTART, R1_Q_WINDOW, R_TIMEOUT_S = 0.20, 3, 8, 3.0
R2_TOL = 0.15


# ============================================================================= filters

def _biquad_hp(f_low, fs, q):
    """2nd-order high-pass by the bilinear transform with prewarping (the form of hb._biquad_lp)."""
    ohm = math.tan(math.pi * f_low / fs); ohm2 = ohm * ohm; inv_q = 1.0 / q
    den = 1.0 + inv_q * ohm + ohm2
    return 1.0 / den, -2.0 / den, 1.0 / den, 2.0 * (ohm2 - 1.0) / den, (1.0 - inv_q * ohm + ohm2) / den


class _Section:
    """One streaming filter (b, a), precharged to steady state on its first input sample, as the
    library's BiquadFilter after reset(); state carried between blocks."""

    def __init__(self, b, a):
        self.b, self.a = np.asarray(b, float), np.asarray(a, float)
        self._zi0 = lfilter_zi(self.b, self.a) if len(self.a) > 1 or len(self.b) > 1 else None
        self.zi = None

    @classmethod
    def biquad(cls, coef):
        b0, b1, b2, a1, a2 = coef
        return cls((b0, b1, b2), (1.0, a1, a2))

    def reset(self):
        self.zi = None

    def process(self, x):
        if len(x) == 0:
            return x
        if self.zi is None:
            self.zi = self._zi0 * x[0]
        y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
        return y


class FrontEnd:
    """The common front end of family 1: LowPass4 15 Hz at fs, negated, one sample in `factor` kept
    (Decimator::step), high-pass 0.5 Hz at the decimated rate. process(x) -> (y, offsets): the output
    samples and, for each, its index in the input block."""

    def __init__(self, fs, target_hz=HR1_TARGET_HZ, lp_hz=HR1_LP_HZ, hp_hz=HR1_HP_HZ):
        self.fs = float(fs)
        # the library's Decimator::configure rounds half away from zero (lroundf): 1250 Hz -> 13
        # -> 96.15 Hz; Python's round() would give 12 (banker's rounding)
        self.factor = max(1, int(math.floor(fs / target_hz + 0.5)))
        self.rate = self.fs / self.factor
        self._lp = [_Section.biquad(hb._biquad_lp(lp_hz, fs, q)) for q in HR1_LP_Q]
        self._hp = _Section.biquad(_biquad_hp(hp_hz, self.rate, HR1_HP_Q))
        self.reset()

    def reset(self):
        for s in self._lp:
            s.reset()
        self._hp.reset()
        self.phase = 0

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        y = x
        for s in self._lp:
            y = s.process(y)
        offsets = np.arange(self.factor - 1 - self.phase, len(x), self.factor)
        self.phase = (self.phase + len(x)) % self.factor
        return self._hp.process(-y[offsets]), offsets


class LibFrontEnd:
    """The library's HR1 front end at the AFE rate (v0.121): DC by an IIR from zero, negated, moving
    average of round(fs / (2 * 5 Hz)) samples capped at 64, buffer from zeros."""

    def __init__(self, fs):
        self.fs = self.rate = float(fs)
        self.factor = 1
        a = math.exp(-1.0 / (LIB_DC_TAU_S * fs))
        n = int(round(fs / (2.0 * LIB_LP_CUTOFF_HZ)))
        self.ma_len = min(max(n, 1), LIB_MA_MAX_LEN)
        self._dc = _Section((1.0 - a,), (1.0, -a))
        self._ma = _Section(np.full(self.ma_len, 1.0 / self.ma_len), (1.0,))
        self.reset()

    def reset(self):
        self._dc.zi = np.zeros(1)
        self._ma.zi = np.zeros(self.ma_len - 1) if self.ma_len > 1 else None

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        raw = -(x - self._dc.process(x))
        y = self._ma.process(raw) if self.ma_len > 1 else raw
        return y, np.arange(len(x))


def _parabola(y_prev, y, y_next):
    den = y_prev - 2.0 * y + y_next
    return 0.5 * (y_prev - y_next) / den if den != 0.0 else 0.0


class _History:
    """The last `keep` samples of a stream, indexed by their global sample number."""

    def __init__(self, keep):
        self.keep = int(keep)
        self.reset()

    def reset(self):
        self.buf = np.zeros(0)
        self.start = 0

    @property
    def end(self):
        return self.start + len(self.buf)

    def append(self, x):
        self.buf = np.concatenate([self.buf, x])
        drop = len(self.buf) - self.keep
        if drop > 0:
            self.buf = self.buf[drop:]
            self.start += drop

    def get(self, i0, i1):
        return self.buf[max(i0, self.start) - self.start:max(i1, self.start) - self.start]

    def at(self, i):
        return self.buf[i - self.start]


# ============================================================================= detectors

class ThrDetector:
    """HR1_THR: the library's adaptive-threshold detector (see the module docstring)."""
    name = "HR1_THR"

    def __init__(self, rate, interpolate=True, threshold_frac=LIB_THRESHOLD_FRAC,
                 decay_tau_s=LIB_MAX_DECAY_TAU_S, refractory_s=LIB_REFRACTORY_S, refractory_rr=None,
                 rr_bounds_s=RR_BOUNDS_S):
        """refractory_rr = k (part 2 of the study, 2026-11-16): the refractory becomes k x the median
        of the last 5 accepted RR, kept within rr_bounds_s; refractory_s until two beats are known."""
        self.rate = float(rate)
        self.interpolate = interpolate
        self.frac = threshold_frac
        self.alpha = math.exp(-1.0 / (decay_tau_s * rate))
        self.refr = refractory_s * rate
        self.refr_rr = refractory_rr
        self.rr_lo, self.rr_hi = rr_bounds_s[0] * rate, rr_bounds_s[1] * rate
        self.latency_s = 0.0                        # decides at the crossing
        self.latency_max_s = self.latency_s         # longest a beat can wait to be decided
        self.trace = None       # a list here records the threshold at every input sample (HR1LAB)
        self.reset()

    def reset(self):
        self.n = 0
        self.rmax = 0.0
        self.above = False
        self.last = None
        self.prev = None
        self.rr = []                                # last accepted RR, decimated samples

    def _refractory(self):
        if self.refr_rr is None or not self.rr:
            return self.refr
        return min(self.rr_hi, max(self.rr_lo, self.refr_rr * float(np.median(self.rr))))

    def push(self, y):
        out = []
        rmax, above, last, prev, n = self.rmax, self.above, self.last, self.prev, self.n
        a, frac, interp = self.alpha, self.frac, self.interpolate
        refr = self._refractory()
        tr = self.trace
        for v in y.tolist():
            rmax = max(rmax * a, v)
            thr = frac * rmax
            if tr is not None:
                tr.append(thr)
            if v > thr and not above:
                above = True
                tc = float(n)
                if interp and prev is not None and v != prev:
                    tc = n - 1 + (thr - prev) / (v - prev)
                if last is not None and tc - last > refr:
                    out.append((tc, float(n), (tc - last) / self.rate))
                    if self.refr_rr is not None:
                        self.rr = (self.rr + [tc - last])[-LIB_N_RR:]
                        refr = self._refractory()
                elif last is None:
                    out.append((tc, float(n), math.nan))
                last = tc
            elif v <= thr:
                above = False
            prev = v
            n += 1
        self.rmax, self.above, self.last, self.prev, self.n = rmax, above, last, prev, n
        return out


def _odd(n):
    n = int(round(n))
    return n if n % 2 else n + 1


class TermaDetector:
    """HR1_TERMA (see the module docstring)."""
    name = "HR1_TERMA"

    def __init__(self, rate, w1_s=TERMA_W1_S, w2_s=TERMA_W2_S, beta=TERMA_BETA):
        self.rate = float(rate)
        self.w1, self.w2 = _odd(w1_s * rate), _odd(w2_s * rate)
        self.beta = beta
        self.delay = self.w2 - self.w1              # peak MA delayed to the beat MA's centre
        self.lag = self.w2 - 1                      # centre of both = n - lag
        self.latency_s = self.lag / self.rate
        self.latency_max_s = self.latency_s + self.w2 / self.rate   # plus a block up to a beat long
        # A list here records, per call, (first sample, MA_peak, MA_beat + offset) on the centred
        # time axis: what the blocks of interest are decided on (HR1LAB).
        self.trace = None
        self.reset()

    def reset(self):
        mk = lambda w: [_Section(np.full(w, 1.0 / w), (1.0,)) for _ in range(2)]
        self.map, self.mab = mk(self.w1), mk(self.w2)
        for s in self.map + self.mab:
            s.zi = np.zeros(len(s.b) - 1)
        self.p_tail = np.zeros(self.delay)
        self.zsum, self.zn = 0.0, 0
        self.hist = _History(int(8 * self.rate))
        self.n = 0
        self.in_block, self.block_start = False, 0

    def push(self, y):
        y = np.asarray(y, float)
        out = []
        step = int(self.rate)                              # the history holds 8 s: feed it 1 s at a time
        for i in range(0, len(y), step):
            out.extend(self._push(y[i:i + step]))
        return out

    def _push(self, y):
        if len(y) == 0:
            return []
        self.hist.append(y)
        z = np.maximum(y, 0.0) ** 2
        p = self.map[1].process(self.map[0].process(z))
        b = self.mab[1].process(self.mab[0].process(z))
        pd = np.concatenate([self.p_tail, p])
        self.p_tail = pd[len(pd) - self.delay:] if self.delay else np.zeros(0)
        p_al = pd[:len(p)]
        cz = self.zsum + np.cumsum(z)
        cnt = self.zn + np.arange(1, len(z) + 1)
        self.zsum, self.zn = float(cz[-1]), int(cnt[-1])
        thr = b + self.beta * cz / cnt
        cond = p_al > thr
        out = []
        n0 = self.n
        if self.trace is not None:
            k0 = max(0, self.lag - n0)                     # centred index n0 + i - lag >= 0
            if k0 < len(y):
                self.trace.append((n0 + k0 - self.lag, p_al[k0:].copy(), thr[k0:].copy()))
        for i, c in enumerate(cond.tolist()):
            m = n0 + i - self.lag
            if m < 0:
                continue
            if c and not self.in_block:
                self.in_block, self.block_start = True, m
            elif not c and self.in_block:
                self.in_block = False
                if m - self.block_start >= self.w1:
                    seg = self.hist.get(self.block_start, m)
                    if len(seg):
                        k = int(np.argmax(seg))
                        g = self.block_start + k
                        t = float(g)
                        if self.hist.start < g < n0 + i:
                            t += _parabola(self.hist.at(g - 1), self.hist.at(g), self.hist.at(g + 1))
                        out.append((t, float(n0 + i), math.nan))
        self.n += len(y)
        return out


class _Grow:
    """A float array that grows by appending, in amortised O(1) per sample (doubling capacity)."""

    def __init__(self):
        self.a = np.zeros(1024)
        self.n = 0

    def extend(self, x):
        need = self.n + len(x)
        if need > len(self.a):
            cap = len(self.a)
            while cap < need:
                cap *= 2
            b = np.zeros(cap)
            b[:self.n] = self.a[:self.n]
            self.a = b
        self.a[self.n:need] = x
        self.n = need

    @property
    def v(self):
        return self.a[:self.n]


class SsfDetector:
    """HR1_SSF, qppg (see the module docstring). Indices are global since reset; the arrays grow with
    the run (a few hours at 100 Hz are ~1e6 samples per array)."""
    name = "HR1_SSF"

    def __init__(self, rate, slope_w_s=SSF_SLOPE_W_S, eye_closing_s=SSF_EYE_CLOSING_S,
                 learn_s=SSF_LEARN_S, no_pulse_s=SSF_NO_PULSE_S, t_min=SSF_T_MIN, eye_closing_rr=None,
                 rr_bounds_s=RR_BOUNDS_S):
        """eye_closing_rr = k (part 2 of the study, 2026-11-16): the eye-closing becomes k x the median
        of the last 5 intervals between onsets, kept within rr_bounds_s; SSF_EC_INIT_S until two
        onsets are known. The look-ahead the detector waits for is then the upper bound, so the
        decisions do not depend on how the input is fed."""
        r = self.rate = float(rate)
        self.w = int(round(slope_w_s * r))
        self.ec_rr = eye_closing_rr
        if eye_closing_rr is None:
            self.ec = int(round(eye_closing_s * r))
            self.ec_min = self.ec_max = self.ec
        else:
            self.ec = int(round(SSF_EC_INIT_S * r))
            self.ec_min, self.ec_max = int(round(rr_bounds_s[0] * r)), int(round(rr_bounds_s[1] * r))
        self.ec0 = self.ec
        self.half_ec = self.ec // 2
        self.learn = int(round(learn_s * r))
        self.expect = int(round(no_pulse_s * r))
        self.t_min = t_min
        self.d40, self.d24, self.d16 = int(round(0.04 * r)), int(round(0.024 * r)), int(round(0.016 * r))
        self.v_back, self.v_fwd = int(round(0.20 * r)), int(round(0.05 * r))
        self.latency_s = (self.ec_max + 1) / r        # the eye-closing look-ahead
        self.latency_max_s = self.latency_s
        # A list here records (sample, T1) every time the detection threshold changes after the
        # learning period: T1 holds from that sample to the next record (HR1LAB). The slope sum
        # itself is self.ssf.v.
        self.t1_trace = None
        self.reset()

    def reset(self):
        self.pending = []                  # input held until the learning period is complete
        self.data, self.dy, self.ssf = _Grow(), _Grow(), _Grow()
        self.scale = None
        self.t = 0
        self.learning = True
        self.T0 = self.Ta = self.T1 = 0.0
        self.timer = 0
        self.last_beat = -1
        self.ec = self.ec0
        self.half_ec = self.ec // 2
        self.onset_rr = []                 # intervals between emitted onsets (adaptive eye-closing)

    def _extend(self, y):
        """Rescale (learning-period min/max -> +-2000) and append the slope sum of the new samples."""
        lo, hi = self.scale
        d = (np.asarray(y, float) - lo) / (hi - lo) * 4000.0 - 2000.0
        prev = self.data.v[-1] if self.data.n else d[0]
        dy = np.maximum(np.diff(np.concatenate([[prev], d])), 0.0)
        tail = self.dy.v[max(0, self.dy.n - (self.w - 1)):]
        c = np.concatenate([[0.0], np.cumsum(np.concatenate([tail, dy]))])
        k = len(tail) + np.arange(len(dy))                 # position of each new sample in c[1:]
        ssf = c[k + 1] - c[np.maximum(k + 1 - self.w, 0)]
        self.data.extend(d); self.dy.extend(dy); self.ssf.extend(ssf)

    def push(self, y):
        y = np.asarray(y, float)
        if self.scale is None:
            self.pending.extend(y.tolist())
            if len(self.pending) < self.learn + self.ec_max + 2:
                return []
            first = np.asarray(self.pending)
            lo, hi = float(first[:self.learn].min()), float(first[:self.learn].max())
            self.scale = (lo, hi if hi > lo else lo + 1.0)
            self.pending = None
            self._extend(first)
            self.T0 = float(np.mean(self.ssf.v[:self.learn + 1]))
            self.Ta = 3.0 * self.T0
        else:
            self._extend(y)
        return self._run()

    def _run(self):
        out = []
        s, d = self.ssf.v, self.data.v
        N = len(s)
        while True:
            t = self.t
            if self.learning:
                if t > self.learn:                         # learning done: start over from the beginning
                    self.learning = False
                    self.T1 = self.T0
                    self.t = t = 0
                    if self.t1_trace is not None:
                        self.t1_trace.append((0, self.T1))
                else:
                    self.T1 = 2.0 * self.T0
            if t + self.ec_max + 1 >= N:
                break
            if s[t] > self.T1:
                self.timer = 0
                seg = s[t + 1:t + self.ec]
                if not (len(seg) and seg.max() > s[t]):   # no larger slope sum ahead: move on
                    self.t = t + 1
                    continue
                k = int(np.argmax(seg))
                maxd, tmax = float(seg[k]), t + 1 + k
                lo = max(t - self.half_ec + 1, 1)
                mind = min(float(s[lo:tmax + 1].min()), maxd)
                if maxd > mind + 10.0:
                    onset = (maxd - mind) / 100.0 + 2.0
                    tpq = t - self.d40
                    thr23 = (maxd - mind) * 2.0 / 3.0
                    tt = tmax
                    for tt in range(tmax, lo - 1, -1):     # down to the 2/3 point of the rise
                        if s[tt] < thr23:
                            break
                    stop = max(t - self.half_ec + self.d24, self.d24)
                    for tt2 in range(tt, stop - 1, -1):    # then down to where the slope flattens
                        if s[tt2] - s[tt2 - self.d24] < onset:
                            tpq = tt2 - self.d16
                            break
                    v = int(round(tpq))
                    if v > 0:
                        for vi in range(max(1, v - self.v_back), min(v + self.v_fwd, len(d) - 2) + 1):
                            if d[v] > d[vi] and d[vi] <= d[vi - 1] and d[vi] <= d[vi + 1]:
                                v = vi
                    if not self.learning and v > self.last_beat and v > 0:
                        # decided once the eye-closing look-ahead is in, and never before the
                        # learning period (whose beats are replayed when it ends)
                        decided = max(t + self.ec + 1, self.learn + self.ec_max + 1)
                        out.append((float(v), float(decided), math.nan))
                        if self.ec_rr is not None and self.last_beat > 0:
                            self.onset_rr = (self.onset_rr + [v - self.last_beat])[-LIB_N_RR:]
                            ec = self.ec_rr * float(np.median(self.onset_rr))
                            self.ec = int(round(min(self.ec_max, max(self.ec_min, ec))))
                            self.half_ec = self.ec // 2
                        self.last_beat = v
                    self.Ta += (maxd - self.Ta) / 10.0
                    self.T1 = self.Ta / 3.0
                    if self.t1_trace is not None and not self.learning:
                        self.t1_trace.append((t, self.T1))
                    self.t = int(tpq + self.ec) + 1        # eye-closing: no detection for 0.34 s (papers)
                    continue
            elif not self.learning:
                self.timer += 1
                if self.timer > self.expect and self.Ta > self.t_min:
                    self.Ta -= 1.0
                    self.T1 = self.Ta / 3.0
                    if self.t1_trace is not None:
                        self.t1_trace.append((t, self.T1))
            self.t = t + 1
        return out


class MsptdDetector:
    """HR1_MSPTD (see the module docstring). Offline reference: a window is processed when complete."""
    name = "HR1_MSPTD"

    def __init__(self, rate, win_s=MSPTD_WIN_S, overlap=MSPTD_OVERLAP, tol_s=MSPTD_TOL_S):
        self.rate = float(rate)
        self.N = int(round(win_s * rate))
        self.step = max(1, int(round(self.N * (1.0 - overlap))))
        self.tol = int(math.ceil(tol_s * rate))
        self.latency_s = self.N / self.rate           # a beat waits for its window to be complete
        self.latency_max_s = (self.N + self.step) / self.rate   # ... and for the next window to start
        self.reset()

    def reset(self):
        self.hist = _History(2 * self.N + self.tol + 2)
        self.next_end = self.N
        self.n = 0
        self.emitted = []

    def _window_peaks(self, x):
        N = len(x)
        t = np.arange(N, dtype=float)
        A = np.vstack([t, np.ones(N)]).T
        coef, *_ = np.linalg.lstsq(A, x, rcond=None)
        x = x - A @ coef
        L = int(math.ceil(N / 2.0)) - 1
        counts = np.zeros(L)
        rows = []
        for k in range(1, L + 1):
            m = np.zeros(N, dtype=bool)
            m[k:N - k] = (x[k:N - k] > x[:N - 2 * k]) & (x[k:N - k] > x[2 * k:])
            rows.append(m)
            counts[k - 1] = m.sum()
        lam = int(np.argmax(counts)) + 1
        allm = np.logical_and.reduce(rows[:lam]) if lam > 0 else np.zeros(N, dtype=bool)
        return np.flatnonzero(allm)

    def push(self, y):
        y = np.asarray(y, float)
        out = []
        for i in range(0, len(y), self.step):              # the history holds two windows only
            out.extend(self._push(y[i:i + self.step]))
        return out

    def _push(self, y):
        self.hist.append(y)
        self.n += len(y)
        out = []
        while self.n >= self.next_end:
            e = self.next_end
            s0 = e - self.N
            x = self.hist.get(s0, e)
            for p in self._window_peaks(x):
                g = s0 + int(p)
                a, b = max(g - self.tol, self.hist.start, s0), min(g + self.tol + 1, e)
                seg = self.hist.get(a, b)
                if len(seg) == 0:
                    continue
                g = a + int(np.argmax(seg))
                if any(abs(g - e_) <= self.tol for e_ in self.emitted):
                    continue
                tb = float(g)
                if self.hist.start < g < self.n - 1:
                    tb += _parabola(self.hist.at(g - 1), self.hist.at(g), self.hist.at(g + 1))
                out.append((tb, float(e - 1), math.nan))
                self.emitted.append(g)
            self.emitted = [e_ for e_ in self.emitted if e_ >= e - self.N - self.tol]
            self.next_end += self.step
        return out


DETECTORS = (ThrDetector, TermaDetector, SsfDetector, MsptdDetector)


# ============================================================================= rules

class RuleR0:
    """Today's rule (see the module docstring)."""
    name = "R0"

    def __init__(self, n=LIB_N_RR, cv_max=LIB_SQI_CV_MAX):
        self.n, self.cv_max = n, cv_max
        self.reset()

    def reset(self):
        self.rr = []

    def on_beat(self, rr_s, t_s, anchor_s=None):
        if math.isfinite(rr_s):
            self.rr = (self.rr + [rr_s])[-self.n:]

    def state(self, t_s):
        if len(self.rr) < self.n:
            return math.nan, 0.0, False
        mean = sum(self.rr) / self.n
        hr = 60.0 / mean
        if not (hb.HR_MIN <= hr <= hb.HR_MAX):
            return math.nan, 0.0, False
        cv = math.sqrt(sum((r - mean) ** 2 for r in self.rr) / self.n) / mean
        sqi = min(1.0, max(0.0, 1.0 - cv / self.cv_max))
        return hr, sqi, sqi > 0.0


class RuleR1:
    """Own rule after Nonin (see the module docstring)."""
    name = "R1"

    def __init__(self, n=LIB_N_RR, tol=R1_TOL, restart=R1_RESTART, q_window=R1_Q_WINDOW,
                 timeout_s=R_TIMEOUT_S, q_min=0.0, cv_max=None):
        """q_min, cv_max (part 2 of the study, 2026-11-16): publish only while the accepted share of the
        last q_window candidates is at least q_min and, when cv_max is set, while the CV of the
        accepted RR is at most cv_max (R0's gate over R1's beats). Defaults = R1 as first measured."""
        self.n, self.tol, self.restart, self.qw, self.timeout = n, tol, restart, q_window, timeout_s
        self.q_min, self.cv_max = q_min, cv_max
        self.reset()

    def reset(self):
        self.acc, self.rej, self.hist = [], [], []
        self.t_acc = -math.inf

    def _accept(self, rr_s, t_s):
        self.acc = (self.acc + [rr_s])[-self.n:]
        self.rej = []
        self.hist = (self.hist + [1])[-self.qw:]
        self.t_acc = t_s

    def _reject(self, rr_s):
        self.hist = (self.hist + [0])[-self.qw:]
        self.rej = (self.rej + [rr_s])[-self.restart:]

    def on_beat(self, rr_s, t_s, anchor_s=None):
        if not math.isfinite(rr_s):
            return
        ref = float(np.median(self.acc)) if len(self.acc) >= 3 else None
        if ref is None or abs(rr_s - ref) <= self.tol * ref:
            self._accept(rr_s, t_s)
            return
        self._reject(rr_s)
        if len(self.rej) >= self.restart:
            m = float(np.median(self.rej))
            if all(abs(r - m) <= self.tol * m for r in self.rej):
                self.acc, self.rej, self.t_acc = list(self.rej), [], t_s

    def state(self, t_s):
        q = sum(self.hist) / self.qw
        if len(self.acc) < self.n or t_s - self.t_acc > self.timeout:
            return math.nan, q, False
        hr = 60.0 / float(np.median(self.acc))
        if not (hb.HR_MIN <= hr <= hb.HR_MAX):
            return math.nan, 0.0, False
        if q < self.q_min:
            return hr, q, False
        if self.cv_max is not None:
            a = np.asarray(self.acc[-self.n:], float)
            if float(a.std() / a.mean()) > self.cv_max:
                return hr, q, False
        return hr, q, True


class RuleR2(RuleR1):
    """Own rule anchored to HR3_SAC's period (see the module docstring)."""
    name = "R2"

    def __init__(self, tol=R2_TOL, **kw):
        super().__init__(**kw)
        self.tol2 = tol

    def on_beat(self, rr_s, t_s, anchor_s=None):
        if not math.isfinite(rr_s):
            return
        if anchor_s is not None and math.isfinite(anchor_s) and abs(rr_s - anchor_s) <= self.tol2 * anchor_s:
            self._accept(rr_s, t_s)
        else:
            self._reject(rr_s)


RULES = (RuleR0, RuleR1, RuleR2)


# ============================================================================= drivers

def detect(x, fs, front_end, detector, block=None):
    """Run a front end and a detector over one run of the probe applied (raw samples at fs).
    Returns beats as an array (n, 3): beat time and decision time in RAW rows from the run's start
    (float), and the explicit RR in seconds (nan where the RR is the difference of beat times).
    block = None feeds the run at once; an int feeds it in blocks of that many raw samples."""
    front_end.reset()
    detector.reset()
    fac = front_end.factor
    out = []
    step = max(len(x) if not block else int(block), 1)
    for i in range(0, len(x), step):
        y, _ = front_end.process(x[i:i + step])
        if len(y):
            out.extend(detector.push(y))
    if not out:
        return np.zeros((0, 3))
    a = np.asarray(out, dtype=float)
    a[:, 0] = a[:, 0] * fac + (fac - 1)          # output sample k = raw row k * fac + fac - 1
    a[:, 1] = a[:, 1] * fac + (fac - 1)
    return a


def rr_of(beats, fs):
    """RR per beat in seconds: the explicit one where given, else the difference of beat times."""
    if len(beats) == 0:
        return np.zeros(0)
    rr = np.concatenate([[math.nan], np.diff(beats[:, 0]) / fs])
    ex = np.isfinite(beats[:, 2])
    rr[ex] = beats[ex, 2]
    return rr


def apply_rule(beats, fs, rule, out_rows, anchor=None, latency_s=0.0, return_last=False):
    """Replay the beats in the order they were decided and read the rule at each output row (raw rows
    from the run's start). anchor(t_row) -> HR3_SAC's period in s or None, read at the decision time.
    latency_s = the detector's own decision delay: a rule's timeout counts from the time the detector
    has seen up to, not from the output row (MSPTD decides up to 6 s late and would always time out).
    Returns hr, quality, valid at out_rows; with return_last also the beat time (raw rows) of the last
    beat the rule had consumed at each row (nan before the first), so a reference can be read over the
    beats the value was computed from whatever the detector's latency."""
    rule.reset()
    rr = rr_of(beats, fs)
    order = np.argsort(beats[:, 1], kind="stable") if len(beats) else np.zeros(0, dtype=int)
    hr = np.full(len(out_rows), math.nan); q = np.zeros(len(out_rows)); v = np.zeros(len(out_rows), bool)
    last = np.full(len(out_rows), math.nan)
    j = 0
    t_last = math.nan
    for k, r in enumerate(out_rows):
        while j < len(order) and beats[order[j], 1] <= r:
            b = order[j]
            rule.on_beat(rr[b], beats[b, 0] / fs, anchor(beats[b, 1]) if anchor else None)
            t_last = beats[b, 0] if not math.isfinite(t_last) else max(t_last, beats[b, 0])
            j += 1
        hr[k], q[k], v[k] = rule.state(r / fs - latency_s)
        last[k] = t_last
    return (hr, q, v, last) if return_last else (hr, q, v)


SAC_RHO_MIN, SAC_PURITY_MIN = 0.5, 0.3       # HR3_SAC's validity, as experiments/hr2_methods_20261115.py


def sac_anchor(d):
    """R2's anchor for a session: HR3_SAC on every HR3 window of the bench (hr_bench.hr3_spectra),
    valid when rho >= 0.5 and comb purity >= 0.3. Returns make(r0, r1) -> anchor(row from r0) giving
    the period in seconds of the last window that ended at or before that row inside the applied run
    [r0, r1), or None (no window yet, or the last one invalid)."""
    P, ends, rate = hb.hr3_spectra(d)
    if len(ends) == 0:
        return lambda r0, r1: (lambda row: None)
    hr, rho, _, _ = hb.hr3_sac(P, rate)
    pur = hb.comb_purity(P, hr, rate)
    ok = np.isfinite(hr) & (rho >= SAC_RHO_MIN) & (pur >= SAC_PURITY_MIN)
    period = np.where(ok, 60.0 / np.where(ok, hr, 1.0), np.nan)

    def make(r0, r1):
        def anchor(row):
            k = int(np.searchsorted(ends, r0 + row, side="right")) - 1
            if k < 0 or ends[k] < r0 or not np.isfinite(period[k]):
                return None
            return float(period[k])
        return anchor
    return make


def output_rows(n_raw, fs, step_s=OUT_STEP_S):
    """The raw rows (from the run's start) at which the chains are read: every 0.5 s."""
    step = int(round(step_s * fs))
    return np.arange(step - 1, n_raw, step)


# ============================================================================= ECG reference beats

# Charlton et al. 2022 (Physiol Meas 43 085007, methods read 2026-11-16): reference beats = the beats two
# ECG detectors (jqrs and rpeakdetect) agree on within 150 ms; a 20 s window where they disagree is
# excluded, and so is one with a flat PPG line longer than 0.2 s; a reference beat is correctly
# detected when the closest PPG beat is within +-150 ms, after the lag (-10..+10 s, 20 ms steps) that
# detects the most; Se = correct / reference, PPV = correct / PPG beats, F1 their harmonic mean, per
# recording, reported as median (IQR). Here the two ECG detectors are our own, of different design
# (not jqrs and rpeakdetect): the agreement rule is what protects the reference.
REF_TOL_S, REF_WIN_S, REF_FLAT_S = 0.150, 20.0, 0.2
LAG_RANGE_S, LAG_STEP_S = 10.0, 0.02


def _sos_band(lo, hi, fs, order=2):
    from scipy.signal import butter
    return butter(order, [lo, hi], btype="band", fs=fs, output="sos")


def qrs_pan_tompkins(ecg, fs):
    """QRS detector A (offline): Pan & Tompkins 1985 in outline. Band-pass 5-15 Hz (zero phase),
    derivative, square, 150 ms moving integration, peaks at least 200 ms apart, adaptive signal and
    noise levels (threshold = noise + 0.25 x (signal - noise)), search-back at half the threshold when
    no QRS for 1.66 average RR. The R wave = largest |band-passed ECG| in the integration window."""
    from scipy.signal import find_peaks, sosfiltfilt
    bp = sosfiltfilt(_sos_band(5.0, 15.0, fs), ecg)
    sq = np.gradient(bp) ** 2
    w = max(1, int(round(0.150 * fs)))
    mwi = np.convolve(sq, np.ones(w) / w)[:len(sq)]
    pk, _ = find_peaks(mwi, distance=max(1, int(round(0.2 * fs))))
    if len(pk) == 0:
        return np.zeros(0)
    head = mwi[:int(2 * fs)]
    spki, npki = 0.25 * float(head.max()), 0.5 * float(head.mean())
    qrs, noise_pk, rr = [], [], []
    for p in pk:
        thr = npki + 0.25 * (spki - npki)
        if mwi[p] > thr:
            spki = 0.125 * mwi[p] + 0.875 * spki
            qrs.append(p)
        else:
            npki = 0.125 * mwi[p] + 0.875 * npki
            noise_pk.append(p)
        if len(qrs) >= 2:
            rr = (rr + [qrs[-1] - qrs[-2]])[-8:]
        if rr and len(qrs) and p - qrs[-1] > 1.66 * np.mean(rr):
            cand = [q for q in noise_pk if qrs[-1] + 0.2 * fs < q < p and mwi[q] > 0.5 * thr]
            if cand:
                q = max(cand, key=lambda i: mwi[i])
                spki = 0.25 * mwi[q] + 0.75 * spki
                qrs.append(q)
                qrs.sort()
                noise_pk = [i for i in noise_pk if i != q]
    r = []
    for q in qrs:
        a = max(0, q - w)
        r.append(a + int(np.argmax(np.abs(bp[a:q + 1]))))
    r = np.unique(r)
    keep = [r[0]] if len(r) else []
    for i in r[1:]:                                    # two R waves closer than 200 ms: keep the larger
        if i - keep[-1] < 0.2 * fs:
            if abs(bp[i]) > abs(bp[keep[-1]]):
                keep[-1] = i
        else:
            keep.append(i)
    return np.asarray(keep, dtype=float)


def qrs_envelope(ecg, fs):
    """QRS detector B (offline), of a different design: band-pass 8-30 Hz (zero phase), |.|, local
    maxima at least 200 ms apart above 0.4 x the local amplitude (median over 5 s of the 1 s maxima)."""
    from scipy.signal import find_peaks, sosfiltfilt
    e = np.abs(sosfiltfilt(_sos_band(8.0, min(30.0, 0.45 * fs), fs), ecg))
    pk, _ = find_peaks(e, distance=max(1, int(round(0.2 * fs))))
    if len(pk) == 0:
        return np.zeros(0)
    blk = int(round(fs))
    nb = int(math.ceil(len(e) / blk))
    bmax = np.array([e[i * blk:(i + 1) * blk].max() for i in range(nb)])
    loc = np.array([np.median(bmax[max(0, i - 2):i + 3]) for i in range(nb)])
    thr = 0.4 * np.interp(np.arange(len(e)), np.arange(nb) * blk + blk / 2.0, loc)
    return pk[e[pk] > thr[pk]].astype(float)


def _pair(a, b, tol):
    """One-to-one matching of two sorted beat lists within tol (greedy in time). Returns (matched pairs
    as index arrays ia, ib; unmatched a; unmatched b)."""
    i = j = 0
    ia, ib = [], []
    while i < len(a) and j < len(b):
        if abs(a[i] - b[j]) <= tol:
            ia.append(i); ib.append(j); i += 1; j += 1
        elif a[i] < b[j]:
            i += 1
        else:
            j += 1
    ua = np.setdiff1d(np.arange(len(a)), ia)
    ub = np.setdiff1d(np.arange(len(b)), ib)
    return np.asarray(ia, int), np.asarray(ib, int), ua, ub


def flat_runs(x, fs, min_s=REF_FLAT_S):
    """Sample intervals [s, e) where x stays exactly constant for longer than min_s."""
    same = np.concatenate([[False], np.diff(x) == 0.0])
    edges = np.flatnonzero(np.diff(np.concatenate([[0], same.astype(np.int8), [0]])))
    out = []
    for s, e in zip(edges[::2], edges[1::2]):
        if (e - s + 1) / fs > min_s:
            out.append((s - 1, e))
    return out


def ecg_reference(ecg, ppg, fs, win_s=REF_WIN_S, tol_s=REF_TOL_S):
    """Reference beats (seconds) and the 20 s windows kept: (ref_t, kept [list of (t0, t1)], n_windows).
    A window is dropped where detectors A and B disagree (a beat of either without a partner within
    150 ms) or the PPG is flat for more than 0.2 s."""
    a = qrs_pan_tompkins(ecg, fs) / fs
    b = qrs_envelope(ecg, fs) / fs
    ia, ib, ua, ub = _pair(a, b, tol_s)
    ref = a[ia]
    bad = np.concatenate([a[ua], b[ub]])
    flats = [(s / fs, e / fs) for s, e in flat_runs(ppg, fs)]
    dur = len(ecg) / fs
    kept, n = [], int(dur // win_s)
    for k in range(n):
        t0, t1 = k * win_s, (k + 1) * win_s
        if np.any((bad >= t0) & (bad < t1)):
            continue
        if any(s < t1 and e > t0 for s, e in flats):
            continue
        kept.append((t0, t1))
    return ref, kept, n


def _inside(t, windows):
    m = np.zeros(len(t), dtype=bool)
    for t0, t1 in windows:
        m |= (t >= t0) & (t < t1)
    return m


def beat_scores(ref_t, det_t, windows, tol_s=REF_TOL_S, lag_range_s=LAG_RANGE_S, lag_step_s=LAG_STEP_S,
                lag_lo_s=None, lag_hi_s=None):
    """Charlton 2022's beat-level scoring on the kept windows: the lag (det - ref) that detects the most
    reference beats, then n_ref, n_det, n_correct (reference beats whose closest detected beat, shifted
    by the lag, is within tol). Returns dict with se, ppv, f1 (%), lag_s and the counts.
    The lag is searched over -lag_range_s..+lag_range_s (Charlton's +-10 s) unless lag_lo_s / lag_hi_s
    narrow it: on a regular rhythm the lags a whole beat apart detect almost as many beats, so the
    unrestricted search can land several beats away (harmless for the counts, not for reading a
    reference rate at the right time; checked on 2026-11-16, MIMIC PERform record 008)."""
    ref = np.sort(np.asarray(ref_t, float))
    det = np.sort(np.asarray(det_t, float))
    ref = ref[_inside(ref, windows)]
    out = {"n_ref": len(ref), "n_det": 0, "n_correct": 0, "lag_s": math.nan,
           "se": math.nan, "ppv": math.nan, "f1": math.nan}
    if len(ref) == 0 or len(det) == 0:
        return out

    def closest_ok(lag):
        d = det - lag
        k = np.clip(np.searchsorted(d, ref), 1, len(d) - 1)
        near = np.minimum(np.abs(d[k] - ref), np.abs(d[k - 1] - ref))
        return near <= tol_s

    lo = -lag_range_s if lag_lo_s is None else lag_lo_s
    hi = lag_range_s if lag_hi_s is None else lag_hi_s
    lags = np.arange(lo, hi + lag_step_s / 2, lag_step_s)
    hits = np.array([closest_ok(lag).sum() for lag in lags])
    # the lags that detect the most form plateaus (+-tol around the true lag, and one beat period away
    # on a regular rhythm): take the plateau nearest zero lag and its centre, so the tolerance stays
    # symmetric around the true offset (Charlton only says "the lag giving the highest proportion")
    top = np.flatnonzero(hits == hits.max())
    runs = np.split(top, np.flatnonzero(np.diff(top) > 1) + 1)
    centres = [0.5 * (lags[r[0]] + lags[r[-1]]) for r in runs]
    lag = float(min(centres, key=abs))
    ok = closest_ok(lag)
    d = det - lag
    n_det = int(_inside(d, windows).sum())
    n_cor = int(ok.sum())
    se = 100.0 * n_cor / len(ref)
    ppv = 100.0 * n_cor / n_det if n_det else math.nan
    f1 = 2 * se * ppv / (se + ppv) if n_det and (se + ppv) > 0 else 0.0
    out.update(n_det=n_det, n_correct=n_cor, lag_s=lag, se=se, ppv=ppv, f1=f1, ok=ok, ref=ref)
    return out


def ref_hr_at(ref_t, windows, t_s, n_rr=LIB_N_RR):
    """ECG heart rate at each time t (s): 60 / mean of the last n_rr reference RR ending at or before t,
    when those n_rr + 1 beats lie in one run of consecutive kept windows; else nan."""
    ref = np.sort(np.asarray(ref_t, float))
    out = np.full(len(t_s), math.nan)
    if len(ref) <= n_rr:
        return out
    win = sorted(windows)
    runs = []                                         # merge consecutive kept windows into runs
    for t0, t1 in win:
        if runs and abs(runs[-1][1] - t0) < 1e-9:
            runs[-1][1] = t1
        else:
            runs.append([t0, t1])
    k = np.searchsorted(ref, t_s, side="right") - 1
    for i, (t, j) in enumerate(zip(t_s, k)):
        if j < n_rr:
            continue
        a, b = ref[j - n_rr], ref[j]
        if any(r0 <= a and b < r1 for r0, r1 in runs):
            out[i] = 60.0 * n_rr / (b - a)
    return out


# ============================================================================= synthetic signals

def synth_ppg(fs, duration_s, bpm=None, rr_s=None, amp=1000.0, dc=1.0e5, notch=0.3, noise=0.0,
              wander=0.0, wander_hz=0.25, shape_max_s=0.5, seed=0):
    """A raw OT-like PPG (DC minus the pulse, as the photodiode sees it) and the true systolic peak
    times in raw rows. Each beat: a systolic Gaussian at 0.25 of the beat's shape time and a dicrotic
    one at 0.6, widths proportional to it; the shape time is the period up to shape_max_s (120 bpm) and
    stays there below that rate, as systole does not stretch with a long diastole. `notch` = relative
    height of the dicrotic wave. rr_s: list of intervals (else constant 60 / bpm)."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * fs))
    t = np.arange(n) / fs
    if rr_s is None:
        rr_s = [60.0 / bpm] * int(duration_s * bpm / 60.0 + 3)
    onsets = np.concatenate([[0.0], np.cumsum(rr_s)])
    p = np.zeros(n)
    peaks = []
    for o, rr in zip(onsets[:-1], rr_s):
        if o >= duration_s:
            break
        w = min(rr, shape_max_s)
        c1, c2 = o + 0.25 * w, o + 0.6 * w
        p += np.exp(-0.5 * ((t - c1) / (0.09 * w)) ** 2) + notch * np.exp(-0.5 * ((t - c2) / (0.08 * w)) ** 2)
        if c1 < duration_s:
            peaks.append(c1 * fs)
    x = dc - amp * p
    if wander:
        x += wander * amp * np.sin(2 * np.pi * wander_hz * t)
    if noise:
        x += noise * amp * rng.standard_normal(n)
    return x, np.asarray(peaks)


def match_beats(ref, det, tol, max_lag=None):
    """Match detected beats to reference beats (same units) one to one within +-tol after the constant
    lag (searched within +-max_lag on a grid of tol / 4) that matches most; a detector's fiducial
    (onset, crossing, peak) sits a fixed time from the reference's. Returns (tp, fp, fn, lag)."""
    ref, det = np.sort(np.asarray(ref, float)), np.sort(np.asarray(det, float))
    if len(ref) == 0 or len(det) == 0:
        return 0, len(det), len(ref), 0.0
    lags = [0.0] if not max_lag else np.arange(-max_lag, max_lag + tol / 8, tol / 4)

    def greedy(lag):
        d = det - lag
        i = j = tp = 0
        while i < len(ref) and j < len(d):
            if abs(d[j] - ref[i]) <= tol:
                tp += 1; i += 1; j += 1
            elif d[j] < ref[i]:
                j += 1
            else:
                i += 1
        return tp

    tps = [greedy(lag) for lag in lags]
    top = max(tps)
    cand = [lag for lag, tp in zip(lags, tps) if tp == top]
    best = cand[len(cand) // 2]                    # the middle of the lags that match most
    return top, len(det) - top, len(ref) - top, float(best)
