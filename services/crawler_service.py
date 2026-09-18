"""
爬虫任务管理：把 crawlers/ 目录下"贴链接下载"的脚本包装成"提交任务 -> 轮询状态/日志"的
后台任务，供 hub.js 的下载面板调用。

每个任务用 subprocess 起一个独立的 crawlers/xxx.py 子进程（复用脚本自身已经写好的下载/
打包/归档逻辑，不重复实现），后台线程读取它的 stdout 逐行追加进内存日志，前端轮询 GET 接口
拿状态和日志增量，不需要 websocket。

crawlers/ 目录里其余脚本（xbookcn_* 全站分类爬取、download_1000ji/fenghuang/guichuideng、
build_english_*、extract_all_apk_books、process_archives）都是一次性/固定清单批量脚本，
没有"每次换一个链接"的输入，不适合这种"输入框+下载按钮"的交互形式，所以没有收进 JOB_TYPES。
"""
import os
import subprocess
import threading
import time
import uuid

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 本文件在 services/ 下，项目根路径是上一级
CRAWLERS_DIR = os.path.join(SCRIPT_DIR, "crawlers")
_venv_python = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
PYTHON_BIN = _venv_python if os.path.exists(_venv_python) else "python3"

_jobs = {}
_jobs_lock = threading.Lock()
_MAX_LOG_LINES = 2000

JOB_TYPES = {
    "bilibili_audiobook": {
        "label": "Bilibili 广播剧音频下载",
        "script": "audiobook_crawler.py",
        "action": "bilibili",
        "fields": [
            {"name": "bvid", "label": "BV号", "required": True},
            {"name": "album", "label": "专辑名", "default": "鬼吹灯之精绝古城"},
            {"name": "start", "label": "起始P", "default": "1"},
            {"name": "end", "label": "结束P", "default": "6"},
            {"name": "output", "label": "输出文件名（可选）", "required": False},
        ],
    },
    "youtube_audiobook": {
        "label": "YouTube 广播剧音频下载",
        "script": "audiobook_crawler.py",
        "action": "youtube",
        "fields": [
            {"name": "url", "label": "视频链接", "required": True},
            {"name": "album", "label": "专辑名", "default": "鬼吹灯之精绝古城"},
            {"name": "cookies", "label": "Cookies来源（浏览器名如 chrome，或 cookies.txt 路径，可选）", "required": False},
            {"name": "output", "label": "输出文件名（可选）", "required": False},
        ],
    },
}


def list_job_types():
    """列出所有可供前端渲染成表单的下载任务类型。

    Returns:
        list[dict]: 每项包含 id/label/fields，fields 是表单字段规格列表
        （name/label/required/default），前端据此动态生成输入框。
    """
    out = []
    for job_id, spec in JOB_TYPES.items():
        out.append({
            "id": job_id,
            "label": spec["label"],
            "fields": spec["fields"],
        })
    return out


def _build_cmd(job_type, params):
    """把表单参数拼成实际要执行的命令行。

    Args:
        job_type: JOB_TYPES 里的任务类型 key。
        params: 前端提交的表单参数字典，缺省/空值的字段会被跳过（用脚本自己的默认值）。

    Returns:
        list[str]: 传给 subprocess.Popen 的完整命令行参数列表。
    """
    spec = JOB_TYPES[job_type]
    cmd = [PYTHON_BIN, os.path.join(CRAWLERS_DIR, spec["script"]), spec["action"]]
    for f in spec["fields"]:
        name = f["name"]
        val = params.get(name)
        if val is None or str(val).strip() == "":
            continue
        cmd += [f"--{name}", str(val)]
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
    for f in spec["fields"]:
        if f.get("required") and not str(params.get(f["name"], "")).strip():
            raise ValueError(f"缺少必填参数: {f['label']}")

    cmd = _build_cmd(job_type, params)
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "type": job_type,
        "label": spec["label"],
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
                cmd, cwd=SCRIPT_DIR,
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
