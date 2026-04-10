function buildGraph(processes, resources, analysis) {
  const processCount = processes.length;
  const resourceCount = resources.length;
  const spacing = 92;
  const topPadding = 70;
  const leftX = 160;
  const rightX = 760;
  const height = Math.max(processCount, resourceCount, 1) * spacing + topPadding * 2;
  const cycleSet = new Set(analysis.cycle || []);

  const nodes = [];
  processes.forEach((process, index) => {
    const hasRequest = Object.keys(process.requestedResources).length > 0;
    const status = cycleSet.has(process.pid)
      ? 'deadlock'
      : process.state === 'blocked' || hasRequest
        ? 'waiting'
        : 'running';

    nodes.push({
      id: process.pid,
      label: process.pid,
      type: 'process',
      x: leftX,
      y: topPadding + index * spacing,
      status,
      subtitle: `Priority ${process.priority}`,
    });
  });

  resources.forEach((resource, index) => {
    nodes.push({
      id: resource.resourceId,
      label: resource.resourceId,
      type: 'resource',
      x: rightX,
      y: topPadding + index * spacing,
      status: resource.availableInstances > 0 ? 'available' : 'full',
      subtitle: `${resource.availableInstances} / ${resource.totalInstances}`,
    });
  });

  const processIndex = new Map(processes.map((process) => [process.pid, process]));
  const resourceIndex = new Map(resources.map((resource) => [resource.resourceId, resource]));
  const edges = [];

  for (const process of processes) {
    for (const [resourceId, amount] of Object.entries(process.requestedResources)) {
      if (amount <= 0 || !resourceIndex.has(resourceId)) {
        continue;
      }

      edges.push({
        id: `${process.pid}->${resourceId}:request`,
        source: process.pid,
        target: resourceId,
        type: 'request',
        amount,
        highlighted: cycleSet.has(process.pid),
      });
    }
  }

  for (const resource of resources) {
    for (const [pid, amount] of Object.entries(resource.allocatedProcesses)) {
      if (!processIndex.has(pid)) {
        continue;
      }

      edges.push({
        id: `${resource.resourceId}->${pid}:allocation`,
        source: resource.resourceId,
        target: pid,
        type: 'allocation',
        amount,
        highlighted: cycleSet.has(pid),
      });
    }
  }

  return {
    width: 940,
    height,
    nodes,
    edges,
  };
}

module.exports = {
  buildGraph,
};
