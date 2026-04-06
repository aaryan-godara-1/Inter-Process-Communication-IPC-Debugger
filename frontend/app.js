const processNodeSlots = [
  { top: "30%", left: "25%", icon: "terminal" },
  { top: "30%", left: "75%", icon: "database" },
  { top: "50%", left: "50%", icon: "settings_ethernet" },
  { top: "85%", left: "50%", icon: "monitoring" },
];

function el(id) {
  return document.getElementById(id);
}

function fmtNumber(value, fallback = "0") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return fallback;
  }
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function buildProcessNodes(processes) {
  const container = el("processNodes");
  container.innerHTML = "";

  processes.forEach((proc, idx) => {
    const slot = processNodeSlots[idx % processNodeSlots.length];
    const stateColor = proc.state === "DEADLOCKED"
      ? "#ef4444"
      : proc.state === "WAITING"
        ? "#f59e0b"
        : proc.state === "TERMINATED"
          ? "#6b7280"
          : "#22c55e";

    const node = document.createElement("div");
    node.className = "absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2 group";
    node.style.top = slot.top;
    node.style.left = slot.left;

    node.innerHTML = `
      <div class="w-16 h-16 rounded-full bg-primary flex items-center justify-center text-on-primary node-draggable node-pulse shadow-[0_8px_32px_-8px_rgba(0,0,0,0.3)] border-2 border-white/20">
        <span class="material-symbols-outlined text-xl">${slot.icon}</span>
      </div>
      <div class="flex flex-col items-center">
        <span class="font-mono text-[10px] font-bold bg-white px-2 py-0.5 rounded shadow-sm border border-outline-variant/30">PID: ${proc.pid}</span>
        <span class="font-mono text-[9px] mt-1" style="color:${stateColor}">${proc.state}</span>
        <span class="font-mono text-[8px] text-on-surface-variant">${proc.name}</span>
      </div>
    `;

    container.appendChild(node);
  });
}

function buildChannels(report) {
  const monitor = el("channelMonitor");
  monitor.innerHTML = "";
  const channels = Object.keys(report.channels || {});

  if (channels.length === 0) {
    const row = document.createElement("div");
    row.className = "text-xs font-mono text-on-surface-variant";
    row.textContent = "No channels loaded.";
    monitor.appendChild(row);
    return;
  }

  channels.forEach((channel) => {
    const throughput = report.throughput_msg_s?.[channel] ?? 0;
    const latency = report.latency_ms?.[channel] ?? 0;

    const row = document.createElement("div");
    row.className = "flex justify-between items-center text-xs font-mono border-b border-outline-variant/10 pb-2";
    row.innerHTML = `
      <span class="text-on-surface-variant flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full bg-secondary"></span> ${channel}
      </span>
      <span class="font-bold">${fmtNumber(throughput)} msg/s | ${fmtNumber(latency)} ms</span>
    `;
    monitor.appendChild(row);
  });
}

function buildTimeline(logs) {
  const rows = el("timelineRows");
  rows.innerHTML = "";

  if (!logs || logs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "font-mono text-xs text-on-surface-variant";
    empty.textContent = "No events yet.";
    rows.appendChild(empty);
    return;
  }

  logs.slice(-20).reverse().forEach((evt) => {
    const row = document.createElement("div");
    row.className = "flex justify-between items-center rounded-md border border-outline-variant/20 bg-surface px-3 py-2";
    row.innerHTML = `
      <span class="font-mono text-[10px] text-on-surface-variant">${evt.ts_str}</span>
      <span class="font-mono text-[10px] font-bold">P${evt.pid}</span>
      <span class="font-mono text-[10px] uppercase">${evt.event_type}</span>
      <span class="font-mono text-[10px]">${evt.channel_id}</span>
      <span class="font-mono text-[10px] text-on-surface-variant truncate max-w-[34ch]">${evt.data}</span>
    `;
    rows.appendChild(row);
  });
}

function render(report) {
  const processDetails = report.process_details || [];
  el("activeProcs").textContent = String(processDetails.length).padStart(2, "0");
  el("ipcEvents").textContent = fmtNumber(report.logged_events, "0");
  el("scenarioText").textContent = `Scenario: ${report.scenario || "Unknown"}`;
  el("clusterLabel").textContent = `Live Topology Map - ${report.scenario || "Unknown"}`;

  const hasDeadlock = (report.deadlock_cycles || []).length > 0;
  const deadlockStatus = el("deadlockStatus");
  const deadlockIcon = el("deadlockIcon");
  const deadlockBanner = el("deadlockBanner");

  if (hasDeadlock) {
    deadlockStatus.textContent = `DETECTED (${report.deadlock_cycles.length} cycles)`;
    deadlockStatus.className = "font-mono text-lg font-bold text-[#ef4444]";
    deadlockIcon.textContent = "warning";
    deadlockIcon.className = "material-symbols-outlined text-[#ef4444] text-3xl";
    deadlockBanner.className = "bg-[#ef4444]/10 p-4 rounded-lg flex items-center justify-between border border-[#ef4444]/20";
    el("uplinkText").textContent = "Deadlock Alert";
  } else {
    deadlockStatus.textContent = "NONE DETECTED";
    deadlockStatus.className = "font-mono text-lg font-bold text-[#22c55e]";
    deadlockIcon.textContent = "check_circle";
    deadlockIcon.className = "material-symbols-outlined text-[#22c55e] text-3xl";
    deadlockBanner.className = "bg-[#22c55e]/5 p-4 rounded-lg flex items-center justify-between border border-[#22c55e]/20";
    el("uplinkText").textContent = report.completed ? "System Uplink Active" : "Scenario Timed Out";
  }

  buildProcessNodes(processDetails);
  buildChannels(report);
  buildTimeline(report.logs || []);
}

async function fetchReport() {
  const res = await fetch("/api/report", { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to fetch report");
  }
  const data = await res.json();
  render(data);
}

async function runScenario() {
  const scenario = el("scenarioSelect").value;
  const delay = Number(el("delayInput").value || "20");

  el("runBtn").disabled = true;
  el("runBtn").textContent = "Running...";
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario, delay_ms: delay, timeout: 10.0 }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Scenario run failed");
    }
    render(data);
  } catch (err) {
    console.error(err);
    alert(err.message || "Could not run scenario.");
  } finally {
    el("runBtn").disabled = false;
    el("runBtn").textContent = "Run";
  }
}

el("runBtn").addEventListener("click", runScenario);
el("refreshBtn").addEventListener("click", fetchReport);
el("reportBtn").addEventListener("click", fetchReport);

fetchReport().catch((err) => {
  console.error(err);
  alert("Could not load initial report. Start server with: python -m ipc_debugger.web_server");
});
