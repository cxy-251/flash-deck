"""
audio_controls.py - 本机原生「音声」播放逻辑与控制条（音声专区、多联放映共用）

两层：
  AudioSession    挂在一个 QMediaPlayer 上的播放逻辑：倍速、播放模式、章节、快退快进、
                  断点续听（存服务器 omni.features.audio.playback，本机 / 网页 / 多联共用）。
                  「下一首放哪条」不归它管——列表在宿主手里（音声专区在网页、多联在每一屏），
                  它只在需要换条时发 nextRequested / prevRequested，宿主按 session.mode 挑。
  AudioControlBar 一条按钮栏，bind() 到某个 session 就显示、操作那个 session；多联顶栏只有
                  一条，焦点屏换了就 rebind。定时关闭是整条栏的（到点发 sleepFired，宿主决定停什么）。

档位（倍速、定时、模式、快退快进秒数）都来自 playback.py，网页经 /api/audio/player_spec 取同一份。
功能 = 网页音声播放器的全部（上/下一首、模式、倍速、定时、章节、进度与总长、续听、删除），
再加本机专属：快退 15 秒 / 快进 30 秒、上一章 / 下一章。
"""
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSlider, QLabel, QMenu, QToolButton
from PyQt6.QtMultimedia import QMediaPlayer

from omni.features.audio import playback

MODE_ICON = {"list": "🔁", "single": "🔂", "random": "🔀"}
MODE_NAME = {"list": "列表循环", "single": "单曲循环", "random": "随机播放"}
SAVE_EVERY_S = 10        # 续听进度几秒写一次


def fmt_ms(ms: int) -> str:
    """毫秒 → "h:mm:ss"（不足一小时省略小时位）。"""
    s = max(0, int(ms)) // 1000
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class AudioSession(QObject):
    """一个音声播放器的逻辑状态。宿主负责列表与换条，这里负责当前这一条怎么放。"""

    changed = pyqtSignal()           # 倍速 / 模式 / 章节 / 当前条目变了（控制条刷新）
    nextRequested = pyqtSignal()     # 播完（非单曲循环）或点了 ⏭
    prevRequested = pyqtSignal()

    def __init__(self, player: QMediaPlayer, parent=None):
        super().__init__(parent)
        self.player = player
        self.rate = 1.0
        self.mode = "list"
        self.title = ""
        self.chapters: List[Dict[str, Any]] = []
        self.key = ""                # 续听记录键（playback.progress_key）
        self._seek_on_load = 0
        self._saved_at = 0.0
        player.mediaStatusChanged.connect(self._on_status)
        player.positionChanged.connect(self._on_position)
        player.playbackStateChanged.connect(self._on_state)

    # ---- 载入 ----
    def load(self, path: str, key: str = "", title: str = "", chapters=None, start_ms: Optional[int] = None):
        """换一条：先把上一条的进度存掉；start_ms 为空时从服务器上的续听记录接着放。"""
        self.save_progress()
        self.key = key
        self.title = title
        self.chapters = list(chapters or [])
        if start_ms is None:
            start_ms = int(playback.get_progress(key) * 1000) if key else 0
        self._seek_on_load = start_ms
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPlaybackRate(self.rate)
        self.changed.emit()

    def clear(self):
        """停止并释放文件（先存进度）。"""
        self.save_progress()
        self.player.stop()
        self.player.setSource(QUrl())
        self.key = ""

    # ---- 续听 ----
    def save_progress(self, finished: bool = False):
        if not self.key or self.player.source().isEmpty():
            return
        dur = self.player.duration() / 1000
        pos = dur if finished else self.player.position() / 1000
        playback.set_progress(self.key, pos, dur)
        self._saved_at = time.time()

    def _on_position(self, _pos: int):
        if time.time() - self._saved_at > SAVE_EVERY_S and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.save_progress()

    def _on_state(self, state):
        if state == QMediaPlayer.PlaybackState.PausedState:
            self.save_progress()

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._seek_on_load:
            self.player.setPosition(self._seek_on_load)
            self._seek_on_load = 0
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.save_progress(finished=True)    # 听完：清掉续听记录
            if self.mode == "single":
                self.player.setPosition(0)
                self.player.play()
            else:
                self.nextRequested.emit()

    # ---- 操作 ----
    def set_rate(self, rate: float):
        self.rate = rate if rate in playback.SPEEDS else 1.0
        self.player.setPlaybackRate(self.rate)   # Qt 默认保持音调，人声不变尖
        self.changed.emit()

    def cycle_rate(self):
        s = playback.SPEEDS
        self.set_rate(s[(s.index(self.rate) + 1) % len(s)] if self.rate in s else 1.0)

    def set_mode(self, mode: str):
        self.mode = mode if mode in playback.MODES else "list"
        self.changed.emit()

    def cycle_mode(self):
        m = playback.MODES
        self.set_mode(m[(m.index(self.mode) + 1) % len(m)])

    def skip(self, seconds: int):
        dur = self.player.duration()
        self.player.setPosition(max(0, min(dur - 500 if dur > 0 else 0, self.player.position() + seconds * 1000)))

    def seek_fraction(self, f: float):
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(f * dur))

    def chapter_index(self) -> int:
        secs = self.player.position() / 1000
        cur = -1
        for i, ch in enumerate(self.chapters):
            if secs >= (ch.get("start") or 0):
                cur = i
        return cur

    def goto_chapter(self, i: int):
        if 0 <= i < len(self.chapters):
            self.player.setPosition(int((self.chapters[i].get("start") or 0) * 1000))

    def step_chapter(self, delta: int):
        """上一章 / 下一章。上一章：本章已放了 3 秒以上先回本章开头（跟常见播放器一样）。"""
        cur = self.chapter_index()
        if delta < 0 and cur >= 0 and self.player.position() / 1000 - (self.chapters[cur].get("start") or 0) > 3:
            self.goto_chapter(cur)
        else:
            self.goto_chapter(max(0, cur + delta))


class AudioControlBar(QWidget):
    """一条音声控制栏，bind(session) 后显示 / 操作那个 session。

    show_play=False：多联里音声跟着那一屏的视频一起停 / 放，不单独给 ⏯。
    """

    playToggled = pyqtSignal()
    deleteRequested = pyqtSignal()
    sleepFired = pyqtSignal()

    def __init__(self, parent=None, show_play: bool = True, seek_width: int = 0):
        super().__init__(parent)
        self.session: Optional[AudioSession] = None
        self._seeking = False
        self._sleep_idx = 0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._on_sleep)
        self._sleep_tick = QTimer(self)       # 每分钟刷新一次剩余分钟数
        self._sleep_tick.setInterval(60_000)
        self._sleep_tick.timeout.connect(self._update_sleep_btn)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        def btn(text, tip, fn, width=34):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            if width:
                b.setFixedWidth(width)
            h.addWidget(b)
            return b

        self.btn_prev = btn("⏮", "上一首", lambda: self.session and self.session.prevRequested.emit())
        self.btn_back = btn("⏪", f"快退 {playback.SKIP_BACK_S} 秒", lambda: self.session and self.session.skip(-playback.SKIP_BACK_S))
        self.btn_play = btn("⏸", "播放 / 暂停", self.playToggled.emit)
        self.btn_play.setVisible(show_play)
        self.btn_fwd = btn("⏩", f"快进 {playback.SKIP_FWD_S} 秒", lambda: self.session and self.session.skip(playback.SKIP_FWD_S))
        self.btn_next = btn("⏭", "下一首", lambda: self.session and self.session.nextRequested.emit())
        self.btn_mode = btn("🔁", "", lambda: self.session and self.session.cycle_mode())
        # 这两个按钮会显示文字（1.25x / ⏳45），宽度按最长的留，不然被截成 "1.2›"
        self.btn_rate = btn("1x", "倍速（点击切下一档）", lambda: self.session and self.session.cycle_rate(), 58)
        self.btn_sleep = btn("⏳", "定时关闭（点击切下一档）", self._cycle_sleep, 58)

        # 章节：弹出菜单（上一章 / 下一章 + 目录），没有章节时隐藏
        self.btn_chapter = QToolButton()
        self.btn_chapter.setText("📑")
        self.btn_chapter.setToolTip("章节")
        self.btn_chapter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_chapter.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.chapter_menu = QMenu(self)
        self.chapter_menu.aboutToShow.connect(self._fill_chapter_menu)
        self.btn_chapter.setMenu(self.chapter_menu)
        h.addWidget(self.btn_chapter)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if seek_width:
            self.seek.setFixedWidth(seek_width)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._on_seek_release)
        h.addWidget(self.seek, 0 if seek_width else 1)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("audioTime")
        h.addWidget(self.time_label)

        # ⋯：不常用、怕误点的放这里
        self.btn_more = QToolButton()
        self.btn_more.setText("⋯")
        self.btn_more.setToolTip("更多")
        self.btn_more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more = QMenu(self)
        more.addAction("🗑 移到回收站…", self.deleteRequested.emit)
        self.btn_more.setMenu(more)
        h.addWidget(self.btn_more)

    # ---- 绑定 ----
    def bind(self, session: Optional[AudioSession]):
        """换一个要显示 / 操作的 session（多联换焦点屏时）。"""
        if self.session is session:
            self.refresh()
            return
        if self.session:
            for sig, slot in self._conns():
                try:
                    sig.disconnect(slot)
                except TypeError:
                    pass
        self.session = session
        if session:
            for sig, slot in self._conns():
                sig.connect(slot)
        self.refresh()

    def _conns(self):
        s = self.session
        return [(s.changed, self.refresh), (s.player.positionChanged, self._on_position),
                (s.player.durationChanged, self._on_position), (s.player.playbackStateChanged, self._on_state)]

    def refresh(self):
        s = self.session
        if not s:
            return
        self.btn_rate.setText(f"{s.rate:g}x")
        self._set_active(self.btn_rate, s.rate != 1.0)
        self.btn_mode.setText(MODE_ICON[s.mode])
        self.btn_mode.setToolTip(f"播放模式：{MODE_NAME[s.mode]}（点击切换）")
        self.btn_chapter.setVisible(bool(s.chapters))
        self.btn_chapter.setToolTip(f"章节（{len(s.chapters)}）")
        self.seek.setToolTip(s.title)
        self._on_state(s.player.playbackState())
        self._on_position()

    @staticmethod
    def _set_active(w: QWidget, on: bool):
        w.setProperty("active", "true" if on else "false")
        w.style().unpolish(w)
        w.style().polish(w)

    # ---- 进度 ----
    def _on_position(self, *_):
        p = self.session.player
        pos, dur = p.position(), p.duration()
        if not self._seeking and dur > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / dur * 1000))
            self.seek.blockSignals(False)
        self.time_label.setText(f"{fmt_ms(pos)} / {fmt_ms(dur)}")

    def _on_state(self, state):
        self.btn_play.setText("⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")

    def _on_seek_release(self):
        self._seeking = False
        if self.session:
            self.session.seek_fraction(self.seek.value() / 1000)

    # ---- 章节 ----
    def _fill_chapter_menu(self):
        m = self.chapter_menu
        m.clear()
        s = self.session
        if not s or not s.chapters:
            return
        m.addAction("⏮ 上一章", lambda: s.step_chapter(-1))
        m.addAction("⏭ 下一章", lambda: s.step_chapter(1))
        m.addSeparator()
        cur = s.chapter_index()
        for i, ch in enumerate(s.chapters):
            label = ch.get("title") or f"第{ch.get('index', i + 1)}章"
            dur = ch.get("duration_str")
            act = QAction(f"{label}" + (f"  ({dur})" if dur else ""), m)
            act.setCheckable(True)
            act.setChecked(i == cur)
            act.triggered.connect(lambda _c=False, i=i: s.goto_chapter(i))
            m.addAction(act)

    # ---- 定时关闭（整条栏的，到点发 sleepFired） ----
    def _cycle_sleep(self):
        mins = playback.SLEEP_MINS
        self._sleep_idx = (self._sleep_idx + 1) % len(mins)
        self._sleep_timer.stop()
        self._sleep_tick.stop()
        if mins[self._sleep_idx] > 0:
            self._sleep_timer.start(mins[self._sleep_idx] * 60_000)
            self._sleep_tick.start()
        self._update_sleep_btn()

    def _update_sleep_btn(self):
        on = self._sleep_timer.isActive()
        left = (self._sleep_timer.remainingTime() + 59_999) // 60_000 if on else 0
        self.btn_sleep.setText(f"⏳{left}" if on else "⏳")
        self.btn_sleep.setToolTip(f"定时关闭：还剩 {left} 分钟（点击切下一档）" if on else "定时关闭：关（点击切下一档）")
        self._set_active(self.btn_sleep, on)

    def _on_sleep(self):
        self._sleep_idx = 0
        self._sleep_tick.stop()
        self._update_sleep_btn()
        self.sleepFired.emit()

    def cancel_sleep(self):
        """关播放器时把定时也撤掉。"""
        self._sleep_timer.stop()
        self._sleep_idx = 0
        self._sleep_tick.stop()
        self._update_sleep_btn()
