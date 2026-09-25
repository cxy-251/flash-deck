#!/usr/bin/env python3
"""
运行保存好的任务：var/config/crawler_tasks/<名字>.task.json
    {"label": "说明", "script": "media_fetch.py", "args": ["...", "--album", "..."]}
参数里可以用占位符（见 _common.expand）：{url:站点键} = endpoints 里的站点根地址，
{tasks} = 任务目录（放剧本/映射表等数据文件），{inbox} = 收件箱目录，{home}/{games}/{sd}… = 基础目录。

    run_task.py --list
    run_task.py audio_fenghuang
"""
import json
import os
import subprocess
import sys

import _common as c

HERE = os.path.dirname(os.path.abspath(__file__))


def list_tasks() -> list:
    """[(名字, 说明)]，按名字排序。"""
    out = []
    if os.path.isdir(c.paths.CRAWLER_TASKS):
        for f in sorted(os.listdir(c.paths.CRAWLER_TASKS)):
            if f.endswith(".task.json"):
                try:
                    with open(os.path.join(c.paths.CRAWLER_TASKS, f), "r", encoding="utf-8") as fh:
                        label = json.load(fh).get("label", "")
                except (OSError, ValueError):
                    label = "(无法读取)"
                out.append((f[:-len(".task.json")], label))
    return out


def load(name: str) -> dict:
    path = os.path.join(c.paths.CRAWLER_TASKS, f"{name}.task.json")
    if not os.path.exists(path):
        raise SystemExit(f"没有这个任务：{name}（用 --list 查看）")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    p = c.parser("运行保存好的下载任务")
    p.add_argument("task", nargs="?", help="任务名（文件名去掉 .task.json）")
    p.add_argument("--task", dest="task_opt", help="同上（下载中心用）")
    p.add_argument("--list", action="store_true", help="列出全部任务")
    args = p.parse_args()
    name = args.task or args.task_opt
    if args.list or not name:
        for n, label in list_tasks():
            print(f"{n:32s} {label}")
        return
    task = load(name)
    script = os.path.join(HERE, task["script"])
    if not os.path.exists(script) or os.path.dirname(os.path.abspath(script)) != HERE:
        raise SystemExit(f"任务引用的脚本不存在：{task['script']}")
    argv = c.expand(list(task.get("args", [])))
    print(f"▶ {task.get('label', name)}")
    sys.stdout.flush()
    raise SystemExit(subprocess.call([sys.executable, "-u", script] + argv, cwd=HERE))


if __name__ == "__main__":
    main()
