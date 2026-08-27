#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

export QTWEBENGINE_CHROMIUM_FLAGS="--enable-features=WebAssemblyThreads,SharedArrayBuffer --enable-webgl --ignore-gpu-blocklist --enable-gpu-rasterization"

echo "[*] 正在启动 Omni Deck (Native Linux on SteamOS)..."

# 1. 优先使用 uv
if command -v uv >/dev/null 2>&1; then
    exec uv run python main.py "$@"
fi

# 2. 如果存在 .venv
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
fi

# 3. 自动下载轻量 uv
if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
        exec uv run python main.py "$@"
    fi
fi

# 4. 兜底
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/pip" install PyQt6 PyQt6-WebEngine
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
