"""
Native GUI application for WatchDock using Tkinter.
Modern ChatGPT/Cursor-style design with sidebar navigation.
"""

import os
import json
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter import font as tkfont
from pathlib import Path
from typing import List, Dict, Optional
import logging

from watchdock import __version__
from watchdock.config import WatchDockConfig, WatchedFolder, AIConfig, ArchiveConfig
from watchdock.pending_actions import PendingActionsQueue

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = str(Path.home() / '.watchdock' / 'config.json')
FEW_SHOT_EXAMPLES_PATH = str(Path.home() / '.watchdock' / 'few_shot_examples.json')


class WatchDockGUI:
    """Main GUI application for WatchDock with modern sidebar design."""
    
    def __init__(self, root):
        self.root = root
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
        
        self.root.configure(bg=self.colors['bg'])
        
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
        self.few_shot_examples = self._load_few_shot_examples()
        self.pending_queue = PendingActionsQueue()
        
        # Current view
        self.current_view = "overview"
        
        # Create UI
        self._create_ui()
        self._populate_ui()
        
        # Auto-refresh pending actions if in HITL mode
        if self.config.mode == "hitl":
            self._refresh_pending_actions()
            self.root.after(5000, self._auto_refresh_pending)
    
    def _load_config(self) -> WatchDockConfig:
        """Load configuration from file."""
        try:
            if os.path.exists(DEFAULT_CONFIG_PATH):
                return WatchDockConfig.load(DEFAULT_CONFIG_PATH)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
        return WatchDockConfig.default()
    
    def _load_few_shot_examples(self) -> List[Dict]:
        """Load few-shot examples."""
        try:
            if os.path.exists(FEW_SHOT_EXAMPLES_PATH):
                with open(FEW_SHOT_EXAMPLES_PATH, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading examples: {e}")
        return []
    
    def _create_ui(self):
        """Create the UI with sidebar navigation."""
        # Main container
        main_container = tk.Frame(self.root, bg=self.colors['bg'])
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Sidebar
        self._create_sidebar(main_container)
        
        # Content area
        self.content_frame = tk.Frame(main_container, bg=self.colors['bg'])
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Header in content area
        self._create_header()
        
        # View container (scrollable)
        self.view_container = tk.Frame(self.content_frame, bg=self.colors['bg'])
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
                command=lambda v=view_id: self._show_view(v)
            )
            btn.pack(fill=tk.X)
            
            # Hover effect
            def on_enter(e, b=btn, f=btn_frame):
                if self.current_view != view_id:
                    b.configure(bg=self.colors['hover'])
                    f.configure(bg=self.colors['hover'])
            
            def on_leave(e, b=btn, f=btn_frame):
                if self.current_view != view_id:
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
        
        reload_btn = self._create_button(btn_frame, "Reload", self._reload_config, secondary=True)
        reload_btn.pack(side=tk.LEFT, padx=8)
        
        save_btn = self._create_button(btn_frame, "Save Configuration", self._save_config)
        save_btn.pack(side=tk.LEFT, padx=8)
    
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
            cursor="hand2"
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
        actions_card.pack(fill=tk.X)
        
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
        scrollbar.config(command=self.folders_listbox.yview)
        
        # Options and buttons
        options_card = self._create_card(frame)
        options_card.pack(fill=tk.X)
        
        options_content = tk.Frame(options_card, bg=self.colors['card'])
        options_content.pack(fill=tk.X, padx=20, pady=16)
        
        self.folder_enabled_var = tk.BooleanVar(value=True)
        enabled_cb = tk.Checkbutton(
            options_content,
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
            options_content,
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
        
        btn_frame = tk.Frame(options_content, bg=self.colors['card'])
        btn_frame.pack(side=tk.RIGHT)
        
        self._create_button(btn_frame, "Add Folder", self._add_folder, secondary=True).pack(side=tk.LEFT, padx=4)
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
        model_card = self._create_card(frame, "Model")
        model_card.pack(fill=tk.X, pady=(0, 16))
        
        model_content = tk.Frame(model_card, bg=self.colors['card'])
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
        
        self.ai_model_var = tk.StringVar(value="gpt-4")
        model_entry = self._create_entry(model_content, width=50)
        model_entry.grid(row=0, column=1, sticky=tk.W, pady=12, padx=8)
        model_entry.config(textvariable=self.ai_model_var)
        
        # Temperature card
        temp_card = self._create_card(frame, "Temperature")
        temp_card.pack(fill=tk.X)
        
        temp_content = tk.Frame(temp_card, bg=self.colors['card'])
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
        
        columns = ("File", "Category", "Action", "Destination")
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
        self.pending_tree.heading("File", text="File")
        self.pending_tree.heading("Category", text="Category")
        self.pending_tree.heading("Action", text="Action")
        self.pending_tree.heading("Destination", text="Destination")
        
        self.pending_tree.column("#0", width=150)
        self.pending_tree.column("File", width=200)
        self.pending_tree.column("Category", width=100)
        self.pending_tree.column("Action", width=80)
        self.pending_tree.column("Destination", width=250)
        
        scrollbar_tree = tk.Scrollbar(tree_content, orient=tk.VERTICAL, command=self.pending_tree.yview)
        self.pending_tree.configure(yscrollcommand=scrollbar_tree.set)
        
        self.pending_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tree.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Action buttons card
        action_card = self._create_card(frame)
        action_card.pack(fill=tk.X)
        
        action_content = tk.Frame(action_card, bg=self.colors['card'])
        action_content.pack(fill=tk.X, padx=20, pady=16)
        
        self._create_button(action_content, "Approve Selected", self._approve_selected, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(action_content, "Reject Selected", self._reject_selected, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(action_content, "Approve All", self._approve_all, secondary=True).pack(side=tk.LEFT, padx=4)
        self._create_button(action_content, "Refresh", self._refresh_pending_actions, secondary=True).pack(side=tk.LEFT, padx=4)
        
        # Status label
        self.pending_status_label = tk.Label(
            action_content,
            text="No pending actions",
            font=self.fonts['small'],
            bg=self.colors['card'],
            fg=self.colors['text_muted']
        )
        self.pending_status_label.pack(side=tk.LEFT, padx=16)
    
    def _populate_ui(self):
        """Populate UI with current configuration."""
        # Folders
        self.folders_data = []
        for folder in self.config.watched_folders:
            self.folders_data.append({
                'path': folder.path,
                'enabled': folder.enabled,
                'recursive': folder.recursive
            })
            self.folders_listbox.insert(tk.END, folder.path)
        
        # AI settings
        self.ai_provider_var.set(self.config.ai_config.provider)
        self.ai_model_var.set(self.config.ai_config.model)
        self.base_url_var.set(self.config.ai_config.base_url or "http://localhost:11434/v1")
        self.temperature_var.set(self.config.ai_config.temperature)
        self.temp_label.config(text=f"{self.config.ai_config.temperature:.1f}")
        self._on_provider_change()
        
        # Archive settings
        self.archive_path_var.set(self.config.archive_config.base_path)
        self.create_date_folders_var.set(self.config.archive_config.create_date_folders)
        self.create_category_folders_var.set(self.config.archive_config.create_category_folders)
        self.move_files_var.set(self.config.archive_config.move_files)
        
        # Examples
        for example in self.few_shot_examples:
            self.examples_listbox.insert(tk.END, f"{example.get('file_name', '')} → {example.get('category', '')}")
        
        # Mode
        self.mode_var.set(self.config.mode)
        
        # Refresh pending actions if in HITL mode
        if self.config.mode == "hitl":
            self._refresh_pending_actions()
        
        self._update_overview()
        self._update_status()
    
    def _update_overview(self):
        """Update overview labels."""
        config_path = Path(DEFAULT_CONFIG_PATH)
        watched_count = len(self.config.watched_folders)
        provider = self.config.ai_config.provider
        model = self.config.ai_config.model
        mode = self.config.mode
        
        if hasattr(self, "overview_labels"):
            self.overview_labels["config_path"].config(text=str(config_path))
            self.overview_labels["watched_count"].config(text=str(watched_count))
            self.overview_labels["mode"].config(text=mode)
            self.overview_labels["provider"].config(text=provider)
            self.overview_labels["model"].config(text=model)
    
    def _update_status(self):
        """Update status bar."""
        config_path = Path(DEFAULT_CONFIG_PATH)
        mode = self.config.mode
        provider = self.config.ai_config.provider
        model = self.config.ai_config.model
        
        if hasattr(self, "status_label"):
            self.status_label.config(
                text=f"Config: {config_path}  |  Mode: {mode}  |  Provider: {provider}  |  Model: {model}  |  v{__version__}"
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
        self._open_path(Path(DEFAULT_CONFIG_PATH).parent)
    
    def _open_config_file(self):
        """Open the config file."""
        self._open_path(Path(DEFAULT_CONFIG_PATH))
    
    def _open_log_file(self):
        """Open the log file if it exists."""
        log_path = Path.cwd() / "watchdock.log"
        if not log_path.exists():
            messagebox.showinfo("Info", f"No log file found at {log_path}")
            return
        self._open_path(log_path)
    
    def _on_provider_change(self, event=None):
        """Handle provider change."""
        provider = self.ai_provider_var.get()
        if provider == "ollama":
            self.api_key_card.pack_forget()
            self.base_url_card.pack(fill=tk.X, pady=(0, 16))
        else:
            self.base_url_card.pack_forget()
            self.api_key_card.pack(fill=tk.X, pady=(0, 16))
    
    def _add_folder(self):
        """Add a folder to watch."""
        folder = filedialog.askdirectory(title="Select folder to watch")
        if folder:
            self.folders_data.append({
                'path': folder,
                'enabled': self.folder_enabled_var.get(),
                'recursive': self.folder_recursive_var.get()
            })
            self.folders_listbox.insert(tk.END, folder)
    
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
                self._add_folder()
    
    def _remove_folder(self):
        """Remove selected folder."""
        selection = self.folders_listbox.curselection()
        if selection:
            idx = selection[0]
            self.folders_listbox.delete(idx)
            self.folders_data.pop(idx)
    
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
    
    def _reload_config(self):
        """Reload configuration from file."""
        self.config = self._load_config()
        self.few_shot_examples = self._load_few_shot_examples()
        
        # Clear and repopulate
        self.folders_listbox.delete(0, tk.END)
        self.examples_listbox.delete(0, tk.END)
        self._populate_ui()
        messagebox.showinfo("Success", "Configuration reloaded!")
    
    def _save_config(self):
        """Save configuration."""
        try:
            # Build watched folders
            watched_folders = []
            for i, folder_data in enumerate(self.folders_data):
                watched_folders.append(WatchedFolder(
                    path=folder_data['path'],
                    enabled=folder_data['enabled'],
                    recursive=folder_data['recursive'],
                    file_extensions=None
                ))
            
            # Build AI config
            provider = self.ai_provider_var.get()
            api_key_input = self.api_key_var.get().strip()
            
            # Use input API key if provided, otherwise preserve existing
            if api_key_input:
                api_key = api_key_input
            elif provider != "ollama" and self.config.ai_config.api_key:
                api_key = self.config.ai_config.api_key
            else:
                api_key = None
            
            ai_config = AIConfig(
                provider=provider,
                api_key=api_key,
                model=self.ai_model_var.get(),
                base_url=self.base_url_var.get() if provider == "ollama" else None,
                temperature=self.temperature_var.get()
            )
            
            # Build archive config
            archive_config = ArchiveConfig(
                base_path=self.archive_path_var.get(),
                create_date_folders=self.create_date_folders_var.get(),
                create_category_folders=self.create_category_folders_var.get(),
                move_files=self.move_files_var.get()
            )
            
            # Create and save config
            self.config = WatchDockConfig(
                watched_folders=watched_folders,
                ai_config=ai_config,
                archive_config=archive_config,
                log_level="INFO",
                check_interval=1.0,
                mode=self.mode_var.get()
            )
            
            config_path = Path(DEFAULT_CONFIG_PATH)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.save(DEFAULT_CONFIG_PATH)
            
            # Save examples
            examples_path = Path(FEW_SHOT_EXAMPLES_PATH)
            examples_path.parent.mkdir(parents=True, exist_ok=True)
            with open(FEW_SHOT_EXAMPLES_PATH, 'w') as f:
                json.dump(self.few_shot_examples, f, indent=2)
            
            messagebox.showinfo("Success", "Configuration saved successfully!")
            
            # Reload pending queue if mode changed
            if self.config.mode == "hitl":
                self.pending_queue = PendingActionsQueue()
                self._refresh_pending_actions()
            
            self._update_overview()
            self._update_status()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
            logger.error(f"Error saving config: {e}", exc_info=True)
    
    def _refresh_pending_actions(self):
        """Refresh the pending actions list."""
        try:
            # Clear existing items
            for item in self.pending_tree.get_children():
                self.pending_tree.delete(item)
            
            # Reload queue
            self.pending_queue = PendingActionsQueue()
            pending = self.pending_queue.get_pending()
            
            # Add items to tree
            for action in pending:
                file_name = Path(action.file_path).name
                category = action.analysis.get('category', 'Unknown')
                action_type = action.proposed_action.get('action_type', 'move')
                destination = action.proposed_action.get('to', 'N/A')
                
                self.pending_tree.insert("", tk.END, 
                                       text=action.action_id,
                                       values=(file_name, category, action_type, destination))
            
            # Update status
            count = len(pending)
            if count > 0:
                self.pending_status_label.config(text=f"{count} pending action(s)", fg=self.colors['accent'])
            else:
                self.pending_status_label.config(text="No pending actions", fg=self.colors['text_muted'])
        except Exception as e:
            logger.error(f"Error refreshing pending actions: {e}")
    
    def _auto_refresh_pending(self):
        """Auto-refresh pending actions (called periodically)."""
        if self.config.mode == "hitl":
            self._refresh_pending_actions()
            self.root.after(5000, self._auto_refresh_pending)
    
    def _approve_selected(self):
        """Approve selected pending action(s)."""
        selected = self.pending_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select an action to approve.")
            return
        
        approved_count = 0
        for item_id in selected:
            action_id = self.pending_tree.item(item_id, "text")
            action = self.pending_queue.approve(action_id)
            if action:
                try:
                    from watchdock.file_organizer import FileOrganizer
                    organizer = FileOrganizer(self.config.archive_config)
                    result = organizer.organize_file(action.file_path, action.analysis)
                    self.pending_queue.remove(action_id)
                    approved_count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to execute action: {e}")
                    logger.error(f"Error executing action: {e}")
        
        if approved_count > 0:
            messagebox.showinfo("Success", f"Approved and executed {approved_count} action(s).")
            self._refresh_pending_actions()
    
    def _reject_selected(self):
        """Reject selected pending action(s)."""
        selected = self.pending_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select an action to reject.")
            return
        
        rejected_count = 0
        for item_id in selected:
            action_id = self.pending_tree.item(item_id, "text")
            action = self.pending_queue.reject(action_id)
            if action:
                self.pending_queue.remove(action_id)
                rejected_count += 1
        
        if rejected_count > 0:
            messagebox.showinfo("Success", f"Rejected {rejected_count} action(s).")
            self._refresh_pending_actions()
    
    def _approve_all(self):
        """Approve all pending actions."""
        pending = self.pending_queue.get_pending()
        if not pending:
            messagebox.showinfo("Info", "No pending actions to approve.")
            return
        
        result = messagebox.askyesno("Confirm", f"Approve all {len(pending)} pending action(s)?")
        if result:
            approved_count = 0
            for action in pending:
                self.pending_queue.approve(action.action_id)
                try:
                    from watchdock.file_organizer import FileOrganizer
                    organizer = FileOrganizer(self.config.archive_config)
                    result = organizer.organize_file(action.file_path, action.analysis)
                    self.pending_queue.remove(action.action_id)
                    approved_count += 1
                except Exception as e:
                    logger.error(f"Error executing action {action.action_id}: {e}")
            
            messagebox.showinfo("Success", f"Approved and executed {approved_count} action(s).")
            self._refresh_pending_actions()


def run_gui():
    """Run the GUI application."""
    root = tk.Tk()
    app = WatchDockGUI(root)
    root.mainloop()


if __name__ == '__main__':
    run_gui()
