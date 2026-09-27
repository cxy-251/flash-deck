// 播放器图标：Material Symbols Rounded（web/vendor/icons/，本机 Qt 的 omni/shell/icons.py 读同一份）。
// 用 CSS mask 画，颜色跟随 currentColor——按钮文字是什么颜色，图标就是什么颜色。
//   HTML 里写 <button data-icon="play_arrow-fill"></button>，启动时 hydrateIcons() 统一换成图标；
//   JS 里状态变了用 setIcon(el, 'pause-fill')，可带一小段文字 setIcon(el, 'bedtime-fill', '30')。

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
