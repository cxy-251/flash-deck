"""
v2 → v3 状态迁移：每次启动最先运行（此时 Chromium 还没起，搬浏览器 profile 是安全的），
每一步都是幂等的——源不存在就跳过，所以迁移完成后它什么也不做。

  • 散落在项目目录各处的状态 → var/（config / data / cache / logs 四类）
  • services/local_settings.py + 旧环境变量 → var/config/settings.json
  • 旧 LIBRARY_ROOTS 里的资源库 → 库清单 + 库标记文件 + 补齐目录骨架
"""
import glob
import json
import os
import runpy
import shutil

from omni.core import paths

R = paths.REPO
LEGACY_CACHE = os.path.join(R, "cache")
_MOVES = [
    (os.path.join(R, "config", "privacy_config.json"), paths.PRIVACY_FILE),
    (os.path.join(R, "cookies.txt"), paths.COOKIES_TXT),
    (os.path.join(R, "data", "storage"), paths.WEBENGINE_PROFILE),
    (os.path.join(paths.WEBENGINE_PROFILE, "shortvideo_likes.json"), paths.SHORTVIDEO_LIKES),
    (os.path.join(LEGACY_CACHE, "engine_cache"), paths.ENGINE_CACHE),
    (os.path.join(LEGACY_CACHE, "flash_cache"), paths.FLASH_CACHE),
    (os.path.join(LEGACY_CACHE, "thumbs"), paths.THUMBS),
    (os.path.join(LEGACY_CACHE, "shortvideo_webm"), paths.SHORTVIDEO_WEBM),
    (os.path.join(LEGACY_CACHE, "media_index.db"), paths.MEDIA_INDEX_DB),
    (os.path.join(LEGACY_CACHE, "media_index.db-wal"), paths.MEDIA_INDEX_DB + "-wal"),
    (os.path.join(LEGACY_CACHE, "media_index.db-shm"), paths.MEDIA_INDEX_DB + "-shm"),
    (os.path.join(paths.HOME, ".cache", "omni_manga_covers"), paths.MANGA_COVERS),
    (os.path.join(paths.HOME, ".cache", "sc2mod", "thumbs_v3"), os.path.join(paths.CACHE, "sc2_thumbs_v3")),
]
_GLOB_MOVES = [
    (os.path.join(LEGACY_CACHE, "shortvideo_list_*.json"), paths.CACHE),
    (os.path.join(LEGACY_CACHE, "game_*.log"), paths.GAME_LOGS),
    (os.path.join(LEGACY_CACHE, "omni_deck.log*"), paths.LOGS),
    (os.path.join(LEGACY_CACHE, "boot.log"), paths.LOGS),
    (os.path.join(LEGACY_CACHE, "flash_crash.log*"), paths.LOGS),
    (os.path.join(LEGACY_CACHE, "shortvideo_player.log"), paths.LOGS),
    (os.path.join(LEGACY_CACHE, "manga_batch_failures.log"), paths.LOGS),
]
# 旧版在 ~/Games 下逐个目录注册成「Windows 软件」，这些名字当时是排除掉的
_LEGACY_APP_EXCLUDES = {"omni-deck", "StarCraft II", "Battle.net", "claude", "rpg_games",
                        "standalone_games", "media_library", "omni_library"}
_LEGACY_APP_META = {
    "Weiyun": {"name": "腾讯微云 (Tencent Weiyun)", "proton_appid": "3498387003",
               "args": ["--no-sandbox", "--disable-gpu-sandbox"]},
    "Battle.net": {"proton_appid": "2415561907"},
}


def _move(src, dst):
    """src → dst；dst 已存在且是目录时逐项合并（已存在的同名项保留 dst 的）。"""
    if not os.path.lexists(src):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.lexists(dst):
        shutil.move(src, dst)
        return
    if os.path.isdir(src) and os.path.isdir(dst) and not os.path.islink(src):
        for name in os.listdir(src):
            _move(os.path.join(src, name), os.path.join(dst, name))
        try:
            os.rmdir(src)
        except OSError:
            pass


def _migrate_state():
    for src, dst in _MOVES:
        _move(src, dst)
    for pattern, dst_dir in _GLOB_MOVES:
        for src in glob.glob(pattern):
            _move(src, os.path.join(dst_dir, os.path.basename(src)))
    lan_f = os.path.join(R, "config", ".lan_config.json")
    wan_f = os.path.join(R, "config", ".wan_config.json")
    if (os.path.exists(lan_f) or os.path.exists(wan_f)) and not os.path.exists(paths.NETWORK_FILE):
        state = {}
        for key, f in (("lan", lan_f), ("wan", wan_f)):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    state[key] = bool(json.load(fh).get("enabled", False))
            except Exception:
                pass
        os.makedirs(paths.CONFIG, exist_ok=True)
        with open(paths.NETWORK_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    for f in (lan_f, wan_f):
        if os.path.exists(f) and os.path.exists(paths.NETWORK_FILE):
            os.remove(f)


def _looks_like_library(root):
    from omni.core import library
    return (os.path.isdir(os.path.join(root, "standalone_games"))
            or os.path.isdir(os.path.join(root, "media_library"))
            or library.read_marker(root) is not None)


def _legacy_external_apps(games_dir, library_roots):
    from omni.features.games.registry import find_best_executable
    out = []
    if not os.path.isdir(games_dir):
        return out
    real_roots = {os.path.realpath(r) for r in library_roots}
    for name in sorted(os.listdir(games_dir)):
        path = os.path.join(games_dir, name)
        if (name in _LEGACY_APP_EXCLUDES or name.startswith(".") or not os.path.isdir(path)
                or os.path.realpath(path) in real_roots or os.path.islink(path)):
            continue
        if find_best_executable(path, "app"):
            out.append({"id": name, "path": path, "category": "app", **_LEGACY_APP_META.get(name, {})})
    return out


def _migrate_settings():
    """首次运行 v3：从 services/local_settings.py 与旧环境变量生成 settings.json，并登记资源库。"""
    if os.path.exists(paths.SETTINGS_FILE):
        return
    from omni.core import library, settings

    legacy = {}
    legacy_file = os.path.join(R, "services", "local_settings.py")
    if os.path.exists(legacy_file):
        try:
            legacy = runpy.run_path(legacy_file)
        except Exception:
            legacy = {}

    roots = [os.path.expanduser(r) for r in legacy.get("LIBRARY_ROOTS") or [] if isinstance(r, str)]
    lib_roots = [r for r in roots if _looks_like_library(r)]
    other_roots = [r for r in roots if r not in lib_roots]

    changes = {"tools": {}}
    if legacy.get("WAN_DOMAIN"):
        changes["wan_domain"] = legacy["WAN_DOMAIN"]
    for key, legacy_key in (("nsfw_default_password", "NSFW_DEFAULT_PASSWORD"),
                            ("archive_extract_password", "ARCHIVE_EXTRACT_PASSWORD")):
        if legacy.get(legacy_key):
            changes[key] = legacy[legacy_key]
    if legacy.get("MEGA_APP_DIR"):
        changes["tools"]["mega_cmd_dir"] = legacy["MEGA_APP_DIR"]
    for env, tool in (("RENPY_SDK_PATH", "renpy_sdk"), ("SC2_DIR", "sc2_dir"), ("SC2MOD_DIR", "sc2mod_dir")):
        if os.environ.get(env):
            changes["tools"][tool] = os.environ[env]
    inbox = os.environ.get("OMNI_DOWNLOAD_DIR") or next(
        (r for r in other_roots if os.path.basename(r.rstrip("/")) == "Downloads"), None)
    if inbox:
        changes["inbox_dir"] = inbox
    if os.environ.get("OMNI_MEM_RESTART_MB"):
        changes["mem_restart_mb"] = int(os.environ["OMNI_MEM_RESTART_MB"])
    changes["external_games"] = _legacy_external_apps(
        os.environ.get("OMNI_GAMES_DIR") or os.path.join(paths.HOME, "Games"), lib_roots)
    settings.update(changes)

    labels = {0: "内置存储"}
    for i, root in enumerate(lib_roots):
        label = labels.get(i) or ("SD 卡" if root.startswith(("/run/media/", "/media/")) else os.path.basename(root))
        try:
            library.add(root, label, make_default=(i == 0))
        except ValueError:
            pass


def run():
    os.makedirs(paths.STATE, exist_ok=True)
    # 用 OMNI_STATE_DIR 指定了别的状态目录（测试/多实例）时，只生成配置，不去搬项目目录里
    # 的旧状态——那些文件可能正被另一个在跑的实例（比如旧版本）使用着。
    if not os.environ.get("OMNI_STATE_DIR"):
        _migrate_state()
    _migrate_settings()
