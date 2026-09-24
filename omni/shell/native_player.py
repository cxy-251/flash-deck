"""
native_player.py - 本机播放原生解码通道

背景：QtWebEngine 内置的解码器是阉割版 Chromium 自带的那份，没有 H.264/AAC（专利编码，
Chromium 开源发布版本为了不背专利费责任故意不带）。但同一个 PyQt6 安装包里的 QtMultimedia
模块用的是另一份完整 ffmpeg，什么都能解——已经实测验证过（H.264 视频、AAC 音频都正常）。

这个模块就是"本机播放走 QtMultimedia，不用转码"的实现：
- 只覆盖本机（同一个进程内嵌的 QWebEngineView 所在的这个窗口）播放。
- 局域网/远程设备访问的是 main.py 现有的 /api/shortvideo/stream、/api/audio/stream
  这两条 HTTP 接口，用的是它们自己那台设备上的正常浏览器解码原始文件，这些设备压根
  拿不到 qt.webChannelTransport（那是 QtWebEngine 专属的本机桥接通道），天然摸不到这条
  原生播放路径，跟这个模块完全无关、不受影响。
- 不开新窗口：原生播放器是盖在 QWebEngineView 上面的一个悬浮控件（同一个顶层窗口的子
  控件），跟这个窗口右上角那个悬浮胶囊控制台是同一个套路（QWidget(self)、手动 geometry、
  resizeEvent 里跟着窗口一起变化），关掉播放器就把它藏起来，网页恢复可见、状态不受影响。

跟网页那边（hub.js）的联动：本模块只管"播放当前给它的这一个文件"，上一条/下一条/删除这些
"接下来放哪一条"的判断，全部丢回网页那边处理（网页那边本来就有完整的列表/当前下标状态，
不用在 Python 这边再重复维护一份）——原生播放器按钮被点了，只是把这个动作转发回网页
（通过 QWebEngineView.page().runJavaScript() 调用网页里对应的 JS 函数），网页算出"下一条
该放哪个文件"之后，再通过 QWebChannel 桥接对象重新喊一次 Python 播放。

播放速度/睡眠定时/章节跳转这几个不需要知道"列表"的功能，直接在 Qt 这边自己闭环，不用
麻烦网页。章节数据由网页在喊播放时一并传过来（audio_service 本来就带 chapters 字段）。
"""
import json
import time
from PyQt6.QtCore import Qt, QUrl, QObject, QEvent, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QComboBox, QFrame
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

SPEEDS = [1.0, 1.25, 1.5, 1.75, 2.0]
SLEEP_MINS = [0, 15, 30, 45, 60]   # 0 = 关闭


def _fmt_ms(ms: int) -> str:
    """把毫秒数格式化成 "h:mm:ss"（不足一小时省略小时位）的进度条文案。

    Args:
        ms: 毫秒数，负数按 0 处理。

    Returns:
        str: 格式化后的时间文本。
    """
    s = max(0, int(ms)) // 1000
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_CONTROL_QSS = """
    QWidget#dyaCtrlBar { background: rgba(10,10,12,0.90); }
    QPushButton { color:#fff; background:rgba(255,255,255,0.12); border:none; border-radius:6px;
                  padding:6px 12px; font-size:13px; }
    QPushButton:hover { background:rgba(255,255,255,0.26); }
    QPushButton:pressed { background:rgba(255,255,255,0.36); }
    QPushButton:checked { background:#58a6ff; color:#04101d; }
    QLabel { color:#e6e6e6; font-size:12px; }
    QComboBox { color:#fff; background:rgba(255,255,255,0.12); border:none; border-radius:6px; padding:4px 8px; }
    QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,0.25); border-radius:2px; }
    QSlider::handle:horizontal { width:13px; margin:-5px 0; background:#58a6ff; border-radius:6px; }
    QSlider::sub-page:horizontal { background:#58a6ff; border-radius:2px; }
"""


class NativePlayerWidget(QWidget):
    """本机原生播放浮层：视频模式铺满+底部悬浮控制条；音频模式隐藏视频区，中间显示大标题/
    封面占位，控制条额外带倍速/睡眠定时/章节跳转（这几个不用惊动网页，Qt 自己闭环）。"""

    closed = pyqtSignal()
    prevRequested = pyqtSignal()
    nextRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    likeToggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        """构造播放器悬浮控件并组装好视频区/控制条/所有信号连接，初始处于隐藏状态。

        Args:
            parent: 父级 QWidget（通常是承载 QWebEngineView 的顶层窗口），用于把播放器
                以浮层形式叠加在网页视图上面。
        """
        super().__init__(parent)
        self.setStyleSheet("background:#000;")
        self.is_audio_mode = False   # main.py 的 resizeEvent 据此决定摆成全屏还是底部细条
        self.loop_mode = "list"      # "list" | "single"
        self.is_liked = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)

        # 切视频时的过渡层：之前的做法是切换时把 video_widget 藏起来、换成这个黑底箭头
        # （共享同一个布局位置，只显示一个）——实测这样还是会露一下底下的网页，很可能是
        # QVideoWidget 这类要用显卡渲染的控件，底层是一块跟 Qt 普通控件"隐藏就完全不画"
        # 不是一回事的原生渲染表面，"隐藏它"这个动作本身没法保证完全盖住。
        # 现在改成：video_widget 全程保持显示状态、切视频时都不再隐藏它，这个过渡层改成
        # 手动摆放位置、悬浮盖在它上面的独立图层（不进 outer 那个共享布局），要遮就直接
        # raise_() 到最上面显示，不去碰 video_widget 的显示/隐藏状态——这样不管 video_widget
        # 底层用的是什么渲染方式，只要这一层纯 Qt 控件盖住了，就不可能透出下面的东西。
        self.transition_label = QLabel("", self)
        self.transition_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.transition_label.setStyleSheet("QLabel{background:#000;color:#58a6ff;font-size:64px;}")
        self.transition_label.hide()
        self._trans_timeout = QTimer(self)
        self._trans_timeout.setSingleShot(True)
        self._trans_timeout.timeout.connect(self._end_transition)

        self.controls = QWidget(self)
        self.controls.setObjectName("dyaCtrlBar")
        self.controls.setStyleSheet(_CONTROL_QSS)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("QLabel{font-size:13px;font-weight:600;color:#fff;}")

        self.btn_prev = QPushButton("⬅")
        self.btn_play = QPushButton("⏸")
        self.btn_next = QPushButton("➡")
        self.btn_loop = QPushButton("🔁")
        self.btn_loop.setToolTip("循环模式：列表循环（点击切换为单片循环）")
        self.btn_like = QPushButton("🤍")
        self.btn_like.setToolTip("点赞")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.time_label = QLabel("0:00 / 0:00")
        self.btn_delete = QPushButton("🗑")
        self.btn_close = QPushButton("✕ 关闭")

        # 音频专属：倍速 / 睡眠定时 / 章节——这几个不用麻烦网页，Qt 自己闭环
        self.btn_speed = QPushButton("1.0x")
        self.btn_sleep = QPushButton("⏳ 定时")
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(120)
        self._speed_idx = 0
        self._sleep_idx = 0
        self._chapters = []
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._on_sleep_fire)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_play)
        btn_row.addWidget(self.btn_next)
        btn_row.addWidget(self.btn_loop)
        btn_row.addWidget(self.btn_like)
        btn_row.addWidget(self.seek, 1)
        btn_row.addWidget(self.time_label)
        btn_row.addWidget(self.chapter_combo)
        btn_row.addWidget(self.btn_speed)
        btn_row.addWidget(self.btn_sleep)

        # 删除按钮离前面这些常用按钮拉开一点距离（加个分隔线），免得手滑误触。
        # 视频播放界面干脆不放删除按钮（删除放在网格卡片上就够了，播放器里点惯了容易
        # 手滑删错）——只有音频模式才显示这一段，见 play_local() 里的 setVisible。
        btn_row.addSpacing(18)
        self.delete_divider = QFrame()
        self.delete_divider.setFrameShape(QFrame.Shape.VLine)
        self.delete_divider.setStyleSheet("background: rgba(255,255,255,0.22); max-width: 1px; min-width: 1px;")
        btn_row.addWidget(self.delete_divider)
        btn_row.addSpacing(10)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_close)

        ctrl_layout = QVBoxLayout(self.controls)
        ctrl_layout.setContentsMargins(14, 8, 14, 10)
        ctrl_layout.setSpacing(6)
        ctrl_layout.addWidget(self.title_label)
        ctrl_layout.addLayout(btn_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.video_widget, 1)
        outer.addWidget(self.controls, 0)
        # transition_label 不进这个布局——它是悬浮在 video_widget 上面的独立图层，见上面注释

        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_prev.clicked.connect(lambda: self._trigger_nav(-1))
        self.btn_next.clicked.connect(lambda: self._trigger_nav(1))
        self.btn_loop.clicked.connect(self._toggle_loop)
        self.btn_like.clicked.connect(self._toggle_like)
        self.btn_close.clicked.connect(self.close_player)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        self.btn_speed.clicked.connect(self._cycle_speed)
        self.btn_sleep.clicked.connect(self._cycle_sleep)
        self.chapter_combo.activated.connect(self._on_chapter_selected)

        self._seeking = False
        self.seek.sliderPressed.connect(lambda: setattr(self, '_seeking', True))
        self.seek.sliderReleased.connect(self._on_seek_release)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_error)

        # 视频区域左右滑一下切上一条/下一条（触屏/触控板都走这条，Qt 默认会把触摸事件
        # 合成成鼠标事件）。装在 video_widget 上而不是整个控件，这样不会跟底部控制条的
        # 按钮点击冲突——按钮本来就是各自的子控件，鼠标事件不会先经过这里。
        self._drag_start = None
        self._drag_start_t = 0.0
        self.video_widget.installEventFilter(self)

    def _toggle_loop(self):
        """在"列表循环"和"单片循环"之间切换，同步按钮图标与提示文案。"""
        if self.loop_mode == "list":
            self.loop_mode = "single"
            self.btn_loop.setText("🔂")
            self.btn_loop.setToolTip("循环模式：单片循环（点击切换为列表循环）")
        else:
            self.loop_mode = "list"
            self.btn_loop.setText("🔁")
            self.btn_loop.setToolTip("循环模式：列表循环（点击切换为单片循环）")

    def _toggle_like(self):
        """点击点赞按钮：本地状态取反、刷新按钮图标，并把结果通过 likeToggled 信号通知网页那边。"""
        self.is_liked = not self.is_liked
        self.btn_like.setText("❤️" if self.is_liked else "🤍")
        self.btn_like.setToolTip("取消点赞" if self.is_liked else "点赞")
        self.likeToggled.emit(self.is_liked)

    def set_liked(self, liked: bool):
        """由外部（网页那边喊播放时）设置当前条目的点赞状态，只更新按钮外观，不发信号。

        Args:
            liked: 是否已点赞。
        """
        self.is_liked = bool(liked)
        self.btn_like.setText("❤️" if self.is_liked else "🤍")
        self.btn_like.setToolTip("取消点赞" if self.is_liked else "点赞")

    def eventFilter(self, obj, event):
        """监听视频区域的鼠标按下/松开，识别"快速横向滑动"手势触发上一条/下一条。

        Args:
            obj: 事件来源控件。
            event: Qt 事件对象。

        Returns:
            bool: 识别为滑动手势并已处理时返回 True（拦截事件），否则交给父类处理。
        """
        if obj is self.video_widget:
            et = event.type()
            if et == QEvent.Type.MouseButtonPress:
                pos = event.position() if hasattr(event, 'position') else event.pos()
                self._drag_start = (pos.x(), pos.y())
                self._drag_start_t = time.time()
            elif et == QEvent.Type.MouseButtonRelease and self._drag_start is not None:
                pos = event.position() if hasattr(event, 'position') else event.pos()
                dx = pos.x() - self._drag_start[0]
                dy = pos.y() - self._drag_start[1]
                dt = time.time() - self._drag_start_t
                self._drag_start = None
                # 横向位移够大、竖向漂移不大、松手够快，才算"滑一下"，避免跟普通点击混淆
                if abs(dx) > 80 and abs(dy) < 60 and dt < 0.6:
                    self._trigger_nav(1 if dx < 0 else -1)
                    return True
        return super().eventFilter(obj, event)

    # ---- 切换动效：滑动/按上一条下一条时统一走这里 ----

    def _trigger_nav(self, direction: int):
        """播放切换动效并把上一条/下一条请求转发给网页那边（列表状态由网页维护）。

        Args:
            direction: 正数表示下一条，负数表示上一条。
        """
        self._start_transition(direction)
        if direction > 0:
            self.nextRequested.emit()
        else:
            self.prevRequested.emit()

    def _position_transition_overlay(self):
        """让切换动效的方向箭头遮罩层跟视频区域（不含底部控制条）保持同样大小和位置。"""
        # 悬浮遮罩要盖住的是"视频区域"这一块，不含底部控制条
        video_h = max(0, self.height() - self.controls.height())
        self.transition_label.setGeometry(0, 0, self.width(), video_h)

    def _start_transition(self, direction: int):
        """显示切换方向箭头遮罩，全程保持完全不透明（音频模式下不显示）。

        之前这里带一个 320ms 淡到 25% 不透明度的动画，但新视频源加载/解码经常撑不到
        这么快（下面 1500ms 的超时兜底本身就承认了最坏情况要等这么久）——遮罩淡成
        接近透明之后，新内容却还没画出来，底下的东西就会透出来，这正是切视频"闪一下"
        的根因。所以改成不淡出：新内容没真正开始播放（_end_transition 触发）之前，
        遮罩死死保持完全不透明，宁可牺牲一点淡出的视觉效果，也不允许"不确定期"透光。

        Args:
            direction: 正数显示右箭头（下一条），负数显示左箭头（上一条）。
        """
        if self.is_audio_mode:
            return
        self.transition_label.setText('➡' if direction > 0 else '⬅')
        self._position_transition_overlay()
        self.transition_label.raise_()
        self.transition_label.show()
        # 保险：万一新视频一直没触发 PlayingState（比如文件有问题），别让箭头卡死一直挡着
        self._trans_timeout.start(1500)

    def _end_transition(self):
        """结束切换遮罩，直接隐藏（正常播放开始或超时兜底都会调用这个）。"""
        self._trans_timeout.stop()
        self.transition_label.hide()

    def resizeEvent(self, event):
        """窗口尺寸变化时，若切换动效遮罩正显示着，跟着重新定位。

        Args:
            event: Qt 的 resize 事件对象。
        """
        super().resizeEvent(event)
        if self.transition_label.isVisible():
            self._position_transition_overlay()

    def play_local(self, full_path: str, is_audio: bool, title: str = "", chapters=None, is_liked: bool = False):
        """加载并播放一个本地文件，按 is_audio 切换视频/音频两种界面布局。

        Args:
            full_path: 本地文件的绝对路径。
            is_audio: True 为音频模式（显示章节/倍速/睡眠定时/删除等控件），False 为视频模式。
            title: 显示标题（音频模式下居中大字展示）。
            chapters: 章节列表，每项含 title/index 等字段，音频模式下填充章节下拉框。
            is_liked: 该条目当前是否已点赞，用于同步点赞按钮外观。
        """
        self.is_audio_mode = is_audio
        self.chapter_combo.setVisible(is_audio)
        self.btn_speed.setVisible(is_audio)
        self.btn_sleep.setVisible(is_audio)
        self.btn_delete.setVisible(is_audio)
        self.delete_divider.setVisible(is_audio)
        self.btn_like.setVisible(not is_audio)
        self.set_liked(is_liked)
        self.title_label.setText(title or "")

        # video_widget 只在音频/视频"模式"切换（不常发生）时才会真的变化；同模式下的
        # 上一条/下一条切换完全不碰它的显示状态——遮罩层是独立悬浮的，不需要靠隐藏
        # video_widget 来配合，见上面 _start_transition/_end_transition 的注释。
        self.video_widget.setVisible(not is_audio)
        if is_audio:
            self._end_transition()

        self._speed_idx = 0
        self.btn_speed.setText("1.0x")
        self._chapters = chapters or []
        self.chapter_combo.clear()
        if self._chapters:
            for ch in self._chapters:
                self.chapter_combo.addItem(f"{ch.get('title') or ('第' + str(ch.get('index', '')) + '章')}")

        self.player.setSource(QUrl.fromLocalFile(full_path))
        self.player.setPlaybackRate(SPEEDS[self._speed_idx])
        self.player.play()

    # ---- 播放/暂停/进度 ----

    def _toggle_play(self):
        """播放/暂停按钮：按当前播放状态取反。"""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state(self, state):
        """QMediaPlayer 播放状态变化回调：同步播放/暂停按钮图标，开始播放时收起切换动效。

        Args:
            state: QMediaPlayer.PlaybackState 枚举值。
        """
        self.btn_play.setText("⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._end_transition()   # 新视频真的开始出画面了，把过渡箭头收掉、露出真实画面

    def _on_media_status(self, status):
        """QMediaPlayer 媒体状态变化回调：播放到结尾时按循环模式处理（重播或请求下一条）。

        Args:
            status: QMediaPlayer.MediaStatus 枚举值。
        """
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.loop_mode == "single":
                self.player.setPosition(0)
                self.player.play()
            else:
                self.nextRequested.emit()   # 播完自动连播，跟网页那边体验一致

    def _on_error(self, error, error_string):
        """QMediaPlayer 出错回调：把错误信息截短显示在时间标签上。

        Args:
            error: QMediaPlayer.Error 枚举值（未使用，仅用于匹配信号签名）。
            error_string: 错误描述文本。
        """
        if error_string:
            self.time_label.setText(f"⚠️ {error_string[:36]}")

    def _on_position(self, pos):
        """播放进度回调：更新进度条、时间文案，并按当前播放位置高亮对应章节。

        Args:
            pos: 当前播放位置（毫秒）。
        """
        if self._seeking:
            return
        dur = max(1, self.player.duration())
        self.seek.blockSignals(True)
        self.seek.setValue(int(pos / dur * 1000))
        self.seek.blockSignals(False)
        self.time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(self.player.duration())}")
        # 高亮当前章节
        if self._chapters:
            secs = pos / 1000.0
            cur = 0
            for i, ch in enumerate(self._chapters):
                if secs >= ch.get('start', 0):
                    cur = i
            if self.chapter_combo.currentIndex() != cur:
                self.chapter_combo.blockSignals(True)
                self.chapter_combo.setCurrentIndex(cur)
                self.chapter_combo.blockSignals(False)

    def _on_duration(self, dur):
        """媒体总时长变化回调（切换新文件时触发）：刷新时间文案。

        Args:
            dur: 总时长（毫秒）。
        """
        self.time_label.setText(f"{_fmt_ms(self.player.position())} / {_fmt_ms(dur)}")

    def _on_seek_release(self):
        """用户拖动进度条松手后，按滑块位置真正跳转播放进度。"""
        self._seeking = False
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(self.seek.value() / 1000 * dur))

    # ---- 音频专属：倍速 / 睡眠定时 / 章节（自己闭环，不用麻烦网页） ----

    def _cycle_speed(self):
        """倍速按钮：按 SPEEDS 列表循环切到下一档播放速度。"""
        self._speed_idx = (self._speed_idx + 1) % len(SPEEDS)
        rate = SPEEDS[self._speed_idx]
        self.player.setPlaybackRate(rate)
        self.btn_speed.setText(f"{rate:g}x")

    def _cycle_sleep(self):
        """睡眠定时按钮：按 SLEEP_MINS 列表循环切到下一档定时时长（0 表示关闭定时）。"""
        self._sleep_idx = (self._sleep_idx + 1) % len(SLEEP_MINS)
        mins = SLEEP_MINS[self._sleep_idx]
        self._sleep_timer.stop()
        if mins > 0:
            self.btn_sleep.setText(f"⏳ {mins}分")
            self._sleep_timer.start(mins * 60 * 1000)
        else:
            self.btn_sleep.setText("⏳ 定时")

    def _on_sleep_fire(self):
        """睡眠定时到点回调：暂停播放并把定时按钮重置回"关闭"状态。"""
        self.player.pause()
        self._sleep_idx = 0
        self.btn_sleep.setText("⏳ 定时")

    def _on_chapter_selected(self, idx: int):
        """章节下拉框选中回调：跳转播放位置到该章节起始时间。

        Args:
            idx: 选中的章节在 self._chapters 里的下标。
        """
        if 0 <= idx < len(self._chapters):
            start_ms = int(self._chapters[idx].get('start', 0) * 1000)
            self.player.setPosition(start_ms)

    def stop_and_hide(self):
        """停止播放、清空媒体源、停掉所有定时器，但不隐藏控件本身（外部决定何时隐藏/复用）。"""
        self.player.stop()
        self.player.setSource(QUrl())
        self._sleep_timer.stop()
        self._trans_timeout.stop()
        self.transition_label.hide()

    def close_player(self):
        """用户点击关闭按钮：停止播放并发出 closed 信号（外部据此隐藏播放器、恢复网页）。"""
        self.stop_and_hide()
        self.closed.emit()


class PlayerBridge(QObject):
    """暴露给 hub.html 网页 JS 的桥接对象（通过 QWebChannel 注册为 `bridge`）。
    只在本机嵌入的 QWebEngineView 里能拿到（局域网/远程浏览器没有 qt.webChannelTransport），
    网页那边据此判断"这是本机，走原生播放"还是"这是远程，走 HTTP 流"。"""

    def __init__(self, main_window):
        """保存主窗口引用，播放请求最终都转发给它的 show_native_player()/hide_native_player()。

        Args:
            main_window: 承载原生播放器控件的主窗口实例。
        """
        super().__init__(main_window)
        self.win = main_window

    @pyqtSlot(str, str, str)
    def playShortVideo(self, platform: str, rel_path: str, title: str):
        """网页 JS 调用：播放一条本机短视频。

        Args:
            platform: 平台名（kuaishou/douyin/tiktok）。
            rel_path: 视频相对路径。
            title: 展示标题，为空时回退成文件名。
        """
        try:
            from omni.features.shortvideo import service as shortvideo_service
            full_p = shortvideo_service.find_shortvideo_file(platform, rel_path)
            is_liked = shortvideo_service.is_shortvideo_liked(platform, rel_path)
        except Exception:
            full_p = None
            is_liked = False
        if full_p:
            self.win.show_native_player(full_p, is_audio=False, title=title or rel_path.rsplit('/', 1)[-1], is_liked=is_liked)

    @pyqtSlot(str, str, str, str)
    def playAudio(self, rel_path: str, nsfw_flag: str, title: str, chapters_json: str):
        """网页 JS 调用：播放一条本机音频（有声书/音声）。

        Args:
            rel_path: 音频相对路径。
            nsfw_flag: '1' 表示走 NSFW 库查找，其余值走标准库。
            title: 展示标题，为空时回退成文件名。
            chapters_json: 章节数据的 JSON 字符串（可为空），解析失败按无章节处理。
        """
        try:
            from omni.features.audio import service as audio_service
            full_p = audio_service.find_audio_file(rel_path, is_nsfw=(nsfw_flag == '1'))
        except Exception:
            full_p = None
        if full_p:
            try:
                chapters = json.loads(chapters_json) if chapters_json else []
            except Exception:
                chapters = []
            self.win.show_native_player(full_p, is_audio=True, title=title or rel_path.rsplit('/', 1)[-1], chapters=chapters)

    @pyqtSlot()
    def closePlayer(self):
        """网页 JS 调用：关闭原生播放器，恢复显示网页。"""
        self.win.hide_native_player()
