/**
 * IPC Debugger WebSocket Handler
 *
 * Provides real-time updates of:
 * - New IPC events
 * - Deadlock detection
 * - Anomalies and alerts
 * - Process/resource updates
 */

const WebSocket = require("ws");

class DebuggerWebSocketServer {
  constructor(server, debugger_service) {
    this.debugger_service = debugger_service;
    this.wss = new WebSocket.Server({ server });
    this.clients = new Set();

    // Setup event listeners
    this.setupListeners();

    this.wss.on("connection", (ws) => {
      console.log("[WS] New debugger client connected");
      this.clients.add(ws);

      // Send initial state
      this.sendToClient(ws, "init", {
        status: this.debugger_service.state?.status || "idle",
        processes: this.debugger_service.get_processes?.() || [],
        resources: this.debugger_service.get_resources?.() || [],
      });

      ws.on("message", (data) => this.handleMessage(ws, data));
      ws.on("close", () => {
        this.clients.delete(ws);
        console.log("[WS] Debugger client disconnected");
      });
      ws.on("error", (err) => {
        console.error("[WS] Debugger WebSocket error:", err);
      });
    });
  }

  /**
   * Setup listeners for debugger events
   */
  setupListeners() {
    // Listen for new events from the collector
    if (this.debugger_service.collector) {
      this.debugger_service.collector.registerEventCallback((event) => {
        this.broadcast("event", {
          event_id: event.event_id,
          timestamp_ns: event.timestamp_ns,
          process_id: event.process_id,
          ipc_type: event.ipc_type,
          event_type: event.event_type,
          resource_id: event.resource_id,
          latency_ns: event.latency_ns,
        });
      });
    }

    // Listen for status changes
    if (this.debugger_service.collector) {
      this.debugger_service.collector.registerStatusCallback((status) => {
        this.broadcast("status", { collector_status: status });
      });
    }
  }

  /**
   * Send message to a single client
   */
  sendToClient(ws, type, data) {
    if (ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type, data, timestamp_ns: Date.now() * 1000000 }));
      } catch (err) {
        console.error("[WS] Error sending to client:", err);
      }
    }
  }

  /**
   * Broadcast message to all clients
   */
  broadcast(type, data) {
    const message = JSON.stringify({
      type,
      data,
      timestamp_ns: Date.now() * 1000000,
    });

    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        try {
          client.send(message);
        } catch (err) {
          console.error("[WS] Error broadcasting:", err);
        }
      }
    }
  }

  /**
   * Handle incoming WebSocket messages
   */
  handleMessage(ws, raw_data) {
    try {
      const msg = JSON.parse(raw_data);
      const { type, data } = msg;

      switch (type) {
        case "query_deadlocks":
          this.sendToClient(ws, "deadlocks", {
            deadlocks: this.debugger_service.get_deadlocks?.() || [],
          });
          break;

        case "query_flows":
          this.sendToClient(ws, "flows", {
            flows: this.debugger_service.get_flows?.() || [],
          });
          break;

        case "query_event":
          if (data.event_id) {
            const event = this.debugger_service.timeline?.get_event_by_id(
              data.event_id
            );
            if (event) {
              const chain =
                this.debugger_service.get_causal_chain?.(data.event_id) || [];
              this.sendToClient(ws, "event_detail", {
                event: event.to_dict?.() || event,
                chain: chain.map((e) => e.to_dict ? e.to_dict() : e),
              });
            }
          }
          break;

        case "query_process":
          if (data.pid) {
            const events =
              this.debugger_service.get_events_by_process?.(data.pid) || [];
            this.sendToClient(ws, "process_events", {
              pid: data.pid,
              events: events.slice(-100).map((e) => e.to_dict?.() || e),
            });
          }
          break;

        case "query_stats":
          this.sendToClient(ws, "stats", {
            state: this.debugger_service.get_state?.() || {},
            latency_stats: this.debugger_service.get_latency_stats?.() || {},
          });
          break;

        default:
          console.log("[WS] Unknown message type:", type);
      }
    } catch (err) {
      console.error("[WS] Error handling message:", err);
      this.sendToClient(ws, "error", { message: err.message });
    }
  }

  /**
   * Report a new deadlock detection
   */
  onDeadlockDetected(deadlock) {
    this.broadcast("deadlock_alert", {
      cycle_id: deadlock.cycle_id,
      processes: deadlock.processes,
      locks: deadlock.locks,
      severity: deadlock.severity || "high",
    });
  }

  /**
   * Report anomaly detection
   */
  onAnomalyDetected(anomaly) {
    this.broadcast("anomaly_alert", {
      anomaly_type: anomaly.type,
      process_id: anomaly.process_id,
      severity: anomaly.severity || "medium",
      description: anomaly.description,
    });
  }

  /**
   * Close all connections
   */
  close() {
    this.wss.clients.forEach((client) => {
      client.close();
    });
    this.clients.clear();
  }
}

module.exports = DebuggerWebSocketServer;
