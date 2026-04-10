class Resource {
  constructor({ resourceId, totalInstances = 1 }) {
    this.resourceId = resourceId;
    this.totalInstances = totalInstances;
    this.availableInstances = totalInstances;
    this.allocatedProcesses = {};
  }

  allocate(pid, amount = 1) {
    this.availableInstances -= amount;
    this.allocatedProcesses[pid] = (this.allocatedProcesses[pid] || 0) + amount;
  }

  release(pid, amount = 1) {
    const heldByProcess = this.allocatedProcesses[pid] || 0;
    const releaseAmount = Math.min(heldByProcess, amount);
    this.availableInstances += releaseAmount;
    const nextAmount = heldByProcess - releaseAmount;
    if (nextAmount <= 0) {
      delete this.allocatedProcesses[pid];
    } else {
      this.allocatedProcesses[pid] = nextAmount;
    }
    return releaseAmount;
  }

  toJSON() {
    return {
      resourceId: this.resourceId,
      totalInstances: this.totalInstances,
      availableInstances: this.availableInstances,
      allocatedProcesses: { ...this.allocatedProcesses },
    };
  }
}

module.exports = Resource;
