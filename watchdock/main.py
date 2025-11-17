"""
Main application entry point for WatchDock.
"""

import sys
import os
import signal
import logging
import argparse
from pathlib import Path
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
            print(f"   Use 'watchdock --approve {action.action_id}' to approve")
            print(f"   Use 'watchdock --reject {action.action_id}' to reject\n")
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="WatchDock - File monitoring and organization tool")
    parser.add_argument(
        '--config',
        type=str,
        default=str(Path.home() / '.watchdock' / 'config.json'),
        help='Path to configuration file'
    )
    parser.add_argument(
        '--init-config',
        action='store_true',
        help='Initialize default configuration file'
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Launch GUI configuration tool'
    )
    parser.add_argument(
        '--approve',
        type=str,
        help='Approve a pending action by action_id (HITL mode)'
    )
    parser.add_argument(
        '--reject',
        type=str,
        help='Reject a pending action by action_id (HITL mode)'
    )
    parser.add_argument(
        '--list-pending',
        action='store_true',
        help='List all pending actions (HITL mode)'
    )
    
    args = parser.parse_args()
    
    # Launch GUI if requested
    if args.gui:
        try:
            from watchdock.gui import run_gui
            run_gui()
            return 0
        except ImportError:
            print("Error: GUI requires tkinter. Install it or use command-line mode.")
            return 1
    
    # Initialize config if requested
    if args.init_config:
        config = WatchDockConfig.default()
        config_path = Path(args.config)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config.save(str(config_path))
        print(f"Default configuration created at: {config_path}")
        print("Please edit the configuration file and add your API keys if needed.")
        return
    
    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Configuration file not found: {config_path}")
        print("Run with --init-config to create a default configuration file.")
        return 1
    
    config = WatchDockConfig.load(str(config_path))
    
    # Handle HITL actions
    if args.approve or args.reject or args.list_pending:
        from watchdock.pending_actions import PendingActionsQueue
        queue = PendingActionsQueue()
        
        if args.list_pending:
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
        
        if args.approve:
            action = queue.approve(args.approve)
            if action:
                # Execute the approved action
                from watchdock.file_organizer import FileOrganizer
                organizer = FileOrganizer(config.archive_config)
                result = organizer.organize_file(action.file_path, action.analysis)
                print(f"✅ Approved and executed: {action.file_path}")
                print(f"   Result: {result}")
                queue.remove(action.action_id)
            else:
                print(f"❌ Action not found: {args.approve}")
                return 1
            return 0
        
        if args.reject:
            action = queue.reject(args.reject)
            if action:
                print(f"❌ Rejected: {action.file_path}")
                queue.remove(action.action_id)
            else:
                print(f"❌ Action not found: {args.reject}")
                return 1
            return 0
    
    # Create and start WatchDock
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


if __name__ == '__main__':
    sys.exit(main())

