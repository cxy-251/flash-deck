// 局域网小工具：文件传输 + 消息板。后端 omni/features/tools/（协议说明见 service.py 开头）。
//
// 上传：一个文件一个任务，排队一个个传；每块 file.slice() 发给 POST /api/tools/uploads/<id>?offset=N。
// 断网 / 超时：退避重试，重试前先问服务器真实收到了多少（半块也算），从那里接着发。
// 页面刷新后浏览器不保留选过的文件——重新选同一个文件，服务器按 名字+大小+修改时间 认出来，返回断点。

const TX = {
    files: [],
    selected: new Set(),
    tasks: [],          // {id, file, name, size, offset, state: queued|uploading|retrying|done|failed|canceled, error, speed, upId}
    running: false,
    chunk: 8 * 1024 * 1024,
    client: Math.random().toString(36).slice(2, 12),   // 这个页面的标识：SSE 事件带回来，自己发的不弹提示
    loaded: false,
};

function txFmtBytes(n) {
    if (n >= 1 << 30) return (n / (1 << 30)).toFixed(2) + ' GB';
    if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB';
    if (n >= 1 << 10) return (n / (1 << 10)).toFixed(0) + ' KB';
    return n + ' B';
}

function txFmtTime(t) {
    const d = new Date(t * 1000), now = new Date();
    const hm = d.toTimeString().slice(0, 5);
    return d.toDateString() === now.toDateString() ? hm : `${d.getMonth() + 1}-${d.getDate()} ${hm}`;
}

function txToken() {
    try { return localStorage.getItem('omni_nsfw_token') || ''; } catch (e) { return ''; }
}

// 下载链接走 <a href>，带不了请求头：广域网下把解锁 token 拼进 URL
function txWithToken(url) {
    const t = txToken();
    return t ? url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t) : url;
}

function txDeviceName() {
    let n = '';
    try { n = localStorage.getItem('omni_tx_device') || ''; } catch (e) {}
    if (n) return n;
    const ua = navigator.userAgent;
    if (/iPhone/.test(ua)) return 'iPhone';
    if (/iPad/.test(ua)) return 'iPad';
    if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android 手机' : 'Android 平板 / 电视';
    if (/QtWebEngine/.test(ua)) return 'Steam Deck';
    if (/Windows/.test(ua)) return 'Windows 电脑';
    if (/Mac OS/.test(ua)) return 'Mac';
    return '浏览器';
}

function txRenameDevice() {
    const n = prompt('这台设备在消息板里显示的名字', txDeviceName());
    if (n === null) return;
    try { localStorage.setItem('omni_tx_device', n.trim().slice(0, 40)); } catch (e) {}
    document.getElementById('tx-device-name').textContent = txDeviceName();
}

// 复制：localhost / https 才有 navigator.clipboard；局域网 http 页面走 textarea + execCommand 兜底
function txCopy(text, onDone) {
    const done = onDone || (() => showMegaToast('已复制'));
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(() => txCopyFallback(text, done));
    } else {
        txCopyFallback(text, done);
    }
}

function txCopyFallback(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    ta.remove();
    if (ok) done();
    else prompt('浏览器不让自动复制，长按下面的内容手动复制：', text);
}

function txLocked(res) {
    const locked = res.status === 403;
    document.getElementById('tx-locked').style.display = locked ? '' : 'none';
    return locked;
}

// ---------------------------------------------------------------- 共享文件夹

function txLoadFiles() {
    return fetch('/api/tools/files?t=' + Date.now())
        .then(r => { if (txLocked(r)) throw new Error('locked'); return r.json(); })
        .then(d => {
            TX.files = d.files || [];
            TX.chunk = d.chunk || TX.chunk;
            const names = new Set(TX.files.map(f => f.name));
            TX.selected.forEach(n => { if (!names.has(n)) TX.selected.delete(n); });
            document.querySelectorAll('#media-tools-view .tx-local-only').forEach(el => { el.style.display = d.dir ? '' : 'none'; });
            if (d.dir) document.getElementById('tx-dir').textContent = '📍 ' + d.dir;
            txRenderFiles();
            txRenderPending(d.uploads || []);
            txUpdateBadge();
        })
        .catch(() => {});
}

function txUpdateBadge() {
    if (activeMediaTab !== 'tools') return;
    document.getElementById('total-badge').textContent = `${TX.files.length} 个共享文件`;
    const sub = document.getElementById('media-sub-stats');
    if (sub) sub.textContent = '局域网传文件 / 传文字';
}

function txRenderFiles() {
    const box = document.getElementById('tx-files');
    document.getElementById('tx-file-count').textContent = `（${TX.files.length}）`;
    if (!TX.files.length) {
        box.innerHTML = '<div class="tx-empty">共享文件夹是空的。传个文件进来，或直接把文件拷进上面这个目录。</div>';
    } else {
        box.innerHTML = TX.files.map(f => {
            const url = txWithToken('/api/tools/files/' + encodeURIComponent(f.name));
            return `<div class="tx-row">
                <label class="tx-check"><input type="checkbox" ${TX.selected.has(f.name) ? 'checked' : ''}
                    onchange="txToggleSelect('${escapeAttr(f.name)}', this.checked)"></label>
                <div class="tx-row-main">
                    <a class="tx-name" href="${url}" download="${escapeHtml(f.name)}" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</a>
                    <div class="tx-dim">${txFmtBytes(f.size)} · ${txFmtTime(f.mtime)}</div>
                </div>
                <a class="tx-icon-btn" href="${url}" download="${escapeHtml(f.name)}" title="下载">⬇️</a>
                <button class="tx-icon-btn" title="移到回收站" onclick="txDeleteFiles(['${escapeAttr(f.name)}'])">🗑</button>
            </div>`;
        }).join('');
    }
    txUpdateSelectionUI();
}

function txToggleSelect(name, on) {
    if (on) TX.selected.add(name); else TX.selected.delete(name);
    txUpdateSelectionUI();
}

function txSelectAll(on) {
    TX.selected = new Set(on ? TX.files.map(f => f.name) : []);
    txRenderFiles();
}

function txUpdateSelectionUI() {
    const n = TX.selected.size;
    document.getElementById('tx-zip-btn').disabled = !n;
    document.getElementById('tx-del-btn').disabled = !n;
    document.getElementById('tx-zip-btn').textContent = n > 1 ? `⬇️ 打包下载（${n}）` : '⬇️ 下载所选';
    document.getElementById('tx-del-btn').textContent = n ? `🗑 删除所选（${n}）` : '🗑 删除所选';
    const all = document.getElementById('tx-select-all');
    all.checked = n > 0 && n === TX.files.length;
}

function txDownloadSelected() {
    const names = [...TX.selected];
    if (!names.length) return;
    const a = document.createElement('a');
    if (names.length === 1) {
        a.href = txWithToken('/api/tools/files/' + encodeURIComponent(names[0]));
        a.download = names[0];
    } else {
        a.href = txWithToken('/api/tools/zip?' + names.map(n => 'name=' + encodeURIComponent(n)).join('&'));
    }
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function txDeleteSelected() {
    txDeleteFiles([...TX.selected]);
}

function txDeleteFiles(names) {
    if (!names.length) return;
    const what = names.length === 1 ? `「${names[0]}」` : `这 ${names.length} 个文件`;
    if (!confirm(`把${what}移到回收站？（Deck 的回收站里能找回）`)) return;
    fetch('/api/tools/files/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names }),
    }).then(r => r.json()).then(d => {
        const n = (d.deleted || []).length;
        showMegaToast(n === names.length ? `已移到回收站（${n}）` : `只删掉了 ${n} / ${names.length} 个`, n !== names.length);
        names.forEach(x => TX.selected.delete(x));
        txLoadFiles();
    }).catch(() => showMegaToast('删除失败', true));
}

function txOpenFolder() {
    fetch('/api/tools/open-folder', { method: 'POST' });
}

// ---------------------------------------------------------------- 上传

function txPickFiles(input) {
    const files = [...(input.files || [])];
    input.value = '';
    txEnqueue(files);
}

function txEnqueue(files) {
    for (const file of files) {
        TX.tasks.push({ id: Math.random().toString(36).slice(2), file, name: file.name, size: file.size,
                        offset: 0, state: 'queued', error: '', speed: 0, upId: null });
    }
    txRenderTasks();
    txRunQueue();
}

async function txRunQueue() {
    if (TX.running) return;
    TX.running = true;
    try {
        let task;
        while ((task = TX.tasks.find(t => t.state === 'queued'))) {
            await txUpload(task);
            txRenderTasks();
        }
    } finally {
        TX.running = false;
    }
}

function txApi(method, url, body) {
    return fetch(url, {
        method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined,
    }).then(async r => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok && r.status !== 409) throw Object.assign(new Error(d.error || ('HTTP ' + r.status)), { status: r.status });
        return d;
    });
}

// 一块：用 XHR 才拿得到块内进度（大块在慢网上也能看到进度条在走）
function txSendChunk(task, offset, blob) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        task.xhr = xhr;
        xhr.open('POST', `/api/tools/uploads/${task.upId}?offset=${offset}`);
        const t = txToken();
        if (t) xhr.setRequestHeader('X-Omni-Token', t);
        xhr.timeout = 120000;
        const started = performance.now();
        xhr.upload.onprogress = e => {
            task.offset = offset + e.loaded;
            const secs = (performance.now() - started) / 1000;
            if (secs > 0.3) task.speed = e.loaded / secs;
            txRenderTaskProgress(task);
        };
        xhr.onload = () => {
            let d = {};
            try { d = JSON.parse(xhr.responseText); } catch (e) {}
            if (xhr.status === 200 || xhr.status === 409) resolve(d);
            else reject(Object.assign(new Error(d.error || ('HTTP ' + xhr.status)), { status: xhr.status }));
        };
        xhr.onerror = () => reject(new Error('网络中断'));
        xhr.ontimeout = () => reject(new Error('超时'));
        xhr.onabort = () => reject(Object.assign(new Error('已取消'), { canceled: true }));
        xhr.send(blob);
    });
}

async function txUpload(task) {
    task.state = 'uploading';
    task.error = '';
    txRenderTasks();
    let fails = 0;
    try {
        const up = await txApi('POST', '/api/tools/uploads', { name: task.name, size: task.size, mtime: task.file.lastModified || 0, client: TX.client });
        task.upId = up.id;
        task.offset = up.offset || 0;
        const chunk = up.chunk || TX.chunk;
        if (task.size === 0) { task.state = 'done'; return; }   // 空文件：服务器建的时候就收尾了
        if (task.offset >= task.size) {
            // 服务器那边已经收满（上次最后一块刚发完就断了）：发一个空块让它收尾
            await txSendChunk(task, task.offset, new Blob([]));
        }
        while (task.offset < task.size) {
            if (task.state === 'canceled') return;
            try {
                const start = task.offset;
                const d = await txSendChunk(task, start, task.file.slice(start, start + chunk));
                task.offset = d.offset;
                fails = 0;
                if (task.state === 'retrying') task.state = 'uploading';
                if (d.done) { task.state = 'done'; break; }
            } catch (e) {
                if (e.canceled || task.state === 'canceled') return;
                if (e.status === 404 || e.status === 403 || e.status === 400) throw e;
                fails += 1;
                if (fails > 30) throw new Error('重试多次仍失败：' + e.message);
                task.state = 'retrying';
                task.error = `${e.message}，${Math.min(30, 2 ** fails)} 秒后重试（第 ${fails} 次）`;
                txRenderTasks();
                await new Promise(r => setTimeout(r, Math.min(30, 2 ** fails) * 1000));
                // 先问服务器真实进度：断开前那一块可能收到了一半
                try { const s = await txApi('GET', `/api/tools/uploads/${task.upId}`); task.offset = s.offset; }
                catch (e2) { if (e2.status === 404) throw new Error('服务器上找不到这个上传了（可能已被放弃）'); }
                task.error = '';
            }
        }
        if (task.offset >= task.size && task.state !== 'done') {
            // 最后一块发完了但回应丢了：服务器那边多半已经收尾，问一下
            const s = await txApi('GET', `/api/tools/uploads/${task.upId}`).catch(e => e.status === 404 ? null : Promise.reject(e));
            if (s === null) task.state = 'done';
            else await txSendChunk(task, s.offset, new Blob([])).then(d => { if (d.done) task.state = 'done'; });
        }
    } catch (e) {
        if (task.state !== 'canceled') { task.state = 'failed'; task.error = e.message; }
    } finally {
        task.xhr = null;
    }
}

function txCancelTask(id) {
    const task = TX.tasks.find(t => t.id === id);
    if (!task) return;
    const was = task.state;
    task.state = 'canceled';
    if (task.xhr) task.xhr.abort();
    // 传了一部分的，问一下要不要把服务器上的半截也丢掉；不丢的话以后重新选这个文件还能接着传
    if (task.upId && was !== 'done' && task.offset > 0 &&
        confirm(`「${task.name}」已传 ${txFmtBytes(task.offset)}。把服务器上这半截也丢掉吗？\n（选「取消」则保留，之后重新选这个文件能接着传）`)) {
        txApi('DELETE', `/api/tools/uploads/${task.upId}`).then(txLoadFiles).catch(() => {});
    } else {
        txLoadFiles();
    }
    txRenderTasks();
}

function txRetryTask(id) {
    const task = TX.tasks.find(t => t.id === id);
    if (!task) return;
    task.state = 'queued';
    txRenderTasks();
    txRunQueue();
}

function txClearDoneTasks() {
    TX.tasks = TX.tasks.filter(t => !['done', 'canceled'].includes(t.state));
    txRenderTasks();
}

const TX_STATE_LABEL = { queued: '排队中', uploading: '上传中', retrying: '重连中', done: '完成', failed: '失败', canceled: '已取消' };

function txRenderTasks() {
    const box = document.getElementById('tx-tasks');
    if (!box) return;
    if (!TX.tasks.length) { box.innerHTML = ''; return; }
    const finished = TX.tasks.some(t => ['done', 'canceled'].includes(t.state));
    box.innerHTML = TX.tasks.map(t => {
        const active = ['queued', 'uploading', 'retrying'].includes(t.state);
        const btn = active ? `<button class="tx-icon-btn" title="取消" onclick="txCancelTask('${t.id}')">✕</button>`
                  : t.state === 'failed' ? `<button class="tx-btn" onclick="txRetryTask('${t.id}')">重试</button>` : '';
        return `<div class="tx-row tx-task tx-state-${t.state}" id="tx-task-${t.id}">
            <div class="tx-row-main">
                <div class="tx-name">${escapeHtml(t.name)}</div>
                <div class="tx-bar"><div class="tx-bar-fill" style="width:${t.size ? (t.offset / t.size * 100).toFixed(1) : 100}%"></div></div>
                <div class="tx-dim tx-task-info">${txTaskInfo(t)}</div>
            </div>
            ${btn}
        </div>`;
    }).join('') + (finished ? '<div class="tx-clear-done"><button class="tx-btn" onclick="txClearDoneTasks()">清除已完成</button></div>' : '');
}

function txTaskInfo(t) {
    const pct = t.size ? Math.floor(t.offset / t.size * 100) : 100;
    let s = `${TX_STATE_LABEL[t.state]} · ${txFmtBytes(t.offset)} / ${txFmtBytes(t.size)}（${pct}%）`;
    if (t.state === 'uploading' && t.speed > 0) {
        const eta = (t.size - t.offset) / t.speed;
        s += ` · ${txFmtBytes(t.speed)}/s · 剩 ${eta >= 60 ? Math.ceil(eta / 60) + ' 分钟' : Math.ceil(eta) + ' 秒'}`;
    }
    if (t.error) s += ` · ${escapeHtml(t.error)}`;
    return s;
}

// 进度回调很密：只改这一行的进度条和文字，不重画整个列表
function txRenderTaskProgress(t) {
    const row = document.getElementById('tx-task-' + t.id);
    if (!row) return;
    row.querySelector('.tx-bar-fill').style.width = (t.size ? t.offset / t.size * 100 : 100).toFixed(1) + '%';
    row.querySelector('.tx-task-info').innerHTML = txTaskInfo(t);
}

function txRenderPending(uploads) {
    // 本页正在传的不算「没传完」
    const mine = new Set(TX.tasks.filter(t => t.upId && t.state !== 'canceled').map(t => t.upId));
    const list = uploads.filter(u => !mine.has(u.id));
    document.getElementById('tx-pending-box').style.display = list.length ? '' : 'none';
    document.getElementById('tx-pending').innerHTML = list.map(u => `<div class="tx-row">
        <div class="tx-row-main">
            <div class="tx-name">${escapeHtml(u.name)}</div>
            <div class="tx-bar"><div class="tx-bar-fill" style="width:${u.size ? (u.offset / u.size * 100).toFixed(1) : 0}%"></div></div>
            <div class="tx-dim">${txFmtBytes(u.offset)} / ${txFmtBytes(u.size)} · ${txFmtTime(u.created)} 开始</div>
        </div>
        <button class="tx-btn" onclick="document.getElementById('tx-file-input').click()">选文件续传</button>
        <button class="tx-icon-btn" title="丢掉这半截（移到回收站）" onclick="txDiscardPending('${u.id}', '${escapeAttr(u.name)}')">🗑</button>
    </div>`).join('');
}

function txDiscardPending(id, name) {
    if (!confirm(`丢掉「${name}」没传完的部分？（移到回收站）`)) return;
    txApi('DELETE', `/api/tools/uploads/${id}`).then(txLoadFiles).catch(() => showMegaToast('操作失败', true));
}

function txInitDrop() {
    const drop = document.getElementById('tx-drop');
    if (!drop || drop.dataset.ready) return;
    drop.dataset.ready = '1';
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', e => {
        e.preventDefault();
        drop.classList.remove('over');
        txEnqueue([...(e.dataTransfer.files || [])]);
    });
}

// 关页面 / 刷新时还有在传的：提醒一下（刷新后要重新选文件才能续传）
window.addEventListener('beforeunload', e => {
    if (TX.tasks.some(t => ['uploading', 'retrying', 'queued'].includes(t.state))) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// ---------------------------------------------------------------- 消息板

function txLoadTexts() {
    return fetch('/api/tools/texts?t=' + Date.now())
        .then(r => { if (txLocked(r)) throw new Error('locked'); return r.json(); })
        .then(d => txRenderTexts(d.texts || []))
        .catch(() => {});
}

function txLinkify(text) {
    return escapeHtml(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function txRenderTexts(items) {
    TX.texts = items;
    const box = document.getElementById('tx-texts');
    document.getElementById('tx-text-count').textContent = items.length ? `（${items.length}）` : '';
    if (!items.length) {
        box.innerHTML = '<div class="tx-empty">暂无分享内容。发出去的文字 / 链接所有设备实时可见，一键复制；记录会一直保留。</div>';
        return;
    }
    box.innerHTML = items.map(t => `<div class="tx-row tx-msg">
        <div class="tx-row-main">
            <div class="tx-msg-text">${txLinkify(t.text)}</div>
            <div class="tx-dim">${escapeHtml(t.from || '')}${t.from ? ' · ' : ''}${txFmtTime(t.time)}</div>
        </div>
        <button class="tx-btn" id="tx-copy-${t.id}" onclick="txCopyText('${t.id}')">复制</button>
        <button class="tx-btn tx-text-del" onclick="txDeleteText('${t.id}')">删除</button>
    </div>`).join('');
}

function txCopyText(id) {
    const t = (TX.texts || []).find(x => x.id === id);
    if (!t) return;
    txCopy(t.text, () => {
        const b = document.getElementById('tx-copy-' + id);
        if (!b) return;
        b.textContent = '已复制';
        setTimeout(() => { b.textContent = '复制'; }, 1500);
    });
}

function txSendText(text) {
    const input = document.getElementById('tx-text-input');
    const value = (text !== undefined ? text : input.value).trim();
    if (!value) return;
    txApi('POST', '/api/tools/texts', { text: value, from: txDeviceName(), client: TX.client })
        .then(() => {
            if (text === undefined) { input.value = ''; input.style.height = 'auto'; }
            txLoadTexts();
        })
        .catch(e => showMegaToast('发送失败：' + e.message, true));
}

// 本机（Deck 上的 Qt 窗口是 localhost，安全上下文）能直接读剪贴板
function txSendClipboard() {
    if (!navigator.clipboard || !window.isSecureContext) return showMegaToast('这个页面读不了剪贴板', true);
    navigator.clipboard.readText().then(t => t.trim() ? txSendText(t) : showMegaToast('剪贴板是空的', true))
        .catch(() => showMegaToast('读剪贴板失败', true));
}

function txDeleteText(id) {
    txApi('DELETE', `/api/tools/texts/${id}`).then(txLoadTexts).catch(() => {});
}

// ---------------------------------------------------------------- 注册

Omni.register('tools', {
    activate() {
        txInitDrop();
        document.getElementById('tx-device-name').textContent = txDeviceName();
        TX.loaded = true;
        txLoadFiles();
        txLoadTexts();
    },
    // 别的设备传了文件 / 发了消息：停在这页就刷新；不管停在哪都给个提示（自己发的不提示）
    onEvent(event) {
        if (event.type !== 'transfer') return;
        const here = activePrimarySection === 'media' && activeMediaTab === 'tools';
        if (event.what === 'files' || event.what === 'uploads') {
            if (here) txLoadFiles();
            if (event.added && event.client !== TX.client) showMegaToast('📥 收到文件：' + event.added);
        } else if (event.what === 'texts') {
            if (here) txLoadTexts();
            // 停在这页就不弹了，列表里直接看得到
            if (event.added && event.client !== TX.client && !here) showMegaToast('💬 收到新的文字 / 链接（局域网小工具）');
        }
    },
});
