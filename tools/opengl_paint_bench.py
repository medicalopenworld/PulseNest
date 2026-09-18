"""What does pyqtgraph's useOpenGL actually cost or save, for the kind of plots this project draws?

`pulsenest_lab.py` opted into `useOpenGL=True` on the strength of a code comment claiming it
"offloads curve rasterization to the GPU (dramatically faster than software antialiasing,
especially for >1000-point curves)". Reading pyqtgraph 0.13.7 shows that is not what happens
here. The GPU fast path (`PlotCurveItem.paintGL`, `glDrawArrays`) runs only when the config
option `enableExperimental` is also set, and this project never sets it; and the one other
OpenGL-dependent branch in `PlotCurveItem` — chunking the path in 5000 points instead of 50 —
is inside `_getFillPathList`, used only for curves with a fill, which these plots do not have.
What `useOpenGL` really switches, for us, is exactly one thing: the `QGraphicsView` viewport
widget, `QOpenGLWidget` instead of a plain `QWidget` (`widgets/GraphicsView.py:153`), so the
same QPainter calls are rasterised by a different backend. pyqtgraph defaults it to False on
every platform and says "in general openGL is poorly supported with Qt+GraphicsView".

That matters because `AxisItem.paint()` ends in `self.picture.play(p)`, directly under the
authors' own `## Sometimes we get a segfault here ???`, and that painter's device is the
viewport. 18 of the lab's 28 recorded crashes are in that call
(`project_signals2_crash_investigation_task`).

So: is the setting paying for itself? Measured in the same process, on the same data, in the
same window, swapping only the viewport (`GraphicsView.useOpenGL()` does that at runtime).

Two numbers, because one of them alone lies:

- **paint** — the wall time inside the view's own `paintEvent`, i.e. the CPU cost of rendering
  the scene. Under OpenGL this *under-reports*: the driver may return before the GPU is done.
- **sustained** — how many full redraws per second the window actually delivers over a fixed
  stretch of wall clock, new data every frame. This one includes the GPU and the buffer swap,
  and it is the number that decides whether a plot window can keep up.

    python tools/opengl_paint_bench.py [--curves 3] [--points 500 2000 5000] [--seconds 3]

It opens a real on-screen window on purpose: measured offscreen, both configurations would go
through a software path and answer a different question from the one asked.
"""
import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulsenest_net import banner  # noqa: E402

import numpy as np                              # noqa: E402
import pyqtgraph as pg                          # noqa: E402
from PyQt5 import QtWidgets                     # noqa: E402


class TimedView(pg.GraphicsLayoutWidget):
    """Times the real paintEvent. Measuring around repaint() from outside gave 0.00 ms — the
    paint was not happening there — which is the sort of number that looks like a result."""

    # Before super().__init__: with show=True, Qt delivers a paintEvent during construction,
    # and an instance attribute set afterwards is not there yet when it arrives.
    paint_ms = []

    def __init__(self, **kw):
        self.paint_ms = []
        super().__init__(**kw)

    def paintEvent(self, ev):
        t0 = time.perf_counter()
        super().paintEvent(ev)
        self.paint_ms.append((time.perf_counter() - t0) * 1e3)


def run(view, app, curves, n_points, seconds):
    """New data every frame, repaint, and let Qt deliver it. -> (paint times, frames, wall)."""
    rng = np.random.default_rng(1234)
    x = np.arange(n_points, dtype=float)
    view.paint_ms.clear()
    frames = 0
    t_end = time.perf_counter() + seconds
    t0 = time.perf_counter()
    while time.perf_counter() < t_end:
        for curve in curves:
            # A PPG-ish trace whose amplitude drifts, so the Y range keeps moving and the axis
            # picture is invalidated — which is what happens on the bench, and is the code path
            # the crashes live in.
            y = np.sin(x / 7.0) * (1.0 + 0.002 * frames) + rng.normal(0, 0.05, n_points)
            curve.setData(x, y)
        view.repaint()
        app.processEvents()
        frames += 1
    return view.paint_ms[:], frames, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--curves", type=int, default=3, help="plots in the window (default %(default)s)")
    ap.add_argument("--points", type=int, nargs="+", default=[500, 2000, 5000],
                    help="points per curve to try (default: %(default)s)")
    ap.add_argument("--seconds", type=float, default=3.0, help="wall clock per measurement")
    args = ap.parse_args()
    print(banner(__file__, "useOpenGL on vs off, same process, same data"))
    print(f"   pyqtgraph {pg.__version__}   enableExperimental="
          f"{pg.getConfigOption('enableExperimental')}   (the GPU fast path would need it True)")

    pg.setConfigOptions(antialias=True)        # as the lab does; the viewport is what we swap
    app = QtWidgets.QApplication(sys.argv)
    view = TimedView(show=True, title="opengl_paint_bench")
    view.resize(1100, 800)
    curves = []
    for row in range(args.curves):
        plot = view.addPlot(row=row, col=0)
        plot.showGrid(x=True, y=True, alpha=0.2)
        curves.append(plot.plot(pen=pg.mkPen("#44AAFF", width=1)))
    for _ in range(50):                        # let the window map and be exposed
        app.processEvents()
        time.sleep(0.01)

    results = {}
    for n_points in args.points:
        print(f"\n  {args.curves} curves x {n_points} points, {args.seconds:.0f} s each:")
        for use_gl in (False, True):
            view.useOpenGL(use_gl)             # swaps the viewport widget in place
            for _ in range(20):
                app.processEvents()
            run(view, app, curves, n_points, 0.5)                 # warm up, discarded
            paints, frames, wall = run(view, app, curves, n_points, args.seconds)
            if not paints:
                print(f"    useOpenGL={use_gl}: NO paintEvent fired — measurement invalid")
                results[(n_points, use_gl)] = None
                continue
            med = statistics.median(paints)
            p90 = sorted(paints)[min(len(paints) - 1, int(0.9 * len(paints)))]
            fps = frames / wall
            flag = "  <- implausible, the paint is not happening here" if med < 0.05 else ""
            print(f"    useOpenGL={str(use_gl):<5}  paint median {med:6.2f} ms  p90 {p90:6.2f} ms"
                  f"   sustained {fps:5.1f} redraws/s{flag}")
            results[(n_points, use_gl)] = (med, fps)

    print("\n  verdict (sustained redraws/s is the one that counts: it includes the GPU)")
    for n_points in args.points:
        off, on = results[(n_points, False)], results[(n_points, True)]
        if off is None or on is None:
            print(f"    {n_points:>5} points: incomplete")
            continue
        (med_off, fps_off), (med_on, fps_on) = off, on
        better = "OpenGL" if fps_on > fps_off else "raster"
        ratio = max(fps_on, fps_off) / max(1e-9, min(fps_on, fps_off))
        print(f"    {n_points:>5} points: {better} sustains more, x{ratio:.2f}"
              f"   ({fps_off:.1f}/s raster vs {fps_on:.1f}/s OpenGL;"
              f" paint {med_off:.2f} vs {med_on:.2f} ms)")
    view.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
