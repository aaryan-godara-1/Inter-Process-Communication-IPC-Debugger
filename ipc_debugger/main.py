"""
main.py — Entry point for the Real-Time IPC Monitor & Process Analyzer.

Initialises the PyQt5 application, instantiates the service layer,
and launches the main window.
"""

import sys

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    print("Error: PyQt5 is not installed.")
    print("Please install via: pip install PyQt5 psutil")
    sys.exit(1)

try:
    import psutil  # noqa: F401 — verify at startup
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False
    print("Warning: psutil not installed — Live Monitor will be disabled.")
    print("Install via: pip install psutil")

from service import IPCService
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("IPC Monitor")
    app.setStyle("Fusion")   # base style; our QSS overrides the rest

    print("Initialising IPC Service…")
    service = IPCService()

    print("Launching GUI…")
    window = MainWindow(service)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
