"""音声画廊 API：常规有声书公开可听，NSFW 音声（?nsfw=1）需要解锁；播放走 Range 分段流。"""
from omni.core.http import Api
from omni.features.audio import playback, service as audio

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


@api.get("/api/audio/player_spec", access="public")
def player_spec(req):
    """倍速 / 定时 / 播放模式 / 快退快进 档位（本机原生控件与网页共用一份，见 playback.py）。"""
    return req.json(playback.spec())


def _progress_key(req, key):
    """NSFW 区的续听记录也要解锁才能读写。"""
    if key.startswith("nsfw:") and not req.nsfw_ok:
        return None
    return key


@api.get("/api/audio/progress", access="public")
def get_progress(req):
    key = _progress_key(req, req.arg("key"))
    return req.json({"pos": playback.get_progress(key) if key else 0})


@api.post("/api/audio/progress", access="public")
def set_progress(req):
    b = req.json_body()
    key = _progress_key(req, str(b.get("key") or ""))
    if key:
        try:
            playback.set_progress(key, float(b.get("pos") or 0), float(b.get("dur") or 0))
        except (TypeError, ValueError):
            return req.json({"status": "error"}, 400)
    return req.json({"status": "ok"})
