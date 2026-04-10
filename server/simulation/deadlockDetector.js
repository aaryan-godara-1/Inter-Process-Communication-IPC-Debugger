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

function analyzeState(processes, resources) {
  const waitForGraph = buildWaitForGraph(processes, resources);
  const cycle = findCycle(waitForGraph);
  const safety = runBankersSafetyCheck(processes, resources);
  const waitingProcesses = processes.filter((process) => Object.keys(process.requestedResources).length > 0);
  const starvingProcesses = waitingProcesses.filter((process) => process.waitSteps >= STARVATION_THRESHOLD);

  let state = 'NORMAL';
  let detail = 'Normal execution';

  if (cycle.length > 0) {
    state = 'DEADLOCK';
    detail = `Deadlock cycle detected: ${cycle.join(' -> ')}`;
  } else if (!safety.safe) {
    state = 'UNSAFE';
    detail = 'Unsafe state detected by Banker\'s algorithm';
  } else if (starvingProcesses.length > 0) {
    state = 'WAITING';
    detail = `Starvation warning for ${starvingProcesses.map((process) => process.pid).join(', ')}`;
  } else if (waitingProcesses.length > 0) {
    state = 'WAITING';
    detail = 'One or more processes are waiting for resources';
  }

  return {
    state,
    detail,
    cycle,
    safeState: safety.safe,
    starvation: starvingProcesses.map((process) => process.pid),
    circularWait: cycle.length > 0,
    waitForGraph,
  };
}

module.exports = {
  analyzeState,
  buildWaitForGraph,
  findCycle,
  runBankersSafetyCheck,
};
