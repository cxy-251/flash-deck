"""
路径守卫：所有路径只能从 omni.core.paths（程序/状态路径）、omni.core.settings（外部工具与配置）、
omni.core.library（资源库）拿。其它模块里出现写死的家目录/挂载点/expanduser，测试直接失败——
防止「改一个位置要满项目找」的霰弹式修改再长回来。

    .venv/bin/python -m pytest tests/test_path_guard.py   或   .venv/bin/python tests/test_path_guard.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {
    "omni/core/paths.py",
    "omni/core/settings.py",
    "omni/core/library.py",
    "omni/core/migrate.py",     # 读取 v2 的旧位置，迁移完成即可删除
}
PATTERNS = [
    (re.compile(r"expanduser\("), "expanduser()：用户路径请放进 settings.DEFAULTS / paths"),
    (re.compile(r"/home/\w+"), "写死的家目录"),
    (re.compile(r"/run/media|(?<![\w.])/media/\w+"), "写死的挂载点"),
    (re.compile(r"\bSCRIPT_DIR\b"), "SCRIPT_DIR：程序路径请用 omni.core.paths"),
    (re.compile(r"\bPath\.home\(\)"), "Path.home()：请用 paths.HOME 或 settings"),
]
SCAN_DIRS = ["omni", "main.py"]


def iter_py_files():
    for entry in SCAN_DIRS:
        full = os.path.join(REPO, entry)
        if os.path.isfile(full):
            yield entry
            continue
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    yield os.path.relpath(os.path.join(root, f), REPO)


def find_violations():
    found = []
    for rel in iter_py_files():
        if rel in ALLOWED:
            continue
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                code = line.split("#", 1)[0]
                for pat, why in PATTERNS:
                    if pat.search(code):
                        found.append(f"{rel}:{lineno}: {why}\n    {line.rstrip()}")
    return found


def test_no_hardcoded_paths():
    violations = find_violations()
    assert not violations, "\n".join(violations)


if __name__ == "__main__":
    v = find_violations()
    print("\n".join(v) or "OK: no hardcoded paths")
    sys.exit(1 if v else 0)
