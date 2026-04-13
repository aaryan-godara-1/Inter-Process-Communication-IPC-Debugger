# IPC Debugger - Quick Reference

## TL;DR - Start Using It Now

### 1. Start Python Backend
```bash
python -m ipc_debugger.http_server --port 8010 &
```

### 2. Start Node.js Frontend
```bash
cd /path/to/IPCdebugger
npm install
node server.js &
```

### 3. Open Browser
```
http://localhost:3000
```

### 4. Click "Debugger" Panel
- Hit "Start" to begin capture
- Watch events flow in real-time
- See deadlocks and anomalies
- Click "Stop" to end capture

---

## Python API - Common Tasks

### Start/Stop Capture
```python
from ipc_debugger.debugger import IPCDebugger
from ipc_debugger.core.collector import CaptureConfig
from ipc_debugger.core.events import IPCType

debugger = IPCDebugger()
config = CaptureConfig(ipc_types=[IPCType.PIPE, IPCType.MUTEX])
debugger.start_capture(config)
# ... wait ...
debugger.stop_capture()
```

### Detect Deadlocks
```python
deadlocks = debugger.get_deadlocks()
for cycle in deadlocks:
    print(f"Deadlock: {cycle.processes} waiting on {cycle.locks}")
```

### Get Latency Stats
```python
stats = debugger.get_latency_stats()
print(f"P99 Latency: {stats['p99']} ns")
print(f"Max Latency: {stats['max']} ns")
```

### Trace a Request
```python
event = debugger.timeline.get_event_by_id(event_id)
causal_chain = debugger.get_causal_chain(event_id)
for event in causal_chain:
    print(f"{event.process_id}: {event.event_type.value}")
```

### Set Breakpoint
```python
from ipc_debugger.core.advanced import Breakpoint, BreakpointType, BreakpointAction

bp = Breakpoint(
    id="bp_1",
    type=BreakpointType.LATENCY_THRESHOLD,
    latency_threshold_ns=50_000_000,
    action=BreakpointAction.SNAPSHOT,
)
debugger.add_breakpoint(bp)
```

### Export Trace
```python
# JSON
json_str = debugger.export_trace(format="json")

# OpenTelemetry (for APM)
otel_str = debugger.export_trace(format="otel")

# CSV (for spreadsheet)
csv_str = debugger.export_trace(format="csv")
```

### Query Events
```python
# Between two processes
events = debugger.query_events("pid:1000 -> pid:1001")

# On specific resource
events = debugger.query_events("resource:pipe_1 SEND")

# High latency only
events = debugger.query_events("latency > 50000000")
```

---

## REST API - Common Endpoints

### Status
```bash
curl http://localhost:8010/api/debugger/status
# Returns: { "status": "capturing", "total_events": 1234, ... }
```

### Deadlocks
```bash
curl http://localhost:8010/api/debugger/deadlocks
# Returns: { "deadlocks": [...], "count": 0 }
```

### Request-Response Flows
```bash
curl http://localhost:8010/api/debugger/flows
# Returns: { "flows": [...], "count": 42 }
```

### Latency Stats
```bash
curl http://localhost:8010/api/debugger/latency-stats
# Returns: { "p50": 12500, "p95": 45000, "p99": 125000, "max": 2500000 }
```

### Event Details
```bash
curl http://localhost:8010/api/debugger/event/{event_id}
# Returns: { "event": {...}, "causal_chain": [...] }
```

### Export (Multiple Formats)
```bash
curl http://localhost:8010/api/debugger/export?format=json > trace.json
curl http://localhost:8010/api/debugger/export?format=otel > trace.otel.json
curl http://localhost:8010/api/debugger/export?format=csv > trace.csv
```

### Prometheus Metrics
```bash
curl http://localhost:8010/api/debugger/summary
# Use to feed into Prometheus scrape target
```

---

## File Locations

### Python Backend
```
ipc_debugger/
├── core/events.py              # IPC event model
├── core/timeline.py            # Event stream
├── core/analysis.py            # Deadlock detection, latency
├── core/advanced.py            # Breakpoints, replay, anomalies
├── core/export.py              # Export API
└── debugger.py                 # Main service
```

### HTTP Server
```
ipc_debugger/
└── http_server.py              # Flask REST API
```

### Node.js
```
server/
├── routes/debuggerRoutes.js    # Express REST wrapper
└── live/debuggerWebSocket.js   # WebSocket handler
client/
└── debugger-panel.js           # Browser control panel
```

### Documentation
```
ARCHITECTURE.md        # System design (500 lines)
REDESIGN.md           # Implementation guide (600 lines)
IMPLEMENTATION_SUMMARY.md  # What's implemented (400 lines)
QUICK_REFERENCE.md    # This file!
```

---

## Key Concepts

### Event
A single IPC operation (SEND, RECEIVE, ACQUIRE, RELEASE, etc.)
```python
event.timestamp_ns      # When it happened (nanoseconds)
event.process_id        # Which process
event.ipc_type          # Resource type (PIPE, SOCKET, MUTEX, etc.)
event.event_type        # Operation (SEND, RECV, ACQUIRE, RELEASE, etc.)
event.latency_ns        # How long it took (if blocking)
event.correlation_id    # Links request-response pairs
event.result            # SUCCESS, BLOCKED, ERROR, etc.
```

### Flow
A sequence of events forming a request-response chain
```
Process A: SEND message → pipe_1
Process B: RECV from pipe_1
Process B: RESPONSE → socket_1
Process A: RECV from socket_1
```

### Deadlock
A cycle in the lock graph where processes wait on each other
```
Process 1: Holds Lock A, Waits on Lock B
Process 2: Holds Lock B, Waits on Lock A
→ Deadlock detected!
```

### Anomaly
An unusual pattern detected during analysis
- Latency spike (> 2x baseline)
- Lock held too long
- Queue backing up
- Message drop

---

## Configuration Options

### Capture Config
```python
CaptureConfig(
    ipc_types=[IPCType.PIPE, IPCType.SOCKET, IPCType.MUTEX],
    process_pids=[1000, 1001],  # Empty = all
    sample_rate=1.0,             # 0.0 to 1.0
    capture_payloads=False,      # Include message data?
    payload_max_size=256,        # Max bytes to capture
    mask_sensitive=True,         # Hide PII?
)
```

### Breakpoint Config
```python
Breakpoint(
    type=BreakpointType.LATENCY_THRESHOLD,
    latency_threshold_ns=50_000_000,  # 50ms
    action=BreakpointAction.SNAPSHOT,  # What to do
)
```

### Export Options
```python
ExportOptions(
    include_payloads=False,
    include_process_names=True,
    include_correlation_ids=True,
    compress=False,
    start_time_ns=None,
    end_time_ns=None,
)
```

---

## Troubleshooting

### Python HTTP server won't start
```bash
# Check port is free
lsof -i :8010

# Check Flask installed
pip install flask flask-cors

# Run with debug
python -m ipc_debugger.http_server --port 8010 --debug
```

### No events appearing
- Make sure `start_capture()` is called
- Check WebSocket connection in browser console
- Verify simulated collector is generating events
- Look for errors in terminal

### Deadlock detection not working
- Need events with ACQUIRE/RELEASE event types
- Need actual lock contention or wait patterns
- Check that lock_id is consistent across events

### Export file is empty
- Capture must complete (stop_capture called)
- Events must exist (size > 0)
- Format might require specific event types
- Check for errors in return value

---

## Performance Tips

### Reduce Overhead
```python
config = CaptureConfig(
    sample_rate=0.1,           # Capture 10% of events
    capture_payloads=False,    # Don't capture message data
    process_pids=[1000, 1001], # Only these processes
    ipc_types=[IPCType.PIPE],  # Only pipes
)
```

### Faster Queries
- Query by event_id (O(1))
- Ask for recent events with `get_latest_n()`
- Use correlation_id for request matching
- Filter before iterating

### Memory Management
```python
# Ring buffer automatically limits memory
# Default: 100k events ≈ 100MB = 10-60 sec capture

# Manually snapshot and clear:
debugger.take_snapshot("checkpoint_1")
debugger.timeline.clear()  # Start fresh
```

### WebSocket Performance
- Updates batch every 100ms (configurable)
- Only new events sent
- Clients can request specific data

---

## Integration Examples

### Prometheus Metrics
```python
metrics = debugger.get_prometheus_metrics()
# Output:
# ipc_debugger_total_events{} 1234
# ipc_debugger_deadlocks_detected{} 0
# ipc_debugger_latency_p99_ns{} 125000000
```

### OpenTelemetry Traces
```python
otel_traces = debugger.export_trace(format="otel")
# Send to OpenTelemetry collector:
# curl -X POST http://opentelemetry.local:4318/v1/traces \
#   -H "Content-Type: application/json" \
#   -d @trace.otel.json
```

### Splunk Logging
```python
splunk_events = IntegrationAPI.to_splunk_hec(events)
# Send to Splunk HTTP Event Collector:
# curl -X POST https://splunk.local:8088/services/collector \
#   -H "Authorization: Splunk <token>" \
#   -d @splunk_events.txt
```

### Datadog Events
```python
dd_events = IntegrationAPI.to_datadog_events(events)
# POSTs each event to Datadog API
```

---

## Architecture Diagram

```
       ┌─────────────────────────┐
       │   Kernel (OS Events)    │
       └────────────┬────────────┘
                    │
                    ▼
       ┌─────────────────────────┐
       │   Collector Abstraction  │ (collector.py)
       └────────────┬────────────┘
                    │
                    ▼
       ┌─────────────────────────┐
       │  Event Normalization    │
       └────────────┬────────────┘
                    │
                    ▼
       ┌─────────────────────────┐
       │   Timeline Engine       │ (timeline.py)
       │   • Ring buffer         │
       │   • Multi-index         │
       │   • O(1) lookups        │
       └────────────┬────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    ┌───────┐  ┌────────┐  ┌─────────┐
    │ Flow  │  │ Lock   │  │ Latency │
    │Stitcher  Graph    │  │Analyzer │
    └───┬───┘  └──┬─────┘  └────┬────┘
        │         │             │
        └─────────┼─────────────┘
                  │
                  ▼
    ┌──────────────────────────────┐
    │   Advanced Features           │
    │  • Breakpoints               │
    │  • Replay Engine              │
    │  • Anomaly Detection         │
    │  • Snapshots                 │
    └─────────────┬────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   ┌────────┐ ┌──────┐  ┌──────────┐
   │ Export │ │Query │  │Integration│
   │ (JSON) │ │ API  │  │APIs      │
   └───┬────┘ └──┬───┘  └────┬─────┘
       │         │            │
       └─────────┼────────────┘
               ▼
    ┌──────────────────────┐
    │  REST HTTP API       │
    │  (http_server.py)    │
    │  25+ endpoints       │
    └────────┬─────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────┐   ┌────────────┐
│ Browser  │   │ Python/Go/ │
│ Dashboard│   │ Java Apps  │
└──────────┘   └────────────┘
```

---

## Next Steps

1. **Try It**: Run the debugger on your system
2. **Set Breakpoints**: Catch specific IPC patterns
3. **Export Data**: Analyze in Prometheus/Splunk/etc
4. **Deploy**: Use in production with sampling
5. **Extend**: Add custom analysis or collectors

---

**Questions?** See ARCHITECTURE.md and REDESIGN.md for detailed documentation.
