"""
logger.py — Centralised IPC event logger.

Records every IPC event (send, receive, channel create/close) with full
metadata.  Exposes a subscription API so other parts of the system
(debugger, GUI, analytics) can react in real time.

Interface:
    IPCLogger.log(event_type, channel_id, pid, data)  → None
    IPCLogger.get_events()                             → list[LogEvent]
    IPCLogger.subscribe(callback)                      → None
    IPCLogger.clear()                                  → None
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from utils.helpers import timestamp, timestamp_str


@dataclass
class LogEvent:
    """A single logged IPC event."""
    event_type: str          # "write", "read", "send", "receive", "close", …
    channel_id: str
    pid: int
    data: str
    ts: float = field(default_factory=timestamp)
    ts_str: str = field(default_factory=timestamp_str)

    def __str__(self) -> str:
        return f"[{self.ts_str}] {self.event_type.upper():8s} ch={self.channel_id} pid={self.pid} | {self.data}"


class IPCLogger:
    """
    Singleton-style centralised logger.

    All IPC channels call ``log()`` on every operation, and the logger
    forwards the event to all registered subscribers (debugger, GUI, etc.).
    """

    def __init__(self):
        self._events: List[LogEvent] = []
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[LogEvent], None]] = []

    # ── public interface ────────────────────────────────────────────────

    def log(self, event_type: str, channel_id: str,
            pid: int, data: str) -> None:
        """Record an event and notify all subscribers."""
        event = LogEvent(event_type=event_type,
                         channel_id=channel_id,
                         pid=pid, data=data)
        with self._lock:
            self._events.append(event)
        # Notify subscribers outside the lock
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                pass  # don't let a bad subscriber crash logging

    def get_events(self, last_n: Optional[int] = None) -> List[LogEvent]:
        """Return a copy of all logged events (or the last *n*)."""
        with self._lock:
            if last_n:
                return list(self._events[-last_n:])
            return list(self._events)

    def subscribe(self, callback: Callable[[LogEvent], None]) -> None:
        """Register a callback that will be called on every new event."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """Remove a previously registered subscriber."""
        self._subscribers = [s for s in self._subscribers if s is not callback]

    def clear(self) -> None:
        """Discard all logged events."""
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        return len(self._events)
