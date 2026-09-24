"""
统一配置常量入口：资源库根路径、广域网隧道域名、NSFW 默认密码等所有"跟这台机器/这个人
绑定、以后可能要改"的设置，都从这里 import，不要在各个模块里各自写死一份。

真实的值来自同目录下的 local_settings.py（本机专属，已加进 .gitignore，不会被提交）；
找不到那个文件时（比如第一次 clone 下来还没配置）退回到本文件里的通用默认值，保证代码
不会直接崩，只是相当于"资源库还没配置""广域网隧道没开"。

新增一项配置的流程：
1. 在 local_settings.example.py 里加一份带说明的示例（真实值留空/占位）；
2. 在这个文件里加一个同名的通用默认值 + 一个 get_xxx() 读取函数；
3. 在自己的 local_settings.py 里填真实值；
4. 用到的地方 `from app_config import get_xxx`，不要再各自 os.path.expanduser(...) 写死。

以前 main.py/shortvideo_service.py/... 各自硬编码一套"要不要看 SD 卡"的路径列表，这部分
职责原来在 library_roots.py 里；现在连同域名、密码一起合并到这一个文件，local_settings.py
的 mtime 变了就自动重新加载，改完不用重启大部分服务。
"""
import importlib
import os

_LOCAL_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_settings.py")

# 本文件里的默认值只在 local_settings.py 不存在/字段缺失时生效。
LIBRARY_ROOTS_DEFAULT = [os.path.expanduser("~/Games")]
WAN_DOMAIN_DEFAULT = None
NSFW_DEFAULT_PASSWORD_DEFAULT = "changeme"
MEGA_APP_DIR_DEFAULT = os.path.expanduser("~/Applications/mega-cmd")
ARCHIVE_EXTRACT_PASSWORD_DEFAULT = "changeme"

_cached_mtime = None
_cached_module = None


def _load_local_settings():
    """按 local_settings.py 的文件 mtime 判断有没有改过；改过了才重新 import 一次，
    没改直接用缓存，避免每次取配置都重新解析文件。文件不存在时返回 None（调用方
    自己决定 fallback 成什么默认值）。"""
    global _cached_mtime, _cached_module

    try:
        mtime = os.path.getmtime(_LOCAL_SETTINGS_PATH)
    except OSError:
        _cached_mtime = None
        _cached_module = None
        return None

    if _cached_module is not None and mtime == _cached_mtime:
        return _cached_module

    try:
        import local_settings as module
        importlib.reload(module)
    except Exception:
        _cached_mtime = None
        _cached_module = None
        return None

    _cached_module = module
    _cached_mtime = mtime
    return module


def get_library_roots():
    """当前配置的资源库根路径列表（原样返回配置值，不检查是否存在——存不存在由调
    用方的 os.path.isdir 判断，SD 卡没插的时候路径本来就该"查了发现没有"而不是直接
    从列表里消失，方便排查"是不是没插卡"还是"是配置错了"）。

    Returns:
        list[str]: 按优先级排好序的根路径列表，第一项是主库位置。
    """
    module = _load_local_settings()
    roots = getattr(module, "LIBRARY_ROOTS", None) if module else None
    if isinstance(roots, list) and roots:
        return [os.path.expanduser(r) for r in roots if isinstance(r, str) and r.strip()]
    return list(LIBRARY_ROOTS_DEFAULT)


def find_library_dirs(*subpath_parts):
    """在每个已配置的根路径下找 <root>/<subpath...>，返回所有实际存在的目录（保序、去重）。

    比如 find_library_dirs("rpg_games") 会依次检查每个根路径下的 rpg_games/ 是否存在，
    用于"读/列出已有资源在哪些地方"这类场景（合并 SSD + SD 卡等多个来源）。

    Args:
        *subpath_parts: 拼在每个根路径之后的子路径片段，等价于 os.path.join 的参数。

    Returns:
        list[str]: 所有根路径下真实存在该子路径的完整路径列表。
    """
    out = []
    seen = set()
    for root in get_library_roots():
        candidate = os.path.join(root, *subpath_parts)
        try:
            real_candidate = os.path.realpath(candidate)
        except OSError:
            continue
        if real_candidate in seen:
            continue
        if os.path.isdir(candidate):
            out.append(candidate)
            seen.add(real_candidate)
    return out


def get_primary_dir(*subpath_parts):
    """主库位置：第一个已配置的资源库根路径 + 给定子路径。

    新下载/正在处理的内容该落在哪，就用这个（单一确定位置，不是拿来枚举全部候选，
    枚举候选用 find_library_dirs）。只改 local_settings.py 里 LIBRARY_ROOTS 的第一项，
    所有服务模块的主库位置就跟着一起变。

    Args:
        *subpath_parts: 拼在主库根路径之后的子路径片段。

    Returns:
        str: 主库根路径 + 子路径拼接后的完整路径。
    """
    roots = get_library_roots()
    base = roots[0] if roots else LIBRARY_ROOTS_DEFAULT[0]
    return os.path.join(base, *subpath_parts)


def get_wan_domain():
    """广域网（Cloudflare 隧道）域名，没配置时返回 None（表示这项功能没开）。

    Returns:
        str | None: 域名字符串，或 None。
    """
    module = _load_local_settings()
    return getattr(module, "WAN_DOMAIN", None) if module else WAN_DOMAIN_DEFAULT


def get_nsfw_default_password():
    """NSFW 内容锁的默认密码（仅首次使用、还没设置过密码时生效）。

    Returns:
        str: 默认密码字符串。
    """
    module = _load_local_settings()
    value = getattr(module, "NSFW_DEFAULT_PASSWORD", None) if module else None
    return value if value else NSFW_DEFAULT_PASSWORD_DEFAULT


def get_mega_app_dir():
    """MEGA 命令行客户端 (mega-cmd) 的安装目录。

    Returns:
        str: mega-cmd 安装目录路径。
    """
    module = _load_local_settings()
    value = getattr(module, "MEGA_APP_DIR", None) if module else None
    return value if value else MEGA_APP_DIR_DEFAULT


def get_archive_extract_password():
    """伪装压缩包游戏（.mp4/.mkv 里塞了加密 7z）的解压密码。

    Returns:
        str: 解压密码字符串。
    """
    module = _load_local_settings()
    value = getattr(module, "ARCHIVE_EXTRACT_PASSWORD", None) if module else None
    return value if value else ARCHIVE_EXTRACT_PASSWORD_DEFAULT
