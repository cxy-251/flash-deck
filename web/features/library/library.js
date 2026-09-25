// 存储与游戏库（仅本机）：资源库清单、添加库（目录浏览 + 骨架预览）、收件箱与外部工具路径、库外程序。
// 后端：omni/features/library/api.py；库的目录骨架定义在 omni/core/library.py 的 LAYOUT。

let libraryData = null;
let libraryPreviewTimer = null;
let libraryPickerTarget = null;
let libraryPickerPath = null;
let libraryPickerParent = null;

const LIBRARY_TOOL_LABELS = {
    renpy_sdk: "Ren'Py SDK 启动脚本",
    lime3ds_dir: 'Lime3DS 目录',
    mega_cmd_dir: 'MEGA-CMD 目录',
    uvx: 'uvx 可执行文件',
    sc2_dir: '星际争霸 2 目录',
    sc2mod_dir: 'sc2Mod 项目目录',
    steam_root: 'Steam 根目录',
    proton_prefix: '默认 Proton 容器',
    cloudflared_config: 'cloudflared 配置文件',
};

// 资源库逻辑键 -> 显示名（从 manifest 的分区/子分类里取，跟导航上的名字一致）
function libraryKeyTitles() {
    const titles = {};
    for (const s of Omni.sections('games')) {
        (s.library || []).forEach(k => { titles[k] = s.title; });
        (s.subcategories || []).forEach(c => { titles[c.library] = c.title; });
    }
    return titles;
}

function libFormatBytes(n) {
    if (!n && n !== 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i >= 3 ? 1 : 0)} ${units[i]}`;
}

function libraryPost(op, body) {
    return fetch(`/api/library/${op}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
    }).then(r => r.json());
}

// 库清单变了：游戏列表与各媒体分区的本地缓存都要重新拉
function libraryChanged() {
    Omni.each('onLibraryChanged');
    loadGames();
    prewarmMediaLibraries();
}

function loadLibraryOverview() {
    return fetch('/api/library?t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            libraryData = data;
            renderLibraryOverview();
        })
        .catch(err => showMegaToast('读取资源库信息失败: ' + err, true));
}

function renderLibraryOverview() {
    const d = libraryData;
    if (!d) return;
    const titles = libraryKeyTitles();

    const list = document.getElementById('library-list');
    if (list) {
        list.innerHTML = (d.libraries || []).map((lib, idx) => {
            const badges = [
                lib.default ? '<span class="lib-badge default">默认库</span>' : '',
                lib.online ? '<span class="lib-badge online">在线</span>' : '<span class="lib-badge offline">离线（未挂载）</span>',
            ].join('');
            let disk = '';
            if (lib.disk) {
                const pct = lib.disk.total ? Math.round(lib.disk.used / lib.disk.total * 100) : 0;
                const cls = pct >= 97 ? 'full' : (pct >= 90 ? 'warn' : '');
                disk = `<div class="lib-disk">
                    <div class="lib-disk-bar"><div class="lib-disk-fill ${cls}" style="width:${pct}%"></div></div>
                    <div class="lib-disk-text">已用 ${libFormatBytes(lib.disk.used)} / 共 ${libFormatBytes(lib.disk.total)} · 剩余 ${libFormatBytes(lib.disk.free)}</div>
                </div>`;
            }
            const counts = Object.entries(lib.counts || {})
                .filter(([, n]) => n > 0)
                .map(([k, n]) => `<span class="lib-count">${escapeHtml(titles[k] || k)} <b>${n}</b></span>`)
                .join('');
            const missing = (lib.missing || []).length
                ? `<div class="lib-missing">⚠️ 缺少 ${lib.missing.length} 个骨架目录（${lib.missing.slice(0, 4).map(escapeHtml).join('、')}${lib.missing.length > 4 ? '…' : ''}），点「修复骨架」补齐。</div>`
                : '';
            const up = idx > 0 ? `<button class="manga-mini-btn" title="提高扫描优先级" onclick="libraryMove('${lib.id}', -1)">⬆</button>` : '';
            const down = idx < d.libraries.length - 1 ? `<button class="manga-mini-btn" title="降低扫描优先级" onclick="libraryMove('${lib.id}', 1)">⬇</button>` : '';
            return `<div class="lib-card${lib.online ? '' : ' offline'}${lib.default ? ' is-default' : ''}">
                <div class="lib-card-head">
                    <div>
                        <div class="lib-name">${escapeHtml(lib.label)} ${badges}</div>
                        <div class="lib-path">${escapeHtml(lib.path)}</div>
                    </div>
                    <div class="lib-actions">
                        ${up}${down}
                        ${lib.default ? '' : `<button class="manga-mini-btn" onclick="librarySetDefault('${lib.id}')">⭐ 设为默认</button>`}
                        <button class="manga-mini-btn" onclick="libraryRename('${lib.id}')">✏️ 重命名</button>
                        ${lib.online ? `<button class="manga-mini-btn" onclick="libraryRepair('${lib.id}')">🧱 修复骨架</button>` : ''}
                        <button class="manga-mini-btn" onclick="libraryRemove('${lib.id}')">🗂️ 移出列表</button>
                    </div>
                </div>
                ${disk}
                ${counts ? `<div class="lib-counts">${counts}</div>` : ''}
                ${missing}
            </div>`;
        }).join('') || '<div class="lib-card">还没有任何资源库，在下方添加一个。</div>';
    }

    const dup = document.getElementById('library-dup-warning');
    if (dup) {
        const items = d.duplicates || [];
        dup.style.display = items.length ? 'block' : 'none';
        dup.innerHTML = items.length
            ? `⚠️ 有 ${items.length} 个游戏同时出现在多个资源库里，大厅只显示排在前面那个库里的版本：<br>` +
              items.slice(0, 8).map(x => `· <b>${escapeHtml(x.name)}</b>：${x.paths.map(escapeHtml).join(' ／ ')}`).join('<br>') +
              (items.length > 8 ? `<br>…等 ${items.length} 项` : '')
            : '';
    }

    const form = document.getElementById('library-settings-form');
    if (form) {
        const rows = [];
        // 基础目录：其它路径写成 {games}/xxx 这种占位形式，挪动某个目录只改这里一处
        for (const [k, v] of Object.entries(d.dirs || {})) {
            rows.push(`<label for="library-dir-${k}">基础目录 {${escapeHtml(k)}}</label>
                <input type="text" class="search-input" id="library-dir-${k}" data-dir="${k}" value="${escapeHtml(v.value || '')}" title="${escapeHtml(v.resolved || '')}">`);
        }
        rows.push(`<label for="library-set-inbox">收件箱（下载目录）</label>
            <input type="text" class="search-input" id="library-set-inbox" value="${escapeHtml(d.inbox_dir || '')}">`);
        for (const [k, v] of Object.entries(d.tools || {})) {
            rows.push(`<label for="library-tool-${k}">${escapeHtml(LIBRARY_TOOL_LABELS[k] || k)}</label>
                <input type="text" class="search-input" id="library-tool-${k}" data-tool="${k}" value="${escapeHtml(v || '')}">`);
        }
        form.innerHTML = rows.join('');
    }

    const ext = document.getElementById('library-external-list');
    if (ext) {
        const items = d.external_games || [];
        ext.innerHTML = items.length
            ? items.map((g, i) => `<div class="lib-external-item">
                    <div><b>${escapeHtml(g.name || g.id)}</b> <span style="color:#8b949e;">· ${escapeHtml(g.category || 'app')} · ${escapeHtml(g.path)}</span></div>
                    <button class="manga-mini-btn" onclick="libraryRemoveExternal(${i})">移除登记</button>
                </div>`).join('')
            : '<div style="font-size:12.5px;color:#8b949e;">暂无</div>';
    }
    const catSel = document.getElementById('library-ext-category');
    if (catSel && !catSel.options.length) {
        const standalone = Omni.section('standalone');
        catSel.innerHTML = ((standalone && standalone.subcategories) || [])
            .map(c => `<option value="${c.id}"${c.id === 'app' ? ' selected' : ''}>${escapeHtml(c.title)}</option>`).join('');
    }
}

function libraryApply(promise, okMsg) {
    return promise.then(res => {
        if (res && res.success === false) {
            showMegaToast(res.error || '操作失败', true);
            return res;
        }
        if (res && res.libraries) {
            libraryData = res;
            renderLibraryOverview();
        } else {
            loadLibraryOverview();
        }
        libraryChanged();
        if (okMsg) showMegaToast(okMsg);
        return res;
    }).catch(err => showMegaToast('操作失败: ' + err, true));
}

function librarySetDefault(id) {
    libraryApply(libraryPost('default', { id }), '✅ 已设为默认库，新下载会写入这里');
}

function libraryRename(id) {
    const lib = (libraryData.libraries || []).find(l => l.id === id);
    const label = prompt('资源库名称：', lib ? lib.label : '');
    if (label === null || !label.trim()) return;
    libraryApply(libraryPost('rename', { id, label: label.trim() }), '✅ 已重命名');
}

function libraryRepair(id) {
    libraryApply(libraryPost('repair', { id }).then(res => {
        if (res && res.success) {
            const n = (res.result || []).length;
            res._msg = n ? `✅ 已补齐 ${n} 个目录` : '✅ 目录骨架完整，无需修复';
        }
        return res;
    }), null).then(res => { if (res && res._msg) showMegaToast(res._msg); });
}

function libraryRemove(id) {
    const lib = (libraryData.libraries || []).find(l => l.id === id);
    if (!confirm(`把「${lib ? lib.label : id}」移出资源库列表？\n\n只是不再扫描它，目录里的文件一个都不会删除；以后重新添加同一个目录会自动认回来。`)) return;
    libraryApply(libraryPost('remove', { id }), '已移出资源库列表（文件未改动）');
}

function libraryMove(id, delta) {
    const ids = (libraryData.libraries || []).map(l => l.id);
    const i = ids.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    libraryApply(libraryPost('reorder', { ids }));
}

function libraryPreviewDebounced() {
    if (libraryPreviewTimer) clearTimeout(libraryPreviewTimer);
    libraryPreviewTimer = setTimeout(libraryPreview, 350);
}

function libraryPreview() {
    const el = document.getElementById('library-add-preview');
    const path = (document.getElementById('library-add-path').value || '').trim();
    if (!el) return;
    if (!path) { el.innerHTML = ''; return; }
    libraryPost('preview', { path }).then(p => {
        if (p.error) { el.textContent = p.error; return; }
        const parts = [`将登记目录 <code>${escapeHtml(p.path)}</code>${p.exists ? '' : '（不存在，会自动创建）'}。`];
        if (p.marker) parts.push(`这里已经是资源库「${escapeHtml(p.marker.label || p.marker.id)}」，会沿用它原来的 ID。`);
        parts.push(p.missing.length
            ? `会新建 ${p.missing.length} 个空的骨架目录：${p.missing.map(x => `<code>${escapeHtml(x)}</code>`).join('、')}`
            : '目录骨架已完整，不会新建任何目录。');
        parts.push('已有文件不会被移动或修改。');
        el.innerHTML = parts.join('<br>');
    }).catch(() => { el.textContent = ''; });
}

function libraryAdd() {
    const path = (document.getElementById('library-add-path').value || '').trim();
    if (!path) { showMegaToast('请先填写或选择资源库目录', true); return; }
    const label = (document.getElementById('library-add-label').value || '').trim();
    const makeDefault = document.getElementById('library-add-default').checked;
    libraryApply(libraryPost('add', { path, label, default: makeDefault }), null).then(res => {
        if (res && res.success) {
            const created = (res.result && res.result.created) || [];
            showMegaToast(`✅ 已添加资源库${created.length ? `，新建了 ${created.length} 个目录` : ''}`);
            document.getElementById('library-add-path').value = '';
            document.getElementById('library-add-label').value = '';
            document.getElementById('library-add-default').checked = false;
            document.getElementById('library-add-preview').innerHTML = '';
        }
    });
}

function librarySaveSettings() {
    const tools = {};
    document.querySelectorAll('#library-settings-form [data-tool]').forEach(el => { tools[el.dataset.tool] = el.value.trim(); });
    const dirs = {};
    document.querySelectorAll('#library-settings-form [data-dir]').forEach(el => { if (el.value.trim()) dirs[el.dataset.dir] = el.value.trim(); });
    const inbox = document.getElementById('library-set-inbox');
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dirs, inbox_dir: inbox ? inbox.value.trim() : undefined, tools }),
    }).then(r => r.json()).then(res => {
        if (res.success) {
            libraryData = res;
            renderLibraryOverview();
            libraryChanged();
            showMegaToast('✅ 设置已保存');
        } else {
            showMegaToast(res.error || '保存失败', true);
        }
    }).catch(err => showMegaToast('保存失败: ' + err, true));
}

function librarySaveExternal(items, okMsg) {
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ external_games: items }),
    }).then(r => r.json()).then(res => {
        if (res.success) {
            libraryData = res;
            renderLibraryOverview();
            loadGames();
            if (okMsg) showMegaToast(okMsg);
        }
    }).catch(err => showMegaToast('保存失败: ' + err, true));
}

function libraryAddExternal() {
    const id = (document.getElementById('library-ext-id').value || '').trim();
    const path = (document.getElementById('library-ext-path').value || '').trim();
    const category = document.getElementById('library-ext-category').value || 'app';
    if (!id || !path) { showMegaToast('请填写名称和程序目录', true); return; }
    const items = (libraryData.external_games || []).filter(g => g.id !== id);
    items.push({ id, path, category });
    librarySaveExternal(items, '✅ 已登记');
    document.getElementById('library-ext-id').value = '';
    document.getElementById('library-ext-path').value = '';
}

function libraryRemoveExternal(idx) {
    const items = (libraryData.external_games || []).slice();
    const g = items[idx];
    if (!g || !confirm(`移除「${g.name || g.id}」的登记？（程序文件不会被删除）`)) return;
    items.splice(idx, 1);
    librarySaveExternal(items, '已移除登记');
}

// ---------------------------------------------------------------- 目录选择器

function openLibraryPicker(targetInputId) {
    libraryPickerTarget = targetInputId;
    const cur = (document.getElementById(targetInputId).value || '').trim();
    document.getElementById('library-picker-modal').style.display = 'flex';
    libraryPickerLoad(cur);
}

function closeLibraryPicker() {
    document.getElementById('library-picker-modal').style.display = 'none';
}

function libraryPickerLoad(path) {
    fetch('/api/library/browse?path=' + encodeURIComponent(path || '') + '&t=' + Date.now())
        .then(r => r.json())
        .then(d => {
            if (d.error) {
                if (path) return libraryPickerLoad('');   // 输入的目录不存在：退回主目录
                showMegaToast(d.error, true);
                return;
            }
            libraryPickerPath = d.path;
            libraryPickerParent = d.parent;
            document.getElementById('library-picker-path').textContent = d.path + (d.is_library ? '  （已是资源库）' : '');
            document.getElementById('library-picker-shortcuts').innerHTML = (d.shortcuts || [])
                .map(s => `<button class="manga-mini-btn" onclick="libraryPickerLoad('${escapeAttr(s.path)}')">${s.path === d.shortcuts[0].path ? '🏠' : '💾'} ${escapeHtml(s.label)}</button>`)
                .join('');
            document.getElementById('library-picker-list').innerHTML = (d.dirs || []).length
                ? d.dirs.map(x => `<div class="lib-picker-item" onclick="libraryPickerLoad('${escapeAttr(x.path)}')">📁 ${escapeHtml(x.name)}${x.is_library ? '<span class="lib-badge default">资源库</span>' : ''}</div>`).join('')
                : '<div style="color:#8b949e;font-size:12.5px;padding:8px;">（没有子目录）</div>';
            const sub = document.getElementById('library-picker-choose-sub');
            if (sub) sub.style.display = (libraryPickerTarget === 'library-add-path' && !d.is_library) ? '' : 'none';
        })
        .catch(err => showMegaToast('读取目录失败: ' + err, true));
}

function libraryPickerUp() {
    if (libraryPickerParent) libraryPickerLoad(libraryPickerParent);
}

function libraryPickerChoose(suffix) {
    if (!libraryPickerPath) return;
    const path = suffix ? `${libraryPickerPath.replace(/\/$/, '')}/${suffix}` : libraryPickerPath;
    const input = document.getElementById(libraryPickerTarget);
    if (input) input.value = path;
    closeLibraryPicker();
    if (libraryPickerTarget === 'library-add-path') libraryPreview();
}

Omni.register('library', {
    activate() {
        document.getElementById('total-badge').textContent = '存储与游戏库';
        const subStats = document.getElementById('media-sub-stats');
        if (subStats) subStats.textContent = '资源库位置 · 收件箱 · 外部工具';
        loadLibraryOverview();
    },
});
