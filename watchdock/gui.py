"""
Native GUI application for WatchDock using Tkinter.
Modern ChatGPT/Cursor-style design with sidebar navigation.
"""

import os
import json
import platform
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
import logging

from watchdock import __version__
from watchdock.config import WatchDockConfig, WatchedFolder, AIConfig, ArchiveConfig
from watchdock.file_organizer import FileOrganizer
from watchdock.logging_utils import configure_logging
from watchdock.main import _validated_watched_source
from watchdock.paths import default_config_path
from watchdock.pending_actions import PendingActionsQueue

logger = logging.getLogger(__name__)

PROVIDER_DEFAULT_MODELS = {
    "openai": AIConfig().model,
    "anthropic": "claude-sonnet-4-5",
    "ollama": "qwen3",
}


@dataclass(frozen=True)
class GUIPaths:
    config_path: Path
    state_dir: Path
    examples_path: Path
    database_path: Path
    log_path: Path


@dataclass(frozen=True)
class ReviewExecutionResult:
    action_id: str
    success: bool
    status: str
    error: Optional[str] = None
    new_path: Optional[str] = None


def gui_paths(config_path: Optional[str] = None) -> GUIPaths:
    resolved_config = Path(config_path or default_config_path()).expanduser().resolve(
        strict=False
    )
    state_dir = resolved_config.parent
    return GUIPaths(
        config_path=resolved_config,
        state_dir=state_dir,
        examples_path=state_dir / "few_shot_examples.json",
        database_path=state_dir / "pending_actions.sqlite3",
        log_path=state_dir / "logs" / "watchdock.log",
    )


def parse_file_extensions(value: str) -> Optional[List[str]]:
    """Parse a friendly comma/semicolon list; blank means all extensions."""

    values = [item.strip() for item in value.replace(";", ",").split(",")]
    normalized = WatchedFolder(".", file_extensions=values).file_extensions
    return normalized or None


def build_config_from_gui(
    folders_data: Iterable[Mapping[str, Any]],
    *,
    provider: str,
    api_key: Optional[str],
    model: str,
    base_url: Optional[str],
    temperature: float,
    archive_base_path: str,
    create_date_folders: bool,
    create_category_folders: bool,
    move_files: bool,
    log_level: str,
    check_interval: Any,
    mode: str,
) -> WatchDockConfig:
    """Build and validate the complete config represented by GUI controls."""

    try:
        parsed_interval = float(check_interval)
    except (TypeError, ValueError) as exc:
        raise ValueError("check_interval must be a number greater than 0") from exc

    watched_folders = []
    for folder in folders_data:
        extensions = folder.get("file_extensions")
        if isinstance(extensions, str):
            extensions = parse_file_extensions(extensions)
        watched_folders.append(
            WatchedFolder(
                path=str(folder.get("path", "")),
                enabled=bool(folder.get("enabled", True)),
                recursive=bool(folder.get("recursive", True)),
                file_extensions=extensions,
            )
        )

    normalized_provider = provider.strip().lower()
    config = WatchDockConfig(
        watched_folders=watched_folders,
        ai_config=AIConfig(
            provider=normalized_provider,
            api_key=(api_key or "").strip() or None,
            model=model.strip() or PROVIDER_DEFAULT_MODELS.get(normalized_provider, ""),
            base_url=(base_url or "").strip() if normalized_provider == "ollama" else None,
            temperature=float(temperature),
        ),
        archive_config=ArchiveConfig(
            base_path=archive_base_path.strip(),
            create_date_folders=bool(create_date_folders),
            create_category_folders=bool(create_category_folders),
            move_files=bool(move_files),
        ),
        log_level=log_level,
        check_interval=parsed_interval,
        mode=mode,
    )
    config.validate()
    return config


def execute_review_action(
    queue_repository: PendingActionsQueue,
    organizer: FileOrganizer,
    action_id: str,
    *,
    config: WatchDockConfig,
    worker_id: str = "gui",
    retry_failed: bool = True,
) -> ReviewExecutionResult:
    """Claim and execute exactly one reviewed action, retaining every failure."""

    existing = queue_repository.get_by_id(action_id)
    if existing is None:
        return ReviewExecutionResult(action_id, False, "missing", "Action not found")
    if existing.status == "failed" and retry_failed:
        existing = queue_repository.retry(action_id)
        if existing is None:
            return ReviewExecutionResult(
                action_id, False, "failed", "Failed action could not be retried"
            )
    if existing.status != "pending":
        return ReviewExecutionResult(
            action_id,
            False,
            existing.status,
            f"Action is {existing.status}, not pending",
        )

    action = queue_repository.claim(action_id, worker_id=worker_id)
    if action is None:
        current = queue_repository.get_by_id(action_id)
        status = current.status if current else "missing"
        return ReviewExecutionResult(
            action_id, False, status, "Action was claimed by another process"
        )

    try:
        try:
            _validated_watched_source(config, action.file_path)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Source is no longer inside a currently enabled watched folder; "
                "action was not executed"
            ) from exc
        if not queue_repository.source_matches(action):
            raise RuntimeError(
                "Source changed or disappeared after review; action was not executed"
            )
        operation = organizer.execute_proposed_action(action.proposed_action)
        if not isinstance(operation, Mapping):
            raise RuntimeError("File organizer returned an invalid result")
        if operation.get("error"):
            raise RuntimeError(str(operation["error"]))

        completed = queue_repository.complete(action_id)
        if completed is None:
            raise RuntimeError(
                "File operation succeeded but completion could not be recorded"
            )
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        failed = queue_repository.fail(action_id, error)
        current = failed or queue_repository.get_by_id(action_id)
        return ReviewExecutionResult(
            action_id, False, current.status if current else "failed", error
        )
    return ReviewExecutionResult(
        action_id,
        True,
        completed.status,
        new_path=operation.get("new_path"),
    )


class WatchDockGUI:
    """Main GUI application for WatchDock with modern sidebar design."""
    
    def __init__(self, root, config_path: Optional[str] = None):
        self.root = root
        self.paths = gui_paths(config_path)
        self.config_path = self.paths.config_path
        self.state_dir = self.paths.state_dir
        self.examples_path = self.paths.examples_path
        self.database_path = self.paths.database_path
        self.log_path = self.paths.log_path
        self.root.title("WatchDock")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)
        self.root.minsize(1000, 700)

        # OpenAI-style dark theme colors (high contrast, refined)
        self.colors = {
            'bg': '#0D0D0D',           # Main background (almost black)
            'sidebar': '#171717',       # Sidebar background (slightly lighter)
            'card': '#1A1A1A',          # Card background
            'card_border': '#2A2A2A',   # Card border (subtle)
            'text': '#ECECEC',          # Primary text (high contrast white)
            'text_muted': '#A0A0A0',     # Muted text (lighter grey, still readable)
            'text_bright': '#FFFFFF',   # Bright text (pure white)
            'accent': '#10A37F',        # Accent green (OpenAI style)
            'accent_hover': '#0D8C6F',  # Accent hover
            'hover': '#252525',         # Hover background
            'selected': '#1A3A2E',      # Selected item (green tint)
            'input_bg': '#252525',      # Input background
            'input_border': '#3A3A3A',  # Input border
            'input_focus': '#10A37F',   # Input focus border
            'success': '#10A37F',       # Success green
            'warning': '#F59E0B',       # Warning amber
            'error': '#EF4444',         # Error red
            'divider': '#2A2A2A',       # Divider lines
        }
        
        self.root.configure(bg=self.colors['bg'], highlightbackground=self.colors['bg'], highlightcolor=self.colors['bg'])
        
        # Configure global widget styles to prevent white/grey highlights
        self._configure_global_styles()
        
        # Setup fonts (cross-platform compatible)
        default_font = tkfont.nametofont("TkDefaultFont")
        font_family = default_font.actual("family")
        self.fonts = {
            'title': tkfont.Font(family=font_family, size=24, weight="bold"),
            'heading': tkfont.Font(family=font_family, size=20, weight="bold"),
            'subtitle': tkfont.Font(family=font_family, size=10),
            'body': tkfont.Font(family=font_family, size=10),
            'body_bold': tkfont.Font(family=font_family, size=10, weight="bold"),
            'small': tkfont.Font(family=font_family, size=9),
            'nav': tkfont.Font(family=font_family, size=11),
        }
        
        # Load configuration
        self.config = self._load_config()
        configure_logging(self.config.log_level, self.log_path)
        self.few_shot_examples = self._load_few_shot_examples()
        self.pending_queue = PendingActionsQueue(db_path=self.database_path)
        self._provider_credentials = {
            self.config.ai_config.provider: self.config.ai_config.api_key
        }
        self._provider_models = {self.config.ai_config.provider: self.config.ai_config.model}
        self._provider_base_urls = {
            self.config.ai_config.provider: self.config.ai_config.base_url
        }
        self._active_provider = self.config.ai_config.provider

        # Monitoring runs outside Tk's event loop. Worker threads communicate
        # back only through this queue, which the Tk thread polls.
        self._service = None
        self._service_thread: Optional[threading.Thread] = None
        self._service_events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._service_lock = threading.Lock()
        self._monitor_stop_requested = threading.Event()
        self._monitor_status = "Stopped"
        self._closing = False
        self._close_deadline = 0.0
        
        # Current view
        self.current_view = "overview"
        
        # Create UI
        self._create_ui()
        self._populate_ui()
        
        self._refresh_pending_actions()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(250, self._poll_background_events)
        self.root.after(5000, self._auto_refresh_pending)
        startup_errors = []
        if self._config_load_error:
            startup_errors.append(
                f"Configuration could not be loaded:\n{self._config_load_error}\n"
                "Safe defaults are shown."
            )
        if self._examples_load_error:
            startup_errors.append(
                f"Few-shot examples could not be loaded:\n{self._examples_load_error}\n"
                "The existing examples file will not be overwritten. Repair it and Reload."
            )
        if startup_errors:
            detail = "\n\n".join(startup_errors)
            self.root.after_idle(
                lambda: messagebox.showerror(
                    "Saved settings need attention",
                    f"Could not fully load state beside {self.config_path}:\n\n{detail}",
                )
            )
    
    def _configure_global_styles(self):
        """Configure readable styles while preserving normal focus/keyboard use."""
        
        # Set option database for default widget colors (must be before widget creation)
        self.root.option_add("*background", self.colors['bg'])
        self.root.option_add("*foreground", self.colors['text_bright'])
        self.root.option_add("*selectBackground", self.colors['selected'])
        self.root.option_add("*selectForeground", self.colors['text_bright'])
        self.root.option_add("*highlightBackground", self.colors['bg'])
        self.root.option_add("*highlightColor", self.colors['bg'])
        self.root.option_add("*insertBackground", self.colors['text_bright'])
        self.root.option_add("*activeBackground", self.colors['hover'])
        self.root.option_add("*activeForeground", self.colors['text_bright'])
        
        # Configure ttk styles for dark theme
        style = ttk.Style(self.root)
        style.theme_use("clam")  # Use clam theme for better customization
        
        # Configure general ttk styles
        style.configure("TFrame", background=self.colors['bg'])
        style.configure("TLabel", background=self.colors['bg'], foreground=self.colors['text_bright'])
        style.configure("TButton", 
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       borderwidth=0,
                       focuscolor=self.colors['accent'])
        style.map("TButton",
                 background=[('active', self.colors['hover']),
                            ('pressed', self.colors['hover'])],
                 foreground=[('active', self.colors['text_bright']),
                           ('pressed', self.colors['text_bright'])])
        
        # Configure Entry/Input styles
        style.configure("TEntry",
                       fieldbackground=self.colors['input_bg'],
                       foreground=self.colors['text_bright'],
                       borderwidth=1,
                       relief=tk.FLAT,
                       insertcolor=self.colors['text_bright'],
                       selectbackground=self.colors['accent'],
                       selectforeground=self.colors['text_bright'])
        style.map("TEntry",
                 focuscolor=[('focus', self.colors['input_focus'])],
                 bordercolor=[('focus', self.colors['input_focus'])])
        
        # Configure Listbox styles
        style.configure("TListbox",
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       selectbackground=self.colors['selected'],
                       selectforeground=self.colors['text_bright'],
                       borderwidth=0,
                       relief=tk.FLAT)
        
        # Configure Treeview styles
        style.configure("Treeview",
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       fieldbackground=self.colors['card'],
                       borderwidth=0)
        style.configure("Treeview.Heading",
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       borderwidth=0)
        style.map("Treeview",
                 background=[('selected', self.colors['selected'])],
                 foreground=[('selected', self.colors['text_bright'])])
        
        # Configure Radiobutton styles
        style.configure("TRadiobutton",
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       selectcolor=self.colors['card'],
                       focuscolor=self.colors['accent'])
        style.map("TRadiobutton",
                 background=[('active', self.colors['card']),
                            ('selected', self.colors['card'])],
                 foreground=[('active', self.colors['text_bright']),
                            ('selected', self.colors['text_bright'])])
        
        # Configure Checkbutton styles
        style.configure("TCheckbutton",
                       background=self.colors['card'],
                       foreground=self.colors['text_bright'],
                       selectcolor=self.colors['card'],
                       focuscolor=self.colors['accent'])
        style.map("TCheckbutton",
                 background=[('active', self.colors['card']),
                            ('selected', self.colors['card'])],
                 foreground=[('active', self.colors['text_bright']),
                            ('selected', self.colors['text_bright'])])
        
        # Configure Scrollbar styles
        style.configure("TScrollbar",
                       background=self.colors['card'],
                       troughcolor=self.colors['bg'],
                       borderwidth=0,
                       arrowcolor=self.colors['text'],
                       darkcolor=self.colors['card'],
                       lightcolor=self.colors['card'])
        style.map("TScrollbar",
                 background=[('active', self.colors['hover'])],
                 arrowcolor=[('active', self.colors['text_bright'])])
    
    def _load_config(self) -> WatchDockConfig:
        """Load configuration from file."""
        self._config_load_error: Optional[str] = None
        try:
            if self.config_path.exists():
                return WatchDockConfig.load(str(self.config_path))
        except Exception as e:
            self._config_load_error = str(e)
            logger.error("Error loading config: %s", e)
        return WatchDockConfig.default()
    
    def _load_few_shot_examples(self) -> List[Dict]:
        """Load few-shot examples."""
        self._examples_load_error: Optional[str] = None
        try:
            return self._read_few_shot_examples()
        except Exception as e:
            self._examples_load_error = str(e)
            logger.error(f"Error loading examples: {e}")
        return []

    def _read_few_shot_examples(self) -> List[Dict]:
        """Read and validate examples without changing current GUI state."""
        if not self.examples_path.exists():
            return []
        with self.examples_path.open("r", encoding="utf-8") as examples_file:
            examples = json.load(examples_file)
        if not isinstance(examples, list) or not all(
            isinstance(example, dict) for example in examples
        ):
            raise ValueError("few-shot examples must be a JSON array of objects")
        return examples
    
    def _create_ui(self):
        """Create the UI with sidebar navigation."""
        # Main container
        main_container = tk.Frame(
            self.root, 
            bg=self.colors['bg'],
            highlightbackground=self.colors['bg'],
            highlightcolor=self.colors['bg'],
            highlightthickness=0
        )
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Sidebar
        self._create_sidebar(main_container)
        
        # Content area
        self.content_frame = tk.Frame(
            main_container, 
            bg=self.colors['bg'],
            highlightbackground=self.colors['bg'],
            highlightcolor=self.colors['bg'],
            highlightthickness=0
        )
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Header in content area
        self._create_header()
        
        # View container (scrollable)
        self.view_container = tk.Frame(
            self.content_frame, 
            bg=self.colors['bg'],
            highlightbackground=self.colors['bg'],
            highlightcolor=self.colors['bg'],
            highlightthickness=0
        )
        self.view_container.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)
        
        # Create all views (hidden initially)
        self.views = {}
        self._create_overview_view()
        self._create_general_view()
        self._create_folders_view()
        self._create_ai_view()
        self._create_archive_view()
        self._create_examples_view()
        self._create_pending_view()
        
        # Show overview by default
        self._show_view("overview")
        
        # Footer with status and actions
        self._create_footer()
    
    def _create_sidebar(self, parent):
        """Create sidebar navigation."""
        sidebar = tk.Frame(parent, bg=self.colors['sidebar'], width=240)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        
        # Logo/Title area
        logo_frame = tk.Frame(sidebar, bg=self.colors['sidebar'], height=80)
        logo_frame.pack(fill=tk.X, pady=(20, 10))
        
        title_label = tk.Label(
            logo_frame,
            text="WatchDock",
            font=self.fonts['heading'],
            bg=self.colors['sidebar'],
            fg=self.colors['text_bright']
        )
        title_label.pack(pady=(10, 0))
        
        subtitle_label = tk.Label(
            logo_frame,
            text="AI File Organizer",
            font=self.fonts['subtitle'],
            bg=self.colors['sidebar'],
            fg=self.colors['text_muted']
        )
        subtitle_label.pack()
        
        # Navigation items
        nav_items = [
            ("overview", "Overview", "📊"),
            ("general", "General", "⚙️"),
            ("folders", "Watched Folders", "📁"),
            ("ai", "AI Settings", "🤖"),
            ("archive", "Archive", "🗄️"),
            ("examples", "Examples", "📚"),
            ("pending", "Pending Actions", "⏳"),
        ]
        
        self.nav_buttons = {}
        for view_id, label, icon in nav_items:
            # Button container for better hover effect
            btn_frame = tk.Frame(sidebar, bg=self.colors['sidebar'])
            btn_frame.pack(fill=tk.X, padx=8, pady=2)
            
            btn = tk.Button(
                btn_frame,
                text=f"  {icon}  {label}",
                font=self.fonts['nav'],
                bg=self.colors['sidebar'],
                fg=self.colors['text_bright'],  # High contrast white
                activebackground=self.colors['hover'],
                activeforeground=self.colors['text_bright'],
                relief=tk.FLAT,
                anchor=tk.W,
                padx=20,
                pady=12,
                cursor="hand2",
                takefocus=True,
                highlightthickness=1,
                highlightbackground=self.colors['sidebar'],
                highlightcolor=self.colors['accent'],
                borderwidth=0,
                command=lambda v=view_id: self._show_view(v)
            )
            btn.pack(fill=tk.X)
            
            # Hover effect
            def on_enter(e, b=btn, f=btn_frame, v=view_id):
                if self.current_view != v:
                    b.configure(bg=self.colors['hover'])
                    f.configure(bg=self.colors['hover'])
            
            def on_leave(e, b=btn, f=btn_frame, v=view_id):
                if self.current_view != v:
                    b.configure(bg=self.colors['sidebar'])
                    f.configure(bg=self.colors['sidebar'])
            
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            
            self.nav_buttons[view_id] = btn
        
        # Version at bottom
        version_label = tk.Label(
            sidebar,
            text=f"v{__version__}",
            font=self.fonts['small'],
            bg=self.colors['sidebar'],
            fg=self.colors['text_muted']
        )
        version_label.pack(side=tk.BOTTOM, pady=16)
    
    def _create_header(self):
        """Create header in content area."""
        header = tk.Frame(self.content_frame, bg=self.colors['bg'], height=60)
        header.pack(fill=tk.X, padx=24, pady=(16, 0))
        header.pack_propagate(False)
        
        # Title (will be updated per view)
        self.header_title = tk.Label(
            header,
            text="Overview",
            font=self.fonts['title'],
            bg=self.colors['bg'],
            fg=self.colors['text_bright']
        )
        self.header_title.pack(side=tk.LEFT, pady=16)
    
    def _create_footer(self):
        """Create footer with status and save button."""
        footer = tk.Frame(self.content_frame, bg=self.colors['bg'], height=60)
        footer.pack(fill=tk.X, side=tk.BOTTOM, padx=24, pady=(0, 16))
        footer.pack_propagate(False)
        
        # Status
        self.status_label = tk.Label(
            footer,
            text="",
            font=self.fonts['small'],
            bg=self.colors['bg'],
            fg=self.colors['text']  # Better contrast than text_muted
        )
        self.status_label.pack(side=tk.LEFT, pady=16)
        
        # Action buttons
        btn_frame = tk.Frame(footer, bg=self.colors['bg'])
        btn_frame.pack(side=tk.RIGHT, pady=16)
        
        self.reload_button = self._create_button(
            btn_frame, "Reload", self._reload_config, secondary=True
        )
        self.reload_button.pack(side=tk.LEFT, padx=8)
        
        self.save_button = self._create_button(
            btn_frame, "Save Configuration", self._save_config
        )
        self.save_button.pack(side=tk.LEFT, padx=8)
    
    def _create_card(self, parent, title=None):
        """Create a modern card container with OpenAI-style design."""
        # Outer frame for border effect
        card_outer = tk.Frame(parent, bg=self.colors['card_border'], padx=1, pady=1)
        card = tk.Frame(card_outer, bg=self.colors['card'], relief=tk.FLAT)
        card.pack(fill=tk.BOTH, expand=True)
        
        if title:
            title_label = tk.Label(
                card,
                text=title,
                font=self.fonts['body_bold'],
                bg=self.colors['card'],
                fg=self.colors['text_bright'],
                anchor=tk.W
            )
            title_label.pack(fill=tk.X, padx=20, pady=(20, 12))
            
            # Divider line under title
            divider = tk.Frame(card, bg=self.colors['divider'], height=1)
            divider.pack(fill=tk.X, padx=20)
        
        return card_outer
    
    def _create_button(self, parent, text, command, secondary=False):
        """Create a modern button."""
        bg = self.colors['accent'] if not secondary else self.colors['card']
        fg = self.colors['text_bright'] if not secondary else self.colors['text']
        hover_bg = self.colors['accent_hover'] if not secondary else self.colors['hover']
        
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            font=self.fonts['body'],
            bg=bg,
            fg=fg,
            activebackground=hover_bg,
            activeforeground=fg,
            relief=tk.FLAT,
            padx=20,
            pady=10,
            cursor="hand2",
            takefocus=True,
            highlightthickness=1,
            highlightbackground=self.colors['card_border'],
            highlightcolor=self.colors['accent'],
            borderwidth=0
        )
        return btn
    
    def _create_entry(self, parent, width=50):
        """Create a modern entry field with OpenAI-style design."""
        entry = tk.Entry(
            parent,
            font=self.fonts['body'],
            bg=self.colors['input_bg'],
            fg=self.colors['text_bright'],  # High contrast white text
            insertbackground=self.colors['text_bright'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=2,
            highlightbackground=self.colors['input_border'],
            highlightcolor=self.colors['input_focus'],
            width=width,
            selectbackground=self.colors['accent'],
            selectforeground=self.colors['text_bright']
        )
        return entry
    
    def _show_view(self, view_id):
        """Show a specific view and update navigation."""
        # Hide all views
        for view in self.views.values():
            view.pack_forget()
        
        # Show selected view
        if view_id in self.views:
            self.views[view_id].pack(fill=tk.BOTH, expand=True)
            self.current_view = view_id
        
        # Update navigation highlighting
        for nav_id, btn in self.nav_buttons.items():
            btn_frame = btn.master  # Get the frame container
            if nav_id == view_id:
                btn.configure(bg=self.colors['selected'], fg=self.colors['text_bright'])
                btn_frame.configure(bg=self.colors['selected'])
            else:
                btn.configure(bg=self.colors['sidebar'], fg=self.colors['text_bright'])  # High contrast
                btn_frame.configure(bg=self.colors['sidebar'])
        
        # Update header title
        titles = {
            'overview': 'Overview',
            'general': 'General Settings',
            'folders': 'Watched Folders',
            'ai': 'AI Configuration',
            'archive': 'Archive Settings',
            'examples': 'Few-Shot Examples',
            'pending': 'Pending Actions',
        }
        self.header_title.config(text=titles.get(view_id, 'WatchDock'))
        
        # Update status
        self._update_status()
    
    def _create_overview_view(self):
        """Create overview view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['overview'] = frame
        
        # Summary card
        summary_card = self._create_card(frame, "Configuration Summary")
        summary_card.pack(fill=tk.X, pady=(0, 16))
        
        summary_content = tk.Frame(summary_card, bg=self.colors['card'])
        summary_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        self.overview_labels = {}
        rows = [
            ("Config File", "config_path"),
            ("Watched Folders", "watched_count"),
            ("Mode", "mode"),
            ("Provider", "provider"),
            ("Model", "model"),
        ]
        
        for idx, (label_text, key) in enumerate(rows):
            row = tk.Frame(summary_content, bg=self.colors['card'])
            row.pack(fill=tk.X, pady=8)
            
            label = tk.Label(
                row,
                text=label_text + ":",
                font=self.fonts['body'],
                bg=self.colors['card'],
                fg=self.colors['text_muted'],
                width=16,
                anchor=tk.W
            )
            label.pack(side=tk.LEFT)
            
            value_label = tk.Label(
                row,
                text="-",
                font=self.fonts['body'],
                bg=self.colors['card'],
                fg=self.colors['text_bright'],  # High contrast white for values
                anchor=tk.W
            )
            value_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.overview_labels[key] = value_label
        
        # Quick actions card
        actions_card = self._create_card(frame, "Quick Actions")
        actions_card.pack(fill=tk.X, pady=(0, 16))
        
        actions_content = tk.Frame(actions_card, bg=self.colors['card'])
        actions_content.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        # Use custom styled buttons instead of ttk
        self._create_button(
            actions_content,
            "Open Config Folder",
            self._open_config_folder,
            secondary=True
        ).pack(side=tk.LEFT, padx=8)
        
        self._create_button(
            actions_content,
            "Open Config File",
            self._open_config_file,
            secondary=True
        ).pack(side=tk.LEFT, padx=8)
        
        self._create_button(
            actions_content,
            "Open Log File",
            self._open_log_file,
            secondary=True
        ).pack(side=tk.LEFT, padx=8)

        monitor_card = self._create_card(frame, "File Monitor")
        monitor_card.pack(fill=tk.X)
        monitor_content = tk.Frame(monitor_card, bg=self.colors['card'])
        monitor_content.pack(fill=tk.X, padx=20, pady=(0, 20))

        self.monitor_start_button = self._create_button(
            monitor_content, "Start Monitor", self._start_monitor
        )
        self.monitor_start_button.pack(side=tk.LEFT, padx=(0, 8))
        self.monitor_stop_button = self._create_button(
            monitor_content, "Stop Monitor", self._stop_monitor, secondary=True
        )
        self.monitor_stop_button.pack(side=tk.LEFT, padx=8)
        self.monitor_status_label = tk.Label(
            monitor_content,
            text="Stopped",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text_muted'],
        )
        self.monitor_status_label.pack(side=tk.LEFT, padx=16)
        self._set_monitor_status("Stopped")
    
    def _create_general_view(self):
        """Create general settings view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['general'] = frame
        
        card = self._create_card(frame, "Operation Mode")
        card.pack(fill=tk.X)
        
        content = tk.Frame(card, bg=self.colors['card'])
        content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        self.mode_var = tk.StringVar(value="auto")
        
        mode_frame = tk.Frame(content, bg=self.colors['card'])
        mode_frame.pack(fill=tk.X, pady=12)
        
        auto_radio = tk.Radiobutton(
            mode_frame,
            text="Auto Mode - Automatically organize files",
            variable=self.mode_var,
            value="auto",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        auto_radio.pack(anchor=tk.W, pady=8)
        
        hitl_radio = tk.Radiobutton(
            mode_frame,
            text="HITL Mode - Request approval before organizing",
            variable=self.mode_var,
            value="hitl",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        hitl_radio.pack(anchor=tk.W, pady=8)
        
        desc_label = tk.Label(
            mode_frame,
            text="In HITL mode, files are analyzed and queued for approval.",
            font=self.fonts['small'],
            bg=self.colors['card'],
            fg=self.colors['text_muted']
        )
        desc_label.pack(anchor=tk.W, pady=(4, 0))

        runtime_card = self._create_card(frame, "Runtime Settings")
        runtime_card.pack(fill=tk.X, pady=(16, 0))
        runtime_content = tk.Frame(runtime_card, bg=self.colors['card'])
        runtime_content.pack(fill=tk.X, padx=20, pady=(0, 16))

        tk.Label(
            runtime_content,
            text="Log level:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=18,
            anchor=tk.W,
        ).grid(row=0, column=0, sticky=tk.W, pady=10)
        self.log_level_var = tk.StringVar(value="INFO")
        ttk.Combobox(
            runtime_content,
            textvariable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly",
            width=24,
        ).grid(row=0, column=1, sticky=tk.W, padx=8, pady=10)

        tk.Label(
            runtime_content,
            text="Stability interval (s):",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=18,
            anchor=tk.W,
        ).grid(row=1, column=0, sticky=tk.W, pady=10)
        self.check_interval_var = tk.StringVar(value="1.0")
        interval_entry = self._create_entry(runtime_content, width=16)
        interval_entry.config(textvariable=self.check_interval_var)
        interval_entry.grid(row=1, column=1, sticky=tk.W, padx=8, pady=10)
    
    def _create_folders_view(self):
        """Create watched folders view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['folders'] = frame
        
        # Instructions
        desc = tk.Label(
            frame,
            text="Add folders to monitor for new files",
            font=self.fonts['body'],
            bg=self.colors['bg'],
            fg=self.colors['text_muted']
        )
        desc.pack(anchor=tk.W, pady=(0, 16))
        
        # List card
        list_card = self._create_card(frame)
        list_card.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        
        list_content = tk.Frame(list_card, bg=self.colors['card'])
        list_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        
        scrollbar = tk.Scrollbar(list_content)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.folders_listbox = tk.Listbox(
            list_content,
            yscrollcommand=scrollbar.set,
            font=self.fonts['body'],
            bg=self.colors['input_bg'],
            fg=self.colors['text'],
            selectbackground=self.colors['selected'],
            selectforeground=self.colors['text_bright'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0
        )
        self.folders_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.folders_listbox.bind("<<ListboxSelect>>", self._on_folder_selected)
        scrollbar.config(command=self.folders_listbox.yview)
        
        # Options and buttons
        options_card = self._create_card(frame)
        options_card.pack(fill=tk.X)
        
        options_content = tk.Frame(options_card, bg=self.colors['card'])
        options_content.pack(fill=tk.X, padx=20, pady=16)
        folder_settings = tk.Frame(options_content, bg=self.colors['card'])
        folder_settings.pack(fill=tk.X)

        self.folder_enabled_var = tk.BooleanVar(value=True)
        enabled_cb = tk.Checkbutton(
            folder_settings,
            text="Enabled",
            variable=self.folder_enabled_var,
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        enabled_cb.pack(side=tk.LEFT, padx=8)
        
        self.folder_recursive_var = tk.BooleanVar(value=False)
        recursive_cb = tk.Checkbutton(
            folder_settings,
            text="Recursive (watch subfolders)",
            variable=self.folder_recursive_var,
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        recursive_cb.pack(side=tk.LEFT, padx=8)

        tk.Label(
            folder_settings,
            text="Extensions:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
        ).pack(side=tk.LEFT, padx=(16, 4))
        self.folder_extensions_var = tk.StringVar(value="")
        extensions_entry = self._create_entry(folder_settings, width=18)
        extensions_entry.config(textvariable=self.folder_extensions_var)
        extensions_entry.pack(side=tk.LEFT, padx=4)
        
        btn_frame = tk.Frame(options_content, bg=self.colors['card'])
        btn_frame.pack(fill=tk.X, pady=(12, 0))
        
        self._create_button(btn_frame, "Add Folder", self._add_folder, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(btn_frame, "Update", self._update_selected_folder, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(btn_frame, "Remove", self._remove_folder, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(btn_frame, "Browse", self._browse_folder, secondary=True).pack(side=tk.LEFT, padx=4)
        
        self.folders_data = []
    
    def _create_ai_view(self):
        """Create AI settings view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['ai'] = frame
        
        # Provider card
        provider_card = self._create_card(frame, "AI Provider")
        provider_card.pack(fill=tk.X, pady=(0, 16))
        
        provider_content = tk.Frame(provider_card, bg=self.colors['card'])
        provider_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        tk.Label(
            provider_content,
            text="Provider:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=12,
            anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.ai_provider_var = tk.StringVar(value="openai")
        provider_combo = ttk.Combobox(
            provider_content,
            textvariable=self.ai_provider_var,
            values=["openai", "anthropic", "ollama"],
            state="readonly",
            width=30,
            font=("SF Pro Display", 10)
        )
        provider_combo.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        
        # API Key card
        self.api_key_card = self._create_card(frame, "API Configuration")
        self.api_key_card.pack(fill=tk.X, pady=(0, 16))
        
        api_key_content = tk.Frame(self.api_key_card, bg=self.colors['card'])
        api_key_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        tk.Label(
            api_key_content,
            text="API Key:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=12,
            anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.api_key_var = tk.StringVar()
        api_key_entry = self._create_entry(api_key_content, width=50)
        api_key_entry.config(show="*")
        api_key_entry.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        api_key_entry.config(textvariable=self.api_key_var)
        
        # Base URL card (for Ollama)
        self.base_url_card = self._create_card(frame, "Base URL (for local providers)")
        self.base_url_card.pack(fill=tk.X, pady=(0, 16))
        
        base_url_content = tk.Frame(self.base_url_card, bg=self.colors['card'])
        base_url_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        tk.Label(
            base_url_content,
            text="Base URL:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=12,
            anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.base_url_var = tk.StringVar(value="http://localhost:11434/v1")
        base_url_entry = self._create_entry(base_url_content, width=50)
        base_url_entry.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        base_url_entry.config(textvariable=self.base_url_var)
        self.base_url_card.pack_forget()  # Hide by default
        
        # Model card
        self.model_card = self._create_card(frame, "Model")
        self.model_card.pack(fill=tk.X, pady=(0, 16))
        
        model_content = tk.Frame(self.model_card, bg=self.colors['card'])
        model_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        tk.Label(
            model_content,
            text="Model:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=12,
            anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.ai_model_var = tk.StringVar(value=PROVIDER_DEFAULT_MODELS["openai"])
        model_entry = self._create_entry(model_content, width=50)
        model_entry.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        model_entry.config(textvariable=self.ai_model_var)
        
        # Temperature card
        self.temperature_card = self._create_card(frame, "Temperature")
        self.temperature_card.pack(fill=tk.X)
        
        temp_content = tk.Frame(self.temperature_card, bg=self.colors['card'])
        temp_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        self.temperature_var = tk.DoubleVar(value=0.3)
        temp_scale = tk.Scale(
            temp_content,
            from_=0.0,
            to=1.0,
            variable=self.temperature_var,
            orient=tk.HORIZONTAL,
            bg=self.colors['card'],
            fg=self.colors['text'],
            troughcolor=self.colors['input_bg'],
            activebackground=self.colors['accent'],
            highlightthickness=0,
            length=400
        )
        temp_scale.grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.temp_label = tk.Label(
            temp_content,
            text="0.3",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=6
        )
        self.temp_label.grid(row=0, column=1, pady=12, padx=8)
        temp_scale.config(command=lambda v: self.temp_label.config(text=f"{float(v):.1f}"))
    
    def _create_archive_view(self):
        """Create archive settings view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['archive'] = frame
        
        # Archive path card
        path_card = self._create_card(frame, "Archive Location")
        path_card.pack(fill=tk.X, pady=(0, 16))
        
        path_content = tk.Frame(path_card, bg=self.colors['card'])
        path_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        tk.Label(
            path_content,
            text="Base Path:",
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            width=12,
            anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=12)
        
        self.archive_path_var = tk.StringVar()
        path_entry = self._create_entry(path_content, width=50)
        path_entry.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        path_entry.config(textvariable=self.archive_path_var)
        
        browse_btn = self._create_button(path_content, "Browse...", self._browse_archive_path, secondary=True)
        browse_btn.grid(row=0, column=2, pady=12, padx=8)
        
        # Options card
        options_card = self._create_card(frame, "Organization Options")
        options_card.pack(fill=tk.X)
        
        options_content = tk.Frame(options_card, bg=self.colors['card'])
        options_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        self.create_date_folders_var = tk.BooleanVar(value=True)
        date_cb = tk.Checkbutton(
            options_content,
            text="Create date folders (YYYY-MM)",
            variable=self.create_date_folders_var,
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        date_cb.pack(anchor=tk.W, pady=8)
        
        self.create_category_folders_var = tk.BooleanVar(value=True)
        cat_cb = tk.Checkbutton(
            options_content,
            text="Create category folders",
            variable=self.create_category_folders_var,
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        cat_cb.pack(anchor=tk.W, pady=8)
        
        self.move_files_var = tk.BooleanVar(value=True)
        move_cb = tk.Checkbutton(
            options_content,
            text="Move files to archive (uncheck to only rename in place)",
            variable=self.move_files_var,
            font=self.fonts['body'],
            bg=self.colors['card'],
            fg=self.colors['text'],
            selectcolor=self.colors['card'],
            activebackground=self.colors['card'],
            activeforeground=self.colors['text'],
            cursor="hand2"
        )
        move_cb.pack(anchor=tk.W, pady=8)
    
    def _create_examples_view(self):
        """Create few-shot examples view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['examples'] = frame
        
        # Instructions
        desc = tk.Label(
            frame,
            text="Add examples to help the AI learn your organization preferences",
            font=self.fonts['body'],
            bg=self.colors['bg'],
            fg=self.colors['text_muted']
        )
        desc.pack(anchor=tk.W, pady=(0, 16))
        
        # List card
        list_card = self._create_card(frame)
        list_card.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        
        list_content = tk.Frame(list_card, bg=self.colors['card'])
        list_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        
        scrollbar = tk.Scrollbar(list_content)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.examples_listbox = tk.Listbox(
            list_content,
            yscrollcommand=scrollbar.set,
            font=self.fonts['body'],
            bg=self.colors['input_bg'],
            fg=self.colors['text'],
            selectbackground=self.colors['selected'],
            selectforeground=self.colors['text_bright'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0
        )
        self.examples_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.examples_listbox.yview)
        
        # Form card
        form_card = self._create_card(frame, "Example Details")
        form_card.pack(fill=tk.X)
        
        form_content = tk.Frame(form_card, bg=self.colors['card'])
        form_content.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        fields = [
            ("Original Filename:", "example_file_var"),
            ("Category:", "example_category_var"),
            ("Suggested Name:", "example_name_var"),
            ("Tags (comma-separated):", "example_tags_var"),
        ]
        
        for idx, (label_text, var_name) in enumerate(fields):
            tk.Label(
                form_content,
                text=label_text,
                font=self.fonts['body'],
                bg=self.colors['card'],
                fg=self.colors['text'],
                width=20,
                anchor=tk.W
            ).grid(row=idx, column=0, sticky=tk.W, pady=12)
            
            var = tk.StringVar()
            setattr(self, var_name, var)
            entry = self._create_entry(form_content, width=40)
            entry.grid(row=idx, column=1, sticky=tk.W, pady=12, padx=8)
            entry.config(textvariable=var)
        
        # Buttons
        btn_frame = tk.Frame(form_content, bg=self.colors['card'])
        btn_frame.grid(row=len(fields), column=0, columnspan=2, pady=12, sticky=tk.W)
        
        self._create_button(btn_frame, "Add Example", self._add_example, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(btn_frame, "Remove", self._remove_example, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(btn_frame, "Clear", self._clear_example_form, secondary=True).pack(side=tk.LEFT, padx=4)
    
    def _create_pending_view(self):
        """Create pending actions view."""
        frame = tk.Frame(self.view_container, bg=self.colors['bg'])
        self.views['pending'] = frame
        
        # Instructions
        desc = tk.Label(
            frame,
            text="Pending file organization actions (HITL mode)",
            font=self.fonts['body'],
            bg=self.colors['bg'],
            fg=self.colors['text_muted']
        )
        desc.pack(anchor=tk.W, pady=(0, 16))
        
        # Treeview card
        tree_card = self._create_card(frame)
        tree_card.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        
        tree_content = tk.Frame(tree_card, bg=self.colors['card'])
        tree_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        
        columns = ("Status", "File", "Category", "Action", "Destination", "Error")
        self.pending_tree = ttk.Treeview(
            tree_content,
            columns=columns,
            show="tree headings",
            height=15
        )
        
        # Style treeview
        style = ttk.Style()
        style.configure("Treeview", background=self.colors['input_bg'], foreground=self.colors['text'], fieldbackground=self.colors['input_bg'])
        style.map("Treeview", background=[("selected", self.colors['selected'])])
        
        self.pending_tree.heading("#0", text="ID")
        self.pending_tree.heading("Status", text="Status")
        self.pending_tree.heading("File", text="File")
        self.pending_tree.heading("Category", text="Category")
        self.pending_tree.heading("Action", text="Action")
        self.pending_tree.heading("Destination", text="Destination")
        self.pending_tree.heading("Error", text="Error")
        
        self.pending_tree.column("#0", width=110)
        self.pending_tree.column("Status", width=80)
        self.pending_tree.column("File", width=160)
        self.pending_tree.column("Category", width=100)
        self.pending_tree.column("Action", width=80)
        self.pending_tree.column("Destination", width=220)
        self.pending_tree.column("Error", width=220)
        
        scrollbar_tree = tk.Scrollbar(tree_content, orient=tk.VERTICAL, command=self.pending_tree.yview)
        self.pending_tree.configure(yscrollcommand=scrollbar_tree.set)
        
        self.pending_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tree.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Action buttons card
        action_card = self._create_card(frame)
        action_card.pack(fill=tk.X)
        
        action_content = tk.Frame(action_card, bg=self.colors['card'])
        action_content.pack(fill=tk.X, padx=20, pady=16)
        review_buttons = tk.Frame(action_content, bg=self.colors['card'])
        review_buttons.pack(fill=tk.X)

        self._create_button(review_buttons, "Approve / Retry Selected", self._approve_selected, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(review_buttons, "Reject Selected", self._reject_selected, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(review_buttons, "Approve All", self._approve_all, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(review_buttons, "Refresh", self._refresh_pending_actions, secondary=True).pack(side=tk.LEFT, padx=4)

        # Status label
        self.pending_status_label = tk.Label(
            action_content,
            text="No pending actions",
            font=self.fonts['small'],
            bg=self.colors['card'],
            fg=self.colors['text_muted']
        )
        self.pending_status_label.pack(anchor=tk.W, padx=4, pady=(12, 0))
    
    def _populate_ui(self):
        """Populate UI with current configuration."""
        self.folders_data = []
        for folder in self.config.watched_folders:
            self.folders_data.append({
                'path': folder.path,
                'enabled': folder.enabled,
                'recursive': folder.recursive,
                'file_extensions': (
                    list(folder.file_extensions)
                    if folder.file_extensions is not None
                    else None
                ),
            })
            self.folders_listbox.insert(tk.END, folder.path)

        if self.folders_data:
            self.folders_listbox.selection_set(0)
            self._on_folder_selected()

        # AI settings
        provider = self.config.ai_config.provider
        self._provider_credentials[provider] = self.config.ai_config.api_key
        self._provider_models[provider] = self.config.ai_config.model
        self._provider_base_urls[provider] = self.config.ai_config.base_url
        self._active_provider = None
        self.ai_provider_var.set(provider)
        self.ai_model_var.set(self.config.ai_config.model)
        self.api_key_var.set(self.config.ai_config.api_key or "")
        self.base_url_var.set(
            self.config.ai_config.base_url or "http://localhost:11434/v1"
        )
        self.temperature_var.set(self.config.ai_config.temperature)
        self.temp_label.config(text=f"{self.config.ai_config.temperature:.1f}")
        self._active_provider = provider
        self._on_provider_change(remember_current=False)

        # Archive settings
        self.archive_path_var.set(self.config.archive_config.base_path)
        self.create_date_folders_var.set(self.config.archive_config.create_date_folders)
        self.create_category_folders_var.set(self.config.archive_config.create_category_folders)
        self.move_files_var.set(self.config.archive_config.move_files)

        # Examples
        for example in self.few_shot_examples:
            self.examples_listbox.insert(tk.END, f"{example.get('file_name', '')} → {example.get('category', '')}")

        self.mode_var.set(self.config.mode)
        self.log_level_var.set(self.config.log_level)
        self.check_interval_var.set(str(self.config.check_interval))

        self._refresh_pending_actions()
        self._update_overview()
        self._update_status()
    
    def _update_overview(self):
        """Update overview labels."""
        watched_count = len(self.config.watched_folders)
        provider = self.config.ai_config.provider
        model = self.config.ai_config.model
        mode = self.config.mode
        
        if hasattr(self, "overview_labels"):
            self.overview_labels["config_path"].config(text=str(self.config_path))
            self.overview_labels["watched_count"].config(text=str(watched_count))
            self.overview_labels["mode"].config(text=mode)
            self.overview_labels["provider"].config(text=provider)
            self.overview_labels["model"].config(text=model)
    
    def _update_status(self):
        """Update status bar."""
        mode = self.config.mode
        provider = self.config.ai_config.provider
        model = self.config.ai_config.model
        
        if hasattr(self, "status_label"):
            self.status_label.config(
                text=f"Config: {self.config_path}  |  Mode: {mode}  |  "
                f"Provider: {provider}  |  Model: {model}  |  "
                f"Monitor: {self._monitor_status}  |  v{__version__}"
            )
    
    def _open_path(self, path: Path):
        """Open a file or folder in the OS file manager."""
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open: {path}\n{e}")
    
    def _open_config_folder(self):
        """Open the config folder."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(self.state_dir)
    
    def _open_config_file(self):
        """Open the config file."""
        if not self.config_path.exists():
            messagebox.showinfo(
                "Info", "The configuration has not been saved yet."
            )
            return
        self._open_path(self.config_path)
    
    def _open_log_file(self):
        """Open the log file if it exists."""
        if not self.log_path.exists():
            messagebox.showinfo("Info", f"No log file found at {self.log_path}")
            return
        self._open_path(self.log_path)
    
    def _on_provider_change(self, event=None, *, remember_current=True):
        """Handle provider change."""
        provider = self.ai_provider_var.get()
        previous = self._active_provider
        if remember_current and previous:
            self._provider_credentials[previous] = (
                self.api_key_var.get().strip() or None
            )
            self._provider_models[previous] = (
                self.ai_model_var.get().strip()
                or PROVIDER_DEFAULT_MODELS.get(previous, "")
            )
            if previous == "ollama":
                self._provider_base_urls[previous] = (
                    self.base_url_var.get().strip() or None
                )

        self._active_provider = provider
        self.api_key_var.set(self._provider_credentials.get(provider) or "")
        self.ai_model_var.set(
            self._provider_models.get(provider)
            or PROVIDER_DEFAULT_MODELS.get(provider, "")
        )
        if provider == "ollama":
            self.base_url_var.set(
                self._provider_base_urls.get(provider)
                or "http://localhost:11434/v1"
            )
        self.api_key_card.pack_forget()
        self.base_url_card.pack_forget()
        provider_card = (
            self.base_url_card if provider == "ollama" else self.api_key_card
        )
        provider_card.pack(
            fill=tk.X, pady=(0, 16), before=self.model_card
        )
    
    def _add_folder(self):
        """Add a folder to watch."""
        folder = filedialog.askdirectory(title="Select folder to watch")
        if folder:
            self.folders_data.append({
                'path': folder,
                'enabled': self.folder_enabled_var.get(),
                'recursive': self.folder_recursive_var.get(),
                'file_extensions': parse_file_extensions(
                    self.folder_extensions_var.get()
                ),
            })
            self.folders_listbox.insert(tk.END, folder)
            index = len(self.folders_data) - 1
            self.folders_listbox.selection_clear(0, tk.END)
            self.folders_listbox.selection_set(index)
            self.folders_listbox.see(index)

    def _on_folder_selected(self, event=None):
        """Load the selected folder's settings into the editor controls."""
        selection = self.folders_listbox.curselection()
        if not selection:
            return
        folder = self.folders_data[selection[0]]
        self.folder_enabled_var.set(bool(folder.get('enabled', True)))
        self.folder_recursive_var.set(bool(folder.get('recursive', True)))
        extensions = folder.get('file_extensions')
        self.folder_extensions_var.set(
            ", ".join(extensions) if extensions is not None else ""
        )

    def _update_selected_folder(self, *, show_warning=True):
        """Apply option controls to the selected watched folder."""
        selection = self.folders_listbox.curselection()
        if not selection:
            if show_warning:
                messagebox.showwarning("Warning", "Please select a folder to update.")
            return False
        folder = self.folders_data[selection[0]]
        folder['enabled'] = self.folder_enabled_var.get()
        folder['recursive'] = self.folder_recursive_var.get()
        folder['file_extensions'] = parse_file_extensions(
            self.folder_extensions_var.get()
        )
        return True
    
    def _browse_folder(self):
        """Browse for folder."""
        folder = filedialog.askdirectory(title="Select folder to watch")
        if folder:
            selection = self.folders_listbox.curselection()
            if selection:
                idx = selection[0]
                self.folders_data[idx]['path'] = folder
                self.folders_listbox.delete(idx)
                self.folders_listbox.insert(idx, folder)
                self.folders_listbox.selection_set(idx)
            else:
                self.folders_data.append({
                    'path': folder,
                    'enabled': self.folder_enabled_var.get(),
                    'recursive': self.folder_recursive_var.get(),
                    'file_extensions': parse_file_extensions(
                        self.folder_extensions_var.get()
                    ),
                })
                self.folders_listbox.insert(tk.END, folder)
    
    def _remove_folder(self):
        """Remove selected folder."""
        selection = self.folders_listbox.curselection()
        if selection:
            idx = selection[0]
            self.folders_listbox.delete(idx)
            self.folders_data.pop(idx)
            if self.folders_data:
                next_index = min(idx, len(self.folders_data) - 1)
                self.folders_listbox.selection_set(next_index)
                self._on_folder_selected()
    
    def _browse_archive_path(self):
        """Browse for archive path."""
        folder = filedialog.askdirectory(title="Select archive base folder")
        if folder:
            self.archive_path_var.set(folder)
    
    def _add_example(self):
        """Add a few-shot example."""
        file_name = self.example_file_var.get().strip()
        category = self.example_category_var.get().strip()
        suggested_name = self.example_name_var.get().strip()
        tags_str = self.example_tags_var.get().strip()
        
        if not file_name or not category or not suggested_name:
            messagebox.showwarning("Warning", "Please fill in at least filename, category, and suggested name.")
            return
        
        tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []
        
        example = {
            'file_name': file_name,
            'category': category,
            'suggested_name': suggested_name,
            'tags': tags,
            'description': ''
        }
        
        self.few_shot_examples.append(example)
        self.examples_listbox.insert(tk.END, f"{file_name} → {category}")
        self._clear_example_form()
    
    def _remove_example(self):
        """Remove selected example."""
        selection = self.examples_listbox.curselection()
        if selection:
            idx = selection[0]
            self.examples_listbox.delete(idx)
            self.few_shot_examples.pop(idx)
    
    def _clear_example_form(self):
        """Clear example form."""
        self.example_file_var.set("")
        self.example_category_var.set("")
        self.example_name_var.set("")
        self.example_tags_var.set("")

    def _monitor_thread_is_alive(self) -> bool:
        thread = getattr(self, "_service_thread", None)
        return bool(thread is not None and thread.is_alive())

    def _configuration_change_allowed(self, operation: str) -> bool:
        """Keep disk/current settings aligned with the active monitor snapshot."""
        if not self._monitor_thread_is_alive():
            return True
        messagebox.showwarning(
            "Stop Monitor first",
            f"Stop Monitor before {operation} configuration. "
            "This keeps the running monitor and the displayed settings in sync.",
        )
        return False
    
    def _reload_config(self):
        """Reload configuration from file."""
        if not self._configuration_change_allowed("reloading"):
            return False
        try:
            config = WatchDockConfig.load(str(self.config_path))
            examples = self._read_few_shot_examples()
        except Exception as exc:
            if self.examples_path.exists():
                try:
                    self._read_few_shot_examples()
                except Exception as examples_exc:
                    self._examples_load_error = str(examples_exc)
            messagebox.showerror(
                "Reload failed",
                f"The current settings were kept because the saved files are invalid:\n{exc}",
            )
            logger.error("Error reloading GUI configuration: %s", exc, exc_info=True)
            return False

        self.config = config
        self.few_shot_examples = examples
        self._config_load_error = None
        self._examples_load_error = None
        self._provider_credentials = {config.ai_config.provider: config.ai_config.api_key}
        self._provider_models = {config.ai_config.provider: config.ai_config.model}
        self._provider_base_urls = {
            config.ai_config.provider: config.ai_config.base_url
        }
        self._active_provider = config.ai_config.provider
        self.folders_listbox.delete(0, tk.END)
        self.examples_listbox.delete(0, tk.END)
        self._populate_ui()
        try:
            configure_logging(config.log_level, self.log_path)
        except Exception as exc:
            messagebox.showwarning(
                "Configuration reloaded with a logging error",
                f"Configuration and examples were reloaded, but logging could not "
                f"be reconfigured:\n{exc}",
            )
            logger.error("Error reconfiguring logging: %s", exc, exc_info=True)
            return True
        messagebox.showinfo("Success", "Configuration reloaded.")
        return True

    def _config_from_controls(self) -> WatchDockConfig:
        """Return a validated snapshot of every editable GUI setting."""
        self._update_selected_folder(show_warning=False)
        self._on_provider_change()
        provider = self.ai_provider_var.get().strip().lower()
        return build_config_from_gui(
            self.folders_data,
            provider=provider,
            api_key=self._provider_credentials.get(provider),
            model=self._provider_models.get(provider, self.ai_model_var.get()),
            base_url=(
                self._provider_base_urls.get(provider, self.base_url_var.get())
                if provider == "ollama"
                else None
            ),
            temperature=self.temperature_var.get(),
            archive_base_path=self.archive_path_var.get(),
            create_date_folders=self.create_date_folders_var.get(),
            create_category_folders=self.create_category_folders_var.get(),
            move_files=self.move_files_var.get(),
            log_level=self.log_level_var.get(),
            check_interval=self.check_interval_var.get(),
            mode=self.mode_var.get(),
        )

    def _save_examples(self) -> None:
        """Atomically persist few-shot examples beside the selected config."""
        if self._examples_load_error:
            raise RuntimeError(
                "the existing few-shot examples file was not loaded and was left "
                "untouched; repair it and Reload before saving examples"
            )
        payload = json.dumps(
            self.few_shot_examples, indent=2, ensure_ascii=False
        ) + "\n"
        self.examples_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.examples_path.parent),
            prefix=f".{self.examples_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self.examples_path)
            self._examples_load_error = None
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _save_config(self, *, show_success=True):
        """Save configuration."""
        if not self._configuration_change_allowed("saving"):
            return False

        # Validation and the primary config write are all-or-nothing. Once that
        # atomic save succeeds, update current state before optional follow-up
        # writes so the GUI never claims the config itself was not saved.
        try:
            config = self._config_from_controls()
            config.save(str(self.config_path))
        except Exception as exc:
            messagebox.showerror(
                "Configuration not saved", f"Configuration was not saved:\n{exc}"
            )
            logger.error("Error saving config: %s", exc, exc_info=True)
            return False

        self.config = config
        self._config_load_error = None
        follow_up_errors = []
        try:
            self._save_examples()
        except Exception as exc:
            follow_up_errors.append(f"Few-shot examples were not saved: {exc}")
            logger.error("Error saving examples: %s", exc, exc_info=True)
        try:
            configure_logging(config.log_level, self.log_path)
        except Exception as exc:
            follow_up_errors.append(f"Logging was not reconfigured: {exc}")
            logger.error("Error configuring logging: %s", exc, exc_info=True)

        self._refresh_pending_actions()
        self._update_overview()
        self._update_status()
        if follow_up_errors:
            messagebox.showwarning(
                "Configuration saved with follow-up errors",
                f"Configuration was saved to {self.config_path}.\n\n"
                + "\n".join(f"• {error}" for error in follow_up_errors),
            )
            return False
        if show_success:
            messagebox.showinfo("Success", "Configuration saved successfully.")
        return True
    
    def _refresh_pending_actions(self):
        """Refresh pending and failed review actions from the colocated database."""
        try:
            for item in self.pending_tree.get_children():
                self.pending_tree.delete(item)

            review_actions = self.pending_queue.list_actions(["pending", "failed"])
            for action in review_actions:
                file_name = Path(action.file_path).name
                category = action.analysis.get('category', 'Unknown')
                action_type = action.proposed_action.get('action_type', 'move')
                destination = action.proposed_action.get('to', 'N/A')
                error = (action.error or "").replace("\n", " ")
                if len(error) > 160:
                    error = error[:157] + "..."
                self.pending_tree.insert(
                    "",
                    tk.END,
                    text=action.action_id,
                    values=(
                        action.status,
                        file_name,
                        category,
                        action_type,
                        destination,
                        error,
                    ),
                )

            pending_count = sum(
                action.status == "pending" for action in review_actions
            )
            failed_count = sum(
                action.status == "failed" for action in review_actions
            )
            if failed_count:
                self.pending_status_label.config(
                    text=(
                        f"{pending_count} pending, {failed_count} failed "
                        "(failed actions can be retried or rejected)"
                    ),
                    fg=self.colors['error'],
                )
            elif pending_count:
                self.pending_status_label.config(
                    text=f"{pending_count} pending action(s)",
                    fg=self.colors['accent'],
                )
            else:
                self.pending_status_label.config(
                    text="No actions awaiting review",
                    fg=self.colors['text_muted'],
                )
        except Exception as exc:
            self.pending_status_label.config(
                text=f"Could not load review queue: {exc}", fg=self.colors['error']
            )
            logger.error("Error refreshing pending actions: %s", exc, exc_info=True)
    
    def _auto_refresh_pending(self):
        """Auto-refresh pending actions (called periodically)."""
        if not self._closing:
            self._refresh_pending_actions()
            self.root.after(5000, self._auto_refresh_pending)

    def _selected_review_action_ids(self) -> List[str]:
        return [
            str(self.pending_tree.item(item_id, "text"))
            for item_id in self.pending_tree.selection()
        ]

    def _execute_review_actions(self, action_ids: Iterable[str]) -> List[ReviewExecutionResult]:
        organizer = FileOrganizer(self.config.archive_config)
        return [
            execute_review_action(
                self.pending_queue,
                organizer,
                action_id,
                config=self.config,
                worker_id=f"gui-{os.getpid()}",
            )
            for action_id in action_ids
        ]

    def _show_review_results(self, results: List[ReviewExecutionResult]) -> None:
        completed = [result for result in results if result.success]
        failures = [result for result in results if not result.success]
        if failures:
            details = "\n".join(
                f"• {result.action_id}: {result.error or result.status}"
                for result in failures[:8]
            )
            if len(failures) > 8:
                details += f"\n• … and {len(failures) - 8} more"
            messagebox.showerror(
                "Review actions",
                f"Completed: {len(completed)}\n"
                f"Failed and retained for review: {len(failures)}\n\n{details}",
            )
        elif completed:
            messagebox.showinfo(
                "Success", f"Completed {len(completed)} reviewed action(s)."
            )

    def _approve_selected(self):
        """Claim and execute selected pending/failed actions truthfully."""
        action_ids = self._selected_review_action_ids()
        if not action_ids:
            messagebox.showwarning("Warning", "Please select an action to approve.")
            return
        try:
            results = self._execute_review_actions(action_ids)
        except Exception as exc:
            messagebox.showerror("Review actions", f"Could not execute actions:\n{exc}")
            logger.error("Could not execute review actions: %s", exc, exc_info=True)
            return
        self._show_review_results(results)
        self._refresh_pending_actions()

    def _reject_selected(self):
        """Durably reject selected pending or failed actions."""
        action_ids = self._selected_review_action_ids()
        if not action_ids:
            messagebox.showwarning("Warning", "Please select an action to reject.")
            return

        rejected = [
            action_id
            for action_id in action_ids
            if self.pending_queue.reject(action_id) is not None
        ]
        if rejected:
            messagebox.showinfo("Success", f"Rejected {len(rejected)} action(s).")
        if len(rejected) != len(action_ids):
            messagebox.showwarning(
                "Review actions",
                f"{len(action_ids) - len(rejected)} action(s) were no longer rejectable.",
            )
        self._refresh_pending_actions()

    def _approve_all(self):
        """Approve all pending actions."""
        pending = self.pending_queue.get_pending()
        if not pending:
            messagebox.showinfo("Info", "No pending actions to approve.")
            return
        
        confirmed = messagebox.askyesno(
            "Confirm", f"Approve all {len(pending)} pending action(s)?"
        )
        if not confirmed:
            return
        try:
            results = self._execute_review_actions(
                action.action_id for action in pending
            )
        except Exception as exc:
            messagebox.showerror("Review actions", f"Could not execute actions:\n{exc}")
            logger.error("Could not execute review actions: %s", exc, exc_info=True)
            return
        self._show_review_results(results)
        self._refresh_pending_actions()

    def _set_monitor_status(self, status: str, *, is_error=False) -> None:
        self._monitor_status = status
        live = status in {"Starting", "Running", "Stopping"}
        if hasattr(self, "monitor_status_label"):
            self.monitor_status_label.config(
                text=status,
                fg=self.colors['error'] if is_error else (
                    self.colors['accent'] if live else self.colors['text_muted']
                ),
            )
            self.monitor_start_button.config(
                state=tk.DISABLED if live else tk.NORMAL
            )
            self.monitor_stop_button.config(
                state=tk.NORMAL if status in {"Starting", "Running"} else tk.DISABLED
            )
        if hasattr(self, "save_button"):
            config_state = tk.DISABLED if live else tk.NORMAL
            self.save_button.config(state=config_state)
            self.reload_button.config(state=config_state)
        self._update_status()

    def _start_monitor(self):
        """Save validated settings and launch monitoring outside Tk's thread."""
        if self._service_thread and self._service_thread.is_alive():
            messagebox.showinfo("Monitor", "The file monitor is already running.")
            return
        if not self._save_config(show_success=False):
            return

        # A completed worker posts before its thread becomes non-alive, so any
        # events present here belong to the previous monitor generation.
        while True:
            try:
                self._service_events.get_nowait()
            except queue.Empty:
                break
        self._monitor_stop_requested.clear()
        self._set_monitor_status("Starting")
        self._service_thread = threading.Thread(
            target=self._monitor_worker,
            args=(self.config,),
            name="watchdock-gui-monitor",
            daemon=True,
        )
        self._service_thread.start()

    def _monitor_worker(self, config: WatchDockConfig) -> None:
        failure: Optional[str] = None
        service = None
        try:
            from watchdock.main import WatchDock

            service = WatchDock(config, state_dir=self.state_dir)
            with self._service_lock:
                self._service = service
            if self._monitor_stop_requested.is_set():
                return
            service.start()
        except Exception as exc:
            failure = str(exc) or exc.__class__.__name__
            logger.error("GUI monitor stopped: %s", failure, exc_info=True)
        finally:
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    logger.debug("Could not stop GUI monitor cleanly", exc_info=True)
            with self._service_lock:
                if self._service is service:
                    self._service = None
            self._service_events.put(
                ("error", failure) if failure else ("stopped", "Stopped")
            )

    def _stop_monitor(self):
        """Request monitor shutdown without blocking Tk's event loop."""
        thread = self._service_thread
        if thread is None or not thread.is_alive():
            self._set_monitor_status("Stopped")
            return
        self._monitor_stop_requested.set()
        self._set_monitor_status("Stopping")
        threading.Thread(
            target=self._stop_service_until_finished,
            args=(thread,),
            name="watchdock-gui-stop",
            daemon=True,
        ).start()

    def _stop_service_until_finished(self, monitor_thread: threading.Thread) -> None:
        """Bridge cancellation races while the monitor service is starting."""
        while monitor_thread.is_alive():
            with self._service_lock:
                service = self._service
            if service is not None and (
                service.running or service.watcher is not None
            ):
                try:
                    service.stop()
                except Exception:
                    logger.debug("Monitor stop attempt failed", exc_info=True)
            monitor_thread.join(timeout=0.1)

    def _poll_background_events(self):
        """Apply worker status updates on Tk's owning thread."""
        with self._service_lock:
            service = self._service
        if (
            service is not None
            and service.running
            and self._monitor_status == "Starting"
        ):
            self._set_monitor_status("Running")

        while True:
            try:
                event_type, detail = self._service_events.get_nowait()
            except queue.Empty:
                break
            if event_type == "error":
                self._set_monitor_status(f"Error: {detail}", is_error=True)
                if not self._closing:
                    messagebox.showerror("Monitor stopped", detail)
            elif event_type == "stopped":
                self._set_monitor_status(detail)

        if not self._closing:
            self.root.after(250, self._poll_background_events)

    def _on_close(self):
        """Stop background work before closing, with a bounded UI wait."""
        if self._closing:
            return
        self._closing = True
        self._close_deadline = time.monotonic() + 3.0
        thread = self._service_thread
        if thread is not None and thread.is_alive():
            self._stop_monitor()
            self.root.after(50, self._finish_close)
        else:
            self.root.destroy()

    def _finish_close(self):
        thread = self._service_thread
        if (
            thread is not None
            and thread.is_alive()
            and time.monotonic() < self._close_deadline
        ):
            self.root.after(50, self._finish_close)
            return
        self.root.destroy()


def run_gui(config_path: Optional[str] = None):
    """Run the GUI application."""
    root = tk.Tk()
    app = WatchDockGUI(root, config_path=config_path)
    root.mainloop()
    return app


if __name__ == '__main__':
    run_gui()
