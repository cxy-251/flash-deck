// ================= 短视频多联放映 (shortvideo_matrix) =================
// 进分区先看到设置页（几屏、每屏频道/随机/静音），点「开始播放」才开播：
//   本机（嵌入视图里有 omniBridge）→ 设置写进后端配置，交给 Python 原生多路播放器（native_matrix_player.py）；
//   其它浏览器 → 网页版，三个 <video> 槽位由 SLOT_TEMPLATE 生成。
// 设置只有后端一份（/api/shortvideo_matrix/config），两边播放中改的也写回去，下次打开设置页就是最新的。

const MATRIX_SLOTS = 3;
const MATRIX_PAGE = 300;   // 频道视频分页取（抖音全部动辄两万多条）
let matrixChannels = null;
let matrixConfig = null;   // {layout, slots: [{channel_id, shuffle, muted}]}
let matrixWebPlaying = false;
let matrixActiveSlot = 0;
const webSlots = Array.from({ length: MATRIX_SLOTS }, () => ({ total: 0, base: 0, page: [], cur: 0, seed: 0, singleLoop: false, skips: 0 }));

const matrixEl = (name, i) => document.getElementById(`matrix-${name}-${i}`);
const matrixIsNative = () => Boolean(window.omniBridge && typeof window.omniBridge.openMatrixPlayer === 'function');
const matrixNewSeed = () => Math.floor(Math.random() * 1e9);

// 频道下拉的 <option>：按 group 分组；query 非空时只留名字里含它的（主播名 = 文件夹名），当前选中的那项始终保留
function matrixChannelOptions(selected, query) {
    const q = (query || '').trim().toLowerCase();
    const groups = {};
    for (const c of matrixChannels) {
        if (q && c.id !== selected && !c.label.toLowerCase().includes(q)) continue;
        (groups[c.group] = groups[c.group] || []).push(c);
    }
    return Object.entries(groups).map(([g, list]) => `<optgroup label="${escapeHtml(g)}">` + list.map(c =>
        `<option value="${escapeHtml(c.id)}"${c.id === selected ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('') + '</optgroup>').join('');
}

// 搜索框输入时重建旁边那个下拉；只剩一个匹配的主播就直接选上
function filterMatrixSelect(input, selectId, onPick) {
    const sel = document.getElementById(selectId);
    const current = sel.value;
    sel.innerHTML = matrixChannelOptions(current, input.value);
    const hits = [...sel.options].filter(o => o.value !== current);
    if (input.value.trim() && hits.length === 1) {
        sel.value = hits[0].value;
        onPick(sel.value);
    }
}

const SEARCH_BOX = (selectId, onPick) =>
    `<input class="matrix-channel-search" type="search" placeholder="🔍 主播" oninput="filterMatrixSelect(this, '${selectId}', ${onPick})" onclick="event.stopPropagation()">`;

// ---------------- 设置页 ----------------

async function showMatrixSetup() {
    document.getElementById('matrix-setup').style.display = 'flex';
    document.getElementById('matrix-web-container').style.display = 'none';
    try {
        const [ch, cfg] = await Promise.all([
            matrixChannels ? null : fetch('/api/shortvideo_matrix/channels').then(r => r.json()),
            fetch('/api/shortvideo_matrix/config').then(r => r.json()),
        ]);
        if (ch) matrixChannels = ch.channels || [];
        matrixConfig = cfg.config;
    } catch (e) {
        document.getElementById('matrix-setup-rows').textContent = '频道加载失败，稍后再切回这个分区试试';
        return;
    }
    renderMatrixSetup();
}

function renderMatrixSetup() {
    document.getElementById('matrix-setup-rows').innerHTML = matrixConfig.slots.map((s, i) => `
        <div class="matrix-setup-row" id="matrix-setup-row-${i}">
            <span class="matrix-slot-num">屏 ${i + 1}</span>
            ${SEARCH_BOX(`matrix-setup-select-${i}`, `v => matrixConfig.slots[${i}].channel_id = v`)}
            <select id="matrix-setup-select-${i}" class="matrix-channel-select" onchange="matrixConfig.slots[${i}].channel_id = this.value">${matrixChannelOptions(s.channel_id)}</select>
            <label><input type="checkbox" ${s.shuffle ? 'checked' : ''} onchange="matrixConfig.slots[${i}].shuffle = this.checked"> 🔀 随机</label>
            <label><input type="checkbox" ${s.muted ? 'checked' : ''} onchange="matrixConfig.slots[${i}].muted = this.checked"> 🔇 静音</label>
        </div>`).join('');
    setMatrixSetupLayout(matrixConfig.layout);
    document.getElementById('matrix-start-btn').disabled = false;
}

function setMatrixSetupLayout(n) {
    matrixConfig.layout = n === 2 ? 2 : 3;
    document.getElementById('matrix-setup-layout-2').classList.toggle('active', matrixConfig.layout === 2);
    document.getElementById('matrix-setup-layout-3').classList.toggle('active', matrixConfig.layout === 3);
    const third = document.getElementById('matrix-setup-row-2');
    if (third) third.classList.toggle('disabled', matrixConfig.layout === 2);
}

function saveMatrixConfig() {
    return fetch('/api/shortvideo_matrix/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(matrixConfig),
    }).catch(() => {});
}

async function startMatrix() {
    await saveMatrixConfig();
    if (matrixIsNative()) window.omniBridge.openMatrixPlayer();   // 原生播放器自己读配置
    else startWebMatrix();
}

// 原生放映点「退出」后 window.py 回调这里：回到设置页，读回播放中改过的设置
window.onNativeMatrixClosed = function () { showMatrixSetup(); };

// ---------------- 网页版播放 ----------------

const SLOT_TEMPLATE = (i) => `
    <div class="matrix-web-slot" id="matrix-slot-${i}" onclick="activateWebSlot(${i})">
        <div class="matrix-slot-header">
            <span class="matrix-slot-num">屏 ${i + 1}</span>
            ${SEARCH_BOX(`matrix-select-${i}`, `v => changeWebSlotChannel(${i}, v)`)}
            <select id="matrix-select-${i}" class="matrix-channel-select" onchange="changeWebSlotChannel(${i}, this.value)"></select>
            <span id="matrix-count-${i}" class="matrix-slot-count">0/0</span>
        </div>
        <div class="matrix-video-wrapper">
            <video id="matrix-video-${i}" class="matrix-video-el" playsinline></video>
        </div>
        <div class="matrix-slot-meta"><span id="matrix-title-${i}" class="matrix-video-title"></span></div>
        <div class="matrix-slot-bar">
            <button class="matrix-tool-btn" onclick="stepWebSlot(${i}, -1)" title="上一条">⬅</button>
            <button class="matrix-tool-btn" id="matrix-play-btn-${i}" onclick="toggleWebSlotPlay(${i})" title="播放/暂停">⏸</button>
            <button class="matrix-tool-btn" onclick="stepWebSlot(${i}, 1)" title="下一条">➡</button>
            <button class="matrix-tool-btn" id="matrix-shuffle-btn-${i}" onclick="toggleWebSlotShuffle(${i})" title="随机顺序">🔀</button>
            <button class="matrix-tool-btn" id="matrix-loop-btn-${i}" onclick="toggleWebSlotLoop(${i})" title="列表循环">🔁</button>
            <button class="matrix-tool-btn" id="matrix-mute-btn-${i}" onclick="toggleWebSlotMute(${i})" title="静音">🔊</button>
        </div>
    </div>`;

function startWebMatrix() {
    matrixWebPlaying = true;
    document.getElementById('matrix-setup').style.display = 'none';
    document.getElementById('matrix-web-container').style.display = 'flex';
    const box = document.getElementById('matrix-web-slots');
    box.innerHTML = webSlots.map((_, i) => SLOT_TEMPLATE(i)).join('');
    webSlots.forEach((slot, i) => {
        const cfg = matrixConfig.slots[i];
        const v = matrixEl('video', i);
        v.onended = () => slot.singleLoop ? (v.currentTime = 0, v.play().catch(() => {})) : stepWebSlot(i, 1);
        v.onplay = () => { matrixEl('play-btn', i).textContent = '⏸'; };
        v.onpause = () => { matrixEl('play-btn', i).textContent = '▶'; };
        v.onplaying = () => { slot.skips = 0; };
        // 放不了就跳下一条；连续 5 条都不行就停，别在坏列表上无限空转
        v.onerror = () => {
            if (!v.getAttribute('src')) return;
            if (++slot.skips > Math.min(5, slot.total)) { matrixEl('title', i).textContent = '连续多条无法播放，已停止'; return; }
            setTimeout(() => stepWebSlot(i, 1), 300);
        };
        matrixEl('select', i).innerHTML = matrixChannelOptions(cfg.channel_id);
        setWebSlotMuted(i, cfg.muted);
        matrixEl('shuffle-btn', i).classList.toggle('active', cfg.shuffle);
        slot.seed = matrixNewSeed();
    });
    setWebMatrixLayout(matrixConfig.layout);
    activateWebSlot(0);
    for (let i = 0; i < matrixConfig.layout; i++) setTimeout(() => loadWebSlotChannel(i), i * 200);
}

function stopWebMatrix() {
    matrixWebPlaying = false;
    webSlots.forEach((_, i) => { const v = matrixEl('video', i); if (v) { v.pause(); v.removeAttribute('src'); v.load(); } });
    showMatrixSetup();
}

function fetchWebSlotPage(i, offset) {
    const cfg = matrixConfig.slots[i];
    const seed = cfg.shuffle ? `&seed=${webSlots[i].seed}` : '';
    return fetch(`/api/shortvideo_matrix/videos?channel_id=${encodeURIComponent(cfg.channel_id)}&offset=${offset}&limit=${MATRIX_PAGE}${seed}`)
        .then(r => r.json());
}

function loadWebSlotChannel(i) {
    const slot = webSlots[i];
    const channelId = matrixConfig.slots[i].channel_id;
    fetchWebSlotPage(i, 0)
        .then(res => {
            if (matrixConfig.slots[i].channel_id !== channelId) return;   // 等待期间又换了频道
            Object.assign(slot, { total: res.total || 0, base: 0, page: res.videos || [], cur: 0, skips: 0 });
            playWebSlot(i);
        })
        .catch(e => console.warn(`[Matrix] 屏 ${i + 1} 视频列表加载失败`, e));
}

function changeWebSlotChannel(i, channelId) {
    matrixConfig.slots[i].channel_id = channelId;
    webSlots[i].seed = matrixNewSeed();
    saveMatrixConfig();
    loadWebSlotChannel(i);
}

function playWebSlot(i) {
    const slot = webSlots[i];
    const v = matrixEl('video', i);
    if (!slot.total) {
        v.pause();
        v.removeAttribute('src');
        v.load();
        matrixEl('title', i).textContent = '这个频道没有视频';
        matrixEl('count', i).textContent = '0/0';
        return;
    }
    const inPage = slot.cur >= slot.base && slot.cur < slot.base + slot.page.length;
    if (!inPage) {   // 翻出了已取的那一页：取 cur 所在的那页再放
        const { cur, seed } = slot;
        const base = Math.floor(cur / MATRIX_PAGE) * MATRIX_PAGE;
        fetchWebSlotPage(i, base).then(res => {
            if (slot.cur !== cur || slot.seed !== seed) return;
            slot.base = base;
            slot.page = res.videos || [];
            if (slot.page.length) playWebSlot(i);
        }).catch(() => {});
        return;
    }
    const it = slot.page[slot.cur - slot.base];
    matrixEl('title', i).textContent = it.title;
    matrixEl('title', i).title = it.title;
    matrixEl('count', i).textContent = `${slot.cur + 1}/${slot.total}`;
    v.src = it.stream_url;
    v.play().catch(() => {});
}

function stepWebSlot(i, delta) {
    const slot = webSlots[i];
    if (!slot.total) return;
    slot.cur = (slot.cur + delta + slot.total) % slot.total;
    playWebSlot(i);
}

function toggleWebSlotPlay(i) {
    const v = matrixEl('video', i);
    if (v.paused) v.play().catch(() => {}); else v.pause();
}

// 切随机/顺序：当前这条接着放，之后按新顺序从头走（换了 seed，已取的那页作废）
function toggleWebSlotShuffle(i) {
    const cfg = matrixConfig.slots[i];
    cfg.shuffle = !cfg.shuffle;
    matrixEl('shuffle-btn', i).classList.toggle('active', cfg.shuffle);
    Object.assign(webSlots[i], { seed: matrixNewSeed(), cur: -1, base: 0, page: [] });
    saveMatrixConfig();
}

function toggleWebSlotLoop(i) {
    const slot = webSlots[i];
    slot.singleLoop = !slot.singleLoop;
    const btn = matrixEl('loop-btn', i);
    btn.textContent = slot.singleLoop ? '🔂' : '🔁';
    btn.title = slot.singleLoop ? '单片循环' : '列表循环';
}

// 静音挂在 <video> 元素上，换 src 不会重置，下一条照样静音
function setWebSlotMuted(i, muted) {
    matrixEl('video', i).muted = muted;
    matrixEl('mute-btn', i).textContent = muted ? '🔇' : '🔊';
}

function toggleWebSlotMute(i) {
    const muted = !matrixEl('video', i).muted;
    setWebSlotMuted(i, muted);
    matrixConfig.slots[i].muted = muted;
    saveMatrixConfig();
}

function activateWebSlot(i) {
    if (i >= matrixConfig.layout) return;
    matrixActiveSlot = i;
    webSlots.forEach((_, j) => matrixEl('slot', j).classList.toggle('active', j === i));
}

function setWebMatrixLayout(cols, save) {
    matrixConfig.layout = cols === 2 ? 2 : 3;
    document.getElementById('matrix-web-layout-2').classList.toggle('active', matrixConfig.layout === 2);
    document.getElementById('matrix-web-layout-3').classList.toggle('active', matrixConfig.layout === 3);
    matrixEl('slot', 2).style.display = matrixConfig.layout === 2 ? 'none' : 'flex';
    const v = matrixEl('video', 2);
    if (matrixConfig.layout === 2) {
        v.pause();
        if (matrixActiveSlot === 2) activateWebSlot(0);
    } else if (save) {
        if (webSlots[2].total) v.play().catch(() => {}); else loadWebSlotChannel(2);
    }
    if (save) saveMatrixConfig();
}

function toggleWebMatrixAllPlay() {
    const vids = webSlots.slice(0, matrixConfig.layout).map((_, i) => matrixEl('video', i));
    const anyPlaying = vids.some(v => !v.paused);
    vids.forEach(v => { if (anyPlaying) v.pause(); else if (v.getAttribute('src')) v.play().catch(() => {}); });
}

Omni.register('shortvideo_matrix', {
    activate() {
        document.getElementById('total-badge').textContent = '多联放映';
        const subStats = document.getElementById('media-sub-stats');
        if (subStats) subStats.textContent = '2 / 3 屏并排 · 每屏独立选频道 / 随机 / 静音';
        if (matrixWebPlaying) {   // 网页版播到一半切走又切回来：接着放
            for (let i = 0; i < matrixConfig.layout; i++) if (matrixEl('video', i).getAttribute('src')) matrixEl('video', i).play().catch(() => {});
        } else {
            showMatrixSetup();
        }
    },
    deactivate() {
        if (window.omniBridge && typeof window.omniBridge.closeMatrixPlayer === 'function') window.omniBridge.closeMatrixPlayer();
        if (matrixWebPlaying) webSlots.forEach((_, i) => matrixEl('video', i).pause());
    },
});
