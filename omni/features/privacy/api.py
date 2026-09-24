"""NSFW 隐私锁 API：解锁（签发 token）、重新锁定、改密码、查询当前请求的解锁状态。"""
from omni.core.http import Api
from omni.features.privacy import service as privacy

api = Api(access_level="public")


@api.get("/api/auth/status")
def status(req):
    return req.json({"is_local": req.is_local, "unlocked": req.nsfw_ok})


@api.post("/api/auth/unlock")
def unlock(req):
    body = req.json_body()
    remember = body.get("remember", True)
    if not privacy.verify_password(body.get("password", "")):
        return req.json({"success": False, "error": "密码错误，请重试"}, 400)
    token = privacy.create_auth_token(days=7 if remember else 1)
    max_age = 7 * 86400 if remember else 86400
    return req.json({"success": True, "token": token, "unlocked": True},
                    headers={"Set-Cookie": f"omni_nsfw_token={token}; Path=/; Max-Age={max_age}; SameSite=Lax"})


@api.post("/api/auth/lock")
def lock(req):
    token = privacy.extract_token_from_handler(req.handler)
    if token:
        privacy.revoke_auth_token(token)
    return req.json({"success": True, "unlocked": False},
                    headers={"Set-Cookie": "omni_nsfw_token=; Path=/; Max-Age=0; SameSite=Lax"})


@api.post("/api/auth/change_password")
def change_password(req):
    body = req.json_body()
    res = privacy.change_password(body.get("old_password", ""), body.get("new_password", ""))
    return req.json(res, 200 if res.get("success") else 400)
