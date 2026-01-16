"""
Native GUI application for WatchDock using Tkinter.
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
    """Main GUI application for WatchDock."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("WatchDock - File Organization Tool")
        self.root.geometry("880x720")
        self.root.resizable(True, True)
        self.root.minsize(860, 680)

        self._apply_theme()
        
        # Try to set window icon (if available)
        try:
            # You can add an icon file later
            pass
        except:
            pass
        
        # Load configuration
        self.config = self._load_config()
        self.few_shot_examples = self._load_few_shot_examples()
        self.pending_queue = PendingActionsQueue()
        
        # Create UI
        self._create_ui()
        self._populate_ui()
        
        # Auto-refresh pending actions if in HITL mode
        if self.config.mode == "hitl":
            self._refresh_pending_actions()
            self.root.after(5000, self._auto_refresh_pending)  # Refresh every 5 seconds
    
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
    
    def _save_config(self):
        """Save configuration to file."""
        try:
            config_path = Path(DEFAULT_CONFIG_PATH)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.save(DEFAULT_CONFIG_PATH)
            
            # Save few-shot examples
            examples_path = Path(FEW_SHOT_EXAMPLES_PATH)
            examples_path.parent.mkdir(parents=True, exist_ok=True)
            with open(FEW_SHOT_EXAMPLES_PATH, 'w') as f:
                json.dump(self.few_shot_examples, f, indent=2)
            
            messagebox.showinfo("Success", "Configuration saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
    
    def _create_ui(self):
        """Create the UI components."""
        header = ttk.Frame(self.root, style="Header.TFrame")
        header.pack(fill=tk.X, padx=16, pady=(16, 8))

        ttk.Label(header, text="WatchDock", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Smart file organization with AI",
            style="Subtitle.TLabel"
        ).pack(anchor=tk.W, pady=(2, 0))

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        
        # Create tabs
        self._create_overview_tab()
        self._create_general_tab()
        self._create_folders_tab()
        self._create_ai_tab()
        self._create_archive_tab()
        self._create_examples_tab()
        self._create_pending_tab()
        
        # Create bottom buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=16, pady=(8, 16))
        
        ttk.Button(button_frame, text="Save Configuration", command=self._save_config, style="Primary.TButton").pack(side=tk.RIGHT, padx=6)
        ttk.Button(button_frame, text="Reload", command=self._reload_config).pack(side=tk.RIGHT, padx=6)
        if self.config.mode == "hitl":
            ttk.Button(button_frame, text="Refresh Pending", command=self._refresh_pending_actions).pack(side=tk.LEFT, padx=6)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=16, pady=(0, 12))
        self.status_label = ttk.Label(status_frame, style="Muted.TLabel")
        self.status_label.pack(anchor=tk.W)
    def _create_overview_tab(self):
        """Create overview tab with quick actions."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Overview")

        summary_frame = ttk.LabelFrame(frame, text="Setup Summary")
        summary_frame.pack(fill=tk.X, padx=16, pady=12)

        self.overview_labels = {}
        rows = [
            ("Config File", "config_path"),
            ("Watched Folders", "watched_count"),
            ("Mode", "mode"),
            ("Provider", "provider"),
            ("Model", "model"),
        ]
        for idx, (label_text, key) in enumerate(rows):
            ttk.Label(summary_frame, text=label_text + ":", style="Section.TLabel").grid(
                row=idx, column=0, sticky=tk.W, padx=8, pady=6
            )
            value_label = ttk.Label(summary_frame, text="-", style="Muted.TLabel")
            value_label.grid(row=idx, column=1, sticky=tk.W, padx=8, pady=6)
            self.overview_labels[key] = value_label

        summary_frame.columnconfigure(1, weight=1)

        actions_frame = ttk.LabelFrame(frame, text="Quick Actions")
        actions_frame.pack(fill=tk.X, padx=16, pady=12)

        ttk.Button(actions_frame, text="Open Config Folder", command=self._open_config_folder).pack(
            side=tk.LEFT, padx=8, pady=8
        )
        ttk.Button(actions_frame, text="Open Config File", command=self._open_config_file).pack(
            side=tk.LEFT, padx=8, pady=8
        )
        ttk.Button(actions_frame, text="Open Log File", command=self._open_log_file).pack(
            side=tk.LEFT, padx=8, pady=8
        )

    
    def _create_general_tab(self):
        """Create general settings tab."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="General")
        
        # Mode selection
        mode_frame = ttk.LabelFrame(frame, text="Operation Mode")
        mode_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(mode_frame, text="Mode:", style="Section.TLabel").pack(anchor=tk.W, padx=8, pady=6)
        
        self.mode_var = tk.StringVar(value="auto")
        mode_auto = ttk.Radiobutton(mode_frame, text="Auto Mode - Automatically organize files", 
                                    variable=self.mode_var, value="auto")
        mode_auto.pack(anchor=tk.W, padx=20, pady=5)
        
        mode_hitl = ttk.Radiobutton(mode_frame, text="HITL Mode - Request approval before organizing", 
                                    variable=self.mode_var, value="hitl")
        mode_hitl.pack(anchor=tk.W, padx=20, pady=5)
        
        ttk.Label(
            mode_frame,
            text="In HITL mode, files are analyzed and queued for approval.",
            style="Muted.TLabel"
        ).pack(anchor=tk.W, padx=20, pady=6)
    
    def _create_folders_tab(self):
        """Create watched folders tab."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Watched Folders")
        
        # Instructions
        ttk.Label(frame, text="Add folders to monitor for new files:", style="Muted.TLabel").pack(anchor=tk.W, padx=16, pady=10)
        
        # Listbox with scrollbar
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.folders_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, height=10)
        self.folders_listbox.configure(
            bg="#FFFFFF",
            fg="#111827",
            highlightthickness=1,
            highlightbackground="#E5E7EB",
            selectbackground="#DCE6FF",
            selectforeground="#111827",
        )
        self.folders_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.folders_listbox.yview)
        
        # Folder options frame
        options_frame = ttk.LabelFrame(frame, text="Folder Options")
        options_frame.pack(fill=tk.X, padx=16, pady=8)
        
        self.folder_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Enabled", variable=self.folder_enabled_var).pack(side=tk.LEFT, padx=5)
        
        self.folder_recursive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Recursive (watch subfolders)", variable=self.folder_recursive_var).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, padx=16, pady=10)
        
        ttk.Button(button_frame, text="Add Folder", command=self._add_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Remove Selected", command=self._remove_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Browse...", command=self._browse_folder).pack(side=tk.LEFT, padx=5)
        
        self.folders_data = []
    
    def _create_ai_tab(self):
        """Create AI settings tab."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="AI Settings")
        
        # Provider selection
        provider_frame = ttk.LabelFrame(frame, text="AI Provider")
        provider_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(provider_frame, text="Provider:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.ai_provider_var = tk.StringVar(value="openai")
        provider_combo = ttk.Combobox(provider_frame, textvariable=self.ai_provider_var, 
                                      values=["openai", "anthropic", "ollama"], state="readonly", width=30)
        provider_combo.grid(row=0, column=1, padx=5, pady=5)
        provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        
        # API Key
        self.api_key_frame = ttk.LabelFrame(frame, text="API Configuration")
        self.api_key_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(self.api_key_frame, text="API Key:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.api_key_var = tk.StringVar()
        api_key_entry = ttk.Entry(self.api_key_frame, textvariable=self.api_key_var, width=50, show="*")
        api_key_entry.grid(row=0, column=1, padx=5, pady=5)
        
        # Base URL (for Ollama)
        self.base_url_frame = ttk.LabelFrame(frame, text="Base URL (for local providers)")
        self.base_url_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(self.base_url_frame, text="Base URL:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.base_url_var = tk.StringVar(value="http://localhost:11434/v1")
        ttk.Entry(self.base_url_frame, textvariable=self.base_url_var, width=50).grid(row=0, column=1, padx=5, pady=5)
        self.base_url_frame.pack_forget()  # Hide by default
        
        # Model
        model_frame = ttk.LabelFrame(frame, text="Model")
        model_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(model_frame, text="Model:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.ai_model_var = tk.StringVar(value="gpt-4")
        ttk.Entry(model_frame, textvariable=self.ai_model_var, width=50).grid(row=0, column=1, padx=5, pady=5)
        
        # Temperature
        temp_frame = ttk.LabelFrame(frame, text="Temperature")
        temp_frame.pack(fill=tk.X, padx=16, pady=12)
        
        self.temperature_var = tk.DoubleVar(value=0.3)
        temp_scale = ttk.Scale(temp_frame, from_=0.0, to=1.0, variable=self.temperature_var, orient=tk.HORIZONTAL)
        temp_scale.grid(row=0, column=0, padx=5, pady=5, sticky=tk.EW)
        temp_frame.columnconfigure(0, weight=1)
        
        self.temp_label = ttk.Label(temp_frame, text="0.3")
        self.temp_label.grid(row=0, column=1, padx=5, pady=5)
        temp_scale.configure(command=lambda v: self.temp_label.config(text=f"{float(v):.1f}"))
    
    def _create_archive_tab(self):
        """Create archive settings tab."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Archive Settings")
        
        # Archive path
        path_frame = ttk.LabelFrame(frame, text="Archive Location")
        path_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(path_frame, text="Base Path:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.archive_path_var = tk.StringVar()
        path_entry = ttk.Entry(path_frame, textvariable=self.archive_path_var, width=50)
        path_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(path_frame, text="Browse...", command=self._browse_archive_path).grid(row=0, column=2, padx=5, pady=5)
        
        # Options
        options_frame = ttk.LabelFrame(frame, text="Organization Options")
        options_frame.pack(fill=tk.X, padx=16, pady=12)
        
        self.create_date_folders_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Create date folders (YYYY-MM)", 
                       variable=self.create_date_folders_var).pack(anchor=tk.W, padx=5, pady=5)
        
        self.create_category_folders_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Create category folders", 
                       variable=self.create_category_folders_var).pack(anchor=tk.W, padx=5, pady=5)
        
        self.move_files_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Move files to archive (uncheck to only rename in place)", 
                       variable=self.move_files_var).pack(anchor=tk.W, padx=5, pady=5)
    
    def _create_examples_tab(self):
        """Create few-shot examples tab."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Few-Shot Examples")
        
        # Instructions
        ttk.Label(
            frame,
            text="Add examples to help the AI learn your organization preferences:",
            style="Muted.TLabel"
        ).pack(anchor=tk.W, padx=16, pady=10)
        
        # Listbox
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.examples_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, height=8)
        self.examples_listbox.configure(
            bg="#FFFFFF",
            fg="#111827",
            highlightthickness=1,
            highlightbackground="#E5E7EB",
            selectbackground="#DCE6FF",
            selectforeground="#111827",
        )
        self.examples_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.examples_listbox.yview)
        
        # Example form
        form_frame = ttk.LabelFrame(frame, text="Example Details")
        form_frame.pack(fill=tk.X, padx=16, pady=12)
        
        ttk.Label(form_frame, text="Original Filename:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.example_file_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.example_file_var, width=40).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(form_frame, text="Category:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.example_category_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.example_category_var, width=40).grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(form_frame, text="Suggested Name:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.example_name_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.example_name_var, width=40).grid(row=2, column=1, padx=5, pady=5)
        
        ttk.Label(form_frame, text="Tags (comma-separated):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.example_tags_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.example_tags_var, width=40).grid(row=3, column=1, padx=5, pady=5)
        
        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, padx=16, pady=10)
        
        ttk.Button(button_frame, text="Add Example", command=self._add_example).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Remove Selected", command=self._remove_example).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Form", command=self._clear_example_form).pack(side=tk.LEFT, padx=5)
    
    def _create_pending_tab(self):
        """Create pending actions tab (HITL mode)."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Pending Actions")
        
        # Instructions
        ttk.Label(
            frame,
            text="Pending file organization actions (HITL mode):",
            style="Muted.TLabel"
        ).pack(anchor=tk.W, padx=16, pady=10)
        
        # Treeview for pending actions
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        
        columns = ("File", "Category", "Action", "Destination")
        self.pending_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=15, style="Modern.Treeview")
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
        
        scrollbar_tree = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.pending_tree.yview)
        self.pending_tree.configure(yscrollcommand=scrollbar_tree.set)
        
        self.pending_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tree.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Action buttons
        action_frame = ttk.Frame(frame)
        action_frame.pack(fill=tk.X, padx=16, pady=10)
        
        ttk.Button(action_frame, text="Approve Selected", command=self._approve_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Reject Selected", command=self._reject_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Approve All", command=self._approve_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Refresh", command=self._refresh_pending_actions).pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.pending_status_label = ttk.Label(frame, text="No pending actions", style="Muted.TLabel")
        self.pending_status_label.pack(anchor=tk.W, padx=16, pady=6)
    
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
        # Don't set API key in UI for security (will be preserved when saving)
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

    def _apply_theme(self):
        """Apply a modern, neutral theme to the UI."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#F7F8FB"
        surface = "#FFFFFF"
        text = "#111827"
        muted = "#6B7280"
        accent = "#4F46E5"
        accent_hover = "#4338CA"
        border = "#E5E7EB"

        self.root.configure(background=bg)

        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(size=11)
        heading_font = tkfont.Font(family=default_font.actual("family"), size=16, weight="bold")
        subtitle_font = tkfont.Font(family=default_font.actual("family"), size=10)
        section_font = tkfont.Font(family=default_font.actual("family"), size=11, weight="bold")

        style.configure("TFrame", background=bg)
        style.configure("Header.TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("Title.TLabel", background=bg, foreground=text, font=heading_font)
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=subtitle_font)
        style.configure("Section.TLabel", background=bg, foreground=text, font=section_font)
        style.configure("Muted.TLabel", background=bg, foreground=muted)

        style.configure("TLabelframe", background=bg, foreground=text)
        style.configure("TLabelframe.Label", background=bg, foreground=muted, font=subtitle_font)

        style.configure("TButton", padding=(12, 6))
        style.configure("Primary.TButton", background=accent, foreground="#FFFFFF")
        style.map(
            "Primary.TButton",
            background=[("active", accent_hover), ("pressed", accent_hover)],
        )

        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=bg,
            foreground=muted,
            padding=(12, 8),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", surface)],
            foreground=[("selected", text)],
        )

        style.configure(
            "Modern.Treeview",
            background=surface,
            fieldbackground=surface,
            foreground=text,
            rowheight=26,
            bordercolor=border,
            borderwidth=1,
        )
        style.map("Modern.Treeview", background=[("selected", "#DCE6FF")])

    def _update_overview(self):
        """Update overview and status bar."""
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

        if hasattr(self, "status_label"):
            self.status_label.config(
                text=f"Config: {config_path}  |  Mode: {mode}  |  Provider: {provider}  |  Model: {model}  |  v{__version__}"
            )

    def _open_path(self, path: Path):
        """Open a file or folder in the OS file manager."""
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
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
            self.api_key_frame.pack_forget()
            self.base_url_frame.pack(fill=tk.X, padx=10, pady=10)
        else:
            self.base_url_frame.pack_forget()
            self.api_key_frame.pack(fill=tk.X, padx=10, pady=10)
    
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
            # Update selected item or add new
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
                self.pending_status_label.config(text=f"{count} pending action(s)", foreground="blue")
            else:
                self.pending_status_label.config(text="No pending actions", foreground="gray")
        except Exception as e:
            logger.error(f"Error refreshing pending actions: {e}")
    
    def _auto_refresh_pending(self):
        """Auto-refresh pending actions (called periodically)."""
        if self.config.mode == "hitl":
            self._refresh_pending_actions()
            self.root.after(5000, self._auto_refresh_pending)  # Schedule next refresh
    
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
                # Execute the action
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

