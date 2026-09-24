# Gemini Project Instructions for Omni Deck

完整规范见 [AGENTS.md](../AGENTS.md)，架构见 [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)。

要点：
1. 删除文件只能用 `gio trash`，禁止 `rm`；未经用户明确指示不得 `git add` / `git push`。
2. 路径只从 `omni/core/paths.py`（程序/状态）、`omni/core/library.py`（资源库）、`omni/core/settings.py`（本机配置）取。
3. UI 由 `omni/manifest.json` 驱动；每个分区在 `omni/features/<module>/` 与 `web/features/<module>/` 各有同名目录。
4. 技术栈：Python 3.10+、PyQt6 + QtWebEngine（Flash 网页游戏走 `.venv_flash` 的 PyQt5 子进程）、uv。
