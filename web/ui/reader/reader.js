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
