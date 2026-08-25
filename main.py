import os
import sys
import platform
import threading
import subprocess
import json
import functools
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

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
FLASH_GAMES_DIR = os.path.join(SCRIPT_DIR, "flash_games")
PLUGINS_DIR = os.path.join(FLASH_GAMES_DIR, "plugins")
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
RPG_GAMES_DIR = os.path.join(SCRIPT_DIR, "rpg_games")
RENPY_GAMES_DIR = os.path.join(SCRIPT_DIR, "renpy_games")
RETRO_GAMES_DIR = os.path.join(SCRIPT_DIR, "retro_games")
SLG_GAMES_DIR = os.path.join(SCRIPT_DIR, "slg_games")
EMULATORJS_DIR = os.path.join(SCRIPT_DIR, "emulatorjs")
GAMES_DIR = RPG_GAMES_DIR
RENPY_SDK_PATH = "/home/deck/Applications/renpy-8.5.3-sdk/renpy.sh"
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
    "001 - Mom's Best Friend": "001 - Mom's Best Friend",
    '002 - After the Fire': '002 - After the Fire',
    '003 - Love Strikes Thrice': '003 - Love Strikes Thrice',
    '004 - Obsessed Lucy': '004 - Obsessed Lucy',
    '005 - Cradle': '005 - Cradle',
    '006 - Hokages Adopted Son': "006 - Hokage's Adopted Son",
    '001 - Cowgirl Maid Milk Cafe': '001 - Cowgirl Maid Milk Cafe',
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

def register_renpy_folder(folder_path, custom_id=None):
    if not os.path.isdir(folder_path):
        return

    game_sub = os.path.join(folder_path, 'game')
    if os.path.isdir(game_sub):
        base_name = os.path.basename(folder_path.rstrip('/'))
        game_id = custom_id or base_name
        name = DISPLAY_NAMES.get(game_id, DISPLAY_NAMES.get(base_name, base_name))
        
        icon_candidates = [
            os.path.join(game_sub, 'gui', 'window_icon.png'),
            os.path.join(game_sub, 'icon.png'),
            os.path.join(folder_path, 'icon.png')
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), None)

        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'type': 'renpy',
            'root': folder_path,
            'save_dir': os.path.join(game_sub, 'saves'),
            'icon': icon_path,
        }

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
    system_core = 'gba'
    # Check by priority
    dir_files = os.listdir(folder_path)
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

    # 2. 扫描 Ren'Py 视觉小说目录 (renpy_games/)
    if os.path.exists(RENPY_GAMES_DIR):
        for item in sorted(os.listdir(RENPY_GAMES_DIR)):
            sub = os.path.join(RENPY_GAMES_DIR, item)
            register_renpy_folder(sub, custom_id=item)

    # 3. 扫描 街机与复古卡带目录 (retro_games/)
    if os.path.exists(RETRO_GAMES_DIR):
        for item in sorted(os.listdir(RETRO_GAMES_DIR)):
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

def resolve_case_insensitive_path(base_dir, rel_path):
    """URL 解码 + 忽略大小写智能查找 (彻底解决 URL 空格 %20 与 大小写 404)"""
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
                for entry in os.listdir(current):
                    entry_lower = entry.lower()
                    if entry_lower == part_lower or entry_lower == part_no_asar:
                        current = os.path.join(current, entry)
                        found = True
                        break
            if not found:
                return os.path.join(current, part)
    return current

class MultiGameRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # 彻底静音所有正常 2xx / 3xx 与空探测 404 日志
        try:
            req = str(args[0]) if len(args) >= 1 else ""
            code = str(args[1]) if len(args) >= 2 else ""
            if code.startswith(('2', '3')):
                return
            if code == '404' and ('HEAD /save/' in req or '.rpgsave' in req or 'favicon.ico' in req):
                return
            sys.stderr.write(f"[WARNING] HTTP {code} on {req}\n")
        except Exception:
            pass

    def log_error(self, format, *args):
        try:
            msg = format % args
            if "favicon.ico" in self.path or "fav.ico" in self.path or "code 404" in msg:
                return
            sys.stderr.write(f"[ERROR] {msg} for path {self.path}\n")
        except Exception:
            pass

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def translate_path(self, path):
        clean_path = path.split('?')[0].split('#')[0]
        unquoted = urllib.parse.unquote(clean_path)

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
            game_id = unquoted[len('/retro_rom/'):]
            if game_id in GAMES_REGISTRY:
                gdata = GAMES_REGISTRY[game_id]
                return os.path.join(gdata['root'], gdata['rom_file'])

        if unquoted.startswith('/game/'):
            parts = unquoted.split('/')
            if len(parts) >= 3:
                game_id = parts[2]
                if game_id in GAMES_REGISTRY:
                    rel_path = '/'.join(parts[3:])
                    return resolve_case_insensitive_path(GAMES_REGISTRY[game_id]['root'], rel_path)

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
                req_path = urllib.parse.unquote(qs['path'][0]).lstrip('/')
                target_path = req_path
                
                if 'game_id' in qs and qs['game_id'][0] in GAMES_REGISTRY:
                    game_dir = GAMES_REGISTRY[qs['game_id'][0]]['root']
                    target_path = os.path.join(game_dir, req_path)
                
                # Manual case-insensitive resolution for absolute paths
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

                if os.path.isdir(target_path):
                    files = os.listdir(target_path)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(files).encode('utf-8'))
                    return
            self.send_response(404)
            self.end_headers()
            return
        if self.path.startswith('/api/patch/'):
            game_id = urllib.parse.unquote(self.path.split('/')[3].split('?')[0])
            if game_id.endswith('.js'): game_id = game_id[:-3]
            patch_path = os.path.join(GAMES_DIR, game_id, "adapter.js")
            if os.path.exists(patch_path):
                self.send_response(200)
                self.send_header('Content-type', 'application/javascript')
                self.end_headers()
                with open(patch_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith('/api/games'):
            scan_games()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
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

class CustomWebPage(QWebEnginePage):
    def __init__(self, profile, main_window, parent=None):
        super().__init__(profile, parent)
        self.main_window = main_window
        self.featurePermissionRequested.connect(self.on_feature_permission_requested)

    def on_feature_permission_requested(self, securityOrigin, feature):
        self.setFeaturePermission(
            securityOrigin, feature, QWebEnginePage.PermissionGrantedByUser
        )

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
        # 仅保留关键的 RPGWeb-Deck 框架启动信息或严重报错，彻底静音游戏自带的日常 console.log
        if level == QWebEnginePage.InfoMessageLevel:
            if not msg.startswith("[RPGWeb-Deck]"):
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
        level_map = {
            QWebEnginePage.InfoMessageLevel: "INFO",
            QWebEnginePage.WarningMessageLevel: "WARN",
            QWebEnginePage.ErrorMessageLevel: "ERROR"
        }
        level_str = level_map.get(level, "LOG")
        sys.stderr.write(f"[JS-{level_str}] {msg} (Line {line} in {src_name})\n")

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        url_str = url.toString()
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

        self.setWindowTitle("Omni Deck 全能游戏中心")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.setStyleSheet("background-color: #000000;")

        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))

        self.is_in_game = False
        self.is_muted = False
        self.current_game_id = None

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
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)

        p_settings = self.profile.settings()
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
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
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
        self.overlay = QWidget(self.central_widget)
        self.overlay_layout = QHBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(6, 4, 6, 4)
        self.overlay_layout.setSpacing(6)

        self.btn_home = QPushButton("🏠 大厅", self.overlay)
        self.btn_home.clicked.connect(self.load_hub)

        self.btn_pure = QPushButton("🎮 纯净全屏", self.overlay)
        self.btn_pure.clicked.connect(self.toggle_roco_pure_mode)
        self.btn_pure.hide()

        self.btn_fullscreen = QPushButton("⛶ 全屏", self.overlay)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_mute = QPushButton("🔊 声音", self.overlay)
        self.btn_mute.clicked.connect(self.toggle_mute)

        for btn in [self.btn_home, self.btn_pure, self.btn_fullscreen, self.btn_mute]:
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
            self.load_hub()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)

    def load_hub(self):
        self.is_in_game = False
        self.current_game_id = None
        self.overlay.hide()
        self.btn_pure.hide()
        self.setWindowTitle("Omni Deck 全能游戏中心")
        self.webview.load(QUrl(f"http://127.0.0.1:{PORT}/hub.html"))
        self.webview.setFocus()

    def launch_game(self, game_id: str, title: str):
        if game_id not in GAMES_REGISTRY:
            return

        game_data = GAMES_REGISTRY[game_id]
        if game_data.get('type') == 'renpy':
            self.launch_renpy_game(game_id, title)
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

    def launch_renpy_game(self, game_id: str, title: str):
        game_data = GAMES_REGISTRY[game_id]
        root = game_data['root']

        # 智能启动决策: 优先使用系统配置的现代全局 Ren'Py SDK (支持 64位 OpenGL 硬件加速与手柄原生映射)
        cmd = None
        if os.path.exists(RENPY_SDK_PATH):
            cmd = [RENPY_SDK_PATH, root]
        else:
            sh_files = [f for f in os.listdir(root) if f.endswith('.sh') and f != 'renpy.sh']
            if sh_files:
                target_sh = os.path.join(root, sh_files[0])
                try: os.chmod(target_sh, 0o755)
                except: pass
                cmd = [target_sh]

        if not cmd:
            sys.stderr.write(f"[ERROR] 未找到可用的 Ren'Py 运行时 ({game_id})\n")
            return

        # 启动 Ren'Py 原生进程，大厅最小化让出前台，游戏退出后自动恢复
        self.showMinimized()

        def runner():
            try:
                proc = subprocess.Popen(cmd, cwd=root)
                proc.wait()
            except Exception as e:
                sys.stderr.write(f"[ERROR] Ren'Py 运行异常 ({game_id}): {e}\n")
            finally:
                self.renpy_finished.emit()

        threading.Thread(target=runner, daemon=True).start()

    def on_renpy_exit(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.load_hub()

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

def main():
    app = QApplication(sys.argv)
    window = RpgDeckMainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
