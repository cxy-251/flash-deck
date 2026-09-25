# 🤖 Omni Deck — AI Agent & Developer Guidelines (`AGENTS.md`)

> **本文档为所有接手本项目的 AI 编码助手（Claude、Gemini、Cursor 等）与开发者提供架构全景、核心铁律与开发规范。**
> 架构细节见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 🚨 核心铁律 (Mandatory Rules)

### 1. 文件删除铁律
* 代表用户删除任何文件或目录时，**必须且只能使用 `gio trash <path>`** 移到回收站；
* **严禁使用 `rm`、`rm -rf`、`rm -f` 永久删除**；任何清理操作都必须能在回收站里找回。
* 应用自身的删除功能（漫画/小说/音频/短视频的「移至回收站」）同样走 `gio trash`。

### 2. Git 操作铁律
* **严禁主动执行 `git add` 与 `git push`**，只有用户明确下达指令时才执行；
* 绝对不得改写/覆盖远程仓库的既有提交历史。

### 3. 路径铁律（防止霰弹式修改）
* 程序与状态路径只从 `omni/core/paths.py` 取；资源（游戏/媒体）路径只从 `omni/core/library.py` 取；
  外部工具路径与本机配置只从 `omni/core/settings.py` 取。
* 业务代码里**禁止**写死 `/home/...`、`/run/media/...`、`expanduser(...)`、`SCRIPT_DIR` 拼路径——
  `tests/test_path_guard.py` 会拦截。新增配置项 = 在 `settings.DEFAULTS` 加一行；新增资源分类 = 在
  `library.GAME_CATEGORIES` / `library.MEDIA_LAYOUT` 加一行（库顶层目录名是 `GAMES_ROOT` / `MEDIA_ROOT` 常量）。
* 配置里的路径写成「基础目录占位」形式：`{home}` `{apps}` `{games}` `{steam}` `{sd}` 定义在 settings 的 `dirs`，
  由 `settings.resolve()` 展开、`settings.compact()` 压缩——挪动一个基础目录只改 `dirs` 一处（资源库页面可编辑）。
* 外部站点与本机地址只从 `omni/core/endpoints.py` 取：代码里写 `endpoints.url("站点键", 路径…)`，本机回环用
  `endpoints.LOOPBACK` / `endpoints.local_url()`；前端用 `Omni.url('站点键', …)` / `Omni.host()`（`endpoints.PUBLIC`
  里的键才下发）。换域名/镜像在 settings.json 的 `endpoints` 覆盖。

### 4. 资源与项目分离
* 仓库里**不放任何游戏/媒体资源**。资源在「资源库」里（见下），状态在 `var/`，两者都不进 git。

---

## 📌 项目定位

**Omni Deck** 是为 **Steam Deck (SteamOS) / Linux** 打造的本地游戏与媒体中心：PyQt6 + QtWebEngine 桌面壳 +
本地 HTTP 服务（8998）+ 网页大厅。覆盖 RPG Maker、独立游戏（Steam 精选 / Unity / Ren'Py / Godot / Unreal /
Wine / 3DS / Windows 软件）、复古街机掌机（EmulatorJS）、SLG、Flash（Ruffle / Pepper Flash）、星际争霸 2 离线对战，
以及技术文档、漫画、小说、有声书、短视频、MEGA 网盘、下载中心。局域网 / Cloudflare 广域网可远程访问。

---

## 🧭 三条架构原则

1. **UI 数据驱动**：`omni/manifest.json` 是 UI 的唯一数据源——分区、导航顺序、图标标题、访问级别
   （`public` / `nsfw` / `local`）、所需资源库键。后端据此给 API 套默认鉴权，前端据此渲染导航与权限表。
2. **代码与 UI 对称**：每个 UI 分区（manifest 的 `module`）在后端和前端各有一个同名目录：
   `omni/features/<module>/{api.py, service.py}` ↔ `web/features/<module>/{view.html, overlays.html, <module>.js, <module>.css}`。
3. **资源与项目分离**：游戏与媒体放在一个或多个「资源库」根目录（像 Steam 的游戏库文件夹），每个库都是同一套
   目录骨架，应用只按逻辑键（如 `games.rpg`、`media.manga`）通过 `omni.core.library` 取路径。

---

## 📂 仓库结构

```text
omni-deck/
├── main.py / run.sh           # 入口（Steam 快捷方式 → run.sh → main.py → omni.app.main）
├── omni/                      # Python 包
│   ├── manifest.json          # ★ UI 唯一数据源
│   ├── app.py                 # 启动编排：迁移 → 单实例 → HTTP → 后台任务 → Qt
│   ├── core/                  # 与具体 UI 无关的平台层
│   │   ├── paths.py           #   程序/状态路径唯一来源
│   │   ├── settings.py        #   var/config/settings.json（全部本机配置）
│   │   ├── library.py         #   资源库清单 + 目录骨架 LAYOUT
│   │   ├── manifest.py  access.py  events.py(SSE 总线)  log.py  process.py  vfs.py  media_index.py  migrate.py
│   │   └── http/              #   router.py(装饰器路由+鉴权) server.py static.py(白名单) hub.py(大厅页面组装)
│   ├── network/               # lan.py  wan.py(cloudflared 隧道 + DNS 助手)  state.py
│   ├── shell/                 # Qt 桌面壳：window.py  native_player.py  flash_runner.py(PyQt5 子进程)
│   └── features/<module>/     # ★ 与 web/features 对称：games sc2 manga novels docs audio shortvideo mega downloads library privacy system
├── web/                       # 前端
│   ├── index.html             #   页面外壳（{{slot}} / {{nav}} 由 hub.py 按 manifest 填充）
│   ├── app/                   #   core(Omni 注册表) access(权限表) shell(分区切换/分派) events(SSE) boot
│   ├── ui/                    #   共享组件：components gallery responsive reader/(文本阅读器+Markdown/RST)
│   ├── features/<module>/     #   ★ 与 omni/features 对称
│   ├── players/               #   retro.html  flash.html  rpg-runtime.js(NW.js/Node 兼容层，Qt 注入)
│   └── vendor/                #   katex marked mermaid
├── vendor/                    # 第三方运行时：emulatorjs/ ruffle/ pepflash/ cloudflared/（随仓库分发，断网可用）
├── tools/crawlers/            # 下载中心脚本：一类任务一个参数化脚本；个人参数在 var/config/crawler_secrets.json，保存的任务在 var/config/crawler_tasks/
├── tests/                     # route_snapshot.py  ui_smoke.py  test_path_guard.py
├── docs/                      # 项目文档
└── var/                       # 本机状态（gitignore）：config/ data/ cache/ logs/
```

**资源库**（仓库外，例如 `~/Games/omni_library`、`/run/media/deck/<SD卡>/omni_library`）：

```text
<库根>/omnilibrary.json                                  # 库标记（id/名称），换挂载点也能认回来
<库根>/standalone_games/{rpg,retro,slg,flash,steam,renpy,unity,godot,unreal,wine,3ds,app}_games/<游戏>/
<库根>/media_library/{manga, novels/{standard,nsfw}, audio/{standard,nsfw}, shortvideo/{快手,抖音,TikTok}, docs}/
```

每个游戏目录可放 `omni.json`（显示名、隐藏、图标、主程序、启动参数、环境变量、Proton 容器 appid），
取代以前写死在代码里的名称表与按 id 特判。

---

## 🛠️ 开发约定

### 新增一个 UI 分区
1. `omni/manifest.json` 的 `sections` 加一项（`id/group/title/icon/access`，需要资源时写 `library` 键），并加进 `groups[].tabs`；
2. 后端 `omni/features/<module>/api.py`：`api = Api("<module>")`，用 `@api.get/@api.post` 登记路由，
   默认鉴权取 manifest 的 `access`，个别路由用 `access=` / `deny=` 覆盖；业务放 `service.py`；
3. 前端 `web/features/<module>/`：`view.html`（根元素 `id="media-<分区id>-view"`）、可选 `overlays.html`、
   `<module>.js`（末尾 `Omni.register('<module>', { activate() {...}, onScrollEnd, prewarm, onUnlock, onLibraryChanged })`）、`<module>.css`；
4. `manifest.web.modules` 里登记 `features/<module>`。外壳、导航、权限表都不用改。

### 前端脚本约定
* 所有脚本是普通 `<script>`，共享全局作用域；HTML 里 `onclick="xxx()"` 直接调用全局函数。
* 顶层语句只做声明与本文件内的初始化；启动流程统一放 `web/app/boot.js`（最后加载）。
* 修改 CSS 拆分/加载顺序后，确认层叠结果不变（同优先级规则后加载者生效）。

### 常用命令
```bash
./run.sh                                        # 启动（Steam 游戏模式同款）
.venv/bin/python -m omni --headless --port 8997 --no-workers   # 只起 HTTP 服务调试
.venv/bin/python tests/test_path_guard.py       # 路径守卫
.venv/bin/python tests/route_snapshot.py compare --against tests/snapshots/v3.json   # 路由回归
.venv/bin/python tests/ui_smoke.py              # 前端冒烟（offscreen QtWebEngine，截图在 /tmp/omni-ui-smoke）
uv lock / uv sync                               # 依赖管理
```
测试实例一律用独立端口 + 临时状态目录（`OMNI_STATE_DIR`），不会碰正在运行的实例。

### Git 提交规范
语义化提交信息：`feat:` / `fix:` / `refactor:` / `chore:` / `docs:` / `test:`；`var/`、`.venv/` 等不进库。
