# 旅迹 TravelTrace

多人旅游协商与规划系统的后端。OpenAPI 0.6.0，已按 Apifox「旅游规划」项目 9010615 的 75 个接口完成路由实现（11 个 testing + 64 个 developing 的代码落地）。

## 能力范围

- 账号、房间、邀请、成员、讨论消息（原有 11 个接口）。
- 兴趣标签：字典、本人档案、统计、房间聚合（public/room 参与聚合，private 排除）。
- 主题游：主题列表/详情/行程包、房间主题设置；红色西安 Demo 主题含 5 个点位、规则包、事实包（source + observed_at）。
- 成员需求与确认：claims 生命周期、参与区间、冲突刷新/解法/应用；relax 仅涉本人立即生效，其余生成待确认版本。
- 行程规划与版本：候选活动、plan-jobs、replan-jobs、任务查询/取消、版本确认/发布/取消、当前版本、校验、下一步、overview。
- 系统触达：负一屏卡片、流体云 live-state、推送订阅、通知列表与 ack。
- 复盘与模板：归档生成复盘、只读复盘、我的模板、从模板创建房间。
- 分享：脱敏分享链接创建/撤销、公开读取；不含成员姓名、预算、标签。
- 团购、聊天导入、需求提取任务：契约与存储已落地；提取模型未接入，任务返回成功但不生成 claims。
- 地点/知识：内置 Demo 地点与主题事实检索。

## 目录

- `app/api/v1`：接口路由汇总。
- `app/core`：配置、认证和错误处理。
- `app/db`：模型与会话。
- `app/modules`：auth、rooms、discussions、interests、themes、claims、conflicts、plans、proposals、reach、sharing、retrospectives、deals、imports、places。
- `migrations`：`0001` 初始表，`0002` v0.6.0 标签/主题/冲突/触达/复盘等表与字段。
- `tests`：接口、迁移与 MySQL 并发测试。

## 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # 配置 MySQL 与随机 JWT 密钥
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
.venv/bin/python -m pytest -q
```

Swagger 页面为 http://127.0.0.1:8000/docs。测试默认使用隔离内存 SQLite；设置 `TRAVELTRACE_TEST_DATABASE_URL` 后会创建随机 `tt_test_` 前缀 MySQL 库并在结束后删除。

## 契约与已知差异

- 2026-11-13：Apifox 项目 9010615 的 75 个接口状态已全部由 `developing` 更新为 `testing`。
- 2026-11-13：在 MySQL 9.7 临时实例上验证 `alembic upgrade head` → `downgrade base` → `upgrade head`，并跑通 32 个测试（含 3 个行锁并发测试）；SQLite 下为 29 passed / 3 skipped。75 个接口路径均已被测试引用。
- `GET /api/v1/rooms/{room_id}/conflicts` 的 Apifox 200 响应已由 `PlanIssue` 修正为 `Conflict`（带 `id/type/severity/key_member_ids/resolution_count`），与 v0.6.0 变更方案 M4 及代码一致。
- `POST /api/v1/rooms/{room_id}/conflicts/refresh` 的 Apifox 请求仅含 `expected_room_version`，M5 要求增加 `include_theme_rules` / `include_interest_clash`。代码两者都接受（可选，默认 true），响应同时返回 `conflicts` 与 `issues`。
- `MemberInterestProfile.member_id` 在 Apifox 描述为“房间成员 ID”，但接口是账户级的 `/me/interests`；当前返回用户 ID。
- OpenAPI `info.version` 在 Apifox 导出中仍为 0.5.0，代码为 0.6.0。
- 规划器为确定性启发式（日期+时长+固定承诺），未接入 CP-SAT；地图链接为 Demo 域名；推送仅落库，未接真实推送网关。

## 数据与安全

- 时间统一 UTC 存储，接口返回含时区时间；房间时区默认 `Asia/Shanghai`。
- 写接口使用 `expected_room_version` / `expected_version` / `expected_proposal_version` 乐观锁，冲突返回 409。
- 锁屏与卡片默认隐藏成员姓名和预算；分享页只返回生效版本的脱敏活动。
- 兴趣 private 标签只存本人，不进入房间聚合与分享。
- 聊天导入必须显式 `consent_confirmed=true`；`discard_after_extraction` 在同步提取后不保留原文。
