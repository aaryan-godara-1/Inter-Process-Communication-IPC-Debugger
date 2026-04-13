"""
Backend entry point for the IPC Debugger.

Runs the simulation headlessly, prints a structured report, and avoids
all GUI dependencies so the project can be used as a backend tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ipc_debugger.service import IPCService
from ipc_debugger.utils.constants import Scenario


SCENARIO_ALIASES = {
    "normal": Scenario.NORMAL_FLOW,
    "normal-flow": Scenario.NORMAL_FLOW,
    "deadlock": Scenario.DEADLOCK,
    "bottleneck": Scenario.BOTTLENECK,
}


def _parse_scenario(value: str) -> Scenario:
    try:
        return SCENARIO_ALIASES[value.lower()]
    except KeyError as exc:
        options = ", ".join(sorted(SCENARIO_ALIASES))
        raise argparse.ArgumentTypeError(
            f"Unknown scenario '{value}'. Choose one of: {options}."
        ) from exc


def _format_report(report) -> str:
    lines = [
        f"Scenario: {report.scenario}",
        f"Completed: {report.completed}",
        f"Timed out: {report.timed_out}",
        f"Events logged: {report.logged_events}",
        "",
        "Process states:",
    ]
    for pid, state in sorted(report.process_states.items()):
        lines.append(f"  P{pid}: {state}")
    lines.append("")
    lines.append("Channels:")
    for channel_id, channel_type in sorted(report.channels.items()):
        lines.append(f"  {channel_id}: {channel_type}")
    lines.append("")
    lines.append(f"Deadlock cycles: {report.deadlock_cycles or 'none'}")
    lines.append(f"Throughput (msg/s): {report.throughput_msg_s or 'none'}")
    lines.append(f"Average latency (ms): {report.latency_ms or 'none'}")
    lines.append(f"Bottlenecks: {report.bottlenecks or 'none'}")
    lines.append(f"Race warnings: {report.race_warnings or 'none'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if not sys.platform.startswith("win"):
        raise OSError("ipc_debugger.main is Windows-only")

    parser = argparse.ArgumentParser(description="Run the IPC Debugger backend.")
    parser.add_argument(
        "--scenario",
        type=_parse_scenario,
        default=Scenario.NORMAL_FLOW,
        help="Scenario to run: normal, normal-flow, deadlock, bottleneck.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=20,
        help="Artificial delay between process actions in milliseconds.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Maximum time to wait for the scenario to finish.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of text.",
    )
    args = parser.parse_args(argv)

    service = IPCService()
    report = service.run_scenario(
        args.scenario,
        delay_ms=args.delay_ms,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_report(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
