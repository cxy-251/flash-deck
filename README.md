# 🎮 Omni Deck (全能甲板) v2.4

> **专为 Steam Deck (SteamOS/Linux) 打造的多引擎单机游戏与媒体流式中枢控制中心**
> *(Steam 精选 · 独立大作 · RPG Maker · Ren'Py · Retro 复古掌机 · SLG · Flash 殿堂 · 漫画阅读器 · 小说书架 · 音声广播剧)*

[![Platform](https://img.shields.io/badge/Platform-Steam%20Deck%20%7C%20Linux-E95420?style=flat&logo=steam&logoColor=white)](https://store.steampowered.com/steamos)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6%20%2B%20WebEngine-41CD52?style=flat&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Environment](https://img.shields.io/badge/Environment-uv%20%7C%20venv-FFC107?style=flat&logo=python&logoColor=black)](https://github.com/astral-sh/uv)

Omni Deck 是一个基于 Python (PyQt6 WebEngine) 构建的现代化本地多引擎全能游戏控制中心，完美融合了六大底层架构体系：
1. 🚀 **独立大作与 Steam 精选**：
   - 🎮 **Steam 精选神作**：完全离线化运行《缺氧》、《饥荒全系列》、《异星工厂》、《戴森球计划》、《死亡细胞》、《潜水员戴夫》等，彻底告别强制更新毁坏 Mod 与基地存档；
   - 🟢 **Unity / 🔵 Godot / 🟡 Unreal / 🖥️ Wine PC**：全引擎支持，智能识别原生 Linux 与 Windows PE 二进制，自动挂载 Proton / Wine 运行时与多语言 UTF-8 注入；
2. 🗡️ **RPG Maker (MV/MZ)**：原生 WebGL 硬件加速 + NW.js/Node 全环境模拟；
3. 📖 **Ren'Py 视觉小说**：原生 64 位 Ren'Py SDK 调度直通；
4. 🕹️ **Retro 掌机与街机**：EmulatorJS WebAssembly 极速加载，覆盖 GBA / NDS / Arcade / NES / SFC / MD 等；
5. ♟️ **SLG 模拟策略与养成**：现代 2D/3D WebGL 引擎；
6. ⚡ **Flash 殿堂级神作**：解除时间炸弹的原生 Pepper Flash 硬件加速微端。

真正做到“全格式即拖即玩、物理硬盘存档直通、满帧流畅低功耗”。

---

## 🌟 核心特性

- **⚡ 100% Linux / Steam Deck 原生直出**
  彻底告别无谓的转译开销与依赖报错，直连 AMD RDNA2 GPU 实现满帧运行。

- **🎮 现代化大厅与专区子筛选**
  - **分类专区**：收藏、RPG Maker、独立游戏专区（内置 Steam 精选、Unity、Ren'Py、Godot、Unreal、Wine 子分类）、街机卡带、SLG、Flash。
  - **悬浮胶囊**：半透明悬浮控制胶囊，支持一键“全屏切换”、“静音切换”、“纯净全屏”与“返回大厅”。

- **💾 物理硬盘存档直通 (Direct FS Bridge)**
  内置轻量级多线程 HTTP 与 Direct FS 桥梁，自动接管各类引擎的存档写入。

- **🌐 全局环境配置解耦**
  路径全局变量化，原生支持 `OMNI_SD_ROOT`、`OMNI_GAMES_DIR`、`RENPY_SDK_PATH` 等环境变量覆盖，完美支持 MicroSD 卡与内置高寿命 NVMe 混合部署。

---

## 📁 目录结构

> `rpg_games/`、`renpy_games/`、`slg_games/`、`steam_games/` 四个专区的实际游戏内容已经搬到仓库外部
> （`~/Games/standalone_games/`、SD 卡等，具体位置由 `services/app_config.py` 统一管理，可编辑
> `services/local_settings.py` 里的 `LIBRARY_ROOTS` 调整），omni-deck 仓库本身不再打包任何游戏文件，
> 只保留引擎运行时与扫描逻辑；下方目录树里只列出仍然随代码一起分发的部分。

```text
omni-deck/
├── flash_games/                        # ⚡ Flash 殿堂专区（原生 Pepper Flash 硬件加速）
│   ├── plugins/                        # Flash 原生 PPAPI 解除时间炸弹插件 (Linux .so / Windows .dll)
│   └── 00 - Roco Kingdom (洛克王国)/    # 随仓库分发的示例条目，其余内容按需自行放入
├── retro_games/                        # 🕹️ 复古街机与掌机卡带专区（按游戏系列+版本规范命名，共 119 款）
│   ├── Knights of Valour (Arcade)/     # 三国战纪 1~3 / 风云再起 / 乱世枭雄 (6款)
│   ├── Oriental Legend (Arcade)/       # 西游释厄传 街机原版 (Arcade)
│   ├── Warriors of Fate (Arcade)/      # 三国志 2：赤壁之战 / 吞食天地 2 (Arcade)
│   ├── The King of Fighters '94 ~ 2003 & '97 Plus (Arcade)/ # 拳皇 94~2003 街机全家桶与风云再起大蛇版 (11款)
│   ├── The King of Fighters EX / EX2 / 95 / Heat of Battle / 98 / 99/ # 拳皇掌机与PS1版 (6款)
│   ├── Metal Slug 1 / 2 / X / 3 / 4 / 5 (Arcade)/ # 合金弹头 街机全家桶 (6款)
│   ├── Metal Slug Advance (GBA) / 7 (NDS) / X (PS1)/ # 合金弹头掌机与PS1版 (3款)
│   ├── Contra (NES / GB / SNES / GBA / NDS)/ # 魂斗罗系列全家桶 (5款)
│   ├── Final Fantasy (GB / GBA)/       # 最终幻想黄金期全家桶 (6款)
│   ├── Pokemon (GB / GBC / GBA / NDS / N64)/ # 宝可梦全世代与重制版 (20款，含心金/魂银/火红/叶绿/红蓝宝石/征服/守护者)
│   ├── The Legend of Zelda (NES / SNES / GB / GBC / GBA / NDS / N64)/ # 塞尔达传说系列全家桶 (13款，含大地的汽笛)
│   ├── Super Mario & Wario (NES / SNES / GB / GBC / GBA / NDS / N64)/ # 马里奥与瓦里奥全家桶 (36款，含瓦里奥制造/大陆/碧姬公主/耀西岛DS)
│   └── Street Fighter II Turbo (SNES)/ # 街头霸王 2 Turbo (SNES)
├── plugins/                            # 🚀 原生解除时间炸弹的 Pepper Flash Player 动态挂载库 (Linux .so & Windows .dll)
├── emulatorjs/                         # 全套预编译 WASM 核心底座 (GBA/NES/FBNeo/SFC/MD)
├── assets/
│   ├── hub.html                        # 五大引擎分类控制中心大厅 (一二级导航+实时搜索+系列包裹)
│   ├── core.js                         # 核心运行环境模拟层与 Polyfill (游戏生命线)
│   ├── player_retro.html               # 复古游戏 WASM 全屏播放器视口
│   └── player_flash.html               # Flash 独立视口播放器与居中自适应
├── services/                           # 可导入的核心业务逻辑模块 (音声/漫画/小说/短视频/MEGA/下载中心等)
├── config/                             # 运行时配置 (NSFW 密码、局域网/公网共享开关，已 gitignore)
├── crawlers/                           # 下载中心 UI 背后的贴链接下载与归档脚本
├── catalogs/                           # 在线小说检索静态目录清单
├── main.py                             # 五大引擎调度主程序、多线程 HTTP 路由与 Direct FS 桥梁
├── flash_runner.py                     # Flash 独立子进程运行时
├── sc2_runner.py                       # 星际争霸2 对局子进程运行时
├── run.sh                              # 一键自愈与依赖管理启动脚本 (入口点)
├── pyproject.toml                      # Python 依赖与项目配置文件
└── uv.lock                             # uv 依赖锁文件，保证环境一致性
```

---

## 🚀 快速启动指南

### 1. 环境准备
项目强烈推荐使用 `uv` 来管理 Python 虚拟环境，以获得极速的启动体验。如果您未安装 `uv`，启动脚本会自动退回使用标准的 `python3 -m venv`。
系统需安装 PyQt5 及其 WebEngine 组件：
```bash
# Arch Linux / SteamOS 依赖安装参考
sudo pacman -S python-pyqt5 python-pyqtwebengine
```

### 2. 运行应用
无需手动配置环境，直接执行 `run.sh` 即可，脚本会自动为您处理一切：
```bash
cd /home/deck/Games/omni-deck
chmod +x run.sh
./run.sh
```

---

## 🕹️ 如何添加游戏？

向 Omni Deck 中添加游戏极其简单，各专区自动识别：

1. **🗡️ RPG Maker 游戏**：放入 `rpg_games/`（支持 MV/MZ，解压后包含 `index.html` 或 `www/`）；
2. **📖 Ren'Py 视觉小说**：放入 `renpy_games/`（包含 `game/` 文件夹即可）；
3. **🕹️ Retro 复古掌机/街机**：放入 `retro_games/`（包含对应系统的 ROM 镜像，如 `.gba`, `.nds`, `.zip`）；
4. **♟️ SLG 模拟策略**：放入 `slg_games/`（支持 WebGL 模拟经营与养成互动）；
5. **⚡ Flash 殿堂神作**：放入 `flash_games/`（放入 `.swf` 单机文件或 `info.json` 网页配置）。

> **注意**：对于 RPG / SLG 类 Web 游戏，您可以直接清理掉其中的 `Game.exe`、`nw.dll` 等多余 Windows 二进制，框架完全不需要它们。
> 放入后重新打开应用或在大厅点击**“刷新”**按钮，游戏就会自动显示在对应专区列表中！

---

## ⚙️ 进阶配置与自定义

如果您想自定义游戏在大厅中的显示名称，可以编辑 `main.py` 顶部的 `DISPLAY_NAMES` 字典：

```python
DISPLAY_NAMES = {
    # '文件夹名称': '您想要的显示名称'
    '001 - Example Folder Name': '001 - 示例显示名称',
}
```

---

## 🛠️ 故障排除 (Troubleshooting)

| 症状 | 可能原因 | 解决方案 |
| :--- | :--- | :--- |
| **启动后全白屏** | 后台存在上一次未完全退出的进程（挂起），导致端口 `8998` 冲突。 | 运行 `pkill -9 -f "main.py"` 彻底清理后台进程后重新启动。 |
| **游戏黑屏且无声音** | 游戏底层 JS 文件出现致命的执行错误，或者部分音频编码在 Linux 原生 WebEngine 中不受支持。 | 展开右上角的悬浮胶囊，点击 **Debug**，查看开发者工具 Console 中的报错。 |
| **多语言插件报错 (DKTools等)** | 原游戏插件强制通过 Node 的 `fs` 同步遍历目录寻找 `.json` 文件。 | `core.js` 已为您接管并修补此类探测，若仍有问题，请检查游戏 `locales/` 目录下是否缺少最基础的默认语言包。 |
| **存档报错/丢失** | 浏览器的 `localStorage` 或 `IndexedDB` 空间不足或遭遇跨域限制。 | 本项目默认开启 **Direct FS Bridge**，已将存档持久化至各游戏目录下的 `save/`。若报错，请检查该目录是否有可写权限。 |

---

## 📝 贡献与许可

Omni Deck 是一个专为 Steam Deck 与 Linux 生态打造的开源多引擎游戏控制台解决方案，致力于让基于 Web、Python、WASM 及 Flash 技术的跨世代游戏在掌机环境（如 Steam Deck）中无拘无束地运行。欢迎提交 Issue 探讨问题或 Pull Request 贡献代码。
