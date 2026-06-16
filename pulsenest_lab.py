import sys
import os
import math
import traceback as _tb
from pathlib import Path

def _crash_handler(exc_type, exc_val, exc_tb):
    with open(os.path.join(os.path.dirname(__file__), "crash.log"), "a") as _f:
        import datetime as _dt
        _f.write(f"\n=== {_dt.datetime.now()} ===\n")
        _tb.print_exception(exc_type, exc_val, exc_tb, file=_f)
sys.excepthook = _crash_handler
import serial
from serial.tools import list_ports
import threading
import queue
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets
from collections import deque, namedtuple
import numpy as np
import time
import datetime
from scipy import signal
from enum import IntEnum


class HRStatus(IntEnum):
    VALID        = 0  # local max found, peak_val >= min_corr, hr in [hr_min, hr_max]
    OUT_OF_RANGE = 1  # local max found, peak_val >= min_corr, but hr outside [hr_min, hr_max]
    INVALID      = 2  # no local max or peak_val < min_corr


HRResult = namedtuple('HRResult', [
    'acorr',      # np.array  — normalized autocorrelation signal (y axis for plotting)
    'lags_s',     # np.array  — lag axis in seconds (x axis for plotting)
    'peak_lag',   # float     — detected fundamental period (s)
    'hr_bpm',     # float     — estimated heart rate (bpm), derived from peak_lag
    'peak_val',   # float     — autocorrelation value at the corrected peak_lag (0–1, quality indicator)
    'hr_status',  # HRStatus  — VALID / OUT_OF_RANGE / INVALID, in decreasing preference order
])


def _estimate_hr_xcorr_v1(seg, fs, max_lag_n, min_lag_s=0.22, min_corr=0.5,
                              hr_min=40, hr_max=300, prominence=0.1):
    """Compute HR estimate via cross-correlation between two overlapping segments of the same signal.

    Uses np.correlate(seg, template, mode='valid') where template = seg[max_lag_n:].
    This is a cross-correlation, not a true autocorrelation: the two vectors share the
    same signal but differ in length and starting sample, introducing a slight asymmetry
    at the edges. See _estimate_hr_autocorr_v2 for the true autocorrelation approach.

    Strategy: find the FIRST significant peak above min_lag_s (not the highest),
    to avoid locking onto harmonics of the fundamental frequency.

    Parameters
    ----------
    seg        : np.array, length = window_n + max_lag_n
    fs         : float, sample rate (Hz)
    max_lag_n  : int, number of samples corresponding to the maximum lag
    min_lag_s  : float, minimum lag to search for peaks (s), equivalent to max detectable HR
    min_corr   : float, minimum autocorrelation value at peak to be considered valid
    hr_min     : float, minimum expected HR (bpm) — below this is OUT_OF_RANGE
    hr_max     : float, maximum expected HR (bpm) — above this is OUT_OF_RANGE
    prominence : float, minimum prominence of peaks passed to signal.find_peaks (0–1 scale).
                 A peak must rise at least this fraction above its surrounding valleys to be
                 considered a candidate. Low values (e.g. 0.05) accept shallow peaks (noisy
                 signals); high values (e.g. 0.3) require well-defined peaks (clean signals).

    Returns
    -------
    HRResult namedtuple — see field documentation above
    """
    template = seg[max_lag_n:]
    acorr = np.correlate(seg, template, mode='valid')[::-1]
    if acorr[0] != 0:
        acorr = acorr / acorr[0]
    lags_s = np.arange(len(acorr)) / fs

    min_idx = int(np.searchsorted(lags_s, min_lag_s))
    if min_idx >= len(acorr):
        return HRResult(acorr, lags_s, 0.0, 0.0, 0.0, HRStatus.INVALID)

    local_peaks, _ = signal.find_peaks(acorr[min_idx:], prominence=prominence)

    # Select the first peak that exceeds min_corr (fundamental period, not a harmonic).
    # Fall back to the highest peak if none meets min_corr.
    peak_idx = None
    for p in local_peaks:
        if acorr[min_idx + p] >= min_corr:
            peak_idx = min_idx + p
            break
    if peak_idx is None:
        if len(local_peaks) > 0:
            peak_idx = min_idx + local_peaks[np.argmax(acorr[min_idx + local_peaks])]
        else:
            peak_idx = min_idx + np.argmax(acorr[min_idx:])

    # Parabolic interpolation for sub-sample peak refinement.
    # Fits a parabola through (peak_idx-1, peak_idx, peak_idx+1) and finds its analytical maximum.
    # delta is the sub-sample correction in samples: positive shifts peak right, negative left.
    # Valid only when the three-point parabola is concave (denominator < 0); otherwise no correction.
    #   delta = 0.5 * (y[n-1] - y[n+1]) / (y[n-1] - 2·y[n] + y[n+1])
    #   peak_lag_refined = (peak_idx + delta) / fs
    if 0 < peak_idx < len(acorr) - 1:
        y_prev, y_curr, y_next = acorr[peak_idx - 1], acorr[peak_idx], acorr[peak_idx + 1]
        denom = y_prev - 2.0 * y_curr + y_next
        delta = 0.5 * (y_prev - y_next) / denom if denom < 0 else 0.0
    else:
        delta = 0.0
    peak_lag = (peak_idx + delta) / fs
    peak_val = acorr[peak_idx]
    hr_bpm   = 60.0 / peak_lag if peak_lag > 0 else 0.0

    if len(local_peaks) == 0 or peak_val < min_corr:
        hr_status = HRStatus.INVALID
    elif hr_min <= hr_bpm <= hr_max:
        hr_status = HRStatus.VALID
    else:
        hr_status = HRStatus.OUT_OF_RANGE

    return HRResult(acorr, lags_s, peak_lag, hr_bpm, peak_val, hr_status)


def _estimate_hr_autocorr_v2(seg, fs, max_lag_n, min_lag_s=0.22, min_corr=0.5,
                              hr_min=40, hr_max=300, prominence=0.1):
    """Compute autocorrelation-based HR estimate using scipy.signal.correlate with FFT.

    Key difference from v1: computes the true autocorrelation of a single vector
    (seg correlated with itself) using FFT-based convolution, which is more efficient
    for long windows and starts both vectors at the same sample (lag 0 = full overlap).
    v1 used two vectors offset by max_lag_n samples and np.correlate in 'valid' mode.

    Parameters
    ----------
    seg        : np.array, length = window_n (only the analysis window, no extra lag samples)
    fs         : float, sample rate (Hz)
    max_lag_n  : int, number of lag samples to extract from the full autocorrelation
    min_lag_s  : float, minimum lag to search for peaks (s), equivalent to max detectable HR
    min_corr   : float, minimum autocorrelation value at peak to be considered valid
    hr_min     : float, minimum expected HR (bpm) — below this is OUT_OF_RANGE
    hr_max     : float, maximum expected HR (bpm) — above this is OUT_OF_RANGE
    prominence : float, minimum prominence of peaks passed to signal.find_peaks (0–1 scale).
                 A peak must rise at least this fraction above its surrounding valleys to be
                 considered a candidate. Low values (e.g. 0.05) accept shallow peaks (noisy
                 signals); high values (e.g. 0.3) require well-defined peaks (clean signals).

    Returns
    -------
    HRResult namedtuple — see field documentation above
    """
    # Full autocorrelation (direct method): result has length 2*N-1, center at index N-1.
    # Positive lags start at index N-1 and extend to the right.
    n = len(seg)
    full = signal.correlate(seg, seg, mode='full', method='fft')
    acorr = full[n - 1: n - 1 + max_lag_n + 1]
    if acorr[0] != 0:
        acorr = acorr / acorr[0]
    lags_s = np.arange(len(acorr)) / fs

    min_idx = int(np.searchsorted(lags_s, min_lag_s))
    if min_idx >= len(acorr):
        return HRResult(acorr, lags_s, 0.0, 0.0, 0.0, HRStatus.INVALID)

    local_peaks, _ = signal.find_peaks(acorr[min_idx:], prominence=prominence)

    # Select the first peak that exceeds min_corr (fundamental period, not a harmonic).
    # Fall back to the highest peak if none meets min_corr.
    peak_idx = None
    for p in local_peaks:
        if acorr[min_idx + p] >= min_corr:
            peak_idx = min_idx + p
            break
    if peak_idx is None:
        if len(local_peaks) > 0:
            peak_idx = min_idx + local_peaks[np.argmax(acorr[min_idx + local_peaks])]
        else:
            peak_idx = min_idx + np.argmax(acorr[min_idx:])

    # Parabolic interpolation for sub-sample peak refinement.
    # Fits a parabola through (peak_idx-1, peak_idx, peak_idx+1) and finds its analytical maximum.
    # delta is the sub-sample correction in samples: positive shifts peak right, negative left.
    # Valid only when the three-point parabola is concave (denominator < 0); otherwise no correction.
    #   delta = 0.5 * (y[n-1] - y[n+1]) / (y[n-1] - 2·y[n] + y[n+1])
    #   peak_lag_refined = (peak_idx + delta) / fs
    if 0 < peak_idx < len(acorr) - 1:
        y_prev, y_curr, y_next = acorr[peak_idx - 1], acorr[peak_idx], acorr[peak_idx + 1]
        denom = y_prev - 2.0 * y_curr + y_next
        delta = 0.5 * (y_prev - y_next) / denom if denom < 0 else 0.0
    else:
        delta = 0.0
    peak_lag = (peak_idx + delta) / fs
    peak_val = acorr[peak_idx]
    hr_bpm   = 60.0 / peak_lag if peak_lag > 0 else 0.0

    if len(local_peaks) == 0 or peak_val < min_corr:
        hr_status = HRStatus.INVALID
    elif hr_min <= hr_bpm <= hr_max:
        hr_status = HRStatus.VALID
    else:
        hr_status = HRStatus.OUT_OF_RANGE

    return HRResult(acorr, lags_s, peak_lag, hr_bpm, peak_val, hr_status)


# --- CONFIGURACIÓN ---
PORT             = 'COM15'
BAUD             = 921600
UDP_DEFAULT_PORT = 5005   # must match UDP_TARGET_PORT in include/wifi_config.h
UDP_CMD_PORT     = 5006   # must match UDP_CMD_PORT in include/wifi_config.h
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulsenest_lab.ini")
CAPTURES_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
os.makedirs(CAPTURES_DIR, exist_ok=True)
WINDOW_SIZE        = 500   # 10 s @ 50 Hz (500 Hz / SERIAL_DOWNSAMPLING_RATIO=10)
PPG_WINDOW_SIZE    = 500   # 10 s — same as WINDOW_SIZE
SPO2_CAL_BUFSIZE   = 3000  # 60 s @ 50 Hz — rolling buffer for SpO2LabWindow
SPO2_RECEIVED_FS   = 50.0  # AFE4490 @ 500 Hz, SERIAL_DOWNSAMPLING_RATIO=10


class SpO2LocalCalc:
    """Replicates firmware _update_spo2() in Python for independent verification.

    Constants must match incunest_afe4490.cpp:
      dc_iir_tau_s=1.6, ac_ema_tau_s=1.0, spo2_min_dc=1000,
      warmup_s=5, spo2_a=104, spo2_b=17, spo2_min=70, spo2_max=100.
    """
    _DC_IIR_TAU_S = 1.6
    _AC_EMA_TAU_S = 1.0
    _SPO2_MIN_DC  = 1000.0
    _WARMUP_S     = 5.0
    SPO2_A        = 114.9208
    SPO2_B        =  30.5547
    _SPO2_MIN     = 70.0
    _SPO2_MAX     = 100.0

    def __init__(self):
        self._fs           = 0.0
        self._dc_alpha     = 0.0
        self._ac_beta      = 0.0
        self._warmup_n     = 0
        self._dc_ir        = 0.0
        self._dc_red       = 0.0
        self._ac2_ir       = 0.0
        self._ac2_red      = 0.0
        self._sample_count = 0

    def _recalc_params(self, fs):
        self._fs       = fs
        self._dc_alpha = np.exp(-1.0 / (self._DC_IIR_TAU_S * fs))
        self._ac_beta  = 1.0 - np.exp(-1.0 / (self._AC_EMA_TAU_S * fs))
        self._warmup_n = int(self._WARMUP_S * fs)

    def reset(self):
        self._dc_ir = self._dc_red = 0.0
        self._ac2_ir = self._ac2_red = 0.0
        self._sample_count = 0
        self._fs = 0.0

    def update(self, ir, red, fs):
        """Process one sample. Returns dict with intermediates, or None during warmup."""
        if fs != self._fs:
            self._recalc_params(fs)

        self._dc_ir  = self._dc_alpha * self._dc_ir  + (1 - self._dc_alpha) * ir
        self._dc_red = self._dc_alpha * self._dc_red + (1 - self._dc_alpha) * red

        ac_ir  = ir  - self._dc_ir
        ac_red = red - self._dc_red
        self._ac2_ir  = self._ac_beta * ac_ir  * ac_ir  + (1 - self._ac_beta) * self._ac2_ir
        self._ac2_red = self._ac_beta * ac_red * ac_red + (1 - self._ac_beta) * self._ac2_red

        self._sample_count += 1
        if (self._sample_count < self._warmup_n or
                self._dc_ir < self._SPO2_MIN_DC or self._dc_red < self._SPO2_MIN_DC):
            return None

        rms_ac_ir  = np.sqrt(self._ac2_ir)
        rms_ac_red = np.sqrt(self._ac2_red)
        if self._dc_ir < 1.0 or self._dc_red < 1.0 or rms_ac_ir < 1.0:
            return None

        R    = (rms_ac_red / self._dc_red) / (rms_ac_ir / self._dc_ir)
        spo2 = self.SPO2_A - self.SPO2_B * R
        return {
            'dc_ir':      self._dc_ir,
            'dc_red':     self._dc_red,
            'rms_ac_ir':  rms_ac_ir,
            'rms_ac_red': rms_ac_red,
            'R':          R,
            'spo2':       spo2,
            'spo2_valid': self._SPO2_MIN <= spo2 <= self._SPO2_MAX,
        }


class HRFFTCalc:
    """FFT-based HR estimator (HR3). Prototype of the planned firmware HR3 algorithm.

    Pipeline per sample:
      led1_aled1 → 2nd-order Butterworth LP 10 Hz → circular buffer 512 samples →
      [every UPDATE_INTERVAL_S] Hann window → rfft → dominant peak in [HR_MIN_HZ, HR_MAX_HZ]
      + parabolic sub-bin interpolation → HR3 (bpm)

    Constants must match the firmware implementation when ported:
      LP_CUTOFF_HZ=10, BUF_LEN=512, UPDATE_INTERVAL_S=0.5, HR_MIN_HZ=0.6667, HR_MAX_HZ=3.5
    """
    LP_CUTOFF_HZ       = 10.0
    BUF_LEN            = 512
    UPDATE_INTERVAL_S  = 0.5
    HR_MIN_HZ          = 40.0 / 60.0  # 0.6667 Hz — 40 BPM — reported valid lower bound (ISO 80601-2-61; neonatal)
    HR_MAX_HZ          = 300.0 / 60.0 # 5.0 Hz    — 300 BPM — reported valid upper bound (neonatal tachycardia)
    # Guard band: internal search extends ±3 BPM beyond the reported valid range.
    # Ensures signals at the boundary are found before the validity gate is applied.
    HR_SEARCH_MIN_HZ   = 22.0 / 60.0  # 0.3667 Hz — 22 BPM
    HR_SEARCH_MAX_HZ   = 303.0 / 60.0 # 5.05 Hz   — 303 BPM

    def __init__(self):
        self._fs           = 0.0
        self._b            = None
        self._a            = None
        self._zi           = None
        self._buf          = np.zeros(self.BUF_LEN)
        self._buf_idx      = 0
        self._buf_count    = 0
        self._update_n     = 0
        self._sample_count = 0
        self.hr_bpm        = 0.0
        self.hr_valid      = False
        # Diagnostic state exposed for HR3LabWindow
        self.last_spectrum         = np.zeros(self.BUF_LEN // 2 + 1)
        self.last_freqs            = np.zeros(self.BUF_LEN // 2 + 1)
        self.last_peak_freq        = 0.0
        self.last_harmonic_ratio = 0.0
        self.last_filtered_buf     = np.zeros(self.BUF_LEN)
        self.last_hps              = np.zeros(self.BUF_LEN // 2 + 1)
        # Gap detection (data_sample_counter continuity — Punto C, post-decimation)
        self._last_counter = None
        self._nominal_step = None
        self.gap_count     = 0

    def _recalc_params(self, fs):
        self._fs      = fs
        self._update_n = max(1, int(self.UPDATE_INTERVAL_S * fs))
        self._b, self._a = signal.butter(2, self.LP_CUTOFF_HZ / (fs / 2.0), btype='low')
        self._zi      = signal.lfilter_zi(self._b, self._a) * 0.0
        self._buf     = np.zeros(self.BUF_LEN)
        self._buf_idx = 0
        self._buf_count   = 0
        self._sample_count = 0
        self.hr_bpm   = 0.0
        self.hr_valid = False
        self.last_spectrum         = np.zeros(self.BUF_LEN // 2 + 1)
        self.last_freqs            = np.zeros(self.BUF_LEN // 2 + 1)
        self.last_peak_freq        = 0.0
        self.last_harmonic_ratio = 0.0
        self.last_filtered_buf     = np.zeros(self.BUF_LEN)
        self.last_hps              = np.zeros(self.BUF_LEN // 2 + 1)

    def reset(self):
        self._fs      = 0.0
        self.hr_bpm   = 0.0
        self.hr_valid = False

    def update(self, led1_aled1, fs, sample_counter=None):
        """Process one sample. Returns (hr_bpm, hr_valid)."""
        if fs != self._fs:
            self._recalc_params(fs)

        if sample_counter is not None:
            if self._last_counter is not None:
                step = sample_counter - self._last_counter
                if self._nominal_step is None:
                    self._nominal_step = step
                elif step > self._nominal_step:
                    self.gap_count += step - self._nominal_step
            self._last_counter = sample_counter

        # LP filter (anti-aliasing before virtual decimation; magnitude-only FFT → no need to negate)
        x = float(led1_aled1)
        filtered, self._zi = signal.lfilter(self._b, self._a, [x], zi=self._zi)
        filtered = filtered[0]

        # Circular buffer
        self._buf[self._buf_idx] = filtered
        self._buf_idx = (self._buf_idx + 1) % self.BUF_LEN
        if self._buf_count < self.BUF_LEN:
            self._buf_count += 1

        # Update every UPDATE_INTERVAL_S seconds
        self._sample_count += 1
        if self._sample_count < self._update_n:
            return self.hr_bpm, self.hr_valid
        self._sample_count = 0

        if self._buf_count < self.BUF_LEN:
            self.hr_valid = False
            return self.hr_bpm, self.hr_valid

        # Reconstruct ordered segment (oldest first)
        seg_raw = np.roll(self._buf, -self._buf_idx)
        self.last_filtered_buf = seg_raw.copy()

        # Apply Hann window and compute rfft
        seg      = seg_raw * np.hanning(self.BUF_LEN)
        fft_cplx = np.fft.rfft(seg)
        spectrum = np.abs(fft_cplx)
        freqs    = np.fft.rfftfreq(self.BUF_LEN, d=1.0 / fs)

        # Restrict search to guard-band HR range (±3 BPM beyond reported valid range)
        mask = (freqs >= self.HR_SEARCH_MIN_HZ) & (freqs <= self.HR_SEARCH_MAX_HZ)
        if not np.any(mask):
            self.hr_valid = False
            return self.hr_bpm, self.hr_valid

        # Harmonic Product Spectrum (HPS): HPS[i] = S[i] · S[2i] · S[3i].
        # Reinforces the fundamental frequency (all harmonics peak together) and
        # suppresses isolated harmonic peaks (their sub-harmonics are weak).
        # Solves the problem of locking onto the 2nd harmonic when it has more
        # power than the fundamental (common in slow PPG signals).
        n_hps = len(spectrum)
        hps   = spectrum.copy()
        for k in range(2, 4):          # k = 2, 3
            n_valid        = n_hps // k
            hps[:n_valid] *= spectrum[np.arange(n_valid) * k]
            hps[n_valid:]  = 0.0
        self.last_hps = hps.copy()     # exposed for HR3LabWindow

        idx_offset = int(np.where(mask)[0][0])
        hps_hr     = hps[mask]

        # Dominant peak in HPS — argmax (same logic as firmware)
        spec_hr = spectrum[mask]       # kept for harmonic_ratio computation below
        peak_local = int(np.argmax(hps_hr))
        peak_global = idx_offset + peak_local

        # Gaussian interpolation: parabolic fit on log|X|² (accurate for Hann window).
        # Jacobsen (complex) gives δ ≈ -0.5·δ_true for Hann: adjacent bins carry
        # phase e^{±jπ}=-1, inverting the numerator sign.  Gaussian gives δ ≈ 1.07·δ_true.
        if 0 < peak_global < len(fft_cplx) - 1:
            pm = abs(fft_cplx[peak_global - 1])**2
            pc = abs(fft_cplx[peak_global    ])**2
            pp = abs(fft_cplx[peak_global + 1])**2
            lm, lc, lp = np.log(max(pm, 1e-30)), np.log(max(pc, 1e-30)), np.log(max(pp, 1e-30))
            denom = lm - 2.0*lc + lp
            delta = 0.5*(lm - lp) / denom if denom != 0.0 else 0.0
        else:
            delta = 0.0

        freq_res  = fs / self.BUF_LEN
        peak_freq = freqs[peak_global] + delta * freq_res
        hr_bpm    = peak_freq * 60.0

        # Store diagnostic state for HR3LabWindow
        spec_max = np.max(spec_hr) if np.max(spec_hr) > 0.0 else 1.0
        self.last_spectrum  = spectrum / spec_max          # normalised to HR-band max
        self.last_freqs     = freqs
        self.last_peak_freq = peak_freq

        # Harmonic power ratio: signal = power at f0, 2·f0, 3·f0 (±1 bin each);
        # denominator = total power in [HR_MIN_HZ, min(3·f0 + 2 bins, Nyquist)].
        # Physically motivated: a clean PPG concentrates energy at the fundamental
        # + harmonics; noise spreads it uniformly.
        f_top    = min(peak_freq * 3.0 + 2.0 * freq_res, fs / 2.0)
        ext_mask = (freqs >= self.HR_SEARCH_MIN_HZ) & (freqs <= f_top)
        total_power  = np.sum(spectrum[ext_mask])
        signal_power = 0.0
        for k in (1, 2, 3):
            h_bin = int(round(peak_freq * k / freq_res))
            for b in range(max(0, h_bin - 1), min(len(spectrum), h_bin + 2)):
                signal_power += spectrum[b]
        self.last_harmonic_ratio = float(signal_power / total_power) if total_power > 0.0 else 0.0

        if (self.HR_MIN_HZ * 60.0) <= hr_bpm <= (self.HR_MAX_HZ * 60.0):
            self.hr_bpm   = hr_bpm
            self.hr_valid = True
        else:
            self.hr_valid = False

        return self.hr_bpm, self.hr_valid


class SpO2TestCalc:
    """SpO2 algorithm mirror for SPO2TEST window.

    Independent reimplementation of firmware _update_spo2() from incunest_afe4490_spec.md §5.1.
    Purpose: post-implementation verification — compare against firmware output to detect bugs.

    All parameters default to firmware values from spec. The user can modify them in
    SpO2TestWindow to explore sensitivity; any deviation activates CUSTOM PARAMS mode.

    Processing chain (per sample):
      IIR DC removal → AC extraction → AC² EMA → RMS AC →
      R = (RMS_AC_red/DC_red) / (RMS_AC_ir/DC_ir) →
      SpO2 = a − b·R →
      PI = (RMS_AC_ir / DC_ir) × 100 →
      SQI = clamp((PI − 0.5) / (2.0 − 0.5), 0, 1)  [forced to 0 if SpO2 out of range]
    """

    # Firmware defaults — must match incunest_afe4490_spec.md §5.1 and incunest_afe4490.cpp constants
    FW_DC_IIR_TAU_S = 2.0   # spo2_ema_mean_tau_s (EmaChannel τ_mean)
    FW_AC_EMA_TAU_S = 6.0   # spo2_ema_var_tau_s  (EmaChannel τ_var, ISO 80601-2-61:2026 JJ.2 d ≥ 6 s)
    FW_SPO2_MIN_DC  = 1000.0
    FW_WARMUP_S     = 18.0  # spo2_warmup_s = 3 × τ_var
    FW_SPO2_A       = 114.9208
    FW_SPO2_B       =  30.5547
    FW_SPO2_MIN     = 70.0
    FW_SPO2_MAX     = 100.0
    FW_PI_SQI_LOW   = 0.5    # PI below this → SQI = 0
    FW_PI_SQI_HIGH  = 2.0    # PI at or above this → SQI = 1

    def __init__(self):
        # User-adjustable parameters (start at firmware defaults)
        self.dc_iir_tau_s = self.FW_DC_IIR_TAU_S
        self.ac_ema_tau_s = self.FW_AC_EMA_TAU_S
        self.spo2_min_dc  = self.FW_SPO2_MIN_DC
        self.warmup_s     = self.FW_WARMUP_S
        self.spo2_a       = self.FW_SPO2_A
        self.spo2_b       = self.FW_SPO2_B
        # Internal state
        self._fs           = 0.0
        self._alpha        = 0.0
        self._beta         = 0.0
        self._warmup_n     = 0
        self._dc_ir        = 0.0
        self._dc_red       = 0.0
        self._ac2_ir       = 0.0
        self._ac2_red      = 0.0
        self._sample_count = 0

    def reset(self):
        """Reset filter state and sample counter. Preserves user parameters."""
        self._fs           = 0.0
        self._dc_ir        = 0.0
        self._dc_red       = 0.0
        self._ac2_ir       = 0.0
        self._ac2_red      = 0.0
        self._sample_count = 0

    def reset_to_defaults(self):
        """Restore all parameters to firmware defaults and reset state."""
        self.dc_iir_tau_s = self.FW_DC_IIR_TAU_S
        self.ac_ema_tau_s = self.FW_AC_EMA_TAU_S
        self.spo2_min_dc  = self.FW_SPO2_MIN_DC
        self.warmup_s     = self.FW_WARMUP_S
        self.spo2_a       = self.FW_SPO2_A
        self.spo2_b       = self.FW_SPO2_B
        self.reset()

    @property
    def using_defaults(self):
        """True when all parameters equal their firmware defaults."""
        return (
            self.dc_iir_tau_s == self.FW_DC_IIR_TAU_S and
            self.ac_ema_tau_s == self.FW_AC_EMA_TAU_S and
            self.spo2_min_dc  == self.FW_SPO2_MIN_DC  and
            self.warmup_s     == self.FW_WARMUP_S     and
            self.spo2_a       == self.FW_SPO2_A       and
            self.spo2_b       == self.FW_SPO2_B
        )

    def _recalc_params(self, fs):
        self._fs       = fs
        self._alpha    = np.exp(-1.0 / (self.dc_iir_tau_s * fs))
        self._beta     = 1.0 - np.exp(-1.0 / (self.ac_ema_tau_s * fs))
        self._warmup_n = int(self.warmup_s * fs)
        self._dc_ir    = 0.0
        self._dc_red   = 0.0
        self._ac2_ir   = 0.0
        self._ac2_red  = 0.0
        self._sample_count = 0

    def update(self, ir, red, fs):
        """Process one sample. Always returns a dict with intermediates.

        Returns
        -------
        dict with keys:
          dc_ir, dc_red       — IIR-tracked DC level
          rms_ac_ir, rms_ac_red — sqrt of AC² EMA
          R                   — (RMS_AC_red/DC_red)/(RMS_AC_ir/DC_ir), nan if invalid
          pi                  — Perfusion Index [%], nan if invalid
          spo2                — SpO2 [%], nan if invalid
          sqi                 — Signal Quality Index [0–1], nan if invalid
          valid               — bool: SpO2 and DC are within valid range
          warmup              — bool: still in warmup period
        """
        if fs != self._fs:
            self._recalc_params(fs)

        # IIR DC removal
        self._dc_ir  = self._alpha * self._dc_ir  + (1.0 - self._alpha) * ir
        self._dc_red = self._alpha * self._dc_red + (1.0 - self._alpha) * red

        # AC extraction and EMA of AC²
        ac_ir  = ir  - self._dc_ir
        ac_red = red - self._dc_red
        self._ac2_ir  = self._beta * ac_ir  * ac_ir  + (1.0 - self._beta) * self._ac2_ir
        self._ac2_red = self._beta * ac_red * ac_red + (1.0 - self._beta) * self._ac2_red

        self._sample_count += 1

        rms_ac_ir  = float(np.sqrt(max(0.0, self._ac2_ir)))
        rms_ac_red = float(np.sqrt(max(0.0, self._ac2_red)))
        nan = float('nan')

        warmup_done = self._sample_count >= self._warmup_n
        dc_ok = (self._dc_ir >= self.spo2_min_dc and self._dc_red >= self.spo2_min_dc)

        if not warmup_done or not dc_ok or self._dc_ir < 1.0 or self._dc_red < 1.0 or rms_ac_ir < 1.0:
            return {
                'dc_ir': self._dc_ir, 'dc_red': self._dc_red,
                'rms_ac_ir': rms_ac_ir, 'rms_ac_red': rms_ac_red,
                'R': nan, 'pi': nan, 'spo2': nan, 'sqi': nan,
                'valid': False, 'warmup': not warmup_done,
            }

        R    = (rms_ac_red / self._dc_red) / (rms_ac_ir / self._dc_ir)
        pi   = (rms_ac_ir / self._dc_ir) * 100.0
        spo2 = self.spo2_a - self.spo2_b * R
        spo2_valid = self.FW_SPO2_MIN <= spo2 <= self.FW_SPO2_MAX
        sqi = float(np.clip((pi - self.FW_PI_SQI_LOW) / (self.FW_PI_SQI_HIGH - self.FW_PI_SQI_LOW), 0.0, 1.0))
        if not spo2_valid:
            sqi = 0.0

        return {
            'dc_ir': self._dc_ir, 'dc_red': self._dc_red,
            'rms_ac_ir': rms_ac_ir, 'rms_ac_red': rms_ac_red,
            'R': R, 'pi': pi, 'spo2': spo2, 'sqi': sqi,
            'valid': spo2_valid, 'warmup': False,
        }


class HR1TestCalc:
    """HR1 algorithm mirror for HR1TEST window.

    Independent reimplementation of firmware _update_hr1() from incunest_afe4490_spec.md §5.2.
    Purpose: post-implementation verification — compare against firmware output to detect bugs.

    Processing chain per sample:
      LED1_SUB → IIR DC removal (τ=1.6 s) → negate (PPG polarity) →
      moving average LP (cutoff ~5 Hz, len=fs/(2×5), max 64) →
      running maximum (×0.9999 decay) →
      threshold crossing (0.6 × running_max, refractory 0.2 s) →
      RR buffer (last 5 intervals) →
      HR1 = fs × 60 / mean(RR) →
      SQI = clamp(1 − CV/0.15, 0, 1)  where CV = std/mean of RR intervals

    Diagnostic buffers expose every intermediate signal for visualization.
    PPGMonitor feeds this calc at full 500 Hz (before decimation).
    """

    # Firmware defaults — must match incunest_afe4490_spec.md §5.2
    FW_DC_IIR_TAU_S      = 1.6
    FW_MA_CUTOFF_HZ      = 5.0
    FW_MA_MAX_LEN        = 64
    FW_RUNNING_MAX_DECAY = 0.9999
    FW_THRESHOLD_FACTOR  = 0.6
    FW_REFRACTORY_S      = 0.2
    FW_RR_BUF_LEN        = 5
    FW_HR_MIN_BPM        = 40.0
    FW_HR_MAX_BPM        = 300.0
    FW_PEAK_MARKER_N     = 10

    DIAG_BUF_LEN = 2500   # diagnostic rolling buffer: 5 s at 500 Hz

    def __init__(self):
        # User-adjustable parameters
        self.dc_iir_tau_s      = self.FW_DC_IIR_TAU_S
        self.ma_cutoff_hz      = self.FW_MA_CUTOFF_HZ
        self.ma_max_len        = self.FW_MA_MAX_LEN
        self.running_max_decay = self.FW_RUNNING_MAX_DECAY
        self.threshold_factor  = self.FW_THRESHOLD_FACTOR
        self.refractory_s      = self.FW_REFRACTORY_S
        # Internal filter state
        self._fs               = 0.0
        self._dc_alpha         = 0.0
        self._dc_est           = 0.0
        self._ma_len           = 1
        self._ma_buf           = np.zeros(self.FW_MA_MAX_LEN)
        self._ma_idx           = 0
        self._ma_sum           = 0.0
        self._ma_count         = 0
        self._running_max      = 0.0
        self._above_thresh     = False
        self._refractory_n     = 0
        self._refractory_ctr   = 0
        self._rr_buf           = []          # list of last FW_RR_BUF_LEN RR intervals (samples)
        self._last_peak_idx    = -1
        self._sample_idx       = 0
        self._peak_marker_ctr  = 0
        self._hr_bpm           = 0.0
        self._hr_sqi           = 0.0
        # Diagnostic rolling buffers (exposed for HR1TestWindow)
        self.diag_dc_removed  = deque(maxlen=self.DIAG_BUF_LEN)
        self.diag_ma_filtered = deque(maxlen=self.DIAG_BUF_LEN)
        self.diag_running_max = deque(maxlen=self.DIAG_BUF_LEN)
        self.diag_threshold   = deque(maxlen=self.DIAG_BUF_LEN)
        self.diag_hr1_ppg     = deque(maxlen=self.DIAG_BUF_LEN)
        self.diag_peak_mask   = deque(maxlen=self.DIAG_BUF_LEN)  # 1.0 on peak sample, 0 elsewhere
        self.hr_bpm           = 0.0
        self.hr_sqi           = 0.0
        self.rr_buf_copy      = []   # copy of _rr_buf, updated on each peak
        # Gap detection (data_sample_counter continuity — Punto C, pre-decimation)
        self._last_counter = None
        self._nominal_step = None
        self.gap_count     = 0

    def reset(self):
        """Reset all filter state. Preserves user parameters."""
        self._fs             = 0.0
        self._dc_est         = 0.0
        self._ma_buf[:]      = 0.0
        self._ma_idx         = 0
        self._ma_sum         = 0.0
        self._ma_count       = 0
        self._running_max    = 0.0
        self._above_thresh   = False
        self._refractory_ctr = 0
        self._rr_buf         = []
        self._last_peak_idx  = -1
        self._sample_idx     = 0
        self._peak_marker_ctr = 0
        self._hr_bpm         = 0.0
        self._hr_sqi         = 0.0
        self.hr_bpm          = 0.0
        self.hr_sqi          = 0.0
        self.rr_buf_copy     = []
        self.diag_dc_removed.clear()
        self.diag_ma_filtered.clear()
        self.diag_running_max.clear()
        self.diag_threshold.clear()
        self.diag_hr1_ppg.clear()
        self.diag_peak_mask.clear()

    def reset_to_defaults(self):
        self.dc_iir_tau_s      = self.FW_DC_IIR_TAU_S
        self.ma_cutoff_hz      = self.FW_MA_CUTOFF_HZ
        self.ma_max_len        = self.FW_MA_MAX_LEN
        self.running_max_decay = self.FW_RUNNING_MAX_DECAY
        self.threshold_factor  = self.FW_THRESHOLD_FACTOR
        self.refractory_s      = self.FW_REFRACTORY_S
        self.reset()

    @property
    def using_defaults(self):
        return (
            self.dc_iir_tau_s      == self.FW_DC_IIR_TAU_S      and
            self.ma_cutoff_hz      == self.FW_MA_CUTOFF_HZ       and
            self.ma_max_len        == self.FW_MA_MAX_LEN          and
            self.running_max_decay == self.FW_RUNNING_MAX_DECAY   and
            self.threshold_factor  == self.FW_THRESHOLD_FACTOR    and
            self.refractory_s      == self.FW_REFRACTORY_S
        )

    def _recalc_params(self, fs):
        self._fs           = fs
        self._dc_alpha     = float(np.exp(-1.0 / (self.dc_iir_tau_s * fs)))
        raw_len            = int(round(fs / (2.0 * self.ma_cutoff_hz)))
        self._ma_len       = max(1, min(raw_len, self.ma_max_len))
        self._ma_buf       = np.zeros(self.ma_max_len)
        self._ma_idx       = 0
        self._ma_sum       = 0.0
        self._ma_count     = 0
        self._refractory_n = int(self.refractory_s * fs)
        self._dc_est       = 0.0
        self._running_max  = 0.0
        self._above_thresh = False
        self._refractory_ctr = 0
        self._rr_buf       = []
        self._last_peak_idx = -1
        self._sample_idx   = 0
        self._peak_marker_ctr = 0
        self._hr_bpm       = 0.0
        self._hr_sqi       = 0.0

    def update(self, led1_sub, fs, sample_counter=None):
        """Process one sample at full firmware rate.

        Parameters
        ----------
        led1_sub         : float — LED1_SUB (LED1-ALED1) ADC value
        fs             : float — sample rate (Hz)
        sample_counter : int | None — data_sample_counter from serial frame (for gap detection)
        """
        if fs != self._fs:
            self._recalc_params(fs)
        if sample_counter is not None:
            if self._last_counter is not None:
                step = sample_counter - self._last_counter
                if self._nominal_step is None:
                    self._nominal_step = step
                elif step > self._nominal_step:
                    self.gap_count += step - self._nominal_step
            self._last_counter = sample_counter

        # 1. IIR DC removal
        self._dc_est = self._dc_alpha * self._dc_est + (1.0 - self._dc_alpha) * led1_sub
        dc_removed   = led1_sub - self._dc_est

        # 2. Negate for conventional PPG polarity (peaks up)
        dc_removed = -dc_removed

        # 3. Moving average low-pass
        old_val = self._ma_buf[self._ma_idx]
        self._ma_buf[self._ma_idx] = dc_removed
        self._ma_idx = (self._ma_idx + 1) % self._ma_len
        self._ma_sum += dc_removed - old_val
        if self._ma_count < self._ma_len:
            self._ma_count += 1
        ma_out = self._ma_sum / self._ma_count

        # 4. Running maximum with exponential decay
        self._running_max *= self.running_max_decay
        if ma_out > self._running_max:
            self._running_max = ma_out

        threshold = self.threshold_factor * self._running_max

        # 5. Peak detection: rising edge through threshold, with refractory period
        peak_detected = False
        if self._refractory_ctr > 0:
            self._refractory_ctr -= 1
        else:
            if ma_out >= threshold > 0 and not self._above_thresh:
                # Rising edge detected
                peak_detected = True
                if self._last_peak_idx >= 0:
                    rr = self._sample_idx - self._last_peak_idx
                    self._rr_buf.append(rr)
                    if len(self._rr_buf) > self.FW_RR_BUF_LEN:
                        self._rr_buf.pop(0)
                    # Compute HR and SQI
                    if len(self._rr_buf) == self.FW_RR_BUF_LEN:
                        rr_arr = np.array(self._rr_buf, dtype=float)
                        mean_rr = np.mean(rr_arr)
                        std_rr  = np.std(rr_arr)
                        hr_bpm  = (fs * 60.0 / mean_rr) if mean_rr > 0 else 0.0
                        cv      = (std_rr / mean_rr) if mean_rr > 0 else 1.0
                        sqi     = float(np.clip(1.0 - cv / 0.15, 0.0, 1.0))
                        if hr_bpm < self.FW_HR_MIN_BPM or hr_bpm > self.FW_HR_MAX_BPM:
                            sqi = 0.0
                        self._hr_bpm = hr_bpm
                        self._hr_sqi = sqi
                        self.hr_bpm  = hr_bpm
                        self.hr_sqi  = sqi
                        self.rr_buf_copy = list(self._rr_buf)
                self._last_peak_idx  = self._sample_idx
                self._refractory_ctr = self._refractory_n
                self._peak_marker_ctr = self.FW_PEAK_MARKER_N

        self._above_thresh = (ma_out >= threshold > 0)

        # 6. Peak marker: hr1_ppg = 0 for FW_PEAK_MARKER_N samples after peak
        if self._peak_marker_ctr > 0:
            hr1_ppg = 0.0
            self._peak_marker_ctr -= 1
        else:
            hr1_ppg = ma_out

        # Update diagnostic buffers
        self.diag_dc_removed.append(dc_removed)
        self.diag_ma_filtered.append(ma_out)
        self.diag_running_max.append(self._running_max)
        self.diag_threshold.append(threshold)
        self.diag_hr1_ppg.append(hr1_ppg)
        self.diag_peak_mask.append(1.0 if peak_detected else 0.0)

        self._sample_idx += 1


class HR2TestCalc:
    """HR2 algorithm mirror for HR2TEST window.

    Independent reimplementation of firmware _update_hr2() from incunest_afe4490_spec.md §5.3.
    Purpose: post-implementation verification.

    Processing chain per sample (at 50 Hz after firmware decimation):
      LED1_SUB → biquad BPF 0.5–5 Hz → circular buffer 400 samples →
      [every 25 samples] normalised autocorrelation over lags [0.185 s .. 137 samples] →
      first local max ≥ hr2_min_corr → parabolic interpolation → HR2 = 60/peak_lag_s

    Diagnostic state exposed for HR2TestWindow:
      last_acorr      — most recent normalised autocorrelation (np.array)
      last_lags_s     — lag axis (s) for last_acorr
      last_peak_lag_s — detected peak lag (s)
      last_filtered   — last 400 filtered samples (circular buffer, ordered oldest→newest)
    """

    FW_FS            = 50.0
    FW_BPF_LOW_HZ    = 0.5
    FW_BPF_HIGH_HZ   = 5.0
    FW_BUF_LEN       = 400
    FW_MAX_LAG       = 137
    FW_UPDATE_N      = 25
    FW_MIN_LAG_S     = 0.185
    FW_MIN_CORR      = 0.5
    FW_HR_MIN_BPM    = 40.0
    FW_HR_MAX_BPM    = 300.0
    FW_HR_SEARCH_MIN = 37.0
    FW_HR_SEARCH_MAX = 303.0

    def __init__(self):
        self.bpf_low_hz  = self.FW_BPF_LOW_HZ
        self.bpf_high_hz = self.FW_BPF_HIGH_HZ
        self.buf_len     = self.FW_BUF_LEN
        self.max_lag     = self.FW_MAX_LAG
        self.update_n    = self.FW_UPDATE_N
        self.min_lag_s   = self.FW_MIN_LAG_S
        self.min_corr    = self.FW_MIN_CORR
        self._fs         = 0.0
        self._b          = None
        self._a          = None
        self._zi         = None
        self._buf        = np.zeros(self.FW_BUF_LEN)
        self._buf_idx    = 0
        self._buf_count  = 0
        self._update_ctr = 0
        self.hr_bpm      = 0.0
        self.hr_sqi      = 0.0
        # Diagnostic state (updated every update_n samples)
        self.last_acorr      = np.zeros(self.FW_MAX_LAG + 1)
        self.last_lags_s     = np.arange(self.FW_MAX_LAG + 1) / self.FW_FS
        self.last_peak_lag_s = 0.0
        self.last_filtered   = np.zeros(self.FW_BUF_LEN)

    def reset(self):
        self._fs      = 0.0
        self._zi      = None
        self._buf[:]  = 0.0
        self._buf_idx = 0
        self._buf_count = 0
        self._update_ctr = 0
        self.hr_bpm   = 0.0
        self.hr_sqi   = 0.0
        self.last_acorr[:]  = 0.0
        self.last_peak_lag_s = 0.0

    def reset_to_defaults(self):
        self.bpf_low_hz  = self.FW_BPF_LOW_HZ
        self.bpf_high_hz = self.FW_BPF_HIGH_HZ
        self.buf_len     = self.FW_BUF_LEN
        self.max_lag     = self.FW_MAX_LAG
        self.update_n    = self.FW_UPDATE_N
        self.min_lag_s   = self.FW_MIN_LAG_S
        self.min_corr    = self.FW_MIN_CORR
        self.reset()

    @property
    def using_defaults(self):
        return (
            self.bpf_low_hz  == self.FW_BPF_LOW_HZ   and
            self.bpf_high_hz == self.FW_BPF_HIGH_HZ  and
            self.buf_len     == self.FW_BUF_LEN       and
            self.max_lag     == self.FW_MAX_LAG        and
            self.update_n    == self.FW_UPDATE_N       and
            self.min_lag_s   == self.FW_MIN_LAG_S      and
            self.min_corr    == self.FW_MIN_CORR
        )

    def _recalc_filter(self, fs):
        self._fs = fs
        nyq = fs / 2.0
        lo  = max(0.01, min(self.bpf_low_hz  / nyq, 0.99))
        hi  = max(0.01, min(self.bpf_high_hz / nyq, 0.99))
        if lo >= hi:
            hi = min(lo + 0.01, 0.99)
        self._b, self._a = signal.butter(2, [lo, hi], btype='band')
        self._zi = signal.lfilter_zi(self._b, self._a) * 0.0
        self._buf     = np.zeros(max(1, self.buf_len))
        self._buf_idx = 0
        self._buf_count = 0
        self._update_ctr = 0
        self.hr_bpm  = 0.0
        self.hr_sqi  = 0.0

    def update(self, led1_sub, fs):
        if fs != self._fs or self._b is None:
            self._recalc_filter(fs)

        # BPF
        x = float(led1_sub)
        filtered, self._zi = signal.lfilter(self._b, self._a, [x], zi=self._zi)
        filtered = float(filtered[0])

        # Circular buffer
        buf_len = max(1, self.buf_len)
        if self._buf.shape[0] != buf_len:
            self._buf = np.zeros(buf_len)
            self._buf_idx = 0
            self._buf_count = 0
        self._buf[self._buf_idx] = filtered
        self._buf_idx = (self._buf_idx + 1) % buf_len
        if self._buf_count < buf_len:
            self._buf_count += 1

        self._update_ctr += 1
        if self._update_ctr < self.update_n:
            return

        self._update_ctr = 0

        if self._buf_count < buf_len:
            return

        # Ordered segment (oldest first)
        seg = np.roll(self._buf, -self._buf_idx)
        self.last_filtered = seg.copy()

        # Unbiased normalised autocorrelation using scipy.signal.correlate (full, FFT).
        # Each lag τ is corrected by n/(n-τ) to eliminate the finite-window bias: the
        # biased estimator (/ acorr[0]) underestimates because the numerator sums only
        # (n-τ) terms while acorr[0] = Σ x² sums n terms. Unbiased correction restores
        # SQI ≈ 1.0 for a clean periodic signal regardless of lag (mirrors firmware fix).
        n = len(seg)
        max_lag = min(self.max_lag, n - 1)
        full = signal.correlate(seg, seg, mode='full', method='fft')
        acorr = full[n - 1: n - 1 + max_lag + 1]
        acorr0_val = float(acorr[0])
        if acorr0_val != 0:
            n_terms = np.maximum(n - np.arange(len(acorr)), 1)
            acorr = acorr * n / (acorr0_val * n_terms)
        lags_s = np.arange(len(acorr)) / fs

        self.last_acorr  = acorr
        self.last_lags_s = lags_s

        # Search range
        min_idx = int(np.searchsorted(lags_s, self.min_lag_s))
        max_search_lag_s = 60.0 / self.FW_HR_SEARCH_MIN
        max_idx = int(np.searchsorted(lags_s, max_search_lag_s))
        max_idx = min(max_idx, len(acorr) - 1)

        if min_idx >= max_idx:
            self.hr_sqi = 0.0
            return

        search = acorr[min_idx:max_idx + 1]
        peaks, _ = signal.find_peaks(search, prominence=0.05)

        peak_idx = None
        for p in peaks:
            if search[p] >= self.min_corr:
                peak_idx = min_idx + p
                break
        if peak_idx is None:
            if len(peaks) > 0:
                peak_idx = min_idx + peaks[np.argmax(search[peaks])]
            else:
                peak_idx = min_idx + int(np.argmax(search))

        # Parabolic interpolation
        if 0 < peak_idx < len(acorr) - 1:
            yp, yc, yn = acorr[peak_idx - 1], acorr[peak_idx], acorr[peak_idx + 1]
            denom = yp - 2.0 * yc + yn
            delta = 0.5 * (yp - yn) / denom if denom < 0 else 0.0
        else:
            delta = 0.0

        peak_lag_s = (peak_idx + delta) / fs
        peak_val   = float(acorr[peak_idx]) if peak_idx < len(acorr) else 0.0

        self.last_peak_lag_s = peak_lag_s

        if peak_val < self.min_corr or peak_lag_s <= 0:
            self.hr_sqi = 0.0
            return

        hr_bpm = 60.0 / peak_lag_s
        if self.FW_HR_SEARCH_MIN <= hr_bpm <= self.FW_HR_SEARCH_MAX:
            self.hr_bpm = hr_bpm if self.FW_HR_MIN_BPM <= hr_bpm <= self.FW_HR_MAX_BPM else hr_bpm
            self.hr_sqi = peak_val if self.FW_HR_MIN_BPM <= hr_bpm <= self.FW_HR_MAX_BPM else 0.0
        else:
            self.hr_sqi = 0.0


ACTION_BUTTON_STYLE = """
    QPushButton { 
        background-color: #555555; color: white; border-radius: 5px; 
        padding: 5px; font-weight: bold; border: 1px solid #777777;
        font-size: 20px;
    }
    QPushButton:checked { 
        background-color: #FF6666; color: white; border: 1px solid #FF8888;
    }
    QPushButton:hover { 
        background-color: #666666; 
    }
    QPushButton:checked:hover { 
        background-color: #FF8888; 
    }
"""

_MOUSE_HINT = "pyqtgraph: use mouse buttons and wheel on plots and axes to zoom/pan (right-click for more options)"

# ── Monkey-patch pyqtgraph ViewBoxMenu ────────────────────────────────────────
# pyqtgraph's axisCtrlTemplate sets Form.setMaximumSize(QSize(200, ...)) which
# hard-limits axis submenu widgets to 200 px wide. No CSS can override a
# programmatic setMaximumWidth. We patch ViewBoxMenu.__init__ to remove that
# limit after construction so all plots created anywhere in the app benefit.
def _patch_viewbox_menu():
    from pyqtgraph.graphicsItems.ViewBox.ViewBoxMenu import ViewBoxMenu as _VBMenu
    _orig = _VBMenu.__init__
    def _patched(self, view):
        _orig(self, view)
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            submenu.setMinimumWidth(380)
            for sub_action in submenu.actions():
                if isinstance(sub_action, QtWidgets.QWidgetAction):
                    w = sub_action.defaultWidget()
                    if w is not None:
                        w.setMaximumWidth(16777215)   # remove 200 px hard-cap
                        w.setMinimumWidth(360)
    _VBMenu.__init__ = _patched
_patch_viewbox_menu()


def _make_tooltip(name: str, text: str, src: str = "") -> str:
    """Build a rich-text HTML tooltip with a vivid purple background.

    ``name`` is shown in bold gold as the first line; ``text`` follows in light grey.
    ``src`` (optional) is the source code element name this control depends on — shown
    in a dim monospace line at the bottom so the user can locate it in the codebase.
    Used by every interactive control in the script.
    """
    def _esc(s: str) -> str:
        return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>')
                  .replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>'))

    src_html = (
        f"<br/><span style='font-size:20px; color:#999999;'>&#x1F4CE;&nbsp;"
        f"<code style='color:#88CCFF; font-family:monospace;'>{_esc(src)}</code></span>"
    ) if src else ""

    return (
        "<table width='540' style='background-color:#5500AA; border-radius:6px;'>"
        "<tr><td style='padding:8px;'>"
        "<span style='font-size:30px; font-weight:bold; color:#FFE066;'>"
        f"{_esc(name)}"
        "</span><br/>"
        "<span style='font-size:24px; white-space:normal; color:#F0F0F0;'>"
        f"{_esc(text)}"
        "</span>"
        f"{src_html}"
        "</td></tr></table>"
    )


class SpO2LabWindow(QtWidgets.QMainWindow):
    """SpO2 calibration window.

    Left panel: 4 live plots (SpO2, R ratio, DC components, RMS-AC components).
    Right panel: sensor info, reference SpO2 input, calibration point table,
                 linear regression (spo2 = a - b·R) and CSV export.

    Sensor model documented: UpnMed U401-D(01AS-F).
    """

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("SPO2LAB — Calibration")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        # ── State ─────────────────────────────────────────────────────────────
        self._local_calc      = SpO2LocalCalc()
        self._last_sample_cnt = -1
        self._nominal_step    = None   # gap detection
        self.gap_count        = 0      # gap detection: lost samples since connect
        self._t0_us           = None
        self._cal_points      = []   # list of (spo2_ref, R_fw_mean, R_loc_mean)

        _B = SPO2_CAL_BUFSIZE
        self._buf_t        = deque(maxlen=_B)
        self._buf_spo2_fw  = deque(maxlen=_B)
        self._buf_R_fw     = deque(maxlen=_B)
        self._buf_spo2_loc = deque(maxlen=_B)
        self._buf_R_loc    = deque(maxlen=_B)
        self._buf_dc_ir    = deque(maxlen=_B)
        self._buf_dc_red   = deque(maxlen=_B)
        self._buf_rms_ir   = deque(maxlen=_B)
        self._buf_rms_red  = deque(maxlen=_B)

        # ── Root layout ───────────────────────────────────────────────────────
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.setHandleWidth(6)
        root_layout.addWidget(self._splitter)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        self._splitter.addWidget(glw)

        def _make_plot(row, title, ylabel):
            p = glw.addPlot(row=row, col=0,
                            title=f"<b style='color:#CCCCCC'>{title}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel('left', ylabel)
            p.setLabel('bottom', 't (s)')
            p.enableAutoRange()
            return p

        self.p_spo2 = _make_plot(0, "SpO2 (%)",             "%")
        self.p_R    = _make_plot(1, "R ratio",               "R")
        self.p_dc   = _make_plot(2, "DC  (LED1, LED2)",         "ADC counts")
        self.p_ac   = _make_plot(3, "RMS AC  (LED1, LED2)",     "ADC counts")

        self.curve_spo2_fw  = self.p_spo2.plot(pen=pg.mkPen('#FFDD44', width=2), name="SpO2 fw")
        self.curve_spo2_loc = self.p_spo2.plot(pen=pg.mkPen('#FF8800', width=2), name="SpO2 local")
        self._ref_line = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen('#FFFFFF', width=1,
                                                      style=QtCore.Qt.DashLine))
        self.p_spo2.addItem(self._ref_line)
        self.p_spo2.addLegend()

        self.curve_R_fw  = self.p_R.plot(pen=pg.mkPen('#FFDD44', width=2), name="R fw")
        self.curve_R_loc = self.p_R.plot(pen=pg.mkPen('#FF8800', width=2), name="R local")
        self.p_R.addLegend()

        self.curve_dc_led1  = self.p_dc.plot(pen=pg.mkPen('#4488FF', width=1.5), name="DC LED1 (IR)")
        self.curve_dc_led2 = self.p_dc.plot(pen=pg.mkPen('#FF4444', width=1.5), name="DC LED2 (RED)")
        self.p_dc.addLegend()

        self.curve_rms_led1  = self.p_ac.plot(pen=pg.mkPen('#44AAFF', width=1.5), name="RMS AC LED1 (IR)")
        self.curve_rms_led2 = self.p_ac.plot(pen=pg.mkPen('#FF6666', width=1.5), name="RMS AC LED2 (RED)")
        self.p_ac.addLegend()

        # ── Right: control panel ──────────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #1A1A1A;")
        self._splitter.addWidget(right)

        panel = QtWidgets.QVBoxLayout(right)
        panel.setContentsMargins(10, 10, 10, 10)
        panel.setSpacing(8)

        # Sensor info
        grp_sensor = QtWidgets.QGroupBox("Sensor info")
        grp_sensor.setStyleSheet("QGroupBox { color: #AAAAAA; font-weight: bold; }")
        form_s = QtWidgets.QFormLayout(grp_sensor)
        _edit_style = "background-color: #2A2A2A; color: #E0E0E0; border: 1px solid #444; padding: 2px;"
        self._edit_model  = QtWidgets.QLineEdit("UpnMed U401-D(01AS-F)")
        self._edit_lot    = QtWidgets.QLineEdit()
        self._edit_partno = QtWidgets.QLineEdit()
        for w in [self._edit_model, self._edit_lot, self._edit_partno]:
            w.setStyleSheet(_edit_style)
        form_s.addRow("Model:",    self._edit_model)
        form_s.addRow("LOT:",      self._edit_lot)
        form_s.addRow("Part No.:", self._edit_partno)
        panel.addWidget(grp_sensor)

        # Simulator info
        grp_sim = QtWidgets.QGroupBox("Simulator info")
        grp_sim.setStyleSheet("QGroupBox { color: #AAAAAA; font-weight: bold; }")
        form_sim = QtWidgets.QFormLayout(grp_sim)
        self._edit_sim_device  = QtWidgets.QLineEdit("MS100")
        self._edit_sim_setting = QtWidgets.QLineEdit("R-Curve Nellcor, 100 bpm")
        for w in [self._edit_sim_device, self._edit_sim_setting]:
            w.setStyleSheet(_edit_style)
        form_sim.addRow("Device:",  self._edit_sim_device)
        form_sim.addRow("Setting:", self._edit_sim_setting)
        panel.addWidget(grp_sim)

        # Reference input
        grp_ref = QtWidgets.QGroupBox("Calibration point")
        grp_ref.setStyleSheet("QGroupBox { color: #AAAAAA; font-weight: bold; }")
        form_r = QtWidgets.QFormLayout(grp_ref)
        self._spin_spo2_ref = QtWidgets.QDoubleSpinBox()
        self._spin_spo2_ref.setRange(50.0, 100.0)
        self._spin_spo2_ref.setSingleStep(0.5)
        self._spin_spo2_ref.setDecimals(1)
        self._spin_spo2_ref.setValue(98.0)
        self._spin_spo2_ref.setStyleSheet("background-color: #2A2A2A; color: #FFDD44; padding: 2px;")
        self._spin_spo2_ref.valueChanged.connect(self._on_ref_changed)
        self._spin_spo2_ref.setToolTip(_make_tooltip(
            "SpO2 ref (%)",
            "Reference SpO2 value provided by the calibrator/simulator (ground truth). "
            "Used as the target when adding a calibration point.",
            src="SpO2LabWindow._spin_spo2_ref"))
        self._spin_avg_win = QtWidgets.QSpinBox()
        self._spin_avg_win.setRange(1, 30)
        self._spin_avg_win.setValue(5)
        self._spin_avg_win.setSuffix(" s")
        self._spin_avg_win.setStyleSheet("background-color: #2A2A2A; color: #E0E0E0; padding: 2px;")
        self._spin_avg_win.setToolTip(_make_tooltip(
            "Avg window",
            "Duration (seconds) of the rolling average used to compute R_fw and R_local "
            "when capturing a calibration point. Longer = more stable, slower to react.",
            src="SpO2LabWindow._spin_avg_win"))
        form_r.addRow("SpO2 ref (%):", self._spin_spo2_ref)
        form_r.addRow("Avg window:",   self._spin_avg_win)
        panel.addWidget(grp_ref)

        btn_add = QtWidgets.QPushButton("ADD POINT")
        btn_add.setStyleSheet("background-color: #226622; color: #FFFFFF; font-weight: bold; padding: 8px;")
        btn_add.clicked.connect(self._add_point)
        btn_add.setToolTip(_make_tooltip(
            "ADD POINT",
            "Capture the current averaged R-ratio (firmware and local) at the reference SpO2 "
            "and add it as a calibration point to the table below."))
        panel.addWidget(btn_add)

        # Calibration table
        grp_tbl = QtWidgets.QGroupBox("Calibration points")
        grp_tbl.setStyleSheet("QGroupBox { color: #AAAAAA; font-weight: bold; }")
        vbox_tbl = QtWidgets.QVBoxLayout(grp_tbl)
        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "SpO2 ref", "R_fw", "R_local"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setStyleSheet(
            "background-color: #1E1E1E; color: #E0E0E0; gridline-color: #333;")
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setMaximumHeight(360)
        vbox_tbl.addWidget(self._table)

        hbox_btns = QtWidgets.QHBoxLayout()
        btn_reg    = QtWidgets.QPushButton("RUN REGRESSION")
        btn_clear  = QtWidgets.QPushButton("CLEAR")
        btn_export = QtWidgets.QPushButton("EXPORT CSV")
        for b, c in [(btn_reg, "#222266"), (btn_clear, "#662222"), (btn_export, "#224466")]:
            b.setStyleSheet(f"background-color: {c}; color: #FFFFFF; font-weight: bold; padding: 5px;")
        btn_reg.clicked.connect(self._run_regression)
        btn_clear.clicked.connect(self._clear_points)
        btn_export.clicked.connect(self._export_csv)
        btn_reg.setToolTip(_make_tooltip(
            "RUN REGRESSION",
            "Compute a linear regression SpO2 = a − b·R from all captured calibration points. "
            "Updates the coefficients a, b and shows R² fit quality."))
        btn_clear.setToolTip(_make_tooltip(
            "CLEAR",
            "Delete all calibration points from the table. Cannot be undone."))
        btn_export.setToolTip(_make_tooltip(
            "EXPORT CSV",
            "Save all calibration points (SpO2 ref, R_fw, R_local) to a CSV file."))
        hbox_btns.addWidget(btn_reg)
        hbox_btns.addWidget(btn_clear)
        hbox_btns.addWidget(btn_export)
        vbox_tbl.addLayout(hbox_btns)
        panel.addWidget(grp_tbl)

        # Regression result
        grp_res = QtWidgets.QGroupBox("Regression result")
        grp_res.setStyleSheet("QGroupBox { color: #AAAAAA; font-weight: bold; }")
        vbox_res = QtWidgets.QVBoxLayout(grp_res)
        self._lbl_formula = QtWidgets.QLabel("spo2 = a \u2212 b \u00b7 R")
        self._lbl_formula.setStyleSheet("color: #888888; font-style: italic;")
        self._lbl_a      = QtWidgets.QLabel("a  =  ---")
        self._lbl_b      = QtWidgets.QLabel("b  =  ---")
        self._lbl_r2     = QtWidgets.QLabel("R\u00b2  =  ---")
        self._lbl_status = QtWidgets.QLabel("")
        for lbl in [self._lbl_a, self._lbl_b, self._lbl_r2]:
            lbl.setStyleSheet("color: #44FF88; font-size: 14px; font-weight: bold;")
        self._lbl_status.setStyleSheet("color: #FFAA44; font-size: 11px;")
        self._lbl_status.setWordWrap(True)
        vbox_res.addWidget(self._lbl_formula)
        vbox_res.addWidget(self._lbl_a)
        vbox_res.addWidget(self._lbl_b)
        vbox_res.addWidget(self._lbl_r2)
        vbox_res.addWidget(self._lbl_status)
        panel.addWidget(grp_res)

        panel.addStretch()

        # ── Restore settings ──────────────────────────────────────────────────
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("SpO2LabWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1500, 1200)
        splitter_state = s.value("SpO2LabWindow/splitter")
        if splitter_state:
            self._splitter.restoreState(splitter_state)
        else:
            self._splitter.setSizes([1100, 390])
        self._spin_spo2_ref.setValue(s.value("SpO2LabWindow/spin_spo2_ref", 98.0, type=float))

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_ref_changed(self, val):
        self._ref_line.setValue(val)

    def _add_point(self):
        if not self._buf_t:
            self._lbl_status.setText("No data yet.")
            return
        avg_win_s = float(self._spin_avg_win.value())
        t_now     = self._buf_t[-1]
        t_min     = t_now - avg_win_s

        R_fw_vals  = [r for t, r in zip(self._buf_t, self._buf_R_fw)
                      if t >= t_min and not np.isnan(r)]
        R_loc_vals = [r for t, r in zip(self._buf_t, self._buf_R_loc)
                      if t >= t_min and not np.isnan(r)]

        if not R_fw_vals:
            self._lbl_status.setText("Not enough valid R_fw samples in window.")
            return

        R_fw_mean  = float(np.mean(R_fw_vals))
        R_loc_mean = float(np.mean(R_loc_vals)) if R_loc_vals else float('nan')
        spo2_ref   = self._spin_spo2_ref.value()
        idx        = len(self._cal_points) + 1

        self._cal_points.append((spo2_ref, R_fw_mean, R_loc_mean))

        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, val in enumerate([
                str(idx),
                f"{spo2_ref:.1f}",
                f"{R_fw_mean:.5f}",
                f"{R_loc_mean:.5f}" if not np.isnan(R_loc_mean) else "---"]):
            item = QtWidgets.QTableWidgetItem(val)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self._table.setItem(row, col, item)

        n_fw = len(R_fw_vals)
        self._lbl_status.setText(
            f"Point {idx} added: SpO2={spo2_ref:.1f}%  R_fw={R_fw_mean:.5f}  (n={n_fw})")

    def _run_regression(self):
        if len(self._cal_points) < 2:
            self._lbl_status.setText("Need at least 2 calibration points.")
            return
        spo2_refs = np.array([p[0] for p in self._cal_points])
        R_fw_vals = np.array([p[1] for p in self._cal_points])

        # spo2 = a - b*R  →  polyfit(R, spo2, 1) gives [slope, intercept]
        coeffs = np.polyfit(R_fw_vals, spo2_refs, 1)
        b = -float(coeffs[0])   # slope is negative → b is positive
        a =  float(coeffs[1])

        spo2_pred = a - b * R_fw_vals
        ss_res = np.sum((spo2_refs - spo2_pred) ** 2)
        ss_tot = np.sum((spo2_refs - np.mean(spo2_refs)) ** 2)
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float('nan')

        self._lbl_a.setText(f"a  =  {a:.4f}")
        self._lbl_b.setText(f"b  =  {b:.4f}")
        self._lbl_r2.setText(f"R\u00b2  =  {r2:.4f}")
        self._lbl_status.setText(
            f"Regression done ({len(self._cal_points)} pts). "
            f"Use setSpO2Coefficients({a:.4f}, {b:.4f}) in firmware.")

    def _clear_points(self):
        self._cal_points.clear()
        self._table.setRowCount(0)
        self._lbl_a.setText("a  =  ---")
        self._lbl_b.setText("b  =  ---")
        self._lbl_r2.setText("R\u00b2  =  ---")
        self._lbl_status.setText("")

    def _export_csv(self):
        if not self._cal_points:
            self._lbl_status.setText("No points to export.")
            return
        now_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(CAPTURES_DIR, f"spo2_cal_{now_str}.csv")
        try:
            with open(filename, "w") as f:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"# SpO2 Calibration — {ts}\n")
                f.write(f"# Model,{self._edit_model.text()}\n")
                f.write(f"# LOT,{self._edit_lot.text()}\n")
                f.write(f"# PartNo,{self._edit_partno.text()}\n")
                f.write(f"# SimDevice,{self._edit_sim_device.text()}\n")
                f.write(f"# SimSetting,{self._edit_sim_setting.text()}\n")
                f.write(f"# SpO2LocalCalc: DC_IIR_TAU_S={SpO2LocalCalc._DC_IIR_TAU_S}, "
                        f"AC_EMA_TAU_S={SpO2LocalCalc._AC_EMA_TAU_S}\n")
                f.write(f"# Firmware defaults: a={SpO2LocalCalc.SPO2_A}, b={SpO2LocalCalc.SPO2_B}\n")
                f.write("#\n")
                f.write("index,spo2_ref,R_fw_mean,R_local_mean\n")
                for i, (s, rfw, rloc) in enumerate(self._cal_points, 1):
                    rloc_str = f"{rloc:.6f}" if not np.isnan(rloc) else ""
                    f.write(f"{i},{s:.1f},{rfw:.6f},{rloc_str}\n")
                if "---" not in self._lbl_a.text():
                    f.write(f"# Regression: {self._lbl_a.text().strip()}, "
                            f"{self._lbl_b.text().strip()}, {self._lbl_r2.text().strip()}\n")
            self._lbl_status.setText(f"Exported: {filename}")
        except Exception as e:
            self._lbl_status.setText(f"Export error: {e}")

    # ── Update (called from main monitor loop) ────────────────────────────────

    def update_algorithms(self, data_led1_sub, data_led2_sub, data_spo2, data_spo2_r,
                          data_timestamp_us, data_sample_counter):
        """Run per-sample algorithm (called from PPGMonitor._process_frames_tick)."""
        n = len(data_sample_counter)
        if n == 0:
            return

        # Find new samples not yet processed (scan backwards from end)
        new_indices = []
        for i in range(n - 1, -1, -1):
            if data_sample_counter[i] <= self._last_sample_cnt:
                break
            new_indices.append(i)
        if not new_indices:
            return
        new_indices.reverse()

        # Gap detection: check for missing samples in new batch
        _counters = [int(data_sample_counter[i]) for i in new_indices]
        if self._nominal_step is None and len(_counters) >= 2:
            self._nominal_step = _counters[1] - _counters[0]
        if self._last_sample_cnt > 0 and self._nominal_step is not None:
            _gap = _counters[0] - self._last_sample_cnt - self._nominal_step
            if _gap > 0:
                self.gap_count += _gap
        if self._nominal_step is not None:
            for _j in range(len(_counters) - 1):
                _step = _counters[_j + 1] - _counters[_j]
                if _step > self._nominal_step:
                    self.gap_count += _step - self._nominal_step

        nan = float('nan')
        for i in new_indices:
            ts     = float(data_timestamp_us[i])
            ir     = float(data_led1_sub[i])
            red    = float(data_led2_sub[i])
            spo2_f = float(data_spo2[i])
            R_f    = float(data_spo2_r[i])

            if self._t0_us is None:
                self._t0_us = ts
            t_s = (ts - self._t0_us) / 1e6

            result = self._local_calc.update(ir, red, SPO2_RECEIVED_FS)

            self._buf_t.append(t_s)
            self._buf_spo2_fw.append(spo2_f if spo2_f >= 0 else nan)
            self._buf_R_fw.append(R_f if R_f >= 0 else nan)

            if result is not None:
                self._buf_spo2_loc.append(result['spo2'] if result['spo2_valid'] else nan)
                self._buf_R_loc.append(result['R'])
                self._buf_dc_ir.append(result['dc_ir'])
                self._buf_dc_red.append(result['dc_red'])
                self._buf_rms_ir.append(result['rms_ac_ir'])
                self._buf_rms_red.append(result['rms_ac_red'])
            else:
                for buf in [self._buf_spo2_loc, self._buf_R_loc, self._buf_dc_ir,
                             self._buf_dc_red, self._buf_rms_ir, self._buf_rms_red]:
                    buf.append(nan)

        self._last_sample_cnt = data_sample_counter[-1]

    def update_plots(self):
        """Render pre-computed buffers (called from PPGMonitor._refresh_plots_tick)."""
        if not self._buf_t:
            return

        t_arr = np.array(self._buf_t)

        spo2_fw_arr  = np.array(self._buf_spo2_fw)
        spo2_loc_arr = np.array(self._buf_spo2_loc)
        R_fw_arr     = np.array(self._buf_R_fw)
        R_loc_arr    = np.array(self._buf_R_loc)
        dc_ir_arr    = np.array(self._buf_dc_ir)
        dc_red_arr   = np.array(self._buf_dc_red)
        rms_ir_arr   = np.array(self._buf_rms_ir)
        rms_red_arr  = np.array(self._buf_rms_red)

        self.curve_spo2_fw.setData(t_arr,  spo2_fw_arr)
        self.curve_spo2_loc.setData(t_arr, spo2_loc_arr)
        self.curve_R_fw.setData(t_arr,     R_fw_arr)
        self.curve_R_loc.setData(t_arr,    R_loc_arr)
        self.curve_dc_led1.setData(t_arr,    dc_ir_arr)
        self.curve_dc_led2.setData(t_arr,   dc_red_arr)
        self.curve_rms_led1.setData(t_arr,   rms_ir_arr)
        self.curve_rms_led2.setData(t_arr,  rms_red_arr)

        def _last(arr):
            valid = arr[~np.isnan(arr)]
            return valid[-1] if len(valid) else float('nan')

        v_spo2_fw  = _last(spo2_fw_arr)
        v_spo2_loc = _last(spo2_loc_arr)
        v_R_fw     = _last(R_fw_arr)
        v_R_loc    = _last(R_loc_arr)
        v_dc_ir    = _last(dc_ir_arr)
        v_dc_red   = _last(dc_red_arr)
        v_rms_ir   = _last(rms_ir_arr)
        v_rms_red  = _last(rms_red_arr)

        def _fmt(v, decimals=2):
            return f"{v:.{decimals}f}" if not np.isnan(v) else "---"

        self.p_spo2.setTitle(
            f"<b style='color:#FFDD44'>SpO2 fw: {_fmt(v_spo2_fw, 1)} %</b>"
            f" &nbsp; <b style='color:#FF8800'>local: {_fmt(v_spo2_loc, 1)} %</b>")
        self.p_R.setTitle(
            f"<b style='color:#FFDD44'>R fw: {_fmt(v_R_fw, 5)}</b>"
            f" &nbsp; <b style='color:#FF8800'>R local: {_fmt(v_R_loc, 5)}</b>")
        self.p_dc.setTitle(
            f"<b style='color:#4488FF'>DC LED1 (IR): {_fmt(v_dc_ir, 0)}</b>"
            f" &nbsp; <b style='color:#FF4444'>DC LED2 (RED): {_fmt(v_dc_red, 0)}</b>")
        self.p_ac.setTitle(
            f"<b style='color:#44AAFF'>RMS AC LED1 (IR): {_fmt(v_rms_ir, 1)}</b>"
            f" &nbsp; <b style='color:#FF6666'>RMS AC LED2 (RED): {_fmt(v_rms_red, 1)}</b>")

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("SpO2LabWindow/geometry",      self.saveGeometry())
        s.setValue("SpO2LabWindow/splitter",      self._splitter.saveState())
        s.setValue("SpO2LabWindow/spin_spo2_ref", self._spin_spo2_ref.value())
        if self.main_monitor is not None:
            self.main_monitor.btn_spo2lab.setChecked(False)
            self.main_monitor.spo2lab_window = None
        super().closeEvent(event)


class SpO2TestWindow(QtWidgets.QMainWindow):
    """SPO2TEST — post-implementation verification window for the SpO2 algorithm.

    Runs an independent Python mirror of the firmware SpO2 algorithm (SpO2TestCalc,
    derived from incunest_afe4490_spec.md §5.1) and compares its output against the firmware
    values received over serial.

    Two data modes:
      Live   — receives samples from PPGMonitor.update_plots() at the decimated rate.
      Offline — loads a recorded CSV file, processes all samples in batch, and displays
                the full time series as a static zoomable plot.

    Layout:
      Left  (wide) : 6 stacked time-series plots.
      Right (narrow): algorithm parameter controls, live value table, CSV buttons.
    """

    _BUF = SPO2_CAL_BUFSIZE   # rolling buffer length (shared with SpO2LabWindow)

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("SPO2TEST")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        self._calc            = SpO2TestCalc()
        self._last_sample_cnt = -1
        self._nominal_step    = None   # gap detection
        self.gap_count        = 0      # gap detection: lost samples since connect
        self._t0_us           = None
        self._last_r          = None
        self._offline_mode    = False

        # Rolling buffers (live mode)
        self._buf_t         = deque(maxlen=self._BUF)
        self._buf_spo2_fw   = deque(maxlen=self._BUF)
        self._buf_spo2_py   = deque(maxlen=self._BUF)
        self._buf_spo2_delta= deque(maxlen=self._BUF)
        self._buf_R_fw      = deque(maxlen=self._BUF)
        self._buf_R_py      = deque(maxlen=self._BUF)
        self._buf_sqi_fw    = deque(maxlen=self._BUF)
        self._buf_sqi_py    = deque(maxlen=self._BUF)
        self._buf_dc_ir     = deque(maxlen=self._BUF)
        self._buf_dc_red    = deque(maxlen=self._BUF)
        self._buf_rms_ir    = deque(maxlen=self._BUF)
        self._buf_rms_red   = deque(maxlen=self._BUF)

        # ── Root layout ───────────────────────────────────────────────────────
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_vbox = QtWidgets.QVBoxLayout(central)
        root_vbox.setContentsMargins(6, 6, 6, 4)
        root_vbox.setSpacing(4)

        # ── Toolbar row ───────────────────────────────────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_load = QtWidgets.QPushButton("LOAD CSV")
        self._btn_load.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_load.clicked.connect(self._load_csv)
        self._btn_load.setToolTip(_make_tooltip(
            "LOAD CSV",
            "Load a recorded CSV file (ppg_chk or ppg_data_raw format) for offline analysis. "
            "Processes all samples in batch and displays the full time series. "
            "Supported formats: ppg_chk_*.csv (CHK_OK column), ppg_data_raw_*.csv."))
        toolbar.addWidget(self._btn_load)

        self._btn_clear_offline = QtWidgets.QPushButton("BACK TO LIVE")
        self._btn_clear_offline.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_clear_offline.clicked.connect(self._clear_offline)
        self._btn_clear_offline.setEnabled(False)
        self._btn_clear_offline.setToolTip(_make_tooltip(
            "BACK TO LIVE",
            "Discard offline data and return to live serial mode."))
        toolbar.addWidget(self._btn_clear_offline)

        self._btn_export = QtWidgets.QPushButton("EXPORT CSV")
        self._btn_export.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_export.setToolTip(_make_tooltip(
            "EXPORT CSV",
            "Export the comparison table (firmware vs Python, delta) to a CSV file."))
        toolbar.addWidget(self._btn_export)

        toolbar.addStretch()

        # Parameter status indicator
        self._lbl_status = QtWidgets.QLabel("● FIRMWARE DEFAULTS")
        self._lbl_status.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
            "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip(
            "Parameter status",
            "GREEN — FIRMWARE DEFAULTS: all parameters match firmware values. "
            "The comparison between firmware output and Python mirror is valid.\n\n"
            "ORANGE — CUSTOM PARAMS: one or more parameters differ from firmware defaults. "
            "The Python mirror no longer replicates the firmware; comparison is exploratory."))
        toolbar.addWidget(self._lbl_status)

        root_vbox.addLayout(toolbar)

        # ── Main splitter ─────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(4)
        root_vbox.addWidget(splitter, stretch=1)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        splitter.addWidget(glw)

        def _mp(row, title, ylabel, link_to=None):
            p = glw.addPlot(row=row, col=0,
                            title=f"<b style='color:#CCCCCC'>{title}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel('left', ylabel)
            p.setLabel('bottom', 't (s)')
            p.enableAutoRange()
            if link_to is not None:
                p.setXLink(link_to)
            return p

        self.p_spo2  = _mp(0, "SpO2 (%)",          "%")
        self.p_delta = _mp(1, "SpO2 delta (fw−py)", "%",          link_to=self.p_spo2)
        self.p_R     = _mp(2, "R ratio",            "R",          link_to=self.p_spo2)
        self.p_sqi   = _mp(3, "SQI [0–1]",          "SQI",        link_to=self.p_spo2)
        self.p_dc    = _mp(4, "DC  (LED1, LED2)",       "ADC counts", link_to=self.p_spo2)
        self.p_ac    = _mp(5, "RMS AC  (LED1, LED2)",   "ADC counts", link_to=self.p_spo2)

        FW_PEN  = pg.mkPen('#00CC66', width=2)   # firmware: green
        PY_PEN  = pg.mkPen('#FFDD44', width=2)   # python:   yellow
        DLT_PEN = pg.mkPen('#FF6666', width=1.5) # delta:    red
        IR_PEN  = pg.mkPen('#4488FF', width=1.5)
        RED_PEN = pg.mkPen('#FF4444', width=1.5)
        IR2_PEN = pg.mkPen('#44AAFF', width=1.5)
        R2_PEN  = pg.mkPen('#FF6666', width=1.5)

        self.p_spo2.addLegend()
        self.curve_spo2_fw  = self.p_spo2.plot(pen=FW_PEN,  name="SpO2 fw")
        self.curve_spo2_py  = self.p_spo2.plot(pen=PY_PEN,  name="SpO2 py")
        self._zero_line_delta = pg.InfiniteLine(
            angle=0, pos=0, movable=False,
            pen=pg.mkPen('#555555', width=1, style=QtCore.Qt.DashLine))
        self.p_delta.addItem(self._zero_line_delta)
        self.curve_spo2_delta = self.p_delta.plot(pen=DLT_PEN, name="delta")
        self.p_R.addLegend()
        self.curve_R_fw  = self.p_R.plot(pen=FW_PEN,  name="R fw")
        self.curve_R_py  = self.p_R.plot(pen=PY_PEN,  name="R py")
        self.p_sqi.addLegend()
        self.curve_sqi_fw = self.p_sqi.plot(pen=FW_PEN,  name="SQI fw")
        self.curve_sqi_py = self.p_sqi.plot(pen=PY_PEN,  name="SQI py")
        self.p_sqi.setYRange(0, 1.05)
        self.p_dc.addLegend()
        self.curve_dc_led1  = self.p_dc.plot(pen=IR_PEN,  name="DC LED1 (IR)")
        self.curve_dc_led2 = self.p_dc.plot(pen=RED_PEN, name="DC LED2 (RED)")
        self.p_ac.addLegend()
        self.curve_rms_led1  = self.p_ac.plot(pen=IR2_PEN, name="RMS AC LED1 (IR)")
        self.curve_rms_led2 = self.p_ac.plot(pen=R2_PEN,  name="RMS AC LED2 (RED)")
        for _c in (self.curve_dc_led1, self.curve_dc_led2,
                   self.curve_rms_led1, self.curve_rms_led2):
            _c.setDownsampling(auto=True, method='peak')
            _c.setClipToView(True)

        # ── Right: parameters + table ─────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #1A1A1A;")
        splitter.addWidget(right)
        splitter.setSizes([900, 320])

        right_vbox = QtWidgets.QVBoxLayout(right)
        right_vbox.setContentsMargins(10, 10, 10, 10)
        right_vbox.setSpacing(10)

        # Parameters group
        grp_params = QtWidgets.QGroupBox("Algorithm parameters")
        grp_params.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        form = QtWidgets.QFormLayout(grp_params)
        form.setSpacing(6)
        _lbl_style = "color: #CCCCCC; font-size: 18px;"
        _spin_style = "background-color: #2A2A2A; color: #FFDD44; padding: 3px; font-size: 18px;"

        def _dspin(lo, hi, val, dec, step, suffix=""):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setDecimals(dec)
            w.setSingleStep(step)
            w.setValue(val)
            w.setStyleSheet(_spin_style)
            if suffix:
                w.setSuffix(suffix)
            return w

        self._spin_a       = _dspin(50.0,   200.0,  SpO2TestCalc.FW_SPO2_A,       4, 0.0001)
        self._spin_b       = _dspin(0.0,    100.0,  SpO2TestCalc.FW_SPO2_B,       4, 0.0001)
        self._spin_dc_tau  = _dspin(0.1,    20.0,   SpO2TestCalc.FW_DC_IIR_TAU_S, 1, 0.1,  " s")
        self._spin_ac_tau  = _dspin(0.1,    20.0,   SpO2TestCalc.FW_AC_EMA_TAU_S, 1, 0.1,  " s")
        self._spin_warmup  = _dspin(0.0,    60.0,   SpO2TestCalc.FW_WARMUP_S,     1, 0.5,  " s")
        self._spin_min_dc  = _dspin(0.0, 100000.0,  SpO2TestCalc.FW_SPO2_MIN_DC,  0, 100.0)

        self._spin_a.setToolTip(_make_tooltip(
            "SpO2 coefficient a",
            "SpO2 = a − b·R. Firmware default: 114.9208. "
            "Empirical calibration coefficient. Changing this shifts the SpO2 curve vertically.",
            src="spo2_a"))
        self._spin_b.setToolTip(_make_tooltip(
            "SpO2 coefficient b",
            "SpO2 = a − b·R. Firmware default: 30.5547. "
            "Empirical calibration coefficient. Changing this changes the slope of the SpO2 vs R curve.",
            src="spo2_b"))
        self._spin_dc_tau.setToolTip(_make_tooltip(
            "DC IIR time constant",
            "IIR low-pass filter time constant for DC level tracking [s]. "
            "Firmware default: 1.6 s. α = exp(−1/(τ·fs)).",
            src="spo2_ema_mean_tau_s"))
        self._spin_ac_tau.setToolTip(_make_tooltip(
            "AC EMA time constant",
            "EMA time constant for AC² tracking [s]. "
            "Firmware default: 1.0 s. β = 1 − exp(−1/(τ·fs)).",
            src="spo2_ema_var_tau_s"))
        self._spin_warmup.setToolTip(_make_tooltip(
            "Warmup period",
            "Number of seconds before the algorithm starts outputting valid SpO2 [s]. "
            "Firmware default: 5.0 s.",
            src="spo2_warmup_s"))
        self._spin_min_dc.setToolTip(_make_tooltip(
            "Min DC level",
            "Minimum DC level on both IR and RED channels to produce a valid SpO2 [ADC counts]. "
            "Firmware default: 1000. Below this → no finger detected.",
            src="spo2_min_dc"))

        _lbl = lambda t: (lambda: (w := QtWidgets.QLabel(t), w.setStyleSheet(_lbl_style), w)[-1])()
        form.addRow(_lbl("SpO2  a"),    self._spin_a)
        form.addRow(_lbl("SpO2  b"),    self._spin_b)
        form.addRow(_lbl("DC τ"),       self._spin_dc_tau)
        form.addRow(_lbl("AC τ"),       self._spin_ac_tau)
        form.addRow(_lbl("Warmup"),     self._spin_warmup)
        form.addRow(_lbl("Min DC"),     self._spin_min_dc)

        right_vbox.addWidget(grp_params)

        btn_reset = QtWidgets.QPushButton("RESET TO DEFAULTS")
        btn_reset.setStyleSheet(ACTION_BUTTON_STYLE)
        btn_reset.clicked.connect(self._reset_to_defaults)
        btn_reset.setToolTip(_make_tooltip(
            "RESET TO DEFAULTS",
            "Restore all algorithm parameters to their firmware default values and reset the "
            "Python mirror state. The comparison indicator returns to green (FIRMWARE DEFAULTS)."))
        right_vbox.addWidget(btn_reset)

        # Value table
        grp_vals = QtWidgets.QGroupBox("Current values")
        grp_vals.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        vals_vbox = QtWidgets.QVBoxLayout(grp_vals)

        self._val_table = QtWidgets.QTableWidget(8, 4)
        self._val_table.setHorizontalHeaderLabels(["Signal", "Firmware", "Python", "Delta"])
        self._val_table.verticalHeader().setVisible(False)
        self._val_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._val_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._val_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self._val_table.setStyleSheet(
            "QTableWidget { background-color: #1A1A1A; color: #E0E0E0; "
            "gridline-color: #333333; font-size: 17px; border: none; } "
            "QHeaderView::section { background-color: #2A2A2A; color: #AAAAAA; "
            "font-weight: bold; font-size: 17px; padding: 3px; }")
        _val_rows = ["SpO2 (%)", "R", "PI (%)", "SQI", "DC LED1 (IR)", "DC LED2 (RED)", "RMS AC LED1 (IR)", "RMS AC LED2 (RED)"]
        for r, name in enumerate(_val_rows):
            item = QtWidgets.QTableWidgetItem(name)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            self._val_table.setItem(r, 0, item)
            for c in range(1, 4):
                self._val_table.setItem(r, c, QtWidgets.QTableWidgetItem("---"))
        self._val_table.horizontalHeader().setStretchLastSection(True)
        self._val_table.resizeColumnsToContents()
        vals_vbox.addWidget(self._val_table)
        right_vbox.addWidget(grp_vals)

        right_vbox.addStretch()

        # Connect parameter spinboxes to update handler
        for sp in [self._spin_a, self._spin_b, self._spin_dc_tau,
                   self._spin_ac_tau, self._spin_warmup, self._spin_min_dc]:
            sp.valueChanged.connect(self._on_param_changed)

        # Cached arrays for offline/live plotting
        self._arr_t        = np.array([])
        self._arr_spo2_fw  = np.array([])
        self._arr_spo2_py  = np.array([])
        self._arr_R_fw     = np.array([])
        self._arr_R_py     = np.array([])
        self._arr_sqi_fw   = np.array([])
        self._arr_sqi_py   = np.array([])
        self._arr_dc_ir    = np.array([])
        self._arr_dc_red   = np.array([])
        self._arr_rms_ir   = np.array([])
        self._arr_rms_red  = np.array([])

        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("SpO2TestWindow/geometry")
        if geom: self.restoreGeometry(geom)

    # ── Parameter handling ────────────────────────────────────────────────────

    def _on_param_changed(self):
        """Called when any parameter spinbox changes. Pushes values to calc and updates indicator."""
        self._calc.dc_iir_tau_s = self._spin_dc_tau.value()
        self._calc.ac_ema_tau_s = self._spin_ac_tau.value()
        self._calc.spo2_min_dc  = self._spin_min_dc.value()
        self._calc.warmup_s     = self._spin_warmup.value()
        self._calc.spo2_a       = self._spin_a.value()
        self._calc.spo2_b       = self._spin_b.value()
        self._calc.reset()   # reset filter state when params change
        self._last_sample_cnt = -1
        self._t0_us = None
        self._clear_buffers()
        self._update_status_indicator()

    def _reset_to_defaults(self):
        for sp, attr in [
            (self._spin_a,      'FW_SPO2_A'),
            (self._spin_b,      'FW_SPO2_B'),
            (self._spin_dc_tau, 'FW_DC_IIR_TAU_S'),
            (self._spin_ac_tau, 'FW_AC_EMA_TAU_S'),
            (self._spin_warmup, 'FW_WARMUP_S'),
            (self._spin_min_dc, 'FW_SPO2_MIN_DC'),
        ]:
            sp.blockSignals(True)
            sp.setValue(getattr(SpO2TestCalc, attr))
            sp.blockSignals(False)
        self._calc.reset_to_defaults()
        self._last_sample_cnt = -1
        self._t0_us = None
        self._clear_buffers()
        self._update_status_indicator()

    def _update_status_indicator(self):
        if self._calc.using_defaults:
            self._lbl_status.setText("● FIRMWARE DEFAULTS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
                "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        else:
            self._lbl_status.setText("● CUSTOM PARAMS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FFAA00; padding: 4px 10px; "
                "background: #2A1A00; border: 1px solid #AA7700; border-radius: 4px;")

    def _clear_buffers(self):
        for buf in [self._buf_t, self._buf_spo2_fw, self._buf_spo2_py, self._buf_spo2_delta,
                    self._buf_R_fw, self._buf_R_py, self._buf_sqi_fw, self._buf_sqi_py,
                    self._buf_dc_ir, self._buf_dc_red, self._buf_rms_ir, self._buf_rms_red]:
            buf.clear()

    # ── Offline mode ──────────────────────────────────────────────────────────

    def _load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self._process_csv_offline(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Load CSV error", str(e))

    def _process_csv_offline(self, path):
        """Parse a CSV file and batch-process all samples through SpO2TestCalc."""
        import csv as _csv
        rows_led1_sub  = []
        rows_led2_sub = []
        rows_spo2_fw = []
        rows_R_fw    = []
        rows_sqi_fw  = []
        rows_ts_us   = []

        with open(path, 'r', newline='') as f:
            header = f.readline().strip()
            # Detect format by header
            is_chk = header.startswith("Timestamp_PC,Diff_us_PC,CHK_OK")
            is_raw = "FrameMode" in header
            reader = _csv.reader(f)
            for row in reader:
                if not row:
                    continue
                try:
                    if is_chk:
                        # Format: Timestamp_PC, Diff_us_PC, CHK_OK, RawFrame ($M1,...)
                        if len(row) < 4:
                            continue
                        chk_ok = row[2].strip()
                        if chk_ok != '1':
                            continue
                        raw = row[3].strip()
                        # Strip checksum *XX
                        if '*' in raw:
                            raw = raw[:raw.rfind('*')]
                        parts = raw.split(',')
                        if len(parts) < 20 or parts[0] not in ('$M1', '$M3'):
                            continue
                        # $M1,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,...
                        ts_us   = float(parts[2])
                        led1_sub  = float(parts[8])
                        led2_sub = float(parts[7])
                        spo2_fw = float(parts[10])
                        R_fw    = float(parts[12])
                        sqi_fw  = float(parts[11])
                    elif is_raw:
                        # Format: Timestamp_PC,Diff_us_PC,FrameMode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,...
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', 'M3', '$M1', '$M3'):
                            continue
                        offset = 3  # after Timestamp_PC, Diff_us_PC, FrameMode
                        ts_us   = float(row[offset + 1])
                        led1_sub  = float(row[offset + 7])
                        led2_sub = float(row[offset + 6])
                        spo2_fw = float(row[offset + 8])
                        R_fw    = float(row[offset + 10])
                        sqi_fw  = float(row[offset + 9])
                    else:
                        continue
                    rows_ts_us.append(ts_us)
                    rows_led1_sub.append(led1_sub)
                    rows_led2_sub.append(led2_sub)
                    rows_spo2_fw.append(spo2_fw if spo2_fw >= 0 else float('nan'))
                    rows_R_fw.append(R_fw if R_fw >= 0 else float('nan'))
                    rows_sqi_fw.append(sqi_fw if sqi_fw >= 0 else float('nan'))
                except (ValueError, IndexError):
                    continue

        if not rows_ts_us:
            raise ValueError("No valid M1 samples found in the file.")

        # Determine sample rate from timestamps
        ts_arr = np.array(rows_ts_us)
        diffs = np.diff(ts_arr)
        diffs = diffs[diffs > 0]
        fs = float(1e6 / np.median(diffs)) if len(diffs) else 500.0
        # Round to nearest standard rate
        for std_fs in [500, 250, 100, 50]:
            if abs(fs - std_fs) < std_fs * 0.2:
                fs = float(std_fs)
                break

        # Batch process
        self._calc.reset()
        nan = float('nan')
        t0 = ts_arr[0]

        arr_t        = (ts_arr - t0) / 1e6
        arr_spo2_fw  = np.array(rows_spo2_fw)
        arr_R_fw     = np.array(rows_R_fw)
        arr_sqi_fw   = np.array(rows_sqi_fw)
        arr_spo2_py  = np.full(len(rows_led1_sub), nan)
        arr_R_py     = np.full(len(rows_led1_sub), nan)
        arr_sqi_py   = np.full(len(rows_led1_sub), nan)
        arr_dc_ir    = np.full(len(rows_led1_sub), nan)
        arr_dc_red   = np.full(len(rows_led1_sub), nan)
        arr_rms_ir   = np.full(len(rows_led1_sub), nan)
        arr_rms_red  = np.full(len(rows_led1_sub), nan)

        for i, (ir, red) in enumerate(zip(rows_led1_sub, rows_led2_sub)):
            r = self._calc.update(ir, red, fs)
            arr_dc_ir[i]   = r['dc_ir']
            arr_dc_red[i]  = r['dc_red']
            arr_rms_ir[i]  = r['rms_ac_ir']
            arr_rms_red[i] = r['rms_ac_red']
            if not r['warmup'] and r['valid']:
                arr_spo2_py[i] = r['spo2']
                arr_R_py[i]    = r['R']
                arr_sqi_py[i]  = r['sqi']
            elif not r['warmup']:
                arr_spo2_py[i] = r['spo2']  # show even if invalid (clipped)
                arr_R_py[i]    = r['R']
                arr_sqi_py[i]  = r['sqi']

        arr_delta = arr_spo2_fw - arr_spo2_py

        # Store and display
        self._arr_t       = arr_t
        self._arr_spo2_fw = arr_spo2_fw
        self._arr_spo2_py = arr_spo2_py
        self._arr_R_fw    = arr_R_fw
        self._arr_R_py    = arr_R_py
        self._arr_sqi_fw  = arr_sqi_fw
        self._arr_sqi_py  = arr_sqi_py
        self._arr_dc_ir   = arr_dc_ir
        self._arr_dc_red  = arr_dc_red
        self._arr_rms_ir  = arr_rms_ir
        self._arr_rms_red = arr_rms_red

        self._offline_mode = True
        self._btn_clear_offline.setEnabled(True)
        fname = path.split('/')[-1].split('\\')[-1]
        self.statusBar().showMessage(
            f"OFFLINE — {fname}  ({len(rows_ts_us)} samples, fs≈{fs:.0f} Hz)")

        self._refresh_plots_from_arrays(arr_t, arr_spo2_fw, arr_spo2_py, arr_delta,
                                        arr_R_fw, arr_R_py, arr_sqi_fw, arr_sqi_py,
                                        arr_dc_ir, arr_dc_red, arr_rms_ir, arr_rms_red)

    def _clear_offline(self):
        self._offline_mode = False
        self._btn_clear_offline.setEnabled(False)
        self._last_sample_cnt = -1
        self._t0_us = None
        self._clear_buffers()
        self._calc.reset()
        self.statusBar().showMessage(_MOUSE_HINT)
        # Clear plots
        for c in [self.curve_spo2_fw, self.curve_spo2_py, self.curve_spo2_delta,
                  self.curve_R_fw, self.curve_R_py, self.curve_sqi_fw, self.curve_sqi_py,
                  self.curve_dc_led1, self.curve_dc_led2, self.curve_rms_led1, self.curve_rms_led2]:
            c.setData([], [])

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        t = self._arr_t if self._offline_mode else np.array(self._buf_t)
        if len(t) == 0:
            QtWidgets.QMessageBox.information(self, "Export", "No data to export.")
            return
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(CAPTURES_DIR, f"spo2test_{now_str}.csv")
        spo2_fw = self._arr_spo2_fw if self._offline_mode else np.array(self._buf_spo2_fw)
        spo2_py = self._arr_spo2_py if self._offline_mode else np.array(self._buf_spo2_py)
        R_fw    = self._arr_R_fw    if self._offline_mode else np.array(self._buf_R_fw)
        R_py    = self._arr_R_py    if self._offline_mode else np.array(self._buf_R_py)
        try:
            with open(filename, 'w') as f:
                f.write(f"# SPO2TEST export — {datetime.datetime.now()}\n")
                f.write(f"# a={self._calc.spo2_a:.4f}, b={self._calc.spo2_b:.4f}, "
                        f"dc_tau={self._calc.dc_iir_tau_s:.1f}s, ac_tau={self._calc.ac_ema_tau_s:.1f}s\n")
                f.write(f"# defaults={'YES' if self._calc.using_defaults else 'NO'}\n")
                f.write("t_s,spo2_fw,spo2_py,spo2_delta,R_fw,R_py\n")
                for i in range(len(t)):
                    def _fv(arr, i):
                        v = arr[i] if i < len(arr) else float('nan')
                        return f"{v:.4f}" if not np.isnan(v) else ""
                    delta = spo2_fw[i] - spo2_py[i] if i < len(spo2_fw) and i < len(spo2_py) else float('nan')
                    f.write(f"{t[i]:.4f},{_fv(spo2_fw,i)},{_fv(spo2_py,i)},"
                            f"{'%.4f'%delta if not np.isnan(delta) else ''},"
                            f"{_fv(R_fw,i)},{_fv(R_py,i)}\n")
            self.statusBar().showMessage(f"Exported: {filename}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export error", str(e))

    # ── Live update (called from PPGMonitor) ──────────────────────────────────

    def update_algorithms(self, data_led1_sub, data_led2_sub, data_spo2, data_spo2_r,
                          data_spo2_sqi, data_timestamp_us, data_sample_counter):
        """Run per-sample algorithm (called from PPGMonitor._process_frames_tick)."""
        if self._offline_mode:
            return
        n = len(data_sample_counter)
        if n == 0:
            return

        # Find new samples
        new_indices = []
        for i in range(n - 1, -1, -1):
            if data_sample_counter[i] <= self._last_sample_cnt:
                break
            new_indices.append(i)
        if not new_indices:
            return
        new_indices.reverse()

        # Gap detection: check for missing samples in new batch
        _counters = [int(data_sample_counter[i]) for i in new_indices]
        if self._nominal_step is None and len(_counters) >= 2:
            self._nominal_step = _counters[1] - _counters[0]
        if self._last_sample_cnt > 0 and self._nominal_step is not None:
            _gap = _counters[0] - self._last_sample_cnt - self._nominal_step
            if _gap > 0:
                self.gap_count += _gap
        if self._nominal_step is not None:
            for _j in range(len(_counters) - 1):
                _step = _counters[_j + 1] - _counters[_j]
                if _step > self._nominal_step:
                    self.gap_count += _step - self._nominal_step

        nan = float('nan')
        r = None
        for i in new_indices:
            ts     = float(data_timestamp_us[i])
            ir     = float(data_led1_sub[i])
            red    = float(data_led2_sub[i])
            spo2_f = float(data_spo2[i])
            R_f    = float(data_spo2_r[i])
            sqi_f  = float(data_spo2_sqi[i])

            if self._t0_us is None:
                self._t0_us = ts
            t_s = (ts - self._t0_us) / 1e6

            r = self._calc.update(ir, red, SPO2_RECEIVED_FS)

            spo2_fw_v = spo2_f if spo2_f >= 0 else nan
            R_fw_v    = R_f    if R_f    >= 0 else nan
            sqi_fw_v  = sqi_f  if sqi_f  >= 0 else nan
            spo2_py_v = r['spo2'] if not r['warmup'] else nan
            R_py_v    = r['R']   if not r['warmup'] else nan
            sqi_py_v  = r['sqi'] if not r['warmup'] else nan
            delta_v   = (spo2_fw_v - spo2_py_v) if not (np.isnan(spo2_fw_v) or np.isnan(spo2_py_v)) else nan

            self._buf_t.append(t_s)
            self._buf_spo2_fw.append(spo2_fw_v)
            self._buf_spo2_py.append(spo2_py_v)
            self._buf_spo2_delta.append(delta_v)
            self._buf_R_fw.append(R_fw_v)
            self._buf_R_py.append(R_py_v)
            self._buf_sqi_fw.append(sqi_fw_v)
            self._buf_sqi_py.append(sqi_py_v)
            self._buf_dc_ir.append(r['dc_ir'])
            self._buf_dc_red.append(r['dc_red'])
            self._buf_rms_ir.append(r['rms_ac_ir'])
            self._buf_rms_red.append(r['rms_ac_red'])

        self._last_r = r
        self._last_sample_cnt = data_sample_counter[-1]

    def update_plots(self):
        """Render pre-computed buffers (called from PPGMonitor._refresh_plots_tick)."""
        if self._offline_mode:
            return
        if not self._buf_t:
            return

        arr_t     = np.array(self._buf_t)
        arr_spo2_fw  = np.array(self._buf_spo2_fw)
        arr_spo2_py  = np.array(self._buf_spo2_py)
        arr_delta    = np.array(self._buf_spo2_delta)
        arr_R_fw     = np.array(self._buf_R_fw)
        arr_R_py     = np.array(self._buf_R_py)
        arr_sqi_fw   = np.array(self._buf_sqi_fw)
        arr_sqi_py   = np.array(self._buf_sqi_py)
        arr_dc_ir    = np.array(self._buf_dc_ir)
        arr_dc_red   = np.array(self._buf_dc_red)
        arr_rms_ir   = np.array(self._buf_rms_ir)
        arr_rms_red  = np.array(self._buf_rms_red)

        self._arr_t       = arr_t
        self._arr_spo2_fw = arr_spo2_fw
        self._arr_spo2_py = arr_spo2_py
        self._arr_R_fw    = arr_R_fw
        self._arr_R_py    = arr_R_py
        self._arr_sqi_fw  = arr_sqi_fw
        self._arr_sqi_py  = arr_sqi_py
        self._arr_dc_ir   = arr_dc_ir
        self._arr_dc_red  = arr_dc_red
        self._arr_rms_ir  = arr_rms_ir
        self._arr_rms_red = arr_rms_red

        self._refresh_plots_from_arrays(arr_t, arr_spo2_fw, arr_spo2_py, arr_delta,
                                        arr_R_fw, arr_R_py, arr_sqi_fw, arr_sqi_py,
                                        arr_dc_ir, arr_dc_red, arr_rms_ir, arr_rms_red)

        # Update value table with last valid values
        def _last_valid(arr):
            valid = arr[~np.isnan(arr)]
            return valid[-1] if len(valid) else float('nan')

        def _fmt(v, d=2):
            return f"{v:.{d}f}" if not np.isnan(v) else "---"

        fw_vals = [_last_valid(arr_spo2_fw), _last_valid(arr_R_fw),   float('nan'),
                   _last_valid(arr_sqi_fw),  float('nan'),             float('nan'),
                   float('nan'),             float('nan')]
        py_vals = [_last_valid(arr_spo2_py), _last_valid(arr_R_py),   float('nan'),
                   _last_valid(arr_sqi_py),  _last_valid(arr_dc_ir),  _last_valid(arr_dc_red),
                   _last_valid(arr_rms_ir),  _last_valid(arr_rms_red)]
        # PI and DC/AC from python mirror
        if self._last_r and not self._last_r['warmup']:
            py_vals[2] = self._last_r.get('pi', float('nan'))
        dec = [1, 5, 2, 3, 0, 0, 1, 1]
        for row in range(8):
            fv = fw_vals[row]
            pv = py_vals[row]
            dv = (fv - pv) if not (np.isnan(fv) or np.isnan(pv)) else float('nan')
            self._val_table.item(row, 1).setText(_fmt(fv, dec[row]))
            self._val_table.item(row, 2).setText(_fmt(pv, dec[row]))
            self._val_table.item(row, 3).setText(_fmt(dv, dec[row]))
            # Color delta column: green if |delta| < threshold, red otherwise
            if not np.isnan(dv) and row < 2:
                threshold = 1.0 if row == 0 else 0.05
                color = QtGui.QColor("#00CC66") if abs(dv) < threshold else QtGui.QColor("#FF4444")
                self._val_table.item(row, 3).setForeground(color)

    def _refresh_plots_from_arrays(self, t, spo2_fw, spo2_py, delta,
                                   R_fw, R_py, sqi_fw, sqi_py,
                                   dc_ir, dc_red, rms_ir, rms_red):
        self.curve_spo2_fw.setData(t, spo2_fw)
        self.curve_spo2_py.setData(t, spo2_py)
        self.curve_spo2_delta.setData(t, delta)
        self.curve_R_fw.setData(t, R_fw)
        self.curve_R_py.setData(t, R_py)
        self.curve_sqi_fw.setData(t, sqi_fw)
        self.curve_sqi_py.setData(t, sqi_py)
        self.curve_dc_led1.setData(t, dc_ir)
        self.curve_dc_led2.setData(t, dc_red)
        self.curve_rms_led1.setData(t, rms_ir)
        self.curve_rms_led2.setData(t, rms_red)

        def _last_valid(arr):
            valid = arr[~np.isnan(arr)]
            return valid[-1] if len(valid) else float('nan')

        def _fmt(v, d=2):
            return f"{v:.{d}f}" if not np.isnan(v) else "---"

        v_spo2_fw = _last_valid(spo2_fw)
        v_spo2_py = _last_valid(spo2_py)
        v_delta   = _last_valid(delta)
        self.p_spo2.setTitle(
            f"<b style='color:#00CC66'>SpO2 fw: {_fmt(v_spo2_fw,1)} %</b>"
            f"  <b style='color:#FFDD44'>py: {_fmt(v_spo2_py,1)} %</b>"
            f"  <span style='color:#FF6666'>Δ={_fmt(v_delta,2)}</span>")
        self.p_delta.setTitle(
            f"<b style='color:#CCCCCC'>SpO2 delta (fw−py):  {_fmt(v_delta,2)} %</b>")
        v_R_fw = _last_valid(R_fw)
        v_R_py = _last_valid(R_py)
        self.p_R.setTitle(
            f"<b style='color:#00CC66'>R fw: {_fmt(v_R_fw,5)}</b>"
            f"  <b style='color:#FFDD44'>R py: {_fmt(v_R_py,5)}</b>")

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("SpO2TestWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_spo2test.setChecked(False)
            self.main_monitor.spo2test_window = None
        super().closeEvent(event)


class HR1TestWindow(QtWidgets.QMainWindow):
    """HR1TEST — post-implementation verification window for the HR1 algorithm.

    Runs an independent Python mirror of the firmware HR1 algorithm (HR1TestCalc,
    derived from incunest_afe4490_spec.md §5.2) and compares its output against firmware values.

    PPGMonitor feeds HR1TestCalc at full 500 Hz (before decimation) in live mode.
    Offline mode: load a raw CSV (500 Hz) for exact comparison, or decimated (50 Hz)
    for approximate comparison (a status message indicates the detected rate).

    Layout:
      Left  : 4 stacked plots — signal chain (5 s window), HR1 fw/py, delta, SQI fw/py.
      Right : parameter controls, RR bar chart, current values table.
    """

    _HR_BUF = SPO2_CAL_BUFSIZE   # HR comparison rolling buffer (60 s at 50 Hz)

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor     = main_monitor
        self.setWindowTitle("HR1TEST")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        self._last_sample_cnt = -1
        self._t0_us           = None
        self._offline_mode    = False
        self._offline_calc    = HR1TestCalc()   # separate calc for offline (live uses PPGMonitor's)

        # Rolling buffers for HR comparison plots (fed at decimated rate)
        self._buf_t       = deque(maxlen=self._HR_BUF)
        self._buf_hr_fw   = deque(maxlen=self._HR_BUF)
        self._buf_hr_py   = deque(maxlen=self._HR_BUF)
        self._buf_hr_delta= deque(maxlen=self._HR_BUF)
        self._buf_sqi_fw  = deque(maxlen=self._HR_BUF)
        self._buf_sqi_py  = deque(maxlen=self._HR_BUF)

        # ── Root layout ───────────────────────────────────────────────────────
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_vbox = QtWidgets.QVBoxLayout(central)
        root_vbox.setContentsMargins(6, 6, 6, 4)
        root_vbox.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_load = QtWidgets.QPushButton("LOAD CSV")
        self._btn_load.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_load.clicked.connect(self._load_csv)
        self._btn_load.setToolTip(_make_tooltip(
            "LOAD CSV",
            "Load a recorded CSV file for offline analysis. "
            "ppg_data_raw_*.csv (500 Hz) gives exact comparison with firmware. "
            "ppg_chk_*.csv (500 Hz) is also supported. "
            "Decimated CSVs (50 Hz) are accepted but give approximate results."))
        toolbar.addWidget(self._btn_load)

        self._btn_clear = QtWidgets.QPushButton("BACK TO LIVE")
        self._btn_clear.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_clear.clicked.connect(self._clear_offline)
        self._btn_clear.setEnabled(False)
        self._btn_clear.setToolTip(_make_tooltip(
            "BACK TO LIVE", "Discard offline data and return to live serial mode."))
        toolbar.addWidget(self._btn_clear)

        self._btn_export = QtWidgets.QPushButton("EXPORT CSV")
        self._btn_export.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_export.setToolTip(_make_tooltip(
            "EXPORT CSV", "Export HR1 comparison table (firmware vs Python, delta) to a CSV file."))
        toolbar.addWidget(self._btn_export)

        toolbar.addStretch()

        self._lbl_status = QtWidgets.QLabel("● FIRMWARE DEFAULTS")
        self._lbl_status.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
            "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip(
            "Parameter status",
            "GREEN — FIRMWARE DEFAULTS: all parameters match firmware. Comparison is valid.\n"
            "ORANGE — CUSTOM PARAMS: parameters differ from firmware; comparison is exploratory."))
        toolbar.addWidget(self._lbl_status)

        root_vbox.addLayout(toolbar)

        # ── Main splitter ─────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(4)
        root_vbox.addWidget(splitter, stretch=1)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        splitter.addWidget(glw)

        def _mp(row, title, ylabel, link_to=None):
            p = glw.addPlot(row=row, col=0,
                            title=f"<b style='color:#CCCCCC'>{title}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel('left', ylabel)
            p.setLabel('bottom', 't (s)')
            p.enableAutoRange()
            if link_to is not None:
                p.setXLink(link_to)
            return p

        self.p_chain = _mp(0, "Signal chain  (last 5 s)", "ADC counts")
        self.p_hr    = _mp(1, "HR1 (bpm)",                "BPM")
        self.p_delta = _mp(2, "HR1 delta (fw−py)",        "BPM",  link_to=self.p_hr)
        self.p_sqi   = _mp(3, "SQI [0–1]",               "SQI",  link_to=self.p_hr)
        self.p_sqi.setYRange(0, 1.05)

        FW_PEN   = pg.mkPen('#00CC66', width=2)
        PY_PEN   = pg.mkPen('#FFDD44', width=2)
        DLT_PEN  = pg.mkPen('#FF6666', width=1.5)
        DCR_PEN  = pg.mkPen('#44AAFF', width=1)    # DC-removed: thin blue
        MAF_PEN  = pg.mkPen('#FFDD44', width=1.5)  # MA-filtered: yellow
        MAX_PEN  = pg.mkPen('#FF8800', width=1, style=QtCore.Qt.DashLine)   # running max: orange dashed
        THR_PEN  = pg.mkPen('#FF3333', width=1, style=QtCore.Qt.DashLine)   # threshold:   red dashed

        self.p_chain.addLegend()
        self.curve_dc_removed  = self.p_chain.plot(pen=DCR_PEN, name="DC-removed")
        self.curve_ma_filtered = self.p_chain.plot(pen=MAF_PEN, name="MA-filtered")
        self.curve_running_max = self.p_chain.plot(pen=MAX_PEN, name="running max")
        self.curve_threshold   = self.p_chain.plot(pen=THR_PEN, name="threshold")
        for _c in (self.curve_dc_removed, self.curve_ma_filtered,
                   self.curve_running_max, self.curve_threshold):
            _c.setDownsampling(auto=True, method='peak')
            _c.setClipToView(True)
        self.scatter_peaks     = pg.ScatterPlotItem(
            size=10, pen=pg.mkPen(None), brush=pg.mkBrush('#00FF88'))
        self.p_chain.addItem(self.scatter_peaks)

        self.p_hr.addLegend()
        self.curve_hr_fw  = self.p_hr.plot(pen=FW_PEN,  name="HR1 fw")
        self.curve_hr_py  = self.p_hr.plot(pen=PY_PEN,  name="HR1 py")
        self._zero_delta  = pg.InfiniteLine(
            angle=0, pos=0, movable=False,
            pen=pg.mkPen('#555555', width=1, style=QtCore.Qt.DashLine))
        self.p_delta.addItem(self._zero_delta)
        self.curve_hr_delta = self.p_delta.plot(pen=DLT_PEN)
        self.p_sqi.addLegend()
        self.curve_sqi_fw = self.p_sqi.plot(pen=FW_PEN,  name="SQI fw")
        self.curve_sqi_py = self.p_sqi.plot(pen=PY_PEN,  name="SQI py")

        # ── Right: parameters + table ─────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #1A1A1A;")
        splitter.addWidget(right)
        splitter.setSizes([900, 320])

        right_vbox = QtWidgets.QVBoxLayout(right)
        right_vbox.setContentsMargins(10, 10, 10, 10)
        right_vbox.setSpacing(10)

        # Parameters
        grp_params = QtWidgets.QGroupBox("Algorithm parameters")
        grp_params.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        form = QtWidgets.QFormLayout(grp_params)
        form.setSpacing(6)
        _lbl_s = "color: #CCCCCC; font-size: 18px;"
        _sp_s  = "background-color: #2A2A2A; color: #FFDD44; padding: 3px; font-size: 18px;"

        def _dspin(lo, hi, val, dec, step, suffix=""):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi); w.setDecimals(dec); w.setSingleStep(step)
            w.setValue(val); w.setStyleSheet(_sp_s)
            if suffix: w.setSuffix(suffix)
            return w

        def _ispin(lo, hi, val):
            w = QtWidgets.QSpinBox()
            w.setRange(lo, hi); w.setValue(val); w.setStyleSheet(_sp_s)
            return w

        self._spin_dc_tau    = _dspin(0.1, 20.0,  HR1TestCalc.FW_DC_IIR_TAU_S,      1, 0.1, " s")
        self._spin_ma_cut    = _dspin(0.5, 50.0,  HR1TestCalc.FW_MA_CUTOFF_HZ,       1, 0.5, " Hz")
        self._spin_ma_max    = _ispin(1,   256,   HR1TestCalc.FW_MA_MAX_LEN)
        self._spin_decay     = _dspin(0.99, 1.0,  HR1TestCalc.FW_RUNNING_MAX_DECAY,  6, 0.0001)
        self._spin_thr       = _dspin(0.1,  1.0,  HR1TestCalc.FW_THRESHOLD_FACTOR,   2, 0.05)
        self._spin_refr      = _dspin(0.05, 2.0,  HR1TestCalc.FW_REFRACTORY_S,       3, 0.005, " s")

        self._spin_dc_tau.setToolTip(_make_tooltip("DC IIR τ",
            "Time constant for IIR DC removal [s]. Firmware default: 1.6 s. "
            "α = exp(−1/(τ·fs)). Larger τ → slower DC tracking.",
            src="hr1_dc_iir_tau_s"))
        self._spin_ma_cut.setToolTip(_make_tooltip("MA cutoff",
            "Moving average low-pass cutoff frequency [Hz]. Firmware default: 5 Hz. "
            "MA length = fs / (2 × cutoff), capped at MA max len.",
            src="hr1_ma_cutoff_hz"))
        self._spin_ma_max.setToolTip(_make_tooltip("MA max len",
            "Maximum moving average window length [samples]. Firmware default: 64.",
            src="hr1_ma_max_len"))
        self._spin_decay.setToolTip(_make_tooltip("Running max decay",
            "Per-sample exponential decay factor for the running maximum. "
            "Firmware default: 0.9999. Values < 1 make the tracker forget old peaks.",
            src="hr1_running_max_decay"))
        self._spin_thr.setToolTip(_make_tooltip("Threshold factor",
            "Rising-edge threshold = factor × running_max. Firmware default: 0.6.",
            src="hr1_threshold_factor"))
        self._spin_refr.setToolTip(_make_tooltip("Refractory period",
            "Minimum time between two detected peaks [s]. Firmware default: 0.2 s (~300 BPM max).",
            src="hr1_refractory_s"))

        def _lbl(t):
            w = QtWidgets.QLabel(t); w.setStyleSheet(_lbl_s); return w

        form.addRow(_lbl("DC τ"),          self._spin_dc_tau)
        form.addRow(_lbl("MA cutoff"),     self._spin_ma_cut)
        form.addRow(_lbl("MA max len"),    self._spin_ma_max)
        form.addRow(_lbl("Max decay"),     self._spin_decay)
        form.addRow(_lbl("Threshold"),     self._spin_thr)
        form.addRow(_lbl("Refractory"),    self._spin_refr)
        right_vbox.addWidget(grp_params)

        btn_reset = QtWidgets.QPushButton("RESET TO DEFAULTS")
        btn_reset.setStyleSheet(ACTION_BUTTON_STYLE)
        btn_reset.clicked.connect(self._reset_to_defaults)
        btn_reset.setToolTip(_make_tooltip("RESET TO DEFAULTS",
            "Restore all parameters to firmware defaults and reset the Python mirror state."))
        right_vbox.addWidget(btn_reset)

        # RR intervals bar chart
        grp_rr = QtWidgets.QGroupBox("Last 5 RR intervals")
        grp_rr.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        rr_vbox = QtWidgets.QVBoxLayout(grp_rr)
        rr_gw = pg.GraphicsLayoutWidget()
        rr_gw.setFixedHeight(120)
        self._rr_plot = rr_gw.addPlot()
        self._rr_plot.setLabel('left', 'samples')
        self._rr_plot.showGrid(y=True, alpha=0.3)
        self._rr_plot.getAxis('bottom').setTicks([[(i, str(i+1)) for i in range(5)]])
        self._rr_bars = pg.BarGraphItem(x=list(range(5)), height=[0]*5, width=0.6,
                                        brush='#4488FF')
        self._rr_plot.addItem(self._rr_bars)
        rr_vbox.addWidget(rr_gw)
        right_vbox.addWidget(grp_rr)

        # Current values table
        grp_vals = QtWidgets.QGroupBox("Current values")
        grp_vals.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        vals_vbox = QtWidgets.QVBoxLayout(grp_vals)
        self._val_table = QtWidgets.QTableWidget(2, 4)
        self._val_table.setHorizontalHeaderLabels(["Signal", "Firmware", "Python", "Delta"])
        self._val_table.verticalHeader().setVisible(False)
        self._val_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._val_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._val_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self._val_table.setStyleSheet(
            "QTableWidget { background-color: #1A1A1A; color: #E0E0E0; "
            "gridline-color: #333333; font-size: 17px; border: none; } "
            "QHeaderView::section { background-color: #2A2A2A; color: #AAAAAA; "
            "font-weight: bold; font-size: 17px; padding: 3px; }")
        for r, name in enumerate(["HR1 (bpm)", "SQI"]):
            item = QtWidgets.QTableWidgetItem(name)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            self._val_table.setItem(r, 0, item)
            for c in range(1, 4):
                self._val_table.setItem(r, c, QtWidgets.QTableWidgetItem("---"))
        self._val_table.horizontalHeader().setStretchLastSection(True)
        self._val_table.resizeColumnsToContents()
        vals_vbox.addWidget(self._val_table)
        right_vbox.addWidget(grp_vals)

        right_vbox.addStretch()

        # Connect parameter spinboxes
        for sp in [self._spin_dc_tau, self._spin_ma_cut, self._spin_decay,
                   self._spin_thr, self._spin_refr]:
            sp.valueChanged.connect(self._on_param_changed)
        self._spin_ma_max.valueChanged.connect(self._on_param_changed)

        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("HR1TestWindow/geometry")
        if geom: self.restoreGeometry(geom)

    # ── Parameter handling ────────────────────────────────────────────────────

    def _get_live_calc(self):
        """Return the HR1TestCalc used for live mode (owned by PPGMonitor)."""
        if self.main_monitor is not None and hasattr(self.main_monitor, 'hr1test_calc'):
            return self.main_monitor.hr1test_calc
        return self._offline_calc

    def _on_param_changed(self):
        calc = self._get_live_calc() if not self._offline_mode else self._offline_calc
        calc.dc_iir_tau_s      = self._spin_dc_tau.value()
        calc.ma_cutoff_hz      = self._spin_ma_cut.value()
        calc.ma_max_len        = self._spin_ma_max.value()
        calc.running_max_decay = self._spin_decay.value()
        calc.threshold_factor  = self._spin_thr.value()
        calc.refractory_s      = self._spin_refr.value()
        calc.reset()
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self._update_status_indicator()

    def _reset_to_defaults(self):
        for sp, attr in [
            (self._spin_dc_tau, 'FW_DC_IIR_TAU_S'),
            (self._spin_ma_cut, 'FW_MA_CUTOFF_HZ'),
            (self._spin_ma_max, 'FW_MA_MAX_LEN'),
            (self._spin_decay,  'FW_RUNNING_MAX_DECAY'),
            (self._spin_thr,    'FW_THRESHOLD_FACTOR'),
            (self._spin_refr,   'FW_REFRACTORY_S'),
        ]:
            sp.blockSignals(True)
            sp.setValue(getattr(HR1TestCalc, attr))
            sp.blockSignals(False)
        calc = self._get_live_calc() if not self._offline_mode else self._offline_calc
        calc.reset_to_defaults()
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self._update_status_indicator()

    def _update_status_indicator(self):
        calc = self._get_live_calc() if not self._offline_mode else self._offline_calc
        if calc.using_defaults:
            self._lbl_status.setText("● FIRMWARE DEFAULTS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
                "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        else:
            self._lbl_status.setText("● CUSTOM PARAMS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FFAA00; padding: 4px 10px; "
                "background: #2A1A00; border: 1px solid #AA7700; border-radius: 4px;")

    # ── Offline mode ──────────────────────────────────────────────────────────

    def _load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self._process_csv_offline(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Load CSV error", str(e))

    def _process_csv_offline(self, path):
        import csv as _csv
        rows_led1_sub = []
        rows_hr_fw  = []
        rows_sqi_fw = []
        rows_ts_us  = []
        with open(path, 'r', newline='') as f:
            header = f.readline().strip()
            is_chk = header.startswith("Timestamp_PC,Diff_us_PC,CHK_OK")
            reader = _csv.reader(f)
            for row in reader:
                if not row:
                    continue
                try:
                    if is_chk:
                        if len(row) < 4 or row[2].strip() != '1':
                            continue
                        raw = row[3].strip()
                        if '*' in raw:
                            raw = raw[:raw.rfind('*')]
                        parts = raw.split(',')
                        if len(parts) < 20 or parts[0] not in ('$M1', '$M3'):
                            continue
                        ts_us  = float(parts[2])
                        led1_sub = float(parts[8])
                        hr_fw  = float(parts[14])
                        sqi_fw = float(parts[15])
                    else:
                        # FrameMode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,...,HR1,HR1_SQI,...
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', 'M3', '$M1', '$M3'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        led1_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 12])
                        sqi_fw = float(row[offset + 13])
                    rows_ts_us.append(ts_us)
                    rows_led1_sub.append(led1_sub)
                    rows_hr_fw.append(hr_fw if hr_fw > 0 else float('nan'))
                    rows_sqi_fw.append(sqi_fw if sqi_fw >= 0 else float('nan'))
                except (ValueError, IndexError):
                    continue

        if not rows_ts_us:
            raise ValueError("No valid M1 samples found.")

        ts_arr = np.array(rows_ts_us)
        diffs = np.diff(ts_arr)
        diffs = diffs[diffs > 0]
        fs = float(1e6 / np.median(diffs)) if len(diffs) else 500.0
        for std_fs in [500, 250, 100, 50]:
            if abs(fs - std_fs) < std_fs * 0.2:
                fs = float(std_fs)
                break

        self._offline_calc.reset_to_defaults()
        # Apply current spinbox params to offline calc
        self._offline_calc.dc_iir_tau_s      = self._spin_dc_tau.value()
        self._offline_calc.ma_cutoff_hz      = self._spin_ma_cut.value()
        self._offline_calc.ma_max_len        = self._spin_ma_max.value()
        self._offline_calc.running_max_decay = self._spin_decay.value()
        self._offline_calc.threshold_factor  = self._spin_thr.value()
        self._offline_calc.refractory_s      = self._spin_refr.value()
        self._offline_calc.reset()

        nan = float('nan')
        n = len(rows_led1_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_led1_sub):
            self._offline_calc.update(ir, fs)
            hr_py = self._offline_calc.hr_bpm
            sq_py = self._offline_calc.hr_sqi
            if hr_py > 0:
                arr_hr_py[i]  = hr_py
                arr_sqi_py[i] = sq_py

        arr_delta = arr_hr_fw - arr_hr_py

        # For the signal chain, use whatever is in the diagnostic buffer at the end
        diag_dc  = np.array(self._offline_calc.diag_dc_removed)
        diag_ma  = np.array(self._offline_calc.diag_ma_filtered)
        diag_max = np.array(self._offline_calc.diag_running_max)
        diag_thr = np.array(self._offline_calc.diag_threshold)
        diag_pk  = np.array(self._offline_calc.diag_peak_mask)
        diag_n   = len(diag_dc)
        # Time axis for diagnostic (last DIAG_BUF_LEN samples of the recording)
        diag_offset = max(0, n - diag_n)
        diag_t = arr_t[diag_offset: diag_offset + diag_n] if diag_n <= n else arr_t[:diag_n]

        self._offline_mode = True
        self._btn_clear.setEnabled(True)
        fname = path.split('/')[-1].split('\\')[-1]
        rate_note = "" if fs >= 400 else f"  ⚠ {fs:.0f} Hz — load RAW CSV for exact comparison"
        self.statusBar().showMessage(f"OFFLINE — {fname}  ({n} samples, fs≈{fs:.0f} Hz){rate_note}")

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sqi_fw, arr_sqi_py)
        self._refresh_chain_plot(diag_t, diag_dc, diag_ma, diag_max, diag_thr, diag_pk, fs)
        self._update_status_indicator()

    def _clear_offline(self):
        self._offline_mode = False
        self._btn_clear.setEnabled(False)
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self.statusBar().showMessage(_MOUSE_HINT)
        for c in [self.curve_dc_removed, self.curve_ma_filtered,
                  self.curve_running_max, self.curve_threshold,
                  self.curve_hr_fw, self.curve_hr_py, self.curve_hr_delta,
                  self.curve_sqi_fw, self.curve_sqi_py]:
            c.setData([], [])
        self.scatter_peaks.setData([], [])

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        t      = np.array(self._buf_t)
        hr_fw  = np.array(self._buf_hr_fw)
        hr_py  = np.array(self._buf_hr_py)
        if len(t) == 0:
            QtWidgets.QMessageBox.information(self, "Export", "No data to export.")
            return
        now_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(CAPTURES_DIR, f"hr1test_{now_str}.csv")
        try:
            calc = self._get_live_calc() if not self._offline_mode else self._offline_calc
            with open(filename, 'w') as f:
                f.write(f"# HR1TEST export — {datetime.datetime.now()}\n")
                f.write(f"# dc_tau={calc.dc_iir_tau_s:.1f}s, ma_cut={calc.ma_cutoff_hz:.1f}Hz, "
                        f"decay={calc.running_max_decay:.4f}, thr={calc.threshold_factor:.2f}, "
                        f"refr={calc.refractory_s:.3f}s\n")
                f.write(f"# defaults={'YES' if calc.using_defaults else 'NO'}\n")
                f.write("t_s,hr1_fw,hr1_py,hr1_delta,sqi_fw,sqi_py\n")
                sqi_fw = np.array(self._buf_sqi_fw)
                sqi_py = np.array(self._buf_sqi_py)
                for i in range(len(t)):
                    def _fv(arr, i): v = arr[i] if i < len(arr) else nan; return f"{v:.2f}" if not np.isnan(v) else ""
                    nan = float('nan')
                    delta = hr_fw[i] - hr_py[i] if i < len(hr_fw) and i < len(hr_py) else nan
                    f.write(f"{t[i]:.3f},{_fv(hr_fw,i)},{_fv(hr_py,i)},"
                            f"{'%.2f'%delta if not np.isnan(delta) else ''},"
                            f"{_fv(sqi_fw,i)},{_fv(sqi_py,i)}\n")
            self.statusBar().showMessage(f"Exported: {filename}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export error", str(e))

    # ── Live update (called from PPGMonitor) ──────────────────────────────────

    def update_plots(self, data_hr1, data_hr1_sqi, data_timestamp_us, data_sample_counter):
        """Update HR comparison plots. Signal chain is read from PPGMonitor's hr1test_calc."""
        if self._offline_mode:
            return
        n = len(data_sample_counter)
        if n == 0:
            return

        new_indices = []
        for i in range(n - 1, -1, -1):
            if data_sample_counter[i] <= self._last_sample_cnt:
                break
            new_indices.append(i)
        if not new_indices:
            return
        new_indices.reverse()

        nan = float('nan')
        for i in new_indices:
            ts    = float(data_timestamp_us[i])
            hr_f  = float(data_hr1[i])
            sqi_f = float(data_hr1_sqi[i])
            if self._t0_us is None:
                self._t0_us = ts
            t_s = (ts - self._t0_us) / 1e6

            calc = self._get_live_calc()
            hr_py  = calc.hr_bpm if calc.hr_bpm > 0 else nan
            sqi_py = calc.hr_sqi if calc.hr_bpm > 0 else nan
            hr_fw  = hr_f  if hr_f  > 0 else nan
            sqi_fw = sqi_f if sqi_f >= 0 else nan
            delta  = (hr_fw - hr_py) if not (np.isnan(hr_fw) or np.isnan(hr_py)) else nan

            self._buf_t.append(t_s)
            self._buf_hr_fw.append(hr_fw)
            self._buf_hr_py.append(hr_py)
            self._buf_hr_delta.append(delta)
            self._buf_sqi_fw.append(sqi_fw)
            self._buf_sqi_py.append(sqi_py)

        self._last_sample_cnt = data_sample_counter[-1]

        arr_t     = np.array(self._buf_t)
        arr_hr_fw = np.array(self._buf_hr_fw)
        arr_hr_py = np.array(self._buf_hr_py)
        arr_delta = np.array(self._buf_hr_delta)
        arr_sf    = np.array(self._buf_sqi_fw)
        arr_sp    = np.array(self._buf_sqi_py)

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sf, arr_sp)

        # Signal chain from live calc diagnostic buffers
        calc = self._get_live_calc()
        fs   = calc._fs if calc._fs > 0 else 500.0
        diag_dc  = np.array(calc.diag_dc_removed)
        diag_ma  = np.array(calc.diag_ma_filtered)
        diag_max = np.array(calc.diag_running_max)
        diag_thr = np.array(calc.diag_threshold)
        diag_pk  = np.array(calc.diag_peak_mask)
        diag_n   = len(diag_dc)
        if diag_n > 0:
            # Relative time axis: last diag_n samples
            t_end = arr_t[-1] if len(arr_t) else 0.0
            diag_t = t_end - (diag_n - 1 - np.arange(diag_n)) / fs
            self._refresh_chain_plot(diag_t, diag_dc, diag_ma, diag_max, diag_thr, diag_pk, fs)

        # RR bar chart
        rr = calc.rr_buf_copy
        heights = list(rr) + [0] * (5 - len(rr))
        self._rr_bars.setOpts(height=heights[:5])

        # Value table
        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        fw_vals = [_lv(arr_hr_fw), _lv(arr_sf)]
        py_vals = [_lv(arr_hr_py), _lv(arr_sp)]
        dec     = [1, 3]
        for row in range(2):
            fv = fw_vals[row]; pv = py_vals[row]
            dv = (fv - pv) if not (np.isnan(fv) or np.isnan(pv)) else float('nan')
            self._val_table.item(row, 1).setText(_fmt(fv, dec[row]))
            self._val_table.item(row, 2).setText(_fmt(pv, dec[row]))
            self._val_table.item(row, 3).setText(_fmt(dv, dec[row]))
            if not np.isnan(dv) and row == 0:
                color = QtGui.QColor("#00CC66") if abs(dv) < 3.0 else QtGui.QColor("#FF4444")
                self._val_table.item(row, 3).setForeground(color)

        self._update_status_indicator()

    def _refresh_hr_plots(self, t, hr_fw, hr_py, delta, sqi_fw, sqi_py):
        self.curve_hr_fw.setData(t, hr_fw)
        self.curve_hr_py.setData(t, hr_py)
        self.curve_hr_delta.setData(t, delta)
        self.curve_sqi_fw.setData(t, sqi_fw)
        self.curve_sqi_py.setData(t, sqi_py)

        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        v_fw = _lv(hr_fw); v_py = _lv(hr_py); v_d = _lv(delta)
        self.p_hr.setTitle(
            f"<b style='color:#00CC66'>HR1 fw: {_fmt(v_fw)} bpm</b>"
            f"  <b style='color:#FFDD44'>py: {_fmt(v_py)} bpm</b>"
            f"  <span style='color:#FF6666'>Δ={_fmt(v_d)}</span>")
        self.p_delta.setTitle(
            f"<b style='color:#CCCCCC'>HR1 delta (fw−py): {_fmt(v_d)} bpm</b>")

    def _refresh_chain_plot(self, t, dc_rem, ma_filt, run_max, thresh, peak_mask, fs):
        self.curve_dc_removed.setData(t, dc_rem)
        self.curve_ma_filtered.setData(t, ma_filt)
        self.curve_running_max.setData(t, run_max)
        self.curve_threshold.setData(t, thresh)
        # Peak scatter: show MA-filtered value at peak samples
        peak_idx = np.where(peak_mask > 0)[0]
        if len(peak_idx) > 0 and len(ma_filt) > 0:
            px = t[peak_idx[peak_idx < len(t)]]
            py = ma_filt[peak_idx[peak_idx < len(ma_filt)]]
            self.scatter_peaks.setData(x=px, y=py)
        else:
            self.scatter_peaks.setData([], [])
        diag_n = len(dc_rem)
        if diag_n > 0:
            t_range = diag_n / fs
            self.p_chain.setTitle(
                f"<b style='color:#CCCCCC'>Signal chain  (last {t_range:.1f} s, "
                f"MA len={int(round(fs / (2.0 * (self._spin_ma_cut.value() or 1))))}, "
                f"fs={fs:.0f} Hz)</b>")

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("HR1TestWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hr1test.setChecked(False)
            self.main_monitor.hr1test_window = None
        super().closeEvent(event)


class HR2TestWindow(QtWidgets.QMainWindow):
    """HR2TEST — post-implementation verification window for the HR2 algorithm.

    Runs an independent Python mirror of the firmware HR2 algorithm (HR2TestCalc,
    derived from incunest_afe4490_spec.md §5.3) and compares against firmware output.

    The mirror runs at the decimated rate (50 Hz default) fed from PPGMonitor.update_plots().
    Offline mode: load any recorded CSV.

    Layout:
      Left  : 4 stacked plots — autocorrelation curve, filtered buffer, HR2 fw/py, SQI fw/py.
      Right : parameter controls and current values table.
    """

    _HR_BUF = SPO2_CAL_BUFSIZE

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor     = main_monitor
        self.setWindowTitle("HR2TEST")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        self._calc            = HR2TestCalc()
        self._last_sample_cnt = -1
        self._nominal_step    = None   # gap detection
        self.gap_count        = 0      # gap detection: lost samples since connect
        self._t0_us           = None
        self._offline_mode    = False

        self._buf_t       = deque(maxlen=self._HR_BUF)
        self._buf_hr_fw   = deque(maxlen=self._HR_BUF)
        self._buf_hr_py   = deque(maxlen=self._HR_BUF)
        self._buf_hr_delta= deque(maxlen=self._HR_BUF)
        self._buf_sqi_fw  = deque(maxlen=self._HR_BUF)
        self._buf_sqi_py  = deque(maxlen=self._HR_BUF)

        # ── Root layout ───────────────────────────────────────────────────────
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_vbox = QtWidgets.QVBoxLayout(central)
        root_vbox.setContentsMargins(6, 6, 6, 4)
        root_vbox.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_load = QtWidgets.QPushButton("LOAD CSV")
        self._btn_load.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_load.clicked.connect(self._load_csv)
        self._btn_load.setToolTip(_make_tooltip("LOAD CSV",
            "Load a recorded CSV file for offline analysis. "
            "HR2 runs at 50 Hz (after decimation); any recorded CSV format is accepted."))
        toolbar.addWidget(self._btn_load)

        self._btn_clear = QtWidgets.QPushButton("BACK TO LIVE")
        self._btn_clear.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_clear.clicked.connect(self._clear_offline)
        self._btn_clear.setEnabled(False)
        self._btn_clear.setToolTip(_make_tooltip("BACK TO LIVE",
            "Discard offline data and return to live serial mode."))
        toolbar.addWidget(self._btn_clear)

        self._btn_export = QtWidgets.QPushButton("EXPORT CSV")
        self._btn_export.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_export.setToolTip(_make_tooltip("EXPORT CSV",
            "Export HR2 comparison table to a CSV file."))
        toolbar.addWidget(self._btn_export)

        toolbar.addStretch()

        self._lbl_status = QtWidgets.QLabel("● FIRMWARE DEFAULTS")
        self._lbl_status.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
            "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip("Parameter status",
            "GREEN — FIRMWARE DEFAULTS: comparison is valid.\n"
            "ORANGE — CUSTOM PARAMS: comparison is exploratory."))
        toolbar.addWidget(self._lbl_status)

        root_vbox.addLayout(toolbar)

        # ── Main splitter ─────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(4)
        root_vbox.addWidget(splitter, stretch=1)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        splitter.addWidget(glw)

        def _mp(row, title, ylabel, link_to=None):
            p = glw.addPlot(row=row, col=0,
                            title=f"<b style='color:#CCCCCC'>{title}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel('left', ylabel)
            p.enableAutoRange()
            if link_to is not None:
                p.setXLink(link_to)
            return p

        self.p_acorr  = _mp(0, "Autocorrelation",       "normalised")
        self.p_filt   = _mp(1, "BPF signal  (400 s buffer)", "ADC counts")
        self.p_hr     = _mp(2, "HR2 (bpm)",              "BPM")
        self.p_sqi    = _mp(3, "SQI [0–1]",              "SQI", link_to=self.p_hr)

        self.p_acorr.setLabel('bottom', 'lag (s)')
        self.p_filt.setLabel('bottom', 't (s)')
        self.p_hr.setLabel('bottom', 't (s)')
        self.p_sqi.setLabel('bottom', 't (s)')
        self.p_sqi.setYRange(0, 1.05)

        FW_PEN  = pg.mkPen('#00CC66', width=2)
        PY_PEN  = pg.mkPen('#FFDD44', width=2)
        ACORR_PEN = pg.mkPen('#44AAFF', width=1.5)
        FILT_PEN  = pg.mkPen('#FFDD44', width=1)

        # Shaded valid-lag region
        self._lag_region = pg.LinearRegionItem(
            values=[HR2TestCalc.FW_MIN_LAG_S, 60.0 / HR2TestCalc.FW_HR_SEARCH_MIN],
            brush=pg.mkBrush(0, 200, 100, 20), movable=False)
        self.p_acorr.addItem(self._lag_region)
        # Min-corr threshold line
        self._min_corr_line = pg.InfiniteLine(
            angle=0, pos=HR2TestCalc.FW_MIN_CORR, movable=False,
            pen=pg.mkPen('#FF3333', width=1, style=QtCore.Qt.DashLine),
            label='min_corr', labelOpts={'color': '#FF3333', 'position': 0.95})
        self.p_acorr.addItem(self._min_corr_line)
        self.curve_acorr = self.p_acorr.plot(pen=ACORR_PEN, name="acorr")
        self.curve_acorr.setDownsampling(auto=True, method='peak')
        self.curve_acorr.setClipToView(True)
        self._peak_line  = pg.InfiniteLine(
            angle=90, pos=0, movable=False,
            pen=pg.mkPen('#00FF88', width=2),
            label='peak', labelOpts={'color': '#00FF88', 'position': 0.92})
        self.p_acorr.addItem(self._peak_line)

        self.curve_filt   = self.p_filt.plot(pen=FILT_PEN)
        self.curve_filt.setDownsampling(auto=True, method='peak')
        self.curve_filt.setClipToView(True)
        self.p_hr.addLegend()
        self.curve_hr_fw  = self.p_hr.plot(pen=FW_PEN,  name="HR2 fw")
        self.curve_hr_py  = self.p_hr.plot(pen=PY_PEN,  name="HR2 py")
        self._zero_delta  = pg.InfiniteLine(
            angle=0, pos=0, movable=False,
            pen=pg.mkPen('#555555', width=1, style=QtCore.Qt.DashLine))
        self.p_sqi.addLegend()
        self.curve_sqi_fw = self.p_sqi.plot(pen=FW_PEN,  name="SQI fw")
        self.curve_sqi_py = self.p_sqi.plot(pen=PY_PEN,  name="SQI py")

        # ── Right: parameters + table ─────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #1A1A1A;")
        splitter.addWidget(right)
        splitter.setSizes([900, 320])

        right_vbox = QtWidgets.QVBoxLayout(right)
        right_vbox.setContentsMargins(10, 10, 10, 10)
        right_vbox.setSpacing(10)

        grp_params = QtWidgets.QGroupBox("Algorithm parameters")
        grp_params.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        form = QtWidgets.QFormLayout(grp_params)
        form.setSpacing(6)
        _sp_s = "background-color: #2A2A2A; color: #FFDD44; padding: 3px; font-size: 18px;"
        _lbl_s = "color: #CCCCCC; font-size: 18px;"

        def _dspin(lo, hi, val, dec, step, suffix=""):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi); w.setDecimals(dec); w.setSingleStep(step)
            w.setValue(val); w.setStyleSheet(_sp_s)
            if suffix: w.setSuffix(suffix)
            return w

        def _ispin(lo, hi, val):
            w = QtWidgets.QSpinBox()
            w.setRange(lo, hi); w.setValue(val); w.setStyleSheet(_sp_s)
            return w

        self._spin_bpf_lo  = _dspin(0.01, 10.0, HR2TestCalc.FW_BPF_LOW_HZ,  2, 0.05, " Hz")
        self._spin_bpf_hi  = _dspin(0.1,  25.0, HR2TestCalc.FW_BPF_HIGH_HZ, 1, 0.5,  " Hz")
        self._spin_buf_len = _ispin(50,    800,  HR2TestCalc.FW_BUF_LEN)
        self._spin_max_lag = _ispin(10,    400,  HR2TestCalc.FW_MAX_LAG)
        self._spin_upd_n   = _ispin(1,     200,  HR2TestCalc.FW_UPDATE_N)
        self._spin_min_lag = _dspin(0.05, 1.0,  HR2TestCalc.FW_MIN_LAG_S,   3, 0.005, " s")
        self._spin_min_cor = _dspin(0.0,  1.0,  HR2TestCalc.FW_MIN_CORR,    2, 0.05)

        self._spin_bpf_lo.setToolTip(_make_tooltip("BPF low cutoff",
            "Bandpass filter lower cutoff [Hz]. Firmware default: 0.5 Hz.",
            src="hr2_bpf_low_hz"))
        self._spin_bpf_hi.setToolTip(_make_tooltip("BPF high cutoff",
            "Bandpass filter upper cutoff [Hz]. Firmware default: 5.0 Hz.",
            src="hr2_bpf_high_hz"))
        self._spin_buf_len.setToolTip(_make_tooltip("Buffer length",
            "Circular buffer length [samples]. Firmware default: 400 (8 s at 50 Hz).",
            src="hr2_buf_len"))
        self._spin_max_lag.setToolTip(_make_tooltip("Max lag",
            "Maximum autocorrelation lag to compute [samples]. "
            "Firmware default: 137 (≈22 BPM guard band at 50 Hz: 50×60/22=136.4).",
            src="hr2_max_lag"))
        self._spin_upd_n.setToolTip(_make_tooltip("Update interval",
            "Recompute autocorrelation every N samples. Firmware default: 25 (0.5 s at 50 Hz).",
            src="hr2_update_n"))
        self._spin_min_lag.setToolTip(_make_tooltip("Min lag",
            "Minimum lag to search [s]. Firmware default: 0.185 s (~303 BPM guard band).",
            src="hr2_min_lag_s"))
        self._spin_min_cor.setToolTip(_make_tooltip("Min correlation",
            "Minimum normalised autocorrelation at peak to be considered valid. "
            "Firmware default: 0.5. Also shown as a red dashed line on the autocorrelation plot.",
            src="hr2_min_corr"))

        def _lbl(t):
            w = QtWidgets.QLabel(t); w.setStyleSheet(_lbl_s); return w

        form.addRow(_lbl("BPF low"),    self._spin_bpf_lo)
        form.addRow(_lbl("BPF high"),   self._spin_bpf_hi)
        form.addRow(_lbl("Buf len"),    self._spin_buf_len)
        form.addRow(_lbl("Max lag"),    self._spin_max_lag)
        form.addRow(_lbl("Update N"),   self._spin_upd_n)
        form.addRow(_lbl("Min lag"),    self._spin_min_lag)
        form.addRow(_lbl("Min corr"),   self._spin_min_cor)
        right_vbox.addWidget(grp_params)

        btn_reset = QtWidgets.QPushButton("RESET TO DEFAULTS")
        btn_reset.setStyleSheet(ACTION_BUTTON_STYLE)
        btn_reset.clicked.connect(self._reset_to_defaults)
        btn_reset.setToolTip(_make_tooltip("RESET TO DEFAULTS",
            "Restore all parameters to firmware defaults and reset mirror state."))
        right_vbox.addWidget(btn_reset)

        grp_vals = QtWidgets.QGroupBox("Current values")
        grp_vals.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        vals_vbox = QtWidgets.QVBoxLayout(grp_vals)
        self._val_table = QtWidgets.QTableWidget(3, 4)
        self._val_table.setHorizontalHeaderLabels(["Signal", "Firmware", "Python", "Delta"])
        self._val_table.verticalHeader().setVisible(False)
        self._val_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._val_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._val_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self._val_table.setStyleSheet(
            "QTableWidget { background-color: #1A1A1A; color: #E0E0E0; "
            "gridline-color: #333333; font-size: 17px; border: none; } "
            "QHeaderView::section { background-color: #2A2A2A; color: #AAAAAA; "
            "font-weight: bold; font-size: 17px; padding: 3px; }")
        for r, name in enumerate(["HR2 (bpm)", "SQI", "Peak lag (s)"]):
            item = QtWidgets.QTableWidgetItem(name)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            self._val_table.setItem(r, 0, item)
            for c in range(1, 4):
                self._val_table.setItem(r, c, QtWidgets.QTableWidgetItem("---"))
        self._val_table.horizontalHeader().setStretchLastSection(True)
        self._val_table.resizeColumnsToContents()
        vals_vbox.addWidget(self._val_table)
        right_vbox.addWidget(grp_vals)

        right_vbox.addStretch()

        for sp in [self._spin_bpf_lo, self._spin_bpf_hi, self._spin_min_lag, self._spin_min_cor]:
            sp.valueChanged.connect(self._on_param_changed)
        for sp in [self._spin_buf_len, self._spin_max_lag, self._spin_upd_n]:
            sp.valueChanged.connect(self._on_param_changed)

        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("HR2TestWindow/geometry")
        if geom: self.restoreGeometry(geom)

    # ── Parameter handling ────────────────────────────────────────────────────

    def _on_param_changed(self):
        self._calc.bpf_low_hz  = self._spin_bpf_lo.value()
        self._calc.bpf_high_hz = self._spin_bpf_hi.value()
        self._calc.buf_len     = self._spin_buf_len.value()
        self._calc.max_lag     = self._spin_max_lag.value()
        self._calc.update_n    = self._spin_upd_n.value()
        self._calc.min_lag_s   = self._spin_min_lag.value()
        self._calc.min_corr    = self._spin_min_cor.value()
        self._calc.reset()
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        # Update min_corr line
        self._min_corr_line.setValue(self._calc.min_corr)
        self._update_status_indicator()

    def _reset_to_defaults(self):
        for sp, attr in [
            (self._spin_bpf_lo,  'FW_BPF_LOW_HZ'),
            (self._spin_bpf_hi,  'FW_BPF_HIGH_HZ'),
            (self._spin_buf_len, 'FW_BUF_LEN'),
            (self._spin_max_lag, 'FW_MAX_LAG'),
            (self._spin_upd_n,   'FW_UPDATE_N'),
            (self._spin_min_lag, 'FW_MIN_LAG_S'),
            (self._spin_min_cor, 'FW_MIN_CORR'),
        ]:
            sp.blockSignals(True)
            sp.setValue(getattr(HR2TestCalc, attr))
            sp.blockSignals(False)
        self._calc.reset_to_defaults()
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self._min_corr_line.setValue(HR2TestCalc.FW_MIN_CORR)
        self._update_status_indicator()

    def _update_status_indicator(self):
        if self._calc.using_defaults:
            self._lbl_status.setText("● FIRMWARE DEFAULTS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
                "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        else:
            self._lbl_status.setText("● CUSTOM PARAMS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FFAA00; padding: 4px 10px; "
                "background: #2A1A00; border: 1px solid #AA7700; border-radius: 4px;")

    # ── Offline mode ──────────────────────────────────────────────────────────

    def _load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self._process_csv_offline(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Load CSV error", str(e))

    def _process_csv_offline(self, path):
        import csv as _csv
        rows_led1_sub = []
        rows_hr_fw  = []
        rows_sqi_fw = []
        rows_ts_us  = []
        with open(path, 'r', newline='') as f:
            header = f.readline().strip()
            is_chk = header.startswith("Timestamp_PC,Diff_us_PC,CHK_OK")
            reader = _csv.reader(f)
            for row in reader:
                if not row:
                    continue
                try:
                    if is_chk:
                        if len(row) < 4 or row[2].strip() != '1':
                            continue
                        raw = row[3].strip()
                        if '*' in raw:
                            raw = raw[:raw.rfind('*')]
                        parts = raw.split(',')
                        if len(parts) < 20 or parts[0] not in ('$M1', '$M3'):
                            continue
                        ts_us  = float(parts[2])
                        led1_sub = float(parts[8])
                        hr_fw  = float(parts[16])
                        sqi_fw = float(parts[17])
                    else:
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', 'M3', '$M1', '$M3'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        led1_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 14])
                        sqi_fw = float(row[offset + 15])
                    rows_ts_us.append(ts_us)
                    rows_led1_sub.append(led1_sub)
                    rows_hr_fw.append(hr_fw if hr_fw > 0 else float('nan'))
                    rows_sqi_fw.append(sqi_fw if sqi_fw >= 0 else float('nan'))
                except (ValueError, IndexError):
                    continue

        if not rows_ts_us:
            raise ValueError("No valid M1 samples found.")

        ts_arr = np.array(rows_ts_us)
        diffs = np.diff(ts_arr); diffs = diffs[diffs > 0]
        fs = float(1e6 / np.median(diffs)) if len(diffs) else 50.0
        for std_fs in [500, 250, 100, 50, 25]:
            if abs(fs - std_fs) < std_fs * 0.2:
                fs = float(std_fs); break

        self._calc.reset_to_defaults()
        self._calc.bpf_low_hz  = self._spin_bpf_lo.value()
        self._calc.bpf_high_hz = self._spin_bpf_hi.value()
        self._calc.buf_len     = self._spin_buf_len.value()
        self._calc.max_lag     = self._spin_max_lag.value()
        self._calc.update_n    = self._spin_upd_n.value()
        self._calc.min_lag_s   = self._spin_min_lag.value()
        self._calc.min_corr    = self._spin_min_cor.value()
        self._calc.reset()

        nan = float('nan')
        n = len(rows_led1_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_led1_sub):
            self._calc.update(ir, fs)
            if self._calc.hr_bpm > 0:
                arr_hr_py[i]  = self._calc.hr_bpm
                arr_sqi_py[i] = self._calc.hr_sqi

        arr_delta = arr_hr_fw - arr_hr_py

        self._offline_mode = True
        self._btn_clear.setEnabled(True)
        fname = path.split('/')[-1].split('\\')[-1]
        self.statusBar().showMessage(f"OFFLINE — {fname}  ({n} samples, fs≈{fs:.0f} Hz)")

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sqi_fw, arr_sqi_py)
        self._refresh_acorr_plot()
        self._refresh_filt_plot(arr_t)
        self._update_status_indicator()

    def _clear_offline(self):
        self._offline_mode = False
        self._btn_clear.setEnabled(False)
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self._calc.reset()
        self.statusBar().showMessage(_MOUSE_HINT)
        for c in [self.curve_acorr, self.curve_filt,
                  self.curve_hr_fw, self.curve_hr_py,
                  self.curve_sqi_fw, self.curve_sqi_py]:
            c.setData([], [])

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        t = np.array(self._buf_t)
        if len(t) == 0:
            QtWidgets.QMessageBox.information(self, "Export", "No data to export.")
            return
        now_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(CAPTURES_DIR, f"hr2test_{now_str}.csv")
        hr_fw = np.array(self._buf_hr_fw); hr_py = np.array(self._buf_hr_py)
        sqi_fw = np.array(self._buf_sqi_fw); sqi_py = np.array(self._buf_sqi_py)
        try:
            with open(filename, 'w') as f:
                f.write(f"# HR2TEST export — {datetime.datetime.now()}\n")
                f.write(f"# bpf=[{self._calc.bpf_low_hz:.2f},{self._calc.bpf_high_hz:.1f}]Hz, "
                        f"buf={self._calc.buf_len}, max_lag={self._calc.max_lag}, "
                        f"min_corr={self._calc.min_corr:.2f}\n")
                f.write("t_s,hr2_fw,hr2_py,hr2_delta,sqi_fw,sqi_py\n")
                nan = float('nan')
                for i in range(len(t)):
                    def _fv(arr, i): v = arr[i] if i < len(arr) else nan; return f"{v:.2f}" if not np.isnan(v) else ""
                    delta = hr_fw[i] - hr_py[i] if i < len(hr_fw) and i < len(hr_py) else nan
                    f.write(f"{t[i]:.3f},{_fv(hr_fw,i)},{_fv(hr_py,i)},"
                            f"{'%.2f'%delta if not np.isnan(delta) else ''},"
                            f"{_fv(sqi_fw,i)},{_fv(sqi_py,i)}\n")
            self.statusBar().showMessage(f"Exported: {filename}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export error", str(e))

    # ── Live update ───────────────────────────────────────────────────────────

    def update_algorithms(self, data_led1_sub, data_hr2, data_hr2_sqi,
                          data_timestamp_us, data_sample_counter):
        """Run per-sample algorithm (called from PPGMonitor._process_frames_tick)."""
        if self._offline_mode:
            return
        n = len(data_sample_counter)
        if n == 0:
            return

        new_indices = []
        for i in range(n - 1, -1, -1):
            if data_sample_counter[i] <= self._last_sample_cnt:
                break
            new_indices.append(i)
        if not new_indices:
            return
        new_indices.reverse()

        # Gap detection: check for missing samples in new batch
        _counters = [int(data_sample_counter[i]) for i in new_indices]
        if self._nominal_step is None and len(_counters) >= 2:
            self._nominal_step = _counters[1] - _counters[0]
        if self._last_sample_cnt > 0 and self._nominal_step is not None:
            _gap = _counters[0] - self._last_sample_cnt - self._nominal_step
            if _gap > 0:
                self.gap_count += _gap
        if self._nominal_step is not None:
            for _j in range(len(_counters) - 1):
                _step = _counters[_j + 1] - _counters[_j]
                if _step > self._nominal_step:
                    self.gap_count += _step - self._nominal_step

        nan = float('nan')
        for i in new_indices:
            ts    = float(data_timestamp_us[i])
            ir    = float(data_led1_sub[i])
            hr_f  = float(data_hr2[i])
            sqi_f = float(data_hr2_sqi[i])
            if self._t0_us is None:
                self._t0_us = ts
            t_s = (ts - self._t0_us) / 1e6

            self._calc.update(ir, SPO2_RECEIVED_FS)

            hr_fw  = hr_f  if hr_f  > 0 else nan
            sqi_fw = sqi_f if sqi_f >= 0 else nan
            hr_py  = self._calc.hr_bpm if self._calc.hr_bpm > 0 else nan
            sqi_py = self._calc.hr_sqi if self._calc.hr_bpm > 0 else nan
            delta  = (hr_fw - hr_py) if not (np.isnan(hr_fw) or np.isnan(hr_py)) else nan

            self._buf_t.append(t_s)
            self._buf_hr_fw.append(hr_fw)
            self._buf_hr_py.append(hr_py)
            self._buf_hr_delta.append(delta)
            self._buf_sqi_fw.append(sqi_fw)
            self._buf_sqi_py.append(sqi_py)

        self._last_sample_cnt = data_sample_counter[-1]

    def update_plots(self):
        """Render pre-computed buffers (called from PPGMonitor._refresh_plots_tick)."""
        if self._offline_mode:
            return
        if not self._buf_t:
            return

        arr_t = np.array(self._buf_t)
        arr_hr_fw = np.array(self._buf_hr_fw); arr_hr_py = np.array(self._buf_hr_py)
        arr_delta = np.array(self._buf_hr_delta)
        arr_sf    = np.array(self._buf_sqi_fw); arr_sp = np.array(self._buf_sqi_py)

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sf, arr_sp)
        self._refresh_acorr_plot()
        self._refresh_filt_plot(arr_t)

        # Value table
        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        fw_v = [_lv(arr_hr_fw), _lv(arr_sf), float('nan')]
        py_v = [_lv(arr_hr_py), _lv(arr_sp), self._calc.last_peak_lag_s]
        dec  = [1, 3, 4]
        for row in range(3):
            fv = fw_v[row]; pv = py_v[row]
            dv = (fv - pv) if not (np.isnan(fv) or np.isnan(pv)) else float('nan')
            self._val_table.item(row, 1).setText(_fmt(fv, dec[row]))
            self._val_table.item(row, 2).setText(_fmt(pv, dec[row]))
            self._val_table.item(row, 3).setText(_fmt(dv, dec[row]))
            if not np.isnan(dv) and row == 0:
                color = QtGui.QColor("#00CC66") if abs(dv) < 3.0 else QtGui.QColor("#FF4444")
                self._val_table.item(row, 3).setForeground(color)

        self._update_status_indicator()

    def _refresh_hr_plots(self, t, hr_fw, hr_py, delta, sqi_fw, sqi_py):
        self.curve_hr_fw.setData(t, hr_fw)
        self.curve_hr_py.setData(t, hr_py)
        self.curve_sqi_fw.setData(t, sqi_fw)
        self.curve_sqi_py.setData(t, sqi_py)
        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        v_fw = _lv(hr_fw); v_py = _lv(hr_py); v_d = _lv(delta)
        self.p_hr.setTitle(
            f"<b style='color:#00CC66'>HR2 fw: {_fmt(v_fw)} bpm</b>"
            f"  <b style='color:#FFDD44'>py: {_fmt(v_py)} bpm</b>"
            f"  <span style='color:#FF6666'>Δ={_fmt(v_d)}</span>")

    def _refresh_acorr_plot(self):
        acorr = self._calc.last_acorr
        lags  = self._calc.last_lags_s
        if len(acorr) > 0 and len(lags) > 0:
            self.curve_acorr.setData(lags, acorr)
            peak = self._calc.last_peak_lag_s
            if peak > 0:
                self._peak_line.setValue(peak)
                hr_at_peak = 60.0 / peak if peak > 0 else 0.0
                sqi_at_peak = self._calc.hr_sqi
                self.p_acorr.setTitle(
                    f"<b style='color:#44AAFF'>Autocorrelation</b>"
                    f"  <span style='color:#00FF88'>peak={peak:.3f} s → {hr_at_peak:.1f} bpm"
                    f"  SQI={sqi_at_peak:.3f}</span>")

    def _refresh_filt_plot(self, t_hr):
        filt = self._calc.last_filtered
        if len(filt) > 0 and len(t_hr) > 0:
            t_end = t_hr[-1]
            fs = self._calc._fs if self._calc._fs > 0 else HR2TestCalc.FW_FS
            filt_t = t_end - (len(filt) - 1 - np.arange(len(filt))) / fs
            self.curve_filt.setData(filt_t, filt)

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("HR2TestWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hr2test.setChecked(False)
            self.main_monitor.hr2test_window = None
        super().closeEvent(event)


class HR3TestCalc:
    """HR3 algorithm mirror for HR3TEST window.

    Independent reimplementation of firmware _update_hr3() from incunest_afe4490_spec.md §5.4.
    Purpose: post-implementation verification.

    Processing chain per sample (at 50 Hz after firmware decimation):
      LED1_SUB → 2nd-order Butterworth BP 0.4–15 Hz → circular buffer 512 samples →
      [every 25 samples] mean subtraction → Hann window → rfft →
      HPS: P[k]·P[2k]·P[3k] → argmax in HR range → parabolic interpolation
      → HR3 = peak_freq × 60

    SQI (two-bin HPS local SNR, spec §5.4):
      b1       = floor(peak_bin + delta)   (delta from parabolic interpolation)
      b2       = b1 + 1
      hps_num  = hps[b1] + hps[b2]
      hps_win  = Σ hps[k]  for k in [b1−W .. b2+W]  (W = FW_SNR_LOCAL_W)
      snr      = hps_num / hps_win
      baseline = 2 / n_win
      SQI      = clamp((snr − baseline) / (1 − baseline), 0, 1)

    Diagnostic state exposed for HR3TestWindow:
      last_spectrum      — FFT magnitude normalised to HR-band max
      last_freqs         — frequency axis (Hz)
      last_hps           — HPS curve normalised to HR-band max
      last_peak_freq     — detected peak frequency (Hz)
      last_filtered_buf  — LP filtered circular buffer (ordered oldest→newest)
    """

    FW_FS            = 50.0
    FW_BP_LOW_HZ     = 0.4
    FW_BP_HIGH_HZ    = 15.0
    FW_BUF_LEN       = 512
    FW_UPDATE_N      = 25
    FW_HPS_HARMONICS = 3        # k = 2, 3  (multiply 2 additional harmonic downsamples)
    FW_HR_MIN_BPM    = 40.0
    FW_HR_MAX_BPM    = 260.0
    FW_HR_SEARCH_MIN = 37.0     # guard band −3 BPM
    FW_HR_SEARCH_MAX = 263.0    # guard band +3 BPM
    FW_SNR_LOCAL_W   = 5        # SQI local window half-width W [bins] on each side of {b1, b2}

    def __init__(self):
        self.bp_low_hz     = self.FW_BP_LOW_HZ
        self.bp_high_hz    = self.FW_BP_HIGH_HZ
        self.buf_len       = self.FW_BUF_LEN
        self.update_n      = self.FW_UPDATE_N
        self.hps_harmonics = self.FW_HPS_HARMONICS
        self._fs           = 0.0
        self._b            = None
        self._a            = None
        self._zi           = None
        self._buf          = np.zeros(self.FW_BUF_LEN)
        self._buf_idx      = 0
        self._buf_count    = 0
        self._update_ctr   = 0
        self.hr_bpm        = 0.0
        self.hr_sqi        = 0.0
        n_fft = self.FW_BUF_LEN // 2 + 1
        self.last_spectrum     = np.zeros(n_fft)
        self.last_freqs        = np.zeros(n_fft)
        self.last_hps          = np.zeros(n_fft)
        self.last_peak_freq    = 0.0
        self.last_filtered_buf = np.zeros(self.FW_BUF_LEN)
        # Gap detection (data_sample_counter continuity — Punto C, post-decimation)
        self._last_counter = None
        self._nominal_step = None
        self.gap_count     = 0

    def reset(self):
        self._fs        = 0.0
        self._zi        = None
        self._buf[:]    = 0.0
        self._buf_idx   = 0
        self._buf_count = 0
        self._update_ctr = 0
        self.hr_bpm     = 0.0
        self.hr_sqi     = 0.0
        self.last_spectrum[:]  = 0.0
        self.last_hps[:]       = 0.0
        self.last_peak_freq    = 0.0

    def reset_to_defaults(self):
        self.bp_low_hz     = self.FW_BP_LOW_HZ
        self.bp_high_hz    = self.FW_BP_HIGH_HZ
        self.buf_len       = self.FW_BUF_LEN
        self.update_n      = self.FW_UPDATE_N
        self.hps_harmonics = self.FW_HPS_HARMONICS
        self.reset()

    @property
    def using_defaults(self):
        return (
            self.bp_low_hz     == self.FW_BP_LOW_HZ     and
            self.bp_high_hz    == self.FW_BP_HIGH_HZ    and
            self.buf_len       == self.FW_BUF_LEN       and
            self.update_n      == self.FW_UPDATE_N      and
            self.hps_harmonics == self.FW_HPS_HARMONICS
        )

    def _recalc_filter(self, fs):
        self._fs = fs
        nyq = fs / 2.0
        self._b, self._a = signal.butter(2, [self.bp_low_hz / nyq, min(self.bp_high_hz / nyq, 0.9999)], btype='band')
        self._zi = signal.lfilter_zi(self._b, self._a) * 0.0
        self._buf = np.zeros(self.buf_len)
        self._buf_idx    = 0
        self._buf_count  = 0
        self._update_ctr = 0
        n_fft = self.buf_len // 2 + 1
        self.last_spectrum     = np.zeros(n_fft)
        self.last_freqs        = np.zeros(n_fft)
        self.last_hps          = np.zeros(n_fft)
        self.last_filtered_buf = np.zeros(self.buf_len)
        self.hr_bpm = 0.0
        self.hr_sqi = 0.0

    def update(self, led1_sub, fs, sample_counter=None):
        """Process one sample at the given fs. Returns (hr_bpm, hr_sqi)."""
        if fs != self._fs or self._b is None:
            self._recalc_filter(fs)
        if sample_counter is not None:
            if self._last_counter is not None:
                step = sample_counter - self._last_counter
                if self._nominal_step is None:
                    self._nominal_step = step
                elif step > self._nominal_step:
                    self.gap_count += step - self._nominal_step
            self._last_counter = sample_counter

        # BP filter
        filtered, self._zi = signal.lfilter(self._b, self._a, [float(led1_sub)], zi=self._zi)
        filtered = filtered[0]

        # Circular buffer
        self._buf[self._buf_idx] = filtered
        self._buf_idx = (self._buf_idx + 1) % self.buf_len
        if self._buf_count < self.buf_len:
            self._buf_count += 1

        # Always update display buffer (cheap: just reorder the circular buffer)
        self.last_filtered_buf = np.roll(self._buf, -self._buf_idx)

        self._update_ctr += 1
        if self._update_ctr < self.update_n:
            return self.hr_bpm, self.hr_sqi
        self._update_ctr = 0

        if self._buf_count < self.buf_len:
            return self.hr_bpm, self.hr_sqi

        # Ordered buffer (oldest first) — reuse display buffer already computed above
        seg_raw = self.last_filtered_buf

        # Mean subtraction → Hann window → rfft
        seg      = seg_raw - seg_raw.mean()
        seg      = seg * np.hanning(self.buf_len)
        fft_cplx = np.fft.rfft(seg)
        spectrum = np.abs(fft_cplx)
        freqs    = np.fft.rfftfreq(self.buf_len, d=1.0 / fs)

        # HPS: P[k] · P[2k] · P[3k] · ... (hps_harmonics controls highest harmonic index)
        n_spec = len(spectrum)
        hps    = spectrum.copy()
        for k in range(2, self.hps_harmonics + 1):
            n_valid       = n_spec // k
            hps[:n_valid] *= spectrum[np.arange(n_valid) * k]
            hps[n_valid:]  = 0.0

        # Search range
        search_min_hz = self.FW_HR_SEARCH_MIN / 60.0
        search_max_hz = self.FW_HR_SEARCH_MAX / 60.0
        mask = (freqs >= search_min_hz) & (freqs <= search_max_hz)
        if not np.any(mask):
            return self.hr_bpm, self.hr_sqi

        hps_hr      = hps[mask]
        n_bins      = int(np.sum(mask))
        idx_offset  = int(np.where(mask)[0][0])
        peak_local  = int(np.argmax(hps_hr))
        peak_global = idx_offset + peak_local

        # Gaussian interpolation: parabolic fit on log|X|² (accurate for Hann window).
        # Jacobsen (complex) gives δ ≈ -0.5·δ_true for Hann: adjacent bins carry
        # phase e^{±jπ}=-1, inverting the numerator sign.  Gaussian gives δ ≈ 1.07·δ_true.
        if 0 < peak_global < len(fft_cplx) - 1:
            pm = abs(fft_cplx[peak_global - 1])**2
            pc = abs(fft_cplx[peak_global    ])**2
            pp = abs(fft_cplx[peak_global + 1])**2
            lm, lc, lp = np.log(max(pm, 1e-30)), np.log(max(pc, 1e-30)), np.log(max(pp, 1e-30))
            denom = lm - 2.0*lc + lp
            delta = 0.5*(lm - lp) / denom if denom != 0.0 else 0.0
        else:
            delta = 0.0
        freq_res  = fs / self.buf_len
        peak_freq = freqs[peak_global] + delta * freq_res
        hr_bpm    = peak_freq * 60.0

        # SQI: two-bin HPS local SNR (mirrors firmware §5.4)
        spec_hr  = spectrum[mask]
        nyquist  = len(hps) - 1
        b1       = int(np.floor(peak_global + delta))
        b2       = b1 + 1
        b1       = max(1, b1)
        b2       = min(nyquist // 3, b2)
        hps_b1   = float(hps[b1])
        hps_b2   = float(hps[b2])
        hps_num  = hps_b1 + hps_b2
        W_sqi    = self.FW_SNR_LOCAL_W
        hps_win  = 0.0
        n_win    = 0
        for k in range(b1 - W_sqi, b2 + W_sqi + 1):
            if k < 1 or k > nyquist // 3:
                continue
            hps_win += float(hps[k])
            n_win   += 1
        if hps_win > 0.0 and n_win > 2:
            snr      = hps_num / hps_win
            baseline = 2.0 / n_win
            sqi = max(0.0, min(1.0, (snr - baseline) / (1.0 - baseline))) if baseline < 1.0 else 0.0
        else:
            sqi = 0.0

        # Normalise for display
        hps_max  = float(np.max(hps_hr))  if np.max(hps_hr)  > 0.0 else 1.0
        spec_max = float(np.max(spec_hr)) if np.max(spec_hr) > 0.0 else 1.0
        self.last_spectrum  = spectrum / spec_max
        self.last_freqs     = freqs
        self.last_hps       = hps / hps_max
        self.last_peak_freq = peak_freq

        if (self.FW_HR_MIN_BPM / 60.0) <= peak_freq <= (self.FW_HR_MAX_BPM / 60.0):
            self.hr_bpm = hr_bpm
            self.hr_sqi = sqi
        else:
            self.hr_sqi = 0.0

        return self.hr_bpm, self.hr_sqi


# ──────────────────────────────────────────────────────────────────────────────
#  PICalc — configurable 3-step Perfusion Index pipeline
# ──────────────────────────────────────────────────────────────────────────────

class PICalc:
    """Configurable 3-step Perfusion Index pipeline.

    Pipeline: STEP1 (AC extraction) → STEP2 (AC estimator) → STEP3 (DC for denominator)

    STEP1 — AC extraction:
      S1_EMA  (1.1): EMA-based subtraction (τ_sub seconds)
      S1_BPF  (1.2): 2nd-order Butterworth bandpass (bpf_lo–bpf_hi Hz)
      S1_NONE (1.3): pass-through (only valid with spectral STEP2 2.4/2.5)

    STEP2 — AC estimator:
      S2_EMA_RMS   (2.1): running RMS via EMA of x² — firmware M1 method
      S2_WIN_RMS   (2.2): windowed RMS (win_s seconds)
      S2_PEAKPK    (2.3): peak-to-peak / 2 over win_s seconds
      S2_SPECTRAL  (2.4): FFT energy in band [f_HR ± delta_hz]
      S2_HARMONICS (2.5): FFT energy sum at n·f_HR harmonics

    STEP3 — DC for PI denominator:
      S3_EMA      (3.1): EMA of raw signal — firmware M1 method (τ_norm seconds)
      S3_LPF      (3.2): 2nd-order Butterworth LPF (lpf_fc Hz)
      S3_WIN_MEAN (3.3): windowed mean (win_norm_s seconds)
    """

    S1_EMA = "1.1"; S1_BPF = "1.2"; S1_NONE = "1.3"
    S2_EMA_RMS = "2.1"; S2_WIN_RMS = "2.2"; S2_PEAKPK = "2.3"
    S2_SPECTRAL = "2.4"; S2_HARMONICS = "2.5"
    S3_EMA = "3.1"; S3_LPF = "3.2"; S3_WIN_MEAN = "3.3"

    # SpO2 calibration defaults (mirror firmware incunest_afe4490 defaults)
    DEFAULT_SPO2_A = 114.9208
    DEFAULT_SPO2_B =  30.5547

    def __init__(self):
        # STEP1
        self.step1      = self.S1_EMA
        self.tau_sub    = 2.0   # S1_EMA τ (s)
        self.bpf_lo     = 0.5   # S1_BPF lo cutoff (Hz)
        self.bpf_hi     = 4.0   # S1_BPF hi cutoff (Hz)
        # STEP2
        self.step2       = self.S2_EMA_RMS
        self.tau_ac      = 6.0   # S2_EMA_RMS τ (s)
        self.win_s       = 4.0   # S2_WIN_RMS / S2_PEAKPK / spectral window (s)
        self.fft_len     = 512   # S2_SPECTRAL / S2_HARMONICS FFT length (samples)
        self.hr_bpm      = 70.0  # nominal HR for spectral methods (bpm)
        self.n_harmonics = 3     # number of harmonics for S2_HARMONICS
        self.delta_hz    = 0.3   # spectral bin half-width around each harmonic (Hz)
        # STEP3
        self.step3      = self.S3_EMA
        self.tau_norm   = 2.0   # S3_EMA τ (s)
        self.lpf_fc     = 0.4   # S3_LPF cutoff (Hz)
        self.win_norm_s = 4.0   # S3_WIN_MEAN window (s)

        # internal state
        self._fs = 0.0
        self._alpha_sub = 0.0; self._alpha_ac = 0.0; self._alpha_norm = 0.0
        self._ema_dc_ir    = 0.0; self._ema_dc_red    = 0.0
        self._ema_ac2_ir   = 0.0; self._ema_ac2_red   = 0.0
        self._ema_dc_r_ir  = 0.0; self._ema_dc_r_red  = 0.0
        self._win_buf_ir   = deque(); self._win_buf_red  = deque()
        self._raw_ir_buf   = deque(); self._raw_red_buf  = deque()
        self._norm_buf_ir  = deque(); self._norm_buf_red = deque()
        self._bpf_sos = None; self._bpf_zi_ir = None; self._bpf_zi_red = None
        self._lpf_sos = None; self._lpf_zi_ir = None; self._lpf_zi_red = None
        self._win_max_n = 200; self._norm_max_n = 200

        # SpO2 calibration (synced from firmware $CFG at runtime)
        self.spo2_a = self.DEFAULT_SPO2_A
        self.spo2_b = self.DEFAULT_SPO2_B

        # outputs
        self.pi_ir    = 0.0; self.pi_red   = 0.0; self.R = 0.0; self.spo2 = 0.0
        self.ac_r_ir  = 0.0; self.ac_r_red = 0.0
        self.dc_r_ir  = 1.0; self.dc_r_red = 1.0
        self.dc_sub_ir = 0.0; self.dc_sub_red = 0.0
        self.ac_t_ir   = 0.0; self.ac_t_red   = 0.0  # STEP1 pulsatile waveform output

    def reset(self):
        """Reset all accumulators (keeps configuration)."""
        self._ema_dc_ir   = 0.0; self._ema_dc_red   = 0.0
        self._ema_ac2_ir  = 0.0; self._ema_ac2_red  = 0.0
        self._ema_dc_r_ir = 0.0; self._ema_dc_r_red = 0.0
        self._win_buf_ir.clear(); self._win_buf_red.clear()
        self._raw_ir_buf.clear(); self._raw_red_buf.clear()
        self._norm_buf_ir.clear(); self._norm_buf_red.clear()
        self._bpf_zi_ir = None; self._bpf_zi_red = None
        self._lpf_zi_ir = None; self._lpf_zi_red = None
        self.pi_ir    = 0.0; self.pi_red   = 0.0; self.R = 0.0; self.spo2 = 0.0
        self.ac_r_ir  = 0.0; self.ac_r_red = 0.0
        self.dc_r_ir  = 1.0; self.dc_r_red = 1.0
        self.dc_sub_ir = 0.0; self.dc_sub_red = 0.0
        self.ac_t_ir   = 0.0; self.ac_t_red   = 0.0

    def reconfigure(self, fs):
        """Recalculate derived params from current settings and reset state."""
        self._fs = fs
        if fs <= 0:
            return
        a_sub  = 1.0 - math.exp(-1.0 / (max(self.tau_sub,  1.0 / fs) * fs))
        a_ac   = 1.0 - math.exp(-1.0 / (max(self.tau_ac,   1.0 / fs) * fs))
        a_norm = 1.0 - math.exp(-1.0 / (max(self.tau_norm, 1.0 / fs) * fs))
        self._alpha_sub  = a_sub
        self._alpha_ac   = a_ac
        self._alpha_norm = a_norm
        nyq = fs / 2.0
        # BPF (S1_BPF)
        if self.step1 == self.S1_BPF:
            lo = max(0.01, min(self.bpf_lo, nyq * 0.9))
            hi = max(lo + 0.01, min(self.bpf_hi, nyq * 0.99))
            try:
                self._bpf_sos = signal.butter(2, [lo / nyq, hi / nyq], btype='bandpass', output='sos')
            except Exception:
                self._bpf_sos = None
        else:
            self._bpf_sos = None
        # LPF (S3_LPF)
        if self.step3 == self.S3_LPF:
            fc = max(0.01, min(self.lpf_fc, nyq * 0.99))
            try:
                self._lpf_sos = signal.butter(2, fc / nyq, btype='low', output='sos')
            except Exception:
                self._lpf_sos = None
        else:
            self._lpf_sos = None
        self._win_max_n  = max(2, int(round(self.win_s      * fs)))
        self._norm_max_n = max(2, int(round(self.win_norm_s * fs)))
        self.reset()

    def update(self, ir, red, fs):
        """Process one sample (ir/red = ADC counts). Returns (pi_ir, pi_red, R)."""
        if fs != self._fs:
            self.reconfigure(fs)
        ir = float(ir); red = float(red)

        # ── STEP 1: AC extraction ─────────────────────────────────────────────
        if self.step1 == self.S1_EMA:
            self._ema_dc_ir  += self._alpha_sub * (ir  - self._ema_dc_ir)
            self._ema_dc_red += self._alpha_sub * (red - self._ema_dc_red)
            self.dc_sub_ir  = self._ema_dc_ir
            self.dc_sub_red = self._ema_dc_red
            ac_ir  = ir  - self._ema_dc_ir
            ac_red = red - self._ema_dc_red
        elif self.step1 == self.S1_BPF:
            if self._bpf_sos is not None:
                if self._bpf_zi_ir is None:
                    zi = signal.sosfilt_zi(self._bpf_sos)
                    self._bpf_zi_ir  = zi * ir
                    self._bpf_zi_red = zi * red
                _out_ir,  self._bpf_zi_ir  = signal.sosfilt(self._bpf_sos, [ir],  zi=self._bpf_zi_ir)
                _out_red, self._bpf_zi_red = signal.sosfilt(self._bpf_sos, [red], zi=self._bpf_zi_red)
                ac_ir  = float(_out_ir[0]); ac_red = float(_out_red[0])
            else:
                ac_ir = ir; ac_red = red
            # dc_sub = signal minus BPF output (what the BPF removes)
            self.dc_sub_ir  = ir  - ac_ir
            self.dc_sub_red = red - ac_red
        else:  # S1_NONE — pass-through, nothing removed; show raw signal as DC reference
            ac_ir = ir; ac_red = red
            self.dc_sub_ir  = ir
            self.dc_sub_red = red

        # STEP1 pulsatile waveform output (fed to STEP2 amplitude estimator)
        self.ac_t_ir  = ac_ir
        self.ac_t_red = ac_red

        # ── STEP 2: AC estimator ─────────────────────────────────────────────
        if self.step2 == self.S2_EMA_RMS:
            self._ema_ac2_ir  += self._alpha_ac * (ac_ir  * ac_ir  - self._ema_ac2_ir)
            self._ema_ac2_red += self._alpha_ac * (ac_red * ac_red - self._ema_ac2_red)
            ac_r_ir  = math.sqrt(max(0.0, self._ema_ac2_ir))
            ac_r_red = math.sqrt(max(0.0, self._ema_ac2_red))
        elif self.step2 == self.S2_WIN_RMS:
            self._win_buf_ir.append(ac_ir);   self._win_buf_red.append(ac_red)
            while len(self._win_buf_ir)  > self._win_max_n: self._win_buf_ir.popleft()
            while len(self._win_buf_red) > self._win_max_n: self._win_buf_red.popleft()
            arr_ir  = np.fromiter(self._win_buf_ir,  dtype=float, count=len(self._win_buf_ir))
            arr_red = np.fromiter(self._win_buf_red, dtype=float, count=len(self._win_buf_red))
            ac_r_ir  = float(np.sqrt(np.mean(arr_ir  * arr_ir)))
            ac_r_red = float(np.sqrt(np.mean(arr_red * arr_red)))
        elif self.step2 == self.S2_PEAKPK:
            self._win_buf_ir.append(ac_ir);   self._win_buf_red.append(ac_red)
            while len(self._win_buf_ir)  > self._win_max_n: self._win_buf_ir.popleft()
            while len(self._win_buf_red) > self._win_max_n: self._win_buf_red.popleft()
            ac_r_ir  = (max(self._win_buf_ir)  - min(self._win_buf_ir))  / 2.0
            ac_r_red = (max(self._win_buf_red) - min(self._win_buf_red)) / 2.0
        elif self.step2 in (self.S2_SPECTRAL, self.S2_HARMONICS):
            self._raw_ir_buf.append(ir);   self._raw_red_buf.append(red)
            while len(self._raw_ir_buf)  > self._win_max_n: self._raw_ir_buf.popleft()
            while len(self._raw_red_buf) > self._win_max_n: self._raw_red_buf.popleft()
            n_fft = min(self.fft_len, len(self._raw_ir_buf))
            if n_fft >= 8:
                arr_ir  = np.array(list(self._raw_ir_buf)[-n_fft:],  dtype=float)
                arr_red = np.array(list(self._raw_red_buf)[-n_fft:], dtype=float)
                arr_ir  -= arr_ir.mean(); arr_red -= arr_red.mean()
                win     = np.hanning(n_fft)
                fft_ir  = np.abs(np.fft.rfft(arr_ir  * win))
                fft_red = np.abs(np.fft.rfft(arr_red * win))
                freqs   = np.fft.rfftfreq(n_fft, d=1.0 / self._fs)
                f0 = self.hr_bpm / 60.0
                if self.step2 == self.S2_SPECTRAL:
                    mask = np.abs(freqs - f0) <= self.delta_hz
                    e_ir  = float(np.sum(fft_ir[mask]  ** 2)) if mask.any() else 0.0
                    e_red = float(np.sum(fft_red[mask] ** 2)) if mask.any() else 0.0
                else:  # S2_HARMONICS
                    e_ir = 0.0; e_red = 0.0
                    for hn in range(1, self.n_harmonics + 1):
                        mask = np.abs(freqs - hn * f0) <= self.delta_hz
                        if mask.any():
                            e_ir  += float(np.sum(fft_ir[mask]  ** 2))
                            e_red += float(np.sum(fft_red[mask] ** 2))
                ac_r_ir  = math.sqrt(e_ir  / n_fft) if e_ir  > 0 else 0.0
                ac_r_red = math.sqrt(e_red / n_fft) if e_red > 0 else 0.0
            else:
                ac_r_ir = 0.0; ac_r_red = 0.0
        else:
            ac_r_ir = 0.0; ac_r_red = 0.0
        self.ac_r_ir = ac_r_ir; self.ac_r_red = ac_r_red

        # ── STEP 3: DC for denominator ────────────────────────────────────────
        if self.step3 == self.S3_EMA:
            self._ema_dc_r_ir  += self._alpha_norm * (ir  - self._ema_dc_r_ir)
            self._ema_dc_r_red += self._alpha_norm * (red - self._ema_dc_r_red)
            dc_r_ir  = self._ema_dc_r_ir; dc_r_red = self._ema_dc_r_red
        elif self.step3 == self.S3_LPF:
            if self._lpf_sos is not None:
                if self._lpf_zi_ir is None:
                    zi = signal.sosfilt_zi(self._lpf_sos)
                    self._lpf_zi_ir  = zi * ir; self._lpf_zi_red = zi * red
                _out_ir,  self._lpf_zi_ir  = signal.sosfilt(self._lpf_sos, [ir],  zi=self._lpf_zi_ir)
                _out_red, self._lpf_zi_red = signal.sosfilt(self._lpf_sos, [red], zi=self._lpf_zi_red)
                dc_r_ir  = float(_out_ir[0]); dc_r_red = float(_out_red[0])
            else:
                dc_r_ir = ir; dc_r_red = red
        elif self.step3 == self.S3_WIN_MEAN:
            self._norm_buf_ir.append(ir);   self._norm_buf_red.append(red)
            while len(self._norm_buf_ir)  > self._norm_max_n: self._norm_buf_ir.popleft()
            while len(self._norm_buf_red) > self._norm_max_n: self._norm_buf_red.popleft()
            dc_r_ir  = float(np.mean(list(self._norm_buf_ir)))
            dc_r_red = float(np.mean(list(self._norm_buf_red)))
        else:
            dc_r_ir = ir; dc_r_red = red

        self.dc_r_ir  = max(1.0, dc_r_ir)
        self.dc_r_red = max(1.0, dc_r_red)

        # ── PI & R ────────────────────────────────────────────────────────────
        self.pi_ir  = self.ac_r_ir  / self.dc_r_ir  * 100.0
        self.pi_red = self.ac_r_red / self.dc_r_red * 100.0
        self.R    = (self.pi_red / self.pi_ir) if self.pi_ir > 0.0 else 0.0
        self.spo2 = max(0.0, min(100.0, self.spo2_a - self.spo2_b * self.R)) if self.R > 0.0 else 0.0
        return self.pi_ir, self.pi_red, self.R


class HR3TestWindow(QtWidgets.QMainWindow):
    """HR3TEST — post-implementation verification window for the HR3 algorithm.

    Runs an independent Python mirror of the firmware HR3 algorithm (HR3TestCalc,
    derived from incunest_afe4490_spec.md §5.4) and compares against firmware output.

    The mirror runs at the decimated rate (50 Hz default) fed from PPGMonitor.update_plots().
    Offline mode: load any recorded CSV.

    Layout:
      Left  : 4 stacked plots — FFT+HPS spectrum, LP filtered buffer, HR3 fw/py, SQI fw/py.
      Right : parameter controls and current values table.
    """

    _HR_BUF = SPO2_CAL_BUFSIZE

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor     = main_monitor
        self.setWindowTitle("HR3TEST")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        self._offline_calc    = HR3TestCalc()
        self._last_sample_cnt = -1
        self._t0_us           = None
        self._offline_mode    = False
        self._paused          = False

        self._buf_t        = deque(maxlen=self._HR_BUF)
        self._buf_hr_fw    = deque(maxlen=self._HR_BUF)
        self._buf_hr_py    = deque(maxlen=self._HR_BUF)
        self._buf_hr_delta = deque(maxlen=self._HR_BUF)
        self._buf_sqi_fw   = deque(maxlen=self._HR_BUF)
        self._buf_sqi_py   = deque(maxlen=self._HR_BUF)

        # ── Root layout ───────────────────────────────────────────────────────
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_vbox = QtWidgets.QVBoxLayout(central)
        root_vbox.setContentsMargins(6, 6, 6, 4)
        root_vbox.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_load = QtWidgets.QPushButton("LOAD CSV")
        self._btn_load.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_load.clicked.connect(self._load_csv)
        self._btn_load.setToolTip(_make_tooltip("LOAD CSV",
            "Load a recorded CSV file for offline analysis. "
            "HR3 runs at 50 Hz (after decimation); any recorded CSV format is accepted."))
        toolbar.addWidget(self._btn_load)

        self._btn_clear = QtWidgets.QPushButton("BACK TO LIVE")
        self._btn_clear.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_clear.clicked.connect(self._clear_offline)
        self._btn_clear.setEnabled(False)
        self._btn_clear.setToolTip(_make_tooltip("BACK TO LIVE",
            "Discard offline data and return to live serial mode."))
        toolbar.addWidget(self._btn_clear)

        self._btn_export = QtWidgets.QPushButton("EXPORT CSV")
        self._btn_export.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_export.setToolTip(_make_tooltip("EXPORT CSV",
            "Export HR3 comparison table to a CSV file."))
        toolbar.addWidget(self._btn_export)

        self._btn_pause = QtWidgets.QPushButton("PAUSE")
        self._btn_pause.setCheckable(True)
        self._btn_pause.setStyleSheet(
            "QPushButton { background-color: #505050; color: #FFFFFF; font-weight: bold; "
            "border: 1px solid #888888; border-radius: 3px; padding: 4px 10px; }"
            "QPushButton:checked { background-color: #CC6600; color: #FFFFFF; "
            "border: 1px solid #FF8800; }")
        self._btn_pause.setToolTip(_make_tooltip("PAUSE",
            "Freeze the HR3TEST display. Live data and algorithms keep running; "
            "only the plots stop updating."))
        self._btn_pause.clicked.connect(self._toggle_pause)
        toolbar.addWidget(self._btn_pause)

        self._btn_py_plots = QtWidgets.QPushButton("PY PLOTS")
        self._btn_py_plots.setCheckable(True)
        self._btn_py_plots.setChecked(True)
        self._btn_py_plots.setStyleSheet(
            "QPushButton { background-color: #505050; color: #FFDD44; font-weight: bold; "
            "border: 1px solid #888888; border-radius: 3px; padding: 4px 10px; }"
            "QPushButton:checked { background-color: #3A3A00; color: #FFDD44; "
            "border: 1px solid #BBAA00; }"
            "QPushButton:!checked { background-color: #2A2A2A; color: #666600; "
            "border: 1px solid #444400; }")
        self._btn_py_plots.setToolTip(_make_tooltip("PY PLOTS",
            "Show/hide the Python-calculated HR3 and SQI curves (yellow) in plots 3 and 4. "
            "Uncheck to see only the firmware (FW) curves."))
        self._btn_py_plots.clicked.connect(self._toggle_py_plots)
        toolbar.addWidget(self._btn_py_plots)

        toolbar.addStretch()

        self._lbl_status = QtWidgets.QLabel("● FIRMWARE DEFAULTS")
        self._lbl_status.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
            "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip("Parameter status",
            "GREEN — FIRMWARE DEFAULTS: comparison is valid.\n"
            "ORANGE — CUSTOM PARAMS: comparison is exploratory."))
        toolbar.addWidget(self._lbl_status)

        root_vbox.addLayout(toolbar)

        # ── Main splitter ─────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(4)
        root_vbox.addWidget(splitter, stretch=1)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        splitter.addWidget(glw)

        def _mp(row, title, ylabel, link_to=None):
            p = glw.addPlot(row=row, col=0,
                            title=f"<b style='color:#CCCCCC'>{title}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel('left', ylabel)
            p.enableAutoRange()
            if link_to is not None:
                p.setXLink(link_to)
            return p

        self.p_fft  = _mp(0, "FFT + HPS Spectrum",       "norm. magnitude")
        self.p_filt = _mp(1, "LP filtered signal  (512-sample buffer)", "ADC counts")
        self.p_filt.setTitle("<b style='color:#FFDD44'>LP filtered signal  (512-sample buffer)</b>")
        self.p_hr   = _mp(2, "HR3 (bpm)",                "BPM")
        self.p_sqi  = _mp(3, "SQI [0\u20131]",           "SQI", link_to=self.p_hr)

        self.p_fft.setLabel('bottom', 'frequency (Hz)')
        self.p_filt.setLabel('bottom', 't (s)')
        self.p_hr.setLabel('bottom', 't (s)')
        self.p_sqi.setLabel('bottom', 't (s)')
        self.p_sqi.setYRange(0, 1.05)

        FW_PEN    = pg.mkPen('#00CC66', width=2)
        FW_LO_PEN = pg.mkPen('#2D6E47', width=2)   # fw low-SQI: darker green
        PY_PEN    = pg.mkPen('#FFDD44', width=2)
        FFT_PEN   = pg.mkPen('#00CCFF', width=1.5)
        HPS_PEN  = pg.mkPen('#FF8800', width=1.5)
        FILT_PEN = pg.mkPen('#FFDD44', width=1)

        # FFT plot decorations
        hr_min_hz = HR3TestCalc.FW_HR_SEARCH_MIN / 60.0
        hr_max_hz = HR3TestCalc.FW_HR_SEARCH_MAX / 60.0
        self._hr_region = pg.LinearRegionItem(
            values=[hr_min_hz, hr_max_hz],
            brush=pg.mkBrush(0, 180, 255, 20), movable=False)
        self.p_fft.addItem(self._hr_region)
        self.curve_fft = self.p_fft.plot(pen=FFT_PEN, name="FFT")
        self.curve_hps = self.p_fft.plot(pen=HPS_PEN, name="HPS")
        self._peak_line = pg.InfiniteLine(
            angle=90, pos=0, movable=False,
            pen=pg.mkPen('#FFDD44', width=2),
            label='peak', labelOpts={'color': '#FFDD44', 'position': 0.92})
        self.p_fft.addItem(self._peak_line)
        self.p_fft.setXRange(0, 5.5)
        self.p_fft.setYRange(0, 1.05)
        self.p_fft.addLegend()

        self.curve_filt  = self.p_filt.plot(pen=FILT_PEN)
        self.curve_filt.setDownsampling(auto=True, method='peak')
        self.curve_filt.setClipToView(True)
        self.p_hr.addLegend()
        self.curve_hr_py    = self.p_hr.plot(pen=PY_PEN,    name="HR3 py")
        self.curve_hr_fw    = self.p_hr.plot(pen=FW_PEN,    name="HR3 fw")
        self.curve_hr_fw_lo = self.p_hr.plot(pen=FW_LO_PEN, name="SQI&lt;0.9")
        self.p_sqi.addLegend()
        self.curve_sqi_py = self.p_sqi.plot(pen=PY_PEN,  name="SQI py")
        self.curve_sqi_fw = self.p_sqi.plot(pen=FW_PEN,  name="SQI fw")

        # ── Right: parameters + table ─────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #1A1A1A;")
        splitter.addWidget(right)
        splitter.setSizes([900, 320])

        right_vbox = QtWidgets.QVBoxLayout(right)
        right_vbox.setContentsMargins(10, 10, 10, 10)
        right_vbox.setSpacing(10)

        grp_params = QtWidgets.QGroupBox("Algorithm parameters")
        grp_params.setStyleSheet(
            "QGroupBox { color: #AAAAAA; font-weight: bold; font-size: 18px; "
            "border: 1px solid #444; border-radius: 4px; margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        form = QtWidgets.QFormLayout(grp_params)
        form.setSpacing(6)
        _sp_s  = "background-color: #2A2A2A; color: #FFDD44; padding: 3px; font-size: 18px;"
        _lbl_s = "color: #CCCCCC; font-size: 18px;"

        def _dspin(lo, hi, val, dec, step, suffix=""):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi); w.setDecimals(dec); w.setSingleStep(step)
            w.setValue(val); w.setStyleSheet(_sp_s)
            if suffix: w.setSuffix(suffix)
            return w

        def _ispin(lo, hi, val):
            w = QtWidgets.QSpinBox()
            w.setRange(lo, hi); w.setValue(val); w.setStyleSheet(_sp_s)
            return w

        self._spin_bp_low      = _dspin(0.1, 5.0,  HR3TestCalc.FW_BP_LOW_HZ,  1, 0.1, " Hz")
        self._spin_bp_high     = _dspin(5.0, 25.0, HR3TestCalc.FW_BP_HIGH_HZ, 1, 0.5, " Hz")
        self._spin_buf_len     = _ispin(128,  1024, HR3TestCalc.FW_BUF_LEN)
        self._spin_upd_n       = _ispin(1,    200,  HR3TestCalc.FW_UPDATE_N)
        self._spin_harmonics   = _ispin(2,    5,    HR3TestCalc.FW_HPS_HARMONICS)

        self._spin_bp_low.setToolTip(_make_tooltip("BP low cutoff",
            "Butterworth bandpass lower cutoff [Hz]. "
            "Firmware default: 0.4 Hz. Removes DC and baseline drift.",
            src="hr3_bp_low_hz"))
        self._spin_bp_high.setToolTip(_make_tooltip("BP high cutoff",
            "Butterworth bandpass upper cutoff [Hz]. "
            "Firmware default: 15 Hz. Preserves 3rd harmonic of 260 BPM (13 Hz).",
            src="hr3_bp_high_hz"))
        self._spin_buf_len.setToolTip(_make_tooltip("Buffer length",
            "Circular buffer length [samples]. "
            "Firmware default: 512 (10.24 s at 50 Hz). Determines FFT frequency resolution.",
            src="hr3_buf_len"))
        self._spin_upd_n.setToolTip(_make_tooltip("Update every N",
            "Run FFT/HPS every N samples. "
            "Firmware default: 25 (every 0.5 s at 50 Hz).",
            src="hr3_update_n"))
        self._spin_harmonics.setToolTip(_make_tooltip("HPS harmonics",
            "Number of harmonic downsamples in HPS: multiply spectrum by P[2k], ..., P[Kk]. "
            "Firmware default: 3 (k=2 and k=3).",
            src="hr3_hps_harmonics"))

        def _row(label_text, widget):
            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet(_lbl_s)
            form.addRow(lbl, widget)

        _row("BP low cutoff:",    self._spin_bp_low)
        _row("BP high cutoff:",   self._spin_bp_high)
        _row("Buffer length:",    self._spin_buf_len)
        _row("Update every N:",   self._spin_upd_n)
        _row("HPS harmonics:",    self._spin_harmonics)

        for sp in [self._spin_bp_low, self._spin_bp_high, self._spin_buf_len,
                   self._spin_upd_n, self._spin_harmonics]:
            sp.valueChanged.connect(self._on_param_changed)

        right_vbox.addWidget(grp_params)

        # Reset button
        self._btn_reset = QtWidgets.QPushButton("RESET TO DEFAULTS")
        self._btn_reset.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_reset.clicked.connect(self._reset_to_defaults)
        self._btn_reset.setToolTip(_make_tooltip("RESET TO DEFAULTS",
            "Restore all algorithm parameters to firmware defaults and reset the algorithm state."))
        right_vbox.addWidget(self._btn_reset)

        # Values table
        grp_vals = QtWidgets.QGroupBox("Current values")
        grp_vals.setStyleSheet(grp_params.styleSheet())
        vals_layout = QtWidgets.QVBoxLayout(grp_vals)

        self._val_table = QtWidgets.QTableWidget(3, 4)
        self._val_table.setStyleSheet(
            "QTableWidget { background: #1A1A1A; color: #E0E0E0; "
            "gridline-color: #333; font-size: 16px; border: none; }"
            "QHeaderView::section { background: #252525; color: #AAAAAA; "
            "font-size: 15px; padding: 3px; border: none; }")
        self._val_table.setHorizontalHeaderLabels(["Signal", "Firmware", "Python", "Delta"])
        self._val_table.verticalHeader().setVisible(False)
        self._val_table.horizontalHeader().setStretchLastSection(True)
        self._val_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._val_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        row_labels = ["HR3 (bpm)", "SQI", "Peak freq (Hz)"]
        for r, lbl in enumerate(row_labels):
            item = QtWidgets.QTableWidgetItem(lbl)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            self._val_table.setItem(r, 0, item)
            for c in range(1, 4):
                self._val_table.setItem(r, c, QtWidgets.QTableWidgetItem("---"))
        vals_layout.addWidget(self._val_table)
        right_vbox.addWidget(grp_vals)
        right_vbox.addStretch()

        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("HR3TestWindow/geometry")
        if geom: self.restoreGeometry(geom)

    def _get_live_calc(self):
        """Return the HR3TestCalc for live mode (owned by PPGMonitor)."""
        if self.main_monitor is not None and hasattr(self.main_monitor, 'hr3test_calc'):
            return self.main_monitor.hr3test_calc
        return self._offline_calc

    def _active_calc(self):
        """Return offline or live calc depending on mode."""
        return self._offline_calc if self._offline_mode else self._get_live_calc()

    def _on_param_changed(self):
        calc = self._active_calc()
        calc.bp_low_hz     = self._spin_bp_low.value()
        calc.bp_high_hz    = self._spin_bp_high.value()
        calc.buf_len       = self._spin_buf_len.value()
        calc.update_n      = self._spin_upd_n.value()
        calc.hps_harmonics = self._spin_harmonics.value()
        calc.reset()
        self._update_status_indicator()

    def _reset_to_defaults(self):
        for sp, attr in [(self._spin_bp_low,    'FW_BP_LOW_HZ'),
                         (self._spin_bp_high,   'FW_BP_HIGH_HZ'),
                         (self._spin_buf_len,   'FW_BUF_LEN'),
                         (self._spin_upd_n,     'FW_UPDATE_N'),
                         (self._spin_harmonics, 'FW_HPS_HARMONICS')]:
            sp.blockSignals(True)
            sp.setValue(getattr(HR3TestCalc, attr))
            sp.blockSignals(False)
        self._active_calc().reset_to_defaults()
        self._update_status_indicator()

    def _update_status_indicator(self):
        if self._active_calc().using_defaults:
            self._lbl_status.setText("● FIRMWARE DEFAULTS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #00CC66; padding: 4px 10px; "
                "background: #0A2A0A; border: 1px solid #00AA44; border-radius: 4px;")
        else:
            self._lbl_status.setText("● CUSTOM PARAMS")
            self._lbl_status.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FFAA00; padding: 4px 10px; "
                "background: #2A1A00; border: 1px solid #AA7700; border-radius: 4px;")

    # ── Offline mode ──────────────────────────────────────────────────────────

    def _load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self._process_csv_offline(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Load CSV error", str(e))

    def _process_csv_offline(self, path):
        import csv as _csv
        rows_led1_sub = []
        rows_hr_fw  = []
        rows_sqi_fw = []
        rows_ts_us  = []
        with open(path, 'r', newline='') as f:
            header = f.readline().strip()
            is_chk = header.startswith("Timestamp_PC,Diff_us_PC,CHK_OK")
            reader = _csv.reader(f)
            for row in reader:
                if not row:
                    continue
                try:
                    if is_chk:
                        if len(row) < 4 or row[2].strip() != '1':
                            continue
                        raw = row[3].strip()
                        if '*' in raw:
                            raw = raw[:raw.rfind('*')]
                        parts = raw.split(',')
                        if len(parts) < 20 or parts[0] not in ('$M1', '$M3'):
                            continue
                        ts_us  = float(parts[2])
                        led1_sub = float(parts[8])
                        hr_fw  = float(parts[18])
                        sqi_fw = float(parts[19])
                    else:
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', 'M3', '$M1', '$M3'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        led1_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 17])
                        sqi_fw = float(row[offset + 18])
                    rows_ts_us.append(ts_us)
                    rows_led1_sub.append(led1_sub)
                    rows_hr_fw.append(hr_fw if hr_fw > 0 else float('nan'))
                    rows_sqi_fw.append(sqi_fw if sqi_fw >= 0 else float('nan'))
                except (ValueError, IndexError):
                    continue

        if not rows_ts_us:
            raise ValueError("No valid M1 samples found.")

        ts_arr = np.array(rows_ts_us)
        diffs = np.diff(ts_arr); diffs = diffs[diffs > 0]
        fs = float(1e6 / np.median(diffs)) if len(diffs) else 50.0
        for std_fs in [500, 250, 100, 50, 25]:
            if abs(fs - std_fs) < std_fs * 0.2:
                fs = float(std_fs); break

        self._offline_calc.reset_to_defaults()
        self._offline_calc.bp_low_hz     = self._spin_bp_low.value()
        self._offline_calc.bp_high_hz    = self._spin_bp_high.value()
        self._offline_calc.buf_len       = self._spin_buf_len.value()
        self._offline_calc.update_n      = self._spin_upd_n.value()
        self._offline_calc.hps_harmonics = self._spin_harmonics.value()
        self._offline_calc.reset()

        nan = float('nan')
        n = len(rows_led1_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_led1_sub):
            self._offline_calc.update(ir, fs)
            if self._offline_calc.hr_bpm > 0:
                arr_hr_py[i]  = self._offline_calc.hr_bpm
                arr_sqi_py[i] = self._offline_calc.hr_sqi

        arr_delta = arr_hr_fw - arr_hr_py

        self._offline_mode = True
        self._btn_clear.setEnabled(True)
        fname = path.split('/')[-1].split('\\')[-1]
        self.statusBar().showMessage(f"OFFLINE — {fname}  ({n} samples, fs≈{fs:.0f} Hz)")

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sqi_fw, arr_sqi_py)
        self._refresh_fft_plot()
        self._refresh_filt_plot(arr_t)
        self._update_status_indicator()

    def _clear_offline(self):
        self._offline_mode = False
        self._btn_clear.setEnabled(False)
        self._last_sample_cnt = -1
        self._t0_us = None
        for buf in [self._buf_t, self._buf_hr_fw, self._buf_hr_py,
                    self._buf_hr_delta, self._buf_sqi_fw, self._buf_sqi_py]:
            buf.clear()
        self._get_live_calc().reset()
        self.statusBar().showMessage(_MOUSE_HINT)
        for c in [self.curve_fft, self.curve_hps, self.curve_filt,
                  self.curve_hr_fw, self.curve_hr_fw_lo, self.curve_hr_py,
                  self.curve_sqi_fw, self.curve_sqi_py]:
            c.setData([], [])

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        t = np.array(self._buf_t)
        if len(t) == 0:
            QtWidgets.QMessageBox.information(self, "Export", "No data to export.")
            return
        now_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(CAPTURES_DIR, f"hr3test_{now_str}.csv")
        hr_fw  = np.array(self._buf_hr_fw);  hr_py  = np.array(self._buf_hr_py)
        sqi_fw = np.array(self._buf_sqi_fw); sqi_py = np.array(self._buf_sqi_py)
        try:
            with open(filename, 'w') as f:
                f.write(f"# HR3TEST export — {datetime.datetime.now()}\n")
                _c = self._active_calc()
                f.write(f"# bp={_c.bp_low_hz:.1f}-{_c.bp_high_hz:.1f} Hz, "
                        f"buf={_c.buf_len}, update_n={_c.update_n}, "
                        f"hps_harmonics={_c.hps_harmonics}\n")
                f.write("t_s,hr3_fw,hr3_py,hr3_delta,sqi_fw,sqi_py\n")
                nan = float('nan')
                for i in range(len(t)):
                    def _fv(arr, i): v = arr[i] if i < len(arr) else nan; return f"{v:.2f}" if not np.isnan(v) else ""
                    delta = hr_fw[i] - hr_py[i] if i < len(hr_fw) and i < len(hr_py) else nan
                    f.write(f"{t[i]:.3f},{_fv(hr_fw,i)},{_fv(hr_py,i)},"
                            f"{'%.2f'%delta if not np.isnan(delta) else ''},"
                            f"{_fv(sqi_fw,i)},{_fv(sqi_py,i)}\n")
            self.statusBar().showMessage(f"Exported: {filename}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Export error", str(e))

    # ── Live update ───────────────────────────────────────────────────────────

    def _toggle_pause(self):
        self._paused = self._btn_pause.isChecked()
        self._btn_pause.setText("RESUME" if self._paused else "PAUSE")

    def _toggle_py_plots(self):
        visible = self._btn_py_plots.isChecked()
        self.curve_hr_py.setVisible(visible)
        self.curve_sqi_py.setVisible(visible)

    def update_plots(self, data_led1_sub, data_hr3, data_hr3_sqi,
                     data_timestamp_us, data_sample_counter):
        if self._offline_mode or self._paused:
            return
        n = len(data_sample_counter)
        if n == 0:
            return

        new_indices = []
        for i in range(n - 1, -1, -1):
            if data_sample_counter[i] <= self._last_sample_cnt:
                break
            new_indices.append(i)
        if not new_indices:
            return
        new_indices.reverse()

        nan = float('nan')
        for i in new_indices:
            ts    = float(data_timestamp_us[i])
            hr_f  = float(data_hr3[i])
            sqi_f = float(data_hr3_sqi[i])
            if self._t0_us is None:
                self._t0_us = ts
            t_s = (ts - self._t0_us) / 1e6

            # _calc.update() is called per-sample in PPGMonitor._process_frames_tick()
            _c     = self._get_live_calc()
            hr_fw  = hr_f  if hr_f  > 0 else nan
            sqi_fw = sqi_f if sqi_f >= 0 else nan
            hr_py  = _c.hr_bpm if _c.hr_bpm > 0 else nan
            sqi_py = _c.hr_sqi if _c.hr_bpm > 0 else nan
            delta  = (hr_fw - hr_py) if not (np.isnan(hr_fw) or np.isnan(hr_py)) else nan

            self._buf_t.append(t_s)
            self._buf_hr_fw.append(hr_fw)
            self._buf_hr_py.append(hr_py)
            self._buf_hr_delta.append(delta)
            self._buf_sqi_fw.append(sqi_fw)
            self._buf_sqi_py.append(sqi_py)

        self._last_sample_cnt = data_sample_counter[-1]

        arr_t     = np.array(self._buf_t)
        arr_hr_fw = np.array(self._buf_hr_fw); arr_hr_py = np.array(self._buf_hr_py)
        arr_delta = np.array(self._buf_hr_delta)
        arr_sf    = np.array(self._buf_sqi_fw); arr_sp    = np.array(self._buf_sqi_py)

        self._refresh_hr_plots(arr_t, arr_hr_fw, arr_hr_py, arr_delta, arr_sf, arr_sp)
        self._refresh_fft_plot()
        self._refresh_filt_plot(arr_t)

        # Value table
        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        fw_v = [_lv(arr_hr_fw), _lv(arr_sf), float('nan')]
        py_v = [_lv(arr_hr_py), _lv(arr_sp), self._get_live_calc().last_peak_freq]
        dec  = [1, 3, 3]
        for row in range(3):
            fv = fw_v[row]; pv = py_v[row]
            dv = (fv - pv) if not (np.isnan(fv) or np.isnan(pv)) else float('nan')
            self._val_table.item(row, 1).setText(_fmt(fv, dec[row]))
            self._val_table.item(row, 2).setText(_fmt(pv, dec[row]))
            self._val_table.item(row, 3).setText(_fmt(dv, dec[row]))
            if not np.isnan(dv) and row == 0:
                color = QtGui.QColor("#00CC66") if abs(dv) < 3.0 else QtGui.QColor("#FF4444")
                self._val_table.item(row, 3).setForeground(color)

        self._update_status_indicator()

    _SQI_ALERT = 0.9   # HR3 fw points below this threshold shown in darker green

    def _refresh_hr_plots(self, t, hr_fw, hr_py, delta, sqi_fw, sqi_py):
        hi_mask = sqi_fw >= self._SQI_ALERT
        self.curve_hr_fw.setData(t, np.where(hi_mask, hr_fw, np.nan))
        self.curve_hr_fw_lo.setData(t, np.where(~hi_mask, hr_fw, np.nan))
        self.curve_hr_py.setData(t, hr_py)
        self.curve_sqi_fw.setData(t, sqi_fw)
        self.curve_sqi_py.setData(t, sqi_py)
        def _lv(arr): v = arr[~np.isnan(arr)]; return v[-1] if len(v) else float('nan')
        def _fmt(v, d=1): return f"{v:.{d}f}" if not np.isnan(v) else "---"
        v_fw = _lv(hr_fw); v_py = _lv(hr_py); v_d = _lv(delta)
        self.p_hr.setTitle(
            f"<b style='color:#FFFFFF'>HR3</b><b style='color:#00CC66'> fw: {_fmt(v_fw)} bpm</b>"
            f"  <b style='color:#FFDD44'>py: {_fmt(v_py)} bpm</b>"
            f"  <span style='color:#FF6666'>\u0394={_fmt(v_d)}</span>")
        s_fw = _lv(sqi_fw); s_py = _lv(sqi_py)
        self.p_sqi.setTitle(
            f"<b style='color:#FFFFFF'>SQI</b><b style='color:#00CC66'> fw: {_fmt(s_fw, 2)}</b>"
            f"  <b style='color:#FFDD44'>py: {_fmt(s_py, 2)}</b>")

    def _refresh_fft_plot(self):
        c     = self._active_calc()
        freqs = c.last_freqs
        spec  = c.last_spectrum
        hps   = c.last_hps
        if len(freqs) > 0 and len(spec) > 0:
            self.curve_fft.setData(freqs, spec)
            self.curve_hps.setData(freqs, hps)
            peak = c.last_peak_freq
            if peak > 0:
                self._peak_line.setValue(peak)
                hr_at_peak = peak * 60.0
                sqi_at_peak = c.hr_sqi
                self.p_fft.setTitle(
                    f"<b style='color:#00CCFF'>FFT + <span style='color:#FF8800'>HPS</span></b>"
                    f"  <span style='color:#FFDD44'>peak={peak:.3f} Hz \u2192 {hr_at_peak:.1f} bpm"
                    f"  SQI={sqi_at_peak:.3f}</span>")

    def _refresh_filt_plot(self, t_hr):
        c    = self._active_calc()
        filt = c.last_filtered_buf
        if len(filt) > 0 and len(t_hr) > 0:
            t_end = t_hr[-1]
            fs = c._fs if c._fs > 0 else HR3TestCalc.FW_FS
            filt_t = t_end - (len(filt) - 1 - np.arange(len(filt))) / fs
            self.curve_filt.setData(filt_t, filt)

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("HR3TestWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hr3test.setChecked(False)
            self.main_monitor.hr3test_window = None
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
#  PILabWindow — Perfusion Index pipeline investigation window
# ──────────────────────────────────────────────────────────────────────────────

class PILabWindow(QtWidgets.QMainWindow):
    """PILAB — Perfusion Index pipeline investigation window.

    Two independent PICalc instances (A = firmware reference, B = experimental)
    run in parallel on live or recorded data. Each uses a 3-step configurable
    pipeline: STEP1 (AC extraction) → STEP2 (AC estimator) → STEP3 (DC denominator).

    Layout:
      Left  : 4 stacked plots — signal+DC_sub, AC_r over time, PI_ir, R ratio.
      Right : Tabbed config panels for instance A (orange) and B (blue) + value table.
    """

    _BUF_LEN    = 3000    # 3000 samples @ 50 Hz → 60 s
    _PLOT_WIN_S = 30.0    # visible x-axis window (s)
    _CLR_SIG    = "#888888"
    _CLR_A      = "#FF8800"   # instance A — orange
    _CLR_B      = "#44AAFF"   # instance B — blue

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("PILAB")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        self._paused       = False
        self._offline_mode = False
        self._t0_us        = None

        self.calc_a = PICalc()   # A = firmware M1 defaults
        self.calc_b = PICalc()   # B = user-configurable

        # rolling plot buffers
        self._t_buf     = deque(maxlen=self._BUF_LEN)
        self._ir_buf    = deque(maxlen=self._BUF_LEN)
        self._dc_sub_a  = deque(maxlen=self._BUF_LEN)
        self._dc_sub_b  = deque(maxlen=self._BUF_LEN)
        self._ac_t_a    = deque(maxlen=self._BUF_LEN)
        self._ac_t_b    = deque(maxlen=self._BUF_LEN)
        self._pi_ir_a   = deque(maxlen=self._BUF_LEN)
        self._pi_ir_b   = deque(maxlen=self._BUF_LEN)
        self._r_a       = deque(maxlen=self._BUF_LEN)
        self._r_b       = deque(maxlen=self._BUF_LEN)
        self._spo2_a    = deque(maxlen=self._BUF_LEN)
        self._spo2_b    = deque(maxlen=self._BUF_LEN)

        self._build_ui()

        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("PILabWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1800, 900)

        # restore config from ini (falls back to widget defaults if not saved yet)
        for inst, cfg in (("A", self._cfg_a), ("B", self._cfg_b)):
            pfx = f"PILabWindow/{inst}"
            if s.contains(f"{pfx}/s1"):
                cfg['s1'].setCurrentIndex(s.value(f"{pfx}/s1",      0,    type=int))
                cfg['s2'].setCurrentIndex(s.value(f"{pfx}/s2",      0,    type=int))
                cfg['s3'].setCurrentIndex(s.value(f"{pfx}/s3",      0,    type=int))
                cfg['tau_sub'].setValue(  s.value(f"{pfx}/tau_sub", 2.0,  type=float))
                cfg['bpf_lo'].setValue(   s.value(f"{pfx}/bpf_lo",  0.5,  type=float))
                cfg['bpf_hi'].setValue(   s.value(f"{pfx}/bpf_hi",  4.0,  type=float))
                cfg['tau_ac'].setValue(   s.value(f"{pfx}/tau_ac",  6.0,  type=float))
                cfg['win_s'].setValue(    s.value(f"{pfx}/win_s",   4.0,  type=float))
                cfg['hr_bpm'].setValue(   s.value(f"{pfx}/hr_bpm",  70.0, type=float))
                cfg['n_harm'].setValue(   s.value(f"{pfx}/n_harm",  3,    type=int))
                cfg['tau_norm'].setValue( s.value(f"{pfx}/tau_norm",2.0,  type=float))
                cfg['lpf_fc'].setValue(   s.value(f"{pfx}/lpf_fc",  0.4,  type=float))
                cfg['win_norm'].setValue( s.value(f"{pfx}/win_norm",4.0,  type=float))

        # apply config (uses current widget values, restored or default)
        self._apply_config(self._cfg_a, self.calc_a)
        self._apply_config(self._cfg_b, self.calc_b)
        self._refresh_param_state(self._cfg_a)
        self._refresh_param_state(self._cfg_b)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        cw = QtWidgets.QWidget()
        self.setCentralWidget(cw)
        root = QtWidgets.QHBoxLayout(cw)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── left: 4 stacked plots ─────────────────────────────────────────────
        gv = pg.GraphicsLayoutWidget()
        gv.setBackground("#121212")
        root.addWidget(gv, stretch=2)

        def _pen(c): return pg.mkPen(c, width=1)

        self.p_sig = gv.addPlot(row=0, col=0)
        self.p_sig.setLabel('left', "AC_t_ir [ADC]")
        self.p_sig.showGrid(x=True, y=True, alpha=0.3)
        self.p_sig.addLegend(offset=(5, 5))
        self.curve_sig   = self.p_sig.plot(pen=_pen(self._CLR_SIG), name="led1_sub")
        self.curve_act_a = self.p_sig.plot(pen=_pen(self._CLR_A),   name="AC_t A")
        self.curve_act_b = self.p_sig.plot(pen=_pen(self._CLR_B),   name="AC_t B")

        self.p_ac = gv.addPlot(row=1, col=0)
        self.p_ac.setLabel('left', "AC_r_ir [ADC]")
        self.p_ac.showGrid(x=True, y=True, alpha=0.3)
        self.p_ac.addLegend(offset=(5, 5))
        self.curve_ac_a = self.p_ac.plot(pen=_pen(self._CLR_A), name="AC_r A")
        self.curve_ac_b = self.p_ac.plot(pen=_pen(self._CLR_B), name="AC_r B")

        self.p_pi = gv.addPlot(row=2, col=0)
        self.p_pi.setLabel('left', "PI_ir [%]")
        self.p_pi.showGrid(x=True, y=True, alpha=0.3)
        self.p_pi.addLegend(offset=(5, 5))
        self.curve_pi_a = self.p_pi.plot(pen=_pen(self._CLR_A), name="PI_ir A")
        self.curve_pi_b = self.p_pi.plot(pen=_pen(self._CLR_B), name="PI_ir B")

        self.p_r = gv.addPlot(row=3, col=0)
        self.p_r.setLabel('left', "R = PI_red / PI_ir")
        self.p_r.showGrid(x=True, y=True, alpha=0.3)
        self.p_r.addLegend(offset=(5, 5))
        self.curve_r_a = self.p_r.plot(pen=_pen(self._CLR_A), name="R A")
        self.curve_r_b = self.p_r.plot(pen=_pen(self._CLR_B), name="R B")

        self.p_spo2 = gv.addPlot(row=4, col=0)
        self.p_spo2.setLabel('left', "SpO2 [%]")
        self.p_spo2.setLabel('bottom', "Time [s]")
        self.p_spo2.showGrid(x=True, y=True, alpha=0.3)
        self.p_spo2.addLegend(offset=(5, 5))
        self.curve_spo2_a = self.p_spo2.plot(pen=_pen(self._CLR_A), name="SpO2 A")
        self.curve_spo2_b = self.p_spo2.plot(pen=_pen(self._CLR_B), name="SpO2 B")

        self.p_ac.setXLink(self.p_sig)
        self.p_pi.setXLink(self.p_sig)
        self.p_r.setXLink(self.p_sig)
        self.p_spo2.setXLink(self.p_sig)

        # ── right panel ───────────────────────────────────────────────────────
        right = QtWidgets.QVBoxLayout()
        root.addLayout(right, stretch=2)

        # toolbar
        tbar = QtWidgets.QHBoxLayout()
        right.addLayout(tbar)

        self.btn_load = QtWidgets.QPushButton("LOAD CSV")
        self.btn_load.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_load.setToolTip(_make_tooltip("Load CSV",
            "Load a recorded CSV file and replay it through both PI pipelines."))
        self.btn_load.clicked.connect(self._on_load_csv)
        tbar.addWidget(self.btn_load)

        self.btn_live = QtWidgets.QPushButton("LIVE")
        self.btn_live.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_live.setEnabled(False)
        self.btn_live.setToolTip(_make_tooltip("Back to live",
            "Switch back to real-time live mode."))
        self.btn_live.clicked.connect(self._on_go_live)
        tbar.addWidget(self.btn_live)

        self.btn_pause = QtWidgets.QPushButton("PAUSE")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause.setToolTip(_make_tooltip("Pause",
            "Freeze plots without stopping data collection."))
        self.btn_pause.clicked.connect(self._toggle_pause)
        tbar.addWidget(self.btn_pause)

        tbar.addStretch()
        btn_help = QtWidgets.QPushButton("?")
        btn_help.setFixedWidth(36)
        btn_help.setStyleSheet(ACTION_BUTTON_STYLE)
        btn_help.setToolTip(_make_tooltip("Help", "Explain the four plots and the 3-step PI pipeline."))
        btn_help.clicked.connect(self._show_help)
        tbar.addWidget(btn_help)

        # config columns A / B — always visible side by side
        self._cfg_a = self._make_config_tab("A", self._CLR_A)
        self._cfg_b = self._make_config_tab("B", self._CLR_B)
        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(4)
        cols.addWidget(self._cfg_a['widget'])
        cols.addWidget(self._cfg_b['widget'])
        right.addLayout(cols, stretch=1)

        # value table
        self._val_table = QtWidgets.QTableWidget(8, 2)
        self._val_table.setHorizontalHeaderLabels(["A (orange)", "B (blue)"])
        self._val_table.horizontalHeaderItem(0).setForeground(QtGui.QColor(self._CLR_A))
        self._val_table.horizontalHeaderItem(1).setForeground(QtGui.QColor(self._CLR_B))
        self._val_table.setVerticalHeaderLabels([
            "AC_r_red", "DC_r_red", "AC_r_ir", "DC_r_ir",
            "PI_red [%]", "PI_ir [%]", "R", "SpO2 [%]",
        ])
        self._val_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self._val_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self._val_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._val_table.setStyleSheet(
            "QTableWidget { background: #1A1A1A; color: #E0E0E0; font-size: 24px; }"
            "QHeaderView::section { background: #252525; font-size: 20px; font-weight: bold; }"
        )
        _row_tips = [
            "AC_r_red — STEP2 output: pulsatile amplitude estimate for red channel [ADC counts]",
            "DC_r_red — STEP3 output: DC denominator for red channel [ADC counts]",
            "AC_r_ir  — STEP2 output: pulsatile amplitude estimate for IR channel [ADC counts]",
            "DC_r_ir  — STEP3 output: DC denominator for IR channel [ADC counts]",
            "PI_red   — Perfusion Index red = AC_r_red / DC_r_red × 100 [%]",
            "PI_ir    — Perfusion Index IR  = AC_r_ir  / DC_r_ir  × 100 [%]",
            "R        — SpO2 ratio = PI_red / PI_ir (dimensionless; ~0.4–1.0 physiological range)",
            "SpO2     — Provisional estimate: 110 − 25×R [%]  (linear approximation, not calibrated)",
        ]
        for i, tip in enumerate(_row_tips):
            self._val_table.verticalHeaderItem(i).setToolTip(tip)
        self._val_table.setMinimumHeight(480)
        self._val_table.setMaximumHeight(700)
        self._val_table.setToolTip(_make_tooltip("PI pipeline values",
            "Full decomposition of the 3-step PI pipeline for instances A and B.\n"
            "Hover over row headers for per-row details."))
        right.addWidget(self._val_table)
        right.addStretch()

    def _make_config_tab(self, name, color):
        """Build STEP1/2/3 config panel for one PICalc instance. Returns a dict."""
        _ss_spin = ("QDoubleSpinBox { background-color: #2A2A2A; color: #FFDD44; padding: 2px; font-size: 20px; }"
                    " QDoubleSpinBox:disabled { color: #505050; background-color: #1A1A1A; }"
                    " QSpinBox { background-color: #2A2A2A; color: #FFDD44; padding: 2px; font-size: 20px; }"
                    " QSpinBox:disabled { color: #505050; background-color: #1A1A1A; }")
        _ss_cb   = "background-color: #2A2A2A; color: #FFFFFF; font-size: 20px;"
        _lbl_sty = f"color: {color}; font-size: 20px; font-weight: bold;"

        def _dspin(lo, hi, val, step, suffix=""):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi); w.setDecimals(2); w.setSingleStep(step); w.setValue(val)
            w.setStyleSheet(_ss_spin)
            if suffix: w.setSuffix(suffix)
            return w

        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: #1A1A1A; QLabel { font-size: 20px; color: #C0C0C0; }"
                            " QLabel:disabled { color: #454545; }")
        form = QtWidgets.QFormLayout(inner)
        form.setSpacing(5); form.setContentsMargins(8, 8, 8, 8)

        # STEP 1
        lbl1 = QtWidgets.QLabel("── STEP1: AC extraction ──")
        lbl1.setStyleSheet(_lbl_sty); form.addRow(lbl1)
        s1 = QtWidgets.QComboBox(); s1.setStyleSheet(_ss_cb)
        s1.addItems(["1.1 EMA subtract", "1.2 BPF", "1.3 None"])
        s1.setToolTip(_make_tooltip("STEP1 method",
            "1.1 EMA: subtract running EMA (τ_sub) from signal — firmware M1\n"
            "1.2 BPF: 2nd-order Butterworth bandpass filter\n"
            "1.3 None: pass-through (only valid with spectral STEP2)",
            src="PICalc.step1"))
        form.addRow("Method:", s1)
        tau_sub = _dspin(0.1, 30.0, 2.0, 0.5, " s")
        tau_sub.setToolTip(_make_tooltip("τ_sub",
            "EMA time constant for DC subtraction (s). Firmware M1 default: 2.0 s.",
            src="PICalc.tau_sub_s"))
        form.addRow("  τ_sub:", tau_sub)
        bpf_lo = _dspin(0.01, 10.0, 0.5, 0.1, " Hz")
        bpf_lo.setToolTip(_make_tooltip("BPF lo cutoff",
            "Lower cutoff frequency for Butterworth bandpass filter (Hz).",
            src="PICalc.bpf_lo_hz"))
        form.addRow("  BPF lo:", bpf_lo)
        bpf_hi = _dspin(0.1, 20.0, 4.0, 0.5, " Hz")
        bpf_hi.setToolTip(_make_tooltip("BPF hi cutoff",
            "Upper cutoff frequency for Butterworth bandpass filter (Hz).",
            src="PICalc.bpf_hi_hz"))
        form.addRow("  BPF hi:", bpf_hi)

        # STEP 2
        lbl2 = QtWidgets.QLabel("── STEP2: AC estimator ──")
        lbl2.setStyleSheet(_lbl_sty); form.addRow(lbl2)
        s2 = QtWidgets.QComboBox(); s2.setStyleSheet(_ss_cb)
        s2.addItems(["2.1 EMA-RMS", "2.2 Win-RMS", "2.3 Peak-to-peak",
                     "2.4 Spectral band", "2.5 Harmonics"])
        s2.setToolTip(_make_tooltip("STEP2 method",
            "2.1 EMA-RMS: running RMS via EMA of x² (τ_ac) — firmware M1\n"
            "2.2 Win-RMS: windowed RMS over win_s seconds\n"
            "2.3 Peak-to-peak: (max−min)/2 over win_s seconds\n"
            "2.4 Spectral: FFT energy in band [f_HR ± delta_hz]\n"
            "2.5 Harmonics: FFT energy sum at n·f_HR (HPS-based)",
            src="PICalc.step2"))
        form.addRow("Method:", s2)
        tau_ac = _dspin(0.1, 30.0, 6.0, 0.5, " s")
        tau_ac.setToolTip(_make_tooltip("τ_ac",
            "EMA-RMS time constant (s). ISO 80601-2-61:2026 JJ.2 d) requires ≥6 s "
            "for SpO2 transfer standard. Firmware M1 default: 6.0 s.",
            src="PICalc.tau_ac_s"))
        form.addRow("  τ_ac:", tau_ac)
        win_s = _dspin(0.5, 30.0, 4.0, 0.5, " s")
        win_s.setToolTip(_make_tooltip("win_s",
            "Window length for Win-RMS, Peak-to-peak, and spectral methods (s).",
            src="PICalc.win_s"))
        form.addRow("  win_s:", win_s)
        hr_bpm = _dspin(30.0, 250.0, 70.0, 5.0, " bpm")
        hr_bpm.setToolTip(_make_tooltip("HR estimate",
            "Nominal HR for spectral methods 2.4 and 2.5 (bpm). "
            "In future this could be linked to the HR3 output.",
            src="PICalc.hr_bpm"))
        form.addRow("  HR:", hr_bpm)
        n_harm = QtWidgets.QSpinBox()
        n_harm.setRange(1, 8); n_harm.setValue(3); n_harm.setStyleSheet(_ss_spin)
        n_harm.setToolTip(_make_tooltip("N harmonics",
            "Number of harmonics to include in S2_HARMONICS (2.5).",
            src="PICalc.n_harm"))
        form.addRow("  N harm:", n_harm)

        # STEP 3
        lbl3 = QtWidgets.QLabel("── STEP3: DC denominator ──")
        lbl3.setStyleSheet(_lbl_sty); form.addRow(lbl3)
        s3 = QtWidgets.QComboBox(); s3.setStyleSheet(_ss_cb)
        s3.addItems(["3.1 EMA", "3.2 LPF", "3.3 Win-mean"])
        s3.setToolTip(_make_tooltip("STEP3 method",
            "3.1 EMA: EMA of raw signal (τ_norm) used as DC denominator — firmware M1\n"
            "3.2 LPF: 2nd-order Butterworth low-pass filter (lpf_fc)\n"
            "3.3 Win-mean: windowed mean of raw signal (win_norm_s)",
            src="PICalc.step3"))
        form.addRow("Method:", s3)
        tau_norm = _dspin(0.1, 30.0, 2.0, 0.5, " s")
        tau_norm.setToolTip(_make_tooltip("τ_norm",
            "EMA time constant for DC denominator (s). Firmware M1 default: 2.0 s.",
            src="PICalc.tau_norm_s"))
        form.addRow("  τ_norm:", tau_norm)
        lpf_fc = _dspin(0.01, 5.0, 0.4, 0.1, " Hz")
        lpf_fc.setToolTip(_make_tooltip("LPF fc",
            "2nd-order Butterworth LPF cutoff for DC denominator (Hz).\n"
            "Equivalent EMA τ ≈ 1/(2π·fc) ≈ 0.16/fc.\n"
            "Example: fc=0.08 Hz ≈ τ=2 s;  fc=0.4 Hz ≈ τ=0.4 s.",
            src="PICalc.lpf_fc_hz"))
        form.addRow("  LPF fc:", lpf_fc)
        win_norm = _dspin(0.5, 30.0, 4.0, 0.5, " s")
        win_norm.setToolTip(_make_tooltip("win_norm_s",
            "Window length for windowed mean DC denominator (s).",
            src="PICalc.win_norm_s"))
        form.addRow("  win_norm:", win_norm)

        apply_btn = QtWidgets.QPushButton(f"APPLY {name}")
        apply_btn.setStyleSheet(ACTION_BUTTON_STYLE)
        apply_btn.setToolTip(_make_tooltip(f"Apply {name}",
            "Apply configuration changes and reset pipeline state. "
            "Plot buffers are cleared so the comparison starts clean."))
        form.addRow("", apply_btn)

        preset_btn = QtWidgets.QPushButton("FIRMWARE PRESET")
        preset_btn.setStyleSheet(ACTION_BUTTON_STYLE)
        preset_btn.setToolTip(_make_tooltip("Firmware preset",
            "Load the firmware SpO2 algorithm parameters into this instance:\n"
            "  STEP1: EMA subtract  τ_sub = 2.0 s\n"
            "  STEP2: EMA-RMS       τ_ac  = 6.0 s\n"
            "  STEP3: EMA           τ_norm = 2.0 s\n"
            "spo2_a/b are read from the last received $CFG frame."))
        form.addRow("", preset_btn)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        tab_widget = QtWidgets.QWidget()
        tab_lay = QtWidgets.QVBoxLayout(tab_widget)
        tab_lay.setContentsMargins(0, 0, 0, 0)
        tab_lay.setSpacing(0)
        header = QtWidgets.QLabel(f"  Instance {name}")
        header.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: bold; padding: 4px;"
            f" background: #1E1E1E;")
        tab_lay.addWidget(header)
        tab_lay.addWidget(scroll)

        cfg = {
            'widget': tab_widget, 'form': form, 's1': s1, 's2': s2, 's3': s3,
            'tau_sub': tau_sub, 'bpf_lo': bpf_lo, 'bpf_hi': bpf_hi,
            'tau_ac':  tau_ac,  'win_s':  win_s,  'hr_bpm': hr_bpm, 'n_harm': n_harm,
            'tau_norm': tau_norm, 'lpf_fc': lpf_fc, 'win_norm': win_norm,
        }
        calc_ref = self.calc_a if name == "A" else self.calc_b
        apply_btn.clicked.connect(lambda: self._apply_config(cfg, calc_ref))
        preset_btn.clicked.connect(lambda: self._apply_firmware_preset(cfg, calc_ref))
        s1.currentIndexChanged.connect(lambda _: self._refresh_param_state(cfg))
        s2.currentIndexChanged.connect(lambda _: self._refresh_param_state(cfg))
        s3.currentIndexChanged.connect(lambda _: self._refresh_param_state(cfg))
        return cfg

    # ── config application ────────────────────────────────────────────────────

    def _apply_config(self, cfg, calc):
        _s1 = [PICalc.S1_EMA,     PICalc.S1_BPF,     PICalc.S1_NONE]
        _s2 = [PICalc.S2_EMA_RMS, PICalc.S2_WIN_RMS, PICalc.S2_PEAKPK,
               PICalc.S2_SPECTRAL, PICalc.S2_HARMONICS]
        _s3 = [PICalc.S3_EMA,     PICalc.S3_LPF,     PICalc.S3_WIN_MEAN]
        calc.step1       = _s1[cfg['s1'].currentIndex()]
        calc.tau_sub     = cfg['tau_sub'].value()
        calc.bpf_lo      = cfg['bpf_lo'].value()
        calc.bpf_hi      = cfg['bpf_hi'].value()
        calc.step2       = _s2[cfg['s2'].currentIndex()]
        calc.tau_ac      = cfg['tau_ac'].value()
        calc.win_s       = cfg['win_s'].value()
        calc.hr_bpm      = cfg['hr_bpm'].value()
        calc.n_harmonics = cfg['n_harm'].value()
        calc.step3       = _s3[cfg['s3'].currentIndex()]
        calc.tau_norm    = cfg['tau_norm'].value()
        calc.lpf_fc      = cfg['lpf_fc'].value()
        calc.win_norm_s  = cfg['win_norm'].value()
        calc._fs = 0.0  # force reconfigure on next sample
        # clear all plot buffers so comparison starts fresh
        self._t_buf.clear(); self._ir_buf.clear()
        self._dc_sub_a.clear(); self._dc_sub_b.clear()
        self._ac_t_a.clear();   self._ac_t_b.clear()
        self._pi_ir_a.clear();  self._pi_ir_b.clear()
        self._r_a.clear();      self._r_b.clear()
        self._spo2_a.clear();   self._spo2_b.clear()
        self._t0_us = None

    def _apply_firmware_preset(self, cfg, calc):
        """Load firmware SpO2 algorithm parameters into cfg widgets and apply."""
        cfg['s1'].setCurrentIndex(0)       # S1_EMA
        cfg['s2'].setCurrentIndex(0)       # S2_EMA_RMS
        cfg['s3'].setCurrentIndex(0)       # S3_EMA
        cfg['tau_sub'].setValue(2.0)
        cfg['tau_ac'].setValue(6.0)
        cfg['tau_norm'].setValue(2.0)
        self._refresh_param_state(cfg)
        self._apply_config(cfg, calc)
        # sync spo2 coeffs from last $CFG
        mon = getattr(self, 'main_monitor', None)
        kv  = getattr(mon, '_last_cfg', {}) if mon is not None else {}
        self._sync_spo2_coeffs(kv)

    def _sync_spo2_coeffs(self, kv):
        """Read spo2_a/spo2_b from a parsed $CFG kv dict and apply to both PICalc instances."""
        try:
            a = float(kv.get("spo2a", PICalc.DEFAULT_SPO2_A))
            b = float(kv.get("spo2b", PICalc.DEFAULT_SPO2_B))
        except (ValueError, TypeError):
            return
        self.calc_a.spo2_a = a;  self.calc_a.spo2_b = b
        self.calc_b.spo2_a = a;  self.calc_b.spo2_b = b

    def _refresh_param_state(self, cfg):
        """Enable/disable parameter widgets based on current STEP combo selections."""
        form   = cfg['form']
        s1_idx = cfg['s1'].currentIndex()  # 0=EMA, 1=BPF, 2=None
        s2_idx = cfg['s2'].currentIndex()  # 0=EMA_RMS,1=WIN_RMS,2=PEAKPK,3=SPECTRAL,4=HARMONICS
        s3_idx = cfg['s3'].currentIndex()  # 0=EMA, 1=LPF, 2=WIN_MEAN

        def _set(widget, enabled):
            widget.setEnabled(enabled)
            lbl = form.labelForField(widget)
            if lbl: lbl.setEnabled(enabled)

        # STEP1
        _set(cfg['tau_sub'], s1_idx == 0)
        _set(cfg['bpf_lo'],  s1_idx == 1)
        _set(cfg['bpf_hi'],  s1_idx == 1)
        # STEP2
        _set(cfg['tau_ac'], s2_idx == 0)
        _set(cfg['win_s'],  s2_idx in (1, 2))
        _set(cfg['hr_bpm'], s2_idx in (3, 4))
        _set(cfg['n_harm'], s2_idx == 4)
        # STEP3
        _set(cfg['tau_norm'], s3_idx == 0)
        _set(cfg['lpf_fc'],   s3_idx == 1)
        _set(cfg['win_norm'], s3_idx == 2)

    # ── data feed (called per-sample from PPGMonitor drain loop) ──────────────

    def feed_sample(self, ir, red, fs, ts_us):
        """Feed one sample. ir/red = ADC counts, ts_us = timestamp in µs."""
        if self._paused or self._offline_mode:
            return
        if self._t0_us is None:
            self._t0_us = ts_us
        t = (ts_us - self._t0_us) * 1e-6

        self.calc_a.update(ir, red, fs)
        self.calc_b.update(ir, red, fs)

        self._t_buf.append(t)
        self._ir_buf.append(float(ir))
        self._dc_sub_a.append(self.calc_a.ac_t_ir)
        self._dc_sub_b.append(self.calc_b.ac_t_ir)
        self._ac_t_a.append(self.calc_a.ac_r_ir)
        self._ac_t_b.append(self.calc_b.ac_r_ir)
        self._pi_ir_a.append(self.calc_a.pi_ir)
        self._pi_ir_b.append(self.calc_b.pi_ir)
        self._r_a.append(self.calc_a.R)
        self._r_b.append(self.calc_b.R)
        self._spo2_a.append(self.calc_a.spo2)
        self._spo2_b.append(self.calc_b.spo2)

    # ── render (called from PPGMonitor render tick) ───────────────────────────

    def update_plots(self):
        if self._paused or not self._t_buf:
            return
        t = np.array(self._t_buf)
        t_end = t[-1]

        self.curve_sig.setData(t,    np.array(self._ir_buf))
        self.curve_act_a.setData(t, np.array(self._dc_sub_a))
        self.curve_act_b.setData(t, np.array(self._dc_sub_b))
        self.curve_ac_a.setData(t, np.array(self._ac_t_a))
        self.curve_ac_b.setData(t, np.array(self._ac_t_b))
        self.curve_pi_a.setData(t, np.array(self._pi_ir_a))
        self.curve_pi_b.setData(t, np.array(self._pi_ir_b))
        self.curve_r_a.setData(t,    np.array(self._r_a))
        self.curve_r_b.setData(t,    np.array(self._r_b))
        self.curve_spo2_a.setData(t, np.array(self._spo2_a))
        self.curve_spo2_b.setData(t, np.array(self._spo2_b))
        self.p_sig.setXRange(max(0.0, t_end - self._PLOT_WIN_S), t_end, padding=0)
        self._update_val_table()

    def _update_val_table(self):
        a, b = self.calc_a, self.calc_b
        rows = [
            # (val_a, val_b, fmt)
            (a.ac_r_red, b.ac_r_red, ".1f"),
            (a.dc_r_red, b.dc_r_red, ".1f"),
            (a.ac_r_ir,  b.ac_r_ir,  ".1f"),
            (a.dc_r_ir,  b.dc_r_ir,  ".1f"),
            (a.pi_red,   b.pi_red,   ".3f"),
            (a.pi_ir,    b.pi_ir,    ".3f"),
            (a.R,        b.R,        ".4f"),
            (a.spo2,     b.spo2,     ".1f"),
        ]
        for row, (va, vb, fmt) in enumerate(rows):
            for col, v in ((0, va), (1, vb)):
                item = QtWidgets.QTableWidgetItem(format(v, fmt))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self._val_table.setItem(row, col, item)

    # ── help ──────────────────────────────────────────────────────────────────

    def _show_help(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("PILAB — Help")
        dlg.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        dlg.resize(900, 800)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        title = QtWidgets.QLabel("PILAB — Four plots explained")
        title.setStyleSheet("font-size: 40px; font-weight: bold; color: #FFD070;")
        lay.addWidget(title)

        _HTML = """
<style>
  body  { font-size: 30px; color: #D0D0D0; }
  h3    { font-size: 32px; color: #FFD070; margin-bottom: 2px; margin-top: 12px; }
  p     { margin: 2px 0 6px 0; }
  code  { color: #FFDD44; }
  .formula { color: #88DDFF; font-style: italic; }
</style>
<body>
<p>Each plot shows the output of one stage of the 3-step PI pipeline,
for instances <b style="color:#FF8800;">A</b> and <b style="color:#44AAFF;">B</b> side by side.</p>

<h3>Plot 1 — IR signal + DC_sub</h3>
<p>The raw <code>led1_sub</code> (IR, grey) overlaid with the DC estimate from STEP1.
STEP1 tracks the slow baseline so it can be subtracted to isolate the AC pulse.
Use this plot to judge whether the DC tracker follows the baseline correctly
(too fast → distorts the pulse; too slow → leaves residual drift).</p>

<h3>Plot 2 — AC_r [ADC counts]</h3>
<p>The AC amplitude estimated by STEP2, in raw ADC counts.
This is the "pulse height" after AC extraction (STEP1):
EMA-RMS computes <span class="formula">√EMA(x²)</span>,
Peak-to-peak computes <span class="formula">(max−min)/2</span>,
spectral methods extract energy at the heart-rate fundamental.
Use this to compare estimators — they should agree on a clean signal
and diverge differently on noise.</p>

<h3>Plot 3 — PI_ir [%]</h3>
<p>The Perfusion Index for the IR channel:
<span class="formula">PI_ir = (AC_ir / DC_ir) × 100 %</span>.
The DC denominator comes from STEP3 (independent of STEP1).
A high PI means a strong, well-perfused signal;
a low PI (&lt; 0.3 %) indicates poor contact or weak perfusion.
This is the main clinical quality indicator.</p>

<h3>Plot 4 — R = PI_red / PI_ir</h3>
<p>The modulation ratio used for SpO2:
<span class="formula">R = (AC_red/DC_red) / (AC_ir/DC_ir)</span>.
Different pipeline configurations that produce the same PI_ir
may still produce different R values — and therefore different SpO2 readings.
Use this plot to evaluate how sensitive R is to the choice of estimator.</p>
</body>"""

        txt = QtWidgets.QTextEdit()
        txt.setReadOnly(True)
        txt.setHtml(_HTML)
        txt.setStyleSheet(
            "QTextEdit { background: #1A1A1A; color: #D0D0D0; "
            "border: 1px solid #333; font-size: 15px; }")
        lay.addWidget(txt, stretch=1)

        btn_close = QtWidgets.QPushButton("Close")
        btn_close.setStyleSheet(ACTION_BUTTON_STYLE)
        btn_close.clicked.connect(dlg.accept)
        lay.addWidget(btn_close, alignment=QtCore.Qt.AlignRight)

        dlg.exec_()

    # ── offline mode ──────────────────────────────────────────────────────────

    def _on_load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            data = np.genfromtxt(path, delimiter=',', names=True)
        except Exception as exc:
            self.statusBar().showMessage(f"CSV load error: {exc}")
            return
        if data is None or data.ndim == 0 or len(data) == 0:
            self.statusBar().showMessage("Empty or unreadable CSV file.")
            return
        cols = data.dtype.names
        ir_col  = next((c for c in cols if c.upper() in ('LED1_SUB', 'IR')),  None)
        red_col = next((c for c in cols if c.upper() in ('LED2_SUB', 'RED')), None)
        ts_col  = next((c for c in cols if any(k in c.upper()
                        for k in ('TIME', 'TS_US', 'TIMESTAMP'))), None)
        if ir_col is None or red_col is None:
            self.statusBar().showMessage(
                f"CSV missing LED1_SUB/LED2_SUB columns. Found: {cols}")
            return

        self._offline_mode = True
        self.btn_live.setEnabled(True)
        self.btn_load.setEnabled(False)
        self.calc_a.reset(); self.calc_b.reset()
        self._t_buf.clear(); self._ir_buf.clear()
        self._dc_sub_a.clear(); self._dc_sub_b.clear()
        self._ac_t_a.clear();   self._ac_t_b.clear()
        self._pi_ir_a.clear();  self._pi_ir_b.clear()
        self._r_a.clear();      self._r_b.clear()
        self._t0_us = None

        n   = len(data)
        fs  = SPO2_RECEIVED_FS
        t0  = float(data[ts_col][0]) if ts_col else 0.0
        for i in range(n):
            ir  = float(data[ir_col][i])
            red = float(data[red_col][i])
            ts  = float(data[ts_col][i]) if ts_col else i / fs * 1e6
            if self._t0_us is None:
                self._t0_us = ts
            t = (ts - self._t0_us) * 1e-6
            self.calc_a.update(ir, red, fs)
            self.calc_b.update(ir, red, fs)
            self._t_buf.append(t); self._ir_buf.append(ir)
            self._dc_sub_a.append(self.calc_a.dc_sub_ir)
            self._dc_sub_b.append(self.calc_b.dc_sub_ir)
            self._ac_t_a.append(self.calc_a.ac_r_ir)
            self._ac_t_b.append(self.calc_b.ac_r_ir)
            self._pi_ir_a.append(self.calc_a.pi_ir)
            self._pi_ir_b.append(self.calc_b.pi_ir)
            self._r_a.append(self.calc_a.R)
            self._r_b.append(self.calc_b.R)

        self.update_plots()
        if self._t_buf:
            t_arr = np.array(self._t_buf)
            self.p_sig.setXRange(t_arr[0], t_arr[-1], padding=0.02)
        self.statusBar().showMessage(f"Offline: {path}  ({n} samples @ {fs:.0f} Hz)")

    def _on_go_live(self):
        self._offline_mode = False
        self._t0_us = None
        self.calc_a.reset(); self.calc_b.reset()
        self.btn_live.setEnabled(False)
        self.btn_load.setEnabled(True)
        self._t_buf.clear(); self._ir_buf.clear()
        self._dc_sub_a.clear(); self._dc_sub_b.clear()
        self._ac_t_a.clear();   self._ac_t_b.clear()
        self._pi_ir_a.clear();  self._pi_ir_b.clear()
        self._r_a.clear();      self._r_b.clear()
        self.statusBar().showMessage(_MOUSE_HINT)

    def _toggle_pause(self):
        self._paused = self.btn_pause.isChecked()

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PILabWindow/geometry", self.saveGeometry())
        for inst, cfg in (("A", self._cfg_a), ("B", self._cfg_b)):
            pfx = f"PILabWindow/{inst}"
            s.setValue(f"{pfx}/s1",      cfg['s1'].currentIndex())
            s.setValue(f"{pfx}/s2",      cfg['s2'].currentIndex())
            s.setValue(f"{pfx}/s3",      cfg['s3'].currentIndex())
            s.setValue(f"{pfx}/tau_sub", cfg['tau_sub'].value())
            s.setValue(f"{pfx}/bpf_lo",  cfg['bpf_lo'].value())
            s.setValue(f"{pfx}/bpf_hi",  cfg['bpf_hi'].value())
            s.setValue(f"{pfx}/tau_ac",  cfg['tau_ac'].value())
            s.setValue(f"{pfx}/win_s",   cfg['win_s'].value())
            s.setValue(f"{pfx}/hr_bpm",  cfg['hr_bpm'].value())
            s.setValue(f"{pfx}/n_harm",  cfg['n_harm'].value())
            s.setValue(f"{pfx}/tau_norm",cfg['tau_norm'].value())
            s.setValue(f"{pfx}/lpf_fc",  cfg['lpf_fc'].value())
            s.setValue(f"{pfx}/win_norm",cfg['win_norm'].value())
        if self.main_monitor is not None:
            self.main_monitor.btn_pilab.setChecked(False)
            self.main_monitor.pilab_window = None
        super().closeEvent(event)


class PythonTimingWindow(QtWidgets.QMainWindow):
    """PYTHON TIMING — real-time performance diagnostics for the pulsenest_lab.py script.

    Displays mean and max execution time (ms) for each measured component:
      Section A — Tick timers: _process_frames_tick() (serial+UDP drain) and _refresh_plots_tick() total.
      Section B — Algorithms: per-window update_algorithms() time (runs in drain, 20ms budget).
      Section C — Render: per-window update_plots() time (runs in render, 200ms budget).

    Stats are computed over a rolling window of the last 50 measurements.
    The status bar reflects the drain timer vs its 20ms budget.
    """

    _SERIAL_TICK_BUDGET_MS  = 20.0    # ms — timer period → _process_frames_tick()
    _PLOTS_TICK_BUDGET_MS = 200.0   # ms — timer period → _refresh_plots_tick()
    _WARN_PCT         = 75.0    # % — warning threshold
    _CRIT_PCT         = 100.0   # % — critical threshold

    # (key, display name, budget_ms)
    _TICK_ROWS = [
        ("drain",           "[_py_timing['drain']]          _process_frames_tick()",           _SERIAL_TICK_BUDGET_MS),
        ("drain_interval",  "[_last_drain_t]                _process_frames_tick() interval",  _SERIAL_TICK_BUDGET_MS * 2),
        ("render",          "[_py_timing['render']]         _refresh_plots_tick()",                  _PLOTS_TICK_BUDGET_MS),
        ("render_interval", "[_last_render_t]               _refresh_plots_tick() interval",         _PLOTS_TICK_BUDGET_MS * 2),
    ]
    _SERIAL_TICK_ROWS = [  # algorithms timed inside _process_frames_tick()
        ("algo_spo2lab",  "[_py_timing['algo_spo2lab']]   SPO2LAB   |  SpO2LabWindow.update_algorithms()",  _SERIAL_TICK_BUDGET_MS),
        ("algo_spo2test", "[_py_timing['algo_spo2test']]  SPO2TEST  |  SpO2TestWindow.update_algorithms()", _SERIAL_TICK_BUDGET_MS),
        ("algo_hr2test",  "[_py_timing['algo_hr2test']]   HR2TEST   |  HR2TestWindow.update_algorithms()",  _SERIAL_TICK_BUDGET_MS),
    ]
    _PLOTS_TICK_ROWS = [  # renderers timed inside _refresh_plots_tick()
        ("plot_ppgplots", "[_py_timing['plot_ppgplots']]  PPGPLOTS  |  PPGPlotsWindow.update_plots()",    _PLOTS_TICK_BUDGET_MS),
        ("plot_signals",  "[_py_timing['plot_signals']]   SIGNALS   |  PPGSignalsWindow.update_plots()",  _PLOTS_TICK_BUDGET_MS),
        ("plot_results",  "[_py_timing['plot_results']]   RESULTS   |  AlgoResultsWindow.update_plots()", _PLOTS_TICK_BUDGET_MS),
        ("plot_hrlab",    "[_py_timing['plot_hrlab']]     HR2LAB    |  HRLabWindow.update_plots()",       _PLOTS_TICK_BUDGET_MS),
        ("plot_spo2lab",  "[_py_timing['plot_spo2lab']]   SPO2LAB   |  SpO2LabWindow.update_plots()",     _PLOTS_TICK_BUDGET_MS),
        ("plot_hr3lab",   "[_py_timing['plot_hr3lab']]    HR3LAB    |  HR3LabWindow.update_plots()",      _PLOTS_TICK_BUDGET_MS),
        ("plot_spo2test", "[_py_timing['plot_spo2test']]  SPO2TEST  |  SpO2TestWindow.update_plots()",    _PLOTS_TICK_BUDGET_MS),
        ("plot_hr1test",  "[_py_timing['plot_hr1test']]   HR1TEST * |  HR1TestWindow.update_plots()",     _PLOTS_TICK_BUDGET_MS),
        ("plot_hr2test",  "[_py_timing['plot_hr2test']]   HR2TEST   |  HR2TestWindow.update_plots()",     _PLOTS_TICK_BUDGET_MS),
        ("plot_hr3test",  "[_py_timing['plot_hr3test']]   HR3TEST   |  HR3TestWindow.update_plots()",     _PLOTS_TICK_BUDGET_MS),
    ]
    # (key, display name) — 'Max' column repurposed as count; queue=instantaneous, others=since connect
    _GAP_ROWS = [
        ("gap_queue",    "[PPGMonitor._queue_size_buf]          Queue size (frames)"),
        ("gap_B",        "[PPGMonitor._gaps_B]                  Ingestion"),
        ("gap_hr1test",  "[PPGMonitor.hr1test_calc.gap_count]   HR1TEST"),
        ("gap_hr3lab",   "[PPGMonitor.hr3_calc.gap_count]       HR3LAB"),
        ("gap_hr3test",  "[PPGMonitor.hr3test_calc.gap_count]   HR3TEST"),
        ("gap_spo2lab",  "[SpO2LabWindow.gap_count]             SPO2LAB"),
        ("gap_spo2test", "[SpO2TestWindow.gap_count]            SPO2TEST"),
        ("gap_hr2test",  "[HR2TestWindow.gap_count]             HR2TEST"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PYTHON TIMING — Script Performance")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value(
            "PythonTimingWindow/geometry")
        if geom: self.restoreGeometry(geom)
        else:    self.resize(560, 760)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Status bar (drain budget)
        self._lbl_status = QtWidgets.QLabel("Waiting for data…")
        self._lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_status.setStyleSheet(
            "background: #1A2A1A; color: #888888; font-size: 13px; "
            "font-weight: bold; padding: 4px; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip(
            "Overall timing status",
            f"Shows the worst row across the entire table.\n"
            f"GRAY:   all rows within {self._WARN_PCT:.0f}% of their budget (ALL OK).\n"
            f"ORANGE: worst row at {self._WARN_PCT:.0f}–{self._CRIT_PCT:.0f}% of budget (TIGHT).\n"
            f"RED:    worst row exceeded budget (OVER BUDGET)."))
        vbox.addWidget(self._lbl_status)

        n_rows = (1 + len(self._TICK_ROWS) + 1 + len(self._SERIAL_TICK_ROWS) +
                  1 + len(self._PLOTS_TICK_ROWS) + 1 + 1 + len(self._GAP_ROWS))
        self._table = QtWidgets.QTableWidget(n_rows, 5)
        self._table.setHorizontalHeaderLabels(["Component", "Mean (ms)", "Budget (ms)", "Max (ms)", "% Budget"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.ContiguousSelection)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in (1, 2, 3, 4):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeToContents)
        self._table.setToolTip(_make_tooltip(
            "Python timing table",
            "Execution time per component measured with time.perf_counter().\n"
            "Stats computed over the last 50 measurements.\n"
            "Color: white < 75% of budget, orange 75–100%, red > 100%."))

        self._row_map     = {}  # key → physical row index (timing rows)
        self._gap_row_map = {}  # key → physical row index (gap rows)

        def _add_section(phys_row, label):
            self._table.setSpan(phys_row, 0, 1, 5)
            item = QtWidgets.QTableWidgetItem(f"  {label}")
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            item.setBackground(QtGui.QColor("#1E2E3E"))
            item.setForeground(QtGui.QColor("#88BBDD"))
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self._table.setItem(phys_row, 0, item)
            return phys_row + 1

        def _add_data_rows(phys_row, row_defs):
            for key, name, budget_ms in row_defs:
                item = QtWidgets.QTableWidgetItem(f"  {name}")
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                self._table.setItem(phys_row, 0, item)
                budget_item = QtWidgets.QTableWidgetItem(f"{budget_ms:.0f}")
                budget_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                budget_item.setForeground(QtGui.QColor("#888888"))
                self._table.setItem(phys_row, 2, budget_item)
                for col in (1, 3, 4):
                    cell = QtWidgets.QTableWidgetItem("—")
                    cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    self._table.setItem(phys_row, col, cell)
                self._row_map[key] = phys_row
                phys_row += 1
            return phys_row

        def _add_gap_rows(phys_row, row_defs):
            # Column sub-header
            _col_labels = {0: "Component", 3: "Count"}
            for col in (0, 1, 2, 3, 4):
                text = _col_labels.get(col, "—")
                cell = QtWidgets.QTableWidgetItem(f"  {text}" if col == 0 else text)
                cell.setFlags(QtCore.Qt.ItemIsEnabled)
                cell.setTextAlignment(
                    (QtCore.Qt.AlignLeft if col == 0 else QtCore.Qt.AlignRight) | QtCore.Qt.AlignVCenter)
                font = cell.font(); font.setBold(True); cell.setFont(font)
                cell.setForeground(QtGui.QColor("#AAAAAA"))
                cell.setBackground(QtGui.QColor("#1A1A1A"))
                self._table.setItem(phys_row, col, cell)
            phys_row += 1
            for key, name in row_defs:
                item = QtWidgets.QTableWidgetItem(f"  {name}")
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                self._table.setItem(phys_row, 0, item)
                for col in (1, 2, 3, 4):
                    cell = QtWidgets.QTableWidgetItem("—")
                    cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    cell.setForeground(QtGui.QColor("#888888"))
                    self._table.setItem(phys_row, col, cell)
                self._gap_row_map[key] = phys_row
                phys_row += 1
            return phys_row

        r = 0
        r = _add_section(r, "Tick timers")
        r = _add_data_rows(r, self._TICK_ROWS)
        r = _add_section(r, f"Algorithms — update_algorithms()  (budget {self._SERIAL_TICK_BUDGET_MS:.0f} ms)")
        r = _add_data_rows(r, self._SERIAL_TICK_ROWS)
        r = _add_section(r, f"Render — update_plots()  (budget {self._PLOTS_TICK_BUDGET_MS:.0f} ms)")
        r = _add_data_rows(r, self._PLOTS_TICK_ROWS)
        r = _add_section(r, "Sample gaps  —  lost samples since connect")
        r = _add_gap_rows(r, self._GAP_ROWS)

        vbox.addWidget(self._table)

        # Last update label
        self._lbl_last = QtWidgets.QLabel("Last update: —")
        self._lbl_last.setAlignment(QtCore.Qt.AlignRight)
        self._lbl_last.setStyleSheet("color: #888888; font-size: 11px;")
        vbox.addWidget(self._lbl_last)

    def update_timing(self, stats, gaps=None):
        """Update table from stats dict: {key: (mean_ms, max_ms)} and gaps dict: {key: int}.
        Called periodically from PPGMonitor._refresh_plots_tick().
        """
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")

        all_rows = self._TICK_ROWS + self._SERIAL_TICK_ROWS + self._PLOTS_TICK_ROWS
        worst_pct   = 0.0
        worst_label = ""

        for key, label, budget_ms in all_rows:
            val = stats.get(key)
            phys_row = self._row_map.get(key)
            if phys_row is None:
                continue
            if val is None:
                # Window is closed — reset to "—"
                for col in (1, 3, 4):
                    self._table.item(phys_row, col).setText("—")
                    self._table.item(phys_row, col).setForeground(QtGui.QColor("#888888"))
                continue
            mean_ms, max_ms = val
            pct = (max_ms / budget_ms * 100.0) if budget_ms > 0 else 0.0
            self._table.item(phys_row, 1).setText(f"{mean_ms:.2f}")
            self._table.item(phys_row, 3).setText(f"{max_ms:.2f}")
            self._table.item(phys_row, 4).setText(f"{pct:.1f}%")
            if pct > self._CRIT_PCT:
                colour = "#FF4444"
            elif pct > self._WARN_PCT:
                colour = "#FFA500"
            else:
                colour = "#E0E0E0"
            for col in (1, 3, 4):
                self._table.item(phys_row, col).setForeground(QtGui.QColor(colour))
            if pct > worst_pct:
                worst_pct   = pct
                worst_label = label

        # Status bar — global worst row
        if worst_pct > self._CRIT_PCT:
            self._lbl_status.setText(f"OVER BUDGET  —  {worst_label}  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #3A0000; color: #FF4444; font-size: 15px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")
        elif worst_pct > self._WARN_PCT:
            self._lbl_status.setText(f"TIGHT  —  {worst_label}  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #2A1A00; color: #FFA500; font-size: 15px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")
        else:
            self._lbl_status.setText(f"ALL OK  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #1A1A1A; color: #E0E0E0; font-size: 15px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")

        # Gap rows
        if gaps is not None:
            for key, _ in self._GAP_ROWS:
                val      = gaps.get(key)
                phys_row = self._gap_row_map.get(key)
                if phys_row is None:
                    continue
                if val is None:
                    self._table.item(phys_row, 3).setText("—")
                    self._table.item(phys_row, 3).setForeground(QtGui.QColor("#888888"))
                elif key == "gap_queue":
                    # val is (mean, max) tuple
                    mean_q, max_q = val
                    self._table.item(phys_row, 1).setText(f"{mean_q:.1f}")
                    self._table.item(phys_row, 3).setText(str(max_q))
                    colour = "#FF4444" if max_q > 50 else "#FFA500" if max_q > 10 else "#E0E0E0"
                    self._table.item(phys_row, 1).setForeground(QtGui.QColor(colour))
                    self._table.item(phys_row, 3).setForeground(QtGui.QColor(colour))
                else:
                    self._table.item(phys_row, 3).setText(str(val))
                    colour = "#FF4444" if val > 0 else "#E0E0E0"
                    self._table.item(phys_row, 3).setForeground(QtGui.QColor(colour))

        self._lbl_last.setText(f"Last update: {now}  (rolling 50 samples)")

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PythonTimingWindow/geometry", self.saveGeometry())
        if hasattr(self, 'main_monitor') and self.main_monitor is not None:
            self.main_monitor.btn_python_timing.setChecked(False)
            self.main_monitor.python_timing_window = None
        super().closeEvent(event)


class Esp32TimingWindow(QtWidgets.QMainWindow):
    """Timing diagnostics window — shows per-algorithm CPU time from $TIMING frames.

    Two sections:
      Task A (real-time 500 Hz): Budget % = max / 2000 µs × 100
      Task B/C (async ~2 Hz):    CPU load % = mean / 500000 µs × 100
    A status bar reflects the Task A cycle_max vs the 2 ms budget.
    """

    _BUDGET_US    = 2000     # µs — 1 sample period at 500 Hz (Task A budget)
    _WARN_US      = 1800     # µs — 10% margin warning threshold
    _ASYNC_PERIOD = 500_000  # µs — HR2/HR3 compute period (0.5 s at 500 Hz)

    # Row definitions: (display name, section)  section 0=Task A, section 1=Task B/C
    _ROW_DEFS = [
        ("HR1",              0),
        ("HR2 fast path",    0),
        ("HR3 fast path",    0),
        ("SpO2",             0),
        ("Cycle (SPI+all)",  0),
        ("HR2 autocorr",     1),
        ("HR3 FFT+HPS",      1),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ESP32 TIMING — CPU Budget & Load")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("Esp32TimingWindow/geometry")
        if geom: self.restoreGeometry(geom)
        else:    self.resize(640, 980)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Status indicator (Task A cycle)
        self._lbl_status = QtWidgets.QLabel("Waiting for $TIMING frame…")
        self._lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_status.setStyleSheet(
            "background: #1A2A1A; color: #888888; font-size: 13px; "
            "font-weight: bold; padding: 4px; border-radius: 4px;")
        self._lbl_status.setToolTip(_make_tooltip(
            "Task A cycle status",
            f"GREEN: cycle_max < {self._WARN_US} µs (safe).\n"
            f"ORANGE: {self._WARN_US}–{self._BUDGET_US} µs (tight — 10% margin).\n"
            f"RED: cycle_max > {self._BUDGET_US} µs (OVER BUDGET — may miss samples at 500 Hz)."))
        vbox.addWidget(self._lbl_status)

        # Table: section header rows + data rows
        # Physical row layout: header_A, 5 data rows, header_BC, 2 data rows = 9 rows total
        self._table = QtWidgets.QTableWidget(9, 4)
        self._table.setHorizontalHeaderLabels(["Algorithm", "Mean (µs)", "Max (µs)", "Metric"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.ContiguousSelection)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in (1, 2, 3):
            self._table.horizontalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

        # Row 0: Task A section header
        self._table.setSpan(0, 0, 1, 4)
        hdr_a = QtWidgets.QTableWidgetItem("  Task A — Real-time 500 Hz  (Budget % = max / 2000 µs)")
        hdr_a.setFlags(QtCore.Qt.ItemIsEnabled)
        hdr_a.setBackground(QtGui.QColor("#1E2E3E"))
        hdr_a.setForeground(QtGui.QColor("#88BBDD"))
        hdr_a.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self._table.setItem(0, 0, hdr_a)

        # Rows 1–5: Task A data rows
        self._data_rows_A = [1, 2, 3, 4, 5]  # physical rows for HR1, HR2fp, HR3fp, SpO2, Cycle
        for phys_row, (name, _) in zip(self._data_rows_A, self._ROW_DEFS[:5]):
            item = QtWidgets.QTableWidgetItem(f"  {name}")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self._table.setItem(phys_row, 0, item)
            for col in (1, 2, 3):
                cell = QtWidgets.QTableWidgetItem("—")
                cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self._table.setItem(phys_row, col, cell)

        # Row 6: Task B/C section header
        self._table.setSpan(6, 0, 1, 4)
        hdr_bc = QtWidgets.QTableWidgetItem("  Task B/C — Async ~2 Hz  (CPU load % = mean / 500 000 µs)")
        hdr_bc.setFlags(QtCore.Qt.ItemIsEnabled)
        hdr_bc.setBackground(QtGui.QColor("#1E2E3E"))
        hdr_bc.setForeground(QtGui.QColor("#88BBDD"))
        hdr_bc.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self._table.setItem(6, 0, hdr_bc)

        # Rows 7–8: Task B/C data rows
        self._data_rows_BC = [7, 8]  # physical rows for HR2 compute, HR3 compute
        for phys_row, (name, _) in zip(self._data_rows_BC, self._ROW_DEFS[5:]):
            item = QtWidgets.QTableWidgetItem(f"  {name}")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self._table.setItem(phys_row, 0, item)
            for col in (1, 2, 3):
                cell = QtWidgets.QTableWidgetItem("—")
                cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self._table.setItem(phys_row, col, cell)

        self._table.setToolTip(_make_tooltip(
            "Timing table",
            "Execution time per algorithm, measured with esp_timer_get_time() (1 µs resolution).\n"
            "Task A (real-time): Budget % = max / 2000 µs × 100. Cycle includes SPI + all fast paths.\n"
            "Task B/C (async): CPU load % = mean / 500 000 µs × 100 (compute time / invocation period)."))
        vbox.addWidget(self._table)

        # Stack free (Task A)
        self._lbl_stack = QtWidgets.QLabel("Stack free: —")
        self._lbl_stack.setAlignment(QtCore.Qt.AlignRight)
        self._lbl_stack.setStyleSheet("color: #888888; font-size: 22px;")
        self._lbl_stack.setToolTip(_make_tooltip(
            "Stack free",
            "Remaining stack of the incunest_afe4490 FreeRTOS task (Task A), in 4-byte words "
            "(uxTaskGetStackHighWaterMark). Low values risk stack overflow."))
        vbox.addWidget(self._lbl_stack)

        # ── FreeRTOS task list section ──────────────────────────────────────────
        lbl_tasks_hdr = QtWidgets.QLabel("  FreeRTOS Tasks (avg CPU since boot)")
        lbl_tasks_hdr.setStyleSheet(
            "background: #1E2E3E; color: #88BBDD; font-size: 22px; font-weight: bold; padding: 3px;")
        lbl_tasks_hdr.setToolTip(_make_tooltip(
            "FreeRTOS task list",
            "CPU% = ulRunTimeCounter / total_time × 100 (cumulative average since boot).\n"
            "Populated from $TASK frames emitted by the firmware after each $TIMING frame.\n"
            "Stack free: uxTaskGetStackHighWaterMark in 4-byte words."))
        vbox.addWidget(lbl_tasks_hdr)

        self._tasks_table = QtWidgets.QTableWidget(0, 3)
        self._tasks_table.setHorizontalHeaderLabels(["Task", "CPU %", "Stack free (bytes)"])
        self._tasks_table.verticalHeader().setVisible(False)
        self._tasks_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._tasks_table.setSelectionMode(QtWidgets.QAbstractItemView.ContiguousSelection)
        self._tasks_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in (1, 2):
            self._tasks_table.horizontalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeToContents)
        self._tasks_table.setToolTip(_make_tooltip(
            "FreeRTOS task list",
            "All active FreeRTOS tasks sorted by CPU% descending.\n"
            "CPU% is cumulative since boot — not a per-interval snapshot."))
        vbox.addWidget(self._tasks_table)

    def esp32_update_timing(self, hr1_mean, hr1_max, hr2fp_mean, hr2fp_max,
                      hr3fp_mean, hr3fp_max, spo2_mean, spo2_max,
                      cycle_mean, cycle_max,
                      hr2cmp_mean, hr2cmp_max, hr3cmp_mean, hr3cmp_max,
                      stack_free):
        """Called with parsed integer µs values from a $TIMING frame."""
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")

        # Task A rows: metric = Budget % (max vs 2000 µs)
        task_a_data = [
            (hr1_mean,   hr1_max),
            (hr2fp_mean, hr2fp_max),
            (hr3fp_mean, hr3fp_max),
            (spo2_mean,  spo2_max),
            (cycle_mean, cycle_max),
        ]
        for phys_row, (mean_us, max_us) in zip(self._data_rows_A, task_a_data):
            budget_pct = max_us / self._BUDGET_US * 100.0
            self._table.item(phys_row, 1).setText(f"{mean_us}")
            self._table.item(phys_row, 2).setText(f"{max_us}")
            self._table.item(phys_row, 3).setText(f"{budget_pct:.1f}%")
            if phys_row == self._data_rows_A[-1]:  # Cycle row — colour-code
                if max_us > self._BUDGET_US:
                    colour = "#FF4444"
                elif max_us > self._WARN_US:
                    colour = "#FFA500"
                else:
                    colour = "#44FF44"
                self._table.item(phys_row, 2).setForeground(QtGui.QColor(colour))
                self._table.item(phys_row, 3).setForeground(QtGui.QColor(colour))

        # Task B/C rows: metric = CPU load % (mean vs 500 000 µs period)
        task_bc_data = [
            (hr2cmp_mean, hr2cmp_max),
            (hr3cmp_mean, hr3cmp_max),
        ]
        for phys_row, (mean_us, max_us) in zip(self._data_rows_BC, task_bc_data):
            cpu_pct = mean_us / self._ASYNC_PERIOD * 100.0
            self._table.item(phys_row, 1).setText(f"{mean_us}")
            self._table.item(phys_row, 2).setText(f"{max_us}")
            self._table.item(phys_row, 3).setText(f"{cpu_pct:.2f}% CPU")

        # Status bar (Task A cycle)
        if cycle_max > self._BUDGET_US:
            self._lbl_status.setText(f"OVER BUDGET  cycle_max={cycle_max} µs > {self._BUDGET_US} µs  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #3A0000; color: #FF4444; font-size: 13px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")
        elif cycle_max > self._WARN_US:
            self._lbl_status.setText(f"TIGHT  cycle_max={cycle_max} µs  (budget {self._BUDGET_US} µs)  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #2A1A00; color: #FFA500; font-size: 13px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")
        else:
            self._lbl_status.setText(f"OK  cycle_max={cycle_max} µs  (budget {self._BUDGET_US} µs)  [{now}]")
            self._lbl_status.setStyleSheet(
                "background: #1A3A1A; color: #44FF44; font-size: 13px; "
                "font-weight: bold; padding: 4px; border-radius: 4px;")

        self._lbl_stack.setText(f"Stack free: {stack_free} words  |  Last update: {now}")

    _TASK_LABELS = {
        "incunest_afe4490": "incunest_afe4490 (Task A)",
        "incunest_hr2":     "incunest_hr2 (Task B)",
        "incunest_hr3":     "incunest_hr3 (Task C)",
    }

    def esp32_update_tasks(self, tasks):
        """Rebuild the FreeRTOS task table from a list of (name, pct_x10, stack) tuples."""
        # Sort by CPU% descending
        sorted_tasks = sorted(tasks, key=lambda t: t[1], reverse=True)
        self._tasks_table.setRowCount(len(sorted_tasks))
        for row, (name, pct_x10, stack) in enumerate(sorted_tasks):
            cpu_pct = pct_x10 / 10.0
            display_name = self._TASK_LABELS.get(name, name)
            name_item = QtWidgets.QTableWidgetItem(display_name)
            name_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            pct_item  = QtWidgets.QTableWidgetItem(f"{cpu_pct:.1f}%")
            pct_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            stk_item  = QtWidgets.QTableWidgetItem(str(stack))
            stk_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # Colour-code CPU%: highlight tasks consuming significant CPU
            if cpu_pct >= 20.0:
                colour = QtGui.QColor("#FFA500")
                name_item.setForeground(colour)
                pct_item.setForeground(colour)
            self._tasks_table.setItem(row, 0, name_item)
            self._tasks_table.setItem(row, 1, pct_item)
            self._tasks_table.setItem(row, 2, stk_item)

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.Copy):
            # Copy from whichever table has an active selection
            for tbl in (self._table, self._tasks_table):
                selected = tbl.selectedRanges()
                if not selected:
                    continue
                rows_text = []
                for rng in selected:
                    for row in range(rng.topRow(), rng.bottomRow() + 1):
                        cells = []
                        for col in range(rng.leftColumn(), rng.rightColumn() + 1):
                            item = tbl.item(row, col)
                            cells.append(item.text() if item else "")
                        rows_text.append("\t".join(cells))
                QtWidgets.QApplication.clipboard().setText("\n".join(rows_text))
                return
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("Esp32TimingWindow/geometry", self.saveGeometry())
        mm = getattr(self, 'main_monitor', None)
        if mm is not None and hasattr(mm, 'btn_timing'):
            mm.btn_timing.setChecked(False)
            mm.timing_window = None
        super().closeEvent(event)


class DiagnosticsWindow(QtWidgets.QMainWindow):
    """AFE4490 hardware diagnostics window.

    Sends $DIAG? to the ESP32, which runs the built-in diagnostic sequence
    (datasheet section 8.4.3.3, ~10 ms) and returns the DIAG register (0x30).
    Displays all 13 diagnostic flags with OK / FAULT status.
    """

    # (bit, flag_name, module, description)
    _DIAG_FLAGS = [
        (12, "PD_ALM",    "PD",  "Photodiode alarm — summary flag for all PD-side faults"),
        (11, "LED_ALM",   "LED", "LED alarm — summary flag for all LED-side faults"),
        (10, "LED1OPEN",  "LED", "LED1 open circuit detected"),
        ( 9, "LED2OPEN",  "LED", "LED2 open circuit detected"),
        ( 8, "LEDSC",     "LED", "LED short circuit detected"),
        ( 7, "OUTPSHGND", "LED", "Tx OUTP line shorted to GND cable"),
        ( 6, "OUTNSHGND", "LED", "Tx OUTN line shorted to GND cable"),
        ( 5, "PDOC",      "PD",  "Photodiode open circuit detected"),
        ( 4, "PDSC",      "PD",  "Photodiode short circuit detected"),
        ( 3, "INNSCGND",  "PD",  "Rx INN cable shorted to GND cable"),
        ( 2, "INPSCGND",  "PD",  "Rx INP cable shorted to GND cable"),
        ( 1, "INNSCLED",  "PD",  "Rx INN cable shorted to LED cable"),
        ( 0, "INPSCLED",  "PD",  "Rx INP cable shorted to LED cable"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_monitor = parent
        self.setWindowTitle("AFE4490 Diagnostics")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0; font-size: 26px;")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value(
            "DiagnosticsWindow/geometry")
        if geom: self.restoreGeometry(geom)
        else:    self.resize(720, 580)
        self._setup_ui()

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setSpacing(6)
        vbox.setContentsMargins(12, 10, 12, 10)

        btn_run = QtWidgets.QPushButton("Run diagnostic  ($DIAG?)")
        btn_run.setStyleSheet("font-size:26px; padding:4px 14px; "
                              "background-color:#2A3D5A; color:#AACCFF;")
        btn_run.clicked.connect(self._on_run)
        btn_run.setToolTip(_make_tooltip(
            "Run diagnostic ($DIAG?)",
            "Sends $DIAG? to the ESP32. The AFE4490 runs its built-in hardware "
            "diagnostic sequence (~10 ms) and returns the DIAG register (0x30). "
            "Checks for LED open/short, photodiode faults, and cable shorts."))
        vbox.addWidget(btn_run)

        raw_row = QtWidgets.QHBoxLayout()
        raw_row.addWidget(QtWidgets.QLabel("Raw DIAG register (0x30):"))
        self._lbl_raw = QtWidgets.QLabel("—")
        self._lbl_raw.setStyleSheet("color:#AACCFF; font-family:monospace;")
        raw_row.addWidget(self._lbl_raw)
        raw_row.addStretch()
        vbox.addLayout(raw_row)

        grp = QtWidgets.QGroupBox("Diagnostic Flags  (AFE4490 datasheet Table 3 / Figure 130)")
        grp.setStyleSheet(
            "QGroupBox { font-size:24px; font-weight:bold; color:#AACCFF; "
            "border:1px solid #334466; border-radius:6px; margin-top:8px; padding-top:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        grid = QtWidgets.QGridLayout(grp)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 24, 8, 8)

        for col, (txt, w) in enumerate([("Bit",6),("Flag",10),("Mod",5),("Status",8),("Description",None)]):
            lbl = QtWidgets.QLabel(txt)
            lbl.setStyleSheet("font-weight:bold; color:#AACCFF; font-size:22px;")
            grid.addWidget(lbl, 0, col)

        self._status_labels = {}
        for row, (bit, name, module, desc) in enumerate(self._DIAG_FLAGS, start=1):
            lbl_bit = QtWidgets.QLabel(f"D{bit}")
            lbl_bit.setStyleSheet("color:#888888; font-size:22px; font-family:monospace;")
            lbl_name = QtWidgets.QLabel(name)
            lbl_name.setStyleSheet("color:#E0E0E0; font-size:22px; font-family:monospace;")
            lbl_mod = QtWidgets.QLabel(module)
            lbl_mod.setStyleSheet("color:#AAAAAA; font-size:22px;")
            lbl_status = QtWidgets.QLabel("—")
            lbl_status.setStyleSheet("color:#555555; font-size:22px; font-weight:bold;")
            lbl_status.setFixedWidth(90)
            lbl_status.setAlignment(QtCore.Qt.AlignCenter)
            lbl_desc = QtWidgets.QLabel(desc)
            lbl_desc.setStyleSheet("color:#AAAAAA; font-size:20px;")
            lbl_desc.setWordWrap(True)
            grid.addWidget(lbl_bit,    row, 0)
            grid.addWidget(lbl_name,   row, 1)
            grid.addWidget(lbl_mod,    row, 2)
            grid.addWidget(lbl_status, row, 3)
            grid.addWidget(lbl_desc,   row, 4)
            self._status_labels[bit] = lbl_status

        grid.setColumnStretch(4, 1)
        vbox.addWidget(grp, stretch=1)

        self._statusbar = self.statusBar()
        self._statusbar.setStyleSheet("font-size:22px; color:#AAAAAA;")
        self._statusbar.showMessage("No data — click 'Run diagnostic'")

    def _on_run(self):
        mm = self.main_monitor
        if mm is None or not mm._is_cmd_ready():
            self._statusbar.showMessage("Not connected — no serial or UDP command channel")
            QtWidgets.QMessageBox.warning(self, "Not connected",
                "No command channel available.\n\nConnect via serial or enable UDP WiFi first.")
            return
        mm.send_cmd(b"$DIAG?\n")
        mm.log("→ $DIAG?")
        self._statusbar.showMessage("Sent $DIAG? — waiting for response (~10 ms)…")

    def update_from_diag(self, raw: int):
        self._lbl_raw.setText(f"0x{raw:06X}")
        fault_count = 0
        for bit, name, module, desc in self._DIAG_FLAGS:
            lbl = self._status_labels[bit]
            if (raw >> bit) & 1:
                lbl.setText("FAULT")
                lbl.setStyleSheet("color:#FF4444; font-size:22px; font-weight:bold;")
                fault_count += 1
            else:
                lbl.setText("OK")
                lbl.setStyleSheet("color:#44FF44; font-size:22px; font-weight:bold;")
        if fault_count == 0:
            self._statusbar.showMessage(f"All OK — no faults detected  (0x{raw:06X})")
        else:
            self._statusbar.showMessage(
                f"Diagnostic complete — {fault_count} fault(s) detected  (0x{raw:06X})")

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue(
            "DiagnosticsWindow/geometry", self.saveGeometry())
        mm = self.main_monitor
        if mm is not None and hasattr(mm, 'btn_diagnostics'):
            mm.btn_diagnostics.setChecked(False)
            mm.diag_window = None
        super().closeEvent(event)


class _WheelBlockFilter(QtCore.QObject):
    """Event filter that blocks mouse-wheel events on a widget unless it has focus."""
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return super().eventFilter(obj, event)


class HWConfigWindow(QtWidgets.QMainWindow):
    """AFE4490 hardware parameter control window.

    Sends $SET,key,value*XX commands to the ESP32 to change hardware parameters
    at runtime. Populates from incoming $CFG frames. Each parameter has its own
    Set button so changes can be applied individually during lab sessions.
    """

    # TIA gain options — same strings as tia_gain_str() in main.cpp
    TIA_GAINS  = ["10K", "25K", "50K", "100K", "250K", "500K", "1M"]
    TIA_CFS    = ["5p", "10p", "20p", "30p", "55p", "155p"]
    STG2_GAINS         = ["0dB", "3.5dB", "6dB", "9.5dB", "12dB"]
    STG2_GAINS_DISPLAY = ["0dB  ×1  100 kΩ", "3.5dB  ×1.5  150 kΩ",
                          "6dB  ×2  200 kΩ",  "9.5dB  ×3  300 kΩ",
                          "12dB  ×4  400 kΩ"]
    LED_RANGES = ["75", "150"]

    # Stylesheets for clean/dirty states
    _SPIN_SS_CLEAN  = "background-color:#202020; color:#E0E0E0;"
    _SPIN_SS_DIRTY  = "background-color:#202020; color:#FF4444;"
    _TSPIN_SS_CLEAN = "font-size:22px; background-color:#202020; color:#E0E0E0;"
    _TSPIN_SS_DIRTY = "font-size:22px; background-color:#202020; color:#FF4444;"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_monitor = parent
        self.setWindowTitle("HW CONFIG — AFE4490")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0; font-size: 26px;")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("HWConfigWindow/geometry")
        if geom: self.restoreGeometry(geom)
        else:    self.resize(560, 900)
        self._updating_from_cfg = False
        self._cfg_timer = QtCore.QTimer(self)
        self._cfg_timer.setSingleShot(True)
        self._cfg_timer.timeout.connect(self._on_cfg_timeout)
        self._setup_ui()

    # Timing register definitions: (key, reg_name, short_name, description)
    # short_name: datasheet field label (Fig. 83–110).
    # Order follows spec §11.1 temporal sequence (t0=0 → t29=PRPCOUNT).
    _TIMING_REGS = [
        ('t21', 'ADCRSTSTCT0',  'ADC reset 0 start count',           'Start of period (t=0). Must be < t22 and ≤ t13.'),
        ('t22', 'ADCRSTENDCT0', 'ADC reset 0 end count',             '3-count pulse (0.75 µs). Must be > t21; < t13; (t22−t21) ≥ 4.'),
        ('t13', 'LED2CONVST',   'LED2 convert start count',          '1 count after t22. Must be ≥ t22; ≥ t2+1 (circ.); < t14.'),
        ('t5',  'ALED2STC',     'Sample ambient LED2 start count',   '≥200 counts after LED2 OFF (TIA settling). Must be > t4 (circ.); < t6.'),
        ('t6',  'ALED2ENDC',    'Sample ambient LED2 end count',     'Must be > t5; < t9; ≤ t15.'),
        ('t14', 'LED2CONVEND',  'LED2 convert end count',            'Must be > t13; (t14−t13) ≥ 1950.'),
        ('t23', 'ADCRSTSTCT1',  'ADC reset 1 start count',           'Start of phase 2 (25% of period). Must be < t24; ≤ t15.'),
        ('t9',  'LED1LEDSTC',   'LED1 start count',                  'LED1 turn-on, start of LED1 phase. Must be ≤ t7; < t10.'),
        ('t24', 'ADCRSTENDCT1', 'ADC reset 1 end count',             't23+3 counts. Must be > t23; < t15; (t24−t23) ≥ 4.'),
        ('t15', 'ALED2CONVST',  'LED2 ambient convert start count',  '1 count after t24. Must be ≥ t24; ≥ t6+1; < t16.'),
        ('t7',  'LED1STC',      'Sample LED1 start count',           '≥50 counts after LED1 on. Must be ≥ t9; < t8.'),
        ('t8',  'LED1ENDC',     'Sample LED1 end count',             'Must be > t7; ≤ t10; < t17.'),
        ('t10', 'LED1LEDENDC',  'LED1 end count',                    'LED1 turn-off. 25% duty cycle. Must be ≥ t8; > t9.'),
        ('t16', 'ALED2CONVEND', 'LED2 ambient convert end count',    'Must be > t15; (t16−t15) ≥ 1950.'),
        ('t25', 'ADCRSTSTCT2',  'ADC reset 2 start count',           'Start of phase 3 (50% of period). Must be < t26; ≤ t17.'),
        ('t26', 'ADCRSTENDCT2', 'ADC reset 2 end count',             't25+3 counts. Must be > t25; < t17; (t26−t25) ≥ 4.'),
        ('t17', 'LED1CONVST',   'LED1 convert start count',          '1 count after t26. Must be ≥ t26; ≥ t8+1; < t18.'),
        ('t11', 'ALED1STC',     'Sample ambient LED1 start count',   '≥200 counts after LED1 OFF (TIA settling). Must be > t10; < t12.'),
        ('t12', 'ALED1ENDC',    'Sample ambient LED1 end count',     'Must be > t11; < t3 (circ.); ≤ t19.'),
        ('t18', 'LED1CONVEND',  'LED1 convert end count',            'Must be > t17; (t18−t17) ≥ 1950.'),
        ('t27', 'ADCRSTSTCT3',  'ADC reset 3 start count',           'Start of phase 4 (75% of period). Must be < t28; ≤ t19.'),
        ('t3',  'LED2LEDSTC',   'LED2 start count',                  'LED2 turn-on, start of LED2 phase. Must be ≤ t1; < t4.'),
        ('t28', 'ADCRSTENDCT3', 'ADC reset 3 end count',             't27+3 counts. Must be > t27; < t19; (t28−t27) ≥ 4.'),
        ('t19', 'ALED1CONVST',  'LED1 ambient convert start count',  '1 count after t28. Must be ≥ t28; ≥ t12+1; < t20.'),
        ('t1',  'LED2STC',      'Sample LED2 start count',           '≥50 counts after LED2 on. Must be ≥ t3; < t2.'),
        ('t2',  'LED2ENDC',     'Sample LED2 end count',             'Must be > t1; ≤ t4; < t13+period (circ.).'),
        ('t4',  'LED2LEDENDC',  'LED2 end count',                    'LED2 turn-off. 25% duty cycle. Must be ≥ t2; > t3.'),
        ('t20', 'ALED1CONVEND', 'LED1 ambient convert end count',    '= PRPCOUNT. Must be > t19; (t20−t19) ≥ 1950.'),
    ]

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setSpacing(6)
        vbox.setContentsMargins(12, 10, 12, 10)

        # Top button row: file ops + Read from chip + Set all
        btn_top_row = QtWidgets.QHBoxLayout()

        btn_read_file = QtWidgets.QPushButton("Read from file")
        btn_read_file.setStyleSheet("font-size:26px; padding:4px 14px; background-color:#2D2010; color:#FFCC66;")
        btn_read_file.clicked.connect(self._on_read_from_file)
        btn_read_file.setToolTip(_make_tooltip(
            "Read from file (.pncfg)",
            "Opens a .pncfg file and loads its values into the UI controls. "
            "Values that differ from the current UI state are highlighted in red "
            "to indicate they have not yet been sent to the hardware."))
        btn_top_row.addWidget(btn_read_file)

        btn_save_file = QtWidgets.QPushButton("Save to file")
        btn_save_file.setStyleSheet("font-size:26px; padding:4px 14px; background-color:#2D2010; color:#FFCC66;")
        btn_save_file.clicked.connect(self._on_save_to_file)
        btn_save_file.setToolTip(_make_tooltip(
            "Save to file (.pncfg)",
            "Saves all current UI values to a .pncfg file. "
            "Does not read from or write to the hardware — only captures the UI state."))
        btn_top_row.addWidget(btn_save_file)

        btn_read = QtWidgets.QPushButton("Read from chip  ($CFG?)")
        btn_read.setStyleSheet("font-size:26px; padding:4px 14px; background-color:#2A3D5A; color:#AACCFF;")
        btn_read.clicked.connect(self._on_read_cfg)
        btn_read.setToolTip(_make_tooltip(
            "Read from chip ($CFG?)",
            "Sends $CFG? to the ESP32 and updates all controls with the actual "
            "current chip configuration."))
        btn_top_row.addWidget(btn_read, stretch=1)

        btn_set_all = QtWidgets.QPushButton("Set all")
        btn_set_all.setStyleSheet("font-size:26px; padding:4px 14px; background-color:#1E3A1E; color:#88FF88;")
        btn_set_all.clicked.connect(self._on_set_all)
        btn_set_all.setToolTip(_make_tooltip(
            "Set all parameters",
            "Sends $SET for every parameter in this window (LED currents, TIA gain, "
            "sample rate, averages and all timing registers t1–t28) in one shot."))
        btn_top_row.addWidget(btn_set_all)

        vbox.addLayout(btn_top_row)

        # ── LED Currents ──────────────────────────────────────────────────────
        grp_led = QtWidgets.QGroupBox("LED Currents")
        grp_led.setStyleSheet("QGroupBox { font-size:26px; font-weight:bold; color:#AACCFF; "
                              "border:1px solid #334466; border-radius:6px; margin-top:8px; padding-top:6px; }"
                              "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")
        form_led = QtWidgets.QFormLayout(grp_led)
        form_led.setSpacing(6)

        self._spin_led1 = QtWidgets.QDoubleSpinBox()
        self._spin_led1.setRange(0.0, 150.0)
        self._spin_led1.setDecimals(2)
        self._spin_led1.setSuffix(" mA")
        self._spin_led1.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._spin_led1.setToolTip(_make_tooltip("LED1 current (IR)",
            "Drive current for the IR LED. Range depends on LED range setting (75 or 150 mA full-scale). "
            "Sends $SET,led1,<value>.",
            src="AFE4490Config::afe_led1_current_mA"))
        form_led.addRow("LED1 (IR)", self._make_row(self._spin_led1, "led1", lambda: f"{self._spin_led1.value():.2f}"))

        self._spin_led2 = QtWidgets.QDoubleSpinBox()
        self._spin_led2.setRange(0.0, 150.0)
        self._spin_led2.setDecimals(2)
        self._spin_led2.setSuffix(" mA")
        self._spin_led2.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._spin_led2.setToolTip(_make_tooltip("LED2 current (RED)",
            "Drive current for the RED LED. Range depends on LED range setting (75 or 150 mA full-scale). "
            "Sends $SET,led2,<value>.",
            src="AFE4490Config::afe_led2_current_mA"))
        form_led.addRow("LED2 (RED)", self._make_row(self._spin_led2, "led2", lambda: f"{self._spin_led2.value():.2f}"))

        self._combo_ledrange = QtWidgets.QComboBox()
        self._combo_ledrange.addItems(self.LED_RANGES)
        self._combo_ledrange.setToolTip(_make_tooltip("LED full-scale range",
            "Sets the LED current DAC full-scale: 75 mA or 150 mA. "
            "Affects the meaning of the LED1/LED2 current values. "
            "Sends $SET,ledrange,<75|150>. ($CFG key: range)",
            src="AFE4490Config::afe_led_range_mA"))
        form_led.addRow("Range", self._make_row(self._combo_ledrange, "ledrange",
                                                lambda: self._combo_ledrange.currentText()))
        vbox.addWidget(grp_led)

        # ── TIA Gain ──────────────────────────────────────────────────────────
        grp_tia = QtWidgets.QGroupBox("TIA Gain")
        grp_tia.setStyleSheet(grp_led.styleSheet())
        form_tia = QtWidgets.QFormLayout(grp_tia)
        form_tia.setSpacing(6)

        # ENSEPGAIN
        self._chk_ensepgain = QtWidgets.QCheckBox("Separate gain per LED (ENSEPGAIN bit D15)")
        self._chk_ensepgain.setStyleSheet("font-size:24px; color:#E0E0E0;")
        self._chk_ensepgain.setToolTip(_make_tooltip("ENSEPGAIN — Enable separate TIA gain per LED",
            "OFF: TIAGAIN register applies to both channels (LED1 controls ignored by chip).\n"
            "ON:  TIAGAIN register → LED1 (IR);  TIA_AMB_GAIN register → LED2 (RED).\n"
            "Sends $SET,ensepgain,<0|1>. ($CFG key: ensepgain)",
            src="AFE4490Config::afe_sep_tia_en"))
        self._chk_ensepgain.stateChanged.connect(self._on_ensepgain_changed)
        self._chk_ensepgain.stateChanged.connect(lambda _=None: self._mark_dirty(self._chk_ensepgain))
        row_ensep = QtWidgets.QHBoxLayout()
        row_ensep.addWidget(self._chk_ensepgain, stretch=1)
        row_ensep.addWidget(self._make_set_btn("ensepgain",
            lambda: "1" if self._chk_ensepgain.isChecked() else "0", self._chk_ensepgain))
        form_tia.addRow("ENSEPGAIN", row_ensep)

        # LED1 (IR) sub-header
        lbl_led1_hdr = QtWidgets.QLabel("── LED1 (IR) ──────────────────────────")
        lbl_led1_hdr.setStyleSheet("font-size:22px; color:#88AACC;")
        form_tia.addRow(lbl_led1_hdr)

        self._combo_tiagain1 = QtWidgets.QComboBox()
        self._combo_tiagain1.addItems(self.TIA_GAINS)
        self._combo_tiagain1.setToolTip(_make_tooltip("LED1 (IR) TIA feedback resistance (RF1)",
            "Feedback resistor for the IR LED channel (TIAGAIN register). "
            "Only active when ENSEPGAIN=ON; ignored by chip when ENSEPGAIN=OFF. "
            "Sends $SET,tiagain1,<value>. ($CFG key: tia1)",
            src="AFE4490Config::afe_tia_rf_led1"))
        form_tia.addRow("RF Gain", self._make_row(self._combo_tiagain1, "tiagain1",
                                                   lambda: self._combo_tiagain1.currentText()))

        self._combo_tiacf1 = QtWidgets.QComboBox()
        self._combo_tiacf1.addItems(self.TIA_CFS)
        self._combo_tiacf1.setToolTip(_make_tooltip("LED1 (IR) TIA feedback capacitance (CF1)",
            "Feedback capacitor for the IR LED channel. "
            "Only active when ENSEPGAIN=ON; ignored by chip when ENSEPGAIN=OFF. "
            "Sends $SET,tiacf1,<value>. ($CFG key: cf1)",
            src="AFE4490Config::afe_tia_cf_led1"))
        form_tia.addRow("CF", self._make_row(self._combo_tiacf1, "tiacf1",
                                              lambda: self._combo_tiacf1.currentText()))

        self._combo_stg21 = QtWidgets.QComboBox()
        self._combo_stg21.addItems(self.STG2_GAINS_DISPLAY)
        self._combo_stg21.setToolTip(_make_tooltip("LED1 (IR) Stage 2 gain (STG2GAIN1)",
            "STG2GAIN1[2:0] bits D[10:8] of TIAGAIN. Gain applied when STAGE2EN1 is ON. "
            "Only active when ENSEPGAIN=ON; ignored by chip when ENSEPGAIN=OFF. "
            "Sends $SET,stg21,<value>. ($CFG key: stg21)",
            src="AFE4490Config::afe_stg2_rg_led1"))
        form_tia.addRow("Stage 2 gain", self._make_row(self._combo_stg21, "stg21",
                                                       lambda: self.STG2_GAINS[self._combo_stg21.currentIndex()]))

        self._combo_stage2en1 = QtWidgets.QComboBox()
        self._combo_stage2en1.addItems(["FALSE", "TRUE"])
        self._combo_stage2en1.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._combo_stage2en1.setToolTip(_make_tooltip("LED1 (IR) Stage 2 enable (STAGE2EN1)",
            "STAGE2EN1 bit D14 of TIAGAIN. Enables the Stage 2 amplifier for the LED1 channel. "
            "Independent of STG2GAIN1 — can be ON at 0 dB (unity gain) or OFF despite non-zero gain. "
            "Only active when ENSEPGAIN=ON; ignored by chip when ENSEPGAIN=OFF. "
            "Sends $SET,stage2en1,<0|1>. ($CFG key: stage2en1)",
            src="AFE4490Config::afe_stg2_en_led1"))
        form_tia.addRow("Stage 2 EN", self._make_row(self._combo_stage2en1, "stage2en1",
            lambda: "1" if self._combo_stage2en1.currentText() == "TRUE" else "0"))

        # LED2 (RED) sub-header
        lbl_led2_hdr = QtWidgets.QLabel("── LED2 (RED) — always active ──────────")
        lbl_led2_hdr.setStyleSheet("font-size:22px; color:#CC8888;")
        form_tia.addRow(lbl_led2_hdr)

        self._combo_tiagain2 = QtWidgets.QComboBox()
        self._combo_tiagain2.addItems(self.TIA_GAINS)
        self._combo_tiagain2.setToolTip(_make_tooltip("LED2 (RED) TIA feedback resistance (RF2)",
            "Feedback resistor for the RED LED channel (TIA_AMB_GAIN register). "
            "Always active. When ENSEPGAIN=OFF, also applies to LED1 (IR). "
            "Sends $SET,tiagain2,<value>. ($CFG key: tia2)",
            src="AFE4490Config::afe_tia_rf_led2"))
        form_tia.addRow("RF Gain", self._make_row(self._combo_tiagain2, "tiagain2",
                                                   lambda: self._combo_tiagain2.currentText()))

        self._combo_tiacf2 = QtWidgets.QComboBox()
        self._combo_tiacf2.addItems(self.TIA_CFS)
        self._combo_tiacf2.setToolTip(_make_tooltip("LED2 (RED) TIA feedback capacitance (CF2)",
            "Feedback capacitor for the RED LED channel. "
            "Always active. When ENSEPGAIN=OFF, also applies to LED1 (IR). "
            "Sends $SET,tiacf2,<value>. ($CFG key: cf2)",
            src="AFE4490Config::afe_tia_cf_led2"))
        form_tia.addRow("CF", self._make_row(self._combo_tiacf2, "tiacf2",
                                              lambda: self._combo_tiacf2.currentText()))

        self._combo_stg22 = QtWidgets.QComboBox()
        self._combo_stg22.addItems(self.STG2_GAINS_DISPLAY)
        self._combo_stg22.setToolTip(_make_tooltip("LED2 (RED) Stage 2 gain (STG2GAIN2)",
            "STG2GAIN2[2:0] bits D[10:8] of TIA_AMB_GAIN. Gain applied when STAGE2EN2 is ON. "
            "Always active. When ENSEPGAIN=OFF, also applies to LED1 (IR). "
            "Sends $SET,stg22,<value>. ($CFG key: stg22)",
            src="AFE4490Config::afe_stg2_rg_led2"))
        form_tia.addRow("Stage 2 gain", self._make_row(self._combo_stg22, "stg22",
                                                       lambda: self.STG2_GAINS[self._combo_stg22.currentIndex()]))

        self._combo_stage2en2 = QtWidgets.QComboBox()
        self._combo_stage2en2.addItems(["FALSE", "TRUE"])
        self._combo_stage2en2.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._combo_stage2en2.setToolTip(_make_tooltip("LED2 (RED) Stage 2 enable (STAGE2EN2)",
            "STAGE2EN2 bit D14 of TIA_AMB_GAIN. Enables the Stage 2 amplifier for the LED2 channel. "
            "Independent of STG2GAIN2 — can be ON at 0 dB (unity gain) or OFF despite non-zero gain. "
            "Always active. When ENSEPGAIN=OFF, also applies to LED1 (IR). "
            "Note: the library also forces STAGE2EN2=1 when AMBDAC &gt; 0. "
            "Sends $SET,stage2en2,<0|1>. ($CFG key: stage2en2)",
            src="AFE4490Config::afe_stg2_en_led2"))
        form_tia.addRow("Stage 2 EN", self._make_row(self._combo_stage2en2, "stage2en2",
            lambda: "1" if self._combo_stage2en2.currentText() == "TRUE" else "0"))

        vbox.addWidget(grp_tia)
        self._on_ensepgain_changed()  # set initial enabled state of LED1 controls

        # ── Ambient Cancellation ───────────────────────────────────────────────
        grp_amb = QtWidgets.QGroupBox("Ambient Cancellation")
        grp_amb.setStyleSheet(grp_led.styleSheet())
        form_amb = QtWidgets.QFormLayout(grp_amb)
        form_amb.setSpacing(6)

        self._spin_ambdac = QtWidgets.QSpinBox()
        self._spin_ambdac.setRange(0, 10)
        self._spin_ambdac.setSuffix(" µA")
        self._spin_ambdac.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._spin_ambdac.setToolTip(_make_tooltip("Ambient cancellation DAC (AMBDAC)",
            "Injects a cancellation current before Stage 2 to reduce ambient light contribution "
            "in the ADC. AMBDAC[3:0] in TIA_AMB_GAIN register D19:D16. Range 0–10 µA (1 µA/step). "
            "Use when aled1/aled2 are large due to strong ambient light (e.g. near window). "
            "Sends $SET,ambdac,<value>.",
            src="AFE4490Config::afe_ambdac_uA"))
        form_amb.addRow("AMBDAC", self._make_row(self._spin_ambdac, "ambdac",
                                                 lambda: str(self._spin_ambdac.value())))
        vbox.addWidget(grp_amb)

        # ── Sampling ──────────────────────────────────────────────────────────
        grp_samp = QtWidgets.QGroupBox("Sampling")
        grp_samp.setStyleSheet(grp_led.styleSheet())
        form_samp = QtWidgets.QFormLayout(grp_samp)
        form_samp.setSpacing(6)

        self._spin_sr = QtWidgets.QSpinBox()
        self._spin_sr.setRange(63, 5000)
        self._spin_sr.setSuffix(" Hz")
        self._spin_sr.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._spin_sr.setToolTip(_make_tooltip("Sample rate",
            "ADC sample rate in Hz (63–5000). Changing this requires a chip restart "
            "(brief data gap ~200 ms). Also recalculates all algorithm time constants. "
            "Sends $SET,sr,<value>.",
            src="AFE4490Config::afe_sample_rate_hz"))
        lbl_sr_warn = QtWidgets.QLabel("⚠ restarts chip")
        lbl_sr_warn.setStyleSheet("color:#FFAA44; font-size:22px;")
        self._spin_sr.valueChanged.connect(lambda _=None: self._mark_dirty(self._spin_sr))
        row_sr = QtWidgets.QHBoxLayout()
        row_sr.addWidget(self._spin_sr)
        row_sr.addWidget(lbl_sr_warn)
        row_sr.addWidget(self._make_set_btn("sr", lambda: str(self._spin_sr.value()), self._spin_sr))
        form_samp.addRow("Sample rate", row_sr)

        self._spin_numav = QtWidgets.QSpinBox()
        self._spin_numav.setRange(1, 128)
        self._spin_numav.setStyleSheet("background-color:#202020; color:#E0E0E0;")
        self._spin_numav.setToolTip(_make_tooltip("ADC averages",
            "Number of ADC hardware averages per sample (1 = no averaging). Higher values "
            "reduce noise but lower effective sample rate. Max allowed = floor(5000 / sr). "
            "Sends $SET,numav,<value>.",
            src="AFE4490Config::afe_adc_averages"))
        form_samp.addRow("Averages", self._make_row(self._spin_numav, "numav",
                                                    lambda: str(self._spin_numav.value())))
        vbox.addWidget(grp_samp)

        # ── Timing Registers ──────────────────────────────────────────────────
        grp_timing = QtWidgets.QGroupBox("Timing Registers  (AFECLK = 4 MHz → 1 count = 0.25 µs)")
        grp_timing.setStyleSheet(grp_led.styleSheet())
        timing_vbox = QtWidgets.QVBoxLayout(grp_timing)
        timing_vbox.setSpacing(4)
        timing_vbox.setContentsMargins(6, 24, 6, 6)

        self._lbl_timing_status = QtWidgets.QLabel("No timing data — click 'Read from chip'")
        self._lbl_timing_status.setStyleSheet("color:#AAAAAA; font-size:20px;")
        self._lbl_timing_status.setWordWrap(True)
        timing_vbox.addWidget(self._lbl_timing_status)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(150)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: transparent;")
        form_t = QtWidgets.QFormLayout(inner)
        form_t.setSpacing(1)
        form_t.setContentsMargins(4, 1, 4, 1)
        scroll.setWidget(inner)
        timing_vbox.addWidget(scroll, stretch=1)
        vbox.addWidget(grp_timing, stretch=1)

        self._timing_spins = {}

        for key, reg_name, short_name, tip in self._TIMING_REGS:
            sp = QtWidgets.QSpinBox()
            sp.setRange(0, 65535)
            sp.setStyleSheet("font-size:22px; background-color:#202020; color:#E0E0E0;")
            _tip_body = (f"{short_name}\n"
                         f"{tip}\n"
                         f"Sends $SET,{key},<value>.")
            _tip = _make_tooltip(f"{key} — {reg_name}", _tip_body,
                                 src=f"AFE4490TimingConfig::{key}")
            sp.setToolTip(_tip)
            sp.valueChanged.connect(self._on_timing_changed)
            sp.valueChanged.connect(lambda _=None, w=sp: self._mark_dirty(w))
            self._timing_spins[key] = sp
            row = QtWidgets.QHBoxLayout()
            row.addWidget(sp, stretch=1)
            row.addWidget(self._make_timing_set_btn(key))
            lbl = QtWidgets.QLabel(f"{key}  {reg_name}")
            lbl.setStyleSheet("font-size:22px; color:#E0E0E0;")
            lbl.setToolTip(_tip)
            form_t.addRow(lbl, row)

        # Status bar
        self._statusbar = self.statusBar()
        self._statusbar.setStyleSheet("font-size:22px; color:#AAAAAA;")
        self._statusbar.showMessage("No data — click 'Read from chip' or wait for $CFG frame")

        # Block accidental wheel changes — only active when the widget has focus
        self._wheel_filter = _WheelBlockFilter(self)
        for w in ([self._spin_led1, self._spin_led2, self._combo_ledrange,
                   self._combo_tiagain1, self._combo_tiacf1, self._combo_stg21,
                   self._combo_tiagain2, self._combo_tiacf2, self._combo_stg22,
                   self._spin_sr, self._spin_numav]
                  + list(self._timing_spins.values())):
            w.setFocusPolicy(QtCore.Qt.StrongFocus)
            w.installEventFilter(self._wheel_filter)

    def _make_set_btn(self, key: str, value_fn, widget=None) -> QtWidgets.QPushButton:
        """Create a 'Set' button that sends $SET,key,value*XX."""
        btn = QtWidgets.QPushButton("Set")
        btn.setStyleSheet("font-size:24px; padding:2px 10px; background-color:#1E3A1E; color:#88FF88;")
        btn.setFixedWidth(70)
        def on_click():
            self._send_set(key, value_fn())
            if widget is not None:
                self._mark_clean(widget)
        btn.clicked.connect(on_click)
        return btn

    def _make_row(self, widget, key: str, value_fn) -> QtWidgets.QHBoxLayout:
        """Wrap a control and its Set button in an HBoxLayout."""
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            widget.valueChanged.connect(lambda _=None: self._mark_dirty(widget))
        elif isinstance(widget, QtWidgets.QComboBox):
            widget.currentIndexChanged.connect(lambda _=None: self._mark_dirty(widget))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(widget, stretch=1)
        row.addWidget(self._make_set_btn(key, value_fn, widget))
        return row

    def _make_timing_set_btn(self, key: str) -> QtWidgets.QPushButton:
        """Set button for a timing register — warns on constraint violations before sending."""
        btn = QtWidgets.QPushButton("Set")
        btn.setStyleSheet("font-size:22px; padding:2px 8px; background-color:#1E3A1E; color:#88FF88;")
        btn.setFixedWidth(60)
        def on_click():
            self._send_timing_set(key)
            self._mark_clean(self._timing_spins[key])
        btn.clicked.connect(on_click)
        return btn

    # ── Dirty / clean state ───────────────────────────────────────────────────
    def _mark_dirty(self, widget):
        """Turn widget text red to signal an unsent change."""
        if getattr(self, '_updating_from_cfg', False):
            return
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            ss = self._TSPIN_SS_DIRTY if widget in self._timing_spins.values() else self._SPIN_SS_DIRTY
            widget.setStyleSheet(ss)
        elif isinstance(widget, QtWidgets.QComboBox):
            widget.setStyleSheet("color:#FF4444;")
        elif isinstance(widget, QtWidgets.QCheckBox):
            widget.setStyleSheet("font-size:24px; color:#FF4444;")

    def _mark_clean(self, widget):
        """Restore normal text color after a successful send."""
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            ss = self._TSPIN_SS_CLEAN if widget in self._timing_spins.values() else self._SPIN_SS_CLEAN
            widget.setStyleSheet(ss)
        elif isinstance(widget, QtWidgets.QComboBox):
            widget.setStyleSheet("")
        elif isinstance(widget, QtWidgets.QCheckBox):
            widget.setStyleSheet("font-size:24px; color:#E0E0E0;")

    # ── Timing constraint validation ──────────────────────────────────────────
    def _validate_timing(self) -> list:
        """Return list of constraint-violation description strings (empty = all OK)."""
        t = {k: sp.value() for k, sp in self._timing_spins.items()}
        v = []
        # Each phase: start < end
        for s, e, name in [
            ('t1','t2','LED2 sample'), ('t3','t4','LED2 drive'),
            ('t5','t6','ALED2 sample'), ('t7','t8','LED1 sample'),
            ('t9','t10','LED1 drive'), ('t11','t12','ALED1 sample'),
            ('t13','t14','LED2 conv'), ('t15','t16','ALED2 conv'),
            ('t17','t18','LED1 conv'), ('t19','t20','ALED1 conv'),
            ('t21','t22','ADC rst0'), ('t23','t24','ADC rst1'),
            ('t25','t26','ADC rst2'), ('t27','t28','ADC rst3'),
        ]:
            if t[s] >= t[e]:
                v.append(f"{name}: {s}({t[s]}) ≥ {e}({t[e]})")
        # Cross-phase ordering (LED encompass, conv > sample, reset < conv) requires
        # modular arithmetic with the PRF period — omitted to avoid false positives
        # in circular configurations where a phase wraps across the cycle boundary.
        return v

    def _on_timing_changed(self):
        """Called whenever any timing spinbox changes — updates the validation label."""
        violations = self._validate_timing()
        if violations:
            preview = " | ".join(violations[:2])
            if len(violations) > 2: preview += f" (+{len(violations)-2} more)"
            self._lbl_timing_status.setText(f"⚠ {preview}")
            self._lbl_timing_status.setStyleSheet("color:#FF8844; font-size:20px;")
        else:
            self._lbl_timing_status.setText("OK — no constraint violations")
            self._lbl_timing_status.setStyleSheet("color:#88FF88; font-size:20px;")

    def _send_timing_set(self, key: str):
        """Send $SET for a timing register. Warns if constraints are violated (does not block)."""
        violations = self._validate_timing()
        if violations:
            msg = f"⚠ Sent with violation: {violations[0]}"
            if len(violations) > 1: msg += f" (+{len(violations)-1} more)"
            self._statusbar.showMessage(msg)
        self._send_set(key, str(self._timing_spins[key].value()))

    # ── ENSEPGAIN enable/disable ──────────────────────────────────────────────
    def _on_ensepgain_changed(self):
        """Enable/disable LED1 controls based on ENSEPGAIN checkbox state."""
        enabled = self._chk_ensepgain.isChecked()
        for w in (self._combo_tiagain1, self._combo_tiacf1, self._combo_stg21, self._combo_stage2en1):
            w.setEnabled(enabled)
            if not enabled:
                w.setStyleSheet("color:#555555;")
            else:
                w.setStyleSheet("")

    # ── Serial communication ──────────────────────────────────────────────────
    def _warn_not_connected(self):
        """Show a warning dialog when a user action requires an open serial port."""
        self._statusbar.showMessage("Not connected — serial port is closed")
        QtWidgets.QMessageBox.warning(self, "Not connected",
            "Serial port is not open.\n\nConnect to the board first (main window CONNECT button).")

    def _on_cfg_timeout(self):
        """Called when no $CFG response arrives within the timeout window."""
        self._statusbar.showMessage("⚠ No response from chip — check connection and firmware")

    def _send_set(self, key: str, value: str):
        mm = self.main_monitor
        if mm is None or not mm._is_cmd_ready():
            self._warn_not_connected()
            return
        payload = f"$SET,{key},{value}"
        chk = 0
        for c in payload[1:]:
            chk ^= ord(c)
        cmd = f"{payload}*{chk:02X}\r\n"
        mm._cfg_notify_lab_capture = False  # $CFG confirmation from $SET must not go to LabCapture notes
        mm.send_cmd(cmd.encode())
        mm.log(f"→ {cmd.strip()}")
        self._statusbar.showMessage(f"Sent: {cmd.strip()}  — waiting for $CFG confirmation…")
        self._cfg_timer.start(3000)

    def _on_read_cfg(self):
        mm = self.main_monitor
        if mm is None or not mm.request_chip_config(notify_lab_capture=False):
            self._warn_not_connected()
        else:
            self._statusbar.showMessage("$CFG? sent — waiting for response…")
            self._cfg_timer.start(3000)

    def _auto_read_cfg(self):
        """Silent auto-read on window open: no modal dialog if serial not ready."""
        mm = self.main_monitor
        if mm is None or not mm.request_chip_config(notify_lab_capture=False):
            self._statusbar.showMessage("Not connected — connect serial to read chip config")
        else:
            self._statusbar.showMessage("$CFG? sent — waiting for response…")
            self._cfg_timer.start(3000)

    def _on_set_all(self):
        """Send $SET for every parameter in the window."""
        hw_params = [
            ("led1",      f"{self._spin_led1.value():.2f}",                    self._spin_led1),
            ("led2",      f"{self._spin_led2.value():.2f}",                    self._spin_led2),
            ("ledrange",  self._combo_ledrange.currentText(),                   self._combo_ledrange),
            ("ensepgain", "1" if self._chk_ensepgain.isChecked() else "0",     self._chk_ensepgain),
            ("tiagain1",  self._combo_tiagain1.currentText(),                   self._combo_tiagain1),
            ("tiacf1",    self._combo_tiacf1.currentText(),                     self._combo_tiacf1),
            ("stg21",       self.STG2_GAINS[self._combo_stg21.currentIndex()],             self._combo_stg21),
            ("stage2en1",   "1" if self._combo_stage2en1.currentText() == "TRUE" else "0", self._combo_stage2en1),
            ("tiagain2",    self._combo_tiagain2.currentText(),                          self._combo_tiagain2),
            ("tiacf2",      self._combo_tiacf2.currentText(),                            self._combo_tiacf2),
            ("stg22",       self.STG2_GAINS[self._combo_stg22.currentIndex()],          self._combo_stg22),
            ("stage2en2",   "1" if self._combo_stage2en2.currentText() == "TRUE" else "0", self._combo_stage2en2),
            ("ambdac",      str(self._spin_ambdac.value()),                              self._spin_ambdac),
            ("sr",        str(self._spin_sr.value()),                           self._spin_sr),
            ("numav",     str(self._spin_numav.value()),                        self._spin_numav),
        ]
        for key, value, widget in hw_params:
            self._send_set(key, value)
            self._mark_clean(widget)
        violations = self._validate_timing()
        for key, sp in self._timing_spins.items():
            self._send_set(key, str(sp.value()))
            self._mark_clean(sp)
        n = len(hw_params) + len(self._timing_spins)
        if violations:
            msg = f"Set all ({n} params) — ⚠ timing violation: {violations[0]}"
            if len(violations) > 1:
                msg += f" (+{len(violations)-1} more)"
            self._statusbar.showMessage(msg)
        else:
            self._statusbar.showMessage(f"Set all — sent {n} parameters")

    # ── File load / save ──────────────────────────────────────────────────────
    _FILE_FILTER   = "PulseNest Config (*.pncfg);;All files (*)"
    _LAST_DIR_KEY  = "HWConfigWindow/last_file_dir"

    def _file_last_dir(self) -> str:
        return QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value(
            self._LAST_DIR_KEY, str(Path.home()))

    def _file_save_last_dir(self, path: str):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue(self._LAST_DIR_KEY, str(Path(path).parent))

    def _on_save_to_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save HW Config", self._file_last_dir(), self._FILE_FILTER)
        if not path:
            return
        if not path.endswith(".pncfg"):
            path += ".pncfg"
        self._file_save_last_dir(path)

        def kv_line(key, value, comment):
            entry = f"{key}={value}"
            return f"{entry:<15}# {comment}"

        lines = [
            "# PulseNest HW Config",
            f"# Saved: {QtCore.QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')}",
            kv_line("led1",      f"{self._spin_led1.value():.2f}",                     "LED1 (IR) — IR LED drive current (mA)"),
            kv_line("led2",      f"{self._spin_led2.value():.2f}",                     "LED2 (RED) — RED LED drive current (mA)"),
            kv_line("ledrange",  self._combo_ledrange.currentText(),                    "LED full-scale range (75 or 150 mA)"),
            kv_line("ensepgain", "1" if self._chk_ensepgain.isChecked() else "0",      "ENSEPGAIN — separate TIA gain per LED (0=shared, 1=separate)"),
            kv_line("tiagain1",  self._combo_tiagain1.currentText(),                    "LED1 (IR) TIA feedback resistance RF1 (active only when ensepgain=1)"),
            kv_line("tiacf1",    self._combo_tiacf1.currentText(),                      "LED1 (IR) TIA feedback capacitance CF1 (active only when ensepgain=1)"),
            kv_line("stg21",      self.STG2_GAINS[self._combo_stg21.currentIndex()],     "LED1 (IR) Stage 2 gain STG2GAIN1 (active only when ensepgain=1)"),
            kv_line("stage2en1", "1" if self._combo_stage2en1.currentText() == "TRUE" else "0", "LED1 (IR) STAGE2EN1 — Stage 2 enable, D14 of TIAGAIN (active only when ensepgain=1)"),
            kv_line("tiagain2",  self._combo_tiagain2.currentText(),                    "LED2 (RED) TIA feedback resistance RF2 (always active)"),
            kv_line("tiacf2",    self._combo_tiacf2.currentText(),                      "LED2 (RED) TIA feedback capacitance CF2 (always active)"),
            kv_line("stg22",     self.STG2_GAINS[self._combo_stg22.currentIndex()],     "LED2 (RED) Stage 2 gain STG2GAIN2 (always active)"),
            kv_line("stage2en2", "1" if self._combo_stage2en2.currentText() == "TRUE" else "0", "LED2 (RED) STAGE2EN2 — Stage 2 enable, D14 of TIA_AMB_GAIN (always active)"),
            kv_line("ambdac",    str(self._spin_ambdac.value()),                        "Ambient cancellation DAC current (µA) — AMBDAC[3:0] in TIA_AMB_GAIN D19:D16"),
            kv_line("sr",        str(self._spin_sr.value()),                            "Sample rate (Hz) — restarts chip on change"),
            kv_line("numav",     str(self._spin_numav.value()),                         "ADC averages per sample"),
        ]
        timing_info = {key: (reg_name, tip) for key, reg_name, _sn, tip in self._TIMING_REGS}
        for key, sp in self._timing_spins.items():
            reg_name, tip = timing_info[key]
            lines.append(kv_line(key, str(sp.value()), f"{reg_name} — {tip}"))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self._statusbar.showMessage(f"Saved: {path}")
        except Exception as e:
            self._statusbar.showMessage(f"Save failed: {e}")

    def _on_read_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open HW Config", self._file_last_dir(), self._FILE_FILTER)
        if not path:
            return
        self._file_save_last_dir(path)
        kv = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, _, v = line.partition("=")
                        kv[k.strip()] = v.split("#")[0].strip()
        except Exception as e:
            self._statusbar.showMessage(f"Read failed: {e}")
            return

        # Apply values without suppressing dirty marking — changed values go red automatically
        def set_spin_float(spin, key):
            try: spin.setValue(float(kv[key]))
            except (KeyError, ValueError): pass

        def set_spin_int(spin, key):
            try: spin.setValue(int(kv[key]))
            except (KeyError, ValueError): pass

        def set_combo(combo, key):
            if key in kv:
                idx = combo.findText(kv[key])
                if idx < 0:
                    idx = combo.findText(kv[key], QtCore.Qt.MatchStartsWith)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

        set_spin_float(self._spin_led1,        "led1")
        set_spin_float(self._spin_led2,        "led2")
        set_combo(self._combo_ledrange,        "ledrange")
        if "ensepgain" in kv:
            self._chk_ensepgain.setChecked(kv["ensepgain"] == "1")
        set_combo(self._combo_tiagain1,        "tiagain1")
        set_combo(self._combo_tiacf1,          "tiacf1")
        set_combo(self._combo_stg21,           "stg21")
        if "stage2en1" in kv:
            self._combo_stage2en1.setCurrentIndex(1 if kv["stage2en1"] == "1" else 0)
        set_combo(self._combo_tiagain2,        "tiagain2")
        set_combo(self._combo_tiacf2,          "tiacf2")
        set_combo(self._combo_stg22,           "stg22")
        if "stage2en2" in kv:
            self._combo_stage2en2.setCurrentIndex(1 if kv["stage2en2"] == "1" else 0)
        set_spin_int(self._spin_ambdac,        "ambdac")
        set_spin_int(self._spin_sr,            "sr")
        set_spin_int(self._spin_numav,         "numav")
        for key, sp in self._timing_spins.items():
            set_spin_int(sp, key)
        self._statusbar.showMessage(f"Loaded: {path}")

    # ── Update controls from $CFG key-value dict ──────────────────────────────
    def update_from_cfg(self, kv: dict):
        """Populate controls from a parsed $CFG key-value dict."""
        def set_spin_float(spin, key):
            try: spin.setValue(float(kv[key]))
            except (KeyError, ValueError): pass

        def set_spin_int(spin, key):
            try: spin.setValue(int(kv[key]))
            except (KeyError, ValueError): pass

        def set_combo(combo, key):
            v = kv.get(key)
            if v is None: return
            idx = combo.findText(v)
            if idx < 0:
                idx = combo.findText(v, QtCore.Qt.MatchStartsWith)
            if idx >= 0: combo.setCurrentIndex(idx)

        self._updating_from_cfg = True
        try:
            set_spin_float(self._spin_led1,    'led1')
            set_spin_float(self._spin_led2,    'led2')
            set_combo(self._combo_ledrange,    'range')
            if 'ensepgain' in kv:
                self._chk_ensepgain.setChecked(kv['ensepgain'] == '1')
            set_combo(self._combo_tiagain1,    'tia1')
            set_combo(self._combo_tiacf1,      'cf1')
            set_combo(self._combo_stg21,       'stg21')
            if 'stage2en1' in kv:
                self._combo_stage2en1.setCurrentIndex(1 if kv['stage2en1'] == '1' else 0)
            set_combo(self._combo_tiagain2,    'tia2')
            set_combo(self._combo_tiacf2,      'cf2')
            set_combo(self._combo_stg22,       'stg22')
            if 'stage2en2' in kv:
                self._combo_stage2en2.setCurrentIndex(1 if kv['stage2en2'] == '1' else 0)
            set_spin_int(self._spin_ambdac,    'ambdac')
            set_spin_int(self._spin_sr,        'sr')
            set_spin_int(self._spin_numav,     'numav')
        finally:
            self._updating_from_cfg = False
        self._cfg_timer.stop()
        for w in (self._spin_led1, self._spin_led2, self._combo_ledrange,
                  self._chk_ensepgain,
                  self._combo_tiagain1, self._combo_tiacf1, self._combo_stg21, self._combo_stage2en1,
                  self._combo_tiagain2, self._combo_tiacf2, self._combo_stg22, self._combo_stage2en2,
                  self._spin_ambdac, self._spin_sr, self._spin_numav):
            self._mark_clean(w)
        self._on_ensepgain_changed()  # update LED1 enabled state
        self._statusbar.showMessage("Config loaded from chip")

    def update_from_tcfg(self, kv: dict):
        """Populate timing controls from a parsed $TCFG key-value dict."""
        for key, sp in self._timing_spins.items():
            v = kv.get(key)
            if v is not None:
                try:
                    sp.blockSignals(True)
                    sp.setValue(int(v))
                    sp.blockSignals(False)
                except ValueError:
                    pass
        for sp in self._timing_spins.values():
            self._mark_clean(sp)
        self._on_timing_changed()  # validate after bulk load
        self._statusbar.showMessage("Timing config loaded from chip")

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("HWConfigWindow/geometry", self.saveGeometry())
        mm = self.main_monitor
        self.main_monitor = None
        if mm is not None and hasattr(mm, 'btn_hw_config'):
            mm.btn_hw_config.setChecked(False)
            mm.hw_config_window = None
        super().closeEvent(event)


class HR3LabWindow(QtWidgets.QMainWindow):
    """Diagnostic window for the HR3 (FFT-based) algorithm.

    Layout:
      Left (wide):   FFT spectrum — magnitude normalised to HR-band max, shaded HR band,
                     peak marker (cyan), harmonic markers (2×, 3×).
      Right top:     LP-filtered signal — last 512 samples fed into the FFT.
      Right bottom:  HR comparison over time — HR1 (yellow), HR2 (red), HR3 (cyan).
      Bottom bar:    Algorithm parameters and last-update diagnostics.
    """

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("HR3LAB")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 4)
        outer.setSpacing(4)

        # ── plots ────────────────────────────────────────────────────────────────
        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.setHandleWidth(2)
        outer.addWidget(self._splitter, stretch=1)

        # Left: FFT spectrum
        left_gw = pg.GraphicsLayoutWidget()
        self.p_fft = left_gw.addPlot(title="<b style='color:#00CCFF'>FFT SPECTRUM</b>")
        self.p_fft.setLabel('bottom', 'Frequency', units='Hz')
        self.p_fft.setLabel('left', 'Magnitude (norm. to HR-band max)')
        self.p_fft.setXRange(0, 5.5)
        self.p_fft.setYRange(0, 1.05)
        self.p_fft.showGrid(x=True, y=True, alpha=0.3)
        self._hr_region = pg.LinearRegionItem(
            values=[HRFFTCalc.HR_MIN_HZ, HRFFTCalc.HR_MAX_HZ],
            brush=pg.mkBrush(0, 180, 255, 25), movable=False)
        self.p_fft.addItem(self._hr_region)
        self.curve_fft = self.p_fft.plot(pen=pg.mkPen('#00CCFF', width=1.5), name="Spectrum")
        self.curve_hps = self.p_fft.plot(pen=pg.mkPen('#FF8800', width=1.5), name="HPS")
        self._line_peak = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen('#00CCFF', width=2),
            label='peak', labelOpts={'color': '#00CCFF', 'position': 0.92})
        self._line_h2 = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen('#006688', width=1, style=QtCore.Qt.DashLine),
            label='2×', labelOpts={'color': '#006688', 'position': 0.85})
        self._line_h3 = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen('#004455', width=1, style=QtCore.Qt.DashLine),
            label='3×', labelOpts={'color': '#004455', 'position': 0.78})
        for item in [self._line_peak, self._line_h2, self._line_h3]:
            self.p_fft.addItem(item)

        # Right: two stacked plots
        right_gw = pg.GraphicsLayoutWidget()
        self.p_sig = right_gw.addPlot(
            row=0, col=0,
            title="<b style='color:#AAFFAA'>LP-FILTERED SIGNAL (input to FFT)</b>")
        self.p_sig.setLabel('bottom', 'Sample')
        self.p_sig.showGrid(x=True, y=True, alpha=0.3)
        self.curve_sig = self.p_sig.plot(pen=pg.mkPen('#AAFFAA', width=1))

        self.p_hr_cmp = right_gw.addPlot(
            row=1, col=0,
            title="<b style='color:#FFFFFF'>HR COMPARISON (bpm)</b>")
        self.p_hr_cmp.setLabel('bottom', 'Sample')
        self.p_hr_cmp.setYRange(40, 180)
        self.p_hr_cmp.showGrid(x=True, y=True, alpha=0.3)
        self.curve_hr1_cmp = self.p_hr_cmp.plot(pen=pg.mkPen('#FFDD44', width=2),  name="HR1")
        self.curve_hr2_cmp = self.p_hr_cmp.plot(pen=pg.mkPen('#FF4444', width=1.5), name="HR2")
        self.curve_hr3_cmp = self.p_hr_cmp.plot(pen=pg.mkPen('#00CCFF', width=2),  name="HR3")

        left_gw.setMinimumWidth(0)
        right_gw.setMinimumWidth(0)
        self._splitter.setMinimumWidth(0)
        self._splitter.addWidget(left_gw)
        self._splitter.addWidget(right_gw)

        # ── info bar ─────────────────────────────────────────────────────────────
        self._info_label = QtWidgets.QLabel()
        self._info_label.setFont(QtGui.QFont("Consolas", 10))
        self._info_label.setStyleSheet("color: #AAAAAA; padding: 2px 4px;")
        self._info_label.setMinimumWidth(0)
        self._info_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        outer.addWidget(self._info_label)
        self._refresh_info(None)

        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("HR3LabWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1800, 900)

    def _refresh_info(self, calc):
        if calc is None or calc._fs == 0.0:
            self._info_label.setText(
                "HR3 params: LP 10 Hz · BUF 512 · Hann · update 0.5 s · band [0.5–3.5 Hz]   |   waiting for data...")
            return
        freq_res_bpm = (calc._fs / calc.BUF_LEN) * 60.0
        buf_pct      = 100.0 * calc._buf_count / calc.BUF_LEN
        self._info_label.setText(
            f"LP {calc.LP_CUTOFF_HZ:.0f} Hz · BUF {calc.BUF_LEN} · Hann · "
            f"update {calc.UPDATE_INTERVAL_S:.1f} s · band [{calc.HR_MIN_HZ:.1f}–{calc.HR_MAX_HZ:.1f} Hz]   |   "
            f"freq_res {freq_res_bpm:.1f} BPM/bin · "
            f"peak {calc.last_peak_freq:.3f} Hz = {calc.last_peak_freq * 60:.1f} BPM · "
            f"harmonic_ratio {calc.last_harmonic_ratio * 100:.1f}% · "
            f"buf {buf_pct:.0f}%")

    def update_plots(self, data_hr1, data_hr2, data_hr3, calc):
        self._refresh_info(calc)

        if len(calc.last_freqs) > 1:
            self.curve_fft.setData(calc.last_freqs, calc.last_spectrum)
            hr_mask  = (calc.last_freqs >= calc.HR_SEARCH_MIN_HZ) & (calc.last_freqs <= calc.HR_SEARCH_MAX_HZ)
            hps_band = calc.last_hps[hr_mask]
            hps_max  = float(np.max(hps_band)) if len(hps_band) > 0 and np.max(hps_band) > 0.0 else 1.0
            self.curve_hps.setData(calc.last_freqs, calc.last_hps / hps_max)
            self._line_peak.setValue(calc.last_peak_freq)
            self._line_h2.setValue(calc.last_peak_freq * 2.0)
            self._line_h3.setValue(calc.last_peak_freq * 3.0)
            self.p_fft.setTitle(
                f"<b style='color:#00CCFF'>FFT SPECTRUM</b>  "
                f"<span style='color:#AAAAAA'>peak {calc.last_peak_freq:.3f} Hz = "
                f"{calc.last_peak_freq * 60:.1f} BPM · "
                f"harmonic_ratio {calc.last_harmonic_ratio * 100:.1f}%</span>")

        if calc._buf_count > 0:
            self.curve_sig.setData(calc.last_filtered_buf)

        self.curve_hr1_cmp.setData(np.array(data_hr1))
        self.curve_hr2_cmp.setData(np.array(data_hr2))
        self.curve_hr3_cmp.setData(np.array(data_hr3))

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, lambda: self._splitter.setSizes([1100, 700]))

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("HR3LabWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hr3lab.setChecked(False)
            self.main_monitor.hr3lab_window = None
        super().closeEvent(event)


class _ResizableGraphicsLayout(pg.GraphicsLayoutWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'ci'):
            return
        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            self.ci.setGeometry(QtCore.QRectF(0, 0, w, h))


class HRLabWindow(QtWidgets.QMainWindow):
    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("HR2LAB")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic;")
        self.statusBar().showMessage(_MOUSE_HINT)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # QSplitter for exact column proportions (1:1:1)
        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.setHandleWidth(2)
        main_layout.addWidget(self._splitter)

        self._col_a = _ResizableGraphicsLayout()
        self._col_b = _ResizableGraphicsLayout()
        self._col_c = _ResizableGraphicsLayout()
        self._splitter.addWidget(self._col_a)
        self._splitter.addWidget(self._col_b)
        self._splitter.addWidget(self._col_c)

        # Column A
        self.p_1a = self._col_a.addPlot(row=0, col=0, title="<span style='color:#AAAAFF'>PPG(original)</span>")
        self.curve_1a = self.p_1a.plot(pen=pg.mkPen('#AAAAFF', width=1.5))
        self.p_1a.showGrid(x=True, y=True, alpha=0.3)

        self.p_2a = self._col_a.addPlot(row=1, col=0, title="<span style='color:#FF88FF'>PPG(0.5–3.7 Hz)</span>")
        self.curve_2a = self.p_2a.plot(pen=pg.mkPen('#FF88FF', width=1.5))
        self.p_2a.showGrid(x=True, y=True, alpha=0.3)
        self.p_2a.setXLink(self.p_1a)

        # Column B
        self.p_1b = self._col_b.addPlot(row=0, col=0, title="<span style='color:#AAAAFF'>1B</span>")
        self.curve_1b = self.p_1b.plot(pen=pg.mkPen('#AAAAFF', width=1.5))
        self.p_1b.showGrid(x=True, y=True, alpha=0.3)
        self.p_1b.setYRange(-1.0, 1.0)
        self.vline_1b = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen('#FFDD44', width=2))
        self.vline_1b.setVisible(False)
        self.p_1b.addItem(self.vline_1b)

        self.p_2b = self._col_b.addPlot(row=1, col=0, title="<span style='color:#FF88FF'>2B</span>")
        self.curve_2b = self.p_2b.plot(pen=pg.mkPen('#FF88FF', width=1.5))
        self.p_2b.showGrid(x=True, y=True, alpha=0.3)
        self.p_2b.setYRange(-1.0, 1.0)
        self.vline_2b = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen('#FFDD44', width=2))
        self.vline_2b.setVisible(False)
        self.p_2b.addItem(self.vline_2b)

        # Column C
        self.p_1c = self._col_c.addPlot(row=0, col=0, title="<span style='color:#AAAAFF'>1C</span>")
        self.curve_1c = self.p_1c.plot(pen=pg.mkPen('#AAAAFF', width=1.5))
        self.p_1c.showGrid(x=True, y=True, alpha=0.3)
        self.p_1c.setYRange(-1.0, 1.0)
        self.vline_1c = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen('#FFDD44', width=2))
        self.vline_1c.setVisible(False)
        self.p_1c.addItem(self.vline_1c)

        self.p_2c = self._col_c.addPlot(row=1, col=0, title="<span style='color:#FF88FF'>2C</span>")
        self.curve_2c = self.p_2c.plot(pen=pg.mkPen('#FF88FF', width=1.5))
        self.p_2c.showGrid(x=True, y=True, alpha=0.3)
        self.p_2c.setYRange(-1.0, 1.0)
        self.vline_2c = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen('#FFDD44', width=2))
        self.vline_2c.setVisible(False)
        self.p_2c.addItem(self.vline_2c)

        for p in [self.p_1a, self.p_2a,
                  self.p_1b, self.p_2b,
                  self.p_1c, self.p_2c]:
            p.setMinimumWidth(0)
            p.getViewBox().setMinimumWidth(0)

        self._hr_refresh_counter = 0

        # Stateful incunest biquad filter state
        self._incunest_zi         = None   # biquad state (2 floats)
        self._incunest_filt_buf   = deque([0.0] * WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self._last_sample_cnt = None
        self._incunest_fs_cached  = None
        self._incunest_ba_cached  = None   # cached (b, a) coefficients — recomputed only when fs changes

        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("HRLabWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(2400, 450)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._set_splitter_sizes)
        self._dbg_timer = QtCore.QTimer()
        self._dbg_timer.timeout.connect(self._dbg_print_ranges)
        self._dbg_timer.start(1000)

    def _dbg_print_ranges(self):
        vr = self.p_1b.viewRange()
        ar = self.p_1b.getViewBox().state['autoRange']
        col_w = self._col_b.width()
        vb_w  = self.p_1b.getViewBox().width()
        print(f"[DBG] p_1b viewRange={vr[0]}  autoRange={ar}  col_b.width={col_w}  vb.width={vb_w:.0f}", flush=True)

    def _set_splitter_sizes(self):
        w = self._splitter.width()
        if w > 0:
            col_a = int(w * 0.42)
            col_bc = (w - col_a) // 2
            self._splitter.setSizes([col_a, col_bc, w - col_a - col_bc])

    @staticmethod
    def _incunest_biquad_coeffs(fs, f_low, f_high):
        """Replicate incunest_afe4490::_recalc_biquad() exactly (bilinear transform)."""
        k    = 2.0 * fs
        o_low = k * np.tan(np.pi * f_low  / fs)
        o_hi  = k * np.tan(np.pi * f_high / fs)
        o0sq  = o_low * o_hi
        bw    = o_hi - o_low
        d     = k*k + bw*k + o0sq
        b = np.array([ bw*k/d,  0.0, -bw*k/d])
        a = np.array([1.0, 2.0*(o0sq - k*k)/d, (k*k - bw*k + o0sq)/d])
        return b, a

    def update_plots(self, ppg_data, timestamp_us_data, sample_counter_data):
        data = np.array(ppg_data)
        self.curve_1a.setData(data)

        fs = 50.0  # AFE4490 @ 500 Hz, SERIAL_DOWNSAMPLING_RATIO=10

        nyq = fs / 2.0
        high_norm = 3.7 / nyq

        # Plot 2A: incunest_afe4490 biquad — stateful, processes only new samples
        incunest_filtered = None
        if high_norm < 1.0:
            try:
                # Recompute coefficients only when fs changes
                if fs != self._incunest_fs_cached or self._incunest_ba_cached is None:
                    self._incunest_ba_cached = self._incunest_biquad_coeffs(fs, 0.5, 3.7)
                    self._incunest_fs_cached = fs
                    self._incunest_zi = None   # force filter reset on coefficient change
                b, a = self._incunest_ba_cached

                cur_cnt = int(sample_counter_data[-1])
                reset = self._incunest_zi is None or self._last_sample_cnt is None

                if not reset:
                    n_new = (cur_cnt - self._last_sample_cnt) // 10  # SERIAL_DOWNSAMPLING_RATIO=10
                    if n_new <= 0 or n_new > len(data):
                        reset = True

                if reset:
                    # First call or anomaly: warm up on full buffer
                    zi_init = signal.lfilter_zi(b, a) * data[0]
                    full_out, self._incunest_zi = signal.lfilter(b, a, data, zi=zi_init)
                    self._incunest_filt_buf = deque(full_out, maxlen=WINDOW_SIZE)
                else:
                    new_samples = data[-n_new:]
                    new_out, self._incunest_zi = signal.lfilter(b, a, new_samples, zi=self._incunest_zi)
                    self._incunest_filt_buf.extend(new_out)

                self._last_sample_cnt = cur_cnt
                incunest_filtered = np.array(self._incunest_filt_buf)
                self.curve_2a.setData(incunest_filtered)
            except Exception:
                pass

        # Plots 4 & 5: autocorrelation-based HR, refreshed at 5 Hz
        self._hr_refresh_counter += 1
        refresh_every = max(1, int(round(fs / 5.0)))
        if self._hr_refresh_counter >= refresh_every and incunest_filtered is not None:
            self._hr_refresh_counter = 0
            window_n  = int(round(4.0 * fs))
            max_lag_n = int(round((60.0 / 22.0) * fs))  # covers guard band minimum 22 BPM
            needed    = window_n + max_lag_n
            max_lag_s = max_lag_n / fs

            _HR_COLOR = {
                HRStatus.VALID:        '#FFDD44',
                HRStatus.OUT_OF_RANGE: '#FF4444',
                HRStatus.INVALID:      '#888888',
            }

            # Plot 1B: xcorr_v1 on raw PPG
            if len(data) >= needed:
                try:
                    r = _estimate_hr_xcorr_v1(data[-needed:], fs, max_lag_n)
                    hr_color = _HR_COLOR[r.hr_status]
                    self.curve_1b.setData(r.lags_s, r.acorr)
                    self.p_1b.setXRange(0, max_lag_s)
                    self.p_1b.setTitle(
                        f"<span style='color:#AAAAFF'>xcorr_v1 &nbsp;|&nbsp; </span>"
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.2f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
                    )
                    self.vline_1b.setPen(pg.mkPen(hr_color, width=2))
                    self.vline_1b.setPos(r.peak_lag)
                    self.vline_1b.setVisible(True)
                except Exception:
                    pass

            # Plot 2B: xcorr_v1 on incunest BPF
            if len(incunest_filtered) >= needed:
                try:
                    r = _estimate_hr_xcorr_v1(incunest_filtered[-needed:], fs, max_lag_n)
                    hr_color = _HR_COLOR[r.hr_status]
                    self.curve_2b.setData(r.lags_s, r.acorr)
                    self.p_2b.setXRange(0, max_lag_s)
                    self.p_2b.setTitle(
                        f"<span style='color:#FF88FF'>xcorr_v1 &nbsp;|&nbsp; </span>"
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.2f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
                    )
                    self.vline_2b.setPen(pg.mkPen(hr_color, width=2))
                    self.vline_2b.setPos(r.peak_lag)
                    self.vline_2b.setVisible(True)
                except Exception:
                    pass

            # Plot 1C: autocorr_v2 on raw PPG (single vector, only window_n samples)
            if len(data) >= window_n:
                try:
                    r = _estimate_hr_autocorr_v2(data[-window_n:], fs, max_lag_n)
                    hr_color = _HR_COLOR[r.hr_status]
                    self.curve_1c.setData(r.lags_s, r.acorr)
                    self.p_1c.setXRange(0, max_lag_s)
                    self.p_1c.setTitle(
                        f"<span style='color:#AAAAFF'>autocorr_v2 &nbsp;|&nbsp; </span>"
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.2f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
                    )
                    self.vline_1c.setPen(pg.mkPen(hr_color, width=2))
                    self.vline_1c.setPos(r.peak_lag)
                    self.vline_1c.setVisible(True)
                except Exception:
                    pass

            # Plot 2C: autocorr_v2 on incunest BPF (single vector, only window_n samples)
            if len(incunest_filtered) >= window_n:
                try:
                    r = _estimate_hr_autocorr_v2(incunest_filtered[-window_n:], fs, max_lag_n)
                    hr_color = _HR_COLOR[r.hr_status]
                    self.curve_2c.setData(r.lags_s, r.acorr)
                    self.p_2c.setXRange(0, max_lag_s)
                    self.p_2c.setTitle(
                        f"<span style='color:#FF88FF'>autocorr_v2 &nbsp;|&nbsp; </span>"
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.2f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
                    )
                    self.vline_2c.setPen(pg.mkPen(hr_color, width=2))
                    self.vline_2c.setPos(r.peak_lag)
                    self.vline_2c.setVisible(True)
                except Exception:
                    pass

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("HRLabWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hrlab.setChecked(False)
            self.main_monitor.hrlab_window = None
        event.accept()


class PPGPlotsWindow(QtWidgets.QWidget):
    """Floating window with all PPG/SpO2/HR plots and LED2 (RED)/LED1 (IR) channel checkboxes."""

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("PPG Plots")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self._setup_ui()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("PPGPlotsWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1800, 900)
        self.check_led2_raw.setChecked(s.value("PPGPlotsWindow/check_led2_raw", False, type=bool))
        self.check_aled2.setChecked(s.value("PPGPlotsWindow/check_aled2", False, type=bool))
        self.check_led2_sub.setChecked(s.value("PPGPlotsWindow/check_led2_sub", True,  type=bool))
        self.check_led1_raw.setChecked( s.value("PPGPlotsWindow/check_led1_raw",  False, type=bool))
        self.check_aled1.setChecked( s.value("PPGPlotsWindow/check_aled1",  False, type=bool))
        self.check_led1_sub.setChecked( s.value("PPGPlotsWindow/check_led1_sub",  True,  type=bool))

    def _setup_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        root = QtWidgets.QHBoxLayout()
        outer.addLayout(root)

        hint = QtWidgets.QLabel(_MOUSE_HINT)
        hint.setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic; padding: 2px 6px;")

        # ── Checkbox sidebar ──────────────────────────────────────────────────
        sidebar = QtWidgets.QVBoxLayout()

        def create_check(label, color, checked):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {color}; font-size: 16px; padding: 2px; }}
                QCheckBox::indicator {{
                    width: 24px; height: 24px; border: 2px solid #555555;
                    border-radius: 4px; background-color: #1A1A1A;
                }}
                QCheckBox::indicator:checked {{
                    background-color: #666666; border: 2px solid #BBBBBB;
                    image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdUlEQVR4nO2UQQ7AIAgEWf//5+21aYQFIpfGvRhJnFGJgqRNfGjrwiqCdKzCVB2DRAFC22RnWoAAAAAElFTkSuQmCC");
                }}
            """)
            return cb

        lbl_ir = QtWidgets.QLabel("LED1 (IR)")
        lbl_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 10px;")
        sidebar.addWidget(lbl_ir)
        self.check_led1_raw  = create_check("LED1 (IR)",     "#FFFFFF", False)
        self.check_aled1  = create_check("Ambient LED1",   "#00FFFF", False)
        self.check_led1_sub  = create_check("LED1 (IR) clean",   "#88CCFF", True)
        self.check_led1_raw.setToolTip(_make_tooltip(
            "LED1 (IR)",
            "Raw IR LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: LED1 in the M1 frame.",
            src="AFE4490Data::led1_raw"))
        self.check_aled1.setToolTip(_make_tooltip(
            "Ambient LED1",
            "Ambient light sampled during the IR LED off period (aled1). "
            "Represents environmental light interference on the LED1 (IR) channel.",
            src="AFE4490Data::aled1"))
        self.check_led1_sub.setToolTip(_make_tooltip(
            "LED1 (IR) clean",
            "LED1 minus ambient: LED1 − ALED1. Ambient-subtracted IR signal. "
            "Primary input to the HR algorithms (HR1, HR2, HR3). Field: LED1_SUB.",
            src="AFE4490Data::led1_sub"))
        for w in (self.check_led1_raw, self.check_aled1, self.check_led1_sub):
            sidebar.addWidget(w)

        lbl_red = QtWidgets.QLabel("LED2 (RED)")
        lbl_red.setStyleSheet("color: #FF4444; font-weight: 800; font-size: 20px; margin-top: 20px;")
        sidebar.addWidget(lbl_red)
        self.check_led2_raw  = create_check("LED2 (RED)",    "#FFFFFF", False)
        self.check_aled2  = create_check("Ambient LED2",  "#00FFFF", False)
        self.check_led2_sub  = create_check("LED2 (RED) clean",  "#FF8888", True)
        self.check_led2_raw.setToolTip(_make_tooltip(
            "LED2 (RED)",
            "Raw RED LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: LED2 in the M1 frame.",
            src="AFE4490Data::led2_raw"))
        self.check_aled2.setToolTip(_make_tooltip(
            "Ambient LED2",
            "Ambient light sampled during the RED LED off period (aled2). "
            "Represents environmental light interference on the LED2 (RED) channel.",
            src="AFE4490Data::aled2"))
        self.check_led2_sub.setToolTip(_make_tooltip(
            "LED2 (RED) clean",
            "LED2 minus ambient: LED2 − ALED2. Ambient-subtracted RED signal. "
            "Primary input to the SpO2 algorithm. Field: LED2_SUB.",
            src="AFE4490Data::led2_sub"))
        for w in (self.check_led2_raw, self.check_aled2, self.check_led2_sub):
            sidebar.addWidget(w)

        sidebar.addStretch()
        sb_widget = QtWidgets.QWidget()
        sb_widget.setLayout(sidebar)
        sb_widget.setFixedWidth(180)
        root.addWidget(sb_widget)

        # ── Plots ─────────────────────────────────────────────────────────────
        plots_vbox = QtWidgets.QVBoxLayout()
        plots_vbox.setContentsMargins(0, 0, 0, 0)
        plots_vbox.setSpacing(0)
        root.addLayout(plots_vbox)

        # Top two rows: LED2 (RED) and LED1 (IR) in a GraphicsLayoutWidget
        self.graphics_layout = pg.GraphicsLayoutWidget()
        plots_vbox.addWidget(self.graphics_layout, stretch=1)

        self.p1 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>LED1 (IR)</b>")
        self.curve_led1      = self.p1.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="LED1 (IR)")
        self.curve_aled1  = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient LED1")
        self.curve_led1_sub  = self.p1.plot(pen=pg.mkPen('#88CCFF', width=1.5), name="LED1 (IR) clean")
        self.p1.showGrid(x=True, y=True, alpha=0.3)

        self.graphics_layout.nextRow()

        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#FF4444'>LED2 (RED)</b>")
        self.curve_led2      = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="LED2 (RED)")
        self.curve_aled2  = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient LED2")
        self.curve_led2_sub  = self.p2.plot(pen=pg.mkPen('#FF8888', width=1.5), name="LED2 (RED) clean")
        self.p2.showGrid(x=True, y=True, alpha=0.3)

        # Bottom row: PPG | SpO2 | HR in a plain QHBoxLayout with pg.PlotWidget
        # Qt distributes QHBoxLayout space evenly by default — guaranteed equal widths.
        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(0)
        plots_vbox.addLayout(bottom_row, stretch=1)

        w_ppg = pg.PlotWidget(title="<b style='color:#FFFFFF'>PPG</b>")
        w_ppg.setBackground('#121212')
        self.p_ppg = w_ppg.plotItem
        self.curve_ppg = self.p_ppg.plot(pen=pg.mkPen('#FFFFFF', width=2))
        self.p_ppg.showGrid(x=True, y=True, alpha=0.3)
        bottom_row.addWidget(w_ppg)

        w_spo2 = pg.PlotWidget(title="<b style='color:#44FF88'>SpO2 (%)</b>")
        w_spo2.setBackground('#121212')
        self.p_spo2 = w_spo2.plotItem
        self.curve_spo2 = self.p_spo2.plot(pen=pg.mkPen('#44FF88', width=3))
        self.p_spo2.setYRange(50, 100)
        bottom_row.addWidget(w_spo2)

        w_hr = pg.PlotWidget(title="<b style='color:#FFDD44'>HEART RATE (BPM)</b>")
        w_hr.setBackground('#121212')
        self.p_hr = w_hr.plotItem
        self.curve_hr1 = self.p_hr.plot(pen=pg.mkPen('#FFDD44', width=3),  name="HR1")
        self.curve_hr2 = self.p_hr.plot(pen=pg.mkPen('#FF4444', width=1.5), name="HR2")
        self.curve_hr3 = self.p_hr.plot(pen=pg.mkPen('#00CCFF', width=1.5), name="HR3")
        self.p_hr.setYRange(40, 180)
        bottom_row.addWidget(w_hr)

        # ── Checkbox → curve visibility ───────────────────────────────────────
        self.check_led2_raw.stateChanged.connect(lambda: self.curve_led2.setVisible(self.check_led2_raw.isChecked()))
        self.check_aled2.stateChanged.connect(lambda: self.curve_aled2.setVisible(self.check_aled2.isChecked()))
        self.check_led2_sub.stateChanged.connect(lambda: self.curve_led2_sub.setVisible(self.check_led2_sub.isChecked()))
        self.check_led1_raw.stateChanged.connect( lambda: self.curve_led1.setVisible(self.check_led1_raw.isChecked()))
        self.check_aled1.stateChanged.connect( lambda: self.curve_aled1.setVisible(self.check_aled1.isChecked()))
        self.check_led1_sub.stateChanged.connect( lambda: self.curve_led1_sub.setVisible(self.check_led1_sub.isChecked()))

        self.curve_led2.setVisible(False)
        self.curve_aled2.setVisible(False)
        self.curve_led2_sub.setVisible(True)
        self.curve_led1.setVisible(False)
        self.curve_aled1.setVisible(False)
        self.curve_led1_sub.setVisible(True)

        outer.addWidget(hint)

    def update_plots(self, data_ppgdisp, data_hr1, data_hr2, data_hr3,
                     data_spo2, data_spo2_sqi, data_spo2_r,
                     data_hr1_sqi, data_hr2_sqi, data_hr3_sqi,
                     data_led2, data_led1,
                     data_aled2, data_aled1, data_led2_sub, data_led1_sub):
        self.p_spo2.setTitle(
            f"<b style='color:#44FF88'>SpO2: {data_spo2[-1]:.1f} %</b>"
            f" &nbsp; <b style='color:#888888'>SQI: {data_spo2_sqi[-1]:.2f}</b>"
            f" &nbsp; <b style='color:#AAAAAA'>R: {data_spo2_r[-1]:.4f}</b>")
        self.p_hr.setTitle(
            f"<b style='color:#FFDD44'>HR1: {data_hr1[-1]:.1f}</b><b style='color:#888888'> [{data_hr1_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#FF4444'>HR2: {data_hr2[-1]:.1f}</b><b style='color:#888888'> [{data_hr2_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#00CCFF'>HR3: {data_hr3[-1]:.1f}</b><b style='color:#888888'> [{data_hr3_sqi[-1]:.2f}]</b>"
            f" <b style='color:#AAAAAA'>bpm</b>")
        self.curve_ppg.setData(list(data_ppgdisp)[-PPG_WINDOW_SIZE:])
        self.curve_spo2.setData(list(data_spo2))
        self.curve_hr1.setData(list(data_hr1))
        self.curve_hr2.setData(list(data_hr2))
        self.curve_hr3.setData(list(data_hr3))
        self.curve_led2.setData(list(data_led2))
        self.curve_led1.setData(list(data_led1))
        self.curve_aled2.setData(list(data_aled2))
        self.curve_aled1.setData(list(data_aled1))
        self.curve_led2_sub.setData(list(data_led2_sub))
        self.curve_led1_sub.setData(list(data_led1_sub))

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PPGPlotsWindow/geometry",    self.saveGeometry())
        s.setValue("PPGPlotsWindow/check_led2_raw",  self.check_led2_raw.isChecked())
        s.setValue("PPGPlotsWindow/check_aled2",  self.check_aled2.isChecked())
        s.setValue("PPGPlotsWindow/check_led2_sub",  self.check_led2_sub.isChecked())
        s.setValue("PPGPlotsWindow/check_led1_raw",   self.check_led1_raw.isChecked())
        s.setValue("PPGPlotsWindow/check_aled1",   self.check_aled1.isChecked())
        s.setValue("PPGPlotsWindow/check_led1_sub",   self.check_led1_sub.isChecked())
        if self.main_monitor is not None:
            self.main_monitor.btn_ppgplots.setChecked(False)
            self.main_monitor.ppgplots_window = None
        super().closeEvent(event)


class PPGSignalsWindow(QtWidgets.QWidget):
    """Floating window with the 6 raw AFE4490 signals (LED2/LED1 raw·amb·sub) and PPG_DISP."""

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("PPG Signals")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self._setup_ui()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("PPGSignalsWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1400, 900)
        self.check_led2_raw.setChecked(s.value("PPGSignalsWindow/check_led2_raw", False, type=bool))
        self.check_aled2.setChecked(s.value("PPGSignalsWindow/check_aled2", False, type=bool))
        self.check_led2_sub.setChecked(s.value("PPGSignalsWindow/check_led2_sub", True,  type=bool))
        self.check_led1_raw.setChecked( s.value("PPGSignalsWindow/check_led1_raw",  False, type=bool))
        self.check_aled1.setChecked( s.value("PPGSignalsWindow/check_aled1",  False, type=bool))
        self.check_led1_sub.setChecked( s.value("PPGSignalsWindow/check_led1_sub",  True,  type=bool))

    def _setup_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        root = QtWidgets.QHBoxLayout()
        outer.addLayout(root)

        hint = QtWidgets.QLabel(_MOUSE_HINT)
        hint.setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic; padding: 2px 6px;")

        # ── Checkbox sidebar ──────────────────────────────────────────────────
        sidebar = QtWidgets.QVBoxLayout()

        def create_check(label, color, checked):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {color}; font-size: 16px; padding: 2px; }}
                QCheckBox::indicator {{
                    width: 24px; height: 24px; border: 2px solid #555555;
                    border-radius: 4px; background-color: #1A1A1A;
                }}
                QCheckBox::indicator:checked {{
                    background-color: #666666; border: 2px solid #BBBBBB;
                    image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdUlEQVR4nO2UQQ7AIAgEWf//5+21aYQFIpfGvRhJnFGJgqRNfGjrwiqCdKzCVB2DRAFC22RnWoAAAAAElFTkSuQmCC");
                }}
            """)
            return cb

        lbl_ir = QtWidgets.QLabel("LED1 (IR)")
        lbl_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 10px;")
        sidebar.addWidget(lbl_ir)
        self.check_led1_raw = create_check("LED1 (IR)",    "#FFFFFF", False)
        self.check_aled1 = create_check("Ambient LED1",  "#00FFFF", False)
        self.check_led1_sub = create_check("LED1 (IR) clean",  "#88CCFF", True)
        self.check_led1_raw.setToolTip(_make_tooltip(
            "LED1 (IR)",
            "Raw IR LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: LED1 in the M1 frame.",
            src="AFE4490Data::led1_raw"))
        self.check_aled1.setToolTip(_make_tooltip(
            "Ambient LED1",
            "Ambient light sampled during the IR LED off period (aled1). "
            "Represents environmental light interference on the LED1 (IR) channel.",
            src="AFE4490Data::aled1"))
        self.check_led1_sub.setToolTip(_make_tooltip(
            "LED1 (IR) clean",
            "LED1 minus ambient: LED1 − ALED1. Ambient-subtracted IR signal. "
            "Primary input to the HR algorithms (HR1, HR2, HR3). Field: LED1_SUB.",
            src="AFE4490Data::led1_sub"))
        for w in (self.check_led1_raw, self.check_aled1, self.check_led1_sub):
            sidebar.addWidget(w)

        lbl_red = QtWidgets.QLabel("LED2 (RED)")
        lbl_red.setStyleSheet("color: #FF4444; font-weight: 800; font-size: 20px; margin-top: 20px;")
        sidebar.addWidget(lbl_red)
        self.check_led2_raw = create_check("LED2 (RED)",   "#FFFFFF", False)
        self.check_aled2 = create_check("Ambient LED2", "#00FFFF", False)
        self.check_led2_sub = create_check("LED2 (RED) clean", "#FF8888", True)
        self.check_led2_raw.setToolTip(_make_tooltip(
            "LED2 (RED)",
            "Raw RED LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: LED2 in the M1 frame.",
            src="AFE4490Data::led2_raw"))
        self.check_aled2.setToolTip(_make_tooltip(
            "Ambient LED2",
            "Ambient light sampled during the RED LED off period (aled2). "
            "Represents environmental light interference on the LED2 (RED) channel.",
            src="AFE4490Data::aled2"))
        self.check_led2_sub.setToolTip(_make_tooltip(
            "LED2 (RED) clean",
            "LED2 minus ambient: LED2 − ALED2. Ambient-subtracted RED signal. "
            "Primary input to the SpO2 algorithm. Field: LED2_SUB.",
            src="AFE4490Data::led2_sub"))
        for w in (self.check_led2_raw, self.check_aled2, self.check_led2_sub):
            sidebar.addWidget(w)

        sidebar.addStretch()
        sb_widget = QtWidgets.QWidget()
        sb_widget.setLayout(sidebar)
        sb_widget.setFixedWidth(180)
        root.addWidget(sb_widget)

        # ── Plots: LED2 (RED) / LED1 (IR) / PPG_DISP in a single GraphicsLayoutWidget ────────
        self.graphics_layout = pg.GraphicsLayoutWidget()
        root.addWidget(self.graphics_layout)

        self.p1 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>LED1 (IR)</b>")
        self.curve_led1     = self.p1.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="LED1 (IR)")
        self.curve_aled1 = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient LED1")
        self.curve_led1_sub = self.p1.plot(pen=pg.mkPen('#88CCFF', width=1.5), name="LED1 (IR) clean")
        self.p1.showGrid(x=True, y=True, alpha=0.3)
        self.p1.getAxis('left').setWidth(80)

        self.graphics_layout.nextRow()

        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#FF4444'>LED2 (RED)</b>")
        self.curve_led2     = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="LED2 (RED)")
        self.curve_aled2 = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient LED2")
        self.curve_led2_sub = self.p2.plot(pen=pg.mkPen('#FF8888', width=1.5), name="LED2 (RED) clean")
        self.p2.showGrid(x=True, y=True, alpha=0.3)
        self.p2.getAxis('left').setWidth(80)

        self.graphics_layout.nextRow()

        self.p3 = self.graphics_layout.addPlot(title="<b style='color:#AAFFAA'>PPG_DISP</b>")
        self.curve_ppgdisp = self.p3.plot(pen=pg.mkPen('#AAFFAA', width=2), name="PPG_DISP")
        self.p3.showGrid(x=True, y=True, alpha=0.3)
        self.p3.getAxis('left').setWidth(80)

        # ── Checkbox → curve visibility ───────────────────────────────────────
        self.check_led2_raw.stateChanged.connect(lambda: self.curve_led2.setVisible(self.check_led2_raw.isChecked()))
        self.check_aled2.stateChanged.connect(lambda: self.curve_aled2.setVisible(self.check_aled2.isChecked()))
        self.check_led2_sub.stateChanged.connect(lambda: self.curve_led2_sub.setVisible(self.check_led2_sub.isChecked()))
        self.check_led1_raw.stateChanged.connect( lambda: self.curve_led1.setVisible(self.check_led1_raw.isChecked()))
        self.check_aled1.stateChanged.connect( lambda: self.curve_aled1.setVisible(self.check_aled1.isChecked()))
        self.check_led1_sub.stateChanged.connect( lambda: self.curve_led1_sub.setVisible(self.check_led1_sub.isChecked()))

        self.curve_led2.setVisible(False)
        self.curve_aled2.setVisible(False)
        self.curve_led2_sub.setVisible(True)
        self.curve_led1.setVisible(False)
        self.curve_aled1.setVisible(False)
        self.curve_led1_sub.setVisible(True)

        outer.addWidget(hint)

    def update_plots(self, data_led2, data_led1, data_aled2, data_aled1,
                     data_led2_sub, data_led1_sub, data_ppgdisp):
        self.curve_led2.setData(list(data_led2))
        self.curve_led1.setData(list(data_led1))
        self.curve_aled2.setData(list(data_aled2))
        self.curve_aled1.setData(list(data_aled1))
        self.curve_led2_sub.setData(list(data_led2_sub))
        self.curve_led1_sub.setData(list(data_led1_sub))
        self.curve_ppgdisp.setData(list(data_ppgdisp)[-PPG_WINDOW_SIZE:])

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PPGSignalsWindow/geometry",       self.saveGeometry())
        s.setValue("PPGSignalsWindow/check_led2_raw",  self.check_led2_raw.isChecked())
        s.setValue("PPGSignalsWindow/check_aled2",  self.check_aled2.isChecked())
        s.setValue("PPGSignalsWindow/check_led2_sub",  self.check_led2_sub.isChecked())
        s.setValue("PPGSignalsWindow/check_led1_raw",   self.check_led1_raw.isChecked())
        s.setValue("PPGSignalsWindow/check_aled1",   self.check_aled1.isChecked())
        s.setValue("PPGSignalsWindow/check_led1_sub",   self.check_led1_sub.isChecked())
        if self.main_monitor is not None:
            self.main_monitor.btn_signals.setChecked(False)
            self.main_monitor.signals_window = None
        super().closeEvent(event)


class AlgoResultsWindow(QtWidgets.QWidget):
    """Floating window with SpO2 (top) and HR1/HR2/HR3 (bottom) algorithm results."""

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("Algorithm Results")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self._setup_ui()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("AlgoResultsWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(900, 700)

    def _setup_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        hint = QtWidgets.QLabel(_MOUSE_HINT)
        hint.setStyleSheet("color: #FFAA44; font-size: 20px; font-style: italic; padding: 2px 6px;")

        self.graphics_layout = pg.GraphicsLayoutWidget()
        outer.addWidget(self.graphics_layout, stretch=1)

        self.p_spo2 = self.graphics_layout.addPlot(title="<b style='color:#44FF88'>SpO2 (%)</b>")
        self.curve_spo2 = self.p_spo2.plot(pen=pg.mkPen('#44FF88', width=3))
        self.p_spo2.setYRange(50, 100)
        self.p_spo2.showGrid(x=True, y=True, alpha=0.3)

        self.graphics_layout.nextRow()

        self.p_hr = self.graphics_layout.addPlot(title="<b style='color:#FFDD44'>HEART RATE (BPM)</b>")
        self.curve_hr1 = self.p_hr.plot(pen=pg.mkPen('#FFDD44', width=3),   name="HR1")
        self.curve_hr2 = self.p_hr.plot(pen=pg.mkPen('#FF4444', width=1.5), name="HR2")
        self.curve_hr3 = self.p_hr.plot(pen=pg.mkPen('#00CCFF', width=1.5), name="HR3")
        self.p_hr.setYRange(40, 180)
        self.p_hr.showGrid(x=True, y=True, alpha=0.3)

        outer.addWidget(hint)

    def update_plots(self, data_spo2, data_spo2_sqi, data_spo2_r,
                     data_hr1, data_hr2, data_hr3,
                     data_hr1_sqi, data_hr2_sqi, data_hr3_sqi):
        self.p_spo2.setTitle(
            f"<b style='color:#44FF88'>SpO2: {data_spo2[-1]:.1f} %</b>"
            f" &nbsp; <b style='color:#888888'>SQI: {data_spo2_sqi[-1]:.2f}</b>"
            f" &nbsp; <b style='color:#AAAAAA'>R: {data_spo2_r[-1]:.4f}</b>")
        self.p_hr.setTitle(
            f"<b style='color:#FFDD44'>HR1: {data_hr1[-1]:.1f}</b><b style='color:#888888'> [{data_hr1_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#FF4444'>HR2: {data_hr2[-1]:.1f}</b><b style='color:#888888'> [{data_hr2_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#00CCFF'>HR3: {data_hr3[-1]:.1f}</b><b style='color:#888888'> [{data_hr3_sqi[-1]:.2f}]</b>"
            f" <b style='color:#AAAAAA'>bpm</b>")
        self.curve_spo2.setData(list(data_spo2))
        self.curve_hr1.setData(list(data_hr1))
        self.curve_hr2.setData(list(data_hr2))
        self.curve_hr3.setData(list(data_hr3))

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("AlgoResultsWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_results.setChecked(False)
            self.main_monitor.results_window = None
        super().closeEvent(event)


class SerialComWindow(QtWidgets.QWidget):
    """Floating window with the raw serial stream console (serial/USB-CDC)."""

    SERIAL_HEADER = (
        f"{'Timestamp_PC':<15},{'Df_us':>5},"
        "FrameMode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState,V_TIA_LED1,V_TIA_LED2,V_TIA_ALED1,V_TIA_ALED2,I_PD_LED1,I_PD_LED2,I_PD_ALED1,I_PD_ALED2"
    )

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self._paused = False
        self.setWindowTitle("Serial COM")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self._setup_ui()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("SerialComWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1200, 400)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        top_bar = QtWidgets.QHBoxLayout()
        self.header_label = QtWidgets.QLabel(self.SERIAL_HEADER)
        self.header_label.setFont(QtGui.QFont("Consolas", 9))
        self.header_label.setWordWrap(False)
        self.header_label.setMinimumWidth(0)
        self.header_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.header_label.setStyleSheet("""
            QLabel {
                background-color: #1A1000; color: #FFAA00;
                padding: 5px 8px; border: 1px solid #FFAA00;
            }
        """)
        top_bar.addWidget(self.header_label, stretch=1)

        self.btn_pause = QtWidgets.QPushButton("PAUSE")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setFixedWidth(110)
        self.btn_pause.setStyleSheet(
            "QPushButton { background-color: #505050; color: #FFFFFF; font-weight: bold; "
            "border: 1px solid #888888; border-radius: 3px; padding: 4px; }"
            "QPushButton:checked { background-color: #CC6600; color: #FFFFFF; "
            "border: 1px solid #FF8800; }")
        self.btn_pause.setToolTip(_make_tooltip("PAUSE", "Freeze the console display. "
            "The queue keeps draining and algorithms keep running; only new lines stop appearing."))
        self.btn_pause.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self.btn_pause)
        layout.addLayout(top_bar)

        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console.setFont(QtGui.QFont("Consolas", 9))
        self.console.setStyleSheet("""
            background-color: #000000; color: #D09000;
            border: 1px solid #FFAA00; padding: 5px;
        """)
        layout.addWidget(self.console)

    def _toggle_pause(self):
        self._paused = self.btn_pause.isChecked()
        self.btn_pause.setText("RESUME" if self._paused else "PAUSE")

    def append_line(self, line):
        """Append a single line immediately (for status/error messages)."""
        if self._paused:
            return
        self.console.appendPlainText(line)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def append_lines(self, lines):
        """Batch append a list of lines (called from _process_frames_tick loop)."""
        if self._paused or not lines:
            return
        self.console.appendPlainText('\n'.join(lines))
        if self.console.blockCount() > 500:
            cursor = self.console.textCursor()
            cursor.movePosition(QtGui.QTextCursor.Start)
            cursor.select(QtGui.QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
        self.console.horizontalScrollBar().setValue(0)

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("SerialComWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_serialcom.setChecked(False)
            self.main_monitor.serialcom_window = None
        super().closeEvent(event)


class _ComboSpin(QtWidgets.QComboBox):
    """QComboBox with value()/setValue() matching QSpinBox API, for drop-in use
    in _param_spins alongside plain QSpinBox widgets.
    Assumes item 0 is always a 'None' sentinel: value() returns currentIndex()-1
    so that None=-1 and real items start at 0, preserving external index semantics."""
    def value(self):
        return self.currentIndex() - 1

    def setValue(self, v):
        self.setCurrentIndex(v + 1)


class AFESweepTestWindow(QtWidgets.QMainWindow):
    """Parametric sweep: sweeps (LED_mA x RF x RG x AMBDAC) for LED1 then LED2,
    recording raw ADC statistics (mean/min/max/pp/std) per combo to a CSV file.
    Total: 3^4 * 2 channels = 162 combos."""

    TIA_GAINS  = ["10K", "25K", "50K", "100K", "250K", "500K", "1M"]
    STG2_GAINS = ["0dB", "3.5dB", "6dB", "9.5dB", "12dB"]

    _SS_SPIN  = "background-color:#202020; color:#E0E0E0; font-size:24px;"
    _SS_COMBO = (
        "QComboBox { background-color:#202020; color:#E0E0E0; font-size:24px; }"
        "QComboBox QAbstractItemView { background-color:#202020; color:#E0E0E0;"
        " font-size:24px; selection-background-color:#404040; }"
    )
    _SS_SPIN_ACTIVE  = "background-color:#2A2000; color:#FFD060; font-size:24px; border:1px solid #FFB300;"
    _SS_COMBO_ACTIVE = (
        "QComboBox { background-color:#2A2000; color:#FFD060; font-size:24px; border:1px solid #FFB300; }"
        "QComboBox QAbstractItemView { background-color:#202020; color:#E0E0E0;"
        " font-size:24px; selection-background-color:#404040; }"
    )

    _SIGNALS = ["LED2", "LED1", "ALED2", "ALED1", "LED2_SUB", "LED1_SUB"]

    # ProbeState enum values (must match incunest_afe4490.h)
    _PROBE_STATES = [
        (0, "PROBE_DISCONNECTED"),
        (1, "PROBE_NOT_APPLIED"),
        (2, "PROBE_APPLIED"),
    ]

    _CSV_HEADER = [
        # ── probe_state check (first 3 columns) ───────────────────────────────
        "probe_state_expected", "probe_state_calculated", "probe_state_check",
        # ── existing columns ──────────────────────────────────────────────────
        "label",
        "datetime", "LED1mA", "LED2mA", "RF1", "RF2", "RG1", "RG2", "ambdac_uA", "n_samples",
        "LED2_mean",  "LED1_mean",  "ALED2_mean",  "ALED1_mean",  "LED2_Sub_mean",  "LED1_Sub_mean",
        "LED2_min",   "LED1_min",   "ALED2_min",   "ALED1_min",   "LED2_Sub_min",   "LED1_Sub_min",
        "LED2_max",   "LED1_max",   "ALED2_max",   "ALED1_max",   "LED2_Sub_max",   "LED1_Sub_max",
        "LED2_pp",    "LED1_pp",    "ALED2_pp",    "ALED1_pp",    "LED2_Sub_pp",    "LED1_Sub_pp",
        "LED2_std",   "LED1_std",   "ALED2_std",   "ALED1_std",   "LED2_Sub_std",   "LED1_Sub_std",
        "OT1", "OT2",
        # ── RSQM columns ──────────────────────────────────────────────────────
        "rsqi_ok_pct",
        "diag_code_mean", "diag_code_min", "diag_code_max",
        "probe_state_fw_mean", "probe_state_fw_min", "probe_state_fw_max",
        # ── V_TIA [V] × 4 signals — received from $M4 frame ─────────────────
        "V_TIA_LED1_mean",        "V_TIA_LED1_std",        "V_TIA_LED1_min",        "V_TIA_LED1_max",
        "V_TIA_LED2_mean",        "V_TIA_LED2_std",        "V_TIA_LED2_min",        "V_TIA_LED2_max",
        "V_TIA_ALED1_mean",       "V_TIA_ALED1_std",       "V_TIA_ALED1_min",       "V_TIA_ALED1_max",
        "V_TIA_ALED2_mean",       "V_TIA_ALED2_std",       "V_TIA_ALED2_min",       "V_TIA_ALED2_max",
        # ── I_PD [µA] × 4 signals — received from $M4 frame ─────────────────
        "I_PD_LED1_uA_mean",      "I_PD_LED1_uA_std",      "I_PD_LED1_uA_min",      "I_PD_LED1_uA_max",
        "I_PD_LED2_uA_mean",      "I_PD_LED2_uA_std",      "I_PD_LED2_uA_min",      "I_PD_LED2_uA_max",
        "I_PD_ALED1_uA_mean",     "I_PD_ALED1_uA_std",     "I_PD_ALED1_uA_min",     "I_PD_ALED1_uA_max",
        "I_PD_ALED2_uA_mean",     "I_PD_ALED2_uA_std",     "I_PD_ALED2_uA_min",     "I_PD_ALED2_uA_max",
        # ── I_PD differential LED−ALED [µA] ─────────────────────────────────
        "I_PD_LED1_ALED1_diff_uA_mean", "I_PD_LED1_ALED1_diff_uA_std", "I_PD_LED1_ALED1_diff_uA_min", "I_PD_LED1_ALED1_diff_uA_max",
        "I_PD_LED2_ALED2_diff_uA_mean", "I_PD_LED2_ALED2_diff_uA_std", "I_PD_LED2_ALED2_diff_uA_min", "I_PD_LED2_ALED2_diff_uA_max",
    ]  # 92 columns

    _ST_IDLE      = 0
    _ST_SETTLING  = 1
    _ST_MEASURING = 2

    # (key, label, lo, hi, [fix_def, var_min_def, var_mid_def, var_max_def])
    # FIX = value applied to this param while the OTHER channel is being swept.
    # VAR min/mid/max = the three sweep values when THIS channel is being swept.
    # AMBDAC: FIX spin is disabled (AMBDAC is always swept for both channels).
    _PARAMS = [
        ("led1",   "LED1 mA (approx)",   0, 150, [20,  5,  20,  50]),
        ("led2",   "LED2 mA (approx)",   0, 150, [20,  5,  20,  50]),
        ("rf1",    "RF1 idx",   0,   6, [ 4,  2,   4,   6]),
        ("rf2",    "RF2 idx",   0,   6, [ 4,  2,   4,   6]),
        ("rg1",    "RG1 idx",   0,   4, [ 2,  0,   2,   4]),
        ("rg2",    "RG2 idx",   0,   4, [ 2,  0,   2,   4]),
        ("ambdac", "AMBDAC uA", 0,  10, [ 3,  0,   3,   6]),
    ]

    def __init__(self, main_monitor):
        super().__init__(parent=None)
        self.main_monitor = main_monitor
        self.setWindowTitle("AFE SWEEP TEST")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0; font-size: 24px;")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("AFESweepTestWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(700, 640)
        self._state                = self._ST_IDLE
        self._combos               = []
        self._combo_idx            = 0
        self._buf                  = {sig: [] for sig in self._SIGNALS}
        self._buf["RSQI"]          = []
        self._buf["DIAG_CODE"]     = []
        self._buf["PROBE_STATE_FW"] = []
        self._buf["V_TIA_LED1"]   = []
        self._buf["V_TIA_LED2"]   = []
        self._buf["V_TIA_ALED1"]  = []
        self._buf["V_TIA_ALED2"]  = []
        self._buf["I_PD_LED1"]    = []
        self._buf["I_PD_LED2"]    = []
        self._buf["I_PD_ALED1"]   = []
        self._buf["I_PD_ALED2"]   = []
        self._probe_mismatch_count = 0
        self._settle_end           = 0.0   # monotonic seconds
        self._timer      = QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._setup_ui()
        self._restore_settings()

    def _setup_ui(self):
        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        root = QtWidgets.QVBoxLayout(w)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Parameter grid ────────────────────────────────────────────────────
        pg = QtWidgets.QGroupBox("Sweep Parameters")
        pg.setStyleSheet("QGroupBox { font-weight: bold; }")
        gl = QtWidgets.QGridLayout(pg)
        gl.setColumnStretch(0, 2)
        for col, lbl in enumerate(["", "FIX", "VAR min", "VAR mid", "VAR max"]):
            h = QtWidgets.QLabel(lbl)
            h.setAlignment(QtCore.Qt.AlignCenter)
            h.setStyleSheet("font-weight: bold;")
            gl.addWidget(h, 0, col)

        _SS_COMBO  = self._SS_COMBO
        _RF_ITEMS  = ["None"] + list(self.TIA_GAINS)
        _RG_ITEMS  = ["None"] + list(self.STG2_GAINS)
        _AMB_ITEMS = ["None"] + [f"{v} \u00b5A" for v in range(11)]
        _LED_ITEMS = ["None"] + [str(i) for i in range(256)]

        self._param_spins = {}  # key -> [fix_spin, var_min_spin, var_mid_spin, var_max_spin]
                           #   AMBDAC: [var_min_spin, var_mid_spin, var_max_spin] (no FIX)
        for row, (key, label, lo, hi, defaults) in enumerate(self._PARAMS, start=1):
            gl.addWidget(QtWidgets.QLabel(label), row, 0)
            spins = []
            # AMBDAC has no FIX (swept for both channels): leave col 1 empty
            start_col = 2 if key == "ambdac" else 1
            spin_vals = defaults[1:] if key == "ambdac" else defaults
            for col, val in zip(range(start_col, 5), spin_vals):
                s = _ComboSpin()
                if key.startswith("rf"):
                    items, w = _RF_ITEMS, 160
                elif key.startswith("rg"):
                    items, w = _RG_ITEMS, 145
                elif key.startswith("led"):
                    items, w = _LED_ITEMS, 90
                else:
                    items, w = _AMB_ITEMS, 130
                for item in items:
                    s.addItem(item)
                s.setCurrentIndex(val)
                s.setStyleSheet(_SS_COMBO)
                s.setFixedWidth(w)
                if col == 1:
                    s.setToolTip(_make_tooltip(
                        f"{label} FIX",
                        f"Value applied to {label} while the OTHER channel is being swept. "
                        f"Select 'None' to skip sending this parameter."))
                else:
                    names = ["VAR min", "VAR mid", "VAR max"]
                    s.setToolTip(_make_tooltip(
                        f"{label} {names[col-2]}",
                        f"One of the three sweep values for {label} when THIS channel is swept. "
                        f"Select 'None' to exclude this value from the sweep."))
                s.currentIndexChanged.connect(self._update_combo_count)
                gl.addWidget(s, row, col)
                spins.append(s)
            self._param_spins[key] = spins
        root.addWidget(pg)

        # ── Sweep settings ────────────────────────────────────────────────────
        sg = QtWidgets.QGroupBox("Sweep Settings")
        sg.setStyleSheet("QGroupBox { font-weight: bold; }")
        fl = QtWidgets.QFormLayout(sg)

        self._spin_settle = QtWidgets.QSpinBox()
        self._spin_settle.setRange(100, 30000)
        self._spin_settle.setValue(500)
        self._spin_settle.setSuffix(" ms")
        self._spin_settle.setStyleSheet("background-color:#202020; color:#E0E0E0; font-size:24px;")
        self._spin_settle.setToolTip(_make_tooltip(
            "Settling time",
            "Time to wait after applying each combo before collecting samples. "
            "TIA worst-case settling (RF=1M, CF=155p): 5τ ≈ 775 µs. "
            "Over UDP, ambdac is sent 60 ms after the other params (lwIP buffer limit) "
            "and processed by Cmd_Task within 50 ms — allow ≥300 ms for clean settling "
            "(default: 500 ms).",
            src="AfeSweepWindow._spin_settle"))

        self._spin_samples = QtWidgets.QSpinBox()
        self._spin_samples.setRange(10, 10000)
        self._spin_samples.setValue(50)
        self._spin_samples.setStyleSheet("background-color:#202020; color:#E0E0E0; font-size:24px;")
        self._spin_samples.setToolTip(_make_tooltip(
            "Samples per combo",
            "Number of M1 frames to collect per combination for statistics. "
            "Frames arrive at 50 Hz (500 Hz / decimation ratio 10). "
            "50 samples = 1 s of data — sufficient for stable DC/AC statistics (default: 50).",
            src="AfeSweepWindow._spin_samples"))

        csv_row = QtWidgets.QHBoxLayout()
        self._edit_csv = QtWidgets.QLineEdit("afe_sweep_test.csv")
        self._edit_csv.setStyleSheet("background-color:#202020; color:#E0E0E0; font-size:24px;")
        self._edit_csv.setToolTip(_make_tooltip(
            "Output CSV",
            "Path to the output CSV file. If the file already exists the new rows are "
            "appended (header is written only once). Use Browse to pick a location."))
        btn_browse = QtWidgets.QPushButton("Browse…")
        btn_browse.setStyleSheet("background-color:#303030; color:#E0E0E0; font-size:24px;")
        btn_browse.clicked.connect(self._browse_csv)
        csv_row.addWidget(self._edit_csv)
        csv_row.addWidget(btn_browse)

        self._edit_label = QtWidgets.QLineEdit()
        self._edit_label.setPlaceholderText("e.g. probe disconnected, finger on sensor…")
        self._edit_label.setStyleSheet("background-color:#202020; color:#E0E0E0; font-size:24px;")
        self._edit_label.setToolTip(_make_tooltip(
            "Test label",
            "Free-text label written to the 'label' column of every CSV row produced "
            "by this sweep. Use it to describe the test condition "
            "(e.g. 'probe disconnected', 'finger 50% perfusion'). Can be empty."))

        self._combo_probe_state = QtWidgets.QComboBox()
        for val, name in self._PROBE_STATES:
            self._combo_probe_state.addItem(f"{name}  ({val})", userData=val)
        self._combo_probe_state.setStyleSheet(self._SS_COMBO)
        self._combo_probe_state.setToolTip(_make_tooltip(
            "Expected probe_state",
            "The probe state you expect the firmware to report during this sweep. "
            "Written as the first CSV column (probe_state_expected). "
            "The second CSV column (probe_state_check) is OK if every sample in the combo "
            "matches this value, NOT OK otherwise. "
            "Values: 0=PROBE_DISCONNECTED, 1=PROBE_NOT_APPLIED, 2=PROBE_APPLIED "
            "(enum ProbeState in incunest_afe4490.h)."))

        fl.addRow("Test label:", self._edit_label)
        fl.addRow("Expected probe_state:", self._combo_probe_state)
        fl.addRow("Settling time:", self._spin_settle)
        fl.addRow("Samples / combo:", self._spin_samples)
        fl.addRow("Output CSV:", csv_row)
        root.addWidget(sg)

        # ── Control / progress ────────────────────────────────────────────────
        cg = QtWidgets.QGroupBox("Control")
        cg.setStyleSheet("QGroupBox { font-weight: bold; }")
        cl = QtWidgets.QVBoxLayout(cg)

        self._lbl_probe_banner = QtWidgets.QLabel("")
        self._lbl_probe_banner.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_probe_banner.setStyleSheet(
            "background-color:#1A1A1A; color:#666666; font-size:28px; font-weight:bold; "
            "border:2px solid #333333; border-radius:4px; padding:4px;")
        self._lbl_probe_banner.setMinimumHeight(44)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m combos")
        self._progress.setStyleSheet(
            "QProgressBar { background:#202020; color:#E0E0E0; border:1px solid #555; border-radius:3px; }"
            "QProgressBar::chunk { background:#4CAF50; }")

        self._lbl_status = QtWidgets.QLabel("Idle — press START SWEEP to begin")
        self._lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_status.setStyleSheet("color:#AAAAAA;")

        self._btn_start = QtWidgets.QPushButton("START SWEEP")
        self._btn_start.setCheckable(True)
        self._btn_start.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_start.setToolTip(_make_tooltip(
            "START / STOP SWEEP",
            "Starts the parametric sweep. Applies each (LED_mA, RF, RG, AMBDAC) combination "
            "via $SET commands, waits for the settling time, then collects the configured "
            "number of M1 samples to compute statistics. Results are appended to the CSV file. "
            "Press again to abort."))
        self._btn_start.clicked.connect(self._toggle_sweep)

        cl.addWidget(self._lbl_probe_banner)
        cl.addWidget(self._progress)
        cl.addWidget(self._lbl_status)
        cl.addWidget(self._btn_start)
        root.addWidget(cg)

    # ── Probe banner ──────────────────────────────────────────────────────────
    def _update_probe_banner(self, final=False):
        n = self._probe_mismatch_count
        if n == 0:
            text = ("✓  SWEEP COMPLETE — PROBE STATE OK" if final
                    else f"✓  PROBE STATE OK  ({self._combo_idx} combos checked)")
            self._lbl_probe_banner.setText(text)
            self._lbl_probe_banner.setStyleSheet(
                "background-color:#0A2A0A; color:#66FF66; font-size:28px; font-weight:bold; "
                "border:2px solid #22AA22; border-radius:4px; padding:4px;")
        else:
            text = ("⚠  SWEEP COMPLETE — PROBE MISMATCH: " if final
                    else "⚠  PROBE MISMATCH — ")
            text += f"{n} combo{'s' if n != 1 else ''}"
            self._lbl_probe_banner.setText(text)
            self._lbl_probe_banner.setStyleSheet(
                "background-color:#2A0A0A; color:#FF6666; font-size:28px; font-weight:bold; "
                "border:2px solid #AA2222; border-radius:4px; padding:4px;")

    def _reset_probe_banner(self):
        self._lbl_probe_banner.setText("")
        self._lbl_probe_banner.setStyleSheet(
            "background-color:#1A1A1A; color:#666666; font-size:28px; font-weight:bold; "
            "border:2px solid #333333; border-radius:4px; padding:4px;")

    # ── CSV path picker ───────────────────────────────────────────────────────
    def _browse_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save CSV", self._edit_csv.text(),
            "CSV files (*.csv);;All files (*)",
            options=QtWidgets.QFileDialog.DontConfirmOverwrite)
        if path:
            self._edit_csv.setText(path)

    # ── Spin highlight helpers ─────────────────────────────────────────────────
    def _set_spin_style(self, spin, active: bool):
        use_combo = isinstance(spin, _ComboSpin)
        if active:
            spin.setStyleSheet(self._SS_COMBO_ACTIVE if use_combo else self._SS_SPIN_ACTIVE)
        else:
            spin.setStyleSheet(self._SS_COMBO if use_combo else self._SS_SPIN)

    def _clear_highlights(self):
        for spins in self._param_spins.values():
            for spin in spins:
                self._set_spin_style(spin, active=False)

    def _highlight_active(self, idx):
        """Highlight the spin that is currently applied to the hardware for combo idx."""
        self._clear_highlights()
        ch, led, rf, rg, amb = self._combos[idx]
        if ch == "LED1":
            var_keys = {"led1": led, "rf1": rf, "rg1": rg}
            fix_keys = ["led2", "rf2", "rg2"]
        else:
            var_keys = {"led2": led, "rf2": rf, "rg2": rg}
            fix_keys = ["led1", "rf1", "rg1"]
        # VAR spins of swept channel: highlight the one matching the current value
        for key, val in var_keys.items():
            for spin in self._param_spins[key][1:]:   # skip FIX (index 0)
                if spin.value() == val:
                    self._set_spin_style(spin, active=True)
                    break
        # FIX spin of the non-swept channel
        for key in fix_keys:
            self._set_spin_style(self._param_spins[key][0], active=True)
        # AMBDAC: no FIX — highlight the matching VAR spin
        for spin in self._param_spins["ambdac"]:
            if spin.value() == amb:
                self._set_spin_style(spin, active=True)
                break

    # ── Combo count display ───────────────────────────────────────────────────
    def _update_combo_count(self):
        if self._state != self._ST_IDLE:
            return
        n = len(self._build_combos())
        self._progress.setMaximum(max(n, 1))
        self._progress.setValue(0)
        self._progress.setFormat(f"%v / {n} combos")
        if n > 0:
            self._lbl_status.setText(
                f"Ready — {n} combo{'s' if n != 1 else ''} — press START SWEEP to begin")
        else:
            self._lbl_status.setText("No combos — all VAR spins set to None")

    # ── Sweep control ─────────────────────────────────────────────────────────
    def _toggle_sweep(self):
        if self._btn_start.isChecked():
            self._start_sweep()
        else:
            self._stop_sweep("Stopped by user")

    def _build_combos(self):
        import itertools
        combos = []
        # For led/rf/rg: spins[0]=FIX, spins[1:]=VAR. For ambdac: all spins are VAR (no FIX).
        amb_vals = sorted(set(s.value() for s in self._param_spins["ambdac"]
                               if s.value() >= 0))
        for ch, led_key, rf_key, rg_key in [
            ("LED1", "led1", "rf1", "rg1"),
            ("LED2", "led2", "rf2", "rg2"),
        ]:
            led_vals = sorted(set(s.value() for s in self._param_spins[led_key][1:]
                                   if s.value() >= 0))
            rf_vals  = sorted(set(s.value() for s in self._param_spins[rf_key][1:]
                                   if s.value() >= 0))
            rg_vals  = sorted(set(s.value() for s in self._param_spins[rg_key][1:]
                                   if s.value() >= 0))
            for amb, led, rf, rg in itertools.product(amb_vals, led_vals, rf_vals, rg_vals):
                combos.append((ch, led, rf, rg, amb))
        return combos

    def _start_sweep(self):
        mm = self.main_monitor
        serial_ok = mm is not None and mm._is_cmd_ready()
        if not serial_ok:
            self._lbl_status.setText("WARNING: no connection — $SET commands will not be sent")
        self._combos               = self._build_combos()
        self._combo_idx            = 0
        self._probe_mismatch_count = 0
        self._reset_probe_banner()
        total = len(self._combos)
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self._progress.setFormat(f"%v / {total} combos")
        self._btn_start.setText("STOP SWEEP")
        self._apply_combo(0)
        import time
        self._settle_end = time.monotonic() + self._spin_settle.value() / 1000.0
        self._buf = {sig: [] for sig in self._SIGNALS}
        self._buf["RSQI"]           = []
        self._buf["DIAG_CODE"]      = []
        self._buf["PROBE_STATE_FW"] = []
        self._buf["V_TIA_LED1"]     = []
        self._buf["V_TIA_LED2"]     = []
        self._buf["V_TIA_ALED1"]    = []
        self._buf["V_TIA_ALED2"]    = []
        self._buf["I_PD_LED1"]      = []
        self._buf["I_PD_LED2"]      = []
        self._buf["I_PD_ALED1"]     = []
        self._buf["I_PD_ALED2"]     = []
        self._state = self._ST_SETTLING
        self._lbl_status.setText(f"Settling combo 1/{total}…")
        self._timer.start()

    def _stop_sweep(self, reason="Done"):
        self._timer.stop()
        self._state = self._ST_IDLE
        self._btn_start.setChecked(False)
        self._btn_start.setText("START SWEEP")
        self._lbl_status.setText(reason)
        self._clear_highlights()
        if self._combo_idx > 0:
            self._update_probe_banner(final=True)

    def _apply_combo(self, idx):
        """Send $SET commands for combo at index idx and highlight the active spins.
        Swept channel uses VAR values; other channel uses its FIX spin (index 0).
        tiagain expects physical string (e.g. "100K"); stg2 expects "6dB"; ambdac expects int."""
        ch, led, rf, rg, amb = self._combos[idx]
        rf_str  = lambda i: self.TIA_GAINS[i]
        rg_str  = lambda i: self.STG2_GAINS[i]
        fix_rf  = lambda key: self._param_spins[key][0].value()
        fix_rg  = lambda key: self._param_spins[key][0].value()
        if ch == "LED1":
            self._send_set("led1",     str(led))
            self._send_set("tiagain1", rf_str(rf))
            self._send_set("stg21",    rg_str(rg))
            if self._param_spins["led2"][0].value() >= 0:
                self._send_set("led2", str(self._param_spins["led2"][0].value()))
            if self._param_spins["rf2"][0].value() >= 0:
                self._send_set("tiagain2", rf_str(fix_rf("rf2")))
            if self._param_spins["rg2"][0].value() >= 0:
                self._send_set("stg22",    rg_str(fix_rg("rg2")))
        else:
            self._send_set("led2",     str(led))
            self._send_set("tiagain2", rf_str(rf))
            self._send_set("stg22",    rg_str(rg))
            if self._param_spins["led1"][0].value() >= 0:
                self._send_set("led1", str(self._param_spins["led1"][0].value()))
            if self._param_spins["rf1"][0].value() >= 0:
                self._send_set("tiagain1", rf_str(fix_rf("rf1")))
            if self._param_spins["rg1"][0].value() >= 0:
                self._send_set("stg21",    rg_str(fix_rg("rg1")))
        # Over UDP, all 6 preceding $SET datagrams arrive in <10 ms — faster than the
        # lwIP UDP receive queue (default 6 slots) can be drained by Cmd_Task (50 ms cycle).
        # Packet 7 (ambdac) would be silently dropped.  Wait one Cmd_Task cycle so the
        # buffer is empty before sending ambdac.
        mm0 = self.main_monitor
        if mm0 is not None and mm0._active_transport == "udp":
            import time as _time; _time.sleep(0.060)
        self._send_set("ambdac", str(amb))
        # ── Trace to log_panel ────────────────────────────────────────────────
        mm = self.main_monitor
        if mm is not None:
            total = len(self._combos)
            if ch == "LED1":
                parts = [f"led1={led}mA", f"rf1={rf_str(rf)}", f"rg1={rg_str(rg)}"]
                if self._param_spins["led2"][0].value() >= 0:
                    parts.append(f"led2={self._param_spins['led2'][0].value()}mA")
                if self._param_spins["rf2"][0].value() >= 0:
                    parts.append(f"rf2={rf_str(fix_rf('rf2'))}")
                if self._param_spins["rg2"][0].value() >= 0:
                    parts.append(f"rg2={rg_str(fix_rg('rg2'))}")
            else:
                parts = [f"led2={led}mA", f"rf2={rf_str(rf)}", f"rg2={rg_str(rg)}"]
                if self._param_spins["led1"][0].value() >= 0:
                    parts.append(f"led1={self._param_spins['led1'][0].value()}mA")
                if self._param_spins["rf1"][0].value() >= 0:
                    parts.append(f"rf1={rf_str(fix_rf('rf1'))}")
                if self._param_spins["rg1"][0].value() >= 0:
                    parts.append(f"rg1={rg_str(fix_rg('rg1'))}")
            parts.append(f"ambdac={amb}µA")
            mm.log(f"[SWEEP] {idx+1}/{total}  ch={ch}  " + "  ".join(parts))
        self._highlight_active(idx)

    def _send_set(self, key: str, value: str):
        mm = self.main_monitor
        if mm is None or not mm._is_cmd_ready():
            return
        payload = f"$SET,{key},{value}"
        chk = 0
        for c in payload[1:]:
            chk ^= ord(c)
        mm.send_cmd(f"{payload}*{chk:02X}\r\n".encode())

    # ── State machine tick ────────────────────────────────────────────────────
    def _tick(self):
        import time
        now = time.monotonic()
        total = len(self._combos)

        if self._state == self._ST_SETTLING:
            if now >= self._settle_end:
                self._buf = {sig: [] for sig in self._SIGNALS}
                self._buf["RSQI"]           = []
                self._buf["DIAG_CODE"]      = []
                self._buf["PROBE_STATE_FW"] = []
                self._buf["V_TIA_LED1"]     = []
                self._buf["V_TIA_LED2"]     = []
                self._buf["V_TIA_ALED1"]    = []
                self._buf["V_TIA_ALED2"]    = []
                self._buf["I_PD_LED1"]      = []
                self._buf["I_PD_LED2"]      = []
                self._buf["I_PD_ALED1"]     = []
                self._buf["I_PD_ALED2"]     = []
                self._state = self._ST_MEASURING
                ch = self._combos[self._combo_idx][0]
                self._lbl_status.setText(
                    f"Measuring combo {self._combo_idx + 1}/{total} ({ch}) — "
                    f"0/{self._spin_samples.value()} smp")

        elif self._state == self._ST_MEASURING:
            n      = len(self._buf["LED1"])
            target = self._spin_samples.value()
            ch     = self._combos[self._combo_idx][0]
            self._lbl_status.setText(
                f"Measuring combo {self._combo_idx + 1}/{total} ({ch}) — "
                f"{n}/{target} smp")
            if n >= target:
                self._write_row()
                self._combo_idx += 1
                self._progress.setValue(self._combo_idx)
                if self._combo_idx >= total:
                    self._stop_sweep(f"Done — {total} combos written to {self._edit_csv.text()}")
                    return
                self._apply_combo(self._combo_idx)
                self._settle_end = now + self._spin_settle.value() / 1000.0
                self._buf = {sig: [] for sig in self._SIGNALS}
                self._buf["RSQI"]           = []
                self._buf["DIAG_CODE"]      = []
                self._buf["PROBE_STATE_FW"] = []
                self._buf["V_TIA_LED1"]     = []
                self._buf["V_TIA_LED2"]     = []
                self._buf["V_TIA_ALED1"]    = []
                self._buf["V_TIA_ALED2"]    = []
                self._buf["I_PD_LED1"]      = []
                self._buf["I_PD_LED2"]      = []
                self._buf["I_PD_ALED1"]     = []
                self._buf["I_PD_ALED2"]     = []
                self._state = self._ST_SETTLING
                self._lbl_status.setText(
                    f"Settling combo {self._combo_idx + 1}/{total}…")

    # ── Sample feed (called from PPGMonitor per M3/M4 frame) ──────────────────
    def feed_sample(self, red, ir, red_amb, ir_amb, led2_sub, led1_sub,
                    rsqi, diag_code, probe_state_fw,
                    v_tia_led1=None, v_tia_led2=None, v_tia_aled1=None, v_tia_aled2=None,
                    i_pd_led1=None, i_pd_led2=None, i_pd_aled1=None, i_pd_aled2=None):
        if self._state != self._ST_MEASURING:
            return
        self._buf["LED2"].append(red)
        self._buf["LED1"].append(ir)
        self._buf["ALED2"].append(red_amb)
        self._buf["ALED1"].append(ir_amb)
        self._buf["LED2_SUB"].append(led2_sub)
        self._buf["LED1_SUB"].append(led1_sub)
        self._buf["RSQI"].append(int(rsqi))
        self._buf["DIAG_CODE"].append(int(diag_code))
        self._buf["PROBE_STATE_FW"].append(int(probe_state_fw))
        if v_tia_led1 is not None:
            self._buf["V_TIA_LED1"].append(float(v_tia_led1))
            self._buf["V_TIA_LED2"].append(float(v_tia_led2))
            self._buf["V_TIA_ALED1"].append(float(v_tia_aled1))
            self._buf["V_TIA_ALED2"].append(float(v_tia_aled2))
            self._buf["I_PD_LED1"].append(float(i_pd_led1))
            self._buf["I_PD_LED2"].append(float(i_pd_led2))
            self._buf["I_PD_ALED1"].append(float(i_pd_aled1))
            self._buf["I_PD_ALED2"].append(float(i_pd_aled2))

    # ── CSV row writer ────────────────────────────────────────────────────────
    def _write_row(self):
        import csv, datetime, math, os
        ch, led, rf, rg, amb = self._combos[self._combo_idx]

        def _fix_text(spin):
            """Return spin's display text; returns 'None' when value() < 0."""
            return "None" if spin.value() < 0 else spin.currentText()

        if ch == "LED1":
            led1, rf1, rg1 = led, rf, rg
            led2    = _fix_text(self._param_spins["led2"][0])
            rf2_str = _fix_text(self._param_spins["rf2"][0])
            rg2_str = _fix_text(self._param_spins["rg2"][0])
            rf1_str = self.TIA_GAINS[rf1]  if 0 <= rf1 < len(self.TIA_GAINS)  else str(rf1)
            rg1_str = self.STG2_GAINS[rg1] if 0 <= rg1 < len(self.STG2_GAINS) else str(rg1)
        else:
            led2, rf2, rg2 = led, rf, rg
            led1    = _fix_text(self._param_spins["led1"][0])
            rf1_str = _fix_text(self._param_spins["rf1"][0])
            rg1_str = _fix_text(self._param_spins["rg1"][0])
            rf2_str = self.TIA_GAINS[rf2]  if 0 <= rf2 < len(self.TIA_GAINS)  else str(rf2)
            rg2_str = self.STG2_GAINS[rg2] if 0 <= rg2 < len(self.STG2_GAINS) else str(rg2)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        label = self._edit_label.text().strip()

        # ── probe_state check (first 3 columns) ───────────────────────────────
        expected_ps = self._combo_probe_state.currentData()
        ps_fw_vals  = self._buf["PROBE_STATE_FW"]
        ps_ok = all(v == expected_ps for v in ps_fw_vals) if ps_fw_vals else True
        ps_check_str = "OK" if ps_ok else "NOT OK"
        if not ps_ok:
            self._probe_mismatch_count += 1
        _ps_names = {code: name for code, name in self._PROBE_STATES}
        if ps_fw_vals:
            ps_calc_mode = max(set(ps_fw_vals), key=ps_fw_vals.count)
            ps_calc_str  = _ps_names.get(ps_calc_mode, str(ps_calc_mode))
        else:
            ps_calc_str = ""

        row = [expected_ps, ps_calc_str, ps_check_str,
               label, now_str, led1, led2, rf1_str, rf2_str, rg1_str, rg2_str, amb, len(self._buf["LED1"])]
        # Pre-compute stats for each signal
        stats = {}
        for sig in self._SIGNALS:
            vals = self._buf[sig]
            if vals:
                n    = len(vals)
                mn   = min(vals)
                mx   = max(vals)
                mean = sum(vals) / n
                stats[sig] = (f"{mean:.2f}", f"{mn:.0f}", f"{mx:.0f}", f"{mx-mn:.0f}",
                              f"{math.sqrt(sum((v-mean)**2 for v in vals)/n):.2f}")
            else:
                stats[sig] = ("0.00", "0", "0", "0", "0.00")
        # Emit grouped by stat type: all means, all mins, all maxs, all pp, all stds
        for stat_idx in range(5):
            for sig in self._SIGNALS:
                row.append(stats[sig][stat_idx])
        # OT1 / OT2: LED_Sub_mean / (LED_mA × RF_Ω × RG_linear)
        # Physical values sourced from firmware $CFG frame via parent monitor's _last_cfg
        _mon = self.parent()
        _cfg = _mon._last_cfg if _mon is not None and hasattr(_mon, "_last_cfg") else {}
        try:
            _led1_ma = float(led1)
            _rf1 = float(_cfg.get("rf1_ohm", 0)) or None
            _rg1 = (float(_cfg.get("rg1_x", 1.0)) if _cfg.get("stage2en1", "0") == "1" else 1.0) if _rf1 else None
            ot1 = f"{float(stats['LED1_SUB'][0]) / (_led1_ma * _rf1 * _rg1):.4f}" \
                  if (_rf1 and _rg1 and _led1_ma) else ""
        except Exception:
            ot1 = ""
        try:
            _led2_ma = float(led2)
            _rf2 = float(_cfg.get("rf2_ohm", 0)) or None
            _rg2 = (float(_cfg.get("rg2_x", 1.0)) if _cfg.get("stage2en2", "0") == "1" else 1.0) if _rf2 else None
            ot2 = f"{float(stats['LED2_SUB'][0]) / (_led2_ma * _rf2 * _rg2):.4f}" \
                  if (_rf2 and _rg2 and _led2_ma) else ""
        except Exception:
            ot2 = ""
        row.extend([ot1, ot2])

        # ── RSQM columns ──────────────────────────────────────────────────────
        rsqi_vals = self._buf["RSQI"]
        if rsqi_vals:
            rsqi_ok_pct = f"{100.0 * sum(rsqi_vals) / len(rsqi_vals):.1f}"
        else:
            rsqi_ok_pct = ""
        dc_vals = self._buf["DIAG_CODE"]
        if dc_vals:
            dc_mean = f"{sum(dc_vals) / len(dc_vals):.2f}"
            dc_min  = str(min(dc_vals))
            dc_max  = str(max(dc_vals))
        else:
            dc_mean = dc_min = dc_max = ""
        if ps_fw_vals:
            ps_mean = f"{sum(ps_fw_vals) / len(ps_fw_vals):.2f}"
            ps_min  = str(min(ps_fw_vals))
            ps_max  = str(max(ps_fw_vals))
        else:
            ps_mean = ps_min = ps_max = ""
        row.extend([rsqi_ok_pct, dc_mean, dc_min, dc_max, ps_mean, ps_min, ps_max])

        # ── V_TIA [V] and I_PD [µA] — received from $M4 frame ────────────────
        def _fstats(vals, fmt):
            if not vals:
                return ("",) * 4
            n = len(vals)
            m = sum(vals) / n
            sd = math.sqrt(sum((v - m) ** 2 for v in vals) / n)
            return fmt.format(m), fmt.format(sd), fmt.format(min(vals)), fmt.format(max(vals))
        for _key in ("V_TIA_LED1", "V_TIA_LED2", "V_TIA_ALED1", "V_TIA_ALED2"):
            row.extend(_fstats(self._buf[_key], "{:.6f}"))
        for _key in ("I_PD_LED1", "I_PD_LED2", "I_PD_ALED1", "I_PD_ALED2"):
            row.extend(_fstats([v * 1e6 for v in self._buf[_key]], "{:.3f}"))
        # ── I_PD differential LED−ALED [µA] ──────────────────────────────────
        for _led_key, _amb_key in [("I_PD_LED1", "I_PD_ALED1"), ("I_PD_LED2", "I_PD_ALED2")]:
            _a, _b = self._buf[_led_key], self._buf[_amb_key]
            if _a and _b and len(_a) == len(_b):
                row.extend(_fstats([(x - y) * 1e6 for x, y in zip(_a, _b)], "{:.3f}"))
            else:
                row.extend([""] * 4)

        path = self._edit_csv.text().strip() or "afe_sweep_test.csv"
        write_header = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(self._CSV_HEADER)
            w.writerow(row)
        self._update_probe_banner()

    # ── Settings persistence ──────────────────────────────────────────────────
    def _restore_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        v = s.value("AFESweepTestWindow/settle_ms", 200, type=int)
        self._spin_settle.setValue(v)
        v = s.value("AFESweepTestWindow/n_samples", 50, type=int)
        self._spin_samples.setValue(v)
        v = s.value("AFESweepTestWindow/csv_path", "afe_sweep_test.csv", type=str)
        self._edit_csv.setText(v)
        v = s.value("AFESweepTestWindow/label", "", type=str)
        self._edit_label.setText(v)
        v = s.value("AFESweepTestWindow/probe_state", 2, type=int)  # default: PROBE_APPLIED
        for i in range(self._combo_probe_state.count()):
            if self._combo_probe_state.itemData(i) == v:
                self._combo_probe_state.setCurrentIndex(i)
                break
        for key, spins in self._param_spins.items():
            for i, spin in enumerate(spins):
                v = s.value(f"AFESweepTestWindow/{key}_{i}", spin.value(), type=int)
                spin.setValue(v)
        self._update_combo_count()

    def closeEvent(self, event):
        if self._state != self._ST_IDLE:
            self._stop_sweep("Window closed")
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("AFESweepTestWindow/geometry",     self.saveGeometry())
        s.setValue("AFESweepTestWindow/settle_ms",   self._spin_settle.value())
        s.setValue("AFESweepTestWindow/n_samples",   self._spin_samples.value())
        s.setValue("AFESweepTestWindow/csv_path",    self._edit_csv.text())
        s.setValue("AFESweepTestWindow/label",       self._edit_label.text())
        s.setValue("AFESweepTestWindow/probe_state", self._combo_probe_state.currentData())
        for key, spins in self._param_spins.items():
            for i, spin in enumerate(spins):
                s.setValue(f"AFESweepTestWindow/{key}_{i}", spin.value())
        if self.main_monitor is not None:
            self.main_monitor.btn_afe_sweep.setChecked(False)
            self.main_monitor.afe_sweep_window = None
        super().closeEvent(event)


class UdpComWindow(QtWidgets.QWidget):
    """Floating window with the raw UDP WiFi stream console."""

    UDP_HEADER = (
        f"{'Timestamp_PC':<15},{'Df_us':>5},"
        "FrameMode,SmpCnt,Ts_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState,V_TIA_LED1,V_TIA_LED2,V_TIA_ALED1,V_TIA_ALED2,I_PD_LED1,I_PD_LED2,I_PD_ALED1,I_PD_ALED2"
    )

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self._paused = False
        self.setWindowTitle("UDP COM")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self._setup_ui()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("UdpComWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1200, 400)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        top_bar = QtWidgets.QHBoxLayout()
        self.header_label = QtWidgets.QLabel(self.UDP_HEADER)
        self.header_label.setFont(QtGui.QFont("Consolas", 9))
        self.header_label.setWordWrap(False)
        self.header_label.setMinimumWidth(0)
        self.header_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.header_label.setStyleSheet("""
            QLabel {
                background-color: #001020; color: #44AAFF;
                padding: 5px 8px; border: 1px solid #44AAFF;
            }
        """)
        top_bar.addWidget(self.header_label, stretch=1)

        self.btn_pause = QtWidgets.QPushButton("PAUSE")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setFixedWidth(110)
        self.btn_pause.setStyleSheet(
            "QPushButton { background-color: #505050; color: #FFFFFF; font-weight: bold; "
            "border: 1px solid #888888; border-radius: 3px; padding: 4px; }"
            "QPushButton:checked { background-color: #CC6600; color: #FFFFFF; "
            "border: 1px solid #FF8800; }")
        self.btn_pause.setToolTip(_make_tooltip("PAUSE", "Freeze the console display. "
            "The queue keeps draining and algorithms keep running; only new lines stop appearing."))
        self.btn_pause.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self.btn_pause)
        layout.addLayout(top_bar)

        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console.setFont(QtGui.QFont("Consolas", 9))
        self.console.setStyleSheet("""
            background-color: #000000; color: #2090D0;
            border: 1px solid #44AAFF; padding: 5px;
        """)
        layout.addWidget(self.console)

    def _toggle_pause(self):
        self._paused = self.btn_pause.isChecked()
        self.btn_pause.setText("RESUME" if self._paused else "PAUSE")

    def append_line(self, line):
        """Append a single line immediately (for status/error messages)."""
        if self._paused:
            return
        self.console.appendPlainText(line)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def append_lines(self, lines):
        """Batch append a list of lines (called from _process_frames_tick loop)."""
        if self._paused or not lines:
            return
        self.console.appendPlainText('\n'.join(lines))
        if self.console.blockCount() > 500:
            cursor = self.console.textCursor()
            cursor.movePosition(QtGui.QTextCursor.Start)
            cursor.select(QtGui.QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
        self.console.horizontalScrollBar().setValue(0)

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("UdpComWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_udpcom.setChecked(False)
            self.main_monitor.udpcom_window = None
        super().closeEvent(event)


class _FullClickCheckBox(QtWidgets.QCheckBox):
    """QCheckBox that responds to clicks anywhere in its bounding rect."""
    def hitButton(self, pos):
        return self.rect().contains(pos)


class LabCaptureWindow(QtWidgets.QMainWindow):
    """Controlled lab capture window.

    Opens via the CAPTURE LAB sidebar button.  Lets the user configure
    metadata, column selection, output path and capture length before
    triggering a 500 Hz CSV capture.  The window stays open after each
    capture so consecutive sessions can be started without reconfiguring.

    CSV format (compatible with incunest_offline_runner):
      - Pre-capture notes as '# ...' lines before the column header.
      - Mandatory columns: LED2, LED1, ALED2, ALED1, LED2_SUB, LED1_SUB.
      - Optional FW columns: FW_SpO2, FW_HR1, FW_HR2, FW_HR3 (offline_runner names).
      - Post-capture notes as '# ...' lines after the last data row.
    """

    # (display label, csv column name, M1-parts index after '$', mandatory)
    # M1 parts layout (after stripping '$' and checksum):
    #   [0]=FrameMode  [1]=SmpCnt  [2]=Ts_us
    #   [3]=LED2  [4]=LED1  [5]=ALED2  [6]=ALED1  [7]=LED2_SUB  [8]=LED1_SUB
    #   [9]=PPG  [10]=SpO2  [11]=SpO2_SQI  [12]=R  [13]=PI
    #   [14]=HR1  [15]=HR1_SQI  [16]=HR2  [17]=HR2_SQI  [18]=HR3  [19]=HR3_SQI
    #   [20]=RSQI  [21]=DiagCode  [22]=ProbeState   (v0.27+)
    _COLS = [
        ("SmpCnt",   "FW_SmpCnt",  1,  False),
        ("Ts_us",    "FW_Ts_us",   2,  False),
        ("LED2 (RED)", "LED2",      3,  True),
        ("LED1 (IR)", "LED1",      4,  True),
        ("ALED2",  "ALED2",    5,  True),
        ("ALED1",   "ALED1",     6,  True),
        ("LED2_SUB",  "LED2_SUB",    7,  True),
        ("LED1_SUB",   "LED1_SUB",     8,  True),
        ("PPG",      "FW_PPG",      9,  False),
        ("SpO2",     "FW_SpO2",    10,  False),
        ("SpO2_SQI", "FW_SpO2_SQI", 11,  False),
        ("R",   "FW_R",  12,  False),
        ("PI",       "FW_PI",      13,  False),
        ("HR1",      "FW_HR1",     14,  False),
        ("HR1_SQI",  "FW_HR1_SQI", 15,  False),
        ("HR2",      "FW_HR2",     16,  False),
        ("HR2_SQI",  "FW_HR2_SQI", 17,  False),
        ("HR3",      "FW_HR3",     18,  False),
        ("HR3_SQI",  "FW_HR3_SQI", 19,  False),
        ("RSQI",      "FW_RSQI",      20,  False),
        ("DiagCode",  "FW_DiagCode",  21,  False),
        ("ProbeState","FW_ProbeState",22,  False),
    ]

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("Lab Capture")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0; font-size: 28px;")
        self._setup_ui()
        self._load_settings()
        self.main_monitor._cfg_listener = self._on_cfg_received

    # ── UI ───────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        _GRP = ("QGroupBox { color: #FFAA44; font-weight: bold; font-size: 28px; "
                "border: 1px solid #555; margin-top: 8px; } "
                "QGroupBox::title { subcontrol-origin: margin; left: 8px; }")

        # ── Output ─────────────────────────────────────────────────────────
        grp_out = QtWidgets.QGroupBox("Output")
        grp_out.setStyleSheet(_GRP)
        form_out = QtWidgets.QFormLayout(grp_out)
        form_out.setSpacing(6)

        dir_row = QtWidgets.QHBoxLayout()
        self._edit_dir = QtWidgets.QLineEdit()
        self._edit_dir.setStyleSheet("QLineEdit { background:#2A2A2A; color:#FFDD44; font-size:28px; }")
        self._edit_dir.setToolTip(_make_tooltip(
            "Output directory", "Folder where capture CSV files are saved."))
        dir_row.addWidget(self._edit_dir)
        btn_browse = QtWidgets.QPushButton("Browse…")
        btn_browse.setStyleSheet("font-size:28px; padding:4px 10px;")
        btn_browse.clicked.connect(self._browse_dir)
        btn_browse.setToolTip(_make_tooltip(
            "Browse", "Choose the output directory for captured CSV files."))
        dir_row.addWidget(btn_browse)
        _lbl_dir = QtWidgets.QLabel("Directory:")
        _lbl_dir.setStyleSheet("QLabel { color:#CCCCCC; font-size:28px; }")
        form_out.addRow(_lbl_dir, dir_row)

        self._edit_prefix = QtWidgets.QLineEdit()
        self._edit_prefix.setPlaceholderText("lab_capture")
        self._edit_prefix.setStyleSheet("QLineEdit { background:#2A2A2A; color:#FFDD44; font-size:28px; }")
        self._edit_prefix.setToolTip(_make_tooltip(
            "Filename prefix",
            "The captured file is named <prefix>_<YYYYMMDD_HHMMSS>.csv"))
        _lbl_pfx = QtWidgets.QLabel("Filename prefix:")
        _lbl_pfx.setStyleSheet("QLabel { color:#CCCCCC; font-size:28px; }")
        form_out.addRow(_lbl_pfx, self._edit_prefix)
        outer.addWidget(grp_out)

        # ── Capture controls ───────────────────────────────────────────────
        grp_cap = QtWidgets.QGroupBox("Capture")
        grp_cap.setStyleSheet(_GRP)
        vbox_cap = QtWidgets.QVBoxLayout(grp_cap)
        vbox_cap.setSpacing(6)

        # Row 1: timed capture
        row_timed = QtWidgets.QHBoxLayout()
        self._btn_capture_timed = QtWidgets.QPushButton("▶  CAPTURE")
        self._btn_capture_timed.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_capture_timed.clicked.connect(self._on_capture_timed)
        self._btn_capture_timed.setToolTip(_make_tooltip(
            "CAPTURE (timed)",
            "Start a capture that stops automatically after the specified number of samples."))
        row_timed.addWidget(self._btn_capture_timed)
        self._spin_samples = QtWidgets.QSpinBox()
        self._spin_samples.setRange(1, 1_000_000)
        self._spin_samples.setValue(5000)
        self._spin_samples.setSingleStep(500)
        self._spin_samples.setStyleSheet(
            "QSpinBox { background:#2A2A2A; color:#FFDD44; font-size:28px; padding:4px; }")
        self._spin_samples.setToolTip(_make_tooltip(
            "Sample count",
            "Number of 500 Hz samples to record in a timed capture. "
            "5000 samples = 10 seconds at 500 Hz.",
            src="LabCaptureWindow._spin_samples"))
        row_timed.addWidget(self._spin_samples)
        lbl_smp = QtWidgets.QLabel("samples")
        lbl_smp.setStyleSheet("QLabel { font-size:28px; color:#AAAAAA; }")
        row_timed.addWidget(lbl_smp)
        vbox_cap.addLayout(row_timed)

        # Row 2: continuous capture
        row_cont = QtWidgets.QHBoxLayout()
        self._btn_capture_cont = QtWidgets.QPushButton("▶  START CONTINUOUS")
        self._btn_capture_cont.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_capture_cont.clicked.connect(self._on_capture_cont)
        self._btn_capture_cont.setToolTip(_make_tooltip(
            "START CONTINUOUS",
            "Start a capture that runs until STOP is pressed."))
        row_cont.addWidget(self._btn_capture_cont)
        self._btn_stop = QtWidgets.QPushButton("■  STOP")
        self._btn_stop.setStyleSheet(ACTION_BUTTON_STYLE)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setToolTip(_make_tooltip(
            "STOP",
            "Stop the ongoing capture and flush post-capture notes to the file."))
        row_cont.addWidget(self._btn_stop)
        vbox_cap.addLayout(row_cont)

        # Progress + status
        self._progress = QtWidgets.QProgressBar()
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(
            "QProgressBar { background:#2A2A2A; border:1px solid #555; color:#FFF; "
            "font-size:28px; text-align:center; } "
            "QProgressBar::chunk { background:#33AA55; }")
        vbox_cap.addWidget(self._progress)

        self._lbl_status = QtWidgets.QLabel("IDLE")
        self._lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_status.setStyleSheet(
            "QLabel { font-size:28px; color:#AAAAAA; font-weight:bold; }")
        vbox_cap.addWidget(self._lbl_status)
        outer.addWidget(grp_cap)

        # ── Pre-capture notes ──────────────────────────────────────────────
        grp_pre = QtWidgets.QGroupBox("Pre-capture notes")
        grp_pre.setStyleSheet(_GRP)
        vbox_pre = QtWidgets.QVBoxLayout(grp_pre)

        btn_row_pre = QtWidgets.QHBoxLayout()
        self._btn_read_cfg = QtWidgets.QPushButton("Read chip config")
        self._btn_read_cfg.setStyleSheet("font-size:26px; padding:4px 14px; background-color:#2A3D5A; color:#AACCFF;")
        self._btn_read_cfg.setToolTip(_make_tooltip(
            "Read chip config",
            "Sends $CFG? to the ESP32 and inserts the current AFE4490 configuration "
            "into the pre-capture notes field."))
        self._btn_read_cfg.clicked.connect(self._on_read_cfg)
        btn_row_pre.addWidget(self._btn_read_cfg)
        btn_row_pre.addStretch()
        vbox_pre.addLayout(btn_row_pre)

        self._pre_notes = QtWidgets.QPlainTextEdit()
        self._pre_notes.setPlaceholderText(
            "Subject ID, session conditions, operator name, …\n"
            "Each line will be written as a # comment before the CSV header.")
        self._pre_notes.setMinimumHeight(250)
        self._pre_notes.setStyleSheet(
            "QPlainTextEdit { background:#1A1A1A; color:#CCCCCC; font-family:Consolas; font-size:28px; }")
        self._pre_notes.setToolTip(_make_tooltip(
            "Pre-capture notes",
            "Free-form text written as # comment lines at the top of the CSV file, "
            "before the column header. Use it for subject ID, session conditions, "
            "operator name, etc."))
        vbox_pre.addWidget(self._pre_notes)
        outer.addWidget(grp_pre, stretch=1)

        # ── Columns ────────────────────────────────────────────────────────
        grp_cols = QtWidgets.QGroupBox("Columns")
        grp_cols.setStyleSheet(_GRP)
        grid_cols = QtWidgets.QGridLayout(grp_cols)
        grid_cols.setSpacing(4)
        self._checks = {}
        for i, (label, csv_name, _, mandatory) in enumerate(self._COLS):
            cb = _FullClickCheckBox(label)
            cb.setMinimumWidth(185)
            cb.setChecked(True)
            cb.setStyleSheet(
                "QCheckBox { font-size:28px; color:#777777; background:#0E2A0E; "
                "border:1px solid #2A5A2A; border-radius:3px; padding:2px 10px; }"
                "QCheckBox::indicator { width:20px; height:20px; border:2px solid #3A7A3A; "
                "background:#0E2A0E; border-radius:2px; }"
                "QCheckBox::indicator:checked { background:#1A5A1A; border-color:#88EE55; "
                "image: url(check_white.svg); }"
                "QCheckBox:checked { color:#FFFFFF; background:#2A6A2A; border-color:#77CC44; }")
            if mandatory:
                cb.setEnabled(False)
                cb.setToolTip(_make_tooltip(
                    label,
                    f"Always included — required by the offline runner (column: {csv_name})."))
            else:
                cb.setToolTip(_make_tooltip(label, f"Optional column: {csv_name}."))
                cb.stateChanged.connect(self._save_settings)
            self._checks[label] = cb
            grid_cols.addWidget(cb, i // 8, i % 8)
        outer.addWidget(grp_cols)

        # ── Post-capture notes ─────────────────────────────────────────────
        grp_post = QtWidgets.QGroupBox("Post-capture notes")
        grp_post.setStyleSheet(_GRP)
        vbox_post = QtWidgets.QVBoxLayout(grp_post)
        self._post_notes = QtWidgets.QPlainTextEdit()
        self._post_notes.setPlaceholderText(
            "Observations after the capture: signal quality, artefacts, …\n"
            "Written as # comment lines at the end of the CSV file.")
        self._post_notes.setMinimumHeight(250)
        self._post_notes.setStyleSheet(
            "QPlainTextEdit { background:#1A1A1A; color:#CCCCCC; font-family:Consolas; font-size:28px; }")
        self._post_notes.setToolTip(_make_tooltip(
            "Post-capture notes",
            "Free-form text written as # comment lines at the bottom of the CSV file, "
            "after the last data row. Use it for signal quality observations, artefacts, etc."))
        vbox_post.addWidget(self._post_notes)
        outer.addWidget(grp_post, stretch=1)

    # ── Settings ─────────────────────────────────────────────────────────────
    def _load_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        self.setMinimumSize(1510, 1300)
        geom = s.value("LabCaptureWindow/geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1510, 1370)
        self._pre_notes.setPlainText(
            s.value("LabCaptureWindow/pre_notes",  "", type=str))
        self._post_notes.setPlainText(
            s.value("LabCaptureWindow/post_notes", "", type=str))
        self._edit_dir.setText(
            s.value("LabCaptureWindow/output_dir", CAPTURES_DIR, type=str))
        self._edit_prefix.setText(
            s.value("LabCaptureWindow/filename_prefix", "lab_capture", type=str))
        self._spin_samples.setValue(
            s.value("LabCaptureWindow/spin_samples", 5000, type=int))
        for label, _, _, mandatory in self._COLS:
            if not mandatory:
                key = f"LabCaptureWindow/check_{label.replace(' ', '_')}"
                self._checks[label].setChecked(s.value(key, True, type=bool))

    def _save_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("LabCaptureWindow/geometry",        self.saveGeometry())
        s.setValue("LabCaptureWindow/pre_notes",       self._pre_notes.toPlainText())
        s.setValue("LabCaptureWindow/post_notes",      self._post_notes.toPlainText())
        s.setValue("LabCaptureWindow/output_dir",      self._edit_dir.text())
        s.setValue("LabCaptureWindow/filename_prefix", self._edit_prefix.text())
        s.setValue("LabCaptureWindow/spin_samples",    self._spin_samples.value())
        for label, _, _, mandatory in self._COLS:
            if not mandatory:
                key = f"LabCaptureWindow/check_{label.replace(' ', '_')}"
                s.setValue(key, self._checks[label].isChecked())

    # ── Chip config readback ──────────────────────────────────────────────────
    def _on_read_cfg(self):
        if not self.main_monitor.request_chip_config():
            self._lbl_status.setText("Not connected — cannot read chip config")

    def _on_cfg_received(self, text):
        existing = self._pre_notes.toPlainText().strip()
        self._pre_notes.setPlainText((existing + "\n\n" + text if existing else text).strip())

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select output directory", self._edit_dir.text())
        if d:
            self._edit_dir.setText(d)

    def _active_col_spec(self):
        """Return list of (csv_name, m1_idx) for checked columns."""
        return [(csv_name, idx)
                for label, csv_name, idx, _ in self._COLS
                if self._checks[label].isChecked()]

    def _make_filepath(self):
        prefix = self._edit_prefix.text().strip() or "lab_capture"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self._edit_dir.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            out_dir = CAPTURES_DIR
        return os.path.join(out_dir, f"{prefix}_{ts}.csv")

    def _set_capturing(self, is_capturing: bool):
        self._btn_capture_timed.setEnabled(not is_capturing)
        self._btn_capture_cont.setEnabled(not is_capturing)
        self._btn_stop.setEnabled(is_capturing)
        for label, _, _, mandatory in self._COLS:
            if not mandatory:
                self._checks[label].setEnabled(not is_capturing)
        self._edit_dir.setEnabled(not is_capturing)
        self._edit_prefix.setEnabled(not is_capturing)
        self._spin_samples.setEnabled(not is_capturing)

    # ── Capture triggers ──────────────────────────────────────────────────────
    def _on_capture_timed(self):
        if self.main_monitor is None:
            return
        self.main_monitor.start_lab_capture(
            target=self._spin_samples.value(),
            col_spec=self._active_col_spec(),
            filepath=self._make_filepath(),
            pre_notes=self._pre_notes.toPlainText(),
        )

    def _on_capture_cont(self):
        if self.main_monitor is None:
            return
        self.main_monitor.start_lab_capture(
            target=0,
            col_spec=self._active_col_spec(),
            filepath=self._make_filepath(),
            pre_notes=self._pre_notes.toPlainText(),
        )

    def _on_stop(self):
        if self.main_monitor is not None:
            self.main_monitor.stop_lab_capture(
                post_notes=self._post_notes.toPlainText())

    # ── Callbacks from PPGMonitor ─────────────────────────────────────────────
    def on_capture_started(self, filepath: str, target: int):
        self._set_capturing(True)
        self._progress.setMaximum(target if target > 0 else 0)
        self._progress.setValue(0)
        self._progress.setFormat("0" if target == 0 else f"0 / {target}")
        name = os.path.basename(filepath)
        self._lbl_status.setText(f"CAPTURING → {name}")
        self._lbl_status.setStyleSheet(
            "QLabel { font-size:28px; color:#FFDD44; font-weight:bold; }")

    def on_capture_progress(self, count: int, target: int):
        if target > 0:
            self._progress.setValue(count)
            self._progress.setFormat(f"{count} / {target}")
        else:
            self._progress.setMaximum(0)
            self._progress.setFormat(f"{count}")

    def on_capture_done(self, count: int, filepath: str):
        self._set_capturing(False)
        self._progress.setMaximum(100)
        self._progress.setValue(100)
        self._progress.setFormat(f"{count} samples")
        name = os.path.basename(filepath)
        self._lbl_status.setText(f"DONE  {count} samples → {name}")
        self._lbl_status.setStyleSheet(
            "QLabel { font-size:28px; color:#00FF88; font-weight:bold; }")

    # ── Close ─────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self.main_monitor is not None and self.main_monitor.is_lab_capturing:
            self.main_monitor.stop_lab_capture(
                post_notes=self._post_notes.toPlainText())
        self._save_settings()
        if self.main_monitor is not None:
            self.main_monitor.btn_lab_capture.setChecked(False)
            self.main_monitor.lab_capture_window = None
        super().closeEvent(event)


class _StatsHighlightDelegate(QtWidgets.QStyledItemDelegate):
    """Draws a gold border around highlighted cells; forces header font on the sub-header row."""
    _BORDER_COLOR = QtGui.QColor("#FFD700")
    _BORDER_WIDTH = 3

    def __init__(self, highlighted: set, tbl, subhdr_row: int, parent=None):
        super().__init__(parent)
        self._highlighted = highlighted
        self._tbl = tbl
        self._subhdr_row = subhdr_row

    def paint(self, painter, option, index):
        if index.row() == self._subhdr_row:
            # Paint sub-header manually. The stylesheet (font-size: 28px) is bypassed
            # by painting directly. Use the QHeaderView widget's effective font + bold
            # to match the horizontal header visual size exactly.
            painter.save()
            bg = index.data(QtCore.Qt.BackgroundRole)
            painter.fillRect(option.rect, bg if bg else QtGui.QColor("#1E1E2E"))
            font = QtGui.QFont()
            font.setPixelSize(22)
            font.setBold(True)
            painter.setFont(font)
            fg = index.data(QtCore.Qt.ForegroundRole)
            painter.setPen(fg.color() if fg else QtGui.QColor("#AAAAAA"))
            text = index.data(QtCore.Qt.DisplayRole) or ""
            align = index.data(QtCore.Qt.TextAlignmentRole)
            painter.drawText(option.rect, int(align) if align else QtCore.Qt.AlignCenter, text)
            painter.restore()
        else:
            super().paint(painter, option, index)
            if (index.row(), index.column()) in self._highlighted:
                painter.save()
                pen = QtGui.QPen(self._BORDER_COLOR, self._BORDER_WIDTH)
                painter.setPen(pen)
                r = option.rect.adjusted(2, 2, -2, -2)
                painter.drawRect(r)
                painter.restore()


class PPGMonitor(QtWidgets.QMainWindow):
    _sig_log           = QtCore.pyqtSignal(str)           # thread-safe log
    _sig_serial_result = QtCore.pyqtSignal(bool, str, str, object)  # (success, port, error_msg, ser_obj)
    _sig_udp_active    = QtCore.pyqtSignal()              # emitted by _udp_reader on first datagram

    def log(self, text):
        """Appends a timestamped line to the log panel, colour inferred from text content."""
        _ERROR_KEYWORDS   = ("error", "failed", "cannot", "not connected", "no port")
        _SUCCESS_KEYWORDS = ("online", "saved")
        _WARNING_KEYWORDS = ("recording", "paused")
        tl = text.lower()
        if any(k in tl for k in _ERROR_KEYWORDS):
            level = "error"
        elif any(k in tl for k in _SUCCESS_KEYWORDS):
            level = "success"
        elif any(k in tl for k in _WARNING_KEYWORDS):
            level = "warning"
        else:
            level = "info"
        colors = {"success": "#00FF88", "warning": "#FFDD44", "error": "#FF4444", "info": "#44AAFF"}
        icons  = {"success": "✔",       "warning": "⚠",       "error": "✖",      "info": "●"}
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_panel.append(
            f'<span style="color:#888888;">[{ts}]</span> '
            f'<span style="color:{colors[level]};font-weight:normal;">{icons[level]} {text}</span>'
        )
        self.log_panel.verticalScrollBar().setValue(
            self.log_panel.verticalScrollBar().maximum()
        )

    def __init__(self, save_chk=False, save_chk_duration=15):
        super().__init__()
        self._sig_log.connect(self.log, QtCore.Qt.QueuedConnection)  # thread-safe: always queued to main thread even from non-QThread
        self._sig_serial_result.connect(self._on_serial_result, QtCore.Qt.QueuedConnection)
        self._sig_udp_active.connect(self._on_udp_active, QtCore.Qt.QueuedConnection)
        self._serial_connecting = False   # guard: prevent concurrent open attempts

        # Configuración Ventana Principal
        self.setWindowTitle("AFE4490 Advanced Monitor (by Medical Open World)")
        self.resize(1800, 1100)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")

        # Estructuras de Datos
        self.data_lib_id = deque(["?"]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_sample_counter = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_timestamp_us = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ppgdisp = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr1 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_led2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_led1  = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_aled1 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_aled2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_led1_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_led2_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr2      = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr3      = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2_r   = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_pi       = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2_sqi = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr1_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr2_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr3_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_rsqi        = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_diag_code   = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_probe_state = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        # AFE4490DebugData analog signals — populated only when frame_mode == "M4"
        self.data_v_tia_led1  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_v_tia_led2  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_v_tia_aled1 = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_v_tia_aled2 = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_i_pd_led1   = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_i_pd_led2   = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_i_pd_aled1  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_i_pd_aled2  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ot2_led1    = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)  # I_PD_LED1/I_PD_ALED1
        self.data_ot2_led2    = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)  # I_PD_LED2/I_PD_ALED2

        self.is_paused = False
        self.last_time = None
        _s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        self.frame_mode = _s.value("PPGMonitor/frame_mode", "M4")
        
        self.is_saving = False
        self._sub_mismatch_count = 0   # LED2_SUB / LED1_SUB integrity check counter
        self.save_file = None
        self.save_file_chk = None
        self._chk_filename = None
        if save_chk:
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._chk_filename = os.path.join(CAPTURES_DIR, f"ppg_chk_{now_str}.csv")
            try:
                self.save_file_chk = open(self._chk_filename, "w", buffering=1)
                self.save_file_chk.write("Timestamp_PC,Diff_us_PC,CHK_OK,RawFrame\n")
                print(f"[save-chk] Saving to {self._chk_filename}")
                if save_chk_duration > 0:
                    QtCore.QTimer.singleShot(save_chk_duration * 1000, self._auto_close_chk)
            except Exception as e:
                print(f"[save-chk] Error opening file: {e}")
        self.ppgplots_window  = None
        self.signals_window   = None
        self.results_window   = None
        self.serialcom_window = None
        self.udpcom_window    = None
        self.hrlab_window     = None
        self.spo2lab_window   = None
        self.hr3lab_window    = None
        self.spo2test_window  = None
        self.hr1test_window   = None
        self.hr1test_calc     = HR1TestCalc()
        self.hr2test_window   = None
        self.hr3test_window   = None
        self.hr3test_calc     = HR3TestCalc()
        self.pilab_window     = None
        self.esp32_timing_window    = None
        self.python_timing_window   = None
        self.hw_config_window = None
        self.diag_window      = None
        self.afe_sweep_window  = None
        self._pending_tasks   = []   # accumulates $TASK frames until $TASKS_END
        # Render throttle rates (relative to 50ms _render_timer ticks)
        self._PPGPLOTS_REFRESH_EVERY  = 1   # 20 Hz — smooth plot animation
        self._SUBWIN_REFRESH_EVERY    = 2   # 10 Hz — SpO2/HR3 change slowly
        self._SPOST_REFRESH_EVERY     = 2   # 10 Hz
        self._HR1TEST_REFRESH_EVERY   = 2   # 10 Hz
        self._HR2TEST_REFRESH_EVERY   = 2   # 10 Hz
        self._HR3TEST_REFRESH_EVERY   = 2   # 10 Hz
        self._PILAB_REFRESH_EVERY     = 2   # 10 Hz
        self._render_pending          = False
        self._ppgplots_refresh_counter = 0
        self._signals_refresh_counter  = 0
        self._results_refresh_counter  = 0
        self._hrlab_refresh_counter    = 0
        self._spo2lab_refresh_counter  = 0
        self._hr3lab_refresh_counter   = 0
        self._spo2test_refresh_counter = 0
        self._hr1test_refresh_counter  = 0
        self._hr2test_refresh_counter  = 0
        self._hr3test_refresh_counter  = 0
        self._pilab_refresh_counter    = 0
        self._pytiming_refresh_counter = 0
        self._decim_counter = 0
        self.hr3_calc = HRFFTCalc()

        # ── Python timing rolling buffers (last 50 measurements, in ms) ──────────
        _pt_keys = [
            'drain', 'drain_interval', 'render', 'render_interval',
            'algo_spo2lab', 'algo_spo2test', 'algo_hr2test',
            'plot_ppgplots', 'plot_signals', 'plot_results', 'plot_hrlab',
            'plot_spo2lab', 'plot_hr3lab', 'plot_spo2test',
            'plot_hr1test', 'plot_hr2test', 'plot_hr3test', 'plot_pilab',
        ]
        self._py_timing = {k: deque(maxlen=50) for k in _pt_keys}
        self._last_drain_t  = None   # for drain_interval measurement
        self._last_render_t = None   # for render_interval measurement
        self._gaps_B   = 0     # Punto B gap detection (updated in _serial_reader / _udp_reader thread)
        self._udp_port = UDP_DEFAULT_PORT
        self._queue_size_buf        = deque(maxlen=50)  # Punto A: serial queue depth history

        # ── Stats table buffers (reset every N seconds) ───────────────────────
        self._STATS_SIGNALS = [
            # (display_name, data_attr, tooltip_description, src)
            # Order mirrors the $M1/$P1 serial frame. Row indices: HR1=11, HR2=13, HR3=15.
            ("LED1 (IR)",  "data_led1",  "Raw IR LED signal (LED1, ~880–940 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts.",  "AFE4490Data::led1_raw"),
            ("LED2 (RED)", "data_led2",  "Raw RED LED signal (LED2, 660 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts.",        "AFE4490Data::led2_raw"),
            ("ALED1",      "data_aled1", "Ambient IR channel (ALED1): sampled with IR LED off. Represents environmental IR interference. Units: ADC counts.",                  "AFE4490Data::aled1"),
            ("ALED2",      "data_aled2", "Ambient RED channel (ALED2): sampled with RED LED off. Represents environmental red-light interference. Units: ADC counts.",         "AFE4490Data::aled2"),
            ("LED1_SUB",   "data_led1_sub",   "Ambient-subtracted IR signal: LED1 − ALED1. Removes DC ambient component. Main input for HR1, HR2, HR3 and SpO2 algorithms. Units: ADC counts.",    "AFE4490Data::led1_sub"),
            ("LED2_SUB",   "data_led2_sub",   "Ambient-subtracted RED signal: LED2 − ALED2. Removes DC ambient component. Used as input for SpO2 AC/DC decomposition. Units: ADC counts.",         "AFE4490Data::led2_sub"),
            ("PPG_DISP",   "data_ppgdisp",    "Display-ready PPG signal (IR channel). IIR DC removal τ=1.6 s → moving-average low-pass 5 Hz → negated. Ready for rendering on graphical displays. Units: ADC counts.", "AFE4490Data::ppg_disp"),
            ("SpO2",       "data_spo2",       "Blood oxygen saturation computed by firmware (incunest_afe4490). Formula: SpO2 = a − b·R. Range: 70–100 %. Clamped to 100 % if within 3 % above; invalid if >103 %.",    "AFE4490Data::spo2"),
            ("SpO2_SQI",   "data_spo2_sqi",   "SpO2 Signal Quality Index [0–1]. Based on Perfusion Index (PI): SQI = clamp((PI − 0.5) / (2.0 − 0.5), 0, 1). PI < 0.5 % → 0 (no contact or very weak signal). PI ≥ 2.0 % → 1 (full quality). Forced to 0 if SpO2 is outside valid range. Thresholds per Nellcor/Masimo clinical reference.", "AFE4490Data::spo2_sqi"),
            ("R",          "data_spo2_r",     "R ratio used for SpO2 calculation: R = (AC_red/DC_red) / (AC_ir/DC_ir). Dimensionless. Useful for sensor calibration (R-curve).",                   "AFE4490Data::spo2_r"),
            ("PI",         "data_pi",         "Perfusion Index: (AC_ir / DC_ir) × 100 [%]. Measures signal strength / perfusion quality. Typical range: 0.02–20 %. Low PI (<0.3 %) indicates weak signal or poor perfusion.", "AFE4490Data::pi"),
            ("HR1",        "data_hr1",        "Heart rate from algorithm HR1 (adaptive threshold peak detection). Threshold = 0.6 × running_max; refractory 185 ms. Average of last 5 RR intervals. Units: BPM. Valid range: 25–300 BPM.",                    "AFE4490Data::hr1"),
            ("HR1_SQI",    "data_hr1_sqi",    "HR1 Signal Quality Index [0–1]. Coefficient of variation (CV = std/mean) of the 5 most recent RR intervals: SQI = clamp(1 − CV/0.15, 0, 1). CV = 0 (perfectly regular rhythm) → 1. CV ≥ 15 % (arrhythmia or motion artefact) → 0. Forced to 0 if fewer than 5 intervals detected or HR1 outside valid range.", "AFE4490Data::hr1_sqi"),
            ("HR2",        "data_hr2",        "Heart rate from algorithm HR2 (normalized autocorrelation). BPF 0.5–5 Hz → decimate ×10 → 400-sample buffer → autocorr every 0.5 s → first local max ≥ 0.5 → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM.",  "AFE4490Data::hr2"),
            ("HR2_SQI",    "data_hr2_sqi",    "HR2 Signal Quality Index [0–1]. Unbiased normalised autocorrelation at the dominant RR lag: SQI = acorr[τ] / (acorr[0]·(N−τ)/N). Unbiased correction removes finite-window underestimation — clean signal yields SQI ≈ 1.0 at all HR. Minimum threshold 0.5: below this no HR2 is reported and SQI = 0. Forced to 0 if buffer not full or HR2 outside valid range.", "AFE4490Data::hr2_sqi"),
            ("HR3",        "data_hr3",        "Heart rate from algorithm HR3 (FFT + HPS, computed in firmware). LP 10 Hz → decimate ×10 → 512-sample Hann window → FFT → Harmonic Product Spectrum (harmonics 2–3) → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM.", "AFE4490Data::hr3"),
            ("HR3_SQI",    "data_hr3_sqi",    "HR3 Signal Quality Index [0–1]. Spectral concentration of fundamental power at the HPS peak bin vs. search range: SQI = (P[peak]/ΣP[k] − 1/N) / (1 − 1/N). Pure dominant tone → SQI ≈ 1. Diffuse or noisy spectrum → SQI ≈ 0. Forced to 0 if buffer not full or HR3 outside valid range.", "AFE4490Data::hr3_sqi"),
            ("RSQI",       "data_rsqi",       "Raw Signal Quality Index (RSQM). 1 = probe applied and no active diagnostic flags. 0 = invalid (probe not applied, disconnected, or DiagCode != 0). Binary.",                                                   "AFE4490Data::rsqi"),
            ("DiagCode",   "data_diag_code",  "DiagCode bitmask (uint32). Bits 0-12: AFE hardware DIAG register (set by runAfeDiagnostics — PD_ALM, LED_ALM, DIAG_OUT, LED2_ALM, LED3_ALM, LED1_ALM, PDOC_ALM, PDSC_ALM, LED2OC_ALM, LED2SC_ALM, LED1OC_ALM, LED1SC_ALM, COMMON_MODE_ALM). Bits 13+: RSQM — 0x2000=AMB_SAT, 0x4000=SIGNAL_WEAK, 0x8000=HW_SETTLING. 0 = no active conditions.", "AFE4490Data::diag_code"),
            ("ProbeState", "data_probe_state",
             "Probe state computed by RSQM at 500 Hz. All transitions debounced: 100 consecutive samples required (200 ms).\n\n"
             "0 — DISCONNECTED (cable out)\n"
             "ALL 6 conditions simultaneously (AND):\n"
             "  · |I_PD_LED1 [µA]|, |I_PD_LED2 [µA]|, |I_PD_ALED1 [µA]|, |I_PD_ALED2 [µA]| < 0.15 µA\n"
             "  · |LED1_SUB|, |LED2_SUB| < 5000 ADC\n"
             "  Note: both criteria are redundant by design — the led_sub guard prevents false positives when AMBDAC raises i_pd even without probe connected.\n\n"
             "1 — NOT_APPLIED (no finger)\n"
             "Not DISCONNECTED AND at least one channel OT > 8.5×10⁻⁵ (OR logic)  →  rows OT_LED1, OT_LED2\n"
             "  OT = (I_PD_LEDx − I_PD_ALEDx) / I_LEDx  [A/A, dimensionless]\n"
             "  Special case: LED_raw ≥ saturation (2 096 921 ADC) → OT forced to 100 → always NOT_APPLIED.\n\n"
             "2 — APPLIED (finger on sensor)\n"
             "Not DISCONNECTED AND <b>OT ≤ 8.5×10⁻⁵ on both channels</b>.",
             "AFE4490Data::probe_state"),
            # AFE4490DebugData analog signals — only populated in $M4 frame mode
            ("V_TIA_LED1",  "data_v_tia_led1",  "TIA output voltage LED1/IR channel [V]. V_TIA = I_PD × RF. Computed per sample by firmware. Only available in $M4 frame mode.",                  "AFE4490DebugData::v_tia_led1"),
            ("V_TIA_LED2",  "data_v_tia_led2",  "TIA output voltage LED2/RED channel [V]. Only available in $M4 frame mode.",                                                                      "AFE4490DebugData::v_tia_led2"),
            ("V_TIA_ALED1", "data_v_tia_aled1", "TIA output voltage ALED1/IR ambient channel [V]. Only available in $M4 frame mode.",                                                             "AFE4490DebugData::v_tia_aled1"),
            ("V_TIA_ALED2", "data_v_tia_aled2", "TIA output voltage ALED2/RED ambient channel [V]. Only available in $M4 frame mode.",                                                            "AFE4490DebugData::v_tia_aled2"),
            ("I_PD_LED1 [µA]",   "data_i_pd_led1",   "Photodiode current LED1/IR channel [µA]. I_PD = V_TIA / RF. Computed per sample by firmware. Only available in $M4 frame mode.",                "AFE4490DebugData::i_pd_led1"),
            ("I_PD_LED2 [µA]",   "data_i_pd_led2",   "Photodiode current LED2/RED channel [µA]. Only available in $M4 frame mode.",                                                                    "AFE4490DebugData::i_pd_led2"),
            ("I_PD_ALED1 [µA]",  "data_i_pd_aled1",  "Photodiode current ALED1/IR ambient channel [µA]. Only available in $M4 frame mode.",                                                           "AFE4490DebugData::i_pd_aled1"),
            ("I_PD_ALED2 [µA]",  "data_i_pd_aled2",  "Photodiode current ALED2/RED ambient channel [µA]. Only available in $M4 frame mode.",                                                          "AFE4490DebugData::i_pd_aled2"),
            ("OT_LED1",     "data_ot2_led1",     "Optical transmittance LED1 (IR): (I_PD_LED1 - I_PD_ALED1) / I_LED1 [A/A, dimensionless]. Uses I_PD values received from $M4 frame (firmware-computed) and I_LED1 from last $CFG. Only available in $M4 frame mode.", "PPGMonitor.data_ot2_led1"),
            ("OT_LED2",     "data_ot2_led2",     "Optical transmittance LED2 (RED): (I_PD_LED2 - I_PD_ALED2) / I_LED2 [A/A, dimensionless]. Uses I_PD values received from $M4 frame (firmware-computed) and I_LED2 from last $CFG. Only available in $M4 frame mode.", "PPGMonitor.data_ot2_led2"),
        ]
        self._stats_buf = {name: [] for name, _, __, _src in self._STATS_SIGNALS}
        self._stats_highlighted = set()   # set of (row, col) manually highlighted by user
        self._last_cfg = {}               # last parsed $CFG key-value dict (for V_TIA/V_ADC)
        
        self.auto_save_timer = QtCore.QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_stop_save)

        self.lab_capture_window     = None
        self.is_lab_capturing       = False
        self._lab_capture_file      = None
        self._lab_capture_count     = 0
        self._lab_capture_target    = 0
        self._lab_capture_col_spec  = []
        self._lab_capture_filepath  = ""

        self._stats_timer = QtCore.QTimer()
        self._stats_timer.timeout.connect(self._update_stats_table)
        self._stats_timer.start(1000)

        self._autosave_settings_timer = QtCore.QTimer()
        self._autosave_settings_timer.timeout.connect(self._save_settings)
        self._autosave_settings_timer.start(10000)  # save every 10 s

        # Widget Central
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Layout para organizar izquierda (gráficas) y derecha (consola)
        content_layout = QtWidgets.QHBoxLayout()
        
        # 0. Sidebar de Control (Izquierda)
        self.sidebar_layout = QtWidgets.QVBoxLayout()
        self.sidebar_layout.setSpacing(10)

        # ── Sidebar (controls only) ───────────────────────────────────────────

        # PORT section
        label_port = QtWidgets.QLabel("PORT")
        label_port.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px;")
        self.sidebar_layout.addWidget(label_port)

        port_row = QtWidgets.QHBoxLayout()
        self.combo_port = QtWidgets.QComboBox()
        self.combo_port.setStyleSheet(
            "background-color: #2A2A2A; color: #FFDD44; font-size: 18px; padding: 3px;")
        self.combo_port.setToolTip(_make_tooltip(
            "PORT",
            "Serial port selector. Shows all available COM ports. "
            "Select the ESP32-S3 (in3ator V15) port — usually COM15.",
            src="PPGMonitor/serial_port"))
        self.btn_port_refresh = QtWidgets.QPushButton("↺")
        self.btn_port_refresh.setFixedWidth(36)
        self.btn_port_refresh.setStyleSheet(
            "background-color: #2A2A2A; color: #AAAAAA; font-size: 18px; border: 1px solid #444;")
        self.btn_port_refresh.clicked.connect(self._populate_ports)
        self.btn_port_refresh.setToolTip(_make_tooltip(
            "Refresh ports",
            "Rescan the system for available serial ports and update the dropdown list."))
        port_row.addWidget(self.combo_port, stretch=1)
        port_row.addWidget(self.btn_port_refresh)
        self.sidebar_layout.addLayout(port_row)

        self.btn_serial = QtWidgets.QPushButton("SERIAL  ●  OFF")
        self.btn_serial.setStyleSheet(
            "background-color: #1E1E1E; color: #666666; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #444444; border-radius: 4px;")
        self.btn_serial.clicked.connect(self._toggle_serial)
        self.btn_serial.setToolTip(_make_tooltip(
            "SERIAL",
            "Connect or disconnect the serial port (USB-CDC). Click to toggle. "
            "When ON: receives all frames and command responses from the ESP32. "
            "921600 baud, 8N1. Hot-swap: click OFF then ON to reconnect to a different port."))
        self.sidebar_layout.addWidget(self.btn_serial)

        self.btn_udp = QtWidgets.QPushButton("UDP WiFi  ●  OFF")
        self.btn_udp.setStyleSheet(
            "background-color: #1E1E1E; color: #666666; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #444444; border-radius: 4px;")
        self.btn_udp.clicked.connect(self._toggle_udp)
        self.btn_udp.setToolTip(_make_tooltip(
            "UDP WiFi",
            "Start or stop the UDP receiver. Click to toggle. "
            "Runs in parallel with SERIAL — serial port stays open for command responses ($CFG, $DIAG, etc.). "
            f"Listens on the port configured below (default {UDP_DEFAULT_PORT})."))
        self.sidebar_layout.addWidget(self.btn_udp)

        self._lbl_wifi = QtWidgets.QLabel("WiFi: —")
        self._lbl_wifi.setStyleSheet("color: #666666; font-size: 14px; padding: 0px 2px;")
        self._lbl_wifi.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_wifi.setToolTip(_make_tooltip("WiFi SSID", "Network the ESP32 is connected to. Updated when a connection message arrives on the serial stream."))
        self.sidebar_layout.addWidget(self._lbl_wifi)

        self.btn_reset_esp = QtWidgets.QPushButton("RESET ESP32")
        self.btn_reset_esp.setStyleSheet(
            "background-color: #3A1A1A; color: #FF8844; font-size: 16px; "
            "font-weight: bold; padding: 4px; border: 1px solid #FF8844; border-radius: 4px;")
        self.btn_reset_esp.clicked.connect(self._reset_esp32)
        self.btn_reset_esp.setToolTip(_make_tooltip(
            "RESET ESP32",
            "Hardware-reset the ESP32 via RTS/DTR (ESP-Prog auto-reset circuit). "
            "EN is pulled low then released. The firmware prints # SYS: info lines on "
            "startup which appear in this log. The serial port stays open during reset."))
        self.sidebar_layout.addWidget(self.btn_reset_esp)

        self.sidebar_layout.addSpacing(12)

        self.btn_pause = QtWidgets.QPushButton("FREEZE DISPLAY")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setToolTip(_make_tooltip(
            "FREEZE DISPLAY",
            "Freeze or resume the live data display. The serial port stays open and data "
            "keeps flowing; only the UI plots and stats are frozen."))
        self.sidebar_layout.addWidget(self.btn_pause)

        self.btn_save = QtWidgets.QPushButton("SAVE DATA")
        self.btn_save.setCheckable(True)
        self.btn_save.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.toggle_save)
        self.btn_save.setToolTip(_make_tooltip(
            "SAVE DATA",
            "Toggle saving decimated data to a timestamped CSV file. "
            "Records at the display rate (500 Hz ÷ DECIMATION). "
            "Filename: ppg_data_<timestamp>.csv"))
        self.sidebar_layout.addWidget(self.btn_save)

        self.btn_lab_capture = QtWidgets.QPushButton("CAPTURE LAB *")
        self.btn_lab_capture.setCheckable(True)
        self.btn_lab_capture.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_lab_capture.clicked.connect(self.toggle_lab_capture)
        self.btn_lab_capture.setToolTip(_make_tooltip(
            "CAPTURE LAB *",
            "Open the Lab Capture window to configure and trigger controlled 500 Hz "
            "CSV captures for offline algorithm analysis.<br/>"
            "* = runs at full 500 Hz rate, unaffected by the Decimation setting."))
        self.sidebar_layout.addWidget(self.btn_lab_capture)

        self.sidebar_layout.addSpacing(20)

        label_decim = QtWidgets.QLabel("DECIMATION")
        label_decim.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_decim)

        decim_lbl = QtWidgets.QLabel("1 out of every")
        decim_lbl.setStyleSheet("color: #CCCCCC; font-size: 20px;")
        self.sidebar_layout.addWidget(decim_lbl)

        self.spin_decim = QtWidgets.QSpinBox()
        self.spin_decim.setRange(1, 500)
        self.spin_decim.setValue(10)
        self.spin_decim.setSuffix(" frames")
        self.spin_decim.setStyleSheet("background-color: #2A2A2A; color: #FFDD44; padding: 4px; font-size: 20px;")
        self.spin_decim.setToolTip(_make_tooltip(
            "DECIMATION",
            "Show 1 out of every N frames in the UI and in SAVE DATA. "
            "At 500 Hz: N=10 → 50 Hz display, N=1 → 500 Hz. "
            "Lab Capture always records at full 500 Hz regardless of this setting.",
            src="PPGMonitor/decimation"))
        self.sidebar_layout.addWidget(self.spin_decim)

        self.sidebar_layout.addSpacing(20)

        self.frame_mode_combo = QtWidgets.QComboBox()
        self.frame_mode_combo.addItems([
            "$M1  PPG MODE",
            "$M2  BASIC MODE",
            "$M3  FULL MODE",
            "$M4  DEBUG MODE",
        ])
        _fm_idx = {"M1": 0, "M2": 1, "M3": 2, "M4": 3}.get(self.frame_mode, 3)
        self.frame_mode_combo.setCurrentIndex(_fm_idx)
        self.frame_mode_combo.setStyleSheet(
            "QComboBox { background: #002A3A; color: #44AAFF; border: 1px solid #44AAFF;"
            " padding: 4px 8px; font-size: 18px; font-weight: 700; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #001A28; color: #44AAFF;"
            " selection-background-color: #003A4A; border: 1px solid #44AAFF; }")
        self.frame_mode_combo.setToolTip(_make_tooltip(
            "Frame mode",
            "$M1 PPG MODE: minimal frame (SmpCnt, Ts_us, PPG_DISP). Lowest bandwidth.\n"
            "$M2 BASIC MODE: PPG + SpO2 + HR3 + quality flags. Use over serial.\n"
            "$M3 FULL MODE: all AFE4490Data fields (default). Use over UDP.\n"
            "$M4 DEBUG MODE: M3 + V_TIA and I_PD for all 4 channels. Use over UDP for analog analysis.",
            src="$MODE,M{1-4}"))
        self.frame_mode_combo.currentIndexChanged.connect(self._on_frame_mode_combo_changed)
        self.sidebar_layout.addWidget(self.frame_mode_combo)
        self._update_frame_button()

        self.sidebar_layout.addSpacing(20)

        label_display = QtWidgets.QLabel("DISPLAY")
        label_display.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_display)

        self.btn_ppgplots = QtWidgets.QPushButton("PPGPLOTS")
        self.btn_ppgplots.setCheckable(True)
        self.btn_ppgplots.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_ppgplots.clicked.connect(self.toggle_ppgplots)
        self.btn_ppgplots.setToolTip(_make_tooltip(
            "PPGPLOTS",
            "Show or hide the PPG Plots window. "
            "Displays LED2 (RED)/LED1 (IR) raw and filtered signals, PPG_DISP, SpO2 and HR curves in real time. "
            "Throttled to 25 Hz to keep CPU load low.",
            src="PPGPlotsWindow"))
        self.sidebar_layout.addWidget(self.btn_ppgplots)

        self.btn_signals = QtWidgets.QPushButton("SIGNALS")
        self.btn_signals.setCheckable(True)
        self.btn_signals.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_signals.clicked.connect(self.toggle_signals)
        self.btn_signals.setToolTip(_make_tooltip(
            "SIGNALS",
            "Show or hide the PPG Signals window. "
            "Displays the 6 raw AFE4490 channels (LED2/LED1 raw, ambient, clean) "
            "and the PPG_DISP display-ready signal. Throttled to 25 Hz.",
            src="PPGSignalsWindow"))
        self.sidebar_layout.addWidget(self.btn_signals)

        self.btn_results = QtWidgets.QPushButton("RESULTS")
        self.btn_results.setCheckable(True)
        self.btn_results.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_results.clicked.connect(self.toggle_results)
        self.btn_results.setToolTip(_make_tooltip(
            "RESULTS",
            "Show or hide the Algorithm Results window. "
            "Displays SpO2 (top) and HR1/HR2/HR3 (bottom) algorithm outputs with SQI. "
            "Throttled to 10 Hz.",
            src="AlgoResultsWindow"))
        self.sidebar_layout.addWidget(self.btn_results)

        self.btn_serialcom = QtWidgets.QPushButton("SERIALCOM")
        self.btn_serialcom.setCheckable(True)
        self.btn_serialcom.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_serialcom.clicked.connect(self.toggle_serialcom)
        self.btn_serialcom.setToolTip(_make_tooltip(
            "SERIALCOM",
            "Show or hide the Serial Console window. "
            "Displays raw frames received via the serial port.",
            src="SerialComWindow"))
        self.sidebar_layout.addWidget(self.btn_serialcom)

        self.btn_udpcom = QtWidgets.QPushButton("UDP COM")
        self.btn_udpcom.setCheckable(True)
        self.btn_udpcom.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_udpcom.clicked.connect(self.toggle_udpcom)
        self.btn_udpcom.setToolTip(_make_tooltip(
            "UDP COM",
            "Show or hide the UDP Console window. "
            "Displays raw frames received via WiFi/UDP transport.",
            src="UdpComWindow"))
        self.sidebar_layout.addWidget(self.btn_udpcom)

        label_analysis = QtWidgets.QLabel("ANALYSIS")
        label_analysis.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_analysis)

        self.btn_hrlab = QtWidgets.QPushButton("HR2LAB")
        self.btn_hrlab.setCheckable(True)
        self.btn_hrlab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hrlab.clicked.connect(self.toggle_hrlab)
        self.btn_hrlab.setToolTip(_make_tooltip(
            "HR2LAB",
            "Show or hide the HR2 diagnostic window. "
            "Displays the normalised autocorrelation (HR2) used to detect the dominant pulse period.",
            src="HRLabWindow"))
        self.sidebar_layout.addWidget(self.btn_hrlab)

        self.btn_hr3lab = QtWidgets.QPushButton("HR3LAB")
        self.btn_hr3lab.setCheckable(True)
        self.btn_hr3lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr3lab.clicked.connect(self.toggle_hr3lab)
        self.btn_hr3lab.setToolTip(_make_tooltip(
            "HR3LAB",
            "Show or hide the HR3 FFT/HPS analysis window. "
            "Displays FFT spectrum, Harmonic Product Spectrum and HR1/HR2/HR3 comparison in real time. "
            "HR3 uses a 512-sample Hann window + rfft + HPS on the LED1_SUB-signal at 50 Hz.",
            src="HR3LabWindow"))
        self.sidebar_layout.addWidget(self.btn_hr3lab)

        self.btn_spo2lab = QtWidgets.QPushButton("SPO2LAB")
        self.btn_spo2lab.setCheckable(True)
        self.btn_spo2lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_spo2lab.clicked.connect(self.toggle_spo2lab)
        self.btn_spo2lab.setToolTip(_make_tooltip(
            "SPO2LAB",
            "Show or hide the SpO2 Calibration Lab window. "
            "Compare firmware vs local SpO2/R-ratio, capture calibration points and "
            "run linear regression to obtain a·b coefficients for the SpO2 = a − b·R formula.",
            src="SpO2LabWindow"))
        self.sidebar_layout.addWidget(self.btn_spo2lab)

        self.btn_pilab = QtWidgets.QPushButton("PILAB")
        self.btn_pilab.setCheckable(True)
        self.btn_pilab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pilab.clicked.connect(self.toggle_pilab)
        self.btn_pilab.setToolTip(_make_tooltip(
            "PILAB — Perfusion Index Lab",
            "Opens the PI investigation window. Compares two configurable PI pipelines (A vs B) "
            "on live or recorded data. Each pipeline has 3 independent steps: "
            "STEP1 (AC extraction), STEP2 (AC estimator), STEP3 (DC denominator). "
            "Instance A defaults to firmware M1 settings; B is freely configurable.",
            src="PILabWindow"))
        self.sidebar_layout.addWidget(self.btn_pilab)

        label_test = QtWidgets.QLabel("TEST")
        label_test.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_test)

        self.btn_spo2test = QtWidgets.QPushButton("SPO2TEST")
        self.btn_spo2test.setCheckable(True)
        self.btn_spo2test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_spo2test.clicked.connect(self.toggle_spo2test)
        self.btn_spo2test.setToolTip(_make_tooltip(
            "SPO2TEST",
            "Post-implementation verification window for the SpO2 algorithm. "
            "Runs an independent Python mirror of the firmware SpO2 algorithm and compares "
            "its output against the firmware values. Supports live and offline (CSV) modes. "
            "See incunest_afe4490_spec.md §5.1 and §8.2.",
            src="SpO2TestWindow"))
        self.sidebar_layout.addWidget(self.btn_spo2test)

        self.btn_hr1test = QtWidgets.QPushButton("HR1TEST *")
        self.btn_hr1test.setCheckable(True)
        self.btn_hr1test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr1test.clicked.connect(self.toggle_hr1test)
        self.btn_hr1test.setToolTip(_make_tooltip(
            "HR1TEST *",
            "Post-implementation verification window for the HR1 algorithm (threshold peak detection). "
            "Python mirror runs at 500 Hz (full serial rate) in live mode. "
            "See incunest_afe4490_spec.md §5.2 and §8.2.<br/>"
            "* = runs at full 500 Hz rate, unaffected by the Decimation setting.",
            src="HR1TestWindow"))
        self.sidebar_layout.addWidget(self.btn_hr1test)

        self.btn_hr2test = QtWidgets.QPushButton("HR2TEST")
        self.btn_hr2test.setCheckable(True)
        self.btn_hr2test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr2test.clicked.connect(self.toggle_hr2test)
        self.btn_hr2test.setToolTip(_make_tooltip(
            "HR2TEST",
            "Post-implementation verification window for the HR2 algorithm (autocorrelation). "
            "Mirror runs at the decimated rate. See incunest_afe4490_spec.md §5.3 and §8.2.",
            src="HR2TestWindow"))
        self.sidebar_layout.addWidget(self.btn_hr2test)

        self.btn_hr3test = QtWidgets.QPushButton("HR3TEST")
        self.btn_hr3test.setCheckable(True)
        self.btn_hr3test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr3test.clicked.connect(self.toggle_hr3test)
        self.btn_hr3test.setToolTip(_make_tooltip(
            "HR3TEST",
            "Post-implementation verification window for the HR3 algorithm (FFT + HPS). "
            "Mirror runs at the decimated rate. See incunest_afe4490_spec.md §5.4 and §8.2.",
            src="HR3TestWindow"))
        self.sidebar_layout.addWidget(self.btn_hr3test)

        self.btn_esp32_timing = QtWidgets.QPushButton("ESP32 TIMING")
        self.btn_esp32_timing.setCheckable(True)
        self.btn_esp32_timing.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_esp32_timing.clicked.connect(self.toggle_esp32_timing)
        self.btn_esp32_timing.setToolTip(_make_tooltip(
            "ESP32 TIMING — Algorithm CPU Budget",
            "Opens the ESP32 timing diagnostics window. Shows per-algorithm mean/max execution time "
            "(µs) and remaining FreeRTOS stack, parsed from $TIMING frames emitted by the firmware "
            "every ~5 s. Requires INCUNEST_TIMING_STATS=1 in firmware. "
            "Cycle budget = 2000 µs (1 sample period at 500 Hz).",
            src="Esp32TimingWindow"))
        self.sidebar_layout.addWidget(self.btn_esp32_timing)

        self.btn_python_timing = QtWidgets.QPushButton("PYTHON TIMING")
        self.btn_python_timing.setCheckable(True)
        self.btn_python_timing.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_python_timing.clicked.connect(self.toggle_python_timing)
        self.btn_python_timing.setToolTip(_make_tooltip(
            "PYTHON TIMING — Script Performance",
            "Opens the Python timing diagnostics window. Shows mean/max execution time (ms) "
            "for _process_frames_tick() drain and _refresh_plots_tick() total, plus per-window algorithm "
            "and render times. Stats computed over a rolling window of the last 50 measurements. "
            "Drain budget = 20 ms, render budget = 200 ms.",
            src="PythonTimingWindow"))
        self.sidebar_layout.addWidget(self.btn_python_timing)

        self.btn_hw_config = QtWidgets.QPushButton("HW CONFIG")
        self.btn_hw_config.setCheckable(True)
        self.btn_hw_config.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hw_config.clicked.connect(self.toggle_hw_config)
        self.btn_hw_config.setToolTip(_make_tooltip(
            "HW CONFIG — AFE4490 Parameters",
            "Opens the hardware configuration window. Allows changing AFE4490 parameters "
            "(LED current, TIA gain, sample rate, etc.) at runtime via $SET commands, "
            "without reflashing. Confirmation arrives as an updated $CFG frame.",
            src="HWConfigWindow"))
        self.sidebar_layout.addWidget(self.btn_hw_config)

        self.btn_diagnostics = QtWidgets.QPushButton("DIAGNOSTICS")
        self.btn_diagnostics.setCheckable(True)
        self.btn_diagnostics.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_diagnostics.clicked.connect(self.toggle_diagnostics)
        self.btn_diagnostics.setToolTip(_make_tooltip(
            "DIAGNOSTICS — AFE4490 fault detection",
            "Opens the diagnostics window. Sends $DIAG? to the ESP32, which runs "
            "the AFE4490 built-in diagnostic sequence (~10 ms) and reports LED, "
            "photodiode, and cable fault flags (datasheet section 8.4.3.3).",
            src="DiagnosticsWindow"))
        self.sidebar_layout.addWidget(self.btn_diagnostics)

        self.btn_afe_sweep = QtWidgets.QPushButton("AFE SWEEP")
        self.btn_afe_sweep.setCheckable(True)
        self.btn_afe_sweep.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_afe_sweep.clicked.connect(self.toggle_afe_sweep)
        self.btn_afe_sweep.setToolTip(_make_tooltip(
            "AFE SWEEP TEST — parametric sweep",
            "Opens the AFE characterisation sweep window. Sweeps 3 levels each of "
            "LED current, TIA gain (RF), stage-2 gain (RG) and ambient DAC for both "
            "LED1 and LED2 (162 combos total). Records mean/min/max/pp/std of all "
            "six raw ADC channels per combo to a CSV file for offline analysis.",
            src="AFESweepTestWindow"))
        self.sidebar_layout.addWidget(self.btn_afe_sweep)

        self.sidebar_layout.addStretch()

        # ── Log panel (right of sidebar, fills remaining space) ───────────────
        self.log_panel = QtWidgets.QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A2E; color: #E0E0E0;
                font-family: monospace; font-size: 28px;
                border: 1px solid #333355; border-radius: 6px; padding: 4px 8px;
            }
        """)

        # ── Stats table widget ────────────────────────────────────────────────
        stats_container = QtWidgets.QWidget()
        stats_container.setStyleSheet("background-color: #1A1A1A; border: 1px solid #333333; border-radius: 6px;")
        stats_vbox = QtWidgets.QVBoxLayout(stats_container)
        stats_vbox.setContentsMargins(6, 6, 6, 6)
        stats_vbox.setSpacing(4)

        stats_header = QtWidgets.QHBoxLayout()
        stats_title = QtWidgets.QLabel("SIGNAL STATS")
        stats_title.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 22px;")
        stats_header.addWidget(stats_title)
        stats_header.addStretch()
        stats_interval_lbl = QtWidgets.QLabel("Update interval:")
        stats_interval_lbl.setStyleSheet("color: #CCCCCC; font-size: 22px;")
        self.spin_stats_interval = QtWidgets.QSpinBox()
        self.spin_stats_interval.setRange(1, 60)
        self.spin_stats_interval.setValue(1)
        self.spin_stats_interval.setSuffix(" s")
        self.spin_stats_interval.setStyleSheet("background-color: #2A2A2A; color: #FFDD44; padding: 2px; font-size: 22px;")
        self.spin_stats_interval.setFixedWidth(110)
        self.spin_stats_interval.valueChanged.connect(
            lambda v: self._stats_timer.setInterval(v * 1000))
        self.spin_stats_interval.setToolTip(_make_tooltip(
            "Stats update interval",
            "How often the Signal Stats table recalculates and resets its running statistics "
            "(Last / Mean / Max-Min / Min / Max). Range: 1–60 s.",
            src="PPGMonitor/stats_interval"))
        stats_header.addWidget(stats_interval_lbl)
        stats_header.addWidget(self.spin_stats_interval)
        stats_vbox.addLayout(stats_header)

        self.stats_table = QtWidgets.QTableWidget(len(self._STATS_SIGNALS) + 1, 9)
        self.stats_table.setHorizontalHeaderLabels(["Signal", "V_TIA", "V_ADC", "% SD/Mean", "Mean", "SD", "Max-Min", "Min", "Max"])
        _hdr_font_normal = QtGui.QFont()
        _hdr_font_normal.setPixelSize(33)
        _hdr_font_small  = QtGui.QFont()
        _hdr_font_small.setPixelSize(9)
        for _c in range(9):
            _f = _hdr_font_small if _c == 3 else _hdr_font_normal
            self.stats_table.horizontalHeaderItem(_c).setFont(_f)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.stats_table.setSelectionMode(QtWidgets.QAbstractItemView.ContiguousSelection)
        self.stats_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                background-color: #111111; color: #E0E0E0;
                font-family: monospace; font-size: 28px;
                gridline-color: #2A2A2A; border: none;
            }
            QHeaderView::section {
                background-color: #1E1E2E; color: #AAAAAA;
                font-weight: bold;
                padding: 6px; border: 1px solid #2A2A2A;
            }
            QTableWidget::item { padding: 6px 10px; }
            QTableWidget::item:selected {
                background-color: #2A4A6A; color: #FFFFFF;
            }
        """)
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        for col in range(1, 9):
            self.stats_table.horizontalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
        self.stats_table.verticalHeader().setDefaultSectionSize(40)

        _HR_ROWS    = {11, 13, 15}   # HR1, HR2, HR3 (signal indices)
        _RAW_ROWS   = {0, 1, 2, 3}   # LED1 (IR), LED2 (RED), ALED1, ALED2
        _MEAN_COL   = 4
        _MAROON     = QtGui.QColor("#5C001A")
        _SUBHDR_ROW = 4              # table row index of the sub-header divider

        for sig_idx, (name, _, tooltip, src) in enumerate(self._STATS_SIGNALS):
            tbl_row  = sig_idx if sig_idx < _SUBHDR_ROW else sig_idx + 1
            rich_tip = _make_tooltip(name, tooltip, src=src)
            item = QtWidgets.QTableWidgetItem(name)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            item.setToolTip(rich_tip)
            self.stats_table.setItem(tbl_row, 0, item)
            for col in range(1, 9):
                text = "" if (sig_idx not in _RAW_ROWS and col in {1, 2}) else "---"
                it = QtWidgets.QTableWidgetItem(text)
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                it.setToolTip(rich_tip)
                if sig_idx in _HR_ROWS and col == _MEAN_COL:
                    it.setBackground(_MAROON)
                self.stats_table.setItem(tbl_row, col, it)

        # Sub-header divider row between ALED2 (row 3) and LED1_SUB (row 5)
        _subhdr_labels  = ["Signal", "ADZ", "% ADZ/Mean", "% SD/Mean", "Mean", "SD", "Max-Min", "Min", "Max"]
        _subhdr_bg      = QtGui.QColor("#1E1E2E")
        _subhdr_fg      = QtGui.QColor("#AAAAAA")
        for col, lbl in enumerate(_subhdr_labels):
            it = QtWidgets.QTableWidgetItem(lbl)
            it.setBackground(_subhdr_bg)
            it.setForeground(_subhdr_fg)
            it.setTextAlignment(QtCore.Qt.AlignCenter)
            self.stats_table.setItem(_SUBHDR_ROW, col, it)
        # Constrain the sub-header row to the same height as the horizontal header so that
        # the physical-pixel fonts (pixelSize=33/9) render with the same visual size as in the header
        _hdr_h = self.stats_table.horizontalHeader().sizeHint().height()
        self.stats_table.setRowHeight(_SUBHDR_ROW, _hdr_h if _hdr_h > 0 else 36)

        # Paired gray highlight: LED1_SUB/% SD/Mean and PI/Mean share the same meaning
        # (LED1_SUB % SD/Mean ≈ AC/DC ≈ PI, so these two cells are conceptually equivalent)
        _ACCENT_PAIR = QtGui.QColor("#5A1A4A")
        self.stats_table.item(5,  3).setBackground(_ACCENT_PAIR)  # LED1_SUB  / % SD/Mean
        self.stats_table.item(11, 4).setBackground(_ACCENT_PAIR)  # PI      / Mean

        # Override V_TIA (col 7) and V_ADC (col 8) tooltips on raw rows (0-3)
        # with specific descriptions including color-coding legend and voltage units.
        _TIP_VTIA_LED = _make_tooltip("V_TIA",
            "TIA differential output voltage estimated from the mean ADC count.\n"
            "Formula: V_TIA = (V_ADC / (2\u00d7RG)) \u00d7 RI  (datasheet eq.2, p.30)\n"
            "RI = 100 k\u03a9 (fixed internal), RG from current \\$CFG stg21/stg22.\n"
            "Units: V (volts).\n\n"
            "Background color (LED phases \u2014 LED1 (IR), LED2 (RED)):\n"
            "  Green   0.40 \u2013 0.80 V \u2014 optimal operating range\n"
            "  Yellow  0.15 \u2013 0.40 V  or  0.80 \u2013 0.95 V \u2014 caution\n"
            "  Red     < 0.15 V  or  > 0.95 V \u2014 saturation or insufficient signal")
        _TIP_VTIA_AMB = _make_tooltip("V_TIA",
            "TIA differential output voltage estimated from the mean ADC count.\n"
            "Formula: V_TIA = (V_ADC / (2\u00d7RG)) \u00d7 RI  (datasheet eq.2, p.30)\n"
            "RI = 100 k\u03a9 (fixed internal), RG from current \\$CFG stg21/stg22.\n"
            "Units: V (volts).\n\n"
            "Background color (ALED phases \u2014 ALED1, ALED2):\n"
            "  Green   < 0.30 V \u2014 low ambient (safe)\n"
            "  Yellow  0.30 \u2013 0.70 V \u2014 moderate ambient, monitor\n"
            "  Red     > 0.70 V \u2014 high ambient, risk of saturation")
        _TIP_VADC_LED = _make_tooltip("V_ADC",
            "ADC input voltage estimated from the mean ADC count.\n"
            "Formula: V_ADC = (mean_counts / 2\u00b2\u00b9) \u00d7 1.2 V  (ADC FS = \u00b11.2 V, 22-bit signed).\n"
            "Units: V (volts).\n\n"
            "Background color (LED phases \u2014 LED1 (IR), LED2 (RED)):\n"
            "  Green   0.45 \u2013 0.95 V \u2014 optimal\n"
            "  Yellow  0.20 \u2013 0.45 V  or  0.95 \u2013 1.10 V \u2014 caution\n"
            "  Red     < 0.20 V  or  > 1.10 V \u2014 insufficient signal or near saturation")
        _TIP_VADC_AMB = _make_tooltip("V_ADC",
            "ADC input voltage estimated from the mean ADC count.\n"
            "Formula: V_ADC = (mean_counts / 2\u00b2\u00b9) \u00d7 1.2 V  (ADC FS = \u00b11.2 V, 22-bit signed).\n"
            "Units: V (volts).\n\n"
            "Background color (ALED phases \u2014 ALED1, ALED2):\n"
            "  Green   < 0.35 V \u2014 low ambient (safe)\n"
            "  Yellow  0.35 \u2013 0.80 V \u2014 moderate ambient\n"
            "  Red     > 0.80 V \u2014 high ambient, risk of saturation")
        for _r in range(4):
            _tip7 = _TIP_VTIA_LED if _r in {0, 1} else _TIP_VTIA_AMB
            _tip8 = _TIP_VADC_LED if _r in {0, 1} else _TIP_VADC_AMB
            self.stats_table.item(_r, 1).setToolTip(_tip7)
            self.stats_table.item(_r, 2).setToolTip(_tip8)

        # Override R col 1 tooltip: derived R estimate, not true % SD/Mean
        self.stats_table.item(10, 3).setToolTip(_make_tooltip("R estimate",
            "Derived R ratio: CV(LED2_SUB) / CV(LED1_SUB)\n"
            "where CV = SD / Mean \u00d7 100  (\u2248 AC/DC per channel).\n\n"
            "Approximates the SpO2 R value:\n"
            "  R = (AC_red/DC_red) / (AC_ir/DC_ir)\n\n"
            "Displayed in italics \u2014 this cell does not show % SD/Mean\n"
            "like the LED1_SUB/LED2_SUB rows above; it is a derived ratio.\n"
            "Useful for a quick sanity-check of the R value without\n"
            "running the full SpO2 algorithm."))

        self.stats_table.setItemDelegate(
            _StatsHighlightDelegate(self._stats_highlighted, self.stats_table, _SUBHDR_ROW, self.stats_table))
        self.stats_table.cellClicked.connect(self._on_stats_cell_clicked)
        _copy_sc = QtWidgets.QShortcut(QtGui.QKeySequence.Copy, self.stats_table)
        _copy_sc.activated.connect(self._copy_stats_selection)
        stats_vbox.addWidget(self.stats_table)

        # ── Right side: stats table + log panel ───────────────────────────────
        self.right_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.right_splitter.addWidget(stats_container)
        self.right_splitter.addWidget(self.log_panel)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        content_layout.addLayout(self.sidebar_layout)
        content_layout.addWidget(self.right_splitter, stretch=1)
        main_layout.addLayout(content_layout)

        self.ser = None
        self._serial_queue = queue.Queue()
        self._udp_queue    = queue.Queue()
        self._reader_stop  = threading.Event()   # controls _serial_reader thread
        self._reader_thread = None
        self._udp_stop     = threading.Event()   # controls _udp_reader thread
        self._udp_thread   = None
        self._esp32_ip     = None   # ESP32 IP learned from first incoming UDP packet
        self._cmd_udp_sock = None   # UDP socket for sending commands to ESP32 (port UDP_CMD_PORT)
        self._cfg_listener = None  # callable(text) set by LabCaptureWindow
        self._active_transport = "serial"  # "serial" or "udp" — only this queue feeds algorithms

        self._populate_ports()
        self._restore_settings()
            
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._process_frames_tick)
        self.timer.start(20)

        self._render_timer = QtCore.QTimer()
        self._render_timer.timeout.connect(self._refresh_plots_tick)
        self._render_timer.start(200)
        self._hb = QtCore.QTimer()
        self._hb.timeout.connect(
            lambda: open("debug_hb.log", "w").write(
                f"{__import__('time').perf_counter():.3f}\n"))
        self._hb.start(500)

    STYLE_LIB_ACTIVE = """
        QPushButton {{
            background-color: {bg}; color: {fg};
            border-radius: 5px; padding: 5px; font-weight: bold;
            border: 2px solid {fg}; font-size: 18px;
        }}
        QPushButton:hover {{ background-color: {bgh}; }}
    """
    STYLE_LIB_INACTIVE = """
        QPushButton {
            background-color: #222222; color: #555555;
            border-radius: 5px; padding: 5px; font-weight: bold;
            border: 2px solid #444444; font-size: 18px;
        }
        QPushButton:hover { background-color: #2A2A2A; }
    """

    _FRAME_MODES = ["M1", "M2", "M3", "M4"]

    def _update_frame_button(self):
        idx = self._FRAME_MODES.index(self.frame_mode) if self.frame_mode in self._FRAME_MODES else 2
        self.frame_mode_combo.blockSignals(True)
        self.frame_mode_combo.setCurrentIndex(idx)
        self.frame_mode_combo.blockSignals(False)

    def _on_frame_mode_combo_changed(self, idx):
        mode = self._FRAME_MODES[idx]
        self._send_frame_cmd(mode)

    def _send_frame_cmd(self, mode):
        if not self._is_cmd_ready():
            return
        self.send_cmd(f"$MODE,{mode}\n".encode())
        self.frame_mode = mode
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("PPGMonitor/frame_mode", mode)
        self._update_frame_button()

    def request_chip_config(self, notify_lab_capture=True):
        """Send $CFG? to ESP32. Response arrives asynchronously via _on_cfg_frame_received().
        notify_lab_capture: forward response to _cfg_listener (LabCaptureWindow Pre-capture notes).
        HWConfigWindow is always updated when a $CFG frame arrives (no flag needed)."""
        if not self._is_cmd_ready():
            return False
        self._cfg_notify_lab_capture = notify_lab_capture
        self.log("CFG request sent → $CFG?")
        self.send_cmd(b'$CFG?\n')
        return True

    def _is_cmd_ready(self):
        """True if a command channel is available: serial open, or UDP active with known ESP32 IP."""
        if self._active_transport == "udp" and self._esp32_ip is not None:
            return True
        return self.ser is not None and self.ser.is_open

    def send_cmd(self, data: bytes):
        """Route a command to the ESP32 via serial or UDP depending on active transport.
        Serial: written directly to the open COM port.
        UDP: sent as a single datagram to ESP32 IP:UDP_CMD_PORT (learned from incoming data)."""
        if self._active_transport == "udp" and self._esp32_ip is not None:
            import socket as _socket
            if self._cmd_udp_sock is None:
                self._cmd_udp_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            self._cmd_udp_sock.sendto(data, (self._esp32_ip, UDP_CMD_PORT))
        elif self.ser is not None and self.ser.is_open:
            self.ser.write(data)

    def _on_cfg_frame_received(self, line):
        """Parse a $CFG frame, log each field, and deliver formatted text to _cfg_listener."""
        kv = {}
        for part in line[len('$CFG,'):].split(','):
            if '=' in part:
                k, v = part.split('=', 1)
                kv[k] = v
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log(
            f"$CFG  board={kv.get('board','?')}  sr={kv.get('sr','?')}Hz  numav={kv.get('numav','?')}"
            f"  led1={kv.get('led1','?')}mA  tia1={kv.get('tia1','?')}  stg21={kv.get('stg21','?')}"
            f"  led2={kv.get('led2','?')}mA  tia2={kv.get('tia2','?')}  stg22={kv.get('stg22','?')}"
            f"  ambdac={kv.get('ambdac','?')}µA  ch={kv.get('ch','?')}"
        )
        text = (
            f"AFE4490 config — {ts}\n"
            f"  Board: {kv.get('board','?')}   MAC: {kv.get('mac','?')}\n"
            f"  Sample rate: {kv.get('sr','?')} Hz   NUMAV: {kv.get('numav','?')}\n"
            f"  LED1: {kv.get('led1','?')} mA   LED2: {kv.get('led2','?')} mA   Range: {kv.get('range','?')} mA\n"
            f"  ENSEPGAIN: {kv.get('ensepgain','?')}\n"
            f"  LED1: TIA={kv.get('tia1','?')}   CF={kv.get('cf1','?')}   STG2={kv.get('stg21','?')}   EN={kv.get('stage2en1','?')}\n"
            f"  LED2: TIA={kv.get('tia2','?')}   CF={kv.get('cf2','?')}   STG2={kv.get('stg22','?')}   EN={kv.get('stage2en2','?')}\n"
            f"  AMBDAC: {kv.get('ambdac','?')} µA\n"
            f"  PPG channel: {kv.get('ch','?')}   Filter: BW [{kv.get('fl','?')}–{kv.get('fh','?')} Hz]\n"
            f"  HR2 BPF: {kv.get('hr2l','?')}–{kv.get('hr2h','?')} Hz   HR3 LPF: {kv.get('hr3h','?')} Hz\n"
            f"  SpO2: a={kv.get('spo2a','?')}  b={kv.get('spo2b','?')}"
        )
        if self._cfg_listener is not None and getattr(self, '_cfg_notify_lab_capture', True):
            self._cfg_listener(text)
        self._last_cfg = kv
        if self.hw_config_window is not None:
            self.hw_config_window.update_from_cfg(kv)
        if self.pilab_window is not None:
            self.pilab_window._sync_spo2_coeffs(kv)
        self._cfg_notify_lab_capture = True   # reset to default after each frame

    def _on_tcfg_frame_received(self, line):
        """Parse a $TCFG frame and deliver timing values to HWConfigWindow (if open)."""
        kv = {}
        for part in line[len('$TCFG,'):].split(','):
            if '=' in part:
                k, v = part.split('=', 1)
                kv[k] = v
        self.log(f"[TCFG] received ({len(kv)} timing registers)")
        if self.hw_config_window is not None:
            self.hw_config_window.update_from_tcfg(kv)

    def _on_diag_frame_received(self, line):
        """Parse a $DIAG frame and update DiagnosticsWindow (if open)."""
        # Format: $DIAG,XXXXXX*YY
        try:
            raw = int(line[len('$DIAG,'):].split('*')[0].strip(), 16)
        except (ValueError, IndexError):
            self.log(f"⚠ Malformed $DIAG frame: {line}")
            return
        self.log(f"[DIAG] 0x{raw:06X}")
        if self.diag_window is not None:
            self.diag_window.update_from_diag(raw)

    def _reset_esp32(self):
        """Reset the ESP32.
        Serial mode: hardware reset via RTS/DTR (ESP-Prog auto-reset circuit).
        UDP mode:    soft reset via $RESET command (ESP.restart() on firmware side).
        """
        if self._active_transport == "udp" and self._esp32_ip is not None:
            try:
                self.send_cmd(b"$RESET\n")
                self.log("ESP32 soft-reset triggered ($RESET via UDP)")
                self._post_reset_cfg_pending = True
            except Exception as e:
                self.log(f"Reset failed: {e}")
        elif self.ser is not None and self.ser.is_open:
            try:
                self.ser.dtr = False   # IO0 high → run mode (not bootloader)
                self.ser.rts = True    # EN low  → reset active
                time.sleep(0.1)
                self.ser.rts = False   # EN high → chip boots in run mode
                # DTR stays False: IO0 remains high → normal firmware, not bootloader
                self.log("ESP32 hard-reset triggered (RTS/DTR via ESP-Prog)")
                self._post_reset_cfg_pending = True
            except Exception as e:
                self.log(f"Reset failed: {e}")
        else:
            self.log("Not connected — cannot reset ESP32")

    def _open_hrlab_default(self):
        self.btn_hrlab.setChecked(True)
        self.toggle_hrlab()

    def toggle_hrlab(self):
        if self.btn_hrlab.isChecked():
            self.hrlab_window = HRLabWindow(None)
            self.hrlab_window.main_monitor = self
            self.hrlab_window.show()
        else:
            if self.hrlab_window is not None:
                self.hrlab_window.main_monitor = None  # prevent recursive callback
                self.hrlab_window.close()
                self.hrlab_window = None

    def _open_ppgplots_default(self):
        self.btn_ppgplots.setChecked(True)
        self.toggle_ppgplots()

    def _open_signals_default(self):
        self.btn_signals.setChecked(True)
        self.toggle_signals()

    def toggle_signals(self):
        if self.btn_signals.isChecked():
            self.signals_window = PPGSignalsWindow(None)
            self.signals_window.main_monitor = self
            self.signals_window.show()
        else:
            if self.signals_window is not None:
                self.signals_window.main_monitor = None
                self.signals_window.close()
                self.signals_window = None

    def _open_results_default(self):
        self.btn_results.setChecked(True)
        self.toggle_results()

    def toggle_results(self):
        if self.btn_results.isChecked():
            self.results_window = AlgoResultsWindow(None)
            self.results_window.main_monitor = self
            self.results_window.show()
        else:
            if self.results_window is not None:
                self.results_window.main_monitor = None
                self.results_window.close()
                self.results_window = None

    def toggle_ppgplots(self):
        if self.btn_ppgplots.isChecked():
            self.ppgplots_window = PPGPlotsWindow(None)
            self.ppgplots_window.main_monitor = self
            self.ppgplots_window.show()
        else:
            if self.ppgplots_window is not None:
                self.ppgplots_window.main_monitor = None
                self.ppgplots_window.close()
                self.ppgplots_window = None

    def _open_serialcom_default(self):
        self.btn_serialcom.setChecked(True)
        self.toggle_serialcom()

    def toggle_serialcom(self):
        if self.btn_serialcom.isChecked():
            self.serialcom_window = SerialComWindow(None)
            self.serialcom_window.main_monitor = self
            self.serialcom_window.show()
        else:
            if self.serialcom_window is not None:
                self.serialcom_window.main_monitor = None
                self.serialcom_window.close()
                self.serialcom_window = None

    def toggle_udpcom(self):
        if self.btn_udpcom.isChecked():
            self.udpcom_window = UdpComWindow(None)
            self.udpcom_window.main_monitor = self
            self.udpcom_window.show()
        else:
            if self.udpcom_window is not None:
                self.udpcom_window.main_monitor = None
                self.udpcom_window.close()
                self.udpcom_window = None

    def _open_hr3lab_default(self):
        self.btn_hr3lab.setChecked(True)
        self.toggle_hr3lab()

    def toggle_hr3lab(self):
        if self.btn_hr3lab.isChecked():
            self.hr3lab_window = HR3LabWindow(None)
            self.hr3lab_window.main_monitor = self
            self.hr3lab_window.show()
        else:
            if self.hr3lab_window is not None:
                self.hr3lab_window.main_monitor = None
                self.hr3lab_window.close()
                self.hr3lab_window = None

    def _open_spo2lab_default(self):
        self.btn_spo2lab.setChecked(True)
        self.toggle_spo2lab()

    def toggle_spo2lab(self):
        if self.btn_spo2lab.isChecked():
            self.spo2lab_window = SpO2LabWindow(None)
            self.spo2lab_window.main_monitor = self
            self.spo2lab_window.show()
        else:
            if self.spo2lab_window is not None:
                self.spo2lab_window.main_monitor = None
                self.spo2lab_window.close()
                self.spo2lab_window = None

    def _open_spo2test_default(self):
        self.btn_spo2test.setChecked(True)
        self.toggle_spo2test()

    def toggle_spo2test(self):
        if self.btn_spo2test.isChecked():
            self.spo2test_window = SpO2TestWindow(None)
            self.spo2test_window.main_monitor = self
            self.spo2test_window.show()
        else:
            if self.spo2test_window is not None:
                self.spo2test_window.main_monitor = None
                self.spo2test_window.close()
                self.spo2test_window = None

    def _open_hr1test_default(self):
        self.btn_hr1test.setChecked(True)
        self.toggle_hr1test()

    def toggle_hr1test(self):
        if self.btn_hr1test.isChecked():
            self.hr1test_window = HR1TestWindow(None)
            self.hr1test_window.main_monitor = self
            self.hr1test_window.show()
        else:
            if self.hr1test_window is not None:
                self.hr1test_window.main_monitor = None
                self.hr1test_window.close()
                self.hr1test_window = None

    def _open_hr2test_default(self):
        self.btn_hr2test.setChecked(True)
        self.toggle_hr2test()

    def toggle_hr2test(self):
        if self.btn_hr2test.isChecked():
            self.hr2test_window = HR2TestWindow(None)
            self.hr2test_window.main_monitor = self
            self.hr2test_window.show()
        else:
            if self.hr2test_window is not None:
                self.hr2test_window.main_monitor = None
                self.hr2test_window.close()
                self.hr2test_window = None

    def _open_hr3test_default(self):
        self.btn_hr3test.setChecked(True)
        self.toggle_hr3test()

    def toggle_hr3test(self):
        if self.btn_hr3test.isChecked():
            self.hr3test_window = HR3TestWindow(None)
            self.hr3test_window.main_monitor = self
            self.hr3test_window.show()
        else:
            if self.hr3test_window is not None:
                self.hr3test_window.main_monitor = None
                self.hr3test_window.close()
                self.hr3test_window = None

    def _open_pilab_default(self):
        self.btn_pilab.setChecked(True)
        self.toggle_pilab()

    def toggle_pilab(self):
        if self.btn_pilab.isChecked():
            self.pilab_window = PILabWindow(None)
            self.pilab_window.main_monitor = self
            self.pilab_window._sync_spo2_coeffs(self._last_cfg)
            self.pilab_window.show()
        else:
            if self.pilab_window is not None:
                self.pilab_window.main_monitor = None
                self.pilab_window.close()
                self.pilab_window = None

    def _open_timing_default(self):
        self.btn_esp32_timing.setChecked(True)
        self.toggle_esp32_timing()

    def _open_hw_config_default(self):
        self.btn_hw_config.setChecked(True)
        self.toggle_hw_config()

    def _open_diagnostics_default(self):
        self.btn_diagnostics.setChecked(True)
        self.toggle_diagnostics()

    def _open_python_timing_default(self):
        self.btn_python_timing.setChecked(True)
        self.toggle_python_timing()

    def toggle_python_timing(self):
        if self.btn_python_timing.isChecked():
            self.python_timing_window = PythonTimingWindow(None)
            self.python_timing_window.main_monitor = self
            self.python_timing_window.show()
        else:
            if self.python_timing_window is not None:
                self.python_timing_window.close()
                self.python_timing_window = None

    def toggle_esp32_timing(self):
        if self.btn_esp32_timing.isChecked():
            self.esp32_timing_window = Esp32TimingWindow(None)
            self.esp32_timing_window.main_monitor = self
            self.esp32_timing_window.show()
        else:
            if self.esp32_timing_window is not None:
                self.esp32_timing_window.close()
                self.esp32_timing_window = None

    def toggle_hw_config(self):
        if self.btn_hw_config.isChecked():
            self.hw_config_window = HWConfigWindow(None)
            self.hw_config_window.main_monitor = self
            self.hw_config_window.show()
            # Use silent auto-read (no modal) — serial may not be ready yet at startup.
            QtCore.QTimer.singleShot(200, self.hw_config_window._auto_read_cfg)
        else:
            if self.hw_config_window is not None:
                self.hw_config_window.main_monitor = None
                self.hw_config_window.close()
                self.hw_config_window = None

    def toggle_diagnostics(self):
        if self.btn_diagnostics.isChecked():
            self.diag_window = DiagnosticsWindow(None)
            self.diag_window.main_monitor = self
            self.diag_window.show()
        else:
            if self.diag_window is not None:
                self.diag_window.main_monitor = None
                self.diag_window.close()
                self.diag_window = None

    def _open_afe_sweep_default(self):
        self.btn_afe_sweep.setChecked(True)
        self.toggle_afe_sweep()

    def toggle_afe_sweep(self):
        if self.btn_afe_sweep.isChecked():
            self.afe_sweep_window = AFESweepTestWindow(self)
            self.afe_sweep_window.show()
        else:
            if self.afe_sweep_window is not None:
                self.afe_sweep_window.main_monitor = None
                self.afe_sweep_window.close()
                self.afe_sweep_window = None

    def _open_lab_capture_default(self):
        self.btn_lab_capture.setChecked(True)
        self.toggle_lab_capture()

    def toggle_lab_capture(self):
        if self.btn_lab_capture.isChecked():
            self.lab_capture_window = LabCaptureWindow(self)
            self.lab_capture_window.show()
        else:
            if self.lab_capture_window is not None:
                self.lab_capture_window.main_monitor = None
                self.lab_capture_window.close()
                self.lab_capture_window = None

    def start_lab_capture(self, target: int, col_spec: list,
                          filepath: str, pre_notes: str):
        """Open the capture file, write pre-notes and header, start counting."""
        if self.is_paused:
            self.log("Cannot capture LAB while paused")
            return
        try:
            f = open(filepath, "w", buffering=1, encoding="utf-8-sig")
            if pre_notes.strip():
                for txt in pre_notes.splitlines():
                    f.write(f"# {txt}\n")
            f.write(",".join(csv_name for csv_name, _ in col_spec) + "\n")
            self._lab_capture_file = f
        except Exception as e:
            self.log(f"Error opening lab capture file: {e}")
            return
        self.is_lab_capturing      = True
        self._lab_capture_count    = 0
        self._lab_capture_target   = target
        self._lab_capture_col_spec = col_spec
        self._lab_capture_filepath = filepath
        mode = f"{target} samples" if target > 0 else "continuous"
        self.log(f"LAB CAPTURE recording ({mode}): {os.path.basename(filepath)}")
        if self.lab_capture_window is not None:
            self.lab_capture_window.on_capture_started(filepath, target)

    def stop_lab_capture(self, post_notes: str = ""):
        """Flush post-notes, close the file, update the window."""
        if not self.is_lab_capturing:
            return
        self.is_lab_capturing = False
        count    = self._lab_capture_count
        filepath = self._lab_capture_filepath
        if self._lab_capture_file:
            if post_notes.strip():
                for txt in post_notes.splitlines():
                    self._lab_capture_file.write(f"# {txt}\n")
            self._lab_capture_file.close()
            self._lab_capture_file = None
        self.log(f"LAB CAPTURE done: {count} samples → {os.path.basename(filepath)}")
        if self.lab_capture_window is not None:
            self.lab_capture_window.on_capture_done(count, filepath)

    def _write_lab_capture_row(self, raw_line: str):
        """Write one CSV row from a raw serial frame. Called at 500 Hz."""
        parts = raw_line[1:].split('*')[0].split(',')   # strip '$' and checksum
        n = len(parts)
        is_m2 = (n >= 1 and parts[0] == "M2")
        # M2 parts layout: [0]=M2 [1]=cnt [2]=LED2 [3]=LED1 [4]=ALED2 [5]=ALED1 [6]=LED2_SUB [7]=LED1_SUB
        _M2_MAP = {3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7}

        row_vals = []
        for csv_name, m1_idx in self._lab_capture_col_spec:
            if is_m2:
                mapped = _M2_MAP.get(m1_idx, -1)
                row_vals.append(parts[mapped] if 0 <= mapped < n else "-1")
            else:
                row_vals.append(parts[m1_idx] if m1_idx < n else "-1")

        self._lab_capture_file.write(",".join(row_vals) + "\n")
        self._lab_capture_count += 1

        # Progress update throttled to every 50 samples
        if self._lab_capture_count % 50 == 0 and self.lab_capture_window is not None:
            self.lab_capture_window.on_capture_progress(
                self._lab_capture_count, self._lab_capture_target)

        # Auto-stop for timed capture
        if (self._lab_capture_target > 0
                and self._lab_capture_count >= self._lab_capture_target):
            post = (self.lab_capture_window._post_notes.toPlainText()
                    if self.lab_capture_window else "")
            QtCore.QTimer.singleShot(0, lambda: self.stop_lab_capture(post_notes=post))

    def toggle_pause(self):
        self.is_paused = self.btn_pause.isChecked()
        if self.is_paused:
            self.btn_pause.setText("RESUME DISPLAY")
            self.log("Display FROZEN")
        else:
            self.btn_pause.setText("FREEZE DISPLAY")
            self.log(f"System ONLINE - Connected to {PORT} @ {BAUD}")

    def auto_stop_save(self):
        if self.is_saving:
            self.btn_save.setChecked(False)
            self.toggle_save()
            self.log("Stream ended (Auto-Stop 1000s)")

    def toggle_save(self):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.is_paused:
            self.btn_save.setChecked(False)
            filename = os.path.join(CAPTURES_DIR, f"ppg_data_snap_{now_str}.csv")
            try:
                with open(filename, "w") as f:
                    f.write("FrameMode,ESP32_Sample_Cnt,ESP32_Timestamp_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_led2[i]},{self.data_led1[i]},{self.data_aled2[i]},{self.data_aled1[i]},{self.data_led2_sub[i]},{self.data_led1_sub[i]},{self.data_ppgdisp[i]},{self.data_spo2[i]},{self.data_spo2_sqi[i]},{self.data_spo2_r[i]},{self.data_pi[i]},{self.data_hr1[i]},{self.data_hr1_sqi[i]},{self.data_hr2[i]},{self.data_hr2_sqi[i]},{self.data_hr3[i]},{self.data_hr3_sqi[i]}\n")
                self.log(f"Snapshot saved to {filename}")
            except Exception as e:
                self.log(f"Error saving snapshot: {e}")
        else:
            self.is_saving = self.btn_save.isChecked()
            if self.is_saving:
                self.btn_save.setText("STOP\nRECORDING")
                filename = os.path.join(CAPTURES_DIR, f"ppg_data_stream_{now_str}.csv")
                try:
                    self.save_file = open(filename, "w")
                    if self.frame_mode == "M1":
                        self.save_file.write("Timestamp_PC,Diff_us_PC,FrameMode,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG_DISP\n")
                    elif self.frame_mode in ("M1", "M2"):
                        self.save_file.write("Timestamp_PC,Diff_us_PC,FrameMode,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG_DISP,SpO2,SpO2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState\n")
                    elif self.frame_mode == "M4":
                        self.save_file.write("Timestamp_PC,Diff_us_PC,FrameMode,ESP32_Sample_Cnt,ESP32_Timestamp_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState,V_TIA_LED1,V_TIA_LED2,V_TIA_ALED1,V_TIA_ALED2,I_PD_LED1,I_PD_LED2,I_PD_ALED1,I_PD_ALED2\n")
                    else:  # M3 (default)
                        self.save_file.write("Timestamp_PC,Diff_us_PC,FrameMode,ESP32_Sample_Cnt,ESP32_Timestamp_us,LED2,LED1,ALED2,ALED1,LED2_SUB,LED1_SUB,PPG_DISP,SpO2,SpO2_SQI,R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState\n")
                    self.log(f"RECORDING LIVE: {filename}")
                    self.auto_save_timer.start(1000 * 1000)
                except Exception as e:
                    self.log(f"Error opening save file: {e}")
                    self.is_saving = False
                    self.btn_save.setChecked(False)
            else:
                self.auto_save_timer.stop()
                self.btn_save.setText("SAVE DATA")
                if self.save_file:
                    self.save_file.close()
                    self.save_file = None
                self.log(f"System ONLINE - Connected to {PORT} @ {BAUD}")

    def _save_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PPGMonitor/geometry",       self.saveGeometry())
        s.setValue("PPGMonitor/right_splitter", self.right_splitter.saveState())
        s.setValue("PPGMonitor/spin_decim",          self.spin_decim.value())
        s.setValue("PPGMonitor/spin_stats_interval", self.spin_stats_interval.value())
        s.setValue("PPGMonitor/combo_port",      self.combo_port.currentText())
        s.setValue("PPGMonitor/serial_connected", self.ser is not None and self.ser.is_open)
        s.setValue("PPGMonitor/udp_connected",    self._udp_thread is not None and self._udp_thread.is_alive())
        s.setValue("PPGMonitor/ppgplots_open",  self.ppgplots_window  is not None)
        s.setValue("PPGMonitor/signals_open",   self.signals_window   is not None)
        s.setValue("PPGMonitor/results_open",   self.results_window   is not None)
        s.setValue("PPGMonitor/serialcom_open", self.serialcom_window is not None)
        s.setValue("PPGMonitor/hrlab_open",     self.hrlab_window     is not None)
        s.setValue("PPGMonitor/spo2lab_open",   self.spo2lab_window   is not None)
        s.setValue("PPGMonitor/hr3lab_open",    self.hr3lab_window    is not None)
        s.setValue("PPGMonitor/spo2test_open",  self.spo2test_window  is not None)
        s.setValue("PPGMonitor/hr1test_open",  self.hr1test_window  is not None)
        s.setValue("PPGMonitor/hr2test_open",  self.hr2test_window  is not None)
        s.setValue("PPGMonitor/hr3test_open",  self.hr3test_window  is not None)
        s.setValue("PPGMonitor/pilab_open",    self.pilab_window    is not None)
        s.setValue("PPGMonitor/esp32_timing_open",   self.esp32_timing_window   is not None)
        s.setValue("PPGMonitor/python_timing_open",  self.python_timing_window  is not None)
        s.setValue("PPGMonitor/hw_config_open",   self.hw_config_window   is not None)
        s.setValue("PPGMonitor/diagnostics_open", self.diag_window         is not None)
        s.setValue("PPGMonitor/afe_sweep_open",    self.afe_sweep_window     is not None)
        s.setValue("PPGMonitor/labcapture_open",  self.lab_capture_window is not None)
        # Persist geometry of all open subwindows (survives taskkill; also saved in their closeEvent)
        if self.ppgplots_window  is not None: s.setValue("PPGPlotsWindow/geometry",    self.ppgplots_window.saveGeometry())
        if self.signals_window   is not None: s.setValue("PPGSignalsWindow/geometry",  self.signals_window.saveGeometry())
        if self.results_window   is not None: s.setValue("AlgoResultsWindow/geometry", self.results_window.saveGeometry())
        if self.serialcom_window is not None: s.setValue("SerialComWindow/geometry",   self.serialcom_window.saveGeometry())
        if self.udpcom_window    is not None: s.setValue("UdpComWindow/geometry",     self.udpcom_window.saveGeometry())
        if self.hrlab_window     is not None: s.setValue("HRLabWindow/geometry",      self.hrlab_window.saveGeometry())
        if self.spo2lab_window   is not None: s.setValue("SpO2LabWindow/geometry",    self.spo2lab_window.saveGeometry())
        if self.hr3lab_window    is not None: s.setValue("HR3LabWindow/geometry",     self.hr3lab_window.saveGeometry())
        if self.spo2test_window  is not None: s.setValue("SpO2TestWindow/geometry",   self.spo2test_window.saveGeometry())
        if self.hr1test_window   is not None: s.setValue("HR1TestWindow/geometry",    self.hr1test_window.saveGeometry())
        if self.hr2test_window   is not None: s.setValue("HR2TestWindow/geometry",    self.hr2test_window.saveGeometry())
        if self.hr3test_window   is not None: s.setValue("HR3TestWindow/geometry",    self.hr3test_window.saveGeometry())
        if self.esp32_timing_window  is not None: s.setValue("Esp32TimingWindow/geometry",   self.esp32_timing_window.saveGeometry())
        if self.python_timing_window is not None: s.setValue("PythonTimingWindow/geometry", self.python_timing_window.saveGeometry())
        if self.hw_config_window     is not None: s.setValue("HWConfigWindow/geometry",     self.hw_config_window.saveGeometry())
        if self.diag_window          is not None: s.setValue("DiagnosticsWindow/geometry",  self.diag_window.saveGeometry())
        if self.afe_sweep_window      is not None: s.setValue("AFESweepTestWindow/geometry",  self.afe_sweep_window.saveGeometry())
        if self.lab_capture_window   is not None: s.setValue("LabCaptureWindow/geometry",   self.lab_capture_window.saveGeometry())

    def _restore_settings(self):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        geom = s.value("PPGMonitor/geometry")
        if geom:
            self.restoreGeometry(geom)
        splitter = s.value("PPGMonitor/right_splitter")
        if splitter:
            self.right_splitter.restoreState(splitter)
        self.spin_decim.setValue(         s.value("PPGMonitor/spin_decim",          10,  type=int))
        self.spin_stats_interval.setValue(s.value("PPGMonitor/spin_stats_interval", 1,   type=int))
        encoded = s.value("PPGMonitor/stats_highlighted", "", type=str)
        self._stats_highlighted.clear()
        if encoded:
            for token in encoded.split(";"):
                parts = token.split(",")
                if len(parts) == 2:
                    try:
                        self._stats_highlighted.add((int(parts[0]), int(parts[1])))
                    except ValueError:
                        pass
        port = s.value("PPGMonitor/combo_port", PORT)
        idx = self.combo_port.findText(port)
        if idx >= 0:
            self.combo_port.setCurrentIndex(idx)
        _ssid = s.value("PPGMonitor/last_wifi_ssid", "", type=str)
        if _ssid:
            self._lbl_wifi.setText(f"WiFi: {_ssid} (last)")
            self._lbl_wifi.setStyleSheet("color: #667788; font-size: 14px; padding: 0px 2px;")
        # Defer connections to after the event loop starts so the window
        # appears immediately — serial.Serial() can block on some ports.
        self._restore_serial_on_start = s.value("PPGMonitor/serial_connected", True, type=bool)
        self._restore_udp_on_start    = s.value("PPGMonitor/udp_connected",    False, type=bool)

    def _populate_ports(self):
        current = self.combo_port.currentText()
        self.combo_port.blockSignals(True)
        self.combo_port.clear()
        ports = sorted(p.device for p in list_ports.comports())
        self.combo_port.addItems(ports)
        idx = self.combo_port.findText(current)
        # If saved port is not in the current list, leave combo unselected (-1)
        # so the startup auto-connect does not silently use the wrong port.
        self.combo_port.setCurrentIndex(idx)
        self.combo_port.blockSignals(False)

    def _toggle_serial(self):
        if self.ser is not None and self.ser.is_open:
            self._disconnect_serial()
        else:
            self._connect_serial(self.combo_port.currentText())

    def _disconnect_serial(self):
        self._reader_stop.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        self.ser = None
        while not self._serial_queue.empty():
            try: self._serial_queue.get_nowait()
            except: break
        self.log("Serial disconnected")
        self.btn_serial.setText("SERIAL  ●  OFF")
        self.btn_serial.setStyleSheet(
            "background-color: #1E1E1E; color: #666666; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #444444; border-radius: 4px;")

    def _connect_serial(self, port: str):
        if not port:
            self.log("No port selected")
            return
        if self._serial_connecting:
            self.log("Serial: connection already in progress")
            return
        # Stop existing reader thread
        self._reader_stop.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        self.ser = None
        # Drain queue
        while not self._serial_queue.empty():
            try: self._serial_queue.get_nowait()
            except: break
        self._reader_stop.clear()
        self._serial_connecting = True
        self.log(f"Connecting to {port}...")
        self.btn_serial.setText(f"SERIAL  ●  ...  ({port})")
        self.btn_serial.setStyleSheet(
            "background-color: #1A1A1A; color: #AAAAAA; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #888888; border-radius: 4px;")

        def _open_port():
            try:
                ser = serial.Serial(port, BAUD, timeout=0.1)
                ser.set_buffer_size(rx_size=65536)
                self._sig_serial_result.emit(True, port, "", ser)
            except Exception as e:
                self._sig_serial_result.emit(False, port, str(e), None)

        threading.Thread(target=_open_port, daemon=True).start()

    def _on_serial_result(self, success: bool, port: str, error: str, ser):
        """Slot called from _sig_serial_result — runs on the main thread."""
        self._serial_connecting = False
        if success:
            self.ser = ser
            self._reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self._reader_thread.start()
            self.log(f"System ONLINE — {port} @ {BAUD}")
            self.btn_serial.setText(f"SERIAL  ●  ON  ({port})")
            self.btn_serial.setStyleSheet(
                "background-color: #1A3A1A; color: #44FF44; font-size: 17px; "
                "font-weight: bold; padding: 5px; border: 1px solid #44FF44; border-radius: 4px;")
            QtCore.QTimer.singleShot(2500, lambda: self.request_chip_config(notify_lab_capture=False))
        else:
            self.ser = None
            self.log(f"ERROR: Could not open {port} — {error}")
            self.btn_serial.setText("SERIAL  ●  OFF")
            self.btn_serial.setStyleSheet(
                "background-color: #3A1A1A; color: #FF4444; font-size: 17px; "
                "font-weight: bold; padding: 5px; border: 1px solid #FF4444; border-radius: 4px;")

    def _on_udp_active(self):
        """Slot called on main thread when first UDP datagram arrives.
        Switches active transport to UDP so serial frames stop feeding the pipeline."""
        self._active_transport = "udp"
        self.log(f"Data source: UDP WiFi (:{self._udp_port})")
        self.btn_udp.setText(f"UDP WiFi  ●  ON  (:{self._udp_port})")
        self.btn_udp.setStyleSheet(
            "background-color: #1A1E3A; color: #44AAFF; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #44AAFF; border-radius: 4px;")

    def _toggle_udp(self):
        if self._udp_thread is not None and self._udp_thread.is_alive():
            self._disconnect_udp()
        else:
            self._connect_udp()

    def _disconnect_udp(self):
        self._udp_stop.set()
        if self._udp_thread is not None:
            self._udp_thread.join(timeout=1.0)
        self._udp_thread = None
        while not self._udp_queue.empty():
            try: self._udp_queue.get_nowait()
            except: break
        self._esp32_ip = None
        if self._cmd_udp_sock is not None:
            self._cmd_udp_sock.close()
            self._cmd_udp_sock = None
        self._active_transport = "serial"
        self.log("UDP disconnected — data source: SERIAL")
        self.btn_udp.setText("UDP WiFi  ●  OFF")
        self.btn_udp.setStyleSheet(
            "background-color: #1E1E1E; color: #666666; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #444444; border-radius: 4px;")

    def _connect_udp(self):
        """Start UDP reader thread (runs in parallel with _serial_reader).
        Serial port stays open so command responses ($CFG, $DIAG, etc.) keep working."""
        # Stop any previous UDP reader
        self._udp_stop.set()
        if self._udp_thread is not None:
            self._udp_thread.join(timeout=1.0)
        # Drain only the UDP queue
        while not self._udp_queue.empty():
            try: self._udp_queue.get_nowait()
            except: break
        self._udp_stop.clear()
        self._gaps_B   = 0
        self._udp_port = UDP_DEFAULT_PORT
        self._udp_thread = threading.Thread(target=self._udp_reader, daemon=True)
        self._udp_thread.start()
        # Transport switches to "udp" only after first datagram arrives (_on_udp_active).
        # Serial stays active until then so data is never lost while WiFi connects.
        self.log(f"UDP listening on port {self._udp_port} — data source stays SERIAL until first datagram")
        self.btn_udp.setText(f"UDP WiFi  ●  LISTEN  (:{self._udp_port})")
        self.btn_udp.setStyleSheet(
            "background-color: #1A1E3A; color: #AAAAFF; font-size: 17px; "
            "font-weight: bold; padding: 5px; border: 1px solid #8888CC; border-radius: 4px;")

    def _udp_reader(self):
        """Dedicated thread: receives UDP datagrams into _udp_queue.
        Each datagram contains UDP_BATCH_SIZE M1/M2 frames (one per line).
        Frames are unpacked line-by-line and queued individually — the pipeline
        downstream is identical to the serial path.
        Gap detection (Punto B): checked per-frame when unpacking."""
        import socket as _socket
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_RCVBUF, 1024 * 1024)  # 1 MB RX buffer
        sock.bind(('', self._udp_port))
        sock.settimeout(0.5)
        _last_cnt = None
        _known_ip = None
        while not self._udp_stop.is_set():
            try:
                data, _addr = sock.recvfrom(4096)   # up to UDP_BATCH_SIZE frames per datagram (~1150 bytes for 5×$M4)
                _src_ip = _addr[0]
                if _known_ip is None:
                    _known_ip = _src_ip
                    self._esp32_ip = _src_ip
                    self._sig_log.emit(f"[UDP] First datagram from {_src_ip}")
                    self._sig_udp_active.emit()   # switch transport on main thread
                elif _src_ip != _known_ip:
                    self._sig_log.emit(f"[UDP] Source IP changed: {_known_ip} → {_src_ip}")
                    _known_ip = _src_ip
                    self._esp32_ip = _src_ip
                if not data:
                    continue
                for line in data.split(b'\n'):
                    line = line.rstrip(b'\r')
                    if not line:
                        continue
                    if line.startswith(b'$M1,') or line.startswith(b'$M2,') or line.startswith(b'$M3,') or line.startswith(b'$M4,'):
                        try:
                            _cnt = int(line[1:].split(b',')[1])
                            if _last_cnt is not None:
                                _gap = _cnt - _last_cnt - 1
                                if 0 < _gap <= 5000:
                                    self._gaps_B += _gap
                                    self._sig_log.emit(
                                        f"[GAP B/UDP] {_gap} samples lost (cnt {_last_cnt}\u2192{_cnt})")
                            _last_cnt = _cnt
                        except (ValueError, IndexError):
                            pass
                    self._udp_queue.put(line + b'\r\n')
            except _socket.timeout:
                continue
            except Exception:
                break
        sock.close()

    def _serial_reader(self):
        """Dedicated thread: reads serial lines at full rate into a queue.
        Completely decoupled from the UI so no frames are lost during rendering.
        Gap detection (Punto B): checks sample counter on every raw M1/M2 frame."""
        _last_cnt = None
        while not self._reader_stop.is_set() and self.ser is not None:
            try:
                line = self.ser.readline()
                if line:
                    if line.startswith(b'$M1,') or line.startswith(b'$M2,'):
                        try:
                            _cnt = int(line[1:].split(b',')[1])
                            if _last_cnt is not None:
                                _gap = _cnt - _last_cnt - 1
                                if 0 < _gap <= 5000:  # >5000 (10 s) → corrupted frame, discard
                                    self._gaps_B += _gap
                                    # self._sig_log.emit(f"[GAP B/SERIAL] {_gap} samples lost (cnt {_last_cnt}\u2192{_cnt})")
                            _last_cnt = _cnt
                        except (ValueError, IndexError):
                            pass
                    self._serial_queue.put(line)
            except Exception:
                break

    _STATS_HR_ROWS       = {11, 13, 15}   # HR1, HR2, HR3
    _STATS_SUB_ROWS      = {4, 5}         # LED1_SUB, LED2_SUB
    _STATS_RAW_ROWS      = {0, 1, 2, 3}  # LED1 (IR), LED2 (RED), ALED1, ALED2 — show V_TIA / V_ADC
    _STATS_MEAN_COL      = 4
    _STATS_MAROON        = QtGui.QColor("#5C001A")
    _STATS_GREEN         = QtGui.QColor("#1A5C1A")
    _STATS_SQI_THRESHOLD = 0.9
    # ProbeState column-0 background colors
    _PROBE_APPLIED_BG       = QtGui.QColor("#00A000")  # green  — APPLIED (2)
    _PROBE_NOT_APPLIED_BG   = QtGui.QColor("#7A6400")  # amber  — NOT_APPLIED (1)
    _PROBE_DISCONNECTED_BG  = QtGui.QColor("#7A0000")  # red    — DISCONNECTED (0)
    # V_TIA / V_ADC cell background colors
    _VTG_GREEN   = QtGui.QColor("#0F3A0F")  # optimal
    _VTG_YELLOW  = QtGui.QColor("#3A2D00")  # caution
    _VTG_RED     = QtGui.QColor("#4A0800")  # saturation / insufficient
    _VTG_DEFAULT = QtGui.QColor("#121212")  # no data
    _ADC_FSR             = 1.2            # V — AFE4490 ADC full-scale voltage (±1.2 V)
    _ADC_FS_COUNTS       = 2 ** 21 - 1    # 22-bit signed: positive full-scale code (datasheet Table 7)
    def _on_stats_cell_clicked(self, row, col):
        key = (row, col)
        if key in self._stats_highlighted:
            self._stats_highlighted.discard(key)
        else:
            self._stats_highlighted.add(key)
        self.stats_table.viewport().update()
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        encoded = ";".join(f"{r},{c}" for r, c in sorted(self._stats_highlighted))
        s.setValue("PPGMonitor/stats_highlighted", encoded)

    def _vtg_tia_color(self, row, v_tia):
        """Background color for V_TIA cell. Uses abs(v_tia) for comparison."""
        v = abs(v_tia)
        if row in {0, 1}:   # LED phase
            if v > 0.95 or v < 0.15:           return self._VTG_RED
            if v >= 0.80 or v < 0.40:          return self._VTG_YELLOW
            return self._VTG_GREEN              # 0.40 – 0.80 V optimal
        else:               # ALED phase
            if v > 0.70:                        return self._VTG_RED
            if v >= 0.30:                       return self._VTG_YELLOW
            return self._VTG_GREEN              # < 0.30 V safe

    def _vtg_adc_color(self, row, v_adc):
        """Background color for V_ADC cell. Uses abs(v_adc) for comparison."""
        v = abs(v_adc)
        if row in {0, 1}:   # LED phase
            if v > 1.10 or v < 0.20:           return self._VTG_RED
            if v >= 0.95 or v < 0.45:          return self._VTG_YELLOW
            return self._VTG_GREEN              # 0.45 – 0.95 V ideal
        else:               # ALED phase
            if v > 0.80:                        return self._VTG_RED
            if v >= 0.35:                       return self._VTG_YELLOW
            return self._VTG_GREEN              # < 0.35 V safe

    def _copy_stats_selection(self):
        selected = self.stats_table.selectedIndexes()
        if not selected:
            return
        rows = sorted({idx.row() for idx in selected})
        cols = sorted({idx.column() for idx in selected})
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                item = self.stats_table.item(r, c)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _update_stats_table(self):
        _led1_sub_cv  = None
        _led2_sub_cv = None
        for sig_idx, (name, _, _tooltip, _src) in enumerate(self._STATS_SIGNALS):
            tbl_row = sig_idx if sig_idx < 4 else sig_idx + 1
            buf = self._stats_buf[name]
            if buf:
                n    = len(buf)
                mean = sum(buf) / n
                lo   = min(buf)
                hi   = max(buf)
                std  = math.sqrt(sum((v - mean) ** 2 for v in buf) / n)
                if sig_idx < 6:  # raw ADC signals: integer, thousands-separated with narrow space
                    def _fmt(v): return f"{v:,.0f}".replace(",", "\u202f")
                elif sig_idx in {20, 21, 22, 23}:  # V_TIA_*: volts, 6 decimal places
                    def _fmt(v): return f"{v:.6f}"
                elif sig_idx in {24, 25, 26, 27}:  # I_PD_*: display in µA (×1e6), 3 decimal places
                    def _fmt(v): return f"{v * 1e6:.3f}"
                elif sig_idx in {28, 29}:  # OT_LED1/OT_LED2: 6 decimal places
                    def _fmt(v): return f"{v:.6f}"
                else:
                    def _fmt(v): return f"{v:.2f}"
                snr_str = f"{std / mean * 100:.2f}" if (sig_idx in self._STATS_SUB_ROWS and mean != 0) else (
                    "" if sig_idx not in self._STATS_SUB_ROWS else "---")
                if sig_idx == 4 and mean != 0:    # LED1_SUB: save CV for R ratio
                    _led1_sub_cv  = std / mean * 100
                elif sig_idx == 5 and mean != 0:  # LED2_SUB: save CV for R ratio
                    _led2_sub_cv = std / mean * 100
                if sig_idx == 18:  # DiagCode: integer everywhere except SD (bitmask, not continuous)
                    vals = [f"{mean:.0f}", f"{std:.2f}", f"{hi - lo:.0f}", f"{lo:.0f}", f"{hi:.0f}"]
                else:
                    vals = [_fmt(mean), _fmt(std), _fmt(hi - lo), _fmt(lo), _fmt(hi)]
            else:
                snr_str = "" if sig_idx not in self._STATS_SUB_ROWS else "---"
                vals = ["---", "---", "---", "---", "---"]
            # R row: show LED2_SUB_CV / LED1_SUB_CV ≈ R  (italic — derived ratio, not true % SD/Mean)
            if sig_idx == 9:
                snr_str = f"{_led2_sub_cv / _led1_sub_cv:.4f}" if (_led1_sub_cv and _led2_sub_cv) else "---"
            # col 3: % SD/Mean (LED1_SUB / LED2_SUB rows) or R estimate (R row)
            snr_item = self.stats_table.item(tbl_row, 3)
            if snr_item is None:
                snr_item = QtWidgets.QTableWidgetItem(snr_str)
                snr_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.stats_table.setItem(tbl_row, 3, snr_item)
            else:
                snr_item.setText(snr_str)
            if sig_idx == 9:
                _f = snr_item.font()
                _f.setItalic(True)
                snr_item.setFont(_f)
            # cols 4-8: Mean, SD, Max-Min, Min, Max
            for col, v in enumerate(vals, start=4):
                item = self.stats_table.item(tbl_row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(v)
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    if sig_idx in self._STATS_HR_ROWS and col == self._STATS_MEAN_COL:
                        item.setBackground(self._STATS_MAROON)
                    self.stats_table.setItem(tbl_row, col, item)
                else:
                    item.setText(v)
                if sig_idx in self._STATS_HR_ROWS and col == self._STATS_MEAN_COL:
                    sqi_buf = self._stats_buf.get(name + "_SQI", [])
                    sqi_mean = sum(sqi_buf) / len(sqi_buf) if sqi_buf else 0.0
                    bg = self._STATS_GREEN if sqi_mean > self._STATS_SQI_THRESHOLD else self._STATS_MAROON
                    item.setBackground(bg)
            # cols 1-2: V_TIA, V_ADC — only for LED1 (IR), LED2 (RED), ALED1, ALED2 (signal rows 0-3)
            if sig_idx in self._STATS_RAW_ROWS and buf:
                is_led1   = sig_idx in {0, 2}   # LED1 (IR) / ALED1 → stg21, tia1; LED2 (RED) / ALED2 → stg22, tia2
                rg_ohm    = float(self._last_cfg.get("rg1_ohm" if is_led1 else "rg2_ohm", 100e3))
                ri_ohm    = float(self._last_cfg.get("ri_ohm", 100e3))
                i_cancel  = float(self._last_cfg.get("ambdac", "0")) * 1e-6  # µA → A
                v_adc     = mean / self._ADC_FS_COUNTS * self._ADC_FSR
                # Eq.2 datasheet p.30: V_DIFF = 2×(I_PD×RF/RI − I_CANCEL)×RG
                # → V_TIA = I_PD×RF = (V_ADC/(2×RG) + I_CANCEL) × RI
                v_tia     = (v_adc / (2 * rg_ohm) + i_cancel) * ri_ohm
                vtia_str  = f"{v_tia:.3f} V"
                vadc_str  = f"{v_adc:.3f} V"
            else:
                vtia_str = "" if sig_idx not in self._STATS_RAW_ROWS else "---"
                vadc_str = vtia_str
            if sig_idx in self._STATS_RAW_ROWS and buf:
                vtia_bg = self._vtg_tia_color(sig_idx, v_tia)
                vadc_bg = self._vtg_adc_color(sig_idx, v_adc)
            else:
                vtia_bg = vadc_bg = self._VTG_DEFAULT
            for col, txt, bg in ((1, vtia_str, vtia_bg), (2, vadc_str, vadc_bg)):
                it = self.stats_table.item(tbl_row, col)
                if it is None:
                    it = QtWidgets.QTableWidgetItem(txt)
                    it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    self.stats_table.setItem(tbl_row, col, it)
                else:
                    it.setText(txt)
                it.setBackground(bg)
            self._stats_buf[name].clear()

    def _process_frames_tick(self):
        """Drain serial and UDP queues and run per-sample algorithms.
        Timing budget: PythonTimingWindow._SERIAL_TICK_BUDGET_MS.
        Algorithm rows: PythonTimingWindow._SERIAL_TICK_ROWS."""
        _t0_drain = time.perf_counter()
        if self._last_drain_t is not None:
            self._py_timing['drain_interval'].append((_t0_drain - self._last_drain_t) * 1000)
        self._last_drain_t = _t0_drain
        self._queue_size_buf.append(self._serial_queue.qsize())  # Punto A
        try:
            _new_data = False
            for _q, _src_com_win in (
                    (self._serial_queue, self.serialcom_window),
                    (self._udp_queue,    self.udpcom_window)):
                _is_active = (
                    (_q is self._serial_queue and self._active_transport == "serial") or
                    (_q is self._udp_queue    and self._active_transport == "udp"))
                _console_lines = []
                while True:
                    try:
                        line_raw = _q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        line = line_raw.decode('utf-8', errors='ignore').strip()
                    except: continue
                    if not line: continue

                    # Confirmation messages from ESP32 (e.g. "# Switched to incunest_afe4490")
                    if line.startswith('#'):
                        if _src_com_win is not None:
                            _src_com_win.append_line(line)
                        if 'incunest' in line.lower() and 'frame' not in line.lower() and _is_active:
                            self.frame_mode = "M4"
                            self._update_frame_button()
                            import re as _re
                            _vm = _re.search(r'incunest_afe4490\s+(v\S+)', line)
                            if _vm:
                                self.log(f"Active library: incunest_afe4490 {_vm.group(1)}")
                                _tsm = _re.search(r'build:\s*([^|]+)', line)
                                if _tsm:
                                    self.log(f"Build: {_tsm.group(1).strip()}")
                                _bm = _re.search(r'Board:\s*(\S+)', line)
                                if _bm:
                                    self.log(f"Board: {_bm.group(1)}")
                            # "# incunest_afe4490 started" → Cmd_Task is running → send $CFG? + $MODE
                            if 'started' in line.lower():
                                self._post_reset_cfg_pending = False
                                QtCore.QTimer.singleShot(300, lambda: self.request_chip_config(notify_lab_capture=False))
                                # Restore saved frame mode (ESP32 always boots in M3)
                                _fm = self.frame_mode
                                QtCore.QTimer.singleShot(500,
                                    lambda fm=_fm: self._send_frame_cmd(fm))
                        elif 'frame mode' in line.lower():
                            if _is_active:
                                _fm_txt = line.lstrip('# ').strip()
                                self.log(f"[FRAME] ✓ {_fm_txt}")
                        elif line.startswith('# SYS:'):
                            self.log(line[6:].strip())
                        elif line.startswith('# WiFi') or line.startswith('#   ['):
                            self.log(line[2:].strip())
                            # Persist last working SSID to ini ("# WiFi connected [SSID] —...")
                            import re as _re
                            _m = _re.match(r'# WiFi connected \[([^\]]+)\]', line)
                            if _m:
                                _ssid = _m.group(1)
                                QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue(
                                    "PPGMonitor/last_wifi_ssid", _ssid)
                                self._lbl_wifi.setText(f"WiFi: {_ssid}")
                                self._lbl_wifi.setStyleSheet("color: #44AAFF; font-size: 14px; padding: 0px 2px;")
                        continue

                    current_time_perf = time.perf_counter()
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")
                    diff_us = int((current_time_perf - self.last_time) * 1e6) if self.last_time is not None else 0
                    self.last_time = current_time_perf

                    if not line.startswith('$'):
                        continue

                    # Verify and strip NMEA-style XOR checksum (*XX) if present.
                    # $M1/$M2 data frames always carry *XX; reject them if missing or malformed.
                    chk_ok = 1
                    is_data_frame = line.startswith('$M1,') or line.startswith('$M2,') or line.startswith('$M3,') or line.startswith('$M4,')
                    if '*' in line:
                        star_pos = line.rfind('*')
                        chk_field = line[star_pos + 1:]
                        if len(chk_field) == 2:
                            try:
                                expected_chk = int(chk_field, 16)
                                computed_chk = 0
                                for c in line[1:star_pos]:
                                    computed_chk ^= ord(c)
                                if computed_chk != expected_chk:
                                    chk_ok = 0
                                    if _src_com_win is not None:
                                        _src_com_win.append_line(
                                            f"# BAD CHK (got {computed_chk:02X} exp {expected_chk:02X}): {line[:70]}")
                            except ValueError:
                                pass
                        else:
                            # *XX field present but not exactly 2 hex chars — malformed
                            if is_data_frame:
                                chk_ok = 0
                                if _src_com_win is not None:
                                    _src_com_win.append_line(
                                        f"# BAD CHK (malformed *field): {line[:70]}")
                        if self.save_file_chk is not None:
                            self.save_file_chk.write(f"{timestamp},{diff_us:>5},{chk_ok},{line}\n")
                        line = line[:star_pos]  # strip *XX for field parsing and CSV
                        if not chk_ok:
                            continue
                    else:
                        # No *XX field — reject data frames, pass through others ($ERR, comments)
                        if is_data_frame:
                            if _src_com_win is not None:
                                _src_com_win.append_line(
                                    f"# BAD CHK (no checksum field): {line[:70]}")
                            if self.save_file_chk is not None:
                                self.save_file_chk.write(f"{timestamp},{diff_us:>5},0,{line}\n")
                            continue
                        if self.save_file_chk is not None:
                            self.save_file_chk.write(f"{timestamp},{diff_us:>5},{chk_ok},{line}\n")

                    csv_line = f"{timestamp},{diff_us:>5},{line}"

                    # Lab Capture: full rate (500 Hz), before decimation
                    if _is_active and self.is_lab_capturing and self._lab_capture_file:
                        self._write_lab_capture_row(line)

                    # HR1TEST mirror: 500 Hz (before decimation) — must match firmware _update_hr1()
                    if _is_active and self.hr1test_window is not None:
                        _p500 = line[1:].split(',')
                        if len(_p500) >= 9 and _p500[0] == 'M1':
                            try:
                                self.hr1test_calc.update(float(_p500[8]), 500.0, int(_p500[1]))
                            except (ValueError, IndexError):
                                pass

                    # TIMING diagnostic frame: handle before decimation, not counted as data
                    # Format: $TIMING,hr1_mean,hr1_max,hr2fp_mean,hr2fp_max,hr3fp_mean,hr3fp_max,
                    #                 spo2_mean,spo2_max,cycle_mean,cycle_max,
                    #                 hr2cmp_mean,hr2cmp_max,hr3cmp_mean,hr3cmp_max,stack_free*XX
                    if line.startswith('$TIMING,'):
                        _console_lines.append(csv_line)
                        self._pending_tasks = []  # reset task accumulator for new cycle
                        if self.esp32_timing_window is not None:
                            _tp = line[1:].split('*')[0].split(',')
                            if len(_tp) >= 16:
                                try:
                                    vals = [int(x) for x in _tp[1:16]]
                                    self.esp32_timing_window.esp32_update_timing(*vals)
                                except (ValueError, IndexError):
                                    pass
                        continue

                    # $TASK frame: one per FreeRTOS task, emitted after $TIMING
                    # Format: $TASK,name,cpu_pct_x10,stack_words*XX
                    if line.startswith('$TASK,'):
                        _tp = line[1:].split('*')[0].split(',')
                        if len(_tp) >= 4:
                            try:
                                name      = _tp[1]
                                pct_x10   = int(_tp[2])
                                stack     = int(_tp[3])
                                self._pending_tasks.append((name, pct_x10, stack))
                            except (ValueError, IndexError):
                                pass
                        continue

                    # $TASKS_END: all $TASK frames for this cycle have been received
                    if line.startswith('$TASKS_END'):
                        if self.esp32_timing_window is not None:
                            self.esp32_timing_window.esp32_update_tasks(self._pending_tasks)
                        continue

                    # $CFG: chip configuration response (reply to $CFG? or $SET command)
                    if line.startswith('$CFG,'):
                        self._on_cfg_frame_received(line)
                        continue

                    # $TCFG: raw timing register values (reply to $CFG? or $SET t1..t28)
                    if line.startswith('$TCFG,'):
                        self._on_tcfg_frame_received(line)
                        continue

                    # $DIAG: hardware diagnostic result (reply to $DIAG?)
                    if line.startswith('$DIAG,'):
                        self._on_diag_frame_received(line)
                        continue

                    # $ERR: firmware rejected a $SET command
                    if line.startswith('$ERR,'):
                        self.log(f"⚠ FIRMWARE ERROR: {line}")
                        if self.hw_config_window is not None:
                            self.hw_config_window._statusbar.showMessage(f"Error: {line}")
                        continue

                    # Only feed data pipeline from the active transport
                    if not _is_active:
                        continue

                    # Decimation: skip N-1 out of every N data frames for console + plots
                    self._decim_counter += 1
                    if self._decim_counter % self.spin_decim.value() != 0:
                        continue

                    # Decimated file save: only kept frames
                    if self.is_saving and self.save_file:
                        self.save_file.write(csv_line + "\n")
                        self.save_file.flush()

                    _console_lines.append(csv_line)

                    parts = line[1:].split('*')[0].split(',')  # strip leading '$' and trailing checksum
                    lib_id = parts[0] if parts else ""
                    if lib_id in ("M3", "M4") and len(parts) >= 23:
                        try:
                            # $M3/$M4: 0:FrameMode, 1:SmpCnt, 2:Ts_us, 3:LED2, 4:LED1, 5:ALED2, 6:ALED1,
                            # 7:LED2_SUB, 8:LED1_SUB, 9:PPG_DISP, 10:SpO2, 11:SpO2_SQI, 12:R, 13:PI,
                            # 14:HR1, 15:HR1_SQI, 16:HR2, 17:HR2_SQI, 18:HR3, 19:HR3_SQI,
                            # 20:RSQI, 21:DiagCode, 22:ProbeState
                            # $M4 additionally: 23:V_TIA_LED1, 24:V_TIA_LED2, 25:V_TIA_ALED1, 26:V_TIA_ALED2,
                            #                   27:I_PD_LED1,  28:I_PD_LED2,  29:I_PD_ALED1,  30:I_PD_ALED2
                            self.data_lib_id.append(lib_id)
                            p = [float(x) for x in parts[1:20]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_led2.append(p[2])
                            self.data_led1.append(p[3])
                            self.data_aled2.append(p[4])
                            self.data_aled1.append(p[5])
                            self.data_led2_sub.append(p[6])
                            self.data_led1_sub.append(p[7])
                            self.data_ppgdisp.append(p[8])
                            self.data_spo2.append(p[9])
                            self.data_spo2_sqi.append(p[10])
                            self.data_spo2_r.append(p[11])
                            self.data_pi.append(p[12])
                            self.data_hr1.append(p[13])
                            self.data_hr1_sqi.append(p[14])
                            self.data_hr2.append(p[15])
                            self.data_hr2_sqi.append(p[16])
                            self.data_hr3.append(p[17])
                            self.data_hr3_sqi.append(p[18])
                            self.data_rsqi.append(int(float(parts[20])))
                            self.data_diag_code.append(int(float(parts[21])))
                            self.data_probe_state.append(int(float(parts[22])))
                            cfg = self._last_cfg
                            if lib_id == "M4" and len(parts) >= 31:
                                self.data_v_tia_led1.append(float(parts[23]))
                                self.data_v_tia_led2.append(float(parts[24]))
                                self.data_v_tia_aled1.append(float(parts[25]))
                                self.data_v_tia_aled2.append(float(parts[26]))
                                _ipd1  = float(parts[27]); _ipd2  = float(parts[28])
                                _iamb1 = float(parts[29]); _iamb2 = float(parts[30])
                                self.data_i_pd_led1.append(_ipd1)
                                self.data_i_pd_led2.append(_ipd2)
                                self.data_i_pd_aled1.append(_iamb1)
                                self.data_i_pd_aled2.append(_iamb2)
                                _led1_a = float(cfg.get("led1", "0")) * 1e-3
                                _led2_a = float(cfg.get("led2", "0")) * 1e-3
                                self.data_ot2_led1.append((_ipd1 - _iamb1) / _led1_a if _led1_a != 0 else 0.0)
                                self.data_ot2_led2.append((_ipd2 - _iamb2) / _led2_a if _led2_a != 0 else 0.0)
                            else:
                                self.data_v_tia_led1.append(0.0);  self.data_v_tia_led2.append(0.0)
                                self.data_v_tia_aled1.append(0.0); self.data_v_tia_aled2.append(0.0)
                                self.data_i_pd_led1.append(0.0);   self.data_i_pd_led2.append(0.0)
                                self.data_i_pd_aled1.append(0.0);  self.data_i_pd_aled2.append(0.0)
                                self.data_ot2_led1.append(0.0);    self.data_ot2_led2.append(0.0)
                            self.hr3_calc.update(p[7], SPO2_RECEIVED_FS, int(p[0]))  # LED1_SUB for HR3Lab diagnostics
                            if self.hr3test_window is not None:
                                self.hr3test_calc.update(p[7], SPO2_RECEIVED_FS, int(p[0]))
                            if self.pilab_window is not None:
                                self.pilab_window.feed_sample(
                                    p[7], p[6], SPO2_RECEIVED_FS, p[1])
                            if self.afe_sweep_window is not None:
                                _m4 = lib_id == "M4" and len(parts) >= 31
                                self.afe_sweep_window.feed_sample(
                                    p[2], p[3], p[4], p[5], p[6], p[7],
                                    self.data_rsqi[-1],
                                    self.data_diag_code[-1],
                                    self.data_probe_state[-1],
                                    v_tia_led1=parts[23] if _m4 else None,
                                    v_tia_led2=parts[24] if _m4 else None,
                                    v_tia_aled1=parts[25] if _m4 else None,
                                    v_tia_aled2=parts[26] if _m4 else None,
                                    i_pd_led1=parts[27] if _m4 else None,
                                    i_pd_led2=parts[28] if _m4 else None,
                                    i_pd_aled1=parts[29] if _m4 else None,
                                    i_pd_aled2=parts[30] if _m4 else None)
                            # Integrity check: LED2_SUB and LED1_SUB must equal hardware-subtracted values
                            led2_sub_exp = int(p[2]) - int(p[4])   # RED - ALED2
                            led1_sub_exp  = int(p[3]) - int(p[5])   # IR  - ALED1
                            led2_sub_fw  = int(p[6])
                            led1_sub_fw   = int(p[7])
                            if led2_sub_fw != led2_sub_exp or led1_sub_fw != led1_sub_exp:
                                self._sub_mismatch_count += 1
                                if self._sub_mismatch_count <= 5 or self._sub_mismatch_count % 100 == 0:
                                    self.log(
                                        f"[CHK] SUB MISMATCH #{self._sub_mismatch_count}"
                                        f" SmpCnt={int(p[0])}"
                                        f" LED2_SUB={led2_sub_fw} exp={led2_sub_exp} Δ={led2_sub_fw - led2_sub_exp}"
                                        f" LED1_SUB={led1_sub_fw} exp={led1_sub_exp} Δ={led1_sub_fw - led1_sub_exp}"
                                    )
                            # Stats buffers
                            for sname, attr, _, _src in self._STATS_SIGNALS:
                                self._stats_buf[sname].append(getattr(self, attr)[-1])
                        except ValueError: pass
                        else: _new_data = True
                    elif lib_id == "M2" and len(parts) >= 11:
                        # $M2,SmpCnt,Ts_us,PPG_DISP,SpO2,SpO2_SQI,HR3,HR3_SQI,RSQI,DiagCode,ProbeState
                        try:
                            self.data_lib_id.append(lib_id)
                            p = [float(x) for x in parts[1:11]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_ppgdisp.append(p[2])
                            self.data_spo2.append(p[3])
                            self.data_spo2_sqi.append(p[4])
                            self.data_hr3.append(p[5])
                            self.data_hr3_sqi.append(p[6])
                            self.data_rsqi.append(int(p[7]))
                            self.data_diag_code.append(int(p[8]))
                            self.data_probe_state.append(int(p[9]))
                            self.data_led2.append(0.0);    self.data_led1.append(0.0)
                            self.data_aled2.append(0.0);   self.data_aled1.append(0.0)
                            self.data_led2_sub.append(0.0); self.data_led1_sub.append(0.0)
                            self.data_spo2_r.append(-1.0); self.data_pi.append(-1.0)
                            self.data_hr1.append(-1.0);    self.data_hr1_sqi.append(0.0)
                            self.data_hr2.append(-1.0);    self.data_hr2_sqi.append(0.0)
                            self.data_v_tia_led1.append(0.0);  self.data_v_tia_led2.append(0.0)
                            self.data_v_tia_aled1.append(0.0); self.data_v_tia_aled2.append(0.0)
                            self.data_i_pd_led1.append(0.0);   self.data_i_pd_led2.append(0.0)
                            self.data_i_pd_aled1.append(0.0);  self.data_i_pd_aled2.append(0.0)
                            self.data_ot2_led1.append(0.0);    self.data_ot2_led2.append(0.0)
                            self.hr3_calc.update(0.0, SPO2_RECEIVED_FS, int(p[0]))
                            if self.hr3test_window is not None:
                                self.hr3test_calc.update(0.0, SPO2_RECEIVED_FS, int(p[0]))
                            for sname, attr, _, _src in self._STATS_SIGNALS:
                                self._stats_buf[sname].append(getattr(self, attr)[-1])
                        except ValueError: pass
                        else: _new_data = True
                    elif lib_id == "M1" and len(parts) >= 4:
                        # $M1,SmpCnt,Ts_us,PPG_DISP  (minimal frame)
                        try:
                            self.data_lib_id.append(lib_id)
                            p = [float(x) for x in parts[1:4]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_ppgdisp.append(p[2])
                            self.data_spo2.append(-1.0);     self.data_spo2_sqi.append(0.0)
                            self.data_spo2_r.append(-1.0);   self.data_pi.append(-1.0)
                            self.data_hr1.append(-1.0);      self.data_hr1_sqi.append(0.0)
                            self.data_hr2.append(-1.0);      self.data_hr2_sqi.append(0.0)
                            self.data_hr3.append(-1.0);      self.data_hr3_sqi.append(0.0)
                            self.data_led2.append(0.0);      self.data_led1.append(0.0)
                            self.data_aled2.append(0.0);     self.data_aled1.append(0.0)
                            self.data_led2_sub.append(0.0);  self.data_led1_sub.append(0.0)
                            self.data_rsqi.append(0);        self.data_diag_code.append(0)
                            self.data_probe_state.append(0)
                            self.data_v_tia_led1.append(0.0);  self.data_v_tia_led2.append(0.0)
                            self.data_v_tia_aled1.append(0.0); self.data_v_tia_aled2.append(0.0)
                            self.data_i_pd_led1.append(0.0);   self.data_i_pd_led2.append(0.0)
                            self.data_i_pd_aled1.append(0.0);  self.data_i_pd_aled2.append(0.0)
                            self.data_ot2_led1.append(0.0);    self.data_ot2_led2.append(0.0)
                            self.hr3_calc.update(0.0, SPO2_RECEIVED_FS, int(p[0]))
                            if self.hr3test_window is not None:
                                self.hr3test_calc.update(0.0, SPO2_RECEIVED_FS, int(p[0]))
                            for sname, attr, _, _src in self._STATS_SIGNALS:
                                self._stats_buf[sname].append(getattr(self, attr)[-1])
                        except ValueError: pass
                        else: _new_data = True

                # Console window: batch update (already one Qt op per cycle — no extra throttle needed)
                if _console_lines and _src_com_win is not None:
                    _src_com_win.append_lines(_console_lines)

            if _new_data:
                if self.spo2lab_window is not None:
                    _t0a = time.perf_counter()
                    self.spo2lab_window.update_algorithms(
                        self.data_led1_sub, self.data_led2_sub,
                        self.data_spo2, self.data_spo2_r,
                        self.data_timestamp_us, self.data_sample_counter)
                    self._py_timing['algo_spo2lab'].append((time.perf_counter() - _t0a) * 1000)
                if self.spo2test_window is not None:
                    _t0a = time.perf_counter()
                    self.spo2test_window.update_algorithms(
                        self.data_led1_sub, self.data_led2_sub,
                        self.data_spo2, self.data_spo2_r, self.data_spo2_sqi,
                        self.data_timestamp_us, self.data_sample_counter)
                    self._py_timing['algo_spo2test'].append((time.perf_counter() - _t0a) * 1000)
                if self.hr2test_window is not None:
                    _t0a = time.perf_counter()
                    self.hr2test_window.update_algorithms(
                        self.data_led1_sub, self.data_hr2, self.data_hr2_sqi,
                        self.data_timestamp_us, self.data_sample_counter)
                    self._py_timing['algo_hr2test'].append((time.perf_counter() - _t0a) * 1000)
            if _new_data and not self.is_paused:
                self._render_pending = True

        except Exception as e:
            print(f"Error en loop: {e}")

        _drain_ms = (time.perf_counter() - _t0_drain) * 1000
        self._py_timing['drain'].append(_drain_ms)
        if _drain_ms > 15:
            print(f"[DRAIN] {_drain_ms:.1f} ms")

    def _refresh_plots_tick(self):
        """Render timer slot (50 ms). Decoupled from queue drain so rendering
        delays never affect serial data ingestion.
        Timing budget: PythonTimingWindow._PLOTS_TICK_BUDGET_MS.
        Render rows: PythonTimingWindow._PLOTS_TICK_ROWS."""
        _t_render = time.perf_counter()
        if not self._render_pending:
            return
        self._render_pending = False

        _t0_render = time.perf_counter()
        if self._last_render_t is not None:
            self._py_timing['render_interval'].append((_t0_render - self._last_render_t) * 1000)
        self._last_render_t = _t0_render
        try:
            # ProbeState cell col-0: update background on every render tick (200 ms)
            _ps = int(self.data_probe_state[-1]) if self.data_probe_state else -1
            if _ps == 2:
                _ps_bg = self._PROBE_APPLIED_BG
            elif _ps == 1:
                _ps_bg = self._PROBE_NOT_APPLIED_BG
            elif _ps == 0:
                _ps_bg = self._PROBE_DISCONNECTED_BG
            else:
                _ps_bg = self._VTG_DEFAULT
            _ps_sig_idx = next(i for i, (n, _, __, ___) in enumerate(self._STATS_SIGNALS) if n == "ProbeState")
            _ps_tbl_row = _ps_sig_idx if _ps_sig_idx < 4 else _ps_sig_idx + 1
            _ps_item = self.stats_table.item(_ps_tbl_row, 0)
            if _ps_item is not None:
                _ps_item.setBackground(_ps_bg)
                _ps_item.setForeground(QtGui.QColor("#FFFFFF") if _ps == 2 else QtGui.QColor("#AAAAAA"))

            # PPGPlotsWindow: throttled to 20 Hz (every render tick)
            self._ppgplots_refresh_counter += 1
            if self.ppgplots_window is not None and self._ppgplots_refresh_counter >= self._PPGPLOTS_REFRESH_EVERY:
                self._ppgplots_refresh_counter = 0
                _t0p = time.perf_counter()
                self.ppgplots_window.update_plots(
                    self.data_ppgdisp, self.data_hr1, self.data_hr2, self.data_hr3,
                    self.data_spo2, self.data_spo2_sqi, self.data_spo2_r,
                    self.data_hr1_sqi, self.data_hr2_sqi, self.data_hr3_sqi,
                    self.data_led2, self.data_led1,
                    self.data_aled2, self.data_aled1, self.data_led2_sub, self.data_led1_sub)
                self._py_timing['plot_ppgplots'].append((time.perf_counter() - _t0p) * 1000)

            # PPGSignalsWindow: throttled to 20 Hz
            self._signals_refresh_counter += 1
            if self.signals_window is not None and self._signals_refresh_counter >= self._PPGPLOTS_REFRESH_EVERY:
                self._signals_refresh_counter = 0
                _t0p = time.perf_counter()
                self.signals_window.update_plots(
                    self.data_led2, self.data_led1,
                    self.data_aled2, self.data_aled1, self.data_led2_sub, self.data_led1_sub,
                    self.data_ppgdisp)
                self._py_timing['plot_signals'].append((time.perf_counter() - _t0p) * 1000)

            # AlgoResultsWindow: throttled to 10 Hz
            self._results_refresh_counter += 1
            if self.results_window is not None and self._results_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                self._results_refresh_counter = 0
                _t0p = time.perf_counter()
                self.results_window.update_plots(
                    self.data_spo2, self.data_spo2_sqi, self.data_spo2_r,
                    self.data_hr1, self.data_hr2, self.data_hr3,
                    self.data_hr1_sqi, self.data_hr2_sqi, self.data_hr3_sqi)
                self._py_timing['plot_results'].append((time.perf_counter() - _t0p) * 1000)

            self._hrlab_refresh_counter += 1
            if self.hrlab_window is not None and self._hrlab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                self._hrlab_refresh_counter = 0
                _t0p = time.perf_counter()
                self.hrlab_window.update_plots(self.data_ppgdisp, self.data_timestamp_us, self.data_sample_counter)
                self._py_timing['plot_hrlab'].append((time.perf_counter() - _t0p) * 1000)

            self._spo2lab_refresh_counter += 1
            if self.spo2lab_window is not None and self._spo2lab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                self._spo2lab_refresh_counter = 0
                _t0p = time.perf_counter()
                self.spo2lab_window.update_plots()
                self._py_timing['plot_spo2lab'].append((time.perf_counter() - _t0p) * 1000)

            self._hr3lab_refresh_counter += 1
            if self.hr3lab_window is not None and self._hr3lab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                self._hr3lab_refresh_counter = 0
                _t0p = time.perf_counter()
                self.hr3lab_window.update_plots(
                    self.data_hr1, self.data_hr2, self.data_hr3, self.hr3_calc)
                self._py_timing['plot_hr3lab'].append((time.perf_counter() - _t0p) * 1000)

            self._spo2test_refresh_counter += 1
            if self.spo2test_window is not None and self._spo2test_refresh_counter >= self._SPOST_REFRESH_EVERY:
                self._spo2test_refresh_counter = 0
                _t0p = time.perf_counter()
                self.spo2test_window.update_plots()
                self._py_timing['plot_spo2test'].append((time.perf_counter() - _t0p) * 1000)

            self._hr1test_refresh_counter += 1
            if self.hr1test_window is not None and self._hr1test_refresh_counter >= self._HR1TEST_REFRESH_EVERY:
                self._hr1test_refresh_counter = 0
                _t0p = time.perf_counter()
                self.hr1test_window.update_plots(
                    self.data_hr1, self.data_hr1_sqi,
                    self.data_timestamp_us, self.data_sample_counter)
                self._py_timing['plot_hr1test'].append((time.perf_counter() - _t0p) * 1000)

            self._hr2test_refresh_counter += 1
            if self.hr2test_window is not None and self._hr2test_refresh_counter >= self._HR2TEST_REFRESH_EVERY:
                self._hr2test_refresh_counter = 0
                _t0p = time.perf_counter()
                self.hr2test_window.update_plots()
                self._py_timing['plot_hr2test'].append((time.perf_counter() - _t0p) * 1000)

            self._hr3test_refresh_counter += 1
            if self.hr3test_window is not None and self._hr3test_refresh_counter >= self._HR3TEST_REFRESH_EVERY:
                self._hr3test_refresh_counter = 0
                _t0p = time.perf_counter()
                self.hr3test_window.update_plots(
                    self.data_led1_sub, self.data_hr3, self.data_hr3_sqi,
                    self.data_timestamp_us, self.data_sample_counter)
                self._py_timing['plot_hr3test'].append((time.perf_counter() - _t0p) * 1000)

            self._pilab_refresh_counter += 1
            if self.pilab_window is not None and self._pilab_refresh_counter >= self._PILAB_REFRESH_EVERY:
                self._pilab_refresh_counter = 0
                _t0p = time.perf_counter()
                self.pilab_window.update_plots()
                self._py_timing['plot_pilab'].append((time.perf_counter() - _t0p) * 1000)

            # PythonTimingWindow: refresh every ~1 s (5 render ticks at 200 ms)
            self._pytiming_refresh_counter += 1
            if self.python_timing_window is not None and self._pytiming_refresh_counter >= 5:
                self._pytiming_refresh_counter = 0
                # Clear timing deques for windows that are currently closed
                if self.ppgplots_window  is None: self._py_timing['plot_ppgplots'].clear()
                if self.signals_window   is None: self._py_timing['plot_signals'].clear()
                if self.results_window   is None: self._py_timing['plot_results'].clear()
                if self.hrlab_window     is None: self._py_timing['plot_hrlab'].clear()
                if self.spo2lab_window   is None:
                    self._py_timing['plot_spo2lab'].clear()
                    self._py_timing['algo_spo2lab'].clear()
                if self.hr3lab_window    is None: self._py_timing['plot_hr3lab'].clear()
                if self.spo2test_window  is None:
                    self._py_timing['plot_spo2test'].clear()
                    self._py_timing['algo_spo2test'].clear()
                if self.hr1test_window   is None: self._py_timing['plot_hr1test'].clear()
                if self.hr2test_window   is None:
                    self._py_timing['plot_hr2test'].clear()
                    self._py_timing['algo_hr2test'].clear()
                if self.hr3test_window   is None: self._py_timing['plot_hr3test'].clear()
                if self.pilab_window     is None: self._py_timing['plot_pilab'].clear()
                _pt_stats = {}
                for k, q in self._py_timing.items():
                    if q:
                        _d = list(q)
                        _pt_stats[k] = (sum(_d) / len(_d), max(_d))
                    else:
                        _pt_stats[k] = None  # window closed — show "—"
                _pt_gaps = {
                    'gap_queue':    (sum(self._queue_size_buf) / len(self._queue_size_buf),
                                     max(self._queue_size_buf)) if self._queue_size_buf else (0, 0),
                    'gap_B':        self._gaps_B,
                    'gap_hr1test':  self.hr1test_calc.gap_count,
                    'gap_hr3lab':   self.hr3_calc.gap_count,
                    'gap_hr3test':  self.hr3test_calc.gap_count,
                    'gap_spo2lab':  self.spo2lab_window.gap_count  if self.spo2lab_window  is not None else None,
                    'gap_spo2test': self.spo2test_window.gap_count if self.spo2test_window is not None else None,
                    'gap_hr2test':  self.hr2test_window.gap_count  if self.hr2test_window  is not None else None,
                }
                self.python_timing_window.update_timing(_pt_stats, _pt_gaps)

        except Exception as e:
            print(f"Error en render: {e}")

        _render_ms = (time.perf_counter() - _t0_render) * 1000
        self._py_timing['render'].append(_render_ms)
        if _render_ms > 15:
            print(f"[RENDER] {_render_ms:.1f} ms")

    def showEvent(self, event):
        super().showEvent(event)
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        if s.value("PPGMonitor/ppgplots_open",  True,  type=bool):
            QtCore.QTimer.singleShot(0, self._open_ppgplots_default)
        if s.value("PPGMonitor/signals_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_signals_default)
        if s.value("PPGMonitor/results_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_results_default)
        if s.value("PPGMonitor/serialcom_open", True,  type=bool):
            QtCore.QTimer.singleShot(0, self._open_serialcom_default)
        if s.value("PPGMonitor/hr3lab_open",    True,  type=bool):
            QtCore.QTimer.singleShot(0, self._open_hr3lab_default)
        if s.value("PPGMonitor/hrlab_open",     False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_hrlab_default)
        if s.value("PPGMonitor/spo2lab_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_spo2lab_default)
        if s.value("PPGMonitor/spo2test_open",  False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_spo2test_default)
        if s.value("PPGMonitor/hr1test_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_hr1test_default)
        if s.value("PPGMonitor/hr2test_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_hr2test_default)
        if s.value("PPGMonitor/hr3test_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_hr3test_default)
        if s.value("PPGMonitor/pilab_open",     False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_pilab_default)
        if s.value("PPGMonitor/esp32_timing_open",    False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_esp32_timing_default)
        if s.value("PPGMonitor/python_timing_open",  False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_python_timing_default)
        if s.value("PPGMonitor/hw_config_open",    False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_hw_config_default)
        if s.value("PPGMonitor/diagnostics_open",  False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_diagnostics_default)
        if s.value("PPGMonitor/afe_sweep_open",     False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_afe_sweep_default)
        if s.value("PPGMonitor/labcapture_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_lab_capture_default)
        if getattr(self, '_restore_serial_on_start', False):
            QtCore.QTimer.singleShot(50,  lambda: self._connect_serial(self.combo_port.currentText()))
        if getattr(self, '_restore_udp_on_start', False):
            QtCore.QTimer.singleShot(150, self._connect_udp)
        QtCore.QTimer.singleShot(300, self._bring_all_to_front)

    def _bring_all_to_front(self):
        pass

    def _auto_close_chk(self):
        if self.save_file_chk is not None:
            self.save_file_chk.close()
            self.save_file_chk = None
        print(f"[save-chk] DONE: {self._chk_filename}")
        QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)

    def closeEvent(self, event):
        self._save_settings()
        if getattr(self, 'is_saving', False) and getattr(self, 'save_file', None):
            self.save_file.close()
        if getattr(self, 'is_lab_capturing', False) and getattr(self, '_lab_capture_file', None):
            self._lab_capture_file.close()
        if getattr(self, 'save_file_chk', None):
            self.save_file_chk.close()
        if hasattr(self, '_reader_stop'):
            self._reader_stop.set()
        if hasattr(self, '_reader_thread') and self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        if hasattr(self, '_udp_stop'):
            self._udp_stop.set()
        if hasattr(self, '_udp_thread') and self._udp_thread is not None:
            self._udp_thread.join(timeout=1.0)
        if hasattr(self, '_cmd_udp_sock') and self._cmd_udp_sock is not None:
            self._cmd_udp_sock.close()
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        if self.ppgplots_window is not None:
            self.ppgplots_window.main_monitor = None
            self.ppgplots_window.close()
        if self.signals_window is not None:
            self.signals_window.main_monitor = None
            self.signals_window.close()
        if self.results_window is not None:
            self.results_window.main_monitor = None
            self.results_window.close()
        if self.serialcom_window is not None:
            self.serialcom_window.main_monitor = None
            self.serialcom_window.close()
        if self.udpcom_window is not None:
            self.udpcom_window.main_monitor = None
            self.udpcom_window.close()
        if self.hrlab_window is not None:
            self.hrlab_window.main_monitor = None
            self.hrlab_window.close()
        if self.spo2lab_window is not None:
            self.spo2lab_window.main_monitor = None
            self.spo2lab_window.close()
        if self.hr3lab_window is not None:
            self.hr3lab_window.main_monitor = None
            self.hr3lab_window.close()
        if self.spo2test_window is not None:
            self.spo2test_window.close()
        if self.hr1test_window is not None:
            self.hr1test_window.close()
        if self.hr2test_window is not None:
            self.hr2test_window.close()
        if self.hr3test_window is not None:
            self.hr3test_window.close()
        if self.pilab_window is not None:
            self.pilab_window.main_monitor = None
            self.pilab_window.close()
        if self.esp32_timing_window is not None:
            self.esp32_timing_window.close()
        if self.python_timing_window is not None:
            self.python_timing_window.close()
        if self.hw_config_window is not None:
            self.hw_config_window.main_monitor = None
            self.hw_config_window.close()
        if self.diag_window is not None:
            self.diag_window.main_monitor = None
            self.diag_window.close()
        if self.afe_sweep_window is not None:
            self.afe_sweep_window.main_monitor = None
            self.afe_sweep_window.close()
        if self.lab_capture_window is not None:
            self.lab_capture_window.main_monitor = None
            self.lab_capture_window.close()
        event.accept()
        QtWidgets.QApplication.quit()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AFE4490 PPG Monitor")
    parser.add_argument("--save-chk", action="store_true",
                        help="Auto-save diagnostic CSV with raw frames and CHK_OK field")
    parser.add_argument("--save-chk-duration", type=int, default=15, metavar="N",
                        help="Auto-close CHK file and exit after N seconds (default: 15)")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)

    # GPU rendering — must be set before any PlotWidget is created.
    # useOpenGL=True offloads curve rasterization to the GPU (dramatically
    # faster than software antialiasing, especially for >1000-point curves).
    pg.setConfigOptions(antialias=True, useOpenGL=True)

    class _FastTipStyle(QtWidgets.QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, returnData=None):
            if hint == QtWidgets.QStyle.SH_ToolTip_WakeUpDelay:
                return 150  # ms (default ~700 ms)
            return super().styleHint(hint, option, widget, returnData)

    app.setStyle(_FastTipStyle('Fusion'))
    app.setStyleSheet(
        "QToolTip { background-color: #5500AA; color: #F0F0F0; "
        "border: 2px solid #FFE066; padding: 8px; }"
        "QMenu { min-width: 360px; } "
        "QMenu::item { min-width: 340px; padding: 4px 20px 4px 28px; }"
    )
    window = PPGMonitor(save_chk=args.save_chk, save_chk_duration=args.save_chk_duration)
    window.show()
    sys.exit(app.exec_())
