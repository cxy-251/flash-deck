#!/usr/bin/env python3
"""
媒体库持久化元数据索引 —— 漫画 / 小说 / 音声共用。

问题：漫画、音声这些几千项的分类，每次扫描都要为**每个文件**开一遍压缩包读
metadata、抽封面、跑 ffprobe……慢速 SD 卡上随机 I/O 几十秒起。而平时我们只需要
索引信息（标题/标签/页数…），并不是当场就要访问文件内容。

方案：一个 SQLite 索引（`cache/media_index.db`），一张表：
    path(主键) | kind | mtime | size | meta(JSON) | indexed_at
扫描时先 `load_kind()` 一把把某类全读进来（一条 SQL），再 `os.scandir` 快速拿到
每个文件的 (mtime, size)：
  - 索引里有、mtime+size 没变  → 直接用缓存的 meta，**不开文件**
  - 新增 / 变了              → 才真去解析，然后 put 回索引
  - 磁盘上没了              → prune 掉
冷启动第一次照旧慢（跟今天扫一次差不多），之后每次都是"零文件打开"。

纯缓存：DB 丢了 / schema 版本对不上 → 自动重建，不丢任何东西（真相永远是磁盘上
的文件本身 + 压缩包里的 metadata.json）。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import threading
import time

from omni.core import paths

_CACHE_DIR = paths.CACHE
_DB_PATH = paths.MEDIA_INDEX_DB
_THUMB_DIR = paths.THUMBS
_SCHEMA_VERSION = 1

os.makedirs(_CACHE_DIR, exist_ok=True)
os.makedirs(_THUMB_DIR, exist_ok=True)

_LOCK = threading.RLock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    """拿到全局共用的 SQLite 连接，没有就建一个；schema 版本对不上就整库重建。

    Returns:
        sqlite3.Connection: 已建好 media_meta 表和索引的连接（WAL 模式，线程间共用）。
    """
    global _conn
    if _conn is not None:
        return _conn
    with _LOCK:
        if _conn is not None:
            return _conn
        need_rebuild = False
        try:
            c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            row = c.execute("PRAGMA user_version").fetchone()
            if row and row[0] != _SCHEMA_VERSION:
                need_rebuild = True
        except Exception:
            need_rebuild = True
            try:
                c.close()  # type: ignore
            except Exception:
                pass
        if need_rebuild:
            try:
                os.remove(_DB_PATH)
            except OSError:
                pass
            c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
        c.execute("""
            CREATE TABLE IF NOT EXISTS media_meta (
                path       TEXT PRIMARY KEY,
                kind       TEXT NOT NULL,
                mtime      REAL NOT NULL,
                size       INTEGER NOT NULL,
                meta       TEXT NOT NULL,
                indexed_at REAL NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_media_kind ON media_meta(kind)")
        c.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        c.commit()
        _conn = c
        return _conn


_LOAD_CACHE: dict = {}          # kind -> (ts, dict)   进程内短 TTL 缓存，避免每次请求都解析几百行 JSON
_LOAD_TTL = 8.0


def _invalidate(kind: str) -> None:
    """清掉某个 kind 的进程内短 TTL 缓存，逼下一次 load_kind() 重新查库。

    Args:
        kind: 媒体类型（如 "manga"/"audio"）。
    """
    _LOAD_CACHE.pop(kind, None)


def load_kind(kind: str, use_cache: bool = True) -> dict:
    """一次性读回某个媒体类型的全部索引记录。

    Args:
        kind: 媒体类型（如 "manga"/"audio"）。
        use_cache: 是否允许命中进程内的短 TTL 缓存（默认 True，避免每次请求都重新查库）。

    Returns:
        dict: {path: {"mtime": ..., "size": ..., "meta": {...}}}，查询失败时返回空 dict。
    """
    if use_cache:
        hit = _LOAD_CACHE.get(kind)
        if hit and (time.time() - hit[0]) < _LOAD_TTL:
            return hit[1]
    out = {}
    try:
        with _LOCK:
            rows = _db().execute(
                "SELECT path, mtime, size, meta FROM media_meta WHERE kind=?", (kind,)
            ).fetchall()
        for path, mtime, size, meta in rows:
            try:
                out[path] = {"mtime": mtime, "size": size, "meta": json.loads(meta)}
            except Exception:
                pass
    except Exception as e:
        print(f"[media_index] load_kind({kind}) 失败：{e}")
    _LOAD_CACHE[kind] = (time.time(), out)
    return out


def put_many(rows: list) -> None:
    """批量写入/更新索引记录（按 path 做 upsert），写完顺带失效受影响 kind 的读缓存。

    Args:
        rows: [(path, kind, mtime, size, meta_dict), ...] 的列表。
    """
    if not rows:
        return
    now = time.time()
    payload = [
        (p, k, float(mt), int(sz), json.dumps(m, ensure_ascii=False), now)
        for (p, k, mt, sz, m) in rows
    ]
    try:
        with _LOCK:
            c = _db()
            c.executemany(
                "INSERT INTO media_meta(path,kind,mtime,size,meta,indexed_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "kind=excluded.kind, mtime=excluded.mtime, size=excluded.size, "
                "meta=excluded.meta, indexed_at=excluded.indexed_at",
                payload,
            )
            c.commit()
        for k in {r[1] for r in rows}:
            _invalidate(k)
    except Exception as e:
        print(f"[media_index] put_many 失败：{e}")


def prune(kind: str, live_paths) -> int:
    """删掉索引里那些磁盘上已经不存在的记录。

    Args:
        kind: 媒体类型（如 "manga"/"audio"）。
        live_paths: 当前磁盘上真实存在的 path 集合（可迭代对象）。

    Returns:
        int: 实际删掉的记录数，出错时返回 0。
    """
    live = set(live_paths)
    try:
        with _LOCK:
            c = _db()
            existing = [r[0] for r in c.execute(
                "SELECT path FROM media_meta WHERE kind=?", (kind,)
            ).fetchall()]
            dead = [p for p in existing if p not in live]
            if dead:
                c.executemany("DELETE FROM media_meta WHERE path=?", [(p,) for p in dead])
                c.commit()
            return len(dead)
    except Exception as e:
        print(f"[media_index] prune({kind}) 失败：{e}")
        return 0


def count(kind: str) -> int:
    """统计某个 kind 在索引里当前有多少条记录。

    Args:
        kind: 媒体类型（如 "manga"/"audio"）。

    Returns:
        int: 记录数，查询失败时返回 0。
    """
    try:
        with _LOCK:
            r = _db().execute("SELECT COUNT(*) FROM media_meta WHERE kind=?", (kind,)).fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


# ---------------- 封面缩略图缓存 ----------------

def thumb_path(src_path: str, tag: str = "") -> str:
    """算出某个源文件（+可选 tag 区分同源多种缩略图）对应的缓存缩略图路径。

    这只是算路径，不保证文件已经生成——是否存在由调用方自己 os.path.exists 判断。

    Args:
        src_path: 原始文件的路径（漫画压缩包、视频文件等）。
        tag: 用于同一个源文件生成多种缩略图时区分缓存 key（默认空）。

    Returns:
        str: 缩略图的目标 .webp 路径（基于 src_path+tag 的哈希文件名）。
    """
    key = hashlib.sha1((os.path.abspath(src_path) + "|" + tag).encode("utf-8")).hexdigest()
    return os.path.join(_THUMB_DIR, key + ".webp")


# 现算封面这一下（对短视频来说是真的开一个 ffmpeg 子进程抽一帧）不限并发的话，一页 60 个
# 缩略图全没缓存过时，浏览器几乎同时发出 60 个请求，ThreadingHTTPServer 每个请求一个线程，
# 等于瞬间拉起 60 个 ffmpeg——CPU 直接打满（切几下标签就看到一堆 ffmpeg 进程，根源在这）。
# 用一个信号量把"现算封面"这一步的并发压到一个小数目，其余请求排队等，缩略图会一张一张
# 陆续冒出来而不是卡成一坨，manga（读压缩包，本来就快）也顺带受益。
_THUMB_GEN_SEM = threading.Semaphore(3)


def get_or_make_thumb(src_path: str, cover_bytes_fn, max_w: int = 360, tag: str = "") -> str | None:
    """拿到 src_path 的封面缩略图路径，没缓存或源文件更新了就现算一份。

    Args:
        src_path: 原始文件路径。
        cover_bytes_fn: 0 参回调，返回封面图片的原始字节；延迟到真需要生成时才调用
            （避免命中缓存时还要白白开一次压缩包/跑一次 ffmpeg）。
        max_w: 缩略图最大宽度，超过会等比缩小。
        tag: 同一个源文件生成多种缩略图时用于区分缓存 key。

    Returns:
        str | None: 缩略图文件路径；cover_bytes_fn() 没拿到数据或生成失败时返回 None。
    """
    tp = thumb_path(src_path, tag)
    try:
        st_src = os.stat(src_path)
        if os.path.exists(tp) and os.stat(tp).st_mtime >= st_src.st_mtime:
            return tp
    except OSError:
        return tp if os.path.exists(tp) else None

    with _THUMB_GEN_SEM:
        # 排队等锁的这段时间里，可能已经被另一个线程（同一张图被并发请求了好几次）做完了
        try:
            if os.path.exists(tp) and os.stat(tp).st_mtime >= os.stat(src_path).st_mtime:
                return tp
        except OSError:
            pass
        try:
            raw = cover_bytes_fn()
            if not raw:
                return None
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            if im.width > max_w:
                h = max(1, round(im.height * max_w / im.width))
                im = im.resize((max_w, h), Image.LANCZOS)
            tmp = tp + ".tmp"
            im.save(tmp, "WEBP", quality=78, method=4)
            os.replace(tmp, tp)
            return tp
        except Exception as e:
            print(f"[media_index] 生成缩略图失败 {os.path.basename(src_path)}: {e}")
            return None


# ---------------- 通用差量扫描 ----------------

_BUILDING: set = set()       # 正在后台补索引的 kind —— 同一个 kind 只跑一个后台线程
_BUILD_LOCK = threading.Lock()
_LAST_PRUNE: dict = {}       # kind -> ts，prune 不用每次都跑


def diff_scan(kind: str, files: list, parse_one, sync_limit: int = 24,
              on_progress=None):
    """对某个 kind 做一次"索引命中就用缓存，没命中才真解析"的差量扫描。

    缓存命中的文件直接用索引里的 meta，不开文件；没命中的文件里，头 sync_limit
    个同步解析（保证接口不用无限等），剩下的交给一个单例后台线程慢慢补齐并写回索引，
    同一个 kind 同时只有一个后台线程在跑，期间再次调用只会顺手多同步解析几个。

    Args:
        kind: 媒体类型（如 "manga"/"audio"）。
        files: 当前磁盘上的文件列表，每项是 (path, mtime, size)。
        parse_one: 真正解析单个文件的回调，签名 (path) -> meta_dict。
        sync_limit: 未命中缓存时，本次调用最多同步解析多少个文件。
        on_progress: 可选进度回调，签名 (done, total)，由后台补齐线程调用。

    Returns:
        dict: {path: meta_dict}，缓存命中的和本次同步解析到的都在里面；后台线程
        还没补完的那部分本次调用拿不到，等下次调用/刷新时才会出现。
    """
    idx = load_kind(kind)
    result = {}
    stale = []
    for path, mtime, size in files:
        hit = idx.get(path)
        if hit and abs(hit["mtime"] - mtime) < 1e-6 and hit["size"] == size:
            result[path] = hit["meta"]
        else:
            stale.append((path, mtime, size))

    # prune 不必每次跑：只在有变动、或距上次 >60s 时做
    now = time.time()
    if stale or (now - _LAST_PRUNE.get(kind, 0)) > 60:
        prune(kind, {f[0] for f in files})
        _LAST_PRUNE[kind] = now

    if not stale:
        return result

    def _parse(one):
        """解析一个 (path, mtime, size) 元组，返回可直接喂给 put_many() 的一行记录。"""
        path, mtime, size = one
        try:
            m = parse_one(path) or {}
        except Exception as e:
            print(f"[media_index] parse_one 失败 {os.path.basename(path)}: {e}")
            m = {}
        return (path, kind, float(mtime), int(size), m)

    # 已经有后台线程在补这个 kind 了 —— 不再动，返回目前能给的
    with _BUILD_LOCK:
        building = kind in _BUILDING
        if not building and len(stale) > sync_limit:
            _BUILDING.add(kind)
    if building:
        # 顺手同步解析很少量，让界面每次刷新都能多冒出来几个
        for one in stale[:8]:
            row = _parse(one)
            put_many([row])
            result[row[0]] = row[4]
        return result

    head, tail = stale[:sync_limit], stale[sync_limit:]
    head_rows = [_parse(one) for one in head]
    put_many(head_rows)
    for row in head_rows:
        result[row[0]] = row[4]

    if tail:
        def _bg():
            """后台把 tail 里剩下的文件慢慢解析完，每 25 条落一次盘并汇报一次进度。"""
            try:
                total, done, batch = len(stale), len(head), []
                for one in tail:
                    batch.append(_parse(one))
                    done += 1
                    if len(batch) >= 25:
                        put_many(batch); batch.clear()
                        if on_progress:
                            try: on_progress(done, total)
                            except Exception: pass
                if batch:
                    put_many(batch)
                if on_progress:
                    try: on_progress(total, total)
                    except Exception: pass
            finally:
                with _BUILD_LOCK:
                    _BUILDING.discard(kind)
        threading.Thread(target=_bg, name=f"media-index-{kind}", daemon=True).start()
    else:
        with _BUILD_LOCK:
            _BUILDING.discard(kind)

    return result
