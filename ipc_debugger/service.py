"""
service.py — Service layer (Facade / Controller).

Acts as the single point of contact between the GUI and the underlying
core logic (simulation, debugging, analytics). Connects all components
together using the central EventManager and IPCLogger.
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


class IPCService:
    """Facade for the entire IPC Debugger backend."""

    def __init__(self):
        # 1. Core infrastructure
        self.event_manager = EventManager()
        self.logger = IPCLogger()

        # 2. Simulation engine
        self.scheduler = Scheduler(self.event_manager, self.logger)

        # 3. Debugging detectors
        self.deadlock_detector = DeadlockDetector()
        self.race_detector = RaceConditionDetector()

        # 4. Analytics trackers
        self.latency_tracker = LatencyTracker()
        self.throughput_tracker = ThroughputTracker()

        # Wire up the logger to feed the detectors/analytics
        self.logger.subscribe(self._on_log_event)

    # ── Internal wiring ──────────────────────────────────────────────────

    def _on_log_event(self, event: LogEvent) -> None:
        """Process an IPC event through our analytical components."""
        
        # Track analytics
        if event.event_type == "send" or event.event_type == "write":
            self.latency_tracker.record_send(event.channel_id, event.ts)
            self.throughput_tracker.record_event(event.channel_id, event.ts)
        elif event.event_type == "receive" or event.event_type == "read":
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
        # (We extract the access_log from all shared memory regions)
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

    # ── Data Retrieval (for GUI) ────────────────────────────────────────

    def get_processes(self) -> List[SimProcess]:
        """Return the current list of simulated processes."""
        return self.scheduler.processes

    def get_channels(self) -> Dict[str, str]:
        """Return a mapping of channel_id -> channel type string."""
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
