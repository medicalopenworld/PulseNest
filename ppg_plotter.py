import sys
import serial
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
                              hr_min=30, hr_max=250, prominence=0.1):
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
                              hr_min=30, hr_max=250, prominence=0.1):
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
    full = signal.correlate(seg, seg, mode='full', method='direct')
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
    LP_CUTOFF_HZ      = 10.0
    BUF_LEN           = 512
    UPDATE_INTERVAL_S = 0.5
    HR_MIN_HZ         = 0.5   # 30 BPM
    HR_MAX_HZ         = 4.167 # 250 BPM

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

        # Restrict search to HR band
        mask = (freqs >= self.HR_MIN_HZ) & (freqs <= self.HR_MAX_HZ)
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
        ext_mask = (freqs >= self.HR_MIN_HZ) & (freqs <= f_top)
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

_MOUSE_HINT = "pyqtgraph: use mouse buttons and wheel on the plots to zoom/pan (right-click for more options)"

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
        self.resize(1500, 1200)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
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
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Left: plots ───────────────────────────────────────────────────────
        glw = pg.GraphicsLayoutWidget()
        root.addWidget(glw, stretch=3)

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
        right.setFixedWidth(390)
        right.setStyleSheet("background-color: #1A1A1A;")
        root.addWidget(right)

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
        self._spin_avg_win = QtWidgets.QSpinBox()
        self._spin_avg_win.setRange(1, 30)
        self._spin_avg_win.setValue(5)
        self._spin_avg_win.setSuffix(" s")
        self._spin_avg_win.setStyleSheet("background-color: #2A2A2A; color: #E0E0E0; padding: 2px;")
        form_r.addRow("SpO2 ref (%):", self._spin_spo2_ref)
        form_r.addRow("Avg window:",   self._spin_avg_win)
        panel.addWidget(grp_ref)

        btn_add = QtWidgets.QPushButton("ADD POINT")
        btn_add.setStyleSheet("background-color: #226622; color: #FFFFFF; font-weight: bold; padding: 8px;")
        btn_add.clicked.connect(self._add_point)
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
        self.resize(1800, 900)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
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

        self._splitter.addWidget(left_gw)
        self._splitter.addWidget(right_gw)

        # ── info bar ─────────────────────────────────────────────────────────────
        self._info_label = QtWidgets.QLabel()
        self._info_label.setFont(QtGui.QFont("Consolas", 10))
        self._info_label.setStyleSheet("color: #AAAAAA; padding: 2px 4px;")
        outer.addWidget(self._info_label)
        self._refresh_info(None)

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
            hps_max = np.max(calc.last_hps) if np.max(calc.last_hps) > 0.0 else 1.0
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

        self.curve_hr1_cmp.setData(list(data_hr1))
        self.curve_hr2_cmp.setData(list(data_hr2))
        self.curve_hr3_cmp.setData(list(data_hr3))

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, lambda: self._splitter.setSizes([1100, 700]))

    def closeEvent(self, event):
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
        self.setWindowTitle("HRLAB")
        self.resize(2400, 450)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
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
        data = np.array(list(ppg_data))
        self.curve_1a.setData(data)

        fs = 50.0  # AFE4490 @ 500 Hz, SERIAL_DOWNSAMPLING_RATIO=10

        nyq = fs / 2.0
        high_norm = 3.7 / nyq

        # Plot 2A: mow_afe4490 biquad — stateful, processes only new samples
        mow_filtered = None
        if high_norm < 1.0:
            try:
                b, a = self._mow_biquad_coeffs(fs, 0.5, 3.7)

                # Reset state if sample rate changed
                if fs != self._mow_fs_cached:
                    self._mow_zi = None
                    self._mow_fs_cached = fs

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
            max_lag_n = int(round(2.0 * fs))
            needed    = window_n + max_lag_n
            max_lag_s = max_lag_n / fs
            print(f"[DBG] max_lag_s={max_lag_s:.4f}  max_lag_n={max_lag_n}  fs={fs:.2f}", flush=True)

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
        if self.main_monitor is not None:
            self.main_monitor.btn_hrlab.setChecked(False)
            self.main_monitor.hrlab_window = None
        event.accept()


class PPGMonitor(QtWidgets.QMainWindow):
    def set_status(self, text, status_type="info"):
        """
        Añade una línea al log de estado con timestamp y color según el tipo.
        tipos: 'info' (azul), 'success' (verde), 'warning' (naranja), 'error' (rojo)
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
            f'<span style="color:{fg};font-weight:bold;">{icon} {text}</span>'
        )
        self.log_panel.verticalScrollBar().setValue(
            self.log_panel.verticalScrollBar().maximum()
        )

    def __init__(self, save_chk=False, save_chk_duration=15):
        super().__init__()
        
        # Configuración Ventana Principal
        self.setWindowTitle("AFE4490 Advanced Monitor (by Medical Open World)")
        self.resize(2700, 1600)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.statusBar().showMessage(_MOUSE_HINT)
        
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
        self.data_red_filt = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir_filt = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr1_ppg = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr2     = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr3     = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2_r  = deque([-1.0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)

        self.is_paused = False
        self.is_plot_paused = False
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
        self.hrlab_window = None
        self.spo2lab_window = None
        self.hr3lab_window = None
        self._decim_counter = 0
        self.hr3_calc = HRFFTCalc()
        
        self.auto_save_timer = QtCore.QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_stop_save)

        self.auto_save_raw_timer = QtCore.QTimer()
        self.auto_save_raw_timer.setSingleShot(True)
        self.auto_save_raw_timer.timeout.connect(self.auto_stop_save_raw)
        
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
        
        def create_check(label, color, checked=True):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {color}; font-weight: bold; font-size: 18px; spacing: 10px; }}
                QCheckBox::indicator {{ 
                    width: 24px; height: 24px; border: 2px solid #555555; 
                    border-radius: 4px; background-color: #1A1A1A; 
                }}
                QCheckBox::indicator:checked {{ 
                    background-color: #666666; 
                    border: 2px solid #BBBBBB;
                    image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdUlEQVR4nO2UQQ7AIAgEWf//5+21aYQFIpfGvRhJnFGJgqRNfGjrwiqCdKzCVB2DRAFC22RnWoAAAAAElFTkSuQmCC");
                }}
            """)
            return cb

        self.label_red = QtWidgets.QLabel("RED")
        self.label_red.setStyleSheet("color: #FF4444; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(self.label_red)
        
        self.check_red_raw = create_check("RED (raw)", "#FFFFFF", False)
        self.check_red_amb = create_check("Ambient RED", "#00FFFF", False)
        self.check_red_sub = create_check("RED (clean)", "#FF8888", True)
        self.check_red_filt = create_check("RED (filt)", "#FF0000", False)
        
        self.sidebar_layout.addWidget(self.check_red_raw)
        self.sidebar_layout.addWidget(self.check_red_amb)
        self.sidebar_layout.addWidget(self.check_red_sub)
        self.sidebar_layout.addWidget(self.check_red_filt)
        
        self.label_ir = QtWidgets.QLabel("IR")
        self.label_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 20px;")
        self.sidebar_layout.addWidget(self.label_ir)
        
        self.check_ir_raw = create_check("IR (raw)", "#FFFFFF", False)
        self.check_ir_amb = create_check("Ambient IR", "#00FFFF", False)
        self.check_ir_sub = create_check("IR (clean)", "#88CCFF", True)
        self.check_ir_filt = create_check("IR (filt)", "#44AAFF", False)
        
        self.sidebar_layout.addWidget(self.check_ir_raw)
        self.sidebar_layout.addWidget(self.check_ir_amb)
        self.sidebar_layout.addWidget(self.check_ir_sub)
        self.sidebar_layout.addWidget(self.check_ir_filt)
        
        # Espaciador para separar checkboxes de botones
        self.sidebar_layout.addSpacing(30)

        # Botones de Acción en el lateral

        self.btn_pause = QtWidgets.QPushButton("PAUSAR\nCAPTURA")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.sidebar_layout.addWidget(self.btn_pause)

        self.btn_pause_plot = QtWidgets.QPushButton("PAUSE\nMAIN WINDOW")
        self.btn_pause_plot.setCheckable(True)
        self.btn_pause_plot.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause_plot.clicked.connect(self.toggle_pause_plot)
        self.sidebar_layout.addWidget(self.btn_pause_plot)
        
        self.btn_save = QtWidgets.QPushButton("GUARDAR\nDATOS")
        self.btn_save.setCheckable(True)
        self.btn_save.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.toggle_save)
        self.sidebar_layout.addWidget(self.btn_save)

        self.btn_save_raw = QtWidgets.QPushButton("GUARDAR\nRAW (500 Hz)")
        self.btn_save_raw.setCheckable(True)
        self.btn_save_raw.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save_raw.clicked.connect(self.toggle_save_raw)
        self.sidebar_layout.addWidget(self.btn_save_raw)

        self.sidebar_layout.addSpacing(20)

        label_decim = QtWidgets.QLabel("DECIMACIÓN")
        label_decim.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_decim)

        decim_row = QtWidgets.QHBoxLayout()
        decim_lbl = QtWidgets.QLabel("1 de cada")
        decim_lbl.setStyleSheet("color: #CCCCCC; font-size: 16px;")
        self.spin_decim = QtWidgets.QSpinBox()
        self.spin_decim.setRange(1, 500)
        self.spin_decim.setValue(10)
        self.spin_decim.setSuffix(" tramas")
        self.spin_decim.setStyleSheet("background-color: #2A2A2A; color: #FFDD44; padding: 4px; font-size: 16px;")
        decim_row.addWidget(decim_lbl)
        decim_row.addWidget(self.spin_decim)
        self.sidebar_layout.addLayout(decim_row)

        self.sidebar_layout.addSpacing(20)

        label_library = QtWidgets.QLabel("LIBRARY")
        label_library.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_library)

        self.btn_lib_mow = QtWidgets.QPushButton("MOW")
        self.btn_lib_pc  = QtWidgets.QPushButton("PROTOCENTRAL")
        self.btn_lib_mow.clicked.connect(lambda: self._send_lib_cmd('m'))
        self.btn_lib_pc.clicked.connect(lambda:  self._send_lib_cmd('p'))
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
        self.sidebar_layout.addWidget(self.btn_frame_m1)
        self.sidebar_layout.addWidget(self.btn_frame_m2)
        self._update_frame_button()

        self.sidebar_layout.addSpacing(20)

        label_analysis = QtWidgets.QLabel("ANALYSIS")
        label_analysis.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_analysis)

        self.btn_hrlab = QtWidgets.QPushButton("HRLAB")
        self.btn_hrlab.setCheckable(True)
        self.btn_hrlab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hrlab.clicked.connect(self.toggle_hrlab)
        self.sidebar_layout.addWidget(self.btn_hrlab)

        self.btn_spo2lab = QtWidgets.QPushButton("SPO2LAB")
        self.btn_spo2lab.setCheckable(True)
        self.btn_spo2lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_spo2lab.clicked.connect(self.toggle_spo2lab)
        self.sidebar_layout.addWidget(self.btn_spo2lab)

        self.btn_hr3lab = QtWidgets.QPushButton("HR3LAB")
        self.btn_hr3lab.setCheckable(True)
        self.btn_hr3lab.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hr3lab.clicked.connect(self.toggle_hr3lab)
        self.sidebar_layout.addWidget(self.btn_hr3lab)

        self.sidebar_layout.addStretch()
        
        left_layout = QtWidgets.QVBoxLayout()
        right_layout = QtWidgets.QVBoxLayout()
        
        # 1. Dashboard de Gráficas (Usando PyQtGraph)
        pg.setConfigOptions(antialias=True)
        self.graphics_layout = pg.GraphicsLayoutWidget()
        left_layout.addWidget(self.graphics_layout, stretch=10)
        
        # Canal Rojo
        self.p1 = self.graphics_layout.addPlot(title="<b style='color:#FF4444'>RED</b>")
        self.curve_red = self.p1.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="RED (Raw)")
        self.curve_amb_red = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient RED")
        self.curve_red_sub = self.p1.plot(pen=pg.mkPen('#FF8888', width=1.5), name="RED (Clean)")
        self.curve_red_filt = self.p1.plot(pen=pg.mkPen('#FF0000', width=3), name="RED (Filtered)")
        self.p1.showGrid(x=True, y=True, alpha=0.3)
        
        self.graphics_layout.nextRow()
        
        # Canal IR
        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>IR</b>")
        self.curve_ir = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="IR (Raw)")
        self.curve_amb_ir = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient IR")
        self.curve_ir_sub = self.p2.plot(pen=pg.mkPen('#88CCFF', width=1.5), name="IR (Clean)")
        self.curve_ir_filt = self.p2.plot(pen=pg.mkPen('#44AAFF', width=3), name="IR (Filtered)")
        self.p2.showGrid(x=True, y=True, alpha=0.3)
        
        self.graphics_layout.nextRow()
        
        # Fila para HR y SPO2 (en paralelo)
        stats_layout = self.graphics_layout.addLayout()
        self.p_ppg = stats_layout.addPlot(title="<b style='color:#FFFFFF'>PPG</b>")
        self.curve_ppg = self.p_ppg.plot(pen=pg.mkPen('#FFFFFF', width=2))
        self.curve_hr1_ppg = self.p_ppg.plot(pen=pg.mkPen('#FF8800', width=1.5), name="HR1 PPG")
        self.p_ppg.showGrid(x=True, y=True, alpha=0.3)

        self.p_spo2 = stats_layout.addPlot(title="<b style='color:#44FF88'>SpO2 (%)</b>")
        self.curve_spo2 = self.p_spo2.plot(pen=pg.mkPen('#44FF88', width=3))
        self.p_spo2.setYRange(50, 100)

        self.p_hr = stats_layout.addPlot(title="<b style='color:#FFDD44'>HEART RATE (BPM)</b>")
        self.curve_hr1 = self.p_hr.plot(pen=pg.mkPen('#FFDD44', width=3), name="HR1")
        self.curve_hr2 = self.p_hr.plot(pen=pg.mkPen('#FF4444', width=1.5), name="HR2")
        self.curve_hr3 = self.p_hr.plot(pen=pg.mkPen('#00CCFF', width=1.5), name="HR3")
        self.p_hr.setYRange(40, 180)

        # Column widths: PPG wider, SpO2 and HR narrower
        stats_layout.layout.setColumnStretchFactor(0, 3)  # Inverted PPG
        stats_layout.layout.setColumnStretchFactor(1, 1)  # SpO2
        stats_layout.layout.setColumnStretchFactor(2, 1)  # HR

        # 2. Consola de Texto
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console.setMinimumWidth(200)
        self.console.setFont(QtGui.QFont("Consolas", 9))
        self.console.setStyleSheet("""
            background-color: #000000; 
            color: #D09000; 
            border: 1px solid #FFAA00;
            padding: 5px;
        """)
        right_layout.addWidget(self.console)

        # 3. Etiqueta de cabecera de campos del puerto serie
        # Timestamp_PC = 15 chars (%H:%M:%S.%f), Df_us = 5 chars (:>5)
        SERIAL_HEADER = (
            f"{'Timestamp_PC':<15},{'Df_us':>5},"
            "LibID,SmpCnt,Ts_us,PPG,SpO2,HR1,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R"
        )
        self.header_label = QtWidgets.QLabel(SERIAL_HEADER)
        self.header_label.setFont(QtGui.QFont("Consolas", 9))
        self.header_label.setWordWrap(False)
        self.header_label.setMinimumWidth(0)
        self.header_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,      # horizontal: ignorar sizeHint → no bloquea splitter
            QtWidgets.QSizePolicy.Preferred     # vertical: normal
        )
        self.header_label.setStyleSheet("""
            QLabel {
                background-color: #1A1000;
                color: #FFAA00;
                padding: 5px 8px;
                border: 1px solid #FFAA00;
                border-top: none;
            }
        """)
        right_layout.addWidget(self.header_label)

        
        # Splitter
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left_container = QtWidgets.QWidget()
        left_container.setLayout(left_layout)
        right_container = QtWidgets.QWidget()
        right_container.setLayout(right_layout)
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(right_container)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        
        content_layout.addLayout(self.sidebar_layout)
        content_layout.addWidget(self.splitter)
        main_layout.addLayout(content_layout)
        
        # Conectar Checkboxes
        self.check_red_raw.stateChanged.connect(lambda: self.curve_red.setVisible(self.check_red_raw.isChecked()))
        self.check_red_amb.stateChanged.connect(lambda: self.curve_amb_red.setVisible(self.check_red_amb.isChecked()))
        self.check_red_sub.stateChanged.connect(lambda: self.curve_red_sub.setVisible(self.check_red_sub.isChecked()))
        self.check_red_filt.stateChanged.connect(lambda: self.curve_red_filt.setVisible(self.check_red_filt.isChecked()))
        self.check_ir_raw.stateChanged.connect(lambda: self.curve_ir.setVisible(self.check_ir_raw.isChecked()))
        self.check_ir_amb.stateChanged.connect(lambda: self.curve_amb_ir.setVisible(self.check_ir_amb.isChecked()))
        self.check_ir_sub.stateChanged.connect(lambda: self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked()))
        self.check_ir_filt.stateChanged.connect(lambda: self.curve_ir_filt.setVisible(self.check_ir_filt.isChecked()))
        
        # Actualizar visibilidad inicial según checks
        self.curve_red.setVisible(self.check_red_raw.isChecked())
        self.curve_amb_red.setVisible(self.check_red_amb.isChecked())
        self.curve_red_sub.setVisible(self.check_red_sub.isChecked())
        self.curve_red_filt.setVisible(self.check_red_filt.isChecked())
        self.curve_ir.setVisible(self.check_ir_raw.isChecked())
        self.curve_amb_ir.setVisible(self.check_ir_amb.isChecked())
        self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked())
        self.curve_ir_filt.setVisible(self.check_ir_filt.isChecked())

        # Panel de log de estado
        self.log_panel = QtWidgets.QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFixedHeight(180)
        self.log_panel.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A2E;
                color: #E0E0E0;
                font-family: monospace;
                font-size: 16px;
                border: 1px solid #333355;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        main_layout.addWidget(self.log_panel)
        self.set_status(f"Conectando a {PORT}...", "info")
        
        # Conexión Serial
        try:
            self.ser = serial.Serial(PORT, BAUD, timeout=0.1)
            self._serial_queue = queue.Queue()
            self._reader_stop = threading.Event()
            self._reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self._reader_thread.start()
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")
            self.console.appendPlainText("Timestamp_PC   ,Df_us,$LibID,SmpCnt,Ts_us,PPG,SpO2,HR1,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R")
        except Exception as e:
            self.set_status(f"ERROR: No se pudo abrir {PORT}", "error")
            QtWidgets.QMessageBox.critical(self, "Error de Puerto", f"No se pudo abrir {PORT}:\n{str(e)}")
            sys.exit(1)
            
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
            self.btn_pause.setText("REANUDAR\nCAPTURA")
            self.set_status("Captura PAUSADA", "warning")
        else:
            self.btn_pause.setText("PAUSAR\nCAPTURA")
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")

    def toggle_pause_plot(self):
        self.is_plot_paused = self.btn_pause_plot.isChecked()
        if self.is_plot_paused:
            self.btn_pause_plot.setText("RESUME\nMAIN WINDOW")
        else:
            self.btn_pause_plot.setText("PAUSE\nMAIN WINDOW")

    def auto_stop_save(self):
        if self.is_saving:
            self.btn_save.setChecked(False)
            self.toggle_save()
            self.set_status("Stream finalizado (Auto-Stop 1000s)", "info")

    def auto_stop_save_raw(self):
        if self.is_saving_raw:
            self.btn_save_raw.setChecked(False)
            self.toggle_save_raw()
            self.set_status("Stream RAW finalizado (Auto-Stop 1000s)", "info")

    def toggle_save_raw(self):
        if self.is_paused:
            self.btn_save_raw.setChecked(False)
            self.set_status("No se puede grabar RAW en modo pausado", "error")
            return
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.is_saving_raw = self.btn_save_raw.isChecked()
        if self.is_saving_raw:
            self.btn_save_raw.setText("DETENER\nRAW")
            filename = f"ppg_data_raw_{now_str}.csv"
            try:
                self.save_file_raw = open(filename, "w")
                if self.frame_mode == "M2":
                    self.save_file_raw.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub\n")
                else:
                    self.save_file_raw.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,SpO2,HR1,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R\n")
                self.set_status(f"GRABANDO RAW (500 Hz): {filename}", "warning")
                self.auto_save_raw_timer.start(1000 * 1000)
            except Exception as e:
                self.set_status(f"Error al grabar RAW: {e}", "error")
                self.is_saving_raw = False
                self.btn_save_raw.setChecked(False)
        else:
            self.auto_save_raw_timer.stop()
            self.btn_save_raw.setText("GUARDAR\nRAW (500 Hz)")
            if self.save_file_raw:
                self.save_file_raw.close()
                self.save_file_raw = None
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")

    def toggle_save(self):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.is_paused:
            self.btn_save.setChecked(False)
            filename = f"ppg_data_snap_{now_str}.csv"
            try:
                with open(filename, "w") as f:
                    f.write("LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,HR1,SpO2,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_ppg[i]},{self.data_hr1[i]},{self.data_spo2[i]},{self.data_red[i]},{self.data_ir[i]},{self.data_amb_red[i]},{self.data_amb_ir[i]},{self.data_red_sub[i]},{self.data_ir_sub[i]},{self.data_red_filt[i]},{self.data_ir_filt[i]},{self.data_hr1_ppg[i]},{self.data_hr2[i]},{self.data_spo2_r[i]}\n")
                self.set_status(f"Memoria guardada en {filename}", "success")
            except Exception as e:
                self.set_status(f"Error al guardar memoria: {e}", "error")
        else:
            self.is_saving = self.btn_save.isChecked()
            if self.is_saving:
                self.btn_save.setText("DETENER\nGRABACIÓN")
                filename = f"ppg_data_stream_{now_str}.csv"
                try:
                    self.save_file = open(filename, "w")
                    if self.frame_mode == "M2":
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub\n")
                    else:
                        self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,SpO2,HR1,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R\n")
                    self.set_status(f"GRABANDO EN TIEMPO REAL: {filename}", "warning")
                    self.auto_save_timer.start(1000 * 1000)
                except Exception as e:
                    self.set_status(f"Error al grabar: {e}", "error")
                    self.is_saving = False
                    self.btn_save.setChecked(False)
            else:
                self.auto_save_timer.stop()
                self.btn_save.setText("GUARDAR\nDATOS")
                if self.save_file:
                    self.save_file.close()
                    self.save_file = None
                self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")

    def _serial_reader(self):
        """Dedicated thread: reads serial lines at full rate into a queue.
        Completely decoupled from the UI so no frames are lost during rendering."""
        while not self._reader_stop.is_set():
            try:
                line = self.ser.readline()
                if line:
                    self._serial_queue.put(line)
            except Exception:
                break

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
                        self.console.appendPlainText(line)
                        if 'mow' in line.lower() and 'frame' not in line.lower():
                            self.active_lib = "MOW"
                            self.frame_mode = "M1"
                            self._update_lib_button()
                            self.set_status("Librería activa: mow_afe4490", "info")
                        elif 'protocentral' in line.lower():
                            self.active_lib = "PROTOCENTRAL"
                            self.frame_mode = "M1"
                            self._update_lib_button()
                            self.set_status("Librería activa: protocentral", "info")
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
                                    self.console.appendPlainText(
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

                    if not self.is_plot_paused:
                        _console_lines.append(csv_line)

                    parts = line[1:].split(',')  # strip leading '$'
                    if len(parts) >= 17:
                        try:
                            # 0:LibID, 1:SmpCnt, 2:Ts_us, 3:PPG, 4:SpO2, 5:HR1, 6:RED, 7:IR, 8:AmbRED, 9:AmbIR, 10:REDSub, 11:IRSub, 12:REDFilt, 13:IRFilt, 14:HR1PPG, 15:HR2, 16:SpO2_R
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:17]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_ppg.append(p[2])
                            self.data_spo2.append(p[3])
                            self.data_hr1.append(p[4])
                            self.data_red.append(p[5])
                            self.data_ir.append(p[6])
                            self.data_amb_red.append(p[7])
                            self.data_amb_ir.append(p[8])
                            self.data_red_sub.append(p[9])
                            self.data_ir_sub.append(p[10])
                            self.data_red_filt.append(p[11])
                            self.data_ir_filt.append(p[12])
                            self.data_hr1_ppg.append(p[13])
                            self.data_hr2.append(p[14])
                            self.data_spo2_r.append(p[15])
                            hr3, _ = self.hr3_calc.update(p[10], SPO2_RECEIVED_FS)  # p[10]=IRSub=led1_aled1
                            self.data_hr3.append(hr3)
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
                            self.data_red_filt.append(0.0)
                            self.data_ir_filt.append(0.0)
                            self.data_hr1_ppg.append(0.0)
                            self.data_hr2.append(-1.0)
                            self.data_hr3.append(-1.0)
                            self.data_spo2_r.append(-1.0)
                        except ValueError: pass
                        else: _new_data = True

                # Batch console update: one appendPlainText call for all lines accumulated this cycle
                if _console_lines and not self.is_plot_paused:
                    self.console.appendPlainText('\n'.join(_console_lines))
                    if self.console.blockCount() > 500:
                        cursor = self.console.textCursor()
                        cursor.movePosition(QtGui.QTextCursor.Start)
                        cursor.select(QtGui.QTextCursor.BlockUnderCursor)
                        cursor.removeSelectedText()
                        cursor.deleteChar()
                    self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
                    self.console.horizontalScrollBar().setValue(0)

                if _new_data and not self.is_plot_paused:
                    self.p_spo2.setTitle(f"<b style='color:#44FF88'>SpO2: {self.data_spo2[-1]:.1f} %</b> &nbsp; <b style='color:#AAAAAA'>R: {self.data_spo2_r[-1]:.4f}</b>")
                    self.p_hr.setTitle(f"<b style='color:#FFDD44'>HR1: {self.data_hr1[-1]:.2f} bpm</b> &nbsp; <b style='color:#FF4444'>HR2: {self.data_hr2[-1]:.2f} bpm</b> &nbsp; <b style='color:#00CCFF'>HR3: {self.data_hr3[-1]:.2f} bpm</b>")
                    self.curve_ppg.setData(list(self.data_ppg)[-PPG_WINDOW_SIZE:])
                    self.curve_spo2.setData(list(self.data_spo2))
                    self.curve_hr1.setData(list(self.data_hr1))
                    self.curve_hr2.setData(list(self.data_hr2))
                    self.curve_hr3.setData(list(self.data_hr3))
                    self.curve_red.setData(list(self.data_red))
                    self.curve_ir.setData(list(self.data_ir))
                    self.curve_amb_red.setData(list(self.data_amb_red))
                    self.curve_amb_ir.setData(list(self.data_amb_ir))
                    self.curve_red_sub.setData(list(self.data_red_sub))
                    self.curve_ir_sub.setData(list(self.data_ir_sub))
                    self.curve_red_filt.setData(list(self.data_red_filt))
                    self.curve_ir_filt.setData(list(self.data_ir_filt))
                    self.curve_hr1_ppg.setData(list(self.data_hr1_ppg)[-PPG_WINDOW_SIZE:])

                # Sub-windows update independently of PAUSE MAIN WINDOW
                if _new_data:
                    if self.hrlab_window is not None:
                        self.hrlab_window.update_plots(self.data_ppg, self.data_timestamp_us, self.data_sample_counter)

                    if self.spo2lab_window is not None:
                        self.spo2lab_window.update_plots(
                            self.data_ir_sub, self.data_red_sub,
                            self.data_spo2, self.data_spo2_r,
                            self.data_timestamp_us, self.data_sample_counter)

                    if self.hr3lab_window is not None:
                        self.hr3lab_window.update_plots(
                            self.data_hr1, self.data_hr2, self.data_hr3, self.hr3_calc)

        except Exception as e:
            print(f"Error en loop: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # setSizes debe llamarse tras show() para que Qt no lo sobreescriba
        QtCore.QTimer.singleShot(0, lambda: self.splitter.setSizes([1800, 900]))
        QtCore.QTimer.singleShot(0, self._open_hr3lab_default)

    def _auto_close_chk(self):
        if self.save_file_chk is not None:
            self.save_file_chk.close()
            self.save_file_chk = None
        print(f"[save-chk] DONE: {self._chk_filename}")
        QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)

    def closeEvent(self, event):
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
    app.setStyle('Fusion')
    window = PPGMonitor(save_chk=args.save_chk, save_chk_duration=args.save_chk_duration)
    window.show()
    sys.exit(app.exec_())
