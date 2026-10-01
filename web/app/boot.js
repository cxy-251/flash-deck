// 按钮上的 data-icon 换成图标（web/ui/icons.js）
hydrateIcons(document);

// 优先从持久缓存中同步完成秒级渲染，避免网络请求延迟导致的视觉闪烁与空屏
try {
    const cached = localStorage.getItem('omni_games_cache') || sessionStorage.getItem('omni_games_cache');
    if (cached) {
        populateGames(JSON.parse(cached));
    }
} catch(e) {}

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
    // 媒体分区不再启动时预热：点进哪个分区才加载哪个（各分区 activate 里列表为空就会去读）
} catch(e) {
    console.error('Init error:', e);
    loadGames();
}
