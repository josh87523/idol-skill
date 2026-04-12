#!/usr/bin/env python3
"""
偶像陪伴模式 — 三种场景, 五项优化.

模式:
  work     工作学习陪伴. 专注音乐 + 偶尔碎碎念 (90-150s)
  sleep    哄睡. 棕噪音 + 持续低声 (30-60s)
  workout  健身. 节奏音乐 + 热血鼓励 (45-90s)

优化 (v2):
  1. 响应速度: persona 截断 2000 字 + prompt 精简
  2. BGM duck: ybw 说话时 SIGSTOP BGM, 说完 SIGCONT (短暂暂停不关闭)
  3. 对话记忆: jsonl 持久化, 对话 prompt 带最近 10 条历史
  4. STT: whisper 默认 small (比 base 准, 可 --whisper-model 调)
  5. 碎碎念: prompt 加风格示例 + 不重复同方向

用法:
  python3 companion.py --mode work
  python3 companion.py --mode sleep --whisper-model base  # 用轻量 STT
  python3 companion.py --mode workout --interval-min 30

打断: touch /tmp/companion_mute (闭嘴) / rm (恢复) / pkill afplay (立刻停 TTS)
"""

import argparse
import base64
import json
import math
import os
import random
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env")

VOLC_APPID = os.getenv("VOLC_APPID")
VOLC_TOKEN = os.getenv("VOLC_TOKEN")

MUTE_FILE = Path("/tmp/companion_mute")
IDOL_DATA_DIR = Path(os.getenv("IDOL_DATA_DIR", Path.home() / ".config/idol-skill/idols"))
HISTORY_DIR = SCRIPT_DIR / "companion_history"

# ── 全局状态 ──────────────────────────────────────────────
_speaking = threading.Event()   # ybw 在说话时 set
_last_chat_time = [0.0]         # 上一次用户对话时间

# ── 碎碎念预缓存 (启动时异步预生成, 到时间直接取, 延迟 0) ──
import queue
_mumble_cache = queue.Queue(maxsize=8)
_topics_lock = threading.Lock()  # 保护 recent_topics 跨线程共享

# ── 三种模式预设 ──────────────────────────────────────────
MODES = {
    "work": {
        "label": "工作学习陪伴",
        "interval_min": 90, "interval_max": 150,
        "bgm_subdir": "bgm_work", "bgm_volume": 0.25,
    },
    "sleep": {
        "label": "哄睡",
        "interval_min": 30, "interval_max": 60,
        "bgm_subdir": "bgm_sleep", "bgm_volume": 0.15,
    },
    "workout": {
        "label": "健身",
        "interval_min": 45, "interval_max": 90,
        "bgm_subdir": "bgm_workout", "bgm_volume": 0.4,
    },
}

MODE_PROMPTS = {
    "work": """【工作学习陪伴 — 碎碎念, 不是对话】
场景: 用户在旁边工作, 你在旁边做自己的事, 偶尔自言自语.

内容方向 (每次随机选一个, 不要连续 2 次选同一个方向):
A. 你正在做的事: 调键盘轴体 / 给狗梳毛 / 在听歌 / 刷视频 / 画画 / 研究新装备
B. 你想到的事: 突然想到一个舞蹈动作 / 想起小时候 / 在想吃啥 / 明天安排
C. 你的小发现: 发现好用的 app / 看到窗外 / 宠物搞笑 / 一首好听的歌
D. 关心用户 (最多 1/5 概率): 渴了吧 / 坐太久了动一下 / 眼睛休息一下

**风格示例** (模仿这种自然感, 不要照抄):
- "刚换了个佳达隆的轴 手感有点涩 得润一下"
- "11刚才把我拖鞋叼走了 这狗真的离谱"
- "诶这首歌副歌部分的和弦走向有点意思"

禁止: 问用户问题 / "加油你真棒" 空洞鸡汤 / emoji 颜文字 markdown
输出 1 句, 30-80 字, 纯口语.""",

    "sleep": """【哄睡 — 轻柔低声, 帮入睡】
场景: 深夜, 用户躺在床上, 你轻声陪着.

内容方向 (随机):
A. 安静画面: 月光 / 海浪 / 森林的风 / 雨声 / 星空 / 雪
B. 温柔小事: 今天的小事 / 小时候的记忆 / 想象的旅行
C. 碎碎念: 被子暖不暖 / 闭上眼睛 / 明天又是新的一天
D. 诗意短句: 安静的 有画面感的

**风格示例**:
- "窗外好像下雨了 你听那个声音 滴滴答答的 挺好听"
- "今天也结束了 什么都不用想 就这样躺着就好"

禁止: 问用户问题 / 激动语气 / emoji 颜文字 markdown
语气: 轻柔缓慢, 像呼吸
输出 1 句, 20-60 字.""",

    "workout": """【健身 — 热血教练, 陪练】
场景: 用户在健身, 你是一起练的搭档.

内容方向 (随机):
A. 鼓励: 再来一组 / 最后几个 / 刚才那组不错
B. 自己感受: 我刚练完腿酸了 / 这个动作核心发力 / 今天状态好
C. 提醒: 喝水 / 拉伸 / 组间别太久
D. 闲聊: 练完吃啥 / 最近体能 / 我这个动作标准不

**风格示例**:
- "来 最后五个 别偷懒 我看着呢"
- "刚才那组比上次强了 继续保持"

禁止: 长篇大论 / 温柔语气 / emoji markdown
语气: 有劲 直接 短促
输出 1 句, 20-50 字.""",
}


# ── 对话历史 (jsonl 持久化) ────────────────────────────────
_history = []  # [{role, text, ts}]


def load_history(slug):
    global _history
    HISTORY_DIR.mkdir(exist_ok=True)
    f = HISTORY_DIR / f"{slug}.jsonl"
    if f.exists():
        try:
            lines = f.read_text().strip().split("\n")
            _history = [json.loads(ln) for ln in lines[-50:] if ln.strip()]
            print(f"[companion] 加载 {len(_history)} 条历史", flush=True)
        except Exception:
            _history = []


def append_history(role, text, slug):
    entry = {"role": role, "text": text, "ts": time.time()}
    _history.append(entry)
    HISTORY_DIR.mkdir(exist_ok=True)
    with open(HISTORY_DIR / f"{slug}.jsonl", "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent_history_str(n=10):
    if not _history:
        return "(暂无历史)"
    lines = []
    for h in _history[-n:]:
        tag = "你" if h["role"] == "idol" else "用户"
        lines.append(f"{tag}: {h['text']}")
    return "\n".join(lines)


# ── BGM 播放器 ─────────────────────────────────────────────
_bgm_proc = None
_bgm_lock = threading.Lock()


def get_bgm_files(bgm_dir):
    exts = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aiff"}
    return sorted(f for f in Path(bgm_dir).iterdir() if f.suffix.lower() in exts and f.is_file())


def bgm_loop(bgm_dir, volume=0.3):
    global _bgm_proc
    files = get_bgm_files(bgm_dir)
    if not files:
        return
    print(f"[companion] BGM 播放列表: {len(files)} 首", flush=True)
    playlist = list(files)
    random.shuffle(playlist)
    idx = 0
    while True:
        track = playlist[idx % len(playlist)]
        print(f"[companion] BGM: {track.name}", flush=True)
        with _bgm_lock:
            _bgm_proc = subprocess.Popen(
                ["afplay", "-v", str(volume), str(track)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        _bgm_proc.wait()
        with _bgm_lock:
            _bgm_proc = None
        idx += 1
        if idx >= len(playlist):
            random.shuffle(playlist)
            idx = 0
        time.sleep(0.5)


def duck_bgm():
    """ybw 说话时暂停 BGM (SIGSTOP), 短暂几秒不是关掉"""
    with _bgm_lock:
        if _bgm_proc and _bgm_proc.poll() is None:
            try:
                os.kill(_bgm_proc.pid, signal.SIGSTOP)
            except OSError:
                pass


def unduck_bgm():
    """ybw 说完恢复 BGM (SIGCONT)"""
    with _bgm_lock:
        if _bgm_proc and _bgm_proc.poll() is None:
            try:
                os.kill(_bgm_proc.pid, signal.SIGCONT)
            except OSError:
                pass


# ── TTS 播放 (带 duck) ────────────────────────────────────
def tts_play(text, speaker_id):
    """火山引擎 TTS → 临时 wav → duck BGM → afplay → unduck"""
    import requests

    if not all([VOLC_APPID, VOLC_TOKEN, speaker_id]):
        print(f"[companion] 缺 TTS 凭证, 仅文字: {text}", flush=True)
        return
    resp = requests.post(
        "https://openspeech.bytedance.com/api/v1/tts",
        json={
            "app": {"appid": VOLC_APPID, "token": VOLC_TOKEN, "cluster": "volcano_icl"},
            "user": {"uid": "companion"},
            "audio": {"voice_type": speaker_id, "encoding": "wav", "speed_ratio": 1.0},
            "request": {"reqid": str(uuid.uuid4()), "text": text, "operation": "query"},
        },
        headers={"Authorization": f"Bearer;{VOLC_TOKEN}", "Content-Type": "application/json"},
        timeout=15,
    )
    result = resp.json()
    if "data" not in result:
        print(f"[companion] TTS 失败: {result.get('message', 'unknown')}", flush=True)
        return
    audio = base64.b64decode(result["data"])
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        tmp_path = tmp.name
    duck_bgm()
    try:
        subprocess.run(["afplay", tmp_path], check=False)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        unduck_bgm()


# ── LLM ──────────────────────────────────────────────────
def load_persona(slug):
    for try_slug in [slug, "yangbaiwan", "ybw"]:
        p = IDOL_DATA_DIR / try_slug / "persona.md"
        if p.exists():
            # 优化1: 截断 persona 避免 prompt 过长
            text = p.read_text(encoding="utf-8")
            return text[:2000], try_slug
    return "", slug


MUMBLE_PROMPT = """{persona}

---
{mode_prompt}

之前你说过的 (严格避免重复, 换个方向):
{recent_topics}

直接输出 1 句话, 不要加前缀/引号."""


def _generate_one_mumble(persona, slug, recent_topics, mode, model):
    """内部: 调 claude CLI 生成一条碎碎念 (阻塞 ~15s)"""
    topics_str = "\n".join(f"- {t}" for t in recent_topics[-10:]) if recent_topics else "(还没说过)"
    prompt = MUMBLE_PROMPT.format(
        persona=persona,
        mode_prompt=MODE_PROMPTS.get(mode, MODE_PROMPTS["work"]),
        recent_topics=topics_str,
    )
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        return ""
    text = r.stdout.strip()
    for prefix in [f"[{slug}]", "[ybw]", "[yangbaiwan]"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text.strip("「」\"'")


def _cache_filler(persona, slug, recent_topics, mode, model):
    """后台线程: 持续预生成碎碎念填充缓存 (保持 cache 不空)"""
    while True:
        if _mumble_cache.full():
            time.sleep(5)
            continue
        with _topics_lock:
            topics_snapshot = list(recent_topics)
        text = _generate_one_mumble(persona, slug, topics_snapshot, mode, model)
        if text:
            _mumble_cache.put(text)
            with _topics_lock:
                recent_topics.append(text[:50])
                if len(recent_topics) > 15:
                    recent_topics.pop(0)
        time.sleep(1)


def get_cached_mumble():
    """从缓存取一条碎碎念 (延迟 0). 缓存空则返回 None"""
    try:
        return _mumble_cache.get_nowait()
    except queue.Empty:
        return None


REPLY_PROMPT = """{persona}

---
用户跟你搭话了. 你们在同一个房间, 自然回应像朋友聊天.
不要 emoji / 颜文字 / markdown (TTS 出戏). 1-2 句, 30-80 字, 纯口语.

最近对话:
{history}

用户刚说: {user_text}

直接输出回复, 不加前缀."""


def generate_reply(persona, user_text, slug, model):
    prompt = REPLY_PROMPT.format(
        persona=persona, user_text=user_text, history=recent_history_str(10),
    )
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip().strip("「」\"'")


# ── mic 录音 + STT ────────────────────────────────────────
MIC_RATE = 16000
MIC_CHUNK = 1024
MIC_SILENCE_SEC = 1.5
MIC_MIN_SPEECH = 10


def record_one(pa, threshold=120):
    import pyaudio
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=MIC_RATE,
                     input=True, frames_per_buffer=MIC_CHUNK)
    frames = []
    silent_chunks = 0
    speech_chunks = 0
    has_speech = False
    max_silent = int(MIC_SILENCE_SEC * MIC_RATE / MIC_CHUNK)
    try:
        while True:
            if _speaking.is_set():
                return None
            data = stream.read(MIC_CHUNK, exception_on_overflow=False)
            frames.append(data)
            count = len(data) // 2
            shorts = struct.unpack(f"{count}h", data)
            rms = (sum(s * s for s in shorts) / count) ** 0.5
            if rms > threshold:
                silent_chunks = 0
                speech_chunks += 1
                if not has_speech:
                    has_speech = True
            else:
                if has_speech and speech_chunks >= MIC_MIN_SPEECH:
                    silent_chunks += 1
                    if silent_chunks >= max_silent:
                        break
            if len(frames) > MIC_RATE / MIC_CHUNK * 60:
                break
    finally:
        stream.stop_stream()
        stream.close()
    return b"".join(frames) if has_speech else None


def transcribe(stt, frames):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(MIC_RATE)
        wf.writeframes(frames)
    try:
        segments, _ = stt.transcribe(tmp.name, language="zh")
        return "".join(seg.text for seg in segments).strip()
    finally:
        os.unlink(tmp.name)


def is_garbage(text):
    if not text or len(text.strip()) < 2:
        return True
    for slen in (1, 2, 3):
        if len(text) >= slen * 5:
            for i in range(len(text) - slen * 5 + 1):
                s = text[i:i + slen]
                if s.strip() and text[i:i + slen * 5] == s * 5:
                    return True
    return False


def mic_loop(persona, speaker, slug, model, threshold, whisper_model):
    import pyaudio
    from faster_whisper import WhisperModel
    print(f"[companion] mic: 加载 whisper {whisper_model}...", flush=True)
    stt = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    pa = pyaudio.PyAudio()
    print("[companion] mic: 就绪, 随时说话", flush=True)

    try:
        while True:
            while _speaking.is_set():
                time.sleep(0.1)
            frames = record_one(pa, threshold)
            if not frames:
                time.sleep(0.2)
                continue
            text = transcribe(stt, frames)
            if is_garbage(text):
                continue

            print(f"[companion] 你: {text}", flush=True)
            append_history("user", text, slug)
            _last_chat_time[0] = time.time()

            reply = generate_reply(persona, text, slug, model)
            if not reply:
                continue

            print(f"[companion] {slug}: {reply}", flush=True)
            append_history("idol", reply, slug)

            _speaking.set()
            tts_play(reply, speaker)
            time.sleep(0.3)
            _speaking.clear()
            _last_chat_time[0] = time.time()
    except Exception as e:
        print(f"[companion] mic 异常: {e}", flush=True)
    finally:
        pa.terminate()


# ── 主循环 ─────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="偶像陪伴模式 v2")
    ap.add_argument("--mode", default="work", choices=MODES.keys())
    ap.add_argument("--slug", default="yangbaiwan")
    ap.add_argument("--interval-min", type=int, default=None)
    ap.add_argument("--interval-max", type=int, default=None)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--whisper-model", default="small",
                    help="STT 模型 (base/small/medium/large-v3), 默认 small")
    ap.add_argument("--bgm-dir", default=None)
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--threshold", type=int, default=120, help="mic 静音阈值")
    ap.add_argument("--max-rounds", type=int, default=200)
    args = ap.parse_args()

    preset = MODES[args.mode]
    interval_min = args.interval_min or preset["interval_min"]
    interval_max = args.interval_max or preset["interval_max"]
    bgm_dir = Path(args.bgm_dir) if args.bgm_dir else SCRIPT_DIR / preset["bgm_subdir"]

    persona, actual_slug = load_persona(args.slug)
    if not persona:
        print(f"[companion] 找不到 {args.slug} 的 persona.md", file=sys.stderr)
        sys.exit(3)

    speaker_env = f"VOLC_{actual_slug.upper()}_SPEAKER_ID"
    speaker = os.getenv(speaker_env) or os.getenv("VOLC_YBW_SPEAKER_ID") or os.getenv("VOLC_SPEAKER_ID")

    load_history(actual_slug)

    if MUTE_FILE.exists():
        MUTE_FILE.unlink()

    print(f"[companion] 模式: {args.mode} ({preset['label']})", flush=True)
    print(f"[companion] 偶像: {actual_slug}, LLM: {args.model}, STT: {args.whisper_model}", flush=True)
    print(f"[companion] 间隔: {interval_min}-{interval_max}s, threshold: {args.threshold}", flush=True)

    if not args.no_bgm:
        bgm_dir.mkdir(exist_ok=True)
        bgm_files = get_bgm_files(bgm_dir)
        if bgm_files:
            threading.Thread(target=bgm_loop, args=(bgm_dir, preset["bgm_volume"]), daemon=True).start()
            print(f"[companion] BGM: {len(bgm_files)} 首", flush=True)
        else:
            print(f"[companion] {bgm_dir} 为空, 放 wav/mp3 进去就有音乐", flush=True)

    mode_labels = {"work": "陪你工作", "sleep": "哄你睡觉", "workout": "陪你健身"}
    print("=" * 50, flush=True)
    print(f"  {preset['label']}模式 — {actual_slug} {mode_labels.get(args.mode)}", flush=True)
    print(f"  随时对着麦克风说话 / touch {MUTE_FILE} 闭嘴 / Ctrl+C 退出", flush=True)
    print("=" * 50, flush=True)

    threading.Thread(
        target=mic_loop,
        args=(persona, speaker, actual_slug, args.model, args.threshold, args.whisper_model),
        daemon=True,
    ).start()

    # 预缓存: 后台持续填充碎碎念, 主循环直接取
    recent_topics = []
    threading.Thread(
        target=_cache_filler,
        args=(persona, actual_slug, recent_topics, args.mode, args.model),
        daemon=True,
    ).start()
    print("[companion] 碎碎念预缓存启动, 后台预生成中...", flush=True)

    CHAT_COOLDOWN = 30

    try:
        for i in range(args.max_rounds):
            wait = random.randint(interval_min, interval_max)
            for _ in range(wait):
                time.sleep(1)

            if MUTE_FILE.exists():
                continue
            if time.time() - _last_chat_time[0] < CHAT_COOLDOWN:
                continue

            # 从预缓存取 (延迟 0, 不等 claude CLI)
            text = get_cached_mumble()
            if not text:
                print("[companion] 缓存空, 等下一轮", flush=True)
                continue
            if MUTE_FILE.exists():
                continue

            print(f"[companion] {actual_slug}: {text}", flush=True)
            append_history("idol", text, actual_slug)

            _speaking.set()
            tts_play(text, speaker)
            time.sleep(0.3)
            _speaking.clear()

    except KeyboardInterrupt:
        print("\n[companion] 退出", flush=True)
    finally:
        with _bgm_lock:
            if _bgm_proc and _bgm_proc.poll() is None:
                _bgm_proc.terminate()
        if MUTE_FILE.exists():
            MUTE_FILE.unlink()


if __name__ == "__main__":
    main()
