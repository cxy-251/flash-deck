let crawlerJobsPollTimer = null;

let crawlerTypesLoaded = false;

function loadCrawlerTypes() {
    // 任务类型列表基本不变，加载过一次就不用每次切标签页都重新拉取
    if (crawlerTypesLoaded) return;
    fetch('/api/downloads/types?t=' + Date.now())
        .then(r => r.json())
        .then(types => {
            crawlerTypesLoaded = true;
            renderCrawlerCards(types || []);
        })
        .catch(() => {});
}

function renderCrawlerCards(types) {
    const container = document.getElementById('crawler-cards-container');
    if (!container) return;
    container.innerHTML = types.map(t => {
        const fieldsHtml = (t.fields || []).map(f => {
            const fieldId = `crawler-field-${t.id}-${f.name}`;
            if (f.options) {
                const opts = f.options.map(o => `<option value="${escapeAttr(o)}"${o === f.default ? ' selected' : ''}>${escapeHtml(o)}</option>`).join('');
                return `<select id="${fieldId}" class="search-input" style="flex:1;min-width:150px;" title="${escapeAttr(f.label)}">${opts}</select>`;
            }
            const placeholder = escapeAttr(f.label + (f.required ? '（必填）' : (f.default ? `（留空默认：${f.default}）` : '（可选）')));
            const value = f.default ? ` value="${escapeAttr(f.default)}"` : '';
            return `<input type="text" id="${fieldId}" class="search-input" style="flex:1;min-width:180px;" placeholder="${placeholder}"${value}>`;
        }).join('');
        const hint = t.fields && t.fields.length
            ? ''
            : `<div style="font-size:12px;color:#8b949e;margin-bottom:10px;">一键运行，没有可填的参数——脚本内部固定清单/全站分类，直接点按钮开始。</div>`;
        return `
            <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px 18px;margin-bottom:16px;">
                <div style="font-size:13px;font-weight:600;color:#c9d1d9;margin-bottom:10px;display:flex;align-items:center;gap:6px;">
                    <span>${escapeHtml(t.label)}</span>
                </div>
                ${hint}
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
                    ${fieldsHtml}
                    <button class="primary-section-btn" style="background:#238636;border-color:#2ea043;color:#fff;font-size:13px;padding:8px 18px;font-weight:600;" onclick="startCrawlerJob('${t.id}')">📥 ${t.fields && t.fields.length ? '开始' : '运行'}</button>
                </div>
            </div>
        `;
    }).join('');
}

function startCrawlerJob(jobType) {
    const params = {};
    document.querySelectorAll(`[id^="crawler-field-${jobType}-"]`).forEach(el => {
        const fieldName = el.id.slice(`crawler-field-${jobType}-`.length);
        params[fieldName] = el.value.trim();
    });
    fetch('/api/downloads/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: jobType, params })
    })
        .then(r => r.json())
        .then(res => {
            if (!res.success) {
                alert('启动失败: ' + (res.error || '未知错误'));
                return;
            }
            refreshCrawlerJobs();
            ensureCrawlerJobsPolling();
        })
        .catch(err => alert('启动失败: ' + err));
}

function refreshCrawlerJobs() {
    fetch('/api/downloads/jobs?t=' + Date.now())
        .then(r => r.json())
        .then(jobs => {
            renderCrawlerJobs(jobs || []);
            const hasRunning = (jobs || []).some(j => j.status === 'running');
            if (hasRunning) {
                ensureCrawlerJobsPolling();
            } else if (crawlerJobsPollTimer) {
                clearInterval(crawlerJobsPollTimer);
                crawlerJobsPollTimer = null;
            }
        })
        .catch(() => {});
}

function ensureCrawlerJobsPolling() {
    if (crawlerJobsPollTimer) return;
    crawlerJobsPollTimer = setInterval(() => {
        if (activePrimarySection === 'media' && activeMediaTab === 'downloads') {
            refreshCrawlerJobs();
        } else {
            clearInterval(crawlerJobsPollTimer);
            crawlerJobsPollTimer = null;
        }
    }, 3000);
}

function renderCrawlerJobs(jobs) {
    const list = document.getElementById('crawler-jobs-list');
    if (!list) return;
    if (!jobs.length) {
        list.innerHTML = '<div style="text-align:center;padding:20px;color:#8b949e;font-size:13px;">暂无下载任务</div>';
        return;
    }
    const statusMeta = {
        running: { icon: '⏳', color: '#f0883e', label: '下载中' },
        done: { icon: '✅', color: '#2ea043', label: '已完成' },
        failed: { icon: '❌', color: '#f85149', label: '失败' },
    };
    list.innerHTML = jobs.map(job => {
        const meta = statusMeta[job.status] || statusMeta.running;
        const tail = (job.log || []).slice(-8).map(escapeHtml).join('\n');
        const startedTime = job.started_at ? new Date(job.started_at * 1000).toLocaleTimeString() : '';
        return `
            <div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px 14px;">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                    <div style="font-size:13px;font-weight:600;color:#f0f6fc;">${meta.icon} ${escapeHtml(job.label || job.type)}</div>
                    <div style="font-size:12px;color:${meta.color};font-weight:600;">${meta.label} · ${startedTime}</div>
                </div>
                <pre style="margin:8px 0 0 0;padding:8px 10px;background:#010409;border-radius:6px;font-size:11.5px;line-height:1.5;color:#8b949e;max-height:140px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;">${tail || '正在启动...'}</pre>
            </div>
        `;
    }).join('');
}

Omni.register('downloads', {
    activate() {
        const subStats = document.getElementById('media-sub-stats');
        document.getElementById('total-badge').textContent = '下载中心';
        if (subStats) subStats.textContent = '把 tools/crawlers/ 里的脚本包装成贴链接下载/一键运行的按钮';
        loadCrawlerTypes();
        refreshCrawlerJobs();
    },
});
