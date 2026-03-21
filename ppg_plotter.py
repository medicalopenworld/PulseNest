import sys
import serial
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
                              hr_min=38, hr_max=252, prominence=0.1):
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
                              hr_min=38, hr_max=252, prominence=0.1):
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
BAUD = 115200
WINDOW_SIZE     = 500   # 10 s @ 50 Hz (500 Hz / SERIAL_DOWNSAMPLING_RATIO=10)
PPG_WINDOW_SIZE = 500   # 10 s — same as WINDOW_SIZE

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

class SpO2LabWindow(QtWidgets.QMainWindow):
    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("SPO2LAB")
        self.resize(1400, 800)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # QSplitter for exact column proportions (1:1:1)
        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.setHandleWidth(2)
        main_layout.addWidget(self._splitter)

        self._col_a = pg.GraphicsLayoutWidget()
        self._col_b = pg.GraphicsLayoutWidget()
        self._col_c = pg.GraphicsLayoutWidget()
        self._splitter.addWidget(self._col_a)
        self._splitter.addWidget(self._col_b)
        self._splitter.addWidget(self._col_c)

        # Plots — column A
        self.p_1a = self._col_a.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1A</b>")
        self.p_2a = self._col_a.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2A</b>")
        self.p_3a = self._col_a.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3A</b>")

        # Plots — column B
        self.p_1b = self._col_b.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1B</b>")
        self.p_2b = self._col_b.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2B</b>")
        self.p_3b = self._col_b.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3B</b>")

        # Plots — column C
        self.p_1c = self._col_c.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1C</b>")
        self.p_2c = self._col_c.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2C</b>")
        self.p_3c = self._col_c.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3C</b>")

        for plot in [self.p_1a, self.p_1b, self.p_1c,
                     self.p_2a, self.p_2b, self.p_2c,
                     self.p_3a, self.p_3b, self.p_3c]:
            plot.showGrid(x=True, y=True, alpha=0.3)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._set_splitter_sizes)

    def _set_splitter_sizes(self):
        w = self._splitter.width()
        if w > 0:
            third = w // 3
            self._splitter.setSizes([third, third, w - 2 * third])

    def closeEvent(self, event):
        if self.main_monitor is not None:
            self.main_monitor.btn_spo2lab.setChecked(False)
            self.main_monitor.spo2lab_window = None
        super().closeEvent(event)


class HRLab2Window(QtWidgets.QMainWindow):
    def __init__(self, main_monitor):
        super().__init__()
        self.main_monitor = main_monitor
        self.setWindowTitle("HRLAB2")
        self.resize(1400, 800)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # QSplitter for exact column proportions (2:1:1)
        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.setHandleWidth(2)
        main_layout.addWidget(self._splitter)

        self._col_a = pg.GraphicsLayoutWidget()
        self._col_b = pg.GraphicsLayoutWidget()
        self._col_c = pg.GraphicsLayoutWidget()
        self._splitter.addWidget(self._col_a)
        self._splitter.addWidget(self._col_b)
        self._splitter.addWidget(self._col_c)

        # Plots — column A
        self.p_1a = self._col_a.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1A</b>")
        self.p_2a = self._col_a.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2A</b>")
        self.p_3a = self._col_a.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3A</b>")

        # Plots — column B
        self.p_1b = self._col_b.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1B</b>")
        self.p_2b = self._col_b.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2B</b>")
        self.p_3b = self._col_b.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3B</b>")

        # Plots — column C
        self.p_1c = self._col_c.addPlot(row=0, col=0, title="<b style='color:#FFFFFF'>1C</b>")
        self.p_2c = self._col_c.addPlot(row=1, col=0, title="<b style='color:#FFFFFF'>2C</b>")
        self.p_3c = self._col_c.addPlot(row=2, col=0, title="<b style='color:#FFFFFF'>3C</b>")

        for plot in [self.p_1a, self.p_1b, self.p_1c,
                     self.p_2a, self.p_2b, self.p_2c,
                     self.p_3a, self.p_3b, self.p_3c]:
            plot.showGrid(x=True, y=True, alpha=0.3)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._set_splitter_sizes)

    def _set_splitter_sizes(self):
        w = self._splitter.width()
        if w > 0:
            self._splitter.setSizes([w // 2, w // 4, w // 4])

    def closeEvent(self, event):
        if self.main_monitor is not None:
            self.main_monitor.btn_hrlab2.setChecked(False)
            self.main_monitor.hrlab2_window = None
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
            window_n  = int(round(8.0 * fs))
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
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.0f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
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
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.0f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
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
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.0f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
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
                        f"<b style='color:{hr_color}'>HR: {r.hr_bpm:.0f} bpm &nbsp; corr: {r.peak_val:.2f}</b>"
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
        Actualiza la barra de estado con colores y estilos llamativos según el tipo.
        tipos: 'info' (azul), 'success' (verde), 'warning' (naranja), 'error' (rojo)
        """
        colors = {
            "success": ("#00FF88", "rgba(0, 255, 136, 0.15)", "#00FF88"),
            "warning": ("#FFDD44", "rgba(255, 221, 68, 0.15)", "#FFDD44"),
            "error":   ("#FF4444", "rgba(255, 68, 68, 0.15)", "#FF4444"),
            "info":    ("#44AAFF", "rgba(68, 170, 255, 0.15)", "#44AAFF")
        }
        
        fg, bg, border = colors.get(status_type, colors["info"])
        
        self.status_bar.setText(f" ●  {text.upper()}")
        self.status_bar.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                font-size: 24px;
                font-weight: 800;
                padding: 20px;
                border: 2px solid {border};
                border-radius: 10px;
                margin: 10px 0px 5px 0px;
            }}
        """)

    def __init__(self):
        super().__init__()
        
        # Configuración Ventana Principal
        self.setWindowTitle("AFE4490 Advanced Monitor (by Medical Open World)")
        self.resize(2700, 1600)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        
        # Estructuras de Datos
        self.data_lib_id = deque(["?"]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_sample_counter = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_timestamp_us = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ppg = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr  = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
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

        self.is_paused = False
        self.is_plot_paused = False
        self.last_time = None
        self.active_lib = "MOW"  # must match default in main.cpp (start_mow)
        
        self.is_saving = False
        self.save_file = None
        self.hrlab_window = None
        self.spo2lab_window = None
        self.hrlab2_window = None
        
        self.auto_save_timer = QtCore.QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_stop_save)
        
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
        self.check_red_sub = create_check("RED (clean)", "#FF8888", False)
        self.check_red_filt = create_check("RED (filt)", "#FF0000", True)
        
        self.sidebar_layout.addWidget(self.check_red_raw)
        self.sidebar_layout.addWidget(self.check_red_amb)
        self.sidebar_layout.addWidget(self.check_red_sub)
        self.sidebar_layout.addWidget(self.check_red_filt)
        
        self.label_ir = QtWidgets.QLabel("IR")
        self.label_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 20px;")
        self.sidebar_layout.addWidget(self.label_ir)
        
        self.check_ir_raw = create_check("IR (raw)", "#FFFFFF", False)
        self.check_ir_amb = create_check("Ambient IR", "#00FFFF", False)
        self.check_ir_sub = create_check("IR (clean)", "#88CCFF", False)
        self.check_ir_filt = create_check("IR (filt)", "#44AAFF", True)
        
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

        self.btn_pause_plot = QtWidgets.QPushButton("PAUSAR\nGRÁFICAS")
        self.btn_pause_plot.setCheckable(True)
        self.btn_pause_plot.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause_plot.clicked.connect(self.toggle_pause_plot)
        self.sidebar_layout.addWidget(self.btn_pause_plot)
        
        self.btn_save = QtWidgets.QPushButton("GUARDAR\nDATOS")
        self.btn_save.setCheckable(True)
        self.btn_save.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.toggle_save)
        self.sidebar_layout.addWidget(self.btn_save)

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

        self.btn_hrlab2 = QtWidgets.QPushButton("HRLAB2")
        self.btn_hrlab2.setCheckable(True)
        self.btn_hrlab2.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_hrlab2.clicked.connect(self.toggle_hrlab2)
        self.sidebar_layout.addWidget(self.btn_hrlab2)

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
        self.p_spo2.setYRange(80, 100)

        self.p_hr = stats_layout.addPlot(title="<b style='color:#FFDD44'>HEART RATE (BPM)</b>")
        self.curve_hr  = self.p_hr.plot(pen=pg.mkPen('#FFDD44', width=3), name="HR1")
        self.curve_hr2 = self.p_hr.plot(pen=pg.mkPen('#FF4444', width=1.5), name="HR2")
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
            "LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2"
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

        # Etiqueta de estado
        self.status_bar = QtWidgets.QLabel()
        self.status_bar.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(self.status_bar)
        self.set_status(f"Conectando a {PORT}...", "info")
        
        # Conexión Serial
        try:
            self.ser = serial.Serial(PORT, BAUD, timeout=0.1)
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")
            self.console.appendPlainText("Timestamp_PC   ,Df_us,$LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2")
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

    def _open_hrlab2_default(self):
        self.btn_hrlab2.setChecked(True)
        self.toggle_hrlab2()

    def toggle_hrlab2(self):
        if self.btn_hrlab2.isChecked():
            self.hrlab2_window = HRLab2Window(self)
            self.hrlab2_window.show()
        else:
            if self.hrlab2_window is not None:
                self.hrlab2_window.main_monitor = None
                self.hrlab2_window.close()
                self.hrlab2_window = None

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
            self.btn_pause_plot.setText("REANUDAR\nGRÁFICAS")
        else:
            self.btn_pause_plot.setText("PAUSAR\nGRÁFICAS")

    def auto_stop_save(self):
        if self.is_saving:
            self.btn_save.setChecked(False)
            self.toggle_save()
            self.set_status("Stream finalizado (Auto-Stop 1000s)", "info")

    def toggle_save(self):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.is_paused:
            self.btn_save.setChecked(False)
            filename = f"ppg_data_snap_{now_str}.csv"
            try:
                with open(filename, "w") as f:
                    f.write("LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,HR,SpO2,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_ppg[i]},{self.data_hr[i]},{self.data_spo2[i]},{self.data_red[i]},{self.data_ir[i]},{self.data_amb_red[i]},{self.data_amb_ir[i]},{self.data_red_sub[i]},{self.data_ir_sub[i]},{self.data_red_filt[i]},{self.data_ir_filt[i]},{self.data_hr1_ppg[i]},{self.data_hr2[i]}\n")
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
                    self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,HR,SpO2,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2\n")
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

    def update_data(self):
        if self.is_paused:
            # Keep draining the serial buffer so the ESP32 doesn't block
            if hasattr(self, 'ser') and self.ser.is_open and self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)
            return
        try:
            if hasattr(self, 'ser') and self.ser.is_open and self.ser.in_waiting > 0:
                while self.ser.is_open and self.ser.in_waiting > 0:
                    line_raw = self.ser.readline()
                    try:
                        line = line_raw.decode('utf-8', errors='ignore').strip()
                    except: continue
                    if not line: continue

                    # Confirmation messages from ESP32 (e.g. "# Switched to mow_afe4490")
                    if line.startswith('#'):
                        self.console.appendPlainText(line)
                        if 'mow' in line.lower():
                            self.active_lib = "MOW"
                            self._update_lib_button()
                            self.set_status("Librería activa: mow_afe4490", "info")
                        elif 'protocentral' in line.lower():
                            self.active_lib = "PROTOCENTRAL"
                            self._update_lib_button()
                            self.set_status("Librería activa: protocentral", "info")
                        continue

                    current_time_perf = time.perf_counter()
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")
                    diff_us = int((current_time_perf - self.last_time) * 1e6) if self.last_time is not None else 0
                    self.last_time = current_time_perf
                    
                    csv_line = f"{timestamp},{diff_us:>5},{line}"
                    self.console.appendPlainText(csv_line)
                    if getattr(self, 'is_saving', False) and getattr(self, 'save_file', None):
                        self.save_file.write(csv_line + "\n")
                        self.save_file.flush()
                    if self.console.blockCount() > 500:
                        cursor = self.console.textCursor()
                        cursor.movePosition(QtGui.QTextCursor.Start)
                        cursor.select(QtGui.QTextCursor.BlockUnderCursor)
                        cursor.removeSelectedText()
                        cursor.deleteChar()
                    self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
                    self.console.horizontalScrollBar().setValue(0)
                    
                    if not line.startswith('$'):
                        continue
                    parts = line[1:].split(',')  # strip leading '$'
                    if len(parts) >= 16:
                        try:
                            # 0:LibID, 1:SmpCnt, 2:Ts_us, 3:PPG, 4:SpO2, 5:HR, 6:RED, 7:IR, 8:AmbRED, 9:AmbIR, 10:REDSub, 11:IRSub, 12:REDFilt, 13:IRFilt, 14:HR1PPG, 15:HR2
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:16]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_ppg.append(p[2])
                            self.data_spo2.append(p[3])
                            self.data_hr.append(p[4])
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
                        except ValueError: pass
                
                if not self.is_plot_paused:
                    self.p_spo2.setTitle(f"<b style='color:#44FF88'>SpO2: {self.data_spo2[-1]:.1f} %</b>")
                    self.p_hr.setTitle(f"<b style='color:#FFDD44'>HR: {self.data_hr[-1]:.1f} bpm</b>")
                    self.curve_ppg.setData(list(self.data_ppg)[-PPG_WINDOW_SIZE:])
                    self.curve_spo2.setData(list(self.data_spo2))
                    self.curve_hr.setData(list(self.data_hr))
                    self.curve_hr2.setData(list(self.data_hr2))
                    self.curve_red.setData(list(self.data_red))
                    self.curve_ir.setData(list(self.data_ir))
                    self.curve_amb_red.setData(list(self.data_amb_red))
                    self.curve_amb_ir.setData(list(self.data_amb_ir))
                    self.curve_red_sub.setData(list(self.data_red_sub))
                    self.curve_ir_sub.setData(list(self.data_ir_sub))
                    self.curve_red_filt.setData(list(self.data_red_filt))
                    self.curve_ir_filt.setData(list(self.data_ir_filt))
                    self.curve_hr1_ppg.setData(list(self.data_hr1_ppg)[-PPG_WINDOW_SIZE:])

                    if self.hrlab_window is not None:
                        self.hrlab_window.update_plots(self.data_ppg, self.data_timestamp_us, self.data_sample_counter)

        except Exception as e:
            print(f"Error en loop: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # setSizes debe llamarse tras show() para que Qt no lo sobreescriba
        QtCore.QTimer.singleShot(0, lambda: self.splitter.setSizes([1800, 900]))
        QtCore.QTimer.singleShot(0, self._open_hrlab_default)

    def closeEvent(self, event):
        if getattr(self, 'is_saving', False) and getattr(self, 'save_file', None):
            self.save_file.close()
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        if self.hrlab_window is not None:
            self.hrlab_window.main_monitor = None
            self.hrlab_window.close()
        if self.spo2lab_window is not None:
            self.spo2lab_window.main_monitor = None
            self.spo2lab_window.close()
        if self.hrlab2_window is not None:
            self.hrlab2_window.main_monitor = None
            self.hrlab2_window.close()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = PPGMonitor()
    window.show()
    sys.exit(app.exec_())
