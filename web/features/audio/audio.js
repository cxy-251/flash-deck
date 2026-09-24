function onAudioSearchInput(val) {
    if (audioSearchDebounceTimer) clearTimeout(audioSearchDebounceTimer);
    audioSearchDebounceTimer = setTimeout(() => {
        loadAudioLibrary(true);
    }, 250);
}

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
        if (emptyDesc) emptyDesc.innerHTML = '请确保内容放在 <code>~/Games/media_library/audio/nsfw/</code> 或 SD 卡镜像的 <code>media_library/audio/nsfw/</code> 目录下。';
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
                // 只按 is_nsfw 这一个字段判断，不再额外按路径里有没有 "/run/media/"（SD 卡挂载点）
                // 二次过滤——那条规则是标准音频还只存在 SSD 上那个年代加的"防 NSFW 音频混进来"
                // 保险，现在标准音频也合法地搬去 SD 卡了，继续按路径过滤会把这些正常内容也
                // 当成 NSFW 误杀掉。is_nsfw 本身在后端就是严格分开算的（standard/nsfw 走的是
                // 完全不同的扫描目录+索引 kind），单独这一个字段判断已经够了。
                allItems = allItems.filter(it => !it.is_nsfw);

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
        if (!isAudioNsfw && item.is_nsfw) {   // 只看 is_nsfw，不再额外按路径二次过滤，理由见 loadAudioLibrary()
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
    // 本机：有 omniBridge 就走原生解码播放（QtWebEngine 解不了 AAC，同一套原生播放
    // 通道，见 native_player.py）。原生播放器音频模式是贴在窗口底部的一条细控制条，
    // 不挡网页——网页这个 HTML 音频条就不用显示了，章节/倍速/睡眠定时都挪到原生
    // 控件里自己闭环。局域网/远程没有这个 bridge，走下面原来那套网页 <audio> 播放器。
    if (window.omniBridge && typeof window.omniBridge.playAudio === 'function') {
        nativePlaybackKind = 'audio';
        const nsfwFlag = item.is_nsfw ? '1' : '0';
        window.omniBridge.playAudio(item.rel_path || item.filename, nsfwFlag, item.title || '', JSON.stringify(item.chapters || []));
        return;
    }

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

Omni.register('audio', {
    activate() {
        const subStats = document.getElementById('media-sub-stats');
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
    },
    onScrollEnd() {
        if (!hasMoreAudio || isLoadingAudio) return;
        loadAudioLibrary(false);
    },
    onUnlock() { loadAudioLibrary(true); },
    onLibraryChanged() { localAudioList = []; totalAudioCount = 0; },
    prewarm() {
        if (!localAudioList || localAudioList.length === 0) {
                const prefetchUrl = isAudioNsfw 
                    ? `/api/audio/library?nsfw=1&q=&page=1&page_size=80&t=${Date.now()}`
                    : `/audio/standard_catalog.json?t=${Date.now()}`;
                fetch(prefetchUrl)
                    .then(r => r.json())
                    .then(res => {
                        let items = res.items || [];
                        if (!isAudioNsfw) {
                            items = items.filter(it => !it.is_nsfw);   // 只看 is_nsfw，不再额外按路径二次过滤，理由见 loadAudioLibrary()
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
    },
});
