# 旅迹 TravelTrace

多人旅游协商与规划系统的后端项目。客户端在独立仓库开发。

计划使用 Python、FastAPI、DeepSeek API、LangGraph 和约束优化。已实现第一阶段账号、房间、邀请码与分页消息接口。其他规划和 AI 接口仍为待实现设计。

## 目录

- app/api/v1：接口路由汇总。
- app/core：配置、认证和错误处理。
- app/db：数据库基础能力。
- app/modules：账号、房间、讨论、需求、协商、地点、规划、行程、团购和知识模块。
- app/ai：Agent、工作流、工具与检索。
- app/integrations：模型和地图等外部服务适配。
- migrations：数据库迁移。
- tests：单元、接口和集成测试。
- data：种子数据与测试样例，private 内容不提交。
- storage：本地运行产物，不提交。

需求见《设计方案.md》，接口设计见 Apifox「旅游规划」项目。空目录通过 `.gitkeep` 保留。

## 协作流程

讨论 → 本人确认需求 → 冲突提案与投票 → 记录决定 → 生成候选行程 → 校验与全员确认 → 房主发布。需求或成员变化后旧候选与批准失效。客户端在独立项目中开发。接口契约当前为 OpenAPI 0.4.0，Apifox 状态保持开发中。


## 本地运行

使用 Conda 项目环境（Windows）：

```powershell
conda activate D:\TravelTrace\.conda
pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，配置你自己的 MySQL 连接（MySQL 8.0+，InnoDB、utf8mb4）和随机 JWT 密钥。不要提交 `.env`。随后在项目根目录执行：

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
python -m pytest -q
```

Swagger 页面为 http://127.0.0.1:8000/docs。默认测试使用隔离内存 SQLite，只验证接口与业务流程，不代替 MySQL 并发测试。设置 `TRAVELTRACE_TEST_DATABASE_URL` 后，测试会创建随机 `tt_test_` 前缀数据库，结束后删除该临时库，不使用已有业务表；测试账号须有建库与删库权限，仅连接专用测试实例。

用户名为 3～32 位英文、数字或下划线，大小写归一；密码为 8～128 位。每个账号自行注册；创建房间时必须填写目的地和起止日期，房主自动成为成员，房间最多六人。邀请码由房主生成，默认有效期 24 小时；消息采用 after/limit 游标分页轮询。重复加入返回已有成员，不重复增加房间版本。生产环境需提供 HTTPS，并在公开服务入口配置登录限流。

当前数据库方案为 MySQL，使用 PyMySQL 驱动；事务隔离级别为 READ COMMITTED，时间统一按 UTC 存储，接口返回带时区时间。迁移版本为 0001。2026-11-06 离线测试 13 项通过，3 项真实数据库并发测试待数据库服务启动后验证；MySQL 真库迁移尚未执行。原 PostgreSQL 数据不自动搬迁或删除。

排障：修改 `.env` 后须手动重启服务，`--reload` 不负责重载该配置文件。数据库连接及连接池等待默认各限制为 5 秒，网络读写等待各限制为 8 秒、InnoDB 锁等待限制为 3 秒（网络超时不等同于服务端 SQL 执行超时）；数据库不可用时返回带 request_id 的 503 DATABASE_UNAVAILABLE，不输出凭证。开发启动可使用 `python -m uvicorn app.main:create_app --factory --reload --reload-dir app`，避免扫描项目环境目录。
