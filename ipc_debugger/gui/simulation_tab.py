"""
simulation_tab.py — Simulation Lab tab.

Wraps the existing ControlPanelWidget, ProcessGraphWidget, LogPanelWidget,
and AnalyticsPanelWidget into a QWidget tab — zero changes to their logic.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from utils.constants import EventType, Scenario
from gui.visualization import ProcessGraphWidget
from gui.controls import ControlPanelWidget, LogPanelWidget, AnalyticsPanelWidget
from PyQt5.QtCore import pyqtSignal


class SimulationTab(QWidget):
    """
    Self-contained Simulation Lab panel.

    Receives the IPCService reference and wires up all simulation controls
    and event subscriptions internally.
    """

    sig_log = pyqtSignal(object)
    sig_deadlock = pyqtSignal(list)
    sig_race = pyqtSignal(list)
    sig_reset = pyqtSignal()
    sig_started = pyqtSignal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._init_ui()
        self._connect_service()

        # Periodic analytics refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_analytics)
        self._timer.start(500)

        # Wire thread-safe signals
        self.sig_log.connect(self._safe_log_event)
        self.sig_deadlock.connect(self._safe_deadlock)
        self.sig_race.connect(self._safe_race)
        self.sig_reset.connect(self._safe_reset)
        self.sig_started.connect(self._safe_started)

    # ── UI layout ───────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Theory badge
        badge = QLabel("🧪  OS Theory Demonstration — Simulated IPC / Deadlock / Race Conditions")
        badge.setStyleSheet(
            "background:#2a3f5f; color:#7ec8e3; padding:5px 10px;"
            "border-radius:4px; font-size:11px;"
        )
        badge.setFont(QFont("Segoe UI", 9))
        root.addWidget(badge)

        # Control panel
        self.control_panel = ControlPanelWidget()
        self.control_panel.actionLoadScenario.connect(self._on_load_scenario)
        self.control_panel.actionStart.connect(self.service.start)
        self.control_panel.actionPause.connect(self.service.pause)
        self.control_panel.actionStep.connect(self.service.step)
        self.control_panel.actionReset.connect(self.service.reset)
        self.control_panel.actionSpeedChanged.connect(self.service.set_speed)
        root.addWidget(self.control_panel)

        # Splitter: graph | log + analytics
        splitter = QSplitter(Qt.Horizontal)

        self.graph_widget = ProcessGraphWidget(self.service)
        splitter.addWidget(self.graph_widget)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.log_panel = LogPanelWidget()
        self.analytics_panel = AnalyticsPanelWidget()

        right_layout.addWidget(self.log_panel, stretch=2)
        right_layout.addWidget(self.analytics_panel, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([700, 500])

        root.addWidget(splitter, stretch=1)

    # ── Service wiring ──────────────────────────────────────────────────

    def _connect_service(self):
        self.service.subscribe_to_logs(self._on_log_event)
        self.service.subscribe_to_events(EventType.DEADLOCK_DETECTED, self._on_deadlock)
        self.service.subscribe_to_events(
            EventType.RACE_CONDITION_DETECTED, self._on_race_condition
        )
        self.service.subscribe_to_events(EventType.SIMULATION_RESET, self._on_reset)
        self.service.subscribe_to_events(EventType.SIMULATION_STARTED, self._on_started)

    # ── Event handlers (called from background threads) ───────────────

    def _on_load_scenario(self, scenario: Scenario):
        self.service.load_scenario(scenario)
        self.log_panel.clear()
        self.analytics_panel.clear()
        self.log_panel.append_log(f"--- Loaded Scenario: {scenario.value} ---")

    def _on_log_event(self, event):
        self.sig_log.emit(event)

    def _on_deadlock(self, cycles, **_):
        self.sig_deadlock.emit(cycles)

    def _on_race_condition(self, warnings, **_):
        self.sig_race.emit(warnings)

    def _on_reset(self, **_):
        self.sig_reset.emit()

    def _on_started(self, **_):
        self.sig_started.emit()

    # ── Safe GUI Handlers (executed in main GUI thread) ─────────────────

    def _safe_log_event(self, event):
        self.log_panel.append_log(str(event))
        self.graph_widget.highlight_edge(event.pid, event.channel_id)

    def _safe_deadlock(self, cycles):
        msg = f"💥 DEADLOCK DETECTED! Cycles: {cycles}"
        self.log_panel.append_log(msg)
        self.analytics_panel.lbl_warnings.setText(msg)

    def _safe_race(self, warnings):
        for w in warnings:
            self.log_panel.append_log(f"⚠️ RACE: {w.message}")
        self.analytics_panel.set_warnings([f"⚠️ RACE: {w.message}" for w in warnings])

    def _safe_reset(self):
        self.log_panel.append_log("--- Simulation Reset ---")
        self.analytics_panel.clear()

    def _safe_started(self):
        self.log_panel.append_log("--- Simulation Started ---")

    def _refresh_analytics(self):
        channels = set(self.service.get_channels().keys())
        latencies = self.service.latency_tracker.get_all_avg_latencies()
        throughputs = self.service.throughput_tracker.get_all_throughputs()
        self.analytics_panel.update_stats(channels, latencies, throughputs)

    # ── Public API ──────────────────────────────────────────────────────

    def load_default_scenario(self):
        """Called by MainWindow on startup to pre-load Normal Flow."""
        self.service.load_scenario(Scenario.NORMAL_FLOW)
