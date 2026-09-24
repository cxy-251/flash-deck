"""
子进程生命周期：所有拉起的游戏/外部窗口/守护进程都登记在这里，退出时统一收尸。

游戏模式下 Steam 用 SIGTERM 结束应用，既不走 Qt 的 closeEvent 也不跑 atexit，所以
shutdown() 是 SIGTERM/SIGINT/窗口关闭/aboutToQuit 的共同出口：清子进程 → 执行登记的
清理钩子（释放 8998 端口等）→ 收掉 Chromium 等全部后代进程 → os._exit 硬退出。
"""
import atexit
import ctypes
import os
import signal
import threading

from omni.core.log import boot

ACTIVE_CHILDREN = []          # subprocess.Popen 对象
RUNNING_GAME_IDS = set()      # 正在运行的独立游戏，防重复启动
_shutdown_hooks = []
_shutting_down = False
_lock = threading.Lock()


def set_pdeathsig():
    """Popen(preexec_fn=...) 用：父进程死了子进程跟着收到 SIGKILL。"""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:
        pass


def track(proc) -> None:
    with _lock:
        ACTIVE_CHILDREN.append(proc)


def untrack(proc) -> None:
    with _lock:
        if proc in ACTIVE_CHILDREN:
            ACTIVE_CHILDREN.remove(proc)


def kill_children() -> None:
    with _lock:
        procs = list(ACTIVE_CHILDREN)
        ACTIVE_CHILDREN.clear()
    for proc in procs:
        try:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
        except Exception:
            pass


def reap_descendants(timeout: float = 3) -> None:
    """递归结束所有后代进程（QtWebEngineProcess、cloudflared、游戏……）。"""
    try:
        import psutil
    except Exception:
        try:
            os.killpg(os.getpgid(0), signal.SIGTERM)
        except Exception:
            pass
        return
    try:
        kids = psutil.Process().children(recursive=True)
    except Exception:
        return
    for p in kids:
        try:
            p.terminate()
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(kids, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass


def on_shutdown(fn) -> None:
    """登记退出清理钩子（比如释放 HTTP 端口）。"""
    _shutdown_hooks.append(fn)


def run_shutdown_hooks() -> None:
    for fn in list(_shutdown_hooks):
        try:
            fn()
        except Exception:
            pass


def shutdown(*_args) -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    boot(f"shutdown (args={_args})")
    kill_children()
    run_shutdown_hooks()
    reap_descendants()
    boot("shutdown: os._exit(0)")
    os._exit(0)


atexit.register(kill_children)
