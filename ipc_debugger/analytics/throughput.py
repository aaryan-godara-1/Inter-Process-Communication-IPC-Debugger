"""
throughput.py — IPC throughput tracker.

Counts the number of messages per unit time on each channel and
identifies bottlenecks (channels with throughput below a threshold).

Interface:
    ThroughputTracker.record_event(channel_id, ts)  → None
    ThroughputTracker.get_throughput(channel_id)     → float  (msg/s)
    ThroughputTracker.get_bottlenecks(threshold)     → list[str]
"""

import threading
from typing import Dict, List
from collections import defaultdict


class ThroughputTracker:
    """
    Tracks message throughput (messages per second) per IPC channel.
    """

    def __init__(self):
        self._events: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record_event(self, channel_id: str, ts: float) -> None:
        """Record a message-transfer event timestamp."""
        with self._lock:
            self._events[channel_id].append(ts)

    def get_throughput(self, channel_id: str) -> float:
        """
        Compute throughput for *channel_id* in messages/second.

        Uses the time span between the first and last recorded event.
        """
        with self._lock:
            times = self._events.get(channel_id, [])
            if len(times) < 2:
                return 0.0
            duration = times[-1] - times[0]
            if duration <= 0:
                return 0.0
            return (len(times) - 1) / duration

    def get_all_throughputs(self) -> Dict[str, float]:
        """Return ``{channel_id: msg/s}`` for every tracked channel."""
        with self._lock:
            result = {}
            for ch, times in self._events.items():
                if len(times) < 2:
                    result[ch] = 0.0
                else:
                    dur = times[-1] - times[0]
                    result[ch] = (len(times) - 1) / dur if dur > 0 else 0.0
            return result

    def get_bottlenecks(self, threshold: float = 1.0) -> List[str]:
        """
        Return channel IDs whose throughput is below *threshold* msg/s.
        """
        throughputs = self.get_all_throughputs()
        return [ch for ch, tp in throughputs.items()
                if 0 < tp < threshold]

    def get_event_count(self, channel_id: str) -> int:
        """Total events recorded for a channel."""
        with self._lock:
            return len(self._events.get(channel_id, []))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
