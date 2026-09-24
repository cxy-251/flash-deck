"""
星际争霸 2 对战面板后端服务

首页顶级卡片"⭐ 星际争霸2"背后的数据 + 对局控制层。地图缩略图抽取/去重、
快捷键安装、拉起对局全部是本项目自己的代码（runner.py / 本文件），
装在 omni-deck 自己的 venv 里（burnysc2 / s2clientprotocol / protobuf==3.20.3 等）。
SC2 本体、sc2Mod、Proton 容器的位置都在 settings.json 的 tools 里配置。

唯一还跨项目 import 的是 sc2Mod 项目里的 bake.py —— 那个项目现在专注"做 mod"：
mod 依赖表（MOD_DEPS/MOD_INFO）和把 mod 烘焙进地图副本（StormLib 改 MPQ）的逻辑留在那边，
这里只是读它的 mod 清单 + 调用它的 bake() 把 mod 焊进地图。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import mpyq
from PIL import Image

from omni.core import paths, settings

HERE = Path(__file__).resolve().parent            # proton-wine 垫片与 runner.py 在这里
SC2MOD_DIR = settings.tool("sc2mod_dir")
SC2_DIR = Path(settings.tool("sc2_dir"))
SC2_MAPS_DIR = SC2_DIR / "Maps"

THUMB_CACHE = Path(paths.CACHE) / "sc2_thumbs_v3"
# 统一正方形画布，"裁切填满"：实测 57 张图里 29 张原生就是正方形 256x256、10 张是竖版 128x256，
# 之前用横版画布硬塞会留一大圈黑边。改正方形 + cover 裁切后基本没有黑边。
# 目录名带版本号：extract_thumb() 只按"地图文件改没改"判断要不要重生成缩略图，地图本身
# 从不改动，所以生成逻辑一旦调整（比如这次从 256x144 letterbox 换成 300x300 cover 裁切），
# 光靠 mtime 判断永远不会重生成旧缓存 —— 踩过这个坑（31/35 张图还是老的 256x144 黑边版）。
# 以后再改生成逻辑，把这串数字加一即可，自动让旧缓存全部失效。
THUMB_W = THUMB_H = 300


_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "last_map": None,
    "last_mods": [],
    "last_opponents": [],  # [{"race":.., "difficulty":..}, ...]
    "last_result": None,   # 'Victory' / 'Defeat' / 'Tie' / None(还没打过) / 'Error: ...'
    "finished_at": None,
    "log_tail": "",
}


def _import_bake():
    """mod 依赖表 + 烘焙逻辑留在 sc2Mod（那是"做 mod"的部分），跨项目 import 它。"""
    if SC2MOD_DIR not in sys.path:
        sys.path.insert(0, SC2MOD_DIR)
    import bake  # noqa
    return bake


def available() -> bool:
    """星际争霸2 控制面板功能是否可用（依赖的 mod 目录和地图目录是否都存在）。

    Returns:
        bool: 两个目录都存在返回 True。
    """
    return os.path.isdir(SC2MOD_DIR) and os.path.isdir(SC2_MAPS_DIR)


# ---------- 地图缩略图 / 感知去重（原 sc2Mod/picker.py，非 UI 部分搬过来）----------

def _read_mpq_file(map_file: Path, inner_name: str) -> Optional[bytes]:
    """从 SC2 地图（MPQ 归档格式）里读出指定内部文件的原始字节。

    Args:
        map_file: .SC2Map 文件路径。
        inner_name: MPQ 归档内的文件名，如 "Minimap.tga"、"MapInfo"。

    Returns:
        Optional[bytes]: 文件内容；地图损坏或没有这个内部文件时返回 None。
    """
    try:
        return mpyq.MPQArchive(str(map_file)).read_file(inner_name)
    except Exception:
        return None


def _read_minimap_raw(map_file: Path) -> Optional[bytes]:
    """读取地图小地图缩略图的原始 TGA 字节。

    Args:
        map_file: .SC2Map 文件路径。

    Returns:
        Optional[bytes]: Minimap.tga 的原始内容，读取失败返回 None。
    """
    return _read_mpq_file(map_file, "Minimap.tga")


# 玩家人数：MapInfo 是黑盒二进制格式，没有官方文档。实测规律——每个"开放槽位/种族不限"的
# 玩家在里面留一条 [槽位号:1字节][控制类型=Open:4字节小端 01000000][种族=任意:FFFFFFFF] 记录，
# 槽位号从 1 开始连续排。扫出所有匹配记录的槽位号集合，找从 1 开始最长的连续段 = 人数上限。
# 强制种族/非常规自定义关卡图这套规律套不上，会返回 None——保守按 1v1 处理。
_SLOT_PAT = __import__("re").compile(rb".\x01\x00\x00\x00\xff\xff\xff\xff")


def _map_has_force_data(raw: bytes, n: int) -> bool:
    """SC2 的 AI-API 建局协议（RequestCreateGame/PlayerSetup）压根没有 team_id 这种字段——
    查过 Blizzard 官方 s2client-proto 源码确认的，不是这版 Python 绑定缺了。真人 vs 多电脑的
    "队伍"从哪来？完全是地图自己烘焙的 Force（编辑器里"部队"面板，几个出生点分一队、是否
    结盟）在起局时由标准 melee 初始化脚本生效，我们的建局请求完全看不见也管不了这个。

    实测规律：真做了队伍的地图（AbandonedCamp 这种）MapInfo 里玩家槽位记录后面还有一段
    "N 个出生点用两种不同顺序各排一遍"的数据块（N 前缀重复两次），推测就是"出生点顺序"
    和"按队伍分组的顺序"；纯竞技场图（Flat/Simple/Empty 系列）完全没有这段——只有单人槽位
    记录，游戏对它们的解读是每个人各自一个队（纯白热化混战，所有人都敌对），这正是"多电脑
    全变成我对手"那次的根因。所以：没有这段数据的图，就不该在 UI 上让选 1 个以上的对手。"""
    if n <= 2 or not raw:
        return False
    marker = struct.pack("<I", n)
    return raw.count(marker) >= 2


def _map_max_players(map_file: Path) -> tuple[Optional[int], bool]:
    """返回 (人数上限, 是否有真正的队伍/Force 数据)。"""
    raw = _read_mpq_file(map_file, "MapInfo")
    if not raw:
        return None, False
    idxs = {raw[m.start()] for m in _SLOT_PAT.finditer(raw)}
    n = 0
    while (n + 1) in idxs:
        n += 1
    n = min(n, 8) or None  # SC2 硬上限 8 人；0 = 没扫到任何合规记录
    has_force = _map_has_force_data(raw, n) if n else False
    return n, has_force


def _thumb_path(map_file: Path) -> Path:
    """算出某张地图对应的缩略图缓存路径（不保证文件已生成）。

    Args:
        map_file: .SC2Map 文件路径。

    Returns:
        Path: 缩略图缓存路径。
    """
    return THUMB_CACHE / f"{map_file.stem}.png"


def _autocrop_black_margin(im: "Image.Image") -> "Image.Image":
    """去掉贴着画布边缘的黑边（SC2 很多地图的 Minimap.tga 本身就在正方形画布里画了个
    菱形/异形的可玩区域，四角/四边留了一大圈纯黑 —— 不是我们缩放代码加的，是原图自带的）。

    不能直接按"暗于阈值"做 bbox：地图里本来就有暗色地形（宇宙/熔岩图），那些暗像素不该被
    当黑边裁掉。用连通域从画布边框往里 flood-fill 近黑像素，只有"贴着边缘、连成一片"的黑色
    才算黑边；地图内部单独的暗色块（哪怕再黑）不受影响。"""
    import numpy as np
    from scipy import ndimage

    arr = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = arr.shape
    black = arr <= 10
    labels, n = ndimage.label(black, structure=np.ones((3, 3)))  # 8-连通
    if n == 0:
        return im
    border_labels = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border_labels.discard(0)
    padding = np.isin(labels, list(border_labels)) if border_labels else np.zeros_like(black)
    content = ~padding
    if content.sum() < 0.15 * h * w:   # 兜底：真裁太狠了就别裁（比如整图本来就很暗）
        return im
    rows = np.where(content.any(axis=1))[0]
    cols = np.where(content.any(axis=0))[0]
    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])
    # 留一点边距，别把边界地形也切掉
    pad = max(2, round(0.03 * max(h, w)))
    top = max(0, top - pad); left = max(0, left - pad)
    bottom = min(h - 1, bottom + pad); right = min(w - 1, right + pad)
    return im.crop((left, top, right + 1, bottom + 1))


def extract_thumb(map_file: Path) -> Optional[Path]:
    """从 .SC2Map 抽 Minimap.tga → 去掉原图自带的黑边 → 裁切填满正方形画布 → 存 PNG 缓存。
    已存在就直接返回。"""
    out = _thumb_path(map_file)
    if out.exists() and out.stat().st_mtime >= map_file.stat().st_mtime:
        return out
    raw = _read_minimap_raw(map_file)
    if not raw:
        return None
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im = _autocrop_black_margin(im)
        # cover 裁切：按较大边比例放大到能盖满正方形画布，再居中裁掉多出来的部分
        scale = max(THUMB_W / im.width, THUMB_H / im.height)
        new_w, new_h = round(im.width * scale), round(im.height * scale)
        im = im.resize((new_w, new_h), Image.LANCZOS)
        left, top = (new_w - THUMB_W) // 2, (new_h - THUMB_H) // 2
        im = im.crop((left, top, left + THUMB_W, top + THUMB_H))
        THUMB_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.png")
        im.save(tmp)
        os.replace(tmp, out)      # 原子替换：进程中途被杀也不会留下半截 PNG
        return out
    except Exception:
        return None


def _minimap_fingerprint(map_file: Path):
    """32x16 灰度缩图，用于感知相似度比较（比 md5 更能抓住"几乎一样"的图）。"""
    raw = _read_minimap_raw(map_file)
    if not raw:
        return None
    try:
        import numpy as np
        im = Image.open(io.BytesIO(raw)).convert("L").resize((32, 16))
        return np.asarray(im, dtype=float)
    except Exception:
        return None


SIMILARITY_THRESHOLD = 1.0  # 32x16 灰度图平均像素差（0-255）低于此值算"同一张图"
# 实测标定：真·同图不同赛季 diff 都在 0.0~0.2；不同的图哪怕观感相近也有 2.8+；
# 完全不同的图 15~40+。1.0 留了足够安全余量，不会把不同图误判成重复。


def dedupe_maps(map_files: List[Path]) -> List[Path]:
    """同地形只留一张（按缩略图感知相似度分组，不只是字节完全一致），
    代表用最短名。烘焙产物（名字含 '__'）不进列表。"""
    import numpy as np

    candidates = sorted((p for p in map_files if "__" not in p.stem), key=lambda p: (len(p.stem), p.stem))
    groups: List[tuple] = []   # (指纹, 该组代表)
    for mf in candidates:
        fp = _minimap_fingerprint(mf)
        if fp is None:
            groups.append((None, mf))
            continue
        matched = False
        for gfp, _ in groups:
            if gfp is not None and np.abs(gfp - fp).mean() < SIMILARITY_THRESHOLD:
                matched = True
                break
        if not matched:
            groups.append((fp, mf))
    return sorted((mf for _, mf in groups), key=lambda p: p.stem.lower())


def _guess_team(stem: str, map_file: Path) -> tuple[str, int, int]:
    """返回 (team 标签, 玩家人数上限, 允许配的电脑对手数上限)。AIE 后缀（AI-Arena Extension）
    专属 1v1 天梯图池，命名规范本身就够权威，直接信；LE 后缀只代表"天梯版"，1v1/2v2/3v3/4v4
    天梯图都用这个后缀（踩过坑：TroiziniaLE 是 4v4 图，之前把所有 *LE 都当 1v1 是错的），
    一律走实测人数分档。max_opponents 在没有队伍/Force 数据的图上强制封到 1——没有 Force，
    "多个电脑"在游戏引擎眼里就是各自一伙的混战，全部敌对，不是真的分两队。"""
    if stem.endswith("AIE"):
        return "1v1", 2, 1
    n, has_force = _map_max_players(map_file)
    if n is None or n <= 2:
        return "1v1", n or 2, 1
    max_opp = (n - 1) if has_force else 1
    if n <= 4:
        return "2v2", n, max_opp
    if n <= 6:
        return "3v3", n, max_opp
    return "4v4+", n, max_opp


def list_maps() -> List[Dict[str, Any]]:
    """去重后的地图清单（同地形不同赛季只留一张），带缩略图相对名 + 分队标签。
    缩略图生成不出来的图（archive 里压根没有 Minimap.tga——见过一批老/残缺的自定义关卡图
    是这样，不是解码问题）、以及缩略图纯色一片没有任何可辨认信息的（比如全空白测试图），
    都直接从列表里剔除，不展示。"""
    import numpy as np

    files = sorted(SC2_MAPS_DIR.glob("*.SC2Map"))
    reps = dedupe_maps(files)
    out = []
    for mf in reps:
        thumb = extract_thumb(mf)
        if thumb is None:
            continue
        try:
            arr = np.asarray(Image.open(thumb).convert("RGB")).reshape(-1, 3)
        except Exception:
            thumb.unlink(missing_ok=True)   # 损坏的缓存（旧版非原子写入留下的）：删掉重新生成
            thumb = extract_thumb(mf)
            if thumb is None:
                continue
            arr = np.asarray(Image.open(thumb).convert("RGB")).reshape(-1, 3)
        if arr.std(axis=0).mean() < 2.0:   # 纯色/近纯色缩略图，没啥可看的，跳过
            continue
        team, max_players, max_opponents = _guess_team(mf.stem, mf)
        out.append({
            "stem": mf.stem,
            "thumb": f"/api/sc2/thumb/{mf.stem}.png",
            "team": team,
            "max_players": max_players,
            "max_opponents": max_opponents,
        })
    return out


def thumb_path(stem: str) -> Optional[str]:
    """按地图文件名（不含扩展名）查询已生成的缩略图路径，供前端 API 用。

    Args:
        stem: 地图文件名（不含 .SC2Map 扩展名）。

    Returns:
        Optional[str]: 缩略图路径字符串；还没生成过则返回 None。
    """
    p = THUMB_CACHE / f"{stem}.png"
    return str(p) if p.exists() else None


def list_mods() -> List[Dict[str, str]]:
    """列出 sc2Mod 里定义的全部可选 mod。

    Returns:
        List[Dict[str, str]]: 每项含 key 及 MOD_INFO 里的其余描述字段；
        sc2Mod 模块导入失败时返回 [{"error": 错误信息}]。
    """
    try:
        bake = _import_bake()
    except Exception as e:
        return [{"error": str(e)}]
    return [{"key": k, **v} for k, v in bake.MOD_INFO.items()]


def get_status() -> Dict[str, Any]:
    """查询当前对局状态（是否在进行中、结果、日志尾部等），供前端轮询。

    Returns:
        Dict[str, Any]: 当前状态字典的浅拷贝。
    """
    with _lock:
        return dict(_state)


# ---------- 快捷键安装（原 sc2Mod/hotkeys.py）----------

PFX_DOCS = (Path(settings.tool("proton_prefix"))
            / "pfx/drive_c/users/steamuser/Documents/StarCraft II")
HOTKEY_PROFILE = "sc2Mod"
HOTKEYS_INI = """\
[Settings]

[Hotkeys]
ArmySelect=Grave
TownCamera=Space
AlertRecall=Backspace
PTT=
"""


def sync_mods_to_pfx() -> None:
    """把 sc2Mod 的 mods/*.SC2Mod 同步进 Wine 前缀自己的 Documents/StarCraft II/Mods。

    踩过的坑：游戏装的地方（~/Games/StarCraft II/Mods/）跟游戏实际读 mod 的地方
    （Wine 前缀里这个 Documents 路径）是两个不同目录！DocumentHeader 里
    "file:Mods/X.SC2Mod" 这条依赖，游戏是按后者解析的——只把新版 mod 复制到前者，
    游戏读到的还是前缀 Documents 里那份没更新过的旧内容，改了 mod 数值跟没改一样，
    人挂着"倍数采集"的名字实际生效的还是原始那份。每次开局前都同步一遍，不然
    以后随便哪次改 mod 数值又会悄悄不生效。"""
    try:
        src_dir = SC2_DIR / "Mods"
        dst_dir = PFX_DOCS / "Mods"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in src_dir.glob("*.SC2Mod"):
            dst = dst_dir / f.name
            if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                shutil.copy2(f, dst)
    except Exception:
        pass


def install_hotkeys() -> Optional[str]:
    """`(Grave)=全选部队, 空格=回基地/循环, Backspace=跳到上个警报（空格/Backspace 互换）。"""
    try:
        hk_dir = PFX_DOCS / "Hotkeys"
        hk_dir.mkdir(parents=True, exist_ok=True)
        hk_file = hk_dir / f"{HOTKEY_PROFILE}.SC2Hotkeys"
        hk_file.write_text(HOTKEYS_INI, encoding="utf-8")

        var = PFX_DOCS / "Variables.txt"
        lines = var.read_text(encoding="utf-8", errors="replace").splitlines() if var.exists() else []
        lines = [ln for ln in lines if not ln.lower().startswith("hotkeyprofile=")]
        lines.append(f"hotkeyProfile={HOTKEY_PROFILE}")
        PFX_DOCS.mkdir(parents=True, exist_ok=True)
        var.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(hk_file)
    except Exception:
        return None


# ---------- 银河编辑器 ----------

def open_editor() -> tuple[bool, str]:
    """拉起银河编辑器（跟游戏共用同一个 Wine 前缀，能看到同一套 Mods/地图）。
    非阻塞——编辑器是个长时间开着交互用的 GUI，不像对局那样要等结果。"""
    exe = SC2_DIR / "StarCraft II Editor_x64.exe"
    if not exe.exists():
        return False, f"找不到编辑器：{exe}"
    proton_wine = HERE / "proton-wine"
    if not proton_wine.exists():
        return False, f"找不到 proton-wine 垫片：{proton_wine}"
    try:
        subprocess.Popen(
            [str(proton_wine), str(exe)],
            cwd=str(SC2_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "编辑器启动中，头一次打开可能要等十几秒"
    except Exception as e:
        return False, str(e)


# ---------- 拉起对局 ----------

def start_match(map_stem: str, race: str, opponents: List[Dict[str, str]], mods: List[str]) -> tuple[bool, str]:
    """在后台线程里起一局（子进程跑本项目 venv 里的 runner.py），立即返回不阻塞。

    Args:
        map_stem: 地图文件名（不含 .SC2Map 扩展名）。
        race: 玩家自己的种族。
        opponents: 电脑对手列表，如 [{"race": "T", "difficulty": "cheatinsane"}, ...]，
            至少 1 个，全是电脑——玩家只有自己一人。
        mods: 要启用的 mod key 列表。

    Returns:
        tuple[bool, str]: (是否成功发起, 提示/错误信息)；已有一局在跑或对手数超过
        地图上限时返回 False。
    """
    if not opponents:
        return False, "至少要有一个电脑对手"
    mf = SC2_MAPS_DIR / f"{map_stem}.SC2Map"
    if mf.exists():
        _, _, max_opponents = _guess_team(map_stem, mf)
        if len(opponents) > max_opponents:
            return False, f"这张图最多只能配 {max_opponents} 个电脑（没有队伍数据的图强制 1 个，多了会全部跟你敌对）"
    with _lock:
        if _state["running"]:
            return False, "已经有一局在跑了"
        _state.update(running=True, started_at=time.time(), last_map=map_stem,
                      last_mods=mods, last_opponents=opponents, last_result=None,
                      finished_at=None, log_tail="")

    def _worker():
        """在独立线程里同步 hotkey/mod、拉起 runner.py 子进程并等待结果，跑完更新 _state。"""
        install_hotkeys()
        sync_mods_to_pfx()
        cmd = [sys.executable, "-m", "omni.features.sc2.runner",
               "--map", map_stem, "--race", race,
               "--opponents", json.dumps(opponents, ensure_ascii=False),
               "--mods", ",".join(mods), "--json"]
        result_text = None
        err_text = None
        tail = ""
        try:
            proc = subprocess.run(cmd, cwd=paths.REPO, capture_output=True, text=True, timeout=3 * 3600)
            tail = "\n".join((proc.stdout or "").splitlines()[-30:])
            for line in (proc.stdout or "").splitlines():
                if line.startswith("SC2MOD_RESULT: "):
                    payload = json.loads(line[len("SC2MOD_RESULT: "):])
                    result_text = payload.get("result")
                    err_text = payload.get("error")
            if result_text is None and err_text is None:
                err_text = (proc.stderr or "未知错误")[-500:]
        except Exception as e:
            err_text = str(e)
        with _lock:
            _state.update(running=False, finished_at=time.time(), log_tail=tail,
                          last_result=result_text or (f"Error: {err_text}" if err_text else None))

    threading.Thread(target=_worker, daemon=True).start()
    return True, "已开局"
