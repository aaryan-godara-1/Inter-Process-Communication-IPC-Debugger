"""
service.py — Service layer (Facade / Controller).

Acts as the single point of contact between the GUI and the underlying
core logic (simulation, live monitoring, debugging, analytics). Connects
all components together using the central EventManager and IPCLogger.

Two modes:
    Live Monitor  — psutil-backed real OS data (system_monitor/)
    Simulation    — thread-based IPC scenarios (simulation/)

Both modes share the same EventManager bus.
"""

import time
from dataclasses import dataclass
from typing import List, Dict, Callable, Any

from ipc_debugger.utils.constants import EventType, Scenario, ProcessState
from ipc_debugger.core.process import SimProcess
from ipc_debugger.simulation.event_manager import EventManager
from ipc_debugger.simulation.scheduler import Scheduler
from ipc_debugger.debugger.logger import IPCLogger, LogEvent
from ipc_debugger.debugger.deadlock_detector import DeadlockDetector
from ipc_debugger.debugger.race_condition import RaceConditionDetector, RaceWarning
from ipc_debugger.analytics.latency import LatencyTracker
from ipc_debugger.analytics.throughput import ThroughputTracker
from ipc_debugger.analytics.system_perf_tracker import SystemPerfTracker
from ipc_debugger.system_monitor.process_monitor import ProcessMonitor
from ipc_debugger.system_monitor.system_stats import SystemStats
from ipc_debugger.system_monitor.ipc_tracker import IPCTracker
from ipc_debugger.system_monitor.data_models import ProcessSnapshot, SystemStatsSnapshot


@dataclass(frozen=True)
class SimulationReport:
    """Structured summary of a completed or partially completed simulation run."""

    scenario: str
    completed: bool
    timed_out: bool
    process_states: Dict[int, str]
    channels: Dict[str, str]
    deadlock_cycles: List[List[int]]
    latency_ms: Dict[str, float]
    throughput_msg_s: Dict[str, float]
    bottlenecks: List[str]
    race_warnings: List[str]
    logged_events: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "completed": self.completed,
            "timed_out": self.timed_out,
            "process_states": dict(self.process_states),
            "channels": dict(self.channels),
            "deadlock_cycles": [list(cycle) for cycle in self.deadlock_cycles],
            "latency_ms": dict(self.latency_ms),
            "throughput_msg_s": dict(self.throughput_msg_s),
            "bottlenecks": list(self.bottlenecks),
            "race_warnings": list(self.race_warnings),
            "logged_events": self.logged_events,
        }


class IPCService:
    """Facade for the entire IPC Debugger / Live Monitor backend."""

    def __init__(self):
        # 1. Core infrastructure (shared by both modes)
        self.event_manager = EventManager()
        self.logger = IPCLogger()

        # 2. Simulation engine
        self.scheduler = Scheduler(self.event_manager, self.logger)

        # 3. Debugging detectors (simulation mode)
        self.deadlock_detector = DeadlockDetector()
        self.race_detector = RaceConditionDetector()

        # 4. Simulation analytics
        self.latency_tracker = LatencyTracker()
        self.throughput_tracker = ThroughputTracker()

        # 5. Live monitor components (real OS data)
        self.process_monitor = ProcessMonitor(self.event_manager)
        self.system_stats = SystemStats(self.event_manager)
        self.ipc_tracker = IPCTracker(self.event_manager)

        # 6. System performance history (for dashboard charts)
        self.perf_tracker = SystemPerfTracker(capacity=120)

        # Wire up the simulation logger → detectors/analytics
        self.logger.subscribe(self._on_log_event)

        # Wire system-stats updates into perf tracker
        self.event_manager.subscribe(
            EventType.SYSTEM_STATS_UPDATE, self._on_system_stats
        )

        # Track live mode state
        self._live_mode_active: bool = False

    # ── Internal wiring ──────────────────────────────────────────────────

    def _on_log_event(self, event: LogEvent) -> None:
        """Process an IPC event through our analytical components."""

        # Track analytics
        if event.event_type in ("send", "write"):
            self.latency_tracker.record_send(event.channel_id, event.ts)
            self.throughput_tracker.record_event(event.channel_id, event.ts)
        elif event.event_type in ("receive", "read"):
            self.latency_tracker.record_receive(event.channel_id, event.ts)
            self.throughput_tracker.record_event(event.channel_id, event.ts)

        self._refresh_detectors(emit_events=True)

    def _refresh_detectors(self, emit_events: bool) -> None:
        """Rebuild detector state from the current simulation snapshot."""

        # Periodically check for deadlocks
        self.deadlock_detector.update(
            self.scheduler.processes,
            list(self.scheduler.channels.values()),
            self.logger
        )
        cycles = self.deadlock_detector.detect()
        if emit_events and cycles:
            self.event_manager.emit(EventType.DEADLOCK_DETECTED, cycles=cycles)

        # Check for shared-memory race conditions
        shm_logs = []
        for ch in self.scheduler.channels.values():
            if hasattr(ch, "get_access_log"):
                shm_logs.extend(ch.get_access_log())

        if shm_logs:
            warnings = self.race_detector.analyse(shm_logs)
            if emit_events and warnings:
                self.event_manager.emit(
                    EventType.RACE_CONDITION_DETECTED, warnings=warnings
                )

    def _on_system_stats(self, stats: SystemStatsSnapshot, **_) -> None:
        """Feed system stats snapshots into the performance history ring buffer."""
        self.perf_tracker.record(stats)

    # ── Live Monitor Controls ────────────────────────────────────────────

    def start_live_mode(self,
                        process_interval: float = 1.5,
                        stats_interval: float = 2.0,
                        ipc_interval: float = 4.0) -> None:
        """Start all real OS monitoring components."""
        if self._live_mode_active:
            return
        self._live_mode_active = True
        self.process_monitor.start(process_interval)
        self.system_stats.start(stats_interval)
        self.ipc_tracker.start(ipc_interval)
        self.event_manager.emit(EventType.MODE_SWITCHED, mode="live")

    def stop_live_mode(self) -> None:
        """Stop all real OS monitoring components."""
        if not self._live_mode_active:
            return
        self._live_mode_active = False
        self.process_monitor.stop()
        self.system_stats.stop()
        self.ipc_tracker.stop()

    @property
    def is_live_mode(self) -> bool:
        return self._live_mode_active

    # ── Live Monitor Data Retrieval ──────────────────────────────────────

    def get_live_processes(self) -> List[ProcessSnapshot]:
        """Return the latest real process snapshots."""
        return self.process_monitor.get_snapshots()

    def get_live_process_tree(self) -> Dict[int, List[int]]:
        """Return {parent_pid: [child_pids]} for the live process list."""
        return self.process_monitor.get_process_tree()

    def get_live_connections(self):
        """Return the latest detected IPC connections."""
        return self.ipc_tracker.get_connections()

    def get_system_stats(self):
        """Return the latest system stats snapshot."""
        return self.system_stats.get_latest()

    def get_perf_history(self) -> SystemPerfTracker:
        """Return the performance history ring buffer."""
        return self.perf_tracker

    # ── Simulation Controls (for GUI) ───────────────────────────────────

    def load_scenario(self, scenario: Scenario) -> None:
        """Load a predefined simulation scenario."""
        self.latency_tracker.clear()
        self.throughput_tracker.clear()
        self.race_detector.clear()
        self.deadlock_detector.clear()
        self.perf_tracker.clear()
        self.scheduler.load_scenario(scenario)

    def start(self) -> None:
        """Start or resume the simulation."""
        self.scheduler.start()

    def pause(self) -> None:
        """Pause the simulation."""
        self.scheduler.pause()

    def step(self) -> None:
        """Execute exactly one simulation step."""
        self.scheduler.step()

    def reset(self) -> None:
        """Reset the simulation back to initial state."""
        self.latency_tracker.clear()
        self.throughput_tracker.clear()
        self.race_detector.clear()
        self.deadlock_detector.clear()
        self.perf_tracker.clear()
        self.scheduler.reset()

    def wait_for_completion(self, timeout: float = 10.0,
                             poll_interval: float = 0.05) -> bool:
        """Block until every process terminates, or return False on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            processes = self.get_processes()
            if not processes:
                return True
            if all(
                proc.state in (ProcessState.TERMINATED, ProcessState.DEADLOCKED)
                for proc in processes
            ):
                return True
            time.sleep(poll_interval)
        return False

    def build_report(self, scenario: Scenario | None = None,
                     timed_out: bool = False) -> SimulationReport:
        """Create a structured summary of the current backend state."""
        self._refresh_detectors(emit_events=False)
        scenario_name = scenario.value if scenario else (
            self.scheduler.current_scenario.value if self.scheduler.current_scenario else "Unknown"
        )
        return SimulationReport(
            scenario=scenario_name,
            completed=not timed_out,
            timed_out=timed_out,
            process_states={proc.pid: proc.state.name for proc in self.get_processes()},
            channels=self.get_channels(),
            deadlock_cycles=self.get_deadlock_cycles(),
            latency_ms=self.latency_tracker.get_all_avg_latencies(),
            throughput_msg_s=self.throughput_tracker.get_all_throughputs(),
            bottlenecks=self.throughput_tracker.get_bottlenecks(),
            race_warnings=[warning.message for warning in self.race_detector.get_warnings()],
            logged_events=len(self.logger),
        )

    def run_scenario(self, scenario: Scenario, delay_ms: int = 10,
                     timeout: float = 10.0) -> SimulationReport:
        """Run a scenario headlessly and return a structured result."""
        self.load_scenario(scenario)
        self.set_speed(delay_ms)
        self.start()
        completed = self.wait_for_completion(timeout=timeout)
        self.pause()
        return self.build_report(scenario=scenario, timed_out=not completed)

    def set_speed(self, delay_ms: int) -> None:
        """Adjust simulation execution speed."""
        self.scheduler.set_delay(delay_ms)

    # ── Simulation Data Retrieval (for GUI) ─────────────────────────────

    def get_processes(self) -> List[SimProcess]:
        """Return the current list of simulated processes."""
        return self.scheduler.processes

    def get_channels(self) -> Dict[str, str]:
        """Return a mapping of channel_id → channel type string."""
        return {
            ch_id: ch.ipc_type.name
            for ch_id, ch in self.scheduler.channels.items()
        }

    def get_deadlock_cycles(self) -> List[List[int]]:
        """Return the list of process IDs involved in a deadlock."""
        return self.deadlock_detector.get_cycles()

    def subscribe_to_events(self, event_type: EventType,
                            callback: Callable) -> None:
        """Register a callback for system events."""
        self.event_manager.subscribe(event_type, callback)

    def subscribe_to_logs(self, callback: Callable) -> None:
        """Register a callback for real-time IPC logs."""
        self.logger.subscribe(callback)
