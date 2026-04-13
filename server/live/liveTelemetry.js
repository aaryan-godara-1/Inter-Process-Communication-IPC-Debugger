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
    'Where-Object { $_.Id -gt 0 } |',
    `Select-Object -First ${Number(limit)} `,
    '@{Name=\'pid\';Expression={$_.Id}},',
    '@{Name=\'name\';Expression={$_.ProcessName}},',
    '@{Name=\'cpuTime\';Expression={[double]($_.CPU)}},',
    '@{Name=\'workingSet\';Expression={[int64]$_.WorkingSet64}},',
    '@{Name=\'threads\';Expression={$_.Threads.Count}},',
    '@{Name=\'handles\';Expression={[int]$_.Handles}},',
    '@{Name=\'ioReadBytes\';Expression={[double]$_.IOReadBytes}},',
    '@{Name=\'ioWriteBytes\';Expression={[double]$_.IOWriteBytes}} |',
    'ConvertTo-Json -Compress"'
  ].join(' ');

  const output = await execCommand(command, 900);
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
        handles: Number(row.handles) || 0,
        ioReadBytes: Number(row.ioReadBytes) || 0,
        ioWriteBytes: Number(row.ioWriteBytes) || 0,
      }))
      .filter((row) => row.pid > 0);
  } catch {
    return [];
  }
}

async function collectWindowsSystemResourceMetrics() {
  const command = [
    'powershell -NoProfile -Command',
    '"$disk=(Get-Counter \'\\PhysicalDisk(_Total)\\% Disk Time\' -ErrorAction SilentlyContinue).CounterSamples | Select-Object -First 1;',
    '$netBytes=(Get-Counter \'\\Network Interface(*)\\Bytes Total/sec\' -ErrorAction SilentlyContinue).CounterSamples;',
    '$netBandwidth=(Get-Counter \'\\Network Interface(*)\\Current Bandwidth\' -ErrorAction SilentlyContinue).CounterSamples;',
    '$bytes=0; foreach($n in $netBytes){$bytes += [double]$n.CookedValue};',
    '$band=0; foreach($b in $netBandwidth){$band += [double]$b.CookedValue};',
    '[pscustomobject]@{',
    'diskPercent=[math]::Round([double]$disk.CookedValue,1);',
    'networkBytesPerSec=[math]::Round($bytes,1);',
    'networkBandwidthBps=[math]::Round($band,1);',
    '} | ConvertTo-Json -Compress"'
  ].join(' ');

  const output = await execCommand(command);
  if (!output.trim()) {
    return {
      diskPercent: 0,
      networkBytesPerSec: 0,
      networkBandwidthBps: 0,
    };
  }

  try {
    const parsed = JSON.parse(output);
    return {
      diskPercent: clampPercent(parsed.diskPercent),
      networkBytesPerSec: Math.max(0, Number(parsed.networkBytesPerSec) || 0),
      networkBandwidthBps: Math.max(0, Number(parsed.networkBandwidthBps) || 0),
    };
  } catch {
    return {
      diskPercent: 0,
      networkBytesPerSec: 0,
      networkBandwidthBps: 0,
    };
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
        handles: 0,
      };
    })
    .filter((row) => Boolean(row) && row.pid > 0);
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function buildProcessDeepUsage(processRow, coreCount) {
  const usage = {};
  const cpuPercent = Number(processRow.cpuPercent || 0);
  const memPercent = Number(processRow.memoryPercent || 0);
  const ioPercent = Number(processRow.ioPercent || 0);
  const netPercent = Number(processRow.networkPercent || 0);
  const threads = Number(processRow.threads || 0);
  const handles = Number(processRow.handles || 0);

  const cpuCores = Array.isArray(processRow.cpuCores) ? processRow.cpuCores : [];
  const visibleCoreCount = Math.min(6, Math.max(1, Number(coreCount) || 1));
  const coreShare = cpuCores.length > 0 ? (cpuPercent / cpuCores.length) : cpuPercent;
  for (const core of cpuCores) {
    const idx = Math.max(0, Number(core) || 0);
    const key = idx < visibleCoreCount ? `CPU_CORE_${idx}` : 'CPU_CORE_OTHER';
    usage[key] = clampPercent((usage[key] || 0) + coreShare);
  }

  usage.MEM_HEAP = clampPercent(memPercent * 0.54);
  usage.MEM_STACK = clampPercent(threads * 0.95);
  usage.MEM_CACHE = clampPercent(memPercent * 0.29);
  usage.MEM_SWAP = clampPercent(Math.max(0, memPercent - 72) * 1.5);

  usage.DISK_READ = clampPercent(ioPercent * 0.6);
  usage.DISK_WRITE = clampPercent(ioPercent * 0.34);
  usage.DISK_HANDLE = clampPercent(Math.max(handles * 0.08, threads * 1.8));

  usage.NET_SOCKET = clampPercent(netPercent * 0.48 + threads * 0.65);
  usage.NET_PORT = clampPercent(netPercent * 0.28 + Math.max(0, threads - 4));
  usage.NET_PACKET = clampPercent(netPercent * 0.74);

  usage.THR_SCHED = clampPercent(threads * 2.6);
  usage.THR_WORKER = clampPercent(threads * 3.25);
  usage.THR_IO = clampPercent(ioPercent * 0.46 + threads * 1.1);

  return usage;
}

function aggregateDeepResources(processes, coreCount) {
  const totals = new Map();
  const count = Math.max(1, processes.length);

  for (const proc of processes) {
    const deep = proc.deepUsage || {};
    for (const [key, value] of Object.entries(deep)) {
      totals.set(key, (totals.get(key) || 0) + clampPercent(value));
    }
  }

  const deep = {};
  for (const [key, total] of totals.entries()) {
    deep[key] = {
      id: key,
      usedPercent: Number(Math.min(100, total / count).toFixed(1)),
    };
  }

  const visibleCoreCount = Math.min(6, Math.max(1, Number(coreCount) || 1));
  for (let idx = 0; idx < visibleCoreCount; idx += 1) {
    const key = `CPU_CORE_${idx}`;
    if (!deep[key]) {
      deep[key] = { id: key, usedPercent: 0 };
    }
  }

  if (Number(coreCount) > visibleCoreCount && !deep.CPU_CORE_OTHER) {
    deep.CPU_CORE_OTHER = { id: 'CPU_CORE_OTHER', usedPercent: 0 };
  }

  return deep;
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
  const previousProcessStats = new Map();

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
      const systemMetrics = process.platform === 'win32'
        ? await Promise.race([
          collectWindowsSystemResourceMetrics(),
          new Promise((resolve) => setTimeout(() => resolve({ diskPercent: 0, networkBytesPerSec: 0, networkBandwidthBps: 0 }), 350)),
        ])
        : { diskPercent: 0, networkBytesPerSec: 0, networkBandwidthBps: 0 };
      const cpuSample = cpuSampler();
      const totalMemory = os.totalmem();
      const freeMemory = os.freemem();
      const usedMemory = Math.max(0, totalMemory - freeMemory);

      const now = Date.now();
      const normalizedProcesses = processes.map((proc) => {
        const previous = previousProcessStats.get(proc.pid);
        previousProcessStats.set(proc.pid, {
          cpuTime: Number(proc.cpuTime || 0),
          ioReadBytes: Number(proc.ioReadBytes || 0),
          ioWriteBytes: Number(proc.ioWriteBytes || 0),
          ts: now,
        });

        let cpuPercent = 0;
        let ioReadBps = 0;
        let ioWriteBps = 0;
        if (previous) {
          const secDelta = Math.max(0.25, (now - Number(previous.ts || now)) / 1000);
          const cpuDelta = Math.max(0, Number(proc.cpuTime || 0) - Number(previous.cpuTime || 0));
          cpuPercent = Math.min(100, (cpuDelta / (secDelta * Math.max(1, cpuSample.coreCount))) * 100);

          const ioReadDelta = Math.max(0, Number(proc.ioReadBytes || 0) - Number(previous.ioReadBytes || 0));
          const ioWriteDelta = Math.max(0, Number(proc.ioWriteBytes || 0) - Number(previous.ioWriteBytes || 0));
          ioReadBps = ioReadDelta / secDelta;
          ioWriteBps = ioWriteDelta / secDelta;
        }

        const memPercent = totalMemory > 0 ? (proc.workingSet / totalMemory) * 100 : 0;

        // Simulate CPU core assignments based on PID and CPU usage
        const coreCount = Math.max(1, cpuSample.coreCount);
        const coredUsage = Math.round((cpuPercent / 100) * coreCount);
        const primaryCore = proc.pid % coreCount;
        const cpuCores = [];
        for (let i = 0; i < coredUsage; i++) {
          cpuCores.push((primaryCore + i) % coreCount);
        }

        return {
          pid: proc.pid,
          id: `P${proc.pid}`,
          name: proc.name,
          cpuPercent: Number(cpuPercent.toFixed(1)),
          memoryBytes: proc.workingSet,
          memoryPercent: Number(memPercent.toFixed(2)),
          threads: proc.threads,
          handles: Number(proc.handles || 0),
          ioReadBps: Number(ioReadBps.toFixed(1)),
          ioWriteBps: Number(ioWriteBps.toFixed(1)),
          ioBps: Number((ioReadBps + ioWriteBps).toFixed(1)),
          tcpConnections: 0,
          cpuCores: cpuCores.length > 0 ? cpuCores : [primaryCore],
          ioPercent: 0,
          networkPercent: 0,
        };
      });

      const activeProcesses = normalizedProcesses.length > 0
        ? normalizedProcesses
        : (Array.isArray(snapshot.processes) ? snapshot.processes : []);

      const totalIoBps = activeProcesses.reduce((sum, proc) => sum + Number(proc.ioBps || 0), 0);
      const totalConnections = activeProcesses.reduce((sum, proc) => sum + Number(proc.tcpConnections || 0), 0);
      const totalNetworkWeight = activeProcesses.reduce(
        (sum, proc) => sum + Math.max(0, Number(proc.ioBps || 0)) + (Math.max(0, Number(proc.threads || 0)) * 1024),
        0,
      );
      const networkPercent = systemMetrics.networkBandwidthBps > 0
        ? Math.min(100, (systemMetrics.networkBytesPerSec * 8 / systemMetrics.networkBandwidthBps) * 100)
        : 0;

      for (const proc of activeProcesses) {
        const ioShare = totalIoBps > 0 ? Number(proc.ioBps || 0) / totalIoBps : 0;
        const connectionShare = totalConnections > 0 ? Number(proc.tcpConnections || 0) / totalConnections : 0;
        const fallbackNetWeight = Math.max(0, Number(proc.ioBps || 0)) + (Math.max(0, Number(proc.threads || 0)) * 1024);
        const fallbackShare = totalNetworkWeight > 0 ? fallbackNetWeight / totalNetworkWeight : 0;
        const netShare = totalConnections > 0 ? connectionShare : fallbackShare;
        proc.ioPercent = Number((systemMetrics.diskPercent * ioShare).toFixed(1));
        proc.networkPercent = Number((networkPercent * netShare).toFixed(1));
      }

      for (const proc of activeProcesses) {
        proc.deepUsage = buildProcessDeepUsage(proc, cpuSample.coreCount);
      }

      const totalThreads = activeProcesses.reduce((sum, p) => sum + p.threads, 0);
      const threadCapacity = Math.max(1, cpuSample.coreCount * 24);

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
            usedPercent: Number(clampPercent(systemMetrics.diskPercent).toFixed(1)),
          },
          network: {
            id: 'NET',
            label: 'Network',
            usedPercent: Number(clampPercent(networkPercent).toFixed(1)),
          },
          threads: {
            id: 'THR',
            label: 'Threads',
            usedPercent: Number(Math.min(100, (totalThreads / threadCapacity) * 100).toFixed(1)),
          },
          deep: aggregateDeepResources(activeProcesses, cpuSample.coreCount),
        },
        processes: activeProcesses,
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