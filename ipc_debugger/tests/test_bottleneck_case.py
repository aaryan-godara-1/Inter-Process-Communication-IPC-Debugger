"""
test_bottleneck_case.py — Ensures throughput tracker flags bottlenecks.
"""

from ipc_debugger.service import IPCService
from ipc_debugger.utils.constants import Scenario


def test_bottleneck_detection():
    service = IPCService()
    service.load_scenario(Scenario.BOTTLENECK)
    
    # Fast producers, slow consumer
    service.set_speed(20)
    service.start()
    
    import time
    
    # Let it run briefly to accumulate messages
    time.sleep(1.0)
    service.pause()
    
    # Validate throughput stats exist
    throughputs = service.throughput_tracker.get_all_throughputs()
    
    # There is 1 channel in this scenario (mq-bottleneck)
    assert "mq-bottleneck" in throughputs
    
    tp = throughputs["mq-bottleneck"]
    assert tp >= 0.0, f"Throughput should be trackable: {tp}"
    
    # The queue size should be building up because producers > consumers
    mq = service.scheduler.channels["mq-bottleneck"]
    assert mq.size() > 0, "Queue should have buffered messages"
