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

import media_index
from app_config import find_library_dirs, get_primary_dir

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 本文件在 services/ 下，项目根路径是上一级
# 主库位置（新下载/正在处理的都落这）——不写死绝对路径，从 app_config.py 派生。
MEDIA_LIBRARY_DIR = get_primary_dir("media_library")
AUDIO_STANDARD_DIR = os.path.join(MEDIA_LIBRARY_DIR, "audio", "standard")
AUDIO_NSFW_DIR = os.path.join(MEDIA_LIBRARY_DIR, "audio", "nsfw")
AUDIO_ROOT_DIR = os.path.join(MEDIA_LIBRARY_DIR, "audio")
_LEGACY_AUDIO_ROOT_DIR = os.path.join(SCRIPT_DIR, "audio")  # 迁移期间兼容，等搬空了这条自然没内容

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
    获取指定模式下所有已挂载并存在的音频根目录列表——主库（新下载落地）+ 已配置资源库
    根路径下的 media_library/audio/standard(或 nsfw)（SD 卡等归档位置）+ omni-deck 自己
    目录下的旧版位置（迁移期间兼容）。
    - Telegram 导出的那批 NSFW 音频已经并入 media_library/audio/nsfw（SD 卡那份），
      不再是独立的 EXTERNAL_AUDIO_DIR 特例，跟其它 NSFW 音频走同一套查找逻辑。
    - "audio/ 根目录直接扔文件、不分 standard/nsfw"这种兜底用法只看主库+旧版位置，
      不延伸到 SD 卡（这本来就是给零散文件用的边缘用法，没必要跟着搬）。
    """
    dirs = []
    if is_nsfw:
        for d in [AUDIO_NSFW_DIR] + find_library_dirs("media_library", "audio", "nsfw"):
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
        legacy = os.path.join(_LEGACY_AUDIO_ROOT_DIR, "nsfw")
        if os.path.isdir(legacy) and legacy not in dirs:
            dirs.append(legacy)
    else:
        for d in [AUDIO_STANDARD_DIR] + find_library_dirs("media_library", "audio", "standard"):
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
        legacy_std = os.path.join(_LEGACY_AUDIO_ROOT_DIR, "standard")
        if os.path.isdir(legacy_std) and legacy_std not in dirs:
            dirs.append(legacy_std)
        if os.path.isdir(AUDIO_ROOT_DIR) and AUDIO_ROOT_DIR not in dirs:
            dirs.append(AUDIO_ROOT_DIR)
        if os.path.isdir(_LEGACY_AUDIO_ROOT_DIR) and _LEGACY_AUDIO_ROOT_DIR not in dirs:
            dirs.append(_LEGACY_AUDIO_ROOT_DIR)
    return dirs

def _rich_parse_audio(full_p: str) -> Dict[str, Any]:
    """读章节信息：优先 .chapters.json 旁车文件，其次对 .m4b 跑一次 ffprobe。
    只在文件新增/变动时被 media_index 调用（ffprobe 是这里最贵的一步）。"""
    ext = os.path.splitext(full_p)[1].lower()
    chapters: List[Dict[str, Any]] = []
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
    return {'chapters': chapters}


def _iter_audio_files_in_dir(adir: str):
    """遍历一个音频库候选目录，yield 出其中所有符合扩展名的文件路径与元信息。

    从 scan_audio_library() 拆出来的文件收集逻辑：本身是 os.walk 一层 + 逐文件名一层，
    拆开后调用方不用再叠第三层循环。

    Args:
        adir: 要扫描的音频库根路径。

    Yields:
        tuple[str, str, str, float, int]: (完整路径, 文件名, 相对路径, mtime, size)。
    """
    for root, dirs, fnames in os.walk(adir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        if adir in (AUDIO_ROOT_DIR, _LEGACY_AUDIO_ROOT_DIR):
            dirs[:] = [d for d in dirs if d not in ('standard', 'nsfw')]
        for fname in fnames:
            if fname.startswith('.'):
                continue
            if os.path.splitext(fname)[1].lower() not in VALID_EXTS:
                continue
            full_p = os.path.join(root, fname)
            rel_p = os.path.relpath(full_p, adir).replace('\\', '/')
            try:
                st = os.stat(full_p)
                if not os.path.isfile(full_p):
                    continue
            except OSError:
                continue
            yield full_p, fname, rel_p, st.st_mtime, st.st_size


def scan_audio_library(is_nsfw: bool = False, force: bool = False) -> List[Dict[str, Any]]:
    """
    扫描音频库目录并返回文件元数据列表。

    - 章节信息（.chapters.json / .m4b ffprobe）走 media_index 持久化索引：只有新增/
      变动的文件才真去读，其余吃 SQLite 缓存。冷启动第一次照旧慢，之后秒出。
    - 上面再叠一层 30 秒内存缓存，挡高频请求。
    - 递归识别子文件夹作为专辑/系列。
    """
    global _AUDIO_STD_CACHE, _LAST_SCAN_STD, _AUDIO_NSFW_CACHE, _LAST_SCAN_NSFW
    now = time.time()

    if not force:
        if not is_nsfw and _AUDIO_STD_CACHE and (now - _LAST_SCAN_STD < 30):
            return _AUDIO_STD_CACHE
        if is_nsfw and _AUDIO_NSFW_CACHE and (now - _LAST_SCAN_NSFW < 30):
            return _AUDIO_NSFW_CACHE

    kind = 'audiolib:nsfw' if is_nsfw else 'audiolib:std'
    files = []
    fs_info = {}          # full_p -> (fname, rel_p, album, size, mtime, adir)
    seen_files = set()

    for adir in get_audio_dirs(is_nsfw=is_nsfw):
        try:
            for full_p, fname, rel_p, mtime, size in _iter_audio_files_in_dir(adir):
                if rel_p in seen_files:
                    continue
                seen_files.add(rel_p)
                album = rel_p.split('/')[0] if '/' in rel_p else ("未分类音声" if is_nsfw else "经典单曲")
                files.append((full_p, mtime, size))
                fs_info[full_p] = (fname, rel_p, album, size, mtime, adir)
        except Exception as e:
            print("Scan audio err:", e)

    metas = media_index.diff_scan(kind, files, _rich_parse_audio, sync_limit=30)

    audios = []
    for full_p, (fname, rel_p, album, size, mtime, adir) in fs_info.items():
        ext = os.path.splitext(fname)[1].lower()
        # 统一走 /api/audio/stream（真支持 Range/206 分段），别再用 /audio/standard/ 这条
        # 静态路径——stdlib 的 SimpleHTTPRequestHandler 不认 Range 头，请求局部字节还是把
        # 整个文件（有声书动辄几百 MB）原样吐回去，不能拖进度、大文件基本等于播不了。
        stream_url = f"/api/audio/stream?path={urllib.parse.quote(rel_p)}&nsfw={1 if is_nsfw else 0}"
        audios.append({
            'filename': fname,
            'rel_path': rel_p,
            'title': os.path.splitext(fname)[0],
            'album': album,
            'is_nsfw': is_nsfw,
            'ext': ext.lstrip('.'),
            'size_mb': round(size / (1024 * 1024), 2),
            'mtime': time.strftime('%Y-%m-%d', time.localtime(mtime)),
            'path': full_p,
            'stream_url': stream_url,
            'chapters': (metas.get(full_p) or {}).get('chapters', []),
        })

    audios.sort(key=lambda a: (natural_sort_key(a.get('album', '')), natural_sort_key(a.get('filename', ''))))

    if is_nsfw:
        _AUDIO_NSFW_CACHE = audios
        _LAST_SCAN_NSFW = now
    else:
        _AUDIO_STD_CACHE = audios
        _LAST_SCAN_STD = now
        update_standard_catalog_json(audios)
        
    return audios

def update_standard_catalog_json(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成"非 NSFW 有声书目录"这份数据（给前端一次性拿标题/专辑/播放地址用）。
    顺手落一份 audio/standard_catalog.json 到磁盘方便手动查看，但谁都不该依赖那份磁盘文件本身
    的新鲜度——main.py 的路由直接用这个函数的返回值，不读盘，从根上不会再冻结成旧版本。"""
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
    try:
        os.makedirs(AUDIO_ROOT_DIR, exist_ok=True)
        catalog_path = os.path.join(AUDIO_ROOT_DIR, "standard_catalog.json")
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Failed to save standard catalog:", e)
    return data


def get_standard_catalog(force: bool = False) -> Dict[str, Any]:
    """非 NSFW 有声书目录——永远现扫现吐，不读那份磁盘快照。"""
    items = scan_audio_library(is_nsfw=False, force=force)
    return update_standard_catalog_json(items)

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
