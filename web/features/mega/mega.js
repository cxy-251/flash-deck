// ==========================================
// MEGA 网盘中枢原生集成模块 (mega-cmd 驱动)
// ==========================================
let megaStatus = null;

let currentMegaPath = '/';

let currentMegaFiles = [];

let megaTransferPollTimer = null;


function updateMegaQuotaUI(quota) {
    const quotaSec = document.getElementById('mega-quota-section');
    const quotaBadge = document.getElementById('mega-quota-badge');
    const quotaIcon = document.getElementById('mega-quota-icon');
    const quotaDetail = document.getElementById('mega-quota-detail');
    const quotaTimer = document.getElementById('mega-quota-timer');
    if (!quotaSec) return;

    if (!quota) {
        quotaSec.style.display = 'none';
        return;
    }

    quotaSec.style.display = 'flex';
    if (quota.exceeded) {
        if (quotaIcon) quotaIcon.textContent = '⏳';
        if (quotaBadge) {
            quotaBadge.textContent = '流量已达限制';
            quotaBadge.style.background = '#d29922';
            quotaBadge.style.color = '#0d1117';
        }
        if (quotaDetail) quotaDetail.style.display = 'block';
        if (quotaTimer) {
            const clockStr = quota.reset_time_clock ? `${escapeHtml(quota.reset_time_clock)} · ` : '';
            const waitStr = escapeHtml(quota.wait_time || '约2~3小时');
            quotaTimer.innerHTML = `${clockStr}还需 <span style="color:#58a6ff;">${waitStr}</span> 恢复`;
        }
    } else {
        if (quotaIcon) quotaIcon.textContent = '⚡';
        if (quotaBadge) {
            quotaBadge.textContent = '正常可用 (充足)';
            quotaBadge.style.background = '#238636';
            quotaBadge.style.color = '#fff';
        }
        if (quotaDetail) quotaDetail.style.display = 'block';
        if (quotaTimer) {
            quotaTimer.innerHTML = '<span style="color:#2ea043;font-weight:600;">当前可高速下载</span>';
        }
    }
}

function loadMegaStatus(callback) {
    fetch('/api/mega/status?t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            megaStatus = data;
            const authBadge = document.getElementById('mega-auth-badge');
            const actionsEl = document.getElementById('mega-header-actions');
            const storageSec = document.getElementById('mega-storage-section');
            const storageText = document.getElementById('mega-storage-text');
            const storageBar = document.getElementById('mega-storage-bar');
            const loginPanel = document.getElementById('mega-login-panel');
            const explorerPanel = document.getElementById('mega-explorer-panel');
            const subStats = document.getElementById('media-sub-stats');

            if (data && data.logged_in) {
                if (authBadge) {
                    authBadge.textContent = data.email || '已连接';
                    authBadge.style.background = '#238636';
                    authBadge.style.color = '#fff';
                }
                if (subStats && activeMediaTab === 'mega') {
                    subStats.textContent = '';
                }
                if (actionsEl) {
                    actionsEl.innerHTML = `
                        <button class="manga-mini-btn" onclick="doMegaReload()" style="color:#58a6ff;border-color:#388bfd44;font-size:13px;padding:6px 12px;" title="拉取网页端刚转存的文件索引并刷新配额">🔄 刷新同步</button>
                        <button class="manga-mini-btn" onclick="openMegaTrashModal()" style="color:#f85149;border-color:#f8514944;font-size:13px;padding:6px 12px;">🗑️ 云端回收站</button>
                        <button class="manga-mini-btn" onclick="doMegaLogout()" style="font-size:13px;padding:6px 12px;">🚪 退出登录</button>
                    `;
                }
                if (data.storage && storageSec) {
                    storageSec.style.display = 'block';
                    if (storageText) storageText.textContent = `${data.storage.used_str}`;
                    if (storageBar) {
                        let pct = 15;
                        try {
                            const u = parseFloat(data.storage.used_str);
                            if (!isNaN(u) && u > 0) {
                                pct = Math.min(100, Math.max(5, (u / 20.0) * 100));
                            }
                        } catch(e) {}
                        storageBar.style.width = pct + '%';
                    }
                }
                updateMegaQuotaUI(data.quota);
                if (loginPanel) loginPanel.style.display = 'none';
                if (explorerPanel) explorerPanel.style.display = 'block';
                if (!currentMegaFiles || currentMegaFiles.length === 0) {
                    loadMegaFiles(currentMegaPath || '/');
                }
            } else {
                if (authBadge) {
                    authBadge.textContent = '未登录';
                    authBadge.style.background = '#30363d';
                    authBadge.style.color = '#8b949e';
                }
                if (subStats && activeMediaTab === 'mega') {
                    subStats.textContent = '';
                }
                if (actionsEl) {
                    actionsEl.innerHTML = `
                        <button class="manga-mini-btn" onclick="loadMegaStatus()" style="font-size:13px;padding:6px 12px;">🔄 检查服务状态</button>
                    `;
                }
                if (storageSec) storageSec.style.display = 'none';
                updateMegaQuotaUI(null);
                if (loginPanel) loginPanel.style.display = 'block';
                if (explorerPanel) explorerPanel.style.display = 'none';
            }
            if (callback) callback(data);
        })
        .catch(err => {
            console.error('Failed to get mega status:', err);
        });
}

function doMegaLogin() {
    const email = (document.getElementById('mega-login-email').value || '').trim();
    const password = document.getElementById('mega-login-password').value || '';
    const authCode = (document.getElementById('mega-login-2fa').value || '').trim();
    const msgEl = document.getElementById('mega-login-msg');
    const submitBtn = document.getElementById('mega-login-submit-btn');

    if (!email || !password) {
        if (msgEl) {
            msgEl.textContent = '请输入 MEGA 账号邮箱与登录密码';
            msgEl.style.display = 'block';
        }
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '⏳ 正在登录 MEGA...';
    }
    if (msgEl) msgEl.style.display = 'none';

    fetch('/api/mega/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email, password: password, auth_code: authCode || null })
    })
    .then(r => r.json())
    .then(res => {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🔐 登录 MEGA 账户';
        }
        if (res.success) {
            if (msgEl) msgEl.style.display = 'none';
            document.getElementById('mega-login-password').value = '';
            document.getElementById('mega-login-2fa').value = '';
            showMegaToast('✅ 登录成功！正在加载个人网盘文件...');
            loadMegaStatus(() => {
                loadMegaFiles('/');
            });
        } else {
            if (msgEl) {
                msgEl.textContent = res.error || '登录失败，请检查账号或网络';
                msgEl.style.display = 'block';
            }
        }
    })
    .catch(err => {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🔐 登录 MEGA 账户';
        }
        if (msgEl) {
            msgEl.textContent = '登录网络异常: ' + err;
            msgEl.style.display = 'block';
        }
    });
}

function doMegaLogout() {
    if (!confirm('确定要退出当前 MEGA 账号吗？退出后仍可免登录下载公开分享链接。')) return;
    fetch('/api/mega/logout', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            currentMegaFiles = [];
            currentMegaPath = '/';
            showMegaToast('已安全登出 MEGA 账号');
            loadMegaStatus();
        })
        .catch(err => showMegaToast('退出异常: ' + err, true));
}

function doMegaReload() {
    const actionsEl = document.getElementById('mega-header-actions');
    if (actionsEl) {
        actionsEl.innerHTML = '<span style="font-size:13px;color:#58a6ff;">🔄 正在与 MEGA 同步索引与配额状态...</span>';
    }

    fetch('/api/mega/reload', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            loadMegaFiles(currentMegaPath);
            loadMegaStatus(() => {
                refreshMegaTransfers();
            });
            showMegaToast('✅ 索引与配额状态刷新完成！');
        })
        .catch(err => {
            loadMegaStatus(() => {
                refreshMegaTransfers();
            });
            showMegaToast('云端同步失败: ' + err, true);
        });
}

function loadMegaFiles(path) {
    currentMegaPath = path || '/';
    const listEl = document.getElementById('mega-file-list');
    const emptyEl = document.getElementById('mega-explorer-empty');
    const breadcrumb = document.getElementById('mega-breadcrumb-path');
    const upBtn = document.getElementById('mega-nav-up-btn');

    if (breadcrumb) breadcrumb.textContent = currentMegaPath;
    if (upBtn) upBtn.disabled = (currentMegaPath === '/');
    if (listEl) listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#8b949e;"><span style="display:inline-block;animation:spin 1s linear infinite;">⏳</span> 正在读取云端目录...</div>';
    if (emptyEl) emptyEl.style.display = 'none';

    fetch('/api/mega/files?path=' + encodeURIComponent(currentMegaPath) + '&t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                if (listEl) listEl.innerHTML = `<div style="text-align:center;padding:40px;color:#f85149;">❌ 读取目录失败: ${escapeHtml(data.error || '未知错误')}</div>`;
                return;
            }
            currentMegaFiles = data.items || [];
            const filterInput = document.getElementById('mega-filter-input');
            const query = filterInput ? filterInput.value.trim() : '';
            renderMegaFileList(currentMegaFiles, query);
        })
        .catch(err => {
            if (listEl) listEl.innerHTML = `<div style="text-align:center;padding:40px;color:#f85149;">❌ 无法连接服务: ${escapeHtml(String(err))}</div>`;
        });
}

function refreshCurrentMegaFolder() {
    loadMegaFiles(currentMegaPath);
}

function megaNavigateUp() {
    if (currentMegaPath === '/' || !currentMegaPath) return;
    const parts = currentMegaPath.split('/').filter(Boolean);
    parts.pop();
    const parentPath = parts.length === 0 ? '/' : '/' + parts.join('/');
    loadMegaFiles(parentPath);
}

function filterMegaList(query) {
    renderMegaFileList(currentMegaFiles, query);
}

function renderMegaFileList(items, query) {
    const listEl = document.getElementById('mega-file-list');
    const emptyEl = document.getElementById('mega-explorer-empty');
    if (!listEl) return;

    let filtered = items;
    if (query) {
        const q = query.toLowerCase();
        filtered = items.filter(it => it.name.toLowerCase().includes(q));
    }

    if (filtered.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    let html = '';
    filtered.forEach(item => {
        let icon = '📄';
        const lower = item.name.toLowerCase();
        if (item.is_dir) {
            icon = '📁';
        } else if (lower.endsWith('.zip') || lower.endsWith('.rar') || lower.endsWith('.7z') || lower.endsWith('.tar') || lower.endsWith('.zst') || lower.endsWith('.gz') || lower.match(/\.7z\.\d+$/)) {
            icon = '📦';
        } else if (lower.endsWith('.mp4') || lower.endsWith('.mkv') || lower.endsWith('.avi') || lower.endsWith('.webm')) {
            icon = '🎬';
        } else if (lower.endsWith('.mp3') || lower.endsWith('.flac') || lower.endsWith('.wav') || lower.endsWith('.m4a') || lower.endsWith('.ogg')) {
            icon = '🎵';
        } else if (lower.endsWith('.epub') || lower.endsWith('.txt') || lower.endsWith('.pdf')) {
            icon = '📖';
        } else if (lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.webp')) {
            icon = '🖼️';
        }

        const safePath = item.path.replace(/'/g, "\\'");
        const safeName = item.name.replace(/'/g, "\\'");
        const nameHtml = item.is_dir
            ? `<span class="mega-file-clickable" onclick="loadMegaFiles('${safePath}')">${escapeHtml(item.name)}</span>`
            : `<span title="${escapeAttr(item.name)}">${escapeHtml(item.name)}</span>`;

        let actionBtns = '';
        if (item.is_dir) {
            actionBtns += `<button class="manga-mini-btn" onclick="loadMegaFiles('${safePath}')" style="color:#58a6ff;border-color:#388bfd44;font-size:12px;padding:4px 10px;">📂 打开</button> `;
            actionBtns += `<button class="manga-mini-btn" onclick="megaDownload('${safePath}')" style="background:#238636;color:#fff;border-color:#2ea043;font-size:12px;padding:4px 10px;font-weight:600;" title="整目录打包下载至 /home/deck/Downloads">📥 下载整目录</button> `;
        } else {
            actionBtns += `<button class="manga-mini-btn" onclick="megaDownload('${safePath}')" style="background:#238636;color:#fff;border-color:#2ea043;font-size:12px;padding:4px 12px;font-weight:600;" title="高速下载至 /home/deck/Downloads">📥 下载</button> `;
        }
        actionBtns += `<button class="manga-mini-btn" onclick="megaTrashItem('${safePath}', '${safeName}')" style="color:#f85149;border-color:#f8514944;font-size:12px;padding:4px 8px;" title="移入 MEGA 云端回收站">🗑️</button>`;

        html += `
            <div class="mega-file-row">
                <div class="mega-file-name">${icon} ${nameHtml}</div>
                <div style="font-size:12px;color:#8b949e;">${item.size_str || '--'}</div>
                <div style="font-size:11.5px;color:#8b949e;">${item.mtime || '--'}</div>
                <div style="text-align:right;display:flex;gap:6px;justify-content:flex-end;align-items:center;">${actionBtns}</div>
            </div>
        `;
    });
    listEl.innerHTML = html;
}

function megaDownload(sourcePath) {
    showMegaToast('⏳ 正在向 MEGA 守护进程发起下载调度...');
    fetch('/api/mega/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: sourcePath, location: 'downloads' })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success) {
            showMegaToast('✅ 任务已加入下载队列，正在保存至 Downloads 目录');
            refreshMegaTransfers();
        } else {
            showMegaToast('❌ 下载启动失败: ' + (res.error || '未知错误'), true);
        }
    })
    .catch(err => showMegaToast('下载请求异常: ' + err, true));
}

function downloadMegaPublicUrl() {
    const input = document.getElementById('mega-public-url-input');
    const url = input ? input.value.trim() : '';
    if (!url) {
        showMegaToast('请先输入或粘贴 MEGA 分享链接！', true);
        return;
    }
    megaDownload(url);
    if (input) input.value = '';
}

function refreshMegaTransfers() {
    fetch('/api/mega/transfers?t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            if (data && data.quota) {
                updateMegaQuotaUI(data.quota);
            }
            const card = document.getElementById('mega-transfers-card');
            const countEl = document.getElementById('mega-transfers-count');
            const listEl = document.getElementById('mega-transfers-list');
            if (!card || !listEl) return;

            let list = (data.transfers || []).filter(item => {
                const s = (item.status || '').toUpperCase();
                return !s.includes('CANCEL') && !s.includes('COMPLET');
            });

            if (list.length === 0) {
                card.style.display = 'none';
                if (megaTransferPollTimer) {
                    clearTimeout(megaTransferPollTimer);
                    megaTransferPollTimer = null;
                }
                return;
            }

            card.style.display = 'block';
            if (countEl) countEl.textContent = list.length;
            let html = '';
            let hasActiveTasks = false;

            // 若触发全局配额限制，在队列卡片顶部展示明确提示栏（含全部暂停/恢复按钮）
            if (data.quota && data.quota.exceeded) {
                const clockText = data.quota.reset_time_clock ? `预计于 <span style="color:#58a6ff;font-weight:700;">${escapeHtml(data.quota.reset_time_clock)}</span> 解除` : '限额中';
                const waitText = escapeHtml(data.quota.wait_time || '约2~3小时');
                html += `
                    <div style="background:#382606;border:1px solid #9e6a03;border-radius:8px;padding:9px 13px;margin-bottom:10px;font-size:12px;color:#f0b429;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                        <span style="font-size:15px;">⏳</span>
                        <div style="flex:1;min-width:200px;"><strong>当前 IP 已触碰 MEGA 免费流量配额上限：</strong>${clockText}（还需 <strong>${waitText}</strong>）。限额解除后后台将自动高速断点续传。</div>
                        <div style="display:flex;gap:6px;">
                            <button class="manga-mini-btn" onclick="pauseMegaTransfer('all')" style="color:#d29922;border-color:#d2992244;font-size:11px;padding:3px 8px;" title="暂停全部下载任务，限额恢复后再手动恢复">⏸ 全部暂停</button>
                            <button class="manga-mini-btn" onclick="resumeMegaTransfer('all')" style="color:#2ea043;border-color:#2ea04344;font-size:11px;padding:3px 8px;" title="恢复全部已暂停的下载任务">▶ 全部恢复</button>
                            <button class="manga-mini-btn" onclick="cancelMegaTransfer('all')" style="color:#f85149;border-color:#f8514944;font-size:11px;padding:3px 8px;" title="取消全部下载任务">✕ 全部取消</button>
                        </div>
                    </div>
                `;
            }

            list.forEach(item => {
                const tag = item.tag || '';
                const name = item.name || item.raw || '未知下载项';
                const progress = item.progress || '--';
                const status = (item.status || 'ACTIVE').toUpperCase();

                let statusBadge = '';
                let isPaused = status.includes('PAUSED') || status === 'PAUSED';
                let isRetrying = status === 'RETRYING' || status.includes('RETRY') || status.includes('BLOCK');

                if (isPaused) {
                    statusBadge = '<span style="color:#8b949e;font-weight:600;">⏸ 已暂停</span>';
                    hasActiveTasks = true;
                } else if (isRetrying) {
                    const waitTime = item.quota_wait || (data.quota ? data.quota.wait_time : null) || '约2~3小时';
                    const clockStr = item.reset_clock || (data.quota ? data.quota.reset_time_clock : null);
                    const clockPart = clockStr ? `${escapeHtml(clockStr)} · ` : '';
                    statusBadge = `<span style="color:#d29922;font-weight:600;" title="MEGA 免费 IP 流量受限，后台将自动退避重试">⏳ 限额等待中 (预计 ${clockPart}还需 ${escapeHtml(waitTime)} 解除)</span>`;
                    hasActiveTasks = true;
                } else if (status === 'ACTIVE' || status === 'RUNNING') {
                    statusBadge = '<span style="color:#2ea043;font-weight:600;">⚡ 正在高速下载...</span>';
                    hasActiveTasks = true;
                } else {
                    statusBadge = `<span style="color:#58a6ff;">${escapeHtml(status)}</span>`;
                    hasActiveTasks = true;
                }

                // 根据任务状态决定显示哪些操作按钮
                let actionBtns = '';
                if (isPaused) {
                    actionBtns = `
                        <button class="manga-mini-btn" onclick="resumeMegaTransfer('${tag}')" style="color:#2ea043;border-color:#2ea04344;font-size:11.5px;padding:4px 10px;" title="恢复下载">▶ 恢复</button>
                        <button class="manga-mini-btn" onclick="cancelMegaTransfer('${tag}')" style="color:#f85149;border-color:#f8514944;font-size:11.5px;padding:4px 10px;">✕ 取消</button>
                    `;
                } else if (isRetrying) {
                    actionBtns = `
                        <button class="manga-mini-btn" onclick="pauseMegaTransfer('${tag}')" style="color:#d29922;border-color:#d2992244;font-size:11.5px;padding:4px 10px;" title="暂停该任务，等限额恢复后手动恢复">⏸ 暂停</button>
                        <button class="manga-mini-btn" onclick="cancelMegaTransfer('${tag}')" style="color:#f85149;border-color:#f8514944;font-size:11.5px;padding:4px 10px;">✕ 取消</button>
                    `;
                } else {
                    actionBtns = `
                        <button class="manga-mini-btn" onclick="pauseMegaTransfer('${tag}')" style="color:#d29922;border-color:#d2992244;font-size:11.5px;padding:4px 10px;" title="暂停下载">⏸ 暂停</button>
                        <button class="manga-mini-btn" onclick="cancelMegaTransfer('${tag}')" style="color:#f85149;border-color:#f8514944;font-size:11.5px;padding:4px 10px;">✕ 取消</button>
                    `;
                }

                html += `
                    <div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px;" id="mega-task-${tag}">
                        <div style="flex:1;overflow:hidden;">
                            <div style="font-size:13px;font-weight:600;color:#f0f6fc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">📥 ${escapeHtml(name)}</div>
                            <div style="font-size:11.5px;color:#8b949e;margin-top:3px;">
                                进度: <span style="color:#58a6ff;font-weight:600;">${escapeHtml(progress)}</span> · 状态: ${statusBadge}
                            </div>
                        </div>
                        <div style="display:flex;gap:4px;">
                            ${actionBtns}
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = html;

            if (megaTransferPollTimer) clearTimeout(megaTransferPollTimer);
            if (hasActiveTasks) {
                megaTransferPollTimer = setTimeout(refreshMegaTransfers, 2500);
            }
        })
        .catch(() => {});
}

function cancelMegaTransfer(tag) {
    const promptMsg = tag === 'all' ? '确定要取消全部正在进行的 MEGA 传输任务吗？' : '确定取消该下载任务吗？';
    if (!confirm(promptMsg)) return;

    // 立即从页面 DOM 中移除该任务或隐藏队列卡片，杜绝任务残留
    if (tag === 'all') {
        const card = document.getElementById('mega-transfers-card');
        if (card) card.style.display = 'none';
    } else {
        const row = document.getElementById('mega-task-' + tag);
        if (row) row.remove();
        const countEl = document.getElementById('mega-transfers-count');
        if (countEl) {
            const currentCount = parseInt(countEl.textContent, 10) || 1;
            const nextCount = Math.max(0, currentCount - 1);
            countEl.textContent = nextCount;
            if (nextCount === 0) {
                const card = document.getElementById('mega-transfers-card');
                if (card) card.style.display = 'none';
            }
        }
    }

    fetch('/api/mega/cancel_transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tag })
    })
    .then(r => r.json())
    .then(() => {
        showMegaToast('任务已取消');
        refreshMegaTransfers();
    })
    .catch(err => {
        showMegaToast('取消任务失败: ' + err, true);
        refreshMegaTransfers();
    });
}

function pauseMegaTransfer(tag) {
    fetch('/api/mega/pause_transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tag })
    })
    .then(r => r.json())
    .then(() => {
        showMegaToast(tag === 'all' ? '已暂停全部下载任务' : '任务已暂停');
        refreshMegaTransfers();
    })
    .catch(err => {
        showMegaToast('暂停任务失败: ' + err, true);
        refreshMegaTransfers();
    });
}

function resumeMegaTransfer(tag) {
    fetch('/api/mega/resume_transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tag })
    })
    .then(r => r.json())
    .then(() => {
        showMegaToast(tag === 'all' ? '已恢复全部下载任务' : '任务已恢复');
        refreshMegaTransfers();
    })
    .catch(err => {
        showMegaToast('恢复任务失败: ' + err, true);
        refreshMegaTransfers();
    });
}

function megaTrashItem(remotePath, name) {
    if (!confirm(`确定要将 "${name}" 移至 MEGA 云端回收站吗？\n可在云端回收站恢复或永久清空。`)) return;

    fetch('/api/mega/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: remotePath })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success) {
            showMegaToast(`已将 "${name}" 移至回收站`);
            loadMegaFiles(currentMegaPath);
            loadMegaStatus();
        } else {
            showMegaToast('移入回收站失败: ' + (res.error || '未知错误'), true);
        }
    })
    .catch(err => showMegaToast('操作异常: ' + err, true));
}

function openMegaTrashModal() {
    const modal = document.getElementById('mega-trash-modal');
    if (modal) modal.style.display = 'flex';
    refreshMegaTrashList();
}

function closeMegaTrashModal() {
    const modal = document.getElementById('mega-trash-modal');
    if (modal) modal.style.display = 'none';
}

function refreshMegaTrashList() {
    const listEl = document.getElementById('mega-trash-items-list');
    const emptyEl = document.getElementById('mega-trash-empty-msg');
    const badgeEl = document.getElementById('mega-trash-modal-badge');

    if (listEl) listEl.innerHTML = '<div style="text-align:center;padding:30px;color:#8b949e;"><span style="display:inline-block;animation:spin 1s linear infinite;">⏳</span> 正在读取云端回收站...</div>';
    if (emptyEl) emptyEl.style.display = 'none';

    fetch('/api/mega/trash?t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            const items = data.items || [];
            if (badgeEl) badgeEl.textContent = `(${items.length} 个项目)`;
            if (items.length === 0) {
                if (listEl) listEl.innerHTML = '';
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';
            let html = '';
            items.forEach(it => {
                const icon = it.is_dir ? '📁' : '📄';
                const safePath = it.path.replace(/'/g, "\\'");
                const safeName = it.name.replace(/'/g, "\\'");
                html += `
                    <div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:8px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px;">
                        <div style="display:flex;align-items:center;gap:10px;overflow:hidden;flex:1;">
                            <span>${icon}</span>
                            <div style="font-size:13px;color:#f0f6fc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeAttr(it.name)}">${escapeHtml(it.name)}</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <div style="font-size:12px;color:#8b949e;white-space:nowrap;">
                                ${it.size_str || '--'}
                            </div>
                            <button class="manga-mini-btn" onclick="restoreMegaTrashItem('${safePath}', '${safeName}')" style="color:#2ea043;border-color:#2ea04355;font-size:12px;padding:3px 10px;font-weight:600;" title="恢复至网盘根目录">↩️ 恢复</button>
                        </div>
                    </div>
                `;
            });
            if (listEl) listEl.innerHTML = html;
        })
        .catch(err => {
            if (listEl) listEl.innerHTML = `<div style="text-align:center;padding:30px;color:#f85149;">❌ 读取回收站异常: ${escapeHtml(String(err))}</div>`;
        });
}

function restoreMegaTrashItem(remotePath, name) {
    showMegaToast(`⏳ 正在恢复 "${name}"...`);
    fetch('/api/mega/restore_trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: remotePath })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success) {
            showMegaToast(`✅ 已成功恢复 "${name}" 至网盘根目录！`);
            refreshMegaTrashList();
            loadMegaFiles(currentMegaPath);
            loadMegaStatus();
        } else {
            showMegaToast('恢复失败: ' + (res.error || '未知错误'), true);
        }
    })
    .catch(err => showMegaToast('恢复异常: ' + err, true));
}

function doEmptyMegaTrash() {
    if (!confirm('⚠️ 警告：清空回收站将彻底永久删除云端回收站中的所有文件，此操作不可撤销！\n\n确定要立即清空吗？')) return;
    const btn = document.getElementById('mega-trash-empty-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '🧹 正在清空云端回收站...';
    }

    fetch('/api/mega/empty_trash', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🧹 一键彻底清空回收站';
            }
            if (res.success) {
                showMegaToast('✅ 云端回收站已彻底清空！已释放空间');
                refreshMegaTrashList();
                loadMegaStatus();
            } else {
                showMegaToast('清空失败: ' + (res.error || '未知错误'), true);
            }
        })
        .catch(err => {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🧹 一键彻底清空回收站';
            }
            showMegaToast('清空异常: ' + err, true);
        });
}

Omni.register('mega', {
    activate() {
        const subStats = document.getElementById('media-sub-stats');
        document.getElementById('total-badge').textContent = 'MEGA';
        if (subStats) {
            subStats.textContent = '';
        }
        loadMegaStatus();
        refreshMegaTransfers();
    },
});
