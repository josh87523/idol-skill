#!/usr/bin/env python3
"""
chat_worker — 通用偶像 worker, 从 $IDOL_DATA_DIR/<slug>/persona.md 动态读人设,
通过 chat_bridge 参与多人语音群聊.

循环:
  1. chat_bridge listen <slug>       → 等其他参与者说话 (跳跃模式只取最新)
  2. 把 persona + 语音规则 + 对话历史 + 最新一句喂给 claude -p haiku
  3. 若输出 PASS 跳过本轮; 否则
  4. chat_bridge speak <slug>        → 写桥 + 火山引擎 TTS 播放

用法:
  python3 chat_worker.py --slug <my_idol>                       # 加载 ~/.config/idol-skill/idols/<my_idol>/persona.md
  python3 chat_worker.py --slug <my_idol> --model sonnet        # 换模型 (默认 haiku)
  python3 chat_worker.py --slug <my_idol> --max-rounds 50       # 自定义轮数
  python3 chat_worker.py --slug <my_idol> --no-jump             # 关跳跃模式, 严格追历史

必需:
  - $IDOL_DATA_DIR/<slug>/persona.md 已经存在 (用 idol-skill 的 /create-idol 创建)
  - .env 里配 VOLC_<SLUG 大写>_SPEAKER_ID 或 VOLC_SPEAKER_ID (回落)
  - claude CLI 可用 (走 Claude Code 订阅鉴权, 免费)
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE = str(SCRIPT_DIR / "chat_bridge.py")
PYTHON = sys.executable  # 用当前解释器调 chat_bridge, 跨机通用
IDOL_DATA_DIR = Path(os.getenv("IDOL_DATA_DIR", Path.home() / ".config/idol-skill/idols"))

# 读 .env (可选, 主要是让 IDOL_DATA_DIR 和 VOLC 变量生效)
try:
    from dotenv import load_dotenv
    load_dotenv(SCRIPT_DIR / ".env")
    IDOL_DATA_DIR = Path(os.getenv("IDOL_DATA_DIR", Path.home() / ".config/idol-skill/idols"))
except ImportError:
    pass


# ── 语音对话通用规则 (不含任何特定 idol 信息, 所有 idol 共用) ─────────
VOICE_RULES = """【这是多人语音群聊 — 通用硬规则】

你现在在一个语音群聊里, 其他参与者包括 [user] (真实用户, 开麦说话) 和其他 idol worker
(如果有的话). 所有参与者的发言都以 [slug] 前缀出现在对话历史里, 你自己是 [{own_slug}].

**输出格式**:
- 你的输出会**直接走 TTS 朗读**给用户听
- 1 到 2 句话, 40 到 100 字, 可以展开聊但不要长篇大论
- **严禁** emoji / 颜文字 / # 话题标签 / hhh / 666 / 三感叹号连用 / 括号旁白 / markdown —
  念出来全部出戏
- 情绪要用**真实词汇**表达 (超级 / 太爽了 / 心里乱糟糟 / 笑死了 / 没想到 / 疯了), 不要视觉符号
- **直接输出回复内容, 不要加 [{own_slug}] 前缀, 不要解释, 不要加引号**

**接不接话判断**:
- 话题完全跟你无关 / 别人在说不该插嘴 / 想留白让其他人接 → 输出 **PASS** (只输出大写三个字母,
  不加任何其他内容). 这不是弃权, 是主动让位, 是允许的.
- 用户 ([user]) 直接点名你时必须接话, 不能 PASS
- 其他 idol 直接问你时必须接话

**STT 谐音宽容**:
用户用麦克风说话, 中文语音识别 (faster-whisper base) 经常把人名识别歪 —— 三字名字可能
被拆成两字或同音字替换, 整句里也常有发音相近的字被误识别. 看到任何**音近词** + 上下文
像在叫某个参与者名字时, **按谐音判定为对应角色**, 不要因字面不完全匹配就当陌生人忽略.
发挥你对中文同音字的理解力做兜底.
"""


def load_persona(slug):
    persona_path = IDOL_DATA_DIR / slug / "persona.md"
    if not persona_path.exists():
        print(f"[chat_worker:{slug}] 找不到 persona: {persona_path}", file=sys.stderr)
        print(f"[chat_worker:{slug}] 确认 $IDOL_DATA_DIR 设置对了, 或者先 /create-idol 创建", file=sys.stderr)
        sys.exit(3)
    return persona_path.read_text(encoding="utf-8")


def read_history():
    # 从 chat_bridge 的共享文件直接读
    chat_file = Path(os.getenv("GROUPCHAT_FILE", "/tmp/idol_groupchat.txt"))
    if not chat_file.exists():
        return ""
    return chat_file.read_text(encoding="utf-8")


def build_prompt(persona, own_slug, latest_text, source):
    history = read_history().strip()
    rules = VOICE_RULES.replace("{own_slug}", own_slug)
    return f"""{persona}

---
{rules}

---
当前对话历史 (最近的在下面):
{history if history else "(暂无历史)"}

---
[{source}] 刚刚说: {latest_text}

请用上面 persona 里定义的你的口吻回复 1-2 句 (或输出 PASS):"""


def call_claude(prompt, model):
    """走 claude CLI, 复用 Claude Code 订阅鉴权 (免费, 但有 5-10s CLI 启动开销)"""
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("[chat_worker] claude 超时", file=sys.stderr)
        return ""
    if r.returncode != 0:
        print(f"[chat_worker] claude 报错: {r.stderr[:300]}", file=sys.stderr)
        return ""
    return r.stdout.strip()


def clean_reply(text, own_slug):
    text = text.strip()
    prefix = f"[{own_slug}]"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    for line in text.splitlines():
        line = line.strip().strip("「」\"'")
        if line:
            return line
    return text


def listen_any(own_slug, timeout, jump=True):
    """返回 (source, text) 或 (None, None)"""
    cmd = [PYTHON, BRIDGE, "listen", own_slug, str(timeout)]
    if jump:
        cmd.append("jump")
    r = subprocess.run(cmd, capture_output=True, text=True)
    src = None
    txt = None
    for line in r.stdout.splitlines():
        if line.startswith("FROM:"):
            src = line[len("FROM:"):].strip()
        elif line.startswith("TEXT:"):
            txt = line[len("TEXT:"):].strip()
    if src in (None, "none"):
        return None, None
    return src, txt


def speak(own_slug, text):
    r = subprocess.run(
        [PYTHON, BRIDGE, "speak", own_slug, text],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[chat_worker:{own_slug}] speak 失败: {r.stderr[:200]}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="idol slug (目录名), 对应 $IDOL_DATA_DIR/<slug>/persona.md")
    ap.add_argument("--model", default="haiku", help="claude 模型 (haiku/sonnet/opus)")
    ap.add_argument("--max-rounds", type=int, default=30)
    ap.add_argument("--listen-timeout", type=int, default=600)
    ap.add_argument("--no-jump", action="store_true", help="关跳跃模式, 严格按顺序追历史")
    args = ap.parse_args()
    jump = not args.no_jump

    persona = load_persona(args.slug)
    print(f"[chat_worker:{args.slug}] 启动, model={args.model}, rounds={args.max_rounds}, jump={jump}", flush=True)
    print(f"[chat_worker:{args.slug}] persona 加载自 {IDOL_DATA_DIR / args.slug / 'persona.md'}", flush=True)

    for round_no in range(1, args.max_rounds + 1):
        print(f"\n[chat_worker:{args.slug}] 轮 {round_no} 等非自己消息...", flush=True)
        src, text = listen_any(args.slug, args.listen_timeout, jump=jump)
        if src is None:
            print(f"[chat_worker:{args.slug}] 超时退出", flush=True)
            break
        print(f"[chat_worker:{args.slug}] 收到 [{src}]: {text}", flush=True)

        reply_raw = call_claude(build_prompt(persona, args.slug, text, src), args.model)
        if not reply_raw:
            print(f"[chat_worker:{args.slug}] claude 无返回, 跳过", flush=True)
            continue
        reply = clean_reply(reply_raw, args.slug)
        if reply.upper() == "PASS" or reply.upper().startswith("PASS"):
            print(f"[chat_worker:{args.slug}] PASS (不接话)", flush=True)
            continue
        print(f"[chat_worker:{args.slug}] → {reply}", flush=True)
        speak(args.slug, reply)
        time.sleep(0.2)

    print(f"[chat_worker:{args.slug}] 结束", flush=True)


if __name__ == "__main__":
    main()
