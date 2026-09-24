"""
路由快照回归测试：起一个无界面的 Omni Deck 实例（另开端口，不跟正在运行的实例抢 8998），
把大厅前端会用到的每一条路由都请求一遍，记录「状态码 + 内容类型 + 响应结构」，
存成快照；重构之后再跑一遍跟快照比，任何路由的行为变了都会被列出来。

    # 采集快照（--legacy 表示用重构前的 main.py 起服务，只在建基线时用）
    python tests/route_snapshot.py record  --out tests/snapshots/baseline.json [--legacy]
    # 跟快照比对（默认起当前代码）
    python tests/route_snapshot.py compare --against tests/snapshots/baseline.json

只发只读请求（外加几个故意传错参数、不会产生副作用的写接口），联网类接口（漫画在线搜索、
榜单、小说在线检索）和 MEGA 不测——它们的结果取决于外部网络，没法做稳定快照。
"""
import argparse
import hashlib
import http.client
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("OMNI_TEST_PORT", "8997"))
PY = os.path.join(REPO, ".venv", "bin", "python")

# 重构前的 main.py 没有 --port / --headless，用这段引导代码把端口替换掉、只跑到 HTTP 服务起来为止。
_LEGACY_BOOT = r"""
import os, sys, time, types
path = os.path.join({repo!r}, "main.py")
src = open(path, encoding="utf-8").read().replace("PORT = 8998", "PORT = {port}")
mod = types.ModuleType("legacy_main"); mod.__file__ = path
sys.modules["legacy_main"] = mod
exec(compile(src, path, "exec"), mod.__dict__)
while True: time.sleep(3600)
"""


def start_server(legacy: bool):
    """起一个无界面实例并等它的 /api/_alive 应答；返回子进程对象。"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if legacy:
        cmd = [PY, "-c", _LEGACY_BOOT.format(repo=REPO, port=PORT)]
    else:
        cmd = [PY, "-m", "omni", "--headless", "--port", str(PORT)]
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"server exited early (rc={proc.returncode}): {' '.join(cmd[:4])}")
        try:
            status, _, _ = request("GET", "/api/_alive", timeout=1)
            if status == 200:
                return proc
        except OSError:
            pass
        time.sleep(0.5)
    stop_server(proc)
    raise SystemExit("server did not come up in 90s")


def stop_server(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass


def request(method, path, body=None, headers=None, timeout=60):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    hdrs = dict(headers or {})
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=hdrs)
    r = conn.getresponse()
    payload = r.read()
    ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
    conn.close()
    return r.status, ctype, payload


def shape(value, depth=0):
    """JSON 值的结构摘要：dict 记键名（递归），list 记长度 + 首元素结构，标量只记类型。"""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return {"__len__": len(value), "__item__": shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def summarize(status, ctype, payload):
    out = {"status": status, "type": ctype}
    if ctype == "application/json" or (payload[:1] in (b"{", b"[") and ctype in ("", "text/plain")):
        try:
            out["json"] = shape(json.loads(payload.decode("utf-8")))
            return out
        except Exception:
            pass
    out["len"] = len(payload)
    out["sha1"] = hashlib.sha1(payload).hexdigest()[:12]
    return out


def q(_route, **params):
    return _route + ("?" + urllib.parse.urlencode(params) if params else "")


def build_cases():
    """先查几个列表接口挑出样本 id，再拼出全部待测请求；挑样本的规则是固定排序后取第一个，
    保证新旧两版代码挑中同一批样本。"""
    cases = []

    def add(name, method, path, body=None, headers=None):
        cases.append({"name": name, "method": method, "path": path, "body": body, "headers": headers})

    def get_json(path):
        status, _, payload = request("GET", path)
        try:
            return json.loads(payload) if status == 200 else None
        except Exception:
            return None

    games = sorted(get_json("/api/games") or [], key=lambda g: g["id"])
    by_type = {}
    for g in games:
        key = g["type"] if g["type"] != "slg" else f"slg_{g.get('slg_engine')}"
        by_type.setdefault(key, g)
    rpg, retro, slg_web, flash = (by_type.get(k) for k in ("rpg", "retro", "slg_web", "flash"))

    # ---- 基础 / 系统
    for p in ["/api/_alive", "/api/auth/status", q("/api/logs", lines=5), "/api/lan/status",
              "/api/client/info", "/api/wan/status"]:
        add(p, "GET", p)
    # ---- 前端静态资源（含旧 URL 别名）
    for p in ["/", "/hub.html", "/hub.js", "/assets/hub.js", "/marked.min.js", "/mermaid.min.js",
              "/assets/katex.min.js", "/assets/katex.min.css", "/player_retro.html", "/player_flash.html",
              "/ruffle/ruffle.js", "/assets/ruffle/ruffle.js", "/plugins/manifest.json",
              "/emulatorjs/data/loader.js", "/emulatorjs/data/emulator.min.js"]:
        add(p, "GET", p)
    # ---- 游戏
    add("games", "GET", "/api/games")
    add("games?force", "GET", "/api/games?force=1")
    if rpg:
        gid = urllib.parse.quote(rpg["id"])
        add("rpg index", "GET", f"/game/{gid}/index.html")
        add("rpg index HEAD", "HEAD", f"/game/{gid}/index.html")
        add("rpg icon", "GET", f"/icon/{gid}")
        add("rpg readdir", "GET", q("/api/readdir", path="save", game_id=rpg["id"]))
        add("rpg patch", "GET", f"/api/patch/{gid}.js")
        add("rpg save missing", "GET", f"/save/{gid}/__nope__.rpgsave")
        add("rpg save missing HEAD", "HEAD", f"/save/{gid}/__nope__.rpgsave")
        add("rpg case-insensitive", "GET", f"/game/{gid}/INDEX.HTML")
    if retro:
        gid = urllib.parse.quote(retro["id"])
        add("retro rom", "GET", f"/retro_rom/{gid}")
        add("retro icon", "GET", f"/icon/{gid}")
    if slg_web:
        gid = urllib.parse.quote(slg_web["id"])
        add("slg entry", "GET", f"/game/{gid}/{slg_web.get('entry_html', 'index.html')}")
    if flash:
        add("flash swf", "GET", f"/flash_swf/{urllib.parse.quote(flash['id'])}")
    add("icon unknown", "GET", "/icon/__nope__")
    add("retro unknown", "GET", "/retro_rom/__nope__")
    # ---- 星际 2
    maps = get_json("/api/sc2/maps")
    for p in ["/api/sc2/maps", "/api/sc2/mods", "/api/sc2/status"]:
        add(p, "GET", p)
    if isinstance(maps, list) and maps:
        stems = sorted(m.get("stem") or m.get("name") or "" for m in maps if isinstance(m, dict))
        if stems and stems[0]:
            add("sc2 thumb", "GET", f"/api/sc2/thumb/{urllib.parse.quote(stems[0])}.png")
    # ---- 下载中心
    for p in ["/api/crawler/types", "/api/crawler/jobs", "/api/crawler/jobs/__nope__"]:
        add(p, "GET", p)
    # ---- 有声书
    add("audio catalog", "GET", "/audio/standard_catalog.json")
    add("audio lib", "GET", "/api/audio/library")
    add("audio lib nsfw", "GET", q("/api/audio/library", nsfw=1))
    audio = get_json("/api/audio/library") or {}
    items = sorted((audio.get("items") or []), key=lambda i: json.dumps(i, sort_keys=True, ensure_ascii=False))
    if items:
        name = items[0].get("path") or items[0].get("name") or items[0].get("rel_path")
        if name:
            add("audio stream range", "GET", q("/api/audio/stream", name=name), headers={"Range": "bytes=0-99"})
    # ---- 短视频
    for plat in ["kuaishou", "douyin", "tiktok"]:
        add(f"sv lib {plat}", "GET", q("/api/shortvideo/library", platform=plat, page_size=5))
        add(f"sv transcode {plat}", "GET", q("/api/shortvideo/transcode_status", platform=plat))
    add("sv thumb missing", "GET", q("/api/shortvideo/thumb", platform="kuaishou", path="__nope__.mp4"))
    # ---- 小说 / 文档
    add("novels lib", "GET", "/api/novels/library")
    add("novels lib nsfw", "GET", q("/api/novels/library", nsfw=1))
    add("novels queue", "GET", "/api/novels/queue")
    add("novels tasks", "GET", "/api/novels/tasks")
    add("docs root", "GET", "/api/docs/explorer")
    docs = get_json("/api/docs/explorer") or {}
    dirs = sorted(d.get("path") or d.get("name") for d in (docs.get("dirs") or docs.get("folders") or []) if isinstance(d, dict))
    if dirs:
        add("docs subdir", "GET", q("/api/docs/explorer", dir=dirs[0]))
    files = sorted((f.get("path") or f.get("name")) for f in (docs.get("files") or []) if isinstance(f, dict))
    if files:
        add("docs read", "GET", q("/api/novels/read", path=files[0]))
    novels = get_json("/api/novels/library") or []
    epubs = sorted(n.get("path") or n.get("name") for n in novels if isinstance(n, dict) and str(n.get("path") or n.get("name") or "").endswith(".epub"))
    if epubs:
        add("novel cover", "GET", q("/api/novels/cover", path=epubs[0]))
    # ---- 漫画
    add("manga lib", "GET", "/api/manga/library")
    add("manga lib novels", "GET", q("/api/manga/library", dir="novels"))
    add("manga queue", "GET", "/api/manga/queue")
    add("manga tasks", "GET", "/api/manga/tasks")
    manga = sorted(get_json("/api/manga/library") or [], key=lambda m: str(m.get("filename") or m.get("name")))
    if manga:
        m0 = manga[0]
        name = m0.get("filename") or m0.get("name")
        mdir = m0.get("dir") or m0.get("target_dir") or ""
        add("manga cover", "GET", q("/api/manga/cover", name=name, dir=mdir))
        add("manga pages", "GET", q("/api/manga/pages", name=name, dir=mdir))
        pages = get_json(q("/api/manga/pages", name=name, dir=mdir))
        if isinstance(pages, list) and pages:
            add("manga page", "GET", q("/api/manga/page", name=name, page=pages[0], dir=mdir))
    # ---- 写接口：只测「参数错误/无副作用」的分支
    add("POST unknown", "POST", "/api/__nope__", body={})
    add("POST unlock wrong", "POST", "/api/auth/unlock", body={"password": "__definitely_wrong__"})
    add("POST crawler bad type", "POST", "/api/crawler/start", body={"type": "__nope__"})
    add("POST launch unknown", "POST", "/api/games/launch", body={"id": "__nope__"})
    add("DELETE unknown", "DELETE", "/api/__nope__")
    return cases


def record(legacy: bool):
    proc = start_server(legacy)
    try:
        cases = build_cases()
        results = {}
        for c in cases:
            key = f"{c['method']} {c['name']}"
            try:
                status, ctype, payload = request(c["method"], c["path"], c["body"], c["headers"])
                results[key] = {"path": c["path"], **summarize(status, ctype, payload)}
            except Exception as e:
                results[key] = {"path": c["path"], "error": type(e).__name__}
        return results
    finally:
        stop_server(proc)


def diff(old, new, path=""):
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            if k not in new:
                out.append(f"{path}.{k}: removed")
            elif k not in old:
                out.append(f"{path}.{k}: added")
            else:
                out += diff(old[k], new[k], f"{path}.{k}")
    elif old != new:
        out.append(f"{path}: {old!r} -> {new!r}")
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--out", required=True)
    r.add_argument("--legacy", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("--against", required=True)
    c.add_argument("--legacy", action="store_true")
    args = ap.parse_args()

    results = record(args.legacy)
    if args.cmd == "record":
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"recorded {len(results)} routes -> {args.out}")
        return
    with open(args.against, encoding="utf-8") as f:
        baseline = json.load(f)
    problems = 0
    for key in sorted(set(baseline) | set(results)):
        if key not in results:
            print(f"MISSING  {key}")
            problems += 1
            continue
        if key not in baseline:
            print(f"NEW      {key}")
            continue
        d = diff({k: v for k, v in baseline[key].items() if k != "path"},
                 {k: v for k, v in results[key].items() if k != "path"})
        if d:
            problems += 1
            print(f"CHANGED  {key}  ({results[key]['path']})")
            for line in d[:12]:
                print("         ", line)
    print(f"\n{len(results)} routes checked, {problems} differ")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
