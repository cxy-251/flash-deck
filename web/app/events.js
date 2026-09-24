// ================= 异步事件推送流 (Server-Sent Events) =================
let mangaEventSource = null;

function initMangaEventStream() {
    if (mangaEventSource) return;
    try {
        mangaEventSource = new EventSource('/api/events');
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
                        else if (dir && dir.startsWith('shortvideo:')) liveRefreshShortVideoLibrary(dir.slice('shortvideo:'.length));
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
