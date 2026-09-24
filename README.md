# 🎮 Omni Deck v3

> **专为 Steam Deck (SteamOS/Linux) 打造的本地游戏与媒体中心**
> *Steam 精选 · 独立游戏 · RPG Maker · Ren'Py · 复古街机掌机 · SLG · Flash · 星际争霸 2 离线对战 · 技术文档 · 漫画 · 小说 · 有声书 · 短视频 · MEGA*

PyQt6 + QtWebEngine 桌面壳 + 本地 HTTP 服务（8998）+ 网页大厅；同一个大厅在局域网手机/平板和 Cloudflare 广域网上也能打开。

---

## 🌟 特性

- **多资源库**：像 Steam 的游戏库文件夹一样，内置存储、SD 卡、移动硬盘都能登记成资源库；每个库同一套目录骨架，
  添加时自动建好，游戏与媒体从所有在线的库合并展示，新下载写入默认库。在应用里「媒体专区 → 🗄️ 存储与游戏库」管理。
- **多引擎**：RPG Maker（WebGL + NW.js 兼容层）、Unity / Godot / Unreal / Wine（原生 Linux 或 Proton）、Ren'Py、
  Lime3DS、EmulatorJS（GBA/NDS/PS1/街机…）、Ruffle 与 Pepper Flash。
- **存档直通磁盘**：网页游戏的存档写进游戏自己目录下的 `save/`，不依赖浏览器存储。
- **媒体中心**：技术文档（Markdown/RST/Mermaid/LaTeX）、CBZ 漫画、EPUB/TXT 小说、有声书（支持章节与后台播放）、短视频画廊、MEGA 网盘、下载中心。
- **隐私与远程访问**：NSFW 分区密码锁；局域网 / 广域网开关；本机专属功能（启动游戏、网盘、下载）对远程设备自动隐藏。

---

## 🚀 启动

```bash
cd ~/Games/omni-deck
./run.sh          # 首次会用 uv 建好 .venv；Steam 里添加非 Steam 游戏指向 run.sh 即可
```

首次启动会自动把旧版本的状态迁移到 `var/`，并根据旧配置登记资源库。

---

## 🗄️ 资源库结构

```text
<资源库根>/
├── omnilibrary.json                 # 库标记（自动生成）
├── standalone_games/
│   ├── rpg_games/  retro_games/  slg_games/  flash_games/
│   └── steam_games/  renpy_games/  unity_games/  godot_games/  unreal_games/  wine_games/  3ds_games/  app_games/
└── media_library/
    ├── docs/  manga/  novels/{standard,nsfw}/  audio/{standard,nsfw}/  shortvideo/{快手,抖音,TikTok}/
```

**添加游戏**：把游戏文件夹放进对应的 `*_games/`，回到大厅刷新即可（RPG Maker 需含 `index.html` 或 `www/`；
复古游戏放 ROM；Flash 放 `.swf` 或写 `info.json` 的网页地址）。

**自定义游戏**：在游戏文件夹里放 `omni.json`（字段都可选）：

```json
{
  "name": "012 - 缺氧 (Oxygen Not Included)",
  "hidden": false,
  "icon": "cover.png",
  "exe": "OxygenNotIncluded",
  "args": ["-nosound"],
  "env": {"KEY": "VALUE"},
  "proton_appid": "3498387003"
}
```

---

## ⚙️ 配置

全部本机配置在 `var/config/settings.json`，大部分可在「存储与游戏库」页面修改：资源库清单、收件箱目录、
外部工具路径（Ren'Py SDK、Lime3DS、MEGA-CMD、星际争霸 2、Proton 容器、cloudflared 配置）、库外程序、
广域网域名、NSFW 初始密码。

---

## 🛠️ 故障排除

| 症状 | 原因 | 处理 |
| :--- | :--- | :--- |
| 启动后立即退出 | 已有实例在运行（或端口 8998 被卡住的实例占用） | 结束旧实例：`pkill -f "omni-deck/main.py"` |
| 某个库的游戏不见了 | 库所在的盘没挂载（库显示「离线」） | 插上 SD 卡 / 挂载后刷新 |
| 游戏黑屏 | 游戏脚本出错 | 右上角「📋 日志」查看，独立游戏的输出在 `var/logs/games/` |
| 存档失败 | 游戏目录不可写 | 检查游戏目录下 `save/` 的权限 |

开发者文档见 [`AGENTS.md`](AGENTS.md) 与 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
