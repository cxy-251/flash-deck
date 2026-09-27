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

RANDOM_LIMIT = 300   # 「随机」频道每次洗牌后只取这么多，列表够刷、下发也不大


def _videos(platform: str) -> List[Dict[str, Any]]:
    """某平台全部可播放视频（带上 platform 字段的浅拷贝）。"""
    return [dict(it, platform=platform) for it in sv.scan_shortvideo_library(platform)
            if it.get("kind") != "images"]


def get_channels() -> List[Dict[str, Any]]:
    """可选频道：我的点赞、全平台随机、每个平台全部、每个作者。"""
    likes = sv.load_likes()
    per_platform = {p: _videos(p) for p in sv.PLATFORMS}
    total = sum(len(v) for v in per_platform.values())
    liked = sum(1 for p, vids in per_platform.items() for it in vids if it["rel_path"] in likes.get(p, ()))

    channels = [
        {"id": "liked", "label": f"❤️ 我的点赞 ({liked})", "count": liked},
        {"id": "random", "label": f"🎲 全平台随机 ({total})", "count": total},
    ]
    for p, vids in per_platform.items():
        if vids:
            channels.append({"id": f"{p}:", "label": f"{sv.PLATFORMS[p]['label']} · 全部 ({len(vids)})", "count": len(vids)})
    for p, vids in per_platform.items():
        authors: Dict[str, int] = {}
        for it in vids:
            a = it.get("folder") or ""
            authors[a] = authors.get(a, 0) + 1
        for a, cnt in sorted(authors.items(), key=lambda x: -x[1]):
            channels.append({"id": f"{p}:{a}", "label": f"[{sv.PLATFORMS[p]['label']}] {a or '未分类'} ({cnt})", "count": cnt})
    return channels


def get_channel_videos(channel_id: str) -> List[Dict[str, Any]]:
    """频道 id → 视频列表。id 形如 liked / random / <平台>: / <平台>:<作者>。"""
    if channel_id == "liked":
        likes = sv.load_likes()
        return [it for p in sv.PLATFORMS for it in _videos(p) if it["rel_path"] in likes.get(p, ())]
    if channel_id == "random":
        out = [it for p in sv.PLATFORMS for it in _videos(p)]
        random.shuffle(out)
        return out[:RANDOM_LIMIT]
    platform, _, author = channel_id.partition(":")
    if platform not in sv.PLATFORMS:
        return []
    vids = _videos(platform)
    return [it for it in vids if (it.get("folder") or "") == author] if author else vids


def public_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """下发给网页的字段（不含本机绝对路径）。"""
    return {k: it.get(k) for k in ("platform", "rel_path", "title", "folder", "duration", "stream_url", "thumb_url")} | {
        "liked": sv.is_shortvideo_liked(it["platform"], it["rel_path"]),
    }


def resolve_file(it: Dict[str, Any]) -> Optional[str]:
    """本机原生播放器用：条目 → 磁盘上的真实文件。"""
    p = sv.find_shortvideo_file(it["platform"], it["rel_path"])
    return p if p and os.path.isfile(p) else None


DEFAULT_CONFIG: Dict[str, Any] = {
    "layout": 3,
    "audio_mode": "focus",   # 'focus' 焦点出声 | 'manual' 手动混音
    "slots": [{"channel_id": "liked"}, {"channel_id": "random"}, {"channel_id": "random"}],
}


def load_config() -> Dict[str, Any]:
    """读取槽位与模式配置；文件缺失或损坏时返回默认值。"""
    with _LOCK:
        try:
            with open(paths.SHORTVIDEO_MATRIX_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except (OSError, ValueError):
            pass
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: Dict[str, Any]) -> None:
    """只保留认识的字段，原子写回。"""
    cfg = {
        "layout": 2 if config.get("layout") == 2 else 3,
        "audio_mode": "manual" if config.get("audio_mode") == "manual" else "focus",
        "slots": [{"channel_id": str(s.get("channel_id") or "random")}
                  for s in (config.get("slots") or [])[:3] if isinstance(s, dict)],
    }
    with _LOCK:
        os.makedirs(os.path.dirname(paths.SHORTVIDEO_MATRIX_CONFIG), exist_ok=True)
        tmp = paths.SHORTVIDEO_MATRIX_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SHORTVIDEO_MATRIX_CONFIG)
