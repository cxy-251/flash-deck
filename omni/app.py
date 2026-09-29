"""
Omni Deck 启动编排：状态迁移 → 单实例检查 → 本地 HTTP 服务 → 后台任务 → Qt 桌面壳。

    python main.py                       # 正常启动（run.sh / Steam 快捷方式走这里）
    python -m omni --headless --port 8997 --no-workers   # 只起 HTTP 服务（测试用）
"""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

from omni.core import endpoints, paths

DEFAULT_PORT = 8998

CHROMIUM_ARGS = [
    f"--disk-cache-dir={paths.ENGINE_CACHE}",
    "--disk-cache-size=1073741824",
    "--media-cache-size=536870912",
    "--max-connections-per-host=16",
    "--no-proxy-server",
    "--proxy-server=direct://",
    "--proxy-bypass-list=*",
    "--enable-gpu-rasterization",
    "--disable-gpu-watchdog",
    "--disable-gpu-process-crash-limit",
    "--enable-webgl",
    "--no-sandbox",
    "--autoplay-policy=no-user-gesture-required",
    "--allow-running-insecure-content",
    "--ignore-certificate-errors",
]


def _parse_args(argv):
    ap = argparse.ArgumentParser(prog="omni", add_help=True)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--headless", action="store_true", help="只起 HTTP 服务，不开窗口")
    ap.add_argument("--no-workers", action="store_true", help="不启动后台任务（广域网隧道、漫画元数据巡检）")
    args, qt_args = ap.parse_known_args(argv)
    return args, qt_args


def _clear_proxy_env():
    """外部代理环境变量一律清掉，强制直连（本地服务 + 游戏资源都走 127.0.0.1）。"""
    for var in ("http_proxy", "https_proxy", "all_proxy", "socks_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        os.environ.pop(var, None)
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"


# --------------------------------------------------------------------------- 单实例

def _port_holder_pids(port):
    pids = set()
    try:
        import psutil
        for c in psutil.net_connections(kind="inet"):
            if c.laddr and c.laddr.port == port and c.pid and c.pid != os.getpid():
                pids.add(c.pid)
        if pids:
            return pids
    except Exception:
        pass
    try:
        out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, timeout=3).stdout
        pids |= {int(m) for m in re.findall(r"pid=(\d+)", out) if int(m) != os.getpid()}
    except Exception:
        pass
    return pids


def _port_in_use(port) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((endpoints.LOOPBACK, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def ensure_single_instance(port):
    """必须在绑定端口、加载 QtWebEngine 之前调用。游戏模式下第二个实例会让 gamescope 合成器
    死锁（两个 Chromium 内核抢 GPU/EGL），所以第二个实例要干净退出。

    这里绝不 kill 任何进程：端口被占 = 已有实例（不管健康与否）= 本次直接退出。以前探测超时
    会把持有端口的进程当"僵尸"杀掉，而那可能正是正常在跑的第一个实例。"""
    import http.client
    from omni.core.log import boot
    from omni.features.system.api import INSTANCE_MAGIC
    boot("ensure_single_instance: probing /api/_alive …")
    try:
        conn = http.client.HTTPConnection(endpoints.LOOPBACK, port, timeout=1.5)
        conn.request("GET", "/api/_alive")
        data = json.loads(conn.getresponse().read() or b"{}")
        conn.close()
        if isinstance(data, dict) and data.get("magic") == INSTANCE_MAGIC:
            boot(f"ensure_single_instance: healthy instance pid={data.get('pid')} → exit(0)")
            print(f"[!] Omni Deck 已在运行 (PID {data.get('pid')})，退出本次启动。")
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        boot(f"ensure_single_instance: probe failed ({type(e).__name__}: {e})")
    holders = _port_holder_pids(port)
    if holders or _port_in_use(port):
        boot(f"ensure_single_instance: port {port} busy holders={sorted(holders)} → exit(0) (NOT killing anything)")
        print(f"[!] 端口 {port} 已被占用（可能有实例卡住了）——本次不启动，避免游戏模式合成器死锁。"
              f" 如需强制：先结束 pid {sorted(holders) or '?'}。")
        sys.exit(0)


# --------------------------------------------------------------------------- 入口

def _tune_malloc():
    """glibc 的默认内存策略在这个进程里会把 RSS 越撑越大，启动时（还没起任何线程前）改掉。

    多联三路播放器不停换片，抖音不少竖屏视频是 1900x3378 的 HEVC，一帧解码缓冲就十几到二十几 MB。
    glibc 的 mmap 阈值是动态的：大块释放一次，阈值就往上涨（最高 32MB），之后这些帧缓冲都改从
    每线程的 malloc arena 里分配，释放后碎在里面还不给系统。几十个线程各一个 arena（最多 8×核数个），
    实测三屏各换 80 条片就涨到 1.5GB。固定阈值 1MB（大块一律 mmap，释放即归还）+ 最多 4 个 arena
    之后同样的测试稳定在 370MB 左右。"""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        M_MMAP_THRESHOLD, M_ARENA_MAX = -3, -8
        libc.mallopt(M_MMAP_THRESHOLD, 1 << 20)
        libc.mallopt(M_ARENA_MAX, 4)
    except (OSError, AttributeError):
        pass


def _set_process_name(name: str = "omni-deck"):
    """进程列表里默认显示解释器的名字（python）。prctl(PR_SET_NAME) 改的是 /proc/<pid>/comm，
    系统监视器 / top / ps 显示的就是它（最长 15 字节）；之后新开的线程也继承这个名字。
    不改 Qt 的 applicationName：那会改变 QtWebEngine 配置目录的位置，网页里存的东西就像被清空了。"""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        PR_SET_NAME = 15
        ctypes.CDLL("libc.so.6").prctl(PR_SET_NAME, name.encode()[:15], 0, 0, 0)
    except (OSError, AttributeError):
        pass


def main(argv=None):
    _tune_malloc()
    _set_process_name()
    args, qt_args = _parse_args(sys.argv[1:] if argv is None else argv)

    from omni.core import migrate
    migrate.run()                    # 旧版本的状态目录/配置 → var/（必须在其它模块 import 之前）
    paths.ensure_state_dirs()

    from omni.core.log import boot, log
    boot("=" * 60)
    boot(f"BOOT start argv={sys.argv} port={args.port} headless={args.headless}")
    boot("env: " + " ".join(f"{k}={os.environ.get(k, '-')}" for k in (
        "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY", "DISPLAY",
        "QT_QPA_PLATFORM", "SteamDeck", "SteamGamepadUI", "STEAM_COMPAT_LAUNCHER_SERVICE", "SteamAppId")))
    _clear_proxy_env()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--enable-features=WebAssemblyThreads,SharedArrayBuffer --enable-webgl "
        "--ignore-gpu-blocklist --enable-gpu-rasterization")

    from omni.core import process
    from omni.core.http import server
    from omni.network import lan, wan

    lan.PORT = args.port
    ensure_single_instance(args.port)
    boot("starting local HTTP server")
    try:
        server.start(args.port)
    except OSError as e:
        boot(f"HTTP server bind FAILED: {e}")
        log("ERROR", f"本地核心服务无法绑定 0.0.0.0:{args.port}（可能已有实例或端口未释放）：{e}", tag="Core")
        sys.exit(1)
    process.on_shutdown(server.stop)
    boot(f"HTTP server bound 0.0.0.0:{args.port}")
    # 游戏库不在启动时预扫：133 个游戏找主程序要走十几万个文件，冷启动能卡十几秒。
    # 打开游戏分区时 /api/games 自己会扫（目录没变就秒回），按 id 查游戏时也会按需补扫。

    if not args.no_workers:
        wan.start_daemon()
        from omni.features.manga import service as manga
        manga.start_auto_metadata_audit()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, process.shutdown)
        except Exception:
            pass

    if args.headless:
        boot("headless: serving without window")
        while True:
            time.sleep(3600)

    _run_qt(qt_args)


def _run_qt(qt_args):
    from omni.core import process
    from omni.core.log import boot
    boot("importing Qt / shell …")
    from omni.shell.window import MainWindow, QApplication, QTimer

    app = QApplication([sys.argv[0]] + qt_args + CHROMIUM_ARGS)
    app.aboutToQuit.connect(process.shutdown)
    # Qt 的 C++ 事件循环会压住 Python 信号处理，用空转定时器定期把控制权交回解释器
    sig_timer = QTimer()
    sig_timer.start(300)
    sig_timer.timeout.connect(lambda: None)

    window = MainWindow()
    window.show()
    boot("entering app.exec()  ← 如果 boot.log 停在这行，说明进了事件循环、Qt/合成器层面卡住")
    sys.exit(getattr(app, "exec", getattr(app, "exec_", None))())


if __name__ == "__main__":
    main()
