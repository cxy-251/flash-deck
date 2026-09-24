"""
下载中心：把 tools/crawlers/ 里的通用脚本包装成「填参数 → 后台运行 → 看日志」的任务，
供前端下载中心面板调用。每类任务一个脚本，参数都来自表单；站点 Cookie、代理等个人参数在
var/config/crawler_secrets.json；常用的一组参数可以存成 var/config/crawler_tasks/*.task.json，
在「运行保存的任务」里一键执行。

字段规格（前端据此生成输入框/下拉框）：
  name/label/required/default/options   基本属性
  positional: True   作为位置参数传给脚本
  multi: True        按空白/换行拆成多个值（位置参数就是多个参数，否则重复 --name）
  flag: True         下拉「否/是」，选「是」时传一个不带值的 --name
"""
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from omni.core import paths

CRAWLERS_DIR = paths.CRAWLERS
PYTHON_BIN = paths.VENV_PYTHON if os.path.exists(paths.VENV_PYTHON) else "python3"

_jobs = {}
_jobs_lock = threading.Lock()
_MAX_LOG_LINES = 2000

NSFW = {"name": "nsfw", "label": "存到 NSFW 分区", "flag": True, "options": ["否", "是"], "default": "否"}

JOB_TYPES = {
    "task": {
        "label": "▶ 运行保存的任务（var/config/crawler_tasks）",
        "script": "run_task.py",
        "fields": [{"name": "task", "label": "任务", "required": True, "options": []}],
    },
    "media_fetch": {
        "label": "🎧 视频站音频 → 有声书（YouTube / B站 / 播放列表）",
        "script": "media_fetch.py",
        "fields": [
            {"name": "urls", "label": "视频/播放列表网址（多个用空格分隔，可写 网址|文件名）", "required": True,
             "positional": True, "multi": True},
            {"name": "album", "label": "专辑名", "required": True},
            {"name": "mode", "label": "保存方式", "options": ["files", "m4b"], "default": "files"},
            {"name": "items", "label": "只取第几集（如 1-6,9，可选）"},
            NSFW,
        ],
    },
    "tts_drama": {
        "label": "🎙️ 文本 → 多角色广播剧（Edge TTS）",
        "script": "tts_drama.py",
        "fields": [
            {"name": "text", "label": "小说文本文件路径", "required": True},
            {"name": "title", "label": "单集标题（可选）"},
            {"name": "roles", "label": "角色音色配置 JSON 路径（可选）"},
            {"name": "album", "label": "专辑名", "required": True},
            NSFW,
        ],
    },
    "blog_stories": {
        "label": "📚 博客站短篇 → 合卷 EPUB",
        "script": "blog_novels.py",
        "subcommand": "stories",
        "fields": [
            {"name": "site", "label": "站点根地址", "required": True},
            {"name": "label", "label": "标签名（多个用空格分隔）", "required": True, "multi": True},
            {"name": "prefix", "label": "书名前缀", "default": "短篇合集"},
            {"name": "chunk", "label": "每卷篇数", "default": "30"},
            NSFW,
        ],
    },
    "blog_book": {
        "label": "📖 博客站标签 → 一本长篇 EPUB",
        "script": "blog_novels.py",
        "subcommand": "book",
        "fields": [
            {"name": "url", "label": "该书的标签页网址", "required": True},
            {"name": "title", "label": "书名", "required": True},
            {"name": "folder", "label": "输出子目录", "default": "长篇"},
            NSFW,
        ],
    },
    "apk_books": {
        "label": "📱 APK 内置书库 → EPUB",
        "script": "apk_books.py",
        "fields": [
            {"name": "apk", "label": "APK 文件路径", "required": True},
            {"name": "root", "label": "书库目录（如 assets/book/世界名著）", "required": True},
            {"name": "layout", "label": "书库布局", "options": ["folders", "files"], "default": "folders"},
            {"name": "folder", "label": "输出子目录", "required": True},
            {"name": "author", "label": "作者", "default": "佚名"},
        ],
    },
    "epub_build": {
        "label": "🗂️ 本地 md/txt 目录 → EPUB",
        "script": "epub_build.py",
        "fields": [
            {"name": "dir", "label": "目录路径", "required": True},
            {"name": "title", "label": "书名", "required": True},
            {"name": "author", "label": "作者", "default": "佚名"},
            {"name": "folder", "label": "输出子目录", "required": True},
        ],
    },
    "archive_unpack": {
        "label": "📦 伪装压缩包游戏还原（.mp4/.mkv → 游戏文件夹）",
        "script": "archive_unpack.py",
        "fields": [
            {"name": "source", "label": "伪装文件完整路径", "required": True},
            {"name": "category", "label": "目标游戏分类", "default": "renpy",
             "options": ["renpy", "steam", "unity", "godot", "unreal", "wine", "app", "rpg", "slg"]},
            {"name": "name", "label": "游戏文件夹名（如 043 - New Game Title）", "required": True},
        ],
    },
}


def _saved_tasks() -> list:
    sys.path.insert(0, CRAWLERS_DIR)
    try:
        import run_task
        return [n for n, _label in run_task.list_tasks()]
    except Exception:
        return []
    finally:
        sys.path.remove(CRAWLERS_DIR)


def list_job_types():
    """前端表单规格（「保存的任务」的下拉选项每次现读任务目录）。"""
    out = []
    for job_id, spec in JOB_TYPES.items():
        fields = [dict(f) for f in spec["fields"]]
        if job_id == "task":
            fields[0]["options"] = _saved_tasks()
            fields[0]["default"] = fields[0]["options"][0] if fields[0]["options"] else ""
        out.append({"id": job_id, "label": spec["label"], "fields": fields})
    return out


def _build_cmd(job_type, params):
    """表单参数 -> 命令行。空值字段跳过（用脚本自己的默认值）。"""
    spec = JOB_TYPES[job_type]
    cmd = [PYTHON_BIN, "-u", os.path.join(CRAWLERS_DIR, spec["script"])]
    if spec.get("subcommand"):
        cmd.append(spec["subcommand"])
    for f in spec["fields"]:
        val = str(params.get(f["name"]) or "").strip()
        if not val:
            continue
        if f.get("flag"):
            if val in ("是", "true", "1", "yes"):
                cmd.append(f"--{f['name']}")
            continue
        values = [v for v in re.split(r"\s+", val) if v] if f.get("multi") else [val]
        for v in values:
            cmd += [v] if f.get("positional") else [f"--{f['name']}", v]
    return cmd


def _job_public(job):
    """把内部任务字典转成可以直接 json.dumps 返回给前端的公开字段子集。

    Args:
        job: `_jobs` 里的内部任务记录。

    Returns:
        dict: 仅含前端需要展示的字段。
    """
    return {
        "id": job["id"],
        "type": job["type"],
        "label": job["label"],
        "params": job["params"],
        "status": job["status"],
        "log": job["log"],
        "returncode": job["returncode"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


def start_job(job_type, params):
    """校验参数并在后台线程里启动一个下载任务，立即返回 job_id（不阻塞等待任务完成）。

    Args:
        job_type: JOB_TYPES 里的任务类型 key。
        params: 前端提交的表单参数字典。

    Returns:
        str: 新建任务的 job_id，用于后续轮询 get_job()。

    Raises:
        ValueError: job_type 不存在，或缺少某个必填字段。
    """
    if job_type not in JOB_TYPES:
        raise ValueError(f"未知任务类型: {job_type}")
    spec = JOB_TYPES[job_type]
    if job_type == "task" and params.get("task") not in _saved_tasks():
        raise ValueError(f"没有这个保存的任务: {params.get('task')}")
    for f in spec["fields"]:
        if f.get("required") and not str(params.get(f["name"], "")).strip():
            raise ValueError(f"缺少必填参数: {f['label']}")

    cmd = _build_cmd(job_type, params)
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "type": job_type,
        "label": spec["label"] if job_type != "task" else f"{spec['label']} · {params.get('task')}",
        "params": params,
        "status": "running",
        "log": [],
        "returncode": None,
        "started_at": time.time(),
        "finished_at": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def _run():
        """实际执行子进程并把输出逐行写进 job["log"]（在独立线程里跑，闭包引用 cmd/job）。"""
        try:
            proc = subprocess.Popen(
                cmd, cwd=paths.REPO,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                with _jobs_lock:
                    job["log"].append(line.rstrip("\n"))
                    if len(job["log"]) > _MAX_LOG_LINES:
                        job["log"] = job["log"][-_MAX_LOG_LINES:]
            proc.wait()
            with _jobs_lock:
                job["returncode"] = proc.returncode
                job["status"] = "done" if proc.returncode == 0 else "failed"
                job["finished_at"] = time.time()
        except Exception as e:
            with _jobs_lock:
                job["log"].append(f"[ERROR] 启动任务失败: {e}")
                job["status"] = "failed"
                job["finished_at"] = time.time()

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_job(job_id):
    """查询单个任务当前状态（供前端轮询）。

    Args:
        job_id: start_job() 返回的任务 id。

    Returns:
        dict | None: 任务的公开字段字典；job_id 不存在时返回 None。
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
        return _job_public(job) if job else None


def list_jobs():
    """列出全部任务，按启动时间倒序（最新的在前）。

    Returns:
        list[dict]: 每个任务的公开字段字典。
    """
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)
        return [_job_public(j) for j in jobs]
