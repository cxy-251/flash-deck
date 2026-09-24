"""
游戏注册表：扫描所有资源库里的游戏目录，按引擎识别入口文件，生成大厅用的游戏清单。

每个游戏目录可以放一个 omni.json 元数据文件（全部字段可选）：
    {
      "name":  "012 - 缺氧 (Oxygen Not Included)",   # 显示名，缺省用文件夹名
      "hidden": false,                                # true = 不出现在大厅
      "icon":  "cover.png",                           # 相对游戏目录，缺省按常见文件名找
      "exe":   "bin/Game.x86_64",                     # 独立游戏主程序，缺省自动挑选
      "args":  ["-nosound"],                          # 追加的启动参数
      "env":   {"KEY": "VALUE"},                      # 追加的环境变量
      "proton_appid": "3498387003"                    # 使用该 Steam compatdata 容器运行 .exe
    }
Flash 目录兼容旧的 info.json（type=web_flash / url / hint）。
资源库之外的游戏/应用登记在 settings.json 的 external_games 里，字段同上外加 path/category/id。
"""
import json
import os
import threading
import urllib.parse

from omni.core import library, settings

REGISTRY = {}
META_FILE = "omni.json"

DEFAULT_SVG_ICON = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect width="100" height="100" rx="20" fill="#1c2128"/>
  <path d="M30 40h40v20H30z" fill="#58a6ff"/>
  <circle cx="50" cy="50" r="15" fill="#388bfd"/>
</svg>'''

ROM_EXTENSIONS = {
    ".cue": "psx", ".chd": "psx", ".pbp": "psx", ".iso": "psx",
    ".gba": "gba", ".gbc": "gb", ".gb": "gb", ".nds": "nds", ".nes": "nes",
    ".sfc": "snes", ".smc": "snes", ".z64": "n64", ".n64": "n64", ".v64": "n64",
    ".md": "segaMD", ".zip": "arcade", ".bin": "segaMD",
}

# 常见大作的主程序名：自动挑选可执行文件时直接加权
KNOWN_MAIN_EXES = {
    "oxygennotincluded", "dontstarve", "dontstarve_steam_x64.exe", "dspgame.exe", "deadcells.exe",
    "factorio.exe", "davethediver.exe", "descenders.exe", "rimworldwin64.exe", "vampiresurvivors.exe",
    "thronefall.exe", "sandustry.exe", "bloonstd6.exe", "cult of the lamb.exe", "eurotrucks2.exe",
    "hades2.exe", "hoi4.exe", "silksong.exe", "hollow_knight.exe", "nms.exe", "palworld.exe",
    "shapez2.exe", "stellaris.exe",
}
BAD_EXE_WORDS = ["crashhandler", "crashpad", "reipatcher", "setup", "uninstall", "ueprereqsetup", "config",
                 "エンジン設定", "vcredist", "dxredist", "redist", "directx", "elevate", "oalinst", "openal",
                 "dotnet", "vc_redist"]

_scan_lock = threading.Lock()
_last_sig = None


# --------------------------------------------------------------------------- 元数据

def read_meta(folder: str) -> dict:
    try:
        with open(os.path.join(folder, META_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _icon(folder: str, meta: dict, candidates) -> str:
    if meta.get("icon"):
        p = os.path.join(folder, meta["icon"])
        if os.path.exists(p):
            return p
    return next((os.path.join(folder, c) for c in candidates if os.path.exists(os.path.join(folder, c))), None)


def _entry(game_id, folder, meta, **fields) -> dict:
    entry = {"id": game_id, "name": meta.get("name") or game_id}
    entry.update(fields)
    for k in ("args", "env", "proton_appid"):
        if meta.get(k):
            entry[k] = meta[k]
    return entry


# --------------------------------------------------------------------------- 各引擎识别

def register_rpg(folder, game_id, meta):
    for sub in ("", "www", os.path.join("data", "www")):
        www = os.path.join(folder, sub) if sub else folder
        if os.path.exists(os.path.join(www, "index.html")):
            save_dir = os.path.join(www, "save")
            os.makedirs(save_dir, exist_ok=True)
            icon = os.path.join(www, "icon", "icon.png")
            icon = _icon(folder, meta, []) or (icon if os.path.exists(icon) else None)
            return _entry(game_id, folder, meta, type="rpg", root=www, save_dir=save_dir, icon=icon)
    return None


def find_best_executable(folder, subcategory):
    """递归挑选最可能的主执行文件（中文版、便携版、Linux 原生优先）。"""
    candidates = []

    def walk(max_depth):
        for root, _dirs, files in os.walk(folder):
            depth = os.path.relpath(root, folder).count(os.sep)
            if depth > max_depth:
                continue
            for f in files:
                yield depth, f, f.lower(), os.path.join(root, f)

    if subcategory == "app":
        for depth, _f, fl, full in walk(2):
            if "battle.net launcher.exe" in fl or "battle.net.exe" in fl or "weiyunapp.exe" in fl:
                return full
            if fl.endswith(".exe") and "uninstall" not in fl:
                candidates.append((50 - depth * 10, full))
        if candidates:
            return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]

    if subcategory == "renpy":
        for depth, _f, fl, full in walk(2):
            if any(bad in fl for bad in ["crashhandler", "oalinst", "vcredist", "dxsetup"]):
                continue
            if fl.endswith(".sh"):
                candidates.append((100 - depth * 10, full))
            elif fl.endswith(".py") and fl != "game.py":
                candidates.append((80 - depth * 10, full))
            elif fl.endswith(".exe"):
                candidates.append((50 - depth * 10, full))
        if candidates:
            return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]

    if subcategory == "3ds":
        for _depth, _f, fl, full in walk(2):
            if fl.endswith((".cci", ".3ds", ".cxi")):
                return full

    for depth, f, fl, full in walk(3):
        native = fl.endswith((".x86_64", ".x86", ".sh")) or (os.access(full, os.X_OK) and "." not in f and not os.path.isdir(full))
        if not (native or fl.endswith(".exe")):
            continue
        if any(bad in fl for bad in BAD_EXE_WORDS):
            continue
        score = 100 - depth * 15
        if native:
            score += 60
        if "_cn" in fl or "chs" in fl or "chinese" in fl or "中文" in fl:
            score += 50
        if "portable" in fl:
            score += 40
        if fl.endswith(".exe"):
            score += 10
        if "loader" in fl:
            score -= 30
        if "_gl.exe" in fl:
            score -= 20
        if fl in KNOWN_MAIN_EXES:
            score += 100
        candidates.append((score, full))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]


def register_standalone(folder, game_id, meta, subcategory):
    exe = os.path.join(folder, meta["exe"]) if meta.get("exe") else find_best_executable(folder, subcategory)
    icon = _icon(folder, meta, ["icon.png", "cover.png", "cover.jpg", os.path.join("icon", "icon.png"),
                                os.path.join("game", "gui", "window_icon.png")])
    return _entry(game_id, folder, meta, type="standalone", engine=subcategory, root=folder, exe_path=exe, icon=icon)


def register_retro(folder, game_id, meta):
    files = os.listdir(folder)
    rom_file = system = None
    if "(ps1)" in game_id.lower() or "(psx)" in game_id.lower():
        # PS1 优先完整带音轨的镜像包
        for ext in (".zip", ".chd", ".pbp", ".iso", ".cue"):
            matched = [f for f in files if f.lower().endswith(ext)]
            if matched:
                rom_file, system = matched[0], "psx"
                break
    else:
        for ext, core in ROM_EXTENSIONS.items():
            matched = [f for f in files if f.lower().endswith(ext)]
            if matched:
                rom_file, system = matched[0], core
                break
    if not rom_file:
        return None
    icon = _icon(folder, meta, ["icon.png", "cover.png", "cover.jpg"])
    return _entry(game_id, folder, meta, type="retro", system=system, root=folder, rom_file=rom_file, icon=icon)


def register_slg(folder, game_id, meta):
    entry_html = None
    for cand in ("index.html", "game.html", os.path.join("www", "index.html")):
        if os.path.exists(os.path.join(folder, cand)):
            entry_html = cand.replace(os.sep, "/")
            break
    if not entry_html:
        for root, _dirs, files in os.walk(folder):
            if "index.html" in files:
                entry_html = os.path.relpath(os.path.join(root, "index.html"), folder)
                break
    if entry_html:
        save_dir = os.path.join(folder, "save")
        os.makedirs(save_dir, exist_ok=True)
        icon = _icon(folder, meta, ["icon.png", "cover.png", "web-presplash.jpg", os.path.join("icons", "icon-512x512.png"),
                                    "icon.jpg", "cover.jpg", os.path.join("icon", "icon.png"),
                                    os.path.join("www", "icon", "icon.png")])
        return _entry(game_id, folder, meta, type="slg", slg_engine="web", root=folder,
                      entry_html=entry_html, save_dir=save_dir, icon=icon)

    game_sub = os.path.join(folder, "game")
    if os.path.isdir(game_sub):
        # 原生桌面版 Ren'Py
        icon = _icon(folder, meta, ["cover.jpg", "cover.png", "icon.png", os.path.join("game", "gui", "window_icon.png"),
                                    os.path.join("game", "icon.png"), os.path.join("game", "presplash.jpg"),
                                    os.path.join("game", "presplash.png")])
        exe = None
        listing = sorted(f for f in os.listdir(folder) if not f.startswith("."))
        for ext in (".sh", ".py", ".exe"):
            matched = [f for f in listing if f.endswith(ext)]
            if matched:
                exe = os.path.join(folder, matched[0])
                if ext != ".exe":
                    try:
                        os.chmod(exe, 0o755)
                    except Exception:
                        pass
                break
        return _entry(game_id, folder, meta, type="slg", slg_engine="renpy", engine="renpy", exe_path=exe,
                      root=folder, save_dir=os.path.join(game_sub, "saves"), icon=icon)
    return None


def register_flash(folder, game_id, meta):
    info = dict(meta)
    if not info.get("type"):
        try:
            with open(os.path.join(folder, "info.json"), "r", encoding="utf-8") as f:
                legacy = json.load(f)
            info = {**legacy, **meta}
        except Exception:
            pass
    engine, url = "swf", ""
    if info.get("type") == "web_flash" and info.get("url"):
        engine, url = "web_flash", info["url"]
    swf_file = None
    if engine == "swf":
        swfs = [f for f in os.listdir(folder) if f.lower().endswith(".swf")]
        if not swfs:
            return None
        swf_file = swfs[0]
    icon = _icon(folder, meta, ["icon.png", "icon.jpg", "cover.png", "cover.jpg"])
    return _entry(game_id, folder, meta, type="flash", engine=engine, url=url, root=folder,
                  swf_file=swf_file, hint=info.get("hint", ""), icon=icon)


# 扫描顺序即大厅列表顺序：(库键, 注册函数)
def _scan_plan():
    plan = [("games.rpg", register_rpg)]
    for cat in library.STANDALONE_CATEGORIES:
        plan.append((f"games.{cat}", lambda f, g, m, c=cat: register_standalone(f, g, m, c)))
    plan += [("games.retro", register_retro), ("games.slg", register_slg), ("games.flash", register_flash)]
    return plan


def _external_games():
    """settings.json 里登记的库外游戏/应用 + Lime3DS 模拟器主界面。"""
    out = []
    for item in settings.get("external_games") or []:
        path = settings.user_path(item.get("path", ""))
        if item.get("id") and os.path.isdir(path):
            out.append((item["id"], path, item.get("category", "app"), item))
    return out


def _lime3ds_entry():
    lime_dir = settings.tool("lime3ds_dir")
    sh = os.path.join(lime_dir, "start-lime3ds.sh")
    if not os.path.exists(sh):
        return None
    return {
        "id": "000 - Lime3DS Emulator",
        "name": "000 - 🍋 Lime3DS 模拟器 (主界面与全局设置)",
        "type": "standalone", "engine": "3ds", "root": lime_dir, "exe_path": sh,
        "icon": os.path.join(lime_dir, "lime3ds.png"),
    }


# --------------------------------------------------------------------------- 扫描

def _signature():
    sig = {}
    watched = []
    for key, _fn in _scan_plan():
        watched += library.candidates(key)
    watched += [p for _i, p, _c, _m in _external_games()]
    for p in watched:
        try:
            st = os.stat(p)
            sig[p] = (st.st_mtime_ns, st.st_size)
        except (OSError, TypeError):
            sig[p] = None
    sig["__libraries__"] = json.dumps(settings.load().get("libraries"), sort_keys=True)
    sig["__external__"] = json.dumps(settings.load().get("external_games"), sort_keys=True)
    return sig


def scan(force=False):
    """只有游戏目录（或库清单）有变动、或 force=True 时才真正重扫（stat 指纹比较，毫秒级）。"""
    global _last_sig
    with _scan_lock:
        sig = _signature()
        if not force and REGISTRY and sig == _last_sig:
            return
        _last_sig = sig
        found = {}
        for key, register in _scan_plan():
            for d in library.dirs(key):
                try:
                    items = sorted(os.listdir(d))
                except OSError:
                    continue
                for item in items:
                    folder = os.path.join(d, item)
                    if item.startswith(".") or item in found or not os.path.isdir(folder):
                        continue
                    meta = read_meta(folder)
                    if meta.get("hidden"):
                        continue
                    try:
                        entry = register(folder, item, meta)
                    except OSError:
                        entry = None
                    if entry:
                        found[item] = entry
        for gid, path, cat, item in _external_games():
            if gid not in found and not item.get("hidden"):
                meta = {**read_meta(path), **{k: v for k, v in item.items() if k not in ("id", "path", "category")}}
                found[gid] = register_standalone(path, gid, meta, cat)
        lime = _lime3ds_entry()
        if lime:
            found[lime["id"]] = lime
        REGISTRY.clear()
        REGISTRY.update(found)


def get(game_id: str):
    """按 id 查游戏（大小写不敏感、兼容 URL 编码）；找不到先强制重扫一次。"""
    if not game_id:
        return None
    for attempt in (False, True):
        if attempt:
            scan(force=True)
        if game_id in REGISTRY:
            return REGISTRY[game_id]
        unq = urllib.parse.unquote(game_id).strip().lower()
        for gid, g in REGISTRY.items():
            if gid.lower() == unq:
                return g
    return None


def lookup(game_id: str):
    """不触发重扫的查询（给高频的资源请求用）。"""
    if game_id in REGISTRY:
        return REGISTRY[game_id]
    low = game_id.lower()
    return next((g for gid, g in REGISTRY.items() if gid.lower() == low), None)


def is_nsfw(game: dict) -> bool:
    """游戏类型就是 manifest 里的分区 id（rpg/slg/retro/flash/standalone）——该分区 access=nsfw 即为 NSFW。"""
    from omni.core import manifest
    sec = manifest.section(game.get("type", ""))
    return bool(sec and sec.get("access") == "nsfw")


def game_id_from_path(path: str):
    """从请求 URL 里取游戏 id（日志打标签用）。"""
    try:
        clean = urllib.parse.unquote(urllib.parse.unquote(path.split("?")[0]))
        for prefix in ("/game/", "/save/"):
            if prefix in clean:
                parts = clean[clean.index(prefix):].split("/")
                if len(parts) >= 3:
                    return parts[2]
        if "game_id=" in path:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(path.split(" ")[1] if " " in path else path).query)
            if "game_id" in qs:
                return qs["game_id"][0]
    except Exception:
        pass
    return None
