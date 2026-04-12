"""
idol-skill · Voice Chat — real-time voice conversation with any idol persona.

Pipeline:
  microphone → faster-whisper (STT) → Claude CLI (LLM) → 火山引擎 TTS (clone voice) → afplay

Features:
- Universal: discovers all idols in $IDOL_DATA_DIR (default ~/.config/idol-skill/idols/)
- Loads full persona: persona.md + presence.md + profile.md + timeline.md
- Real few-shot corpus from knowledge/weibo/idol_weibos.json
- Optional per-idol voice_chat.json with multi-state (day/night/...) config:
    - different TTS speaker per state
    - different model / length / BGM per state
    - time-based auto state switching
    - keyword-based state detection ("想睡" → night)
- Conversation history persisted as jsonl, auto-resume next launch
- Long text TTS auto-segment + silence padding to avoid pops
- BGM loop with SIGSTOP/SIGCONT pause during mic recording (prevents feedback)

Usage:
    python3 voice_chat.py --idol <slug>              # auto state by time
    python3 voice_chat.py --idol <slug> --state day
    python3 voice_chat.py --idol <slug> --fresh      # skip history
    python3 voice_chat.py --list                     # list all idols
    python3 voice_chat.py --idol <slug> --model sonnet  # override model

Environment (in .env next to script or in shell):
    VOLC_APPID, VOLC_TOKEN                    火山引擎账号
    VOLC_{SLUG_UPPER}_SPEAKER_ID              默认声线 (slug 大写, - → _)
    VOLC_{SLUG_UPPER}_{STATE_UPPER}_SPEAKER_ID  按 state 覆盖 (可选)
    VOLC_SPEAKER_ID                           全局兜底
    IDOL_DATA_DIR                             偶像数据目录 (默认 ~/.config/idol-skill/idols)
"""

import argparse
import base64
import io
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import uuid
import wave
from pathlib import Path

try:
    import pyaudio
except ImportError:
    print("错误: 缺少 pyaudio。macOS: brew install portaudio && pip3 install pyaudio")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(_p=None):
        pass

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("错误: 缺少 faster-whisper。pip3 install faster-whisper")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.resolve()
IDOL_DATA_DIR = Path(os.environ.get(
    "IDOL_DATA_DIR",
    os.path.expanduser("~/.config/idol-skill/idols")
))

CLAUDE_BIN = (
    shutil.which("claude")
    or ("/opt/homebrew/bin/claude" if os.path.exists("/opt/homebrew/bin/claude") else None)
    or "/usr/local/bin/claude"
)


# ── 偶像发现 ──────────────────────────────────────────────
def discover_idols():
    if not IDOL_DATA_DIR.exists():
        return []
    return sorted([
        p.name for p in IDOL_DATA_DIR.iterdir()
        if p.is_dir() and (p / "persona.md").exists()
    ])


# ── 参数 ──────────────────────────────────────────────────
_ap = argparse.ArgumentParser(description="idol-skill voice chat")
_ap.add_argument("--idol", help="偶像 slug (见 --list)")
_ap.add_argument("--list", action="store_true", help="列出所有可用偶像")
_ap.add_argument("--state", help="强制初始状态名（day/night/... 按 voice_chat.json 配置）")
_ap.add_argument("--model", default="haiku",
                 help="Claude 模型 (haiku/sonnet/opus)，会被 state 里的 model 覆盖")
_ap.add_argument("--fresh", action="store_true", help="不加载对话历史")
_args = _ap.parse_args()

if _args.list:
    slugs = discover_idols()
    if not slugs:
        print(f"未发现偶像（目录: {IDOL_DATA_DIR}）")
        print("先用 /create-idol 创建一个")
    else:
        print(f"偶像目录: {IDOL_DATA_DIR}")
        for s in slugs:
            print(f"  - {s}")
    sys.exit(0)

if not _args.idol:
    print("错误: 必须指定 --idol <slug>，或 --list 查看可用偶像")
    sys.exit(1)

idol_dir = IDOL_DATA_DIR / _args.idol
if not (idol_dir / "persona.md").exists():
    print(f"错误: 偶像「{_args.idol}」不存在或没有 persona.md")
    print(f"路径: {idol_dir}")
    print("可用偶像:")
    for s in discover_idols():
        print(f"  - {s}")
    sys.exit(1)

load_dotenv(SCRIPT_DIR / ".env")

VOLC_APPID = os.getenv("VOLC_APPID")
VOLC_TOKEN = os.getenv("VOLC_TOKEN")
VOLC_VOICE_TYPE = os.getenv("VOLC_VOICE_TYPE", "zh_male_M392_conversation_wvae_bigtts")

USE_VOLCENGINE = bool(VOLC_APPID and VOLC_TOKEN)
if USE_VOLCENGINE:
    import requests
    print("TTS 引擎: 火山引擎 (豆包)")
else:
    print("错误: .env 缺少 VOLC_APPID / VOLC_TOKEN，无法使用火山引擎 TTS")
    print("请参考 .env.example 配置，或扩展本脚本支持其他 TTS 引擎")
    sys.exit(1)


# ── Persona 加载 ──────────────────────────────────────────
def _read_if_exists(path):
    try:
        return Path(path).read_text() if Path(path).exists() else ""
    except Exception:
        return ""


IDOL_PERSONA = _read_if_exists(idol_dir / "persona.md")
IDOL_PRESENCE = _read_if_exists(idol_dir / "presence.md")
IDOL_PROFILE = _read_if_exists(idol_dir / "profile.md")
IDOL_TIMELINE = _read_if_exists(idol_dir / "timeline.md")

# 真实微博语料 few-shot
IDOL_WEIBOS = ""
_weibo_json = idol_dir / "knowledge/weibo/idol_weibos.json"
if _weibo_json.exists():
    try:
        _wb = json.loads(_weibo_json.read_text())
        if isinstance(_wb, dict):
            _wb = _wb.get("data") or _wb.get("weibos") or []
        if isinstance(_wb, list):
            _texts = []
            for item in _wb[:20]:
                if isinstance(item, dict):
                    t = item.get("text") or item.get("content") or ""
                elif isinstance(item, str):
                    t = item
                else:
                    continue
                t = t.strip()
                if t and len(t) < 500:
                    _texts.append(t)
            if _texts:
                IDOL_WEIBOS = "\n".join(f"- {t}" for t in _texts[:12])
    except Exception as e:
        print(f"   weibo 语料加载失败: {e}")

print(f"偶像人格: 已加载 persona.md ({_args.idol})")
if IDOL_PROFILE:
    print(f"            + profile.md")
if IDOL_TIMELINE:
    print(f"            + timeline.md")
if IDOL_PRESENCE:
    print(f"            + presence.md")
if IDOL_WEIBOS:
    print(f"            + 真实微博 few-shot ({IDOL_WEIBOS.count(chr(10))+1} 条)")


# ── 状态机配置 ────────────────────────────────────────────
# 优先加载 idol_dir/voice_chat.json，没有则用 default 单 state
def _load_states_config():
    cfg_path = idol_dir / "voice_chat.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception as e:
            print(f"   voice_chat.json 解析失败: {e}，用默认配置")
    # 默认配置：单 state
    slug_upper = _args.idol.upper().replace("-", "_")
    return {
        "states": {
            "default": {
                "speaker_env": f"VOLC_{slug_upper}_SPEAKER_ID",
                "label": "默认",
                "length": [80, 250],
                "model": _args.model,
                "tone": "自然聊天，按人设说话。",
            }
        },
        "initial_state": "default",
    }


STATES_CONFIG = _load_states_config()
STATES = STATES_CONFIG.get("states", {})


def _initial_state():
    # 命令行强制
    if _args.state and _args.state in STATES:
        return _args.state
    # time_rules.night_hours: [start, end]（跨天区间）
    rules = STATES_CONFIG.get("time_rules", {})
    night_hours = rules.get("night_hours")
    if night_hours and len(night_hours) == 2 and "night" in STATES and "day" in STATES:
        import datetime as _dt
        h = _dt.datetime.now().hour
        start, end = night_hours
        is_night = (h >= start or h < end) if start > end else (start <= h < end)
        return "night" if is_night else "day"
    # fallback: initial_state 或第一个 state
    return STATES_CONFIG.get("initial_state") or next(iter(STATES.keys()), "default")


current_state = _initial_state()
_state_info_init = STATES.get(current_state, {})
print(f"初始状态: {_args.idol}/{current_state} ({_state_info_init.get('label', '')})")


def current_speaker_id():
    info = STATES.get(current_state, {})
    env = info.get("speaker_env")
    if env:
        sid = os.getenv(env)
        if sid:
            return sid
    return os.getenv("VOLC_SPEAKER_ID") or ""


def current_state_tone():
    return STATES.get(current_state, {}).get("tone", "")


# ── 状态切换（关键词触发）─────────────────────────────────
NIGHT_KEYWORDS_DEFAULT = [
    "睡不着", "想睡", "要睡", "哄我睡", "哄睡", "陪我睡", "温柔点",
    "轻点", "小声", "晚安", "好困", "好累", "我困了", "闭眼",
]
DAY_KEYWORDS_DEFAULT = [
    "早上好", "起床", "醒了", "醒过来", "精神点", "元气",
    "白天", "切白天", "早安",
]


def detect_state(user_text, current):
    if len(STATES) <= 1:
        return current
    triggers = STATES_CONFIG.get("triggers", {})
    night_kw = triggers.get("night", NIGHT_KEYWORDS_DEFAULT)
    day_kw = triggers.get("day", DAY_KEYWORDS_DEFAULT)
    if "night" in STATES and any(k in user_text for k in night_kw):
        return "night"
    if "day" in STATES and any(k in user_text for k in day_kw):
        return "day"
    return current


# ── BGM（per-state 循环播放）──────────────────────────────
_bgm_proc = None


def _start_bgm():
    global _bgm_proc
    info = STATES.get(current_state, {})
    bgm_file = info.get("bgm")
    if not bgm_file:
        return
    # 先在 idol 目录找，再在 script 同级找
    bgm_path = idol_dir / bgm_file
    if not bgm_path.exists():
        bgm_path = SCRIPT_DIR / bgm_file
    if not bgm_path.exists():
        print(f"   (BGM 文件缺失: {bgm_file}，跳过)")
        return
    vol = info.get("bgm_volume", 0.2)
    _bgm_proc = subprocess.Popen(
        ["bash", "-c", f'while true; do afplay -v {vol} "{bgm_path}"; done'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    print(f"   ♪ BGM 启动: {bgm_path.name} (vol={vol})")


def _stop_bgm():
    global _bgm_proc
    if _bgm_proc is not None:
        try:
            os.killpg(os.getpgid(_bgm_proc.pid), signal.SIGTERM)
        except Exception:
            pass
        _bgm_proc = None


def _pause_bgm():
    if _bgm_proc is not None:
        try:
            os.killpg(os.getpgid(_bgm_proc.pid), signal.SIGSTOP)
        except Exception:
            pass


def _resume_bgm():
    if _bgm_proc is not None:
        try:
            os.killpg(os.getpgid(_bgm_proc.pid), signal.SIGCONT)
        except Exception:
            pass


def _switch_bgm_if_needed():
    _stop_bgm()
    _start_bgm()


import atexit
atexit.register(_stop_bgm)


# ── System Prompt 构建 ────────────────────────────────────
_base_instruction = (
    f"你是{_args.idol}。下面是你的完整人设、口癖、真实语料。严格按照这些还原自己，不许跳出角色。"
)

_persona_block = ""
if IDOL_PERSONA:
    _persona_block += "\n\n## 完整人设（persona.md）\n" + IDOL_PERSONA
if IDOL_PRESENCE:
    _persona_block += "\n\n## 口癖与句式（presence.md）\n" + IDOL_PRESENCE
if IDOL_PROFILE:
    _persona_block += "\n\n## 用户关系与昵称规则（profile.md）\n" + IDOL_PROFILE
if IDOL_TIMELINE:
    _persona_block += "\n\n## 时间线（timeline.md）\n" + IDOL_TIMELINE
if IDOL_WEIBOS:
    _persona_block += (
        "\n\n## 你的真实微博语料（模仿语气、短句节奏、口癖；不要逐字复读）\n"
        + IDOL_WEIBOS
    )

SYSTEM_PROMPT = (
    _base_instruction
    + _persona_block
    + "\n\n## 回复硬性要求（最高优先级）\n"
      "- 你是**活人**，用真人语气聊天，不是写散文不是客服不是治疗师\n"
      "- **严禁跳出角色**：不能说「根据我的人设」「我是 AI」「按照我的设定」\n"
      "- **严禁自称 MBTI**：不能说「INTJ 嘛」「作为 INFP」这种话\n"
      "- **严禁元视角**：不能说「我的微博」「我在采访里」「微博里的我」\n"
      "- **严禁 AI 公式**：不用排比列举凑温柔，不用鸡汤腔"
      "（「你的每一句话我都装心里头了」），不用固定收尾三件套\n"
      "- **鼓励**：笨拙、害羞、一句话接不上、冷不丁的小反应、地道口癖\n"
      "- 严禁 emoji、颜文字、markdown、括号旁白、舞台指示、星号动作\n"
      "- 纯文字输出，不要任何前缀、引号、说明\n"
      "- 模仿真实微博语料的短句节奏，不要写成童话故事或 guided meditation\n"
)

# ── 音频参数 & STT ────────────────────────────────────────
RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024
SILENCE_THRESHOLD = 100
SILENCE_DURATION = 0.8
MIN_SPEECH_CHUNKS = 10

print("正在加载语音识别模型...")
stt_model = WhisperModel("base", device="cpu", compute_type="int8")
print("模型加载完成。")

pa = pyaudio.PyAudio()
conversation_history = []


# ── 对话历史持久化 ────────────────────────────────────────
HISTORY_DIR = SCRIPT_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)
HISTORY_FILE = HISTORY_DIR / f"{_args.idol}.jsonl"


def _load_history(max_turns=20):
    if _args.fresh or not HISTORY_FILE.exists():
        return 0
    try:
        lines = [l for l in HISTORY_FILE.read_text().splitlines() if l.strip()]
        lines = lines[-max_turns * 2:]
        for line in lines:
            try:
                obj = json.loads(line)
                role = "用户" if obj["role"] == "user" else "助手"
                conversation_history.append(f"{role}: {obj['content']}")
            except json.JSONDecodeError:
                continue
        return len(conversation_history)
    except Exception as e:
        print(f"   加载历史失败: {e}")
        return 0


def _save_turn(user_text, reply):
    try:
        with HISTORY_FILE.open("a") as f:
            f.write(json.dumps({"role": "user", "content": user_text},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"role": "assistant", "content": reply},
                               ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"   保存历史失败: {e}")


_loaded = _load_history()
if _loaded > 0:
    print(f"   已加载上次对话历史: {_loaded} 条 ({HISTORY_FILE.name})")
elif _args.fresh:
    print("   --fresh 从头开始")
else:
    print("   (无历史)")


# ── 录音 / STT / 工具函数 ────────────────────────────────
def get_rms(data):
    count = len(data) // 2
    shorts = struct.unpack(f"{count}h", data)
    sum_squares = sum(s * s for s in shorts)
    return (sum_squares / count) ** 0.5


def play_beep():
    import math
    duration = 0.15
    freq = 800
    n_samples = int(24000 * duration)
    samples = bytes(
        int(127 + 80 * math.sin(2 * math.pi * freq * i / 24000))
        for i in range(n_samples)
    )
    stream = pa.open(format=pyaudio.paUInt8, channels=1, rate=24000, output=True)
    stream.write(samples)
    stream.stop_stream()
    stream.close()


def record_audio():
    play_beep()
    stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)
    print("\n🎤 请说话...")

    frames = []
    silent_chunks = 0
    speech_chunks = 0
    has_speech = False
    max_silent = int(SILENCE_DURATION * RATE / CHUNK)

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            rms = get_rms(data)
            if rms > SILENCE_THRESHOLD:
                silent_chunks = 0
                speech_chunks += 1
                if not has_speech:
                    has_speech = True
                    print("   检测到语音，录音中...")
            else:
                if has_speech and speech_chunks >= MIN_SPEECH_CHUNKS:
                    silent_chunks += 1
                    if silent_chunks >= max_silent:
                        print("   录音结束")
                        break
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()

    if not has_speech:
        return None

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pa.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    return tmp.name


def speech_to_text(audio_path):
    segments, info = stt_model.transcribe(
        audio_path, language="zh", vad_filter=True
    )
    text = "".join(seg.text for seg in segments).strip()
    os.unlink(audio_path)
    return text


# ── LLM 调用 ──────────────────────────────────────────────
def chat_with_llm(user_text):
    global current_state
    new_state = detect_state(user_text, current_state)
    if new_state != current_state:
        old_label = STATES[current_state].get("label", current_state)
        new_label = STATES[new_state].get("label", new_state)
        print(f"   ⇢ 状态切换: {old_label} → {new_label}")
        current_state = new_state
        _switch_bgm_if_needed()

    conversation_history.append(f"用户: {user_text}")
    if len(conversation_history) > 40:
        conversation_history[:] = conversation_history[-40:]

    context = "\n".join(conversation_history[-16:])  # 最近 8 轮进 prompt
    state_info = STATES.get(current_state, {})
    state_tone = state_info.get("tone", "")
    state_block = f"\n\n## 当前状态（必须遵守）\n{state_tone}\n" if state_tone else ""

    length = state_info.get("length", [80, 250])
    if isinstance(length, list) and len(length) == 2:
        min_len, max_len = length
    else:
        min_len, max_len = 80, 250
    state_model = state_info.get("model") or _args.model

    import datetime as _dt
    _now = _dt.datetime.now()
    has_multi_state = "day" in STATES and "night" in STATES
    if has_multi_state:
        _label = ("白天（如果对话历史里有深夜情绪片段，那都是昨晚的事儿，现在妈妈已经醒了）"
                  if current_state == "day" else "深夜")
        time_header = (
            f"【当前时间】{_now.strftime('%Y-%m-%d %H:%M')} — {_label}\n"
            f"【重要】不要沿用历史里不属于当前状态的情绪（比如历史是哄睡而当前是白天），"
            f"按当前状态{current_state}的要求聊。\n\n"
        )
    else:
        time_header = ""

    length_header = (
        f"【本次回复长度】{min_len}-{max_len} 字之间，自然短句，真人聊天。\n\n"
    )

    prompt = (
        f"{time_header}{length_header}{SYSTEM_PROMPT}{state_block}\n\n"
        f"对话历史（最近 8 轮）:\n{context}\n\n"
        f"请回复用户最新的消息。只输出回复正文。"
    )

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", state_model, prompt],
            capture_output=True, text=True, timeout=90,
        )
        reply = result.stdout.strip()
    except subprocess.TimeoutExpired:
        reply = ""
    except FileNotFoundError:
        print(f"   ❌ 找不到 claude CLI ({CLAUDE_BIN})，请安装 Claude Code")
        reply = ""

    # 严重过短才扩写
    if reply and len(reply) < max(min_len // 3, 20):
        print(f"   ⚠ 回复过短 ({len(reply)} 字)，扩写…")
        expand_prompt = (
            f"{time_header}{length_header}{SYSTEM_PROMPT}{state_block}\n\n"
            f"对话历史:\n{context}\n\n"
            f"你刚才的草稿太短（{len(reply)} 字）：\n「{reply}」\n\n"
            f"往后自然续写到 {min_len}-{max_len} 字。不要编童话，不要排比，"
            f"就是真人继续聊。只输出最终版本。"
        )
        try:
            result2 = subprocess.run(
                [CLAUDE_BIN, "-p", "--model", state_model, expand_prompt],
                capture_output=True, text=True, timeout=90,
            )
            expanded = result2.stdout.strip()
            if expanded and len(expanded) >= len(reply):
                reply = expanded
                print(f"   ✓ 扩写后 {len(reply)} 字")
        except Exception:
            pass

    if not reply:
        reply = "嗯……"

    conversation_history.append(f"助手: {reply}")
    _save_turn(user_text, reply)
    return reply


# ── TTS（分段 + 静音垫片 + 拼接）──────────────────────────
def _split_for_tts(text, max_chars=400):
    import re as _re
    sentences = _re.split(r"(?<=[。！？!?.；;~\n])", text)
    chunks = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) <= max_chars:
            buf += s
        else:
            if buf:
                chunks.append(buf)
            if len(s) > max_chars:
                parts = _re.split(r"(?<=[，,、])", s)
                buf2 = ""
                for p in parts:
                    if len(buf2) + len(p) <= max_chars:
                        buf2 += p
                    else:
                        if buf2:
                            chunks.append(buf2)
                        buf2 = p
                buf = buf2
            else:
                buf = s
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


def _tts_one(text, voice, cluster):
    payload = {
        "app": {"appid": VOLC_APPID, "token": VOLC_TOKEN, "cluster": cluster},
        "user": {"uid": "idol_voice_chat"},
        "audio": {"voice_type": voice, "encoding": "wav", "speed_ratio": 1.0},
        "request": {"reqid": str(uuid.uuid4()), "text": text, "operation": "query"},
    }
    resp = requests.post(
        "https://openspeech.bytedance.com/api/v1/tts",
        json=payload,
        headers={"Authorization": f"Bearer;{VOLC_TOKEN}",
                 "Content-Type": "application/json"},
        timeout=60,
    )
    result = resp.json()
    if "data" not in result:
        print(f"   TTS 错误: {json.dumps(result, ensure_ascii=False)[:200]}")
        return None
    return base64.b64decode(result["data"])


def _concat_wav(wav_bytes_list, silence_ms=80):
    if not wav_bytes_list:
        return None
    if len(wav_bytes_list) == 1:
        return wav_bytes_list[0]

    frames = []
    ref_params = None
    for i, wb in enumerate(wav_bytes_list):
        with wave.open(io.BytesIO(wb), "rb") as wf:
            p = wf.getparams()
            if ref_params is None:
                ref_params = p
            elif (p.nchannels, p.sampwidth, p.framerate) != (
                ref_params.nchannels, ref_params.sampwidth, ref_params.framerate
            ):
                print(f"   ⚠ 第 {i+1} 段 wav 参数不一致，跳过拼接")
                return wav_bytes_list[0]
            frames.append(wf.readframes(wf.getnframes()))

    silence_frames = int(ref_params.framerate * silence_ms / 1000)
    silence_bytes = (b"\x00" * ref_params.sampwidth * ref_params.nchannels) * silence_frames

    joined = frames[0]
    for f in frames[1:]:
        joined += silence_bytes + f

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setparams(ref_params)
        wf.writeframes(joined)
    return out.getvalue()


def text_to_speech(text):
    sid = current_speaker_id()
    if not sid:
        print("   ⚠ 当前状态没有可用 speaker_id，跳过 TTS")
        return None
    voice = sid
    cluster = "volcano_icl"

    chunks = _split_for_tts(text, max_chars=400)
    if not chunks:
        return None
    print(f"   TTS 分段: {len(chunks)} 段 (speaker={voice[:12]}…)")
    pieces = []
    for i, c in enumerate(chunks, 1):
        audio = _tts_one(c, voice, cluster)
        if audio is None:
            print(f"   第 {i}/{len(chunks)} 段失败")
            return None
        pieces.append(audio)
    return _concat_wav(pieces)


def play_audio(audio_bytes):
    """走 macOS afplay，比 pyaudio 重采样更干净（避免电流声）"""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(audio_bytes)
    tmp.close()
    try:
        subprocess.run(["afplay", tmp.name], check=False)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ── 主循环 ────────────────────────────────────────────────
def main():
    print("\n" + "=" * 50)
    print(f"  idol-skill Voice Chat · {_args.idol}")
    print(f"  LLM: claude {_args.model}   状态: {current_state}")
    print("  说话后静音自动识别，Ctrl+C 退出")
    print("=" * 50)

    _start_bgm()

    try:
        while True:
            _pause_bgm()
            audio_path = record_audio()
            if not audio_path:
                _resume_bgm()
                print("   未检测到语音，请重试")
                continue

            print("   识别中...")
            user_text = speech_to_text(audio_path)
            _resume_bgm()
            if not user_text:
                print("   未识别到内容，请重试")
                continue
            print(f"   你: {user_text}")

            print("   思考中...")
            reply = chat_with_llm(user_text)
            print(f"   AI ({_args.idol}): {reply}")

            print("   合成语音...")
            audio = text_to_speech(reply)
            if audio:
                play_audio(audio)
            else:
                print("   (语音合成失败，仅显示文字)")

    except KeyboardInterrupt:
        print("\n\n再见！")
    finally:
        _stop_bgm()
        pa.terminate()


if __name__ == "__main__":
    main()
