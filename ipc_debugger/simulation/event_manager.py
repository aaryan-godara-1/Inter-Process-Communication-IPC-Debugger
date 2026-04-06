"""
event_manager.py — Central event bus (observer pattern).

Any module can emit events, and any module can subscribe to event types.
This keeps modules decoupled — they communicate through the bus rather
than holding references to each other.

Interface:
    EventManager.subscribe(event_type, callback)  → None
    EventManager.emit(event_type, **data)          → None
    EventManager.clear()                           → None
"""

import threading
from typing import Callable, Dict, List, Any

from ipc_debugger.utils.constants import EventType


class EventManager:
    """
    Publish-subscribe event bus.

    Subscribers register interest in an ``EventType`` and receive a
    dict of keyword arguments whenever that event is emitted.
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType,
                  callback: Callable[..., None]) -> None:
        """Register *callback* for *event_type*."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: EventType,
                    callback: Callable) -> None:
        """Remove a callback from *event_type*."""
        with self._lock:
            listeners = self._subscribers.get(event_type, [])
            self._subscribers[event_type] = [
                cb for cb in listeners if cb is not callback
            ]

    def emit(self, event_type: EventType, **data: Any) -> None:
        """
        Fire *event_type* with arbitrary keyword data.

        All subscribers registered for that type are called synchronously
        in the order they were registered.
        """
        with self._lock:
            listeners = list(self._subscribers.get(event_type, []))
        for cb in listeners:
            try:
                cb(**data)
            except Exception as exc:
                print(f"[EventManager] subscriber error on {event_type}: {exc}")

    def clear(self) -> None:
        """Remove all subscriptions."""
        with self._lock:
            self._subscribers.clear()
