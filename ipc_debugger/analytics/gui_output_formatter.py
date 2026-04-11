"""
gui_output_formatter.py — Structured output formatter for GUI.

Combines data from ALL analysis components into one clean
JSON-compatible dict that Member 3's GUI can directly consume.

Interface:
    GUIOutputFormatter.get_full_report()     → dict
    GUIOutputFormatter.get_alerts_feed()     → list[dict]
    GUIOutputFormatter.get_status_banner()   → dict
"""

import time
from typing import Dict, List, Optional


class GUIOutputFormatter:
    """
    Single point of contact between analysis engine and GUI.

    Member 3 only needs to call get_full_report() to get
    everything — deadlocks, latency, throughput, alerts,
    anomalies all in one clean structured dict.
    """

    def __init__(self,
                 deadlock_analyzer=None,
                 latency_tracker=None,
                 throughput_tracker=None,
                 alert_manager=None,
                 anomaly_detector=None,
                 event_correlator=None):

        self.deadlock_analyzer = deadlock_analyzer
        self.latency_tracker = latency_tracker
        self.throughput_tracker = throughput_tracker
        self.alert_manager = alert_manager
        self.anomaly_detector = anomaly_detector
        self.event_correlator = event_correlator

    def get_full_report(self) -> Dict:
        """
        Generate complete structured report for GUI dashboard.
        Member 3 calls this one function to get everything.
        """
        return {
            "timestamp": time.time(),
            "timestamp_str": time.strftime('%Y-%m-%d %H:%M:%S'),
            "deadlock": self._get_deadlock_data(),
            "latency": self._get_latency_data(),
            "throughput": self._get_throughput_data(),
            "alerts": self._get_alerts_data(),
            "anomalies": self._get_anomaly_data(),
            "chains": self._get_chain_data(),
            "status": self._get_status_banner()
        }

    def get_status_banner(self) -> Dict:
        """
        Returns simple status for GUI header banner.
        GREEN / YELLOW / RED
        """
        return self._get_status_banner()

    def get_alerts_feed(self) -> List[Dict]:
        """Returns latest alerts for GUI notification feed."""
        return self._get_alerts_data()

    # ── internal helpers ──────────────────────────────────────────────

    def _get_deadlock_data(self) -> Dict:
        if not self.deadlock_analyzer:
            return {"available": False}
        report = self.deadlock_analyzer.get_report()
        return {
            "available": True,
            "has_deadlock": report.get("has_deadlock", False),
            "severity": report.get("severity", "OK"),
            "cycle_count": report.get("cycle_count", 0),
            "cycles": report.get("cycles_readable", []),
            "processes_involved": report.get("processes_involved", [])
        }

    def _get_latency_data(self) -> Dict:
        if not self.latency_tracker:
            return {"available": False}
        return {
            "available": True,
            "summary": self.latency_tracker.get_summary(),
            "spikes": self.latency_tracker.detect_spikes(),
            "averages": self.latency_tracker.get_all_avg_latencies()
        }

    def _get_throughput_data(self) -> Dict:
        if not self.throughput_tracker:
            return {"available": False}
        return {
            "available": True,
            "throughputs": self.throughput_tracker.get_all_throughputs(),
            "bottlenecks": self.throughput_tracker.get_bottlenecks()
        }

    def _get_alerts_data(self) -> List[Dict]:
        if not self.alert_manager:
            return []
        return [
            {
                "severity": a.severity,
                "type": a.alert_type,
                "message": a.message,
                "timestamp": a.timestamp
            }
            for a in self.alert_manager.get_latest(20)
        ]

    def _get_anomaly_data(self) -> List[Dict]:
        if not self.anomaly_detector:
            return []
        return self.anomaly_detector.get_anomalies()

    def _get_chain_data(self) -> List[Dict]:
        if not self.event_correlator:
            return []
        return self.event_correlator.get_chains()

    def _get_status_banner(self) -> Dict:
        """
        Compute overall system status for GUI banner.
        """
        # Check deadlock
        if self.deadlock_analyzer:
            if self.deadlock_analyzer.has_deadlock():
                return {
                    "color": "RED",
                    "status": "CRITICAL",
                    "message": "Deadlock detected!"
                }

        # Check latency spikes
        if self.latency_tracker:
            spikes = self.latency_tracker.detect_spikes()
            if spikes:
                return {
                    "color": "YELLOW",
                    "status": "WARNING",
                    "message": f"{len(spikes)} channel(s) have high latency"
                }

        # Check bottlenecks
        if self.throughput_tracker:
            bottlenecks = self.throughput_tracker.get_bottlenecks()
            if bottlenecks:
                return {
                    "color": "YELLOW",
                    "status": "WARNING",
                    "message": f"{len(bottlenecks)} bottleneck(s) detected"
                }

        return {
            "color": "GREEN",
            "status": "HEALTHY",
            "message": "All systems normal"
        }