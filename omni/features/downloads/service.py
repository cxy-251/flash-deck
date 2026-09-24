"""
下载中心：把 tools/crawlers/ 目录下的脚本包装成"提交任务 -> 轮询状态/日志"的后台任务，
供 hub.js 的下载中心面板调用。

每个任务用 subprocess 起一个独立的 tools/crawlers/xxx.py 子进程（复用脚本自身已经写好的下载/
打包/解压逻辑，不重复实现），后台线程读取它的 stdout 逐行追加进内存日志，前端轮询 GET 接口
拿状态和日志增量，不需要 websocket。

JOB_TYPES 里的任务分两种形态：
- 带 fields 的（如 bilibili/youtube 下载、伪装压缩包解压）：前端渲染成输入框表单，
  "action" 对应脚本 argparse 的子命令（没有子命令的脚本 action 留 None）。
- fields 为空列表的（如 xbookcn 全站爬取、guichuideng/1000ji/fenghuang 有声书批量下载）：
  这几个脚本本身没有 argparse，每次运行走的是脚本内置的固定清单/全站分类，前端只渲染一个
  "一键运行"按钮，没有输入框。

tools/crawlers/ 目录里剩下 3 个脚本（build_english_books.py、build_english_module.py、
extract_all_apk_books.py）没收进 JOB_TYPES——它们是纯本地内容生成器，没有下载/爬取这一步，
输出内容确定且已经生成过，重新跑一遍不会产生任何新结果，收进"下载中心"没有意义。
"""
import os
import subprocess
import threading
import time
import uuid

from omni.core import paths

CRAWLERS_DIR = paths.CRAWLERS
PYTHON_BIN = paths.VENV_PYTHON if os.path.exists(paths.VENV_PYTHON) else "python3"

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
    "archive_extract": {
        "label": "伪装压缩包游戏解压（.mp4/.mkv 还原成游戏文件夹）",
        "script": "process_archives.py",
        "action": None,
        "fields": [
            {"name": "type", "label": "伪装容器类型", "default": "mp4", "options": ["mp4", "mkv"]},
            {"name": "source", "label": "伪装文件完整路径", "required": True},
            {"name": "category", "label": "目标专区", "default": "renpy",
             "options": ["renpy", "steam", "unity", "godot", "unreal", "wine", "app", "rpg", "slg"]},
            {"name": "name", "label": "游戏文件夹名（如 043 - New Game Title）", "required": True},
        ],
    },
    "guichuideng_audiobook": {
        "label": "《鬼吹灯》有声书批量下载（支持断点续传）",
        "script": "download_guichuideng.py",
        "action": None,
        "fields": [],
    },
    "1000ji_audiobook": {
        "label": "《你都1000级了外面最高30级》有声书批量下载",
        "script": "download_1000ji.py",
        "action": None,
        "fields": [],
    },
    "fenghuang_audiobook": {
        "label": "《新鬼吹灯之凤凰神殿》有声书批量下载",
        "script": "download_fenghuang.py",
        "action": None,
        "fields": [],
    },
    "xbookcn_official": {
        "label": "小书屋 官方32分类全站抓取",
        "script": "xbookcn_downloader.py",
        "action": None,
        "fields": [],
    },
    "xbookcn_long": {
        "label": "小书屋 长篇小说全站抓取",
        "script": "xbookcn_long_downloader.py",
        "action": None,
        "fields": [],
    },
    "xbookcn_wave2": {
        "label": "小书屋 第二波18分类抓取",
        "script": "xbookcn_wave2_downloader.py",
        "action": None,
        "fields": [],
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
    cmd = [PYTHON_BIN, os.path.join(CRAWLERS_DIR, spec["script"])]
    if spec.get("action"):
        cmd.append(spec["action"])
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
