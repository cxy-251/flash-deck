"""
Omni Deck 短视频画廊服务

展示 ExtensionForge 浏览器插件抓下来的短视频——新下载落在收件箱（settings.inbox_dir，默认
~/Downloads），归档后在各资源库的 media_library/shortvideo/<平台>/ 下：
    <收件箱>/快手/<主播名>/*.mp4   (002 插件, platform="kuaishou")
    <收件箱>/抖音/<主播名>/*.mp4   (003 插件, platform="douyin")
按 platform 分开扫描/索引/转码缓存，互不干扰；子标签按文件夹名（= 主播名）分类，
跟音声库的"专辑筛选条"是一个模式。

- 元数据（时长/分辨率）走 media_index 持久化索引：只有新增/变动的文件才真去跑一次
  ffprobe，其余吃 SQLite 缓存。kind 按平台区分（shortvideo:kuaishou / shortvideo:douyin）。
- 缩略图用 ffmpeg 抽一帧，同样只在文件新增/变动时才真去抽（media_index.get_or_make_thumb）。
- 播放：网页里原生 <video> 标签，跟媒体专区其它分区一个模式——这样本机 QtWebEngine 和
  局域网里的手机/电脑浏览器打开的是同一个页面，不用开任何新窗口。
  问题只出在本机这份 QtWebEngine：它是纯开源编译，没有 H.264 解码器（实测直接
  DEMUXER_ERROR_NO_SUPPORTED_STREAMS），放不了原始 mp4（快手、抖音都是 H.264，同一个坑）；
  局域网设备的正常浏览器解码原始 H.264 完全没问题。
  所以只对本机请求现转码成 VP9/WebM（有缓存，转一次以后都是秒开，输出只落在
  var/cache/shortvideo_webm/，绝不碰/不覆盖原始文件）；局域网/远程请求直接给
  原始文件，不转码、不丢质量、也不占本机 CPU。见 get_playable_for_client()。
"""

import os
import re
import sys
import time
import json
import subprocess
import threading
import urllib.parse
from typing import List, Dict, Any, Optional

from omni.core import events, library, manifest, media_index, paths, settings


# 平台清单来自 manifest 里 module=shortvideo 的分区（跟前端导航是同一份数据）
PLATFORMS: Dict[str, Dict[str, str]] = {
    sec["platform"]: {"label": sec["title"], "dir_name": sec["dir_name"], "kind": f"shortvideo:{sec['platform']}"}
    for sec in manifest.load()["sections"] if sec.get("module") == "shortvideo"
}
DEFAULT_PLATFORM = 'kuaishou'

VALID_EXTS = {'.mp4', '.mov', '.webm', '.mkv'}
# 图集作品（003 插件下载抖音多图+BGM 作品时，一个作品落地成一个子文件夹，里面是
# 01.webp/02.webp/... 这种编号图片，不再带视频）
IMAGE_EXTS = {'.webp', '.jpg', '.jpeg', '.png'}
IMAGE_MIME = {'.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}

# 点赞数据落盘（var/data/，本机状态）
LIKES_FILE = paths.SHORTVIDEO_LIKES
_LIKES_CACHE: Optional[Dict[str, set]] = None
_LIKES_LOCK = None


def _get_likes_lock():
    """懒初始化并返回保护点赞缓存读写的全局锁。

    Returns:
        threading.Lock: 全局唯一的点赞数据锁。
    """
    global _LIKES_LOCK
    if _LIKES_LOCK is None:
        import threading
        _LIKES_LOCK = threading.Lock()
    return _LIKES_LOCK


def load_likes() -> Dict[str, set]:
    """读取（并缓存）各平台的点赞集合，首次调用才真正读盘。

    Returns:
        Dict[str, set]: {平台名: 已点赞的相对路径集合}，固定含 kuaishou/douyin/tiktok 三个 key。
    """
    global _LIKES_CACHE
    if _LIKES_CACHE is not None:
        return _LIKES_CACHE
    with _get_likes_lock():
        if _LIKES_CACHE is not None:
            return _LIKES_CACHE
        res = {'kuaishou': set(), 'douyin': set(), 'tiktok': set()}
        if os.path.exists(LIKES_FILE):
            try:
                with open(LIKES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if k in res and isinstance(v, list):
                                res[k] = set(v)
            except Exception as e:
                print(f"[shortvideo] 读取点赞记录失败: {e}")
        _LIKES_CACHE = res
        return _LIKES_CACHE


# ---------------- 作者筛选条：钉住的作者 ----------------
#
# 筛选条第一行默认只有「全部」「我的点赞」，用户自己把常看的作者钉上去（顺序 = 钉的先后）。
# 存服务端（var/data/shortvideo_pins.json），Deck 本机和手机看到的是同一份。

_PINS_LOCK = threading.Lock()


def load_pins() -> Dict[str, List[str]]:
    try:
        with open(paths.SHORTVIDEO_PINS, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: [str(x) for x in v] for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}


def set_pinned(platform: str, folder: str, pinned: bool) -> List[str]:
    """钉 / 取消钉一个作者，返回这个平台钉住的作者（按钉的先后）。"""
    folder = str(folder or '').strip()
    with _PINS_LOCK:
        data = load_pins()
        cur = [f for f in data.get(platform, []) if f != folder]
        if pinned and folder:
            cur.append(folder)
        data[platform] = cur
        os.makedirs(os.path.dirname(paths.SHORTVIDEO_PINS), exist_ok=True)
        tmp = paths.SHORTVIDEO_PINS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SHORTVIDEO_PINS)
    return cur


def save_likes() -> None:
    """把当前内存里的点赞缓存原子写回磁盘（先写临时文件再 rename，避免写一半崩溃损坏文件）。"""
    if _LIKES_CACHE is None:
        return
    with _get_likes_lock():
        try:
            os.makedirs(os.path.dirname(LIKES_FILE), exist_ok=True)
            tmp = LIKES_FILE + ".tmp"
            data = {k: sorted(list(v)) for k, v in _LIKES_CACHE.items()}
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LIKES_FILE)
        except Exception as e:
            print(f"[shortvideo] 保存点赞记录失败: {e}")


def is_shortvideo_liked(platform: str, rel_path: str) -> bool:
    """查询某条短视频是否已被点赞。

    Args:
        platform: 平台名（kuaishou/douyin/tiktok）。
        rel_path: 视频相对路径（用作点赞记录的 key）。

    Returns:
        bool: 已点赞返回 True。
    """
    likes = load_likes()
    return rel_path in likes.get(platform, set())


def toggle_shortvideo_like(platform: str, rel_path: str, liked: Optional[bool] = None) -> bool:
    """切换或显式设置某条短视频的点赞状态，并持久化。

    Args:
        platform: 平台名（kuaishou/douyin/tiktok）。
        rel_path: 视频相对路径。
        liked: None 表示按当前状态取反；传 True/False 则显式设置成对应状态。

    Returns:
        bool: 操作完成后的最终点赞状态。
    """
    likes = load_likes()
    s = likes.setdefault(platform, set())
    if liked is None:
        if rel_path in s:
            s.remove(rel_path)
            res = False
        else:
            s.add(rel_path)
            res = True
    else:
        if liked:
            s.add(rel_path)
            res = True
        else:
            s.discard(rel_path)
            res = False
    save_likes()
    return res


def _platform_info(platform: str) -> Dict[str, str]:
    """查询平台配置（目录名、kind 等），不认识的平台名回退到 DEFAULT_PLATFORM。

    Args:
        platform: 平台名（kuaishou/douyin/tiktok）。

    Returns:
        Dict[str, str]: PLATFORMS 里对应的配置字典。
    """
    return PLATFORMS.get(platform) or PLATFORMS[DEFAULT_PLATFORM]


def _inbox_dir(platform: str) -> str:
    """收件箱里该平台的目录（浏览器插件写死的落地位置）。"""
    return os.path.join(settings.get("inbox_dir"), _platform_info(platform)['dir_name'])


def _platform_dirs(platform: str) -> List[str]:
    """该平台所有实际存在的目录：收件箱排最前，其后是各资源库的 media_library/shortvideo/<平台>。"""
    dirs = []
    inbox = _inbox_dir(platform)
    if os.path.isdir(inbox):
        dirs.append(inbox)
    key = f"media.shortvideo.{platform if platform in PLATFORMS else DEFAULT_PLATFORM}"
    for d in library.dirs(key):
        if d not in dirs:
            dirs.append(d)
    return dirs


def _resolve_platform_file(platform: str, clean_rel_path: str, kind: str = 'file') -> Optional[str]:
    """按相对路径依次在这个平台的每个候选根目录下找，返回第一个真实存在的物理路径。"""
    for root_dir in _platform_dirs(platform):
        full_p = os.path.join(root_dir, clean_rel_path)
        if kind == 'file' and os.path.isfile(full_p):
            return full_p
        if kind == 'dir' and os.path.isdir(full_p):
            return full_p
    return None


def _platform_kind(platform: str) -> str:
    """查询平台的内容形态（如视频/图集）。

    Args:
        platform: 平台名。

    Returns:
        str: PLATFORMS 配置里的 'kind' 字段值。
    """
    return _platform_info(platform)['kind']


def _rich_parse_video(full_p: str) -> Dict[str, Any]:
    """跑一次 ffprobe 拿时长/分辨率。只在文件新增/变动时被 media_index 调用。"""
    duration, width, height = 0.0, 0, 0
    try:
        # 后台补元数据：跟抽缩略图一样降到低 CPU / 空闲 IO 优先级，先让界面和正在播放的视频
        cmd = ['nice', '-n', '15', 'ionice', '-c3',
               'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', full_p]
        info = json.loads(subprocess.check_output(cmd, text=True, timeout=15, stderr=subprocess.DEVNULL))
        duration = float((info.get('format') or {}).get('duration') or 0)
        for s in info.get('streams', []):
            if s.get('codec_type') == 'video':
                width = int(s.get('width') or 0)
                height = int(s.get('height') or 0)
                # 手机录像常把竖屏存成横的宽高 + 旋转 90° 标记，按显示方向交换
                rot = (s.get('tags') or {}).get('rotate') or next(
                    (d.get('rotation') for d in s.get('side_data_list') or [] if 'rotation' in d), 0)
                if abs(int(float(rot or 0))) % 180 == 90:
                    width, height = height, width
                break
    except Exception:
        pass
    return {'duration': round(duration, 1), 'width': width, 'height': height}


def _extract_frame_bytes(full_p: str) -> Optional[bytes]:
    """ffmpeg 抽一帧当封面（JPEG bytes），失败就返回 None，前端用占位图兜底。

    批量补缩略图时外层信号量（_THUMB_GEN_SEM）已经把并发压到 3，但每个 ffmpeg
    进程本身默认会按核心数自动开解码线程，3 个进程 x 好几个线程照样能把整机吃满。
    这里用 nice/ionice 降低这类后台低优先级任务的调度/IO 优先级，再用 -threads 1
    把单个 ffmpeg 钉死在一个核上，"并发 3" 才名副其实地约等于"最多占 3 个核"，
    不会跟前台的网页请求/正在播放的视频抢资源。
    """
    for at_sec in ('1.0', '0.1'):  # 极短的片子 1s 处可能已经过了结尾，退到 0.1s 再试一次
        try:
            cmd = [
                'nice', '-n', '15', 'ionice', '-c3',
                'ffmpeg', '-y', '-threads', '1', '-ss', at_sec, '-i', full_p, '-frames:v', '1',
                '-vf', 'scale=360:-2', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'
            ]
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
            if out.returncode == 0 and out.stdout:
                return out.stdout
        except Exception:
            continue
    return None


def _iter_valid_files_under(dir_path: str, root_dir: str, folder: str):
    """递归遍历某个"主播/作品"子文件夹，yield 出其中所有符合扩展名的视频文件。

    从 _iter_files() 拆出来的内层逻辑：本身是 os.walk 一层 + 逐文件名一层，两层嵌套，
    拆开后 _iter_files() 自己不用再叠第三、四层循环。

    Args:
        dir_path: 要递归遍历的子文件夹路径。
        root_dir: 该子文件夹所属的资源库根路径，用于算相对路径。
        folder: 子文件夹名（作为返回条目的"所属文件夹"字段）。

    Yields:
        tuple[str, str, str, float, int]: (完整路径, 相对路径, 所属文件夹名, mtime, size)。
    """
    for root, dirs, fnames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in fnames:
            if fname.startswith('.'):
                continue
            if os.path.splitext(fname)[1].lower() not in VALID_EXTS:
                continue
            full_p = os.path.join(root, fname)
            try:
                st = os.stat(full_p)
                if not os.path.isfile(full_p):
                    continue
            except OSError:
                continue
            rel_p = os.path.relpath(full_p, root_dir).replace('\\', '/')
            yield full_p, rel_p, folder, st.st_mtime, st.st_size


def _iter_files(platform: str):
    """遍历某平台目录下所有符合扩展名的视频文件（含子文件夹归类的"主播/作品"结构）。

    一个平台的内容可能分布在好几个已配置的资源库根路径下（比如老视频挪去了 SD 卡），
    每个候选根目录都扫一遍、结果合并。

    Args:
        platform: 平台名。

    Yields:
        tuple[str, str, str, float, int]: (完整路径, 相对路径, 所属文件夹名/"未分类",
        mtime, size)。
    """
    # 一个平台的内容可能分布在好几个已配置的资源库根路径下（比如老视频挪去了 SD 卡），
    # 每个候选根目录都扫一遍、结果合并。
    for root_dir in _platform_dirs(platform):
        try:
            top = list(os.scandir(root_dir))
        except OSError:
            continue
        for entry in top:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir():
                yield from _iter_valid_files_under(entry.path, root_dir, entry.name)
            elif entry.is_file() and os.path.splitext(entry.name)[1].lower() in VALID_EXTS:
                # 万一有人把视频直接扔在平台根目录下，也认，归到"未分类"
                try:
                    st = entry.stat()
                except OSError:
                    continue
                yield entry.path, entry.name, "未分类", st.st_mtime, st.st_size


def _iter_gallery_leaf_dirs_under(dir_path: str, root_dir: str, folder: str):
    """递归遍历某个"主播"子文件夹，yield 出其中每个符合条件的图集叶子目录。

    从 _iter_galleries() 拆出来的内层逻辑，避免在调用方再叠一层 os.walk 循环。

    Args:
        dir_path: 要递归遍历的子文件夹路径。
        root_dir: 该子文件夹所属的资源库根路径，用于算相对路径。
        folder: 子文件夹名（作为返回条目的"所属文件夹"字段）。

    Yields:
        tuple[str, str, list[str], float, int]: (相对路径, 所属文件夹名, 图片文件名列表,
        最新 mtime, 总 size)。
    """
    for root, dirs, fnames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        if dirs:
            continue  # 图集不会再往下分层，只看叶子目录
        fnames = [f for f in fnames if not f.startswith('.')]
        imgs = sorted(f for f in fnames if os.path.splitext(f)[1].lower() in IMAGE_EXTS)
        if not imgs:
            continue
        if any(os.path.splitext(f)[1].lower() in VALID_EXTS for f in fnames):
            continue  # 防御性：万一混进视频文件，不当图集处理，留给视频那条路径
        try:
            mtime = max(os.stat(os.path.join(root, f)).st_mtime for f in imgs)
            size = sum(os.stat(os.path.join(root, f)).st_size for f in imgs)
        except OSError:
            continue
        rel_p = os.path.relpath(root, root_dir).replace('\\', '/')
        yield rel_p, folder, imgs, mtime, size


def _iter_galleries(platform: str):
    """扫图集文件夹：<平台目录>/<主播>/<作品文件夹>/01.webp 02.webp ...

    只认"叶子目录、全是图片、不带视频"的文件夹，一个这样的文件夹算一条图集条目。
    同一个平台的内容可能分布在好几个已配置的资源库根路径下，逐个扫、结果合并。

    Args:
        platform: 平台名。

    Yields:
        tuple[str, str, list[str], float, int]: 见 _iter_gallery_leaf_dirs_under()。
    """
    for root_dir in _platform_dirs(platform):
        try:
            top = list(os.scandir(root_dir))
        except OSError:
            continue
        for entry in top:
            if entry.name.startswith('.') or not entry.is_dir():
                continue
            yield from _iter_gallery_leaf_dirs_under(entry.path, root_dir, entry.name)


def _on_index_progress(platform: str, done: int, total: int) -> None:
    """把某平台索引补齐进度通过 SSE 广播给前端。

    Args:
        platform: 平台名。
        done: 已处理数量。
        total: 总数量。
    """
    events.broadcast({'type': 'library_indexed', 'dir': f'shortvideo:{platform}', 'done': done, 'total': total})


_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_LAST_SCAN: Dict[str, float] = {}
_SCAN_TTL = 60.0
_SCAN_RUNNING: Dict[str, bool] = {}   # platform -> 后台全量重扫是否在跑
_LAST_SAVE: Dict[str, float] = {}     # platform -> 上次写落盘快照的时间
_SAVE_INTERVAL = 600.0                # 只有元数据变化时，快照最多这么久写一次

# 上面那套"旧数据先顶着、后台重扫"的缓存全是进程内存，重启 omni-deck 就清空了——每次重启
# 后的第一次打开，_CACHE 里没东西可垫，照样要同步跑一遍全量扫描，一样会转圈等。这里再加一层
# 落盘快照（cache/shortvideo_list_<platform>.json）：每次扫完顺手存一份，下次进程重启后
# 冷启动时先读这份快照（可能有几分钟到几小时旧，无所谓），立刻还给前端，真正的重扫依旧丢
# 后台去做——这样"转圈"只会出现在这台机器有史以来第一次打开某个平台的短视频库那一次。
_LIST_CACHE_DIR = paths.CACHE


def _list_cache_path(platform: str) -> str:
    """算出某平台列表快照的落盘路径。

    Args:
        platform: 平台名。

    Returns:
        str: 快照 JSON 文件路径。
    """
    return os.path.join(_LIST_CACHE_DIR, f"shortvideo_list_{platform}.json")


def _save_list_cache(platform: str, items: List[Dict[str, Any]]) -> None:
    """把扫描结果原子写入落盘快照，供下次进程重启后冷启动垫底用。

    Args:
        platform: 平台名。
        items: 完整的条目列表。
    """
    try:
        os.makedirs(_LIST_CACHE_DIR, exist_ok=True)
        tmp = _list_cache_path(platform) + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, _list_cache_path(platform))
    except Exception as e:
        print(f"[shortvideo] 落盘快照失败 {platform}: {e}")


def _load_list_cache(platform: str) -> Optional[List[Dict[str, Any]]]:
    """读取某平台的落盘列表快照（进程重启后的冷启动垫底数据）。

    Args:
        platform: 平台名。

    Returns:
        Optional[List[Dict[str, Any]]]: 快照内容；不存在/损坏时返回 None。
    """
    try:
        with open(_list_cache_path(platform), 'r', encoding='utf-8') as f:
            items = json.load(f)
        return [_slim(platform, it) for it in items] if isinstance(items, list) else None   # 旧格式快照也转成精简条目
    except Exception:
        return None


_DATE_PREFIX_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')
_AWEME_ID_RE = re.compile(r'_(\d{15,20})$')   # 抖音：文件名 / 图集文件夹名结尾的作品 ID

# ---------------- 列表条目：内存 / 快照里只存这几个字段，其余下发时现算 ----------------
#
# 抖音一个平台六万多条。以前每条带 13 个字段，其中 thumb_url / stream_url 是两条把中文路径百分号编码过的
# 长 URL，标题、文件名、大小 MB、日期字符串也都能从别的字段推出来——光抖音就占 140MB 内存、快照 70MB。
# 现在只存 platform / rel_path / folder / mtime / size / kind / duration / width / height（图集多 image_count），
# folder 字符串 intern 掉（一个作者几百上千条共用一份）；给网页的完整字段由 public_item() 现算。
SLIM_KEYS = ('platform', 'rel_path', 'folder', 'mtime', 'size', 'kind', 'duration', 'width', 'height', 'image_count')


def _slim(platform: str, it: Dict[str, Any]) -> Dict[str, Any]:
    """任意来源的条目（新扫描 / 旧格式快照）→ 精简条目。"""
    size = it.get('size')
    if size is None:   # 旧快照只有 size_mb
        size = int(round((it.get('size_mb') or 0) * 1024 * 1024))
    out = {'platform': platform, 'rel_path': it['rel_path'], 'folder': sys.intern(it.get('folder') or '未分类'),
           'mtime': it.get('mtime') or 0, 'size': size, 'kind': it.get('kind') or 'video',
           'duration': it.get('duration') or 0, 'width': it.get('width') or 0, 'height': it.get('height') or 0}
    if out['kind'] == 'images':
        out['image_count'] = it.get('image_count') or 0
    return out


def item_title(it: Dict[str, Any]) -> str:
    """显示用标题：视频 = 文件名去扩展名；图集 = 文件夹名。"""
    base = it['rel_path'].rsplit('/', 1)[-1]
    return base if it.get('kind') == 'images' else os.path.splitext(base)[0]


def public_item(it: Dict[str, Any], liked: bool = False, local_cached: Optional[bool] = None) -> Dict[str, Any]:
    """精简条目 → 给网页的完整字段（新字典，不改缓存里的条目）。"""
    platform, rel_p = it['platform'], it['rel_path']
    q = urllib.parse.quote(rel_p)
    images = it.get('kind') == 'images'
    out = dict(it)
    out.update({
        'title': item_title(it),
        'filename': rel_p.rsplit('/', 1)[-1],
        'size_mb': round(it['size'] / (1024 * 1024), 2),
        'mtime_str': time.strftime('%Y-%m-%d', time.localtime(it['mtime'])),
        'thumb_url': (f"/api/shortvideo/gallery_image?platform={platform}&path={q}&idx=0&thumb=1" if images
                      else f"/api/shortvideo/thumb?platform={platform}&path={q}"),
        'stream_url': None if images else f"/api/shortvideo/stream?platform={platform}&path={q}",
        'liked': liked,
    })
    if local_cached is not None:
        out['local_cached'] = local_cached
    return out


def _chrono_sort_key(item: Dict[str, Any]):
    """按作品真实发布日期排序，最新的在前——不能用文件的 mtime，实测快手 1856 个文件的
    mtime 全挤在同一天几个小时的窗口里（明显是某次批量搬运/复制留下的痕迹，不是真实下载
    节奏），但文件名/图集文件夹名本身是 002/003 插件按「日期_标题_作品ID」这个格式命名的
    （见两个插件 background.js 的 expand()），日期前缀才是真正可信的发布时间。有就用它
    排序（数值取负实现降序，同时保留"有日期的分组"这个优先级不受降序影响），没有（老
    文件、非标准命名）才退回 mtime，统一垫底，不会因为个别没匹配上的文件直接报错断档。"""
    title = item_title(item)
    m = _DATE_PREFIX_RE.match(title)
    if m:
        date_num = int(m.group(1).replace('-', ''))
        # 同一天里再按作品 ID 排：抖音文件名结尾的作品 ID 是按发布时间递增的雪花 ID（快手的 ID 不是，
        # 只能退回 mtime——而 mtime 是下载时间，同一天里的先后基本是乱的）
        aid = _AWEME_ID_RE.search(title)
        return (0, -date_num, -int(aid.group(1)) if aid else 0, -item['mtime'])
    return (1, 0, 0, -item['mtime'])


def _do_scan(platform: str) -> List[Dict[str, Any]]:
    """真正干活的那一遍扫描——os.walk 全库 + media_index 差量补 ffprobe。这是"慢"的部分，
    只应该在冷启动或用户主动点刷新时同步跑；平时缓存过期的重扫改走后台线程（见
    scan_shortvideo_library），别让随手翻页/切标签被这个卡住。"""
    files = []
    fs_info = {}   # full_p -> (rel_p, folder, mtime, size)
    for full_p, rel_p, folder, mtime, size in _iter_files(platform):
        files.append((full_p, mtime, size))
        fs_info[full_p] = (rel_p, folder, mtime, size)

    metas = media_index.diff_scan(_platform_kind(platform), files, _rich_parse_video,
                                   sync_limit=20, on_progress=lambda d, t: _on_index_progress(platform, d, t))

    items = []
    for full_p, (rel_p, folder, mtime, size) in fs_info.items():
        meta = metas.get(full_p) or {}
        items.append(_slim(platform, {'rel_path': rel_p, 'folder': folder, 'mtime': mtime, 'size': size, 'kind': 'video',
                                      'duration': meta.get('duration', 0), 'width': meta.get('width', 0),
                                      'height': meta.get('height', 0)}))

    # 图集（抖音多图作品）：不用 ffprobe/转码，直接拿文件夹里的图当"帧"
    for rel_p, folder, imgs, mtime, size in _iter_galleries(platform):
        items.append(_slim(platform, {'rel_path': rel_p, 'folder': folder, 'mtime': mtime, 'size': size,
                                      'kind': 'images', 'image_count': len(imgs)}))

    items.sort(key=_chrono_sort_key)   # 正序：按作品真实发布日期从早到晚
    return items


def _store_scan(platform: str, items: List[Dict[str, Any]]) -> bool:
    """扫描结果写回内存缓存；跟上一份不一样才落盘快照，返回是否有变化。

    抖音一个平台五万多条，快照 JSON 五十多 MB——以前每扫一遍都重写一次，扫完还无条件广播
    library_indexed，网页收到就拉一次列表，拉列表又触发下一轮后台重扫：只要页面开着就一直
    转圈似地扫盘写盘、内存跟着来回涨。列表逐条比对是 C 层的 dict 比较，几十毫秒。"""
    old = _CACHE.get(platform)
    changed = items != old
    _CACHE[platform] = items
    if changed:
        # 文件有增减马上落盘；只是后台 ffprobe 补上了时长 / 分辨率（新下载一万多条时要补好几十分钟，
        # 每轮都「变了」），最多 10 分钟写一次——快照只是重启后先顶上的垫底数据，元数据本来就在
        # media_index 里，晚几分钟无所谓。以前补全期间每分钟重写一次 70MB 的抖音快照。
        files_changed = old is None or len(old) != len(items) or \
            {it["rel_path"] for it in old} != {it["rel_path"] for it in items}
        now = time.time()
        if files_changed or now - _LAST_SAVE.get(platform, 0) >= _SAVE_INTERVAL:
            _save_list_cache(platform, items)
            _LAST_SAVE[platform] = now
    return changed


def _refresh_in_background(platform: str) -> None:
    """真正的全量重扫丢到后台跑，扫完了更新缓存、顺手广播一下 library_indexed——前端 SSE
    收到这个事件会自己 loadShortVideoLibrary 静默刷新，用户不用等、也不会看到卡顿。"""
    import threading
    if _SCAN_RUNNING.get(platform):
        return
    _SCAN_RUNNING[platform] = True

    def _bg():
        """实际执行全量重扫，写回缓存并广播完成事件（无论成败都清掉运行中标记）。"""
        try:
            items = _do_scan(platform)
            if _store_scan(platform, items):   # 没变化就不通知网页，免得它拉列表又触发下一轮
                _on_index_progress(platform, len(items), len(items))
        finally:
            _SCAN_RUNNING[platform] = False

    threading.Thread(target=_bg, name=f"shortvideo-scan-{platform}", daemon=True).start()


def scan_shortvideo_library(platform: str = DEFAULT_PLATFORM, force: bool = False) -> List[Dict[str, Any]]:
    """<下载目录>/<平台>/ 的视频列表（含 media_index 缓存的时长/分辨率）。

    冷启动第一次、或者用户主动点"刷新"（force=True），没有别的选择，只能真去扫一遍、
    同步等结果。但平常缓存过期（每 60s）这种被动触发的情况，之前是每次都在请求线程里
    同步重新 os.walk 一遍全库（快手 1800+ / 抖音 2000+ 条，一堆图集子文件夹更是加倍拉长
    这个耗时）——这就是"首屏很慢，感觉是一次性加载全部视频"的真实原因：不是一次性把
    全部视频都发给前端（分页一直是对的），而是"扫下一页之前，得先把全库重新扫一遍"这一步
    本身很慢、还挡在请求路径上。现在改成：手头有旧数据就先把旧数据立刻还回去（哪怕过期
    最多 60s 也无所谓，跟漫画/音声/小说同一个"先给能给的，新数据后台补"的思路），真正的
    重扫挪到后台线程，扫完自动通知前端刷新，请求路径上完全不再等这个。"""
    now = time.time()
    cached = _CACHE.get(platform)
    fresh_enough = cached is not None and (now - _LAST_SCAN.get(platform, 0) < _SCAN_TTL)

    if not force and fresh_enough:
        return cached

    if not force and cached is None:
        # 进程刚启动，内存缓存是空的——先看看上次进程存的落盘快照有没有，有就先拿它顶上
        # （可能是几分钟到几小时前的状态，无所谓，比转圈等强），后台照样去真扫一遍更新
        disk_cached = _load_list_cache(platform)
        if disk_cached is not None:
            _CACHE[platform] = disk_cached
            _LAST_SCAN[platform] = now
            _refresh_in_background(platform)
            return disk_cached

    if force or cached is None:
        # 没有任何旧数据可垫（这台机器第一次打开这个平台的短视频库）、或者用户主动要求
        # 刷新：这次真等
        items = _do_scan(platform)
        _store_scan(platform, items)
        _LAST_SCAN[platform] = now
        return items

    # 有旧数据、只是过期了：先照旧数据回，重扫挪到后台
    _LAST_SCAN[platform] = now   # 立刻续期，避免这段时间内的并发请求各自再触发一次后台重扫
    _refresh_in_background(platform)
    return cached


def query_shortvideo_library(platform: str = DEFAULT_PLATFORM, q: str = "", folder: str = "all",
                              page: int = 1, page_size: int = 60) -> Dict[str, Any]:
    """短视频库的分页查询入口：搜索 + 按文件夹/点赞过滤 + 分页，供 API 路由直接调用。

    Args:
        platform: 平台名。
        q: 搜索关键词（大小写不敏感，匹配文件名），空字符串表示不过滤。
        folder: 'all' 全部 / 'liked' 只看点赞 / 具体文件夹名。
        page: 页码，从 1 开始。
        page_size: 每页条数。

    Returns:
        Dict[str, Any]: 含 items（当页条目）、total、folders（文件夹筛选栏数据）等字段。
    """
    all_items = scan_shortvideo_library(platform)
    ensure_background_transcode(platform)

    # 别往缓存里的条目写字段（以前写 liked / local_cached，下一轮扫描拿新结果一比，次次都「变了」，
    # 于是又广播、网页又来拉、又触发重扫——短视频页开着就每分钟重写一遍快照）
    liked_set = load_likes().get(platform, set())
    liked_count = sum(1 for it in all_items if it['rel_path'] in liked_set)

    folder_counts: Dict[str, int] = {}
    for it in all_items:
        folder_counts[it['folder']] = folder_counts.get(it['folder'], 0) + 1
    folders = [
        {'name': '全部', 'key': 'all', 'count': len(all_items)},
        {'name': '❤️ 我的点赞', 'key': 'liked', 'count': liked_count}
    ]
    for name, cnt in sorted(folder_counts.items(), key=lambda x: -x[1]):
        folders.append({'name': name, 'key': name, 'count': cnt})

    matched = all_items
    if folder == 'liked' or folder == '❤️ 我的点赞':
        matched = [it for it in matched if it['rel_path'] in liked_set]
    elif folder and folder != 'all':
        matched = [it for it in matched if it['folder'] == folder]

    q = (q or '').strip().lower()
    if q:
        matched = [it for it in matched if q in item_title(it).lower() or q in it['folder'].lower()]

    total = len(matched)
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    # 告诉前端这条本机是不是已经转码缓存过了——只有本机 QtWebEngine 需要转码，前端据此
    # 决定要不要显示"正在转码"提示，别对着已经缓存好的视频也无脑弹一下
    # 图集是图片，浏览器原生能显示 webp，不存在"转码"这回事，直接当已就绪处理
    page_items = []
    for it in matched[start:end]:
        if it.get('kind') == 'images':
            cached = True
        else:
            full_p = find_shortvideo_file(platform, it['rel_path'])
            cached = bool(full_p and _is_transcode_fresh(full_p, _transcode_cache_path(full_p)))
        page_items.append(public_item(it, it['rel_path'] in liked_set, cached))

    return {
        'items': page_items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'has_more': end < total,
        'folders': folders,
        'pinned': load_pins().get(platform, []),
        'platform': platform,
        'liked_count': liked_count,
    }


def find_shortvideo_file(platform: str, rel_path: str) -> Optional[str]:
    """按相对路径在这个平台的各个候选根目录下定位物理文件，防路径穿越。"""
    if not rel_path:
        return None
    clean_p = rel_path.replace('\\', '/').strip('/')
    if '..' in clean_p.split('/'):
        return None
    return _resolve_platform_file(platform, clean_p, kind='file')


def find_gallery_dir(platform: str, rel_path: str) -> Optional[str]:
    """按相对路径在这个平台的各个候选根目录下定位图集文件夹，防路径穿越。"""
    if not rel_path:
        return None
    clean_p = rel_path.replace('\\', '/').strip('/')
    if '..' in clean_p.split('/'):
        return None
    return _resolve_platform_file(platform, clean_p, kind='dir')


def get_gallery_image(platform: str, rel_path: str, idx: int):
    """图集里第 idx 张图（按文件名排序）。返回 (物理路径, content-type) 或 (None, None)。"""
    full_dir = find_gallery_dir(platform, rel_path)
    if not full_dir:
        return None, None
    try:
        imgs = sorted(
            f for f in os.listdir(full_dir)
            if not f.startswith('.') and os.path.splitext(f)[1].lower() in IMAGE_EXTS
        )
    except OSError:
        return None, None
    if idx < 0 or idx >= len(imgs):
        return None, None
    full_p = os.path.join(full_dir, imgs[idx])
    ext = os.path.splitext(full_p)[1].lower()
    return full_p, IMAGE_MIME.get(ext, 'application/octet-stream')


def gallery_image_count(platform: str, rel_path: str) -> int:
    """统计某个图集文件夹里的图片张数。

    Args:
        platform: 平台名。
        rel_path: 图集文件夹相对路径。

    Returns:
        int: 图片数量；找不到文件夹时返回 0。
    """
    full_dir = find_gallery_dir(platform, rel_path)
    if not full_dir:
        return 0
    try:
        return sum(1 for f in os.listdir(full_dir) if not f.startswith('.') and os.path.splitext(f)[1].lower() in IMAGE_EXTS)
    except OSError:
        return 0


def get_gallery_thumb(platform: str, rel_path: str) -> Optional[str]:
    """图集卡片封面：第一张图缩成 360 宽的 webp（跟视频缩略图同一套缓存）。
    以前卡片直接用原图——抖音图集多是 1400×2500 上下，一张解码后十几 MB，网页滚几页就涨好几百 MB。"""
    p, _ = get_gallery_image(platform, rel_path, 0)
    if not p:
        return None

    def read():
        with open(p, 'rb') as f:
            return f.read()
    return media_index.get_or_make_thumb(p, read, max_w=360, tag='gthumb')


def get_video_thumb(platform: str, rel_path: str) -> Optional[str]:
    """拿到某条视频的封面缩略图路径，没有就现抽一帧生成。

    Args:
        platform: 平台名。
        rel_path: 视频相对路径。

    Returns:
        Optional[str]: 缩略图路径；找不到源文件或生成失败时返回 None。
    """
    full_p = find_shortvideo_file(platform, rel_path)
    if not full_p:
        return None
    return media_index.get_or_make_thumb(full_p, lambda: _extract_frame_bytes(full_p), max_w=360, tag='vthumb')


# ---------------- 播放：只给本机转码，局域网/远程走原始文件 ----------------

_TRANSCODE_DIR = paths.SHORTVIDEO_WEBM
_TRANSCODE_LOCKS: Dict[str, "object"] = {}
_TRANSCODE_LOCKS_GUARD = None  # 延迟建 Lock，避免模块顶层就 import threading

# -cpu-used 8 + row-mt + tile-columns：牺牲一点画质/体积换编码速度，个人媒体库看个短视频，
# 速度比画质重要——实测一条 12s 短视频 ~6s 转完（比 -cpu-used 5 快一倍还多）。
_FFMPEG_WEBM_ARGS = [
    '-c:v', 'libvpx-vp9', '-b:v', '1200k', '-deadline', 'realtime',
    '-cpu-used', '8', '-row-mt', '1', '-tile-columns', '2', '-threads', '4',
    '-c:a', 'libopus', '-b:a', '96k', '-f', 'webm'
]


def _transcode_cache_path(full_p: str) -> str:
    """算出某个源视频对应的 WebM 转码缓存路径（按完整绝对路径哈希，天然跨平台不冲突）。

    Args:
        full_p: 源视频文件的绝对路径。

    Returns:
        str: 转码后 .webm 文件的缓存路径。
    """
    # 哈希 key 是完整绝对路径（本来就带着 快手/抖音 这层目录），两个平台天然不会撞
    import hashlib
    key = hashlib.sha1(full_p.encode('utf-8')).hexdigest()
    os.makedirs(_TRANSCODE_DIR, exist_ok=True)
    return os.path.join(_TRANSCODE_DIR, key + '.webm')


def _is_transcode_fresh(full_p: str, out_p: str) -> bool:
    """判断转码缓存是否还有效（存在且不比源文件旧）。

    Args:
        full_p: 源视频文件路径。
        out_p: 转码缓存文件路径。

    Returns:
        bool: 缓存有效返回 True。
    """
    try:
        return os.path.exists(out_p) and os.stat(out_p).st_mtime >= os.stat(full_p).st_mtime
    except OSError:
        return False


def _get_lock(key: str):
    """按 key 懒创建/取出一把互斥锁，避免同一个视频被并发重复转码。

    Args:
        key: 通常是源视频的绝对路径。

    Returns:
        threading.Lock: 该 key 专属的锁对象。
    """
    import threading
    global _TRANSCODE_LOCKS_GUARD
    if _TRANSCODE_LOCKS_GUARD is None:
        _TRANSCODE_LOCKS_GUARD = threading.Lock()
    with _TRANSCODE_LOCKS_GUARD:
        return _TRANSCODE_LOCKS.setdefault(key, threading.Lock())


def _transcode_to_webm(full_p: str) -> Optional[str]:
    """把源视频转码成 VP9/WebM（本机 QtWebEngine 放不了原始 H.264 时用），有新鲜缓存直接复用。

    Args:
        full_p: 源视频文件的绝对路径。

    Returns:
        Optional[str]: 转码后文件路径；ffmpeg 失败时返回 None。
    """
    out_p = _transcode_cache_path(full_p)
    if _is_transcode_fresh(full_p, out_p):
        return out_p
    with _get_lock(full_p):
        if _is_transcode_fresh(full_p, out_p):   # 排队等锁时可能已经被别的请求转完了
            return out_p
        tmp = out_p + '.tmp'
        try:
            cmd = ['ffmpeg', '-y', '-i', full_p] + _FFMPEG_WEBM_ARGS + [tmp]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
            if res.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                err = (res.stderr or b'').decode('utf-8', 'ignore')[-300:]
                print(f"[shortvideo] 转码失败 {os.path.basename(full_p)}: {err}")
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return None
            os.replace(tmp, out_p)
            return out_p
        except Exception as e:
            print(f"[shortvideo] 转码异常 {os.path.basename(full_p)}: {e}")
            return None


def get_playable_for_client(platform: str, rel_path: str, is_local: bool):
    """返回 (文件路径, content_type)。本机（QtWebEngine 放不了原始 H.264）现转 VP9/WebM，
    有缓存；局域网/远程设备的浏览器解码原始 H.264 没问题，直接给原始文件，不转码。"""
    full_p = find_shortvideo_file(platform, rel_path)
    if not full_p:
        return None, None
    if not is_local:
        ext = os.path.splitext(full_p)[1].lower()
        mime_map = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm', '.mkv': 'video/x-matroska'}
        return full_p, mime_map.get(ext, 'video/mp4')
    webm_p = _transcode_to_webm(full_p)
    if not webm_p:
        return None, None
    return webm_p, 'video/webm'


_EAGER_TRANSCODE: Dict[str, bool] = {}     # platform -> 「立即全部转码」按钮按下时置 True（已停用，留着不用）
_TRANSCODE_RUNNING: Dict[str, bool] = {}   # platform -> 后台补缓存线程是否在跑

# 转码功能整体停用：本机播放已经改走 native_player.py 的原生解码（QtMultimedia 自带完整
# ffmpeg，H.264/AAC 都能直接放），不再需要转码成 webm 再给本机播；局域网/远程本来就是给
# 原始文件，也用不上。_transcode_to_webm/get_playable_for_client 函数本体没删，留着当
# 万一以后哪天原生播放这条路走不通时的备用方案，但不再有任何代码主动触发它们。
_TRANSCODE_DISABLED = True


def ensure_background_transcode(platform: str = DEFAULT_PLATFORM) -> None:
    """默认节流模式：某平台的画廊页面打开时顺手在后台把还没转过的本机播放缓存陆续转好
    （间隔 0.3s，不占着 CPU），真点开时大概率已经缓存好、秒开。每个平台各自最多一个后台线程。

    已停用（见 _TRANSCODE_DISABLED）——本机播放不再需要转码，白跑纯粹浪费 CPU/硬盘。"""
    if _TRANSCODE_DISABLED:
        return
    import threading
    if _TRANSCODE_RUNNING.get(platform):
        return
    _TRANSCODE_RUNNING[platform] = True

    def _worker():
        """依次遍历该平台还没转码或缓存已过期的视频，逐个转码，转完清掉运行中标记。"""
        try:
            for it in scan_shortvideo_library(platform):
                if it.get('kind') == 'images':
                    continue   # 图集是图片，没有"转码"这回事
                full_p = find_shortvideo_file(platform, it['rel_path'])
                if not full_p:
                    continue
                if _is_transcode_fresh(full_p, _transcode_cache_path(full_p)):
                    continue
                _transcode_to_webm(full_p)
                if not _EAGER_TRANSCODE.get(platform):
                    time.sleep(0.3)   # 别把 CPU 焊死一整块，间隙里让别的请求能插进来
        finally:
            _TRANSCODE_RUNNING[platform] = False

    threading.Thread(target=_worker, name=f"shortvideo-transcode-{platform}", daemon=True).start()


def transcode_all_now(platform: str = DEFAULT_PLATFORM) -> None:
    """「立即全部转码」按钮：已停用，按钮本身也从页面上拿掉了，这个函数留空壳防止旧路由
    还打过来时报错。"""
    if _TRANSCODE_DISABLED:
        return
    _EAGER_TRANSCODE[platform] = True
    ensure_background_transcode(platform)


def transcode_status(platform: str = DEFAULT_PLATFORM) -> Dict[str, Any]:
    """已停用：转码不再进行，直接报「跟总数一样多」，语义上等价于"没有待转码的"。"""
    if _TRANSCODE_DISABLED:
        return {'done': 0, 'total': 0, 'running': False}
    items = [it for it in scan_shortvideo_library(platform) if it.get('kind') != 'images']
    total = len(items)
    done = 0
    for it in items:
        full_p = find_shortvideo_file(platform, it['rel_path'])
        if full_p and _is_transcode_fresh(full_p, _transcode_cache_path(full_p)):
            done += 1
    return {'done': done, 'total': total, 'running': bool(_TRANSCODE_RUNNING.get(platform))}


def trash_shortvideo_file(platform: str, rel_path: str) -> bool:
    """按 AGENTS.md 准则用 gio trash 安全删除。
    视频是单个文件，图集是一整个文件夹——两种都按同一套逻辑：定位到什么删什么。
    删完只从内存列表里拿掉这一条，不再同步全量重扫（抖音五万多条，扫一遍要好几秒）；
    落盘快照等下一轮后台扫描自然更新。"""
    full_p = find_shortvideo_file(platform, rel_path) or find_gallery_dir(platform, rel_path)
    if not full_p:
        return False
    try:
        res = subprocess.run(['gio', 'trash', full_p], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return False
    if res.returncode != 0:
        return False
    toggle_shortvideo_like(platform, rel_path, liked=False)
    cached = _CACHE.get(platform)
    if cached is not None:
        _CACHE[platform] = [it for it in cached if it['rel_path'] != rel_path]
    return True
