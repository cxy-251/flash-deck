"""局域网小工具：文件传输（共享文件夹 + 分块断点续传上传）与消息板（跨设备传文字）。

共享文件夹 = 资源库键 media.shared（<库根>/media_library/shared/）。列表合并所有在线库里的这个目录，
磁盘就是数据源：网页传上来的、直接拷进去的都算；新上传的写进默认库。

分块上传（大文件、断点续传）：
    create(name, size, mtime)   同一个文件（名字 + 大小 + 修改时间）有没传完的就接着用，返回已收到的字节数
    write_chunk(id, offset, …)  offset 必须等于已收到的字节数，边读边追加写进 .omni-uploads/<id>.part，
                                内存占用固定；连接中途断了，收到多少算多少，客户端问一下进度接着发
    收满 → 改名移进共享文件夹（同名自动改成「名字 (1).ext」，不覆盖）
每块默认 8MB：经 Cloudflare 转发时单个请求上限 100MB，手机上断了重传一块的代价也小。
未完成上传的登记在 var/data/transfer_uploads.json；放弃一个上传 = .part 移到回收站（gio trash）。

消息板：发文字 / 链接，所有设备通过 SSE 实时收到，存盘（重启还在），最多留 MAX_TEXTS 条。
"""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional

from omni.core import events, library, paths

KEY = "media.shared"
PART_DIR = ".omni-uploads"          # 放在共享文件夹里（同一个文件系统，收满后改名是原子操作）
CHUNK_SIZE = 8 * 1024 * 1024
READ_SIZE = 1024 * 1024
FREE_MARGIN = 256 * 1024 * 1024     # 上传前留给系统的余量
MAX_TEXTS = 200
MAX_TEXT_LEN = 100_000

_lock = threading.RLock()
_upload_locks: Dict[str, threading.Lock] = {}


def _notify(what: str, **extra) -> None:
    events.broadcast({"type": "transfer", "what": what, **extra})


# ---------------------------------------------------------------- 文件名

def safe_name(name: str) -> Optional[str]:
    """浏览器给的文件名 → 能安全落盘的名字；不行返回 None。
    去掉路径部分和控制字符；开头的点去掉（隐藏文件不出现在列表里）；按 UTF-8 截到 200 字节内。"""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip().lstrip(".").strip()
    if not name:
        return None
    while len(name.encode("utf-8")) > 200:
        stem, ext = os.path.splitext(name)
        name = (stem[:-1] + ext) if stem else name[:-1]
    return name or None


def _unique_path(directory: str, name: str) -> str:
    """同名不覆盖：名字 (1).ext、名字 (2).ext ……"""
    stem, ext = os.path.splitext(name)
    candidate, n = os.path.join(directory, name), 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem} ({n}){ext}")
        n += 1
    return candidate


# ---------------------------------------------------------------- 共享文件夹

def write_dir() -> str:
    """新上传写到默认库的共享文件夹（不存在就建）。"""
    d = library.primary(KEY)
    os.makedirs(d, exist_ok=True)
    return d


def _dirs() -> List[str]:
    return library.dirs(KEY)


def list_files() -> List[Dict[str, Any]]:
    """所有库的共享文件夹里的文件（不含子目录和隐藏文件），新的在前；多个库里同名的只算第一个。"""
    seen, out = set(), []
    for d in _dirs():
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(".") or e.name in seen:
                continue
            try:
                if not e.is_file():
                    continue
                st = e.stat()
            except OSError:
                continue
            seen.add(e.name)
            out.append({"name": e.name, "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out


def find_file(name: str) -> Optional[str]:
    """文件名 → 绝对路径（只认共享文件夹顶层的普通文件，挡掉 ../ 之类）。"""
    if not name or name != os.path.basename(name) or name.startswith("."):
        return None
    for d in _dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def trash_files(names: List[str]) -> List[str]:
    """移到回收站（gio trash），返回成功的文件名。"""
    done = []
    for name in names:
        p = find_file(name)
        if p and subprocess.run(["gio", "trash", p], capture_output=True).returncode == 0:
            done.append(name)
    if done:
        _notify("files")
    return done


def stream_zip(names: List[str], out) -> None:
    """多选打包下载：不压缩、边打包边写给浏览器（不占内存、不落临时文件）。
    out 是不能 seek 的 socket，zipfile 会改用数据描述符；预先给出文件大小，超过 4GB 的自动用 zip64。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for name in names:
            p = find_file(name)
            if not p:
                continue
            st = os.stat(p)
            info = zipfile.ZipInfo(name, time.localtime(st.st_mtime)[:6])
            info.file_size = st.st_size
            with open(p, "rb") as src, zf.open(info, "w", force_zip64=st.st_size >= 0xFFFFFFFF) as dst:
                shutil.copyfileobj(src, dst, READ_SIZE)


# ---------------------------------------------------------------- 分块上传

def _load_uploads() -> Dict[str, Dict[str, Any]]:
    try:
        with open(paths.TRANSFER_UPLOADS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_uploads(data: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(paths.TRANSFER_UPLOADS), exist_ok=True)
    tmp = paths.TRANSFER_UPLOADS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, paths.TRANSFER_UPLOADS)


def _received(up: Dict[str, Any]) -> int:
    try:
        return os.path.getsize(up["part"])
    except OSError:
        return 0


def _public(up: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": up["id"], "name": up["name"], "size": up["size"], "offset": _received(up),
            "created": up.get("created", 0), "chunk": CHUNK_SIZE}


def list_uploads() -> List[Dict[str, Any]]:
    with _lock:
        ups = _load_uploads()
    return sorted((_public(u) for u in ups.values()), key=lambda u: u["created"], reverse=True)


def get_upload(upload_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        up = _load_uploads().get(upload_id)
    return _public(up) if up else None


def create_upload(name: str, size: int, mtime: int, client: str = "") -> Dict[str, Any]:
    """开始（或接着）一个上传。同一个文件 = 名字 + 大小 + 修改时间都一样，返回它已收到的进度。
    出错抛 ValueError（文件名不行 / 空间不够），消息给前端直接显示。"""
    clean = safe_name(name)
    if not clean:
        raise ValueError("文件名无效")
    if size < 0:
        raise ValueError("文件大小无效")
    key = hashlib.sha1(f"{name}\0{size}\0{mtime}".encode("utf-8")).hexdigest()
    with _lock:
        ups = _load_uploads()
        for up in ups.values():
            if up.get("key") == key and os.path.isdir(os.path.dirname(up["part"])):
                return _public(up)
        d = write_dir()
        if shutil.disk_usage(d).free < size + FREE_MARGIN:
            raise ValueError(f"空间不够：剩余 {shutil.disk_usage(d).free // (1024 * 1024)} MB")
        part_dir = os.path.join(d, PART_DIR)
        os.makedirs(part_dir, exist_ok=True)
        upload_id = secrets.token_hex(8)
        up = {"id": upload_id, "key": key, "name": clean, "size": size, "client": client[:32],
              "part": os.path.join(part_dir, upload_id + ".part"), "created": time.time()}
        open(up["part"], "wb").close()
        ups[upload_id] = up
        _save_uploads(ups)
    if size == 0:
        _finish(upload_id)
    return _public(up)


def write_chunk(upload_id: str, offset: int, length: int, rfile) -> Dict[str, Any]:
    """从 rfile 读 length 字节追加到 .part。offset 对不上已收到的字节数就不写，返回实际进度让客户端对齐。
    返回 {"offset": 收到的字节数, "done": 是否收满, "name": 落盘的文件名（收满时）}；没有这个上传抛 KeyError。"""
    with _lock:
        up = _load_uploads().get(upload_id)
        if not up:
            raise KeyError(upload_id)
        lock = _upload_locks.setdefault(upload_id, threading.Lock())
    with lock:
        have = _received(up)
        if offset != have or length < 0 or have + length > up["size"]:
            _drain(rfile, length)
            return {"offset": have, "done": False, "mismatch": True}
        left = length
        with open(up["part"], "ab") as f:
            while left > 0:
                buf = rfile.read(min(READ_SIZE, left))
                if not buf:          # 连接断了：收到多少算多少
                    break
                f.write(buf)
                left -= len(buf)
        have = _received(up)
        if have >= up["size"]:
            return {"offset": have, "done": True, "name": _finish(upload_id)}
        return {"offset": have, "done": False}


def _drain(rfile, length: int) -> None:
    """不要的请求体也读完，免得连接上残留数据。"""
    while length > 0:
        buf = rfile.read(min(READ_SIZE, length))
        if not buf:
            break
        length -= len(buf)


def _finish(upload_id: str) -> Optional[str]:
    """收满：.part 改名移进共享文件夹（同名自动改名），从登记里拿掉。"""
    with _lock:
        ups = _load_uploads()
        up = ups.pop(upload_id, None)
        if not up:
            return None
        target = _unique_path(os.path.dirname(os.path.dirname(up["part"])), up["name"])
        os.replace(up["part"], target)
        _save_uploads(ups)
        _upload_locks.pop(upload_id, None)
    name = os.path.basename(target)
    _notify("files", added=name, client=up.get("client", ""))   # client：发起的那个页面，它自己不弹「收到文件」
    return name


def cancel_upload(upload_id: str) -> bool:
    """放弃一个没传完的上传：.part 移到回收站。"""
    with _lock:
        ups = _load_uploads()
        up = ups.get(upload_id)
        if not up:
            return False
        if os.path.exists(up["part"]) and \
                subprocess.run(["gio", "trash", up["part"]], capture_output=True).returncode != 0:
            return False        # 没移成就别丢登记，不然 .part 成了没人管的孤儿
        ups.pop(upload_id)
        _save_uploads(ups)
        _upload_locks.pop(upload_id, None)
    _notify("uploads")
    return True


# ---------------------------------------------------------------- 消息板

def _load_texts() -> List[Dict[str, Any]]:
    try:
        with open(paths.TRANSFER_TEXTS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_texts(items: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(paths.TRANSFER_TEXTS), exist_ok=True)
    tmp = paths.TRANSFER_TEXTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, paths.TRANSFER_TEXTS)


def list_texts() -> List[Dict[str, Any]]:
    with _lock:
        return _load_texts()


def add_text(text: str, sender: str = "", client: str = "") -> Dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        raise ValueError("内容为空")
    if len(text) > MAX_TEXT_LEN:
        raise ValueError(f"太长了（最多 {MAX_TEXT_LEN} 字）")
    item = {"id": secrets.token_hex(6), "text": text, "time": time.time(), "from": sender[:40]}
    with _lock:
        items = [item] + _load_texts()
        _save_texts(items[:MAX_TEXTS])
    _notify("texts", added=item["id"], client=client[:32])
    return item


def delete_text(text_id: str) -> bool:
    with _lock:
        items = _load_texts()
        keep = [t for t in items if t.get("id") != text_id]
        if len(keep) == len(items):
            return False
        _save_texts(keep)
    _notify("texts")
    return True
