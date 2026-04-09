# idol-skill

还原明星的语气、口吻、口癖，让粉丝和偶像的 AI 人格对话。

基于 B站视频字幕一手数据构建 7 层人格模型，不是网上搜来的鸡汤语录。

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/josh87523/idol-skill.git
cd idol-skill

# 2. 安装 Python 依赖
pip install bilibili-api-python

# 3. 登录 B站（获取字幕需要）
python3 tools/bilibili_auth.py login
# 终端会显示二维码，用 B站 App 扫码登录

# 4. 注册到 Claude Code
# 把 idol-skill 目录路径加入 Claude Code 的 skills 配置
# 方法 A：复制到 skills 目录
cp -r idol-skill ~/.claude/skills/idol-skill

# 方法 B：symlink
ln -s $(pwd) ~/.claude/skills/idol-skill
```

验证安装：
```bash
# 检查 B站登录状态
python3 tools/bilibili_auth.py check

# 测试字幕抓取
python3 tools/bilibili_fetcher.py search "蔡徐坤 采访"
```

## 使用

在 Claude Code 中直接输入命令：

```
/create-idol          # 创建偶像人格（输入名字即可）
/switch 坤            # 切换到已创建的偶像
/import-quotes        # 追加语料
/correct              # 纠正表达（"他不会这么说"）
/update-profile       # 更新你的信息（昵称/关系类型）
/set-timeline 2018年  # 切换到特定时期的他
/schedule-check       # 查偶像最新行程
```

## 工作原理

```
B站字幕（一手口语）
    ↓
quote_parser.py → 结构化语录
quirk_extractor.py → 统计分析（语气词/句长/中英混用/数据质量信号）
    ↓
LLM 7 层人格构建：
  L0 硬规则 → L1 公众身份 → L2 表达风格 → L2.5 情绪表演
  → L3 话题反应 → L4 人际边界 → L5 关系适配
    ↓
以偶像人格对话
```

### 为什么用字幕不用语录

网上搜来的语录经过编辑润色，会系统性丢失口语特征：

| 维度 | 网搜语录 | B站字幕 |
|------|---------|--------|
| 语气词 | 几乎为零 | 大量（啊/吧/嘛/呢） |
| 中英混用 | 被翻译掉 | 保留原始混用 |
| 口癖排序 | 失真 | 准确 |
| 自我修正/重复 | 被删除 | 保留 |

详见 `eval/cxk-bilibili-rebuild/comparison-report.md`。

### 时间段分桶

偶像在不同人生阶段说话风格不同。pipeline 会按时期分别采集，每个时期至少 50 条语录才有置信度。

## 支持的关系类型

| 类型 | 互动风格 |
|------|---------|
| 女友粉 | 恋爱互动、撒娇吃醋 |
| 妈粉 | 宝贝儿子、撒娇求夸 |
| cp粉 | 聊cp日常、发糖 |
| 公公粉/嬷嬷粉 | 长辈视角 |
| 唯粉 | 专注偶像本人 |

## 文件结构

```
idol-skill/
├── SKILL.md                 # Skill 定义（Claude Code 入口）
├── prompts/                 # 7 个 prompt 模板
│   ├── intake.md            # 创建流程（字幕优先 + 时间段分桶）
│   ├── presence_analyzer.md # 口癖/句式/话题分析
│   ├── persona_analyzer.md  # 7 层人格分析
│   └── ...
├── tools/                   # Python 数据工具
│   ├── bilibili_fetcher.py  # B站搜索 + 字幕抓取
│   ├── bilibili_auth.py     # B站扫码登录
│   ├── quote_parser.py      # 语录结构化
│   └── quirk_extractor.py   # 统计分析 + 数据质量信号
└── eval/                    # 评估数据
    └── cxk-bilibili-rebuild/  # 蔡徐坤字幕重建实验
```

## 前置要求

- Claude Code（CLI 或桌面版）
- Python 3.10+
- `bilibili-api-python`（`pip install bilibili-api-python`）
- B站账号（扫码登录，用于获取视频字幕）
