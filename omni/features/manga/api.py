"""漫画画廊 API：本地 CBZ 书架、封面/分页读取、JM 在线检索与榜单、下载队列与任务。"""
import os
import subprocess

from omni.core import events
from omni.core.http import Api
from omni.features.manga import service as manga

api = Api("manga")

LOCKED = lambda req: req.error(403, "Forbidden: Manga is locked")                    # noqa: E731
LOCKED_POST = lambda req: req.json({"status": "error", "error": "NSFW content is locked"}, 403)  # noqa: E731
ONLINE_LOCAL_ONLY = lambda req: req.error(403, "Forbidden: online search/download is local-only")  # noqa: E731

events.on_init(lambda: {
    "manga_queue": manga.get_persistent_queue(target_dir="manga"),
    "novel_queue": manga.get_persistent_queue(target_dir="novels"),
    "queue": manga.get_persistent_queue(target_dir="manga"),
    "tasks": manga.get_all_tasks(),
})


def _dir(req, default="manga"):
    return req.arg("dir") or req.arg("type") or default


# ------------------------------------------------------------------ 本地书架

@api.get("/api/manga/library", deny=lambda req: req.json([]))
def library(req):
    return req.json(manga.get_local_library(req.arg("q"), target_dir=_dir(req)))


@api.get("/api/manga/cover", deny=LOCKED)
def cover(req):
    name, target_dir = req.arg("name"), req.arg("dir")
    if not req.flag("full"):
        # 默认发磁盘缓存的缩略图（网格用），源没变就不再开压缩包；?full=1 发原图
        thumb = manga.get_cbz_cover_thumb(name, target_dir=target_dir)
        if thumb and os.path.exists(thumb):
            return req.file(thumb, "image/webp", headers={"Cache-Control": "public, max-age=86400"})
    data = manga.get_cbz_cover_bytes(name, target_dir=target_dir)
    if not data:
        return req.not_found()
    return req.send(200, data, "image/jpeg", {"Cache-Control": "public, max-age=3600"})


@api.get("/api/manga/pages", deny=LOCKED)
def pages(req):
    return req.json(manga.get_cbz_pages_list(req.arg("name"), target_dir=req.arg("dir")))


@api.get("/api/manga/page", deny=LOCKED)
def page(req):
    data = manga.get_cbz_page_bytes(req.arg("name"), req.arg("page"), target_dir=req.arg("dir"))
    if not data:
        return req.not_found()
    return req.send(200, data, "image/jpeg", {"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------ 在线检索（仅本机）

@api.get("/api/manga/search", access="local", deny=ONLINE_LOCAL_ONLY)
def search(req):
    q, page_no = req.arg("q"), req.int_arg("page", 1)
    category = req.arg("category") or req.arg("type") or "0"
    order_by = req.arg("order_by") or req.arg("o")
    local = manga.get_local_library(q, target_dir=("novels" if category == "novel" else "manga")) if page_no == 1 else []
    online = manga.search_jm_online(q, page_no, category=category, order_by=order_by)
    return req.json({
        "local": local, "online": online.get("results", []), "total_online": online.get("total", 0),
        "page": page_no, "page_count": online.get("page_count", 1), "has_more": online.get("has_more", False),
        "error": online.get("error"),
    })


@api.get("/api/manga/rankings", access="local", deny=ONLINE_LOCAL_ONLY)
def rankings(req):
    rank_type = req.arg("type", "week")
    page_no = req.int_arg("page", 1)
    items = manga.get_ranking_albums(rank_type=rank_type, page=page_no, count=req.int_arg("count", 80))
    return req.json({"rank_type": rank_type, "page": page_no, "results": items})


@api.get("/api/manga/detail", access="local", deny=ONLINE_LOCAL_ONLY)
def detail(req):
    try:
        return req.json(manga.get_jm_album_detail(req.arg("id")))
    except Exception as e:
        return req.json({"error": str(e)}, 500)


@api.get("/api/manga/online_cover", access="local", deny=ONLINE_LOCAL_ONLY)
def online_cover(req):
    data = manga.get_online_cover_bytes(req.arg("id"))
    if not data:
        return req.not_found()
    return req.send(200, data, "image/jpeg", {"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------ 队列与任务

@api.get("/api/manga/queue", deny=LOCKED)
def get_queue(req):
    return req.json(manga.get_persistent_queue(target_dir=_dir(req)))


@api.post("/api/manga/queue", deny=LOCKED_POST)
def save_queue(req):
    body = req.json_body()
    manga.save_persistent_queue(body.get("items", []), target_dir=body.get("dir", "manga"))
    return req.json({"status": "ok"})


@api.get("/api/manga/tasks", deny=LOCKED)
def tasks(req):
    return req.json(manga.get_all_tasks())


@api.get("/api/manga/recover_temp", deny=LOCKED)
def recover_temp(req):
    return req.json(manga.scan_and_recover_temp_manga(target_dir=req.arg("dir", "manga")))


@api.post("/api/manga/download", deny=LOCKED_POST)
def download(req):
    b = req.json_body()
    task_id = manga.start_download_task(b.get("album_id"), b.get("chapter_ids"), b.get("pack_cbz", True),
                                        b.get("clean_temp", True), dest_dir=b.get("dir", "manga"))
    return req.json({"status": "ok", "task_id": task_id})


@api.post("/api/manga/batch_download", deny=LOCKED_POST)
def batch_download(req):
    b = req.json_body()
    task_id = manga.start_batch_download_task(b.get("album_ids", []), b.get("pack_cbz", True), b.get("clean_temp", True),
                                              dest_dir=b.get("dir", "manga"), concurrency=int(b.get("concurrency", 3)))
    return req.json({"status": "ok", "task_id": task_id})


@api.post("/api/manga/stop_batch", deny=LOCKED_POST)
def stop_batch(req):
    return req.json({"status": "ok", "stopped": manga.stop_batch_download_task(req.json_body().get("task_id"))})


@api.post("/api/manga/clean_temp", deny=LOCKED_POST)
def clean_temp(req):
    return req.json({"status": "ok", "cleaned_count": manga.clean_all_temp_files()})


@api.post("/api/manga/manual_pack", deny=LOCKED_POST)
def manual_pack(req):
    b = req.json_body()
    ok = manga.manual_pack_manga(b.get("folder", ""), b.get("target_name"), dest_dir=b.get("dir", "manga"))
    return req.json({"status": "ok" if ok else "failed"})


@api.post("/api/manga/open_external", deny=LOCKED_POST)
def open_external(req):
    b = req.json_body()
    path = manga.resolve_file_path(b.get("filename", ""), b.get("dir", ""))
    if path and os.path.exists(path):
        subprocess.Popen(["xdg-open", path])
    return req.json({"status": "ok"})


@api.post("/api/manga/delete", deny=LOCKED_POST)
def delete(req):
    b = req.json_body()
    ok = manga.trash_manga_file(b.get("filename", ""), target_dir=b.get("dir", ""))
    return req.json({"status": "ok" if ok else "failed"})
