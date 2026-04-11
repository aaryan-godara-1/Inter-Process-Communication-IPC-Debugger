"""
ipc_logger_writer.py — Persistent log writer for IPC events.

Subscribes to IPCLogger and writes every event to disk.
Provides persistence that the in-memory logger lacks —
if the program crashes, all events are saved.

Interface:
    IPCLoggerWriter(logger, log_file)  → None
    IPCLoggerWriter.start()            → None
    IPCLoggerWriter.stop()             → None
    IPCLoggerWriter.replay()           → list[dict]
"""

import os
import time
import threading
from typing import List, Dict, Optional


class IPCLoggerWriter:
    """
    Subscribes to IPCLogger and writes every event to a log file.

    Adds persistence to the in-memory logger — events survive
    program crashes and can be replayed later for analysis.
    """

    def __init__(self, logger, 
                 log_file: str = "ipc_events.log"):
        self._logger = logger
        self._log_file = log_file
        self._lock = threading.Lock()
        self._running = False
        self._events_written = 0

        # Create log file if it doesn't exist
        if not os.path.exists(self._log_file):
            with open(self._log_file, "w") as f:
                f.write(f"# IPC Event Log\n")
                f.write(f"# Started: "
                       f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")

    def start(self) -> None:
        """Start listening to logger and writing events."""
        self._running = True
        self._logger.subscribe(self._on_event)

    def stop(self) -> None:
        """Stop writing events."""
        self._running = False
        self._logger.unsubscribe(self._on_event)
        self._write_footer()

    def _on_event(self, event) -> None:
        """Called on every new IPC event — writes to disk."""
        if not self._running:
            return
        try:
            with self._lock:
                with open(self._log_file, "a") as f:
                    f.write(f"[{event.ts_str}] "
                           f"{event.event_type.upper():8s} "
                           f"ch={event.channel_id} "
                           f"pid={event.pid} "
                           f"| {event.data}\n")
                self._events_written += 1
        except Exception:
            pass

    def replay(self) -> List[Dict]:
        """
        Read log file and return all events as list of dicts.
        Useful for post-mortem analysis.
        """
        events = []
        try:
            with open(self._log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#") \
                            or line.startswith("="):
                        continue
                    events.append({"raw": line})
        except FileNotFoundError:
            pass
        return events

    def get_events_written(self) -> int:
        """Return total number of events written to disk."""
        return self._events_written

    def get_log_path(self) -> str:
        """Return absolute path to log file."""
        return os.path.abspath(self._log_file)

    def clear_log(self) -> None:
        """Wipe the log file and start fresh."""
        with self._lock:
            with open(self._log_file, "w") as f:
                f.write(f"# IPC Event Log\n")
                f.write(f"# Cleared: "
                       f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
            self._events_written = 0

    def _write_footer(self) -> None:
        """Write session summary at end of log."""
        try:
            with open(self._log_file, "a") as f:
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"# Session ended: "
                       f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total events: {self._events_written}\n")
                f.write("=" * 60 + "\n")
        except Exception:
            pass