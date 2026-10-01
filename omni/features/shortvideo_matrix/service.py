"""短视频多联放映：频道聚合、频道视频列表、槽位配置持久化。

视频数据全部复用 shortvideo 模块的扫描缓存（scan_shortvideo_library），音声（每屏可用来
代替视频原声）复用 audio 模块的扫描；这里只做筛选与拼装；平台清单同样来自 manifest 里 module=shortvideo 的分区，新增平台不用改这里。
图集作品（kind == 'images'）没有视频流，一律排除。
"""
import json
import os
import random
import threading
from typing import Any, Dict, List, Optional

from omni.core import paths
from omni.features.audio import playback, service as audio
from omni.features.shortvideo import service as sv

_LOCK = threading.RLock()


def is_landscape(it: Dict[str, Any]) -> bool:
    """横屏视频（宽 > 高）。宽高未知（还没 ffprobe 过）的不算，播放器拿到画面尺寸后再判断。"""
    w, h = it.get("width") or 0, it.get("height") or 0
    return w > h > 0


def _videos(platform: str) -> List[Dict[str, Any]]:
    """某平台可在多联里播放的视频（直接用扫描缓存里的条目，本身就带 platform，不再逐条拷贝——
    「全部平台」频道有六七万条，每屏拷一份就是几十 MB）。图集没有视频流、横屏视频在竖长的分屏里只剩一条缝，都不要。"""
    return [it for it in sv.scan_shortvideo_library(platform)
            if it.get("kind") != "images" and not is_landscape(it)]


def _platform_label(p: str) -> str:
    return sv.PLATFORMS[p]["label"]


def get_channels() -> List[Dict[str, Any]]:
    """可选频道：我的点赞、全部平台、每个平台全部、每个作者。group 给下拉框分组用。"""
    likes = sv.load_likes()
    per_platform = {p: _videos(p) for p in sv.PLATFORMS}
    total = sum(len(v) for v in per_platform.values())
    liked = sum(1 for p, vids in per_platform.items() for it in vids if it["rel_path"] in likes.get(p, ()))

    channels = [
        {"id": "liked", "group": "常用", "label": f"❤️ 我的点赞 ({liked})", "count": liked},
        {"id": "all", "group": "常用", "label": f"🌐 全部平台 ({total})", "count": total},
    ]
    for p, vids in per_platform.items():
        if vids:
            channels.append({"id": f"{p}:", "group": "常用", "label": f"{_platform_label(p)} · 全部 ({len(vids)})", "count": len(vids)})
    for p, vids in per_platform.items():
        authors: Dict[str, int] = {}
        for it in vids:
            a = it.get("folder") or ""
            authors[a] = authors.get(a, 0) + 1
        for a, cnt in sorted(authors.items(), key=lambda x: -x[1]):
            channels.append({"id": f"{p}:{a}", "group": _platform_label(p), "label": f"{a or '未分类'} ({cnt})", "count": cnt})
    return channels


def get_channel_videos(channel_id: str, seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """频道 id → 视频列表。id 形如 liked / all / <平台>: / <平台>:<作者>。

    seed 不为空时按它洗牌（同一个 seed 顺序固定，网页版分页取才不会前后两页对不上）。
    """
    if channel_id == "liked":
        likes = sv.load_likes()
        out = [it for p in sv.PLATFORMS for it in _videos(p) if it["rel_path"] in likes.get(p, ())]
    elif channel_id in ("all", "random"):   # random 是旧配置里的频道名
        out = [it for p in sv.PLATFORMS for it in _videos(p)]
    else:
        platform, _, author = channel_id.partition(":")
        if platform not in sv.PLATFORMS:
            return []
        out = _videos(platform)
        if author:
            out = [it for it in out if (it.get("folder") or "") == author]
    if seed is not None:
        random.Random(seed).shuffle(out)
    return out


def public_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """下发给网页的字段（不含本机绝对路径）。"""
    full = sv.public_item(it, sv.is_shortvideo_liked(it["platform"], it["rel_path"]))
    return {k: full.get(k) for k in ("platform", "rel_path", "title", "folder", "duration", "width", "stream_url",
                                     "thumb_url", "liked")}


def resolve_file(it: Dict[str, Any]) -> Optional[str]:
    """本机原生播放器用：条目 → 磁盘上的真实文件。"""
    p = sv.find_shortvideo_file(it["platform"], it["rel_path"])
    return p if p and os.path.isfile(p) else None


# ---------------- 音声（代替视频原声） ----------------
#
# 音声多是一段段的零碎文件，不按单个文件挑，只选范围：全部 / 某个专辑。范围 id：
#   all                    全部音声
#   std:<专辑> / nsfw:<专辑>  某个专辑（常规区、NSFW 区分开，同名专辑不混）

def _audio_items() -> List[Dict[str, Any]]:
    return audio.scan_audio_library(False) + audio.scan_audio_library(True)


def _scope_id(it: Dict[str, Any]) -> str:
    return f"{'nsfw' if it.get('is_nsfw') else 'std'}:{it.get('album') or ''}"


def get_audio_scopes() -> List[Dict[str, Any]]:
    """可选的音声范围，按专辑内条数从多到少。"""
    items = _audio_items()
    counts: Dict[str, int] = {}
    for it in items:
        counts[_scope_id(it)] = counts.get(_scope_id(it), 0) + 1
    scopes = [{"id": "all", "label": "全部音声", "count": len(items)}]
    for sid, n in sorted(counts.items(), key=lambda x: -x[1]):
        scopes.append({"id": sid, "label": sid.split(":", 1)[1] or "未分类", "count": n})
    return scopes


def get_audio_tracks(scope: str) -> List[Dict[str, Any]]:
    """范围 → 音声列表（按专辑、文件名自然序；随机由播放器自己洗）。"""
    items = _audio_items()
    return items if scope == "all" else [it for it in items if _scope_id(it) == scope]


def public_track(it: Dict[str, Any]) -> Dict[str, Any]:
    """下发给网页的字段（不含本机绝对路径）。rel_path / is_nsfw 用来算续听记录键。"""
    return {k: it.get(k) for k in ("title", "album", "stream_url", "rel_path", "is_nsfw", "chapters")}


def resolve_track(it: Dict[str, Any]) -> Optional[str]:
    p = it.get("path")
    return p if p and os.path.isfile(p) else None


DEFAULT_CONFIG: Dict[str, Any] = {
    "layout": 3,
    "focus_audio": True,   # 焦点出声：没手动静音的屏里，只有焦点屏（点中的那一屏）出声
    "bar_pinned": False,   # 顶栏固定显示（关 = 自动隐藏，鼠标移到顶端才出来）
    "bar_float": True,     # 本机顶栏悬浮在视频上（独立弹出层窗口）；关 = 留出一条固定位置
    "slots": [{"channel_id": "liked", "shuffle": False, "muted": False},
              {"channel_id": "all", "shuffle": True, "muted": True},
              {"channel_id": "all", "shuffle": True, "muted": True}],
}
# 每屏的声音设置：sound = video（视频原声）| audio（音声代替原声）；音声范围与是否随机
SLOT_SOUND_DEFAULTS = {"sound": "video", "audio_scope": "all", "audio_mode": "random", "audio_rate": 1.0}


def _clean_slot(s: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(s.get("channel_id") or "all")
    return {"channel_id": "all" if cid == "random" else cid,
            "shuffle": bool(s.get("shuffle", cid == "random")),
            "muted": bool(s.get("muted", False)),
            "sound": "audio" if s.get("sound") == "audio" else "video",
            "audio_scope": str(s.get("audio_scope") or "all"),
            # 播放模式跟音声专区一样（列表 / 单曲 / 随机）；旧配置只有「随机」开关
            "audio_mode": s.get("audio_mode") if s.get("audio_mode") in playback.MODES
            else ("random" if s.get("audio_shuffle", True) else "list"),
            "audio_rate": _clean_rate(s.get("audio_rate"))}


def _clean_rate(v: Any) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return v if v in playback.SPEEDS else 1.0


def load_config() -> Dict[str, Any]:
    """读取布局与各屏设置；文件缺失或损坏时返回默认值。"""
    data: Dict[str, Any] = {}
    with _LOCK:
        try:
            with open(paths.SHORTVIDEO_MATRIX_CONFIG, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass
    slots = [s for s in (data.get("slots") or []) if isinstance(s, dict)]
    slots += DEFAULT_CONFIG["slots"][len(slots):]
    return {"layout": 2 if data.get("layout") == 2 else 3, "focus_audio": bool(data.get("focus_audio", True)),
            "bar_pinned": bool(data.get("bar_pinned", False)),
            "bar_float": bool(data.get("bar_float", True)),
            "slots": [_clean_slot(s) for s in slots[:3]]}


def save_config(config: Dict[str, Any]) -> None:
    """只保留认识的字段，原子写回。"""
    slots = [s for s in (config.get("slots") or []) if isinstance(s, dict)][:3]
    cfg = {"layout": 2 if config.get("layout") == 2 else 3, "focus_audio": bool(config.get("focus_audio", True)),
           "bar_pinned": bool(config.get("bar_pinned", False)),
           "bar_float": bool(config.get("bar_float", True)),
           "slots": [_clean_slot(s) for s in slots]}
    with _LOCK:
        os.makedirs(os.path.dirname(paths.SHORTVIDEO_MATRIX_CONFIG), exist_ok=True)
        tmp = paths.SHORTVIDEO_MATRIX_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SHORTVIDEO_MATRIX_CONFIG)
