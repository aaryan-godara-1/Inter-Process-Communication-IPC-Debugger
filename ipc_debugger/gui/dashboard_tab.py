"""
dashboard_tab.py — System Performance Dashboard tab.

Displays:
  • Four MetricGauge widgets: CPU, Memory, Disk I/O, Network I/O
  • SparkLine charts for CPU and Memory history
  • TopNWidget for top processes by CPU and by Memory
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont

from utils.constants import EventType
from system_monitor.data_models import SystemStatsSnapshot
from gui.gauge_widgets import MetricGauge, SparkLine, TopNWidget, _format_bytes


class DashboardTab(QWidget):
    """
    Performance Dashboard.

    Subscribes to SYSTEM_STATS_UPDATE and PROCESS_SNAPSHOT events to
    keep all widgets refreshed in real time.
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._init_ui()
        self._connect_service()

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("📊  System Performance Dashboard — Real Kernel Data")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet("color:#7ec8e3; padding:4px 0;")
        root.addWidget(title)

        # ── Row 1: Four gauges ────────────────────────────────────────
        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(8)

        self._cpu_gauge  = MetricGauge("CPU", "%", 100)
        self._mem_gauge  = MetricGauge("Memory", "%", 100)
        self._disk_gauge = MetricGauge("Disk Read", "B/s")
        self._net_gauge  = MetricGauge("Net Recv", "B/s")

        for g in (self._cpu_gauge, self._mem_gauge,
                  self._disk_gauge, self._net_gauge):
            g.setMinimumSize(160, 160)
            gauge_row.addWidget(g)

        root.addLayout(gauge_row)

        # ── Row 2: Spark lines ────────────────────────────────────────
        spark_group = QGroupBox("History (last 4 min)")
        spark_group.setFont(QFont("Segoe UI", 9))
        spark_layout = QVBoxLayout(spark_group)
        spark_layout.setSpacing(4)

        self._cpu_spark = SparkLine("CPU %", color="#EF5350", unit="%", max_value=100)
        self._mem_spark = SparkLine("Memory %", color="#42A5F5", unit="%", max_value=100)
        self._disk_spark_r = SparkLine("Disk Read", color="#66BB6A", unit="B/s")
        self._disk_spark_w = SparkLine("Disk Write", color="#FFA726", unit="B/s")

        self._cpu_spark.setMinimumHeight(80)
        self._mem_spark.setMinimumHeight(80)

        spark_layout.addWidget(self._cpu_spark)
        spark_layout.addWidget(self._mem_spark)

        disk_row = QHBoxLayout()
        disk_row.addWidget(self._disk_spark_r)
        disk_row.addWidget(self._disk_spark_w)
        spark_layout.addLayout(disk_row)

        root.addWidget(spark_group)

        # ── Row 3: Top-N tables ───────────────────────────────────────
        topn_row = QHBoxLayout()
        topn_row.setSpacing(8)

        self._topn_cpu = TopNWidget("Top by CPU", "%", "#EF5350")
        self._topn_mem = TopNWidget("Top by RAM", "MB", "#42A5F5")

        topn_row.addWidget(self._topn_cpu)
        topn_row.addWidget(self._topn_mem)

        root.addLayout(topn_row)

        # ── Stats footer ──────────────────────────────────────────────
        self._footer = QLabel("Waiting for live data…  Start Live Monitor on the Live tab.")
        self._footer.setStyleSheet("color:#616161; font-size:9px;")
        root.addWidget(self._footer)

    # ── Service wiring ────────────────────────────────────────────────────

    def _connect_service(self):
        self.service.subscribe_to_events(
            EventType.SYSTEM_STATS_UPDATE, self._on_stats_update
        )
        self.service.subscribe_to_events(
            EventType.PROCESS_SNAPSHOT, self._on_process_snapshot
        )

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_stats_update(self, stats: SystemStatsSnapshot, **_):
        from PyQt5.QtCore import QMetaObject, Qt as Qtc
        self._pending_stats = stats
        QMetaObject.invokeMethod(self, "_apply_stats", Qtc.QueuedConnection)

    @pyqtSlot()
    def _apply_stats(self):
        stats = getattr(self, "_pending_stats", None)
        if stats is None:
            return

        # Gauges
        self._cpu_gauge.set_value(stats.cpu_percent)
        mem_gb = stats.memory_used / (1024**3)
        total_gb = stats.memory_total / (1024**3)
        self._mem_gauge.set_value(
            stats.memory_percent,
            subtitle=f"{mem_gb:.1f} / {total_gb:.1f} GB",
        )
        self._disk_gauge.set_value(stats.disk_read_bytes_s)
        self._disk_gauge.max_value = max(stats.disk_read_bytes_s * 1.2, 1_000_000)
        self._net_gauge.set_value(stats.net_recv_bytes_s)
        self._net_gauge.max_value = max(stats.net_recv_bytes_s * 1.2, 100_000)

        # Spark lines from ring buffer
        perf = self.service.get_perf_history()
        self._cpu_spark.set_data(perf.get_cpu_history())
        self._mem_spark.set_data(perf.get_memory_history())
        reads, writes = perf.get_disk_history()
        max_disk = max(max(reads, default=1), max(writes, default=1), 1)
        self._disk_spark_r.set_data(reads, max_disk)
        self._disk_spark_w.set_data(writes, max_disk)

        # Footer
        import datetime
        uptime_s = __import__("time").time() - stats.boot_time
        h, rem = divmod(int(uptime_s), 3600)
        m, s = divmod(rem, 60)
        swap_mb = stats.swap_used / (1024**2)
        self._footer.setText(
            f"Uptime: {h}h {m}m {s}s  |  "
            f"Swap used: {swap_mb:.0f} MB  |  "
            f"Processes: {stats.process_count}  |  "
            f"Disk W: {_format_bytes(stats.disk_write_bytes_s)}/s  |  "
            f"Net ↑: {_format_bytes(stats.net_sent_bytes_s)}/s"
        )

    def _on_process_snapshot(self, processes, **_):
        from PyQt5.QtCore import QMetaObject, Qt as Qtc
        self._pending_procs = processes
        QMetaObject.invokeMethod(self, "_apply_topn", Qtc.QueuedConnection)

    @pyqtSlot()
    def _apply_topn(self):
        processes = getattr(self, "_pending_procs", [])

        # Top by CPU
        by_cpu = sorted(processes, key=lambda p: p.cpu_percent, reverse=True)[:8]
        cpu_rows = [(p.name, p.pid, p.cpu_percent) for p in by_cpu]
        max_cpu = max((p.cpu_percent for p in by_cpu), default=1)
        self._topn_cpu.set_data(cpu_rows, max_value=max_cpu)

        # Top by memory
        by_mem = sorted(processes, key=lambda p: p.memory_rss, reverse=True)[:8]
        mem_rows = [(p.name, p.pid, p.memory_rss_mb) for p in by_mem]
        max_mem = max((p.memory_rss_mb for p in by_mem), default=1)
        self._topn_mem.set_data(mem_rows, max_value=max_mem)
