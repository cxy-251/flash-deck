"""
manga_service.py - Omni Deck 漫画生态核心服务模块
包含：
1. 本地 .cbz 漫画库扫描、封面提取与页面流式解析
2. 禁漫天堂 (JMComic) 在线检索与本子详情解析
3. 异步下载任务队列（支持整本下载、指定章节补充下载）
4. 自动切片混淆还原与单文件 .cbz 封装
5. 临时缓存一键清理与安全删除 (gio trash)
"""

import os
import re
import sys
import time
import zipfile
import shutil
import logging
import threading
import subprocess
import json
from urllib.parse import quote as urllib_quote
import jmcomic
jmcomic.JmModuleConfig.FLAG_API_CLIENT_AUTO_UPDATE_DOMAIN = False
from typing import List, Dict, Optional, Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANGA_DIR = os.path.join(SCRIPT_DIR, "manga")
NOVELS_DIR = os.path.join(SCRIPT_DIR, "novels")
TEMP_DIR = os.path.join(MANGA_DIR, ".temp")
QUEUE_FILE = os.path.join(MANGA_DIR, ".download_queue.json")
QUEUE_LOCK = threading.Lock()

os.makedirs(MANGA_DIR, exist_ok=True)
os.makedirs(NOVELS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

import queue

# 异步回调事件推送系统 (Server-Sent Events 广播总线)
EVENT_LISTENERS: set = set()
LISTENERS_LOCK = threading.Lock()

def add_event_listener(q: queue.Queue):
    """注册一个 SSE 事件监听队列，用于实时推送后台下载进度与队列变更"""
    with LISTENERS_LOCK:
        EVENT_LISTENERS.add(q)

def remove_event_listener(q: queue.Queue):
    """注销已断开连接的 SSE 事件监听队列"""
    with LISTENERS_LOCK:
        EVENT_LISTENERS.discard(q)

def broadcast_manga_event(event_data: dict):
    """向所有连接的 SSE 客户端广播漫画/小说异步状态事件"""
    with LISTENERS_LOCK:
        for q in list(EVENT_LISTENERS):
            try:
                q.put_nowait(event_data)
            except Exception:
                pass

# 活跃下载任务字典: task_id -> task_info
DOWNLOAD_TASKS: Dict[str, Dict[str, Any]] = {}
TASKS_LOCK = threading.Lock()

# 初始化 jmcomic 客户端 (懒加载)
_jm_client = None
_client_lock = threading.Lock()

def get_jm_client():
    """获取或线程安全地单例初始化 JMComic API 客户端"""
    global _jm_client
    with _client_lock:
        if _jm_client is None:
            import jmcomic
            jmcomic.JmModuleConfig.FLAG_API_CLIENT_AUTO_UPDATE_DOMAIN = False
            opt = jmcomic.JmOption.default()
            _jm_client = opt.new_jm_client()
        return _jm_client

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符，截断过长名称并防止路径穿越"""
    clean = re.sub(r'[\/\\:\*\?"<>\|]', '_', name).strip()
    return clean[:120] if len(clean) > 120 else clean

# =========================================================================
# 待下载队列磁盘持久化系统 (防掉电、防意外退出、断点续传，支持漫画/小说独立分流)
# =========================================================================

def get_queue_file(target_dir: str = 'manga') -> str:
    if str(target_dir).lower() in ('novels', 'novel'):
        return os.path.join(NOVELS_DIR, ".download_queue.json")
    return os.path.join(MANGA_DIR, ".download_queue.json")

def get_persistent_queue(target_dir: str = 'manga') -> List[Dict[str, Any]]:
    """读取保存在磁盘上的待下载作品列表（支持 manga/novels 独立分流）"""
    q_file = get_queue_file(target_dir)
    with QUEUE_LOCK:
        if not os.path.exists(q_file):
            return []
        try:
            with open(q_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

def save_persistent_queue(items: List[Dict[str, Any]], target_dir: str = 'manga') -> None:
    """持久化待下载作品列表至磁盘"""
    q_file = get_queue_file(target_dir)
    dir_flag = 'novels' if str(target_dir).lower() in ('novels', 'novel') else 'manga'
    with QUEUE_LOCK:
        try:
            with open(q_file, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            broadcast_manga_event({'type': 'queue_updated', 'queue': items, 'dir': dir_flag})
        except Exception as e:
            print(f"[{dir_flag}] Failed to save queue file: {e}")

def remove_from_persistent_queue(album_id: str, target_dir: str = 'manga') -> None:
    """当某部作品成功下载打包为 .cbz 后，自动从未完成队列中剔除"""
    q_file = get_queue_file(target_dir)
    dir_flag = 'novels' if str(target_dir).lower() in ('novels', 'novel') else 'manga'
    with QUEUE_LOCK:
        if not os.path.exists(q_file):
            return
        try:
            with open(q_file, 'r', encoding='utf-8') as f:
                items = json.load(f)
            aid_str = str(album_id).strip()
            new_items = [x for x in items if str(x.get('id', '')).strip() != aid_str]
            with open(q_file, 'w', encoding='utf-8') as f:
                json.dump(new_items, f, ensure_ascii=False, indent=2)
            broadcast_manga_event({'type': 'album_completed', 'album_id': aid_str, 'queue': new_items, 'dir': dir_flag})
        except Exception:
            pass

# =========================================================================
# 一、 本地 CBZ 漫画库扫描与页面读取
# =========================================================================

def urllib_quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text)

def resolve_file_path(filename: str, target_dir: str = "") -> Optional[str]:
    """根据目标目录解析 .cbz 物理文件绝对路径"""
    if str(target_dir).lower() in ('novels', 'novel'):
        p = os.path.join(NOVELS_DIR, filename)
        if os.path.exists(p):
            return p
    elif str(target_dir).lower() in ('manga', '0'):
        p = os.path.join(MANGA_DIR, filename)
        if os.path.exists(p):
            return p
    p1 = os.path.join(MANGA_DIR, filename)
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(NOVELS_DIR, filename)
    if os.path.exists(p2):
        return p2
    return None

def get_local_library(q: str = "", target_dir: str = "manga") -> List[Dict[str, Any]]:
    """扫描本地漫画(manga)或小说(novels)目录下的所有 .cbz 文件并解析元数据"""
    base_dir = NOVELS_DIR if str(target_dir).lower() in ('novels', 'novel') else MANGA_DIR
    if not os.path.exists(base_dir):
        return []

    q = (q or "").lower().strip()
    items = []

    for fname in os.listdir(base_dir):
        if not fname.lower().endswith(('.cbz', '.txt', '.epub')):
            continue
        if fname.startswith('.'):
            continue

        full_path = os.path.join(base_dir, fname)
        if not os.path.isfile(full_path):
            continue

        base_name = os.path.splitext(fname)[0]
        ext = os.path.splitext(fname)[1].lower().lstrip('.')
        if q and (q not in base_name.lower()):
            continue

        stat = os.stat(full_path)
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        mtime_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))

        page_count = 0
        has_cover = False
        if ext == 'cbz':
            try:
                with zipfile.ZipFile(full_path, 'r') as zf:
                    namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
                    img_files = [n for n in namelist if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))]
                    page_count = len(img_files)
                    has_cover = page_count > 0
            except Exception:
                pass

        dir_flag = 'novels' if base_dir == NOVELS_DIR else 'manga'
        items.append({
            'filename': fname,
            'title': base_name,
            'ext': ext,
            'dir': dir_flag,
            'size_mb': size_mb,
            'mtime': mtime_str,
            'page_count': page_count,
            'has_cover': has_cover,
            'cover_url': f'/api/manga/cover?name={urllib_quote(fname)}&dir={dir_flag}',
        })

    # 按修改时间倒序排列 (新收录的排前面)
    items.sort(key=lambda x: x.get('mtime', ''), reverse=True)
    return items

def get_cbz_cover_bytes(filename: str, target_dir: str = "") -> Optional[bytes]:
    """从 .cbz 文件中直接读取封面图片二进制数据"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return None

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
            img_files = sorted([n for n in namelist if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))])
            if not img_files:
                return None
            cover_entry = next((f for f in img_files if 'cover' in os.path.basename(f).lower()), img_files[0])
            return zf.read(cover_entry)
    except Exception:
        return None

def get_cbz_pages_list(filename: str, target_dir: str = "") -> List[str]:
    """获取 .cbz 内部所有排好序的图片文件名列表"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return []

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
            img_files = sorted([n for n in namelist if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp'))])
            return img_files
    except Exception:
        return []

get_cbz_pages = get_cbz_pages_list

def get_cbz_page_bytes(filename: str, page_name: str, target_dir: str = "") -> Optional[bytes]:
    """流式读取 .cbz 内指定页面的图片二进制流"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return None

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            return zf.read(page_name)
    except Exception:
        return None

MANGA_COVER_CACHE_DIR = os.path.expanduser('~/.cache/omni_manga_covers')
os.makedirs(MANGA_COVER_CACHE_DIR, exist_ok=True)

def get_online_cover_bytes(album_id: str) -> Optional[bytes]:
    """通过官方移动端 API 安全通道获取并本地缓存禁漫线上作品的封面图"""
    aid = str(album_id).strip()
    if not aid or not aid.isdigit():
        return None

    cached = os.path.join(MANGA_COVER_CACHE_DIR, f'{aid}.jpg')
    if os.path.exists(cached):
        try:
            with open(cached, 'rb') as f:
                return f.read()
        except Exception:
            pass

    try:
        client = get_jm_client()
        url = jmcomic.JmcomicText.get_album_cover_url(aid)
        resp = client.get_jm_image(url)
        data = resp.content
        if data and len(data) > 500:
            with open(cached, 'wb') as f:
                f.write(data)
            return data
    except Exception as e:
        print(f"[Manga] Failed to fetch online cover for JM{aid}: {e}")
    return None

# =========================================================================
# 二、 禁漫天堂 (JMComic) 在线检索与本子详情解析
# =========================================================================

def search_jm_online(query: str, page: int = 1, category: str = '0', order_by: str = '') -> Dict[str, Any]:
    """调用禁漫天堂 API 搜索在线漫画/小说，支持单个/多个编号与关键词检索，支持多种排序方式 (mv, mr, tf, tr, mp, md)"""
    q = query.strip()
    client = get_jm_client()

    # 默认排序规则：小说默认 mr (最新收录)，漫画默认 mv (最多点击)
    if not order_by:
        order_by = 'mr' if category == 'novel' else 'mv'

    # 1. 小说专区无搜索词时，自动推荐禁漫小说
    if category == 'novel' and not q:
        try:
            cf = client.categories_filter(category='novel', order_by=order_by, time='a', page=page)
            results = []
            for item in list(cf):
                if isinstance(item, tuple) and len(item) >= 2:
                    aid_item, title_item = str(item[0]), str(item[1])
                    results.append({
                        'id': aid_item,
                        'title': title_item,
                        'cover_url': f'/api/manga/online_cover?id={aid_item}',
                    })
                elif hasattr(item, 'album_id') and hasattr(item, 'title'):
                    aid_item = str(item.album_id)
                    results.append({
                        'id': aid_item,
                        'title': str(item.title),
                        'cover_url': f'/api/manga/online_cover?id={aid_item}',
                    })
            total_count = getattr(cf, 'total', len(results))
            page_count = getattr(cf, 'page_count', 1)
            return {
                'total': total_count,
                'page': page,
                'page_count': page_count,
                'has_more': page < page_count or len(results) >= 20,
                'results': results
            }
        except Exception as e:
            return {'total': 0, 'page': page, 'page_count': 1, 'has_more': False, 'error': str(e), 'results': []}

    if not q:
        return {'total': 0, 'results': []}

    # 检查是否包含多个数字编号（如逗号、空格、分号隔开的多个 ID）
    tokens = [t.strip() for t in re.split(r'[\s,，;；\n\r]+', q) if t.strip()]
    pure_ids = [t for t in tokens if t.isdigit()]

    if len(pure_ids) > 1:
        results = []
        for aid in pure_ids:
            try:
                detail = get_jm_album_detail(aid)
                results.append({
                    'id': str(detail.get('id', aid)),
                    'title': detail.get('title', f'JM{aid}'),
                    'author': detail.get('author', ''),
                    'chapter_count': len(detail.get('chapters', [])),
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                    'tags': detail.get('tags', []),
                })
            except Exception:
                results.append({
                    'id': str(aid),
                    'title': f'JM{aid}',
                    'author': '',
                    'chapter_count': 1,
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                    'tags': [],
                })
        return {
            'total': len(results),
            'is_multi_id': True,
            'results': results
        }

    # 单个编号或链接
    aid = None
    if len(pure_ids) == 1 and len(tokens) == 1:
        aid = pure_ids[0]
    else:
        m = re.search(r'(?:album|photo)[/=](\d+)', q)
        if m:
            aid = m.group(1)

    if aid:
        try:
            detail = get_jm_album_detail(aid)
            return {
                'total': 1,
                'is_direct_id': True,
                'results': [{
                    'id': str(detail.get('id', aid)),
                    'title': detail.get('title', f'JM{aid}'),
                    'author': detail.get('author', ''),
                    'chapter_count': len(detail.get('chapters', [])),
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                    'tags': detail.get('tags', []),
                }]
            }
        except Exception:
            return {
                'total': 1,
                'is_direct_id': True,
                'results': [{
                    'id': str(aid),
                    'title': f'JM{aid}',
                    'author': '',
                    'chapter_count': 1,
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                    'tags': [],
                }]
            }

    try:
        if category == 'novel':
            # 严密使用禁漫 API 的 c=novel 和 category_id=novel 过滤参数
            url = f'/search?c=novel&category_id=novel&search_query={urllib_quote(q)}&page={page}&o={order_by}'
            resp = client.req_api(url)
            data = resp.model_data
            content_list = data.get('content', [])
            results = []
            for item in content_list:
                aid_item = str(item.get('id', ''))
                title_item = str(item.get('name') or item.get('title') or f'JM{aid_item}')
                if aid_item:
                    results.append({
                        'id': aid_item,
                        'title': title_item,
                        'cover_url': f'/api/manga/online_cover?id={aid_item}',
                    })
            total_count = int(data.get('total', len(results)) or len(results))
            page_count = int(data.get('page_count', (total_count // 80) + 1) or 1)
            return {
                'total': total_count,
                'page': page,
                'page_count': page_count,
                'has_more': page < page_count or len(results) >= 80,
                'results': results
            }
        else:
            # 漫画专区
            search_res = client.search_site(search_query=q, page=page, order_by=order_by)
            results = []
            for item in list(search_res):
                if isinstance(item, tuple) and len(item) >= 2:
                    aid_item, title_item = str(item[0]), str(item[1])
                    results.append({
                        'id': aid_item,
                        'title': title_item,
                        'cover_url': f'/api/manga/online_cover?id={aid_item}',
                    })
                elif hasattr(item, 'album_id') and hasattr(item, 'title'):
                    aid_item = str(item.album_id)
                    results.append({
                        'id': aid_item,
                        'title': str(item.title),
                        'cover_url': f'/api/manga/online_cover?id={aid_item}',
                    })
            total_count = getattr(search_res, 'total', len(results))
            page_count = getattr(search_res, 'page_count', 1)
            return {
                'total': total_count,
                'page': page,
                'page_count': page_count,
                'has_more': page < page_count,
                'results': results
            }
    except Exception as e:
        return {'total': 0, 'page': page, 'page_count': 1, 'has_more': False, 'error': str(e), 'results': []}

def get_jm_album_detail(album_id: str) -> Dict[str, Any]:
    """获取本子详细章节与元数据"""
    client = get_jm_client()
    detail = client.get_album_detail(album_id)

    chapters = []
    for photo in list(detail):
        pid = str(getattr(photo, 'photo_id', getattr(photo, 'id', '')))
        title = getattr(photo, 'title', f'第{len(chapters)+1}话')
        if not str(title).strip():
            title = f'第{len(chapters)+1}话'
        chapters.append({
            'photo_id': pid,
            'title': str(title).strip(),
            'index': len(chapters) + 1
        })

    return {
        'id': str(album_id),
        'title': detail.title,
        'author': getattr(detail, 'author', ''),
        'description': getattr(detail, 'description', ''),
        'tags': getattr(detail, 'tags', []),
        'cover_url': f'https://cdn-msp.jmapinode2.cc/media/albums/{album_id}.jpg',
        'chapters': chapters,
    }

# =========================================================================
# 三、 异步下载与单文件 CBZ 自动打包
# =========================================================================

def create_jm_option_for_dir(base_dir: str):
    """创建定制 JmOption，保证切片解密并存入指定目录"""
    import jmcomic
    opt = jmcomic.JmOption.default()
    opt.dir_rule.base_dir = base_dir
    opt.dir_rule.rule = 'Bd_Pname'
    opt.download_image_decode = True
    return opt

def pack_folder_to_cbz(source_folder: str, target_cbz_path: str, cover_file: Optional[str] = None):
    """将下载好的漫画文件夹整整齐齐地封装为单个 .cbz 容器"""
    os.makedirs(os.path.dirname(target_cbz_path), exist_ok=True)
    temp_zip = target_cbz_path + ".tmp"

    with zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if cover_file and os.path.exists(cover_file):
            zf.write(cover_file, arcname="cover.jpg")

        for root, dirs, files in os.walk(source_folder):
            dirs.sort()
            for f in sorted(files):
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, source_folder)
                    zf.write(full_p, arcname=rel_p)

    if os.path.exists(target_cbz_path):
        os.remove(target_cbz_path)
    os.rename(temp_zip, target_cbz_path)

def _download_thread(task_id: str, album_id: str, chapter_ids: Optional[List[str]], pack_cbz: bool, clean_temp: bool, dest_dir: str = 'manga'):
    """后台下载执行线程"""
    import jmcomic

    task = DOWNLOAD_TASKS.get(task_id)
    if not task:
        return

    album_temp_dir = os.path.join(TEMP_DIR, album_id)
    os.makedirs(album_temp_dir, exist_ok=True)
    opt = create_jm_option_for_dir(album_temp_dir)
    target_dir_path = NOVELS_DIR if str(dest_dir).lower() in ('novels', 'novel') else MANGA_DIR

    try:
        task['status'] = 'fetching_meta'
        task['message'] = '正在获取章节元数据...'
        client = get_jm_client()
        detail = client.get_album_detail(album_id)

        title = detail.title
        safe_title = sanitize_filename(title)
        task['title'] = title
        target_cbz_name = f"{safe_title}.cbz"
        task['target_cbz'] = target_cbz_name
        target_cbz_path = os.path.join(target_dir_path, target_cbz_name)

        if pack_cbz and os.path.exists(target_cbz_path) and os.path.getsize(target_cbz_path) > 10240 and (not chapter_ids):
            task['status'] = 'completed'
            task['percent'] = 100.0
            task['message'] = f"单文件《{target_cbz_name}》本地已收录，无需重复下载！"
            return

        if chapter_ids and len(chapter_ids) > 0:
            target_photos = [p for p in list(detail) if str(getattr(p, 'photo_id', getattr(p, 'id', ''))) in chapter_ids]
            if not target_photos:
                target_photos = list(detail)
        else:
            target_photos = list(detail)

        total_chapters = len(target_photos)
        task['total_chapters'] = total_chapters
        task['downloaded_chapters'] = 0

        for idx, photo in enumerate(target_photos, 1):
            pid = getattr(photo, 'photo_id', getattr(photo, 'id', ''))
            task['status'] = 'downloading'
            task['current_chapter'] = f"第 {idx}/{total_chapters} 话"
            task['percent'] = round((idx - 1) / total_chapters * 85, 1)
            task['message'] = f"正在下载解密: {task['current_chapter']} (ID: {pid})..."

            jmcomic.download_photo(pid, option=opt)
            task['downloaded_chapters'] = idx

        if pack_cbz:
            task['status'] = 'packing'
            task['percent'] = 90.0
            task['message'] = '正在合并全章节图片并封装为单文件 .cbz 容器...'

            target_cbz_path = os.path.join(target_dir_path, target_cbz_name)
            pack_folder_to_cbz(album_temp_dir, target_cbz_path)

            if clean_temp:
                task['status'] = 'cleaning'
                task['percent'] = 98.0
                task['message'] = '正在清理下载临时切片碎片...'
                shutil.rmtree(album_temp_dir, ignore_errors=True)

            remove_from_persistent_queue(album_id, target_dir=dest_dir)

        task['status'] = 'completed'
        task['percent'] = 100.0
        task['message'] = f"下载与打包已完成！单文件已就绪: {target_cbz_name}"

    except Exception as e:
        task['status'] = 'failed'
        task['error'] = str(e)
        task['message'] = f"下载遇到异常: {e}"

def start_download_task(album_id: str, chapter_ids: Optional[List[str]] = None, pack_cbz: bool = True, clean_temp: bool = True, dest_dir: str = 'manga') -> str:
    """启动一个异步下载任务，返回 task_id"""
    task_id = f"task_{album_id}_{int(time.time())}"
    with TASKS_LOCK:
        DOWNLOAD_TASKS[task_id] = {
            'task_id': task_id,
            'album_id': str(album_id),
            'title': f"JM{album_id}",
            'status': 'queued',
            'percent': 0.0,
            'message': '任务已进入队列...',
            'current_chapter': '',
            'total_chapters': 0,
            'downloaded_chapters': 0,
            'target_cbz': '',
            'dest_dir': dest_dir,
            'created_at': time.time(),
        }

    t = threading.Thread(
        target=_download_thread,
        args=(task_id, str(album_id), chapter_ids, pack_cbz, clean_temp, dest_dir),
        daemon=True
    )
    t.start()
    return task_id

def get_ranking_albums(rank_type: str = 'week', page: int = 1, count: int = 80) -> List[Dict[str, Any]]:
    """获取禁漫官方榜单列表 (week=每周必看, month=每月必看, day=今日必看)"""
    client = get_jm_client()
    try:
        if rank_type == 'month':
            search_page = client.month_ranking(page=page)
        elif rank_type == 'day':
            search_page = client.day_ranking(page=page)
        else:
            search_page = client.week_ranking(page=page)

        items = []
        for it in list(search_page)[:count]:
            if isinstance(it, tuple) and len(it) >= 2:
                aid, title = str(it[0]), str(it[1])
                items.append({
                    'id': aid,
                    'title': title,
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                })
            elif hasattr(it, 'album_id') and hasattr(it, 'title'):
                aid, title = str(it.album_id), str(it.title)
                items.append({
                    'id': aid,
                    'title': title,
                    'cover_url': f'/api/manga/online_cover?id={aid}',
                })
        return items
    except Exception as e:
        logging.error(f"Failed to fetch ranking albums ({rank_type}): {e}")
        return []

def _batch_download_worker(task_id: str, album_ids: List[str], pack_cbz: bool, clean_temp: bool, dest_dir: str = 'manga'):
    """后台批量连轴转下载工作线程"""
    import jmcomic
    task = DOWNLOAD_TASKS.get(task_id)
    if not task:
        return

    target_dir_path = NOVELS_DIR if str(dest_dir).lower() in ('novels', 'novel') else MANGA_DIR

    # 过滤空 ID 并去重
    seen = set()
    clean_ids = []
    for aid in album_ids:
        c = str(aid).strip()
        if c and c.isdigit() and c not in seen:
            seen.add(c)
            clean_ids.append(c)

    task['clean_ids'] = list(clean_ids)
    task['total_albums'] = len(task['clean_ids'])
    task['completed_albums'] = 0

    if not task['clean_ids']:
        task['status'] = 'completed'
        task['percent'] = 100.0
        task['message'] = '待下载 ID 列表为空！'
        return

    client = get_jm_client()

    curr_idx = 0
    while curr_idx < len(task['clean_ids']):
        aid = task['clean_ids'][curr_idx]
        i = curr_idx + 1
        total_albums = len(task['clean_ids'])
        task['total_albums'] = total_albums

        album_temp_dir = os.path.join(TEMP_DIR, aid)
        os.makedirs(album_temp_dir, exist_ok=True)
        opt = create_jm_option_for_dir(album_temp_dir)

        try:
            task['status'] = 'downloading'
            task['current_album_index'] = i
            base_percent = round(((i - 1) / total_albums) * 100, 1)
            task['percent'] = base_percent
            task['title'] = f"批量连轴转队列 ({i}/{total_albums})"
            task['message'] = f"[{i}/{total_albums}] 正在获取 JM{aid} 章节目录与详情..."

            detail = client.get_album_detail(aid)
            safe_title = sanitize_filename(detail.title)
            target_cbz_name = f"{safe_title}.cbz"
            target_cbz_path = os.path.join(target_dir_path, target_cbz_name)
            task['current_album_title'] = detail.title

            if pack_cbz and os.path.exists(target_cbz_path) and os.path.getsize(target_cbz_path) > 10240:
                task['message'] = f"[{i}/{total_albums}] 《{safe_title[:18]}》 本地已存在完整 CBZ，自动跳过..."
                remove_from_persistent_queue(aid)
                task['completed_albums'] = i
                task['percent'] = round((i / total_albums) * 100, 1)
                curr_idx += 1
                continue

            photos = list(detail)
            total_photos = len(photos)

            for p_idx, photo in enumerate(photos, 1):
                pid = getattr(photo, 'photo_id', getattr(photo, 'id', ''))
                inner_pct = (p_idx / max(total_photos, 1)) * (100.0 / total_albums)
                task['percent'] = round(base_percent + inner_pct * 0.88, 1)
                task['message'] = f"[{i}/{total_albums}] 《{safe_title[:18]}》 正在解密下载第 {p_idx}/{total_photos} 话..."
                broadcast_manga_event({'type': 'progress', 'task': task})
                jmcomic.download_photo(pid, option=opt)

            if pack_cbz:
                task['message'] = f"[{i}/{total_albums}] 正在封箱打包 《{safe_title[:18]}》 为单文件 CBZ..."
                target_cbz_path = os.path.join(target_dir_path, target_cbz_name)
                pack_folder_to_cbz(album_temp_dir, target_cbz_path)

            if clean_temp:
                shutil.rmtree(album_temp_dir, ignore_errors=True)

            remove_from_persistent_queue(aid, target_dir=dest_dir)
            task['completed_albums'] = i
            task['percent'] = round((i / total_albums) * 100, 1)
            broadcast_manga_event({'type': 'progress', 'task': task})

        except Exception as e:
            logging.error(f"Error downloading album {aid}: {e}")
            task['message'] = f"[{i}/{total_albums}] JM{aid} 遇阻 ({e})，自动轮转下一部..."
            broadcast_manga_event({'type': 'progress', 'task': task})
            time.sleep(1)

        curr_idx += 1

    total_albums = len(task['clean_ids'])
    task['status'] = 'completed'
    task['percent'] = 100.0
    task['message'] = f"🎉 批量连轴转已全部完成！已成功收录 {task.get('completed_albums', 0)}/{total_albums} 部单文件！"
    broadcast_manga_event({'type': 'batch_completed', 'task': task})

def start_batch_download_task(album_ids: List[str], pack_cbz: bool = True, clean_temp: bool = True, dest_dir: str = 'manga') -> str:
    """启动批量连轴转下载任务，若已有队列正在运行则无缝追加到末尾"""
    with TASKS_LOCK:
        for tid, t_info in DOWNLOAD_TASKS.items():
            if t_info.get('is_batch') and t_info.get('status') in ('queued', 'downloading'):
                existing = t_info.get('clean_ids', [])
                added_count = 0
                for aid in album_ids:
                    aid_str = str(aid).strip()
                    if aid_str and aid_str not in existing:
                        existing.append(aid_str)
                        added_count += 1
                t_info['total_albums'] = len(existing)
                t_info['title'] = f"批量连轴转队列 (当前第 {t_info.get('current_album_index', 1)}/{len(existing)} 部)"
                t_info['message'] = f"已将新加入的 {added_count} 部追加至当前下载队伍末尾 (总计 {len(existing)} 部)！"
                return tid

        task_id = f"batch_{int(time.time())}"
        DOWNLOAD_TASKS[task_id] = {
            'task_id': task_id,
            'is_batch': True,
            'title': f"批量连轴转队列 (共 {len(album_ids)} 部)",
            'status': 'queued',
            'percent': 0.0,
            'message': f'准备连轴转下载 {len(album_ids)} 部作品...',
            'total_albums': len(album_ids),
            'completed_albums': 0,
            'dest_dir': dest_dir,
            'created_at': time.time(),
        }

    t = threading.Thread(
        target=_batch_download_worker,
        args=(task_id, album_ids, pack_cbz, clean_temp, dest_dir),
        daemon=True
    )
    t.start()
    return task_id

def get_all_tasks() -> List[Dict[str, Any]]:
    """获取所有下载任务状态"""
    with TASKS_LOCK:
        return sorted(list(DOWNLOAD_TASKS.values()), key=lambda x: x.get('created_at', 0), reverse=True)

def manual_pack_manga(folder_name: str, target_name: Optional[str] = None, dest_dir: str = 'manga') -> bool:
    """将 .temp 下的一个目录手动打包为 .cbz"""
    src = os.path.join(TEMP_DIR, folder_name)
    if not os.path.isdir(src):
        return False
    cbz_name = sanitize_filename(target_name or folder_name) + ".cbz"
    target_dir_path = NOVELS_DIR if str(dest_dir).lower() in ('novels', 'novel') else MANGA_DIR
    dst = os.path.join(target_dir_path, cbz_name)
    pack_folder_to_cbz(src, dst)
    return True

def clean_all_temp_files() -> int:
    """一键清理 .temp/ 目录下的所有临时下载切片碎片"""
    count = 0
    if os.path.exists(TEMP_DIR):
        for item in os.listdir(TEMP_DIR):
            p = os.path.join(TEMP_DIR, item)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    count += 1
                else:
                    os.remove(p)
                    count += 1
            except Exception:
                pass
    return count

def trash_manga_file(filename: str, target_dir: str = "") -> bool:
    """严格按照 AGENTS.md 准则，使用 gio trash 安全删除漫画/小说至回收站"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return False
    res = subprocess.run(['gio', 'trash', cbz_path], capture_output=True)
    return res.returncode == 0
