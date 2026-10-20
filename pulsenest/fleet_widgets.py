"""The Qt-measured pieces of a PPG band: the numbers panel width and the statistics panel.

Shared by tools/fleet_ppg_viewer.py and tools/pulsenest_recorder_gui.py (extracted 2026-10-13, see
pulsenest/fleet_trace.py). Everything here needs a QApplication: the widths come from real font
metrics, which is what keeps three digits from wrapping on a display with a scaling factor.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from pulsenest.fleet_trace import (BIG_PT, SMALL_PT, HEART, HEART_PT, WIDEST_VALUE, WIDEST_UNIT,
                                   STATS_FAMILY, STATS_PT, STATS_ROWS, STATS_COLS, VAL_CHARS,
                                   STATS_BG, STATS_BODY)


def panel_width():
    """How wide the numbers panel has to be for its worst case, from the real font metrics.

    It was a flat 190 px, which fitted two digits and wrapped at three — SpO2 reaching 100 was
    enough to add a line and shift every row. Measuring it here also makes it right on a display
    with a scaling factor, where a pixel guess made against one monitor is wrong on the next.
    """
    big = QtGui.QFont()
    big.setPointSize(BIG_PT)
    big.setBold(True)
    small = QtGui.QFont()
    small.setPointSize(SMALL_PT)
    heart = QtGui.QFont()
    heart.setPointSize(HEART_PT)
    # The widest line is the rate: heart, space, three digits. Measuring the digits alone would
    # hand back exactly the wrapping this function exists to prevent.
    value_w = (QtGui.QFontMetrics(big).horizontalAdvance(WIDEST_VALUE)
               + QtGui.QFontMetrics(heart).horizontalAdvance(HEART + " "))
    return max(value_w,
               QtGui.QFontMetrics(small).horizontalAdvance(WIDEST_UNIT)) + 24


def stats_font():
    """SIGNAL STATS's family at this panel's size. The same QFont is measured and painted."""
    f = QtGui.QFont(STATS_FAMILY)
    f.setPointSize(STATS_PT)
    return f


def stats_columns():
    """-> (label column px, value column px), measured from the real font metrics."""
    fm = QtGui.QFontMetrics(stats_font())
    label_w = max(fm.horizontalAdvance(row[0]) for row in STATS_ROWS) + 8
    value_w = max(fm.horizontalAdvance(VAL_CHARS),
                  max(fm.horizontalAdvance(c) for c in STATS_COLS)) + 8
    return label_w, value_w


def stats_width():
    """Width of the whole statistics panel, scrollbar included."""
    label_w, value_w = stats_columns()
    bar = QtWidgets.QApplication.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent)
    return label_w + value_w * len(STATS_COLS) + bar + 12


def stats_cell_at(edit, pos):
    """(row, column) of the statistics table cell under `pos` (viewport coordinates), or None.
    Row 0 is the header; column 0 the signal label. Asks the document, not a pixel grid, so it
    stays right whatever the font, the scroll position or the display scaling."""
    cursor = edit.cursorForPosition(pos)
    table = cursor.currentTable()
    if table is None:
        return None
    cell = table.cellAt(cursor)
    return (cell.row(), cell.column()) if cell.isValid() else None


def make_stats_widget(width):
    """The panel: a read-only QTextEdit in the band, not a drawn label.

    A widget for three reasons. It brings a real scrollbar, which is how the rows that do not
    fit stay reachable. It clips itself, so no part of it can be painted outside the window --
    the failure that made three panels read as empty. And with its minimum height at zero its
    content has no say in how tall the band is, which is what stopped the bands being equal.
    """
    edit = QtWidgets.QTextEdit()
    edit.setReadOnly(True)
    edit.setFont(stats_font())
    edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
    edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    edit.setFrameShape(QtWidgets.QFrame.NoFrame)
    edit.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)   # read-only means read-only
    # The scrollbar is styled too: a native light-grey bar in the middle of a black window
    # reads as a piece of some other application.
    edit.setStyleSheet(
        f"QTextEdit {{ background-color:{STATS_BG}; color:{STATS_BODY}; border:none; }}"
        f"QScrollBar:vertical {{ background:{STATS_BG}; width:10px; margin:0; }}"
        f"QScrollBar::handle:vertical {{ background:#3A3A3A; min-height:20px; border-radius:4px; }}"
        f"QScrollBar::handle:vertical:hover {{ background:#585858; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:{STATS_BG}; }}")
    edit.setFixedWidth(width)
    edit.setMinimumHeight(0)
    edit.document().setDocumentMargin(2)
    return edit
