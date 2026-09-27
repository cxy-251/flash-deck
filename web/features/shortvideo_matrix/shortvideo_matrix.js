// ================= 短视频多联放映 (shortvideo_matrix) =================
// 本机（嵌入视图里有 omniBridge）：交给 Python 的原生多路播放器（native_matrix_player.py），
// 这里只显示一个「重新打开」入口。其它浏览器：网页版，三个 <video> 槽位由 SLOT_TEMPLATE 生成。
// 布局 / 声音模式 / 各屏频道存在后端 /api/shortvideo_matrix/config，本机与网页版共用一份。

const MATRIX_SLOTS = 3;
const MATRIX_PAGE = 300;   // 频道视频分页取（抖音全部动辄两万多条），「随机」频道本身就只有一页
let matrixLayout = 3;
let matrixAudioMode = 'focus';
let matrixActiveSlot = 0;
let matrixWebReady = false;
const webSlots = Array.from({ length: MATRIX_SLOTS }, () => ({ channelId: 'random', total: 0, base: 0, page: [], cur: 0, singleLoop: false, skips: 0 }));

const SLOT_TEMPLATE = (i) => `
    <div class="matrix-web-slot" id="matrix-slot-${i}" onmouseenter="activateWebSlot(${i})" onclick="activateWebSlot(${i})">
        <div class="matrix-slot-header">
            <span class="matrix-slot-num">屏 ${i + 1}</span>
            <select id="matrix-select-${i}" class="matrix-channel-select" onchange="loadWebSlotChannel(${i}, this.value, true)"></select>
            <span id="matrix-count-${i}" class="matrix-slot-count">0/0</span>
        </div>
        <div class="matrix-video-wrapper">
            <video id="matrix-video-${i}" class="matrix-video-el" playsinline></video>
        </div>
        <div class="matrix-slot-meta"><span id="matrix-title-${i}" class="matrix-video-title">加载中…</span></div>
        <div class="matrix-slot-bar">
            <button class="matrix-tool-btn" onclick="stepWebSlot(${i}, -1)" title="上一条">⬅</button>
            <button class="matrix-tool-btn" id="matrix-play-btn-${i}" onclick="toggleWebSlotPlay(${i})" title="播放/暂停">⏸</button>
            <button class="matrix-tool-btn" onclick="stepWebSlot(${i}, 1)" title="下一条">➡</button>
            <button class="matrix-tool-btn" id="matrix-loop-btn-${i}" onclick="toggleWebSlotLoop(${i})" title="列表循环">🔁</button>
            <button class="matrix-tool-btn" id="matrix-mute-btn-${i}" onclick="toggleWebSlotMute(${i})" title="静音">🔊</button>
        </div>
    </div>`;

const matrixEl = (name, i) => document.getElementById(`matrix-${name}-${i}`);

function launchNativeMatrixPlayer() {
    if (window.omniBridge && typeof window.omniBridge.openMatrixPlayer === 'function') window.omniBridge.openMatrixPlayer();
}

// 原生放映点「退出」后 window.py 回调这里：停留在分区页，横幅上可以再次打开
window.onNativeMatrixClosed = function () {};

function initMatrixView() {
    const native = Boolean(window.omniBridge && typeof window.omniBridge.openMatrixPlayer === 'function');
    document.getElementById('matrix-native-banner').style.display = native ? 'flex' : 'none';
    document.getElementById('matrix-web-container').style.display = native ? 'none' : 'flex';
    if (native) {
        launchNativeMatrixPlayer();
    } else if (!matrixWebReady) {
        buildWebMatrix();
    } else {
        webSlots.forEach((_, i) => { if (i < matrixLayout && matrixEl('video', i).src) matrixEl('video', i).play().catch(() => {}); });
    }
}

async function buildWebMatrix() {
    matrixWebReady = true;
    const box = document.getElementById('matrix-web-slots');
    box.innerHTML = webSlots.map((_, i) => SLOT_TEMPLATE(i)).join('');
    setWebMatrixLayout(matrixLayout);
    setWebMatrixAudio(matrixAudioMode);
    webSlots.forEach((slot, i) => {
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
    });
    try {
        const [chRes, cfgRes] = await Promise.all([
            fetch('/api/shortvideo_matrix/channels').then(r => r.json()),
            fetch('/api/shortvideo_matrix/config').then(r => r.json()),
        ]);
        const channels = chRes.channels || [];
        const cfg = cfgRes.config || {};
        webSlots.forEach((slot, i) => {
            const want = ((cfg.slots || [])[i] || {}).channel_id;
            slot.channelId = channels.some(c => c.id === want) ? want : 'random';
            matrixEl('select', i).innerHTML = channels.map(c =>
                `<option value="${escapeHtml(c.id)}"${c.id === slot.channelId ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('');
        });
        setWebMatrixLayout(cfg.layout === 2 ? 2 : 3);
        setWebMatrixAudio(cfg.audio_mode === 'manual' ? 'manual' : 'focus');
        activateWebSlot(0);
        for (let i = 0; i < matrixLayout; i++) setTimeout(() => loadWebSlotChannel(i, webSlots[i].channelId), i * 200);
    } catch (e) {
        console.warn('[Matrix] 频道加载失败', e);
        matrixWebReady = false;
    }
}

function saveMatrixConfig() {
    fetch('/api/shortvideo_matrix/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout: matrixLayout, audio_mode: matrixAudioMode, slots: webSlots.map(s => ({ channel_id: s.channelId })) }),
    }).catch(() => {});
}

function fetchWebSlotPage(slot, offset) {
    const url = `/api/shortvideo_matrix/videos?channel_id=${encodeURIComponent(slot.channelId)}&offset=${offset}&limit=${MATRIX_PAGE}`;
    return fetch(url).then(r => r.json());
}

function loadWebSlotChannel(i, channelId, save) {
    const slot = webSlots[i];
    slot.channelId = channelId;
    if (save) saveMatrixConfig();
    fetchWebSlotPage(slot, 0)
        .then(res => {
            if (slot.channelId !== channelId) return;   // 等待期间又换了频道
            slot.total = res.total || 0;
            slot.base = 0;
            slot.page = res.videos || [];
            slot.cur = 0;
            slot.skips = 0;
            playWebSlot(i);
        })
        .catch(e => console.warn(`[Matrix] 屏 ${i + 1} 视频列表加载失败`, e));
}

function playWebSlot(i) {
    const slot = webSlots[i];
    const v = matrixEl('video', i);
    if (!slot.total) {
        v.pause();
        v.removeAttribute('src');
        v.load();
        matrixEl('title', i).textContent = '无视频';
        matrixEl('count', i).textContent = '0/0';
        return;
    }
    const inPage = slot.cur >= slot.base && slot.cur < slot.base + slot.page.length;
    if (!inPage) {   // 翻出了已取的那一页：取 cur 所在的那页再放
        const { channelId, cur } = slot;
        const base = Math.floor(cur / MATRIX_PAGE) * MATRIX_PAGE;
        fetchWebSlotPage(slot, base).then(res => {
            if (slot.channelId !== channelId || slot.cur !== cur) return;
            slot.base = base;
            slot.page = res.videos || [];
            if (slot.page.length) playWebSlot(i);
        }).catch(() => {});
        return;
    }
    const it = slot.page[slot.cur - slot.base];
    matrixEl('title', i).textContent = it.title;
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

function toggleWebSlotLoop(i) {
    const slot = webSlots[i];
    slot.singleLoop = !slot.singleLoop;
    const btn = matrixEl('loop-btn', i);
    btn.textContent = slot.singleLoop ? '🔂' : '🔁';
    btn.title = slot.singleLoop ? '单片循环' : '列表循环';
}

function setWebSlotMuted(i, muted) {
    matrixEl('video', i).muted = muted;
    matrixEl('mute-btn', i).textContent = muted ? '🔇' : '🔊';
}

function toggleWebSlotMute(i) {
    setWebSlotMuted(i, !matrixEl('video', i).muted);
}

function activateWebSlot(i) {
    if (i >= matrixLayout) return;
    matrixActiveSlot = i;
    webSlots.forEach((_, j) => matrixEl('slot', j).classList.toggle('active', j === i));
    applyWebMatrixAudio();
}

function applyWebMatrixAudio() {
    if (matrixAudioMode !== 'focus') return;
    webSlots.forEach((_, j) => setWebSlotMuted(j, j !== matrixActiveSlot));
}

function setWebMatrixLayout(cols, save) {
    matrixLayout = cols === 2 ? 2 : 3;
    document.getElementById('matrix-web-layout-2').classList.toggle('active', matrixLayout === 2);
    document.getElementById('matrix-web-layout-3').classList.toggle('active', matrixLayout === 3);
    const third = matrixEl('slot', 2);
    third.style.display = matrixLayout === 2 ? 'none' : 'flex';
    const v = matrixEl('video', 2);
    if (matrixLayout === 2) {
        v.pause();
        if (matrixActiveSlot === 2) activateWebSlot(0);
    } else if (save) {
        if (webSlots[2].total) v.play().catch(() => {}); else loadWebSlotChannel(2, webSlots[2].channelId);
    }
    if (save) saveMatrixConfig();
}

function setWebMatrixAudio(mode, save) {
    matrixAudioMode = mode === 'manual' ? 'manual' : 'focus';
    document.getElementById('matrix-web-audio-focus').classList.toggle('active', matrixAudioMode === 'focus');
    document.getElementById('matrix-web-audio-manual').classList.toggle('active', matrixAudioMode === 'manual');
    applyWebMatrixAudio();
    if (save) saveMatrixConfig();
}

function toggleWebMatrixAllPlay() {
    const vids = webSlots.slice(0, matrixLayout).map((_, i) => matrixEl('video', i));
    const anyPlaying = vids.some(v => !v.paused);
    vids.forEach(v => { if (anyPlaying) v.pause(); else if (v.getAttribute('src')) v.play().catch(() => {}); });
}

function randomWebMatrixAll() {
    webSlots.slice(0, matrixLayout).forEach((slot, i) => {
        if (!slot.total) return;
        slot.cur = Math.floor(Math.random() * slot.total);
        playWebSlot(i);
    });
}

Omni.register('shortvideo_matrix', {
    activate() {
        document.getElementById('total-badge').textContent = '多联放映';
        const subStats = document.getElementById('media-sub-stats');
        if (subStats) subStats.textContent = '2 / 3 屏并排 · 各屏独立选频道 · 焦点出声';
        initMatrixView();
    },
    deactivate() {
        if (window.omniBridge && typeof window.omniBridge.closeMatrixPlayer === 'function') window.omniBridge.closeMatrixPlayer();
        if (matrixWebReady) webSlots.forEach((_, i) => matrixEl('video', i).pause());
    },
});
