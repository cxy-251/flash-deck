// NSFW 隐私授权与访问控制全局状态
let isDeckLocal = (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');

let isNsfwUnlocked = isDeckLocal;

try {
    const cachedAuth = localStorage.getItem('omni_nsfw_unlocked') ?? sessionStorage.getItem('omni_nsfw_unlocked');
    if (cachedAuth !== null) {
        isNsfwUnlocked = (cachedAuth === '1');
    }
} catch(e) {}

// 客户端位置判定：默认本机（Steam Deck）优先，由后端 /api/lan/status 根据物理 Socket 来源 IP 权威仲裁
let isRemoteClient = false;

// ============ 分区/标签展示权限总表（由 omni/manifest.json 生成） ============
// 显示/隐藏、以及点击时是弹密码框还是静默拒绝，全部走 isAccessAllowed()/applyAccessRules()。
// 后端给同一分区的 API 用的也是 manifest 里这个 access 字段——前后端是同一份权限定义。
//   selectors:          门面卡片 / 分类标签 / 媒体标签按钮的 CSS 选择器，命中的元素一起隐藏。
//   requiresNsfwUnlock: access=nsfw，需要先解锁隐私密码才能看到（点击时弹密码框）。
//   requiresLocal:      access=local，仅 Steam Deck 本机可用，局域网及以外设备一律隐藏（点击静默无视）。
//   showDisplay:        展示时用的 display 值（manifest controls[].show_display），省略则交给样式表。
const ACCESS_RULES = (function buildAccessRules() {
    const rules = {};
    for (const s of Omni.sections()) {
        if (s.access !== 'nsfw' && s.access !== 'local') continue;
        const selectors = s.group === 'games'
            ? [`.${s.id}-card`, `.tab-btn[data-tab="${s.id}"]`]
            : [`#media-tab-${s.id}`];
        rules[s.id] = s.access === 'nsfw' ? { selectors, requiresNsfwUnlock: true } : { selectors, requiresLocal: true };
    }
    for (const c of Omni.manifest.controls || []) {
        rules[c.id] = { selectors: [`#${c.id}-wrapper`], requiresLocal: c.access === 'local', showDisplay: c.show_display };
    }
    return rules;
})();

function isAccessAllowed(key) {
    const rule = ACCESS_RULES[key];
    if (!rule) return true;
    if (rule.requiresLocal && isRemoteClient) return false;
    if (rule.requiresNsfwUnlock && !isNsfwUnlocked) return false;
    return true;
}

// 按当前的 isRemoteClient / isNsfwUnlocked 重新过一遍权限表，该藏的藏、该露的露；
// 谁在改变这两个状态之一（NSFW 解锁/重新锁定、LAN 状态轮询），改完了都调一次这个函数。
function applyAccessRules() {
    for (const key in ACCESS_RULES) {
        const rule = ACCESS_RULES[key];
        const allowed = isAccessAllowed(key);
        rule.selectors.forEach(sel => {
            const el = document.querySelector(sel);
            if (el) el.style.display = allowed ? (rule.showDisplay || '') : 'none';
        });
    }
    // 当前正停留在一个刚变得不可见的分区/标签里：跳回安全位置，不留一个空列表页
    const listView = document.getElementById('list-view');
    if (ACCESS_RULES[currentTab] && !isAccessAllowed(currentTab) && listView && listView.style.display !== 'none') {
        showPortalView();
    }
    if (typeof activeMediaTab !== 'undefined' && ACCESS_RULES[activeMediaTab] && !isAccessAllowed(activeMediaTab)) {
        switchMediaTab((Omni.sections('media').find(s => s.default) || { id: 'docs' }).id);
    }
}

// 局域网/远程设备限定的分区显示/隐藏全部走 ACCESS_RULES/applyAccessRules()；
// 这两个函数现在只剩"表里没有的、remote-client 特有的杂项"：body 类名（驱动
// #manga-subtab-week 等另一批 CSS 规则）、搜索框占位文案、门面卡片上的数字徽章。
function applyRemoteClientRestrictions() {
    if (!isRemoteClient) return;
    document.body.classList.add('remote-client');   // 驱动 CSS 隐藏联网/下载类控件
    const mSearch = document.getElementById('manga-search-input');
    if (mSearch) mSearch.placeholder = '🔍 搜索本机已收录的漫画...';
    const nSearch = document.getElementById('novel-search-input');
    if (nSearch) nSearch.placeholder = '🔍 搜索本机已收录的小说...';
    applyAccessRules();
}

function removeRemoteClientRestrictions() {
    // Steam Deck 本机环境：彻底恢复独立大作卡片与专区原本的生机与互动能力
    document.body.classList.remove('remote-client');
    applyAccessRules();

    const standaloneBadgeEl = document.querySelector('.standalone-card .standalone-count');
    if (standaloneBadgeEl) standaloneBadgeEl.textContent = allGames.filter(g => g.type === 'standalone').length + ' Games';
    const flashBadgeEl = document.querySelector('.flash-card #flash-count-badge');
    if (flashBadgeEl) flashBadgeEl.textContent = allGames.filter(g => g.type === 'flash').length + ' Games';
    const sc2BadgeEl = document.querySelector('.sc2-card #sc2-count-badge');
    if (sc2BadgeEl) sc2BadgeEl.textContent = '离线对战';
}
