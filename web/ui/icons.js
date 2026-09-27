// 播放器图标：Material Symbols Rounded（web/vendor/icons/，本机 Qt 的 omni/shell/icons.py 读同一份）。
// 用 CSS mask 画，颜色跟随 currentColor——按钮文字是什么颜色，图标就是什么颜色。
//   HTML 里写 <button data-icon="play_arrow-fill"></button>，启动时 hydrateIcons() 统一换成图标；
//   JS 里状态变了用 setIcon(el, 'pause-fill')，可带一小段文字 setIcon(el, 'bedtime-fill', '30')。
// 带图标的按钮悬停 0.25 秒弹出说明气泡（文字取 title，挪到 data-tip，免得浏览器自己的慢气泡也冒出来）。

const ICON_BASE = '/web/vendor/icons/';

function icon(name) {
    return `<span class="ico" style="--ico:url('${ICON_BASE}${name}.svg')"></span>`;
}

function setIcon(el, name, text) {
    if (!el) return;
    el.dataset.icon = name;
    el.innerHTML = icon(name) + (text ? `<span class="ico-text">${escapeHtml(String(text))}</span>` : '');
}

function hydrateIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(el => {
        if (!el.querySelector('.ico')) setIcon(el, el.dataset.icon, el.dataset.iconText);
    });
}

// ---- 图标按钮的说明气泡 ----
let omniTipEl = null;
let omniTipTimer = 0;

function showOmniTip(btn, text) {
    if (!document.body.contains(btn)) return;
    if (!omniTipEl) {
        omniTipEl = document.createElement('div');
        omniTipEl.className = 'omni-tip';
        document.body.appendChild(omniTipEl);
    }
    omniTipEl.textContent = text;
    omniTipEl.style.display = 'block';
    const r = btn.getBoundingClientRect(), t = omniTipEl.getBoundingClientRect();
    const below = r.bottom + 6 + t.height < window.innerHeight;
    const left = Math.max(6, Math.min(window.innerWidth - t.width - 6, r.left + r.width / 2 - t.width / 2));
    omniTipEl.style.left = `${left}px`;
    omniTipEl.style.top = `${below ? r.bottom + 6 : r.top - t.height - 6}px`;
}

function hideOmniTip() {
    clearTimeout(omniTipTimer);
    if (omniTipEl) omniTipEl.style.display = 'none';
}

document.addEventListener('mouseover', (e) => {
    const btn = e.target.closest && e.target.closest('button, summary, [data-icon]');
    if (!btn || !btn.querySelector('.ico')) return;
    const title = btn.getAttribute('title');
    if (title) { btn.dataset.tip = title; btn.removeAttribute('title'); }   // JS 之后再改 title，下次悬停会重新挪过来
    if (!btn.dataset.tip) return;
    clearTimeout(omniTipTimer);
    omniTipTimer = setTimeout(() => showOmniTip(btn, btn.dataset.tip), 250);
});
document.addEventListener('mouseout', (e) => { if (e.target.closest && e.target.closest('button, summary, [data-icon]')) hideOmniTip(); });
document.addEventListener('mousedown', hideOmniTip, true);
window.addEventListener('scroll', hideOmniTip, true);
