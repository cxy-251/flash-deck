"""音声画廊 API：常规有声书公开可听，NSFW 音声（?nsfw=1）需要解锁；播放走 Range 分段流。"""
from omni.core.http import Api
from omni.features.audio import service as audio

api = Api("audio")

LOCKED_POST = lambda req: req.json({"status": "error", "error": "NSFW content is locked"}, 403)  # noqa: E731
MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".flac": "audio/flac",
        ".wav": "audio/wav", ".ogg": "audio/ogg", ".opus": "audio/opus", ".aac": "audio/aac"}


def _nsfw_mode(req):
    return req.flag("nsfw") or req.arg("mode") == "nsfw"


@api.get("/api/audio/library", access="public")
def library(req):
    nsfw = _nsfw_mode(req)
    if nsfw and not req.nsfw_ok:
        return req.json({"items": [], "total": 0, "page": 1, "page_size": 80, "albums": [], "is_nsfw": True})
    return req.json(audio.query_audio_library(q=req.arg("q"), album=req.arg("album", "all"), is_nsfw=nsfw,
                                              page=req.int_arg("page", 1), page_size=req.int_arg("page_size", 80)))


@api.get("/audio/standard_catalog.json", access="public")
def standard_catalog(req):
    """非 NSFW 有声书目录（每次现扫，stream_url 永远是当前可播的地址）。"""
    return req.json(audio.get_standard_catalog())


@api.get("/api/audio/stream", access="public")
def stream(req):
    nsfw = req.flag("nsfw")
    if nsfw and not req.nsfw_ok:
        return req.error(403, "Forbidden: Audio is locked")
    import os
    full = audio.find_audio_file(req.arg("name") or req.arg("path"), is_nsfw=nsfw)
    if not full or not os.path.exists(full):
        return req.not_found()
    return req.file(full, MIME.get(os.path.splitext(full)[1].lower(), "audio/mpeg"))


def _trash(req):
    b = req.json_body()
    ok = audio.trash_audio_file(b.get("filename", "") or b.get("name", "") or b.get("path", ""),
                                is_nsfw=bool(b.get("is_nsfw", False)))
    return req.json({"status": "ok" if ok else "failed"})


api.post("/api/audio/trash", deny=LOCKED_POST)(_trash)
api.post("/api/audio/delete", deny=LOCKED_POST)(_trash)
