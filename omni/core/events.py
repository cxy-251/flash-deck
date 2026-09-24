"""
全局事件总线：后台任务（漫画/小说下载进度、元数据巡检、网络开关变化……）调 broadcast()，
所有连着 /api/events（SSE）的页面实时收到。
"""
import queue
import threading

_listeners = set()
_lock = threading.Lock()


def subscribe() -> queue.Queue:
    q = queue.Queue()
    with _lock:
        _listeners.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        _listeners.discard(q)


def _sanitize(obj):
    """去掉下划线私有字段和 Queue 对象，保证能 json.dumps。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()
                if not str(k).startswith("_") and not isinstance(v, queue.Queue)}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def broadcast(event: dict) -> None:
    clean = _sanitize(event)
    with _lock:
        for q in list(_listeners):
            try:
                q.put_nowait(clean)
            except Exception:
                pass


# SSE 连接建立时推给客户端的初始状态：各功能模块登记自己的那部分（比如漫画登记下载队列），
# 系统模块只负责拼起来，不需要认识具体功能。
_init_providers = []


def on_init(fn) -> None:
    """登记一个返回 dict 的函数，其结果并入 SSE 的 init 事件。"""
    _init_providers.append(fn)


def init_payload() -> dict:
    data = {"type": "init"}
    for fn in _init_providers:
        try:
            data.update(fn() or {})
        except Exception:
            pass
    return data
