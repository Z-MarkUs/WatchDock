"""
File system watcher for monitoring folders.
"""

import time
import logging
from pathlib import Path
from typing import Set, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)


class WatchDockHandler(FileSystemEventHandler):
    """Handler for file system events."""
    
    def __init__(self, callback: Callable[[str], None], processed_files: Set[str]):
        super().__init__()
        self.callback = callback
        self.processed_files = processed_files
        self.ignored_extensions = {'.tmp', '.temp', '.crdownload', '.part', '.watchdock_meta.json'}
    
    def on_created(self, event: FileSystemEvent):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        file_path = event.src_path
        self._handle_file(file_path)
    
    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events."""
        if event.is_directory:
            return
        
        file_path = event.src_path
        self._handle_file(file_path)
    
    def on_moved(self, event: FileSystemEvent):
        """Handle file move events."""
        if event.is_directory:
            return
        
        # When a file is moved, the destination is in event.dest_path
        if hasattr(event, 'dest_path'):
            self._handle_file(event.dest_path)
    
    def _handle_file(self, file_path: str):
        """Process a file event."""
        path = Path(file_path)
        
        # Skip ignored files
        if path.suffix.lower() in self.ignored_extensions:
            return
        
        # Skip already processed files
        if file_path in self.processed_files:
            return
        
        # Skip if file doesn't exist (might be a temporary file)
        if not path.exists():
            return
        
        # Wait a bit to ensure file is fully written (especially for downloads)
        time.sleep(0.5)
        
        # Check again if file exists
        if not path.exists():
            return
        
        # Check if file is still being written (for downloads)
        try:
            size1 = path.stat().st_size
            time.sleep(0.5)
            size2 = path.stat().st_size
            if size1 != size2:
                # File is still being written, skip for now
                logger.debug(f"File {file_path} is still being written, skipping")
                return
        except Exception as e:
            logger.debug(f"Could not check file size: {e}")
            return
        
        # Mark as processed and call callback
        self.processed_files.add(file_path)
        logger.info(f"Processing new file: {file_path}")
        self.callback(file_path)


class FileWatcher:
    """Watches folders for new or modified files."""
    
    def __init__(self, watched_folders: list, callback: Callable[[str], None]):
        self.watched_folders = watched_folders
        self.callback = callback
        self.observer = Observer()
        self.processed_files: Set[str] = set()
        self.handlers = []
    
    def start(self):
        """Start watching folders."""
        for folder_config in self.watched_folders:
            if not folder_config.enabled:
                continue
            
            folder_path = Path(folder_config.path)
            if not folder_path.exists():
                logger.warning(f"Watched folder does not exist: {folder_path}")
                continue
            
            handler = WatchDockHandler(self.callback, self.processed_files)
            self.handlers.append(handler)
            
            self.observer.schedule(
                handler,
                str(folder_path),
                recursive=folder_config.recursive
            )
            
            logger.info(f"Watching folder: {folder_path} (recursive: {folder_config.recursive})")
        
        self.observer.start()
        logger.info("File watcher started")
    
    def stop(self):
        """Stop watching folders."""
        self.observer.stop()
        self.observer.join()
        logger.info("File watcher stopped")
    
    def is_alive(self) -> bool:
        """Check if watcher is running."""
        return self.observer.is_alive()

