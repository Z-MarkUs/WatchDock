"""
Web UI for WatchDock configuration and management.
"""

import os
import json
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from watchdock.config import WatchDockConfig, WatchedFolder, AIConfig, ArchiveConfig

logger = logging.getLogger(__name__)

# Get the directory where this file is located
BASE_DIR = Path(__file__).parent

app = Flask(__name__, 
            template_folder=str(BASE_DIR / 'templates'),
            static_folder=str(BASE_DIR / 'static'))

# Default config path
DEFAULT_CONFIG_PATH = str(Path.home() / '.watchdock' / 'config.json')
FEW_SHOT_EXAMPLES_PATH = str(Path.home() / '.watchdock' / 'few_shot_examples.json')


@app.route('/')
def index():
    """Main UI page."""
    return render_template('index.html')


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration."""
    try:
        if os.path.exists(DEFAULT_CONFIG_PATH):
            config = WatchDockConfig.load(DEFAULT_CONFIG_PATH)
            return jsonify({
                'success': True,
                'config': {
                    'watched_folders': [
                        {
                            'path': wf.path,
                            'enabled': wf.enabled,
                            'recursive': wf.recursive,
                            'file_extensions': wf.file_extensions
                        }
                        for wf in config.watched_folders
                    ],
                    'ai_config': {
                        'provider': config.ai_config.provider,
                        'model': config.ai_config.model,
                        'base_url': config.ai_config.base_url,
                        'temperature': config.ai_config.temperature
                        # Don't send API key for security
                    },
                    'archive_config': {
                        'base_path': config.archive_config.base_path,
                        'create_date_folders': config.archive_config.create_date_folders,
                        'create_category_folders': config.archive_config.create_category_folders,
                        'move_files': config.archive_config.move_files
                    },
                    'log_level': config.log_level,
                    'check_interval': config.check_interval
                }
            })
        else:
            # Return default config
            config = WatchDockConfig.default()
            return jsonify({
                'success': True,
                'config': {
                    'watched_folders': [
                        {
                            'path': wf.path,
                            'enabled': wf.enabled,
                            'recursive': wf.recursive,
                            'file_extensions': wf.file_extensions
                        }
                        for wf in config.watched_folders
                    ],
                    'ai_config': {
                        'provider': config.ai_config.provider,
                        'model': config.ai_config.model,
                        'base_url': config.ai_config.base_url,
                        'temperature': config.ai_config.temperature
                    },
                    'archive_config': {
                        'base_path': config.archive_config.base_path,
                        'create_date_folders': config.archive_config.create_date_folders,
                        'create_category_folders': config.archive_config.create_category_folders,
                        'move_files': config.archive_config.move_files
                    },
                    'log_level': config.log_level,
                    'check_interval': config.check_interval
                },
                'is_default': True
            })
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config', methods=['POST'])
def save_config():
    """Save configuration."""
    try:
        data = request.json
        
        # Load existing config to preserve API key if not provided
        existing_config = None
        if os.path.exists(DEFAULT_CONFIG_PATH):
            existing_config = WatchDockConfig.load(DEFAULT_CONFIG_PATH)
        
        # Build watched folders
        watched_folders = [
            WatchedFolder(
                path=wf['path'],
                enabled=wf.get('enabled', True),
                recursive=wf.get('recursive', False),
                file_extensions=wf.get('file_extensions')
            )
            for wf in data.get('watched_folders', [])
        ]
        
        # Build AI config (preserve API key if not provided)
        ai_data = data.get('ai_config', {})
        api_key = ai_data.get('api_key')
        if not api_key and existing_config:
            api_key = existing_config.ai_config.api_key
        
        ai_config = AIConfig(
            provider=ai_data.get('provider', 'openai'),
            api_key=api_key,
            model=ai_data.get('model', 'gpt-4'),
            base_url=ai_data.get('base_url'),
            temperature=float(ai_data.get('temperature', 0.3))
        )
        
        # Build archive config
        archive_data = data.get('archive_config', {})
        archive_config = ArchiveConfig(
            base_path=archive_data.get('base_path', str(Path.home() / 'Documents' / 'Archive')),
            create_date_folders=archive_data.get('create_date_folders', True),
            create_category_folders=archive_data.get('create_category_folders', True),
            move_files=archive_data.get('move_files', True)
        )
        
        # Create config
        config = WatchDockConfig(
            watched_folders=watched_folders,
            ai_config=ai_config,
            archive_config=archive_config,
            log_level=data.get('log_level', 'INFO'),
            check_interval=float(data.get('check_interval', 1.0))
        )
        
        # Save config
        config_path = Path(DEFAULT_CONFIG_PATH)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config.save(DEFAULT_CONFIG_PATH)
        
        return jsonify({'success': True, 'message': 'Configuration saved successfully'})
    
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/few-shot-examples', methods=['GET'])
def get_few_shot_examples():
    """Get few-shot examples."""
    try:
        if os.path.exists(FEW_SHOT_EXAMPLES_PATH):
            with open(FEW_SHOT_EXAMPLES_PATH, 'r') as f:
                examples = json.load(f)
            return jsonify({'success': True, 'examples': examples})
        else:
            return jsonify({'success': True, 'examples': []})
    except Exception as e:
        logger.error(f"Error loading few-shot examples: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/few-shot-examples', methods=['POST'])
def save_few_shot_examples():
    """Save few-shot examples."""
    try:
        data = request.json
        examples = data.get('examples', [])
        
        # Validate examples structure
        for ex in examples:
            if 'file_name' not in ex or 'category' not in ex or 'suggested_name' not in ex:
                return jsonify({'success': False, 'error': 'Invalid example format'}), 400
        
        # Save examples
        examples_path = Path(FEW_SHOT_EXAMPLES_PATH)
        examples_path.parent.mkdir(parents=True, exist_ok=True)
        with open(FEW_SHOT_EXAMPLES_PATH, 'w') as f:
            json.dump(examples, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Few-shot examples saved successfully'})
    
    except Exception as e:
        logger.error(f"Error saving few-shot examples: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/test-folder', methods=['POST'])
def test_folder():
    """Test if a folder path is valid."""
    try:
        data = request.json
        folder_path = data.get('path', '')
        
        path = Path(folder_path)
        exists = path.exists()
        is_dir = path.is_dir() if exists else False
        
        return jsonify({
            'success': True,
            'exists': exists,
            'is_directory': is_dir,
            'readable': os.access(folder_path, os.R_OK) if exists else False
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def run_ui(host='127.0.0.1', port=5000, debug=False):
    """Run the web UI."""
    print(f"Starting WatchDock UI at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    app.run(host=host, port=port, debug=debug)

