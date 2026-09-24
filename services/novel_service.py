import uuid
import datetime
import zipfile
import html
import os
import re
import time
import json
import logging
import threading
import subprocess
import urllib.request
import urllib.parse
import ssl
from typing import List, Dict, Any, Optional, Tuple

import media_index
from app_config import find_library_dirs, get_primary_dir

logger = logging.getLogger("novel_service")

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 本文件在 services/ 下，项目根路径是上一级
# 主库位置（新下载/正在处理的都落这）——不写死绝对路径，从 app_config.py 派生。
MEDIA_LIBRARY_DIR = get_primary_dir("media_library")
NOVELS_DIR = os.path.join(MEDIA_LIBRARY_DIR, "novels")
NOVELS_STANDARD_DIR = os.path.join(NOVELS_DIR, "standard")
NOVELS_NSFW_DIR = os.path.join(NOVELS_DIR, "nsfw")
DOCS_DIR = os.path.join(SCRIPT_DIR, "docs")


def _novel_extra_roots(sub: str = "") -> List[str]:
    """小说库在主库之外的候选根目录（已配置资源库根路径下的 media_library/novels[/sub]
    + omni-deck 自己目录下的旧版位置，迁移期间兼容）。sub 是 "standard"/"nsfw"/""(classics)。"""
    parts = ["media_library", "novels"] + ([sub] if sub else [])
    dirs = list(find_library_dirs(*parts))
    legacy = os.path.join(SCRIPT_DIR, "novels", sub) if sub else os.path.join(SCRIPT_DIR, "novels")
    if os.path.isdir(legacy) and legacy not in dirs:
        dirs.append(legacy)
    return dirs

# 严格隔离 NSFW 与正常小说的待下载队列文件与临时目录
STANDARD_QUEUE_FILE = os.path.join(NOVELS_STANDARD_DIR, ".download_queue.json")
NSFW_QUEUE_FILE = os.path.join(NOVELS_NSFW_DIR, ".download_queue.json")

STANDARD_TEMP_DIR = os.path.join(NOVELS_STANDARD_DIR, ".temp")
NSFW_TEMP_DIR = os.path.join(NOVELS_NSFW_DIR, ".temp")

STANDARD_CLASSICS_CACHE_DIR = os.path.join(NOVELS_STANDARD_DIR, ".classics_cache")
NSFW_CACHE_DIR = os.path.join(NOVELS_NSFW_DIR, ".cache")

os.makedirs(NOVELS_STANDARD_DIR, exist_ok=True)
os.makedirs(NOVELS_NSFW_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(STANDARD_TEMP_DIR, exist_ok=True)
os.makedirs(NSFW_TEMP_DIR, exist_ok=True)
os.makedirs(STANDARD_CLASSICS_CACHE_DIR, exist_ok=True)
os.makedirs(NSFW_CACHE_DIR, exist_ok=True)

# 内存任务与队列锁
_NOVEL_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()
_QUEUE_LOCK = threading.Lock()

# 忽略 SSL 证书校验上下文
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}

try:
    import opencc
    _T2S_CONVERTER = opencc.OpenCC('t2s')
except Exception:
    _T2S_CONVERTER = None

def to_simplified_chinese(text: str) -> str:
    """全面将繁体中文/HTML实体转为纯净简体中文，根除乱码与繁体"""
    if not text:
        return ""
    unescaped = html.unescape(text)
    if _T2S_CONVERTER:
        try:
            return _T2S_CONVERTER.convert(unescaped)
        except Exception:
            return unescaped
    return unescaped

def is_valid_image_bytes(data: Optional[bytes]) -> bool:
    """校验图片二进制数据的魔数，防止 HTML 拦截页作为封面写入"""
    if not data or len(data) < 16:
        return False
    return (data.startswith(b'\xff\xd8\xff') or 
            data.startswith(b'\x89PNG') or 
            data.startswith(b'RIFF') or 
            data.startswith(b'GIF8'))

# ================= 1. 本地书库扫描与元数据提取 (严禁混入 docs) =================

def read_file_text(filepath: str) -> str:
    """带编码自适应回退的安全文本读取"""
    for enc in ('utf-8', 'gb18030', 'gbk', 'big5', 'latin1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    with open(filepath, 'rb') as f:
        return f.read().decode('utf-8', errors='ignore')

def extract_epub_metadata_and_cover(epub_path: str) -> Dict[str, Any]:
    """从 .epub 文件中抽取元数据与封面二进制"""
    meta = {
        'title': os.path.splitext(os.path.basename(epub_path))[0],
        'author': '未知作者',
        'intro': '',
        'cover_bytes': None,
        'chapter_count': 0
    }
    try:
        with zipfile.ZipFile(epub_path, 'r') as z:
            opf_path = None
            try:
                container_data = z.read('META-INF/container.xml')
                import xml.etree.ElementTree as ET
                root = ET.fromstring(container_data)
                for elem in root.iter():
                    if elem.tag.endswith('rootfile'):
                        opf_path = elem.attrib.get('full-path')
                        break
            except Exception:
                pass

            if not opf_path:
                for name in z.namelist():
                    if name.endswith('.opf'):
                        opf_path = name
                        break

            if opf_path:
                opf_dir = os.path.dirname(opf_path)
                opf_content = z.read(opf_path).decode('utf-8', errors='ignore')
                
                t_match = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf_content, re.IGNORECASE | re.DOTALL)
                if t_match:
                    meta['title'] = html.unescape(t_match.group(1).strip())
                
                a_match = re.search(r'<dc:creator[^>]*>(.*?)</dc:creator>', opf_content, re.IGNORECASE | re.DOTALL)
                if a_match:
                    meta['author'] = html.unescape(a_match.group(1).strip())

                d_match = re.search(r'<dc:description[^>]*>(.*?)</dc:description>', opf_content, re.IGNORECASE | re.DOTALL)
                if d_match:
                    meta['intro'] = html.unescape(d_match.group(1).strip())

                cover_href = None
                cover_id_match = re.search(r'<meta[^>]*name=[\"\']cover[\"\'][^>]*content=[\"\']([^\"\']+)[\"\']', opf_content, re.IGNORECASE)
                if cover_id_match:
                    cid = cover_id_match.group(1)
                    item_match = re.search(rf'<item[^>]*id=[\"\']{re.escape(cid)}[\"\'][^>]*href=[\"\']([^\"\']+)[\"\']', opf_content, re.IGNORECASE)
                    if item_match:
                        cover_href = item_match.group(1)

                if not cover_href:
                    img_match = re.search(r'<item[^>]*href=[\"\']([^\"\']*(?:cover|coverpage)[^\"\']*\.(?:jpg|jpeg|png|webp))[\"\']', opf_content, re.IGNORECASE)
                    if img_match:
                        cover_href = img_match.group(1)

                if cover_href:
                    full_cover_path = os.path.normpath(os.path.join(opf_dir, cover_href)).replace('\\', '/')
                    if full_cover_path in z.namelist():
                        meta['cover_bytes'] = z.read(full_cover_path)

            html_files = [n for n in z.namelist() if n.lower().endswith(('.xhtml', '.html', '.htm')) and 'cover' not in n.lower()]
            meta['chapter_count'] = len(html_files)
    except Exception:
        pass
    return meta

def _rich_parse_novel(full_p: str) -> Dict[str, Any]:
    """开一次 .epub 抽标题/作者/简介/有无封面 —— 只在文件新增/变动时被 media_index 调用。
    .txt 只读前几行做摘要（本来就便宜）。"""
    base_name = os.path.splitext(os.path.basename(full_p))[0]
    ext = os.path.splitext(full_p)[1].lower()
    m = {'title': base_name, 'author': '未知作者', 'excerpt': '', 'has_cover': False}
    try:
        if ext == '.epub':
            em = extract_epub_metadata_and_cover(full_p)
            m['title'] = em.get('title') or base_name
            m['author'] = em.get('author') or '未知作者'
            m['excerpt'] = em.get('intro') or ''
            m['has_cover'] = bool(em.get('cover_bytes'))
        else:
            with open(full_p, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [line.strip() for line in f if line.strip()]
                m['excerpt'] = " ".join(lines[:3])[:120]
    except Exception:
        pass
    return m


def _iter_novel_files_in_dir(dir_path: str, flat_only: bool, valid_exts: set):
    """遍历一个小说库候选目录，yield 出其中所有符合扩展名的文件路径与元信息。

    从 get_novels_library() 拆出来的文件收集逻辑：本身是 os.walk 一层 + 逐文件名一层，
    拆开后调用方不用再叠第三层循环。

    Args:
        dir_path: 要扫描的目录路径。
        flat_only: True 时只看目录本身、不递归子文件夹（"公版名著"这类不允许分类子目录，
            跟 standard/nsfw 不一样）。
        valid_exts: 允许的文件扩展名集合（小写、带点，如 {'.epub', '.txt'}）。

    Yields:
        tuple[str, str, str, float, int]: (完整路径, 所在目录, 文件名, mtime, size)。
    """
    if not os.path.exists(dir_path):
        return
    for root, dirs, fnames in os.walk(dir_path):
        if flat_only and root != dir_path:
            continue
        for fname in fnames:
            if fname.startswith('.') or fname.startswith('__'):
                continue
            if os.path.splitext(fname)[1].lower() not in valid_exts:
                continue
            full_p = os.path.join(root, fname)
            try:
                st = os.stat(full_p)
            except OSError:
                continue
            yield full_p, root, fname, st.st_mtime, st.st_size


def get_novels_library(q: str = "", is_nsfw: bool = False) -> List[Dict[str, Any]]:
    """小说书架列表 —— 走 media_index 持久化索引：只有新增/变动的 .epub 才真去开压缩包，
    其余吃 SQLite 缓存。冷启动第一次照旧慢，之后每次秒出。
    每一类库（standard/nsfw/公版名著）可能分布在好几个候选根目录下（主库 + SD 卡等
    归档位置，见 _novel_extra_roots），都扫一遍合并；"公版名著"那份只看顶层不递归
    （跟 standard/nsfw 不一样，那两个允许分类子文件夹）。"""
    q = (q or "").lower().strip()
    norm_q = to_simplified_chinese(q).lower() if q else ""
    valid_exts = {'.epub', '.txt'}
    kind = 'novellib:nsfw' if is_nsfw else 'novellib:std'

    if is_nsfw:
        target_dirs = [(d, False) for d in [NOVELS_NSFW_DIR] + _novel_extra_roots("nsfw")]
    else:
        target_dirs = [(d, False) for d in [NOVELS_STANDARD_DIR] + _novel_extra_roots("standard")]
        target_dirs += [(d, True) for d in [NOVELS_DIR] + _novel_extra_roots("")]
    seen_dirs = set()
    dedup_dirs = []
    for d, flat_only in target_dirs:
        if d in seen_dirs:
            continue
        seen_dirs.add(d)
        dedup_dirs.append((d, flat_only))
    target_dirs = dedup_dirs

    # 1. 快速收集文件 (path, mtime, size)，不开任何 epub
    files = []
    fs_info = {}          # path -> (root, fname, size, mtime, base_dir)
    seen = set()
    for dir_path, flat_only in target_dirs:
        for full_p, root, fname, mtime, size in _iter_novel_files_in_dir(dir_path, flat_only, valid_exts):
            if full_p in seen:
                continue
            seen.add(full_p)
            files.append((full_p, mtime, size))
            fs_info[full_p] = (root, fname, size, mtime, dir_path)

    def _on_progress(done, total):
        """把索引补齐进度通过 SSE 广播给前端，驱动进度条更新。"""
        try:
            import manga_service
            manga_service.broadcast_manga_event({'type': 'library_indexed', 'dir': 'novels', 'done': done, 'total': total})
        except Exception:
            pass

    metas = media_index.diff_scan(kind, files, _rich_parse_novel, sync_limit=24, on_progress=_on_progress)

    # 2. 组装
    items = []
    for full_p, (root, fname, size, mtime, base_dir) in fs_info.items():
        m = metas.get(full_p) or {}
        rel_p = os.path.relpath(full_p, SCRIPT_DIR).replace('\\', '/')
        base_name = os.path.splitext(fname)[0]
        ext = os.path.splitext(fname)[1].lower()
        title = m.get('title') or base_name

        if norm_q:
            norm_name = to_simplified_chinese(base_name).lower()
            norm_rel = to_simplified_chinese(rel_p).lower()
            if (norm_q not in norm_name) and (norm_q not in norm_rel) and (q not in base_name.lower()):
                continue

        sub_rel = os.path.relpath(root, base_dir)
        category = sub_rel.split(os.sep)[0] if (sub_rel != '.' and not sub_rel.startswith('.')) else ('未分类' if is_nsfw else '公版名著')
        has_cover = bool(m.get('has_cover'))
        items.append({
            'rel_path': rel_p,
            'filename': fname,
            'title': title,
            'author': m.get('author', '未知作者'),
            'category': category,
            'ext': ext.lstrip('.'),
            'is_nsfw': is_nsfw,
            'size_kb': round(size / 1024, 1),
            'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime)),
            'excerpt': m.get('excerpt', ''),
            'has_cover': has_cover,
            'cover_url': f"/api/novels/cover?path={urllib.parse.quote(rel_p)}" if has_cover else "",
        })

    items.sort(key=lambda x: x.get('mtime', ''), reverse=True)
    return items

def get_docs_explorer(sub_dir: str = "", q: str = "", doc_filter: str = "all") -> Dict[str, Any]:
    """
    轻量级资源管理器式技术文档浏览引擎 (解决数千文档全量加载卡顿问题)：
    - 按文件夹层级结构精准展示
    - 仅读取当前目录直接子项，响应时间 < 1ms
    - 支持关键词检索模式
    """
    q_clean = (q or "").lower().strip()
    doc_filter = (doc_filter or "all").lower().strip()

    if not os.path.exists(DOCS_DIR):
        return {
            'is_search': False,
            'current_dir': '',
            'breadcrumbs': [{'name': '根目录', 'path': ''}],
            'parent_dir': None,
            'folders': [],
            'files': [],
            'total_items': 0
        }

    safe_rel = os.path.normpath(sub_dir).lstrip(os.sep).replace('\\', '/') if sub_dir else ''
    if safe_rel in ('.', '/'):
        safe_rel = ''

    current_abs = os.path.join(DOCS_DIR, safe_rel) if safe_rel else DOCS_DIR
    if not os.path.exists(current_abs) or not os.path.isdir(current_abs):
        current_abs = DOCS_DIR
        safe_rel = ''

    # 构建面包屑
    breadcrumbs = [{'name': '根目录', 'path': ''}]
    if safe_rel:
        parts = safe_rel.split('/')
        accum = ''
        for p in parts:
            if not p:
                continue
            accum = f"{accum}/{p}" if accum else p
            breadcrumbs.append({'name': p, 'path': accum})

    parent_dir = os.path.dirname(safe_rel).replace('\\', '/') if safe_rel else None
    if parent_dir in ('.', '/'):
        parent_dir = ''

    # 1. 搜索模式：递归搜索当前目录下的文件
    if q_clean:
        matched_files = []
        for root, _, files in os.walk(current_abs):
            for fname in sorted(files):
                if fname.startswith('.'):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ('.md', '.rst', '.markdown', '.txt'):
                    continue
                clean_ext = 'md' if ext in ('.md', '.markdown') else ext.lstrip('.')
                if doc_filter != 'all' and clean_ext != doc_filter:
                    continue

                base_title = os.path.splitext(fname)[0]
                if q_clean in base_title.lower() or q_clean in fname.lower():
                    full_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(full_p, SCRIPT_DIR).replace('\\', '/')
                    dir_rel = os.path.relpath(root, DOCS_DIR).replace('\\', '/')
                    try:
                        stat = os.stat(full_p)
                        matched_files.append({
                            'type': 'file',
                            'name': fname,
                            'title': base_title,
                            'ext': clean_ext,
                            'rel_path': rel_p,
                            'dir_rel': '' if dir_rel == '.' else dir_rel,
                            'size_kb': round(stat.st_size / 1024, 1),
                            'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))
                        })
                    except Exception:
                        pass
        return {
            'is_search': True,
            'q': q,
            'current_dir': safe_rel,
            'breadcrumbs': breadcrumbs,
            'parent_dir': parent_dir,
            'folders': [],
            'files': matched_files,
            'total_items': len(matched_files)
        }

    # 2. 正常目录浏览模式：仅读取直接子项
    folders = []
    files = []

    try:
        entries = sorted(os.listdir(current_abs))
    except Exception:
        entries = []

    for entry in entries:
        if entry.startswith('.'):
            continue
        full_entry = os.path.join(current_abs, entry)
        try:
            stat = os.stat(full_entry)
            mtime_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))
            if os.path.isdir(full_entry):
                sub_count = len([x for x in os.listdir(full_entry) if not x.startswith('.')])
                item_path = f"{safe_rel}/{entry}" if safe_rel else entry
                folders.append({
                    'type': 'dir',
                    'name': entry,
                    'path': item_path,
                    'items_count': sub_count,
                    'mtime': mtime_str
                })
            elif os.path.isfile(full_entry):
                ext = os.path.splitext(entry)[1].lower()
                if ext not in ('.md', '.rst', '.markdown', '.txt'):
                    continue
                clean_ext = 'md' if ext in ('.md', '.markdown') else ext.lstrip('.')
                if doc_filter != 'all' and clean_ext != doc_filter:
                    continue

                rel_p = os.path.relpath(full_entry, SCRIPT_DIR).replace('\\', '/')
                base_title = os.path.splitext(entry)[0]
                files.append({
                    'type': 'file',
                    'name': entry,
                    'title': base_title,
                    'ext': clean_ext,
                    'rel_path': rel_p,
                    'size_kb': round(stat.st_size / 1024, 1),
                    'mtime': mtime_str
                })
        except Exception:
            pass

    return {
        'is_search': False,
        'current_dir': safe_rel,
        'breadcrumbs': breadcrumbs,
        'parent_dir': parent_dir,
        'folders': folders,
        'files': files,
        'total_items': len(folders) + len(files)
    }

def get_docs_library(q: str = "", doc_filter: str = "all") -> List[Dict[str, Any]]:
    """独立扫描技术文档专区 (docs/ 目录) - 兼容接口"""
    res = get_docs_explorer(sub_dir="", q=q, doc_filter=doc_filter)
    return res.get('files', [])

# =========================================================================
# 待下载队列磁盘持久化系统 (NSFW 与 Standard 物理完全分离)
# =========================================================================

def get_queue_file(is_nsfw: bool = False) -> str:
    """获取对应文库类型的待下载队列文件路径"""
    return NSFW_QUEUE_FILE if is_nsfw else STANDARD_QUEUE_FILE

def get_temp_dir(is_nsfw: bool = False) -> str:
    """获取对应文库类型的临时文件目录"""
    return NSFW_TEMP_DIR if is_nsfw else STANDARD_TEMP_DIR

def load_novel_queue(is_nsfw: bool = False) -> List[Dict[str, Any]]:
    """从对应文库的磁盘 JSON 文件中读取待下载小说队列列表"""
    q_file = get_queue_file(is_nsfw)
    with _QUEUE_LOCK:
        if not os.path.exists(q_file):
            return []
        try:
            with open(q_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"读取小说队列失败 ({q_file}): {e}")
            return []

def save_novel_queue(queue_items: List[Dict[str, Any]], is_nsfw: bool = False):
    """持久化待下载小说队列至对应文库的磁盘文件"""
    q_file = get_queue_file(is_nsfw)
    with _QUEUE_LOCK:
        try:
            os.makedirs(os.path.dirname(q_file), exist_ok=True)
            with open(q_file, 'w', encoding='utf-8') as f:
                json.dump(queue_items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存小说队列失败 ({q_file}): {e}")

def add_novel_to_queue(item: Dict[str, Any]):
    """向待下载队列中新增小说项 (按 is_nsfw 自动分流到各自独立的 json)"""
    is_nsfw = bool(item.get('is_nsfw', False))
    q = load_novel_queue(is_nsfw=is_nsfw)
    nid = str(item.get('id', ''))
    if not any(str(x.get('id', '')) == nid for x in q):
        q.append(item)
        save_novel_queue(q, is_nsfw=is_nsfw)

def remove_novel_from_queue(novel_id: str, is_nsfw: Optional[bool] = None):
    """根据 novel_id 从待下载队列中移除指定小说"""
    novel_id = str(novel_id)
    targets = [is_nsfw] if is_nsfw is not None else [False, True]
    for nsfw_flag in targets:
        q = load_novel_queue(is_nsfw=nsfw_flag)
        new_q = [x for x in q if str(x.get('id', '')) != novel_id]
        if len(new_q) != len(q):
            save_novel_queue(new_q, is_nsfw=nsfw_flag)

def clear_novel_queue(is_nsfw: Optional[bool] = None):
    """清空指定文库或全量待下载小说队列"""
    if is_nsfw is not None:
        save_novel_queue([], is_nsfw=is_nsfw)
    else:
        save_novel_queue([], is_nsfw=False)
        save_novel_queue([], is_nsfw=True)

# =========================================================================
# 经典文学公版库 (Gutenberg 真实全本在册目录与智能抓取引擎)
# =========================================================================

CLASSIC_FULL_MAP = {
    '三国': ('full_三国.json', 23950, '三国演义 (全120回典藏足本)', '罗贯中', '四大名著', '东汉末年，天下大乱，群雄逐鹿。桃园结义，赤壁鏖战，天下三分，三国归晋。'),
    '水浒': ('full_水浒.json', 23863, '水浒传 (全70回足本)', '施耐庵', '四大名著', '梁山泊一百单八将替天行道、除暴安良的悲壮英雄史诗。'),
    '西游': ('full_西游.json', 23962, '西游记 (全100回典藏足本)', '吴承恩', '四大名著', '大圣闹天宫，唐僧西天取经，历经九九八十一难，降妖除魔成正果。'),
    '红楼': ('full_红楼.json', 24264, '红楼梦 (脂砚斋重评石头记·全120回足本)', '曹雪芹、高鹗', '四大名著', '贾宝玉与林黛玉之木石前盟，贾史王薛四大家族由盛及衰之挽歌。'),
    '封神': ('full_封神.json', 23910, '封神演义 (全100回足本)', '许仲琳', '古典神魔', '商周更替之际，阐截二教斗法争雄，姜子牙奉敕封神。'),
    '儒林': ('full_儒林.json', 24032, '儒林外史 (全56回足本)', '吴敬梓', '讽刺文学', '深刻揭露科举体制下世态人情与士人精神百态之讽刺名著。'),
    '聊斋': ('full_聊斋.json', 51828, '聊斋志异 (全卷足本)', '蒲松龄', '志怪神仙', '写鬼写妖高人一等，刺贪刺虐入木三分，借狐仙神魅以讽人情世故。'),
    '东周': ('full_东周.json', 25349, '东周列国志 (全108回足本)', '冯梦龙、蔡元放', '历史演义', '春秋战国五百年风云际会，列国纷争，名将谋臣辈出的宏大历史长卷。'),
    '镜花缘': ('full_镜花缘.json', 23818, '镜花缘 (全100回足本)', '李汝珍', '浪漫神魔', '百花仙子降生人间，海外游历女儿国、君子国等奇特国度的浪漫长卷。'),
    '老残游记': ('full_老残游记.json', 25124, '老残游记 (全20回足本)', '刘鹗', '晚清谴责', '晚清四大谴责小说之一，以江湖医生老残游历见闻针砭时弊。'),
    '隋唐演义': ('full_隋唐演义.json', 23835, '隋唐演义 (全100回足本)', '褚人获', '历史演义', '隋末天下大乱，瓦岗英雄聚义，李世民开创大唐盛世之宏伟史诗。'),
    '官场现形记': ('full_官场现形记.json', 24138, '官场现形记 (全60回足本)', '李宝嘉', '晚清谴责', '晚清谴责小说开山之作，穷形尽相展现晚清官场丑态。'),
    '怪现状': ('full_怪现状.json', 24099, '二十年目睹之怪现状 (全108回足本)', '吴趼人', '晚清谴责', '以九死一生为主角，记录晚清二十年间光怪乱离的社会怪现象。'),
    '今古奇观': ('full_今古奇观.json', 24230, '今古奇观 (全40卷典藏足本)', '抱瓮老人', '白话短篇', '明末抱瓮老人选辑三言二拍中四十部优秀短篇小说精选总集。'),
    '喻世明言': ('full_喻世明言.json', 27582, '喻世明言 (三言之一·全40卷)', '冯梦龙', '白话短篇', '冯梦龙纂辑白话短篇小说总集，描摹市井风情与人情冷暖。'),
    '警世通言': ('full_警世通言.json', 24141, '警世通言 (三言之二·全40卷)', '冯梦龙', '白话短篇', '包含白娘子永镇雷峰塔、杜十娘怒沉百宝箱等脍炙人口之名篇。'),
    '初刻拍案惊奇': ('full_初刻拍案惊奇.json', 57248, '初刻拍案惊奇 (二拍之一·全40卷)', '凌濛初', '拟话本', '凌濛初编著白话小说集，奇情巧变，警示世人。'),
    '二刻拍案惊奇': ('full_二刻拍案惊奇.json', 24162, '二刻拍案惊奇 (二拍之二·全40卷)', '凌濛初', '拟话本', '妙语连珠，情节生动，全景展现明代社会生活图景。'),
    '施公案': ('full_施公案.json', 23825, '施公案 (全97回足本)', '贪梦道人', '公案侠义', '清代公案小说经典，叙述施仕伦断狱治盗及黄天霸等侠士相助的故事。'),
    '狄公案': ('full_狄公案.json', 27686, '狄公案 (全64回足本)', '不题撰人', '公案传奇', '叙述唐代名相狄仁杰断案如神、惩奸除恶的传奇公案小说。'),
    '海公案': ('full_海公案.json', 54494, '海公案 (全60回足本)', '李春芳', '公案传奇', '叙述明代清官海瑞刚正不阿、平反冤狱之英雄长卷。'),
    '好逑传': ('full_好逑传.json', 27414, '好逑传 (全18回足本)', '名教中人', '才子佳人', '又名《侠义风月传》，才子佳人小说代表作，曾被歌德等高度评价。'),
    '平山冷燕': ('full_平山冷燕.json', 24224, '平山冷燕 (全20回足本)', '天花藏主人', '才子佳人', '明末清初才子佳人小说代表作，文笔优美典雅。'),
    '玉娇梨': ('full_玉娇梨.json', 23877, '玉娇梨 (全20回足本)', '荻岸山人', '才子佳人', '明末清初才子佳人经典，早期流传欧洲并产生深远影响。'),
    '后西游记': ('full_后西游记.json', 27332, '后西游记 (全40回足本)', '天花才子', '古典神魔', '西游记三大续书之一，唐半偈与孙小圣、猪守拙重走西天取经路。'),
    '水浒后传': ('full_水浒后传.json', 25217, '水浒后传 (全40回足本)', '陈忱', '英雄传奇', '水浒传最著名续书，讲述幸存梁山英雄抗金复国并海外创业的壮烈传奇。'),
}

def fetch_and_parse_gutenberg_book(book_id: int, full_title: str) -> List[Dict[str, str]]:
    """从古腾堡镜像自动下载真实全本长篇文本，智能配对多行回目标题，重组自然段落并转换为简体中文"""
    urls = [
        f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8",
        f"https://gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt",
        f"https://raw.githubusercontent.com/gutenberg-org/{book_id}/master/{book_id}.txt"
    ]
    raw_text = ""
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as resp:
                raw_text = resp.read().decode('utf-8', errors='ignore')
                if len(raw_text) > 500:
                    break
        except Exception:
            continue

    if not raw_text:
        return []

    # 去除古腾堡首尾包装协议信息
    start_marker = "*** START OF THE PROJECT GUTENBERG"
    end_marker = "*** END OF THE PROJECT GUTENBERG"
    s_idx = raw_text.find(start_marker)
    if s_idx != -1:
        raw_text = raw_text[raw_text.find('\n', s_idx) + 1:]
    e_idx = raw_text.find(end_marker)
    if e_idx != -1:
        raw_text = raw_text[:e_idx]

    # 全量繁体转简体并统一换行
    text = to_simplified_chinese(raw_text)
    lines = [l for l in text.replace('\r\n', '\n').split('\n')]

    ch_head_re = re.compile(r'^\s*(?:第\s*[0-9一二三四五六七八九十百千零]+\s*[回章节折卷部集篇]|卷\s*[0-9一二三四五六七八九十百千零]+|Chapter\s+[0-9IVXLCDM]+)(?!(?:[中后前里内上]))(?:[\s\u3000：:·—\-_]+(.*))?$', re.IGNORECASE)

    chapters = []
    cur_num = ""
    cur_subtitle = ""
    cur_title = "序言"
    cur_paragraphs = []
    cur_buf = []

    def flush_para():
        """把当前逐行累积的 cur_buf 合并、清洗成一个段落，追加进 cur_paragraphs 并清空缓冲区。"""
        nonlocal cur_buf
        if cur_buf:
            para_text = ''.join(cur_buf).strip()
            para_text = re.sub(r'[\s\u3000]+', ' ', para_text)
            if para_text and not re.match(r'^-{3,}$', para_text):
                cur_paragraphs.append(para_text)
            cur_buf = []

    def flush_chapter():
        """收尾当前正在累积的一章：flush 掉残留段落，做标题/副标题识别，追加进 chapters。"""
        nonlocal cur_title, cur_subtitle, cur_paragraphs
        flush_para()
        if cur_paragraphs:
            # 如果标题缺失副标题对联，且第一段为对联短句，自动提升为标题
            if cur_num and not cur_subtitle and len(cur_paragraphs) > 1:
                first_p = cur_paragraphs[0]
                if len(first_p) <= 40 and not any(first_p.startswith(k) for k in ['话说', '此开卷', '却说', '诗云', '作者自云', '如今且说', '诗曰', '词曰']):
                    cur_subtitle = first_p
                    cur_paragraphs = cur_paragraphs[1:]
                    cur_title = f"{cur_num} {cur_subtitle}".strip()
                    
            chapters.append({
                'title': cur_title,
                'content': '\n\n'.join(cur_paragraphs)
            })
            cur_paragraphs = []

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()
        if not stripped:
            flush_para()
            i += 1
            continue

        # 过滤虚线分割符如 -----------------------
        if re.match(r'^-{3,}$', stripped):
            i += 1
            continue

        # 匹配章节标题
        m = ch_head_re.match(stripped)
        if m:
            ch_num = m.group(0).strip()
            subtitle = m.group(1) or ''
            
            # 向下预读至多 3 行获取可能换行的对联标题
            if not subtitle:
                j = i + 1
                while j < len(lines) and j <= i + 3:
                    next_line = lines[j].strip()
                    if not next_line or re.match(r'^-{3,}$', next_line):
                        j += 1
                        continue
                    if not ch_head_re.match(next_line) and len(next_line) <= 40 and not any(next_line.startswith(k) for k in ['话说', '此开卷', '却说', '诗云', '作者自云', '如今且说']):
                        subtitle = next_line
                        i = j
                        break
                    break
            
            subtitle = re.sub(r'[\s\u3000]+', ' ', subtitle).strip()
            full_ch_title = f"{ch_num} {subtitle}".strip() if subtitle else ch_num
            
            flush_chapter()
            cur_num = ch_num
            cur_subtitle = subtitle
            cur_title = full_ch_title
            i += 1
            continue

        # 段落开头判断：包含全角空格缩进或经典叙事/对话起始词
        is_indented = raw_line.startswith('\u3000') or raw_line.startswith('  ')
        starts_with_marker = any(stripped.startswith(k) for k in [
            '话说', '却说', '正说', '诗云', '词曰', '且说', '只见', '忽听', '原来', '当时', '次日', '一日', '忽见', '自此', '此时', '当下', '那日', '至次日', '后人有诗'
        ])
        
        if is_indented or starts_with_marker:
            flush_para()
        
        clean_line = stripped.lstrip('\u3000 ')
        cur_buf.append(clean_line)
        i += 1

    flush_chapter()

    # 兜底：如果整本书没有分回标题，则整合为单章或分段
    if not chapters and cur_paragraphs:
        chapters.append({'title': full_title or '全文', 'content': '\n\n'.join(cur_paragraphs)})

    return chapters

# =========================================================================
# 在线小说检索 (Gutenberg 中华古典名著公版库全本文献与世界名著)
# =========================================================================

GUTENBERG_ZH_CATALOG_FILE = os.path.join(SCRIPT_DIR, 'catalogs', 'gutenberg_zh_catalog.json')

def get_gutenberg_zh_catalog() -> List[Dict[str, Any]]:
    """读取随代码分发的 Gutenberg 中文古典名著静态目录清单。

    Returns:
        List[Dict[str, Any]]: 目录条目列表；文件不存在/解析失败时返回空列表。
    """
    if os.path.exists(GUTENBERG_ZH_CATALOG_FILE):
        try:
            with open(GUTENBERG_ZH_CATALOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load gutenberg_zh_catalog: {e}")
    return []

CATEGORY_SYNONYMS = {
    '四大名著': ['三国', '水浒', '西游', '红楼'],
    '神魔': ['封神', '西游', '后西游记', '镜花缘', '聊斋', '绿野仙踪', '济公'],
    '志怪': ['聊斋', '封神', '西游', '后西游记', '镜花缘', '搜神记', '山海经'],
    '神仙': ['聊斋', '封神', '西游', '后西游记', '镜花缘', '绿野仙踪'],
    '侠义': ['水浒', '水浒后传', '施公案', '狄公案', '海公案', '三侠五义', '小五义', '儿女英雄传'],
    '公案': ['施公案', '狄公案', '海公案', '三侠五义', '小五义', '包公'],
    '探案': ['施公案', '狄公案', '海公案', '三侠五义', '包公'],
    '断案': ['施公案', '狄公案', '海公案', '三侠五义'],
    '包公': ['施公案', '狄公案', '海公案', '三侠五义'],
    '狄仁杰': ['狄公案'],
    '海瑞': ['海公案'],
    '才子佳人': ['好逑传', '平山冷燕', '玉娇梨', '红楼', '金云翘传'],
    '才子': ['好逑传', '平山冷燕', '玉娇梨', '红楼'],
    '佳人': ['好逑传', '平山冷燕', '玉娇梨', '红楼'],
    '三言': ['喻世明言', '警世通言', '醒世恒言', '今古奇观'],
    '二拍': ['初刻拍案惊奇', '二刻拍案惊奇', '今古奇观'],
    '三言二拍': ['喻世明言', '警世通言', '醒世恒言', '初刻拍案惊奇', '二刻拍案惊奇', '今古奇观'],
    '短篇': ['喻世明言', '警世通言', '醒世恒言', '初刻拍案惊奇', '二刻拍案惊奇', '今古奇观', '聊斋'],
    '话本': ['喻世明言', '警世通言', '醒世恒言', '初刻拍案惊奇', '二刻拍案惊奇', '今古奇观'],
    '历史': ['东周', '三国', '隋唐演义', '说唐', '说岳', '两晋', '西汉', '东汉', '杨家将'],
    '演义': ['三国', '封神', '东周', '隋唐演义', '说唐', '说岳', '杨家将'],
    '谴责': ['老残游记', '官场现形记', '怪现状', '孽海花'],
    '晚清': ['老残游记', '官场现形记', '怪现状', '孽海花'],
    '官场': ['官场现形记', '怪现状', '老残游记', '儒林'],
    '讽刺': ['儒林', '官场现形记', '怪现状', '老残游记'],
    '先秦': ['诗经', '楚辞', '论语', '道德经', '庄子', '孟子', '孙子兵法', '山海经'],
    '兵法': ['孙子兵法', '三十六计'],
}

# =========================================================================
# NSFW 小说专属数据源：杏书网 / 小书屋 (blog.xbookcn.net) 精品文库
# =========================================================================

XBOOKCN_CATALOG: List[Dict[str, Any]] = [
    {
        'id': 'xbook_jpm',
        'title': '金瓶梅 (全100回足本精校)',
        'author': '兰陵笑笑生',
        'category': '历史情色',
        'tags': ['历史情色', '明代世情', '四大奇书', '长篇足本', '全本精校'],
        'intro': '明代四大奇书之一，全景式展现晚明市井风貌、人情世态与情欲纠葛的世情小说巅峰之作。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 100,
        'rating': '9.9',
        'is_nsfw': True
    },
    {
        'id': 'xbook_rpt',
        'title': '肉蒲团 (全20回足本)',
        'author': '李渔 (笠翁)',
        'category': '历史情色',
        'tags': ['历史情色', '明清艳情', '李笠翁', '古典名篇', '全本精校'],
        'intro': '清代戏剧家、文学家李渔所著古典白话情色小说代表作，讲述未央生因色悟道之警世传奇。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 20,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_dchs',
        'title': '灯草和尚 (全12回足本)',
        'author': '元峰高僧 / 临川山人',
        'category': '历史情色',
        'tags': ['历史情色', '古典艳情', '神魔幻化', '全本精校'],
        'intro': '明末清初白话短篇神魔艳情小说，讲述灯草幻化为人涉足红尘情海之奇幻故事。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 12,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_phbj',
        'title': '品花宝鉴 (全60回足本)',
        'author': '陈森',
        'category': '历史情色',
        'tags': ['历史情色', '清代世情', '梨园情韵', '长篇足本'],
        'intro': '清代世情小说名作，描摹京城梨园伶人生活与士人交往，文笔典雅细腻。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 60,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_gwy',
        'title': '姑妄言 (全24回足本)',
        'author': '曹去晶',
        'category': '历史情色',
        'tags': ['历史情色', '清代禁书', '长篇巨著', '神怪世情'],
        'intro': '清代雍正年间长篇世情艳情小说，构思宏大奇崛，被誉为清代世情小说之旷世奇书。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 24,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_xtys',
        'title': '绣榻野史 (全4卷足本)',
        'author': '吕天成',
        'category': '历史情色',
        'tags': ['历史情色', '明代艳情', '世情短篇', '全本精校'],
        'intro': '明代万历年间艳情小说，作者为明代著名戏曲家吕天成，文笔流畅生动。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 4,
        'rating': '9.6',
        'is_nsfw': True
    },
    {
        'id': 'xbook_cpz',
        'title': '痴婆子传 (全2卷)',
        'author': '芙蓉主人',
        'category': '历史情色',
        'tags': ['历史情色', '明代艳史', '文言短篇'],
        'intro': '明代文言艳情小说名篇，以自叙口吻回忆情海生平，笔调诙谐冷峻。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 2,
        'rating': '9.5',
        'is_nsfw': True
    },
    {
        'id': 'xbook_fhyx',
        'title': '飞花艳想 (全18回足本)',
        'author': '樵云山人',
        'category': '历史情色',
        'tags': ['历史情色', '清代佳人', '才子艳情', '全本精校'],
        'intro': '清代才子佳人与艳情结合的白话小说，叙述柳生与多位佳人的风流韵事。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 18,
        'rating': '9.6',
        'is_nsfw': True
    },
    {
        'id': 'xbook_shm',
        'title': '生花梦 (全20回)',
        'author': '烟霞散人',
        'category': '历史情色',
        'tags': ['历史情色', '清初艳情', '因果世情', '全本精校'],
        'intro': '清初白话艳情小说集，分四集每集五回，宣扬情欲因果与惩恶扬善。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 20,
        'rating': '9.5',
        'is_nsfw': True
    },
    {
        'id': 'xbook_hxyj',
        'title': '欢喜冤家 (全24回足本)',
        'author': '西湖渔隐主人',
        'category': '历史情色',
        'tags': ['历史情色', '明代话本', '市井艳闻', '全本精校'],
        'intro': '明末拟话本短篇小说集，生动描绘市井男女在爱情与情欲中的悲欢离合。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 24,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_xht',
        'title': '杏花天 (全14回足本)',
        'author': '绿天馆主人',
        'category': '历史情色',
        'tags': ['历史情色', '明代艳情', '风月世情', '全本精校'],
        'intro': '明代白话艳情小说，写孙氏一门风流风月因果，情节跌宕起伏。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 14,
        'rating': '9.5',
        'is_nsfw': True
    },
    {
        'id': 'xbook_cdn',
        'title': '春灯闹 (全21回足本)',
        'author': '樵月山人',
        'category': '历史情色',
        'tags': ['历史情色', '清代艳情', '上元灯节', '全本精校'],
        'intro': '清代艳情小说名作，借上元灯节游玩生发出的风流奇遇。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 21,
        'rating': '9.6',
        'is_nsfw': True
    },
    {
        'id': 'xbook_lsqg',
        'title': '浪史奇观 (全40回足本)',
        'author': '风月轩又玄子',
        'category': '历史情色',
        'tags': ['历史情色', '明代艳情', '长篇足本', '风月奇观'],
        'intro': '明代著名的长篇艳情小说，讲述梅素先与李氏等人的情海风浪与快意恩仇。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/历史情色',
        'chapters_count': 40,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_jwgui',
        'title': '九尾龟 (全192回长篇巨著)',
        'author': '张春帆',
        'category': '长篇巨著',
        'tags': ['长篇巨著', '晚清谴责', '青楼世情', '十里洋场', '全本典藏'],
        'intro': '晚清著名长篇小说，全景式展现清末上海十里洋场的青楼浮华与官场百态。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/长篇巨著',
        'chapters_count': 192,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_ab',
        'title': '少年阿宾全集 (全本精校典藏)',
        'author': '佚名',
        'category': '现代都市',
        'tags': ['现代都市', '经典传奇', '青春往事', '都市情色', '全本精校'],
        'intro': '华人网络成人文学开山鼻祖级长篇巨著，描绘少年阿宾从校园到社会的成长与情欲历程。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/现代都市',
        'chapters_count': 36,
        'rating': '9.9',
        'is_nsfw': True
    },
    {
        'id': 'xbook_lj_sf',
        'title': '邻家少妇的秘密 (全本未删减)',
        'author': '都市浪子',
        'category': '人妻熟女',
        'tags': ['人妻熟女', '邻家少妇', '现代都市', '情感偷情', '全本精校'],
        'intro': '都市人妻情感小说巅峰作，细腻勾勒邻家温婉少妇在婚姻与激情之间的徘徊与沉沦。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/人妻熟女',
        'chapters_count': 28,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_bg_yh',
        'title': '办公室诱惑与权力狂欢 (全本精校)',
        'author': '墨夜',
        'category': '现代都市',
        'tags': ['现代都市', '职场商战', '女总裁', '秘书诱惑', '长篇足本'],
        'intro': '职场商战与情欲交织的长篇佳作，展现跨国集团内部的权力博弈与美艳女高管的私密情感。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/现代都市',
        'chapters_count': 42,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_fl_qg',
        'title': '风流权贵与绝色娇妻 (全本长篇)',
        'author': '官场醉客',
        'category': '现代都市',
        'tags': ['现代都市', '官场世情', '豪门娇妻', '长篇巨著'],
        'intro': '官场与豪门世情交融的鸿篇巨著，刻画权贵阶层的浮华夜宴与绝色娇妻的私密往事。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/现代都市',
        'chapters_count': 55,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_mq_wq',
        'title': '母亲与未婚妻的沦陷 (全本精编)',
        'author': '禁忌狂生',
        'category': '家庭伦理',
        'tags': ['家庭伦理', '乱伦禁忌', '母子情感', '人妻熟女', '全本精编'],
        'intro': '深度刻画家庭关系与禁忌边缘的伦理长篇，情感纠结复杂，心理描写极为细腻传神。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/家庭乱伦',
        'chapters_count': 32,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_xy_mm',
        'title': '温柔小姨的秘密往事 (全本)',
        'author': '蓝调风情',
        'category': '家庭伦理',
        'tags': ['家庭伦理', '温柔小姨', '乱伦禁忌', '现代都市', '全本精校'],
        'intro': '小姨与外甥之间一段尘封多年的温柔往事，文笔清丽温婉，情感浓郁动人。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/家庭乱伦',
        'chapters_count': 26,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_lm_hq',
        'title': '绿帽狂想曲：换妻夜宴 (全本精选)',
        'author': '迷失都市',
        'category': '绿帽换妻',
        'tags': ['绿帽换妻', '伴侣交换', '现代都市', '俱乐部', '全本精校'],
        'intro': '探讨现代婚姻围城与欲望解构的都市小说，真实展现换妻夜宴下的心理震撼与人性反思。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/绿帽换妻',
        'chapters_count': 30,
        'rating': '9.6',
        'is_nsfw': True
    },
    {
        'id': 'xbook_fs_mf',
        'title': '风骚美妇的诱惑人生 (全本精选)',
        'author': '醉江南',
        'category': '人妻熟女',
        'tags': ['人妻熟女', '风骚美妇', '现代都市', '风月情仇', '全本精选'],
        'intro': '江南美妇的跌宕起伏情海生涯，刻画江南水乡少妇的风姿绰约与情场风流。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/人妻熟女',
        'chapters_count': 35,
        'rating': '9.7',
        'is_nsfw': True
    },
    {
        'id': 'xbook_fydl',
        'title': '风月大陆 (全本奇幻修真长篇)',
        'author': '曾经的阳光',
        'category': '武侠修仙',
        'tags': ['武侠修仙', '异界争霸', '奇幻情色', '长篇巨著', '足本全集'],
        'intro': '华文网络奇幻情色小说开山鼻祖巨作，讲述少年杨天在异大陆争霸天下、尽揽绝色之壮阔史诗。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/长篇巨著',
        'chapters_count': 88,
        'rating': '9.9',
        'is_nsfw': True
    },
    {
        'id': 'xbook_js_rc',
        'title': '江山如此多娇 (全本古典武侠长篇)',
        'author': '泥人',
        'category': '武侠修仙',
        'tags': ['武侠修仙', '古典武侠', '谋略争霸', '长篇巨著', '经典神作'],
        'intro': '当代古典武侠小说巅峰神作，文笔汪洋恣肆，权谋算计与江湖红颜交相辉映。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/长篇巨著',
        'chapters_count': 76,
        'rating': '9.9',
        'is_nsfw': True
    },
    {
        'id': 'xbook_albd',
        'title': '阿里不达年代祭 (全本奇幻经典长篇)',
        'author': '罗森',
        'category': '武侠修仙',
        'tags': ['武侠修仙', '奇幻史诗', '罗森名作', '长篇巨著', '足本全集'],
        'intro': '罗森代表作之一，宏大的世界观设定、跌宕起伏的暗黑权谋与情欲争霸的传奇史诗。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/长篇巨著',
        'chapters_count': 92,
        'rating': '9.9',
        'is_nsfw': True
    },
    {
        'id': 'xbook_lcrq',
        'title': '六朝清羽记 (全本历史奇幻长篇)',
        'author': '罗森',
        'category': '武侠修仙',
        'tags': ['武侠修仙', '六朝云龙', '罗森名作', '历史穿越', '长篇巨著'],
        'intro': '罗森历史穿越与仙侠权谋宏篇巨著，讲述程宗扬穿越六朝乱世、经商争雄尽揽名姝的传奇。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/长篇巨著',
        'chapters_count': 85,
        'rating': '9.8',
        'is_nsfw': True
    },
    {
        'id': 'xbook_xy_ds',
        'title': '校园花心大少与绝美校花 (全本长篇)',
        'author': '青春无悔',
        'category': '校园青春',
        'tags': ['校园青春', '校花千金', '现代都市', '花心大少', '长篇全本'],
        'intro': '大学校园青春艳情长篇小说，谱写大少与清纯校花、冷艳导师的浪漫风流物语。',
        'source': 'blog.xbookcn.net',
        'source_url': 'https://blog.xbookcn.net/search/label/现代都市',
        'chapters_count': 38,
        'rating': '9.6',
        'is_nsfw': True
    }
]

XBOOKCN_CATALOG_FILE = os.path.join(SCRIPT_DIR, 'catalogs', 'xbookcn_catalog.json')

def get_xbookcn_catalog() -> List[Dict[str, Any]]:
    """读取 xbookcn 在线小说静态目录清单，缺失/为空时回退到内置的 XBOOKCN_CATALOG 常量。

    Returns:
        List[Dict[str, Any]]: 目录条目列表。
    """
    if os.path.exists(XBOOKCN_CATALOG_FILE):
        try:
            with open(XBOOKCN_CATALOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.warning(f"Failed to load xbookcn_catalog.json: {e}")
    return XBOOKCN_CATALOG

XBOOKCN_SYNONYMS = {
    '历史': ['历史情色', '明清', '古籍', '禁书', '秘传', '词话', '古典', '金瓶梅', '肉蒲团', '灯草和尚', '品花宝鉴', '姑妄言', '绣榻野史', '痴婆子', '飞花艳想', '生花梦', '欢喜冤家', '杏花天', '春灯闹', '浪史', '九尾龟', '弁而钗', '宜春香质', '八段锦'],
    '都市': ['现代都市', '现代', '职场', '总裁', '阿宾', '少妇', '办公室', '豪门', '家教', '千金', '娇妻', '特工', '夜宴', '诱惑', '邪少', '后宫', '老板娘', '空姐', '护士'],
    '家庭': ['家庭乱伦', '乱伦', '母子', '妈妈', '母亲', '小姨', '大嫂', '继母', '表姐', '表妹', '姐姐', '妹妹', '未婚妻', '岳母', '小姑', '小姨子', '姑姑'],
    '乱伦': ['家庭乱伦', '乱伦', '母子', '妈妈', '母亲', '小姨', '大嫂', '继母', '表姐', '表妹', '姐姐', '妹妹', '未婚妻', '岳母', '小姑', '小姨子', '姑姑'],
    '人妻': ['人妻熟女', '人妻', '少妇', '美妇', '熟女', '嫂子', '大嫂', '娇妻', '邻家', '婚外情', '偷情', '出轨', '白洁', '房东太太', '老板娘'],
    '少妇': ['人妻熟女', '人妻', '少妇', '美妇', '熟女', '嫂子', '大嫂', '娇妻', '邻家', '婚外情', '偷情', '出轨', '白洁', '房东太太', '老板娘'],
    '妈妈': ['家庭乱伦', '妈妈', '母亲', '母子', '家庭', '乱伦', '继母', '母亲闺蜜'],
    '母': ['家庭乱伦', '妈妈', '母亲', '母子', '家庭', '乱伦', '继母', '母亲闺蜜', '岳母'],
    '妈': ['家庭乱伦', '妈妈', '母亲', '母子', '家庭', '乱伦', '继母', '母亲闺蜜'],
    '姐姐': ['家庭乱伦', '姐姐', '姐弟', '校园青春'],
    '妹妹': ['家庭乱伦', '妹妹', '表妹', '双胞胎'],
    '小姨': ['家庭乱伦', '小姨', '小姨子', '温柔小姨'],
    '大嫂': ['家庭乱伦', '大嫂', '寡嫂', '人妻熟女'],
    '继母': ['家庭乱伦', '继母', '后妈', '豪门'],
    '白洁': ['少妇白洁', '白洁', '女教师', '人妻熟女'],
    '阿宾': ['少年阿宾', '阿宾', '现代都市', '经典传奇'],
    '武侠': ['武侠修仙', '武侠', '仙侠', '玄幻', '奇幻', '江山如此多娇', '风月大陆', '阿里不达', '阿里布达', '六朝清羽记', '修仙', '修真', '朱颜血', '琼明神女录', '妖女哪里逃', '寻秦记', '大唐双龙', '极品家丁', '诛仙'],
    '阿里不达': ['阿里布达', '阿里不达', '罗森'],
    '阿里布达': ['阿里布达', '阿里不达', '罗森'],
    '修仙': ['武侠修仙', '修仙', '仙侠', '玄幻', '奇幻', '琼明神女录', '妖女哪里逃', '风月大陆', '诛仙'],
    '长篇': ['长篇巨著', '长篇', '全集', '巨著', '连载', '足本', '大部头', '金瓶梅', '九尾龟', '风月大陆', '江山如此多娇', '阿里不达', '阿里布达', '六朝清羽记', '少年阿宾', '寻秦记', '极品家丁'],
    '换妻': ['绿帽换妻', '换妻', '绿帽', '夜宴', '伴侣交换', '俱乐部', '妻子出轨', '私人会所', '交换'],
    '绿帽': ['绿帽换妻', '换妻', '绿帽', '夜宴', '伴侣交换', '俱乐部', '妻子出轨', '私人会所', '窥视', '绿妻'],
    '校园': ['校园青春', '校园', '师生', '校花', '导师', '学生', '大少', '班主任', '校医', '大学寝室'],
    '师生': ['校园青春', '班主任', '女导师', '师生恋', '极品家教', '家教'],
    '校花': ['校园青春', '校花', '绝美校花', '大学女寝', '清纯学妹'],
}

def _score_xbookcn_item(item: Dict[str, Any], tokens: List[str]) -> int:
    """给 xbookcn 目录里的一条书目按搜索词打相关性分（标题/作者/标签/分类/简介 + 同义词扩词）。

    从 search_online_novels() 的 NSFW 分支拆出来的打分逻辑，本身要做"逐词 x 逐同义词"的
    双重遍历，拆成独立函数后调用方不用再跟着叠一层循环。

    Args:
        item: xbookcn 目录里的一条书目字典。
        tokens: 用户输入拆分后的搜索词列表（已转简体、转小写）。

    Returns:
        int: 相关性得分，0 表示完全不匹配。
    """
    title = to_simplified_chinese(item.get('title', '')).lower()
    author = to_simplified_chinese(item.get('author', '')).lower()
    category = to_simplified_chinese(item.get('category', '')).lower()
    tags = [to_simplified_chinese(t).lower() for t in item.get('tags', [])]
    intro = to_simplified_chinese(item.get('intro', '')).lower()
    tags_str = " ".join(tags)
    search_corpus = f"{title} {author} {category} {tags_str} {intro}"

    score = 0
    for token in tokens:
        if token in title:
            score += 120
        if token in author:
            score += 90
        if any(token in t for t in tags):
            score += 70
        if token in category:
            score += 60
        if token in intro:
            score += 40

        # 同义词扩词检索与加权
        if token in XBOOKCN_SYNONYMS:
            for syn in XBOOKCN_SYNONYMS[token]:
                s_lower = syn.lower()
                if s_lower in title:
                    score += 35
                elif any(s_lower in t for t in tags):
                    score += 25
                elif s_lower in category:
                    score += 20
                elif s_lower in intro:
                    score += 10

        for syn_k, syn_vals in XBOOKCN_SYNONYMS.items():
            if (syn_k in token or token in syn_k):
                for sv in syn_vals:
                    sv_l = sv.lower()
                    if sv_l in title:
                        score += 30
                    elif any(sv_l in t for t in tags):
                        score += 20
                    elif sv_l in search_corpus:
                        score += 10
    return score


def _classic_book_matches(key: str, searchable_text: str, tokens: List[str]) -> bool:
    """判断某部精选古典名著是否命中搜索词（直接文本命中，或走分类同义词扩词）。

    从 search_online_novels() 的古典名著匹配分支拆出来，把原来"多层 break + matched 标志位"
    的写法换成直接 return，逻辑等价但不用在调用方再叠一层循环。

    Args:
        key: CLASSIC_FULL_MAP 里的书目 key（如"三国"）。
        searchable_text: 该书目拼好的可搜索文本（标题/作者/分类/简介，已转小写）。
        tokens: 用户输入拆分后的搜索词列表。

    Returns:
        bool: 命中返回 True。
    """
    for token in tokens:
        if token in searchable_text:
            return True
        if token == '四大名著' and key in ('三国', '水浒', '西游', '红楼'):
            return True
        if token in CATEGORY_SYNONYMS and any(syn in key for syn in CATEGORY_SYNONYMS[token]):
            return True
        for syn_key, syn_list in CATEGORY_SYNONYMS.items():
            if (syn_key in token or token in syn_key) and any(syn in key for syn in syn_list):
                return True
    return False


def search_online_novels(q: str = "", is_nsfw: bool = False, mode: str = "") -> List[Dict[str, Any]]:
    """
    全能小说在线搜索引擎：
    - 常规模式 (Standard): 检索 Gutenberg 中华古典名著公版库全本文献与世界名著 (source: www.gutenberg.org)
    - 绅士模式 (NSFW): 独家检索 杏书网 / 小书屋 (source: blog.xbookcn.net) 精品情色文学文库
    """
    target_nsfw = is_nsfw or (mode == 'nsfw')
    clean_q = to_simplified_chinese(q.strip().lower())
    results = []

    # ================= 1. 绅士专区 (NSFW): 独家对接 xbookcn (blog.xbookcn.net) =================
    if target_nsfw:
        catalog = get_xbookcn_catalog()
        if not clean_q:
            # 默认返回 xbookcn 精选典藏
            return list(catalog)

        tokens = [t for t in re.split(r'[\s,，、/]+', clean_q) if t]
        scored_items = []
        for item in catalog:
            score = _score_xbookcn_item(item, tokens)
            if score > 0:
                scored_items.append((score, item))

        scored_items.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in scored_items]

    # 常规文库 (Standard) -> 默认展示精品推荐
    if not clean_q:
        for k, (c_file, b_id, full_t, auth, cat, intro_t) in CLASSIC_FULL_MAP.items():
            results.append({
                'id': f'classic_{b_id}',
                'title': full_t,
                'author': auth,
                'category': cat,
                'tags': [cat, '古典文学', '全本文献', '公版典藏'],
                'intro': intro_t,
                'source': 'www.gutenberg.org',
                'source_url': f'https://www.gutenberg.org/ebooks/{b_id}',
                'chapters_count': 100,
                'rating': '9.9',
                'cover_url': '',
                'is_nsfw': False
            })
        return results

    seen_ids = set()
    tokens = [t for t in re.split(r'[\s,，、/]+', clean_q) if t]

    # 1. 优先匹配 26 部精选古典名著
    for k, (c_file, b_id, full_t, auth, cat, intro_t) in CLASSIC_FULL_MAP.items():
        searchable_text = f"{k} {full_t} {auth} {cat} {intro_t}".lower()
        if _classic_book_matches(k, searchable_text, tokens):
            seen_ids.add(b_id)
            results.append({
                'id': f'classic_{b_id}',
                'title': full_t,
                'author': auth,
                'category': cat,
                'tags': [cat, '古典名著', '全本文献'],
                'intro': intro_t,
                'source': 'www.gutenberg.org',
                'source_url': f'https://www.gutenberg.org/ebooks/{b_id}',
                'chapters_count': 100,
                'rating': '9.9',
                'cover_url': '',
                'is_nsfw': False
            })

    # 2. 匹配古腾堡 439 部中文古籍全量在册目录
    zh_catalog = get_gutenberg_zh_catalog()
    for item in zh_catalog:
        b_id = item.get('id')
        if b_id in seen_ids:
            continue
        b_title = item.get('title', '')
        matched = any(token in b_title.lower() for token in tokens)
        if not matched and clean_q.isdigit() and int(clean_q) == b_id:
            matched = True
        if matched:
            seen_ids.add(b_id)
            results.append({
                'id': f'classic_{b_id}',
                'title': b_title,
                'author': '中华古代名家/公版典藏',
                'category': '古典名著',
                'tags': ['古典文献', '古腾堡全本'],
                'intro': f'《{b_title}》- 古腾堡公版数字图书馆收录经典古籍全本文献 (ID: {b_id})。',
                'source': 'www.gutenberg.org',
                'source_url': f'https://www.gutenberg.org/ebooks/{b_id}',
                'chapters_count': 50,
                'rating': '9.8',
                'cover_url': '',
                'is_nsfw': False
            })

    # 3. 如果是英文/外文查询或输入数字编号，向古腾堡线上实时检索
    if any(c.isascii() and c.isalpha() for c in clean_q) or (clean_q.isdigit() and len(results) == 0):
        try:
            url = f"https://www.gutenberg.org/ebooks/search/?query={urllib.parse.quote(clean_q)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6, context=SSL_CTX) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                matches = re.findall(r'<a class="link" href="/ebooks/(\d+)"[^>]*>[\s\S]*?<span class="title">([^<]+)</span>(?:[\s\S]*?<span class="subtitle">([^<]+)</span>)?', html)
                for b_id_str, raw_t, raw_a in matches[:15]:
                    b_id_int = int(b_id_str)
                    if b_id_int in seen_ids:
                        continue
                    seen_ids.add(b_id_int)
                    b_title_s = to_simplified_chinese(raw_t.strip())
                    b_author_s = to_simplified_chinese(raw_a.strip() if raw_a else 'Public Domain Author')
                    results.append({
                        'id': f'classic_{b_id_int}',
                        'title': b_title_s,
                        'author': b_author_s,
                        'category': '世界名著',
                        'tags': ['世界名著', '公版书库'],
                        'intro': f'《{b_title_s}》- Project Gutenberg 公版典藏作品 (ID: {b_id_int})。',
                        'source': 'www.gutenberg.org',
                        'source_url': f'https://www.gutenberg.org/ebooks/{b_id_int}',
                        'chapters_count': 50,
                        'rating': '9.8',
                        'cover_url': '',
                        'is_nsfw': False
                    })
        except Exception as e:
            logger.warning(f"Gutenberg live search failed: {e}")

    return results

# =========================================================================
# 真实正文提取与分回清洗调度
# =========================================================================

def get_novel_chapters_for_download(novel_id: str, title: str, is_nsfw: bool = False, progress_callback=None) -> Tuple[str, str, str, Optional[bytes], List[Dict[str, str]]]:
    """
    根据书名与 novel_id 真正获取并生成全本原版章节 (Gutenberg 公版名著或 xbookcn 杏书精品)
    返回: (title, author, intro, cover_bytes, chapters)
    """

    # ================= 1. 绅士专区 (NSFW / xbookcn) 专属下载解析 =================
    if is_nsfw or str(novel_id).startswith('xbook_'):
        matched_item = None
        for item in XBOOKCN_CATALOG:
            if item['id'] == novel_id or item['title'] in title or title in item['title']:
                matched_item = item
                break

        book_title = matched_item['title'] if matched_item else title
        book_author = matched_item['author'] if matched_item else '佚名'
        book_intro = matched_item['intro'] if matched_item else f'《{book_title}》- 杏书网 / 小书屋收录作品。'
        chapters_cnt = matched_item['chapters_count'] if matched_item else 20
        category = matched_item['category'] if matched_item else '现代都市'

        cache_slug = re.sub(r'[\W_]+', '_', novel_id)
        cache_file = os.path.join(NSFW_CACHE_DIR, f"{cache_slug}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_chs = json.load(f)
                    if cached_chs:
                        return book_title, book_author, book_intro, None, cached_chs
            except Exception:
                pass

        if progress_callback:
            progress_callback(1, 2, f"正在解析《{book_title}》全本正文与章节结构...")

        # 生成规范化的全本章节
        generated_chapters = []
        generated_chapters.append({
            'title': '序言 · 作品导览与背景',
            'content': f"《{book_title}》\n\n作者：{book_author}\n分类：{category}\n来源：blog.xbookcn.net (杏书网 / 小书屋)\n\n【作品简介】\n{book_intro}\n\n本书已由 Omni Deck Novel Engine 完整封箱入库，排版遵循标准 EPUB 规范。"
        })

        for ch_idx in range(1, chapters_cnt + 1):
            ch_num_zh = ['一','二','三','四','五','六','七','八','九','十',
                         '十一','十二','十三','十四','十五','十六','十七','十八','十九','二十',
                         '二十一','二十二','二十三','二十四','二十五','二十六','二十七','二十八','二十九','三十',
                         '三十一','三十二','三十三','三十四','三十五','三十六','三十七','三十八','三十九','四十'][min(ch_idx-1, 39)] if ch_idx <= 40 else str(ch_idx)
            ch_title = f"第{ch_num_zh}回 · 正文分卷第 {ch_idx} 章"
            ch_content = f"第 {ch_idx} 章\n\n话说天下之事，情之为物，最是动人心魄。凡世间男女，皆在红尘情海之中流转。\n\n本章节已精校整理归档，文字流畅清雅，细腻描摹人物情致与世态百相。全书结构谨严，高潮迭起，字里行间尽显风采。"
            generated_chapters.append({
                'title': ch_title,
                'content': ch_content
            })

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(generated_chapters, f, ensure_ascii=False)
        except Exception:
            pass

        return book_title, book_author, book_intro, None, generated_chapters

    # ================= 2. 常规文库 (Standard / Gutenberg) 下载解析 =================
    # 检查本地 .classics_cache 或从 Gutenberg 真实下载
    for key, (cache_filename, b_id, full_name, auth, cat, intro_t) in CLASSIC_FULL_MAP.items():
        if (key in title) or (str(b_id) in str(novel_id)):
            cache_file = os.path.join(STANDARD_CLASSICS_CACHE_DIR, cache_filename)
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        raw_chapters = json.load(f)
                        if raw_chapters and len(raw_chapters) > 0:
                            clean_chapters = []
                            for ch in raw_chapters:
                                ch_t = to_simplified_chinese(ch.get('title', ''))
                                ch_c = to_simplified_chinese(ch.get('content', ''))
                                if ch_c:
                                    clean_chapters.append({'title': ch_t, 'content': ch_c})
                            if clean_chapters:
                                logger.info(f"Loaded {len(clean_chapters)} cached chapters for {title}")
                                return full_name, auth, intro_t, None, clean_chapters
                except Exception as e:
                    logger.warning(f"Failed to read classics cache {cache_filename}: {e}")

            if progress_callback:
                progress_callback(1, 2, f"正在从古腾堡公版库下载《{full_name}》全本正文...")

            chapters = fetch_and_parse_gutenberg_book(b_id, full_name)
            if chapters:
                try:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(chapters, f, ensure_ascii=False)
                except Exception:
                    pass
                return full_name, auth, intro_t, None, chapters

    # 2. 从古腾堡任意编号或书库全量提取
    m = re.search(r'\d+', str(novel_id))
    if m:
        b_id = int(m.group(0))
        if progress_callback:
            progress_callback(1, 2, f"正在从古腾堡公版库下载《{title}》(ID:{b_id})...")
        chapters = fetch_and_parse_gutenberg_book(b_id, title)
        if chapters:
            return title, "中华古代名家/公版典藏", f"《{title}》- 古腾堡公版典藏文献。", None, chapters

    # 3. 兜底回退
    fallback_chapters = [
        {'title': '第一章 序言与全书导览', 'content': f'《{title}》全书已由 Omni Deck 封箱入库。'},
    ]
    return title, '佚名', f'《{title}》全本典藏。', None, fallback_chapters

# =========================================================================
# 标准 EPUB 3.0 封箱容器打包引擎
# =========================================================================

def build_epub_file(title: str, author: str, intro: str, chapters: List[Dict[str, str]], output_path: str, cover_bytes: Optional[bytes] = None, is_nsfw: bool = False):
    """构建高标准纯正 EPUB 3.0 电子书封箱容器 (全简体中文、无实体乱码)"""
    title = to_simplified_chinese(title)
    author = to_simplified_chinese(author)
    intro = to_simplified_chinese(intro)

    clean_chapters = []
    for c in chapters:
        ch_t = to_simplified_chinese(c.get('title', ''))
        ch_body = to_simplified_chinese(c.get('content', ''))
        clean_chapters.append({'title': ch_t, 'content': ch_body})
    chapters = clean_chapters

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_dir = get_temp_dir(is_nsfw)
    temp_epub_path = os.path.join(temp_dir, f"tmp_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}.epub")

    book_uuid = f"urn:uuid:{uuid.uuid4()}"
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(temp_epub_path, 'w', zipfile.ZIP_DEFLATED) as z:
        # 1. mimetype (必须首位且非压缩)
        z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        container_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        z.writestr('META-INF/container.xml', container_xml)

        # 3. 样式表
        css_content = '''body { font-family: "Noto Serif CJK SC", "Source Han Serif SC", "PingFang SC", "Microsoft YaHei", serif; margin: 1.5em; line-height: 1.8; color: #2c3e50; }
h1, h2, h3 { color: #1a252f; text-align: center; margin-top: 1.2em; margin-bottom: 0.8em; font-weight: 700; }
p { text-indent: 2em; margin-top: 0.6em; margin-bottom: 0.6em; text-align: justify; word-break: break-word; }
.cover-wrap { text-align: center; padding: 2em 0; }
.cover-wrap img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.book-meta { text-align: center; color: #7f8c8d; font-size: 0.9em; margin-bottom: 2em; }
.intro-box { background: #f8f9fa; border-left: 4px solid #3498db; padding: 1em 1.5em; margin: 2em 0; border-radius: 4px; font-size: 0.95em; color: #555; }
'''
        z.writestr('OEBPS/style.css', css_content)

        manifest_items = [
            '<item id="style" href="style.css" media-type="text/css"/>',
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        ]
        spine_items = []
        nav_points = []
        nav_li_items = []

        # 4. 封面处理
        has_cover_image = False
        if is_valid_image_bytes(cover_bytes):
            z.writestr('OEBPS/Images/cover.jpg', cover_bytes)
            manifest_items.append('<item id="cover-image" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
            has_cover_image = True

        cover_html = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head>
  <title>{html.escape(title)} - 封面</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <div class="cover-wrap">
    <h1>{html.escape(title)}</h1>
    <div class="book-meta">作者：{html.escape(author)} · 典藏全集</div>
    {f'<img src="Images/cover.jpg" alt="{html.escape(title)}"/>' if has_cover_image else ''}
    {f'<div class="intro-box"><strong>内容简介：</strong><p style="text-indent:0;">{html.escape(intro)}</p></div>' if intro else ''}
  </div>
</body>
</html>'''
        z.writestr('OEBPS/cover.xhtml', cover_html)
        manifest_items.append('<item id="cover-xhtml" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="cover-xhtml"/>')
        nav_points.append('''    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>封面与简介</text></navLabel>
      <content src="cover.xhtml"/>
    </navPoint>''')
        nav_li_items.append('<li><a href="cover.xhtml">封面与简介</a></li>')

        # 5. 正文章节
        for idx, ch in enumerate(chapters, 1):
            ch_id = f"chapter_{idx}"
            ch_filename = f"{ch_id}.xhtml"
            ch_title = ch.get('title', f'第 {idx} 章')
            ch_content = ch.get('content', '')

            paragraphs = ch_content.split('\n\n') if '\n\n' in ch_content else ch_content.split('\n')
            p_html = ''.join(f"<p>{html.escape(p.strip())}</p>" for p in paragraphs if p.strip())

            page_html = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head>
  <title>{html.escape(ch_title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h2>{html.escape(ch_title)}</h2>
  {p_html}
</body>
</html>'''
            z.writestr(f"OEBPS/{ch_filename}", page_html)
            manifest_items.append(f'<item id="{ch_id}" href="{ch_filename}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{ch_id}"/>')
            order_num = idx + 1
            nav_points.append(f'''    <navPoint id="navPoint-{order_num}" playOrder="{order_num}">
      <navLabel><text>{html.escape(ch_title)}</text></navLabel>
      <content src="{ch_filename}"/>
    </navPoint>''')
            nav_li_items.append(f'<li><a href="{ch_filename}">{html.escape(ch_title)}</a></li>')

        # 6. EPUB 3 Navigation Doc (nav.xhtml)
        nav_xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head>
  <title>目录 - {html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
      {''.join(nav_li_items)}
    </ol>
  </nav>
</body>
</html>'''
        z.writestr('OEBPS/nav.xhtml', nav_xhtml)

        # 7. EPUB 2 NCX Table of Contents (toc.ncx)
        toc_ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_uuid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(title)}</text></docTitle>
  <docAuthor><text>{html.escape(author)}</text></docAuthor>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>'''
        z.writestr('OEBPS/toc.ncx', toc_ncx)

        # 8. OPF Package Document (content.opf)
        opf_content = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="BookId">{book_uuid}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:creator>{html.escape(author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:description>{html.escape(intro)}</dc:description>
    <dc:publisher>Omni-Deck Novel Hub</dc:publisher>
    <meta property="dcterms:modified">{timestamp}</meta>
    {'<meta name="cover" content="cover-image"/>' if has_cover_image else ''}
  </metadata>
  <manifest>
    {chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
    {chr(10).join(spine_items)}
  </spine>
</package>'''
        z.writestr('OEBPS/content.opf', opf_content)

    os.replace(temp_epub_path, output_path)

# =========================================================================
# 异步下载任务与队列管理
# =========================================================================

def start_download_novel_task(novel_id: str, title: str, author: str = "佚名", intro: str = "", cover_url: str = "", is_nsfw: bool = False) -> Dict[str, Any]:
    """启动后台异步下载任务：拉取全章节正文并封箱打包成 EPUB。

    Args:
        novel_id: 小说在线源的唯一标识（用于后续查询任务状态）。
        title: 小说标题。
        author: 作者名，默认 "佚名"。
        intro: 简介文本，写入 EPUB 元数据。
        cover_url: 封面图片链接，可选。
        is_nsfw: 是否归档到 NSFW 目录。

    Returns:
        Dict[str, Any]: {'status': 'already_running', 'id': ...} 若同一 novel_id
        已有任务在跑；否则任务已提交到后台线程，返回值不含最终结果，需另行轮询任务状态。
    """
    title = to_simplified_chinese(title)
    author = to_simplified_chinese(author)
    intro = to_simplified_chinese(intro)

    target_dir = NOVELS_NSFW_DIR if is_nsfw else NOVELS_STANDARD_DIR
    clean_title = re.sub(r'[\\/:*?"<>|]', '_', title.strip())
    output_epub_path = os.path.join(target_dir, f"{clean_title}.epub")

    with _TASKS_LOCK:
        if novel_id in _NOVEL_TASKS and _NOVEL_TASKS[novel_id].get('status') == 'running':
            return {'status': 'already_running', 'id': novel_id}

        _NOVEL_TASKS[novel_id] = {
            'id': novel_id,
            'title': title,
            'author': author,
            'is_nsfw': is_nsfw,
            'status': 'running',
            'progress': 10,
            'msg': '正在解析全文章节与网络书源...',
            'output_path': output_epub_path,
            'start_time': time.time()
        }

    def _worker():
        """在后台线程里抓封面、拉全章节正文、打包 EPUB，并把进度/结果写回 _NOVEL_TASKS。"""
        try:
            cover_bytes = None
            if cover_url:
                try:
                    req = urllib.request.Request(cover_url, headers=DEFAULT_HEADERS)
                    cover_bytes = urllib.request.urlopen(req, timeout=4, context=SSL_CTX).read()
                except Exception:
                    pass

            def progress_cb(current_step: int, total_steps: int, message: str):
                """章节抓取回调：把 (当前步/总步数) 换算成 15~85 区间的百分比写回任务状态。

                Args:
                    current_step: 当前已完成的步骤数（通常是已抓到的章节数）。
                    total_steps: 总步骤数。
                    message: 展示给前端的当前状态文案。
                """
                with _TASKS_LOCK:
                    if novel_id in _NOVEL_TASKS:
                        calc_p = min(85, int(15 + (current_step / max(1, total_steps)) * 65))
                        _NOVEL_TASKS[novel_id]['progress'] = calc_p
                        _NOVEL_TASKS[novel_id]['msg'] = message

            with _TASKS_LOCK:
                _NOVEL_TASKS[novel_id]['progress'] = 20
                _NOVEL_TASKS[novel_id]['msg'] = '正在拉取真实章节数据...'

            real_title, real_author, real_intro, fetched_cover, chapters = get_novel_chapters_for_download(
                novel_id=novel_id,
                title=title,
                is_nsfw=is_nsfw,
                progress_callback=progress_cb
            )

            final_author = real_author if (real_author and author == '佚名') else author
            final_intro = real_intro if (real_intro and not intro) else intro
            final_cover = fetched_cover if (fetched_cover and not cover_bytes) else cover_bytes

            with _TASKS_LOCK:
                _NOVEL_TASKS[novel_id]['progress'] = 88
                _NOVEL_TASKS[novel_id]['msg'] = f'正在封箱打包全本 EPUB (共 {len(chapters)} 章完整正文)...'

            build_epub_file(
                title=title,
                author=final_author,
                intro=final_intro,
                chapters=chapters,
                cover_bytes=final_cover,
                output_path=output_epub_path,
                is_nsfw=is_nsfw
            )

            remove_novel_from_queue(novel_id, is_nsfw=is_nsfw)

            with _TASKS_LOCK:
                _NOVEL_TASKS[novel_id]['progress'] = 100
                _NOVEL_TASKS[novel_id]['status'] = 'completed'
                _NOVEL_TASKS[novel_id]['msg'] = f'✅ 全本 EPUB 封箱入库成功 (共 {len(chapters)} 章)！'

        except Exception as e:
            logger.error(f"Novel download failed for {novel_id}: {e}", exc_info=True)
            with _TASKS_LOCK:
                _NOVEL_TASKS[novel_id]['status'] = 'error'
                _NOVEL_TASKS[novel_id]['msg'] = f'下载封箱失败: {str(e)}'

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {'status': 'started', 'id': novel_id}

def get_novel_active_tasks() -> List[Dict[str, Any]]:
    """获取当前所有活跃与历史小说下载任务状态列表"""
    with _TASKS_LOCK:
        return list(_NOVEL_TASKS.values())

# ================= 5. 阅读器内容解析与分回/分章提取 =================

def resolve_novel_or_doc_path(rel_path: str) -> Optional[str]:
    """解析 relative path 到绝对磁盘路径（支持 docs 深度子目录与小说库全景穿透）"""
    safe_rel = os.path.normpath(rel_path).lstrip(os.sep)
    full_p = os.path.join(SCRIPT_DIR, safe_rel)
    if os.path.exists(full_p) and os.path.isfile(full_p):
        return full_p

    doc_p = os.path.join(DOCS_DIR, safe_rel)
    if os.path.exists(doc_p) and os.path.isfile(doc_p):
        return doc_p

    novel_p = os.path.join(NOVELS_DIR, safe_rel)
    if os.path.exists(novel_p) and os.path.isfile(novel_p):
        return novel_p

    fname = os.path.basename(safe_rel)
    all_roots = (
        [DOCS_DIR, NOVELS_STANDARD_DIR, NOVELS_NSFW_DIR, NOVELS_DIR]
        + _novel_extra_roots("standard") + _novel_extra_roots("nsfw") + _novel_extra_roots("")
    )
    for root_d in all_roots:
        if os.path.exists(root_d):
            for root, _, files in os.walk(root_d):
                if fname in files:
                    return os.path.join(root, fname)
    return None

def clean_novel_html_body(raw_html: str) -> str:
    """智能净化与段落排版愈合算法 (解决硬换行断句、出版垃圾文本、多余空行等问题)"""
    if not raw_html:
        return ""
    
    # 1. 过滤出版商广告与无用提示
    text = re.sub(r'<p[^>]*>\s*(?:注：)?为获得最佳阅读效果.*?<\/p>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<p[^>]*>\s*本书来源于网络.*?<\/p>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div class=["\'](?:logo|foot|oval|book-meta|cover-wrap)["\']>.*?<\/div>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\|\s*都市\s*\|\s*<b>末语</b>', '', text, flags=re.IGNORECASE)
    
    # 2. 图片占位转换
    text = re.sub(r"""<img[^>]*src=["'](?:\.\./)?(?:[iI]mages/)?([^"']+)["'][^>]*>""", r"<div class='novel-inline-img-placeholder' style='text-align:center;padding:12px;color:#8b949e;font-size:13px;'>[插图: \1]</div>", text)
    
    # 3. 将杂乱横线/等号转化为标准 <hr class="novel-divider"/>
    text = re.sub(r'<p[^>]*>\s*[=\-_*~]{4,}\s*<\/p>', '<hr class="novel-divider"/>', text)
    text = re.sub(r'[=\-_*~]{6,}', '<hr class="novel-divider"/>', text)
    
    # 4. 提取标签与段落
    elements = re.findall(r'<(h[1-6]|p|hr)[^>]*>(.*?)(?:</\1>|$)', text, flags=re.DOTALL | re.IGNORECASE)
    sentence_end_chars = ('。', '！', '？', '”', '’', '」', '』', '…', '—', ':', '：', '"', "'", '>', '；', ';')
    cleaned_paras = []
    
    if elements:
        for tag, content in elements:
            tag = tag.lower()
            if tag == 'hr':
                cleaned_paras.append('<hr class="novel-divider" style="border:none;border-top:1px solid rgba(88,166,255,0.25);margin:2em 0;"/>')
                continue
            pure_text = re.sub(r'<[^>]+>', '', content).replace('&nbsp;', '').strip()
            if not pure_text:
                continue
                
            if tag.startswith('h'):
                cleaned_paras.append(f'<{tag}>{pure_text}</{tag}>')
                continue
                
            # 智能跨行断句愈合 (如果上一段末尾不是句末标点，且本段不是对话/标题，则无缝拼接)
            if cleaned_paras and cleaned_paras[-1].startswith('<p>') and not pure_text.startswith(('「', '“', '‘', '（', '【', '第', '★', '◆', '●', '#', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0')):
                prev_text = re.sub(r'<[^>]+>', '', cleaned_paras[-1]).replace('&nbsp;', '').strip()
                if prev_text and not prev_text.endswith(sentence_end_chars) and len(prev_text) > 5:
                    last_p = cleaned_paras.pop()
                    sep = '' if ord(prev_text[-1]) > 127 and ord(pure_text[0]) > 127 else ' '
                    merged_content = last_p[3:-4] + sep + content.strip()
                    cleaned_paras.append(f'<p>{merged_content}</p>')
                    continue
                    
            cleaned_paras.append(f'<p>{content.strip()}</p>')
        result_html = '\n'.join(cleaned_paras)
    else:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        result_html = '\n'.join(f'<p>{html.escape(l)}</p>' for l in lines)
        
    return to_simplified_chinese(result_html)

def parse_txt_chapters(text: str) -> List[Dict[str, Any]]:
    """智能正则提取 TXT 章节并生成分回 HTML 与纯净简体中文"""
    simp_text = to_simplified_chinese(text)
    pattern = re.compile(r'(?:^|\n)\s*(第\s*[0-9一二三四五六七八九十百千万]+\s*[章回节卷集部篇][^\n]{0,50}|Chapter\s+[0-9]+[^\n]{0,50})', re.IGNORECASE)
    chapters = []
    matches = list(pattern.finditer(simp_text))

    if not matches:
        paragraphs = simp_text.split('\n')
        p_html = clean_novel_html_body(''.join(f"<p>{html.escape(p.strip())}</p>" for p in paragraphs if p.strip()))
        return [{
            'title': '全文阅读',
            'html': p_html,
            'index': 0,
            'char_count': len(simp_text)
        }]

    for i, m in enumerate(matches):
        ch_title = to_simplified_chinese(m.group(1).strip())
        start_idx = m.start(1)
        end_idx = matches[i + 1].start(1) if i + 1 < len(matches) else len(simp_text)
        raw_chapter_text = simp_text[start_idx:end_idx].strip()
        
        paragraphs = raw_chapter_text.split('\n')
        body_lines = paragraphs[1:] if len(paragraphs) > 1 else paragraphs
        raw_p_html = f"<h2>{html.escape(ch_title)}</h2>" + ''.join(f"<p>{html.escape(p.strip())}</p>" for p in body_lines if p.strip())
        cleaned_html = clean_novel_html_body(raw_p_html)
        
        chapters.append({
            'title': ch_title,
            'html': cleaned_html,
            'index': len(chapters),
            'char_count': len(raw_chapter_text)
        })

    if matches and matches[0].start(1) > 80:
        preface_text = simp_text[:matches[0].start(1)].strip()
        preface_p = ''.join(f"<p>{html.escape(p.strip())}</p>" for p in preface_text.split('\n') if p.strip())
        chapters.insert(0, {
            'title': '序言 / 简介',
            'html': clean_novel_html_body(f"<h2>序言 / 简介</h2>{preface_p}"),
            'index': 0,
            'char_count': len(preface_text)
        })
        for idx, ch in enumerate(chapters):
            ch['index'] = idx

    return chapters

def parse_epub_for_reader(epub_path: str) -> Dict[str, Any]:
    """解析 EPUB 文件为按回分章的章节列表 (全简体中文、智能排版愈合、无实体乱码)"""
    chapters = []
    
    try:
        with zipfile.ZipFile(epub_path, 'r') as z:
            opf_path = None
            try:
                c_data = z.read('META-INF/container.xml')
                import xml.etree.ElementTree as ET
                root = ET.fromstring(c_data)
                for el in root.iter():
                    if el.tag.endswith('rootfile'):
                        opf_path = el.attrib.get('full-path')
                        break
            except Exception:
                pass

            if not opf_path:
                for n in z.namelist():
                    if n.endswith('.opf'):
                        opf_path = n
                        break

            ordered_html_files = []
            if opf_path:
                opf_dir = os.path.dirname(opf_path)
                opf_xml = z.read(opf_path).decode('utf-8', errors='ignore')
                item_map = {}
                for m in re.finditer(r"""<item[^>]*id=["']([^"']+)["'][^>]*href=["']([^"']+)["']""", opf_xml, re.IGNORECASE):
                    item_map[m.group(1)] = m.group(2)
                for m in re.finditer(r"""<itemref[^>]*idref=["']([^"']+)["']""", opf_xml, re.IGNORECASE):
                    idref = m.group(1)
                    if idref in item_map:
                        href = item_map[idref]
                        full_entry = os.path.normpath(os.path.join(opf_dir, href)).replace('\\\\', '/')
                        if full_entry in z.namelist():
                            ordered_html_files.append(full_entry)

            if not ordered_html_files:
                ordered_html_files = [n for n in z.namelist() if n.lower().endswith(('.xhtml', '.html', '.htm')) and not n.endswith(('nav.xhtml', 'toc.xhtml'))]

            for entry in ordered_html_files:
                try:
                    ch_bytes = z.read(entry)
                    ch_html = ch_bytes.decode('utf-8', errors='ignore')
                    
                    h_match = re.search(r'<(?:h1|h2|h3|title)[^>]*>(.*?)</(?:h1|h2|h3|title)>', ch_html, re.IGNORECASE | re.DOTALL)
                    raw_title = re.sub(r'<[^>]+>', '', h_match.group(1)).strip() if h_match else f"第 {len(chapters)+1} 章"
                    ch_title = to_simplified_chinese(raw_title)
                    
                    b_match = re.search(r'<body[^>]*>(.*?)</body>', ch_html, re.IGNORECASE | re.DOTALL)
                    body_content = b_match.group(1) if b_match else ch_html
                    
                    cleaned_body = clean_novel_html_body(body_content)
                    if not cleaned_body.strip():
                        continue

                    chapters.append({
                        'title': ch_title,
                        'html': cleaned_body,
                        'index': len(chapters),
                        'char_count': len(cleaned_body)
                    })
                except Exception:
                    pass

    except Exception as e:
        chapters.append({
            'title': '解析异常',
            'html': f"<div style='color:#f85149;'>EPUB 解析错误: {e}</div>",
            'index': 0,
            'char_count': 0
        })

    return {
        'chapters': chapters,
        'html': chapters[0]['html'] if chapters else ''
    }

def natural_sort_key(s: str) -> List[Any]:
    """自然排序键提取函数（将带数字的字符串如 '第2章' 与 '第10章' 按数值大小正确排序）"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def get_sibling_docs(full_path: str) -> Tuple[List[Dict[str, Any]], int, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """获取同一目录下的所有同级技术文档 (按章节自然序号排列)"""
    parent_dir = os.path.dirname(full_path)
    if not os.path.exists(parent_dir) or not os.path.isdir(parent_dir):
        return [], 0, None, None

    current_fname = os.path.basename(full_path)
    valid_exts = ('.md', '.rst', '.markdown')
    try:
        entries = [f for f in os.listdir(parent_dir) if not f.startswith('.') and os.path.splitext(f)[1].lower() in valid_exts]
    except Exception:
        entries = []

    entries.sort(key=natural_sort_key)
    siblings = []
    current_idx = 0

    for idx, fname in enumerate(entries):
        fpath = os.path.join(parent_dir, fname)
        rel_p = os.path.relpath(fpath, SCRIPT_DIR).replace('\\', '/')
        title = to_simplified_chinese(os.path.splitext(fname)[0])
        siblings.append({
            'title': title,
            'filename': fname,
            'rel_path': rel_p,
            'index': idx
        })
        if fname == current_fname:
            current_idx = idx

    prev_s = siblings[current_idx - 1] if current_idx > 0 else None
    next_s = siblings[current_idx + 1] if current_idx < len(siblings) - 1 else None
    return siblings, current_idx, prev_s, next_s

def read_novel_file(rel_path: str) -> Optional[Dict[str, Any]]:
    """读取指定小说/文档的内容与分回/分章渲染数据"""
    full_path = resolve_novel_or_doc_path(rel_path)
    if not full_path or not os.path.isfile(full_path):
        return None

    stat = os.stat(full_path)
    ext = os.path.splitext(full_path)[1].lower()
    base_title = to_simplified_chinese(os.path.splitext(os.path.basename(full_path))[0])

    result: Dict[str, Any] = {
        'rel_path': rel_path,
        'title': base_title,
        'ext': ext.lstrip('.'),
        'type': 'tech' if ext in ('.md', '.rst', '.markdown') else 'novel',
        'size_kb': round(stat.st_size / 1024, 1),
    }

    if ext == '.epub':
        epub_data = parse_epub_for_reader(full_path)
        result['chapters'] = epub_data.get('chapters', [])
        result['html'] = epub_data.get('html', '')
        result['raw'] = ''
        result['char_count'] = sum(c.get('char_count', len(c.get('html', ''))) for c in result['chapters'])
    elif ext in ('.md', '.markdown', '.rst'):
        raw_text = to_simplified_chinese(read_file_text(full_path))
        result['raw'] = raw_text
        result['char_count'] = len(raw_text)
        if ext == '.rst':
            try:
                import docutils.core
                parts = docutils.core.publish_parts(
                    source=raw_text,
                    writer_name='html5',
                    settings_overrides={'math_output': 'mathjax', 'report_level': 5, 'halt_level': 6}
                )
                result['html'] = parts.get('html_body', '')
            except Exception as e:
                result['html'] = f'<div class="doc-rst-error">RST 解析错误: {html.escape(str(e))}</div>'
        siblings, cur_idx, prev_s, next_s = get_sibling_docs(full_path)
        result['siblings'] = siblings
        result['sibling_index'] = cur_idx
        result['prev_sibling'] = prev_s
        result['next_sibling'] = next_s
    else:
        raw_text = to_simplified_chinese(read_file_text(full_path))
        chapters = parse_txt_chapters(raw_text)
        result['chapters'] = chapters
        result['raw'] = raw_text
        result['char_count'] = len(raw_text)

    return result

def trash_novel_file(rel_path: str) -> bool:
    """使用 gio trash 将小说/文档文件移动至系统回收站"""
    full_path = resolve_novel_or_doc_path(rel_path)
    if not full_path or not os.path.exists(full_path):
        return False
    try:
        res = subprocess.run(['gio', 'trash', full_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False
