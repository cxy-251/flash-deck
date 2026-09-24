"""小说画廊 API：本地书架（standard / nsfw 物理隔离）、阅读器、在线检索与下载队列。"""
from omni.core.http import Api
from omni.features.novels import service as novels

api = Api("novels")

LOCKED = lambda req: req.error(403, "Forbidden: Novels is locked")                         # noqa: E731
LOCKED_POST = lambda req: req.json({"status": "error", "error": "NSFW content is locked"}, 403)  # noqa: E731


def _nsfw_mode(req):
    return req.flag("nsfw") or req.arg("mode") == "nsfw"


@api.get("/api/novels/library", deny=lambda req: req.json([]))
def library(req):
    return req.json(novels.get_novels_library(req.arg("q"), is_nsfw=_nsfw_mode(req)))


@api.get("/api/novels/search", access="local",
         deny=lambda req: req.error(403, "Forbidden: online search/download is local-only"))
def search(req):
    return req.json(novels.search_online_novels(req.arg("q"), is_nsfw=_nsfw_mode(req)))


@api.get("/api/novels/cover", access="public")
def cover(req):
    full = novels.resolve_novel_or_doc_path(req.arg("path") or req.arg("name"))
    if not req.nsfw_ok and not novels.is_doc_path(full):
        return LOCKED(req)
    if full and full.endswith(".epub"):
        data = novels.extract_epub_metadata_and_cover(full).get("cover_bytes")
        if data:
            return req.send(200, data, "image/jpeg", {"Cache-Control": "max-age=86400"})
    return req.not_found()


@api.get("/api/novels/read", access="public")
def read(req):
    """技术文档（.md/.rst）公开可读，其余（小说正文）需要解锁。"""
    data = novels.read_novel_file(req.arg("path") or req.arg("name"))
    if not data:
        return req.not_found()
    if data.get("type") != "tech" and not req.nsfw_ok:
        return LOCKED(req)
    return req.json(data)


@api.get("/api/novels/queue", deny=LOCKED)
def queue(req):
    return req.json(novels.load_novel_queue(is_nsfw=_nsfw_mode(req)))


@api.get("/api/novels/tasks", deny=LOCKED)
def tasks(req):
    return req.json(novels.get_novel_active_tasks())


@api.post("/api/novels/download", deny=LOCKED_POST)
def download(req):
    import time
    b = req.json_body()
    res = novels.start_download_novel_task(
        b.get("id", "") or str(int(time.time())), b.get("title", "未命名小说"), b.get("author", "佚名"),
        b.get("intro", ""), b.get("cover_url", ""), is_nsfw=b.get("is_nsfw", False) or b.get("mode") == "nsfw")
    return req.json(res)


@api.post("/api/novels/queue/add", deny=LOCKED_POST)
def queue_add(req):
    item = req.json_body()
    if item.get("id"):
        novels.add_novel_to_queue(item)
    return req.json({"status": "ok"})


@api.post("/api/novels/queue/remove", deny=LOCKED_POST)
def queue_remove(req):
    b = req.json_body()
    if b.get("id"):
        novels.remove_novel_from_queue(b["id"], is_nsfw=b.get("is_nsfw"))
    return req.json({"status": "ok"})


@api.post("/api/novels/queue/clear", deny=LOCKED_POST)
def queue_clear(req):
    novels.clear_novel_queue(is_nsfw=req.json_body().get("is_nsfw"))
    return req.json({"status": "ok"})


def _trash(req):
    b = req.json_body()
    ok = novels.trash_novel_file(b.get("path", "") or b.get("name", "") or b.get("filename", ""))
    return req.json({"status": "ok" if ok else "failed"})


api.post("/api/novels/trash", deny=LOCKED_POST)(_trash)
api.post("/api/novels/delete", deny=LOCKED_POST)(_trash)
