"""
process.py — Simulated process model.

Each SimProcess represents a lightweight OS process with a PID that can
send and receive data over IPC channels.  Processes run in their own
threads and follow a user-defined task function.

Interface:
    SimProcess.start()                         → None
    SimProcess.pause() / .resume()             → None
    SimProcess.send(channel, data)             → None
    SimProcess.receive(channel)                → str | None
    SimProcess.state                           → ProcessState
"""

import threading
import time
from typing import Optional, Callable, Any

from ipc_debugger.utils.constants import ProcessState, DEFAULT_DELAY_MS
from ipc_debugger.utils.helpers import generate_pid


class SimProcess:
    """
    A simulated OS process.

    Parameters
    ----------
    name : str
        Human-readable label (e.g. "Producer-1").
    task : callable
        Function ``task(process)`` executed in the process's thread.
    delay_ms : int
        Artificial delay (ms) inserted between actions, modelling CPU time.
    on_state_change : callable, optional
        Notified whenever the process changes state.
    """

    def __init__(self, name: str,
                 task: Optional[Callable] = None,
                 delay_ms: int = DEFAULT_DELAY_MS,
                 on_state_change: Optional[Callable] = None):
        self.pid: int = generate_pid()
        self.name: str = name
        self.delay_ms: int = delay_ms
        self._state: ProcessState = ProcessState.READY
        self._task: Optional[Callable] = task
        self._thread: Optional[threading.Thread] = None
        self._pause_event = threading.Event()
        self._pause_event.set()       # not paused by default
        self._stop_flag = threading.Event()
        self._on_state_change: Optional[Callable] = on_state_change
        self._lock = threading.Lock()
        self._waiting_on: Optional[str] = None   # channel id being waited on

    # ── state property ──────────────────────────────────────────────────

    @property
    def state(self) -> ProcessState:
        return self._state

    @state.setter
    def state(self, new_state: ProcessState) -> None:
        old = self._state
        self._state = new_state
        if self._on_state_change and old != new_state:
            self._on_state_change(self, old, new_state)

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the process thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._pause_event.set()
        self.state = ProcessState.RUNNING
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"Process-{self.pid}")
        self._thread.start()

    def pause(self) -> None:
        """Pause execution (the thread blocks until resumed)."""
        self._pause_event.clear()
        self.state = ProcessState.WAITING

    def resume(self) -> None:
        """Resume a paused process."""
        self._pause_event.set()
        self.state = ProcessState.RUNNING

    def stop(self) -> None:
        """Signal the process to terminate."""
        self._stop_flag.set()
        self._pause_event.set()     # unblock if paused
        self.state = ProcessState.TERMINATED

    def join(self, timeout: float = 2.0) -> None:
        """Wait for the thread to finish."""
        if self._thread:
            self._thread.join(timeout=timeout)

    # ── IPC helpers (used by task functions) ─────────────────────────────

    def send(self, channel: Any, data: str) -> None:
        """Send *data* through *channel* (pipe, queue, or shared memory)."""
        self._check_alive()
        self._wait_if_paused()
        self._simulate_delay()
        # Dispatch by channel type
        if hasattr(channel, "write"):
            channel.write(data, sender_pid=self.pid)
        elif hasattr(channel, "send_message"):
            channel.send_message(data, sender_pid=self.pid)
        else:
            raise TypeError(f"Unsupported channel type: {type(channel)}")

    def receive(self, channel: Any, timeout: float = 5.0) -> Optional[str]:
        """Receive data from *channel*.  Returns None on timeout."""
        self._check_alive()
        self._wait_if_paused()
        self._waiting_on = getattr(channel, "pipe_id",
                                   getattr(channel, "queue_id",
                                           getattr(channel, "shm_id", "?")))
        self.state = ProcessState.WAITING
        if hasattr(channel, "read"):
            result = channel.read(reader_pid=self.pid, timeout=timeout) \
                if "timeout" in channel.read.__code__.co_varnames \
                else channel.read(self.pid)
        elif hasattr(channel, "receive_message"):
            msg = channel.receive_message(reader_pid=self.pid, timeout=timeout)
            result = msg.data if msg else None
        else:
            raise TypeError(f"Unsupported channel type: {type(channel)}")
        self._waiting_on = None
        if not self._stop_flag.is_set():
            self.state = ProcessState.RUNNING
        return result

    @property
    def waiting_on(self) -> Optional[str]:
        """Channel the process is currently blocked on, if any."""
        return self._waiting_on

    # ── internal ────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Thread entry point — executes the user-supplied task."""
        try:
            if self._task:
                self._task(self)
        except Exception as exc:
            print(f"[Process {self.pid}] task error: {exc}")
        finally:
            if self._state != ProcessState.DEADLOCKED:
                self.state = ProcessState.TERMINATED

    def _simulate_delay(self) -> None:
        """Insert the configurable artificial delay."""
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)

    def _wait_if_paused(self) -> None:
        """Block if the process has been paused."""
        self._pause_event.wait()

    def _check_alive(self) -> None:
        """Raise if the process has been stopped."""
        if self._stop_flag.is_set():
            raise RuntimeError(f"Process {self.pid} has been terminated")

    # ── dunder ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<SimProcess pid={self.pid} name='{self.name}' state={self._state.name}>"
