"""短视频多联放映 API：频道列表、频道视频、槽位配置。"""
from omni.core.http import Api
from omni.features.shortvideo_matrix import service as mx

api = Api("shortvideo-matrix")


@api.get("/api/shortvideo_matrix/channels")
def channels(req):
    return req.json({"status": "ok", "channels": mx.get_channels()})


@api.get("/api/shortvideo_matrix/videos")
def videos(req):
    """分页取频道视频：一个平台动辄两万多条，整列表下发给手机太大。「随机」频道每次重新洗牌，只有一页。"""
    cid = req.arg("channel_id", "random")
    offset = max(0, req.int_arg("offset", 0))
    limit = min(500, max(1, req.int_arg("limit", 100)))
    vids = mx.get_channel_videos(cid)
    return req.json({"status": "ok", "channel_id": cid, "total": len(vids), "offset": offset,
                     "videos": [mx.public_item(it) for it in vids[offset:offset + limit]]})


@api.get("/api/shortvideo_matrix/config")
def get_config(req):
    return req.json({"status": "ok", "config": mx.load_config()})


@api.post("/api/shortvideo_matrix/config")
def save_config(req):
    data = req.json_body()
    if not isinstance(data, dict):
        return req.json({"status": "error", "error": "bad config"}, 400)
    mx.save_config(data)
    return req.json({"status": "ok"})
