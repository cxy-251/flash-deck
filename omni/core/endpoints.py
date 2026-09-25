"""
外部站点与本机服务地址的唯一定义处。代码里只写「站点键 + 路径」，由这里拼成完整 URL：

    endpoints.url("gutenberg", "ebooks", book_id)        # https://www.gutenberg.org/ebooks/123
    endpoints.url("xbookcn_blog", "search/label", "历史")  # 路径段自动 URL 编码
    endpoints.host("xbookcn_blog")                       # blog.xbookcn.net

站点换域名/换镜像：在 var/config/settings.json 的 "endpoints" 里覆盖对应的键即可，全项目（后端、前端、
下载脚本、任务文件里的 {url:键}）一起生效。前端拿到的是 PUBLIC 里列出的这部分（见 omni/core/http/hub.py）。
"""
import urllib.parse

DEFAULTS = {
    # 在线小说
    "gutenberg": "https://www.gutenberg.org",
    "gutenberg_alt": "https://gutenberg.org",
    "gutenberg_raw": "https://raw.githubusercontent.com/gutenberg-org",
    "xbookcn_blog": "https://blog.xbookcn.net",
    "xbookcn_book": "https://book.xbookcn.net",
    # 漫画
    "jm_web": "https://18comic.vip",
    "jm_cdn": "https://cdn-msp.jmapinode2.cc",
    # 视频 / 代码托管 / 网盘
    "youtube": "https://www.youtube.com",
    "bilibili": "https://www.bilibili.com",
    "github_api": "https://api.github.com",
    "github_raw": "https://raw.githubusercontent.com",
    "mega": "https://mega.nz",
}

# 暴露给前端页面的键（window.OMNI_ENDPOINTS）
PUBLIC = ("gutenberg", "xbookcn_blog", "jm_web", "mega")

# 本机回环地址：本地 HTTP 服务、单实例探测、Qt 视口加载页面都用它
LOOPBACK = "127.0.0.1"


def get(name: str) -> str:
    """站点根地址（不带结尾斜杠）；settings.json 的 endpoints 优先。"""
    from omni.core import settings
    override = (settings.load().get("endpoints") or {}).get(name)
    base = override or DEFAULTS[name]
    return base.rstrip("/")


def url(name: str, *parts, **query) -> str:
    """根地址 + 路径段（每段 URL 编码，允许段内带 /）+ 查询参数。"""
    path = "/".join(urllib.parse.quote(str(p).strip("/"), safe="/:@!$&'()*+,;=-._~") for p in parts if str(p) != "")
    out = get(name) + ("/" + path if path else "")
    if query:
        out += "?" + urllib.parse.urlencode(query)
    return out


def host(name: str) -> str:
    return urllib.parse.urlparse(get(name)).hostname or ""


def public() -> dict:
    return {k: get(k) for k in PUBLIC}


def local_url(port: int, path: str = "/") -> str:
    """本机 HTTP 服务上的地址（Qt 视口加载大厅/游戏用）。"""
    return f"http://{LOOPBACK}:{port}/{path.lstrip('/')}"
