"""
helpers.py — Shared utility functions.

Provides timestamp generation, PID management, and message formatting
used by multiple modules across the project.
"""

import time
import threading
from datetime import datetime


# Thread-safe PID counter
_pid_lock = threading.Lock()
_next_pid = 1


def generate_pid() -> int:
    """Return the next unique process identifier (thread-safe)."""
    global _next_pid
    with _pid_lock:
        pid = _next_pid
        _next_pid += 1
    return pid


def reset_pid_counter() -> None:
    """Reset the PID counter (useful when resetting the simulation)."""
    global _next_pid
    with _pid_lock:
        _next_pid = 1


def timestamp() -> float:
    """Return a high-resolution monotonic timestamp (seconds)."""
    return time.monotonic()


def timestamp_str() -> str:
    """Return a human-readable timestamp string."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def format_message(source_pid: int, dest_pid: int, data: str,
                   channel_type: str = "") -> str:
    """Format a log-friendly message string."""
    ts = timestamp_str()
    prefix = f"[{ts}] P{source_pid} → P{dest_pid}"
    if channel_type:
        prefix += f" ({channel_type})"
    return f"{prefix}: {data}"
