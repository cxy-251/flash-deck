import os
import sys
import threading
import json
import functools
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
GAMES_DIR = os.path.join(SCRIPT_DIR, "games")
HUB_HTML_PATH = os.path.join(ASSETS_DIR, "hub.html")
PORT = 8998

GAMES_REGISTRY = {}

DISPLAY_NAMES = {
    'countryside': 'My Countryside Life',
    'karryn-prison': 'Karryn\'s Prison',
    'gym-center': 'Gym Center',
    'succubus-boss': 'Succubus Boss',
    'secret-rule': 'Secret Rule',
    'live-empire': 'Live Empire',
}

DEFAULT_SVG_ICON = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect width="100" height="100" rx="20" fill="#1c2128"/>
  <path d="M30 40h40v20H30z" fill="#58a6ff"/>
  <circle cx="50" cy="50" r="15" fill="#388bfd"/>
</svg>'''

def register_game_folder(folder_path, custom_id=None):
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
        name = DISPLAY_NAMES.get(game_id, DISPLAY_NAMES.get(base_name, base_name.split('-')[-1].replace('00', '').strip()))
        
        icon_path = os.path.join(target_www, 'icon', 'icon.png')
        save_dir = os.path.join(target_www, 'save')
        os.makedirs(save_dir, exist_ok=True)

        GAMES_REGISTRY[game_id] = {
            'id': game_id,
            'name': name,
            'root': target_www,
            'save_dir': save_dir,
            'icon': icon_path if os.path.exists(icon_path) else None,
        }

def scan_games():
    GAMES_REGISTRY.clear()
    if os.path.exists(GAMES_DIR):
        for item in sorted(os.listdir(GAMES_DIR)):
            sub = os.path.join(GAMES_DIR, item)
            register_game_folder(sub, custom_id=item)

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
        super().do_HEAD()

    def do_GET(self):
        if self.path.startswith('/api/readdir?'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if 'path' in qs:
                req_path = urllib.parse.unquote(qs['path'][0])
                target_path = req_path
                
                if 'game_id' in qs and qs['game_id'][0] in GAMES_REGISTRY:
                    game_dir = GAMES_REGISTRY[qs['game_id'][0]]['dir']
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

def start_local_server():
    try:
        httpd = QuietThreadingHTTPServer(('127.0.0.1', PORT), MultiGameRequestHandler)
        httpd.serve_forever()
    except OSError:
        pass

threading.Thread(target=start_local_server, daemon=True).start()

# Chromium 硬件加速与日志静音
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--log-level=3 --disable-logging"
sys.argv.append("--log-level=3")
sys.argv.append("--disable-logging")
sys.argv.append("--enable-gpu-rasterization")
sys.argv.append("--enable-webgl")
sys.argv.append("--ignore-gpu-blocklist")
sys.argv.append("--enable-features=WebGL2ComputeContext")
sys.argv.append("--no-sandbox")
sys.argv.append("--autoplay-policy=no-user-gesture-required")

from PyQt5.QtCore import QUrl, Qt
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

    def javaScriptConsoleMessage(self, level, msg, line, source):
        # 仅保留关键的 RPG-Deck 框架启动信息或严重报错，彻底静音游戏自带的日常 console.log
        if level == QWebEnginePage.InfoMessageLevel:
            if not msg.startswith("[RPG-Deck]"):
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
            "pipeline_error"
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
        if url_str.startswith("action://play-rpg"):
            parsed = urllib.parse.urlparse(url_str)
            params = urllib.parse.parse_qs(parsed.query)
            game_id = params.get('id', [''])[0]
            title = params.get('title', ['RPG Game'])[0]
            if game_id:
                self.main_window.launch_game(game_id, title)
            return False

        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

class RpgDeckMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("RPG 游戏库")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.setStyleSheet("background-color: #000000;")

        self.is_in_game = False
        self.is_muted = False
        self.current_game_id = None

        self.setup_webengine()
        self.setup_ui()
        self.setup_shortcuts()

        self.load_hub()

    def setup_webengine(self):
        self.profile = QWebEngineProfile("rpg_deck_console_profile", self)

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
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
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

        self.btn_fullscreen = QPushButton("⛶ 全屏", self.overlay)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_mute = QPushButton("🔊 声音", self.overlay)
        self.btn_mute.clicked.connect(self.toggle_mute)

        for btn in [self.btn_home, self.btn_fullscreen, self.btn_mute]:
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
        self.setWindowTitle("RPG 游戏库")
        self.webview.load(QUrl(f"http://127.0.0.1:{PORT}/hub.html"))
        self.webview.setFocus()

    def launch_game(self, game_id: str, title: str):
        if game_id not in GAMES_REGISTRY:
            return

        self.is_in_game = True
        self.current_game_id = game_id
        self.setWindowTitle(f"{title} — RPG Deck")
        
        target_url = QUrl(f"http://127.0.0.1:{PORT}/game/{urllib.parse.quote(game_id)}/index.html")
        self.webview.load(target_url)
        self.webview.setFocus()
        
        self.overlay.adjustSize()
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)
        self.overlay.show()
        self.overlay.raise_()

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
