"""Offline test of HR1LAB (pulsenest_lab.py, spec §7.19): the methods of analysis family 1 side by side,
live or on a stored session, with every parameter editable.

Four things, in this order:

1. HR1LabCalc gives the bench's beats and rates. On a session (two applications of the probe and a
   stretch saturated) each chain's beats are those of pulsenest.hr1_bench.detect() on every applied
   run, and its rate, quality and publication every 0.5 s those of hr1_bench.apply_rule(). Fed live,
   sample by sample, it gives the same as on the session at once (the bench is block invariant), and
   its HR1_THR publishes what the lab's library mirror (HR1TestCalc, HR1TEST) publishes.
2. Editing a parameter restarts that chain only; edited() names what is not the measured value.
3. The window, opened from the monitor as the user does, is fed through the real frame loop ($M4
   lines pushed into the serial queue: no port, no hub, no network), draws, pauses, starts over on
   a stream discontinuity, shows a value typed but not applied in red and an applied one that is not
   the measured value in orange, and goes back to the measured values.
4. LOAD SESSION reads a session folder as the bench does (a synthetic one written here in the board's
   CSV format), draws the whole of it with the detail region, and LIVE goes back to the stream.

Run any time, no board, no hub and no stored capture needed:

    python test_pulsenest/hr1lab_test.py

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
from pulsenest import hr1_bench as h1  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  HR1LAB: the methods of family 1 side by side, offscreen")

FS = 500.0
APPLIED = P.HR1LabCalc.PROBE_APPLIED
CHAINS = P.HR1LabCalc.CHAINS

results = []


def check(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg)


def session_signal():
    """70 s: 140 bpm with wander, then 50 bpm; the probe off for 3 s and saturated for 0.5 s."""
    a, _ = h1.synth_ppg(FS, 45, bpm=140, noise=0.05, wander=0.5, seed=5)
    b, _ = h1.synth_ppg(FS, 25, bpm=50, noise=0.02, seed=6)
    x = np.concatenate([a, b])
    ps = np.full(len(x), APPLIED)
    ps[int(15 * FS):int(18 * FS)] = P.HR1Variant.PROBE_DISCONNECTED
    ps[int(55 * FS):int(55.5 * FS)] = P.HR1Variant.PROBE_ONLY_LED_SATURATING
    return x, ps


def bench(calc, x, ps):
    """Per chain: (beats [t s, rr s], outputs [t s, hr, q, published]) of the bench on every run."""
    on = (ps == APPLIED).astype(np.int8)
    e = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    out = {}
    for k in CHAINS:
        ch = P._HR1LabChain(k, calc.values[k])
        wb, wo = [], []
        for r0, r1 in zip(e[::2], e[1::2]):
            fe, det = ch._make(FS)
            det.trace = None
            if hasattr(det, "t1_trace"):
                det.t1_trace = None
            b = h1.detect(x[r0:r1], FS, fe, det)
            rows = h1.output_rows(r1 - r0, FS)
            hr, q, v = h1.apply_rule(b, FS, h1.RuleR0(), rows, latency_s=det.latency_s)
            wb.append(np.column_stack([(r0 + b[:, 0]) / FS, h1.rr_of(b, FS)]))
            wo.append(np.column_stack([(r0 + rows) / FS, hr, q, v.astype(float)]))
        out[k] = (np.concatenate(wb), np.concatenate(wo))
    return out


def m4_line(cnt, ot_led1, probe_state, hr1, hr2, hr3):
    """A $M4 frame as the board sends it, with its checksum (field list: lab spec §4.2)."""
    f = ["0"] * 38
    f[0], f[1], f[2] = "M4", str(cnt), str(cnt * 2000)
    f[13], f[14], f[16], f[18] = "1.50", "%.1f" % hr1, "%.1f" % hr2, "%.1f" % hr3
    f[22] = str(probe_state)
    f[31] = f[32] = "%.9g" % ot_led1
    f[33], f[34], f[35] = "0x0", "500K", "500K"
    body = ",".join(f)
    chk = 0
    for ch in body:
        chk ^= ord(ch)
    return ("$%s*%02X" % (body, chk)).encode()


def write_session(folder, x, ps):
    """A session folder in the board's CSV format (incunest_csv/1), as hr_bench.parse_columns reads it."""
    os.makedirs(folder, exist_ok=True)
    cols = ["LED2", "LED1", "OT_LED1", "OT_LED2", "ProbeState", "HR1", "HR1_SQI", "HR2", "HR3", "HR3_SQI"]
    with open(os.path.join(folder, "TEST_20261116_000000_p01.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("# format=incunest_csv/1\n")
        f.write("# @row 0 afe: cause=open afe_prf_hz=500 afe_numav=8\n")
        f.write(",".join(cols) + "\n")
        for i in range(len(x)):
            if i % 5000 == 0:
                f.write("# @row %d clock: smpcnt=%d host_epoch_us=%d\n" % (i, i, 1790000000000000 + i * 2000))
            f.write("0,0,%.17g,%.17g,%d,141.0,0.9,-1,142.0,0.8\n" % (x[i], x[i], ps[i]))


def main():
    app = QtWidgets.QApplication([])
    P.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_lab_hr1lab_test.ini")
    if os.path.exists(P.SETTINGS_FILE):
        os.remove(P.SETTINGS_FILE)
    x, ps = session_signal()

    print("\n--- 1. the lab's chains are the bench's ---")
    calc = P.HR1LabCalc()
    d = {"OT_LED1": x, "ps": ps.astype(np.int32), "fs": FS, "HR1": np.full(len(x), 141.0),
         "HR2": np.full(len(x), -1.0), "HR3": np.full(len(x), 142.0)}
    calc.load_session(d, "synthetic")
    want = bench(calc, x, ps)
    for k in CHAINS:
        wb, wo = want[k]
        gb = calc.chains[k].beats.data
        go = calc.chains[k].out.data
        go = go[np.isfinite(go[:, 3])]
        same_b = gb.shape == wb.shape and np.allclose(gb, wb, atol=1e-9, equal_nan=True)
        same_o = go.shape == wo.shape and np.allclose(go, wo, atol=1e-9, equal_nan=True)
        check(same_b and same_o and len(wb) > 100,
              f"{k}: on the session, {len(wb)} beats and {len(wo)} rates every 0.5 s equal the bench's "
              f"(detect + apply_rule on each applied run)")
    check(len(calc._runs()) == 3, "the session has three applied runs (probe off, then saturated)")

    live = P.HR1LabCalc()
    mirror = P.HR1TestCalc()
    step = int(round(0.5 * FS))
    pub_mirror = {}
    for i in range(len(x)):
        live.update(float(x[i]), FS, int(ps[i]), i, 141.0, -1.0, 142.0)
        mirror.update(float(x[i]), FS, int(ps[i]))
        pub_mirror[i] = (mirror.hr_bpm if mirror.hr_sqi > 0 else float('nan'))
    live._end_run()
    tmin = live.t_s - live.HIST_S + 1.0
    for k in CHAINS:
        a, b = calc.chains[k], live.chains[k]
        ga, gl = a.beats.data, b.beats.data
        ga, gl = ga[ga[:, 0] >= tmin], gl[gl[:, 0] >= tmin]
        oa, ol = a.out.data, b.out.data
        oa, ol = oa[oa[:, 0] >= tmin], ol[ol[:, 0] >= tmin]
        check(ga.shape == gl.shape and np.allclose(ga, gl, atol=1e-9, equal_nan=True)
              and oa.shape == ol.shape and np.allclose(oa, ol, atol=1e-9, equal_nan=True),
              f"{k}: fed live, sample by sample, it gives what it gives on the session at once "
              f"({len(gl)} beats, {len(ol)} rates in the last {live.HIST_S:.0f} s kept)")
    o = calc.chains["HR1_THR"].out.data
    o = o[np.isfinite(o[:, 3])]
    rows = np.rint(o[:, 0] * FS).astype(int)
    lab = np.where(o[:, 3] > 0.5, o[:, 1], np.nan)
    mir = np.array([pub_mirror[r] for r in rows])
    agree = np.mean(np.isclose(lab, mir, atol=1e-6, equal_nan=True))
    check(agree > 0.999, f"HR1_THR publishes what the library mirror (HR1TestCalc) publishes, "
                         f"at {100 * agree:.2f} % of the {len(rows)} reading times")
    check(np.mean(live.block_ms) < 5.0, f"a 0.1 s block of the three chains costs {np.mean(live.block_ms):.2f} ms")

    print("\n--- 2. editing a parameter ---")
    before = {k: calc.chains[k].beats.data.copy() for k in CHAINS}
    v = dict(calc.values["HR1_SSF"])
    v["eye_closing_s"] = 0.45
    calc.set_values("HR1_SSF", v)
    check(not np.array_equal(calc.chains["HR1_SSF"].beats.data, before["HR1_SSF"], equal_nan=True)
          and all(np.array_equal(calc.chains[k].beats.data, before[k], equal_nan=True)
                  for k in ("HR1_THR", "HR1_TERMA")),
          "on a session, a new SSF eye-closing reruns SSF and leaves THR and TERMA as they were")
    ed = calc.edited()
    check(list(ed) == ["HR1_SSF"] and ed["HR1_SSF"][0][:3] == ("Eye-closing", 0.45, 0.30),
          f"edited() names it with its measured value ({ed})")
    calc.set_values("HR1_SSF", P.HR1LabCalc.measured()["HR1_SSF"])
    check(calc.edited() == {} and np.array_equal(calc.chains["HR1_SSF"].beats.data, before["HR1_SSF"],
                                                 equal_nan=True),
          "back to the measured values, the same beats as before")
    m = P.HR1LabCalc.measured()
    check(m["HR1_THR"] == {"lp_hz": 15.0, "hp_hz": 0.5, "threshold_frac": 0.6, "decay_tau_s": 1.5,
                           "refractory_s": 0.185}
          and m["HR1_SSF"] == {"lp_hz": 15.0, "hp_hz": 0.3, "eye_closing_s": 0.30, "slope_w_s": 0.17,
                               "learn_s": 2.0}
          and m["HR1_TERMA"] == {"lp_hz": 15.0, "hp_hz": 0.5, "w1_s": 0.111, "w2_s": 0.667, "beta": 0.02},
          "measured values: THR = lib v0.122, SSF = part 3 of the study, TERMA = the papers' on v0.122")
    check((h1.TERMA_W1_S, h1.TERMA_W2_S, h1.TERMA_BETA) == (0.111, 0.667, 0.02)
          and (h1.LIB_THRESHOLD_FRAC, h1.LIB_MAX_DECAY_TAU_S, h1.LIB_REFRACTORY_S) == (0.6, 1.5, 0.185),
          "and the bench's own constants agree with them")

    print("\n--- 3. the window, opened from the monitor and fed through the frame loop ---")
    w = P.PPGMonitor()
    w.btn_hr1lab.setChecked(True)
    w.toggle_hr1lab()
    win = w.hr1lab_window
    check(win is not None and win.main_monitor is w, "HR1LAB opens from its sidebar button")
    check(win.calc.block_ms is w._py_timing['algo_hr1lab'], "the cost of each block goes to PYTHON TIMING (algo_hr1lab)")
    sig, _ = h1.synth_ppg(FS, 14, bpm=120, noise=0.02, seed=7)
    for i in range(len(sig)):
        w._serial_queue.put(m4_line(i + 1, sig[i], APPLIED, 121.0, 122.0, 123.0))
    w._process_frames_tick()
    c = win.calc
    check(all(c.chains[k].in_run for k in CHAINS) and abs(c.t_s - 14.0) < 0.01,
          f"the frame loop feeds it at the AFE rate ({c.t_s:.2f} s fed)")
    bd = c.board.data
    check(len(bd) > 20 and np.allclose(bd[-1, 1:], [121.0, 122.0, 123.0]),
          "the board's HR1 (field 14), HR2 (16) and HR3 (18) reach it")
    win.update_plots(w.data_pi)
    xs, ys = win.curve_sig["HR1_THR"].getData()
    check(len(xs) > 500 and abs(xs[-1]) < 0.15 and xs[0] > -P.HR1LabCalc.SHOW_S - 0.5,
          "the signal plots end at 'now' and hold the last 10 s")
    xm, ym = win.marks["HR1_SSF"].getData()
    check(len(xm) >= 15 and np.all(xm <= 0.0), f"each chain's beats are marked on its signal ({len(xm)} SSF onsets)")
    xr, yr = win.curve_rate["HR1_THR"].getData()
    pub = yr[np.isfinite(yr)]
    check(len(pub) > 10 and abs(np.median(pub) - 120.0) < 0.5 and abs(pub[-1] - 120.0) < 0.5,
          f"HR1_THR publishes 120 bpm on a 120 bpm pulse (median {np.median(pub):.1f}; the first value, "
          f"{pub[0]:.1f}, still holds the start-up's first RR)")
    xd, yd = win.curve_db["HR1_SSF"].getData()
    xa, ya = win.curve_da["HR1_TERMA"].getData()
    check(len(xd) > 2 and len(xa) > 100, "SSF's threshold T1 and TERMA's moving averages are drawn")
    check("120" in win.p_chain["HR1_THR"].titleLabel.text or "119" in win.p_chain["HR1_THR"].titleLabel.text,
          "each chain's header carries its rate")
    check(win._lbl_state.text() == "PROBE APPLIED" and win._lbl_pi.text() == "PI 1.50 %",
          f"context bar: {win._lbl_state.text()} / {win._lbl_pi.text()}")
    draws = []
    real = win._draw
    win._draw = lambda: (draws.append(1), real())
    win.update_plots(w.data_pi)
    check(len(draws) == 0, "a refresh with nothing new draws nothing")

    print("\n--- the parameter panel ---")
    sp = win._spins["HR1_SSF"]["eye_closing_s"]
    sp.setValue(0.40)
    check("#FF5555" in sp.styleSheet() and c.values["HR1_SSF"]["eye_closing_s"] == 0.30,
          "a value typed but not applied is red, and nothing changes yet")
    win._apply("HR1_SSF")
    check(c.values["HR1_SSF"]["eye_closing_s"] == 0.40 and "#FF5555" not in sp.styleSheet()
          and win._COL_EDIT in sp.styleSheet(), "APPLY: the chain runs with it, and the box turns orange")
    check("EDITED" in win._info_label.text() and "Eye-closing" in win._info_label.text(),
          "the info line names what is edited")
    check(c.chains["HR1_SSF"].in_run and c.chains["HR1_THR"].in_run, "live, the chain starts over where it is")
    win._measured("HR1_SSF")
    check(c.values["HR1_SSF"]["eye_closing_s"] == 0.30 and sp.styleSheet() == ""
          and "EDITED" not in win._info_label.text(), "MEASURED: back to the measured value, nothing marked")
    tl = win._spins["HR1_TERMA"]["w1_s"]
    tl.setValue(0.9 * 0.5)
    win._spins["HR1_TERMA"]["w2_s"].setValue(0.3)
    win._apply("HR1_TERMA")
    check(c.values["HR1_TERMA"]["w1_s"] == 0.111 and "W1" in win.statusBar().currentMessage(),
          "an impossible pair (W1 >= W2) is refused with a message")
    win._measured("HR1_TERMA")

    print("\n--- PAUSE, the render tick and PYTHON TIMING ---")
    win._draw = real
    win._btn_pause.setChecked(True)
    win._toggle_pause()
    x0 = win.curve_sig["HR1_THR"].getData()[0].copy()
    for i in range(1000):
        w._serial_queue.put(m4_line(len(sig) + i + 1, sig[i], APPLIED, 121.0, 122.0, 123.0))
    w._process_frames_tick()
    win.update_plots(w.data_pi)
    check(np.array_equal(win.curve_sig["HR1_THR"].getData()[0], x0) and win._btn_pause.text() == "RESUME",
          "paused: the picture stays while 2 s more are computed")
    win._btn_pause.setChecked(False)
    win._toggle_pause()
    w.btn_python_timing.setChecked(True)
    w.toggle_python_timing()
    for _ in range(6):
        w._render_pending = True
        w._refresh_plots_tick()
    table = w.python_timing_window._table
    cells = {table.item(r, 0).text(): r for r in range(table.rowCount()) if table.item(r, 0) is not None}
    algo = [r for label, r in cells.items() if "algo_hr1lab" in label]
    gap = [r for label, r in cells.items() if "HR1LabWindow.calc.gap_count" in label]
    check(len(algo) == 1 and float(table.item(algo[0], 1).text()) > 0.0,
          f"PYTHON TIMING shows the cost per block ({table.item(algo[0], 1).text() if algo else '?'} ms mean)")
    check(len(gap) == 1 and table.item(gap[0], 3).text() == "0", "and the window's sample gaps (0)")
    check(len(w._py_timing['plot_hr1lab']) > 0, "the render tick refreshes the window (plot_hr1lab timed)")
    w.btn_python_timing.setChecked(False)
    w.toggle_python_timing()

    print("\n--- probe off, stream discontinuity ---")
    for i in range(100):
        w._serial_queue.put(m4_line(len(sig) + 1000 + i + 1, 0.0, P.HR1Variant.PROBE_DISCONNECTED, -1, -1, -1))
    w._process_frames_tick()
    win.update_plots(w.data_pi)
    check(not any(c.chains[k].in_run for k in CHAINS) and "--- bpm" in win.p_chain["HR1_SSF"].titleLabel.text,
          "probe not applied: the chains stop, the headers read '--- bpm'")
    w._stream_disc_t = 0.0
    w._on_stream_discontinuity("test")
    check(c.t_s == 0.0 and len(c.chains["HR1_THR"].sig.data) == 0 and len(c.board.data) == 0,
          "a stream discontinuity restarts the clock and every trace")

    print("\n--- 4. LOAD SESSION and LIVE ---")
    tmp = tempfile.mkdtemp(prefix="hr1lab_test_")
    P.CAPTURES_DIR = tmp                              # the bench's cache goes there, not into captures/
    folder = os.path.join(tmp, "TEST_SESSION")
    write_session(folder, x, ps)
    ok = win.load_session(folder)
    check(ok and c.offline and c.source == "TEST_SESSION" and win._btn_live.isEnabled()
          and not win._btn_pause.isEnabled(), "a session folder loads: SOURCE names it, LIVE is enabled")
    for k in CHAINS:
        wb, wo = want[k]
        gb = c.chains[k].beats.data
        check(gb.shape == wb.shape and np.allclose(gb, wb, atol=1e-6, equal_nan=True),
              f"{k}: read from the CSV as the bench reads it, the same {len(wb)} beats as in part 1")
    xs, _ = win.curve_sig["HR1_THR"].getData()
    xr, _ = win.curve_rate["HR1_SSF"].getData()
    lo, hi = win.region.getRegion()
    rng = win.p_chain["HR1_THR"].viewRange()[0]
    check(xs[0] < 1.0 and xs[-1] > 69.0 and xr[-1] > 69.0, "the whole session is drawn, X = seconds from the first row")
    check(win.region.isVisible() and abs(lo) < 1e-6 and abs(hi - 20.0) < 1e-6 and abs(rng[0] - lo) < 0.5
          and abs(rng[1] - hi) < 0.5, "the detail region (0-20 s) sets the signal plots' span")
    win.region.setRegion((30.0, 40.0))
    rng = win.p_chain["HR1_THR"].viewRange()[0]
    check(abs(rng[0] - 30.0) < 0.5 and abs(rng[1] - 40.0) < 0.5, "dragging the region moves the signal plots")
    check("published" in win.p_chain["HR1_THR"].titleLabel.text, "on a session the headers give the share published")
    n_before = c.n
    for i in range(50):
        w._serial_queue.put(m4_line(i + 1, sig[i], APPLIED, 121.0, 122.0, 123.0))
    w._process_frames_tick()
    check(c.n == n_before, "while a session is loaded the live stream is ignored")
    win._go_live()
    check(not c.offline and c.source == "live" and not win.region.isVisible() and not win._btn_live.isEnabled(),
          "LIVE goes back to the stream")
    for i in range(500):
        w._serial_queue.put(m4_line(i + 1, sig[i], APPLIED, 121.0, 122.0, 123.0))
    w._process_frames_tick()
    check(c.chains["HR1_THR"].in_run and abs(c.t_s - 1.0) < 0.01, "and is fed again")

    w.btn_hr1lab.setChecked(False)
    w.toggle_hr1lab()
    check(w.hr1lab_window is None and not w.btn_hr1lab.isChecked(), "closes from its button")
    w._disconnect_udp()
    w.close()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed —", "OK" if ok else "FAILED")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
