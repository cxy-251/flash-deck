"""
flash_runner.py - Omni Deck 独立 Flash 运行引擎 (PyQt5 隔离环境)

架构设计与职责：
1. 运行环境隔离：利用 PyQt5 (Chromium 83) 独立子进程运行，完美支持 PPAPI Flash (libpepflashplayer.so)。
2. 显示协议兼容：针对 SteamOS Game Mode (Gamescope)，通过 QT_QPA_PLATFORM=xcb 强制使用 XWayland 兼容层，防止底层协议崩溃。
3. 网页全屏与静音增强：内置 JavaScript DOM 提取引擎，一键实现网页 Flash 组件的窗口内最大化填充，并支持底层音频流静音。
"""

import sys
import os
import traceback
import urllib.parse
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# PyQt5 默认把槽函数里未捕获的异常直接 qFatal 掉整个进程（"点一下按钮就闪退"）。
# 装个 excepthook：异常写进 flash_crash.log，进程不因此退出。
def _log_uncaught(exc_type, exc_value, exc_tb):
    """sys.excepthook 替换函数：把未捕获异常写进 cache/flash_crash.log，不让进程崩溃退出。

    Args:
        exc_type: 异常类型。
        exc_value: 异常实例。
        exc_tb: 异常的 traceback 对象。
    """
    try:
        with open(os.path.join(SCRIPT_DIR, "cache", "flash_crash.log"), "a") as f:
            f.write("\n[flash_runner uncaught]\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass

sys.excepthook = _log_uncaught

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

from PyQt5.QtCore import QUrl, Qt, QTimer
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
        """按类文档字符串里说明的参数构造窗口并加载对应的 Flash 内容。"""
        super().__init__()
        self.setWindowTitle(f"{title} — Omni Deck Flash Runner")
        self.resize(1280, 800)
        
        self.webview = QWebEngineView(self)
        # profile 不挂到窗口下 —— 挂 self 的话关窗时 Qt 可能先销毁 profile 再销毁 page，
        # 报 "Release of profile requested but WebEnginePage still not deleted. Expect
        # troubles!"，teardown 卡住 → 进程不退 → omni 那边 proc.wait() 不返回 → 大厅收不到
        # 退出回调、界面卡住。改成无父对象，Python 引用兜住生命周期。
        self.profile = QWebEngineProfile("omni_flash_profile")
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
        """全屏切换。以前只靠注入 JS 去拉页面里的 <object>/<embed> —— 洛克王国的 Flash
        在**跨源 iframe** 里，JS 根本够不着，所以按钮"没反应"。
        现在：**先无条件切整窗口全屏**（这个一定生效），再顺带发一次 JS 尽量把 Flash
        元素也撑满（够得着就撑，够不着拉倒）。"""
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("⛶ 全屏")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("🗗 退出全屏")
        js = r'''
        (function() {
            function allDocs() {
                var docs = [document];
                function dive(w) {
                    var fr;
                    try { fr = w.frames; } catch (e) { return; }
                    for (var i = 0; i < fr.length; i++) {
                        try {
                            var d = fr[i].document;
                            if (d) { docs.push(d); dive(fr[i]); }
                        } catch (e) {}   // 跨源 iframe，跳过
                    }
                }
                try { dive(window); } catch (e) {}
                return docs;
            }
            function biggestFlash() {
                var best = null, bestArea = 0;
                allDocs().forEach(function(d) {
                    var list = d.querySelectorAll('object, embed');
                    for (var i = 0; i < list.length; i++) {
                        var el = list[i];
                        var t = (el.type || '') + ' ' + (el.getAttribute('src') || '') + ' ' + (el.getAttribute('data') || '');
                        if (list.length > 1 && t.indexOf('flash') < 0 && t.indexOf('.swf') < 0) continue;
                        var r = el.getBoundingClientRect();
                        var area = r.width * r.height;
                        if (area >= bestArea) { bestArea = area; best = el; }
                    }
                });
                return best;
            }
            if (window.top.__omni_fs && window.top.__omni_fs_el) {
                var el = window.top.__omni_fs_el, s = window.top.__omni_fs;
                el.style.position = s.pos; el.style.top = s.top; el.style.left = s.left;
                el.style.width = s.width; el.style.height = s.height; el.style.zIndex = s.zindex;
                window.top.__omni_fs = null; window.top.__omni_fs_el = null;
                try { window.dispatchEvent(new Event('resize')); } catch (e) {}
                return false;
            }
            var el = biggestFlash();
            if (!el) return null;
            window.top.__omni_fs = {
                pos: el.style.position, top: el.style.top, left: el.style.left,
                width: el.style.width, height: el.style.height, zindex: el.style.zIndex
            };
            window.top.__omni_fs_el = el;
            el.style.position = 'fixed'; el.style.top = '0'; el.style.left = '0';
            el.style.width = '100vw'; el.style.height = '100vh'; el.style.zIndex = '2147483647';
            el.style.background = '#000';
            try { window.dispatchEvent(new Event('resize')); } catch (e) {}
            return true;
        })();
        '''
        # 结果不影响按钮状态（窗口全屏已经切好了），纯 best-effort
        self.page.runJavaScript(js)

    def closeEvent(self, event):
        """关窗时按正确顺序拆 webview/page，再硬退 —— 保证 omni 那边 proc.wait() 一定返回。"""
        try:
            self.webview.setPage(None)
        except Exception:
            pass
        for obj in ("page", "webview"):
            try:
                getattr(self, obj).deleteLater()
            except Exception:
                pass
        super().closeEvent(event)
        QApplication.quit()
        # Qt 的 profile/page 释放偶尔会卡住，800ms 后无论如何硬退
        QTimer.singleShot(800, lambda: os._exit(0))
        
    def toggle_mute(self):
        """切换当前 Chromium 实例的底层音频静音状态"""
        # 坑：PyQt5 QWebEnginePage 的读取器是 isAudioMuted()，没有 audioMuted() 这个方法。
        # 之前写成 self.page.audioMuted() → AttributeError → PyQt5 把整个进程 qFatal 掉
        #（就是"点一下声音按钮页面卡死然后闪退"）。
        try:
            is_muted = self.page.isAudioMuted()
        except Exception:
            is_muted = getattr(self, "_muted", False)
        try:
            self.page.setAudioMuted(not is_muted)
        except Exception:
            traceback.print_exc()
        self._muted = not is_muted
        self.btn_mute.setText("🔇 取消静音" if self._muted else "🔊 静音")

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
    # 直接全屏起 —— 在 gamescope / Steam 里，一个 1280x800 的窗口跟大厅窗口并存会让
    # 合成器分不清前台是谁，关掉 flash 后大厅就点不动了。全屏起 = 明确的前台 app。
    runner.showFullScreen()
    sys.exit(app.exec_())
