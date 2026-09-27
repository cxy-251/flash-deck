// ================= 短视频多联放映 (shortvideo_matrix) =================
// 进分区先看到设置页（几屏、每屏频道/随机/静音），点「开始播放」才开播：
//   本机（嵌入视图里有 omniBridge）→ 设置写进后端配置，交给 Python 原生多路播放器（native_matrix_player.py）；
//   其它浏览器 → 网页版，三个 <video> 槽位由 SLOT_TEMPLATE 生成。
// 设置只有后端一份（/api/shortvideo_matrix/config），两边播放中改的也写回去，下次打开设置页就是最新的。
// 声音 = 手动静音 OR（焦点出声 且 不是焦点屏）：手动静音的屏永远不出声，焦点出声只在没静音的屏之间挑。
// 每屏的声音可换成「音声」分区的音频（原声 / 音声 切换）：一个隐藏的 <audio>，跟视频各播各的；
// 这一屏听不到或视频被暂停时音声暂停，回来接着放。音声只选范围（全部 / 专辑），不挑单个文件；
// 控件功能跟网页音声专区一样，档位（AUDIO_SPEEDS / SLEEP_TIMER_MINS / AUDIO_SKIP）和断点续听
// （fetchAudioProgress / saveAudioProgress）直接用 audio.js 里统一的那份。
// 同一次页面生命周期里：⤓ 收起 回到进多联之前的页面（去开游戏等），再点多联标签直接回到播放器；
// 各屏的频道/顺序/第几条/第几秒都记着，进来一律暂停（按 ⏯ 开播）；⚙ 回设置页，没改过的屏照样接着放。

const MATRIX_SLOTS = 3;
const MATRIX_PAGE = 300;   // 频道视频分页取（抖音全部动辄两万多条）
let matrixChannels = null;
let matrixAudioScopes = [];
let matrixConfig = null;   // {layout, focus_audio, slots: [{channel_id, shuffle, muted}]}
let matrixWebPlaying = false;
let matrixActiveSlot = 0;
let matrixSessionStarted = false;   // 这次页面里点过「开始播放」：再进分区直接回播放器
let matrixReturnTo = 'games';        // ⤓ 收起 回到哪：进多联之前的媒体标签，或游戏区
const webSlots = Array.from({ length: MATRIX_SLOTS }, () => ({ total: 0, base: 0, page: [], cur: 0, seed: 0, singleLoop: false, skips: 0,
    userPaused: false, tracks: [], tracksScope: null, apos: 0, askips: 0, asavedAt: 0 }));
const MATRIX_AUDIO_MODES = { list: ['repeat', '列表循环'], single: ['repeat_one', '单曲循环'], random: ['shuffle', '随机播放'] };

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

function matrixScopeLabel(id) {
    const sc = matrixAudioScopes.find(x => x.id === id) || matrixAudioScopes[0];
    return sc ? `${sc.label} (${sc.count})` : '全部音声';
}

function matrixNextScope(id) {
    const ids = matrixAudioScopes.map(x => x.id);
    return ids.length ? ids[(ids.indexOf(id) + 1) % ids.length] : 'all';
}

// ---------------- 设置页 ----------------

async function showMatrixSetup() {
    document.getElementById('matrix-setup').style.display = 'flex';
    document.getElementById('matrix-web-container').style.display = 'none';
    try {
        const [ch, cfg] = await Promise.all([
            matrixChannels ? null : fetch('/api/shortvideo_matrix/channels').then(r => r.json()),
            fetch('/api/shortvideo_matrix/config').then(r => r.json()),
        ]);
        if (ch) { matrixChannels = ch.channels || []; matrixAudioScopes = ch.audio_scopes || []; }
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
            <div class="matrix-btn-group">
                <button id="matrix-setup-snd-video-${i}" class="matrix-tab-btn" onclick="setMatrixSetupSound(${i}, 'video')" data-icon="movie-fill" data-icon-text="原声"></button>
                <button id="matrix-setup-snd-audio-${i}" class="matrix-tab-btn" onclick="setMatrixSetupSound(${i}, 'audio')" data-icon="headphones-fill" data-icon-text="音声"></button>
            </div>
            <span id="matrix-setup-audio-${i}" class="matrix-setup-audio">
                <button class="matrix-tab-btn matrix-scope-btn" id="matrix-setup-scope-${i}" onclick="cycleMatrixSetupScope(${i})" title="点击切到下一个专辑"></button>
                <button class="matrix-tab-btn" id="matrix-setup-amode-${i}" onclick="cycleMatrixSetupAMode(${i})"></button>
            </span>
        </div>`).join('');
    hydrateIcons(document.getElementById('matrix-setup-rows'));
    matrixConfig.slots.forEach((_, i) => updateMatrixSetupSound(i));
    setMatrixSetupLayout(matrixConfig.layout);
    document.getElementById('matrix-setup-focus').checked = matrixConfig.focus_audio;
    document.getElementById('matrix-start-btn').disabled = false;
}

function updateMatrixSetupSound(i) {
    const s = matrixConfig.slots[i];
    document.getElementById(`matrix-setup-snd-video-${i}`).classList.toggle('active', s.sound !== 'audio');
    document.getElementById(`matrix-setup-snd-audio-${i}`).classList.toggle('active', s.sound === 'audio');
    document.getElementById(`matrix-setup-audio-${i}`).style.display = s.sound === 'audio' ? 'flex' : 'none';
    setIcon(document.getElementById(`matrix-setup-scope-${i}`), 'library_music', matrixScopeLabel(s.audio_scope));
    const [modeIcon, name] = MATRIX_AUDIO_MODES[s.audio_mode] || MATRIX_AUDIO_MODES.list;
    const modeBtn = document.getElementById(`matrix-setup-amode-${i}`);
    setIcon(modeBtn, modeIcon, name);
    modeBtn.title = '音声播放模式（点击切换）';
}

function setMatrixSetupSound(i, sound) { matrixConfig.slots[i].sound = sound; updateMatrixSetupSound(i); }
function cycleMatrixSetupScope(i) { const s = matrixConfig.slots[i]; s.audio_scope = matrixNextScope(s.audio_scope); updateMatrixSetupSound(i); }
function matrixNextAudioMode(m) { const ks = Object.keys(MATRIX_AUDIO_MODES); return ks[(ks.indexOf(m) + 1) % ks.length]; }
function cycleMatrixSetupAMode(i) { const s = matrixConfig.slots[i]; s.audio_mode = matrixNextAudioMode(s.audio_mode); updateMatrixSetupSound(i); }

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
    matrixSessionStarted = true;
    await saveMatrixConfig();
    if (matrixIsNative()) window.omniBridge.openMatrixPlayer();   // 原生播放器自己读配置
    else startWebMatrix();
}

// 回到进多联之前的页面
function leaveMatrix() {
    if (matrixReturnTo === 'games' || !document.getElementById(`media-tab-${matrixReturnTo}`)) switchToGamesSection();
    else switchMediaTab(matrixReturnTo, document.getElementById(`media-tab-${matrixReturnTo}`));
}

// 原生放映退出后 window.py 回调这里：settings → 设置页（读回播放中改过的设置）；collapse → 回去
window.onNativeMatrixClosed = function (reason) {
    if (reason === 'settings') showMatrixSetup();
    else leaveMatrix();
};

// ---------------- 网页版播放 ----------------
// 每屏只有画面 + 底部细进度线；顶栏一套控件，操作的永远是焦点屏（matrixActiveSlot）。
// 焦点：点击立即；鼠标停留 MATRIX_HOVER_MS 才换（去点顶栏时斜着划过别的屏不算）。

const MATRIX_HOVER_MS = 300;
let matrixHoverTimer = 0;

const SLOT_TEMPLATE = (i) => `
    <div class="matrix-web-slot" id="matrix-slot-${i}" onmouseenter="hoverWebSlot(${i})" onmouseleave="clearTimeout(matrixHoverTimer)" onclick="activateWebSlot(${i})">
        <div class="matrix-video-wrapper">
            <video id="matrix-video-${i}" class="matrix-video-el" playsinline></video>
        </div>
        <div class="matrix-slot-progress"><div id="matrix-progress-${i}"></div></div>
        <audio id="matrix-audio-${i}" preload="none"></audio>
    </div>`;

function hoverWebSlot(i) {
    clearTimeout(matrixHoverTimer);
    matrixHoverTimer = setTimeout(() => activateWebSlot(i), MATRIX_HOVER_MS);
}

function startWebMatrix() {
    matrixWebPlaying = true;
    document.getElementById('matrix-setup').style.display = 'none';
    document.getElementById('matrix-web-container').style.display = 'flex';
    document.getElementById('matrix-web-slots').innerHTML = webSlots.map((_, i) => SLOT_TEMPLATE(i)).join('');
    document.getElementById('matrix-bar-select').innerHTML = matrixChannelOptions(null);
    webSlots.forEach((slot, i) => {
        const v = matrixEl('video', i);
        v.onended = () => stepWebSlot(i, 1);
        v.onplay = v.onpause = () => { if (i === matrixActiveSlot) refreshWebBar(); };
        v.onplaying = () => { slot.skips = 0; if (matrixConfig.slots[i].sound === 'audio') applyWebMatrixAudio(); };
        v.ontimeupdate = () => { if (v.duration) matrixEl('progress', i).style.width = `${v.currentTime / v.duration * 100}%`; };
        // 扫描时没拿到宽高的，等浏览器解出尺寸再判：横屏就跳过（不算坏片）
        v.onloadedmetadata = () => { if (slot.checkOrientation && v.videoWidth > v.videoHeight) stepWebSlot(i, 1); };
        // 放不了就跳下一条；连续 5 条都不行就停，别在坏列表上无限空转
        v.onerror = () => {
            if (!v.getAttribute('src')) return;
            if (++slot.skips > Math.min(5, slot.total)) { v.title = '连续多条无法播放，已停止'; return; }
            setTimeout(() => stepWebSlot(i, 1), 300);
        };
        const cfg = matrixConfig.slots[i];
        slot.userPaused = true;      // 进来一律暂停，按 ⏯ 开播
        bindWebSlotAudio(i);
        if (slot.session !== `${cfg.channel_id}|${cfg.shuffle}`) { slot.total = 0; slot.seed = matrixNewSeed(); }
        if (slot.tracksScope !== cfg.audio_scope) slot.tracks = [];   // 设置页改过音声范围：重新取
        if (cfg.sound === 'audio' && !slot.tracks.length) loadWebSlotTracks(i);
    });
    setWebMatrixLayout(matrixConfig.layout);
    document.getElementById('matrix-web-focus').classList.toggle('active', matrixConfig.focus_audio);
    document.getElementById('matrix-bar-pin').classList.toggle('active', !!matrixConfig.bar_pinned);
    showWebMatrixBar(3000);   // 进来先亮 3 秒，让人知道控件在上面
    matrixActiveSlot = -1;
    activateWebSlot(0);
    for (let i = 0; i < matrixConfig.layout; i++) setTimeout(() => resumeOrLoadWebSlot(i), i * 200);
}

// 列表还是按同样设置取的（⚙ 回设置页没改这一屏）就接着上次的位置，否则重新取
function resumeOrLoadWebSlot(i) {
    if (webSlots[i].total) playWebSlot(i, webSlots[i].resumeAt || 0);
    else loadWebSlotChannel(i);
}

// ⚙ 回设置页：记下各屏位置再释放
function stopWebMatrix() {
    matrixWebPlaying = false;
    webSlots.forEach((slot, i) => {
        const v = matrixEl('video', i), a = matrixEl('audio', i);
        if (!v) return;
        slot.resumeAt = v.currentTime;
        saveWebSlotAudioProgress(i);   // 音声进度存服务器（跟音声专区共用）
        for (const el of [v, a]) { el.pause(); el.removeAttribute('src'); el.load(); }
    });
    showMatrixSetup();
}

// ⤓ 收起：全部暂停（状态都留着），回到进多联之前的页面
function collapseWebMatrix() {
    for (let i = 0; i < MATRIX_SLOTS; i++) if (matrixEl('video', i)) setWebSlotPaused(i, true);
    leaveMatrix();
}

// ---- 顶栏：显示焦点屏的状态 ----
function refreshWebBar() {
    const i = matrixActiveSlot, cfg = matrixConfig.slots[i], slot = webSlots[i];
    if (!cfg) return;
    const $ = (id) => document.getElementById(id);
    $('matrix-bar-tag').textContent = `屏${i + 1}`;
    const sel = $('matrix-bar-select');
    if (sel.value !== cfg.channel_id) sel.innerHTML = matrixChannelOptions(cfg.channel_id, $('matrix-bar-search').value);
    setIcon($('matrix-bar-play'), matrixEl('video', i).paused ? 'play_arrow-fill' : 'pause-fill');
    $('matrix-bar-shuffle').classList.toggle('active', cfg.shuffle);
    const it = currentWebVideo(i);
    const liked = !!(it && it.liked);
    setIcon($('matrix-bar-like'), liked ? 'favorite-fill' : 'favorite');
    $('matrix-bar-like').classList.toggle('liked', liked);
    setIcon($('matrix-bar-mute'), cfg.muted ? 'volume_off-fill' : 'volume_up-fill');   // 顶栏显示的就是焦点屏，不存在「等焦点」
    $('matrix-bar-mute').classList.toggle('danger', cfg.muted);
    const audio = cfg.sound === 'audio';
    setIcon($('matrix-bar-sound'), audio ? 'headphones-fill' : 'movie-fill');
    $('matrix-bar-sound').title = audio ? '声音：音声（点击换回视频原声）' : '声音：视频原声（点击换成音声）';
    $('matrix-bar-sound').classList.toggle('active', audio);
    $('matrix-bar-audio').style.display = audio ? 'flex' : 'none';
    if (audio) refreshWebAudioBar(i);
}

function currentWebVideo(i) {
    const slot = webSlots[i];
    return slot.total && slot.cur >= slot.base && slot.cur < slot.base + slot.page.length ? slot.page[slot.cur - slot.base] : null;
}

// 顶栏按钮 → 焦点屏
const barSlot = () => matrixActiveSlot;
function barStep(d) { stepWebSlot(barSlot(), d); }
function barTogglePlay() { const i = barSlot(); setWebSlotPaused(i, !matrixEl('video', i).paused); }
function barChannel(id) { changeWebSlotChannel(barSlot(), id); }

function barToggleLike() {
    const i = barSlot(), it = currentWebVideo(i);
    if (!it) return;
    const liked = !it.liked;
    fetch('/api/shortvideo/like', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: it.platform, path: it.rel_path, liked }),
    }).then(r => { if (r.ok) { it.liked = liked; refreshWebBar(); } }).catch(() => {});
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
            Object.assign(slot, { total: res.total || 0, base: 0, page: res.videos || [], cur: 0, skips: 0,
                                  session: `${channelId}|${matrixConfig.slots[i].shuffle}` });
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

function playWebSlot(i, startAt = 0) {
    const slot = webSlots[i];
    const v = matrixEl('video', i);
    if (!slot.total) {
        v.pause();
        v.removeAttribute('src');
        v.load();
        v.title = '这个频道没有视频';
        if (i === matrixActiveSlot) refreshWebBar();
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
            if (slot.page.length) playWebSlot(i, startAt);
        }).catch(() => {});
        return;
    }
    const it = slot.page[slot.cur - slot.base];
    v.title = `${it.folder}\n${it.title}`;
    slot.checkOrientation = !it.width;
    v.src = it.stream_url;
    if (startAt) v.addEventListener('loadedmetadata', () => { v.currentTime = startAt; }, { once: true });
    if (!slot.userPaused) v.play().catch(() => {});
    if (i === matrixActiveSlot) refreshWebBar();
}

function stepWebSlot(i, delta) {
    const slot = webSlots[i];
    if (!slot.total) return;
    slot.cur = (slot.cur + delta + slot.total) % slot.total;
    playWebSlot(i);
}

// 暂停/继续这一屏：视频和音声一起
function setWebSlotPaused(i, paused) {
    const v = matrixEl('video', i);
    webSlots[i].userPaused = paused;
    if (paused) v.pause(); else if (v.getAttribute('src')) v.play().catch(() => {});
    applyWebMatrixAudio();
}

// 切随机/顺序：当前这条接着放，之后按新顺序从头走（换了 seed，已取的那页作废）
function barToggleShuffle() {
    const i = barSlot(), cfg = matrixConfig.slots[i];
    cfg.shuffle = !cfg.shuffle;
    Object.assign(webSlots[i], { seed: matrixNewSeed(), cur: -1, base: 0, page: [], session: `${cfg.channel_id}|${cfg.shuffle}` });
    saveMatrixConfig();
    refreshWebBar();
}

// 静音挂在 <video> 元素上，换 src 不会重置，下一条照样静音。
// 用音声的屏：视频一直静音，音声按「听得到 且 没暂停」放 / 停。
function applyWebMatrixAudio() {
    webSlots.forEach((slot, i) => {
        const v = matrixEl('video', i), a = matrixEl('audio', i);
        if (!v) return;
        const cfg = matrixConfig.slots[i];
        const heard = !cfg.muted && !(matrixConfig.focus_audio && i !== matrixActiveSlot) && i < matrixConfig.layout;
        if (cfg.sound === 'audio') {
            v.muted = true;
            if (heard && !slot.userPaused && v.getAttribute('src') && slot.tracks.length) {
                if (!a.getAttribute('src')) loadWebSlotTrack(i);
                a.play().catch(() => {});
            } else {
                a.pause();
            }
        } else {
            v.muted = !heard;
            a.pause();
        }
    });
    refreshWebBar();
}

function barToggleMute() {
    const cfg = matrixConfig.slots[barSlot()];
    cfg.muted = !cfg.muted;
    applyWebMatrixAudio();
    saveMatrixConfig();
}

function toggleWebMatrixFocus() {
    matrixConfig.focus_audio = !matrixConfig.focus_audio;
    document.getElementById('matrix-web-focus').classList.toggle('active', matrixConfig.focus_audio);
    applyWebMatrixAudio();
    saveMatrixConfig();
}

function activateWebSlot(i) {
    clearTimeout(matrixHoverTimer);
    if (i >= matrixConfig.layout || i === matrixActiveSlot) return;
    matrixActiveSlot = i;
    webSlots.forEach((_, j) => matrixEl('slot', j).classList.toggle('active', j === i));
    document.getElementById('matrix-bar-search').value = '';
    applyWebMatrixAudio();
}

// ---------------- 音声（代替视频原声） ----------------
// 跟网页音声专区同样的功能：上/下一首、快退快进、列表/单曲/随机、倍速、定时、章节、进度与总长、
// 断点续听（服务器）、移到回收站。列表是这一屏的「范围」，按自然顺序；随机模式下一首随机挑。

const fmtMatrixTime = (t) => (typeof formatAudioTime === 'function' ? formatAudioTime(t || 0) : `${Math.floor((t || 0) / 60)}:${String(Math.floor(t || 0) % 60).padStart(2, '0')}`);
let matrixASeeking = false;
let matrixSleepTimer = 0, matrixSleepIdx = 0, matrixSleepEnd = 0;

const currentWebTrack = (i) => {
    const slot = webSlots[i];
    return slot.tracks.length && matrixEl('audio', i) && matrixEl('audio', i).getAttribute('src') ? slot.tracks[slot.apos] : null;
};

function bindWebSlotAudio(i) {
    const slot = webSlots[i], a = matrixEl('audio', i);
    a.onended = () => {
        const tr = currentWebTrack(i);
        if (tr) saveAudioProgress(tr, a.duration || 0, a.duration || 0);   // 听完：清掉续听记录
        if (matrixConfig.slots[i].audio_mode === 'single') { a.currentTime = 0; a.play().catch(() => {}); }
        else astepWebSlot(i, 1, false);
    };
    a.onplaying = () => { slot.askips = 0; };
    a.onpause = () => { if (!a.ended) saveWebSlotAudioProgress(i); };
    a.onerror = () => {
        if (!a.getAttribute('src')) return;
        if (++slot.askips > Math.min(5, slot.tracks.length)) return;
        setTimeout(() => astepWebSlot(i, 1, false), 300);
    };
    a.ontimeupdate = () => {
        if (Date.now() - slot.asavedAt > 10000 && !a.paused) saveWebSlotAudioProgress(i);
        if (i === matrixActiveSlot) updateWebAudioProgress(i);
    };
    a.ondurationchange = () => { if (i === matrixActiveSlot) updateWebAudioProgress(i); };
}

function saveWebSlotAudioProgress(i) {
    const tr = currentWebTrack(i), a = matrixEl('audio', i);
    if (!tr || !a) return;
    webSlots[i].asavedAt = Date.now();
    saveAudioProgress(tr, a.currentTime, a.duration);
}

function refreshWebAudioBar(i) {
    const $ = (id) => document.getElementById(id), cfg = matrixConfig.slots[i], tr = currentWebTrack(i);
    const [modeIcon, name] = MATRIX_AUDIO_MODES[cfg.audio_mode] || MATRIX_AUDIO_MODES.list;
    setIcon($('matrix-bar-amode'), modeIcon);
    $('matrix-bar-amode').classList.toggle('active', cfg.audio_mode !== 'list');
    $('matrix-bar-amode').title = `播放模式：${name}（点击切换）`;
    $('matrix-bar-arate').textContent = `${cfg.audio_rate}x`;
    $('matrix-bar-arate').classList.toggle('active', cfg.audio_rate !== 1);
    setIcon($('matrix-bar-scope'), 'library_music', matrixScopeLabel(cfg.audio_scope).replace(/ \(\d+\)$/, ''));
    $('matrix-bar-scope').title = `音声范围：${matrixScopeLabel(cfg.audio_scope)}\n点击切到下一个专辑`;
    const title = tr ? tr.title : (webSlots[i].tracks.length ? '' : '这个范围没有音声');
    $('matrix-bar-atitle').textContent = title;
    $('matrix-bar-atitle').title = tr ? `${tr.album} / ${tr.title}` : title;
    const chapters = (tr && tr.chapters) || [];
    const chSel = $('matrix-bar-chapter');
    chSel.style.display = chapters.length ? '' : 'none';
    if (chSel.dataset.track !== (tr && tr.rel_path)) {
        chSel.dataset.track = tr ? tr.rel_path : '';
        chSel.innerHTML = '<option value="">📑 章节</option>' + chapters.map((c, k) =>
            `<option value="${c.start || 0}">${escapeHtml(c.title || `第${k + 1}章`)}</option>`).join('');
    }
    updateWebAudioProgress(i);
}

function updateWebAudioProgress(i) {
    const a = matrixEl('audio', i), seek = document.getElementById('matrix-bar-aseek');
    if (!a) return;
    document.getElementById('matrix-bar-atime').textContent = `${fmtMatrixTime(a.currentTime)} / ${fmtMatrixTime(a.duration)}`;
    if (!matrixASeeking) seek.value = a.duration ? Math.round(a.currentTime / a.duration * 1000) : 0;
}

function barASeek(value, done) {
    matrixASeeking = !done;
    const a = matrixEl('audio', barSlot());
    if (done && a.duration) a.currentTime = value / 1000 * a.duration;
}

function barASkip(dir) {
    const a = matrixEl('audio', barSlot());
    if (a.duration) a.currentTime = Math.max(0, Math.min(a.duration - 0.5, a.currentTime + dir * (dir < 0 ? AUDIO_SKIP.back : AUDIO_SKIP.fwd)));
}

function barAChapter(start) {
    if (start === '') return;
    matrixEl('audio', barSlot()).currentTime = parseFloat(start);
    document.getElementById('matrix-bar-chapter').value = '';
}

function loadWebSlotTracks(i) {
    const slot = webSlots[i], scope = matrixConfig.slots[i].audio_scope, a = matrixEl('audio', i);
    saveWebSlotAudioProgress(i);
    a.pause();
    a.removeAttribute('src');
    fetch(`/api/shortvideo_matrix/audio?scope=${encodeURIComponent(scope)}`).then(r => r.json()).then(res => {
        if (matrixConfig.slots[i].audio_scope !== scope) return;
        slot.tracks = res.tracks || [];
        slot.tracksScope = scope;
        slot.apos = slot.tracks.length && matrixConfig.slots[i].audio_mode === 'random' ? Math.floor(Math.random() * slot.tracks.length) : 0;
        slot.askips = 0;
        applyWebMatrixAudio();
    }).catch(e => console.warn(`[Matrix] 屏 ${i + 1} 音声列表加载失败`, e));
}

// 载入当前这段：续听位置从服务器取（跟音声专区共用）
function loadWebSlotTrack(i) {
    const slot = webSlots[i], a = matrixEl('audio', i), tr = slot.tracks[slot.apos];
    a.src = tr.stream_url;
    applyWebSlotRate(i);   // 换 src 会把 playbackRate 重置成 defaultPlaybackRate，两个都设
    fetchAudioProgress(tr).then(pos => {
        if (pos <= 0 || slot.tracks[slot.apos] !== tr) return;
        const go = () => { if (pos < (a.duration || Infinity) - 5) a.currentTime = pos; };
        if (a.readyState >= 1) go(); else a.addEventListener('loadedmetadata', go, { once: true });
    });
    if (i === matrixActiveSlot) refreshWebAudioBar(i);
}

function applyWebSlotRate(i) {
    const a = matrixEl('audio', i), rate = matrixConfig.slots[i].audio_rate || 1;
    a.defaultPlaybackRate = rate;
    a.playbackRate = rate;
}

function barCycleRate() {
    const i = barSlot(), cfg = matrixConfig.slots[i], rates = AUDIO_SPEEDS;
    cfg.audio_rate = rates[(rates.indexOf(cfg.audio_rate) + 1) % rates.length];
    applyWebSlotRate(i);
    refreshWebBar();
    saveMatrixConfig();
}

function barCycleAMode() {
    const cfg = matrixConfig.slots[barSlot()];
    cfg.audio_mode = matrixNextAudioMode(cfg.audio_mode);
    refreshWebBar();
    saveMatrixConfig();
}

// 下一首按播放模式挑（跟音声专区一样）：随机 → 随机一段；其它 → 按列表顺序
function astepWebSlot(i, delta, manual = true) {
    const slot = webSlots[i], n = slot.tracks.length;
    if (!n) return;
    if (manual) slot.askips = 0;
    saveWebSlotAudioProgress(i);
    if (delta > 0 && matrixConfig.slots[i].audio_mode === 'random' && n > 1) {
        let k;
        do { k = Math.floor(Math.random() * n); } while (k === slot.apos);
        slot.apos = k;
    } else {
        slot.apos = (slot.apos + delta + n) % n;
    }
    loadWebSlotTrack(i);
    applyWebMatrixAudio();
}

function barToggleSound() {
    const i = barSlot(), cfg = matrixConfig.slots[i];
    cfg.sound = cfg.sound === 'audio' ? 'video' : 'audio';
    if (cfg.sound === 'audio' && !webSlots[i].tracks.length) loadWebSlotTracks(i);
    applyWebMatrixAudio();
    saveMatrixConfig();
}

function barCycleScope() {
    const i = barSlot(), cfg = matrixConfig.slots[i];
    cfg.audio_scope = matrixNextScope(cfg.audio_scope);
    loadWebSlotTracks(i);
    refreshWebBar();
    saveMatrixConfig();
}

// 定时关闭：到点全部暂停（多联里跟音声专区一样按档位循环）
function barCycleSleep() {
    const mins = SLEEP_TIMER_MINS;
    matrixSleepIdx = (matrixSleepIdx + 1) % mins.length;
    clearTimeout(matrixSleepTimer);
    matrixSleepEnd = 0;
    if (mins[matrixSleepIdx] > 0) {
        matrixSleepEnd = Date.now() + mins[matrixSleepIdx] * 60000;
        matrixSleepTimer = setTimeout(() => {
            matrixSleepIdx = 0;
            matrixSleepEnd = 0;
            for (let k = 0; k < matrixConfig.layout; k++) setWebSlotPaused(k, true);
            updateWebSleepBtn();
        }, mins[matrixSleepIdx] * 60000);
    }
    updateWebSleepBtn();
}

function updateWebSleepBtn() {
    const btn = document.getElementById('matrix-bar-sleep');
    const left = matrixSleepEnd ? Math.ceil((matrixSleepEnd - Date.now()) / 60000) : 0;
    setIcon(btn, left ? 'bedtime-fill' : 'bedtime', left || '');
    btn.title = left ? `定时关闭：还剩 ${left} 分钟（点击切下一档）` : '定时关闭：关（点击切下一档）';
    btn.classList.toggle('active', !!left);
}
setInterval(() => { if (matrixSleepEnd) updateWebSleepBtn(); }, 60000);

function barDeleteTrack() {
    const i = barSlot(), slot = webSlots[i], tr = currentWebTrack(i);
    document.getElementById('matrix-bar-more').open = false;
    if (!tr || !confirm(`确定将音声《${tr.title}》移至回收站吗？`)) return;
    fetch('/api/audio/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: tr.rel_path, is_nsfw: !!tr.is_nsfw }),
    }).then(r => r.json()).then(res => {
        if (res.status !== 'ok') return;
        const a = matrixEl('audio', i);
        a.pause();
        a.removeAttribute('src');
        slot.tracks.splice(slot.apos, 1);
        if (slot.tracks.length) slot.apos %= slot.tracks.length;
        applyWebMatrixAudio();
    }).catch(() => {});
}

// ---------------- 顶栏自动隐藏 ----------------
// 进来先亮 3 秒；之后鼠标移到播放区最顶端（或点「▾」把手）才出来，离开 1.5 秒收起；
// 下拉 / 搜索框 / ⋯ 菜单正在用时不收。📌 固定后一直显示（存配置，本机原生版共用这个设置）。

let matrixBarHideTimer = 0;

function setWebMatrixBarVisible(on) {
    document.getElementById('matrix-web-topbar').classList.toggle('bar-hidden', !on);
    document.getElementById('matrix-web-container').classList.toggle('bar-collapsed', !on);
}

function showWebMatrixBar(lingerMs) {
    clearTimeout(matrixBarHideTimer);
    setWebMatrixBarVisible(true);
    if (lingerMs) scheduleWebMatrixBarHide(lingerMs);
}

function webMatrixBarBusy() {
    const a = document.activeElement;
    const typing = a && a.id === 'matrix-bar-search' && a.value;
    const menuOpen = document.getElementById('matrix-bar-more').open;
    return typing || menuOpen || (a && a.tagName === 'SELECT' && a.closest('#matrix-web-topbar'));
}

function scheduleWebMatrixBarHide(ms = 1500) {
    clearTimeout(matrixBarHideTimer);
    if (matrixConfig && matrixConfig.bar_pinned) return;
    matrixBarHideTimer = setTimeout(() => {
        if (matrixConfig.bar_pinned) return;
        if (webMatrixBarBusy()) { scheduleWebMatrixBarHide(); return; }
        setWebMatrixBarVisible(false);
    }, ms);
}

function toggleWebMatrixBarPin() {
    matrixConfig.bar_pinned = !matrixConfig.bar_pinned;
    document.getElementById('matrix-bar-pin').classList.toggle('active', matrixConfig.bar_pinned);
    if (matrixConfig.bar_pinned) showWebMatrixBar(); else scheduleWebMatrixBarHide();
    saveMatrixConfig();
}

// 鼠标到了播放区最顶端几像素就叫出顶栏
document.addEventListener('mousemove', (e) => {
    if (!matrixWebPlaying) return;
    const box = document.getElementById('matrix-web-container');
    const r = box.getBoundingClientRect();
    if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top - 4 && e.clientY <= r.top + 8) showWebMatrixBar();
});

// ---------------- 布局 / 全局 ----------------

function setWebMatrixLayout(cols, save) {
    matrixConfig.layout = cols === 2 ? 2 : 3;
    document.getElementById('matrix-web-layout-2').classList.toggle('active', matrixConfig.layout === 2);
    document.getElementById('matrix-web-layout-3').classList.toggle('active', matrixConfig.layout === 3);
    matrixEl('slot', 2).style.display = matrixConfig.layout === 2 ? 'none' : 'flex';
    const v = matrixEl('video', 2);
    if (matrixConfig.layout === 2) {
        v.pause();
        matrixEl('audio', 2).pause();
        if (matrixActiveSlot === 2) activateWebSlot(0);
    } else if (save) {
        if (webSlots[2].total) { if (!webSlots[2].userPaused) v.play().catch(() => {}); } else loadWebSlotChannel(2);
    }
    if (save) { applyWebMatrixAudio(); saveMatrixConfig(); }
}

function toggleWebMatrixAllPlay() {
    const n = matrixConfig.layout;
    const anyPlaying = webSlots.slice(0, n).some((_, i) => !matrixEl('video', i).paused);
    for (let i = 0; i < n; i++) setWebSlotPaused(i, anyPlaying);
}

Omni.register('shortvideo_matrix', {
    activate() {
        if (typeof loadAudioPlayerSpec === 'function') loadAudioPlayerSpec();   // 倍速 / 定时档位（跟音声专区同一份）
        document.getElementById('total-badge').textContent = '多联放映';
        const subStats = document.getElementById('media-sub-stats');
        if (subStats) subStats.textContent = '2 / 3 屏并排 · 顶栏控制焦点屏 · 焦点出声 · 音声可代替原声';
        if (typeof mediaTabCameFrom !== 'undefined' && mediaTabCameFrom && mediaTabCameFrom !== 'shortvideo-matrix') {
            matrixReturnTo = mediaTabCameFrom;
        }
        if (matrixWebPlaying) {
            // 网页版收起 / 切走又回来：各屏停在原处（暂停），按 ⏯ 接着放
            for (let i = 0; i < MATRIX_SLOTS; i++) webSlots[i].userPaused = true;
            applyWebMatrixAudio();
            showWebMatrixBar(3000);
        } else if (matrixSessionStarted && matrixIsNative()) {
            showMatrixSetup();                    // 垫在原生播放器下面，收起时不至于露出空白
            window.omniBridge.openMatrixPlayer(); // 原生播放器按记住的位置恢复、暂停
        } else {
            showMatrixSetup();
        }
    },
    deactivate() {
        if (window.omniBridge && typeof window.omniBridge.closeMatrixPlayer === 'function') window.omniBridge.closeMatrixPlayer();
        if (matrixWebPlaying) for (let i = 0; i < MATRIX_SLOTS; i++) setWebSlotPaused(i, true);
    },
});
