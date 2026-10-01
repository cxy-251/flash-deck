"""局域网小工具 API：文件传输（共享文件夹、分块断点续传上传、下载 / 打包 / 删除）与消息板。

访问规则：局域网（「局域网共享」开着）直接能用；经 Cloudflare 广域网来的请求要先解锁（隐私密码，
请求带 X-Omni-Token / Cookie / ?token=）——这里能往 Deck 上写文件，不能对公网裸奔。
"""
import functools
import subprocess
import urllib.parse

from omni.core import access
from omni.core.http import Api
from omni.features.tools import service as svc

api = Api("tools")


def guarded(fn):
    @functools.wraps(fn)
    def inner(req):
        if access.is_cloudflare(req.handler) and not req.nsfw_ok:
            return req.error(403, "广域网使用传输功能需要先解锁（隐私密码）", locked=True)
        return fn(req)
    return inner


def _attachment(name: str) -> str:
    return "attachment; filename*=UTF-8''" + urllib.parse.quote(name)


# ---------------------------------------------------------------- 共享文件夹

@api.get("/api/tools/files")
@guarded
def files(req):
    data = {"files": svc.list_files(), "uploads": svc.list_uploads(), "chunk": svc.CHUNK_SIZE}
    if req.is_local:
        data["dir"] = svc.write_dir()
    return req.json(data)


@api.get("/api/tools/files/{name}")
@guarded
def download(req):
    path = svc.find_file(req.params["name"])
    if not path:
        return req.not_found()
    headers = None if req.flag("inline") else {"Content-Disposition": _attachment(req.params["name"])}
    return req.file(path, headers=headers)


@api.post("/api/tools/files/delete")
@guarded
def delete_files(req):
    names = req.json_body().get("names") or []
    if not isinstance(names, list):
        return req.error(400, "names 应该是列表")
    return req.json({"deleted": svc.trash_files([str(n) for n in names])})


@api.get("/api/tools/zip")
@guarded
def zip_files(req):
    """多选打包：长度事先不知道，不带 Content-Length，发完关连接。"""
    names = [n for n in req.query.get("name", []) if n]
    if not names:
        return req.error(400, "没有选文件")
    h = req.handler
    h.send_response(200)
    h.send_header("Content-Type", "application/zip")
    h.send_header("Content-Disposition", _attachment(f"omni-shared-{len(names)}个文件.zip"))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.close_connection = True
    try:
        svc.stream_zip(names, h.wfile)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass


@api.post("/api/tools/open-folder", access="local")
def open_folder(req):
    subprocess.Popen(["xdg-open", svc.write_dir()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return req.json({"ok": True})


# ---------------------------------------------------------------- 分块上传

@api.get("/api/tools/uploads")
@guarded
def uploads(req):
    return req.json({"uploads": svc.list_uploads()})


@api.post("/api/tools/uploads")
@guarded
def create_upload(req):
    b = req.json_body()
    try:
        up = svc.create_upload(str(b.get("name") or ""), int(b.get("size") or 0), int(b.get("mtime") or 0),
                               str(b.get("client") or ""))
    except (TypeError, ValueError) as e:
        return req.error(400, str(e))
    return req.json(up)


@api.get("/api/tools/uploads/{id}")
@guarded
def upload_status(req):
    up = svc.get_upload(req.params["id"])
    return req.json(up) if up else req.error(404, "没有这个上传（可能已经完成或被放弃）")


@api.post("/api/tools/uploads/{id}")
@guarded
def upload_chunk(req):
    """请求体就是这一块的原始字节；?offset= 是这一块在文件里的起点。"""
    try:
        length = int(req.headers.get("Content-Length") or 0)
    except ValueError:
        return req.error(400, "缺少 Content-Length")
    try:
        result = svc.write_chunk(req.params["id"], req.int_arg("offset", -1), length, req.handler.rfile)
    except KeyError:
        svc._drain(req.handler.rfile, length)
        return req.error(404, "没有这个上传（可能已经完成或被放弃）")
    return req.json(result, 409 if result.get("mismatch") else 200)


@api.delete("/api/tools/uploads/{id}")
@guarded
def cancel_upload(req):
    return req.json({"ok": svc.cancel_upload(req.params["id"])})


# ---------------------------------------------------------------- 消息板

@api.get("/api/tools/texts")
@guarded
def texts(req):
    return req.json({"texts": svc.list_texts()})


@api.post("/api/tools/texts")
@guarded
def add_text(req):
    b = req.json_body()
    try:
        return req.json(svc.add_text(b.get("text", ""), str(b.get("from") or ""), str(b.get("client") or "")))
    except ValueError as e:
        return req.error(400, str(e))


@api.delete("/api/tools/texts/{id}")
@guarded
def delete_text(req):
    return req.json({"ok": svc.delete_text(req.params["id"])})
