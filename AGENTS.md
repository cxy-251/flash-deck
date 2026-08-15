# 🤖 Flash Deck — AI Agent & Developer Guidelines (`AGENTS.md`)

> **本文档为所有接手本项目的 AI 编码助手（Gemini, Antigravity, Claude Code, Cursor, Copilot 等）与开发者提供全景架构、核心规则与开发规范。**

---

## 📌 项目定位与核心愿景 (Project Mission)

**Flash Deck** 是一个专为 **Steam Deck (SteamOS/Linux x86_64)** 与 **Windows 10/11 (PC x64)** 打造的原生多标签页 Flash 独立微端与殿堂级单机/页游游戏中心。

### 关键目标：
1. **100% 原生硬件加速与满帧渲染**：内置已解除时间锁限制的 Linux 原生 `libpepflashplayer.so` 与 Windows 64位 `pepflashplayer64.dll`，无需 Wine / Proton 兼容层，直接调用底层 GPU 渲染。
2. **多标签页极速多开 (Multi-Tab)**：支持在单个应用窗口内同时多开多个独立游戏标签页。
3. **彻底告别垃圾广告壳**：内置 14 款官方原装 Flash 封神单机游戏（0 广告、0 网页壳），支持本地自动持久化存档（Flash SharedObject）。
4. **极简依赖与零配置冷启动**：由 `uv` 统一管理依赖（仅 `PyQt5` + `PyQtWebEngine`），新用户克隆后运行 `./run.sh` 即可自动准备环境并开箱即玩。

---

## 📂 项目全景文件结构 (Repository Map)

```text
flash-deck/
├── AGENTS.md                 # [本文件] AI 助手与核心架构规范
├── pyproject.toml            # uv 标准依赖配置 (仅 PyQt5 + PyQtWebEngine)
├── uv.lock                   # uv 依赖锁定清单
├── README.md                 # 用户面向说明文档与 Steam Deck 配置指南
├── LICENSE                   # MIT 开源许可证
├── .gitignore                # 严格过滤运行时目录 (.venv, __pycache__, data, cache)
├── run.sh                    # Linux / SteamOS 全自动自愈启动脚本
├── main.py                   # Flash Deck 核心主程序 (双端通用)
├── assets/
│   ├── hub.html              # Flash Deck 殿堂级神作大厅前端
│   └── games/                # 内置 14 款殿堂级 Flash 单机游戏 SWF
│       ├── kingdom_rush.swf           # 王国保卫战
│       ├── the_last_stand_2.swf       # 最后的战役 2
│       ├── dad_n_me.swf               # 狂扁小朋友
│       ├── bob_the_robber.swf         # 神偷鲍勃
│       ├── age_of_war.swf             # 战争进化史
│       ├── learn_to_fly.swf           # 企鹅学飞
│       ├── henry_escaping_prison.swf  # 火柴人亨利：逃狱记
│       ├── portal_flash.swf           # 传送门 Flash 版
│       ├── bloxorz.swf                # 滚动方块
│       ├── extreme_pamplona.swf       # 奔牛节大逃亡
│       ├── mad_arrow.swf              # 疯狂弓箭手
│       ├── fish_tales.swf             # 大鱼吃小鱼
│       ├── bad_ice_cream_3.swf        # 坏冰淇淋 3
│       └── interactive_buddy.swf      # 互动巴迪
└── plugins/
    ├── libpepflashplayer.so  # Linux 原生 64 位 Pepper Flash (已解除时间锁，直接随 Git 打包)
    └── pepflashplayer64.dll  # Windows 64 位 Pepper Flash (已解除时间锁，直接随 Git 打包)
```

---

## ⚙️ 核心架构与设计规范 (Core Architecture)

### 1. 双端运行库动态挂载 (`get_flash_plugin_path`)
* 程序启动时通过 `platform.system().lower()` 动态判断：
  * Linux / SteamOS ➔ 挂载 `plugins/libpepflashplayer.so`；
  * Windows ➔ 挂载 `plugins/pepflashplayer64.dll`；
* **严禁规则**：**绝对不要**把插件改成网络按需下载，必须始终随 Git 仓库直接打包入库，保证新机器彻底离线可用。

### 2. 多标签页系统 (`QTabWidget` + `CustomWebPage`)
* 采用 `QTabWidget(documentMode=True, tabsClosable=True, movable=True)` 作为主窗口核心容器；
* 每个标签页拥有独立的 `QWebEngineView` 与 `CustomWebPage`；
* 所有标签页共享同一个 `QWebEngineProfile("flash_deck_profile")`（持久化存储路径设为 `data/storage/`），共享 Cookie、硬件加速与 Flash 存档；
* `createWindow` 拦截所有网页弹窗与 `target="_blank"` 链接，自动调度 `main_window.add_new_tab(target_url)` 在独立新标签页中打开。

### 3. 窗口内全屏逻辑 (Window Fullscreen Rule)
* **严格限制**：「🎮 窗口内全屏」功能是专门为《洛克王国》（`17roco.qq.com`）消除网页广告横幅并沉浸居中设计的；
* **展示条件**：在 `update_fullscreen_action_visibility` 中，**只有当前标签页 URL 包含 `17roco.qq.com` 时才展示该按钮**；
* **隐藏规则**：在《造梦西游》、游戏大厅（`hub.html`）以及所有单机 SWF（`file://`）游戏下，**必须强制隐藏 (`setVisible(False)`)**；
* **实现方式**：采用全局 `<style id="roco-pure-mode-style">` 注入与移除机制，彻底避免腾讯登录脚本重构 DOM 时导致样式丢失或无法退出的问题。

### 4. 键盘按键与快捷键准则
* **严禁拦截快捷键**：**绝对不要**在主窗口中绑定 `Ctrl+T`、`Ctrl+W`、`Ctrl+Tab` 等全局键盘快捷键，避免与 Flash 游戏的键盘走位/技能键（如 WASD, Tab 等）产生冲突；
* 标签的新建、关闭、切换一律通过 UI 按钮原生触发。

### 5. 零垃圾文件与持久化收敛
* 运行时产生的全部数据严格收敛在 4 个目录中，且全部受到 `.gitignore` 保护：
  * `data/storage/`：用户 Flash 本地存档（`.sol`）与 Cookie；
  * `cache/engine_cache/`：Chromium 原生 C++ 磁盘缓存（上限 1GB）；
  * `.venv/`：由 `uv` 管理的隔离运行环境；
  * `__pycache__/`：Python 字节码编译缓存。

---

## 🛠️ 常用开发与测试指令 (Developer Commands)

### 1. 运行与验证程序
```bash
# 方式 A：标准 uv 极速启动
uv run python main.py

# 方式 B：执行 Linux 自动化自愈脚本
./run.sh
```

### 2. 依赖管理
```bash
# 查看或锁定依赖
uv lock

# 更新或同步虚拟环境
uv sync
```

### 3. Git 提交规范
* 遵循语义化提交信息：`feat: ...`, `fix: ...`, `chore: ...`, `docs: ...`；
* 避免将 `data/`, `cache/`, `.venv/` 等运行时缓存提交进仓库。
