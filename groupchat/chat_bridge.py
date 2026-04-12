#!/usr/bin/env python3
"""
chat_bridge — 多参与者语音群聊共享文件桥. 每个参与者是一个 slug (idol 目录名),
特殊保留 slug 'user' 表示用户插话 (不 TTS 只入桥).

用法:
  python3 chat_bridge.py speak  <slug> <text>           # TTS 播放 + append 共享文件
  python3 chat_bridge.py listen <slug> [timeout] [jump] # 阻塞等待非自己的下一条新消息
  python3 chat_bridge.py reset                          # 清空共享文件 (开新一轮)
  python3 chat_bridge.py tail                           # 看一眼最近 20 行 (调试)

环境变量:
  GROUPCHAT_FILE  共享文件路径 (默认 /tmp/idol_groupchat.txt)
  VOLC_APPID      火山引擎 appid
  VOLC_TOKEN      火山引擎 token
  VOLC_<SLUG>_SPEAKER_ID  某个 idol 的克隆声音 id (slug 大写)
  VOLC_SPEAKER_ID 回落默认 speaker
"""

import os
import sys
import time
import uuid
import wave
import io
import base64
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env")

CHAT_FILE = Path(os.getenv("GROUPCHAT_FILE", "/tmp/idol_groupchat.txt"))
SPEAK_LOCK = Path(str(CHAT_FILE) + ".speaking.lock")  # worker 播放 TTS 期间持有 flock, user_mic 检测到就暂停录音


def pos_file_for(role):
    return Path(f"{CHAT_FILE}.pos.{role}")


VOLC_APPID = os.getenv("VOLC_APPID")
VOLC_TOKEN = os.getenv("VOLC_TOKEN")

# user 是保留 slug, 表示用户插话, 不走 TTS 只入桥
USER_SLUG = "user"


def get_speaker(slug):
    """从 VOLC_<SLUG>_SPEAKER_ID 环境变量读 speaker_id, 回落到 VOLC_SPEAKER_ID"""
    return os.getenv(f"VOLC_{slug.upper()}_SPEAKER_ID") or os.getenv("VOLC_SPEAKER_ID")


def ensure_file():
    if not CHAT_FILE.exists():
        CHAT_FILE.touch()


def append_line(role, text):
    ensure_file()
    line = f"[{role}] {text.strip()}\n"
    with CHAT_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


def read_lines():
    ensure_file()
    with CHAT_FILE.open("r", encoding="utf-8") as f:
        return f.readlines()


def tts_play(text, speaker_id):
    """火山引擎 TTS → 写临时 wav → afplay 播放 (避免 pyaudio 电流声)"""
    import subprocess
    import tempfile

    if not all([VOLC_APPID, VOLC_TOKEN, speaker_id]):
        print("[bridge] 缺少 VOLC_APPID / VOLC_TOKEN / speaker_id", file=sys.stderr)
        return

    resp = requests.post(
        "https://openspeech.bytedance.com/api/v1/tts",
        json={
            "app": {"appid": VOLC_APPID, "token": VOLC_TOKEN, "cluster": "volcano_icl"},
            "user": {"uid": "chat_bridge"},
            "audio": {"voice_type": speaker_id, "encoding": "wav", "speed_ratio": 1.0},
            "request": {"reqid": str(uuid.uuid4()), "text": text, "operation": "query"},
        },
        headers={"Authorization": f"Bearer;{VOLC_TOKEN}", "Content-Type": "application/json"},
        timeout=15,
    )
    result = resp.json()
    if "data" not in result:
        print(f"[bridge] TTS 失败: {result.get('message', 'unknown')}", file=sys.stderr)
        return
    audio = base64.b64decode(result["data"])

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        tmp_path = tmp.name

    # fcntl.flock: 多个 worker 串行播放, 后到的阻塞等前一个播完, 避免叠声
    import fcntl
    SPEAK_LOCK.touch()
    lock_fd = open(SPEAK_LOCK, "r+")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)  # 阻塞等待独占
        subprocess.run(["afplay", tmp_path], check=False)
        # 释放锁前清场 0.4s, 让扬声器余音消散, 避免被 user_mic 录到
        time.sleep(0.4)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    print(f"[bridge] 已播放 ({len(audio)//1024}KB)")


def cmd_speak(role, text):
    # 任意 slug 都合法 (user 是保留 slug, 不 TTS 只入桥)
    # 先写文件让对面立刻能看到
    append_line(role, text)
    if role == USER_SLUG:
        print(f"[bridge] {role} 入桥 (无 TTS)")
        return
    speaker = get_speaker(role)
    if not speaker:
        print(f"[bridge] 没配 VOLC_{role.upper()}_SPEAKER_ID, 只入桥不 TTS", file=sys.stderr)
        return
    tts_play(text, speaker)


def cmd_listen(role, timeout=600, interval=0.4, jump=False):
    """阻塞等待 *任何非自己* 的下一条未读新消息 (其他参与者 + user 插话).

    用 <CHAT_FILE>.pos.<role> 持久化"我已经读到第几条非自己消息".

    jump=False (默认): 严格按顺序读, 一次返回 .pos 之后第一条未读
    jump=True (跳跃模式): 一旦发现有未读, **直接跳到最末**, 只返回最新那一条,
                         pos 也跳到末尾, 中间所有积压全部丢弃. 适合 worker 永远只回应最新.
    """
    own_prefix = f"[{role}]"
    pf = pos_file_for(role)
    pos = int(pf.read_text().strip() or "0") if pf.exists() else 0

    deadline = time.time() + timeout
    mode = "jump" if jump else "seq"
    print(f"[bridge] {role} 等待非自己消息 (read_pos={pos}, timeout={timeout}s, mode={mode})...", file=sys.stderr)

    while time.time() < deadline:
        non_self = []
        for ln in read_lines():
            ln_stripped = ln.rstrip("\n")
            if not ln_stripped.startswith("[") or "]" not in ln_stripped:
                continue
            if ln_stripped.startswith(own_prefix):
                continue
            non_self.append(ln_stripped)
        if len(non_self) > pos:
            if jump:
                # 跳跃: 取最新, pos 跳到末尾
                new = non_self[-1]
                new_pos = len(non_self)
                skipped = new_pos - pos - 1
                if skipped > 0:
                    print(f"[bridge] jump: 丢弃中间 {skipped} 条积压", file=sys.stderr)
            else:
                new = non_self[pos]
                new_pos = pos + 1
            end = new.index("]")
            who = new[1:end]
            payload = new[end + 1:].strip()
            pf.write_text(str(new_pos))
            print(f"FROM: {who}")
            print(f"TEXT: {payload}")
            print(f"OTHER_SAID: {payload}")
            return payload
        time.sleep(interval)

    print("FROM: none")
    print("TEXT: （超时未收到消息）")
    print("OTHER_SAID: （超时未收到对方消息）")
    return None


def cmd_reset():
    if CHAT_FILE.exists():
        CHAT_FILE.unlink()
    CHAT_FILE.touch()
    # 扫所有 .pos.* 文件删掉 (不再依赖固定 ROLES 列表)
    for pf in CHAT_FILE.parent.glob(f"{CHAT_FILE.name}.pos.*"):
        try:
            pf.unlink()
        except OSError:
            pass
    # 也清 speak lock (防残留)
    if SPEAK_LOCK.exists():
        try:
            SPEAK_LOCK.unlink()
        except OSError:
            pass
    print(f"[bridge] 已清空 {CHAT_FILE} 和所有 .pos 文件")


def cmd_tail(n=20):
    lines = read_lines()
    for ln in lines[-n:]:
        print(ln.rstrip("\n"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sub = sys.argv[1]
    if sub == "speak":
        if len(sys.argv) < 4:
            print("用法: chat_bridge.py speak <role> <text>", file=sys.stderr)
            sys.exit(1)
        cmd_speak(sys.argv[2], " ".join(sys.argv[3:]))
    elif sub == "listen":
        if len(sys.argv) < 3:
            print("用法: chat_bridge.py listen <role> [timeout] [jump]", file=sys.stderr)
            sys.exit(1)
        timeout = int(sys.argv[3]) if len(sys.argv) >= 4 and sys.argv[3] != "jump" else 600
        jump = "jump" in sys.argv[3:]
        cmd_listen(sys.argv[2], timeout=timeout, jump=jump)
    elif sub == "reset":
        cmd_reset()
    elif sub == "tail":
        cmd_tail()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
