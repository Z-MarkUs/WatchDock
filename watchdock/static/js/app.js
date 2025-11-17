// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;
        
        // Update buttons
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        // Update content
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(tabName).classList.add('active');
    });
});

// Temperature slider
const tempSlider = document.getElementById('temperature');
const tempValue = document.getElementById('temperature-value');
if (tempSlider && tempValue) {
    tempSlider.addEventListener('input', (e) => {
        tempValue.textContent = e.target.value;
    });
}

// Load configuration on page load
loadConfig();

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();
        
        if (data.success) {
            const config = data.config;
            
            // Load watched folders
            loadFolders(config.watched_folders || []);
            
            // Load AI config
            document.getElementById('ai-provider').value = config.ai_config.provider || 'openai';
            document.getElementById('ai-model').value = config.ai_config.model || 'gpt-4';
            document.getElementById('base-url').value = config.ai_config.base_url || '';
            document.getElementById('temperature').value = config.ai_config.temperature || 0.3;
            tempValue.textContent = config.ai_config.temperature || 0.3;
            updateAIProvider();
            
            // Load archive config
            document.getElementById('archive-path').value = config.archive_config.base_path || '';
            document.getElementById('create-date-folders').checked = config.archive_config.create_date_folders !== false;
            document.getElementById('create-category-folders').checked = config.archive_config.create_category_folders !== false;
            document.getElementById('move-files').checked = config.archive_config.move_files !== false;
            
            // Load few-shot examples
            loadExamples();
        }
    } catch (error) {
        showStatus('Error loading configuration: ' + error.message, 'error');
    }
}

function loadFolders(folders) {
    const container = document.getElementById('folders-list');
    container.innerHTML = '';
    
    folders.forEach((folder, index) => {
        const div = document.createElement('div');
        div.className = 'folder-item';
        div.innerHTML = `
            <div class="folder-item-header">
                <input type="text" value="${folder.path}" placeholder="/path/to/folder" data-index="${index}">
                <button class="btn btn-danger" onclick="removeFolder(${index})">Remove</button>
            </div>
            <div class="folder-item-options">
                <label>
                    <input type="checkbox" ${folder.enabled !== false ? 'checked' : ''} data-index="${index}" data-option="enabled">
                    Enabled
                </label>
                <label>
                    <input type="checkbox" ${folder.recursive ? 'checked' : ''} data-index="${index}" data-option="recursive">
                    Recursive
                </label>
            </div>
        `;
        container.appendChild(div);
    });
}

function addFolder() {
    const folders = getFolders();
    folders.push({
        path: '',
        enabled: true,
        recursive: false,
        file_extensions: null
    });
    loadFolders(folders);
}

function removeFolder(index) {
    const folders = getFolders();
    folders.splice(index, 1);
    loadFolders(folders);
}

function getFolders() {
    const items = document.querySelectorAll('.folder-item');
    const folders = [];
    
    items.forEach((item, index) => {
        const pathInput = item.querySelector('input[type="text"]');
        const enabledCheck = item.querySelector('input[data-option="enabled"]');
        const recursiveCheck = item.querySelector('input[data-option="recursive"]');
        
        folders.push({
            path: pathInput.value,
            enabled: enabledCheck ? enabledCheck.checked : true,
            recursive: recursiveCheck ? recursiveCheck.checked : false,
            file_extensions: null
        });
    });
    
    return folders;
}

function updateAIProvider() {
    const provider = document.getElementById('ai-provider').value;
    const apiKeyGroup = document.getElementById('api-key-group');
    const baseUrlGroup = document.getElementById('base-url-group');
    
    if (provider === 'ollama') {
        apiKeyGroup.style.display = 'none';
        baseUrlGroup.style.display = 'block';
    } else {
        apiKeyGroup.style.display = 'block';
        baseUrlGroup.style.display = 'none';
    }
}

async function loadExamples() {
    try {
        const response = await fetch('/api/few-shot-examples');
        const data = await response.json();
        
        if (data.success) {
            const container = document.getElementById('examples-list');
            container.innerHTML = '';
            
            data.examples.forEach((example, index) => {
                addExampleToDOM(example, index);
            });
        }
    } catch (error) {
        console.error('Error loading examples:', error);
    }
}

function addExample() {
    const container = document.getElementById('examples-list');
    const index = container.children.length;
    addExampleToDOM({
        file_name: '',
        category: '',
        suggested_name: '',
        tags: [],
        description: ''
    }, index);
}

function addExampleToDOM(example, index) {
    const container = document.getElementById('examples-list');
    const div = document.createElement('div');
    div.className = 'example-item';
    div.innerHTML = `
        <div class="example-item-header">
            <input type="text" value="${example.file_name || ''}" placeholder="Original filename" data-index="${index}" data-field="file_name">
            <button class="btn btn-danger" onclick="removeExample(${index})">Remove</button>
        </div>
        <div class="form-group">
            <label>Category</label>
            <input type="text" value="${example.category || ''}" placeholder="e.g., Documents, Images" data-index="${index}" data-field="category">
        </div>
        <div class="form-group">
            <label>Suggested Name</label>
            <input type="text" value="${example.suggested_name || ''}" placeholder="Clean filename" data-index="${index}" data-field="suggested_name">
        </div>
        <div class="form-group">
            <label>Tags (comma-separated)</label>
            <input type="text" value="${example.tags ? example.tags.join(', ') : ''}" placeholder="tag1, tag2, tag3" data-index="${index}" data-field="tags">
        </div>
        <div class="form-group">
            <label>Description</label>
            <input type="text" value="${example.description || ''}" placeholder="Brief description" data-index="${index}" data-field="description">
        </div>
    `;
    container.appendChild(div);
}

function removeExample(index) {
    const container = document.getElementById('examples-list');
    const items = Array.from(container.children);
    if (items[index]) {
        items[index].remove();
        // Re-index remaining items
        Array.from(container.children).forEach((item, i) => {
            item.querySelectorAll('[data-index]').forEach(el => {
                el.dataset.index = i;
            });
            item.querySelector('button').setAttribute('onclick', `removeExample(${i})`);
        });
    }
}

function getExamples() {
    const items = document.querySelectorAll('.example-item');
    const examples = [];
    
    items.forEach((item) => {
        const file_name = item.querySelector('[data-field="file_name"]').value;
        const category = item.querySelector('[data-field="category"]').value;
        const suggested_name = item.querySelector('[data-field="suggested_name"]').value;
        const tagsStr = item.querySelector('[data-field="tags"]').value;
        const description = item.querySelector('[data-field="description"]').value;
        
        if (file_name && category && suggested_name) {
            examples.push({
                file_name,
                category,
                suggested_name,
                tags: tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(t => t) : [],
                description
            });
        }
    });
    
    return examples;
}

async function testPath(inputId) {
    const input = document.getElementById(inputId);
    const path = input.value;
    
    if (!path) {
        showStatus('Please enter a path', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/test-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        
        const data = await response.json();
        
        if (data.success) {
            if (data.exists && data.is_directory) {
                showStatus('✓ Path is valid', 'success');
            } else if (data.exists) {
                showStatus('Path exists but is not a directory', 'error');
            } else {
                showStatus('Path does not exist (will be created)', 'success');
            }
        }
    } catch (error) {
        showStatus('Error testing path: ' + error.message, 'error');
    }
}

async function saveConfig() {
    try {
        // Collect configuration
        const config = {
            watched_folders: getFolders(),
            ai_config: {
                provider: document.getElementById('ai-provider').value,
                api_key: document.getElementById('api-key').value,
                model: document.getElementById('ai-model').value,
                base_url: document.getElementById('base-url').value,
                temperature: parseFloat(document.getElementById('temperature').value)
            },
            archive_config: {
                base_path: document.getElementById('archive-path').value,
                create_date_folders: document.getElementById('create-date-folders').checked,
                create_category_folders: document.getElementById('create-category-folders').checked,
                move_files: document.getElementById('move-files').checked
            },
            log_level: 'INFO',
            check_interval: 1.0
        };
        
        // Save config
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Save few-shot examples
            const examples = getExamples();
            const examplesResponse = await fetch('/api/few-shot-examples', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ examples })
            });
            
            const examplesData = await examplesResponse.json();
            
            if (examplesData.success) {
                showStatus('Configuration saved successfully!', 'success');
            } else {
                showStatus('Config saved but examples failed: ' + examplesData.error, 'error');
            }
        } else {
            showStatus('Error saving configuration: ' + data.error, 'error');
        }
    } catch (error) {
        showStatus('Error saving configuration: ' + error.message, 'error');
    }
}

function showStatus(message, type) {
    const statusEl = document.getElementById('status-message');
    statusEl.textContent = message;
    statusEl.className = type;
    statusEl.style.display = 'block';
    
    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
}

