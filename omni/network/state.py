"""局域网/广域网共享开关的持久化（var/config/network.json：{"lan": bool, "wan": bool}）。"""
import json
import os
import threading

from omni.core import paths

_lock = threading.Lock()


def load() -> dict:
    try:
        with open(paths.NETWORK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(**changes) -> None:
    with _lock:
        data = load()
        data.update({k: bool(v) for k, v in changes.items()})
        os.makedirs(paths.CONFIG, exist_ok=True)
        with open(paths.NETWORK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
