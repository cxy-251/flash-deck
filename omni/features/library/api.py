"""
「存储与游戏库」API（仅本机）：像 Steam 的存储管理一样登记多个资源库根目录，
添加时自动建目录骨架；另外管理收件箱、库外游戏和外部工具路径。
"""
import os

from omni.core import events, library, paths, settings
from omni.core.http import Api
from omni.features.games import registry

api = Api("library")

LOCAL_ONLY = lambda req: req.error(403, "Forbidden: local-only")  # noqa: E731


def _changed():
    registry.scan(force=True)
    events.broadcast({"type": "library_changed"})


def _overview():
    cfg = settings.load()
    return {
        "dirs": {k: {"value": v, "resolved": settings.resolve("{%s}" % k)} for k, v in (cfg.get("dirs") or {}).items()},
        "libraries": library.status(),
        "layout": library.LAYOUT,
        "duplicates": library.duplicates(),
        "inbox_dir": settings.get("inbox_dir"),
        "external_games": cfg.get("external_games", []),
        "tools": {k: settings.tool(k) for k in cfg.get("tools", {})},
    }


@api.get("/api/library", deny=LOCAL_ONLY)
def overview(req):
    return req.json(_overview())


@api.get("/api/library/browse", deny=LOCAL_ONLY)
def browse(req):
    """目录选择器：列出某个目录下的子目录（默认从家目录开始），标出哪些已经是资源库。"""
    path = settings.user_path(req.arg("path") or paths.HOME)
    if not os.path.isdir(path):
        return req.error(404, "目录不存在")
    try:
        names = sorted(e.name for e in os.scandir(path) if e.is_dir() and not e.name.startswith("."))
    except OSError as e:
        return req.error(403, str(e))
    shortcuts = [{"label": "主目录", "path": paths.HOME}]
    shortcuts += [{"label": os.path.basename(m), "path": m} for m in library.mount_points()]
    return req.json({
        "path": path,
        "parent": os.path.dirname(path) if path != "/" else None,
        "dirs": [{"name": n, "path": os.path.join(path, n),
                  "is_library": library.read_marker(os.path.join(path, n)) is not None} for n in names],
        "is_library": library.read_marker(path) is not None,
        "shortcuts": shortcuts,
    })


@api.post("/api/library/preview", deny=LOCAL_ONLY)
def preview(req):
    """添加前预览：该目录是否已有库标记、会新建哪些骨架目录。"""
    path = settings.user_path(req.json_body().get("path", "")) or paths.HOME
    return req.json({
        "path": path,
        "exists": os.path.isdir(path),
        "marker": library.read_marker(path),
        "missing": library.plan_skeleton(path),
    })


def _op(fn):
    def handler(req):
        b = req.json_body()
        try:
            result = fn(b)
        except (ValueError, KeyError, OSError) as e:
            return req.json({"success": False, "error": str(e)}, 400)
        _changed()
        return req.json({"success": True, "result": result, **_overview()})
    return handler


api.post("/api/library/add", deny=LOCAL_ONLY)(_op(
    lambda b: library.add(b["path"], b.get("label"), make_default=bool(b.get("default")))))
api.post("/api/library/remove", deny=LOCAL_ONLY)(_op(lambda b: library.remove(b["id"])))
api.post("/api/library/default", deny=LOCAL_ONLY)(_op(lambda b: library.set_default(b["id"])))
api.post("/api/library/rename", deny=LOCAL_ONLY)(_op(lambda b: library.rename(b["id"], b.get("label", ""))))
api.post("/api/library/reorder", deny=LOCAL_ONLY)(_op(lambda b: library.reorder(list(b["ids"]))))
api.post("/api/library/repair", deny=LOCAL_ONLY)(_op(lambda b: library.repair(b["id"])))


@api.post("/api/settings", deny=LOCAL_ONLY)
def update_settings(req):
    """更新收件箱 / 外部工具路径 / 库外游戏等配置（只接受已知的顶层键）。"""
    b = req.json_body()
    allowed = {k: b[k] for k in ("inbox_dir", "tools", "external_games", "wan_domain", "dirs") if k in b}
    # 基础目录先落盘，下面其它路径才能按新的 dirs 压缩
    if "dirs" in allowed:
        settings.update({"dirs": {k: v.strip() for k, v in allowed.pop("dirs").items()
                                  if isinstance(v, str) and v.strip()}})
    # 路径一律存成「基础目录占位」形式（{games}/...），以后挪动基础目录只改 dirs 一处
    if "tools" in allowed:
        allowed["tools"] = {k: settings.compact(v) if v else v
                            for k, v in allowed["tools"].items() if k in settings.DEFAULTS["tools"]}
    if allowed.get("inbox_dir"):
        allowed["inbox_dir"] = settings.compact(allowed["inbox_dir"])
    if "external_games" in allowed:
        allowed["external_games"] = [{**g, "path": settings.compact(g.get("path", ""))} for g in allowed["external_games"]]
    settings.update(allowed)
    _changed()
    return req.json({"success": True, **_overview()})
