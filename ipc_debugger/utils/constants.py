"""
constants.py — Global enums, constants, and configuration values.

This module defines all shared constants used across the IPC Debugger system.
Each developer should import from here rather than hard-coding magic values.
"""

from enum import Enum, auto


# ─── IPC Channel Types ────────────────────────────────────────────────────────

class IPCType(Enum):
    """Types of IPC mechanisms supported by the simulator."""
    UNNAMED_PIPE = auto()
    NAMED_PIPE = auto()
    MESSAGE_QUEUE = auto()
    SHARED_MEMORY = auto()


# ─── Process States ──────────────────────────────────────────────────────────

class ProcessState(Enum):
    """Lifecycle states for a simulated process."""
    READY = auto()
    RUNNING = auto()
    WAITING = auto()       # blocked on IPC read/write
    TERMINATED = auto()
    DEADLOCKED = auto()


# ─── Event Types ─────────────────────────────────────────────────────────────

class EventType(Enum):
    """Events emitted through the central EventManager bus."""
    PROCESS_STARTED = auto()
    PROCESS_STOPPED = auto()
    DATA_SENT = auto()
    DATA_RECEIVED = auto()
    CHANNEL_CREATED = auto()
    CHANNEL_CLOSED = auto()
    DEADLOCK_DETECTED = auto()
    RACE_CONDITION_DETECTED = auto()
    WARNING = auto()
    SIMULATION_STARTED = auto()
    SIMULATION_PAUSED = auto()
    SIMULATION_RESET = auto()
    SIMULATION_STEP = auto()
    STATE_CHANGED = auto()

    # ── Live Monitor Events ──────────────────────────────────────────────
    PROCESS_SNAPSHOT = auto()        # periodic real process list update
    PROCESS_NEW = auto()             # a new real process appeared
    PROCESS_TERMINATED = auto()      # a real process disappeared
    IPC_CONNECTION_FOUND = auto()    # shared file or socket link detected
    SYSTEM_STATS_UPDATE = auto()     # global CPU / RAM / IO metrics

    # ── Mode Events ──────────────────────────────────────────────────────
    MODE_SWITCHED = auto()           # user switched Live ↔ Simulation


# ─── Colour Codes (for GUI) ─────────────────────────────────────────────────

class StatusColor:
    """Hex colours used by the GUI to indicate system health."""
    NORMAL = "#4CAF50"       # green
    DELAY = "#FFC107"        # amber / yellow
    DEADLOCK = "#F44336"     # red
    IDLE = "#9E9E9E"         # grey
    RACE = "#FF9800"         # orange
    BACKGROUND = "#1E1E2E"   # dark surface
    SURFACE = "#2D2D44"      # card / panel surface
    TEXT = "#E0E0E0"         # light text
    ACCENT = "#7C4DFF"       # accent purple


# ─── Simulation Defaults ────────────────────────────────────────────────────

DEFAULT_PROCESS_COUNT = 4
DEFAULT_DELAY_MS = 500          # ms between simulation steps
MIN_DELAY_MS = 50
MAX_DELAY_MS = 3000
DEFAULT_QUEUE_MAX_SIZE = 100
DEFAULT_PIPE_BUFFER_SIZE = 256  # bytes (conceptual)

# ─── Scenarios ───────────────────────────────────────────────────────────────

class Scenario(Enum):
    """Pre-built simulation scenarios."""
    NORMAL_FLOW = "Normal Flow"
    DEADLOCK = "Deadlock"
    BOTTLENECK = "Bottleneck"
