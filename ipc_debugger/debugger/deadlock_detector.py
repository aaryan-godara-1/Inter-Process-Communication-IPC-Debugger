"""
deadlock_detector.py — Deadlock detection via wait-for graph cycle analysis.

Builds a directed graph where an edge  P_i → P_j  means
"process i is waiting for a resource held by process j".
A cycle in this graph indicates a deadlock.

Interface:
    DeadlockDetector.update(processes, channels)  → None
    DeadlockDetector.detect()                     → list[list[int]]   (cycles)
    DeadlockDetector.has_deadlock()                → bool
"""

import threading
from typing import List, Dict, Set, Optional


class DeadlockDetector:
    """
    Detects circular-wait deadlocks among simulated processes.

    Usage:
        1. Call ``update()`` periodically with the current set of
           processes and channels.
        2. Call ``detect()`` to get a list of cycles (each cycle is a
           list of PIDs forming the circular wait).
    """

    def __init__(self):
        # wait-for graph: pid → set of pids it is waiting for
        self._graph: Dict[int, Set[int]] = {}
        self._lock = threading.Lock()
        self._deadlock_cycles: List[List[int]] = []
        self._channel_owners: Dict[str, int] = {}  # channel_id → owner pid

    # ── public interface ────────────────────────────────────────────────

    def update(self, processes: list, channels: list, logger=None) -> None:
        """
        Rebuild the wait-for graph from current process and channel state.

        Parameters
        ----------
        processes : list of SimProcess
        channels : list of IPC channel objects (pipes, queues, shm)
        logger : Optional[IPCLogger] to rebuild ownership
        """
        with self._lock:
            self._graph.clear()
            self._channel_owners.clear()

            # Build mapping: channel → process that last wrote to it
            if logger:
                # Find the owner (last writer) for each channel
                for event in logger.get_events():
                    if event.event_type in ("write", "send"):
                        self._channel_owners[event.channel_id] = event.pid

            for proc in processes:
                self._graph.setdefault(proc.pid, set())

            # Determine who "holds" each channel
            from ipc_debugger.utils.constants import ProcessState
            for proc in processes:
                if proc.state == ProcessState.WAITING and proc.waiting_on:
                    # Look up true owner from logs, or fall back to heuristic
                    holder = self._channel_owners.get(proc.waiting_on)
                    if holder is None:
                        holder = self._find_holder(proc.waiting_on, processes, proc.pid)
                    if holder is not None and holder != proc.pid:
                        self._graph.setdefault(proc.pid, set()).add(holder)

    def detect(self) -> List[List[int]]:
        """
        Run cycle detection on the wait-for graph.

        Returns a list of cycles; each cycle is a list of PIDs.
        An empty list means no deadlock.
        """
        with self._lock:
            self._deadlock_cycles = self._find_cycles()
        return self._deadlock_cycles

    def clear(self) -> None:
        """Reset the internal wait-for graph and cached cycle list."""
        with self._lock:
            self._graph.clear()
            self._deadlock_cycles.clear()
            self._channel_owners.clear()

    def has_deadlock(self) -> bool:
        """Convenience: True if the last ``detect()`` found at least one cycle."""
        return len(self._deadlock_cycles) > 0

    def get_graph(self) -> Dict[int, Set[int]]:
        """Return a copy of the current wait-for graph."""
        with self._lock:
            return {k: set(v) for k, v in self._graph.items()}

    def get_cycles(self) -> List[List[int]]:
        """Return the cycles found by the last ``detect()``."""
        return list(self._deadlock_cycles)

    # ── internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _find_holder(channel_id: str, processes: list,
                     exclude_pid: int) -> Optional[int]:
        """
        Heuristic: find a process other than *exclude_pid* that is also
        interacting with the same channel (simulating resource contention).
        """
        from ipc_debugger.utils.constants import ProcessState
        for p in processes:
            if p.pid == exclude_pid:
                continue
            if p.state in (ProcessState.RUNNING, ProcessState.WAITING):
                if p.waiting_on == channel_id:
                    return p.pid
        # Fallback: check any running process
        for p in processes:
            if p.pid != exclude_pid and p.state == ProcessState.RUNNING:
                return p.pid
        return None

    def _find_cycles(self) -> List[List[int]]:
        """DFS-based cycle detection on the wait-for graph."""
        visited: Set[int] = set()
        rec_stack: Set[int] = set()
        cycles: List[List[int]] = []
        path: List[int] = []

        def dfs(node: int) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbour in self._graph.get(node, set()):
                if neighbour not in visited:
                    dfs(neighbour)
                elif neighbour in rec_stack:
                    # Found a cycle — extract it
                    idx = path.index(neighbour)
                    cycle = path[idx:] + [neighbour]
                    cycles.append(cycle)

            path.pop()
            rec_stack.discard(node)

        for node in list(self._graph.keys()):
            if node not in visited:
                dfs(node)

        return cycles
