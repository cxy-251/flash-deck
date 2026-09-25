# 下载中心脚本（`tools/crawlers/`）

一类任务一个脚本，全部通过参数复用；应用里「媒体专区 → ⬇️ 下载中心」就是这些脚本的表单界面。
产物一律写进**默认资源库**对应目录（见 `omni/core/library.py`），任何在线资源库里已有同名文件就跳过。

| 脚本 | 任务 | 例 |
| :--- | :--- | :--- |
| `media_fetch.py` | 视频站音频 → 有声书（YouTube / B 站 / 播放列表 / 多 P；逐条 m4a 或合成带章节 m4b） | `media_fetch.py "<播放列表网址>" --album 某书` |
| `tts_drama.py` | 文本 / 剧本 → 多角色广播剧（Edge TTS） | `tts_drama.py --text 第一章.txt --roles 角色.json --album 自制广播剧` |
| `blog_novels.py` | 博客类小说站 → EPUB：`stories` 短篇合卷 / `book` 单本长篇 / `books` 目录页逐本 | `blog_novels.py stories --site https://… --label 分类 --nsfw` |
| `apk_books.py` | 读书 App 的 APK 内置书库 → EPUB（`folders` / `files` 两种布局） | `apk_books.py --apk x.apk --root assets/book/名著 --folder 名著` |
| `epub_build.py` | 书稿 JSON / 本地 md·txt 目录 / GitHub 仓库目录 → EPUB | `epub_build.py --dir ~/notes --title 笔记 --folder 技术笔记` |
| `archive_unpack.py` | 伪装成 .mp4/.mkv 的加密压缩包游戏 → 游戏文件夹 | `archive_unpack.py --source x.mp4 --category renpy --name "043 - 某游戏"` |
| `run_task.py` | 运行保存好的任务 | `run_task.py --list` / `run_task.py <任务名>` |

每个脚本 `-h` 查看全部参数。运行方式：`.venv/bin/python tools/crawlers/<脚本> …`。

## 个人参数（不进 git）

站点 Cookie、代理、YouTube 登录方式放在 **`var/config/crawler_secrets.json`**，格式见
[`secrets.example.json`](secrets.example.json)：

* `sites.<域名>.cookies` —— 抓网页时按域名自动带上（例如 Cloudflare 的 `cf_clearance`；过期后脚本会提示更新）；
* `http.user_agent` / `http.proxy` —— 网页抓取用；
* `ytdlp.cookies_file` / `ytdlp.cookies_from_browser` / `ytdlp.proxy` —— yt-dlp 用；都没配时默认用 `var/config/cookies.txt`。

命令行参数（`--cookies`、`--proxy`）优先于这里。游戏解压密码在 `var/config/settings.json` 的 `archive_extract_password`。

## 保存的任务（不进 git）

常跑的一组参数存成 **`var/config/crawler_tasks/<名字>.task.json`**，下载中心「运行保存的任务」里一键执行：

```json
{"label": "说明文字", "script": "media_fetch.py",
 "args": ["https://youtu.be/xxx|第一部", "--album", "某书", "--min-mb", "10"]}
```

参数（命令行、任务文件、secrets 里都一样，见 `_common.expand`）支持占位符：`{url:站点键}` 替换成
`omni/core/endpoints.py` 里的站点根地址（如 `{url:youtube}/watch?v=…`、`{url:xbookcn_blog}`），`{tasks}` 替换成任务目录
（剧本、角色配置、书名映射等数据文件放在 `{tasks}/data/`），`{inbox}` 替换成收件箱目录，`{home}` `{games}` `{sd}` 等
替换成 settings 的基础目录。secrets 的 `sites` 键可以写站点键（如 `xbookcn_blog`），换域名时不用改。
另外所有脚本都支持 `@参数文件`（每行一个参数）：`media_fetch.py @我的参数.args`。

## 约定

* 公共逻辑在 `_common.py`（私密参数、网页抓取、yt-dlp、资源库路径、EPUB 生成复用小说画廊的实现）；
* 删除文件只用 `gio trash`（`_common.trash`）；
* 新增一类任务：写一个参数化脚本 → 在 `omni/features/downloads/service.py` 的 `JOB_TYPES` 登记表单字段。
