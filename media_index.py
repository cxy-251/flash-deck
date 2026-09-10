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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
_DB_PATH = os.path.join(_CACHE_DIR, "media_index.db")
_THUMB_DIR = os.path.join(_CACHE_DIR, "thumbs")
_SCHEMA_VERSION = 1

os.makedirs(_CACHE_DIR, exist_ok=True)
os.makedirs(_THUMB_DIR, exist_ok=True)

_LOCK = threading.RLock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
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
    _LOAD_CACHE.pop(kind, None)


def load_kind(kind: str, use_cache: bool = True) -> dict:
    """一次读回某类的全部索引：{path: {"mtime":..., "size":..., "meta": {...}}}"""
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
    """rows: [(path, kind, mtime, size, meta_dict), ...]"""
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
    """删掉磁盘上已不存在的条目。live_paths: 当前真实存在的 path 集合。返回删了几条。"""
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
    try:
        with _LOCK:
            r = _db().execute("SELECT COUNT(*) FROM media_meta WHERE kind=?", (kind,)).fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


# ---------------- 封面缩略图缓存 ----------------

def thumb_path(src_path: str, tag: str = "") -> str:
    key = hashlib.sha1((os.path.abspath(src_path) + "|" + tag).encode("utf-8")).hexdigest()
    return os.path.join(_THUMB_DIR, key + ".webp")


def get_or_make_thumb(src_path: str, cover_bytes_fn, max_w: int = 360, tag: str = "") -> str | None:
    """src_path 的封面缩略图路径。没有或源文件更新了就用 cover_bytes_fn() 现取封面二进制、
    压成 <=max_w 的 WebP 存下来。cover_bytes_fn 是个 0 参回调（延迟到真需要时才开压缩包）。"""
    tp = thumb_path(src_path, tag)
    try:
        st_src = os.stat(src_path)
        if os.path.exists(tp) and os.stat(tp).st_mtime >= st_src.st_mtime:
            return tp
    except OSError:
        return tp if os.path.exists(tp) else None
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
    """
    files: [(path, mtime, size), ...]  当前磁盘上的文件
    parse_one(path) -> meta_dict       真去解析一个文件（开压缩包等）的回调
    返回 {path: meta_dict}（缓存命中的全有；没命中的：同步解析头 sync_limit 个，
    其余交给**单例**后台线程慢慢补，期间再来的请求不会重复触发）。
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
