import os
import sys
import platform
import urllib.parse

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
PLUGINS_DIR = os.path.join(SCRIPT_DIR, "plugins")
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
CHROMIUM_CACHE = os.path.join(CACHE_DIR, "engine_cache")
HUB_HTML_PATH = os.path.join(ASSETS_DIR, "hub.html")


def get_flash_plugin_path():
    """专为 Steam Deck (Linux x86_64) 与 Windows (x64) 双端优化，动态挂载对应 Flash 插件"""
    sys_name = platform.system().lower()
    if sys_name == "linux":
        # Steam Deck / Linux 原生 SO (已内置并解除时间炸弹)
        return os.path.join(PLUGINS_DIR, "libpepflashplayer.so")
    elif sys_name == "windows":
        # Windows 端 DLL 插件 (已内置并解除时间炸弹)
        for dll in ["pepflashplayer64.dll", "pepflashplayer.dll", "pepflashplayer32.dll"]:
            p = os.path.join(PLUGINS_DIR, dll)
            if os.path.exists(p):
                return p
        return os.path.join(PLUGINS_DIR, "pepflashplayer64.dll")
    return os.path.join(PLUGINS_DIR, "libpepflashplayer.so")


FLASH_PLUGIN_PATH = get_flash_plugin_path()

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

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QStatusBar,
    QAction,
    QToolBar,
    QFileDialog,
    QTabWidget,
    QPushButton,
)
from PyQt5.QtWebEngineWidgets import (
    QWebEngineView,
    QWebEngineSettings,
    QWebEngineProfile,
    QWebEnginePage,
)


class CustomWebPage(QWebEnginePage):
    """支持多标签页自动弹出与本地 SWF 动作拦截的安全网页视图"""

    def __init__(self, profile, main_window, webview, parent=None):
        super().__init__(profile, parent)
        self.main_window = main_window
        self.webview = webview
        self.featurePermissionRequested.connect(self.on_feature_permission_requested)

    def on_feature_permission_requested(self, securityOrigin, feature):
        self.setFeaturePermission(
            securityOrigin, feature, QWebEnginePage.PermissionGrantedByUser
        )

    def createWindow(self, window_type):
        """网页弹窗或 target='_blank' 链接时，自动在全新标签页中打开"""
        proxy_page = QWebEnginePage(self.profile(), self)

        def handle_new_url(target_url):
            url_str = target_url.toString()
            if url_str and url_str != "about:blank":
                self.main_window.add_new_tab(target_url, title="加载中...", switch_to=True)
                proxy_page.deleteLater()

        proxy_page.urlChanged.connect(handle_new_url)
        return proxy_page

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        url_str = url.toString()
        if url_str == "action://open-local":
            self.main_window.prompt_open_local_swf()
            return False

        if url_str.startswith("action://play-swf"):
            parsed = urllib.parse.urlparse(url_str)
            params = urllib.parse.parse_qs(parsed.query)
            rel_file = params.get("file", [""])[0]
            title = params.get("title", ["Flash Game"])[0]
            hint = params.get("hint", [""])[0]
            if rel_file:
                full_path = os.path.join(SCRIPT_DIR, rel_file)
                self.main_window.play_swf_direct(full_path, title, hint, target_webview=self.webview)
            return False

        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            self.setUrl(url)
            return False

        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class RocoMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 固定窗口标题为 Flash Deck
        self.setWindowTitle("Flash Deck")
        self.resize(1060, 700)
        self.setMinimumSize(960, 600)
        self.is_pure_mode = False
        self.is_muted = False

        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))

        # 共享同一个持久化 Profile（所有标签页共享 Cookie、Flash 本地存档与硬件加速）
        self.profile = QWebEngineProfile("flash_deck_profile", self)
        self.profile.setPersistentStoragePath(os.path.join(DATA_DIR, "storage"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.ForcePersistentCookies
        )
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
        )

        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, False)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)

        self.setup_ui()

        # 默认打开第一个标签页：洛克王国 (官方默认启动)
        self.add_new_tab(QUrl("https://17roco.qq.com"), title="👑 洛克王国", switch_to=True)

    def setup_ui(self):
        # 1. 现代化深色标签页控件 (QTabWidget)
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # 标签栏右上角配备快捷新建标签按钮 [+]
        self.new_tab_btn = QPushButton("➕")
        self.new_tab_btn.setFixedSize(30, 26)
        self.new_tab_btn.setToolTip("新建标签页")
        self.new_tab_btn.setStyleSheet("""
            QPushButton {
                background: #21262d;
                color: #58a6ff;
                border: 1px solid #30363d;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                margin-right: 6px;
            }
            QPushButton:hover {
                background: #30363d;
                color: #79c0ff;
            }
        """)
        self.new_tab_btn.clicked.connect(lambda: self.add_new_tab(title="🏠 游戏大厅", switch_to=True))
        self.tabs.setCornerWidget(self.new_tab_btn, Qt.TopRightCorner)

        # 现代化深色主题 QSS
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b0e14;
            }
            QTabWidget::pane {
                border: 0;
                background: #0b0e14;
            }
            QTabBar::tab {
                background: #161b22;
                color: #8b949e;
                padding: 7px 16px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                min-width: 90px;
                max-width: 220px;
            }
            QTabBar::tab:selected {
                background: #21262d;
                color: #58a6ff;
                border-bottom: 2px solid #58a6ff;
            }
            QTabBar::tab:hover:!selected {
                background: #1c2128;
                color: #c9d1d9;
            }
            QToolBar {
                background: #161b22;
                border-bottom: 1px solid #30363d;
                spacing: 8px;
                padding: 4px 8px;
            }
            QToolButton {
                background: transparent;
                color: #c9d1d9;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QToolButton:hover {
                background: #21262d;
                color: #58a6ff;
            }
            QStatusBar {
                background: #0d1117;
                color: #8b949e;
                font-size: 11px;
                border-top: 1px solid #21262d;
            }
        """)

        self.create_toolbar()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def create_toolbar(self):
        self.toolbar = QToolBar("快捷控制")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # ➕ 新建标签 (打开大厅)
        self.new_tab_action = QAction("➕ 新建标签", self)
        self.new_tab_action.triggered.connect(lambda: self.add_new_tab(title="🏠 游戏大厅", switch_to=True))
        self.toolbar.addAction(self.new_tab_action)

        # 🏠 游戏大厅 (当前标签页导航回大厅)
        self.home_action = QAction("🏠 游戏大厅", self)
        self.home_action.triggered.connect(self.open_hub_in_current_tab)
        self.toolbar.addAction(self.home_action)

        # 🎮 窗口内全屏 (仅在有外部网页横幅的网页游戏如洛克王国中展示，单机游戏与大厅自动隐藏)
        self.fullscreen_action = QAction("🎮 窗口内全屏 (关)", self)
        self.fullscreen_action.triggered.connect(self.toggle_window_fullscreen)
        self.toolbar.addAction(self.fullscreen_action)

        # 🔊 声音控制 (全局静音/开启)
        self.audio_action = QAction("🔊 声音: 开启", self)
        self.audio_action.triggered.connect(self.toggle_audio)
        self.toolbar.addAction(self.audio_action)

    def current_webview(self) -> QWebEngineView:
        widget = self.tabs.currentWidget()
        if isinstance(widget, QWebEngineView):
            return widget
        return None

    def add_new_tab(self, url: QUrl = None, title: str = "🏠 游戏大厅", switch_to: bool = True):
        """新建一个独立的 Flash 标签页"""
        webview = QWebEngineView(self)
        page = CustomWebPage(self.profile, self, webview, parent=webview)
        webview.setPage(page)
        webview.page().setAudioMuted(self.is_muted)
        if url:
            webview.setProperty("initial_url", url.toString())

        # 动态更新标签标题
        def update_tab_title(new_title):
            idx = self.tabs.indexOf(webview)
            if idx != -1:
                clean_title = new_title.split("-")[0].split("_")[0].strip()
                if not clean_title or "4399" in clean_title:
                    clean_title = title
                self.tabs.setTabText(idx, clean_title[:14])
                self.tabs.setTabToolTip(idx, new_title)

        def handle_progress(progress):
            if self.current_webview() == webview:
                self.status_bar.showMessage(f"正在加载... {progress}%")

        def handle_finish(success):
            if self.current_webview() == webview:
                if success:
                    self.status_bar.showMessage("就绪 (独立 Flash 容器)", 3000)
                else:
                    self.status_bar.showMessage("加载失败，请检查网络", 3000)

        webview.titleChanged.connect(update_tab_title)
        webview.loadProgress.connect(handle_progress)
        webview.loadFinished.connect(handle_finish)
        webview.urlChanged.connect(lambda u: self.on_url_changed(u, webview))

        index = self.tabs.addTab(webview, title)
        if switch_to:
            self.tabs.setCurrentIndex(index)

        # 加载目标 URL 或本地游戏大厅
        if url is not None:
            webview.load(url)
            self.update_fullscreen_action_visibility(webview, target_url=url)
        else:
            if os.path.exists(HUB_HTML_PATH):
                hub_url = QUrl.fromLocalFile(HUB_HTML_PATH)
                webview.load(hub_url)
                self.update_fullscreen_action_visibility(webview, target_url=hub_url)
            else:
                roco_url = QUrl("https://17roco.qq.com")
                webview.load(roco_url)
                self.update_fullscreen_action_visibility(webview, target_url=roco_url)

        return webview

    def close_tab(self, index):
        """关闭指定标签页"""
        if index < 0 or index >= self.tabs.count():
            return

        if self.tabs.count() > 1:
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            widget.deleteLater()
        else:
            # 最后一个标签页关闭时，重置为游戏大厅
            webview = self.current_webview()
            if webview and os.path.exists(HUB_HTML_PATH):
                hub_url = QUrl.fromLocalFile(HUB_HTML_PATH)
                webview.load(hub_url)
                self.tabs.setTabText(0, "🏠 游戏大厅")
                self.update_fullscreen_action_visibility(webview, target_url=hub_url)

    def update_fullscreen_action_visibility(self, webview, target_url=None):
        """仅在洛克王国页面展示窗口内全屏按钮，造梦西游、大厅与单机SWF等其他全部页面自动隐藏"""
        if not webview:
            self.fullscreen_action.setVisible(False)
            return

        u = target_url or webview.url()
        url_str = u.toString().lower() if u and not u.isEmpty() else ""
        if not url_str and webview.property("initial_url"):
            url_str = str(webview.property("initial_url")).lower()

        # 仅对洛克王国官网展示窗口内全屏
        is_roco = "17roco.qq.com" in url_str or "17roco" in url_str
        self.fullscreen_action.setVisible(is_roco)
        if is_roco:
            webview.page().runJavaScript(
                "!!document.getElementById('roco-pure-mode-style')",
                lambda is_on: self.fullscreen_action.setText("🎮 窗口内全屏 (开)" if is_on else "🎮 窗口内全屏 (关)")
            )
        else:
            self.fullscreen_action.setText("🎮 窗口内全屏 (关)")

    def on_tab_changed(self, index):
        """切换标签页时更新工具栏状态"""
        webview = self.current_webview()
        self.update_fullscreen_action_visibility(webview)

    def on_url_changed(self, url, webview):
        if webview == self.current_webview():
            self.update_fullscreen_action_visibility(webview, target_url=url)

    def open_hub_in_current_tab(self):
        """在当前激活的标签页中返回游戏大厅"""
        webview = self.current_webview()
        if webview:
            if os.path.exists(HUB_HTML_PATH):
                hub_url = QUrl.fromLocalFile(HUB_HTML_PATH)
                webview.load(hub_url)
                self.tabs.setTabText(self.tabs.currentIndex(), "🏠 游戏大厅")
                self.update_fullscreen_action_visibility(webview, target_url=hub_url)

    def play_swf_direct(self, file_path, title="Flash Game", hint="", target_webview=None):
        """在当前或指定标签页中原生嵌入运行 SWF 单机神作（单机游戏纯净无横幅，自动隐藏全屏按钮）"""
        if not os.path.exists(file_path):
            self.status_bar.showMessage(f"文件不存在: {file_path}", 4000)
            return

        webview = target_webview or self.current_webview()
        if not webview:
            webview = self.add_new_tab(title=title, switch_to=True)

        swf_file_url = QUrl(f"file://{file_path}")
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
            <style>
                html, body {{
                    margin: 0; padding: 0; width: 100%; height: 100%;
                    background-color: #0b0e14; overflow: hidden;
                    display: flex; justify-content: center; align-items: center;
                }}
                embed, object {{
                    width: 100%; height: 100%; max-width: 960px; max-height: 560px; outline: none;
                }}
            </style>
        </head>
        <body>
            <embed src="file://{file_path}" type="application/x-shockwave-flash" quality="high" wmode="direct" allowscriptaccess="always">
        </body>
        </html>
        """
        webview.setHtml(html, swf_file_url)
        idx = self.tabs.indexOf(webview)
        if idx != -1:
            self.tabs.setTabText(idx, title[:14])

        self.update_fullscreen_action_visibility(webview, target_url=swf_file_url)

        msg = f"🎮 正在畅玩: {title}"
        if hint:
            msg += f" | 💡 操作: {hint.replace('_', ' ')}"
        self.status_bar.showMessage(msg, 9000)

    def prompt_open_local_swf(self):
        """选择本地 SWF 文件并在新标签页中运行"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要运行的 Flash SWF 文件", os.path.expanduser("~"), "Flash Files (*.swf)"
        )
        if file_path:
            name = os.path.splitext(os.path.basename(file_path))[0]
            new_view = self.add_new_tab(title=name, switch_to=True)
            self.play_swf_direct(file_path, name, target_webview=new_view)

    def toggle_audio(self):
        """实时控制所有标签页音频静音/开启"""
        self.is_muted = not self.is_muted
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, QWebEngineView):
                w.page().setAudioMuted(self.is_muted)

        if self.is_muted:
            self.audio_action.setText("🔇 声音: 静音")
            self.status_bar.showMessage("已静音所有标签页", 2000)
        else:
            self.audio_action.setText("🔊 声音: 开启")
            self.status_bar.showMessage("已开启所有标签页声音", 2000)

    def toggle_window_fullscreen(self):
        """采用动态 CSS 规则注入与移除机制，彻底避免登录前后 DOM 节点替换导致无法退出的问题"""
        webview = self.current_webview()
        if not webview:
            return

        toggle_js = """
        (function() {
            var styleId = 'roco-pure-mode-style';
            var backdropId = 'roco-pure-backdrop';
            var existingStyle = document.getElementById(styleId);
            
            if (existingStyle) {
                // 当前处于窗口内全屏 -> 彻底移除规则与遮罩，还原页面原始排版
                existingStyle.remove();
                var backdrop = document.getElementById(backdropId);
                if (backdrop) backdrop.remove();
                return false;
            } else {
                // 当前处于普通页面 -> 动态注入居中遮罩与隐藏规则
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

        def on_toggle_result(is_enabled):
            if is_enabled:
                self.fullscreen_action.setText("🎮 窗口内全屏 (开)")
                self.status_bar.showMessage("已开启当前标签页窗口内全屏", 3000)
            else:
                self.fullscreen_action.setText("🎮 窗口内全屏 (关)")
                self.status_bar.showMessage("已关闭当前标签页窗口内全屏", 3000)

        webview.page().runJavaScript(toggle_js, on_toggle_result)


def main():
    app = QApplication(sys.argv)
    window = RocoMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
