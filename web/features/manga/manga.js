let localMangaList = [];

let onlineMangaResults = [];

let currentReaderCbz = '';

let activeMangaSubView = 'shelf'; // 'shelf' 或 'online'

let mangaTasksPollingTimer = null;

let currentModalAlbumDetail = null;

function filterLocalManga(query) {
    if (!query) return localMangaList;
    const normQ = normalizeZh(query.trim());
    return localMangaList.filter(item => {
        const normTitle = normalizeZh(item.title || item.filename || '');
        const normAuthor = normalizeZh(item.author || '');
        const normTags = Array.isArray(item.tags) ? item.tags.map(t => normalizeZh(t)).join(' ') : normalizeZh(item.tags || '');
        const normId = item.id ? String(item.id).toLowerCase() : '';
        const normFile = normalizeZh(item.filename || '');
        return normTitle.includes(normQ) || normAuthor.includes(normQ) || normTags.includes(normQ) || normId.includes(normQ) || normFile.includes(normQ);
    });
}

function onMangaSearchInput(val) {
    val = (val || '').trim();
    currentMangaSearchQuery = val;

    const localSection = document.getElementById('manga-local-section');
    const rankingSection = document.getElementById('manga-ranking-section');
    const onlineSec = document.getElementById('manga-online-section');

    if (!val) {
        clearMangaSearch();
        return;
    }

    // 搜索时确保展示本地书架并隐藏榜单与在线区
    if (rankingSection) rankingSection.style.display = 'none';
    if (localSection) localSection.style.display = 'block';
    if (onlineSec) onlineSec.style.display = 'none';

    // 激活“本地已收录”子标签高亮
    document.querySelectorAll('#manga-sub-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    const shelfTabBtn = document.getElementById('manga-subtab-shelf');
    if (shelfTabBtn) shelfTabBtn.classList.add('active');

    // 实时繁简模糊检索本地漫画书架，绝不触发联网搜索
    let matched = filterLocalManga(val);
    if (activeMangaTag === '__incomplete__') {
        matched = matched.filter(item => item.is_complete === false);
    } else if (activeMangaTag !== 'all') {
        const normTag = normalizeZh(activeMangaTag);
        matched = matched.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
    }
    const localHeading = document.getElementById('manga-local-heading');
    if (localHeading) localHeading.textContent = `🟢 本地已收录 (匹配到 ${matched.length} 部 · 点击封面直接阅读)`;
    renderMangaShelf(matched);
}

function onMangaSearchEnter() {
    const input = document.getElementById('manga-search-input');
    const val = (input ? input.value : '').trim();
    if (isRemoteClient) {          // 非本机：只搜本地，回车不触发联网检索
        onMangaSearchInput(val);
        return;
    }
    if (val) {
        executeUnifiedSearch(val);
    } else {
        clearMangaSearch();
    }
}

let activeMangaTag = 'all';

function renderMangaTagBar() {
    const bar = document.getElementById('manga-tag-filter-bar');
    if (!bar) return;

    if (!localMangaList || localMangaList.length === 0) {
        bar.style.display = 'none';
        return;
    }

    // 统计本地所有已收录漫画的标签分布
    const tagCounts = {};
    localMangaList.forEach(item => {
        const tags = Array.isArray(item.tags) ? item.tags : [];
        tags.forEach(t => {
            const cleanT = String(t).trim();
            if (cleanT) {
                tagCounts[cleanT] = (tagCounts[cleanT] || 0) + 1;
            }
        });
    });

    const sortedTags = Object.entries(tagCounts)
        .sort((a, b) => b[1] - a[1]);

    if (sortedTags.length === 0) {
        bar.style.display = 'none';
        return;
    }

    let html = `<button class="manga-tag-filter-btn ${activeMangaTag === 'all' ? 'active' : ''}" onclick="setMangaTagFilter('all')">🏷️ 全部 (${localMangaList.length})</button>`;

    const incompleteCount = localMangaList.filter(item => item.is_complete === false).length;
    if (incompleteCount > 0) {
        const isIncActive = (activeMangaTag === '__incomplete__');
        html += `<button class="manga-tag-filter-btn ${isIncActive ? 'active' : ''}" style="color:${isIncActive ? '#fff' : '#d29922'};border-color:#d2992288;background:${isIncActive ? '#d29922' : '#161b22'};font-weight:600;" onclick="setMangaTagFilter('__incomplete__')">⚠️ 连载更新/未完 (${incompleteCount})</button>`;
    }

    // 展示出现频次最高的分类标签 (频次 >= 2，最多 40 个分类)
    const visibleTags = sortedTags.filter(([t, count]) => count >= 2).slice(0, 40);
    const tagsToRender = visibleTags.length >= 8 ? visibleTags : sortedTags.slice(0, 25);

    tagsToRender.forEach(([t, count]) => {
        const isActive = (activeMangaTag === t);
        html += `<button class="manga-tag-filter-btn ${isActive ? 'active' : ''}" onclick="setMangaTagFilter('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)} (${count})</button>`;
    });

    bar.innerHTML = html;
    bar.style.display = 'flex';
}

function setMangaTagFilter(tag) {
    activeMangaTag = tag;
    renderMangaTagBar();
    updateMangaIncompleteBanner();

    const searchInput = document.getElementById('manga-search-input');
    const searchVal = (searchInput ? searchInput.value : '').trim();
    let baseList = localMangaList;
    if (searchVal) {
        baseList = filterLocalManga(searchVal);
    }

    if (activeMangaTag === 'all') {
        renderMangaShelf(baseList);
    } else if (activeMangaTag === '__incomplete__') {
        const filtered = baseList.filter(item => item.is_complete === false);
        renderMangaShelf(filtered);
    } else {
        const normTag = normalizeZh(activeMangaTag);
        const filtered = baseList.filter(item => {
            if (!Array.isArray(item.tags)) return false;
            return item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag);
        });
        renderMangaShelf(filtered);
    }
}

function updateMangaIncompleteBanner() {
    const banner = document.getElementById('manga-incomplete-banner');
    if (!banner) return;
    const incompleteList = localMangaList.filter(item => item.is_complete === false);
    const count = incompleteList.length;

    if (activeMangaTag !== '__incomplete__' || count === 0) {
        banner.style.display = 'none';
        banner.innerHTML = '';
        return;
    }

    banner.innerHTML = `
        <div style="background: linear-gradient(135deg, rgba(210,153,34,0.18), rgba(210,153,34,0.06)); border: 1px solid rgba(210,153,34,0.45); border-radius: 10px; padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 24px;">⚠️</span>
                <div>
                    <div style="font-size: 14px; font-weight: 700; color: #f0f6fc;">
                        智能检测到 <span style="color: #d29922; font-weight: 800; font-size: 16px;">${count}</span> 部连载漫画有线上新章节更新
                    </div>
                    <div style="font-size: 12px; color: #8b949e; margin-top: 3px;">
                        增量追更机制：仅下载抓取新增章节并就地注入现有 CBZ，旧章节无需重新下载！
                    </div>
                </div>
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                <button class="manga-btn manga-btn-primary" style="background: #d29922; border-color: #bb8009; color: #fff; font-weight: 600; padding: 6px 14px; font-size: 12px;" onclick="startSupplementAllManga(true)">
                    ⚡ 一键并发补充下载 (${count} 部)
                </button>
                <button class="manga-btn" style="border-color: #d2992288; color: #d29922; padding: 6px 14px; font-size: 12px;" onclick="startSupplementAllManga(false)">
                    📥 逐本顺序补充下载
                </button>
                <button class="manga-btn" style="font-size: 12px; padding: 6px 12px;" onclick="addAllIncompleteToQueue()">
                    ➕ 全部加入待下载列表
                </button>
            </div>
        </div>
    `;
    banner.style.display = 'block';
}

function startSupplementSingleManga(albumId, filename, dir = 'manga', title = '') {
    if (!albumId && filename) {
        const item = localMangaList.find(m => m.filename === filename);
        if (item && item.id) albumId = item.id;
    }
    if (!albumId) {
        alert('未能识别该漫画的线上编号，请尝试在线搜索重下。');
        return;
    }

    fetch('/api/manga/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            album_id: albumId,
            chapter_ids: null,
            pack_cbz: true,
            clean_temp: true,
            dir: dir || 'manga'
        })
    })
    .then(r => r.json())
    .then(res => {
        pollMangaTasks();
        const container = document.getElementById('manga-tasks-container');
        if (container) {
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    })
    .catch(err => {
        alert('启动增量补充下载失败: ' + err);
    });
}

function startSupplementAllManga(concurrent = true) {
    const incompleteItems = localMangaList.filter(item => item.is_complete === false && item.id);
    if (incompleteItems.length === 0) {
        alert('本地目前没有检测到需要补充更新的连载漫画！');
        return;
    }
    const ids = incompleteItems.map(item => item.id);

    fetch('/api/manga/batch_download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            album_ids: ids,
            dir: 'manga',
            pack_cbz: true,
            clean_temp: true,
            concurrency: concurrent ? 3 : 1
        })
    })
    .then(r => r.json())
    .then(res => {
        pollMangaTasks();
        const container = document.getElementById('manga-tasks-container');
        if (container) {
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    })
    .catch(err => {
        alert('启动批量补充下载失败: ' + err);
    });
}

function addAllIncompleteToQueue() {
    const incompleteItems = localMangaList.filter(item => item.is_complete === false && item.id);
    if (incompleteItems.length === 0) {
        alert('本地目前没有检测到需要补充更新的连载漫画！');
        return;
    }
    let addedCount = 0;
    incompleteItems.forEach(item => {
        if (!isMangaInQueue(item.id)) {
            mangaDownloadQueue.push({
                id: String(item.id),
                title: item.title,
                cover_url: item.cover_url || `/api/manga/cover?name=${encodeURIComponent(item.filename)}&dir=${item.dir || 'manga'}`
            });
            addedCount++;
        }
    });
    if (addedCount > 0) {
        saveMangaDownloadQueue();
        renderMangaQueueModalItems();
        alert(`已成功将 ${addedCount} 部待更新的连载漫画加入待下载列表！`);
    } else {
        alert('所有待更新的连载漫画已在待下载列表中。');
    }
}

function loadMangaLibrary() {
    fetch('/api/manga/library?dir=manga&t=' + Date.now())
        .then(r => r.json())
        .then(list => {
            localMangaList = list || [];
            const mangaCountBadge = document.getElementById('manga-local-count');
            if (mangaCountBadge) mangaCountBadge.textContent = `(${localMangaList.length} 部)`;
            if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                document.getElementById('total-badge').textContent = localMangaList.length + ' 部漫画';
                const subStats = document.getElementById('media-sub-stats');
                if (subStats) subStats.textContent = '共 ' + localMangaList.length + ' 部漫画';
            }

            renderMangaTagBar();
            updateMangaIncompleteBanner();

            const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
            if (activeMangaSubTab === 'shelf') {
                let baseList = localMangaList;
                if (searchVal) {
                    baseList = filterLocalManga(searchVal);
                }
                if (activeMangaTag === 'all') {
                    renderMangaShelf(baseList);
                } else {
                    const normTag = normalizeZh(activeMangaTag);
                    const filtered = baseList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
                    renderMangaShelf(filtered);
                }
            } else if (rankingDataCache[activeMangaSubTab]) {
                renderMangaRankingGrid(rankingDataCache[activeMangaSubTab]);
            }
        })
        .catch(err => {
            console.error('Failed to load manga library:', err);
        });
}

let currentMangaShelfList = [];

let mangaShelfRenderIndex = 0;

const MANGA_SHELF_PAGE_SIZE = 36;

function renderMangaShelf(items, reset = true) {
    const grid = document.getElementById('manga-shelf-grid');
    const emptyEl = document.getElementById('manga-shelf-empty');
    if (!grid) return;

    if (reset) {
        grid.innerHTML = '';
        currentMangaShelfList = (items !== undefined && items !== null ? items : localMangaList) || [];
        mangaShelfRenderIndex = 0;
    }

    if (!currentMangaShelfList || currentMangaShelfList.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const nextChunk = currentMangaShelfList.slice(mangaShelfRenderIndex, mangaShelfRenderIndex + MANGA_SHELF_PAGE_SIZE);
    nextChunk.forEach(item => {
        const card = document.createElement('div');
        card.className = 'manga-card';
        card.onclick = () => openMangaReader(item.filename, 'manga');

        const tagsList = Array.isArray(item.tags) ? item.tags : [];
        const tagsHtml = tagsList.length > 0
            ? `<div class="manga-tags-row" onclick="event.stopPropagation()">
                ${tagsList.slice(0, 3).map(t => `<span class="manga-tag-pill" title="按标签筛选: ${escapeAttr(t)}" onclick="filterMangaByTag('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)}</span>`).join('')}
              </div>`
            : '';

        const isInc = (item.is_complete === false);
        const missingCount = isInc ? Math.max(1, (item.online_chapters || 0) - (item.local_chapters || 0)) : 0;
        const completeBadge = isInc
            ? `<span class="manga-badge-cbz" style="background:#d29922dd;color:#fff;" title="部分话数收录 (本地 ${item.local_chapters || '?'}/${item.online_chapters || '?'} 话)">⚠️ ${item.local_chapters || '?'}/${item.online_chapters || '?'}话</span>`
            : `<span class="manga-badge-cbz">单文件 CBZ</span>`;

        const hoverSupplementBtn = isInc
            ? `<button class="manga-mini-btn" style="background:#d29922;color:#fff;border-color:#bb8009;" title="增量补充下载最新章节 (差 ${missingCount} 话)" onclick="startSupplementSingleManga('${escapeAttr(item.id || '')}', '${escapeAttr(item.filename)}', '${escapeAttr(item.dir || 'manga')}', '${escapeAttr(item.title)}')">📥</button>`
            : '';

        const cardSupplementRow = isInc
            ? `<div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;padding-top:4px;border-top:1px dashed #30363d;" onclick="event.stopPropagation()">
                 <span style="font-size:11px;color:#d29922;font-weight:600;">⚠️ 缺 ${missingCount} 话更新</span>
                 <button class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;background:#d29922;border-color:#bb8009;font-weight:600;border-radius:4px;" onclick="startSupplementSingleManga('${escapeAttr(item.id || '')}', '${escapeAttr(item.filename)}', '${escapeAttr(item.dir || 'manga')}', '${escapeAttr(item.title)}')">📥 补全下载</button>
               </div>`
            : '';

        card.innerHTML = `
            <div class="manga-cover-wrap">
                ${item.has_cover ? `<img src="${item.cover_url}" class="manga-cover" loading="lazy">` : `<div class="manga-cover-fallback">📖</div>`}
                ${completeBadge}
                <div class="manga-actions-hover" onclick="event.stopPropagation()">
                    ${hoverSupplementBtn}
                    <button class="manga-mini-btn" title="调用系统外部阅读器 (Okular)" onclick="openExternalManga('${escapeAttr(item.filename)}', 'manga')">🖥️</button>
                    <button class="manga-mini-btn" title="移至回收站" onclick="deleteMangaFile('${escapeAttr(item.filename)}', 'manga')">🗑️</button>
                </div>
            </div>
            <div class="manga-info">
                <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                ${tagsHtml}
                <div class="manga-meta">
                    <span>${item.page_count ? item.page_count + ' 页' : '整本'}</span>
                    <span>${item.size_mb} MB</span>
                </div>
                ${cardSupplementRow}
            </div>
        `;
        grid.appendChild(card);
    });
    mangaShelfRenderIndex += nextChunk.length;
}

function filterMangaByTag(tag) {
    if (activeMangaSubTab !== 'shelf') {
        const shelfTabBtn = document.getElementById('manga-subtab-shelf');
        switchMangaSubTab('shelf', shelfTabBtn);
    }
    setMangaTagFilter(tag);
}

function loadMoreMangaShelf() {
    if (mangaShelfRenderIndex < currentMangaShelfList.length) {
        renderMangaShelf(null, false);
    }
}

// ================= 漫画画廊子标签与必看榜单系统 (每周必看 / 每月必看 TOP 80) =================
let activeMangaSubTab = 'shelf'; // 'shelf' | 'week' | 'month'

let rankingDataCache = {
    week: null,
    month: null
};

function switchMangaSubTab(subTab, btnEl) {
    if (isRemoteClient && subTab !== 'shelf') {   // 非本机：榜单是联网内容，禁用（按钮也已 CSS 隐藏）
        return;
    }
    activeMangaSubTab = subTab;
    document.querySelectorAll('#manga-sub-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');

    const localSec = document.getElementById('manga-local-section');
    const rankingSec = document.getElementById('manga-ranking-section');
    const rankHeading = document.getElementById('manga-ranking-heading');
    const rankLoading = document.getElementById('manga-ranking-loading');
    const rankGrid = document.getElementById('manga-ranking-grid');
    const subStats = document.getElementById('media-sub-stats');
    const onlineSec = document.getElementById('manga-online-section');

    if (subTab === 'shelf') {
        if (localSec) localSec.style.display = 'block';
        if (rankingSec) rankingSec.style.display = 'none';
        if (onlineSec && !currentMangaSearchQuery) onlineSec.style.display = 'none';
        const count = localMangaList ? localMangaList.length : 0;
        if (subStats) subStats.textContent = '共 ' + count + ' 部漫画';
        renderMangaTagBar();
        setMangaTagFilter(activeMangaTag);
    } else {
        if (localSec) localSec.style.display = 'none';
        if (rankingSec) rankingSec.style.display = 'block';
        if (onlineSec) onlineSec.style.display = 'none';

        const rankTitles = {
            week: '🔥 每周必看榜单 (禁漫官方本周热度 TOP 80 · 点击封面沉浸阅读或一键下载)',
            month: '🏆 每月必看榜单 (禁漫官方本月热度 TOP 80 · 点击封面沉浸阅读或一键下载)'
        };
        if (rankHeading) rankHeading.textContent = rankTitles[subTab] || '🔥 热门榜单';
        if (subStats) subStats.textContent = (subTab === 'week' ? '每周必看 TOP 80' : '每月必看 TOP 80') + ' · 官方热度实时排行';

        if (rankingDataCache[subTab] && rankingDataCache[subTab].length > 0) {
            if (rankLoading) rankLoading.style.display = 'none';
            renderMangaRankingGrid(rankingDataCache[subTab]);
        } else {
            if (rankLoading) rankLoading.style.display = 'block';
            if (rankGrid) rankGrid.innerHTML = '';
            fetch(`/api/manga/rankings?type=${subTab}&page=1&count=80&t=` + Date.now())
                .then(r => r.json())
                .then(data => {
                    if (rankLoading) rankLoading.style.display = 'none';
                    const items = data.results || [];
                    rankingDataCache[subTab] = items;
                    renderMangaRankingGrid(items);
                })
                .catch(err => {
                    if (rankLoading) rankLoading.style.display = 'none';
                    if (rankGrid) rankGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f85149;padding:40px;">获取榜单遇到异常: ${err}</div>`;
                });
        }
    }
}

function renderMangaRankingGrid(items) {
    const grid = document.getElementById('manga-ranking-grid');
    if (!grid) return;
    grid.innerHTML = '';

    if (!items || items.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#8b949e;padding:40px;">暂无榜单数据</div>';
        return;
    }

    items.forEach((item, idx) => {
        const rankNum = idx + 1;
        const card = document.createElement('div');
        card.className = 'manga-card';
        const inQueue = isMangaInQueue(item.id);
        const localMatch = findLocalMangaMatch(item);

        let badgeHtml = `
            <span class="manga-badge-online">JM${item.id}</span>
        `;
        let actionHtml = '';

        if (localMatch) {
            badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#238636;">✓ 已在书架</span>`;
            actionHtml = `
                <div style="display:flex;gap:6px;margin-top:8px;">
                    <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;justify-content:center;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">
                        📖 立即阅读
                    </button>
                    <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;" title="重新下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">🔄 重下</button>
                </div>
            `;
        } else {
            actionHtml = `
                <div style="display:flex;gap:6px;margin-top:8px;">
                    <button id="manga-queue-btn-${item.id}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="flex:1;font-size:11.5px;padding:5px 8px;justify-content:center;" onclick="toggleMangaQueueItem('${item.id}', '${escapeAttr(item.title)}', '${escapeAttr(item.cover_url)}', this)">
                        ${inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表'}
                    </button>
                    <button class="manga-btn manga-btn-primary" style="font-size:11.5px;padding:5px 8px;" title="立即下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">📥 一键下载</button>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="manga-cover-wrap">
                <img src="${item.cover_url}" class="manga-cover" loading="lazy" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'130\\' fill=\\'%2321262d\\'><rect width=\\'100\\' height=\\'130\\'/></svg>'">
                ${badgeHtml}
            </div>
            <div class="manga-info">
                <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                ${actionHtml}
            </div>
        `;
        grid.appendChild(card);
    });
}

// ================= 1. 漫画专属待下载列表系统 =================
let currentOnlineResults = [];

let currentMangaSearchQuery = '';

let currentMangaPage = 1;

let currentMangaSort = 'mv';

let hasMoreMangaPages = false;

let isLoadingMoreManga = false;

let totalOnlineMangaCount = 0;

let mangaDownloadQueue = [];

function onMangaSortChange(val) {
    currentMangaSort = val || 'mv';
    const input = document.getElementById('manga-search-input');
    const valInput = (input ? input.value : '').trim();
    if (valInput) {
        executeUnifiedSearch(valInput);
    }
}

try {
    const savedMangaQueue = localStorage.getItem('omni_manga_queue');
    if (savedMangaQueue) mangaDownloadQueue = JSON.parse(savedMangaQueue);
} catch(e) {}

function saveMangaDownloadQueue() {
    try {
        localStorage.setItem('omni_manga_queue', JSON.stringify(mangaDownloadQueue));
    } catch(e) {}
    updateMangaQueueBadge();

    fetch('/api/manga/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: mangaDownloadQueue, dir: 'manga' })
    }).catch(() => {});
}

function loadPersistentMangaQueue() {
    fetch('/api/manga/queue?dir=manga&t=' + Date.now())
        .then(r => r.json())
        .then(items => {
            if (Array.isArray(items)) {
                mangaDownloadQueue = items;
                try { localStorage.setItem('omni_manga_queue', JSON.stringify(mangaDownloadQueue)); } catch(e) {}
                updateMangaQueueBadge();
                const modal = document.getElementById('manga-download-queue-modal');
                if (modal && modal.style.display === 'flex') {
                    renderMangaQueueModalItems();
                }
            }
        })
        .catch(() => {});
}

function updateMangaQueueBadge() {
    const count = mangaDownloadQueue.length;
    const mBadge = document.getElementById('manga-queue-badge-count');
    const modalBadge = document.getElementById('manga-queue-modal-badge');
    const btnCount = document.getElementById('manga-queue-btn-count');

    if (mBadge) mBadge.textContent = count;
    if (modalBadge) modalBadge.textContent = `(共 ${count} 部)`;
    if (btnCount) btnCount.textContent = count;
}

function isMangaInQueue(id) {
    return mangaDownloadQueue.some(item => String(item.id) === String(id));
}

function toggleMangaQueueItem(id, title, cover_url, btnEl) {
    id = String(id);
    const idx = mangaDownloadQueue.findIndex(item => String(item.id) === id);
    let inQueue = false;
    if (idx >= 0) {
        mangaDownloadQueue.splice(idx, 1);
        inQueue = false;
    } else {
        mangaDownloadQueue.push({ id, title, cover_url });
        inQueue = true;
    }
    saveMangaDownloadQueue();

    const targetBtn = btnEl || document.getElementById(`manga-queue-btn-${id}`);
    if (targetBtn) {
        targetBtn.className = `manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}`;
        targetBtn.textContent = inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表';
    }

    renderMangaQueueModalItems();
}

function removeMangaQueueItem(id) {
    id = String(id);
    mangaDownloadQueue = mangaDownloadQueue.filter(item => String(item.id) !== id);
    saveMangaDownloadQueue();
    renderMangaQueueModalItems();

    const cardBtn = document.getElementById(`manga-queue-btn-${id}`);
    if (cardBtn) {
        cardBtn.className = 'manga-btn';
        cardBtn.textContent = '➕ 加入待下载列表';
    }
}

function recoverUncompletedMangaDownloads() {
    const btn = document.getElementById('manga-queue-recover-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '🔄 扫描中...';
    }
    fetch('/api/manga/recover_temp?dir=manga&t=' + Date.now())
        .then(r => r.json())
        .then(res => {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🔄 找回未完成下载';
            }
            const count = res.recovered_count || 0;
            if (count > 0) {
                alert(`已成功找回 ${count} 部存在下载碎片的漫画并重新加入待下载列表！`);
                loadPersistentMangaQueue();
            } else {
                alert('扫描完成！当前 temp 目录下所有未完成漫画均已在待下载列表中，无遗漏作品。');
            }
        })
        .catch(err => {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🔄 找回未完成下载';
            }
            alert('扫描未完成漫画失败: ' + err);
        });
}

function clearMangaDownloadQueue() {
    if (mangaDownloadQueue.length === 0) return;
    mangaDownloadQueue = [];
    saveMangaDownloadQueue();
    renderMangaQueueModalItems();

    document.querySelectorAll('#manga-online-grid .manga-btn-in-queue').forEach(btn => {
        btn.className = 'manga-btn';
        btn.textContent = '➕ 加入待下载列表';
    });
}

function openMangaQueueModal() {
    renderMangaQueueModalItems();
    pollMangaTasks();
    const modal = document.getElementById('manga-download-queue-modal');
    if (modal) modal.style.display = 'flex';
}

function closeMangaQueueModal() {
    const modal = document.getElementById('manga-download-queue-modal');
    if (modal) modal.style.display = 'none';
}

function renderMangaQueueModalItems() {
    updateMangaQueueBadge();
    const listEl = document.getElementById('manga-queue-items-list');
    const emptyEl = document.getElementById('manga-queue-empty-msg');
    const startBtn = document.getElementById('manga-queue-start-download-btn');
    const seqBtn = document.getElementById('manga-queue-seq-download-btn');
    const clearBtn = document.getElementById('manga-queue-clear-btn');
    if (!listEl) return;

    listEl.innerHTML = '';
    if (mangaDownloadQueue.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        if (startBtn) startBtn.disabled = true;
        if (seqBtn) seqBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';
    if (startBtn) startBtn.disabled = false;
    if (seqBtn) seqBtn.disabled = false;
    if (clearBtn) clearBtn.disabled = false;

    mangaDownloadQueue.forEach(item => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;background:#0d1117;padding:8px 12px;border-radius:8px;border:1px solid #21262d;gap:10px;';
        row.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;overflow:hidden;flex:1;">
                <img src="${item.cover_url}" style="width:36px;height:48px;object-fit:cover;border-radius:4px;background:#21262d;" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'36\\' height=\\'48\\' fill=\\'%2321262d\\'><rect width=\\'36\\' height=\\'48\\'/></svg>'">
                <div style="overflow:hidden;">
                    <div style="font-size:13px;font-weight:600;color:#f0f6fc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                    <div style="font-size:11px;color:#58a6ff;margin-top:2px;">JM${item.id}</div>
                </div>
            </div>
            <button class="manga-mini-btn" style="color:#f85149;border-color:#f8514944;padding:4px 8px;" onclick="removeMangaQueueItem('${item.id}')">✕ 移除</button>
        `;
        listEl.appendChild(row);
    });
}

function startMangaQueueBatchDownload(concurrency = 3) {
    if (mangaDownloadQueue.length === 0) {
        alert('漫画待下载列表为空！请先搜索漫画并添加到列表。');
        return;
    }
    const ids = mangaDownloadQueue.map(item => item.id);
    closeMangaQueueModal();

    fetch('/api/manga/batch_download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            album_ids: ids,
            dir: 'manga',
            pack_cbz: true,
            clean_temp: true,
            concurrency: concurrency
        })
    })
    .then(r => r.json())
    .then(res => {
        pollMangaTasks();
    })
    .catch(err => {
        alert('启动批量下载失败: ' + err);
    });
}

function stopMangaBatchDownload(taskId) {
    const queueStopBtn = document.getElementById('manga-queue-stop-btn');
    if (queueStopBtn) {
        queueStopBtn.disabled = true;
        queueStopBtn.textContent = '⏳ 正在请求停止...';
    }
    fetch('/api/manga/stop_batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId || null })
    })
    .then(r => r.json())
    .then(res => {
        pollMangaTasks();
    })
    .catch(err => {
        console.error('Failed to stop batch download:', err);
    });
}

let currentUnifiedLocalMatches = [];

function executeUnifiedSearch(overrideQuery) {
    const input = document.getElementById('manga-search-input');
    const q = (overrideQuery !== undefined ? overrideQuery : (input ? input.value : '') || '').trim();
    if (!q) {
        clearMangaSearch();
        return;
    }

    currentMangaSearchQuery = q;
    currentMangaPage = 1;
    hasMoreMangaPages = false;
    isLoadingMoreManga = false;
    totalOnlineMangaCount = 0;

    // 1. 本地匹配 (包含标题、作者、标签、以及编号 ID)
    currentUnifiedLocalMatches = [...filterLocalManga(q)];
    const localSection = document.getElementById('manga-local-section');
    const localHeading = document.getElementById('manga-local-heading');
    const emptyEl = document.getElementById('manga-shelf-empty');
    const rankingSection = document.getElementById('manga-ranking-section');

    if (rankingSection) rankingSection.style.display = 'none';
    if (localSection) localSection.style.display = 'block';
    if (localHeading) localHeading.textContent = `🟢 本地已收录 (匹配到 ${currentUnifiedLocalMatches.length} 部 · 点击封面直接阅读)`;
    renderMangaShelf(currentUnifiedLocalMatches);
    if (emptyEl) emptyEl.style.display = currentUnifiedLocalMatches.length === 0 ? 'block' : 'none';

    // 2. 同时检索禁漫全网（支持单 ID、多 ID 或标题关键字）
    const onlineSection = document.getElementById('manga-online-section');
    const onlineLoading = document.getElementById('manga-online-loading');
    const onlineGrid = document.getElementById('manga-online-grid');
    const kwLabel = document.getElementById('manga-search-kw-label');
    const moreLoading = document.getElementById('manga-online-more-loading');
    const endTip = document.getElementById('manga-online-end-tip');

    if (moreLoading) moreLoading.style.display = 'none';
    if (endTip) endTip.style.display = 'none';

    if (onlineSection) onlineSection.style.display = 'block';
    if (onlineLoading) onlineLoading.style.display = 'block';
    if (onlineGrid) onlineGrid.innerHTML = '';
    if (kwLabel) kwLabel.textContent = `正在全网检索: "${q}"...`;

    fetch('/api/manga/search?q=' + encodeURIComponent(q) + '&category=0&order_by=' + encodeURIComponent(currentMangaSort || 'mv') + '&page=1&t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            if (onlineLoading) onlineLoading.style.display = 'none';
            currentOnlineResults = data.online || [];
            hasMoreMangaPages = !!data.has_more;
            totalOnlineMangaCount = data.total_online || currentOnlineResults.length;

            if (kwLabel) {
                if (totalOnlineMangaCount > currentOnlineResults.length) {
                    kwLabel.textContent = `检索: "${q}" (已加载 ${currentOnlineResults.length}/${totalOnlineMangaCount} 部 · 向下滚动自动加载更多)`;
                } else {
                    kwLabel.textContent = `检索: "${q}" (共 ${currentOnlineResults.length} 部)`;
                }
            }

            // ⭐ 关键同步：将全网搜索结果中已被标记为“✓ 已在书架”的本地收录作品，自动动态合并进上方的“本地已收录”结果列表！
            // 彻底解决：网络搜索能基于官方角色/系列词找到已下载作品，而本地简单文本模糊匹配漏掉，导致本地展示数少于网络已下载数的问题
            let mergedNew = false;
            currentOnlineResults.forEach(onlineItem => {
                const localMatch = findLocalMangaMatch(onlineItem);
                if (localMatch) {
                    const alreadyInLocal = currentUnifiedLocalMatches.some(m => 
                        (m.filename && localMatch.filename && m.filename === localMatch.filename) ||
                        (m.id && localMatch.id && String(m.id) === String(localMatch.id))
                    );
                    if (!alreadyInLocal) {
                        currentUnifiedLocalMatches.push(localMatch);
                        mergedNew = true;
                    }
                }
            });

            if (mergedNew) {
                renderMangaShelf(currentUnifiedLocalMatches);
                if (localHeading) {
                    localHeading.textContent = `🟢 本地已收录 (匹配到 ${currentUnifiedLocalMatches.length} 部 · 点击封面直接阅读)`;
                }
                if (emptyEl) emptyEl.style.display = 'none';
            }

            renderOnlineResults(currentOnlineResults, currentUnifiedLocalMatches.length === 0, false);

            if (!hasMoreMangaPages && currentOnlineResults.length > 0 && endTip) {
                endTip.style.display = 'block';
            }
        })
        .catch(err => {
            if (onlineLoading) onlineLoading.style.display = 'none';
            if (onlineGrid) onlineGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f85149;padding:40px;">禁漫在线检索遇到异常: ${err}</div>`;
        });
}

function findLocalMangaMatch(onlineItem) {
    if (!localMangaList || localMangaList.length === 0) return null;
    const oId = String(onlineItem.id);
    const oTitle = (onlineItem.title || '').trim().toLowerCase();
    return localMangaList.find(local => {
        if (local.id && String(local.id) === oId) return true;
        const lTitle = (local.title || '').trim().toLowerCase();
        const lFile = (local.filename || '').trim().toLowerCase();
        return lFile.includes(oId) || lTitle.includes(oId) || (oTitle && lTitle === oTitle);
    });
}

function loadNextMangaPage() {
    if (isLoadingMoreManga || !hasMoreMangaPages || !currentMangaSearchQuery) return;
    isLoadingMoreManga = true;
    const moreLoading = document.getElementById('manga-online-more-loading');
    const endTip = document.getElementById('manga-online-end-tip');
    if (moreLoading) moreLoading.style.display = 'block';
    if (endTip) endTip.style.display = 'none';

    const nextPage = currentMangaPage + 1;
    fetch('/api/manga/search?q=' + encodeURIComponent(currentMangaSearchQuery) + '&category=0&order_by=' + encodeURIComponent(currentMangaSort) + '&page=' + nextPage + '&t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            if (moreLoading) moreLoading.style.display = 'none';
            isLoadingMoreManga = false;

            const newItems = data.online || [];
            if (newItems.length > 0) {
                currentMangaPage = nextPage;
                hasMoreMangaPages = !!data.has_more;
                totalOnlineMangaCount = data.total_online || totalOnlineMangaCount;
                currentOnlineResults.push(...newItems);

                // ⭐ 翻页加载更多时，同样自动将新发现的已收录作品合并进本地列表
                let mergedNew = false;
                newItems.forEach(onlineItem => {
                    const localMatch = findLocalMangaMatch(onlineItem);
                    if (localMatch) {
                        const alreadyInLocal = currentUnifiedLocalMatches.some(m => 
                            (m.filename && localMatch.filename && m.filename === localMatch.filename) ||
                            (m.id && localMatch.id && String(m.id) === String(localMatch.id))
                        );
                        if (!alreadyInLocal) {
                            currentUnifiedLocalMatches.push(localMatch);
                            mergedNew = true;
                        }
                    }
                });
                if (mergedNew) {
                    renderMangaShelf(currentUnifiedLocalMatches);
                    const localHeading = document.getElementById('manga-local-heading');
                    if (localHeading) {
                        localHeading.textContent = `🟢 本地已收录 (匹配到 ${currentUnifiedLocalMatches.length} 部 · 点击封面直接阅读)`;
                    }
                    const emptyEl = document.getElementById('manga-shelf-empty');
                    if (emptyEl) emptyEl.style.display = 'none';
                }

                const kwLabel = document.getElementById('manga-search-kw-label');
                if (kwLabel) {
                    kwLabel.textContent = `检索: "${currentMangaSearchQuery}" (已加载 ${currentOnlineResults.length}/${totalOnlineMangaCount} 部${hasMoreMangaPages ? ' · 向下滚动加载更多' : ''})`;
                }

                renderOnlineResults(newItems, false, true); // true = 追加模式，绝不刷新前面已有的卡片
            } else {
                hasMoreMangaPages = false;
            }

            if (!hasMoreMangaPages && endTip) {
                endTip.style.display = 'block';
            }
        })
        .catch(err => {
            isLoadingMoreManga = false;
            if (moreLoading) moreLoading.style.display = 'none';
            console.error('Failed to load next page of manga:', err);
        });
}

function clearOnlineSearchResults() {
    const onlineSection = document.getElementById('manga-online-section');
    const onlineGrid = document.getElementById('manga-online-grid');
    const kwLabel = document.getElementById('manga-search-kw-label');
    const endTip = document.getElementById('manga-online-end-tip');
    const moreLoading = document.getElementById('manga-online-more-loading');

    if (onlineSection) onlineSection.style.display = 'none';
    if (onlineGrid) onlineGrid.innerHTML = '';
    if (kwLabel) kwLabel.textContent = '';
    if (endTip) endTip.style.display = 'none';
    if (moreLoading) moreLoading.style.display = 'none';
    currentOnlineResults = [];
    currentMangaSearchQuery = '';
    currentMangaPage = 1;
    hasMoreMangaPages = false;
    isLoadingMoreManga = false;
    currentUnifiedLocalMatches = [];
}

function clearMangaSearch() {
    const input = document.getElementById('manga-search-input');
    if (input) input.value = '';

    const localSection = document.getElementById('manga-local-section');
    const localHeading = document.getElementById('manga-local-heading');
    if (localSection) localSection.style.display = 'block';
    if (localHeading) localHeading.textContent = '📚 本地已收录漫画';
    let list = localMangaList;
    if (activeMangaTag === '__incomplete__') {
        list = localMangaList.filter(item => item.is_complete === false);
    } else if (activeMangaTag !== 'all') {
        const normTag = normalizeZh(activeMangaTag);
        list = localMangaList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
    }
    renderMangaShelf(list);
    updateMangaIncompleteBanner();

    clearOnlineSearchResults();
}

function renderOnlineResults(results, isLocalEmpty = false, isAppend = false) {
    const grid = document.getElementById('manga-online-grid');
    if (!grid) return;
    if (!isAppend) {
        grid.innerHTML = '';
    }

    if (!results || results.length === 0) {
        if (!isAppend) {
            if (isLocalEmpty) {
                grid.innerHTML = `
                    <div style="grid-column: 1/-1; text-align: center; color: #8b949e; padding: 50px 20px;">
                        <div style="font-size:36px;margin-bottom:10px;">🔍</div>
                        <div style="font-size:15px;font-weight:600;color:#f0f6fc;">未检索到匹配的漫画作品</div>
                        <div style="font-size:13px;margin-top:6px;">请检查输入的编号或漫画名，支持同时输入多个编号（如 287234, 1074734）。</div>
                    </div>
                `;
            } else {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: #8b949e; padding: 30px;">全网暂未找到更多在线结果（已在上方展示本地已收录版本）</div>`;
            }
        }
        return;
    }

    results.forEach(item => {
        const card = document.createElement('div');
        card.className = 'manga-card';
        const inQueue = isMangaInQueue(item.id);
        const localMatch = findLocalMangaMatch(item);

        let badgeHtml = `<span class="manga-badge-online">JM${item.id}</span>`;
        let actionHtml = '';

        if (localMatch) {
            const isInc = (localMatch.is_complete === false);
            if (isInc) {
                badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#d29922dd;color:#fff;" title="本地仅收录部分章节">⚠️ ${localMatch.local_chapters || '?'}/${localMatch.online_chapters || '?'}话</span>`;
                actionHtml = `
                    <div style="display:flex;gap:6px;margin-top:8px;">
                        <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#d29922;border-color:#bb8009;justify-content:center;" onclick="startSupplementSingleManga('${item.id}', '${escapeAttr(localMatch.filename)}', 'manga', '${escapeAttr(item.title)}')">
                            📥 增量补更新
                        </button>
                        <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;color:#fff;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">📖 阅读</button>
                    </div>
                `;
            } else {
                badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#238636;">✓ 已在书架</span>`;
                actionHtml = `
                    <div style="display:flex;gap:6px;margin-top:8px;">
                        <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;justify-content:center;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">
                            📖 立即阅读
                        </button>
                        <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;" title="重新下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">🔄 重下</button>
                    </div>
                `;
            }
        } else {
            actionHtml = `
                <div style="display:flex;gap:6px;margin-top:8px;">
                    <button id="manga-queue-btn-${item.id}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="flex:1;font-size:11.5px;padding:5px 8px;justify-content:center;" onclick="toggleMangaQueueItem('${item.id}', '${escapeAttr(item.title)}', '${escapeAttr(item.cover_url)}', this)">
                        ${inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表'}
                    </button>
                    <button class="manga-btn manga-btn-primary" style="font-size:11.5px;padding:5px 8px;" title="立即下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">📥 一键下载</button>
                </div>
            `;
        }

        const tagsList = Array.isArray(item.tags) ? item.tags : [];
        const onlineTagsHtml = tagsList.length > 0
            ? `<div class="manga-tags-row" onclick="event.stopPropagation()">
                ${tagsList.slice(0, 3).map(t => `<span class="manga-tag-pill" title="按标签筛选: ${escapeAttr(t)}" onclick="filterMangaByTag('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)}</span>`).join('')}
              </div>`
            : '';

        card.innerHTML = `
            <div class="manga-cover-wrap">
                <img src="${item.cover_url}" class="manga-cover" loading="lazy" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'130\\' fill=\\'%2321262d\\'><rect width=\\'100\\' height=\\'130\\'/></svg>'">
                ${badgeHtml}
            </div>
            <div class="manga-info">
                <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                ${onlineTagsHtml}
                ${actionHtml}
            </div>
        `;
        grid.appendChild(card);
    });
}

function openChapterSelectModal(albumId) {
    const modal = document.getElementById('manga-chapters-modal');
    modal.style.display = 'flex';
    document.getElementById('modal-album-title').textContent = '正在获取章节目录...';
    document.getElementById('modal-album-author').textContent = '';
    document.getElementById('modal-chapters-list').innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#8b949e;padding:20px;">正在加载章节列表...</div>';

    fetch('/api/manga/detail?id=' + albumId)
        .then(r => r.json())
        .then(detail => {
            currentModalAlbumDetail = detail;
            document.getElementById('modal-album-title').textContent = detail.title;
            document.getElementById('modal-album-author').textContent = '作者: ' + (detail.author || '未知') + ' · 共 ' + (detail.chapters || []).length + ' 话';

            const listEl = document.getElementById('modal-chapters-list');
            listEl.innerHTML = '';
            (detail.chapters || []).forEach(ch => {
                const label = document.createElement('label');
                label.style.cssText = 'display:flex;align-items:center;gap:6px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 10px;font-size:12px;color:#c9d1d9;cursor:pointer;';
                label.innerHTML = `
                    <input type="checkbox" class="chapter-cb" value="${ch.photo_id}" checked onchange="updateSelectedChapterCount()">
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeAttr(ch.title)}">${escapeHtml(ch.title)}</span>
                `;
                listEl.appendChild(label);
            });
            updateSelectedChapterCount();
        })
        .catch(err => {
            document.getElementById('modal-chapters-list').innerHTML = `<div style="grid-column:1/-1;color:#f85149;">加载失败: ${err}</div>`;
        });
}

function updateSelectedChapterCount() {
    const cbs = document.querySelectorAll('.chapter-cb:checked');
    document.getElementById('modal-selected-count').textContent = '已选 ' + cbs.length + ' 话';
}

function selectAllChapters(select) {
    document.querySelectorAll('.chapter-cb').forEach(cb => cb.checked = select);
    updateSelectedChapterCount();
}

function closeChapterModal() {
    document.getElementById('manga-chapters-modal').style.display = 'none';
}

function confirmDownloadSelectedChapters() {
    if (!currentModalAlbumDetail) return;
    const selected = Array.from(document.querySelectorAll('.chapter-cb:checked')).map(cb => cb.value);
    if (selected.length === 0) {
        alert('请至少勾选一个章节！');
        return;
    }
    const cleanTemp = document.getElementById('modal-clean-temp-cb').checked;
    closeChapterModal();

    fetch('/api/manga/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            album_id: currentModalAlbumDetail.id,
            chapter_ids: selected,
            pack_cbz: true,
            clean_temp: cleanTemp
        })
    }).then(r => r.json()).then(res => {
        alert(`已启动 ${selected.length} 个勾选章节的后台下载与解密！`);
        pollMangaTasks();
    }).catch(err => {
        alert('启动下载任务失败: ' + err);
    });
}

function renderMangaTasksProgress(tasks) {
    const container = document.getElementById('manga-tasks-container');
    const card = document.getElementById('manga-tasks-card');
    if (!container || !card) return;

    if (!tasks || tasks.length === 0) {
        container.style.display = 'none';
        return;
    }

    // 同步模态弹窗中的【⏹️ 完工当前后停止】按钮
    const queueStopBtn = document.getElementById('manga-queue-stop-btn');
    const activeBatch = tasks.find(t => t.is_batch && (t.status === 'downloading' || t.status === 'queued'));
    if (queueStopBtn) {
        if (activeBatch) {
            queueStopBtn.style.display = 'inline-block';
            if (activeBatch.stopping) {
                queueStopBtn.disabled = true;
                queueStopBtn.textContent = '⏳ 完工后将停止';
                queueStopBtn.style.opacity = '0.6';
            } else {
                queueStopBtn.disabled = false;
                queueStopBtn.textContent = '⏹️ 完工当前后停止';
                queueStopBtn.style.opacity = '1';
            }
        } else {
            queueStopBtn.style.display = 'none';
        }
    }

    const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed');
    if (activeTasks.length > 0) {
        container.style.display = 'block';
        card.innerHTML = tasks.slice(0, 3).map(t => `
            <div style="display:flex;flex-direction:column;gap:6px;padding:6px 0;border-bottom:1px solid #21262d;">
                <div class="manga-task-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                    <div style="font-size:13px;font-weight:600;color:#f0f6fc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">${escapeHtml(t.title)}</div>
                    <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                        <div style="font-size:12px;color:#58a6ff;font-weight:700;">${t.percent}%</div>
                        ${t.is_batch && (t.status === 'downloading' || t.status === 'queued') ? `
                            <button class="manga-mini-btn" style="padding:2px 8px;font-size:11px;color:${t.stopping ? '#8b949e' : '#f85149'};border-color:${t.stopping ? '#30363d' : '#f8514966'};background:#21262d;"
                                onclick="stopMangaBatchDownload('${t.task_id}')"
                                ${t.stopping ? 'disabled' : ''}>
                                ${t.stopping ? '⏳ 完工后将停止' : '⏹️ 完工当前后停止'}
                            </button>
                        ` : ''}
                    </div>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="width: ${t.percent}%;"></div>
                </div>
                <div style="font-size:11.5px;color:#8b949e;">${escapeHtml(t.message || '')}</div>
            </div>
        `).join('');
    } else {
        setTimeout(() => { container.style.display = 'none'; }, 4000);
    }
}

let lastCompletedMangaCount = -1;

function pollMangaTasks() {
    initMangaEventStream();
    fetch('/api/manga/tasks?t=' + Date.now())
        .then(r => r.json())
        .then(tasks => {
            renderMangaTasksProgress(tasks);
        })
        .catch(() => {});
}

function cleanMangaTemp() {
    fetch('/api/manga/clean_temp', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            alert(`清理完成！已清理 ${res.cleaned_count || 0} 个临时解密切片目录/文件。`);
        });
}

// ================= 内嵌 Webtoon 瀑布流漫画/小说阅读器 =================
let currentReaderDir = '';

function openMangaReader(filename, dir = '') {
    currentReaderCbz = filename;
    currentReaderDir = dir || '';
    const modal = document.getElementById('manga-reader-modal');
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';

    document.getElementById('reader-title').textContent = filename.replace(/\.(cbz|txt|epub)$/i, '');
    const container = document.getElementById('reader-image-container');
    container.innerHTML = '<div style="color:#8b949e;padding:50px;">正在解析封箱切片内容...</div>';

    const dirQuery = currentReaderDir ? '&dir=' + encodeURIComponent(currentReaderDir) : '';
    fetch('/api/manga/pages?name=' + encodeURIComponent(filename) + dirQuery)
        .then(r => r.json())
        .then(pages => {
            container.innerHTML = '';
            document.getElementById('reader-page-counter').textContent = '共 ' + pages.length + ' 页';
            pages.forEach((p, idx) => {
                const img = document.createElement('img');
                img.className = 'reader-img';
                img.loading = idx < 3 ? 'eager' : 'lazy';
                img.src = `/api/manga/page?name=${encodeURIComponent(filename)}&page=${encodeURIComponent(p)}${dirQuery}`;
                container.appendChild(img);
            });

            // 恢复上次浏览滚动位置
            const savedPos = localStorage.getItem('omni_manga_scroll_' + filename);
            if (savedPos) {
                setTimeout(() => { modal.scrollTop = parseInt(savedPos, 10); }, 50);
            } else {
                modal.scrollTop = 0;
            }
        })
        .catch(err => {
            container.innerHTML = `<div style="color:#f85149;padding:50px;">读取失败: ${err}</div>`;
        });

    // 监听滚动位置并实时记忆
    modal.onscroll = () => {
        try {
            localStorage.setItem('omni_manga_scroll_' + filename, modal.scrollTop);
        } catch(e) {}
    };
}

function closeMangaReader() {
    document.getElementById('manga-reader-modal').style.display = 'none';
    document.getElementById('reader-image-container').innerHTML = '';
    document.body.style.overflow = '';
    document.documentElement.style.overflow = '';
}

function openCurrentMangaExternal() {
    if (currentReaderCbz) {
        openExternalManga(currentReaderCbz, currentReaderDir);
    }
}

function openExternalManga(filename, dir = '') {
    fetch('/api/manga/open_external', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename, dir: dir })
    });
}

function deleteMangaFile(filename, dir = '') {
    if (!confirm(`确定将《${filename}》移至回收站吗？`)) return;
    fetch('/api/manga/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename, dir: dir })
    }).then(r => r.json()).then(res => {
        if (dir === 'novels') {
            loadNovelsLibrary();
        } else {
            loadMangaLibrary();
        }
    });
}

function startFullMangaDownload(album_id, title, dir = 'manga') {
    fetch('/api/manga/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ album_id: album_id, dir: dir, pack_cbz: true, clean_temp: true })
    })
    .then(r => r.json())
    .then(res => {
        pollMangaTasks();
    })
    .catch(err => {
        alert('启动下载遇到异常: ' + err);
    });
}

function toggleReaderFullscreen() {
    const modal = document.getElementById('manga-reader-modal');
    const btn = document.getElementById('manga-fullscreen-btn');
    const isImmersive = modal.classList.toggle('reader-immersive-fullscreen');

    if (!document.fullscreenElement) {
        const req = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || modal.requestFullscreen;
        if (req) {
            req.call(document.documentElement || modal).catch(() => {});
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen().catch(() => {});
        }
    }

    if (btn) {
        btn.textContent = (isImmersive || document.fullscreenElement) ? '🗗 退出全屏' : '⛶ 全屏';
    }
}

Omni.register('manga', {
    activate() {
        const subStats = document.getElementById('media-sub-stats');
        const count = localMangaList && localMangaList.length > 0 ? localMangaList.length : null;
        if (count !== null) {
            document.getElementById('total-badge').textContent = count + ' 部漫画';
            if (subStats) subStats.textContent = '共 ' + count + ' 部漫画';
            renderMangaTagBar();
            updateMangaIncompleteBanner();
            const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
            if (activeMangaSubTab === 'shelf') {
                let baseList = localMangaList;
                if (searchVal) {
                    baseList = filterLocalManga(searchVal);
                }
                if (activeMangaTag === 'all') {
                    renderMangaShelf(baseList);
                } else {
                    const normTag = normalizeZh(activeMangaTag);
                    const filtered = baseList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
                    renderMangaShelf(filtered);
                }
            } else if (rankingDataCache[activeMangaSubTab]) {
                renderMangaRankingGrid(rankingDataCache[activeMangaSubTab]);
            }
        } else {
            document.getElementById('total-badge').textContent = '漫画画廊';
            if (subStats) subStats.textContent = '正在读取本地漫画库...';
            loadMangaLibrary();
        }
    },
    onScrollEnd() {
        if (activeMangaSubTab === 'shelf') {
            loadMoreMangaShelf();
        } else if (currentMangaSearchQuery && hasMoreMangaPages && !isLoadingMoreManga) {
            loadNextMangaPage();
        }
    },
    onUnlock() { loadMangaLibrary(); },
    onLibraryChanged() { localMangaList = []; },
    onMediaEnter() {
        loadPersistentMangaQueue();
        pollMangaTasks();
    },
    prewarm() {
        if (!localMangaList || localMangaList.length === 0) {
                fetch('/api/manga/library?dir=manga&t=' + Date.now())
                    .then(r => r.json())
                    .then(list => {
                        localMangaList = list || [];
                        const mangaCountBadge = document.getElementById('manga-local-count');
                        if (mangaCountBadge) mangaCountBadge.textContent = `(${localMangaList.length} 部)`;
                        if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                            document.getElementById('total-badge').textContent = localMangaList.length + ' 部漫画';
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = '共 ' + localMangaList.length + ' 部漫画';
                            renderMangaTagBar();
                            updateMangaIncompleteBanner();
                            if (activeMangaSubTab === 'shelf') {
                                const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
                                const baseList = searchVal ? filterLocalManga(searchVal) : localMangaList;
                                renderMangaShelf(baseList);
                            }
                        }
                    })
                    .catch(() => {});
            }
    },
});
