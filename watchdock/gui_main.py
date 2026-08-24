"""
Entry point for running WatchDock GUI.
"""

import argparse
import sys

# Check if tkinter is available
try:
    from watchdock.gui import run_gui
except ImportError as e:
    run_gui = None
    GUI_IMPORT_ERROR = e
else:
    GUI_IMPORT_ERROR = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the WatchDock desktop GUI")
    parser.add_argument(
        "--config",
        help=(
            "configuration file to use; GUI state, review database, examples, "
            "and logs are stored beside it"
        ),
    )
    return parser


def main(argv=None):
    """Main entry point for GUI."""
    args = build_parser().parse_args(argv)
    if run_gui is None:
        print(f"Error importing GUI: {GUI_IMPORT_ERROR}")
        print("Make sure tkinter is installed.")
        return 1
    try:
        run_gui(config_path=args.config)
    except Exception as e:
        print(f"Error running GUI: {e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

