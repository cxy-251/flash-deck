"""
资源库（类似 Steam 游戏库）：一台机器可以登记多个库根目录（内置 SSD、SD 卡、移动硬盘……），
每个库都是同一套目录骨架，游戏和媒体资源只按「逻辑键」取路径，不关心具体在哪个盘。

    library.dirs("games.rpg")        # 所有在线库里存在的 rpg_games 目录（扫描/列表用）
    library.primary("media.manga")   # 默认库里的漫画目录（新下载/写入用）

LAYOUT 是库目录结构的唯一定义：加一个分类 = 在这里加一行；新库建骨架、「修复骨架」、
游戏扫描器遍历哪些目录，全部从这张表派生。

每个库根目录下有一个 omnilibrary.json 标记文件（库 id/名称），作用：
  • SD 卡换了挂载点也能按 id 认回来，自动修正库清单里的路径；
  • 库根目录不在（卡没插）时显示为离线，而不是从清单里消失。
"""
import glob
import json
import os
import shutil
import threading
import time
import uuid

from omni.core import settings

MARKER = "omnilibrary.json"
LAYOUT_VERSION = 1

# 逻辑键 -> 库根目录下的相对路径
LAYOUT = {
    # 游戏
    "games.rpg":     "standalone_games/rpg_games",
    "games.retro":   "standalone_games/retro_games",
    "games.slg":     "standalone_games/slg_games",
    "games.flash":   "standalone_games/flash_games",
    "games.steam":   "standalone_games/steam_games",
    "games.renpy":   "standalone_games/renpy_games",
    "games.unity":   "standalone_games/unity_games",
    "games.godot":   "standalone_games/godot_games",
    "games.unreal":  "standalone_games/unreal_games",
    "games.wine":    "standalone_games/wine_games",
    "games.3ds":     "standalone_games/3ds_games",
    "games.app":     "standalone_games/app_games",
    # 媒体
    "media.manga":             "media_library/manga",
    "media.novels":            "media_library/novels",
    "media.novels.standard":   "media_library/novels/standard",
    "media.novels.nsfw":       "media_library/novels/nsfw",
    "media.audio":             "media_library/audio",
    "media.audio.standard":    "media_library/audio/standard",
    "media.audio.nsfw":        "media_library/audio/nsfw",
    "media.shortvideo":        "media_library/shortvideo",
    "media.shortvideo.kuaishou": "media_library/shortvideo/快手",
    "media.shortvideo.douyin":   "media_library/shortvideo/抖音",
    "media.shortvideo.tiktok":   "media_library/shortvideo/TikTok",
    "media.docs":              "media_library/docs",
}

# 独立游戏专区的子分类（顺序即前端子标签顺序）
STANDALONE_CATEGORIES = ["steam", "renpy", "unity", "godot", "unreal", "wine", "3ds", "app"]

_lock = threading.RLock()


# --------------------------------------------------------------------------- 标记文件

def read_marker(root: str):
    try:
        with open(os.path.join(root, MARKER), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_marker(root: str, lib_id: str, label: str) -> None:
    data = read_marker(root) or {}
    data.update({"id": lib_id, "label": label, "layout_version": LAYOUT_VERSION})
    data.setdefault("created", time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(os.path.join(root, MARKER), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- 库清单

def _stored() -> list:
    libs = settings.load().get("libraries") or []
    return [dict(l) for l in libs if isinstance(l, dict) and l.get("path")]


def _save(libs: list, default_id=None) -> None:
    changes = {"libraries": libs}
    if default_id is not None:
        changes["default_library"] = default_id
    settings.update(changes)


def _relocate(lib: dict):
    """库根目录不在了：到 /run/media 下找带同 id 标记文件的目录（SD 卡换了挂载点的情况）。"""
    patterns = ["/run/media/*/*", "/run/media/*/*/*", "/media/*/*", "/media/*/*/*"]
    for pattern in patterns:
        for cand in glob.glob(os.path.join(pattern, MARKER)):
            marker = read_marker(os.path.dirname(cand))
            if marker and marker.get("id") == lib["id"]:
                return os.path.dirname(cand)
    return None


def libraries() -> list:
    """全部已登记的库（含离线的），按优先级排序：[{id, path, label, online, default}]。"""
    with _lock:
        libs = _stored()
        default_id = settings.load().get("default_library")
        changed = False
        out = []
        for lib in libs:
            path = os.path.expanduser(lib["path"])
            online = os.path.isdir(path)
            if not online:
                moved = _relocate(lib)
                if moved:
                    lib["path"], path, online, changed = moved, moved, True, True
            out.append({
                "id": lib["id"],
                "path": path,
                "label": lib.get("label") or os.path.basename(path.rstrip("/")),
                "online": online,
                "default": lib["id"] == default_id,
            })
        if changed:
            _save(libs)
        if out and not any(l["default"] for l in out):
            out[0]["default"] = True
        return out


def roots() -> list:
    """在线库的根目录（优先级顺序）。"""
    return [l["path"] for l in libraries() if l["online"]]


def default_library():
    libs = libraries()
    return next((l for l in libs if l["default"]), None)


def _rel(key: str) -> str:
    if key not in LAYOUT:
        raise KeyError(f"unknown library key: {key}")
    return LAYOUT[key]


def dirs(key: str, *sub: str) -> list:
    """所有在线库里「键对应目录/子路径」中真实存在的目录（优先级顺序，按真实路径去重）。"""
    out, seen = [], set()
    rel = _rel(key)
    for root in roots():
        cand = os.path.join(root, rel, *sub)
        if os.path.isdir(cand):
            real = os.path.realpath(cand)
            if real not in seen:
                seen.add(real)
                out.append(cand)
    return out


def candidates(key: str) -> list:
    """所有已登记库里该键对应的目录路径（不管存不存在，给目录变动监控用）。"""
    rel = _rel(key)
    return [os.path.join(l["path"], rel) for l in libraries()]


def primary(key: str, *sub: str) -> str:
    """默认库里该键对应的路径（新内容写入位置）；没有任何库时退回到 ~/Games/omni_library。"""
    lib = default_library()
    root = lib["path"] if lib else os.path.expanduser("~/Games/omni_library")
    return os.path.join(root, _rel(key), *sub)


def locate(abs_path: str):
    """反查：给一个绝对路径，返回 (库 dict, 逻辑键, 键下的相对路径)，不在任何库里返回 None。"""
    real = os.path.realpath(abs_path)
    best = None
    for lib in libraries():
        for key, rel in LAYOUT.items():
            base = os.path.realpath(os.path.join(lib["path"], rel))
            if real == base or real.startswith(base + os.sep):
                if best is None or len(base) > len(best[3]):
                    best = (lib, key, os.path.relpath(real, base), base)
    return best[:3] if best else None


# --------------------------------------------------------------------------- 骨架

def plan_skeleton(root: str) -> list:
    """该库根目录下还缺哪些骨架目录（相对路径列表）。"""
    root = os.path.expanduser(root)
    return [rel for rel in sorted(set(LAYOUT.values())) if not os.path.isdir(os.path.join(root, rel))]


def ensure_skeleton(root: str) -> list:
    """补齐缺失的骨架目录（只建空目录，绝不动已有文件），返回新建的相对路径列表。"""
    root = os.path.expanduser(root)
    created = []
    for rel in plan_skeleton(root):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
        created.append(rel)
    return created


def mount_points() -> list:
    """可移动存储的挂载点（SD 卡、U 盘……），给目录选择器当快捷入口。"""
    out = []
    for base in ("/run/media", "/media"):
        for mount in sorted(glob.glob(os.path.join(base, "*", "*"))):
            if os.path.isdir(mount):
                out.append(mount)
    return out


# --------------------------------------------------------------------------- 管理操作

def add(path: str, label: str = None, make_default: bool = False) -> dict:
    """登记一个新库：建根目录与骨架、写标记文件。已登记的路径不会重复添加。"""
    with _lock:
        path = os.path.abspath(os.path.expanduser(path.strip()))
        if not path or path == "/":
            raise ValueError("无效的路径")
        libs = _stored()
        for lib in libs:
            if os.path.realpath(os.path.expanduser(lib["path"])) == os.path.realpath(path):
                raise ValueError("这个目录已经是资源库了")
        marker = read_marker(path) if os.path.isdir(path) else None
        lib_id = (marker or {}).get("id") or uuid.uuid4().hex[:8]
        if any(l["id"] == lib_id for l in libs):
            lib_id = uuid.uuid4().hex[:8]
        label = (label or (marker or {}).get("label") or os.path.basename(path.rstrip("/")) or "资源库").strip()
        os.makedirs(path, exist_ok=True)
        created = ensure_skeleton(path)
        _write_marker(path, lib_id, label)
        libs.append({"id": lib_id, "path": path, "label": label})
        default_id = lib_id if (make_default or len(libs) == 1) else None
        _save(libs, default_id)
        return {"id": lib_id, "path": path, "label": label, "created": created}


def remove(lib_id: str) -> None:
    """只从清单里注销（不删除任何文件，标记文件也保留，重新添加时能认回同一个 id）。"""
    with _lock:
        libs = [l for l in _stored() if l["id"] != lib_id]
        default_id = settings.load().get("default_library")
        _save(libs, (libs[0]["id"] if libs else "") if default_id == lib_id else None)


def set_default(lib_id: str) -> None:
    if not any(l["id"] == lib_id for l in _stored()):
        raise ValueError("没有这个资源库")
    settings.update({"default_library": lib_id})


def rename(lib_id: str, label: str) -> None:
    with _lock:
        libs = _stored()
        for lib in libs:
            if lib["id"] == lib_id:
                lib["label"] = label.strip() or lib.get("label")
                path = os.path.expanduser(lib["path"])
                if os.path.isdir(path):
                    _write_marker(path, lib_id, lib["label"])
        _save(libs)


def reorder(ids: list) -> None:
    with _lock:
        libs = _stored()
        order = {i: n for n, i in enumerate(ids)}
        libs.sort(key=lambda l: order.get(l["id"], len(order)))
        _save(libs)


def repair(lib_id: str) -> list:
    lib = next((l for l in libraries() if l["id"] == lib_id), None)
    if not lib or not lib["online"]:
        raise ValueError("资源库不在线")
    created = ensure_skeleton(lib["path"])
    _write_marker(lib["path"], lib["id"], lib["label"])
    return created


def _count_entries(path: str) -> int:
    try:
        return sum(1 for e in os.scandir(path) if not e.name.startswith("."))
    except OSError:
        return 0


def status() -> list:
    """库管理页面用：每个库的在线状态、容量、各分类条目数、缺失的骨架目录。"""
    out = []
    for lib in libraries():
        item = dict(lib)
        if lib["online"]:
            try:
                du = shutil.disk_usage(lib["path"])
                item["disk"] = {"total": du.total, "used": du.used, "free": du.free}
            except OSError:
                item["disk"] = None
            item["counts"] = {key: _count_entries(os.path.join(lib["path"], rel))
                              for key, rel in LAYOUT.items() if key.startswith("games.")}
            item["missing"] = plan_skeleton(lib["path"])
        out.append(item)
    return out


def duplicates(game_keys=None) -> list:
    """同名游戏目录出现在多个库里的情况：[{key, name, paths}]（排在前面的库生效）。"""
    keys = game_keys or [k for k in LAYOUT if k.startswith("games.")]
    found = []
    for key in keys:
        seen = {}
        for d in dirs(key):
            try:
                names = [e.name for e in os.scandir(d) if e.is_dir() and not e.name.startswith(".")]
            except OSError:
                continue
            for n in names:
                seen.setdefault(n, []).append(os.path.join(d, n))
        found += [{"key": key, "name": n, "paths": p} for n, p in sorted(seen.items()) if len(p) > 1]
    return found
