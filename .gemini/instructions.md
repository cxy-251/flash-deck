# Gemini Project Instructions for Flash Deck

See [AGENTS.md](../AGENTS.md) for full project architecture, strict guidelines, and workflow.

## Quick Summary for AI Assistants:
1. **Tech Stack**: Python 3.10+, PyQt5, PyQtWebEngine, uv, Pepper Flash (`libpepflashplayer.so` & `pepflashplayer64.dll`).
2. **Key Rules**:
   - Both Flash binaries in `plugins/` must stay in git tracking (no on-demand download scripts).
   - "🎮 窗口内全屏" must ONLY be visible for Roco Kingdom (`17roco.qq.com`); it must stay hidden for all other games, local SWFs, and the hub.
   - Do NOT add background keyboard shortcuts (`Ctrl+T`, `Ctrl+W`, etc.) to prevent conflicts with Flash game controls.
   - Maintain multi-tab isolation while sharing `QWebEngineProfile("flash_deck_profile")`.
