"""
内存压力看门狗：系统内存紧张时 Omni 自己先收一收，别等系统拿交换分区硬扛。

每 INTERVAL 秒看一眼两个指标：
  - /proc/meminfo 的 MemAvailable 占 MemTotal 的比例（还能给程序用的内存）
  - /proc/pressure/memory 的 some avg10（PSI：最近 10 秒里有多少时间有进程在等内存，内核 4.20+）
进入「紧张」：可用 < TIGHT_AVAILABLE，或 PSI ≥ TIGHT_PSI；
解除：可用 ≥ CALM_AVAILABLE 且 PSI < CALM_PSI，连续 CALM_CHECKS 次（留个回差，免得在边上来回抖）。

紧张时：
  - 后台补元数据（media_index 的 ffprobe 循环）在 wait_if_tight() 处停住，缓过来再接着补
  - Python 这边 gc + malloc_trim，把空出来的堆还给系统
  - SSE 广播 {"type": "memory_pressure", "tight": true}：网页把「离开后等着清理」的分区马上清掉
  - on_pressure() 登记的回调（功能模块自己的缓存之类）
"""
import ctypes
import gc
import sys
import threading
import time

from omni.core import events
from omni.core.log import log

INTERVAL = 5
TIGHT_AVAILABLE = 0.10
TIGHT_PSI = 10.0
CALM_AVAILABLE = 0.15
CALM_PSI = 2.0
CALM_CHECKS = 3

_tight = threading.Event()
_callbacks = []
_started = False


def tight() -> bool:
    return _tight.is_set()


def wait_if_tight(poll: float = 2.0) -> None:
    """后台的「不着急」的活（补元数据之类）每做一件前调一下：内存紧张就在这儿等着，缓过来再继续。"""
    while _tight.is_set():
        time.sleep(poll)


def on_pressure(fn) -> None:
    """登记回调 fn(tight: bool)：进入 / 解除紧张时各调一次。"""
    _callbacks.append(fn)


def read() -> dict:
    """当前指标：available（可用比例 0~1）、psi（some avg10，百分比；读不到为 0）。"""
    info = {}
    with open("/proc/meminfo", "r") as f:
        for line in f:
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                info[key] = int(rest.split()[0])
    psi = 0.0
    try:
        with open("/proc/pressure/memory", "r") as f:
            for line in f:
                if line.startswith("some"):
                    psi = float(line.split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        pass
    total = info.get("MemTotal") or 1
    return {"available": info.get("MemAvailable", total) / total, "psi": psi}


def release_memory() -> None:
    """Python 侧能还的都还：回收循环引用，再让 glibc 把空闲的堆页还给系统。"""
    gc.collect()
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


def _set(state: bool, m: dict) -> None:
    if state:
        _tight.set()
    else:
        _tight.clear()
    log("WARN" if state else "INFO",
        f"内存{'紧张' if state else '缓解'}：可用 {m['available']:.0%}，PSI {m['psi']:.1f}%"
        + ("，暂停后台补元数据、释放缓存" if state else "，恢复后台任务"), tag="Memory")
    if state:
        release_memory()
    for fn in list(_callbacks):
        try:
            fn(state)
        except Exception:
            pass
    events.broadcast({"type": "memory_pressure", "tight": state})


def _loop() -> None:
    calm = 0
    while True:
        try:
            m = read()
        except OSError:
            time.sleep(INTERVAL)
            continue
        if not _tight.is_set():
            if m["available"] < TIGHT_AVAILABLE or m["psi"] >= TIGHT_PSI:
                _set(True, m)
                calm = 0
        else:
            calm = calm + 1 if (m["available"] >= CALM_AVAILABLE and m["psi"] < CALM_PSI) else 0
            if calm >= CALM_CHECKS:
                _set(False, m)
        time.sleep(INTERVAL)


def start() -> None:
    global _started
    if _started or not sys.platform.startswith("linux"):
        return
    _started = True
    threading.Thread(target=_loop, name="memwatch", daemon=True).start()
