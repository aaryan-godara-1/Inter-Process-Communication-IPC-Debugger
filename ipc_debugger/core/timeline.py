"""
Timeline engine for storing and querying IPC events.

Maintains a chronological stream of events with efficient indexing
for fast queries by time, process, resource, etc.
"""

from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ipc_debugger.core.events import IPCEvent, IPCType


@dataclass
class TimeRange:
    """Represents a time range query."""
    start_ns: int = 0
    end_ns: int = 2**63 - 1  # Max int64
    
    def contains(self, timestamp_ns: int) -> bool:
        return self.start_ns <= timestamp_ns <= self.end_ns


class EventTimeline:
    """
    In-memory timeline of IPC events.
    
    Supports:
    - Chronological event stream
    - Fast queries by time, process, resource
    - Causal chain reconstruction
    - Ring buffer overflow handling
    """
    
    def __init__(self, max_events: int = 100000):
        self.max_events = max_events
        self._events: List[IPCEvent] = []
        self._next_index = 0
        self._is_full = False
        
        # Indices for fast lookup
        self._by_process: Dict[int, List[IPCEvent]] = {}
        self._by_resource: Dict[str, List[IPCEvent]] = {}
        self._by_correlation: Dict[str, List[IPCEvent]] = {}
        self._by_event_id: Dict[str, IPCEvent] = {}
        
        # Synchronization
        self._lock = threading.RLock()
    
    def add_event(self, event: IPCEvent) -> None:
        """Add an event to the timeline."""
        with self._lock:
            # Add to main list (ring buffer)
            if len(self._events) < self.max_events:
                self._events.append(event)
            else:
                self._is_full = True
                # Replace oldest event
                old_event = self._events[self._next_index]
                self._events[self._next_index] = event
                
                # Remove old event from indices
                self._remove_from_indices(old_event)
            
            self._next_index = (self._next_index + 1) % self.max_events
            
            # Add to indices
            self._add_to_indices(event)
    
    def get_event_by_id(self, event_id: str) -> Optional[IPCEvent]:
        """Get a single event by ID."""
        with self._lock:
            return self._by_event_id.get(event_id)
    
    def get_events_in_range(self, time_range: TimeRange) -> List[IPCEvent]:
        """Get all events within a time range."""
        with self._lock:
            result = []
            for event in self._events:
                if time_range.contains(event.timestamp_ns):
                    result.append(event)
            return sorted(result, key=lambda e: e.timestamp_ns)
    
    def get_events_by_process(self, pid: int, time_range: Optional[TimeRange] = None) -> List[IPCEvent]:
        """Get all events for a process."""
        with self._lock:
            events = self._by_process.get(pid, [])
            if time_range:
                return [e for e in events if time_range.contains(e.timestamp_ns)]
            return sorted(events, key=lambda e: e.timestamp_ns)
    
    def get_events_by_resource(self, resource_id: str, time_range: Optional[TimeRange] = None) -> List[IPCEvent]:
        """Get all events for a resource."""
        with self._lock:
            events = self._by_resource.get(resource_id, [])
            if time_range:
                return [e for e in events if time_range.contains(e.timestamp_ns)]
            return sorted(events, key=lambda e: e.timestamp_ns)
    
    def get_events_by_correlation(self, correlation_id: str) -> List[IPCEvent]:
        """Get all events with a correlation ID (for request-response chains)."""
        with self._lock:
            events = self._by_correlation.get(correlation_id, [])
            return sorted(events, key=lambda e: e.timestamp_ns)
    
    def get_causal_chain(self, event_id: str) -> List[IPCEvent]:
        """
        Reconstruct a causal chain starting from an event.
        
        Follows parent_event_id backwards and child_event_ids forwards.
        """
        with self._lock:
            chain = []
            visited: Set[str] = set()
            
            # Start with the given event
            current = self._by_event_id.get(event_id)
            if not current:
                return []
            
            # Trace backwards to find the root
            while current and current.parent_event_id and current.parent_event_id not in visited:
                current = self._by_event_id.get(current.parent_event_id)
                if current:
                    visited.add(current.event_id)
            
            # Now trace forward from root
            if current:
                chain = self._trace_causal_forward(current, visited)
            
            return chain
    
    def _trace_causal_forward(self, event: IPCEvent, visited: Set[str]) -> List[IPCEvent]:
        """Recursively trace a causal chain forward."""
        chain = [event]
        visited.add(event.event_id)
        
        # Follow children
        for child_id in event.child_event_ids:
            if child_id not in visited:
                child = self._by_event_id.get(child_id)
                if child:
                    chain.extend(self._trace_causal_forward(child, visited))
        
        return chain
    
    def get_request_response_flow(self, start_event_id: str) -> List[IPCEvent]:
        """
        Get a request-response flow.
        
        Starting from a request event, finds the matching response.
        """
        with self._lock:
            start_event = self._by_event_id.get(start_event_id)
            if not start_event:
                return []
            
            correlation_id = start_event.correlation_id
            if not correlation_id:
                return [start_event]
            
            events = self._by_correlation.get(correlation_id, [])
            return sorted(events, key=lambda e: e.timestamp_ns)
    
    def get_all_processes(self) -> List[int]:
        """Get list of all processes in the timeline."""
        with self._lock:
            return sorted(self._by_process.keys())
    
    def get_all_resources(self) -> List[str]:
        """Get list of all resources in the timeline."""
        with self._lock:
            return sorted(self._by_resource.keys())
    
    def get_latest_n(self, n: int) -> List[IPCEvent]:
        """Get the N most recent events."""
        with self._lock:
            return sorted(self._events, key=lambda e: e.timestamp_ns, reverse=True)[:n]
    
    def get_process_pair_events(self, pid1: int, pid2: int) -> List[IPCEvent]:
        """Get all events between two processes."""
        with self._lock:
            events = []
            for event in self._events:
                if (event.process_id == pid1 or event.process_id == pid2):
                    # Check if involves both
                    if event.parent_event_id:
                        parent = self._by_event_id.get(event.parent_event_id)
                        if parent and parent.process_id in (pid1, pid2):
                            if event.process_id in (pid1, pid2):
                                events.append(event)
                    else:
                        # Check children
                        for child_id in event.child_event_ids:
                            child = self._by_event_id.get(child_id)
                            if child and child.process_id in (pid1, pid2):
                                if event.process_id in (pid1, pid2):
                                    events.append(event)
                                    break
            
            return sorted(events, key=lambda e: e.timestamp_ns)
    
    def clear(self) -> None:
        """Clear all events."""
        with self._lock:
            self._events.clear()
            self._next_index = 0
            self._is_full = False
            self._by_process.clear()
            self._by_resource.clear()
            self._by_correlation.clear()
            self._by_event_id.clear()
    
    def size(self) -> int:
        """Get current number of events."""
        with self._lock:
            return len(self._events)
    
    def is_full(self) -> bool:
        """Check if buffer is full."""
        with self._lock:
            return self._is_full
    
    def _add_to_indices(self, event: IPCEvent) -> None:
        """Add event to all index structures."""
        # Index by event ID
        self._by_event_id[event.event_id] = event
        
        # Index by process
        if event.process_id not in self._by_process:
            self._by_process[event.process_id] = []
        self._by_process[event.process_id].append(event)
        
        # Index by resource
        if event.resource_id:
            if event.resource_id not in self._by_resource:
                self._by_resource[event.resource_id] = []
            self._by_resource[event.resource_id].append(event)
        
        # Index by correlation
        if event.correlation_id:
            if event.correlation_id not in self._by_correlation:
                self._by_correlation[event.correlation_id] = []
            self._by_correlation[event.correlation_id].append(event)
    
    def _remove_from_indices(self, event: IPCEvent) -> None:
        """Remove event from all index structures."""
        self._by_event_id.pop(event.event_id, None)
        
        if event.process_id in self._by_process:
            self._by_process[event.process_id] = [
                e for e in self._by_process[event.process_id]
                if e.event_id != event.event_id
            ]
        
        if event.resource_id and event.resource_id in self._by_resource:
            self._by_resource[event.resource_id] = [
                e for e in self._by_resource[event.resource_id]
                if e.event_id != event.event_id
            ]
        
        if event.correlation_id and event.correlation_id in self._by_correlation:
            self._by_correlation[event.correlation_id] = [
                e for e in self._by_correlation[event.correlation_id]
                if e.event_id != event.event_id
            ]
