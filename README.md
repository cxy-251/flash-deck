# 🗡️ RPG Deck

> **专为 Steam Deck (SteamOS/Linux) 打造的原生多标签页 RPG Maker HTML5 游戏微端与运行中心**

[![Platform](https://img.shields.io/badge/Platform-Steam%20Deck%20%7C%20Linux%20%7C%20Windows-E95420?style=flat&logo=steam&logoColor=white)](https://store.steampowered.com/steamos)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt5%20%2B%20WebEngine-41CD52?style=flat&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Managed by uv](https://img.shields.io/badge/managed%20by-uv-DE5FE9?style=flat&logo=astral&logoColor=white)](https://github.com/astral-sh/uv)

---

## 🌟 核心特性

- **⚡ 100% Linux 原生直出**：告别 Wine / Proton 转译开销，直接通过 Linux 原生 WebGL 硬件加速引擎直连 AMD RDNA2 GPU，满帧 60FPS 流畅运行。
- **📑 原生多标签页极速多开 (Multi-Tab)**：在单一现代化暗黑窗口内，支持同时打开多个不同的 RPG 游戏，随时点击切换，标签页独立声音与生命周期。
- **💾 物理硬盘存档直通 (Direct FS Bridge)**：独家实现 Node.js 物理文件系统虚拟化，物理 `.rpgsave` 存档无缝双向读写，直接读取本地历史存档，游戏内保存实时写回硬盘。
- **📦 项目内自包含游戏库 (`games/`)**：所有游戏资源均完整存放在项目自身 `games/` 目录下，100% 独立于外部 SD 卡，拔掉存储卡或迁移项目直接可用。
- **📂 支持外部任意 RPG 导入**：支持自由选择电脑或 SD 卡中的任意外部 RPG Maker 游戏目录一键载入。

---

## 📁 目录结构

```text
rpg-deck/
├── games/                      # 自包含游戏库 (完全独立于外部介质)
│   ├── countryside/            # 《我的乡村日常生活》
│   ├── karryn-prison/          # 《卡琳监狱长》
│   ├── gym-center/             # 《禁欲健身中心》
│   ├── succubus-boss/          # 《我与魅魔上司的同居生活》
│   └── secret-rule/            # 《只有我的神秘规则 (女教练)》
├── assets/
│   └── hub.html                # 现代化暗黑风格游戏大厅前端
├── main.py                     # 原生多标签页客户端主程序与 Direct FS 桥梁
├── run.sh                      # 一键自愈启动脚本
├── pyproject.toml              # 依赖与项目配置文件
└── README.md
```

---

## 🚀 启动与使用

```bash
cd /home/deck/Documents/rpg-deck
chmod +x run.sh
./run.sh
```
