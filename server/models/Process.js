class Process {
  constructor({ pid, priority = 1 }) {
    this.pid = pid;
    this.state = 'running';
    this.heldResources = {};
    this.requestedResources = {};
    this.priority = priority;
    this.waitSteps = 0;
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
  }

  clearRequest(resourceId) {
    delete this.requestedResources[resourceId];
  }

  clearRequests() {
    this.requestedResources = {};
  }

  toJSON() {
    return {
      pid: this.pid,
      state: this.state,
      heldResources: { ...this.heldResources },
      requestedResources: { ...this.requestedResources },
      priority: this.priority,
      waitSteps: this.waitSteps,
    };
  }
}

module.exports = Process;
