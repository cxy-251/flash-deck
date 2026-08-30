"""
flash_runner.py - Omni Deck 独立 Flash 运行引擎 (PyQt5 隔离环境)

架构设计与职责：
1. 运行环境隔离：利用 PyQt5 (Chromium 83) 独立子进程运行，完美支持 PPAPI Flash (libpepflashplayer.so)。
2. 显示协议兼容：针对 SteamOS Game Mode (Gamescope)，通过 QT_QPA_PLATFORM=xcb 强制使用 XWayland 兼容层，防止底层协议崩溃。
3. 网页全屏与静音增强：内置 JavaScript DOM 提取引擎，一键实现网页 Flash 组件的窗口内最大化填充，并支持底层音频流静音。
"""

import sys
import os
import urllib.parse
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGINS_DIR = os.path.join(SCRIPT_DIR, "flash_games", "plugins")
FLASH_PLUGIN_PATH = os.path.join(PLUGINS_DIR, "libpepflashplayer.so") if sys.platform != "win32" else os.path.join(PLUGINS_DIR, "pepflashplayer64.dll")

os.makedirs(os.path.join(SCRIPT_DIR, "cache", "flash_cache"), exist_ok=True)
chromium_flags = [
    f"--disk-cache-dir={os.path.join(SCRIPT_DIR, 'cache', 'flash_cache')}",
    "--disk-cache-size=1073741824",
    "--enable-gpu-rasterization",
    "--ignore-gpu-blocklist",
    "--disable-gpu-watchdog",
    "--disable-gpu-process-crash-limit",
    "--enable-webgl",
    "--no-sandbox",
    "--autoplay-policy=no-user-gesture-required",
    f"--ppapi-flash-path={FLASH_PLUGIN_PATH}",
    "--ppapi-flash-version=32.0.0.465",
    "--allow-running-insecure-content",
    "--ignore-certificate-errors",
    "--disable-site-isolation-trials",
    "--disable-web-security"
]
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(chromium_flags)
os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QPushButton, QShortcut
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage, QWebEngineSettings

class FlashPage(QWebEnginePage):
    """自定义 Flash 网页渲染 Page，负责拦截并自动处理 JavaScript 弹窗与确认框"""
    def javaScriptConfirm(self, securityOrigin, msg):
        """自动确认网页 Flash 加载时的弹窗提示，保证游戏无缝启动"""
        return True

class FlashRunner(QMainWindow):
    """
    Flash 专属独立全屏/窗口化宿主容器
    
    参数说明:
        game_id (str): 游戏唯一标识符
        title (str): 游戏展示标题
        url (str): 网页 Flash 目标链接 (如 17roco 登录入口)
        engine (str): 引擎类型 ('web_flash' 或 'swf')
        swf_path (str): 本地 SWF 文件的物理路径
        hint (str): 游戏操作提示文字
    """
    def __init__(self, game_id, title, url, engine, swf_path, hint):
        super().__init__()
        self.setWindowTitle(f"{title} — Omni Deck Flash Runner")
        self.resize(1280, 800)
        
        self.webview = QWebEngineView(self)
        self.profile = QWebEngineProfile("omni_flash_profile", self)
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 QtWebEngine/1.0"
        )
        self.profile.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
        self.profile.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        
        self.page = FlashPage(self.profile, self)
        self.webview.setPage(self.page)
        
        self.setCentralWidget(self.webview)
        
        # 悬浮控制胶囊
        self.overlay = QWidget(self)
        self.overlay_layout = QHBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(6, 4, 6, 4)
        self.overlay_layout.setSpacing(6)
        
        self.btn_back = QPushButton("🔙 退出专区")
        self.btn_back.clicked.connect(self.close)
        
        self.btn_fullscreen = QPushButton("⛶ 窗口内全屏")
        self.btn_fullscreen.clicked.connect(self.toggle_web_fullscreen)
        
        self.btn_mute = QPushButton("🔊 静音")
        self.btn_mute.clicked.connect(self.toggle_mute)
        
        self.overlay_layout.addWidget(self.btn_back)
        self.overlay_layout.addWidget(self.btn_fullscreen)
        self.overlay_layout.addWidget(self.btn_mute)
        
        self.overlay.setStyleSheet("""
            QWidget { background: rgba(15, 20, 28, 0.88); border-radius: 16px; }
            QPushButton { background: transparent; color: #a1b0c0; border: none; font-size: 13px; font-weight: 600; padding: 4px 10px; }
            QPushButton:hover { color: #ffffff; background: rgba(255, 255, 255, 0.1); border-radius: 12px; }
        """)
        
        self.webview.loadFinished.connect(self.on_load_finished)
        
        if engine == 'web_flash':
            self.webview.load(QUrl(url))
        else:
            html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>html, body {{margin: 0; padding: 0; width: 100%; height: 100%; background-color: #080a0f; overflow: hidden; display: flex; align-items: center; justify-content: center;}} embed {{width: 100%; height: 100%; max-width: 1060px; max-height: 700px;}}</style></head><body><embed src="file://{swf_path}" type="application/x-shockwave-flash" quality="high" wmode="direct" allowscriptaccess="always"></body></html>"""
            self.webview.setHtml(html, QUrl(f"file://{swf_path}"))
            
        QShortcut(QKeySequence("F11"), self, self.toggle_web_fullscreen)

    def on_load_finished(self):
        """网页或 SWF 加载完成回调：自适应控制胶囊尺寸并定位到窗口右上角"""
        self.overlay.adjustSize()
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)
        self.overlay.show()
        self.overlay.raise_()

    def resizeEvent(self, event):
        """窗口尺寸变动事件：保持右上角悬浮胶囊始终对齐右侧边缘"""
        super().resizeEvent(event)
        self.overlay.move(self.width() - self.overlay.width() - 16, 16)

    def toggle_web_fullscreen(self):
        """
        网页 Flash 窗口内全屏切换：
        通过注入 JavaScript 寻找页面中的 <object> 或 <embed> Flash 元素，
        将其样式修改为 fixed 定位并填满整个视口 (100vw, 100vh)，再次点击恢复原样。
        """
        js = '''
        (function() {
            if (window.__omni_fs) {
                var el = window.__omni_fs_el;
                if (el) {
                    el.style.position = window.__omni_fs.pos;
                    el.style.top = window.__omni_fs.top;
                    el.style.left = window.__omni_fs.left;
                    el.style.width = window.__omni_fs.width;
                    el.style.height = window.__omni_fs.height;
                    el.style.zIndex = window.__omni_fs.zindex;
                }
                window.__omni_fs = null;
                return false;
            } else {
                var el = document.querySelector('object') || document.querySelector('embed');
                if (el) {
                    window.__omni_fs = {
                        pos: el.style.position,
                        top: el.style.top,
                        left: el.style.left,
                        width: el.style.width,
                        height: el.style.height,
                        zindex: el.style.zIndex
                    };
                    window.__omni_fs_el = el;
                    el.style.position = 'fixed';
                    el.style.top = '0';
                    el.style.left = '0';
                    el.style.width = '100vw';
                    el.style.height = '100vh';
                    el.style.zIndex = '999999';
                    return true;
                }
                return null;
            }
        })();
        '''
        def callback(is_fs):
            if is_fs is True:
                self.btn_fullscreen.setText("🗗 还原页面")
            elif is_fs is False:
                self.btn_fullscreen.setText("⛶ 窗口内全屏")
        self.page.runJavaScript(js, callback)
        
    def toggle_mute(self):
        """切换当前 Chromium 实例的底层音频静音状态"""
        is_muted = self.page.audioMuted()
        self.page.setAudioMuted(not is_muted)
        if not is_muted:
            self.btn_mute.setText("🔇 取消静音")
        else:
            self.btn_mute.setText("🔊 静音")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    game_data_json = sys.argv[1]
    game_data = json.loads(game_data_json)
    
    runner = FlashRunner(
        game_data['id'],
        game_data.get('title', game_data.get('name', game_data['id'])),
        game_data.get('url', ''),
        game_data.get('engine', ''),
        os.path.join(game_data.get('root', '') or '', game_data.get('swf_file') or ''),
        game_data.get('hint', '')
    )
    runner.showNormal()
    sys.exit(app.exec_())
