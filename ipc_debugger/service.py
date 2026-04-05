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

from typing import List, Dict, Callable

from utils.constants import EventType, Scenario
from core.process import SimProcess
from simulation.event_manager import EventManager
from simulation.scheduler import Scheduler
from debugger.logger import IPCLogger, LogEvent
from debugger.deadlock_detector import DeadlockDetector
from debugger.race_condition import RaceConditionDetector, RaceWarning
from analytics.latency import LatencyTracker
from analytics.throughput import ThroughputTracker
from analytics.system_perf_tracker import SystemPerfTracker
from system_monitor.process_monitor import ProcessMonitor
from system_monitor.system_stats import SystemStats
from system_monitor.ipc_tracker import IPCTracker
from system_monitor.data_models import ProcessSnapshot, SystemStatsSnapshot


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

        # Periodically check for deadlocks
        self.deadlock_detector.update(
            self.scheduler.processes,
            list(self.scheduler.channels.values()),
            self.logger
        )
        cycles = self.deadlock_detector.detect()
        if cycles:
            self.event_manager.emit(EventType.DEADLOCK_DETECTED, cycles=cycles)

        # Check for shared-memory race conditions
        shm_logs = []
        for ch in self.scheduler.channels.values():
            if hasattr(ch, "get_access_log"):
                shm_logs.extend(ch.get_access_log())

        if shm_logs:
            warnings = self.race_detector.analyse(shm_logs)
            if warnings:
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
        self.scheduler.reset()

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
