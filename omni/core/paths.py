"""
Omni Deck 所有「程序自身」路径的唯一来源。

路径分三类，互不混放：
  • REPO 下的程序文件：代码、前端、内置第三方运行时（vendor/），随 git 分发；
  • STATE 下的本机状态：配置、用户数据、缓存、日志，全部 gitignore，可整体拷走迁移；
  • 资源库（游戏/媒体）：不在这里——由 omni.core.library 按库清单 + 目录骨架表给出。

其它模块只允许从这里（程序/状态路径）和 omni.core.library（资源路径）拿路径，不要自己
os.path.join(SCRIPT_DIR, ...) 或 expanduser(...)；tests/test_path_guard.py 会检查这一点。
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.expanduser("~")

# ---- 程序文件（随代码分发）
WEB = os.path.join(REPO, "web")
VENDOR = os.path.join(REPO, "vendor")
EMULATORJS = os.path.join(VENDOR, "emulatorjs")
RUFFLE = os.path.join(VENDOR, "ruffle")
PEPFLASH = os.path.join(VENDOR, "pepflash")
CLOUDFLARED_BIN = os.path.join(VENDOR, "cloudflared", "cloudflared")
CATALOGS = os.path.join(REPO, "omni", "features", "novels", "catalogs")
CRAWLERS = os.path.join(REPO, "tools", "crawlers")
VENV_PYTHON = os.path.join(REPO, ".venv", "bin", "python")
FLASH_VENV_PYTHON = os.path.join(REPO, ".venv_flash", "bin", "python")

# ---- 本机状态（gitignore；OMNI_STATE_DIR 可整体改位置）
STATE = os.environ.get("OMNI_STATE_DIR") or os.path.join(REPO, "var")
CONFIG = os.path.join(STATE, "config")
DATA = os.path.join(STATE, "data")
CACHE = os.path.join(STATE, "cache")
LOGS = os.path.join(STATE, "logs")

SETTINGS_FILE = os.path.join(CONFIG, "settings.json")
PRIVACY_FILE = os.path.join(CONFIG, "privacy.json")
NETWORK_FILE = os.path.join(CONFIG, "network.json")
COOKIES_TXT = os.path.join(CONFIG, "cookies.txt")

WEBENGINE_PROFILE = os.path.join(DATA, "webengine")      # QtWebEngine 持久化存储（Cookie/LocalStorage/IndexedDB）
SHORTVIDEO_LIKES = os.path.join(DATA, "shortvideo_likes.json")

ENGINE_CACHE = os.path.join(CACHE, "engine_cache")       # Chromium 磁盘缓存
FLASH_CACHE = os.path.join(CACHE, "flash_cache")
THUMBS = os.path.join(CACHE, "thumbs")
MEDIA_INDEX_DB = os.path.join(CACHE, "media_index.db")
MANGA_COVERS = os.path.join(CACHE, "manga_covers")
SHORTVIDEO_WEBM = os.path.join(CACHE, "shortvideo_webm")

APP_LOG = os.path.join(LOGS, "omni_deck.log")
BOOT_LOG = os.path.join(LOGS, "boot.log")
FLASH_LOG = os.path.join(LOGS, "flash_crash.log")
GAME_LOGS = os.path.join(LOGS, "games")


def game_log(safe_game_id: str) -> str:
    """独立游戏子进程的 stdout/stderr 落盘位置。"""
    return os.path.join(GAME_LOGS, f"game_{safe_game_id}.log")


def ensure_state_dirs() -> None:
    for d in (CONFIG, DATA, CACHE, LOGS, GAME_LOGS, ENGINE_CACHE, FLASH_CACHE, THUMBS):
        os.makedirs(d, exist_ok=True)
