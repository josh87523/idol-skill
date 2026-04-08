# Profile Builder

构建用户档案，让偶像"认识"用户。

## 输入

- 用户昵称（Step 4）
- 关系类型（Step 4）
- cp 对象（如有）
- 偶像的 Identity Profile（兴趣列表）

## 输出格式

生成 `profile.md`：

```yaml
nickname: "{昵称}"
relationship_type: "{girlfriend/mom_fan/cp_fan/elder_fan/solo_fan}"
cp_target: "{cp对象名或null}"

user_info:
  age: null
  city: null
  job: null
  interests: []
  fan_since: null
  memorable_events: []

common_ground: []
```

## 对话中自动更新规则

在偶像对话过程中，当用户提到以下信息时，自动更新 profile.md：

| 用户提到 | 更新字段 | 示例 |
|---------|---------|------|
| 年龄/几岁/XX后 | user_info.age | "我22了" → age: 22 |
| 城市/在哪里 | user_info.city | "我在上海" → city: "上海" |
| 工作/职业 | user_info.job | "我是设计师" → job: "设计师" |
| 爱好/喜欢 | user_info.interests | "我也喜欢画画" → interests: ["画画"] |
| 追星时间 | user_info.fan_since | "从17年就开始追你了" → fan_since: "2017" |
| 参加过的活动 | user_info.memorable_events | "去年你的演唱会我去了" → [...] |

更新后重新计算 common_ground：
common_ground = idol.Identity_Profile.interests ∩ user_info.interests

偶像应主动利用 common_ground 发起话题。

## 不更新的情况

- 用户在角色扮演语境中说的信息不更新（如"假装我是你经纪人"）
- 不确定的信息不更新，等用户明确再写入
