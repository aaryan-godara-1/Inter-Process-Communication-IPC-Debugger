"""
ipc_tracker.py — Detect real IPC connections between OS processes.

Inspects open file handles and network sockets to infer IPC relationships:
  • Shared files — two+ processes with the same file path open
  • TCP/UDP sockets — matching local/remote address pairs across processes
  • Named pipes — Windows \\.\pipe\ namespace listing

Interface:
    IPCTracker.start(interval_s)  → None
    IPCTracker.stop()             → None
    IPCTracker.get_connections()  → list[IPCConnection]
"""

import os
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from simulation.event_manager import EventManager
from utils.constants import EventType
from system_monitor.data_models import IPCConnection

# Only track files under these roots to avoid massive noise
_INTERESTING_FILE_PREFIXES: tuple = (
    r"C:\Users",
    r"C:\ProgramData",
    r"/home",
    r"/tmp",
    r"/var",
    r"/opt",
)

# Ignore kernel/system files that every process has open
_SKIP_FILE_PATTERNS: tuple = (
    "\\Device\\",
    "\\BaseNamedObjects\\",
    "pagefile.sys",
    "ntdll.dll",
    ".dll",
    ".exe",
)


def _is_interesting_file(path: str) -> bool:
    """Return True if the file is worth tracking as a potential shared resource."""
    path_lower = path.lower()
    for skip in _SKIP_FILE_PATTERNS:
        if skip.lower() in path_lower:
            return False
    return True


class IPCTracker:
    """
    Detects real IPC connections between OS processes using psutil.

    Runs in a background thread, cross-references open file handles and
    network sockets across all processes, and emits IPC_CONNECTION_FOUND
    events through the shared EventManager.
    """

    def __init__(self, event_manager: EventManager):
        self.event_manager = event_manager
        self._interval_s: float = 3.0
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._connections: List[IPCConnection] = []

    # ── public interface ────────────────────────────────────────────────

    def start(self, interval_s: float = 3.0) -> None:
        """Start the background IPC detection thread."""
        if self._running:
            return
        self._interval_s = interval_s
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="IPCTracker",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_connections(self) -> List[IPCConnection]:
        """Return the last detected IPC connections (thread-safe copy)."""
        with self._lock:
            return list(self._connections)

    # ── internal ────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                connections = self._detect()
                with self._lock:
                    self._connections = connections
                self.event_manager.emit(
                    EventType.IPC_CONNECTION_FOUND,
                    connections=connections,
                )
            except Exception as exc:
                print(f"[IPCTracker] poll error: {exc}")
            time.sleep(self._interval_s)

    def _detect(self) -> List[IPCConnection]:
        if not PSUTIL_AVAILABLE:
            return []

        connections: List[IPCConnection] = []
        proc_names: Dict[int, str] = {}

        # ── Gather per-process data ──────────────────────────────────
        file_map: Dict[str, List[int]] = defaultdict(list)   # path → [pids]
        sock_map: Dict[str, List[int]] = defaultdict(list)   # endpoint → [pids]

        for proc in psutil.process_iter(["pid", "name"]):
            pid = proc.pid
            try:
                proc_names[pid] = proc.info.get("name") or "?"

                # Open files
                try:
                    for f in proc.open_files():
                        path = f.path
                        if _is_interesting_file(path):
                            file_map[path].append(pid)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

                # Network connections
                try:
                    for conn in proc.connections(kind="inet"):
                        if conn.laddr:
                            key = f"{conn.laddr.ip}:{conn.laddr.port}"
                            sock_map[key].append(pid)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # ── Shared files ─────────────────────────────────────────────
        seen_file_pairs: Set[tuple] = set()
        for path, pids in file_map.items():
            unique = list(dict.fromkeys(pids))  # deduplicate, preserve order
            if len(unique) < 2:
                continue
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    a, b = unique[i], unique[j]
                    pair_key = (min(a, b), max(a, b), "file")
                    if pair_key in seen_file_pairs:
                        continue
                    seen_file_pairs.add(pair_key)
                    connections.append(IPCConnection(
                        connection_type="shared_file",
                        pid_a=a,
                        pid_b=b,
                        resource=path,
                        direction="bidirectional",
                        process_name_a=proc_names.get(a, "?"),
                        process_name_b=proc_names.get(b, "?"),
                    ))

        # ── Socket connections ────────────────────────────────────────
        # Find loopback sockets shared across processes
        seen_sock_pairs: Set[tuple] = set()
        for endpoint, pids in sock_map.items():
            unique = list(dict.fromkeys(pids))
            if len(unique) < 2:
                continue
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    a, b = unique[i], unique[j]
                    pair_key = (min(a, b), max(a, b), "sock")
                    if pair_key in seen_sock_pairs:
                        continue
                    seen_sock_pairs.add(pair_key)
                    connections.append(IPCConnection(
                        connection_type="tcp_socket",
                        pid_a=a,
                        pid_b=b,
                        resource=endpoint,
                        direction="bidirectional",
                        process_name_a=proc_names.get(a, "?"),
                        process_name_b=proc_names.get(b, "?"),
                    ))

        # ── Named pipes (Windows only) ────────────────────────────────
        # We can list named pipes but cannot attribute them to PIDs
        pipe_names = self._list_named_pipes()
        for pipe_name in pipe_names[:20]:  # cap at 20 to avoid spam
            connections.append(IPCConnection(
                connection_type="named_pipe",
                pid_a=0,
                pid_b=0,
                resource=pipe_name,
                direction="unknown",
            ))

        # Cap total connections to keep the GUI responsive
        return connections[:200]

    @staticmethod
    def _list_named_pipes() -> List[str]:
        """List Windows named pipes (no-op on non-Windows)."""
        try:
            pipe_dir = r"\\.\pipe"
            return [
                os.path.join(pipe_dir, p)
                for p in os.listdir(pipe_dir)
            ]
        except (OSError, PermissionError):
            return []
