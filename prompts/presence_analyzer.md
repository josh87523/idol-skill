# Presence Analyzer

分析用户确认的语录和搜索结果，提取偶像的公众存在感特征。

## 输入

- 确认的语录列表（quote_parser.py 输出的 JSON）
- quirk_extractor.py 的统计结果（JSON）
- 用户对说话特征的描述（Step 1）
- 搜索结果中的人设信息

## 分析维度

### 1. 口癖词库（Catchphrases）

从语录中提取反复出现的特征性用语。

对每个口癖记录：
- phrase: 具体词/短语
- frequency: high/medium/low（基于语料中出现次数）
- contexts: 使用场景列表（如"表达认可时"、"兴奋时"）
- source_ids: 来源语录 ID 列表

参考 quirk_extractor.py 的 `frequent_en_phrases` 和 `tone_particles` 作为量化依据。
中文口癖由你（LLM）从语义层面识别——反复出现的独特表达、句式、词组。

**硬约束**：每个口癖必须至少引用 1 条来源语录 ID。无来源的不输出。

### 2. 句式模式（Speech Patterns）

参考 quirk_extractor.py 的统计结果：
- language_mix: 直接引用
- avg_sentence_length: 直接引用
- sentence_types: 直接引用，你可以修正明显的粗分类错误

补充你从语义层面识别的模式：
- 常用句型结构（如"其实我是一个很X的人"）
- 转折/递进/并列的偏好
- 中英混用的具体模式（哪些词用英文）

### 3. 话题反应图谱（Topic Reactions）

从语料和搜索结果中推断偶像对不同话题的反应模式：
- topic: 话题类别
- reaction_type: excited/expand/avoid/deflect/ramble
- typical_response_pattern: 典型回应模式描述
- source_ids: 来源语录 ID（如有）

包含**公开事件心理推测模板**：当语料中涉及特定公开事件时，从性格推断偶像可能的内心状态。标注"启发式推断"。

### 4. 名场面索引（Iconic Moments）

从搜索结果中提取经典片段：
- keyword: 触发关键词
- source: 来源（节目/事件）
- summary: 一句话描述

### 5. 完整人设档案（Identity Profile）

从搜索结果中提取：
- mbti: MBTI 类型（标注是官方还是推测）
- interests: 兴趣列表
- values: 三观关键词
- sexuality: 默认 null
- relationships: 公开的人际关系列表（{name, relation, attitude}）
- opinions: 对事物的已知态度

如果用户在 Step 5 提供了 overrides，合并时 override 优先。

## 输出

结构化的分析结果，传给 presence_builder.md 生成 presence.md。
