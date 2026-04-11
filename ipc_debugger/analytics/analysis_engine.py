"""
analysis_engine.py — Central analysis engine for IPC Debugger.

Subscribes to IPCLogger and coordinates all detectors:
- Deadlock detection
- Bottleneck detection  
- Latency tracking
- Race condition detection

Emits structured alerts for the GUI.
"""

import threading
import time
from typing import List, Dict, Callable
from collections import deque

from debugger.logger import IPCLogger, LogEvent
from debugger.deadlock_detector import DeadlockDetector
from analytics.latency import LatencyTracker
from analytics.throughput import ThroughputTracker
from analytics.race_condition import RaceConditionDetector


class AnalysisEngine:

    def __init__(self, logger: IPCLogger):
        self.logger = logger
        self.deadlock_detector = DeadlockDetector()
        self.latency_tracker = LatencyTracker()
        self.throughput_tracker = ThroughputTracker()
        self.alerts: deque = deque(maxlen=100)
        self._subscribers: List[Callable] = []
        self._lock = threading.Lock()

        # Subscribe to logger in real time
        logger.subscribe(self._on_event)

    def _on_event(self, event: LogEvent) -> None:
        """Called automatically on every new IPC event."""
        # Track latency
        if event.event_type in ("send", "write"):
            self.latency_tracker.record_send(event.channel_id, event.ts)
        elif event.event_type in ("receive", "read"):
            self.latency_tracker.record_receive(event.channel_id, event.ts)

        # Track throughput
        self.throughput_tracker.record_event(event.channel_id, event.ts)

        # Check for bottlenecks
        bottlenecks = self.throughput_tracker.get_bottlenecks()
        for ch in bottlenecks:
            self._emit_alert("WARNING", "BOTTLENECK",
                           f"Channel {ch} is a bottleneck")

    def run_deadlock_check(self, processes, channels) -> Dict:
        """Run deadlock detection and return results."""
        self.deadlock_detector.update(processes, channels, self.logger)
        cycles = self.deadlock_detector.detect()

        if cycles:
            for cycle in cycles:
                self._emit_alert("CRITICAL", "DEADLOCK",
                               f"Deadlock detected: {' → '.join(map(str, cycle))}")

        return {
            "deadlock": len(cycles) > 0,
            "cycles": cycles,
            "graph": self.deadlock_detector.get_graph()
        }

    def get_summary(self) -> Dict:
        """Return structured summary for GUI."""
        return {
            "total_events": len(self.logger.get_events()),
            "latencies": self.latency_tracker.get_all_avg_latencies(),
            "throughputs": self.throughput_tracker.get_all_throughputs(),
            "bottlenecks": self.throughput_tracker.get_bottlenecks(),
            "alerts": list(self.alerts)
        }

    def _emit_alert(self, severity: str, alert_type: str, message: str) -> None:
        """Store alert and notify subscribers."""
        alert = {
            "severity": severity,
            "type": alert_type,
            "message": message,
            "timestamp": time.time()
        }
        with self._lock:
            self.alerts.append(alert)
        for cb in self._subscribers:
            try:
                cb(alert)
            except Exception:
                pass

    def subscribe(self, callback: Callable) -> None:
        """Register callback for real time alerts."""
        self._subscribers.append(callback)

    def get_alerts(self) -> List[Dict]:
        """Return all alerts."""
        with self._lock:
            return list(self.alerts)

    def clear(self) -> None:
        """Reset all trackers."""
        self.latency_tracker.clear()
        self.throughput_tracker.clear()
        self.alerts.clear()