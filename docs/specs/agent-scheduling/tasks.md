# L6 智能排班任务拆解

关联规格：[spec.md](./spec.md)  
验收报告：[acceptance.md](./acceptance.md)  
状态：已完成（2026-11-11，验收复验 2026-11-13）

## 阶段 1：数据层

- [x] T1 实现前重新运行 `cd apps/api && uv run alembic heads`，确认迁移基点。
- [x] T2 新增 `scheduling` 包与 `models.py` 四个模型、约束和索引。
- [x] T3 新增迁移，包含 PostgreSQL/SQLite 部分唯一索引与完整 downgrade。
- [x] T4 在真实 PostgreSQL 执行升级，检查 head、表、索引、旧数据保留。

## 阶段 2：服务层

- [x] T5 新增 `schemas.py`，覆盖班次、班表、条目、策略与当班状态。
- [x] T6 实现班次创建、列表、修改、停用与版本/重名/引用检查。
- [x] T7 实现周草稿获取或创建、整体保存、乐观锁和相同内容重试。
- [x] T8 实现 IANA 时区、UTC 换算、跨天和快照；完整校验坐席与日期。
- [x] T9 实现发布、旧发布稿归档、克隆修订、空班表与状态保护。
- [x] T10 实现策略读取/更新、当前周就绪检查和当班候选批量查询。

## 阶段 3：派班与接口

- [x] T11 新增 `router.py`，注册全部接口、`service.admin`、租户检查和审计。
- [x] T12 在 `main.py` 注册 scheduling router。
- [x] T13 改造 `CustomerConversationService.auto_assign` 接入分业务单元当班约束。
- [x] T14 扩展候选解释，保留旧响应兼容；确认手工分配和接管不受影响。
- [x] T15 增加 AgentPresence 确定性行锁和锁内负载重算，防止并发超容量。
- [x] T16 验证既有 10 秒 Celery 自动分配任务，无需新增 beat。

## 阶段 4：前端

- [x] T17 在 `api.ts` / `types.ts` 增加排班请求函数和类型。
- [x] T18 新增 `SchedulingPage.tsx`：周切换、班次、班表网格、当班与缺口。
- [x] T19 实现保存、发布、克隆、策略开关的确认、loading、错误与自动刷新。
- [x] T20 修改 `App.tsx` 和 `capabilities.ts`，增加新入口并保持旧路由。

## 阶段 5：测试

- [x] T21 新增 `test_agent_scheduling.py`，覆盖验收矩阵 1–8、11–19、22；补强 DST
  不存在/歧义时间、无当前周发布稿不回退、分业务单元策略隔离 3 个用例。
- [x] T22 扩充既有自动分配回归，证明默认关闭时旧行为完全兼容。
- [x] T23 新增 `test_agent_scheduling_pg.py`，覆盖真实 PG 并发发布、唯一约束和派班容量。
- [x] T24 更新 SQLite 迁移测试，覆盖新迁移 upgrade/downgrade。
- [x] T25 浏览器验证新页面直达、旧入口、全部按钮反馈、冲突提示和自动刷新。

## 阶段 6：完整验收与记录

- [x] T26 运行专项测试、全量 pytest、Ruff、mypy、TypeScript、Vite production build。
- [x] T27 运行真实 PG 迁移检查、`make migrate-check`、`make stack-smoke`。
- [x] T28 用真实服务和临时业务单元完成矩阵全链路验收并清理数据。
- [x] T29 更新 `outputs/07_开发日志.md` 和 `outputs/06_当前实施状态.md`。
- [x] T30 更新 `docs/features.md` 与相关 README（如涉及），逐项核对本任务清单。

## 完成定义

- 验收矩阵 22 项均有真实执行记录，允许与拒绝路径均验证。
- 并发发布与并发派班在真实 PostgreSQL 通过，无重复分配、无超容量。
- 默认关闭策略时旧派班行为兼容；已发布班表和快照不可变。
- 所有规定检查与全栈 Smoke 通过，临时验收数据清理完毕。
- 最终回复列明正常/异常路径、真实验收数据、外部依赖未验收项和剩余风险。
