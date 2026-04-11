const state = {
  sim: null,
  live: null,
  socket: null,
  liveEnabled: true,
  terminalOpen: false,
  history: {
    threads: [],
    memory: [],
    disk: [],
    latency: [],
    network: [],
  },
};

const HISTORY_LIMIT = 12;
const el = (id) => document.getElementById(id);

function formatPercent(value, digits = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return `0.${'0'.repeat(digits)}%`;
  }
  return `${n.toFixed(digits)}%`;
}

function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) {
    return '0 B';
  }

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatSpeed(mbPerSec) {
  const n = Number(mbPerSec);
  return `${(Number.isFinite(n) ? n : 0).toFixed(1)} MB/s`;
}

function setText(id, value) {
  const node = el(id);
  if (node) {
    node.textContent = value;
  }
}

function setBar(id, value) {
  const node = el(id);
  if (!node) {
    return;
  }
  const clamped = Math.max(0, Math.min(100, Number(value) || 0));
  node.style.width = `${clamped}%`;
}

function pushHistory(key, value) {
  const arr = state.history[key];
  if (!arr) {
    return;
  }
  arr.push(Math.max(0, Number(value) || 0));
  while (arr.length > HISTORY_LIMIT) {
    arr.shift();
  }
}

function setSparkline(id, values, width = 100, height = 20) {
  const node = el(id);
  if (!node || !Array.isArray(values) || values.length === 0) {
    return;
  }

  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(1, max - min);
  const step = values.length > 1 ? width / (values.length - 1) : width;

  const points = values
    .map((value, idx) => {
      const x = idx * step;
      const y = height - (((value - min) / range) * (height - 2)) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  if (node.tagName.toLowerCase() === 'polyline') {
    node.setAttribute('points', points);
  } else if (node.tagName.toLowerCase() === 'path') {
    node.setAttribute('d', `M${points.replace(/ /g, ' L')}`);
  }
}

function renderGraph() {
  const graph = state.sim?.graph;
  const nodesHost = el('ipcGraphNodes');
  const edgesHost = el('ipcGraphEdges');

  if (!nodesHost || !edgesHost || !graph) {
    return;
  }

  nodesHost.innerHTML = '';
  edgesHost.innerHTML = '';

  const graphWidth = Math.max(1, Number(graph.width) || 940);
  const graphHeight = Math.max(1, Number(graph.height) || 360);
  const positions = new Map();

  for (const node of graph.nodes || []) {
    const x = (Number(node.x || 0) / graphWidth) * 100;
    const y = (Number(node.y || 0) / graphHeight) * 100;
    positions.set(node.id, { x, y });

    const card = document.createElement('div');
    card.className = 'absolute -translate-x-1/2 -translate-y-1/2 p-3 rounded-xl shadow-sm text-center min-w-[120px]';
    card.style.left = `${x}%`;
    card.style.top = `${y}%`;

    const isProcess = node.type === 'process';
    const isDeadlock = node.status === 'deadlock';
    const isWaiting = node.status === 'waiting';

    if (isProcess) {
      card.classList.add('bg-white', 'border-2', 'border-black');
    } else {
      card.classList.add('bg-surface-container-high', 'border', 'border-outline');
    }

    if (isDeadlock) {
      card.classList.remove('border-outline');
      card.classList.add('border-error', 'bg-error-container');
    } else if (isWaiting) {
      card.classList.add('bg-surface-container-lowest');
    }

    const kind = document.createElement('div');
    kind.className = isProcess
      ? 'text-[10px] uppercase font-bold text-tertiary'
      : 'text-[10px] uppercase font-bold text-on-surface-variant';
    kind.textContent = isProcess ? 'Process' : 'Resource';

    const title = document.createElement('div');
    title.className = 'text-sm font-bold';
    title.textContent = node.label;

    const subtitle = document.createElement('div');
    subtitle.className = 'text-[10px] mt-1 opacity-70';
    subtitle.textContent = node.subtitle || '';

    card.appendChild(kind);
    card.appendChild(title);
    card.appendChild(subtitle);
    nodesHost.appendChild(card);
  }

  for (const edge of graph.edges || []) {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) {
      continue;
    }

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', `${source.x}%`);
    line.setAttribute('y1', `${source.y}%`);
    line.setAttribute('x2', `${target.x}%`);
    line.setAttribute('y2', `${target.y}%`);
    line.setAttribute('stroke-width', edge.type === 'allocation' ? '2.5' : '2');
    line.setAttribute('stroke', edge.type === 'allocation' ? '#00358c' : '#ba1a1a');
    line.setAttribute('opacity', edge.highlighted ? '0.95' : '0.5');
    if (edge.type === 'request') {
      line.setAttribute('stroke-dasharray', '5 4');
    }
    edgesHost.appendChild(line);
  }
}

function renderMetrics() {
  const simProcesses = Array.isArray(state.sim?.processes) ? state.sim.processes : [];
  const liveProcesses = Array.isArray(state.live?.processes) ? state.live.processes : [];
  const top = [...liveProcesses].sort((a, b) => Number(b.cpuPercent || 0) - Number(a.cpuPercent || 0));
  const first = top[0];
  const second = top[1];

  setText('masterKernelLabel', `IPC_KERNEL · ${simProcesses.length} PROC`);
  setText('managerStatus', first ? `${first.id}_ACTIVE` : 'IDLE');
  setText('managerPrimaryName', first ? first.name : 'NO_PROCESS');
  setText('managerPrimaryPid', first ? String(first.pid) : '---');
  setText('managerPrimaryCpu', first ? formatPercent(first.cpuPercent, 1) : '0.0%');
  setText('managerSecondaryName', second ? second.name : 'NO_PROCESS');
  setText('managerSecondaryPid', second ? String(second.pid) : '---');
  setText('managerSecondaryCpu', second ? formatPercent(second.cpuPercent, 1) : '0.0%');

  const totalThreads = liveProcesses.reduce((sum, process) => sum + Number(process.threads || 0), 0);
  const memPercent = Number(state.live?.host?.memoryPercent || 0);
  const diskPercent = Number(state.live?.resources?.disk?.usedPercent || 0);
  const netPercent = Number(state.live?.resources?.network?.usedPercent || 0);
  const cpuPercent = Number(state.live?.resources?.cpu?.usedPercent || 0);
  const latency = Math.max(20, Math.round(220 - cpuPercent * 1.6));

  pushHistory('threads', totalThreads);
  pushHistory('memory', memPercent);
  pushHistory('disk', diskPercent);
  pushHistory('network', netPercent);
  pushHistory('latency', latency);

  setText('threadCountValue', `${totalThreads.toLocaleString()} ACTIVE`);
  setSparkline('threadSparkline', state.history.threads);

  setText('memoryFragmentationValue', formatPercent(memPercent * 0.8, 1));
  setBar('memoryFragmentationBar', memPercent * 0.8);

  setText('diskIoValue', formatSpeed(diskPercent * 2.2));
  setSparkline('diskIoSparkline', state.history.disk);

  setText('swapUsageValue', formatBytes((state.live?.host?.totalMemory || 0) * (memPercent / 100) * 0.45));
  setBar('swapUsageBar', memPercent * 0.9);

  setText('interruptLatencyValue', `${latency} μs`);
  setSparkline('interruptLatencySparkline', state.history.latency);

  setText('socketThroughputValue', `${(netPercent * 0.16).toFixed(1)} Gbps`);
  setSparkline('socketThroughputSparkline', state.history.network);
}

function renderBanner() {
  const analysis = state.sim?.analysis;
  const banner = el('criticalBanner');
  const icon = el('criticalBannerIcon');
  if (!banner || !icon) {
    return;
  }

  if (analysis?.state === 'DEADLOCK') {
    banner.className = 'absolute top-8 left-1/2 -translate-x-1/2 bg-error-container text-on-error-container px-4 py-1 text-[10px] tracking-tighter uppercase font-bold flex items-center gap-2 border border-error animate-pulse z-40 rounded-full shadow-lg';
    setText('criticalBannerText', analysis.detail || 'Deadlock detected');
    icon.textContent = 'warning';
    return;
  }

  if (analysis?.state === 'UNSAFE') {
    banner.className = 'absolute top-8 left-1/2 -translate-x-1/2 bg-error-container text-on-error-container px-4 py-1 text-[10px] tracking-tighter uppercase font-bold flex items-center gap-2 border border-error z-40 rounded-full shadow-lg';
    setText('criticalBannerText', analysis.detail || 'Unsafe state detected');
    icon.textContent = 'report';
    return;
  }

  if (analysis?.state === 'WAITING') {
    banner.className = 'absolute top-8 left-1/2 -translate-x-1/2 bg-surface-container-low text-on-surface px-4 py-1 text-[10px] tracking-tighter uppercase font-bold flex items-center gap-2 border border-outline-variant z-40 rounded-full shadow-lg';
    setText('criticalBannerText', analysis.detail || 'Waiting for resources');
    icon.textContent = 'schedule';
    return;
  }

  banner.className = 'absolute top-8 left-1/2 -translate-x-1/2 bg-surface-container-low text-on-surface px-4 py-1 text-[10px] tracking-tighter uppercase font-bold flex items-center gap-2 border border-outline-variant z-40 rounded-full shadow-lg';
  setText('criticalBannerText', 'Normal execution');
  icon.textContent = 'check_circle';
}

function renderButtons() {
  const runButton = el('runSimulationButton');
  const runText = runButton?.querySelector('span:last-child');
  const runIcon = runButton?.querySelector('span:first-child');

  if (runText) {
    const running = Boolean(state.sim?.simulation?.running);
    runText.textContent = running ? 'Pause Simulation' : 'Run Simulation';
    if (runIcon) {
      runIcon.textContent = running ? 'pause' : 'play_arrow';
    }
  }

  const liveButton = el('liveModeButton');
  const liveText = liveButton?.querySelector('span:last-child');
  if (liveButton && liveText) {
    const connected = state.socket?.readyState === WebSocket.OPEN;
    const active = state.liveEnabled && connected;
    liveText.textContent = active ? 'Live Mode On' : 'Live Mode Off';
    liveButton.className = active
      ? 'flex-1 flex flex-col items-center justify-center bg-neutral-800 text-white px-4 py-3 transition-all duration-75 scale-95 active:scale-90 rounded-xl'
      : 'flex-1 flex flex-col items-center justify-center text-neutral-400 px-4 py-3 hover:text-white hover:bg-neutral-800 transition-all duration-75 scale-95 active:scale-90 rounded-xl';
  }

  const terminalText = el('terminalButton')?.querySelector('span:last-child');
  if (terminalText) {
    terminalText.textContent = state.terminalOpen ? 'Hide Logs' : 'Show Logs';
  }
}

function renderLogOverlay() {
  if (!state.terminalOpen) {
    return;
  }

  const logs = Array.isArray(state.sim?.logs) ? state.sim.logs.slice(0, 3) : [];
  const text = logs.map((entry) => `${entry.time} ${String(entry.type || 'info').toUpperCase()} ${entry.message}`).join(' | ');
  setText('criticalBannerText', text || 'No recent events');
}

function render() {
  renderGraph();
  renderMetrics();
  renderBanner();
  renderButtons();
  renderLogOverlay();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

async function refreshState() {
  state.sim = await fetchJson('/api/state', { cache: 'no-store' });
  render();
}

function connectSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
  state.socket = socket;

  socket.addEventListener('open', () => {
    socket.send(JSON.stringify({ type: 'live:mode', enabled: state.liveEnabled }));
    renderButtons();
  });

  socket.addEventListener('message', (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type === 'state:update') {
        state.sim = message.payload;
      }
      if (message.type === 'live:update' && state.liveEnabled) {
        state.live = message.payload;
      }
      render();
    } catch {
      // Ignore malformed payloads.
    }
  });

  socket.addEventListener('close', () => {
    renderButtons();
    setTimeout(connectSocket, 1200);
  });
}

async function addProcess() {
  const payload = { priority: 1 + Math.floor(Math.random() * 5) };
  await fetchJson('/api/process', { method: 'POST', body: JSON.stringify(payload) });
  await refreshState();
}

async function addResource() {
  const payload = { totalInstances: 1 + Math.floor(Math.random() * 3) };
  await fetchJson('/api/resource', { method: 'POST', body: JSON.stringify(payload) });
  await refreshState();
}

async function toggleSimulation() {
  const running = Boolean(state.sim?.simulation?.running);
  if (running) {
    await fetchJson('/api/pause', { method: 'POST', body: '{}' });
  } else {
    await fetchJson('/api/start', {
      method: 'POST',
      body: JSON.stringify({ speed: 900, mode: 'realtime' }),
    });
  }
  await refreshState();
}

function toggleLiveMode() {
  state.liveEnabled = !state.liveEnabled;
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send(JSON.stringify({ type: 'live:mode', enabled: state.liveEnabled }));
  }
  renderButtons();
}

async function handleTerminalToggle() {
  state.terminalOpen = !state.terminalOpen;
  if (state.terminalOpen) {
    await fetchJson('/api/step', { method: 'POST', body: '{}' });
    await refreshState();
  } else {
    render();
  }
}

async function expandClusterView() {
  await fetchJson('/api/step', { method: 'POST', body: '{}' });
  await refreshState();
}

function wireControls() {
  el('addProcessButton')?.addEventListener('click', () => {
    addProcess().catch((error) => window.alert(error.message || 'Could not add process'));
  });

  el('addResourceButton')?.addEventListener('click', () => {
    addResource().catch((error) => window.alert(error.message || 'Could not add resource'));
  });

  el('runSimulationButton')?.addEventListener('click', () => {
    toggleSimulation().catch((error) => window.alert(error.message || 'Could not toggle simulation'));
  });

  el('liveModeButton')?.addEventListener('click', toggleLiveMode);

  el('terminalButton')?.addEventListener('click', () => {
    handleTerminalToggle().catch((error) => window.alert(error.message || 'Could not toggle logs'));
  });

  el('expandClusterView')?.addEventListener('click', () => {
    expandClusterView().catch((error) => window.alert(error.message || 'Could not expand cluster view'));
  });
}

async function init() {
  wireControls();
  connectSocket();
  try {
    await refreshState();
  } catch (error) {
    console.error(error);
    window.alert('Could not load simulation state. Ensure the server is running and refresh.');
  }
}

init();
