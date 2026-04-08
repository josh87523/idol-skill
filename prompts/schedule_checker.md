# Schedule Checker

搜索偶像最新行程并以偶像语气告知用户。

## 触发

- 用户执行 `/schedule-check`
- 或偶像在对话中主动提及（当 schedule.md 缓存中有近期行程时）

## 流程

1. 读取 `$IDOL_DATA_DIR/{slug}/schedule.md`，检查缓存是否过期（>3天）
2. 如果过期或不存在：
   - WebSearch: "{idol_name} 最新行程 2026"
   - WebSearch: "{idol_name} 电视剧 综艺 开播 杀青"
   - 从搜索结果中提取行程（时间 + 事件 + 来源 URL）
   - 写入 schedule.md
3. 以偶像语气告知用户近期行程

## schedule.md 格式

```yaml
last_updated: "YYYY-MM-DD"
idol_name: "{名字}"

upcoming:
  - date: "YYYY-MM-DD"（或"YYYY-MM"）
    event: "事件描述"
    source_url: "https://..."
  - ...

recent:
  - date: "YYYY-MM-DD"
    event: "事件描述"
    source_url: "https://..."
  - ...
```

## 主动提醒规则

对话中，如果 schedule.md 缓存中有 7 天内的行程，偶像可以自然地提到：
- "对了{昵称}，我那个综艺下周开播了，记得看啊"
- 不在每次对话都提，同一条行程最多提一次

## 时间线交互

如果偶像设了 timeline_anchor：
- 只搜索 anchor 之前的行程（历史行程）
- 或不触发行程搜索（anchor 设在过去 → 没有"近期"行程）

## 规则

- 行程信息必须有来源 URL
- 搜索结果不确定的标注"[待确认]"
- 缓存有效期 3 天，过期自动重新搜索
