// 局域网设备只能玩大厅 webview 能直接渲染的游戏；PC 独立大作 (standalone)、
// Flash 的 web_flash 引擎、SLG 分区里用 Ren'Py 原生子进程跑的那部分，都是在 Deck 本机
// 单独开一个窗口/子进程，局域网设备连不上、看不见，所以要在游戏网格与数量统计里统一剔除。
function isLanUnplayableGame(g) {
    const rule = ACCESS_RULES[g.type];
    return !!(rule && rule.requiresLocal) || (g.type === 'slg' && g.slg_engine === 'renpy');
}

// 游戏类型就是 manifest 的分区 id；该分区 access=nsfw（见 ACCESS_RULES）即为 NSFW 游戏
function isNsfwGame(g) {
    const rule = ACCESS_RULES[g.type] || ACCESS_RULES[g.category];
    return !!(rule && rule.requiresNsfwUnlock);
}

let allGames = [];

const _initUrlCat = new URLSearchParams(window.location.search).get('category');

let currentTab = (_initUrlCat && _initUrlCat !== 'portal')
    ? _initUrlCat
    : ((isDeckLocal || localStorage.getItem('omni_nsfw_token')) ? 'rpg' : 'standalone');

let currentStandaloneSubTab = null;

let currentSearchQuery = '';

let currentGameSearchQuery = '';

function launchStandaloneGame(gid, title) {
    fetch('/api/games/launch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: gid, title: title })
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === 'ok') {
            alert(`🎮 正在 Steam Deck 屏幕启动 《${title}》！\n\n请直接查看 Deck 实体机屏幕或任务栏。`);
        } else {
            alert('启动失败: ' + (res.error || res.message || '未知错误'));
        }
    })
    .catch(err => alert('启动请求失败: ' + err));
}

// 收藏夹管理 (永久存储于 localStorage)
function getFavorites() {
    try {
        return JSON.parse(localStorage.getItem('rpgweb_favorites') || '[]');
    } catch(e) {
        return [];
    }
}

function saveFavorites(favs) {
    localStorage.setItem('rpgweb_favorites', JSON.stringify(favs));
    updateFavBadges();
}

function toggleFavorite(e, gameId) {
    e.preventDefault();
    e.stopPropagation();
    let favs = getFavorites();
    if (favs.includes(gameId)) {
        favs = favs.filter(id => id !== gameId);
    } else {
        favs.push(gameId);
    }
    saveFavorites(favs);
    applyFilter();
}

function updateFavBadges() {
    const favs = getFavorites();
    const badge = document.getElementById('fav-count-badge');
    if (badge) badge.textContent = favs.length + ' Favorites';
}

function showPortalView() {
    document.querySelectorAll('.cat-init-style, #cat-init-style').forEach(el => el.remove());
    document.getElementById('portal-view').style.display = 'block';
    document.getElementById('list-view').style.display = 'none';
    document.getElementById('list-controls').style.display = 'none';
    document.getElementById('nav-back-btn').style.display = 'none';
    const gSearch = document.getElementById('game-search-input');
    if (gSearch) gSearch.value = '';
    currentSearchQuery = '';
    currentGameSearchQuery = '';
    currentTab = isNsfwUnlocked ? 'rpg' : 'standalone';
    currentStandaloneSubTab = null;
    document.querySelectorAll('#standalone-sub-filters .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
    if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', window.location.pathname);
    }
    window.scrollTo({ top: 0, behavior: 'instant' });
}

function openCategory(cat) {
    const rule = ACCESS_RULES[cat];
    if (rule && rule.requiresNsfwUnlock && !isNsfwUnlocked) {
        openNsfwModal();
        return;
    }
    if (rule && rule.requiresLocal && isRemoteClient) {
        return;   // 局域网不可用分区：卡片已隐藏，这里只是兜底（URL 直连等场景）
    }
    cleanupCatInitStyle();
    document.getElementById('portal-view').style.display = 'none';
    document.getElementById('list-view').style.display = 'block';
    document.getElementById('list-controls').style.display = 'flex';
    document.getElementById('nav-back-btn').style.display = 'flex';
    currentTab = cat;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === cat);
    });
    applyFilter();
}

function switchStandaloneSubTab(sub, el) {
    if (currentStandaloneSubTab === sub) {
        currentStandaloneSubTab = null;
        if (el) el.classList.remove('active');
    } else {
        currentStandaloneSubTab = sub;
        document.querySelectorAll('#standalone-sub-filters .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
        if (el) el.classList.add('active');
    }
    applyFilter();
}

function switchTab(tab, el) {
    const rule = ACCESS_RULES[tab];
    if (rule && rule.requiresNsfwUnlock && !isNsfwUnlocked) {
        openNsfwModal();
        return;
    }
    if (rule && rule.requiresLocal && isRemoteClient) {
        return;   // 局域网不可用分区：标签已隐藏，这里只是兜底（URL 直连等场景）
    }
    cleanupCatInitStyle();
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    applyFilter();
}

function onGameSearchInput(val) {
    currentSearchQuery = (val || '').trim().toLowerCase();
    currentGameSearchQuery = currentSearchQuery;
    if (currentSearchQuery && document.getElementById('portal-view').style.display !== 'none') {
        openCategory('rpg');
    } else {
        applyFilter();
    }
}

function applyFilter() {
    const searchInput = document.getElementById('game-search-input');
    if (searchInput) {
        currentSearchQuery = (searchInput.value || '').trim().toLowerCase();
        currentGameSearchQuery = currentSearchQuery;
    }

    const favs = getFavorites();
    const standaloneFilterEl = document.getElementById('standalone-sub-filters');
    if (standaloneFilterEl) {
        standaloneFilterEl.style.display = (!currentSearchQuery && currentTab === 'standalone') ? 'flex' : 'none';
    }

    // 星际2 对战：首页独立大卡片进来的专区，不是游戏卡片网格，是专属操作台
    const sc2Panel = document.getElementById('sc2-panel');
    const gameGrid = document.getElementById('game-grid');
    const showSc2 = currentTab === 'sc2';
    if (sc2Panel) sc2Panel.style.display = showSc2 ? 'block' : 'none';
    if (gameGrid) gameGrid.style.display = showSc2 ? 'none' : '';
    if (showSc2) {
        document.getElementById('list-controls').style.display = 'none'; // 不需要分类/搜索栏
        const stats = document.getElementById('filter-stats');
        if (stats) stats.textContent = '';
        initSc2Panel();
        return;
    }

    const filtered = allGames.filter(g => {
        // NSFW 隐私过滤：未解锁时彻底剔除 RPG 与 SLG 敏感游戏
        if (!isNsfwUnlocked && isNsfwGame(g)) return false;

        // 局域网访问安全隔离：外部设备严禁搜索与显示"只能在 Deck 本机开一个独立窗口"的游戏
        if (isRemoteClient && isLanUnplayableGame(g)) return false;

        const name = g.name || g.id || '';
        const matchesQuery = !currentSearchQuery || g.id.toLowerCase().includes(currentSearchQuery) || name.toLowerCase().includes(currentSearchQuery);

        if (currentSearchQuery) {
            return matchesQuery;
        }

        if (currentTab === 'fav') return favs.includes(g.id);
        if (currentTab === 'standalone') {
            if (g.type !== 'standalone') return false;
            if (currentStandaloneSubTab) return g.engine === currentStandaloneSubTab;
            return true;
        }
        return g.type === currentTab;
    });
    renderGames(filtered);
}

const RETRO_FRANCHISES = [
    {
        key: 'kov',
        name: '三国战纪与街机清版名作 (Knights of Valour & Arcade Classics)',
        icon: '🐉',
        match: g => /valour|oriental legend|warriors of fate|三国|西游/i.test(g.id) || /kov|orlegend|wof/i.test(g.rom_file || '')
    },
    {
        key: 'kof',
        name: '拳皇全系列 (The King of Fighters)',
        icon: '🥊',
        match: g => /fighters|kof|热斗/i.test(g.id) || /kof/i.test(g.rom_file || '')
    },
    {
        key: 'mslug',
        name: '合金弹头全系列 (Metal Slug)',
        icon: '🪖',
        match: g => /metal slug|mslug/i.test(g.id) || /mslug/i.test(g.rom_file || '')
    },
    {
        key: 'pokemon',
        name: '宝可梦全世代与外传 (Pokemon)',
        icon: '🐾',
        match: g => /pokemon|宝可梦|口袋妖怪/i.test(g.id)
    },
    {
        key: 'zelda',
        name: '塞尔达传说系列 (The Legend of Zelda)',
        icon: '🗡️',
        match: g => /zelda|塞尔达/i.test(g.id)
    },
    {
        key: 'mario',
        name: '超级马里奥与瓦里奥系列 (Super Mario & Wario)',
        icon: '🍄',
        match: g => /mario|wario|yoshi|princess peach|马里奥|瓦里奥|耀西|碧姬/i.test(g.id)
    },
    {
        key: 'ff',
        name: '最终幻想系列 (Final Fantasy)',
        icon: '🔮',
        match: g => /final fantasy|最终幻想/i.test(g.id)
    },
    {
        key: 'contra',
        name: '魂斗罗全系列 (Contra)',
        icon: '🔫',
        match: g => /contra|operation c|魂斗罗/i.test(g.id)
    },
    {
        key: 'other_retro',
        name: '其他复古经典名作 (Other Retro Classics)',
        icon: '🕹️',
        match: g => g.type === 'retro'
    }
];

function createGameCardElement(g, favs) {
    const item = document.createElement('a');
    item.className = 'game-card';

    let actionProto = 'action://play-rpg';
    let badgeText = 'RPG';
    let badgeClass = 'badge-rpg';

    if (g.type === 'standalone') {
        actionProto = 'action://play-standalone';
        const eng = (g.engine || 'PC').toLowerCase();
        if (eng === 'renpy') {
            badgeText = "Ren'Py";
            badgeClass = 'badge-renpy';
        } else if (eng === 'unity') {
            badgeText = 'Unity';
            badgeClass = 'badge-unity';
        } else if (eng === 'godot') {
            badgeText = 'Godot';
            badgeClass = 'badge-godot';
        } else if (eng === 'unreal') {
            badgeText = 'Unreal';
            badgeClass = 'badge-unreal';
        } else if (eng === 'app') {
            badgeText = 'Windows 软件';
            badgeClass = 'badge-app';
        } else {
            badgeText = 'PC / Wine';
            badgeClass = 'badge-wine';
        }
    } else if (g.type === 'retro') {
        actionProto = 'action://play-retro';
        badgeText = (g.system || 'Retro').toUpperCase();
        badgeClass = 'badge-retro';
    } else if (g.type === 'slg') {
        actionProto = 'action://play-slg';
        badgeText = 'SLG';
        badgeClass = 'badge-slg';
    } else if (g.type === 'flash') {
        actionProto = 'action://play-flash';
        badgeText = 'Flash';
        badgeClass = 'badge-flash';
    }

    const isDeckNative = navigator.userAgent.includes('QtWebEngine');
    if (isDeckNative) {
        item.href = actionProto + '?id=' + encodeURIComponent(g.id) + '&title=' + encodeURIComponent(g.name || g.id);
    } else {
        // 适配 iPad / 手机 / 外部浏览器：绝不触发 action:// 自定义协议 (彻底消除 iOS 误弹 App Store 下载 Apple Vision Pro 的异常)
        if (g.type === 'retro') {
            item.href = '/player_retro.html?id=' + encodeURIComponent(g.id) + '&system=' + encodeURIComponent(g.system || 'arcade') + '&rom=' + encodeURIComponent(g.rom_file || '');
        } else if (g.type === 'flash') {
            if (g.engine === 'web_flash' && g.url) {
                item.href = g.url;
                item.target = '_blank';
            } else {
                item.href = '/player_flash.html?id=' + encodeURIComponent(g.id) + '&file=' + encodeURIComponent(g.swf_file || '');
            }
        } else if (g.type === 'rpg' || g.type === 'slg') {
            item.href = '/game/' + encodeURIComponent(g.id) + '/index.html';
        } else {
            // standalone / renpy 是 Windows/Linux 独立程序
            item.href = 'javascript:void(0);';
            if (isRemoteClient) {
                item.onclick = (e) => {
                    e.preventDefault();
                    alert(`🔒 独立大作《${g.name || g.id}》属于大型 PC / Windows 游戏，仅限在 Steam Deck 实体机屏幕上运行。\n\n局域网外部设备已禁用，防止 Deck 误唤醒卡顿。`);
                };
            } else {
                // 在 Steam Deck 本机浏览器中点击：直接调用后台 API 秒级拉起游戏，彻底告别 xdg-open 弹窗！
                item.onclick = (e) => {
                    e.preventDefault();
                    launchStandaloneGame(g.id, g.name || g.id);
                };
            }
        }
    }

    const isFav = favs.includes(g.id);
    const starBtn = document.createElement('button');
    starBtn.className = 'fav-star-btn' + (isFav ? ' is-fav' : '');
    starBtn.title = isFav ? '取消收藏' : '加入喜欢';
    starBtn.innerHTML = isFav ? '★' : '☆';
    starBtn.onclick = (e) => toggleFavorite(e, g.id);

    const titleBox = document.createElement('div');
    titleBox.className = 'game-title-box';

    const titleSpan = document.createElement('span');
    titleSpan.className = 'game-title';
    titleSpan.textContent = g.id;

    titleBox.appendChild(starBtn);
    titleBox.appendChild(titleSpan);

    const badgeSpan = document.createElement('span');
    badgeSpan.className = 'engine-badge ' + badgeClass;
    badgeSpan.textContent = badgeText;

    item.appendChild(titleBox);
    item.appendChild(badgeSpan);
    item.addEventListener('click', () => {
        sessionStorage.setItem('hub_scroll_' + currentTab, String(window.scrollY));
    });
    return item;
}

function createSeriesCardElement(icon, title, count, gameCards) {
    const card = document.createElement('div');
    card.className = 'series-card';

    const header = document.createElement('div');
    header.className = 'series-header';

    const titleBox = document.createElement('div');
    titleBox.className = 'series-title-box';

    const iconSpan = document.createElement('span');
    iconSpan.className = 'series-icon';
    iconSpan.textContent = icon;

    const titleSpan = document.createElement('span');
    titleSpan.className = 'series-title';
    titleSpan.textContent = title;

    titleBox.appendChild(iconSpan);
    titleBox.appendChild(titleSpan);

    const countBadge = document.createElement('span');
    countBadge.className = 'series-count-badge';
    countBadge.textContent = count + ' 款游戏';

    header.appendChild(titleBox);
    header.appendChild(countBadge);

    const flow = document.createElement('div');
    flow.className = 'series-game-flow';
    gameCards.forEach(c => flow.appendChild(c));

    card.appendChild(header);
    card.appendChild(flow);
    return card;
}

function renderGames(games) {
    const grid = document.getElementById('game-grid');
    grid.innerHTML = '';

    const stats = document.getElementById('filter-stats');
    if (stats) stats.textContent = '共 ' + games.length + ' 款游戏';

    if (games.length === 0) {
        const emptyTip = currentTab === 'fav' 
            ? '⭐ 暂无收藏游戏，点击任意游戏卡片左侧的 ★ 即可加入喜欢列表！'
            : '未检索到相关游戏';
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.innerHTML = `
            <div style="font-size:36px;margin-bottom:12px;">🔍</div>
            <div style="font-size:16px;color:#c9d1d9;margin-bottom:6px;">${emptyTip}</div>
            <div style="font-size:13px;">请尝试更换搜索关键词或切换上方专区标签</div>
        `;
        grid.appendChild(empty);
        return;
    }

    const favs = getFavorites();
    const isRetroView = (currentTab === 'retro' && !currentSearchQuery);

    if (isRetroView) {
        const seriesContainer = document.createElement('div');
        seriesContainer.className = 'series-container';

        const assignedSet = new Set();
        RETRO_FRANCHISES.forEach(f => {
            const matching = games.filter(g => !assignedSet.has(g.id) && f.match(g));
            if (matching.length > 0) {
                matching.forEach(g => assignedSet.add(g.id));
                const cards = matching.map(g => createGameCardElement(g, favs));
                seriesContainer.appendChild(createSeriesCardElement(f.icon, f.name, matching.length, cards));
            }
        });

        grid.appendChild(seriesContainer);
    } else {
        // 各专区平铺流 (RPG / 独立大作 / SLG / Flash / 喜欢)
        games.forEach(g => {
            grid.appendChild(createGameCardElement(g, favs));
        });
    }

    const savedScroll = sessionStorage.getItem('hub_scroll_' + currentTab);
    if (savedScroll) {
        const sTop = parseInt(savedScroll, 10);
        document.documentElement.scrollTop = sTop;
        document.body.scrollTop = sTop;
        window.scrollTo(0, sTop);
    }
}

function populateGames(games, isManualRefresh = false) {
    allGames = games;
    const rpgCount = games.filter(g => g.type === 'rpg').length;
    const standaloneCount = games.filter(g => g.type === 'standalone').length;
    const retroCount = games.filter(g => g.type === 'retro').length;
    const slgCount = isRemoteClient ? games.filter(g => g.type === 'slg' && !isLanUnplayableGame(g)).length : games.filter(g => g.type === 'slg').length;
    const flashCount = games.filter(g => g.type === 'flash').length;

    if (activePrimarySection === 'games') {
        if (isRemoteClient) {
            const playable = games.filter(g => !isLanUnplayableGame(g)).length;
            document.getElementById('total-badge').textContent = playable + ' 款网页轻量游戏 (局域网)';
        } else {
            document.getElementById('total-badge').textContent = games.length + ' 款游戏';
        }
    }
    document.getElementById('rpg-count-badge').textContent = rpgCount + ' Games';
    const standaloneBadge = document.getElementById('standalone-count-badge');
    if (standaloneBadge) standaloneBadge.textContent = isRemoteClient ? '🔒 本机独占' : standaloneCount + ' Games';
    document.getElementById('retro-count-badge').textContent = retroCount + ' Games';
    document.getElementById('slg-count-badge').textContent = slgCount + ' Games';
    const flashBadge = document.getElementById('flash-count-badge');
    if (flashBadge) flashBadge.textContent = isRemoteClient ? '🔒 本机独占' : flashCount + ' Games';
    const sc2Badge = document.getElementById('sc2-count-badge');
    if (sc2Badge) sc2Badge.textContent = isRemoteClient ? '🔒 本机独占' : '离线对战';

    updateFavBadges();
    applyRemoteClientRestrictions();

    if (!isManualRefresh && activePrimarySection === 'games') {
        const urlParams = new URLSearchParams(window.location.search);
        const initCat = urlParams.get('category');
        if (initCat && initCat !== 'portal') {
            document.getElementById('portal-view').style.display = 'none';
            document.getElementById('list-view').style.display = 'block';
            document.getElementById('list-controls').style.display = 'flex';
            document.getElementById('nav-back-btn').style.display = 'flex';
            currentTab = initCat;
            cleanupCatInitStyle();
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === initCat);
            });
        } else {
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === currentTab);
            });
        }
    }
    applyFilter();
}

function loadGames() {
    fetch('/api/games?t=' + Date.now(), { cache: 'no-store' })
        .then(res => res.json())
        .then(games => {
            try {
                localStorage.setItem('omni_games_cache', JSON.stringify(games));
                sessionStorage.setItem('omni_games_cache', JSON.stringify(games));
            } catch(e) {}
            populateGames(games);
        })
        .catch(err => {
            if (err.name === 'AbortError' || document.hidden) return;
            console.warn('Notice: loadGames fetch interrupted or network offline:', err.message || err);
        });
}
