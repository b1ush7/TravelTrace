# 旅迹 TravelTrace

多人旅游协商与规划系统的后端项目。客户端在独立仓库开发。

计划使用 Python、FastAPI、DeepSeek API、LangGraph 和约束优化。当前仅完成目录规划，尚未实现服务或安装依赖。

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

需求见《设计方案.md》，接口设计见 Apifox「旅游规划」项目。空目录仅保留在本地，随着实际代码加入后纳入版本管理。
