# Analytics Engine — Member 2

This module is the analysis layer of the IPC Debugger.
It sits between the IPC Monitor (Member 1) and the GUI (Member 3).

---

## How It Works
---

## Files

### `analysis_engine.py`
Central engine. Subscribes to IPCLogger and coordinates
all detectors in real time. Start here.

### `gui_output_formatter.py` ← Member 3 start here
Single point of contact for the GUI. Call `get_full_report()`
to get all analysis data in one clean structured dict.

### `deadlock_analyzer.py`
Enhanced deadlock detection via wait-for graph and DFS
cycle detection. Adds severity levels, history, timestamps
and saves detections to `deadlock_log.txt`.

### `latency.py`
Tracks send → receive latency per channel. Detects spikes,
tracks min/max, generates GUI summary.

### `alerts.py`
Alert management with severity levels (INFO/WARNING/CRITICAL)
and cooldown to prevent spam.

### `stats_reporter.py`
Generates performance reports — busiest channel, slowest
channel, system health score (HEALTHY/DEGRADED/CRITICAL).

### `anomaly_detector.py`
Builds baseline of normal behavior and flags deviations.
Smarter than simple threshold detection.

### `event_correlator.py`
Groups related IPC events into cause-effect chains per channel.
Helps trace root cause of issues.

### `ipc_logger_writer.py`
Writes all IPC events to disk permanently. Adds persistence
that the in-memory logger lacks — events survive crashes.

---

## For Member 3 — How To Use

### Step 1 — Import

```python
from analytics.gui_output_formatter import GUIOutputFormatter
from analytics.deadlock_analyzer import DeadlockAnalyzer
from analytics.latency import LatencyTracker
from analytics.throughput import ThroughputTracker
from analytics.alerts import AlertManager
from analytics.anomaly_detector import AnomalyDetector
from analytics.event_correlator import EventCorrelator
```

### Step 2 — Setup

```python
formatter = GUIOutputFormatter(
    deadlock_analyzer=DeadlockAnalyzer(),
    latency_tracker=LatencyTracker(),
    throughput_tracker=ThroughputTracker(),
    alert_manager=AlertManager(),
    anomaly_detector=AnomalyDetector(),
    event_correlator=EventCorrelator()
)
```

### Step 3 — Get Everything In One Call

```python
report = formatter.get_full_report()
```

### Step 4 — Use The Data

```python
# Status banner color
color = report["status"]["color"]      # GREEN / YELLOW / RED

# Deadlock info
has_deadlock = report["deadlock"]["has_deadlock"]
cycles = report["deadlock"]["cycles"]  # ["101 → 102 → 101"]

# Latency spikes
spikes = report["latency"]["spikes"]

# Bottlenecks
bottlenecks = report["throughput"]["bottlenecks"]

# Latest alerts
alerts = report["alerts"]

# Anomalies
anomalies = report["anomalies"]
```

---

## Output Structure

```json
{
    "timestamp": 1234567890.0,
    "timestamp_str": "2026-04-11 18:45:23",
    "status": {
        "color": "GREEN",
        "status": "HEALTHY",
        "message": "All systems normal"
    },
    "deadlock": {
        "has_deadlock": false,
        "severity": "OK",
        "cycle_count": 0,
        "cycles": [],
        "processes_involved": []
    },
    "latency": {
        "spikes": [],
        "averages": {"pipe_1": 12.3}
    },
    "throughput": {
        "bottlenecks": [],
        "throughputs": {"pipe_1": 45.2}
    },
    "alerts": [],
    "anomalies": [],
    "chains": []
}
```

---

## Deadlock Log File

Every deadlock detected is saved to `deadlock_log.txt`: