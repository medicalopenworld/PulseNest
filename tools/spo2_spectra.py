"""Spectrograms and HPS-grams of a subject's sessions, 0-15 Hz, mirroring the library's HR3 chain.

Chain (spec 5.4): OT_LED1 (IR) -> 4th-order Butterworth LP 15 Hz (causal) -> decimate x10 (50 Hz)
-> 512-sample window (10.24 s), mean removed, Hann -> |FFT|^2 -> HPS[k] = P[k] P[2k] P[3k], k up to
nyquist/3. Hop 25 samples (0.5 s), like hr3_update_interval. RED (OT_LED2) gets the same spectrogram.

    python tools/spo2_spectra.py SUBJ10 [out_dir]

Default out_dir: captures/sessions/<SUBJ>/Spectra. One PNG per session, named after it (the
Spectra folders of SUBJ08-SUBJ11 were made with it on 2026-10-16).
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.spo2_bias_analysis import parse_board_session, parse_reference  # noqa: E402

FS = 500.0
DECIM = 10
FS_D = FS / DECIM
NFFT = 512
HOP = 25
F_MAX = 15.0


def load_ot(session_dir):
    parts = sorted(glob.glob(os.path.join(session_dir, "*_p[0-9][0-9].csv")))
    dfs = []
    for p in parts:
        df = pd.read_csv(p, comment="#", usecols=["OT_LED1", "OT_LED2", "HR3", "HR3_SQI", "SpO2", "ProbeState"])
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def spectrogram(x):
    """Columns every HOP decimated samples; returns f, t_idx (decimated sample index of window end), P."""
    sos = butter(4, 15.0, btype="low", fs=FS, output="sos")
    xd = sosfilt(sos, x)[::DECIM]
    win = np.hanning(NFFT)
    ends = np.arange(NFFT, len(xd) + 1, HOP)
    P = np.empty((NFFT // 2 + 1, len(ends)))
    for j, e in enumerate(ends):
        seg = xd[e - NFFT:e]
        seg = (seg - seg.mean()) * win
        P[:, j] = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(NFFT, 1 / FS_D)
    return f, ends, P


def hps(P):
    n = P.shape[0]
    kmax = (n - 1) // 3
    H = np.zeros_like(P)
    k = np.arange(1, kmax + 1)
    H[k] = P[k] * P[2 * k] * P[3 * k]
    return H


def main():
    subject = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "captures", "sessions", subject, "Spectra")
    os.makedirs(out, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dirs = sorted(d for d in glob.glob(os.path.join(ROOT, "captures", "sessions", subject, f"{subject}_*_*_*"))
                  if os.path.isdir(d))
    for d in dirs:
        name = os.path.basename(d)
        df = load_ot(d)
        board, _ = parse_board_session(d)
        ref_t, ref_spo2, _ = parse_reference(d)
        import datetime
        import matplotlib.dates as mdates
        t0 = board["t"][0]
        t_min = mdates.date2num([datetime.datetime.fromtimestamp(v / 1e6) for v in board["t"]])
        ref_x = mdates.date2num([datetime.datetime.fromtimestamp(v / 1e6) for v in ref_t])
        ir, red = df["OT_LED1"].to_numpy(float), df["OT_LED2"].to_numpy(float)
        f, ends, P_ir = spectrogram(ir)
        _, _, P_red = spectrogram(red)
        H = hps(P_ir)
        # column time = window end, in minutes from session start (decimated index -> original row)
        tc = t_min[np.minimum(ends * DECIM - 1, len(t_min) - 1)]
        fm = f <= F_MAX
        # per-column normalisation to the HPS maximum INSIDE the HR search band (30-260 BPM), as the
        # library's peak search does; shown in dB below that maximum
        band = (f >= 0.5) & (f <= 260 / 60)
        Hn = 10 * np.log10(np.maximum(H, 1e-300) / np.maximum(H[band].max(axis=0, keepdims=True), 1e-300))
        hr3 = df["HR3"].to_numpy(float)
        hr3 = np.where(hr3 > 0, hr3, np.nan)

        fig, axes = plt.subplots(4, 1, figsize=(18, 13), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 3, 3, 1.6]})
        for ax, P, lab in ((axes[0], P_ir, "IR (OT_LED1)"), (axes[1], P_red, "RED (OT_LED2)")):
            dB = 10 * np.log10(np.maximum(P[fm], 1e-30))
            vmax = np.percentile(dB, 99.5)
            ax.pcolormesh(tc, f[fm], dB, shading="nearest", cmap="magma", vmin=vmax - 60, vmax=vmax)
            ax.set_ylabel("Hz")
            ax.set_title(f"{lab}: power spectrogram, 10.24 s Hann windows every 0.5 s, dB (top 60 dB)", fontsize=10)
            ax.plot(t_min[::100], hr3[::100] / 60 + 0.35, ".", ms=1.0, color="cyan", alpha=0.5)
        ax = axes[2]
        ax.pcolormesh(tc, f[fm], Hn[fm], shading="nearest", cmap="magma", vmin=-40, vmax=0)
        for yb in (0.5, 260 / 60):
            ax.axhline(yb, color="lime", lw=0.6, ls=":", alpha=0.8)
        ax.plot(t_min[::100], hr3[::100] / 60 + 0.35, ".", ms=1.2, color="cyan", alpha=0.6, label="firmware HR3 / 60, drawn 0.35 Hz above")
        ax.axhline(FS_D / 2 / 3, color="w", lw=0.6, ls="--", alpha=0.6)
        ax.set_ylabel("Hz")
        ax.set_title("IR HPS = P[k] P[2k] P[3k], dB below each column's maximum inside the HR band 0.5-4.33 Hz "
                     "(dotted: band; dashed: nyquist/3 cap; cyan: firmware HR3)", fontsize=10)
        ax.legend(loc="upper right", fontsize=8)
        ax = axes[3]
        ps_ok = np.isin(board["ps"], (1, 2))
        ax.plot(t_min[::25], np.where(ps_ok, board["spo2"], np.nan)[::25], "-", lw=0.7, color="tab:blue", label="ours")
        ax.plot(ref_x, ref_spo2, ".", ms=2.5, color="tab:red", label="reference")
        ax.set_ylim(70, 102)
        ax.set_ylabel("SpO2 [%]")
        ax2 = ax.twinx()
        ax2.plot(t_min[::50], hr3[::50], ".", ms=1.5, color="tab:green", alpha=0.6)
        ax2.set_ylabel("HR3 [BPM]", color="tab:green")
        ax2.set_ylim(0, 250)
        ax.legend(loc="lower left", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.set_xlabel("local wall-clock time [HH:MM:SS]")
        ax.grid(True, alpha=0.3)
        for a in axes[:3]:
            a.set_ylim(0, F_MAX)
        fig.suptitle(f"{name}: spectra of the OT signals, 0-{F_MAX:.0f} Hz", fontsize=12)
        fig.tight_layout()
        fig.savefig(os.path.join(out, f"{name}_spectra.png"), dpi=110)
        plt.close(fig)
        print(name, "columns", len(ends), "HR3 valid frac %.2f" % np.isfinite(hr3).mean())


if __name__ == "__main__":
    main()
