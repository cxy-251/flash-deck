"""技术文档 API：资源管理器式浏览（多个资源库的 media_library/docs 合并显示）。
文档正文读取与小说共用阅读器接口 /api/novels/read（.md/.rst 公开可读）。"""
from omni.core.http import Api
from omni.features.novels import service as novels

api = Api("docs")


@api.get("/api/docs/explorer")
def explorer(req):
    return req.json(novels.get_docs_explorer(sub_dir=req.arg("dir"), q=req.arg("q"), doc_filter=req.arg("ext", "all")))


@api.get("/api/docs/library")
def library(req):
    return req.json(novels.get_docs_library(q=req.arg("q"), doc_filter=req.arg("ext", "all")))
