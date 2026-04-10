# idol-skill 数据源策略

> 偶像 AI 人格还原的信息搜集方案。`[+0409 Opus+Codex 交叉验证]`

## 核心原则

1. **搜原始长文本，不搜语录页** — 采访原文 > 粉丝逐字稿 > 语录聚合站（兜底）
2. **两阶段检索** — 先宽召回长文本，再从文本内部统计发现口癖
3. **证据卡验证** — 每个特征附证据+来源+置信度+一手/二手标注
4. **按证据生态分流** — 不按地域标签，按平台可用性分

## 平台接入优先级

### Phase 1: B站（最高 ROI）

**为什么 B站最优先**：反爬最松、采访/综艺字幕是真正的一手原话、文本质量最高。

| 工具 | 类型 | 功能 | 安装 |
|------|------|------|------|
| [bilibili-subtitle-fetch](https://github.com/Initsnow/bilibili-subtitle-fetch) | MCP Server | 视频字幕获取 | `uv tool install --python 3.13 bilibili-subtitle-fetch` |
| [bilibili-video-info-mcp](https://github.com/lesir831/bilibili-video-info-mcp) | MCP Server | 弹幕+字幕+评论 | GitHub README |
| [bilibili-mcp-server](https://github.com/wangshunnn/bilibili-mcp-server) | MCP Server | B站全功能 API | GitHub README |
| [bilibili-api-python](https://pypi.org/project/bilibili-api-python/) | Python SDK | 视频/字幕/评论/用户 | `pip install bilibili-api-python` |

**字幕 API**：`api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}` → JSON 格式字幕，大部分无需登录。

**搜索流程**：
1. 搜索 `{idol_name} 采访 专访 site:bilibili.com` → 获取 BV 号列表
2. 通过 MCP/API 批量获取字幕 JSON
3. 从字幕文本做 n-gram/句尾词统计发现口癖

**凭证**：字幕获取大部分无需登录；评论等需 SESSDATA/BILI_JCT/BUVID3（浏览器 cookie）。

### Phase 2: 微博

**价值**：明星亲自发的博文 = 一手书面语风格。

| 工具 | 类型 | 功能 |
|------|------|------|
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | Python 爬虫（27.7k⭐） | 微博+B站+小红书+抖音统一爬虫 |
| [weibo-crawler](https://github.com/dataabc/weibo-crawler) | Python 爬虫（4.1k⭐） | 按用户 ID 抓博文+评论 |
| [Weibo MCP Server](https://www.pulsemcp.com/servers/payne-weibo) | MCP Server | 需验证成熟度 |

**风险**：需 cookie 登录；高频抓取触发验证码。
**缓解**：单次抓取量不大（只抓目标明星），控制频率即可。

### Phase 3: 小红书/抖音（延后）

**延后原因**：
- 小红书反爬最激进（xs/xt 签名频繁变更），维护成本高
- 抖音视频描述太短（几十字），信息密度低
- 两个平台的明星内容多为营销号转述，不是一手原话

**备选统一方案**：MediaCrawler 覆盖四个平台，如果微博已接入可顺带验证。

## 搜索词策略（已更新到 intake.md）

### 发现阶段（宽召回，不带引号）
```
"{name} 采访 原文 专访 全文"
"{name} 逐字稿 OR 字幕 OR 文字版"
"{name} 综艺 直播 说了什么 原话"
```

### 验证阶段（窄精确，带引号/site 限定）
```
"{name}" "{候选口癖}" — 验证是否多源出现
"{name}" site:bilibili.com 采访 — 定向找 B站视频
```

### 搜索词扩展
- 包含别名/昵称/团体名（如"坤坤""KUN""NINE PERCENT"）
- 韩流加 `翻译 中字`，日系加 `字幕组`

## 证据质量分级

| 等级 | 来源 | 置信度 | 示例 |
|------|------|--------|------|
| 🟢 一手 | 采访原文/字幕/官方直播/本人社媒 | 高 | 腾讯专访全文、B站字幕 JSON |
| 🟡 二手 | 粉丝逐字稿/整理帖/百科 | 中 | 知乎语录整理、贴吧汇总 |
| 🔴 三手 | 语录聚合站/鸡汤号 | 低 | 句子控、文字站 |

## 与 Opus/Codex 交叉验证的核心共识

1. 当前搜"语录"搜到的是鸡汤化二手加工品，不是原始说话方式
2. MBTI 噪声极大，只能做弱特征
3. 口癖应该从长文本中统计发现，不是从搜索引擎搜"口癖"两个字
4. 需要验证层（证据卡）防止粉丝二次加工被当成本人表达
5. 按证据生态（有无字幕/wiki/粉丝站）分流，不按地域标签

## CLI Fetcher 工具（已实现）`[+0409]`

所有 fetcher 在 `tools/` 下，统一 CLI 接口：

| 平台 | 脚本 | 认证方式 | 核心命令 |
|------|------|---------|---------|
| B站 | `bilibili_fetcher.py` | 扫码登录（`bilibili_auth.py login`） | `search`/`subtitle`/`info` |
| 微博 | `weibo_fetcher.py` | MediaCrawler QR 登录 | `search`/`user` |
| 小红书 | `xiaohongshu_fetcher.py` | 浏览器 Cookie | `search`/`note`/`user`/`login` |
| 抖音 | `douyin_fetcher.py` | 无需登录(video) / MediaCrawler(search) | `video`/`search` |

认证凭证统一存放 `~/.config/idol-skill/`，权限 600。

## TODO

- [x] B站扫码登录 + 字幕获取（已验证：HOPICO 采访 635 行一手原话）`[+0409]`
- [x] 小红书 Playwright 登录可用，但搜索被反爬拦截（SDK 需签名服务）`[+0409]`
- [x] 微博 MediaCrawler 登录选择器失效，需更新 `[+0409]`
- [x] 抖音 API 被反爬，需签名/cookie `[+0409]`
- **结论**：Phase 1 聚焦 B站，其他平台反爬成本 > 收益，延后 `[+0409]`
- [ ] 用 B站字幕跑完整的蔡徐坤人格重建，验证质量提升
- [ ] intake.md 集成 bilibili_fetcher.py 到搜索流程
