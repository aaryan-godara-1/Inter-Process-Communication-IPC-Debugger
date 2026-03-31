"""
main_window.py — Main GUI application window.

Assembles the ProcessGraphWidget, ControlPanelWidget, LogPanelWidget,
and AnalyticsPanelWidget into a cohesive layout.
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter
)
from PyQt5.QtCore import Qt, QTimer

from utils.constants import EventType, Scenario
from service import IPCService
from gui.visualization import ProcessGraphWidget
from gui.controls import ControlPanelWidget, LogPanelWidget, AnalyticsPanelWidget


class MainWindow(QMainWindow):
    """
    The main window of the IPC Debugger application.
    """
    
    def __init__(self, service: IPCService):
        super().__init__()
        self.service = service
        self.setWindowTitle("OS IPC Debugger")
        self.resize(1200, 800)
        
        self._init_ui()
        self._connect_service()
        
        # Periodic UI update timer for analytics
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._refresh_analytics)
        self.update_timer.start(500)  # Refresh every 500ms

        # Load default scenario
        self.service.load_scenario(Scenario.NORMAL_FLOW)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # 1. Top Control Panel
        self.control_panel = ControlPanelWidget()
        self.control_panel.actionLoadScenario.connect(self._on_load_scenario)
        self.control_panel.actionStart.connect(self.service.start)
        self.control_panel.actionPause.connect(self.service.pause)
        self.control_panel.actionStep.connect(self.service.step)
        self.control_panel.actionReset.connect(self.service.reset)
        self.control_panel.actionSpeedChanged.connect(self.service.set_speed)
        main_layout.addWidget(self.control_panel)
        
        # 2. Splitter for Graph, Logs, Analytics
        splitter = QSplitter(Qt.Horizontal)
        
        # 2a. Left side: Graph
        self.graph_widget = ProcessGraphWidget(self.service)
        splitter.addWidget(self.graph_widget)
        
        # 2b. Right side: Logs over Analytics
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.log_panel = LogPanelWidget()
        self.analytics_panel = AnalyticsPanelWidget()
        
        right_layout.addWidget(self.log_panel, stretch=2)
        right_layout.addWidget(self.analytics_panel, stretch=1)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions (e.g. 60% graph, 40% side panel)
        splitter.setSizes([700, 500])
        main_layout.addWidget(splitter, stretch=1)

    def _connect_service(self):
        """Wire up service events to UI updates."""
        # Logs
        self.service.subscribe_to_logs(self._on_log_event)
        
        # System events
        self.service.subscribe_to_events(EventType.DEADLOCK_DETECTED, self._on_deadlock)
        self.service.subscribe_to_events(EventType.RACE_CONDITION_DETECTED, self._on_race_condition)
        self.service.subscribe_to_events(EventType.SIMULATION_RESET, self._on_reset)
        self.service.subscribe_to_events(EventType.SIMULATION_STARTED, self._on_started)

    # ── UI Event Handlers ───────────────────────────────────────────────

    def _on_load_scenario(self, scenario: Scenario):
        """User selected a new scenario."""
        self.service.load_scenario(scenario)
        self.log_panel.clear()
        self.analytics_panel.clear()
        self.log_panel.append_log(f"--- Loaded Scenario: {scenario.value} ---")
        
    def _on_log_event(self, event):
        """A new log event arrived from the core."""
        self.log_panel.append_log(str(event))
        # Tell the graph to pulse this edge
        self.graph_widget.highlight_edge(event.pid, event.channel_id)

    def _on_deadlock(self, cycles):
        """System detected a deadlock."""
        msg = f"💥 DEADLOCK DETECTED! Cycles: {cycles}"
        self.log_panel.append_log(msg)
        self.analytics_panel.lbl_warnings.setText(msg)

    def _on_race_condition(self, warnings):
        """System detected a race condition."""
        alerts = []
        for w in warnings:
            alert = f"⚠️ RACE: {w.message}"
            alerts.append(alert)
            self.log_panel.append_log(alert)
        self.analytics_panel.set_warnings(alerts)

    def _on_reset(self, **kwargs):
        """Simulation was reset."""
        self.log_panel.append_log("--- Simulation Reset ---")
        self.analytics_panel.clear()
        
    def _on_started(self, **kwargs):
        self.log_panel.append_log("--- Simulation Started ---")

    def _refresh_analytics(self):
        """Polled refresh of the analytics table."""
        channels = set(self.service.get_channels().keys())
        latencies = self.service.latency_tracker.get_all_avg_latencies()
        throughputs = self.service.throughput_tracker.get_all_throughputs()
        
        self.analytics_panel.update_stats(channels, latencies, throughputs)
