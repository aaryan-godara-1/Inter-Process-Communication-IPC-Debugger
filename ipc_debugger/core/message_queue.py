"""
message_queue.py — Message Queue IPC implementation.

Wraps a priority-aware queue that allows processes to send and receive
messages with optional priority levels.

Interface:
    MessageQueue.send_message(data, sender_pid, priority)  → None
    MessageQueue.receive_message(reader_pid, timeout)       → Message | None
    MessageQueue.peek()                                     → Message | None
    MessageQueue.size()                                     → int
"""

import threading
import queue
from dataclasses import dataclass, field
from typing import Optional, Callable

from ipc_debugger.utils.constants import IPCType, DEFAULT_QUEUE_MAX_SIZE
from ipc_debugger.utils.helpers import timestamp


@dataclass(order=True)
class Message:
    """A single message in the queue.  Ordered by priority (lower = higher)."""
    priority: int
    data: str = field(compare=False)
    sender_pid: int = field(compare=False, default=0)
    timestamp: float = field(compare=False, default_factory=timestamp)


class MessageQueue:
    """
    Thread-safe message queue with optional priority ordering.

    Messages are stored in a ``PriorityQueue`` so that lower-priority
    numbers are dequeued first, mimicking a real OS message queue.
    """

    def __init__(self, queue_id: str = "",
                 max_size: int = DEFAULT_QUEUE_MAX_SIZE,
                 on_event: Optional[Callable] = None):
        self.queue_id: str = queue_id or f"mq-{id(self)}"
        self.ipc_type: IPCType = IPCType.MESSAGE_QUEUE
        self.max_size: int = max_size
        self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_size)
        self._lock = threading.Lock()
        self._on_event: Optional[Callable] = on_event
        self._open: bool = True

    # ── public interface ────────────────────────────────────────────────

    def send_message(self, data: str, sender_pid: int = 0,
                     priority: int = 5) -> None:
        """Enqueue a message.  Blocks if the queue is full."""
        if not self._open:
            raise RuntimeError(f"MessageQueue '{self.queue_id}' is closed")
        msg = Message(priority=priority, data=data, sender_pid=sender_pid)
        self._queue.put(msg, timeout=5.0)
        if self._on_event:
            self._on_event("send", self.queue_id, sender_pid, data)

    def receive_message(self, reader_pid: int = 0,
                        timeout: float = 5.0) -> Optional[Message]:
        """Dequeue the highest-priority message.  Returns None on timeout."""
        try:
            msg = self._queue.get(timeout=timeout)
            if self._on_event:
                self._on_event("receive", self.queue_id, reader_pid, msg.data)
            return msg
        except queue.Empty:
            return None

    def peek(self) -> Optional[Message]:
        """Return the next message without removing it, or None if empty."""
        with self._lock:
            # PriorityQueue has no peek — briefly get and re-put
            try:
                msg = self._queue.get_nowait()
                self._queue.put(msg)
                return msg
            except queue.Empty:
                return None

    def size(self) -> int:
        """Current number of messages in the queue."""
        return self._queue.qsize()

    def close(self) -> None:
        """Close the queue."""
        self._open = False
        if self._on_event:
            self._on_event("close", self.queue_id, 0, "")

    @property
    def is_open(self) -> bool:
        return self._open

    def __repr__(self) -> str:
        status = "open" if self._open else "closed"
        return f"<MessageQueue {self.queue_id} [{status}] size={self.size()}>"
