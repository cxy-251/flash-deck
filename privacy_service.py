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

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "privacy_config.json")
DEFAULT_PASSWORD = "deck888"


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def _load_or_init_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 首次初始化配置，使用默认密码 deck888
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
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Privacy] Failed to save config: {e}")

def verify_password(password: str) -> bool:
    """验证用户输入的密码是否正确"""
    if not password:
        return False
    config = _load_or_init_config()
    salt = config.get("salt", "")
    target_hash = config.get("password_hash", "")
    input_hash = _hash_password(password, salt)
    return secrets.compare_digest(input_hash, target_hash)

def change_password(old_password: str, new_password: str) -> Dict[str, Any]:
    """修改访问密码"""
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
    cfg = _load_or_init_config()
    cfg["tokens"] = _ACTIVE_TOKENS
    _save_config(cfg)

def create_auth_token(days: int = 7) -> str:
    """生成并记录有效期 Token"""
    _ensure_tokens_loaded()
    token = secrets.token_hex(16)
    expire_at = time.time() + (days * 86400)
    _ACTIVE_TOKENS[token] = expire_at
    _save_active_tokens()
    return token

def revoke_auth_token(token: str) -> bool:
    """撤销已授权的 Token"""
    _ensure_tokens_loaded()
    if token in _ACTIVE_TOKENS:
        del _ACTIVE_TOKENS[token]
        _save_active_tokens()
        return True
    return False

def is_token_valid(token: Optional[str]) -> bool:
    """检查客户端携带的 Token 是否处于有效期内"""
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
    """从 HTTP 请求头、Cookie 或 URL 参数提取 Token"""
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
    """
    检查请求是否具备访问 NSFW/成人专区的权限：
    - 本机客户端 (127.0.0.1 / 本机屏幕)：始终自动放行
    - 非本机客户端 (局域网手机/电脑或广域网)：必须提供有效 Token
    """
    if is_local:
        return True

    token = extract_token_from_handler(handler)
    return is_token_valid(token)
