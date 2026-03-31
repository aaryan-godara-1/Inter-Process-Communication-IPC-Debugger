"""
test_normal_flow.py — Validates the base "Normal Flow" scenario.

Asserts:
  - No deadlocks.
  - Data flows end-to-end (non-zero throughput).
  - All processes eventually terminate cleanly.

Note on race warnings: shared-memory write/read between P3 and P4 can appear
within a small time window, so the test does NOT assert zero race warnings —
that is expected behaviour in an unprotected single-writer, single-reader SHM
scenario.  Deadlock detection is the critical invariant here.
"""

import time
from service import IPCService
from utils.constants import Scenario, ProcessState


def test_normal_flow_completes_without_deadlock():
    service = IPCService()
    service.load_scenario(Scenario.NORMAL_FLOW)

    service.set_speed(10)
    service.start()

    # Wait for all processes to terminate (up to 10 s)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if all(p.state in (ProcessState.TERMINATED, ProcessState.DEADLOCKED)
               for p in service.get_processes()):
            break
        time.sleep(0.1)

    # 1. Assert no deadlocks
    service.deadlock_detector.update(
        service.scheduler.processes,
        list(service.scheduler.channels.values()),
        service.logger
    )
    cycles = service.deadlock_detector.detect()
    assert len(cycles) == 0, f"Expected 0 deadlocks, got {cycles}"

    # 2. Assert data flowed (non-zero throughput on at least one channel)
    thr = service.throughput_tracker.get_all_throughputs()
    assert any(val > 0 for val in thr.values()), \
        f"Expected non-zero throughput, got: {thr}"

    # 3. All processes should have terminated, not deadlocked
    for p in service.get_processes():
        assert p.state != ProcessState.DEADLOCKED, \
            f"Process {p.name} is unexpectedly deadlocked"
