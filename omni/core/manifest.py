"""读取 omni/manifest.json（UI 唯一数据源），文件改动后自动重新加载。"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest.json")
_cache = {"mtime": None, "data": None}


def load() -> dict:
    mtime = os.path.getmtime(PATH)
    if _cache["data"] is None or _cache["mtime"] != mtime:
        with open(PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("_doc", None)
        _cache.update(mtime=mtime, data=data)
    return _cache["data"]


def section(section_id: str):
    return next((s for s in load()["sections"] if s["id"] == section_id), None)


def access(section_id: str) -> str:
    s = section(section_id)
    if s is None:
        raise KeyError(f"manifest has no section '{section_id}'")
    return s.get("access", "public")


def section_ids() -> list:
    return [s["id"] for s in load()["sections"]]
