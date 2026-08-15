# 🎮 Flash Deck

> **专为 Steam Deck (SteamOS/Linux) 与 Windows 10/11 打造的原生多标签页 Flash 独立微端与殿堂级游戏中心**

[![Platform](https://img.shields.io/badge/Platform-Steam%20Deck%20%7C%20Linux%20%7C%20Windows-E95420?style=flat&logo=steam&logoColor=white)](https://store.steampowered.com/steamos)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt5%20%2B%20WebEngine-41CD52?style=flat&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Managed by uv](https://img.shields.io/badge/managed%20by-uv-DE5FE9?style=flat&logo=astral&logoColor=white)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 项目简介 (About Flash Deck)

随着 2021 年 Adobe 官方终止 Flash 支持，传统的网页端 Flash 体验逐渐凋零，充斥着广告劫持、登录拦截与卡顿的网页壳。

**Flash Deck** 是一个专注于**极致纯净、原生性能与跨平台多开**的 Flash 独立微端项目：
- 🐧 **Steam Deck (SteamOS/Linux) 原生直出**：内置已解除时间锁的原生 Linux `libpepflashplayer.so`，无需 Wine / Proton 兼容层，直接调用 AMD RDNA2 GPU 原生光栅化渲染，满帧 60FPS 极速秒开。
- 🪟 **Windows 10/11 开箱即用**：内置已解除时间锁的 64 位 Windows `pepflashplayer64.dll`，克隆即可运行，彻底告别 Flash 锁区与弹窗。
- 📑 **原生多标签页系统 (Multi-Tab)**：支持在同一窗口内多开游戏（左边洛克王国挂机、右边造梦西游除妖、后台畅玩王国保卫战）。
- 🕹️ **内置 14 款殿堂级封神单机 SWF**：精选全球公认最高评分的 Flash 游戏，0 广告、0 网页壳、纯正单机。
- 💾 **全自动本地存盘 (SharedObject)**：所有单机游戏的科技树、金币、关卡进度 100% 自动保存在本地磁盘，无需登录，关机不丢档。

---

## 🕹️ 精选游戏阵容 (Game Lineup)

### 1. 经典页游专区
* 👑 **《洛克王国》**（腾讯官方魔法宠物社区 · 默认开机启动 · 支持窗口内全屏沉浸居中）
* 🐒 **《造梦西游全系列》**（4399 官方页游 · 包含 1 代七魔王、2 代十殿阎罗、3 代大闹天庭、4 代洪荒大劫全集）

### 2. 14 款 Flash 殿堂级单机神作（100% 原装内置 · 离线秒开）
* 🏰 **《王国保卫战 (Kingdom Rush)》**：铁皮工作室（Ironhide）初代封神原版，全球公认塔防天花板。
* 🧟 **《最后的战役 2 (The Last Stand 2)》**：丧尸末日防御求生巅峰，白天搜集军火，黑夜筑垒抵抗尸潮。
* 🥊 **《狂扁小朋友 (Dad 'n Me)》**：The Behemoth 动作打击感之王，爽快浮空连段与投掷煤气罐。
* 🕵️ **《神偷鲍勃 (Bob The Robber)》**：经典潜行神作，躲避监控、破译密码、打晕警卫潜入豪宅。
* 🛡️ **《战争进化史 (Age of War)》**：经典战歌响起，从原始人扔石头一路打到未来激光机甲。
* 🐧 **《企鹅学飞 (Learn to Fly)》**：风靡全球的滑翔物理力学神作，升级火箭助推器飞跃极地。
* 🎬 **《火柴人亨利：逃狱记》**：PuffballsUnited 恶搞分支互动选择，无数爆笑神结局。
* 🌀 **《传送门 Flash版 (Portal)》**：被 Valve 官方收录的传世时空双色传送门解谜神作。
* 🎲 **《滚动方块 (Bloxorz)》**：Miniclip 镇站之宝！33 关立体几何空间翻转益智。
* 🐂 **《奔牛节大逃亡 (Extreme Pamplona)》**：经典西班牙街头跑酷，飞跃屋顶逃离狂暴公牛。
* 🏹 **《疯狂弓箭手 (Mad Arrow)》**：经典城墙冷兵器塔防，部署神箭手与长矛卫兵。
* 🐟 **《大鱼吃小鱼 (Fish Tales Deluxe)》**：经典海底吞噬成长与进化。
* 🍦 **《坏冰淇淋 3 (Bad Ice Cream)》**：Nitrome 经典像素神作，吐冰建墙、碎冰抢水果。
* 🤖 **《互动巴迪 (Interactive Buddy)》**：经典物理减压交互小人，解锁重力枪、激光与炸药。
* 📂 **《运行本地 SWF》**：支持任意外部 Flash `.swf` 单机文件离线载入。

---

## 🛠️ 快速安装与使用指南 (Getting Started)

### 1. Steam Deck / Linux 桌面模式 (SteamOS)

打开终端，执行以下命令：

```bash
# 1. 克隆仓库
git clone https://github.com/cxy-251/flash-deck.git
cd flash-deck

# 2. 赋予执行权限并一键启动
chmod +x run.sh
./run.sh
```

> 💡 **提示**：`run.sh` 脚本内置**环境自愈功能**，会自动准备好 Python 虚拟环境与依赖，无需手动安装任何库。

#### 🎮 将 Flash Deck 添加至 Steam 掌机模式启动：
1. 在 Steam Deck 桌面模式中打开 **Steam 客户端**；
2. 点击左下角 **「添加游戏 (Add a Game)」** ➔ **「添加非 Steam 游戏 (Add a Non-Steam Game...)」**；
3. 点击 **浏览 (Browse)**，选择 `flash-deck/run.sh`；
4. 添加完成后，切换回 **Gaming Mode (掌机模式)**，即可像游玩 Steam 游戏一样用手柄/触控板畅玩！

---

### 2. Windows 10 / 11 (PC)

```powershell
# 1. 克隆仓库
git clone https://github.com/cxy-251/flash-deck.git
cd flash-deck

# 2. 启动客户端 (推荐使用 uv 或系统 python)
uv run python main.py
# 或直接: python main.py
```

---

## 💡 快捷功能与操作技巧

- **📑 多标签页多开**：
  - 点击标签栏右上角 **`➕`** 按钮或工具栏 **`➕ 新建标签`** 即可打开新标签页；
  - 点击标签页右上角 **`✕`** 即可关闭当前标签页；
  - 支持直接鼠标拖拽标签页进行前后排序。
- **🎮 窗口内全屏**：
  - 在《洛克王国》页面中，点击工具栏 **`🎮 窗口内全屏`** 可一键消除网页无关横幅，游戏画面正中呈现并附带沉浸式黑屏遮罩。再次点击即可完美还原。
- **🔊 全局声音控制**：
  - 点击工具栏 **`🔊 声音: 开启 / 静音`** 可实时开启或静音所有标签页音频。
- **📂 运行外部 SWF 文件**：
  - 在游戏大厅点击 **「📂 运行本地 SWF」**，选择电脑本地的任意 `.swf` 文件，即可在新标签页中满帧流畅运行。

---

## 📂 项目结构说明

```text
flash-deck/
├── pyproject.toml            # uv 标准项目配置 (flash-deck v1.0.0)
├── uv.lock                   # uv 依赖锁定文件
├── README.md                 # 项目详细说明文档
├── LICENSE                   # MIT 开源许可证
├── .gitignore                # 运行时目录过滤 (.venv, __pycache__, data, cache)
├── run.sh                    # Linux / Steam Deck 一键全自动启动脚本
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
    ├── libpepflashplayer.so  # Linux 原生 64 位 Flash 运行库 (已解除时间锁)
    └── pepflashplayer64.dll  # Windows 64 位 Flash 运行库 (已解除时间锁)
```

---

## 🧹 数据持久化与重置

- **游戏存档目录**：用户的 Flash 本地存档（`.sol` 文件）保存在本地 `data/storage/` 中，关机不丢失；
- **底层加速缓存**：浏览器底层素材缓存保存在 `cache/engine_cache/` 中（最大限制 1GB，自动清理）；
- **恢复出厂设置**：若需清空所有存档与缓存，只需在项目根目录下执行：
  ```bash
  rm -rf data/ cache/ .venv/
  ```

---

## 📄 开源许可证

本项目遵循 [MIT License](LICENSE) 开源许可证。
