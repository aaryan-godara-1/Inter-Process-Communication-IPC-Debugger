"""
stats_reporter.py — Statistics reporter for IPC Debugger.

Generates structured performance reports from all analysis data.
Provides summary data for the GUI dashboard.

Interface:
    StatsReporter.generate_report()  → dict
    StatsReporter.print_report()     → None
"""

import time
import threading
from typing import Dict, List, Optional
from analytics.latency import LatencyTracker
from analytics.throughput import ThroughputTracker


class StatsReporter:
    """
    Aggregates data from all trackers and generates
    structured reports for the GUI.
    """

    def __init__(self, latency_tracker: LatencyTracker,
                 throughput_tracker: ThroughputTracker):
        self.latency_tracker = latency_tracker
        self.throughput_tracker = throughput_tracker
        self._lock = threading.Lock()
        self._report_history: List[Dict] = []

    def generate_report(self) -> Dict:
        """
        Generate a full structured report of current system state.
        Returns clean dict for GUI consumption.
        """
        latencies = self.latency_tracker.get_all_avg_latencies()
        throughputs = self.throughput_tracker.get_all_throughputs()
        bottlenecks = self.throughput_tracker.get_bottlenecks()

        # Find busiest channel
        busiest = max(throughputs, key=throughputs.get) \
            if throughputs else None

        # Find slowest channel
        slowest = max(latencies, key=latencies.get) \
            if latencies else None

        report = {
            "timestamp": time.time(),
            "total_channels": len(throughputs),
            "busiest_channel": busiest,
            "slowest_channel": slowest,
            "bottleneck_channels": bottlenecks,
            "avg_latencies": latencies,
            "throughputs": throughputs,
            "health": self._compute_health(bottlenecks, latencies)
        }

        with self._lock:
            self._report_history.append(report)

        return report

    def _compute_health(self, bottlenecks: List[str],
                        latencies: Dict[str, float]) -> str:
        """
        Compute overall system health score.
        Returns HEALTHY / DEGRADED / CRITICAL
        """
        if len(bottlenecks) == 0 and all(v < 100 for v in latencies.values()):
            return "HEALTHY"
        elif len(bottlenecks) <= 2:
            return "DEGRADED"
        else:
            return "CRITICAL"

    def get_history(self) -> List[Dict]:
        """Return all previously generated reports."""
        with self._lock:
            return list(self._report_history)

    def print_report(self) -> None:
        """Print a human readable report to console."""
        report = self.generate_report()
        print("\n===== IPC SYSTEM REPORT =====")
        print(f"Total Channels  : {report['total_channels']}")
        print(f"Busiest Channel : {report['busiest_channel']}")
        print(f"Slowest Channel : {report['slowest_channel']}")
        print(f"Bottlenecks     : {report['bottleneck_channels']}")
        print(f"System Health   : {report['health']}")
        print("==============================\n")

    def clear(self) -> None:
        with self._lock:
            self._report_history.clear()