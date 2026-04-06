# IPC Debugger

Backend-only Inter-Process Communication debugging and analysis tool.

The project simulates IPC channels, logs communication events, detects deadlocks and race conditions, and reports throughput and latency metrics without any GUI layer.

## Run

```bash
python -m ipc_debugger.main --scenario normal-flow
python -m ipc_debugger.main --scenario deadlock --json
```

## Web UI

Run the backend API + frontend UI server:

```bash
python -m ipc_debugger.web_server --port 8010
```

Then open:

```text
http://127.0.0.1:8010
```

## Tests

```bash
python -m pytest ipc_debugger/tests -q
```