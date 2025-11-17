"""
Entry point for running WatchDock GUI.
"""

import sys
import tkinter as tk

# Check if tkinter is available
try:
    from watchdock.gui import run_gui
except ImportError as e:
    print(f"Error importing GUI: {e}")
    print("Make sure tkinter is installed.")
    sys.exit(1)


def main():
    """Main entry point for GUI."""
    try:
        run_gui()
    except Exception as e:
        print(f"Error running GUI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

