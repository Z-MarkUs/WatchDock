"""
Main application entry point for WatchDock.
"""

import sys
import signal
import logging
import argparse
from pathlib import Path
from watchdock.config import WatchDockConfig
from watchdock.watcher import FileWatcher
from watchdock.ai_processor import AIProcessor
from watchdock.file_organizer import FileOrganizer


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
        self.watcher = None
        self.running = False
    
    def process_file(self, file_path: str):
        """Process a single file."""
        try:
            logger.info(f"Analyzing file: {file_path}")
            
            # Analyze file with AI
            analysis = self.ai_processor.analyze_file(file_path)
            logger.info(f"Analysis result: {analysis}")
            
            # Organize file
            result = self.file_organizer.organize_file(file_path, analysis)
            logger.info(f"Organization result: {result}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}", exc_info=True)
    
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
    
    args = parser.parse_args()
    
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

