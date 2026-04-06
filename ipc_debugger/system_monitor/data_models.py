"""
data_models.py — Dataclasses for real OS monitoring data.

All data flowing out of system_monitor/ is strongly typed through
these dataclasses so the GUI layer has a stable contract.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProcessSnapshot:
    """A point-in-time snapshot of a real OS process."""
    pid: int
    name: str
    cpu_percent: float
    memory_rss: int        # bytes — resident set size
    memory_vms: int        # bytes — virtual memory size
    num_threads: int
    ppid: int              # parent PID
    status: str            # 'running', 'sleeping', 'zombie', etc.
    username: str
    is_new: bool = False          # appeared since last poll
    is_terminated: bool = False   # disappeared since last poll
    is_high_cpu: bool = False     # cpu_percent > HIGH_CPU_THRESHOLD

    @property
    def memory_rss_mb(self) -> float:
        return self.memory_rss / (1024 * 1024)

    @property
    def memory_vms_mb(self) -> float:
        return self.memory_vms / (1024 * 1024)


@dataclass
class IPCConnection:
    """A detected IPC link between two real OS processes."""
    connection_type: str   # 'shared_file', 'tcp_socket', 'udp_socket', 'named_pipe'
    pid_a: int
    pid_b: int             # 0 = external / unknown endpoint
    resource: str          # file path, "127.0.0.1:8080", or pipe name
    direction: str = "bidirectional"  # 'bidirectional', 'a_to_b', 'unknown'
    process_name_a: str = ""
    process_name_b: str = ""


@dataclass
class SystemStatsSnapshot:
    """Point-in-time global system performance metrics."""
    timestamp: float
    cpu_percent: float               # overall
    cpu_percpu: List[float]          # per-core list
    memory_total: int                # bytes
    memory_used: int
    memory_percent: float
    swap_total: int
    swap_used: int
    swap_percent: float
    disk_read_bytes_s: float         # bytes/second delta
    disk_write_bytes_s: float
    net_sent_bytes_s: float
    net_recv_bytes_s: float
    process_count: int
    boot_time: float                 # epoch seconds
