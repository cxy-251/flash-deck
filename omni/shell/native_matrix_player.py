"""
native_matrix_player.py - 短视频多联放映（本机原生多路播放）

2 屏 / 3 屏并排，每屏一个独立的 QMediaPlayer（Qt 的 FFmpeg 后端，能用 VA-API 就走硬解），
独立选频道、独立顺序/随机、独立静音（静音跟着这一屏走，换下一条也保持）。

跟 native_player.py 同一个套路：MainWindow 的子控件，盖在网页上面。网页那边先有一个设置页
（选几屏、每屏的频道/随机/静音，存进 shortvideo_matrix 的配置），点「开始播放」才调
start_matrix()；这里改动的设置也写回同一份配置，退出后网页设置页看到的就是最新的。

键盘（Steam Input 可映射）：1/2/3 选屏，空格 暂停/继续，←/→ 上/下一条，M 静音，Esc 退出。
"""
import random
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QUrl, QEvent, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QComboBox,
                             QFrame, QSizePolicy, QCompleter)
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
    QPushButton { color:#fff; background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.15);
                  border-radius:6px; padding:5px 10px; }
    QPushButton:hover { background:rgba(255,255,255,0.22); }
    QPushButton[active="true"] { background:#1f6feb; border-color:#58a6ff; font-weight:600; }
    QPushButton#matrixClose { background:#b62324; border-color:#da3633; }
    QComboBox { background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.2); border-radius:6px; padding:3px 8px; }
    QComboBox QAbstractItemView { background:#161b22; color:#fff; selection-background-color:#1f6feb; }
    QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,0.25); border-radius:2px; }
    QSlider::handle:horizontal { width:12px; margin:-4px 0; background:#58a6ff; border-radius:6px; }
    QSlider::sub-page:horizontal { background:#58a6ff; border-radius:2px; }
    QFrame#matrixSlot { background:#000; border:2px solid #22272e; border-radius:8px; }
    QFrame#matrixSlot[active="true"] { border-color:#58a6ff; }
    QLabel#slotTag { color:#58a6ff; font-weight:bold; }
    QLabel#slotDim { color:#8b949e; font-size:11px; }
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
    """一屏：独立解码器 + 选频道 + 进度 + 控制条。"""

    activated = pyqtSignal(int)          # 屏序号（键盘快捷键作用在哪一屏）
    settingsChanged = pyqtSignal()       # 频道/随机/静音变了，让容器写回配置

    MAX_SKIP = 5                         # 连续这么多条都放不了就停下，别无限跳

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
        self.single_loop = False
        self._seeking = False
        self._skips = 0

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video_widget = QVideoWidget(self)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.installEventFilter(self)   # 点视频画面也算选中这一屏

        self._build()
        self._bind()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        top = QHBoxLayout()
        tag = QLabel(f"屏 {self.index + 1}")
        tag.setObjectName("slotTag")
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(6)
        _no_width_hint(self.combo)
        # 可输入搜索：在下拉框里打主播名（文件夹名）的任意一段，弹出匹配项，选中即切换
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.lineEdit().setPlaceholderText("🔍 输入主播名搜索")
        completer = QCompleter(self.combo.model(), self.combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.combo.setCompleter(completer)
        self.lbl_index = QLabel("0/0")
        self.lbl_index.setObjectName("slotDim")
        top.addWidget(tag)
        top.addWidget(self.combo, 1)
        top.addWidget(self.lbl_index)
        v.addLayout(top)

        v.addWidget(self.video_widget, 1)

        meta = QHBoxLayout()
        self.lbl_title = QLabel("")
        _no_width_hint(self.lbl_title)
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setObjectName("slotDim")
        meta.addWidget(self.lbl_title, 1)
        meta.addWidget(self.lbl_time)
        v.addLayout(meta)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        v.addWidget(self.seek)

        bar = QHBoxLayout()
        self.btn_prev, self.btn_play, self.btn_next, self.btn_shuffle, self.btn_loop, self.btn_like, self.btn_mute = (
            QPushButton(t) for t in ("⬅", "⏸", "➡", "🔀", "🔁", "🤍", "🔊"))
        for b, tip in ((self.btn_prev, "上一条"), (self.btn_play, "播放 / 暂停"), (self.btn_next, "下一条"),
                       (self.btn_shuffle, "随机顺序"), (self.btn_loop, "列表循环（点击切为单片循环）"),
                       (self.btn_like, "点赞"), (self.btn_mute, "静音")):
            b.setToolTip(tip)
            b.setFixedWidth(40)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 键盘焦点留给容器，快捷键才不会被按钮吃掉
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)

    def _bind(self):
        self.combo.activated.connect(self._on_combo)   # 只响应用户选择，程序里 setCurrentIndex 不触发
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_shuffle.clicked.connect(lambda: self.set_shuffle(not self.shuffle, user=True))
        self.btn_loop.clicked.connect(self.toggle_loop)
        self.btn_like.clicked.connect(self.toggle_like)
        self.btn_mute.clicked.connect(lambda: self.set_muted(not self.audio.isMuted(), user=True))
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._on_seek_released)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.lbl_time.setText(f"{_fmt_ms(self.player.position())} / {_fmt_ms(d)}"))
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(
            lambda st: self.btn_play.setText("⏸" if st == QMediaPlayer.PlaybackState.PlayingState else "▶"))
        self.player.errorOccurred.connect(self._on_error)

    # ---- 选中（只决定键盘快捷键作用在哪一屏，不动声音） ----
    def mousePressEvent(self, event):
        self.activated.emit(self.index)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.video_widget and event.type() == QEvent.Type.MouseButtonPress:
            self.activated.emit(self.index)
        return False

    def set_active(self, on: bool):
        _set_active_prop(self, on)

    # ---- 设置 ----
    def set_muted(self, muted: bool, user: bool = False):
        """静音挂在这一屏的 QAudioOutput 上，换片不会重置。"""
        self.audio.setMuted(muted)
        self.btn_mute.setText("🔇" if muted else "🔊")
        if user:
            self.settingsChanged.emit()

    def set_shuffle(self, on: bool, user: bool = False):
        """切随机/顺序：当前这条接着放，只重排后面的顺序。"""
        self.shuffle = on
        _set_active_prop(self.btn_shuffle, on)
        self.btn_shuffle.setToolTip("随机顺序（点击切回顺序播放）" if on else "顺序播放（点击切为随机）")
        if self.videos:
            current = self.order[self.pos]
            self._make_order()
            self.pos = self.order.index(current)
            self.lbl_index.setText(f"{self.pos + 1}/{len(self.videos)}")
        if user:
            self.settingsChanged.emit()

    def _make_order(self):
        self.order = list(range(len(self.videos)))
        if self.shuffle:
            random.shuffle(self.order)

    def set_channels(self, channels: List[Dict[str, Any]], channel_id: str):
        self.combo.clear()
        for ch in channels:
            label = ch["label"] if ch.get("group") == "常用" else f"[{ch.get('group')}] {ch['label']}"
            self.combo.addItem(label, ch["id"])
        i = self.combo.findData(channel_id)
        if i < 0:   # 配置里的作者已经不在了（删光了/改名），退回全部平台
            channel_id, i = "all", max(0, self.combo.findData("all"))
        self.combo.setCurrentIndex(i)
        self.channel_id = channel_id

    def _on_combo(self, _i: int):
        cid = self.combo.currentData()
        self.activated.emit(self.index)   # 焦点还给容器，快捷键接着能用
        if cid and cid != self.channel_id:
            self.load_channel(cid)
            self.settingsChanged.emit()
        else:   # 打了字但没选中任何频道：把框里的文字还原成当前频道
            self.combo.setCurrentIndex(max(0, self.combo.findData(self.channel_id)))

    def load_channel(self, channel_id: str):
        self.channel_id = channel_id
        self.videos = mx.get_channel_videos(channel_id)
        self._make_order()
        self.pos = 0
        self._skips = 0
        self._play_current()

    # ---- 播放 ----
    def _play_current(self):
        if not self.videos:
            self.stop()
            self.lbl_title.setText("这个频道没有视频")
            self.lbl_index.setText("0/0")
            return
        it = self.videos[self.order[self.pos]]
        self.lbl_index.setText(f"{self.pos + 1}/{len(self.videos)}")
        self.lbl_title.setText(it.get("title") or "")
        self.lbl_title.setToolTip(it.get("title") or "")
        self.btn_like.setText("❤️" if sv.is_shortvideo_liked(it["platform"], it["rel_path"]) else "🤍")
        path = mx.resolve_file(it)
        if not path:
            self._skip_broken()
            return
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _skip_broken(self):
        """当前条放不了：跳下一条；连续 MAX_SKIP 条都不行就停，别在坏列表上无限空转。"""
        self._skips += 1
        if self._skips > min(self.MAX_SKIP, len(self.videos)):
            self.stop()
            self.lbl_title.setText("连续多条无法播放，已停止")
            return
        QTimer.singleShot(300, lambda: self.step(1, manual=False))

    def step(self, delta: int, manual: bool = True):
        if not self.videos:
            return
        if manual:
            self._skips = 0
        self.pos = (self.pos + delta) % len(self.videos)
        self._play_current()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            self._play_current()
        else:
            self.player.play()

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle_loop(self):
        self.single_loop = not self.single_loop
        self.btn_loop.setText("🔂" if self.single_loop else "🔁")
        self.btn_loop.setToolTip("单片循环（点击切为列表循环）" if self.single_loop else "列表循环（点击切为单片循环）")

    def toggle_like(self):
        if not self.videos:
            return
        it = self.videos[self.order[self.pos]]
        liked = sv.toggle_shortvideo_like(it["platform"], it["rel_path"])
        self.btn_like.setText("❤️" if liked else "🤍")

    def stop(self):
        """停解码并释放文件，隐藏/切换布局/退出时调用。"""
        self.player.stop()
        self.player.setSource(QUrl())
        self.seek.setValue(0)
        self.lbl_time.setText("0:00 / 0:00")

    # ---- 播放器回调 ----
    def _on_seek_released(self):
        self._seeking = False
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(self.seek.value() / 1000 * dur))

    def _on_position(self, pos: int):
        dur = self.player.duration()
        if not self._seeking and dur > 0:
            self.seek.setValue(int(pos / dur * 1000))
        self.lbl_time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._skips = 0          # 真放起来了，坏片计数清零
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.single_loop:
                self.player.setPosition(0)
                self.player.play()
            else:
                self.step(1, manual=False)

    def _on_error(self, error, _msg=""):
        if error != QMediaPlayer.Error.NoError:
            self._skip_broken()


class NativeMatrixPlayerWidget(QWidget):
    """多联放映全屏容器：顶栏 + 2/3 个等宽并排的 MatrixSlotWidget。"""

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("NativeMatrixPlayerWidget{background:#0a0a0c;}" + _QSS)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_mode = 3
        self.active = 0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = QWidget(self)
        top_bar.setObjectName("matrixTopBar")
        top_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_bar.setFixedHeight(48)
        top = QHBoxLayout(top_bar)
        top.setContentsMargins(16, 4, 16, 4)
        top.setSpacing(8)
        logo = QLabel("📺 多联放映")
        logo.setStyleSheet("font-size:15px; font-weight:700; margin-right:12px;")
        top.addWidget(logo)

        def button(text, slot, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            top.addWidget(b)
            return b

        self.btn_l2 = button("2 屏", lambda: self.set_layout_mode(2, save=True))
        self.btn_l3 = button("3 屏", lambda: self.set_layout_mode(3, save=True))
        top.addStretch(1)
        button("⏯ 齐播/齐停", self.toggle_all_play)
        close = button("✕ 退出", self.close_matrix, "Esc")
        close.setObjectName("matrixClose")
        root.addWidget(top_bar)

        area = QWidget(self)
        h = QHBoxLayout(area)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)
        self.slots: List[MatrixSlotWidget] = []
        for i in range(3):
            s = MatrixSlotWidget(i, area)
            s.activated.connect(self.activate_slot)
            s.settingsChanged.connect(self.save_config)
            h.addWidget(s, 1)   # 等分；配合 _no_width_hint，宽度不再随视频变
            self.slots.append(s)
        root.addWidget(area, 1)

    def visible_slots(self) -> List[MatrixSlotWidget]:
        return self.slots[:self.layout_mode]

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
                third.load_channel(third.channel_id)
        if save:
            self.save_config()

    def activate_slot(self, idx: int):
        if idx >= self.layout_mode:
            return
        self.active = idx
        for i, s in enumerate(self.slots):
            s.set_active(i == idx)
        self.setFocus()

    def toggle_all_play(self):
        playing = any(s.is_playing() for s in self.visible_slots())
        for s in self.visible_slots():
            if playing:
                s.player.pause()
            else:
                s.toggle_play()

    # ---- 生命周期 ----
    def start_matrix(self):
        """网页设置页点「开始播放」后调用：按配置填频道、设随机/静音，错峰起播
        （SD 卡上几路同时 seek 会互相堵）。"""
        cfg = mx.load_config()
        channels = mx.get_channels()
        for s, s_cfg in zip(self.slots, cfg["slots"]):
            s.set_channels(channels, s_cfg["channel_id"])
            s.set_shuffle(s_cfg["shuffle"])
            s.set_muted(s_cfg["muted"])
        self.set_layout_mode(cfg["layout"], autoload=False)
        for i, s in enumerate(self.visible_slots()):
            QTimer.singleShot(i * 200, lambda s=s: s.load_channel(s.channel_id))
        self.activate_slot(0)
        self.setFocus()

    def save_config(self):
        try:
            mx.save_config({"layout": self.layout_mode,
                            "slots": [{"channel_id": s.channel_id, "shuffle": s.shuffle, "muted": s.audio.isMuted()}
                                      for s in self.slots]})
        except OSError as e:
            print(f"[matrix] 保存配置失败: {e}")

    def stop_and_hide(self):
        """离开分区 / 关闭：停掉所有解码器、释放文件句柄。"""
        for s in self.slots:
            s.stop()
        self.hide()

    def close_matrix(self):
        self.save_config()
        self.stop_and_hide()
        self.closed.emit()

    def keyPressEvent(self, event):
        key = event.key()
        cur = self.slots[self.active]
        if key == Qt.Key.Key_Escape:
            self.close_matrix()
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.activate_slot(key - Qt.Key.Key_1)
        elif key == Qt.Key.Key_Space:
            cur.toggle_play()
        elif key == Qt.Key.Key_Left:
            cur.step(-1)
        elif key == Qt.Key.Key_Right:
            cur.step(1)
        elif key == Qt.Key.Key_M:
            cur.set_muted(not cur.audio.isMuted(), user=True)
        else:
            super().keyPressEvent(event)
