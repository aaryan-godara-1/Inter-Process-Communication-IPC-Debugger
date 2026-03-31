"""
controls.py — Control panel, log viewer, and analytics display blocks.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QSlider, QListWidget, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt, pyqtSignal

from utils.constants import Scenario


class ControlPanelWidget(QWidget):
    """
    Simulation controls: Load scenario, play/pause/stop, speed slider.
    """
    
    # Signals emitted when user clicks buttons
    actionLoadScenario = pyqtSignal(Scenario)
    actionStart = pyqtSignal()
    actionPause = pyqtSignal()
    actionStep = pyqtSignal()
    actionReset = pyqtSignal()
    actionSpeedChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # 1. Scenario Selector
        self.cb_scenario = QComboBox()
        for s in Scenario:
            self.cb_scenario.addItem(s.value, s)
        self.btn_load = QPushButton("Load Scenario")
        self.btn_load.clicked.connect(self._on_load_clicked)

        # 2. Playback Controls
        self.btn_start = QPushButton("▶ Start")
        self.btn_start.clicked.connect(self.actionStart.emit)
        
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self.actionPause.emit)
        
        self.btn_step = QPushButton("⏭ Step")
        self.btn_step.clicked.connect(self.actionStep.emit)
        
        self.btn_reset = QPushButton("⏹ Reset")
        self.btn_reset.clicked.connect(self.actionReset.emit)

        # 3. Speed slider
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setMinimum(50)
        self.slider_speed.setMaximum(3000)
        self.slider_speed.setValue(500)
        self.slider_speed.setTickPosition(QSlider.TicksBelow)
        self.slider_speed.setTickInterval(500)
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        
        self.lbl_speed = QLabel("Delay: 500 ms")

        # Assemble layout
        layout.addWidget(QLabel("Scenario:"))
        layout.addWidget(self.cb_scenario)
        layout.addWidget(self.btn_load)
        layout.addSpacing(20)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_step)
        layout.addWidget(self.btn_reset)
        layout.addSpacing(20)
        layout.addWidget(QLabel("Simulation Speed:"))
        layout.addWidget(self.slider_speed)
        layout.addWidget(self.lbl_speed)
        
        # Push everything to the left
        layout.addStretch()

    def _on_load_clicked(self):
        # Data attached to item is the Scenario enum value
        data = self.cb_scenario.currentData()
        self.actionLoadScenario.emit(data)

    def _on_speed_changed(self, value: int):
        self.lbl_speed.setText(f"Delay: {value} ms")
        self.actionSpeedChanged.emit(value)


class LogPanelWidget(QWidget):
    """
    Displays the raw stream of IPC events.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("IPC Event Log")
        group_layout = QVBoxLayout(group)
        
        self.list_widget = QListWidget()
        self.list_widget.setFont(self.font())  # Default font, we can style it monospaced later
        # monospaced style
        self.list_widget.setStyleSheet("font-family: monospace; font-size: 10pt;")
        
        group_layout.addWidget(self.list_widget)
        layout.addWidget(group)

    def append_log(self, text: str):
        self.list_widget.addItem(text)
        self.list_widget.scrollToBottom()

    def clear(self):
        self.list_widget.clear()


class AnalyticsPanelWidget(QWidget):
    """
    Displays performance analytics: latency, throughput, and warnings.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("Performance Analytics")
        group_layout = QVBoxLayout(group)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Channel ID", "Avg Latency (ms)", "Throughput (msg/s)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        group_layout.addWidget(self.table)
        
        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_warnings.setWordWrap(True)
        group_layout.addWidget(self.lbl_warnings)
        
        layout.addWidget(group)

    def update_stats(self, channels: set, 
                     latencies: dict, 
                     throughputs: dict):
        self.table.setRowCount(max(1, len(channels)))
        
        if not channels:
            item = QTableWidgetItem("No channels active")
            self.table.setItem(0, 0, item)
            return
            
        for row, ch_id in enumerate(sorted(channels)):
            lat = latencies.get(ch_id, 0.0)
            thr = throughputs.get(ch_id, 0.0)
            
            self.table.setItem(row, 0, QTableWidgetItem(ch_id))
            self.table.setItem(row, 1, QTableWidgetItem(f"{lat:.1f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{thr:.1f}"))

    def set_warnings(self, msgs: list):
        if msgs:
            self.lbl_warnings.setText("\n".join(msgs))
        else:
            self.lbl_warnings.setText("")

    def clear(self):
        self.table.setRowCount(0)
        self.set_warnings([])
