# Gemini Project Instructions for Omni Deck

See [AGENTS.md](../AGENTS.md) for full 5-Engine architecture, strict guidelines, and workflow.

## Quick Summary for AI Assistants:
1. **Tech Stack**: Python 3.10+, PyQt5, PyQtWebEngine, uv, EmulatorJS (WASM), Ren'Py SDK 8.x/7.x, NW.js polyfill (`core.js`), Pepper Flash PPAPI (`flash_games/plugins/`).
2. **Key Rules**:
   - **Mandatory Deletion Policy**: MUST ALWAYS use `gio trash <path>` to delete/trash files. NEVER use `rm` or `rm -rf`.
   - **Git Operations**: NEVER execute `git add` or `git push` unless explicitly instructed by the user.
   - **5-Engine Directory Structure**:
     - `rpg_games/`: RPG Maker MV/MZ (WebGL, NW.js polyfilled, Direct FS Bridge)
     - `renpy_games/`: Ren'Py Visual Novels (Native SDK bridge)
     - `retro_games/`: Retro Arcade & Handheld ROMs (EmulatorJS WASM)
     - `slg_games/`: SLG Simulation & Strategy (WebGL)
     - `flash_games/`: Flash SWFs + Web Flash (PPAPI Flash, self-contained plugins)
   - **Flash Support**: Flash binaries reside in `flash_games/plugins/` and are fully tracked in Git.
   - **Window Fullscreen**: "🎮 纯净全屏" is dynamically displayed for Roco Kingdom (`17roco.qq.com`) and hidden for others.
