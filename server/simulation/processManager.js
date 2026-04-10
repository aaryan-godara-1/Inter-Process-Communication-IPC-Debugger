const Process = require('../models/Process');

class ProcessManager {
  constructor() {
    this.reset();
  }

  reset() {
    this.processes = [];
    this.processMap = new Map();
    this.pidCounter = 1;
  }

  createProcess({ pid, priority = 1 } = {}) {
    const nextPid = pid || `P${this.pidCounter++}`;
    if (this.processMap.has(nextPid)) {
      throw new Error(`Process ${nextPid} already exists`);
    }

    const process = new Process({ pid: nextPid, priority: Number(priority) || 1 });
    this.processes.push(process);
    this.processMap.set(nextPid, process);
    return process;
  }

  getProcess(pid) {
    return this.processMap.get(pid);
  }

  listProcesses() {
    return this.processes;
  }

  toJSON() {
    return this.processes.map((process) => process.toJSON());
  }
}

module.exports = ProcessManager;
