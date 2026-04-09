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
            hps_max = np.max(calc.last_hps)
            if hps_max <= 0.0:
                hps_max = 1.0
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
            "RED minus ambient: RED − AmbRED. Ambient-subtracted RED signal. "
            "Primary input to the SpO2 algorithm. Field: REDSub."))
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
            "IR minus ambient: IR − AmbIR. Ambient-subtracted IR signal. "
            "Primary input to the HR algorithms (HR1, HR2, HR3). Field: IRSub."))
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
        self.curve_amb_red  = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient RED")
        self.curve_red_sub  = self.p1.plot(pen=pg.mkPen('#FF8888', width=1.5), name="RED (Clean)")
        self.p1.showGrid(x=True, y=True, alpha=0.3)

        self.graphics_layout.nextRow()

        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>IR</b>")
        self.curve_ir      = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="IR (Raw)")
        self.curve_amb_ir  = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient IR")
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
        self.check_red_amb.stateChanged.connect(lambda: self.curve_amb_red.setVisible(self.check_red_amb.isChecked()))
        self.check_red_sub.stateChanged.connect(lambda: self.curve_red_sub.setVisible(self.check_red_sub.isChecked()))
        self.check_ir_raw.stateChanged.connect( lambda: self.curve_ir.setVisible(self.check_ir_raw.isChecked()))
        self.check_ir_amb.stateChanged.connect( lambda: self.curve_amb_ir.setVisible(self.check_ir_amb.isChecked()))
        self.check_ir_sub.stateChanged.connect( lambda: self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked()))

        self.curve_red.setVisible(False)
        self.curve_amb_red.setVisible(False)
        self.curve_red_sub.setVisible(True)
        self.curve_ir.setVisible(False)
        self.curve_amb_ir.setVisible(False)
        self.curve_ir_sub.setVisible(True)

        outer.addWidget(hint)

    def update_plots(self, data_ppg, data_hr1, data_hr2, data_hr3,
                     data_spo2, data_spo2_sqi, data_spo2_r,
                     data_hr1_sqi, data_hr2_sqi, data_hr3_sqi,
                     data_red, data_ir,
                     data_amb_red, data_amb_ir, data_red_sub, data_ir_sub):
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
        self.curve_amb_red.setData(list(data_amb_red))
        self.curve_amb_ir.setData(list(data_amb_ir))
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
        "LibID,SmpCnt,Ts_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI"
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


class PPGMonitor(QtWidgets.QMainWindow):
    def set_status(self, text, status_type="info"):
        """
        Appends a timestamped line to the status log, coloured by type.
        types: 'info' (blue), 'success' (green), 'warning' (orange), 'error' (red)
        """
        colors = {
            "success": "#00FF88",
            "warning": "#FFDD44",
            "error":   "#FF4444",
            "info":    "#44AAFF",
        }
        icons = {
            "success": "✔",
            "warning": "⚠",
            "error":   "✖",
            "info":    "●",
        }
        fg = colors.get(status_type, colors["info"])
        icon = icons.get(status_type, icons["info"])
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_panel.append(
            f'<span style="color:#888888;">[{ts}]</span> '
            f'<span style="color:{fg};font-weight:normal;">{icon} {text}</span>'
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
        self.data_amb_ir = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_amb_red = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
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
        self.is_saving_raw = False
        self.save_file_raw = None
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
        # Render throttle rates (all relative to ~50 Hz update_data calls)
        self._PPGPLOTS_REFRESH_EVERY  = 2   # 25 Hz — smooth plot animation
        self._SUBWIN_REFRESH_EVERY    = 5   # 10 Hz — SpO2/HR3 change slowly
        self._ppgplots_refresh_counter = 0
        self._hrlab_refresh_counter    = 0
        self._spo2lab_refresh_counter  = 0
        self._hr3lab_refresh_counter   = 0
        self._decim_counter = 0
        self.hr3_calc = HRFFTCalc()

        # ── Stats table buffers (reset every N seconds) ───────────────────────
        self._STATS_SIGNALS = [
            # (display_name, data_attr, tooltip_description)
            # Order mirrors the $M1/$P1 serial frame. Row indices: HR1=11, HR2=13, HR3=15.
            ("RED",      "data_red",      "Raw RED LED signal (LED2, 660 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts."),
            ("IR",       "data_ir",       "Raw IR LED signal (LED1, ~880 nm) before ambient subtraction. Includes ambient light + LED contribution. Units: ADC counts."),
            ("Amb RED",  "data_amb_red",  "Ambient RED channel (ALED2): sampled with RED LED off. Represents environmental red-light interference. Units: ADC counts."),
            ("Amb IR",   "data_amb_ir",   "Ambient IR channel (ALED1): sampled with IR LED off. Represents environmental IR interference. Units: ADC counts."),
            ("RED sub",  "data_red_sub",  "Ambient-subtracted RED signal: LED2 − ALED2. Removes DC ambient component. Used as input for SpO2 AC/DC decomposition. Units: ADC counts."),
            ("IR sub",   "data_ir_sub",   "Ambient-subtracted IR signal: LED1 − ALED1. Removes DC ambient component. Main input for HR1, HR2, HR3 and SpO2 algorithms. Units: ADC counts."),
            ("PPG",      "data_ppg",      "Filtered PPG signal (IR channel). IIR DC removal τ=1.6 s → moving-average low-pass 5 Hz → negated. Units: ADC counts."),
            ("SpO2",     "data_spo2",     "Blood oxygen saturation computed by firmware (mow_afe4490). Formula: SpO2 = a − b·R. Range: 70–100 %. Clamped to 100 % if within 3 % above; invalid if >103 %."),
            ("SpO2 SQI", "data_spo2_sqi", "SpO2 Signal Quality Index [0–1]. Based on Perfusion Index (PI): SQI = clamp((PI − 0.5) / (2.0 − 0.5), 0, 1). PI < 0.5 % → 0 (no contact or very weak signal). PI ≥ 2.0 % → 1 (full quality). Forced to 0 if SpO2 is outside valid range. Thresholds per Nellcor/Masimo clinical reference."),
            ("SpO2_R",   "data_spo2_r",   "R ratio used for SpO2 calculation: R = (AC_red/DC_red) / (AC_ir/DC_ir). Dimensionless. Useful for sensor calibration (R-curve)."),
            ("PI",       "data_pi",       "Perfusion Index: (AC_ir / DC_ir) × 100 [%]. Measures signal strength / perfusion quality. Typical range: 0.02–20 %. Low PI (<0.3 %) indicates weak signal or poor perfusion."),
            ("HR1",      "data_hr1",      "Heart rate from algorithm HR1 (adaptive threshold peak detection). Threshold = 0.6 × running_max; refractory 185 ms. Average of last 5 RR intervals. Units: BPM. Valid range: 25–300 BPM."),
            ("HR1 SQI",  "data_hr1_sqi",  "HR1 Signal Quality Index [0–1]. Coefficient of variation (CV = std/mean) of the 5 most recent RR intervals: SQI = clamp(1 − CV/0.15, 0, 1). CV = 0 (perfectly regular rhythm) → 1. CV ≥ 15 % (arrhythmia or motion artefact) → 0. Forced to 0 if fewer than 5 intervals detected or HR1 outside valid range."),
            ("HR2",      "data_hr2",      "Heart rate from algorithm HR2 (normalized autocorrelation). BPF 0.5–5 Hz → decimate ×10 → 400-sample buffer → autocorr every 0.5 s → first local max ≥ 0.5 → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM."),
            ("HR2 SQI",  "data_hr2_sqi",  "HR2 Signal Quality Index [0–1]. Normalised autocorrelation value at the dominant RR lag: SQI = acorr[peak_lag] / acorr[0]. High value = strong, clear periodicity. Minimum threshold 0.5: below this no HR2 is reported and SQI = 0. Forced to 0 if buffer not full or HR2 outside valid range."),
            ("HR3",      "data_hr3",      "Heart rate from algorithm HR3 (FFT + HPS, computed in firmware). LP 10 Hz → decimate ×10 → 512-sample Hann window → FFT → Harmonic Product Spectrum (harmonics 2–3) → parabolic interpolation. Units: BPM. Valid range: 25–300 BPM."),
            ("HR3 SQI",  "data_hr3_sqi",  "HR3 Signal Quality Index [0–1]. Spectral concentration of fundamental power at the HPS peak bin vs. search range: SQI = (P[peak]/ΣP[k] − 1/N) / (1 − 1/N). Pure dominant tone → SQI ≈ 1. Diffuse or noisy spectrum → SQI ≈ 0. Forced to 0 if buffer not full or HR3 outside valid range."),
        ]
        self._stats_buf = {name: [] for name, _, __ in self._STATS_SIGNALS}
        
        self.auto_save_timer = QtCore.QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_stop_save)

        self.auto_save_raw_timer = QtCore.QTimer()
        self.auto_save_raw_timer.setSingleShot(True)
        self.auto_save_raw_timer.timeout.connect(self.auto_stop_save_raw)

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

        self.btn_save_raw = QtWidgets.QPushButton("SAVE\nRAW (500 Hz)")
        self.btn_save_raw.setCheckable(True)
        self.btn_save_raw.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save_raw.clicked.connect(self.toggle_save_raw)
        self.btn_save_raw.setToolTip(_make_tooltip(
            "SAVE RAW (500 Hz)",
            "Toggle saving every raw frame at full 500 Hz to a timestamped CSV file. "
            "Ignores DECIMATION. Use for offline algorithm analysis. "
            "Filename: ppg_data_raw_<timestamp>.csv"))
        self.sidebar_layout.addWidget(self.btn_save_raw)

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
            "SAVE RAW always records at full 500 Hz regardless of this setting."))
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
            "Full frame mode: 19 fields — SmpCnt, Ts_us, RED, IR, AmbRED, AmbIR, REDSub, IRSub, "
            "PPG, SpO2, SpO2SQI, SpO2_R, PI, HR1, HR1SQI, HR2, HR2SQI, HR3, HR3SQI + checksum. "
            "Use for algorithm analysis and calibration."))
        self.btn_frame_m2.setToolTip(_make_tooltip(
            "$M2 — RAW frame",
            "Raw frame mode: only raw ADC values — SmpCnt, Ts_us, RED, IR, AmbRED, AmbIR + checksum. "
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
            "HR3 uses a 512-sample Hann window + rfft + HPS on the IR sub-signal at 50 Hz."))
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

        self.sidebar_layout.addStretch()

        # ── Log panel (right of sidebar, fills remaining space) ───────────────
        self.log_panel = QtWidgets.QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A2E; color: #E0E0E0;
                font-family: monospace; font-size: 26px;
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
                font-family: monospace; font-size: 22px;
                gridline-color: #2A2A2A; border: none;
            }
            QHeaderView::section {
                background-color: #1E1E2E; color: #AAAAAA;
                font-size: 22px; font-weight: bold;
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
        self.set_status(f"Frame mode: ${mode}", "info")

    def _send_lib_cmd(self, cmd):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            return
        self.ser.write(cmd.encode())

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

    def toggle_pause(self):
        self.is_paused = self.btn_pause.isChecked()
        if self.is_paused:
            self.btn_pause.setText("RESUME\nCAPTURE")
            self.set_status("Capture PAUSED", "warning")
        else:
            self.btn_pause.setText("PAUSE\nCAPTURE")
            self.set_status(f"System ONLINE - Connected to {PORT} @ {BAUD}", "success")

    def auto_stop_save(self):
        if self.is_saving:
            self.btn_save.setChecked(False)
            self.toggle_save()
            self.set_status("Stream ended (Auto-Stop 1000s)", "info")

    def auto_stop_save_raw(self):
        if self.is_saving_raw:
            self.btn_save_raw.setChecked(False)
            self.toggle_save_raw()
            self.set_status("RAW stream ended (Auto-Stop 1000s)", "info")

    def toggle_save_raw(self):
        if self.is_paused:
            self.btn_save_raw.setChecked(False)
            self.set_status("Cannot record RAW while capture is paused", "error")
            return
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.is_saving_raw = self.btn_save_raw.isChecked()
        if self.is_saving_raw:
            self.btn_save_raw.setText("STOP\nRAW")
            filename = f"ppg_data_raw_{now_str}.csv"
            try:
                self.save_file_raw = open(filename, "w")
                if self.frame_mode == "M2":
                    self.save_file_raw.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub\n")
                else:
                    self.save_file_raw.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI\n")
                self.set_status(f"RECORDING RAW (500 Hz): {filename}", "warning")
                self.auto_save_raw_timer.start(1000 * 1000)
            except Exception as e:
                self.set_status(f"Error opening RAW file: {e}", "error")
                self.is_saving_raw = False
                self.btn_save_raw.setChecked(False)
        else:
            self.auto_save_raw_timer.stop()
            self.btn_save_raw.setText("SAVE\nRAW (500 Hz)")
            if self.save_file_raw:
                self.save_file_raw.close()
                self.save_file_raw = None
            self.set_status(f"System ONLINE - Connected to {PORT} @ {BAUD}", "success")

    def toggle_save(self):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.is_paused:
            self.btn_save.setChecked(False)
            filename = f"ppg_data_snap_{now_str}.csv"
            try:
                with open(filename, "w") as f:
                    f.write("LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_red[i]},{self.data_ir[i]},{self.data_amb_red[i]},{self.data_amb_ir[i]},{self.data_red_sub[i]},{self.data_ir_sub[i]},{self.data_ppg[i]},{self.data_spo2[i]},{self.data_spo2_sqi[i]},{self.data_spo2_r[i]},{self.data_pi[i]},{self.data_hr1[i]},{self.data_hr1_sqi[i]},{self.data_hr2[i]},{self.data_hr2_sqi[i]},{self.data_hr3[i]},{self.data_hr3_sqi[i]}\n")
                self.set_status(f"Snapshot saved to {filename}", "success")
            except Exception as e:
                self.set_status(f"Error saving snapshot: {e}", "error")
        else:
            self.is_saving = self.btn_save.isChecked()
            if self.is_saving:
                self.btn_save.setText("STOP\nRECORDING")
                filename = f"ppg_data_stream_{now_str}.csv"
                try:
                    self.save_file = open(filename, "w")
                    if self.frame_mode == "M2":
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub\n")
                    else:
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SQI,SpO2_R,PI,HR1,HR1SQI,HR2,HR2SQI,HR3,HR3SQI\n")
                    self.set_status(f"RECORDING LIVE: {filename}", "warning")
                    self.auto_save_timer.start(1000 * 1000)
                except Exception as e:
                    self.set_status(f"Error opening save file: {e}", "error")
                    self.is_saving = False
                    self.btn_save.setChecked(False)
            else:
                self.auto_save_timer.stop()
                self.btn_save.setText("SAVE\nDATA")
                if self.save_file:
                    self.save_file.close()
                    self.save_file = None
                self.set_status(f"System ONLINE - Connected to {PORT} @ {BAUD}", "success")

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
            self.set_status("No port selected", "error")
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
        self.set_status(f"Connecting to {port}...", "info")
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.1)
            self._reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self._reader_thread.start()
            self.set_status(f"System ONLINE — {port} @ {BAUD}", "success")
            self.btn_port_connect.setStyleSheet(
                "background-color: #1A3A1A; color: #44FF44; font-size: 18px; "
                "font-weight: bold; padding: 4px; border: 1px solid #44FF44; border-radius: 4px;")
            self.btn_port_connect.setText("CONNECTED")
        except Exception as e:
            self.ser = None
            self.set_status(f"ERROR: Could not open {port} — {e}", "error")
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
                            self.set_status("Active library: mow_afe4490", "info")
                        elif 'protocentral' in line.lower():
                            self.active_lib = "PROTOCENTRAL"
                            self.frame_mode = "M1"
                            self._update_lib_button()
                            self.set_status("Active library: protocentral", "info")
                        elif 'frame mode' in line.lower():
                            self.set_status(line.lstrip('# '), "info")
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

                    # RAW file save: full rate (500 Hz), before decimation
                    if self.is_saving_raw and self.save_file_raw:
                        self.save_file_raw.write(csv_line + "\n")
                        self.save_file_raw.flush()

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
                            # 0:LibID, 1:SmpCnt, 2:Ts_us, 3:RED, 4:IR, 5:AmbRED, 6:AmbIR, 7:REDSub, 8:IRSub,
                            # 9:PPG, 10:SpO2, 11:SpO2SQI, 12:SpO2_R, 13:PI, 14:HR1, 15:HR1SQI, 16:HR2, 17:HR2SQI, 18:HR3, 19:HR3SQI
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:20]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_red.append(p[2])
                            self.data_ir.append(p[3])
                            self.data_amb_red.append(p[4])
                            self.data_amb_ir.append(p[5])
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
                            self.hr3_calc.update(p[7], SPO2_RECEIVED_FS)  # IRSub for HR3Lab diagnostics
                            # Stats buffers
                            for sname, attr, _ in self._STATS_SIGNALS:
                                self._stats_buf[sname].append(getattr(self, attr)[-1])
                        except ValueError: pass
                        else: _new_data = True
                    elif parts[0] == "M2" and len(parts) >= 8:
                        # $M2,cnt,led2(RED),led1(IR),aled2(AmbRED),aled1(AmbIR),led2_aled2(REDSub),led1_aled1(IRSub)
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
                            self.data_amb_red.append(p[3])
                            self.data_amb_ir.append(p[4])
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
                            self.data_amb_red, self.data_amb_ir, self.data_red_sub, self.data_ir_sub)

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
                  self.hrlab_window, self.spo2lab_window, self.hr3lab_window]:
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
        if getattr(self, 'is_saving_raw', False) and getattr(self, 'save_file_raw', None):
            self.save_file_raw.close()
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
