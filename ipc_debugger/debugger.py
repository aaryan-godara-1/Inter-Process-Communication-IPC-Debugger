"""
Main IPC Debugger Service.

Orchestrates kernel event collection, timeline management, and analysis.
Provides the primary interface for debugger operations.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from ipc_debugger.core.collector import (
    KernelEventCollector,
    CaptureConfig,
    CaptureStatus,
)
from ipc_debugger.core.simulated_collector import SimulatedCollector
from ipc_debugger.core.windows_etw_collector import WindowsETWCollector
from ipc_debugger.core.events import IPCEvent, DeadlockCycle
from ipc_debugger.core.timeline import EventTimeline
from ipc_debugger.core.analysis import DebugAnalysisEngine
from ipc_debugger.core.advanced import (
    BreakpointManager,
    Breakpoint,
    ReplayEngine,
    AnomalyDetector,
    SnapshotManager,
)
from ipc_debugger.core.export import TraceExporter, ExportOptions, IntegrationAPI, QueryAPI


@dataclass
class DebuggerState:
    """Current state of the debugger."""
    
    status: CaptureStatus = CaptureStatus.IDLE
    total_events: int = 0
    total_processes: int = 0
    total_resources: int = 0
    
    deadlocks_detected: int = 0
    high_latency_events: int = 0
    
    start_time_ns: int = 0
    duration_ns: int = 0


class IPCDebugger:
    """
    Main IPC debugger service.
    
    Usage:
        debugger = IPCDebugger()
        config = CaptureConfig(ipc_types=[IPCType.PIPE, IPCType.MUTEX])
        debugger.start_capture(config)
        # ... debugger runs in background ...
        deadlocks = debugger.get_deadlocks()
        flows = debugger.get_flows()
        debugger.stop_capture()
    """
    
    def __init__(self, use_real_collector: bool = True):
        """Initialize the debugger."""
        if not sys.platform.startswith("win"):
            raise OSError("IPCDebugger is Windows-only")

        self.timeline = EventTimeline()
        self.analysis = DebugAnalysisEngine(self.timeline)
        
        if use_real_collector:
            self.collector = WindowsETWCollector()
        else:
            self.collector = SimulatedCollector()
        self.collector.register_event_callback(self._on_kernel_event)
        self.collector.register_status_callback(self._on_collector_status)
        
        self.state = DebuggerState()
        self._lock = threading.RLock()
        
        # Advanced features
        self.breakpoint_manager = BreakpointManager()
        self.replay_engine = ReplayEngine(self.timeline)
        self.anomaly_detector = AnomalyDetector()
        self.snapshot_manager = SnapshotManager(self.timeline)
        self.trace_exporter = TraceExporter()
        self.query_api = QueryAPI(self)
        
        # Setup callbacks
        self.breakpoint_manager.register_callback(self._on_breakpoint_hit)
        self.anomaly_detector.register_callback(self._on_anomaly_detected)
        
        # Event filtering
        self._event_filters: Dict[str, Any] = {}
    
    def start_capture(self, config: Optional[CaptureConfig] = None) -> None:
        """Start capturing IPC events."""
        with self._lock:
            if config:
                self.collector.set_config(config)
            
            self.state.start_time_ns = int(time.time_ns())
            self.timeline.clear()
            
            self.collector.start()
            self.state.status = CaptureStatus.CAPTURING
    
    def stop_capture(self) -> None:
        """Stop capturing IPC events."""
        with self._lock:
            self.collector.stop()
            self.state.status = CaptureStatus.STOPPED
            self.state.duration_ns = int(time.time_ns()) - self.state.start_time_ns
    
    def pause_capture(self) -> None:
        """Pause capture temporarily."""
        with self._lock:
            self.collector.pause()
            self.state.status = CaptureStatus.PAUSED
    
    def resume_capture(self) -> None:
        """Resume capture after pause."""
        with self._lock:
            self.collector.resume()
            self.state.status = CaptureStatus.CAPTURING
    
    def get_state(self) -> DebuggerState:
        """Get current debugger state."""
        with self._lock:
            state = DebuggerState(
                status=self.state.status,
                total_events=self.timeline.size(),
                total_processes=len(self.timeline.get_all_processes()),
                total_resources=len(self.timeline.get_all_resources()),
                deadlocks_detected=len(self.analysis.lock_graph.detected_deadlocks),
                start_time_ns=self.state.start_time_ns,
                duration_ns=self.state.duration_ns,
            )
            return state
    
    def get_deadlocks(self) -> List[DeadlockCycle]:
        """Get detected deadlock cycles."""
        return self.analysis.get_deadlocks()
    
    def get_processes(self) -> List[int]:
        """Get list of all processes in trace."""
        return self.timeline.get_all_processes()
    
    def get_resources(self) -> List[str]:
        """Get list of all resources in trace."""
        return self.timeline.get_all_resources()
    
    def get_events_by_process(self, pid: int) -> List[IPCEvent]:
        """Get all events for a process."""
        return self.timeline.get_events_by_process(pid)
    
    def get_events_by_resource(self, resource_id: str) -> List[IPCEvent]:
        """Get all events for a resource."""
        return self.timeline.get_events_by_resource(resource_id)
    
    def get_events_for_process_pair(self, pid1: int, pid2: int) -> List[IPCEvent]:
        """Get events between two processes."""
        return self.timeline.get_process_pair_events(pid1, pid2)
    
    def get_flows(self) -> List[List[IPCEvent]]:
        """Get completed request-response flows."""
        return self.analysis.flow_stitcher.get_completed_flows()
    
    def get_flow_for_event(self, event_id: str) -> List[IPCEvent]:
        """Get the flow containing an event."""
        event = self.timeline.get_event_by_id(event_id)
        if not event:
            return []
        
        return self.timeline.get_request_response_flow(event_id)
    
    def get_causal_chain(self, event_id: str) -> List[IPCEvent]:
        """Get the causal chain for an event."""
        return self.timeline.get_causal_chain(event_id)
    
    def get_latency_stats(self) -> Dict[str, Any]:
        """Get latency statistics."""
        return self.analysis.latency_analyzer.get_statistics()
    
    def get_lock_holders(self) -> Dict[str, tuple]:
        """Get current lock owners."""
        return self.analysis.lock_graph.get_lock_holders()
    
    def get_lock_contention(self, lock_id: str) -> float:
        """Get contention ratio for a lock (0.0-1.0)."""
        return self.analysis.lock_graph.get_lock_contention(lock_id)
    
    def export_events(self, include_payloads: bool = False) -> List[Dict[str, Any]]:
        """Export all events as JSON-serializable dicts."""
        events = []
        for event in sorted(self.timeline._events, key=lambda e: e.timestamp_ns):
            d = event.to_dict()
            if not include_payloads:
                d['payload_preview'] = ''
            events.append(d)
        return events
    
    def export_flows(self) -> List[Dict[str, Any]]:
        """Export flows as JSON."""
        flows = []
        for flow in self.analysis.flow_stitcher.get_completed_flows():
            flow_dict = {
                'event_ids': [e.event_id for e in flow],
                'process_path': list({e.process_id for e in flow}),
                'start_time_ns': flow[0].timestamp_ns if flow else 0,
                'end_time_ns': flow[-1].timestamp_ns if flow else 0,
                'latency_ns': (flow[-1].timestamp_ns - flow[0].timestamp_ns) if flow else 0,
            }
            flows.append(flow_dict)
        return flows
    
    # === Advanced Feature Methods ===
    
    def add_breakpoint(self, bp: Breakpoint) -> str:
        """Add a debugging breakpoint."""
        return self.breakpoint_manager.add_breakpoint(bp)
    
    def remove_breakpoint(self, bp_id: str) -> bool:
        """Remove a breakpoint."""
        return self.breakpoint_manager.remove_breakpoint(bp_id)
    
    def get_breakpoints(self) -> Dict[str, Breakpoint]:
        """Get all breakpoints."""
        return dict(self.breakpoint_manager.breakpoints)
    
    def start_recording(self, recording_name: str) -> None:
        """Start recording for replay."""
        self.replay_engine.start_recording(recording_name)
    
    def stop_recording(self, recording_name: str) -> int:
        """Stop recording and return event count."""
        return self.replay_engine.stop_recording(recording_name)
    
    def start_replay(self, recording_name: str) -> bool:
        """Start replaying a recording."""
        return self.replay_engine.start_replay(recording_name)
    
    def replay_step_forward(self) -> Optional[IPCEvent]:
        """Step forward in replay."""
        return self.replay_engine.step_forward()
    
    def replay_step_backward(self) -> Optional[IPCEvent]:
        """Step backward in replay."""
        return self.replay_engine.step_backward()
    
    def get_anomalies(self) -> List:
        """Get detected anomalies."""
        return self.anomaly_detector.get_anomalies()
    
    def take_snapshot(self, label: str = "") -> Dict[str, Any]:
        """Take a snapshot of the timeline."""
        snap = self.snapshot_manager.take_snapshot(label)
        return {
            'id': snap.id,
            'created_at_ns': snap.created_at_ns,
            'event_count': snap.event_count,
            'process_count': snap.process_count,
            'resource_count': snap.resource_count,
            'label': snap.timestamp_label,
        }
    
    def export_trace(self, format: str = "json", options: Optional[ExportOptions] = None) -> str:
        """Export trace in specified format."""
        events = sorted(self.timeline._events, key=lambda e: e.timestamp_ns)
        return self.trace_exporter.export(events, format, options)
    
    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        state = self.to_dict()
        return IntegrationAPI.to_prometheus_metrics(state)
    
    def query_events(self, pattern: str) -> List[IPCEvent]:
        """Query events using pattern matching."""
        return self.query_api.query_by_pattern(pattern)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize entire debugger state."""
        state = self.get_state()
        return {
            'state': {
                'status': state.status.value,
                'total_events': state.total_events,
                'total_processes': state.total_processes,
                'total_resources': state.total_resources,
                'deadlocks_detected': state.deadlocks_detected,
                'duration_ns': state.duration_ns,
            },
            'processes': self.get_processes(),
            'resources': self.get_resources(),
            'deadlocks': [d.to_dict() for d in self.get_deadlocks()],
            'latency_stats': self.get_latency_stats(),
            'flows_summary': self.analysis.get_flow_summary(),
        }
    
    def _on_kernel_event(self, event: IPCEvent) -> None:
        """Callback for new kernel events."""
        self.analysis.on_event(event)
        
        # Check breakpoints
        self.breakpoint_manager.check_event(event)
        
        # Check for anomalies
        self.anomaly_detector.check_event(event)
    
    def _on_collector_status(self, status: CaptureStatus) -> None:
        """Callback for collector status changes."""
        with self._lock:
            self.state.status = status
    
    def _on_breakpoint_hit(self, bp: Breakpoint, event: IPCEvent) -> None:
        """Handle breakpoint hit."""
        # Log the hit
        print(f"[BREAKPOINT] {bp.type.value} triggered by event {event.event_id}")
        
        # Take snapshot if configured
        if bp.action.value == "snapshot":
            self.take_snapshot(f"bp_{bp.id}")
    
    def _on_anomaly_detected(self, anomaly) -> None:
        """Handle anomaly detection."""
        print(f"[ANOMALY] {anomaly.anomaly_type}: {anomaly.description}")
