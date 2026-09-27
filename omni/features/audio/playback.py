"""音声播放的共同规格与断点续听。

音声在三个地方播放：音声专区（本机原生 / 网页 <audio>）和多联放映（本机原生 / 网页）。
档位（倍速、定时、播放模式、快退快进秒数）只在这里定义一份：本机原生控件直接 import，
网页经 /api/audio/player_spec 取。断点续听也只存一份（var/data/audio_progress.json），
哪里听到一半，换个地方打开同一段接着放。
"""
import json
import os
import threading
import time
from typing import Any, Dict

from omni.core import paths

SPEEDS = [1.0, 1.25, 1.5, 1.75, 2.0, 0.75]   # 倍速按钮循环顺序
SLEEP_MINS = [0, 15, 30, 45, 60]             # 定时关闭（0 = 关）
MODES = ["list", "single", "random"]         # 列表循环 / 单曲循环 / 随机
SKIP_BACK_S = 15
SKIP_FWD_S = 30

RESUME_MIN_S = 3      # 听了不到 3 秒不记
RESUME_TAIL_S = 5     # 离结尾不到 5 秒算听完，清掉记录


def spec() -> Dict[str, Any]:
    return {"speeds": SPEEDS, "sleep_mins": SLEEP_MINS, "modes": MODES,
            "skip_back": SKIP_BACK_S, "skip_fwd": SKIP_FWD_S}


def progress_key(rel_path: str, is_nsfw: bool) -> str:
    """一段音声的续听记录键：常规区 / NSFW 区分开（两边可能有同名文件）。"""
    return f"{'nsfw' if is_nsfw else 'std'}:{rel_path}"


_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, float]] = {}
_LOADED = False


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    try:
        with open(paths.AUDIO_PROGRESS, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _CACHE.update({k: v for k, v in data.items() if isinstance(v, dict)})
    except (OSError, ValueError):
        pass
    _LOADED = True


def _save() -> None:
    os.makedirs(os.path.dirname(paths.AUDIO_PROGRESS), exist_ok=True)
    tmp = paths.AUDIO_PROGRESS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_CACHE, f, ensure_ascii=False)
    os.replace(tmp, paths.AUDIO_PROGRESS)


def get_progress(key: str) -> float:
    """上次听到的秒数（没有记录返回 0）。"""
    with _LOCK:
        _load()
        return float((_CACHE.get(key) or {}).get("pos", 0))


def set_progress(key: str, pos: float, duration: float = 0) -> None:
    """记下听到的位置；太靠前或已经听完就删掉记录。调用方自己控制频率（几秒一次）。"""
    if not key:
        return
    with _LOCK:
        _load()
        done = duration > 0 and pos >= duration - RESUME_TAIL_S
        if pos < RESUME_MIN_S or done:
            if _CACHE.pop(key, None) is None:
                return
        else:
            _CACHE[key] = {"pos": round(pos, 1), "dur": round(duration, 1), "at": int(time.time())}
        try:
            _save()
        except OSError as e:
            print(f"[audio] 保存续听进度失败: {e}")
