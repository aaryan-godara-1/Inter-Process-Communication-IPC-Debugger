"""
main_window.py — Main GUI application window.

Assembles the three tabs — Live Monitor, Simulation Lab, Dashboard —
into a QTabWidget with a status bar that shows real-time system state.
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QStatusBar, QLabel,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette

from service import IPCService
from utils.constants import EventType
from gui.live_monitor_tab import LiveMonitorTab
from gui.simulation_tab import SimulationTab
from gui.dashboard_tab import DashboardTab


class MainWindow(QMainWindow):
    """
    Main application window — Real-Time IPC Monitor & Process Analyzer.

    Three QTabWidget tabs:
        🔴 Live Monitor    — real OS process data via psutil
        🧪 Simulation Lab  — existing theory demos (deadlock, race, IPC)
        📊 Dashboard       — system performance gauges & charts
    """

    def __init__(self, service: IPCService):
        super().__init__()
        self.service = service

        self.setWindowTitle("Real-Time IPC Monitor & Process Analyzer")
        self.resize(1280, 860)
        self._apply_stylesheet()

        self._init_ui()
        self._init_status_bar()
        self._connect_events()

        # Status-bar refresh timer
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start(1500)

        # Load default simulation scenario so Simulation tab is ready
        self._sim_tab.load_default_scenario()

    # ── Stylesheet ───────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a2e;
                color: #e0e0e0;
                font-family: "Segoe UI", sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #2d2d44;
                background: #1a1a2e;
            }
            QTabBar::tab {
                background: #2d2d44;
                color: #9e9e9e;
                padding: 10px 22px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                min-width: 160px;
            }
            QTabBar::tab:selected {
                background: #3a3a5c;
                color: #7ec8e3;
                border-bottom: 2px solid #7C4DFF;
            }
            QTabBar::tab:hover:!selected {
                background: #32324a;
                color: #c0c0c0;
            }
            QGroupBox {
                border: 1px solid #3a3a5c;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: #9e9e9e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background: #3a3a5c;
                color: #e0e0e0;
                border: none;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 10px;
            }
            QPushButton:hover  { background: #4a4a6c; }
            QPushButton:pressed{ background: #2a2a4c; }
            QPushButton:disabled { background: #2a2a3c; color: #555; }
            QLineEdit {
                background: #252540;
                border: 1px solid #3a3a5c;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e0e0e0;
            }
            QListWidget, QTableView {
                background: #1e1e32;
                alternate-background-color: #252542;
                border: 1px solid #3a3a5c;
                border-radius: 4px;
                color: #e0e0e0;
                gridline-color: #2d2d44;
            }
            QHeaderView::section {
                background: #2d2d44;
                color: #9e9e9e;
                border: none;
                padding: 5px 8px;
                font-weight: bold;
                font-size: 10px;
            }
            QScrollBar:vertical {
                background: #1a1a2e;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #3a3a5c;
                border-radius: 4px;
            }
            QSplitter::handle {
                background: #3a3a5c;
            }
            QComboBox {
                background: #252540;
                border: 1px solid #3a3a5c;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e0e0e0;
            }
            QSlider::groove:horizontal {
                background: #3a3a5c;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #7C4DFF;
                border-radius: 6px;
                width: 14px;
                height: 14px;
                margin: -5px 0;
            }
            QToolTip {
                background: #2d2d44;
                color: #e0e0e0;
                border: 1px solid #7C4DFF;
                padding: 6px;
                font-size: 10px;
            }
            QStatusBar {
                background: #12122a;
                color: #7ec8e3;
                border-top: 1px solid #2d2d44;
                font-size: 10px;
            }
        """)

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Tab 1 — Live Monitor
        self._live_tab = LiveMonitorTab(self.service)
        self._tabs.addTab(self._live_tab, "🔴  Live Monitor")

        # Tab 2 — Simulation Lab
        self._sim_tab = SimulationTab(self.service)
        self._tabs.addTab(self._sim_tab, "🧪  Simulation Lab")

        # Tab 3 — Dashboard
        self._dash_tab = DashboardTab(self.service)
        self._tabs.addTab(self._dash_tab, "📊  Dashboard")

        self.setCentralWidget(self._tabs)

    # ── Status bar ────────────────────────────────────────────────────────

    def _init_status_bar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)

        self._lbl_mode   = QLabel("Mode: —")
        self._lbl_procs  = QLabel("Processes: —")
        self._lbl_cpu    = QLabel("CPU: —")
        self._lbl_ram    = QLabel("RAM: —")
        self._lbl_ipc    = QLabel("IPC links: —")

        separator = " │ "
        for lbl in (self._lbl_mode, self._lbl_procs, self._lbl_cpu,
                    self._lbl_ram, self._lbl_ipc):
            lbl.setFont(QFont("Segoe UI", 9))
            sb.addWidget(lbl)
            sb.addWidget(QLabel(separator))

        # Right-side: project badge
        badge = QLabel("OS IPC Monitor  v2.0")
        badge.setStyleSheet("color:#7C4DFF; font-weight:bold;")
        sb.addPermanentWidget(badge)

    # ── Service events ────────────────────────────────────────────────────

    def _connect_events(self):
        self.service.subscribe_to_events(
            EventType.MODE_SWITCHED, self._on_mode_switched
        )

    def _on_mode_switched(self, mode: str, **_):
        if mode == "live":
            self._lbl_mode.setText("Mode: 🔴 LIVE")
            self._lbl_mode.setStyleSheet("color:#4CAF50; font-weight:bold;")

    # ── Status bar refresh ────────────────────────────────────────────────

    def _refresh_status_bar(self):
        # Live processes count
        procs = self.service.get_live_processes()
        if procs:
            self._lbl_procs.setText(f"Processes: {len(procs):,}")
        else:
            self._lbl_procs.setText("Processes: —")

        # System stats
        stats = self.service.get_system_stats()
        if stats:
            self._lbl_cpu.setText(f"CPU: {stats.cpu_percent:.1f}%")
            self._lbl_ram.setText(f"RAM: {stats.memory_percent:.1f}%")
        else:
            self._lbl_cpu.setText("CPU: —")
            self._lbl_ram.setText("RAM: —")

        # IPC connections
        conns = self.service.get_live_connections()
        real = [c for c in conns if c.pid_a != 0]
        self._lbl_ipc.setText(f"IPC links: {len(real)}")

        # Mode badge when stopped
        if not self.service.is_live_mode:
            self._lbl_mode.setText("Mode: ⏸ Stopped")
            self._lbl_mode.setStyleSheet("color:#9E9E9E;")

    # ── Close event ───────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Cleanly stop all background threads on exit."""
        self.service.stop_live_mode()
        self.service.reset()
        super().closeEvent(event)
