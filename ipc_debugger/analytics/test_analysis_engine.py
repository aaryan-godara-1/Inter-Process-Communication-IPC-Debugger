"""
test_analysis_engine.py — Tests for analysis engine components.

Tests for:
- DeadlockAnalyzer
- AlertManager
- AnomalyDetector
- StatsReporter
- EventCorrelator
"""

import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analytics.deadlock_analyzer import DeadlockAnalyzer
from analytics.alerts import AlertManager
from analytics.anomaly_detector import AnomalyDetector
from analytics.event_correlator import EventCorrelator


# ── DeadlockAnalyzer Tests ────────────────────────────────────────────

def test_no_deadlock():
    """Empty graph should have no deadlock."""
    analyzer = DeadlockAnalyzer()
    result = analyzer.analyze()
    assert result["has_deadlock"] == False
    assert result["severity"] == "OK"
    assert result["cycle_count"] == 0
    print("✅ test_no_deadlock passed")


def test_deadlock_detected():
    """Manually inject a cycle into graph and detect it."""
    analyzer = DeadlockAnalyzer()
    analyzer._graph = {
        101: {102},
        102: {101}
    }
    result = analyzer.analyze()
    assert result["has_deadlock"] == True
    assert result["severity"] == "CRITICAL"
    assert result["cycle_count"] > 0
    print("✅ test_deadlock_detected passed")


def test_history_recorded():
    """History should grow with each analyze call."""
    analyzer = DeadlockAnalyzer()
    analyzer.analyze()
    analyzer.analyze()
    assert len(analyzer.get_history()) == 2
    print("✅ test_history_recorded passed")


# ── AlertManager Tests ────────────────────────────────────────────────

def test_alert_added():
    """Alert should be added successfully."""
    manager = AlertManager(cooldown_seconds=0)
    alert = manager.add_alert("CRITICAL", "DEADLOCK", "Test deadlock")
    assert alert is not None
    assert len(manager.get_alerts()) == 1
    print("✅ test_alert_added passed")


def test_alert_cooldown():
    """Same alert type should be suppressed during cooldown."""
    manager = AlertManager(cooldown_seconds=10)
    manager.add_alert("WARNING", "BOTTLENECK", "First alert")
    second = manager.add_alert("WARNING", "BOTTLENECK", "Second alert")
    assert second is None
    print("✅ test_alert_cooldown passed")


def test_alert_severity_filter():
    """Should filter alerts by severity correctly."""
    manager = AlertManager(cooldown_seconds=0)
    manager.add_alert("CRITICAL", "DEADLOCK", "deadlock")
    manager.add_alert("WARNING", "BOTTLENECK", "bottleneck")
    manager.add_alert("INFO", "LATENCY", "latency")
    assert len(manager.get_critical()) == 1
    assert len(manager.get_warnings()) == 1
    print("✅ test_alert_severity_filter passed")


# ── AnomalyDetector Tests ─────────────────────────────────────────────

def test_no_anomaly_insufficient_data():
    """Should not flag anomaly with less than 5 data points."""
    detector = AnomalyDetector()
    detector.record("ch1", 10.0)
    detector.record("ch1", 10.0)
    result = detector.check("ch1", 100.0)
    assert result == False
    print("✅ test_no_anomaly_insufficient_data passed")


def test_anomaly_detected():
    """Should detect anomaly when value exceeds threshold x baseline."""
    detector = AnomalyDetector(threshold=2.0)
    for _ in range(6):
        detector.record("ch1", 10.0)
    result = detector.check("ch1", 100.0)
    assert result == True
    print("✅ test_anomaly_detected passed")


# ── EventCorrelator Tests ─────────────────────────────────────────────

def test_event_chain():
    """Events on same channel should be grouped into chain."""

    class FakeEvent:
        def __init__(self):
            self.channel_id = "pipe_1"
            self.pid = 101
            self.event_type = "send"
            self.data = "hello"
            self.ts = time.time()

    correlator = EventCorrelator()
    correlator.add_event(FakeEvent())
    correlator.add_event(FakeEvent())
    chains = correlator.get_chains()
    assert len(chains) == 1
    assert chains[0]["event_count"] == 2
    print("✅ test_event_chain passed")


# ── Run All Tests ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n===== Running Analysis Engine Tests =====\n")
    test_no_deadlock()
    test_deadlock_detected()
    test_history_recorded()
    test_alert_added()
    test_alert_cooldown()
    test_alert_severity_filter()
    test_no_anomaly_insufficient_data()
    test_anomaly_detected()
    test_event_chain()
    print("\n===== All Tests Passed! ✅ :) =====\n")