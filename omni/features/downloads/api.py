"""下载中心 API：会在本机拉起 tools/crawlers/ 里的脚本抓取/解压，仅限 Steam Deck 本机。"""
from omni.core.http import Api
from omni.features.downloads import service as downloads

api = Api("downloads")

LOCAL_ONLY = lambda req: req.error(403, "Forbidden: download center is local-only")  # noqa: E731


@api.get("/api/downloads/types", deny=LOCAL_ONLY)
def types(req):
    return req.json(downloads.list_job_types())


@api.get("/api/downloads/jobs", deny=LOCAL_ONLY)
def jobs(req):
    return req.json(downloads.list_jobs())


@api.get("/api/downloads/jobs/{job_id}", deny=LOCAL_ONLY)
def job(req):
    j = downloads.get_job(req.params["job_id"])
    return req.json(j or {"error": "任务不存在"}, 200 if j else 404)


@api.post("/api/downloads/start", deny=LOCAL_ONLY)
def start(req):
    b = req.json_body()
    try:
        job_id = downloads.start_job(b.get("type", ""), b.get("params", {}) or {})
        return req.json({"success": True, "job_id": job_id})
    except ValueError as e:
        return req.json({"success": False, "error": str(e)}, 400)
