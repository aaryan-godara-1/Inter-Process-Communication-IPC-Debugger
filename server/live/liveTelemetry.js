const os = require('os');
const { exec } = require('child_process');

function execCommand(command, timeout = 1200) {
  return new Promise((resolve) => {
    exec(command, { timeout, windowsHide: true, maxBuffer: 1024 * 1024 * 4 }, (error, stdout) => {
      if (error) {
        resolve('');
        return;
      }
      resolve(String(stdout || ''));
    });
  });
}

async function collectWindowsProcesses(limit) {
  const command = [
    'powershell -NoProfile -Command',
    '"Get-Process |',
    'Sort-Object -Property WorkingSet64 -Descending |',
    `Select-Object -First ${limit} `,
    '@{Name=\'pid\';Expression={$_.Id}},',
    '@{Name=\'name\';Expression={$_.ProcessName}},',
    '@{Name=\'cpuTime\';Expression={[double]($_.CPU)}},',
    '@{Name=\'workingSet\';Expression={[int64]$_.WorkingSet64}},',
    '@{Name=\'threads\';Expression={$_.Threads.Count}} |',
    'ConvertTo-Json -Compress"'
  ].join(' ');

  const output = await execCommand(command);
  if (!output.trim()) {
    return [];
  }

  try {
    const parsed = JSON.parse(output);
    const rows = Array.isArray(parsed) ? parsed : [parsed];
    return rows
      .map((row) => ({
        pid: Number(row.pid) || 0,
        name: String(row.name || 'unknown'),
        cpuTime: Number(row.cpuTime) || 0,
        workingSet: Number(row.workingSet) || 0,
        threads: Number(row.threads) || 0,
      }))
      .filter((row) => row.pid > 0);
  } catch {
    return [];
  }
}

async function collectUnixProcesses(limit) {
  const output = await execCommand(`ps -eo pid=,comm=,time=,rss= --sort=-rss | head -n ${limit + 1}`);
  if (!output.trim()) {
    return [];
  }

  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/);
      if (parts.length < 4) {
        return null;
      }
      const pid = Number(parts[0]) || 0;
      const name = parts[1] || 'proc';
      const time = parts[2] || '00:00:00';
      const rssKb = Number(parts[3]) || 0;

      const hhmmss = time.split(':').map((v) => Number(v) || 0);
      const seconds = hhmmss.length === 3
        ? (hhmmss[0] * 3600 + hhmmss[1] * 60 + hhmmss[2])
        : (hhmmss[0] * 60 + hhmmss[1]);

      return {
        pid,
        name,
        cpuTime: seconds,
        workingSet: rssKb * 1024,
        threads: 0,
      };
    })
    .filter((row) => Boolean(row) && row.pid > 0);
}

function createCpuSampler() {
  let previous = os.cpus();

  return () => {
    const next = os.cpus();
    if (!previous || !next || !next.length) {
      previous = next;
      return { totalPercent: 0, coreCount: Math.max(1, next ? next.length : 1) };
    }

    let totalIdle = 0;
    let totalTick = 0;

    for (let i = 0; i < next.length; i += 1) {
      const prevTimes = previous[i].times;
      const nextTimes = next[i].times;

      const idle = nextTimes.idle - prevTimes.idle;
      const total =
        (nextTimes.user - prevTimes.user) +
        (nextTimes.nice - prevTimes.nice) +
        (nextTimes.sys - prevTimes.sys) +
        (nextTimes.irq - prevTimes.irq) +
        idle;

      totalIdle += idle;
      totalTick += total;
    }

    previous = next;
    const usage = totalTick > 0 ? (1 - totalIdle / totalTick) * 100 : 0;
    return {
      totalPercent: Number(usage.toFixed(1)),
      coreCount: Math.max(1, next.length),
    };
  };
}

function createLiveTelemetryStream({ broadcast, intervalMs = 1200, processLimit = 14 } = {}) {
  const cpuSampler = createCpuSampler();
  const previousProcessCpu = new Map();

  let timer = null;
  let running = false;
  let sampling = false;
  let subscribers = 0;
  let snapshot = {
    ts: Date.now(),
    host: {
      totalMemory: os.totalmem(),
      freeMemory: os.freemem(),
      memoryPercent: 0,
      cpuTotalPercent: 0,
      logicalCores: os.cpus().length,
      platform: os.platform(),
      uptimeSec: os.uptime(),
    },
    resources: {
      cpu: { id: 'CPU', label: 'CPU', usedPercent: 0 },
      memory: { id: 'MEM', label: 'Memory', usedPercent: 0 },
      disk: { id: 'DISK', label: 'Disk', usedPercent: 0 },
      network: { id: 'NET', label: 'Network', usedPercent: 0 },
      threads: { id: 'THR', label: 'Threads', usedPercent: 0 },
    },
    processes: [],
  };

  async function collectProcesses() {
    if (process.platform === 'win32') {
      return collectWindowsProcesses(processLimit);
    }
    return collectUnixProcesses(processLimit);
  }

  async function sampleOnce() {
    if (sampling) {
      return;
    }

    sampling = true;
    try {
      const processes = await collectProcesses();
      const cpuSample = cpuSampler();
      const totalMemory = os.totalmem();
      const freeMemory = os.freemem();
      const usedMemory = Math.max(0, totalMemory - freeMemory);

      const now = Date.now();
      const normalizedProcesses = processes.map((proc) => {
        const previous = previousProcessCpu.get(proc.pid);
        previousProcessCpu.set(proc.pid, { cpuTime: proc.cpuTime, ts: now });

        let cpuPercent = 0;
        if (previous) {
          const cpuDelta = Math.max(0, proc.cpuTime - previous.cpuTime);
          const secDelta = Math.max(0.25, (now - previous.ts) / 1000);
          cpuPercent = Math.min(100, (cpuDelta / (secDelta * Math.max(1, cpuSample.coreCount))) * 100);
        }

        const memPercent = totalMemory > 0 ? (proc.workingSet / totalMemory) * 100 : 0;

        return {
          pid: proc.pid,
          id: `P${proc.pid}`,
          name: proc.name,
          cpuPercent: Number(cpuPercent.toFixed(1)),
          memoryBytes: proc.workingSet,
          memoryPercent: Number(memPercent.toFixed(2)),
          threads: proc.threads,
          // Approximation for a live visual channel without kernel tracing.
          ioPercent: Number(Math.min(100, (cpuPercent * 0.55) + Math.min(18, proc.threads * 0.6)).toFixed(1)),
          networkPercent: Number(Math.min(100, cpuPercent * 0.35).toFixed(1)),
        };
      });

      const totalThreads = normalizedProcesses.reduce((sum, p) => sum + p.threads, 0);
      const maxThreads = Math.max(1, totalThreads);

      snapshot = {
        ts: now,
        host: {
          totalMemory,
          freeMemory,
          memoryPercent: Number(((usedMemory / Math.max(1, totalMemory)) * 100).toFixed(1)),
          cpuTotalPercent: cpuSample.totalPercent,
          logicalCores: cpuSample.coreCount,
          platform: process.platform,
          uptimeSec: Math.round(os.uptime()),
        },
        resources: {
          cpu: { id: 'CPU', label: 'CPU', usedPercent: cpuSample.totalPercent },
          memory: { id: 'MEM', label: 'Memory', usedPercent: Number(((usedMemory / Math.max(1, totalMemory)) * 100).toFixed(1)) },
          disk: {
            id: 'DISK',
            label: 'Disk IO',
            usedPercent: Number(Math.min(100, normalizedProcesses.reduce((s, p) => s + p.ioPercent, 0) / 2).toFixed(1)),
          },
          network: {
            id: 'NET',
            label: 'Network',
            usedPercent: Number(Math.min(100, normalizedProcesses.reduce((s, p) => s + p.networkPercent, 0) / 2).toFixed(1)),
          },
          threads: {
            id: 'THR',
            label: 'Threads',
            usedPercent: Number(Math.min(100, (totalThreads / maxThreads) * 100).toFixed(1)),
          },
        },
        processes: normalizedProcesses,
      };

      if (running && subscribers > 0) {
        broadcast({ type: 'live:update', payload: snapshot });
      }
    } finally {
      sampling = false;
    }
  }

  function start() {
    if (running) {
      return;
    }
    running = true;
    sampleOnce();
    timer = setInterval(sampleOnce, intervalMs);
  }

  function stop() {
    running = false;
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function setSubscribers(count) {
    subscribers = Math.max(0, Number(count) || 0);
    if (subscribers > 0) {
      start();
    } else {
      stop();
    }
  }

  function getSnapshot() {
    return snapshot;
  }

  return {
    setSubscribers,
    getSnapshot,
  };
}

module.exports = {
  createLiveTelemetryStream,
};