function onNovelSearchInput(val) {
    val = (val || '').trim();
    currentNovelSearchQuery = val;
    // 实时繁简模糊检索本地小说书架，绝不触发联网搜索
    renderNovelsShelf(filterLocalNovels(val));

    if (!val) {
        const onlineSec = document.getElementById('novel-online-section');
        if (onlineSec) onlineSec.style.display = 'none';
    }
}

function onNovelSearchEnter() {
    const input = document.getElementById('novel-search-input');
    const val = (input ? input.value : '').trim();
    if (isRemoteClient) {          // 非本机：只搜本地，回车不触发联网检索
        onNovelSearchInput(val);
        return;
    }
    if (val) {
        executeNovelSearch(val);
    } else {
        const onlineSec = document.getElementById('novel-online-section');
        if (onlineSec) onlineSec.style.display = 'none';
    }
}

let localNovelsList = [];

let currentNovelFilter = 'all';

// ================= 小说画廊 (Novel Gallery - 对接禁漫在线小说与独立小说书架) =================
let currentNovelSearchQuery = '';

let currentNovelPage = 1;

let currentNovelSort = 'mr';

let hasMoreNovelPages = false;

let isLoadingMoreNovels = false;

let currentOnlineNovelResults = [];

let totalOnlineNovelCount = 0;

function onNovelSortChange(val) {
    currentNovelSort = val || 'mr';
    const input = document.getElementById('novel-search-input');
    const valInput = (input ? input.value : '').trim();
    if (valInput) {
        executeUnifiedNovelSearch(valInput);
    }
}

// ================= 小说画廊 (Novel Gallery - 纯净隔离与专业 EPUB 阅读系统) =================
let isNovelNsfw = false;

let novelSearchTimer = null;

let novelOnlineResults = [];

let novelDownloadQueue = [];

let novelTasksPollingTimer = null;

// 检索来源链接（站点地址来自 omni/core/endpoints.py）
function setNovelSourceIndicator(site) {
    const el = document.getElementById('novel-source-indicator');
    if (!el) return;
    el.textContent = Omni.host(site) + ' ↗';
    el.href = Omni.url(site);
    el.title = '点击在浏览器中打开: ' + Omni.url(site);
}

function toggleNovelNsfw() {
    if (!isNovelNsfw && !isNsfwUnlocked) {
        openNsfwModal();
        return;
    }
    isNovelNsfw = !isNovelNsfw;
    const btn = document.getElementById('novel-nsfw-toggle-btn');
    const heading = document.getElementById('novel-shelf-heading');
    const searchInput = document.getElementById('novel-search-input');
    const srcTip = document.getElementById('novel-source-tip');

    if (isNovelNsfw) {
        if (btn) {
            btn.classList.add('active');
            btn.style.background = '#da363333';
            btn.style.borderColor = '#da3633';
            btn.style.color = '#f85149';
            btn.style.fontWeight = '700';
        }
        if (heading) heading.textContent = '🔞 NSFW 杏书私有书架';
        if (searchInput) searchInput.placeholder = '🔍 搜索 xbookcn 小说书名、作者或题材 (回车检索)...';
        setNovelSourceIndicator('xbookcn_blog');
        if (srcTip) {
            srcTip.textContent = '杏书网 / 小书屋精品情色文学 (历史情色/现代都市/长篇巨著/人妻乱伦) · 回车检索';
        }
    } else {
        if (btn) {
            btn.classList.remove('active');
            btn.style.background = '';
            btn.style.borderColor = '';
            btn.style.color = '';
            btn.style.fontWeight = '';
        }
        if (heading) heading.textContent = '📚 本地已收录小说';
        if (searchInput) searchInput.placeholder = '🔍 搜索小说书名、作者或关键词 (回车检索)...';
        setNovelSourceIndicator('gutenberg');
        if (srcTip) {
            srcTip.textContent = '支持书名/作者/分类/题材多维检索 (回车检索)';
        }
    }

    activeNovelCategory = 'all';
    loadNovelsLibrary();
    syncNovelQueue();

    const searchVal = (searchInput ? searchInput.value : '').trim();
    if (searchVal) {
        executeNovelSearch(searchVal);
    } else {
        const onlineSec = document.getElementById('novel-online-section');
        if (onlineSec) onlineSec.style.display = 'none';
    }
}

let activeNovelCategory = 'all';

function renderNovelCategoryBar() {
    const bar = document.getElementById('novel-category-filter-bar');
    if (!bar) return;

    const catCounts = {};
    localNovelsList.forEach(item => {
        const cat = item.category || (isNovelNsfw ? '另类小说' : '公版名著');
        catCounts[cat] = (catCounts[cat] || 0) + 1;
    });

    const preferredCategories = isNovelNsfw ? [
        '精选作品', '现代情色', '日本情色', '西洋情色', '伴侣交换',
        '武侠情色', '奇幻科幻', '家庭乱伦', '性爱调教', '粗野性交',
        '多人群交', '教师学生', '古典情色', '历史情色', '同性情色',
        '都市生活', '乡间记趣', '疯狂暴露', '午夜怪谈', '游戏乐园',
        '医生护士', '奇遇物语', '左邻右舍', '同事之间', '旅游纪事',
        '纯洁恋情', '明星系列', '意外收获', '忘年之乐', '另类其他',
        '知识技巧', '文学评论', '精选长篇典藏'
    ] : [
        '英语进阶', '一生必读100本', '世界名著精选', '中国智慧与谋略', '中国法律法规', '公版名著'
    ];
    const categories = Array.from(new Set([...preferredCategories, ...Object.keys(catCounts)]));
    let html = `<button class="novel-cat-btn ${activeNovelCategory === 'all' ? 'active' : ''}" onclick="setNovelCategoryFilter('all')">🏷️ 全部 (${localNovelsList.length})</button>`;

    categories.forEach(c => {
        const cnt = catCounts[c] || 0;
        if (cnt > 0) {
            html += `<button class="novel-cat-btn ${activeNovelCategory === c ? 'active' : ''}" onclick="setNovelCategoryFilter('${escapeAttr(c)}')">${escapeHtml(c)} (${cnt})</button>`;
        }
    });

    bar.innerHTML = html;
    bar.style.display = 'flex';
}

function setNovelCategoryFilter(cat) {
    activeNovelCategory = cat;
    renderNovelCategoryBar();
    const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
    renderNovelsShelf(filterLocalNovels(searchVal));
}

function loadNovelsLibrary() {
    fetch(`/api/novels/library?nsfw=${isNovelNsfw ? 1 : 0}&t=${Date.now()}`)
        .then(r => r.json())
        .then(list => {
            localNovelsList = list || [];
            if (activePrimarySection === 'media' && activeMediaTab === 'novels') {
                const modeTag = isNovelNsfw ? ' (NSFW)' : '';
                document.getElementById('total-badge').textContent = `${localNovelsList.length} 本已收录小说${modeTag}`;
                const subStats = document.getElementById('media-sub-stats');
                if (subStats) subStats.textContent = `共 ${localNovelsList.length} 本已收录作品${modeTag}`;
            }
            const countEl = document.getElementById('novel-local-count');
            if (countEl) countEl.textContent = `(${localNovelsList.length} 部 · EPUB / TXT)`;

            renderNovelCategoryBar();

            const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
            renderNovelsShelf(filterLocalNovels(searchVal));
        })
        .catch(err => {
            console.error('Failed to load novels library:', err);
        });
}

function filterLocalNovels(query) {
    const q = (query || '').toLowerCase();
    return localNovelsList.filter(item => {
        if (activeNovelCategory !== 'all') {
            if ((item.category || '') !== activeNovelCategory) {
                return false;
            }
        }
        if (!q) return true;
        return (item.title && item.title.toLowerCase().includes(q)) ||
               (item.author && item.author.toLowerCase().includes(q)) ||
               (item.category && item.category.toLowerCase().includes(q)) ||
               (item.rel_path && item.rel_path.toLowerCase().includes(q));
    });
}

let currentNovelsShelfList = [];

let novelShelfRenderIndex = 0;

const NOVEL_SHELF_PAGE_SIZE = 30;

function renderNovelsShelf(list, reset = true) {
    const grid = document.getElementById('novels-shelf-grid');
    const emptyEl = document.getElementById('novels-shelf-empty');
    if (!grid) return;

    if (reset) {
        grid.innerHTML = '';
        currentNovelsShelfList = (list !== undefined && list !== null ? list : localNovelsList) || [];
        novelShelfRenderIndex = 0;
    }

    if (!currentNovelsShelfList || currentNovelsShelfList.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const nextChunk = currentNovelsShelfList.slice(novelShelfRenderIndex, novelShelfRenderIndex + NOVEL_SHELF_PAGE_SIZE);
    nextChunk.forEach(item => {
        const card = document.createElement('div');
        card.className = 'novel-card';
        const safeName = escapeAttr(item.filename || item.rel_path);
        const ext = (item.ext || '').toLowerCase();
        const isEpub = ext === 'epub';
        card.onclick = () => openNovelReader(item.rel_path || item.filename);

        const badgeLabel = isEpub ? 'EPUB' : (ext === 'txt' ? 'TXT' : ext.toUpperCase());
        const badgeClass = isEpub ? 'novel-badge-txt' : (ext === 'md' ? 'novel-badge-md' : 'novel-badge-rst');
        const sizeText = item.size_mb ? `${item.size_mb} MB` : (item.size_kb ? `${item.size_kb} KB` : `${item.char_count || 0} 字`);
        const authorText = item.author && item.author !== '未知作者' ? `✍️ ${escapeHtml(item.author)} · ` : '';
        const catTag = item.category ? `<span class="novel-cat-pill">${escapeHtml(item.category)}</span>` : '';

        card.innerHTML = `
            <div class="novel-card-top">
                <div style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
                    <span style="font-size:15px;line-height:1;">📖</span>
                    <div class="novel-title" title="${safeName}">${escapeHtml(item.title)}</div>
                </div>
                <span class="novel-badge ${badgeClass}" style="flex-shrink:0;">${badgeLabel}</span>
            </div>
            <div class="novel-meta">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:210px;">${catTag}${authorText}💾 ${sizeText}</span>
                <button class="manga-mini-btn" title="移至回收站" style="padding:2px 7px;font-size:12px;" onclick="event.stopPropagation();deleteNovelFile('${escapeAttr(item.rel_path || item.filename)}')">🗑️</button>
            </div>
        `;
        grid.appendChild(card);
    });
    novelShelfRenderIndex += nextChunk.length;
}

function loadMoreNovelsShelf() {
    if (novelShelfRenderIndex < currentNovelsShelfList.length) {
        renderNovelsShelf(null, false);
    }
}

function deleteNovelFile(relPath) {
    const filename = (relPath || '').split('/').pop() || relPath;
    if (!confirm(`确定将小说《${filename}》移至回收站吗？`)) return;
    fetch('/api/novels/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: relPath })
    }).then(r => r.json()).then(res => {
        loadNovelsLibrary();
    }).catch(err => {
        console.error('Failed to delete novel file:', err);
    });
}

function executeNovelSearch(keyword) {
    const onlineSec = document.getElementById('novel-online-section');
    const loadingEl = document.getElementById('novel-online-loading');
    const grid = document.getElementById('novels-online-grid');
    const statsEl = document.getElementById('novel-online-stats');
    const endTip = document.getElementById('novel-online-end-tip');

    if (onlineSec) onlineSec.style.display = 'block';
    if (loadingEl) loadingEl.style.display = 'block';
    if (grid) grid.innerHTML = '';
    if (endTip) endTip.style.display = 'none';

    fetch(`/api/novels/search?nsfw=${isNovelNsfw ? 1 : 0}&q=${encodeURIComponent(keyword)}&t=${Date.now()}`)
        .then(r => r.json())
        .then(results => {
            if (loadingEl) loadingEl.style.display = 'none';
            novelOnlineResults = results || [];
            if (statsEl) statsEl.textContent = `(共 ${novelOnlineResults.length} 部)`;
            renderNovelOnlineResults(novelOnlineResults);
            if (endTip) endTip.style.display = novelOnlineResults.length > 0 ? 'block' : 'none';
        })
        .catch(err => {
            if (loadingEl) loadingEl.style.display = 'none';
            if (grid) grid.innerHTML = `<div style="color:#f85149;padding:20px;grid-column:1/-1;text-align:center;">检索失败: ${err}</div>`;
        });
}

function isNovelInQueue(id) {
    return novelDownloadQueue.some(item => String(item.id) === String(id));
}

function toggleNovelQueueItem(id, btnEl) {
    id = String(id);
    const item = novelOnlineResults.find(b => String(b.id) === id);
    if (!item) return;

    const inQueue = isNovelInQueue(id);
    if (inQueue) {
        novelDownloadQueue = novelDownloadQueue.filter(b => String(b.id) !== id);
        fetch('/api/novels/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'remove',
                id: id,
                is_nsfw: isNovelNsfw
            })
        }).catch(e => console.error(e));
        updateNovelQueueUI(id, false, btnEl);
    } else {
        fetch('/api/novels/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'add',
                novel: {
                    id: id,
                    title: item.title,
                    author: item.author,
                    intro: item.intro,
                    cover_url: item.cover_url,
                    is_nsfw: isNovelNsfw
                },
                is_nsfw: isNovelNsfw
            })
        }).then(() => {
            novelDownloadQueue.push({
                id: id,
                title: item.title,
                author: item.author,
                intro: item.intro,
                cover_url: item.cover_url,
                is_nsfw: isNovelNsfw
            });
            updateNovelQueueUI(id, true, btnEl);
        });
    }
}

function updateNovelQueueUI(id, inQueue, btnEl) {
    const badgeCount = document.getElementById('novel-queue-badge-count');
    const modalBadge = document.getElementById('novel-queue-modal-badge');
    const btnCount = document.getElementById('novel-queue-btn-count');
    if (badgeCount) badgeCount.textContent = novelDownloadQueue.length;
    if (modalBadge) modalBadge.textContent = `(共 ${novelDownloadQueue.length} 部)`;
    if (btnCount) btnCount.textContent = novelDownloadQueue.length;

    const targetBtn = btnEl || document.getElementById(`novel-queue-btn-${id}`);
    if (targetBtn) {
        targetBtn.className = `manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}`;
        targetBtn.textContent = inQueue ? '✓' : '➕';
    }
    renderNovelQueueModal();
}

function renderNovelOnlineResults(results) {
    const grid = document.getElementById('novels-online-grid');
    if (!grid) return;
    grid.innerHTML = '';

    if (!results || results.length === 0) {
        grid.innerHTML = `<div style="color:#8b949e;padding:30px;grid-column:1/-1;text-align:center;">未找到匹配作品，请更换书名、作者或关键词重试</div>`;
        return;
    }

    const localTitleSet = new Set(localNovelsList.map(b => b.title.replace(/\.[^/.]+$/, '').trim()));

    results.forEach(item => {
        const card = document.createElement('div');
        card.className = 'novel-card';
        const isLocal = localTitleSet.has(item.title.trim()) || localNovelsList.some(b => b.title.includes(item.title) || item.title.includes(b.title));
        const inQueue = isNovelInQueue(item.id);
        const sourceUrl = item.source_url || (item.id && String(item.id).includes('classic_') ? Omni.url('gutenberg', 'ebooks', String(item.id).replace('classic_', '')) : Omni.url('gutenberg'));
        const sourceDisplay = Omni.host('gutenberg');

        const actionHtml = isLocal
            ? `<button class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;" onclick="event.stopPropagation();openNovelReader('${escapeAttr(item.title)}')">📖 已收录</button>`
            : `<button id="novel-queue-btn-${escapeAttr(item.id)}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="font-size:11px;padding:3px 6px;" onclick="event.stopPropagation();toggleNovelQueueItem('${escapeAttr(item.id)}', this)">${inQueue ? '✓' : '➕'}</button>
               <button id="novel-dl-btn-${escapeAttr(item.id)}" class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;" onclick="event.stopPropagation();downloadSingleNovelById('${escapeAttr(item.id)}', this)">📥 下载</button>`;

        card.onclick = () => {
            if (isLocal) openNovelReader(item.title);
        };

        card.innerHTML = `
            <div class="novel-card-top">
                <div style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
                    <span style="font-size:15px;line-height:1;">📚</span>
                    <div class="novel-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                </div>
                <span class="novel-badge novel-badge-txt" style="flex-shrink:0;">${escapeHtml(item.category || '公版典藏')}</span>
            </div>
            <div class="novel-meta" style="display:flex;justify-content:space-between;align-items:center;">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;font-size:12px;color:#8b949e;">✍️ ${escapeHtml(item.author || '佚名')}</span>
                <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;" onclick="event.stopPropagation()">
                    ${actionHtml}
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

function downloadSingleNovelById(id, btnEl) {
    const item = novelOnlineResults.find(b => b.id === id);
    if (!item) return;
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳ 正在下载...';
    }
    downloadSingleNovel(item.id, item.title, item.author, item.intro, item.cover_url);
}

function downloadSingleNovel(id, title, author, intro, coverUrl) {
    fetch('/api/novels/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            id: id,
            title: title,
            author: author,
            intro: intro,
            cover_url: coverUrl,
            is_nsfw: isNovelNsfw
        })
    }).then(r => r.json()).then(res => {
        pollNovelTasks();
    }).catch(err => {
        console.error('下载请求失败:', err);
    });
}

function pollNovelTasks() {
    fetch('/api/novels/tasks?t=' + Date.now())
        .then(r => r.json())
        .then(tasks => {
            renderNovelTasks(tasks);
            const running = (tasks || []).some(t => t.status === 'running');
            if (running) {
                if (!novelTasksPollingTimer) {
                    novelTasksPollingTimer = setInterval(pollNovelTasks, 1500);
                }
            } else {
                if (novelTasksPollingTimer) {
                    clearInterval(novelTasksPollingTimer);
                    novelTasksPollingTimer = null;
                }
                loadNovelsLibrary();
                syncNovelQueue();
            }
        })
        .catch(() => {});
}

function renderNovelTasks(tasks) {
    const container = document.getElementById('novel-tasks-container');
    const card = document.getElementById('novel-tasks-card');
    if (!container || !card) return;

    const runningTasks = (tasks || []).filter(t => t.status === 'running');
    const recentTasks = (tasks || []).filter(t => t.status === 'running' || (t.status === 'completed' && Date.now() - (t.start_time || 0) * 1000 < 4000));

    if (recentTasks.length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';

    // 归一化展示：始终只显示 1 个主进度条，多任务时显示队列数量与当前进度
    const cur = runningTasks[0] || recentTasks[0];
    const queueCount = runningTasks.length;

    card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <div style="font-size:13px;font-weight:600;color:#f0f6fc;display:flex;align-items:center;gap:6px;">
                <span>📥 正在打包 EPUB: </span>
                <span style="color:#58a6ff;">《${escapeHtml(cur.title)}》</span>
                ${queueCount > 1 ? `<span style="font-size:11px;background:#21262d;color:#8b949e;padding:1px 6px;border-radius:4px;">剩余 ${queueCount - 1} 部排队</span>` : ''}
            </div>
            <div style="font-size:12px;color:#58a6ff;font-weight:700;">${cur.progress || 0}%</div>
        </div>
        <div style="width:100%;height:6px;background:#21262d;border-radius:3px;overflow:hidden;margin-bottom:6px;">
            <div style="width:${cur.progress || 0}%;height:100%;background:#238636;transition:width 0.3s ease;"></div>
        </div>
        <div style="font-size:11px;color:#8b949e;display:flex;justify-content:space-between;">
            <span>${escapeHtml(cur.msg || '处理中...')}</span>
            ${queueCount > 1 ? `<span style="color:#7d8590;">总任务数: ${queueCount}</span>` : ''}
        </div>
    `;
}

// --- 小说待下载列表模态弹窗管理 ---
function syncNovelQueue() {
    fetch(`/api/novels/queue?nsfw=${isNovelNsfw ? 1 : 0}&t=` + Date.now())
        .then(r => r.json())
        .then(q => {
            novelDownloadQueue = q || [];
            const badgeCount = document.getElementById('novel-queue-badge-count');
            const modalBadge = document.getElementById('novel-queue-modal-badge');
            const btnCount = document.getElementById('novel-queue-btn-count');
            if (badgeCount) badgeCount.textContent = novelDownloadQueue.length;
            if (modalBadge) modalBadge.textContent = `(共 ${novelDownloadQueue.length} 部)`;
            if (btnCount) btnCount.textContent = novelDownloadQueue.length;
            renderNovelQueueModal();
        }).catch(() => {});
}

function openNovelQueueModal() {
    syncNovelQueue();
    const modal = document.getElementById('novel-download-queue-modal');
    if (modal) modal.style.display = 'flex';
}

function closeNovelQueueModal() {
    const modal = document.getElementById('novel-download-queue-modal');
    if (modal) modal.style.display = 'none';
}

function removeNovelFromQueue(id) {
    fetch('/api/novels/queue/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, is_nsfw: isNovelNsfw })
    }).then(() => {
        novelDownloadQueue = novelDownloadQueue.filter(x => String(x.id) !== String(id));
        syncNovelQueue();
        const cardBtn = document.getElementById(`novel-queue-btn-${id}`);
        if (cardBtn) {
            cardBtn.className = 'manga-btn';
            cardBtn.textContent = '➕ 加入待下载列表';
        }
    });
}

function clearNovelDownloadQueue() {
    fetch('/api/novels/queue/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_nsfw: isNovelNsfw })
    }).then(() => {
        novelDownloadQueue = [];
        syncNovelQueue();
        document.querySelectorAll('#novels-online-grid .manga-btn-in-queue').forEach(btn => {
            btn.className = 'manga-btn';
            btn.textContent = '➕ 加入待下载列表';
        });
    });
}

function renderNovelQueueModal() {
    const listEl = document.getElementById('novel-queue-items-list');
    const emptyEl = document.getElementById('novel-queue-empty-msg');
    const startBtn = document.getElementById('novel-queue-start-download-btn');
    const clearBtn = document.getElementById('novel-queue-clear-btn');
    if (!listEl) return;

    if (novelDownloadQueue.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        if (startBtn) startBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;
        listEl.innerHTML = '';
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';
    if (startBtn) startBtn.disabled = false;
    if (clearBtn) clearBtn.disabled = false;

    listEl.innerHTML = novelDownloadQueue.map(item => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#161b22;border:1px solid #30363d;border-radius:8px;">
            <div>
                <div style="font-size:14px;font-weight:600;color:#f0f6fc;">${escapeHtml(item.title)}</div>
                <div style="font-size:12px;color:#8b949e;margin-top:2px;">${escapeHtml(item.author || '佚名')}${item.is_nsfw ? ' · 🔞 NSFW' : ''}</div>
            </div>
            <button class="manga-mini-btn" title="移出待下载列表" onclick="removeNovelFromQueue('${escapeAttr(item.id)}')">✕</button>
        </div>
    `).join('');
}

function startNovelQueueBatchDownload() {
    if (novelDownloadQueue.length === 0) return;
    novelDownloadQueue.forEach(item => {
        fetch('/api/novels/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: item.id,
                title: item.title,
                author: item.author,
                intro: item.intro,
                cover_url: item.cover_url,
                is_nsfw: item.is_nsfw !== undefined ? item.is_nsfw : isNovelNsfw
            })
        });
    });
    closeNovelQueueModal();
    pollNovelTasks();
}

Omni.register('novels', {
    activate() {
        setNovelSourceIndicator(isNovelNsfw ? 'xbookcn_blog' : 'gutenberg');
        const subStats = document.getElementById('media-sub-stats');
        const count = localNovelsList && localNovelsList.length > 0 ? localNovelsList.length : null;
        if (count !== null) {
            document.getElementById('total-badge').textContent = count + ' 本小说';
            if (subStats) subStats.textContent = '共 ' + count + ' 本已收录小说';
            renderNovelCategoryBar();
            const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
            renderNovelsShelf(filterLocalNovels(searchVal));
        } else {
            document.getElementById('total-badge').textContent = '小说画廊';
            if (subStats) subStats.textContent = '正在读取本地小说书库...';
            loadNovelsLibrary();
        }
    },
    onScrollEnd() { loadMoreNovelsShelf(); },
    onUnlock() { loadNovelsLibrary(); },
    onLibraryChanged() { localNovelsList = []; },
    prewarm() {
        if (!localNovelsList || localNovelsList.length === 0) {
                fetch(`/api/novels/library?nsfw=${isNovelNsfw ? 1 : 0}&t=${Date.now()}`)
                    .then(r => r.json())
                    .then(list => {
                        localNovelsList = list || [];
                        const countEl = document.getElementById('novel-local-count');
                        if (countEl) countEl.textContent = `(${localNovelsList.length} 部 · EPUB / TXT)`;
                        if (activePrimarySection === 'media' && activeMediaTab === 'novels') {
                            document.getElementById('total-badge').textContent = localNovelsList.length + ' 本小说';
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = '共 ' + localNovelsList.length + ' 本已收录小说';
                            renderNovelCategoryBar();
                            const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
                            renderNovelsShelf(filterLocalNovels(searchVal));
                        }
                    })
                    .catch(() => {});
            }
    },
});
