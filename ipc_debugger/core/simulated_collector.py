"""
Simulated kernel event collector for development and testing.

Generates realistic IPC event streams without requiring actual kernel instrumentation.
Useful for demos, development, and automated testing.
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from typing import Dict, List, Optional

from ipc_debugger.core.collector import (
    KernelEventCollector,
    CaptureConfig,
    CaptureStatus,
    CaptureMetrics,
)
from ipc_debugger.core.events import (
    IPCEvent,
    IPCType,
    EventType,
    EventResult,
    EventSource,
)


class SimulatedCollector(KernelEventCollector):
    """
    Generates synthetic but realistic IPC events for testing and demos.
    
    Simulates:
    - Process lifecycles
    - Pipe and socket communication
    - Lock contention and waiting
    - Message queues
    - Various latency patterns
    """
    
    def __init__(self, config: Optional[CaptureConfig] = None):
        super().__init__(config)
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        
        # Simulation state
        self._virtual_timestamp_ns = int(time.time_ns())
        self._process_pids = [1000, 1001, 1002, 1003, 1004]
        self._process_names = ["worker-1", "worker-2", "worker-3", "queue", "monitor"]
        self._resources: Dict[str, IPCType] = {}  # resource_id -> type
        self._resource_counter = 0
        
    def get_os_name(self) -> str:
        return "simulated"
    
    def _initialize_capture(self) -> None:
        """Start the simulation thread."""
        self._stop_event.clear()
        self._pause_event.clear()
        self._virtual_timestamp_ns = int(time.time_ns())
        
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=False
        )
        self._capture_thread.start()
    
    def _finalize_capture(self) -> None:
        """Stop the simulation thread."""
        if self._capture_thread:
            self._stop_event.set()
            self._capture_thread.join(timeout=5.0)
            self._capture_thread = None
    
    def _pause_capture(self) -> None:
        """Pause event generation."""
        self._pause_event.set()
    
    def _resume_capture(self) -> None:
        """Resume event generation."""
        self._pause_event.clear()
    
    def _apply_config_changes(self) -> None:
        """Update capture config (no special actions needed for simulator)."""
        pass
    
    def _capture_loop(self) -> None:
        """Main capture loop - generates synthetic events."""
        try:
            iteration = 0
            while not self._stop_event.is_set():
                # Handle pause
                while self._pause_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.1)
                
                iteration += 1
                
                # Generate events based on scenario
                if iteration % 5 == 0:
                    # Process creation events (occasional)
                    self._sim_process_communication()
                else:
                    # Normal communication
                    self._sim_normal_flow()
                
                # Respect sampling rate
                if random.random() > self.config.sample_rate:
                    self.metrics.events_sampled += 1
                
                # Sleep to simulate real-time capture
                time.sleep(0.01)  # 10ms between batches
                
        except Exception as e:
            self.status = CaptureStatus.ERROR
            self._notify_status()
            raise
    
    def _sim_normal_flow(self) -> None:
        """Simulate normal message passing between processes."""
        
        # Pick two random processes
        sender_id = random.randint(0, len(self._process_pids) - 1)
        receiver_id = random.randint(0, len(self._process_pids) - 1)
        
        if sender_id == receiver_id:
            return
        
        sender_pid = self._process_pids[sender_id]
        receiver_pid = self._process_pids[receiver_id]
        
        # Create or reuse a resource
        resource_key = f"pipe_{sender_id}_{receiver_id}"
        if resource_key not in self._resources:
            self._resources[resource_key] = IPCType.PIPE
        
        correlation_id = f"req_{int(time.time_ns()) % 1000000}"
        
        # Send event
        send_event = IPCEvent(
            timestamp_ns=self._virtual_timestamp_ns,
            correlation_id=correlation_id,
            process_id=sender_pid,
            thread_id=sender_pid * 10 + random.randint(0, 3),
            process_name=self._process_names[sender_id],
            ipc_type=IPCType.PIPE,
            resource_id=resource_key,
            event_type=EventType.SEND,
            payload_size=random.randint(10, 1000),
            result=EventResult.SUCCESS,
            source=EventSource.KERNEL,
            confidence=100.0,
        )
        self._emit_event(send_event)
        self._virtual_timestamp_ns += random.randint(100, 500)
        
        # Receive event (with realistic latency)
        recv_event = IPCEvent(
            timestamp_ns=self._virtual_timestamp_ns,
            correlation_id=correlation_id,
            process_id=receiver_pid,
            thread_id=receiver_pid * 10 + random.randint(0, 3),
            process_name=self._process_names[receiver_id],
            ipc_type=IPCType.PIPE,
            resource_id=resource_key,
            event_type=EventType.RECV,
            payload_size=send_event.payload_size,
            result=EventResult.SUCCESS,
            source=EventSource.KERNEL,
            confidence=100.0,
            parent_event_id=send_event.event_id,
        )
        self._emit_event(recv_event)
        self._virtual_timestamp_ns += random.randint(100, 500)
        
        # Occasionally generate a response
        if random.random() < 0.6:
            resp_correlation_id = f"resp_{int(time.time_ns()) % 1000000}"
            
            response_event = IPCEvent(
                timestamp_ns=self._virtual_timestamp_ns,
                correlation_id=resp_correlation_id,
                process_id=receiver_pid,
                thread_id=receiver_pid * 10 + random.randint(0, 3),
                process_name=self._process_names[receiver_id],
                ipc_type=IPCType.PIPE,
                resource_id=resource_key,
                event_type=EventType.RESPONSE,
                payload_size=random.randint(5, 500),
                result=EventResult.SUCCESS,
                source=EventSource.KERNEL,
                confidence=100.0,
                parent_event_id=recv_event.event_id,
            )
            self._emit_event(response_event)
            self._virtual_timestamp_ns += random.randint(100, 500)
    
    def _sim_process_communication(self) -> None:
        """Simulate lock contention and waiting scenarios."""
        
        # Pick a random lock
        lock_id = f"mutex_{random.randint(0, 5)}"
        
        # Lock acquisition
        acquirer_id = random.randint(0, len(self._process_pids) - 1)
        acquirer_pid = self._process_pids[acquirer_id]
        
        acquire_event = IPCEvent(
            timestamp_ns=self._virtual_timestamp_ns,
            correlation_id=f"lock_{lock_id}_{self._virtual_timestamp_ns}",
            process_id=acquirer_pid,
            thread_id=acquirer_pid * 10 + random.randint(0, 3),
            process_name=self._process_names[acquirer_id],
            ipc_type=IPCType.MUTEX,
            resource_id=lock_id,
            event_type=EventType.ACQUIRE,
            result=EventResult.SUCCESS,
            source=EventSource.KERNEL,
            confidence=100.0,
            latency_ns=random.randint(0, 1000),  # Some contention
        )
        self._emit_event(acquire_event)
        self._virtual_timestamp_ns += random.randint(500, 2000)  # Hold lock
        
        # Lock release
        release_event = IPCEvent(
            timestamp_ns=self._virtual_timestamp_ns,
            process_id=acquirer_pid,
            thread_id=acquirer_pid * 10 + random.randint(0, 3),
            process_name=self._process_names[acquirer_id],
            ipc_type=IPCType.MUTEX,
            resource_id=lock_id,
            event_type=EventType.RELEASE,
            result=EventResult.SUCCESS,
            source=EventSource.KERNEL,
            confidence=100.0,
            parent_event_id=acquire_event.event_id,
        )
        self._emit_event(release_event)
        self._virtual_timestamp_ns += random.randint(100, 300)
    
    def _create_resource(self, ipc_type: IPCType) -> str:
        """Create a simulated resource."""
        self._resource_counter += 1
        resource_id = f"{ipc_type.value}_{self._resource_counter}"
        self._resources[resource_id] = ipc_type
        return resource_id
