"""
Windows ETW collector for kernel-level IPC events.

Uses native Windows tooling (`logman` + `tracerpt`) to collect ETW events
from kernel providers and stream them into the debugger event pipeline.
"""

from __future__ import annotations

import csv
import hashlib
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from ipc_debugger.core.collector import CaptureConfig, KernelEventCollector
from ipc_debugger.core.events import EventResult, EventSource, EventType, IPCEvent, IPCType


class WindowsETWCollector(KernelEventCollector):
    """
    Windows ETW-backed collector.

    Starts an ETW session with selected providers and periodically parses
    ETL output into normalized IPCEvent entries.
    """

    _KERNEL_PROVIDERS = [
        ("Microsoft-Windows-Kernel-Network", "0xFFFFFFFFFFFFFFFF", "5"),
        ("Microsoft-Windows-Kernel-Process", "0xFFFFFFFFFFFFFFFF", "5"),
        ("Microsoft-Windows-Kernel-File", "0xFFFFFFFFFFFFFFFF", "5"),
    ]

    def __init__(self, config: Optional[CaptureConfig] = None):
        if not sys.platform.startswith("win"):
            raise OSError("WindowsETWCollector is only supported on Windows")
        super().__init__(config)

        self._session_name = f"IPCDebuggerETW_{int(time.time())}"
        self._temp_dir = Path(tempfile.mkdtemp(prefix="ipcdbg_etw_"))
        self._etl_path = self._temp_dir / "capture.etl"
        self._csv_path = self._temp_dir / "capture.csv"

        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        self._seen_hashes: Dict[str, int] = {}
        self._seen_cap = 50000

    def _run_cmd(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            check=check,
            capture_output=True,
            text=True,
            shell=False,
        )

    def _ensure_tooling(self) -> None:
        try:
            self._run_cmd(["where", "logman"])
            self._run_cmd(["where", "tracerpt"])
        except Exception as exc:
            raise RuntimeError(
                "Required ETW tools not found (logman/tracerpt)."
            ) from exc

    def _stop_session_if_exists(self) -> None:
        self._run_cmd(["logman", "stop", self._session_name, "-ets"], check=False)

    def _initialize_capture(self) -> None:
        self._ensure_tooling()
        self._stop_session_if_exists()

        start_cmd = [
            "logman",
            "start",
            self._session_name,
            "-ets",
            "-o",
            str(self._etl_path),
            "-f",
            "bincirc",
            "-max",
            "128",
        ]

        for provider, any_kw, level in self._KERNEL_PROVIDERS:
            start_cmd.extend(["-p", provider, any_kw, level])

        try:
            self._run_cmd(start_cmd)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RuntimeError(
                "Failed to start ETW session. Run as Administrator. "
                f"Details: {stderr}"
            ) from exc

        self._stop_event.clear()
        self._pause_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _finalize_capture(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3.0)
            self._poll_thread = None

        self._stop_session_if_exists()

    def _pause_capture(self) -> None:
        self._pause_event.set()

    def _resume_capture(self) -> None:
        self._pause_event.clear()

    def _apply_config_changes(self) -> None:
        return None

    def get_os_name(self) -> str:
        return "windows"

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(0.2)
                continue

            try:
                self._dump_etl_to_csv()
                self._parse_csv_and_emit()
            except Exception:
                # Keep capture alive; ETW files can be transiently unavailable.
                pass

            time.sleep(0.6)

    def _dump_etl_to_csv(self) -> None:
        if not self._etl_path.exists():
            return

        self._run_cmd(
            [
                "tracerpt",
                str(self._etl_path),
                "-of",
                "CSV",
                "-o",
                str(self._csv_path),
                "-y",
            ],
            check=False,
        )

    @staticmethod
    def _get_ci(row: dict[str, str], key: str) -> str:
        key_l = key.lower()
        for k, v in row.items():
            if k.lower() == key_l:
                return (v or "").strip()
        return ""

    def _row_sig(self, row: dict[str, str]) -> str:
        event_name = self._get_ci(row, "Event Name")
        ts = self._get_ci(row, "Clock-Time")
        pid = self._get_ci(row, "PID")
        tid = self._get_ci(row, "TID")
        task = self._get_ci(row, "Task")
        opcode = self._get_ci(row, "Opcode")
        src = self._get_ci(row, "saddr") + self._get_ci(row, "daddr")
        data = f"{event_name}|{ts}|{pid}|{tid}|{task}|{opcode}|{src}"
        return hashlib.sha1(data.encode("utf-8")).hexdigest()

    def _parse_csv_and_emit(self) -> None:
        if not self._csv_path.exists() or self._csv_path.stat().st_size == 0:
            return

        with self._csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sig = self._row_sig(row)
                if sig in self._seen_hashes:
                    continue

                evt = self._map_row_to_event(row)
                if evt is None:
                    continue

                if not self._passes_filters(evt):
                    continue

                self._seen_hashes[sig] = 1
                if len(self._seen_hashes) > self._seen_cap:
                    # Bounded dedup map.
                    for k in list(self._seen_hashes.keys())[: self._seen_cap // 4]:
                        self._seen_hashes.pop(k, None)

                self._emit_event(evt)

    def _map_row_to_event(self, row: dict[str, str]) -> Optional[IPCEvent]:
        event_name = self._get_ci(row, "Event Name")
        task = self._get_ci(row, "Task").lower()
        opcode = self._get_ci(row, "Opcode").lower()
        provider = self._get_ci(row, "Provider Name")

        pid = int(self._get_ci(row, "PID") or 0)
        tid = int(self._get_ci(row, "TID") or 0)
        clock = self._get_ci(row, "Clock-Time")
        ts_ns = int(time.time_ns())
        if clock:
            # Keep simple and stable: ETW wall-clock parsing is provider/locale-dependent.
            ts_ns = int(time.time_ns())

        ipc_type = None
        event_type = None
        resource_id = ""

        name_l = event_name.lower()
        if "send" in name_l or opcode == "send":
            event_type = EventType.SEND
        elif "recv" in name_l or "receive" in name_l or opcode == "receive":
            event_type = EventType.RECV
        elif "connect" in name_l:
            event_type = EventType.OPEN
        elif "disconnect" in name_l or "close" in name_l:
            event_type = EventType.CLOSE

        if "network" in provider.lower() or "tcp" in name_l:
            ipc_type = IPCType.TCP_SOCKET
            saddr = self._get_ci(row, "saddr")
            daddr = self._get_ci(row, "daddr")
            sport = self._get_ci(row, "sport")
            dport = self._get_ci(row, "dport")
            resource_id = f"{saddr}:{sport}->{daddr}:{dport}".strip("-<>")
        elif "udp" in name_l:
            ipc_type = IPCType.UDP_SOCKET
        elif "file" in provider.lower() or task == "fileio":
            # File I/O can represent named pipe activity on Windows paths.
            path = self._get_ci(row, "FileName") or self._get_ci(row, "Path")
            if "\\\\.\\pipe\\" in path.lower():
                ipc_type = IPCType.NAMED_PIPE
                resource_id = path
            else:
                return None
        elif "process" in provider.lower() and ("pipe" in name_l or "ipc" in name_l):
            ipc_type = IPCType.PIPE

        if ipc_type is None or event_type is None:
            return None

        size_raw = self._get_ci(row, "size") or self._get_ci(row, "datalength")
        payload_size = int(size_raw or 0)
        corr = self._get_ci(row, "Activity ID")
        if not corr:
            corr = f"{pid}:{tid}:{resource_id}:{ts_ns // 1_000_000}"

        return IPCEvent(
            timestamp_ns=ts_ns,
            correlation_id=corr,
            process_id=pid,
            thread_id=tid,
            process_name=self._get_ci(row, "Process Name"),
            thread_name="",
            ipc_type=ipc_type,
            resource_id=resource_id or f"{ipc_type.value}:{pid}",
            event_type=event_type,
            payload_size=payload_size,
            latency_ns=0,
            result=EventResult.SUCCESS,
            source=EventSource.KERNEL,
            confidence=100.0,
            custom_fields={
                "provider": provider,
                "task": task,
                "opcode": opcode,
            },
        )

    def _passes_filters(self, event: IPCEvent) -> bool:
        if self.config.ipc_types and event.ipc_type not in self.config.ipc_types:
            return False

        if self.config.process_pids and event.process_id not in self.config.process_pids:
            return False

        if self.config.min_latency_ns and event.latency_ns < self.config.min_latency_ns:
            return False

        if self.config.sample_rate < 1.0 and random.random() > self.config.sample_rate:
            self.metrics.events_sampled += 1
            return False

        return True
