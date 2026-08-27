# 🤖 Omni Deck — AI Agent & Developer Guidelines (`AGENTS.md`)

> **本文档为所有接手本项目的 AI 编码助手（Antigravity, Gemini, Claude, Cursor 等）与开发者提供全景架构、核心铁律与开发规范。**

---

## 🚨 核心铁律 (Mandatory Rules)

### 1. 文件删除铁律 (Deletion Policy)
* 在代表用户删除任何文件或目录时，**必须且只能使用 `gio trash <path>`** 将其移动到回收站；
* **严禁使用 `rm`、`rm -rf` 或 `rm -f` 进行永久删除**；
* 任何清理操作必须确保可在回收站中找回。

### 2. Git 提交与推送铁律 (Git Operations Policy)
* **严禁主动执行 `git add` 和 `git push`**；
* 只有在用户明确下达 `add` 或 `push` 指令时方可执行提交与推送操作；
* 绝对不得覆盖远程仓库的既有提交历史。

---

## 📌 项目定位与核心愿景 (Project Mission)

**Omni Deck** 是一个专为 **Steam Deck (SteamOS/Linux x86_64)** 与 **PC Linux** 打造的五大引擎多世代全能独立游戏控制中心。

### 🌟 五大底层引擎矩阵：
1. 🗡️ **RPG Maker 专区 (`rpg_games/`)**：原生 WebGL 硬件加速，内置 `core.js` 全套 NW.js/Node 模拟与 Direct FS 物理存档直通；
2. 📖 **Ren'Py 专区 (`renpy_games/`)**：全局 Ren'Py SDK 调度直通，原生支持 64位 OpenGL 硬件加速与手柄映射；
3. 🕹️ **Retro 复古掌机街机专区 (`retro_games/`)**：EmulatorJS 纯原生 WebAssembly 极速底座（GBA/NDS/Arcade/NES/SFC/MD）；
4. ♟️ **SLG 模拟策略与养成专区 (`slg_games/`)**：现代 2D/3D WebGL 互动模拟引擎；
5. ⚡ **Flash 殿堂级神作专区 (`flash_games/`)**：内置解除时间炸弹的原生 Pepper Flash 硬件加速微端，直通 14 款官方原装单机神作及《洛克王国》/《造梦西游》。

---

## 📂 项目全景文件结构 (Repository Map)

```text
omni-deck/
├── AGENTS.md                 # [本文件] AI 助手与核心架构规范
├── pyproject.toml            # uv 标准依赖配置 (PyQt5 + PyQtWebEngine)
├── uv.lock                   # uv 依赖锁定清单
├── README.md                 # 用户面向完整说明文档
├── LICENSE                   # MIT 开源许可证
├── .gitignore                # 运行时目录过滤与骨架规则
├── run.sh                    # Linux / SteamOS 全自动自愈启动脚本
├── main.py                   # Omni Deck 核心调度主程序与 Direct FS 路由
├── core.js                   # 核心 Polyfill 与环境仿真层 (NW.js / Node.js 模拟)
├── assets/                   # 前端大厅 UI 与独立播放器视口
│   ├── hub.html              # Omni Deck 五大专区分类控制中心
│   ├── player_retro.html     # 复古游戏 WASM 全屏视口
│   └── player_flash.html     # Flash 独立视口
├── emulatorjs/               # EmulatorJS WASM 核心底座 (含 data/ 核心文件)
├── rpg_games/                # 🗡️ RPG Maker 游戏专区
├── renpy_games/              # 📖 Ren'Py 视觉小说专区
├── retro_games/              # 🕹️ 复古街机掌机 ROM 专区
├── slg_games/                # ♟️ SLG 模拟策略专区
└── flash_games/              # ⚡ Flash 殿堂神作专区 (全量入库跟踪)
    └── plugins/              # Linux/Windows 原生 Pepper Flash PPAPI 插件
```

---

## ⚙️ 核心架构规范与开发约束

### 1. Flash 插件内聚性
* Flash 运行库统一放置在 `flash_games/plugins/`；
* 必须随 Git 仓库直接打包入库，保证新设备断网亦能开箱即玩；
* `scan_games()` 扫描 `flash_games/` 时自动跳过 `plugins` 文件夹。

### 2. 窗口内纯净全屏
* 悬浮胶囊中的「🎮 纯净全屏」功能专门服务于《洛克王国》（`17roco.qq.com`）等带网页边框的游戏，单机 SWF、大厅与其他专区游戏自动隐藏。

### 3. Direct FS 存档持久化
* 所有基于 Web 的游戏通过本地多线程 HTTP 路由与文件系统直通将存档写入物理磁盘（各游戏根目录下的 `save/`），绝不依赖不可靠的临时浏览器 IndexedDB。

### 4. 零垃圾文件与持久化收敛
* 运行时产生的全部数据严格收敛在 4 个目录中，且全部受到 `.gitignore` 保护：
  * `data/storage/`：用户本地存档与 Cookie；
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
