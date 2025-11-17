"""
AI processor for understanding file content and generating organization suggestions.
"""

import os
import json
import mimetypes
from pathlib import Path
from typing import Dict, Optional, Any, List
import logging

logger = logging.getLogger(__name__)

FEW_SHOT_EXAMPLES_PATH = str(Path.home() / '.watchdock' / 'few_shot_examples.json')


class AIProcessor:
    """Processes files using AI to understand content and suggest organization."""
    
    def __init__(self, config):
        self.config = config
        self.provider = config.provider
        self._client = None
        self._few_shot_examples = self._load_few_shot_examples()
        self._initialize_client()
    
    def _load_few_shot_examples(self) -> List[Dict]:
        """Load few-shot examples from file."""
        try:
            if os.path.exists(FEW_SHOT_EXAMPLES_PATH):
                with open(FEW_SHOT_EXAMPLES_PATH, 'r') as f:
                    examples = json.load(f)
                    return examples if isinstance(examples, list) else []
        except Exception as e:
            logger.debug(f"Could not load few-shot examples: {e}")
        return []
    
    def _initialize_client(self):
        """Initialize the AI client based on provider."""
        if self.provider == "openai":
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.config.api_key)
            except ImportError:
                logger.error("openai package not installed. Install with: pip install openai")
        elif self.provider == "anthropic":
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.config.api_key)
            except ImportError:
                logger.error("anthropic package not installed. Install with: pip install anthropic")
        elif self.provider == "ollama":
            # Ollama uses OpenAI-compatible API
            try:
                import openai
                self._client = openai.OpenAI(
                    api_key="ollama",  # Not needed but required
                    base_url=self.config.base_url or "http://localhost:11434/v1"
                )
            except ImportError:
                logger.error("openai package not installed for Ollama. Install with: pip install openai")
        else:
            logger.warning(f"Unknown provider: {self.provider}. Using fallback processor.")
            self._client = None
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a file and return organization suggestions.
        
        Returns:
            Dict with keys: category, suggested_name, tags, description
        """
        path = Path(file_path)
        
        # Get basic file info
        file_info = {
            'name': path.name,
            'extension': path.suffix.lower(),
            'size': path.stat().st_size,
            'mime_type': mimetypes.guess_type(str(path))[0] or 'unknown'
        }
        
        # Try to read file content (for text files)
        content_preview = self._read_file_preview(file_path, file_info['mime_type'])
        
        # Use AI to understand and categorize
        if self._client:
            return self._ai_analyze(file_path, file_info, content_preview)
        else:
            return self._fallback_analyze(file_path, file_info, content_preview)
    
    def _read_file_preview(self, file_path: str, mime_type: str, max_chars: int = 5000) -> str:
        """Read a preview of file content for text-based files."""
        if not mime_type or not mime_type.startswith('text/'):
            # Try common text extensions
            text_extensions = {'.txt', '.md', '.py', '.js', '.json', '.xml', '.csv', '.log'}
            if Path(file_path).suffix.lower() not in text_extensions:
                return ""
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(max_chars)
                return content[:max_chars]
        except Exception as e:
            logger.debug(f"Could not read file preview: {e}")
            return ""
    
    def _ai_analyze(self, file_path: str, file_info: Dict, content_preview: str) -> Dict[str, Any]:
        """Use AI to analyze the file."""
        prompt = self._build_analysis_prompt(file_path, file_info, content_preview)
        
        try:
            if self.provider in ["openai", "ollama"]:
                response = self._client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt()},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config.temperature
                )
                result_text = response.choices[0].message.content
            elif self.provider == "anthropic":
                response = self._client.messages.create(
                    model=self.config.model,
                    max_tokens=1000,
                    system=self._get_system_prompt(),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature
                )
                result_text = response.content[0].text
            else:
                return self._fallback_analyze(file_path, file_info, content_preview)
            
            return self._parse_ai_response(result_text, file_info)
        
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return self._fallback_analyze(file_path, file_info, content_preview)
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for AI analysis."""
        prompt = """You are a file organization assistant. Analyze files and suggest:
1. A category (e.g., "Documents", "Images", "Videos", "Code", "Archives", "Spreadsheets", "Presentations")
2. A better filename (clean, descriptive, without special chars except - and _)
3. Tags (comma-separated keywords)
4. A brief description

Respond in JSON format:
{
  "category": "category name",
  "suggested_name": "clean filename with extension",
  "tags": ["tag1", "tag2"],
  "description": "brief description"
}"""
        
        # Add few-shot examples if available
        if self._few_shot_examples:
            prompt += "\n\nHere are some examples of how files should be organized:\n"
            for ex in self._few_shot_examples[:5]:  # Limit to 5 examples
                prompt += f"\nExample:\n"
                prompt += f"  Original: {ex.get('file_name', '')}\n"
                prompt += f"  Category: {ex.get('category', '')}\n"
                prompt += f"  Suggested name: {ex.get('suggested_name', '')}\n"
                if ex.get('tags'):
                    prompt += f"  Tags: {', '.join(ex.get('tags', []))}\n"
                if ex.get('description'):
                    prompt += f"  Description: {ex.get('description', '')}\n"
        
        return prompt
    
    def _build_analysis_prompt(self, file_path: str, file_info: Dict, content_preview: str) -> str:
        """Build the prompt for AI analysis."""
        prompt = f"""Analyze this file and suggest how to organize it:

File name: {file_info['name']}
File extension: {file_info['extension']}
File size: {file_info['size']} bytes
MIME type: {file_info['mime_type']}
"""
        
        if content_preview:
            prompt += f"\nFile content preview:\n{content_preview[:2000]}"
        
        prompt += "\n\nProvide organization suggestions in JSON format."
        return prompt
    
    def _parse_ai_response(self, response_text: str, file_info: Dict) -> Dict[str, Any]:
        """Parse AI response and extract organization info."""
        import json
        import re
        
        # Try to extract JSON from response
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                return {
                    'category': result.get('category', 'Other'),
                    'suggested_name': result.get('suggested_name', file_info['name']),
                    'tags': result.get('tags', []),
                    'description': result.get('description', ''),
                    'confidence': 'high'
                }
            except json.JSONDecodeError:
                pass
        
        # Fallback if JSON parsing fails
        return self._fallback_analyze(None, file_info, "")
    
    def _fallback_analyze(self, file_path: Optional[str], file_info: Dict, content_preview: str) -> Dict[str, Any]:
        """Fallback analysis without AI."""
        ext = file_info['extension']
        name = file_info['name']
        
        # Simple category mapping
        category_map = {
            '.pdf': 'Documents',
            '.doc': 'Documents', '.docx': 'Documents',
            '.txt': 'Documents', '.md': 'Documents',
            '.jpg': 'Images', '.jpeg': 'Images', '.png': 'Images', '.gif': 'Images',
            '.mp4': 'Videos', '.avi': 'Videos', '.mov': 'Videos',
            '.zip': 'Archives', '.tar': 'Archives', '.gz': 'Archives',
            '.xls': 'Spreadsheets', '.xlsx': 'Spreadsheets', '.csv': 'Spreadsheets',
            '.ppt': 'Presentations', '.pptx': 'Presentations',
            '.py': 'Code', '.js': 'Code', '.java': 'Code'
        }
        
        category = category_map.get(ext, 'Other')
        
        # Clean filename
        suggested_name = name.replace(' ', '_').replace('(', '').replace(')', '')
        
        return {
            'category': category,
            'suggested_name': suggested_name,
            'tags': [category.lower(), ext[1:] if ext else 'file'],
            'description': f'{category} file',
            'confidence': 'low'
        }

