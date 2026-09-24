"""
Omni Deck 桌面壳（PyQt6 + QtWebEngine）：一个铺满窗口的 WebEngineView 承载大厅页面，
按游戏类型分流启动（网页游戏在本视口内、独立游戏/网页 Flash 走子进程），右上角悬浮胶囊
（返回专区/纯净全屏/全屏/静音），内存看门狗，本机原生音视频播放通道。
"""
import json
import os
import sys
import threading
import subprocess
import urllib.parse

from omni.core import paths, process, settings
from omni.core.log import boot, log
from omni.features.games import launcher, registry
from omni.network import lan

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
        log(level_str, f"{msg} (Line {line} in {src_name})", tag=active_game)

    def javaScriptAlert(self, securityOrigin, msg):
        """网页 window.alert() 的回调：不弹原生对话框（单机全屏体验），只记日志。

        Args:
            securityOrigin: 调用来源页面。
            msg: alert 文本内容。
        """
        try:
            active_game = getattr(self.main_window, 'current_game_id', None) or "Emulator"
            log("WARN", f"[JS-Alert] {msg}", tag=active_game)
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
            log("WARN", f"[JS-Confirm] {msg}", tag=active_game)
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

class MainWindow(QMainWindow):
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
        boot("RpgDeckMainWindow: setup_webengine() …")
        self.setup_webengine()
        boot("RpgDeckMainWindow: setup_ui() …")
        self.setup_ui()
        boot("RpgDeckMainWindow: setup_shortcuts() …")
        self.setup_shortcuts()

        boot("RpgDeckMainWindow: load_hub() …")
        self.load_hub()
        self.setup_mem_guard()
        boot("RpgDeckMainWindow: __init__ done")

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
        limit_mb = settings.get("mem_restart_mb")
        if rss <= 0 or rss < limit_mb:
            return
        if getattr(self, 'is_in_game', False):
            log("WARN", f"内存 {rss:.0f}MB 超阈值，但正在游戏中，暂缓重启", tag="Mem")
            return
        # 有下载在跑就先不重启（execv 会打断；漫画队列/ MEGA 都能续传，但能等就等）
        try:
            if __import__("omni.features.manga.service", fromlist=["x"]).is_active_downloading():
                log("WARN", f"内存 {rss:.0f}MB 超阈值，但有下载在跑，暂缓重启", tag="Mem")
                return
        except Exception:
            pass
        log("WARN", f"内存 {rss:.0f}MB > {limit_mb}MB，自重启 Omni Deck", tag="Mem")
        boot(f"mem watchdog: RSS {rss:.0f}MB over {limit_mb}MB → self-restart via execv")
        try:
            process.kill_children()
        except Exception:
            pass
        process.run_shutdown_hooks()
        process.reap_descendants()
        script = os.path.join(paths.REPO, "main.py")
        try:
            os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
        except Exception as e:
            # execv 没成功 → 保持运行，下个 tick 再试（别把自己搞挂）
            log("ERROR", f"自重启 execv 失败，继续运行：{e}", tag="Mem")

    def setup_webengine(self):
        """配置 QtWebEngine 专用 Profile、持久化存储与核心 Runtime Polyfill 脚本注入"""
        boot("setup_webengine: QWebEngineProfile(...) …")
        self.profile = QWebEngineProfile("omni_deck_console_profile", self)
        boot("setup_webengine: profile created")
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 QtWebEngine/1.0"
        )
        self.profile.setPersistentStoragePath(paths.WEBENGINE_PROFILE)
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

        boot("setup_webengine: profile config done, settings…")
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
        core_js_path = os.path.join(paths.WEB, "players", "rpg-runtime.js")
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

        boot("setup_ui: QWebEngineView(self) …  ← Chromium 在这里起，游戏模式卡死常卡这一步")
        self.webview = QWebEngineView(self)
        boot("setup_ui: QWebEngineView created")
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
        from omni.shell.native_player import NativePlayerWidget, PlayerBridge

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
            log("WARN", "qwebchannel.js 资源读取失败，本机原生播放桥接不可用（会自动退回网页内置播放器）", tag="NativePlayer")

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
            boot(f"on_load_finished: first page loaded ok={ok}  ← 启动全程走完，界面已出")
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
            log("INFO", f"⬅ 退出游戏 [{prev_game}]，返回大厅", tag="Lifecycle")
            sys.stderr.write("=" * 70 + "\n")
        self.is_in_game = False
        self.is_external_game = False
        self.current_game_id = None
        self.overlay.hide()
        self.btn_pure.hide()
        self.setWindowTitle("Omni Deck")
        self.webview.stop()
        self.webview.load(QUrl(f"http://127.0.0.1:{lan.PORT}/hub.html"))
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
        if prev_game and prev_game in registry.REGISTRY:
            gtype = registry.REGISTRY[prev_game].get('type')
            if gtype:
                cat = gtype
        cat = cat_map.get(cat, cat)
        if prev_game:
            sys.stderr.write("\n" + "=" * 70 + "\n")
            log("INFO", f"⬅ 退出游戏 [{prev_game}]，返回 [{cat}] 专区", tag="Lifecycle")
            sys.stderr.write("=" * 70 + "\n")
        self.is_in_game = False
        self.is_external_game = False
        self.current_game_id = None
        self.overlay.hide()
        self.btn_pure.hide()
        self.setWindowTitle("Omni Deck")
        self.webview.stop()
        self.webview.load(QUrl(f"http://127.0.0.1:{lan.PORT}/hub.html?category={cat}"))
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
        if game_id not in registry.REGISTRY:
            # 1. 尝试 URL 解码与大小写不敏感匹配
            unq_id = urllib.parse.unquote(game_id).strip()
            matched_id = next((gid for gid in registry.REGISTRY if gid.lower() == unq_id.lower()), None)
            if matched_id:
                game_id = matched_id
            else:
                # 2. 尝试重新扫描游戏目录（热发现刚下载/转换的新游戏）
                registry.scan(force=True)
                if game_id not in registry.REGISTRY:
                    matched_id = next((gid for gid in registry.REGISTRY if gid.lower() == unq_id.lower()), None)
                    if matched_id:
                        game_id = matched_id
                    else:
                        log("ERROR", f"未找到游戏注册信息: {game_id}", tag="Launcher")
                        return

        game_data = registry.REGISTRY[game_id]
        self.current_game_type = game_data.get('type', 'rpg')
        self.current_game_id = game_id

        sys.stderr.write("\n" + "=" * 70 + "\n")
        log("INFO", f"🎮 启动游戏: [{game_id}] (Type: {self.current_game_type})", tag="Lifecycle")
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
            target_url = QUrl(f"http://127.0.0.1:{lan.PORT}/player_retro.html?id={urllib.parse.quote(game_id)}&system={system_core}&rom={urllib.parse.quote(rom_file)}")
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
            target_url = QUrl(f"http://127.0.0.1:{lan.PORT}/game/{urllib.parse.quote(game_id)}/{entry}?engine=renpy&type=slg")
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
                flash_python = paths.FLASH_VENV_PYTHON
                if not os.path.exists(flash_python):
                    flash_python = sys.executable
                cmd = [flash_python, os.path.join(paths.REPO, "omni", "shell", "flash_runner.py"), game_data_json]
                
                clean_env = os.environ.copy()
                for k in list(clean_env.keys()):
                    if k.startswith('QT_') or k.startswith('QML_'):
                        del clean_env[k]
                clean_env['QT_QPA_PLATFORM'] = 'xcb'
                
                def runner():
                    """在后台线程里拉起 flash_runner.py 隔离子进程并等待其退出。"""
                    log_file = open(paths.FLASH_LOG, "w")
                    rc = None
                    try:
                        proc = subprocess.Popen(
                            cmd,
                            env=clean_env,
                            preexec_fn=process.set_pdeathsig,
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
                    log("INFO" if rc == 0 else "WARN",
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
                target_url = QUrl(f"http://127.0.0.1:{lan.PORT}/player_flash.html?id={urllib.parse.quote(game_id)}&file={urllib.parse.quote(swf_file)}")
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
        
        target_url = QUrl(f"http://127.0.0.1:{lan.PORT}/game/{urllib.parse.quote(game_id)}/index.html")
        self.webview.load(target_url)
        self.webview.setFocus()
        
        self.overlay.adjustSize()
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)
        self.overlay.show()
        self.overlay.raise_()

    def launch_standalone_game(self, game_id: str, title: str):
        """调用全局独立进程拉起器运行大型 PC 游戏，退出时自动回调激活大厅"""
        self.showMinimized()
        launcher.launch(game_id, title, on_exit=lambda: self.renpy_finished.emit())

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
        process.shutdown()
