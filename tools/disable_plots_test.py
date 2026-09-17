"""Offline regression for the DISABLE PLOTTING toggle (pulsenest_lab.py, spec §6.5.2).

Instantiates PPGMonitor offscreen, opens a handful of the pyqtgraph-bearing subwindows, and
checks the toggle's whole contract in one pass: it closes every one of them through their own
existing toggle_xxx() (main_monitor -> None, window -> None, geometry saved -- nothing new, a
synthetic click on the same button the user would press), locks their buttons so none can
reopen while it is on, releases them when turned back off, and its state survives a
save/restore round trip through QSettings so a relaunch after a crash does not silently let
plotting back on.

Run any time, no board and no hub needed:

    python tools/disable_plots_test.py

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

import pulsenest_lab as P  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

print(f"== {os.path.basename(__file__)} ==  DISABLE PLOTTING toggle, offscreen")

results = []


def check(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg)


def main():
    app = QtWidgets.QApplication([])
    # Redirect BEFORE instantiation, like every other offscreen test here: patching
    # _save_settings alone is not enough, closeEvent()s build their own QSettings.
    P.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pulsenest_lab_disable_plots_test.ini")
    if os.path.exists(P.SETTINGS_FILE):
        os.remove(P.SETTINGS_FILE)
    w = P.PPGMonitor()

    check(not w.btn_disable_plots.isChecked(), "starts enabled (nothing persisted yet)")
    check(all(getattr(w, n).isEnabled() for n in w._PLOT_WINDOW_BUTTONS),
          "every plot-window button starts enabled")

    # Open three, of different kinds: a *LAB, a *TEST, and the odd one out (LIB CONFIG, which
    # is NOT fed by the 200 ms render tick but still owns a pyqtgraph PlotWidget).
    w.btn_hr1lab.setChecked(True); w.toggle_hr1lab()
    w.btn_spo2test.setChecked(True); w.toggle_spo2test()
    w.btn_lib_config.setChecked(True); w.toggle_lib_config()
    check(w.hr1lab_window is not None and w.spo2test_window is not None
          and w.lib_config_window is not None, "three plot windows opened")

    print("\n--- toggle ON: must close all three and lock every button ---")
    w.btn_disable_plots.setChecked(True)
    w._toggle_disable_plots()
    check(w.hr1lab_window is None and w.spo2test_window is None and w.lib_config_window is None,
          "all three closed (via their own toggle_xxx, main_monitor/window set to None)")
    check(not w.btn_hr1lab.isChecked() and not w.btn_spo2test.isChecked()
          and not w.btn_lib_config.isChecked(), "their buttons report unchecked, not just hidden")
    check(all(not getattr(w, n).isEnabled() for n in w._PLOT_WINDOW_BUTTONS),
          "every plot-window button is now disabled")
    check(w.btn_disable_plots.text() == "PLOTS  ●  OFF", f"button reads OFF ({w.btn_disable_plots.text()})")

    print("\n--- while ON: a plot window cannot be opened by calling its toggle directly ---")
    w.btn_hr2lab.setChecked(True)
    check(not w.btn_hr2lab.isEnabled(), "the button itself is disabled (a real click cannot reach it)")

    print("\n--- toggle OFF: buttons unlocked, nothing reopened on its own ---")
    w.btn_disable_plots.setChecked(False)
    w._toggle_disable_plots()
    check(all(getattr(w, n).isEnabled() for n in w._PLOT_WINDOW_BUTTONS),
          "every plot-window button re-enabled")
    check(w.hr1lab_window is None and w.spo2test_window is None and w.lib_config_window is None,
          "nothing reopens by itself -- the user opens what they need again")
    check(w.btn_disable_plots.text() == "PLOTS  ●  ON", f"button reads ON ({w.btn_disable_plots.text()})")

    print("\n--- persistence: survives a restart, which is the point (a crash relaunch) ---")
    w.btn_disable_plots.setChecked(True)
    w._toggle_disable_plots()
    w._save_settings()
    w2 = P.PPGMonitor()
    check(w2.btn_disable_plots.isChecked(), "a fresh instance restores the disabled state")
    check(all(not getattr(w2, n).isEnabled() for n in w2._PLOT_WINDOW_BUTTONS),
          "and its buttons come up already locked, with no window ever opened to close")
    w2._disconnect_udp()
    w2.close()

    w._disconnect_udp()
    w.close()
    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed —", "OK" if ok else "FAILED")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
