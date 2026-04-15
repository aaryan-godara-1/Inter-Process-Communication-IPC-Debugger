const ProcessManager = require('./processManager');
const ResourceManager = require('./resourceManager');
const { analyzeState } = require('./deadlockDetector');
const { buildGraph } = require('./graphEngine');

function formatTimestamp() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function parseScenario(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'empty' || raw === 'none') {
    return 'empty';
  }
  if (raw === 'normal' || raw === 'normal-flow') {
    return 'normal-flow';
  }
  return 'deadlock';
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
    currentScenario: 'deadlock',
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

    resetEntities() {
      this.processManager.reset();
      this.resourceManager.reset();
    },

    createPresetProcess(data) {
      return this.processManager.createProcess(data);
    },

    createPresetResource(data) {
      return this.resourceManager.createResource(data);
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
          scenario: this.currentScenario,
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
        this.log('Deadlock persists while simulation is running', 'warning', { source });
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

    applyDeadlockPreset() {
      const p1 = this.processManager.createProcess({ priority: 4 });
      const p2 = this.processManager.createProcess({ priority: 4 });
      const p3 = this.processManager.createProcess({ priority: 3 });
      const p4 = this.processManager.createProcess({ priority: 2 });
      const r1 = this.resourceManager.createResource({ totalInstances: 1 });
      const r2 = this.resourceManager.createResource({ totalInstances: 1 });
      const r3 = this.resourceManager.createResource({ totalInstances: 2 });

      // Allocate resources to processes (green edges)
      this.resourceManager.allocate(p1.pid, r1.resourceId, 1);
      p1.hold(r1.resourceId, 1);
      this.resourceManager.allocate(p2.pid, r2.resourceId, 1);
      p2.hold(r2.resourceId, 1);
      this.resourceManager.allocate(p3.pid, r3.resourceId, 1);
      p3.hold(r3.resourceId, 1);
      this.resourceManager.allocate(p4.pid, r3.resourceId, 1);
      p4.hold(r3.resourceId, 1);

      // Both p1 and p2 request each other's resources (creates circular wait - red edges)
      p1.request(r2.resourceId, 1);
      p2.request(r1.resourceId, 1);
      
      p1.state = 'waiting';
      p2.state = 'waiting';
      p1.waitSteps = 0;
      p2.waitSteps = 0;

      this.log(`🔄 Deadlock preset: ${p1.pid} holds ${r1.resourceId}, requesting ${r2.resourceId}`, 'system');
      this.log(`🔄 Deadlock preset: ${p2.pid} holds ${r2.resourceId}, requesting ${r1.resourceId}`, 'system');
      this.log(`⏳ Watching for circular wait pattern to emerge...`, 'info');
    },

    applyNormalFlowPreset() {
      const p1 = this.createPresetProcess({ priority: 4 });
      const p2 = this.createPresetProcess({ priority: 3 });
      const p3 = this.createPresetProcess({ priority: 2 });
      const p4 = this.createPresetProcess({ priority: 1 });

      const r1 = this.createPresetResource({ resourceId: 'R1', totalInstances: 1 });
      const r2 = this.createPresetResource({ resourceId: 'R2', totalInstances: 1 });
      const r3 = this.createPresetResource({ resourceId: 'R3', totalInstances: 2 });

      // Allocate resources (green edges)
      this.resourceManager.allocate(p1.pid, r1.resourceId, 1);
      p1.hold(r1.resourceId, 1);
      this.resourceManager.allocate(p2.pid, r2.resourceId, 1);
      p2.hold(r2.resourceId, 1);
      this.resourceManager.allocate(p3.pid, r3.resourceId, 1);
      p3.hold(r3.resourceId, 1);
      this.resourceManager.allocate(p4.pid, r3.resourceId, 1);
      p4.hold(r3.resourceId, 1);

      p1.state = 'running';
      p2.state = 'running';
      p3.state = 'running';
      p4.state = 'running';

      this.log(`✓ Normal flow: 4 processes and 3 resources with no waiting`, 'system');
      this.log(`✓ Resource utilization: steady allocations, zero queued requests`, 'system');
    },

    applyBottleneckPreset() {
      const p1 = this.createPresetProcess({ priority: 1 });
      const p2 = this.createPresetProcess({ priority: 4 });
      const p3 = this.createPresetProcess({ priority: 3 });
      const p4 = this.createPresetProcess({ priority: 2 });

      const r1 = this.createPresetResource({ resourceId: 'R1', totalInstances: 1 });
      const r2 = this.createPresetResource({ resourceId: 'R2', totalInstances: 1 });
      const r3 = this.createPresetResource({ resourceId: 'R3', totalInstances: 2 });

      // Allocate resources (green edges)
      this.resourceManager.allocate(p1.pid, r1.resourceId, 1);
      p1.hold(r1.resourceId, 1);
      this.resourceManager.allocate(p2.pid, r2.resourceId, 1);
      p2.hold(r2.resourceId, 1);
      this.resourceManager.allocate(p3.pid, r3.resourceId, 1);
      p3.hold(r3.resourceId, 1);

      // One process waiting for bottleneck resource (red edges)
      p4.request(r1.resourceId, 1);
      p4.request(r2.resourceId, 1);
      p4.state = 'waiting';
      p4.waitSteps = 0;

      p1.state = 'running';
      p2.state = 'running';
      p3.state = 'running';

      this.log(`⏸️ Bottleneck preset: ${p1.pid} and ${p2.pid} hold critical resources`, 'system');
      this.log(`⏸️ Bottleneck forming: ${p4.pid} waiting for multiple resources`, 'system');
      this.log(`📊 Resource utilization: 67% (3 allocated, 1 waiting for 2)`, 'warning');
    },
  };

  runner.initialize = function initialize({ scenario = 'deadlock' } = {}) {
    const preset = parseScenario(scenario);

    this.currentScenario = preset;
    this.resetEntities();
    this.stepCount = 0;
    this.logs = [];
    
    // Ensure any running timer is cleared
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.running = false;

    if (preset === 'normal-flow') {
      this.applyNormalFlowPreset();
      this.log('Loaded normal flow scenario', 'system', { scenario: 'normal-flow' });
    } else if (preset === 'deadlock') {
      this.applyDeadlockPreset();
      this.log('Loaded default deadlock scenario', 'system', { scenario: 'deadlock' });
    } else {
      this.log('Loaded empty scenario', 'system', { scenario: 'empty' });
    }

    this.syncProcessStates();
    return this.emitState();
  };

  runner.reset = function reset(options = {}) {
    const scenario = parseScenario(options.scenario);
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.running = false;
    this.mode = 'step';
    if (Object.prototype.hasOwnProperty.call(options, 'speed')) {
      this.speed = Math.max(100, Number(options.speed) || this.speed);
    } else {
      this.speed = 1000;
    }
    return this.initialize({ scenario });
  };

  // Start simulation mode with a non-blocking default so the UI visibly advances.
  runner.reset({ scenario: 'normal-flow' });

  return runner;
}

module.exports = {
  createSimulationRunner,
};
