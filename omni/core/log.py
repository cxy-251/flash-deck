"""
日志：
  • boot(msg)  —— 启动追踪，每行立即落盘到 var/logs/boot.log。专门查「游戏模式下第二次打开
                  卡死、只能硬重启」这类问题：硬重启后 stdout/stderr 全丢，只有落盘的能留下来。
  • log(level, msg, tag) —— 全局分级日志：内存环形缓冲（给日志面板）+ omni_deck.log + 彩色 stderr。
"""
import datetime
import os
import sys
import time
from collections import deque

from omni.core import paths

_BOOT_T0 = time.time()
BUFFER = deque(maxlen=1000)

_COLORS = {"ERROR": "\033[91m", "WARN": "\033[93m", "INFO": "\033[92m", "DEBUG": "\033[94m"}


def boot(msg: str) -> None:
    line = (f"{datetime.datetime.now().isoformat(timespec='milliseconds')} "
            f"pid={os.getpid()} +{time.time() - _BOOT_T0:6.2f}s  {msg}")
    try:
        os.makedirs(paths.LOGS, exist_ok=True)
        # 超过 200KB 只保留最近 300 行，够覆盖好几次启动
        if os.path.exists(paths.BOOT_LOG) and os.path.getsize(paths.BOOT_LOG) > 200_000:
            try:
                with open(paths.BOOT_LOG, "r", errors="replace") as f:
                    tail = f.readlines()[-300:]
                with open(paths.BOOT_LOG, "w") as f:
                    f.writelines(tail)
            except Exception:
                pass
        with open(paths.BOOT_LOG, "a", buffering=1) as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print("[boot]", msg, flush=True)
    except Exception:
        pass


def log(level: str, msg: str, tag: str = None) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = "[Omni-Deck]" + (f"[{tag}]" if tag else "") + f"[{level}]"
    BUFFER.append({
        "time": timestamp,
        "level": level,
        "tag": tag or "Core",
        "msg": msg,
        "text": f"[{timestamp}] {prefix} {msg}",
    })
    try:
        with open(paths.APP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {prefix} {msg}\n")
    except Exception:
        pass
    try:
        sys.stderr.write(f"{_COLORS.get(level, chr(27) + '[97m')}{prefix} {msg}\033[0m\n")
        sys.stderr.flush()
    except Exception:
        pass
