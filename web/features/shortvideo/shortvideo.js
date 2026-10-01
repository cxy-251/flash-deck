// ================= 短视频画廊：快手 / 抖音 / TikTok =================
// 平台清单来自 manifest 里 module=shortvideo 的分区（id / platform / title），每个平台一份状态；
// DOM id 统一是 "<分区 id>-<名字>"（视图模板 features/shortvideo/view.html 按分区各渲染一次）。
const SV_SECTIONS = Omni.sections('media').filter(s => (s.module || s.id) === 'shortvideo');
const SV = Object.fromEntries(SV_SECTIONS.map(s => [s.platform, {
    folder: 'all', list: [], total: 0, page: 1, pageSize: 60, hasMore: true, loading: false,
    curIndex: -1, searchTimer: null, pollTimer: null,
}]));

const SV_LABEL = Object.fromEntries(SV_SECTIONS.map(s => [s.platform, s.title]));

let svPlayerPlatform = 'kuaishou';   // 播放器弹窗当前在播哪个平台的列表

let shortVideoLoopMode = 'list';     // 'list' | 'single'
// 短视频静音开关：记在本设备浏览器里，下次打开播放器还是同样状态
let shortVideoMuted = false;
try { shortVideoMuted = localStorage.getItem('omni.shortvideo.muted') === '1'; } catch (e) { /* 隐私模式等读不到就按有声 */ }

try {
    shortVideoLoopMode = localStorage.getItem('omni_shortvideo_loop_mode') || 'list';
} catch (e) {}

// 点赞按钮（播放器 / 图集查看器共用）：实心红心 = 已赞
function svSetLikeBtn(btn, liked) {
    if (!btn) return;
    setIcon(btn, liked ? 'favorite-fill' : 'favorite');
    btn.classList.toggle('liked', !!liked);
    btn.title = liked ? '取消点赞' : '点赞';
}

function updateShortVideoLoopBtnUI() {
    const btn = document.getElementById('shortvideo-loop-btn');
    if (!btn) return;
    if (shortVideoLoopMode === 'single') {
        setIcon(btn, 'repeat_one');
        btn.classList.add('active');
        btn.title = '循环模式：单视频循环（点击切换为列表循环）';
    } else {
        setIcon(btn, 'repeat');
        btn.classList.remove('active');
        btn.title = '循环模式：列表循环（点击切换为单片循环）';
    }
}

function toggleShortVideoLoopMode() {
    shortVideoLoopMode = shortVideoLoopMode === 'list' ? 'single' : 'list';
    try { localStorage.setItem('omni_shortvideo_loop_mode', shortVideoLoopMode); } catch (e) {}
    updateShortVideoLoopBtnUI();
}

function toggleShortVideoLike(platform, relPath, event) {
    if (event) event.stopPropagation();
    const st = SV[platform];
    const item = st ? st.list.find(x => x.rel_path === relPath) : null;
    const targetLiked = item ? !item.liked : true;

    fetch('/api/shortvideo/like', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, path: relPath, liked: targetLiked })
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === 'ok') {
            const actualLiked = !!res.liked;
            if (item) item.liked = actualLiked;

            // 同步当前网格
            renderShortVideoGrid(platform, false);

            // 同步播放器按钮
            const likeBtn = document.getElementById('shortvideo-like-btn');
            if (likeBtn && svPlayerPlatform === platform && st && st.curIndex >= 0 && st.list[st.curIndex] && st.list[st.curIndex].rel_path === relPath) {
                svSetLikeBtn(likeBtn, actualLiked);
            }
            const galleryLikeBtn = document.getElementById('shortvideo-gallery-like-btn');
            if (galleryLikeBtn && svGalleryPlatform === platform && st && st.curIndex >= 0 && st.list[st.curIndex] && st.list[st.curIndex].rel_path === relPath) {
                svSetLikeBtn(galleryLikeBtn, actualLiked);
            }

            // 同步 Native 播放器端
            if (window.omniBridge && typeof window.omniBridge.setLikeStatus === 'function') {
                window.omniBridge.setLikeStatus(platform, relPath, actualLiked);
            }
        }
    })
    .catch(err => console.error('Failed to toggle shortvideo like:', err));
}

function toggleShortVideoLikeFromPlayer() {
    const st = SV[svPlayerPlatform];
    if (!st || st.curIndex < 0 || st.curIndex >= st.list.length) return;
    const item = st.list[st.curIndex];
    toggleShortVideoLike(svPlayerPlatform, item.rel_path);
}

function toggleShortVideoLikeFromGallery() {
    const st = SV[svGalleryPlatform];
    if (!st || st.curIndex < 0 || st.curIndex >= st.list.length) return;
    const item = st.list[st.curIndex];
    toggleShortVideoLike(svGalleryPlatform, item.rel_path);
}

function svTabName(platform) {
    const sec = SV_SECTIONS.find(x => x.platform === platform);
    return sec ? sec.id : 'shortvideo';
}
function svPlatformFromTab(tab) {
    const sec = Omni.section(tab);
    return (sec && sec.platform) || 'kuaishou';
}
function svId(platform, base) { return `${svTabName(platform)}-${base}`; }
function svEl(platform, base) { return document.getElementById(svId(platform, base)); }

function onShortVideoSearchInput(platform, val) {
    const st = SV[platform];
    if (st.searchTimer) clearTimeout(st.searchTimer);
    st.searchTimer = setTimeout(() => loadShortVideoLibrary(platform, true), 250);
}

function rescanShortVideoLibrary(platform) {
    loadShortVideoLibrary(platform, true);
}

// 转码功能已停用：本机播放改走 native_player.py 的原生解码（QtMultimedia），不用再
// 转码；局域网/远程本来就是给原始文件，也用不上。这两个函数留空壳，防止旧页面缓存
// 或者别处遗漏的调用点报错。
function refreshShortVideoTranscodeStatus(platform) {}

function transcodeAllShortVideos(platform) {}

function formatVideoDuration(secs) {
    secs = Math.round(secs || 0);
    const m = Math.floor(secs / 60), s = secs % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function shortVideoImgFallback(imgEl) {
    imgEl.outerHTML = '<div class="manga-cover-fallback">📱</div>';
}

// 一页按屏幕实际能摆下多少张卡片来算（列数 x 能看到的行数 + 多留一行），不再固定
// 60 条——60 条经常比首屏能看到的多好几倍，等于一次性把好多张压根还没滚到看不见的
// 缩略图也拉去生成，白白占用刚加的那个"最多 3 个并发"的名额，首屏能看到的反而排在后面。
//
// 注意：这里故意不读 grid.clientWidth——切标签刚把容器从 display:none 切成可见，
// 紧接着就去读某个元素的 clientWidth，会逼着浏览器立刻做一次同步强制重排（这张页面
// 是所有功能挤在一起的单页应用，DOM 树不小，这一下重排本身就有 CPU 开销，快速连续
// 切标签等于连续触发好几次，CPU 占用跟着飙，重排卡住主线程那一下也正是画面闪烁的
// 真正原因）。改用 window.innerWidth（随时能拿到，不触发重排）估算，body 左右各
// 留了 24px 内边距、这张页面没有侧边栏，减一下就是网格的可用宽度，够用。
function computeShortVideoPageSize(platform) {
    const containerWidth = Math.max(320, window.innerWidth - 48);
    const cardMinW = 185, gap = 18;
    const cols = Math.max(1, Math.floor((containerWidth + gap) / (cardMinW + gap)));
    const cardW = (containerWidth - (cols - 1) * gap) / cols;
    const coverH = cardW * (16 / 9);           // 短视频封面是 9:16
    const infoH = 74;                          // 标题+meta 那一小条，大致估个高度
    const rowH = coverH + infoH + gap;
    const viewportH = window.innerHeight || 800;
    const rows = Math.max(1, Math.ceil(viewportH / rowH));
    return Math.min(200, cols * (rows + 1));   // 多留一整行做缓冲，别频繁触发下一页
}

function loadShortVideoLibrary(platform, reset = false) {
    const st = SV[platform];
    if (reset) {
        st.loading = false;
        st.page = 1;
        st.hasMore = true;
        st.pageSize = computeShortVideoPageSize(platform);
    } else if (st.loading) {
        return;
    }
    if (!st.hasMore && !reset) return;

    st.loading = true;
    const loadingIndicator = svEl(platform, 'loading-more');
    if (loadingIndicator) loadingIndicator.style.display = 'block';

    const searchEl = svEl(platform, 'search-input');
    const searchVal = (searchEl ? searchEl.value : '').trim();
    const url = `/api/shortvideo/library?platform=${platform}&folder=${encodeURIComponent(st.folder)}&q=${encodeURIComponent(searchVal)}&page=${st.page}&page_size=${st.pageSize}&t=${Date.now()}`;

    fetch(url)
        .then(r => r.json())
        .then(res => {
            st.loading = false;
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            if (res && res.error) return;

            const items = res.items || [];
            st.total = res.total || 0;
            st.hasMore = res.has_more || false;
            // 翻页追加时跳过已经在列表里的：后台补元数据 / 新下载会触发 liveRefresh，把第一页（最多 60 条）里
            // 没见过的追加到末尾，正常翻页再拉到它们就重复了（每页条数小于 60 时必现）
            const known = reset ? null : new Set(st.list.map(x => x.rel_path));
            st.list = reset ? items : st.list.concat(items.filter(x => !known.has(x.rel_path)));

            // 文件夹筛选条只在真正 reset（切筛选/搜索/首次进页）时才重建——翻页加载
            // 更多本来就是同一个查询的下一页，文件夹集合不会变，没必要每次都
            // innerHTML='' 再重建一遍；这条筛选条挂在瀑布流网格正上方，重建一次哪怕
            // 最终高度没变，也可能让浏览器在那一刻重新算一遍上面这块区域的布局，
            // 用户视觉上就会觉得"下面的内容跟着抖了一下/挪了地方"——触底加载更多时
            // 关掉这个重建，问题原样消失。
            if (reset) {
                st.pinned = res.pinned || [];
                renderShortVideoFolderBar(platform, res.folders || []);
            }

            const badge = svEl(platform, 'total-count-badge');
            if (badge) badge.textContent = `共 ${st.total} 条`;
            if (activePrimarySection === 'media' && activeMediaTab === svTabName(platform)) {
                const label = SV_LABEL[platform] || platform;
                document.getElementById('total-badge').textContent = `${st.total} 条 ${label} 视频`;
                const subStats = document.getElementById('media-sub-stats');
                if (subStats) subStats.textContent = `共 ${st.total} 条 ${label} 视频`;
            }

            renderShortVideoGrid(platform, reset);
            st.page++;
        })
        .catch(err => {
            st.loading = false;
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            console.error('Failed to load shortvideo library:', platform, err);
        });
}

// 后台文件监控发现新下载的短视频时（SSE library_indexed 事件）调这个，跟用户主动
// 切筛选/搜索触发的 loadShortVideoLibrary(platform, true) 不是一回事——那个 reset=true
// 会把整个网格 innerHTML 清空重建，几十张已经渲染好的封面图跟着全部重新加载一遍，
// 就是"每下载一条就闪一下"的原因。这里改成静默拉一遍最新数据，只把真正没见过的
// 几条（按 rel_path 判重）追加到列表末尾、只往 DOM 里插这几张新卡片，已经在屏幕上
// 的卡片原封不动，不会闪。代价是新视频不会立刻跳到瀑布流最前面（按时间重新排到最
// 前，要等用户下次真正切换筛选/进标签页触发一次 reset 才会体现），拿这点滞后换不
// 闪烁，划算。
function liveRefreshShortVideoLibrary(platform) {
    const st = SV[platform];
    if (!st || st.loading) return;
    const searchEl = svEl(platform, 'search-input');
    const searchVal = (searchEl ? searchEl.value : '').trim();
    const url = `/api/shortvideo/library?platform=${platform}&folder=${encodeURIComponent(st.folder)}&q=${encodeURIComponent(searchVal)}&page=1&page_size=${Math.max(st.pageSize || 60, 60)}&t=${Date.now()}`;
    fetch(url).then(r => r.json()).then(res => {
        if (!res || res.error) return;
        const known = new Set(st.list.map(x => x.rel_path));
        const fresh = (res.items || []).filter(it => !known.has(it.rel_path));
        st.total = res.total || st.total;
        const badge = svEl(platform, 'total-count-badge');
        if (badge) badge.textContent = `共 ${st.total} 条`;
        if (activePrimarySection === 'media' && activeMediaTab === svTabName(platform)) {
            const label = SV_LABEL[platform] || platform;
            document.getElementById('total-badge').textContent = `${st.total} 条 ${label} 视频`;
            const subStats = document.getElementById('media-sub-stats');
            if (subStats) subStats.textContent = `共 ${st.total} 条 ${label} 视频`;
        }
        if (!fresh.length) return;   // 没有真正新增的（比如只是别的文件被删了），不动网格
        st.list = st.list.concat(fresh);
        renderShortVideoGrid(platform, false);   // reset=false → 只追加新增那几条，不清空重建
    }).catch(() => {});
}

// 作者（文件夹）筛选条：第一行默认只有「全部」「我的点赞」，常看的作者自己钉上去（📌，存服务端，
// 各设备同一份）；当前选中的作者没钉也临时露在第一行。其余收进「更多作者」：带搜索框、可滚动的面板，
// 面板里每个作者也能直接钉 / 取消钉，选中一个作者面板自动收起。
function svFolderKey(f) {
    return f.key || (f.name === '全部' ? 'all' : f.name);
}

function svFolderChip(platform, f) {
    const st = SV[platform];
    const fKey = svFolderKey(f);
    const isSelected = st.folder === fKey;
    const isAuthor = !['all', 'liked'].includes(fKey);
    const pinned = isAuthor && (st.pinned || []).includes(f.name);
    const btn = document.createElement('button');
    btn.className = 'tab-btn sv-chip' + (isSelected ? ' active' : '') + (fKey === 'liked' ? ' sv-chip-liked' : '');
    btn.title = f.name;
    const label = document.createElement('span');
    label.className = 'sv-chip-label';
    label.textContent = `${f.name} (${f.count})`;
    btn.appendChild(label);
    if (isAuthor) {
        const pin = document.createElement('span');
        pin.className = 'sv-pin' + (pinned ? ' on' : '');
        pin.textContent = '📌';
        pin.title = pinned ? '从第一行取下' : '钉到第一行';
        pin.onclick = e => { e.stopPropagation(); svTogglePin(platform, f.name, !pinned); };
        btn.appendChild(pin);
    }
    btn.onclick = () => {
        st.folder = fKey;
        st.authorsOpen = false;
        loadShortVideoLibrary(platform, true);
    };
    return btn;
}

function svTogglePin(platform, name, pinned) {
    const st = SV[platform];
    fetch('/api/shortvideo/pin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, folder: name, pinned }),
    }).then(r => r.json()).then(d => {
        if (!d || d.status !== 'ok') return showMegaToast('操作失败', true);
        st.pinned = d.pinned || [];
        renderShortVideoFolderBar(platform, st.folders);
    }).catch(() => showMegaToast('操作失败', true));
}

function renderShortVideoFolderBar(platform, folders) {
    const bar = svEl(platform, 'folder-filter-bar');
    if (!bar) return;
    const st = SV[platform];
    if (!folders || folders.length <= 1) {
        bar.style.display = 'none';
        bar.innerHTML = '';
        return;
    }
    st.folders = folders;
    // 重画时保住面板里搜索框的焦点和光标（钉 / 取消钉会重画）
    const oldInput = bar.querySelector('.sv-author-search');
    const hadFocus = oldInput && document.activeElement === oldInput;
    const listScroll = (bar.querySelector('.sv-author-list') || {}).scrollTop || 0;
    bar.style.display = 'block';
    bar.innerHTML = '';

    const fixed = folders.filter(f => ['all', 'liked'].includes(svFolderKey(f)));
    const authors = folders.filter(f => !['all', 'liked'].includes(svFolderKey(f)));   // 后端已按条数从多到少排好
    const byName = new Map(authors.map(f => [f.name, f]));
    const first = (st.pinned || []).map(n => byName.get(n)).filter(Boolean);           // 按钉的先后
    const current = authors.find(f => svFolderKey(f) === st.folder);
    if (current && !first.includes(current)) first.push(current);

    const row = document.createElement('div');
    row.className = 'sv-chip-row';
    [...fixed, ...first].forEach(f => row.appendChild(svFolderChip(platform, f)));
    if (authors.length) {
        const more = document.createElement('button');
        more.className = 'tab-btn sv-chip sv-chip-more' + (st.authorsOpen ? ' active' : '');
        more.textContent = st.authorsOpen ? '收起 ▲' : `👤 更多作者 (${authors.length}) ▼`;
        more.onclick = () => { st.authorsOpen = !st.authorsOpen; renderShortVideoFolderBar(platform, st.folders); };
        row.appendChild(more);
    }
    bar.appendChild(row);

    if (st.authorsOpen) {
        const panel = document.createElement('div');
        panel.className = 'sv-author-panel';
        const input = document.createElement('input');
        input.className = 'search-input sv-author-search';
        input.placeholder = `🔍 在 ${authors.length} 个作者里搜索（点 📌 钉到第一行）`;
        input.value = st.authorFilter || '';
        const list = document.createElement('div');
        list.className = 'sv-author-list';
        const fill = () => {
            const q = input.value.trim().toLowerCase();
            st.authorFilter = input.value;
            const hits = q ? authors.filter(f => f.name.toLowerCase().includes(q)) : authors;
            list.innerHTML = '';
            hits.forEach(f => list.appendChild(svFolderChip(platform, f)));
            if (!hits.length) list.innerHTML = '<div class="sv-author-empty">没有匹配的作者</div>';
        };
        input.oninput = fill;
        panel.appendChild(input);
        panel.appendChild(list);
        bar.appendChild(panel);
        fill();
        list.scrollTop = listScroll;
        if (hadFocus || !oldInput) setTimeout(() => input.focus(), 0);
    }
}

function renderShortVideoGrid(platform, reset = true) {
    const grid = svEl(platform, 'grid');
    const emptyEl = svEl(platform, 'empty-msg');
    if (!grid) return;
    const st = SV[platform];

    if (reset) grid.innerHTML = '';

    if (st.list.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const startIdx = reset ? 0 : grid.children.length;
    for (let i = startIdx; i < st.list.length; i++) {
        const item = st.list[i];
        const isGallery = item.kind === 'images';
        const isLiked = !!item.liked;
        const card = document.createElement('div');
        card.className = 'manga-card';
        card.onclick = () => isGallery ? openShortVideoGallery(platform, i) : openShortVideoPlayer(platform, i);
        const cornerBadge = isGallery ? `${icon('photo_library-fill')}<span class="ico-text">${item.image_count || 1}</span>` : formatVideoDuration(item.duration);
        const centerIcon = icon(isGallery ? 'photo_library-fill' : 'play_arrow-fill');
        card.innerHTML = `
            <div class="manga-cover-wrap" style="aspect-ratio:9/16;">
                <img src="${item.thumb_url}" class="manga-cover" loading="lazy" onerror="shortVideoImgFallback(this)">
                <span class="manga-badge-cbz" style="background:rgba(0,0,0,0.68);">${cornerBadge}</span>
                ${isLiked ? `<span class="sv-liked-badge" title="已点赞">${icon('favorite-fill')}</span>` : ''}
                <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;">
                    <span class="sv-center-icon">${centerIcon}</span>
                </div>
                <div class="manga-actions-hover" onclick="event.stopPropagation()">
                    <button class="ico-btn sv-card-btn${isLiked ? ' liked' : ''}" title="${isLiked ? '取消点赞' : '点赞'}" onclick="toggleShortVideoLike('${platform}', '${escapeAttr(item.rel_path)}', event)">${icon(isLiked ? 'favorite-fill' : 'favorite')}</button>
                    <button class="ico-btn sv-card-btn" title="移至回收站" onclick="deleteShortVideoFile('${platform}', '${escapeAttr(item.rel_path)}')">${icon('delete')}</button>
                </div>
            </div>
            <div class="manga-info">
                <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                <div class="manga-meta">
                    <span title="${escapeAttr(item.folder)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">${escapeHtml(item.folder)}</span>
                    <span>${item.size_mb} MB</span>
                </div>
            </div>
        `;
        grid.appendChild(card);
    }
    if (grid.children.length === 0 && emptyEl) emptyEl.style.display = 'block';
}

// 同一个 <video> 标签、同一个播放器弹窗——本机（QtWebEngine 没有 H.264 解码器）跟局域网里
// 的手机/电脑浏览器打开的是同一份东西，不开新窗口。/api/shortvideo/stream 后端会按
// 请求是不是本机决定给转码过的 webm 还是原始文件，前端完全不用关心。两个平台共用一个
// 弹窗，svPlayerPlatform 记住当前播的是哪个平台，上一条/下一条/删除都照这个来。
function openShortVideoPlayer(platform, index) {
    const st = SV[platform];
    if (index < 0 || index >= st.list.length) return;
    svPlayerPlatform = platform;
    st.curIndex = index;
    const item = st.list[index];

    // 本机：有 omniBridge 就走原生解码播放（QtWebEngine 解不了 H.264，这条路绕开它，
    // 见 native_player.py）——原生播放器是盖在整个窗口上的浮层，网页这个 HTML 弹窗
    // 不用打开。局域网/远程设备没有这个 bridge，走下面原来那套 <video> 标签+HTTP 流。
    if (window.omniBridge && typeof window.omniBridge.playShortVideo === 'function') {
        nativePlaybackKind = 'shortvideo';
        window.omniBridge.playShortVideo(platform, item.rel_path, item.title || '');
        return;
    }

    const modal = document.getElementById('shortvideo-player-modal');
    const videoEl = document.getElementById('shortvideo-player-el');
    const titleEl = document.getElementById('shortvideo-player-title');
    const metaEl = document.getElementById('shortvideo-player-meta');
    const loadingEl = document.getElementById('shortvideo-player-loading');
    if (!modal || !videoEl) return;

    videoEl.pause();
    videoEl.poster = item.thumb_url || '';   // 先糊缩略图当封面，别黑屏等首帧
    // 只有"本机 + 这条真没转码缓存过"才提示"正在转码"——已经缓存过的（或本来就是
    // 局域网设备在看，压根不转码）不该无脑弹这句话
    if (loadingEl) loadingEl.style.display = (!isRemoteClient && !item.local_cached) ? 'flex' : 'none';
    videoEl.src = item.stream_url;
    if (titleEl) titleEl.textContent = item.title;
    if (metaEl) metaEl.textContent = `${item.folder} · ${item.mtime_str} · ${item.size_mb} MB`;
    updateShortVideoLoopBtnUI();
    videoEl.muted = shortVideoMuted;
    updateShortVideoMuteBtnUI();
    const likeBtn = document.getElementById('shortvideo-like-btn');
    if (likeBtn) {
        svSetLikeBtn(likeBtn, item.liked);
    }
    modal.style.display = 'flex';
    videoEl.play().catch((e) => console.log('Autoplay policy:', e));
}

function toggleShortVideoMute() {
    shortVideoMuted = !shortVideoMuted;
    try { localStorage.setItem('omni.shortvideo.muted', shortVideoMuted ? '1' : '0'); } catch (e) { /* 存不了就只在本次生效 */ }
    const videoEl = document.getElementById('shortvideo-player-el');
    if (videoEl) videoEl.muted = shortVideoMuted;
    updateShortVideoMuteBtnUI();
}

function updateShortVideoMuteBtnUI() {
    const btn = document.getElementById('shortvideo-mute-btn');
    if (!btn) return;
    setIcon(btn, shortVideoMuted ? 'volume_off-fill' : 'volume_up-fill');
    btn.classList.toggle('danger', shortVideoMuted);
    btn.title = shortVideoMuted ? '取消静音' : '静音';
}

function closeShortVideoPlayer() {
    const modal = document.getElementById('shortvideo-player-modal');
    const videoEl = document.getElementById('shortvideo-player-el');
    const loadingEl = document.getElementById('shortvideo-player-loading');
    if (videoEl) { videoEl.pause(); videoEl.removeAttribute('src'); videoEl.load(); }
    if (loadingEl) loadingEl.style.display = 'none';
    if (modal) modal.style.display = 'none';
}

function playShortVideoDelta(delta) {
    const st = SV[svPlayerPlatform];
    if (!st.list.length) return;
    let next = st.curIndex + delta;
    if (next < 0) next = st.list.length - 1;
    if (next >= st.list.length) next = 0;
    openShortVideoPlayer(svPlayerPlatform, next);
}

function toggleShortVideoPlay() {
    const videoEl = document.getElementById('shortvideo-player-el');
    if (!videoEl) return;
    videoEl.paused ? videoEl.play() : videoEl.pause();
}

function deleteShortVideoFromPlayer() {
    const platform = svPlayerPlatform;
    const st = SV[platform];
    if (st.curIndex < 0 || st.curIndex >= st.list.length) return;
    const item = st.list[st.curIndex];
    if (!confirm('移至回收站？可以从系统回收站找回。')) return;
    fetch('/api/shortvideo/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, path: item.rel_path })
    }).then((r) => r.json()).then((res) => {
        if (res.status !== 'ok') { alert('删除失败'); return; }
        st.list.splice(st.curIndex, 1);
        st.total = Math.max(0, st.total - 1);
        const badge = svEl(platform, 'total-count-badge');
        if (badge) badge.textContent = `共 ${st.total} 条`;
        renderShortVideoGrid(platform, true);
        if (st.list.length === 0) { closeShortVideoPlayer(); return; }
        if (st.curIndex >= st.list.length) st.curIndex = 0;
        openShortVideoPlayer(platform, st.curIndex);
    }).catch(() => alert('删除失败'));
}

// 只挂一次：起播/有数据了就把"转码中"盖层收起来；失败了给个提示；进度条跟播放位置双向联动
(function setupShortVideoPlayerEvents() {
    const videoEl = document.getElementById('shortvideo-player-el');
    const seekEl = document.getElementById('shortvideo-seek');
    const timeEl = document.getElementById('shortvideo-time');
    const playBtn = document.getElementById('shortvideo-play-btn');
    if (!videoEl) return;
    let seeking = false;
    const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
    const hideLoading = () => {
        const el = document.getElementById('shortvideo-player-loading');
        if (el) el.style.display = 'none';
    };
    videoEl.addEventListener('playing', hideLoading);
    videoEl.addEventListener('loadeddata', hideLoading);
    videoEl.addEventListener('play', () => setIcon(playBtn, 'pause-fill'));
    videoEl.addEventListener('pause', () => setIcon(playBtn, 'play_arrow-fill'));
    videoEl.addEventListener('ended', () => {
        if (shortVideoLoopMode === 'single') {
            videoEl.currentTime = 0;
            videoEl.play().catch((e) => console.log('Autoplay policy:', e));
        } else {
            playShortVideoDelta(1);   // 列表循环自动连播
        }
    });
    videoEl.addEventListener('error', () => {
        hideLoading();
        const metaEl = document.getElementById('shortvideo-player-meta');
        if (metaEl) metaEl.textContent = '⚠️ 播放失败（转码出错，看 omni_deck.log）';
    });
    videoEl.addEventListener('timeupdate', () => {
        if (seeking || !videoEl.duration) return;
        if (seekEl) seekEl.value = Math.round((videoEl.currentTime / videoEl.duration) * 1000);
        if (timeEl) timeEl.textContent = `${fmt(videoEl.currentTime)} / ${fmt(videoEl.duration)}`;
    });
    if (seekEl) {
        seekEl.addEventListener('input', () => {
            seeking = true;
            if (videoEl.duration && timeEl) {
                timeEl.textContent = `${fmt((seekEl.value / 1000) * videoEl.duration)} / ${fmt(videoEl.duration)}`;
            }
        });
        seekEl.addEventListener('change', () => {
            if (videoEl.duration) videoEl.currentTime = (seekEl.value / 1000) * videoEl.duration;
            seeking = false;
        });
    }
})();

// 图集（抖音多图作品）查看器——跟视频播放器是两个独立弹窗，同一份 st.list 里混着
// 视频条目和图集条目，靠 item.kind 分流点开哪个。图集不用转码，直接原图 <img>。
let svGalleryPlatform = 'kuaishou';

let svGalleryImgIdx = 0;

function openShortVideoGallery(platform, index) {
    const st = SV[platform];
    if (index < 0 || index >= st.list.length) return;
    svGalleryPlatform = platform;
    st.curIndex = index;
    svGalleryImgIdx = 0;
    const modal = document.getElementById('shortvideo-gallery-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    renderGalleryImage();
}

function renderGalleryImage() {
    const st = SV[svGalleryPlatform];
    const item = st.list[st.curIndex];
    if (!item) return;
    const total = item.image_count || 1;
    if (svGalleryImgIdx < 0) svGalleryImgIdx = total - 1;
    if (svGalleryImgIdx >= total) svGalleryImgIdx = 0;
    const imgEl = document.getElementById('shortvideo-gallery-img');
    const titleEl = document.getElementById('shortvideo-gallery-title');
    const metaEl = document.getElementById('shortvideo-gallery-meta');
    const pageEl = document.getElementById('shortvideo-gallery-page');
    const galleryLikeBtn = document.getElementById('shortvideo-gallery-like-btn');
    if (galleryLikeBtn) {
        svSetLikeBtn(galleryLikeBtn, item.liked);
    }
    if (imgEl) imgEl.src = `/api/shortvideo/gallery_image?platform=${svGalleryPlatform}&path=${encodeURIComponent(item.rel_path)}&idx=${svGalleryImgIdx}`;
    if (titleEl) titleEl.textContent = item.title;
    if (metaEl) metaEl.textContent = `${item.folder} · ${item.mtime_str} · ${item.size_mb} MB`;
    if (pageEl) pageEl.textContent = `${svGalleryImgIdx + 1} / ${total}`;
}

function galleryImgDelta(delta) {
    svGalleryImgIdx += delta;
    renderGalleryImage();
}

// 上一条/下一条只在图集条目之间跳（这是图集查看器，混在列表里的视频条目跳过）
function galleryWorkDelta(delta) {
    const st = SV[svGalleryPlatform];
    if (!st.list.length) return;
    let next = st.curIndex;
    for (let tries = 0; tries < st.list.length; tries++) {
        next = (next + delta + st.list.length) % st.list.length;
        if (st.list[next] && st.list[next].kind === 'images') { openShortVideoGallery(svGalleryPlatform, next); return; }
    }
}

function closeShortVideoGallery() {
    const modal = document.getElementById('shortvideo-gallery-modal');
    if (modal) modal.style.display = 'none';
}

function deleteShortVideoGalleryFromViewer() {
    const platform = svGalleryPlatform;
    const st = SV[platform];
    if (st.curIndex < 0 || st.curIndex >= st.list.length) return;
    const item = st.list[st.curIndex];
    if (!confirm('移至回收站？可以从系统回收站找回。')) return;
    fetch('/api/shortvideo/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, path: item.rel_path })
    }).then((r) => r.json()).then((res) => {
        if (res.status !== 'ok') { alert('删除失败'); return; }
        st.list.splice(st.curIndex, 1);
        st.total = Math.max(0, st.total - 1);
        const badge = svEl(platform, 'total-count-badge');
        if (badge) badge.textContent = `共 ${st.total} 条`;
        renderShortVideoGrid(platform, true);
        if (!st.list.length) { closeShortVideoGallery(); return; }
        if (st.curIndex >= st.list.length) st.curIndex = 0;
        if (st.list[st.curIndex] && st.list[st.curIndex].kind === 'images') {
            openShortVideoGallery(platform, st.curIndex);
        } else {
            closeShortVideoGallery();
        }
    }).catch(() => alert('删除失败'));
}

function deleteShortVideoFile(platform, relPath) {
    if (!confirm('移至回收站？可以从系统回收站找回。')) return;
    fetch('/api/shortvideo/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, path: relPath })
    }).then(r => r.json()).then(res => {
        if (res.status === 'ok') {
            const st = SV[platform];
            st.list = st.list.filter(x => x.rel_path !== relPath);
            renderShortVideoGrid(platform, true);
            st.total = Math.max(0, st.total - 1);
            const badge = svEl(platform, 'total-count-badge');
            if (badge) badge.textContent = `共 ${st.total} 条`;
        } else {
            alert('删除失败');
        }
    }).catch(() => alert('删除失败'));
}

// 快手 / 抖音 / TikTok 三个分区都由本模块实现（manifest 里 module=shortvideo），按分区 id 区分平台
Omni.register('shortvideo', {
    // 离开 10 分钟没回来（app/shell.js）：网格只留第一页，后面翻出来的卡片和缩略图清掉；再往下滚从第 2 页接着拉
    trim(sectionId) {
        const platform = svPlatformFromTab(sectionId);
        const st = SV[platform];
        const grid = svEl(platform, 'grid');
        const keep = st.pageSize || 60;
        if (!grid || st.list.length <= keep) return;
        while (grid.children.length > keep) grid.lastElementChild.remove();
        st.list = st.list.slice(0, keep);
        st.page = 2;
        st.hasMore = st.total > keep;
    },
    activate(sectionId) {
        const activeMediaTab = sectionId;
        const subStats = document.getElementById('media-sub-stats');
        const svPlatform = svPlatformFromTab(activeMediaTab);
        const svSt = SV[svPlatform];
        const svLabel = SV_LABEL[svPlatform];
        if (svSt.total > 0) {
            document.getElementById('total-badge').textContent = `${svSt.total} 条 ${svLabel} 视频`;
            if (subStats) subStats.textContent = `共 ${svSt.total} 条 ${svLabel} 视频`;
            if (svSt.list.length > 0) renderShortVideoGrid(svPlatform, true);
        } else {
            document.getElementById('total-badge').textContent = `📱 ${svLabel}`;
            if (subStats) subStats.textContent = `正在扫描 ${(Omni.section(sectionId) || {}).dir_name || svPlatform}...`;
        }
        loadShortVideoLibrary(svPlatform, true);
    },
    onScrollEnd(sectionId) {
        const svPlatform = svPlatformFromTab(sectionId);
        const svSt = SV[svPlatform];
        if (!svSt.hasMore || svSt.loading) return;
        loadShortVideoLibrary(svPlatform, false);
    },
});
