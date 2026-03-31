"""
main.py — Entry point for the IPC Debugger Tool.

Initialises the PyQt5 application, instantiates the service layer,
and launches the main window.
"""

import sys
import argparse

# Check for PyQt5 early so we can give a clear error message.
try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    print("Error: PyQt5 is not installed.")
    print("Please install via: pip install PyQt5")
    sys.exit(1)


from service import IPCService
from gui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="OS IPC Debugger Simulator")
    parser.parse_args()

    # Create the Qt Application
    app = QApplication(sys.argv)
    
    # Optional: Set a dark theme globally for the application
    app.setStyle("Fusion")
    
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtCore import Qt
    
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)
    

    # Initialise backend service
    print("Initialising IPC Service...")
    service = IPCService()

    # Initialise and show GUI
    print("Launching GUI...")
    window = MainWindow(service)
    window.show()

    # Run the event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
