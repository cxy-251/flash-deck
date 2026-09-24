"""
系统 API：实例探活、内存、日志面板、局域网/广域网开关、SSE 事件流、UI manifest。
"""
import json
import os
import queue
import re
import subprocess

from omni.core import events, manifest, paths, settings
from omni.core.http import Api
from omni.core.log import BUFFER, log
from omni.network import lan, wan

api = Api(access_level="public")

INSTANCE_MAGIC = "omni-deck-core/1"   # 单实例探测握手标识（app.ensure_single_instance 用）


@api.get("/api/_alive")
def alive(req):
    return req.json({"magic": INSTANCE_MAGIC, "pid": os.getpid()})


@api.get("/api/_mem")
def mem(req):
    info = {"pid": os.getpid(), "restart_threshold_mb": settings.get("mem_restart_mb"), "procs": []}
    try:
        import psutil
        me = psutil.Process()
        total = 0
        for p in [me] + me.children(recursive=True):
            try:
                rss = p.memory_info().rss
                total += rss
                info["procs"].append({"pid": p.pid, "name": (p.name() or "")[:40],
                                      "rss_mb": round(rss / 1048576, 1), "threads": p.num_threads()})
            except Exception:
                pass
        info["total_rss_mb"] = round(total / 1048576, 1)
        info["procs"].sort(key=lambda x: -x["rss_mb"])
    except Exception as e:
        info["error"] = str(e)
    return req.json(info)


@api.get("/api/manifest")
def get_manifest(req):
    return req.json(manifest.load())


# ------------------------------------------------------------------ 日志面板

@api.get("/api/logs")
def logs(req):
    level = req.arg("level").upper()
    tag = req.arg("tag")
    game_id = req.arg("game_id")
    limit = max(1, min(req.int_arg("lines", 200), 1000))

    game_log = None
    if game_id:
        glog = paths.game_log(re.sub(r"\W+", "_", str(game_id)).strip("_"))
        if os.path.exists(glog):
            try:
                with open(glog, "r", encoding="utf-8", errors="ignore") as f:
                    game_log = "".join(f.readlines()[-limit:])
            except Exception as e:
                game_log = f"读取游戏日志失败: {e}"
        else:
            game_log = "暂无该游戏的独立进程输出日志 (游戏尚未运行或已清理)"

    available = []
    if os.path.isdir(paths.GAME_LOGS):
        for f in sorted(os.listdir(paths.GAME_LOGS)):
            if f.startswith("game_") and f.endswith(".log"):
                try:
                    st = os.stat(os.path.join(paths.GAME_LOGS, f))
                    available.append({"filename": f, "size": st.st_size, "mtime": st.st_mtime, "game_key": f[5:-4]})
                except OSError:
                    pass

    entries = list(BUFFER)
    if level and level != "ALL":
        entries = [e for e in entries if e.get("level") == level]
    if tag:
        entries = [e for e in entries if tag.lower() in e.get("tag", "").lower()]
    return req.json({"status": "ok", "logs": entries[-limit:], "game_log": game_log,
                     "available_game_logs": available})


@api.post("/api/logs/clear")
def clear_logs(req):
    BUFFER.clear()
    log("INFO", "全局日志缓冲区已成功清空", tag="System")
    return req.json({"status": "ok"})


@api.get("/api/open_external_url", access="local")
def open_external_url(req):
    url = req.arg("url")
    if url.startswith(("http://", "https://")):
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    return req.json({"status": "ok"})


# ------------------------------------------------------------------ 网络

def _client_status(req):
    return {**lan.status(), "is_local": req.is_local, "is_remote": not req.is_local}


@api.get("/api/lan/status")
def lan_status(req):
    from omni.core import access
    return req.json({**_client_status(req), "client_ip": access.client_ip(req.handler), "unlocked": req.nsfw_ok})


api.get("/api/client/info")(lan_status)


@api.get("/api/wan/status")
def wan_status(req):
    return req.json(wan.status())


def broadcast_network_status():
    events.broadcast({"type": "network_status", "lan": lan.status(), "wan": wan.status()})


@api.post("/api/lan/toggle", access="local",
          deny=lambda req: req.json({"status": "error", "error": "🔒 局域网网络开关仅限在 Steam Deck 本机控制"}, 403))
def lan_toggle(req):
    body = req.json_body()
    lan.set_enabled(body["enabled"] if "enabled" in body else not lan.enabled())
    broadcast_network_status()
    return req.json({"status": "ok", **lan.status()})


@api.post("/api/wan/toggle", access="local",
          deny=lambda req: req.json({"status": "error", "error": "🔒 广域网公网访问开关仅限在 Steam Deck 本机控制"}, 403))
def wan_toggle(req):
    body = req.json_body()
    wan.set_enabled(body["enabled"] if "enabled" in body else not wan.enabled())
    broadcast_network_status()
    return req.json(wan.status())


# ------------------------------------------------------------------ SSE 事件流

def _event_stream(req):
    h = req.handler
    h.send_response(200)
    for k, v in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-cache"),
                 ("Connection", "keep-alive"), ("Access-Control-Allow-Origin", "*")):
        h.send_header(k, v)
    h.end_headers()
    q = events.subscribe()
    try:
        init = events.init_payload()
        init["lan"] = _client_status(req)
        init["wan"] = wan.status()
        h.wfile.write(f"data: {json.dumps(init, ensure_ascii=False)}\n\n".encode("utf-8"))
        h.wfile.flush()
        while True:
            try:
                ev = q.get(timeout=20)
                h.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
            except queue.Empty:
                h.wfile.write(b": keepalive\n\n")
            h.wfile.flush()
    except Exception:
        pass
    finally:
        events.unsubscribe(q)


api.get("/api/events")(_event_stream)
api.get("/api/manga/events")(_event_stream)   # 旧地址
