"""
pipes.py — Pipe IPC implementations (unnamed and named).

Provides thread-safe pipe channels that support blocking reads,
buffered writes, and configurable delays for simulation purposes.

Interface:
    Pipe.write(data, sender_pid)  → None
    Pipe.read(reader_pid)         → str
    Pipe.close()                  → None
    Pipe.is_open                  → bool
"""

import threading
import time
from collections import deque
from typing import Optional, Callable

from utils.constants import IPCType, DEFAULT_PIPE_BUFFER_SIZE


class Pipe:
    """
    Unnamed (anonymous) pipe — uni-directional channel between two processes.

    Data written by a sender is buffered and read FIFO by the receiver.
    Reads block when the buffer is empty (simulating real pipe behaviour).
    """

    def __init__(self, pipe_id: str = "",
                 buffer_size: int = DEFAULT_PIPE_BUFFER_SIZE,
                 on_event: Optional[Callable] = None):
        self.pipe_id: str = pipe_id or f"pipe-{id(self)}"
        self.ipc_type: IPCType = IPCType.UNNAMED_PIPE
        self.buffer_size: int = buffer_size
        self._buffer: deque = deque()
        self._lock = threading.Lock()
        self._data_available = threading.Event()
        self._open: bool = True
        self._on_event: Optional[Callable] = on_event   # callback for logging

    # ── public interface ────────────────────────────────────────────────

    def write(self, data: str, sender_pid: int = 0) -> None:
        """Write *data* into the pipe (non-blocking)."""
        if not self._open:
            raise BrokenPipeError(f"Pipe '{self.pipe_id}' is closed")
        with self._lock:
            self._buffer.append(data)
            self._data_available.set()
        if self._on_event:
            self._on_event("write", self.pipe_id, sender_pid, data)

    def read(self, reader_pid: int = 0, timeout: float = 5.0) -> Optional[str]:
        """
        Read from the pipe.  Blocks up to *timeout* seconds while empty.
        Returns ``None`` on timeout.
        """
        if not self._open and not self._buffer:
            return None
        # Wait until data is available
        if not self._buffer:
            signalled = self._data_available.wait(timeout=timeout)
            if not signalled:
                return None  # timeout
        with self._lock:
            if self._buffer:
                data = self._buffer.popleft()
                if not self._buffer:
                    self._data_available.clear()
                if self._on_event:
                    self._on_event("read", self.pipe_id, reader_pid, data)
                return data
        return None

    def close(self) -> None:
        """Close the pipe. Subsequent writes will raise BrokenPipeError."""
        self._open = False
        self._data_available.set()   # unblock any waiting readers
        if self._on_event:
            self._on_event("close", self.pipe_id, 0, "")

    @property
    def is_open(self) -> bool:
        return self._open

    def __repr__(self) -> str:
        status = "open" if self._open else "closed"
        return f"<Pipe {self.pipe_id} [{status}] buf={len(self._buffer)}>"


class NamedPipe(Pipe):
    """
    Named pipe — like an unnamed pipe but identified by a human-readable name
    so that unrelated processes can connect to it by name.
    """

    def __init__(self, name: str,
                 buffer_size: int = DEFAULT_PIPE_BUFFER_SIZE,
                 on_event: Optional[Callable] = None):
        super().__init__(pipe_id=name, buffer_size=buffer_size,
                         on_event=on_event)
        self.ipc_type = IPCType.NAMED_PIPE
        self.name: str = name

    def __repr__(self) -> str:
        status = "open" if self._open else "closed"
        return f"<NamedPipe '{self.name}' [{status}] buf={len(self._buffer)}>"
