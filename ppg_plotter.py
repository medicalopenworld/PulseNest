import sys
import os
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
                              hr_min=25, hr_max=300, prominence=0.1):
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
                              hr_min=25, hr_max=300, prominence=0.1):
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
PORT = 'COM15'
BAUD = 921600
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ppg_plotter.ini")
WINDOW_SIZE        = 500   # 10 s @ 50 Hz (500 Hz / SERIAL_DOWNSAMPLING_RATIO=10)
PPG_WINDOW_SIZE    = 500   # 10 s — same as WINDOW_SIZE
SPO2_CAL_BUFSIZE   = 3000  # 60 s @ 50 Hz — rolling buffer for SpO2LabWindow
SPO2_RECEIVED_FS   = 50.0  # AFE4490 @ 500 Hz, SERIAL_DOWNSAMPLING_RATIO=10


class SpO2LocalCalc:
    """Replicates firmware _update_spo2() in Python for independent verification.

    Constants must match mow_afe4490.cpp:
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
      LP_CUTOFF_HZ=10, BUF_LEN=512, UPDATE_INTERVAL_S=0.5, HR_MIN_HZ=0.5, HR_MAX_HZ=3.5
    """
    LP_CUTOFF_HZ       = 10.0
    BUF_LEN            = 512
    UPDATE_INTERVAL_S  = 0.5
    HR_MIN_HZ          = 25.0 / 60.0  # 0.4167 Hz — 25 BPM — reported valid lower bound (ISO 80601-2-61; neonatal)
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

    def update(self, led1_aled1, fs):
        """Process one sample. Returns (hr_bpm, hr_valid)."""
        if fs != self._fs:
            self._recalc_params(fs)

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
        spectrum = np.abs(np.fft.rfft(seg))
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

        # Dominant peak in HPS (highest peak with minimum prominence)
        spec_hr = spectrum[mask]       # kept for harmonic_ratio computation below
        peaks, _ = signal.find_peaks(hps_hr, prominence=0.05 * np.max(hps_hr))
        peak_local = int(peaks[np.argmax(hps_hr[peaks])]) if len(peaks) > 0 else int(np.argmax(hps_hr))
        peak_global = idx_offset + peak_local

        # Parabolic sub-bin interpolation on original spectrum (not HPS) for freq precision
        if 0 < peak_global < len(spectrum) - 1:
            yp, yc, yn = spectrum[peak_global - 1], spectrum[peak_global], spectrum[peak_global + 1]
            denom = yp - 2.0 * yc + yn
            delta = 0.5 * (yp - yn) / denom if denom < 0.0 else 0.0
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

    Independent reimplementation of firmware _update_spo2() from mow_afe4490_spec.md §5.1.
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

    # Firmware defaults — must match mow_afe4490_spec.md §5.1 and mow_afe4490.cpp constants
    FW_DC_IIR_TAU_S = 1.6
    FW_AC_EMA_TAU_S = 1.0
    FW_SPO2_MIN_DC  = 1000.0
    FW_WARMUP_S     = 5.0
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

    Independent reimplementation of firmware _update_hr1() from mow_afe4490_spec.md §5.2.
    Purpose: post-implementation verification — compare against firmware output to detect bugs.

    Processing chain per sample:
      IR_Sub → IIR DC removal (τ=1.6 s) → negate (PPG polarity) →
      moving average LP (cutoff ~5 Hz, len=fs/(2×5), max 64) →
      running maximum (×0.9999 decay) →
      threshold crossing (0.6 × running_max, refractory 0.2 s) →
      RR buffer (last 5 intervals) →
      HR1 = fs × 60 / mean(RR) →
      SQI = clamp(1 − CV/0.15, 0, 1)  where CV = std/mean of RR intervals

    Diagnostic buffers expose every intermediate signal for visualization.
    PPGMonitor feeds this calc at full 500 Hz (before decimation).
    """

    # Firmware defaults — must match mow_afe4490_spec.md §5.2
    FW_DC_IIR_TAU_S      = 1.6
    FW_MA_CUTOFF_HZ      = 5.0
    FW_MA_MAX_LEN        = 64
    FW_RUNNING_MAX_DECAY = 0.9999
    FW_THRESHOLD_FACTOR  = 0.6
    FW_REFRACTORY_S      = 0.2
    FW_RR_BUF_LEN        = 5
    FW_HR_MIN_BPM        = 25.0
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

    def update(self, ir_sub, fs):
        """Process one sample at full firmware rate.

        Parameters
        ----------
        ir_sub : float  — IR_Sub (LED1-ALED1) ADC value
        fs     : float  — sample rate (Hz)
        """
        if fs != self._fs:
            self._recalc_params(fs)

        # 1. IIR DC removal
        self._dc_est = self._dc_alpha * self._dc_est + (1.0 - self._dc_alpha) * ir_sub
        dc_removed   = ir_sub - self._dc_est

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

    Independent reimplementation of firmware _update_hr2() from mow_afe4490_spec.md §5.3.
    Purpose: post-implementation verification.

    Processing chain per sample (at 50 Hz after firmware decimation):
      IR_Sub → biquad BPF 0.5–5 Hz → circular buffer 400 samples →
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
    FW_HR_MIN_BPM    = 25.0
    FW_HR_MAX_BPM    = 300.0
    FW_HR_SEARCH_MIN = 22.0
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

    def update(self, ir_sub, fs):
        if fs != self._fs or self._b is None:
            self._recalc_filter(fs)

        # BPF
        x = float(ir_sub)
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

        # Normalised autocorrelation using scipy.signal.correlate (full, FFT)
        n = len(seg)
        max_lag = min(self.max_lag, n - 1)
        full = signal.correlate(seg, seg, mode='full', method='fft')
        acorr = full[n - 1: n - 1 + max_lag + 1]
        if acorr[0] != 0:
            acorr = acorr / acorr[0]
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


def _make_tooltip(name: str, text: str) -> str:
    """Build a rich-text HTML tooltip with a vivid purple background.

    ``name`` is shown in bold gold as the first line; ``text`` follows in light grey.
    Used by every interactive control in the script.
    """
    return (
        "<table width='540' style='background-color:#5500AA; border-radius:6px;'>"
        "<tr><td style='padding:8px;'>"
        "<span style='font-size:32px; font-weight:bold; color:#FFE066;'>"
        f"{name}"
        "</span><br/>"
        "<span style='font-size:30px; white-space:normal; color:#F0F0F0;'>"
        f"{text}"
        "</span></td></tr></table>"
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
        self.p_dc   = _make_plot(2, "DC  (IR, RED)",         "ADC counts")
        self.p_ac   = _make_plot(3, "RMS AC  (IR, RED)",     "ADC counts")

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

        self.curve_dc_ir  = self.p_dc.plot(pen=pg.mkPen('#4488FF', width=1.5), name="DC IR")
        self.curve_dc_red = self.p_dc.plot(pen=pg.mkPen('#FF4444', width=1.5), name="DC RED")
        self.p_dc.addLegend()

        self.curve_rms_ir  = self.p_ac.plot(pen=pg.mkPen('#44AAFF', width=1.5), name="RMS AC IR")
        self.curve_rms_red = self.p_ac.plot(pen=pg.mkPen('#FF6666', width=1.5), name="RMS AC RED")
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
            "Used as the target when adding a calibration point."))
        self._spin_avg_win = QtWidgets.QSpinBox()
        self._spin_avg_win.setRange(1, 30)
        self._spin_avg_win.setValue(5)
        self._spin_avg_win.setSuffix(" s")
        self._spin_avg_win.setStyleSheet("background-color: #2A2A2A; color: #E0E0E0; padding: 2px;")
        self._spin_avg_win.setToolTip(_make_tooltip(
            "Avg window",
            "Duration (seconds) of the rolling average used to compute R_fw and R_local "
            "when capturing a calibration point. Longer = more stable, slower to react."))
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
        filename = f"spo2_cal_{now_str}.csv"
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

    def update_plots(self, data_ir_sub, data_red_sub, data_spo2, data_spo2_r,
                     data_timestamp_us, data_sample_counter):
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

        nan = float('nan')
        for i in new_indices:
            ts     = float(data_timestamp_us[i])
            ir     = float(data_ir_sub[i])
            red    = float(data_red_sub[i])
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
        self.curve_dc_ir.setData(t_arr,    dc_ir_arr)
        self.curve_dc_red.setData(t_arr,   dc_red_arr)
        self.curve_rms_ir.setData(t_arr,   rms_ir_arr)
        self.curve_rms_red.setData(t_arr,  rms_red_arr)

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
            f"<b style='color:#4488FF'>DC IR: {_fmt(v_dc_ir, 0)}</b>"
            f" &nbsp; <b style='color:#FF4444'>DC RED: {_fmt(v_dc_red, 0)}</b>")
        self.p_ac.setTitle(
            f"<b style='color:#44AAFF'>RMS AC IR: {_fmt(v_rms_ir, 1)}</b>"
            f" &nbsp; <b style='color:#FF6666'>RMS AC RED: {_fmt(v_rms_red, 1)}</b>")

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
    derived from mow_afe4490_spec.md §5.1) and compares its output against the firmware
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
        self._t0_us           = None
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
        self.p_dc    = _mp(4, "DC  (IR, RED)",       "ADC counts", link_to=self.p_spo2)
        self.p_ac    = _mp(5, "RMS AC  (IR, RED)",   "ADC counts", link_to=self.p_spo2)

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
        self.curve_dc_ir  = self.p_dc.plot(pen=IR_PEN,  name="DC IR")
        self.curve_dc_red = self.p_dc.plot(pen=RED_PEN, name="DC RED")
        self.p_ac.addLegend()
        self.curve_rms_ir  = self.p_ac.plot(pen=IR2_PEN, name="RMS AC IR")
        self.curve_rms_red = self.p_ac.plot(pen=R2_PEN,  name="RMS AC RED")

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
            "Empirical calibration coefficient. Changing this shifts the SpO2 curve vertically."))
        self._spin_b.setToolTip(_make_tooltip(
            "SpO2 coefficient b",
            "SpO2 = a − b·R. Firmware default: 30.5547. "
            "Empirical calibration coefficient. Changing this changes the slope of the SpO2 vs R curve."))
        self._spin_dc_tau.setToolTip(_make_tooltip(
            "DC IIR time constant",
            "IIR low-pass filter time constant for DC level tracking [s]. "
            "Firmware default: 1.6 s. α = exp(−1/(τ·fs))."))
        self._spin_ac_tau.setToolTip(_make_tooltip(
            "AC EMA time constant",
            "EMA time constant for AC² tracking [s]. "
            "Firmware default: 1.0 s. β = 1 − exp(−1/(τ·fs))."))
        self._spin_warmup.setToolTip(_make_tooltip(
            "Warmup period",
            "Number of seconds before the algorithm starts outputting valid SpO2 [s]. "
            "Firmware default: 5.0 s."))
        self._spin_min_dc.setToolTip(_make_tooltip(
            "Min DC level",
            "Minimum DC level on both IR and RED channels to produce a valid SpO2 [ADC counts]. "
            "Firmware default: 1000. Below this → no finger detected."))

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
        _val_rows = ["SpO2 (%)", "R", "PI (%)", "SQI", "DC IR", "DC RED", "RMS AC IR", "RMS AC RED"]
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
        rows_ir_sub  = []
        rows_red_sub = []
        rows_spo2_fw = []
        rows_R_fw    = []
        rows_sqi_fw  = []
        rows_ts_us   = []

        with open(path, 'r', newline='') as f:
            header = f.readline().strip()
            # Detect format by header
            is_chk = header.startswith("Timestamp_PC,Diff_us_PC,CHK_OK")
            is_raw = "LibID" in header
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
                        if len(parts) < 20 or parts[0] != '$M1':
                            continue
                        # $M1,SmpCnt,Ts_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,PPG,SpO2,SpO2_SQI,SpO2_R,PI,...
                        ts_us   = float(parts[2])
                        ir_sub  = float(parts[8])
                        red_sub = float(parts[7])
                        spo2_fw = float(parts[10])
                        R_fw    = float(parts[12])
                        sqi_fw  = float(parts[11])
                    elif is_raw:
                        # Format: Timestamp_PC,Diff_us_PC,LibID,SmpCnt,Ts_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,...
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', '$M1'):
                            continue
                        offset = 3  # after Timestamp_PC, Diff_us_PC, LibID
                        ts_us   = float(row[offset + 1])
                        ir_sub  = float(row[offset + 7])
                        red_sub = float(row[offset + 6])
                        spo2_fw = float(row[offset + 8])
                        R_fw    = float(row[offset + 10])
                        sqi_fw  = float(row[offset + 9])
                    else:
                        continue
                    rows_ts_us.append(ts_us)
                    rows_ir_sub.append(ir_sub)
                    rows_red_sub.append(red_sub)
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
        arr_spo2_py  = np.full(len(rows_ir_sub), nan)
        arr_R_py     = np.full(len(rows_ir_sub), nan)
        arr_sqi_py   = np.full(len(rows_ir_sub), nan)
        arr_dc_ir    = np.full(len(rows_ir_sub), nan)
        arr_dc_red   = np.full(len(rows_ir_sub), nan)
        arr_rms_ir   = np.full(len(rows_ir_sub), nan)
        arr_rms_red  = np.full(len(rows_ir_sub), nan)

        for i, (ir, red) in enumerate(zip(rows_ir_sub, rows_red_sub)):
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
                  self.curve_dc_ir, self.curve_dc_red, self.curve_rms_ir, self.curve_rms_red]:
            c.setData([], [])

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        t = self._arr_t if self._offline_mode else np.array(self._buf_t)
        if len(t) == 0:
            QtWidgets.QMessageBox.information(self, "Export", "No data to export.")
            return
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"spo2test_{now_str}.csv"
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

    def update_plots(self, data_ir_sub, data_red_sub, data_spo2, data_spo2_r,
                     data_spo2_sqi, data_timestamp_us, data_sample_counter):
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

        nan = float('nan')
        for i in new_indices:
            ts     = float(data_timestamp_us[i])
            ir     = float(data_ir_sub[i])
            red    = float(data_red_sub[i])
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

        self._last_sample_cnt = data_sample_counter[-1]

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
        if r and not r['warmup']:
            py_vals[2] = r.get('pi', float('nan'))
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
        self.curve_dc_ir.setData(t, dc_ir)
        self.curve_dc_red.setData(t, dc_red)
        self.curve_rms_ir.setData(t, rms_ir)
        self.curve_rms_red.setData(t, rms_red)

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
    derived from mow_afe4490_spec.md §5.2) and compares its output against firmware values.

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
            "α = exp(−1/(τ·fs)). Larger τ → slower DC tracking."))
        self._spin_ma_cut.setToolTip(_make_tooltip("MA cutoff",
            "Moving average low-pass cutoff frequency [Hz]. Firmware default: 5 Hz. "
            "MA length = fs / (2 × cutoff), capped at MA max len."))
        self._spin_ma_max.setToolTip(_make_tooltip("MA max len",
            "Maximum moving average window length [samples]. Firmware default: 64."))
        self._spin_decay.setToolTip(_make_tooltip("Running max decay",
            "Per-sample exponential decay factor for the running maximum. "
            "Firmware default: 0.9999. Values < 1 make the tracker forget old peaks."))
        self._spin_thr.setToolTip(_make_tooltip("Threshold factor",
            "Rising-edge threshold = factor × running_max. Firmware default: 0.6."))
        self._spin_refr.setToolTip(_make_tooltip("Refractory period",
            "Minimum time between two detected peaks [s]. Firmware default: 0.2 s (~300 BPM max)."))

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
        rows_ir_sub = []
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
                        if len(parts) < 20 or parts[0] != '$M1':
                            continue
                        ts_us  = float(parts[2])
                        ir_sub = float(parts[8])
                        hr_fw  = float(parts[14])
                        sqi_fw = float(parts[15])
                    else:
                        # LibID,SmpCnt,Ts_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,...,HR1,HR1_SQI,...
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', '$M1'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        ir_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 12])
                        sqi_fw = float(row[offset + 13])
                    rows_ts_us.append(ts_us)
                    rows_ir_sub.append(ir_sub)
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
        n = len(rows_ir_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_ir_sub):
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
        filename = f"hr1test_{now_str}.csv"
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
    derived from mow_afe4490_spec.md §5.3) and compares against firmware output.

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
        DLT_PEN = pg.mkPen('#FF6666', width=1.5)
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
        self._peak_line  = pg.InfiniteLine(
            angle=90, pos=0, movable=False,
            pen=pg.mkPen('#00FF88', width=2),
            label='peak', labelOpts={'color': '#00FF88', 'position': 0.92})
        self.p_acorr.addItem(self._peak_line)

        self.curve_filt   = self.p_filt.plot(pen=FILT_PEN)
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
            "Bandpass filter lower cutoff [Hz]. Firmware default: 0.5 Hz."))
        self._spin_bpf_hi.setToolTip(_make_tooltip("BPF high cutoff",
            "Bandpass filter upper cutoff [Hz]. Firmware default: 5.0 Hz."))
        self._spin_buf_len.setToolTip(_make_tooltip("Buffer length",
            "Circular buffer length [samples]. Firmware default: 400 (8 s at 50 Hz)."))
        self._spin_max_lag.setToolTip(_make_tooltip("Max lag",
            "Maximum autocorrelation lag to compute [samples]. "
            "Firmware default: 137 (≈22 BPM guard band at 50 Hz: 50×60/22=136.4)."))
        self._spin_upd_n.setToolTip(_make_tooltip("Update interval",
            "Recompute autocorrelation every N samples. Firmware default: 25 (0.5 s at 50 Hz)."))
        self._spin_min_lag.setToolTip(_make_tooltip("Min lag",
            "Minimum lag to search [s]. Firmware default: 0.185 s (~303 BPM guard band)."))
        self._spin_min_cor.setToolTip(_make_tooltip("Min correlation",
            "Minimum normalised autocorrelation at peak to be considered valid. "
            "Firmware default: 0.5. Also shown as a red dashed line on the autocorrelation plot."))

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
        rows_ir_sub = []
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
                        if len(parts) < 20 or parts[0] != '$M1':
                            continue
                        ts_us  = float(parts[2])
                        ir_sub = float(parts[8])
                        hr_fw  = float(parts[16])
                        sqi_fw = float(parts[17])
                    else:
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', '$M1'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        ir_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 14])
                        sqi_fw = float(row[offset + 15])
                    rows_ts_us.append(ts_us)
                    rows_ir_sub.append(ir_sub)
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
        n = len(rows_ir_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_ir_sub):
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
        filename = f"hr2test_{now_str}.csv"
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

    def update_plots(self, data_ir_sub, data_hr2, data_hr2_sqi,
                     data_timestamp_us, data_sample_counter):
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
            ir    = float(data_ir_sub[i])
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

    Independent reimplementation of firmware _update_hr3() from mow_afe4490_spec.md §5.4.
    Purpose: post-implementation verification.

    Processing chain per sample (at 50 Hz after firmware decimation):
      IR_Sub → 2nd-order Butterworth LP 10 Hz → circular buffer 512 samples →
      [every 25 samples] mean subtraction → Hann window → rfft →
      HPS: P[k]·P[2k]·P[3k] → argmax in HR range → parabolic interpolation
      → HR3 = peak_freq × 60

    SQI (HPS peak prominence, spec §5.4):
      fraction = HPS[peak_bin] / Σ HPS[k]   (k across search range)
      baseline = 1 / N_bins_search
      SQI      = clamp((fraction − baseline) / (1 − baseline), 0, 1)

    Diagnostic state exposed for HR3TestWindow:
      last_spectrum      — FFT magnitude normalised to HR-band max
      last_freqs         — frequency axis (Hz)
      last_hps           — HPS curve normalised to HR-band max
      last_peak_freq     — detected peak frequency (Hz)
      last_filtered_buf  — LP filtered circular buffer (ordered oldest→newest)
    """

    FW_FS            = 50.0
    FW_LP_CUTOFF_HZ  = 10.0
    FW_BUF_LEN       = 512
    FW_UPDATE_N      = 25
    FW_HPS_HARMONICS = 3        # k = 2, 3  (multiply 2 additional harmonic downsamples)
    FW_HR_MIN_BPM    = 25.0
    FW_HR_MAX_BPM    = 300.0
    FW_HR_SEARCH_MIN = 22.0     # guard band −3 BPM
    FW_HR_SEARCH_MAX = 303.0    # guard band +3 BPM

    def __init__(self):
        self.lp_cutoff_hz  = self.FW_LP_CUTOFF_HZ
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
        self.lp_cutoff_hz  = self.FW_LP_CUTOFF_HZ
        self.buf_len       = self.FW_BUF_LEN
        self.update_n      = self.FW_UPDATE_N
        self.hps_harmonics = self.FW_HPS_HARMONICS
        self.reset()

    @property
    def using_defaults(self):
        return (
            self.lp_cutoff_hz  == self.FW_LP_CUTOFF_HZ  and
            self.buf_len       == self.FW_BUF_LEN        and
            self.update_n      == self.FW_UPDATE_N       and
            self.hps_harmonics == self.FW_HPS_HARMONICS
        )

    def _recalc_filter(self, fs):
        self._fs = fs
        nyq = fs / 2.0
        self._b, self._a = signal.butter(2, min(self.lp_cutoff_hz / nyq, 0.9999), btype='low')
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

    def update(self, ir_sub, fs):
        """Process one 50 Hz sample. Returns (hr_bpm, hr_sqi)."""
        if fs != self._fs or self._b is None:
            self._recalc_filter(fs)

        # LP filter
        filtered, self._zi = signal.lfilter(self._b, self._a, [float(ir_sub)], zi=self._zi)
        filtered = filtered[0]

        # Circular buffer
        self._buf[self._buf_idx] = filtered
        self._buf_idx = (self._buf_idx + 1) % self.buf_len
        if self._buf_count < self.buf_len:
            self._buf_count += 1

        self._update_ctr += 1
        if self._update_ctr < self.update_n:
            return self.hr_bpm, self.hr_sqi
        self._update_ctr = 0

        if self._buf_count < self.buf_len:
            return self.hr_bpm, self.hr_sqi

        # Ordered buffer (oldest first)
        seg_raw = np.roll(self._buf, -self._buf_idx)
        self.last_filtered_buf = seg_raw.copy()

        # Mean subtraction → Hann window → rfft
        seg      = seg_raw - seg_raw.mean()
        seg      = seg * np.hanning(self.buf_len)
        spectrum = np.abs(np.fft.rfft(seg))
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

        # Parabolic sub-bin interpolation on original spectrum
        if 0 < peak_global < len(spectrum) - 1:
            yp, yc, yn = spectrum[peak_global - 1], spectrum[peak_global], spectrum[peak_global + 1]
            denom = yp - 2.0 * yc + yn
            delta = 0.5 * (yp - yn) / denom if denom < 0.0 else 0.0
        else:
            delta = 0.0
        freq_res  = fs / self.buf_len
        peak_freq = freqs[peak_global] + delta * freq_res
        hr_bpm    = peak_freq * 60.0

        # SQI: HPS peak prominence (spec §5.4)
        spec_hr   = spectrum[mask]
        total_hps = float(np.sum(hps_hr))
        if total_hps > 0.0:
            fraction = float(hps[peak_global]) / total_hps
            baseline = 1.0 / n_bins if n_bins > 0 else 1.0
            sqi = max(0.0, min(1.0, (fraction - baseline) / (1.0 - baseline))) if baseline < 1.0 else 0.0
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


class HR3TestWindow(QtWidgets.QMainWindow):
    """HR3TEST — post-implementation verification window for the HR3 algorithm.

    Runs an independent Python mirror of the firmware HR3 algorithm (HR3TestCalc,
    derived from mow_afe4490_spec.md §5.4) and compares against firmware output.

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

        self._calc            = HR3TestCalc()
        self._last_sample_cnt = -1
        self._t0_us           = None
        self._offline_mode    = False

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

        FW_PEN   = pg.mkPen('#00CC66', width=2)
        PY_PEN   = pg.mkPen('#FFDD44', width=2)
        FFT_PEN  = pg.mkPen('#00CCFF', width=1.5)
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
        self.p_hr.addLegend()
        self.curve_hr_fw = self.p_hr.plot(pen=FW_PEN,  name="HR3 fw")
        self.curve_hr_py = self.p_hr.plot(pen=PY_PEN,  name="HR3 py")
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

        self._spin_lp_cutoff   = _dspin(0.5, 20.0, HR3TestCalc.FW_LP_CUTOFF_HZ, 1, 0.5, " Hz")
        self._spin_buf_len     = _ispin(128,  1024, HR3TestCalc.FW_BUF_LEN)
        self._spin_upd_n       = _ispin(1,    200,  HR3TestCalc.FW_UPDATE_N)
        self._spin_harmonics   = _ispin(2,    5,    HR3TestCalc.FW_HPS_HARMONICS)

        self._spin_lp_cutoff.setToolTip(_make_tooltip("LP cutoff",
            "Butterworth low-pass filter cutoff frequency [Hz]. "
            "Firmware default: 10 Hz. Anti-aliasing before virtual decimation."))
        self._spin_buf_len.setToolTip(_make_tooltip("Buffer length",
            "Circular buffer length [samples]. "
            "Firmware default: 512 (10.24 s at 50 Hz). Determines FFT frequency resolution."))
        self._spin_upd_n.setToolTip(_make_tooltip("Update every N",
            "Run FFT/HPS every N samples. "
            "Firmware default: 25 (every 0.5 s at 50 Hz)."))
        self._spin_harmonics.setToolTip(_make_tooltip("HPS harmonics",
            "Number of harmonic downsamples in HPS: multiply spectrum by P[2k], ..., P[Kk]. "
            "Firmware default: 3 (k=2 and k=3)."))

        def _row(label_text, widget):
            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet(_lbl_s)
            form.addRow(lbl, widget)

        _row("LP cutoff:",        self._spin_lp_cutoff)
        _row("Buffer length:",    self._spin_buf_len)
        _row("Update every N:",   self._spin_upd_n)
        _row("HPS harmonics:",    self._spin_harmonics)

        for sp in [self._spin_lp_cutoff, self._spin_buf_len,
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

    def _on_param_changed(self):
        self._calc.lp_cutoff_hz  = self._spin_lp_cutoff.value()
        self._calc.buf_len       = self._spin_buf_len.value()
        self._calc.update_n      = self._spin_upd_n.value()
        self._calc.hps_harmonics = self._spin_harmonics.value()
        self._calc.reset()
        self._update_status_indicator()

    def _reset_to_defaults(self):
        for sp, attr in [(self._spin_lp_cutoff, 'FW_LP_CUTOFF_HZ'),
                         (self._spin_buf_len,   'FW_BUF_LEN'),
                         (self._spin_upd_n,     'FW_UPDATE_N'),
                         (self._spin_harmonics, 'FW_HPS_HARMONICS')]:
            sp.blockSignals(True)
            sp.setValue(getattr(HR3TestCalc, attr))
            sp.blockSignals(False)
        self._calc.reset_to_defaults()
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
        rows_ir_sub = []
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
                        if len(parts) < 20 or parts[0] != '$M1':
                            continue
                        ts_us  = float(parts[2])
                        ir_sub = float(parts[8])
                        hr_fw  = float(parts[18])
                        sqi_fw = float(parts[19])
                    else:
                        if len(row) < 22:
                            continue
                        lib_id = row[2].strip()
                        if lib_id not in ('M1', '$M1'):
                            continue
                        offset = 3
                        ts_us  = float(row[offset + 1])
                        ir_sub = float(row[offset + 7])
                        hr_fw  = float(row[offset + 17])
                        sqi_fw = float(row[offset + 18])
                    rows_ts_us.append(ts_us)
                    rows_ir_sub.append(ir_sub)
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
        self._calc.lp_cutoff_hz  = self._spin_lp_cutoff.value()
        self._calc.buf_len       = self._spin_buf_len.value()
        self._calc.update_n      = self._spin_upd_n.value()
        self._calc.hps_harmonics = self._spin_harmonics.value()
        self._calc.reset()

        nan = float('nan')
        n = len(rows_ir_sub)
        t0 = ts_arr[0]
        arr_t      = (ts_arr - t0) / 1e6
        arr_hr_fw  = np.array(rows_hr_fw)
        arr_sqi_fw = np.array(rows_sqi_fw)
        arr_hr_py  = np.full(n, nan)
        arr_sqi_py = np.full(n, nan)

        for i, ir in enumerate(rows_ir_sub):
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
        self._calc.reset()
        self.statusBar().showMessage(_MOUSE_HINT)
        for c in [self.curve_fft, self.curve_hps, self.curve_filt,
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
        filename = f"hr3test_{now_str}.csv"
        hr_fw  = np.array(self._buf_hr_fw);  hr_py  = np.array(self._buf_hr_py)
        sqi_fw = np.array(self._buf_sqi_fw); sqi_py = np.array(self._buf_sqi_py)
        try:
            with open(filename, 'w') as f:
                f.write(f"# HR3TEST export — {datetime.datetime.now()}\n")
                f.write(f"# lp_cutoff={self._calc.lp_cutoff_hz:.1f} Hz, "
                        f"buf={self._calc.buf_len}, update_n={self._calc.update_n}, "
                        f"hps_harmonics={self._calc.hps_harmonics}\n")
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

    def update_plots(self, data_ir_sub, data_hr3, data_hr3_sqi,
                     data_timestamp_us, data_sample_counter):
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
            ir    = float(data_ir_sub[i])
            hr_f  = float(data_hr3[i])
            sqi_f = float(data_hr3_sqi[i])
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
        py_v = [_lv(arr_hr_py), _lv(arr_sp), self._calc.last_peak_freq]
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

    def _refresh_hr_plots(self, t, hr_fw, hr_py, delta, sqi_fw, sqi_py):
        self.curve_hr_fw.setData(t, hr_fw)
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
        freqs = self._calc.last_freqs
        spec  = self._calc.last_spectrum
        hps   = self._calc.last_hps
        if len(freqs) > 0 and len(spec) > 0:
            self.curve_fft.setData(freqs, spec)
            self.curve_hps.setData(freqs, hps)
            peak = self._calc.last_peak_freq
            if peak > 0:
                self._peak_line.setValue(peak)
                hr_at_peak = peak * 60.0
                sqi_at_peak = self._calc.hr_sqi
                self.p_fft.setTitle(
                    f"<b style='color:#00CCFF'>FFT + <span style='color:#FF8800'>HPS</span></b>"
                    f"  <span style='color:#FFDD44'>peak={peak:.3f} Hz \u2192 {hr_at_peak:.1f} bpm"
                    f"  SQI={sqi_at_peak:.3f}</span>")

    def _refresh_filt_plot(self, t_hr):
        filt = self._calc.last_filtered_buf
        if len(filt) > 0 and len(t_hr) > 0:
            t_end = t_hr[-1]
            fs = self._calc._fs if self._calc._fs > 0 else HR3TestCalc.FW_FS
            filt_t = t_end - (len(filt) - 1 - np.arange(len(filt))) / fs
            self.curve_filt.setData(filt_t, filt)

    def closeEvent(self, event):
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("HR3TestWindow/geometry", self.saveGeometry())
        if self.main_monitor is not None:
            self.main_monitor.btn_hr3test.setChecked(False)
            self.main_monitor.hr3test_window = None
        super().closeEvent(event)


class TimingWindow(QtWidgets.QMainWindow):
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
        self.setWindowTitle("TIMING — CPU Budget & Load")
        geom = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).value("TimingWindow/geometry")
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

        # Section header style
        _hdr_style = "background: #1E2E3E; color: #88BBDD; font-size: 11px; font-weight: bold;"

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
            "Remaining stack of the mow_afe4490 FreeRTOS task (Task A), in 4-byte words "
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

    def update_timing(self, hr1_mean, hr1_max, hr2fp_mean, hr2fp_max,
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
        "mow_afe4490": "mow_afe4490 (Task A)",
        "mow_hr2":     "mow_hr2 (Task B)",
        "mow_hr3":     "mow_hr3 (Task C)",
    }

    def update_tasks(self, tasks):
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
        QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat).setValue("TimingWindow/geometry", self.saveGeometry())
        parent = self.parent()
        if parent is not None and hasattr(parent, 'btn_timing'):
            parent.btn_timing.setChecked(False)
            parent.timing_window = None
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

        pg.setConfigOptions(antialias=True)

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

        # Stateful mow biquad filter state
        self._mow_zi         = None   # biquad state (2 floats)
        self._mow_filt_buf   = deque([0.0] * WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self._last_sample_cnt = None
        self._mow_fs_cached  = None
        self._mow_ba_cached  = None   # cached (b, a) coefficients — recomputed only when fs changes

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
    def _mow_biquad_coeffs(fs, f_low, f_high):
        """Replicate mow_afe4490::_recalc_biquad() exactly (bilinear transform)."""
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

        # Plot 2A: mow_afe4490 biquad — stateful, processes only new samples
        mow_filtered = None
        if high_norm < 1.0:
            try:
                # Recompute coefficients only when fs changes
                if fs != self._mow_fs_cached or self._mow_ba_cached is None:
                    self._mow_ba_cached = self._mow_biquad_coeffs(fs, 0.5, 3.7)
                    self._mow_fs_cached = fs
                    self._mow_zi = None   # force filter reset on coefficient change
                b, a = self._mow_ba_cached

                cur_cnt = int(sample_counter_data[-1])
                reset = self._mow_zi is None or self._last_sample_cnt is None

                if not reset:
                    n_new = (cur_cnt - self._last_sample_cnt) // 10  # SERIAL_DOWNSAMPLING_RATIO=10
                    if n_new <= 0 or n_new > len(data):
                        reset = True

                if reset:
                    # First call or anomaly: warm up on full buffer
                    zi_init = signal.lfilter_zi(b, a) * data[0]
                    full_out, self._mow_zi = signal.lfilter(b, a, data, zi=zi_init)
                    self._mow_filt_buf = deque(full_out, maxlen=WINDOW_SIZE)
                else:
                    new_samples = data[-n_new:]
                    new_out, self._mow_zi = signal.lfilter(b, a, new_samples, zi=self._mow_zi)
                    self._mow_filt_buf.extend(new_out)

                self._last_sample_cnt = cur_cnt
                mow_filtered = np.array(self._mow_filt_buf)
                self.curve_2a.setData(mow_filtered)
            except Exception:
                pass

        # Plots 4 & 5: autocorrelation-based HR, refreshed at 5 Hz
        self._hr_refresh_counter += 1
        refresh_every = max(1, int(round(fs / 5.0)))
        if self._hr_refresh_counter >= refresh_every and mow_filtered is not None:
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

            # Plot 2B: xcorr_v1 on mow BPF
            if len(mow_filtered) >= needed:
                try:
                    r = _estimate_hr_xcorr_v1(mow_filtered[-needed:], fs, max_lag_n)
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

            # Plot 2C: autocorr_v2 on mow BPF (single vector, only window_n samples)
            if len(mow_filtered) >= window_n:
                try:
                    r = _estimate_hr_autocorr_v2(mow_filtered[-window_n:], fs, max_lag_n)
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
    """Floating window with all PPG/SpO2/HR plots and RED/IR channel checkboxes."""

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
        self.check_red_raw.setChecked(s.value("PPGPlotsWindow/check_red_raw", False, type=bool))
        self.check_red_amb.setChecked(s.value("PPGPlotsWindow/check_red_amb", False, type=bool))
        self.check_red_sub.setChecked(s.value("PPGPlotsWindow/check_red_sub", True,  type=bool))
        self.check_ir_raw.setChecked( s.value("PPGPlotsWindow/check_ir_raw",  False, type=bool))
        self.check_ir_amb.setChecked( s.value("PPGPlotsWindow/check_ir_amb",  False, type=bool))
        self.check_ir_sub.setChecked( s.value("PPGPlotsWindow/check_ir_sub",  True,  type=bool))

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

        lbl_red = QtWidgets.QLabel("RED")
        lbl_red.setStyleSheet("color: #FF4444; font-weight: 800; font-size: 20px; margin-top: 10px;")
        sidebar.addWidget(lbl_red)
        self.check_red_raw  = create_check("RED (raw)",    "#FFFFFF", False)
        self.check_red_amb  = create_check("Ambient RED",  "#00FFFF", False)
        self.check_red_sub  = create_check("RED (clean)",  "#FF8888", True)
        self.check_red_raw.setToolTip(_make_tooltip(
            "RED (raw)",
            "Raw RED LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: RED in the M1 frame."))
        self.check_red_amb.setToolTip(_make_tooltip(
            "Ambient RED",
            "Ambient light sampled during the RED LED off period (aled2). "
            "Represents environmental light interference on the RED channel."))
        self.check_red_sub.setToolTip(_make_tooltip(
            "RED (clean)",
            "RED minus ambient: RED − RED_Amb. Ambient-subtracted RED signal. "
            "Primary input to the SpO2 algorithm. Field: RED_Sub."))
        for w in (self.check_red_raw, self.check_red_amb, self.check_red_sub):
            sidebar.addWidget(w)

        lbl_ir = QtWidgets.QLabel("IR")
        lbl_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 20px;")
        sidebar.addWidget(lbl_ir)
        self.check_ir_raw  = create_check("IR (raw)",     "#FFFFFF", False)
        self.check_ir_amb  = create_check("Ambient IR",   "#00FFFF", False)
        self.check_ir_sub  = create_check("IR (clean)",   "#88CCFF", True)
        self.check_ir_raw.setToolTip(_make_tooltip(
            "IR (raw)",
            "Raw IR LED ADC reading directly from the AFE4490. "
            "Includes ambient light contamination. Field: IR in the M1 frame."))
        self.check_ir_amb.setToolTip(_make_tooltip(
            "Ambient IR",
            "Ambient light sampled during the IR LED off period (aled1). "
            "Represents environmental light interference on the IR channel."))
        self.check_ir_sub.setToolTip(_make_tooltip(
            "IR (clean)",
            "IR minus ambient: IR − IR_Amb. Ambient-subtracted IR signal. "
            "Primary input to the HR algorithms (HR1, HR2, HR3). Field: IR_Sub."))
        for w in (self.check_ir_raw, self.check_ir_amb, self.check_ir_sub):
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

        # Top two rows: RED and IR in a GraphicsLayoutWidget
        self.graphics_layout = pg.GraphicsLayoutWidget()
        plots_vbox.addWidget(self.graphics_layout, stretch=1)

        self.p1 = self.graphics_layout.addPlot(title="<b style='color:#FF4444'>RED</b>")
        self.curve_red      = self.p1.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="RED (Raw)")
        self.curve_red_amb  = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient RED")
        self.curve_red_sub  = self.p1.plot(pen=pg.mkPen('#FF8888', width=1.5), name="RED (Clean)")
        self.p1.showGrid(x=True, y=True, alpha=0.3)

        self.graphics_layout.nextRow()

        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>IR</b>")
        self.curve_ir      = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="IR (Raw)")
        self.curve_ir_amb  = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient IR")
        self.curve_ir_sub  = self.p2.plot(pen=pg.mkPen('#88CCFF', width=1.5), name="IR (Clean)")
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
        self.check_red_raw.stateChanged.connect(lambda: self.curve_red.setVisible(self.check_red_raw.isChecked()))
        self.check_red_amb.stateChanged.connect(lambda: self.curve_red_amb.setVisible(self.check_red_amb.isChecked()))
        self.check_red_sub.stateChanged.connect(lambda: self.curve_red_sub.setVisible(self.check_red_sub.isChecked()))
        self.check_ir_raw.stateChanged.connect( lambda: self.curve_ir.setVisible(self.check_ir_raw.isChecked()))
        self.check_ir_amb.stateChanged.connect( lambda: self.curve_ir_amb.setVisible(self.check_ir_amb.isChecked()))
        self.check_ir_sub.stateChanged.connect( lambda: self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked()))

        self.curve_red.setVisible(False)
        self.curve_red_amb.setVisible(False)
        self.curve_red_sub.setVisible(True)
        self.curve_ir.setVisible(False)
        self.curve_ir_amb.setVisible(False)
        self.curve_ir_sub.setVisible(True)

        outer.addWidget(hint)

    def update_plots(self, data_ppg, data_hr1, data_hr2, data_hr3,
                     data_spo2, data_spo2_sqi, data_spo2_r,
                     data_hr1_sqi, data_hr2_sqi, data_hr3_sqi,
                     data_red, data_ir,
                     data_red_amb, data_ir_amb, data_red_sub, data_ir_sub):
        self.p_spo2.setTitle(
            f"<b style='color:#44FF88'>SpO2: {data_spo2[-1]:.1f} %</b>"
            f" &nbsp; <b style='color:#888888'>SQI: {data_spo2_sqi[-1]:.2f}</b>"
            f" &nbsp; <b style='color:#AAAAAA'>R: {data_spo2_r[-1]:.4f}</b>")
        self.p_hr.setTitle(
            f"<b style='color:#FFDD44'>HR1: {data_hr1[-1]:.1f}</b><b style='color:#888888'> [{data_hr1_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#FF4444'>HR2: {data_hr2[-1]:.1f}</b><b style='color:#888888'> [{data_hr2_sqi[-1]:.2f}]</b>"
            f" &nbsp; <b style='color:#00CCFF'>HR3: {data_hr3[-1]:.1f}</b><b style='color:#888888'> [{data_hr3_sqi[-1]:.2f}]</b>"
            f" <b style='color:#AAAAAA'>bpm</b>")
        self.curve_ppg.setData(list(data_ppg)[-PPG_WINDOW_SIZE:])
        self.curve_spo2.setData(list(data_spo2))
        self.curve_hr1.setData(list(data_hr1))
        self.curve_hr2.setData(list(data_hr2))
        self.curve_hr3.setData(list(data_hr3))
        self.curve_red.setData(list(data_red))
        self.curve_ir.setData(list(data_ir))
        self.curve_red_amb.setData(list(data_red_amb))
        self.curve_ir_amb.setData(list(data_ir_amb))
        self.curve_red_sub.setData(list(data_red_sub))
        self.curve_ir_sub.setData(list(data_ir_sub))

    def closeEvent(self, event):
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        s.setValue("PPGPlotsWindow/geometry",    self.saveGeometry())
        s.setValue("PPGPlotsWindow/check_red_raw",  self.check_red_raw.isChecked())
        s.setValue("PPGPlotsWindow/check_red_amb",  self.check_red_amb.isChecked())
        s.setValue("PPGPlotsWindow/check_red_sub",  self.check_red_sub.isChecked())
        s.setValue("PPGPlotsWindow/check_ir_raw",   self.check_ir_raw.isChecked())
        s.setValue("PPGPlotsWindow/check_ir_amb",   self.check_ir_amb.isChecked())
        s.setValue("PPGPlotsWindow/check_ir_sub",   self.check_ir_sub.isChecked())
        if self.main_monitor is not None:
            self.main_monitor.btn_ppgplots.setChecked(False)
            self.main_monitor.ppgplots_window = None
        super().closeEvent(event)


class SerialComWindow(QtWidgets.QWidget):
    """Floating window with the raw serial stream console."""

    SERIAL_HEADER = (
        f"{'Timestamp_PC':<15},{'Df_us':>5},"
        "LibID,SmpCnt,Ts_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,PPG,SpO2,SpO2_SQI,SpO2_R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI"
    )

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
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
        layout.addWidget(self.header_label)

        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console.setFont(QtGui.QFont("Consolas", 9))
        self.console.setStyleSheet("""
            background-color: #000000; color: #D09000;
            border: 1px solid #FFAA00; padding: 5px;
        """)
        layout.addWidget(self.console)

    def append_line(self, line):
        """Append a single line immediately (for status/error messages)."""
        self.console.appendPlainText(line)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def append_lines(self, lines):
        """Batch append a list of lines (called from update_data loop)."""
        if not lines:
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

    CSV format (compatible with mow_offline_runner):
      - Pre-capture notes as '# ...' lines before the column header.
      - Mandatory columns: RED, IR, RED_Amb, IR_Amb, RED_Sub, IR_Sub.
      - Optional FW columns: FW_SpO2, FW_HR1, FW_HR2, FW_HR3 (offline_runner names).
      - Post-capture notes as '# ...' lines after the last data row.
    """

    # (display label, csv column name, M1-parts index after '$', mandatory)
    # M1 parts layout (after stripping '$' and checksum):
    #   [0]=LibID  [1]=SmpCnt  [2]=Ts_us
    #   [3]=RED  [4]=IR  [5]=RED_Amb  [6]=IR_Amb  [7]=RED_Sub  [8]=IR_Sub
    #   [9]=PPG  [10]=SpO2  [11]=SpO2_SQI  [12]=SpO2_R  [13]=PI
    #   [14]=HR1  [15]=HR1_SQI  [16]=HR2  [17]=HR2_SQI  [18]=HR3  [19]=HR3_SQI
    _COLS = [
        ("SmpCnt",   "FW_SmpCnt",  1,  False),
        ("Ts_us",    "FW_Ts_us",   2,  False),
        ("RED",      "RED",        3,  True),
        ("IR",       "IR",         4,  True),
        ("RED_Amb",  "RED_Amb",    5,  True),
        ("IR_Amb",   "IR_Amb",     6,  True),
        ("RED_Sub",  "RED_Sub",    7,  True),
        ("IR_Sub",   "IR_Sub",     8,  True),
        ("PPG",      "FW_PPG",      9,  False),
        ("SpO2",     "FW_SpO2",    10,  False),
        ("SpO2_SQI", "FW_SpO2_SQI", 11,  False),
        ("SpO2_R",   "FW_SpO2_R",  12,  False),
        ("PI",       "FW_PI",      13,  False),
        ("HR1",      "FW_HR1",     14,  False),
        ("HR1_SQI",  "FW_HR1_SQI", 15,  False),
        ("HR2",      "FW_HR2",     16,  False),
        ("HR2_SQI",  "FW_HR2_SQI", 17,  False),
        ("HR3",      "FW_HR3",     18,  False),
        ("HR3_SQI",  "FW_HR3_SQI", 19,  False),
    ]

    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("Lab Capture")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0; font-size: 28px;")
        self._setup_ui()
        self._load_settings()

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
            "5000 samples = 10 seconds at 500 Hz."))
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
        default_dir = os.path.dirname(os.path.abspath(__file__))
        self._edit_dir.setText(
            s.value("LabCaptureWindow/output_dir", default_dir, type=str))
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
            out_dir = os.path.dirname(os.path.abspath(__file__))
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


class PPGMonitor(QtWidgets.QMainWindow):
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
        
        # Configuración Ventana Principal
        self.setWindowTitle("AFE4490 Advanced Monitor (by Medical Open World)")
        self.resize(1800, 1100)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")

        # Estructuras de Datos
        self.data_lib_id = deque(["?"]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_sample_counter = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_timestamp_us = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ppg = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr1 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir  = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir_amb = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red_amb = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr2      = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr3      = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2_r   = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_pi       = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2_sqi = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr1_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr2_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr3_sqi  = deque([0.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)

        self.is_paused = False
        self.last_time = None
        self.active_lib = "MOW"   # must match default in main.cpp (start_mow)
        self.frame_mode = "M1"    # must match default in main.cpp (MowFrameMode::FULL)
        
        self.is_saving = False
        self.save_file = None
        self.save_file_chk = None
        self._chk_filename = None
        if save_chk:
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._chk_filename = f"ppg_chk_{now_str}.csv"
            try:
                self.save_file_chk = open(self._chk_filename, "w", buffering=1)
                self.save_file_chk.write("Timestamp_PC,Diff_us_PC,CHK_OK,RawFrame\n")
                print(f"[save-chk] Saving to {self._chk_filename}")
                if save_chk_duration > 0:
                    QtCore.QTimer.singleShot(save_chk_duration * 1000, self._auto_close_chk)
            except Exception as e:
                print(f"[save-chk] Error opening file: {e}")
        self.ppgplots_window  = None
        self.serialcom_window = None
        self.hrlab_window     = None
        self.spo2lab_window   = None
        self.hr3lab_window    = None
        self.spo2test_window  = None
        self.hr1test_window   = None
        self.hr1test_calc     = HR1TestCalc()
        self.hr2test_window   = None
        self.hr3test_window   = None
        self.timing_window    = None
        self._pending_tasks   = []   # accumulates $TASK frames until $TASKS_END
        # Render throttle rates (all relative to ~50 Hz update_data calls)
        self._PPGPLOTS_REFRESH_EVERY  = 2   # 25 Hz — smooth plot animation
        self._SUBWIN_REFRESH_EVERY    = 5   # 10 Hz — SpO2/HR3 change slowly
        self._SPOST_REFRESH_EVERY     = 5   # 10 Hz
        self._HR1TEST_REFRESH_EVERY   = 5   # 10 Hz
        self._HR2TEST_REFRESH_EVERY   = 5   # 10 Hz
        self._HR3TEST_REFRESH_EVERY   = 5   # 10 Hz
        self._ppgplots_refresh_counter = 0
        self._hrlab_refresh_counter    = 0
        self._spo2lab_refresh_counter  = 0
        self._hr3lab_refresh_counter   = 0
        self._spo2test_refresh_counter = 0
        self._hr1test_refresh_counter  = 0
        self._hr2test_refresh_counter  = 0
        self._hr3test_refresh_counter  = 0
        self._decim_counter = 0
        self.hr3_calc = HRFFTCalc()

        # ── Stats table buffers (reset every N seconds) ───────────────────────
        self._STATS_SIGNALS = [
            # (display_name, data_attr, tooltip_description)
            # Order mirrors the $M1/$P1 serial frame. Row indices: HR1=11, HR2=13, HR3=15.
            ("RED",      "data_red",      "Raw RED LED signal (LED2, 660 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts."),
            ("IR",       "data_ir",       "Raw IR LED signal (LED1, ~880 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts."),
            ("RED_Amb",  "data_red_amb",  "Ambient RED channel (ALED2): sampled with RED LED off. Represents environmental red-light interference. Units: ADC counts."),
            ("IR_Amb",   "data_ir_amb",   "Ambient IR channel (ALED1): sampled with IR LED off. Represents environmental IR interference. Units: ADC counts."),
            ("RED_Sub",  "data_red_sub",  "Ambient-subtracted RED signal: LED2 − ALED2. Removes DC ambient component. Used as input for SpO2 AC/DC decomposition. Units: ADC counts."),
            ("IR_Sub",   "data_ir_sub",   "Ambient-subtracted IR signal: LED1 − ALED1. Removes DC ambient component. Main input for HR1, HR2, HR3 and SpO2 algorithms. Units: ADC counts."),
            ("PPG",      "data_ppg",      "Filtered PPG signal (IR channel). IIR DC removal τ=1.6 s → moving-average low-pass 5 Hz → negated. Units: ADC counts."),
            ("SpO2",     "data_spo2",     "Blood oxygen saturation computed by firmware (mow_afe4490). Formula: SpO2 = a − b·R. Range: 70–100 %. Clamped to 100 % if within 3 % above; invalid if >103 %."),
            ("SpO2_SQI", "data_spo2_sqi", "SpO2 Signal Quality Index [0–1]. Based on Perfusion Index (PI): SQI = clamp((PI − 0.5) / (2.0 − 0.5), 0, 1). PI < 0.5 % → 0 (no contact or very weak signal). PI ≥ 2.0 % → 1 (full quality). Forced to 0 if SpO2 is outside valid range. Thresholds per Nellcor/Masimo clinical reference."),
            ("SpO2_R",   "data_spo2_r",   "R ratio used for SpO2 calculation: R = (AC_red/DC_red) / (AC_ir/DC_ir). Dimensionless. Useful for sensor calibration (R-curve)."),
            ("PI",       "data_pi",       "Perfusion Index: (AC_ir / DC_ir) × 100 [%]. Measures signal strength / perfusion quality. Typical range: 0.02–20 %. Low PI (<0.3 %) indicates weak signal or poor perfusion."),
            ("HR1",      "data_hr1",      "Heart rate from algorithm HR1 (adaptive threshold peak detection). Threshold = 0.6 × running_max; refractory 185 ms. Average of last 5 RR intervals. Units: BPM. Valid range: 25–300 BPM."),
            ("HR1_SQI",  "data_hr1_sqi",  "HR1 Signal Quality Index [0–1]. Coefficient of variation (CV = std/mean) of the 5 most recent RR intervals: SQI = clamp(1 − CV/0.15, 0, 1). CV = 0 (perfectly regular rhythm) → 1. CV ≥ 15 % (arrhythmia or motion artefact) → 0. Forced to 0 if fewer than 5 intervals detected or HR1 outside valid range."),
            ("HR2",      "data_hr2",      "Heart rate from algorithm HR2 (normalized autocorrelation). BPF 0.5–5 Hz → decimate ×10 → 400-sample buffer → autocorr every 0.5 s → first local max ≥ 0.5 → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM."),
            ("HR2_SQI",  "data_hr2_sqi",  "HR2 Signal Quality Index [0–1]. Normalised autocorrelation value at the dominant RR lag: SQI = acorr[peak_lag] / acorr[0]. High value = strong, clear periodicity. Minimum threshold 0.5: below this no HR2 is reported and SQI = 0. Forced to 0 if buffer not full or HR2 outside valid range."),
            ("HR3",      "data_hr3",      "Heart rate from algorithm HR3 (FFT + HPS, computed in firmware). LP 10 Hz → decimate ×10 → 512-sample Hann window → FFT → Harmonic Product Spectrum (harmonics 2–3) → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM."),
            ("HR3_SQI",  "data_hr3_sqi",  "HR3 Signal Quality Index [0–1]. Spectral concentration of fundamental power at the HPS peak bin vs. search range: SQI = (P[peak]/ΣP[k] − 1/N) / (1 − 1/N). Pure dominant tone → SQI ≈ 1. Diffuse or noisy spectrum → SQI ≈ 0. Forced to 0 if buffer not full or HR3 outside valid range."),
        ]
        self._stats_buf = {name: [] for name, _, __ in self._STATS_SIGNALS}
        
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
            "Select the ESP32-S3 (in3ator V15) port — usually COM15."))
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

        self.btn_port_connect = QtWidgets.QPushButton("CONNECT")
        self.btn_port_connect.setStyleSheet(
            "background-color: #1A3A1A; color: #44FF44; font-size: 18px; "
            "font-weight: bold; padding: 4px; border: 1px solid #44FF44; border-radius: 4px;")
        self.btn_port_connect.clicked.connect(
            lambda: self._connect_serial(self.combo_port.currentText()))
        self.btn_port_connect.setToolTip(_make_tooltip(
            "CONNECT / DISCONNECT",
            "Open or close the serial connection to the selected COM port. "
            "921600 baud, 8N1. Reconnect hot-swap: disconnect and reconnect without restarting."))
        self.sidebar_layout.addWidget(self.btn_port_connect)

        self.btn_reset_esp = QtWidgets.QPushButton("RESET\nESP32")
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

        self.btn_pause = QtWidgets.QPushButton("PAUSE\nCAPTURE")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setToolTip(_make_tooltip(
            "PAUSE CAPTURE",
            "Pause or resume live data display. The serial port stays open and data "
            "keeps flowing; only the UI plots and stats are frozen."))
        self.sidebar_layout.addWidget(self.btn_pause)

        self.btn_save = QtWidgets.QPushButton("SAVE\nDATA")
        self.btn_save.setCheckable(True)
        self.btn_save.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.toggle_save)
        self.btn_save.setToolTip(_make_tooltip(
            "SAVE DATA",
            "Toggle saving decimated data to a timestamped CSV file. "
            "Records at the display rate (500 Hz ÷ DECIMATION). "
            "Filename: ppg_data_<timestamp>.csv"))
        self.sidebar_layout.addWidget(self.btn_save)

        self.btn_lab_capture = QtWidgets.QPushButton("CAPTURE\nLAB")
        self.btn_lab_capture.setCheckable(True)
        self.btn_lab_capture.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_lab_capture.clicked.connect(self.toggle_lab_capture)
        self.btn_lab_capture.setToolTip(_make_tooltip(
            "CAPTURE LAB",
            "Open the Lab Capture window to configure and trigger controlled 500 Hz "
            "CSV captures for offline algorithm analysis."))
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
            "Lab Capture always records at full 500 Hz regardless of this setting."))
        self.sidebar_layout.addWidget(self.spin_decim)

        self.sidebar_layout.addSpacing(20)

        label_library = QtWidgets.QLabel("LIBRARY")
        label_library.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_library)

        self.btn_lib_mow = QtWidgets.QPushButton("MOW")
        self.btn_lib_pc  = QtWidgets.QPushButton("PROTOCENTRAL")
        self.btn_lib_mow.clicked.connect(lambda: self._send_lib_cmd('m'))
        self.btn_lib_pc.clicked.connect(lambda:  self._send_lib_cmd('p'))
        self.btn_lib_mow.setToolTip(_make_tooltip(
            "LIBRARY: MOW",
            "Switch the firmware to use the custom mow_afe4490 library (lib/mow_afe4490). "
            "Sends 'm' command over serial. The button stays highlighted while MOW is active."))
        self.btn_lib_pc.setToolTip(_make_tooltip(
            "LIBRARY: PROTOCENTRAL",
            "Switch the firmware to use the ProtoCentral AFE4490 Arduino library. "
            "Sends 'p' command over serial. The button stays highlighted while PROTOCENTRAL is active."))
        self.sidebar_layout.addWidget(self.btn_lib_mow)
        self.sidebar_layout.addWidget(self.btn_lib_pc)
        self._update_lib_button()

        self.sidebar_layout.addSpacing(10)

        label_frame = QtWidgets.QLabel("FRAME MODE")
        label_frame.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_frame)

        self.btn_frame_m1 = QtWidgets.QPushButton("$M1  FULL")
        self.btn_frame_m2 = QtWidgets.QPushButton("$M2  RAW")
        self.btn_frame_m1.clicked.connect(lambda: self._send_frame_cmd("M1"))
        self.btn_frame_m2.clicked.connect(lambda: self._send_frame_cmd("M2"))
        self.btn_frame_m1.setToolTip(_make_tooltip(
            "$M1 — FULL frame",
            "Full frame mode: 19 fields — SmpCnt, Ts_us, RED, IR, RED_Amb, IR_Amb, RED_Sub, IR_Sub, "
            "PPG, SpO2, SpO2_SQI, SpO2_R, PI, HR1, HR1_SQI, HR2, HR2_SQI, HR3, HR3_SQI + checksum. "
            "Use for algorithm analysis and calibration."))
        self.btn_frame_m2.setToolTip(_make_tooltip(
            "$M2 — RAW frame",
            "Raw frame mode: only raw ADC values — SmpCnt, Ts_us, RED, IR, RED_Amb, IR_Amb + checksum. "
            "Lower bandwidth. Use when only raw signal capture is needed."))
        self.sidebar_layout.addWidget(self.btn_frame_m1)
        self.sidebar_layout.addWidget(self.btn_frame_m2)
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
            "Displays RED/IR raw and filtered signals, PPG, SpO2 and HR curves in real time. "
            "Throttled to 25 Hz to keep CPU load low."))
        self.sidebar_layout.addWidget(self.btn_ppgplots)

        self.btn_serialcom = QtWidgets.QPushButton("SERIALCOM")
        self.btn_serialcom.setCheckable(True)
        self.btn_serialcom.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_serialcom.clicked.connect(self.toggle_serialcom)
        self.btn_serialcom.setToolTip(_make_tooltip(
            "SERIALCOM",
            "Show or hide the Serial Console window. "
            "Displays raw serial frames received from the ESP32-S3 and the CSV header."))
        self.sidebar_layout.addWidget(self.btn_serialcom)

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
            "Displays the normalised autocorrelation (HR2) used to detect the dominant pulse period."))
        self.sidebar_layout.addWidget(self.btn_hrlab)

        self.btn_hr3lab = QtWidgets.QPushButton("HR3LAB")
        self.btn_hr3lab.setCheckable(True)
        self.btn_hr3lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr3lab.clicked.connect(self.toggle_hr3lab)
        self.btn_hr3lab.setToolTip(_make_tooltip(
            "HR3LAB",
            "Show or hide the HR3 FFT/HPS analysis window. "
            "Displays FFT spectrum, Harmonic Product Spectrum and HR1/HR2/HR3 comparison in real time. "
            "HR3 uses a 512-sample Hann window + rfft + HPS on the IR_Sub-signal at 50 Hz."))
        self.sidebar_layout.addWidget(self.btn_hr3lab)

        self.btn_spo2lab = QtWidgets.QPushButton("SPO2LAB")
        self.btn_spo2lab.setCheckable(True)
        self.btn_spo2lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_spo2lab.clicked.connect(self.toggle_spo2lab)
        self.btn_spo2lab.setToolTip(_make_tooltip(
            "SPO2LAB",
            "Show or hide the SpO2 Calibration Lab window. "
            "Compare firmware vs local SpO2/R-ratio, capture calibration points and "
            "run linear regression to obtain a·b coefficients for the SpO2 = a − b·R formula."))
        self.sidebar_layout.addWidget(self.btn_spo2lab)

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
            "See mow_afe4490_spec.md §5.1 and §8.2."))
        self.sidebar_layout.addWidget(self.btn_spo2test)

        self.btn_hr1test = QtWidgets.QPushButton("HR1TEST")
        self.btn_hr1test.setCheckable(True)
        self.btn_hr1test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr1test.clicked.connect(self.toggle_hr1test)
        self.btn_hr1test.setToolTip(_make_tooltip(
            "HR1TEST",
            "Post-implementation verification window for the HR1 algorithm (threshold peak detection). "
            "Python mirror runs at 500 Hz (full serial rate) in live mode. "
            "See mow_afe4490_spec.md §5.2 and §8.2."))
        self.sidebar_layout.addWidget(self.btn_hr1test)

        self.btn_hr2test = QtWidgets.QPushButton("HR2TEST")
        self.btn_hr2test.setCheckable(True)
        self.btn_hr2test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr2test.clicked.connect(self.toggle_hr2test)
        self.btn_hr2test.setToolTip(_make_tooltip(
            "HR2TEST",
            "Post-implementation verification window for the HR2 algorithm (autocorrelation). "
            "Mirror runs at the decimated rate. See mow_afe4490_spec.md §5.3 and §8.2."))
        self.sidebar_layout.addWidget(self.btn_hr2test)

        self.btn_hr3test = QtWidgets.QPushButton("HR3TEST")
        self.btn_hr3test.setCheckable(True)
        self.btn_hr3test.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr3test.clicked.connect(self.toggle_hr3test)
        self.btn_hr3test.setToolTip(_make_tooltip(
            "HR3TEST",
            "Post-implementation verification window for the HR3 algorithm (FFT + HPS). "
            "Mirror runs at the decimated rate. See mow_afe4490_spec.md §5.4 and §8.2."))
        self.sidebar_layout.addWidget(self.btn_hr3test)

        self.btn_timing = QtWidgets.QPushButton("TIMING")
        self.btn_timing.setCheckable(True)
        self.btn_timing.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_timing.clicked.connect(self.toggle_timing)
        self.btn_timing.setToolTip(_make_tooltip(
            "TIMING — Algorithm CPU Budget",
            "Opens the timing diagnostics window. Shows per-algorithm mean/max execution time "
            "(µs) and remaining FreeRTOS stack, parsed from $TIMING frames emitted by the firmware "
            "every ~5 s. Requires MOW_TIMING_STATS=1 in firmware. "
            "Cycle budget = 2000 µs (1 sample period at 500 Hz)."))
        self.sidebar_layout.addWidget(self.btn_timing)

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
            "(Last / Mean / Min / Max). Range: 1–60 s."))
        stats_header.addWidget(stats_interval_lbl)
        stats_header.addWidget(self.spin_stats_interval)
        stats_vbox.addLayout(stats_header)

        self.stats_table = QtWidgets.QTableWidget(len(self._STATS_SIGNALS), 5)
        self.stats_table.setHorizontalHeaderLabels(["Signal", "Last", "Mean", "Min", "Max"])
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.stats_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.stats_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                background-color: #111111; color: #E0E0E0;
                font-family: monospace; font-size: 28px;
                gridline-color: #2A2A2A; border: none;
            }
            QHeaderView::section {
                background-color: #1E1E2E; color: #AAAAAA;
                font-size: 33px; font-weight: bold;
                padding: 6px; border: 1px solid #2A2A2A;
            }
            QTableWidget::item { padding: 6px 10px; }
        """)
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        for col in range(1, 5):
            self.stats_table.horizontalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
        self.stats_table.verticalHeader().setDefaultSectionSize(40)

        _HR_ROWS  = {11, 13, 15}   # HR1, HR2, HR3
        _MEAN_COL = 2
        _MAROON   = QtGui.QColor("#5C001A")

        for row, (name, _, tooltip) in enumerate(self._STATS_SIGNALS):
            rich_tip = _make_tooltip(name, tooltip)
            item = QtWidgets.QTableWidgetItem(name)
            item.setForeground(QtGui.QColor("#AAAAAA"))
            item.setToolTip(rich_tip)
            self.stats_table.setItem(row, 0, item)
            for col in range(1, 5):
                it = QtWidgets.QTableWidgetItem("---")
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                it.setToolTip(rich_tip)
                if row in _HR_ROWS and col == _MEAN_COL:
                    it.setBackground(_MAROON)
                self.stats_table.setItem(row, col, it)

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
        self._reader_stop = threading.Event()
        self._reader_thread = None

        self._populate_ports()
        self._restore_settings()
        self._connect_serial(self.combo_port.currentText())
            
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(20)
        
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

    def _update_lib_button(self):
        mow_active = (self.active_lib == "MOW")
        self.btn_lib_mow.setStyleSheet(
            self.STYLE_LIB_ACTIVE.format(bg="#3A2A00", fg="#FFAA00", bgh="#4A3800")
            if mow_active else self.STYLE_LIB_INACTIVE)
        self.btn_lib_pc.setStyleSheet(
            self.STYLE_LIB_ACTIVE.format(bg="#3A2A00", fg="#FFAA00", bgh="#4A3800")
            if not mow_active else self.STYLE_LIB_INACTIVE)
        if hasattr(self, 'btn_frame_m1'):
            self._update_frame_button()

    def _update_frame_button(self):
        mow_active = (self.active_lib == "MOW")
        m1_active = (self.frame_mode == "M1")
        for btn, is_active in ((self.btn_frame_m1, m1_active), (self.btn_frame_m2, not m1_active)):
            btn.setEnabled(mow_active)
            btn.setStyleSheet(
                self.STYLE_LIB_ACTIVE.format(bg="#002A3A", fg="#44AAFF", bgh="#003A4A")
                if (mow_active and is_active) else self.STYLE_LIB_INACTIVE)

    def _send_frame_cmd(self, mode):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            return
        self.ser.write(('1' if mode == "M1" else '2').encode())
        self.frame_mode = mode
        self._update_frame_button()
        self.log(f"Frame mode: ${mode}")

    def _send_lib_cmd(self, cmd):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            return
        self.ser.write(cmd.encode())

    def _reset_esp32(self):
        """Hardware-reset the ESP32 via RTS/DTR (ESP-Prog auto-reset circuit)."""
        if not hasattr(self, 'ser') or self.ser is None or not self.ser.is_open:
            self.log("Not connected — cannot reset ESP32")
            return
        try:
            self.ser.dtr = False   # IO0 high → run mode (not bootloader)
            self.ser.rts = True    # EN low  → reset active
            time.sleep(0.1)
            self.ser.rts = False   # EN high → chip boots in run mode
            # DTR stays False: IO0 remains high → normal firmware, not bootloader
            self.log("ESP32 reset triggered (RTS/DTR via ESP-Prog)")
        except Exception as e:
            self.log(f"Reset failed: {e}")

    def _open_hrlab_default(self):
        self.btn_hrlab.setChecked(True)
        self.toggle_hrlab()

    def toggle_hrlab(self):
        if self.btn_hrlab.isChecked():
            self.hrlab_window = HRLabWindow(self)
            self.hrlab_window.show()
        else:
            if self.hrlab_window is not None:
                self.hrlab_window.main_monitor = None  # prevent recursive callback
                self.hrlab_window.close()
                self.hrlab_window = None

    def _open_ppgplots_default(self):
        self.btn_ppgplots.setChecked(True)
        self.toggle_ppgplots()

    def toggle_ppgplots(self):
        if self.btn_ppgplots.isChecked():
            self.ppgplots_window = PPGPlotsWindow(self)
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
            self.serialcom_window = SerialComWindow(self)
            self.serialcom_window.show()
        else:
            if self.serialcom_window is not None:
                self.serialcom_window.main_monitor = None
                self.serialcom_window.close()
                self.serialcom_window = None

    def _open_hr3lab_default(self):
        self.btn_hr3lab.setChecked(True)
        self.toggle_hr3lab()

    def toggle_hr3lab(self):
        if self.btn_hr3lab.isChecked():
            self.hr3lab_window = HR3LabWindow(self)
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
            self.spo2lab_window = SpO2LabWindow(self)
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
            self.spo2test_window = SpO2TestWindow(self)
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
            self.hr1test_window = HR1TestWindow(self)
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
            self.hr2test_window = HR2TestWindow(self)
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
            self.hr3test_window = HR3TestWindow(self)
            self.hr3test_window.show()
        else:
            if self.hr3test_window is not None:
                self.hr3test_window.main_monitor = None
                self.hr3test_window.close()
                self.hr3test_window = None

    def _open_timing_default(self):
        self.btn_timing.setChecked(True)
        self.toggle_timing()

    def toggle_timing(self):
        if self.btn_timing.isChecked():
            self.timing_window = TimingWindow(self)
            self.timing_window.show()
        else:
            if self.timing_window is not None:
                self.timing_window.close()
                self.timing_window = None

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
            f = open(filepath, "w", buffering=1)
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
        # M2 parts layout: [0]=M2 [1]=cnt [2]=RED [3]=IR [4]=RED_Amb [5]=IR_Amb [6]=RED_Sub [7]=IR_Sub
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
            self.btn_pause.setText("RESUME\nCAPTURE")
            self.log("Capture PAUSED")
        else:
            self.btn_pause.setText("PAUSE\nCAPTURE")
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
            filename = f"ppg_data_snap_{now_str}.csv"
            try:
                with open(filename, "w") as f:
                    f.write("LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,PPG,SpO2,SpO2_SQI,SpO2_R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_red[i]},{self.data_ir[i]},{self.data_red_amb[i]},{self.data_ir_amb[i]},{self.data_red_sub[i]},{self.data_ir_sub[i]},{self.data_ppg[i]},{self.data_spo2[i]},{self.data_spo2_sqi[i]},{self.data_spo2_r[i]},{self.data_pi[i]},{self.data_hr1[i]},{self.data_hr1_sqi[i]},{self.data_hr2[i]},{self.data_hr2_sqi[i]},{self.data_hr3[i]},{self.data_hr3_sqi[i]}\n")
                self.log(f"Snapshot saved to {filename}")
            except Exception as e:
                self.log(f"Error saving snapshot: {e}")
        else:
            self.is_saving = self.btn_save.isChecked()
            if self.is_saving:
                self.btn_save.setText("STOP\nRECORDING")
                filename = f"ppg_data_stream_{now_str}.csv"
                try:
                    self.save_file = open(filename, "w")
                    if self.frame_mode == "M2":
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,RED_Amb,IR_Amb,RED_Sub,IR_Sub\n")
                    else:
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,RED,IR,RED_Amb,IR_Amb,RED_Sub,IR_Sub,PPG,SpO2,SpO2_SQI,SpO2_R,PI,HR1,HR1_SQI,HR2,HR2_SQI,HR3,HR3_SQI\n")
                    self.log(f"RECORDING LIVE: {filename}")
                    self.auto_save_timer.start(1000 * 1000)
                except Exception as e:
                    self.log(f"Error opening save file: {e}")
                    self.is_saving = False
                    self.btn_save.setChecked(False)
            else:
                self.auto_save_timer.stop()
                self.btn_save.setText("SAVE\nDATA")
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
        s.setValue("PPGMonitor/combo_port",     self.combo_port.currentText())
        s.setValue("PPGMonitor/ppgplots_open",  self.ppgplots_window  is not None)
        s.setValue("PPGMonitor/serialcom_open", self.serialcom_window is not None)
        s.setValue("PPGMonitor/hrlab_open",     self.hrlab_window     is not None)
        s.setValue("PPGMonitor/spo2lab_open",   self.spo2lab_window   is not None)
        s.setValue("PPGMonitor/hr3lab_open",    self.hr3lab_window    is not None)
        s.setValue("PPGMonitor/spo2test_open",  self.spo2test_window  is not None)
        s.setValue("PPGMonitor/hr1test_open",  self.hr1test_window  is not None)
        s.setValue("PPGMonitor/hr2test_open",  self.hr2test_window  is not None)
        s.setValue("PPGMonitor/hr3test_open",  self.hr3test_window  is not None)
        s.setValue("PPGMonitor/timing_open",      self.timing_window      is not None)
        s.setValue("PPGMonitor/labcapture_open",  self.lab_capture_window is not None)
        # Persist geometry of all open subwindows (survives taskkill; also saved in their closeEvent)
        if self.ppgplots_window  is not None: s.setValue("PPGPlotsWindow/geometry",   self.ppgplots_window.saveGeometry())
        if self.serialcom_window is not None: s.setValue("SerialComWindow/geometry",  self.serialcom_window.saveGeometry())
        if self.hrlab_window     is not None: s.setValue("HRLabWindow/geometry",      self.hrlab_window.saveGeometry())
        if self.spo2lab_window   is not None: s.setValue("SpO2LabWindow/geometry",    self.spo2lab_window.saveGeometry())
        if self.hr3lab_window    is not None: s.setValue("HR3LabWindow/geometry",     self.hr3lab_window.saveGeometry())
        if self.spo2test_window  is not None: s.setValue("SpO2TestWindow/geometry",   self.spo2test_window.saveGeometry())
        if self.hr1test_window   is not None: s.setValue("HR1TestWindow/geometry",    self.hr1test_window.saveGeometry())
        if self.hr2test_window   is not None: s.setValue("HR2TestWindow/geometry",    self.hr2test_window.saveGeometry())
        if self.hr3test_window   is not None: s.setValue("HR3TestWindow/geometry",    self.hr3test_window.saveGeometry())
        if self.timing_window        is not None: s.setValue("TimingWindow/geometry",       self.timing_window.saveGeometry())
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
        port = s.value("PPGMonitor/combo_port", PORT)
        idx = self.combo_port.findText(port)
        if idx >= 0:
            self.combo_port.setCurrentIndex(idx)

    def _populate_ports(self):
        current = self.combo_port.currentText()
        self.combo_port.blockSignals(True)
        self.combo_port.clear()
        ports = sorted(p.device for p in list_ports.comports())
        self.combo_port.addItems(ports)
        idx = self.combo_port.findText(current)
        self.combo_port.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_port.blockSignals(False)

    def _connect_serial(self, port: str):
        if not port:
            self.log("No port selected")
            return
        # Stop existing reader thread
        self._reader_stop.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        # Drain queue
        while not self._serial_queue.empty():
            try: self._serial_queue.get_nowait()
            except: break
        self._reader_stop.clear()
        self.log(f"Connecting to {port}...")
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.1)
            self._reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self._reader_thread.start()
            self.log(f"System ONLINE — {port} @ {BAUD}")
            self.btn_port_connect.setStyleSheet(
                "background-color: #1A3A1A; color: #44FF44; font-size: 18px; "
                "font-weight: bold; padding: 4px; border: 1px solid #44FF44; border-radius: 4px;")
            self.btn_port_connect.setText("CONNECTED")
        except Exception as e:
            self.ser = None
            self.log(f"ERROR: Could not open {port} — {e}")
            self.btn_port_connect.setStyleSheet(
                "background-color: #3A1A1A; color: #FF4444; font-size: 18px; "
                "font-weight: bold; padding: 4px; border: 1px solid #FF4444; border-radius: 4px;")
            self.btn_port_connect.setText("CONNECT")

    def _serial_reader(self):
        """Dedicated thread: reads serial lines at full rate into a queue.
        Completely decoupled from the UI so no frames are lost during rendering."""
        while not self._reader_stop.is_set() and self.ser is not None:
            try:
                line = self.ser.readline()
                if line:
                    self._serial_queue.put(line)
            except Exception:
                break

    _STATS_HR_ROWS  = {11, 13, 15}   # HR1, HR2, HR3
    _STATS_MEAN_COL = 2
    _STATS_MAROON   = QtGui.QColor("#5C001A")

    def _update_stats_table(self):
        for row, (name, _, _tooltip) in enumerate(self._STATS_SIGNALS):
            buf = self._stats_buf[name]
            if buf:
                last = buf[-1]
                mean = sum(buf) / len(buf)
                lo   = min(buf)
                hi   = max(buf)
                vals = [f"{last:.2f}", f"{mean:.2f}", f"{lo:.2f}", f"{hi:.2f}"]
            else:
                vals = ["---", "---", "---", "---"]
            for col, v in enumerate(vals, start=1):
                item = self.stats_table.item(row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(v)
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    if row in self._STATS_HR_ROWS and col == self._STATS_MEAN_COL:
                        item.setBackground(self._STATS_MAROON)
                    self.stats_table.setItem(row, col, item)
                else:
                    item.setText(v)
            self._stats_buf[name].clear()

    def update_data(self):
        if self.is_paused:
            # Drain queue to prevent memory buildup while paused
            try:
                while True:
                    self._serial_queue.get_nowait()
            except queue.Empty:
                pass
            return
        try:
            _new_data = False
            _console_lines = []
            if hasattr(self, '_serial_queue'):
                while True:
                    try:
                        line_raw = self._serial_queue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        line = line_raw.decode('utf-8', errors='ignore').strip()
                    except: continue
                    if not line: continue

                    # Confirmation messages from ESP32 (e.g. "# Switched to mow_afe4490")
                    if line.startswith('#'):
                        if self.serialcom_window is not None:
                            self.serialcom_window.append_line(line)
                        if 'mow' in line.lower() and 'frame' not in line.lower():
                            self.active_lib = "MOW"
                            self.frame_mode = "M1"
                            self._update_lib_button()
                            self.log("Active library: mow_afe4490")
                        elif 'protocentral' in line.lower():
                            self.active_lib = "PROTOCENTRAL"
                            self.frame_mode = "M1"
                            self._update_lib_button()
                            self.log("Active library: protocentral")
                        elif 'frame mode' in line.lower():
                            self.log(line.lstrip('# '))
                        elif line.startswith('# SYS:'):
                            self.log(line[6:].strip())
                        continue

                    current_time_perf = time.perf_counter()
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")
                    diff_us = int((current_time_perf - self.last_time) * 1e6) if self.last_time is not None else 0
                    self.last_time = current_time_perf

                    if not line.startswith('$'):
                        continue

                    # Verify and strip NMEA-style XOR checksum (*XX) if present
                    chk_ok = 1
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
                                    if self.serialcom_window is not None:
                                        self.serialcom_window.append_line(
                                            f"# BAD CHK (got {computed_chk:02X} exp {expected_chk:02X}): {line[:70]}")
                            except ValueError:
                                pass
                        if self.save_file_chk is not None:
                            self.save_file_chk.write(f"{timestamp},{diff_us:>5},{chk_ok},{line}\n")
                        line = line[:star_pos]  # strip *XX for field parsing and CSV
                        if not chk_ok:
                            continue
                    else:
                        if self.save_file_chk is not None:
                            self.save_file_chk.write(f"{timestamp},{diff_us:>5},{chk_ok},{line}\n")

                    csv_line = f"{timestamp},{diff_us:>5},{line}"

                    # Lab Capture: full rate (500 Hz), before decimation
                    if self.is_lab_capturing and self._lab_capture_file:
                        self._write_lab_capture_row(line)

                    # HR1TEST mirror: 500 Hz (before decimation) — must match firmware _update_hr1()
                    if self.hr1test_window is not None:
                        _p500 = line[1:].split(',')
                        if len(_p500) >= 9 and _p500[0] == 'M1':
                            try:
                                self.hr1test_calc.update(float(_p500[8]), 500.0)
                            except (ValueError, IndexError):
                                pass

                    # TIMING diagnostic frame: handle before decimation, not counted as data
                    # Format: $TIMING,hr1_mean,hr1_max,hr2fp_mean,hr2fp_max,hr3fp_mean,hr3fp_max,
                    #                 spo2_mean,spo2_max,cycle_mean,cycle_max,
                    #                 hr2cmp_mean,hr2cmp_max,hr3cmp_mean,hr3cmp_max,stack_free*XX
                    if line.startswith('$TIMING,'):
                        _console_lines.append(csv_line)
                        self._pending_tasks = []  # reset task accumulator for new cycle
                        if self.timing_window is not None:
                            _tp = line[1:].split('*')[0].split(',')
                            if len(_tp) >= 16:
                                try:
                                    vals = [int(x) for x in _tp[1:16]]
                                    self.timing_window.update_timing(*vals)
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
                        if self.timing_window is not None:
                            self.timing_window.update_tasks(self._pending_tasks)
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
                    if len(parts) >= 20:
                        try:
                            # 0:LibID, 1:SmpCnt, 2:Ts_us, 3:RED, 4:IR, 5:RED_Amb, 6:IR_Amb, 7:RED_Sub, 8:IR_Sub,
                            # 9:PPG, 10:SpO2, 11:SpO2_SQI, 12:SpO2_R, 13:PI, 14:HR1, 15:HR1_SQI, 16:HR2, 17:HR2_SQI, 18:HR3, 19:HR3_SQI
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:20]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_red.append(p[2])
                            self.data_ir.append(p[3])
                            self.data_red_amb.append(p[4])
                            self.data_ir_amb.append(p[5])
                            self.data_red_sub.append(p[6])
                            self.data_ir_sub.append(p[7])
                            self.data_ppg.append(p[8])
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
                            self.hr3_calc.update(p[7], SPO2_RECEIVED_FS)  # IR_Sub for HR3Lab diagnostics
                            # Stats buffers
                            for sname, attr, _ in self._STATS_SIGNALS:
                                self._stats_buf[sname].append(getattr(self, attr)[-1])
                        except ValueError: pass
                        else: _new_data = True
                    elif parts[0] == "M2" and len(parts) >= 8:
                        # $M2,cnt,led2(RED),led1(IR),aled2(RED_Amb),aled1(IR_Amb),led2_aled2(RED_Sub),led1_aled1(IR_Sub)
                        try:
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:8]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(0.0)
                            self.data_ppg.append(0.0)
                            self.data_spo2.append(-1.0)
                            self.data_hr1.append(-1.0)
                            self.data_red.append(p[1])
                            self.data_ir.append(p[2])
                            self.data_red_amb.append(p[3])
                            self.data_ir_amb.append(p[4])
                            self.data_red_sub.append(p[5])
                            self.data_ir_sub.append(p[6])
                            self.data_hr2.append(-1.0)
                            self.data_hr3.append(-1.0)
                            self.data_spo2_r.append(-1.0)
                            self.data_pi.append(-1.0)
                            self.data_spo2_sqi.append(0.0)
                            self.data_hr1_sqi.append(0.0)
                            self.data_hr2_sqi.append(0.0)
                            self.data_hr3_sqi.append(0.0)
                        except ValueError: pass
                        else: _new_data = True

                # SerialComWindow: batch update (already one Qt op per cycle — no extra throttle needed)
                if _console_lines and self.serialcom_window is not None:
                    self.serialcom_window.append_lines(_console_lines)

                if _new_data:
                    # PPGPlotsWindow: throttled to 25 Hz (every 2 calls)
                    self._ppgplots_refresh_counter += 1
                    if self.ppgplots_window is not None and self._ppgplots_refresh_counter >= self._PPGPLOTS_REFRESH_EVERY:
                        self._ppgplots_refresh_counter = 0
                        self.ppgplots_window.update_plots(
                            self.data_ppg, self.data_hr1, self.data_hr2, self.data_hr3,
                            self.data_spo2, self.data_spo2_sqi, self.data_spo2_r,
                            self.data_hr1_sqi, self.data_hr2_sqi, self.data_hr3_sqi,
                            self.data_red, self.data_ir,
                            self.data_red_amb, self.data_ir_amb, self.data_red_sub, self.data_ir_sub)

                if _new_data:
                    self._hrlab_refresh_counter += 1
                    if self.hrlab_window is not None and self._hrlab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                        self._hrlab_refresh_counter = 0
                        self.hrlab_window.update_plots(self.data_ppg, self.data_timestamp_us, self.data_sample_counter)

                    self._spo2lab_refresh_counter += 1
                    if self.spo2lab_window is not None and self._spo2lab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                        self._spo2lab_refresh_counter = 0
                        self.spo2lab_window.update_plots(
                            self.data_ir_sub, self.data_red_sub,
                            self.data_spo2, self.data_spo2_r,
                            self.data_timestamp_us, self.data_sample_counter)

                    self._hr3lab_refresh_counter += 1
                    if self.hr3lab_window is not None and self._hr3lab_refresh_counter >= self._SUBWIN_REFRESH_EVERY:
                        self._hr3lab_refresh_counter = 0
                        self.hr3lab_window.update_plots(
                            self.data_hr1, self.data_hr2, self.data_hr3, self.hr3_calc)

                    self._spo2test_refresh_counter += 1
                    if self.spo2test_window is not None and self._spo2test_refresh_counter >= self._SPOST_REFRESH_EVERY:
                        self._spo2test_refresh_counter = 0
                        self.spo2test_window.update_plots(
                            self.data_ir_sub, self.data_red_sub,
                            self.data_spo2, self.data_spo2_r, self.data_spo2_sqi,
                            self.data_timestamp_us, self.data_sample_counter)

                    self._hr1test_refresh_counter += 1
                    if self.hr1test_window is not None and self._hr1test_refresh_counter >= self._HR1TEST_REFRESH_EVERY:
                        self._hr1test_refresh_counter = 0
                        self.hr1test_window.update_plots(
                            self.data_hr1, self.data_hr1_sqi,
                            self.data_timestamp_us, self.data_sample_counter)

                    self._hr2test_refresh_counter += 1
                    if self.hr2test_window is not None and self._hr2test_refresh_counter >= self._HR2TEST_REFRESH_EVERY:
                        self._hr2test_refresh_counter = 0
                        self.hr2test_window.update_plots(
                            self.data_ir_sub, self.data_hr2, self.data_hr2_sqi,
                            self.data_timestamp_us, self.data_sample_counter)

                    self._hr3test_refresh_counter += 1
                    if self.hr3test_window is not None and self._hr3test_refresh_counter >= self._HR3TEST_REFRESH_EVERY:
                        self._hr3test_refresh_counter = 0
                        self.hr3test_window.update_plots(
                            self.data_ir_sub, self.data_hr3, self.data_hr3_sqi,
                            self.data_timestamp_us, self.data_sample_counter)

        except Exception as e:
            print(f"Error en loop: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        s = QtCore.QSettings(SETTINGS_FILE, QtCore.QSettings.IniFormat)
        if s.value("PPGMonitor/ppgplots_open",  True,  type=bool):
            QtCore.QTimer.singleShot(0, self._open_ppgplots_default)
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
        if s.value("PPGMonitor/timing_open",       False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_timing_default)
        if s.value("PPGMonitor/labcapture_open",   False, type=bool):
            QtCore.QTimer.singleShot(0, self._open_lab_capture_default)
        QtCore.QTimer.singleShot(300, self._bring_all_to_front)

    def _bring_all_to_front(self):
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid  = user32.GetWindowThreadProcessId(fg_hwnd, None)
        my_tid  = kernel32.GetCurrentThreadId()
        if fg_tid != my_tid:
            user32.AttachThreadInput(my_tid, fg_tid, True)
        for w in [self, self.ppgplots_window, self.serialcom_window,
                  self.hrlab_window, self.spo2lab_window, self.hr3lab_window,
                  self.spo2test_window, self.hr1test_window, self.hr2test_window,
                  self.hr3test_window, self.timing_window, self.lab_capture_window]:
            if w is not None:
                w.show()
                w.raise_()
                w.activateWindow()
                try:
                    user32.SetForegroundWindow(int(w.winId()))
                except Exception:
                    pass
        if fg_tid != my_tid:
            user32.AttachThreadInput(my_tid, fg_tid, False)

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
        if hasattr(self, '_reader_thread'):
            self._reader_thread.join(timeout=1.0)
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        if self.ppgplots_window is not None:
            self.ppgplots_window.main_monitor = None
            self.ppgplots_window.close()
        if self.serialcom_window is not None:
            self.serialcom_window.main_monitor = None
            self.serialcom_window.close()
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
        if self.timing_window is not None:
            self.timing_window.close()
        if self.lab_capture_window is not None:
            self.lab_capture_window.main_monitor = None
            self.lab_capture_window.close()
        event.accept()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AFE4490 PPG Monitor")
    parser.add_argument("--save-chk", action="store_true",
                        help="Auto-save diagnostic CSV with raw frames and CHK_OK field")
    parser.add_argument("--save-chk-duration", type=int, default=15, metavar="N",
                        help="Auto-close CHK file and exit after N seconds (default: 15)")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)

    class _FastTipStyle(QtWidgets.QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, returnData=None):
            if hint == QtWidgets.QStyle.SH_ToolTip_WakeUpDelay:
                return 150  # ms (default ~700 ms)
            return super().styleHint(hint, option, widget, returnData)

    app.setStyle(_FastTipStyle('Fusion'))
    app.setStyleSheet(
        "QToolTip { background-color: #5500AA; color: #F0F0F0; "
        "border: 2px solid #FFE066; padding: 8px; }"
    )
    window = PPGMonitor(save_chk=args.save_chk, save_chk_duration=args.save_chk_duration)
    window.show()
    sys.exit(app.exec_())
