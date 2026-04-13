"""
Export and Integration APIs for IPC Debugger

Supports:
- JSON trace export
- OpenTelemetry trace format
- Offline replay files
- gRPC service definition
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Any, Optional

from ipc_debugger.core.events import IPCEvent, DeadlockCycle


@dataclass
class ExportOptions:
    """Options for exporting traces."""
    
    include_payloads: bool = False
    include_process_names: bool = True
    include_correlation_ids: bool = True
    compress: bool = False
    start_time_ns: Optional[int] = None
    end_time_ns: Optional[int] = None


class TraceExporter:
    """Exports traces in various formats."""
    
    def __init__(self):
        self.exporters = {
            "json": self._export_json,
            "jsonl": self._export_jsonl,
            "otel": self._export_opentelemetry,
            "replay": self._export_replay,
            "csv": self._export_csv,
        }
    
    def export(
        self,
        events: List[IPCEvent],
        format: str = "json",
        options: Optional[ExportOptions] = None,
    ) -> str:
        """Export events in the specified format."""
        if format not in self.exporters:
            raise ValueError(f"Unknown export format: {format}")
        
        options = options or ExportOptions()
        return self.exporters[format](events, options)
    
    def _export_json(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> str:
        """Export as JSON array."""
        filtered = self._filter_events(events, options)
        data = {
            "export_format": "ipc-debugger-json",
            "version": "1.0",
            "exported_at_ns": int(time.time_ns()),
            "event_count": len(filtered),
            "events": [self._event_to_dict(e, options) for e in filtered],
        }
        return json.dumps(data, indent=2)
    
    def _export_jsonl(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> str:
        """Export as JSONL (one event per line)."""
        filtered = self._filter_events(events, options)
        lines = [json.dumps(self._event_to_dict(e, options)) for e in filtered]
        return "\n".join(lines)
    
    def _export_opentelemetry(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> str:
        """Export in OpenTelemetry trace format."""
        filtered = self._filter_events(events, options)
        
        # Build OTEL spans
        spans = []
        for event in filtered:
            span = {
                "traceId": event.correlation_id or "0" * 32,
                "spanId": event.event_id[:16],
                "parentSpanId": event.parent_event_id[:16] if event.parent_event_id else None,
                "name": f"{event.event_type.value}_{event.ipc_type.value}",
                "startTime": event.timestamp_ns,
                "endTime": event.timestamp_ns + (event.latency_ns or 0),
                "attributes": {
                    "process.id": event.process_id,
                    "thread.id": event.thread_id,
                    "ipc.type": event.ipc_type.value,
                    "ipc.event_type": event.event_type.value,
                    "ipc.resource_id": event.resource_id,
                    "ipc.result": event.result.value,
                    "ipc.latency_ns": event.latency_ns,
                },
            }
            if event.process_name:
                span["attributes"]["process.name"] = event.process_name
            if event.error_message:
                span["attributes"]["error.message"] = event.error_message
            
            spans.append(span)
        
        data = {
            "resourceSpans": [
                {
                    "spans": spans,
                }
            ]
        }
        return json.dumps(data, indent=2)
    
    def _export_replay(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> str:
        """Export as deterministic replay file."""
        filtered = self._filter_events(events, options)
        
        # Serialize for replay
        replay_data = {
            "format": "ipc-debugger-replay",
            "version": "1.0",
            "created_at_ns": int(time.time_ns()),
            "events": [self._event_to_dict(e, options) for e in filtered],
        }
        return json.dumps(replay_data, indent=2)
    
    def _export_csv(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> str:
        """Export as CSV."""
        filtered = self._filter_events(events, options)
        
        if not filtered:
            return "timestamp_ns,process_id,thread_id,ipc_type,event_type,resource_id,result,latency_ns\n"
        
        lines = [
            "timestamp_ns,process_id,thread_id,ipc_type,event_type,resource_id,result,latency_ns"
        ]
        
        for event in filtered:
            line = (
                f"{event.timestamp_ns},"
                f"{event.process_id},"
                f"{event.thread_id},"
                f"{event.ipc_type.value},"
                f"{event.event_type.value},"
                f"{event.resource_id},"
                f"{event.result.value},"
                f"{event.latency_ns}"
            )
            lines.append(line)
        
        return "\n".join(lines)
    
    def _filter_events(
        self,
        events: List[IPCEvent],
        options: ExportOptions,
    ) -> List[IPCEvent]:
        """Filter events based on export options."""
        filtered = events
        
        if options.start_time_ns:
            filtered = [e for e in filtered if e.timestamp_ns >= options.start_time_ns]
        
        if options.end_time_ns:
            filtered = [e for e in filtered if e.timestamp_ns <= options.end_time_ns]
        
        return filtered
    
    def _event_to_dict(self, event: IPCEvent, options: ExportOptions) -> Dict[str, Any]:
        """Convert event to dictionary for export."""
        d = event.to_dict()
        
        if not options.include_payloads:
            d["payload_preview"] = ""
        
        if not options.include_process_names:
            d["process_name"] = ""
            d["thread_name"] = ""
        
        if not options.include_correlation_ids:
            d["correlation_id"] = ""
        
        return d


class IntegrationAPI:
    """API for integrating with external systems."""
    
    @staticmethod
    def to_prometheus_metrics(state: Dict[str, Any]) -> str:
        """Convert debugger state to Prometheus metrics format."""
        lines = []
        
        # Gauge metrics
        lines.append(
            f'ipc_debugger_total_events{{}} {state.get("state", {}).get("total_events", 0)}'
        )
        lines.append(
            f'ipc_debugger_deadlocks_detected{{}} {state.get("state", {}).get("deadlocks_detected", 0)}'
        )
        lines.append(
            f'ipc_debugger_processes{{}} {state.get("state", {}).get("total_processes", 0)}'
        )
        lines.append(
            f'ipc_debugger_resources{{}} {state.get("state", {}).get("total_resources", 0)}'
        )
        
        # Latency metrics
        latency = state.get("latency_stats", {})
        if latency:
            lines.append(f'ipc_debugger_latency_p50_ns{{}} {latency.get("p50", 0)}')
            lines.append(f'ipc_debugger_latency_p99_ns{{}} {latency.get("p99", 0)}')
            lines.append(f'ipc_debugger_latency_max_ns{{}} {latency.get("max", 0)}')
        
        return "\n".join(lines)
    
    @staticmethod
    def to_datadog_events(events: List[IPCEvent]) -> List[Dict[str, Any]]:
        """Convert events to Datadog event format."""
        datadog_events = []
        
        for event in events:
            dd_event = {
                "timestamp": int(event.timestamp_ns / 1_000_000_000),  # seconds
                "text": f"IPC Event: {event.event_type.value} on {event.ipc_type.value}",
                "priority": "normal" if event.latency_ns < 50_000_000 else "high",
                "tags": [
                    f"pid:{event.process_id}",
                    f"ipc_type:{event.ipc_type.value}",
                    f"event_type:{event.event_type.value}",
                    f"resource:{event.resource_id}",
                ],
            }
            
            if event.error_code:
                dd_event["alert_type"] = "error"
            
            datadog_events.append(dd_event)
        
        return datadog_events
    
    @staticmethod
    def to_splunk_hec(events: List[IPCEvent]) -> str:
        """Convert events to Splunk HEC format."""
        lines = []
        
        for event in events:
            hec_event = {
                "time": event.timestamp_ns / 1_000_000_000,  # seconds
                "source": "ipc_debugger",
                "sourcetype": f"ipc_{event.ipc_type.value}",
                "event": {
                    "event_id": event.event_id,
                    "timestamp_ns": event.timestamp_ns,
                    "process_id": event.process_id,
                    "thread_id": event.thread_id,
                    "ipc_type": event.ipc_type.value,
                    "event_type": event.event_type.value,
                    "resource_id": event.resource_id,
                    "latency_ns": event.latency_ns,
                    "result": event.result.value,
                },
            }
            lines.append(json.dumps(hec_event))
        
        return "\n".join(lines)


class QueryAPI:
    """Advanced query API for debugger traces."""
    
    def __init__(self, debugger):
        self.debugger = debugger
    
    def query_by_pattern(self, pattern: str) -> List[IPCEvent]:
        """Query events matching a pattern."""
        # Simple pattern matching for now
        # Pattern examples:
        # - "pid:1234 -> pid:5678"
        # - "resource:pipe_1 SEND"
        # - "latency > 50000000"
        
        events = self.debugger.timeline._events
        
        if "->" in pattern:
            parts = pattern.split("->")
            if len(parts) == 2:
                parts = [p.strip() for p in parts]
                if parts[0].startswith("pid:") and parts[1].startswith("pid:"):
                    pid1 = int(parts[0][4:])
                    pid2 = int(parts[1][4:])
                    return self.debugger.get_events_for_process_pair(pid1, pid2)
        
        if "resource:" in pattern:
            resource_id = pattern.replace("resource:", "").split()[0]
            return self.debugger.get_events_by_resource(resource_id)
        
        if "latency >" in pattern:
            threshold_ns = int(pattern.replace("latency >", "").strip())
            return [e for e in events if e.latency_ns > threshold_ns]
        
        return []
    
    def correlate_with_logs(self, log_timestamp_ms: int) -> List[IPCEvent]:
        """Find IPC events near a log timestamp."""
        # Convert ms to ns
        target_ns = log_timestamp_ms * 1_000_000
        
        # Find events within 1 second (1 billion ns) of the timestamp
        window = 1_000_000_000
        
        events = self.debugger.timeline._events
        return [
            e for e in events
            if abs(e.timestamp_ns - target_ns) <= window
        ]
