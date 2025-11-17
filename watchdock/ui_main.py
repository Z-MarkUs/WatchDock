"""
Entry point for running WatchDock UI.
"""

import argparse
import sys
from watchdock.ui import run_ui


def main():
    """Main entry point for UI."""
    parser = argparse.ArgumentParser(description="WatchDock UI - Web interface for configuration")
    parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to bind to (default: 5000)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    try:
        run_ui(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)


if __name__ == '__main__':
    main()

