#!/usr/bin/env python3
"""
伪装压缩包游戏还原工具

一些站点把游戏本体伪装成 .mp4/.mkv 视频文件分发（避开平台的压缩包/可执行文件检测），
真实内容是拼接/嵌套在视频容器尾部的加密 7z 包。这个脚本负责把伪装文件解密还原成正常能玩
的游戏文件夹：

- mp4 伪装：视频文件尾部直接拼了一个 zip64 格式的 7z 包（靠 EOCD 记录定位，从中间往回找
  压缩包起始位置，再挑出里面打包过一层 tar 的真正 7z）
- mkv 伪装：反过来，先用 7z 把外层"当作压缩包"解开拿到一个 tar，tar 里面才是真正的 7z

两种最终都走同一步：拿到内层 7z 后用密码解密到临时目录，识别出唯一顶层文件夹（或者原样
整棵目录树），挪到目标游戏专区下 <category>_games/<name>，清理广告 .url 文件，给
Linux 可执行文件补上执行权限。

用法（下载中心 UI 调用，也可以直接命令行跑）：
    archive_unpack.py --source /path/to/伪装文件.mp4 --category renpy --name "043 - New Game Title"
解压密码默认取 var/config/settings.json 的 archive_extract_password，可用 --password 覆盖；
--type 缺省按扩展名判断。
"""
import os
import sys
import glob
import zlib
import struct
import shutil
import tempfile
import subprocess

import _common as c
from _common import library, settings

PASSWORD = None   # main() 里按 --password / settings 设置

# 目标专区 = 资源库骨架里的游戏分类（games.<分类>）
VALID_CATEGORIES = tuple(k.split(".", 1)[1] for k in library.LAYOUT if k.startswith("games."))


def trash_path(path: str) -> None:
    """按项目铁律用 gio trash 安全删除，不用 rm（可在回收站找回）。"""
    if os.path.exists(path):
        print(f"Trashing: {path}")
        c.trash(path)


def extract_7z_from_mp4(mp4_path: str, out_7z_path: str) -> str:
    """从伪装成 mp4 的文件尾部，靠 zip64 EOCD 记录定位并流式抽出内层打包过 tar 的 7z 文件。

    Args:
        mp4_path: 伪装 mp4 文件路径。
        out_7z_path: 抽取出的 7z 文件写到哪。

    Returns:
        str: 内层 tar 里那个 7z/zip 条目的原始文件名（仅供日志展示）。

    Raises:
        ValueError: 文件尾部找不到合法的 zip64 记录，或 tar 里没有 7z/zip 条目。
    """
    size = os.path.getsize(mp4_path)
    print(f"Reading {mp4_path} ({size} bytes)...")
    with open(mp4_path, 'rb') as f:
        f.seek(max(0, size - 65536))
        tail = f.read()
        loc_idx = tail.rfind(b'PK\x06\x07')
        z64_idx = tail.rfind(b'PK\x06\x06')
        if loc_idx == -1 or z64_idx == -1:
            raise ValueError(f"Not a valid zip64 payload in {mp4_path}")
        z64_eocd_offset = struct.unpack('<Q', tail[loc_idx+8:loc_idx+16])[0]
        actual_z64_pos = max(0, size - 65536) + z64_idx
        zip_start = actual_z64_pos - z64_eocd_offset
        cd_size, cd_offset = struct.unpack('<QQ', tail[z64_idx+40:z64_idx+56])
        f.seek(zip_start + cd_offset)
        cd_entry = f.read(46)
        fn_len, extra_len, comment_len = struct.unpack('<HHH', cd_entry[28:34])
        lho = struct.unpack('<I', cd_entry[42:46])[0]
        f.seek(zip_start + cd_offset + 46)
        extra = f.read(extra_len)
        if lho == 0xFFFFFFFF:
            idx = 0
            while idx < len(extra):
                tag, sz = struct.unpack('<HH', extra[idx:idx+4])
                if tag == 0x0001:
                    lho = struct.unpack('<Q', extra[idx+4+16:idx+4+24])[0]
                    break
                idx += 4 + sz
        f.seek(zip_start + lho)
        lfh = f.read(30)
        l_fn_len, l_extra_len = struct.unpack('<HH', lfh[26:30])
        data_start = zip_start + lho + 30 + l_fn_len + l_extra_len
        f.seek(data_start)

        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        tar_buf = bytearray()
        target_size = None
        target_name = None

        while target_size is None:
            raw = f.read(65536)
            if not raw:
                break
            tar_buf.extend(decompressor.decompress(raw))
            pos = 0
            while pos + 512 <= len(tar_buf):
                hdr = tar_buf[pos:pos+512]
                if hdr == b'\x00' * 512:
                    pos += 512
                    continue
                name = hdr[:100].split(b'\x00')[0].decode('utf-8', errors='replace')
                typeflag = chr(hdr[156]) if hdr[156] else '0'
                try:
                    entry_size = int(hdr[124:136].strip(b'\x00 ').decode(), 8)
                except Exception:
                    entry_size = 0
                pos += 512
                if typeflag == '0' and (name.endswith('.7z') or name.endswith('.zip')):
                    target_name = name
                    target_size = entry_size
                    tar_buf = tar_buf[pos:]
                    break
                else:
                    pos += ((entry_size + 511) // 512) * 512
                    if pos > len(tar_buf):
                        tar_buf = tar_buf[pos-((entry_size + 511) // 512) * 512 - 512:]
                        break

        if not target_name or target_size is None:
            raise ValueError(f"Could not find 7z entry inside {mp4_path}")

        print(f"Streaming inner {target_name} ({target_size} bytes) -> {out_7z_path}...")
        bytes_written = 0
        with open(out_7z_path, 'wb') as out_f:
            if len(tar_buf) > 0:
                to_write = min(len(tar_buf), target_size)
                out_f.write(tar_buf[:to_write])
                bytes_written += to_write
            while bytes_written < target_size:
                raw = f.read(1024 * 1024)
                if not raw:
                    break
                decomp = decompressor.decompress(raw)
                to_write = min(len(decomp), target_size - bytes_written)
                out_f.write(decomp[:to_write])
                bytes_written += to_write
        print(f"Extraction complete: {bytes_written} bytes written.")
        return target_name


def _finalize_unpacked_dir(tmp_unpacked: str, final_path: str) -> None:
    """把临时解包目录挪到最终目标位置：只有单一顶层文件夹就直接挪那个文件夹，
    否则整棵临时目录原样改名过去；再清理广告 .url 文件、给可执行文件补执行权限。

    Args:
        tmp_unpacked: 7z 解包后的临时目录。
        final_path: 最终游戏文件夹的目标路径（<category>_games/<name>）。
    """
    if os.path.exists(final_path):
        trash_path(final_path)

    entries = os.listdir(tmp_unpacked)
    if len(entries) == 1 and os.path.isdir(os.path.join(tmp_unpacked, entries[0])):
        single_dir = os.path.join(tmp_unpacked, entries[0])
        print(f"Moving {single_dir} -> {final_path}")
        shutil.move(single_dir, final_path)
        trash_path(tmp_unpacked)
    else:
        print(f"Moving entire unpacked tree -> {final_path}")
        shutil.move(tmp_unpacked, final_path)

    if not os.path.exists(final_path):
        return
    for ad in glob.glob(os.path.join(final_path, "**", "*.url"), recursive=True):
        trash_path(ad)
    for sh in glob.glob(os.path.join(final_path, "*.sh")):
        try:
            os.chmod(sh, 0o755)
        except OSError:
            pass
    for exe in glob.glob(os.path.join(final_path, "*.x86_64")):
        try:
            os.chmod(exe, 0o755)
        except OSError:
            pass


def process_mp4_item(src_mp4: str, target_cat_dir: str, final_folder_name: str) -> None:
    """处理一个伪装成 mp4 的游戏压缩包：抽取内层 7z、密码解压、挪到最终目录、清理善后。

    Args:
        src_mp4: 伪装 mp4 文件路径。
        target_cat_dir: 目标专区目录（如 .../standalone_games/renpy_games）。
        final_folder_name: 解压后最终的游戏文件夹名（如 "043 - New Game Title"）。
    """
    print("\n==================================================")
    print(f"Processing: {src_mp4} -> {final_folder_name}")
    print("==================================================")

    stage_dir = tempfile.mkdtemp(prefix=".process_archives_", dir=os.path.dirname(src_mp4))
    try:
        tmp_7z = os.path.join(stage_dir, "stage.7z")

        # 1. 从 mp4 尾部流式抽出内层 7z
        extract_7z_from_mp4(src_mp4, tmp_7z)

        # 2. 立刻回收源 mp4 文件释放磁盘空间
        trash_path(src_mp4)

        # 3. 密码解压 7z 到临时目录
        tmp_unpacked = os.path.join(stage_dir, "unpacked")
        os.makedirs(tmp_unpacked, exist_ok=True)
        print(f"Extracting {tmp_7z} to {tmp_unpacked}...")
        res = subprocess.run(["7z", "x", f"-p{PASSWORD}", f"-o{tmp_unpacked}", tmp_7z], stdout=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError(f"7z extraction failed with code {res.returncode}")

        # 4. 挪到最终目标目录并清理善后
        final_path = os.path.join(target_cat_dir, final_folder_name)
        _finalize_unpacked_dir(tmp_unpacked, final_path)
        print(f"SUCCESS: {final_folder_name} completed!")
    finally:
        trash_path(stage_dir)


def process_mkv_item(src_mkv: str, target_cat_dir: str, final_folder_name: str) -> None:
    """处理一个伪装成 mkv 的游戏压缩包：外层 7z 解出 tar，tar 里再找真正的 7z，密码解压、
    挪到最终目录、清理善后。

    Args:
        src_mkv: 伪装 mkv 文件路径。
        target_cat_dir: 目标专区目录（如 .../standalone_games/renpy_games）。
        final_folder_name: 解压后最终的游戏文件夹名。
    """
    print("\n==================================================")
    print(f"Processing MKV: {src_mkv} -> {final_folder_name}")
    print("==================================================")

    stage_dir = tempfile.mkdtemp(prefix=".process_archives_", dir=os.path.dirname(src_mkv))
    try:
        tmp_dir = os.path.join(stage_dir, "outer")
        os.makedirs(tmp_dir, exist_ok=True)

        # 1. 外层解出 tar
        print(f"Extracting inner tar from {src_mkv}...")
        res = subprocess.run(["7z", "x", f"-p{PASSWORD}", f"-o{tmp_dir}", src_mkv], stdout=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError(f"MKV 7z outer extract failed with code {res.returncode}")

        # 2. 立刻回收源 mkv 文件释放磁盘空间
        trash_path(src_mkv)

        # 3. tar 里找真正的 7z
        inner_7zs = glob.glob(os.path.join(tmp_dir, "**", "*.7z"), recursive=True)
        if not inner_7zs:
            raise RuntimeError(f"No inner 7z found in {tmp_dir}")
        inner_7z = inner_7zs[0]

        # 4. 密码解压内层 7z
        tmp_unpacked = os.path.join(stage_dir, "unpacked")
        os.makedirs(tmp_unpacked, exist_ok=True)
        print(f"Extracting {inner_7z} to {tmp_unpacked}...")
        res = subprocess.run(["7z", "x", f"-p{PASSWORD}", f"-o{tmp_unpacked}", inner_7z], stdout=subprocess.DEVNULL)
        if res.returncode != 0:
            raise RuntimeError(f"Inner 7z extract failed with code {res.returncode}")

        # 5. 挪到最终目标目录并清理善后
        final_path = os.path.join(target_cat_dir, final_folder_name)
        _finalize_unpacked_dir(tmp_unpacked, final_path)
        print(f"SUCCESS: {final_folder_name} completed!")
    finally:
        trash_path(stage_dir)


def main() -> None:
    """命令行入口：把伪装 mp4/mkv 还原成 <category>_games/<name> 下的游戏文件夹。"""
    global PASSWORD
    parser = c.parser("伪装压缩包游戏还原")
    parser.add_argument("--source", required=True, help="伪装文件的完整路径")
    parser.add_argument("--type", choices=("mp4", "mkv"), help="伪装容器类型（缺省按扩展名判断）")
    parser.add_argument("--category", required=True, choices=VALID_CATEGORIES,
                        help="目标游戏分类，对应资源库的 <category>_games 目录")
    parser.add_argument("--name", required=True, help="还原后的游戏文件夹名，如 \"043 - New Game Title\"")
    parser.add_argument("--password", default=None, help="解压密码（缺省取 settings 的 archive_extract_password）")
    args = parser.parse_args()

    source = os.path.expanduser(args.source)
    if not os.path.exists(source):
        sys.exit(f"❌ 源文件不存在: {source}")
    kind = args.type or os.path.splitext(source)[1].lower().lstrip(".")
    if kind not in ("mp4", "mkv"):
        sys.exit("❌ 无法从扩展名判断容器类型，请用 --type mp4|mkv 指定")
    c.need("7z")
    PASSWORD = args.password or settings.get("archive_extract_password")

    target_cat_dir = library.primary(f"games.{args.category}")
    os.makedirs(target_cat_dir, exist_ok=True)
    (process_mp4_item if kind == "mp4" else process_mkv_item)(source, target_cat_dir, args.name)


if __name__ == '__main__':
    main()
