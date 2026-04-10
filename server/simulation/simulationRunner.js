const ProcessManager = require('./processManager');
const ResourceManager = require('./resourceManager');
const { analyzeState } = require('./deadlockDetector');
const { buildGraph } = require('./graphEngine');

function formatTimestamp() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function createSimulationRunner(broadcast = () => {}) {
  const processManager = new ProcessManager();
  const resourceManager = new ResourceManager();

  const runner = {
    processManager,
    resourceManager,
    broadcast,
    logs: [],
    stepCount: 0,
    running: false,
    mode: 'step',
    speed: 1000,
    timer: null,

    log(message, type = 'info', details = {}) {
      this.logs.unshift({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        time: formatTimestamp(),
        message,
        type,
        details,
      });

      if (this.logs.length > 200) {
        this.logs.length = 200;
      }
    },

    syncProcessStates() {
      const processes = this.processManager.listProcesses();

      for (const process of processes) {
        const hasRequest = Object.keys(process.requestedResources).length > 0;
        if (hasRequest) {
          process.state = process.waitSteps > 0 ? 'blocked' : 'waiting';
        } else if (process.state !== 'finished') {
          process.state = 'running';
        }
      }
    },

    tryResolveRequests() {
      const processes = [...this.processManager.listProcesses()].sort((left, right) => {
        if (right.priority !== left.priority) {
          return right.priority - left.priority;
        }
        return left.pid.localeCompare(right.pid);
      });

      for (const process of processes) {
        for (const [resourceId, amount] of Object.entries(process.requestedResources)) {
          const resource = this.resourceManager.getResource(resourceId);
          if (!resource) {
            continue;
          }

          if (resource.availableInstances >= amount) {
            this.resourceManager.allocate(process.pid, resourceId, amount);
            process.hold(resourceId, amount);
            process.clearRequest(resourceId);
            process.waitSteps = 0;
            process.state = 'running';
            this.log(`${process.pid} allocated ${resourceId}`, 'allocation', { processId: process.pid, resourceId, amount });
          } else {
            process.state = process.waitSteps > 1 ? 'blocked' : 'waiting';
          }
        }
      }
    },

    ageWaitingProcesses() {
      for (const process of this.processManager.listProcesses()) {
        if (Object.keys(process.requestedResources).length > 0) {
          process.waitSteps += 1;
          if (process.waitSteps > 1) {
            process.state = 'blocked';
          }
        } else if (process.state !== 'finished') {
          process.waitSteps = 0;
        }
      }
    },

    emitState() {
      const processes = this.processManager.listProcesses();
      const resources = this.resourceManager.listResources();
      const analysis = analyzeState(processes, resources);
      const graph = buildGraph(processes.map((process) => process.toJSON()), resources.map((resource) => resource.toJSON()), analysis);

      const state = {
        processes: this.processManager.toJSON(),
        resources: this.resourceManager.toJSON(),
        matrices: {
          allocation: this.resourceManager.getAllocationMatrix(processes),
          request: this.resourceManager.getRequestMatrix(processes),
          available: this.resourceManager.getAvailableVector(),
        },
        analysis,
        graph,
        logs: this.logs,
        simulation: {
          running: this.running,
          mode: this.mode,
          speed: this.speed,
          stepCount: this.stepCount,
        },
      };

      this.broadcast({ type: 'state:update', payload: state });
      return state;
    },

    getState() {
      return this.emitState();
    },

    createProcess(data = {}) {
      const process = this.processManager.createProcess(data);
      this.log(`Created process ${process.pid}`, 'system', { processId: process.pid });
      this.emitState();
      return process.toJSON();
    },

    createResource(data = {}) {
      const resource = this.resourceManager.createResource(data);
      this.log(`Created resource ${resource.resourceId}`, 'system', { resourceId: resource.resourceId });
      this.tryResolveRequests();
      this.syncProcessStates();
      this.emitState();
      return resource.toJSON();
    },

    requestResource({ processId, resourceId, amount = 1 }) {
      const process = this.processManager.getProcess(processId);
      const resource = this.resourceManager.getResource(resourceId);

      if (!process) {
        throw new Error(`Process ${processId} not found`);
      }
      if (!resource) {
        throw new Error(`Resource ${resourceId} not found`);
      }

      const requestAmount = Math.max(1, Number(amount) || 1);
      process.request(resourceId, requestAmount);
      process.state = 'waiting';
      process.waitSteps = 0;
      this.log(`${processId} requested ${resourceId}`, 'request', { processId, resourceId, amount: requestAmount });
      this.tryResolveRequests();
      this.syncProcessStates();
      this.emitState();
      return this.getState();
    },

    releaseResource({ processId, resourceId, amount = 1 }) {
      const process = this.processManager.getProcess(processId);
      const resource = this.resourceManager.getResource(resourceId);

      if (!process) {
        throw new Error(`Process ${processId} not found`);
      }
      if (!resource) {
        throw new Error(`Resource ${resourceId} not found`);
      }

      const releaseAmount = Math.max(1, Number(amount) || 1);
      const released = this.resourceManager.release(processId, resourceId, releaseAmount);
      process.release(resourceId, released);
      this.log(`${processId} released ${resourceId}`, 'release', { processId, resourceId, amount: released });
      this.tryResolveRequests();
      this.syncProcessStates();
      this.emitState();
      return this.getState();
    },

    advanceStep(source = 'step') {
      this.stepCount += 1;
      this.ageWaitingProcesses();
      this.tryResolveRequests();
      this.syncProcessStates();

      const runnable = this.processManager
        .listProcesses()
        .filter((process) => process.state === 'running' && Object.keys(process.requestedResources).length === 0)
        .sort((left, right) => {
          if (right.priority !== left.priority) {
            return right.priority - left.priority;
          }
          return left.pid.localeCompare(right.pid);
        });

      if (runnable.length > 0) {
        const activeProcess = runnable[0];
        this.log(`${activeProcess.pid} executed a time slice`, 'execution', { processId: activeProcess.pid, source });
      } else {
        this.log(`Simulation tick ${this.stepCount}`, 'system', { source });
      }

      const state = this.emitState();
      if (state.analysis.state === 'DEADLOCK') {
        this.pause();
      }
      return state;
    },

    start({ speed, mode } = {}) {
      if (speed) {
        this.speed = Math.max(100, Number(speed) || this.speed);
      }
      if (mode) {
        this.mode = mode;
      }

      if (this.timer) {
        clearInterval(this.timer);
      }

      this.running = true;
      this.mode = 'realtime';
      this.timer = setInterval(() => {
        this.advanceStep('realtime');
      }, this.speed);
      this.log(`Realtime simulation started at ${this.speed} ms`, 'system', { speed: this.speed });
      return this.emitState();
    },

    pause() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
      this.running = false;
      this.mode = 'step';
      this.log('Simulation paused', 'system');
      return this.emitState();
    },

    step() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
      this.running = false;
      this.mode = 'step';
      return this.advanceStep('step');
    },

    reset() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
      this.running = false;
      this.mode = 'step';
      this.speed = 1000;
      this.stepCount = 0;
      this.logs = [];
      this.processManager.reset();
      this.resourceManager.reset();
      this.log('System reset', 'system');
      return this.emitState();
    },

    setSpeed(speed) {
      this.speed = Math.max(100, Number(speed) || this.speed);
      if (this.running) {
        return this.start({ speed: this.speed });
      }
      return this.emitState();
    },
  };

  return runner;
}

module.exports = {
  createSimulationRunner,
};
