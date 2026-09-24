#!/usr/bin/env python3
"""
博客类小说站（Blogger 风格：/search/label/<标签>、文章 URL 带 /20xx/）→ EPUB。

三个子命令：
  stories  把标签页（或专题页）下的全部短篇按 N 篇一卷合成若干本 EPUB
           blog_novels.py stories --site https://example.blog --label 分类A --label 分类B --prefix "短篇合集"
           blog_novels.py stories --page https://example.blog/p/special.html --name 专题名 --chunk 15
  book     把一个标签下的全部章节（自动翻页、按章节号排序）合成一本长篇
           blog_novels.py book --url https://example.blog/search/label/书名 --title 书名
  books    从目录首页发现所有书的标签页，逐本执行 book（已存在的跳过）
           blog_novels.py books --index https://example.blog/ --exclude 分类A --exclude 联系我们

站点需要的 Cookie（如 Cloudflare 的 cf_clearance）与 UA 放在 var/config/crawler_secrets.json 的
sites.<域名>.cookies / http.user_agent 里。输出到默认资源库 media_library/novels/<standard|nsfw>/<子目录>/。
"""
import argparse
import os
import re
import time
import urllib.parse

import _common as c

ARTICLE_RE = re.compile(r'<a[^>]+href=["\']([^"\'?#]*20\d\d/\d\d/[^"\'?#]+\.html)["\'][^>]*>(.*?)</a>', re.S | re.I)
ANY_ARTICLE_RE = re.compile(r'<a[^>]+href=["\']([^"\'?#]*\.html)["\'][^>]*>(.*?)</a>', re.S | re.I)
TITLE_RES = [re.compile(r'<h1[^>]*class=["\'][^"\']*post__title[^"\']*["\'][^>]*>(.*?)</h1>', re.S | re.I),
             re.compile(r'<h3[^>]*class=["\'][^"\']*post-title[^"\']*["\'][^>]*>(.*?)</h3>', re.S | re.I),
             re.compile(r'<title>(.*?)</title>', re.S | re.I)]
BODY_RES = [re.compile(r'<div[^>]*class=["\'][^"\']*post__content[^"\']*["\'][^>]*>(.*?)</div>\s*</article>', re.S | re.I),
            re.compile(r'<div[^>]*class=["\'][^"\']*post__content[^"\']*["\'][^>]*>(.*?)<nav', re.S | re.I),
            re.compile(r'<div[^>]*class=["\'][^"\']*(?:post-body|post__content|entry-content)[^"\']*["\'][^>]*>(.*?)</div>\s*'
                       r'(?:<div class=["\'](?:post-bottom|separator)|<footer|<nav|</div>\s*</div>)', re.S | re.I),
            re.compile(r'itemprop=["\']description articleBody["\'][^>]*>(.*?)</div>', re.S | re.I)]
NEXT_RE = re.compile(r'<a[^>]+class=["\'][^"\']*(?:blog-pager-older-link|next)[^"\']*["\'][^>]*href=["\']([^"\']+)["\']', re.I)
SENTENCE_END = ('。', '！', '？', '”', '’', '」', '』', '…', '—', ':', '：', ';', '；')
PARA_START = ('「', '“', '‘', '（', '【', '第', '★', '◆', '●') + tuple('0123456789')
CN_NUM = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
          '十': 10, '百': 100, '千': 1000, '万': 10000}


def strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', '', s or '').replace('&nbsp;', ' ').strip()


def clean_body(raw_html: str) -> str:
    """正文 HTML → 纯文本段落（空行分隔）：去脚本样式、合并被硬换行打断的句子。"""
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or '', flags=re.S | re.I)
    text = re.sub(r'<div class=["\']separator["\']>.*?</div>', '', text, flags=re.S | re.I)
    text = re.sub(r'[\r\n\t]+', '\n', text)
    paras = re.findall(r'<p[^>]*>(.*?)</p>', text, flags=re.S | re.I) or re.split(r'<br\s*/?>|\n', text)
    out = []
    for p in paras:
        t = strip_tags(p)
        if len(t) < 2:
            continue
        if out and not t.startswith(PARA_START) and len(out[-1]) > 6 and not out[-1].endswith(SENTENCE_END):
            sep = '' if ord(out[-1][-1]) > 127 and ord(t[0]) > 127 else ' '
            out[-1] += sep + t
            continue
        out.append(t)
    return '\n\n'.join(out)


def cn_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    val = tmp = 0
    for ch in s:
        n = CN_NUM.get(ch)
        if n is None:
            continue
        if n >= 10:
            val += (tmp or 1) * n
            tmp = 0
        else:
            tmp = n
    return val + tmp


def chapter_key(title: str):
    if any(k in title for k in ('简介', '楔子', '序章', '引子', '前言')):
        return (0, 0, 0, title)
    if any(k in title for k in ('尾声', '大结局', '后记', '番外')):
        return (9999, 9999, 9999, title)
    num = r'([0-9零一二两三四五六七八九十百千]+)'
    part = re.search(r'第\s*' + num + r'\s*(?:部|卷|集)', title)
    ch = re.search(r'第\s*' + num + r'\s*(?:章|节|回|篇)', title)
    digits = re.search(r'([0-9]+)', title)
    return (1, cn_to_int(part.group(1)) if part else 0,
            cn_to_int(ch.group(1)) if ch else (int(digits.group(1)) if digits else 0), title)


def list_links(html_text: str, base: str, pattern=ARTICLE_RE) -> list:
    out = []
    for href, title in pattern.findall(html_text or ''):
        t = strip_tags(title)
        if len(t) > 1:
            out.append((urllib.parse.urljoin(base, href), t))
    return out


def fetch_article(url: str, referer: str, strip_suffix: str = ''):
    page = c.fetch_text(url, referer=referer)
    title = next((strip_tags(m.group(1)) for r in TITLE_RES for m in [r.search(page)] if m), '')
    if strip_suffix:
        title = title.replace(strip_suffix, '').strip()
    body = next((m.group(1) for r in BODY_RES for m in [r.search(page)] if m), '')
    return title, clean_body(body)


def out_dir(args, sub: str) -> str:
    d = c.library.primary(c.novels_key(args.nsfw), c.safe_name(sub))
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- stories

def label_articles(site: str, label: str, max_pages: int) -> list:
    base = f"{site.rstrip('/')}/search/label/{urllib.parse.quote(label)}/"
    seen, out = set(), []
    for n in range(1, max_pages + 1):
        url = base if n == 1 else f"{base}page/{n}/"
        page = c.fetch_text(url)
        fresh = [(u, t) for u, t in list_links(page, url, ANY_ARTICLE_RE)
                 if u not in seen and '/20' in u and urllib.parse.urlparse(u).hostname == urllib.parse.urlparse(site).hostname]
        if not fresh:
            break
        for u, t in fresh:
            seen.add(u)
            out.append((u, t))
        print(f"  📄 第 {n} 页：{len(fresh)} 篇（累计 {len(out)}）")
        time.sleep(0.3)
    return out


def write_volumes(args, category: str, articles: list, referer: str):
    folder = out_dir(args, args.folder or category)
    if args.replace:
        for f in os.listdir(folder):
            if f.endswith('.epub'):
                c.trash(os.path.join(folder, f))
    stories, vol = [], 1

    def flush():
        nonlocal stories, vol
        if not stories:
            return
        title = f"{args.prefix}·{category} (第{vol:02d}卷)"
        path = os.path.join(folder, c.safe_name(title) + ".epub")
        c.build_epub(title, args.author, f"{category}，第 {vol} 卷，收录 {len(stories)} 篇。", stories, path, args.nsfw)
        print(f"📦 {path}（{len(stories)} 篇）")
        stories, vol = [], vol + 1

    for i, (url, t) in enumerate(articles, 1):
        title, body = fetch_article(url, referer, args.strip_title)
        if len(body) > 50:
            stories.append({"title": title or t, "content": body})
            print(f"  [{i}/{len(articles)}] ✓ 《{title or t}》 {len(body)} 字")
        else:
            print(f"  [{i}/{len(articles)}] ⚠️ 正文为空，跳过：{t}")
        if len(stories) >= args.chunk:
            flush()
        time.sleep(args.delay)
    flush()


def cmd_stories(args):
    args.prefix = args.prefix or "短篇合集"   # 不用 set_defaults：子命令共用的参数对象会把默认值串到别的子命令
    jobs = []
    for label in args.label or []:
        if not args.site:
            raise SystemExit("--label 需要配合 --site")
        jobs.append((label, lambda l=label: label_articles(args.site, l, args.max_pages),
                     f"{args.site.rstrip('/')}/search/label/{urllib.parse.quote(label)}/"))
    if args.page:
        if not args.name:
            raise SystemExit("--page 需要配合 --name（专题名）")
        jobs.append((args.name, lambda: list(dict.fromkeys(list_links(c.fetch_text(args.page), args.page))),
                     args.page))
    for category, collect, referer in jobs:
        print(f"\n📂 【{category}】")
        articles = collect()
        print(f"  共 {len(articles)} 篇")
        if articles:
            write_volumes(args, category, articles, referer)


# --------------------------------------------------------------------------- book / books

def book_exists(args, title: str) -> bool:
    key = title.replace('《', '').replace('》', '').strip()
    for d in c.library.dirs(c.novels_key(args.nsfw)):
        for _root, _dirs, files in os.walk(d):
            if any(key in f and f.endswith('.epub') for f in files):
                return True
    return False


def book_chapters(label_url: str) -> list:
    url = label_url + ('&' if '?' in label_url else '?') + 'max-results=500'
    seen, visited, out = set(), set(), []
    while url and url not in visited:
        visited.add(url)
        page = c.fetch_text(url)
        if not page:
            break
        for u, t in list_links(page, url):
            if u not in seen:
                seen.add(u)
                out.append((t, u))
        nxt = NEXT_RE.search(page)
        url = urllib.parse.urljoin(url, nxt.group(1).replace('&amp;', '&')) if nxt else None
        time.sleep(0.2)
    return sorted(out, key=lambda x: chapter_key(x[0]))


def build_book(args, title: str, label_url: str):
    if not args.force and book_exists(args, title):
        print(f"⏩ 《{title}》已在书架，跳过")
        return
    chapters = book_chapters(label_url)
    print(f"📚 《{title}》共 {len(chapters)} 章")
    contents = []
    for i, (ch_title, url) in enumerate(chapters, 1):
        _t, body = fetch_article(url, label_url)
        if len(body) > 50:
            contents.append({"title": ch_title, "content": body})
        if i % 20 == 0:
            print(f"  …{i}/{len(chapters)}")
        time.sleep(args.delay)
    if not contents:
        print("  ⚠️ 没有抓到正文")
        return
    name = f"{args.prefix}·{title} (全本)" if args.prefix else title
    path = os.path.join(out_dir(args, args.folder), c.safe_name(name) + ".epub")
    c.build_epub(name, args.author, f"《{title}》全本，共 {len(contents)} 章。", contents, path, args.nsfw)
    print(f"📦 {path}")


def cmd_book(args):
    build_book(args, args.title, args.url)


def cmd_books(args):
    page = c.fetch_text(args.index)
    if not page:
        raise SystemExit(f"无法打开目录页：{args.index}")
    exclude = set(args.exclude or [])
    books, seen = [], set()
    for href, t in re.findall(r'<a[^>]+href=["\']([^"\'?#]*search/label/[^"\'?#]+)["\'][^>]*>(.*?)</a>', page):
        label = urllib.parse.unquote(href.split('search/label/')[-1].strip('/'))
        title = strip_tags(t) or label
        if label in exclude or title in exclude or label in seen:
            continue
        seen.add(label)
        books.append((title, urllib.parse.urljoin(args.index, href)))
    print(f"📊 目录页发现 {len(books)} 本")
    for i, (title, url) in enumerate(books, 1):
        print(f"\n[{i}/{len(books)}]")
        build_book(args, title, url)


def main():
    p = c.parser("博客类小说站 → EPUB")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--nsfw", action="store_true", help="存到 novels/nsfw（默认 standard）")
    common.add_argument("--author", default="网络文学")
    common.add_argument("--delay", type=float, default=0.15, help="每篇之间的间隔秒数")
    common.add_argument("--prefix", default="", help="书名前缀（stories 缺省「短篇合集」，book 缺省无）")

    s = sub.add_parser("stories", parents=[common],
                       help="标签页/专题页短篇 → 多卷合集")
    s.add_argument("--site", help="站点根地址，配合 --label")
    s.add_argument("--label", action="append", help="标签名（可多次）")
    s.add_argument("--page", help="专题页 URL（单页列出全部文章）")
    s.add_argument("--name", help="专题名（配合 --page）")
    s.add_argument("--folder", help="输出子目录（默认=标签名/专题名）")
    s.add_argument("--chunk", type=int, default=30, help="每卷篇数")
    s.add_argument("--max-pages", type=int, default=100)
    s.add_argument("--strip-title", default="", help="从文章标题里去掉的站点后缀")
    s.add_argument("--replace", action="store_true", help="先把该目录旧的 EPUB 移到回收站再重建")
    s.set_defaults(func=cmd_stories)

    b = sub.add_parser("book", parents=[common], help="一个标签 → 一本长篇")
    b.add_argument("--url", required=True, help="该书的标签页 URL")
    b.add_argument("--title", required=True)
    b.add_argument("--folder", default="长篇")
    b.add_argument("--force", action="store_true", help="已存在也重建")
    b.set_defaults(func=cmd_book)

    bs = sub.add_parser("books", parents=[common], help="目录页 → 逐本长篇")
    bs.add_argument("--index", required=True, help="列出所有书标签的目录页 URL")
    bs.add_argument("--exclude", action="append", help="排除的标签/链接文字（可多次）")
    bs.add_argument("--folder", default="长篇")
    bs.add_argument("--force", action="store_true")
    bs.set_defaults(func=cmd_books)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
