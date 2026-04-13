"""
Analysis engine for IPC debugging.

Implements:
- Causal chain reconstruction
- Flow stitching (request-response correlation)
- Lock and wait graph tracking
- Deadlock detection
- Latency analysis
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ipc_debugger.core.events import (
    IPCEvent,
    EventType,
    EventResult,
    EventSource,
    LockEvent,
    WaitEntry,
    DeadlockCycle,
)
from ipc_debugger.core.timeline import EventTimeline


class FlowStitcher:
    """
    Correlates request-response pairs and reconstructs message flows.
    
    Matches:
    - SEND → RECV
    - REQUEST → RESPONSE
    - ENQUEUE → DEQUEUE
    """
    
    def __init__(self, timeline: EventTimeline):
        self.timeline = timeline
        self._pending_requests: Dict[str, IPCEvent] = {}  # correlation_id -> event
        self._completed_flows: List[List[IPCEvent]] = []
        self._lock = threading.RLock()
    
    def on_event(self, event: IPCEvent) -> None:
        """Process an event for flow stitching."""
        with self._lock:
            if event.event_type in (EventType.SEND, EventType.REQUEST, EventType.ENQUEUE):
                self._pending_requests[event.correlation_id] = event
            
            elif event.event_type in (EventType.RECV, EventType.RESPONSE, EventType.DEQUEUE):
                if event.correlation_id in self._pending_requests:
                    start_event = self._pending_requests[event.correlation_id]
                    flow = self._reconstruct_flow(start_event, event)
                    self._completed_flows.append(flow)
                    del self._pending_requests[event.correlation_id]
    
    def _reconstruct_flow(self, start: IPCEvent, end: IPCEvent) -> List[IPCEvent]:
        """Reconstruct the full flow between two events."""
        flow = [start]
        
        # Get all intermediate events
        time_range = (start.timestamp_ns, end.timestamp_ns)
        
        # Look for hops between processes in this timeframe
        for pid in [start.process_id, end.process_id]:
            events = self.timeline.get_events_by_process(
                pid,
                time_range=type('', (), {
                    'start_ns': time_range[0],
                    'end_ns': time_range[1],
                    'contains': lambda self, t: time_range[0] <= t <= time_range[1]
                })()
            )
            flow.extend([e for e in events if e not in flow])
        
        flow.append(end)
        return sorted(flow, key=lambda e: e.timestamp_ns)
    
    def get_completed_flows(self) -> List[List[IPCEvent]]:
        """Get all completed request-response flows."""
        with self._lock:
            return list(self._completed_flows)
    
    def get_pending_requests(self) -> Dict[str, IPCEvent]:
        """Get requests waiting for responses."""
        with self._lock:
            return dict(self._pending_requests)


class LockGraph:
    """
    Tracks lock ownership, waiting, and detects deadlocks.
    
    Maintains:
    - Current lock owners
    - Waiter queues
    - Historical lock events
    """
    
    def __init__(self):
        self.locks: Dict[str, LockEvent] = {}
        self.lock_history: List[LockEvent] = []
        self.detected_deadlocks: List[DeadlockCycle] = []
        self._lock = threading.RLock()
    
    def on_event(self, event: IPCEvent) -> None:
        """Process a lock-related event."""
        with self._lock:
            if event.event_type == EventType.ACQUIRE:
                self._handle_acquire(event)
            elif event.event_type == EventType.RELEASE:
                self._handle_release(event)
            elif event.event_type == EventType.WAIT:
                self._handle_wait(event)
            elif event.event_type == EventType.SIGNAL:
                self._handle_signal(event)
    
    def _handle_acquire(self, event: IPCEvent) -> None:
        """Handle lock acquisition."""
        lock_id = event.resource_id
        
        if lock_id not in self.locks:
            self.locks[lock_id] = LockEvent(
                lock_id=lock_id,
                lock_type=event.ipc_type,
                owner_pid=event.process_id,
                owner_tid=event.thread_id,
                acquire_time_ns=event.timestamp_ns,
                acquired_in_event_id=event.event_id,
            )
        else:
            # Reacquire (recursive lock)
            old_lock = self.locks[lock_id]
            self.lock_history.append(old_lock)
            self.locks[lock_id] = LockEvent(
                lock_id=lock_id,
                lock_type=event.ipc_type,
                owner_pid=event.process_id,
                owner_tid=event.thread_id,
                acquire_time_ns=event.timestamp_ns,
                acquired_in_event_id=event.event_id,
            )
    
    def _handle_release(self, event: IPCEvent) -> None:
        """Handle lock release."""
        lock_id = event.resource_id
        
        if lock_id in self.locks:
            lock = self.locks[lock_id]
            lock.release_time_ns = event.timestamp_ns
            lock.released_in_event_id = event.event_id
            
            # Move to history
            self.lock_history.append(lock)
            del self.locks[lock_id]
            
            # Wake up a waiter if any
            if lock.waiters:
                waiter = lock.waiters.pop(0)
                waiter.wait_end_ns = event.timestamp_ns
                waiter.is_resolved = True
    
    def _handle_wait(self, event: IPCEvent) -> None:
        """Handle thread waiting on a lock."""
        lock_id = event.resource_id
        
        if lock_id not in self.locks:
            # Lock doesn't exist, create a pending one
            self.locks[lock_id] = LockEvent(
                lock_id=lock_id,
                lock_type=event.ipc_type,
                owner_pid=0,
                owner_tid=0,
                acquire_time_ns=event.timestamp_ns,
            )
        
        # Add as waiter
        waiter = WaitEntry(
            waiter_pid=event.process_id,
            waiter_tid=event.thread_id,
            wait_start_ns=event.timestamp_ns,
            wait_reason="lock_contention",
        )
        self.locks[lock_id].waiters.append(waiter)
    
    def _handle_signal(self, event: IPCEvent) -> None:
        """Handle condition variable signal."""
        lock_id = event.resource_id
        
        if lock_id in self.locks:
            lock = self.locks[lock_id]
            if lock.waiters:
                waiter = lock.waiters.pop(0)
                waiter.wait_end_ns = event.timestamp_ns
                waiter.is_resolved = True
    
    def detect_deadlocks(self) -> List[DeadlockCycle]:
        """
        Detect deadlock cycles in the lock wait graph.
        
        Uses DFS to find cycles in:
        Process A holds Lock 1 and waits for Lock 2
        Process B holds Lock 2 and waits for Lock 1
        """
        with self._lock:
            deadlocks: List[DeadlockCycle] = []
            
            # Build a wait graph: processes -> locks they're waiting for
            waiter_graph: Dict[int, Set[str]] = {}
            holder_graph: Dict[int, Set[str]] = {}
            
            for lock_id, lock in self.locks.items():
                holder_graph.setdefault(lock.owner_pid, set()).add(lock_id)
                for waiter in lock.waiters:
                    waiter_graph.setdefault(waiter.waiter_pid, set()).add(lock_id)
            
            # Find cycles using DFS
            visited: Set[int] = set()
            rec_stack: Set[int] = set()
            
            for process in waiter_graph.keys():
                if process not in visited:
                    cycle = self._find_cycle_dfs(
                        process,
                        waiter_graph,
                        holder_graph,
                        visited,
                        rec_stack,
                        [],
                    )
                    if cycle:
                        deadlock = DeadlockCycle(
                            processes=[p for p, _ in cycle],
                            locks=[l for _, l in cycle],
                        )
                        deadlocks.append(deadlock)
            
            return deadlocks
    
    def _find_cycle_dfs(
        self,
        pid: int,
        waiter_graph: Dict[int, Set[str]],
        holder_graph: Dict[int, Set[str]],
        visited: Set[int],
        rec_stack: Set[int],
        path: List[Tuple[int, str]],
    ) -> Optional[List[Tuple[int, str]]]:
        """DFS to find a cycle."""
        visited.add(pid)
        rec_stack.add(pid)
        
        # This process waits for locks
        for lock_id in waiter_graph.get(pid, set()):
            # Find who holds this lock
            for holder_pid, held_locks in holder_graph.items():
                if lock_id in held_locks:
                    new_path = path + [(pid, lock_id), (holder_pid, lock_id)]
                    
                    if holder_pid in rec_stack:
                        # Found a cycle
                        return new_path
                    
                    if holder_pid not in visited:
                        result = self._find_cycle_dfs(
                            holder_pid,
                            waiter_graph,
                            holder_graph,
                            visited,
                            rec_stack,
                            new_path,
                        )
                        if result:
                            return result
        
        rec_stack.remove(pid)
        return None
    
    def get_lock_contention(self, lock_id: str) -> float:
        """Get contention ratio for a lock (waiters / total accesses)."""
        lock = self.locks.get(lock_id)
        if not lock:
            return 0.0
        
        total = 1 + len(lock.waiters)
        return len(lock.waiters) / total if total > 0 else 0.0
    
    def get_lock_holders(self) -> Dict[str, Tuple[int, int]]:
        """Get current lock holders (lock_id -> (owner_pid, owner_tid))."""
        with self._lock:
            return {
                lock_id: (lock.owner_pid, lock.owner_tid)
                for lock_id, lock in self.locks.items()
            }


class LatencyAnalyzer:
    """
    Analyzes end-to-end latencies of IPC operations.
    
    Computes:
    - Per-flow latency
    - P50, P95, P99 latencies
    - Outlier detection
    - Long-tail analysis
    """
    
    def __init__(self):
        self.latencies: List[int] = []
        self._lock = threading.RLock()
    
    def on_event(self, event: IPCEvent) -> None:
        """Record latency from an event."""
        with self._lock:
            if event.latency_ns > 0:
                self.latencies.append(event.latency_ns)
    
    def get_percentile(self, p: float) -> int:
        """Get the Pth percentile latency."""
        with self._lock:
            if not self.latencies:
                return 0
            
            sorted_lat = sorted(self.latencies)
            idx = int(len(sorted_lat) * p / 100.0)
            return sorted_lat[min(idx, len(sorted_lat) - 1)]
    
    def get_statistics(self) -> Dict[str, int]:
        """Get latency statistics."""
        with self._lock:
            if not self.latencies:
                return {
                    'min': 0, 'max': 0, 'avg': 0,
                    'p50': 0, 'p95': 0, 'p99': 0,
                    'count': 0,
                }
            
            sorted_lat = sorted(self.latencies)
            total = sum(self.latencies)
            
            return {
                'min': min(sorted_lat),
                'max': max(sorted_lat),
                'avg': total // len(sorted_lat),
                'p50': self.get_percentile(50),
                'p95': self.get_percentile(95),
                'p99': self.get_percentile(99),
                'count': len(self.latencies),
            }


class DebugAnalysisEngine:
    """
    Complete analysis engine combining all analysis components.
    """
    
    def __init__(self, timeline: EventTimeline):
        self.timeline = timeline
        self.flow_stitcher = FlowStitcher(timeline)
        self.lock_graph = LockGraph()
        self.latency_analyzer = LatencyAnalyzer()
        
        self._lock = threading.RLock()
    
    def on_event(self, event: IPCEvent) -> None:
        """Process an event through all analysis components."""
        with self._lock:
            self.timeline.add_event(event)
            self.flow_stitcher.on_event(event)
            self.lock_graph.on_event(event)
            self.latency_analyzer.on_event(event)
    
    def get_deadlocks(self) -> List[DeadlockCycle]:
        """Get detected deadlock cycles."""
        return self.lock_graph.detect_deadlocks()
    
    def get_flow_summary(self) -> Dict:
        """Get summary of message flows."""
        flows = self.flow_stitcher.get_completed_flows()
        return {
            'completed_flows': len(flows),
            'pending_requests': len(self.flow_stitcher.get_pending_requests()),
        }
    
    def get_lock_summary(self) -> Dict:
        """Get summary of lock state."""
        return {
            'held_locks': len(self.lock_graph.locks),
            'lock_history_size': len(self.lock_graph.lock_history),
            'detected_deadlocks': len(self.lock_graph.detected_deadlocks),
        }
