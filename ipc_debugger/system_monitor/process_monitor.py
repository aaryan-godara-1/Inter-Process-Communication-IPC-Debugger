"""
process_monitor.py — Real-time OS process monitoring via psutil.

Polls the OS process list at a configurable interval, computes the delta
(new / terminated PIDs), and emits PROCESS_SNAPSHOT events through the
shared EventManager bus.

Interface:
    ProcessMonitor.start(interval_s)   → None
    ProcessMonitor.stop()              → None
    ProcessMonitor.get_process_tree()  → dict[int, list[int]]
"""

import threading
import time
from typing import Dict, List, Optional, Set

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from ipc_debugger.simulation.event_manager import EventManager
from ipc_debugger.utils.constants import EventType
from ipc_debugger.system_monitor.data_models import ProcessSnapshot

# CPU above this % is highlighted as high-cpu
HIGH_CPU_THRESHOLD = 15.0

# psutil attributes to fetch per process (fail-fast if process disappears)
_PROC_ATTRS = [
    "pid", "name", "cpu_percent", "memory_info",
    "num_threads", "ppid", "status", "username",
]


class ProcessMonitor:
    """
    Polls real OS processes and emits snapshots via EventManager.

    Uses psutil.process_iter() with attribute pre-fetching for efficiency.
    Two back-to-back polls are compared to detect process churn.
    """

    def __init__(self, event_manager: EventManager):
        self.event_manager = event_manager
        self._interval_s: float = 1.5
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Previous snapshot: pid → ProcessSnapshot
        self._prev_pids: Set[int] = set()
        self._prev_snapshots: Dict[int, ProcessSnapshot] = {}

        # First-call initialisation for cpu_percent (returns 0.0 on first call)
        if PSUTIL_AVAILABLE:
            for _ in psutil.process_iter(["pid", "cpu_percent"]):
                pass  # prime the cpu_percent cache

    # ── public interface ────────────────────────────────────────────────

    def start(self, interval_s: float = 1.5) -> None:
        """Start the background polling thread."""
        if self._running:
            return
        self._interval_s = interval_s
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="ProcessMonitor",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the polling thread."""
        self._running = False

    def get_snapshots(self) -> List[ProcessSnapshot]:
        """Return the last polled process list (thread-safe copy)."""
        with self._lock:
            return list(self._prev_snapshots.values())

    def get_process_tree(self) -> Dict[int, List[int]]:
        """
        Return a parent→children mapping built from the last snapshot.
        Format: { parent_pid: [child_pid, child_pid, ...] }
        """
        with self._lock:
            tree: Dict[int, List[int]] = {}
            for snap in self._prev_snapshots.values():
                tree.setdefault(snap.ppid, []).append(snap.pid)
                tree.setdefault(snap.pid, [])   # ensure every node exists
        return tree

    # ── internal ────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll()
            except Exception as exc:
                print(f"[ProcessMonitor] poll error: {exc}")
            time.sleep(self._interval_s)

    def _poll(self) -> None:
        if not PSUTIL_AVAILABLE:
            self._emit_dummy()
            return

        new_snapshots: Dict[int, ProcessSnapshot] = {}

        for proc in psutil.process_iter(_PROC_ATTRS):
            try:
                info = proc.info
                mem = info.get("memory_info")
                rss = mem.rss if mem else 0
                vms = mem.vms if mem else 0
                cpu = info.get("cpu_percent") or 0.0
                snap = ProcessSnapshot(
                    pid=info["pid"],
                    name=info.get("name") or "?",
                    cpu_percent=cpu,
                    memory_rss=rss,
                    memory_vms=vms,
                    num_threads=info.get("num_threads") or 1,
                    ppid=info.get("ppid") or 0,
                    status=info.get("status") or "unknown",
                    username=info.get("username") or "",
                    is_high_cpu=(cpu > HIGH_CPU_THRESHOLD),
                )
                new_snapshots[snap.pid] = snap
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        current_pids = set(new_snapshots.keys())

        with self._lock:
            prev_pids = self._prev_pids
            new_pids = current_pids - prev_pids
            terminated_pids = prev_pids - current_pids

            # Tag newly appeared processes
            for pid in new_pids:
                if pid in new_snapshots:
                    new_snapshots[pid].is_new = True

            self._prev_pids = current_pids
            self._prev_snapshots = new_snapshots

        # Emit outside the lock
        self.event_manager.emit(
            EventType.PROCESS_SNAPSHOT,
            processes=list(new_snapshots.values()),
            new_pids=new_pids,
            terminated_pids=terminated_pids,
        )

    def _emit_dummy(self) -> None:
        """Fallback when psutil is not available — emit a notice."""
        self.event_manager.emit(
            EventType.PROCESS_SNAPSHOT,
            processes=[],
            new_pids=set(),
            terminated_pids=set(),
        )
