import os
import sys
import shutil
import platform
import threading
import subprocess
import json
import functools
import urllib.parse
import atexit
import signal
import ctypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

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

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--enable-features=WebAssemblyThreads,SharedArrayBuffer "
    "--enable-webgl "
    "--ignore-gpu-blocklist "
    "--enable-gpu-rasterization"
)

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
GAMES_DIR = RPG_GAMES_DIR
HUB_HTML_PATH = os.path.join(ASSETS_DIR, "hub.html")
PLAYER_RETRO_HTML = os.path.join(ASSETS_DIR, "player_retro.html")
PLAYER_FLASH_HTML = os.path.join(ASSETS_DIR, "player_flash.html")
PORT = 8998

FLASH_PLUGIN_PATH = os.path.join(PLUGINS_DIR, "libpepflashplayer.so") if sys.platform != "win32" else os.path.join(PLUGINS_DIR, "pepflashplayer64.dll")

DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
CHROMIUM_CACHE = os.path.join(CACHE_DIR, "engine_cache")

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CHROMIUM_CACHE, exist_ok=True)

# 2. Chromium C++ 原生极速网络与硬件加速参数（强化 AMD GPU 稳定性）
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
sys.argv.append(f"--ppapi-flash-path={FLASH_PLUGIN_PATH}")
sys.argv.append("--ppapi-flash-version=32.0.0.465")
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
    '085 - Elf Girl Rifia': '085 - Elf Girl Rifia',
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
    "001 - Mom's Best Friend": "001 - Mom's Best Friend",
    '002 - After the Fire': '002 - After the Fire',
    '003 - Love Strikes Thrice': '003 - Love Strikes Thrice',
    '004 - Obsessed Lucy': '004 - Obsessed Lucy',
    '005 - Cradle Beyond the Veil': '005 - Cradle: Beyond the Veil',
    '006 - Hokages Adopted Son': "006 - Hokage's Adopted Son",
    '007 - sMother': '007 - sMother',
    '008 - Succu-Mama': '008 - SUCCU-MAMA',
    '009 - Bright Lord': '009 - Bright Lord (光明领主)',
    '001 - Cowgirl Maid Milk Cafe': '001 - Cowgirl Maid Milk Cafe',
    '002 - Summer Sisters': '002 - Summer Sisters',

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
                if fl.endswith('.sh'): candidates.append((100 - depth * 10, full_p))
                elif fl.endswith('.py') and fl != 'game.py': candidates.append((80 - depth * 10, full_p))
                elif fl.endswith('.exe'): candidates.append((50 - depth * 10, full_p))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

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

            if any(bad in fl for bad in ['crashhandler', 'crashpad', 'reipatcher', 'setup', 'uninstall', 'ueprereqsetup', 'config', 'エンジン設定', 'vcredist', 'dxredist', 'redist', 'directx', 'elevate']):
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
            if fl in ['oxygennotincluded', 'dontstarve', 'dontstarve_steam_x64.exe', 'dspgame.exe', 'deadcells.exe', 'factorio.exe', 'davethediver.exe', 'descenders.exe', 'rimworldwin64.exe', 'vampiresurvivors.exe', 'thronefall.exe', 'sandustry.exe']:
                score += 100

            candidates.append((score, full_p))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def register_standalone_folder(folder_path, subcategory, custom_id=None):
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
    if not os.path.isdir(folder_path):
        return
    game_id = custom_id or os.path.basename(folder_path)
    name = DISPLAY_NAMES.get(game_id, game_id)
    
    # 检查是否为 Ren'Py 架构的 3D/策略 SLG
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

    # WebGL / HTML5 / RPG Maker 架构的 SLG
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

    save_dir = os.path.join(folder_path, 'save')
    os.makedirs(save_dir, exist_ok=True)
    
    icon_candidates = [
        os.path.join(folder_path, 'icon.png'),
        os.path.join(folder_path, 'icon.jpg'),
        os.path.join(folder_path, 'cover.png'),
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

def register_flash_folder(folder_path, custom_id=None):
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

def scan_games():
    GAMES_REGISTRY.clear()
    
    # 1. 扫描 RPG Maker 游戏目录 (rpg_games/ 或 games/)
    rpg_dir = RPG_GAMES_DIR if os.path.exists(RPG_GAMES_DIR) else os.path.join(SCRIPT_DIR, "games")
    if os.path.exists(rpg_dir):
        for item in sorted(os.listdir(rpg_dir)):
            sub = os.path.join(rpg_dir, item)
            register_rpg_folder(sub, custom_id=item)

    # 2. 扫描 独立游戏专区 (Steam 精选, Ren'Py, Unity, Godot, Unreal, Wine, Windows 软件应用)
    standalone_categories = ['steam', 'renpy', 'unity', 'godot', 'unreal', 'wine', 'app']
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
            if item in ['omni-deck', 'StarCraft II', 'Battle.net', 'rpg_games', 'standalone_games']: continue
            sub = os.path.join(GAMES_BASE_DIR, item)
            if os.path.isdir(sub):
                register_standalone_folder(sub, subcategory='app', custom_id=item)

    # 注册 星际争霸 2 离线内核 (直接调用 Support64/SC2Switcher_x64.exe 绕过战网)
    sc2_switcher = os.path.join(SC2_DIR, "Support64", "SC2Switcher_x64.exe")
    if os.path.exists(sc2_switcher):
        register_standalone_folder(SC2_DIR, subcategory='app', custom_id='StarCraft II')
        if 'StarCraft II' in GAMES_REGISTRY:
            GAMES_REGISTRY['StarCraft II']['exe_path'] = sc2_switcher

    if 'Weiyun' not in GAMES_REGISTRY and os.path.exists(WEIYUN_STEAM_PATH):
        register_standalone_folder(WEIYUN_STEAM_PATH, subcategory='app', custom_id='Weiyun')

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

def log_omni(level: str, msg: str, tag: str = None):
    """
    统一的 Omni-Deck 项目分级日志系统:
    - 带有 [Omni-Deck] 项目全局标签
    - 支持可选的子标签 [tag]（如具体的游戏ID、组件名）
    - 明确的日志等级 [INFO] / [WARN] / [ERROR] / [DEBUG]
    - 带终端 ANSI 颜色区分，清晰易读
    """
    prefix = "[Omni-Deck]"
    if tag:
        prefix += f"[{tag}]"
    prefix += f"[{level}]"

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

    sys.stderr.write(f"{color_code}{prefix} {msg}{reset_code}\n")
    sys.stderr.flush()

def extract_game_id_from_path(path: str) -> str:
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

class MultiGameRequestHandler(SimpleHTTPRequestHandler):
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

        if unquoted in ['/player_retro.html']:
            return PLAYER_RETRO_HTML

        if unquoted in ['/player_flash.html']:
            return PLAYER_FLASH_HTML

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

        if self.path.startswith('/api/games'):
            scan_games()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            games_list = list(GAMES_REGISTRY.values())
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
                req_file = subparts[1] if len(subparts) > 1 else gdata.get('swf_file', '')
                target_file = os.path.join(gdata['root'], req_file)
                if not os.path.exists(target_file):
                    target_file = os.path.join(gdata['root'], gdata.get('swf_file', ''))
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
            self.send_response(404)
            self.end_headers()
            return

        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        super().end_headers()

    def do_POST(self):
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
    def handle_error(self, request, client_address):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)

scan_games()

def start_local_server():
    try:
        httpd = QuietThreadingHTTPServer(('127.0.0.1', PORT), MultiGameRequestHandler)
        httpd.serve_forever()
    except OSError:
        pass

threading.Thread(target=start_local_server, daemon=True).start()

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
    QT6 = False

class CustomWebPage(QWebEnginePage):
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
        """网页弹窗或 target='_blank' 链接时，自动在主视口中加载"""
        proxy_page = QWebEnginePage(self.profile(), self)

        def handle_new_url(target_url):
            url_str = target_url.toString()
            if url_str and url_str != "about:blank":
                self.main_window.webview.load(target_url)
                proxy_page.deleteLater()

        proxy_page.urlChanged.connect(handle_new_url)
        return proxy_page

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
            "Could not load previous settings"
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
        active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
        log_omni("WARN", f"[JS-Alert] {msg}", tag=active_game)

    def javaScriptConfirm(self, securityOrigin, msg):
        active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
        log_omni("WARN", f"[JS-Confirm] {msg}", tag=active_game)
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
        self.profile = QWebEngineProfile("omni_deck_console_profile", self)
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
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

        # 悬浮控制胶囊
        self.overlay = QWidget(self.webview)
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

    def toggle_roco_pure_mode(self):
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
        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, self.handle_escape)

    def handle_escape(self):
        if self.isFullScreen():
            self.showNormal()
        elif self.is_in_game:
            self.load_category()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)

    def load_hub(self):
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
        cat = getattr(self, 'current_game_type', 'rpg')
        prev_game = getattr(self, 'current_game_id', None)
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
        if game_id not in GAMES_REGISTRY:
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
            target_url = QUrl(f"http://127.0.0.1:{PORT}/game/{urllib.parse.quote(game_id)}/{entry}")
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
                target_url = QUrl(game_data.get('url'))
                self.webview.load(target_url)
                is_roco = "17roco" in game_data.get('url', '')
                self.btn_pure.setVisible(is_roco)
            else:
                self.btn_pure.hide()
                swf_path = os.path.join(game_data['root'], game_data['swf_file'])
                swf_file_url = QUrl(f"file://{swf_path}")
                hint = game_data.get('hint', '')
                html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        html, body {{
            margin: 0; padding: 0; width: 100%; height: 100%;
            background-color: #080a0f; overflow: hidden;
            display: flex; flex-direction: column; justify-content: center; align-items: center;
        }}
        embed, object {{
            width: 100%; height: 100%; max-width: 1060px; max-height: 700px; outline: none;
            border-radius: 4px; box-shadow: 0 0 40px rgba(0,0,0,0.8);
        }}
        #hint-bar {{
            position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
            background: rgba(22, 27, 34, 0.85); backdrop-filter: blur(8px);
            border: 1px solid rgba(48, 54, 61, 0.6); border-radius: 20px;
            padding: 6px 16px; color: #58a6ff; font-size: 13px; font-weight: 500;
            display: flex; align-items: center; gap: 8px; z-index: 100;
            pointer-events: none; transition: opacity 0.5s;
        }}
    </style>
</head>
<body>
    <embed src="file://{swf_path}" type="application/x-shockwave-flash" quality="high" wmode="direct" allowscriptaccess="always">
    {f'<div id="hint-bar">{hint}</div>' if hint else ''}
    <script>
        setTimeout(function() {{
            var hb = document.getElementById('hint-bar');
            if (hb) hb.style.opacity = '0';
        }}, 8000);
    </script>
</body>
</html>"""
                self.webview.setHtml(html, swf_file_url)

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
        # 防止同一游戏重复启动（单实例保护）
        if game_id in RUNNING_GAME_IDS:
            log_omni("WARN", f"游戏 [{title}] 已经在运行中，忽略重复启动请求", tag="Launcher")
            return

        game_data = GAMES_REGISTRY.get(game_id)
        if not game_data:
            return
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
            return

        # 确保工作目录准确指向实际可执行文件所在的子目录 (解决内嵌子目录游戏找不到资源与 Pak 文件的严重问题)
        # 星际争霸 2 必须以游戏根目录作为工作目录，否则无法正确定位根目录的 Maps 与 Mods
        if game_id and game_id.startswith('StarCraft II'):
            run_cwd = root
        else:
            run_cwd = os.path.dirname(exe_path) if (exe_path and os.path.exists(exe_path)) else root

        # 注入多语言环境 (修复 RPG Maker VX Ace / 吉里吉里 / 经典日文与中文单机游戏乱码与崩溃)
        run_env['LANG'] = 'zh_CN.UTF-8'
        run_env['LC_ALL'] = 'zh_CN.UTF-8'
        run_env['WINEDEBUG'] = '-all'

        RUNNING_GAME_IDS.add(game_id)

        def runner():
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=run_cwd,
                    env=run_env,
                    preexec_fn=set_pdeathsig,
                    start_new_session=True
                )
                ACTIVE_CHILD_PROCESSES.append(proc)
                proc.wait()
            except Exception as e:
                log_omni("ERROR", f"独立游戏运行异常 ({game_id}): {e}", tag="Launcher")
            finally:
                if 'proc' in locals() and proc in ACTIVE_CHILD_PROCESSES:
                    ACTIVE_CHILD_PROCESSES.remove(proc)
                RUNNING_GAME_IDS.discard(game_id)
                self.renpy_finished.emit()

        threading.Thread(target=runner, daemon=True).start()

    def on_renpy_exit(self):
        self.raise_()
        self.activateWindow()
        self.load_category()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("⛶ 全屏")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("🗗 窗口")

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        self.webview.page().setAudioMuted(self.is_muted)
        self.btn_mute.setText("🔇 静音" if self.is_muted else "🔊 声音")

    def closeEvent(self, event):
        kill_all_child_processes()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    window = RpgDeckMainWindow()
    window.show()
    sys.exit(getattr(app, 'exec', getattr(app, 'exec_', None))())

if __name__ == "__main__":
    main()
