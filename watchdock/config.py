"""
Configuration management for WatchDock.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class WatchedFolder:
    """Configuration for a watched folder."""
    path: str
    enabled: bool = True
    recursive: bool = True
    file_extensions: Optional[List[str]] = None  # None means all files


@dataclass
class AIConfig:
    """AI provider configuration."""
    provider: str  # "openai", "anthropic", "ollama", "local"
    api_key: Optional[str] = None
    model: str = "gpt-4"
    base_url: Optional[str] = None  # For local providers like Ollama
    temperature: float = 0.3


@dataclass
class ArchiveConfig:
    """Archive/organization configuration."""
    base_path: str
    create_date_folders: bool = True
    create_category_folders: bool = True
    move_files: bool = True  # If False, just rename/tag in place


@dataclass
class WatchDockConfig:
    """Main configuration for WatchDock."""
    watched_folders: List[WatchedFolder]
    ai_config: AIConfig
    archive_config: ArchiveConfig
    log_level: str = "INFO"
    check_interval: float = 1.0  # seconds
    mode: str = "auto"  # "auto" or "hitl" (Human-In-The-Loop)

    @classmethod
    def load(cls, config_path: str) -> "WatchDockConfig":
        """Load configuration from JSON file."""
        if not os.path.exists(config_path):
            return cls.default()
        
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        return cls(
            watched_folders=[WatchedFolder(**wf) for wf in data.get('watched_folders', [])],
            ai_config=AIConfig(**data.get('ai_config', {})),
            archive_config=ArchiveConfig(**data.get('archive_config', {})),
            log_level=data.get('log_level', 'INFO'),
            check_interval=data.get('check_interval', 1.0),
            mode=data.get('mode', 'auto')
        )
    
    def save(self, config_path: str):
        """Save configuration to JSON file."""
        data = {
            'watched_folders': [asdict(wf) for wf in self.watched_folders],
            'ai_config': asdict(self.ai_config),
            'archive_config': asdict(self.archive_config),
            'log_level': self.log_level,
            'check_interval': self.check_interval,
            'mode': self.mode
        }
        
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def default(cls) -> "WatchDockConfig":
        """Create default configuration."""
        downloads_path = str(Path.home() / "Downloads")
        
        return cls(
            watched_folders=[
                WatchedFolder(
                    path=downloads_path,
                    enabled=True,
                    recursive=False,
                    file_extensions=None
                )
            ],
            ai_config=AIConfig(
                provider="openai",
                model="gpt-4",
                temperature=0.3
            ),
            archive_config=ArchiveConfig(
                base_path=str(Path.home() / "Documents" / "Archive"),
                create_date_folders=True,
                create_category_folders=True,
                move_files=True
            ),
            log_level="INFO",
            check_interval=1.0,
            mode="auto"
        )

