"""
race_condition.py — Race-condition detector for shared memory.

Analyses the SharedMemory access log for patterns that indicate
potential data races:  two or more processes accessing the same key
within a short time window where at least one access is a write.

Interface:
    RaceConditionDetector.analyse(access_log)  → list[RaceWarning]
    RaceConditionDetector.set_window(ms)       → None
"""

import threading
from dataclasses import dataclass
from typing import List

from ipc_debugger.core.shared_memory import AccessRecord


@dataclass
class RaceWarning:
    """Describes a detected potential race condition."""
    key: str
    pid_a: int
    pid_b: int
    operation_a: str   # "read" or "write"
    operation_b: str
    time_gap_ms: float
    message: str


class RaceConditionDetector:
    """
    Detects potential race conditions in shared-memory access logs.

    Two accesses to the same key by different PIDs are flagged as a
    potential race when:
      1. They occur within ``window_ms`` milliseconds of each other.
      2. At least one of them is a write.
    """

    def __init__(self, window_ms: float = 2.0):
        self.window_ms: float = window_ms   # ms
        self._warnings: List[RaceWarning] = []
        self._lock = threading.Lock()

    # ── public interface ────────────────────────────────────────────────

    def analyse(self, access_log: List[AccessRecord]) -> List[RaceWarning]:
        """
        Scan *access_log* for race conditions.

        Returns a list of ``RaceWarning`` objects.
        """
        warnings: List[RaceWarning] = []
        n = len(access_log)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = access_log[i], access_log[j]
                # Same key, different PIDs, at least one write
                if (a.key == b.key
                        and a.pid != b.pid
                        and (a.operation == "write" or b.operation == "write")):
                    gap_ms = abs(b.timestamp - a.timestamp) * 1000
                    if gap_ms <= self.window_ms:
                        msg = (f"Race on key '{a.key}': "
                               f"P{a.pid}({a.operation}) vs "
                               f"P{b.pid}({b.operation}) "
                               f"Δ={gap_ms:.1f}ms")
                        warnings.append(RaceWarning(
                            key=a.key,
                            pid_a=a.pid, pid_b=b.pid,
                            operation_a=a.operation,
                            operation_b=b.operation,
                            time_gap_ms=gap_ms,
                            message=msg,
                        ))
        with self._lock:
            self._warnings = warnings
        return warnings

    def get_warnings(self) -> List[RaceWarning]:
        """Return warnings from the last ``analyse()`` call."""
        with self._lock:
            return list(self._warnings)

    def set_window(self, ms: float) -> None:
        """Change the detection window (milliseconds)."""
        self.window_ms = ms

    def clear(self) -> None:
        """Clear stored warnings."""
        with self._lock:
            self._warnings.clear()
