#!/usr/bin/env python3
"""
安卓读书 App 的 APK 内置书库 → EPUB。

两种常见布局：
  --layout folders   <root>/<书>/ 下是章节 txt；有 <书>_essayfile.txt + <书>_essaytitle.txt
                     两个索引文件时按索引排章节，否则按文件名排序
  --layout files     <root>/ 下每个 txt 是一本书，按 --split 正则切章节（默认按「第X章/编/节」等）

例：
  apk_books.py --apk 世界名著.apk --root assets/book/世界名著 --folder 世界名著精选 --author 经典名著
  apk_books.py --apk 智谋.apk --root assets/book/中国智谋 --folder 中国智慧与谋略 --titles 书名映射.json
  apk_books.py --apk 法规.apk --root assets/book/alllaw --layout files --folder 中国法律法规 \\
               --keyword 宪法 --keyword 民法典 --min-chars 500
输出到默认资源库 media_library/novels/standard/<folder>/，已存在的书跳过。
"""
import json
import os
import re
import zipfile

import _common as c

INDEX_SUFFIXES = ("_essayfile.txt", "_essaytitle.txt", "_chapter.txt", "_chaptercount.txt", "_chapterindex.txt")
DEFAULT_SPLIT = r'^(第[一二三四五六七八九十百千\d]+[编章节部]|序言|总则|附则|前言)'


def open_apk(path):
    zf = zipfile.ZipFile(path, "r")
    names = {}
    for n in zf.namelist():
        try:
            names[n.encode("cp437").decode("utf-8")] = n      # 老 APK 里的中文文件名常是 cp437 误编码
        except (UnicodeEncodeError, UnicodeDecodeError):
            names[n] = n
    return zf, names


def read(zf, names, key):
    return zf.read(names[key]).decode("utf-8", errors="ignore")


def split_list(text):
    return [x.strip() for x in re.split(r"[\r\n,]+", text) if x.strip()]


def folder_books(zf, names, root):
    """[(书目录名, [章节])]"""
    root = root.rstrip("/") + "/"
    depth = root.count("/")
    books = sorted({k.split("/")[depth] for k in names if k.startswith(root) and len(k.split("/")) > depth + 1})
    for b in books:
        prefix = f"{root}{b}/"
        idx_f, idx_t = prefix + f"{b}_essayfile.txt", prefix + f"{b}_essaytitle.txt"
        chapters = []
        if idx_f in names and idx_t in names:
            for f, t in zip(split_list(read(zf, names, idx_f)), split_list(read(zf, names, idx_t))):
                key = prefix + f + ("" if f.endswith(".txt") else ".txt")
                if key in names:
                    chapters.append({"title": t, "content": read(zf, names, key)})
        else:
            for k in sorted(k for k in names if k.startswith(prefix) and k.endswith(".txt") and not k.endswith(INDEX_SUFFIXES)):
                chapters.append({"title": os.path.splitext(os.path.basename(k))[0], "content": read(zf, names, k)})
        yield b, chapters


def file_books(zf, names, root, split_re, keywords, max_title, min_chars):
    root = root.rstrip("/") + "/"
    seen = set()
    for k in sorted(k for k in names if k.startswith(root) and k.endswith(".txt")):
        title = re.sub(r"^\d+_", "", os.path.basename(k))[:-4].strip()
        if title in seen:
            continue
        if keywords and not (any(w in title for w in keywords) or (max_title and len(title) <= max_title)):
            continue
        content = read(zf, names, k)
        if len(content) < min_chars:
            continue
        seen.add(title)
        chapters, cur_t, cur = [], "正文", []
        for line in content.split("\n"):
            if split_re.match(line.strip()):
                if cur:
                    chapters.append({"title": cur_t, "content": "\n".join(cur)})
                cur_t, cur = line.strip(), []
            else:
                cur.append(line)
        if cur:
            chapters.append({"title": cur_t, "content": "\n".join(cur)})
        yield title, chapters or [{"title": title, "content": content}]


def main():
    p = c.parser("APK 内置书库 → EPUB")
    p.add_argument("--apk", required=True, help="APK 文件路径")
    p.add_argument("--root", required=True, help="APK 里书库所在目录，如 assets/book/世界名著")
    p.add_argument("--layout", choices=["folders", "files"], default="folders")
    p.add_argument("--folder", required=True, help="输出到 novels/standard/<folder>")
    p.add_argument("--author", default="佚名")
    p.add_argument("--intro", default="《{title}》全本。", help="简介模板，可用 {title}")
    p.add_argument("--titles", help="JSON：{书目录名: 显示书名}（folders 布局）")
    p.add_argument("--split", default=DEFAULT_SPLIT, help="files 布局的章节标题正则")
    p.add_argument("--keyword", action="append", help="files 布局：只要书名含这些词的（可多次）")
    p.add_argument("--max-title", type=int, default=0, help="files 布局：书名不超过这个长度的也收")
    p.add_argument("--min-chars", type=int, default=0, help="files 布局：正文少于这个字数的跳过")
    p.add_argument("--nsfw", action="store_true")
    args = p.parse_args()

    titles = {}
    if args.titles:
        with open(args.titles, "r", encoding="utf-8") as f:
            titles = json.load(f)
    zf, names = open_apk(os.path.expanduser(args.apk))
    books = (folder_books(zf, names, args.root) if args.layout == "folders" else
             file_books(zf, names, args.root, re.compile(args.split), args.keyword or [], args.max_title, args.min_chars))
    out_dir = c.library.primary(c.novels_key(args.nsfw), args.folder)
    os.makedirs(out_dir, exist_ok=True)
    made = skipped = 0
    for key, chapters in books:
        if not chapters:
            continue
        title = c.safe_name(titles.get(key, key))
        if c.find_existing(c.novels_key(args.nsfw), args.folder, title + ".epub", min_bytes=1024):
            skipped += 1
            continue
        c.build_epub(title, args.author, args.intro.format(title=title), chapters,
                     os.path.join(out_dir, title + ".epub"), args.nsfw)
        made += 1
        print(f"  ✅ {title}（{len(chapters)} 章）")
    print(f"📚 新建 {made} 本，已存在跳过 {skipped} 本 → {out_dir}")


if __name__ == "__main__":
    main()
