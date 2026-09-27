"""
icons.py - 本机原生控件的图标（Material Symbols Rounded，跟网页 web/ui/icons.js 读同一份 SVG）

SVG 在 web/vendor/icons/；渲染前把颜色填进 <svg fill="…">，按 (名字, 颜色, 尺寸) 缓存成 QIcon。
按钮统一用 set_icon()：去掉文字、设图标与图标尺寸。
install_tips()：悬停 0.25 秒就在按钮正下方弹出说明气泡（文字取按钮的 toolTip），
比 Qt 默认的 0.7 秒快，位置也固定，不跟着鼠标跑。气泡样式见 TIP_QSS。
"""
import os
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QEvent, QObject, QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton, QToolTip, QWidget

from omni.core import paths

ICON_DIR = os.path.join(paths.WEB, "vendor", "icons")

FG = "#e6edf3"        # 默认图标色
ACCENT = "#58a6ff"    # 开着的开关（随机、固定、焦点出声…）
AUDIO = "#d2a8ff"     # 音声那一组
LIKE = "#ff4d6d"      # 已点赞


@lru_cache(maxsize=256)
def icon(name: str, color: str = FG, size: int = 24) -> QIcon:
    """name 是 web/vendor/icons/ 下的文件名（不带 .svg），比如 play_arrow-fill。"""
    try:
        with open(os.path.join(ICON_DIR, name + ".svg"), "r", encoding="utf-8") as f:
            svg = f.read()
    except OSError:
        return QIcon()
    svg = svg.replace("<svg ", f'<svg fill="{color}" ', 1)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = QPixmap(size * 2, size * 2)          # 2 倍渲染，高分屏 / 缩放下也清楚
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    renderer.render(painter)
    painter.end()
    px.setDevicePixelRatio(2)
    return QIcon(px)


def set_icon(btn: QAbstractButton, name: str, color: str = FG, size: int = 22, text: str = "") -> None:
    """按钮换成图标（可带一小段文字，比如倍速 1.5x、定时剩余分钟）。"""
    btn.setIcon(icon(name, color, size))
    btn.setIconSize(QSize(size, size))
    btn.setText(text)


# 气泡样式：拼进各播放器自己的样式表（QToolTip 会继承弹出它的控件那棵树上的样式表）
TIP_QSS = """
    QToolTip { color:#e6edf3; background:#1f242c; border:1px solid #3a414b; border-radius:6px;
               padding:4px 8px; font-size:12px; }
"""


class _TipFilter(QObject):
    """装在按钮上：Enter 后 250ms 在按钮下方显示 toolTip；Leave / 点击就收；吞掉 Qt 自己那个慢半拍的气泡。"""

    def __init__(self):
        super().__init__()
        self._target = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._show)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._target = obj
            self._timer.start()
        elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
            self._timer.stop()
            if obj is self._target:
                QToolTip.hideText()
        elif t == QEvent.Type.ToolTip:
            return True
        return False

    def _show(self):
        w = self._target
        if w is not None and w.isVisible() and w.toolTip():
            QToolTip.showText(w.mapToGlobal(QPoint(0, w.height() + 6)), w.toolTip(), w)


_TIPS = None


def install_tips(root: QWidget) -> None:
    """root 下所有按钮都用快速气泡（后面新建的按钮要再调一次）。"""
    global _TIPS
    if _TIPS is None:
        _TIPS = _TipFilter()
    for b in root.findChildren(QAbstractButton):
        b.installEventFilter(_TIPS)
