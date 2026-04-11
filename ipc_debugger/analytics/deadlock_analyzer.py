"""
deadlock_analyzer.py — Enhanced deadlock analysis for IPC Debugger.

Builds on wait-for graph cycle detection with improved
structured output, timestamps and severity levels for the GUI.

Interface:
    DeadlockAnalyzer.update(processes, channels, logger) → None
    DeadlockAnalyzer.analyze()                           → dict
    DeadlockAnalyzer.get_report()                        → dict
    DeadlockAnalyzer.get_history()                       → list[dict]
"""

import time
import threading
from typing import Dict, List, Set, Optional


class DeadlockAnalyzer:
    """
    Enhanced deadlock detection with structured GUI output.
    Adds history, severity levels, timestamps and
    human readable descriptions on top of base detection.
    """

    def __init__(self):
        self._graph: Dict[int, Set[int]] = {}
        self._channel_owners: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_result: Dict = {}
        self._history: List[Dict] = []

    def update(self, processes: list,
               channels: list, logger=None) -> None:
        """Rebuild wait-for graph from current process and channel state."""
        with self._lock:
            self._graph.clear()
            self._channel_owners.clear()

            if logger:
                for event in logger.get_events():
                    if event.event_type in ("write", "send"):
                        self._channel_owners[event.channel_id] = event.pid

            for proc in processes:
                self._graph.setdefault(proc.pid, set())

            try:
                from utils.constants import ProcessState
                for proc in processes:
                    if proc.state == ProcessState.WAITING and proc.waiting_on:
                        holder = self._channel_owners.get(proc.waiting_on)
                        if holder is None:
                            holder = self._find_holder(
                                proc.waiting_on, processes, proc.pid)
                        if holder and holder != proc.pid:
                            self._graph[proc.pid].add(holder)
            except ImportError:
                pass

    def analyze(self) -> Dict:
        """Run cycle detection and return fully structured result for GUI."""
        cycles = self._find_cycles()
        severity = self._compute_severity(cycles)

        result = {
            "timestamp": time.time(),
            "has_deadlock": len(cycles) > 0,
            "severity": severity,
            "cycle_count": len(cycles),
            "cycles_raw": cycles,
            "cycles_readable": [
                " → ".join(map(str, c)) for c in cycles
            ],
            "processes_involved": list({
                pid for cycle in cycles for pid in cycle
            }),
            "graph_size": len(self._graph),
            "graph": {k: list(v) for k, v in self._graph.items()}
        }

        with self._lock:
            self._last_result = result
            self._history.append(result)

        return result

    def get_report(self) -> Dict:
        """Return last analysis result for GUI."""
        with self._lock:
            return self._last_result

    def get_history(self) -> List[Dict]:
        """Return full history of all analysis runs."""
        with self._lock:
            return list(self._history)

    def has_deadlock(self) -> bool:
        """True if last analyze() found a deadlock."""
        return self._last_result.get("has_deadlock", False)

    def clear(self) -> None:
        """Reset everything."""
        with self._lock:
            self._graph.clear()
            self._channel_owners.clear()
            self._last_result = {}
            self._history.clear()

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _find_holder(channel_id: str, processes: list,
                     exclude_pid: int) -> Optional[int]:
        """Heuristic fallback to find which process holds a channel."""
        try:
            from utils.constants import ProcessState
            for p in processes:
                if p.pid == exclude_pid:
                    continue
                if p.state in (ProcessState.RUNNING, ProcessState.WAITING):
                    if p.waiting_on == channel_id:
                        return p.pid
            for p in processes:
                if p.pid != exclude_pid and p.state == ProcessState.RUNNING:
                    return p.pid
        except ImportError:
            pass
        return None

    def _compute_severity(self, cycles: List) -> str:
        """Rate severity based on number of deadlock cycles."""
        if len(cycles) == 0:
            return "OK"
        elif len(cycles) == 1:
            return "CRITICAL"
        else:
            return "CRITICAL — MULTIPLE DEADLOCKS"

    def _find_cycles(self) -> List[List[int]]:
        """DFS based cycle detection on the wait-for graph."""
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
                    idx = path.index(neighbour)
                    cycles.append(path[idx:] + [neighbour])
            path.pop()
            rec_stack.discard(node)

        for node in list(self._graph.keys()):
            if node not in visited:
                dfs(node)
        return cycles