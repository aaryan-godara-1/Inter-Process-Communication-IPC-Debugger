"""
system_perf_tracker.py — Rolling history of system performance metrics.

Maintains a fixed-size ring buffer of SystemStatsSnapshot entries so the
dashboard can render time-series charts for CPU, memory, and I/O without
storing unlimited data.

Interface:
    SystemPerfTracker.record(snapshot)       → None
    SystemPerfTracker.get_cpu_history()      → list[float]
    SystemPerfTracker.get_memory_history()   → list[float]
    SystemPerfTracker.get_disk_history()     → tuple[list, list]
    SystemPerfTracker.get_net_history()      → tuple[list, list]
    SystemPerfTracker.get_timestamps()       → list[float]
"""

import threading
from collections import deque
from typing import Deque, List, Optional, Tuple

from system_monitor.data_models import SystemStatsSnapshot


class SystemPerfTracker:
    """
    Fixed-size ring buffer of SystemStatsSnapshot objects.

    Default capacity = 120 entries. At 2-second polling this covers
    4 minutes of history — enough for a meaningful chart without
    consuming significant memory.
    """

    def __init__(self, capacity: int = 120):
        self._capacity = capacity
        self._buffer: Deque[SystemStatsSnapshot] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    # ── recording ───────────────────────────────────────────────────────

    def record(self, snapshot: SystemStatsSnapshot) -> None:
        """Append a new snapshot to the ring buffer."""
        with self._lock:
            self._buffer.append(snapshot)

    def clear(self) -> None:
        """Clear all history."""
        with self._lock:
            self._buffer.clear()

    # ── retrieval ───────────────────────────────────────────────────────

    def get_timestamps(self) -> List[float]:
        with self._lock:
            return [s.timestamp for s in self._buffer]

    def get_cpu_history(self) -> List[float]:
        """Per-poll overall CPU % values."""
        with self._lock:
            return [s.cpu_percent for s in self._buffer]

    def get_memory_history(self) -> List[float]:
        """Per-poll memory usage % values."""
        with self._lock:
            return [s.memory_percent for s in self._buffer]

    def get_disk_history(self) -> Tuple[List[float], List[float]]:
        """Returns (read_bytes_s_list, write_bytes_s_list)."""
        with self._lock:
            reads = [s.disk_read_bytes_s for s in self._buffer]
            writes = [s.disk_write_bytes_s for s in self._buffer]
        return reads, writes

    def get_net_history(self) -> Tuple[List[float], List[float]]:
        """Returns (sent_bytes_s_list, recv_bytes_s_list)."""
        with self._lock:
            sent = [s.net_sent_bytes_s for s in self._buffer]
            recv = [s.net_recv_bytes_s for s in self._buffer]
        return sent, recv

    def get_latest(self) -> Optional[SystemStatsSnapshot]:
        """Return the most recently recorded snapshot."""
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def __len__(self) -> int:
        return len(self._buffer)
