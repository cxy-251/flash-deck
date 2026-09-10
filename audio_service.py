"""
audio_service.py - Omni Deck 音声与广播剧核心流媒体服务
特性：
1. 高速扫描 /run/media/deck/FUCKDECK/telegramFile 与本地 audio 目录 (支持非 NSFW 常规有声书与 NSFW 绅士专区隔离)
2. 支持有声书专辑/系列层级目录自动识别 (如《鬼吹灯之精绝古城》、评书名著等)
3. 毫秒级内存双模缓存与模糊/专辑检索
4. HTTP Range 请求原生流式分段点播（支持快速拖动进度条）
5. 安全回收站清理 (gio trash)
"""

import os
import re
import json
import time
import subprocess
import urllib.parse
from typing import List, Dict, Any, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTERNAL_AUDIO_DIR = os.environ.get("OMNI_AUDIO_DIR", "/run/media/deck/FUCKDECK/telegramFile")
AUDIO_STANDARD_DIR = os.path.join(SCRIPT_DIR, "audio", "standard")
AUDIO_NSFW_DIR = os.path.join(SCRIPT_DIR, "audio", "nsfw")
AUDIO_ROOT_DIR = os.path.join(SCRIPT_DIR, "audio")

VALID_EXTS = {'.mp3', '.m4a', '.m4b', '.wav', '.flac', '.aac', '.ogg', '.opus', '.wma'}

def natural_sort_key(s: Any) -> list:
    """自然数字排序键，确保 EP1-10 < EP11-20 < EP104-120 等顺畅排序"""
    if not s:
        return []
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

# 内存索引缓存 (分别缓存标准有声书与 NSFW 音频)
_AUDIO_STD_CACHE = []
_LAST_SCAN_STD = 0

_AUDIO_NSFW_CACHE = []
_LAST_SCAN_NSFW = 0

def get_audio_dirs(is_nsfw: bool = False) -> List[str]:
    """
    获取指定模式下所有已挂载并存在的音频根目录列表。
    - is_nsfw=False: 扫描本地 audio/standard/ 目录与 audio/ 根目录
    - is_nsfw=True: 扫描 SD 卡 / 外部挂载目录 (/run/media/deck/FUCKDECK/telegramFile) 及 audio/nsfw/
    """
    dirs = []
    if is_nsfw:
        if os.path.exists(EXTERNAL_AUDIO_DIR) and os.path.isdir(EXTERNAL_AUDIO_DIR):
            dirs.append(EXTERNAL_AUDIO_DIR)
        if os.path.exists(AUDIO_NSFW_DIR) and os.path.isdir(AUDIO_NSFW_DIR):
            dirs.append(AUDIO_NSFW_DIR)
    else:
        if os.path.exists(AUDIO_STANDARD_DIR) and os.path.isdir(AUDIO_STANDARD_DIR):
            dirs.append(AUDIO_STANDARD_DIR)
        if os.path.exists(AUDIO_ROOT_DIR) and os.path.isdir(AUDIO_ROOT_DIR):
            dirs.append(AUDIO_ROOT_DIR)
    return dirs

def scan_audio_library(is_nsfw: bool = False, force: bool = False) -> List[Dict[str, Any]]:
    """
    全量扫描音频库目录并提取文件元数据。
    
    性能与缓存机制：
    - 内存中保留 30 秒缓存有效期，避免高频请求产生磁盘 I/O 瓶颈。
    - 递归识别子文件夹作为专辑/系列 (如《鬼吹灯之精绝古城》)。
    - 计算文件体积 (MB)、修改时间以及生成流式点播 URL。
    """
    global _AUDIO_STD_CACHE, _LAST_SCAN_STD, _AUDIO_NSFW_CACHE, _LAST_SCAN_NSFW
    now = time.time()
    
    if not force:
        if not is_nsfw and _AUDIO_STD_CACHE and (now - _LAST_SCAN_STD < 30):
            return _AUDIO_STD_CACHE
        if is_nsfw and _AUDIO_NSFW_CACHE and (now - _LAST_SCAN_NSFW < 30):
            return _AUDIO_NSFW_CACHE

    audios = []
    seen_files = set()

    for adir in get_audio_dirs(is_nsfw=is_nsfw):
        try:
            for root, dirs, files in os.walk(adir):
                # 排除隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                # 若扫描 audio/ 根目录，避免重复进入 standard/ 或 nsfw/
                if adir == AUDIO_ROOT_DIR:
                    dirs[:] = [d for d in dirs if d not in ('standard', 'nsfw')]

                for fname in sorted(files, key=natural_sort_key):
                    if fname.startswith('.'):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in VALID_EXTS:
                        continue

                    full_p = os.path.join(root, fname)
                    if not os.path.isfile(full_p):
                        continue

                    rel_p = os.path.relpath(full_p, adir).replace('\\', '/')
                    if rel_p in seen_files:
                        continue
                    seen_files.add(rel_p)

                    # 智能解析专辑名称
                    if '/' in rel_p:
                        album = rel_p.split('/')[0]
                    else:
                        album = "未分类音声" if is_nsfw else "经典单曲"

                    try:
                        stat = os.stat(full_p)
                        size_mb = round(stat.st_size / (1024 * 1024), 2)
                        mtime_str = time.strftime('%Y-%m-%d', time.localtime(stat.st_mtime))
                        base_title = os.path.splitext(fname)[0]

                        chapters = []
                        chap_p = full_p.rsplit('.', 1)[0] + '.chapters.json'
                        if os.path.exists(chap_p):
                            try:
                                with open(chap_p, 'r', encoding='utf-8') as cf:
                                    chapters = json.load(cf)
                            except Exception:
                                pass
                        elif ext == '.m4b':
                            try:
                                probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_chapters', full_p]
                                p_res = json.loads(subprocess.check_output(probe_cmd, text=True)).get('chapters', [])
                                for idx, ch in enumerate(p_res, start=1):
                                    st = float(ch.get('start_time', 0))
                                    et = float(ch.get('end_time', 0))
                                    dur_sec = max(0, et - st)
                                    chapters.append({
                                        'index': idx,
                                        'title': ch.get('tags', {}).get('title', f'第{idx}章'),
                                        'start': round(st, 2),
                                        'end': round(et, 2),
                                        'duration_str': f'{int(dur_sec//60):02d}:{int(dur_sec%60):02d}'
                                    })
                            except Exception:
                                pass

                        stream_url = (
                            f"/audio/standard/{urllib.parse.quote(rel_p)}"
                            if not is_nsfw and adir == AUDIO_STANDARD_DIR
                            else f"/api/audio/stream?path={urllib.parse.quote(rel_p)}&nsfw={1 if is_nsfw else 0}"
                        )

                        audios.append({
                            'filename': fname,
                            'rel_path': rel_p,
                            'title': base_title,
                            'album': album,
                            'is_nsfw': is_nsfw,
                            'ext': ext.lstrip('.'),
                            'size_mb': size_mb,
                            'mtime': mtime_str,
                            'path': full_p,
                            'stream_url': stream_url,
                            'chapters': chapters
                        })
                    except Exception:
                        pass
        except Exception as e:
            print("Scan audio err:", e)

    # 全局按照专辑与文件名进行自然数字排序，确保 EP1-10 < EP11-20 < EP104-120
    audios.sort(key=lambda a: (natural_sort_key(a.get('album', '')), natural_sort_key(a.get('filename', ''))))

    if is_nsfw:
        _AUDIO_NSFW_CACHE = audios
        _LAST_SCAN_NSFW = now
    else:
        _AUDIO_STD_CACHE = audios
        _LAST_SCAN_STD = now
        update_standard_catalog_json(audios)
        
    return audios

def update_standard_catalog_json(items: List[Dict[str, Any]]):
    """自动生成并同步 audio/standard_catalog.json，保证非 NSFW 视图瞬时读取与 100% 隔离"""
    catalog_path = os.path.join(SCRIPT_DIR, "audio", "standard_catalog.json")
    try:
        album_counts = {}
        for a in items:
            alb = a.get('album', '经典单曲')
            album_counts[alb] = album_counts.get(alb, 0) + 1
        albums = [{'name': '全部', 'count': len(items)}]
        for alb, cnt in sorted(album_counts.items(), key=lambda x: -x[1]):
            albums.append({'name': alb, 'count': cnt})
        data = {
            'items': items,
            'total': len(items),
            'albums': albums,
            'is_nsfw': False
        }
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Failed to save standard catalog:", e)

def query_audio_library(q: str = "", album: str = "all", is_nsfw: bool = False, page: int = 1, page_size: int = 80) -> Dict[str, Any]:
    """
    带分页、专辑分类统计与模糊检索的音频查询接口。
    """
    all_audios = scan_audio_library(is_nsfw=is_nsfw)
    
    # 统计专辑列表与各专辑曲目数
    album_counts = {}
    for a in all_audios:
        alb = a.get('album', '未分类')
        album_counts[alb] = album_counts.get(alb, 0) + 1
        
    albums = [{'name': '全部', 'count': len(all_audios)}]
    for alb, count in sorted(album_counts.items(), key=lambda x: -x[1]):
        albums.append({'name': alb, 'count': count})

    # 过滤筛选
    matched = all_audios
    if album and album != "all":
        matched = [a for a in matched if a.get('album') == album]

    q = (q or "").strip().lower()
    if q:
        matched = [a for a in matched if q in a['title'].lower() or q in a.get('album', '').lower() or q in a['filename'].lower()]

    total = len(matched)
    start_idx = max(0, (page - 1) * page_size)
    end_idx = start_idx + page_size
    page_items = matched[start_idx:end_idx]

    return {
        'items': page_items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'has_more': end_idx < total,
        'albums': albums,
        'is_nsfw': is_nsfw
    }

def find_audio_file(filename: str, is_nsfw: Optional[bool] = None) -> Optional[str]:
    """
    根据相对路径或文件名在音频根目录下定位物理绝对路径。
    """
    if not filename:
        return None
    
    # 防止路径穿越
    clean_p = filename.replace('\\', '/').strip('/')
    if '..' in clean_p.split('/'):
        return None

    # 确定目标目录集合
    dirs_to_check = []
    if is_nsfw is True:
        dirs_to_check.extend(get_audio_dirs(is_nsfw=True))
    elif is_nsfw is False:
        dirs_to_check.extend(get_audio_dirs(is_nsfw=False))
    else:
        dirs_to_check.extend(get_audio_dirs(is_nsfw=False))
        dirs_to_check.extend(get_audio_dirs(is_nsfw=True))

    # 1. 尝试直接相对路径拼接
    for adir in dirs_to_check:
        full_p = os.path.join(adir, clean_p)
        if os.path.exists(full_p) and os.path.isfile(full_p):
            return full_p

    # 2. 尝试仅按文件名全库扫描
    base_name = os.path.basename(clean_p)
    for adir in dirs_to_check:
        for root, _, files in os.walk(adir):
            if base_name in files:
                full_p = os.path.join(root, base_name)
                if os.path.isfile(full_p):
                    return full_p

    return None

def trash_audio_file(filename: str, is_nsfw: Optional[bool] = None) -> bool:
    """
    按照 AGENTS.md 准则，使用 'gio trash' 安全删除指定音频至系统回收站，并自动刷新双模缓存。
    """
    full_p = find_audio_file(filename, is_nsfw=is_nsfw)
    if not full_p:
        return False
    try:
        res = subprocess.run(['gio', 'trash', full_p], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        scan_audio_library(is_nsfw=False, force=True)
        scan_audio_library(is_nsfw=True, force=True)
        return res.returncode == 0
    except Exception:
        return False
