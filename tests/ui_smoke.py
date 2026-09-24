"""
UI 冒烟测试：起一个无界面服务实例（独立端口 + 临时状态目录），用 offscreen 的 QtWebEngine
打开大厅，依次进入各游戏分类与媒体分区，检查视图可见、内容渲染出来、JS 控制台没有报错，
并给每一步截图（默认存到 /tmp/omni-ui-smoke/）。

    .venv/bin/python tests/ui_smoke.py [--out DIR]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing"

import route_snapshot as rs  # noqa: E402  复用起服务的逻辑

from PyQt6.QtCore import QTimer, QUrl  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

MANIFEST = json.load(open(os.path.join(rs.REPO, "omni", "manifest.json"), encoding="utf-8"))
MEDIA = next(g for g in MANIFEST["groups"] if g["id"] == "media")["tabs"]
GAME_TABS = next(g for g in MANIFEST["groups"] if g["id"] == "games")["tabs"]

# 每一步：(名字, 要执行的 JS, 最长等待毫秒, 检查用的 JS 表达式——返回 [ok, 说明])；检查每 500ms
# 轮询一次，通过就进下一步，超时算失败
STEPS = [("portal", "showPortalView()", 20000,
          "[document.getElementById('portal-view').style.display !== 'none' && allGames.length > 0, 'games=' + allGames.length]")]
for tab in GAME_TABS:
    if tab == "fav":
        continue
    check = ("[document.getElementById('sc2-panel').style.display === 'block', 'sc2 panel']" if tab == "sc2" else
             "(function(){ const n = document.querySelectorAll('#game-grid .game-card, #game-grid .series-card').length; return [n > 0, 'cards=' + n]; })()")
    STEPS.append((f"games-{tab}", f"openCategory('{tab}')", 5000, check))
STEPS.append(("games-standalone-steam", "openCategory('standalone'); switchStandaloneSubTab('steam', document.querySelector('[data-sub=steam]'))", 5000,
              "(function(){ const n = document.querySelectorAll('#game-grid .game-card, #game-grid .series-card').length; return [n > 0, 'cards=' + n]; })()"))
for tab in MEDIA:
    STEPS.append((f"media-{tab}",
                  f"if (activePrimarySection !== 'media') switchToMediaSection(); switchMediaTab('{tab}', document.getElementById('media-tab-{tab}'))",
                  15000,
                  f"(function(){{ const v = document.getElementById('media-{tab}-view'); "
                  f"return [!!v && v.style.display === 'block' && v.innerText.trim().length > 20, "
                  f"'badge=' + document.getElementById('total-badge').textContent + ' | stats=' + document.getElementById('media-sub-stats').textContent]; }})()"))
STEPS.append(("privacy-modal", "openNsfwModal()", 3000,
              "[document.getElementById('nsfw-lock-modal').style.display === 'flex', 'nsfw modal']"))
STEPS.append(("library-picker", "closeNsfwModal(); openLibraryPicker('library-add-path')", 8000,
              "(function(){ const n = document.querySelectorAll('#library-picker-list .lib-picker-item').length; "
              "const m = document.getElementById('library-picker-modal'); const cs = getComputedStyle(m); const r = m.getBoundingClientRect(); "
              "const top = document.elementFromPoint(640, 400); "
              "return [m.style.display === 'flex' && n > 0, 'dirs=' + n + ' display=' + cs.display + ' z=' + cs.zIndex + ' pos=' + cs.position + "
              "' rect=' + [r.x, r.y, r.width, r.height].map(Math.round) + ' center=' + (top ? (top.id || top.className) : 'none') + ' parent=' + m.parentElement.tagName]; })()"))
STEPS.append(("library-preview", "closeLibraryPicker(); document.getElementById('library-add-path').value = '/tmp/omni-ui-smoke/fake_library'; libraryPreview()", 8000,
              "(function(){ const t = document.getElementById('library-add-preview').innerText; return [t.includes('骨架目录'), t.slice(0, 80)]; })()"))


class Page(QWebEnginePage):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def javaScriptConsoleMessage(self, level, msg, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.sink.append(f"{os.path.basename(source or 'inline')}:{line}  {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/omni-ui-smoke")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    proc = rs.start_server(legacy=False)
    errors, results = [], []
    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.setPage(Page(errors))
    view.resize(1280, 800)
    view.show()

    queue = list(STEPS)

    def shot(name):
        view.grab().save(os.path.join(args.out, f"{name}.png"))

    def run_next():
        if not queue:
            finish()
            return
        name, js, wait, check = queue.pop(0)
        n_err = len(errors)
        view.page().runJavaScript(js)

        deadline = [wait]

        def verify():
            def got(res):
                ok, info = (res or [False, "no result"])
                if not ok and deadline[0] > 0:
                    deadline[0] -= 500
                    QTimer.singleShot(500, verify)
                    return
                QTimer.singleShot(600, lambda: finish_step(ok, info))

            def finish_step(ok, info):
                new_errors = errors[n_err:]
                results.append((name, bool(ok) and not new_errors, info, new_errors))
                shot(name)
                run_next()
            view.page().runJavaScript(check, got)
        QTimer.singleShot(500, verify)

    def finish():
        rs.stop_server(proc)
        failed = 0
        for name, ok, info, errs in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name:28s} {info}")
            for e in errs:
                print(f"        JS error: {e}")
            failed += not ok
        print(f"\n{len(results)} steps, {failed} failed; screenshots in {args.out}")
        app.exit(1 if failed else 0)

    # offscreen 软件渲染下带 backdrop-filter 的 fixed 弹窗截不出来（页面本身正常），截图时关掉它
    shot_css = ("var st=document.createElement('style');"
                "st.textContent='.manga-modal-backdrop{backdrop-filter:none!important}';document.head.appendChild(st);")
    view.loadFinished.connect(lambda ok: (view.page().runJavaScript(shot_css), QTimer.singleShot(3000, run_next)))
    view.load(QUrl(f"http://127.0.0.1:{rs.PORT}/hub.html"))
    code = app.exec()
    rs.stop_server(proc)
    sys.exit(code)


if __name__ == "__main__":
    main()
