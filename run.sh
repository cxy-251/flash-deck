#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

# ---------------------------------------------------------------------------
# 关键：从 Steam 启动时，Steam 往每个子进程注入一堆东西 —— 最要命的是
#   LD_PRELOAD=.../gameoverlayrenderer.so       (Steam 覆盖层)
#   ENABLE_VK_LAYER_VALVE_steam_overlay_1 / fossilize   (Steam 的 Vulkan 层)
# 它们钩进 QtWebEngine 的 Chromium/GPU 子进程，初始化就卡在那儿反复重试，
# 实测让 setup_webengine() 卡 ~100 秒（boot.log 抓到的）。全部清掉，用干净环境起。
# ---------------------------------------------------------------------------
unset LD_PRELOAD
unset LD_LIBRARY_PATH
unset SteamAppId SteamGameId SteamOverlayGameId SteamClientLaunch
unset ENABLE_VK_LAYER_VALVE_steam_overlay_1 ENABLE_VK_LAYER_VALVE_steam_fossilize_1
export DISABLE_VK_LAYER_VALVE_steam_overlay_1=1
export DISABLE_VK_LAYER_VALVE_steam_fossilize_1=1

export QTWEBENGINE_CHROMIUM_FLAGS="--enable-features=WebAssemblyThreads,SharedArrayBuffer --enable-webgl --ignore-gpu-blocklist --enable-gpu-rasterization"

# 启动计时落盘（boot.log 里 Python 侧 +0.00s 之前那段 = venv/uv 冷启动）
mkdir -p "$SCRIPT_DIR/cache"
printf '%s  [run.sh] LD_PRELOAD/Steam overlay 已清，exec python\n' "$(date --iso-8601=seconds)" \
    >> "$SCRIPT_DIR/cache/boot.log" 2>/dev/null || true

echo "[*] 正在启动 Omni Deck (Native Linux on SteamOS)..."

# 直接用 venv 里的 python（比 uv run 每次重解析依赖快好几秒）
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
fi

# 兜底 1：uv
if command -v uv >/dev/null 2>&1; then
    exec uv run python main.py "$@"
fi

# 兜底 2：装 uv 再跑
if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
        exec uv run python main.py "$@"
    fi
fi

# 兜底 3：自建 venv
python3 -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/pip" install PyQt6 PyQt6-WebEngine
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
