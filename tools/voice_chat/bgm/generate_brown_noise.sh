#!/usr/bin/env bash
# 用 ffmpeg 生成棕噪音作为睡前/放松 BGM
# 棕噪比白噪/粉噪低频更强，最助眠
#
# 用法: ./generate_brown_noise.sh [duration_seconds] [output_file]
# 例：  ./generate_brown_noise.sh 600 brown_noise.wav

DURATION="${1:-600}"      # 默认 10 分钟
OUTPUT="${2:-brown_noise.wav}"
VOLUME="${VOLUME:-0.12}"  # 音量 0.12 偏低，适合做背景

if ! command -v ffmpeg >/dev/null; then
    echo "错误: 需要 ffmpeg"
    echo "macOS: brew install ffmpeg"
    exit 1
fi

cd "$(dirname "$0")"

ffmpeg -f lavfi \
    -i "anoisesrc=c=brown:d=${DURATION}:r=44100:a=${VOLUME}" \
    -ac 2 -c:a pcm_s16le \
    "${OUTPUT}" -y

echo ""
echo "✓ 生成完成: $(pwd)/${OUTPUT}"
ls -lh "${OUTPUT}"
