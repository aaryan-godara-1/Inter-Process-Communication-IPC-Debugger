"""
latency.py — IPC latency tracker.

Measures the time between a send and the corresponding receive on each
channel to quantify communication latency.

Interface:
    LatencyTracker.record_send(channel_id, ts)     → None
    LatencyTracker.record_receive(channel_id, ts)   → None
    LatencyTracker.get_avg_latency(channel_id)      → float
    LatencyTracker.get_latency_history()             → dict
"""

import threading
from typing import Dict, List
from collections import defaultdict


class LatencyTracker:

    def __init__(self):
        self._pending: Dict[str, List[float]] = defaultdict(list)
        self._latencies: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record_send(self, channel_id: str, ts: float) -> None:
        """Record the timestamp of a send event."""
        with self._lock:
            self._pending[channel_id].append(ts)

    def record_receive(self, channel_id: str, ts: float) -> None:
        """Record a receive event and pair with oldest unmatched send."""
        with self._lock:
            pending = self._pending.get(channel_id, [])
            if pending:
                send_ts = pending.pop(0)
                latency = (ts - send_ts) * 1000
                self._latencies[channel_id].append(latency)

    def get_avg_latency(self, channel_id: str) -> float:
        """Average latency in ms for channel_id."""
        with self._lock:
            vals = self._latencies.get(channel_id, [])
            return sum(vals) / len(vals) if vals else 0.0

    def get_all_avg_latencies(self) -> Dict[str, float]:
        """Return {channel_id: avg_ms} for every tracked channel."""
        with self._lock:
            return {
                ch: (sum(v) / len(v) if v else 0.0)
                for ch, v in self._latencies.items()
            }

    def get_latency_history(self) -> Dict[str, List[float]]:
        """Full latency history per channel."""
        with self._lock:
            return {ch: list(v) for ch, v in self._latencies.items()}

    def get_max_latency(self, channel_id: str) -> float:
        """Maximum latency ever recorded for a channel in ms."""
        with self._lock:
            vals = self._latencies.get(channel_id, [])
            return max(vals) if vals else 0.0

    def get_min_latency(self, channel_id: str) -> float:
        """Minimum latency ever recorded for a channel in ms."""
        with self._lock:
            vals = self._latencies.get(channel_id, [])
            return min(vals) if vals else 0.0

    def detect_spikes(self, threshold_ms: float = 100.0) -> list:
        """
        Return list of channels where average latency
        exceeds threshold_ms.
        """
        with self._lock:
            spikes = []
            for ch, vals in self._latencies.items():
                if vals:
                    avg = sum(vals) / len(vals)
                    if avg > threshold_ms:
                        spikes.append({
                            "channel_id": ch,
                            "avg_latency_ms": avg,
                            "severity": "CRITICAL" if avg > 500 else "WARNING"
                        })
            return spikes

    def get_summary(self) -> dict:
        """Return structured latency summary for GUI."""
        with self._lock:
            summary = {}
            for ch, vals in self._latencies.items():
                if vals:
                    summary[ch] = {
                        "avg_ms": sum(vals) / len(vals),
                        "max_ms": max(vals),
                        "min_ms": min(vals),
                        "count": len(vals)
                    }
            return summary

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()
            self._latencies.clear()