"""短视频画廊 API（快手 / 抖音 / TikTok 三个分区共用，按 platform 参数区分）。"""
import os

from omni.core.http import Api
from omni.features.shortvideo import service as sv

api = Api("shortvideo")

LOCKED = lambda req: req.error(403, "Forbidden: short-video gallery is locked")            # noqa: E731
LOCKED_POST = lambda req: req.json({"status": "error", "error": "NSFW content is locked"}, 403)  # noqa: E731


def _platform(req):
    return req.arg("platform", "kuaishou")


@api.get("/api/shortvideo/library", deny=LOCKED)
def library(req):
    return req.json(sv.query_shortvideo_library(platform=_platform(req), q=req.arg("q"), folder=req.arg("folder", "all"),
                                                page=req.int_arg("page", 1), page_size=req.int_arg("page_size", 60)))


@api.get("/api/shortvideo/transcode_status", deny=LOCKED)
def transcode_status(req):
    return req.json(sv.transcode_status(_platform(req)))


@api.get("/api/shortvideo/thumb", deny=LOCKED)
def thumb(req):
    p = sv.get_video_thumb(_platform(req), req.arg("path"))
    if not p or not os.path.exists(p):
        return req.not_found()
    return req.file(p, "image/webp", headers={"Cache-Control": "public, max-age=86400"})


@api.get("/api/shortvideo/gallery_image", deny=LOCKED)
def gallery_image(req):
    """图集（抖音多图作品）里第 idx 张原图。"""
    p, ctype = sv.get_gallery_image(_platform(req), req.arg("path"), req.int_arg("idx", 0))
    if not p or not os.path.exists(p):
        return req.not_found()
    return req.file(p, ctype or "application/octet-stream", headers={"Cache-Control": "public, max-age=86400"})


@api.get("/api/shortvideo/stream", deny=LOCKED)
def stream(req):
    """本机 QtWebEngine 没有 H.264 解码器——本机请求现转 VP9/WebM（有缓存），
    局域网/远程是正常浏览器，直接给原始文件。前端两边用的是同一个接口。"""
    rel = req.arg("path")
    full, ctype = sv.get_playable_for_client(_platform(req), rel, req.is_local)
    if not full or not os.path.exists(full):
        return req.error(503 if rel else 404, "video not found or transcode failed")
    return req.file(full, ctype)


@api.post("/api/shortvideo/like", deny=LOCKED_POST)
def like(req):
    b = req.json_body()
    res = sv.toggle_shortvideo_like(b.get("platform") or "kuaishou", b.get("path", "") or b.get("rel_path", ""), b.get("liked"))
    return req.json({"status": "ok", "liked": res})


def _trash(req):
    b = req.json_body()
    ok = sv.trash_shortvideo_file(b.get("platform") or "kuaishou", b.get("path", "") or b.get("rel_path", ""))
    return req.json({"status": "ok" if ok else "failed"})


api.post("/api/shortvideo/trash", deny=LOCKED_POST)(_trash)
api.post("/api/shortvideo/delete", deny=LOCKED_POST)(_trash)


@api.post("/api/shortvideo/transcode_all", deny=LOCKED_POST)
def transcode_all(req):
    sv.transcode_all_now(req.json_body().get("platform") or "kuaishou")
    return req.json({"status": "ok"})
