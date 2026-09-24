"""
独立游戏 / PC 应用启动器：在 Steam Deck 本机拉起子进程（Linux 原生、Ren'Py、Lime3DS、
Proton/Wine 运行 .exe），stdout/stderr 落到 var/logs/games/，退出时回调通知大厅。
"""
import os
import re
import shutil
import subprocess
import sys
import threading

from omni.core import paths, process, settings
from omni.core.log import log
from omni.features.games import registry

PROTON_NAMES = ["Proton - Experimental", "Proton 11.0", "Proton 10.0", "Proton 9.0 (Beta)",
                "Proton 8.0", "Proton 7.0", "Proton 5.13"]
UE5_HINTS = ["Shipping", "Win64", "UTW_", "LoserIsekai", "UE5", "Unreal"]


def proton_command(exe_path, game=None):
    """给 .exe 选运行容器：系统 wine 优先，否则用 Steam 装的 Proton（有专属 compatdata 的软件用专属容器）。"""
    game = game or {}
    if sys.platform == "win32":
        return [exe_path], os.environ.copy()
    if shutil.which("wine"):
        return ["wine", exe_path], os.environ.copy()

    steam_root = settings.tool("steam_root")
    prefix = None
    if game.get("proton_appid"):
        cand = os.path.join(steam_root, "steamapps", "compatdata", str(game["proton_appid"]))
        if os.path.exists(cand):
            prefix = cand
    prefix = prefix or settings.tool("proton_prefix")
    common = os.path.join(steam_root, "steamapps", "common")
    for name in PROTON_NAMES:
        proton = os.path.join(common, name, "proton")
        if not os.path.exists(proton):
            continue
        env = os.environ.copy()
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = steam_root
        env["STEAM_COMPAT_DATA_PATH"] = prefix
        os.makedirs(prefix, exist_ok=True)
        gid = game.get("id") or ""
        if "unreal" in (gid + exe_path).lower() or any(k in exe_path for k in UE5_HINTS):
            # UE5：关掉异常重抛限制与崩溃上报，避免 "FATAL: exception not rethrown"
            env.update({
                "PROTON_NO_ESYNC": "0", "PROTON_NO_FSYNC": "0", "WINE_LARGE_ADDRESS_AWARE": "1",
                "DXVK_ASYNC": "1", "DXVK_STATE_CACHE": "1", "__GL_SHADER_DISK_CACHE": "1",
                "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP": "1", "UE_DISABLE_CRASH_REPORTER": "1",
                "UE_NO_CRASH_REPORT": "1",
            })
        return [proton, "run", exe_path], env
    return None, None


def _chmod_x(path):
    try:
        os.chmod(path, 0o755)
    except Exception:
        pass


def build_command(game):
    """-> (cmd, env) ；找不到可用运行时返回 (None, None)。"""
    engine = game.get("engine", "wine")
    exe = game.get("exe_path")
    has_exe = bool(exe and os.path.exists(exe))
    cmd, env = None, os.environ.copy()

    if engine == "renpy":
        if has_exe and exe.endswith((".sh", ".py")):
            _chmod_x(exe)
            cmd = [exe]
        elif has_exe and exe.endswith(".exe"):
            cmd, env = proton_command(exe, game)
        elif os.path.exists(settings.tool("renpy_sdk")):
            cmd = [settings.tool("renpy_sdk"), game["root"]]
    elif engine == "3ds":
        lime = os.path.join(settings.tool("lime3ds_dir"), "Lime3DS.AppImage")
        if not os.path.exists(lime):
            lime = shutil.which("lime3ds") or os.path.join(paths.HOME, ".local", "bin", "lime3ds")
        if has_exe and exe.endswith((".sh", ".AppImage")):
            _chmod_x(exe)
            cmd = [exe]
        elif has_exe:
            cmd = [lime, exe]
    elif has_exe:
        if exe.endswith(".exe"):
            cmd, env = proton_command(exe, game)
        else:
            _chmod_x(exe)
            cmd = [exe]

    if cmd:
        cmd = list(cmd) + [str(a) for a in game.get("args") or []]
        env = dict(env or os.environ)
        env.update({str(k): str(v) for k, v in (game.get("env") or {}).items()})
    return cmd, env


def launch(game_id: str, title: str, on_exit=None):
    """-> (ok, message)。同一个游戏在运行中时拒绝重复启动。"""
    if game_id in process.RUNNING_GAME_IDS:
        log("WARN", f"游戏 [{title}] 已经在运行中，忽略重复启动请求", tag="Launcher")
        return False, "游戏已在运行中"
    game = registry.get(game_id)
    if not game:
        return False, f"未找到游戏配置: {game_id}"
    game_id = game["id"]
    cmd, env = build_command(game)
    if not cmd:
        log("ERROR", f"未找到可用的独立游戏/软件运行时 (Wine/Proton 未就绪) ({game_id})", tag="Launcher")
        return False, "未找到可用的独立游戏运行时 (Wine/Proton 未就绪)"

    exe = game.get("exe_path")
    cwd = os.path.dirname(exe) if (exe and os.path.exists(exe)) else game["root"]
    env.update({"LANG": "zh_CN.UTF-8", "LC_ALL": "zh_CN.UTF-8", "WINEDEBUG": "-all"})
    process.RUNNING_GAME_IDS.add(game_id)

    def runner():
        log_path = paths.game_log(re.sub(r"\W+", "_", str(game_id)).strip("_"))
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log("INFO", f"启动独立游戏: [{title}] (工作目录: {cwd})", tag="Launcher")
        log("DEBUG", f"命令行参数: {' '.join(cmd)}", tag="Launcher")
        log("DEBUG", f"独立进程标准输出/错误将记录至: {log_path}", tag="Launcher")
        proc = None
        try:
            with open(log_path, "wb") as out:
                proc = subprocess.Popen(cmd, cwd=cwd, env=env, preexec_fn=process.set_pdeathsig,
                                        start_new_session=True, stdout=out, stderr=subprocess.STDOUT)
                process.track(proc)
                log("INFO", f"独立进程已在 Steam Deck 本机成功启动: [{title}] (PID: {proc.pid})", tag="Launcher")
                rc = proc.wait()
            log("INFO" if rc == 0 else "WARN", f"独立进程已退出: [{title}] (退出码: {rc})", tag="Launcher")
            if rc != 0:
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                        tail = "".join(lf.readlines()[-10:]).strip()
                    if tail:
                        log("ERROR", f"游戏 [{title}] 异常退出末尾日志:\n{tail}", tag="Launcher")
                except Exception:
                    pass
        except Exception as e:
            log("ERROR", f"独立游戏运行异常 ({game_id}): {e}", tag="Launcher")
        finally:
            if proc is not None:
                process.untrack(proc)
            process.RUNNING_GAME_IDS.discard(game_id)
            if on_exit:
                try:
                    on_exit()
                except Exception:
                    pass

    threading.Thread(target=runner, daemon=True, name=f"game-{game_id}").start()
    return True, "已在 Steam Deck 屏幕启动游戏"
