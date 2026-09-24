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
    // 启动时静默预热媒体专区数量与列表，彻底告别 0 部/0 首闪烁与空白页面
    setTimeout(prewarmMediaLibraries, 50);
} catch(e) {
    console.error('Init error:', e);
    loadGames();
}
