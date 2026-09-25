"""
统一配置：所有「跟这台机器/这个人绑定」的设置都在 var/config/settings.json 这一个文件里，
路径值可以写成 "{games}/xxx" 的形式（基础目录在 dirs 里定义一次，resolve() 负责展开），
应用内的「设置 → 存储与游戏库」页面读写的也是它，改完立即生效（按 mtime 自动重载）。

DEFAULTS 是全部配置项的唯一定义处（含默认值与说明）；新增配置项 = 在 DEFAULTS 里加一行，
用的地方 `settings.get("xxx")`，不要在业务模块里另写默认值或 expanduser(...)。

资源库清单（libraries）也存在这里，但读写请走 omni.core.library，那边负责校验、建骨架。
"""
import copy
import json
import os
import re
import threading

from omni.core import paths

DEFAULTS = {
    # 基础目录：其它路径写成 "{games}/omni_library" 这种形式，由 resolve() 展开——挪动某个基础目录只改这里一处。
    # 可以自己加（例如 "sd": "/run/media/deck/<卷标>"），在应用里添加路径时会自动换成最长匹配的占位形式。
    "dirs": {
        "home": "~",
        "apps": "{home}/Applications",
        "games": "{home}/Games",
        "steam": "{home}/.local/share/Steam",
    },
    # 资源库清单：[{id, path, label}]，顺序即扫描优先级；default_library 是新内容写入的库。
    "libraries": [],
    "default_library": None,
    # 收件箱：浏览器/MEGA/短视频插件的原始下载落点，不是资源库，不参与游戏/媒体扫描。
    "inbox_dir": "{home}/Downloads",
    # 资源库之外、需要单独登记的游戏/应用（例如装在 Proton 容器里的程序）。
    #   [{id, path, category, name?, icon?, exe?}]，category 取独立游戏子分类（app/wine/...）
    "external_games": [],
    # 外部工具的位置
    "tools": {
        "renpy_sdk": "{apps}/renpy-8.5.3-sdk/renpy.sh",
        "lime3ds_dir": "{apps}/Lime3DS",
        "mega_cmd_dir": "{apps}/mega-cmd",
        "uvx": "{home}/.local/bin/uvx",
        "sc2_dir": "{games}/StarCraft II",
        "sc2mod_dir": "{games}/claude/omniMod/sc2Mod",
        "steam_root": "{steam}",
        "proton_prefix": "{home}/.local/share/omni_deck_pfx",
        "cloudflared_config": "{home}/.cloudflared/config.yml",
    },
    # 外部站点根地址的覆盖（键见 omni/core/endpoints.py 的 DEFAULTS），换域名/镜像时填这里。
    "endpoints": {},
    # Cloudflare 广域网隧道域名；None = 不启用广域网访问。
    "wan_domain": None,
    # NSFW 内容锁的初始密码（仅在还没设置过密码时生效，首次解锁后请在应用里改掉）。
    "nsfw_default_password": "changeme",
    # 伪装压缩包游戏（.mp4/.mkv 里塞了加密 7z）的解压密码。
    "archive_extract_password": "changeme",
    # 内存看门狗：主进程+Chromium 子进程 RSS 合计超过它(MB)就在空闲时自重启。
    "mem_restart_mb": 4500,
}

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

_lock = threading.RLock()
_cache = None
_cache_mtime = None


def resolve(value):
    """把字符串里的 {基础目录} 占位与开头的 ~ 展开成真实路径；不认识的占位原样保留
    （比如任务文件里的 {tasks}、{url:键} 由各自的调用方处理）。非字符串原样返回。"""
    if not isinstance(value, str):
        return value
    dirs = load().get("dirs") or {}
    for _ in range(8):                      # 基础目录之间可以互相引用（apps -> {home}/Applications）
        new = _PLACEHOLDER.sub(lambda m: dirs.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return os.path.expanduser(value) if value.startswith("~") else value


def compact(path: str) -> str:
    """resolve 的反向：绝对路径 -> 用最长匹配的基础目录写成占位形式（存配置时用，方便以后整体挪动）。"""
    if not isinstance(path, str) or not path:
        return path
    real = os.path.abspath(os.path.expanduser(path))
    best = None
    for name in (load().get("dirs") or {}):
        base = os.path.abspath(resolve("{%s}" % name))
        if base == os.path.abspath(os.sep):
            continue
        if real == base or real.startswith(base + os.sep):
            if best is None or len(base) > len(best[1]):
                best = (name, base)
    if not best:
        return real
    rest = real[len(best[1]):]
    return "{%s}%s" % (best[0], rest)


_expand = resolve


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    """完整配置（默认值 + settings.json 覆盖），文件没变就用缓存。"""
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = os.path.getmtime(paths.SETTINGS_FILE)
        except OSError:
            mtime = None
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        stored = {}
        if mtime is not None:
            try:
                with open(paths.SETTINGS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f) or {}
            except Exception:
                stored = {}
        _cache = _merge(DEFAULTS, stored)
        _cache_mtime = mtime
        return _cache


def user_path(value: str) -> str:
    """用户填写/配置里的路径（可能带 ~ 或 {基础目录}）-> 绝对路径。"""
    return os.path.abspath(resolve((value or "").strip())) if value else ""


def get(key: str, default=None):
    """顶层配置项（字符串值里的 ~ 与 {基础目录} 会展开）。"""
    value = load().get(key, default)
    return _expand(value)


def tool(name: str) -> str:
    """外部工具路径（tools.<name>，占位已展开）。"""
    return _expand(load()["tools"].get(name) or DEFAULTS["tools"].get(name))


def update(changes: dict) -> dict:
    """合并写入若干配置项（原子写），返回写入后的完整配置。"""
    global _cache, _cache_mtime
    with _lock:
        stored = {}
        if os.path.exists(paths.SETTINGS_FILE):
            try:
                with open(paths.SETTINGS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f) or {}
            except Exception:
                stored = {}
        stored = _merge(stored, changes)
        os.makedirs(paths.CONFIG, exist_ok=True)
        tmp = paths.SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SETTINGS_FILE)
        _cache = None
        _cache_mtime = None
    return load()
