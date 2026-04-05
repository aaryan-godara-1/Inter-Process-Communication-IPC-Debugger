"""
process_table.py — Real process list table widget.

A QAbstractTableModel + QTableView combination that displays live OS
processes with sortable columns, CPU/memory highlighting, and a
real-time filter bar.
"""

from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QLabel, QPushButton, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    pyqtSignal, QTimer,
)
from PyQt5.QtGui import QColor, QBrush, QFont

from system_monitor.data_models import ProcessSnapshot

# Column indices
COL_PID = 0
COL_NAME = 1
COL_STATUS = 2
COL_CPU = 3
COL_MEM = 4
COL_THREADS = 5
COL_USER = 6

HEADERS = ["PID", "Name", "Status", "CPU %", "RAM (MB)", "Threads", "User"]

# Colour thresholds
HIGH_CPU_COLOR = QColor(200, 80, 80, 180)      # red-ish
NEW_PROC_COLOR = QColor(60, 180, 60, 160)       # green
ZOMBIE_COLOR = QColor(160, 160, 60, 160)        # amber


class ProcessTableModel(QAbstractTableModel):
    """
    Table model backed by a list of ProcessSnapshot objects.

    Supports sorting on all numeric and string columns.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[ProcessSnapshot] = []

    def update(self, processes: List[ProcessSnapshot]) -> None:
        """Replace the entire process list and trigger a full repaint."""
        self.beginResetModel()
        self._data = sorted(processes, key=lambda p: p.cpu_percent, reverse=True)
        self.endResetModel()

    # ── QAbstractTableModel interface ───────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None

        proc = self._data[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            return self._cell_text(proc, col)

        if role == Qt.BackgroundRole:
            return self._row_color(proc)

        if role == Qt.ForegroundRole:
            if proc.is_high_cpu or proc.status == "zombie":
                return QBrush(Qt.white)
            if proc.is_new:
                return QBrush(Qt.black)

        if role == Qt.TextAlignmentRole:
            if col in (COL_PID, COL_CPU, COL_MEM, COL_THREADS):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        if role == Qt.UserRole:
            return proc  # for click handling

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        self.beginResetModel()
        reverse = (order == Qt.DescendingOrder)
        key_fns = {
            COL_PID: lambda p: p.pid,
            COL_NAME: lambda p: p.name.lower(),
            COL_STATUS: lambda p: p.status,
            COL_CPU: lambda p: p.cpu_percent,
            COL_MEM: lambda p: p.memory_rss,
            COL_THREADS: lambda p: p.num_threads,
            COL_USER: lambda p: p.username.lower(),
        }
        self._data.sort(key=key_fns.get(column, lambda p: p.pid), reverse=reverse)
        self.endResetModel()

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _cell_text(proc: ProcessSnapshot, col: int) -> str:
        if col == COL_PID:     return str(proc.pid)
        if col == COL_NAME:    return proc.name
        if col == COL_STATUS:  return proc.status
        if col == COL_CPU:     return f"{proc.cpu_percent:.1f}"
        if col == COL_MEM:     return f"{proc.memory_rss_mb:.1f}"
        if col == COL_THREADS: return str(proc.num_threads)
        if col == COL_USER:    return proc.username
        return ""

    @staticmethod
    def _row_color(proc: ProcessSnapshot) -> Optional[QBrush]:
        if proc.is_high_cpu:       return QBrush(HIGH_CPU_COLOR)
        if proc.is_new:            return QBrush(NEW_PROC_COLOR)
        if proc.status == "zombie":return QBrush(ZOMBIE_COLOR)
        return None


class ProcessTableWidget(QWidget):
    """
    Complete process-table panel with filter bar, refresh count, and
    colour legend.

    Signals:
        processSelected(ProcessSnapshot) — emitted when user clicks a row
    """

    processSelected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Top bar ─────────────────────────────────────────────────
        top_bar = QHBoxLayout()

        lbl = QLabel("🖥  Live Processes")
        lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl.setStyleSheet("color: #7ec8e3;")
        top_bar.addWidget(lbl)
        top_bar.addStretch()

        self._count_lbl = QLabel("0 processes")
        self._count_lbl.setStyleSheet("color:#9E9E9E; font-size:10px;")
        top_bar.addWidget(self._count_lbl)

        layout.addLayout(top_bar)

        # ── Filter bar ───────────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Type process name or PID…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._filter_edit, stretch=1)
        layout.addLayout(filter_bar)

        # ── Table ────────────────────────────────────────────────────
        self._model = ProcessTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self._table.horizontalHeader().setSortIndicatorShown(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            "QTableView { selection-background-color: #3a5a8a; }"
            "QTableView::item { padding: 2px 6px; }"
        )
        self._table.clicked.connect(self._on_row_clicked)
        layout.addWidget(self._table, stretch=1)

        # ── Legend ───────────────────────────────────────────────────
        legend = QHBoxLayout()
        for color, label in [
            ("#C85050", "High CPU"),
            ("#3CB43C", "New process"),
            ("#A0A03C", "Zombie"),
        ]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:14px;")
            legend.addWidget(dot)
            legend.addWidget(QLabel(label))
            legend.addSpacing(12)
        legend.addStretch()
        layout.addLayout(legend)

    # ── Public API ──────────────────────────────────────────────────────

    def update_processes(self, processes) -> None:
        self._model.update(processes)
        self._count_lbl.setText(f"{len(processes):,} processes")

    # ── Slots ────────────────────────────────────────────────────────────

    def _apply_filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _on_row_clicked(self, index: QModelIndex) -> None:
        src_index = self._proxy.mapToSource(index)
        proc = self._model.data(src_index, Qt.UserRole)
        if proc:
            self.processSelected.emit(proc)
