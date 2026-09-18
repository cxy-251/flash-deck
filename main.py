import os
import sys
import shutil
import threading
import subprocess
import json
import re
import socket
import struct
import time
import urllib.parse
import atexit
import signal
import ctypes
import mimetypes
import datetime
from collections import deque
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "services"))
from app_config import find_library_dirs, get_library_roots, get_wan_domain
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 启动追踪日志：写到 cache/boot.log（每行立即 flush），专门查"游戏模式下第二次
# 打开卡死、切不到桌面、只能重启"这类问题 —— 硬重启后 stdout/stderr 全丢，只有
# 落盘的文件能留下"这次启动走到哪一步就不动了"。
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BOOT_LOG = os.path.join(_SCRIPT_DIR, "cache", "boot.log")
_BOOT_T0 = time.time()

def _boot(msg: str) -> None:
    """把启动阶段的追踪日志写到 cache/boot.log（带时间戳/pid/相对启动耗时），超长自动截断。

    专门用来排查"游戏模式下第二次打开卡死/切不到桌面"这类硬重启后 stdout/stderr
    全丢的问题——这份日志是唯一能留下来的线索。

    Args:
        msg: 本条日志的正文内容。
    """
    line = f"{datetime.datetime.now().isoformat(timespec='milliseconds')} " \
           f"pid={os.getpid()} +{time.time() - _BOOT_T0:6.2f}s  {msg}"
    try:
        os.makedirs(os.path.dirname(_BOOT_LOG), exist_ok=True)
        # 开头修剪，别让文件无限长（保留最近 ~400 行，够覆盖好几次启动）
        if os.path.exists(_BOOT_LOG) and os.path.getsize(_BOOT_LOG) > 200_000:
            try:
                with open(_BOOT_LOG, "r", errors="replace") as f:
                    tail = f.readlines()[-300:]
                with open(_BOOT_LOG, "w") as f:
                    f.writelines(tail)
            except Exception:
                pass
        with open(_BOOT_LOG, "a", buffering=1) as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass
    try:
        print("[boot]", msg, flush=True)
    except Exception:
        pass

_boot("=" * 60)
_boot(f"BOOT start  argv={sys.argv}")
_boot("env: " + " ".join(
    f"{k}={os.environ.get(k, '-')}" for k in (
        "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY",
        "DISPLAY", "QT_QPA_PLATFORM", "SteamDeck", "SteamGamepadUI",
        "STEAM_COMPAT_LAUNCHER_SERVICE", "SteamAppId",
    )
))
_boot("stdlib imports done, importing services…")

mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/x-shockwave-flash', '.swf')
mimetypes.add_type('audio/mp4', '.m4b')
mimetypes.add_type('audio/mp4', '.m4a')
import manga_service
_boot("imported manga_service")
import novel_service
_boot("imported novel_service")
import audio_service
_boot("imported audio_service")
import shortvideo_service
_boot("imported shortvideo_service")
import mega_service
import sc2_panel_service
import privacy_service
import crawler_service
_boot("all service imports done")

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--enable-features=WebAssemblyThreads,SharedArrayBuffer "
    "--enable-webgl "
    "--ignore-gpu-blocklist "
    "--enable-gpu-rasterization"
)

ACTIVE_CHILD_PROCESSES = []
RUNNING_GAME_IDS = set()  # 当前正在运行的游戏 ID 集合，防止重复启动同一游戏
HTTPD = None              # 本地 HTTP 核心服务实例，供退出时主动关闭并释放 8998 端口
_INSTANCE_MAGIC = "omni-deck-core/1"  # 单实例探测握手标识
_SHUTTING_DOWN = False    # graceful_shutdown 幂等标记

def set_pdeathsig():
    """在 Linux 下设置子进程随父进程一同销毁 (Parent Death Signal)"""
    try:
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(1, signal.SIGKILL) # PR_SET_PDEATHSIG = 1
    except Exception:
        pass

def kill_all_child_processes():
    """彻底终止并清理 Omni Deck 打开的所有子进程和进程组"""
    for proc in list(ACTIVE_CHILD_PROCESSES):
        try:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
        except Exception:
            pass
    ACTIVE_CHILD_PROCESSES.clear()

def _release_http_server():
    """主动关闭本地 HTTP 核心服务并释放 8998 监听套接字。
    游戏模式下 Steam 用 SIGTERM 结束进程，不会走 Qt 的 closeEvent，
    若不显式 server_close()，QtWebEngine 的 Chromium 子进程可能仍持有该
    套接字副本，导致端口一直不释放、下次启动 bind 失败。"""
    global HTTPD
    srv = HTTPD
    HTTPD = None
    if srv is None:
        return
    try:
        threading.Thread(target=srv.shutdown, daemon=True).start()
    except Exception:
        pass
    try:
        srv.server_close()
    except Exception:
        pass

def _reap_descendants(timeout=3):
    """递归结束所有后代进程：QtWebEngineProcess / Chromium zygote·GPU·渲染进程、
    cloudflared、本地 DNS 助手、以及已拉起的游戏进程。"""
    try:
        import psutil
    except Exception:
        try:
            os.killpg(os.getpgid(0), signal.SIGTERM)
        except Exception:
            pass
        return
    try:
        me = psutil.Process()
        kids = me.children(recursive=True)
    except Exception:
        return
    for p in kids:
        try:
            p.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(kids, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass

def graceful_shutdown(*_args):
    """SIGTERM / SIGINT / aboutToQuit 统一入口：清子进程 → 释放端口 → 收后代 → 硬退出。
    末尾 os._exit 确保即使 Qt 或后台线程卡住，进程也一定结束（游戏模式下这点最关键）。"""
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    _boot(f"graceful_shutdown (args={_args})")
    try:
        kill_all_child_processes()
    except Exception:
        pass
    _release_http_server()
    _reap_descendants()
    _boot("graceful_shutdown: os._exit(0)")
    os._exit(0)

atexit.register(kill_all_child_processes)
atexit.register(lambda: _boot("atexit: process exiting"))

# 1. 彻底清除外部代理环境变量，强制直连
for env_var in [
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "socks_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "SOCKS_PROXY",
]:
    if env_var in os.environ:
        del os.environ[env_var]

os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_DIR = os.path.expanduser("~")

# ==========================================
# 全局路径配置 (Global Path Configuration)
# 支持通过环境变量直接覆盖，彻底解耦硬编码路径
# ==========================================
SD_CARD_ROOT = os.environ.get("OMNI_SD_ROOT", "/run/media/deck/FUCKDECK")
GAMES_BASE_DIR = os.environ.get("OMNI_GAMES_DIR", os.path.join(HOME_DIR, "Games"))
RENPY_SDK_PATH = os.environ.get("RENPY_SDK_PATH", os.path.join(HOME_DIR, "Applications", "renpy-8.5.3-sdk", "renpy.sh"))
SC2_DIR = os.environ.get("SC2_DIR", os.path.join(GAMES_BASE_DIR, "StarCraft II"))
STEAM_COMPAT_DATA_DIR = os.path.join(HOME_DIR, ".local", "share", "Steam", "steamapps", "compatdata")
WEIYUN_STEAM_PATH = os.path.join(STEAM_COMPAT_DATA_DIR, "3498387003", "pfx", "drive_c", "users", "steamuser", "AppData", "Local", "Programs", "WeiyunApp")

FLASH_GAMES_DIR = os.path.join(SCRIPT_DIR, "flash_games")
PLUGINS_DIR = os.path.join(FLASH_GAMES_DIR, "plugins")
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
RPG_GAMES_DIR = os.path.join(SCRIPT_DIR, "rpg_games")
RENPY_GAMES_DIR = os.path.join(SCRIPT_DIR, "renpy_games")
RETRO_GAMES_DIR = os.path.join(SCRIPT_DIR, "retro_games")
SLG_GAMES_DIR = os.path.join(SCRIPT_DIR, "slg_games")
EMULATORJS_DIR = os.path.join(RETRO_GAMES_DIR, "emulatorjs")
HUB_HTML_PATH = os.path.join(ASSETS_DIR, "hub.html")
HUB_JS_PATH = os.path.join(ASSETS_DIR, "hub.js")
PLAYER_RETRO_HTML = os.path.join(ASSETS_DIR, "player_retro.html")
PLAYER_FLASH_HTML = os.path.join(ASSETS_DIR, "player_flash.html")
PORT = 8998

os.makedirs(os.path.join(SCRIPT_DIR, "config"), exist_ok=True)
LAN_CONFIG_FILE = os.path.join(SCRIPT_DIR, "config", ".lan_config.json")

def get_local_ip() -> str:
    """
    通过 UDP Socket 探测当前设备在局域网内分配到的物理 IPv4 地址。
    不发出真实数据包，仅探测最优路由网卡，失败时回退到 '127.0.0.1'。
    """
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def load_lan_sharing_enabled() -> bool:
    """从磁盘配置文件读取局域网共享开关状态（默认 False）"""
    try:
        if os.path.exists(LAN_CONFIG_FILE):
            with open(LAN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return bool(data.get('enabled', False))
    except Exception:
        pass
    return False

def save_lan_sharing_enabled(enabled: bool) -> None:
    """持久化局域网共享开关状态至磁盘"""
    try:
        with open(LAN_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'enabled': bool(enabled)}, f)
    except Exception:
        pass

LAN_SHARING_ENABLED = load_lan_sharing_enabled()

WAN_CONFIG_FILE = os.path.join(SCRIPT_DIR, "config", ".wan_config.json")
WAN_DOMAIN = get_wan_domain()  # 真实域名在 services/local_settings.py 里，不写死在会公开的源码中
WAN_URL = f"https://{WAN_DOMAIN}" if WAN_DOMAIN else None

def load_wan_sharing_enabled() -> bool:
    """从磁盘配置文件读取 Cloudflare 广域网隧道远程共享开关状态（默认 False）"""
    try:
        if os.path.exists(WAN_CONFIG_FILE):
            with open(WAN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return bool(data.get('enabled', False))
    except Exception:
        pass
    return False

def save_wan_sharing_enabled(enabled: bool) -> None:
    """持久化 Cloudflare 广域网隧道远程共享开关状态至磁盘"""
    try:
        with open(WAN_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'enabled': bool(enabled)}, f)
    except Exception:
        pass

WAN_SHARING_ENABLED = load_wan_sharing_enabled()

CLOUDFLARED_BIN = os.path.join(SCRIPT_DIR, "bin", "cloudflared")
WAN_TUNNEL_PROC = None
WAN_TUNNEL_LOCK = threading.Lock()
LOCAL_DNS_HELPER_STARTED = False

# Cloudflare 隧道边缘 IP（region1 = 198.41.192.0/24，region2 = 198.41.200.0/24，端口 7844）。
# 大陆网络下踩的坑（2026-09 实测）：
#   1. argotunnel.com 的 SRV 记录解析被污染 → cloudflared 发现不了边缘 IP，直接
#      "failed to resolve any edge address" 退出；
#   2. 到边缘 7844 的 TCP / HTTP2 握手会被 GFW 重置（"TLS handshake with edge error: EOF"）；
#   3. 只有 QUIC(UDP:7844) 能连上。
# 对策：写死边缘 IP 绕过 DNS 发现 + 强制 --protocol quic。实测这组能注册满 4 条隧道连接。
CLOUDFLARE_EDGE_IPS = [
    "198.41.192.7", "198.41.192.27", "198.41.192.37", "198.41.192.47",
    "198.41.192.67", "198.41.192.107", "198.41.192.167", "198.41.192.227",
    "198.41.200.13", "198.41.200.23", "198.41.200.33", "198.41.200.43",
    "198.41.200.53", "198.41.200.113", "198.41.200.193", "198.41.200.233",
]

# 内存看门狗：主进程 + 所有 Chromium 子进程 RSS 合计超过这个值(MB)就干净自重启。
# 长期跑的 hub + 从不整页刷新的单页应用，QtWebEngine 会慢慢涨，之前把内存和交换
# 全吃光。可用环境变量 OMNI_MEM_RESTART_MB 覆盖。
MEM_RESTART_MB = int(os.environ.get("OMNI_MEM_RESTART_MB", "4500"))

def is_cloudflared_ready():
    """检测本地 bin/cloudflared 可执行文件是否存在且可正常运行"""
    if not os.path.exists(CLOUDFLARED_BIN):
        return False
    try:
        res = subprocess.run([CLOUDFLARED_BIN, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
        return res.returncode == 0
    except Exception:
        return False

def start_local_dns_helper():
    """
    启动本地轻量级 DNS 代理助手 (127.0.0.1:53535)：
    专门针对中国大陆或特定网络环境下 Steam Deck 解析 Argo Tunnel 域名被污染的问题，
    精准劫持 argotunnel.com 查询并返回直连 SRV/IP 记录，其他请求转发至阿里 DNS (223.5.5.5)。
    """
    global LOCAL_DNS_HELPER_STARTED
    if LOCAL_DNS_HELPER_STARTED:
        return
    LOCAL_DNS_HELPER_STARTED = True

    def dns_worker():
        """DNS 代理主循环：监听 127.0.0.1:53535，劫持 argotunnel.com 查询并转发其余请求。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', 53535))
        except Exception:
            return
        while True:
            try:
                data, addr = s.recvfrom(2048)
                if not data:
                    break
                tid = data[:2]
                qname = ''
                idx = 12
                while idx < len(data):
                    l = data[idx]
                    if l == 0:
                        idx += 1
                        break
                    idx += 1
                    qname += data[idx:idx+l].decode('utf-8', 'ignore') + '.'
                    idx += l
                qtype = struct.unpack('>H', data[idx:idx+2])[0]
                if qtype == 33 and 'argotunnel.com' in qname:
                    resp_hdr = tid + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'
                    question = data[12:idx+4]
                    target = b'\x07region1\x02v2\x0bargotunnel\x03com\x00'
                    rdata = struct.pack('>HHH', 0, 100, 7844) + target
                    ans = b'\xc0\x0c\x00\x21\x00\x01\x00\x00\x01\x2c' + struct.pack('>H', len(rdata)) + rdata
                    s.sendto(resp_hdr + question + ans, addr)
                else:
                    f = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    f.settimeout(2)
                    try:
                        f.sendto(data, ('223.5.5.5', 53))
                        rdata, _ = f.recvfrom(2048)
                        s.sendto(rdata, addr)
                    except Exception:
                        pass
                    finally:
                        f.close()
            except Exception:
                pass

    threading.Thread(target=dns_worker, daemon=True).start()

def ensure_wan_daemon():
    """保证 Cloudflare 专属隧道后台静默常驻，随时待命响应请求"""
    if not is_cloudflared_ready():
        return
    config_file = os.path.expanduser("~/.cloudflared/config.yml")
    if not os.path.exists(config_file):
        return

    start_local_dns_helper()

    def daemon_worker():
        """后台常驻循环：按 WAN_SHARING_ENABLED 开关状态拉起/保持 cloudflared 隧道进程。"""
        global WAN_TUNNEL_PROC
        while True:
            # 广域网开关关着就不起隧道（否则 config 存在时会空转 / 反复重连）
            if not WAN_SHARING_ENABLED:
                time.sleep(10)
                continue
            try:
                cmd = [CLOUDFLARED_BIN, "--config", config_file, "--protocol", "quic"]
                for ip in CLOUDFLARE_EDGE_IPS:          # 写死边缘 IP，绕过被污染的 SRV 解析
                    cmd += ["--edge", f"{ip}:7844"]
                cmd += ["tunnel", "run"]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=set_pdeathsig
                )
                with WAN_TUNNEL_LOCK:
                    WAN_TUNNEL_PROC = proc
                proc.wait()
            except Exception as e:
                log_omni("WARN", f"Cloudflare 隧道守护异常: {e}", tag="WAN")
            time.sleep(3)

    threading.Thread(target=daemon_worker, daemon=True).start()

def get_wan_status():
    """获取当前 Cloudflare 广域网隧道的配置与连接状态字典"""
    return {
        "enabled": WAN_SHARING_ENABLED,
        "status": "running" if WAN_SHARING_ENABLED else "stopped",
        "url": WAN_URL,
        "domain": WAN_DOMAIN,
        "has_binary": is_cloudflared_ready()
    }

def broadcast_network_status():
    """向所有已连接的视口和浏览器客户端广播当前最新的局域网与广域网网络状态"""
    try:
        ip = get_local_ip()
        manga_service.broadcast_manga_event({
            'type': 'network_status',
            'lan': {
                'enabled': LAN_SHARING_ENABLED,
                'ip': ip,
                'port': PORT,
                'url': f'http://{ip}:{PORT}'
            },
            'wan': get_wan_status()
        })
    except Exception:
        pass

FLASH_PLUGIN_PATH = os.path.join(PLUGINS_DIR, "libpepflashplayer.so") if sys.platform != "win32" else os.path.join(PLUGINS_DIR, "pepflashplayer64.dll")

DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
CHROMIUM_CACHE = os.path.join(CACHE_DIR, "engine_cache")

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CHROMIUM_CACHE, exist_ok=True)

sys.argv.append(f"--disk-cache-dir={CHROMIUM_CACHE}")
sys.argv.append("--disk-cache-size=1073741824")
sys.argv.append("--media-cache-size=536870912")
sys.argv.append("--max-connections-per-host=16")
sys.argv.append("--no-proxy-server")
sys.argv.append("--proxy-server=direct://")
sys.argv.append("--proxy-bypass-list=*")
sys.argv.append("--enable-gpu-rasterization")
sys.argv.append("--disable-gpu-watchdog")
sys.argv.append("--disable-gpu-process-crash-limit")
sys.argv.append("--enable-webgl")
sys.argv.append("--no-sandbox")
sys.argv.append("--autoplay-policy=no-user-gesture-required")
sys.argv.append("--allow-running-insecure-content")
sys.argv.append("--ignore-certificate-errors")

GAMES_REGISTRY = {}

DISPLAY_NAMES = {
    '001 - Loli Ninja Village': '001 - Loli Ninja Village',
    '002 - Adventurer Liena': '002 - Adventurer Liena',
    "003 - Aisha's Futa Diaries": "003 - Aisha's Futa Diaries",
    "004 - Ayako's Effort": "004 - Ayako's Effort",
    '005 - Battle Demon Kirsten': '005 - Battle Demon Kirsten',
    '006 - Broken Eden': '006 - Broken Eden',
    '007 - Careless Sister': '007 - Careless Sister',
    '008 - Cool Friend & Sister': '008 - Cool Friend & Sister',
    '009 - Daily Love Life with Mother': '009 - Daily Love Life with Mother',
    '010 - Escape from Ninja Girls': '010 - Escape from Ninja Girls',
    '011 - Fallen Kunoichi': '011 - Fallen Kunoichi',
    '012 - Forestia': '012 - Forestia',
    "013 - Futanari's Sex World": "013 - Futanari's Sex World",
    '014 - Isekai Monster Girls': '014 - Isekai Monster Girls',
    '015 - Goblin Front': '015 - Goblin Front',
    '016 - Golden Canary': '016 - Golden Canary',
    '017 - House Chores': '017 - House Chores',
    '018 - Isekai Kabukicho': '018 - Isekai Kabukicho',
    "019 - Karryn's Prison": "019 - Karryn's Prison",
    '020 - Latex Dungeon': '020 - Latex Dungeon',
    '021 - Lewd Gym': '021 - Lewd Gym',
    "022 - Lilialette's Hustle": "022 - Lilialette's Hustle",
    '023 - Listaria': '023 - Listaria',
    '024 - Live Empire': '024 - Live Empire',
    '025 - MRYG': '025 - MRYG',
    '026 - Mother Alicia': '026 - Mother Alicia',
    '027 - Mother NTR Hunter': '027 - Mother NTR Hunter',
    '028 - My Countryside Life': '028 - My Countryside Life',
    '029 - My Secret Summer Vacation 2': '029 - My Secret Summer Vacation 2',
    '030 - NTR Hunter': '030 - NTR Hunter',
    '031 - NTR Priestess': '031 - NTR Priestess',
    '032 - Naive Elven Swordswoman': '032 - Naive Elven Swordswoman',
    '033 - Night Bloom': '033 - Night Bloom',
    '034 - Now, She is...': '034 - Now, She is...',
    '035 - OVER Devil': '035 - OVER Devil',
    '036 - Pleasant Adultery Village': '036 - Pleasant Adultery Village',
    '037 - Pleasure Cruise': '037 - Pleasure Cruise',
    '038 - QOS MILF': '038 - QOS MILF',
    '039 - QOS Wife 2': '039 - QOS Wife 2',
    '040 - Hooked on Air Conditioner': '040 - Hooked on Air Conditioner',
    '041 - Sakurako NTR Story': '041 - Sakurako NTR Story',
    '042 - Heroine Falah': '042 - Heroine Falah',
    '043 - Reaching Mom': '043 - Reaching Mom',
    '044 - Rebecca and the Sword of Mystery': '044 - Rebecca and the Sword of Mystery',
    '045 - Risty and the Village of Bocchino': '045 - Risty and the Village of Bocchino',
    '046 - Secret Rule': '046 - Secret Rule',
    '047 - Sex Knight': '047 - Sex Knight',
    '048 - Sheena Relic Hunter': '048 - Sheena Relic Hunter',
    '049 - Shoot NPC': '049 - Shoot NPC',
    '050 - Slutty Witches': '050 - Slutty Witches',
    '051 - Succubers! Dark Covenant': '051 - Succubers! Dark Covenant',
    '052 - Succubus Boss': '052 - Succubus Boss',
    '053 - Summer Vacation': '053 - Summer Vacation',
    '054 - The Cuniculus of Paradise': '054 - The Cuniculus of Paradise',
    "055 - The Saint Wife's Newlywed Trials": "055 - The Saint Wife's Newlywed Trials",
    '056 - The Savior Heart 2': '056 - The Savior Heart 2',
    '057 - Town of Passion': '057 - Town of Passion',
    '058 - Trials of Interspecies Sisters': '058 - Trials of Interspecies Sisters',
    '059 - Undercity of Sin': '059 - Undercity of Sin',
    '060 - Unholy Maiden': '060 - Unholy Maiden',
    '061 - Yokai Busters': '061 - Yokai Busters',
    "062 - Eriru's Adventure": "062 - Eriru's Adventure",
    '063 - Succubus Battle Kai': '063 - Succubus Battle Kai',
    '064 - Sex Training Island': '064 - Sex Training Island',
    "065 - Toneriko's Merchant Life": "065 - Toneriko's Merchant Life",
    '066 - May It Be For Her': '066 - May It Be For Her',
    '067 - Masturbation Wife': '067 - Masturbation Wife',
    '068 - Bitch Training': '068 - Bitch Training',
    '069 - Hina & Dean and Cursed Dungeon': '069 - Hina & Dean and Cursed Dungeon',
    '070 - Isekai Island': '070 - Isekai Island',
    '071 - School Ghost Stories': '071 - School Ghost Stories',
    '072 - Wild West Female Gunman 2': '072 - Wild West Female Gunman 2',
    '073 - Red Warrior Remilia': '073 - Red Warrior Remilia',
    "074 - Saint Magnolia's Quest": "074 - Saint Magnolia's Quest",
    '075 - Defiled Silver': '075 - Defiled Silver',
    '076 - Elf Heroine Leane': '076 - Elf Heroine Leane',
    '077 - Lady Spy of the Blue Sea': '077 - Lady Spy of the Blue Sea',
    '078 - Red-Haired Pregnant Princess': '078 - Red-Haired Pregnant Princess',
    '079 - Ayuu Rei': '079 - Ayuu Rei',
    '080 - Ruruka and the Grand Sorcerer': '080 - Ruruka and the Grand Sorcerer',
    '081 - Demon Goblin and Mr Knight': '081 - Demon Goblin and Mr Knight',
    '082 - Zombio Apocalypse': '082 - Zombio Apocalypse',
    '083 - Village Erotic Life': '083 - Village Erotic Life',
    '084 - Hot Spring Room Sharing': '084 - Hot Spring Room Sharing',
    '086 - This Goddess Corrupted Our World': '086 - This Goddess Corrupted Our World',
    '087 - Endless Tentacle Cave': '087 - Endless Tentacle Cave',
    '088 - Trial of Lust': '088 - Trial of Lust',
    '089 - Moms Friend Under Curse': "089 - Mom's Friend Under Curse",
    '090 - Aine Tamagushi Case Files': '090 - Aine Tamagushi Case Files',
    '091 - Support Among Companions': '091 - Support Among Companions',
    '092 - Contributing to the Village': '092 - Contributing to the Village',
    '093 - Mind Lyuda': '093 - Mind Lyuda',
    '094 - Takitsubo Channel': '094 - Takitsubo Channel',
    '095 - Mother Alicia Crest': '095 - Mother Alicia Crest',
    '096 - Daily Greetings Wife': '096 - Daily Greetings Wife',
    '097 - The Witch and the Two Apprentices': '097 - The Witch and the Two Apprentices',
    '098 - Dragon Conqueror': '098 - Dragon Conqueror',

    # === Standalone Ren'Py Games (001 - 013) ===
    "001 - Mom's Best Friend": "001 - Mom's Best Friend",
    '002 - After the Fire': '002 - After the Fire',
    '003 - Love Strikes Thrice': '003 - Love Strikes Thrice',
    '004 - Obsessed Lucy': '004 - Obsessed Lucy',
    '005 - Cradle Beyond the Veil': '005 - Cradle: Beyond the Veil',
    '006 - Hokages Adopted Son': "006 - Hokage's Adopted Son",
    '007 - sMother': '007 - sMother',
    '008 - Succu-Mama': '008 - SUCCU-MAMA',
    '009 - Bright Lord': '009 - Bright Lord (光明领主)',
    '010 - Supower': '010 - 超能力者的日常 (Supower)',
    '011 - Midnight Shifts with Femboy': '011 - 与伪娘的深夜轮班 (Midnight Shifts with Femboy)',
    '012 - Harem x Family': '012 - 间谍后宫家 (Harem x Family)',
    '013 - Harem Heaven': '013 - 后宫天堂 (Harem Heaven)',
    '014 - Sayaka My Naughty Milf Neighbor': '014 - 邻家俏人妻沙耶加 (Sayaka: My Naughty Neighbor)',
    '015 - Happy Island Fantasy': '015 - 幸福岛物语 (Happy Island Fantasy)',
    '016 - Neighbors Wife': '016 - 邻家的人妻 (Neighbor\'s Wife)',
    '017 - Legend of Moonlight': '017 - 月光传说 (Legend of Moonlight)',
    '018 - Falling Undercover Nox Syndicate': '018 - 潜伏行动：夜色辛迪加 (Falling Undercover)',
    '019 - Agent 17': '019 - 特工 17 (Agent 17)',
    '020 - The Seven Realms': '020 - 七大王国 (The Seven Realms)',
    '021 - Midnight Sin': '021 - 午夜之罪 (Midnight Sin)',
    '022 - Summer Memories': '022 - 夏日回忆 (Summer Memories)',
    '023 - Love and Life': '023 - 爱与生活 (Love and Life)',
    '024 - Forbidden Thoughts': '024 - 禁忌的念头 (Forbidden Thoughts)',

    # === SLG 策略与互动模拟 (001 - 008) ===
    '001 - Cowgirl Maid Milk Cafe': '001 - Cowgirl Maid Milk Cafe',
    '002 - Summer Sisters': '002 - Summer Sisters',
    '003 - My Summer Vacation': '003 - 大叔的暑假 (My Summer Vacation)',
    '004 - Girls on the Borderline': '004 - 百万引町边界的少女们 (Girls on the Borderline)',
    '005 - Elf Girl Rifia': '005 - 精灵少女莉菲亚与梦幻迷宫 (Elf Lifia and the Labyrinth of Everdream)',
    '008 - Harem x Family': '008 - 间谍过家家 (Harem x Family)',
    '009 - Midnight Shifts with Femboy': '009 - 伪娘的深夜轮班 (Midnight Shifts with Femboy)',
    '010 - Obsessed Lucy': '010 - 痴迷的露西 (Obsessed Lucy)',
    '011 - Sayaka My Naughty Milf Neighbor': '011 - 调皮熟女邻居沙耶香 (Sayaka My Naughty Milf Neighbor)',
    '012 - Astra Ardent Show': '012 - 阿斯特拉炽热秀 (Astra Ardent Show)',
    '013 - sMother': '013 - 窒息母爱 (sMother)',
    '014 - Kunoichi Trainer': '014 - 女忍训练师 (Kunoichi Trainer)',
    '015 - The Last Year': '015 - 最后一学年 (The Last Year)',
    '016 - Harmony Girls': '016 - 和谐少女 (Harmony Girls)',
    '017 - Forbidden Thoughts': '017 - 禁忌的念头 (Forbidden Thoughts)',
    '018 - Blood Ties': '018 - 血脉相连 (Blood Ties)',
    '019 - Love Strikes Thrice': '019 - 恋爱三击 (Love Strikes Thrice)',
    '020 - Supower': '020 - 超能人生 (Supower)',
    '021 - Cradle Beyond the Veil': '021 - 摇篮：面纱之外 (Cradle Beyond the Veil)',
    '022 - A Foreign World Episode 8': '022 - 异界：第8集 (A Foreign World Episode 8)',
    "023 - Mom's Best Friend": "023 - 妈妈的闺蜜 (Mom's Best Friend)",
    '024 - Succu-Mama': '024 - 魅魔妈妈 (Succu-Mama)',
    '025 - Agent 17': '025 - 特工 17 (Agent 17)',
    '026 - Echoes': '026 - 回音 (Echoes)',
    '027 - Mother NTR Training': '027 - 妈妈的NTR调教 (Mother NTR Training)',
    '028 - Falling Undercover Nox Syndicate': '028 - 潜伏行动：夜色辛迪加 (Falling Undercover)',
    '029 - The Better Deal': '029 - 更好的交易 (The Better Deal)',
    '030 - Boundaries of Morality': '030 - 道德的边界 (Boundaries of Morality)',
    '031 - No Honor Just Need': '031 - 无关荣耀，唯有渴望 (No Honor Just Need)',
    '032 - Driven by Desire': '032 - 欲望驱使 (Driven by Desire)',
    '033 - Time Heals': '033 - 时间治愈一切 (Time Heals)',
    '034 - That New Teacher': '034 - 那个新老师 (That New Teacher)',
    '035 - His Bet Her Loss': '035 - 他的赌注她的损失 (His Bet Her Loss)',
    '036 - Bright Lord': '036 - 光明领主 (Bright Lord)',
    '037 - Town of Magic': '037 - 魔法小镇 (Town of Magic)',
    '038 - Angels Love': '038 - 天使之爱 (Angels Love)',
    '039 - Little Man': '039 - 小男人 (Little Man)',
    '040 - Reclaiming the Lost': '040 - 寻回失落 (Reclaiming the Lost)',
    '041 - The Neverwhere Tales': '041 - 虚幻传说 (The Neverwhere Tales)',
    '042 - Double Faced': '042 - 双面 (Double Faced)',
    '043 - Dark Lord Leona': '043 - 魔物女王蕾欧娜 (Dark Lord Leona)',
    '044 - My Cute Roommate 2': '044 - 我可爱的室友2 (My Cute Roommate 2)',
    '045 - Tokyo Hotel': '045 - 东京旅馆 (Tokyo Hotel)',
    '046 - Growing Things Up': '046 - 萌芽滋长 (Growing Things Up)',
    '047 - JASON Coming of Age': '047 - 杰森：成年初显期 (JASON, Coming of Age)',
    '048 - FreshWomen Season 2': '048 - 疯狂星期四：第二季 (FreshWomen Season 2)',

    # === Standalone Unity Games ===
    '001 - Kaiju Princess Detective': '001 - Kaiju Princess & Detective Servant',
    '002 - Kurea Struggle': '002 - Kurea Struggle',
    '003 - Harem Fantasy': '003 - Harem Fantasy',
    '004 - Stranger Maidens': '004 - Stranger Maidens',
    '005 - Summer at Smile Cafe': '005 - Summer at Smile Café',
    '006 - Yakuza Rogue EX': '006 - Yakuza Rogue EX',
    '007 - Female Sex Service': '007 - Female Sex Service',
    '008 - Peeping Dorm Manager': '008 - Peeping Dorm Manager',
    '009 - Workplace Fantasy': '009 - Workplace Fantasy',
    '010 - NTRaholic': '010 - NTRaholic',
    '011 - Lifeguard Holic': '011 - Lifeguard Holic',
    '012 - Love Confessions Adventure': '012 - Love Confessions Adventure',
    '013 - Lucky Teacher': '013 - Lucky Teacher',
    '014 - Mansion Days': '014 - Mansion Days: Roommates',
    '015 - Swarm Bunker Lust Defense': '015 - Swarm Bunker: Lust Defense',
    '016 - Tavern Inn Halberd': '016 - Tavern, Inn & the Halberd',
    '017 - Sex Secrets Used Tech': '017 - Sex, Secrets & Used Tech',
    '018 - Hypnosis Corruption After': '018 - Hypnosis of Corruption After Story',
    '019 - Chona': '019 - Chona',
    '020 - Taiwan MRT': '020 - Taiwan MRT',
    '021 - Spirit Valley': '021 - Spirit Valley',
    '022 - The Censor DX Edition': '022 - 审查员 DX版 (The Censor DX)',
    '023 - Circlemate': '023 - 社团伴侣 (Circlemate)',
    '024 - Hotel Tales': '024 - 旅社物语 (Hotel Tales)',
    "025 - Lovers' Fun": "025 - 连任 (Lovers' Fun)",
    "026 - Mirai's Midnight Training": "026 - 未来的午夜特训 (Mirai's Midnight Training)",
    '027 - Exit Lust': '027 - 8号欲口 (Exit Lust)',
    '028 - Handyman Fantasy': '028 - 便利屋奇幻物语 (Handyman Fantasy)',
    '029 - Immoral Bathhouse': '029 - 背德混浴温泉 (Immoral Bathhouse)',
    '030 - Problematic Subjects': '030 - 有问题的课题 (Problematic Subjects)',
    '031 - Magi-Iki': '031 - 魔法高潮 (Magi-Iki)',
    '032 - Oral Sex Shop 2': '032 - 口交工坊 2 (Oral Sex Shop 2)',
    '033 - Isekai Bistro': '033 - 异世界餐酒馆 (Isekai Bistro)',
    '034 - Ride Me Taxi Driver': '034 - 老司机带带我 (Ride Me Taxi Driver)',
    '035 - Dekiru Kouhai Aoi-chan': '035 - 能力出众的后辈葵酱 (Dekiru Kouhai Aoi-chan)',
    '036 - Final Boss is Mother-in-law': '036 - 最终魔王是岳母 (Final Boss is Mother-in-Law)',
    '037 - Maid Sister': '037 - 女仆妹妹 (Maid Sister)',
    '038 - Secret Pie': '038 - 秘密派 (Secret Pie)',
    '039 - Daily Lives of My Country Cousins': '039 - 乡下堂妹们的日常 (Daily Lives of My Country Cousins)',
    '040 - Detective Girl': '040 - 侦探少女 (Detective Girl)',
    '041 - Sister Travel': '041 - 姐妹旅行 (Sister Travel)',
    '042 - Happy Island Fantasy': '042 - 快乐岛幻想 (Happy Island Fantasy)',
    '043 - Neighbors Wife': '043 - 邻居的妻子 (Neighbors Wife)',
    '044 - Midnight Sin': '044 - 午夜之罪 (Midnight Sin)',
    '045 - Summer Memories': '045 - 夏日回忆 (Summer Memories)',
    '046 - Love and Life': '046 - 爱与生活 (Love and Life)',
    '047 - NTR Family': '047 - NTR家族 (NTR Family)',
    '048 - My 29 Years': '048 - 我的29岁妻子 (My 29 Years)',
    '049 - Fallen Elf Freya': '049 - 堕落精灵芙蕾雅 (Fallen Elf Freya)',
    '050 - Summer 14 Days': '050 - 夏日14日 (SUMMER ～夏の14日)',
    '051 - Sisters Service': '051 - 姊妹的侍奉 (Sisters Service)',

    # === Standalone Steam 精选独立神作 ===
    '001 - Game Dev Story': '001 - 游戏开发物语 (Game Dev Story)',
    '002 - Thronefall': '002 - 王权陨落 (Thronefall)',
    '003 - Sandustry': '003 - 沙尘工业 (Sandustry)',
    '004 - Berry Bury Berry': '004 - 浆果埋葬 (Berry Bury Berry)',
    '005 - RimWorld': '005 - 环世界 (RimWorld)',
    '006 - Vampire Survivors': '006 - 吸血鬼幸存者 (Vampire Survivors)',
    '007 - Dead Cells': '007 - 死亡细胞 (Dead Cells)',
    '008 - Dave the Diver': '008 - 潜水员戴夫 (Dave the Diver)',
    '009 - Dyson Sphere Program': '009 - 戴森球计划 (Dyson Sphere Program)',
    '010 - Descenders': '010 - 速降王者 (Descenders)',
    '011 - Factorio': '011 - 异星工厂 (Factorio)',
    '012 - Oxygen Not Included': '012 - 缺氧 (Oxygen Not Included)',
    '013 - Don\'t Starve': '013 - 饥荒单机版 (Don\'t Starve)',
    '014 - Don\'t Starve Together': '014 - 饥荒联机版 (Don\'t Starve Together)',
    '015 - Bloons TD 6': '015 - 气球塔防 6 (Bloons TD 6)',
    '016 - Cult of the Lamb': '016 - 咩咩启示录 (Cult of the Lamb)',
    '017 - Euro Truck Simulator 2': '017 - 欧洲卡车模拟 2 (Euro Truck Simulator 2)',
    '018 - Hades II': '018 - 哈迪斯 2 (Hades II)',
    '019 - Hearts of Iron IV': '019 - 钢铁雄心 4 (Hearts of Iron IV)',
    '020 - Hollow Knight Silksong': '020 - 空洞骑士：丝之歌 (Hollow Knight: Silksong)',
    '021 - Hollow Knight': '021 - 空洞骑士 (Hollow Knight)',
    '022 - No Mans Sky': '022 - 无人深空 (No Man\'s Sky)',
    '023 - Palworld': '023 - 幻兽帕鲁 (Palworld)',
    '024 - Shapez 2': '024 - 异形工厂 2 (Shapez 2)',
    '025 - Stellaris': '025 - 群星 (Stellaris)',
    '026 - Marvels Spider-Man Miles Morales': "026 - 漫威蜘蛛侠：迈尔斯 (Marvel's Spider-Man: Miles Morales)",

    # === Standalone Godot Games ===
    '001 - Pawn Pleasure': '001 - Pawn Pleasure',
    '002 - NTR Phone': '002 - NTR Phone',
    '003 - 30 Days of Work': '003 - 职场的30天 (30 Days of Work)',
    '004 - Barely Working': '004 - 勉强维持 (Barely Working)',
    '005 - Harem Heaven': '005 - 后宫天堂 (Harem Heaven)',
    '006 - Goodbye Eternity': '006 - 再见永恒 (Goodbye Eternity)',
    '007 - Anomalous Coffee Machine 2': '007 - 异常咖啡机 2 (Anomalous Coffee Machine 2)',

    # === Standalone Unreal Games ===
    '001 - Loser Isekai': '001 - Loser Got Isekai\'d',
    '002 - Under the Witch Gothic': '002 - Under the Witch: Gothic',

    # === Standalone Wine / PC Games ===
    '001 - Train 45': '001 - Train 45',
    '002 - Beppin Mama': '002 - Beppin Mama',
    '003 - Goblin Nest': '003 - Goblin Nest',
    '004 - Hitozuma Netori Kaihou': '004 - Hitozuma Netori Kaihou',
    '005 - Dungeon Erotic Master': '005 - Dungeon of Erotic Master Plus',
    '006 - Bokusion': '006 - Bokusion',
    '007 - Descended to My Home': '007 - Descended to My Home',
    '008 - Please Oyako': '008 - Please (Oyako)',
    '009 - DokiDoki Massage': '009 - DokiDoki Massage',
    '010 - Why No Meat': '010 - Why No Meat',
    '011 - Scarlet Knight': '011 - Scarlet Knight',
    '012 - Mamaboku': '012 - Mamaboku',
    '013 - Mom Stolen in Space': '013 - Mom Stolen in Space',
    '014 - SPITE': '014 - SPITE',
    '015 - Kahogo Mama Volleyball': '015 - Kahogo na Mama Volleyball',
    '016 - Fiendish Quest': '016 - Fiendish Quest',
    '017 - Femtazio': '017 - Warrior of Femtazio',
    '018 - Xiaofan': '018 - Xiaofan',
    '019 - Depraved Scenario': '019 - 背德情境 (Depraved Scenario)',
    '020 - Eric Mercenary Corps': '020 - 埃里克佣兵团 (Eric Mercenary Corps)',
    '021 - YadoKasegi': '021 - 旅店打工记 (YadoKasegi)',
    '022 - Komadori Inn': '022 - 驹鸟旅馆 (Komadori Inn)',
    '023 - Punishment NyanNyan R': '023 - 惩罚喵喵 R (Punishment NyanNyan R)',
    '024 - Bodysmith Tales': '024 - 锻体物语 (Bodysmith Tales)',
    '025 - Naughty Chat': '025 - 淘气聊天室 (Naughty Chat)',
    '026 - Magical Monstergirls Academy': '026 - 魔法魔物娘学园 (Magical Monstergirls Academy)',
    '027 - Legend of Moonlight': '027 - 月光物语 (Legend of Moonlight)',
    '028 - Loser Isekai': '028 - 废柴转生异世界 (Loser Got Isekai\'d)',
    '029 - Company Trip Island': '029 - 孤岛求生：公司旅行 (Company Trip)',
    '030 - I Antasized Again': '030 - 幻想 (I Antasized Again)',
    '031 - Queen': '031 - 恶魔女王的诱惑 (Seduction of the Demon Queen)',
    '032 - NTR Phone v0.33': '032 - 打电话 (NTR Phone v0.33)',

    # === Standalone 3DS 模拟器专区 ===
    '001 - Pokemon Ultra Sun': '001 - 宝可梦：究极之日 (Pokemon Ultra Sun)',
    '002 - Pokemon Ultra Moon': '002 - 宝可梦：究极之月 (Pokemon Ultra Moon)',
    '003 - Pokemon X': '003 - 宝可梦 X (Pokemon X)',
    '004 - Pokemon Y': '004 - 宝可梦 Y (Pokemon Y)',
    '005 - Legend of Zelda Majoras Mask 3D': "005 - 塞尔达传说：姆吉拉的假面 3D (Majora's Mask 3D)",
    '006 - Legend of Zelda Ocarina of Time 3D': '006 - 塞尔达传说：时之笛 3D (Ocarina of Time 3D)',

    # === Windows 软件与独立应用 ===
    'StarCraft II': '星际争霸 2 (StarCraft II 离线版)',
    'Weiyun': '腾讯微云 (Tencent Weiyun)',
}

DEFAULT_SVG_ICON = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect width="100" height="100" rx="20" fill="#1c2128"/>
  <path d="M30 40h40v20H30z" fill="#58a6ff"/>
  <circle cx="50" cy="50" r="15" fill="#388bfd"/>
</svg>'''

def register_rpg_folder(folder_path, custom_id=None):
    """
    扫描并注册单个 RPG Maker 游戏目录 (MV / MZ / VX / XP 网页打包架构)。
    检测 index.html, www/index.html 或 data/www/index.html，自动建立存档子目录 save/。
    
    参数:
        folder_path (str): 游戏根目录物理路径
        custom_id (str, optional): 自定义游戏 ID (默认采用文件夹名称)
    """
    if not os.path.isdir(folder_path):
        return

    p1 = os.path.join(folder_path, 'index.html')
    p2 = os.path.join(folder_path, 'www', 'index.html')
    p3 = os.path.join(folder_path, 'data', 'www', 'index.html')

    target_www = None
    if os.path.exists(p1): target_www = folder_path
    elif os.path.exists(p2): target_www = os.path.join(folder_path, 'www')
    elif os.path.exists(p3): target_www = os.path.join(folder_path, 'data', 'www')

    if target_www:
        base_name = os.path.basename(folder_path.rstrip('/'))
        game_id = custom_id or base_name
        name = DISPLAY_NAMES.get(game_id, DISPLAY_NAMES.get(base_name, base_name))
        
        icon_path = os.path.join(target_www, 'icon', 'icon.png')
        save_dir = os.path.join(target_www, 'save')
        os.makedirs(save_dir, exist_ok=True)

        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'rpg',
            'root': target_www,
            'save_dir': save_dir,
            'icon': icon_path if os.path.exists(icon_path) else None,
        }

def find_best_executable(folder_path, subcategory):
    """递归智能查找最优先的主执行文件（自动识别中文字幕版、便携版、Linux 原生与内嵌子目录）"""
    candidates = []

    # 如果是专用 app
    if subcategory == 'app':
        for root, dirs, files in os.walk(folder_path):
            depth = os.path.relpath(root, folder_path).count(os.sep)
            if depth > 2: continue
            for f in files:
                fl = f.lower()
                full_p = os.path.join(root, f)
                if 'battle.net launcher.exe' in fl: return full_p
                if 'battle.net.exe' in fl: return full_p
                if 'weiyunapp.exe' in fl: return full_p
                if fl.endswith('.exe') and not 'uninstall' in fl:
                    candidates.append((50 - depth * 10, full_p))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    # Ren'Py 优先寻找 .sh 或 .py
    if subcategory == 'renpy':
        for root, dirs, files in os.walk(folder_path):
            depth = os.path.relpath(root, folder_path).count(os.sep)
            if depth > 2: continue
            for f in files:
                fl = f.lower()
                full_p = os.path.join(root, f)
                if any(bad in fl for bad in ['crashhandler', 'oalinst', 'vcredist', 'dxsetup']): continue
                if fl.endswith('.sh'): candidates.append((100 - depth * 10, full_p))
                elif fl.endswith('.py') and fl != 'game.py': candidates.append((80 - depth * 10, full_p))
                elif fl.endswith('.exe'): candidates.append((50 - depth * 10, full_p))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    # 3DS 模拟器游戏优先寻找 .cci, .3ds, .cxi
    if subcategory == '3ds':
        for root, dirs, files in os.walk(folder_path):
            depth = os.path.relpath(root, folder_path).count(os.sep)
            if depth > 2: continue
            for f in files:
                fl = f.lower()
                full_p = os.path.join(root, f)
                if fl.endswith(('.cci', '.3ds', '.cxi')):
                    return full_p

    # 通用独立游戏 (Unity, Godot, Unreal, Wine)
    for root, dirs, files in os.walk(folder_path):
        depth = os.path.relpath(root, folder_path).count(os.sep)
        if depth > 3: continue

        for f in files:
            fl = f.lower()
            full_p = os.path.join(root, f)

            is_valid_exec = fl.endswith(('.exe', '.x86_64', '.x86', '.sh')) or (
                os.access(full_p, os.X_OK) and '.' not in f and not os.path.isdir(full_p)
            )
            if not is_valid_exec:
                continue

            if any(bad in fl for bad in ['crashhandler', 'crashpad', 'reipatcher', 'setup', 'uninstall', 'ueprereqsetup', 'config', 'エンジン設定', 'vcredist', 'dxredist', 'redist', 'directx', 'elevate', 'oalinst', 'openal', 'dotnet', 'vc_redist']):
                continue

            score = 100 - depth * 15

            if fl.endswith('.x86_64') or fl.endswith('.x86') or fl.endswith('.sh') or ('.' not in f and os.access(full_p, os.X_OK)):
                score += 60
            if '_cn' in fl or 'chs' in fl or 'chinese' in fl or '中文' in fl:
                score += 50
            if 'portable' in fl:
                score += 40
            if fl.endswith('.exe'):
                score += 10
            if 'loader' in fl:
                score -= 30
            if '_gl.exe' in fl:
                score -= 20
            if fl in ['oxygennotincluded', 'dontstarve', 'dontstarve_steam_x64.exe', 'dspgame.exe', 'deadcells.exe', 'factorio.exe', 'davethediver.exe', 'descenders.exe', 'rimworldwin64.exe', 'vampiresurvivors.exe', 'thronefall.exe', 'sandustry.exe', 'bloonstd6.exe', 'cult of the lamb.exe', 'eurotrucks2.exe', 'hades2.exe', 'hoi4.exe', 'silksong.exe', 'hollow_knight.exe', 'nms.exe', 'palworld.exe', 'shapez2.exe', 'stellaris.exe']:
                score += 100

            candidates.append((score, full_p))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def register_standalone_folder(folder_path, subcategory, custom_id=None):
    """
    扫描并注册单个独立游戏 / PC 应用目录。
    
    参数:
        folder_path (str): 游戏根目录物理路径
        subcategory (str): 子分类引擎 ('steam', 'renpy', 'unity', 'godot', 'unreal', 'wine', '3ds', 'app')
        custom_id (str, optional): 自定义游戏 ID
    """
    if not os.path.isdir(folder_path):
        return

    base_name = os.path.basename(folder_path.rstrip('/'))
    game_id = custom_id or base_name
    name = DISPLAY_NAMES.get(game_id, DISPLAY_NAMES.get(base_name, base_name))

    icon_candidates = [
        os.path.join(folder_path, 'icon.png'),
        os.path.join(folder_path, 'cover.png'),
        os.path.join(folder_path, 'cover.jpg'),
        os.path.join(folder_path, 'icon', 'icon.png'),
        os.path.join(folder_path, 'game', 'gui', 'window_icon.png'),
    ]
    icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)

    exe_path = find_best_executable(folder_path, subcategory)

    GAMES_REGISTRY[game_id] = {
        'id': game_id,
        'name': name,
        'type': 'standalone',
        'engine': subcategory,
        'root': folder_path,
        'exe_path': exe_path,
        'icon': icon_path,
    }

# 映射常见大型软件/游戏的专用 compatdata ID，确保注册表、证书与 AppData 100% 完整
APPID_PFX_MAP = {
    'Battle.net': '2415561907',
    'StarCraft II': '2415561907',
    'Weiyun': '3498387003',
}

def get_wine_or_proton_runner(exe_path, pfx_path=None, game_id=None):
    """
    在 Linux / SteamOS 环境下智能定位最佳 Wine / Proton 运行容器。
    
    优化策略：
    - 自动匹配 Steam 官方 Proton 运行时（Proton Experimental, 11, 10, 9, 8...）
    - 针对专用软件（战网、微云）挂载专属 Steam 容器，保证证书与注册表完整
    - 针对 UE5 游戏注入 DXVK/GL 异步着色器缓存与防崩溃环境变量
    """
    if sys.platform == 'win32':
        return [exe_path], os.environ.copy()

    # 1. 优先检测系统全局 wine
    if shutil.which('wine'):
        return ['wine', exe_path], os.environ.copy()

    # 2. 在 SteamOS / Steam Deck 环境下自动检测 Valve 官方 Proton 运行时
    # 若指定了特定的 Steam Prefix，优先使用专属环境（保证战网、微云等大型软件的原生完整注册表与 AppData）
    chosen_pfx = pfx_path
    if not chosen_pfx and game_id and game_id in APPID_PFX_MAP:
        steam_pfx = os.path.expanduser(f'~/.local/share/Steam/steamapps/compatdata/{APPID_PFX_MAP[game_id]}')
        if os.path.exists(steam_pfx):
            chosen_pfx = steam_pfx

    default_pfx = chosen_pfx or os.path.expanduser('~/.local/share/omni_deck_pfx')
    steam_common = os.path.expanduser('~/.local/share/Steam/steamapps/common')
    proton_candidates = [
        os.path.join(steam_common, 'Proton - Experimental', 'proton'),
        os.path.join(steam_common, 'Proton 11.0', 'proton'),
        os.path.join(steam_common, 'Proton 10.0', 'proton'),
        os.path.join(steam_common, 'Proton 9.0 (Beta)', 'proton'),
        os.path.join(steam_common, 'Proton 8.0', 'proton'),
        os.path.join(steam_common, 'Proton 7.0', 'proton'),
        os.path.join(steam_common, 'Proton 5.13', 'proton'),
    ]
    for p in proton_candidates:
        if os.path.exists(p):
            env = os.environ.copy()
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = os.path.expanduser('~/.local/share/Steam')
            env['STEAM_COMPAT_DATA_PATH'] = default_pfx
            os.makedirs(default_pfx, exist_ok=True)

            cmd = [p, 'run', exe_path]
            # 为 Electron 类应用（如微云等）附加 Chromium 渲染修复参数，避免 GPU 沙盒导致黑屏
            if game_id == 'Weiyun' or 'weiyun' in exe_path.lower():
                cmd.extend(['--no-sandbox', '--disable-gpu-sandbox'])

            # UE5 专项修复：关闭异常重抛限制与崩溃上报，避免 FATAL: exception not rethrown
            is_ue5 = (
                game_id and 'unreal' in (game_id + exe_path).lower()
            ) or any(
                kw in exe_path for kw in ['Shipping', 'Win64', 'UTW_', 'LoserIsekai', 'UE5', 'Unreal']
            )
            if is_ue5:
                env['PROTON_NO_ESYNC'] = '0'
                env['PROTON_NO_FSYNC'] = '0'
                env['WINE_LARGE_ADDRESS_AWARE'] = '1'
                env['DXVK_ASYNC'] = '1'
                env['DXVK_STATE_CACHE'] = '1'
                env['__GL_SHADER_DISK_CACHE'] = '1'
                env['__GL_SHADER_DISK_CACHE_SKIP_CLEANUP'] = '1'
                env['UE_DISABLE_CRASH_REPORTER'] = '1'
                env['UE_NO_CRASH_REPORT'] = '1'

            return cmd, env

    return None, None

def register_retro_folder(folder_path, custom_id=None):
    """
    扫描并注册单个复古街机/主机游戏 (GBA, NDS, PS1, SFC, MD, Arcade)。
    自动匹配 EmulatorJS 支持的 ROM 镜像扩展名与核心。
    """
    if not os.path.isdir(folder_path):
        return

    base_name = os.path.basename(folder_path.rstrip('/'))
    game_id = custom_id or base_name
    name = DISPLAY_NAMES.get(game_id, DISPLAY_NAMES.get(base_name, base_name))

    rom_extensions = {
        '.cue': 'psx',
        '.chd': 'psx',
        '.pbp': 'psx',
        '.iso': 'psx',
        '.gba': 'gba',
        '.gbc': 'gb',
        '.gb': 'gb',
        '.nds': 'nds',
        '.nes': 'nes',
        '.sfc': 'snes',
        '.smc': 'snes',
        '.z64': 'n64',
        '.n64': 'n64',
        '.v64': 'n64',
        '.md': 'segaMD',
        '.zip': 'arcade',
        '.bin': 'segaMD'
    }
    rom_file = None
    dir_files = os.listdir(folder_path)
    # 针对 PS1 专区特别优化: 优先加载完整包含音频轨的 .zip / .chd / .pbp / .iso 镜像包
    if '(ps1)' in game_id.lower() or '(psx)' in game_id.lower():
        ps1_candidates = ['.zip', '.chd', '.pbp', '.iso', '.cue']
        for ext in ps1_candidates:
            matched = [f for f in dir_files if f.lower().endswith(ext)]
            if matched:
                rom_file = matched[0]
                system_core = 'psx'
                break
    else:
        for ext_target, core_target in rom_extensions.items():
            matched = [f for f in dir_files if f.lower().endswith(ext_target)]
            if matched:
                rom_file = matched[0]
                system_core = core_target
                break

    if rom_file:
        icon_candidates = [
            os.path.join(folder_path, 'icon.png'),
            os.path.join(folder_path, 'cover.png'),
            os.path.join(folder_path, 'cover.jpg')
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)
        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'retro',
            'system': system_core,
            'root': folder_path,
            'rom_file': rom_file,
            'icon': icon_path,
        }

def register_slg_folder(folder_path, custom_id=None):
    """
    扫描并注册单个 SLG 策略/模拟养成游戏。
    支持 Ren'Py 架构与 WebGL/HTML5 网页渲染架构。
    """
    if not os.path.isdir(folder_path):
        return
    game_id = custom_id or os.path.basename(folder_path)
    name = DISPLAY_NAMES.get(game_id, game_id)
    
    # 1. 优先检查 WebGL / HTML5 / Ren'Py Web / RPG Maker 网页渲染架构
    entry_html = None
    if os.path.exists(os.path.join(folder_path, 'index.html')):
        entry_html = 'index.html'
    elif os.path.exists(os.path.join(folder_path, 'game.html')):
        entry_html = 'game.html'
    elif os.path.exists(os.path.join(folder_path, 'www', 'index.html')):
        entry_html = 'www/index.html'
    else:
        for root, dirs, files in os.walk(folder_path):
            if 'index.html' in files:
                entry_html = os.path.relpath(os.path.join(root, 'index.html'), folder_path)
                break

    if entry_html:
        save_dir = os.path.join(folder_path, 'save')
        os.makedirs(save_dir, exist_ok=True)
        
        icon_candidates = [
            os.path.join(folder_path, 'icon.png'),
            os.path.join(folder_path, 'cover.png'),
            os.path.join(folder_path, 'web-presplash.jpg'),
            os.path.join(folder_path, 'icons', 'icon-512x512.png'),
            os.path.join(folder_path, 'icon.jpg'),
            os.path.join(folder_path, 'cover.jpg'),
            os.path.join(folder_path, 'icon', 'icon.png'),
            os.path.join(folder_path, 'www', 'icon', 'icon.png')
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)

        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'slg',
            'slg_engine': 'web',
            'root': folder_path,
            'entry_html': entry_html or 'index.html',
            'save_dir': save_dir,
            'icon': icon_path,
        }
        return

    # 2. 原生桌面版 Ren'Py 架构（无 index.html，且含有 game/ 目录）
    game_sub = os.path.join(folder_path, 'game')
    if os.path.isdir(game_sub):
        icon_candidates = [
            os.path.join(folder_path, 'cover.jpg'),
            os.path.join(folder_path, 'cover.png'),
            os.path.join(folder_path, 'icon.png'),
            os.path.join(game_sub, 'gui', 'window_icon.png'),
            os.path.join(game_sub, 'icon.png'),
            os.path.join(game_sub, 'presplash.jpg'),
            os.path.join(game_sub, 'presplash.png')
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)

        # 寻找原生可执行脚本 (.sh / .py / .exe)
        sh_files = [f for f in sorted(os.listdir(folder_path)) if f.endswith('.sh') and not f.startswith('.')]
        exe_path = None
        if sh_files:
            exe_path = os.path.join(folder_path, sh_files[0])
            try: os.chmod(exe_path, 0o755)
            except: pass
        else:
            py_files = [f for f in sorted(os.listdir(folder_path)) if f.endswith('.py') and not f.startswith('.')]
            if py_files:
                exe_path = os.path.join(folder_path, py_files[0])
                try: os.chmod(exe_path, 0o755)
                except: pass
            else:
                exe_files = [f for f in sorted(os.listdir(folder_path)) if f.endswith('.exe') and not f.startswith('.')]
                if exe_files:
                    exe_path = os.path.join(folder_path, exe_files[0])

        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'slg',
            'slg_engine': 'renpy',
            'engine': 'renpy',
            'exe_path': exe_path,
            'root': folder_path,
            'save_dir': os.path.join(game_sub, 'saves'),
            'icon': icon_path,
        }
        return

def register_flash_folder(folder_path, custom_id=None):
    """
    扫描并注册单个 Flash 游戏。
    支持在线网页 Flash (info.json 中 type: web_flash) 与本地 SWF 离线游戏。
    """
    if not os.path.isdir(folder_path):
        return
    game_id = custom_id or os.path.basename(folder_path)
    name = DISPLAY_NAMES.get(game_id, game_id)
    
    hint = ""
    info_json = os.path.join(folder_path, 'info.json')
    engine = 'swf'
    url = ''
    if os.path.exists(info_json):
        try:
            with open(info_json, 'r', encoding='utf-8') as f:
                info = json.load(f)
                hint = info.get('hint', '')
                if info.get('type') == 'web_flash' and info.get('url'):
                    engine = 'web_flash'
                    url = info.get('url')
        except: pass
    
    swf_file = None
    if engine == 'swf':
        swf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.swf')]
        if not swf_files:
            return
        swf_file = swf_files[0]
    
    icon_candidates = [
        os.path.join(folder_path, 'icon.png'),
        os.path.join(folder_path, 'icon.jpg'),
        os.path.join(folder_path, 'cover.png'),
        os.path.join(folder_path, 'cover.jpg')
    ]
    icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)

    GAMES_REGISTRY[game_id] = {
        'id': game_id,
        'name': name,
        'type': 'flash',
        'engine': engine,
        'url': url,
        'root': folder_path,
        'swf_file': swf_file,
        'hint': hint,
        'icon': icon_path,
    }

_games_scan_lock = threading.Lock()
_last_watched_sig = None

STANDALONE_CATEGORIES = ['steam', 'renpy', 'unity', 'godot', 'unreal', 'wine', '3ds', 'app']

def _get_monitored_paths():
    """列出所有需要监控 stat 变化的游戏目录路径（各资源库根路径下五大分类各自的候选位置）。

    这只是列路径，不判断存在性——路径存不存在都无所谓（stat 失败记 None，从 None
    变成有值本身也是一种"变化"，照样能被 _get_filesystem_signature() 检测到）。

    Returns:
        list[str]: 待监控路径列表。
    """
    # 指纹只是"这些路径的 stat 变没变"，路径存不存在都无所谓（stat 失败记 None，
    # 从 None 变成有值本身也是一种"变化"，照样能被检测到）——所以这里直接按配置的
    # 资源库根路径拼路径，不用先过滤存在性。
    paths = [RPG_GAMES_DIR, GAMES_BASE_DIR]
    for root in get_library_roots():
        paths.append(os.path.join(root, "rpg_games"))
        paths.append(os.path.join(root, "standalone_games", "rpg_games"))
        paths.append(os.path.join(root, "retro_games"))
        paths.append(os.path.join(root, "standalone_games", "retro_games"))
        paths.append(os.path.join(root, "slg_games"))
        paths.append(os.path.join(root, "standalone_games", "slg_games"))
        paths.append(os.path.join(root, "flash_games"))
        paths.append(os.path.join(root, "standalone_games", "flash_games"))
        for cat in STANDALONE_CATEGORIES:
            paths.append(os.path.join(root, f"{cat}_games"))
            paths.append(os.path.join(root, "standalone_games", f"{cat}_games"))
    return paths

def _get_filesystem_signature():
    """给所有监控路径拍一次快照（mtime+size），用于跟上一次快照比较判断"有没有变动"。

    Returns:
        dict: {路径: (mtime_ns, size) 或 None（路径不存在）}。
    """
    sig = {}
    for p in _get_monitored_paths():
        try:
            st = os.stat(p)
            sig[p] = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig[p] = None
    return sig

def _scan_roots_for(subfolder_name):
    """某一类资源（比如 "retro_games"）在所有已配置资源库根路径（app_config.py）
    下的候选目录，外加 omni-deck 自己目录下的旧版位置（SCRIPT_DIR/<subfolder_name>）——
    这个旧版位置不在配置的根路径管辖范围内，因为它嵌套在 SCRIPT_DIR 里，不是直接
    挂在某个配置根路径下面，得额外补一句。"""
    dirs = find_library_dirs("standalone_games", subfolder_name) + find_library_dirs(subfolder_name)
    legacy = os.path.join(SCRIPT_DIR, subfolder_name)
    if os.path.isdir(legacy) and legacy not in dirs:
        dirs.append(legacy)
    return dirs

def _register_standalone_category_games(cat: str) -> None:
    """扫描并注册某个独立游戏子分类（如 "renpy"/"unity"）在所有已配置资源库根路径下的游戏。

    从 scan_games() 拆出来的单分类扫描逻辑，避免那边"遍历分类 -> 遍历根路径 -> 遍历
    文件夹"叠成三层嵌套。

    Args:
        cat: 子分类前缀（如 "renpy"），实际会去扫描 f"{cat}_games" 目录。
    """
    for sp in _scan_roots_for(f"{cat}_games"):
        for item in sorted(os.listdir(sp)):
            if item.startswith("."):
                continue
            sub = os.path.join(sp, item)
            register_standalone_folder(sub, subcategory=cat, custom_id=item)


def scan_games(force=False):
    """
    全量扫描并索引 Omni Deck 的五大板块游戏与应用。
    使用根目录 stat/mtime 指纹快速校验（仅需 0.09ms）。
    只有当目录发生变动（增删改游戏文件夹）或 force=True 时才执行实际文件树检索，
    杜绝粗暴固定的盲目时间防抖，实现变动即感知、无变动零延迟。
    """
    global _last_watched_sig
    with _games_scan_lock:
        current_sig = _get_filesystem_signature()
        if not force and GAMES_REGISTRY and (_last_watched_sig == current_sig):
            return
        _last_watched_sig = current_sig
        GAMES_REGISTRY.clear()
    
    # 1. 扫描 RPG Maker 游戏目录 —— 依次看每个已配置的资源库根路径（app_config.py：
    #    默认是项目根路径/SD 卡/下载目录，可编辑 services/local_settings.py 里的
    #    LIBRARY_ROOTS 增删），同名文件夹后扫到的覆盖先扫到的。
    rpg_scan_roots = _scan_roots_for("rpg_games")
    legacy_games_dir = os.path.join(SCRIPT_DIR, "games")  # 更老版本的目录名兼容
    if os.path.isdir(legacy_games_dir) and legacy_games_dir not in rpg_scan_roots:
        rpg_scan_roots.append(legacy_games_dir)
    for rpg_dir in rpg_scan_roots:
        for item in sorted(os.listdir(rpg_dir)):
            if item.startswith("."): continue
            sub = os.path.join(rpg_dir, item)
            register_rpg_folder(sub, custom_id=item)

    # 2. 扫描 独立游戏专区 (Steam 精选, Ren'Py, Unity, Godot, Unreal, Wine, 3DS 模拟器, Windows 软件应用)
    for cat in STANDALONE_CATEGORIES:
        _register_standalone_category_games(cat)

    # 扫描 Windows 软件与独立应用 (支持 GAMES_BASE_DIR 或 Steam 原装容器路径)
    if os.path.exists(GAMES_BASE_DIR):
        for item in sorted(os.listdir(GAMES_BASE_DIR)):
            if item in ['omni-deck', 'StarCraft II', 'Battle.net', 'claude', 'rpg_games', 'standalone_games', 'media_library']: continue
            sub = os.path.join(GAMES_BASE_DIR, item)
            if os.path.isdir(sub):
                register_standalone_folder(sub, subcategory='app', custom_id=item)

    # 星际争霸 2 不再作为普通游戏卡片：它在「独立游戏」专区有专属子标签 (sc2)，
    # 走 /api/sc2/* 接口 + sc2Mod 子进程，见 SC2Panel 相关代码。

    if 'Weiyun' not in GAMES_REGISTRY and os.path.exists(WEIYUN_STEAM_PATH):
        register_standalone_folder(WEIYUN_STEAM_PATH, subcategory='app', custom_id='Weiyun')

    # 注册 Lime3DS 模拟器主程序 (快速拉起主界面与设置)
    lime3ds_sh = os.path.join(HOME_DIR, "Applications", "Lime3DS", "start-lime3ds.sh")
    if os.path.exists(lime3ds_sh):
        GAMES_REGISTRY['000 - Lime3DS Emulator'] = {
            'id': '000 - Lime3DS Emulator',
            'name': '000 - 🍋 Lime3DS 模拟器 (主界面与全局设置)',
            'type': 'standalone',
            'engine': '3ds',
            'root': os.path.dirname(lime3ds_sh),
            'exe_path': lime3ds_sh,
            'icon': os.path.join(HOME_DIR, "Applications", "Lime3DS", "lime3ds.png"),
        }

    # 3. 扫描 街机与复古卡带目录 (retro_games/)——emulatorjs/plugins 是模拟器核心/插件
    #    固定放在 RETRO_GAMES_DIR 下（app 基础设施，不是游戏内容，不跟着资源库根路径走），
    #    这里只排除这两个名字，不影响 EMULATORJS_DIR/PLUGINS_DIR 这两个固定路径本身。
    for r_dir in _scan_roots_for("retro_games"):
        for item in sorted(os.listdir(r_dir)):
            if item in ["emulatorjs", "plugins"] or item.startswith("."):
                continue
            sub = os.path.join(r_dir, item)
            register_retro_folder(sub, custom_id=item)

    # 4. 扫描 SLG 模拟策略与养成互动目录 (slg_games/)
    for s_dir in _scan_roots_for("slg_games"):
        for item in sorted(os.listdir(s_dir)):
            if item.startswith("."): continue
            sub = os.path.join(s_dir, item)
            register_slg_folder(sub, custom_id=item)

    # 5. 扫描 Flash 殿堂级神作目录 (flash_games/)——plugins（Ruffle 等运行时）固定放在
    #    FLASH_GAMES_DIR 下，同样是基础设施，不跟资源库根路径走，这里只排除这个名字。
    for f_dir in _scan_roots_for("flash_games"):
        for item in sorted(os.listdir(f_dir)):
            if item == "plugins" or item.startswith("."):
                continue
            sub = os.path.join(f_dir, item)
            register_flash_folder(sub, custom_id=item)

scan_games()

REVERSE_LOCALE_CACHE = {}

def _merge_locale_reverse_map(json_path: str, rev: dict) -> None:
    """读取一个语言包 JSON 文件，把"翻译后文本 -> 原始 key"的反向映射合并进 rev。

    从 get_reverse_locale() 拆出来的单文件加载逻辑，避免那边的
    "遍历文件 -> 遍历 JSON 键值对" 叠成三层嵌套。

    Args:
        json_path: 语言包 JSON 文件路径。
        rev: 累积结果的反向映射字典（原地修改，不返回新对象）。
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as jf:
            data = json.load(jf)
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if isinstance(v, str) and isinstance(k, str) and len(v) < 100:
                rev[v.strip().lower()] = k.strip()
    except Exception:
        pass


def get_reverse_locale(base_dir):
    """
    扫描游戏 locales/ 目录下的翻译 JSON 映射表，构建反向映射字典。
    解决多语言汉化补丁中将文件名改为中文导致游戏内核找不到原英文/日文资源的问题。
    """
    if base_dir in REVERSE_LOCALE_CACHE:
        return REVERSE_LOCALE_CACHE[base_dir]
    rev = {}
    locales_dir = os.path.join(base_dir, 'locales')
    if os.path.isdir(locales_dir):
        try:
            for root, dirs, files in os.walk(locales_dir):
                for f in files:
                    if f.endswith('.json'):
                        _merge_locale_reverse_map(os.path.join(root, f), rev)
        except Exception:
            pass
    REVERSE_LOCALE_CACHE[base_dir] = rev
    return rev

KNOWN_LOCALES = {'tw', 'ch', 'zh', 'zh-cn', 'zh-tw', 'en', 'ja', 'jp', 'es', 'ru', 'kr', 'fr', 'de'}

def try_strip_locale(rel_path: str):
    """尝试剥离 URL 路径中的语言前缀目录（如 img/zh-cn/pictures -> img/pictures）以实现自适应回退"""
    parts = rel_path.strip('/').split('/')
    new_parts = []
    removed = False
    for i, p in enumerate(parts):
        if not removed and p.lower() in KNOWN_LOCALES and i > 0 and i < len(parts) - 1:
            removed = True
            continue
        new_parts.append(p)
    return '/'.join(new_parts) if removed else None

def _resolve_case_insensitive_path_inner(base_dir, rel_path):
    """
    Linux 虚拟文件系统 (VFS) 大小写无关与扩展名混淆回退核心算法：
    1. 逐层路径贪婪匹配与 URL 解码
    2. RPG Maker 加密扩展名自动互转 (.rpgmvp <-> .png, .rpgmvo <-> .ogg, .rpgmvm <-> .m4a)
    3. 多语言旗帜与语言包命名互转 (flag_ <-> locale_)
    4. 反向翻译字典逆向匹配
    """
    current = base_dir
    decoded_path = urllib.parse.unquote(rel_path)
    parts = decoded_path.strip('/').split('/')
    for part in parts:
        if not part: continue
        target = os.path.join(current, part)
        if os.path.exists(target):
            current = target
        else:
            found = False
            if os.path.isdir(current):
                part_lower = part.lower()
                part_no_asar = part_lower[:-5] if part_lower.endswith('.asar') else part_lower
                
                candidates = [part_lower, part_no_asar]
                if part_lower.endswith('.png'):
                    candidates.extend([part_lower[:-4] + '.rpgmvp', part_lower + '_'])
                elif part_lower.endswith('.rpgmvp'):
                    candidates.extend([part_lower[:-7] + '.png', part_lower[:-7] + '.png_'])
                elif part_lower.endswith('.ogg'):
                    candidates.extend([part_lower[:-4] + '.rpgmvo', part_lower + '_'])
                elif part_lower.endswith('.rpgmvo'):
                    candidates.extend([part_lower[:-7] + '.ogg', part_lower[:-7] + '.ogg_'])
                elif part_lower.endswith('.m4a'):
                    candidates.extend([part_lower[:-4] + '.rpgmvm', part_lower + '_'])
                elif part_lower.endswith('.rpgmvm'):
                    candidates.extend([part_lower[:-7] + '.m4a', part_lower[:-7] + '.m4a_'])
                elif part_lower.endswith('.mp4'):
                    candidates.append(part_lower + '_')

                if part_lower.startswith('flag_'):
                    candidates.extend(['locale_' + part_lower[5:], 'locale_' + part_lower[5:] + '_'])
                elif part_lower.startswith('locale_'):
                    candidates.extend(['flag_' + part_lower[7:], 'flag_' + part_lower[7:] + '_'])

                entries = os.listdir(current)
                for entry in entries:
                    entry_lower = entry.lower()
                    if entry_lower in candidates:
                        current = os.path.join(current, entry)
                        found = True
                        break

                if not found and base_dir:
                    rev_dict = get_reverse_locale(base_dir)
                    stem, ext = os.path.splitext(part)
                    stem_lower = stem.strip().lower()
                    if stem_lower in rev_dict:
                        orig_key = rev_dict[stem_lower]
                        cand_names = [orig_key.lower() + ext.lower(), orig_key.lower()]
                        for entry in entries:
                            entry_lower = entry.lower()
                            if entry_lower in cand_names or entry_lower.startswith(orig_key.lower()):
                                current = os.path.join(current, entry)
                                found = True
                                break

            if not found:
                return os.path.join(current, part)
    return current

def resolve_case_insensitive_path(base_dir, rel_path):
    """URL 解码 + 忽略大小写智能查找 + 资源扩展名智能回退 + 翻译资源反向映射 + 语言子目录自适应回退"""
    res = _resolve_case_insensitive_path_inner(base_dir, rel_path)
    if os.path.exists(res):
        return res
    stripped = try_strip_locale(rel_path)
    if stripped:
        fallback_res = _resolve_case_insensitive_path_inner(base_dir, stripped)
        if os.path.exists(fallback_res):
            return fallback_res
    return res

GLOBAL_LOG_BUFFER = deque(maxlen=1000)
LOG_FILE_PATH = os.path.join(CACHE_DIR, "omni_deck.log")

def log_omni(level: str, msg: str, tag: str = None):
    """
    统一的 Omni-Deck 项目分级日志系统:
    - 带有 [Omni-Deck] 项目全局标签
    - 支持可选的子标签 [tag]（如具体的游戏ID、组件名）
    - 明确的日志等级 [INFO] / [WARN] / [ERROR] / [DEBUG]
    - 带终端 ANSI 颜色区分，同时写入内存环形缓冲区及 omni_deck.log 文件
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = "[Omni-Deck]"
    if tag:
        prefix += f"[{tag}]"
    prefix += f"[{level}]"

    log_entry = {
        'time': timestamp,
        'level': level,
        'tag': tag or 'Core',
        'msg': msg,
        'text': f"[{timestamp}] {prefix} {msg}"
    }
    GLOBAL_LOG_BUFFER.append(log_entry)

    # 写入文件持久化 (剔除 ANSI 颜色转义字符)
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {prefix} {msg}\n")
    except Exception:
        pass

    if level == "ERROR":
        color_code = "\033[91m"  # 红色
    elif level == "WARN":
        color_code = "\033[93m"  # 黄色
    elif level == "INFO":
        color_code = "\033[92m"  # 绿色
    elif level == "DEBUG":
        color_code = "\033[94m"  # 蓝色
    else:
        color_code = "\033[97m"
    reset_code = "\033[0m"

    try:
        sys.stderr.write(f"{color_code}{prefix} {msg}{reset_code}\n")
        sys.stderr.flush()
    except Exception:
        pass

def extract_game_id_from_path(path: str) -> str:
    """从 HTTP 请求 URL 路径或 QueryString 中精准提取当前交互的目标游戏 ID"""
    try:
        clean = path.split('?')[0]
        unq = urllib.parse.unquote(urllib.parse.unquote(clean))
        if unq.startswith('/game/'):
            parts = unq.split('/')
            if len(parts) >= 3:
                return parts[2]
        if unq.startswith('/save/'):
            parts = unq.split('/')
            if len(parts) >= 3:
                return parts[2]
        if '?game_id=' in path or '&game_id=' in path:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            if 'game_id' in qs:
                return qs['game_id'][0]
    except Exception:
        pass
    return None

def launch_standalone_game_process(game_id: str, title: str, on_exit_callback=None):
    """全局独立游戏启动器：既支持 Qt GUI 触发，也支持 Steam Deck 本机浏览器 API 触发"""
    if game_id in RUNNING_GAME_IDS:
        log_omni("WARN", f"游戏 [{title}] 已经在运行中，忽略重复启动请求", tag="Launcher")
        return False, "游戏已在运行中"

    game_data = GAMES_REGISTRY.get(game_id)
    if not game_data:
        scan_games(force=True)
        game_data = GAMES_REGISTRY.get(game_id)
    if not game_data:
        return False, f"未找到游戏配置: {game_id}"
    root = game_data['root']
    engine = game_data.get('engine', 'wine')
    exe_path = game_data.get('exe_path')

    cmd = None
    run_env = os.environ.copy()

    if engine == 'renpy':
        if exe_path and os.path.exists(exe_path):
            if exe_path.endswith('.sh') or exe_path.endswith('.py'):
                try: os.chmod(exe_path, 0o755)
                except: pass
                cmd = [exe_path]
            elif exe_path.endswith('.exe'):
                cmd, run_env = get_wine_or_proton_runner(exe_path, game_id=game_id)
        elif os.path.exists(RENPY_SDK_PATH):
            cmd = [RENPY_SDK_PATH, root]
    elif engine == '3ds':
        lime_app = '/home/deck/Applications/Lime3DS/Lime3DS.AppImage'
        if not os.path.exists(lime_app):
            lime_app = shutil.which('lime3ds') or '/home/deck/.local/bin/lime3ds'
        if exe_path and os.path.exists(exe_path):
            if exe_path.endswith('.sh') or exe_path.endswith('.AppImage'):
                try: os.chmod(exe_path, 0o755)
                except: pass
                cmd = [exe_path]
            else:
                # 正常窗口化启动 3DS ROM（不强制全屏，方便手柄与分屏调节）
                cmd = [lime_app, exe_path]
    else:
        if exe_path and os.path.exists(exe_path):
            if exe_path.endswith('.exe'):
                cmd, run_env = get_wine_or_proton_runner(exe_path, game_id=game_id)
            else:
                try: os.chmod(exe_path, 0o755)
                except: pass
                cmd = [exe_path]

    if not cmd:
        log_omni("ERROR", f"未找到可用的独立游戏/软件运行时 (Wine/Proton 未就绪) ({game_id})", tag="Launcher")
        return False, "未找到可用的独立游戏运行时 (Wine/Proton 未就绪)"

    if game_id and game_id.startswith('StarCraft II'):
        run_cwd = root
    else:
        run_cwd = os.path.dirname(exe_path) if (exe_path and os.path.exists(exe_path)) else root

    run_env['LANG'] = 'zh_CN.UTF-8'
    run_env['LC_ALL'] = 'zh_CN.UTF-8'
    run_env['WINEDEBUG'] = '-all'

    RUNNING_GAME_IDS.add(game_id)

    def runner():
        """在后台线程里拉起独立游戏子进程，把 stdout/stderr 落到 cache/game_<id>.log。"""
        safe_game_id = re.sub(r'\W+', '_', str(game_id)).strip('_')
        game_log_path = os.path.join(SCRIPT_DIR, "cache", f"game_{safe_game_id}.log")
        os.makedirs(os.path.dirname(game_log_path), exist_ok=True)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        log_omni("INFO", f"启动独立游戏: [{title}] (工作目录: {run_cwd})", tag="Launcher")
        log_omni("DEBUG", f"命令行参数: {cmd_str}", tag="Launcher")
        log_omni("DEBUG", f"独立进程标准输出/错误将记录至: {game_log_path}", tag="Launcher")

        try:
            with open(game_log_path, "wb") as g_log:
                proc = subprocess.Popen(
                    cmd,
                    cwd=run_cwd,
                    env=run_env,
                    preexec_fn=set_pdeathsig,
                    start_new_session=True,
                    stdout=g_log,
                    stderr=subprocess.STDOUT
                )
                ACTIVE_CHILD_PROCESSES.append(proc)
                log_omni("INFO", f"独立进程已在 Steam Deck 本机成功启动: [{title}] (PID: {proc.pid})", tag="Launcher")
                proc.wait()
                exit_code = proc.returncode
                log_omni("INFO" if exit_code == 0 else "WARN", f"独立进程已退出: [{title}] (退出码: {exit_code})", tag="Launcher")
                if exit_code != 0:
                    try:
                        with open(game_log_path, "r", encoding="utf-8", errors="ignore") as lf:
                            lines = lf.readlines()
                            if lines:
                                tail = "".join(lines[-10:]).strip()
                                log_omni("ERROR", f"游戏 [{title}] 异常退出末尾日志:\n{tail}", tag="Launcher")
                    except Exception:
                        pass
        except Exception as e:
            log_omni("ERROR", f"独立游戏运行异常 ({game_id}): {e}", tag="Launcher")
        finally:
            if 'proc' in locals() and proc in ACTIVE_CHILD_PROCESSES:
                ACTIVE_CHILD_PROCESSES.remove(proc)
            RUNNING_GAME_IDS.discard(game_id)
            if on_exit_callback:
                try:
                    on_exit_callback()
                except Exception:
                    pass

    threading.Thread(target=runner, daemon=True).start()
    return True, "已在 Steam Deck 屏幕启动游戏"

class MultiGameRequestHandler(SimpleHTTPRequestHandler):
    """
    Omni Deck 核心 HTTP 请求调度分发处理器：
    1. 门禁与安全控制 (parse_request)：
       - 局域网请求闸门拦截 (LAN_SHARING_ENABLED)
       - Cloudflare 广域网公网请求闸门拦截 (WAN_SHARING_ENABLED)
    2. 虚拟文件系统映射 (translate_path)：
       - 映射大厅静态前端 (/hub.html, /hub.js, /marked.min.js, /mermaid.min.js)
       - 映射模拟器核心 (/emulatorjs/, /player_retro.html) 与 Flash (/ruffle/, /player_flash.html)
       - 映射游戏资源虚拟路径 (/game/<id>/ -> 实际物理路径并结合 VFS 模糊大小写查找)
       - 映射游戏存档路径 (/save/<id>/)
    3. RESTful API 路由分发 (do_GET, do_POST, do_DELETE)：
       - 游戏与媒体库扫描索引 API (/api/games, /api/manga/library, /api/novels/library, /api/docs/explorer, /api/audio/list)
       - 异步流媒体点播与分段传输 (Range 请求支持) (/api/audio/stream)
       - 实时事件广播 Server-Sent Events (/api/events)
       - 网络状态与远程共享开关控制 (/api/lan/status, /api/lan/toggle, /api/wan/status, /api/wan/toggle)
       - 在线检索、异步下载任务与队列管理 (/api/manga/*, /api/novels/*)
    """
    def log_message(self, format, *args):
        """覆盖父类默认的访问日志：静音正常 2xx/3xx 与游戏常规探测 404，其余写进 log_omni。

        Args:
            format: printf 风格格式串（父类约定的签名）。
            *args: 格式化参数，约定 args[0] 是请求行、args[1] 是状态码。
        """
        # 彻底静音所有正常 2xx / 3xx 与游戏常规探测 HEAD / 404 日志
        try:
            req = str(args[0]) if len(args) >= 1 else ""
            code = str(args[1]) if len(args) >= 2 else ""
            if code.startswith(('2', '3')):
                return
            if code == '404' and ('HEAD ' in req or '/save/' in req or '.rpgsave' in req or 'favicon.ico' in req
                                   or '/api/patch/' in req or '/api/shortvideo/thumb' in req or '/api/shortvideo/stream' in req
                                   or '/api/shortvideo/gallery_image' in req):
                return
            tag = extract_game_id_from_path(req) or "Server"
            if code.startswith('5'):
                log_omni("ERROR", f"HTTP {code} on {req}", tag=tag)
            else:
                log_omni("WARN", f"HTTP {code} on {req}", tag=tag)
        except Exception:
            pass

    def parse_request(self):
        """请求解析钩子：在真正处理请求前做局域网/广域网访问闸门拦截。

        Returns:
            bool: 允许继续处理返回 True；命中闸门时直接回 403 页面并返回 False，
            调用方（BaseHTTPRequestHandler）据此中止后续的 do_GET/do_POST 分发。
        """
        if not super().parse_request():
            return False

        client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
        local_ip = get_local_ip()
        is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
        is_local = (client_ip in ('127.0.0.1', 'localhost', '::1', local_ip)) and not is_cf

        # 1. 广域网公网请求闸门拦截（外部通过 omni.cxy251.uk 访问）
        if is_cf and not WAN_SHARING_ENABLED:
            self.send_response(403)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write("<html><body style='background:#0d1117;color:#f0f6fc;font-family:sans-serif;text-align:center;padding-top:80px;'><h2>🔒 广域网公网访问已关闭</h2><p style='color:#8b949e;margin-top:12px;'>Steam Deck 上的 Omni Deck 广域网远程访问开关目前处于关闭状态。<br>如需在外部网络访问，请在 Steam Deck 屏幕右上角点击【广域网】开关开启。</p></body></html>".encode('utf-8'))
            return False

        # 2. 外部局域网设备请求闸门拦截（外部通过 192.168.0.x 访问）
        if not is_local and not is_cf and not LAN_SHARING_ENABLED:
            self.send_response(403)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write("<html><body style='background:#0d1117;color:#f0f6fc;font-family:sans-serif;text-align:center;padding-top:80px;'><h2>🔒 局域网跨设备共享已关闭</h2><p style='color:#8b949e;margin-top:12px;'>Steam Deck 上的 Omni Deck 局域网共享功能目前处于关闭状态。<br>如需在手机或平板上访问，请在 Steam Deck 屏幕右上角点击【局域网共享】按钮开启。</p></body></html>".encode('utf-8'))
            return False

        return True

    def check_is_local(self) -> bool:
        """判断当前请求是否来自本机（127.0.0.1/本机屏幕），Cloudflare 转发的一律不算本机。

        Returns:
            bool: 是本机请求返回 True。
        """
        client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
        local_ip = get_local_ip()
        is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
        return (client_ip in ('127.0.0.1', 'localhost', '::1', local_ip)) and not is_cf

    def check_nsfw_authorized(self) -> bool:
        """判断当前请求是否有权限访问 NSFW/成人专区内容。

        Returns:
            bool: 有权限返回 True（本机始终放行，非本机需要有效 Token）。
        """
        is_local = self.check_is_local()
        return privacy_service.is_request_authorized(self, is_local)

    # 非本机（局域网/广域网）访客：只能翻本地已下好的媒体，不能联网搜/不能拉新下载。
    # 下载类 POST 端点各自已有 is_local 拦截；这里补上联网"搜索/榜单/详情/在线封面"这些 GET。
    _REMOTE_BLOCKED_ONLINE = (
        '/api/manga/search', '/api/manga/rankings', '/api/manga/detail',
        '/api/manga/online_cover', '/api/novels/search',
    )

    def deny_if_remote_online(self) -> bool:
        """命中联网端点且非本机 → 回 403 并返回 True（调用方直接 return）。"""
        if not self.path.startswith(self._REMOTE_BLOCKED_ONLINE):
            return False
        if self.check_is_local():
            return False
        self.send_response(403)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"error":"Forbidden: online search/download is local-only"}')
        return True

    def log_error(self, format, *args):
        """覆盖父类默认的错误日志：过滤掉 favicon/404 噪音，其余写进 log_omni 并带上游戏 tag。

        Args:
            format: printf 风格格式串（父类约定的签名）。
            *args: 格式化参数。
        """
        try:
            msg = format % args
            if "favicon.ico" in self.path or "fav.ico" in self.path or "code 404" in msg:
                return
            tag = extract_game_id_from_path(self.path) or "Server"
            log_omni("ERROR", f"{msg} (path: {self.path})", tag=tag)
        except Exception:
            pass

    def copyfile(self, source, outputfile):
        """覆盖父类的静态文件传输：吞掉客户端中途断开连接的异常，避免刷一堆无意义报错。

        Args:
            source: 源文件对象。
            outputfile: 目标输出流（通常是 self.wfile）。
        """
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def translate_path(self, path):
        """把请求路径映射成实际物理文件路径——大厅前端资源、模拟器核心、游戏/存档虚拟路径
        都在这里做重定向，是整个 Direct FS Bridge 虚拟文件系统的核心入口。

        Args:
            path: 原始请求路径（可能带 query string/fragment）。

        Returns:
            str: 解析后的物理文件路径。
        """
        clean_path = path.split('?')[0].split('#')[0]
        unquoted = urllib.parse.unquote(urllib.parse.unquote(clean_path))

        if unquoted in ['/', '/hub.html']:
            return HUB_HTML_PATH

        if unquoted in ['/hub.js', '/assets/hub.js']:
            return HUB_JS_PATH

        if unquoted in ['/marked.min.js', '/assets/marked.min.js']:
            return os.path.join(ASSETS_DIR, 'marked.min.js')

        if unquoted in ['/mermaid.min.js', '/assets/mermaid.min.js']:
            return os.path.join(ASSETS_DIR, 'mermaid.min.js')

        if unquoted in ['/player_retro.html']:
            return PLAYER_RETRO_HTML

        if unquoted in ['/player_flash.html']:
            return PLAYER_FLASH_HTML

        if unquoted.startswith('/assets/'):
            rel = unquoted[len('/assets/'):]
            if rel.startswith('ruffle/'):
                return os.path.join(FLASH_GAMES_DIR, 'plugins', rel)
            return os.path.join(ASSETS_DIR, rel)

        if unquoted.startswith('/ruffle/'):
            rel = unquoted[len('/ruffle/'):]
            return os.path.join(FLASH_GAMES_DIR, 'plugins', 'ruffle', rel)

        if unquoted.startswith('/plugins/'):
            rel = unquoted[len('/plugins/'):]
            p_flash = os.path.join(FLASH_GAMES_DIR, 'plugins', rel)
            if os.path.exists(p_flash):
                return p_flash
            p1 = os.path.join(SCRIPT_DIR, 'plugins', rel)
            if os.path.exists(p1):
                return p1
            return p_flash

        if unquoted.startswith('/emulatorjs/'):
            rel = unquoted[len('/emulatorjs/'):]
            return resolve_case_insensitive_path(EMULATORJS_DIR, rel)

        if unquoted.startswith('/retro_rom/'):
            subparts = [p for p in unquoted[len('/retro_rom/'):].split('/') if p]
            game_id = subparts[0] if subparts else ''
            req_file = subparts[1] if len(subparts) > 1 else None
            if game_id in GAMES_REGISTRY:
                gdata = GAMES_REGISTRY[game_id]
                return os.path.join(gdata['root'], req_file or gdata['rom_file'])
            for gid, gdata in GAMES_REGISTRY.items():
                if gid.lower() == game_id.lower():
                    return os.path.join(gdata['root'], req_file or gdata['rom_file'])

        if unquoted.startswith('/game/'):
            parts = unquoted.split('/')
            if len(parts) >= 3:
                game_id = parts[2]
                if game_id in GAMES_REGISTRY:
                    rel_path = '/'.join(parts[3:])
                    return resolve_case_insensitive_path(GAMES_REGISTRY[game_id]['root'], rel_path)
                for gid, gdata in GAMES_REGISTRY.items():
                    if gid.lower() == game_id.lower():
                        rel_path = '/'.join(parts[3:])
                        return resolve_case_insensitive_path(gdata['root'], rel_path)

        return super().translate_path(path)

    def do_HEAD(self):
        """处理 HEAD 请求：存档文件走专门的存在性检查，其余资源走快速存在性判断后交给父类。"""
        if self.path.startswith('/save/'):
            parts = urllib.parse.unquote(self.path).split('/')
            if len(parts) >= 4:
                game_id = parts[2]
                filename = os.path.basename(parts[3].split('?')[0])
                if game_id in GAMES_REGISTRY:
                    target_file = os.path.join(GAMES_REGISTRY[game_id]['save_dir'], filename)
                    if os.path.exists(target_file):
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                        self.send_header('Content-Length', str(os.path.getsize(target_file)))
                        self.end_headers()
                        return
            self.send_response(404)
            self.end_headers()
            return
            
        # Fast path existence check for games and general assets
        resolved_path = self.translate_path(self.path)
        if resolved_path and os.path.exists(resolved_path):
            self.send_response(200)
            self.end_headers()
            return
            
        super().do_HEAD()

    def do_GET(self):
        """GET 请求总路由：一长串 `if self.path.startswith(...)` 依次匹配 `/api/*` 接口
        （游戏/媒体库查询、流媒体点播、SSE 事件、网络共享开关状态等），一个都不命中时
        落到最后交给父类按静态文件处理（走 translate_path() 解析出的物理路径）。

        本方法只做路由分发，具体业务逻辑都在各 service 模块里；新增路由直接在方法体里
        按 `if self.path.startswith('/api/xxx')` 的既有写法插入即可。
        """
        if self.deny_if_remote_online():
            return
        if self.path.startswith('/api/_alive'):
            body = json.dumps({'magic': _INSTANCE_MAGIC, 'pid': os.getpid()}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith('/api/_mem'):
            info = {'pid': os.getpid(), 'restart_threshold_mb': MEM_RESTART_MB, 'procs': []}
            try:
                import psutil
                me = psutil.Process()
                total = 0
                for p in [me] + me.children(recursive=True):
                    try:
                        rss = p.memory_info().rss
                        total += rss
                        info['procs'].append({'pid': p.pid, 'name': (p.name() or '')[:40],
                                              'rss_mb': round(rss / 1048576, 1),
                                              'threads': p.num_threads()})
                    except Exception:
                        pass
                info['total_rss_mb'] = round(total / 1048576, 1)
                info['procs'].sort(key=lambda x: -x['rss_mb'])
            except Exception as e:
                info['error'] = str(e)
            body = json.dumps(info, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith('/api/auth/status'):
            is_local = self.check_is_local()
            unlocked = privacy_service.is_request_authorized(self, is_local)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'is_local': is_local,
                'unlocked': unlocked
            }).encode('utf-8'))
            return

        if self.path.startswith('/api/logs'):
            parsed_url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed_url.query)
            level_filter = qs.get('level', [''])[0].upper()
            tag_filter = qs.get('tag', [''])[0]
            game_id = qs.get('game_id', [''])[0]
            limit = 200
            try:
                limit = int(qs.get('lines', [200])[0])
            except Exception:
                limit = 200
            limit = max(1, min(limit, 1000))

            game_specific_log = None
            if game_id:
                safe_gid = re.sub(r'\W+', '_', str(game_id)).strip('_')
                glog_path = os.path.join(SCRIPT_DIR, "cache", f"game_{safe_gid}.log")
                if os.path.exists(glog_path):
                    try:
                        with open(glog_path, "r", encoding="utf-8", errors="ignore") as gf:
                            glines = gf.readlines()
                            game_specific_log = "".join(glines[-limit:])
                    except Exception as ge:
                        game_specific_log = f"读取游戏日志失败: {ge}"
                else:
                    game_specific_log = "暂无该游戏的独立进程输出日志 (游戏尚未运行或已清理)"

            available_game_logs = []
            cache_dir = os.path.join(SCRIPT_DIR, "cache")
            if os.path.exists(cache_dir):
                for f in sorted(os.listdir(cache_dir)):
                    if f.startswith("game_") and f.endswith(".log"):
                        fpath = os.path.join(cache_dir, f)
                        try:
                            fstat = os.stat(fpath)
                            available_game_logs.append({
                                'filename': f,
                                'size': fstat.st_size,
                                'mtime': fstat.st_mtime,
                                'game_key': f[5:-4]
                            })
                        except Exception:
                            pass

            logs = list(GLOBAL_LOG_BUFFER)
            if level_filter and level_filter != 'ALL':
                logs = [entry for entry in logs if entry.get('level') == level_filter]
            if tag_filter:
                logs = [entry for entry in logs if tag_filter.lower() in entry.get('tag', '').lower()]
            logs = logs[-limit:]

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'ok',
                'logs': logs,
                'game_log': game_specific_log,
                'available_game_logs': available_game_logs
            }, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/game/'):
            parts = urllib.parse.unquote(self.path).split('/')
            if len(parts) >= 3:
                gid = parts[2]
                gdata = GAMES_REGISTRY.get(gid)
                if not gdata:
                    for k, v in GAMES_REGISTRY.items():
                        if k.lower() == gid.lower():
                            gdata = v
                            break
                if gdata and (gdata.get('type') in ('rpg', 'slg') or gdata.get('category') in ('rpg', 'slg')):
                    if not self.check_nsfw_authorized():
                        self.send_response(403)
                        self.send_header('Content-Type', 'text/plain; charset=utf-8')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b"NSFW game content is locked")
                        return

        if self.path.startswith('/api/readdir?'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if 'path' in qs:
                req_path = urllib.parse.unquote(urllib.parse.unquote(qs['path'][0])).lstrip('/')
                target_path = req_path
                
                game_id = None
                if 'game_id' in qs:
                    raw_gid = urllib.parse.unquote(urllib.parse.unquote(qs['game_id'][0]))
                    if raw_gid in GAMES_REGISTRY:
                        game_id = raw_gid
                    else:
                        for gid_candidate in GAMES_REGISTRY:
                            if gid_candidate.lower() == raw_gid.lower():
                                game_id = gid_candidate
                                break
                
                if game_id and game_id in GAMES_REGISTRY:
                    game_dir = GAMES_REGISTRY[game_id]['root']
                    target_path = resolve_case_insensitive_path(game_dir, req_path)
                elif not os.path.isabs(target_path):
                    target_path = resolve_case_insensitive_path(SCRIPT_DIR, target_path)
                else:
                    if not os.path.exists(target_path):
                        parts = target_path.strip('/').split('/')
                        current_path = '/'
                        for part in parts:
                            if not part: continue
                            if os.path.exists(os.path.join(current_path, part)):
                                current_path = os.path.join(current_path, part)
                            else:
                                try:
                                    dir_contents = os.listdir(current_path)
                                    lower_part = part.lower()
                                    matched = False
                                    for item in dir_contents:
                                        if item.lower() == lower_part:
                                            current_path = os.path.join(current_path, item)
                                            matched = True
                                            break
                                    if not matched:
                                        current_path = os.path.join(current_path, part)
                                except Exception:
                                    current_path = os.path.join(current_path, part)
                        target_path = current_path

                if target_path and os.path.isdir(target_path):
                    files = os.listdir(target_path)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(files).encode('utf-8'))
                    return
                else:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'[]')
                    return
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'[]')
            return
        if self.path.startswith('/api/patch/'):
            game_id = urllib.parse.unquote(self.path.split('/')[3].split('?')[0])
            if game_id.endswith('.js'): game_id = game_id[:-3]
            patch_path = None
            if game_id in GAMES_REGISTRY:
                patch_path = os.path.join(GAMES_REGISTRY[game_id]['root'], "adapter.js")
            else:
                patch_path = os.path.join(RPG_GAMES_DIR, game_id, "adapter.js")
            if patch_path and os.path.exists(patch_path):
                self.send_response(200)
                self.send_header('Content-type', 'application/javascript')
                self.end_headers()
                with open(patch_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(200)
                self.send_header('Content-type', 'application/javascript')
                self.end_headers()
                self.wfile.write(b'// default adapter\n')
            return

        if self.path.startswith('/api/sc2/maps'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(sc2_panel_service.list_maps(), ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/sc2/mods'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(sc2_panel_service.list_mods(), ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/sc2/status'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(sc2_panel_service.get_status(), ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/sc2/thumb/'):
            stem = urllib.parse.unquote(self.path.split('/api/sc2/thumb/', 1)[1]).rsplit('.png', 1)[0]
            p = sc2_panel_service.thumb_path(stem)
            if not p:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(p, 'rb') as f:
                self.wfile.write(f.read())
            return

        if self.path.startswith('/api/games'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            force_refresh = ('force' in qs or 'refresh' in qs)
            scan_games(force=force_refresh)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            games_list = list(GAMES_REGISTRY.values())
            if not self.check_nsfw_authorized():
                games_list = [g for g in games_list if g.get('type') not in ('rpg', 'slg') and g.get('category') not in ('rpg', 'slg')]
            self.wfile.write(json.dumps(games_list, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/player_retro.html'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(PLAYER_RETRO_HTML, 'rb') as f:
                self.wfile.write(f.read())
            return

        if self.path.startswith('/retro_rom/'):
            raw_path = self.path[len('/retro_rom/'):].split('?')[0].split('#')[0]
            subparts = [urllib.parse.unquote(p) for p in raw_path.split('/') if p]
            game_id = subparts[0] if subparts else ''
            if game_id not in GAMES_REGISTRY:
                scan_games()
            if game_id in GAMES_REGISTRY and GAMES_REGISTRY[game_id].get('type') == 'retro':
                gdata = GAMES_REGISTRY[game_id]
                req_file = subparts[1] if len(subparts) > 1 else gdata['rom_file']
                target_file = os.path.join(gdata['root'], req_file)
                if not os.path.exists(target_file):
                    target_file = os.path.join(gdata['root'], gdata['rom_file'])
                if os.path.exists(target_file):
                    self.send_response(200)
                    self.send_header('Content-type', 'application/octet-stream')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    with open(target_file, 'rb') as f:
                        data = f.read()
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_response(404)
            self.end_headers()
            return

        if self.path.startswith('/flash_swf/'):
            raw_path = self.path[len('/flash_swf/'):].split('?')[0].split('#')[0]
            subparts = [urllib.parse.unquote(p) for p in raw_path.split('/') if p]
            game_id = subparts[0] if subparts else ''
            if game_id not in GAMES_REGISTRY:
                scan_games()
            if game_id in GAMES_REGISTRY and GAMES_REGISTRY[game_id].get('type') == 'flash':
                gdata = GAMES_REGISTRY[game_id]
                req_file = subparts[1] if len(subparts) > 1 else gdata.get('swf_file')
                if req_file:
                    target_file = os.path.join(gdata['root'], req_file)
                    if os.path.exists(target_file):
                        self.send_response(200)
                        self.send_header('Content-type', 'application/x-shockwave-flash')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        with open(target_file, 'rb') as f:
                            data = f.read()
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
            self.send_response(404)
            self.end_headers()
            return

        if self.path.startswith('/icon/'):
            game_id = urllib.parse.unquote(self.path.replace('/icon/', '').split('?')[0])
            if game_id in GAMES_REGISTRY and GAMES_REGISTRY[game_id]['icon']:
                icon_file = GAMES_REGISTRY[game_id]['icon']
                if os.path.exists(icon_file):
                    self.send_response(200)
                    self.send_header('Content-type', 'image/png')
                    with open(icon_file, 'rb') as f:
                        self.wfile.write(f.read())
                    return
            self.send_response(200)
            self.send_header('Content-type', 'image/svg+xml')
            self.end_headers()
            self.wfile.write(DEFAULT_SVG_ICON)
            return

        if self.path.startswith('/save/'):
            parts = urllib.parse.unquote(self.path).split('/')
            if len(parts) >= 4:
                game_id = parts[2]
                filename = os.path.basename(parts[3].split('?')[0])
                if game_id in GAMES_REGISTRY:
                    target_file = os.path.join(GAMES_REGISTRY[game_id]['save_dir'], filename)
                    if os.path.exists(target_file):
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain; charset=utf-8')
                        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                        with open(target_file, 'rb') as f:
                            data = f.read()
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
        # --- 非 NSFW 有声书前端直接读的"静态"JSON快照 ---
        # 这个文件本来是 audio_service.update_standard_catalog_json() 写盘的缓存，但前端切换成
        # 直接读这个静态路径之后，没人再触发过会重新扫描/重写它的那条 API 了——文件就冻结在了
        # 「stream_url 还是 /audio/standard/... 这种旧静态直链」的年代（那条路由早就没了，
        # 现在统一走支持 Range 分段的 /api/audio/stream）。结果就是有声书打开了但放不出声音。
        # 这里直接拦下这个路径，每次都强制重新扫描一遍再吐出去，stream_url 永远是当前代码生成的、
        # 真正能播的地址，不会再冻结成史前版本。
        if self.path.startswith('/audio/standard_catalog.json'):
            data = audio_service.get_standard_catalog()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        # --- Crawler Download Panel Routes ---
        if self.path.startswith('/api/crawler/types'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(crawler_service.list_job_types(), ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/crawler/jobs/'):
            job_id = self.path.replace('/api/crawler/jobs/', '').split('?')[0]
            job = crawler_service.get_job(job_id)
            self.send_response(200 if job else 404)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(job or {'error': '任务不存在'}, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/crawler/jobs'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(crawler_service.list_jobs(), ensure_ascii=False).encode('utf-8'))
            return

        # --- Audio Stream & Library Routes ---
        if self.path.startswith('/api/audio/library'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            is_nsfw = qs.get('nsfw', ['0'])[0] in ('1', 'true', 'True') or qs.get('mode', [''])[0] == 'nsfw'
            if is_nsfw and not self.check_nsfw_authorized():
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'items': [], 'total': 0, 'page': 1, 'page_size': 80, 'albums': [], 'is_nsfw': True}).encode('utf-8'))
                return
            q = qs.get('q', [''])[0] or ''
            album = qs.get('album', ['all'])[0] or 'all'
            page = int(qs.get('page', ['1'])[0] or 1)
            page_size = int(qs.get('page_size', ['80'])[0] or 80)
            data = audio_service.query_audio_library(q=q, album=album, is_nsfw=is_nsfw, page=page, page_size=page_size)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/audio/stream'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = qs.get('name', [''])[0] or qs.get('path', [''])[0]
            is_nsfw = qs.get('nsfw', ['0'])[0] in ('1', 'true', 'True')
            if is_nsfw and not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Audio is locked"}')
                return
            full_path = audio_service.find_audio_file(name, is_nsfw=is_nsfw)
            if not full_path or not os.path.exists(full_path):
                self.send_response(404)
                self.end_headers()
                return

            file_size = os.path.getsize(full_path)
            range_header = self.headers.get('Range', '')
            ext = os.path.splitext(full_path)[1].lower()
            mime_map = {
                '.mp3': 'audio/mpeg',
                '.m4a': 'audio/mp4',
                '.m4b': 'audio/mp4',
                '.flac': 'audio/flac',
                '.wav': 'audio/wav',
                '.ogg': 'audio/ogg',
                '.opus': 'audio/opus',
                '.aac': 'audio/aac'
            }
            content_type = mime_map.get(ext, 'audio/mpeg')

            if range_header and range_header.startswith('bytes='):
                ranges = range_header[6:].split('-')
                start = int(ranges[0]) if ranges[0] else 0
                end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(206)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Content-Length', str(length))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                with open(full_path, 'rb') as f:
                    f.seek(start)
                    chunk_size = 65536
                    bytes_left = length
                    while bytes_left > 0:
                        to_read = min(chunk_size, bytes_left)
                        chunk = f.read(to_read)
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
                        bytes_left -= len(chunk)
            else:
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(file_size))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open(full_path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
            return

        # --- 短视频画廊（Downloads/快手/<主播>/*.mp4，来自 ExtensionForge 002 插件）---
        # 内容是私人下的主播视频，跟其它 NSFW 分区一个安全模型：本机随便看，
        # 非本机（局域网/广域网）要过 privacy_service 的 token 校验。
        if self.path.startswith(('/api/shortvideo/library', '/api/shortvideo/thumb', '/api/shortvideo/stream', '/api/shortvideo/transcode_status', '/api/shortvideo/gallery_image')):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: short-video gallery is locked"}')
                return

            if self.path.startswith('/api/shortvideo/transcode_status'):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                platform = qs.get('platform', ['kuaishou'])[0] or 'kuaishou'
                data = shortvideo_service.transcode_status(platform)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/shortvideo/library'):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                platform = qs.get('platform', ['kuaishou'])[0] or 'kuaishou'
                q = qs.get('q', [''])[0] or ''
                folder = qs.get('folder', ['all'])[0] or 'all'
                page = int(qs.get('page', ['1'])[0] or 1)
                page_size = int(qs.get('page_size', ['60'])[0] or 60)
                data = shortvideo_service.query_shortvideo_library(platform=platform, q=q, folder=folder, page=page, page_size=page_size)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/shortvideo/thumb'):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                platform = qs.get('platform', ['kuaishou'])[0] or 'kuaishou'
                rel_p = qs.get('path', [''])[0]
                thumb_p = shortvideo_service.get_video_thumb(platform, rel_p)
                if not thumb_p or not os.path.exists(thumb_p):
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-type', 'image/webp')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', '*')
                with open(thumb_p, 'rb') as f:
                    data = f.read()
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if self.path.startswith('/api/shortvideo/gallery_image'):
                # 图集（抖音多图作品）里第 idx 张原图，浏览器原生显示 webp/jpg，不用转码
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                platform = qs.get('platform', ['kuaishou'])[0] or 'kuaishou'
                rel_p = qs.get('path', [''])[0]
                idx = int(qs.get('idx', ['0'])[0] or 0)
                img_p, content_type = shortvideo_service.get_gallery_image(platform, rel_p, idx)
                if not img_p or not os.path.exists(img_p):
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-type', content_type or 'application/octet-stream')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', '*')
                with open(img_p, 'rb') as f:
                    data = f.read()
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if self.path.startswith('/api/shortvideo/stream'):
                # 本机 QtWebEngine 没有 H.264 解码器，放不了原始 mp4——现转 VP9/WebM（有缓存）；
                # 局域网/远程设备是正常浏览器，解码原始 H.264 没问题，直接给原始文件，不转码。
                # 两边用的是同一个 <video> 标签、同一个接口，前端不用关心是谁在看。
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                platform = qs.get('platform', ['kuaishou'])[0] or 'kuaishou'
                rel_p = qs.get('path', [''])[0]
                full_path, content_type = shortvideo_service.get_playable_for_client(platform, rel_p, self.check_is_local())
                if not full_path or not os.path.exists(full_path):
                    self.send_response(503 if rel_p else 404)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'{"error": "video not found or transcode failed"}')
                    return

                file_size = os.path.getsize(full_path)
                range_header = self.headers.get('Range', '')

                if range_header and range_header.startswith('bytes='):
                    ranges = range_header[6:].split('-')
                    start = int(ranges[0]) if ranges[0] else 0
                    end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else file_size - 1
                    end = min(end, file_size - 1)
                    length = end - start + 1

                    self.send_response(206)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()

                    with open(full_path, 'rb') as f:
                        f.seek(start)
                        chunk_size = 65536
                        bytes_left = length
                        while bytes_left > 0:
                            to_read = min(chunk_size, bytes_left)
                            chunk = f.read(to_read)
                            if not chunk:
                                break
                            try:
                                self.wfile.write(chunk)
                            except (BrokenPipeError, ConnectionResetError):
                                break
                            bytes_left -= len(chunk)
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Length', str(file_size))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    with open(full_path, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
                return

        # --- Manga & Media Hub API Routes ---
        if self.path.startswith(('/api/novels/search', '/api/novels/queue', '/api/novels/tasks')):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Novels is locked"}')
                return

        if self.path.startswith('/api/novels/library'):
            if not self.check_nsfw_authorized():
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'[]')
                return
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q', [''])[0] or ''
            is_nsfw = qs.get('nsfw', ['0'])[0] in ('1', 'true', 'True') or qs.get('mode', [''])[0] == 'nsfw'
            items = novel_service.get_novels_library(q, is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(items, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/docs/explorer'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sub_dir = qs.get('dir', [''])[0]
            q = qs.get('q', [''])[0]
            doc_filter = qs.get('ext', ['all'])[0]
            data = novel_service.get_docs_explorer(sub_dir=sub_dir, q=q, doc_filter=doc_filter)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/docs/library'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q', [''])[0] or ''
            doc_filter = qs.get('ext', ['all'])[0]
        if self.path.startswith('/api/open_external_url'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            target_url = qs.get('url', [''])[0]
            if target_url.startswith(('http://', 'https://')):
                try:
                    subprocess.Popen(['xdg-open', target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    try:
                        import webbrowser
                        webbrowser.open(target_url)
                    except Exception:
                        pass
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        if self.path.startswith('/api/novels/search'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q', [''])[0] or ''
            is_nsfw = qs.get('nsfw', ['0'])[0] in ('1', 'true', 'True') or qs.get('mode', [''])[0] == 'nsfw'
            results = novel_service.search_online_novels(q, is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(results, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/cover'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel_path = qs.get('path', [''])[0] or qs.get('name', [''])[0]
            full_path = novel_service.resolve_novel_or_doc_path(rel_path)
            if not self.check_nsfw_authorized():
                if not (full_path and full_path.startswith(novel_service.DOCS_DIR)):
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Forbidden: Novels is locked"}')
                    return
            if full_path and full_path.endswith('.epub') and os.path.exists(full_path):
                meta = novel_service.extract_epub_metadata_and_cover(full_path)
                cover_bytes = meta.get('cover_bytes')
                if cover_bytes:
                    self.send_response(200)
                    self.send_header('Content-type', 'image/jpeg')
                    self.send_header('Cache-Control', 'max-age=86400')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(cover_bytes)
                    return
            self.send_response(404)
            self.end_headers()
            return

        if self.path.startswith('/api/novels/queue'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            is_nsfw = qs.get('nsfw', ['0'])[0] in ('1', 'true', 'True') or qs.get('mode', [''])[0] == 'nsfw'
            q_items = novel_service.load_novel_queue(is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(q_items, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/tasks'):
            tasks = novel_service.get_novel_active_tasks()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(tasks, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/read'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel_path = qs.get('path', [''])[0] or qs.get('name', [''])[0]
            data = novel_service.read_novel_file(rel_path)
            if data:
                if data.get('type') != 'tech' and not self.check_nsfw_authorized():
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Forbidden: Novels is locked"}')
                    return
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith(('/api/manga/cover', '/api/manga/online_cover', '/api/manga/pages', '/api/manga/page', '/api/manga/rankings', '/api/manga/detail', '/api/manga/search', '/api/manga/queue', '/api/manga/tasks', '/api/manga/recover_temp')):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Manga is locked"}')
                return

        if self.path.startswith('/api/manga/library'):
            if not self.check_nsfw_authorized():
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'[]')
                return
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q', [''])[0] or ''
            target_dir = qs.get('dir', ['manga'])[0] or qs.get('type', ['manga'])[0]
            items = manga_service.get_local_library(q, target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(items, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/cover'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = qs.get('name', [''])[0]
            target_dir = qs.get('dir', [''])[0]
            want_full = qs.get('full', ['0'])[0] in ('1', 'true')
            # 默认发磁盘缓存的缩略图（网格用），源没变就不再开压缩包；?full=1 发原图
            if not want_full:
                tp = manga_service.get_cbz_cover_thumb(name, target_dir=target_dir)
                if tp and os.path.exists(tp):
                    with open(tp, 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header('Content-type', 'image/webp')
                    self.send_header('Cache-Control', 'public, max-age=86400')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(data)
                    return
            data = manga_service.get_cbz_cover_bytes(name, target_dir=target_dir)
            if data:
                self.send_response(200)
                self.send_header('Content-type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith('/api/manga/online_cover'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            aid = qs.get('id', [''])[0]
            data = manga_service.get_online_cover_bytes(aid)
            if data:
                self.send_response(200)
                self.send_header('Content-type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith('/api/manga/pages'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = qs.get('name', [''])[0]
            target_dir = qs.get('dir', [''])[0]
            pages = manga_service.get_cbz_pages(name, target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(pages, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/page'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            name = qs.get('name', [''])[0]
            page = qs.get('page', [''])[0]
            target_dir = qs.get('dir', [''])[0]
            data = manga_service.get_cbz_page_bytes(name, page, target_dir=target_dir)
            if data:
                self.send_response(200)
                self.send_header('Content-type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith('/api/lan/status') or self.path.startswith('/api/client/info'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            ip = get_local_ip()
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', ip)) and not is_cf
            resp = {
                'enabled': LAN_SHARING_ENABLED,
                'ip': ip,
                'port': PORT,
                'url': f'http://{ip}:{PORT}',
                'is_local': is_local,
                'is_remote': not is_local,
                'client_ip': client_ip,
                'unlocked': self.check_nsfw_authorized()
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        if self.path.startswith('/api/wan/status'):
            resp = get_wan_status()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/events'):
            import queue
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            q = queue.Queue()
            manga_service.add_event_listener(q)
            try:
                client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
                is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
                ip = get_local_ip()
                is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', ip)) and not is_cf
                init_event = {
                    'type': 'init',
                    'manga_queue': manga_service.get_persistent_queue(target_dir='manga'),
                    'novel_queue': manga_service.get_persistent_queue(target_dir='novels'),
                    'queue': manga_service.get_persistent_queue(target_dir='manga'),
                    'tasks': manga_service.get_all_tasks(),
                    'lan': {
                        'enabled': LAN_SHARING_ENABLED,
                        'ip': ip,
                        'port': PORT,
                        'url': f'http://{ip}:{PORT}',
                        'is_local': is_local,
                        'is_remote': not is_local
                    },
                    'wan': get_wan_status()
                }
                self.wfile.write(f"data: {json.dumps(init_event, ensure_ascii=False)}\n\n".encode('utf-8'))
                self.wfile.flush()

                while True:
                    try:
                        ev = q.get(timeout=20)
                        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode('utf-8'))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError, Exception):
                pass
            finally:
                manga_service.remove_event_listener(q)
            return

        if self.path.startswith('/api/manga/queue'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            target_dir = qs.get('dir', ['manga'])[0] or qs.get('type', ['manga'])[0]
            items = manga_service.get_persistent_queue(target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(items, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/search'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get('q', [''])[0]
            page = int(qs.get('page', ['1'])[0])
            category = qs.get('category', ['0'])[0] or qs.get('type', ['0'])[0]
            order_by = qs.get('order_by', [''])[0] or qs.get('o', [''])[0]
            local_matches = manga_service.get_local_library(q, target_dir=('novels' if category == 'novel' else 'manga')) if page == 1 else []
            online_res = manga_service.search_jm_online(q, page, category=category, order_by=order_by)
            resp = {
                'local': local_matches,
                'online': online_res.get('results', []),
                'total_online': online_res.get('total', 0),
                'page': page,
                'page_count': online_res.get('page_count', 1),
                'has_more': online_res.get('has_more', False),
                'error': online_res.get('error')
            }
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/rankings'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rank_type = qs.get('type', ['week'])[0]
            page = int(qs.get('page', ['1'])[0] or 1)
            count = int(qs.get('count', ['80'])[0] or 80)
            items = manga_service.get_ranking_albums(rank_type=rank_type, page=page, count=count)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'rank_type': rank_type, 'page': page, 'results': items}, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/detail'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            aid = qs.get('id', [''])[0]
            try:
                detail = manga_service.get_jm_album_detail(aid)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(detail, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/tasks'):
            tasks = manga_service.get_all_tasks()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(tasks, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/recover_temp'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            target_dir = qs.get('dir', ['manga'])[0]
            res = manga_service.scan_and_recover_temp_manga(target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            return

        # --- MEGA API GET Routes ---
        if self.path.startswith('/api/mega/'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 MEGA 服务包含隐私账户信息，仅限在 Steam Deck 本机访问，局域网禁止访问'}).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/status'):
                res = mega_service.get_mega_status()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/files'):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                rpath = params.get('path', ['/'])[0]
                res = mega_service.list_mega_files(rpath)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/transfers'):
                res = mega_service.get_transfers()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/quota'):
                res = mega_service.get_quota_status(force_probe=True)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/trash'):
                res = mega_service.list_cloud_trash()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

        super().do_GET()

    def end_headers(self):
        """给每个响应统一加上禁用缓存的响应头，再交给父类真正写出响应头。"""
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        super().end_headers()

    def do_POST(self):
        """POST 请求总路由：跟 do_GET 同样的 `if self.path.startswith(...)` 依次匹配写法，
        覆盖下载中心任务提交、存档写入、隐私鉴权、局域网/广域网开关切换等所有写操作接口。
        """
        if self.path.startswith('/api/crawler/start'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            job_type = payload.get('type', '')
            params = payload.get('params', {}) or {}
            try:
                job_id = crawler_service.start_job(job_type, params)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'job_id': job_id}, ensure_ascii=False).encode('utf-8'))
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/logs/clear'):
            GLOBAL_LOG_BUFFER.clear()
            log_omni("INFO", "全局日志缓冲区已成功清空", tag="System")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            return

        if self.path.startswith('/api/save/'):
            parsed = urllib.parse.urlparse(self.path)
            game_id = urllib.parse.unquote(parsed.path.replace('/api/save/', ''))
            params = urllib.parse.parse_qs(parsed.query)
            filename = params.get('file', [''])[0]
            
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            if game_id in GAMES_REGISTRY and filename:
                save_dir = GAMES_REGISTRY[game_id]['save_dir']
                try:
                    os.makedirs(save_dir, exist_ok=True)
                    target_file = os.path.join(save_dir, filename)
                    with open(target_file, 'wb') as f:
                        f.write(post_data)
                except Exception as e:
                    sys.stderr.write(f"[ERROR] 存档写入失败 ({game_id}): {e}\n")

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        # --- NSFW Privacy Auth POST Routes ---
        if self.path.startswith('/api/auth/unlock'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            password = payload.get('password', '')
            remember = payload.get('remember', True)
            if privacy_service.verify_password(password):
                token = privacy_service.create_auth_token(days=7 if remember else 1)
                max_age = (7 * 86400) if remember else 86400
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Set-Cookie', f'omni_nsfw_token={token}; Path=/; Max-Age={max_age}; SameSite=Lax')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'token': token,
                    'unlocked': True
                }).encode('utf-8'))
            else:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': False,
                    'error': '密码错误，请重试'
                }, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/auth/lock'):
            token = privacy_service.extract_token_from_handler(self)
            if token:
                privacy_service.revoke_auth_token(token)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Set-Cookie', 'omni_nsfw_token=; Path=/; Max-Age=0; SameSite=Lax')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'unlocked': False}).encode('utf-8'))
            return

        if self.path.startswith('/api/auth/change_password'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            old_pwd = payload.get('old_password', '')
            new_pwd = payload.get('new_password', '')
            res = privacy_service.change_password(old_pwd, new_pwd)
            self.send_response(200 if res.get('success') else 400)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            return

        # 检查敏感专区 POST 操作权限
        if self.path.startswith(('/api/manga/', '/api/novels/', '/api/audio/', '/api/shortvideo/')):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"status": "error", "error": "NSFW content is locked"}')
                return

        # --- Manga API POST Routes ---
        if self.path.startswith('/api/manga/download'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            aid = payload.get('album_id')
            cids = payload.get('chapter_ids')
            pack = payload.get('pack_cbz', True)
            clean = payload.get('clean_temp', True)
            dest_dir = payload.get('dir', 'manga')
            task_id = manga_service.start_download_task(aid, cids, pack, clean, dest_dir=dest_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'task_id': task_id}).encode('utf-8'))
            return

        if self.path.startswith('/api/lan/toggle'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 局域网网络开关仅限在 Steam Deck 本机控制'}).encode('utf-8'))
                return

            global LAN_SHARING_ENABLED
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            if 'enabled' in payload:
                LAN_SHARING_ENABLED = bool(payload['enabled'])
            else:
                LAN_SHARING_ENABLED = not LAN_SHARING_ENABLED
            save_lan_sharing_enabled(LAN_SHARING_ENABLED)
            broadcast_network_status()
            ip = get_local_ip()
            resp = {
                'status': 'ok',
                'enabled': LAN_SHARING_ENABLED,
                'ip': ip,
                'port': PORT,
                'url': f'http://{ip}:{PORT}'
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        if self.path.startswith('/api/wan/toggle'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 广域网公网访问开关仅限在 Steam Deck 本机控制'}).encode('utf-8'))
                return

            global WAN_SHARING_ENABLED
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            if 'enabled' in payload:
                WAN_SHARING_ENABLED = bool(payload['enabled'])
            else:
                WAN_SHARING_ENABLED = not WAN_SHARING_ENABLED
            save_wan_sharing_enabled(WAN_SHARING_ENABLED)
            broadcast_network_status()

            resp = get_wan_status()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        if self.path.startswith('/api/sc2/play'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 独立游戏专区仅限在 Steam Deck 实体机屏幕上运行'}).encode('utf-8'))
                return
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            ok, msg = sc2_panel_service.start_match(
                payload.get('map', ''), payload.get('race', 'P'),
                payload.get('opponents', []), payload.get('mods', []))
            self.send_response(200 if ok else 409)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'error', 'message': msg}).encode('utf-8'))
            return

        if self.path.startswith('/api/sc2/open_editor'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 独立游戏专区仅限在 Steam Deck 实体机屏幕上运行'}).encode('utf-8'))
                return
            ok, msg = sc2_panel_service.open_editor()
            self.send_response(200 if ok else 409)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'error', 'message': msg}).encode('utf-8'))
            return

        if self.path.startswith('/api/games/launch'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 独立游戏专区仅限在 Steam Deck 实体机屏幕上运行，局域网禁止远程拉起'}).encode('utf-8'))
                return
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            gid = payload.get('id')
            title = payload.get('title', gid)
            ok, msg = launch_standalone_game_process(gid, title)
            self.send_response(200 if ok else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'error', 'message': msg}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/batch_download'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            album_ids = payload.get('album_ids', [])
            pack_cbz = payload.get('pack_cbz', True)
            clean_temp = payload.get('clean_temp', True)
            dest_dir = payload.get('dir', 'manga')
            concurrency = int(payload.get('concurrency', 3))
            task_id = manga_service.start_batch_download_task(album_ids, pack_cbz, clean_temp, dest_dir=dest_dir, concurrency=concurrency)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'task_id': task_id}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/stop_batch'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            task_id = payload.get('task_id')
            ok = manga_service.stop_batch_download_task(task_id)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'stopped': ok}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/queue'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            items = payload.get('items', [])
            target_dir = payload.get('dir', 'manga')
            manga_service.save_persistent_queue(items, target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        if self.path.startswith('/api/manga/clean_temp'):
            freed = manga_service.clean_all_temp_files()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'cleaned_count': freed}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/manual_pack'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            folder = payload.get('folder', '')
            tname = payload.get('target_name')
            dest_dir = payload.get('dir', 'manga')
            ok = manga_service.manual_pack_manga(folder, tname, dest_dir=dest_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'failed'}).encode('utf-8'))
            return

        if self.path.startswith('/api/manga/open_external'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            fname = payload.get('filename', '')
            target_dir = payload.get('dir', '')
            cbz_p = manga_service.resolve_file_path(fname, target_dir)
            if cbz_p and os.path.exists(cbz_p):
                subprocess.Popen(['xdg-open', cbz_p])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        if self.path.startswith('/api/manga/delete'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            fname = payload.get('filename', '')
            target_dir = payload.get('dir', '')
            ok = manga_service.trash_manga_file(fname, target_dir=target_dir)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'failed'}).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/download'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            novel_id = payload.get('id', '') or str(int(time.time()))
            title = payload.get('title', '未命名小说')
            author = payload.get('author', '佚名')
            intro = payload.get('intro', '')
            cover_url = payload.get('cover_url', '')
            is_nsfw = payload.get('is_nsfw', False) or payload.get('mode') == 'nsfw'
            res = novel_service.start_download_novel_task(novel_id, title, author, intro, cover_url, is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/queue/add'):
            content_length = int(self.headers.get('Content-Length', 0))
            item = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            if item.get('id'):
                novel_service.add_novel_to_queue(item)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/queue/remove'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            nid = payload.get('id', '')
            is_nsfw = payload.get('is_nsfw', None)
            if nid:
                novel_service.remove_novel_from_queue(nid, is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/queue/clear'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            is_nsfw = payload.get('is_nsfw', None)
            novel_service.clear_novel_queue(is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            return

        if self.path.startswith('/api/novels/trash') or self.path.startswith('/api/novels/delete'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            rel_path = payload.get('path', '') or payload.get('name', '') or payload.get('filename', '')
            ok = novel_service.trash_novel_file(rel_path)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'failed'}).encode('utf-8'))
            return

        if self.path.startswith('/api/audio/trash') or self.path.startswith('/api/audio/delete'):
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            fname = payload.get('filename', '') or payload.get('name', '') or payload.get('path', '')
            is_nsfw = bool(payload.get('is_nsfw', False))
            ok = audio_service.trash_audio_file(fname, is_nsfw=is_nsfw)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'failed'}).encode('utf-8'))
            return

        if self.path.startswith('/api/shortvideo/like'):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: short-video gallery is locked"}')
                return
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            platform = payload.get('platform') or 'kuaishou'
            rel_p = payload.get('path', '') or payload.get('rel_path', '')
            liked_val = payload.get('liked')
            res = shortvideo_service.toggle_shortvideo_like(platform, rel_p, liked_val)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'liked': res}).encode('utf-8'))
            return

        if self.path.startswith('/api/shortvideo/trash') or self.path.startswith('/api/shortvideo/delete'):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: short-video gallery is locked"}')
                return
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            platform = payload.get('platform') or 'kuaishou'
            rel_p = payload.get('path', '') or payload.get('rel_path', '')
            ok = shortvideo_service.trash_shortvideo_file(platform, rel_p)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok' if ok else 'failed'}).encode('utf-8'))
            return

        if self.path.startswith('/api/shortvideo/transcode_all'):
            if not self.check_nsfw_authorized():
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: short-video gallery is locked"}')
                return
            content_length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            shortvideo_service.transcode_all_now(payload.get('platform') or 'kuaishou')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        # --- MEGA API POST Routes ---
        if self.path.startswith('/api/mega/'):
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
            is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
            is_local = (client_ip in ('127.0.0.1', '::1', 'localhost', get_local_ip())) and not is_cf
            if not is_local:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'error': '🔒 MEGA 服务包含隐私账户信息，仅限在 Steam Deck 本机访问，局域网禁止访问'}).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/login'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                email = payload.get('email', '').strip()
                password = payload.get('password', '')
                auth_code = payload.get('auth_code')
                res = mega_service.mega_login(email, password, auth_code=auth_code)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/logout'):
                res = mega_service.mega_logout()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/reload'):
                try:
                    import importlib
                    importlib.reload(mega_service)
                except Exception as e:
                    print(f"[MEGA] reload module error: {e}")
                res = mega_service.mega_reload()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/download'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                src = payload.get('source', '').strip()
                loc = payload.get('location', 'downloads')
                res = mega_service.start_download(src, target_location=loc)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/cancel_transfer'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                tag = payload.get('tag', '')
                res = mega_service.cancel_transfer(str(tag))
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/pause_transfer'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                tag = payload.get('tag', '')
                res = mega_service.pause_transfer(str(tag))
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/resume_transfer'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                tag = payload.get('tag', '')
                res = mega_service.resume_transfer(str(tag))
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/trash'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                rpath = payload.get('path', '')
                res = mega_service.move_cloud_to_trash(rpath)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/restore_trash'):
                content_length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                rpath = payload.get('path', '')
                res = mega_service.restore_cloud_trash(rpath)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/mega/empty_trash'):
                res = mega_service.empty_cloud_trash()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

        # 没有路由认领这个 POST——SimpleHTTPRequestHandler 压根没有 do_POST，
        # 之前这里写的是 super().do_POST()，任何没匹配上的 POST 都会直接炸出
        # AttributeError（比如前端代码更新了、调了新接口，但服务器还没重启热更那批）。
        # 老老实实回一个 404，别让整条请求线程崩掉。
        self.send_response(404)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"error": "no such POST route"}')

    def do_DELETE(self):
        """DELETE 请求总路由：目前只有存档删除一条 `/api/save/<id>` 路径。"""
        if self.path.startswith('/api/save/'):
            parsed = urllib.parse.urlparse(self.path)
            game_id = urllib.parse.unquote(parsed.path.replace('/api/save/', ''))
            params = urllib.parse.parse_qs(parsed.query)
            filename = params.get('file', [''])[0]
            
            if game_id in GAMES_REGISTRY and filename:
                save_dir = GAMES_REGISTRY[game_id]['save_dir']
                try:
                    target_file = os.path.join(save_dir, filename)
                    if os.path.exists(target_file):
                        os.remove(target_file)
                except Exception as e:
                    sys.stderr.write(f"[ERROR] 存档删除失败 ({game_id}): {e}\n")

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        
        self.send_response(405)
        self.end_headers()
class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """静默多线程 HTTP 服务器，抑制客户端中途主动断开连接引起的 BrokenPipe 异常噪音"""
    daemon_threads = True        # 工作线程不阻塞进程退出
    allow_reuse_address = True   # 允许 TIME_WAIT 状态下立即重新绑定
    def handle_error(self, request, client_address):
        """覆盖父类的请求处理异常钩子：吞掉客户端中途断连的噪音异常，其余交给父类正常处理。

        Args:
            request: 出错的请求对象。
            client_address: 客户端地址。
        """
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)

scan_games()

def start_local_server():
    """在后台子线程中绑定并启动 0.0.0.0:8998 高性能多线程 HTTP 核心服务"""
    global HTTPD
    try:
        HTTPD = QuietThreadingHTTPServer(('0.0.0.0', PORT), MultiGameRequestHandler)
        HTTPD.daemon_threads = True
        _boot(f"HTTP server bound 0.0.0.0:{PORT}, serve_forever")
        HTTPD.serve_forever()
    except OSError as e:
        HTTPD = None
        _boot(f"HTTP server bind FAILED: {e}")
        log_omni("ERROR", f"本地核心服务无法绑定 0.0.0.0:{PORT}（可能已有实例或端口未释放）：{e}", tag="Core")


def _port_holder_pids(port):
    """返回正持有 <port> 的进程 PID（不含自己）。优先 psutil，回退 ss。"""
    pids = set()
    try:
        import psutil
        for c in psutil.net_connections(kind='inet'):
            if c.laddr and c.laddr.port == port and c.pid and c.pid != os.getpid():
                pids.add(c.pid)
        if pids:
            return pids
    except Exception:
        pass
    try:
        out = subprocess.run(
            ['ss', '-ltnpH', f'sport = :{port}'],
            capture_output=True, text=True, timeout=3
        ).stdout
        for m in re.finditer(r'pid=(\d+)', out):
            pid = int(m.group(1))
            if pid != os.getpid():
                pids.add(pid)
    except Exception:
        pass
    return pids


def _port_in_use(port) -> bool:
    """8998 上有没有人在 listen（不判断是不是我们的）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def ensure_single_instance():
    """单实例保护 —— 必须在绑定端口、加载 QtWebEngine 之前调用。
    游戏模式下第二次启动会让 gamescope 合成器死锁（两个 Chromium 内核抢 GPU/EGL），
    所以第二个实例必须**干净退出**。

    关键：这里**绝不去 kill 任何进程**。以前会在探测超时时把持有端口的进程当"僵尸"
    杀掉 —— 但那有可能是**正常在跑的第一个实例**（磁盘慢/GC 卡了一下就探测超时），
    在游戏模式里把前台 app 突然 SIGKILL 掉，正是把合成器搞死的原因之一。
    现在的策略：端口被占 = 有实例（不管健康与否）= 本次直接退出，让用户/内存看门狗
    去处理真卡住的那个。"""
    import http.client
    _boot("ensure_single_instance: probing /api/_alive …")
    try:
        conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=1.5)
        conn.request('GET', '/api/_alive')
        r = conn.getresponse()
        data = json.loads(r.read() or b'{}')
        conn.close()
        if isinstance(data, dict) and data.get('magic') == _INSTANCE_MAGIC:
            _boot(f"ensure_single_instance: healthy instance pid={data.get('pid')} → exit(0)")
            print(f"[!] Omni Deck 已在运行 (PID {data.get('pid')})，退出本次启动。")
            sys.exit(0)
        _boot(f"ensure_single_instance: /api/_alive answered but no magic: {data!r}")
    except SystemExit:
        raise
    except Exception as e:
        _boot(f"ensure_single_instance: probe failed ({type(e).__name__}: {e})")

    holders = _port_holder_pids(PORT)
    in_use = _port_in_use(PORT)
    _boot(f"ensure_single_instance: port {PORT} holders={sorted(holders)} in_use={in_use}")
    if holders or in_use:
        _boot("ensure_single_instance: port busy → assume an instance exists → exit(0) (NOT killing anything)")
        print(f"[!] 端口 {PORT} 已被占用（可能有实例卡住了）——本次不启动，避免游戏模式合成器死锁。"
              f" 如需强制：先结束 pid {sorted(holders) or '?'}。")
        sys.exit(0)
    _boot("ensure_single_instance: no other instance, proceeding to bind")


_boot("calling ensure_single_instance()")
ensure_single_instance()
_boot("starting local HTTP server thread")
threading.Thread(target=start_local_server, daemon=True).start()
_boot("ensure_wan_daemon()")
ensure_wan_daemon()
_boot("module-level init: importing PyQt6 next")

try:
    from PyQt6.QtCore import QUrl, Qt, QTimer, pyqtSignal
    from PyQt6.QtNetwork import QNetworkProxy
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QPushButton,
    )
    from PyQt6.QtGui import QKeySequence, QShortcut
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import (
        QWebEngineSettings,
        QWebEngineProfile,
        QWebEnginePage,
        QWebEngineScript,
    )
    from PyQt6.QtWebChannel import QWebChannel
    QT6 = True
except ImportError:
    from PyQt5.QtCore import QUrl, Qt, QTimer, pyqtSignal
    from PyQt5.QtNetwork import QNetworkProxy
    from PyQt5.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QPushButton,
        QShortcut,
    )
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWebEngineWidgets import (
        QWebEngineView,
        QWebEngineSettings,
        QWebEngineProfile,
        QWebEnginePage,
        QWebEngineScript,
    )
    from PyQt5.QtWebChannel import QWebChannel
    QT6 = False

class CustomWebPage(QWebEnginePage):
    """
    定制化 WebEnginePage：
    1. 自动授予麦克风、全屏等特性权限
    2. 控制台日志过滤并注入统一的 log_omni 系统
    3. 自定义 JavaScript Alert / Confirm / Prompt 交互适配
    4. 导航拦截：拦截 action://play- 内部伪协议，直通 launch_game 启动器
    """
    def __init__(self, profile, main_window, parent=None):
        """构造定制页面并接好特性权限自动授予的信号连接。

        Args:
            profile: QWebEngineProfile 实例。
            main_window: 承载这个页面的主窗口，用于取当前游戏 id 等上下文。
            parent: 父级 QObject，可选。
        """
        super().__init__(profile, parent)
        self.main_window = main_window
        self.featurePermissionRequested.connect(self.on_feature_permission_requested)

    def on_feature_permission_requested(self, securityOrigin, feature):
        """网页请求麦克风/全屏等浏览器特性权限时自动授予（单机游戏场景不需要用户逐次确认）。

        Args:
            securityOrigin: 请求权限的页面来源。
            feature: 请求的具体特性类型。
        """
        perm = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if QT6
            else QWebEnginePage.PermissionGrantedByUser
        )
        self.setFeaturePermission(securityOrigin, feature, perm)

    def createWindow(self, window_type):
        """网页弹窗或新标签一律直接在当前视口加载，绝不跳出外部独立浏览器"""
        return self

    def javaScriptConsoleMessage(self, level, msg, line, source):
        """网页 console.log/warn/error 的回调：过滤掉游戏引擎自带的日常噪音，其余转发进 log_omni。

        Args:
            level: 日志级别（QWebEnginePage 的 JavaScriptConsoleMessageLevel 枚举）。
            msg: 日志文本。
            line: 触发日志的源码行号。
            source: 触发日志的源文件/URL。
        """
        # 仅保留关键的 Omni-Deck / RPGWeb-Deck 框架启动信息或警告报错，彻底静音游戏自带的日常噪音 log
        info_level = (
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel
            if QT6
            else QWebEnginePage.InfoMessageLevel
        )
        if level == info_level:
            if not msg.startswith("[Omni-Deck]") and not msg.startswith("[RPGWeb-Deck]"):
                return

        ignored_patterns = [
            "passive event listener",
            "Synchronous XMLHttpRequest",
            "PixiJS",
            "DragonBones",
            "Deprecated",
            "鼠标右键",
            "anc is anc",
            "loadgame",
            "Greenworks failed",
            "video load error",
            "The play() request was interrupted",
            "AudioContext was not allowed to start",
            "batching_media_log",
            "FFmpegDemuxer",
            "pipeline_error",
            "Enlarging memory arrays",
            "enlarged memory arrays",
            "Wake Lock permission request denied",
            "Could not load previous settings",
            "Failed to load games: TypeError: Failed to fetch",
            "net::ERR_ABORTED"
        ]
        if any(ign in msg for ign in ignored_patterns):
            return

        src_name = os.path.basename(source) if source else "inline"
        if QT6:
            level_map = {
                QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "INFO",
                QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
                QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "ERROR",
            }
        else:
            level_map = {
                QWebEnginePage.InfoMessageLevel: "INFO",
                QWebEnginePage.WarningMessageLevel: "WARN",
                QWebEnginePage.ErrorMessageLevel: "ERROR",
            }
        level_str = level_map.get(level, "LOG")
        active_game = getattr(self.main_window, 'current_game_id', None) or "Hub"
        log_omni(level_str, f"{msg} (Line {line} in {src_name})", tag=active_game)

    def javaScriptAlert(self, securityOrigin, msg):
        """网页 window.alert() 的回调：不弹原生对话框（单机全屏体验），只记日志。

        Args:
            securityOrigin: 调用来源页面。
            msg: alert 文本内容。
        """
        try:
            active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
            log_omni("WARN", f"[JS-Alert] {msg}", tag=active_game)
        except Exception:
            pass

    def javaScriptConfirm(self, securityOrigin, msg):
        """网页 window.confirm() 的回调：默认一律当用户点了"确定"，特定已知误报文案除外。

        Args:
            securityOrigin: 调用来源页面。
            msg: confirm 提示文本。

        Returns:
            bool: 视为用户选择的结果，默认 True（确定）。
        """
        try:
            active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
            log_omni("WARN", f"[JS-Confirm] {msg}", tag=active_game)
            if "flash加载可能存在异常" in msg:
                return False
        except Exception:
            pass
        return True

    def javaScriptPrompt(self, securityOrigin, msg, defaultVal):
        """网页 window.prompt() 的回调：不弹原生输入框，直接回默认值当作用户输入。

        Args:
            securityOrigin: 调用来源页面。
            msg: 提示文本。
            defaultVal: 默认值。

        Returns:
            tuple[bool, str]: (是否"确定", 返回给网页的输入值)。
        """
        return (True, defaultVal)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        """页面导航拦截：回到大厅时重置窗口状态；拦截 `action://play-` 伪协议直通游戏启动器。

        Args:
            url: 目标导航 URL。
            nav_type: 导航触发类型。
            is_main_frame: 是否主 frame 导航。

        Returns:
            bool: 是否放行这次导航（父类默认实现的返回值，本方法末尾会调用父类处理）。
        """
        url_str = url.toString()
        if "hub.html" in url_str:
            self.main_window.is_in_game = False
            self.main_window.is_external_game = False
            self.main_window.current_game_id = None
            self.main_window.overlay.hide()
            self.main_window.btn_pure.hide()
            self.main_window.setWindowTitle("Omni Deck")

        if url_str.startswith("action://play-"):
            parsed = urllib.parse.urlparse(url_str)
            params = urllib.parse.parse_qs(parsed.query)
            game_id = params.get('id', [''])[0]
            title = params.get('title', ['Game'])[0]
            if game_id:
                self.main_window.launch_game(game_id, title)
            return False

        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

class RpgDeckMainWindow(QMainWindow):
    """
    Omni Deck 主应用程序窗口 (PyQt6 桌面客户端)：
    - 统一游戏大厅与媒体中心集成渲染
    - 悬浮胶囊控制台 (返回专区、全屏切换、声音静音、纯净模式)
    - 多引擎游戏动态路由 (RPG Maker 网页渲染、独立游戏子进程拉起、Retro 街机模拟器、SLG 引擎、Flash 殿堂双轨路由)
    - 进程与网络生命周期统一监控
    """
    renpy_finished = pyqtSignal()

    def __init__(self):
        """构造主窗口：初始化 WebEngine、UI、快捷键，加载大厅页面，并启动内存看门狗。"""
        super().__init__()

        self.setWindowTitle("Omni Deck")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.setStyleSheet("background-color: #000000;")

        proxy_type = (
            QNetworkProxy.ProxyType.NoProxy if QT6 else QNetworkProxy.NoProxy
        )
        QNetworkProxy.setApplicationProxy(QNetworkProxy(proxy_type))

        self.is_in_game = False
        self.is_muted = False
        self.current_game_id = None
        self.current_game_type = 'all'

        self.renpy_finished.connect(self.on_renpy_exit)
        _boot("RpgDeckMainWindow: setup_webengine() …")
        self.setup_webengine()
        _boot("RpgDeckMainWindow: setup_ui() …")
        self.setup_ui()
        _boot("RpgDeckMainWindow: setup_shortcuts() …")
        self.setup_shortcuts()

        _boot("RpgDeckMainWindow: load_hub() …")
        self.load_hub()
        self.setup_mem_guard()
        _boot("RpgDeckMainWindow: __init__ done")

    # ---------- 内存看门狗 ----------
    def setup_mem_guard(self):
        """两个定时器：① 每 5 分钟查总 RSS，超阈值干净自重启；② 每 2 小时清一次 HTTP 缓存。"""
        self._mem_timer = QTimer(self)
        self._mem_timer.timeout.connect(self._mem_watchdog_tick)
        self._mem_timer.start(5 * 60 * 1000)

        self._cache_timer = QTimer(self)
        self._cache_timer.timeout.connect(self._http_cache_flush)
        self._cache_timer.start(2 * 60 * 60 * 1000)

    def _total_rss_mb(self) -> float:
        """统计当前进程及其所有子进程的 RSS 内存总和。

        Returns:
            float: 总内存占用（MB）；psutil 不可用或出错时返回 0.0。
        """
        try:
            import psutil
            me = psutil.Process()
            procs = [me] + me.children(recursive=True)
            return sum(p.memory_info().rss for p in procs if p.is_running()) / (1024 * 1024)
        except Exception:
            return 0.0

    def _http_cache_flush(self):
        """HTTP 缓存清理定时器回调：目前是空实现占位（见方法内注释说明原因）。"""
        # 曾经在这里 clearHttpCache()，但 QtWebEngine 运行中调它会把 profile 的网络请求
        # 上下文搅乱，之后页面里所有 fetch() 全挂（"TypeError: Failed to fetch"，媒体专区
        # 整个加载不出来）。缓存靠 setHttpCacheMaximumSize(96MB) 的上限兜着就够了，
        # 不再运行时主动清。这个定时器留着当占位/以后别的用途。
        pass

    def _mem_watchdog_tick(self):
        """内存看门狗定时回调：总内存超阈值且当前不在游戏中时，干净地自我重启进程。"""
        rss = self._total_rss_mb()
        if rss <= 0 or rss < MEM_RESTART_MB:
            return
        if getattr(self, 'is_in_game', False):
            log_omni("WARN", f"内存 {rss:.0f}MB 超阈值，但正在游戏中，暂缓重启", tag="Mem")
            return
        # 有下载在跑就先不重启（execv 会打断；漫画队列/ MEGA 都能续传，但能等就等）
        try:
            if manga_service.is_active_downloading():
                log_omni("WARN", f"内存 {rss:.0f}MB 超阈值，但有下载在跑，暂缓重启", tag="Mem")
                return
        except Exception:
            pass
        log_omni("WARN", f"内存 {rss:.0f}MB > {MEM_RESTART_MB}MB，自重启 Omni Deck", tag="Mem")
        _boot(f"mem watchdog: RSS {rss:.0f}MB over {MEM_RESTART_MB}MB → self-restart via execv")
        try:
            kill_all_child_processes()
        except Exception:
            pass
        _release_http_server()
        _reap_descendants()
        script = os.path.join(SCRIPT_DIR, "main.py")
        try:
            os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
        except Exception as e:
            # execv 没成功 → 保持运行，下个 tick 再试（别把自己搞挂）
            log_omni("ERROR", f"自重启 execv 失败，继续运行：{e}", tag="Mem")

    def setup_webengine(self):
        """配置 QtWebEngine 专用 Profile、持久化存储与核心 Runtime Polyfill 脚本注入"""
        _boot("setup_webengine: QWebEngineProfile(...) …")
        self.profile = QWebEngineProfile("omni_deck_console_profile", self)
        _boot("setup_webengine: profile created")
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 QtWebEngine/1.0"
        )
        self.profile.setPersistentStoragePath(os.path.join(SCRIPT_DIR, "data", "storage"))
        cookie_policy = (
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            if QT6
            else QWebEngineProfile.ForcePersistentCookies
        )
        self.profile.setPersistentCookiesPolicy(cookie_policy)

        # HTTP 缓存默认不设上限——常年跑下来会一路涨。压到 96MB，并定期 clear（见
        # _mem_maintenance_tick）。注意：这只影响"浏览器缓存已抓过的网页资源"，跟漫画/
        # MEGA/小说的下载任务完全无关（那些在 Python 线程/子进程里跑），清缓存不会打断下载。
        try:
            disk = (QWebEngineProfile.HttpCacheType.DiskHttpCache if QT6
                    else QWebEngineProfile.DiskHttpCache)
            self.profile.setHttpCacheType(disk)
            self.profile.setHttpCacheMaximumSize(96 * 1024 * 1024)
        except Exception:
            pass

        _boot("setup_webengine: profile config done, settings…")
        p_settings = self.profile.settings()
        if QT6:
            Attr = QWebEngineSettings.WebAttribute
            for attr_name in [
                'JavascriptEnabled',
                'LocalStorageEnabled',
                'LocalContentCanAccessRemoteUrls',
                'LocalContentCanAccessFileUrls',
                'AllowRunningInsecureContent',
                'WebGLEnabled',
                'Accelerated2dCanvasEnabled',
            ]:
                if hasattr(Attr, attr_name):
                    p_settings.setAttribute(getattr(Attr, attr_name), True)
        else:
            p_settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
            p_settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
            p_settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
            p_settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            p_settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            p_settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
            p_settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            p_settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)

        # 核心 Polyfill: 精准单次 Hook、全模块 NW/Node 模拟、Spine 原生立绘引擎、首帧居中缩放自适应
        core_js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "core.js")
        with open(core_js_path, "r", encoding="utf-8") as f:
            core_runtime_js = f.read()

        script = QWebEngineScript()
        script.setName("rpg_deck_runtime")
        script.setSourceCode(core_runtime_js)
        injection_point = (
            QWebEngineScript.InjectionPoint.DocumentCreation
            if QT6
            else QWebEngineScript.DocumentCreation
        )
        world_id = (
            QWebEngineScript.ScriptWorldId.MainWorld
            if QT6
            else QWebEngineScript.MainWorld
        )
        script.setInjectionPoint(injection_point)
        script.setWorldId(world_id)
        self.profile.scripts().insert(script)

    def setup_ui(self):
        """初始化主窗口组件、WebEngineView 视口、全局快捷键以及右上角悬浮控制胶囊"""
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        _boot("setup_ui: QWebEngineView(self) …  ← Chromium 在这里起，游戏模式卡死常卡这一步")
        self.webview = QWebEngineView(self)
        _boot("setup_ui: QWebEngineView created")
        self.page = CustomWebPage(self.profile, self, parent=self.webview)
        self.webview.setPage(self.page)

        settings = self.webview.settings()
        if QT6:
            Attr = QWebEngineSettings.WebAttribute
            for attr_name in [
                'JavascriptEnabled',
                'LocalStorageEnabled',
                'LocalContentCanAccessRemoteUrls',
                'LocalContentCanAccessFileUrls',
                'AllowRunningInsecureContent',
                'WebGLEnabled',
                'Accelerated2dCanvasEnabled',
            ]:
                if hasattr(Attr, attr_name):
                    settings.setAttribute(getattr(Attr, attr_name), True)
        else:
            settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
            settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
            settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)

        self.layout.addWidget(self.webview)

        # 快捷键支持：F5 / Ctrl+R 快速刷新页面
        QShortcut(QKeySequence("F5"), self, self.webview.reload)
        QShortcut(QKeySequence("Ctrl+R"), self, self.webview.reload)

        # 悬浮控制胶囊
        self.overlay = QWidget(self)
        self.overlay_layout = QHBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(6, 4, 6, 4)
        self.overlay_layout.setSpacing(6)

        self.btn_back_category = QPushButton("⬅ 返回专区", self.overlay)
        self.btn_back_category.clicked.connect(self.load_category)

        self.btn_pure = QPushButton("🎮 纯净全屏", self.overlay)
        self.btn_pure.clicked.connect(self.toggle_roco_pure_mode)
        self.btn_pure.hide()

        self.btn_fullscreen = QPushButton("⛶ 全屏", self.overlay)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_mute = QPushButton("🔊 声音", self.overlay)
        self.btn_mute.clicked.connect(self.toggle_mute)

        for btn in [self.btn_back_category, self.btn_pure, self.btn_fullscreen, self.btn_mute]:
            self.overlay_layout.addWidget(btn)

        self.webview.loadFinished.connect(self.on_load_finished)

        self.overlay.setStyleSheet("""
            QWidget {
                background: rgba(15, 20, 28, 0.88);
                border: 1px solid rgba(88, 166, 255, 0.35);
                border-radius: 8px;
            }
            QPushButton {
                background: rgba(30, 38, 50, 0.9);
                color: #e6edf3;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1f6feb;
                color: #ffffff;
            }
        """)
        self.overlay.hide()

        # ---- 本机原生播放通道：QtWebEngine 内置解码器阉割了 H.264/AAC，这里旁路一份
        # QtMultimedia（完整 ffmpeg，同一个窗口里播放，不开新窗口）——见 native_player.py
        # 顶部注释。局域网/远程设备走的还是 main.py 现有的 HTTP 流接口，不受影响。
        from native_player import NativePlayerWidget, PlayerBridge

        self.native_player = NativePlayerWidget(self)
        self.native_player.hide()
        self.native_player.closed.connect(self.hide_native_player)
        # 上一条/下一条/删除：原生播放器自己不维护列表，转发回网页，网页算出下一条该放
        # 哪个文件之后，会再通过 bridge 重新喊一次 Python 播放（见 hub.js 里的
        # nativePlayerPrev/Next/Delete）。
        self.native_player.prevRequested.connect(
            lambda: self.webview.page().runJavaScript("window.nativePlayerPrev && window.nativePlayerPrev()"))
        self.native_player.nextRequested.connect(
            lambda: self.webview.page().runJavaScript("window.nativePlayerNext && window.nativePlayerNext()"))
        self.native_player.deleteRequested.connect(
            lambda: self.webview.page().runJavaScript("window.nativePlayerDelete && window.nativePlayerDelete()"))
        self.native_player.likeToggled.connect(
            lambda liked: self.webview.page().runJavaScript(f"window.nativePlayerToggleLike && window.nativePlayerToggleLike({json.dumps(liked)})"))

        self.player_bridge = PlayerBridge(self)
        self.web_channel = QWebChannel(self.webview.page())
        self.web_channel.registerObject('bridge', self.player_bridge)
        self.webview.page().setWebChannel(self.web_channel)

        # qwebchannel.js 是 Qt 自带资源（不是磁盘上的散文件），读出来跟"网页那边怎么连上
        # 这个 bridge"的胶水代码拼一块，当成页面脚本注入——跟上面 core_runtime_js 是同一个
        #机制。网页那边（hub.js）判断 window.omniBridge 存在与否，来决定走原生播放还是
        # 走 HTTP 流，天然只在本机这个嵌入视图里生效。
        try:
            from PyQt6.QtCore import QFile, QIODevice
        except ImportError:
            from PyQt5.QtCore import QFile, QIODevice
        qwc_file = QFile(":/qtwebchannel/qwebchannel.js")
        if qwc_file.open(QIODevice.OpenModeFlag.ReadOnly if QT6 else QIODevice.ReadOnly):
            qwebchannel_js = bytes(qwc_file.readAll()).decode("utf-8")
            qwc_file.close()
            glue_js = qwebchannel_js + """
            (function() {
                if (typeof qt === 'undefined' || !qt.webChannelTransport) return;
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    window.omniBridge = channel.objects.bridge;
                    window.dispatchEvent(new Event('omniBridgeReady'));
                });
            })();
            """
            bridge_script = QWebEngineScript()
            bridge_script.setName("omni_deck_bridge")
            bridge_script.setSourceCode(glue_js)
            bridge_script.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation if QT6 else QWebEngineScript.DocumentCreation)
            bridge_script.setWorldId(
                QWebEngineScript.ScriptWorldId.MainWorld if QT6 else QWebEngineScript.MainWorld)
            self.profile.scripts().insert(bridge_script)
        else:
            log_omni("WARN", "qwebchannel.js 资源读取失败，本机原生播放桥接不可用（会自动退回网页内置播放器）", tag="NativePlayer")

    def show_native_player(self, full_path: str, is_audio: bool, title: str = "", chapters=None, is_liked: bool = False):
        """显示原生播放器并播放指定文件；同模式下切歌不重新摆窗口，避免闪一下露出网页。

        Args:
            full_path: 本地文件绝对路径。
            is_audio: True 为音频模式（底部细条），False 为视频模式（铺满窗口）。
            title: 展示标题。
            chapters: 章节列表，可选。
            is_liked: 当前条目是否已点赞。
        """
        # 视频：铺满整个窗口（专注观看，跟原来的网页视频弹窗一个体验）。
        # 音频：只占底部一条细长的控制条，不挡住上面的网页——有声书本来就是"边听边逛"，
        # 不该被一个全屏播放器把浏览这件事挡掉。
        #
        # 切上一条/下一条时（同一个模式下、播放器本来就已经开着）不要重新 setGeometry/
        # show/raise_——这几个调用会让底下那个原生视频解码表面被迫重新贴一次窗口，
        # 相当于"关一下窗口再开一下"，只是快到看着像一次切换，但中间那一下依旧会露出
        # 底下的网页。已经开着、模式没变的情况下，只管换源播放，窗口本身完全不动。
        already_showing_same_mode = (
            self.native_player.isVisible() and self.native_player.is_audio_mode == is_audio
        )
        self.native_player.play_local(full_path, is_audio, title, chapters=chapters, is_liked=is_liked)
        if not already_showing_same_mode:
            self._layout_native_player()
            self.native_player.show()
            self.native_player.raise_()

    def _layout_native_player(self):
        """按当前模式（音频/视频）重新计算并设置原生播放器控件的位置与大小。"""
        if not hasattr(self, 'native_player'):
            return
        if getattr(self.native_player, 'is_audio_mode', False):
            bar_h = max(64, self.native_player.controls.sizeHint().height())
            self.native_player.setGeometry(0, self.height() - bar_h, self.width(), bar_h)
        else:
            self.native_player.setGeometry(0, 0, self.width(), self.height())

    def hide_native_player(self):
        """停止播放并隐藏原生播放器，恢复显示底下的网页。"""
        self.native_player.stop_and_hide()
        self.native_player.hide()

    def on_load_finished(self, ok):
        """网页加载完毕后，若处于游戏状态则自动计算并显示右上角控制胶囊。
        外部游戏（web_flash 独立窗口 / Proton 独立进程）不算 —— 大厅这套胶囊按钮
        作用的是大厅 webview，对外部窗口没意义，显示出来只会让人以为大厅还在游戏里。"""
        if not getattr(self, '_first_load_logged', False):
            self._first_load_logged = True
            _boot(f"on_load_finished: first page loaded ok={ok}  ← 启动全程走完，界面已出")
        if getattr(self, 'is_in_game', False) and not getattr(self, 'is_external_game', False):
            self.overlay.adjustSize()
            self.overlay.move(self.width() - self.overlay.width() - 16, 16)
            self.overlay.show()
            self.overlay.raise_()

    def toggle_roco_pure_mode(self):
        """洛克王国等网页游戏专用纯净模式：注入 JS 消除周边广告与边框，使 Flash 居中铺满视口"""
        toggle_js = """
        (function() {
            var styleId = 'roco-pure-mode-style';
            var backdropId = 'roco-pure-backdrop';
            var existingStyle = document.getElementById(styleId);
            
            if (existingStyle) {
                existingStyle.remove();
                var backdrop = document.getElementById(backdropId);
                if (backdrop) backdrop.remove();
                return false;
            } else {
                var style = document.createElement('style');
                style.id = styleId;
                style.textContent = `
                    #roco-pure-backdrop {
                        position: fixed !important;
                        top: 0 !important;
                        left: 0 !important;
                        width: 100vw !important;
                        height: 100vh !important;
                        background: #080a0f !important;
                        z-index: 999990 !important;
                        pointer-events: none !important;
                    }
                    .float, .tips, .clearfix, .footer, .news-content, .btn-mgame,
                    .qqLink, .falshLink, #share-py, #qqLink, #falshLink, #header, #footer,
                    .lt-up-ang, .rt-up-ang, .lt-dn-ang, .rt-dn-ang, .head, .header,
                    #ad, .ad, .bottom, .bot {
                        display: none !important;
                    }
                    #swf, embed[name='swf'], object[name='swf'], #flashcontent {
                        position: fixed !important;
                        top: 50% !important;
                        left: 50% !important;
                        transform: translate(-50%, -50%) !important;
                        width: 960px !important;
                        height: 560px !important;
                        z-index: 999999 !important;
                        box-shadow: 0 0 60px rgba(0,0,0,0.95) !important;
                        display: block !important;
                        visibility: visible !important;
                        margin: 0 !important;
                        padding: 0 !important;
                    }
                    html, body {
                        overflow: hidden !important;
                    }
                `;
                (document.head || document.documentElement).appendChild(style);
                
                if (!document.getElementById(backdropId)) {
                    var backdrop = document.createElement('div');
                    backdrop.id = backdropId;
                    (document.body || document.documentElement).appendChild(backdrop);
                }
                return true;
            }
        })();
        """
        self.webview.page().runJavaScript(toggle_js)

    def setup_shortcuts(self):
        """注册 F11 全屏与 Escape 退出快捷键"""
        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, self.handle_escape)

    def handle_escape(self):
        """Escape 键处理：全屏状态下退出全屏，游戏运行状态下返回专区大厅"""
        if self.isFullScreen():
            self.showNormal()
        elif self.is_in_game:
            self.load_category()

    def resizeEvent(self, event):
        """窗口尺寸变动时自适应悬浮控制胶囊在右上角的位置；原生播放器铺满全窗口，跟着一起变"""
        super().resizeEvent(event)
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)
        if hasattr(self, 'native_player') and self.native_player.isVisible():
            self._layout_native_player()

    def load_hub(self):
        """加载 Omni Deck 首页大厅 (hub.html) 并重置游戏状态"""
        prev_game = getattr(self, 'current_game_id', None)
        if prev_game:
            sys.stderr.write("\n" + "=" * 70 + "\n")
            log_omni("INFO", f"⬅ 退出游戏 [{prev_game}]，返回大厅", tag="Lifecycle")
            sys.stderr.write("=" * 70 + "\n")
        self.is_in_game = False
        self.is_external_game = False
        self.current_game_id = None
        self.overlay.hide()
        self.btn_pure.hide()
        self.setWindowTitle("Omni Deck")
        self.webview.stop()
        self.webview.load(QUrl(f"http://127.0.0.1:{PORT}/hub.html"))
        self.webview.setFocus()

    def load_category(self):
        """退出当前正在游玩的游戏，返回其对应的专区分类列表 (hub.html?category=<cat>)"""
        cat = getattr(self, 'current_game_type', 'rpg')
        cat_map = {
            'renpy': 'standalone',
            'steam': 'standalone',
            'unity': 'standalone',
            'windows': 'standalone',
            'app': 'standalone'
        }
        prev_game = getattr(self, 'current_game_id', None)
        if prev_game and prev_game in GAMES_REGISTRY:
            gtype = GAMES_REGISTRY[prev_game].get('type')
            if gtype:
                cat = gtype
        cat = cat_map.get(cat, cat)
        if prev_game:
            sys.stderr.write("\n" + "=" * 70 + "\n")
            log_omni("INFO", f"⬅ 退出游戏 [{prev_game}]，返回 [{cat}] 专区", tag="Lifecycle")
            sys.stderr.write("=" * 70 + "\n")
        self.is_in_game = False
        self.is_external_game = False
        self.current_game_id = None
        self.overlay.hide()
        self.btn_pure.hide()
        self.setWindowTitle("Omni Deck")
        self.webview.stop()
        self.webview.load(QUrl(f"http://127.0.0.1:{PORT}/hub.html?category={cat}"))
        self.webview.setFocus()

    def launch_game(self, game_id: str, title: str):
        """
        核心游戏启动总线：
        根据游戏类型执行精准分流路由：
        - standalone / renpy -> 独立子进程 (Proton/Wine/Native)
        - retro -> EmulatorJS WASM 模拟器 (player_retro.html)
        - slg -> Web / Ren'Py
        - flash (web_flash) -> PyQt5 隔离新窗口 (flash_runner.py)
        - flash (swf) -> 内置 Ruffle WASM 模拟器 (player_flash.html)
        - rpg -> 本地 HTTP 代理加载 index.html 并挂载 core.js 运行环境
        """
        if game_id not in GAMES_REGISTRY:
            # 1. 尝试 URL 解码与大小写不敏感匹配
            unq_id = urllib.parse.unquote(game_id).strip()
            matched_id = next((gid for gid in GAMES_REGISTRY if gid.lower() == unq_id.lower()), None)
            if matched_id:
                game_id = matched_id
            else:
                # 2. 尝试重新扫描游戏目录（热发现刚下载/转换的新游戏）
                scan_games(force=True)
                if game_id not in GAMES_REGISTRY:
                    matched_id = next((gid for gid in GAMES_REGISTRY if gid.lower() == unq_id.lower()), None)
                    if matched_id:
                        game_id = matched_id
                    else:
                        log_omni("ERROR", f"未找到游戏注册信息: {game_id}", tag="Launcher")
                        return

        game_data = GAMES_REGISTRY[game_id]
        self.current_game_type = game_data.get('type', 'rpg')
        self.current_game_id = game_id

        sys.stderr.write("\n" + "=" * 70 + "\n")
        log_omni("INFO", f"🎮 启动游戏: [{game_id}] (Type: {self.current_game_type})", tag="Lifecycle")
        sys.stderr.write("=" * 70 + "\n")
        if game_data.get('type') in ['standalone', 'renpy']:
            self.launch_standalone_game(game_id, title)
            return

        if game_data.get('type') == 'retro':
            self.is_in_game = True
            self.current_game_id = game_id
            self.setWindowTitle(f"{title} — Omni Deck")
            system_core = game_data.get('system', 'gba')
            rom_file = game_data.get('rom_file', '')
            target_url = QUrl(f"http://127.0.0.1:{PORT}/player_retro.html?id={urllib.parse.quote(game_id)}&system={system_core}&rom={urllib.parse.quote(rom_file)}")
            self.webview.load(target_url)
            self.webview.setFocus()
            self.btn_pure.hide()
            self.overlay.adjustSize()
            self.overlay.move(self.width() - self.overlay.width() - 16, 16)
            self.overlay.show()
            self.overlay.raise_()
            return

        if game_data.get('type') == 'slg':
            if game_data.get('slg_engine') == 'renpy':
                self.launch_renpy_game(game_id, title)
                return
            self.is_in_game = True
            self.current_game_id = game_id
            self.setWindowTitle(f"{title} — Omni Deck")
            entry = game_data.get('entry_html', 'index.html')
            target_url = QUrl(f"http://127.0.0.1:{PORT}/game/{urllib.parse.quote(game_id)}/{entry}?engine=renpy&type=slg")
            self.webview.load(target_url)
            self.webview.setFocus()
            self.btn_pure.hide()
            self.overlay.adjustSize()
            self.overlay.move(self.width() - self.overlay.width() - 16, 16)
            self.overlay.show()
            self.overlay.raise_()
            return

        if game_data.get('type') == 'flash':
            self.is_in_game = True
            self.current_game_id = game_id
            self.setWindowTitle(f"{title} — Omni Deck")

            if game_data.get('engine') == 'web_flash':
                # web_flash 跑在独立的 flash_runner 窗口里，大厅 webview 仍是首页 ——
                # 别让大厅顶上的悬浮胶囊冒出来
                self.is_external_game = True
                self.overlay.hide()
                self.btn_pure.hide()
                # flash_runner 全屏起；大厅这边收起来，给合成器一个干净的前台切换
                self.showMinimized()
                game_data_json = json.dumps(game_data)
                flash_python = os.path.join(SCRIPT_DIR, ".venv_flash", "bin", "python")
                if not os.path.exists(flash_python):
                    flash_python = sys.executable
                cmd = [flash_python, os.path.join(SCRIPT_DIR, "flash_runner.py"), game_data_json]
                
                clean_env = os.environ.copy()
                for k in list(clean_env.keys()):
                    if k.startswith('QT_') or k.startswith('QML_'):
                        del clean_env[k]
                clean_env['QT_QPA_PLATFORM'] = 'xcb'
                
                def runner():
                    """在后台线程里拉起 flash_runner.py 隔离子进程并等待其退出。"""
                    log_file = open(os.path.join(CACHE_DIR, "flash_crash.log"), "w")
                    rc = None
                    try:
                        proc = subprocess.Popen(
                            cmd,
                            env=clean_env,
                            preexec_fn=set_pdeathsig,
                            start_new_session=True,
                            stdout=log_file,
                            stderr=subprocess.STDOUT
                        )
                        rc = proc.wait()
                    except Exception as e:
                        log_file.write(f"\\nPython Error: {str(e)}\\n")
                    finally:
                        log_file.close()
                    # flash_runner 退出（正常关闭 或 崩溃）→ 通知 GUI 线程收尾：
                    # 复位 is_in_game、藏掉悬浮胶囊、把大厅拉回前台
                    log_omni("INFO" if rc == 0 else "WARN",
                             f"Flash 窗口已退出 (rc={rc})", tag="Lifecycle")
                    try:
                        self.renpy_finished.emit()
                    except Exception:
                        pass

                threading.Thread(target=runner, daemon=True).start()
                return
            else:
                self.is_external_game = False   # swf 走内置 Ruffle，在大厅 webview 里，胶囊要留着
                self.btn_pure.hide()
                swf_file = game_data.get('swf_file', '')
                target_url = QUrl(f"http://127.0.0.1:{PORT}/player_flash.html?id={urllib.parse.quote(game_id)}&file={urllib.parse.quote(swf_file)}")
                self.webview.load(target_url)
                
                self.webview.setFocus()
                self.overlay.adjustSize()
                self.overlay.move(self.width() - self.overlay.width() - 16, 16)
                self.overlay.show()
                self.overlay.raise_()
                return

        # RPG Maker 网页渲染流程
        self.is_in_game = True
        self.current_game_id = game_id
        self.setWindowTitle(f"{title} — Omni Deck")
        
        target_url = QUrl(f"http://127.0.0.1:{PORT}/game/{urllib.parse.quote(game_id)}/index.html")
        self.webview.load(target_url)
        self.webview.setFocus()
        
        self.overlay.adjustSize()
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)
        self.overlay.show()
        self.overlay.raise_()

    def launch_standalone_game(self, game_id: str, title: str):
        """调用全局独立进程拉起器运行大型 PC 游戏，退出时自动回调激活大厅"""
        self.showMinimized()
        launch_standalone_game_process(game_id, title, on_exit_callback=lambda: self.renpy_finished.emit())

    def launch_renpy_game(self, game_id: str, title: str):
        """拉起原生桌面版 Ren'Py 视觉小说游戏"""
        self.launch_standalone_game(game_id, title)

    def on_renpy_exit(self):
        """独立游戏 / 外部进程退出回调：重新激活并置顶 Omni Deck 窗口，保持大厅当前视口"""
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized if QT6
                            else self.windowState() & ~Qt.WindowMinimized)
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        # 合成器有时要慢半拍才把焦点交回来，延迟再顶一次
        QTimer.singleShot(400, lambda: (self.raise_(), self.activateWindow()))
        # ⚠️ 不要在这里 clearHttpCache() —— 运行中调它会搞坏渲染进程的网络栈，之后页面
        # 所有 fetch() 全失败（媒体专区加载不出来）。缓存有 96MB 上限兜着。
        # 仅当处于内置 Webview 游戏运行时才触发 load_category()。
        # 对于 Wine/Proton/Linux 外部独立游戏，Webview 在游戏运行期间始终停留在大厅页面，无需也不应重新加载，避免破坏用户的滚动位置、过滤条件与标签页状态！
        if getattr(self, 'is_in_game', False):
            self.load_category()
        else:
            try:
                self.webview.page().runJavaScript("if (typeof updateFavBadges === 'function') updateFavBadges();")
            except Exception:
                pass

    def toggle_fullscreen(self):
        """切换主窗口操作系统级全屏 / 窗口化状态 (支持 F11 快捷键)"""
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("⛶ 全屏")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("🗗 窗口")

    def toggle_mute(self):
        """切换主浏览器视口的游戏全局音频静音状态"""
        self.is_muted = not self.is_muted
        self.webview.page().setAudioMuted(self.is_muted)
        self.btn_mute.setText("🔇 静音" if self.is_muted else "🔊 声音")

    def closeEvent(self, event):
        """主窗口关闭拦截：彻底递归清理所有拉起的游戏与后台守护子进程。

        点窗口右上角叉叉，本来指望 Qt「最后一个窗口关掉就自动退出」这套机制去触发
        app.aboutToQuit → graceful_shutdown。但 native_player.py 里的 QVideoWidget
        （QtMultimedia 视频渲染）在某些图形后端下会额外占一个隐藏的原生渲染表面，Qt
        清点"还有没有顶层窗口开着"时可能把它也算进去——主窗口表面上关掉了，Qt却觉得
        还有一个窗口没关，于是不触发自动退出，进程悄悄留在后台不退出（Steam 因此认为
        游戏还在跑，得手动去 Steam 里点停止才能再次启动）。不再依赖那套自动判断，这里
        直接强制调用同一套关闭流程（清子进程、放端口、os._exit 硬退出），不管 Qt 怎么
        清点窗口数量，点叉叉一定真正退出进程。"""
        try:
            if hasattr(self, 'native_player'):
                self.native_player.stop_and_hide()
        except Exception:
            pass
        graceful_shutdown()

def main():
    """Omni Deck 应用程序全局启动主入口"""
    _boot("main(): entered")
    # 游戏模式下 Steam 用 SIGTERM 结束应用，既不触发 Qt closeEvent 也不跑 atexit。
    # 显式挂 SIGTERM/SIGINT → graceful_shutdown（清子进程、释放 8998、收 Chromium 后代、硬退出）。
    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(_sig, graceful_shutdown)
        except Exception:
            pass

    _boot("main(): QApplication(sys.argv) …")
    app = QApplication(sys.argv)
    _boot("main(): QApplication created")
    app.aboutToQuit.connect(graceful_shutdown)

    # Qt 的 C++ 事件循环会压住 Python 信号处理，用一个空转定时器把控制权定期交回解释器。
    _sig_timer = QTimer()
    _sig_timer.start(300)
    _sig_timer.timeout.connect(lambda: None)

    _boot("main(): RpgDeckMainWindow() …")
    window = RpgDeckMainWindow()
    _boot("main(): window created, show()")
    window.show()
    _boot("main(): entering app.exec()  ← 如果 boot.log 停在这行，说明进了事件循环、Qt/合成器层面卡住")
    sys.exit(getattr(app, 'exec', getattr(app, 'exec_', None))())

if __name__ == "__main__":
    main()
