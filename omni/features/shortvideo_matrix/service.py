"""短视频多联放映：频道聚合、频道视频列表、槽位配置持久化。

视频数据全部复用 shortvideo 模块的扫描缓存（scan_shortvideo_library），这里只做筛选与
拼装；平台清单同样来自 manifest 里 module=shortvideo 的分区，新增平台不用改这里。
图集作品（kind == 'images'）没有视频流，一律排除。
"""
import json
import os
import random
import threading
from typing import Any, Dict, List, Optional

from omni.core import paths
from omni.features.shortvideo import service as sv

_LOCK = threading.RLock()


def is_landscape(it: Dict[str, Any]) -> bool:
    """横屏视频（宽 > 高）。宽高未知（还没 ffprobe 过）的不算，播放器拿到画面尺寸后再判断。"""
    w, h = it.get("width") or 0, it.get("height") or 0
    return w > h > 0


def _videos(platform: str) -> List[Dict[str, Any]]:
    """某平台可在多联里播放的视频（带上 platform 字段的浅拷贝）。
    图集没有视频流、横屏视频在竖长的分屏里只剩一条缝，都不要。"""
    return [dict(it, platform=platform) for it in sv.scan_shortvideo_library(platform)
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
    return {k: it.get(k) for k in ("platform", "rel_path", "title", "folder", "duration", "width", "stream_url", "thumb_url")} | {
        "liked": sv.is_shortvideo_liked(it["platform"], it["rel_path"]),
    }


def resolve_file(it: Dict[str, Any]) -> Optional[str]:
    """本机原生播放器用：条目 → 磁盘上的真实文件。"""
    p = sv.find_shortvideo_file(it["platform"], it["rel_path"])
    return p if p and os.path.isfile(p) else None


DEFAULT_CONFIG: Dict[str, Any] = {
    "layout": 3,
    "focus_audio": True,   # 焦点出声：没手动静音的屏里，只有鼠标所在/点中的那一屏出声
    "slots": [{"channel_id": "liked", "shuffle": False, "muted": False},
              {"channel_id": "all", "shuffle": True, "muted": True},
              {"channel_id": "all", "shuffle": True, "muted": True}],
}


def _clean_slot(s: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(s.get("channel_id") or "all")
    return {"channel_id": "all" if cid == "random" else cid,
            "shuffle": bool(s.get("shuffle", cid == "random")),
            "muted": bool(s.get("muted", False))}


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
            "slots": [_clean_slot(s) for s in slots[:3]]}


def save_config(config: Dict[str, Any]) -> None:
    """只保留认识的字段，原子写回。"""
    slots = [s for s in (config.get("slots") or []) if isinstance(s, dict)][:3]
    cfg = {"layout": 2 if config.get("layout") == 2 else 3, "focus_audio": bool(config.get("focus_audio", True)),
           "slots": [_clean_slot(s) for s in slots]}
    with _LOCK:
        os.makedirs(os.path.dirname(paths.SHORTVIDEO_MATRIX_CONFIG), exist_ok=True)
        tmp = paths.SHORTVIDEO_MATRIX_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SHORTVIDEO_MATRIX_CONFIG)
