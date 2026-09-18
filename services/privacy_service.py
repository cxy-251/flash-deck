# -*- coding: utf-8 -*-
"""
privacy_service.py - Omni Deck 隐私与 NSFW 访问控制服务
提供基于加盐哈希的密码保护、Token 签发、非本机（局域网/广域网）访问鉴权与敏感数据过滤
"""

import os
import json
import time
import secrets
import hashlib
from typing import Dict, Any, Optional

from app_config import get_nsfw_default_password

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "privacy_config.json")
DEFAULT_PASSWORD = get_nsfw_default_password()  # 真实默认密码在 services/local_settings.py 里，不写死在会公开的源码中


def _hash_password(password: str, salt: str) -> str:
    """对密码加盐后做 SHA-256 摘要。

    Args:
        password: 明文密码。
        salt: 每个配置独立生成的随机盐值。

    Returns:
        str: 十六进制格式的哈希摘要。
    """
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def _load_or_init_config() -> Dict[str, Any]:
    """读取密码配置文件，不存在/读取失败时用默认密码初始化一份新的。

    Returns:
        Dict[str, Any]: 配置字典，至少包含 salt/password_hash 两个字段。
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 首次初始化配置，使用 local_settings.py 里配置的默认密码
    salt = secrets.token_hex(8)
    config = {
        "salt": salt,
        "password_hash": _hash_password(DEFAULT_PASSWORD, salt),
        "created_at": time.time(),
        "default_password_used": True
    }
    _save_config(config)
    return config

def _save_config(config: Dict[str, Any]):
    """把密码配置字典写回磁盘（JSON，覆盖写）。

    Args:
        config: 完整的配置字典（不会跟磁盘上的旧内容合并，调用方需自己带全字段）。
    """
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Privacy] Failed to save config: {e}")

def verify_password(password: str) -> bool:
    """验证用户输入的密码是否正确。

    Args:
        password: 用户输入的明文密码。

    Returns:
        bool: 密码正确返回 True，为空或不匹配返回 False。
    """
    if not password:
        return False
    config = _load_or_init_config()
    salt = config.get("salt", "")
    target_hash = config.get("password_hash", "")
    input_hash = _hash_password(password, salt)
    return secrets.compare_digest(input_hash, target_hash)

def change_password(old_password: str, new_password: str) -> Dict[str, Any]:
    """校验旧密码后修改访问密码（会重新生成 salt，旧密码哈希失效）。

    Args:
        old_password: 当前密码，用于身份校验。
        new_password: 新密码，长度至少 4 位。

    Returns:
        Dict[str, Any]: {"success": bool, "error"/"message": str}。
    """
    if not new_password or len(new_password) < 4:
        return {"success": False, "error": "新密码长度至少需要4位字符"}
    if not verify_password(old_password):
        return {"success": False, "error": "原密码错误，修改失败"}

    new_salt = secrets.token_hex(8)
    config = {
        "salt": new_salt,
        "password_hash": _hash_password(new_password, new_salt),
        "updated_at": time.time(),
        "default_password_used": False
    }
    _save_config(config)
    return {"success": True, "message": "密码修改成功"}

# 内存与文件中活跃的 Token 列表: {token: expire_timestamp}
_ACTIVE_TOKENS: Dict[str, float] = {}
_TOKENS_LOADED = False

def _ensure_tokens_loaded():
    """进程首次用到 Token 相关功能时，把磁盘上还没过期的 Token 读进内存（只做一次）。"""
    global _TOKENS_LOADED
    if not _TOKENS_LOADED:
        cfg = _load_or_init_config()
        saved_tokens = cfg.get("tokens", {})
        now = time.time()
        for t, exp in saved_tokens.items():
            if exp > now:
                _ACTIVE_TOKENS[t] = exp
        _TOKENS_LOADED = True

def _save_active_tokens():
    """把内存里当前的活跃 Token 表写回配置文件（沿用现有 salt/password_hash 等字段）。"""
    cfg = _load_or_init_config()
    cfg["tokens"] = _ACTIVE_TOKENS
    _save_config(cfg)

def create_auth_token(days: int = 7) -> str:
    """签发一个新的登录 Token 并持久化。

    Args:
        days: Token 有效天数（默认 7 天）。

    Returns:
        str: 新生成的 Token 字符串。
    """
    _ensure_tokens_loaded()
    token = secrets.token_hex(16)
    expire_at = time.time() + (days * 86400)
    _ACTIVE_TOKENS[token] = expire_at
    _save_active_tokens()
    return token

def revoke_auth_token(token: str) -> bool:
    """撤销已授权的 Token（用于登出）。

    Args:
        token: 要撤销的 Token 字符串。

    Returns:
        bool: Token 存在并被撤销返回 True，本来就不存在返回 False。
    """
    _ensure_tokens_loaded()
    if token in _ACTIVE_TOKENS:
        del _ACTIVE_TOKENS[token]
        _save_active_tokens()
        return True
    return False

def is_token_valid(token: Optional[str]) -> bool:
    """检查客户端携带的 Token 是否处于有效期内；过期的顺手清理掉。

    Args:
        token: 待校验的 Token 字符串，可以是 None。

    Returns:
        bool: 有效返回 True，缺失/不存在/已过期返回 False。
    """
    if not token:
        return False
    _ensure_tokens_loaded()
    expire_at = _ACTIVE_TOKENS.get(token)
    if not expire_at:
        return False
    if time.time() > expire_at:
        del _ACTIVE_TOKENS[token]
        _save_active_tokens()
        return False
    return True

def extract_token_from_handler(handler) -> Optional[str]:
    """从 HTTP 请求里提取客户端携带的 Token，依次尝试请求头、Cookie、URL 参数。

    Args:
        handler: BaseHTTPRequestHandler 实例，需要有 headers（必需）和 path（可选）属性。

    Returns:
        Optional[str]: 提取到的 Token 字符串；三处都没有则返回 None。
    """
    # 1. 优先请求头 X-Omni-Token
    token = handler.headers.get("X-Omni-Token")
    if token:
        return token.strip()

    # 2. Cookie: omni_nsfw_token
    cookie_str = handler.headers.get("Cookie", "")
    if "omni_nsfw_token=" in cookie_str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("omni_nsfw_token="):
                return part.split("=", 1)[1].strip()

    # 3. Query Param: ?token=xxx
    if hasattr(handler, "path") and "token=" in handler.path:
        try:
            import urllib.parse
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            t_list = qs.get("token")
            if t_list:
                return t_list[0].strip()
        except Exception:
            pass

    return None

def is_request_authorized(handler, is_local: bool) -> bool:
    """检查请求是否具备访问 NSFW/成人专区的权限。

    本机客户端（127.0.0.1 / 本机屏幕）始终自动放行；非本机客户端（局域网手机/电脑
    或广域网）必须携带有效 Token。

    Args:
        handler: BaseHTTPRequestHandler 实例，用于提取 Token。
        is_local: 该请求是否来自本机。

    Returns:
        bool: 有权限返回 True。
    """
    if is_local:
        return True

    token = extract_token_from_handler(handler)
    return is_token_valid(token)
