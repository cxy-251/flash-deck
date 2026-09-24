// ================= 星际争霸2 对战面板（独立游戏专区专属子标签） =================
const SC2_RACES = [['R', '随机'], ['T', '人族'], ['P', '神族'], ['Z', '虫族']];

const SC2_TEAMS = [['all', '全部'], ['1v1', '1v1'], ['2v2', '2v2'], ['3v3', '3v3'], ['4v4+', '4+v4+']];

let sc2State = {
    race: 'P', mods: new Set(), loaded: false, polling: false, team: 'all', maps: [],
    modalMap: null, oppCount: 1, oppConfig: [],
};

function sc2RaceChips(role, container) {
    container.innerHTML = '';
    SC2_RACES.forEach(([key, name]) => {
        const b = document.createElement('button');
        b.className = 'sc2-race-btn' + (sc2State[role] === key ? ' active' : '');
        b.textContent = name;
        b.onclick = () => {
            sc2State[role] = key;
            container.querySelectorAll('.sc2-race-btn').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
        };
        container.appendChild(b);
    });
}

function sc2RenderTeamTabs() {
    const bar = document.getElementById('sc2-team-tabs');
    bar.innerHTML = '';
    SC2_TEAMS.forEach(([key, name]) => {
        const b = document.createElement('button');
        b.className = 'sub-tab-btn' + (sc2State.team === key ? ' active' : '');
        b.textContent = name;
        b.onclick = () => {
            sc2State.team = key;
            bar.querySelectorAll('.sub-tab-btn').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            sc2RenderMapGrid();
        };
        bar.appendChild(b);
    });
}

function sc2RenderMapGrid() {
    const grid = document.getElementById('sc2-map-grid');
    grid.innerHTML = '';
    const list = sc2State.team === 'all'
        ? sc2State.maps
        : sc2State.maps.filter(m => m.team === sc2State.team);
    if (!list.length) {
        grid.innerHTML = '<div class="empty-state">这个分队规模暂时没有地图</div>';
        return;
    }
    list.forEach(m => {
        const card = document.createElement('div');
        card.className = 'sc2-map-card';
        card.dataset.stem = m.stem;
        card.innerHTML = `<img src="${m.thumb}" loading="lazy"><div class="sc2-map-name">${escapeHtml(m.stem)}</div>`;
        card.onclick = () => sc2OpenModal(m.stem);
        grid.appendChild(card);
    });
}

function initSc2Panel() {
    sc2RaceChips('race', document.querySelector('#sc2-settings [data-role="race"]'));
    sc2RenderTeamTabs();
    if (!sc2State.loaded) {
        sc2State.loaded = true;
        fetch('/api/sc2/mods').then(r => r.json()).then(mods => {
            const row = document.getElementById('sc2-mods-row');
            row.innerHTML = '';
            const byGroup = {};   // group -> [key,...]，同组只能选一个
            (mods || []).forEach(m => {
                if (m.group) (byGroup[m.group] ||= []).push(m.key);
            });
            (mods || []).forEach(m => {
                if (m.error) return;
                const label = document.createElement('label');
                label.className = 'sc2-mod-chip';
                label.title = m.desc || '';
                label.innerHTML = `<input type="checkbox" data-mod="${escapeAttr(m.key)}"> ${escapeHtml(m.name)}`;
                label.querySelector('input').onchange = (e) => {
                    if (e.target.checked) {
                        sc2State.mods.add(m.key);
                        // 同组的其它选项互斥：勾了这个就把同组别的都取消
                        if (m.group) {
                            for (const otherKey of byGroup[m.group]) {
                                if (otherKey === m.key) continue;
                                sc2State.mods.delete(otherKey);
                                const otherInput = row.querySelector(`input[data-mod="${CSS.escape(otherKey)}"]`);
                                if (otherInput) otherInput.checked = false;
                            }
                        }
                    } else {
                        sc2State.mods.delete(m.key);
                    }
                };
                row.appendChild(label);
            });
        }).catch(() => {});
        fetch('/api/sc2/maps').then(r => r.json()).then(maps => {
            sc2State.maps = (maps || []).filter(m => !m.error);
            sc2RenderMapGrid();
        }).catch(() => {
            const grid = document.getElementById('sc2-map-grid');
            grid.innerHTML = '<div class="empty-state">地图列表加载失败，确认 omni-deck 自己的 sc2_runner.py / sc2_panel_service.py 还在</div>';
        });
    }
    sc2RefreshStatus();
}

function sc2SetBanner(text, kind) {
    const el = document.getElementById('sc2-status-banner');
    if (!text) { el.style.display = 'none'; return; }
    const colors = {
        info: ['#132436', '#1f3a5f', '#58a6ff'],
        ok: ['#0f2a1a', '#1f5c33', '#3fb950'],
        err: ['#2d1214', '#5c2226', '#f85149'],
    }[kind || 'info'];
    el.style.display = 'block';
    el.style.background = colors[0];
    el.style.border = '1px solid ' + colors[1];
    el.style.color = colors[2];
    el.textContent = text;
}

function sc2OpenEditor() {
    sc2SetBanner('🛠️ 正在启动银河编辑器…（头一次打开可能要等十几秒）', 'info');
    fetch('/api/sc2/open_editor', { method: 'POST' })
        .then(r => r.json())
        .then(res => {
            if (res.status !== 'ok') sc2SetBanner('⚠️ ' + (res.message || '编辑器启动失败'), 'err');
        })
        .catch(() => sc2SetBanner('⚠️ 请求失败，看 omni-deck 日志', 'err'));
}

const SC2_DIFFS = [
    ['cheatinsane', '残酷3（作弊-疯狂）'],
    ['cheatmoney', '作弊-资源'],
    ['cheatvision', '作弊-视野'],
    ['veryhard', '非常难'],
];

function sc2OpenModal(mapStem) {
    const m = sc2State.maps.find(x => x.stem === mapStem);
    if (!m) return;
    const maxOpp = Math.max(1, m.max_opponents || 1);
    sc2State.modalMap = m;
    sc2State.oppCount = maxOpp;   // 默认选满对手，可以往下调
    sc2State.oppConfig = Array.from({ length: maxOpp }, () => ({ race: 'R', difficulty: 'cheatinsane' }));
    document.getElementById('sc2-modal-title').textContent = mapStem + `（${m.max_players || 2} 人图 · ${m.team}）`;
    sc2RenderOppRows();
    document.getElementById('sc2-match-modal').style.display = 'flex';
}

function sc2CloseModal() {
    document.getElementById('sc2-match-modal').style.display = 'none';
    sc2State.modalMap = null;
}

function sc2ChangeOppCount(delta) {
    const m = sc2State.modalMap;
    if (!m) return;
    const maxOpp = Math.max(1, m.max_opponents || 1);
    const next = Math.min(maxOpp, Math.max(1, sc2State.oppCount + delta));
    if (next === sc2State.oppCount) return;
    while (sc2State.oppConfig.length < next) sc2State.oppConfig.push({ race: 'R', difficulty: 'cheatinsane' });
    sc2State.oppCount = next;
    sc2RenderOppRows();
}

function sc2RenderOppRows() {
    const m = sc2State.modalMap;
    const maxOpp = Math.max(1, m.max_opponents || 1);
    document.getElementById('sc2-opp-count-label').textContent = sc2State.oppCount;
    const noTeamData = maxOpp === 1 && (m.max_players || 2) > 2;
    document.getElementById('sc2-opp-count-hint').textContent = noTeamData
        ? '（这张图没有预设队伍数据，多个电脑会各打各的、全部跟你敌对，所以只能配 1 个）'
        : `（这张图最多 ${maxOpp} 个电脑，会跟你分成两队）`;
    const wrap = document.getElementById('sc2-opp-rows');
    wrap.innerHTML = '';
    for (let i = 0; i < sc2State.oppCount; i++) {
        const cfg = sc2State.oppConfig[i];
        const raceOpts = SC2_RACES.map(([k, n]) => `<option value="${k}"${cfg.race === k ? ' selected' : ''}>${n}</option>`).join('');
        const diffOpts = SC2_DIFFS.map(([k, n]) => `<option value="${k}"${cfg.difficulty === k ? ' selected' : ''}>${n}</option>`).join('');
        const row = document.createElement('div');
        row.className = 'sc2-opp-row';
        row.innerHTML = `<span class="sc2-opp-label">电脑 ${i + 1}</span>
            <select data-field="race">${raceOpts}</select>
            <select data-field="difficulty">${diffOpts}</select>`;
        row.querySelector('[data-field="race"]').onchange = e => { cfg.race = e.target.value; };
        row.querySelector('[data-field="difficulty"]').onchange = e => { cfg.difficulty = e.target.value; };
        wrap.appendChild(row);
    }
}

function sc2ConfirmPlay() {
    const m = sc2State.modalMap;
    if (!m) return;
    const mapStem = m.stem;
    const body = {
        map: mapStem, race: sc2State.race,
        opponents: sc2State.oppConfig.slice(0, sc2State.oppCount),
        mods: Array.from(sc2State.mods),
    };
    sc2CloseModal();
    fetch('/api/sc2/play', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => r.json())
        .then(res => {
            if (res.status === 'ok') {
                sc2SetBanner('🎮 正在启动 ' + mapStem + ' …（首次挂 mod 要烘焙几秒，SC2 窗口出来后正常操作）', 'info');
                sc2StartPolling();
            } else {
                sc2SetBanner('⚠️ ' + (res.message || '开局失败'), 'err');
            }
        })
        .catch(() => sc2SetBanner('⚠️ 请求失败，看 omni-deck 日志', 'err'));
}

function sc2RefreshStatus() {
    fetch('/api/sc2/status').then(r => r.json()).then(st => {
        document.querySelectorAll('.sc2-map-card').forEach(c => c.classList.toggle('playing', !!st.running));
        if (st.running) {
            sc2SetBanner('🎮 对局进行中（' + (st.last_map || '') + '）…', 'info');
            sc2StartPolling();
        } else if (st.last_result) {
            const ok = /Victory/i.test(st.last_result);
            const bad = /Error/i.test(st.last_result);
            sc2SetBanner((ok ? '🏆 胜利！' : bad ? '⚠️ ' : '💀 ') + st.last_result, bad ? 'err' : (ok ? 'ok' : 'info'));
        }
    }).catch(() => {});
}

function sc2StartPolling() {
    if (sc2State.polling) return;
    sc2State.polling = true;
    const tick = () => {
        fetch('/api/sc2/status').then(r => r.json()).then(st => {
            document.querySelectorAll('.sc2-map-card').forEach(c => c.classList.toggle('playing', !!st.running));
            if (st.running) {
                sc2SetBanner('🎮 对局进行中（' + (st.last_map || '') + '）…', 'info');
                setTimeout(tick, 4000);
            } else {
                sc2State.polling = false;
                if (st.last_result) {
                    const ok = /Victory/i.test(st.last_result);
                    const bad = /Error/i.test(st.last_result);
                    sc2SetBanner((ok ? '🏆 胜利！' : bad ? '⚠️ ' : '💀 ') + st.last_result, bad ? 'err' : (ok ? 'ok' : 'info'));
                }
            }
        }).catch(() => { sc2State.polling = false; });
    };
    setTimeout(tick, 4000);
}
