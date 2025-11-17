"""
File organizer that renames, tags, and moves files based on AI analysis.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class FileOrganizer:
    """Organizes files based on AI analysis results."""
    
    def __init__(self, config):
        self.config = config
        self.archive_base = Path(config.archive_config.base_path)
        self.archive_base.mkdir(parents=True, exist_ok=True)
    
    def get_proposed_action(self, file_path: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get proposed action without executing it (for HITL mode).
        
        Returns:
            Dict with proposed action details
        """
        source_path = Path(file_path)
        
        if self.config.move_files:
            dest_path = self._get_destination_path(source_path, analysis)
            return {
                'action_type': 'move',
                'from': str(source_path),
                'to': str(dest_path),
                'new_name': dest_path.name,
                'category': analysis.get('category', 'Other'),
                'tags': analysis.get('tags', [])
            }
        else:
            new_name = analysis.get('suggested_name', source_path.name)
            return {
                'action_type': 'rename',
                'from': str(source_path),
                'to': str(source_path.parent / new_name),
                'new_name': new_name,
                'category': analysis.get('category', 'Other'),
                'tags': analysis.get('tags', [])
            }
    
    def organize_file(self, file_path: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Organize a file based on analysis results.
        
        Returns:
            Dict with operation results: moved, renamed, new_path, tags_applied
        """
        source_path = Path(file_path)
        results = {
            'original_path': str(source_path),
            'moved': False,
            'renamed': False,
            'new_path': None,
            'tags_applied': False,
            'error': None
        }
        
        try:
            # Determine destination
            if self.config.archive_config.move_files:
                dest_path = self._get_destination_path(source_path, analysis)
                results['new_path'] = str(dest_path)
                
                # Move file
                if dest_path != source_path:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Handle name conflicts
                    if dest_path.exists():
                        dest_path = self._handle_name_conflict(dest_path)
                        results['new_path'] = str(dest_path)
                    
                    shutil.move(str(source_path), str(dest_path))
                    results['moved'] = True
                    logger.info(f"Moved {source_path} -> {dest_path}")
            else:
                # Just rename in place
                new_name = analysis.get('suggested_name', source_path.name)
                if new_name != source_path.name:
                    dest_path = source_path.parent / new_name
                    if dest_path.exists():
                        dest_path = self._handle_name_conflict(dest_path)
                    
                    source_path.rename(dest_path)
                    results['renamed'] = True
                    results['new_path'] = str(dest_path)
                    logger.info(f"Renamed {source_path} -> {dest_path}")
            
            # Apply tags (store in metadata file or extended attributes if supported)
            if analysis.get('tags'):
                self._apply_tags(results['new_path'] or str(source_path), analysis['tags'])
                results['tags_applied'] = True
            
        except Exception as e:
            logger.error(f"Error organizing file {file_path}: {e}")
            results['error'] = str(e)
        
        return results
    
    def _get_destination_path(self, source_path: Path, analysis: Dict[str, Any]) -> Path:
        """Calculate the destination path for a file."""
        # Start with archive base
        dest_parts = [self.archive_base]
        
        # Add date folder if enabled
        if self.config.archive_config.create_date_folders:
            date_str = datetime.now().strftime("%Y-%m")
            dest_parts.append(date_str)
        
        # Add category folder if enabled
        if self.config.archive_config.create_category_folders:
            category = analysis.get('category', 'Other')
            dest_parts.append(category)
        
        # Build destination directory
        dest_dir = Path(*dest_parts)
        
        # Use suggested name or original name
        suggested_name = analysis.get('suggested_name', source_path.name)
        dest_path = dest_dir / suggested_name
        
        return dest_path
    
    def _handle_name_conflict(self, path: Path) -> Path:
        """Handle filename conflicts by appending a number."""
        if not path.exists():
            return path
        
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        
        counter = 1
        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return new_path
            counter += 1
    
    def _apply_tags(self, file_path: str, tags: list):
        """Apply tags to a file (store in metadata file)."""
        try:
            # Create a metadata file alongside the file
            metadata_path = Path(file_path).with_suffix('.watchdock_meta.json')
            
            import json
            metadata = {
                'tags': tags,
                'tagged_at': datetime.now().isoformat()
            }
            
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug(f"Applied tags to {file_path}: {tags}")
        except Exception as e:
            logger.warning(f"Could not apply tags to {file_path}: {e}")

