"""
访问控制的唯一实现：请求来自哪（本机 / 局域网 / Cloudflare 广域网）、能不能看 NSFW 内容、
局域网/广域网开关关着时整站闸门。路由上的 access="nsfw"/"local" 最终都落到这里。
"""
from omni.core import endpoints
from omni.network import lan, wan

LOOPBACK = (endpoints.LOOPBACK, "localhost", "::1")


def client_ip(handler) -> str:
    addr = getattr(handler, "client_address", None)
    return addr[0] if addr else endpoints.LOOPBACK


def is_cloudflare(handler) -> bool:
    return bool(handler.headers.get("CF-Connecting-IP") or handler.headers.get("cf-ray"))


def is_local(handler) -> bool:
    """本机屏幕（回环地址或本机局域网 IP）发来的请求；经 Cloudflare 转发的一律不算本机。"""
    ip = client_ip(handler)
    return (ip in LOOPBACK or ip == lan.local_ip()) and not is_cloudflare(handler)


def nsfw_authorized(handler) -> bool:
    """本机始终放行；非本机要带有效的解锁 token。"""
    from omni.features.privacy import service as privacy
    return privacy.is_request_authorized(handler, is_local(handler))


def allowed(handler, level: str) -> bool:
    if level == "local":
        return is_local(handler)
    if level == "nsfw":
        return nsfw_authorized(handler)
    return True


def gate(handler):
    """整站闸门：广域网/局域网共享关着时拒绝外部请求。返回 None 放行，否则返回 (标题, 说明)。"""
    if is_cloudflare(handler):
        if not wan.enabled():
            return ("🔒 广域网公网访问已关闭",
                    "Steam Deck 上的 Omni Deck 广域网远程访问开关目前处于关闭状态。<br>"
                    "如需在外部网络访问，请在 Steam Deck 屏幕右上角点击【广域网】开关开启。")
        return None
    if not is_local(handler) and not lan.enabled():
        return ("🔒 局域网跨设备共享已关闭",
                "Steam Deck 上的 Omni Deck 局域网共享功能目前处于关闭状态。<br>"
                "如需在手机或平板上访问，请在 Steam Deck 屏幕右上角点击【局域网共享】按钮开启。")
    return None
