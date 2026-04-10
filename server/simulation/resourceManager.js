const Resource = require('../models/Resource');

class ResourceManager {
  constructor() {
    this.reset();
  }

  reset() {
    this.resources = [];
    this.resourceMap = new Map();
    this.resourceCounter = 1;
  }

  createResource({ resourceId, totalInstances = 1 } = {}) {
    const nextResourceId = resourceId || `R${this.resourceCounter++}`;
    if (this.resourceMap.has(nextResourceId)) {
      throw new Error(`Resource ${nextResourceId} already exists`);
    }

    const resource = new Resource({ resourceId: nextResourceId, totalInstances: Math.max(1, Number(totalInstances) || 1) });
    this.resources.push(resource);
    this.resourceMap.set(nextResourceId, resource);
    return resource;
  }

  getResource(resourceId) {
    return this.resourceMap.get(resourceId);
  }

  listResources() {
    return this.resources;
  }

  allocate(pid, resourceId, amount = 1) {
    const resource = this.getResource(resourceId);
    if (!resource) {
      throw new Error(`Resource ${resourceId} does not exist`);
    }
    if (resource.availableInstances < amount) {
      return false;
    }
    resource.allocate(pid, amount);
    return true;
  }

  release(pid, resourceId, amount = 1) {
    const resource = this.getResource(resourceId);
    if (!resource) {
      throw new Error(`Resource ${resourceId} does not exist`);
    }
    return resource.release(pid, amount);
  }

  getAllocationMatrix(processes) {
    return processes.map((process) =>
      this.resources.map((resource) => process.heldResources[resource.resourceId] || 0)
    );
  }

  getRequestMatrix(processes) {
    return processes.map((process) =>
      this.resources.map((resource) => process.requestedResources[resource.resourceId] || 0)
    );
  }

  getAvailableVector() {
    return this.resources.map((resource) => resource.availableInstances);
  }

  toJSON() {
    return this.resources.map((resource) => resource.toJSON());
  }
}

module.exports = ResourceManager;
