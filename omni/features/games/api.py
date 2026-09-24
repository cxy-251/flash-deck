"""
游戏中心 API：游戏清单、启动独立游戏、游戏资源虚拟文件系统（/game/<id>/...，大小写不敏感）、
网页游戏存档直通磁盘（/save、/api/save —— 存档写进游戏自己目录下的 save/，不依赖浏览器 IndexedDB）。
"""
import os

from omni.core import paths
from omni.core.http import Api
from omni.core.vfs import resolve_case_insensitive_path
from omni.features.games import launcher, registry

api = Api(access_level="public")

LOCAL_ONLY_LAUNCH = {"status": "error", "error": "🔒 独立游戏专区仅限在 Steam Deck 实体机屏幕上运行，局域网禁止远程拉起"}


def _locked(req, game):
    """RPG/SLG 属于 NSFW 分区：非本机且未解锁时拒绝访问其资源。"""
    if game and registry.is_nsfw(game) and not req.nsfw_ok:
        req.send(403, b"NSFW game content is locked", "text/plain; charset=utf-8")
        return True
    return False


@api.get("/api/games")
def list_games(req):
    registry.scan(force=("force" in req.query or "refresh" in req.query))
    games = list(registry.REGISTRY.values())
    if not req.nsfw_ok:
        games = [g for g in games if not registry.is_nsfw(g)]
    return req.json(games)


@api.post("/api/games/launch", access="local", deny=lambda req: req.json(LOCAL_ONLY_LAUNCH, 403))
def launch(req):
    body = req.json_body()
    gid = body.get("id")
    ok, msg = launcher.launch(gid, body.get("title", gid))
    return req.json({"status": "ok" if ok else "error", "message": msg}, 200 if ok else 400)


def _serve_game_file(req):
    game = registry.lookup(req.params["game_id"])
    if not game:
        return req.not_found()
    if _locked(req, game):
        return
    target = resolve_case_insensitive_path(game["root"], req.params.get("rest", ""))
    if os.path.isdir(target):
        target = os.path.join(target, "index.html")
    if not os.path.isfile(target):
        return req.not_found()
    return req.file(target)


api.get("/game/{game_id}/{rest:path}")(_serve_game_file)
api.head("/game/{game_id}/{rest:path}")(_serve_game_file)


@api.get("/icon/{game_id:path}")
def icon(req):
    game = registry.lookup(req.params["game_id"])
    if game and game.get("icon") and os.path.exists(game["icon"]):
        return req.file(game["icon"], headers={"Cache-Control": "public, max-age=3600"})
    return req.send(200, registry.DEFAULT_SVG_ICON, "image/svg+xml")


@api.get("/retro_rom/{rest:path}")
def retro_rom(req):
    parts = [p for p in req.params["rest"].split("/") if p]
    game = registry.get(parts[0]) if parts else None
    if game and game.get("type") == "retro":
        target = os.path.join(game["root"], parts[1]) if len(parts) > 1 else None
        if not target or not os.path.exists(target):
            target = os.path.join(game["root"], game["rom_file"])
        if os.path.exists(target):
            return req.file(target, "application/octet-stream")
    return req.not_found()


@api.get("/flash_swf/{rest:path}")
def flash_swf(req):
    parts = [p for p in req.params["rest"].split("/") if p]
    game = registry.get(parts[0]) if parts else None
    if game and game.get("type") == "flash":
        name = parts[1] if len(parts) > 1 else game.get("swf_file")
        if name:
            target = os.path.join(game["root"], name)
            if os.path.exists(target):
                return req.file(target, "application/x-shockwave-flash")
    return req.not_found()


# ------------------------------------------------------------------ 存档直通

def _save_target(game, filename):
    name = os.path.basename(filename or "")
    return os.path.join(game["save_dir"], name) if (game and game.get("save_dir") and name) else None


def _read_save(req):
    game = registry.lookup(req.params["game_id"])
    if _locked(req, game):
        return
    target = _save_target(game, req.params["file"])
    if target and os.path.exists(target):
        return req.file(target, "text/plain; charset=utf-8")
    return req.not_found()


api.get("/save/{game_id}/{file}")(_read_save)
api.head("/save/{game_id}/{file}")(_read_save)


@api.post("/api/save/{game_id:path}")
def write_save(req):
    game = registry.lookup(req.params["game_id"])
    data = req.body()
    if _locked(req, game):
        return
    target = _save_target(game, req.arg("file"))
    if target:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
        except Exception as e:
            from omni.core.log import log
            log("ERROR", f"存档写入失败: {e}", tag=game["id"])
    return req.json({"status": "ok"})


@api.delete("/api/save/{game_id:path}")
def delete_save(req):
    game = registry.lookup(req.params["game_id"])
    if _locked(req, game):
        return
    target = _save_target(game, req.arg("file"))
    if target and os.path.exists(target):
        try:
            os.remove(target)   # 游戏自己发起的删档，语义就是立即删除
        except Exception as e:
            from omni.core.log import log
            log("ERROR", f"存档删除失败: {e}", tag=game["id"])
    return req.json({"status": "ok"})


# ------------------------------------------------------------------ NW.js 兼容层用到的辅助接口

def _case_insensitive_abs(path):
    current = "/"
    for part in path.strip("/").split("/"):
        if not part:
            continue
        nxt = os.path.join(current, part)
        if not os.path.exists(nxt):
            try:
                low = part.lower()
                nxt = next((os.path.join(current, e) for e in os.listdir(current) if e.lower() == low), nxt)
            except OSError:
                pass
        current = nxt
    return current


@api.get("/api/readdir")
def readdir(req):
    """rpg-runtime.js 里 fs.readdirSync 的后端：列出游戏目录下某个子目录。"""
    rel = req.arg("path").lstrip("/")
    if not req.arg("path"):
        return req.json([])
    game = registry.lookup(req.arg("game_id")) if req.arg("game_id") else None
    if game:
        if _locked(req, game):
            return
        target = resolve_case_insensitive_path(game["root"], rel)
    elif not req.is_local:
        return req.json([])     # 不带游戏 id 的任意路径只对本机开放
    elif os.path.isabs(req.arg("path")):
        target = _case_insensitive_abs(req.arg("path"))
    else:
        target = resolve_case_insensitive_path(paths.REPO, rel)
    try:
        return req.json(os.listdir(target) if os.path.isdir(target) else [])
    except OSError:
        return req.json([])


@api.get("/api/patch/{name:path}")
def patch(req):
    """游戏目录下的 adapter.js（针对单个游戏的兼容补丁），没有就回一个空补丁。"""
    gid = req.params["name"]
    gid = gid[:-3] if gid.endswith(".js") else gid
    game = registry.lookup(gid)
    p = os.path.join(game["root"], "adapter.js") if game else None
    if p and os.path.exists(p):
        return req.file(p, "application/javascript")
    return req.send(200, b"// default adapter\n", "application/javascript")
