"""
大厅页面组装：web/index.html 外壳 + omni/manifest.json → 完整页面。

  {{nav:portal-cards}} / {{nav:game-tabs}} / {{nav:standalone-subtabs}} / {{nav:media-tabs}}
      由 manifest 的分区数据渲染（顺序见 groups[].portal / groups[].tabs）；
  {{slot:header|subbar|games|games-list|media|overlays}}
      依次拼入 manifest.web.modules 里每个功能目录的 header.html / subbar.html / view.html /
      overlays.html（媒体类分区的 view.html 按分区各渲染一次，模板里用 {{s.<字段>}} 取分区数据）；
  {{styles}} / {{scripts}} / {{vendor}}
      按 manifest.web 的 core → modules → tail 顺序引入 css/js（加版本号，防 QtWebEngine 缓存旧文件）。

组装结果按源文件 mtime 缓存，改了任何片段刷新页面即可生效。
"""
import html
import json
import os
import re

from omni.core import endpoints, manifest, paths

W = paths.WEB
_cache = {"sig": None, "html": None}


def _read(rel):
    p = os.path.join(W, rel)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _module_files(mod):
    name = mod.split("/")[-1]
    return {kind: f"{mod}/{fname}" for kind, fname in (
        ("css", f"{name}.css"), ("js", f"{name}.js"), ("header", "header.html"),
        ("subbar", "subbar.html"), ("view", "view.html"), ("overlays", "overlays.html"))}


def _all_sources(m):
    files = ["index.html"] + list(m["web"]["core"]) + list(m["web"]["tail"])
    for mod in m["web"]["modules"]:
        files += list(_module_files(mod).values())
    return files


def _signature(m):
    sig = [os.path.getmtime(manifest.PATH), json.dumps(endpoints.public())]
    for rel in _all_sources(m):
        p = os.path.join(W, rel)
        sig.append(os.path.getmtime(p) if os.path.exists(p) else 0)
    return tuple(sig)


def _ver(rel):
    try:
        return int(os.path.getmtime(os.path.join(W, rel)))
    except OSError:
        return 0


def _asset_tag(rel):
    url = f"/web/{rel}?v={_ver(rel)}"
    return f'<link rel="stylesheet" href="{url}">' if rel.endswith(".css") else f'<script src="{url}"></script>'


def _e(s):
    return html.escape(str(s), quote=True)


# --------------------------------------------------------------------------- 导航渲染

def _portal_cards(m, sections):
    out = []
    for sid in next(g for g in m["groups"] if g["id"] == "games")["portal"]:
        s = sections[sid]
        badge = s.get("badge", "0 Games")
        out.append(f'''<div class="cat-card {sid}-card" onclick="openCategory('{sid}')">
    <div class="cat-header">
        <div class="cat-title">{s["icon"]} {_e(s.get("card_title", s["title"]))}</div>
        <span class="cat-count {sid}-count" id="{sid}-count-badge">{_e(badge)}</span>
    </div>
    <div class="cat-desc">
        {_e(s.get("desc", ""))}
    </div>
    <div class="cat-action">{_e(s.get("action", "进入专区"))} ➔</div>
</div>''')
    return "\n".join(out)


def _game_tabs(m, sections):
    return "\n".join(
        f'''<button class="tab-btn" data-tab="{sid}" onclick="switchTab('{sid}', this)">{sections[sid]["icon"]} {_e(sections[sid]["title"])}</button>'''
        for sid in next(g for g in m["groups"] if g["id"] == "games")["tabs"])


def _standalone_subtabs(m, sections):
    return "\n".join(
        f'''<button class="sub-tab-btn" data-sub="{c["id"]}" onclick="switchStandaloneSubTab('{c["id"]}', this)">{c["icon"]} {_e(c["title"])}</button>'''
        for c in sections["standalone"].get("subcategories", []))


def _media_tabs(m, sections):
    out = []
    for sid in next(g for g in m["groups"] if g["id"] == "media")["tabs"]:
        s = sections[sid]
        active = " active" if s.get("default") else ""
        out.append(f'''<button class="tab-btn{active}" id="media-tab-{sid}" onclick="switchMediaTab('{sid}', this)">{s["icon"]} {_e(s["title"])}</button>''')
    return "\n".join(out)


def _nsfw_init_selectors(m):
    sels = []
    for s in m["sections"]:
        if s.get("access") != "nsfw":
            continue
        if s["group"] == "games":
            sels += [f".{s['id']}-card", f'.tab-btn[data-tab="{s["id"]}"]']
        else:
            sels.append(f"#media-tab-{s['id']}")
    return ", ".join(sels)


# --------------------------------------------------------------------------- 片段拼装

def _render_section_template(text, section):
    return re.sub(r"\{\{s\.(\w+)\}\}", lambda mo: _e(section.get(mo.group(1), "")), text)


def _slots(m):
    slots = {k: [] for k in ("header", "subbar", "games", "games-list", "media", "overlays")}
    by_module = {}
    for s in m["sections"]:
        by_module.setdefault(s.get("module", s["id"]), []).append(s)
    for mod in m["web"]["modules"]:
        files = _module_files(mod)
        name = mod.split("/")[-1]
        for kind in ("header", "subbar", "overlays"):
            text = _read(files[kind])
            if text:
                slots[kind].append(text)
        view = _read(files["view"])
        if not view:
            continue
        secs = by_module.get(name, [])
        if name == "games":
            slots["games"].append(view)
        elif secs and secs[0]["group"] == "games":
            slots["games-list"].append(view)          # 游戏分区的专属面板（如星际2），放进列表页
        else:
            ordered = [s for s in secs]
            tab_order = next(g for g in m["groups"] if g["id"] == "media")["tabs"]
            ordered.sort(key=lambda s: tab_order.index(s["id"]) if s["id"] in tab_order else 99)
            for s in ordered or [{}]:
                slots["media"].append(_render_section_template(view, s))
    return {k: "\n".join(v) for k, v in slots.items()}


def render() -> str:
    m = manifest.load()
    sig = _signature(m)
    if _cache["sig"] == sig:
        return _cache["html"]
    sections = {s["id"]: s for s in m["sections"]}
    web = m["web"]
    styles = [r for r in web["core"] if r.endswith(".css")]
    scripts = [r for r in web["core"] if r.endswith(".js")]
    for mod in web["modules"]:
        f = _module_files(mod)
        if os.path.exists(os.path.join(W, f["css"])):
            styles.append(f["css"])
        if os.path.exists(os.path.join(W, f["js"])):
            scripts.append(f["js"])
    styles += [r for r in web["tail"] if r.endswith(".css")]
    scripts += [r for r in web["tail"] if r.endswith(".js")]

    page = _read("index.html")
    slots = _slots(m)
    # games-list 在 games 视图内部，先展开 games 再替换
    page = page.replace("{{slot:games}}", slots["games"])
    public_manifest = {k: v for k, v in m.items() if k != "web"}
    replacements = {
        "{{vendor}}": "\n    ".join([_asset_tag(r) for r in web.get("vendor_styles", [])]
                                   + [_asset_tag(r) for r in web.get("vendor_scripts", [])]),
        "{{manifest_json}}": json.dumps(public_manifest, ensure_ascii=False).replace("</", "<\\/"),
        "{{endpoints_json}}": json.dumps(endpoints.public(), ensure_ascii=False),
        "{{styles}}": "\n    ".join(_asset_tag(r) for r in styles),
        "{{scripts}}": "\n    ".join(_asset_tag(r) for r in scripts),
        "{{nsfw_init_selectors}}": _nsfw_init_selectors(m),
        "{{nav:portal-cards}}": _portal_cards(m, sections),
        "{{nav:game-tabs}}": _game_tabs(m, sections),
        "{{nav:standalone-subtabs}}": _standalone_subtabs(m, sections),
        "{{nav:media-tabs}}": _media_tabs(m, sections),
    }
    # 先拼片段（片段里可能还带 {{nav:*}}），再渲染导航与资源引用
    for key in ("header", "subbar", "games-list", "media", "overlays"):
        page = page.replace("{{slot:%s}}" % key, slots[key])
    for k, v in replacements.items():
        page = page.replace(k, v)
    leftover = re.findall(r"\{\{[a-z_:.\-]+\}\}", page)
    if leftover:
        raise ValueError(f"hub template has unresolved tokens: {sorted(set(leftover))}")
    _cache.update(sig=sig, html=page)
    return page
