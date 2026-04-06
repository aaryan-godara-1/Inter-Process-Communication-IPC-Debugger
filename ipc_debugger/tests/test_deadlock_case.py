"""
test_deadlock_case.py — Asserts the DeadlockDetector flags the circular wait.

Scenario: P1 blocks on pipe-A, P2 blocks on pipe-B.
          Conceptually P2 holds pipe-A, P1 holds pipe-B.
          Graph:   P1 → P2 → P1  (cycle)
"""

import time

from ipc_debugger.service import IPCService
from ipc_debugger.utils.constants import Scenario, ProcessState


def test_deadlock_detection():
    service = IPCService()
    service.load_scenario(Scenario.DEADLOCK)

    service.set_speed(50)
    service.start()

    # Allow processes to enter their blocking receive calls
    time.sleep(0.5)

    # Build the wait-for graph manually based on logger + waiting_on state
    # The scheduler pre-seeds phantom ownership log entries for the detector.
    service.deadlock_detector.update(
        service.scheduler.processes,
        list(service.scheduler.channels.values()),
        service.logger
    )

    cycles = service.deadlock_detector.detect()

    # At least some processes must be waiting
    waiting = [p for p in service.scheduler.processes
               if p.state == ProcessState.WAITING]
    assert len(waiting) >= 2, f"Expected blocking processes, got: {service.scheduler.processes}"

    assert len(cycles) > 0, (
        f"DeadlockDetector failed to find cycle. "
        f"Graph: {service.deadlock_detector.get_graph()}"
    )
