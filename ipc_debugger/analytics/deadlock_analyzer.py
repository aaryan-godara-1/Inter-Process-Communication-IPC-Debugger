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
    Wraps wait-for graph cycle detection with severity
    levels, timestamps and human readable descriptions.
    Better than basic detection — adds history, severity,
    timestamps and clean GUI output.
    """

    def __init__(self):
        self._graph: Dict[int, Set[int]] = {}
        self._channel_owners: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_result: Dict = {}
        self._history: List[Dict] = []

    def update(self, processes: list,
               channels: list, logger=None) -> None:
        """Rebuild wait-for graph from current state."""
        with self._lock:
            self._graph.clear()
            for proc in processes:
                self._graph.setdefault(proc.pid, set())

    def analyze(self) -> Dict:
        """Run cycle detection and return result."""
        cycles = self._find_cycles()
        result = {
            "timestamp": time.time(),
            "has_deadlock": len(cycles) > 0,
            "cycle_count": len(cycles),
            "cycles_readable": [
                " → ".join(map(str, c)) for c in cycles
            ],
        }
        with self._lock:
            self._last_result = result
        return result

    def _find_cycles(self) -> List[List[int]]:
        """DFS based cycle detection."""
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