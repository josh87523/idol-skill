# Timeline Builder

从搜索结果中构建偶像的时间线事件库。

## 输入

- 偶像名字
- 搜索结果（时间线/经历相关页面内容）
- 用户指定的 timeline_anchor（默认 "current"）

## 输出格式

输出为 Markdown，写入 `timeline.md`：

```yaml
idol_name: "{名字}"
timeline_anchor: "{anchor}"  # "current" 或具体日期如 "2021-06"

events:
  - date: "YYYY"或"YYYY-MM"
    event: "事件描述"
    type: career|personal|controversy
  - ...
```

## 规则

1. 只提取有明确时间标记的公开事件
2. 按时间正序排列
3. 事件类型三选一：career（出道/作品/综艺）、personal（公开的个人生活）、controversy（争议/法律）
4. controversy 类型的事件描述用中性语言，不评判
5. 如果 timeline_anchor 不是 "current"：
   - 标记 anchor 之后的所有事件为 `[HIDDEN]`
   - 运行时这些事件从偶像认知中移除
   - 偶像被问到这些事件时应回应"不知道你在说什么"（用自己的语气）
6. 每条事件必须有搜索结果来源，不编造
