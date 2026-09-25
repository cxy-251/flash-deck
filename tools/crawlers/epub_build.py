#!/usr/bin/env python3
"""
书稿 → EPUB，三种来源：
  --spec 书稿.json      {"title", "author", "intro", "chapters": [{"title", "content"}]}；也可以是这样的列表（多本）
  --dir 目录            目录下每个 .md/.txt 是一章（按文件名自然排序；章节名取首个标题或文件名）
  --github 用户/仓库 --path 子目录 [--ref 分支]   仓库里某目录下的 .md 按顺序成章

例：
  epub_build.py --spec 英语习语.json --folder 英语进阶
  epub_build.py --dir ~/notes/rust --title "Rust 笔记" --author 我 --folder 技术笔记
  epub_build.py --github hanxiaomax/WordPowerMadeEasy --path src/wpme --title "Word Power Made Easy" \\
                --author "Norman Lewis" --folder 英语进阶 --order 章节顺序.json
（--order：JSON 列表 [[文件名, 章节名], ...]，只收列出的文件并按此顺序；不给就按文件名排序）
输出到默认资源库 media_library/novels/<standard|nsfw>/<folder>/<书名>.epub。
"""
import json
import os
import re
import urllib.request

import _common as c


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def md_to_text(text: str) -> str:
    """Markdown 标题转成醒目的纯文本行（EPUB 生成器按段落排版，不解析 Markdown）。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("### "):
            out.append(f"  ● {s[4:].strip()}")
        elif s.startswith("## "):
            out.append(f"\n■ {s[3:].strip()}\n")
        elif s.startswith("# "):
            out.append(f"【{s[2:].strip()}】\n")
        else:
            out.append(line)
    return "\n".join(out)


def chapter_title(fname: str, text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else os.path.splitext(fname)[0]


def load_order(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return [tuple(x) for x in json.load(f)]


def from_dir(d: str, order):
    files = order or [(f, None) for f in sorted(os.listdir(d), key=natural_key) if f.endswith((".md", ".txt"))]
    chapters = []
    for fname, title in files:
        with open(os.path.join(d, fname), "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        chapters.append({"title": title or chapter_title(fname, text),
                         "content": md_to_text(text) if fname.endswith(".md") else text})
    return chapters


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": c.user_agent()})
    handlers = []
    if c.http_proxy():
        handlers.append(urllib.request.ProxyHandler({"http": c.http_proxy(), "https": c.http_proxy()}))
    with urllib.request.build_opener(*handlers).open(req, timeout=30) as r:
        return r.read()


def from_github(repo: str, path: str, ref: str, order):
    if order is None:
        listing = json.loads(http_get(c.endpoints.url("github_api", "repos", repo, "contents", path, ref=ref)))
        order = [(x["name"], None) for x in sorted(listing, key=lambda x: natural_key(x["name"]))
                 if x["type"] == "file" and x["name"].endswith((".md", ".txt"))]
    chapters = []
    for fname, title in order:
        try:
            text = http_get(c.endpoints.url("github_raw", repo, ref, path, fname)).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  ⚠️ {fname}: {e}")
            continue
        chapters.append({"title": title or chapter_title(fname, text),
                         "content": md_to_text(text) if fname.endswith(".md") else text})
        print(f"  ✓ {fname}（{len(text)} 字节）")
    return chapters


def write(book: dict, folder: str, nsfw: bool, force: bool):
    title = book["title"]
    name = c.safe_name(title) + ".epub"
    if not force and c.find_existing(c.novels_key(nsfw), folder, name, min_bytes=1024):
        print(f"✅ 已存在，跳过：{title}")
        return
    out_dir = c.library.primary(c.novels_key(nsfw), folder)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    c.build_epub(title, book.get("author", "佚名"), book.get("intro", ""), book["chapters"], path, nsfw)
    print(f"📦 {path}（{len(book['chapters'])} 章）")


def main():
    p = c.parser("书稿 / 本地目录 / GitHub 目录 → EPUB")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", help="书稿 JSON（一本或多本）")
    src.add_argument("--dir", help="本地 md/txt 目录")
    src.add_argument("--github", help="GitHub 仓库 用户/仓库名")
    p.add_argument("--path", default="", help="--github 时仓库内的目录")
    p.add_argument("--ref", default="master", help="--github 时的分支")
    p.add_argument("--order", help="章节顺序 JSON：[[文件名, 章节名], ...]")
    p.add_argument("--title", help="书名（--dir / --github 必填）")
    p.add_argument("--author", default="佚名")
    p.add_argument("--intro", default="")
    p.add_argument("--folder", required=True, help="输出到 novels/<standard|nsfw>/<folder>")
    p.add_argument("--nsfw", action="store_true")
    p.add_argument("--force", action="store_true", help="已存在也重建")
    args = p.parse_args()

    if args.spec:
        with open(args.spec, "r", encoding="utf-8") as f:
            data = json.load(f)
        for book in (data if isinstance(data, list) else [data]):
            write(book, args.folder, args.nsfw, args.force)
        return
    if not args.title:
        raise SystemExit("--dir / --github 需要 --title")
    order = load_order(args.order)
    chapters = from_dir(os.path.expanduser(args.dir), order) if args.dir else from_github(args.github, args.path, args.ref, order)
    if not chapters:
        raise SystemExit("没有读到任何章节")
    write({"title": args.title, "author": args.author, "intro": args.intro, "chapters": chapters},
          args.folder, args.nsfw, args.force)


if __name__ == "__main__":
    main()
