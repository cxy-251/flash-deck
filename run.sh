#!/usr/bin/env bash
set -e

# 定位当前脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 补充常见用户二进制目录到 PATH
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

echo "[*] 正在启动 Flash Deck 独立微端 (Native Flash on SteamOS/Linux)..."

# 1. 优先使用已安装的 uv (极速无缝管理环境)
if command -v uv >/dev/null 2>&1; then
    exec uv run python main.py "$@"
fi

# 2. 如果存在现成的虚拟环境，直接启动
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
fi

# 3. 若无 uv，尝试自动在线安装轻量级 uv
echo "[*] 正在为您准备运行环境..."
if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
        exec uv run python main.py "$@"
    fi
fi

# 4. 终极兜底方案：使用系统 Python3 创建虚拟环境并安装依赖
echo "[*] 正在使用系统 Python3 创建独立运行环境..."
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/pip" install PyQt5 PyQtWebEngine
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
