"""
轻量路由：各功能模块在自己的 api.py 里用装饰器登记路由，不再往一个 1000 行的 do_GET 里塞 if。

    from omni.core.http import Api
    api = Api("manga")                       # 默认访问级别取 manifest 里 manga 分区的 access

    @api.get("/api/manga/library", deny=lambda req: req.json([]))
    def library(req):
        return req.json(service.get_local_library(req.arg("q")))

路径模式：精确匹配，或 {name}（单段）、{name:path}（剩余全部）占位。
访问级别：public（不限）/ nsfw（本机或已解锁）/ local（仅 Steam Deck 本机）。
未授权时默认回 403 JSON；有的列表接口约定「锁定时返回空列表」，用 deny= 指定。
"""
import json
import mimetypes
import os
import shutil
import urllib.parse

from omni.core import access

ACCESS_LEVELS = ("public", "nsfw", "local")

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/x-shockwave-flash", ".swf")
mimetypes.add_type("audio/mp4", ".m4b")
mimetypes.add_type("audio/mp4", ".m4a")

NO_STORE = "no-store, no-cache, must-revalidate, max-age=0"


class Route:
    __slots__ = ("method", "pattern", "segments", "fn", "access", "deny")

    def __init__(self, method, pattern, fn, access_level, deny):
        self.method = method
        self.pattern = pattern
        self.segments = pattern.strip("/").split("/") if pattern != "/" else [""]
        self.fn = fn
        self.access = access_level
        self.deny = deny

    def match(self, parts):
        params = {}
        for i, seg in enumerate(self.segments):
            if seg.startswith("{") and seg.endswith("}"):
                name = seg[1:-1]
                if name.endswith(":path"):
                    params[name[:-5]] = "/".join(parts[i:])
                    return params
                if i >= len(parts):
                    return None
                params[name] = parts[i]
            elif i >= len(parts) or parts[i] != seg:
                return None
        return params if len(parts) == len(self.segments) else None


ROUTES = []


def find(method, path):
    parts = path.strip("/").split("/") if path != "/" else [""]
    for r in ROUTES:
        if r.method == method:
            params = r.match(parts)
            if params is not None:
                return r, params
    return None, None


class Api:
    """一个功能模块的路由登记入口；section 对应 manifest 里的分区 id（决定默认访问级别）。"""

    def __init__(self, section=None, access_level=None):
        if access_level is None:
            from omni.core import manifest
            access_level = manifest.access(section) if section else "public"
        assert access_level in ACCESS_LEVELS, access_level
        self.default_access = access_level

    def route(self, method, pattern, access_level=None, deny=None):
        def deco(fn):
            ROUTES.append(Route(method, pattern, fn, access_level or self.default_access, deny))
            return fn
        return deco

    def get(self, pattern, access=None, deny=None):
        return self.route("GET", pattern, access, deny)

    def post(self, pattern, access=None, deny=None):
        return self.route("POST", pattern, access, deny)

    def head(self, pattern, access=None, deny=None):
        return self.route("HEAD", pattern, access, deny)

    def delete(self, pattern, access=None, deny=None):
        return self.route("DELETE", pattern, access, deny)


class Request:
    """包一层 BaseHTTPRequestHandler：取参数 + 写响应的常用操作。"""

    def __init__(self, handler, method, path, query, params):
        self.handler = handler
        self.method = method
        self.path = path              # 已 unquote、不含 query 的路径
        self.raw_path = handler.path
        self.query = query            # dict[str, list[str]]
        self.params = params
        self.headers = handler.headers
        self._body = None

    # ---------------------------------------------------------------- 请求
    def arg(self, name, default=""):
        values = self.query.get(name)
        return values[0] if values and values[0] != "" else default

    def int_arg(self, name, default=0):
        try:
            return int(self.arg(name, default))
        except (TypeError, ValueError):
            return default

    def flag(self, name):
        return self.arg(name, "0") in ("1", "true", "True")

    def body(self) -> bytes:
        if self._body is None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            self._body = self.handler.rfile.read(length) if length > 0 else b""
        return self._body

    def json_body(self) -> dict:
        raw = self.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @property
    def is_local(self) -> bool:
        return access.is_local(self.handler)

    @property
    def nsfw_ok(self) -> bool:
        return access.nsfw_authorized(self.handler)

    # ---------------------------------------------------------------- 响应
    def send(self, status, body=b"", ctype=None, headers=None):
        h = self.handler
        hdrs = {"Access-Control-Allow-Origin": "*"}
        if ctype:
            hdrs["Content-Type"] = ctype
        if body is not None:
            hdrs["Content-Length"] = str(len(body))
        hdrs.update(headers or {})
        hdrs.setdefault("Cache-Control", NO_STORE)
        h.send_response(status)
        for k, v in hdrs.items():
            h.send_header(k, v)
        h.end_headers()
        if body and self.method != "HEAD":
            try:
                h.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def json(self, data, status=200, headers=None):
        return self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", headers)

    def error(self, status, message, **extra):
        return self.json({"error": message, **extra}, status)

    def text(self, text, status=200, ctype="text/plain; charset=utf-8"):
        return self.send(status, text.encode("utf-8") if isinstance(text, str) else text, ctype)

    def not_found(self):
        return self.send(404, b"")

    def file(self, path, ctype=None, headers=None):
        """发送本地文件，支持 HTTP Range 分段（音视频拖进度条、大文件断点）。"""
        try:
            size = os.path.getsize(path)
        except OSError:
            return self.not_found()
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        hdrs = {"Accept-Ranges": "bytes", **(headers or {})}
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        status = 200
        if rng.startswith("bytes=") and size > 0:
            first = rng[6:].split(",")[0].strip()
            a, _, b = first.partition("-")
            try:
                if a:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                if start > end or start >= size:
                    return self.send(416, b"", headers={"Content-Range": f"bytes */{size}"})
                status = 206
                hdrs["Content-Range"] = f"bytes {start}-{end}/{size}"
            except ValueError:
                start, end, status = 0, size - 1, 200
        length = end - start + 1 if size else 0
        h = self.handler
        h.send_response(status)
        hdrs.setdefault("Cache-Control", NO_STORE)
        for k, v in {"Access-Control-Allow-Origin": "*", "Content-Type": ctype,
                     "Content-Length": str(length), **hdrs}.items():
            h.send_header(k, v)
        h.end_headers()
        if self.method == "HEAD" or not length:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                if status == 200:
                    shutil.copyfileobj(f, h.wfile, 256 * 1024)
                    return
                left = length
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    h.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def split_path(raw_path):
    parsed = urllib.parse.urlsplit(raw_path)
    return urllib.parse.unquote(parsed.path), urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
