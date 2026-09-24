// Omni Deck 前端核心：分区注册表 + 全站共用的工具函数。
//
// 页面由 omni/core/http/hub.py 按 omni/manifest.json 组装；各脚本都是普通 <script>，共享全局作用域
// （HTML 里 onclick="xxx()" 直接调各文件的全局函数）。功能目录的脚本用 Omni.register() 登记自己
// 负责的分区，外壳（app/shell.js）切标签、滚动到底、解锁、预热时按分区分派，不再认识具体分区：
//   Omni.register('<module>', {
//       activate(sectionId)     切到该分区（或该模块负责的某个分区）时
//       onScrollEnd(sectionId)  分区可见且滚动到接近底部时（无限加载）
//       onUnlock(sectionId)     NSFW 解锁成功、且当前停在该分区时
//       prewarm()               启动后静默预热（切进来时不闪 0 条）
//       onMediaEnter()          从游戏区切到媒体区时
//   });
const Omni = window.Omni = {
    manifest: window.OMNI_MANIFEST || { sections: [], groups: [], controls: [] },
    _features: {},
    register(module, hooks) { this._features[module] = hooks; },
    section(id) { return this.manifest.sections.find(s => s.id === id) || null; },
    sections(group) { return this.manifest.sections.filter(s => !group || s.group === group); },
    moduleOf(id) { const s = this.section(id); return s ? (s.module || s.id) : id; },
    // 调某个分区所属模块的钩子（sectionId 作为第一个参数传入）
    call(sectionId, hook, ...args) {
        const f = this._features[this.moduleOf(sectionId)];
        if (f && typeof f[hook] === 'function') return f[hook](sectionId, ...args);
    },
    // 广播给所有登记了该钩子的模块
    each(hook, ...args) {
        for (const [name, f] of Object.entries(this._features)) {
            if (typeof f[hook] !== 'function') continue;
            try { f[hook](...args); } catch (e) { console.error(`[Omni] ${name}.${hook}:`, e); }
        }
    },
};

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

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
    if (!str) return '';
    return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// 全站通用 Toast（历史原因函数名/元素 id 带 mega-）
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
