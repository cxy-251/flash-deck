"""局域网共享：开关状态、本机局域网 IP、给前端的状态字典。"""
import socket
import time

from omni.network import state

PORT = 8998            # app 启动时按 --port 覆盖
_enabled = bool(state.load().get("lan", False))
_ip_cache = ("127.0.0.1", 0.0)


def local_ip() -> str:
    """本机在局域网里的 IPv4（UDP connect 探测路由，不发包），30 秒缓存。"""
    global _ip_cache
    ip, ts = _ip_cache
    if time.time() - ts < 30:
        return ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    _ip_cache = (ip, time.time())
    return ip


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
    state.save(lan=_enabled)


def status() -> dict:
    ip = local_ip()
    return {"enabled": _enabled, "ip": ip, "port": PORT, "url": f"http://{ip}:{PORT}"}
