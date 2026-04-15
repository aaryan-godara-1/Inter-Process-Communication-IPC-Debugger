class Process {
  constructor({ pid, priority = 1 }) {
    this.pid = pid;
    this.state = 'running';
    this.heldResources = {};
    this.requestedResources = {};
    this.requestTimestamps = {}; // Track when each resource was requested
    this.priority = priority;
    this.waitSteps = 0;
    // CPU core assignments (0-indexed core IDs)
    this.cpuCores = [];
  }

  hold(resourceId, amount = 1) {
    this.heldResources[resourceId] = (this.heldResources[resourceId] || 0) + amount;
  }

  release(resourceId, amount = 1) {
    const nextAmount = Math.max(0, (this.heldResources[resourceId] || 0) - amount);
    if (nextAmount === 0) {
      delete this.heldResources[resourceId];
    } else {
      this.heldResources[resourceId] = nextAmount;
    }
  }

  request(resourceId, amount = 1) {
    this.requestedResources[resourceId] = amount;
    // Record the timestamp of when this request was made
    if (!this.requestTimestamps[resourceId]) {
      this.requestTimestamps[resourceId] = Date.now();
    }
  }

  clearRequest(resourceId) {
    delete this.requestedResources[resourceId];
    delete this.requestTimestamps[resourceId];
  }

  clearRequests() {
    this.requestedResources = {};
  }

  assignCpuCore(coreId) {
    if (!this.cpuCores.includes(coreId)) {
      this.cpuCores.push(coreId);
    }
  }

  releaseCpuCore(coreId) {
    const index = this.cpuCores.indexOf(coreId);
    if (index > -1) {
      this.cpuCores.splice(index, 1);
    }
  }

  toJSON() {
    return {
      pid: this.pid,
      state: this.state,
      heldResources: { ...this.heldResources },
      requestedResources: { ...this.requestedResources },
      requestTimestamps: { ...this.requestTimestamps },
      priority: this.priority,
      waitSteps: this.waitSteps,
      cpuCores: [...this.cpuCores],
    };
  }
}

module.exports = Process;
