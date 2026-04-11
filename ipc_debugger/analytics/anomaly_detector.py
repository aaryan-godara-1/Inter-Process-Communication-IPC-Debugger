"""
anomaly_detector.py — Anomaly detection for IPC Debugger.

Builds a baseline of normal behaviour and flags
anything that deviates significantly.

Interface:
    AnomalyDetector.record(channel_id, value)   → None
    AnomalyDetector.check(channel_id, value)    → bool
    AnomalyDetector.get_anomalies()             → list[dict]
"""

import time
import threading
from typing import Dict, List
from collections import defaultdict


class AnomalyDetector:
    """
    Detects anomalies by comparing current values
    against a running baseline average.
    Flags values that exceed threshold x baseline.
    """

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold
        self._baselines: Dict[str, List[float]] = defaultdict(list)
        self._anomalies: List[Dict] = []
        self._lock = threading.Lock()

    def record(self, channel_id: str, value: float) -> None:
        """Record a normal value to build baseline."""
        with self._lock:
            self._baselines[channel_id].append(value)

    def check(self, channel_id: str, value: float) -> bool:
        """
        Check if value is anomalous compared to baseline.
        Returns True if anomaly detected.
        """
        with self._lock:
            baseline = self._baselines.get(channel_id, [])
            if len(baseline) < 5:
                # Not enough data yet
                return False

            avg = sum(baseline) / len(baseline)
            if avg == 0:
                return False

            if value > avg * self.threshold:
                self._anomalies.append({
                    "channel_id": channel_id,
                    "value": value,
                    "baseline_avg": avg,
                    "ratio": value / avg,
                    "timestamp": time.time()
                })
                return True
            return False

    def get_anomalies(self) -> List[Dict]:
        """Return all detected anomalies."""
        with self._lock:
            return list(self._anomalies)

    def get_baseline(self, channel_id: str) -> float:
        """Return current baseline average for a channel."""
        with self._lock:
            vals = self._baselines.get(channel_id, [])
            return sum(vals) / len(vals) if vals else 0.0

    def clear(self) -> None:
        with self._lock:
            self._baselines.clear()
            self._anomalies.clear()