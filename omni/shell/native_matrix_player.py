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
用音声时视频原声的音轨直接关掉，不解码。横屏视频在竖长分屏里只剩一条缝，跳过。

跟 native_player.py 同一个套路：MainWindow 的子控件，盖在网页上面。网页那边先有一个设置页
（选几屏、每屏的频道/随机/静音/声源，存进 shortvideo_matrix 的配置），点「开始播放」才调
start_matrix()；这里改动的设置也写回同一份配置，退出后网页设置页看到的就是最新的。

同一个 Omni 进程里退出再进来，每屏接着上次的频道 / 顺序 / 第几条 / 第几秒（音声同理），
只有在设置页里改了频道或随机的那屏才重新开始；进来时一律是暂停状态，按 ⏯ / 空格 开播。
退出时解码器和文件照样释放，记住的只是位置。退出有两种（closed 信号带原因给网页）：
  collapse ⤓ 收起：回到进多联之前的页面（比如去开一局游戏），再点多联标签直接回到播放器；
  settings ⚙ 设置：回到网页设置页。

键盘（Steam Input 可映射）：1/2/3 选焦点屏，空格 暂停/继续，←/→ 上/下一条，M 静音，Esc 退出。
"""
import random
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QUrl, QEvent, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QComboBox,
                             QFrame, QSizePolicy, QCompleter, QProgressBar)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from omni.features.shortvideo import service as sv
from omni.features.shortvideo_matrix import service as mx


def _fmt_ms(ms: int) -> str:
    m, s = divmod(max(0, int(ms)) // 1000, 60)
    return f"{m}:{s:02d}"


# Qt 样式表不认 CSS 的 .class 选择器，高亮一律用动态属性 [active="true"]，改完属性要 polish 一下才生效
_QSS = """
    QWidget { color:#e6e6e6; font-size:12px; }
    QWidget#matrixTopBar { background:#0c0d10; border-bottom:1px solid #222; }
    QPushButton { color:#fff; background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.14);
                  border-radius:6px; padding:4px 6px; min-width:26px; }
    QPushButton:hover { background:rgba(255,255,255,0.22); }
    QPushButton[active="true"] { background:#1f6feb; border-color:#58a6ff; font-weight:600; }
    QPushButton#matrixClose { background:#b62324; border-color:#da3633; }
    QComboBox { background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.2); border-radius:6px; padding:3px 8px; }
    QComboBox QAbstractItemView { background:#161b22; color:#fff; selection-background-color:#1f6feb; }
    QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,0.25); border-radius:2px; }
    QSlider::handle:horizontal { width:12px; margin:-4px 0; background:#d2a8ff; border-radius:6px; }
    QSlider::sub-page:horizontal { background:#d2a8ff; border-radius:2px; }
    QFrame#matrixSlot { background:#000; border:2px solid #22272e; border-radius:6px; }
    QFrame#matrixSlot[active="true"] { border-color:#58a6ff; }
    QProgressBar { background:#161b22; border:none; }
    QProgressBar::chunk { background:#58a6ff; }
    QLabel#slotTag { color:#58a6ff; font-weight:bold; font-size:13px; }
    QLabel#slotDim { color:#8b949e; font-size:11px; }
    QFrame#barSep { background:#30363d; }
    QWidget#audioBox { background:rgba(210,168,255,0.10); border:1px solid rgba(210,168,255,0.30); border-radius:8px; }
    QWidget#audioBox QPushButton[active="true"] { background:#8957e5; border-color:#d2a8ff; }
    QPushButton#scopeBtn { min-width:96px; max-width:150px; text-align:left; padding-left:8px; }
"""


def _set_active_prop(w: QWidget, on: bool) -> None:
    w.setProperty("active", "true" if on else "false")
    w.style().unpolish(w)
    w.style().polish(w)


def _no_width_hint(w: QWidget) -> None:
    """宽度不跟内容走：视频控件会按当前视频的宽高比报 sizeHint、长标题会报很宽的 sizeHint，
    放进 QHBoxLayout 后每换一条视频三屏就重新分一次宽度。三屏宽度只由布局等分决定。"""
    w.setSizePolicy(QSizePolicy.Policy.Ignored, w.sizePolicy().verticalPolicy())


class MatrixSlotWidget(QFrame):
    """一屏：视频画面 + 底部一条细进度线，没有控件。播放状态和操作都在这里，顶栏只是调用它。"""

    activated = pyqtSignal(int)          # 要成为焦点屏（点击立即；鼠标停留 HOVER_MS 后）
    changed = pyqtSignal(int)            # 顶栏要显示的状态变了（换片、点赞、暂停、声源…）
    audioProgress = pyqtSignal(int, int, int)   # 屏序号, 音声位置, 音声总长（毫秒）
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
        self._aseek_on_load = 0
        self._resume_ms = 0              # stop() 时记下的位置，下次打开接着放
        self._aresume_ms = 0
        self._session: Optional[tuple] = None    # 视频列表是按什么设置取的（频道, 随机）；对不上就重新取
        self._asession: Optional[tuple] = None   # 音声列表同理（范围, 随机）

        # 音声（代替视频原声）
        self.sound = "video"             # video | audio
        self.audio_scope = "all"
        self.audio_shuffle = True
        self.tracks: List[Dict[str, Any]] = []
        self.aorder: List[int] = []
        self.apos = 0
        self._askips = 0

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.aplayer = QMediaPlayer(self)
        self.aout = QAudioOutput(self)
        self.aplayer.setAudioOutput(self.aout)

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
        a = self.aplayer
        a.positionChanged.connect(lambda pos: self.audioProgress.emit(self.index, pos, self.aplayer.duration()))
        a.mediaStatusChanged.connect(self._on_astatus)
        a.errorOccurred.connect(self._on_aerror)

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
        return self.tracks[self.aorder[self.apos]] if self.tracks and self.aplayer.source().isValid() else None

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
                    self._load_track(self._aresume_ms)   # 上次退出时放到的位置（新列表是 0）
                    self._aresume_ms = 0
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

    # ---- 音声 ----
    def set_audio_scope(self, scope: str, user: bool = False):
        self.audio_scope = scope
        self._load_tracks()
        if user:
            self.settingsChanged.emit()

    def set_audio_shuffle(self, on: bool, user: bool = False):
        """切随机/顺序：当前这段接着放，只重排后面的。"""
        self.audio_shuffle = on
        if self.tracks:
            current = self.aorder[self.apos]
            self._make_aorder()
            self.apos = self.aorder.index(current)
        self.changed.emit(self.index)
        if user:
            self.settingsChanged.emit()

    def _make_aorder(self):
        self.aorder = list(range(len(self.tracks)))
        if self.audio_shuffle:
            random.shuffle(self.aorder)

    def _load_tracks(self):
        """换范围：重新取列表，从头（或随机的第一段）开始，但只在该出声时才真的播。"""
        self.tracks = mx.get_audio_tracks(self.audio_scope)
        self._asession = (self.audio_scope, self.audio_shuffle)
        self._aresume_ms = 0
        self._make_aorder()
        self.apos = 0
        self._askips = 0
        self.aplayer.stop()
        self.aplayer.setSource(QUrl())
        self._apply_audio()
        self.changed.emit(self.index)

    def _load_track(self, start_ms: int = 0):
        path = mx.resolve_track(self.tracks[self.aorder[self.apos]])
        self._aseek_on_load = start_ms
        if path:
            self.aplayer.setSource(QUrl.fromLocalFile(path))
        else:
            self._askip_broken()
        self.changed.emit(self.index)

    def astep(self, delta: int, manual: bool = True):
        if not self.tracks:
            return
        if manual:
            self._askips = 0
        self.apos = (self.apos + delta) % len(self.tracks)
        self._load_track()
        self._apply_audio()

    def aseek(self, fraction: float):
        dur = self.aplayer.duration()
        if dur > 0:
            self.aplayer.setPosition(int(fraction * dur))

    def _askip_broken(self):
        self._askips += 1
        if self._askips > min(self.MAX_SKIP, len(self.tracks)):
            self.aplayer.stop()
            return
        QTimer.singleShot(300, lambda: self.astep(1, manual=False))

    def _on_astatus(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._aseek_on_load:
            self.aplayer.setPosition(self._aseek_on_load)
            self._aseek_on_load = 0
        elif status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._askips = 0
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.astep(1, manual=False)

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
        if not self.aplayer.source().isEmpty():
            self._aresume_ms = self.aplayer.position()
        self.player.stop()
        self.player.setSource(QUrl())
        self.aplayer.stop()
        self.aplayer.setSource(QUrl())
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
        self.setStyleSheet("NativeMatrixPlayerWidget{background:#0a0a0c;}" + _QSS)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_mode = 3
        self.active = 0
        self.focus_audio = True
        self.audio_scopes: List[Dict[str, Any]] = []
        self._aseeking = False
        self._build()

    # ---- 界面 ----
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = QWidget(self)
        top_bar.setObjectName("matrixTopBar")
        top_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_bar.setFixedHeight(44)
        top = QHBoxLayout(top_bar)
        top.setContentsMargins(10, 4, 10, 4)
        top.setSpacing(4)

        def button(text, slot, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 键盘焦点留给容器，快捷键才不会被按钮吃掉
            b.clicked.connect(slot)
            if len(text) <= 2:     # 图标按钮统一宽度
                b.setFixedWidth(34)
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
        self.btn_l2 = button("2屏", lambda: self.set_layout_mode(2, save=True), "2 屏并排")
        self.btn_l3 = button("3屏", lambda: self.set_layout_mode(3, save=True), "3 屏并排")
        self.btn_focus = button("🎯", lambda: self.set_focus_audio(not self.focus_audio, save=True),
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
        self.combo.lineEdit().setPlaceholderText("🔍 主播")
        completer = QCompleter(self.combo.model(), self.combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.combo.setCompleter(completer)
        self.combo.activated.connect(self._on_combo)   # 只响应用户选择，程序里 setCurrentIndex 不触发
        top.addWidget(self.combo, 1)
        self.btn_prev = button("⬅", lambda: self.cur().step(-1), "上一条（←）")
        self.btn_play = button("⏸", lambda: self.cur().set_paused(self.cur().is_playing()), "暂停 / 继续（空格）")
        self.btn_next = button("➡", lambda: self.cur().step(1), "下一条（→）")
        self.btn_shuffle = button("🔀", lambda: self.cur().set_shuffle(not self.cur().shuffle, user=True), "视频随机顺序")
        self.btn_like = button("🤍", lambda: self.cur().toggle_like(), "点赞")
        self.btn_mute = button("🔊", lambda: self.cur().set_muted(not self.cur().user_muted, user=True), "静音（M）")
        self.btn_sound = button("🎬", lambda: self.cur().set_sound("video" if self.cur().sound == "audio" else "audio", user=True))

        # 音声（焦点屏用音声时才显示）
        self.audio_box = QWidget()
        self.audio_box.setObjectName("audioBox")
        self.audio_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ab = QHBoxLayout(self.audio_box)
        ab.setContentsMargins(4, 2, 6, 2)
        ab.setSpacing(4)
        self.btn_anext = QPushButton("⏭")
        self.btn_ashuffle = QPushButton("🔀")
        self.btn_scope = QPushButton("📁")
        for b, tip, fn in ((self.btn_anext, "下一段音声", lambda: self.cur().astep(1)),
                           (self.btn_ashuffle, "音声随机顺序", lambda: self.cur().set_audio_shuffle(not self.cur().audio_shuffle, user=True)),
                           (self.btn_scope, "音声范围（点击切到下一个专辑）", self._next_scope)):
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            if b is not self.btn_scope:
                b.setFixedWidth(34)
            ab.addWidget(b)
        self.btn_scope.setObjectName("scopeBtn")   # 宽度在 _QSS 里定（样式表的 min-width 会盖过 setMinimumWidth）
        self.aseek = QSlider(Qt.Orientation.Horizontal)
        self.aseek.setRange(0, 1000)
        self.aseek.setFixedWidth(110)
        self.aseek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.aseek.sliderPressed.connect(lambda: setattr(self, "_aseeking", True))
        self.aseek.sliderReleased.connect(self._on_aseek_released)
        ab.addWidget(self.aseek)
        self.lbl_atime = QLabel("0:00")
        self.lbl_atime.setObjectName("slotDim")
        ab.addWidget(self.lbl_atime)
        top.addSpacing(6)
        top.addWidget(self.audio_box)
        top.addStretch(0)
        sep()

        button("⏯", self.toggle_all_play, "全部 暂停 / 继续")
        button("⚙", lambda: self.close_matrix("settings"), "回到设置页（改每屏的频道 / 声源等）")
        close = button("⤓", lambda: self.close_matrix("collapse"),
                       "收起（Esc）：记住各屏位置，回到进来之前的页面；再点多联标签接着看")
        close.setObjectName("matrixClose")
        root.addWidget(top_bar)

        area = QWidget(self)
        h = QHBoxLayout(area)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(6)
        self.slots: List[MatrixSlotWidget] = []
        for i in range(3):
            s = MatrixSlotWidget(i, area)
            s.activated.connect(self.activate_slot)
            s.changed.connect(lambda idx: idx == self.active and self.refresh_bar())
            s.audioProgress.connect(self._on_audio_progress)
            s.settingsChanged.connect(self.save_config)
            h.addWidget(s, 1)   # 等分；配合 _no_width_hint，宽度不再随视频变
            self.slots.append(s)
        root.addWidget(area, 1)

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
        self.btn_play.setText("⏸" if s.is_playing() else "▶")
        _set_active_prop(self.btn_shuffle, s.shuffle)
        self.btn_like.setText("❤️" if s.is_liked() else "🤍")
        if s.user_muted:
            self.btn_mute.setText("🔇")
        elif s.focus_silenced:
            self.btn_mute.setText("🔈")
        else:
            self.btn_mute.setText("🔊")
        audio = s.sound == "audio"
        self.btn_sound.setText("🎧" if audio else "🎬")
        self.btn_sound.setToolTip("声音：音声（点击换回视频原声）" if audio else "声音：视频原声（点击换成音声）")
        _set_active_prop(self.btn_sound, audio)
        self.audio_box.setVisible(audio)
        if audio:
            _set_active_prop(self.btn_ashuffle, s.audio_shuffle)
            sc = next((x for x in self.audio_scopes if x["id"] == s.audio_scope), None)
            name = sc["label"] if sc else "全部音声"
            self.btn_scope.setText(f"📁 {name}")
            tr = s.current_track()
            self.btn_scope.setToolTip(f"范围：{name}" + (f"\n正在放：{tr.get('title')}" if tr else "") + "\n点击切到下一个专辑")
            self.aseek.setToolTip(tr.get("title") if tr else "")
            self._on_audio_progress(s.index, s.aplayer.position(), s.aplayer.duration())

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

    def _on_audio_progress(self, idx: int, pos: int, dur: int):
        if idx != self.active:
            return
        if not self._aseeking and dur > 0:
            self.aseek.setValue(int(pos / dur * 1000))
        self.lbl_atime.setText(_fmt_ms(pos))

    def _on_aseek_released(self):
        self._aseeking = False
        self.cur().aseek(self.aseek.value() / 1000)

    # ---- 布局 / 焦点 ----
    def set_layout_mode(self, mode: int, save: bool = False, autoload: bool = True):
        self.layout_mode = 2 if mode == 2 else 3
        _set_active_prop(self.btn_l2, self.layout_mode == 2)
        _set_active_prop(self.btn_l3, self.layout_mode == 3)
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
        _set_active_prop(self.btn_focus, on)
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
            s.audio_shuffle = s_cfg["audio_shuffle"]
            if s._asession != (s.audio_scope, s.audio_shuffle):
                s.tracks = []        # 设置页改过音声范围/随机：重新取
            s.set_sound(s_cfg["sound"])
        self.set_layout_mode(cfg["layout"], autoload=False)
        self.set_focus_audio(cfg["focus_audio"])
        for i, s in enumerate(self.visible_slots()):
            QTimer.singleShot(i * 200, s.resume_or_load)
        self.activate_slot(0)
        self.setFocus()

    def save_config(self):
        try:
            mx.save_config({"layout": self.layout_mode, "focus_audio": self.focus_audio,
                            "slots": [{"channel_id": s.channel_id, "shuffle": s.shuffle, "muted": s.user_muted,
                                       "sound": s.sound, "audio_scope": s.audio_scope, "audio_shuffle": s.audio_shuffle}
                                      for s in self.slots]})
        except OSError as e:
            print(f"[matrix] 保存配置失败: {e}")

    def stop_and_hide(self):
        """离开分区 / 关闭：停掉所有解码器、释放文件句柄。"""
        for s in self.slots:
            s.stop()
        self.hide()

    def close_matrix(self, reason: str = "collapse"):
        self.save_config()
        self.stop_and_hide()
        self.closed.emit(reason)

    def keyPressEvent(self, event):
        key = event.key()
        cur = self.cur()
        if key == Qt.Key.Key_Escape:
            self.close_matrix()
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
