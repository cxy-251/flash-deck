import os
import sys
import shutil
import platform
import threading
import subprocess
import json
import re
import socket
import struct
import time
import functools
import urllib.parse
import atexit
import signal
import ctypes
import mimetypes
import datetime
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/x-shockwave-flash', '.swf')
mimetypes.add_type('audio/mp4', '.m4b')
mimetypes.add_type('audio/mp4', '.m4a')
import manga_service
import novel_service
import audio_service
import mega_service
import sc2_panel_service
import privacy_service

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--enable-features=WebAssemblyThreads,SharedArrayBuffer "
    "--enable-webgl "
    "--ignore-gpu-blocklist "
    "--enable-gpu-rasterization"
)

ACTIVE_CHILD_PROCESSES = []
RUNNING_GAME_IDS = set()  # 当前正在运行的游戏 ID 集合，防止重复启动同一游戏

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

atexit.register(kill_all_child_processes)

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

LAN_CONFIG_FILE = os.path.join(SCRIPT_DIR, ".lan_config.json")

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

WAN_CONFIG_FILE = os.path.join(SCRIPT_DIR, ".wan_config.json")
WAN_DOMAIN = "omni.cxy251.uk"
WAN_URL = f"https://{WAN_DOMAIN}"

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
    global WAN_TUNNEL_PROC
    if not is_cloudflared_ready():
        return
    config_file = os.path.expanduser("~/.cloudflared/config.yml")
    if not os.path.exists(config_file):
        return

    start_local_dns_helper()

    def daemon_worker():
        global WAN_TUNNEL_PROC
        while True:
            try:
                cmd = [
                    CLOUDFLARED_BIN,
                    "--config", config_file,
                    "tunnel", "run"
                ]
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
            os.path.join(game_sub, 'gui', 'window_icon.png'),
            os.path.join(game_sub, 'icon.png'),
            os.path.join(folder_path, 'icon.png'),
            os.path.join(folder_path, 'cover.png'),
            os.path.join(folder_path, 'cover.jpg')
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)
        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'slg',
            'slg_engine': 'renpy',
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

def _get_monitored_paths():
    paths = [
        RPG_GAMES_DIR,
        os.path.join(SCRIPT_DIR, "games"),
        RETRO_GAMES_DIR,
        SLG_GAMES_DIR,
        FLASH_GAMES_DIR,
        GAMES_BASE_DIR,
    ]
    standalone_categories = ['steam', 'renpy', 'unity', 'godot', 'unreal', 'wine', '3ds', 'app']
    for cat in standalone_categories:
        paths.extend([
            os.path.join(SD_CARD_ROOT, "standalone_games", f"{cat}_games"),
            os.path.join(SD_CARD_ROOT, f"{cat}_games"),
            os.path.join(SCRIPT_DIR, "standalone_games", f"{cat}_games"),
            os.path.join(SCRIPT_DIR, f"{cat}_games"),
            os.path.join(GAMES_BASE_DIR, "standalone_games", f"{cat}_games"),
            os.path.join(GAMES_BASE_DIR, f"{cat}_games"),
        ])
    return paths

def _get_filesystem_signature():
    sig = {}
    for p in _get_monitored_paths():
        try:
            st = os.stat(p)
            sig[p] = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig[p] = None
    return sig

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
    
    # 1. 扫描 RPG Maker 游戏目录 (rpg_games/ 或 games/)
    rpg_dir = RPG_GAMES_DIR if os.path.exists(RPG_GAMES_DIR) else os.path.join(SCRIPT_DIR, "games")
    if os.path.exists(rpg_dir):
        for item in sorted(os.listdir(rpg_dir)):
            sub = os.path.join(rpg_dir, item)
            register_rpg_folder(sub, custom_id=item)

    # 2. 扫描 独立游戏专区 (Steam 精选, Ren'Py, Unity, Godot, Unreal, Wine, 3DS 模拟器, Windows 软件应用)
    standalone_categories = ['steam', 'renpy', 'unity', 'godot', 'unreal', 'wine', '3ds', 'app']
    for cat in standalone_categories:
        scan_paths = [
            os.path.join(SD_CARD_ROOT, "standalone_games", f"{cat}_games"),
            os.path.join(SD_CARD_ROOT, f"{cat}_games"),
            os.path.join(SCRIPT_DIR, "standalone_games", f"{cat}_games"),
            os.path.join(SCRIPT_DIR, f"{cat}_games"),
            os.path.join(GAMES_BASE_DIR, "standalone_games", f"{cat}_games"),
            os.path.join(GAMES_BASE_DIR, f"{cat}_games")
        ]
        for sp in scan_paths:
            if os.path.isdir(sp):
                for item in sorted(os.listdir(sp)):
                    if item.startswith("."): continue
                    sub = os.path.join(sp, item)
                    register_standalone_folder(sub, subcategory=cat, custom_id=item)

    # 扫描 Windows 软件与独立应用 (支持 GAMES_BASE_DIR 或 Steam 原装容器路径)
    if os.path.exists(GAMES_BASE_DIR):
        for item in sorted(os.listdir(GAMES_BASE_DIR)):
            if item in ['omni-deck', 'StarCraft II', 'Battle.net', 'claude', 'rpg_games', 'standalone_games']: continue
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

    # 3. 扫描 街机与复古卡带目录 (retro_games/)
    if os.path.exists(RETRO_GAMES_DIR):
        for item in sorted(os.listdir(RETRO_GAMES_DIR)):
            if item in ["emulatorjs", "plugins"] or item.startswith("."):
                continue
            sub = os.path.join(RETRO_GAMES_DIR, item)
            register_retro_folder(sub, custom_id=item)

    # 4. 扫描 SLG 模拟策略与养成互动目录 (slg_games/)
    if os.path.exists(SLG_GAMES_DIR):
        for item in sorted(os.listdir(SLG_GAMES_DIR)):
            sub = os.path.join(SLG_GAMES_DIR, item)
            register_slg_folder(sub, custom_id=item)

    # 5. 扫描 Flash 殿堂级神作目录 (flash_games/)
    if os.path.exists(FLASH_GAMES_DIR):
        for item in sorted(os.listdir(FLASH_GAMES_DIR)):
            if item == "plugins" or item.startswith("."):
                continue
            sub = os.path.join(FLASH_GAMES_DIR, item)
            register_flash_folder(sub, custom_id=item)

scan_games()

REVERSE_LOCALE_CACHE = {}

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
                        fp = os.path.join(root, f)
                        try:
                            with open(fp, 'r', encoding='utf-8') as jf:
                                data = json.load(jf)
                                if isinstance(data, dict):
                                    for k, v in data.items():
                                        if isinstance(v, str) and isinstance(k, str) and len(v) < 100:
                                            rev[v.strip().lower()] = k.strip()
                        except:
                            pass
        except:
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
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, "omni_deck.log")

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
        if os.path.exists(RENPY_SDK_PATH):
            cmd = [RENPY_SDK_PATH, root]
        elif exe_path and os.path.exists(exe_path):
            if exe_path.endswith('.sh') or exe_path.endswith('.py'):
                try: os.chmod(exe_path, 0o755)
                except: pass
                cmd = [exe_path]
            elif exe_path.endswith('.exe'):
                cmd, run_env = get_wine_or_proton_runner(exe_path, game_id=game_id)
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
        # 彻底静音所有正常 2xx / 3xx 与游戏常规探测 HEAD / 404 日志
        try:
            req = str(args[0]) if len(args) >= 1 else ""
            code = str(args[1]) if len(args) >= 2 else ""
            if code.startswith(('2', '3')):
                return
            if code == '404' and ('HEAD ' in req or '/save/' in req or '.rpgsave' in req or 'favicon.ico' in req or '/api/patch/' in req):
                return
            tag = extract_game_id_from_path(req) or "Server"
            if code.startswith('5'):
                log_omni("ERROR", f"HTTP {code} on {req}", tag=tag)
            else:
                log_omni("WARN", f"HTTP {code} on {req}", tag=tag)
        except Exception:
            pass

    def parse_request(self):
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
        client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else '127.0.0.1'
        local_ip = get_local_ip()
        is_cf = bool(self.headers.get('CF-Connecting-IP') or self.headers.get('cf-ray'))
        return (client_ip in ('127.0.0.1', 'localhost', '::1', local_ip)) and not is_cf

    def check_nsfw_authorized(self) -> bool:
        is_local = self.check_is_local()
        return privacy_service.is_request_authorized(self, is_local)

    def log_error(self, format, *args):
        try:
            msg = format % args
            if "favicon.ico" in self.path or "fav.ico" in self.path or "code 404" in msg:
                return
            tag = extract_game_id_from_path(self.path) or "Server"
            log_omni("ERROR", f"{msg} (path: {self.path})", tag=tag)
        except Exception:
            pass

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def translate_path(self, path):
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
                                except:
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
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        super().end_headers()

    def do_POST(self):
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
        if self.path.startswith(('/api/manga/', '/api/novels/', '/api/audio/')):
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

        super().do_POST()

    def do_DELETE(self):
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
    def handle_error(self, request, client_address):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)

scan_games()

def start_local_server():
    """在后台子线程中绑定并启动 0.0.0.0:8998 高性能多线程 HTTP 核心服务"""
    try:
        httpd = QuietThreadingHTTPServer(('0.0.0.0', PORT), MultiGameRequestHandler)
        httpd.serve_forever()
    except OSError:
        pass

threading.Thread(target=start_local_server, daemon=True).start()
ensure_wan_daemon()

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
    from PyQt6.QtGui import QKeySequence, QShortcut, QDesktopServices
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import (
        QWebEngineSettings,
        QWebEngineProfile,
        QWebEnginePage,
        QWebEngineScript,
    )
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
    from PyQt5.QtGui import QKeySequence, QDesktopServices
    from PyQt5.QtWebEngineWidgets import (
        QWebEngineView,
        QWebEngineSettings,
        QWebEngineProfile,
        QWebEnginePage,
        QWebEngineScript,
    )
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
        super().__init__(profile, parent)
        self.main_window = main_window
        self.featurePermissionRequested.connect(self.on_feature_permission_requested)

    def on_feature_permission_requested(self, securityOrigin, feature):
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
        try:
            active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
            log_omni("WARN", f"[JS-Alert] {msg}", tag=active_game)
        except Exception:
            pass

    def javaScriptConfirm(self, securityOrigin, msg):
        try:
            active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
            log_omni("WARN", f"[JS-Confirm] {msg}", tag=active_game)
            if "flash加载可能存在异常" in msg:
                return False
        except Exception:
            pass
        return True

    def javaScriptPrompt(self, securityOrigin, msg, defaultVal):
        return (True, defaultVal)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        url_str = url.toString()
        if "hub.html" in url_str:
            self.main_window.is_in_game = False
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
        self.setup_webengine()
        self.setup_ui()
        self.setup_shortcuts()

        self.load_hub()

    def setup_webengine(self):
        """配置 QtWebEngine 专用 Profile、持久化存储与核心 Runtime Polyfill 脚本注入"""
        self.profile = QWebEngineProfile("omni_deck_console_profile", self)
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
        core_js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core.js")
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

        self.webview = QWebEngineView(self)
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

    def on_load_finished(self, ok):
        """网页加载完毕后，若处于游戏状态则自动计算并显示右上角控制胶囊"""
        if getattr(self, 'is_in_game', False):
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
        """窗口尺寸变动时自适应悬浮控制胶囊在右上角的位置"""
        super().resizeEvent(event)
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)

    def load_hub(self):
        """加载 Omni Deck 首页大厅 (hub.html) 并重置游戏状态"""
        prev_game = getattr(self, 'current_game_id', None)
        if prev_game:
            sys.stderr.write("\n" + "=" * 70 + "\n")
            log_omni("INFO", f"⬅ 退出游戏 [{prev_game}]，返回大厅", tag="Lifecycle")
            sys.stderr.write("=" * 70 + "\n")
        self.is_in_game = False
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
                    log_file = open(os.path.join(SCRIPT_DIR, "flash_crash.log"), "w")
                    try:
                        proc = subprocess.Popen(
                            cmd, 
                            env=clean_env, 
                            preexec_fn=set_pdeathsig,
                            start_new_session=True,
                            stdout=log_file, 
                            stderr=subprocess.STDOUT
                        )
                        proc.wait()
                    except Exception as e:
                        log_file.write(f"\\nPython Error: {str(e)}\\n")
                    finally:
                        log_file.close()
                
                threading.Thread(target=runner, daemon=True).start()
                return
            else:
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
        launch_standalone_game_process(game_id, title, on_exit_callback=lambda: self.renpy_finished.emit())

    def on_renpy_exit(self):
        """独立游戏 / 外部进程退出回调：重新激活并置顶 Omni Deck 窗口，保持大厅当前视口"""
        self.show()
        self.raise_()
        self.activateWindow()
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
        """主窗口关闭拦截：彻底递归清理所有拉起的游戏与后台守护子进程"""
        kill_all_child_processes()
        super().closeEvent(event)

def main():
    """Omni Deck 应用程序全局启动主入口"""
    app = QApplication(sys.argv)
    window = RpgDeckMainWindow()
    window.show()
    sys.exit(getattr(app, 'exec', getattr(app, 'exec_', None))())

if __name__ == "__main__":
    main()
