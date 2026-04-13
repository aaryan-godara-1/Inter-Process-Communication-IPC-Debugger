"""Simple backend web server for the IPC Debugger frontend.

Serves the static frontend and exposes JSON APIs to run scenarios and fetch
live simulation summaries.
"""

from __future__ import annotations

import json
import argparse
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ipc_debugger.service import IPCService
from ipc_debugger.utils.constants import Scenario


SCENARIO_ALIASES = {
    "normal": Scenario.NORMAL_FLOW,
    "normal-flow": Scenario.NORMAL_FLOW,
    "deadlock": Scenario.DEADLOCK,
    "bottleneck": Scenario.BOTTLENECK,
}


def _parse_scenario(value: str) -> Scenario:
    key = value.strip().lower()
    if key not in SCENARIO_ALIASES:
        options = ", ".join(sorted(SCENARIO_ALIASES))
        raise ValueError(f"Unknown scenario '{value}'. Choose one of: {options}.")
    return SCENARIO_ALIASES[key]


def _serialize_log_event(event) -> dict[str, Any]:
    return {
        "ts": event.ts,
        "ts_str": event.ts_str,
        "event_type": event.event_type,
        "channel_id": event.channel_id,
        "pid": event.pid,
        "data": event.data,
    }


@dataclass
class ServerState:
    service: IPCService
    lock: threading.Lock
    report: dict[str, Any]


class IPCWebHandler(BaseHTTPRequestHandler):
    state: ServerState
    frontend_dir: Path

    def log_message(self, format: str, *args) -> None:
        # Keep terminal output concise and predictable.
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if path == "/api/report":
            with self.state.lock:
                payload = dict(self.state.report)
            self._write_json(HTTPStatus.OK, payload)
            return

        if path == "/api/scenarios":
            self._write_json(
                HTTPStatus.OK,
                {
                    "scenarios": [
                        {"key": "normal-flow", "label": "Normal Flow"},
                        {"key": "deadlock", "label": "Deadlock"},
                        {"key": "bottleneck", "label": "Bottleneck"},
                    ]
                },
            )
            return

        # Static frontend
        if path == "/":
            self._serve_file(self.frontend_dir / "index.html", "text/html; charset=utf-8")
            return

        if path == "/app.js":
            self._serve_file(self.frontend_dir / "app.js", "application/javascript; charset=utf-8")
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_len) if content_len else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            return

        scenario_raw = str(payload.get("scenario", "normal-flow"))
        delay_ms = int(payload.get("delay_ms", 20))
        timeout = float(payload.get("timeout", 10.0))

        try:
            scenario = _parse_scenario(scenario_raw)
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        with self.state.lock:
            report = self.state.service.run_scenario(scenario, delay_ms=delay_ms, timeout=timeout)
            logs = [
                _serialize_log_event(evt)
                for evt in self.state.service.logger.get_events(last_n=80)
            ]
            processes = [
                {
                    "pid": proc.pid,
                    "name": proc.name,
                    "state": proc.state.name,
                    "waiting_on": proc.waiting_on,
                }
                for proc in self.state.service.get_processes()
            ]
            response_payload = report.to_dict()
            response_payload["logs"] = logs
            response_payload["process_details"] = processes
            self.state.report = response_payload

        self._write_json(HTTPStatus.OK, response_payload)

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
            return

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    if not sys.platform.startswith("win"):
        raise OSError("ipc_debugger.web_server is Windows-only")

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"

    if not (frontend_dir / "index.html").exists():
        raise FileNotFoundError(
            f"Expected frontend/index.html to exist at: {frontend_dir / 'index.html'}"
        )

    service = IPCService()
    initial = service.run_scenario(Scenario.NORMAL_FLOW, delay_ms=20, timeout=10.0).to_dict()
    initial["logs"] = [_serialize_log_event(evt) for evt in service.logger.get_events(last_n=80)]
    initial["process_details"] = [
        {
            "pid": proc.pid,
            "name": proc.name,
            "state": proc.state.name,
            "waiting_on": proc.waiting_on,
        }
        for proc in service.get_processes()
    ]

    state = ServerState(service=service, lock=threading.Lock(), report=initial)

    IPCWebHandler.state = state
    IPCWebHandler.frontend_dir = frontend_dir

    server = ThreadingHTTPServer((host, port), IPCWebHandler)
    print(f"IPC Debugger Web UI running at http://{host}:{port}")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run IPC Debugger web server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8010, help="Bind port")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
