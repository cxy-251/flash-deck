let localDocsList = [];

let currentDocFilter = 'all';

// ================= 技术文档 (Docs Explorer - 资源管理器式分层浏览) =================
let currentDocsSubDir = '';

let currentDocsExplorerData = null;

let docSearchTimer = null;

function loadDocsLibrary(subDir, q) {
    if (subDir === undefined) subDir = currentDocsSubDir;
    if (q === undefined) {
        const searchInput = document.getElementById('doc-search-input');
        q = (searchInput ? searchInput.value : '').trim();
    }

    fetch(`/api/docs/explorer?dir=${encodeURIComponent(subDir)}&q=${encodeURIComponent(q)}&ext=${currentDocFilter}&t=${Date.now()}`)
        .then(r => r.json())
        .then(data => {
            currentDocsExplorerData = data;
            currentDocsSubDir = data.current_dir || '';

            if (activePrimarySection === 'media' && activeMediaTab === 'docs') {
                const countText = data.is_search ? `${data.total_items} 篇搜索结果` : `${data.total_items} 项 (当前文件夹)`;
                document.getElementById('total-badge').textContent = countText;
                const subStats = document.getElementById('media-sub-stats');
                if (subStats) subStats.textContent = `📁 docs/${currentDocsSubDir ? currentDocsSubDir + '/' : ''} · 共 ${data.total_items} 项`;
            }

            renderDocsBreadcrumbs(data);
            renderDocsExplorerGrid(data);
        })
        .catch(err => {
            console.error('Failed to load docs explorer:', err);
        });
}

function navigateDocsDir(targetPath) {
    const searchInput = document.getElementById('doc-search-input');
    if (searchInput) searchInput.value = '';
    currentDocsSubDir = targetPath || '';
    loadDocsLibrary(currentDocsSubDir, '');
}

function refreshCurrentDocsDir() {
    loadDocsLibrary(currentDocsSubDir);
}

function switchDocFilter(filterExt, btnEl) {
    currentDocFilter = filterExt;
    document.querySelectorAll('#doc-filter-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    loadDocsLibrary(currentDocsSubDir);
}

function onDocSearchInput(val) {
    clearTimeout(docSearchTimer);
    docSearchTimer = setTimeout(() => {
        loadDocsLibrary(currentDocsSubDir, val.trim());
    }, 250);
}

function renderDocsBreadcrumbs(data) {
    const bar = document.getElementById('docs-breadcrumbs-bar');
    if (!bar) return;

    if (data.is_search) {
        bar.innerHTML = `
            <span class="docs-crumb-item" onclick="navigateDocsDir('${escapeAttr(data.current_dir)}')">📁 返回当前目录</span>
            <span class="docs-crumb-sep">/</span>
            <span class="docs-crumb-item active">🔍 "${escapeHtml(data.q)}" 的搜索结果 (${data.total_items} 篇)</span>
        `;
        return;
    }

    const crumbs = data.breadcrumbs || [{ name: '根目录', path: '' }];
    let html = '';
    crumbs.forEach((c, idx) => {
        const isLast = idx === crumbs.length - 1;
        const icon = idx === 0 ? '🏠' : '📁';
        if (isLast) {
            html += `<span class="docs-crumb-item active">${icon} ${escapeHtml(c.name || '根目录')}</span>`;
        } else {
            html += `<span class="docs-crumb-item" onclick="navigateDocsDir('${escapeAttr(c.path)}')">${icon} ${escapeHtml(c.name || '根目录')}</span>`;
            html += `<span class="docs-crumb-sep">/</span>`;
        }
    });
    bar.innerHTML = html;
}

function renderDocsExplorerGrid(data) {
    const grid = document.getElementById('docs-explorer-grid');
    const emptyEl = document.getElementById('docs-shelf-empty');
    if (!grid) return;
    grid.innerHTML = '';

    const folders = data.folders || [];
    const files = data.files || [];

    if (folders.length === 0 && files.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    // 1. 如果不在根目录且不是搜索模式，显示“返回上一级”卡片
    if (data.current_dir && !data.is_search) {
        const upCard = document.createElement('div');
        upCard.className = 'docs-folder-card';
        upCard.style.borderColor = '#1f6feb66';
        upCard.onclick = () => navigateDocsDir(data.parent_dir || '');
        upCard.innerHTML = `
            <div class="docs-folder-icon" style="color:#58a6ff;">⬆️</div>
            <div class="docs-folder-info">
                <div class="docs-folder-title" style="color:#58a6ff;">.. (返回上一级目录)</div>
                <div class="docs-folder-meta">
                    <span>点击返回上层</span>
                </div>
            </div>
        `;
        grid.appendChild(upCard);
    }

    // 2. 渲染文件夹列表 (📁)
    folders.forEach(folder => {
        const card = document.createElement('div');
        card.className = 'docs-folder-card';
        card.onclick = () => navigateDocsDir(folder.path);

        card.innerHTML = `
            <div class="docs-folder-icon">📁</div>
            <div class="docs-folder-info">
                <div class="docs-folder-title" title="${escapeAttr(folder.name)}">${escapeHtml(folder.name)}</div>
                <div class="docs-folder-meta">
                    <span style="color:#58a6ff;background:#1f6feb22;padding:1px 6px;border-radius:4px;font-size:11px;">${folder.items_count} 项</span>
                    <span>${folder.mtime}</span>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });

    // 3. 渲染文档文件列表 (📄)
    files.forEach(file => {
        const card = document.createElement('div');
        card.className = 'docs-file-card';
        card.onclick = () => openNovelReader(file.rel_path);

        const ext = (file.ext || '').toLowerCase();
        const extClass = ext === 'rst' ? 'novel-badge-rst' : (ext === 'md' ? 'novel-badge-md' : 'novel-badge-txt');
        const pathHint = (data.is_search && file.dir_rel) ? `<div class="docs-file-path-hint" title="${escapeAttr(file.dir_rel)}">📂 ${escapeHtml(file.dir_rel)}</div>` : '';

        card.innerHTML = `
            <div>
                <div class="docs-file-top">
                    <span class="novel-badge ${extClass}">${ext.toUpperCase()}</span>
                    <button class="manga-mini-btn" title="移至回收站" onclick="event.stopPropagation(); deleteDocFile('${escapeAttr(file.rel_path)}')">🗑️</button>
                </div>
                <div class="docs-file-title" title="${escapeAttr(file.title)}">${escapeHtml(file.title)}</div>
                ${pathHint}
            </div>
            <div class="docs-file-meta">
                <span>${file.size_kb} KB</span>
                <span>${file.mtime}</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

function deleteDocFile(relPath) {
    if (!confirm(`确定将技术文档《${relPath}》移至回收站吗？`)) return;
    fetch('/api/novels/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: relPath })
    }).then(r => r.json()).then(() => {
        loadDocsLibrary();
    });
}

Omni.register('docs', {
    activate() {
        const subStats = document.getElementById('media-sub-stats');
        document.getElementById('total-badge').textContent = '技术文档';
        if (subStats) subStats.textContent = '正在读取技术文档库...';
        loadDocsLibrary();
    },
});
