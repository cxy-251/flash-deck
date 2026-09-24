"""
本地 HTTP 服务（0.0.0.0:8998）：大厅前端、游戏资源虚拟文件系统、全部 /api/*。

请求流程：parse_request 过整站闸门（局域网/广域网开关）→ 路由表匹配（各功能模块 api.py
登记）→ 按路由的访问级别鉴权 → 调处理函数；没匹配上的 GET/HEAD 查静态白名单。
"""
import importlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from omni.core import access, manifest
from omni.core.http import router, static
from omni.core.log import log

# 常驻挂载的功能模块（不对应单个 UI 分区的基础能力）；其余按 manifest 分区挂载
CORE_FEATURES = ["system", "privacy", "games", "library"]

# 游戏里常规的探测型 404（存档是否存在、缩略图还没生成……），不写日志
_QUIET_404 = ("HEAD ", "/save/", ".rpgsave", "favicon.ico", "/api/patch/",
              "/api/shortvideo/thumb", "/api/shortvideo/stream", "/api/shortvideo/gallery_image")

_GATE_PAGE = ("<html><body style='background:#0d1117;color:#f0f6fc;font-family:sans-serif;"
              "text-align:center;padding-top:80px;'><h2>{title}</h2>"
              "<p style='color:#8b949e;margin-top:12px;'>{desc}</p></body></html>")


def load_features():
    """导入全部功能模块的 api.py（导入即登记路由）。"""
    ids = list(CORE_FEATURES)
    for sid in manifest.section_ids():
        pkg = sid.split("-")[0]  # shortvideo-douyin 等变体共用 shortvideo 模块
        if pkg not in ids:
            ids.append(pkg)
    for pkg in ids:
        try:
            importlib.import_module(f"omni.features.{pkg}.api")
        except ModuleNotFoundError as e:
            # 游戏类分区（rpg/retro/...）共用 games 模块，没有自己的包
            if e.name not in (f"omni.features.{pkg}", f"omni.features.{pkg}.api"):
                raise


def _game_tag(path: str) -> str:
    from omni.features.games.registry import game_id_from_path
    return game_id_from_path(path) or "Server"


class Handler(BaseHTTPRequestHandler):
    server_version = "OmniDeck/3"

    def log_message(self, fmt, *args):
        try:
            req = str(args[0]) if args else ""
            code = str(args[1]) if len(args) > 1 else ""
            if code.startswith(("2", "3")):
                return
            if code == "404" and any(s in req for s in _QUIET_404):
                return
            log("ERROR" if code.startswith("5") else "WARN", f"HTTP {code} on {req}", tag=_game_tag(req))
        except Exception:
            pass

    def log_error(self, fmt, *args):
        try:
            msg = fmt % args
            if "favicon.ico" in self.path or "code 404" in msg:
                return
            log("ERROR", f"{msg} (path: {self.path})", tag=_game_tag(self.path))
        except Exception:
            pass

    def parse_request(self):
        if not super().parse_request():
            return False
        denied = access.gate(self)
        if denied:
            body = _GATE_PAGE.format(title=denied[0], desc=denied[1]).encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False
        return True

    def _dispatch(self, method):
        path, query = router.split_path(self.path)
        route, params = router.find(method, path)
        req = router.Request(self, method, path, query, params or {})
        if route is None and method == "HEAD":
            route, params = router.find("GET", path)
            if route is not None:
                req.params = params
        if route is not None:
            if not access.allowed(self, route.access):
                if route.deny:
                    return route.deny(req)
                if route.access == "local":
                    return req.error(403, "Forbidden: local-only")
                return req.error(403, "Forbidden: NSFW content is locked")
            return route.fn(req)
        if method in ("GET", "HEAD"):
            target = static.resolve(path)
            if target:
                return req.file(target)
            return req.not_found()
        if method == "POST":
            return req.error(404, "no such POST route")
        return req.send(405, b"")

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


class QuietServer(ThreadingHTTPServer):
    """客户端中途断开（拖进度条、切页面）是常态，不当错误刷屏。"""
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        if sys.exc_info()[0] in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)


_httpd = None


def start(port: int) -> QuietServer:
    """绑定端口并在后台线程里 serve_forever；绑定失败抛 OSError。"""
    global _httpd
    load_features()
    _httpd = QuietServer(("0.0.0.0", port), Handler)
    threading.Thread(target=_httpd.serve_forever, daemon=True, name="http").start()
    return _httpd


def stop() -> None:
    """释放监听端口。游戏模式下 Steam 用 SIGTERM 结束进程，不显式 server_close()
    的话 Chromium 子进程可能还持有套接字副本，下次启动 bind 失败。"""
    global _httpd
    srv, _httpd = _httpd, None
    if srv is None:
        return
    threading.Thread(target=srv.shutdown, daemon=True).start()
    try:
        srv.server_close()
    except Exception:
        pass
