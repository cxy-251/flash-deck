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

from omni.core import endpoints, library, paths, settings  # noqa: E402

DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/151.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- 参数与私密配置

_TOKEN = re.compile(r"\{(url:)?([a-z_][a-z0-9_]*)\}")


def expand(value):
    """展开参数/任务文件/secrets 里的占位符，让它们只写「键」不写死地址：
      {url:站点键}  -> omni/core/endpoints.py 的站点根地址，如 {url:youtube}/watch?v=xxx
      {tasks}       -> 任务目录 var/config/crawler_tasks（剧本/映射表等数据文件）
      {inbox}       -> 收件箱目录（settings.inbox_dir）
      {home} {games} {sd} …  -> settings.json 的 dirs 基础目录
    不认识的占位符原样保留。列表/字典递归处理。"""
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if not isinstance(value, str) or "{" not in value:
        return value

    def sub(m):
        is_url, key = m.group(1), m.group(2)
        if is_url:
            return endpoints.get(key) if key in endpoints.DEFAULTS else m.group(0)
        if key == "tasks":
            return paths.CRAWLER_TASKS
        if key == "inbox":
            return settings.resolve(settings.get("inbox_dir"))
        return settings.resolve(m.group(0))
    return _TOKEN.sub(sub, value)


class _Parser(argparse.ArgumentParser):
    def parse_args(self, *a, **kw):
        ns = super().parse_args(*a, **kw)
        for k, v in vars(ns).items():
            setattr(ns, k, expand(v))
        return ns


def parser(description: str) -> argparse.ArgumentParser:
    """统一的参数解析器：支持 @文件 读参数（每行一个），便于保存/复用一组参数；参数里的占位符见 expand()。"""
    p = _Parser(description=description, fromfile_prefix_chars="@")
    p.convert_arg_line_to_args = lambda line: [line.strip()] if line.strip() and not line.startswith("#") else []
    return p


def secrets() -> dict:
    try:
        with open(paths.CRAWLER_SECRETS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return expand(data) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def user_agent() -> str:
    return (secrets().get("http") or {}).get("user_agent") or DEFAULT_UA


def http_proxy():
    return (secrets().get("http") or {}).get("proxy")


def site_cookies(url: str) -> dict:
    """按域名取 Cookie（secrets.sites.<域名 或 endpoints 站点键>.cookies），没配置返回空。"""
    host = urllib.parse.urlparse(url).hostname or ""
    sites = secrets().get("sites") or {}
    for key, conf in sites.items():
        if key == host or (key in endpoints.DEFAULTS and endpoints.host(key) == host):
            return (conf or {}).get("cookies") or {}
    return {}


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
                    key = next((k for k in endpoints.DEFAULTS if endpoints.host(k) == host), host)
                    print(CF_COOKIE_HELP.format(host=host, key=key))
                return ""
            if res.stdout and len(res.stdout) > min_len:
                return res.stdout
        except Exception:
            pass
        time.sleep(0.4)
    return ""


_warned_hosts = set()


CF_COOKIE_HELP = """⚠️ {host} 返回了 Cloudflare 验证页，站点 Cookie 缺失或已过期。更新方法：
  1. 用电脑/Deck 上的浏览器打开 https://{host} ，等「正在验证你是否是真人」通过、能看到正文；
  2. 按 F12 打开开发者工具 → Application（Firefox 叫「存储」）→ Cookies → https://{host}，
     复制 cf_clearance 的值（其它 Cookie 一般不需要）；
  3. 同一个开发者工具的 Console 里执行 navigator.userAgent，复制输出的 UA 字符串；
  4. 写进 var/config/crawler_secrets.json（没有就从 tools/crawlers/secrets.example.json 复制一份）：
       "http":  {{"user_agent": "<第 3 步的 UA>"}},
       "sites": {{"{key}": {{"cookies": {{"cf_clearance": "<第 2 步的值>"}}}}}}
  cf_clearance 绑定浏览器 UA 和出口 IP：UA 必须一致，换网络/开关代理后可能要重新获取；一般几天到几周过期。"""


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
