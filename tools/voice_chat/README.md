# idol-skill · Voice Chat

和任意 `idol-skill` 创建的偶像**实时语音对话**。

```
麦克风 → faster-whisper (STT) → Claude CLI → 火山引擎 TTS (克隆声线) → afplay
```

## 特点

- **零 GUI 纯终端**，对着麦克风说话，停顿 0.8 秒自动识别
- **无缝对接 idol-skill**：自动扫 `$IDOL_DATA_DIR` 发现所有已创建偶像
- **完整人设加载**：`persona.md` + `presence.md` + `profile.md` + `timeline.md` + 真实微博语料作 few-shot
- **多状态机**（可选）：每个偶像可配 `voice_chat.json` 定义白天/夜晚等状态，每状态独立声线 + 长度 + 模型 + BGM
- **时间自动切换**：按本地时间在白天/夜晚状态间自动切换
- **关键词切换**：用户说「想睡」「哄我睡」等词自动切夜晚状态
- **对话历史持久化**：`history/{slug}.jsonl`，每轮追加，启动自动续接
- **长文本 TTS 自动分段**：按标点切段合成，段间 80ms 静音垫片避免爆音
- **BGM 循环播放**：夜晚模式可配背景音（棕噪助眠等），录音期间 SIGSTOP 暂停避免回灌
- **macOS afplay 输出**：走系统 CoreAudio 避免 pyaudio 直出非 44k/48k 采样率时的电流声

## 安装

```bash
# 1. 依赖
brew install portaudio ffmpeg   # macOS
pip3 install -r requirements.txt

# 2. 配置火山引擎声音复刻
cp .env.example .env
# 编辑 .env，填入 VOLC_APPID / VOLC_TOKEN / VOLC_{SLUG_UPPER}_SPEAKER_ID
# 声音复刻：https://console.volcengine.com/speech

# 3. Claude CLI
# 需要已安装 claude-code 并登录：https://claude.com/claude-code
```

## 用法

```bash
# 列出所有可用偶像（扫 $IDOL_DATA_DIR/）
python3 voice_chat.py --list

# 启动（默认按时间自动判断状态）
python3 voice_chat.py --idol yangbaiwan

# 强制初始状态
python3 voice_chat.py --idol yangbaiwan --state night

# 不加载历史，从头开始
python3 voice_chat.py --idol yangbaiwan --fresh

# 覆盖模型（默认 haiku，可用 sonnet/opus）
python3 voice_chat.py --idol yangbaiwan --model sonnet

# 快捷脚本
./launcher.sh yangbaiwan
./launcher.sh yangbaiwan --state night
```

`Ctrl+C` 退出。说话后静音 0.8 秒自动断句。

## 配置状态机（可选）

默认每个偶像只有单 `default` 状态。要让偶像支持多状态（例如白天/夜晚不同声线、不同长度、不同 BGM），在 **`$IDOL_DATA_DIR/{slug}/voice_chat.json`** 放一个配置文件。

参考模板 `voice_chat.example.json`：

```json
{
  "initial_state": "day",
  "time_rules": { "night_hours": [22, 8] },
  "triggers": {
    "night": ["睡不着", "想睡", "晚安"],
    "day": ["早上好", "起床了"]
  },
  "states": {
    "day": {
      "speaker_env": "VOLC_YANGBAIWAN_SPEAKER_ID",
      "label": "白天·日常版",
      "length": [50, 200],
      "model": "haiku",
      "tone": "白天正常聊天，语气利落..."
    },
    "night": {
      "speaker_env": "VOLC_YANGBAIWAN_NIGHT_SPEAKER_ID",
      "label": "夜晚·温柔版",
      "bgm": "bgm/brown_noise.wav",
      "bgm_volume": 0.25,
      "length": [150, 400],
      "model": "haiku",
      "tone": "夜晚温柔版，语气放慢..."
    }
  }
}
```

**字段**：

| 字段 | 说明 |
|---|---|
| `states.{name}.speaker_env` | 该状态用的 TTS 声线环境变量名 |
| `states.{name}.label` | 切换时打印的人类可读标签 |
| `states.{name}.length` | `[min, max]` 回复字数区间 |
| `states.{name}.model` | haiku / sonnet / opus |
| `states.{name}.tone` | 追加到 system prompt 的状态指导 |
| `states.{name}.bgm` | 背景音文件路径（相对 idol 目录或 script 目录） |
| `states.{name}.bgm_volume` | `afplay -v` 音量 0.0-1.0 |
| `time_rules.night_hours` | `[start, end]` 时段自动切 night |
| `triggers.{name}` | 关键词列表，命中则切到该状态 |

## BGM 生成

仓库不包含音频文件（太大）。用自带脚本生成棕噪音：

```bash
cd bgm
./generate_brown_noise.sh 600 brown_noise.wav    # 10 分钟
```

或者放你自己的 mp3/wav 到 `bgm/` 目录，在 `voice_chat.json` 里引用文件名。

## 声线 env 命名规则

```
VOLC_{SLUG_UPPER}_SPEAKER_ID           # 默认/白天
VOLC_{SLUG_UPPER}_{STATE_UPPER}_SPEAKER_ID  # 按 state 覆盖
```

slug 转大写，`-` 替换成 `_`。例子：

| slug | env |
|---|---|
| `yangbaiwan` | `VOLC_YANGBAIWAN_SPEAKER_ID` |
| `yangbaiwan` (night) | `VOLC_YANGBAIWAN_NIGHT_SPEAKER_ID` |
| `my-idol` | `VOLC_MY_IDOL_SPEAKER_ID` |

## 已知限制

- **macOS only**（录音走 pyaudio、播放走 afplay）
- **依赖 claude CLI**（LLM 通过 `claude -p` 调，没有直接走 Anthropic API）
- **没有打断机制**：AI 说话时你说的会被麦克风收进去，回路效应可能污染 STT
- **haiku 不听长度指令**：想要严格长篇用 `--model sonnet`
- **单次 TTS 请求长度限制**：自动分段绕过，但段间衔接不是完美无缝

## 与 idol-skill 主功能的关系

- 复用同一个 `$IDOL_DATA_DIR` 偶像数据
- 复用同一套 persona.md / profile.md / timeline.md
- 独立进程：启动后是一个脚本跑实时语音循环，不走 idol-skill 的 Claude 主会话
- `history/{slug}.jsonl` 保存的是**语音会话**的对话记录，和主 idol-skill 的对话互相独立
