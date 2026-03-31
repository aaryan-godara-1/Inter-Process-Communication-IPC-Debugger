# OS IPC Debugger Simulator

A modular, team-friendly Operating Systems project designed to simulate, monitor, and debug Inter-Process Communication (IPC) mechanisms. 

It provides implementations of Pipes (named and unnamed), Message Queues, and Shared Memory, alongside detectors for Deadlocks and Race Conditions, wrapped in a live PyQt5 graph visualisation.

## 📁 Architecture & Module Responsibilities

The system is split into decoupled folders. The GUI knows only about the `IPCService`, which in turn coordinates the core modules via the `EventManager` bus.

* `core/` (IPC & Processes): Thread-safe IPC channels with backing buffers, priority queues, and RW locks.
* `debugger/`: Subscribes to the event logger and parses wait-for graphs (for deadlocks) or access timestamps (for races).
* `simulation/`: The thread scheduler and pub-sub EventManager. Sets up the scenarios.
* `analytics/`: Tracks round-trip latencies and msg/s throughput for performance profiling.
* `gui/`: `QPainter`-based layout showing nodes (processes) and edges (wait/hold dependencies), updating in real time.
* `utils/`: Shared enums, colours, and helper thread-safe generators.

## 🚀 How to Run

1. Ensure you have Python 3.8+ installed.
2. Install the GUI and test requirements:
   ```bash
   pip install PyQt5 pytest
   ```
3. Run the main entry point:
   ```bash
   python main.py
   ```

## 🧪 Scenarios

The GUI allows you to select between 3 main scenarios built into the scheduler:

1. **Normal Flow**: A 4-process pipeline `P1 (Pipe) -> P2 (Queue) -> P3 (Shared Mem) -> P4`. Watch the latency settle and no errors report.
2. **Deadlock**: Two processes holding onto separate pipes whilst waiting to read the other's pipe. The graph will mark these nodes red, and the log will throw an alert.
3. **Bottleneck**: Three fast producers spamming one message queue, while a single consumer intentionally acts slow. The queue backs up.

## 🛠 Running Tests
To verify the engine autonomously detects the conditions:
```bash
python -m pytest tests/ -v
```
