"""
system_stats.py — Global system performance metrics via psutil.

Polls CPU, memory, disk I/O, and network I/O at a configurable interval
and emits SYSTEM_STATS_UPDATE events through the shared EventManager bus.

Interface:
    SystemStats.start(interval_s)  → None
    SystemStats.stop()             → None
    SystemStats.get_latest()       → SystemStatsSnapshot | None
"""

import threading
import time
from typing import Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from simulation.event_manager import EventManager
from utils.constants import EventType
from system_monitor.data_models import SystemStatsSnapshot


class SystemStats:
    """
    Collects system-wide performance metrics and emits snapshots.

    Disk and network stats are based on deltas between consecutive polls
    to compute bytes/second rates.
    """

    def __init__(self, event_manager: EventManager):
        self.event_manager = event_manager
        self._interval_s: float = 2.0
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest: Optional[SystemStatsSnapshot] = None

        # Delta baselines
        self._prev_disk = None
        self._prev_net = None
        self._prev_ts: float = 0.0

        if PSUTIL_AVAILABLE:
            # Prime baselines
            self._prev_disk = psutil.disk_io_counters()
            self._prev_net = psutil.net_io_counters()
            self._prev_ts = time.monotonic()

    # ── public interface ────────────────────────────────────────────────

    def start(self, interval_s: float = 2.0) -> None:
        """Start the polling thread."""
        if self._running:
            return
        self._interval_s = interval_s
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="SystemStats",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_latest(self) -> Optional[SystemStatsSnapshot]:
        """Return the most recent snapshot (thread-safe)."""
        with self._lock:
            return self._latest

    # ── internal ────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                print(f"[SystemStats] poll error: {exc}")
            time.sleep(self._interval_s)

    def _poll(self) -> None:
        if not PSUTIL_AVAILABLE:
            return

        now = time.monotonic()
        elapsed = max(now - self._prev_ts, 0.001)
        self._prev_ts = now

        # CPU
        cpu_all = psutil.cpu_percent(interval=None)
        try:
            cpu_percpu = psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            cpu_percpu = [cpu_all]

        # Memory
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disk I/O delta
        disk = psutil.disk_io_counters()
        disk_read_s = disk_write_s = 0.0
        if self._prev_disk and disk:
            disk_read_s = (disk.read_bytes - self._prev_disk.read_bytes) / elapsed
            disk_write_s = (disk.write_bytes - self._prev_disk.write_bytes) / elapsed
        self._prev_disk = disk

        # Network I/O delta
        net = psutil.net_io_counters()
        net_sent_s = net_recv_s = 0.0
        if self._prev_net and net:
            net_sent_s = (net.bytes_sent - self._prev_net.bytes_sent) / elapsed
            net_recv_s = (net.bytes_recv - self._prev_net.bytes_recv) / elapsed
        self._prev_net = net

        snap = SystemStatsSnapshot(
            timestamp=time.time(),
            cpu_percent=cpu_all,
            cpu_percpu=cpu_percpu,
            memory_total=mem.total,
            memory_used=mem.used,
            memory_percent=mem.percent,
            swap_total=swap.total,
            swap_used=swap.used,
            swap_percent=swap.percent,
            disk_read_bytes_s=max(0.0, disk_read_s),
            disk_write_bytes_s=max(0.0, disk_write_s),
            net_sent_bytes_s=max(0.0, net_sent_s),
            net_recv_bytes_s=max(0.0, net_recv_s),
            process_count=len(psutil.pids()),
            boot_time=psutil.boot_time(),
        )

        with self._lock:
            self._latest = snap

        self.event_manager.emit(EventType.SYSTEM_STATS_UPDATE, stats=snap)
