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

// 一级板块状态 ('games' 或 'manga')
let activePrimarySection = 'games';

let activeMediaTab = (Omni.sections('media').find(s => s.default) || { id: 'docs' }).id;

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
    Omni.each('onMediaEnter');
}

function switchMediaTab(tab, btnEl) {
    const rule = ACCESS_RULES[tab];
    if (rule && rule.requiresNsfwUnlock && !isNsfwUnlocked) {
        openNsfwModal();
        return;
    }
    if (rule && rule.requiresLocal && isRemoteClient) {
        return;   // 局域网不可用标签：按钮已隐藏，这里只是兜底（URL 直连等场景）
    }
    activeMediaTab = tab;
    document.querySelectorAll('.media-nav-bar .tab-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    updateMediaTabUI();
    if (typeof checkScrollTopVisibility === 'function') setTimeout(checkScrollTopVisibility, 50);
}

function updateMediaTabUI() {
    for (const s of Omni.sections('media')) {
        const view = document.getElementById(`media-${s.id}-view`);
        if (view) view.style.display = activeMediaTab === s.id ? 'block' : 'none';
    }
    Omni.call(activeMediaTab, 'activate');
}

function prewarmMediaLibraries() {
    // 静默预热各媒体分区（漫画/小说/音声等在各自模块的 prewarm 钩子里），避免首次切入时闪 0 部/0 首
    Omni.each('prewarm');
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

    if (activePrimarySection === 'media') Omni.call(activeMediaTab, 'onScrollEnd');
}, { passive: true });

window.addEventListener('resize', checkScrollTopVisibility, { passive: true });

window.addEventListener('DOMContentLoaded', checkScrollTopVisibility);
