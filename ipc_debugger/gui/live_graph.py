"""
live_graph.py — Real-time process graph for the Live Monitor tab.

Draws a directed graph of real OS processes using QPainter:
  • Nodes  = real processes (coloured by CPU / status)
  • Edges  = parent-child relationships (thin grey)
  • Edges  = detected IPC connections (coloured by type)

Unlike the simulation graph which draws a fixed circular layout,
this graph uses a two-tier layout:
  Top row    = root processes (ppid not in the visible set)
  Child rows = children grouped under their parent
"""

import math
import time
from typing import Dict, List, Optional, Tuple

from PyQt5.QtWidgets import QWidget, QToolTip
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPolygonF,
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF

from system_monitor.data_models import ProcessSnapshot, IPCConnection
from utils.constants import StatusColor

# Visual constants
NODE_RADIUS = 18
LABEL_FONT_SIZE = 8
MAX_DISPLAYED_NODES = 80   # cap to keep rendering snappy

# Colour by IPC connection type
IPC_COLORS = {
    "shared_file": "#7C4DFF",   # purple
    "tcp_socket":  "#00BCD4",   # cyan
    "udp_socket":  "#FF9800",   # orange
    "named_pipe":  "#4CAF50",   # green
}

# Node colour by status
STATUS_COLORS = {
    "running":  "#4CAF50",
    "sleeping": "#42A5F5",
    "zombie":   "#FFC107",
    "stopped":  "#9E9E9E",
    "disk-sleep": "#9C27B0",
}


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """Linear-interpolate between two QColors."""
    return QColor(
        int(c1.red()   + (c2.red()   - c1.red())   * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue()  + (c2.blue()  - c1.blue())  * t),
    )


class LiveGraphWidget(QWidget):
    """
    QPainter-based live process graph.

    Positions up to MAX_DISPLAYED_NODES processes in a grid/tree layout
    and draws IPC edges as coloured arcs. Repaints at ~20 FPS.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 350)
        self.setMouseTracking(True)

        self._processes: List[ProcessSnapshot] = []
        self._connections: List[IPCConnection] = []
        self._positions: Dict[int, QPointF] = {}     # pid → position
        self._hovered_pid: Optional[int] = None
        self._selected_pid: Optional[int] = None

        # Animation state for new process flash
        self._new_flash: Dict[int, float] = {}       # pid → timestamp

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(50)  # 20 FPS

    # ── Public API ──────────────────────────────────────────────────────

    def update_data(self,
                    processes: List[ProcessSnapshot],
                    connections: List[IPCConnection]) -> None:
        """Feed new process+connection data from the live monitor."""
        # Limit displayed processes for performance
        visible = sorted(processes, key=lambda p: p.cpu_percent, reverse=True)
        visible = visible[:MAX_DISPLAYED_NODES]

        # Track newly appeared nodes for the flash animation
        existing_pids = set(self._positions.keys())
        for p in visible:
            if p.is_new and p.pid not in existing_pids:
                self._new_flash[p.pid] = time.time()

        self._processes = visible
        self._connections = [
            c for c in connections
            if c.connection_type != "named_pipe"  # skip nameless pipe noise
        ]
        self._recompute_layout()

    def set_selected(self, pid: Optional[int]) -> None:
        self._selected_pid = pid

    # ── Layout ──────────────────────────────────────────────────────────

    def _recompute_layout(self) -> None:
        """Arrange process nodes in a grid. Called after data update."""
        if not self._processes:
            self._positions.clear()
            return

        W, H = self.width(), self.height()
        margin = 40
        n = len(self._processes)

        # Simple grid layout — elegant enough for this tool
        cols = max(1, int(math.ceil(math.sqrt(n * 1.5))))
        rows = max(1, math.ceil(n / cols))

        cell_w = (W - 2 * margin) / cols
        cell_h = (H - 2 * margin) / rows

        self._positions.clear()
        for i, proc in enumerate(self._processes):
            row = i // cols
            col = i % cols
            x = margin + col * cell_w + cell_w / 2
            y = margin + row * cell_h + cell_h / 2
            self._positions[proc.pid] = QPointF(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_layout()

    # ── Painting ────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(StatusColor.BACKGROUND))

        if not self._processes:
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "🔴  Live monitor not active\nor no processes visible"
            )
            return

        now = time.time()

        self._draw_parent_edges(painter)
        self._draw_ipc_edges(painter)
        self._draw_nodes(painter, now)
        self._draw_legend(painter)
        self._draw_count_badge(painter)

    def _draw_parent_edges(self, painter: QPainter) -> None:
        """Thin grey lines for parent-child relationships."""
        pid_set = {p.pid for p in self._processes}
        pen = QPen(QColor(80, 80, 100), 1, Qt.DotLine)
        painter.setPen(pen)

        for proc in self._processes:
            if proc.ppid in pid_set and proc.ppid != proc.pid:
                p1 = self._positions.get(proc.ppid)
                p2 = self._positions.get(proc.pid)
                if p1 and p2:
                    painter.drawLine(p1, p2)

    def _draw_ipc_edges(self, painter: QPainter) -> None:
        """Coloured lines for detected IPC connections."""
        for conn in self._connections:
            p1 = self._positions.get(conn.pid_a)
            p2 = self._positions.get(conn.pid_b)
            if not (p1 and p2):
                continue
            color_hex = IPC_COLORS.get(conn.connection_type, "#AAAAAA")
            pen = QPen(QColor(color_hex), 2)
            painter.setPen(pen)
            painter.drawLine(p1, p2)
            # Small label on the midpoint
            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            painter.setPen(QColor(color_hex))
            painter.setFont(QFont("Segoe UI", 7))
            lbl_map = {
                "shared_file": "file",
                "tcp_socket":  "TCP",
                "udp_socket":  "UDP",
                "named_pipe":  "pipe",
            }
            painter.drawText(QRectF(mid.x() - 20, mid.y() - 8, 40, 14),
                             Qt.AlignCenter,
                             lbl_map.get(conn.connection_type, "?"))

    def _draw_nodes(self, painter: QPainter, now: float) -> None:
        """Draw process circles with CPU-based sizing and status colouring."""
        fm = QFontMetrics(QFont("Segoe UI", LABEL_FONT_SIZE))

        for proc in self._processes:
            pos = self._positions.get(proc.pid)
            if not pos:
                continue

            # CPU-scaled radius (15–30px)
            r = NODE_RADIUS + min(proc.cpu_percent * 0.3, 12)

            # Base colour from status
            base_hex = STATUS_COLORS.get(proc.status, "#607d8b")
            base_color = QColor(base_hex)

            # Pulse flash for new processes
            flash_ts = self._new_flash.get(proc.pid, 0.0)
            if now - flash_ts < 1.5:
                t = (now - flash_ts) / 1.5
                base_color = _lerp_color(QColor("#FFFFFF"), base_color, t)

            # Highlight selected / hovered
            if proc.pid == self._selected_pid:
                painter.setPen(QPen(QColor("#FFFFFF"), 3))
            elif proc.pid == self._hovered_pid:
                painter.setPen(QPen(QColor("#AAAAFF"), 2))
            else:
                painter.setPen(QPen(Qt.NoPen))

            # High-CPU: add red glow ring
            if proc.is_high_cpu:
                glow_pen = QPen(QColor(220, 50, 50, 160), 4)
                painter.setPen(glow_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(pos, r + 4, r + 4)

            painter.setBrush(QBrush(base_color))
            if proc.pid != self._selected_pid:
                painter.setPen(QPen(base_color.darker(140), 1))
            painter.drawEllipse(pos, r, r)

            # Label: name (truncated) + PID
            painter.setFont(QFont("Segoe UI", LABEL_FONT_SIZE))
            painter.setPen(QColor(230, 230, 230))

            name = proc.name
            if len(name) > 12:
                name = name[:10] + "…"

            label = f"{name}\n{proc.pid}"
            lines = label.split("\n")
            line_h = fm.height()
            y_start = pos.y() + r + 4

            for i, line in enumerate(lines):
                lw = fm.horizontalAdvance(line)
                painter.drawText(
                    QRectF(pos.x() - lw / 2, y_start + i * line_h, lw + 2, line_h + 2),
                    Qt.AlignLeft,
                    line,
                )

            # CPU badge inside node
            if proc.cpu_percent >= 1.0:
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(Qt.white)
                cpu_text = f"{proc.cpu_percent:.0f}%"
                tw = fm.horizontalAdvance(cpu_text)
                painter.drawText(
                    QRectF(pos.x() - tw / 2, pos.y() - fm.height() / 2, tw + 2, fm.height() + 2),
                    Qt.AlignLeft,
                    cpu_text,
                )

    def _draw_legend(self, painter: QPainter) -> None:
        """Small IPC-type colour legend in the top-right corner."""
        x, y = self.width() - 155, 10
        painter.setFont(QFont("Segoe UI", 8))
        for i, (conn_type, color) in enumerate(IPC_COLORS.items()):
            painter.setPen(QPen(QColor(color), 3))
            painter.drawLine(x, y + i * 16 + 8, x + 20, y + i * 16 + 8)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(x + 24, y + i * 16 + 12, conn_type.replace("_", " "))

    def _draw_count_badge(self, painter: QPainter) -> None:
        """Bottom-left badge showing displayed/total count."""
        n = len(self._processes)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(120, 120, 120))
        painter.drawText(6, self.height() - 6, f"Showing top {n} by CPU")

    # ── Mouse interaction ────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        pos = QPointF(event.pos())
        self._hovered_pid = None
        for pid, node_pos in self._positions.items():
            dx = pos.x() - node_pos.x()
            dy = pos.y() - node_pos.y()
            if math.hypot(dx, dy) <= NODE_RADIUS + 15:
                self._hovered_pid = pid
                # Show tooltip
                proc = next((p for p in self._processes if p.pid == pid), None)
                if proc:
                    QToolTip.showText(
                        event.globalPos(),
                        f"PID: {proc.pid}\nName: {proc.name}\n"
                        f"CPU: {proc.cpu_percent:.1f}%\n"
                        f"RAM: {proc.memory_rss_mb:.1f} MB\n"
                        f"Threads: {proc.num_threads}\n"
                        f"Status: {proc.status}\n"
                        f"User: {proc.username}",
                        self,
                    )
                break
        self.update()

    def mousePressEvent(self, event):
        pos = QPointF(event.pos())
        for pid, node_pos in self._positions.items():
            dx = pos.x() - node_pos.x()
            dy = pos.y() - node_pos.y()
            if math.hypot(dx, dy) <= NODE_RADIUS + 15:
                self._selected_pid = pid if self._selected_pid != pid else None
                self.update()
                return
        self._selected_pid = None
        self.update()
