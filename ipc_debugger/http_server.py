"""
HTTP server for the IPC Debugger.

Exposes the debugger functionality via REST API and WebSocket.
Can be used standalone or integrated with Node.js via HTTP proxying.
"""

from __future__ import annotations

import json
import sys
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from typing import Optional

from ipc_debugger.debugger import IPCDebugger
from ipc_debugger.core.collector import CaptureConfig, CaptureMode
from ipc_debugger.core.events import IPCType


def create_app(debugger: Optional[IPCDebugger] = None) -> Flask:
    """Create Flask application for the debugger."""
    
    app = Flask(__name__)
    CORS(app)
    
    # Use provided debugger or create new one
    if debugger is None:
        debugger = IPCDebugger(use_real_collector=True)
    
    app.locals = {"debugger": debugger}
    
    # === Status & Control Endpoints ===
    
    @app.route("/api/debugger/status", methods=["GET"])
    def get_status():
        """Get debugger status."""
        try:
            state = app.locals["debugger"].get_state()
            return jsonify({
                "status": state.status.value,
                "total_events": state.total_events,
                "total_processes": state.total_processes,
                "total_resources": state.total_resources,
                "deadlocks_detected": state.deadlocks_detected,
                "duration_ms": state.duration_ns // 1000000,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/start", methods=["POST"])
    def start_capture():
        """Start capturing events."""
        try:
            data = request.get_json() or {}
            
            # Parse capture config from JSON
            ipc_types = data.get("ipc_types")
            if ipc_types:
                ipc_types = [IPCType(t) for t in ipc_types]
            
            config = CaptureConfig(
                ipc_types=ipc_types or list(IPCType),
                sample_rate=data.get("sample_rate", 1.0),
                capture_payloads=data.get("capture_payloads", False),
                payload_max_size=data.get("payload_max_size", 256),
                mask_sensitive=data.get("mask_sensitive", True),
            )
            
            app.locals["debugger"].start_capture(config)
            return jsonify({"message": "Capture started"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/stop", methods=["POST"])
    def stop_capture():
        """Stop capturing events."""
        try:
            app.locals["debugger"].stop_capture()
            return jsonify({"message": "Capture stopped"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/pause", methods=["POST"])
    def pause_capture():
        """Pause capture."""
        try:
            app.locals["debugger"].pause_capture()
            return jsonify({"message": "Capture paused"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/resume", methods=["POST"])
    def resume_capture():
        """Resume capture."""
        try:
            app.locals["debugger"].resume_capture()
            return jsonify({"message": "Capture resumed"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # === Query Endpoints ===
    
    @app.route("/api/debugger/processes", methods=["GET"])
    def get_processes():
        """Get all processes."""
        try:
            processes = app.locals["debugger"].get_processes()
            return jsonify({"processes": processes})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/resources", methods=["GET"])
    def get_resources():
        """Get all resources."""
        try:
            resources = app.locals["debugger"].get_resources()
            return jsonify({"resources": resources})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/events", methods=["GET"])
    def get_events():
        """Get events with filtering."""
        try:
            pid = request.args.get("process_id", type=int)
            resource_id = request.args.get("resource_id")
            limit = request.args.get("limit", 1000, type=int)
            
            if pid:
                events = app.locals["debugger"].get_events_by_process(pid)
            elif resource_id:
                events = app.locals["debugger"].get_events_by_resource(resource_id)
            else:
                events = app.locals["debugger"].timeline.get_latest_n(limit)
            
            return jsonify({
                "events": [e.to_dict() for e in events],
                "count": len(events),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/deadlocks", methods=["GET"])
    def get_deadlocks():
        """Get detected deadlocks."""
        try:
            deadlocks = app.locals["debugger"].get_deadlocks()
            return jsonify({
                "deadlocks": [d.to_dict() for d in deadlocks],
                "count": len(deadlocks),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/flows", methods=["GET"])
    def get_flows():
        """Get request-response flows."""
        try:
            flows = app.locals["debugger"].get_flows()
            flow_data = [
                {
                    "event_count": len(flow),
                    "start_time_ns": flow[0].timestamp_ns if flow else 0,
                    "end_time_ns": flow[-1].timestamp_ns if flow else 0,
                    "latency_ns": (flow[-1].timestamp_ns - flow[0].timestamp_ns) if flow else 0,
                    "event_ids": [e.event_id for e in flow],
                }
                for flow in flows
            ]
            return jsonify({
                "flows": flow_data,
                "count": len(flow_data),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/latency-stats", methods=["GET"])
    def get_latency_stats():
        """Get latency statistics."""
        try:
            stats = app.locals["debugger"].get_latency_stats()
            return jsonify(stats)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/process-pair/<int:pid1>/<int:pid2>", methods=["GET"])
    def get_process_pair(pid1: int, pid2: int):
        """Get events between two processes."""
        try:
            events = app.locals["debugger"].get_events_for_process_pair(pid1, pid2)
            return jsonify({
                "events": [e.to_dict() for e in events],
                "count": len(events),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/event/<event_id>", methods=["GET"])
    def get_event(event_id: str):
        """Get event and its causal chain."""
        try:
            event = app.locals["debugger"].timeline.get_event_by_id(event_id)
            if not event:
                return jsonify({"error": "Event not found"}), 404
            
            chain = app.locals["debugger"].get_causal_chain(event_id)
            return jsonify({
                "event": event.to_dict(),
                "causal_chain": [e.to_dict() for e in chain],
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/export", methods=["GET"])
    def export_events():
        """Export all events."""
        try:
            include_payloads = request.args.get("include_payloads", "false").lower() == "true"
            events = app.locals["debugger"].export_events(include_payloads)
            return jsonify({
                "event_count": len(events),
                "events": events,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/debugger/summary", methods=["GET"])
    def get_summary():
        """Get complete summary."""
        try:
            summary = app.locals["debugger"].to_dict()
            return jsonify(summary)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return app


def run_server(port: int = 8010, debug: bool = False):
    """Run the HTTP server."""
    if not sys.platform.startswith("win"):
        raise OSError("ipc_debugger.http_server is Windows-only")

    debugger = IPCDebugger(use_real_collector=True)
    app = create_app(debugger)
    
    print(f"Starting IPC Debugger HTTP server on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    run_server(args.port, args.debug)
