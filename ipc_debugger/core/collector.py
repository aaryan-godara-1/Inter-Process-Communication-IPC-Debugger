"""
Kernel event capture abstraction layer.

Defines the interface for OS-specific kernel event collectors.
This codebase is configured for Windows-only ETW collection.
"""

from __future__ import annotations

import abc
import json
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Optional, Dict, List, Any

from ipc_debugger.core.events import IPCEvent, IPCType, EventType, EventResult, EventSource


class CaptureStatus(str, Enum):
    """Collector status."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    CAPTURING = "capturing"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class CaptureMode(str, Enum):
    """Capture mode options."""
    OFF = "off"
    SAMPLING = "sampling"
    TRACING = "tracing"
    PROFILING = "profiling"


@dataclass
class CaptureConfig:
    """Configuration for event capture."""
    
    # What to capture
    ipc_types: List[IPCType] = field(default_factory=lambda: list(IPCType))
    process_pids: List[int] = field(default_factory=list)  # Empty = all
    process_names: List[str] = field(default_factory=list)  # Empty = all
    
    # How to capture
    sample_rate: float = 1.0  # 0.0-1.0, fraction of events to capture
    mode: CaptureMode = CaptureMode.TRACING
    buffer_size_events: int = 100000
    
    # Filtering
    min_latency_ns: int = 0  # Only events longer than this
    include_malloc: bool = False  # Include memory allocation events
    
    # Payload handling
    capture_payloads: bool = False
    payload_max_size: int = 256
    mask_sensitive: bool = True
    
    # Performance
    kernel_buffer_pages: int = 1024
    event_loss_policy: str = "drop_oldest"  # drop_oldest, drop_newest, block
    
    def __post_init__(self):
        if not self.ipc_types:
            self.ipc_types = list(IPCType)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['ipc_types'] = [t.value for t in self.ipc_types]
        d['mode'] = self.mode.value
        return d
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> CaptureConfig:
        data = data.copy()
        if 'ipc_types' in data and data['ipc_types']:
            data['ipc_types'] = [IPCType(t) for t in data['ipc_types']]
        if 'mode' in data:
            data['mode'] = CaptureMode(data['mode'])
        return CaptureConfig(**data)


@dataclass
class CaptureMetrics:
    """Metrics about the capture session."""
    
    start_time_ns: int = 0
    events_captured: int = 0
    events_dropped: int = 0
    bytes_captured: int = 0
    
    # Sampling stats
    events_sampled: int = 0
    sample_rate_actual: float = 1.0
    
    # Performance
    cpu_usage_percent: float = 0.0
    memory_usage_bytes: int = 0
    kernel_buffer_loss_percent: float = 0.0
    
    last_update_ns: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KernelEventCollector(abc.ABC):
    """
    Abstract base class for kernel-level IPC event collectors.
    
    Implementations in this repository target:
    - Windows: ETW (Event Tracing for Windows)
    """
    
    def __init__(self, config: Optional[CaptureConfig] = None):
        self.config = config or CaptureConfig()
        self.status = CaptureStatus.IDLE
        self.metrics = CaptureMetrics()
        
        self.event_callbacks: List[Callable[[IPCEvent], None]] = []
        self.status_callbacks: List[Callable[[CaptureStatus], None]] = []
        
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Begin capturing kernel events."""
        with self._lock:
            if self.status != CaptureStatus.IDLE:
                raise RuntimeError(f"Cannot start collector in {self.status} state")
            
            self.status = CaptureStatus.INITIALIZING
            self._notify_status()
            
            try:
                self._initialize_capture()
                self.status = CaptureStatus.CAPTURING
                self._notify_status()
            except Exception as e:
                self.status = CaptureStatus.ERROR
                self._notify_status()
                raise
    
    def stop(self) -> None:
        """Stop capturing kernel events."""
        with self._lock:
            if self.status not in (CaptureStatus.CAPTURING, CaptureStatus.PAUSED):
                raise RuntimeError(f"Cannot stop collector in {self.status} state")
            
            self.status = CaptureStatus.STOPPING
            self._notify_status()
            
            try:
                self._finalize_capture()
                self.status = CaptureStatus.STOPPED
                self._notify_status()
            except Exception as e:
                self.status = CaptureStatus.ERROR
                self._notify_status()
                raise
    
    def pause(self) -> None:
        """Temporarily pause capture without stopping."""
        with self._lock:
            if self.status != CaptureStatus.CAPTURING:
                raise RuntimeError(f"Cannot pause in {self.status} state")
            
            self.status = CaptureStatus.PAUSED
            self._pause_capture()
            self._notify_status()
    
    def resume(self) -> None:
        """Resume capture after pause."""
        with self._lock:
            if self.status != CaptureStatus.PAUSED:
                raise RuntimeError(f"Cannot resume from {self.status} state")
            
            self.status = CaptureStatus.CAPTURING
            self._resume_capture()
            self._notify_status()
    
    def set_config(self, config: CaptureConfig) -> None:
        """Update capture configuration."""
        with self._lock:
            self.config = config
            self._apply_config_changes()
    
    def register_event_callback(self, callback: Callable[[IPCEvent], None]) -> None:
        """Register a callback for newly captured events."""
        self.event_callbacks.append(callback)
    
    def register_status_callback(self, callback: Callable[[CaptureStatus], None]) -> None:
        """Register a callback for status changes."""
        self.status_callbacks.append(callback)
    
    def get_metrics(self) -> CaptureMetrics:
        """Get current capture metrics."""
        with self._lock:
            return self.metrics
    
    def _emit_event(self, event: IPCEvent) -> None:
        """Emit an event to all registered callbacks."""
        with self._lock:
            self.metrics.events_captured += 1
            self.metrics.bytes_captured += event.payload_size
        
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as e:
                # Log but don't crash on callback errors
                print(f"Error in event callback: {e}")
    
    def _notify_status(self) -> None:
        """Notify all status callbacks of status change."""
        for callback in self.status_callbacks:
            try:
                callback(self.status)
            except Exception as e:
                print(f"Error in status callback: {e}")
    
    # Abstract methods - must be implemented by subclasses
    
    @abc.abstractmethod
    def _initialize_capture(self) -> None:
        """Set up kernel-level capture infrastructure."""
        pass
    
    @abc.abstractmethod
    def _finalize_capture(self) -> None:
        """Clean up kernel-level capture infrastructure."""
        pass
    
    @abc.abstractmethod
    def _pause_capture(self) -> None:
        """Pause capture without full shutdown."""
        pass
    
    @abc.abstractmethod
    def _resume_capture(self) -> None:
        """Resume capture after pause."""
        pass
    
    @abc.abstractmethod
    def _apply_config_changes(self) -> None:
        """Apply new configuration to running collector."""
        pass
    
    @abc.abstractmethod
    def get_os_name(self) -> str:
        """Return the OS this collector targets (linux, windows, macos)."""
        pass
