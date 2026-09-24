"""
下载中心脚本的公共部分。

个人参数（站点 Cookie、代理、YouTube 登录方式等）不写在脚本里，统一放在
var/config/crawler_secrets.json（已 gitignore，格式见同目录 secrets.example.json）。
所有脚本的参数都支持从文件读取：  python xxx.py @我的参数.args   （每行一个参数）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from omni.core import library, paths, settings  # noqa: E402

DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/151.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- 参数与私密配置

def parser(description: str) -> argparse.ArgumentParser:
    """统一的参数解析器：支持 @文件 读参数（每行一个），便于保存/复用一组参数。"""
    p = argparse.ArgumentParser(description=description, fromfile_prefix_chars="@")
    p.convert_arg_line_to_args = lambda line: [line.strip()] if line.strip() and not line.startswith("#") else []
    return p


def secrets() -> dict:
    try:
        with open(paths.CRAWLER_SECRETS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def user_agent() -> str:
    return (secrets().get("http") or {}).get("user_agent") or DEFAULT_UA


def http_proxy():
    return (secrets().get("http") or {}).get("proxy")


def site_cookies(url: str) -> dict:
    """按域名取 Cookie（secrets.sites.<host>.cookies），没配置返回空。"""
    host = urllib.parse.urlparse(url).hostname or ""
    return ((secrets().get("sites") or {}).get(host) or {}).get("cookies") or {}


# --------------------------------------------------------------------------- 网页抓取

def fetch_text(url: str, referer: str = None, retries: int = 3, min_len: int = 0, timeout: int = 20) -> str:
    """用 curl 抓网页（带该站点的 Cookie 与统一 UA；过 Cloudflare 的 cf_clearance 需要 UA 与获取时一致）。"""
    cmd = ["curl", "-sL", "--max-time", str(timeout),
           "-H", "accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "-H", "accept-language: zh-CN,zh;q=0.9",
           "-H", f"user-agent: {user_agent()}"]
    cookies = site_cookies(url)
    if cookies:
        cmd += ["-b", "; ".join(f"{k}={v}" for k, v in cookies.items())]
    if referer:
        cmd += ["-H", f"referer: {referer}"]
    if http_proxy():
        cmd += ["--proxy", http_proxy()]
    cmd += ["--url", url]
    for _ in range(retries):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            if is_challenge(res.stdout):
                host = urllib.parse.urlparse(url).hostname
                if host not in _warned_hosts:
                    _warned_hosts.add(host)
                    print(f"⚠️ {host} 返回了 Cloudflare 验证页：请在浏览器里打开该站，把新的 cf_clearance 填进 "
                          f"var/config/crawler_secrets.json 的 sites.{host}.cookies（UA 也要与该浏览器一致）")
                return ""
            if res.stdout and len(res.stdout) > min_len:
                return res.stdout
        except Exception:
            pass
        time.sleep(0.4)
    return ""


_warned_hosts = set()


def is_challenge(page: str) -> bool:
    head = (page or "")[:4000]
    return "<title>Just a moment...</title>" in head or "cf-chl" in head or "challenge-platform" in head


# --------------------------------------------------------------------------- yt-dlp

def ytdlp_cmd() -> list:
    uvx = settings.tool("uvx")
    if uvx and os.path.exists(uvx):
        return [uvx, "yt-dlp"]
    venv_bin = os.path.join(REPO, ".venv", "bin", "yt-dlp")
    if os.path.exists(venv_bin):
        return [venv_bin]
    return ["yt-dlp"]


def ytdlp_auth_args(cookies: str = None, proxy: str = None) -> list:
    """登录凭证与代理：命令行参数优先，其次 secrets.ytdlp。
    cookies 可以是 cookies.txt 路径，也可以是浏览器名（chrome/firefox…）；都没配置时用 var/config/cookies.txt。"""
    conf = secrets().get("ytdlp") or {}
    args = []
    cookies = cookies or conf.get("cookies_file") or conf.get("cookies_from_browser")
    if not cookies and os.path.exists(paths.COOKIES_TXT):
        cookies = paths.COOKIES_TXT          # 默认：var/config/cookies.txt
    if cookies:
        cookies = os.path.expanduser(cookies)
        if "/" in cookies or cookies.endswith(".txt"):
            if not os.path.exists(cookies):
                sys.exit(f"cookies 文件不存在：{cookies}")
            args += ["--cookies", cookies]
        else:
            args += ["--cookies-from-browser", cookies]
    proxy = proxy or conf.get("proxy")
    if proxy:
        args += ["--proxy", proxy]
    return args


# --------------------------------------------------------------------------- 资源库

def safe_name(name: str, max_len: int = 120) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name)).strip(" ._")[:max_len] or "untitled"


def audio_key(nsfw: bool) -> str:
    return "media.audio.nsfw" if nsfw else "media.audio.standard"


def novels_key(nsfw: bool) -> str:
    return "media.novels.nsfw" if nsfw else "media.novels.standard"


def find_existing(key: str, *rel: str, min_bytes: int = 1):
    """在所有在线资源库里找同一相对路径的文件（可能之前挪去了 SD 卡），避免重复下载。"""
    for d in library.dirs(key):
        p = os.path.join(d, *rel)
        if os.path.isfile(p) and os.path.getsize(p) >= min_bytes:
            return p
    return None


def trash(path: str) -> None:
    """项目铁律：删除一律进回收站。"""
    if os.path.exists(path):
        subprocess.run(["gio", "trash", path], capture_output=True)


def need(binary: str) -> None:
    if not shutil.which(binary):
        sys.exit(f"缺少依赖命令：{binary}")


# --------------------------------------------------------------------------- 输出

def build_epub(title: str, author: str, intro: str, chapters: list, out_path: str, nsfw: bool = False) -> str:
    """chapters: [{title, content(纯文本，按行/空行分段)}]；复用小说画廊的 EPUB 生成器。"""
    from omni.features.novels.service import build_epub_file
    build_epub_file(title, author, intro, chapters, out_path, is_nsfw=nsfw)
    return out_path


def parse_ranges(spec: str) -> set:
    """"1-6,9,12-" -> 集合（开区间上限用一个大数）。空串返回空集合（表示全部）。"""
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            out.update(range(int(a or 1), int(b or 100000) + 1))
        else:
            out.add(int(part))
    return out
