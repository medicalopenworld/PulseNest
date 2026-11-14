"""Offline test of HR3LAB (pulsenest_lab.py, spec §7.12): the methods of analysis family 3 side
by side on the library's HR3 window.

Three things, in this order:

1. HR3LabCalc, fed sample by sample, gives at every window exactly what pulsenest.hr_bench gives
   in batch on the same signal, across a stretch with the probe not applied. That is the point
   of the window's design: it calls the bench instead of re-implementing the methods, so what
   is watched live is what was measured offline. Its HR3_HPS is also the lab's own library
   mirror (HR3TestCalc), an independent implementation of today's HR3.
2. The three methods read a clean synthetic pulse; a probe that is not applied leaves no value
   and breaks the traces instead of joining them.
3. The window, opened from the monitor as the user does, is fed through the real frame loop
   ($M4 lines pushed into the serial queue: no port, no hub, no network), draws only when
   there is something new, pauses, starts over on a stream discontinuity and closes.

Run any time, no board, no hub and no stored capture needed:

    python test_pulsenest/hr3lab_test.py

Exit code 0 when every check passes.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import numpy as np  # noqa: E402
import pulsenest_lab as P  # noqa: E402
from pulsenest import hr_bench as hb  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  HR3LAB: the methods of family 3 side by side, offscreen")

FS = 500.0
BPM = 150.0
APPLIED = P.HR3TestCalc.PROBE_APPLIED

results = []


def check(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg)


def pulse(seconds, bpm=BPM, seed=1):
    """A PPG-like optical transmittance: a small pulsatile part with three harmonics on a DC."""
    t = np.arange(int(FS * seconds)) / FS
    f0 = bpm / 60.0
    ac = (np.sin(2 * np.pi * f0 * t) + 0.5 * np.sin(2 * np.pi * 2 * f0 * t + 0.6)
          + 0.25 * np.sin(2 * np.pi * 3 * f0 * t + 1.1))
    return 0.02 * (1.0 - 0.01 * ac) + 2e-7 * np.random.default_rng(seed).standard_normal(len(t))


def bench(ot, ps):
    """The bench, in batch, on the whole signal: one row per HR3 window."""
    d = {"OT_LED1": ot, "ps": ps.astype(np.int32), "fs": FS}
    Pw, end_rows, rate = hb.hr3_spectra(d)
    bin_res, b_lo, b_hi = hb.band_bins(rate)
    C, Cs = hb.hps(Pw, 3)
    hr_hps, sqi = hb.hps_estimate(Pw, C, Cs, rate)
    hr_sac, rho, _contrast, _R = hb.hr3_sac(Pw, rate)
    purity = hb.comb_purity(Pw, hr_sac, rate)
    A, dq = hb.band_cepstrum(hb.log_floor(Pw, b_lo, b_hi, P.HR3LabCalc.CEP_FLOOR_DB), bin_res)
    hr_cep, peak = hb.pick_quefrency(A, dq)
    return end_rows, np.column_stack([hr_hps, sqi, hr_sac, rho, purity, hr_cep, peak])


def m4_line(cnt, ot_led1, probe_state, hr1, hr2):
    """A $M4 frame as the board sends it, with its checksum (field list: lab spec §4.2)."""
    f = ["0"] * 38
    f[0], f[1], f[2] = "M4", str(cnt), str(cnt * 2000)
    f[13], f[14], f[16] = "1.50", "%.1f" % hr1, "%.1f" % hr2
    f[22] = str(probe_state)
    f[31] = f[32] = "%.9g" % ot_led1
    f[33], f[34], f[35] = "0x0", "500K", "500K"
    body = ",".join(f)
    chk = 0
    for ch in body:
        chk ^= ord(ch)
    return ("$%s*%02X" % (body, chk)).encode()


def main():
    app = QtWidgets.QApplication([])
    # Redirect BEFORE any window exists: closeEvent()s build their own QSettings.
    P.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_lab_hr3lab_test.ini")
    if os.path.exists(P.SETTINGS_FILE):
        os.remove(P.SETTINGS_FILE)

    print("\n--- 1. the lab's calculation is the bench's, window by window ---")
    ot = pulse(52.0)
    ps = np.full(len(ot), APPLIED)
    off = slice(int(25 * FS), int(27 * FS))          # 2 s with the probe not applied
    ps[off] = P.HR3TestCalc.PROBE_DISCONNECTED
    calc = P.HR3LabCalc()
    rows, got, lost_at = [], [], []
    for i in range(len(ot)):
        rev, had = calc.revision, calc.has_window
        calc.update(float(ot[i]), FS, int(ps[i]), i, 151.0, 149.5)
        if calc.revision != rev:
            if calc.has_window:
                rows.append(i)
                got.append((calc.hr_hps, calc.sqi_hps, calc.hr_sac, calc.rho, calc.purity,
                            calc.hr_cep, calc.cep_peak))
                check_mirror = (abs(calc.hr_hps - calc._fe.hr_bpm) < 1e-6
                                and abs(calc.sqi_hps - calc._fe.hr_sqi) < 1e-6)
                if not check_mirror:
                    lost_at.append(("mirror", i))
            elif had:
                lost_at.append(("lost", i))
    end_rows, want = bench(ot, ps)
    got = np.array(got)
    check(len(rows) == len(end_rows) and len(rows) > 50,
          f"same number of windows as the bench ({len(rows)} / {len(end_rows)})")
    check(np.array_equal(np.array(rows), end_rows), "each window ends on the same sample as the bench's")
    same = got.shape == want.shape and np.allclose(got, want, rtol=1e-9, atol=1e-9, equal_nan=True)
    check(same, "rate and quality index of HR3_HPS, HR3_SAC and HR3_CEP, and the comb purity, equal "
                "the bench's at every window"
          + ("" if same else f" (largest difference {np.nanmax(np.abs(got - want)):.3g})"))
    check(not [x for x in lost_at if x[0] == "mirror"],
          "HR3_HPS and its SQI equal the lab's library mirror (HR3TestCalc) at every window")
    lost = [i for kind, i in lost_at if kind == "lost"]
    check(lost == [off.start], f"the window is lost on the first sample with the probe not applied ({lost})")
    gap = np.diff(rows).max() / FS
    check(abs(gap - (2.0 + hb.BUF_LEN / hb.DECIM_TARGET_HZ + 0.5)) < 0.6,
          f"and comes back once a full window of applied signal is buffered (gap {gap:.2f} s)")

    print("\n--- 2. what the three methods read ---")
    last = got[-1]
    check(all(abs(last[k] - BPM) < 2.0 for k in (0, 2, 5)),
          f"HR3_HPS {last[0]:.1f}, HR3_SAC {last[2]:.1f}, HR3_CEP {last[5]:.1f} bpm on a {BPM:.0f} bpm pulse")
    check(last[1] > 0.9 and last[3] > 0.5 and last[4] > 0.9,
          f"quality indices on a clean pulse: SQI {last[1]:.2f}, rho {last[3]:.2f}, purity {last[4]:.2f}")
    h = calc.hist
    n_nan = sum(1 for v in h["sac"] if v != v)
    check(n_nan == 1 and len(h["t"]) == len(rows) + 1,
          "the history holds one entry per window plus one break (NaN) where the window was lost")
    check(abs(h["hr1"][-1] - 151.0) < 1e-9 and abs(h["hr2"][-1] - 149.5) < 1e-9,
          "the board's HR1 and HR2 of the same frame are stored with each window")
    calc.update(0.0, FS, P.HR3TestCalc.PROBE_DISCONNECTED, len(ot), -1.0, -1.0)
    check(not calc.has_window and calc.hr_sac != calc.hr_sac and calc.rho == 0.0,
          "probe not applied: no rate, quality indices at 0")
    d = P.HR3LabCalc.bench_defaults()
    check(d == {"margin_db": 6.0, "cap_db": 30.0, "alpha_sac": 0.8, "alpha_cep": 0.8},
          f"the info line reads the bench's own parameters ({d})")

    print("\n--- 3. the window, opened from the monitor and fed through the frame loop ---")
    w = P.PPGMonitor()
    check(not hasattr(w, "hr3_calc") and not hasattr(P, "HRFFTCalc"),
          "the prototype that was fed on every sample (HRFFTCalc) is gone")
    w.btn_hr3lab.setChecked(True)
    w.toggle_hr3lab()
    win = w.hr3lab_window
    check(win is not None and win.main_monitor is w, "HR3LAB opens from its sidebar button")
    check(win.calc.window_ms is w._py_timing['algo_hr3lab'],
          "the cost of each window goes to PYTHON TIMING (algo_hr3lab)")
    draws = []
    real_draw = win._draw
    win._draw = lambda: (draws.append(1), real_draw())

    sig = pulse(14.0, seed=2)
    for i in range(len(sig)):
        w._serial_queue.put(m4_line(i + 1, sig[i], APPLIED, 151.0, 149.5))
    w._process_frames_tick()
    c = win.calc
    n_expected = int((14.0 - hb.BUF_LEN / hb.DECIM_TARGET_HZ) / 0.5) + 1
    check(c.has_window and abs(len(c.hist["t"]) - n_expected) <= 1,
          f"the frame loop feeds it at the AFE rate: {len(c.hist['t'])} windows in 14 s of $M4 frames")
    check(abs(c.hr_sac - BPM) < 2.0 and abs(c.hr1 - 151.0) < 1e-9 and abs(c.hr2 - 149.5) < 1e-9,
          f"OT_LED1 (field 31), HR1 (14) and HR2 (16) reach it: HR3_SAC {c.hr_sac:.1f} bpm, "
          f"HR1 {c.hr1:.1f}, HR2 {c.hr2:.1f}")
    check(len(w._py_timing['algo_hr3lab']) > 0, "per-window cost recorded "
          f"({np.mean(w._py_timing['algo_hr3lab']):.1f} ms mean)")

    win.update_plots(w.data_pi)
    x_spec, y_spec = win.curve_spec.getData()
    x_rate, y_rate = win.curve_r_sac.getData()
    check(len(draws) == 1 and len(x_spec) > 100 and abs(float(np.max(y_spec))) < 1e-9,
          "first refresh draws: the spectrum in dB below the band maximum")
    check(len(x_rate) == len(c.hist["t"]) and abs(x_rate[-1]) < 0.6 and abs(y_rate[-1] - c.hr_sac) < 1e-9,
          "the rate plot holds one point per window, the last one at 'now'")
    teeth = win._teeth(c.hr_sac)
    check(len(teeth) == int(15.0 / (c.hr_sac / 60.0)) and abs(teeth[0] - c.hr_sac / 60.0) < 1e-12,
          f"comb ticks at n x the rate up to 15 Hz ({len(teeth)} teeth)")
    check("HR3_SAC" in win.p_sac.titleLabel.text and ("%.1f bpm" % c.hr_sac) in win.p_sac.titleLabel.text,
          "each method's header carries its rate")
    check(win._lbl_state.text() == "PROBE APPLIED" and win._lbl_pi.text() == "PI 1.50 %",
          f"context bar: {win._lbl_state.text()} / {win._lbl_pi.text()}")
    win.update_plots(w.data_pi)
    check(len(draws) == 1, "a refresh with nothing new draws nothing")

    print("\n--- PAUSE freezes the picture, not the methods ---")
    win._btn_pause.setChecked(True)
    win._toggle_pause()
    n_before = len(c.hist["t"])
    for i in range(1000):                                   # 2 s more
        w._serial_queue.put(m4_line(len(sig) + i + 1, sig[i], APPLIED, 151.0, 149.5))
    w._process_frames_tick()
    win.update_plots(w.data_pi)
    check(len(draws) == 1 and len(c.hist["t"]) > n_before and win._btn_pause.text() == "RESUME",
          f"paused: no redraw while {len(c.hist['t']) - n_before} more windows were computed")
    win._btn_pause.setChecked(False)
    win._toggle_pause()
    win.update_plots(w.data_pi)
    check(len(draws) == 2 and len(win.curve_r_sac.getData()[0]) == len(c.hist["t"]),
          "RESUME shows the present with the windows computed meanwhile")

    print("\n--- the monitor's own render tick, with PYTHON TIMING open ---")
    w.btn_python_timing.setChecked(True)
    w.toggle_python_timing()
    for _ in range(6):                                      # the timing table refreshes every 5 ticks
        w._render_pending = True
        w._refresh_plots_tick()
    table = w.python_timing_window._table
    cells = {table.item(r, 0).text(): r for r in range(table.rowCount()) if table.item(r, 0) is not None}
    algo = [r for label, r in cells.items() if "algo_hr3lab" in label]
    gap = [r for label, r in cells.items() if "HR3LabWindow.calc.gap_count" in label]
    check(len(algo) == 1 and float(table.item(algo[0], 1).text()) > 0.0,
          "PYTHON TIMING shows the cost per HR3 window "
          f"({table.item(algo[0], 1).text() if algo else '?'} ms mean)")
    check(len(gap) == 1 and table.item(gap[0], 3).text() == "0",
          "and the sample gaps of the window's front end (0)")
    check(len(w._py_timing['plot_hr3lab']) > 0, "the render tick refreshes the window (plot_hr3lab timed)")
    w.btn_python_timing.setChecked(False)
    w.toggle_python_timing()

    print("\n--- probe off, stream discontinuity, close ---")
    for i in range(20):
        w._serial_queue.put(m4_line(len(sig) + 1000 + i + 1, 0.0, P.HR3TestCalc.PROBE_DISCONNECTED, -1, -1))
    w._process_frames_tick()
    win.update_plots(w.data_pi)
    x_spec = win.curve_spec.getData()[0]
    check(not c.has_window and (x_spec is None or len(x_spec) == 0)
          and "--- bpm" in win.p_hps.titleLabel.text and not win.line_sac.isVisible(),
          "probe not applied: views cleared, headers read '--- bpm', chosen-value lines hidden")
    check(win._lbl_state.text() == "PROBE DISCONNECTED", "and the bar says so")
    w._stream_disc_t = 0.0                                   # outside the duplicate-suppression window
    w._on_stream_discontinuity("test")
    check(len(c.hist["t"]) == 0 and c.t_s == 0.0 and not c.has_window,
          "a stream discontinuity restarts the front end and the history")
    w.btn_hr3lab.setChecked(False)
    w.toggle_hr3lab()
    check(w.hr3lab_window is None and not w.btn_hr3lab.isChecked(), "closes from its button")
    for i in range(50):
        w._serial_queue.put(m4_line(i + 1, sig[i], APPLIED, 151.0, 149.5))
    w._process_frames_tick()
    check(w._serial_queue.empty() and c.t_s == 0.0,
          "frames keep draining with the window closed, and nothing is fed to it")

    w._disconnect_udp()
    w.close()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed —", "OK" if ok else "FAILED")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
