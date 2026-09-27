"""
native_matrix_player.py - 短视频多联放映（本机原生多路播放）

2 屏 / 3 屏并排，每屏一个独立的 QMediaPlayer（Qt 的 FFmpeg 后端，能用 VA-API 就走硬解），
独立选频道、独立顺序/随机、独立静音（静音跟着这一屏走，换下一条也保持）。

「焦点屏」是整个放映的核心：鼠标在某屏停留一会儿（路过不算）或点中它、或按 1/2/3，它就成为焦点。
  - 控件：每屏不放任何控件（画面尽量大，3 屏时竖屏视频正好铺满），顶栏只有一套控件，
    操作的永远是焦点屏；换焦点时顶栏刷新成那一屏的状态。
  - 声音：手动静音 OR（开了焦点出声 且 不是焦点屏）→ 不出声。手动静音的屏永远不出声，
    焦点出声只在没静音的屏之间挑一个。

每屏的声音可以换成「音声」分区的音频（🎬/🎧）：音声用一个只出声的 QMediaPlayer，跟视频各播各的
（视频一条条换，音声连着往下放）；这一屏听不到或视频被暂停时，音声暂停，回来接着放。
音声的播放逻辑和控件跟本机音声专区是同一个组件（audio_controls.AudioSession / AudioControlBar），
断点续听也是同一份；焦点屏用音声时顶栏展开第二行放这套控件，多联只多一个「范围」按钮。
用音声时视频原声的音轨直接关掉，不解码。横屏视频在竖长分屏里只剩一条缝，跳过。

跟 native_player.py 同一个套路：MainWindow 的子控件，盖在网页上面。网页那边先有一个设置页
（选几屏、每屏的频道/随机/静音/声源，存进 shortvideo_matrix 的配置），点「开始播放」才调
start_matrix()；这里改动的设置也写回同一份配置，退出后网页设置页看到的就是最新的。

同一个 Omni 进程里退出再进来，每屏接着上次的频道 / 顺序 / 第几条 / 第几秒（音声同理），
只有在设置页里改了频道或随机的那屏才重新开始；进来时一律是暂停状态，按 ⏯ / 空格 开播。
退出时解码器和文件照样释放，记住的只是位置。退出有两种（closed 信号带原因给网页）：
  collapse ⤓ 收起：回到进多联之前的页面（比如去开一局游戏），再点多联标签直接回到播放器；
  settings ⚙ 设置：回到网页设置页。

顶栏默认自动隐藏：进来先显示 3 秒，之后鼠标移到最顶端才出来，移开 1.5 秒收起（下拉 / 菜单 / 搜索框
打开时不收）；📌 固定后一直显示。顶栏是悬浮的，盖在三屏上面，出没不改变播放区大小。
视频是原生子窗口（QVideoWidget 里面是 QWindowContainer），普通控件盖不住它，所以顶栏也设成原生
窗口（WA_NativeWindow），显示时 raise_() 到视频上层。

键盘（Steam Input 可映射）：Tab 显示 / 收起顶栏，1/2/3 选焦点屏，空格 暂停/继续，←/→ 上/下一条，M 静音，Esc 退出。
"""
import random
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QUrl, QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QComboBox,
                             QFrame, QSizePolicy, QCompleter, QProgressBar)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from omni.features.audio import playback, service as audio_service
from omni.features.shortvideo import service as sv
from omni.features.shortvideo_matrix import service as mx
from omni.shell.audio_controls import AudioControlBar, AudioSession
from omni.shell.icons import ACCENT, AUDIO, FG, LIKE, TIP_QSS, icon, install_tips, set_icon


# Qt 样式表不认 CSS 的 .class 选择器，高亮一律用动态属性 [active="true"]，改完属性要 polish 一下才生效
_QSS = """
    QWidget { color:#e6edf3; font-size:12px; }
    QWidget#matrixTopBar { background:#0d1015; border-bottom:1px solid #1c2129; }
    /* 图标按钮：扁平、圆形，悬停时浮出淡底（YouTube / 音乐播放器那种） */
    QPushButton, QToolButton { color:#e6edf3; background:transparent; border:none; border-radius:15px; padding:0 6px; }
    QPushButton:hover, QToolButton:hover { background:rgba(255,255,255,0.12); }
    QPushButton:pressed, QToolButton:pressed { background:rgba(255,255,255,0.20); }
    QPushButton[active="true"] { background:rgba(88,166,255,0.16); }
    QToolButton::menu-indicator { image:none; }
    QComboBox { background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.10); border-radius:16px;
                padding:4px 12px; min-height:24px; }
    QComboBox:hover { background:rgba(255,255,255,0.11); }
    QComboBox::drop-down { border:none; width:22px; }
    QComboBox QAbstractItemView { background:#161b22; color:#e6edf3; border:1px solid #30363d; border-radius:8px;
                                  selection-background-color:#1f6feb; padding:4px; }
    QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,0.18); border-radius:2px; }
    QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0; background:#fff; border-radius:6px; }
    QSlider::sub-page:horizontal { background:#d2a8ff; border-radius:2px; }
    QMenu { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:4px; }
    QMenu::item { padding:6px 14px 6px 8px; border-radius:6px; }
    QMenu::item:selected { background:rgba(255,255,255,0.10); }
    QFrame#matrixSlot { background:#000; border:2px solid #1c2129; border-radius:8px; }
    QFrame#matrixSlot[active="true"] { border-color:#58a6ff; }
    QProgressBar { background:#161b22; border:none; }
    QProgressBar::chunk { background:#58a6ff; }
    QLabel#slotTag { color:#58a6ff; font-weight:600; font-size:13px; padding:0 4px; }
    QLabel#slotDim { color:#8b949e; font-size:11px; }
    QLabel#audioTime { color:#c9d1d9; font-size:11px; }
    QFrame#barSep { background:#30363d; }
    QWidget#audioBox { background:rgba(210,168,255,0.07); border:1px solid rgba(210,168,255,0.18); border-radius:18px; }
    QWidget#audioBox QPushButton[active="true"] { background:rgba(210,168,255,0.16); }
    QPushButton#scopeBtn { min-width:96px; max-width:170px; text-align:left; padding:0 12px 0 8px;
                           background:rgba(210,168,255,0.10); border-radius:15px; }
    QPushButton#scopeBtn:hover { background:rgba(210,168,255,0.20); }
"""


def _set_active_prop(w: QWidget, on: bool) -> None:
    w.setProperty("active", "true" if on else "false")
    w.style().unpolish(w)
    w.style().polish(w)


def _toggle_icon(btn, on: bool, name: str, name_on: str = "", color: str = ACCENT) -> None:
    """开关按钮：开着时换成 name_on（没给就同一个图标）并染成强调色 + 淡底色。"""
    set_icon(btn, (name_on or name) if on else name, color if on else FG)
    _set_active_prop(btn, on)


def _no_width_hint(w: QWidget) -> None:
    """宽度不跟内容走：视频控件会按当前视频的宽高比报 sizeHint、长标题会报很宽的 sizeHint，
    放进 QHBoxLayout 后每换一条视频三屏就重新分一次宽度。三屏宽度只由布局等分决定。"""
    w.setSizePolicy(QSizePolicy.Policy.Ignored, w.sizePolicy().verticalPolicy())


class MatrixSlotWidget(QFrame):
    """一屏：视频画面 + 底部一条细进度线，没有控件。播放状态和操作都在这里，顶栏只是调用它。"""

    activated = pyqtSignal(int)          # 要成为焦点屏（点击立即；鼠标停留 HOVER_MS 后）
    changed = pyqtSignal(int)            # 顶栏要显示的状态变了（换片、点赞、暂停、声源…）
    settingsChanged = pyqtSignal()       # 频道/随机/静音/声源变了，让容器写回配置

    MAX_SKIP = 5                         # 连续这么多条都放不了就停下，别无限跳
    HOVER_MS = 300                       # 鼠标停留多久才换焦点：去点顶栏时斜着划过别的屏不算

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("matrixSlot")
        _no_width_hint(self)
        self.videos: List[Dict[str, Any]] = []
        self.order: List[int] = []       # 播放顺序（videos 的下标）；随机时是洗过牌的
        self.pos = 0                     # 当前在 order 里的位置
        self.channel_id = "all"
        self.shuffle = False
        self._skips = 0
        self._check_orientation = False
        self.user_muted = False          # 这一屏的静音
        self.focus_silenced = False      # 焦点出声模式下不是焦点屏
        self.user_paused = False         # 用户暂停了这一屏（换片时播放器短暂 Stopped 不算）
        self._seek_on_load = 0           # 恢复进度：片源载入后跳到这里（毫秒）
        self._resume_ms = 0              # stop() 时记下的位置，下次打开接着放
        self._session: Optional[tuple] = None    # 视频列表是按什么设置取的（频道, 随机）；对不上就重新取
        self._tracks_scope: Optional[str] = None # 音声列表是按哪个范围取的

        # 音声（代替视频原声）
        self.sound = "video"             # video | audio
        self.audio_scope = "all"
        self.tracks: List[Dict[str, Any]] = []   # 范围里的音声（自然顺序；随机模式下一首随机挑）
        self.apos = 0
        self._askips = 0

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.aplayer = QMediaPlayer(self)
        self.aout = QAudioOutput(self)
        self.aplayer.setAudioOutput(self.aout)
        # 倍速 / 模式 / 章节 / 续听 都在 AudioSession（跟音声专区同一个）
        self.asession = AudioSession(self.aplayer, self)
        self.asession.nextRequested.connect(lambda: self.astep(1, manual=False))
        self.asession.prevRequested.connect(lambda: self.astep(-1))
        self.asession.changed.connect(lambda: self.changed.emit(self.index))

        self.video_widget = QVideoWidget(self)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.installEventFilter(self)   # 点视频画面也算选中这一屏
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        _no_width_hint(self.progress)

        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(0)
        v.addWidget(self.video_widget, 1)
        v.addWidget(self.progress)

        self._hover = QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(self.HOVER_MS)
        self._hover.timeout.connect(lambda: self.activated.emit(self.index))

        p = self.player
        p.positionChanged.connect(self._on_position)
        p.mediaStatusChanged.connect(self._on_status)
        p.playbackStateChanged.connect(lambda _st: self.changed.emit(self.index))
        p.errorOccurred.connect(self._on_error)
        # videoSizeChanged 可能从解码线程发出来，排队回到界面线程再处理（在别的线程里切片源会崩）
        self.video_widget.videoSink().videoSizeChanged.connect(self._on_video_size, Qt.ConnectionType.QueuedConnection)
        self.aplayer.mediaStatusChanged.connect(self._on_astatus)
        self.aplayer.errorOccurred.connect(self._on_aerror)

    # ---- 焦点：点击立即，鼠标停留 HOVER_MS 后 ----
    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover.start()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover.stop()

    def mousePressEvent(self, event):
        self.activated.emit(self.index)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.video_widget and event.type() == QEvent.Type.MouseButtonPress:
            self.activated.emit(self.index)
        return False

    def set_active(self, on: bool):
        _set_active_prop(self, on)

    # ---- 当前条目 ----
    def current_video(self) -> Optional[Dict[str, Any]]:
        return self.videos[self.order[self.pos]] if self.videos else None

    def current_track(self) -> Optional[Dict[str, Any]]:
        return self.tracks[self.apos] if self.tracks and self.aplayer.source().isValid() else None

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ---- 声音 ----
    def set_muted(self, muted: bool, user: bool = False):
        """这一屏的静音。状态挂在 QAudioOutput 上，换片不会重置。"""
        self.user_muted = muted
        self._apply_audio()
        self.changed.emit(self.index)
        if user:
            self.settingsChanged.emit()

    def set_focus_silenced(self, silenced: bool):
        self.focus_silenced = silenced
        self._apply_audio()

    def _apply_audio(self):
        """按 声源 / 静音 / 焦点 / 暂停 决定谁出声：
        原声 → 视频自己的音频输出开关；音声 → 视频原声关掉，音声播放器 放 / 暂停。"""
        heard = not (self.user_muted or self.focus_silenced)
        if self.sound == "video":
            self.audio.setMuted(not heard)
            self.aplayer.pause()
        else:
            self.audio.setMuted(True)
            if heard and not self.user_paused and not self.player.source().isEmpty() and self.tracks:
                if self.aplayer.source().isEmpty():
                    self._load_track()   # 续听位置 AudioSession 从服务器取
                self.aplayer.play()
            else:
                self.aplayer.pause()

    def set_sound(self, sound: str, user: bool = False):
        self.sound = "audio" if sound == "audio" else "video"
        self._set_video_audio_track()
        if self.sound == "audio" and not self.tracks:
            self._load_tracks()
        self._apply_audio()
        self.changed.emit(self.index)
        if user:
            self.settingsChanged.emit()

    def _set_video_audio_track(self):
        """用音声时视频的原声音轨直接关掉（不解码），换回原声再打开。"""
        want = -1 if self.sound == "audio" else 0
        if self.player.activeAudioTrack() != want and (want == -1 or self.player.audioTracks()):
            self.player.setActiveAudioTrack(want)

    # ---- 音声（播放逻辑在 self.asession；这里管列表：范围、上一首 / 下一首、删除） ----
    def set_audio_scope(self, scope: str, user: bool = False):
        self.audio_scope = scope
        self._load_tracks()
        if user:
            self.settingsChanged.emit()

    def _load_tracks(self):
        """换范围：重新取列表，从第一段（随机模式下随机一段）开始，但只在该出声时才真的播。"""
        self.tracks = mx.get_audio_tracks(self.audio_scope)
        self._tracks_scope = self.audio_scope
        self.apos = random.randrange(len(self.tracks)) if self.tracks and self.asession.mode == "random" else 0
        self._askips = 0
        self.asession.clear()
        self._apply_audio()
        self.changed.emit(self.index)

    def _load_track(self):
        it = self.tracks[self.apos]
        path = mx.resolve_track(it)
        if path:
            self.asession.load(path, playback.progress_key(it["rel_path"], bool(it.get("is_nsfw"))),
                               it.get("title") or "", it.get("chapters"))
        else:
            self._askip_broken()
        self.changed.emit(self.index)

    def astep(self, delta: int, manual: bool = True):
        """下一首按播放模式挑（跟音声专区一样）：随机 → 随机一段；其它 → 按列表顺序。"""
        n = len(self.tracks)
        if not n:
            return
        if manual:
            self._askips = 0
        if delta > 0 and self.asession.mode == "random" and n > 1:
            self.apos = random.choice([k for k in range(n) if k != self.apos])
        else:
            self.apos = (self.apos + delta) % n
        self._load_track()
        self._apply_audio()

    def delete_current_track(self) -> bool:
        """当前这段移到回收站（gio trash），从列表里拿掉并接着放下一段。"""
        it = self.current_track()
        if not it or not audio_service.trash_audio_file(it["rel_path"], is_nsfw=bool(it.get("is_nsfw"))):
            return False
        self.asession.clear()
        self.tracks.pop(self.apos)
        if self.tracks:
            self.apos %= len(self.tracks)
            self._apply_audio()
        self.changed.emit(self.index)
        return True

    def _askip_broken(self):
        self._askips += 1
        if self._askips > min(self.MAX_SKIP, len(self.tracks)):
            self.aplayer.stop()
            return
        QTimer.singleShot(300, lambda: self.astep(1, manual=False))

    def _on_astatus(self, status):
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._askips = 0

    def _on_aerror(self, error, _msg=""):
        if error != QMediaPlayer.Error.NoError:
            self._askip_broken()

    # ---- 频道与视频 ----
    def set_shuffle(self, on: bool, user: bool = False):
        """切随机/顺序：当前这条接着放，只重排后面的顺序。"""
        self.shuffle = on
        if self.videos:
            current = self.order[self.pos]
            self._make_order()
            self.pos = self.order.index(current)
        self.changed.emit(self.index)
        if user:
            self.settingsChanged.emit()

    def _make_order(self):
        self.order = list(range(len(self.videos)))
        if self.shuffle:
            random.shuffle(self.order)

    def load_channel(self, channel_id: str):
        self.channel_id = channel_id
        self.videos = mx.get_channel_videos(channel_id)
        self._session = (channel_id, self.shuffle)
        self._resume_ms = 0
        self._make_order()
        self.pos = 0
        self._skips = 0
        self._play_current()

    def resume_or_load(self):
        """打开放映 / 3 屏切回来：列表还是按同样设置取的就接着上次的位置，否则重新取。"""
        if self.videos and self._session == (self.channel_id, self.shuffle):
            self._play_current(self._resume_ms)
            self._resume_ms = 0
        else:
            self.load_channel(self.channel_id)

    def _play_current(self, start_ms: int = 0):
        it = self.current_video()
        if not it:
            self.stop()
            self.video_widget.setToolTip("这个频道没有视频")
            self.changed.emit(self.index)
            return
        self.video_widget.setToolTip(f"{it.get('folder') or ''}\n{it.get('title') or ''}")
        path = mx.resolve_file(it)
        if not path:
            self._skip_broken()
            return
        self._check_orientation = not it.get("width")   # 扫描时没拿到宽高的，等解码出尺寸再判横竖
        self._seek_on_load = start_ms
        self.player.setSource(QUrl.fromLocalFile(path))
        if self.user_paused:
            self.player.pause()      # 暂停着换片：载入并停在第一帧
        else:
            self.player.play()
        self.changed.emit(self.index)

    def _skip_broken(self):
        """当前条放不了：跳下一条；连续 MAX_SKIP 条都不行就停，别在坏列表上无限空转。"""
        self._skips += 1
        if self._skips > min(self.MAX_SKIP, len(self.videos)):
            self.stop()
            self.video_widget.setToolTip("连续多条无法播放，已停止")
            return
        QTimer.singleShot(300, lambda: self.step(1, manual=False))

    def step(self, delta: int, manual: bool = True):
        if not self.videos:
            return
        if manual:
            self._skips = 0
        self.pos = (self.pos + delta) % len(self.videos)
        self._play_current()

    def set_paused(self, paused: bool):
        """暂停/继续这一屏：视频和音声一起停、一起放。"""
        self.user_paused = paused
        if paused:
            self.player.pause()
        elif self.player.source().isEmpty():
            self._play_current()
        else:
            self.player.play()
        self._apply_audio()

    def toggle_like(self):
        it = self.current_video()
        if it:
            sv.toggle_shortvideo_like(it["platform"], it["rel_path"])
            self.changed.emit(self.index)

    def is_liked(self) -> bool:
        it = self.current_video()
        return bool(it) and sv.is_shortvideo_liked(it["platform"], it["rel_path"])

    def stop(self):
        """停解码并释放文件，隐藏/切换布局/退出时调用。先记下位置，下次打开接着放。"""
        if not self.player.source().isEmpty():
            self._resume_ms = self.player.position()
        self.player.stop()
        self.player.setSource(QUrl())
        self.asession.clear()      # 音声进度存服务器（跟音声专区共用），下次接着放
        self.progress.setValue(0)

    # ---- 视频播放器回调 ----
    def _on_position(self, pos: int):
        dur = self.player.duration()
        if dur > 0:
            self.progress.setValue(int(pos / dur * 1000))

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._set_video_audio_track()   # 每换一条视频，音轨选择要重新设
            if self._seek_on_load:
                self.player.setPosition(self._seek_on_load)
                self._seek_on_load = 0
        elif status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._skips = 0          # 真放起来了，坏片计数清零
            if self.sound == "audio" and self.aplayer.source().isEmpty():
                self._apply_audio()  # 第一条视频刚放起来，音声也跟着起
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.step(1, manual=False)

    def _on_video_size(self):
        """扫描时没拿到宽高的那条，解出第一帧尺寸后判横竖：横屏跳过（不算坏片）。"""
        size = self.video_widget.videoSink().videoSize()
        if self._check_orientation and size.width() > 0:
            self._check_orientation = False
            if size.width() > size.height():
                QTimer.singleShot(0, lambda: self.step(1, manual=False))

    def _on_error(self, error, _msg=""):
        if error != QMediaPlayer.Error.NoError:
            self._skip_broken()


class NativeMatrixPlayerWidget(QWidget):
    """多联放映全屏容器：顶栏（全局 + 焦点屏控制台）+ 2/3 个等宽并排、没有控件的 MatrixSlotWidget。"""

    closed = pyqtSignal(str)             # 退出原因：collapse（收起）| settings（去设置页）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("NativeMatrixPlayerWidget{background:#0a0a0c;}" + _QSS + TIP_QSS)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_mode = 3
        self.active = 0
        self.focus_audio = True
        self.bar_pinned = False
        self._bar_hide = QTimer(self)          # 离开顶栏后多久收起
        self._bar_hide.setSingleShot(True)
        self._bar_hide.timeout.connect(self._hide_bar_if_idle)
        self._bar_poll = QTimer(self)          # 看鼠标是不是到了顶端（视频是原生子窗口，收不到它上面的鼠标移动事件）
        self._bar_poll.setInterval(150)
        self._bar_poll.timeout.connect(self._poll_bar)
        self.audio_scopes: List[Dict[str, Any]] = []
        self._build()

    # ---- 界面 ----
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏：第一行 全局 + 焦点屏视频控件；第二行 音声控件（只在焦点屏用音声时展开）
        # 悬浮顶栏：不进布局，手动摆在最上面（_place_bar），原生窗口才能盖住下面的原生视频窗口
        top_bar = self.top_bar = QWidget(self)
        top_bar.setObjectName("matrixTopBar")
        top_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_bar.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        rows = QVBoxLayout(top_bar)
        rows.setContentsMargins(10, 4, 10, 4)
        rows.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(4)
        rows.addLayout(top)

        def button(icon_name, slot, tip=""):
            b = QPushButton()
            set_icon(b, icon_name)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 键盘焦点留给容器，快捷键才不会被按钮吃掉
            b.clicked.connect(slot)
            b.setFixedSize(34, 34)   # 圆形图标按钮
            top.addWidget(b)
            return b

        def sep():
            line = QFrame()
            line.setObjectName("barSep")
            line.setFixedSize(1, 24)
            top.addSpacing(4)
            top.addWidget(line)
            top.addSpacing(4)

        # 全局
        self.btn_l2 = button("view_column_2", lambda: self.set_layout_mode(2, save=True), "2 屏并排")
        self.btn_l3 = button("view_week", lambda: self.set_layout_mode(3, save=True), "3 屏并排")
        self.btn_focus = button("hearing", lambda: self.set_focus_audio(not self.focus_audio, save=True),
                                "焦点出声：开 = 没静音的屏里只有焦点屏出声；关 = 没静音的屏一起出声")
        sep()

        # 焦点屏控制台
        self.lbl_tag = QLabel("屏1")
        self.lbl_tag.setObjectName("slotTag")
        top.addWidget(self.lbl_tag)
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(10)
        self.combo.setMaximumWidth(240)
        # 可输入搜索：打主播名（文件夹名）的任意一段，弹出匹配项，选中即切换
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.lineEdit().setPlaceholderText("搜索主播")
        self.combo.lineEdit().addAction(icon("search", "#8b949e", 18), self.combo.lineEdit().ActionPosition.LeadingPosition)
        completer = QCompleter(self.combo.model(), self.combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.combo.setCompleter(completer)
        self.combo.activated.connect(self._on_combo)   # 只响应用户选择，程序里 setCurrentIndex 不触发
        top.addWidget(self.combo, 1)
        self.btn_prev = button("skip_previous-fill", lambda: self.cur().step(-1), "上一条（←）")
        self.btn_play = button("pause-fill", lambda: self.cur().set_paused(self.cur().is_playing()), "暂停 / 继续（空格）")
        self.btn_next = button("skip_next-fill", lambda: self.cur().step(1), "下一条（→）")
        self.btn_shuffle = button("shuffle", lambda: self.cur().set_shuffle(not self.cur().shuffle, user=True), "视频随机顺序")
        self.btn_like = button("favorite", lambda: self.cur().toggle_like(), "点赞")
        self.btn_mute = button("volume_up-fill", lambda: self.cur().set_muted(not self.cur().user_muted, user=True), "静音（M）")
        self.btn_sound = button("movie-fill", lambda: self.cur().set_sound("video" if self.cur().sound == "audio" else "audio", user=True),
                                "声音：视频原声（点击换成音声）")

        top.addStretch(0)
        sep()

        button("play_pause", self.toggle_all_play, "全部 暂停 / 继续")
        self.btn_pin = button("keep", lambda: self.set_bar_pinned(not self.bar_pinned, save=True),
                              "固定顶栏（关 = 自动隐藏，鼠标移到最顶端才出来；Tab 键也能叫出来）")
        button("settings-fill", lambda: self.close_matrix("settings"), "回到设置页（改每屏的频道 / 声源等）")
        button("keyboard_arrow_down", lambda: self.close_matrix("collapse"),
                       "收起（Esc）：记住各屏位置，回到进来之前的页面；再点多联标签接着看")

        # 第二行：音声 —— 跟本机音声专区同一个控件（AudioControlBar），多联只多一个「范围」
        self.audio_box = QWidget()
        self.audio_box.setObjectName("audioBox")
        self.audio_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ab = QHBoxLayout(self.audio_box)
        ab.setContentsMargins(6, 2, 6, 2)
        ab.setSpacing(6)
        self.lbl_atag = QLabel()
        self.lbl_atag.setPixmap(icon("headphones-fill", AUDIO, 20).pixmap(20, 20))
        ab.addWidget(self.lbl_atag)
        self.btn_scope = QPushButton("📁")
        self.btn_scope.setObjectName("scopeBtn")   # 宽度在 _QSS 里定（样式表的 min-width 会盖过 setMinimumWidth）
        self.btn_scope.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_scope.clicked.connect(self._next_scope)
        ab.addWidget(self.btn_scope)
        self.lbl_atitle = QLabel("")
        self.lbl_atitle.setObjectName("slotDim")
        self.lbl_atitle.setFixedWidth(180)
        ab.addWidget(self.lbl_atitle)
        self.audio_bar = AudioControlBar(self.audio_box, show_play=False)   # 音声跟着那一屏的视频一起停 / 放
        self.audio_bar.sleepFired.connect(lambda: [s.set_paused(True) for s in self.visible_slots()])
        self.audio_bar.deleteRequested.connect(self._delete_track)
        for b in (self.audio_bar.btn_rate, self.audio_bar.btn_mode):
            b.clicked.connect(self.save_config)
        ab.addWidget(self.audio_bar, 1)
        self.audio_box.hide()
        rows.addWidget(self.audio_box)

        area = QWidget(self)
        h = QHBoxLayout(area)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(6)
        self.slots: List[MatrixSlotWidget] = []
        for i in range(3):
            s = MatrixSlotWidget(i, area)
            s.activated.connect(self.activate_slot)
            s.changed.connect(lambda idx: idx == self.active and self.refresh_bar())
            s.settingsChanged.connect(self.save_config)
            h.addWidget(s, 1)   # 等分；配合 _no_width_hint，宽度不再随视频变
            self.slots.append(s)
        root.addWidget(area, 1)
        install_tips(self)

    def cur(self) -> MatrixSlotWidget:
        return self.slots[self.active]

    def visible_slots(self) -> List[MatrixSlotWidget]:
        return self.slots[:self.layout_mode]

    def refresh_bar(self):
        """顶栏显示焦点屏的状态。"""
        s = self.cur()
        self.lbl_tag.setText(f"屏{s.index + 1}")
        i = self.combo.findData(s.channel_id)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        set_icon(self.btn_play, "pause-fill" if s.is_playing() else "play_arrow-fill", size=26)
        _toggle_icon(self.btn_shuffle, s.shuffle, "shuffle")
        liked = s.is_liked()
        set_icon(self.btn_like, "favorite-fill" if liked else "favorite", LIKE if liked else FG)
        if s.user_muted:
            set_icon(self.btn_mute, "volume_off-fill", "#ff7b72")
        elif s.focus_silenced:
            set_icon(self.btn_mute, "volume_mute-fill", "#8b949e")
        else:
            set_icon(self.btn_mute, "volume_up-fill")
        audio = s.sound == "audio"
        set_icon(self.btn_sound, "headphones-fill" if audio else "movie-fill", AUDIO if audio else FG)
        self.btn_sound.setToolTip("声音：音声（点击换回视频原声）" if audio else "声音：视频原声（点击换成音声）")
        _set_active_prop(self.btn_sound, audio)
        self.audio_box.setVisible(audio)
        self._place_bar()   # 音声那一行出没，顶栏高度跟着变
        self.audio_bar.bind(s.asession)
        if audio:
            sc = next((x for x in self.audio_scopes if x["id"] == s.audio_scope), None)
            name = sc["label"] if sc else "全部音声"
            set_icon(self.btn_scope, "library_music", AUDIO, 18, f" {name}")
            self.btn_scope.setToolTip(f"音声范围：{name}（{sc['count'] if sc else '?'} 段）\n点击切到下一个专辑")
            tr = s.current_track()
            title = (tr or {}).get("title") or ("这个范围没有音声" if not s.tracks else "")
            self.lbl_atitle.setText(self.lbl_atitle.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, 176))
            self.lbl_atitle.setToolTip(f"{tr.get('album')} / {title}" if tr else title)

    def _on_combo(self, _i: int):
        cid = self.combo.currentData()
        s = self.cur()
        if cid and cid != s.channel_id:
            s.load_channel(cid)
            self.save_config()
        else:   # 打了字但没选中任何频道：把框里的文字还原成当前频道
            self.combo.setCurrentIndex(max(0, self.combo.findData(s.channel_id)))
        self.setFocus()

    def _next_scope(self):
        ids = [x["id"] for x in self.audio_scopes] or ["all"]
        s = self.cur()
        s.set_audio_scope(ids[(ids.index(s.audio_scope) + 1) % len(ids)] if s.audio_scope in ids else ids[0], user=True)

    def _delete_track(self):
        """⋯ → 移到回收站：焦点屏正在放的这段音声。"""
        from PyQt6.QtWidgets import QMessageBox
        s = self.cur()
        tr = s.current_track()
        if not tr:
            return
        if QMessageBox.question(self, "移到回收站", f"确定把音声《{tr.get('title')}》移到回收站吗？") \
                == QMessageBox.StandardButton.Yes:
            s.delete_current_track()
        self.setFocus()

    # ---- 布局 / 焦点 ----
    def set_layout_mode(self, mode: int, save: bool = False, autoload: bool = True):
        self.layout_mode = 2 if mode == 2 else 3
        _toggle_icon(self.btn_l2, self.layout_mode == 2, "view_column_2")
        _toggle_icon(self.btn_l3, self.layout_mode == 3, "view_week")
        third = self.slots[2]
        if self.layout_mode == 2:
            third.stop()          # 藏起来的那一屏必须停解码，不然还在后台吃硬解
            third.hide()
            if self.active == 2:
                self.activate_slot(0)
        else:
            third.show()
            if autoload and third.player.source().isEmpty():
                third.resume_or_load()
        if save:
            self.save_config()

    def activate_slot(self, idx: int):
        if idx >= self.layout_mode:
            return
        self.active = idx
        for i, s in enumerate(self.slots):
            s.set_active(i == idx)
        self._apply_focus_audio()
        self.refresh_bar()
        if not self.combo.lineEdit().hasFocus():   # 正在频道框里打字时别把焦点抢走
            self.setFocus()

    def set_focus_audio(self, on: bool, save: bool = False):
        self.focus_audio = on
        _toggle_icon(self.btn_focus, on, "hearing")
        self._apply_focus_audio()
        self.refresh_bar()
        if save:
            self.save_config()

    def _apply_focus_audio(self):
        for i, s in enumerate(self.slots):
            s.set_focus_silenced(self.focus_audio and i != self.active)

    def toggle_all_play(self):
        playing = any(s.is_playing() for s in self.visible_slots())
        for s in self.visible_slots():
            s.set_paused(playing)

    # ---- 生命周期 ----
    # ---- 顶栏：悬浮 + 自动隐藏 ----
    def _place_bar(self):
        """顶栏贴在最上面、跟窗口一样宽，高度按内容（一行 / 两行）。"""
        self.top_bar.setGeometry(0, 0, self.width(), self.top_bar.sizeHint().height())

    def _raise_bar(self):
        self._place_bar()
        self.top_bar.show()
        self.top_bar.raise_()   # 压在原生视频窗口上面

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_bar()

    # ---- 顶栏自动隐藏 ----
    def set_bar_pinned(self, on: bool, save: bool = False):
        self.bar_pinned = on
        _toggle_icon(self.btn_pin, on, "keep", "keep-fill")
        if on:
            self._bar_hide.stop()
            self._raise_bar()
        else:
            self._bar_hide.start(1500)
        if save:
            self.save_config()

    def show_bar(self, linger_ms: int = 0):
        self._raise_bar()
        if linger_ms and not self.bar_pinned:
            self._bar_hide.start(linger_ms)

    def _bar_busy(self) -> bool:
        """下拉 / 菜单打开着，或者正在频道框里打字搜索（框里的字跟当前频道不一样），别收。
        光是框有键盘焦点不算——刚显示时它会自己拿到焦点。"""
        from PyQt6.QtWidgets import QApplication
        le = self.combo.lineEdit()
        typing = le.hasFocus() and le.text() != self.combo.currentText()
        return bool(QApplication.activePopupWidget()) or typing

    def _poll_bar(self):
        if self.bar_pinned or not self.isVisible():
            return
        p = self.mapFromGlobal(QCursor.pos())
        inside_x = 0 <= p.x() < self.width()
        edge = self.top_bar.height() if self.top_bar.isVisible() else 6   # 收着时只认最顶端几像素
        if inside_x and 0 <= p.y() <= edge:
            self._bar_hide.stop()
            self._raise_bar()
        elif self.top_bar.isVisible() and not self._bar_hide.isActive():
            self._bar_hide.start(1500)

    def _hide_bar_if_idle(self):
        if self.bar_pinned:
            return
        if self._bar_busy():
            self._bar_hide.start(1500)
            return
        self.top_bar.hide()

    def start_matrix(self):
        """网页设置页点「开始播放」后调用：按配置填频道、设随机/静音/声源，全部以暂停状态载入
        （停在当前帧，按 ⏯ / 空格 开播）；错峰载入，SD 卡上几路同时 seek 会互相堵。
        设置跟这一屏上次放的一样（同一进程里退出再进来）就接着上次的位置。"""
        cfg = mx.load_config()
        channels = mx.get_channels()
        self.audio_scopes = mx.get_audio_scopes()
        self.combo.clear()
        for ch in channels:
            label = ch["label"] if ch.get("group") == "常用" else f"[{ch.get('group')}] {ch['label']}"
            self.combo.addItem(label, ch["id"])
        ids = {ch["id"] for ch in channels}
        scope_ids = {x["id"] for x in self.audio_scopes}
        for s, s_cfg in zip(self.slots, cfg["slots"]):
            # 配置里的作者/专辑已经不在了（删光了/改名），退回全部
            # （直接赋值，不走 set_shuffle：那个会把当前顺序重新洗一遍，恢复进度就对不上了）
            s.channel_id = s_cfg["channel_id"] if s_cfg["channel_id"] in ids else "all"
            s.shuffle = s_cfg["shuffle"]
            s.user_paused = True
            s.set_muted(s_cfg["muted"])
            s.audio_scope = s_cfg["audio_scope"] if s_cfg["audio_scope"] in scope_ids else "all"
            s.asession.set_mode(s_cfg["audio_mode"])
            s.asession.set_rate(s_cfg["audio_rate"])
            if s._tracks_scope != s.audio_scope:
                s.tracks = []        # 设置页改过音声范围：重新取
            s.set_sound(s_cfg["sound"])
        self.set_layout_mode(cfg["layout"], autoload=False)
        self.set_focus_audio(cfg["focus_audio"])
        self.set_bar_pinned(cfg["bar_pinned"])
        self.show_bar(linger_ms=3000)   # 进来先亮 3 秒，让人知道控件在上面
        self._bar_poll.start()
        for i, s in enumerate(self.visible_slots()):
            QTimer.singleShot(i * 200, s.resume_or_load)
        self.activate_slot(0)
        self.setFocus()

    def save_config(self):
        try:
            mx.save_config({"layout": self.layout_mode, "focus_audio": self.focus_audio, "bar_pinned": self.bar_pinned,
                            "slots": [{"channel_id": s.channel_id, "shuffle": s.shuffle, "muted": s.user_muted,
                                       "sound": s.sound, "audio_scope": s.audio_scope,
                                       "audio_mode": s.asession.mode, "audio_rate": s.asession.rate}
                                      for s in self.slots]})
        except OSError as e:
            print(f"[matrix] 保存配置失败: {e}")

    def stop_and_hide(self):
        """离开分区 / 关闭：停掉所有解码器、释放文件句柄。"""
        self._bar_poll.stop()
        self._bar_hide.stop()
        for s in self.slots:
            s.stop()
        self.hide()

    def close_matrix(self, reason: str = "collapse"):
        self.save_config()
        self.stop_and_hide()
        self.closed.emit(reason)

    def focusNextPrevChild(self, _next: bool) -> bool:
        return False   # 别让 Tab 被拿去切换键盘焦点，留给 keyPressEvent 显示 / 收起顶栏

    def keyPressEvent(self, event):
        key = event.key()
        cur = self.cur()
        if key == Qt.Key.Key_Escape:
            self.close_matrix()
        elif key == Qt.Key.Key_Tab:
            if self.top_bar.isVisible() and not self.bar_pinned:
                self.top_bar.hide()
            else:
                self.show_bar(linger_ms=4000)
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.activate_slot(key - Qt.Key.Key_1)
        elif key == Qt.Key.Key_Space:
            cur.set_paused(cur.is_playing())
        elif key == Qt.Key.Key_Left:
            cur.step(-1)
        elif key == Qt.Key.Key_Right:
            cur.step(1)
        elif key == Qt.Key.Key_M:
            cur.set_muted(not cur.user_muted, user=True)
        else:
            super().keyPressEvent(event)
