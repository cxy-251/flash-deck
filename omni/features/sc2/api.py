"""星际争霸 2 对战面板 API：地图/mod 列表、缩略图、开局、打开银河编辑器（开局与编辑器仅本机）。"""
from omni.core.http import Api
from omni.features.sc2 import service as sc2

api = Api("sc2", access_level="public")   # 列表类只读接口不设限；拉起进程的写接口单独限本机

LOCAL_ONLY = lambda req: req.json(  # noqa: E731
    {"status": "error", "error": "🔒 独立游戏专区仅限在 Steam Deck 实体机屏幕上运行"}, 403)


@api.get("/api/sc2/maps")
def maps(req):
    return req.json(sc2.list_maps())


@api.get("/api/sc2/mods")
def mods(req):
    return req.json(sc2.list_mods())


@api.get("/api/sc2/status")
def status(req):
    return req.json(sc2.get_status())


@api.get("/api/sc2/thumb/{name}")
def thumb(req):
    stem = req.params["name"].rsplit(".png", 1)[0]
    p = sc2.thumb_path(stem)
    if not p:
        return req.not_found()
    return req.file(str(p), "image/png", headers={"Cache-Control": "public, max-age=86400"})


@api.post("/api/sc2/play", access="local", deny=LOCAL_ONLY)
def play(req):
    b = req.json_body()
    ok, msg = sc2.start_match(b.get("map", ""), b.get("race", "P"), b.get("opponents", []), b.get("mods", []))
    return req.json({"status": "ok" if ok else "error", "message": msg}, 200 if ok else 409)


@api.post("/api/sc2/open_editor", access="local", deny=LOCAL_ONLY)
def open_editor(req):
    ok, msg = sc2.open_editor()
    return req.json({"status": "ok" if ok else "error", "message": msg}, 200 if ok else 409)
