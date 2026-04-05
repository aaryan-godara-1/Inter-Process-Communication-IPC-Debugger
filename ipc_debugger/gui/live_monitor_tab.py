"""
live_monitor_tab.py — Live Monitor tab assembly.

Combines ProcessTableWidget (left) and LiveGraphWidget (right) into a
split layout, with an IPC connections panel below.
Subscribes to PROCESS_SNAPSHOT and IPC_CONNECTION_FOUND events.
"""

from typing import List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QListWidget, QListWidgetItem, QLabel, QPushButton,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QColor, QFont, QIcon

from utils.constants import EventType
from system_monitor.data_models import ProcessSnapshot, IPCConnection
from gui.process_table import ProcessTableWidget
from gui.live_graph import LiveGraphWidget

# IPC type colour mapping (same as live_graph but for text badges)
IPC_BADGE_STYLES = {
    "shared_file": "background:#7C4DFF;color:#fff;",
    "tcp_socket":  "background:#00BCD4;color:#fff;",
    "udp_socket":  "background:#FF9800;color:#000;",
    "named_pipe":  "background:#4CAF50;color:#fff;",
}


class LiveMonitorTab(QWidget):
    """
    Live Monitor tab — real OS process data from psutil.

    Layout:
        ┌─────────────────────────────────────────────┐
        │  [Start Live]  [Stop Live]  status badge    │
        ├────────────────────┬────────────────────────┤
        │  Process Table     │  Live Graph             │
        ├────────────────────┴────────────────────────┤
        │  IPC Connections Detected                   │
        └─────────────────────────────────────────────┘
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._connections: List[IPCConnection] = []
        self._init_ui()
        self._connect_service()

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Top control bar ───────────────────────────────────────────
        top_bar = QHBoxLayout()

        self._btn_start = QPushButton("🔴  Start Live Monitor")
        self._btn_start.setFixedHeight(32)
        self._btn_start.setStyleSheet(
            "QPushButton { background:#1b5e20; color:#fff; border-radius:4px; padding:0 14px; font-weight:bold; }"
            "QPushButton:hover { background:#2e7d32; }"
        )
        self._btn_start.clicked.connect(self._on_start)

        self._btn_stop = QPushButton("⏹  Stop")
        self._btn_stop.setFixedHeight(32)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(
            "QPushButton { background:#b71c1c; color:#fff; border-radius:4px; padding:0 14px; }"
            "QPushButton:hover { background:#c62828; }"
        )
        self._btn_stop.clicked.connect(self._on_stop)

        self._status_lbl = QLabel("● Stopped")
        self._status_lbl.setStyleSheet("color:#9E9E9E; font-size:11px; padding-left:10px;")

        top_bar.addWidget(self._btn_start)
        top_bar.addWidget(self._btn_stop)
        top_bar.addWidget(self._status_lbl)
        top_bar.addStretch()

        self._proc_count_lbl = QLabel("")
        self._proc_count_lbl.setStyleSheet("color:#7ec8e3; font-size:11px;")
        top_bar.addWidget(self._proc_count_lbl)

        root.addLayout(top_bar)

        # ── Main splitter: table | graph ──────────────────────────────
        h_splitter = QSplitter(Qt.Horizontal)

        self._proc_table = ProcessTableWidget()
        self._proc_table.processSelected.connect(self._on_process_selected)
        h_splitter.addWidget(self._proc_table)

        self._live_graph = LiveGraphWidget()
        h_splitter.addWidget(self._live_graph)

        h_splitter.setSizes([480, 620])
        root.addWidget(h_splitter, stretch=3)

        # ── IPC Connections panel ─────────────────────────────────────
        ipc_group = QGroupBox("🔗  Detected IPC Connections (Real)")
        ipc_group.setFont(QFont("Segoe UI", 9))
        ipc_layout = QVBoxLayout(ipc_group)
        ipc_layout.setContentsMargins(6, 6, 6, 6)

        self._ipc_list = QListWidget()
        self._ipc_list.setMaximumHeight(110)
        self._ipc_list.setStyleSheet(
            "QListWidget { font-family: 'Consolas','Courier New',monospace; font-size:9pt; }"
        )
        ipc_layout.addWidget(self._ipc_list)

        self._ipc_count_lbl = QLabel("No connections detected yet.")
        self._ipc_count_lbl.setStyleSheet("color:#9E9E9E; font-size:9px;")
        ipc_layout.addWidget(self._ipc_count_lbl)

        root.addWidget(ipc_group, stretch=1)

    # ── Service wiring ────────────────────────────────────────────────────

    def _connect_service(self):
        self.service.subscribe_to_events(
            EventType.PROCESS_SNAPSHOT, self._on_process_snapshot
        )
        self.service.subscribe_to_events(
            EventType.IPC_CONNECTION_FOUND, self._on_ipc_found
        )

    # ── Slots ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_start(self):
        self.service.start_live_mode()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status_lbl.setText("● Live")
        self._status_lbl.setStyleSheet("color:#4CAF50; font-size:11px; font-weight:bold; padding-left:10px;")

    @pyqtSlot()
    def _on_stop(self):
        self.service.stop_live_mode()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status_lbl.setText("● Stopped")
        self._status_lbl.setStyleSheet("color:#9E9E9E; font-size:11px; padding-left:10px;")

    def _on_process_snapshot(self, processes, new_pids, terminated_pids, **_):
        # Qt signals/slots: this may be called from a non-GUI thread, so
        # we use QMetaObject.invokeMethod pattern — simplest fix is to
        # queue the call. Here we rely on Qt's thread affinity for lambdas
        # by scheduling via a zero-interval timer on the GUI thread.
        from PyQt5.QtCore import QMetaObject, Qt as Qtc
        # Safe cross-thread update: marshal to GUI thread
        self._pending_processes = processes
        QMetaObject.invokeMethod(self, "_apply_process_update", Qtc.QueuedConnection)

    @pyqtSlot()
    def _apply_process_update(self):
        processes = getattr(self, "_pending_processes", [])
        self._proc_table.update_processes(processes)
        connections = self.service.get_live_connections()
        self._live_graph.update_data(processes, connections)
        n_new = sum(1 for p in processes if p.is_new)
        self._proc_count_lbl.setText(
            f"{len(processes):,} processes  |  {n_new} new"
        )

    def _on_ipc_found(self, connections, **_):
        from PyQt5.QtCore import QMetaObject, Qt as Qtc
        self._pending_connections = connections
        QMetaObject.invokeMethod(self, "_apply_ipc_update", Qtc.QueuedConnection)

    @pyqtSlot()
    def _apply_ipc_update(self):
        connections = getattr(self, "_pending_connections", [])
        self._ipc_list.clear()
        real_conns = [c for c in connections if c.pid_a != 0 or c.pid_b != 0]
        for conn in real_conns[:50]:
            badge = conn.connection_type.replace("_", " ").upper()
            name_a = conn.process_name_a or str(conn.pid_a)
            name_b = conn.process_name_b or str(conn.pid_b)
            item = QListWidgetItem(
                f"[{badge}]  {name_a} ({conn.pid_a}) ↔ {name_b} ({conn.pid_b})"
                f"  ·  {conn.resource[:60]}"
            )
            color_hex = {
                "shared_file": "#CE93D8",
                "tcp_socket":  "#80DEEA",
                "udp_socket":  "#FFCC02",
                "named_pipe":  "#A5D6A7",
            }.get(conn.connection_type, "#EEEEEE")
            item.setForeground(QColor(color_hex))
            self._ipc_list.addItem(item)

        total = len(real_conns)
        self._ipc_count_lbl.setText(
            f"{total} real IPC connection{'s' if total != 1 else ''} detected"
        )

    def _on_process_selected(self, proc: ProcessSnapshot):
        self._live_graph.set_selected(proc.pid)
