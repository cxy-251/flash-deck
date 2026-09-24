#!/usr/bin/env python3
"""
视频站音频 → 有声书（YouTube / Bilibili / 其它 yt-dlp 支持的站点）。

一个 URL 可以是单个视频、播放列表或 B 站多 P 视频，统一展开成「条目列表」再下载：
  --mode files  每个条目存成一个 m4a（默认）
  --mode m4b    全部条目合成一个带章节的 m4b（单个视频自带章节时用视频章节），并写 .chapters.json

例：
  media_fetch.py "https://www.youtube.com/playlist?list=XXXX" --album "某有声书"
  media_fetch.py "https://www.bilibili.com/video/BVxxxx" --album "广播剧" --items 1-6 --mode m4b
  media_fetch.py "https://youtu.be/AAA|第一部" "https://youtu.be/BBB|第二部" --album "某书"   # URL|文件名
文件写入默认资源库的 media_library/audio/<standard|nsfw>/<专辑>/；任何在线库里已有同名文件就跳过。
登录 Cookie / 代理默认取 var/config/crawler_secrets.json 的 ytdlp 段，也可用 --cookies / --proxy 覆盖。
"""
import json
import os
import subprocess
import tempfile
import time

import _common as c

AUDIO_EXTS = (".m4a", ".m4b", ".mp3", ".opus", ".aac")


def is_single_video(url: str) -> bool:
    """明显是单个视频（不是播放列表/多P）的链接：写了文件名时可以省掉一次 yt-dlp 解析（每次约几十秒）。"""
    u = url.lower()
    return (("youtube.com/watch" in u or "youtu.be/" in u) and "list=" not in u)


def expand(url: str, auth: list, items: set) -> list:
    """URL -> [(条目URL, 标题, 序号)]；播放列表/多P按 --items 过滤。"""
    res = subprocess.run(c.ytdlp_cmd() + ["--flat-playlist", "-J", "--socket-timeout", "60"] + auth + [url],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "yt-dlp 解析失败")
    info = json.loads(res.stdout)
    if info.get("_type") != "playlist":
        return [(url, info.get("title") or url, 1)]
    out = []
    for idx, e in enumerate(info.get("entries") or [], 1):
        if items and idx not in items:
            continue
        e_url = e.get("url") or e.get("webpage_url") or e.get("id")
        if e_url and not e_url.startswith("http") and "youtube" in (info.get("extractor") or "").lower():
            e_url = f"https://www.youtube.com/watch?v={e_url}"
        out.append((e_url, e.get("title") or f"{info.get('title', '')} P{idx}", idx))
    return out


def download(entry_url: str, out_base: str, fmt: str, auth: list, retries: int = 3) -> str:
    """下载单个条目的音频到 out_base.<ext>，返回实际文件路径。"""
    cmd = c.ytdlp_cmd() + ["-f", fmt, "-x", "--audio-format", "m4a", "--no-playlist", "--continue",
                           "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "60",
                           "-o", out_base + ".%(ext)s"] + auth + [entry_url]
    for attempt in range(1, retries + 1):
        res = subprocess.run(cmd, capture_output=True, text=True)
        for ext in AUDIO_EXTS:
            if res.returncode == 0 and os.path.exists(out_base + ext):
                return out_base + ext
        err = (res.stderr.strip().splitlines() or ["未知错误"])[-1]
        print(f"    重试 {attempt}/{retries}：{err}")
        if "Sign in to confirm" in res.stderr:
            print("    💡 YouTube 要求登录：在 crawler_secrets.json 的 ytdlp 里配置 cookies_file 或 cookies_from_browser")
        time.sleep(3)
    raise RuntimeError(f"下载失败：{entry_url}")


def probe_duration(path: str) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=noprint_wrappers=1:nokey=1", path], text=True)
    return float(out.strip() or 0)


def video_chapters(entry_url: str, auth: list) -> list:
    res = subprocess.run(c.ytdlp_cmd() + ["-J", "--no-playlist", "--socket-timeout", "60"] + auth + [entry_url],
                         capture_output=True, text=True)
    try:
        return json.loads(res.stdout).get("chapters") or []
    except ValueError:
        return []


def fmt_dur(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def run_files(entries, target_dir, args, auth):
    ok, failed = 0, []
    for n, (url, title, idx) in enumerate(entries, 1):
        name = c.safe_name(args.names.get(url) or args.name.format(title=title, index=idx, album=args.album))
        if any(c.find_existing(c.audio_key(args.nsfw), args.album, name + ext, min_bytes=args.min_mb * 1048576)
               for ext in AUDIO_EXTS):
            print(f"[{n}/{len(entries)}] ✅ 已存在，跳过：{name}")
            ok += 1
            continue
        print(f"[{n}/{len(entries)}] ⏬ {name}\n    {url}")
        t0 = time.time()
        try:
            path = download(url, os.path.join(target_dir, name), args.format, auth)
            print(f"    ✅ 完成 {os.path.getsize(path) / 1048576:.1f} MB，用时 {time.time() - t0:.0f}s")
            ok += 1
        except RuntimeError as e:
            print(f"    ❌ {e}")
            failed.append(name)
    print(f"\n📊 {ok}/{len(entries)} 成功" + (f"；失败：{', '.join(failed)}" if failed else ""))
    return not failed


def run_m4b(entries, target_dir, args, auth):
    out_name = c.safe_name(args.output or f"{args.album}.m4b")
    if not out_name.endswith(".m4b"):
        out_name += ".m4b"
    if c.find_existing(c.audio_key(args.nsfw), args.album, out_name, min_bytes=args.min_mb * 1048576):
        print(f"✅ 已存在，跳过：{out_name}")
        return True
    c.need("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="omni_m4b_", dir=target_dir) as tmp:
        parts = []
        for n, (url, title, idx) in enumerate(entries, 1):
            print(f"[{n}/{len(entries)}] ⏬ {title}")
            path = download(url, os.path.join(tmp, f"part_{n:03d}"), args.format, auth)
            parts.append((title, path, probe_duration(path)))

        chapters, t = [], 0.0
        if len(parts) == 1 and not args.no_video_chapters:
            for i, ch in enumerate(video_chapters(entries[0][0], auth), 1):
                st, et = float(ch.get("start_time", 0)), float(ch.get("end_time", parts[0][2]))
                chapters.append({"index": i, "title": ch.get("title") or f"第{i}回", "start": st, "end": et})
        if not chapters:
            for i, (title, _p, dur) in enumerate(parts, 1):
                chapters.append({"index": i, "title": title, "start": t, "end": t + dur})
                t += dur

        concat = os.path.join(tmp, "concat.txt")
        with open(concat, "w", encoding="utf-8") as f:
            for _t, p, _d in parts:
                f.write("file '%s'\n" % p.replace("'", "'\\''"))
        meta = os.path.join(tmp, "meta.txt")
        with open(meta, "w", encoding="utf-8") as f:
            f.write(f";FFMETADATA1\ntitle={args.album}\nalbum={args.album}\ngenre=有声书\n\n")
            for ch in chapters:
                f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(ch['start'] * 1000)}\nEND={int(ch['end'] * 1000)}\n"
                        f"title={ch['title']}\n\n")
        final = os.path.join(target_dir, out_name)
        base = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-i", meta, "-map_metadata", "1"]
        if subprocess.run(base + ["-c", "copy", "-movflags", "+faststart", final], capture_output=True).returncode != 0:
            subprocess.run(base + ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", final],
                           check=True, capture_output=True)
    with open(final.rsplit(".", 1)[0] + ".chapters.json", "w", encoding="utf-8") as f:
        json.dump([{**ch, "start": round(ch["start"], 2), "end": round(ch["end"], 2),
                    "duration_str": fmt_dur(ch["end"] - ch["start"])} for ch in chapters], f, ensure_ascii=False, indent=2)
    print(f"🎉 {final}（{os.path.getsize(final) / 1048576:.1f} MB，{len(chapters)} 个章节）")
    return True


def main():
    p = c.parser("视频站音频 → 有声书（逐条 m4a 或合成带章节的 m4b）")
    p.add_argument("urls", nargs="+", help="视频/播放列表/多P URL；可写成 URL|文件名 指定保存名")
    p.add_argument("--album", required=True, help="专辑名（= 音声画廊里的分类文件夹）")
    p.add_argument("--nsfw", action="store_true", help="存到 audio/nsfw（默认 audio/standard）")
    p.add_argument("--mode", choices=["files", "m4b"], default="files")
    p.add_argument("--items", default="", help="只取播放列表/多P 的这些序号，如 1-6,9")
    p.add_argument("--name", default="{title}", help="files 模式的文件名模板：{title} {index} {album}")
    p.add_argument("--output", default=None, help="m4b 模式的输出文件名（默认 <专辑>.m4b）")
    p.add_argument("--format", default="140/ba[ext=m4a]/ba", help="yt-dlp 格式选择")
    p.add_argument("--min-mb", type=float, default=1, help="已存在文件小于这个大小(MB)视为残缺，重新下载")
    p.add_argument("--cookies", default=None, help="cookies.txt 路径或浏览器名，覆盖 secrets 配置")
    p.add_argument("--proxy", default=None, help="代理地址，覆盖 secrets 配置")
    p.add_argument("--no-video-chapters", action="store_true", help="m4b 模式下不使用视频自带章节")
    p.add_argument("--dry-run", action="store_true", help="只列出将要下载的条目，不下载")
    args = p.parse_args()

    auth = c.ytdlp_auth_args(args.cookies, args.proxy)
    items = c.parse_ranges(args.items)
    args.names, entries = {}, []
    for spec in args.urls:
        url, _, name = spec.partition("|")
        if name.strip() and is_single_video(url):
            entries.append((url.strip(), name.strip(), 1))
            args.names[url.strip()] = name.strip()
            continue
        try:
            expanded = expand(url.strip(), auth, items)
        except RuntimeError as e:
            print(f"❌ 解析失败 {url}：{e}")
            continue
        if name and len(expanded) == 1:
            args.names[expanded[0][0]] = name.strip()
        entries += expanded
    if not entries:
        raise SystemExit("没有可下载的条目")
    target_dir = c.library.primary(c.audio_key(args.nsfw), args.album)
    if not args.dry_run:
        os.makedirs(target_dir, exist_ok=True)
    print(f"🎧 《{args.album}》共 {len(entries)} 个条目 → {target_dir}")
    if args.dry_run:
        for url, title, idx in entries:
            print(f"  {idx:>3}. {args.names.get(url) or title}  {url}")
        return
    ok = run_m4b(entries, target_dir, args, auth) if args.mode == "m4b" else run_files(entries, target_dir, args, auth)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
