# IPC Debugger

Backend-only Inter-Process Communication debugging and analysis tool.

Windows-only build. Run on Windows hosts.

Kernel capture mode now defaults to real Windows ETW collection.

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

Run real IPC debugger API (ETW capture):

```bash
python -m ipc_debugger.http_server --port 8010
```

Use an elevated terminal (Run as Administrator) for ETW session startup.

Then open:

```text
http://127.0.0.1:8010
```

## Tests

```bash
python -m pytest ipc_debugger/tests -q
```

## Branch Workflow Note

For incremental work on branch `sahaj`, prefer small commits and push each commit after validation so deployment and review stay traceable.