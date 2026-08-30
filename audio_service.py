"""
audio_service.py - Omni Deck 音声与广播剧核心流媒体服务
特性：
1. 高速扫描 /run/media/deck/FUCKDECK/telegramFile 与本地 audio 目录
2. 毫秒级内存缓存与模糊检索
3. HTTP Range 请求原生流式分段点播（支持快速拖动进度条）
4. 安全回收站清理 (gio trash)
"""

import os
import re
import time
import subprocess
import urllib.parse
from typing import List, Dict, Any, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTERNAL_AUDIO_DIR = os.environ.get("OMNI_AUDIO_DIR", "/run/media/deck/FUCKDECK/telegramFile")

VALID_EXTS = {'.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.opus', '.wma'}

# 内存索引缓存
_AUDIO_CACHE = []
_LAST_SCAN_TIME = 0

def get_audio_dirs() -> List[str]:
    """
    获取当前系统中所有已挂载并存在的音声根目录列表。
    默认扫描 SD 卡 / 外部挂载目录 (/run/media/deck/FUCKDECK/telegramFile)，支持 OMNI_AUDIO_DIR 环境变量覆盖。
    """
    dirs = []
    if os.path.exists(EXTERNAL_AUDIO_DIR) and os.path.isdir(EXTERNAL_AUDIO_DIR):
        dirs.append(EXTERNAL_AUDIO_DIR)
    return dirs

def scan_audio_library(force: bool = False) -> List[Dict[str, Any]]:
    """
    全量扫描音频库目录并提取文件元数据。
    
    性能与缓存机制：
    - 内存中保留 30 秒缓存有效期，避免高频请求产生磁盘 I/O 瓶颈。
    - 自动去重同名文件并跳过隐藏文件。
    - 计算文件体积 (MB)、修改时间以及生成流式点播 URL。
    
    参数:
        force (bool): 是否强制跳过 30s 缓存进行全盘物理重扫。
    """
    global _AUDIO_CACHE, _LAST_SCAN_TIME
    now = time.time()
    if not force and _AUDIO_CACHE and (now - _LAST_SCAN_TIME < 30):
        return _AUDIO_CACHE

    audios = []
    seen_files = set()

    for adir in get_audio_dirs():
        try:
            for fname in sorted(os.listdir(adir)):
                if fname.startswith('.'):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in VALID_EXTS:
                    continue

                full_p = os.path.join(adir, fname)
                if not os.path.isfile(full_p):
                    continue

                if fname in seen_files:
                    continue
                seen_files.add(fname)

                try:
                    stat = os.stat(full_p)
                    size_mb = round(stat.st_size / (1024 * 1024), 2)
                    mtime_str = time.strftime('%Y-%m-%d', time.localtime(stat.st_mtime))
                    base_title = os.path.splitext(fname)[0]

                    audios.append({
                        'filename': fname,
                        'title': base_title,
                        'ext': ext.lstrip('.'),
                        'size_mb': size_mb,
                        'mtime': mtime_str,
                        'path': full_p,
                        'stream_url': f'/api/audio/stream?name={urllib.parse.quote(fname)}'
                    })
                except Exception:
                    pass
        except Exception as e:
            print("Scan audio err:", e)

    _AUDIO_CACHE = audios
    _LAST_SCAN_TIME = now
    return audios

def query_audio_library(q: str = "", page: int = 1, page_size: int = 80) -> Dict[str, Any]:
    """
    带分页和模糊检索的音频查询接口。
    
    参数:
        q (str): 模糊检索关键词（匹配标题或文件名）
        page (int): 当前页码 (1-indexed)
        page_size (int): 每页条目数 (默认 80)
        
    返回:
        Dict: 包含 items, total, page, page_size, has_more 的标准分页字典
    """
    all_audios = scan_audio_library()
    q = (q or "").strip().lower()

    if q:
        matched = [a for a in all_audios if q in a['title'].lower() or q in a['filename'].lower()]
    else:
        matched = all_audios

    total = len(matched)
    start_idx = max(0, (page - 1) * page_size)
    end_idx = start_idx + page_size
    page_items = matched[start_idx:end_idx]

    return {
        'items': page_items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'has_more': end_idx < total
    }

def find_audio_file(filename: str) -> Optional[str]:
    """
    根据文件名在所有注册的音频根目录下定位物理绝对路径。
    
    参数:
        filename (str): 目标音频文件名
        
    返回:
        Optional[str]: 物理绝对路径或 None
    """
    clean_name = os.path.basename(filename)
    for adir in get_audio_dirs():
        full_p = os.path.join(adir, clean_name)
        if os.path.exists(full_p) and os.path.isfile(full_p):
            return full_p
    return None

def trash_audio_file(filename: str) -> bool:
    """
    按照 AGENTS.md 准则，使用 'gio trash' 安全删除指定音频至系统回收站，并自动刷新缓存。
    
    参数:
        filename (str): 要删除的音频文件名
        
    返回:
        bool: 删除是否成功
    """
    full_p = find_audio_file(filename)
    if not full_p:
        return False
    try:
        res = subprocess.run(['gio', 'trash', full_p], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        scan_audio_library(force=True)
        return res.returncode == 0
    except Exception:
        return False
