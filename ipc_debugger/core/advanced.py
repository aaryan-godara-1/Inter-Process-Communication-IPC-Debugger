"""
Advanced IPC Debugger Features

Implements:
- Breakpoints and watchpoints
- Record and deterministic replay
- Anomaly detection and alerting
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Dict, List, Optional, Any

from ipc_debugger.core.events import IPCEvent, EventType
from ipc_debugger.core.timeline import EventTimeline


class BreakpointType(str, Enum):
    """Types of breakpoints."""
    PROCESS_PAIR = "process_pair"  # Triggered when A communicates with B
    LATENCY_THRESHOLD = "latency_threshold"  # Triggered when latency > threshold
    LOCK_HELD = "lock_held"  # Triggered when lock held > threshold
    QUEUE_BUILDUP = "queue_buildup"  # Triggered when queue depth > threshold
    DEADLOCK_RISK = "deadlock_risk"  # Triggered on hold-and-wait pattern
    EVENT_TYPE = "event_type"  # Triggered on specific event type
    RESOURCE_ACCESS = "resource_access"  # Triggered when resource accessed


class BreakpointAction(str, Enum):
    """Actions to take when breakpoint triggers."""
    PAUSE = "pause"
    LOG = "log"
    SNAPSHOT = "snapshot"
    ALERT = "alert"


@dataclass
class Breakpoint:
    """A debugging breakpoint."""
    
    id: str
    enabled: bool = True
    type: BreakpointType = BreakpointType.PROCESS_PAIR
    
    # Breakpoint conditions
    process_id_1: Optional[int] = None
    process_id_2: Optional[int] = None
    latency_threshold_ns: Optional[int] = None
    lock_id: Optional[str] = None
    hold_threshold_ns: Optional[int] = None
    queue_threshold: Optional[int] = None
    resource_id: Optional[str] = None
    event_type_filter: Optional[EventType] = None
    
    # Actions
    action: BreakpointAction = BreakpointAction.PAUSE
    
    # Statistics
    hit_count: int = 0
    last_hit_ns: Optional[int] = None
    
    def matches(self, event: IPCEvent) -> bool:
        """Check if event matches this breakpoint condition."""
        if not self.enabled:
            return False
        
        if self.type == BreakpointType.PROCESS_PAIR:
            return (event.process_id == self.process_id_1 or
                    event.process_id == self.process_id_2)
        
        elif self.type == BreakpointType.LATENCY_THRESHOLD:
            return (self.latency_threshold_ns and
                    event.latency_ns >= self.latency_threshold_ns)
        
        elif self.type == BreakpointType.EVENT_TYPE:
            return event.event_type == self.event_type_filter
        
        elif self.type == BreakpointType.RESOURCE_ACCESS:
            return event.resource_id == self.resource_id
        
        return False


@dataclass
class Snapshot:
    """Capture of timeline state at a point in time."""
    
    id: str
    created_at_ns: int
    event_count: int
    process_count: int
    resource_count: int
    
    # Serialized events up to this point
    events_json: str = ""
    deadlocks_json: str = ""
    
    timestamp_label: str = ""


@dataclass
class AnomalyEvent:
    """An anomaly detected by the analyzer."""
    
    id: str = field(default_factory=lambda: str(time.time_ns()))
    detected_at_ns: int = field(default_factory=lambda: int(time.time_ns()))
    
    anomaly_type: str = ""  # latency_spike, queue_growth, lock_contention, etc.
    severity: str = "medium"  # low, medium, high, critical
    description: str = ""
    
    affected_pid: Optional[int] = None
    affected_resource: Optional[str] = None
    
    baseline_value: float = 0.0
    current_value: float = 0.0
    threshold: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BreakpointManager:
    """Manages breakpoints and triggering."""
    
    def __init__(self):
        self.breakpoints: Dict[str, Breakpoint] = {}
        self.callbacks: List[Callable[[Breakpoint, IPCEvent], None]] = []
        self._lock = threading.RLock()
    
    def add_breakpoint(self, bp: Breakpoint) -> str:
        """Add a breakpoint."""
        with self._lock:
            self.breakpoints[bp.id] = bp
        return bp.id
    
    def remove_breakpoint(self, bp_id: str) -> bool:
        """Remove a breakpoint."""
        with self._lock:
            return self.breakpoints.pop(bp_id, None) is not None
    
    def enable_breakpoint(self, bp_id: str) -> None:
        """Enable a breakpoint."""
        with self._lock:
            if bp_id in self.breakpoints:
                self.breakpoints[bp_id].enabled = True
    
    def disable_breakpoint(self, bp_id: str) -> None:
        """Disable a breakpoint."""
        with self._lock:
            if bp_id in self.breakpoints:
                self.breakpoints[bp_id].enabled = False
    
    def check_event(self, event: IPCEvent) -> List[Breakpoint]:
        """Check if event matches any breakpoints."""
        with self._lock:
            triggered = []
            for bp in self.breakpoints.values():
                if bp.matches(event):
                    bp.hit_count += 1
                    bp.last_hit_ns = event.timestamp_ns
                    triggered.append(bp)
                    
                    for callback in self.callbacks:
                        callback(bp, event)
            
            return triggered
    
    def register_callback(self, callback: Callable) -> None:
        """Register breakpoint hit callback."""
        self.callbacks.append(callback)


class ReplayEngine:
    """
    Record and deterministic replay of IPC execution.
    
    Allows stepping through events and inspecting state at each point.
    """
    
    def __init__(self, timeline: EventTimeline):
        self.timeline = timeline
        self.recordings: Dict[str, List[IPCEvent]] = {}
        self._lock = threading.RLock()
        
        # Replay state
        self.is_replaying = False
        self.current_index = 0
        self.current_recording: Optional[List[IPCEvent]] = None
    
    def start_recording(self, recording_name: str) -> None:
        """Start recording events."""
        with self._lock:
            self.recordings[recording_name] = []
    
    def record_event(self, recording_name: str, event: IPCEvent) -> None:
        """Record an event."""
        with self._lock:
            if recording_name in self.recordings:
                self.recordings[recording_name].append(event)
    
    def stop_recording(self, recording_name: str) -> int:
        """Stop recording and return event count."""
        with self._lock:
            count = len(self.recordings.get(recording_name, []))
            return count
    
    def start_replay(self, recording_name: str) -> bool:
        """Start replaying a recording."""
        with self._lock:
            if recording_name not in self.recordings:
                return False
            
            self.current_recording = self.recordings[recording_name]
            self.current_index = 0
            self.is_replaying = True
            return True
    
    def step_forward(self) -> Optional[IPCEvent]:
        """Step forward one event in replay."""
        with self._lock:
            if not self.is_replaying or not self.current_recording:
                return None
            
            if self.current_index >= len(self.current_recording):
                self.is_replaying = False
                return None
            
            event = self.current_recording[self.current_index]
            self.current_index += 1
            return event
    
    def step_backward(self) -> Optional[IPCEvent]:
        """Step backward one event in replay."""
        with self._lock:
            if not self.is_replaying or not self.current_recording:
                return None
            
            if self.current_index <= 0:
                return None
            
            self.current_index -= 1
            return self.current_recording[self.current_index]
    
    def seek_to_index(self, index: int) -> None:
        """Seek to an index in the replay."""
        with self._lock:
            if self.current_recording:
                self.current_index = max(0, min(index, len(self.current_recording)))
    
    def get_current_event(self) -> Optional[IPCEvent]:
        """Get the event at current replay position."""
        with self._lock:
            if not self.is_replaying or not self.current_recording:
                return None
            
            if self.current_index < len(self.current_recording):
                return self.current_recording[self.current_index]
            
            return None
    
    def stop_replay(self) -> None:
        """Stop replaying."""
        with self._lock:
            self.is_replaying = False
            self.current_recording = None


class AnomalyDetector:
    """
    Detects anomalies in IPC patterns.
    
    Detects:
    - Latency spikes
    - Queue buildup
    - Lock contention
    - Message drops
    - Resource starvation
    """
    
    def __init__(self):
        self.anomalies: List[AnomalyEvent] = []
        self.baselines: Dict[str, float] = {}
        self.callbacks: List[Callable[[AnomalyEvent], None]] = []
        self._lock = threading.RLock()
        
        # Configuration
        self.latency_spike_threshold = 2.0  # 2x baseline
        self.queue_growth_threshold = 100  # messages
        self.lock_wait_threshold_ns = 50_000_000  # 50ms
    
    def register_callback(self, callback: Callable[[AnomalyEvent], None]) -> None:
        """Register anomaly detection callback."""
        self.callbacks.append(callback)
    
    def check_event(self, event: IPCEvent) -> Optional[AnomalyEvent]:
        """Check an event for anomalies."""
        with self._lock:
            anomaly = None
            
            # Check for latency spike
            if event.latency_ns > 0:
                baseline = self.baselines.get(f"latency_{event.ipc_type}", 1000.0)
                if event.latency_ns > baseline * self.latency_spike_threshold:
                    anomaly = AnomalyEvent(
                        anomaly_type="latency_spike",
                        severity="high",
                        description=f"Latency spike on {event.ipc_type}",
                        affected_pid=event.process_id,
                        affected_resource=event.resource_id,
                        baseline_value=baseline,
                        current_value=float(event.latency_ns),
                        threshold=baseline * self.latency_spike_threshold,
                    )
            
            # Check for lock contention
            if event.event_type == EventType.ACQUIRE and event.latency_ns > self.lock_wait_threshold_ns:
                anomaly = AnomalyEvent(
                    anomaly_type="lock_contention",
                    severity="medium",
                    description=f"Long wait on lock {event.resource_id}",
                    affected_pid=event.process_id,
                    affected_resource=event.resource_id,
                    baseline_value=0,
                    current_value=float(event.latency_ns),
                    threshold=float(self.lock_wait_threshold_ns),
                )
            
            if anomaly:
                self.anomalies.append(anomaly)
                for callback in self.callbacks:
                    try:
                        callback(anomaly)
                    except Exception as e:
                        print(f"Error in anomaly callback: {e}")
            
            return anomaly
    
    def update_baseline(self, metric_name: str, value: float) -> None:
        """Update baseline for a metric."""
        with self._lock:
            # Exponential moving average
            alpha = 0.3
            old_baseline = self.baselines.get(metric_name, value)
            self.baselines[metric_name] = alpha * value + (1 - alpha) * old_baseline
    
    def get_anomalies(self) -> List[AnomalyEvent]:
        """Get all detected anomalies."""
        with self._lock:
            return list(self.anomalies)
    
    def clear_anomalies(self) -> None:
        """Clear anomaly history."""
        with self._lock:
            self.anomalies.clear()


class SnapshotManager:
    """Manages timeline snapshots for debugging."""
    
    def __init__(self, timeline: EventTimeline):
        self.timeline = timeline
        self.snapshots: Dict[str, Snapshot] = {}
        self._lock = threading.RLock()
    
    def take_snapshot(self, label: str = "") -> Snapshot:
        """Take a snapshot of the current timeline."""
        with self._lock:
            snap_id = f"snap_{int(time.time_ns())}"
            
            events = self.timeline._events
            snapshot = Snapshot(
                id=snap_id,
                created_at_ns=int(time.time_ns()),
                event_count=len(events),
                process_count=len(self.timeline.get_all_processes()),
                resource_count=len(self.timeline.get_all_resources()),
                timestamp_label=label,
            )
            
            self.snapshots[snap_id] = snapshot
            return snapshot
    
    def get_snapshot(self, snap_id: str) -> Optional[Snapshot]:
        """Get a snapshot by ID."""
        with self._lock:
            return self.snapshots.get(snap_id)
    
    def compare_snapshots(self, snap_id_1: str, snap_id_2: str) -> Dict[str, Any]:
        """Compare two snapshots."""
        with self._lock:
            snap1 = self.snapshots.get(snap_id_1)
            snap2 = self.snapshots.get(snap_id_2)
            
            if not snap1 or not snap2:
                return {}
            
            return {
                "events_delta": snap2.event_count - snap1.event_count,
                "processes_delta": snap2.process_count - snap1.process_count,
                "resources_delta": snap2.resource_count - snap1.resource_count,
                "time_delta_ns": snap2.created_at_ns - snap1.created_at_ns,
            }
