/**
 * IPC Debugger Control Panel & Analytics Display
 *
 * Enhanced UI components for the debugger that display:
 * - Capture control (start/stop)
 * - Deadlock alerts
 * - Process and flow analysis
 * - Latency statistics
 */

class DebuggerPanel {
  constructor() {
    this.apiBase = "http://localhost:8010";
    this.debuggerBase = "/api/debugger";
    this.socket = null;
    this.state = {
      isCapturing: false,
      processes: [],
      resources: [],
      deadlocks: [],
      flows: [],
      totalEvents: 0,
      latencyStats: {},
    };
    this.callbacks = {
      onDeadlockDetected: null,
      onEventReceived: null,
      onStateChanged: null,
    };
  }

  /**
   * Initialize the debugger panel
   */
  async init(container_id = "debugger-panel") {
    const container = document.getElementById(container_id);
    if (!container) {
      console.warn(`Container ${container_id} not found`);
      return;
    }

    // Create panel UI
    this.createPanelUI(container);

    // Setup WebSocket for real-time updates
    this.setupWebSocket();

    // Get initial state
    await this.refreshState();
  }

  /**
   * Create the UI elements
   */
  createPanelUI(container) {
    container.innerHTML = `
      <div class="debugger-panel">
        <div class="debugger-header">
          <h3>IPC Debugger</h3>
          <div class="debugger-controls">
            <button id="debugger-start" class="btn btn-primary">Start</button>
            <button id="debugger-stop" class="btn btn-secondary" disabled>Stop</button>
            <button id="debugger-refresh" class="btn btn-secondary">Refresh</button>
          </div>
        </div>

        <div class="debugger-content">
          <!-- Status -->
          <div class="status-panel">
            <div class="status-row">
              <span>Status:</span>
              <span id="debugger-status" class="status-badge">Idle</span>
            </div>
            <div class="status-row">
              <span>Events:</span>
              <span id="debugger-events">0</span>
            </div>
            <div class="status-row">
              <span>Processes:</span>
              <span id="debugger-processes">0</span>
            </div>
            <div class="status-row">
              <span>Deadlocks:</span>
              <span id="debugger-deadlocks" class="alert-badge">0</span>
            </div>
          </div>

          <!-- Alerts -->
          <div class="alerts-panel">
            <h4>Alerts</h4>
            <div id="debugger-alerts" class="alerts-list"></div>
          </div>

          <!-- Latency Stats -->
          <div class="stats-panel">
            <h4>Latency (ns)</h4>
            <div id="debugger-latency-stats" class="stats-grid"></div>
          </div>

          <!-- Processes -->
          <div class="processes-panel">
            <h4>Processes</h4>
            <ul id="debugger-process-list" class="process-list"></ul>
          </div>
        </div>
      </div>

      <style>
        .debugger-panel {
          border: 1px solid #ddd;
          border-radius: 4px;
          background: #f9f9f9;
          padding: 12px;
          max-width: 400px;
          font-family: monospace;
          font-size: 12px;
        }

        .debugger-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
          padding-bottom: 8px;
          border-bottom: 1px solid #ddd;
        }

        .debugger-header h3 {
          margin: 0;
          font-size: 14px;
        }

        .debugger-controls {
          display: flex;
          gap: 4px;
        }

        .debugger-controls button {
          padding: 4px 8px;
          font-size: 11px;
          border: 1px solid #ccc;
          background: white;
          cursor: pointer;
          border-radius: 3px;
        }

        .debugger-controls button.btn-primary {
          background: #0ea;
          color: white;
          border-color: #0a8;
        }

        .debugger-controls button.btn-secondary {
          background: #666;
          color: white;
          border-color: #555;
        }

        .debugger-controls button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .debugger-content > div {
          margin-bottom: 12px;
          padding-bottom: 8px;
          border-bottom: 1px solid #ddd;
        }

        .debugger-content > div:last-child {
          border-bottom: none;
          margin-bottom: 0;
          padding-bottom: 0;
        }

        .debugger-content h4 {
          margin: 0 0 6px 0;
          font-size: 12px;
        }

        .status-panel {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }

        .status-row {
          display: flex;
          justify-content: space-between;
          padding: 4px;
          background: white;
          border-radius: 3px;
        }

        .status-badge {
          padding: 2px 6px;
          border-radius: 3px;
          background: #ddemergence;
          font-weight: bold;
        }

        .status-badge.capturing {
          background: #0ea;
          color: white;
        }

        .alert-badge {
          padding: 2px 6px;
          border-radius: 3px;
          background: #f44;
          color: white;
          font-weight: bold;
        }

        .alerts-list {
          max-height: 120px;
          overflow-y: auto;
        }

        .alert-item {
          padding: 6px;
          margin: 2px 0;
          background: #ffe0e0;
          border-left: 3px solid #f44;
          border-radius: 2px;
          font-size: 11px;
        }

        .stats-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
        }

        .stat-item {
          padding: 6px;
          background: white;
          border-radius: 3px;
          text-align: center;
        }

        .stat-label {
          display: block;
          font-size: 10px;
          color: #666;
        }

        .stat-value {
          display: block;
          font-size: 14px;
          font-weight: bold;
          color: #0ea;
        }

        .process-list {
          list-style: none;
          margin: 0;
          padding: 0;
          max-height: 200px;
          overflow-y: auto;
        }

        .process-item {
          padding: 4px 6px;
          margin: 2px 0;
          background: white;
          border-left: 3px solid #0ea;
          border-radius: 2px;
          cursor: pointer;
        }

        .process-item:hover {
          background: #f0ff00;
        }
      </style>
    `;

    // Setup event listeners
    document.getElementById("debugger-start").addEventListener("click", () =>
      this.startCapture()
    );
    document.getElementById("debugger-stop").addEventListener("click", () =>
      this.stopCapture()
    );
    document.getElementById("debugger-refresh").addEventListener("click", () =>
      this.refreshState()
    );
  }

  /**
   * Setup WebSocket connection for real-time updates
   */
  setupWebSocket() {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/api/debugger/ws`;

    this.socket = new WebSocket(wsUrl);

    this.socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleWebSocketMessage(msg);
      } catch (err) {
        console.error("WebSocket message parse error:", err);
      }
    };

    this.socket.onerror = (err) => {
      console.error("WebSocket error:", err);
    };

    this.socket.onopen = () => {
      console.log("Debugger WebSocket connected");
      this.refreshState();
    };

    this.socket.onclose = () => {
      console.log("Debugger WebSocket disconnected");
    };
  }

  /**
   * Handle WebSocket messages
   */
  handleWebSocketMessage(msg) {
    const { type, data } = msg;

    switch (type) {
      case "event":
        this.state.totalEvents++;
        if (this.callbacks.onEventReceived) {
          this.callbacks.onEventReceived(data);
        }
        this.updateEventCount();
        break;

      case "deadlock_alert":
        this.state.deadlocks.push(data);
        this.addAlert(`Deadlock detected: ${data.processes.join(", ")}`);
        if (this.callbacks.onDeadlockDetected) {
          this.callbacks.onDeadlockDetected(data);
        }
        this.updateDeadlockCount();
        break;

      case "status":
        this.state.status = data.collector_status;
        this.updateStatus();
        break;

      case "stats":
        this.state.latencyStats = data.latency_stats || {};
        this.updateLatencyStats();
        break;
    }
  }

  /**
   * Start capture
   */
  async startCapture() {
    try {
      const response = await fetch(
        `${this.apiBase}${this.debuggerBase}/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ipc_types: ["pipe", "socket", "mutex"],
            sample_rate: 1.0,
          }),
        }
      );

      if (response.ok) {
        this.state.isCapturing = true;
        this.updateStatus();
        document.getElementById("debugger-start").disabled = true;
        document.getElementById("debugger-stop").disabled = false;
      }
    } catch (err) {
      console.error("Error starting capture:", err);
      this.addAlert(`Error: ${err.message}`);
    }
  }

  /**
   * Stop capture
   */
  async stopCapture() {
    try {
      const response = await fetch(
        `${this.apiBase}${this.debuggerBase}/stop`,
        {
          method: "POST",
        }
      );

      if (response.ok) {
        this.state.isCapturing = false;
        this.updateStatus();
        document.getElementById("debugger-start").disabled = false;
        document.getElementById("debugger-stop").disabled = true;
      }
    } catch (err) {
      console.error("Error stopping capture:", err);
      this.addAlert(`Error: ${err.message}`);
    }
  }

  /**
   * Refresh state
   */
  async refreshState() {
    try {
      const [status, processes, deadlocks, latency] = await Promise.all([
        fetch(`${this.apiBase}${this.debuggerBase}/status`).then((r) =>
          r.json()
        ),
        fetch(`${this.apiBase}${this.debuggerBase}/processes`).then((r) =>
          r.json()
        ),
        fetch(`${this.apiBase}${this.debuggerBase}/deadlocks`).then((r) =>
          r.json()
        ),
        fetch(`${this.apiBase}${this.debuggerBase}/latency-stats`).then((r) =>
          r.json()
        ),
      ]);

      this.state.status = status.status;
      this.state.totalEvents = status.total_events;
      this.state.processes = processes.processes || [];
      this.state.deadlocks = deadlocks.deadlocks || [];
      this.state.latencyStats = latency || {};

      this.isCapturing = status.status === "capturing";
      this.updateAllUI();
    } catch (err) {
      console.error("Error refreshing state:", err);
    }
  }

  /**
   * Update UI elements
   */
  updateAllUI() {
    this.updateStatus();
    this.updateEventCount();
    this.updateProcessList();
    this.updateDeadlockCount();
    this.updateLatencyStats();
  }

  updateStatus() {
    const badge = document.getElementById("debugger-status");
    if (badge) {
      badge.textContent = this.state.status || "unknown";
      badge.className =
        "status-badge " +
        (this.state.isCapturing ? "capturing" : "");
    }
  }

  updateEventCount() {
    const el = document.getElementById("debugger-events");
    if (el) {
      el.textContent = this.state.totalEvents;
    }
  }

  updateDeadlockCount() {
    const el = document.getElementById("debugger-deadlocks");
    if (el) {
      el.textContent = this.state.deadlocks.length;
    }
  }

  updateLatencyStats() {
    const container = document.getElementById("debugger-latency-stats");
    if (!container) return;

    const stats = this.state.latencyStats;
    const items = [
      ["P50", Math.floor(stats.p50 || 0)],
      ["P95", Math.floor(stats.p95 || 0)],
      ["P99", Math.floor(stats.p99 || 0)],
      ["Max", Math.floor(stats.max || 0)],
    ];

    container.innerHTML = items
      .map(
        ([label, value]) =>
          `<div class="stat-item"><span class="stat-label">${label}</span><span class="stat-value">${value}</span></div>`
      )
      .join("");
  }

  updateProcessList() {
    const container = document.getElementById("debugger-process-list");
    if (!container) return;

    container.innerHTML = this.state.processes
      .map(
        (pid) =>
          `<li class="process-item" onclick="debuggerPanel.selectProcess(${pid})">PID ${pid}</li>`
      )
      .join("");
  }

  addAlert(message) {
    const container = document.getElementById("debugger-alerts");
    if (!container) return;

    const alert = document.createElement("div");
    alert.className = "alert-item";
    alert.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;

    container.insertBefore(alert, container.firstChild);

    // Keep only last 10 alerts
    while (container.children.length > 10) {
      container.removeChild(container.lastChild);
    }
  }

  selectProcess(pid) {
    console.log("Selected process:", pid);
    if (this.callbacks.onStateChanged) {
      this.callbacks.onStateChanged({ selectedProcess: pid });
    }
  }
}

// Global instance for easy access
const debuggerPanel = new DebuggerPanel();
