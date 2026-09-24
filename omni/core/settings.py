"""
统一配置：所有「跟这台机器/这个人绑定」的设置都在 var/config/settings.json 这一个文件里，
应用内的「设置 → 存储与游戏库」页面读写的也是它，改完立即生效（按 mtime 自动重载）。

DEFAULTS 是全部配置项的唯一定义处（含默认值与说明）；新增配置项 = 在 DEFAULTS 里加一行，
用的地方 `settings.get("xxx")`，不要在业务模块里另写默认值或 expanduser(...)。

资源库清单（libraries）也存在这里，但读写请走 omni.core.library，那边负责校验、建骨架。
"""
import copy
import json
import os
import threading

from omni.core import paths

DEFAULTS = {
    # 资源库清单：[{id, path, label}]，顺序即扫描优先级；default_library 是新内容写入的库。
    "libraries": [],
    "default_library": None,
    # 收件箱：浏览器/MEGA/短视频插件的原始下载落点，不是资源库，不参与游戏/媒体扫描。
    "inbox_dir": "~/Downloads",
    # 资源库之外、需要单独登记的游戏/应用（例如装在 Proton 容器里的程序）。
    #   [{id, path, category, name?, icon?, exe?}]，category 取独立游戏子分类（app/wine/...）
    "external_games": [],
    # 外部工具的位置
    "tools": {
        "renpy_sdk": "~/Applications/renpy-8.5.3-sdk/renpy.sh",
        "lime3ds_dir": "~/Applications/Lime3DS",
        "mega_cmd_dir": "~/Applications/mega-cmd",
        "uvx": "~/.local/bin/uvx",
        "sc2_dir": "~/Games/StarCraft II",
        "sc2mod_dir": "~/Games/claude/omniMod/sc2Mod",
        "steam_root": "~/.local/share/Steam",
        "proton_prefix": "~/.local/share/omni_deck_pfx",
        "cloudflared_config": "~/.cloudflared/config.yml",
    },
    # Cloudflare 广域网隧道域名；None = 不启用广域网访问。
    "wan_domain": None,
    # NSFW 内容锁的初始密码（仅在还没设置过密码时生效，首次解锁后请在应用里改掉）。
    "nsfw_default_password": "changeme",
    # 伪装压缩包游戏（.mp4/.mkv 里塞了加密 7z）的解压密码。
    "archive_extract_password": "changeme",
    # 内存看门狗：主进程+Chromium 子进程 RSS 合计超过它(MB)就在空闲时自重启。
    "mem_restart_mb": 4500,
}

_lock = threading.RLock()
_cache = None
_cache_mtime = None


def _expand(value):
    return os.path.expanduser(value) if isinstance(value, str) and value.startswith("~") else value


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
    """用户填写/配置里的路径（可能带 ~）-> 绝对路径。"""
    return os.path.abspath(os.path.expanduser((value or "").strip())) if value else ""


def get(key: str, default=None):
    """顶层配置项（字符串值里的 ~ 会展开）。"""
    value = load().get(key, default)
    return _expand(value)


def tool(name: str) -> str:
    """外部工具路径（tools.<name>，~ 已展开）。"""
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
