"""
静态文件白名单：只有这里列出的 URL 能映射到磁盘文件——前端页面、第三方前端库、模拟器/Flash 运行时。
游戏与媒体资源走各自功能模块的路由（按游戏 id / 媒体路径解析），不经过这里。

以前没匹配上的请求会落到 SimpleHTTPRequestHandler 默认行为，把整个项目目录（含配置、源码）
当静态目录对外提供；现在不在白名单里一律 404。
"""
import os

from omni.core import paths
from omni.core.vfs import resolve_case_insensitive_path

W = paths.WEB

# 精确路径 -> 文件（含旧 URL 别名，保持书签、缓存页面与局域网设备可用）
EXACT = {
    "/": os.path.join(W, "hub.html"),
    "/hub.html": os.path.join(W, "hub.html"),
    "/hub.js": os.path.join(W, "hub.js"),
    "/assets/hub.js": os.path.join(W, "hub.js"),
    "/marked.min.js": os.path.join(W, "vendor", "marked.min.js"),
    "/mermaid.min.js": os.path.join(W, "vendor", "mermaid.min.js"),
    "/player_retro.html": os.path.join(W, "players", "retro.html"),
    "/player_flash.html": os.path.join(W, "players", "flash.html"),
}

# 前缀 -> 候选根目录（按顺序找第一个存在的）；vfs=True 走大小写不敏感解析
PREFIXES = [
    ("/web/", [W], False),
    ("/assets/ruffle/", [paths.RUFFLE], False),
    ("/assets/", [os.path.join(W, "vendor"), W], False),
    ("/ruffle/", [paths.RUFFLE], False),
    ("/plugins/ruffle/", [paths.RUFFLE], False),
    ("/plugins/", [paths.PEPFLASH], False),
    ("/emulatorjs/", [paths.EMULATORJS], True),
]


def _inside(root, target):
    root = os.path.realpath(root)
    target = os.path.realpath(target)
    return target == root or target.startswith(root + os.sep)


def resolve(path: str):
    """请求路径（已 unquote、无 query）-> 磁盘文件路径；不在白名单里返回 None。"""
    if path in EXACT:
        return EXACT[path]
    for prefix, roots, vfs in PREFIXES:
        if path.startswith(prefix):
            rel = path[len(prefix):]
            if not rel or ".." in rel.split("/"):
                return None
            found = None
            for root in roots:
                cand = resolve_case_insensitive_path(root, rel) if vfs else os.path.join(root, rel)
                if _inside(root, cand) and os.path.isfile(cand):
                    return cand
                found = found or (cand if _inside(root, cand) else None)
            return found
    return None
