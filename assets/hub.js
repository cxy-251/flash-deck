// 客户端位置判定：默认本机（Steam Deck）优先，由后端 /api/lan/status 根据物理 Socket 来源 IP 权威仲裁
        let isRemoteClient = false;
        let allGames = [];
        let currentTab = 'rpg';
        let currentStandaloneSubTab = null;
        let currentSearchQuery = '';
        let currentGameSearchQuery = '';

        function applyRemoteClientRestrictions() {
            if (!isRemoteClient) return;

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

            // 4. 隐藏网络能力开关 (局域网与广域网)：远程访客严禁操作服务端的网络能力，同时为移动端界面释放宝贵顶栏空间
            const lanControl = document.getElementById('lan-control-wrapper');
            const wanControl = document.getElementById('wan-control-wrapper');
            if (lanControl) lanControl.style.display = 'none';
            if (wanControl) wanControl.style.display = 'none';
        }

        function removeRemoteClientRestrictions() {
            // Steam Deck 本机环境：彻底恢复独立大作卡片与专区原本的生机与互动能力
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

            // 恢复本机网络能力控制按钮显示
            const lanControl = document.getElementById('lan-control-wrapper');
            const wanControl = document.getElementById('wan-control-wrapper');
            if (lanControl) lanControl.style.display = 'inline-flex';
            if (wanControl) wanControl.style.display = 'inline-flex';
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
            var initStyle = document.getElementById('cat-init-style');
            if (initStyle) initStyle.remove();
            document.getElementById('portal-view').style.display = 'block';
            document.getElementById('list-view').style.display = 'none';
            document.getElementById('list-controls').style.display = 'none';
            document.getElementById('nav-back-btn').style.display = 'none';
            const gSearch = document.getElementById('game-search-input');
            if (gSearch) gSearch.value = '';
            currentSearchQuery = '';
            currentGameSearchQuery = '';
            currentTab = 'rpg';
            currentStandaloneSubTab = null;
            document.querySelectorAll('#standalone-sub-filters .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
            if (window.history && window.history.replaceState) {
                window.history.replaceState(null, '', window.location.pathname);
            }
            window.scrollTo({ top: 0, behavior: 'instant' });
        }

        function openCategory(cat) {
            if (isRemoteClient && cat === 'standalone') {
                alert('🔒 独立大作专区属于大型 PC / Windows / Wine 程序，仅限 Steam Deck 实体机本机窗口游玩。\n\n局域网访问已禁用此专区，防止外部并发唤醒导致掌机卡顿！');
                return;
            }
            if (isRemoteClient && cat === 'flash') {
                alert('🔒 Flash 殿堂专区依赖 Steam Deck 本地 Pepper Flash 插件环境，外部浏览器不支持运行。\n\n局域网访问已禁用此专区。');
                return;
            }
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
            if (isRemoteClient && tab === 'standalone') {
                alert('🔒 独立大作专区属于大型 PC / Windows / Wine 程序，仅限 Steam Deck 实体机本机窗口游玩。\n\n局域网访问已禁用此专区，防止外部并发唤醒导致掌机卡顿！');
                return;
            }
            if (isRemoteClient && tab === 'flash') {
                alert('🔒 Flash 殿堂专区依赖 Steam Deck 本地 Pepper Flash 插件环境，外部浏览器不支持运行。\n\n局域网访问已禁用此专区。');
                return;
            }
            currentTab = tab;
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            if (el) el.classList.add('active');
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

        function onMangaSearchInput(val) {
            const q = (val || '').trim();
            currentMangaSearchQuery = q;
            if (!q) {
                clearMangaSearch();
            } else {
                const matchedLocal = localMangaList.filter(item => item.title.toLowerCase().includes(q.toLowerCase()));
                const localSection = document.getElementById('manga-local-section');
                const localHeading = document.getElementById('manga-local-heading');
                const emptyEl = document.getElementById('manga-shelf-empty');

                if (matchedLocal.length > 0) {
                    localSection.style.display = 'block';
                    localHeading.textContent = `🟢 本地已收录 (匹配到 ${matchedLocal.length} 部 · 点击封面直接阅读)`;
                    renderMangaShelf(matchedLocal);
                    emptyEl.style.display = 'none';
                } else {
                    localSection.style.display = 'none';
                }
            }
        }

        function onMangaSearchEnter() {
            const input = document.getElementById('manga-search-input');
            const val = input ? input.value.trim() : '';
            if (val) {
                executeUnifiedSearch(val);
            }
        }

        function onNovelSearchInput(val) {
            const q = (val || '').trim();
            currentNovelSearchQuery = q;
            if (!q) {
                clearNovelSearch();
            } else {
                const matchedLocal = localNovelsList.filter(item => item.title.toLowerCase().includes(q.toLowerCase()));
                const localSection = document.getElementById('novel-local-section');
                const localHeading = document.getElementById('novel-local-heading');
                const emptyEl = document.getElementById('novels-shelf-empty');

                if (matchedLocal.length > 0) {
                    localSection.style.display = 'block';
                    localHeading.textContent = `🟢 本地已收录 (匹配到 ${matchedLocal.length} 本 · 点击封面直接阅读)`;
                    renderNovelsShelf(matchedLocal);
                    emptyEl.style.display = 'none';
                } else {
                    localSection.style.display = 'none';
                }
            }
        }

        function onNovelSearchEnter() {
            const input = document.getElementById('novel-search-input');
            const val = input ? input.value.trim() : '';
            if (val) {
                executeUnifiedNovelSearch(val);
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

            const filtered = allGames.filter(g => {
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
            
            updateFavBadges();
            applyRemoteClientRestrictions();
            
            if (!isManualRefresh) {
                const urlParams = new URLSearchParams(window.location.search);
                const initCat = urlParams.get('category');
                if (initCat && initCat !== 'portal') {
                    document.getElementById('portal-view').style.display = 'none';
                    document.getElementById('list-view').style.display = 'block';
                    document.getElementById('list-controls').style.display = 'flex';
                    document.getElementById('nav-back-btn').style.display = 'flex';
                    currentTab = initCat;
                    document.querySelectorAll('.tab-btn').forEach(btn => {
                        btn.classList.toggle('active', btn.dataset.tab === initCat);
                    });
                }
            }
            applyFilter();
        }

        // 优先从缓存中同步完成秒级渲染，避免网络请求延迟导致的视觉闪烁
        try {
            const cached = sessionStorage.getItem('omni_games_cache');
            if (cached) {
                populateGames(JSON.parse(cached));
            }
        } catch(e) {}

        function loadGames() {
            fetch('/api/games?t=' + Date.now(), { cache: 'no-store' })
                .then(res => res.json())
                .then(games => {
                    sessionStorage.setItem('omni_games_cache', JSON.stringify(games));
                    populateGames(games);
                })
                .catch(err => {
                    console.error('Failed to load games:', err);
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

        let activeMediaTab = 'manga';
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
            document.getElementById('header-brand-title').textContent = '📖 Omni Deck Media';
            document.getElementById('primary-section-btn').innerHTML = '🎮 游戏专区';
            document.getElementById('nav-back-btn').style.display = 'none';

            // Remove any inline injected styles that might force display:flex on list-controls!
            const catStyle = document.getElementById('cat-init-style');
            if (catStyle) catStyle.remove();

            document.getElementById('games-section').style.display = 'none';
            document.getElementById('list-controls').style.display = 'none';
            document.getElementById('media-section').style.display = 'block';

            updateMediaTabUI();
            loadPersistentMangaQueue();
            loadMangaLibrary();
            loadNovelsLibrary();
            pollMangaTasks();
        }

        let localDocsList = [];
        let currentDocFilter = 'all';

        function switchMediaTab(tab, btnEl) {
            activeMediaTab = tab;
            document.querySelectorAll('.media-nav-bar .tab-btn').forEach(b => b.classList.remove('active'));
            if (btnEl) btnEl.classList.add('active');
            updateMediaTabUI();
        }

        function updateMediaTabUI() {
            const mangaView = document.getElementById('media-manga-view');
            const novelsView = document.getElementById('media-novels-view');
            const docsView = document.getElementById('media-docs-view');
            const audioView = document.getElementById('media-audio-view');
            const subStats = document.getElementById('media-sub-stats');

            if (mangaView) mangaView.style.display = activeMediaTab === 'manga' ? 'block' : 'none';
            if (novelsView) novelsView.style.display = activeMediaTab === 'novels' ? 'block' : 'none';
            if (docsView) docsView.style.display = activeMediaTab === 'docs' ? 'block' : 'none';
            if (audioView) audioView.style.display = activeMediaTab === 'audio' ? 'block' : 'none';

            if (activeMediaTab === 'manga') {
                const count = localMangaList ? localMangaList.length : 0;
                document.getElementById('total-badge').textContent = count + ' 部漫画';
                if (subStats) subStats.textContent = '共 ' + count + ' 部漫画';
                if (localMangaList.length === 0) loadMangaLibrary();
            } else if (activeMediaTab === 'novels') {
                const count = localNovelsList ? localNovelsList.length : 0;
                document.getElementById('total-badge').textContent = count + ' 本小说';
                if (subStats) subStats.textContent = '共 ' + count + ' 本已收录小说';
                if (localNovelsList.length === 0) loadNovelsLibrary();
            } else if (activeMediaTab === 'docs') {
                loadDocsLibrary();
            } else if (activeMediaTab === 'audio') {
                const count = totalAudioCount || localAudioList.length;
                document.getElementById('total-badge').textContent = (count || '1880+') + ' 部音声作品';
                if (subStats) subStats.textContent = '共 ' + (count || '1880+') + ' 部音声作品 (支持后台全局播放)';
                if (localAudioList.length === 0) {
                    loadAudioLibrary(true);
                }
            }
        }

        function switchToGamesSection() {
            activePrimarySection = 'games';
            try { localStorage.setItem('omni_primary_section', 'games'); } catch(e) {}
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

        function loadMangaLibrary() {
            fetch('/api/manga/library?dir=manga&t=' + Date.now())
                .then(r => r.json())
                .then(list => {
                    localMangaList = list || [];
                    if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                        document.getElementById('total-badge').textContent = localMangaList.length + ' 部漫画';
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = '共 ' + localMangaList.length + ' 部漫画';
                    }
                    const searchVal = (document.getElementById('manga-search-input') ? document.getElementById('manga-search-input').value : '').trim();
                    if (activeMangaSubTab === 'shelf') {
                        if (!searchVal) {
                            renderMangaShelf(localMangaList);
                        } else {
                            const matched = localMangaList.filter(item => item.title.toLowerCase().includes(searchVal.toLowerCase()));
                            renderMangaShelf(matched);
                        }
                    } else if (rankingDataCache[activeMangaSubTab]) {
                        renderMangaRankingGrid(rankingDataCache[activeMangaSubTab]);
                    }
                })
                .catch(err => {
                    console.error('Failed to load manga library:', err);
                });
        }

        function renderMangaShelf(items) {
            const grid = document.getElementById('manga-shelf-grid');
            const emptyEl = document.getElementById('manga-shelf-empty');
            grid.innerHTML = '';

            if (!items || items.length === 0) {
                emptyEl.style.display = 'block';
                return;
            }
            emptyEl.style.display = 'none';

            items.forEach(item => {
                const card = document.createElement('div');
                card.className = 'manga-card';
                // 用户核心要求：不用立即阅读按钮，直接点击卡片封面进入阅读器
                card.onclick = () => openMangaReader(item.filename, 'manga');

                card.innerHTML = `
                    <div class="manga-cover-wrap">
                        ${item.has_cover ? `<img src="${item.cover_url}" class="manga-cover" loading="lazy">` : `<div class="manga-cover-fallback">📖</div>`}
                        <span class="manga-badge-cbz">单文件 CBZ</span>
                        <div class="manga-actions-hover" onclick="event.stopPropagation()">
                            <button class="manga-mini-btn" title="调用系统外部阅读器 (Okular)" onclick="openExternalManga('${escapeAttr(item.filename)}', 'manga')">🖥️</button>
                            <button class="manga-mini-btn" title="移至回收站" onclick="deleteMangaFile('${escapeAttr(item.filename)}', 'manga')">🗑️</button>
                        </div>
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        <div class="manga-meta">
                            <span>${item.page_count ? item.page_count + ' 页' : '整本'}</span>
                            <span>${item.size_mb} MB</span>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        // ================= 漫画画廊子标签与必看榜单系统 (每周必看 / 每月必看 TOP 80) =================
        let activeMangaSubTab = 'shelf'; // 'shelf' | 'week' | 'month'
        let rankingDataCache = {
            week: null,
            month: null
        };

        function switchMangaSubTab(subTab, btnEl) {
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
                renderMangaShelf(localMangaList);
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

                let rankBadgeClass = 'rank-other';
                if (rankNum === 1) rankBadgeClass = 'rank-top-1';
                else if (rankNum === 2) rankBadgeClass = 'rank-top-2';
                else if (rankNum === 3) rankBadgeClass = 'rank-top-3';

                let badgeHtml = `
                    <span class="manga-rank-badge ${rankBadgeClass}">TOP ${rankNum}</span>
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
            const clearBtn = document.getElementById('manga-queue-clear-btn');
            if (!listEl) return;

            listEl.innerHTML = '';
            if (mangaDownloadQueue.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                if (startBtn) startBtn.disabled = true;
                if (clearBtn) clearBtn.disabled = true;
                return;
            }

            if (emptyEl) emptyEl.style.display = 'none';
            if (startBtn) startBtn.disabled = false;
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

        function startMangaQueueBatchDownload() {
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
                    clean_temp: true
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

        // ================= 2. 搜索框输入防抖与键盘事件 =================
        let mangaSearchDebounceTimer = null;
        function onMangaSearchInput(val) {
            clearTimeout(mangaSearchDebounceTimer);
            val = (val || '').trim();
            if (!val) {
                clearMangaSearch();
                return;
            }
            const matched = localMangaList.filter(item => item.title.toLowerCase().includes(val.toLowerCase()));
            const localSection = document.getElementById('manga-local-section');
            const localHeading = document.getElementById('manga-local-heading');
            if (localSection) localSection.style.display = matched.length > 0 ? 'block' : 'none';
            if (localHeading) localHeading.textContent = `🟢 本地已收录 (匹配到 ${matched.length} 部 · 点击封面直接阅读)`;
            renderMangaShelf(matched);

            mangaSearchDebounceTimer = setTimeout(() => {
                executeUnifiedSearch(val);
            }, 600);
        }

        function onMangaSearchEnter() {
            clearTimeout(mangaSearchDebounceTimer);
            const input = document.getElementById('manga-search-input');
            const val = (input ? input.value : '').trim();
            if (val) {
                executeUnifiedSearch(val);
            } else {
                clearMangaSearch();
            }
        }

        function onNovelSearchInput(val) {
            val = (val || '').trim().toLowerCase();
            const heading = document.getElementById('novel-local-heading');
            if (!val) {
                if (heading) heading.textContent = '📚 本地已收录小说';
                renderNovelsShelf(localNovelsList);
                return;
            }
            const matched = localNovelsList.filter(item => {
                const t = (item.title || '').toLowerCase();
                const f = (item.filename || item.rel_path || '').toLowerCase();
                return t.includes(val) || f.includes(val);
            });
            if (heading) heading.textContent = `🟢 匹配结果 (${matched.length} 本)`;
            renderNovelsShelf(matched);
        }

        function executeUnifiedSearch(overrideQuery) {
            const q = (overrideQuery !== undefined ? overrideQuery : document.getElementById('manga-search-input').value || '').trim();
            if (!q) {
                clearMangaSearch();
                return;
            }

            currentMangaSearchQuery = q;
            currentMangaPage = 1;
            hasMoreMangaPages = false;
            isLoadingMoreManga = false;
            totalOnlineMangaCount = 0;

            // 1. 本地匹配
            const matchedLocal = localMangaList.filter(item => item.title.toLowerCase().includes(q.toLowerCase()));
            const localSection = document.getElementById('manga-local-section');
            const localHeading = document.getElementById('manga-local-heading');
            const emptyEl = document.getElementById('manga-shelf-empty');

            if (matchedLocal.length > 0) {
                localSection.style.display = 'block';
                localHeading.textContent = `🟢 本地已收录 (匹配到 ${matchedLocal.length} 部 · 点击封面直接阅读)`;
                renderMangaShelf(matchedLocal);
                emptyEl.style.display = 'none';
            } else {
                localSection.style.display = 'none';
            }

            // 2. 同时检索禁漫全网（支持单 ID、多 ID 或标题关键字）
            const onlineSection = document.getElementById('manga-online-section');
            const onlineLoading = document.getElementById('manga-online-loading');
            const onlineGrid = document.getElementById('manga-online-grid');
            const kwLabel = document.getElementById('manga-search-kw-label');
            const moreLoading = document.getElementById('manga-online-more-loading');
            const endTip = document.getElementById('manga-online-end-tip');

            if (moreLoading) moreLoading.style.display = 'none';
            if (endTip) endTip.style.display = 'none';

            onlineSection.style.display = 'block';
            onlineLoading.style.display = 'block';
            onlineGrid.innerHTML = '';
            kwLabel.textContent = `正在全网检索: "${q}"...`;

            fetch('/api/manga/search?q=' + encodeURIComponent(q) + '&category=0&order_by=' + encodeURIComponent(currentMangaSort) + '&page=1&t=' + Date.now())
                .then(r => r.json())
                .then(data => {
                    onlineLoading.style.display = 'none';
                    currentOnlineResults = data.online || [];
                    hasMoreMangaPages = !!data.has_more;
                    totalOnlineMangaCount = data.total_online || currentOnlineResults.length;

                    if (totalOnlineMangaCount > currentOnlineResults.length) {
                        kwLabel.textContent = `检索: "${q}" (已加载 ${currentOnlineResults.length}/${totalOnlineMangaCount} 部 · 向下滚动自动加载更多)`;
                    } else {
                        kwLabel.textContent = `检索: "${q}" (共 ${currentOnlineResults.length} 部)`;
                    }

                    renderOnlineResults(currentOnlineResults, matchedLocal.length === 0, false);

                    if (!hasMoreMangaPages && currentOnlineResults.length > 0 && endTip) {
                        endTip.style.display = 'block';
                    }
                })
                .catch(err => {
                    onlineLoading.style.display = 'none';
                    onlineGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f85149;padding:40px;">禁漫在线检索遇到异常: ${err}</div>`;
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
            if (onlineSection) onlineSection.style.display = 'none';
            currentOnlineResults = [];
            currentMangaSearchQuery = '';
            currentMangaPage = 1;
            hasMoreMangaPages = false;
            isLoadingMoreManga = false;
            const endTip = document.getElementById('manga-online-end-tip');
            const moreLoading = document.getElementById('manga-online-more-loading');
            if (endTip) endTip.style.display = 'none';
            if (moreLoading) moreLoading.style.display = 'none';
        }

        function clearMangaSearch() {
            const input = document.getElementById('manga-search-input');
            if (input) input.value = '';

            const localSection = document.getElementById('manga-local-section');
            const localHeading = document.getElementById('manga-local-heading');
            if (localSection) localSection.style.display = 'block';
            if (localHeading) localHeading.textContent = '📚 本地已收录漫画';
            renderMangaShelf(localMangaList);

            clearOnlineSearchResults();
        }

        function renderOnlineResults(results, isLocalEmpty = false, isAppend = false) {
            const grid = document.getElementById('manga-online-grid');
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

            const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed');
            if (activeTasks.length > 0) {
                container.style.display = 'block';
                card.innerHTML = tasks.slice(0, 3).map(t => `
                    <div style="display:flex;flex-direction:column;gap:6px;padding:6px 0;border-bottom:1px solid #21262d;">
                        <div class="manga-task-row">
                            <div style="font-size:13px;font-weight:600;color:#f0f6fc;">${escapeHtml(t.title)}</div>
                            <div style="font-size:12px;color:#58a6ff;font-weight:700;">${t.percent}%</div>
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
            isNovelNsfw = !isNovelNsfw;
            const btn = document.getElementById('novel-nsfw-toggle-btn');
            const heading = document.getElementById('novel-shelf-heading');
            const searchInput = document.getElementById('novel-search-input');
            const srcIndicator = document.getElementById('novel-source-indicator');

            if (isNovelNsfw) {
                if (btn) {
                    btn.classList.add('active');
                    btn.style.background = '#da363333';
                    btn.style.borderColor = '#da3633';
                    btn.style.color = '#f85149';
                    btn.style.fontWeight = '700';
                }
                if (heading) heading.textContent = '🔞 NSFW 已收录小说';
                if (searchInput) searchInput.placeholder = '🔍 搜索日系 R18 轻小说、同人、母系题材 (如 妈妈、影之实力者)...';
                if (srcIndicator) srcIndicator.textContent = '🎌 ESJ Zone 汉化组 · Pixiv 二次元同人文学源 (R18/母系/拔作/日轻)';
            } else {
                if (btn) {
                    btn.classList.remove('active');
                    btn.style.background = '';
                    btn.style.borderColor = '';
                    btn.style.color = '';
                    btn.style.fontWeight = '';
                }
                if (heading) heading.textContent = '📚 本地已收录小说';
                if (searchInput) searchInput.placeholder = '🔍 搜索小说书名、作者、标签或题材 (如 妈妈、三国演义、凡人)...';
                if (srcIndicator) srcIndicator.textContent = '🏛️ 中华古典名著公版库 · 全网精选文学源 (修真/科幻/都市/家庭)';
            }

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
                    
                    const searchVal = (document.getElementById('novel-search-input') ? document.getElementById('novel-search-input').value : '').trim();
                    renderNovelsShelf(searchVal ? filterLocalNovels(searchVal) : localNovelsList);
                })
                .catch(err => {
                    console.error('Failed to load novels library:', err);
                });
        }

        function filterLocalNovels(query) {
            const q = query.toLowerCase();
            return localNovelsList.filter(item => {
                return (item.title && item.title.toLowerCase().includes(q)) ||
                       (item.author && item.author.toLowerCase().includes(q)) ||
                       (item.rel_path && item.rel_path.toLowerCase().includes(q));
            });
        }

        function renderNovelsShelf(list) {
            const grid = document.getElementById('novels-shelf-grid');
            const emptyEl = document.getElementById('novels-shelf-empty');
            if (!grid) return;
            grid.innerHTML = '';

            const items = list !== undefined ? list : localNovelsList;
            if (!items || items.length === 0) {
                if (emptyEl) emptyEl.style.display = 'block';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';

            items.forEach(item => {
                const card = document.createElement('div');
                card.className = 'manga-card';
                const safeName = escapeAttr(item.filename || item.rel_path);
                const ext = (item.ext || '').toLowerCase();
                const isEpub = ext === 'epub';
                const clickAction = `openNovelReader('${escapeAttr(item.rel_path || item.filename)}')`;
                
                const coverHtml = item.has_cover 
                    ? `<img src="/api/novels/cover?path=${encodeURIComponent(item.rel_path)}" class="manga-cover" loading="lazy">`
                    : `<div style="width:100%;height:100%;background:linear-gradient(135deg,#1f242c,#0d1117);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:12px 8px;text-align:center;">
                         <span style="font-size:26px;margin-bottom:6px;">${isNovelNsfw ? '🔞' : '📖'}</span>
                         <span style="font-size:12px;font-weight:700;color:#f0f6fc;line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${escapeHtml(item.title)}</span>
                       </div>`;

                const badgeLabel = isEpub ? 'EPUB 典藏' : (ext === 'txt' ? 'TXT 文本' : ext.toUpperCase());
                const sizeText = item.size_mb ? `${item.size_mb} MB` : (item.size_kb ? `${item.size_kb} KB` : `${item.char_count || 0} 字`);
                const authorText = item.author && item.author !== '未知作者' ? ` · ${escapeHtml(item.author)}` : '';

                card.innerHTML = `
                    <div class="manga-cover-wrap" onclick="${clickAction}">
                        ${coverHtml}
                        <span class="manga-badge-cbz" style="${isEpub ? 'background:#1f6feb;color:#fff;' : ''}">${badgeLabel}</span>
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${safeName}" onclick="${clickAction}">${escapeHtml(item.title)}</div>
                        <div class="manga-meta">
                            <span style="font-size:11px;color:#8b949e;">${sizeText}${authorText}</span>
                            <div style="display:flex;gap:4px;" onclick="event.stopPropagation()">
                                <button class="manga-mini-btn" title="移至回收站" onclick="deleteNovelFile('${escapeAttr(item.rel_path || item.filename)}')">🗑️</button>
                            </div>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function onNovelSearchInput(val) {
            const trimmed = (val || '').trim();
            renderNovelsShelf(trimmed ? filterLocalNovels(trimmed) : localNovelsList);

            if (novelSearchTimer) clearTimeout(novelSearchTimer);
            if (!trimmed) {
                const onlineSec = document.getElementById('novel-online-section');
                if (onlineSec) onlineSec.style.display = 'none';
                return;
            }

            novelSearchTimer = setTimeout(() => {
                executeNovelSearch(trimmed);
            }, 300);
        }

        function onNovelSearchEnter() {
            if (novelSearchTimer) clearTimeout(novelSearchTimer);
            const input = document.getElementById('novel-search-input');
            const val = (input ? input.value : '').trim();
            if (val) executeNovelSearch(val);
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
            const item = novelOnlineResults.find(b => String(b.id) === id) || novelDownloadQueue.find(b => String(b.id) === id);
            if (!item) return;

            const inQueue = isNovelInQueue(id);
            if (inQueue) {
                fetch('/api/novels/queue/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id })
                }).then(() => {
                    novelDownloadQueue = novelDownloadQueue.filter(x => String(x.id) !== id);
                    updateNovelQueueUI(id, false, btnEl);
                });
            } else {
                fetch('/api/novels/queue/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: item.id,
                        title: item.title,
                        author: item.author,
                        intro: item.intro,
                        cover_url: item.cover_url,
                        is_nsfw: isNovelNsfw
                    })
                }).then(() => {
                    novelDownloadQueue.push({
                        id: item.id,
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
                targetBtn.textContent = inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表';
            }
            renderNovelQueueModal();
        }

        function renderNovelOnlineResults(results) {
            const grid = document.getElementById('novels-online-grid');
            if (!grid) return;
            grid.innerHTML = '';

            if (!results || results.length === 0) {
                grid.innerHTML = `<div style="color:#8b949e;padding:30px;grid-column:1/-1;text-align:center;">未找到匹配作品，请更换书名、作者或标签关键词重试</div>`;
                return;
            }

            const localTitleSet = new Set(localNovelsList.map(b => b.title.replace(/\.[^/.]+$/, '').trim()));

            results.forEach(item => {
                const card = document.createElement('div');
                card.className = 'manga-card';
                const isLocal = localTitleSet.has(item.title.trim()) || localNovelsList.some(b => b.title.includes(item.title) || item.title.includes(b.title));
                const inQueue = isNovelInQueue(item.id);

                const coverHtml = item.cover_url
                    ? `<img src="${item.cover_url}" class="manga-cover" loading="lazy" onerror="this.parentElement.innerHTML='<div style=\\'width:100%;height:100%;background:linear-gradient(135deg,#1f242c,#0d1117);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:12px 8px;text-align:center;\\'><span style=\\'font-size:26px;margin-bottom:6px;\\'>${isNovelNsfw ? '🔞' : '📚'}</span><span style=\\'font-size:12px;font-weight:700;color:#f0f6fc;line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;\\'>${escapeHtml(item.title)}</span></div>'">`
                    : `<div style="width:100%;height:100%;background:linear-gradient(135deg,#1f242c,#0d1117);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:12px 8px;text-align:center;">
                         <span style="font-size:26px;margin-bottom:6px;">${isNovelNsfw ? '🔞' : '📚'}</span>
                         <span style="font-size:12px;font-weight:700;color:#f0f6fc;line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${escapeHtml(item.title)}</span>
                         <span style="font-size:10px;color:#8b949e;margin-top:6px;">${escapeHtml(item.author || '精选')}</span>
                       </div>`;

                const actionHtml = isLocal
                    ? `<button class="manga-btn manga-btn-primary" style="font-size:11px;padding:4px 8px;" onclick="openNovelReader('${escapeAttr(item.title)}')">📖 立即阅读</button>`
                    : `<button id="novel-queue-btn-${escapeAttr(item.id)}" class="manga-btn ${inQueue ? 'manga-btn-in-queue' : ''}" style="font-size:11px;padding:4px 8px;" onclick="toggleNovelQueueItem('${escapeAttr(item.id)}', this)">${inQueue ? '✓ 已在列表中' : '➕ 加入待下载列表'}</button>
                       <button id="novel-dl-btn-${escapeAttr(item.id)}" class="manga-btn manga-btn-primary" style="font-size:11px;padding:4px 8px;" onclick="downloadSingleNovelById('${escapeAttr(item.id)}', this)">📥 下载 EPUB</button>`;

                card.innerHTML = `
                    <div class="manga-cover-wrap">
                        ${coverHtml}
                        <span class="manga-badge-cbz" style="background:${isNovelNsfw ? '#da3633' : '#1f6feb'};color:#fff;">${escapeHtml(item.category || '小说')}</span>
                        ${isLocal ? '<span class="manga-badge-downloaded">✓ 已在书架</span>' : ''}
                    </div>
                    <div class="manga-info">
                        <div class="manga-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                        <div style="font-size:11px;color:#8b949e;margin-top:2px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                            <span>${escapeHtml(item.author)}</span>
                            <span style="font-size:10px;background:#21262d;color:#58a6ff;padding:1px 5px;border-radius:4px;border:1px solid #30363d;">${escapeHtml(item.source || '文库源')}</span>
                        </div>
                        ${item.intro ? `<div style="font-size:11px;color:#7d8590;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.4;" title="${escapeAttr(item.intro)}">${escapeHtml(item.intro)}</div>` : ''}
                        <div class="manga-meta" style="margin-top:8px;">
                            <div style="display:flex;gap:6px;width:100%;justify-content:flex-end;">
                                ${actionHtml}
                            </div>
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
            fetch('/api/novels/queue?t=' + Date.now())
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
                body: JSON.stringify({ id })
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
            fetch('/api/novels/queue/clear', { method: 'POST' }).then(() => {
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
                .then(r => r.json())
                .then(data => {
                    currentNovelData = data;
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

                        viewEl.innerHTML = `
                            <div class="doc-markdown-body">
                                ${parseMarkdownToHtml(data.raw || '')}
                            </div>
                            ${bottomNavHtml}
                        `;
                        renderMermaidDiagrams(viewEl);
                        const scrollBox = document.getElementById('novel-content-scroll');
                        if (scrollBox) scrollBox.scrollTop = 0;
                    } else if (currentNovelChapters.length > 1) {
                        // 2. 小说多回目
                        chBtn.style.display = 'inline-flex';
                        renderNovelChaptersList(currentNovelChapters);

                        // 恢复历史阅读章节
                        let savedCh = parseInt(localStorage.getItem('omni_novel_ch_' + relPath) || '0', 10);
                        if (isNaN(savedCh) || savedCh < 0 || savedCh >= currentNovelChapters.length) {
                            savedCh = 0;
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
                            viewEl.innerHTML = `<div class="doc-markdown-body">${data.html || parseMarkdownToHtml(data.raw || '')}</div>`;
                            renderMermaidDiagrams(viewEl);
                        } else if (ext === 'md' || ext === 'markdown') {
                            renderMarkdownDoc(data.raw || '', viewEl);
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

        function parseMarkdownToHtml(md) {
            if (!md) return '';
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
                            return `<div class="mermaid-block-wrapper"><div class="mermaid" id="${uniqueId}">${escapeHtml(code)}</div></div>`;
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
            renderMermaidDiagrams(containerEl);
        }

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

        function loadAudioLibrary(reset = false) {
            if (isLoadingAudio) return;
            if (reset) {
                audioPage = 1;
                localAudioList = [];
                hasMoreAudio = true;
            }
            if (!hasMoreAudio && !reset) return;

            isLoadingAudio = true;
            const loadingIndicator = document.getElementById('audio-loading-more');
            if (loadingIndicator) loadingIndicator.style.display = 'block';

            const searchEl = document.getElementById('audio-search-input');
            const searchVal = (searchEl ? searchEl.value : '').trim();
            const url = `/api/audio/library?q=${encodeURIComponent(searchVal)}&page=${audioPage}&page_size=80`;

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

                    const badge = document.getElementById('audio-total-count-badge');
                    if (badge) badge.textContent = `共 ${totalAudioCount} 首`;

                    if (activePrimarySection === 'media' && activeMediaTab === 'audio') {
                        document.getElementById('total-badge').textContent = `${totalAudioCount} 部音声作品`;
                        const subStats = document.getElementById('media-sub-stats');
                        if (subStats) subStats.textContent = `共 ${totalAudioCount} 部音声作品 (支持后台全局播放)`;
                    }

                    renderAudioTrackList(reset);
                    audioPage++;
                })
                .catch(err => {
                    isLoadingAudio = false;
                    if (loadingIndicator) loadingIndicator.style.display = 'none';
                    console.error('Failed to load audio:', err);
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
                const card = document.createElement('div');
                card.className = 'audio-track-item' + (currentAudioItem && currentAudioItem.filename === item.filename ? ' playing' : '');
                card.id = `audio-track-item-${i}`;
                card.onclick = () => playAudio(i);

                const ext = (item.ext || 'mp3').toUpperCase();

                card.innerHTML = `
                    <div class="audio-track-info">
                        <div class="audio-track-icon">🎧</div>
                        <div style="overflow:hidden;flex:1;">
                            <div class="audio-track-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
                            <div class="audio-track-meta">
                                <span class="novel-badge novel-badge-txt">${ext}</span>
                                <span>${item.size_mb} MB</span>
                                <span>${item.mtime}</span>
                            </div>
                        </div>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;" onclick="event.stopPropagation()">
                        <button class="manga-mini-btn" title="立即播放" onclick="playAudio(${i})">▶</button>
                        <button class="manga-mini-btn" title="移至回收站" onclick="deleteAudioFile('${escapeAttr(item.filename)}')">🗑️</button>
                    </div>
                `;
                listEl.appendChild(card);
            }
        }

        function playAudio(index) {
            if (index < 0 || index >= localAudioList.length) return;
            currentAudioIndex = index;
            currentAudioItem = localAudioList[index];
            playAudioItem(currentAudioItem);
            updateTrackPlayingHighlight();
        }

        function playAudioItem(item) {
            const playerBar = document.getElementById('global-audio-player-bar');
            const audioEl = document.getElementById('main-audio-element');
            const titleEl = document.getElementById('player-track-title');
            const badgeEl = document.getElementById('player-track-badge');
            const discEl = document.getElementById('player-disc-icon');
            const playBtn = document.getElementById('player-play-btn');

            if (playerBar) playerBar.style.display = 'flex';
            if (titleEl) titleEl.textContent = item.title;
            if (badgeEl) badgeEl.textContent = `${(item.ext || 'MP3').toUpperCase()} · ${item.size_mb} MB · 音声画廊`;

            audioEl.src = item.stream_url;
            audioEl.playbackRate = AUDIO_SPEEDS[audioSpeedIdx];
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
            if (audioEl && audioEl.duration) {
                audioEl.currentTime = (val / 100) * audioEl.duration;
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
            if (playerBar) playerBar.style.display = 'none';
        }

        function deleteAudioFile(filename) {
            if (!confirm(`确定将音频《${filename}》移至回收站吗？`)) return;
            fetch('/api/audio/trash', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: filename })
            }).then(r => r.json()).then(() => {
                loadAudioLibrary(true);
            });
        }

        function formatAudioTime(secs) {
            if (isNaN(secs) || secs < 0) return '00:00';
            const m = Math.floor(secs / 60);
            const s = Math.floor(secs % 60);
            const mm = m < 10 ? '0' + m : m;
            const ss = s < 10 ? '0' + s : s;
            return `${mm}:${ss}`;
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
                    if (audioEl.duration) {
                        const percent = (audioEl.currentTime / audioEl.duration) * 100;
                        if (seekBar) seekBar.value = percent;
                        if (curTimeEl) curTimeEl.textContent = formatAudioTime(audioEl.currentTime);
                        if (totalTimeEl) totalTimeEl.textContent = formatAudioTime(audioEl.duration);
                    }
                };

                audioEl.onended = () => {
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

        // 触底自动无限追加加载
        window.addEventListener('scroll', () => {
            if (activePrimarySection === 'media' && activeMediaTab === 'audio') {
                if (!hasMoreAudio || isLoadingAudio) return;
                if ((window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 600)) {
                    loadAudioLibrary(false);
                }
            } else if (activePrimarySection === 'media' && activeMediaTab === 'manga') {
                if (!currentMangaSearchQuery || !hasMoreMangaPages || isLoadingMoreManga) return;
                if ((window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 600)) {
                    loadNextMangaPage();
                }
            }
        }, { passive: true });

        // 启动时自动恢复上次离开时所在的一级页面 (游戏区 或 媒体区)
        try {
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
        } catch(e) {
            console.error('Init error:', e);
            loadGames();
        }
