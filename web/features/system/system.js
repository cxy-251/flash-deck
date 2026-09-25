// ================= 局域网与广域网网络控制与气泡管理 =================
let currentLanStatus = { enabled: false, ip: '', port: 8998, url: '' };

let currentWanStatus = { enabled: false, status: 'stopped', url: '' };

let wanPollingTimer = null;

function updateLanButtonUI(status) {
    currentLanStatus = status;
    const btn = document.getElementById('lan-share-btn');
    const dot = document.getElementById('lan-share-dot');
    const text = document.getElementById('lan-share-text');
    const bubbleStatus = document.getElementById('lan-bubble-status');
    const urlText = document.getElementById('lan-url-text');
    if (!btn || !dot || !text) return;

    const targetUrl = status.url || (status.ip ? `http://${status.ip}:${status.port}` : location.origin);

    if (status.enabled) {
        btn.className = 'nav-net-btn active';
        text.textContent = '局域网: 开';
        if (bubbleStatus) {
            bubbleStatus.className = 'bubble-status active';
            bubbleStatus.textContent = '已开启';
        }
        if (urlText) urlText.textContent = targetUrl;
    } else {
        btn.className = 'nav-net-btn';
        text.textContent = '局域网: 关';
        if (bubbleStatus) {
            bubbleStatus.className = 'bubble-status';
            bubbleStatus.textContent = '未开启';
        }
        if (urlText) urlText.textContent = targetUrl;
    }
}

function updateWanButtonUI(status) {
    currentWanStatus = status;
    const btn = document.getElementById('wan-share-btn');
    const dot = document.getElementById('wan-share-dot');
    const text = document.getElementById('wan-share-text');
    const bubbleStatus = document.getElementById('wan-bubble-status');
    const urlText = document.getElementById('wan-url-text');
    const desc = document.getElementById('wan-bubble-desc');
    if (!btn || !dot || !text) return;

    const domainUrl = status.url || '（未配置广域网域名）';

    if (status.enabled) {
        btn.className = 'nav-net-btn active';
        text.textContent = '广域网: 开';
        if (bubbleStatus) {
            bubbleStatus.className = 'bubble-status active';
            bubbleStatus.textContent = '已开启';
        }
        if (urlText) urlText.textContent = domainUrl;
        if (desc) desc.textContent = '全球任何地方通过该专属 HTTPS 加密网址均可访问！点击网址直接复制。';
    } else {
        btn.className = 'nav-net-btn';
        text.textContent = '广域网: 关';
        if (bubbleStatus) {
            bubbleStatus.className = 'bubble-status';
            bubbleStatus.textContent = '未开启';
        }
        if (urlText) urlText.textContent = domainUrl;
        if (desc) desc.textContent = (status.url ? `开启后放行外部网络通过 ${status.url} 访问，出门在外随时看漫画！` : '先在 var/config/settings.json 里配置 wan_domain');
    }
}

function checkLanStatus() {
    fetch('/api/lan/status?t=' + Date.now())
        .then(r => r.json())
        .then(status => {
            updateLanButtonUI(status);
            if (status) {
                if (typeof status.is_local === 'boolean') {
                    isDeckLocal = status.is_local;
                }
                if (typeof status.unlocked === 'boolean') {
                    isNsfwUnlocked = status.unlocked;
                    updateNsfwUI();
                }
            }
            if (status && typeof status.is_remote === 'boolean') {
                const prev = isRemoteClient;
                isRemoteClient = status.is_remote;
                if (isRemoteClient) {
                    applyRemoteClientRestrictions();
                } else {
                    removeRemoteClientRestrictions();
                }
                if (prev !== isRemoteClient) {
                    applyFilter();
                }
            }
        })
        .catch(() => {});
}

function checkWanStatus() {
    fetch('/api/wan/status?t=' + Date.now())
        .then(r => r.json())
        .then(status => {
            updateWanButtonUI(status);
        })
        .catch(() => {});
}

function toggleLanSharing() {
    const nextState = !currentLanStatus.enabled;
    fetch('/api/lan/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextState })
    })
    .then(r => r.json())
    .then(status => {
        updateLanButtonUI(status);
    })
    .catch(err => alert('切换局域网状态失败: ' + err));
}

function toggleWanSharing() {
    const nextState = !currentWanStatus.enabled;
    fetch('/api/wan/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextState })
    })
    .then(r => r.json())
    .then(status => {
        updateWanButtonUI(status);
    })
    .catch(err => alert('切换广域网状态失败: ' + err));
}

function copyNetUrl(type) {
    let url = '';
    let badgeEl = null;
    if (type === 'lan') {
        if (!currentLanStatus || !currentLanStatus.enabled) {
            alert('局域网共享尚未开启！请先点击左侧【局域网】按钮开启。');
            return;
        }
        url = currentLanStatus.url || `http://${currentLanStatus.ip}:${currentLanStatus.port}`;
        badgeEl = document.getElementById('lan-copy-badge');
    } else {
        url = (currentWanStatus && currentWanStatus.url) ? currentWanStatus.url : '';
        if (!url) { alert('尚未配置广域网域名（settings.json 的 wan_domain）'); return; }
        badgeEl = document.getElementById('wan-copy-badge');
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            if (badgeEl) {
                const orig = badgeEl.textContent;
                badgeEl.textContent = '✓ 已复制！';
                badgeEl.style.color = '#3fb950';
                setTimeout(() => {
                    badgeEl.textContent = orig;
                    badgeEl.style.color = '';
                }, 2000);
            }
        }).catch(() => {
            prompt('请手动复制网址：', url);
        });
    } else {
        prompt('请手动复制网址：', url);
    }
}

// ================= 全局系统与运行日志 (System Log Console) =================
let logAutoRefreshTimer = null;

let currentLogsData = [];

let currentGameLogContent = null;

function openLogModal() {
    const modal = document.getElementById('log-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    refreshLogSources();
    refreshLogs();
    toggleLogAutoRefresh(document.getElementById('log-auto-refresh')?.checked ?? true);
}

function closeLogModal() {
    const modal = document.getElementById('log-modal');
    if (modal) modal.style.display = 'none';
    toggleLogAutoRefresh(false);
}

function toggleLogAutoRefresh(enabled) {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }
    const badge = document.getElementById('log-status-badge');
    if (enabled) {
        if (badge) {
            badge.textContent = '实时监控 (2s)';
            badge.style.color = '#58a6ff';
            badge.style.borderColor = '#388bfd';
        }
        logAutoRefreshTimer = setInterval(() => {
            const modal = document.getElementById('log-modal');
            if (modal && modal.style.display !== 'none') {
                refreshLogs(true);
            } else {
                toggleLogAutoRefresh(false);
            }
        }, 2000);
    } else {
        if (badge) {
            badge.textContent = '暂停轮询';
            badge.style.color = '#8b949e';
            badge.style.borderColor = '#30363d';
        }
    }
}

function refreshLogSources() {
    fetch('/api/logs?lines=1&t=' + Date.now())
        .then(r => r.json())
        .then(data => {
            const sel = document.getElementById('log-source-select');
            if (!sel) return;
            const curVal = sel.value;
            let optsHtml = '<option value="global">全系统核心日志 (omni_deck.log)</option>';
            if (data.available_game_logs && data.available_game_logs.length > 0) {
                data.available_game_logs.forEach(gl => {
                    const sizeKb = (gl.size / 1024).toFixed(1);
                    optsHtml += `<option value="game:${gl.game_key}">🎮 游戏进程 [${gl.game_key}] (${sizeKb} KB)</option>`;
                });
            }
            sel.innerHTML = optsHtml;
            if (curVal && sel.querySelector(`option[value="${curVal}"]`)) {
                sel.value = curVal;
            }
        })
        .catch(() => {});
}

function onLogSourceChange() {
    refreshLogs();
}

function refreshLogs(isAuto = false) {
    const sel = document.getElementById('log-source-select');
    const levelSel = document.getElementById('log-level-select');
    const source = sel ? sel.value : 'global';
    const level = levelSel ? levelSel.value : 'ALL';

    let url = `/api/logs?lines=500&level=${encodeURIComponent(level)}&t=${Date.now()}`;
    if (source && source.startsWith('game:')) {
        const gid = source.replace('game:', '');
        url += `&game_id=${encodeURIComponent(gid)}`;
    }

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                currentLogsData = data.logs || [];
                currentGameLogContent = data.game_log || null;
                renderLogs(source);
            }
        })
        .catch(err => {
            if (!isAuto) {
                const box = document.getElementById('log-console-container');
                if (box) box.innerHTML = `<div style="color:#f85149;">获取日志失败: ${err}</div>`;
            }
        });
}

function renderLogs(source) {
    const box = document.getElementById('log-console-container');
    const summaryEl = document.getElementById('log-summary-text');
    const kw = (document.getElementById('log-search-input')?.value || '').trim().toLowerCase();
    if (!box) return;

    const isNearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 80;

    if (source && source.startsWith('game:')) {
        if (!currentGameLogContent) {
            box.innerHTML = '<div style="color:#8b949e;">暂无该游戏的输出日志</div>';
            if (summaryEl) summaryEl.textContent = '0 行输出';
            return;
        }
        let lines = currentGameLogContent.split('\n');
        if (kw) {
            lines = lines.filter(l => l.toLowerCase().includes(kw));
        }
        if (summaryEl) summaryEl.textContent = `共 ${lines.length} 行输出`;
        let html = lines.map(line => {
            let esc = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            let col = '#c9d1d9';
            if (/error|err|fail|exception|fatal/i.test(line)) col = '#f85149';
            else if (/warn|warning/i.test(line)) col = '#d29922';
            else if (/info|success/i.test(line)) col = '#7ee787';
            return `<div style="color:${col};">${esc || '&nbsp;'}</div>`;
        }).join('');
        box.innerHTML = html || '<div style="color:#8b949e;">无匹配内容</div>';
    } else {
        let logs = currentLogsData;
        if (kw) {
            logs = logs.filter(item => {
                const txt = (item.text || item.msg || '').toLowerCase();
                return txt.includes(kw);
            });
        }
        if (summaryEl) summaryEl.textContent = `共 ${logs.length} 条系统日志`;
        if (logs.length === 0) {
            box.innerHTML = '<div style="color:#8b949e;">暂无日志条目</div>';
            return;
        }
        let html = logs.map(entry => {
            const escTime = entry.time || '';
            const escTag = entry.tag ? `[${entry.tag}]` : '';
            const escLevel = entry.level || 'INFO';
            const escMsg = (entry.msg || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            let levelCol = '#7ee787';
            if (escLevel === 'ERROR') levelCol = '#f85149';
            else if (escLevel === 'WARN') levelCol = '#d29922';
            else if (escLevel === 'DEBUG') levelCol = '#58a6ff';

            return `<div style="margin-bottom:2px;display:flex;gap:8px;">
                <span style="color:#6e7681;flex-shrink:0;">${escTime}</span>
                <span style="color:${levelCol};font-weight:600;flex-shrink:0;min-width:55px;">[${escLevel}]</span>
                <span style="color:#8b949e;flex-shrink:0;">${escTag}</span>
                <span style="color:#e6edf3;flex:1;">${escMsg}</span>
            </div>`;
        }).join('');
        box.innerHTML = html;
    }

    if (isNearBottom) {
        box.scrollTop = box.scrollHeight;
    }
}

function filterDisplayedLogs() {
    const sel = document.getElementById('log-source-select');
    renderLogs(sel ? sel.value : 'global');
}

function copyAllLogs() {
    const box = document.getElementById('log-console-container');
    if (!box) return;
    const text = box.innerText || box.textContent || '';
    if (!text) {
        alert('日志为空，无需复制');
        return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            alert('📋 日志已成功复制到剪贴板！');
        }).catch(err => {
            alert('复制失败: ' + err);
        });
    } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('📋 日志已成功复制到剪贴板！');
    }
}

function clearLogs() {
    if (!confirm('确定清空当前全局运行日志吗？')) return;
    fetch('/api/logs/clear', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            currentLogsData = [];
            refreshLogs();
        })
        .catch(err => alert('清空失败: ' + err));
}
