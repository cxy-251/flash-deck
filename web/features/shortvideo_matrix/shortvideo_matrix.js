// ================= 短视频多联放映 (shortvideo_matrix) =================
// 进分区先看到设置页（几屏、每屏频道/随机/静音），点「开始播放」才开播：
//   本机（嵌入视图里有 omniBridge）→ 设置写进后端配置，交给 Python 原生多路播放器（native_matrix_player.py）；
//   其它浏览器 → 网页版，三个 <video> 槽位由 SLOT_TEMPLATE 生成。
// 设置只有后端一份（/api/shortvideo_matrix/config），两边播放中改的也写回去，下次打开设置页就是最新的。
// 声音 = 手动静音 OR（焦点出声 且 不是焦点屏）：手动静音的屏永远不出声，焦点出声只在没静音的屏之间挑。
// 每屏的声音可换成「音声」分区的音频（🎬/🎧）：一个隐藏的 <audio>，跟视频各播各的；
// 这一屏听不到或视频被暂停时音声暂停，回来接着放。音声只选范围（全部 / 专辑），不挑单个文件。
// 同一次页面生命周期里：⤓ 收起 回到进多联之前的页面（去开游戏等），再点多联标签直接回到播放器；
// 各屏的频道/顺序/第几条/第几秒都记着，进来一律暂停（按 ⏯ 开播）；⚙ 回设置页，没改过的屏照样接着放。

const MATRIX_SLOTS = 3;
const MATRIX_PAGE = 300;   // 频道视频分页取（抖音全部动辄两万多条）
let matrixChannels = null;
let matrixAudioScopes = [];
let matrixAudioRates = [1];
let matrixConfig = null;   // {layout, focus_audio, slots: [{channel_id, shuffle, muted}]}
let matrixWebPlaying = false;
let matrixActiveSlot = 0;
let matrixSessionStarted = false;   // 这次页面里点过「开始播放」：再进分区直接回播放器
let matrixReturnTo = 'games';        // ⤓ 收起 回到哪：进多联之前的媒体标签，或游戏区
const webSlots = Array.from({ length: MATRIX_SLOTS }, () => ({ total: 0, base: 0, page: [], cur: 0, seed: 0, singleLoop: false, skips: 0,
    userPaused: false, tracks: [], aorder: [], apos: 0, askips: 0 }));

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
    return sc ? `📁 ${sc.label} (${sc.count})` : '📁 全部音声';
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
        if (ch) { matrixChannels = ch.channels || []; matrixAudioScopes = ch.audio_scopes || []; matrixAudioRates = ch.audio_rates || [1]; }
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
                <button id="matrix-setup-snd-video-${i}" class="matrix-tab-btn" onclick="setMatrixSetupSound(${i}, 'video')">🎬 原声</button>
                <button id="matrix-setup-snd-audio-${i}" class="matrix-tab-btn" onclick="setMatrixSetupSound(${i}, 'audio')">🎧 音声</button>
            </div>
            <span id="matrix-setup-audio-${i}" class="matrix-setup-audio">
                <button class="matrix-tab-btn matrix-scope-btn" id="matrix-setup-scope-${i}" onclick="cycleMatrixSetupScope(${i})" title="点击切到下一个专辑"></button>
                <button class="matrix-tab-btn" id="matrix-setup-ashuffle-${i}" onclick="toggleMatrixSetupAShuffle(${i})" title="音声随机顺序">🔀</button>
            </span>
        </div>`).join('');
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
    document.getElementById(`matrix-setup-scope-${i}`).textContent = matrixScopeLabel(s.audio_scope);
    document.getElementById(`matrix-setup-ashuffle-${i}`).classList.toggle('active', s.audio_shuffle);
}

function setMatrixSetupSound(i, sound) { matrixConfig.slots[i].sound = sound; updateMatrixSetupSound(i); }
function cycleMatrixSetupScope(i) { const s = matrixConfig.slots[i]; s.audio_scope = matrixNextScope(s.audio_scope); updateMatrixSetupSound(i); }
function toggleMatrixSetupAShuffle(i) { const s = matrixConfig.slots[i]; s.audio_shuffle = !s.audio_shuffle; updateMatrixSetupSound(i); }

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
        if (slot.asession !== `${cfg.audio_scope}|${cfg.audio_shuffle}`) { slot.tracks = []; slot.aresumeAt = 0; }
        if (cfg.sound === 'audio' && !slot.tracks.length) loadWebSlotTracks(i);
    });
    setWebMatrixLayout(matrixConfig.layout);
    document.getElementById('matrix-web-focus').classList.toggle('active', matrixConfig.focus_audio);
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
        if (a.getAttribute('src')) slot.aresumeAt = a.currentTime;
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
    $('matrix-bar-play').textContent = matrixEl('video', i).paused ? '▶' : '⏸';
    $('matrix-bar-shuffle').classList.toggle('active', cfg.shuffle);
    const it = currentWebVideo(i);
    $('matrix-bar-like').textContent = it && it.liked ? '❤️' : '🤍';
    $('matrix-bar-mute').textContent = cfg.muted ? '🔇' : '🔊';   // 顶栏显示的就是焦点屏，不存在「等焦点」
    const audio = cfg.sound === 'audio';
    $('matrix-bar-sound').textContent = audio ? '🎧' : '🎬';
    $('matrix-bar-sound').title = audio ? '声音：音声（点击换回视频原声）' : '声音：视频原声（点击换成音声）';
    $('matrix-bar-sound').classList.toggle('active', audio);
    $('matrix-bar-audio').style.display = audio ? 'flex' : 'none';
    if (audio) {
        $('matrix-bar-ashuffle').classList.toggle('active', cfg.audio_shuffle);
        $('matrix-bar-arate').textContent = `${cfg.audio_rate}x`;
        $('matrix-bar-arate').classList.toggle('active', cfg.audio_rate !== 1);
        $('matrix-bar-scope').textContent = matrixScopeLabel(cfg.audio_scope).replace(/ \(\d+\)$/, '');
        const tr = slot.tracks.length && matrixEl('audio', i).getAttribute('src') ? slot.tracks[slot.aorder[slot.apos]] : null;
        $('matrix-bar-scope').title = `范围：${matrixScopeLabel(cfg.audio_scope)}` + (tr ? `\n正在放：${tr.title}` : '') + '\n点击切到下一个专辑';
        $('matrix-bar-aseek').title = tr ? tr.title : '';
        updateWebAudioProgress(i);
    }
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

const fmtMatrixTime = (t) => { t = Math.floor(t || 0); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
let matrixASeeking = false;

function bindWebSlotAudio(i) {
    const slot = webSlots[i], a = matrixEl('audio', i);
    a.onended = () => astepWebSlot(i, 1, false);
    a.onplaying = () => { slot.askips = 0; };
    a.onerror = () => {
        if (!a.getAttribute('src')) return;
        if (++slot.askips > Math.min(5, slot.tracks.length)) return;
        setTimeout(() => astepWebSlot(i, 1, false), 300);
    };
    a.ontimeupdate = () => { if (i === matrixActiveSlot) updateWebAudioProgress(i); };
}

function updateWebAudioProgress(i) {
    const a = matrixEl('audio', i), seek = document.getElementById('matrix-bar-aseek');
    document.getElementById('matrix-bar-atime').textContent = fmtMatrixTime(a.currentTime);
    if (!matrixASeeking) seek.value = a.duration ? Math.round(a.currentTime / a.duration * 1000) : 0;
}

function barASeek(value, done) {
    matrixASeeking = !done;
    const a = matrixEl('audio', barSlot());
    if (done && a.duration) a.currentTime = value / 1000 * a.duration;
}

function loadWebSlotTracks(i) {
    const slot = webSlots[i], scope = matrixConfig.slots[i].audio_scope, a = matrixEl('audio', i);
    a.pause();
    a.removeAttribute('src');
    fetch(`/api/shortvideo_matrix/audio?scope=${encodeURIComponent(scope)}`).then(r => r.json()).then(res => {
        if (matrixConfig.slots[i].audio_scope !== scope) return;
        slot.tracks = res.tracks || [];
        slot.asession = `${scope}|${matrixConfig.slots[i].audio_shuffle}`;
        slot.aresumeAt = 0;
        makeWebSlotAOrder(i);
        slot.apos = 0;
        slot.askips = 0;
        applyWebMatrixAudio();
    }).catch(e => console.warn(`[Matrix] 屏 ${i + 1} 音声列表加载失败`, e));
}

function makeWebSlotAOrder(i) {
    const slot = webSlots[i];
    slot.aorder = slot.tracks.map((_, k) => k);
    if (matrixConfig.slots[i].audio_shuffle) {
        for (let k = slot.aorder.length - 1; k > 0; k--) {
            const j = Math.floor(Math.random() * (k + 1));
            [slot.aorder[k], slot.aorder[j]] = [slot.aorder[j], slot.aorder[k]];
        }
    }
}

function loadWebSlotTrack(i) {
    const slot = webSlots[i], a = matrixEl('audio', i);
    a.src = slot.tracks[slot.aorder[slot.apos]].stream_url;
    applyWebSlotRate(i);   // 换 src 会把 playbackRate 重置成 defaultPlaybackRate，两个都设
    const at = slot.aresumeAt;
    slot.aresumeAt = 0;
    if (at) a.addEventListener('loadedmetadata', () => { a.currentTime = at; }, { once: true });
}

function applyWebSlotRate(i) {
    const a = matrixEl('audio', i), rate = matrixConfig.slots[i].audio_rate || 1;
    a.defaultPlaybackRate = rate;
    a.playbackRate = rate;
}

// 音声倍速：按档位循环切（视频不调速）
function barCycleRate() {
    const i = barSlot(), cfg = matrixConfig.slots[i], rates = matrixAudioRates;
    const k = rates.indexOf(cfg.audio_rate);
    cfg.audio_rate = rates[(k + 1) % rates.length];
    applyWebSlotRate(i);
    refreshWebBar();
    saveMatrixConfig();
}

function astepWebSlot(i, delta, manual = true) {
    const slot = webSlots[i];
    if (!slot.tracks.length) return;
    if (manual) slot.askips = 0;
    slot.apos = (slot.apos + delta + slot.tracks.length) % slot.tracks.length;
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

// 切随机/顺序：当前这段接着放，只重排后面的
function barToggleAShuffle() {
    const i = barSlot(), cfg = matrixConfig.slots[i], slot = webSlots[i];
    cfg.audio_shuffle = !cfg.audio_shuffle;
    if (slot.tracks.length) {
        const current = slot.aorder[slot.apos];
        makeWebSlotAOrder(i);
        slot.apos = slot.aorder.indexOf(current);
    }
    slot.asession = `${cfg.audio_scope}|${cfg.audio_shuffle}`;
    refreshWebBar();
    saveMatrixConfig();
}

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
