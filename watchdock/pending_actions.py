"""
Pending actions queue for HITL (Human-In-The-Loop) mode.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

PENDING_ACTIONS_PATH = str(Path.home() / '.watchdock' / 'pending_actions.json')


class PendingAction:
    """Represents a pending file organization action."""
    
    def __init__(self, file_path: str, analysis: Dict, proposed_action: Dict, action_id: Optional[str] = None):
        self.action_id = action_id or f"{datetime.now().timestamp()}_{Path(file_path).name}"
        self.file_path = file_path
        self.analysis = analysis
        self.proposed_action = proposed_action
        self.created_at = datetime.now().isoformat()
        self.status = "pending"  # "pending", "approved", "rejected"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'action_id': self.action_id,
            'file_path': self.file_path,
            'analysis': self.analysis,
            'proposed_action': self.proposed_action,
            'created_at': self.created_at,
            'status': self.status
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PendingAction":
        """Create from dictionary."""
        action = cls(
            file_path=data['file_path'],
            analysis=data['analysis'],
            proposed_action=data['proposed_action'],
            action_id=data.get('action_id')
        )
        action.created_at = data.get('created_at', datetime.now().isoformat())
        action.status = data.get('status', 'pending')
        return action


class PendingActionsQueue:
    """Manages the queue of pending actions for HITL mode."""
    
    def __init__(self):
        self.actions: List[PendingAction] = []
        self._load()
    
    def _load(self):
        """Load pending actions from file."""
        try:
            if os.path.exists(PENDING_ACTIONS_PATH):
                with open(PENDING_ACTIONS_PATH, 'r') as f:
                    data = json.load(f)
                    self.actions = [
                        PendingAction.from_dict(item)
                        for item in data.get('actions', [])
                        if item.get('status') == 'pending'  # Only load pending actions
                    ]
        except Exception as e:
            logger.error(f"Error loading pending actions: {e}")
            self.actions = []
    
    def _save(self):
        """Save pending actions to file."""
        try:
            actions_path = Path(PENDING_ACTIONS_PATH)
            actions_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Load existing to preserve history
            existing_actions = []
            if actions_path.exists():
                with open(PENDING_ACTIONS_PATH, 'r') as f:
                    data = json.load(f)
                    existing_actions = data.get('actions', [])
            
            # Update existing actions and add new ones
            action_dicts = {a.action_id: a.to_dict() for a in self.actions}
            for existing in existing_actions:
                action_id = existing.get('action_id')
                if action_id not in action_dicts:
                    action_dicts[action_id] = existing
            
            with open(PENDING_ACTIONS_PATH, 'w') as f:
                json.dump({
                    'actions': list(action_dicts.values()),
                    'updated_at': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving pending actions: {e}")
    
    def add(self, file_path: str, analysis: Dict, proposed_action: Dict) -> PendingAction:
        """Add a new pending action."""
        action = PendingAction(file_path, analysis, proposed_action)
        self.actions.append(action)
        self._save()
        logger.info(f"Added pending action: {action.action_id} for {file_path}")
        return action
    
    def get_pending(self) -> List[PendingAction]:
        """Get all pending actions."""
        return [a for a in self.actions if a.status == 'pending']
    
    def get_by_id(self, action_id: str) -> Optional[PendingAction]:
        """Get action by ID."""
        for action in self.actions:
            if action.action_id == action_id:
                return action
        return None
    
    def approve(self, action_id: str):
        """Mark an action as approved."""
        action = self.get_by_id(action_id)
        if action:
            action.status = 'approved'
            self._save()
            logger.info(f"Approved action: {action_id}")
            return action
        return None
    
    def reject(self, action_id: str):
        """Mark an action as rejected."""
        action = self.get_by_id(action_id)
        if action:
            action.status = 'rejected'
            self._save()
            logger.info(f"Rejected action: {action_id}")
            return action
        return None
    
    def remove(self, action_id: str):
        """Remove an action from the queue."""
        self.actions = [a for a in self.actions if a.action_id != action_id]
        self._save()
    
    def clear_processed(self):
        """Remove all processed (approved/rejected) actions."""
        self.actions = [a for a in self.actions if a.status == 'pending']
        self._save()

