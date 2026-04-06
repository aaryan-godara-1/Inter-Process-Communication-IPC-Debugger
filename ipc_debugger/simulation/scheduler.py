"""
scheduler.py — Simulation scheduler.

Creates and manages SimProcess threads, orchestrates scenario setup,
and provides start / pause / step / reset controls.

Interface:
    Scheduler.load_scenario(scenario)  → None
    Scheduler.start()                  → None
    Scheduler.pause()                  → None
    Scheduler.step()                   → None
    Scheduler.reset()                  → None
"""

import threading
import time
from typing import List, Optional, Callable, Dict, Any

from ipc_debugger.utils.constants import (
    ProcessState, EventType, Scenario, DEFAULT_DELAY_MS
)
from ipc_debugger.utils.helpers import reset_pid_counter
from ipc_debugger.core.process import SimProcess
from ipc_debugger.core.pipes import Pipe, NamedPipe
from ipc_debugger.core.message_queue import MessageQueue
from ipc_debugger.core.shared_memory import SharedMemory
from ipc_debugger.simulation.event_manager import EventManager
from ipc_debugger.debugger.logger import IPCLogger


class Scheduler:
    """
    Simulation scheduler — the main orchestrator.

    Responsibilities:
        * Create processes and IPC channels for each scenario.
        * Coordinate start / pause / step / reset.
        * Broadcast lifecycle events via the EventManager.
    """

    def __init__(self, event_manager: EventManager, logger: IPCLogger):
        self.event_manager: EventManager = event_manager
        self.logger: IPCLogger = logger
        self.processes: List[SimProcess] = []
        self.channels: Dict[str, Any] = {}    # channel_id → channel obj
        self._running: bool = False
        self._delay_ms: int = DEFAULT_DELAY_MS
        self._current_scenario: Optional[Scenario] = None

    # ── public interface ────────────────────────────────────────────────

    def load_scenario(self, scenario: Scenario) -> None:
        """Tear down any running simulation and set up *scenario*."""
        self.reset()
        self._current_scenario = scenario
        if scenario == Scenario.NORMAL_FLOW:
            self._setup_normal_flow()
        elif scenario == Scenario.DEADLOCK:
            self._setup_deadlock()
        elif scenario == Scenario.BOTTLENECK:
            self._setup_bottleneck()

    def start(self) -> None:
        """Start (or resume) all processes."""
        self._running = True
        for proc in self.processes:
            if proc.state == ProcessState.READY:
                proc.start()
            elif proc.state == ProcessState.WAITING:
                proc.resume()
        self.event_manager.emit(EventType.SIMULATION_STARTED)

    def pause(self) -> None:
        """Pause all running processes."""
        self._running = False
        for proc in self.processes:
            if proc.state == ProcessState.RUNNING:
                proc.pause()
        self.event_manager.emit(EventType.SIMULATION_PAUSED)

    def step(self) -> None:
        """Execute one simulation step (resume briefly, then pause)."""
        self.start()
        time.sleep(self._delay_ms / 1000.0)
        self.pause()
        self.event_manager.emit(EventType.SIMULATION_STEP)

    def reset(self) -> None:
        """Stop all processes, destroy channels, and clear state."""
        for proc in self.processes:
            proc.stop()
        for proc in self.processes:
            proc.join(timeout=1.0)
        for ch in self.channels.values():
            if hasattr(ch, "close"):
                ch.close()
        self.processes.clear()
        self.channels.clear()
        self.logger.clear()
        self._delay_ms = DEFAULT_DELAY_MS
        reset_pid_counter()
        self._running = False
        self._current_scenario = None
        self.event_manager.emit(EventType.SIMULATION_RESET)

    def set_delay(self, ms: int) -> None:
        """Change the per-step delay for all processes."""
        self._delay_ms = ms
        for proc in self.processes:
            proc.delay_ms = ms

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_scenario(self) -> Optional[Scenario]:
        return self._current_scenario

    # ── scenario builders ───────────────────────────────────────────────

    def _on_event(self, event_type: str, channel_id: str,
                  pid: int, data: str) -> None:
        """Callback wired into every channel to feed the logger."""
        self.logger.log(event_type, channel_id, pid, data)

    def _on_state_change(self, proc: SimProcess,
                         old: ProcessState, new: ProcessState) -> None:
        """Broadcast process-state changes through the event bus."""
        self.event_manager.emit(
            EventType.STATE_CHANGED,
            pid=proc.pid, name=proc.name,
            old_state=old.name, new_state=new.name,
        )

    # -- Normal Flow scenario -----------------------------------------

    def _setup_normal_flow(self) -> None:
        """
        Simple producer-consumer flow:
          P1 ──pipe──▶ P2 ──queue──▶ P3 ──shm──▶ P4
        """
        pipe = Pipe("pipe-1", on_event=self._on_event)
        mq = MessageQueue("mq-1", on_event=self._on_event)
        shm = SharedMemory("shm-1", on_event=self._on_event)
        self.channels = {"pipe-1": pipe, "mq-1": mq, "shm-1": shm}

        def task_p1(proc: SimProcess):
            for i in range(5):
                if proc._stop_flag.is_set():
                    return
                proc.send(pipe, f"msg-{i}")

        def task_p2(proc: SimProcess):
            for _ in range(5):
                if proc._stop_flag.is_set():
                    return
                data = proc.receive(pipe)
                if data:
                    proc.send(mq, f"fwd:{data}")

        def task_p3(proc: SimProcess):
            for _ in range(5):
                if proc._stop_flag.is_set():
                    return
                data = proc.receive(mq)
                if data:
                    shm.write("result", data, proc.pid)

        def task_p4(proc: SimProcess):
            for _ in range(5):
                if proc._stop_flag.is_set():
                    return
                proc._simulate_delay()
                proc._wait_if_paused()
                val = shm.read("result", proc.pid)

        procs = [
            SimProcess("Producer", task=task_p1, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
            SimProcess("Forwarder", task=task_p2, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
            SimProcess("Writer", task=task_p3, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
            SimProcess("Reader", task=task_p4, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
        ]
        self.processes = procs

    # -- Deadlock scenario --------------------------------------------

    def _setup_deadlock(self) -> None:
        """
        True circular wait:
          P1 blocks waiting to receive from pipe-A  →  P2 is the conceptual holder
          P2 blocks waiting to receive from pipe-B  →  P1 is the conceptual holder

        The DeadlockDetector reads channel ownership from logger events.
        We seed those events *after* creating processes so that the real PIDs are used.
        Graph built:  P1 → P2 → P1  (cycle detected ✓)
        """
        pipe_a = Pipe("pipe-A", on_event=self._on_event)
        pipe_b = Pipe("pipe-B", on_event=self._on_event)
        pipe_c = Pipe("pipe-C", on_event=self._on_event)
        self.channels = {"pipe-A": pipe_a, "pipe-B": pipe_b, "pipe-C": pipe_c}

        def task_p1(proc: SimProcess):
            """P1 blocks waiting for data on pipe-A (which P2 can never send because P2 is also blocked)."""
            proc._waiting_on = "pipe-A"
            proc.receive(pipe_a, timeout=60)   # blocks indefinitely → deadlock

        def task_p2(proc: SimProcess):
            """P2 blocks waiting for data on pipe-B (which P1 can never send because P1 is also blocked)."""
            proc._waiting_on = "pipe-B"
            proc.receive(pipe_b, timeout=60)   # blocks indefinitely → deadlock

        def task_p3(proc: SimProcess):
            """P3 waits on pipe-C — nothing ever writes to it."""
            proc._waiting_on = "pipe-C"
            proc.receive(pipe_c, timeout=60)

        # Build processes first so we have real PIDs
        procs = [
            SimProcess("Process-1", task=task_p1, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
            SimProcess("Process-2", task=task_p2, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
            SimProcess("Process-3", task=task_p3, delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
        ]
        self.processes = procs

        pid_p1 = procs[0].pid   # e.g. 1
        pid_p2 = procs[1].pid   # e.g. 2

        # Seed ownership:
        #   pipe-A is "held" by P2  →  P1 waits for P2  →  edge P1 → P2
        #   pipe-B is "held" by P1  →  P2 waits for P1  →  edge P2 → P1
        self.logger.log("write", "pipe-A", pid_p2, "HOLDER_SEED")
        self.logger.log("write", "pipe-B", pid_p1, "HOLDER_SEED")


    # -- Bottleneck scenario ------------------------------------------

    def _setup_bottleneck(self) -> None:
        """
        Multiple producers flood a single message queue that one slow
        consumer reads from.
        """
        mq = MessageQueue("mq-bottleneck", max_size=10,
                          on_event=self._on_event)
        self.channels = {"mq-bottleneck": mq}

        def make_producer(idx: int):
            def task(proc: SimProcess):
                for i in range(10):
                    if proc._stop_flag.is_set():
                        return
                    proc.send(mq, f"P{idx}-msg-{i}")
            return task

        def task_consumer(proc: SimProcess):
            for _ in range(30):
                if proc._stop_flag.is_set():
                    return
                # Slow consumer — double delay
                proc._simulate_delay()
                proc._simulate_delay()
                proc.receive(mq)

        procs = [
            SimProcess("FastProd-1", task=make_producer(1),
                       delay_ms=max(100, self._delay_ms // 3),
                       on_state_change=self._on_state_change),
            SimProcess("FastProd-2", task=make_producer(2),
                       delay_ms=max(100, self._delay_ms // 3),
                       on_state_change=self._on_state_change),
            SimProcess("FastProd-3", task=make_producer(3),
                       delay_ms=max(100, self._delay_ms // 3),
                       on_state_change=self._on_state_change),
            SimProcess("SlowConsumer", task=task_consumer,
                       delay_ms=self._delay_ms,
                       on_state_change=self._on_state_change),
        ]
        self.processes = procs
