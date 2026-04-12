# groupchat — 多偶像真互聊子模块

让**你用 `/create-idol` 创建的任意偶像**同时在线互相聊天，自己开麦语音参与，三方**真互聊**。

**关键区别：真互聊 ≠ 剧本式**
- ❌ 剧本式（一次 Claude 调用生成多行 `[A]...[B]...` 配音剧）
- ✅ 真互聊（每个偶像每一句都是独立 Claude 推理，LLM 上下文隔离，谁接话谁 PASS 各自判断，用户随时开麦或文字插话）

## 架构

```
         ┌─ /tmp/idol_groupchat.txt ─┐  共享对话流
         │  [idol_a] ...             │  每行 [slug] 内容
         │  [idol_b] ...             │
         │  [user] ...               │
         └──────────┬────────────────┘
                    │读写
    ┌───────────────┼───────────────┬───────────────┐
    │               │               │               │
chat_worker     chat_worker     user_mic       主 Claude 窗口
(slug=idol_a)  (slug=idol_b)   (麦克风+STT)    (Monitor 看戏 + 转字)
```

每个组件：
- **`chat_bridge.py`** — 共享文件读写 + `speak` (火山引擎 TTS + afplay + flock 互斥) + `listen` (阻塞等非自己的下一条, 支持跳跃模式) + `reset/tail`. 不知道任何特定 idol, 任意 slug 都接受
- **`chat_worker.py`** — 通用偶像 worker, `--slug <x>` 启动时从 `$IDOL_DATA_DIR/<x>/persona.md` 动态加载人设. 所有 idol 共用同一份"语音对话硬规则"(禁视觉符号/PASS/STT 谐音宽容), 特定口吻完全走 persona
- **`user_mic.py`** — 持续录麦克风 → `faster-whisper` 中文 STT → 垃圾过滤 → `speak user` 入桥. 检测 flock 在 worker 播放时暂停录音防回声

## 六大坑 + 修法

1. **listen 死锁** — `<CHAT_FILE>.pos.<slug>` 文件持久化"已读到第几条"，启动时有未读立即返回
2. **声音叠播** — `fcntl.flock(LOCK_EX)` 串行互斥，后到的 worker 阻塞等前一个播完
3. **麦克风录到 worker 回声** — user_mic 非阻塞试 flock，worker 持有锁时暂停录音；afplay 完**多 sleep 0.4s 清场**才释放锁
4. **PASS 留白机制** — worker prompt 允许输出 `PASS` 不接话，不发言自然给用户让位
5. **STT 中文人名识别歪** — worker 通用规则内置"谐音宽容"（让 LLM 按音+上下文判断，不靠字面匹配）
6. **worker 追老消息** — `listen jump` 跳跃模式，直接取最新一条丢弃积压

## 前置要求

- **Python 3.9+** 脚本用 `sys.executable` 跨机通用
- **macOS**（`afplay` 系统自带；Linux 改 `aplay` 搜 `afplay` 替换即可）
- **Claude Code CLI** — worker 靠它调 `claude -p --model haiku`，走 Claude Code 订阅鉴权**不额外收费**
- **火山引擎 TTS 账号** + 每个偶像一个克隆 `speaker_id`
- **Python 包**：见 `requirements.txt`

## 安装

```bash
cd ~/.claude/skills/idol-skill/groupchat
pip install -r requirements.txt

# 复制 env 模板, 填上你的火山引擎凭证 + 每个偶像的 speaker_id
cp .env.example .env
$EDITOR .env
```

## 用法：让你自己的偶像互相聊天

### 1. 先 `/create-idol` 创建好你的偶像

假设你创建了两个偶像 slug 为 `zhangsan` 和 `lisi`（目录 `~/.config/idol-skill/idols/zhangsan/persona.md` 存在）。

### 2. 每个偶像配一个克隆声音（可选，没配就没声音只有文字）

在 `.env` 里加：
```env
VOLC_ZHANGSAN_SPEAKER_ID=你克隆的 speaker_id
VOLC_LISI_SPEAKER_ID=另一个 speaker_id
```

规则：**`VOLC_<SLUG_UPPER>_SPEAKER_ID`**，slug 大写。没有克隆声音？姊妹技能 [voice-clone](../../voice-clone.md) 教你从公开音视频复刻。

### 3. 启动群聊（三个后台 + 主窗口 tail）

```bash
cd ~/.claude/skills/idol-skill/groupchat

# 清桥
python3 chat_bridge.py reset

# 为每个参加群聊的偶像起一个 worker (后台)
python3 chat_worker.py --slug zhangsan --max-rounds 30 &
python3 chat_worker.py --slug lisi --max-rounds 30 &

# 起 user_mic 让你能开麦说话
python3 user_mic.py --threshold 120 --silence-sec 1.5 &

# 主 Claude Code 窗口盯对话流 (可选)
tail -F /tmp/idol_groupchat.txt | grep --line-buffered "^\["
```

启动后**直接对着麦克风说话**：
- 说"张三你最近怎么样" → zhangsan 的 worker 点名必须接话
- 说"你们俩" → 两个 worker 都可能接（各自独立判断）
- 不点名 → 谁想接谁接，有时 PASS 留白给你说话

### 4. 加入第三个偶像？第四个？

一样的套路：
```bash
python3 chat_worker.py --slug wangwu --max-rounds 30 &
```

桥支持任意数量参与者（性能瓶颈在 claude CLI 启动开销，每多一个 worker 多一份延迟）。

## 调试

```bash
# 看共享文件最近 20 行
python3 chat_bridge.py tail

# 全部停
pkill -f chat_worker.py; pkill -f user_mic.py

# 清空开新一轮
python3 chat_bridge.py reset
```

## 关键参数

| 参数 | 默认 | 作用 |
|---|---|---|
| `chat_worker --slug` | 必填 | 偶像 slug，对应 `$IDOL_DATA_DIR/<slug>/persona.md` |
| `chat_worker --model` | haiku | claude 模型 (haiku/sonnet/opus) |
| `chat_worker --max-rounds` | 30 | 用完自然退出 |
| `chat_worker --listen-timeout` | 600 | 等对方消息最长时间（秒） |
| `chat_worker --no-jump` | 关 | 加上这个就关跳跃模式，严格按顺序追历史（默认跳跃只回最新） |
| `user_mic --threshold` | 120 | 静音阈值 RMS，环境噪音大调高 |
| `user_mic --silence-sec` | 1.5 | 静音多久判定一句结束，别调到 0.8 会切到一半 |
| `user_mic --max-record-sec` | 60 | 单句最长录音 |

## 环境变量

| 变量 | 作用 |
|---|---|
| `GROUPCHAT_FILE` | 共享文件路径，默认 `/tmp/idol_groupchat.txt` |
| `IDOL_DATA_DIR` | 偶像数据目录，默认 `~/.config/idol-skill/idols/`（和 idol-skill 主技能一致） |
| `VOLC_APPID` / `VOLC_TOKEN` | 火山引擎凭证 |
| `VOLC_<SLUG>_SPEAKER_ID` | 某个偶像的克隆声音 ID（slug 大写），比如 `VOLC_ZHANGSAN_SPEAKER_ID` |
| `VOLC_SPEAKER_ID` | 回落默认 speaker，所有没单独配的偶像共用这个 |

## 已知限制

- **慢**：haiku 一轮 15-20s（claude CLI 启动开销 5-10s + 推理 1-3s + TTS 1-2s）。跳跃模式避免积压但响应时延固定。加速需要走 Anthropic SDK 直连 API，但那需要独立 API key 单独付费，不在 Claude Code 订阅内。
- **STT 中文人名识别差**：`faster-whisper base` 常把中文人名识别歪，worker prompt 里做了"谐音宽容"兜底。换 `large-v3` 会好但慢很多。
- **不戴耳机也行**：`flock` + 0.4s 清场让 user_mic 在 worker 播放期间暂停录音，不会自循环。但如果房间混响严重，建议戴耳机更稳。

## 与 `tools/voice_chat/` 的区别

| 维度 | `tools/voice_chat/` | `groupchat/` (本模块) |
|---|---|---|
| 参与者 | 1 用户 + 1 偶像 | 1 用户 + N 偶像 |
| 场景 | 面对面私聊 | 多人群聊 + 偶像互聊 |
| 架构 | 单进程 loop | 每个偶像一个独立子进程 |
| 触发 | `/voice-chat <slug>` | `/groupchat` + 手动起多个 worker |
