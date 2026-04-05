"""
gauge_widgets.py — Custom QPainter gauge and chart widgets for the Dashboard.

Provides:
    MetricGauge  — circular arc gauge for a single metric (CPU, RAM, etc.)
    SparkLine    — compact rolling line chart for time-series data
    TopNWidget   — ranked list of processes by a metric
"""

import math
from typing import List, Tuple, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QLinearGradient
from PyQt5.QtCore import Qt, QRectF, QPointF


# ── Palette ──────────────────────────────────────────────────────────────────

def _value_color(percent: float) -> QColor:
    """Gradient from green → amber → red based on 0-100 %."""
    if percent < 60:
        t = percent / 60.0
        return QColor(
            int(60 + t * (230 - 60)),
            int(200 - t * (200 - 180)),
            60,
        )
    else:
        t = (percent - 60) / 40.0
        return QColor(
            220,
            int(180 - t * 180),
            int(60 * (1 - t)),
        )


# ── MetricGauge ───────────────────────────────────────────────────────────────

class MetricGauge(QWidget):
    """
    Circular arc gauge widget.

    Displays a title, current value, unit string, and a coloured arc that
    sweeps from bottom-left to bottom-right (270° sweep centred at top).
    """

    def __init__(self, title: str, unit: str = "%",
                 max_value: float = 100.0, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.max_value = max_value
        self.value: float = 0.0
        self.subtitle: str = ""
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, value: float, subtitle: str = "") -> None:
        self.value = max(0.0, min(value, self.max_value))
        self.subtitle = subtitle
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        size = min(W, H) - 20
        cx, cy = W / 2, H / 2

        # Background disc
        painter.setBrush(QBrush(QColor(35, 35, 55)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(cx - size/2, cy - size/2, size, size))

        # Track arc (dim)
        track_pen = QPen(QColor(60, 60, 80), 12, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track_pen)
        start_angle = -210 * 16      # Qt angles are 1/16th degree, start bottom-left
        span_angle  = 240 * 16
        rect = QRectF(cx - size/2 + 14, cy - size/2 + 14, size - 28, size - 28)
        painter.drawArc(rect, start_angle, span_angle)

        # Value arc (coloured)
        pct = self.value / self.max_value
        value_span = int(pct * 240 * 16)
        color = _value_color(pct * 100)
        value_pen = QPen(color, 12, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(value_pen)
        painter.drawArc(rect, start_angle, value_span)

        # Central text — value
        painter.setPen(QColor(230, 230, 230))

        # Value number — large
        if self.unit == "B/s":
            val_str = _format_bytes(self.value)
        elif self.unit == "%":
            val_str = f"{self.value:.1f}%"
        else:
            val_str = f"{self.value:.1f} {self.unit}"

        painter.setFont(QFont("Segoe UI", int(size * 0.14), QFont.Bold))
        painter.drawText(QRectF(cx - size/2, cy - size * 0.18, size, size * 0.3),
                         Qt.AlignCenter, val_str)

        # Subtitle (e.g. "2.1 / 8.0 GB")
        if self.subtitle:
            painter.setFont(QFont("Segoe UI", int(size * 0.08)))
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(QRectF(cx - size/2, cy + size * 0.1, size, size * 0.2),
                             Qt.AlignCenter, self.subtitle)

        # Title below
        painter.setFont(QFont("Segoe UI", int(size * 0.09), QFont.Bold))
        painter.setPen(QColor(130, 160, 200))
        painter.drawText(QRectF(cx - size/2, cy + size * 0.3, size, size * 0.2),
                         Qt.AlignCenter, self.title)


# ── SparkLine ─────────────────────────────────────────────────────────────────

class SparkLine(QWidget):
    """
    Compact rolling line chart.

    Draws up to N data points as a filled area chart with a coloured line.
    Designed to show CPU or memory history.
    """

    def __init__(self, title: str = "", color: str = "#42A5F5",
                 unit: str = "%", max_value: float = 100.0, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.unit = unit
        self.max_value = max_value
        self._data: List[float] = []
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, values: List[float], max_value: Optional[float] = None) -> None:
        self._data = list(values)
        if max_value is not None:
            self.max_value = max_value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        pad_top, pad_bot, pad_side = 8, 24, 8
        chart_w = W - 2 * pad_side
        chart_h = H - pad_top - pad_bot

        # Background
        painter.fillRect(self.rect(), QColor(28, 28, 42))

        if len(self._data) < 2:
            painter.setPen(QColor(100, 100, 120))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(self.rect(), Qt.AlignCenter, "Waiting for data…")
            return

        n = len(self._data)
        mv = max(self.max_value, max(self._data, default=1), 1)

        # Build polyline points
        def pt(i: int) -> QPointF:
            x = pad_side + (i / (n - 1)) * chart_w
            y = pad_top + chart_h - (self._data[i] / mv) * chart_h
            return QPointF(x, y)

        points = [pt(i) for i in range(n)]

        # Filled gradient area
        grad = QLinearGradient(0, pad_top, 0, pad_top + chart_h)
        c1 = QColor(self.color)
        c1.setAlpha(120)
        c2 = QColor(self.color)
        c2.setAlpha(10)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)

        poly = [QPointF(pad_side, pad_top + chart_h)]
        poly += points
        poly.append(QPointF(pad_side + chart_w, pad_top + chart_h))

        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(*poly)

        # Line
        pen = QPen(self.color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i + 1])

        # Current value label
        current = self._data[-1]
        if self.unit == "B/s":
            val_str = _format_bytes(current) + "/s"
        else:
            val_str = f"{current:.1f}{self.unit}"

        painter.setPen(QColor(220, 220, 220))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(pad_side, pad_top, chart_w, 18), Qt.AlignRight, val_str)

        # Title
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(130, 160, 200))
        painter.drawText(QRectF(pad_side, H - pad_bot, chart_w, pad_bot),
                         Qt.AlignLeft | Qt.AlignVCenter, self.title)

        # Y-axis min/max labels
        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor(80, 80, 100))
        painter.drawText(QRectF(0, pad_top, pad_side + 2, 12), Qt.AlignRight,
                         f"{mv:.0f}")
        painter.drawText(QRectF(0, pad_top + chart_h - 12, pad_side + 2, 12),
                         Qt.AlignRight, "0")


# ── TopNWidget ────────────────────────────────────────────────────────────────

class TopNWidget(QWidget):
    """
    Ranked bar-list of the top N processes by a given metric.

    Each row shows [rank] [name] [bar] [value].
    """

    def __init__(self, title: str = "Top Processes",
                 unit: str = "%", color: str = "#7C4DFF",
                 parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.bar_color = QColor(color)
        self._rows: List[Tuple[str, int, float]] = []  # (name, pid, value)
        self._max_value: float = 100.0
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, rows: List[Tuple[str, int, float]],
                 max_value: float = 100.0) -> None:
        """Pass a sorted list of (name, pid, value) tuples."""
        self._rows = rows[:8]
        self._max_value = max(max_value, 1.0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        painter.fillRect(self.rect(), QColor(28, 28, 42))

        # Title
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.setPen(QColor(130, 160, 200))
        painter.drawText(QRectF(8, 4, W - 16, 18), Qt.AlignLeft, self.title)

        if not self._rows:
            painter.setPen(QColor(100, 100, 120))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QRectF(0, 22, W, H - 22), Qt.AlignCenter, "No data")
            return

        row_h = max(16, (H - 24) // max(len(self._rows), 1))
        name_w = int(W * 0.34)
        val_w = int(W * 0.16)
        bar_w = W - name_w - val_w - 16

        for i, (name, pid, val) in enumerate(self._rows):
            y = 24 + i * row_h
            if y + row_h > H:
                break

            # Name
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor(200, 200, 200))
            short_name = name[:16] + "…" if len(name) > 16 else name
            painter.drawText(QRectF(8, y, name_w, row_h),
                             Qt.AlignLeft | Qt.AlignVCenter, short_name)

            # Bar
            fill_w = int((val / self._max_value) * bar_w)
            bar_rect = QRectF(name_w + 8, y + 3, bar_w, row_h - 6)
            bg_color = QColor(50, 50, 70)
            painter.setBrush(QBrush(bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 3, 3)
            if fill_w > 0:
                fill_rect = QRectF(name_w + 8, y + 3, fill_w, row_h - 6)
                bar_c = QColor(self.bar_color)
                bar_c.setAlpha(200)
                painter.setBrush(QBrush(bar_c))
                painter.drawRoundedRect(fill_rect, 3, 3)

            # Value
            if self.unit == "MB":
                val_str = f"{val:.0f} MB"
            elif self.unit == "%":
                val_str = f"{val:.1f}%"
            else:
                val_str = f"{val:.1f}"

            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(
                QRectF(name_w + bar_w + 12, y, val_w, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                val_str,
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_bytes(b: float) -> str:
    """Human-readable byte count."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
