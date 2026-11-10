# 旅迹｜Apifox 变更方案 v0.6.0

对应设计：《设计方案-v0.6.0.md》
项目：旅游规划（9010615）· 模块：旅迹多人旅游规划 API（8838329）
基线：55 个接口（11 testing / 44 developing）、76 个模型 · 目标：75 个接口、92 个模型

## 0. 摘要

| 项 | 数量 | 说明 |
| --- | --- | --- |
| 新增目录 | 5 | 兴趣标签、主题游、冲突解决、系统触达、复盘与模板 |
| 新增接口 | 20 | 其中 5 个在 Demo 前转 testing |
| 修改接口 | 10 | 均为字段追加，不改既有字段语义，兼容旧客户端 |
| 新增模型 | 16 | 含 `RoomOverviewV06`（M3 响应升级）；另有 5 个内联对象（卡片动作、解法代价等） |
| 不改动 | 11 个 testing 接口 | 账号、房间、邀请、成员、消息保持原样 |

状态约定：新增接口创建为 `developing`；联调通过后由负责人改为 `testing`；`released` 只用于已上线的 11 个旧接口。

## 1. 新增目录

| 目录 | 接口数 | 归属模块 |
| --- | --- | --- |
| 兴趣标签 | 5 | 8838329 |
| 主题游 | 4 | 8838329 |
| 冲突解决 | 2 | 8838329 |
| 系统触达 | 5 | 8838329 |
| 复盘与模板 | 4 | 8838329 |

## 2. 新增接口清单

### 2.1 兴趣标签

| # | 方法 | 路径 | 名称 | 优先级 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/interests/tags` | 获取兴趣标签字典 | P0 | developing |
| 2 | GET | `/api/v1/me/interests` | 查看本人兴趣标签 | P0 | developing |
| 3 | PUT | `/api/v1/me/interests` | 全量设置本人兴趣标签 | P0 | developing |
| 4 | GET | `/api/v1/me/interests/stats` | 查看本人兴趣统计 | P1 | developing |
| 5 | GET | `/api/v1/rooms/{room_id}/interests` | 查看房间兴趣聚合 | P0 | developing |

要点：

- 1 为公开接口（免鉴权），支持 `?domain=` 过滤，返回 ETag，缓存 24 小时。
- 2 返回 `MemberInterestProfile`，`interests[]` 为空表示未填写，客户端不得自动补默认值。
- 3 为全量替换：`{ interests: MemberInterest[], expected_version: int }`；超过 30 个标签返回 422 `TOO_MANY_TAGS`；未知 `tag_code` 返回 422 `TAG_UNKNOWN`；`visibility=private` 的标签只存本人。
- 4 仅本人可读，返回域分布、Top 标签、与上一段行程相比的漂移。
- 5 仅房间成员可读，**排除 private 标签**，只返回聚合结果，不返回他人原始标签。

### 2.2 主题游

| # | 方法 | 路径 | 名称 | 优先级 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| 6 | GET | `/api/v1/themes` | 获取主题列表 | P0 | developing |
| 7 | GET | `/api/v1/themes/{theme_code}` | 查看主题详情 | P0 | developing |
| 8 | GET | `/api/v1/themes/{theme_code}/packs` | 查看主题行程包 | P1 | developing |
| 9 | PUT | `/api/v1/rooms/{room_id}/theme` | 设置房间主题 | P0 | developing |

要点：

- 6 公开，支持 `?domain=&city=`，返回主题卡片所需字段（名称、一句话、封面、点位数、是否 Demo 主题）。
- 7 公开，返回内容包 + 规则包 + 事实包；事实条目必须含 `source` 与 `observed_at`，无法核实的 `verified=false`。
- 8 返回 2 天/3 天骨架，含点位、时长、费用、时间窗。
- 9 房主操作，`{ theme_code, expected_room_version }`；房间已有生效版本时返回 409 `THEME_LOCKED`，提示走 `replan-jobs` 生成主题变更提案；`theme_code=null` 表示清除主题。

### 2.3 冲突解决

| # | 方法 | 路径 | 名称 | 优先级 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| 10 | GET | `/api/v1/rooms/{room_id}/conflicts/{conflict_id}/resolutions` | 查看冲突解法选项 | P0 | developing |
| 11 | POST | `/api/v1/rooms/{room_id}/conflicts/{conflict_id}/resolve` | 应用冲突解法 | P0 | developing |

要点：

- 10 返回 `options[]`：`action` 取 `relax/replace/shift/split/rotate/vote/leave/defer`，每个选项带 `cost`（时间、费用、步行）与 `required_member_ids`；`feasibility` 为 `feasible/needs_data/infeasible`。
- 11 请求 `{ option_id, expected_room_version, comment? }`：
  - `relax` 且仅涉及本人 → 立即生效，`effect=applied`，`room_version+1`；
  - 其余动作 → 生成待确认版本或提案，`effect=pending_confirmation`，返回 `version_id`/`proposal_id` 与 `pending_member_ids`；
  - 版本不符 409 `VERSION_CONFLICT`；选项不可行 422 `OPTION_INFEASIBLE`。

### 2.4 系统触达

| # | 方法 | 路径 | 名称 | 优先级 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| 12 | GET | `/api/v1/me/travel-cards` | 获取负一屏旅行卡片 | P0 | developing |
| 13 | GET | `/api/v1/rooms/{room_id}/live-state` | 获取流体云实时状态 | P0 | developing |
| 14 | POST | `/api/v1/devices/push-subscriptions` | 注册设备推送与卡片能力 | P0 | developing |
| 15 | DELETE | `/api/v1/devices/push-subscriptions/{subscription_id}` | 注销设备推送 | P1 | developing |
| 16 | POST | `/api/v1/rooms/{room_id}/notifications/{notification_id}/ack` | 确认已读通知 | P1 | developing |

要点：

- 12 返回当前用户所有未结束房间的卡片摘要（≤10 条），按出行时间排序；无生效版本的房间返回“待确认”状态卡片。
- 13 返回 `stage`（before/traveling/activity/meeting/split/ended）、标题、副标题、倒计时目标、进度、动作数组、隐私级别；只基于生效版本，不返回待确认提案。
- 14 幂等：同一 `device_id` 重复注册返回 200 与既有记录；`capabilities` 取 `fluid_cloud/card/push`。
- 16 只允许通知接收人本人操作；用于流体云/卡片上的一键“知道了”。

### 2.5 复盘与模板

| # | 方法 | 路径 | 名称 | 优先级 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| 17 | POST | `/api/v1/rooms/{room_id}/archive` | 归档房间并生成复盘 | P1 | developing |
| 18 | GET | `/api/v1/rooms/{room_id}/retrospective` | 查看旅行复盘 | P1 | developing |
| 19 | POST | `/api/v1/rooms/from-template` | 从模板创建房间 | P1 | developing |
| 20 | GET | `/api/v1/me/templates` | 查看我的模板 | P1 | developing |

要点：

- 17 房主操作，`{ expected_room_version }`；要求存在生效版本；归档后房间只读，写接口返回 409 `ROOM_ARCHIVED`；复盘同步生成（数据量小，不引入 job）。
- 18 成员可读；分享令牌不可读复盘。
- 19 复用新建房间校验；复制主题、点位、行程骨架；**标签只作为建议带入，不写入已确认条件**。
- 20 返回本人创建或被授权复用的模板，按最近使用排序。

## 3. 修改接口

| # | 接口 | 变更 | 兼容性 |
| --- | --- | --- | --- |
| M1 | `POST /api/v1/rooms` | `CreateRoom` 增 `theme_code?`、`interest_tag_codes?[]` | 兼容 |
| M2 | `GET /api/v1/rooms/{room_id}` | `Room` 增 `theme_code`、`interest_summary{common_count, conflict_count}` | 兼容 |
| M3 | `GET /api/v1/rooms/{room_id}/overview` | 响应升级为 `RoomOverviewV06`（新增 theme、interests、conflict_summary、live、next_meeting） | 兼容（新增字段） |
| M4 | `GET /api/v1/rooms/{room_id}/conflicts` | `Conflict` 增 `severity`、`key_member_ids`、`resolution_count` | 兼容 |
| M5 | `POST /api/v1/rooms/{room_id}/conflicts/refresh` | 请求增 `include_theme_rules?`、`include_interest_clash?`，默认 true | 兼容 |
| M6 | `POST /api/v1/rooms/{room_id}/plan-jobs` | `InitialPlanInput` 增 `theme_code?`、`interest_weight?`(0–1)、`must_tag_codes?[]`、`avoid_tag_codes?[]` | 兼容 |
| M7 | `GET /api/v1/rooms/{room_id}/trip-versions/current` | `PlanVersionV05` 增 `theme_code?`、`card_summary{title, subtitle, at}` | 兼容 |
| M8 | `GET /api/v1/rooms/{room_id}/next-step` | `NextStep` 增 `live`（LiveState 精简）、`theme`、`deep_link` | 兼容 |
| M9 | `GET /api/v1/rooms/{room_id}/notifications` | `PlanNotification` 增 `channel`、`acked_at`、`deep_link`；`kind` 增 `confirmation_needed`、`meeting_soon`、`activity_starting` | 兼容（枚举扩展） |
| M10 | `GET /api/v1/shared-plans/{share_token}` | `SharedPlan` 增 `theme{code,name,badge}`、`create_room_hint{destination,theme_code,days}` | 兼容；仍不含标签、预算、成员姓名 |

注意：M3 建议新建 `RoomOverviewV06` 而不是改动 `RoomOverviewV05`，避免前端在迁移期同时踩两个结构；旧模型保留一个迭代后删除。

## 4. 新增数据模型

### 4.1 兴趣标签

**InterestTag**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| code | string | 是 | 稳定标识，如 `red_history` |
| name | string | 是 | 中文名 |
| domain | enum | 是 | nature/culture/food/play/shopping/nightlife/red/outdoor/photo/show/family |
| parent_code | string? | 否 | 二级标签指向父级 |
| icon | string? | 否 | 图标标识 |
| sort | int | 是 | 展示顺序 |

**MemberInterest**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| tag_code | string | 是 | 引用 InterestTag.code |
| strength | int | 是 | 1–5 |
| role | enum | 是 | must/want/avoid |
| visibility | enum | 是 | public/room/private |
| source | enum | 是 | self/ai/history |

**MemberInterestProfile**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| member_id | uuid | 是 | |
| interests | MemberInterest[] | 是 | 最多 30 条 |
| version | int | 是 | 乐观锁 |
| updated_at | datetime | 是 | |

**InterestStats**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| total_tags | int | 是 | |
| by_domain | {domain,count,share}[] | 是 | |
| top_tags | {tag_code,name,count}[] | 是 | |
| drift | {tag_code,delta}[] | 是 | 与上一段行程比较 |

**RoomInterestOverview**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| room_id | uuid | 是 | |
| member_count | int | 是 | |
| filled_member_count | int | 是 | 已填标签人数 |
| common_tags | InterestTag[] | 是 | 共同兴趣 |
| clash_tags | {tag_code,name,must_member_ids,avoid_member_ids}[] | 是 | 雷区 |
| coverage | number | 是 | 0–1，已填占比 |
| private_excluded | int | 是 | 被排除的私密标签数 |

### 4.2 主题游

**Theme**：`code`、`name`、`summary`、`cover_url`、`domains[]`、`city_scope`、`fact_count`、`pack_count`、`is_demo`、`status`、`updated_at`。

**ThemeRule**：`code`、`description`、`severity`(error/warning/info)、`applies_to`(activity/transport/meeting)。

**ThemeFact**：`id`、`category`(opening/ticket/reservation/docent/etiquette/transport)、`title`、`place_name`、`place_id?`、`value`、`source`、`observed_at`、`verified`、`stale`。

**ThemePack**：`id`、`theme_code`、`name`、`days`、`city`、`items[]`（place_name、place_id?、duration_minutes、estimated_cost_cny、window_start?、window_end?）、`suitable_group`、`notes`。

### 4.3 冲突与解法

**ConflictResolution**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| id | uuid | 是 | |
| conflict_id | uuid | 是 | |
| action | enum | 是 | relax/replace/shift/split/rotate/vote/leave/defer |
| title | string | 是 | 一句话解法 |
| description | string | 是 | 具体怎么做 |
| affected_member_ids | uuid[] | 是 | 受影响成员 |
| required_member_ids | uuid[] | 是 | 需确认成员 |
| cost | {time_delta_minutes?,cost_delta_cny?,walking_delta_m?} | 是 | 代价 |
| feasibility | enum | 是 | feasible/needs_data/infeasible |
| rank | int | 是 | 推荐排序 |

### 4.4 系统触达

**TravelCard**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| room_id | uuid | 是 | |
| room_name | string | 是 | |
| destination | string | 是 | |
| theme_code | string? | 否 | |
| days_to_start | int? | 否 | 已开始为 null |
| start_date / end_date | date | 是 | |
| pending_confirmations | int | 是 | 待我确认的数量 |
| next_meeting | {title,place_name,at}? | 否 | |
| current_version_id | uuid? | 否 | 未发布为 null |
| deep_link | uri | 是 | 卡片点击跳转 |
| updated_at | datetime | 是 | 供客户端缓存判断 |

**LiveState**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| room_id / version_id | uuid | 是 | |
| stage | enum | 是 | before/traveling/activity/meeting/split/ended |
| title / subtitle | string | 是 | 一行以内，供锁屏展示 |
| countdown_to | datetime? | 否 | 倒计时目标 |
| progress | number? | 否 | 0–1，仅进行中使用 |
| actions | {action,label,deep_link}[] | 是 | action 取 open/confirm/navigate/ack |
| privacy | {hide_members,hide_budget} | 是 | 默认 true/true |
| updated_at / expires_at | datetime | 是 | |

**PushSubscription**：`id`、`device_id`、`platform`(coloros/android/ios/web)、`capabilities[]`、`app_version`、`push_token`（加密存储，响应中脱敏）、`created_at`、`last_seen_at`。

### 4.5 复盘与模板

**Retrospective**：`room_id`、`version_id`、`planned_vs_actual{on_time_rate,changed_activities,skipped_activities}`、`cost{estimated_cny,actual_cny,per_person_cny}`、`conflicts_resolved`、`concessions[{member_id,count}]`、`highlights[]`、`generated_at`。

**RoomTemplate**：`id`、`name`、`source_room_id`、`destination`、`theme_code`、`days`、`member_count`、`interest_tag_codes[]`、`items[]`、`created_at`、`last_used_at`。

## 5. 关键示例

`PUT /api/v1/me/interests`

```json
{
  "expected_version": 3,
  "interests": [
    {"tag_code": "red_history", "strength": 5, "role": "must", "visibility": "public", "source": "self"},
    {"tag_code": "hiking", "strength": 2, "role": "avoid", "visibility": "room", "source": "self"}
  ]
}
```

`GET /api/v1/rooms/{room_id}/conflicts/{conflict_id}/resolutions`（节选）

```json
{
  "conflict_id": "c1",
  "room_version": 12,
  "options": [
    {
      "id": "r1",
      "action": "split",
      "title": "上午分头：博物馆组 / 老街组",
      "affected_member_ids": ["m1", "m2", "m3"],
      "required_member_ids": ["m1", "m2", "m3"],
      "cost": {"time_delta_minutes": 0, "cost_delta_cny": 40, "walking_delta_m": 600},
      "feasibility": "feasible",
      "rank": 1
    }
  ]
}
```

`GET /api/v1/rooms/{room_id}/live-state`

```json
{
  "room_id": "r1",
  "version_id": "v7",
  "stage": "meeting",
  "title": "14:30 在纪念馆北门集合",
  "subtitle": "A 组已到，B 组还有 12 分钟",
  "countdown_to": "2027-01-15T06:30:00Z",
  "progress": 0.6,
  "actions": [{"action": "navigate", "label": "导航", "deep_link": "traveltrace://room/r1/nav"}],
  "privacy": {"hide_members": true, "hide_budget": true},
  "updated_at": "2027-01-15T06:18:00Z",
  "expires_at": "2027-01-15T07:00:00Z"
}
```

## 6. 约定与错误码

- 鉴权：`bearerAuth`（JWT）；`/interests/tags`、`/themes/*` 公开；`/shared-plans/{token}` 用分享令牌。
- 时间：UTC RFC3339；日期用 `date`。
- 并发：所有写接口带 `expected_room_version` 或 `expected_version`；冲突返回 409。
- 分页：卡片、模板、主题列表均 ≤ 50 条，直接数组，不翻页。
- 错误体沿用 `Error{code,message,request_id,details}`。

| HTTP | code | 场景 |
| --- | --- | --- |
| 409 | `VERSION_CONFLICT` | 版本号不匹配 |
| 409 | `THEME_LOCKED` | 已有生效版本时切换主题 |
| 409 | `ROOM_ARCHIVED` | 房间已归档仍写 |
| 422 | `TAG_UNKNOWN` | 标签不存在 |
| 422 | `TOO_MANY_TAGS` | 超过 30 个标签 |
| 422 | `OPTION_INFEASIBLE` | 解法不可行 |
| 404 | `THEME_NOT_FOUND` | 主题不存在 |
| 403 | `NOT_MEMBER` | 非房间成员访问聚合 |

## 7. 前端接入顺序（Flutter）

| 页面 | 接口 | 依赖 |
| --- | --- | --- |
| 兴趣选择页 | 1、2、3 | 无 |
| 房间首页 | M3、5 | 标签聚合 |
| 主题选择页 | 6、7、9 | 房间已创建 |
| 冲突页 | M4、10、11 | 已有冲突数据 |
| 行程页 | M6、M7、8 | 主题与解法 |
| 下一步/锁屏 | M8、13 | 生效版本 |
| 负一屏卡片 | 12、14 | 设备注册 |
| 复盘页 | 17、18、19、20 | 行程结束 |

## 8. 实施顺序

1. **阶段一（11 月）**：目录与模型先建（1–5、M1/M2/M3），标签链路可联调。
2. **阶段二（12 月上旬）**：主题（6–9、M6）+ 冲突解法（10、11、M4/M5）。
3. **阶段三（12 月中下旬）**：触达（12–16、M8/M9）+ 真机联调；演示前把 1、3、6、10、13 转 `testing`。
4. **阶段四（1 月）**：复盘与模板（17–20）、分享 CTA（M10），端到端演练。

## 9. 在 Apifox 中的落地记录

已于 2026-11-10 按本方案写入项目 9010615 的 `main` 分支（未走 AI 分支）。每个 payload 写入前都用 `apifox cli-schema validate` 校验过结构，写入后逐条回读核对。

| 项 | 结果 |
| --- | --- |
| 新增目录 | 5 个（见 9.1） |
| 新增接口 | 20 个，均为 `developing`，tags 与所在目录一致 |
| 新增模型 | 16 个（原计划 15 + `RoomOverviewV06`） |
| 修改模型 | 9 个：CreateRoom、Room、Conflict、ConflictRefresh、InitialPlanInput、PlanVersionV05、NextStep、PlanNotification、SharedPlan |
| 修改接口 | 1 个：`GET /api/v1/rooms/{room_id}/overview` 的 200 响应由 `RoomOverviewV05` 改为 `RoomOverviewV06` |
| 当前总量 | **75 个接口**（11 testing / 64 developing）、**92 个模型** |

### 9.1 新增目录

| 目录 | folderId | 接口数 |
| --- | --- | --- |
| 兴趣标签 | 99451981 | 5 |
| 主题游 | 99451982 | 4 |
| 冲突解决 | 99451983 | 2 |
| 系统触达 | 99451984 | 5 |
| 复盘与模板 | 99451985 | 4 |

### 9.2 新增接口 ID

| # | 方法 | 路径 | endpointId |
| --- | --- | --- | --- |
| 1 | GET | `/api/v1/interests/tags` | 535209063 |
| 2 | GET | `/api/v1/me/interests` | 535209064 |
| 3 | PUT | `/api/v1/me/interests` | 535209065 |
| 4 | GET | `/api/v1/me/interests/stats` | 535209067 |
| 5 | GET | `/api/v1/rooms/{room_id}/interests` | 535209068 |
| 6 | GET | `/api/v1/themes` | 535209070 |
| 7 | GET | `/api/v1/themes/{theme_code}` | 535209071 |
| 8 | GET | `/api/v1/themes/{theme_code}/packs` | 535209073 |
| 9 | PUT | `/api/v1/rooms/{room_id}/theme` | 535209078 |
| 10 | GET | `.../conflicts/{conflict_id}/resolutions` | 535209079 |
| 11 | POST | `.../conflicts/{conflict_id}/resolve` | 535209083 |
| 12 | GET | `/api/v1/me/travel-cards` | 535209084 |
| 13 | GET | `/api/v1/rooms/{room_id}/live-state` | 535209085 |
| 14 | POST | `/api/v1/devices/push-subscriptions` | 535209087 |
| 15 | DELETE | `/api/v1/devices/push-subscriptions/{subscription_id}` | 535209088 |
| 16 | POST | `.../notifications/{notification_id}/ack` | 535209090 |
| 17 | POST | `/api/v1/rooms/{room_id}/archive` | 535209092 |
| 18 | GET | `/api/v1/rooms/{room_id}/retrospective` | 535209093 |
| 19 | POST | `/api/v1/rooms/from-template` | 535209095 |
| 20 | GET | `/api/v1/me/templates` | 535209097 |

### 9.3 新增模型 ID

| 模型 | schemaId | 模型 | schemaId |
| --- | --- | --- | --- |
| InterestTag | 327974696 | TravelCard | 327974706 |
| MemberInterest | 327974697 | LiveState | 327974708 |
| MemberInterestProfile | 327974698 | PushSubscription | 327974709 |
| InterestStats | 327974699 | Retrospective | 327974710 |
| RoomInterestOverview | 327974700 | RoomTemplate | 327974718 |
| Theme | 327974701 | RoomOverviewV06 | 327974719 |
| ThemeRule | 327974702 | ConflictResolution | 327974705 |
| ThemeFact | 327974703 | ThemePack | 327974704 |

### 9.4 复核结果

- `apifox endpoint list --project 9010615 --page-size 500` → 75 条，其中新增 20 条全部落在 5 个新目录内（5/4/2/5/4）。
- `apifox schema list --project 9010615` → 92 个。
- 37 个生成文件里的 `$ref` 全部能解析到现存模型，无悬空引用。
- `GET /api/v1/rooms/{room_id}/overview` 回读确认：200 响应 `$ref = #/definitions/327974719`、描述已改为 v0.6 口径。
- `PlanNotification.kind` 已扩到 5 个枚举值；`NextStep.live` 指向 `LiveState`。

### 9.5 后续约定

- 联调通过后由负责人把第 1、3、6、10、13 号接口手动转 `testing`，不批量刷状态。
- `RoomOverviewV05` 保留一个迭代（前端迁移期），迁完删除，届时模型数回落 91。
- 复盘、模板类接口（17–20）在 1 月才联调，状态保持 `developing` 即可。


## 10. 待团队确认

1. 主题是否允许在已有生效版本后切换（现方案：409，走 `replan-jobs`）。
2. 标签是全局账户级，还是按房间单独填（现方案：账户级 + 房间内可见性）。
3. 流体云首发做几个场景（建议 2 个：集合倒计时、待确认）。
4. 复盘是否进 P0（现方案：P1，Demo 只读）。
5. 是否接入 OPPO 账号一键登录（影响 M1 与设备注册）。
