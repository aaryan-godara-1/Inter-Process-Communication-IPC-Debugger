"""
shared_memory.py — Shared Memory IPC implementation.

Provides a key-value shared memory region protected by read/write locks.
Tracks every access for race-condition analysis.

Interface:
    SharedMemory.write(key, value, pid)  → None
    SharedMemory.read(key, pid)          → Any
    SharedMemory.get_snapshot()           → dict
    SharedMemory.get_access_log()         → list
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, List, Dict

from ipc_debugger.utils.constants import IPCType
from ipc_debugger.utils.helpers import timestamp


@dataclass
class AccessRecord:
    """Single read/write access to shared memory."""
    operation: str          # "read" or "write"
    key: str
    pid: int
    timestamp: float
    value: Any = None


class SharedMemory:
    """
    Thread-safe shared memory region backed by a dict.

    Every access is recorded in an internal log so that the
    RaceConditionDetector can analyse concurrent access patterns.
    """

    def __init__(self, shm_id: str = "",
                 on_event: Optional[Callable] = None):
        self.shm_id: str = shm_id or f"shm-{id(self)}"
        self.ipc_type: IPCType = IPCType.SHARED_MEMORY
        self._data: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._access_log: List[AccessRecord] = []
        self._on_event: Optional[Callable] = on_event
        self._open: bool = True

    # ── public interface ────────────────────────────────────────────────

    def write(self, key: str, value: Any, pid: int = 0) -> None:
        """Write *value* under *key*.  Thread-safe."""
        if not self._open:
            raise RuntimeError(f"SharedMemory '{self.shm_id}' is closed")
        with self._lock:
            self._data[key] = value
            record = AccessRecord("write", key, pid, timestamp(), value)
            self._access_log.append(record)
        if self._on_event:
            self._on_event("write", self.shm_id, pid, f"{key}={value}")

    def read(self, key: str, pid: int = 0) -> Any:
        """Read value for *key*.  Returns None if key doesn't exist."""
        with self._lock:
            value = self._data.get(key)
            record = AccessRecord("read", key, pid, timestamp(), value)
            self._access_log.append(record)
        if self._on_event:
            self._on_event("read", self.shm_id, pid, f"{key}={value}")
        return value

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy of the current memory contents."""
        with self._lock:
            return dict(self._data)

    def get_access_log(self) -> List[AccessRecord]:
        """Return a copy of all access records (for race-condition analysis)."""
        with self._lock:
            return list(self._access_log)

    def clear_log(self) -> None:
        """Clear the access log (e.g. after a reset)."""
        with self._lock:
            self._access_log.clear()

    def close(self) -> None:
        """Close the shared memory region."""
        self._open = False
        if self._on_event:
            self._on_event("close", self.shm_id, 0, "")

    @property
    def is_open(self) -> bool:
        return self._open

    def __repr__(self) -> str:
        status = "open" if self._open else "closed"
        return (f"<SharedMemory {self.shm_id} [{status}] "
                f"keys={list(self._data.keys())}>")
