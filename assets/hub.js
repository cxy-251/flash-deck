// 全局 Fetch 拦截器：自动携带 NSFW 隐私访问 Token (用于局域网设备免密放行)
(function() {
    const _origFetch = window.fetch;
    window.fetch = function(url, init) {
        init = init || {};
        const token = localStorage.getItem('omni_nsfw_token');
        if (token) {
            if (!init.headers) {
                init.headers = {};
            }
            if (init.headers instanceof Headers) {
                if (!init.headers.has('X-Omni-Token')) init.headers.set('X-Omni-Token', token);
            } else if (Array.isArray(init.headers)) {
                init.headers.push(['X-Omni-Token', token]);
            } else {
                if (!init.headers['X-Omni-Token']) init.headers['X-Omni-Token'] = token;
            }
        }
        return _origFetch(url, init);
    };
})();

// NSFW 隐私授权与访问控制全局状态
let isDeckLocal = (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');
let isNsfwUnlocked = isDeckLocal;
try {
    const cachedAuth = localStorage.getItem('omni_nsfw_unlocked') ?? sessionStorage.getItem('omni_nsfw_unlocked');
    if (cachedAuth !== null) {
        isNsfwUnlocked = (cachedAuth === '1');
    }
} catch(e) {}
let nsfwModalView = 'unlock'; // 'unlock' | 'unlocked' | 'change'

function cleanupCatInitStyle() {
    try {
        document.querySelectorAll('.cat-init-style, #cat-init-style').forEach(el => el.remove());
    } catch(e) {}
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', cleanupCatInitStyle);
} else {
    cleanupCatInitStyle();
}

function updateNsfwUI() {
    const gameBtn = document.getElementById('game-nsfw-lock-btn');
    const gameIcon = document.getElementById('game-nsfw-lock-icon');
    const gameText = document.getElementById('game-nsfw-lock-text');

    if (isNsfwUnlocked) {
        document.body.classList.remove('nsfw-locked');
        document.documentElement.classList.remove('nsfw-locked');
        const initStyle = document.getElementById('nsfw-init-style');
        if (initStyle) initStyle.remove();

        const btnLabel = isDeckLocal ? '实体机已解锁' : '隐私已解锁';
        if (gameIcon) gameIcon.textContent = '🔓';
        if (gameText) gameText.textContent = btnLabel;
        if (gameBtn) {
            gameBtn.classList.add('active');
            gameBtn.title = isDeckLocal ? 'Steam Deck 实体机免密完全放行' : '当前设备已授权解锁 NSFW 专区';
        }
    } else {
        document.body.classList.add('nsfw-locked');
        document.documentElement.classList.add('nsfw-locked');

        if (gameIcon) gameIcon.textContent = '🔒';
        if (gameText) gameText.textContent = '隐私锁定';
        if (gameBtn) {
            gameBtn.classList.remove('active');
            gameBtn.title = 'NSFW 专区已锁定并隐形，点击输入密码解锁';
        }

        // 若当前处于敏感页面，强制重定向至安全区域
        if (typeof activePrimarySection !== 'undefined' && activePrimarySection === 'games') {
            if (currentTab === 'rpg' || currentTab === 'slg') {
                showPortalView();
            }
        } else if (typeof activePrimarySection !== 'undefined' && activePrimarySection === 'media') {
            if (activeMediaTab === 'manga' || activeMediaTab === 'novels' || activeMediaTab === 'audio') {
                switchMediaTab('docs');
            }
        }
    }
}

function checkNsfwStatus() {
    return fetch('/api/auth/status?t=' + Date.now())
        .then(r => r.json())
        .then(status => {
            if (status) {
                isDeckLocal = !!status.is_local;
                const prev = isNsfwUnlocked;
                isNsfwUnlocked = !!status.unlocked;
                try { 
                    localStorage.setItem('omni_nsfw_unlocked', isNsfwUnlocked ? '1' : '0');
                    sessionStorage.setItem('omni_nsfw_unlocked', isNsfwUnlocked ? '1' : '0'); 
                } catch(e) {}
                updateNsfwUI();
                if ((isNsfwUnlocked !== prev) || (!prev && isNsfwUnlocked) || (typeof allGames !== 'undefined' && allGames.length > 0)) {
                    if (typeof applyFilter === 'function') {
                        applyFilter();
                    }
                }
            }
            return status;
        })
        .catch(() => {});
}

function openNsfwModal() {
    const modal = document.getElementById('nsfw-lock-modal');
    if (!modal) return;
    modal.style.display = 'flex';

    if (isNsfwUnlocked) {
        switchNsfwModalView('unlocked');
    } else {
        switchNsfwModalView('unlock');
    }
}

function closeNsfwModal() {
    const modal = document.getElementById('nsfw-lock-modal');
    if (modal) modal.style.display = 'none';
    const pwdInput = document.getElementById('nsfw-password-input');
    if (pwdInput) pwdInput.value = '';
    const oldPwd = document.getElementById('nsfw-old-pwd-input');
    if (oldPwd) oldPwd.value = '';
    const newPwd = document.getElementById('nsfw-new-pwd-input');
    if (newPwd) newPwd.value = '';
    hideNsfwMsgs();
}

function hideNsfwMsgs() {
    ['nsfw-unlock-msg', 'nsfw-unlocked-msg', 'nsfw-change-msg'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.textContent = ''; }
    });
}

function switchNsfwModalView(view) {
    hideNsfwMsgs();
    const vUnlock = document.getElementById('nsfw-view-unlock');
    const vUnlocked = document.getElementById('nsfw-view-unlocked');
    const vChange = document.getElementById('nsfw-view-change');
    const titleEl = document.getElementById('nsfw-modal-title');
    const iconEl = document.getElementById('nsfw-modal-icon');
    const btnBack = document.getElementById('nsfw-btn-back');
    const btnCancel = document.getElementById('nsfw-btn-cancel');
    const btnAction = document.getElementById('nsfw-btn-action');

    if (view === 'back') {
        view = isNsfwUnlocked ? 'unlocked' : 'unlock';
    }
    nsfwModalView = view;

    if (view === 'unlock') {
        if (vUnlock) vUnlock.style.display = 'block';
        if (vUnlocked) vUnlocked.style.display = 'none';
        if (vChange) vChange.style.display = 'none';
        if (titleEl) titleEl.textContent = 'NSFW 隐私安全验证';
        if (iconEl) iconEl.textContent = '🔐';
        if (btnBack) btnBack.style.display = 'none';
        if (btnCancel) btnCancel.style.display = 'inline-flex';
        if (btnAction) {
            btnAction.style.display = 'inline-flex';
            btnAction.textContent = '立即解锁';
            btnAction.style.background = '#238636';
            btnAction.style.borderColor = '#2ea043';
            btnAction.onclick = submitNsfwUnlock;
        }
        setTimeout(() => {
            const p = document.getElementById('nsfw-password-input');
            if (p) p.focus();
        }, 100);
    } else if (view === 'unlocked') {
        if (vUnlock) vUnlock.style.display = 'none';
        if (vUnlocked) vUnlocked.style.display = 'block';
        if (vChange) vChange.style.display = 'none';
        if (titleEl) titleEl.textContent = 'NSFW 隐私状态管理';
        if (iconEl) iconEl.textContent = '🔓';
        if (btnBack) btnBack.style.display = 'none';
        if (btnCancel) btnCancel.style.display = 'none';
        if (btnAction) {
            if (isDeckLocal) {
                btnAction.style.display = 'none';
            } else {
                btnAction.style.display = 'inline-flex';
                btnAction.textContent = '🔒 重新上锁 (隐形)';
                btnAction.style.background = '#da3633';
                btnAction.style.borderColor = '#f85149';
                btnAction.onclick = submitNsfwLock;
            }
        }
        const descEl = document.getElementById('nsfw-unlocked-desc');
        if (descEl) {
            descEl.textContent = isDeckLocal
                ? '当前处于 Steam Deck 实体机环境，默认免密完全放行。局域网/广域网访客需输入密码方可解锁。'
                : '敏感专区（RPG Maker、SLG、漫画、小说、音声）已全部展示。如需离开或避免他人借用设备，可随时在此重新上锁。';
        }
    } else if (view === 'change') {
        if (vUnlock) vUnlock.style.display = 'none';
        if (vUnlocked) vUnlocked.style.display = 'none';
        if (vChange) vChange.style.display = 'block';
        if (titleEl) titleEl.textContent = '修改全局访问密码';
        if (iconEl) iconEl.textContent = '🔑';
        if (btnBack) btnBack.style.display = 'inline-flex';
        if (btnCancel) btnCancel.style.display = 'none';
        if (btnAction) {
            btnAction.style.display = 'inline-flex';
            btnAction.textContent = '保存新密码';
            btnAction.style.background = '#1f6feb';
            btnAction.style.borderColor = '#388bfd';
            btnAction.onclick = submitNsfwChangePassword;
        }
        setTimeout(() => {
            const p = document.getElementById('nsfw-old-pwd-input');
            if (p) p.focus();
        }, 100);
    }
}

function submitNsfwUnlock() {
    const pwdInput = document.getElementById('nsfw-password-input');
    const chkRemember = document.getElementById('nsfw-remember-checkbox');
    const msgEl = document.getElementById('nsfw-unlock-msg');
    const pwd = (pwdInput ? pwdInput.value : '').trim();
    const remember = chkRemember ? chkRemember.checked : true;

    if (!pwd) {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '请输入访问密码';
        }
        return;
    }

    fetch('/api/auth/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd, remember: remember })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success && res.token) {
            localStorage.setItem('omni_nsfw_token', res.token);
            isNsfwUnlocked = true;
            updateNsfwUI();
            closeNsfwModal();
            try {
                localStorage.removeItem('omni_games_cache');
                sessionStorage.removeItem('omni_games_cache');
            } catch(e) {}
            loadGames();
            if (typeof activePrimarySection !== 'undefined' && activePrimarySection === 'media') {
                prewarmMediaLibraries();
                if (activeMediaTab === 'manga') loadMangaLibrary();
                else if (activeMediaTab === 'novels') loadNovelsLibrary();
                else if (activeMediaTab === 'audio') loadAudioLibrary(true);
            }
            if (typeof showMegaToast === 'function') {
                showMegaToast('✅ 已成功解锁 NSFW 隐私专区！');
            }
        } else {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#f85149';
                msgEl.textContent = res.error || '密码错误，请重试';
            }
        }
    })
    .catch(err => {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '网络请求失败，请稍后重试';
        }
    });
}

function submitNsfwLock() {
    fetch('/api/auth/lock', { method: 'POST' })
        .finally(() => {
            localStorage.removeItem('omni_nsfw_token');
            try {
                localStorage.removeItem('omni_games_cache');
                sessionStorage.removeItem('omni_games_cache');
            } catch(e) {}
            isNsfwUnlocked = false;
            updateNsfwUI();
            closeNsfwModal();
            loadGames();
            if (typeof showMegaToast === 'function') {
                showMegaToast('🔒 NSFW 专区已重新锁定并隐形');
            }
        });
}

function submitNsfwChangePassword() {
    const oldPwd = document.getElementById('nsfw-old-pwd-input').value;
    const newPwd = document.getElementById('nsfw-new-pwd-input').value;
    const msgEl = document.getElementById('nsfw-change-msg');

    if (!newPwd || newPwd.length < 4) {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '新密码长度至少需要 4 位字符';
        }
        return;
    }

    fetch('/api/auth/change_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success) {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#3fb950';
                msgEl.textContent = '✅ 密码修改成功！';
            }
            if (typeof showMegaToast === 'function') {
                showMegaToast('✅ 访问密码修改成功！');
            }
            setTimeout(() => {
                switchNsfwModalView(isNsfwUnlocked ? 'unlocked' : 'unlock');
            }, 1200);
        } else {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#f85149';
                msgEl.textContent = res.error || '原密码错误，修改失败';
            }
        }
    })
    .catch(err => {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '网络请求失败，请稍后重试';
        }
    });
}

function submitNsfwAction() {
    if (nsfwModalView === 'unlock') {
        submitNsfwUnlock();
    } else if (nsfwModalView === 'unlocked') {
        submitNsfwLock();
    } else if (nsfwModalView === 'change') {
        submitNsfwChangePassword();
    }
}

// 客户端位置判定：默认本机（Steam Deck）优先，由后端 /api/lan/status 根据物理 Socket 来源 IP 权威仲裁
let isRemoteClient = false;
let allGames = [];
const _initUrlCat = new URLSearchParams(window.location.search).get('category');
let currentTab = (_initUrlCat && _initUrlCat !== 'portal')
    ? _initUrlCat
    : ((isDeckLocal || localStorage.getItem('omni_nsfw_token')) ? 'rpg' : 'standalone');
let currentStandaloneSubTab = null;
let currentSearchQuery = '';
let currentGameSearchQuery = '';


        function applyRemoteClientRestrictions() {
            if (!isRemoteClient) return;
            document.body.classList.add('remote-client');   // 驱动 CSS 隐藏联网/下载类控件
            const mSearch = document.getElementById('manga-search-input');
            if (mSearch) mSearch.placeholder = '🔍 搜索本机已收录的漫画...';
            const nSearch = document.getElementById('novel-search-input');
            if (nSearch) nSearch.placeholder = '🔍 搜索本机已收录的小说...';

            // 1. 灰显并禁用大厅门面的独立大作卡片
            const standaloneCard = document.querySelector('.standalone-card');
            if (standaloneCard) {
                standaloneCard.style.opacity = '0.42';
                standaloneCard.style.filter = 'grayscale(0.85)';
                standaloneCard.style.cursor = 'not-allowed';
                standaloneCard.style.borderColor = '#30363d';
                standaloneCard.title = '🔒 独立大作属于大型 PC/Wine 程序，仅限 Steam Deck 本机实体机窗口运行。';
                const actionEl = standaloneCard.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '🔒 仅限本机运行 (局域网禁用)';
                    actionEl.style.color = '#8b949e';
                }
                const badgeEl = standaloneCard.querySelector('.standalone-count');
                if (badgeEl) badgeEl.textContent = '🔒 本机独占';
            }

            // 2. 灰显并禁用大厅门面的 Flash 殿堂卡片
            const flashCard = document.querySelector('.flash-card');
            if (flashCard) {
                flashCard.style.opacity = '0.42';
                flashCard.style.filter = 'grayscale(0.85)';
                flashCard.style.cursor = 'not-allowed';
                flashCard.style.borderColor = '#30363d';
                flashCard.title = '🔒 Flash 游戏依赖 Steam Deck 本地 Pepper Flash 插件环境，外部浏览器不支持 Flash 运行。';
                const actionEl = flashCard.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '🔒 仅限本机运行 (外部不支持 Flash)';
                    actionEl.style.color = '#8b949e';
                }
                const badgeEl = flashCard.querySelector('#flash-count-badge');
                if (badgeEl) badgeEl.textContent = '🔒 本机独占';
            }

            // 2b. 灰显并禁用大厅门面的星际争霸2卡片（对战只能在 Steam Deck 实体机屏幕上跑）
            const sc2Card = document.querySelector('.sc2-card');
            if (sc2Card) {
                sc2Card.style.opacity = '0.42';
                sc2Card.style.filter = 'grayscale(0.85)';
                sc2Card.style.cursor = 'not-allowed';
                sc2Card.style.borderColor = '#30363d';
                sc2Card.title = '🔒 星际争霸2 对战仅限 Steam Deck 实体机屏幕运行，局域网禁止远程拉起。';
                const actionEl = sc2Card.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '🔒 仅限本机运行 (局域网禁用)';
                    actionEl.style.color = '#8b949e';
                }
                const badgeEl = sc2Card.querySelector('#sc2-count-badge');
                if (badgeEl) badgeEl.textContent = '🔒 本机独占';
            }

            // 3. 灰显并禁用分类切换栏中的独立游戏标签和 Flash 标签
            const standaloneTabBtn = document.querySelector('.tab-btn[data-tab="standalone"]');
            if (standaloneTabBtn) {
                standaloneTabBtn.style.opacity = '0.38';
                standaloneTabBtn.style.cursor = 'not-allowed';
                standaloneTabBtn.style.filter = 'grayscale(0.85)';
                standaloneTabBtn.title = '🔒 独立游戏专区仅限 Steam Deck 本机运行 (局域网已禁用)';
            }
            const flashTabBtn = document.querySelector('.tab-btn[data-tab="flash"]');
            if (flashTabBtn) {
                flashTabBtn.style.opacity = '0.38';
                flashTabBtn.style.cursor = 'not-allowed';
                flashTabBtn.style.filter = 'grayscale(0.85)';
                flashTabBtn.title = '🔒 Flash 殿堂仅限 Steam Deck 本机运行 (外部浏览器不支持 Flash)';
            }
            const sc2TabBtn = document.querySelector('.tab-btn[data-tab="sc2"]');
            if (sc2TabBtn) {
                sc2TabBtn.style.opacity = '0.38';
                sc2TabBtn.style.cursor = 'not-allowed';
                sc2TabBtn.style.filter = 'grayscale(0.85)';
                sc2TabBtn.title = '🔒 星际争霸2 对战仅限 Steam Deck 本机运行 (局域网已禁用)';
            }

            // 4. 隐藏网络能力开关 (局域网与广域网)：远程访客严禁操作服务端的网络能力，同时为移动端界面释放宝贵顶栏空间
            const lanControl = document.getElementById('lan-control-wrapper');
            const wanControl = document.getElementById('wan-control-wrapper');
            if (lanControl) lanControl.style.display = 'none';
            if (wanControl) wanControl.style.display = 'none';

            // 5. 局域网设备严禁访问个人 MEGA 网盘（保护个人账号凭证与隐私云盘数据）
            const megaTabBtn = document.getElementById('media-tab-mega');
            if (megaTabBtn) megaTabBtn.style.display = 'none';
            const megaView = document.getElementById('media-mega-view');
            if (megaView && typeof activeMediaTab !== 'undefined' && activeMediaTab === 'mega') {
                switchMediaTab('docs');
            }
        }

        function removeRemoteClientRestrictions() {
            // Steam Deck 本机环境：彻底恢复独立大作卡片与专区原本的生机与互动能力
            document.body.classList.remove('remote-client');
            const standaloneCard = document.querySelector('.standalone-card');
            if (standaloneCard) {
                standaloneCard.style.opacity = '';
                standaloneCard.style.filter = '';
                standaloneCard.style.cursor = '';
                standaloneCard.style.borderColor = '';
                standaloneCard.title = '';
                const actionEl = standaloneCard.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '进入专区 →';
                    actionEl.style.color = '';
                }
                const badgeEl = standaloneCard.querySelector('.standalone-count');
                if (badgeEl) {
                    const cnt = allGames.filter(g => g.type === 'standalone').length;
                    badgeEl.textContent = cnt + ' Games';
                }
            }

            const flashCard = document.querySelector('.flash-card');
            if (flashCard) {
                flashCard.style.opacity = '';
                flashCard.style.filter = '';
                flashCard.style.cursor = '';
                flashCard.style.borderColor = '';
                flashCard.title = '';
                const actionEl = flashCard.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '进入专区 →';
                    actionEl.style.color = '';
                }
                const badgeEl = flashCard.querySelector('#flash-count-badge');
                if (badgeEl) {
                    const cnt = allGames.filter(g => g.type === 'flash').length;
                    badgeEl.textContent = cnt + ' Games';
                }
            }

            const sc2Card = document.querySelector('.sc2-card');
            if (sc2Card) {
                sc2Card.style.opacity = '';
                sc2Card.style.filter = '';
                sc2Card.style.cursor = '';
                sc2Card.style.borderColor = '';
                sc2Card.title = '';
                const actionEl = sc2Card.querySelector('.cat-action');
                if (actionEl) {
                    actionEl.innerHTML = '进入专区 →';
                    actionEl.style.color = '';
                }
                const badgeEl = sc2Card.querySelector('#sc2-count-badge');
                if (badgeEl) badgeEl.textContent = '离线对战';
            }

            const standaloneTabBtn = document.querySelector('.tab-btn[data-tab="standalone"]');
            if (standaloneTabBtn) {
                standaloneTabBtn.style.opacity = '';
                standaloneTabBtn.style.cursor = '';
                standaloneTabBtn.style.filter = '';
                standaloneTabBtn.title = '';
            }
            const flashTabBtn = document.querySelector('.tab-btn[data-tab="flash"]');
            if (flashTabBtn) {
                flashTabBtn.style.opacity = '';
                flashTabBtn.style.cursor = '';
                flashTabBtn.style.filter = '';
                flashTabBtn.title = '';
            }
            const sc2TabBtn = document.querySelector('.tab-btn[data-tab="sc2"]');
            if (sc2TabBtn) {
                sc2TabBtn.style.opacity = '';
                sc2TabBtn.style.cursor = '';
                sc2TabBtn.style.filter = '';
                sc2TabBtn.title = '';
            }

            // 恢复本机网络能力控制按钮显示
            const lanControl = document.getElementById('lan-control-wrapper');
            const wanControl = document.getElementById('wan-control-wrapper');
            if (lanControl) lanControl.style.display = 'inline-flex';
            if (wanControl) wanControl.style.display = 'inline-flex';

            // 恢复本机 MEGA 标签页显示
            const megaTabBtn = document.getElementById('media-tab-mega');
            if (megaTabBtn) megaTabBtn.style.display = '';
        }

        // 一级板块状态 ('games' 或 'manga')
        let activePrimarySection = 'games';
        let localMangaList = [];
        let onlineMangaResults = [];
        let currentReaderCbz = '';
        let activeMangaSubView = 'shelf'; // 'shelf' 或 'online'
        let mangaTasksPollingTimer = null;
        let currentModalAlbumDetail = null;

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

            const targetUrl = status.url || (status.ip ? `http://${status.ip}:${status.port}` : 'http://127.0.0.1:8998');

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

            const domainUrl = status.url || 'https://omni.cxy251.uk';

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
                if (desc) desc.textContent = '开启后放行外部网络通过 https://omni.cxy251.uk 访问，出门在外随时看漫画！';
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

        function launchStandaloneGame(gid, title) {
            fetch('/api/games/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: gid, title: title })
            })
            .then(r => r.json())
            .then(res => {
                if (res.status === 'ok') {
                    alert(`🎮 正在 Steam Deck 屏幕启动 《${title}》！\n\n请直接查看 Deck 实体机屏幕或任务栏。`);
                } else {
                    alert('启动失败: ' + (res.error || res.message || '未知错误'));
                }
            })
            .catch(err => alert('启动请求失败: ' + err));
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
                url = (currentWanStatus && currentWanStatus.url) ? currentWanStatus.url : 'https://omni.cxy251.uk';
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

        // 收藏夹管理 (永久存储于 localStorage)
        function getFavorites() {
            try {
                return JSON.parse(localStorage.getItem('rpgweb_favorites') || '[]');
            } catch(e) {
                return [];
            }
        }

        function saveFavorites(favs) {
            localStorage.setItem('rpgweb_favorites', JSON.stringify(favs));
            updateFavBadges();
        }

        function toggleFavorite(e, gameId) {
            e.preventDefault();
            e.stopPropagation();
            let favs = getFavorites();
            if (favs.includes(gameId)) {
                favs = favs.filter(id => id !== gameId);
            } else {
                favs.push(gameId);
            }
            saveFavorites(favs);
            applyFilter();
        }

        function updateFavBadges() {
            const favs = getFavorites();
            const badge = document.getElementById('fav-count-badge');
            if (badge) badge.textContent = favs.length + ' Favorites';
        }

        function showPortalView() {
            document.querySelectorAll('.cat-init-style, #cat-init-style').forEach(el => el.remove());
            document.getElementById('portal-view').style.display = 'block';
            document.getElementById('list-view').style.display = 'none';
            document.getElementById('list-controls').style.display = 'none';
            document.getElementById('nav-back-btn').style.display = 'none';
            const gSearch = document.getElementById('game-search-input');
            if (gSearch) gSearch.value = '';
            currentSearchQuery = '';
            currentGameSearchQuery = '';
            currentTab = isNsfwUnlocked ? 'rpg' : 'standalone';
            currentStandaloneSubTab = null;
            document.querySelectorAll('#standalone-sub-filters .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
            if (window.history && window.history.replaceState) {
                window.history.replaceState(null, '', window.location.pathname);
            }
            window.scrollTo({ top: 0, behavior: 'instant' });
        }

        function openCategory(cat) {
            if (!isNsfwUnlocked && (cat === 'rpg' || cat === 'slg')) {
                openNsfwModal();
                return;
            }
            if (isRemoteClient && cat === 'standalone') {
                alert('🔒 独立大作专区属于大型 PC / Windows / Wine 程序，仅限 Steam Deck 实体机本机窗口游玩。\n\n局域网访问已禁用此专区，防止外部并发唤醒导致掌机卡顿！');
                return;
            }
            if (isRemoteClient && cat === 'flash') {
                alert('🔒 Flash 殿堂专区依赖 Steam Deck 本地 Pepper Flash 插件环境，外部浏览器不支持运行。\n\n局域网访问已禁用此专区。');
                return;
            }
            if (isRemoteClient && cat === 'sc2') {
                alert('🔒 星际争霸2 对战仅限在 Steam Deck 实体机屏幕上运行，局域网禁止远程拉起。');
                return;
            }
            cleanupCatInitStyle();
            document.getElementById('portal-view').style.display = 'none';
            document.getElementById('list-view').style.display = 'block';
            document.getElementById('list-controls').style.display = 'flex';
            document.getElementById('nav-back-btn').style.display = 'flex';
            currentTab = cat;
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === cat);
            });
            applyFilter();
        }

        function switchStandaloneSubTab(sub, el) {
            if (currentStandaloneSubTab === sub) {
                currentStandaloneSubTab = null;
                if (el) el.classList.remove('active');
            } else {
                currentStandaloneSubTab = sub;
                document.querySelectorAll('#standalone-sub-filters .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
                if (el) el.classList.add('active');
            }
            applyFilter();
        }

        function switchTab(tab, el) {
            if (!isNsfwUnlocked && (tab === 'rpg' || tab === 'slg')) {
                openNsfwModal();
                return;
            }
            if (isRemoteClient && tab === 'standalone') {
                alert('🔒 独立大作专区属于大型 PC / Windows / Wine 程序，仅限 Steam Deck 实体机本机窗口游玩。\n\n局域网访问已禁用此专区，防止外部并发唤醒导致掌机卡顿！');
                return;
            }
            if (isRemoteClient && tab === 'flash') {
                alert('🔒 Flash 殿堂专区依赖 Steam Deck 本地 Pepper Flash 插件环境，外部浏览器不支持运行。\n\n局域网访问已禁用此专区。');
                return;
            }
            if (isRemoteClient && tab === 'sc2') {
                alert('🔒 星际争霸2 对战仅限在 Steam Deck 实体机屏幕上运行，局域网禁止远程拉起。');
                return;
            }
            cleanupCatInitStyle();
            currentTab = tab;
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === tab);
            });
            applyFilter();
        }

        function onGameSearchInput(val) {
            currentSearchQuery = (val || '').trim().toLowerCase();
            currentGameSearchQuery = currentSearchQuery;
            if (currentSearchQuery && document.getElementById('portal-view').style.display !== 'none') {
                openCategory('rpg');
            } else {
                applyFilter();
            }
        }

        // ================= 全量 3000+ 字符级繁简双向智能转换与模糊匹配 =================
        const T_CHARS = "㑯㑳㑶㓨㘚㜄㜏㠏㥮㩜㩳㩵䁻䃮䊷䋙䋚䋹䋻䍦䎱䙡䜀䝼䥇䥑䥱䦛䦟䯀䰾䱷䱽䲁䲘䴉丟並乘乾亂亙亞佇佈佔佛併來侖侶侷俁係俔俠俥俬倀倆倈倉個們倖倫倲假偉偑側偵偽傌傑傖傘備傢傭傯傳傴債傷傾僂僅僉僑僕僞僥僨僱價儀儁儂億儈儉儎儐儔儕儘償優儲儷儸儺儻儼兇兌兒兗內兩冊冑冪凈凍凜凱別刪剄則剋剎剗剛剝剩剮剴創剷劃劇劉劊劌劍劏劑劚勁動務勛勝勞勢勩勱勳勵勸勻匭匯匱區協卷卹卻卽厙厠厤厭厲厴參叄叢吒吳吶呂咒咼員唄唸問啓啞啟啢喎喚喪喫喬單喲嗆嗇嗊嗎嗚嗩嗶嘆嘍嘓嘔嘖嘗嘜嘩嘮嘯嘰嘵嘸嘽噁噓噚噝噠噥噦噯噲噴噸噹嚀嚇嚌嚐嚕嚙嚥嚦嚨嚮嚲嚳嚴嚶囀囁囂囅囈囉囌囑囪圇圈國圍園圓圖團垻埡埰執堅堊堖堝堯報場塊塋塏塒塗塚塢塤塵塹墊墜增墮墰墳墶墻墾壇壋壎壓壘壙壚壜壞壟壠壢壤壩壪壯壹壺壼壽夠夢夥夾奐奧奩奪奬奮奼妝姍姦娛婁婦婭媧媯媰媼媽嫋嫗嫵嫺嫻嫿嬀嬃嬈嬋嬌嬙嬡嬤嬪嬰嬸孃孋孌孫學孿宮寀寢實寧審寫寬寵寶將專尋對導尷屆屍屓屜屢層屨屬岡峯峴島峽崍崑崗崙崢崬嵐嵗嵾嶁嶄嶇嶔嶗嶠嶢嶧嶨嶮嶸嶺嶼嶽巋巒巔巖巢巰巹帥師帳帶幀幃幓幗幘幟幣幫幬幹幾庫廁廂廄廈廎廕廚廝廟廠廡廢廣廩廬廳弒弔弳張強彆彈彌彎彔彙彠彥彫彲彿後徑從徠復徵德徹恆恥悅悞悵悶悽惠惡惱惲惻愛愜愨愴愷愾慄態慍慘慚慟慣慤慪慫慮慳慶慺慼慾憂憊憐憑憒憖憚憤憫憮憲憶懇應懌懍懞懟懣懤懨懲懶懷懸懺懼懾戀戇戔戧戩戰戱戲戶戾拂拋拔拜挩挱挾捨捫捱捲掃掄掆掗掙掛採揀插揚換揭揮揯損搔搖搗搜搵搶摑摜摟摯摳摶摺摻撈撏撐撓撝撟撣撥撫撲撳撻撾撿擁擄擇擊擋擓擔據擠擣擬擯擰擱擲擴擷擺擻擼擽擾攄攆攏攔攖攙攛攜攝攢攣攤攪攬收效敎敓敕敗敘敵數斂斃斆斕斬斷於旂旣昇時晉晚晝暈暉暘暢暨暫曄曆曇曉曏曖曠曨曬書曾會朧朮東枡枴查柵柺査桿梔梘條梟梲棄棊棖棗棟棡棧棱棲棶椏椲楊楓楨業極榆榘榦榪榮榲榿構槍槓槤槧槨槮槳槶槼樁樂樅樑樓標樞樢樣樧樫樳樸樹樺樿橈橋機橢橫檁檉檔檜檟檢檣檮檯檳檸檻櫃櫓櫚櫛櫝櫞櫟櫥櫧櫨櫪櫫櫬櫱櫳櫸櫻欄欅權欏欒欖欞欽歎歐歟歡步歲歷歸歿殘殞殤殨殫殭殮殯殰殲殺殻殼毀毆每毿氂氈氌氣氫氬氳氾汎汙污決沒沖況泝洩洶浹涇涉涗涼淒淚淥淨淩淪淵淶淺渙減渢渦測渴渾湊湞湧湯溈準溝溪溫溮溳溼滄滅滌滎滙滬滯滲滷滸滻滾滿漁漊漚漢漣漬漲漵漸漿潁潑潔潙潚潛潤潯潰潷潿澀澆澇澐澗澠澤澦澩澮澱澾濁濃濄濕濘濚濛濜濟濤濧濫濰濱濺濼濾瀂瀅瀆瀇瀉瀋瀏瀕瀘瀝瀟瀠瀦瀧瀨瀰瀲瀾灃灄灑灕灘灝灡灣灤灧灩災為烏烴無焰煉煒煙煢煥煩煬煱熅熒熗熱熲熾燁燈燉燒燙燜營燦燬燭燴燶燻燼燾爍爐爛爭爲爺爾牀牆牘牽犖犛犢犧狀狹狽猙猶猻獁獃獄獅獎獨獪獫獮獰獱獲獵獷獸獺獻獼玀現琱琺琿瑋瑒瑣瑤瑩瑪瑲璉璡璣璦璫璯環璵璸璽璿瓊瓏瓔瓚瓣甌甕產産甦甯畝畢畫異畵當疇疊疎痙痠痹痾瘂瘋瘍瘓瘞瘡瘦瘧瘮瘲瘺瘻療癆癇癉癒癘癟癡癢癤癥癧癩癬癭癮癰癱癲發皁皋皚皰皸皺盃盜盞盡監盤盧盪眞眥眾睏睜睞瞘瞜瞞瞶瞼矇矓矚矯硃硜硤硨硯碎碕碩碭碸確碼碽磑磚磠磣磧磯磽磾礄礆礎礙礦礪礫礬礱祕祿禍禎禕禡禦禪禮禰禱禿秈稅稈稏稜稟種稱稻穀穇穌積穎穗穠穡穢穩穫穭穰窩窪窮窯窵窶窺竄竅竇竈竊竪競筆筍筧筴箇箋箏節範築篋篔篠篤篩篳簀簍簑簞簡簣簫簹簽簾籃籌籔籙籛籜籟籠籤籩籪籬籮籲粵粹糉糝糞糧糰糲糴糶糹糾紀紂約紅紆紇紈紉紋納紐紓純紕紖紗紘紙級紛紜紝紡紬紮細紱紲紳紵紹紺紼紿絀終絃組絅絆絎結絕絛絝絞絡絢給絨絰統絲絳絶絹綁綃綆綈綉綌綏綐綑經綜綞綠綢綣綫綬維綯綰綱網綳綴綵綸綹綺綻綽綾綿緄緇緊緋緑緒緓緔緖緗緘緙線緝緞締緡緣緦編緩緬緯緱緲練緶緹緻緼縈縉縊縋縐縑縕縗縛縝縞縟縣縧縫縭縮縱縲縳縴縵縶縷縹總績繃繅繆繒織繕繚繞繡繢繩繪繫繭繮繯繰繳繸繹繼繽繾繿纇纈纊續纍纏纓纔纖纘纜缺缽罃罈罌罎罐罰罵罷羅羆羈羋羣羥羨義羶習翫翬翹翽耬耮聖聞聯聰聲聳聵聶職聹聽聾肅脅脈脛脣脩脫脹腎腖腡腦腫腳腸膃膕膚膞膠膩膽膾膿臉臍臏臘臚臟臠臢臥臨臺與興舉舊舍舘艙艤艦艫艱艷芻苧茲荊荔莊莖莢莧華菴菸萇萊萬萴萵葉葒葤葦葯葷蒐蒓蒔蒕蒞蒼蓀蓆蓋蓮蓯蓴蓽蔔蔘蔞蔣蔥蔦蔭蕁蕆蕎蕒蕓蕕蕘蕢蕩蕪蕭蕷薀薈薊薌薑薔薘薟薦薩薰薳薴薵薹薺藍藎藏藝藥藪藭藴藶藹藺蘀蘄蘆蘇蘊蘋蘚蘞蘢蘭蘺蘿虆處虛虜號虧虯蛺蛻蜆蝕蝟蝦蝨蝸螄螞螢螮螻螿蟄蟈蟎蟣蟬蟯蟲蟶蟻蠁蠅蠆蠍蠐蠑蠔蠟蠣蠨蠱蠶蠻衆衊術衕衚衛衝袞裊裏補裝裡製複褌褘褲褳褸褻襇襉襏襖襝襠襤襪襬襯襲襴覈見覎規覓視覘覡覥覦親覬覯覲覷覺覽覿觀觴觶觸訁訂訃計訊訌討訐訒訓訕訖託記訛訝訟訢訣訥訩訪設許訴訶診註証詁詆詎詐詒詔評詖詗詘詛詞詠詡詢詣試詩詫詬詭詮詰話該詳詵詼詿誄誅誆誇誌認誑誒誕誘誚語誠誡誣誤誥誦誨說説誰課誶誹誼誾調諂諄談諉請諍諏諑諒論諗諛諜諝諞諡諢諤諦諧諫諭諮諱諳諶諷諸諺諼諾謀謁謂謄謅謊謎謐謔謖謗謙謚講謝謠謡謨謫謬謭謳謹謾譁證譎譏譖識譙譚譜譟譫譭譯議譴護譸譽譾讀讅變讋讌讎讒讓讕讖讚讜讞豈豎豐豔豫豬豶貓貙貝貞貟負財貢貧貨販貪貫責貯貰貲貳貴貶買貸貺費貼貽貿賀賁賂賃賄賅資賈賊賑賒賓賕賙賚賜賞賠賡賢賣賤賦賧質賫賬賭賰賴賵賺賻購賽賾贄贅贇贈贊贋贍贏贐贓贔贖贗贛贜赬趕趙趨趲跡踐踰踴蹌蹕蹟蹠蹣蹤蹺躂躉躊躋躍躎躑躒躓躕躚躡躥躦躪軀車軋軌軍軑軒軔軛軟軤軫軲軸軹軺軻軼軾較輅輇輈載輊輒輓輔輕輛輜輝輞輟輥輦輩輪輬輯輳輸輻輼輾輿轀轂轄轅轆轉轍轎轔轟轡轢轤辦辨辭辮辯農迴逕這連週進遊運過達違遙遜遞遠遡遥適遲遷選遺遼邁還邇邊邏邐郟郵鄆鄉鄒鄔鄖鄧鄭鄰鄲鄴鄶鄺酇酈酢醃醉醖醜醞醟醣醫醬醱釀釁釃釅釋釐釒釓釔釕釗釘釙針釣釤釦釧釩釵釷釹釺釾鈀鈁鈃鈄鈅鈈鈉鈍鈎鈐鈑鈒鈔鈕鈞鈡鈣鈥鈦鈧鈮鈰鈳鈴鈷鈸鈹鈺鈽鈾鈿鉀鉅鉆鉈鉉鉋鉍鉑鉕鉗鉚鉛鉞鉢鉤鉦鉬鉭鉳鉶鉸鉺鉻鉿銀銃銅銍銑銓銖銘銚銛銜銠銣銥銦銨銩銪銫銬銱銳銷銹銻銼鋁鋃鋅鋇鋌鋏鋒鋙鋝鋟鋣鋤鋥鋦鋨鋩鋪鋭鋮鋯鋰鋱鋶鋸鋼錁錄錆錇錈錏錐錒錕錘錙錚錛錟錠錡錢錦錨錩錫錮錯録錳錶錸錼鍀鍁鍃鍅鍆鍇鍈鍊鍋鍍鍔鍘鍚鍛鍠鍤鍥鍩鍬鍰鍵鍶鍺鍼鍾鎂鎄鎇鎊鎌鎔鎖鎘鎚鎛鎡鎢鎣鎦鎧鎩鎪鎬鎭鎮鎰鎲鎳鎵鎶鎸鎿鏃鏇鏈鏌鏍鏐鏑鏗鏘鏜鏝鏞鏟鏡鏢鏤鏨鏰鏵鏷鏹鏺鏽鐃鐋鐐鐒鐓鐔鐘鐙鐝鐠鐥鐦鐧鐨鐫鐮鐯鐲鐳鐵鐶鐸鐺鐿鑄鑊鑌鑑鑒鑔鑕鑛鑞鑠鑣鑥鑭鑰鑱鑲鑷鑹鑼鑽鑾鑿钁钂長門閂閃閆閈閉開閌閎閏閑閒間閔閘閡閣閤閥閨閩閫閬閭閱閲閶閹閻閼閽閾閿闃闆闇闈闊闋闌闍闐闒闓闔闕闖關闞闠闡闢闤闥陘陝陞陣陰陳陷陸陽隉隊階隕際隨險隯隱隴隸隻雋雖雙雛雜雞離難雲電霑霢霧霸霽靂靄靆靈靉靚靜靝靦靨鞏鞝鞦鞽韁韃韆韉韋韌韍韓韙韜韝韞韻響頁頂頃項順頇須頊頌頎頏預頑頒頓頗領頜頡頤頦頭頮頰頲頴頷頸頹頻頽顆題額顎顏顒顓顔願顙顛類顢顥顧顫顬顯顰顱顳顴風颭颮颯颱颳颶颸颺颻颼飀飄飆飈飛飠飢飣飥飩飪飫飭飯飱飲飴飼飽飾飿餃餄餅餈餉養餌餎餏餑餒餓餕餖餘餚餛餜餞餡館餬餱餳餵餶餷餺餼餾餿饁饃饅饈饉饊饋饌饑饒饗饜饞饢馬馭馮馱馳馴馹駁駐駑駒駔駕駘駙駛駝駟駡駢駭駰駱駸駿騁騂騅騌騍騎騏騖騙騤騧騫騭騮騰騶騷騸騾驀驁驂驃驄驅驊驌驍驏驕驗驚驛驟驢驤驥驦驪驫骯髏髒髓體髕髖髮鬆鬍鬚鬢鬥鬧鬨鬩鬮鬱鬹魎魘魚魛魢魨魯魴魷魺鮁鮃鮊鮋鮍鮎鮐鮑鮒鮓鮚鮜鮝鮞鮣鮦鮪鮫鮭鮮鮳鮶鮺鯀鯁鯇鯉鯊鯒鯔鯕鯖鯗鯛鯝鯡鯢鯤鯧鯨鯪鯫鯰鯴鯷鯽鯿鰁鰂鰃鰆鰈鰉鰌鰍鰏鰐鰒鰓鰛鰜鰟鰠鰣鰥鰧鰨鰩鰭鰮鰱鰲鰳鰵鰷鰹鰺鰻鰼鰾鱂鱅鱈鱉鱒鱔鱖鱗鱘鱝鱟鱠鱣鱤鱧鱨鱭鱯鱷鱸鱺鳥鳧鳩鳬鳲鳳鳴鳶鳾鴆鴇鴉鴒鴕鴛鴝鴞鴟鴣鴦鴨鴯鴰鴴鴷鴻鴿鵁鵂鵃鵐鵑鵒鵓鵜鵝鵠鵡鵪鵬鵮鵯鵰鵲鵷鵾鶄鶇鶉鶊鶓鶖鶘鶚鶡鶥鶩鶪鶬鶯鶲鶴鶹鶺鶻鶼鶿鷀鷁鷂鷄鷉鷊鷓鷖鷗鷙鷚鷥鷦鷫鷯鷲鷳鷴鷸鷹鷺鷽鸂鸇鸊鸌鸏鸕鸘鸚鸛鸝鸞鹵鹹鹺鹼鹽麗麥麩麪麫麯麴麵麼麽黃黌黑默點黨黲黴黶黷黽黿鼂鼉鼕鼴齊齋齎齏齒齔齕齗齙齜齟齠齡齣齦齧齪齬齲齶齷龍龎龐龑龔龕龜鿁鿓";
        const S_CHARS = "㑔㑇㐹刾㘎㚯㛣㟆㤘㨫㧐擜䀥鿎䌶䌺䌻䌿䌾䍠䎬䙌䜧䞍䦂鿏䥾䦶䦷䯅鲃䲣䲝鳚鳤鹮丢并乗干乱亘亚伫布占仏并来仑侣局俣系伣侠伡私伥俩俫仓个们幸伦㑈仮伟㐽侧侦伪㐷杰伧伞备家佣偬传伛债伤倾偻仅佥侨仆伪侥偾雇价仪俊侬亿侩俭傤傧俦侪尽偿优储俪㑩傩傥俨凶兑儿兖内两册胄幂净冻凛凯别删刭则克刹刬刚剥剰剐剀创铲划剧刘刽刿剑㓥剂㔉劲动务勋胜劳势勚劢勋励劝匀匦汇匮区协巻恤却即厍厕历厌厉厣参叁丛咤吴呐吕呪呙员呗念问启哑启唡㖞唤丧吃乔单哟呛啬唝吗呜唢哔叹喽啯呕啧尝唛哗唠啸叽哓呒啴恶嘘㖊咝哒哝哕嗳哙喷吨当咛吓哜尝噜啮咽呖咙向亸喾严嘤啭嗫嚣冁呓啰苏嘱囱囵圏国围园圆图团坝垭采执坚垩垴埚尧报场块茔垲埘涂冢坞埙尘堑垫坠増堕坛坟垯墙垦坛垱埙压垒圹垆坛坏垄垅坜壌坝塆壮壱壶壸寿够梦伙夹奂奥奁夺奖奋姹妆姗奸娱娄妇娅娲妫㛀媪妈袅妪妩娴娴婳妫媭娆婵娇嫱嫒嬷嫔婴婶娘㛤娈孙学孪宫采寝实宁审写宽宠宝将专寻对导尴届尸屃屉屡层屦属冈峰岘岛峡崃昆岗仑峥岽岚岁㟥嵝崭岖嵚崂峤峣峄峃崄嵘岭屿岳岿峦巅岩巣巯卺帅师帐带帧帏㡎帼帻帜币帮帱干几库厕厢厩厦庼荫厨厮庙厂庑废广廪庐厅弑吊弪张强别弹弥弯录汇彟彦雕彨佛后径从徕复征徳彻恒耻悦悮怅闷凄恵恶恼恽恻爱惬悫怆恺忾栗态愠惨惭恸惯悫怄怂虑悭庆㥪戚欲忧惫怜凭愦慭惮愤悯怃宪忆恳应怿懔蒙怼懑㤽恹惩懒怀悬忏惧慑恋戆戋戗戬战戯戏户戻払抛抜拝捝挲挟舍扪挨卷扫抡㧏挜挣挂采拣挿扬换掲挥搄损掻摇捣捜揾抢掴掼搂挚抠抟折掺捞挦撑挠㧑挢掸拨抚扑揿挞挝捡拥掳择击挡㧟担据挤捣拟摈拧搁掷扩撷摆擞撸㧰扰摅撵拢拦撄搀撺携摄攒挛摊搅揽収効教敚勅败叙敌数敛毙敩斓斩断于旗既升时晋晩昼晕晖旸畅曁暂晔历昙晓向暧旷昽晒书曽会胧术东桝拐査栅拐查杆栀枧条枭棁弃棋枨枣栋㭎栈稜栖梾桠㭏杨枫桢业极楡矩干杩荣榅桤构枪杠梿椠椁椮桨椢椝桩乐枞梁楼标枢㭤样榝㭴桪朴树桦椫桡桥机椭横檩柽档桧槚检樯梼台槟柠槛柜橹榈栉椟橼栎橱槠栌枥橥榇蘖栊榉樱栏榉权椤栾榄棂钦叹欧欤欢歩岁历归殁残殒殇㱮殚僵殓殡㱩歼杀壳壳毁殴毎毵牦毡氇气氢氩氲泛泛污汚决没冲况溯泄汹浃泾渉涚凉凄泪渌净凌沦渊涞浅涣减沨涡测渇浑凑浈涌汤沩准沟渓温浉涢湿沧灭涤荥汇沪滞渗卤浒浐滚满渔溇沤汉涟渍涨溆渐浆颍泼洁沩㴋潜润浔溃滗涠涩浇涝沄涧渑泽滪泶浍淀㳠浊浓㳡湿泞溁蒙浕济涛㳔滥潍滨溅泺滤澛滢渎㲿泻沈浏濒泸沥潇潆潴泷濑弥潋澜沣滠洒漓滩灏㳕湾滦滟滟灾为乌烃无焔炼炜烟茕焕烦炀㶽煴荧炝热颎炽烨灯炖烧烫焖营灿毁烛烩㶶熏烬焘烁炉烂争为爷尔床墙牍牵荦牦犊牺状狭狈狰犹狲犸呆狱狮奖独狯猃狝狞㺍获猎犷兽獭献猕猡现雕珐珲玮玚琐瑶莹玛玱琏琎玑瑷珰㻅环玙瑸玺璇琼珑璎瓒弁瓯瓮产产苏宁亩毕画异画当畴叠疏痉酸痺疴痖疯疡痪瘗疮痩疟瘆疭瘘瘘疗痨痫瘅愈疠瘪痴痒疖症疬癞癣瘿瘾痈瘫癫发皂皐皑疱皲皱杯盗盏尽监盘卢荡真眦众困睁睐眍䁖瞒瞆睑蒙眬瞩矫朱硁硖砗砚砕埼硕砀砜确码䂵硙砖硵碜碛矶硗䃅硚硷础碍矿砺砾矾砻秘禄祸祯祎祃御禅礼祢祷秃籼税秆䅉棱禀种称稲谷䅟稣积颖穂秾穑秽稳获穞穣窝洼穷窑窎窭窥窜窍窦灶窃竖竞笔笋笕䇲个笺筝节范筑箧筼筿笃筛筚箦篓蓑箪简篑箫筜签帘篮筹䉤箓篯箨籁笼签笾簖篱箩吁粤粋粽糁粪粮团粝籴粜纟纠纪纣约红纡纥纨纫纹纳纽纾纯纰纼纱纮纸级纷纭纴纺䌷扎细绂绁绅纻绍绀绋绐绌终弦组䌹绊绗结绝绦绔绞络绚给绒绖统丝绛绝绢绑绡绠绨绣绤绥䌼捆经综缍绿绸绻线绶维绹绾纲网绷缀彩纶绺绮绽绰绫绵绲缁紧绯绿绪绬绱緒缃缄缂线缉缎缔缗缘缌编缓缅纬缑缈练缏缇致缊萦缙缢缒绉缣缊缞缚缜缟缛县绦缝缡缩纵缧䌸纤缦絷缕缥总绩绷缫缪缯织缮缭绕绣缋绳绘系茧缰缳缲缴䍁绎继缤缱䍀颣缬纩续累缠缨才纤缵缆欠钵䓨坛罂坛缶罚骂罢罗罴羁芈群羟羡义膻习玩翚翘翙耧耢圣闻联聪声耸聩聂职聍听聋肃胁脉胫唇修脱胀肾胨脶脑肿脚肠腽腘肤䏝胶腻胆脍脓脸脐膑腊胪脏脔臜卧临台与兴举旧舎馆舱舣舰舻艰艳刍苎兹荆茘庄茎荚苋华庵烟苌莱万荝莴叶荭荮苇药荤搜莼莳蒀莅苍荪席盖莲苁莼荜卜参蒌蒋葱茑荫荨蒇荞荬芸莸荛蒉荡芜萧蓣蕰荟蓟芗姜蔷荙莶荐萨薫䓕苧䓓苔荠蓝荩蔵艺药薮䓖蕴苈蔼蔺萚蕲芦苏蕴苹藓蔹茏兰蓠萝蔂处虚虏号亏虬蛱蜕蚬蚀猬虾虱蜗蛳蚂萤䗖蝼螀蛰蝈螨虮蝉蛲虫蛏蚁蚃蝇虿蝎蛴蝾蚝蜡蛎蟏蛊蚕蛮众蔑术同胡卫冲衮袅里补装里制复裈袆裤裢褛亵裥裥袯袄裣裆褴袜摆衬袭襕核见觃规觅视觇觋觍觎亲觊觏觐觑觉览觌观觞觯触讠订讣计讯讧讨讦讱训讪讫托记讹讶讼䜣诀讷讻访设许诉诃诊注证诂诋讵诈诒诏评诐诇诎诅词咏诩询诣试诗诧诟诡诠诘话该详诜诙诖诔诛诓夸志认诳诶诞诱诮语诚诫诬误诰诵诲说说谁课谇诽谊訚调谄谆谈诿请诤诹诼谅论谂谀谍谞谝谥诨谔谛谐谏谕咨讳谙谌讽诸谚谖诺谋谒谓誊诌谎谜谧谑谡谤谦谥讲谢谣谣谟谪谬谫讴谨谩哗证谲讥谮识谯谭谱噪谵毁译议谴护诪誉谫读谉变詟䜩雠谗让谰谶赞谠谳岂竖丰艳予猪豮猫䝙贝贞贠负财贡贫货贩贪贯责贮贳赀贰贵贬买贷贶费贴贻贸贺贲赂赁贿赅资贾贼赈赊宾赇赒赉赐赏赔赓贤卖贱赋赕质赍账赌䞐赖赗赚赙购赛赜贽赘赟赠赞赝赡赢赆赃赑赎赝赣赃赪赶赵趋趱迹践逾踊跄跸迹跖蹒踪跷跶趸踌跻跃䟢踯跞踬蹰跹蹑蹿躜躏躯车轧轨军轪轩轫轭软轷轸轱轴轵轺轲轶轼较辂辁辀载轾辄挽辅轻辆辎辉辋辍辊辇辈轮辌辑辏输辐辒辗舆辒毂辖辕辘转辙轿辚轰辔轹轳办弁辞辫辩农回迳这连周进游运过达违遥逊递远溯遙适迟迁选遗辽迈还迩边逻逦郏邮郓乡邹邬郧邓郑邻郸邺郐邝酂郦醋腌酔酝丑酝蒏糖医酱酦酿衅酾酽释厘钅钆钇钌钊钉钋针钓钐扣钏钒钗钍钕钎䥺钯钫钘钭钥钚钠钝钩钤钣钑钞钮钧钟钙钬钛钪铌铈钶铃钴钹铍钰钸铀钿钾巨钻铊铉铇铋铂钷钳铆铅钺钵钩钲钼钽锫铏铰铒铬铪银铳铜铚铣铨铢铭铫铦衔铑铷铱铟铵铥铕铯铐铞锐销锈锑锉铝锒锌钡铤铗锋铻锊锓铘锄锃锔锇铓铺锐铖锆锂铽锍锯钢锞录锖锫锩铔锥锕锟锤锱铮锛锬锭锜钱锦锚锠锡锢错录锰表铼镎锝锨锪钫钔锴锳炼锅镀锷铡钖锻锽锸锲锘锹锾键锶锗针钟镁锿镅镑镰镕锁镉锤镈镃钨蓥镏铠铩锼镐镇镇镒镋镍镓鿔镌镎镞旋链镆镙镠镝铿锵镗镘镛铲镜镖镂錾镚铧镤镪䥽锈铙铴镣铹镦镡钟镫镢镨䦅锎锏镄镌镰䦃镯镭铁镮铎铛镱铸镬镔鉴鉴镲锧鉱镴铄镳镥镧钥镵镶镊镩锣钻銮凿镢镋长门闩闪闫闬闭开闶闳闰闲闲间闵闸阂阁合阀闺闽阃阆闾阅阅阊阉阎阏阍阈阌阒板暗闱阔阕阑阇阗阘闿阖阙闯关阚阓阐辟阛闼陉陕升阵阴陈陥陆阳陧队阶陨际随险陦隐陇隶只隽虽双雏杂鸡离难云电沾霡雾覇霁雳霭叇灵叆靓静靔腼靥巩绱秋鞒缰鞑千鞯韦韧韨韩韪韬鞲韫韵响页顶顷项顺顸须顼颂颀颃预顽颁顿颇领颌颉颐颏头颒颊颋颕颔颈颓频颓颗题额颚颜颙颛颜愿颡颠类颟颢顾颤颥显颦颅颞颧风飐飑飒台刮飓飔飏飖飕飗飘飙飚飞饣饥饤饦饨饪饫饬饭飧饮饴饲饱饰饳饺饸饼糍饷养饵饹饻饽馁饿馂饾余肴馄馃饯馅馆糊糇饧喂馉馇馎饩馏馊馌馍馒馐馑馓馈馔饥饶飨餍馋馕马驭冯驮驰驯驲驳驻驽驹驵驾骀驸驶驼驷骂骈骇骃骆骎骏骋骍骓骔骒骑骐骛骗骙䯄骞骘骝腾驺骚骟骡蓦骜骖骠骢驱骅骕骁骣骄验惊驿骤驴骧骥骦骊骉肮髅脏髄体髌髋发松胡须鬓斗闹哄阋阄郁鬶魉魇鱼鱽鱾鲀鲁鲂鱿鲄鲅鲆鲌鲉鲏鲇鲐鲍鲋鲊鲒鲘鲞鲕䲟鲖鲔鲛鲑鲜鲓鲪鲝鲧鲠鲩鲤鲨鲬鲻鲯鲭鲞鲷鲴鲱鲵鲲鲳鲸鲮鲰鲶鲺鳀鲫鳊鳈鲗鳂䲠鲽鳇䲡鳅鲾鳄鳆鳃鳁鳒鳑鳋鲥鳏䲢鳎鳐鳍鳁鲢鳌鳓鳘鲦鲣鲹鳗鳛鳔鳉鳙鳕鳖鳟鳝鳜鳞鲟鲼鲎鲙鳣鳡鳢鲿鲚鳠鳄鲈鲡鸟凫鸠凫鸤凤鸣鸢䴓鸩鸨鸦鸰鸵鸳鸲鸮鸱鸪鸯鸭鸸鸹鸻䴕鸿鸽䴔鸺鸼鹀鹃鹆鹁鹈鹅鹄鹉鹌鹏鹐鹎雕鹊鹓鹍䴖鸫鹑鹒鹋鹙鹕鹗鹖鹛鹜䴗鸧莺鹟鹤鹠鹡鹘鹣鹚鹚鹢鹞鸡䴘鹝鹧鹥鸥鸷鹨鸶鹪鹔鹩鹫鹇鹇鹬鹰鹭鸴㶉鹯䴙鹱鹲鸬鹴鹦鹳鹂鸾卤咸鹾碱盐丽麦麸面面曲曲面么么黄黉黒黙点党黪霉黡黩黾鼋鼌鼍冬鼹齐斋赍齑齿龀龁龂龅龇龃龆龄出龈啮龊龉龋腭龌龙厐庞䶮龚龛龟䜤鿒";
        const T2S_MAP = {};
        for (let i = 0; i < T_CHARS.length; i++) {
            T2S_MAP[T_CHARS[i]] = S_CHARS[i];
        }

        function normalizeZh(str) {
            if (!str) return '';
            let s = String(str).toLowerCase();
            let res = '';
            for (let i = 0; i < s.length; i++) {
                const ch = s[i];
                res += T2S_MAP[ch] || ch;
            }
            return res;
        }

        function filterLocalManga(query) {
            if (!query) return localMangaList;
            const normQ = normalizeZh(query.trim());
            return localMangaList.filter(item => {
                const normTitle = normalizeZh(item.title || item.filename || '');
                const normAuthor = normalizeZh(item.author || '');
                const normTags = Array.isArray(item.tags) ? item.tags.map(t => normalizeZh(t)).join(' ') : normalizeZh(item.tags || '');
                return normTitle.includes(normQ) || normAuthor.includes(normQ) || normTags.includes(normQ);
            });
        }

        function onMangaSearchInput(val) {
            val = (val || '').trim();
            currentMangaSearchQuery = val;

            const localSection = document.getElementById('manga-local-section');
            const rankingSection = document.getElementById('manga-ranking-section');
            const onlineSec = document.getElementById('manga-online-section');

            if (!val) {
                clearMangaSearch();
                return;
            }

            // 搜索时确保展示本地书架并隐藏榜单与在线区
            if (rankingSection) rankingSection.style.display = 'none';
            if (localSection) localSection.style.display = 'block';
            if (onlineSec) onlineSec.style.display = 'none';

            // 激活“本地已收录”子标签高亮
            document.querySelectorAll('#manga-sub-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            const shelfTabBtn = document.getElementById('manga-subtab-shelf');
            if (shelfTabBtn) shelfTabBtn.classList.add('active');

            // 实时繁简模糊检索本地漫画书架，绝不触发联网搜索
            let matched = filterLocalManga(val);
            if (activeMangaTag === '__incomplete__') {
                matched = matched.filter(item => item.is_complete === false);
            } else if (activeMangaTag !== 'all') {
                const normTag = normalizeZh(activeMangaTag);
                matched = matched.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
            }
            const localHeading = document.getElementById('manga-local-heading');
            if (localHeading) localHeading.textContent = `🟢 本地已收录 (匹配到 ${matched.length} 部 · 点击封面直接阅读)`;
            renderMangaShelf(matched);
        }

        function onMangaSearchEnter() {
            const input = document.getElementById('manga-search-input');
            const val = (input ? input.value : '').trim();
            if (isRemoteClient) {          // 非本机：只搜本地，回车不触发联网检索
                onMangaSearchInput(val);
                return;
            }
            if (val) {
                executeUnifiedSearch(val);
            } else {
                clearMangaSearch();
            }
        }

        function onNovelSearchInput(val) {
            val = (val || '').trim();
            currentNovelSearchQuery = val;
            // 实时繁简模糊检索本地小说书架，绝不触发联网搜索
            renderNovelsShelf(filterLocalNovels(val));

            if (!val) {
                const onlineSec = document.getElementById('novel-online-section');
                if (onlineSec) onlineSec.style.display = 'none';
            }
        }

        function onNovelSearchEnter() {
            const input = document.getElementById('novel-search-input');
            const val = (input ? input.value : '').trim();
            if (isRemoteClient) {          // 非本机：只搜本地，回车不触发联网检索
                onNovelSearchInput(val);
                return;
            }
            if (val) {
                executeNovelSearch(val);
            } else {
                const onlineSec = document.getElementById('novel-online-section');
                if (onlineSec) onlineSec.style.display = 'none';
            }
        }

        function onDocSearchInput(val) {
            renderDocsShelf();
        }

        function onAudioSearchInput(val) {
            if (audioSearchDebounceTimer) clearTimeout(audioSearchDebounceTimer);
            audioSearchDebounceTimer = setTimeout(() => {
                loadAudioLibrary(true);
            }, 250);
        }

        function applyFilter() {
            const searchInput = document.getElementById('game-search-input');
            if (searchInput) {
                currentSearchQuery = (searchInput.value || '').trim().toLowerCase();
                currentGameSearchQuery = currentSearchQuery;
            }

            const favs = getFavorites();
            const standaloneFilterEl = document.getElementById('standalone-sub-filters');
            if (standaloneFilterEl) {
                standaloneFilterEl.style.display = (!currentSearchQuery && currentTab === 'standalone') ? 'flex' : 'none';
            }

            // 星际2 对战：首页独立大卡片进来的专区，不是游戏卡片网格，是专属操作台
            const sc2Panel = document.getElementById('sc2-panel');
            const gameGrid = document.getElementById('game-grid');
            const showSc2 = currentTab === 'sc2';
            if (sc2Panel) sc2Panel.style.display = showSc2 ? 'block' : 'none';
            if (gameGrid) gameGrid.style.display = showSc2 ? 'none' : '';
            if (showSc2) {
                document.getElementById('list-controls').style.display = 'none'; // 不需要分类/搜索栏
                const stats = document.getElementById('filter-stats');
                if (stats) stats.textContent = '';
                initSc2Panel();
                return;
            }

            const filtered = allGames.filter(g => {
                // NSFW 隐私过滤：未解锁时彻底剔除 RPG 与 SLG 敏感游戏
                if (!isNsfwUnlocked && (g.type === 'rpg' || g.type === 'slg' || g.category === 'rpg' || g.category === 'slg')) return false;

                // 局域网访问安全隔离：外部设备严禁搜索与显示 PC 独立大作与 Flash 游戏，防止 Deck 误唤醒或因外部无 Flash 插件报错
                if (isRemoteClient && (g.type === 'standalone' || g.type === 'flash')) return false;

                const name = g.name || g.id || '';
                const matchesQuery = !currentSearchQuery || g.id.toLowerCase().includes(currentSearchQuery) || name.toLowerCase().includes(currentSearchQuery);

                if (currentSearchQuery) {
                    return matchesQuery;
                }

                if (currentTab === 'fav') return favs.includes(g.id);
                if (currentTab === 'standalone') {
                    if (g.type !== 'standalone') return false;
                    if (currentStandaloneSubTab) return g.engine === currentStandaloneSubTab;
                    return true;
                }
                return g.type === currentTab;
            });
            renderGames(filtered);
        }

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

        const RETRO_FRANCHISES = [
            {
                key: 'kov',
                name: '三国战纪与街机清版名作 (Knights of Valour & Arcade Classics)',
                icon: '🐉',
                match: g => /valour|oriental legend|warriors of fate|三国|西游/i.test(g.id) || /kov|orlegend|wof/i.test(g.rom_file || '')
            },
            {
                key: 'kof',
                name: '拳皇全系列 (The King of Fighters)',
                icon: '🥊',
                match: g => /fighters|kof|热斗/i.test(g.id) || /kof/i.test(g.rom_file || '')
            },
            {
                key: 'mslug',
                name: '合金弹头全系列 (Metal Slug)',
                icon: '🪖',
                match: g => /metal slug|mslug/i.test(g.id) || /mslug/i.test(g.rom_file || '')
            },
            {
                key: 'pokemon',
                name: '宝可梦全世代与外传 (Pokemon)',
                icon: '🐾',
                match: g => /pokemon|宝可梦|口袋妖怪/i.test(g.id)
            },
            {
                key: 'zelda',
                name: '塞尔达传说系列 (The Legend of Zelda)',
                icon: '🗡️',
                match: g => /zelda|塞尔达/i.test(g.id)
            },
            {
                key: 'mario',
                name: '超级马里奥与瓦里奥系列 (Super Mario & Wario)',
                icon: '🍄',
                match: g => /mario|wario|yoshi|princess peach|马里奥|瓦里奥|耀西|碧姬/i.test(g.id)
            },
            {
                key: 'ff',
                name: '最终幻想系列 (Final Fantasy)',
                icon: '🔮',
                match: g => /final fantasy|最终幻想/i.test(g.id)
            },
            {
                key: 'contra',
                name: '魂斗罗全系列 (Contra)',
                icon: '🔫',
                match: g => /contra|operation c|魂斗罗/i.test(g.id)
            },
            {
                key: 'other_retro',
                name: '其他复古经典名作 (Other Retro Classics)',
                icon: '🕹️',
                match: g => g.type === 'retro'
            }
        ];

        function createGameCardElement(g, favs) {
            const item = document.createElement('a');
            item.className = 'game-card';
            
            let actionProto = 'action://play-rpg';
            let badgeText = 'RPG';
            let badgeClass = 'badge-rpg';

            if (g.type === 'standalone') {
                actionProto = 'action://play-standalone';
                const eng = (g.engine || 'PC').toLowerCase();
                if (eng === 'renpy') {
                    badgeText = "Ren'Py";
                    badgeClass = 'badge-renpy';
                } else if (eng === 'unity') {
                    badgeText = 'Unity';
                    badgeClass = 'badge-unity';
                } else if (eng === 'godot') {
                    badgeText = 'Godot';
                    badgeClass = 'badge-godot';
                } else if (eng === 'unreal') {
                    badgeText = 'Unreal';
                    badgeClass = 'badge-unreal';
                } else if (eng === 'app') {
                    badgeText = 'Windows 软件';
                    badgeClass = 'badge-app';
                } else {
                    badgeText = 'PC / Wine';
                    badgeClass = 'badge-wine';
                }
            } else if (g.type === 'retro') {
                actionProto = 'action://play-retro';
                badgeText = (g.system || 'Retro').toUpperCase();
                badgeClass = 'badge-retro';
            } else if (g.type === 'slg') {
                actionProto = 'action://play-slg';
                badgeText = 'SLG';
                badgeClass = 'badge-slg';
            } else if (g.type === 'flash') {
                actionProto = 'action://play-flash';
                badgeText = 'Flash';
                badgeClass = 'badge-flash';
            }

            const isDeckNative = navigator.userAgent.includes('QtWebEngine');
            if (isDeckNative) {
                item.href = actionProto + '?id=' + encodeURIComponent(g.id) + '&title=' + encodeURIComponent(g.name || g.id);
            } else {
                // 适配 iPad / 手机 / 外部浏览器：绝不触发 action:// 自定义协议 (彻底消除 iOS 误弹 App Store 下载 Apple Vision Pro 的异常)
                if (g.type === 'retro') {
                    item.href = '/player_retro.html?id=' + encodeURIComponent(g.id) + '&system=' + encodeURIComponent(g.system || 'arcade') + '&rom=' + encodeURIComponent(g.rom_file || '');
                } else if (g.type === 'flash') {
                    if (g.engine === 'web_flash' && g.url) {
                        item.href = g.url;
                        item.target = '_blank';
                    } else {
                        item.href = '/player_flash.html?id=' + encodeURIComponent(g.id) + '&file=' + encodeURIComponent(g.swf_file || '');
                    }
                } else if (g.type === 'rpg' || g.type === 'slg') {
                    item.href = '/game/' + encodeURIComponent(g.id) + '/index.html';
                } else {
                    // standalone / renpy 是 Windows/Linux 独立程序
                    item.href = 'javascript:void(0);';
                    if (isRemoteClient) {
                        item.onclick = (e) => {
                            e.preventDefault();
                            alert(`🔒 独立大作《${g.name || g.id}》属于大型 PC / Windows 游戏，仅限在 Steam Deck 实体机屏幕上运行。\n\n局域网外部设备已禁用，防止 Deck 误唤醒卡顿。`);
                        };
                    } else {
                        // 在 Steam Deck 本机浏览器中点击：直接调用后台 API 秒级拉起游戏，彻底告别 xdg-open 弹窗！
                        item.onclick = (e) => {
                            e.preventDefault();
                            launchStandaloneGame(g.id, g.name || g.id);
                        };
                    }
                }
            }

            const isFav = favs.includes(g.id);
            const starBtn = document.createElement('button');
            starBtn.className = 'fav-star-btn' + (isFav ? ' is-fav' : '');
            starBtn.title = isFav ? '取消收藏' : '加入喜欢';
            starBtn.innerHTML = isFav ? '★' : '☆';
            starBtn.onclick = (e) => toggleFavorite(e, g.id);

            const titleBox = document.createElement('div');
            titleBox.className = 'game-title-box';

            const titleSpan = document.createElement('span');
            titleSpan.className = 'game-title';
            titleSpan.textContent = g.id;

            titleBox.appendChild(starBtn);
            titleBox.appendChild(titleSpan);

            const badgeSpan = document.createElement('span');
            badgeSpan.className = 'engine-badge ' + badgeClass;
            badgeSpan.textContent = badgeText;

            item.appendChild(titleBox);
            item.appendChild(badgeSpan);
            item.addEventListener('click', () => {
                sessionStorage.setItem('hub_scroll_' + currentTab, String(window.scrollY));
            });
            return item;
        }

        function createSeriesCardElement(icon, title, count, gameCards) {
            const card = document.createElement('div');
            card.className = 'series-card';

            const header = document.createElement('div');
            header.className = 'series-header';

            const titleBox = document.createElement('div');
            titleBox.className = 'series-title-box';

            const iconSpan = document.createElement('span');
            iconSpan.className = 'series-icon';
            iconSpan.textContent = icon;

            const titleSpan = document.createElement('span');
            titleSpan.className = 'series-title';
            titleSpan.textContent = title;

            titleBox.appendChild(iconSpan);
            titleBox.appendChild(titleSpan);

            const countBadge = document.createElement('span');
            countBadge.className = 'series-count-badge';
            countBadge.textContent = count + ' 款游戏';

            header.appendChild(titleBox);
            header.appendChild(countBadge);

            const flow = document.createElement('div');
            flow.className = 'series-game-flow';
            gameCards.forEach(c => flow.appendChild(c));

            card.appendChild(header);
            card.appendChild(flow);
            return card;
        }

        function renderGames(games) {
            const grid = document.getElementById('game-grid');
            grid.innerHTML = '';
            
            const stats = document.getElementById('filter-stats');
            if (stats) stats.textContent = '共 ' + games.length + ' 款游戏';

            if (games.length === 0) {
                const emptyTip = currentTab === 'fav' 
                    ? '⭐ 暂无收藏游戏，点击任意游戏卡片左侧的 ★ 即可加入喜欢列表！'
                    : '未检索到相关游戏';
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.innerHTML = `
                    <div style="font-size:36px;margin-bottom:12px;">🔍</div>
                    <div style="font-size:16px;color:#c9d1d9;margin-bottom:6px;">${emptyTip}</div>
                    <div style="font-size:13px;">请尝试更换搜索关键词或切换上方专区标签</div>
                `;
                grid.appendChild(empty);
                return;
            }

            const favs = getFavorites();
            const isRetroView = (currentTab === 'retro' && !currentSearchQuery);

            if (isRetroView) {
                const seriesContainer = document.createElement('div');
                seriesContainer.className = 'series-container';

                const assignedSet = new Set();
                RETRO_FRANCHISES.forEach(f => {
                    const matching = games.filter(g => !assignedSet.has(g.id) && f.match(g));
                    if (matching.length > 0) {
                        matching.forEach(g => assignedSet.add(g.id));
                        const cards = matching.map(g => createGameCardElement(g, favs));
                        seriesContainer.appendChild(createSeriesCardElement(f.icon, f.name, matching.length, cards));
                    }
                });

                grid.appendChild(seriesContainer);
            } else {
                // 各专区平铺流 (RPG / 独立大作 / SLG / Flash / 喜欢)
                games.forEach(g => {
                    grid.appendChild(createGameCardElement(g, favs));
                });
            }

            const savedScroll = sessionStorage.getItem('hub_scroll_' + currentTab);
            if (savedScroll) {
                const sTop = parseInt(savedScroll, 10);
                document.documentElement.scrollTop = sTop;
                document.body.scrollTop = sTop;
                window.scrollTo(0, sTop);
            }
        }

        function populateGames(games, isManualRefresh = false) {
            allGames = games;
            const rpgCount = games.filter(g => g.type === 'rpg').length;
            const standaloneCount = games.filter(g => g.type === 'standalone').length;
            const retroCount = games.filter(g => g.type === 'retro').length;
            const slgCount = games.filter(g => g.type === 'slg').length;
            const flashCount = games.filter(g => g.type === 'flash').length;
            
            if (activePrimarySection === 'games') {
                if (isRemoteClient) {
                    const playable = games.filter(g => g.type !== 'standalone' && g.type !== 'flash').length;
                    document.getElementById('total-badge').textContent = playable + ' 款网页轻量游戏 (局域网)';
                } else {
                    document.getElementById('total-badge').textContent = games.length + ' 款游戏';
                }
            }
            document.getElementById('rpg-count-badge').textContent = rpgCount + ' Games';
            const standaloneBadge = document.getElementById('standalone-count-badge');
            if (standaloneBadge) standaloneBadge.textContent = isRemoteClient ? '🔒 本机独占' : standaloneCount + ' Games';
            document.getElementById('retro-count-badge').textContent = retroCount + ' Games';
            document.getElementById('slg-count-badge').textContent = slgCount + ' Games';
            const flashBadge = document.getElementById('flash-count-badge');
            if (flashBadge) flashBadge.textContent = isRemoteClient ? '🔒 本机独占' : flashCount + ' Games';
            const sc2Badge = document.getElementById('sc2-count-badge');
            if (sc2Badge) sc2Badge.textContent = isRemoteClient ? '🔒 本机独占' : '离线对战';
            
            updateFavBadges();
            applyRemoteClientRestrictions();
            
            if (!isManualRefresh && activePrimarySection === 'games') {
                const urlParams = new URLSearchParams(window.location.search);
                const initCat = urlParams.get('category');
                if (initCat && initCat !== 'portal') {
                    document.getElementById('portal-view').style.display = 'none';
                    document.getElementById('list-view').style.display = 'block';
                    document.getElementById('list-controls').style.display = 'flex';
                    document.getElementById('nav-back-btn').style.display = 'flex';
                    currentTab = initCat;
                    cleanupCatInitStyle();
                    document.querySelectorAll('.tab-btn').forEach(btn => {
                        btn.classList.toggle('active', btn.dataset.tab === initCat);
                    });
                } else {
                    document.querySelectorAll('.tab-btn').forEach(btn => {
                        btn.classList.toggle('active', btn.dataset.tab === currentTab);
                    });
                }
            }
            applyFilter();
        }

        // 优先从持久缓存中同步完成秒级渲染，避免网络请求延迟导致的视觉闪烁与空屏
        try {
            const cached = localStorage.getItem('omni_games_cache') || sessionStorage.getItem('omni_games_cache');
            if (cached) {
                populateGames(JSON.parse(cached));
            }
        } catch(e) {}

        function loadGames() {
            fetch('/api/games?t=' + Date.now(), { cache: 'no-store' })
                .then(res => res.json())
                .then(games => {
                    try {
                        localStorage.setItem('omni_games_cache', JSON.stringify(games));
                        sessionStorage.setItem('omni_games_cache', JSON.stringify(games));
                    } catch(e) {}
                    populateGames(games);
                })
                .catch(err => {
                    if (err.name === 'AbortError' || document.hidden) return;
                    console.warn('Notice: loadGames fetch interrupted or network offline:', err.message || err);
                });
        }

        // =========================================================================
        // 漫画区 (Manga Hub) 控制器与交互方法
        // =========================================================================

        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }
        function escapeAttr(str) {
            if (!str) return '';
            return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
        }

        let activeMediaTab = 'docs';
        let localNovelsList = [];
        let currentNovelFilter = 'all';

        function togglePrimarySection() {
            if (activePrimarySection === 'games') {
                switchToMediaSection();
            } else {
                switchToGamesSection();
            }
        }

        function switchToMediaSection() {
            activePrimarySection = 'media';
            try { localStorage.setItem('omni_primary_section', 'media'); } catch(e) {}
            document.body.classList.add('section-media');
            document.getElementById('header-brand-title').textContent = '📖 Omni Deck Media';
            document.getElementById('primary-section-btn').innerHTML = '🎮 游戏专区';
            document.getElementById('nav-back-btn').style.display = 'none';

            // Remove all inline injected category styles that might force display:flex on list-controls!
            document.querySelectorAll('.cat-init-style, #cat-init-style').forEach(el => el.remove());
            if (window.history && window.history.replaceState) {
                window.history.replaceState(null, '', window.location.pathname);
            }

            document.getElementById('games-section').style.display = 'none';
            document.getElementById('list-controls').style.display = 'none';
            document.getElementById('media-section').style.display = 'block';

            updateMediaTabUI();
            loadPersistentMangaQueue();
            pollMangaTasks();
        }

        let localDocsList = [];
        let currentDocFilter = 'all';

        function switchMediaTab(tab, btnEl) {
            if (!isNsfwUnlocked && tab === 'manga') {
                openNsfwModal();
                return;
            }
            if (isRemoteClient && tab === 'mega') {
                if (typeof showMegaToast === 'function') {
                    showMegaToast('🔒 MEGA 个人网盘仅限 Steam Deck 本机访问，局域网禁止访问', true);
                }
                return;
            }
            activeMediaTab = tab;
            document.querySelectorAll('.media-nav-bar .tab-btn').forEach(b => b.classList.remove('active'));
            if (btnEl) btnEl.classList.add('active');
            updateMediaTabUI();
            if (typeof checkScrollTopVisibility === 'function') setTimeout(checkScrollTopVisibility, 50);
        }

        function updateMediaTabUI() {
            const mangaView = document.getElementById('media-manga-view');
            const novelsView = document.getElementById('media-novels-view');
            const docsView = document.getElementById('media-docs-view');
            const audioView = document.getElementById('media-audio-view');
            const megaView = document.getElementById('media-mega-view');
            const subStats = document.getElementById('media-sub-stats');

            if (mangaView) mangaView.style.display = activeMediaTab === 'manga' ? 'block' : 'none';
            if (novelsView) novelsView.style.display = activeMediaTab === 'novels' ? 'block' : 'none';
            if (docsView) docsView.style.display = activeMediaTab === 'docs' ? 'block' : 'none';
            if (audioView) audioView.style.display = activeMediaTab === 'audio' ? 'block' : 'none';
            if (megaView) megaView.style.display = activeMediaTab === 'mega' ? 'block' : 'none';

            if (activeMediaTab === 'manga') {
                const count = localMangaList && localMangaList.length > 0 ? localMangaList.length : null;
                if (count !== null) {
                    document.getElementById('total-badge').textContent = count + ' 部漫画';
                    if (subStats) subStats.textContent = '共 ' + count + ' 部漫画';
                    renderMangaTagBar();
                    updateMangaIncompleteBanner();
                    const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
                    if (activeMangaSubTab === 'shelf') {
                        let baseList = localMangaList;
                        if (searchVal) {
                            baseList = filterLocalManga(searchVal);
                        }
                        if (activeMangaTag === 'all') {
                            renderMangaShelf(baseList);
                        } else {
                            const normTag = normalizeZh(activeMangaTag);
                            const filtered = baseList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
                            renderMangaShelf(filtered);
                        }
                    } else if (rankingDataCache[activeMangaSubTab]) {
                        renderMangaRankingGrid(rankingDataCache[activeMangaSubTab]);
                    }
                } else {
                    document.getElementById('total-badge').textContent = '漫画画廊';
                    if (subStats) subStats.textContent = '正在读取本地漫画库...';
                    loadMangaLibrary();
                }
            } else if (activeMediaTab === 'novels') {
                const count = localNovelsList && localNovelsList.length > 0 ? localNovelsList.length : null;
                if (count !== null) {
                    document.getElementById('total-badge').textContent = count + ' 本小说';
                    if (subStats) subStats.textContent = '共 ' + count + ' 本已收录小说';
                    renderNovelCategoryBar();
                    const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
                    renderNovelsShelf(filterLocalNovels(searchVal));
                } else {
                    document.getElementById('total-badge').textContent = '小说画廊';
                    if (subStats) subStats.textContent = '正在读取本地小说书库...';
                    loadNovelsLibrary();
                }
            } else if (activeMediaTab === 'docs') {
                document.getElementById('total-badge').textContent = '技术文档';
                if (subStats) subStats.textContent = '正在读取技术文档库...';
                loadDocsLibrary();
            } else if (activeMediaTab === 'audio') {
                const count = totalAudioCount || (localAudioList ? localAudioList.length : 0);
                const label = isAudioNsfw ? '部绅士音声' : '部有声书';
                if (count > 0) {
                    document.getElementById('total-badge').textContent = `${count} ${label}`;
                    if (subStats) subStats.textContent = `共 ${count} ${label} (支持后台全局播放)`;
                    if (localAudioList && localAudioList.length > 0) {
                        renderAudioTrackList(true);
                    }
                } else {
                    document.getElementById('total-badge').textContent = isAudioNsfw ? '🔞 音声画廊' : '📻 有声书与广播剧';
                    if (subStats) subStats.textContent = '正在读取有声书曲库...';
                }
                loadAudioLibrary(true);
            } else if (activeMediaTab === 'mega') {
                document.getElementById('total-badge').textContent = 'MEGA';
                if (subStats) {
                    subStats.textContent = '';
                }
                loadMegaStatus();
                refreshMegaTransfers();
            }
        }

        function prewarmMediaLibraries() {
            // 静默预加载漫画、小说和音声库元数据，避免首次切入媒体画廊时出现 0 部/0 首闪烁
            if (!localMangaList || localMangaList.length === 0) {
                fetch('/api/manga/library?dir=manga&t=' + Date.now())
                    .then(r => r.json())
                    .then(list => {
                        localMangaList = list || [];
                        const mangaCountBadge = document.getElementById('manga-local-count');
                        if (mangaCountBadge) mangaCountBadge.textContent = `(${localMangaList.length} 部)`;
                        if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                            document.getElementById('total-badge').textContent = localMangaList.length + ' 部漫画';
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = '共 ' + localMangaList.length + ' 部漫画';
                            renderMangaTagBar();
                            updateMangaIncompleteBanner();
                            if (activeMangaSubTab === 'shelf') {
                                const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
                                const baseList = searchVal ? filterLocalManga(searchVal) : localMangaList;
                                renderMangaShelf(baseList);
                            }
                        }
                    })
                    .catch(() => {});
            }
            if (!localNovelsList || localNovelsList.length === 0) {
                fetch(`/api/novels/library?nsfw=${isNovelNsfw ? 1 : 0}&t=${Date.now()}`)
                    .then(r => r.json())
                    .then(list => {
                        localNovelsList = list || [];
                        const countEl = document.getElementById('novel-local-count');
                        if (countEl) countEl.textContent = `(${localNovelsList.length} 部 · EPUB / TXT)`;
                        if (activePrimarySection === 'media' && activeMediaTab === 'novels') {
                            document.getElementById('total-badge').textContent = localNovelsList.length + ' 本小说';
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = '共 ' + localNovelsList.length + ' 本已收录小说';
                            renderNovelCategoryBar();
                            const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
                            renderNovelsShelf(filterLocalNovels(searchVal));
                        }
                    })
                    .catch(() => {});
            }
            if (!localAudioList || localAudioList.length === 0) {
                const prefetchUrl = isAudioNsfw 
                    ? `/api/audio/library?nsfw=1&q=&page=1&page_size=80&t=${Date.now()}`
                    : `/audio/standard_catalog.json?t=${Date.now()}`;
                fetch(prefetchUrl)
                    .then(r => r.json())
                    .then(res => {
                        let items = res.items || [];
                        if (!isAudioNsfw) {
                            items = items.filter(it => !it.is_nsfw && !it.path?.includes('/run/media/') && !it.path?.includes('telegramFile'));
                        }
                        items.sort((a, b) => {
                            const albA = a.album || '';
                            const albB = b.album || '';
                            const albCmp = albA.localeCompare(albB, undefined, { numeric: true, sensitivity: 'base' });
                            if (albCmp !== 0) return albCmp;
                            return (a.filename || a.title || '').localeCompare(b.filename || b.title || '', undefined, { numeric: true, sensitivity: 'base' });
                        });
                        localAudioList = items;
                        totalAudioCount = isAudioNsfw ? (res.total || items.length) : items.length;
                        const badge = document.getElementById('audio-total-count-badge');
                        if (badge) badge.textContent = `共 ${totalAudioCount} 首`;
                        if (activePrimarySection === 'media' && activeMediaTab === 'audio') {
                            const label = isAudioNsfw ? '部绅士音声' : '部有声书';
                            document.getElementById('total-badge').textContent = `${totalAudioCount} ${label}`;
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = `共 ${totalAudioCount} ${label} (支持后台全局播放)`;
                            if (res.albums) renderAudioAlbumFilterBar(res.albums);
                            renderAudioTrackList(true);
                        }
                    })
                    .catch(() => {});
            }
        }

        function switchToGamesSection() {
            activePrimarySection = 'games';
            try { localStorage.setItem('omni_primary_section', 'games'); } catch(e) {}
            document.body.classList.remove('section-media');
            var secStyle = document.getElementById('sec-init-style');
            if (secStyle) secStyle.remove();

            document.getElementById('header-brand-title').textContent = '🎮 Omni Deck Games';
            document.getElementById('primary-section-btn').innerHTML = '📖 媒体专区';
            const searchInput = document.getElementById('game-search-input');
            if (searchInput) {
                searchInput.value = currentGameSearchQuery || '';
            }
            currentSearchQuery = currentGameSearchQuery || '';

            document.getElementById('media-section').style.display = 'none';
            document.getElementById('games-section').style.display = 'block';
            document.getElementById('total-badge').textContent = allGames.length + ' 款游戏';

            if (currentTab && document.getElementById('list-view').style.display === 'block') {
                document.getElementById('list-controls').style.display = 'flex';
                document.getElementById('nav-back-btn').style.display = 'flex';
                applyFilter();
            } else {
                if (currentSearchQuery) {
                    openCategory(currentTab || 'rpg');
                } else {
                    showPortalView();
                }
            }
        }

        let activeMangaTag = 'all';

        function renderMangaTagBar() {
            const bar = document.getElementById('manga-tag-filter-bar');
            if (!bar) return;

            if (!localMangaList || localMangaList.length === 0) {
                bar.style.display = 'none';
                return;
            }

            // 统计本地所有已收录漫画的标签分布
            const tagCounts = {};
            localMangaList.forEach(item => {
                const tags = Array.isArray(item.tags) ? item.tags : [];
                tags.forEach(t => {
                    const cleanT = String(t).trim();
                    if (cleanT) {
                        tagCounts[cleanT] = (tagCounts[cleanT] || 0) + 1;
                    }
                });
            });

            const sortedTags = Object.entries(tagCounts)
                .sort((a, b) => b[1] - a[1]);

            if (sortedTags.length === 0) {
                bar.style.display = 'none';
                return;
            }

            let html = `<button class="manga-tag-filter-btn ${activeMangaTag === 'all' ? 'active' : ''}" onclick="setMangaTagFilter('all')">🏷️ 全部 (${localMangaList.length})</button>`;

            const incompleteCount = localMangaList.filter(item => item.is_complete === false).length;
            if (incompleteCount > 0) {
                const isIncActive = (activeMangaTag === '__incomplete__');
                html += `<button class="manga-tag-filter-btn ${isIncActive ? 'active' : ''}" style="color:${isIncActive ? '#fff' : '#d29922'};border-color:#d2992288;background:${isIncActive ? '#d29922' : '#161b22'};font-weight:600;" onclick="setMangaTagFilter('__incomplete__')">⚠️ 连载更新/未完 (${incompleteCount})</button>`;
            }

            // 展示出现频次最高的分类标签 (频次 >= 2，最多 40 个分类)
            const visibleTags = sortedTags.filter(([t, count]) => count >= 2).slice(0, 40);
            const tagsToRender = visibleTags.length >= 8 ? visibleTags : sortedTags.slice(0, 25);

            tagsToRender.forEach(([t, count]) => {
                const isActive = (activeMangaTag === t);
                html += `<button class="manga-tag-filter-btn ${isActive ? 'active' : ''}" onclick="setMangaTagFilter('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)} (${count})</button>`;
            });

            bar.innerHTML = html;
            bar.style.display = 'flex';
        }

        function setMangaTagFilter(tag) {
            activeMangaTag = tag;
            renderMangaTagBar();
            updateMangaIncompleteBanner();

            const searchInput = document.getElementById('manga-search-input');
            const searchVal = (searchInput ? searchInput.value : '').trim();
            let baseList = localMangaList;
            if (searchVal) {
                baseList = filterLocalManga(searchVal);
            }

            if (activeMangaTag === 'all') {
                renderMangaShelf(baseList);
            } else if (activeMangaTag === '__incomplete__') {
                const filtered = baseList.filter(item => item.is_complete === false);
                renderMangaShelf(filtered);
            } else {
                const normTag = normalizeZh(activeMangaTag);
                const filtered = baseList.filter(item => {
                    if (!Array.isArray(item.tags)) return false;
                    return item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag);
                });
                renderMangaShelf(filtered);
            }
        }

        function updateMangaIncompleteBanner() {
            const banner = document.getElementById('manga-incomplete-banner');
            if (!banner) return;
            const incompleteList = localMangaList.filter(item => item.is_complete === false);
            const count = incompleteList.length;

            if (activeMangaTag !== '__incomplete__' || count === 0) {
                banner.style.display = 'none';
                banner.innerHTML = '';
                return;
            }

            banner.innerHTML = `
                <div style="background: linear-gradient(135deg, rgba(210,153,34,0.18), rgba(210,153,34,0.06)); border: 1px solid rgba(210,153,34,0.45); border-radius: 10px; padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-size: 24px;">⚠️</span>
                        <div>
                            <div style="font-size: 14px; font-weight: 700; color: #f0f6fc;">
                                智能检测到 <span style="color: #d29922; font-weight: 800; font-size: 16px;">${count}</span> 部连载漫画有线上新章节更新
                            </div>
                            <div style="font-size: 12px; color: #8b949e; margin-top: 3px;">
                                增量追更机制：仅下载抓取新增章节并就地注入现有 CBZ，旧章节无需重新下载！
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                        <button class="manga-btn manga-btn-primary" style="background: #d29922; border-color: #bb8009; color: #fff; font-weight: 600; padding: 6px 14px; font-size: 12px;" onclick="startSupplementAllManga(true)">
                            ⚡ 一键并发补充下载 (${count} 部)
                        </button>
                        <button class="manga-btn" style="border-color: #d2992288; color: #d29922; padding: 6px 14px; font-size: 12px;" onclick="startSupplementAllManga(false)">
                            📥 逐本顺序补充下载
                        </button>
                        <button class="manga-btn" style="font-size: 12px; padding: 6px 12px;" onclick="addAllIncompleteToQueue()">
                            ➕ 全部加入待下载列表
                        </button>
                    </div>
                </div>
            `;
            banner.style.display = 'block';
        }

        function startSupplementSingleManga(albumId, filename, dir = 'manga', title = '') {
            if (!albumId && filename) {
                const item = localMangaList.find(m => m.filename === filename);
                if (item && item.id) albumId = item.id;
            }
            if (!albumId) {
                alert('未能识别该漫画的线上编号，请尝试在线搜索重下。');
                return;
            }

            fetch('/api/manga/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    album_id: albumId,
                    chapter_ids: null,
                    pack_cbz: true,
                    clean_temp: true,
                    dir: dir || 'manga'
                })
            })
            .then(r => r.json())
            .then(res => {
                pollMangaTasks();
                const container = document.getElementById('manga-tasks-container');
                if (container) {
                    container.style.display = 'block';
                    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            })
            .catch(err => {
                alert('启动增量补充下载失败: ' + err);
            });
        }

        function startSupplementAllManga(concurrent = true) {
            const incompleteItems = localMangaList.filter(item => item.is_complete === false && item.id);
            if (incompleteItems.length === 0) {
                alert('本地目前没有检测到需要补充更新的连载漫画！');
                return;
            }
            const ids = incompleteItems.map(item => item.id);

            fetch('/api/manga/batch_download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    album_ids: ids,
                    dir: 'manga',
                    pack_cbz: true,
                    clean_temp: true,
                    concurrency: concurrent ? 3 : 1
                })
            })
            .then(r => r.json())
            .then(res => {
                pollMangaTasks();
                const container = document.getElementById('manga-tasks-container');
                if (container) {
                    container.style.display = 'block';
                    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            })
            .catch(err => {
                alert('启动批量补充下载失败: ' + err);
            });
        }

        function addAllIncompleteToQueue() {
            const incompleteItems = localMangaList.filter(item => item.is_complete === false && item.id);
            if (incompleteItems.length === 0) {
                alert('本地目前没有检测到需要补充更新的连载漫画！');
                return;
            }
            let addedCount = 0;
            incompleteItems.forEach(item => {
                if (!isMangaInQueue(item.id)) {
                    mangaDownloadQueue.push({
                        id: String(item.id),
                        title: item.title,
                        cover_url: item.cover_url || `/api/manga/cover?name=${encodeURIComponent(item.filename)}&dir=${item.dir || 'manga'}`
                    });
                    addedCount++;
                }
            });
            if (addedCount > 0) {
                saveMangaQueueToStorage();
                syncMangaQueueToBackend();
                updateMangaQueueBadge();
                renderMangaQueueList();
                alert(`已成功将 ${addedCount} 部待更新的连载漫画加入待下载列表！`);
            } else {
                alert('所有待更新的连载漫画已在待下载列表中。');
            }
        }

        function loadMangaLibrary() {
            fetch('/api/manga/library?dir=manga&t=' + Date.now())
                .then(r => r.json())
                .then(list => {
                    localMangaList = list || [];
                    const mangaCountBadge = document.getElementById('manga-local-count');
                    if (mangaCountBadge) mangaCountBadge.textContent = `(${localMangaList.length} 部)`;
                    if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                        document.getElementById('total-badge').textContent = localMangaList.length + ' 部漫画';
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = '共 ' + localMangaList.length + ' 部漫画';
                    }

                    renderMangaTagBar();
                    updateMangaIncompleteBanner();

                    const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
                    if (activeMangaSubTab === 'shelf') {
                        let baseList = localMangaList;
                        if (searchVal) {
                            baseList = filterLocalManga(searchVal);
                        }
                        if (activeMangaTag === 'all') {
                            renderMangaShelf(baseList);
                        } else {
                            const normTag = normalizeZh(activeMangaTag);
                            const filtered = baseList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
                            renderMangaShelf(filtered);
                        }
                    } else if (rankingDataCache[activeMangaSubTab]) {
                        renderMangaRankingGrid(rankingDataCache[activeMangaSubTab]);
                    }
                })
                .catch(err => {
                    console.error('Failed to load manga library:', err);
                });
        }

        let currentMangaShelfList = [];
        let mangaShelfRenderIndex = 0;
        const MANGA_SHELF_PAGE_SIZE = 36;

        function renderMangaShelf(items, reset = true) {
            const grid = document.getElementById('manga-shelf-grid');
            const emptyEl = document.getElementById('manga-shelf-empty');
            if (!grid) return;

            if (reset) {
                grid.innerHTML = '';
                currentMangaShelfList = (items !== undefined && items !== null ? items : localMangaList) || [];
                mangaShelfRenderIndex = 0;
            }

            if (!currentMangaShelfList || currentMangaShelfList.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';

            const nextChunk = currentMangaShelfList.slice(mangaShelfRenderIndex, mangaShelfRenderIndex + MANGA_SHELF_PAGE_SIZE);
            nextChunk.forEach(item => {
                const card = document.createElement('div');
                card.className = 'manga-card';
                card.onclick = () => openMangaReader(item.filename, 'manga');

                const tagsList = Array.isArray(item.tags) ? item.tags : [];
                const tagsHtml = tagsList.length > 0
                    ? `<div class="manga-tags-row" onclick="event.stopPropagation()">
                        ${tagsList.slice(0, 3).map(t => `<span class="manga-tag-pill" title="按标签筛选: ${escapeAttr(t)}" onclick="filterMangaByTag('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)}</span>`).join('')}
                      </div>`
                    : '';

                const isInc = (item.is_complete === false);
                const missingCount = isInc ? Math.max(1, (item.online_chapters || 0) - (item.local_chapters || 0)) : 0;
                const completeBadge = isInc
                    ? `<span class="manga-badge-cbz" style="background:#d29922dd;color:#fff;" title="部分话数收录 (本地 ${item.local_chapters || '?'}/${item.online_chapters || '?'} 话)">⚠️ ${item.local_chapters || '?'}/${item.online_chapters || '?'}话</span>`
                    : `<span class="manga-badge-cbz">单文件 CBZ</span>`;

                const hoverSupplementBtn = isInc
                    ? `<button class="manga-mini-btn" style="background:#d29922;color:#fff;border-color:#bb8009;" title="增量补充下载最新章节 (差 ${missingCount} 话)" onclick="startSupplementSingleManga('${escapeAttr(item.id || '')}', '${escapeAttr(item.filename)}', '${escapeAttr(item.dir || 'manga')}', '${escapeAttr(item.title)}')">📥</button>`
                    : '';

                const cardSupplementRow = isInc
                    ? `<div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;padding-top:4px;border-top:1px dashed #30363d;" onclick="event.stopPropagation()">
                         <span style="font-size:11px;color:#d29922;font-weight:600;">⚠️ 缺 ${missingCount} 话更新</span>
                         <button class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;background:#d29922;border-color:#bb8009;font-weight:600;border-radius:4px;" onclick="startSupplementSingleManga('${escapeAttr(item.id || '')}', '${escapeAttr(item.filename)}', '${escapeAttr(item.dir || 'manga')}', '${escapeAttr(item.title)}')">📥 补全下载</button>
                       </div>`
                    : '';

                card.innerHTML = `
                    <div class="manga-cover-wrap">
                        ${item.has_cover ? `<img src="${item.cover_url}" class="manga-cover" loading="lazy">` : `<div class="manga-cover-fallback">📖</div>`}
                        ${completeBadge}
                        <div class="manga-actions-hover" onclick="event.stopPropagation()">
                            ${hoverSupplementBtn}
                            <button class="manga-mini-btn" title="调用系统外部阅读器 (Okular)" onclick="openExternalManga('${escapeAttr(item.filename)}', 'manga')">🖥️</button>
                            <button class="manga-mini-btn" title="移至回收站" onclick="deleteMangaFile('${escapeAttr(item.filename)}', 'manga')">🗑️</button>
                        </div>
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        ${tagsHtml}
                        <div class="manga-meta">
                            <span>${item.page_count ? item.page_count + ' 页' : '整本'}</span>
                            <span>${item.size_mb} MB</span>
                        </div>
                        ${cardSupplementRow}
                    </div>
                `;
                grid.appendChild(card);
            });
            mangaShelfRenderIndex += nextChunk.length;
        }

        function filterMangaByTag(tag) {
            if (activeMangaSubTab !== 'shelf') {
                const shelfTabBtn = document.getElementById('manga-subtab-shelf');
                switchMangaSubTab('shelf', shelfTabBtn);
            }
            setMangaTagFilter(tag);
        }

        function loadMoreMangaShelf() {
            if (mangaShelfRenderIndex < currentMangaShelfList.length) {
                renderMangaShelf(null, false);
            }
        }

        // ================= 漫画画廊子标签与必看榜单系统 (每周必看 / 每月必看 TOP 80) =================
        let activeMangaSubTab = 'shelf'; // 'shelf' | 'week' | 'month'
        let rankingDataCache = {
            week: null,
            month: null
        };

        function switchMangaSubTab(subTab, btnEl) {
            if (isRemoteClient && subTab !== 'shelf') {   // 非本机：榜单是联网内容，禁用（按钮也已 CSS 隐藏）
                return;
            }
            activeMangaSubTab = subTab;
            document.querySelectorAll('#manga-sub-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            if (btnEl) btnEl.classList.add('active');

            const localSec = document.getElementById('manga-local-section');
            const rankingSec = document.getElementById('manga-ranking-section');
            const rankHeading = document.getElementById('manga-ranking-heading');
            const rankLoading = document.getElementById('manga-ranking-loading');
            const rankGrid = document.getElementById('manga-ranking-grid');
            const subStats = document.getElementById('media-sub-stats');

            if (subTab === 'shelf') {
                if (localSec) localSec.style.display = 'block';
                if (rankingSec) rankingSec.style.display = 'none';
                const count = localMangaList ? localMangaList.length : 0;
                if (subStats) subStats.textContent = '共 ' + count + ' 部漫画';
                renderMangaTagBar();
                setMangaTagFilter(activeMangaTag);
            } else {
                if (localSec) localSec.style.display = 'none';
                if (rankingSec) rankingSec.style.display = 'block';

                const rankTitles = {
                    week: '🔥 每周必看榜单 (禁漫官方本周热度 TOP 80 · 点击封面沉浸阅读或一键下载)',
                    month: '🏆 每月必看榜单 (禁漫官方本月热度 TOP 80 · 点击封面沉浸阅读或一键下载)'
                };
                if (rankHeading) rankHeading.textContent = rankTitles[subTab] || '🔥 热门榜单';
                if (subStats) subStats.textContent = (subTab === 'week' ? '每周必看 TOP 80' : '每月必看 TOP 80') + ' · 官方热度实时排行';

                if (rankingDataCache[subTab] && rankingDataCache[subTab].length > 0) {
                    if (rankLoading) rankLoading.style.display = 'none';
                    renderMangaRankingGrid(rankingDataCache[subTab]);
                } else {
                    if (rankLoading) rankLoading.style.display = 'block';
                    if (rankGrid) rankGrid.innerHTML = '';
                    fetch(`/api/manga/rankings?type=${subTab}&page=1&count=80&t=` + Date.now())
                        .then(r => r.json())
                        .then(data => {
                            if (rankLoading) rankLoading.style.display = 'none';
                            const items = data.results || [];
                            rankingDataCache[subTab] = items;
                            renderMangaRankingGrid(items);
                        })
                        .catch(err => {
                            if (rankLoading) rankLoading.style.display = 'none';
                            if (rankGrid) rankGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f85149;padding:40px;">获取榜单遇到异常: ${err}</div>`;
                        });
                }
            }
        }

        function renderMangaRankingGrid(items) {
            const grid = document.getElementById('manga-ranking-grid');
            if (!grid) return;
            grid.innerHTML = '';

            if (!items || items.length === 0) {
                grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#8b949e;padding:40px;">暂无榜单数据</div>';
                return;
            }

            items.forEach((item, idx) => {
                const rankNum = idx + 1;
                const card = document.createElement('div');
                card.className = 'manga-card';
                const inQueue = isMangaInQueue(item.id);
                const localMatch = findLocalMangaMatch(item);

                let badgeHtml = `
                    <span class="manga-badge-online">JM${item.id}</span>
                `;
                let actionHtml = '';

                if (localMatch) {
                    badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#238636;">✓ 已在书架</span>`;
                    actionHtml = `
                        <div style="display:flex;gap:6px;margin-top:8px;">
                            <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;justify-content:center;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">
                                📖 立即阅读
                            </button>
                            <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;" title="重新下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">🔄 重下</button>
                        </div>
                    `;
                } else {
                    actionHtml = `
                        <div style="display:flex;gap:6px;margin-top:8px;">
                            <button id="manga-queue-btn-${item.id}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="flex:1;font-size:11.5px;padding:5px 8px;justify-content:center;" onclick="toggleMangaQueueItem('${item.id}', '${escapeAttr(item.title)}', '${escapeAttr(item.cover_url)}', this)">
                                ${inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表'}
                            </button>
                            <button class="manga-btn manga-btn-primary" style="font-size:11.5px;padding:5px 8px;" title="立即下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">📥 一键下载</button>
                        </div>
                    `;
                }

                card.innerHTML = `
                    <div class="manga-cover-wrap">
                        <img src="${item.cover_url}" class="manga-cover" loading="lazy" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'130\\' fill=\\'%2321262d\\'><rect width=\\'100\\' height=\\'130\\'/></svg>'">
                        ${badgeHtml}
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        ${actionHtml}
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        // ================= 1. 漫画专属待下载列表系统 =================
        let currentOnlineResults = [];
        let currentMangaSearchQuery = '';
        let currentMangaPage = 1;
        let currentMangaSort = 'mv';
        let hasMoreMangaPages = false;
        let isLoadingMoreManga = false;
        let totalOnlineMangaCount = 0;
        let mangaDownloadQueue = [];

        function onMangaSortChange(val) {
            currentMangaSort = val || 'mv';
            const input = document.getElementById('manga-search-input');
            const valInput = (input ? input.value : '').trim();
            if (valInput) {
                executeUnifiedSearch(valInput);
            }
        }
        try {
            const savedMangaQueue = localStorage.getItem('omni_manga_queue');
            if (savedMangaQueue) mangaDownloadQueue = JSON.parse(savedMangaQueue);
        } catch(e) {}

        function saveMangaDownloadQueue() {
            try {
                localStorage.setItem('omni_manga_queue', JSON.stringify(mangaDownloadQueue));
            } catch(e) {}
            updateMangaQueueBadge();

            fetch('/api/manga/queue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: mangaDownloadQueue, dir: 'manga' })
            }).catch(() => {});
        }

        function loadPersistentMangaQueue() {
            fetch('/api/manga/queue?dir=manga&t=' + Date.now())
                .then(r => r.json())
                .then(items => {
                    if (Array.isArray(items)) {
                        mangaDownloadQueue = items;
                        try { localStorage.setItem('omni_manga_queue', JSON.stringify(mangaDownloadQueue)); } catch(e) {}
                        updateMangaQueueBadge();
                        const modal = document.getElementById('manga-download-queue-modal');
                        if (modal && modal.style.display === 'flex') {
                            renderMangaQueueModalItems();
                        }
                    }
                })
                .catch(() => {});
        }

        function updateMangaQueueBadge() {
            const count = mangaDownloadQueue.length;
            const mBadge = document.getElementById('manga-queue-badge-count');
            const modalBadge = document.getElementById('manga-queue-modal-badge');
            const btnCount = document.getElementById('manga-queue-btn-count');

            if (mBadge) mBadge.textContent = count;
            if (modalBadge) modalBadge.textContent = `(共 ${count} 部)`;
            if (btnCount) btnCount.textContent = count;
        }

        function isMangaInQueue(id) {
            return mangaDownloadQueue.some(item => String(item.id) === String(id));
        }

        function toggleMangaQueueItem(id, title, cover_url, btnEl) {
            id = String(id);
            const idx = mangaDownloadQueue.findIndex(item => String(item.id) === id);
            let inQueue = false;
            if (idx >= 0) {
                mangaDownloadQueue.splice(idx, 1);
                inQueue = false;
            } else {
                mangaDownloadQueue.push({ id, title, cover_url });
                inQueue = true;
            }
            saveMangaDownloadQueue();

            const targetBtn = btnEl || document.getElementById(`manga-queue-btn-${id}`);
            if (targetBtn) {
                targetBtn.className = `manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}`;
                targetBtn.textContent = inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表';
            }

            renderMangaQueueModalItems();
        }

        function removeMangaQueueItem(id) {
            id = String(id);
            mangaDownloadQueue = mangaDownloadQueue.filter(item => String(item.id) !== id);
            saveMangaDownloadQueue();
            renderMangaQueueModalItems();

            const cardBtn = document.getElementById(`manga-queue-btn-${id}`);
            if (cardBtn) {
                cardBtn.className = 'manga-btn';
                cardBtn.textContent = '➕ 加入待下载列表';
            }
        }
        function recoverUncompletedMangaDownloads() {
            const btn = document.getElementById('manga-queue-recover-btn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '🔄 扫描中...';
            }
            fetch('/api/manga/recover_temp?dir=manga&t=' + Date.now())
                .then(r => r.json())
                .then(res => {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = '🔄 找回未完成下载';
                    }
                    const count = res.recovered_count || 0;
                    if (count > 0) {
                        alert(`已成功找回 ${count} 部存在下载碎片的漫画并重新加入待下载列表！`);
                        loadPersistentMangaQueue();
                    } else {
                        alert('扫描完成！当前 temp 目录下所有未完成漫画均已在待下载列表中，无遗漏作品。');
                    }
                })
                .catch(err => {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = '🔄 找回未完成下载';
                    }
                    alert('扫描未完成漫画失败: ' + err);
                });
        }

        function clearMangaDownloadQueue() {
            if (mangaDownloadQueue.length === 0) return;
            mangaDownloadQueue = [];
            saveMangaDownloadQueue();
            renderMangaQueueModalItems();

            document.querySelectorAll('#manga-online-grid .manga-btn-in-queue').forEach(btn => {
                btn.className = 'manga-btn';
                btn.textContent = '➕ 加入待下载列表';
            });
        }

        function openMangaQueueModal() {
            renderMangaQueueModalItems();
            pollMangaTasks();
            const modal = document.getElementById('manga-download-queue-modal');
            if (modal) modal.style.display = 'flex';
        }

        function closeMangaQueueModal() {
            const modal = document.getElementById('manga-download-queue-modal');
            if (modal) modal.style.display = 'none';
        }

        function renderMangaQueueModalItems() {
            updateMangaQueueBadge();
            const listEl = document.getElementById('manga-queue-items-list');
            const emptyEl = document.getElementById('manga-queue-empty-msg');
            const startBtn = document.getElementById('manga-queue-start-download-btn');
            const seqBtn = document.getElementById('manga-queue-seq-download-btn');
            const clearBtn = document.getElementById('manga-queue-clear-btn');
            if (!listEl) return;

            listEl.innerHTML = '';
            if (mangaDownloadQueue.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                if (startBtn) startBtn.disabled = true;
                if (seqBtn) seqBtn.disabled = true;
                if (clearBtn) clearBtn.disabled = true;
                return;
            }

            if (emptyEl) emptyEl.style.display = 'none';
            if (startBtn) startBtn.disabled = false;
            if (seqBtn) seqBtn.disabled = false;
            if (clearBtn) clearBtn.disabled = false;

            mangaDownloadQueue.forEach(item => {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;background:#0d1117;padding:8px 12px;border-radius:8px;border:1px solid #21262d;gap:10px;';
                row.innerHTML = `
                    <div style="display:flex;align-items:center;gap:10px;overflow:hidden;flex:1;">
                        <img src="${item.cover_url}" style="width:36px;height:48px;object-fit:cover;border-radius:4px;background:#21262d;" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'36\\' height=\\'48\\' fill=\\'%2321262d\\'><rect width=\\'36\\' height=\\'48\\'/></svg>'">
                        <div style="overflow:hidden;">
                            <div style="font-size:13px;font-weight:600;color:#f0f6fc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                            <div style="font-size:11px;color:#58a6ff;margin-top:2px;">JM${item.id}</div>
                        </div>
                    </div>
                    <button class="manga-mini-btn" style="color:#f85149;border-color:#f8514944;padding:4px 8px;" onclick="removeMangaQueueItem('${item.id}')">✕ 移除</button>
                `;
                listEl.appendChild(row);
            });
        }

        function startMangaQueueBatchDownload(concurrency = 3) {
            if (mangaDownloadQueue.length === 0) {
                alert('漫画待下载列表为空！请先搜索漫画并添加到列表。');
                return;
            }
            const ids = mangaDownloadQueue.map(item => item.id);
            closeMangaQueueModal();

            fetch('/api/manga/batch_download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    album_ids: ids,
                    dir: 'manga',
                    pack_cbz: true,
                    clean_temp: true,
                    concurrency: concurrency
                })
            })
            .then(r => r.json())
            .then(res => {
                pollMangaTasks();
            })
            .catch(err => {
                alert('启动批量下载失败: ' + err);
            });
        }

        function stopMangaBatchDownload(taskId) {
            const queueStopBtn = document.getElementById('manga-queue-stop-btn');
            if (queueStopBtn) {
                queueStopBtn.disabled = true;
                queueStopBtn.textContent = '⏳ 正在请求停止...';
            }
            fetch('/api/manga/stop_batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId || null })
            })
            .then(r => r.json())
            .then(res => {
                pollMangaTasks();
            })
            .catch(err => {
                console.error('Failed to stop batch download:', err);
            });
        }



        function executeUnifiedSearch(overrideQuery) {
            const input = document.getElementById('manga-search-input');
            const q = (overrideQuery !== undefined ? overrideQuery : (input ? input.value : '') || '').trim();
            if (!q) {
                clearMangaSearch();
                return;
            }

            currentMangaSearchQuery = q;
            currentMangaPage = 1;
            hasMoreMangaPages = false;
            isLoadingMoreManga = false;
            totalOnlineMangaCount = 0;

            // 1. 本地匹配 (支持繁简双向与标签模糊匹配)
            const matchedLocal = filterLocalManga(q);
            const localSection = document.getElementById('manga-local-section');
            const localHeading = document.getElementById('manga-local-heading');
            const emptyEl = document.getElementById('manga-shelf-empty');

            if (localSection) localSection.style.display = 'block';
            if (localHeading) localHeading.textContent = `🟢 本地已收录 (匹配到 ${matchedLocal.length} 部 · 点击封面直接阅读)`;
            renderMangaShelf(matchedLocal);
            if (emptyEl) emptyEl.style.display = matchedLocal.length === 0 ? 'block' : 'none';

            // 2. 同时检索禁漫全网（支持单 ID、多 ID 或标题关键字）
            const onlineSection = document.getElementById('manga-online-section');
            const onlineLoading = document.getElementById('manga-online-loading');
            const onlineGrid = document.getElementById('manga-online-grid');
            const kwLabel = document.getElementById('manga-search-kw-label');
            const moreLoading = document.getElementById('manga-online-more-loading');
            const endTip = document.getElementById('manga-online-end-tip');

            if (moreLoading) moreLoading.style.display = 'none';
            if (endTip) endTip.style.display = 'none';

            if (onlineSection) onlineSection.style.display = 'block';
            if (onlineLoading) onlineLoading.style.display = 'block';
            if (onlineGrid) onlineGrid.innerHTML = '';
            if (kwLabel) kwLabel.textContent = `正在全网检索: "${q}"...`;

            fetch('/api/manga/search?q=' + encodeURIComponent(q) + '&category=0&order_by=' + encodeURIComponent(currentMangaSort || 'mv') + '&page=1&t=' + Date.now())
                .then(r => r.json())
                .then(data => {
                    if (onlineLoading) onlineLoading.style.display = 'none';
                    currentOnlineResults = data.online || [];
                    hasMoreMangaPages = !!data.has_more;
                    totalOnlineMangaCount = data.total_online || currentOnlineResults.length;

                    if (kwLabel) {
                        if (totalOnlineMangaCount > currentOnlineResults.length) {
                            kwLabel.textContent = `检索: "${q}" (已加载 ${currentOnlineResults.length}/${totalOnlineMangaCount} 部 · 向下滚动自动加载更多)`;
                        } else {
                            kwLabel.textContent = `检索: "${q}" (共 ${currentOnlineResults.length} 部)`;
                        }
                    }

                    renderOnlineResults(currentOnlineResults, matchedLocal.length === 0, false);

                    if (!hasMoreMangaPages && currentOnlineResults.length > 0 && endTip) {
                        endTip.style.display = 'block';
                    }
                })
                .catch(err => {
                    if (onlineLoading) onlineLoading.style.display = 'none';
                    if (onlineGrid) onlineGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f85149;padding:40px;">禁漫在线检索遇到异常: ${err}</div>`;
                });
        }

        function findLocalMangaMatch(onlineItem) {
            if (!localMangaList || localMangaList.length === 0) return null;
            const oId = String(onlineItem.id);
            const oTitle = (onlineItem.title || '').trim().toLowerCase();
            return localMangaList.find(local => {
                const lTitle = (local.title || '').trim().toLowerCase();
                const lFile = (local.filename || '').trim().toLowerCase();
                return lFile.includes(oId) || lTitle.includes(oId) || (oTitle && lTitle === oTitle);
            });
        }

        function loadNextMangaPage() {
            if (isLoadingMoreManga || !hasMoreMangaPages || !currentMangaSearchQuery) return;
            isLoadingMoreManga = true;
            const moreLoading = document.getElementById('manga-online-more-loading');
            const endTip = document.getElementById('manga-online-end-tip');
            if (moreLoading) moreLoading.style.display = 'block';
            if (endTip) endTip.style.display = 'none';

            const nextPage = currentMangaPage + 1;
            fetch('/api/manga/search?q=' + encodeURIComponent(currentMangaSearchQuery) + '&category=0&order_by=' + encodeURIComponent(currentMangaSort) + '&page=' + nextPage + '&t=' + Date.now())
                .then(r => r.json())
                .then(data => {
                    if (moreLoading) moreLoading.style.display = 'none';
                    isLoadingMoreManga = false;

                    const newItems = data.online || [];
                    if (newItems.length > 0) {
                        currentMangaPage = nextPage;
                        hasMoreMangaPages = !!data.has_more;
                        totalOnlineMangaCount = data.total_online || totalOnlineMangaCount;
                        currentOnlineResults.push(...newItems);

                        const kwLabel = document.getElementById('manga-search-kw-label');
                        if (kwLabel) {
                            kwLabel.textContent = `检索: "${currentMangaSearchQuery}" (已加载 ${currentOnlineResults.length}/${totalOnlineMangaCount} 部${hasMoreMangaPages ? ' · 向下滚动加载更多' : ''})`;
                        }

                        renderOnlineResults(newItems, false, true); // true = 追加模式，绝不刷新前面已有的卡片
                    } else {
                        hasMoreMangaPages = false;
                    }

                    if (!hasMoreMangaPages && endTip) {
                        endTip.style.display = 'block';
                    }
                })
                .catch(err => {
                    isLoadingMoreManga = false;
                    if (moreLoading) moreLoading.style.display = 'none';
                    console.error('Failed to load next page of manga:', err);
                });
        }

        function clearOnlineSearchResults() {
            const onlineSection = document.getElementById('manga-online-section');
            const onlineGrid = document.getElementById('manga-online-grid');
            const kwLabel = document.getElementById('manga-search-kw-label');
            const endTip = document.getElementById('manga-online-end-tip');
            const moreLoading = document.getElementById('manga-online-more-loading');

            if (onlineSection) onlineSection.style.display = 'none';
            if (onlineGrid) onlineGrid.innerHTML = '';
            if (kwLabel) kwLabel.textContent = '';
            if (endTip) endTip.style.display = 'none';
            if (moreLoading) moreLoading.style.display = 'none';
            currentOnlineResults = [];
            currentMangaSearchQuery = '';
            currentMangaPage = 1;
            hasMoreMangaPages = false;
            isLoadingMoreManga = false;
        }

        function clearMangaSearch() {
            const input = document.getElementById('manga-search-input');
            if (input) input.value = '';

            const localSection = document.getElementById('manga-local-section');
            const localHeading = document.getElementById('manga-local-heading');
            if (localSection) localSection.style.display = 'block';
            if (localHeading) localHeading.textContent = '📚 本地已收录漫画';
            let list = localMangaList;
            if (activeMangaTag === '__incomplete__') {
                list = localMangaList.filter(item => item.is_complete === false);
            } else if (activeMangaTag !== 'all') {
                const normTag = normalizeZh(activeMangaTag);
                list = localMangaList.filter(item => Array.isArray(item.tags) && item.tags.some(t => normalizeZh(t) === normTag || t === activeMangaTag));
            }
            renderMangaShelf(list);
            updateMangaIncompleteBanner();

            clearOnlineSearchResults();
        }

        function renderOnlineResults(results, isLocalEmpty = false, isAppend = false) {
            const grid = document.getElementById('manga-online-grid');
            if (!grid) return;
            if (!isAppend) {
                grid.innerHTML = '';
            }

            if (!results || results.length === 0) {
                if (!isAppend) {
                    if (isLocalEmpty) {
                        grid.innerHTML = `
                            <div style="grid-column: 1/-1; text-align: center; color: #8b949e; padding: 50px 20px;">
                                <div style="font-size:36px;margin-bottom:10px;">🔍</div>
                                <div style="font-size:15px;font-weight:600;color:#f0f6fc;">未检索到匹配的漫画作品</div>
                                <div style="font-size:13px;margin-top:6px;">请检查输入的编号或漫画名，支持同时输入多个编号（如 287234, 1074734）。</div>
                            </div>
                        `;
                    } else {
                        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: #8b949e; padding: 30px;">全网暂未找到更多在线结果（已在上方展示本地已收录版本）</div>`;
                    }
                }
                return;
            }

            results.forEach(item => {
                const card = document.createElement('div');
                card.className = 'manga-card';
                const inQueue = isMangaInQueue(item.id);
                const localMatch = findLocalMangaMatch(item);

                let badgeHtml = `<span class="manga-badge-online">JM${item.id}</span>`;
                let actionHtml = '';

                if (localMatch) {
                    const isInc = (localMatch.is_complete === false);
                    if (isInc) {
                        badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#d29922dd;color:#fff;" title="本地仅收录部分章节">⚠️ ${localMatch.local_chapters || '?'}/${localMatch.online_chapters || '?'}话</span>`;
                        actionHtml = `
                            <div style="display:flex;gap:6px;margin-top:8px;">
                                <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#d29922;border-color:#bb8009;justify-content:center;" onclick="startSupplementSingleManga('${item.id}', '${escapeAttr(localMatch.filename)}', 'manga', '${escapeAttr(item.title)}')">
                                    📥 增量补更新
                                </button>
                                <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;color:#fff;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">📖 阅读</button>
                            </div>
                        `;
                    } else {
                        badgeHtml += `<span class="manga-badge-cbz" style="left:auto;right:8px;background:#238636;">✓ 已在书架</span>`;
                        actionHtml = `
                            <div style="display:flex;gap:6px;margin-top:8px;">
                                <button class="manga-btn manga-btn-primary" style="flex:1;font-size:11.5px;padding:5px 8px;background:#238636;border-color:#2ea043;justify-content:center;" onclick="openMangaReader('${escapeAttr(localMatch.filename)}', 'manga')">
                                    📖 立即阅读
                                </button>
                                <button class="manga-btn" style="font-size:11.5px;padding:5px 8px;" title="重新下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">🔄 重下</button>
                            </div>
                        `;
                    }
                } else {
                    actionHtml = `
                        <div style="display:flex;gap:6px;margin-top:8px;">
                            <button id="manga-queue-btn-${item.id}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="flex:1;font-size:11.5px;padding:5px 8px;justify-content:center;" onclick="toggleMangaQueueItem('${item.id}', '${escapeAttr(item.title)}', '${escapeAttr(item.cover_url)}', this)">
                                ${inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表'}
                            </button>
                            <button class="manga-btn manga-btn-primary" style="font-size:11.5px;padding:5px 8px;" title="立即下载整本" onclick="startFullMangaDownload('${item.id}', '${escapeAttr(item.title)}', 'manga')">📥 一键下载</button>
                        </div>
                    `;
                }

                const tagsList = Array.isArray(item.tags) ? item.tags : [];
                const onlineTagsHtml = tagsList.length > 0
                    ? `<div class="manga-tags-row" onclick="event.stopPropagation()">
                        ${tagsList.slice(0, 3).map(t => `<span class="manga-tag-pill" title="按标签筛选: ${escapeAttr(t)}" onclick="filterMangaByTag('${escapeAttr(t)}')">🏷️ ${escapeHtml(t)}</span>`).join('')}
                      </div>`
                    : '';

                card.innerHTML = `
                    <div class="manga-cover-wrap">
                        <img src="${item.cover_url}" class="manga-cover" loading="lazy" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'130\\' fill=\\'%2321262d\\'><rect width=\\'100\\' height=\\'130\\'/></svg>'">
                        ${badgeHtml}
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        ${onlineTagsHtml}
                        ${actionHtml}
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function startFullMangaDownload(albumId, title) {
            fetch('/api/manga/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    album_id: albumId,
                    chapter_ids: null,
                    pack_cbz: true,
                    clean_temp: true
                })
            }).then(r => r.json()).then(res => {
                alert(`已启动《${title || albumId}》的后台全本异步下载与解密打包！`);
                pollMangaTasks();
            }).catch(err => {
                alert('启动下载失败: ' + err);
            });
        }

        function openChapterSelectModal(albumId) {
            const modal = document.getElementById('manga-chapters-modal');
            modal.style.display = 'flex';
            document.getElementById('modal-album-title').textContent = '正在获取章节目录...';
            document.getElementById('modal-album-author').textContent = '';
            document.getElementById('modal-chapters-list').innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#8b949e;padding:20px;">正在加载章节列表...</div>';

            fetch('/api/manga/detail?id=' + albumId)
                .then(r => r.json())
                .then(detail => {
                    currentModalAlbumDetail = detail;
                    document.getElementById('modal-album-title').textContent = detail.title;
                    document.getElementById('modal-album-author').textContent = '作者: ' + (detail.author || '未知') + ' · 共 ' + (detail.chapters || []).length + ' 话';

                    const listEl = document.getElementById('modal-chapters-list');
                    listEl.innerHTML = '';
                    (detail.chapters || []).forEach(ch => {
                        const label = document.createElement('label');
                        label.style.cssText = 'display:flex;align-items:center;gap:6px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 10px;font-size:12px;color:#c9d1d9;cursor:pointer;';
                        label.innerHTML = `
                            <input type="checkbox" class="chapter-cb" value="${ch.photo_id}" checked onchange="updateSelectedChapterCount()">
                            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeAttr(ch.title)}">${escapeHtml(ch.title)}</span>
                        `;
                        listEl.appendChild(label);
                    });
                    updateSelectedChapterCount();
                })
                .catch(err => {
                    document.getElementById('modal-chapters-list').innerHTML = `<div style="grid-column:1/-1;color:#f85149;">加载失败: ${err}</div>`;
                });
        }

        function updateSelectedChapterCount() {
            const cbs = document.querySelectorAll('.chapter-cb:checked');
            document.getElementById('modal-selected-count').textContent = '已选 ' + cbs.length + ' 话';
        }

        function selectAllChapters(select) {
            document.querySelectorAll('.chapter-cb').forEach(cb => cb.checked = select);
            updateSelectedChapterCount();
        }

        function closeChapterModal() {
            document.getElementById('manga-chapters-modal').style.display = 'none';
        }

        function confirmDownloadSelectedChapters() {
            if (!currentModalAlbumDetail) return;
            const selected = Array.from(document.querySelectorAll('.chapter-cb:checked')).map(cb => cb.value);
            if (selected.length === 0) {
                alert('请至少勾选一个章节！');
                return;
            }
            const cleanTemp = document.getElementById('modal-clean-temp-cb').checked;
            closeChapterModal();

            fetch('/api/manga/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    album_id: currentModalAlbumDetail.id,
                    chapter_ids: selected,
                    pack_cbz: true,
                    clean_temp: cleanTemp
                })
            }).then(r => r.json()).then(res => {
                alert(`已启动 ${selected.length} 个勾选章节的后台下载与解密！`);
                pollMangaTasks();
            }).catch(err => {
                alert('启动下载任务失败: ' + err);
            });
        }

        function renderMangaTasksProgress(tasks) {
            const container = document.getElementById('manga-tasks-container');
            const card = document.getElementById('manga-tasks-card');
            if (!container || !card) return;

            if (!tasks || tasks.length === 0) {
                container.style.display = 'none';
                return;
            }

            // 同步模态弹窗中的【⏹️ 完工当前后停止】按钮
            const queueStopBtn = document.getElementById('manga-queue-stop-btn');
            const activeBatch = tasks.find(t => t.is_batch && (t.status === 'downloading' || t.status === 'queued'));
            if (queueStopBtn) {
                if (activeBatch) {
                    queueStopBtn.style.display = 'inline-block';
                    if (activeBatch.stopping) {
                        queueStopBtn.disabled = true;
                        queueStopBtn.textContent = '⏳ 完工后将停止';
                        queueStopBtn.style.opacity = '0.6';
                    } else {
                        queueStopBtn.disabled = false;
                        queueStopBtn.textContent = '⏹️ 完工当前后停止';
                        queueStopBtn.style.opacity = '1';
                    }
                } else {
                    queueStopBtn.style.display = 'none';
                }
            }

            const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed');
            if (activeTasks.length > 0) {
                container.style.display = 'block';
                card.innerHTML = tasks.slice(0, 3).map(t => `
                    <div style="display:flex;flex-direction:column;gap:6px;padding:6px 0;border-bottom:1px solid #21262d;">
                        <div class="manga-task-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                            <div style="font-size:13px;font-weight:600;color:#f0f6fc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">${escapeHtml(t.title)}</div>
                            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                                <div style="font-size:12px;color:#58a6ff;font-weight:700;">${t.percent}%</div>
                                ${t.is_batch && (t.status === 'downloading' || t.status === 'queued') ? `
                                    <button class="manga-mini-btn" style="padding:2px 8px;font-size:11px;color:${t.stopping ? '#8b949e' : '#f85149'};border-color:${t.stopping ? '#30363d' : '#f8514966'};background:#21262d;"
                                        onclick="stopMangaBatchDownload('${t.task_id}')"
                                        ${t.stopping ? 'disabled' : ''}>
                                        ${t.stopping ? '⏳ 完工后将停止' : '⏹️ 完工当前后停止'}
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: ${t.percent}%;"></div>
                        </div>
                        <div style="font-size:11.5px;color:#8b949e;">${escapeHtml(t.message || '')}</div>
                    </div>
                `).join('');
            } else {
                setTimeout(() => { container.style.display = 'none'; }, 4000);
            }
        }

        // ================= 异步事件推送流 (Server-Sent Events) =================
        let mangaEventSource = null;

        function initMangaEventStream() {
            if (mangaEventSource) return;
            try {
                mangaEventSource = new EventSource('/api/manga/events');
                mangaEventSource.onmessage = function(e) {
                    try {
                        const event = JSON.parse(e.data);
                        if (event.type === 'init') {
                            if (Array.isArray(event.manga_queue)) {
                                mangaDownloadQueue = event.manga_queue;
                                updateMangaQueueBadge();
                            }
                            if (Array.isArray(event.tasks)) {
                                renderMangaTasksProgress(event.tasks);
                            }
                            // SSE 初始化时同步网络状态与客户端身份判定
                            if (event.lan) {
                                updateLanButtonUI(event.lan);
                                if (typeof event.lan.is_remote === 'boolean') {
                                    isRemoteClient = event.lan.is_remote;
                                    if (isRemoteClient) {
                                        applyRemoteClientRestrictions();
                                    } else {
                                        removeRemoteClientRestrictions();
                                    }
                                }
                            }
                            if (event.wan) {
                                updateWanButtonUI(event.wan);
                            }
                        } else if (event.type === 'network_status') {
                            // 跨窗口实时同步：任意窗口切换了局域网或广域网开关后，所有连接的客户端毫秒级同步刷新按钮状态
                            if (event.lan) updateLanButtonUI(event.lan);
                            if (event.wan) updateWanButtonUI(event.wan);
                        } else if (event.type === 'album_completed') {
                            // 异步回调：新下好一部，毫秒级无感热上架本地书架，同时从待下载列表秒级剔除！
                            loadMangaLibrary();
                            loadNovelsLibrary();
                            if (event.dir === 'novels') {
                                if (Array.isArray(event.queue)) {
                                    novelDownloadQueue = event.queue;
                                    updateNovelQueueBadge();
                                    renderNovelQueueModalItems();
                                }
                            } else {
                                if (Array.isArray(event.queue)) {
                                    mangaDownloadQueue = event.queue;
                                    updateMangaQueueBadge();
                                    renderMangaQueueModalItems();
                                }
                            }
                        } else if (event.type === 'queue_updated') {
                            if (event.dir === 'novels') {
                                if (Array.isArray(event.queue)) {
                                    novelDownloadQueue = event.queue;
                                    updateNovelQueueBadge();
                                    renderNovelQueueModalItems();
                                }
                            } else {
                                if (Array.isArray(event.queue)) {
                                    mangaDownloadQueue = event.queue;
                                    updateMangaQueueBadge();
                                    renderMangaQueueModalItems();
                                }
                            }
                        } else if (event.type === 'metadata_updated') {
                            if (Array.isArray(localMangaList)) {
                                const target = localMangaList.find(it => it.filename === event.filename);
                                if (target) {
                                    target.tags = event.tags || [];
                                    if (typeof event.is_complete === 'boolean') target.is_complete = event.is_complete;
                                    if (event.online_chapters) target.online_chapters = event.online_chapters;
                                    if (event.local_chapters) target.local_chapters = event.local_chapters;
                                    renderMangaTagBar();
                                }
                            }
                        } else if (event.type === 'progress') {
                            // 实时推送进度，零多余 HTTP 轮询！
                            if (event.task) {
                                renderMangaTasksProgress([event.task]);
                            }
                        } else if (event.type === 'batch_completed') {
                            loadMangaLibrary();
                            loadNovelsLibrary();
                            loadPersistentMangaQueue();
                            if (event.task) {
                                renderMangaTasksProgress([event.task]);
                            }
                        } else if (event.type === 'library_indexed') {
                            // 后台补媒体索引：中途 debounce 刷一次，补完立刻刷
                            const dir = event.dir;
                            const finished = event.total && event.done >= event.total;
                            const doReload = () => {
                                if (dir === 'novels') loadNovelsLibrary();
                                else loadMangaLibrary();
                            };
                            if (finished) {
                                doReload();
                            } else {
                                clearTimeout(window.__libIdxTimer);
                                window.__libIdxTimer = setTimeout(doReload, 1500);
                            }
                        }
                    } catch(err) {}
                };
            } catch(e) {}
        }

        let lastCompletedMangaCount = -1;

        function pollMangaTasks() {
            initMangaEventStream();
            fetch('/api/manga/tasks?t=' + Date.now())
                .then(r => r.json())
                .then(tasks => {
                    renderMangaTasksProgress(tasks);
                })
                .catch(() => {});
        }

        function cleanMangaTemp() {
            fetch('/api/manga/clean_temp', { method: 'POST' })
                .then(r => r.json())
                .then(res => {
                    alert(`清理完成！已清理 ${res.cleaned_count || 0} 个临时解密切片目录/文件。`);
                });
        }

        // ================= 内嵌 Webtoon 瀑布流漫画/小说阅读器 =================
        let currentReaderDir = '';

        function openMangaReader(filename, dir = '') {
            currentReaderCbz = filename;
            currentReaderDir = dir || '';
            const modal = document.getElementById('manga-reader-modal');
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            document.documentElement.style.overflow = 'hidden';

            document.getElementById('reader-title').textContent = filename.replace(/\.(cbz|txt|epub)$/i, '');
            const container = document.getElementById('reader-image-container');
            container.innerHTML = '<div style="color:#8b949e;padding:50px;">正在解析封箱切片内容...</div>';

            const dirQuery = currentReaderDir ? '&dir=' + encodeURIComponent(currentReaderDir) : '';
            fetch('/api/manga/pages?name=' + encodeURIComponent(filename) + dirQuery)
                .then(r => r.json())
                .then(pages => {
                    container.innerHTML = '';
                    document.getElementById('reader-page-counter').textContent = '共 ' + pages.length + ' 页';
                    pages.forEach((p, idx) => {
                        const img = document.createElement('img');
                        img.className = 'reader-img';
                        img.loading = idx < 3 ? 'eager' : 'lazy';
                        img.src = `/api/manga/page?name=${encodeURIComponent(filename)}&page=${encodeURIComponent(p)}${dirQuery}`;
                        container.appendChild(img);
                    });

                    // 恢复上次浏览滚动位置
                    const savedPos = localStorage.getItem('omni_manga_scroll_' + filename);
                    if (savedPos) {
                        setTimeout(() => { modal.scrollTop = parseInt(savedPos, 10); }, 50);
                    } else {
                        modal.scrollTop = 0;
                    }
                })
                .catch(err => {
                    container.innerHTML = `<div style="color:#f85149;padding:50px;">读取失败: ${err}</div>`;
                });

            // 监听滚动位置并实时记忆
            modal.onscroll = () => {
                try {
                    localStorage.setItem('omni_manga_scroll_' + filename, modal.scrollTop);
                } catch(e) {}
            };
        }

        function closeMangaReader() {
            document.getElementById('manga-reader-modal').style.display = 'none';
            document.getElementById('reader-image-container').innerHTML = '';
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }

        function openCurrentMangaExternal() {
            if (currentReaderCbz) {
                openExternalManga(currentReaderCbz, currentReaderDir);
            }
        }

        function openExternalManga(filename, dir = '') {
            fetch('/api/manga/open_external', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: filename, dir: dir })
            });
        }

        function deleteMangaFile(filename, dir = '') {
            if (!confirm(`确定将《${filename}》移至回收站吗？`)) return;
            fetch('/api/manga/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: filename, dir: dir })
            }).then(r => r.json()).then(res => {
                if (dir === 'novels') {
                    loadNovelsLibrary();
                } else {
                    loadMangaLibrary();
                }
            });
        }

        function startFullMangaDownload(album_id, title, dir = 'manga') {
            fetch('/api/manga/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ album_id: album_id, dir: dir, pack_cbz: true, clean_temp: true })
            })
            .then(r => r.json())
            .then(res => {
                pollMangaTasks();
            })
            .catch(err => {
                alert('启动下载遇到异常: ' + err);
            });
        }

        function toggleReaderFullscreen() {
            const modal = document.getElementById('manga-reader-modal');
            const btn = document.getElementById('manga-fullscreen-btn');
            const isImmersive = modal.classList.toggle('reader-immersive-fullscreen');

            if (!document.fullscreenElement) {
                const req = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || modal.requestFullscreen;
                if (req) {
                    req.call(document.documentElement || modal).catch(() => {});
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen().catch(() => {});
                }
            }

            if (btn) {
                btn.textContent = (isImmersive || document.fullscreenElement) ? '🗗 退出全屏' : '⛶ 全屏';
            }
        }

        // ================= 小说画廊 (Novel Gallery - 对接禁漫在线小说与独立小说书架) =================
        let currentNovelSearchQuery = '';
        let currentNovelPage = 1;
        let currentNovelSort = 'mr';
        let hasMoreNovelPages = false;
        let isLoadingMoreNovels = false;
        let currentOnlineNovelResults = [];
        let totalOnlineNovelCount = 0;

        function onNovelSortChange(val) {
            currentNovelSort = val || 'mr';
            const input = document.getElementById('novel-search-input');
            const valInput = (input ? input.value : '').trim();
            if (valInput) {
                executeUnifiedNovelSearch(valInput);
            }
        }



        // ================= 小说画廊 (Novel Gallery - 纯净隔离与专业 EPUB 阅读系统) =================
        let isNovelNsfw = false;
        let novelSearchTimer = null;
        let novelOnlineResults = [];
        let novelDownloadQueue = [];
        let novelTasksPollingTimer = null;

        function toggleNovelNsfw() {
            if (!isNovelNsfw && !isNsfwUnlocked) {
                openNsfwModal();
                return;
            }
            isNovelNsfw = !isNovelNsfw;
            const btn = document.getElementById('novel-nsfw-toggle-btn');
            const heading = document.getElementById('novel-shelf-heading');
            const searchInput = document.getElementById('novel-search-input');
            const srcIndicator = document.getElementById('novel-source-indicator');
            const srcTip = document.getElementById('novel-source-tip');

            if (isNovelNsfw) {
                if (btn) {
                    btn.classList.add('active');
                    btn.style.background = '#da363333';
                    btn.style.borderColor = '#da3633';
                    btn.style.color = '#f85149';
                    btn.style.fontWeight = '700';
                }
                if (heading) heading.textContent = '🔞 NSFW 杏书私有书架';
                if (searchInput) searchInput.placeholder = '🔍 搜索 xbookcn 小说书名、作者或题材 (回车检索)...';
                if (srcIndicator) {
                    srcIndicator.textContent = 'blog.xbookcn.net ↗';
                    srcIndicator.href = 'https://blog.xbookcn.net';
                    srcIndicator.target = '_blank';
                    srcIndicator.rel = 'noopener noreferrer';
                    srcIndicator.style.textDecoration = 'underline';
                    srcIndicator.style.cursor = 'pointer';
                    srcIndicator.title = '点击在浏览器中打开: https://blog.xbookcn.net';
                }
                if (srcTip) {
                    srcTip.textContent = '杏书网 / 小书屋精品情色文学 (历史情色/现代都市/长篇巨著/人妻乱伦) · 回车检索';
                }
            } else {
                if (btn) {
                    btn.classList.remove('active');
                    btn.style.background = '';
                    btn.style.borderColor = '';
                    btn.style.color = '';
                    btn.style.fontWeight = '';
                }
                if (heading) heading.textContent = '📚 本地已收录小说';
                if (searchInput) searchInput.placeholder = '🔍 搜索小说书名、作者或关键词 (回车检索)...';
                if (srcIndicator) {
                    srcIndicator.textContent = 'www.gutenberg.org ↗';
                    srcIndicator.href = 'https://www.gutenberg.org';
                    srcIndicator.target = '_blank';
                    srcIndicator.rel = 'noopener noreferrer';
                    srcIndicator.style.textDecoration = 'underline';
                    srcIndicator.style.cursor = 'pointer';
                    srcIndicator.title = '点击在浏览器中打开: https://www.gutenberg.org';
                }
                if (srcTip) {
                    srcTip.textContent = '支持书名/作者/分类/题材多维检索 (回车检索)';
                }
            }

            activeNovelCategory = 'all';
            loadNovelsLibrary();
            syncNovelQueue();

            const searchVal = (searchInput ? searchInput.value : '').trim();
            if (searchVal) {
                executeNovelSearch(searchVal);
            } else {
                const onlineSec = document.getElementById('novel-online-section');
                if (onlineSec) onlineSec.style.display = 'none';
            }
        }

        let activeNovelCategory = 'all';

        function renderNovelCategoryBar() {
            const bar = document.getElementById('novel-category-filter-bar');
            if (!bar) return;

            const catCounts = {};
            localNovelsList.forEach(item => {
                const cat = item.category || (isNovelNsfw ? '另类小说' : '公版名著');
                catCounts[cat] = (catCounts[cat] || 0) + 1;
            });

            const preferredCategories = isNovelNsfw ? [
                '精选作品', '现代情色', '日本情色', '西洋情色', '伴侣交换',
                '武侠情色', '奇幻科幻', '家庭乱伦', '性爱调教', '粗野性交',
                '多人群交', '教师学生', '古典情色', '历史情色', '同性情色',
                '都市生活', '乡间记趣', '疯狂暴露', '午夜怪谈', '游戏乐园',
                '医生护士', '奇遇物语', '左邻右舍', '同事之间', '旅游纪事',
                '纯洁恋情', '明星系列', '意外收获', '忘年之乐', '另类其他',
                '知识技巧', '文学评论', '精选长篇典藏'
            ] : [
                '英语进阶', '一生必读100本', '世界名著精选', '中国智慧与谋略', '中国法律法规', '公版名著'
            ];
            const categories = Array.from(new Set([...preferredCategories, ...Object.keys(catCounts)]));
            let html = `<button class="novel-cat-btn ${activeNovelCategory === 'all' ? 'active' : ''}" onclick="setNovelCategoryFilter('all')">🏷️ 全部 (${localNovelsList.length})</button>`;
            
            categories.forEach(c => {
                const cnt = catCounts[c] || 0;
                if (cnt > 0) {
                    html += `<button class="novel-cat-btn ${activeNovelCategory === c ? 'active' : ''}" onclick="setNovelCategoryFilter('${escapeAttr(c)}')">${escapeHtml(c)} (${cnt})</button>`;
                }
            });

            bar.innerHTML = html;
            bar.style.display = 'flex';
        }

        function setNovelCategoryFilter(cat) {
            activeNovelCategory = cat;
            renderNovelCategoryBar();
            const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
            renderNovelsShelf(filterLocalNovels(searchVal));
        }

        function loadNovelsLibrary() {
            fetch(`/api/novels/library?nsfw=${isNovelNsfw ? 1 : 0}&t=${Date.now()}`)
                .then(r => r.json())
                .then(list => {
                    localNovelsList = list || [];
                    if (activePrimarySection === 'media' && activeMediaTab === 'novels') {
                        const modeTag = isNovelNsfw ? ' (NSFW)' : '';
                        document.getElementById('total-badge').textContent = `${localNovelsList.length} 本已收录小说${modeTag}`;
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = `共 ${localNovelsList.length} 本已收录作品${modeTag}`;
                    }
                    const countEl = document.getElementById('novel-local-count');
                    if (countEl) countEl.textContent = `(${localNovelsList.length} 部 · EPUB / TXT)`;
                    
                    renderNovelCategoryBar();

                    const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
                    renderNovelsShelf(filterLocalNovels(searchVal));
                })
                .catch(err => {
                    console.error('Failed to load novels library:', err);
                });
        }

        function filterLocalNovels(query) {
            const q = (query || '').toLowerCase();
            return localNovelsList.filter(item => {
                if (activeNovelCategory !== 'all') {
                    if ((item.category || '') !== activeNovelCategory) {
                        return false;
                    }
                }
                if (!q) return true;
                return (item.title && item.title.toLowerCase().includes(q)) ||
                       (item.author && item.author.toLowerCase().includes(q)) ||
                       (item.category && item.category.toLowerCase().includes(q)) ||
                       (item.rel_path && item.rel_path.toLowerCase().includes(q));
            });
        }

        let currentNovelsShelfList = [];
        let novelShelfRenderIndex = 0;
        const NOVEL_SHELF_PAGE_SIZE = 30;

        function renderNovelsShelf(list, reset = true) {
            const grid = document.getElementById('novels-shelf-grid');
            const emptyEl = document.getElementById('novels-shelf-empty');
            if (!grid) return;

            if (reset) {
                grid.innerHTML = '';
                currentNovelsShelfList = (list !== undefined && list !== null ? list : localNovelsList) || [];
                novelShelfRenderIndex = 0;
            }

            if (!currentNovelsShelfList || currentNovelsShelfList.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';

            const nextChunk = currentNovelsShelfList.slice(novelShelfRenderIndex, novelShelfRenderIndex + NOVEL_SHELF_PAGE_SIZE);
            nextChunk.forEach(item => {
                const card = document.createElement('div');
                card.className = 'novel-card';
                const safeName = escapeAttr(item.filename || item.rel_path);
                const ext = (item.ext || '').toLowerCase();
                const isEpub = ext === 'epub';
                card.onclick = () => openNovelReader(item.rel_path || item.filename);
                
                const badgeLabel = isEpub ? 'EPUB' : (ext === 'txt' ? 'TXT' : ext.toUpperCase());
                const badgeClass = isEpub ? 'novel-badge-txt' : (ext === 'md' ? 'novel-badge-md' : 'novel-badge-rst');
                const sizeText = item.size_mb ? `${item.size_mb} MB` : (item.size_kb ? `${item.size_kb} KB` : `${item.char_count || 0} 字`);
                const authorText = item.author && item.author !== '未知作者' ? `✍️ ${escapeHtml(item.author)} · ` : '';
                const catTag = item.category ? `<span class="novel-cat-pill">${escapeHtml(item.category)}</span>` : '';

                card.innerHTML = `
                    <div class="novel-card-top">
                        <div style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
                            <span style="font-size:15px;line-height:1;">📖</span>
                            <div class="novel-title" title="${safeName}">${escapeHtml(item.title)}</div>
                        </div>
                        <span class="novel-badge ${badgeClass}" style="flex-shrink:0;">${badgeLabel}</span>
                    </div>
                    <div class="novel-meta">
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:210px;">${catTag}${authorText}💾 ${sizeText}</span>
                        <button class="manga-mini-btn" title="移至回收站" style="padding:2px 7px;font-size:12px;" onclick="event.stopPropagation();deleteNovelFile('${escapeAttr(item.rel_path || item.filename)}')">🗑️</button>
                    </div>
                `;
                grid.appendChild(card);
            });
            novelShelfRenderIndex += nextChunk.length;
        }

        function loadMoreNovelsShelf() {
            if (novelShelfRenderIndex < currentNovelsShelfList.length) {
                renderNovelsShelf(null, false);
            }
        }

        function deleteNovelFile(relPath) {
            const filename = (relPath || '').split('/').pop() || relPath;
            if (!confirm(`确定将小说《${filename}》移至回收站吗？`)) return;
            fetch('/api/novels/trash', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: relPath })
            }).then(r => r.json()).then(res => {
                loadNovelsLibrary();
            }).catch(err => {
                console.error('Failed to delete novel file:', err);
            });
        }



        function executeNovelSearch(keyword) {
            const onlineSec = document.getElementById('novel-online-section');
            const loadingEl = document.getElementById('novel-online-loading');
            const grid = document.getElementById('novels-online-grid');
            const statsEl = document.getElementById('novel-online-stats');
            const endTip = document.getElementById('novel-online-end-tip');

            if (onlineSec) onlineSec.style.display = 'block';
            if (loadingEl) loadingEl.style.display = 'block';
            if (grid) grid.innerHTML = '';
            if (endTip) endTip.style.display = 'none';

            fetch(`/api/novels/search?nsfw=${isNovelNsfw ? 1 : 0}&q=${encodeURIComponent(keyword)}&t=${Date.now()}`)
                .then(r => r.json())
                .then(results => {
                    if (loadingEl) loadingEl.style.display = 'none';
                    novelOnlineResults = results || [];
                    if (statsEl) statsEl.textContent = `(共 ${novelOnlineResults.length} 部)`;
                    renderNovelOnlineResults(novelOnlineResults);
                    if (endTip) endTip.style.display = novelOnlineResults.length > 0 ? 'block' : 'none';
                })
                .catch(err => {
                    if (loadingEl) loadingEl.style.display = 'none';
                    if (grid) grid.innerHTML = `<div style="color:#f85149;padding:20px;grid-column:1/-1;text-align:center;">检索失败: ${err}</div>`;
                });
        }

        function isNovelInQueue(id) {
            return novelDownloadQueue.some(item => String(item.id) === String(id));
        }

        function toggleNovelQueueItem(id, btnEl) {
            id = String(id);
            const item = novelOnlineResults.find(b => String(b.id) === id);
            if (!item) return;

            const inQueue = isNovelInQueue(id);
            if (inQueue) {
                novelDownloadQueue = novelDownloadQueue.filter(b => String(b.id) !== id);
                fetch('/api/novels/queue', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'remove',
                        id: id,
                        is_nsfw: isNovelNsfw
                    })
                }).catch(e => console.error(e));
                updateNovelQueueUI(id, false, btnEl);
            } else {
                fetch('/api/novels/queue', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'add',
                        novel: {
                            id: id,
                            title: item.title,
                            author: item.author,
                            intro: item.intro,
                            cover_url: item.cover_url,
                            is_nsfw: isNovelNsfw
                        },
                        is_nsfw: isNovelNsfw
                    })
                }).then(() => {
                    novelDownloadQueue.push({
                        id: id,
                        title: item.title,
                        author: item.author,
                        intro: item.intro,
                        cover_url: item.cover_url,
                        is_nsfw: isNovelNsfw
                    });
                    updateNovelQueueUI(id, true, btnEl);
                });
            }
        }

        function updateNovelQueueUI(id, inQueue, btnEl) {
            const badgeCount = document.getElementById('novel-queue-badge-count');
            const modalBadge = document.getElementById('novel-queue-modal-badge');
            const btnCount = document.getElementById('novel-queue-btn-count');
            if (badgeCount) badgeCount.textContent = novelDownloadQueue.length;
            if (modalBadge) modalBadge.textContent = `(共 ${novelDownloadQueue.length} 部)`;
            if (btnCount) btnCount.textContent = novelDownloadQueue.length;

            const targetBtn = btnEl || document.getElementById(`novel-queue-btn-${id}`);
            if (targetBtn) {
                targetBtn.className = `manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}`;
                targetBtn.textContent = inQueue ? '✓' : '➕';
            }
            renderNovelQueueModal();
        }

        function renderNovelOnlineResults(results) {
            const grid = document.getElementById('novels-online-grid');
            if (!grid) return;
            grid.innerHTML = '';

            if (!results || results.length === 0) {
                grid.innerHTML = `<div style="color:#8b949e;padding:30px;grid-column:1/-1;text-align:center;">未找到匹配作品，请更换书名、作者或关键词重试</div>`;
                return;
            }

            const localTitleSet = new Set(localNovelsList.map(b => b.title.replace(/\.[^/.]+$/, '').trim()));

            results.forEach(item => {
                const card = document.createElement('div');
                card.className = 'novel-card';
                const isLocal = localTitleSet.has(item.title.trim()) || localNovelsList.some(b => b.title.includes(item.title) || item.title.includes(b.title));
                const inQueue = isNovelInQueue(item.id);
                const sourceUrl = item.source_url || (item.id && String(item.id).includes('classic_') ? `https://www.gutenberg.org/ebooks/${String(item.id).replace('classic_', '')}` : 'https://www.gutenberg.org');
                const sourceDisplay = 'www.gutenberg.org';

                const actionHtml = isLocal
                    ? `<button class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;" onclick="event.stopPropagation();openNovelReader('${escapeAttr(item.title)}')">📖 已收录</button>`
                    : `<button id="novel-queue-btn-${escapeAttr(item.id)}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="font-size:11px;padding:3px 6px;" onclick="event.stopPropagation();toggleNovelQueueItem('${escapeAttr(item.id)}', this)">${inQueue ? '✓' : '➕'}</button>
                       <button id="novel-dl-btn-${escapeAttr(item.id)}" class="manga-btn manga-btn-primary" style="font-size:11px;padding:3px 8px;" onclick="event.stopPropagation();downloadSingleNovelById('${escapeAttr(item.id)}', this)">📥 下载</button>`;

                card.onclick = () => {
                    if (isLocal) openNovelReader(item.title);
                };

                card.innerHTML = `
                    <div class="novel-card-top">
                        <div style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
                            <span style="font-size:15px;line-height:1;">📚</span>
                            <div class="novel-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        </div>
                        <span class="novel-badge novel-badge-txt" style="flex-shrink:0;">${escapeHtml(item.category || '公版典藏')}</span>
                    </div>
                    <div class="novel-meta" style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;font-size:12px;color:#8b949e;">✍️ ${escapeHtml(item.author || '佚名')}</span>
                        <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;" onclick="event.stopPropagation()">
                            ${actionHtml}
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function downloadSingleNovelById(id, btnEl) {
            const item = novelOnlineResults.find(b => b.id === id);
            if (!item) return;
            if (btnEl) {
                btnEl.disabled = true;
                btnEl.textContent = '⏳ 正在下载...';
            }
            downloadSingleNovel(item.id, item.title, item.author, item.intro, item.cover_url);
        }

        function downloadSingleNovel(id, title, author, intro, coverUrl) {
            fetch('/api/novels/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: id,
                    title: title,
                    author: author,
                    intro: intro,
                    cover_url: coverUrl,
                    is_nsfw: isNovelNsfw
                })
            }).then(r => r.json()).then(res => {
                pollNovelTasks();
            }).catch(err => {
                console.error('下载请求失败:', err);
            });
        }

        function pollNovelTasks() {
            fetch('/api/novels/tasks?t=' + Date.now())
                .then(r => r.json())
                .then(tasks => {
                    renderNovelTasks(tasks);
                    const running = (tasks || []).some(t => t.status === 'running');
                    if (running) {
                        if (!novelTasksPollingTimer) {
                            novelTasksPollingTimer = setInterval(pollNovelTasks, 1500);
                        }
                    } else {
                        if (novelTasksPollingTimer) {
                            clearInterval(novelTasksPollingTimer);
                            novelTasksPollingTimer = null;
                        }
                        loadNovelsLibrary();
                        syncNovelQueue();
                    }
                })
                .catch(() => {});
        }

        function renderNovelTasks(tasks) {
            const container = document.getElementById('novel-tasks-container');
            const card = document.getElementById('novel-tasks-card');
            if (!container || !card) return;

            const runningTasks = (tasks || []).filter(t => t.status === 'running');
            const recentTasks = (tasks || []).filter(t => t.status === 'running' || (t.status === 'completed' && Date.now() - (t.start_time || 0) * 1000 < 4000));

            if (recentTasks.length === 0) {
                container.style.display = 'none';
                return;
            }

            container.style.display = 'block';
            
            // 归一化展示：始终只显示 1 个主进度条，多任务时显示队列数量与当前进度
            const cur = runningTasks[0] || recentTasks[0];
            const queueCount = runningTasks.length;

            card.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                    <div style="font-size:13px;font-weight:600;color:#f0f6fc;display:flex;align-items:center;gap:6px;">
                        <span>📥 正在打包 EPUB: </span>
                        <span style="color:#58a6ff;">《${escapeHtml(cur.title)}》</span>
                        ${queueCount > 1 ? `<span style="font-size:11px;background:#21262d;color:#8b949e;padding:1px 6px;border-radius:4px;">剩余 ${queueCount - 1} 部排队</span>` : ''}
                    </div>
                    <div style="font-size:12px;color:#58a6ff;font-weight:700;">${cur.progress || 0}%</div>
                </div>
                <div style="width:100%;height:6px;background:#21262d;border-radius:3px;overflow:hidden;margin-bottom:6px;">
                    <div style="width:${cur.progress || 0}%;height:100%;background:#238636;transition:width 0.3s ease;"></div>
                </div>
                <div style="font-size:11px;color:#8b949e;display:flex;justify-content:space-between;">
                    <span>${escapeHtml(cur.msg || '处理中...')}</span>
                    ${queueCount > 1 ? `<span style="color:#7d8590;">总任务数: ${queueCount}</span>` : ''}
                </div>
            `;
        }

        // --- 小说待下载列表模态弹窗管理 ---
        function syncNovelQueue() {
            fetch(`/api/novels/queue?nsfw=${isNovelNsfw ? 1 : 0}&t=` + Date.now())
                .then(r => r.json())
                .then(q => {
                    novelDownloadQueue = q || [];
                    const badgeCount = document.getElementById('novel-queue-badge-count');
                    const modalBadge = document.getElementById('novel-queue-modal-badge');
                    const btnCount = document.getElementById('novel-queue-btn-count');
                    if (badgeCount) badgeCount.textContent = novelDownloadQueue.length;
                    if (modalBadge) modalBadge.textContent = `(共 ${novelDownloadQueue.length} 部)`;
                    if (btnCount) btnCount.textContent = novelDownloadQueue.length;
                    renderNovelQueueModal();
                }).catch(() => {});
        }

        function openNovelQueueModal() {
            syncNovelQueue();
            const modal = document.getElementById('novel-download-queue-modal');
            if (modal) modal.style.display = 'flex';
        }

        function closeNovelQueueModal() {
            const modal = document.getElementById('novel-download-queue-modal');
            if (modal) modal.style.display = 'none';
        }

        function removeNovelFromQueue(id) {
            fetch('/api/novels/queue/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, is_nsfw: isNovelNsfw })
            }).then(() => {
                novelDownloadQueue = novelDownloadQueue.filter(x => String(x.id) !== String(id));
                syncNovelQueue();
                const cardBtn = document.getElementById(`novel-queue-btn-${id}`);
                if (cardBtn) {
                    cardBtn.className = 'manga-btn';
                    cardBtn.textContent = '➕ 加入待下载列表';
                }
            });
        }

        function clearNovelDownloadQueue() {
            fetch('/api/novels/queue/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_nsfw: isNovelNsfw })
            }).then(() => {
                novelDownloadQueue = [];
                syncNovelQueue();
                document.querySelectorAll('#novels-online-grid .manga-btn-in-queue').forEach(btn => {
                    btn.className = 'manga-btn';
                    btn.textContent = '➕ 加入待下载列表';
                });
            });
        }

        function renderNovelQueueModal() {
            const listEl = document.getElementById('novel-queue-items-list');
            const emptyEl = document.getElementById('novel-queue-empty-msg');
            const startBtn = document.getElementById('novel-queue-start-download-btn');
            const clearBtn = document.getElementById('novel-queue-clear-btn');
            if (!listEl) return;

            if (novelDownloadQueue.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                if (startBtn) startBtn.disabled = true;
                if (clearBtn) clearBtn.disabled = true;
                listEl.innerHTML = '';
                return;
            }

            if (emptyEl) emptyEl.style.display = 'none';
            if (startBtn) startBtn.disabled = false;
            if (clearBtn) clearBtn.disabled = false;

            listEl.innerHTML = novelDownloadQueue.map(item => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#161b22;border:1px solid #30363d;border-radius:8px;">
                    <div>
                        <div style="font-size:14px;font-weight:600;color:#f0f6fc;">${escapeHtml(item.title)}</div>
                        <div style="font-size:12px;color:#8b949e;margin-top:2px;">${escapeHtml(item.author || '佚名')}${item.is_nsfw ? ' · 🔞 NSFW' : ''}</div>
                    </div>
                    <button class="manga-mini-btn" title="移出待下载列表" onclick="removeNovelFromQueue('${escapeAttr(item.id)}')">✕</button>
                </div>
            `).join('');
        }

        function startNovelQueueBatchDownload() {
            if (novelDownloadQueue.length === 0) return;
            novelDownloadQueue.forEach(item => {
                fetch('/api/novels/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: item.id,
                        title: item.title,
                        author: item.author,
                        intro: item.intro,
                        cover_url: item.cover_url,
                        is_nsfw: item.is_nsfw !== undefined ? item.is_nsfw : isNovelNsfw
                    })
                });
            });
            closeNovelQueueModal();
            pollNovelTasks();
        }

        // ================= 技术文档 (Docs Explorer - 资源管理器式分层浏览) =================
        let currentDocsSubDir = '';
        let currentDocsExplorerData = null;
        let docSearchTimer = null;

        function loadDocsLibrary(subDir, q) {
            if (subDir === undefined) subDir = currentDocsSubDir;
            if (q === undefined) {
                const searchInput = document.getElementById('doc-search-input');
                q = (searchInput ? searchInput.value : '').trim();
            }

            fetch(`/api/docs/explorer?dir=${encodeURIComponent(subDir)}&q=${encodeURIComponent(q)}&ext=${currentDocFilter}&t=${Date.now()}`)
                .then(r => r.json())
                .then(data => {
                    currentDocsExplorerData = data;
                    currentDocsSubDir = data.current_dir || '';

                    if (activePrimarySection === 'media' && activeMediaTab === 'docs') {
                        const countText = data.is_search ? `${data.total_items} 篇搜索结果` : `${data.total_items} 项 (当前文件夹)`;
                        document.getElementById('total-badge').textContent = countText;
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = `📁 docs/${currentDocsSubDir ? currentDocsSubDir + '/' : ''} · 共 ${data.total_items} 项`;
                    }

                    renderDocsBreadcrumbs(data);
                    renderDocsExplorerGrid(data);
                })
                .catch(err => {
                    console.error('Failed to load docs explorer:', err);
                });
        }

        function navigateDocsDir(targetPath) {
            const searchInput = document.getElementById('doc-search-input');
            if (searchInput) searchInput.value = '';
            currentDocsSubDir = targetPath || '';
            loadDocsLibrary(currentDocsSubDir, '');
        }

        function refreshCurrentDocsDir() {
            loadDocsLibrary(currentDocsSubDir);
        }

        function switchDocFilter(filterExt, btnEl) {
            currentDocFilter = filterExt;
            document.querySelectorAll('#doc-filter-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            if (btnEl) btnEl.classList.add('active');
            loadDocsLibrary(currentDocsSubDir);
        }

        function onDocSearchInput(val) {
            clearTimeout(docSearchTimer);
            docSearchTimer = setTimeout(() => {
                loadDocsLibrary(currentDocsSubDir, val.trim());
            }, 250);
        }

        function renderDocsBreadcrumbs(data) {
            const bar = document.getElementById('docs-breadcrumbs-bar');
            if (!bar) return;

            if (data.is_search) {
                bar.innerHTML = `
                    <span class="docs-crumb-item" onclick="navigateDocsDir('${escapeAttr(data.current_dir)}')">📁 返回当前目录</span>
                    <span class="docs-crumb-sep">/</span>
                    <span class="docs-crumb-item active">🔍 "${escapeHtml(data.q)}" 的搜索结果 (${data.total_items} 篇)</span>
                `;
                return;
            }

            const crumbs = data.breadcrumbs || [{ name: '根目录', path: '' }];
            let html = '';
            crumbs.forEach((c, idx) => {
                const isLast = idx === crumbs.length - 1;
                const icon = idx === 0 ? '🏠' : '📁';
                if (isLast) {
                    html += `<span class="docs-crumb-item active">${icon} ${escapeHtml(c.name || '根目录')}</span>`;
                } else {
                    html += `<span class="docs-crumb-item" onclick="navigateDocsDir('${escapeAttr(c.path)}')">${icon} ${escapeHtml(c.name || '根目录')}</span>`;
                    html += `<span class="docs-crumb-sep">/</span>`;
                }
            });
            bar.innerHTML = html;
        }

        function renderDocsExplorerGrid(data) {
            const grid = document.getElementById('docs-explorer-grid');
            const emptyEl = document.getElementById('docs-shelf-empty');
            if (!grid) return;
            grid.innerHTML = '';

            const folders = data.folders || [];
            const files = data.files || [];

            if (folders.length === 0 && files.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';

            // 1. 如果不在根目录且不是搜索模式，显示“返回上一级”卡片
            if (data.current_dir && !data.is_search) {
                const upCard = document.createElement('div');
                upCard.className = 'docs-folder-card';
                upCard.style.borderColor = '#1f6feb66';
                upCard.onclick = () => navigateDocsDir(data.parent_dir || '');
                upCard.innerHTML = `
                    <div class="docs-folder-icon" style="color:#58a6ff;">⬆️</div>
                    <div class="docs-folder-info">
                        <div class="docs-folder-title" style="color:#58a6ff;">.. (返回上一级目录)</div>
                        <div class="docs-folder-meta">
                            <span>点击返回上层</span>
                        </div>
                    </div>
                `;
                grid.appendChild(upCard);
            }

            // 2. 渲染文件夹列表 (📁)
            folders.forEach(folder => {
                const card = document.createElement('div');
                card.className = 'docs-folder-card';
                card.onclick = () => navigateDocsDir(folder.path);

                card.innerHTML = `
                    <div class="docs-folder-icon">📁</div>
                    <div class="docs-folder-info">
                        <div class="docs-folder-title" title="${escapeAttr(folder.name)}">${escapeHtml(folder.name)}</div>
                        <div class="docs-folder-meta">
                            <span style="color:#58a6ff;background:#1f6feb22;padding:1px 6px;border-radius:4px;font-size:11px;">${folder.items_count} 项</span>
                            <span>${folder.mtime}</span>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });

            // 3. 渲染文档文件列表 (📄)
            files.forEach(file => {
                const card = document.createElement('div');
                card.className = 'docs-file-card';
                card.onclick = () => openNovelReader(file.rel_path);

                const ext = (file.ext || '').toLowerCase();
                const extClass = ext === 'rst' ? 'novel-badge-rst' : (ext === 'md' ? 'novel-badge-md' : 'novel-badge-txt');
                const pathHint = (data.is_search && file.dir_rel) ? `<div class="docs-file-path-hint" title="${escapeAttr(file.dir_rel)}">📂 ${escapeHtml(file.dir_rel)}</div>` : '';

                card.innerHTML = `
                    <div>
                        <div class="docs-file-top">
                            <span class="novel-badge ${extClass}">${ext.toUpperCase()}</span>
                            <button class="manga-mini-btn" title="移至回收站" onclick="event.stopPropagation(); deleteDocFile('${escapeAttr(file.rel_path)}')">🗑️</button>
                        </div>
                        <div class="docs-file-title" title="${escapeAttr(file.title)}">${escapeHtml(file.title)}</div>
                        ${pathHint}
                    </div>
                    <div class="docs-file-meta">
                        <span>${file.size_kb} KB</span>
                        <span>${file.mtime}</span>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function deleteDocFile(relPath) {
            if (!confirm(`确定将技术文档《${relPath}》移至回收站吗？`)) return;
            fetch('/api/novels/trash', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: relPath })
            }).then(r => r.json()).then(() => {
                loadDocsLibrary();
            });
        }

        // ================= 全能文本阅读器 (EPUB / TXT / MD / RST) =================
        let currentNovelPath = '';
        let currentNovelData = null;
        let currentNovelChapters = [];
        let currentChapterIndex = 0;
        let currentFontSize = 17;
        const NOVEL_THEMES = ['novel-theme-dark', 'novel-theme-sepia', 'novel-theme-eye', 'novel-theme-light'];
        const NOVEL_THEME_NAMES = ['🌙 暗夜', '📜 羊皮纸', '🍃 护眼', '☀️ 明亮'];
        let currentThemeIdx = 0;

        function openNovelReader(relPath) {
            currentNovelPath = relPath;
            const modal = document.getElementById('novel-reader-modal');
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            document.documentElement.style.overflow = 'hidden';

            const titleEl = document.getElementById('novel-reader-title');
            const extBadge = document.getElementById('novel-reader-ext-badge');
            const metaEl = document.getElementById('novel-reader-meta');
            const viewEl = document.getElementById('novel-content-view');
            const drawer = document.getElementById('novel-chapter-drawer');
            const chBtn = document.getElementById('novel-chapter-btn');

            titleEl.textContent = relPath.split('/').pop().replace(/\.[^/.]+$/, '');
            viewEl.innerHTML = '<div style="text-align:center;padding:50px;color:#8b949e;">📖 正在加载并排版回目...</div>';

            fetch('/api/novels/read?path=' + encodeURIComponent(relPath))
                .then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText || '文件未找到'}`);
                    return r.json();
                })
                .then(data => {
                    if (!data) throw new Error('返回文档数据为空');
                    currentNovelData = data;
                    currentNovelChapters = data.chapters || [];
                    const ext = (data.ext || '').toLowerCase();
                    extBadge.textContent = ext.toUpperCase();
                    extBadge.className = 'novel-badge ' + (ext === 'txt' ? 'novel-badge-txt' : (ext === 'md' ? 'novel-badge-md' : (ext === 'epub' ? 'novel-badge-txt' : 'novel-badge-rst')));
                    metaEl.textContent = `${data.char_count || 0} 字 · ${data.size_kb} KB`;

                    if (data.siblings && data.siblings.length > 1) {
                        // 1. 技术文档同目录下多章节自然分页
                        chBtn.style.display = 'inline-flex';
                        renderDocSiblingsList(data.siblings, data.sibling_index);
                        metaEl.textContent = `第 ${data.sibling_index + 1} / ${data.siblings.length} 篇 · ${data.char_count || 0} 字 · ${data.size_kb} KB`;

                        const isFirst = data.sibling_index === 0;
                        const isLast = data.sibling_index >= data.siblings.length - 1;
                        const prevRel = data.prev_sibling ? data.prev_sibling.rel_path : '';
                        const nextRel = data.next_sibling ? data.next_sibling.rel_path : '';

                        const bottomNavHtml = `
                            <div class="novel-chapter-bottom-nav">
                                <button class="reader-tool-btn novel-nav-btn" onclick="openNovelReader('${escapeAttr(prevRel)}')" ${isFirst ? 'disabled style="opacity:0.35;pointer-events:none;"' : ''}>◀ 上一篇</button>
                                <button class="reader-tool-btn novel-nav-btn" onclick="toggleChapterDrawer()" style="color:#58a6ff;font-weight:700;">📑 目录 (${data.sibling_index + 1} / ${data.siblings.length} 篇)</button>
                                <button class="reader-tool-btn novel-nav-btn" onclick="openNovelReader('${escapeAttr(nextRel)}')" ${isLast ? 'disabled style="opacity:0.35;pointer-events:none;"' : ''}>下一篇 ▶</button>
                            </div>
                        `;

                        let docBodyHtml = '';
                        try {
                            docBodyHtml = ext === 'rst' 
                                ? `<div class="doc-markdown-body doc-rst-body">${data.html || parseRstToHtml(data.raw || '')}</div>`
                                : `<div class="doc-markdown-body">${parseMarkdownToHtml(data.raw || '')}</div>`;
                        } catch (pErr) {
                            console.error('Doc parse error:', pErr);
                            docBodyHtml = `<div class="doc-markdown-body"><pre>${escapeHtml(data.raw || '')}</pre></div>`;
                        }

                        viewEl.innerHTML = `
                            ${docBodyHtml}
                            ${bottomNavHtml}
                        `;
                        try {
                            enhanceDocContent(viewEl);
                            renderMermaidDiagrams(viewEl);
                        } catch (enhErr) {
                            console.warn('Doc enhance warning:', enhErr);
                        }
                        const scrollBox = document.getElementById('novel-content-scroll');
                        if (scrollBox) scrollBox.scrollTop = 0;
                    } else if (currentNovelChapters.length > 1) {
                        // 2. 小说多回目
                        chBtn.style.display = 'inline-flex';
                        renderNovelChaptersList(currentNovelChapters);

                        // 恢复历史阅读章节
                        let savedCh = parseInt(localStorage.getItem('omni_novel_ch_' + relPath), 10);
                        if (isNaN(savedCh) || savedCh < 0 || savedCh >= currentNovelChapters.length) {
                            savedCh = (currentNovelChapters.length > 1 && (currentNovelChapters[0].title.includes('封面') || currentNovelChapters[0].title.includes('简介'))) ? 1 : 0;
                        }
                        goToNovelChapter(savedCh);
                    } else {
                        // 3. 独立单篇文档
                        chBtn.style.display = 'none';
                        drawer.style.display = 'none';
                        currentChapterIndex = 0;
                        if (ext === 'epub') {
                            viewEl.innerHTML = data.html || (currentNovelChapters[0] ? currentNovelChapters[0].html : '<p style="color:#8b949e;">(空电子书)</p>');
                        } else if (ext === 'rst') {
                            try {
                                viewEl.innerHTML = `<div class="doc-markdown-body doc-rst-body">${data.html || parseRstToHtml(data.raw || '')}</div>`;
                                enhanceDocContent(viewEl);
                                renderMermaidDiagrams(viewEl);
                            } catch(e) {
                                viewEl.innerHTML = `<div class="doc-markdown-body"><pre>${escapeHtml(data.raw || '')}</pre></div>`;
                            }
                        } else if (ext === 'md' || ext === 'markdown') {
                            try {
                                viewEl.innerHTML = `<div class="doc-markdown-body">${parseMarkdownToHtml(data.raw || '')}</div>`;
                                enhanceDocContent(viewEl);
                                renderMermaidDiagrams(viewEl);
                            } catch(e) {
                                viewEl.innerHTML = `<div class="doc-markdown-body"><pre>${escapeHtml(data.raw || '')}</pre></div>`;
                            }
                        } else {
                            renderTxtContent(data.raw || '');
                        }
                    }
                })
                .catch(err => {
                    viewEl.innerHTML = `<div style="color:#f85149;padding:40px;">读取失败: ${err}</div>`;
                });
        }

        function renderDocSiblingsList(siblings, activeIdx) {
            const listEl = document.getElementById('novel-chapter-list');
            document.getElementById('novel-chapter-count').textContent = siblings.length;
            listEl.innerHTML = '';
            siblings.forEach((s, idx) => {
                const item = document.createElement('div');
                item.className = 'novel-chapter-item' + (idx === activeIdx ? ' active' : '');
                item.id = `novel-ch-drawer-item-${idx}`;
                item.textContent = `${idx + 1}. ${s.title}`;
                item.onclick = () => {
                    openNovelReader(s.rel_path);
                    toggleChapterDrawer();
                };
                listEl.appendChild(item);
            });
        }

        function closeNovelReader() {
            document.getElementById('novel-reader-modal').style.display = 'none';
            document.getElementById('novel-content-view').innerHTML = '';
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }

        function toggleChapterDrawer() {
            const drawer = document.getElementById('novel-chapter-drawer');
            drawer.style.display = drawer.style.display === 'none' ? 'flex' : 'none';
            if (drawer.style.display === 'flex') {
                const activeItem = drawer.querySelector('.novel-chapter-item.active');
                if (activeItem) {
                    activeItem.scrollIntoView({ block: 'center', behavior: 'smooth' });
                }
            }
        }

        function renderNovelChaptersList(chapters) {
            const listEl = document.getElementById('novel-chapter-list');
            document.getElementById('novel-chapter-count').textContent = chapters.length;
            listEl.innerHTML = '';
            chapters.forEach((ch, idx) => {
                const item = document.createElement('div');
                item.className = 'novel-chapter-item' + (idx === currentChapterIndex ? ' active' : '');
                item.id = `novel-ch-drawer-item-${idx}`;
                item.textContent = ch.title;
                item.onclick = () => {
                    goToNovelChapter(idx);
                    toggleChapterDrawer();
                };
                listEl.appendChild(item);
            });
        }

        function goToNovelChapter(newIdx) {
            if (!currentNovelChapters || currentNovelChapters.length === 0) return;
            if (newIdx < 0) newIdx = 0;
            if (newIdx >= currentNovelChapters.length) newIdx = currentNovelChapters.length - 1;

            currentChapterIndex = newIdx;
            localStorage.setItem('omni_novel_ch_' + currentNovelPath, newIdx);

            const ch = currentNovelChapters[newIdx];
            const metaEl = document.getElementById('novel-reader-meta');
            metaEl.textContent = `第 ${newIdx + 1} / ${currentNovelChapters.length} 回 · ${ch.char_count || 0} 字 · ${currentNovelData ? currentNovelData.size_kb : 0} KB`;

            const viewEl = document.getElementById('novel-content-view');
            const total = currentNovelChapters.length;

            const isFirst = newIdx === 0;
            const isLast = newIdx >= total - 1;

            const bottomNavHtml = `
                <div class="novel-chapter-bottom-nav">
                    <button class="reader-tool-btn novel-nav-btn" onclick="goToNovelChapter(${newIdx - 1})" ${isFirst ? 'disabled style="opacity:0.35;pointer-events:none;"' : ''}>◀ 上一回</button>
                    <button class="reader-tool-btn novel-nav-btn" onclick="toggleChapterDrawer()" style="color:#58a6ff;font-weight:700;">📑 目录 (${newIdx + 1} / ${total} 回)</button>
                    <button class="reader-tool-btn novel-nav-btn" onclick="goToNovelChapter(${newIdx + 1})" ${isLast ? 'disabled style="opacity:0.35;pointer-events:none;"' : ''}>下一回 ▶</button>
                </div>
            `;

            viewEl.innerHTML = `
                <div class="novel-current-chapter-body">
                    ${ch.html}
                </div>
                ${bottomNavHtml}
            `;
            renderMermaidDiagrams(viewEl);

            // 回到顶部
            const scrollBox = document.getElementById('novel-content-scroll');
            if (scrollBox) scrollBox.scrollTop = 0;

            // 更新目录高亮
            document.querySelectorAll('.novel-chapter-item').forEach((item, idx) => {
                if (idx === newIdx) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });
        }

        function renderTxtContent(rawText) {
            const viewEl = document.getElementById('novel-content-view');
            const lines = rawText.split('\n');
            let html = '';
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed) continue;
                if (/^(?:第\s*[0-9一二三四五六七八九十百千万]+\s*[章回节卷集部篇]|Chapter\s+[0-9]+)/i.test(trimmed)) {
                    html += `<h2 class="txt-chapter-anchor" style="color:#58a6ff;margin-top:2em;margin-bottom:0.8em;padding-bottom:6px;border-bottom:1px solid rgba(88,166,255,0.25);">${escapeHtml(trimmed)}</h2>`;
                } else {
                    html += `<p>${escapeHtml(trimmed)}</p>`;
                }
            }
            viewEl.innerHTML = html || '<p style="color:#8b949e;">(空文档)</p>';
        }

        // ================= Markdown 与 Mermaid 图表引擎 =================
        function initMarkdownAndMermaidEngines() {
            if (window.mermaid) {
                try {
                    window.mermaid.initialize({
                        startOnLoad: false,
                        theme: 'dark',
                        securityLevel: 'loose',
                        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                    });
                } catch(e) {
                    console.warn('Mermaid init warning:', e);
                }
            }
        }
        initMarkdownAndMermaidEngines();

        function renderLatexMath(text) {
            if (!text) return text;
            if (!window.katex) return text;
            try {
                // 1. 独立块公式 $$ ... $$ 或 \[ ... \]
                text = text.replace(/(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\])/g, function(match, m1, m2) {
                    let formula = (m1 || m2 || '').trim();
                    try {
                        return `<div class="katex-display">${katex.renderToString(formula, { displayMode: true, throwOnError: false })}</div>`;
                    } catch(e) {
                        return match;
                    }
                });
                // 2. 行内公式 $ ... $ 或 \( ... \) (排查货币或转义符号)
                text = text.replace(/(?:(?<!\\)\$([^\$\n\r]+?)(?<!\\)\$|\\\(([\s\S]+?)\\\))/g, function(match, m1, m2) {
                    let formula = (m1 || m2 || '').trim();
                    if (!formula || formula.length < 1) return match;
                    try {
                        return katex.renderToString(formula, { displayMode: false, throwOnError: false });
                    } catch(e) {
                        return match;
                    }
                });
            } catch(e) {}
            return text;
        }

        function isAsciiDiagram(text) {
            if (!text) return false;
            const lines = text.trim().split('\n');
            if (lines.length < 2) return false;
            
            // 匹配边框角 +---+ 或 | ... | 或 箭头 ---> / <--- 或 Unicode 框线
            const boxCorners = (text.match(/\+[-=]+\+/g) || []).length;
            const pipes = (text.match(/\|/g) || []).length;
            const arrows = (text.match(/[-=]+>|<[-=]+|[▼▲◄►]/g) || []).length;
            const unicodeBoxes = (text.match(/[┌┐└┘├┤┬┴┼│─═║╔╗╚╝]/g) || []).length;
            
            const score = boxCorners * 3 + arrows * 2 + unicodeBoxes * 2 + (pipes >= 4 ? 4 : 0);
            return score >= 6;
        }

        function renderAsciiToSvg(text) {
            if (!text) return '';
            const lines = text.replace(/\r\n/g, '\n').split('\n');
            let maxCols = 0;
            lines.forEach(l => { if (l.length > maxCols) maxCols = l.length; });
            if (maxCols === 0 || lines.length === 0) return '';
            
            const charW = 10;
            const charH = 20;
            const padX = 20;
            const padY = 25;
            
            const svgW = Math.max(maxCols * charW + padX * 2, 400);
            const svgH = lines.length * charH + padY * 2;
            
            const grid = lines.map(l => l.padEnd(maxCols, ' ').split(''));
            let svgBody = '';
            
            for (let r = 0; r < grid.length; r++) {
                const row = grid[r];
                let c = 0;
                while (c < row.length) {
                    const startLoopC = c;
                    let ch = row[c];
                    if (ch === ' ') {
                        c++;
                        continue;
                    }
                    
                    // 1. 水平箭头 ----> / ---> / -->
                    if (c + 3 < row.length && row.slice(c, c+4).join('') === '---->') {
                        let x1 = padX + c * charW;
                        let x2 = padX + (c + 4) * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 4;
                        continue;
                    }
                    if (c + 2 < row.length && row.slice(c, c+3).join('') === '--->') {
                        let x1 = padX + c * charW;
                        let x2 = padX + (c + 3) * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 3;
                        continue;
                    }
                    if (c + 1 < row.length && row.slice(c, c+2).join('') === '-->') {
                        let x1 = padX + c * charW;
                        let x2 = padX + (c + 2) * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 2;
                        continue;
                    }
                    
                    // 2. 反向水平箭头 <---- / <--- / <--
                    if (c + 3 < row.length && row.slice(c, c+4).join('') === '<----') {
                        let x1 = padX + (c + 4) * charW;
                        let x2 = padX + c * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 4;
                        continue;
                    }
                    if (c + 2 < row.length && row.slice(c, c+3).join('') === '<---') {
                        let x1 = padX + (c + 3) * charW;
                        let x2 = padX + c * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 3;
                        continue;
                    }
                    if (c + 1 < row.length && row.slice(c, c+2).join('') === '<--') {
                        let x1 = padX + (c + 2) * charW;
                        let x2 = padX + c * charW;
                        let cy = padY + r * charH + 10;
                        svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green)" />`;
                        c += 2;
                        continue;
                    }
                    
                    // 3. 垂直向下箭头 (v, ▼)
                    if ((ch === 'v' || ch === '▼') && r > 0 && (grid[r-1][c] === '|' || grid[r-1][c] === '│')) {
                        let cx = padX + c * charW + 5;
                        let y1 = padY + (r - 1) * charH + 10;
                        let y2 = padY + r * charH + 14;
                        svgBody += `<line x1="${cx}" y1="${y1}" x2="${cx}" y2="${y2}" stroke="#3fb950" stroke-width="2.5" marker-end="url(#arrow-green-down)" />`;
                        c++;
                        continue;
                    }
                    
                    // 4. 矩形水平边框 (+-------+)
                    if (ch === '+' && c + 1 < row.length && (row[c+1] === '-' || row[c+1] === '=')) {
                        let c2 = c + 1;
                        while (c2 < row.length && (row[c2] === '-' || row[c2] === '=')) c2++;
                        if (c2 < row.length && row[c2] === '+') {
                            let x1 = padX + c * charW + 5;
                            let x2 = padX + c2 * charW + 5;
                            let cy = padY + r * charH + 10;
                            svgBody += `<line x1="${x1}" y1="${cy}" x2="${x2}" y2="${cy}" stroke="#58a6ff" stroke-width="2.5" />`;
                            svgBody += `<circle cx="${x1}" cy="${cy}" r="3.5" fill="#58a6ff" />`;
                            svgBody += `<circle cx="${x2}" cy="${cy}" r="3.5" fill="#58a6ff" />`;
                            c = c2 + 1;
                            continue;
                        }
                    }
                    
                    // 5. 垂直竖线 (|)
                    if (ch === '|' || ch === '│') {
                        let cx = padX + c * charW + 5;
                        let y1 = padY + r * charH;
                        let y2 = padY + (r + 1) * charH;
                        svgBody += `<line x1="${cx}" y1="${y1}" x2="${cx}" y2="${y2}" stroke="#58a6ff" stroke-width="2.5" />`;
                        c++;
                        continue;
                    }
                    
                    // 6. 提取普通文本
                    let textChars = [];
                    let startTextC = c;
                    while (c < row.length) {
                        if (row[c] === '|' || row[c] === '│') break;
                        if (row[c] === '+' && c + 1 < row.length && (row[c+1] === '-' || row[c+1] === '=')) break;
                        if (row.slice(c, c+2).join('') === '->' || row.slice(c, c+2).join('') === '<-') break;
                        textChars.push(row[c]);
                        c++;
                    }
                    let word = textChars.join('').trim();
                    if (word) {
                        let tx = padX + startTextC * charW;
                        let ty = padY + r * charH + 14;
                        let isAnnotation = word.startsWith('(') || word.endsWith(')');
                        let fillColor = isAnnotation ? '#8b949e' : '#f0f6fc';
                        let fontWeight = isAnnotation ? 'normal' : '700';
                        let fontStyle = isAnnotation ? 'italic' : 'normal';
                        svgBody += `<text x="${tx}" y="${ty}" fill="${fillColor}" font-size="13.5" font-family="'JetBrains Mono', monospace" font-weight="${fontWeight}" font-style="${fontStyle}">${escapeHtml(word)}</text>`;
                    }
                    
                    if (c <= startLoopC) {
                        c = startLoopC + 1;
                    }
                }
            }
            
            return `<div class="doc-diagram-svg-container" style="padding:16px;overflow-x:auto;display:flex;justify-content:center;">
  <svg class="doc-ascii-diagram-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${svgW} ${svgH}" width="100%" style="max-width:${svgW}px;display:block;background:#090d13;border-radius:10px;border:1px solid rgba(56,139,253,0.3);box-shadow:0 8px 30px rgba(0,0,0,0.5);">
    <defs>
      <marker id="arrow-green" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#3fb950" />
      </marker>
      <marker id="arrow-green-down" viewBox="0 0 10 10" refX="5" refY="6" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M 1.5 0 L 5 8 L 8.5 0 z" fill="#3fb950" />
      </marker>
    </defs>
    <rect width="100%" height="100%" fill="#090d13" rx="10" />
    ${svgBody}
  </svg>
</div>`;
        }

        function colorizeAsciiDiagram(rawText) {
            let escaped = escapeHtml(rawText);
            // 边框字符与角高亮 (幽蓝)
            escaped = escaped.replace(/(\+[-=]+\+|\+[-=]+|[-=]+\+|\+|\||─|│|┌|┐|└|┘|├|┤|┬|┴|┼|═|║|╔|╗|╚|╝)/g, '<span class="doc-diagram-box">$1</span>');
            // 箭头高亮 (翠绿)
            escaped = escaped.replace(/([-=]+&gt;|&lt;[-=]+|&gt;|&lt;|[-=]+&gt;&gt;|&lt;&lt;[-=]+|[▼▲◄►^v])/g, '<span class="doc-diagram-arrow">$1</span>');
            return escaped;
        }

        function toggleDiagramView(btn) {
            if (!btn) return;
            const card = btn.closest('.doc-diagram-card');
            if (!card) return;
            const svgView = card.querySelector('.doc-diagram-svg-view');
            const codeView = card.querySelector('.doc-diagram-code-view');
            if (svgView && codeView) {
                if (svgView.style.display === 'none') {
                    svgView.style.display = 'block';
                    codeView.style.display = 'none';
                    btn.textContent = '📄 查看源码';
                } else {
                    svgView.style.display = 'none';
                    codeView.style.display = 'block';
                    btn.textContent = '🎨 切换为矢量图';
                }
            }
        }

        function parseRstToHtml(rst) {
            if (!rst) return '';
            const lines = rst.replace(/\r\n/g, '\n').split('\n');
            let html = [];
            let i = 0;

            function parseRstInline(text) {
                if (!text) return '';
                const mathTokens = [];
                // 1. 提取 :math:`...` 公式并生成占位符
                let s = text.replace(/:math:`([^`]+)`/g, function(match, mathCode) {
                    const token = '___KATEX_PH_' + mathTokens.length + '___';
                    let rendered = '';
                    if (window.katex) {
                        try {
                            rendered = katex.renderToString(mathCode.trim(), { displayMode: false, throwOnError: false });
                        } catch(e) {
                            rendered = `<code>${escapeHtml(mathCode)}</code>`;
                        }
                    } else {
                        rendered = `<code>${escapeHtml(mathCode)}</code>`;
                    }
                    mathTokens.push({ token: token, html: rendered });
                    return token;
                });

                // 2. 基础转义与行内语法
                s = escapeHtml(s);
                // 行内代码 ``code``
                s = s.replace(/``([^`]+)``/g, '<code>$1</code>');
                // 加粗 **bold**
                s = s.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
                // 斜体 *italic*
                s = s.replace(/\*([^\*]+)\*/g, '<em>$1</em>');
                // 链接 `text <url>`_
                s = s.replace(/`([^`]+)\s+&lt;([^&>]+)&gt;`_/g, '<a href="$2" target="_blank" onclick="handleExternalLinkClick(event, \'$2\')" class="doc-markdown-link">$1 ↗</a>');
                // 内部文档链接 `text <doc.md>`_
                s = s.replace(/`([^`]+)\s+&lt;(\.\/[^&>]+|\.\.\/[^&>]+|[^&>:]+\.(?:md|rst|markdown))&gt;`_/g, '<a href="javascript:void(0)" onclick="openInternalDocLink(\'$2\')" class="doc-markdown-link doc-internal-link">📄 $1</a>');
                // 简单链接 `url`_
                s = s.replace(/`([^`]+)`_/g, '<a href="$1" target="_blank" onclick="handleExternalLinkClick(event, \'$1\')" class="doc-markdown-link">$1 ↗</a>');

                // 3. 还原完整 KaTeX HTML (使用 split().join() 防止 LaTeX 内部符号被当成正则替换模式)
                mathTokens.forEach(item => {
                    s = s.split(item.token).join(item.html);
                });
                return s;
            }

            while (i < lines.length) {
                let line = lines[i];
                let trimmed = line.trim();

                if (!trimmed) {
                    i++;
                    continue;
                }

                // 1. 检查双线主标题 (Overline + Title + Underline)
                if (i + 2 < lines.length && /^[=\-~^]{3,}$/.test(trimmed) && /^[=\-~^]{3,}$/.test(lines[i+2].trim()) && trimmed[0] === lines[i+2].trim()[0]) {
                    let titleText = lines[i+1].trim();
                    let char = trimmed[0];
                    let tag = char === '=' ? 'h1' : 'h2';
                    html.push(`<${tag}>${parseRstInline(titleText)}</${tag}>`);
                    i += 3;
                    continue;
                }

                // 2. 检查单线下划线标题 (Title + Underline)
                if (i + 1 < lines.length && /^[=\-~^`#"']{3,}$/.test(lines[i+1].trim())) {
                    let underChar = lines[i+1].trim()[0];
                    let tag = underChar === '=' ? 'h2' : (underChar === '-' ? 'h3' : 'h4');
                    html.push(`<${tag}>${parseRstInline(trimmed)}</${tag}>`);
                    i += 2;
                    continue;
                }

                // 3. 检查指令: .. list-table::
                let matchTable = trimmed.match(/^\.\.\s+list-table::\s*(.*)$/i);
                if (matchTable) {
                    let tableCaption = matchTable[1].trim();
                    i++;
                    let tableLines = [];
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        if (lines[i].trim()) tableLines.push(lines[i].trim());
                        i++;
                    }

                    let rows = [];
                    let curRow = null;
                    let curCol = [];

                    for (let tl of tableLines) {
                        if (tl.startsWith(':widths:') || tl.startsWith(':header-rows:') || tl.startsWith(':align:')) {
                            continue;
                        }
                        if (tl.startsWith('* -')) {
                            if (curRow) {
                                if (curCol.length) curRow.push(curCol.join(' '));
                                rows.push(curRow);
                            }
                            curRow = [];
                            curCol = [tl.substring(3).trim()];
                        } else if (tl.startsWith('- ')) {
                            if (curCol.length && curRow) curRow.push(curCol.join(' '));
                            curCol = [tl.substring(2).trim()];
                        } else {
                            curCol.push(tl);
                        }
                    }
                    if (curRow) {
                        if (curCol.length) curRow.push(curCol.join(' '));
                        rows.push(curRow);
                    }

                    let tableHtml = '<table class="docutils">';
                    if (tableCaption) tableHtml += `<caption>${parseRstInline(tableCaption)}</caption>`;
                    if (rows.length > 0) {
                        tableHtml += '<thead><tr>';
                        for (let cell of rows[0]) {
                            tableHtml += `<th>${parseRstInline(cell)}</th>`;
                        }
                        tableHtml += '</tr></thead><tbody>';
                        for (let rIdx = 1; rIdx < rows.length; rIdx++) {
                            tableHtml += '<tr>';
                            for (let cell of rows[rIdx]) {
                                tableHtml += `<td>${parseRstInline(cell)}</td>`;
                            }
                            tableHtml += '</tr>';
                        }
                        tableHtml += '</tbody>';
                    }
                    tableHtml += '</table>';
                    html.push(tableHtml);
                    continue;
                }

                // 4. 检查指令: .. mermaid:: 或 .. code-block:: mermaid
                let matchMermaid = trimmed.match(/^\.\.\s+(?:mermaid|code-block::\s*mermaid|code::\s*mermaid)/i);
                if (matchMermaid) {
                    i++;
                    let mermaidLines = [];
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        mermaidLines.push(lines[i].replace(/^ {3}/, '').replace(/^\t/, ''));
                        i++;
                    }
                    let mCode = mermaidLines.join('\n').trim();
                    const uniqueId = 'mermaid-' + Math.random().toString(36).substring(2, 9);
                    html.push(`<div class="mermaid-block-wrapper"><div class="mermaid" id="${uniqueId}">${mCode}</div></div>`);
                    continue;
                }

                // 5. 检查指令: .. math:: (LaTeX 数学公式块)
                let matchMath = trimmed.match(/^\.\.\s+math::/i);
                if (matchMath) {
                    i++;
                    let mathLines = [];
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        mathLines.push(lines[i].trim());
                        i++;
                    }
                    let mathCode = mathLines.join('\n').trim();
                    if (window.katex) {
                        try {
                            html.push(`<div class="katex-display">${katex.renderToString(mathCode, { displayMode: true, throwOnError: false })}</div>`);
                            continue;
                        } catch(e) {}
                    }
                    html.push(`<pre class="doc-math-fallback"><code>${escapeHtml(mathCode)}</code></pre>`);
                    continue;
                }

                // 6. 检查指令: .. code-block:: / .. code::
                let matchCode = trimmed.match(/^\.\.\s+(?:code-block|code|sourcecode)::\s*([a-zA-Z0-9_-]*)$/i);
                if (matchCode) {
                    let lang = matchCode[1].trim() || 'text';
                    i++;
                    let codeLines = [];
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        codeLines.push(lines[i].replace(/^ {3}/, '').replace(/^\t/, ''));
                        i++;
                    }
                    let codeText = codeLines.join('\n').trim();
                    html.push(`<pre><code class="lang-${lang}">${escapeHtml(codeText)}</code></pre>`);
                    continue;
                }

                // 7. 检查指令: .. note:: / .. warning:: / .. tip:: / .. important:: / .. danger::
                let matchAdmonition = trimmed.match(/^\.\.\s+(note|warning|tip|important|danger|caution|attention)::\s*(.*)$/i);
                if (matchAdmonition) {
                    let type = matchAdmonition[1].toLowerCase();
                    let title = matchAdmonition[2].trim() || (type.toUpperCase());
                    i++;
                    let admLines = [];
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        admLines.push(lines[i].trim());
                        i++;
                    }
                    let bodyText = parseRstInline(admLines.filter(x => x).join(' '));
                    html.push(`<div class="admonition ${type}"><p class="admonition-title">${title}</p><p>${bodyText}</p></div>`);
                    continue;
                }

                // 8. 检查指令: .. image:: / .. figure::
                let matchImg = trimmed.match(/^\.\.\s+(?:image|figure)::\s*(.+)$/i);
                if (matchImg) {
                    let imgSrc = matchImg[1].trim();
                    i++;
                    let caption = '';
                    let alt = '';
                    while (i < lines.length && (lines[i].startsWith('   ') || lines[i].startsWith('\t') || !lines[i].trim())) {
                        let l = lines[i].trim();
                        if (l.startsWith(':alt:')) alt = l.substring(5).trim();
                        else if (l.startsWith(':caption:')) caption = l.substring(9).trim();
                        else if (l && !l.startsWith(':')) caption = l;
                        i++;
                    }
                    html.push(`<img src="${escapeAttr(imgSrc)}" alt="${escapeAttr(alt || caption)}" title="${escapeAttr(caption || alt)}">`);
                    continue;
                }

                // 9. 无序列表 (*, -, +)
                if (/^[\*\-\+]\s+/.test(trimmed)) {
                    let listItems = [];
                    while (i < lines.length && /^[\*\-\+]\s+/.test(lines[i].trim())) {
                        listItems.push(lines[i].trim().replace(/^[\*\-\+]\s+/, ''));
                        i++;
                    }
                    let listHtml = '<ul>' + listItems.map(item => `<li>${parseRstInline(item)}</li>`).join('') + '</ul>';
                    html.push(listHtml);
                    continue;
                }

                // 10. 有序列表 (1., 2.)
                if (/^\d+\.\s+/.test(trimmed)) {
                    let listItems = [];
                    while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
                        listItems.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
                        i++;
                    }
                    let listHtml = '<ol>' + listItems.map(item => `<li>${parseRstInline(item)}</li>`).join('') + '</ol>';
                    html.push(listHtml);
                    continue;
                }

                // 11. 普通段落
                let paraLines = [trimmed];
                i++;
                while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith('..') && !/^[=\-~^]{3,}$/.test(lines[i].trim()) && !/^[\*\-\+]\s+/.test(lines[i].trim()) && !/^\d+\.\s+/.test(lines[i].trim())) {
                    paraLines.push(lines[i].trim());
                    i++;
                }
                html.push(`<p>${parseRstInline(paraLines.join(' '))}</p>`);
            }

            return html.join('\n');
        }

        function parseMarkdownToHtml(md) {
            if (!md) return '';
            
            // 预处理 LaTeX 数学公式
            md = renderLatexMath(md);

            if (window.marked && typeof window.marked.parse === 'function') {
                try {
                    const renderer = new marked.Renderer();

                    // 自定义超链接渲染 (外部链接调用原生浏览器打开，相对内部文档链接支持无缝在阅读器内跳转)
                    const origLink = renderer.link.bind(renderer);
                    renderer.link = function(href, title, text) {
                        if (typeof href === 'object') {
                            title = href.title;
                            text = href.text;
                            href = href.href;
                        }
                        href = href || '';
                        const isInternalDoc = href.endsWith('.md') || href.endsWith('.rst') || href.endsWith('.markdown') || href.startsWith('./') || href.startsWith('../');
                        const titleAttr = title ? ` title="${escapeAttr(title)}"` : '';
                        if (isInternalDoc && !href.startsWith('http://') && !href.startsWith('https://')) {
                            return `<a href="javascript:void(0)" onclick="openInternalDocLink('${escapeAttr(href)}')" class="doc-markdown-link doc-internal-link"${titleAttr}>📄 ${text}</a>`;
                        }
                        return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer" onclick="handleExternalLinkClick(event, '${escapeAttr(href)}')" class="doc-markdown-link doc-external-link"${titleAttr}>${text} ↗</a>`;
                    };

                    // 自定义代码块渲染 (自动识别并隔离 mermaid 流程图、架构图、时序图)
                    const origCode = renderer.code.bind(renderer);
                    renderer.code = function(code, lang, isEscaped) {
                        if (typeof code === 'object') {
                            lang = code.lang;
                            code = code.text;
                        }
                        const cleanLang = (lang || '').trim().toLowerCase();
                        if (cleanLang === 'mermaid') {
                            const uniqueId = 'mermaid-' + Math.random().toString(36).substring(2, 9);
                            return `<div class="mermaid-block-wrapper"><div class="mermaid" id="${uniqueId}">${code}</div></div>`;
                        }
                        return origCode(code, lang, isEscaped);
                    };

                    return marked.parse(md, { renderer: renderer, gfm: true, breaks: true });
                } catch (e) {
                    console.error('Marked parsing error, fallback to regex:', e);
                }
            }
            return fallbackParseMarkdown(md);
        }

        function handleExternalLinkClick(e, url) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            if (!url) return;
            // 优先通过后端调起系统默认外部浏览器 (Chrome / Firefox 等)，防止内部跳转冲掉应用主界面
            fetch('/api/open_external_url?url=' + encodeURIComponent(url)).catch(() => {});
            // 针对远程浏览器访问 (局域网/手机等)，在新标签页打开
            try {
                window.open(url, '_blank', 'noopener,noreferrer');
            } catch(err) {}
        }

        function renderMarkdownDoc(rawMd, containerEl) {
            containerEl.innerHTML = `<div class="doc-markdown-body">${parseMarkdownToHtml(rawMd)}</div>`;
            enhanceDocContent(containerEl);
            renderMermaidDiagrams(containerEl);
        }

        function highlightCodeSyntax(codeText, lang) {
            if (!codeText) return '';
            let escaped = escapeHtml(codeText);
            
            // 字符串高亮
            escaped = escaped.replace(/(&quot;[\s\S]*?&quot;|&#39;[\s\S]*?&#39;|&apos;[\s\S]*?&apos;|`[\s\S]*?`|"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')/g, '<span class="token-string">$1</span>');
            // 注释高亮 (支持 #, //, /* ... */)
            escaped = escaped.replace(/((?:#|\/\/)[^\n]*|\/\*[\s\S]*?\*\/)/g, '<span class="token-comment">$1</span>');
            // 常用编程语言关键字高亮
            const keywords = ['def', 'class', 'import', 'from', 'as', 'return', 'if', 'elif', 'else', 'for', 'while', 'in', 'is', 'not', 'and', 'or', 'try', 'except', 'finally', 'with', 'lambda', 'yield', 'async', 'await', 'fn', 'let', 'mut', 'pub', 'struct', 'enum', 'impl', 'use', 'mod', 'match', 'const', 'var', 'function', 'export', 'default', 'null', 'None', 'True', 'False', 'true', 'false'];
            const kwRegex = new RegExp(`\\b(${keywords.join('|')})\\b`, 'g');
            escaped = escaped.replace(kwRegex, '<span class="token-keyword">$1</span>');
            // 数字高亮
            escaped = escaped.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="token-number">$1</span>');
            
            return escaped;
        }

        function enhanceDocContent(containerEl) {
            if (!containerEl) return;
            
            // 1. 代码块增强 (Mac 顶栏 + 语言徽章 + 一键复制 + 语法高亮)
            const preBlocks = containerEl.querySelectorAll('pre');
            preBlocks.forEach(pre => {
                if (pre.closest('.doc-code-card') || pre.classList.contains('mermaid')) return;
                
                let codeEl = pre.querySelector('code') || pre;
                let rawCode = codeEl.textContent || '';
                
                // 识别语言
                let lang = 'CODE';
                if (codeEl.className) {
                    let match = codeEl.className.match(/(?:language-|lang-|code-)([a-zA-Z0-9_-]+)/);
                    if (match) lang = match[1].toUpperCase();
                } else if (pre.className) {
                    let match = pre.className.match(/(?:language-|lang-|code-)([a-zA-Z0-9_-]+)/);
                    if (match) lang = match[1].toUpperCase();
                }
                if (lang === 'MERMAID') return;
                
                // 检查是否为 ASCII / Unicode 文本字符流架构框图
                if (isAsciiDiagram(rawCode)) {
                    const card = document.createElement('div');
                    card.className = 'doc-diagram-card';
                    card.innerHTML = `
                        <div class="doc-code-header">
                            <div class="doc-code-dots">
                                <span class="doc-code-dot doc-dot-red"></span>
                                <span class="doc-code-dot doc-dot-yellow"></span>
                                <span class="doc-code-dot doc-dot-green"></span>
                            </div>
                            <span class="doc-code-lang">📐 架构流程图 (SVG 矢量图形)</span>
                            <div style="display:flex;gap:6px;align-items:center;">
                                <button class="doc-code-copy-btn" onclick="toggleDiagramView(this)">📄 查看源码</button>
                                <button class="doc-code-copy-btn" onclick="copyDocCodeBlock(this)">📋 复制</button>
                            </div>
                        </div>
                        <div class="doc-diagram-svg-view">
                            ${renderAsciiToSvg(rawCode)}
                        </div>
                        <div class="doc-diagram-code-view" style="display:none;">
                            <pre><code>${colorizeAsciiDiagram(rawCode)}</code></pre>
                        </div>
                    `;
                    pre.parentNode.replaceChild(card, pre);
                    return;
                }

                // 语法高亮
                let highlighted = highlightCodeSyntax(rawCode, lang);
                
                // 构建代码卡片
                const card = document.createElement('div');
                card.className = 'doc-code-card';
                card.innerHTML = `
                    <div class="doc-code-header">
                        <div class="doc-code-dots">
                            <span class="doc-code-dot doc-dot-red"></span>
                            <span class="doc-code-dot doc-dot-yellow"></span>
                            <span class="doc-code-dot doc-dot-green"></span>
                        </div>
                        <span class="doc-code-lang">${escapeHtml(lang)}</span>
                        <button class="doc-code-copy-btn" onclick="copyDocCodeBlock(this)">📋 复制</button>
                    </div>
                    <pre><code>${highlighted}</code></pre>
                `;
                pre.parentNode.replaceChild(card, pre);
            });
            
            // 2. 图片卡片化与全屏灯箱
            const images = containerEl.querySelectorAll('.doc-markdown-body img, .doc-rst-body img');
            images.forEach(img => {
                if (img.closest('.doc-image-frame') || img.id === 'doc-lightbox-img') return;
                
                const captionText = img.alt || img.title || '';
                const card = document.createElement('div');
                card.className = 'doc-image-card';
                
                const frame = document.createElement('div');
                frame.className = 'doc-image-frame';
                frame.title = '点击全屏查看高清大图';
                frame.onclick = () => openDocImageLightbox(img.src, captionText);
                
                const cloneImg = img.cloneNode(true);
                frame.appendChild(cloneImg);
                card.appendChild(frame);
                
                if (captionText && captionText !== '全屏预览') {
                    const cap = document.createElement('div');
                    cap.className = 'doc-image-caption';
                    cap.textContent = `▲ ${captionText}`;
                    card.appendChild(cap);
                }
                
                img.parentNode.replaceChild(card, img);
            });
            
            // 3. RST Admonitions 提示框图标注入
            const admonitions = containerEl.querySelectorAll('.doc-rst-body .admonition');
            admonitions.forEach(adm => {
                const titleEl = adm.querySelector('.admonition-title');
                if (titleEl && !titleEl.getAttribute('data-icon-added')) {
                    titleEl.setAttribute('data-icon-added', 'true');
                    let icon = '💡';
                    if (adm.classList.contains('warning')) icon = '⚠️';
                    else if (adm.classList.contains('danger') || adm.classList.contains('caution')) icon = '🛑';
                    else if (adm.classList.contains('tip')) icon = '📌';
                    else if (adm.classList.contains('important')) icon = '🚀';
                    titleEl.innerHTML = `${icon} ${titleEl.innerHTML}`;
                }
            });

            // 4. LaTeX 数学公式渲染 (KaTeX 遍历 .math / div.math / span.math / math 节点)
            if (window.katex) {
                const mathNodes = containerEl.querySelectorAll('.math, div.math, span.math, aside.math, math');
                mathNodes.forEach(mNode => {
                    if (mNode.querySelector('.katex') || mNode.classList.contains('katex')) return;
                    let rawTex = mNode.textContent || '';
                    rawTex = rawTex.replace(/^\\\(/, '').replace(/\\\)$/, '');
                    rawTex = rawTex.replace(/^\\\[/, '').replace(/\\\]$/, '');
                    rawTex = rawTex.replace(/\\begin\{equation\*?\}/, '').replace(/\\end\{equation\*?\}/, '');
                    rawTex = rawTex.trim();
                    if (!rawTex) return;

                    const isDisplay = mNode.tagName === 'DIV' || mNode.tagName === 'ASIDE' || mNode.classList.contains('math-display');
                    try {
                        mNode.innerHTML = katex.renderToString(rawTex, {
                            displayMode: isDisplay,
                            throwOnError: false
                        });
                    } catch(e) {}
                });
            }
        }

        function copyDocCodeBlock(btn) {
            if (!btn) return;
            const card = btn.closest('.doc-code-card');
            if (!card) return;
            const codeEl = card.querySelector('code');
            const text = codeEl ? codeEl.textContent : '';
            if (!text) return;
            
            navigator.clipboard.writeText(text).then(() => {
                btn.textContent = '✓ 已复制';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.textContent = '📋 复制';
                    btn.classList.remove('copied');
                }, 2000);
            }).catch(() => {
                btn.textContent = '✓ 已复制';
                setTimeout(() => { btn.textContent = '📋 复制'; }, 2000);
            });
        }

        function openDocImageLightbox(src, alt) {
            const lightbox = document.getElementById('doc-image-lightbox');
            const img = document.getElementById('doc-lightbox-img');
            if (!lightbox || !img) return;
            img.src = src;
            img.alt = alt || '全屏预览';
            lightbox.style.display = 'flex';
        }

        function closeDocImageLightbox() {
            const lightbox = document.getElementById('doc-image-lightbox');
            if (lightbox) lightbox.style.display = 'none';
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeDocImageLightbox();
            }
        });

        function renderMermaidDiagrams(containerEl) {
            if (!window.mermaid || !containerEl) return;
            try {
                const mermaidNodes = containerEl.querySelectorAll('.mermaid');
                if (mermaidNodes && mermaidNodes.length > 0) {
                    window.mermaid.run({ nodes: Array.from(mermaidNodes) }).catch(err => {
                        console.warn('Mermaid rendering warning:', err);
                    });
                }
            } catch (e) {
                console.warn('Mermaid run error:', e);
            }
        }

        function openInternalDocLink(relHref) {
            if (!relHref) return;
            if (relHref.startsWith('http://') || relHref.startsWith('https://')) {
                handleExternalLinkClick(null, relHref);
                return;
            }
            let baseDir = currentNovelPath ? currentNovelPath.substring(0, currentNovelPath.lastIndexOf('/')) : 'docs';
            let cleanHref = relHref.replace(/^\.\//, '');
            let resolved = baseDir ? `${baseDir}/${cleanHref}` : cleanHref;
            openNovelReader(resolved);
        }

        function fallbackParseMarkdown(md) {
            let html = escapeHtml(md);
            // 代码块
            html = html.replace(/```([a-z0-9_-]*)\n([\s\S]*?)```/g, function(match, lang, code) {
                if (lang.toLowerCase() === 'mermaid') {
                    return `<div class="mermaid-block-wrapper"><div class="mermaid">${code}</div></div>`;
                }
                return `<pre><code class="lang-${lang}">${code}</code></pre>`;
            });
            // 链接
            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" onclick="handleExternalLinkClick(event, \'$2\')" class="doc-markdown-link">$1 ↗</a>');
            // 行内代码
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
            // 标题
            html = html.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
            html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
            html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
            html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
            // 引用
            html = html.replace(/^>\s?(.*?)$/gm, '<blockquote><p>$1</p></blockquote>');
            // 粗体 / 斜体
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            // 分割线
            html = html.replace(/^(?:---|\*\*\*|___)$/gm, '<hr>');
            // 段落
            const blocks = html.split(/\n{2,}/);
            return blocks.map(b => {
                b = b.trim();
                if (!b) return '';
                if (/^<(h[1-6]|pre|blockquote|table|ul|ol|hr|div)/i.test(b)) return b;
                return `<p>${b.replace(/\n/g, '<br>')}</p>`;
            }).join('');
        }

        function onNovelScroll() {
            if (!currentNovelPath) return;
            const scrollBox = document.getElementById('novel-content-scroll');
            try {
                localStorage.setItem('omni_novel_scroll_' + currentNovelPath, scrollBox.scrollTop);
            } catch(e) {}
        }

        function changeFontSize(delta) {
            currentFontSize = Math.max(13, Math.min(28, currentFontSize + delta));
            const viewEl = document.getElementById('novel-content-view');
            viewEl.style.setProperty('--novel-font-size', currentFontSize + 'px');
            viewEl.style.fontSize = currentFontSize + 'px';
        }

        function cycleReaderTheme() {
            currentThemeIdx = (currentThemeIdx + 1) % NOVEL_THEMES.length;
            const modal = document.getElementById('novel-reader-modal');
            NOVEL_THEMES.forEach(t => modal.classList.remove(t));
            modal.classList.add(NOVEL_THEMES[currentThemeIdx]);
            document.getElementById('novel-theme-btn').textContent = NOVEL_THEME_NAMES[currentThemeIdx];
        }

        function toggleNovelFullscreen() {
            const modal = document.getElementById('novel-reader-modal');
            const btn = document.getElementById('novel-fullscreen-btn');
            const isImmersive = modal.classList.toggle('reader-immersive-fullscreen');

            if (!document.fullscreenElement) {
                const req = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || modal.requestFullscreen;
                if (req) {
                    req.call(document.documentElement || modal).catch(() => {});
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen().catch(() => {});
                }
            }

            if (btn) {
                btn.textContent = (isImmersive || document.fullscreenElement) ? '🗗 退出全屏' : '⛶ 全屏';
            }
        }

        // 统一监听浏览器 ESC 或原生全屏切换事件，同步按钮文字与沉浸式状态
        document.addEventListener('fullscreenchange', () => {
            const isFs = !!document.fullscreenElement;
            const nBtn = document.getElementById('novel-fullscreen-btn');
            const mBtn = document.getElementById('manga-fullscreen-btn');
            const nModal = document.getElementById('novel-reader-modal');
            const mModal = document.getElementById('manga-reader-modal');
            if (!isFs) {
                if (nModal) nModal.classList.remove('reader-immersive-fullscreen');
                if (mModal) mModal.classList.remove('reader-immersive-fullscreen');
            }
            if (nBtn) nBtn.textContent = isFs ? '🗗 退出全屏' : '⛶ 全屏';
            if (mBtn) mBtn.textContent = isFs ? '🗗 退出全屏' : '⛶ 全屏';
        });

        // 绑定小说阅读器滚动事件与键盘翻页
        document.addEventListener('DOMContentLoaded', () => {
            const scrollBox = document.getElementById('novel-content-scroll');
            if (scrollBox) scrollBox.addEventListener('scroll', onNovelScroll, { passive: true });
        });

        document.addEventListener('keydown', (e) => {
            const modal = document.getElementById('novel-reader-modal');
            if (!modal || modal.style.display === 'none') return;
            if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;

            if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
                if (currentNovelData && currentNovelData.prev_sibling) {
                    openNovelReader(currentNovelData.prev_sibling.rel_path);
                } else if (currentNovelChapters && currentNovelChapters.length > 1) {
                    goToNovelChapter(currentChapterIndex - 1);
                }
            } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
                if (currentNovelData && currentNovelData.next_sibling) {
                    openNovelReader(currentNovelData.next_sibling.rel_path);
                } else if (currentNovelChapters && currentNovelChapters.length > 1) {
                    goToNovelChapter(currentChapterIndex + 1);
                }
            } else if (e.key === 'Escape') {
                closeNovelReader();
            }
        });

        // ================= 音声与广播剧 (Audio & Player) 模块 =================
        let isAudioNsfw = false;
        let selectedAudioAlbum = 'all';
        let localAudioList = [];
        let totalAudioCount = 0;
        let audioPage = 1;
        let hasMoreAudio = true;
        let isLoadingAudio = false;
        let currentAudioIndex = -1;
        let currentAudioItem = null;
        let audioPlayMode = 'list'; // 'list' | 'single' | 'random'
        const AUDIO_SPEEDS = [1.0, 1.25, 1.5, 2.0, 0.75];
        let audioSpeedIdx = 0;
        let sleepTimerTimeout = null;
        const SLEEP_TIMER_MINS = [0, 15, 30, 60];
        let sleepTimerIdx = 0;
        let audioSearchDebounceTimer = null;

        function toggleAudioNsfw() {
            if (!isAudioNsfw && !isNsfwUnlocked) {
                openNsfwModal();
                return;
            }
            isAudioNsfw = !isAudioNsfw;
            const btn = document.getElementById('audio-nsfw-toggle-btn');
            const heading = document.getElementById('audio-heading');
            const searchInput = document.getElementById('audio-search-input');
            const emptyDesc = document.getElementById('audio-empty-desc');

            if (isAudioNsfw) {
                if (btn) {
                    btn.classList.add('active');
                    btn.style.background = '#da363333';
                    btn.style.borderColor = '#da3633';
                    btn.style.color = '#f85149';
                    btn.style.fontWeight = '700';
                }
                if (heading) heading.textContent = '🔞 NSFW 音声画廊';
                if (searchInput) searchInput.placeholder = '🔍 搜索绅士音声作品...';
                if (emptyDesc) emptyDesc.innerHTML = '请确保 SD 卡已挂载于 <code>/run/media/deck/FUCKDECK/telegramFile/</code> 或本地 <code>audio/nsfw/</code> 目录。';
            } else {
                if (btn) {
                    btn.classList.remove('active');
                    btn.style.background = '';
                    btn.style.borderColor = '';
                    btn.style.color = '';
                    btn.style.fontWeight = '';
                }
                if (heading) heading.textContent = '📻 有声书与广播剧';
                if (searchInput) searchInput.placeholder = '🔍 搜索有声书或专辑...';
                if (emptyDesc) emptyDesc.innerHTML = '常规有声书存放在 <code>audio/standard/</code> 目录，支持子文件夹按专辑归档。点击 🔞 NSFW 按钮可切换至 SD 卡绅士音声库。';
            }
            selectedAudioAlbum = 'all';
            loadAudioLibrary(true);
        }

        function renderAudioAlbumFilterBar(albums) {
            const bar = document.getElementById('audio-album-filter-bar');
            if (!bar) return;
            if (!albums || albums.length <= 1) {
                bar.style.display = 'none';
                bar.innerHTML = '';
                return;
            }
            bar.style.display = 'flex';
            bar.innerHTML = '';
            albums.forEach(alb => {
                const btn = document.createElement('button');
                const isSelected = (selectedAudioAlbum === 'all' && alb.name === '全部') || (selectedAudioAlbum === alb.name);
                btn.className = 'tab-btn' + (isSelected ? ' active' : '');
                btn.style.padding = '4px 12px';
                btn.style.fontSize = '12px';
                btn.style.borderRadius = '16px';
                btn.style.cursor = 'pointer';
                btn.textContent = `${alb.name} (${alb.count})`;
                btn.onclick = () => {
                    selectedAudioAlbum = alb.name === '全部' ? 'all' : alb.name;
                    loadAudioLibrary(true);
                };
                bar.appendChild(btn);
            });
        }

        function loadAudioLibrary(reset = false) {
            if (reset) {
                isLoadingAudio = false;
                audioPage = 1;
                hasMoreAudio = true;
            } else if (isLoadingAudio) {
                return;
            }
            if (!hasMoreAudio && !reset) return;

            isLoadingAudio = true;
            const loadingIndicator = document.getElementById('audio-loading-more');
            if (loadingIndicator && (!localAudioList || localAudioList.length === 0 || !reset)) {
                loadingIndicator.style.display = 'block';
            }

            const searchEl = document.getElementById('audio-search-input');
            const searchVal = (searchEl ? searchEl.value : '').trim().toLowerCase();

            if (!isAudioNsfw) {
                // 非 NSFW 常规有声书模式：读取 standard_catalog.json 并双重过滤，彻底杜绝 SD 卡绅士音频泄漏
                fetch(`/audio/standard_catalog.json?t=${Date.now()}`)
                    .then(r => r.json())
                    .then(res => {
                        isLoadingAudio = false;
                        if (loadingIndicator) loadingIndicator.style.display = 'none';

                        let allItems = res.items || [];
                        allItems = allItems.filter(it => !it.is_nsfw && !it.path?.includes('/run/media/') && !it.path?.includes('telegramFile'));

                        // 核心：自然数字排序 (Natural Sorting: EP1-10 < EP11-20 < EP104-120)
                        allItems.sort((a, b) => {
                            const albA = a.album || '';
                            const albB = b.album || '';
                            const albCmp = albA.localeCompare(albB, undefined, { numeric: true, sensitivity: 'base' });
                            if (albCmp !== 0) return albCmp;
                            return (a.filename || a.title || '').localeCompare(b.filename || b.title || '', undefined, { numeric: true, sensitivity: 'base' });
                        });

                        // 专辑列表聚合与曲目统计
                        const albumCounts = {};
                        allItems.forEach(a => {
                            const alb = a.album || '经典单曲';
                            albumCounts[alb] = (albumCounts[alb] || 0) + 1;
                        });
                        const albums = [{ name: '全部', count: allItems.length }];
                        Object.keys(albumCounts).sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })).forEach(alb => {
                            albums.push({ name: alb, count: albumCounts[alb] });
                        });
                        renderAudioAlbumFilterBar(albums);

                        // 按选中专辑与搜索词过滤
                        let matched = allItems;
                        if (selectedAudioAlbum && selectedAudioAlbum !== 'all') {
                            matched = matched.filter(a => a.album === selectedAudioAlbum);
                        }
                        if (searchVal) {
                            matched = matched.filter(a => (a.title || '').toLowerCase().includes(searchVal) || (a.album || '').toLowerCase().includes(searchVal));
                        }

                        totalAudioCount = matched.length;
                        hasMoreAudio = false;
                        localAudioList = matched;

                        const badge = document.getElementById('audio-total-count-badge');
                        if (badge) badge.textContent = `共 ${totalAudioCount} 首`;

                        if (activePrimarySection === 'media' && activeMediaTab === 'audio') {
                            document.getElementById('total-badge').textContent = `${totalAudioCount} 部有声书`;
                            const subStats = document.getElementById('media-sub-stats');
                            if (subStats) subStats.textContent = `共 ${totalAudioCount} 部有声书 (支持后台全局播放)`;
                        }

                        renderAudioTrackList(true);
                    })
                    .catch(err => {
                        isLoadingAudio = false;
                        if (loadingIndicator) loadingIndicator.style.display = 'none';
                        console.error('Failed to load standard audio catalog:', err);
                    });
                return;
            }

            // NSFW 模式：请求后端 API 点播 SD 卡及 NSFW 音声库
            const url = `/api/audio/library?nsfw=1&album=${encodeURIComponent(selectedAudioAlbum)}&q=${encodeURIComponent(searchVal)}&page=${audioPage}&page_size=80&t=${Date.now()}`;

            fetch(url)
                .then(r => r.json())
                .then(res => {
                    isLoadingAudio = false;
                    if (loadingIndicator) loadingIndicator.style.display = 'none';

                    const items = res.items || [];
                    totalAudioCount = res.total || 0;
                    hasMoreAudio = res.has_more || false;

                    if (reset) {
                        localAudioList = items;
                    } else {
                        localAudioList = localAudioList.concat(items);
                    }

                    renderAudioAlbumFilterBar(res.albums || []);

                    const badge = document.getElementById('audio-total-count-badge');
                    if (badge) badge.textContent = `共 ${totalAudioCount} 首`;

                    if (activePrimarySection === 'media' && activeMediaTab === 'audio') {
                        document.getElementById('total-badge').textContent = `${totalAudioCount} 部绅士音声`;
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = `共 ${totalAudioCount} 部绅士音声 (支持后台全局播放)`;
                    }

                    renderAudioTrackList(reset);
                    audioPage++;
                })
                .catch(err => {
                    isLoadingAudio = false;
                    if (loadingIndicator) loadingIndicator.style.display = 'none';
                    console.error('Failed to load nsfw audio:', err);
                });
        }

        function renderAudioTrackList(reset = false) {
            const listEl = document.getElementById('audio-track-list');
            const emptyEl = document.getElementById('audio-empty-msg');
            if (!listEl) return;

            if (reset) listEl.innerHTML = '';

            if (localAudioList.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';

            const startIdx = reset ? 0 : listEl.children.length;
            for (let i = startIdx; i < localAudioList.length; i++) {
                const item = localAudioList[i];
                if (!isAudioNsfw && (item.is_nsfw || (item.path && (item.path.includes('/run/media/') || item.path.includes('telegramFile'))))) {
                    continue;
                }
                const card = document.createElement('div');
                card.className = 'audio-track-item' + (currentAudioItem && (currentAudioItem.rel_path || currentAudioItem.filename) === (item.rel_path || item.filename) ? ' playing' : '');
                card.id = `audio-track-item-${i}`;
                card.onclick = () => playAudio(i);

                const ext = (item.ext || 'mp3').toUpperCase();
                const albumTag = item.album ? `<span class="novel-badge novel-badge-genre" style="background:#1f6feb22;color:#58a6ff;border:1px solid #388bfd44;margin-right:6px;">${escapeHtml(item.album)}</span>` : '';
                const hasChapters = item.chapters && item.chapters.length > 0;
                const chapterTag = hasChapters ? `<span class="novel-badge" style="background:#23863622;color:#3fb950;border:1px solid #2ea04344;margin-right:6px;">📑 ${item.chapters.length} 章节选集</span>` : '';
                const chapterBtn = hasChapters ? `<button class="manga-mini-btn" title="查看各回选集目录" style="background:#23863622;color:#3fb950;border-color:#2ea04366;" onclick="event.stopPropagation(); openAudioChaptersModalWithIndex(${i})">📑 选集</button>` : '';

                card.innerHTML = `
                    <div class="audio-track-info">
                        <div class="audio-track-icon">${item.ext === 'm4b' ? '📕' : (isAudioNsfw ? '🎧' : '📻')}</div>
                        <div style="overflow:hidden;flex:1;">
                            <div class="audio-track-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                            <div class="audio-track-meta">
                                ${albumTag}
                                ${chapterTag}
                                <span class="novel-badge novel-badge-txt">${ext}</span>
                                <span>${item.size_mb} MB</span>
                                <span>${item.mtime}</span>
                            </div>
                        </div>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;" onclick="event.stopPropagation()">
                        ${chapterBtn}
                        <button class="manga-mini-btn" title="立即播放" onclick="playAudio(${i})">▶</button>
                        <button class="manga-mini-btn" title="移至回收站" onclick="deleteAudioFile('${escapeAttr(item.rel_path || item.filename)}', ${item.is_nsfw ? 'true' : 'false'})">🗑️</button>
                    </div>
                `;
                listEl.appendChild(card);
            }
            if (listEl.children.length === 0 && emptyEl) {
                emptyEl.style.display = 'block';
            }
        }

        function playAudio(index) {
            if (index < 0 || index >= localAudioList.length) return;
            currentAudioIndex = index;
            currentAudioItem = localAudioList[index];
            playAudioItem(currentAudioItem);
            updateTrackPlayingHighlight();
        }

        let currentAudioChapters = [];
        let lastActiveChapter = null;

        function playAudioItem(item) {
            const playerBar = document.getElementById('global-audio-player-bar');
            const audioEl = document.getElementById('main-audio-element');
            const titleEl = document.getElementById('player-track-title');
            const badgeEl = document.getElementById('player-track-badge');
            const discEl = document.getElementById('player-disc-icon');
            const playBtn = document.getElementById('player-play-btn');

            currentAudioChapters = item.chapters || [];
            lastActiveChapter = null;

            const chaptersBtn = document.getElementById('player-chapters-btn');
            const chaptersBadge = document.getElementById('player-chapter-badge');
            if (chaptersBtn) {
                if (currentAudioChapters.length > 0) {
                    chaptersBtn.style.display = 'inline-flex';
                    if (chaptersBadge) chaptersBadge.textContent = currentAudioChapters.length;
                } else {
                    chaptersBtn.style.display = 'none';
                }
            }

            if (playerBar) {
                playerBar.style.display = 'flex';
                if (typeof checkScrollTopVisibility === 'function') checkScrollTopVisibility();
            }
            if (titleEl) titleEl.textContent = item.title;
            const albumName = item.album || (item.is_nsfw ? 'NSFW音声' : '有声书');
            const chapInfo = currentAudioChapters.length > 0 ? ` · 含 ${currentAudioChapters.length} 章节` : '';
            if (badgeEl) badgeEl.textContent = `${albumName} · ${(item.ext || 'MP3').toUpperCase()} · ${item.size_mb} MB${chapInfo}`;

            audioEl.src = item.stream_url;
            audioEl.preload = 'auto';
            audioEl.playbackRate = AUDIO_SPEEDS[audioSpeedIdx];

            // 立即初始化时间显示与进度条，防止 00:00 闪烁
            const curTimeEl = document.getElementById('player-cur-time');
            const totalTimeEl = document.getElementById('player-total-time');
            const seekBar = document.getElementById('player-seek-bar');
            if (curTimeEl) curTimeEl.textContent = '00:00';
            if (seekBar) seekBar.value = 0;
            if (totalTimeEl) {
                if (currentAudioChapters.length > 0) {
                    totalTimeEl.textContent = formatAudioTime(currentAudioChapters[currentAudioChapters.length - 1].end);
                } else {
                    totalTimeEl.textContent = '--:--';
                }
            }

            // 恢复历史播放位置 (断点续听) 与元数据加载联动
            const trackKey = 'omni_audio_pos_' + (item.rel_path || item.filename);
            const savedPos = parseFloat(localStorage.getItem(trackKey) || '0');
            audioEl.onloadedmetadata = () => {
                const totalSecs = (audioEl.duration && !isNaN(audioEl.duration))
                    ? audioEl.duration
                    : (currentAudioChapters.length ? currentAudioChapters[currentAudioChapters.length - 1].end : 0);
                if (totalTimeEl && totalSecs > 0) {
                    totalTimeEl.textContent = formatAudioTime(totalSecs);
                }
                if (savedPos > 3 && totalSecs && savedPos < totalSecs - 5) {
                    audioEl.currentTime = savedPos;
                }
            };

            audioEl.play().catch(e => console.log('Autoplay policy:', e));

            if (discEl) discEl.classList.add('spinning');
            if (playBtn) playBtn.innerHTML = '⏸';
        }

        function toggleAudioPlay() {
            const audioEl = document.getElementById('main-audio-element');
            const playBtn = document.getElementById('player-play-btn');
            const discEl = document.getElementById('player-disc-icon');

            if (!audioEl.src) {
                if (localAudioList.length > 0) playAudio(0);
                return;
            }

            if (audioEl.paused) {
                audioEl.play();
                if (playBtn) playBtn.innerHTML = '⏸';
                if (discEl) discEl.classList.add('spinning');
            } else {
                audioEl.pause();
                if (playBtn) playBtn.innerHTML = '▶';
                if (discEl) discEl.classList.remove('spinning');
            }
        }

        function playNextAudio() {
            if (localAudioList.length === 0) return;
            if (audioPlayMode === 'random') {
                playRandomAudio();
            } else {
                let nextIdx = currentAudioIndex + 1;
                if (nextIdx >= localAudioList.length) nextIdx = 0;
                playAudio(nextIdx);
            }
        }

        function playPrevAudio() {
            if (localAudioList.length === 0) return;
            let prevIdx = currentAudioIndex - 1;
            if (prevIdx < 0) prevIdx = localAudioList.length - 1;
            playAudio(prevIdx);
        }

        function playRandomAudio() {
            if (localAudioList.length === 0) return;
            const randIdx = Math.floor(Math.random() * localAudioList.length);
            playAudio(randIdx);
        }

        function onAudioSeek(val) {
            const audioEl = document.getElementById('main-audio-element');
            if (!audioEl) return;
            const totalSecs = (audioEl.duration && !isNaN(audioEl.duration))
                ? audioEl.duration
                : (currentAudioChapters.length ? currentAudioChapters[currentAudioChapters.length - 1].end : 0);
            if (totalSecs > 0) {
                const targetTime = (val / 100) * totalSecs;
                try {
                    audioEl.currentTime = targetTime;
                } catch(e) {
                    console.warn('Seek error:', e);
                }
                const curTimeEl = document.getElementById('player-cur-time');
                if (curTimeEl) curTimeEl.textContent = formatAudioTime(targetTime);
            }
        }

        function cycleAudioSpeed() {
            audioSpeedIdx = (audioSpeedIdx + 1) % AUDIO_SPEEDS.length;
            const speed = AUDIO_SPEEDS[audioSpeedIdx];
            const audioEl = document.getElementById('main-audio-element');
            if (audioEl) audioEl.playbackRate = speed;
            const text = `${speed.toFixed(speed % 1 === 0 ? 1 : 2)}x`;
            const btn = document.getElementById('player-speed-btn');
            const quickBtn = document.getElementById('player-speed-quick-btn');
            if (btn) btn.textContent = text;
            if (quickBtn) quickBtn.textContent = text;
        }

        function cycleAudioMode() {
            const modes = ['list', 'single', 'random'];
            const names = ['🔁 列表', '🔂 单曲', '🔀 随机'];
            const curIdx = modes.indexOf(audioPlayMode);
            const nextIdx = (curIdx + 1) % modes.length;
            audioPlayMode = modes[nextIdx];
            const btn = document.getElementById('player-mode-btn');
            const quickBtn = document.getElementById('player-mode-quick-btn');
            if (btn) btn.textContent = names[nextIdx];
            if (quickBtn) quickBtn.textContent = names[nextIdx];
        }

        function cycleSleepTimer() {
            sleepTimerIdx = (sleepTimerIdx + 1) % SLEEP_TIMER_MINS.length;
            const mins = SLEEP_TIMER_MINS[sleepTimerIdx];
            const btn = document.getElementById('player-sleep-btn');
            if (sleepTimerTimeout) {
                clearTimeout(sleepTimerTimeout);
                sleepTimerTimeout = null;
            }
            if (mins > 0) {
                btn.textContent = `⏳ ${mins}分`;
                btn.style.color = '#58a6ff';
                sleepTimerTimeout = setTimeout(() => {
                    const audioEl = document.getElementById('main-audio-element');
                    if (audioEl) audioEl.pause();
                    btn.textContent = '⏳ 定时';
                    btn.style.color = '';
                    sleepTimerIdx = 0;
                    alert('⏳ 定时关闭生效，已为您暂停音频播放。');
                }, mins * 60 * 1000);
            } else {
                btn.textContent = '⏳ 定时';
                btn.style.color = '';
            }
        }

        function setAudioVolume(val) {
            const audioEl = document.getElementById('main-audio-element');
            if (audioEl) audioEl.volume = parseFloat(val);
        }

        function hideGlobalAudioPlayer() {
            const playerBar = document.getElementById('global-audio-player-bar');
            const audioEl = document.getElementById('main-audio-element');
            if (audioEl) audioEl.pause();
            if (playerBar) {
                playerBar.style.display = 'none';
                if (typeof checkScrollTopVisibility === 'function') checkScrollTopVisibility();
            }
        }

        function deleteAudioFile(filepath, isNsfw = false) {
            const shortName = filepath.split('/').pop();
            if (!confirm(`确定将音频《${shortName}》移至回收站吗？`)) return;
            fetch('/api/audio/trash', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: filepath, is_nsfw: isNsfw })
            }).then(r => r.json()).then(() => {
                loadAudioLibrary(true);
            });
        }

        function formatAudioTime(secs) {
            if (isNaN(secs) || secs < 0) return '00:00';
            const h = Math.floor(secs / 3600);
            const m = Math.floor((secs % 3600) / 60);
            const s = Math.floor(secs % 60);
            const mm = m < 10 ? '0' + m : m;
            const ss = s < 10 ? '0' + s : s;
            if (h > 0) {
                const hh = h < 10 ? '0' + h : h;
                return `${hh}:${mm}:${ss}`;
            }
            return `${mm}:${ss}`;
        }

        function openAudioChaptersModalWithIndex(idx) {
            if (idx < 0 || idx >= localAudioList.length) return;
            const item = localAudioList[idx];
            currentAudioChapters = item.chapters || [];
            if (!currentAudioItem || (currentAudioItem.rel_path || currentAudioItem.filename) !== (item.rel_path || item.filename)) {
                playAudio(idx);
            }
            renderAudioChaptersModal(item);
            const modal = document.getElementById('audio-chapters-modal');
            if (modal) modal.style.display = 'flex';
        }

        function toggleAudioChaptersModal() {
            const modal = document.getElementById('audio-chapters-modal');
            if (!modal) return;
            if (modal.style.display === 'flex') {
                closeAudioChaptersModal();
            } else {
                if (currentAudioItem) {
                    renderAudioChaptersModal(currentAudioItem);
                }
                modal.style.display = 'flex';
            }
        }

        function closeAudioChaptersModal(e) {
            if (e && e.target && e.target.id !== 'audio-chapters-modal') return;
            const modal = document.getElementById('audio-chapters-modal');
            if (modal) modal.style.display = 'none';
        }

        function renderAudioChaptersModal(item) {
            const titleEl = document.getElementById('audio-chapters-modal-title');
            const sumEl = document.getElementById('audio-chapters-summary');
            const listEl = document.getElementById('audio-chapters-list');
            const audioEl = document.getElementById('main-audio-element');
            if (!listEl) return;

            const chaps = item.chapters || [];
            if (titleEl) titleEl.textContent = `📑 《${item.title}》章节选集目录`;
            if (sumEl) sumEl.textContent = `共 ${chaps.length} 个回目 · 点击即可即刻瞬移播放`;

            listEl.innerHTML = '';
            const curTime = audioEl ? audioEl.currentTime : 0;

            chaps.forEach((ch) => {
                const isActive = curTime >= ch.start && curTime < ch.end;
                const row = document.createElement('div');
                row.className = 'audio-chapter-item' + (isActive ? ' active' : '');
                row.id = `audio-chapter-row-${ch.index}`;
                row.onclick = () => jumpToAudioChapter(ch.start);

                row.innerHTML = `
                    <div style="display:flex;align-items:center;gap:12px;overflow:hidden;flex:1;">
                        <span class="audio-chapter-idx">${ch.index}</span>
                        <span class="audio-chapter-name" title="${escapeAttr(ch.title)}">${escapeHtml(ch.title)}</span>
                    </div>
                    <span class="audio-chapter-time">${ch.duration_str}</span>
                `;
                listEl.appendChild(row);
            });
        }

        function updateActiveChapterInDrawer(activeIdx) {
            document.querySelectorAll('.audio-chapter-item').forEach(el => el.classList.remove('active'));
            const activeRow = document.getElementById(`audio-chapter-row-${activeIdx}`);
            if (activeRow) activeRow.classList.add('active');
        }

        function jumpToAudioChapter(startTime) {
            const audioEl = document.getElementById('main-audio-element');
            if (audioEl) {
                const doSeek = () => {
                    try {
                        audioEl.currentTime = startTime;
                    } catch (e) {
                        console.warn('Seek error:', e);
                    }
                    if (audioEl.paused) audioEl.play().catch(() => {});

                    // 立即预更新 UI 界面，杜绝延迟卡顿
                    const curTimeEl = document.getElementById('player-cur-time');
                    const seekBar = document.getElementById('player-seek-bar');
                    const totalSecs = (audioEl.duration && !isNaN(audioEl.duration))
                        ? audioEl.duration
                        : (currentAudioChapters.length ? currentAudioChapters[currentAudioChapters.length - 1].end : 0);
                    if (curTimeEl) curTimeEl.textContent = formatAudioTime(startTime);
                    if (seekBar && totalSecs > 0) seekBar.value = Math.min(100, (startTime / totalSecs) * 100);

                    // 立即更新底栏与抽屉中的高亮章节
                    if (currentAudioChapters && currentAudioChapters.length > 0) {
                        const activeCh = currentAudioChapters.find(c => startTime >= c.start && startTime < c.end) || currentAudioChapters[0];
                        if (activeCh) {
                            lastActiveChapter = activeCh;
                            const subBadge = document.getElementById('player-track-badge');
                            if (subBadge && currentAudioItem) {
                                subBadge.textContent = `${activeCh.title} (${activeCh.duration_str}) · ${currentAudioItem.album}`;
                            }
                            updateActiveChapterInDrawer(activeCh.index);
                        }
                    }
                };

                if (audioEl.readyState >= 1) {
                    doSeek();
                } else {
                    audioEl.addEventListener('loadedmetadata', doSeek, { once: true });
                    audioEl.addEventListener('canplay', doSeek, { once: true });
                    if (audioEl.paused) audioEl.play().catch(() => {});
                }
            }
            closeAudioChaptersModal();
        }

        function updateTrackPlayingHighlight() {
            document.querySelectorAll('.audio-track-item').forEach(el => el.classList.remove('playing'));
            if (currentAudioIndex >= 0) {
                const activeEl = document.getElementById(`audio-track-item-${currentAudioIndex}`);
                if (activeEl) activeEl.classList.add('playing');
            }
        }

        // 监听原生 Audio 元素事件
        document.addEventListener('DOMContentLoaded', () => {
            const audioEl = document.getElementById('main-audio-element');
            const curTimeEl = document.getElementById('player-cur-time');
            const totalTimeEl = document.getElementById('player-total-time');
            const seekBar = document.getElementById('player-seek-bar');
            const discEl = document.getElementById('player-disc-icon');
            const playBtn = document.getElementById('player-play-btn');

            if (audioEl) {
                audioEl.ontimeupdate = () => {
                    const totalSecs = (audioEl.duration && !isNaN(audioEl.duration))
                        ? audioEl.duration
                        : (currentAudioChapters.length ? currentAudioChapters[currentAudioChapters.length - 1].end : 0);

                    if (totalSecs > 0) {
                        const percent = Math.min(100, (audioEl.currentTime / totalSecs) * 100);
                        if (seekBar) seekBar.value = percent;
                        if (curTimeEl) curTimeEl.textContent = formatAudioTime(audioEl.currentTime);
                        if (totalTimeEl) totalTimeEl.textContent = formatAudioTime(totalSecs);
                    } else {
                        if (curTimeEl) curTimeEl.textContent = formatAudioTime(audioEl.currentTime);
                    }

                    // 动态感知与联动当前播放章节
                    if (currentAudioChapters && currentAudioChapters.length > 0) {
                        const cur = audioEl.currentTime;
                        const activeCh = currentAudioChapters.find(c => cur >= c.start && cur < c.end) || currentAudioChapters[0];
                        if (activeCh && activeCh !== lastActiveChapter) {
                            lastActiveChapter = activeCh;
                            const subBadge = document.getElementById('player-track-badge');
                            if (subBadge && currentAudioItem) {
                                subBadge.textContent = `${activeCh.title} (${activeCh.duration_str}) · ${currentAudioItem.album}`;
                            }
                            updateActiveChapterInDrawer(activeCh.index);
                        }
                    }

                    // 自动记录断点续听位置
                    if (currentAudioItem && audioEl.currentTime > 5) {
                        const trackKey = 'omni_audio_pos_' + (currentAudioItem.rel_path || currentAudioItem.filename);
                        try { localStorage.setItem(trackKey, Math.floor(audioEl.currentTime)); } catch(e) {}
                    }
                };

                audioEl.onended = () => {
                    if (currentAudioItem) {
                        const trackKey = 'omni_audio_pos_' + (currentAudioItem.rel_path || currentAudioItem.filename);
                        try { localStorage.removeItem(trackKey); } catch(e) {}
                    }
                    if (audioPlayMode === 'single') {
                        audioEl.currentTime = 0;
                        audioEl.play();
                    } else {
                        playNextAudio();
                    }
                };

                audioEl.onplay = () => {
                    if (playBtn) playBtn.innerHTML = '⏸';
                    if (discEl) discEl.classList.add('spinning');
                };

                audioEl.onpause = () => {
                    if (playBtn) playBtn.innerHTML = '▶';
                    if (discEl) discEl.classList.remove('spinning');
                };
            }
        });

        // ==========================================
        // 全局浮动回到顶部模块 (Scroll to Top)
        // ==========================================
        function checkScrollTopVisibility() {
            const btn = document.getElementById('scroll-to-top-btn');
            if (!btn) return;

            // 动态检查全局音频播放条是否开启，避开底部遮挡
            const playerBar = document.getElementById('global-audio-player-bar');
            const isPlayerActive = playerBar && getComputedStyle(playerBar).display !== 'none';
            if (isPlayerActive) {
                btn.classList.add('elevated');
            } else {
                btn.classList.remove('elevated');
            }

            const currentScroll = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
            if (currentScroll > 240) {
                btn.classList.add('visible');
            } else {
                btn.classList.remove('visible');
            }
        }

        function scrollToTop() {
            try {
                window.scrollTo({ top: 0, behavior: 'smooth' });
                document.documentElement.scrollTo({ top: 0, behavior: 'smooth' });
                document.body.scrollTo({ top: 0, behavior: 'smooth' });
            } catch (e) {
                window.scrollTo(0, 0);
            }
        }

        // 触底自动无限追加加载与回到顶部按钮响应
        window.addEventListener('scroll', () => {
            checkScrollTopVisibility();

            const nearBottom = (window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 600);
            if (!nearBottom) return;

            if (activePrimarySection === 'media') {
                if (activeMediaTab === 'audio') {
                    if (!hasMoreAudio || isLoadingAudio) return;
                    loadAudioLibrary(false);
                } else if (activeMediaTab === 'manga') {
                    if (activeMangaSubTab === 'shelf') {
                        loadMoreMangaShelf();
                    } else if (currentMangaSearchQuery && hasMoreMangaPages && !isLoadingMoreManga) {
                        loadNextMangaPage();
                    }
                } else if (activeMediaTab === 'novels') {
                    loadMoreNovelsShelf();
                }
            }
        }, { passive: true });

        window.addEventListener('resize', checkScrollTopVisibility, { passive: true });
        window.addEventListener('DOMContentLoaded', checkScrollTopVisibility);

        // ==========================================
        // MEGA 网盘中枢原生集成模块 (mega-cmd 驱动)
        // ==========================================
        let megaStatus = null;
        let currentMegaPath = '/';
        let currentMegaFiles = [];
        let megaTransferPollTimer = null;
        let megaToastTimer = null;

        function showMegaToast(msg, isError = false) {
            const toast = document.getElementById('mega-toast');
            const msgEl = document.getElementById('mega-toast-msg');
            const iconEl = document.getElementById('mega-toast-icon');
            if (!toast || !msgEl) return;

            msgEl.textContent = msg;
            if (iconEl) iconEl.textContent = isError ? '⚠️' : '✅';
            toast.style.background = isError ? '#b62324' : '#238636';
            toast.style.display = 'flex';
            toast.style.opacity = '1';

            if (megaToastTimer) clearTimeout(megaToastTimer);
            megaToastTimer = setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => { toast.style.display = 'none'; }, 250);
            }, 3200);
        }

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

        // 启动时自动恢复上次离开时所在的一级页面 (游戏区 或 媒体区)
        try {
            checkNsfwStatus();
            checkLanStatus();
            checkWanStatus();
            initMangaEventStream();
            loadPersistentMangaQueue();
            const savedSection = localStorage.getItem('omni_primary_section');
            if (savedSection === 'media' || savedSection === 'manga') {
                switchToMediaSection();
                loadGames();
            } else {
                loadGames();
            }
            // 启动时静默预热媒体专区数量与列表，彻底告别 0 部/0 首闪烁与空白页面
            setTimeout(prewarmMediaLibraries, 50);
        } catch(e) {
            console.error('Init error:', e);
            loadGames();
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
