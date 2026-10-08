#!/usr/bin/env python3
"""
SC2 对局核心（原 sc2Mod/runner.py，按用户要求搬到 omni-deck：sc2Mod 只留做 mod 用的东西）。
用 burnysc2 的组局逻辑（久经考验，能正确加载地图、不秒胜），把 SC2 通过 proton-wine
垫片在 Steam 容器里拉起来。realtime，只有你一个真人玩家，其余全是电脑（1v1/2v2/3v3/4v4+ 都行）。

支持多电脑对手：burnysc2 的 run_game() 表面上是给"1 真人 vs 1 对手"设计的，但只要玩家列表里
"真人/Bot"角色只有一个（其余全是 Computer），它走的分支（main.py 的 _host_game 单进程路径）
其实原样把整个玩家列表转给 RequestCreateGame 的 player_setup —— 而这个协议字段本来就是
repeated，天生支持任意人数。实测直接给 `players = [Human(...), Computer(...), Computer(...), ...]`
就能开出真正的多人对战，不用自己重写 AI-API 建局逻辑。

烘焙 mod 进地图（bake.py + _bake_inner.py + lib/libstorm.so）还留在 ~/Games/claude/omniMod/sc2Mod/ —
那是"做 mod"的活儿，这里只是 import 它来用。

单独跑一局（在 omni-deck 目录下）：
  .venv/bin/python -m omni.features.sc2.runner --map BlackburnAIE --race P \
    --opponents '[{"race":"T","difficulty":"cheatinsane"},{"race":"Z","difficulty":"veryhard"}]'
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from omni.core import settings  # noqa: E402

HERE = Path(__file__).resolve().parent
SC2_ROOT = Path(settings.tool("sc2_dir"))
SC2MOD_DIR = settings.tool("sc2mod_dir")

# —— 让 burnysc2 走 Wine 分支，并用我们的 proton 垫片（跟本文件在同一目录）——
os.environ.setdefault("SC2PF", "WineLinux")
os.environ.setdefault("SC2PATH", str(SC2_ROOT))
os.environ.setdefault("WINE", str(HERE / "proton-wine"))
os.environ.setdefault("SC2MOD_COMPAT_DATA", settings.tool("proton_prefix"))
os.environ.setdefault("SC2_TIMEOUT", "180")   # 起 SC2 给足时间

from sc2 import maps                       # noqa: E402
from sc2.data import AIBuild, Difficulty, Race, Result  # noqa: E402
from sc2.main import run_game              # noqa: E402
from sc2.player import Computer, Human     # noqa: E402

RACE = {"T": Race.Terran, "P": Race.Protoss, "Z": Race.Zerg, "R": Race.Random}
DIFF = {
    "veryeasy": Difficulty.VeryEasy, "easy": Difficulty.Easy, "medium": Difficulty.Medium,
    "mediumhard": Difficulty.MediumHard, "hard": Difficulty.Hard, "harder": Difficulty.Harder,
    "veryhard": Difficulty.VeryHard,
    "cheatvision": Difficulty.CheatVision, "cheatmoney": Difficulty.CheatMoney,
    "cheatinsane": Difficulty.CheatInsane,   # 残酷3
}
AIB = {
    "random": AIBuild.RandomBuild, "rush": AIBuild.Rush, "timing": AIBuild.Timing,
    "power": AIBuild.Power, "macro": AIBuild.Macro, "air": AIBuild.Air,
}


def _import_bake():
    """bake.py 留在 sc2Mod（那是"做 mod"的部分），这里跨项目 import 它。"""
    if SC2MOD_DIR not in sys.path:
        sys.path.insert(0, SC2MOD_DIR)
    import bake  # noqa
    return bake


def _kill_prefix_leftovers(since: float) -> None:
    """杀掉本局期间在 omni-deck Wine 前缀里起的所有残留进程（winedevice.exe 等）。

    上面 SIGKILL 掉 SC2_x64.exe 之后 wineserver 跟着没了，但 Wine 的驱动服务进程
    winedevice.exe 会留下来当孤儿——连不上 wineserver 就原地空转，每个吃 10~25% CPU，
    一局留一个，打几局就把 CPU 吃满；还会把 omni-deck 的 Steam 启动（reaper）拖着不退，
    Steam 一直显示 omni-deck 在运行。

    只杀"这一局开始之后才起的、WINEPREFIX 指向 omni-deck 前缀"的进程，同一个前缀里
    别的时间点起的 Windows 游戏不会被误杀。

    Args:
        since: 本局开始时的 time.time()。
    """
    import signal
    prefix = os.environ["SC2MOD_COMPAT_DATA"]   # 模块顶部已 setdefault 成 settings 里的 proton_prefix
    try:
        clk = os.sysconf("SC_CLK_TCK")
        with open("/proc/stat") as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith("btime"))
    except Exception as e:
        print(f"[sc2] 读不到系统启动时间，跳过前缀残留清理: {e}")
        return
    killed = []
    me = os.getpid()
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        try:
            with open(f"/proc/{d}/environ", "rb") as f:
                env = f.read()
            if f"WINEPREFIX={prefix}".encode() not in env:
                continue
            with open(f"/proc/{d}/stat") as f:
                start_ticks = int(f.read().rsplit(")", 1)[1].split()[19])
            if btime + start_ticks / clk < since - 1:
                continue
            os.kill(int(d), signal.SIGKILL)
            killed.append(d)
        except (OSError, ValueError, IndexError):
            continue
    if killed:
        print(f"[sc2] 清理了本局留下的 Wine 残留进程: {killed}")


def _force_kill_lingering_sc2() -> None:
    """burnysc2 结束时只 terminate() 它直接 Popen 出来的那个进程——也就是 proton-wine 垫片，
    真正的 SC2_x64.exe 是 SteamLinuxRuntime + Proton 往下好几层子进程，SIGTERM 不一定传得到底
    （踩过这个坑：投降/结束后窗口卡成黑屏不关）。这里兜底直接按进程名找真正的游戏进程，
    收不到正常退出信号就 SIGKILL，不管上面几层容器转发得对不对。"""
    import subprocess
    try:
        out = subprocess.run(["pgrep", "-f", "SC2_x64.exe"], capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.split() if p.isdigit()]
        for pid in pids:
            subprocess.run(["kill", "-9", pid], timeout=3)
        if pids:
            print(f"[sc2] 兜底清理了残留的 SC2_x64.exe 进程: {pids}")
    except Exception as e:
        print(f"[sc2] 兜底清理进程时出错（不影响结果）: {e}")


WINDOW_LOST_GRACE = 15   # 秒：窗口连续这么久"既不可见也不是最小化"才算没了


def _sc2_window_states() -> list[str] | None:
    """返回 SC2_x64.exe 名下所有 X 窗口的 WM_STATE（"Normal"/"Iconic"/"Withdrawn"）。

    SC2 通过 Proton 跑在 Xwayland 上，窗口的 _NET_WM_PID 就是 SC2_x64.exe 的 pid。
    最小化 = Iconic；窗口被撤掉（2026-10-08 实测：D3D9 设备反复丢失后窗口变成 Withdrawn，
    游戏进程和对局还在跑、照常给 burnysc2 发数据，但人已经看不到也切不回去）= Withdrawn/没有 WM_STATE。

    Returns:
        list[str] | None: 各窗口状态；SC2 进程不在或查询工具出错时返回 None（不做判断）。
    """
    import subprocess
    try:
        pids = subprocess.run(["pgrep", "-f", "SC2_x64.exe"], capture_output=True, text=True, timeout=5).stdout.split()
        if not pids:
            return None
        states = []
        for pid in pids:
            wins = subprocess.run(["xdotool", "search", "--pid", pid], capture_output=True, text=True, timeout=5).stdout.split()
            for w in wins:
                out = subprocess.run(["xprop", "-id", w, "WM_STATE"], capture_output=True, text=True, timeout=5).stdout
                states.append("Normal" if "Normal" in out else "Iconic" if "Iconic" in out else "Withdrawn")
        return states
    except Exception:
        return None


def _watch_sc2_window(stop, lost: dict) -> None:
    """对局期间盯着 SC2 窗口：窗口出现过之后，连续 WINDOW_LOST_GRACE 秒找不到可见/最小化的窗口，
    就当游戏"闪退"处理——SIGKILL 掉 SC2，让 run_game 结束，上层能及时知道对局没了。

    burnysc2 只认 websocket：窗口没了但进程还在发数据时它会一直等下去，omni-deck 也就一直
    显示"对局进行中"、不让再开新局。

    Args:
        stop: threading.Event，对局结束时置位，线程退出。
        lost: 共享字典，判定窗口丢失时写入 lost["reason"]。
    """
    seen = False
    missing_since = None
    while not stop.wait(3):
        states = _sc2_window_states()
        if states is None:
            missing_since = None
            continue
        if any(s in ("Normal", "Iconic") for s in states):
            seen = True
            missing_since = None
            continue
        if not seen:
            continue   # 还在启动，窗口没出来
        missing_since = missing_since or time.monotonic()
        if time.monotonic() - missing_since >= WINDOW_LOST_GRACE:
            lost["reason"] = f"SC2 窗口消失（{WINDOW_LOST_GRACE} 秒内既不可见也没最小化，疑似闪退），已结束对局"
            print(f"[sc2] {lost['reason']}", flush=True)
            _force_kill_lingering_sc2()
            return


def play_one(sel: dict) -> Result | list | None:
    """按前端选好的地图/种族/对手/mod 组一局并通过 burnysc2 拉起游戏。

    Args:
        sel: 选局参数字典，含 map/race/opponents（对手列表，每项含 race/difficulty/
            ai_build）/mods（可选）/cheat（可选，历史兼容字段）。

    Returns:
        Result | list | None: burnysc2 run_game() 的原始返回值（对局结果）。
    """
    bake = _import_bake()
    mods = sel.get("mods") or (["5xHarvest"] if sel.get("cheat") else [])
    map_name = bake.bake(sel["map"], mods) if mods else sel["map"]
    game_map = maps.get(map_name)
    opponents = sel["opponents"]  # [{"race":..,"difficulty":..,"ai_build":..}, ...]，至少 1 个
    # fullscreen=True -> burnysc2 加 "-displayMode 1"（SC2 标准命令行参数），不然默认窗口模式
    players = [Human(RACE[sel["race"].upper()], fullscreen=True)]
    for o in opponents:
        players.append(Computer(
            RACE[o["race"].upper()],
            DIFF[o["difficulty"]],
            AIB.get(o.get("ai_build", "random"), AIBuild.RandomBuild),
        ))
    desc = ", ".join(f'{o["race"]}/{o["difficulty"]}' for o in opponents)
    print(f"[sc2] 开一局：{sel['map']}  你={sel['race']}  电脑({len(opponents)}) = {desc}")
    started = time.time()
    import threading
    stop, lost = threading.Event(), {}
    threading.Thread(target=_watch_sc2_window, args=(stop, lost), daemon=True).start()
    try:
        res = run_game(game_map, players, realtime=True)
    except Exception:
        if lost:
            raise RuntimeError(lost["reason"]) from None
        raise
    else:
        if lost:   # SC2 被杀后 burnysc2 也可能不抛异常、直接返回 None/空结果
            raise RuntimeError(lost["reason"])
        return res
    finally:
        stop.set()
        _force_kill_lingering_sc2()
        _kill_prefix_leftovers(started)


def main() -> None:
    """命令行入口：解析 sc2_panel_service.py 传来的参数，跑一局并打印结果。

    由 sc2_panel_service.py 通过 `uv run python sc2_runner.py --map ... --json`
    以子进程方式调用；`--json` 打开时结束时会额外打印一行机器可读的结果供父进程解析。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--race", default="P")
    ap.add_argument("--opponents", required=True,
                     help='JSON 数组，如 \'[{"race":"T","difficulty":"cheatinsane"}]\'')
    ap.add_argument("--mods", default="", help="逗号分隔的 mod key，如 5xHarvest")
    ap.add_argument("--json", action="store_true", help="结束时额外打印一行机器可读结果")
    a = ap.parse_args()
    import json as _json
    sel = {
        "map": a.map, "race": a.race,
        "opponents": _json.loads(a.opponents),
        "mods": [m for m in a.mods.split(",") if m],
    }
    err = None
    try:
        res = play_one(sel)
    except Exception as e:
        res = None
        err = str(e)
    print(f"[sc2] 结果：{res if res is not None else err}")

    if a.json:
        import json
        payload = {
            "map": a.map,
            "result": (res.name if hasattr(res, "name") else
                       [r.name if hasattr(r, "name") else str(r) for r in res] if isinstance(res, list) else
                       str(res) if res is not None else None),
            "error": err,
        }
        print("SC2MOD_RESULT: " + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
