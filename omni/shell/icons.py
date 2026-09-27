"""
icons.py - 本机原生控件的图标（Material Symbols Rounded，跟网页 web/ui/icons.js 读同一份 SVG）

SVG 在 web/vendor/icons/；渲染前把颜色填进 <svg fill="…">，按 (名字, 颜色, 尺寸) 缓存成 QIcon。
按钮统一用 set_icon()：去掉文字、设图标与图标尺寸。
"""
import os
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton

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
