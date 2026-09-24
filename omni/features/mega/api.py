"""MEGA 网盘 API（含账户隐私信息，仅限 Steam Deck 本机）。"""
from omni.core.http import Api
from omni.features.mega import service as mega

LOCAL_ONLY = lambda req: req.json(  # noqa: E731
    {"status": "error", "error": "🔒 MEGA 服务包含隐私账户信息，仅限在 Steam Deck 本机访问，局域网禁止访问"}, 403)

api = Api("mega")


def _get(path, fn):
    api.get(path, deny=LOCAL_ONLY)(lambda req: req.json(fn(req)))


def _post(path, fn):
    api.post(path, deny=LOCAL_ONLY)(lambda req: req.json(fn(req.json_body())))


_get("/api/mega/status", lambda req: mega.get_mega_status())
_get("/api/mega/files", lambda req: mega.list_mega_files(req.arg("path", "/")))
_get("/api/mega/transfers", lambda req: mega.get_transfers())
_get("/api/mega/quota", lambda req: mega.get_quota_status(force_probe=True))
_get("/api/mega/trash", lambda req: mega.list_cloud_trash())

_post("/api/mega/login", lambda b: mega.mega_login(b.get("email", "").strip(), b.get("password", ""), auth_code=b.get("auth_code")))
_post("/api/mega/logout", lambda b: mega.mega_logout())
_post("/api/mega/reload", lambda b: mega.mega_reload())
_post("/api/mega/download", lambda b: mega.start_download(b.get("source", "").strip(), target_location=b.get("location", "downloads")))
_post("/api/mega/cancel_transfer", lambda b: mega.cancel_transfer(str(b.get("tag", ""))))
_post("/api/mega/pause_transfer", lambda b: mega.pause_transfer(str(b.get("tag", ""))))
_post("/api/mega/resume_transfer", lambda b: mega.resume_transfer(str(b.get("tag", ""))))
_post("/api/mega/trash", lambda b: mega.move_cloud_to_trash(b.get("path", "")))
_post("/api/mega/restore_trash", lambda b: mega.restore_cloud_trash(b.get("path", "")))
_post("/api/mega/empty_trash", lambda b: mega.empty_cloud_trash())
