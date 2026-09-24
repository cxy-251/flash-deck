"""
Omni Deck 漫画生态核心服务
包含：
1. 本地 .cbz 漫画库扫描、封面提取与页面流式解析
2. 禁漫天堂 (JMComic) 在线检索与本子详情解析
3. 异步下载任务队列（支持整本下载、指定章节补充下载）
4. 自动切片混淆还原与单文件 .cbz 封装
5. 临时缓存一键清理与安全删除 (gio trash)
"""

import os
import re
import time
import zipfile
import shutil
import logging
import threading
import subprocess
import json
import jmcomic
jmcomic.JmModuleConfig.FLAG_API_CLIENT_AUTO_UPDATE_DOMAIN = False
from typing import List, Dict, Optional, Any

from omni.core import events, library, media_index, paths

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')
QUEUE_LOCK = threading.Lock()


def manga_dir() -> str:
    """默认库里的漫画目录（新下载落这里）——每次现取，切换默认库后立即生效。"""
    return library.primary("media.manga")


def novels_dir() -> str:
    """默认库里 JM 小说的目录（media_library/novels 根，跟小说画廊的 standard/nsfw 分开）。"""
    return library.primary("media.novels")


def temp_dir() -> str:
    d = os.path.join(manga_dir(), ".temp")
    os.makedirs(d, exist_ok=True)
    return d


def _media_roots(dir_flag: str) -> List[str]:
    """某一类库（"manga"/"novels"）在所有资源库里的目录：默认库排最前（新下载落地处），
    其余在线库按优先级跟在后面。"""
    key = "media.novels" if dir_flag == 'novels' else "media.manga"
    primary = library.primary(key)
    os.makedirs(primary, exist_ok=True)
    dirs = [primary]
    for d in library.dirs(key):
        if os.path.realpath(d) not in {os.path.realpath(x) for x in dirs}:
            dirs.append(d)
    return dirs


def _classify_dir_flag(path: str) -> str:
    """按"这个文件的父目录叫 manga 还是 novels"分类，不跟某一个固定绝对路径比较——
    这样不管文件实际是在主库还是 SD 卡archive 位置，分类都不会错。"""
    parent_name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return 'novels' if parent_name == 'novels' else 'manga'

import queue
import html

try:
    from opencc import OpenCC
    _T2S_CC = OpenCC('t2s')
    def to_simplified_chinese(text: str) -> str:
        """繁体转简体（opencc 可用时）。

        Args:
            text: 待转换文本，可以是空字符串/None。

        Returns:
            str: 转换后的简体文本；text 为空则返回 ""。
        """
        return _T2S_CC.convert(text) if text else ""
except Exception:
    def to_simplified_chinese(text: str) -> str:
        """opencc 不可用时的降级实现：原样返回，不做繁简转换。

        Args:
            text: 待转换文本，可以是空字符串/None。

        Returns:
            str: 原样返回的文本；text 为空则返回 ""。
        """
        return text if text else ""
# SSE 事件总线已移到 omni.core.events；这几个名字保留给本模块内部调用
broadcast_manga_event = events.broadcast
_sanitize_for_json = events._sanitize

# 活跃下载任务字典: task_id -> task_info
DOWNLOAD_TASKS: Dict[str, Dict[str, Any]] = {}
TASKS_LOCK = threading.Lock()
BATCH_WORK_QUEUES: Dict[str, queue.Queue] = {}

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
            jmcomic.JmModuleConfig.DOMAIN_API_LIST = ['www.cdngwc.club', 'www.cdngwc.net', 'www.cdngwc.cc', 'www.cdnhjk.net']
            opt = jmcomic.JmOption.default()
            try:
                opt.client.postman.meta_data['timeout'] = 10
            except Exception:
                pass
            _jm_client = opt.new_jm_client()
        return _jm_client

def sanitize_filename(name: str, max_bytes: int = 180) -> str:
    """清理文件名中的非法字符，严格按 UTF-8 字节长度截断，彻底防止 Linux ext4 [Errno 36] File name too long"""
    clean = re.sub(r'[\/\\:\*\?"<>\|\r\n\t]', '_', str(name or '')).strip()
    encoded = clean.encode('utf-8')
    if len(encoded) > max_bytes:
        clean = encoded[:max_bytes].decode('utf-8', errors='ignore').rstrip('_ .')
    return clean or 'unnamed'

def safe_chapter_dirname(photo) -> str:
    """生成安全、规范、带 4 位零填充序号的章节目录名，杜绝章节名过长与同名覆盖"""
    idx = getattr(photo, 'index', 1) or 1
    name = getattr(photo, 'name', '') or ''
    safe_name = sanitize_filename(name, max_bytes=50)
    if safe_name and safe_name != 'unnamed':
        return f"{idx:04d}_{safe_name}"
    return f"{idx:04d}"

# 全局注入 JMComic 章节文件夹命名策略与最长路径兜底
try:
    import jmcomic
    jmcomic.JmModuleConfig.PFIELD_ADVICE['name'] = safe_chapter_dirname
    jmcomic.JmModuleConfig.VAR_FILE_NAME_LENGTH_LIMIT = 50
except Exception:
    pass

def normalize_album_temp_folders(album_temp_dir: str, photos: list):
    """
    检查并迁移 .temp/{aid}/ 下历史存在的长名称或旧格式章节目录，
    将其对齐到 safe_chapter_dirname(photo) 规范名称，避免重复下载并打捞已下载切片。
    """
    if not os.path.exists(album_temp_dir):
        return
    try:
        existing_dirs = [d for d in os.listdir(album_temp_dir) if os.path.isdir(os.path.join(album_temp_dir, d))]
    except Exception:
        return
    if not existing_dirs:
        return

    # 单章节作品：直接将现有的单个目录重命名为目标规范名
    if len(photos) == 1 and len(existing_dirs) == 1:
        target_name = safe_chapter_dirname(photos[0])
        old_p = os.path.join(album_temp_dir, existing_dirs[0])
        new_p = os.path.join(album_temp_dir, target_name)
        if old_p != new_p and not os.path.exists(new_p):
            try:
                os.rename(old_p, new_p)
                logging.info(f"Normalized temp folder for album {photos[0].id}: {existing_dirs[0]} -> {target_name}")
            except Exception as e:
                logging.warning(f"Failed to rename temp folder {old_p} -> {new_p}: {e}")
        return

    # 多章节作品：按序号或章节名称精准匹配并重命名
    for photo in photos:
        target_name = safe_chapter_dirname(photo)
        target_path = os.path.join(album_temp_dir, target_name)
        if os.path.exists(target_path):
            continue
        p_name = getattr(photo, 'name', '') or ''
        p_idx = getattr(photo, 'index', 0)
        for old_dir in list(existing_dirs):
            old_path = os.path.join(album_temp_dir, old_dir)
            if not os.path.isdir(old_path):
                continue
            clean_old = sanitize_filename(old_dir, max_bytes=200)
            clean_pname = sanitize_filename(p_name, max_bytes=200)
            if (old_dir == p_name or clean_old == clean_pname or 
                old_dir.startswith(f"{p_idx:04d}_") or old_dir == str(p_idx)):
                try:
                    os.rename(old_path, target_path)
                    existing_dirs.remove(old_dir)
                    logging.info(f"Normalized multi-chapter temp folder: {old_dir} -> {target_name}")
                except Exception:
                    pass
                break


# =========================================================================
# 待下载队列磁盘持久化系统 (防掉电、防意外退出、断点续传，支持漫画/小说独立分流)
# =========================================================================

def get_queue_file(target_dir: str = 'manga') -> str:
    """按目标库类型返回对应的持久化下载队列文件路径。

    Args:
        target_dir: 'manga' 或 'novels'/'novel'（大小写不敏感）。

    Returns:
        str: 对应库目录下 .download_queue.json 的完整路径。
    """
    if str(target_dir).lower() in ('novels', 'novel'):
        return os.path.join(novels_dir(), ".download_queue.json")
    return os.path.join(manga_dir(), ".download_queue.json")

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
    """URL 编码一段文本（用于拼接文件路径类的 URL 时转义特殊字符）。

    Args:
        text: 待编码的原始文本。

    Returns:
        str: URL 编码后的文本。
    """
    from urllib.parse import quote
    return quote(text)

def resolve_file_path(filename: str, target_dir: str = "") -> Optional[str]:
    """根据目标目录解析 .cbz 物理文件绝对路径——依次在这一类库的每个候选根目录下找。"""
    if str(target_dir).lower() in ('novels', 'novel'):
        flags = ['novels']
    elif str(target_dir).lower() in ('manga', '0'):
        flags = ['manga']
    else:
        flags = ['manga', 'novels']
    for flag in flags:
        for root in _media_roots(flag):
            p = os.path.join(root, filename)
            if os.path.exists(p):
                return p
    return None

def get_cover_path(target_path: str) -> Optional[str]:
    """获取指定游戏目录下的封面路径 (优先 cover.jpg/png，次选 Steam 规范封面)"""
    for name in ("cover.jpg", "cover.png", "cover.webp", "folder.jpg", "poster.jpg"):
        p = os.path.join(target_path, name)
        if os.path.exists(p):
            return p
    # Steam 规范兼容
    p2 = os.path.join(target_path, "header.jpg")
    if os.path.exists(p2):
        return p2
    return None

_ALBUM_ID_TO_FILE: Dict[str, str] = {}


def _seed_media_index(cbz_path: str, meta: Dict[str, Any]) -> None:
    """把刚下载好 / 修复好的 CBZ 直接写进索引，省得下次扫描再开一遍。"""
    try:
        st = os.stat(cbz_path)
        dir_flag = _classify_dir_flag(cbz_path)
        media_index.put_many([(cbz_path, f'mangalib:{dir_flag}', st.st_mtime, st.st_size, meta)])
    except Exception:
        pass


def _rich_parse_manga(full_path: str) -> Dict[str, Any]:
    """开一次 .cbz 读页数 + metadata.json —— 只在文件新增/变动时被 media_index 调用。"""
    meta = {
        'id': '', 'author': '', 'tags': [], 'is_complete': True,
        'online_chapters': 0, 'local_chapters': 0, 'page_count': 0, 'has_cover': False,
    }
    if not full_path.lower().endswith('.cbz'):
        return meta
    try:
        with zipfile.ZipFile(full_path, 'r') as zf:
            namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
            img_files = [n for n in namelist if n.lower().endswith(IMAGE_EXTENSIONS)]
            meta['page_count'] = len(img_files)
            meta['has_cover'] = len(img_files) > 0
            if 'metadata.json' in namelist:
                try:
                    m = json.loads(zf.read('metadata.json').decode('utf-8'))
                    meta['id'] = str(m.get('id', '') or '').strip()
                    meta['author'] = m.get('author', '')
                    meta['tags'] = m.get('tags', [])
                    meta['is_complete'] = m.get('is_complete', True)
                    meta['online_chapters'] = m.get('online_chapters', 0)
                    meta['local_chapters'] = m.get('local_chapters', 0)
                except Exception:
                    pass
    except Exception:
        pass
    return meta


def get_local_library(q: str = "", target_dir: str = "manga") -> List[Dict[str, Any]]:
    """本地漫画/小说库列表 —— 走 media_index 持久化索引：只有新增/变动的文件才会真的
    去开压缩包，其余直接吃 SQLite 缓存。冷启动第一次照旧慢，之后每次都是秒出。
    一类库可能分布在好几个候选根目录下（主库 + SD 卡等归档位置，见 _media_roots），
    每个都扫一遍、结果合并；同一个 kind 下不同根目录的文件走同一份索引，互不冲突。"""
    dir_flag = 'novels' if str(target_dir).lower() in ('novels', 'novel') else 'manga'
    kind = f'mangalib:{dir_flag}'
    q = (q or "").lower().strip()
    norm_q = to_simplified_chinese(q)

    # 1. 快速拿到每个文件的 (path, mtime, size) —— 不开任何压缩包，每个候选根目录都看一遍
    files = []
    fs_info = {}
    for base_dir in _media_roots(dir_flag):
        try:
            with os.scandir(base_dir) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith('.') or not name.lower().endswith(('.cbz', '.txt', '.epub')):
                        continue
                    try:
                        st = entry.stat()
                        if not entry.is_file():
                            continue
                    except OSError:
                        continue
                    files.append((entry.path, st.st_mtime, st.st_size))
                    fs_info[entry.path] = (name, st.st_size, st.st_mtime)
        except FileNotFoundError:
            continue

    if not files:
        return []

    def _on_progress(done, total):
        """把索引补齐进度通过 SSE 广播给前端，驱动进度条更新。"""
        try:
            broadcast_manga_event({'type': 'library_indexed', 'dir': dir_flag, 'done': done, 'total': total})
        except Exception:
            pass

    metas = media_index.diff_scan(kind, files, _rich_parse_manga, sync_limit=40, on_progress=_on_progress)

    # 2. 组装列表（元数据来自索引，文件名/大小/时间来自刚才的 scandir）
    items = []
    for path, (fname, size_bytes, mtime) in fs_info.items():
        m = metas.get(path) or {}
        base_name = os.path.splitext(fname)[0]
        ext = os.path.splitext(fname)[1].lower().lstrip('.')
        album_id = m.get('id', '')
        author = m.get('author', '')
        tags = m.get('tags', []) or []
        if album_id:
            _ALBUM_ID_TO_FILE[album_id] = path

        if norm_q:
            norm_name = to_simplified_chinese(base_name).lower()
            norm_author = to_simplified_chinese(author).lower()
            norm_tags = [to_simplified_chinese(t).lower() for t in tags]
            matched = (norm_q in norm_name) or (norm_q in norm_author) or (album_id and q in str(album_id)) or any(norm_q in t for t in norm_tags) or (q in base_name.lower())
            if not matched:
                continue

        items.append({
            'id': album_id,
            'filename': fname,
            'title': base_name,
            'author': author,
            'tags': tags,
            'is_complete': m.get('is_complete', True),
            'online_chapters': m.get('online_chapters', 0),
            'local_chapters': m.get('local_chapters', 0),
            'ext': ext,
            'dir': dir_flag,
            'size_mb': round(size_bytes / (1024 * 1024), 2),
            'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime)),
            'page_count': m.get('page_count', 0),
            'has_cover': m.get('has_cover', False),
            'cover_url': f'/api/manga/cover?name={urllib_quote(fname)}&dir={dir_flag}',
        })

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
            img_files = sorted([n for n in namelist if n.lower().endswith(IMAGE_EXTENSIONS)])
            if not img_files:
                return None
            cover_entry = next((f for f in img_files if 'cover' in os.path.basename(f).lower()), img_files[0])
            return zf.read(cover_entry)
    except Exception:
        return None


def get_cbz_cover_thumb(filename: str, target_dir: str = "") -> Optional[str]:
    """封面网格缩略图（<=360px WebP，磁盘缓存）的文件路径。源 CBZ 没变就不再开压缩包。"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return None
    return media_index.get_or_make_thumb(
        cbz_path,
        lambda: get_cbz_cover_bytes(filename, target_dir),
        max_w=360, tag="cover",
    )

def get_cbz_pages_list(filename: str, target_dir: str = "") -> List[str]:
    """获取 .cbz 内部所有排好序的图片文件名列表"""
    cbz_path = resolve_file_path(filename, target_dir)
    if not cbz_path or not os.path.exists(cbz_path):
        return []

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
            img_files = sorted([n for n in namelist if n.lower().endswith(IMAGE_EXTENSIONS)])
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


def get_online_cover_bytes(album_id: str) -> Optional[bytes]:
    """通过官方移动端 API 安全通道获取并本地缓存禁漫线上作品的封面图"""
    aid = str(album_id).strip()
    if not aid or not aid.isdigit():
        return None

    os.makedirs(paths.MANGA_COVERS, exist_ok=True)
    cached = os.path.join(paths.MANGA_COVERS, f'{aid}.jpg')
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
    jmcomic.JmModuleConfig.FLAG_API_CLIENT_AUTO_UPDATE_DOMAIN = False
    jmcomic.JmModuleConfig.DOMAIN_API_LIST = ['www.cdngwc.club', 'www.cdnhjk.net', 'www.cdngwc.net', 'www.cdngwc.cc']
    jmcomic.JmModuleConfig.PFIELD_ADVICE['name'] = safe_chapter_dirname
    jmcomic.JmModuleConfig.VAR_FILE_NAME_LENGTH_LIMIT = 50
    opt = jmcomic.JmOption.default()
    opt.dir_rule.base_dir = base_dir
    opt.dir_rule.rule = 'Bd_Pname'
    opt.download_image_decode = True
    return opt

def pack_folder_to_cbz(source_folder: str, target_cbz_path: str, cover_file: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    """将下载好的漫画文件夹整整齐齐地封装为单个 .cbz 容器，自动注入 ComicInfo.xml 与 metadata.json 元数据"""
    os.makedirs(os.path.dirname(target_cbz_path), exist_ok=True)
    temp_zip = target_cbz_path + ".tmp"

    with zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if cover_file and os.path.exists(cover_file):
            zf.write(cover_file, arcname="cover.jpg")

        # 写入 ComicInfo.xml 与 metadata.json
        if metadata:
            meta_json = json.dumps(metadata, ensure_ascii=False, indent=2)
            zf.writestr("metadata.json", meta_json)

            title_xml = html.escape(str(metadata.get('title', '')))
            writer_xml = html.escape(str(metadata.get('author', '')))
            summary_xml = html.escape(str(metadata.get('description', '')))
            tags_list = metadata.get('tags', [])
            tags_xml = html.escape(','.join(tags_list) if isinstance(tags_list, list) else str(tags_list))
            album_id = metadata.get('id', '')

            comic_info_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Title>{title_xml}</Title>
  <Writer>{writer_xml}</Writer>
  <Summary>{summary_xml}</Summary>
  <Genre>{tags_xml}</Genre>
  <Tags>{tags_xml}</Tags>
  <Web>https://18comic.vip/album/{album_id}</Web>
</ComicInfo>"""
            zf.writestr("ComicInfo.xml", comic_info_xml)

        for root, dirs, files in os.walk(source_folder):
            dirs.sort()
            for f in sorted(files):
                if f.lower().endswith(IMAGE_EXTENSIONS):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, source_folder)
                    zf.write(full_p, arcname=rel_p)

    try:
        if os.path.exists(target_cbz_path):
            os.remove(target_cbz_path)
        os.rename(temp_zip, target_cbz_path)
    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass

def append_folder_to_cbz(source_folder: str, target_cbz_path: str, metadata: Optional[Dict[str, Any]] = None):
    """
    极速将新下载的章节文件夹增量追加注入到已存在的 .cbz 压缩包中，
    自动更新 metadata.json 与 ComicInfo.xml，杜绝全量重新打包的巨大 I/O 开销。
    """
    if not os.path.exists(target_cbz_path):
        return pack_folder_to_cbz(source_folder, target_cbz_path, metadata=metadata)

    use_cli_zip = False
    try:
        sub_check = subprocess.run(['zip', '-v'], capture_output=True)
        if sub_check.returncode == 0:
            use_cli_zip = True
    except Exception:
        use_cli_zip = False

    if metadata:
        meta_json = json.dumps(metadata, ensure_ascii=False, indent=2)
        with open(os.path.join(source_folder, "metadata.json"), 'w', encoding='utf-8') as f:
            f.write(meta_json)

        title_xml = html.escape(str(metadata.get('title', '')))
        writer_xml = html.escape(str(metadata.get('author', '')))
        summary_xml = html.escape(str(metadata.get('description', '')))
        tags_list = metadata.get('tags', [])
        tags_xml = html.escape(','.join(tags_list) if isinstance(tags_list, list) else str(tags_list))
        album_id = metadata.get('id', '')

        comic_info_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Title>{title_xml}</Title>
  <Writer>{writer_xml}</Writer>
  <Summary>{summary_xml}</Summary>
  <Genre>{tags_xml}</Genre>
  <Tags>{tags_xml}</Tags>
  <Web>https://18comic.vip/album/{album_id}</Web>
</ComicInfo>"""
        with open(os.path.join(source_folder, "ComicInfo.xml"), 'w', encoding='utf-8') as f:
            f.write(comic_info_xml)

    if use_cli_zip:
        try:
            # 剔除旧元数据以保证唯一性
            subprocess.run(['zip', '-d', target_cbz_path, 'metadata.json', 'ComicInfo.xml'], check=False, capture_output=True)
            # 增量注入新章节与新元数据
            res = subprocess.run(['zip', '-u', '-r', target_cbz_path, '.'], cwd=source_folder, capture_output=True)
            if res.returncode == 0:
                return True
        except Exception as e:
            logging.warning(f"cli zip failed, falling back to python zipfile: {e}")

    # Fallback: Python zipfile 重打包
    temp_zip = target_cbz_path + ".tmp"
    with zipfile.ZipFile(target_cbz_path, 'r') as src_zf, zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as dst_zf:
        for zinfo in src_zf.infolist():
            if zinfo.filename not in ('metadata.json', 'ComicInfo.xml'):
                dst_zf.writestr(zinfo.filename, src_zf.read(zinfo.filename))
        
        for root, dirs, files in os.walk(source_folder):
            dirs.sort()
            for f in sorted(files):
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, source_folder)
                dst_zf.write(full_p, arcname=rel_p)

    if os.path.exists(target_cbz_path):
        os.remove(target_cbz_path)
    os.rename(temp_zip, target_cbz_path)
    return True

def update_cbz_metadata(cbz_path: str, meta_dict: Dict[str, Any]) -> bool:
    """更新已存在 CBZ 内部的 metadata.json 与 ComicInfo.xml，并同步更新 media_index 索引与前台事件"""
    if not os.path.exists(cbz_path):
        return False
    try:
        meta_json = json.dumps(meta_dict, ensure_ascii=False, indent=2)
        title_xml = html.escape(str(meta_dict.get('title', '')))
        writer_xml = html.escape(str(meta_dict.get('author', '')))
        summary_xml = html.escape(str(meta_dict.get('description', '')))
        tags_list = meta_dict.get('tags', [])
        tags_xml = html.escape(','.join(tags_list) if isinstance(tags_list, list) else str(tags_list))
        album_id = meta_dict.get('id', '')

        comic_info_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Title>{title_xml}</Title>
  <Writer>{writer_xml}</Writer>
  <Summary>{summary_xml}</Summary>
  <Genre>{tags_xml}</Genre>
  <Tags>{tags_xml}</Tags>
  <Web>https://18comic.vip/album/{album_id}</Web>
</ComicInfo>"""

        use_cli_zip = False
        try:
            sub_check = subprocess.run(['zip', '-v'], capture_output=True)
            if sub_check.returncode == 0:
                use_cli_zip = True
        except Exception:
            use_cli_zip = False

        if use_cli_zip:
            tmp_dir = os.path.join(temp_dir(), f"_meta_{int(time.time()*1000)}")
            os.makedirs(tmp_dir, exist_ok=True)
            try:
                with open(os.path.join(tmp_dir, "metadata.json"), 'w', encoding='utf-8') as f:
                    f.write(meta_json)
                with open(os.path.join(tmp_dir, "ComicInfo.xml"), 'w', encoding='utf-8') as f:
                    f.write(comic_info_xml)
                subprocess.run(['zip', '-d', cbz_path, 'metadata.json', 'ComicInfo.xml'], check=False, capture_output=True)
                subprocess.run(['zip', '-u', '-j', cbz_path, os.path.join(tmp_dir, "metadata.json"), os.path.join(tmp_dir, "ComicInfo.xml")], check=False, capture_output=True)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            temp_zip = cbz_path + ".tmp"
            with zipfile.ZipFile(cbz_path, 'r') as src_zf, zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as dst_zf:
                for zinfo in src_zf.infolist():
                    if zinfo.filename not in ('metadata.json', 'ComicInfo.xml'):
                        dst_zf.writestr(zinfo.filename, src_zf.read(zinfo.filename))
                dst_zf.writestr("metadata.json", meta_json)
                dst_zf.writestr("ComicInfo.xml", comic_info_xml)
            if os.path.exists(cbz_path):
                os.remove(cbz_path)
            os.rename(temp_zip, cbz_path)

        with zipfile.ZipFile(cbz_path, 'r') as zf:
            page_c = sum(1 for n in zf.namelist() if n.lower().endswith(IMAGE_EXTENSIONS))

        _seed_media_index(cbz_path, {
            'id': str(album_id),
            'page_count': page_c,
            'has_cover': page_c > 0,
            'author': meta_dict.get('author', ''),
            'tags': meta_dict.get('tags', []),
            'is_complete': meta_dict.get('is_complete', True),
            'online_chapters': meta_dict.get('online_chapters', 0),
            'local_chapters': meta_dict.get('local_chapters', 0),
        })
        dir_flag = _classify_dir_flag(cbz_path)
        media_index._invalidate(f'mangalib:{dir_flag}')

        broadcast_manga_event({
            'type': 'metadata_updated',
            'filename': os.path.basename(cbz_path),
            'title': meta_dict.get('title', ''),
            'tags': meta_dict.get('tags', []),
            'is_complete': meta_dict.get('is_complete', True),
            'online_chapters': meta_dict.get('online_chapters', 0),
            'local_chapters': meta_dict.get('local_chapters', 0),
        })
        return True
    except Exception as e:
        logging.warning(f"Failed to update CBZ metadata for {cbz_path}: {e}")
        return False

def find_existing_cbz_by_aid(aid: str, target_dir_path: Optional[str] = None) -> Optional[str]:
    """根据 JM 专辑 ID 快速查找本地已存在的 .cbz 文件路径——在这一类库的每个候选根
    目录下都找一遍（主库 + SD 卡等归档位置），不然已经搬去 SD 卡的本子会被当成"没
    下过"重新下一遍。target_dir_path 只用来判断这是 manga 还是 novels 这一类库，不
    再限定死只在这一个目录里找。"""
    aid_str = str(aid).strip()
    if not aid_str:
        return None
    dir_flag = _classify_dir_flag(os.path.join(target_dir_path or manga_dir(), "x"))
    roots = _media_roots(dir_flag)

    fast_path = _ALBUM_ID_TO_FILE.get(aid_str)
    if fast_path and os.path.isfile(fast_path) and os.path.dirname(fast_path) in roots:
        return fast_path

    for fpath, row in media_index.load_kind(f'mangalib:{dir_flag}').items():
        if os.path.dirname(fpath) in roots and str(row.get('meta', {}).get('id', '')) == aid_str:
            if os.path.isfile(fpath):
                _ALBUM_ID_TO_FILE[aid_str] = fpath
                return fpath

    for root_dir in roots:
        if not os.path.isdir(root_dir):
            continue
        for fname in os.listdir(root_dir):
            if fname.lower().endswith('.cbz') and not fname.startswith('.'):
                full_p = os.path.join(root_dir, fname)
                try:
                    with zipfile.ZipFile(full_p, 'r') as zf:
                        if 'metadata.json' in zf.namelist():
                            m = json.loads(zf.read('metadata.json').decode('utf-8'))
                            m_id = str(m.get('id', '')).strip()
                            if m_id:
                                _ALBUM_ID_TO_FILE[m_id] = full_p
                            if m_id == aid_str:
                                return full_p
                except Exception:
                    continue
    return None

def _download_thread(task_id: str, album_id: str, chapter_ids: Optional[List[str]], pack_cbz: bool, clean_temp: bool, dest_dir: str = 'manga'):
    """后台下载执行线程 (全面支持增量追更与整本下载)"""
    task = DOWNLOAD_TASKS.get(task_id)
    if not task:
        return

    album_temp_dir = os.path.join(temp_dir(), album_id)
    os.makedirs(album_temp_dir, exist_ok=True)
    opt = create_jm_option_for_dir(album_temp_dir)
    target_dir_path = novels_dir() if str(dest_dir).lower() in ('novels', 'novel') else manga_dir()

    try:
        task['status'] = 'fetching_meta'
        task['message'] = '正在获取章节元数据...'
        client = get_jm_client()
        detail = client.get_album_detail(album_id)

        title = detail.title
        safe_title = sanitize_filename(title)
        task['title'] = title
        target_cbz_name = f"{safe_title}.cbz"
        target_cbz_path = os.path.join(target_dir_path, target_cbz_name)

        existing_cbz_path = find_existing_cbz_by_aid(album_id, target_dir_path)
        if not existing_cbz_path and os.path.exists(target_cbz_path) and os.path.getsize(target_cbz_path) > 10240:
            existing_cbz_path = target_cbz_path

        all_photos = list(detail)
        total_online = len(all_photos)

        existing_chapter_count = 0
        is_incremental = False
        if pack_cbz and existing_cbz_path and os.path.exists(existing_cbz_path) and os.path.getsize(existing_cbz_path) > 10240:
            try:
                with zipfile.ZipFile(existing_cbz_path, 'r') as zf:
                    nl = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
                    inner_dirs = sorted(list({n.split('/')[0] for n in nl if '/' in n}))
                    existing_chapter_count = len(inner_dirs) if inner_dirs else (1 if any(n.lower().endswith(IMAGE_EXTENSIONS) for n in nl) else 0)
            except Exception:
                existing_chapter_count = 0

            if existing_chapter_count >= total_online and (not chapter_ids):
                try:
                    needs_fix = False
                    with zipfile.ZipFile(existing_cbz_path, 'r') as zf:
                        if 'metadata.json' in zf.namelist():
                            _pm = json.loads(zf.read('metadata.json').decode('utf-8'))
                            if not _pm.get('is_complete') or _pm.get('local_chapters', 0) < existing_chapter_count:
                                needs_fix = True
                        else:
                            needs_fix = True
                    if needs_fix:
                        fixed_meta = {
                            'id': str(album_id),
                            'title': title,
                            'author': getattr(detail, 'author', '') or '',
                            'description': getattr(detail, 'description', '') or '',
                            'tags': getattr(detail, 'tags', []) or [],
                            'online_chapters': total_online,
                            'local_chapters': existing_chapter_count,
                            'is_complete': True,
                            'verified': True,
                            'updated_at': time.time(),
                        }
                        update_cbz_metadata(existing_cbz_path, fixed_meta)
                except Exception as me:
                    logging.warning(f"Error fixing metadata in single worker: {me}")

                if clean_temp and os.path.exists(album_temp_dir):
                    shutil.rmtree(album_temp_dir, ignore_errors=True)

                task['status'] = 'completed'
                task['percent'] = 100.0
                task['message'] = f"单文件《{os.path.basename(existing_cbz_path)}》已是最新全本 ({existing_chapter_count}/{total_online}话)，无需重复下载！"
                remove_from_persistent_queue(album_id, target_dir=dest_dir)
                return

            if existing_chapter_count < total_online and (not chapter_ids):
                is_incremental = True

        if chapter_ids and len(chapter_ids) > 0:
            target_photos = [p for p in all_photos if str(getattr(p, 'photo_id', getattr(p, 'id', ''))) in chapter_ids]
            if not target_photos:
                target_photos = all_photos
        elif is_incremental:
            target_photos = all_photos[existing_chapter_count:]
            task['message'] = f"发现新章节更新！本地已有 {existing_chapter_count} 话，开始增量下载最新 {len(target_photos)} 话..."
        else:
            target_photos = all_photos

        total_chapters = len(target_photos)
        task['total_chapters'] = total_chapters
        task['downloaded_chapters'] = 0

        # 自动对齐并规范化该作品在 temp 下的历史章节目录
        normalize_album_temp_folders(album_temp_dir, target_photos)

        failed_photos = []
        for idx, photo in enumerate(target_photos, 1):
            pid = getattr(photo, 'photo_id', getattr(photo, 'id', ''))
            display_num = existing_chapter_count + idx if is_incremental else idx
            task['status'] = 'downloading'
            task['current_chapter'] = f"第 {display_num}/{total_online} 话"
            task['percent'] = round((idx - 1) / total_chapters * 85, 1)
            task['message'] = f"正在下载解密: {task['current_chapter']} (ID: {pid})..."

            success = _download_photo_with_retry(album_id, pid, opt)

            if success:
                task['downloaded_chapters'] = idx
            else:
                failed_photos.append(pid)

        if pack_cbz:
            valid_imgs = sum(
                len(fl) for _, _, fl in os.walk(album_temp_dir)
                if any(f.lower().endswith(IMAGE_EXTENSIONS) for f in fl)
            )
            if valid_imgs == 0:
                raise RuntimeError("下载自检失败：未在解密目录找到有效图片，放弃打包以防止损坏文件入库")

            task['status'] = 'packing'
            task['percent'] = 90.0

            final_local_chapters = existing_chapter_count + (len(target_photos) - len(failed_photos)) if is_incremental else (len(target_photos) - len(failed_photos))
            is_complete = (final_local_chapters >= total_online)

            meta_dict = {
                'id': str(album_id),
                'title': title,
                'author': getattr(detail, 'author', '') or '',
                'description': getattr(detail, 'description', '') or '',
                'tags': getattr(detail, 'tags', []) or [],
                'online_chapters': total_online,
                'local_chapters': final_local_chapters,
                'is_complete': is_complete,
                'verified': True,
                'updated_at': time.time(),
            }

            final_cbz_path = existing_cbz_path if (is_incremental and existing_cbz_path) else target_cbz_path
            if is_incremental and existing_cbz_path:
                task['message'] = '正在将新章节增量追加注入到现有 CBZ 封箱包...'
                append_folder_to_cbz(album_temp_dir, final_cbz_path, metadata=meta_dict)
            else:
                task['message'] = '正在合并全章节图片并封装为单文件 .cbz 容器(附带 ComicInfo 标签元数据)...'
                pack_folder_to_cbz(album_temp_dir, final_cbz_path, metadata=meta_dict)

            try:
                with zipfile.ZipFile(final_cbz_path, 'r') as zf:
                    page_c = sum(1 for n in zf.namelist() if n.lower().endswith(IMAGE_EXTENSIONS))
                _seed_media_index(final_cbz_path, {
                    'id': str(album_id),
                    'page_count': page_c,
                    'has_cover': page_c > 0,
                    'author': meta_dict['author'],
                    'tags': meta_dict['tags'],
                    'is_complete': is_complete,
                    'online_chapters': total_online,
                    'local_chapters': final_local_chapters,
                })
                _ALBUM_ID_TO_FILE[str(album_id)] = final_cbz_path
            except Exception:
                pass

            broadcast_manga_event({
                'type': 'metadata_updated',
                'filename': os.path.basename(final_cbz_path),
                'title': meta_dict['title'],
                'tags': meta_dict['tags'],
                'is_complete': is_complete,
                'online_chapters': total_online,
                'local_chapters': final_local_chapters,
            })

            if clean_temp and not failed_photos:
                task['status'] = 'cleaning'
                task['percent'] = 98.0
                task['message'] = '正在清理下载临时切片碎片...'
                shutil.rmtree(album_temp_dir, ignore_errors=True)

            remove_from_persistent_queue(album_id, target_dir=dest_dir)

        task['status'] = 'completed'
        task['percent'] = 100.0
        final_cbz_name = os.path.basename(final_cbz_path) if 'final_cbz_path' in locals() else target_cbz_name
        task['message'] = f"下载与封装完成！《{final_cbz_name}》已就绪 (已收录 {final_local_chapters}/{total_online} 话)"

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

MAX_BATCH_CONCURRENCY = 3
_PHOTO_DOWNLOAD_MAX_RETRIES = 3
_PHOTO_DOWNLOAD_RETRY_DELAY_S = 1.0


def _download_photo_with_retry(aid: str, pid, opt) -> bool:
    """下载单个章节 (photo)，失败自动重试，重试间隔固定等待一小段时间。

    从 _batch_download_worker() 里的逐章节下载循环拆出来，避免那边的
    "for photo: for retry" 两层循环叠在 while True 主循环上变成三层嵌套。

    Args:
        aid: 所属漫画的 JM 编号（仅用于日志标识）。
        pid: 章节 (photo) 的 ID。
        opt: jmcomic 下载选项对象（已配置好目标目录等）。

    Returns:
        bool: 下载成功返回 True；重试用尽仍失败返回 False。
    """
    for attempt in range(_PHOTO_DOWNLOAD_MAX_RETRIES):
        try:
            jmcomic.download_photo(pid, option=opt)
            return True
        except Exception as pe:
            logging.warning(
                f"Album {aid} chapter {pid} attempt {attempt + 1}/{_PHOTO_DOWNLOAD_MAX_RETRIES} failed: {pe}"
            )
            time.sleep(_PHOTO_DOWNLOAD_RETRY_DELAY_S)
    return False


def _batch_download_worker(task_id: str, album_ids: List[str], pack_cbz: bool, clean_temp: bool, dest_dir: str = 'manga'):
    """后台多线程并发连轴转下载工作线程 (支持 MAX_BATCH_CONCURRENCY 路并行并发)"""
    task = DOWNLOAD_TASKS.get(task_id)
    if not task:
        return

    target_dir_path = novels_dir() if str(dest_dir).lower() in ('novels', 'novel') else manga_dir()

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

    work_queue: queue.Queue = queue.Queue()
    for aid in task['clean_ids']:
        work_queue.put(aid)
    BATCH_WORK_QUEUES[task_id] = work_queue

    active_jobs: Dict[str, str] = {}
    state_lock = threading.RLock()
    completed_count = [0]
    failed_albums = []
    task_concurrency = int(task.get('concurrency', MAX_BATCH_CONCURRENCY))
    is_sequential = (task_concurrency == 1)

    def update_task_progress():
        """按当前完成数/总数刷新 task 的百分比、标题、消息文案，并通过 SSE 广播出去。"""
        with state_lock:
            done = completed_count[0]
            total = max(task['total_albums'], 1)
            pct = round((done / total) * 100, 1)
            task['percent'] = min(pct, 99.9) if done < total else 100.0
            task['completed_albums'] = done
            if is_sequential:
                task['title'] = f"📥 逐本顺序下载队列 ({done}/{total} 部)"
                if active_jobs:
                    current_active = list(active_jobs.values())[0]
                    task['message'] = f"[{done}/{total}] 正在抓取: {current_active}"
                else:
                    task['message'] = f"已完成 {done}/{total} 部作品"
            else:
                task['title'] = f"⚡ 并发批量下载队列 ({done}/{total} 部)"
                if active_jobs:
                    current_actives = list(active_jobs.values())[:3]
                    task['message'] = f"[{done}/{total}] 并行抓取中: " + " · ".join(current_actives)
                else:
                    task['message'] = f"已完成 {done}/{total} 部作品"
        broadcast_manga_event({'type': 'progress', 'task': task})

    def worker_loop(worker_num: int):
        """批量下载工作线程主循环：不断从 work_queue 领任务下载，直到队列清空或任务被停止。

        Args:
            worker_num: 工作线程编号，仅用于日志/状态展示区分是哪个并发槽位。
        """
        client = get_jm_client()
        while True:
            # 优雅停止检查：若已触发停止，不再领取新漫画，手头任务完工后平稳退出
            if task.get('stopping'):
                break

            try:
                aid = work_queue.get_nowait()
            except queue.Empty:
                break

            album_temp_dir = os.path.join(temp_dir(), aid)
            os.makedirs(album_temp_dir, exist_ok=True)
            opt = create_jm_option_for_dir(album_temp_dir)

            with state_lock:
                active_jobs[aid] = f"JM{aid} 准备中"
            update_task_progress()

            try:
                # 1. 尝试获取详情与标题 (带容错重试)
                detail = None
                last_de = None
                # 大批量下载到尾部经常被 JM 限流（403/429），1.5s×3 撑不过限流窗口 ——
                # 改成指数退避 5 次：3s / 9s / 21s / 39s / 63s
                for d_try in range(5):
                    try:
                        detail = client.get_album_detail(aid)
                        break
                    except Exception as de:
                        last_de = de
                        wait = min(75, 3 * (d_try + 1) ** 2)
                        logging.warning(f"Album {aid} detail attempt {d_try+1}/5 failed: {de} (retry in {wait}s)")
                        with state_lock:
                            active_jobs[aid] = f"JM{aid} 被限流，{wait}s 后重试({d_try+1}/5)"
                        update_task_progress()
                        time.sleep(wait)

                if not detail:
                    raise RuntimeError(f"获取 JM{aid} 详情连续 5 次失败（{last_de}）—— 多半是被限流或该本已下架")

                photos = list(detail)
                total_photos = len(photos)
                failed_photos = []

                # 自动对齐并规范化该作品在 temp 下的历史章节目录
                normalize_album_temp_folders(album_temp_dir, photos)

                safe_title = sanitize_filename(detail.title, max_bytes=180)
                target_cbz_name = f"{safe_title}.cbz"
                target_cbz_path = os.path.join(target_dir_path, target_cbz_name)

                # 检查本地是否已有该本的 CBZ 文件 (增量检测)
                existing_cbz_path = find_existing_cbz_by_aid(aid, target_dir_path)
                if not existing_cbz_path and os.path.exists(target_cbz_path) and os.path.getsize(target_cbz_path) > 10240:
                    existing_cbz_path = target_cbz_path

                existing_chapter_count = 0
                is_incremental = False
                prev_stall = 0
                if pack_cbz and existing_cbz_path and os.path.exists(existing_cbz_path) and os.path.getsize(existing_cbz_path) > 10240:
                    try:
                        with zipfile.ZipFile(existing_cbz_path, 'r') as zf:
                            nl = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
                            inner_dirs = sorted(list({n.split('/')[0] for n in nl if '/' in n}))
                            existing_chapter_count = len(inner_dirs) if inner_dirs else (1 if any(n.lower().endswith(IMAGE_EXTENSIONS) for n in nl) else 0)
                            if 'metadata.json' in nl:
                                try:
                                    _pm = json.loads(zf.read('metadata.json').decode('utf-8'))
                                    prev_stall = int(_pm.get('stall_count', 0))
                                    # 之前跑过、已确认 local<online 又补不上的（verified 且未完结）：
                                    # 视作已经卡过一次，这次再 0 收获就直接认账
                                    if prev_stall == 0 and _pm.get('verified') and _pm.get('is_complete') is False:
                                        prev_stall = 1
                                except Exception:
                                    prev_stall = 0
                    except Exception:
                        existing_chapter_count = 0

                    if existing_chapter_count >= total_photos:
                        try:
                            needs_fix = False
                            with zipfile.ZipFile(existing_cbz_path, 'r') as zf:
                                if 'metadata.json' in zf.namelist():
                                    _pm = json.loads(zf.read('metadata.json').decode('utf-8'))
                                    if not _pm.get('is_complete') or _pm.get('local_chapters', 0) < existing_chapter_count:
                                        needs_fix = True
                                else:
                                    needs_fix = True
                            if needs_fix:
                                fixed_meta = {
                                    'id': str(aid),
                                    'title': detail.title,
                                    'author': getattr(detail, 'author', '') or '',
                                    'description': getattr(detail, 'description', '') or '',
                                    'tags': getattr(detail, 'tags', []) or [],
                                    'online_chapters': total_photos,
                                    'local_chapters': existing_chapter_count,
                                    'is_complete': True,
                                    'verified': True,
                                    'updated_at': time.time()
                                }
                                update_cbz_metadata(existing_cbz_path, fixed_meta)
                        except Exception as me:
                            logging.warning(f"Error fixing metadata in batch worker for {aid}: {me}")

                        if clean_temp and os.path.exists(album_temp_dir):
                            shutil.rmtree(album_temp_dir, ignore_errors=True)

                        remove_from_persistent_queue(aid, target_dir=dest_dir)
                        with state_lock:
                            completed_count[0] += 1
                            active_jobs.pop(aid, None)
                        update_task_progress()
                        # 注意：不要在这里调 work_queue.task_done() —— 下面的 finally
                        # 已经会为**包括 continue 在内的每条出口**各调一次。
                        continue

                    is_incremental = True

                target_photos = photos[existing_chapter_count:] if is_incremental else photos

                # 2. 逐章节解密下载 (自带本地缓存检测跳过已下载图 + 3次容错重试)
                for p_idx, photo in enumerate(target_photos, 1):
                    pid = getattr(photo, 'photo_id', getattr(photo, 'id', ''))
                    disp_idx = existing_chapter_count + p_idx if is_incremental else p_idx
                    with state_lock:
                        status_label = "补更新" if is_incremental else ""
                        active_jobs[aid] = f"《{safe_title[:10]}》{status_label}({disp_idx}/{total_photos}话)"
                    update_task_progress()

                    success = _download_photo_with_retry(aid, pid, opt)

                    if not success:
                        failed_photos.append(pid)

                # 3. 封箱打包为 CBZ (只要有切片下载成功就打包装盒，保全进度)
                if pack_cbz:
                    valid_imgs = sum(
                        len(fl) for _, _, fl in os.walk(album_temp_dir)
                        if any(f.lower().endswith(IMAGE_EXTENSIONS) for f in fl)
                    )
                    if valid_imgs == 0:
                        raise RuntimeError("下载自检失败：未在解密目录找到有效图片，放弃打包以防止损坏文件入库")

                    with state_lock:
                        active_jobs[aid] = f"《{safe_title[:10]}》{'增量封箱' if is_incremental else '封箱打包'}"
                    update_task_progress()

                    got_new = len(target_photos) - len(failed_photos)
                    final_local_chapters = existing_chapter_count + got_new if is_incremental else got_new
                    is_complete = (final_local_chapters >= total_photos)

                    # 卡住检测：增量补更新一章都没补到（要补的章 JM 上已经拉不下来 —— 下架/
                    # 加锁/章节 ID 失效）。连续 2 次都是 0 收获，就认账收工，标 partial，
                    # 从待下载列表移除，别再无限重试骚扰"未完结"标签。
                    stall_count = 0
                    accept_partial = False
                    if is_incremental and got_new == 0 and existing_chapter_count > 0:
                        stall_count = prev_stall + 1
                        if stall_count >= 2:
                            accept_partial = True
                            is_complete = True

                    meta_dict = {
                        'id': str(aid),
                        'title': detail.title,
                        'author': getattr(detail, 'author', '') or '',
                        'description': getattr(detail, 'description', '') or '',
                        'tags': getattr(detail, 'tags', []) or [],
                        'online_chapters': total_photos,
                        'local_chapters': final_local_chapters,
                        'is_complete': is_complete,
                        'stall_count': 0 if (got_new > 0 or accept_partial) else stall_count,
                        'partial': accept_partial or None,
                        'missing_chapters': (total_photos - final_local_chapters) if accept_partial else None,
                        'verified': True,
                        'updated_at': time.time()
                    }
                    meta_dict = {k: v for k, v in meta_dict.items() if v is not None}

                    final_cbz_path = existing_cbz_path if (is_incremental and existing_cbz_path) else target_cbz_path
                    if is_incremental and existing_cbz_path:
                        append_folder_to_cbz(album_temp_dir, final_cbz_path, metadata=meta_dict)
                    else:
                        pack_folder_to_cbz(album_temp_dir, final_cbz_path, metadata=meta_dict)

                    try:
                        with zipfile.ZipFile(final_cbz_path, 'r') as zf:
                            page_c = sum(1 for n in zf.namelist() if n.lower().endswith(IMAGE_EXTENSIONS))
                        _seed_media_index(final_cbz_path, {
                            'id': str(aid),
                            'page_count': page_c,
                            'has_cover': page_c > 0,
                            'author': meta_dict['author'],
                            'tags': meta_dict['tags'],
                            'is_complete': is_complete,
                            'online_chapters': total_photos,
                            'local_chapters': final_local_chapters,
                        })
                        _ALBUM_ID_TO_FILE[str(aid)] = final_cbz_path
                    except Exception:
                        pass

                    broadcast_manga_event({
                        'type': 'metadata_updated',
                        'filename': os.path.basename(final_cbz_path),
                        'title': meta_dict['title'],
                        'tags': meta_dict['tags'],
                        'is_complete': is_complete,
                        'online_chapters': total_photos,
                        'local_chapters': final_local_chapters,
                    })

                    if accept_partial:
                        logging.warning(f"Album {aid} 连续 {stall_count} 次补更新 0 收获，"
                                        f"缺 {total_photos - final_local_chapters} 章（JM 上已拉不下来），"
                                        f"标记 partial 并移出待下载列表")

                    if clean_temp and (not failed_photos or accept_partial):
                        shutil.rmtree(album_temp_dir, ignore_errors=True)

                    if not failed_photos or accept_partial:
                        remove_from_persistent_queue(aid, target_dir=dest_dir)

                with state_lock:
                    completed_count[0] += 1
                    active_jobs.pop(aid, None)
                update_task_progress()

            except Exception as e:
                logging.error(f"Error downloading album {aid}: {e}")
                try:
                    with open(os.path.join(paths.LOGS, "manga_batch_failures.log"), "a", encoding="utf-8") as _lf:
                        _lf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  JM{aid}  {e}\n")
                except Exception:
                    pass
                with state_lock:
                    active_jobs.pop(aid, None)
                    failed_albums.append({'id': str(aid), 'error': str(e)[:200]})
                update_task_progress()
            finally:
                # 每条出口都在这里销账一次；即便别处误多调一次也不能让 worker 整个挂掉
                try:
                    work_queue.task_done()
                except ValueError:
                    pass

    # 启动工作线程池 (1 路逐本顺序 或 3 路并发)
    concurrency = max(1, min(task_concurrency, len(task['clean_ids'])))
    threads = []
    task['status'] = 'downloading'
    update_task_progress()

    for w_idx in range(concurrency):
        t = threading.Thread(target=worker_loop, args=(w_idx + 1,), daemon=True)
        t.start()
        threads.append(t)

    # 等待队列中所有任务执行完毕
    for t in threads:
        t.join()

    BATCH_WORK_QUEUES.pop(task_id, None)

    total_albums = task['total_albums']
    done_total = completed_count[0]
    prefix = "📥 逐本顺序下载队列" if is_sequential else "⚡ 并发批量下载队列"
    if task.get('stopping'):
        task['status'] = 'stopped'
        pct = round((done_total / max(total_albums, 1)) * 100, 1)
        task['percent'] = min(pct, 100.0)
        task['title'] = f"⏹️ {prefix} (已按要求停止: {done_total}/{total_albums} 部)"
        task['message'] = f"已在当前作品下载打包完成后安全停止队列！共收录 {done_total}/{total_albums} 部，剩余作品保存在待下载列表中。"
        broadcast_manga_event({'type': 'batch_stopped', 'task': task})
    else:
        task['status'] = 'completed'
        task['percent'] = 100.0
        name_desc = "逐本顺序下载" if is_sequential else "并发批量下载"
        task['failed'] = failed_albums          # [{'id','error'}, ...] —— 前端可展示、日志见 cache/manga_batch_failures.log
        if failed_albums:
            ids = "、".join("JM" + f['id'] for f in failed_albums[:12])
            more = f" 等 {len(failed_albums)} 部" if len(failed_albums) > 12 else ""
            task['message'] = (f"下载结束：成功 {done_total}/{total_albums} 部。"
                               f"失败 {len(failed_albums)} 部（{ids}{more}）—— "
                               f"多为限流/下架，详见 cache/manga_batch_failures.log，可稍后重试。")
        else:
            task['message'] = f"🎉 {name_desc}已全部完成！已成功收录 {done_total}/{total_albums} 部作品！"
        broadcast_manga_event({'type': 'batch_completed', 'task': task})

def stop_batch_download_task(task_id: Optional[str] = None) -> bool:
    """
    优雅停止批量并发下载队列：
    标记 stopping 标志位。当前正在并发下载/打包的漫画完成后，工作线程不再领取新任务，
    剩余未下载的作品完整保存在待下载列表中。
    """
    found = False
    with TASKS_LOCK:
        for tid, t_info in DOWNLOAD_TASKS.items():
            if t_info.get('is_batch') and t_info.get('status') in ('queued', 'downloading'):
                if task_id is None or tid == task_id:
                    t_info['stopping'] = True
                    t_info['message'] = "⏹️ 已请求停止：正在等待当前并发的漫画下载打包完毕，完成后将自动暂停队列..."
                    broadcast_manga_event({'type': 'progress', 'task': t_info})
                    found = True
    return found

def start_batch_download_task(album_ids: List[str], pack_cbz: bool = True, clean_temp: bool = True, dest_dir: str = 'manga', concurrency: int = 3) -> str:
    """启动批量下载任务，支持 concurrency=1 (逐本顺序) 或 concurrency=3 (并发批量)"""
    with TASKS_LOCK:
        for tid, t_info in DOWNLOAD_TASKS.items():
            if t_info.get('is_batch') and t_info.get('status') in ('queued', 'downloading'):
                existing = t_info.get('clean_ids', [])
                q = BATCH_WORK_QUEUES.get(tid)
                added_count = 0
                for aid in album_ids:
                    aid_str = str(aid).strip()
                    if aid_str and aid_str not in existing:
                        existing.append(aid_str)
                        if q is not None:
                            q.put(aid_str)
                        added_count += 1
                t_info['total_albums'] = len(existing)
                is_seq = (t_info.get('concurrency', 3) == 1)
                prefix = "📥 逐本顺序下载队列" if is_seq else "⚡ 并发批量下载队列"
                t_info['title'] = f"{prefix} ({t_info.get('completed_albums', 0)}/{len(existing)} 部)"
                t_info['message'] = f"已将新加入的 {added_count} 部追加至当前下载队伍末尾 (总计 {len(existing)} 部)！"
                return tid

        task_id = f"batch_{int(time.time())}"
        is_seq = (concurrency == 1)
        prefix = "📥 逐本顺序下载队列" if is_seq else f"⚡ {concurrency}路并发批量下载队列"
        msg = f"准备逐本顺序下载 {len(album_ids)} 部作品..." if is_seq else f"准备以 {concurrency} 路并发下载 {len(album_ids)} 部作品..."
        DOWNLOAD_TASKS[task_id] = {
            'task_id': task_id,
            'is_batch': True,
            'concurrency': concurrency,
            'title': f"{prefix} (共 {len(album_ids)} 部)",
            'status': 'queued',
            'percent': 0.0,
            'message': msg,
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

def scan_and_recover_temp_manga(target_dir: str = 'manga') -> Dict[str, Any]:
    """
    扫描 .temp 目录下未完成下载且未打包入库的漫画碎片，
    若不在待下载列表中，自动找回并追加回持久化待下载列表。
    """
    if not os.path.exists(temp_dir()):
        return {'recovered_count': 0, 'recovered_items': []}

    target_dir_path = novels_dir() if str(target_dir).lower() in ('novels', 'novel') else manga_dir()
    q_items = get_persistent_queue(target_dir)
    q_ids = {str(it.get('id')) for it in q_items if it.get('id')}

    recovered = []
    client = None

    for item in sorted(os.listdir(temp_dir())):
        item_path = os.path.join(temp_dir(), item)
        if not os.path.isdir(item_path):
            continue
        aid = str(item).strip()
        if not aid.isdigit():
            continue

        file_count = sum(len(fl) for _, _, fl in os.walk(item_path))
        if file_count == 0:
            try:
                shutil.rmtree(item_path, ignore_errors=True)
            except Exception:
                pass
            continue

        # 核心过滤：若本地已有完整 CBZ，说明是历史打包成功后残留的碎片，自动清理并跳过
        existing_cbz = find_existing_cbz_by_aid(aid, target_dir_path)
        if existing_cbz and os.path.exists(existing_cbz) and os.path.getsize(existing_cbz) > 10240:
            try:
                with zipfile.ZipFile(existing_cbz, 'r') as zf:
                    nl = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
                    inner_dirs = sorted(list({n.split('/')[0] for n in nl if '/' in n}))
                    existing_chapter_count = len(inner_dirs) if inner_dirs else (1 if any(n.lower().endswith(IMAGE_EXTENSIONS) for n in nl) else 0)
                    if 'metadata.json' in nl:
                        _pm = json.loads(zf.read('metadata.json').decode('utf-8'))
                        if _pm.get('is_complete') or existing_chapter_count >= _pm.get('online_chapters', 999999):
                            shutil.rmtree(item_path, ignore_errors=True)
                            continue
            except Exception:
                pass

        # 检查如果当前不在队列中，找回并加入
        if aid not in q_ids:
            title = f"JM{aid}"
            cover_url = f"/api/manga/online_cover?id={aid}"
            try:
                if client is None:
                    client = get_jm_client()
                detail = client.get_album_detail(aid)
                if detail and detail.title:
                    title = detail.title
            except Exception:
                pass

            recovered_item = {'id': aid, 'title': title, 'cover_url': cover_url}
            q_items.append(recovered_item)
            q_ids.add(aid)
            recovered.append(recovered_item)

    if recovered:
        save_persistent_queue(q_items, target_dir=target_dir)

    return {
        'recovered_count': len(recovered),
        'recovered_items': recovered
    }

def get_all_tasks() -> List[Dict[str, Any]]:
    """获取所有下载任务状态 (纯净化确保完全可 JSON 序列化)"""
    with TASKS_LOCK:
        res = []
        for t in DOWNLOAD_TASKS.values():
            res.append({k: v for k, v in t.items() if not k.startswith('_') and not isinstance(v, queue.Queue)})
        return sorted(res, key=lambda x: x.get('created_at', 0), reverse=True)

def manual_pack_manga(folder_name: str, target_name: Optional[str] = None, dest_dir: str = 'manga') -> bool:
    """将 .temp 下的一个目录手动打包为 .cbz"""
    src = os.path.join(temp_dir(), folder_name)
    if not os.path.isdir(src):
        return False
    cbz_name = sanitize_filename(target_name or folder_name) + ".cbz"
    target_dir_path = novels_dir() if str(dest_dir).lower() in ('novels', 'novel') else manga_dir()
    dst = os.path.join(target_dir_path, cbz_name)
    pack_folder_to_cbz(src, dst)
    return True

def clean_all_temp_files() -> int:
    """一键清理 .temp/ 目录下的所有临时下载切片碎片"""
    count = 0
    if os.path.exists(temp_dir()):
        for item in os.listdir(temp_dir()):
            p = os.path.join(temp_dir(), item)
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

def is_active_downloading() -> bool:
    """检查当前是否有活跃的由用户发起的下载任务正在进行"""
    with TASKS_LOCK:
        return any(
            t.get('status') in ('downloading', 'queued') and not t.get('is_background_audit')
            for t in DOWNLOAD_TASKS.values()
        )

def match_and_repair_cbz_metadata(cbz_path: str, client=None) -> Optional[Dict[str, Any]]:
    """
    自动为缺失元数据的旧 CBZ 文件在线匹配漫画、核验完整性，并将 metadata.json 与 ComicInfo.xml 写入压缩包
    """
    if not os.path.exists(cbz_path) or os.path.getsize(cbz_path) < 1024:
        return None

    try:
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            namelist = [n for n in zf.namelist() if not n.endswith('/') and not os.path.basename(n).startswith('.')]
            if 'metadata.json' in namelist:
                try:
                    meta = json.loads(zf.read('metadata.json').decode('utf-8'))
                    if meta.get('verified') or (meta.get('tags') and meta.get('is_complete') is not None):
                        return meta
                except Exception:
                    pass

            inner_dirs = sorted(list({n.split('/')[0] for n in namelist if '/' in n}))
            img_files = [n for n in namelist if n.lower().endswith(IMAGE_EXTENSIONS)]
            if len(img_files) == 0:
                return None
    except Exception as e:
        logging.warning(f"Error reading cbz {cbz_path}: {e}")
        return None

    if client is None:
        client = get_jm_client()

    fname = os.path.basename(cbz_path)
    base_name = os.path.splitext(fname)[0]

    clean_name = re.sub(r'\[.*?\]', '', base_name).strip()
    clean_core = re.sub(r'(\(.*?\)|\[.*?\])', '', base_name).strip()
    clean_sub = clean_name.replace('_', ' ').strip()
    parts = [p.strip() for p in clean_name.split('_') if p.strip()]

    # 从括号中提取作者名或社团名作为检索候选
    bracket_authors = []
    for b in re.findall(r'\[(.*?)\]', base_name):
        b_clean = b.strip()
        if b_clean:
            bracket_authors.append(b_clean)
            sub_parens = re.findall(r'\((.*?)\)', b_clean)
            bracket_authors.extend([sp.strip() for sp in sub_parens if sp.strip()])

    queries = []
    for q in [clean_core, clean_name, clean_sub] + parts + bracket_authors + inner_dirs + [base_name]:
        q = q.strip()
        if q and len(q) >= 2 and q not in queries:
            queries.append(q)

    matched_aid = None

    for q in queries[:6]:
        try:
            page = client.search_site(search_query=q)
            if not page:
                continue
            for aid, atitle in page:
                raw_name = atitle.get('name', '') if isinstance(atitle, dict) else (getattr(atitle, 'name', None) or str(atitle))
                c_clean = sanitize_filename(raw_name)
                # 精确匹配全名、清理名或核心名
                if (c_clean == base_name or raw_name == base_name or
                    re.sub(r'\[.*?\]', '', c_clean).strip() == clean_name or
                    (clean_core and clean_core in raw_name and len(clean_core) >= 4)):
                    matched_aid = aid
                    break
            if matched_aid:
                break
            if len(page) == 1:
                matched_aid = page[0][0]
                break
        except Exception:
            continue

    if not matched_aid:
        return None

    try:
        detail = client.get_album_detail(str(matched_aid))
        online_chapters = len(detail)
        local_chapters = len(inner_dirs) if inner_dirs else 1
        is_complete = (local_chapters >= online_chapters) if online_chapters > 1 else (len(img_files) > 0)

        meta_dict = {
            'id': str(matched_aid),
            'title': detail.title,
            'author': getattr(detail, 'author', '') or '',
            'description': getattr(detail, 'description', '') or '',
            'tags': getattr(detail, 'tags', []) or [],
            'online_chapters': online_chapters,
            'local_chapters': local_chapters,
            'is_complete': is_complete,
            'verified': True,
            'verified_at': int(time.time()),
        }

        with zipfile.ZipFile(cbz_path, 'a') as zf:
            meta_json = json.dumps(meta_dict, ensure_ascii=False, indent=2)
            zf.writestr("metadata.json", meta_json)

            title_xml = html.escape(str(meta_dict.get('title', '')))
            writer_xml = html.escape(str(meta_dict.get('author', '')))
            summary_xml = html.escape(str(meta_dict.get('description', '')))
            tags_list = meta_dict.get('tags', [])
            tags_xml = html.escape(','.join(tags_list) if isinstance(tags_list, list) else str(tags_list))
            album_id = meta_dict.get('id', '')

            comic_info_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Title>{title_xml}</Title>
  <Writer>{writer_xml}</Writer>
  <Summary>{summary_xml}</Summary>
  <Genre>{tags_xml}</Genre>
  <Tags>{tags_xml}</Tags>
  <Web>https://18comic.vip/album/{album_id}</Web>
</ComicInfo>"""
            zf.writestr("ComicInfo.xml", comic_info_xml)

        _seed_media_index(cbz_path, {
            'id': str(album_id),
            'page_count': len(img_files),
            'has_cover': len(img_files) > 0,
            'author': meta_dict['author'],
            'tags': meta_dict['tags'],
            'is_complete': is_complete,
            'online_chapters': online_chapters,
            'local_chapters': local_chapters,
        })
        if album_id:
            _ALBUM_ID_TO_FILE[str(album_id)] = cbz_path

        return meta_dict
    except Exception as e:
        logging.error(f"Error repairing metadata for {cbz_path}: {e}")
        return None

_DOWNLOAD_YIELD_POLL_S = 5.0


def _wait_until_downloads_idle():
    """阻塞等待，直到没有用户主动发起的下载任务在跑（后台巡检给用户下载让路用）。"""
    while is_active_downloading():
        time.sleep(_DOWNLOAD_YIELD_POLL_S)


def _auto_metadata_audit_worker():
    """
    后台静默巡检守护线程：
    1. 启动延迟 12 秒，不干扰系统启动和首屏体验；
    2. 发现缺少标签与元数据的旧 CBZ，自动通过标题在线匹配补齐标签与元数据；
    3. 自行检查漫画各章节完整性，校验是否完整收录；
    4. 遇用户正在主动下载时，自动挂起避让；
    5. 每本处理平稳间隔 2.5 秒，低调防限频。
    """
    time.sleep(12.0)
    audit_state_file = os.path.join(manga_dir(), '.metadata_audit.json')

    while True:
        try:
            audit_state = {}
            if os.path.exists(audit_state_file):
                try:
                    with open(audit_state_file, 'r', encoding='utf-8') as f:
                        audit_state = json.load(f)
                except Exception:
                    pass

            unmatched = set(audit_state.get('unmatched', []))
            client = get_jm_client()

            if os.path.exists(manga_dir()):
                cbz_files = [f for f in sorted(os.listdir(manga_dir())) if f.lower().endswith('.cbz') and not f.startswith('.')]
                for fname in cbz_files:
                    if fname in unmatched:
                        continue

                    full_path = os.path.join(manga_dir(), fname)
                    if not os.path.isfile(full_path):
                        continue

                    # 探测是否需要补全
                    needs_repair = False
                    try:
                        with zipfile.ZipFile(full_path, 'r') as zf:
                            namelist = zf.namelist()
                            if 'metadata.json' not in namelist:
                                needs_repair = True
                            else:
                                meta = json.loads(zf.read('metadata.json').decode('utf-8'))
                                if not meta.get('tags') or meta.get('is_complete') is None:
                                    needs_repair = True
                    except Exception:
                        needs_repair = False

                    if not needs_repair:
                        continue

                    # 用户正在主动下载时，优雅避让挂起
                    _wait_until_downloads_idle()

                    # 执行元数据补全与完整性核验
                    res = match_and_repair_cbz_metadata(full_path, client=client)
                    if res:
                        broadcast_manga_event({
                            'type': 'metadata_updated',
                            'filename': fname,
                            'title': res.get('title', ''),
                            'tags': res.get('tags', []),
                            'is_complete': res.get('is_complete', True),
                            'online_chapters': res.get('online_chapters', 0),
                            'local_chapters': res.get('local_chapters', 0),
                        })
                    else:
                        unmatched.add(fname)
                        audit_state['unmatched'] = list(unmatched)
                        try:
                            with open(audit_state_file, 'w', encoding='utf-8') as f:
                                json.dump(audit_state, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass

                    # 间隔 2.5 秒，平稳静默运行
                    time.sleep(2.5)

        except Exception as e:
            logging.error(f"Error in auto_metadata_audit_worker: {e}")

        # 一轮巡检完成，休眠 2 小时后进行下一轮巡检
        time.sleep(7200)

def start_auto_metadata_audit():
    """启动后台静默元数据补全与完整性核验守护服务"""
    t = threading.Thread(target=_auto_metadata_audit_worker, daemon=True, name="AutoMangaAuditor")
    t.start()

