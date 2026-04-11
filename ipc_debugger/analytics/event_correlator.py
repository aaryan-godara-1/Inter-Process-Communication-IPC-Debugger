"""
event_correlator.py — Links related IPC events into cause-effect chains.

Connects events across processes to trace root causes of issues.

Interface:
    EventCorrelator.add_event(event)        → None
    EventCorrelator.get_chains()            → list[dict]
    EventCorrelator.clear()                 → None
"""

import threading
from typing import List, Dict
from collections import defaultdict


class EventCorrelator:
    """
    Groups related IPC events into chains showing
    cause and effect across processes.
    """

    def __init__(self):
        self._chains: Dict[str, List] = defaultdict(list)
        self._lock = threading.Lock()

    def add_event(self, event) -> None:
        """Add event to its channel chain."""
        with self._lock:
            self._chains[event.channel_id].append({
                "pid": event.pid,
                "type": event.event_type,
                "data": event.data,
                "timestamp": event.ts
            })

    def get_chains(self) -> List[Dict]:
        """Return all event chains per channel."""
        with self._lock:
            return [
                {
                    "channel_id": ch,
                    "events": list(events),
                    "event_count": len(events)
                }
                for ch, events in self._chains.items()
            ]

    def get_chain(self, channel_id: str) -> List[Dict]:
        """Return event chain for a specific channel."""
        with self._lock:
            return list(self._chains.get(channel_id, []))

    def clear(self) -> None:
        with self._lock:
            self._chains.clear()