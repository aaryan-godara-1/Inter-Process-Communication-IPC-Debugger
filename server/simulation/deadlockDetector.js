const STARVATION_THRESHOLD = 5;

function buildWaitForGraph(processes, resources) {
  const graph = {};

  for (const process of processes) {
    graph[process.pid] = new Set();
  }

  for (const process of processes) {
    for (const [resourceId, requestedAmount] of Object.entries(process.requestedResources)) {
      if (requestedAmount <= 0) {
        continue;
      }

      const resource = resources.find((entry) => entry.resourceId === resourceId);
      if (!resource) {
        continue;
      }

      for (const allocatedPid of Object.keys(resource.allocatedProcesses)) {
        if (allocatedPid !== process.pid) {
          graph[process.pid].add(allocatedPid);
        }
      }
    }
  }

  const finalGraph = {};
  for (const [pid, targets] of Object.entries(graph)) {
    finalGraph[pid] = Array.from(targets);
  }
  return finalGraph;
}

function findCycle(waitForGraph) {
  const visited = new Set();
  const active = new Set();
  const path = [];

  function dfs(node) {
    if (active.has(node)) {
      const startIndex = path.indexOf(node);
      return path.slice(startIndex).concat(node);
    }

    if (visited.has(node)) {
      return null;
    }

    visited.add(node);
    active.add(node);
    path.push(node);

    for (const neighbor of waitForGraph[node] || []) {
      const cycle = dfs(neighbor);
      if (cycle) {
        return cycle;
      }
    }

    active.delete(node);
    path.pop();
    return null;
  }

  for (const node of Object.keys(waitForGraph)) {
    const cycle = dfs(node);
    if (cycle) {
      return cycle;
    }
  }

  return [];
}

function runBankersSafetyCheck(processes, resources) {
  const available = resources.map((resource) => resource.availableInstances);
  const allocation = processes.map((process) =>
    resources.map((resource) => process.heldResources[resource.resourceId] || 0)
  );
  const need = processes.map((process) =>
    resources.map((resource) => process.requestedResources[resource.resourceId] || 0)
  );

  const finish = processes.map(() => false);
  const work = [...available];

  let progressed = true;
  while (progressed) {
    progressed = false;

    for (let i = 0; i < processes.length; i += 1) {
      if (finish[i]) {
        continue;
      }

      const canFinish = need[i].every((required, resourceIndex) => required <= work[resourceIndex]);
      if (canFinish) {
        for (let resourceIndex = 0; resourceIndex < work.length; resourceIndex += 1) {
          work[resourceIndex] += allocation[i][resourceIndex];
        }
        finish[i] = true;
        progressed = true;
      }
    }
  }

  return {
    safe: finish.every(Boolean),
    work,
  };
}

function detectBottleneck(processes, resources) {
  let best = null;

  for (const resource of resources) {
    const waitingProcesses = processes.filter((process) => (process.requestedResources[resource.resourceId] || 0) > 0);
    const holders = Object.keys(resource.allocatedProcesses || {});
    const saturation = resource.totalInstances > 0
      ? ((resource.totalInstances - resource.availableInstances) / resource.totalInstances)
      : 0;

    if (waitingProcesses.length === 0) {
      continue;
    }

    const score = (waitingProcesses.length * 2) + holders.length + (saturation >= 1 ? 1 : 0);
    if (!best || score > best.score) {
      best = {
        resourceId: resource.resourceId,
        waitingPids: waitingProcesses.map((process) => process.pid),
        holderPids: holders,
        queueDepth: waitingProcesses.length,
        saturation,
        score,
      };
    }
  }

  if (!best) {
    return null;
  }

  const isBottleneck = best.queueDepth >= 2 && best.saturation >= 0.95;
  return {
    detected: isBottleneck,
    resourceId: best.resourceId,
    waitingPids: best.waitingPids,
    holderPids: best.holderPids,
    queueDepth: best.queueDepth,
    saturation: best.saturation,
  };
}

function analyzeState(processes, resources) {
  const waitForGraph = buildWaitForGraph(processes, resources);
  const cycle = findCycle(waitForGraph);
  const safety = runBankersSafetyCheck(processes, resources);
  const bottleneck = detectBottleneck(processes, resources);
  const waitingProcesses = processes.filter((process) => Object.keys(process.requestedResources).length > 0);
  const starvingProcesses = waitingProcesses.filter((process) => process.waitSteps >= STARVATION_THRESHOLD);

  let state = 'NORMAL';
  let detail = 'Normal execution';
  let severity = 'low';
  let recommendation = 'Keep monitoring the system.';

  if (cycle.length > 0) {
    state = 'DEADLOCK';
    detail = `Deadlock cycle detected: ${cycle.join(' -> ')}`;
    severity = 'critical';
    recommendation = 'Break the circular wait by releasing one held resource.';
  } else if (!safety.safe) {
    state = 'UNSAFE';
    detail = 'Unsafe state detected by Banker\'s algorithm';
    severity = 'high';
    recommendation = 'Reduce concurrent allocation requests before continuing.';
  } else if (bottleneck?.detected) {
    state = 'WAITING';
    detail = `Bottleneck on ${bottleneck.resourceId}: ${bottleneck.queueDepth} processes queued`;
    severity = 'medium';
    recommendation = `Increase capacity or reduce contention on ${bottleneck.resourceId}.`;
  } else if (starvingProcesses.length > 0) {
    state = 'WAITING';
    detail = `Starvation warning for ${starvingProcesses.map((process) => process.pid).join(', ')}`;
    severity = 'medium';
    recommendation = 'Re-balance process priority or allocate additional resources.';
  } else if (waitingProcesses.length > 0) {
    state = 'WAITING';
    detail = 'One or more processes are waiting for resources';
    severity = 'low';
    recommendation = 'Observe queue growth before making scheduling changes.';
  } else {
    recommendation = 'System is healthy. Continue normal execution.';
  }

  const summaryByState = {
    DEADLOCK: 'Deadlock detected. Circular wait is blocking progress.',
    UNSAFE: 'Unsafe allocation pattern detected. Risk of deadlock is elevated.',
    WAITING: bottleneck?.detected
      ? `Bottleneck on ${bottleneck.resourceId}. ${bottleneck.queueDepth} process(es) waiting.`
      : 'Processes are waiting for resources. No circular wait detected.',
    NORMAL: 'System is stable. No contention risks detected.',
  };

  return {
    state,
    detail,
    ui: {
      severity,
      summary: summaryByState[state] || detail,
      recommendation,
    },
    cycle,
    safeState: safety.safe,
    starvation: starvingProcesses.map((process) => process.pid),
    circularWait: cycle.length > 0,
    bottleneck,
    waitForGraph,
  };
}

module.exports = {
  analyzeState,
  buildWaitForGraph,
  findCycle,
  runBankersSafetyCheck,
};
