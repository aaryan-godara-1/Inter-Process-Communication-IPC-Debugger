const state = {
  sim: null,
  live: null,
  socket: null,
  liveEnabled: false,
  terminalOpen: false,
  taskManagerOpen: false,
  graphMinimized: false,
  graphView: {
    scale: 1,
    x: 0,
    y: 0,
    isPanning: false,
    startX: 0,
    startY: 0,
  },
  graphLayoutCache: {
    width: 0,
    height: 0,
    layoutSignature: '',
    nextProcessSlot: 0,
    processSlots: new Map(),
    processAnchors: new Map(),
    anchorSlots: new Map(),
    anchorNextSlot: new Map(),
    maxProcessCount: 0,
  },
  graphInteraction: {
    hoverProcessId: null,
    hoverResourceId: null,
    selectedProcessId: null,
    selectedResourceId: null,
    filterResourceId: 'ALL',
  },
  graphSnapshot: null,
  graphFramePending: false,
  modeTransitionTimer: null,
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

function humanizeLabel(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }

  return raw
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
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

function formatLiveAge(ts) {
  const sampleTs = Number(ts || 0);
  if (!Number.isFinite(sampleTs) || sampleTs <= 0) {
    return 'Live: waiting';
  }
  const seconds = Math.max(0, Math.round((Date.now() - sampleTs) / 1000));
  return seconds <= 1 ? 'Live: now' : `Live: ${seconds}s ago`;
}

const RESOURCE_COLORS = {
  CPU: '#b45309',
  MEM: '#1d4ed8',
  DISK: '#6b7280',
  NET: '#0f766e',
  THR: '#475569',
  GPU: '#7c3aed',
  BAT: '#ca8a04',
  TMP: '#dc2626',
};

const RESOURCE_ORDER = ['CPU', 'MEM', 'DISK', 'NET', 'THR', 'GPU', 'BAT', 'TMP'];
const RESOURCE_LANE_OFFSET = {
  CPU: -35,
  MEM: -25,
  DISK: -15,
  NET: -5,
  THR: 5,
  GPU: 15,
  BAT: 25,
  TMP: 35,
};
const PROCESS_RESOURCE_MIN_GAP = 360;
const GRAPH_LAYOUT = {
  centerRadius: 172,
  childRingRadius: 336,
  processRingCapacity: 24,
  processBaseRadius: 640,
  processRingGap: 140,
  processYScale: 0.95,
};
const PROCESS_RING_SLOT_ORDER = [
  0, 12, 6, 18, 3, 9, 15, 21,
  1, 7, 13, 19, 4, 10, 16, 22,
  2, 8, 14, 20, 5, 11, 17, 23,
];

const RESOURCE_CHILDREN = {
  CPU: (coreCount) => {
    const count = Math.max(1, Number(coreCount) || 1);
    const visible = Math.min(6, count);
    const nodes = Array.from({ length: visible }, (_, idx) => ({
      id: `CPU_CORE_${idx}`,
      label: `Core ${idx}`,
      subtitle: 'cpu lane',
    }));

    if (count > visible) {
      nodes.push({
        id: 'CPU_CORE_OTHER',
        label: `Core +${count - visible}`,
        subtitle: 'grouped cores',
      });
    }

    return nodes;
  },
  MEM: () => [
    { id: 'MEM_HEAP', label: 'Heap', subtitle: 'allocations' },
    { id: 'MEM_STACK', label: 'Stack', subtitle: 'execution stack' },
    { id: 'MEM_CACHE', label: 'Cache', subtitle: 'hot pages' },
    { id: 'MEM_SWAP', label: 'Swap', subtitle: 'paged memory' },
  ],
  DISK: () => [
    { id: 'DISK_READ', label: 'Read Q', subtitle: 'read queue' },
    { id: 'DISK_WRITE', label: 'Write Q', subtitle: 'write queue' },
    { id: 'DISK_HANDLE', label: 'Handles', subtitle: 'file handles' },
  ],
  NET: () => [
    { id: 'NET_SOCKET', label: 'Sockets', subtitle: 'active sockets' },
    { id: 'NET_PORT', label: 'Ports', subtitle: 'bound ports' },
    { id: 'NET_PACKET', label: 'Packets', subtitle: 'packet flow' },
  ],
  THR: () => [
    { id: 'THR_SCHED', label: 'Scheduler', subtitle: 'dispatch queue' },
    { id: 'THR_WORKER', label: 'Workers', subtitle: 'worker pool' },
    { id: 'THR_IO', label: 'IO Threads', subtitle: 'io workers' },
  ],
  GPU: () => [
    { id: 'GPU_3D', label: '3D', subtitle: 'graphics engines' },
    { id: 'GPU_COPY', label: 'Copy', subtitle: 'copy engines' },
    { id: 'GPU_VIDEO', label: 'Video', subtitle: 'video engines' },
  ],
  BAT: () => [
    { id: 'BAT_CHARGE', label: 'Charge', subtitle: 'battery level' },
    { id: 'BAT_RATE', label: 'Rate', subtitle: 'drain profile' },
  ],
  TMP: () => [
    { id: 'TMP_CPU', label: 'CPU Temp', subtitle: 'thermal zone' },
    { id: 'TMP_GPU', label: 'GPU Temp', subtitle: 'sensor map' },
  ],
};

function buildProcessResourceUsage(process) {
  const usage = [
    { resourceId: 'CPU', value: Number(process.cpuPercent || 0) },
    { resourceId: 'MEM', value: Number(process.memoryPercent || 0) },
    { resourceId: 'DISK', value: Number(process.ioPercent || 0) },
    { resourceId: 'NET', value: Number(process.networkPercent || 0) },
    { resourceId: 'THR', value: Number(process.threads || 0) * 2.2 },
    { resourceId: 'GPU', value: Number(process.gpuPercent || 0) },
  ];

  return usage.filter((item) => item.value >= 2);
}

function accumulateUsage(bucket, key, value) {
  const current = Number(bucket.get(key) || 0);
  bucket.set(key, current + Math.max(0, Number(value) || 0));
}

function computeDepthUsage(process, hostCores) {
  if (process && process.deepUsage && typeof process.deepUsage === 'object') {
    const depthUsage = new Map();
    for (const [key, value] of Object.entries(process.deepUsage)) {
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 0) {
        depthUsage.set(key, numeric);
      }
    }
    return depthUsage;
  }

  // No synthetic fallback: only render connections backed by telemetry-provided deepUsage.
  return new Map();
}

function buildLiveGraph(liveProcesses, graphWidth, graphHeight) {
  const sortedProcesses = [...liveProcesses].sort((a, b) => Number(b.cpuPercent || 0) - Number(a.cpuPercent || 0));
  const hostCores = Math.max(2, Math.min(10, Number(state.live?.host?.logicalCores || 4)));

  const baseResources = [
    { id: 'CPU', label: 'CPU', subtitle: 'compute plane', usage: Number(state.live?.resources?.cpu?.usedPercent || 0) },
    { id: 'MEM', label: 'Memory', subtitle: 'memory plane', usage: Number(state.live?.resources?.memory?.usedPercent || 0) },
    { id: 'DISK', label: 'Disk IO', subtitle: 'storage plane', usage: Number(state.live?.resources?.disk?.usedPercent || 0) },
    { id: 'NET', label: 'Network', subtitle: 'network plane', usage: Number(state.live?.resources?.network?.usedPercent || 0) },
    { id: 'THR', label: 'Threads', subtitle: 'thread plane', usage: Number(state.live?.resources?.threads?.usedPercent || 0) },
    { id: 'GPU', label: 'GPU', subtitle: 'graphics plane', usage: Number(state.live?.resources?.gpu?.usedPercent || 0) },
    { id: 'BAT', label: 'Battery', subtitle: 'power plane', usage: Number(state.live?.resources?.battery?.usedPercent || 0) },
    { id: 'TMP', label: 'Temperature', subtitle: 'thermal plane', usage: Number(state.live?.resources?.temperature?.usedPercent || 0) },
  ];

  const nodes = [];
  const edges = [];
  const nodeById = new Map();
  const depthTotals = new Map();
  const resourceConsumers = new Map();
  const processCount = Math.max(1, sortedProcesses.length);
  const liveDeep = state.live?.resources?.deep && typeof state.live.resources.deep === 'object'
    ? state.live.resources.deep
    : null;

  const addNode = (node) => {
    nodes.push(node);
    nodeById.set(node.id, node);
  };

  for (const resource of baseResources) {
    const color = RESOURCE_COLORS[resource.id] || '#6b7280';
    addNode({
      id: resource.id,
      type: 'resource',
      depth: 0,
      resourceGroup: resource.id,
      label: resource.label,
      usage: resource.usage,
      subtitle: `${formatPercent(resource.usage, 1)} live`,
      color,
    });

    const childFactory = RESOURCE_CHILDREN[resource.id];
    const children = typeof childFactory === 'function'
      ? childFactory(resource.id === 'CPU' ? hostCores : undefined)
      : [];

    for (const child of children) {
      const deepEntry = liveDeep ? liveDeep[child.id] : null;
      const deepPercent = Number(deepEntry?.usedPercent || 0);
      addNode({
        id: child.id,
        type: 'resource',
        depth: 1,
        parentId: resource.id,
        resourceGroup: resource.id,
        label: child.label,
        usage: deepPercent,
        subtitle: `${child.subtitle} · ${formatPercent(deepPercent, 1)}`,
        color,
      });

      edges.push({
        source: resource.id,
        target: child.id,
        type: 'depth-link',
        resourceId: resource.id,
        intensity: 0.25,
      });
    }

  }

  for (const process of sortedProcesses) {
    const processId = `live-${process.pid}`;
    const usage = buildProcessResourceUsage(process).sort((a, b) => b.value - a.value);
    const depthUsage = computeDepthUsage(process, hostCores);
    const status = Number(process.cpuPercent || 0) >= 75 ? 'waiting' : 'running';
    const primaryResourceId = usage[0]?.resourceId || 'CPU';

    addNode({
      id: processId,
      type: 'process',
      label: String(process.name || 'PROCESS').toUpperCase(),
      subtitle: `PID ${process.pid} · CPU ${formatPercent(process.cpuPercent, 1)} · MEM ${formatPercent(process.memoryPercent, 1)}`,
      cpuPercent: Number(process.cpuPercent || 0),
      memoryPercent: Number(process.memoryPercent || 0),
      status,
      primaryResourceId,
    });

    for (const resourceUse of usage) {
      if (resourceUse.value < 3) {
        continue;
      }

      if (!resourceConsumers.has(resourceUse.resourceId)) {
        resourceConsumers.set(resourceUse.resourceId, []);
      }
      resourceConsumers.get(resourceUse.resourceId).push({
        processId,
        value: Number(resourceUse.value || 0),
      });

      edges.push({
        source: processId,
        target: resourceUse.resourceId,
        type: 'usage',
        resourceId: resourceUse.resourceId,
        intensity: Math.min(1, resourceUse.value / 100),
      });
    }

    const depthByResource = new Map();
    for (const [depthNodeId, depthValue] of depthUsage.entries()) {
      if (depthValue < 3 || !nodeById.has(depthNodeId)) {
        continue;
      }

      const depthNode = nodeById.get(depthNodeId);
      const resourceId = depthNode?.resourceGroup || depthNode?.parentId;
      if (!resourceId) {
        continue;
      }

      const existing = depthByResource.get(resourceId);
      if (!existing || depthValue > existing.value) {
        depthByResource.set(resourceId, {
          depthNodeId,
          value: depthValue,
        });
      }
    }

    for (const [resourceId, depthTarget] of depthByResource.entries()) {
      const depthNodeId = depthTarget.depthNodeId;
      const depthValue = depthTarget.value;
      accumulateUsage(depthTotals, depthNodeId, depthValue);

      edges.push({
        source: processId,
        target: depthNodeId,
        type: 'usage-depth',
        resourceId,
        intensity: Math.min(1, depthValue / 100),
      });
    }

  }

  for (const [resourceId, consumers] of resourceConsumers.entries()) {
    const ordered = [...consumers].sort((a, b) => b.value - a.value);
    const resourceNode = nodeById.get(resourceId);
    if (resourceNode) {
      const holder = ordered[0];
      const holderPid = holder ? String(holder.processId).replace('live-', '') : '---';
      const waiting = Math.max(0, ordered.length - 1);
      const usageText = formatPercent(resourceNode.usage || 0, 1);
      resourceNode.subtitle = resourceId === 'CPU'
        ? `CPU ${usageText} · H:${holderPid} · W:${waiting}`
        : `${usageText} · H:${holderPid} · W:${waiting}`;
    }

    if (ordered.length <= 1) {
      continue;
    }

    const holder = ordered[0];
    const waiters = ordered.slice(1, 6);
    for (const waiter of waiters) {
      edges.push({
        source: waiter.processId,
        target: holder.processId,
        type: 'contention',
        resourceId,
        intensity: Math.min(1, waiter.value / 100),
      });
    }
  }

  for (const [depthNodeId, totalValue] of depthTotals.entries()) {
    const node = nodeById.get(depthNodeId);
    if (!node) {
      continue;
    }

    const avgUsage = liveDeep && liveDeep[depthNodeId]
      ? Number(liveDeep[depthNodeId].usedPercent || 0)
      : Math.min(100, totalValue / processCount);
    const baseSubtitle = String(node.subtitle || '').split('·')[0].trim();
    node.usage = avgUsage;
    node.subtitle = `${baseSubtitle} · ${formatPercent(avgUsage, 1)}`;
  }

  return { nodes, edges, width: graphWidth, height: graphHeight };
}

function chunk(items, size) {
  const rows = [];
  for (let idx = 0; idx < items.length; idx += size) {
    rows.push(items.slice(idx, idx + size));
  }
  return rows;
}

function ellipsePerimeter(radiusX, radiusY) {
  const a = Math.max(1, Number(radiusX) || 1);
  const b = Math.max(1, Number(radiusY) || 1);
  // Ramanujan approximation for ellipse circumference.
  return 2 * Math.PI * Math.sqrt(((a * a) + (b * b)) / 2);
}

function resolveProcessRingLayout({
  processCount,
  maxOuterRadius,
  minBaseRadius,
  preferredGap,
  minGap,
  nodeSpacing,
  yScale,
}) {
  const targetCount = Math.max(0, Number(processCount) || 0);
  if (targetCount === 0) {
    return {
      ringCapacities: [],
      ringCount: 0,
      ringGap: 0,
      baseRadius: Math.max(0, Number(minBaseRadius) || 0),
    };
  }

  const outer = Math.max(160, Number(maxOuterRadius) || 160);
  const minBase = Math.max(100, Math.min(outer, Number(minBaseRadius) || 100));
  const prefGap = Math.max(0, Number(preferredGap) || 0);
  const hardMinGap = Math.max(0, Number(minGap) || 0);
  const spacing = Math.max(110, Number(nodeSpacing) || 110);
  const scaleY = Math.max(0.5, Number(yScale) || 0.95);
  const maxRings = 14;
  let best = null;

  for (let ringCount = 1; ringCount <= maxRings; ringCount += 1) {
    const maxGapBySpan = ringCount === 1 ? 0 : ((outer - minBase) / (ringCount - 1));
    if (ringCount > 1 && maxGapBySpan < hardMinGap) {
      continue;
    }

    const ringGap = ringCount === 1 ? 0 : Math.min(prefGap, maxGapBySpan);
    const baseRadius = ringCount === 1 ? outer : (outer - ringGap * (ringCount - 1));
    if (baseRadius < minBase - 0.001) {
      continue;
    }

    const ringCapacities = [];
    let totalCapacity = 0;
    for (let ring = 0; ring < ringCount; ring += 1) {
      const radius = baseRadius + (ring * ringGap);
      const perimeter = ellipsePerimeter(radius, radius * scaleY);
      const capacity = Math.max(6, Math.floor(perimeter / spacing));
      ringCapacities.push(capacity);
      totalCapacity += capacity;
    }

    const candidate = {
      ringCapacities,
      ringCount,
      ringGap,
      baseRadius,
      totalCapacity,
    };

    if (!best || totalCapacity > best.totalCapacity) {
      best = candidate;
    }
    if (totalCapacity >= targetCount) {
      return candidate;
    }
  }

  if (best) {
    return best;
  }

  const fallbackPerimeter = ellipsePerimeter(outer, outer * scaleY);
  return {
    ringCapacities: [Math.max(targetCount, Math.floor(fallbackPerimeter / spacing), 6)],
    ringCount: 1,
    ringGap: 0,
    baseRadius: outer,
  };
}

function layoutGraphNodes(nodes, graphWidth, graphHeight) {
  const resources = nodes.filter((node) => node.type === 'resource');
  const processes = nodes.filter((node) => node.type === 'process');
  const positions = new Map();
  const cardSizes = {
    process: { w: 184, h: 60, radius: 10 },
    resourceRoot: { w: 170, h: 56, radius: 10 },
    resourceDepth: { w: 146, h: 50, radius: 10 },
  };

  const cache = state.graphLayoutCache;
  if (!cache || !(cache.processSlots instanceof Map)) {
    state.graphLayoutCache = {
      width: graphWidth,
      height: graphHeight,
      nextProcessSlot: 0,
      processSlots: new Map(),
      processAnchors: new Map(),
      anchorSlots: new Map(),
      anchorNextSlot: new Map(),
      maxProcessCount: 0,
    };
  }

  state.graphLayoutCache.width = graphWidth;
  state.graphLayoutCache.height = graphHeight;

  const centerX = graphWidth / 2;
  const centerY = graphHeight / 2;

  const ringSpacing = 120;
  const nodeSpacing = 90;
  const resourceBaseRadius = 120;
  const processBaseRadius = 400;
  const rootAngles = new Map();

  const sortedResources = [...resources].sort((a, b) => {
    const aRoot = String(a.resourceGroup || a.parentId || a.id || '');
    const bRoot = String(b.resourceGroup || b.parentId || b.id || '');
    const ai = RESOURCE_ORDER.indexOf(aRoot);
    const bi = RESOURCE_ORDER.indexOf(bRoot);
    if ((ai === -1 ? 99 : ai) !== (bi === -1 ? 99 : bi)) {
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    }
    if (Number(a.depth || 0) !== Number(b.depth || 0)) {
      return Number(a.depth || 0) - Number(b.depth || 0);
    }
    return String(a.id).localeCompare(String(b.id));
  });

  const processSlots = state.graphLayoutCache.processSlots;
  for (const process of processes) {
    if (!processSlots.has(process.id)) {
      processSlots.set(process.id, state.graphLayoutCache.nextProcessSlot);
      state.graphLayoutCache.nextProcessSlot += 1;
    }
  }

  const sortedProcesses = [...processes].sort((a, b) => {
    const sa = Number(processSlots.get(a.id) || 0);
    const sb = Number(processSlots.get(b.id) || 0);
    return sa - sb;
  });

  const maxNodesForRing = (radius) => {
    const circumference = Math.max(1, 2 * Math.PI * Math.max(1, radius));
    return Math.max(1, Math.floor(circumference / nodeSpacing));
  };

  const placeNodesOnRings = (nodeList, baseRadius, onPlaced = null) => {
    const ringRadii = [];
    let placed = 0;
    let ringIndex = 0;

    while (placed < nodeList.length) {
      const remaining = nodeList.length - placed;
      const capacity = 4 + (ringIndex * 2);
      const radius = baseRadius + (ringIndex * ringSpacing);
      const maxBySpacing = maxNodesForRing(radius);
      const nodesInRing = Math.max(1, Math.min(capacity, maxBySpacing, remaining));
      const rotationOffset = ringIndex * (Math.PI / 2);

      ringRadii.push(radius);
      for (let index = 0; index < nodesInRing; index += 1) {
        const node = nodeList[placed + index];
        const angle = ((Math.PI * 2 / nodesInRing) * index) + rotationOffset;
        const x = centerX + (radius * Math.cos(angle));
        const y = centerY + (radius * Math.sin(angle));

        positions.set(node.id, { x, y, fromX: centerX, fromY: centerY });
        node.fx = x;
        node.fy = y;

        if (typeof onPlaced === 'function') {
          onPlaced(node, angle);
        }
      }

      placed += nodesInRing;
      ringIndex += 1;
    }

    return ringRadii;
  };

  const resourceRingRadii = placeNodesOnRings(sortedResources, resourceBaseRadius, (node, angle) => {
    if (Number(node.depth || 0) === 0) {
      rootAngles.set(node.id, angle);
    }
  });
  const lastResourceRadius = resourceRingRadii.length > 0
    ? resourceRingRadii[resourceRingRadii.length - 1]
    : resourceBaseRadius;
  const resolvedProcessBaseRadius = Math.max(processBaseRadius, lastResourceRadius + (ringSpacing * 2));
  const processRingRadii = placeNodesOnRings(sortedProcesses, resolvedProcessBaseRadius);

  const centerRadius = resourceRingRadii[0] || resourceBaseRadius;
  const childRingRadius = resourceRingRadii.length > 0
    ? resourceRingRadii[resourceRingRadii.length - 1]
    : resourceBaseRadius;

  return {
    positions,
    cards: {
      process: cardSizes.process,
      resourceRoot: cardSizes.resourceRoot,
      resourceDepth: cardSizes.resourceDepth,
    },
    layoutMetrics: {
      centerRadius,
      childRingRadius,
      depthRadii: resourceRingRadii,
      resourceRingRadii,
      processRingRadii,
      processBaseRadius: resolvedProcessBaseRadius,
      processRingGap: ringSpacing,
      processRingCount: processRingRadii.length,
    },
    rootAngles,
  };
}

function createSvgEl(name) {
  return document.createElementNS('http://www.w3.org/2000/svg', name);
}

function ensureGraphSurfaceDefs(canvas) {
  if (canvas.querySelector('defs[data-graph-surface="true"]')) {
    return;
  }

  const defs = createSvgEl('defs');
  defs.setAttribute('data-graph-surface', 'true');

  const shadow = createSvgEl('filter');
  shadow.setAttribute('id', 'graphNodeShadow');
  shadow.setAttribute('x', '-24%');
  shadow.setAttribute('y', '-24%');
  shadow.setAttribute('width', '148%');
  shadow.setAttribute('height', '148%');

  const dropShadow = createSvgEl('feDropShadow');
  dropShadow.setAttribute('dx', '0');
  dropShadow.setAttribute('dy', '10');
  dropShadow.setAttribute('stdDeviation', '10');
  dropShadow.setAttribute('flood-color', '#000000');
  dropShadow.setAttribute('flood-opacity', '0.16');
  shadow.appendChild(dropShadow);

  defs.appendChild(shadow);
  canvas.appendChild(defs);
}

function renderNodeSvg(canvas, node, position, cards, nodeFocus = null) {
  const isProcess = node.type === 'process';
  const card = isProcess
    ? cards.process
    : (node.depth === 0 ? cards.resourceRoot : cards.resourceDepth);
  const hasNodeFocus = Boolean(nodeFocus?.hasFocus);
  const isFocused = hasNodeFocus ? Boolean(nodeFocus?.focusedNodeIds?.has(node.id)) : true;
  const onlyResourcesOnHover = Boolean(nodeFocus?.onlyResourcesOnHover);
  const nodeOpacity = onlyResourcesOnHover && isProcess
    ? 0.02
    : (hasNodeFocus ? (isFocused ? 1 : 0.14) : 1);
  const nodeScale = hasNodeFocus
    ? (isFocused ? 1.04 : (onlyResourcesOnHover && isProcess ? 0.92 : 0.97))
    : 1;
  const label = humanizeLabel(node.label || node.id || 'Node');
  const subtitle = isProcess
    ? (Number.isFinite(Number(node.cpuPercent)) || Number.isFinite(Number(node.memoryPercent))
      ? `PID ${String(node.id || '').replace(/^live-/, '')} · CPU ${formatPercent(node.cpuPercent, 1)} · MEM ${formatPercent(node.memoryPercent, 1)}`
      : String(node.subtitle || '').slice(0, 44))
    : String(node.subtitle || '').slice(0, 44);
  const typeLabel = isProcess
    ? 'PROCESS'
    : (node.depth === 0 ? 'RESOURCE' : 'SUB-RESOURCE');

  const group = createSvgEl('g');
  const finalTransform = `translate(${position.x}, ${position.y}) scale(${nodeScale})`;
  const shouldAnimate = Boolean(nodeFocus?.animateLayout)
    && Number.isFinite(position?.fromX)
    && Number.isFinite(position?.fromY);
  if (shouldAnimate) {
    group.setAttribute('transform', `translate(${position.fromX}, ${position.fromY}) scale(0.72)`);
    group.style.transition = 'transform 400ms cubic-bezier(0.2, 0, 0, 1), opacity 400ms ease';
    group.style.willChange = 'transform, opacity';
  } else {
    group.setAttribute('transform', finalTransform);
    group.style.transition = 'none';
    group.style.willChange = 'auto';
  }
  group.setAttribute('data-node-id', node.id);
  group.setAttribute('data-node-type', node.type);
  group.setAttribute('data-resource-id', node.resourceGroup || node.id);
  group.setAttribute('opacity', shouldAnimate ? '0.01' : String(nodeOpacity));
  group.setAttribute('filter', 'url(#graphNodeShadow)');
  group.style.cursor = 'pointer';

  const body = createSvgEl('rect');
  body.setAttribute('x', `${-card.w / 2}`);
  body.setAttribute('y', `${-card.h / 2}`);
  body.setAttribute('rx', `${card.radius || 10}`);
  body.setAttribute('width', `${card.w}`);
  body.setAttribute('height', `${card.h}`);
  body.setAttribute('fill', '#04070d');
  body.setAttribute('stroke', isFocused ? '#dce3ee' : '#1f2937');
  body.setAttribute('stroke-width', isFocused ? '1.9' : '1');
  group.appendChild(body);

  const frame = createSvgEl('rect');
  frame.setAttribute('x', `${-card.w / 2 + 2}`);
  frame.setAttribute('y', `${-card.h / 2 + 2}`);
  frame.setAttribute('rx', `${Math.max(4, (card.radius || 10) - 2)}`);
  frame.setAttribute('width', `${card.w - 4}`);
  frame.setAttribute('height', `${card.h - 4}`);
  frame.setAttribute('fill', 'none');
  frame.setAttribute('stroke', 'rgba(255, 255, 255, 0.06)');
  frame.setAttribute('stroke-width', '1');
  group.appendChild(frame);

  const typeText = createSvgEl('text');
  typeText.setAttribute('x', `${card.w / 2 - 12}`);
  typeText.setAttribute('y', `${-card.h / 2 + 14}`);
  typeText.setAttribute('fill', '#98a3b8');
  typeText.setAttribute('font-size', '7.8');
  typeText.setAttribute('font-weight', '700');
  typeText.setAttribute('letter-spacing', '1.1');
  typeText.setAttribute('text-anchor', 'end');
  typeText.textContent = typeLabel;
  group.appendChild(typeText);

  const nameText = createSvgEl('text');
  nameText.setAttribute('x', `${-card.w / 2 + 10}`);
  nameText.setAttribute('y', `${-card.h / 2 + 24}`);
  nameText.setAttribute('fill', '#f8fafc');
  nameText.setAttribute('font-size', isProcess ? '12' : '11.2');
  nameText.setAttribute('font-weight', '600');
  nameText.setAttribute('letter-spacing', '0.18');
  nameText.textContent = label.slice(0, isProcess ? 22 : 19);
  group.appendChild(nameText);

  const subText = createSvgEl('text');
  subText.setAttribute('x', `${-card.w / 2 + 10}`);
  subText.setAttribute('y', `${-card.h / 2 + 40}`);
  subText.setAttribute('fill', '#98a3b8');
  subText.setAttribute('font-size', isProcess ? '8.6' : '8.9');
  subText.setAttribute('letter-spacing', '0.14');
  subText.textContent = subtitle;
  group.appendChild(subText);

  if (!isProcess) {
    const usageValue = Math.max(0, Math.min(100, Number(node.usage || 0)));
    const usageText = createSvgEl('text');
    usageText.setAttribute('x', `${card.w / 2 - 10}`);
    usageText.setAttribute('y', `${-card.h / 2 + 24}`);
    usageText.setAttribute('fill', '#f8fafc');
    usageText.setAttribute('font-size', '8.4');
    usageText.setAttribute('font-weight', '700');
    usageText.setAttribute('text-anchor', 'end');
    usageText.textContent = `${formatPercent(usageValue, 1)}`;
    group.appendChild(usageText);

    const usageBarBg = createSvgEl('rect');
    usageBarBg.setAttribute('x', `${-card.w / 2 + 10}`);
    usageBarBg.setAttribute('y', `${-card.h / 2 + card.h - 16}`);
    usageBarBg.setAttribute('rx', '3');
    usageBarBg.setAttribute('width', `${card.w - 20}`);
    usageBarBg.setAttribute('height', '4');
    usageBarBg.setAttribute('fill', '#1f2937');
    group.appendChild(usageBarBg);

    const usageBar = createSvgEl('rect');
    usageBar.setAttribute('x', `${-card.w / 2 + 10}`);
    usageBar.setAttribute('y', `${-card.h / 2 + card.h - 16}`);
    usageBar.setAttribute('rx', '3');
    usageBar.setAttribute('width', `${((card.w - 20) * usageValue) / 100}`);
    usageBar.setAttribute('height', '4');
    usageBar.setAttribute('fill', '#3b82f6');
    group.appendChild(usageBar);
  }

  const hitbox = createSvgEl('rect');
  hitbox.setAttribute('x', `${-card.w / 2 - 6}`);
  hitbox.setAttribute('y', `${-card.h / 2 - 6}`);
  hitbox.setAttribute('rx', `${card.radius || 10}`);
  hitbox.setAttribute('width', `${card.w + 12}`);
  hitbox.setAttribute('height', `${card.h + 12}`);
  hitbox.setAttribute('fill', 'transparent');
  hitbox.setAttribute('stroke', 'transparent');
  hitbox.setAttribute('pointer-events', 'all');
  group.appendChild(hitbox);

  canvas.appendChild(group);
  if (shouldAnimate) {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        group.setAttribute('transform', finalTransform);
        group.setAttribute('opacity', String(nodeOpacity));
      });
    });

    window.setTimeout(() => {
      group.setAttribute('opacity', String(nodeOpacity));
      group.style.willChange = 'auto';
    }, 460);
  }
}

function getNodeCard(node, cards) {
  if (!node) {
    return cards.process;
  }
  if (node.type === 'process') {
    return cards.process;
  }
  return node.depth === 0 ? cards.resourceRoot : cards.resourceDepth;
}

function edgeMatchesFilter(edge) {
  const filter = state.graphInteraction.filterResourceId;
  if (!filter || filter === 'ALL') {
    return true;
  }
  return edge.resourceId === filter;
}

function edgeFocusMultiplier(edge) {
  const { hoverProcessId } = state.graphInteraction;
  if (!hoverProcessId) {
    return 1;
  }

  const processMatch = hoverProcessId
    ? (edge.source === hoverProcessId || edge.target === hoverProcessId)
    : false;

  return processMatch ? 1 : 0.12;
}

function stableHash(value) {
  const text = String(value || '');
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) - h) + text.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function getRoundedRectBoundaryPoint(center, card, toward, padding = 0) {
  const dx = Number(toward.x - center.x || 0);
  const dy = Number(toward.y - center.y || 0);
  const halfW = (Number(card?.w || 0) / 2) + padding;
  const halfH = (Number(card?.h || 0) / 2) + padding;
  const cornerRadius = Math.max(0, Math.min(Number(card?.radius || 0), halfW, halfH));

  if (Math.abs(dx) < 0.0001 && Math.abs(dy) < 0.0001) {
    return { x: center.x + halfW, y: center.y };
  }

  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);
  const scaleX = absDx > 0.0001 ? (halfW / absDx) : Number.POSITIVE_INFINITY;
  const scaleY = absDy > 0.0001 ? (halfH / absDy) : Number.POSITIVE_INFINITY;
  const rectScale = Math.min(scaleX, scaleY);

  if (cornerRadius <= 0.001) {
    return {
      x: center.x + dx * rectScale,
      y: center.y + dy * rectScale,
    };
  }

  const px = dx * rectScale;
  const py = dy * rectScale;
  const innerW = Math.max(0, halfW - cornerRadius);
  const innerH = Math.max(0, halfH - cornerRadius);

  if (Math.abs(px) <= innerW + 0.0001 || Math.abs(py) <= innerH + 0.0001) {
    return {
      x: center.x + px,
      y: center.y + py,
    };
  }

  const sx = dx >= 0 ? 1 : -1;
  const sy = dy >= 0 ? 1 : -1;
  const cx = sx * innerW;
  const cy = sy * innerH;
  const a = (dx * dx) + (dy * dy);
  const b = -2 * ((dx * cx) + (dy * cy));
  const c = (cx * cx) + (cy * cy) - (cornerRadius * cornerRadius);
  const disc = Math.max(0, (b * b) - (4 * a * c));
  const sqrtDisc = Math.sqrt(disc);
  const t1 = (-b - sqrtDisc) / (2 * a);
  const t2 = (-b + sqrtDisc) / (2 * a);
  const t = [t1, t2]
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((m, n) => m - n)[0] || rectScale;

  return {
    x: center.x + dx * t,
    y: center.y + dy * t,
  };
}

function resolveBundlePoint(edge, source, target, nodeIndex, positions, sourceSlot = 0, targetSlot = 0) {
  if (edge.type === 'depth-link' || edge.type === 'contention') {
    return null;
  }

  const targetNode = nodeIndex.get(edge.target);
  const sourceNode = nodeIndex.get(edge.source);
  if (!targetNode || !sourceNode) {
    return null;
  }

  let resourceAnchor = target;
  if (targetNode.type === 'resource' && targetNode.depth === 1 && targetNode.parentId) {
    const parentPos = positions.get(targetNode.parentId);
    if (parentPos) {
      resourceAnchor = parentPos;
    }
  }

  const straightDistance = Math.hypot(resourceAnchor.x - source.x, resourceAnchor.y - source.y);
  if (straightDistance < 260) {
    return null;
  }

  const bundleStrength = edge.type === 'usage' ? 0.74 : 0.6;
  const dx = resourceAnchor.x - source.x;
  const dy = resourceAnchor.y - source.y;
  const dist = Math.max(1, Math.hypot(dx, dy));
  const tx = -dy / dist;
  const ty = dx / dist;
  const laneOffset = Number(RESOURCE_LANE_OFFSET[edge.resourceId] || 0);
  const sourceJitter = ((stableHash(edge.source) % 5) - 2) * 7;
  const targetJitter = ((stableHash(edge.target) % 5) - 2) * 5;
  const slotJitter = (sourceSlot * 3.6) + (targetSlot * 2.8);
  const mergedOffset = laneOffset + sourceJitter + targetJitter + slotJitter;
  return {
    x: source.x + ((resourceAnchor.x - source.x) * bundleStrength) + (tx * mergedOffset),
    y: source.y + ((resourceAnchor.y - source.y) * bundleStrength) + (ty * mergedOffset),
  };
}

function renderEdgeSvg(canvas, edge, source, target, cards, nodeIndex, positions, sourceSlot = 0, targetSlot = 0, nodeFocus = null) {
  const sourceNode = nodeIndex.get(edge.source);
  const targetNode = nodeIndex.get(edge.target);
  if (!sourceNode || !targetNode) {
    return;
  }

  const sourceCard = getNodeCard(sourceNode, cards);
  const targetCard = getNodeCard(targetNode, cards);

  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const nx = dx / distance;
  const ny = dy / distance;

  const bundle = resolveBundlePoint(edge, source, target, nodeIndex, positions, sourceSlot, targetSlot);
  const sourceAnchorTarget = bundle || target;
  const targetAnchorTarget = bundle || source;

  const sourceAnchor = getRoundedRectBoundaryPoint(source, sourceCard, sourceAnchorTarget, 0.6);
  const targetAnchor = getRoundedRectBoundaryPoint(target, targetCard, targetAnchorTarget, 0.6);

  const sourceX = sourceAnchor.x;
  const sourceY = sourceAnchor.y;
  const targetX = targetAnchor.x;
  const targetY = targetAnchor.y;

  const curve = Math.max(56, Math.min(148, distance * 0.36));
  const tangentX = -ny;
  const tangentY = nx;
  const slotOffset = (sourceSlot * 3.4) + (targetSlot * 2.2);
  const bX = bundle ? bundle.x + tangentX * slotOffset : ((sourceX + targetX) / 2 + tangentX * slotOffset);
  const bY = bundle ? bundle.y + tangentY * slotOffset : ((sourceY + targetY) / 2 + tangentY * slotOffset);
  const controlA = `${sourceX + ((bX - sourceX) * 0.7)} ${sourceY + ((bY - sourceY) * 0.7)}`;
  const controlB = `${targetX + ((bX - targetX) * 0.7)} ${targetY + ((bY - targetY) * 0.7)}`;

  const color = RESOURCE_COLORS[edge.resourceId] || '#9ca3af';
  if (nodeFocus?.onlyResourcesOnHover) {
    const hasResourceEndpoint = sourceNode.type === 'resource' || targetNode.type === 'resource';
    if (!hasResourceEndpoint) {
      return;
    }
    const highlightedResourceIds = nodeFocus.highlightedResourceIds;
    if (highlightedResourceIds && highlightedResourceIds.size > 0 && !highlightedResourceIds.has(edge.resourceId)) {
      return;
    }
  }
  const filteredIn = edgeMatchesFilter(edge);
  const focusMultiplier = edgeFocusMultiplier(edge);
  if (!filteredIn && focusMultiplier <= 0.12) {
    return;
  }

  const path = createSvgEl('path');
  path.setAttribute('d', `M ${sourceX} ${sourceY} C ${controlA}, ${controlB}, ${targetX} ${targetY}`);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', color);
  const intensity = Math.max(0, Math.min(1, Number(edge.intensity) || 0));
  const edgeWidth = edge.type === 'depth-link'
    ? 1.0
    : (edge.type === 'usage' ? 2.35 : (edge.type === 'contention' ? 1.5 : 1.8));
  const baseOpacity = edge.type === 'depth-link'
    ? 0.12
    : (edge.type === 'usage'
      ? (0.24 + intensity * 0.24)
      : (edge.type === 'contention' ? (0.2 + intensity * 0.16) : (0.22 + intensity * 0.18)));
  const filteredOpacity = filteredIn ? baseOpacity : 0.05;
  const edgeOpacity = filteredOpacity * focusMultiplier;
  path.setAttribute('stroke-width', String(edgeWidth));
  path.setAttribute('opacity', String(edgeOpacity));
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('pointer-events', 'none');
  canvas.appendChild(path);
}

function renderGraphGuides(canvas, graphWidth, graphHeight, processCount, layoutMetrics) {
  const centerX = graphWidth / 2;
  const centerY = graphHeight / 2;
  const resourceRingRadii = Array.isArray(layoutMetrics?.resourceRingRadii)
    ? layoutMetrics.resourceRingRadii
    : (Array.isArray(layoutMetrics?.depthRadii)
      ? layoutMetrics.depthRadii
      : []);
  const processRingRadii = Array.isArray(layoutMetrics?.processRingRadii)
    ? layoutMetrics.processRingRadii
    : [];

  const guideLayer = createSvgEl('g');
  guideLayer.setAttribute('opacity', '1');

  for (const r of resourceRingRadii) {
    const ringGuide = createSvgEl('circle');
    ringGuide.setAttribute('cx', `${centerX}`);
    ringGuide.setAttribute('cy', `${centerY}`);
    ringGuide.setAttribute('r', `${r}`);
    ringGuide.setAttribute('fill', 'none');
    ringGuide.setAttribute('stroke', 'rgba(0, 0, 0, 0.08)');
    ringGuide.setAttribute('stroke-width', '1');
    guideLayer.appendChild(ringGuide);
  }

  for (const radius of processRingRadii) {
    const loop = createSvgEl('circle');
    loop.setAttribute('cx', `${centerX}`);
    loop.setAttribute('cy', `${centerY}`);
    loop.setAttribute('r', `${radius}`);
    loop.setAttribute('fill', 'none');
    loop.setAttribute('stroke', 'rgba(0, 0, 0, 0.08)');
    loop.setAttribute('stroke-width', '1');
    guideLayer.appendChild(loop);
  }

  canvas.appendChild(guideLayer);
}

function setHoverProcess(nextProcessId) {
  const normalized = nextProcessId || null;
  if (state.graphInteraction.hoverProcessId === normalized) {
    return;
  }
  state.graphInteraction.hoverProcessId = normalized;
  scheduleGraphFrame(true);
}

function renderGraphScene(canvas, sourceGraph, graphWidth, graphHeight) {
  const { positions, cards, layoutMetrics } = layoutGraphNodes(sourceGraph.nodes || [], graphWidth, graphHeight);
  const nodeIndex = new Map((sourceGraph.nodes || []).map((node) => [node.id, node]));
  const layoutSignature = (sourceGraph.nodes || [])
    .map((node) => {
      const pos = positions.get(node.id);
      if (!pos) {
        return `${node.id}:na`;
      }
      return `${node.id}:${Math.round(pos.x)}:${Math.round(pos.y)}`;
    })
    .sort()
    .join('|');
  const animateLayout = state.graphLayoutCache.layoutSignature !== layoutSignature;
  state.graphLayoutCache.layoutSignature = layoutSignature;
  if (state.graphInteraction.hoverProcessId && !nodeIndex.has(state.graphInteraction.hoverProcessId)) {
    state.graphInteraction.hoverProcessId = null;
  }
  const focusedNodeIds = new Set();
  const highlightedResourceIds = new Set();
  const { hoverProcessId, hoverResourceId, selectedProcessId, selectedResourceId } = state.graphInteraction;

  const focusProcessId = hoverProcessId || selectedProcessId || null;
  const focusResourceId = hoverResourceId || selectedResourceId || null;
  const onlyResourcesOnHover = Boolean(hoverResourceId);
  if (focusProcessId || focusResourceId) {
    for (const edge of sourceGraph.edges || []) {
      const processHit = focusProcessId
        ? (edge.source === focusProcessId || edge.target === focusProcessId)
        : false;
      const resourceHit = focusResourceId
        ? edge.resourceId === focusResourceId
        : false;

      if (processHit || resourceHit) {
        focusedNodeIds.add(edge.source);
        focusedNodeIds.add(edge.target);
        if (edge.resourceId) {
          highlightedResourceIds.add(edge.resourceId);
        }
      }
    }

    if (focusProcessId) {
      focusedNodeIds.add(focusProcessId);
    }
    if (focusResourceId) {
      highlightedResourceIds.add(focusResourceId);
      for (const node of sourceGraph.nodes || []) {
        if (node.id === focusResourceId || node.resourceGroup === focusResourceId || node.parentId === focusResourceId) {
          focusedNodeIds.add(node.id);
        }
      }
    }

    if (onlyResourcesOnHover) {
      focusedNodeIds.clear();
      for (const node of sourceGraph.nodes || []) {
        if (node.type !== 'resource') {
          continue;
        }
        const resourceId = node.resourceGroup || node.id;
        if (highlightedResourceIds.size === 0 || highlightedResourceIds.has(resourceId)) {
          focusedNodeIds.add(node.id);
        }
      }
    }
  }

  const nodeFocus = {
    hasFocus: focusedNodeIds.size > 0,
    focusedNodeIds,
    onlyResourcesOnHover,
    highlightedResourceIds,
    animateLayout,
  };

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const node of sourceGraph.nodes || []) {
    const position = positions.get(node.id);
    if (!position) {
      continue;
    }
    const card = getNodeCard(node, cards);
    minX = Math.min(minX, position.x - card.w / 2);
    minY = Math.min(minY, position.y - card.h / 2);
    maxX = Math.max(maxX, position.x + card.w / 2);
    maxY = Math.max(maxY, position.y + card.h / 2);
  }

  canvas.innerHTML = '';
  ensureGraphSurfaceDefs(canvas);
  const zoomScale = clampScale(Number(state.graphView?.scale || 1));
  const hasBounds = Number.isFinite(minX) && Number.isFinite(minY) && Number.isFinite(maxX) && Number.isFinite(maxY);
  const fitPadding = 148;
  const fallbackWidth = Math.max(1, graphWidth);
  const fallbackHeight = Math.max(1, graphHeight);

  let baseWidth = hasBounds ? Math.max(1, (maxX - minX) + fitPadding * 2) : fallbackWidth;
  let baseHeight = hasBounds ? Math.max(1, (maxY - minY) + fitPadding * 2) : fallbackHeight;
  let baseCenterX = hasBounds ? (minX + maxX) / 2 : graphWidth / 2;
  let baseCenterY = hasBounds ? (minY + maxY) / 2 : graphHeight / 2;

  const viewportAspect = fallbackWidth / fallbackHeight;
  const baseAspect = baseWidth / baseHeight;
  if (baseAspect > viewportAspect) {
    baseHeight = baseWidth / viewportAspect;
  } else {
    baseWidth = baseHeight * viewportAspect;
  }

  const zoomWidth = baseWidth / zoomScale;
  const zoomHeight = baseHeight / zoomScale;
  const maxPanX = Math.max(0, (baseWidth - zoomWidth) / 2);
  const maxPanY = Math.max(0, (baseHeight - zoomHeight) / 2);
  const panX = Math.max(-maxPanX, Math.min(maxPanX, Number(state.graphView?.x || 0)));
  const panY = Math.max(-maxPanY, Math.min(maxPanY, Number(state.graphView?.y || 0)));
  state.graphView.x = panX;
  state.graphView.y = panY;

  const zoomX = (baseCenterX - panX) - (zoomWidth / 2);
  const zoomY = (baseCenterY - panY) - (zoomHeight / 2);

  canvas.setAttribute('viewBox', `${zoomX} ${zoomY} ${zoomWidth} ${zoomHeight}`);
  canvas.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  canvas.style.pointerEvents = 'auto';

  const processCount = (sourceGraph.nodes || []).filter((node) => node.type === 'process').length;
  renderGraphGuides(canvas, graphWidth, graphHeight, processCount, layoutMetrics);

  const sortedEdges = [...(sourceGraph.edges || [])].sort((a, b) => {
    if (a.type === 'depth-link' && b.type !== 'depth-link') {
      return -1;
    }
    if (a.type !== 'depth-link' && b.type === 'depth-link') {
      return 1;
    }
    return 0;
  });

  const sourceGroups = new Map();
  const targetGroups = new Map();
  for (const edge of sortedEdges) {
    const sourceKey = edge.source;
    const targetKey = edge.target;
    if (!sourceGroups.has(sourceKey)) {
      sourceGroups.set(sourceKey, []);
    }
    if (!targetGroups.has(targetKey)) {
      targetGroups.set(targetKey, []);
    }
    sourceGroups.get(sourceKey).push(edge);
    targetGroups.get(targetKey).push(edge);
  }

  for (const edge of sortedEdges) {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) {
      continue;
    }

    const sourceList = sourceGroups.get(edge.source) || [];
    const targetList = targetGroups.get(edge.target) || [];
    const sourceSlot = sourceList.indexOf(edge) - (sourceList.length - 1) / 2;
    const targetSlot = targetList.indexOf(edge) - (targetList.length - 1) / 2;

    renderEdgeSvg(canvas, edge, source, target, cards, nodeIndex, positions, sourceSlot, targetSlot, nodeFocus);
  }

  for (const node of sourceGraph.nodes || []) {
    const position = positions.get(node.id);
    if (!position) {
      continue;
    }
    renderNodeSvg(canvas, node, position, cards, nodeFocus);
  }

  const groups = canvas.querySelectorAll('g[data-node-id]');
  groups.forEach((groupEl) => {
    const nodeId = groupEl.getAttribute('data-node-id');
    const nodeType = groupEl.getAttribute('data-node-type');
    const resourceId = groupEl.getAttribute('data-resource-id');
    if (!nodeId) {
      return;
    }

    groupEl.addEventListener('mouseenter', () => {
      if (nodeType === 'process') {
        setHoverProcess(nodeId);
      } else {
        // Resource hover highlight is intentionally disabled.
      }
    });

    groupEl.addEventListener('mouseleave', () => {
      if (nodeType === 'process') {
        if (state.graphInteraction.hoverProcessId === nodeId) {
          setHoverProcess(null);
        }
      } else {
        // Resource hover highlight is intentionally disabled.
      }
    });

    groupEl.addEventListener('click', (event) => {
      event.stopPropagation();
      if (nodeType === 'process') {
        state.graphInteraction.selectedProcessId = nodeId;
        state.graphInteraction.selectedResourceId = null;
      } else {
        state.graphInteraction.selectedResourceId = resourceId || nodeId;
        state.graphInteraction.selectedProcessId = null;
      }
      state.taskManagerOpen = true;
      renderTaskManager();
      scheduleGraphFrame(true);
    });
  });
}

function applyGraphViewportTransform() {
  const viewport = el('sceneViewport');
  if (!viewport) {
    return;
  }
  viewport.style.transform = 'translate(0px, 0px)';
}

function renderGraphFromSnapshot() {
  const graphCanvas = el('ipcGraphCanvas');
  const graphViewport = el('graphViewport');
  const snapshot = state.graphSnapshot;
  if (!graphCanvas || !snapshot) {
    return false;
  }

  const viewportWidth = Number(graphViewport?.clientWidth || graphCanvas.clientWidth || 0);
  const viewportHeight = Number(graphViewport?.clientHeight || graphCanvas.clientHeight || 0);
  const expectedWidth = Math.max(1200, viewportWidth || 1200);
  const expectedHeight = Math.max(860, viewportHeight || 860);
  if (Math.abs(Number(snapshot.width || 0) - expectedWidth) > 1 || Math.abs(Number(snapshot.height || 0) - expectedHeight) > 1) {
    return false;
  }

  renderGraphScene(graphCanvas, snapshot, Number(snapshot.width), Number(snapshot.height));
  return true;
}

function scheduleGraphFrame(preferSnapshot = true) {
  if (state.graphFramePending) {
    return;
  }

  state.graphFramePending = true;
  window.requestAnimationFrame(() => {
    state.graphFramePending = false;
    if (preferSnapshot && renderGraphFromSnapshot()) {
      return;
    }
    renderGraph();
  });
}

function resetGraphView() {
  state.graphView.scale = 1;
  state.graphView.x = 0;
  state.graphView.y = 0;
  applyGraphViewportTransform();
  scheduleGraphFrame(true);
}

function clampScale(nextScale) {
  return Math.max(0.5, Math.min(2.1, nextScale));
}

function initGraphInteraction() {
  const viewport = el('sceneViewport');
  const graphCanvas = el('ipcGraphCanvas');
  if (!viewport) {
    return;
  }
  const allowPan = true;
  viewport.classList.add('cursor-grab');

  viewport.addEventListener('mousedown', (event) => {
    if (!allowPan) {
      return;
    }
    if (event.button !== 0) {
      return;
    }
    const target = event.target;
    if (target instanceof Element && target.closest('button, input, select, textarea, a, #taskManagerPanel')) {
      return;
    }
    event.preventDefault();
    state.graphView.isPanning = true;
    state.graphView.startX = event.clientX - state.graphView.x;
    state.graphView.startY = event.clientY - state.graphView.y;
    document.body.classList.add('is-panning');
    viewport.classList.remove('cursor-grab');
    viewport.classList.add('cursor-grabbing');
  });

  window.addEventListener('mousemove', (event) => {
    if (!allowPan) {
      return;
    }
    if (!state.graphView.isPanning) {
      return;
    }
    event.preventDefault();
    state.graphView.x = event.clientX - state.graphView.startX;
    state.graphView.y = event.clientY - state.graphView.startY;
    applyGraphViewportTransform();
    if (!renderGraphFromSnapshot()) {
      renderGraph();
    }
  });

  if (graphCanvas) {
    graphCanvas.addEventListener('mousemove', (event) => {
      if (state.graphView.isPanning) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      const processNode = target.closest('g[data-node-type="process"]');
      const processId = processNode?.getAttribute('data-node-id') || null;
      setHoverProcess(processId);
    });

    graphCanvas.addEventListener('mouseleave', () => {
      setHoverProcess(null);
    });
  }

  window.addEventListener('mouseup', () => {
    if (!allowPan) {
      return;
    }
    if (!state.graphView.isPanning) {
      return;
    }
    state.graphView.isPanning = false;
    document.body.classList.remove('is-panning');
    viewport.classList.remove('cursor-grabbing');
    viewport.classList.add('cursor-grab');
    setHoverProcess(null);
  });

  window.addEventListener('blur', () => {
    if (!state.graphView.isPanning) {
      return;
    }
    state.graphView.isPanning = false;
    document.body.classList.remove('is-panning');
    viewport.classList.remove('cursor-grabbing');
    viewport.classList.add('cursor-grab');
  });

  viewport.addEventListener(
    'wheel',
    (event) => {
      event.preventDefault();
      const delta = event.deltaY > 0 ? -0.08 : 0.08;
      state.graphView.scale = clampScale(state.graphView.scale + delta);
      applyGraphViewportTransform();
      if (!renderGraphFromSnapshot()) {
        renderGraph();
      }
    },
    { passive: false },
  );

  viewport.addEventListener('dblclick', () => {
    resetGraphView();
  });

  applyGraphViewportTransform();
}

function renderGraph() {
  const graph = state.sim?.graph;
  const liveProcesses = state.liveEnabled && Array.isArray(state.live?.processes)
    ? state.live.processes
    : [];
  const graphCanvas = el('ipcGraphCanvas');
  const graphContainer = el('graphContainer');

  if (!graphCanvas) {
    return;
  }

  if (!graph && liveProcesses.length === 0 && !Array.isArray(state.sim?.processes)) {
    return;
  }

  if (state.graphMinimized) {
    graphCanvas.innerHTML = '';
    if (graphContainer) {
      graphContainer.style.opacity = '0.3';
      graphContainer.style.pointerEvents = 'none';
    }
    return;
  } else {
    if (graphContainer) {
      graphContainer.style.opacity = '1';
      graphContainer.style.pointerEvents = 'auto';
    }
  }

  const fallbackProcesses = Array.isArray(state.sim?.processes)
    ? state.sim.processes.map((proc, idx) => ({
      pid: proc.pid || idx + 1,
      name: proc.name || `PROC_${idx + 1}`,
      cpuPercent: Number(proc.cpuPercent || (idx + 1) * 7),
      memoryPercent: Number(proc.memoryPercent || 18 + idx * 4),
      ioPercent: Number(proc.ioPercent || 8 + idx * 3),
      networkPercent: Number(proc.networkPercent || 6 + idx * 2),
      threads: Number(proc.threads || 2 + (idx % 6)),
    }))
    : [];

  const processFeed = state.liveEnabled
    ? liveProcesses
    : fallbackProcesses;
  const graphViewport = el('graphViewport');
  const viewportWidth = Number(graphViewport?.clientWidth || graphCanvas.clientWidth || Number(graph?.width) || 0);
  const viewportHeight = Number(graphViewport?.clientHeight || graphCanvas.clientHeight || Number(graph?.height) || 0);
  const graphWidth = Math.max(1200, viewportWidth || 1200);
  const graphHeight = Math.max(860, viewportHeight || 860);
  const sourceGraph = buildLiveGraph(processFeed, graphWidth, graphHeight);
  state.graphSnapshot = sourceGraph;
  renderGraphScene(graphCanvas, sourceGraph, graphWidth, graphHeight);
}

function renderMetrics() {
  const simProcesses = Array.isArray(state.sim?.processes) ? state.sim.processes : [];
  const liveProcesses = Array.isArray(state.live?.processes) ? state.live.processes : [];
  const activeProcesses = state.liveEnabled ? liveProcesses : simProcesses;
  const top = [...activeProcesses].sort((a, b) => Number(b.cpuPercent || 0) - Number(a.cpuPercent || 0));
  const first = top[0];
  const second = top[1];

  setText('managerStatus', first ? 'Active' : 'Idle');
  setText('managerPrimaryName', first ? humanizeLabel(first.name) : 'No Process');
  setText('managerPrimaryPid', first ? String(first.pid) : '---');
  setText('managerPrimaryCpu', first ? formatPercent(first.cpuPercent, 1) : '0.0%');
  setText('managerSecondaryName', second ? humanizeLabel(second.name) : 'No Process');
  setText('managerSecondaryPid', second ? String(second.pid) : '---');
  setText('managerSecondaryCpu', second ? formatPercent(second.cpuPercent, 1) : '0.0%');

  const totalThreads = activeProcesses.reduce((sum, process) => sum + Number(process.threads || 0), 0);
  const memPercent = state.liveEnabled
    ? Number(state.live?.host?.memoryPercent || 0)
    : Number((top.reduce((acc, row) => acc + Number(row.memoryPercent || 0), 0) / Math.max(1, top.length)) || 0);
  const diskPercent = state.liveEnabled
    ? Number(state.live?.resources?.disk?.usedPercent || 0)
    : Number((top.reduce((acc, row) => acc + Number(row.ioPercent || 0), 0) / Math.max(1, top.length)) || 0);
  const netPercent = state.liveEnabled
    ? Number(state.live?.resources?.network?.usedPercent || 0)
    : Number((top.reduce((acc, row) => acc + Number(row.networkPercent || 0), 0) / Math.max(1, top.length)) || 0);
  const cpuPercent = state.liveEnabled
    ? Number(state.live?.resources?.cpu?.usedPercent || 0)
    : Number((top.reduce((acc, row) => acc + Number(row.cpuPercent || 0), 0) / Math.max(1, top.length)) || 0);
  const latency = Math.max(20, Math.round(220 - cpuPercent * 1.6));

  pushHistory('threads', totalThreads);
  pushHistory('memory', memPercent);
  pushHistory('disk', diskPercent);
  pushHistory('network', netPercent);
  pushHistory('latency', latency);

  setText('threadCountValue', `${totalThreads.toLocaleString()} active`);
  setText('managerStatus', state.liveEnabled ? formatLiveAge(state.live?.ts) : 'Simulation');
  setSparkline('threadSparkline', state.history.threads);

  setText('memoryFragmentationValue', formatPercent(memPercent * 0.8, 1));
  setBar('memoryFragmentationBar', memPercent * 0.8);

  const diskReadBps = Number(state.live?.resources?.disk?.readBps || 0);
  const diskWriteBps = Number(state.live?.resources?.disk?.writeBps || 0);
  const totalDiskBps = state.liveEnabled ? (diskReadBps + diskWriteBps) : (diskPercent * 2.2 * 1024 * 1024);
  setText('diskIoValue', formatSpeed(totalDiskBps / (1024 * 1024)));
  setSparkline('diskIoSparkline', state.history.disk);

  setText('swapUsageValue', formatBytes((state.live?.host?.totalMemory || 0) * (memPercent / 100) * 0.45));
  setBar('swapUsageBar', memPercent * 0.9);

  const tempC = Number(state.live?.resources?.temperature?.celsius || 0);
  setText('interruptLatencyValue', state.liveEnabled && tempC > 0 ? `${tempC.toFixed(1)} C` : `${latency} μs`);
  setSparkline('interruptLatencySparkline', state.history.latency);

  const netBytesPerSec = Number(state.live?.resources?.network?.bytesPerSec || 0);
  const netGbps = state.liveEnabled
    ? ((netBytesPerSec * 8) / 1_000_000_000)
    : (netPercent * 0.16);
  setText('socketThroughputValue', `${netGbps.toFixed(1)} Gbps`);
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

  banner.className = 'absolute top-8 left-1/2 -translate-x-1/2 bg-surface-container-low text-on-surface px-4 py-1 text-[10px] tracking-tighter uppercase font-bold flex items-center gap-2 border border-outline-variant z-40 rounded-full shadow-lg hidden';
  setText('criticalBannerText', '');
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
  const manualControls = el('manualControlsGroup');
  const controlBar = el('controlBar');
  const liveIntentEnabled = state.liveEnabled;
  if (liveButton && liveText) {
    liveText.textContent = liveIntentEnabled ? 'Live Mode: On' : 'Live Mode: Off';
    liveButton.className = liveIntentEnabled
      ? 'dock-btn dock-btn-live is-on'
      : 'dock-btn dock-btn-live is-off';
  }

  if (manualControls && controlBar) {
    manualControls.classList.toggle('is-collapsed', liveIntentEnabled);
    controlBar.classList.toggle('manual-hidden', liveIntentEnabled);
  }

  const minimizeButton = el('minimizeGraphButton');
  if (minimizeButton) {
    const icon = minimizeButton.querySelector('span:first-child');
    const text = minimizeButton.querySelector('span:last-child');
    if (icon) {
      icon.textContent = state.taskManagerOpen ? 'close' : 'task_alt';
    }
    if (text) {
      text.textContent = state.taskManagerOpen ? 'Close' : 'Tasks';
    }
  }
}

function triggerModeTransition() {
  const controlBar = el('controlBar');
  const graphContainer = el('graphContainer');

  if (controlBar) {
    controlBar.classList.remove('mode-switching');
    void controlBar.offsetWidth;
    controlBar.classList.add('mode-switching');
  }

  if (graphContainer) {
    graphContainer.classList.remove('mode-switching');
    void graphContainer.offsetWidth;
    graphContainer.classList.add('mode-switching');
  }

  if (state.modeTransitionTimer) {
    clearTimeout(state.modeTransitionTimer);
  }
  state.modeTransitionTimer = setTimeout(() => {
    controlBar?.classList.remove('mode-switching');
    graphContainer?.classList.remove('mode-switching');
    state.modeTransitionTimer = null;
  }, 380);
}

function setLiveMode(enabled, animate = true) {
  const next = Boolean(enabled);
  if (state.liveEnabled === next) {
    return false;
  }

  state.liveEnabled = next;

  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send(JSON.stringify({ type: 'live:mode', enabled: state.liveEnabled }));
  }

  if (animate) {
    triggerModeTransition();
  }

  return true;
}

function ensureGraphFilterControls() {
  const bar = el('graphFilterBar');
  if (bar) {
    bar.remove();
  }
}

function renderGraphFilterControls() {
  // Filter bar intentionally removed.
}

function renderLogOverlay() {
  if (!state.terminalOpen) {
    return;
  }

  const logs = Array.isArray(state.sim?.logs) ? state.sim.logs.slice(0, 3) : [];
  const text = logs.map((entry) => `${entry.time} ${String(entry.type || 'info').toUpperCase()} ${entry.message}`).join(' | ');
  setText('criticalBannerText', text || 'No recent events');
}

function renderTaskManager() {
  const panel = el('taskManagerPanel');
  const list = el('taskManagerList');
  const backdrop = el('taskManagerPanel');
  const slidePanel = el('taskManagerSheet');
  
  if (!panel || !list) {
    return;
  }

  if (state.taskManagerOpen) {
    backdrop.style.opacity = '1';
    backdrop.style.pointerEvents = 'auto';
    if (slidePanel) {
      slidePanel.style.transform = 'translateX(0)';
      slidePanel.style.opacity = '1';
    }
  } else {
    backdrop.style.opacity = '0';
    backdrop.style.pointerEvents = 'none';
    if (slidePanel) {
      slidePanel.style.transform = 'translateX(100%)';
      slidePanel.style.opacity = '0.92';
    }
  }

  // Get all processes from live mode
  const liveProcesses = Array.isArray(state.live?.processes) ? state.live.processes : [];
  const simProcesses = Array.isArray(state.sim?.processes) ? state.sim.processes : [];
  const allProcesses = [
    ...liveProcesses.map(p => ({ ...p, source: 'live' })),
    ...simProcesses.filter(sp => !liveProcesses.find(lp => lp.pid === sp.pid)).map(p => ({ ...p, source: 'sim' }))
  ];
  
  // Sort by CPU usage
  allProcesses.sort((a, b) => Number(b.cpuPercent || 0) - Number(a.cpuPercent || 0));

  const selectedProcessId = state.graphInteraction.selectedProcessId;
  const selectedResourceId = state.graphInteraction.selectedResourceId;
  const graphNodes = state.graphSnapshot?.nodes || [];
  const graphEdges = state.graphSnapshot?.edges || [];

  if (selectedProcessId) {
    const pid = Number(String(selectedProcessId).replace('live-', ''));
    const process = allProcesses.find((row) => Number(row.pid) === pid);
    const connections = graphEdges
      .filter((edge) => edge.source === selectedProcessId && edge.type !== 'depth-link')
      .map((edge) => {
        const targetNode = graphNodes.find((node) => node.id === edge.target);
        return {
          label: targetNode?.label || edge.target,
          resourceId: edge.resourceId,
          intensity: Math.round((Number(edge.intensity || 0) * 100)),
        };
      });

    list.innerHTML = `
      <div class="bg-surface-container-lowest border border-outline-variant/20 rounded-lg p-4">
        <div class="text-xs font-bold text-on-surface">${String(process?.name || selectedProcessId).toUpperCase()}</div>
        <div class="text-[10px] text-on-surface-variant mt-1">PID ${process?.pid || 'N/A'} · CPU ${(Number(process?.cpuPercent || 0)).toFixed(1)}% · MEM ${(Number(process?.memoryPercent || 0)).toFixed(1)}%</div>
      </div>
      <div class="text-[10px] uppercase tracking-wider text-on-surface-variant mt-2">Active Connections</div>
      ${connections.map((item) => `
        <div class="rounded-lg border border-outline-variant/20 bg-surface-container-lowest/90 p-3 mt-2">
          <div class="text-[11px] font-semibold text-on-surface">${item.label}</div>
          <div class="text-[10px] text-on-surface-variant mt-1">${item.resourceId} · ${item.intensity}% intensity</div>
        </div>
      `).join('') || '<div class="text-[10px] text-on-surface-variant mt-2">No active resource usage detected.</div>'}
    `;
    return;
  }

  if (selectedResourceId) {
    const consumers = graphEdges
      .filter((edge) => edge.resourceId === selectedResourceId && edge.source.startsWith('live-'))
      .map((edge) => edge.source);
    const uniqueConsumers = [...new Set(consumers)];
    const rows = uniqueConsumers
      .map((processId) => {
        const pid = Number(String(processId).replace('live-', ''));
        return allProcesses.find((row) => Number(row.pid) === pid);
      })
      .filter(Boolean)
      .sort((a, b) => Number(b.cpuPercent || 0) - Number(a.cpuPercent || 0));

    list.innerHTML = `
      <div class="bg-surface-container-lowest border border-outline-variant/20 rounded-lg p-4">
        <div class="text-xs font-bold text-on-surface">${selectedResourceId} Consumers</div>
        <div class="text-[10px] text-on-surface-variant mt-1">${rows.length} active processes using this resource</div>
      </div>
      ${rows.map((process) => `
        <div class="bg-surface-container-lowest border border-outline-variant/20 rounded-lg p-3 mt-2">
          <div class="text-xs font-bold text-on-surface">${String(process.name || 'PROCESS').toUpperCase()}</div>
          <div class="text-[10px] text-on-surface-variant mt-1">PID ${process.pid} · CPU ${(Number(process.cpuPercent || 0)).toFixed(1)}% · MEM ${(Number(process.memoryPercent || 0)).toFixed(1)}%</div>
        </div>
      `).join('') || '<div class="text-[10px] text-on-surface-variant mt-2">No process currently consuming this resource.</div>'}
    `;
    return;
  }

  list.innerHTML = allProcesses.map(process => `
    <div class="bg-surface-container-lowest border border-outline-variant/20 rounded-lg p-3 hover:bg-surface-container-low transition-colors">
      <div class="flex items-start justify-between mb-2">
        <div>
          <div class="text-xs font-bold text-on-surface">${String(process.name || 'PROCESS').toUpperCase()}</div>
          <div class="text-[10px] text-on-surface-variant">PID ${process.pid}</div>
        </div>
        <span class="text-[10px] px-2 py-1 rounded bg-primary-fixed text-on-primary-fixed">${process.state || 'running'}</span>
      </div>
      <div class="grid grid-cols-2 gap-2 mb-2">
        <div class="text-[10px]">
          <span class="text-on-surface-variant">CPU:</span>
          <span class="text-tertiary font-semibold ml-1">${(Number(process.cpuPercent || 0)).toFixed(1)}%</span>
        </div>
        <div class="text-[10px]">
          <span class="text-on-surface-variant">Memory:</span>
          <span class="text-tertiary font-semibold ml-1">${(Number(process.memoryPercent || 0)).toFixed(1)}%</span>
        </div>
        <div class="text-[10px]">
          <span class="text-on-surface-variant">I/O:</span>
          <span class="text-tertiary font-semibold ml-1">${(Number(process.ioPercent || 0)).toFixed(1)}%</span>
        </div>
        <div class="text-[10px]">
          <span class="text-on-surface-variant">Threads:</span>
          <span class="text-tertiary font-semibold ml-1">${process.threads || 0}</span>
        </div>
      </div>
      ${process.cpuCores ? `<div class="text-[10px] text-on-surface-variant">
        <span>Cores: </span><span class="font-mono text-tertiary">${process.cpuCores.join(', ')}</span>
      </div>` : ''}
    </div>
  `).join('');
}

function render() {
  ensureGraphFilterControls();
  renderGraph();
  renderMetrics();
  renderBanner();
  renderButtons();
  renderLogOverlay();
  renderTaskManager();
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
  setLiveMode(false);
  const payload = { priority: 1 + Math.floor(Math.random() * 5) };
  await fetchJson('/api/process', { method: 'POST', body: JSON.stringify(payload) });
  await refreshState();
}

async function addResource() {
  setLiveMode(false);
  const payload = { totalInstances: 1 + Math.floor(Math.random() * 3) };
  await fetchJson('/api/resource', { method: 'POST', body: JSON.stringify(payload) });
  await refreshState();
}

async function toggleSimulation() {
  setLiveMode(false);
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
  setLiveMode(!state.liveEnabled);
  render();
}

function toggleTaskManager() {
  state.taskManagerOpen = !state.taskManagerOpen;
  render();
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

  el('minimizeGraphButton')?.addEventListener('click', () => {
    try {
      toggleTaskManager();
    } catch (error) {
      window.alert(error.message || 'Could not toggle task manager');
    }
  });

  el('taskManagerClose')?.addEventListener('click', () => {
    state.taskManagerOpen = false;
    render();
  });

  el('taskManagerPanel')?.addEventListener('click', (e) => {
    if (e.target === el('taskManagerPanel')) {
      state.taskManagerOpen = false;
      render();
    }
  });

  el('resetGraphViewButton')?.addEventListener('click', () => {
    resetGraphView();
  });

  el('ipcGraphCanvas')?.addEventListener('click', (event) => {
    if (event.target && event.target !== el('ipcGraphCanvas')) {
      return;
    }
    state.graphInteraction.hoverProcessId = null;
    state.graphInteraction.hoverResourceId = null;
    state.graphInteraction.selectedProcessId = null;
    state.graphInteraction.selectedResourceId = null;
    renderGraph();
    renderTaskManager();
  });

  // Disable browser zoom so only the in-app zoom interaction is used.
  window.addEventListener(
    'wheel',
    (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
      }
    },
    { passive: false },
  );

  window.addEventListener('keydown', (event) => {
    if (!(event.ctrlKey || event.metaKey)) {
      return;
    }

    const key = String(event.key || '').toLowerCase();
    if (key === '+' || key === '-' || key === '=' || key === '_' || key === '0') {
      event.preventDefault();
    }
  });
}

async function init() {
  initGraphInteraction();
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
