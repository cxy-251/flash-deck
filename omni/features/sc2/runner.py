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
    try:
        return run_game(game_map, players, realtime=True)
    finally:
        _force_kill_lingering_sc2()


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
