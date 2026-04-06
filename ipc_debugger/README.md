# IPC Debugger Backend

This package contains the backend implementation of the IPC Debugger project. The frontend has been removed, so the repository now focuses on simulation, logging, analysis, and reporting.

## Architecture

The backend is organized into the following modules:

* `core/` - thread-safe IPC primitives and simulated processes
* `simulation/` - scheduler and event bus
* `debugger/` - event logger, deadlock detector, race-condition detector
* `analytics/` - latency, throughput, and system-performance tracking
* `system_monitor/` - optional psutil-backed live monitoring layer
* `utils/` - shared enums, constants, and helpers

## Usage

Run a simulation scenario from the command line:

```bash
python -m ipc_debugger.main --scenario normal-flow
python -m ipc_debugger.main --scenario deadlock
python -m ipc_debugger.main --scenario bottleneck --json
```

Run the connected web frontend:

```bash
python -m ipc_debugger.web_server --port 8010
```

Open the UI at `http://127.0.0.1:8010`.

The backend prints a structured summary with process states, throughput, latency, bottlenecks, and deadlock cycles.

## Testing

```bash
python -m pytest ipc_debugger/tests -q
```

## Scenarios

The scheduler currently provides three built-in simulation scenarios:

1. `Normal Flow` - producer to consumer chain across pipe, queue, and shared memory.
2. `Deadlock` - circular wait between blocked processes.
3. `Bottleneck` - fast producers overwhelming a slow consumer.
