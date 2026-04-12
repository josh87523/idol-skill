#!/usr/bin/env python3
"""
user_mic — 持续录用户麦克风, faster-whisper 识别, 写入 chat_bridge 的 [user] 行.

防回声: 用 fcntl 非阻塞试 flock speak 锁文件. worker 正在 TTS 播放时会持有独占锁,
user_mic 拿不到锁就暂停录音, 避免把 worker 自己的声音录回来形成自循环.

用法:
  python3 user_mic.py
  python3 user_mic.py --threshold 150        # 调静音阈值
  python3 user_mic.py --max-rounds 50        # 最多录几句
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE = str(SCRIPT_DIR / "chat_bridge.py")
PYTHON = sys.executable  # 用当前解释器调 chat_bridge, 跨机通用

# 和 chat_bridge 保持一致: 共享文件默认 /tmp/idol_groupchat.txt, 可用 GROUPCHAT_FILE 覆盖
CHAT_FILE = Path(os.getenv("GROUPCHAT_FILE", "/tmp/idol_groupchat.txt"))
SPEAK_LOCK = Path(str(CHAT_FILE) + ".speaking.lock")

RATE = 16000
CHUNK = 1024
SILENCE_SEC = 1.5  # 静音多久判定一句话结束 (默认从 0.8 调大到 1.5, 允许说话间停顿)
MIN_SPEECH = 10
MAX_RECORD_SEC = 60  # 单句最长录音 (默认从 30 调到 60)


def is_speaking():
    """非阻塞试 flock, 拿不到说明 worker 正在 speak"""
    import fcntl
    if not SPEAK_LOCK.exists():
        return False
    try:
        fd = open(SPEAK_LOCK, "r")
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except (IOError, OSError):
        return True
    finally:
        fd.close()


def wait_lock_gone():
    while is_speaking():
        time.sleep(0.15)


def record_one(pa, threshold):
    """录一句话, 返回 frames bytes 或 None.
    如果录音中途锁出现 (worker 突然开始播放) -> 丢弃返回 None.
    """
    import pyaudio

    wait_lock_gone()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)
    frames = []
    silent_chunks = 0
    speech_chunks = 0
    has_speech = False
    max_silent = int(SILENCE_SEC * RATE / CHUNK)
    aborted = False

    print("[user_mic] 等你说话...", flush=True)
    try:
        while True:
            if is_speaking():
                # worker 抢话, 丢弃当前 frames
                aborted = True
                break
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            count = len(data) // 2
            shorts = struct.unpack(f"{count}h", data)
            rms = (sum(s * s for s in shorts) / count) ** 0.5

            if rms > threshold:
                silent_chunks = 0
                speech_chunks += 1
                if not has_speech:
                    has_speech = True
                    print("[user_mic] 检测到语音", flush=True)
            else:
                if has_speech and speech_chunks >= MIN_SPEECH:
                    silent_chunks += 1
                    if silent_chunks >= max_silent:
                        break

            if len(frames) > RATE / CHUNK * MAX_RECORD_SEC:
                break
    finally:
        stream.stop_stream()
        stream.close()

    if aborted or not has_speech:
        return None
    return b"".join(frames)


def transcribe(stt, frames):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(frames)
    try:
        segments, info = stt.transcribe(tmp.name, language="zh")
        text = "".join(seg.text for seg in segments).strip()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return text


def is_garbage(text):
    if not text:
        return True
    text = text.strip()
    if len(text) < 2:
        return True
    # 全标点/空白
    if all(not c.isalnum() and c not in "你我他她它的是了不在有人嘛吧呢啊哦呀诶嗯哎" for c in text):
        return True
    # whisper 幻觉重复模式: 同一个短串连续重复 5+ 次 (例如"试试试试试")
    for substr_len in (1, 2, 3, 4):
        if len(text) >= substr_len * 5:
            for i in range(0, len(text) - substr_len * 5 + 1):
                substr = text[i:i + substr_len]
                if substr.strip() and text[i:i + substr_len * 5] == substr * 5:
                    return True
    # 异常长且字符种类极少 (whisper 在长静音段乱拼)
    if len(text) > 60 and len(set(text)) < len(text) * 0.25:
        return True
    return False


def speak_user(text):
    r = subprocess.run(
        [PYTHON, BRIDGE, "speak", "user", text],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[user_mic] speak user 失败: {r.stderr[:200]}", file=sys.stderr)


def main():
    global SILENCE_SEC, MAX_RECORD_SEC
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=120, help="静音阈值 RMS")
    ap.add_argument("--silence-sec", type=float, default=SILENCE_SEC, help="静音多久判停 (秒)")
    ap.add_argument("--max-record-sec", type=int, default=MAX_RECORD_SEC, help="单句最长录音 (秒)")
    ap.add_argument("--max-rounds", type=int, default=200)
    args = ap.parse_args()
    SILENCE_SEC = args.silence_sec
    MAX_RECORD_SEC = args.max_record_sec
    print(f"[user_mic] 参数: threshold={args.threshold} silence_sec={SILENCE_SEC} max_record={MAX_RECORD_SEC}", flush=True)

    print(f"[user_mic] 启动, threshold={args.threshold}", flush=True)
    print("[user_mic] 加载 whisper base...", flush=True)
    from faster_whisper import WhisperModel
    stt = WhisperModel("base", device="cpu", compute_type="int8")
    print("[user_mic] whisper 就绪", flush=True)

    import pyaudio
    pa = pyaudio.PyAudio()

    try:
        for i in range(args.max_rounds):
            frames = record_one(pa, args.threshold)
            if frames is None:
                # 被锁打断或没识别到语音, 短暂休息再继续
                time.sleep(0.3)
                continue
            text = transcribe(stt, frames)
            print(f"[user_mic] 识别: {text}", flush=True)
            if is_garbage(text):
                print("[user_mic] 噪音/无效, 丢弃", flush=True)
                continue
            speak_user(text)
            # 给 worker 看到 [user] 留点时间
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[user_mic] 用户中断")
    finally:
        pa.terminate()


if __name__ == "__main__":
    main()
