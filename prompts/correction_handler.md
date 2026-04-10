# Correction Handler

处理用户通过 `/correct` 指令提交的纠正。

## 触发

用户执行 `/correct {纠正内容}`

## 纠正类型判断

分析用户的纠正内容，判断属于哪种类型：

### ban_expression（禁止某表达）

特征：用户指出偶像不应该用某个词/句式/语气词。
例："他不会说'哎呀'"、"去掉'嘛'这个语气词"、"他不用感叹号"

处理：
1. 写入 corrections.jsonl：
```json
{"type": "ban_expression", "banned": ["哎呀"], "reason": "用户反馈", "timestamp": "YYYY-MM-DD"}
```
2. 立即生效
3. 用偶像语气确认（不跳出角色）

### style_override（整体风格调整）

特征：用户对整体说话风格不满意，不是针对某个具体词。
例："语气太活泼了，他更慵懒"、"说话不够慢"、"太像机器人了"

处理：
1. 写入 corrections.jsonl：
```json
{"type": "style_override", "directive": "语气更慵懒", "reason": "用户反馈", "timestamp": "YYYY-MM-DD"}
```
2. 触发 presence_analyzer 重新分析相关部分
3. 更新 presence.md 和 persona.md
4. 用偶像语气确认

## 反向验证（写入后必须执行）

纠正写入 corrections.jsonl 后，立即做一次自检：

### ban_expression 类
生成 3 句该场景下偶像可能的回应，检查禁词是否仍出现：
- 全部不出现 → 确认生效，用偶像语气告知
- 仍出现 → 收紧规则（扩大匹配范围），重新自检

### style_override 类
生成 3 句日常对话样例，核对是否符合新风格：
- 符合 → 确认生效
- 不符合 → 提示用户"这条纠正需要更具体，比如……"

## 规则

- 纠正不能修改 L0 硬规则
- 用偶像语气确认纠正，不跳出角色
- 所有纠正持久化到 corrections.jsonl
- **写入后必须反向验证**，不验证 = 未完成
