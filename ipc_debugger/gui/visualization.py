"""
visualization.py — NetworkX / QPainter based visualisation of the processes and IPC channels.
"""

import math
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFontMetrics, QPolygonF
from PyQt5.QtCore import Qt, QTimer, QPointF

from utils.constants import ProcessState, StatusColor


class ProcessGraphWidget(QWidget):
    """
    Draws a directed graph representing:
        Nodes = Processes
        Edges = IPC Channels
    
    Nodes and edges change colours to reflect their current status.
    """
    
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setMinimumSize(600, 400)
        
        # Graph layout cache: pid -> QPointF
        self.node_positions = {}
        
        # Visual cues for active communication
        self.active_edges = {}   # (sender_pid, dest_ch) -> timestamp
        
        # Periodic repaint timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)  # 20 FPS

    def highlight_edge(self, sender_pid: int, channel_id: str):
        """Called when a log event happens to pulse an edge."""
        import time
        self.active_edges[(sender_pid, channel_id)] = time.time()

    def _compute_layout(self, width: int, height: int):
        """Place nodes in a circle."""
        processes = self.service.get_processes()
        if not processes:
            self.node_positions.clear()
            return

        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) / 3.0
        
        n = len(processes)
        for i, proc in enumerate(processes):
            angle = i * (2 * math.pi / n) - (math.pi / 2.0)  # start at top
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            self.node_positions[proc.pid] = QPointF(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), QColor(StatusColor.BACKGROUND))
        
        processes = self.service.get_processes()
        if not processes:
            painter.setPen(QColor(StatusColor.TEXT))
            painter.drawText(self.rect(), Qt.AlignCenter, "No scenario loaded.")
            return

        w, h = self.width(), self.height()
        self._compute_layout(w, h)
        
        deadlocks = self.service.get_deadlock_cycles()
        deadlocked_pids = set(pid for cycle in deadlocks for pid in cycle)

        self._draw_edges(painter, processes)
        self._draw_nodes(painter, processes, deadlocked_pids)

    def _draw_edges(self, painter: QPainter, processes: list):
        """Draw lines representing channels between processes."""
        import time
        now = time.time()
        
        # It's tricky to map channels strictly as edges without knowing the exact topology
        # beforehand. For visualization, we look at who is waiting on what.
        
        # Step 1: gather channel 'owners' (who wrote to it last, approximation)
        # Note: a true robust graph would require parsing the logic or having explicit config.
        # We will draw edges based on wait states for now.
        
        pen = QPen(QColor(StatusColor.IDLE), 2)
        painter.setPen(pen)

        for p in processes:
            if p.waiting_on:
                # Find a process that might 'own' this channel to draw an arrow
                for q in processes:
                    if q.pid != p.pid and not q.waiting_on:
                        p1 = self.node_positions.get(p.pid)
                        p2 = self.node_positions.get(q.pid)
                        
                        if p1 and p2:
                            # Draw an arrow from p (waiter) to q (holder)
                            self._draw_arrow(painter, p1, p2, QColor(StatusColor.DEADLOCK))
                            
        # Draw active pulse for recent transfers
        for (sid, ch), ts in list(self.active_edges.items()):
            if now - ts > 0.5:
                del self.active_edges[(sid, ch)]
                continue
                
            p1 = self.node_positions.get(sid)
            if p1:
                # Draw a temporary dot or line indicating activity (simplification)
                # Since we don't strictly know destination in 'queue' setups immediately,
                # we just pulse the node
                pen.setColor(QColor(StatusColor.NORMAL))
                pen.setWidth(4)
                painter.setPen(pen)
                painter.drawEllipse(p1, 25, 25)

    def _draw_arrow(self, painter: QPainter, p1: QPointF, p2: QPointF, color: QColor):
        """Draw a directed arrow."""
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        
        # Draw arrow head
        angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        arrow_size = 10
        # Offset slightly from the center of the node circle
        node_radius = 20
        end_x = p2.x() - node_radius * math.cos(angle)
        end_y = p2.y() - node_radius * math.sin(angle)
        
        dest = QPointF(end_x, end_y)
        
        p3 = QPointF(end_x - arrow_size * math.cos(angle - math.pi / 6),
                     end_y - arrow_size * math.sin(angle - math.pi / 6))
        p4 = QPointF(end_x - arrow_size * math.cos(angle + math.pi / 6),
                     end_y - arrow_size * math.sin(angle + math.pi / 6))
                     
        polygon = QPolygonF()
        polygon.append(dest)
        polygon.append(p3)
        polygon.append(p4)
        
        painter.setBrush(QBrush(color))
        painter.drawPolygon(polygon)

    def _draw_nodes(self, painter: QPainter, processes: list, deadlocked_pids: set):
        """Draw the process circles and labels."""
        fm = QFontMetrics(painter.font())
        node_radius = 20
        
        for p in processes:
            pos = self.node_positions.get(p.pid)
            if not pos:
                continue
                
            # Determine color
            if p.pid in deadlocked_pids:
                color = QColor(StatusColor.DEADLOCK)
            elif p.state == ProcessState.WAITING:
                color = QColor(StatusColor.DELAY)
            elif p.state == ProcessState.RUNNING:
                color = QColor(StatusColor.NORMAL)
            else:
                color = QColor(StatusColor.IDLE)
                
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.white, 2))
            painter.drawEllipse(pos, node_radius, node_radius)
            
            # Draw label
            label = f"{p.name}\n(P{p.pid})"
            painter.setPen(QColor(StatusColor.TEXT))
            rect = fm.boundingRect(label)
            # Center below node
            x = pos.x() - rect.width() / 2
            y = pos.y() + node_radius + rect.height()
            painter.drawText(int(x), int(y), label)
            
            # Draw waiting status
            if p.waiting_on:
                w_label = f"Wait: {p.waiting_on}"
                painter.setPen(QColor(StatusColor.RACE))
                w_rect = fm.boundingRect(w_label)
                painter.drawText(int(pos.x() - w_rect.width() / 2), int(y + rect.height()), w_label)
