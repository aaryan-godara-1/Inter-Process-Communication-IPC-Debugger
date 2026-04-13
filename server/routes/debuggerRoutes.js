/**
 * IPC Debugger REST API Controller
 *
 * Provides REST endpoints for:
 * - Starting/stopping capture
 * - Querying events, processes, resources
 * - Getting deadlock and anomaly information
 * - Exporting traces
 */

const express = require("express");
const router = express.Router();

// Reference to the debugger instance (passed in via middleware)
let debugger_service = null;

/**
 * Middleware to inject debugger service
 */
function withDebugger(req, res, next) {
  debugger_service = req.app.locals.debugger_service;
  if (!debugger_service) {
    return res.status(500).json({ error: "Debugger service not initialized" });
  }
  next();
}

/**
 * GET /api/debugger/status
 * Get current debugger state
 */
router.get("/status", withDebugger, (req, res) => {
  try {
    const state = debugger_service.getState();
    res.json({
      status: state.status,
      total_events: state.total_events,
      total_processes: state.total_processes,
      total_resources: state.total_resources,
      deadlocks_detected: state.deadlocks_detected,
      duration_ms: Math.floor(state.duration_ns / 1000000),
      start_time_ns: state.start_time_ns,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /api/debugger/start
 * Start capturing events
 */
router.post("/start", withDebugger, (req, res) => {
  try {
    const config = req.body || {};
    debugger_service.start_capture(config);
    res.json({ message: "Capture started" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /api/debugger/stop
 * Stop capturing events
 */
router.post("/stop", withDebugger, (req, res) => {
  try {
    debugger_service.stop_capture();
    res.json({ message: "Capture stopped" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /api/debugger/pause
 * Pause capture temporarily
 */
router.post("/pause", withDebugger, (req, res) => {
  try {
    debugger_service.pause_capture();
    res.json({ message: "Capture paused" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * POST /api/debugger/resume
 * Resume capture after pause
 */
router.post("/resume", withDebugger, (req, res) => {
  try {
    debugger_service.resume_capture();
    res.json({ message: "Capture resumed" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/processes
 * Get list of all processes in trace
 */
router.get("/processes", withDebugger, (req, res) => {
  try {
    const processes = debugger_service.get_processes();
    res.json({ processes });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/resources
 * Get list of all resources
 */
router.get("/resources", withDebugger, (req, res) => {
  try {
    const resources = debugger_service.get_resources();
    res.json({ resources });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/events
 * Get events with optional filtering
 */
router.get("/events", withDebugger, (req, res) => {
  try {
    const { process_id, resource_id, correlation_id, limit } = req.query;
    let events = [];

    if (process_id) {
      events = debugger_service.get_events_by_process(parseInt(process_id));
    } else if (resource_id) {
      events = debugger_service.get_events_by_resource(resource_id);
    } else {
      events = debugger_service.timeline.get_latest_n(
        limit ? parseInt(limit) : 1000
      );
    }

    // Filter by correlation if provided
    if (correlation_id) {
      events = events.filter((e) => e.correlation_id === correlation_id);
    }

    res.json({ events: events.map((e) => e.to_dict()) });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/deadlocks
 * Get detected deadlock cycles
 */
router.get("/deadlocks", withDebugger, (req, res) => {
  try {
    const deadlocks = debugger_service.get_deadlocks();
    res.json({
      deadlocks: deadlocks.map((d) => d.to_dict()),
      count: deadlocks.length,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/flows
 * Get completed request-response flows
 */
router.get("/flows", withDebugger, (req, res) => {
  try {
    const flows = debugger_service.get_flows();
    const flow_data = flows.map((flow) => ({
      event_count: flow.length,
      start_time_ns: flow[0]?.timestamp_ns || 0,
      end_time_ns: flow[flow.length - 1]?.timestamp_ns || 0,
      latency_ns:
        (flow[flow.length - 1]?.timestamp_ns || 0) -
        (flow[0]?.timestamp_ns || 0),
      event_ids: flow.map((e) => e.event_id),
    }));
    res.json({ flows: flow_data, count: flow_data.length });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/latency-stats
 * Get latency statistics
 */
router.get("/latency-stats", withDebugger, (req, res) => {
  try {
    const stats = debugger_service.get_latency_stats();
    res.json(stats);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/process-pair/:pid1/:pid2
 * Get events between two processes
 */
router.get("/process-pair/:pid1/:pid2", withDebugger, (req, res) => {
  try {
    const pid1 = parseInt(req.params.pid1);
    const pid2 = parseInt(req.params.pid2);
    const events = debugger_service.get_events_for_process_pair(pid1, pid2);
    res.json({ events: events.map((e) => e.to_dict()), count: events.length });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/event/:event_id
 * Get a single event and its causal chain
 */
router.get("/event/:event_id", withDebugger, (req, res) => {
  try {
    const event_id = req.params.event_id;
    const event = debugger_service.timeline.get_event_by_id(event_id);

    if (!event) {
      return res.status(404).json({ error: "Event not found" });
    }

    const chain = debugger_service.get_causal_chain(event_id);

    res.json({
      event: event.to_dict(),
      causal_chain: chain.map((e) => e.to_dict()),
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/export
 * Export all events as JSON
 */
router.get("/export", withDebugger, (req, res) => {
  try {
    const { include_payloads } = req.query;
    const events = debugger_service.export_events(
      include_payloads === "true"
    );
    res.json({ event_count: events.length, events });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/debugger/summary
 * Get complete debugger summary
 */
router.get("/summary", withDebugger, (req, res) => {
  try {
    const summary = debugger_service.to_dict();
    res.json(summary);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
