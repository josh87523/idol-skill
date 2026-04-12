#!/usr/bin/env bash
# idol-skill voice chat launcher
# 用法:
#   ./launcher.sh <idol-slug>
#   ./launcher.sh <idol-slug> --state night
#   ./launcher.sh <idol-slug> --fresh
#   ./launcher.sh --list

# 确保 claude CLI 在 PATH 里（homebrew 安装位置）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$(dirname "$0")"

# macOS 系统 python 默认有 pyaudio / faster-whisper 的用户应该用 /usr/bin/python3
# 其他系统或 venv 请替换 PYTHON 变量
PYTHON="${PYTHON:-/usr/bin/python3}"

exec "$PYTHON" -u voice_chat.py "$@"
