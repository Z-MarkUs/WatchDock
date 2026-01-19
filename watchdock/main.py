"""
Main application entry point for WatchDock.
"""

import sys
import os
import signal
import logging
import argparse
import subprocess
import json
import urllib.request
from pathlib import Path
from packaging import version as packaging_version
from watchdock import __version__
from watchdock.config import WatchDockConfig
from watchdock.watcher import FileWatcher
from watchdock.ai_processor import AIProcessor
from watchdock.file_organizer import FileOrganizer
from watchdock.pending_actions import PendingActionsQueue


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('watchdock.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class WatchDock:
    """Main WatchDock application."""
    
    def __init__(self, config: WatchDockConfig):
        self.config = config
        self.ai_processor = AIProcessor(config.ai_config)
        self.file_organizer = FileOrganizer(config.archive_config)
        self.pending_queue = PendingActionsQueue() if config.mode == "hitl" else None
        self.watcher = None
        self.running = False
    
    def process_file(self, file_path: str):
        """Process a single file."""
        try:
            logger.info(f"Analyzing file: {file_path}")
            
            # Analyze file with AI
            analysis = self.ai_processor.analyze_file(file_path)
            logger.info(f"Analysis result: {analysis}")
            
            # Check mode
            if self.config.mode == "hitl":
                # HITL mode: add to pending queue
                proposed_action = self.file_organizer.get_proposed_action(file_path, analysis)
                action = self.pending_queue.add(file_path, analysis, proposed_action)
                logger.info(f"Added to pending queue (action_id: {action.action_id}). "
                          f"Use GUI or CLI to approve/reject.")
                
                # Try to show notification
                self._notify_pending_action(action)
            else:
                # Auto mode: organize immediately
                result = self.file_organizer.organize_file(file_path, analysis)
                logger.info(f"Organization result: {result}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}", exc_info=True)
    
    def _notify_pending_action(self, action):
        """Notify user about pending action (CLI mode)."""
        try:
            # Try desktop notifications
            try:
                import platform
                if platform.system() == "Darwin":  # macOS
                    os.system(f'''osascript -e 'display notification "{action.file_path}" with title "WatchDock: Pending Action"' ''')
                elif platform.system() == "Linux":
                    os.system(f'notify-send "WatchDock" "Pending action for: {Path(action.file_path).name}"')
                elif platform.system() == "Windows":
                    # Windows toast notification would require additional library
                    pass
            except:
                pass
            
            # Also print to console
            print(f"\n📋 Pending Action: {action.file_path}")
            print(f"   Category: {action.analysis.get('category', 'Unknown')}")
            print(f"   Suggested name: {action.proposed_action.get('new_name', 'N/A')}")
            print(f"   Action ID: {action.action_id}")
            print(f"   Use 'watchdock approve {action.action_id}' to approve")
            print(f"   Use 'watchdock reject {action.action_id}' to reject\n")
        except Exception as e:
            logger.debug(f"Could not send notification: {e}")
    
    def start(self):
        """Start the WatchDock service."""
        logger.info("Starting WatchDock...")
        
        # Create file watcher
        self.watcher = FileWatcher(
            self.config.watched_folders,
            self.process_file
        )
        
        # Start watching
        self.watcher.start()
        self.running = True
        
        logger.info("WatchDock is running. Press Ctrl+C to stop.")
        
        # Keep running
        try:
            while self.running and self.watcher.is_alive():
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the WatchDock service."""
        logger.info("Stopping WatchDock...")
        self.running = False
        if self.watcher:
            self.watcher.stop()
        logger.info("WatchDock stopped")


def cmd_version(args):
    """Show version information."""
    print(f"WatchDock version {__version__}")
    return 0


def cmd_update(args):
    """Check for and install updates."""
    print("Checking for updates...")
    
    try:
        # Check PyPI for latest version
        url = "https://pypi.org/pypi/watchdock/json"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read())
            latest_version = data['info']['version']
        
        current_version = __version__
        
        if packaging_version.parse(latest_version) > packaging_version.parse(current_version):
            print(f"Update available: {current_version} → {latest_version}")
            if args.install:
                print("Installing update...")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "watchdock"],
                    check=False
                )
                if result.returncode == 0:
                    print("✅ Update installed successfully!")
                    print("Please restart WatchDock to use the new version.")
                    return 0
                else:
                    print("❌ Update failed. Try running: pip install -U watchdock")
                    return 1
            else:
                print("Run 'watchdock update --install' to install the update.")
                return 0
        else:
            print(f"✅ You are running the latest version ({current_version})")
            return 0
    except Exception as e:
        print(f"❌ Error checking for updates: {e}")
        print("You can manually update with: pip install -U watchdock")
        return 1


def cmd_status(args):
    """Show WatchDock status."""
    config_path = Path(args.config)
    
    if not config_path.exists():
        print("❌ Configuration file not found")
        print(f"   Expected at: {config_path}")
        print("   Run 'watchdock config init' to create one.")
        return 1
    
    try:
        config = WatchDockConfig.load(str(config_path))
        print("✅ Configuration loaded")
        print(f"   Mode: {config.mode.upper()}")
        print(f"   Watched folders: {len(config.watched_folders)}")
        for folder in config.watched_folders:
            exists = "✅" if Path(folder).exists() else "❌"
            print(f"     {exists} {folder}")
        print(f"   AI Provider: {config.ai_config.provider}")
        print(f"   Archive: {config.archive_config.archive_path}")
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return 1
    
    return 0


def cmd_config_init(args):
    """Initialize default configuration."""
    config = WatchDockConfig.default()
    config_path = Path(args.config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config.save(str(config_path))
    print(f"✅ Default configuration created at: {config_path}")
    print("Please edit the configuration file and add your API keys if needed.")
    return 0


def cmd_config_validate(args):
    """Validate configuration file."""
    config_path = Path(args.config)
    
    if not config_path.exists():
        print(f"❌ Configuration file not found: {config_path}")
        return 1
    
    try:
        config = WatchDockConfig.load(str(config_path))
        print("✅ Configuration is valid")
        return 0
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return 1


def cmd_gui(args):
    """Launch GUI configuration tool."""
    try:
        from watchdock.gui import run_gui
        run_gui()
        return 0
    except ImportError:
        print("Error: GUI requires tkinter. Install it or use command-line mode.")
        return 1


def cmd_approve(args):
    """Approve a pending action."""
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Configuration file not found: {config_path}")
        return 1
    
    config = WatchDockConfig.load(str(config_path))
    queue = PendingActionsQueue()
    action = queue.approve(args.action_id)
    
    if action:
        from watchdock.file_organizer import FileOrganizer
        organizer = FileOrganizer(config.archive_config)
        result = organizer.organize_file(action.file_path, action.analysis)
        print(f"✅ Approved and executed: {action.file_path}")
        print(f"   Result: {result}")
        queue.remove(action.action_id)
        return 0
    else:
        print(f"❌ Action not found: {args.action_id}")
        return 1


def cmd_reject(args):
    """Reject a pending action."""
    queue = PendingActionsQueue()
    action = queue.reject(args.action_id)
    
    if action:
        print(f"❌ Rejected: {action.file_path}")
        queue.remove(action.action_id)
        return 0
    else:
        print(f"❌ Action not found: {args.action_id}")
        return 1


def cmd_list_pending(args):
    """List all pending actions."""
    queue = PendingActionsQueue()
    pending = queue.get_pending()
    
    if pending:
        print(f"\n📋 Pending Actions ({len(pending)}):\n")
        for action in pending:
            print(f"  ID: {action.action_id}")
            print(f"  File: {action.file_path}")
            print(f"  Category: {action.analysis.get('category', 'Unknown')}")
            print(f"  Suggested: {action.proposed_action.get('new_name', 'N/A')}")
            print()
    else:
        print("No pending actions.")
    return 0


def cmd_start(args):
    """Start WatchDock monitoring."""
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Configuration file not found: {config_path}")
        print("Run 'watchdock config init' to create a default configuration file.")
        return 1
    
    config = WatchDockConfig.load(str(config_path))
    watchdock = WatchDock(config)
    
    # Handle signals for graceful shutdown
    def signal_handler(sig, frame):
        watchdock.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the service
    watchdock.start()
    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WatchDock - File monitoring and organization tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=str(Path.home() / '.watchdock' / 'config.json'),
        help='Path to configuration file'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Version command
    version_parser = subparsers.add_parser('version', help='Show version information')
    version_parser.set_defaults(func=cmd_version)
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Check for and install updates')
    update_parser.add_argument('--install', action='store_true', help='Install update if available')
    update_parser.set_defaults(func=cmd_update)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show WatchDock status')
    status_parser.set_defaults(func=cmd_status)
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Configuration management')
    config_subparsers = config_parser.add_subparsers(dest='config_command', help='Config commands')
    
    config_init_parser = config_subparsers.add_parser('init', help='Initialize default configuration')
    config_init_parser.set_defaults(func=cmd_config_init)
    
    config_validate_parser = config_subparsers.add_parser('validate', help='Validate configuration file')
    config_validate_parser.set_defaults(func=cmd_config_validate)
    
    # GUI command
    gui_parser = subparsers.add_parser('gui', help='Launch GUI configuration tool')
    gui_parser.set_defaults(func=cmd_gui)
    
    # HITL commands
    approve_parser = subparsers.add_parser('approve', help='Approve a pending action (HITL mode)')
    approve_parser.add_argument('action_id', help='Action ID to approve')
    approve_parser.set_defaults(func=cmd_approve)
    
    reject_parser = subparsers.add_parser('reject', help='Reject a pending action (HITL mode)')
    reject_parser.add_argument('action_id', help='Action ID to reject')
    reject_parser.set_defaults(func=cmd_reject)
    
    list_pending_parser = subparsers.add_parser('list-pending', help='List all pending actions (HITL mode)')
    list_pending_parser.set_defaults(func=cmd_list_pending)
    
    # Start command (default)
    start_parser = subparsers.add_parser('start', help='Start WatchDock monitoring (default)')
    start_parser.set_defaults(func=cmd_start)
    
    args = parser.parse_args()
    
    # If no command provided, default to start
    if not args.command:
        args.command = 'start'
        args.func = cmd_start
    
    # Call the appropriate command function
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())

