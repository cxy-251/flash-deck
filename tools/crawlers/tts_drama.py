#!/usr/bin/env python3
"""
文本 → 多角色广播剧（微软 Edge Neural 语音 + ffmpeg 拼接为带标签的 mp3）。

两种输入：
  --script 剧本.json   已分好角色的剧本：
        [{"title": "第01回", "segments": [["narrator", "……"], ["角色A", "……"]]}, ...]
  --text 小说.txt      纯文本：按角色配置里的 keywords 识别「某人说“……”」，引号内台词给该角色，其余给旁白

角色配置（--roles roles.json，缺省只有旁白）：
  {"narrator": {"voice": "zh-CN-YunjianNeural", "rate": "-2%", "pitch": "-2Hz"},
   "角色A":    {"voice": "zh-CN-YunxiNeural", "keywords": ["角色A", "别名"], "rate": "+2%"}}

例：
  tts_drama.py --script 剧本.json --roles 角色.json --album "自制广播剧"
  tts_drama.py --text 第一章.txt --title "第01回" --roles 角色.json --album "自制广播剧"
输出到默认资源库 media_library/audio/<standard|nsfw>/<专辑>/<标题>.mp3，已存在的集跳过（--force 重做）。
"""
import asyncio
import json
import os
import re
import subprocess
import tempfile

import _common as c

DEFAULT_ROLES = {"narrator": {"voice": "zh-CN-YunjianNeural", "rate": "-2%", "pitch": "-2Hz"}}
QUOTE_RE = re.compile(r'“([^”]+)”|"([^"]+)"')


def load_roles(path):
    roles = dict(DEFAULT_ROLES)
    if path:
        with open(path, "r", encoding="utf-8") as f:
            roles.update(json.load(f))
    return roles


def parse_text(raw: str, roles: dict) -> list:
    """纯文本 -> [(角色, 文本)]：行内出现某角色关键词且带引号台词时，台词归该角色，其余旁白。"""
    segments = []
    for line in (l.strip() for l in raw.splitlines()):
        if not line:
            continue
        speaker = next((name for name, r in roles.items()
                        if name != "narrator" and any(k in line for k in r.get("keywords", []))), None)
        quotes = QUOTE_RE.findall(line) if speaker else []
        if quotes:
            narr = QUOTE_RE.sub("", line).strip()
            if narr:
                segments.append(("narrator", narr))
            segments.append((speaker, quotes[0][0] or quotes[0][1]))
        else:
            segments.append(("narrator", line))
    return segments


async def synth(text: str, role: dict, out_file: str):
    import edge_tts
    await edge_tts.Communicate(text, role["voice"], rate=role.get("rate", "+0%"),
                               pitch=role.get("pitch", "+0Hz")).save(out_file)


async def make_episode(ep: dict, roles: dict, album: str, out_dir: str, bitrate: str) -> str:
    title = ep["title"]
    out_mp3 = os.path.join(out_dir, c.safe_name(title) + ".mp3")
    segs = ep["segments"]
    print(f"\n🎙️ 《{album}》{title}（{len(segs)} 段）")
    with tempfile.TemporaryDirectory(prefix="omni_tts_") as tmp:
        files = []
        for i, (role_name, text) in enumerate(segs):
            role = roles.get(role_name) or roles["narrator"]
            f = os.path.join(tmp, f"seg_{i:04d}.mp3")
            print(f"   [{i + 1}/{len(segs)}] {role_name}: {text[:24]}…")
            await synth(text, role, f)
            files.append(f)
            await asyncio.sleep(0.1)       # 避免触发频率限制
        concat = os.path.join(tmp, "concat.txt")
        with open(concat, "w", encoding="utf-8") as fh:
            fh.writelines(f"file '{p}'\n" for p in files)
        res = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
                              "-c:a", "libmp3lame", "-b:a", bitrate,
                              "-metadata", f"title={title}", "-metadata", f"album={album}",
                              "-metadata", "genre=Audiobook", out_mp3], capture_output=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.decode("utf-8", "ignore")[-500:])
    print(f"✅ {out_mp3}（{os.path.getsize(out_mp3) // 1024} KB）")
    return out_mp3


def main():
    p = c.parser("文本 / 剧本 → 多角色广播剧 mp3")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--script", help="已分角色的剧本 JSON")
    src.add_argument("--text", help="纯文本文件（按角色关键词自动分配台词）")
    p.add_argument("--title", help="--text 模式的单集标题（缺省用文件名）")
    p.add_argument("--roles", help="角色 → 音色配置 JSON")
    p.add_argument("--album", required=True, help="专辑名")
    p.add_argument("--nsfw", action="store_true", help="存到 audio/nsfw")
    p.add_argument("--episodes", default="", help="只生成剧本里的这些集，如 1-3")
    p.add_argument("--bitrate", default="64k")
    p.add_argument("--force", action="store_true", help="已存在也重新生成")
    args = p.parse_args()

    c.need("ffmpeg")
    roles = load_roles(args.roles)
    if args.script:
        with open(args.script, "r", encoding="utf-8") as f:
            episodes = json.load(f)
    else:
        with open(args.text, "r", encoding="utf-8") as f:
            episodes = [{"title": args.title or os.path.splitext(os.path.basename(args.text))[0],
                         "segments": parse_text(f.read(), roles)}]
    wanted = c.parse_ranges(args.episodes)
    out_dir = c.library.primary(c.audio_key(args.nsfw), args.album)
    os.makedirs(out_dir, exist_ok=True)
    for i, ep in enumerate(episodes, 1):
        if wanted and i not in wanted:
            continue
        name = c.safe_name(ep["title"]) + ".mp3"
        if not args.force and c.find_existing(c.audio_key(args.nsfw), args.album, name):
            print(f"✅ 已存在，跳过：{name}")
            continue
        asyncio.run(make_episode(ep, roles, args.album, out_dir, args.bitrate))


if __name__ == "__main__":
    main()
