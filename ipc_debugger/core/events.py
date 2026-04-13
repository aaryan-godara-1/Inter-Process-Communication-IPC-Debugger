"""
Core IPC event model with kernel-captured data structures.

This module defines the unified event model that represents all IPC events
captured from the kernel across different resource types.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional, Any, Dict, List


class IPCType(str, Enum):
    """IPC resource types supported by the debugger."""
    PIPE = "pipe"
    NAMED_PIPE = "named_pipe"
    UNIX_SOCKET = "unix_socket"
    TCP_SOCKET = "tcp_socket"
    UDP_SOCKET = "udp_socket"
    UDS_DATAGRAM = "uds_datagram"
    SHARED_MEMORY = "shared_memory"
    MMAP = "mmap"
    MUTEX = "mutex"
    SEMAPHORE = "semaphore"
    RWLOCK = "rwlock"
    FUTEX = "futex"
    EVENTFD = "eventfd"
    SIGNALFD = "signalfd"
    TIMERFD = "timerfd"
    MESSAGE_QUEUE = "message_queue"
    FILE_DESCRIPTOR = "file_descriptor"
    SIGNAL = "signal"
    CONDITION_VAR = "condition_var"
    BARRIER = "barrier"
    EPOLL = "epoll"
    KQUEUE = "kqueue"
    IOURING = "iouring"


class EventType(str, Enum):
    """IPC event operation types."""
    # Send/Receive
    SEND = "SEND"
    RECV = "RECV"
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    
    # Lock operations
    ACQUIRE = "ACQUIRE"
    RELEASE = "RELEASE"
    LOCK_TRY = "LOCK_TRY"
    UNLOCK = "UNLOCK"
    
    # Wait/Signal
    WAIT = "WAIT"
    SIGNAL = "SIGNAL"
    NOTIFY_ONE = "NOTIFY_ONE"
    NOTIFY_ALL = "NOTIFY_ALL"
    
    # Queue operations
    ENQUEUE = "ENQUEUE"
    DEQUEUE = "DEQUEUE"
    
    # Memory operations
    ATTACH = "ATTACH"
    DETACH = "DETACH"
    MAP = "MAP"
    UNMAP = "UNMAP"
    
    # Resource lifecycle
    CREATE = "CREATE"
    DESTROY = "DESTROY"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    
    # Polling events
    POLL_WAIT = "POLL_WAIT"
    POLL_WOKEN = "POLL_WOKEN"


class EventResult(str, Enum):
    """Outcome of an IPC event."""
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    QUEUED = "QUEUED"
    PARTIAL = "PARTIAL"


class EventSource(str, Enum):
    """Data provenance: where did this event come from?"""
    KERNEL = "KERNEL"              # Captured directly from kernel
    USERSPACE_HOOK = "USERSPACE_HOOK"  # Instrumented user library
    INFERRED = "INFERRED"          # Guessed from other events


@dataclass
class IPCEvent:
    """
    A single IPC event captured from the kernel.
    
    This is the atomic unit of all IPC debugging analysis.
    Every event carries timing, context, and causality information.
    """
    
    # Metadata
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ns: int = field(default_factory=lambda: int(time.time_ns()))
    correlation_id: str = ""  # Links related events across processes
    
    # Context
    process_id: int = 0
    thread_id: int = 0
    parent_process_id: Optional[int] = None
    process_name: str = ""
    thread_name: str = ""
    
    # IPC Details
    ipc_type: IPCType = IPCType.PIPE
    resource_id: str = ""  # Handle, FD, or memory address
    event_type: EventType = EventType.SEND
    
    # Payload
    payload_size: int = 0
    payload_hash: str = ""  # SHA256 for dedup
    payload_preview: str = ""  # First N bytes (base64 or masked)
    payload_masked: bool = False
    
    # Timing
    latency_ns: int = 0  # Wait time if blocking
    cpu_cycles: Optional[int] = None
    duration_ns: int = 0  # For operations spanning time
    
    # Status
    result: EventResult = EventResult.SUCCESS
    error_code: Optional[int] = None
    error_message: str = ""
    
    # Flags
    is_blocking: bool = False
    retry_count: int = 0  # 0 for first attempt
    is_timeout: bool = False
    
    # Source tracking
    source: EventSource = EventSource.KERNEL
    confidence: float = 100.0  # 0-100%
    
    # Related events
    parent_event_id: Optional[str] = None  # For causality chains
    child_event_ids: List[str] = field(default_factory=list)
    
    # Metadata
    tags: Dict[str, str] = field(default_factory=dict)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, preserving enums."""
        d = asdict(self)
        d['ipc_type'] = self.ipc_type.value
        d['event_type'] = self.event_type.value
        d['result'] = self.result.value
        d['source'] = self.source.value
        return d
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> IPCEvent:
        """Reconstruct from dictionary."""
        # Convert string enums back
        data = data.copy()
        if isinstance(data.get('ipc_type'), str):
            data['ipc_type'] = IPCType(data['ipc_type'])
        if isinstance(data.get('event_type'), str):
            data['event_type'] = EventType(data['event_type'])
        if isinstance(data.get('result'), str):
            data['result'] = EventResult(data['result'])
        if isinstance(data.get('source'), str):
            data['source'] = EventSource(data['source'])
        return IPCEvent(**data)


@dataclass
class CausalChain:
    """
    A sequence of related IPC events forming a causal dependency chain.
    
    Examples:
    - Process A sends msg → Process B receives msg → Process B sends response → Process A receives response
    - Process A acquires mutex → waits on condition var → Process B signals condition var → Process A resumes
    """
    
    chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at_ns: int = field(default_factory=lambda: int(time.time_ns()))
    
    # Endpoints
    start_event_id: str = ""
    end_event_id: str = ""
    
    # Events in order
    event_ids: List[str] = field(default_factory=list)
    process_path: List[int] = field(default_factory=list)  # PIDs traversed
    
    # Metrics
    total_latency_ns: int = 0
    hop_count: int = 0
    
    # Classification
    chain_type: str = "unknown"  # request-response, producer-consumer, lock-wait, etc.
    is_complete: bool = False
    completion_time_ns: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LockEvent:
    """Tracks lock acquisition, release, and waiter information."""
    
    lock_id: str
    lock_type: IPCType  # MUTEX, SEMAPHORE, FUTEX, RWLOCK, etc.
    
    owner_pid: int
    owner_tid: int
    acquire_time_ns: int
    release_time_ns: Optional[int] = None
    
    acquired_in_event_id: str = ""
    released_in_event_id: str = ""
    
    waiters: List[WaitEntry] = field(default_factory=list)
    lock_value: Optional[int] = None  # For semaphores
    
    def is_held(self) -> bool:
        return self.release_time_ns is None
    
    def held_duration_ns(self) -> int:
        if not self.is_held():
            return (self.release_time_ns or 0) - self.acquire_time_ns
        return int(time.time_ns()) - self.acquire_time_ns


@dataclass
class WaitEntry:
    """Tracks a thread waiting on a lock."""
    
    waiter_pid: int
    waiter_tid: int
    wait_start_ns: int
    wait_end_ns: Optional[int] = None
    
    wait_reason: str = "lock_contention"
    is_resolved: bool = False
    
    def wait_duration_ns(self) -> int:
        if not self.is_resolved:
            return int(time.time_ns()) - self.wait_start_ns
        return (self.wait_end_ns or 0) - self.wait_start_ns


@dataclass
class DeadlockCycle:
    """Detected deadlock cycle in lock graph."""
    
    cycle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detected_at_ns: int = field(default_factory=lambda: int(time.time_ns()))
    
    processes: List[int] = field(default_factory=list)
    locks: List[str] = field(default_factory=list)
    
    # Describes the cycle: PID -> LOCK -> waiting for PID -> LOCK -> ...
    path: List[Dict[str, Any]] = field(default_factory=list)
    
    severity: str = "high"  # low, medium, high, critical
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IPCEventBuffer:
    """
    Ring buffer for storing IPC events in memory.
    
    Supports:
    - Efficient circular storage with overflow handling
    - Time-based queries
    - Process-based queries
    """
    
    def __init__(self, max_events: int = 100000):
        self.max_events = max_events
        self.events: List[IPCEvent] = []
        self.next_index = 0
        self.is_full = False
    
    def add_event(self, event: IPCEvent) -> None:
        """Add an event to the buffer."""
        if len(self.events) < self.max_events:
            self.events.append(event)
        else:
            self.is_full = True
            self.events[self.next_index] = event
        
        self.next_index = (self.next_index + 1) % self.max_events
    
    def get_events_after(self, timestamp_ns: int) -> List[IPCEvent]:
        """Get all events after a given timestamp."""
        return [e for e in self.events if e.timestamp_ns > timestamp_ns]
    
    def get_events_by_process(self, pid: int) -> List[IPCEvent]:
        """Get all events involving a process."""
        return [e for e in self.events if e.process_id == pid]
    
    def get_events_by_resource(self, resource_id: str) -> List[IPCEvent]:
        """Get all events involving a resource."""
        return [e for e in self.events if e.resource_id == resource_id]
    
    def get_latest_n(self, n: int) -> List[IPCEvent]:
        """Get the N most recent events."""
        return sorted(self.events, key=lambda e: e.timestamp_ns, reverse=True)[:n]
    
    def clear(self) -> None:
        """Clear the buffer."""
        self.events.clear()
        self.next_index = 0
        self.is_full = False
    
    def size(self) -> int:
        """Current number of events in buffer."""
        return len(self.events)
